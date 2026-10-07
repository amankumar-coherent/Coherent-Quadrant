#!/usr/bin/env python3
"""Ask Google AI Mode whether each verified company still operates today.

Answers go to ``_pipeline/operating_status.json`` (active / acquired /
defunct / renamed, with a one-line note such as "Filed for Chapter 7
bankruptcy in 2016."). run_quadrant_pipeline.py runs this after dedupe and
leaves every non-active company out of the chart and the long tail.
Resumable: a company already answered is never asked again (use --recheck
to ask again). See vendor_intel.pipeline.company_status.

    .\\.venv\\Scripts\\python.exe scripts\\check_operating_status.py ^
        --market "Marine Seismic Data Processing Services Market" --country global
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

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def log(msg: str) -> None:
    print(f"[status {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", required=True)
    ap.add_argument("--country", default="global")
    ap.add_argument("--slot", type=int, default=41, help="browser profile slot")
    ap.add_argument("--names-file", default="",
                    help="JSON list of company names to check (default: every verified company)")
    ap.add_argument("--recheck", action="store_true", help="ask again for companies already answered")
    ap.add_argument("--out-file", default="",
                    help="write answers to this JSON instead of _pipeline/operating_status.json "
                         "(one file per parallel browser, so shards never overwrite each other)")
    args = ap.parse_args()

    os.environ["GOOGLE_AI_MODE_PROFILE_DIR"] = str(ROOT / "data" / f"ai_mode_batch_{args.slot:02d}")
    os.environ["GOOGLE_AI_MODE_BROWSER"] = "chromium"
    os.environ["GOOGLE_AI_MODE_ENABLED"] = "true"

    from vendor_intel.config import Settings
    from vendor_intel.pipeline import chatgpt_expand as ce
    from vendor_intel.pipeline.company_status import check_status, load_status, save_status
    from vendor_intel.pipeline.quadrant_pipeline import dedupe_companies, row_name, row_website
    from vendor_intel.pipeline.web_expand import default_output_dir

    out_dir = Path(default_output_dir(args.market, args.country))
    pipe_dir = out_dir / "_pipeline"
    state = json.loads((out_dir / "chatgpt_checkpoint_batch_all.json").read_text(encoding="utf-8"))
    data = state.get("data") or {}
    analysis = dict(data.get("market_analysis") or {})
    if analysis.get("market_type"):
        ce.publish_discovery_market(analysis)
    scope = str(analysis.get("market_definition") or "").strip()

    rows = {row_name(r): r for r in data.get("verified") or []}
    if args.names_file:
        names = list(json.loads(Path(args.names_file).read_text(encoding="utf-8")) or [])
    else:
        names = list(dedupe_companies(list(rows.values()))[0])
    companies = [{"name": n, "website": row_website(rows.get(n) or {})} for n in names]

    out_file = Path(args.out_file) if args.out_file else None
    status = (json.loads(out_file.read_text(encoding="utf-8")) if out_file and out_file.exists()
              else {} if out_file else load_status(pipe_dir))
    if args.recheck:
        status = {k: v for k, v in status.items() if k not in set(names)}
    todo = [c for c in companies if c["name"] not in status]
    log(f"{len(companies)} companies, {len(todo)} to check")
    if not todo:
        return 0

    client, model = ce._client(Settings()), ce._model(Settings())

    def ask(system: str, user: str, label: str):
        return ce._chat_json(client, model, system, user, label=label,
                             max_tokens=2500, require_key="results")

    def saved(st: dict) -> None:
        if out_file:
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_text(json.dumps(st, indent=2, ensure_ascii=False), encoding="utf-8")
        else:
            save_status(pipe_dir, st)
        log(f"saved {len(st)} answers")

    status = check_status(ask, args.market, scope, companies, status, on_batch=saved)
    missing = [c["name"] for c in companies if c["name"] not in status]
    flagged = {n: v for n, v in status.items() if v.get("status") != "active" and n in set(names)}
    for n, v in sorted(flagged.items()):
        log(f"NOT ACTIVE: {n} -> {v['status']}: {v.get('note', '')}")
    if missing:
        log(f"{len(missing)} companies got no answer (kept; re-run to retry): {missing[:8]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
