#!/usr/bin/env python3
"""One command, any market: discovery -> dedupe -> scoring -> report -> verify.

Chains every step the Marine Seismic and Wearable Glucometer reports went
through, with nothing specific to either market:

  1. Discovery      run_chatgpt_expand.py, only if the market has no
                    verified companies yet. With --keep N: discover a batch,
                    verify, discover more, verify ... (discover_verify_rounds.py)
                    until N verified companies exist after dedupe; the report
                    then keeps the best N by score.
  2. Axes spec      the market's own X/Y axes + 10 parameter definitions
                    (--fixed-axes, else the checkpoint's xy_audit, else
                    generated) -> _pipeline/axes_spec.json. Every later step
                    scores against this one file.
  3. Dedupe         one row per real company (shared website domain or the
                    same name minus legal suffixes).
  4. Overall-only   score_overall_only.py for every company that has no
                    score yet -- ranks the pool and feeds the Strength
                    bubbles of the long tail. No evidence stored.
  5. Evidence pool  the top --top-n companies by that score (or a list you
                    pin with --top-list) get full per-parameter evidence.
  6. Evidence       prescore_verified.py (1 parameter per query), then up to
                    --max-rounds of gap fill: fill_missing_parameters.py for
                    missing scores, fill_missing_assessed_on.py for scores
                    with no "why" reasoning.
  7. Composite      seed_from_full_evidence.py -- X/Y/Overall with the
                    65-100 floor; 5 per quadrant when the evidence pool IS
                    the Top N.
  8. Tone           rewrite_assessed_on_tone.py (desk-research wording, "we").
  9. Report         build_report_from_composite.py (HTML + JSON + CSV).
 10. Verify         completeness, 5/5/5/5, X/Y = mean of parameters, no
                    hedge wording, no numbers in Other Noticeable Player.

Every step is resumable: re-running skips work that is already saved.

    .\\.venv\\Scripts\\python.exe scripts\\run_quadrant_pipeline.py ^
        --market "Global Wearable Glucometer Market" --country global ^
        --slots 41-50

    # see what would run, without opening a browser
    ... --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from vendor_intel.pipeline.quadrant_pipeline import (  # noqa: E402
    dedupe_companies,
    evidence_gaps,
    load_evidence,
    load_overall_only,
    rank_score,
    row_name,
)
from vendor_intel.pipeline.web_expand import default_output_dir  # noqa: E402

PY = sys.executable
_HEDGE_RE = re.compile(
    r"could not verify|not publicly (?:disclosed|accessible|available)|"
    r"no public (?:records?|evidence|data)|\bI (?:verified|found|searched|confirmed|could)\b",
    re.I,
)


def log(msg: str) -> None:
    print(f"[pipeline {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def parse_slots(text: str) -> list[int]:
    slots: list[int] = []
    for part in str(text).split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            slots.extend(range(int(a), int(b) + 1))
        elif part:
            slots.append(int(part))
    return slots


def write_json(path: Path, obj) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


class Runner:
    def __init__(self, args, out_dir: Path, pipe_dir: Path, spec_path: Path):
        self.args = args
        self.out_dir = out_dir
        self.pipe_dir = pipe_dir
        self.spec_path = spec_path
        self.slots = parse_slots(args.slots)
        self.log_dir = pipe_dir / "logs"

    def run(self, cmd: list[str], log_name: str, env: dict | None = None) -> int:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        with (self.log_dir / log_name).open("w", encoding="utf-8") as fh:
            return subprocess.call(cmd, cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT,
                                   env={**os.environ, "PYTHONIOENCODING": "utf-8", **(env or {})})

    def shards(self, step: str, script: str, names: list[str], extra: list[str],
               per_shard=None) -> None:
        """Run `script` over `names`, one shard per browser slot, and wait."""
        if not names:
            return
        names_path = write_json(self.pipe_dir / f"{step}_names.json", names)
        n = max(1, min(len(self.slots), len(names)))
        log(f"{step}: {len(names)} companies across {n} browser(s)")
        if self.args.dry_run:
            return
        self.log_dir.mkdir(parents=True, exist_ok=True)
        procs = []
        for i in range(n):
            cmd = [PY, str(ROOT / "scripts" / script),
                   "--market", self.args.market, "--country", self.args.country,
                   "--slot", str(self.slots[i]), "--shard", str(i), "--shards", str(n),
                   "--only-file", str(names_path), *extra,
                   *(per_shard(i) if per_shard else [])]
            fh = (self.log_dir / f"{step}_shard{i}.log").open("w", encoding="utf-8")
            procs.append((subprocess.Popen(
                cmd, cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"}), fh))
            time.sleep(2)
        try:
            while True:
                alive = sum(1 for p, _ in procs if p.poll() is None)
                if not alive:
                    break
                log(f"{step}: {alive}/{n} shard(s) still running")
                time.sleep(60)
        except KeyboardInterrupt:
            for p, _ in procs:
                p.terminate()
            raise
        finally:
            for _, fh in procs:
                fh.close()
        bad = [i for i, (p, _) in enumerate(procs) if p.returncode not in (0, None)]
        if bad:
            log(f"{step}: shard(s) {bad} exited with an error -- see {self.log_dir}")


def resolve_spec(args, data: dict, spec_path: Path) -> dict:
    """The market's axes spec, written once and reused by every step."""
    from vendor_intel.quadrant.axis_define import AXIS_X_FIXED, AXIS_Y_FIXED, PARAMS_PER_AXIS

    def _five_each(sp: dict) -> bool:
        return (len(sp.get("x") or []) == PARAMS_PER_AXIS
                and len(sp.get("y") or []) == PARAMS_PER_AXIS)

    if args.fixed_axes:
        spec = read_json(Path(args.fixed_axes))
    elif spec_path.exists():
        spec = read_json(spec_path)
        # Axis NAMES are fixed for every market; an older spec may still carry
        # a market-specific title -- restate it, the parameters stay as-is.
        if (spec.get("axis_x"), spec.get("axis_y")) != (AXIS_X_FIXED, AXIS_Y_FIXED):
            spec["axis_x"], spec["axis_y"] = AXIS_X_FIXED, AXIS_Y_FIXED
            write_json(spec_path, spec)
        if not _five_each(spec):
            raise SystemExit(
                f"{spec_path} has {len(spec.get('x') or [])} X / {len(spec.get('y') or [])} Y "
                f"parameters; exactly {PARAMS_PER_AXIS} per axis are required. "
                "Delete the file to regenerate the axes."
            )
        return spec
    else:
        audit = data.get("xy_audit") or {}
        if (len(audit.get("x_features") or []) == PARAMS_PER_AXIS
                and len(audit.get("y_features") or []) == PARAMS_PER_AXIS):
            spec = {
                "x": list(audit["x_features"]),
                "y": list(audit["y_features"]),
                "parameter_definitions": audit.get("parameter_definitions") or {"x": {}, "y": {}},
            }
        else:
            from vendor_intel.config import Settings
            from vendor_intel.quadrant.axis_define import define_market_axes
            from vendor_intel.quadrant.industry_select import select_industry

            settings = Settings.load()
            industry = select_industry(args.market, geography=args.country, settings=settings)
            industry = define_market_axes(args.market, industry, geography=args.country,
                                          settings=settings)
            spec = {
                "x": list(industry.get("x") or []),
                "y": list(industry.get("y") or []),
                "parameter_definitions": industry.get("parameter_definitions") or {"x": {}, "y": {}},
            }
    # X = Product Capability, Y = Business Capability for EVERY market (stored
    # under the internal keys scoring uses); only the parameters vary.
    spec["axis_x"], spec["axis_y"] = AXIS_X_FIXED, AXIS_Y_FIXED
    if not _five_each(spec):
        raise SystemExit(
            f"axes have {len(spec.get('x') or [])} X / {len(spec.get('y') or [])} Y parameters; "
            f"exactly {PARAMS_PER_AXIS} per axis are required"
        )
    defs = spec.setdefault("parameter_definitions", {"x": {}, "y": {}})
    miss_x = [p for p in spec["x"] if not str(defs.get("x", {}).get(p) or "").strip()]
    miss_y = [p for p in spec["y"] if not str(defs.get("y", {}).get(p) or "").strip()]
    if miss_x or miss_y:
        from vendor_intel.config import Settings
        from vendor_intel.quadrant.axis_define import explain_market_parameters

        fresh = explain_market_parameters(
            args.market, miss_x, miss_y, axis_x=spec["axis_x"], axis_y=spec["axis_y"],
            geography=args.country, settings=Settings.load(),
        )
        defs.setdefault("x", {}).update({k: v for k, v in (fresh.get("x") or {}).items() if v})
        defs.setdefault("y", {}).update({k: v for k, v in (fresh.get("y") or {}).items() if v})
    ma = data.get("market_analysis") or {}
    spec["market"] = args.market
    spec["market_definition"] = str(spec.get("market_definition") or ma.get("market_definition") or "")
    write_json(spec_path, spec)
    return spec


