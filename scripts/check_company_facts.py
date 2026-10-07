#!/usr/bin/env python3
"""Google AI Mode fact checks for the chatgpt_expand quadrant pipeline (step 3c).

--mode ownership  has each company been acquired, by whom, is it still trading
                  under its own name? 10 companies per query; unclear answers
                  are asked again one company at a time.
--mode identity   one company per query: does it exist, is the listed website
                  its own, is it active, is it in this market?
--mode scope      10 companies per query: core player, adjacent-segment player
                  (kept off the chart) or not in this market?
--mode hq         single-country runs, 10 per query: is the company's own head
                  office in that country, or is it a foreign company's branch?

Run by run_quadrant_pipeline.py across browser slots (--shard/--shards/
--only-file, like the other sharded steps). Each shard saves to
_pipeline/facts_<mode>_shard<N>.json; the orchestrator merges them into
_pipeline/ownership.json / identity_check.json. Resumable: names already
answered (merged or in this shard's file) are skipped.
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
OWN_KEYS = ("acquired", "acquirer", "year", "today", "note", "current_name", "brand_status")
SCOPE_KEYS = ("scope", "reason")
ID_KEYS = ("exists", "website_is_theirs", "website_owner", "operating", "event", "year",
           "in_market", "evidence")


def log(msg: str) -> None:
    print(f"[facts {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", required=True)
    ap.add_argument("--country", default="global")
    ap.add_argument("--mode", choices=("ownership", "identity", "scope", "hq"), required=True)
    ap.add_argument("--slot", type=int, default=41)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--only-file", required=True, help="JSON list of company names")
    args = ap.parse_args()

    os.environ["GOOGLE_AI_MODE_PROFILE_DIR"] = str(ROOT / "data" / f"ai_mode_batch_{args.slot:02d}")
    os.environ["GOOGLE_AI_MODE_BROWSER"] = "chromium"
    os.environ["GOOGLE_AI_MODE_ENABLED"] = "true"

    from vendor_intel.config import Settings
    from vendor_intel.pipeline import chatgpt_expand as ce
    from vendor_intel.pipeline import company_facts as cf
    from vendor_intel.pipeline.quadrant_pipeline import norm_name, row_name, row_website
    from vendor_intel.pipeline.web_expand import default_output_dir

    out_dir = Path(default_output_dir(args.market, args.country))
    pipe = out_dir / "_pipeline"
    state = json.loads((out_dir / "chatgpt_checkpoint_batch_all.json").read_text(encoding="utf-8"))
    data = state.get("data") or {}
    scope = str((data.get("market_analysis") or {}).get("market_definition") or "").strip()
    rows = {row_name(r): r for r in data.get("verified") or []}

    names = json.loads(Path(args.only_file).read_text(encoding="utf-8")) or []
    names = names[args.shard::max(1, args.shards)]
    merged_file = pipe / {"ownership": cf.OWNERSHIP_FILE, "identity": cf.IDENTITY_FILE,
                          "scope": cf.SCOPE_FILE, "hq": cf.HQ_FILE}[args.mode]
    merged = json.loads(merged_file.read_text(encoding="utf-8")) if merged_file.exists() else {}
    out = pipe / f"facts_{args.mode}_shard{args.shard}.json"
    done = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    client, model = ce._client(Settings()), ce._model(Settings())

    def save() -> None:
        out.write_text(json.dumps(done, indent=2, ensure_ascii=False), encoding="utf-8")

    def ask(system: str, user: str, label: str) -> list[dict]:
        try:
            res = ce._chat_json(client, model, system, user, label=label,
                                max_tokens=3000, require_key="results")
        except Exception as err:  # noqa: BLE001 -- one failed query must not stop the run
            log(f"{label} failed: {err}")
            return []
        return [r for r in (res or {}).get("results") or [] if isinstance(r, dict)]

    def web(n: str) -> str:
        return row_website(rows.get(n) or {})

    def brand(n: str) -> str:
        r = rows.get(n) or {}
        b = str(r.get("brand_name") or r.get("brand") or r.get("Brand") or "").strip()
        return b if b and norm_name(b) != norm_name(n) else ""

    if args.mode == "ownership":
        system = cf.ownership_prompt(args.market, scope)
        todo = [n for n in names if n not in done and n not in merged]
        log(f"ownership: {len(names)} companies, {len(todo)} to check")
        for i in range(0, len(todo), BATCH):
            chunk = todo[i: i + BATCH]
            payload = [{"name": n, **({"brand": brand(n)} if brand(n) else {}), "website": web(n)}
                       for n in chunk]
            got = ask(system, "Companies:\n" + json.dumps(payload, ensure_ascii=False), f"own-{i // BATCH + 1}")
            by = {norm_name(str(r.get("name") or "")): r for r in got}
            for n in chunk:
                if norm_name(n) in by:
                    done[n] = {k: by[norm_name(n)].get(k, "") for k in OWN_KEYS}
            save()
        # Batch answers that could not place a company: ask about it alone.
        unclear = [n for n in names if n in done and cf.is_unclear(done[n]) and not done[n].get("_single")]
        log(f"ownership: {len(unclear)} unclear, asking one at a time")
        for n in unclear:
            got = ask(system, cf.ownership_question(n, web(n)), f"own-one-{n[:20]}")
            if got:
                done[n] = {k: got[0].get(k, "") for k in OWN_KEYS} | {"_single": True}
            else:
                done[n]["_single"] = True
            save()
    elif args.mode == "hq":
        system = cf.hq_prompt(args.market, args.country)
        todo = [n for n in names if n not in done and n not in merged]
        log(f"hq: {len(todo)} companies to check")
        for i in range(0, len(todo), BATCH):
            chunk = todo[i: i + BATCH]
            payload = [{"name": n, "website": web(n)} for n in chunk]
            got = ask(system, "Companies:\n" + json.dumps(payload, ensure_ascii=False), f"hq-{i // BATCH + 1}")
            by = {norm_name(str(r.get("name") or "")): r for r in got}
            for n in chunk:
                r = by.get(norm_name(n))
                if r:
                    done[n] = {k: str(r.get(k, "")).strip() for k in ("hq", "in_country", "evidence")}
            save()
    elif args.mode == "scope":
        analysis = data.get("market_analysis") or {}
        system = cf.scope_prompt(args.market, scope, str(analysis.get("core_scope") or ""),
                                 analysis.get("adjacent_segments") or [])
        todo = [n for n in names if n not in done and n not in merged]
        log(f"scope: {len(todo)} companies to check")
        for i in range(0, len(todo), BATCH):
            chunk = todo[i: i + BATCH]
            payload = [{"name": n, "website": web(n)} for n in chunk]
            got = ask(system, "Companies:\n" + json.dumps(payload, ensure_ascii=False), f"scope-{i // BATCH + 1}")
            by = {norm_name(str(r.get("name") or "")): r for r in got}
            for n in chunk:
                r = by.get(norm_name(n))
                if r and str(r.get("scope") or "").strip().lower() in cf.SCOPES:
                    done[n] = {k: str(r.get(k, "")).strip() for k in SCOPE_KEYS}
            save()
    else:
        system = cf.identity_prompt(args.market, scope)
        todo = [n for n in names if n not in done and n not in merged]
        log(f"identity: {len(todo)} companies to check")
        for n in todo:
            r = rows.get(n) or {}
            hq = str(r.get("headquarters") or r.get("Headquarters") or "")
            got = ask(system, cf.identity_question(n, args.market, web(n), hq), f"id-{n[:20]}")
            if got:
                done[n] = {k: got[0].get(k, "") for k in ID_KEYS}
                save()
    log(f"{args.mode}: {len(done)} answers saved -> {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
