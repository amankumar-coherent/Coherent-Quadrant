#!/usr/bin/env python3
"""Ask Google AI Mode who owns each company in a market: has it ever been
acquired (majority stake, merger, asset purchase), by whom, when, and what it
is today (independent, subsidiary still trading under its own name, absorbed
into the acquirer, or closed).

This is a research read-out, not a filter: it never changes the report. The
operating-status check (check_operating_status.py) decides what is listed;
this answers "which of these companies were bought by someone".

One browser per run (--slot); run several with different --names-file /
--out-file pairs to check in parallel. Resumable: answered names are skipped.

    .\\.venv\\Scripts\\python.exe scripts\\check_ownership.py --market "..." ^
        --country global --slot 41 --names-file names_0.json --out-file own_0.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BATCH = 10


def log(msg: str) -> None:
    print(f"[ownership {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def prompt(market: str, scope: str) -> str:
    return (
        "You are a market research analyst checking the ownership history of companies "
        "in a market landscape. Answer from verifiable facts only: acquisitions, "
        "majority-stake purchases, mergers and asset purchases.\n"
        f"Market: {market}\n" + (f"Market scope: {scope}\n" if scope else "")
        + "For EACH company: acquired = true if another company bought it (or a majority "
        "stake in it, or its business/assets) at any time, else false. acquirer = the "
        "buyer's name; year = the year of the deal; today = one of independent | "
        "subsidiary (still trades under its own name, owned by the acquirer) | absorbed "
        "(merged into the acquirer, own name gone) | closed | unknown. note = one short "
        "factual sentence with the deal. If you are not sure a deal happened, answer "
        "acquired=false with today=unknown; never guess an acquirer.\n"
        "Return one result for EVERY company, never skip a name. Compact JSON only: "
        '{"results":[{"name":"...","acquired":true,"acquirer":"...","year":"...",'
        '"today":"...","note":"..."}]}'
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", required=True)
    ap.add_argument("--country", default="global")
    ap.add_argument("--slot", type=int, default=41)
    ap.add_argument("--names-file", required=True)
    ap.add_argument("--out-file", required=True)
    ap.add_argument("--batch", type=int, default=BATCH,
                    help="companies per query; 1 = one search per company (for unclear answers)")
    ap.add_argument("--recheck-unknown", action="store_true",
                    help="ask again for names answered acquired=false with today=unknown")
    args = ap.parse_args()

    os.environ["GOOGLE_AI_MODE_PROFILE_DIR"] = str(ROOT / "data" / f"ai_mode_batch_{args.slot:02d}")
    os.environ["GOOGLE_AI_MODE_BROWSER"] = "chromium"
    os.environ["GOOGLE_AI_MODE_ENABLED"] = "true"

    from vendor_intel.config import Settings
    from vendor_intel.pipeline import chatgpt_expand as ce
    from vendor_intel.pipeline.quadrant_pipeline import norm_name, row_name, row_website
    from vendor_intel.pipeline.web_expand import default_output_dir

    out_dir = Path(default_output_dir(args.market, args.country))
    state = json.loads((out_dir / "chatgpt_checkpoint_batch_all.json").read_text(encoding="utf-8"))
    data = state.get("data") or {}
    scope = str((data.get("market_analysis") or {}).get("market_definition") or "").strip()
    rows = {row_name(r): r for r in data.get("verified") or []}

    names = list(json.loads(Path(args.names_file).read_text(encoding="utf-8")) or [])
    out = Path(args.out_file)
    done = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    def unclear(v: dict) -> bool:
        return str(v.get("acquired")).lower() != "true" and v.get("today") == "unknown"
    todo = [n for n in names if n not in done or (args.recheck_unknown and unclear(done[n]))]
    log(f"{len(names)} companies, {len(todo)} to check")
    client, model = ce._client(Settings()), ce._model(Settings())
    system = prompt(args.market, scope)

    step = max(1, args.batch)
    for i in range(0, len(todo), step):
        chunk = todo[i: i + step]
        payload = [{"name": n, "website": row_website(rows.get(n) or {})} for n in chunk]
        try:
            res = ce._chat_json(client, model, system, "Companies:\n" + json.dumps(payload, ensure_ascii=False),
                                label=f"own-{i // step + 1}", max_tokens=3000, require_key="results")
        except Exception as err:  # noqa: BLE001 -- one failed query must not stop the run
            log(f"batch {i // step + 1} failed: {err}")
            continue
        by = {norm_name(str(r.get("name") or "")): r for r in (res or {}).get("results") or [] if isinstance(r, dict)}
        for n in chunk:
            r = by.get(norm_name(n))
            if r is None and len(chunk) == 1 and len(by) == 1:
                r = next(iter(by.values()))  # a single-company answer may spell the name differently
            if r:
                done[n] = {k: r.get(k, "") for k in ("acquired", "acquirer", "year", "today", "note")}
        out.write_text(json.dumps(done, indent=2, ensure_ascii=False), encoding="utf-8")
        log(f"saved {len(done)} answers")
    missing = [n for n in names if n not in done]
    if missing:
        log(f"{len(missing)} without an answer (re-run to retry): {missing[:8]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
