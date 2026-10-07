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
  4. Quick scores   score_overall_only.py for every company that has no
                    score yet: 2 AI Mode queries each -- a Product
                    Capability scorecard (all 5 X parameters) and a Business
                    Capability scorecard (all 5 Y). X/Y = parameter means,
                    Overall = (X+Y)/2. Feeds the long tail's Strength bubbles.
  5. Top N          the best --top-n/4 companies by Overall from EACH
                    quadrant (split at the pool's median X and Y) -- or a
                    list you pin with --top-list -- get full per-parameter
                    evidence.
  6. Evidence       prescore_verified.py (1 parameter per query), then up to
                    --max-rounds of gap fill: fill_missing_parameters.py for
                    missing scores, fill_missing_assessed_on.py for scores
                    with no "why" reasoning.
  7. Composite      seed_from_full_evidence.py -- X/Y/Overall with the
                    65-100 floor; 5 per quadrant when the evidence pool IS
                    the Top N.
  8. Tone           rewrite_assessed_on_tone.py (desk-research wording, "we");
                    analyst review + automatic review (ownership labels,
                    exclusions); supporting points tidied ("Not available").
  9. Report         build_report_from_composite.py (HTML + JSON + CSV), the
                    interactive page, then the PDF (export_report_pdf.py).
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
    axis_xy,
    dedupe_companies,
    evidence_gaps,
    load_evidence,
    load_overall_only,
    norm_name,
    rank_score,
    row_name,
    select_top_by_quadrant,
)
from vendor_intel.pipeline.web_expand import default_output_dir  # noqa: E402