def verify(out_dir: Path, spec: dict, top_n: int, keep: int = 0) -> bool:
    slug = out_dir.name
    payload = read_json(out_dir / f"{slug}_quadrant.json", {})
    html = (out_dir / f"{slug}_report.html").read_text(encoding="utf-8")
    brands = payload.get("brands") or []
    xp, yp = spec["x"], spec["y"]
    chart = [b for b in brands if b.get("on_chart")]
    checks: list[tuple[str, bool, str]] = []

    from vendor_intel.quadrant.axis_define import PARAMS_PER_AXIS
    from vendor_intel.quadrant.quadrant_language import AXIS_X_TITLE, AXIS_Y_TITLE

    crit = payload.get("criteria") or {}
    n_x, n_y = len(crit.get("x_axis") or xp), len(crit.get("y_axis") or yp)
    checks.append((f"Exactly {PARAMS_PER_AXIS} parameters on X and on Y",
                   n_x == n_y == PARAMS_PER_AXIS == len(xp) == len(yp), f"X={n_x} Y={n_y}"))
    checks.append((f"Axes are {AXIS_X_TITLE} (X) / {AXIS_Y_TITLE} (Y)",
                   AXIS_X_TITLE in html and AXIS_Y_TITLE in html, ""))

    incomplete = []
    for b in chart:
        sd = b.get("score_detail") or {}
        for axis, params in (("x", xp), ("y", yp)):
            got = (sd.get(axis) or {}).get("parameters") or {}
            for p in params:
                v = got.get(p) or {}
                if not (v.get("score") is not None and v.get("evidence") and v.get("assessed_on")):
                    incomplete.append(f"{b.get('company')} / {p}")
    checks.append(("Top companies: score + evidence + reasoning for all 10 parameters",
                   not incomplete, f"{len(incomplete)} gap(s): {incomplete[:5]}"))

    split = Counter(b.get("quadrant") for b in chart)
    want_even = len(chart) == top_n and top_n % 4 == 0
    even = len(set(split.values())) == 1 and len(split) == 4
    if keep:
        checks.append((f"Report keeps {keep} companies", len(brands) == keep,
                       f"{len(brands)} in report"))
    checks.append((f"Chart has {top_n} companies", len(chart) == min(top_n, len(brands)),
                   f"{len(chart)} on chart"))
    checks.append(("Quadrant split even (5/5/5/5)", even or not want_even, dict(split)))

    mismatch = []
    for b in brands:
        sd = b.get("score_detail") or {}
        xs = [v.get("score") for v in ((sd.get("x") or {}).get("parameters") or {}).values()]
        ys = [v.get("score") for v in ((sd.get("y") or {}).get("parameters") or {}).values()]
        if xs and ys and None not in xs and None not in ys:
            if (int(b["execution"]) != round(sum(xs) / len(xs))
                    or int(b["innovation"]) != round(sum(ys) / len(ys))):
                mismatch.append(b.get("company"))
    checks.append(("X/Y = mean of their parameter scores", not mismatch, mismatch[:5]))

    hedges = _HEDGE_RE.findall(html)
    checks.append(("No hedge wording / first person in report", not hedges, hedges[:5]))

    a = html.find("Other Noticeable Player")
    tail_html = html[a: html.find("</table>", a)] if a >= 0 else ""
    # The Strength cell (last column) must carry no number -- neither as
    # visible text nor in its hover tooltip. Company names / HQs may contain
    # digits ("3M"), so only that cell is checked; CSS classes like
    # cq-sdot-7 are markup, not shown, so tags are stripped first.
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", tail_html, re.S)[1:]
    numeric: list[str] = []
    for r in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)
        cell = cells[-1] if cells else ""
        shown = re.sub(r"<[^>]+>", " ", cell) + " " + " ".join(re.findall(r'title="([^"]*)"', cell))
        numeric += re.findall(r"\d+", shown)
        if "title=" in cell:  # bubbles only -- no hover tooltip of any kind
            numeric.append("tooltip")
    checks.append(("Other Noticeable Player shows filled bubbles only (no numbers, no tooltip)",
                   not numeric and "cq-bub-num" not in tail_html and "Scored" not in tail_html,
                   numeric[:5]))
    dots = [r.count("cq-sdot-on") for r in rows]
    checks.append(("Other Noticeable Player sorted by Strength",
                   all(a >= b for a, b in zip(dots, dots[1:])), dots[:10]))

    no_hq = [b.get("company") for b in brands if not str(b.get("hq_location") or "").strip()]
    checks.append(("Every company has an HQ", not no_hq, f"{len(no_hq)} missing: {no_hq[:5]}"))

    low = [b.get("company") for b in brands
           if min(int(b.get("execution") or 0), int(b.get("innovation") or 0)) < 65]
    checks.append(("Every X/Y >= 65", not low, low[:5]))

    ok = True
    log("VERIFY")
    for name, passed, detail in checks:
        ok &= passed
        print(f"   [{'PASS' if passed else 'FAIL'}] {name}"
              + ("" if passed or not detail else f"  -> {detail}"), flush=True)
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", required=True)
    ap.add_argument("--country", default="global")
    ap.add_argument("--slots", default="41-50", help="browser profile slots, e.g. 41-50")
    ap.add_argument("--top-n", type=int, default=20, help="companies on the chart")
    ap.add_argument("--evidence-pool", type=int, default=0,
                    help="how many companies get full per-parameter evidence "
                         "(default: --top-n). Larger than --top-n = the chart "
                         "selector picks the Top N from that bigger pool.")
    ap.add_argument("--fixed-axes", default="", help="operator-authored axes spec JSON")
    ap.add_argument("--top-list", default="",
                    help="JSON list pinning the evidence pool instead of ranking")
    ap.add_argument("--chart-top", default="",
                    help="JSON list pinning the exact chart companies (manual swaps)")
    ap.add_argument("--reselect", action="store_true",
                    help="re-rank the evidence pool even if one was saved")
    ap.add_argument("--max-rounds", type=int, default=3, help="evidence gap-fill rounds")
    ap.add_argument("--keep", type=int, default=0,
                    help="companies kept in the final report AFTER verification + dedupe "
                         "(chart + Other Noticeable Player). Discovery runs in batches "
                         "-- discover, verify, discover more, verify -- until this many "
                         "verified companies exist; the best --keep by score are kept.")
    ap.add_argument("--discover-target", type=int, default=0,
                    help="first discovery batch size (default: --keep, else 400)")
    ap.add_argument("--max-discover-rounds", type=int, default=10,
                    help="discover -> verify top-up rounds when --keep is short")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, open no browser")
    args = ap.parse_args()
    if not args.discover_target:
        # With --keep, the first batch aims at the target itself; the
        # discover -> verify rounds below top it up until enough survive.
        args.discover_target = args.keep or 400
    if args.keep and args.keep < args.top_n:
        ap.error(f"--keep {args.keep} is smaller than --top-n {args.top_n}")

    out_dir = Path(default_output_dir(args.market, args.country))
    pipe_dir = out_dir / "_pipeline"
    spec_path = pipe_dir / "axes_spec.json"
    ckpt_path = out_dir / "chatgpt_checkpoint_batch_all.json"
    runner = Runner(args, out_dir, pipe_dir, spec_path)
    log(f"market: {args.market} ({args.country}) -> {out_dir}")

    # 1. Discovery -----------------------------------------------------------
    state = read_json(ckpt_path, {}) or {}
    if not (state.get("data") or {}).get("verified"):
        log("1. no verified companies yet -> running discovery (run_chatgpt_expand.py)")
        if args.dry_run:
            return 0
        slot = runner.slots[0]
        rc = runner.run(
            [PY, str(ROOT / "scripts" / "run_chatgpt_expand.py"), "--query", args.market,
             "--country", args.country, "--target", str(args.discover_target)],
            "discovery.log",
            env={"GOOGLE_AI_MODE_PROFILE_DIR": str(ROOT / "data" / f"ai_mode_batch_{slot:02d}"),
                 "GOOGLE_AI_MODE_BROWSER": "chromium", "GOOGLE_AI_MODE_ENABLED": "true"},
        )
        state = read_json(ckpt_path, {}) or {}
        if rc != 0 or not (state.get("data") or {}).get("verified"):
            log("discovery produced no verified companies -- see _pipeline/logs/discovery.log")
            return 2
    data = state["data"]
    verified = data.get("verified") or []
    if args.keep:
        have = len(dedupe_companies(verified)[0])
        if have < args.keep:
            log(f"1b. {have} verified companies after dedupe, need {args.keep} -> "
                "discover -> verify rounds")
            if args.dry_run:
                return 0
            runner.run(
                [PY, str(ROOT / "scripts" / "discover_verify_rounds.py"),
                 "--market", args.market, "--country", args.country,
                 "--keep", str(args.keep), "--slot", str(runner.slots[0]),
                 "--max-rounds", str(args.max_discover_rounds)],
                "discover_rounds.log",
            )
            state = read_json(ckpt_path, {}) or {}
            data = state["data"]
            verified = data.get("verified") or []
            log(f"1b. now {len(dedupe_companies(verified)[0])} verified companies after "
                "dedupe (see _pipeline/logs/discover_rounds.log)")
    log(f"1. verified rows: {len(verified)}")

    # 2. Axes spec -----------------------------------------------------------
    spec = resolve_spec(args, data, spec_path)
    xp, yp = spec["x"], spec["y"]
    from vendor_intel.quadrant.quadrant_language import AXIS_X_TITLE, AXIS_Y_TITLE

    log(f"2. axes: X={AXIS_X_TITLE} ({len(spec['x'])} params) "
        f"Y={AXIS_Y_TITLE} ({len(spec['y'])} params) -> {spec_path}")

    # 3. Dedupe --------------------------------------------------------------
    evidence = load_evidence(out_dir)
    complete = {n for n in evidence if not evidence_gaps(evidence, [n], xp, yp)}
    pool_path = pipe_dir / "evidence_pool.json"
    chart_path = Path(args.chart_top) if args.chart_top else pipe_dir / "chart_top.json"
    pinned = set(read_json(pool_path, []) or []) | set(read_json(chart_path, []) or [])
    # Prefer, as a group's representative, a name that already carries a
    # score, so a spelling variant ("... Inc" vs "... Inc.") never forces
    # the same company to be scored twice.
    tiers = {n: 2 for n in load_overall_only(out_dir)}
    tiers.update({n: 1 for n in pinned})
    tiers.update({n: 0 for n in complete})
    pool, groups = dedupe_companies(verified, prefer=tiers)
    rep_of = {m: rep for rep, ms in groups.items() for m in ms}
    merged = {rep: ms for rep, ms in groups.items() if len(ms) > 1}
    write_json(pipe_dir / "dedupe_groups.json", merged)
    log(f"3. {len({row_name(r) for r in verified})} names -> {len(pool)} companies "
        f"after dedupe ({len(merged)} groups merged)")

    # 4. Evidence pool (choose, or reuse) + Overall-only scores --------------
    size = args.evidence_pool or args.top_n
    if args.top_list:
        ev_pool = read_json(Path(args.top_list), [])
    elif pool_path.exists() and not args.reselect:
        # An empty saved pool (e.g. left by an interrupted run before any
        # company had a score) is re-ranked, never reused as "score nobody".
        ev_pool = read_json(pool_path, []) or None
    else:
        ev_pool = None
    overall = load_overall_only(out_dir)
    if ev_pool is None:
        need = [n for n in pool if rank_score(n, evidence, overall, xp, yp) is None]
    else:
        ev_pool = list(dict.fromkeys(rep_of.get(n, n) for n in ev_pool if rep_of.get(n, n) in pool))
        need = [n for n in pool if n not in ev_pool
                and rank_score(n, evidence, overall, xp, yp) is None]
    log(f"4. Overall-only scoring needed for {len(need)} companies")
    runner.shards("overall", "score_overall_only.py", need, ["--fixed-axes", str(spec_path)])
    overall = load_overall_only(out_dir)
    if ev_pool is None:
        ranked = sorted(
            (n for n in pool if rank_score(n, evidence, overall, xp, yp) is not None),
            key=lambda n: rank_score(n, evidence, overall, xp, yp), reverse=True,
        )
        ev_pool = ranked if size >= len(ranked) else ranked[:size]
    if args.dry_run:
        log(f"   evidence pool: {len(ev_pool)} companies"
            + (" (ranked after Overall-only scoring on a real run)" if not ev_pool else ""))
    else:
        write_json(pool_path, ev_pool)
        log(f"   evidence pool: {len(ev_pool)} companies -> {pool_path}")

    # 5. Evidence with reasoning, then gap-fill rounds -----------------------
    for rnd in range(1, args.max_rounds + 1):
        evidence = load_evidence(out_dir)
        gaps = evidence_gaps(evidence, ev_pool, xp, yp)
        if not gaps:
            break
        log(f"5. evidence round {rnd}: {len(gaps)} companies with gaps")
        fresh = [n for n in gaps if not (evidence.get(n) or {}).get("x")
                 and not (evidence.get(n) or {}).get("y")]
        runner.shards(f"evidence_r{rnd}", "prescore_verified.py", fresh,
                      ["--fixed-axes", str(spec_path), "--skip-batch", "--group-size", "1"],
                      per_shard=lambda i, r=rnd: ["--sidecar-name", f"pipe_r{r}_{i}"])
        evidence = load_evidence(out_dir)
        gaps = evidence_gaps(evidence, ev_pool, xp, yp)
        runner.shards(f"fillgap_r{rnd}", "fill_missing_parameters.py",
                      [n for n, g in gaps.items() if g["missing"]],
                      ["--fixed-axes", str(spec_path)])
        evidence = load_evidence(out_dir)
        gaps = evidence_gaps(evidence, ev_pool, xp, yp)
        runner.shards(f"reasoning_r{rnd}", "fill_missing_assessed_on.py",
                      [n for n, g in gaps.items() if g["no_reasoning"]],
                      ["--fixed-axes", str(spec_path)])
        if args.dry_run:
            break
    evidence = load_evidence(out_dir)
    left = evidence_gaps(evidence, ev_pool, xp, yp)
    done_ev = [n for n in ev_pool if n not in left]
    if left:
        log(f"   WARNING: {len(left)} companies still incomplete after "
            f"{args.max_rounds} rounds, left out of the evidence set: {list(left)[:8]}")
    ev_file = write_json(pipe_dir / "evidence_complete.json", done_ev)
    tail = [n for n in pool if n not in set(done_ev)]
    if args.keep:
        # Keep the best --keep companies after verification + dedupe: the
        # evidence set (chart) always stays, the long tail is filled by score.
        room = max(0, args.keep - len(done_ev))
        scored_tail = sorted(
            (n for n in tail if rank_score(n, evidence, overall, xp, yp) is not None),
            key=lambda n: rank_score(n, evidence, overall, xp, yp), reverse=True,
        )
        if len(done_ev) + len(scored_tail) < args.keep:
            log(f"   WARNING: only {len(done_ev) + len(scored_tail)} verified companies "
                f"after dedupe, fewer than --keep {args.keep}. Discovery has already "
                f"run for this market; re-run it with a larger --discover-target in a "
                f"fresh output folder to find more.")
        dropped = len(tail) - min(room, len(scored_tail))
        tail = scored_tail[:room]
        log(f"   --keep {args.keep}: {len(done_ev)} chart/evidence + {len(tail)} long tail "
            f"kept, {dropped} lower-scored dropped")
    tail_file = write_json(pipe_dir / "long_tail.json", tail)
    log(f"   {len(done_ev)} companies with full evidence, {len(tail)} in the long tail")
    if args.dry_run:
        log("dry run: stopping before composite / report")
        return 0

    # 6. Composite scores ----------------------------------------------------
    chart_top = [rep_of.get(n, n) for n in (read_json(chart_path, []) or [])]
    chart_top = [n for n in dict.fromkeys(chart_top) if n in done_ev]
    force_even = not chart_top and len(done_ev) <= args.top_n
    seed_cmd = [PY, str(ROOT / "scripts" / "seed_from_full_evidence.py"),
                "--market", args.market, "--country", args.country,
                "--include-legacy-scores", "--evidence-file", str(ev_file),
                "--long-tail-file", str(tail_file)]
    if force_even:
        seed_cmd.append("--force-even-quadrants")
    log(f"6. composite scores ({'5 per quadrant' if force_even else 'cohort median'})")
    if runner.run(seed_cmd, "seed.log") != 0:
        log("seed_from_full_evidence failed -- see _pipeline/logs/seed.log")
        return 2

    # 7. Tone ----------------------------------------------------------------
    log("7. rewriting hedge wording / first person in evidence")
    runner.run([PY, str(ROOT / "scripts" / "rewrite_assessed_on_tone.py"),
                "--market", args.market, "--country", args.country], "tone.log")

    # 8. Report --------------------------------------------------------------
    report_cmd = [PY, str(ROOT / "scripts" / "build_report_from_composite.py"),
                  "--market", args.market, "--country", args.country,
                  "--fixed-axes", str(spec_path)]
    fixed = chart_top or (done_ev if force_even else [])
    if fixed:
        report_cmd += ["--fixed-top20", str(write_json(pipe_dir / "chart_final.json", fixed))]
    log("8. building HTML / JSON / CSV report")
    if runner.run(report_cmd, "report.log") != 0:
        log("build_report_from_composite failed -- see _pipeline/logs/report.log")
        return 2

    # 9. Verify --------------------------------------------------------------
    ok = verify(out_dir, spec, args.top_n, args.keep)
    log(f"report: {out_dir / (out_dir.name + '_report.html')}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
