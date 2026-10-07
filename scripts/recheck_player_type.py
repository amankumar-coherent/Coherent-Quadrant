#!/usr/bin/env python3
"""Re-verify every company in a finished report against the market's player
type, through Google AI Mode (read-only).

Each company in <slug>_quadrant.json (chart + Other Noticeable Players) goes
through the pipeline's own verification (chatgpt_expand.gpt_verify_market):
the market's required player type from Step 0c (e.g. Solution Provider),
builds/owns the product, in the market (MARKET_SCOPE / market brief),
confidence >= 70, operating today. Companies are split over N browsers; every
answer is saved, so a re-run only asks the rest. Nothing in the report
changes: the result is a list for review, and a confirmed failure goes into
the market's _pipeline/analyst_review.json ("exclude" or "scope").

    .venv\\Scripts\\python.exe scripts\\recheck_player_type.py --market "X Market" --country global --browsers 10

Output: <market>/_pipeline/player_type_check/results.json and summary.md
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def report_companies(out_dir: Path) -> list[dict]:
    """Every company the report lists, with the richest discovery row for it."""
    from vendor_intel.pipeline.factcheck import company_name
    from vendor_intel.pipeline.quadrant_pipeline import norm_name

    q = _read(next(out_dir.glob("*_quadrant.json")), {})
    ckpt = _read(out_dir / "chatgpt_checkpoint_batch_all.json", {}).get("data") or {}
    rows = {}
    for r in ckpt.get("verified") or []:
        rows.setdefault(norm_name(str(r.get("name") or r.get("Company") or "")), r)
    out = []
    for b in q.get("brands") or []:
        name = company_name(b)
        src = rows.get(norm_name(name)) or {}
        out.append({"name": name, "brand": b.get("brand") or "", "on_chart": bool(b.get("on_chart")),
                    "website": src.get("website") or src.get("Website") or "",
                    "snippet": str(src.get("snippet") or src.get("Summary") or src.get("why_related") or "")[:280],
                    "role": src.get("role") or ""})
    return out


def worker(args) -> int:
    os.environ["GOOGLE_AI_MODE_PROFILE_DIR"] = str(ROOT / "data" / f"ai_mode_batch_{args.slot:02d}")
    os.environ["GOOGLE_AI_MODE_BROWSER"] = "chromium"
    os.environ["GOOGLE_AI_MODE_ENABLED"] = "true"
    from vendor_intel.config import Settings
    from vendor_intel.pipeline import chatgpt_expand as ce
    from vendor_intel.pipeline.web_expand import default_output_dir, market_family

    out_dir = Path(default_output_dir(args.market, args.country))
    ma = (_read(out_dir / "chatgpt_checkpoint_batch_all.json", {}).get("data") or {}).get("market_analysis") or {}
    if ma.get("market_type"):
        ce.publish_discovery_market(ma)          # the market's own player type (Step 0c)
    expected = ce.player_label(args.market, market_family(args.market))
    todo = _read(Path(args.companies), [])
    out_file = Path(args.out)
    done = _read(out_file, {})
    todo = [c for c in todo if c["name"] not in done]
    client, model = ce._client(Settings()), ce._model(Settings())
    from vendor_intel.pipeline.quadrant_pipeline import norm_name

    ours = {norm_name(c["name"]): c["name"] for c in todo}

    def own(name) -> str:          # the report's exact name for an answer
        return ours.get(norm_name(str(name or "")), str(name or ""))

    for i in range(0, len(todo), 12):
        chunk = todo[i:i + 12]
        kept, rejected = ce.gpt_verify_market(client, model, query=args.market, family=market_family(args.market),
                                              companies=chunk, country=args.country)
        for r in kept:
            done[own(r.get("name"))] = {"pass": True, "expected": expected, "role": r.get("commercial_role") or "",
                                        "confidence": r.get("verify_confidence") or "",
                                        "reason": r.get("verify_reason") or ""}
        for r in rejected:
            done[own(r.get("name"))] = {"pass": False, "expected": expected, "role": r.get("role") or "",
                                        "confidence": r.get("confidence") or "", "reason": r.get("reason") or ""}
        tmp = out_file.with_name(out_file.name + ".tmp")
        tmp.write_text(json.dumps(done, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, out_file)
        print(f"saved {len(done)}", flush=True)
    print("finished", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", required=True)
    ap.add_argument("--country", default="global")
    ap.add_argument("--browsers", type=int, default=10)
    ap.add_argument("--slot-start", type=int, default=41)
    ap.add_argument("--stagger", type=float, default=10.0)
    ap.add_argument("--slot", type=int, default=0, help=argparse.SUPPRESS)
    ap.add_argument("--companies", default="", help=argparse.SUPPRESS)
    ap.add_argument("--out", default="", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.companies:
        return worker(args)

    from vendor_intel.pipeline.web_expand import default_output_dir

    out_dir = Path(default_output_dir(args.market, args.country))
    brief = _read(out_dir / "_pipeline" / "market_brief.json", {})
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    if brief.get("scope"):
        env["MARKET_SCOPE"] = " ".join(str(brief["scope"]).split())
    work = out_dir / "_pipeline" / "player_type_check"
    work.mkdir(parents=True, exist_ok=True)
    companies = report_companies(out_dir)
    results: dict = {}
    for f in sorted(work.glob("results_*.json")):
        results.update(_read(f, {}))
    todo = [c for c in companies if c["name"] not in results]
    print(f"[check] {len(companies)} companies in the report; {len(companies) - len(todo)} already checked; "
          f"{len(todo)} on {min(args.browsers, len(todo))} browsers", flush=True)
    n = min(args.browsers, len(todo))
    procs = []
    for i in range(n):
        part = work / f"companies_{i + 1}.json"
        part.write_text(json.dumps(todo[i::n], ensure_ascii=False), encoding="utf-8")
        log = (work / f"browser_{i + 1}.log").open("a", encoding="utf-8")
        procs.append(subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--market", args.market, "--country", args.country,
             "--slot", str(args.slot_start + i), "--companies", str(part),
             "--out", str(work / f"results_{i + 1}.json")],
            cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT, env=env))
        print(f"browser {i + 1}: slot {args.slot_start + i}, {len(todo[i::n])} companies", flush=True)
        time.sleep(args.stagger)
    for p in procs:
        p.wait()
    for f in sorted(work.glob("results_*.json")):
        results.update(_read(f, {}))
    (work / "results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    by = {c["name"]: c for c in companies}
    fails = [(n_, r) for n_, r in results.items() if n_ in by and not r.get("pass")]
    missing = [c["name"] for c in companies if c["name"] not in results]
    lines = [f"# Player-type re-check: {args.market} ({args.country})", "",
             f"- companies in report: {len(companies)}",
             f"- pass: {sum(1 for n_, r in results.items() if n_ in by and r.get('pass'))}",
             f"- fail: {len(fails)}", f"- not answered: {len(missing)}", ""]
    for n_, r in sorted(fails, key=lambda x: (not by[x[0]]["on_chart"], x[0])):
        lines.append(f"- {'**CHART** ' if by[n_]['on_chart'] else ''}{n_} -- role: {r.get('role') or '?'}, "
                     f"confidence {r.get('confidence')}: {r.get('reason')}")
    if missing:
        lines += ["", "Not answered (re-run to resume): " + ", ".join(missing)]
    (work / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[check] done -> {work / 'summary.md'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
