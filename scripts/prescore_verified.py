#!/usr/bin/env python3
"""Score the already-verified companies while discovery is still running.

Scoring is the long pole: a 200-company market spends hours there, and none
of it can start until discovery and verify finish. But the companies that
have ALREADY passed verification will not change -- discovery only adds new
ones. So their scores can be earned now, in parallel, on a separate browser
profile.

The results go into the checkpoint's parameter-detail cache under the same
keys the pipeline uses, so when the normal run reaches scoring it finds them
already done and only scores what is genuinely new.

Runs on its own GOOGLE_AI_MODE_PROFILE_DIR so it never contends with the
discovery browser for a profile lock.

    .\\.venv\\Scripts\\python.exe scripts\\prescore_verified.py ^
        --market "Advanced Seismic Data Processing Solutions Market" ^
        --country global --slot 9
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

# Company names carry Polish, Estonian and other diacritics that crash the
# Windows console's default codepage mid-run (confirmed live: killed a
# shard printing "Geofizyka Toruń").
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _row_name(r: dict) -> str:
    """Company name, whichever shape the row is in.

    Rows produced by the AI Mode discovery sweep carry the pipeline's
    PascalCase keys (Company/Headquarters); rows merged in from an
    operator-supplied list carry lowercase ones (company/headquarters).
    Reading only "Company" silently dropped every operator-supplied row --
    264 of 339 verified companies went unscored because their name resolved
    to an empty string.
    """
    return str(r.get("Company") or r.get("company") or r.get("name") or "").strip()


def _row_hq(r: dict) -> str:
    return str(r.get("Headquarters") or r.get("headquarters") or "").strip()


def _row_summary(r: dict) -> str:
    return str(
        r.get("Summary") or r.get("snippet") or r.get("why_related") or ""
    ).strip()


def _scope_for(market: str) -> str:
    for path in sorted((ROOT / "queries").glob("*.tsv")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            name, _, scope = line.partition("\t")
            if name.strip().lower() == market.strip().lower():
                return " ".join(scope.split())
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--market", required=True)
    ap.add_argument("--country", default="global")
    ap.add_argument(
        "--slot", type=int, default=9,
        help="browser profile slot; must differ from the running discovery",
    )
    ap.add_argument("--batch", type=int, default=5)
    ap.add_argument(
        "--only-file", default="",
        help="path to a JSON list of company names; restricts scoring to "
             "just these (e.g. top20_names.json), instead of every "
             "verified company",
    )
    ap.add_argument(
        "--shard", type=int, default=0,
        help="this instance's shard index (0-based), for splitting the "
             "company list across several browsers",
    )
    ap.add_argument(
        "--shards", type=int, default=1,
        help="total number of shards. Fixed slice by position, so shards "
             "can run concurrently and never overlap.",
    )
    ap.add_argument(
        "--sidecar-name", default="",
        help="explicit sidecar filename (e.g. 'straggler_a'), instead of "
             "the shard-index-derived one. Use this for an ad-hoc retry run "
             "against a --only-file list -- the shard-index name would "
             "otherwise collide with an EARLIER unrelated run's shard0/1/2 "
             "files and overwrite already-good companies.",
    )
    ap.add_argument(
        "--fixed-axes", default="",
        help="path to a JSON spec ({market, axis_x, axis_y, x, y, "
             "parameter_definitions}) with OPERATOR-AUTHORED scoring "
             "parameters. Skips select_industry/define_market_axes (and its "
             "LLM call) entirely -- use this when the parameters and their "
             "definitions were given directly rather than generated.",
    )
    ap.add_argument(
        "--skip-batch", action="store_true",
        help="go straight to the small-group fallback instead of trying "
             "the 5-in-1 axis query first -- for a --only-file list of "
             "known stragglers that have already failed the batch query "
             "across several runs, so there is no point paying for it "
             "again.",
    )
    ap.add_argument(
        "--group-size", type=int, default=2,
        help="parameters per fallback query (default 2). Use 1 for the "
             "most reliable, slowest path on persistent stragglers that "
             "even the group-of-2 fallback missed.",
    )
    args = ap.parse_args()

    profile = ROOT / "data" / f"ai_mode_batch_{args.slot:02d}"
    os.environ["GOOGLE_AI_MODE_PROFILE_DIR"] = str(profile)
    os.environ["GOOGLE_AI_MODE_BROWSER"] = "chromium"
    os.environ["GOOGLE_AI_MODE_ENABLED"] = "true"
    os.environ["AI_MODE_PARAM_BATCH"] = str(args.batch)
    scope = _scope_for(args.market)
    if scope:
        os.environ["MARKET_SCOPE"] = scope

    from vendor_intel.config import Settings
    from vendor_intel.pipeline.web_expand import default_output_dir
    from vendor_intel.quadrant import ai_mode_scorer
    from vendor_intel.quadrant.axis_define import define_market_axes
    from vendor_intel.quadrant.industry_select import select_industry

    out_dir = Path(default_output_dir(args.market, args.country))
    ckpt_path = out_dir / "chatgpt_checkpoint_batch_all.json"
    if not ckpt_path.exists():
        print(f"ERROR: no checkpoint at {ckpt_path}", file=sys.stderr)
        return 2

    state = json.loads(ckpt_path.read_text(encoding="utf-8"))
    data = state.get("data") or {}
    verified = data.get("verified") or []
    if not verified:
        print("nothing verified yet — run verification first")
        return 1

    if args.only_file:
        only = set(json.loads(Path(args.only_file).read_text(encoding="utf-8")))
        verified = [
            r for r in verified
            if _row_name(r) in only
        ]
        print(f"restricted to {len(verified)} companies from {args.only_file}")

    # De-dupe by company name BEFORE sharding: a company with several
    # verified product rows must land in exactly one shard, or two browsers
    # would both score it (wasted queries) or a shard boundary could split
    # its rows across two processes writing to two different sidecars.
    by_company: dict[str, dict] = {}
    for r in verified:
        name = _row_name(r)
        if name and name not in by_company:
            by_company[name] = r
    verified = list(by_company.values())

    if args.shards > 1:
        # Fixed slice by position, not a hash: every shard's boundaries are
        # deterministic from the SAME deduped list, so two shards can never
        # both claim a company even if launched slightly out of sync.
        verified = verified[args.shard::args.shards]
        print(f"shard {args.shard}/{args.shards}: {len(verified)} companies")

    # Sidecar, NOT the checkpoint. Both this process and the pipeline would
    # otherwise write the same file with a non-atomic write_text: the
    # pipeline holds the whole state in memory and rewrites it, so it would
    # silently drop everything scored here, and an interleaved write can
    # leave a truncated file. The pipeline merges this sidecar at scoring.
    # One sidecar per shard: several processes doing a non-atomic
    # read-modify-write on the SAME file would silently drop whichever
    # write lost the race. Merged after every shard is done.
    if args.sidecar_name:
        side_path = out_dir / f"param_detail_prescored_{args.sidecar_name}.json"
    else:
        suffix = f"_shard{args.shard}" if args.shards > 1 else ""
        side_path = out_dir / f"param_detail_prescored{suffix}.json"
    done: dict = {}
    if side_path.exists():
        try:
            done = json.loads(side_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - a half-written sidecar restarts clean
            done = {}
    done.update(data.get("param_detail") or {})
    names = [
        _row_name(r) for r in verified
    ]
    names = [n for n in names if n and n not in done]
    if not names:
        print(f"all {len(verified)} verified companies already scored")
        return 0

    # Resolve the axes exactly as the pipeline does, so the parameters this
    # pass scores are the same ones the real scoring step will expect. A
    # different parameter list would make the cache unusable. An operator-
    # authored --fixed-axes spec skips the LLM entirely: those 10 parameters
    # ARE the criteria, not a baseline for the model to refine.
    settings = Settings.load()
    if args.fixed_axes:
        industry = json.loads(Path(args.fixed_axes).read_text(encoding="utf-8"))
    else:
        industry = select_industry(args.market, geography=args.country, settings=settings)
        industry = define_market_axes(
            args.market, industry, geography=args.country, settings=settings
        )
    x_feats = list(industry.get("x") or [])
    y_feats = list(industry.get("y") or [])
    if not x_feats or not y_feats:
        print("ERROR: could not resolve axis parameters", file=sys.stderr)
        return 2

    # An operator-authored spec carries a "what it measures" sentence per
    # parameter and its own axis titles. Passing them through makes the
    # scorer judge each parameter against THAT stated measure and record
    # which parts of it were actually verified, instead of scoring a bare
    # parameter name however the model happens to read it.
    _defs = industry.get("parameter_definitions") or {}
    x_defs = dict(_defs.get("x") or {}) if isinstance(_defs, dict) else {}
    y_defs = dict(_defs.get("y") or {}) if isinstance(_defs, dict) else {}
    market_definition = str(industry.get("market_definition") or "")
    axis_x_label = str(industry.get("axis_x") or ai_mode_scorer.AXIS_X_LABEL)
    axis_y_label = str(industry.get("axis_y") or ai_mode_scorer.AXIS_Y_LABEL)

    print(f"pre-scoring {len(names)} verified companies on slot {args.slot}")
    print(f"  already done : {len(done)}")
    print(f"  X axis       : {axis_x_label}")
    print(f"  Y axis       : {axis_y_label}")
    print(f"  X parameters : {', '.join(x_feats[:3])}...")
    print(f"  Y parameters : {', '.join(y_feats[:3])}...")
    print(f"  definitions  : {len(x_defs)} X, {len(y_defs)} Y")

    ctx = {_row_name(r): _row_summary(r)[:200] for r in verified}
    hqs = {_row_name(r): _row_hq(r) for r in verified}

    started = time.monotonic()

    def _write_sidecar(merged: dict) -> None:
        """Write via a temp file and rename: a reader must never see a
        half-written sidecar.

        The rename is retried a few times: on Windows another process (an
        antivirus scan, a search indexer) briefly holding the file handle
        raises PermissionError on os.replace(), and this run crashed on
        exactly that — after 5 companies had already been safely written in
        an EARLIER call, only this one rename failed. A transient lock does
        not need the whole shard to die.
        """
        tmp = side_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")
        for attempt in range(5):
            try:
                os.replace(tmp, side_path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.5 * (attempt + 1))

    def _save(start: int, chunk: list[str], out: dict) -> None:
        """Persist after every batch: this runs for hours and must survive
        an interruption without re-asking for what it already has.

        Mutates `done` IN PLACE. The callback now fires once per company
        (see ai_mode_scorer.score_parameters_for_companies), and rebuilding
        from the original `done` snapshot on every call -- instead of
        accumulating into it -- meant each save overwrote the sidecar with
        only that one company, discarding every company saved before it.
        """
        done.update(out)
        _write_sidecar(done)
        mins = (time.monotonic() - started) / 60
        print(f"  saved {len(done)} companies total ({mins:.0f}m elapsed)",
              flush=True)

    def _has_both_axes(record: dict) -> bool:
        """True only when a saved entry carries REAL parameter detail.

        score_parameters_for_companies() always sets out[name] = record, even
        when both axes failed to parse -- the record just has empty
        "parameters" dicts. `done.update(got)` below then adds that empty
        record under the company's own name, so a plain `name in done`
        check reads as "already have it" and the retry pass never fires.
        Confirmed live: two shards finished at 6/7 and 5/7 with zero retry
        attempts logged.
        """
        return bool(
            (record.get("x") or {}).get("parameters")
            and (record.get("y") or {}).get("parameters")
        )

    got = ai_mode_scorer.score_parameters_for_companies(
        names,
        x_parameters=x_feats,
        y_parameters=y_feats,
        market=args.market,
        context_by_company=ctx,
        hq_by_company=hqs,
        batch=args.batch,
        on_batch=_save,
        x_definitions=x_defs,
        y_definitions=y_defs,
        market_definition=market_definition,
        x_axis_label=axis_x_label,
        y_axis_label=axis_y_label,
        skip_batch=args.skip_batch,
        group_size=args.group_size,
    )
    for name, record in got.items():
        if _has_both_axes(record):
            done[name] = record

    # A single-company query occasionally comes back as a prose summary
    # instead of the required numbered "Evidence: / Score:" layout -- the
    # parser correctly rejects it, but score_parameters_for_companies has NO
    # retry of its own once that happens: the company is silently skipped
    # for the rest of THIS run. Confirmed live (Petrosys twice in a row).
    # Give every gap up to 2 more single-shot attempts before giving up.
    for attempt in range(1, 3):
        missing = [
            n for n in names
            if n not in done or not _has_both_axes(done[n])
        ]
        if not missing:
            break
        print(f"\nretry pass {attempt}: {len(missing)} companies never "
              f"parsed a valid reply -- asking again", flush=True)
        retried = ai_mode_scorer.score_parameters_for_companies(
            missing,
            x_parameters=x_feats,
            y_parameters=y_feats,
            market=args.market,
            context_by_company=ctx,
            hq_by_company=hqs,
            batch=1,  # one at a time: these already failed a batched ask
            on_batch=_save,
            x_definitions=x_defs,
            y_definitions=y_defs,
            market_definition=market_definition,
            x_axis_label=axis_x_label,
            y_axis_label=axis_y_label,
            # Already failed the 5-in-1 once this run -- go straight to the
            # fallback instead of paying for a repeat of the same failure.
            skip_batch=bool(x_defs or y_defs),
            group_size=args.group_size,
        )
        for name, record in retried.items():
            if _has_both_axes(record):
                done[name] = record

    _write_sidecar(done)

    scored = sum(1 for v in done.values() if (v.get("x") or {}).get("parameters"))
    still_missing = [
        n for n in names if n not in done or not _has_both_axes(done[n])
    ]
    print(f"\ndone: {scored}/{len(done)} companies carry parameter detail")
    if still_missing:
        print(f"WARNING: {len(still_missing)} companies never parsed after "
              f"retries: {still_missing}")
    print(f"elapsed {(time.monotonic() - started) / 60:.0f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