PY = sys.executable
_HEDGE_RE = re.compile(
    r"could not verify|not publicly (?:disclosed|accessible|available|reported|detailed|specified|"
    r"documented|published)|\b(?:does|do) not publicly\b|found no public|no evidence exists|"
    r"no (?:(?:specific|public|confirmed|direct|verifiable)\s+)+evidence|remains? undisclosed|"
    r"\bno (?:[\w-]+ ){0,10}?(?:metrics|reports|statements|figures|records)\b[^.<]{0,160}?"
    r"\b(?:(?:is|are|was|were) (?:found|available)|exists?)\b|\bdesk[- ]research\b|"
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
            settings = Settings.load()
            # The market alone (and its brief / scope), never a sector catalog.
            industry = define_market_axes(args.market, {}, geography=args.country,
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
    classic = out_dir / f"{slug}_report_classic.html"
    report = out_dir / f"{slug}_report.html"
    html = (classic if classic.exists() else report).read_text(encoding="utf-8")
    viewer_html = report.read_text(encoding="utf-8") if classic.exists() else ""
    brands = payload.get("brands") or []
    xp, yp = spec["x"], spec["y"]
    chart = [b for b in brands if b.get("on_chart")]
    checks: list[tuple[str, bool, str]] = []

    from vendor_intel.pipeline.company_status import inactive_companies, is_inactive
    from vendor_intel.quadrant.axis_define import PARAMS_PER_AXIS
    from vendor_intel.quadrant.quadrant_language import AXIS_Y_TITLE, x_axis_title

    crit = payload.get("criteria") or {}
    n_x, n_y = len(crit.get("x_axis") or xp), len(crit.get("y_axis") or yp)
    checks.append((f"Exactly {PARAMS_PER_AXIS} parameters on X and on Y",
                   n_x == n_y == PARAMS_PER_AXIS == len(xp) == len(yp), f"X={n_x} Y={n_y}"))
    x_title = x_axis_title(payload)
    checks.append((f"Axes are {x_title} (X) / {AXIS_Y_TITLE} (Y)",
                   x_title in html and AXIS_Y_TITLE in html, ""))
    inactive = inactive_companies(out_dir / "_pipeline")
    listed = [b.get("company") for b in brands
              if is_inactive(str(b.get("company") or ""), inactive)
              or is_inactive(str(b.get("company_key") or ""), inactive)
              or is_inactive(str(b.get("brand") or ""), inactive)]
    checks.append(("No inactive / acquired / excluded company listed", not listed, listed[:5]))

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
    if viewer_html:
        checks.append(("Interactive report: data embedded, long-tail bubbles without tooltip",
                       'id="quadrant-data"' in viewer_html and "__QUADRANT_DATA__" not in viewer_html
                       and 'class="dots" title=' not in viewer_html, ""))
    dots = [r.count("cq-sdot-on") for r in rows]
    checks.append(("Other Noticeable Player sorted by Strength",
                   all(a >= b for a, b in zip(dots, dots[1:])), dots[:10]))

    publishers = [ln.strip() for ln in (ROOT / "config" / "research_publishers.txt")
                  .read_text(encoding="utf-8").splitlines()
                  if ln.strip() and not ln.startswith("#")]
    pub_re = re.compile("|".join(r"\s*".join(map(re.escape, n.split())) for n in publishers), re.I)
    cited = sorted({m.group(0) for m in pub_re.finditer(html)}
                   | {m.group(0) for m in pub_re.finditer(json.dumps(brands, ensure_ascii=False))})
    checks.append(("No market-research publisher (competitor) named", not cited, cited[:5]))

    from vendor_intel.pipeline.company_facts import gap_bullets

    from vendor_intel.pipeline.company_status import chart_ineligible

    off = chart_ineligible(out_dir / "_pipeline")
    # Adjacent companies chosen to fill a small market's chart are allowed.
    off -= {norm_name(n) for n in read_json(out_dir / "_pipeline" / "chart_fill_adjacent.json", []) or []}
    adj_on_chart = [b.get("company") for b in chart
                    if norm_name(str(b.get("company_key") or b.get("company") or "")) in off]
    checks.append(("No adjacent-segment company on the chart (like-for-like quadrant)",
                   not adj_on_chart, adj_on_chart[:5]))

    gaps = gap_bullets(payload)
    checks.append(("Supporting points: absence reads 'Not available', only when nothing else is found",
                   not gaps, f"{len(gaps)}: {gaps[:3]}"))

    no_hq = [b.get("company") for b in brands if not str(b.get("hq_location") or "").strip()]
    checks.append(("Every company has an HQ", not no_hq, f"{len(no_hq)} missing: {no_hq[:5]}"))

    low = [b.get("company") for b in brands
           if min(int(b.get("execution") or 0), int(b.get("innovation") or 0)) < 65]
    checks.append(("Every X/Y >= 65", not low, low[:5]))

    from vendor_intel.pipeline.factcheck import missing as factcheck_missing

    unchecked = factcheck_missing(out_dir)
    checks.append(("Chart fact-check complete (status, owner, HQ, scope, supporting points)",
                   not unchecked, unchecked[:5]))

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
    ap.add_argument("--skip-facts", action="store_true",
                    help="skip step 3c (ownership / identity checks in AI Mode); saved answers still apply")
    ap.add_argument("--no-pdf", action="store_true", help="do not print the PDF report (step 8b)")
    ap.add_argument("--no-docx", action="store_true", help="do not write the Word report (step 8b)")
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
    # An analyst-supplied market brief (data, per market): its scope text
    # steers discovery and verification (MARKET_SCOPE, inherited by every
    # step), and its definition / core / adjacent text replaces AI Mode's
    # after discovery, so the scope check judges against the client's own
    # definition (e.g. a taxonomy that explicitly includes ERP modules).
    brief = read_json(pipe_dir / "market_brief.json", {}) or {}
    if brief.get("scope"):
        os.environ["MARKET_SCOPE"] = " ".join(str(brief["scope"]).split())
        log(f"   market brief: scope set from _pipeline/market_brief.json")

    # Discovery must not score: steps 2 and 4 below derive the axes and score
    # every verified company, so discovery's own X/Y pass (its step 6c) only
    # doubled the AI Mode queries.
    os.environ.setdefault("EXPAND_DISCOVERY_XY", "0")

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
    if brief and not args.dry_run:
        ma = dict(data.get("market_analysis") or {})
        want = {k: brief[k] for k in ("market_definition", "core_scope", "adjacent_segments") if brief.get(k)}
        if any(ma.get(k) != v for k, v in want.items()):
            ma.update(want)
            data["market_analysis"] = ma
            state["data"] = data
            write_json(ckpt_path, state)
            log(f"   market brief: {', '.join(want)} applied to the market analysis")

    # 2. Axes spec -----------------------------------------------------------
    spec = resolve_spec(args, data, spec_path)
    xp, yp = spec["x"], spec["y"]
    from vendor_intel.quadrant.quadrant_language import AXIS_Y_TITLE, X_TITLE_BY_PLAYER

    roles = ((data.get("market_analysis") or {}).get("keep_roles")
             or [(data.get("market_analysis") or {}).get("primary_participant") or ""])
    x_title = X_TITLE_BY_PLAYER.get(str(roles[0] if roles else "").strip().lower(),
                                    "Product Capability")
    # Child scorers (quick scorecard) name the X axis the way the report does.
    os.environ["QUADRANT_X_TITLE"] = x_title
    log(f"2. axes: X={x_title} ({len(spec['x'])} params) "
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

    # 3b. Operating status: list only companies that still operate today ----
    # (bankrupt / liquidated / absorbed by an acquirer / renamed out of the
    # market are left out), plus any company an analyst review excluded.
    from vendor_intel.pipeline.company_status import (
        inactive_companies, is_inactive, load_status, refill_top_by_quadrant)

    from vendor_intel.pipeline.company_status import save_status

    def merge_status_shards() -> None:
        # One answer file per browser; folded into operating_status.json so a
        # resumed run never asks again for what a shard already answered.
        st = load_status(pipe_dir)
        for side in sorted(pipe_dir.glob("status_shard*.json")):
            st.update(read_json(side, {}) or {})
        save_status(pipe_dir, st)

    merge_status_shards()
    unchecked = [n for n in pool if n not in load_status(pipe_dir)]
    if unchecked and not args.dry_run:
        # Split across every browser slot (10 companies per query each), not
        # one browser: on a 250-company market that is minutes, not an hour.
        n = max(1, min(len(runner.slots), (len(unchecked) + 9) // 10))
        log(f"3b. operating-status check for {len(unchecked)} companies across {n} browser(s)")
        runner.log_dir.mkdir(parents=True, exist_ok=True)
        procs = []
        for i in range(n):
            part = unchecked[i::n]
            fh = (runner.log_dir / f"status_shard{i}.log").open("w", encoding="utf-8")
            procs.append((subprocess.Popen(
                [PY, str(ROOT / "scripts" / "check_operating_status.py"),
                 "--market", args.market, "--country", args.country,
                 "--slot", str(runner.slots[i]),
                 "--names-file", str(write_json(pipe_dir / f"status_todo_{i}.json", part)),
                 "--out-file", str(pipe_dir / f"status_shard{i}.json")],
                cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"}), fh))
            time.sleep(2)
        while any(p.poll() is None for p, _ in procs):
            time.sleep(15)
        for _, fh in procs:
            fh.close()
        merge_status_shards()
    inactive = inactive_companies(pipe_dir, include_auto=False)  # 3c applies the automatic review
    # A dedupe group goes if any of its spellings is flagged.
    why = {n: [inactive[norm_name(m)] for m in groups.get(n, [n]) if is_inactive(m, inactive)]
           for n in pool}
    gone = [n for n in pool if why[n]]
    if gone:
        pool = [n for n in pool if not why[n]]
        write_json(pipe_dir / "excluded_companies.json", {n: why[n][0] for n in gone})
        log(f"3b. {len(gone)} companies left out (not active or excluded by review): "
            f"{gone[:8]} -> _pipeline/excluded_companies.json")
    from vendor_intel.pipeline.company_status import status_needs_review

    review_status = status_needs_review(pipe_dir)
    write_json(pipe_dir / "status_needs_review.json", review_status)
    if review_status:
        log(f"3b. {len(review_status)} status answers kept but need a person's look "
            f"(renamed / no event given) -> _pipeline/status_needs_review.json")

    # 3c. Ownership + identity (AI Mode) -> automatic review ------------------
    # Bought-and-absorbed companies, old names of rebranded companies listed
    # twice, and companies that cannot be shown to exist or are not in this
    # market are left out; a company bought but still trading under its own
    # name gets "Name (acquired by Owner)" in the Company column. The analyst
    # review file always wins (see company_facts).
    from vendor_intel.pipeline import company_facts as cf

    def merged_facts(mode: str, fname: str) -> dict:
        merged = read_json(pipe_dir / fname, {}) or {}
        for side in sorted(pipe_dir.glob(f"facts_{mode}_shard*.json")):
            merged.update(read_json(side, {}) or {})
        write_json(pipe_dir / fname, merged)
        return merged

    status_now = load_status(pipe_dir)
    own = merged_facts("ownership", cf.OWNERSHIP_FILE)
    need = [n for n in pool if n not in own]
    if need and not args.skip_facts:
        runner.shards("ownership", "check_company_facts.py", need, ["--mode", "ownership"])
        own = merged_facts("ownership", cf.OWNERSHIP_FILE)
    ident = merged_facts("identity", cf.IDENTITY_FILE)
    need = [n for n in cf.identity_candidates(pipe_dir, pool, status_now) if n not in ident]
    if need and not args.skip_facts:
        runner.shards("identity", "check_company_facts.py", need, ["--mode", "identity"])
        ident = merged_facts("identity", cf.IDENTITY_FILE)
    # Scope: a like-for-like quadrant. "out" is left out; "adjacent" (a
    # neighbouring segment) stays in Other Noticeable Players, never on the chart.
    scope_ans = merged_facts("scope", cf.SCOPE_FILE)
    need = [n for n in pool if n not in scope_ans]
    if need and not args.skip_facts:
        runner.shards("scope", "check_company_facts.py", need, ["--mode", "scope"])
        scope_ans = merged_facts("scope", cf.SCOPE_FILE)
    # Single-country run: where is each company's own head office?
    from vendor_intel.pipeline.geo_rotation import is_single_country

    one_country = args.country if is_single_country(args.country) else ""
    if one_country:
        hq_ans = merged_facts("hq", cf.HQ_FILE)
        need = [n for n in pool if n not in hq_ans]
        if need and not args.skip_facts:
            runner.shards("hq", "check_company_facts.py", need, ["--mode", "hq"])
            hq_ans = merged_facts("hq", cf.HQ_FILE)
    auto = cf.auto_review(pipe_dir, pool, status_now, country=one_country)
    cf.write_auto_review(pipe_dir, auto)
    from vendor_intel.pipeline.company_status import chart_ineligible

    off_chart = chart_ineligible(pipe_dir)
    inactive = inactive_companies(pipe_dir)
    more = [n for n in pool if any(is_inactive(m, inactive) for m in groups.get(n, [n]))]
    if more:
        pool = [n for n in pool if n not in more]
        gone = list(gone) + more
        why.update({n: [inactive.get(norm_name(n), "automatic review")] for n in more})
        write_json(pipe_dir / "excluded_companies.json", {n: why[n][0] for n in gone})
    adjacent = [n for n in pool if norm_name(n) in off_chart]
    log(f"3c. ownership {len(own)} / identity {len(ident)} / scope {len(scope_ans)} answers: "
        f"{len(more)} more left out {more[:6]}, {len(auto['ownership'])} owner labels, "
        f"{len(adjacent)} adjacent-segment (not on the chart) {adjacent[:6]} -> _pipeline/auto_review.json")

    def chart_ok(n: str) -> bool:
        return norm_name(n) not in off_chart

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
    log(f"4. quick X/Y scorecard scoring needed for {len(need)} companies "
        f"(1 Product + 1 Business query each)")
    runner.shards("overall", "score_overall_only.py", need, ["--fixed-axes", str(spec_path)])
    overall = load_overall_only(out_dir)
    # A small market can have fewer core companies than chart slots (the
    # main-product test moves add-on vendors to adjacent). The chart still
    # shows top_n: every core company, then the strongest adjacent ones fill
    # the remaining slots. Recorded, so VERIFY accepts exactly these.
    fill_path = pipe_dir / "chart_fill_adjacent.json"
    scored = [n for n in pool if rank_score(n, evidence, overall, xp, yp) is not None]
    core_scored = [n for n in scored if norm_name(n) not in off_chart]
    fill: list[str] = []
    if len(core_scored) < args.top_n:
        adj_ranked = sorted((n for n in scored if norm_name(n) in off_chart),
                            key=lambda n: rank_score(n, evidence, overall, xp, yp), reverse=True)
        fill = adj_ranked[: args.top_n - len(core_scored)]
        off_chart = off_chart - {norm_name(n) for n in fill}
        log(f"   only {len(core_scored)} core companies for {args.top_n} chart slots: "
            f"{len(fill)} strongest adjacent companies fill the rest {fill[:8]}")
    if not args.dry_run:
        write_json(fill_path, fill)
    if ev_pool is None and size <= args.top_n:
        # The chart's Top N = the best top_n/4 per quadrant by Overall, from
        # the quick X/Y scores of the whole verified pool.
        xy = {n: v for n in pool if chart_ok(n)
              and (v := axis_xy(n, evidence, overall, xp, yp)) is not None}
        ev_pool = select_top_by_quadrant(xy, args.top_n)
        log(f"   Top {len(ev_pool)} chosen {args.top_n // 4} per quadrant from "
            f"{len(xy)} quick-scored companies")
    elif ev_pool is None:
        # A larger --evidence-pool: the chart selector picks from it later.
        ranked = sorted(
            (n for n in pool if rank_score(n, evidence, overall, xp, yp) is not None),
            key=lambda n: rank_score(n, evidence, overall, xp, yp), reverse=True,
        )
        ev_pool = ranked if size >= len(ranked) else ranked[:size]
    if ev_pool is not None and size <= args.top_n and not args.top_list \
            and any(not chart_ok(n) for n in ev_pool):
        # A saved Top N that holds adjacent-segment companies: they leave the
        # chart (their quadrant is refilled below from core companies).
        dropped_adj = [n for n in ev_pool if not chart_ok(n)]
        ev_pool = [n for n in ev_pool if chart_ok(n)]
        log(f"   adjacent-segment companies taken off the chart: {dropped_adj}")
        gone = list(gone) + dropped_adj
    if ev_pool is not None and gone and len(ev_pool) < min(size, len(pool)) \
            and size <= args.top_n and not args.top_list:
        # A saved Top N lost companies to 3b/3c: keep every company that stayed
        # and fill each short quadrant with its best remaining core company.
        xy = {n: v for n in pool
              if (v := axis_xy(n, evidence, overall, xp, yp)) is not None}
        before = list(ev_pool)
        ev_pool = refill_top_by_quadrant(ev_pool, xy, args.top_n, eligible=chart_ok)
        log(f"   Top {args.top_n} refilled after 3b: added "
            f"{[n for n in ev_pool if n not in before]}")
        if not args.chart_top:
            write_json(chart_path, ev_pool)
    if args.dry_run:
        log(f"   evidence pool: {len(ev_pool)} companies"
            + (" (ranked after Overall-only scoring on a real run)" if not ev_pool else ""))
    else:
        write_json(pool_path, ev_pool)
        log(f"   evidence pool: {len(ev_pool)} companies -> {pool_path}")

    # 5. Evidence with reasoning, then gap-fill rounds -----------------------
    # Bullets resting on a never-valid source (employee reviews, competing
    # publishers, modelled-estimate data sites) go first, so a parameter left
    # empty is re-asked below instead of keeping a score built on them.
    if not args.dry_run:
        n_bad = cf.drop_invalid_sources(out_dir)
        if n_bad:
            log(f"5. {n_bad} supporting point(s) on invalid sources removed before gap-fill")
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
        scored_tail = [n for n in tail if rank_score(n, evidence, overall, xp, yp) is not None]
        # A company can reach here with NO quick-score at all -- a transient
        # Overall-only query failure (CAPTCHA storm, timeout, unparsed
        # reply) that Step 4 never retried, since Step 4 only scores each
        # company once. Left as-is, that company silently vanishes from the
        # final report (seed_from_full_evidence drops any long-tail name it
        # cannot find a score for) and --keep comes up short with no
        # explanation. Retry those specific names now, once, before
        # accepting the shortfall.
        unscored_tail = [n for n in tail if n not in scored_tail]
        if unscored_tail and len(scored_tail) < room:
            log(f"   {len(unscored_tail)} long-tail companies have no quick-score "
                f"(a Step 4 query failed) -- retrying before filling --keep {args.keep}")
            runner.shards("overall_retry", "score_overall_only.py", unscored_tail,
                         ["--fixed-axes", str(spec_path)])
            overall = load_overall_only(out_dir)
            scored_tail = [n for n in tail if rank_score(n, evidence, overall, xp, yp) is not None]
        scored_tail = sorted(
            scored_tail, key=lambda n: rank_score(n, evidence, overall, xp, yp), reverse=True,
        )
        if len(done_ev) + len(scored_tail) < args.keep:
            log(f"   WARNING: only {len(done_ev) + len(scored_tail)} verified companies "
                f"after dedupe, fewer than --keep {args.keep}. Discovery has already "
                f"run for this market; re-run it with a larger --discover-target in a "
                f"fresh output folder to find more.")
        dropped = len(scored_tail) - min(room, len(scored_tail))
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
    saved_chart = [n for n in dict.fromkeys(chart_top) if n in done_ev]
    chart_top = [n for n in saved_chart if chart_ok(n)]
    if (gone or len(chart_top) < len(saved_chart)) and chart_top and not args.chart_top:
        # A pinned chart after 3b removed companies: keep the ones that stayed
        # and fill each short quadrant from the companies with full evidence.
        # Checked even when no chart company left: a smaller pool moves the
        # median split, which can push a chart company into the next quadrant.
        from vendor_intel.quadrant.matrix_rollup import normalize_cohort_to_band

        xy = {n: v for n in done_ev
              if (v := axis_xy(n, evidence, overall, xp, yp)) is not None}
        # Quadrants on the scale the composite step (seed_from_full_evidence)
        # places them: banded to 65-100 and rounded. Rounding creates ties at
        # the median, so raw means would disagree near the split.
        names = list(xy)
        bx = normalize_cohort_to_band([xy[n][0] for n in names])
        by = normalize_cohort_to_band([xy[n][1] for n in names])
        xy = {n: (int(round(a)), int(round(b))) for n, a, b in zip(names, bx, by)}
        before = list(chart_top)
        chart_top = refill_top_by_quadrant(chart_top, xy, args.top_n, eligible=chart_ok)
        if set(chart_top) != set(before):
            write_json(chart_path, chart_top)
            log(f"6. chart rebalanced after 3b: added {[n for n in chart_top if n not in before]}, "
                f"removed {[n for n in before if n not in chart_top]}")
    # When the full-evidence set IS the chart (top_n companies or fewer), the
    # split must be by rank -- top_n/4 per quadrant -- on every run. A median
    # split over those same 20 only happens to give 5/5/5/5; it broke once a
    # pinned chart lost a company and was refilled (2/8/4/6).
    force_even = len(done_ev) <= args.top_n
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
    if runner.run([PY, str(ROOT / "scripts" / "rewrite_assessed_on_tone.py"),
                   "--market", args.market, "--country", args.country], "tone.log") != 0:
        # An evidence file it could not read keeps its old wording, which
        # VERIFY would only catch as hedge wording much later.
        log("FAIL: tone rewrite failed (see _pipeline/tone.log)")
        return 1

    # 7b. Analyst review corrections (_pipeline/analyst_review.json) ---------
    from vendor_intel.pipeline.company_status import (
        apply_corrections, apply_display_corrections, apply_hq_corrections,
        apply_ownership_corrections, apply_wording, load_review, load_wording)

    n_wording = apply_wording(out_dir, load_wording(pipe_dir))
    if n_wording:
        log(f"7b. reviewed wording: {n_wording} justification(s) rewritten "
            "(_pipeline/wording_review.json)")
    # Supporting points: an absence-only bullet reads "Not available", which
    # a parameter shows only when it has no real finding, and then once.
    from vendor_intel.pipeline.company_facts import tidy_evidence

    n_tidy = tidy_evidence(out_dir)
    if n_tidy:
        log(f"7b. supporting points: {n_tidy} text(s) tidied (citation leftovers, absence -> 'Not available')")
    review = load_review(pipe_dir)
    for r in apply_hq_corrections(ckpt_path, review["hq"]):
        log(f"7b. HQ for {r['company']}: {r['headquarters']}"
            + ("" if r["changed"] else " (already set)" if r["matched"]
               else " -- WARNING: company not found in the verified list"))
    for r in apply_display_corrections(ckpt_path, review["display"]):
        log(f"7b. current name for {r['company']}: {r['current_name']} (listed brand is legacy)"
            + ("" if r["changed"] else " (already set)" if r["matched"]
               else " -- WARNING: company not found in the verified list"))
    for r in apply_ownership_corrections(ckpt_path, review["ownership"]):
        log(f"7b. owner of {r['company']}: {r['owner']}"
            + ("" if r["changed"] else " (already set)" if r["matched"]
               else " -- WARNING: company not found in the verified list"))
    corrections = review["corrections"]
    if corrections:
        sys.path.insert(0, str(ROOT / "scripts"))
        from primary_research_wording import to_primary

        rows = apply_corrections(out_dir, corrections, normalize=to_primary)
        log(f"7b. analyst corrections: {sum(r['changed'] for r in rows)} text(s) changed "
            f"from {len(rows)} correction(s)")
        for r in rows:
            if not r["changed"] and not r["already_applied"] and r.get("replace"):
                log(f"   WARNING: correction text not found for {r['company']}: "
                    f"{r['find'][:80]!r}")

    # 8. Report --------------------------------------------------------------
    report_cmd = [PY, str(ROOT / "scripts" / "build_report_from_composite.py"),
                  "--market", args.market, "--country", args.country,
                  "--fixed-axes", str(spec_path), "--top-n", str(args.top_n)]
    fixed = chart_top or (done_ev if force_even else [])
    if fixed:
        report_cmd += ["--fixed-top20", str(write_json(pipe_dir / "chart_final.json", fixed))]
    log("8. building HTML / JSON / CSV report")
    if runner.run(report_cmd, "report.log") != 0:
        log("build_report_from_composite failed -- see _pipeline/logs/report.log")
        return 2
    # The delivered report is the interactive design (quadrant.json embedded,
    # rendered in the browser). The static page stays next to it as
    # <slug>_report_classic.html: VERIFY and the maintenance scripts read it.
    from vendor_intel.quadrant.viewer import write_viewer

    slug = out_dir.name
    static = out_dir / f"{slug}_report.html"
    classic = out_dir / f"{slug}_report_classic.html"
    static.replace(classic)
    write_viewer(read_json(out_dir / f"{slug}_quadrant.json", {}), static)
    log(f"8. report page: interactive design ({static.name}); static copy {classic.name}")

    # 8a. Chart fact-check (always): every chart company's status, owner, HQ,
    # scope and specific supporting points, checked in AI Mode on every
    # browser of this run (resumable; checked companies are not re-asked).
    # Only decisions that pass generic safety rules are applied
    # (vendor_intel.pipeline.factcheck), through the review layer the
    # analyst file overrides; the rest is listed in _pipeline/factcheck/findings.md.
    if not args.dry_run:
        from vendor_intel.pipeline import factcheck as fcheck

        slots = parse_slots(args.slots)
        for attempt in (1, 2):
            if not fcheck.missing(out_dir):
                break
            log(f"8a. chart fact-check (attempt {attempt}) on {len(slots)} browser(s)")
            runner.run([PY, str(ROOT / "scripts" / "factcheck_chart.py"), "--market", args.market,
                        "--country", args.country, "--browsers", str(len(slots)),
                        "--slot-start", str(slots[0])], "factcheck.log")
        left = fcheck.missing(out_dir)
        decisions = fcheck.build_review(out_dir)
        changed = fcheck.write_review(pipe_dir, decisions)
        n_chart = len(fcheck.chart_rows(out_dir))
        log(f"8a. fact-check: {n_chart - len(left)} of {n_chart} chart companies checked; decided "
            + ", ".join(f"{len(v)} {k}" for k, v in decisions.items())
            + " (analyst review wins where both touch the same text)"
            + (f"; NOT complete: {left}" if left else ""))
        fc_pass = int(os.environ.get("QUADRANT_FACTCHECK_PASS") or "1")
        if changed and fc_pass < 3:
            # Apply through the normal steps: 3b/3c drop or move companies
            # (the chart refills from core companies, whose evidence step 5
            # gathers), 7b writes corrections / owners / HQ, 8 rebuilds, and
            # 8a then checks only the new chart entrants. Saved work is reused.
            log(f"8a. fact-check decisions changed -> re-running from saved work (pass {fc_pass + 1})")
            env = {**os.environ, "QUADRANT_FACTCHECK_PASS": str(fc_pass + 1)}
            return subprocess.call([PY, str(Path(__file__).resolve()), *sys.argv[1:]], env=env)

    # 8b. PDF: cover, contents, one section per page, one company per page.
    if not args.no_pdf and not args.dry_run:
        rc = runner.run([PY, str(ROOT / "scripts" / "export_report_pdf.py"), "--html", str(static)],
                        "pdf.log")
        log("8b. PDF report: " + (f"{static.with_suffix('.pdf').name}" if rc == 0
                                  else "FAILED -- see _pipeline/logs/pdf.log (report HTML is fine)"))
    # Word copy of the same pages (text read from the page the PDF prints).
    if not args.no_docx and not args.dry_run:
        rc = runner.run([PY, str(ROOT / "scripts" / "export_report_docx.py"), "--html", str(static)],
                        "docx.log")
        log("8b. Word report: " + (f"{static.with_suffix('.docx').name}" if rc == 0
                                   else "FAILED -- see _pipeline/logs/docx.log (report HTML is fine)"))

    # 9. Verify --------------------------------------------------------------
    # A market that ran out keeps every company it has (never padded), so the
    # check is against what was available after 3b/3c, not the raw --keep.
    ok = verify(out_dir, spec, args.top_n, min(args.keep, len(pool)) if args.keep else 0)
    log(f"report: {out_dir / (out_dir.name + '_report.html')}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
