#!/usr/bin/env python3
"""Fact-check a finished report's chart companies through Google AI Mode (read-only).

Per chart company: one question for operating status, owner, head office and
scope (core / adjacent / out against the market's own definition), then every
specific supporting point in batches of 5, each judged correct / incorrect /
unverified against published sources. Companies are split over N browsers
(one profile slot each); every answer is saved as it arrives, so a re-run only
asks what is still missing.

Nothing in the report changes. The findings are for an analyst: a verdict from
AI Mode is a lead, not a fact (it cites directory sites, and sometimes
contradicts itself), so a confirmed error goes into the market's
_pipeline/analyst_review.json ("corrections", "ownership", "scope") and the
pipeline is re-run.

    .venv\\Scripts\\python.exe scripts\\factcheck_chart.py --market "X Market" --country global ^
        --browsers 10 --slot-start 41

Output: <market>/_pipeline/factcheck/findings.json and findings.md (the review list).
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

STATUS_SYS = (
    "You are a market research analyst auditing a published market report. Use current, verifiable "
    "facts only (registries, insolvency notices, press releases, news). operating = active | "
    "in_administration | liquidated | dissolved | acquired_absorbed | renamed | unknown; event = the event "
    "and date if not active; current_name = the name it trades under today; owner = its parent company or "
    "majority owner today (empty if independent); owner_since = year; hq = its own head office as "
    "'City, Country'; main_product = what it mainly sells; scope = core | adjacent | out for the market "
    "below (core only when the market's product is a main product the company sells; adjacent when it is "
    "a minor feature of a different main product; out when it does not sell it at all or is a service "
    "firm); scope_reason = one sentence; evidence = one factual sentence with the source. Never guess. "
    "Compact JSON only: "
    '{"results":[{"operating":"...","event":"","current_name":"","owner":"","owner_since":"","hq":"",'
    '"main_product":"","scope":"","scope_reason":"","evidence":"..."}]}')
CLAIM_SYS = (
    "You are a fact-checker auditing a published market report. For EACH numbered claim about the "
    "company, check it against published sources (company site, press releases, filings, reputable news). "
    "verdict = correct (the source states it) | incorrect (a source contradicts a fact: date, number, name, "
    "title, client, status, or the claim belongs to another company) | unverified (no source states that "
    "detail). For incorrect, give corrected = the same sentence with only the wrong detail fixed; for "
    "unverified, name the unconfirmed detail in note. source = where you checked. Never guess. Compact "
    'JSON only: {"results":[{"n":1,"verdict":"correct|incorrect|unverified","corrected":"","note":"","source":""}]}')
def market_scope(out_dir: Path) -> tuple[str, str, str]:
    """Definition, core players and adjacent segments: the market brief when
    the client gave one, else Step 0c's own analysis."""
    brief = out_dir / "_pipeline" / "market_brief.json"
    if brief.exists():
        src = json.loads(brief.read_text(encoding="utf-8"))
    else:
        ckpt = json.loads((out_dir / "chatgpt_checkpoint_batch_all.json").read_text(encoding="utf-8"))
        src = ckpt.get("data", {}).get("market_analysis") or {}
    adjacent = src.get("adjacent_segments") or []
    return (str(src.get("market_definition") or ""), str(src.get("core_scope") or ""),
            "; ".join(adjacent) if isinstance(adjacent, list) else str(adjacent))


from vendor_intel.pipeline.factcheck import (  # noqa: E402
    applied_replacements, chart_rows, finished, key, merged_findings, specific_claims, was_checked)


def worker(args) -> int:
    """One browser: check the companies in --companies, saving to --out."""
    os.environ["GOOGLE_AI_MODE_PROFILE_DIR"] = str(ROOT / "data" / f"ai_mode_batch_{args.slot:02d}")
    os.environ["GOOGLE_AI_MODE_BROWSER"] = "chromium"
    os.environ["GOOGLE_AI_MODE_ENABLED"] = "true"
    from vendor_intel.config import Settings
    from vendor_intel.pipeline import chatgpt_expand as ce
    from vendor_intel.pipeline.web_expand import default_output_dir

    out_dir = Path(default_output_dir(args.market, args.country))
    by = {b["company"]: b for b in chart_rows(out_dir)}
    # The market brief's scope test applies here too: with "own_product_line" a
    # company that makes the market's product itself is core even when it is one
    # line of a larger business. The default main-product wording removed real
    # medical-film makers (sterilization-packaging film, coated medical films).
    brief_file = out_dir / "_pipeline" / "market_brief.json"
    brief = json.loads(brief_file.read_text(encoding="utf-8")) if brief_file.exists() else {}
    status_sys = STATUS_SYS
    if str(brief.get("scope_test") or "").strip().lower() == "own_product_line":
        status_sys = STATUS_SYS.replace(
            "(core only when the market's product is a main product the company sells; adjacent when it is "
            "a minor feature of a different main product; out when it does not sell it at all or is a service "
            "firm)",
            "(core when the company itself makes and sells the market's product under its own name, also when "
            "it is one product line of a larger business; adjacent when it does not make it itself -- it buys, "
            "converts for others, distributes or resells it -- or makes only a neighbouring product; out when it "
            "does not sell it at all or is a service firm)")
        assert status_sys != STATUS_SYS, "STATUS_SYS wording changed: update the own_product_line variant"
    skip = applied_replacements(out_dir / "_pipeline")
    definition, core, adjacent = market_scope(out_dir)
    names = json.loads(Path(args.companies).read_text(encoding="utf-8"))
    out_file = Path(args.out)
    done = json.loads(out_file.read_text(encoding="utf-8")) if out_file.exists() else {}
    client, model = ce._client(Settings()), ce._model(Settings())

    def ask(system: str, user: str, label: str) -> list[dict]:
        try:
            res = ce._chat_json(client, model, system, user, label=label, max_tokens=3000,
                                require_key="results")
            return [r for r in (res or {}).get("results") or [] if isinstance(r, dict)]
        except Exception as err:  # noqa: BLE001 -- one failed query must not stop the rest
            print("failed", label, err, flush=True)
            return []

    def save() -> None:
        tmp = out_file.with_name(out_file.name + ".tmp")
        tmp.write_text(json.dumps(done, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, out_file)

    for name in names:
        b = by.get(name) or {}
        rec = done.setdefault(name, {})
        if not rec.get("status"):
            got = ask(status_sys,
                      f"Market: {args.market}. Definition: {definition[:600]}\nCore players: {core[:500]}\n"
                      f"Adjacent segments: {adjacent[:300]}\n\nCompany: {name} (brand {b.get('brand')}), "
                      f"listed HQ {b.get('hq_location')}. Is it operating today, who owns it, where is its "
                      "head office, and is it core / adjacent / out for this market?",
                      f"status-{name[:20]}")
            rec.update({"status": got[0] if got else {}, "listed_hq": b.get("hq_location")})
            save()
        rec["claims"] = [c for c in rec.get("claims") or [] if c.get("verdict")]
        have = {c["claim"] for c in rec["claims"]}
        todo = [c for c in specific_claims(b, skip) if not was_checked(c["claim"], have)]
        for i in range(0, len(todo), 5):
            chunk = todo[i:i + 5]
            got = ask(CLAIM_SYS, f"Company: {name} ({b.get('brand')}), {b.get('hq_location')}.\nClaims:\n"
                      + "\n".join(f"{k + 1}. {c['claim']}" for k, c in enumerate(chunk)),
                      f"claims-{name[:14]}-{i // 5 + 1}")
            byn = {int(r["n"]): r for r in got if str(r.get("n") or "").isdigit()}
            for k, c in enumerate(chunk, 1):
                r = byn.get(k) or {}
                if r.get("verdict"):
                    rec["claims"].append({**c, **{f: r.get(f, "") for f in ("verdict", "corrected", "note", "source")}})
            save()
            print("saved", name, len(rec["claims"]), flush=True)
    print("finished", flush=True)
    return 0


def write_review(work: Path, rows: list[dict], merged: dict) -> Path:
    """findings.md: what an analyst has to look at, company by company."""
    lines = ["# Chart fact-check (Google AI Mode) -- leads for analyst review", ""]
    for b in rows:
        rec = merged.get(key(b["company"])) or {}
        s = rec.get("status") or {}
        lines.append(f"## {b['company']}")
        lines.append(f"- scope: **{s.get('scope', '?')}** -- {s.get('scope_reason', '')}")
        lines.append(f"- status: {s.get('operating', '?')} {s.get('event', '')}".rstrip())
        lines.append(f"- owner today: {s.get('owner') or 'independent'} {s.get('owner_since', '')}".rstrip())
        if s.get("hq") and s.get("hq") != rec.get("listed_hq"):
            lines.append(f"- HQ: report says {rec.get('listed_hq')}, AI Mode says {s.get('hq')}")
        for c in rec.get("claims") or []:
            if c.get("verdict") == "incorrect" and c.get("corrected") and c["corrected"] != c["claim"]:
                lines += [f"- INCORRECT [{c['parameter']}]: {c['claim']}",
                          f"  - suggested: {c['corrected']}", f"  - source: {c.get('source', '')}"]
        lines.append("")
    path = work / "findings.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", required=True)
    ap.add_argument("--country", default="global")
    ap.add_argument("--browsers", type=int, default=10)
    ap.add_argument("--slot-start", type=int, default=41)
    ap.add_argument("--stagger", type=float, default=10.0, help="seconds between browser launches")
    # worker mode (one browser), started by the coordinator below
    ap.add_argument("--slot", type=int, default=0, help=argparse.SUPPRESS)
    ap.add_argument("--companies", default="", help=argparse.SUPPRESS)
    ap.add_argument("--out", default="", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.companies:
        return worker(args)

    from vendor_intel.pipeline.web_expand import default_output_dir

    out_dir = Path(default_output_dir(args.market, args.country))
    work = out_dir / "_pipeline" / "factcheck"
    work.mkdir(parents=True, exist_ok=True)
    rows = chart_rows(out_dir)
    merged = merged_findings(work)
    skip = applied_replacements(out_dir / "_pipeline")
    todo = [b["company"] for b in rows if not finished(b, merged.get(key(b["company"])), skip)]
    print(f"[factcheck] {len(rows) - len(todo)} of {len(rows)} chart companies already checked; "
          f"{len(todo)} on {min(args.browsers, len(todo))} browsers", flush=True)
    # Keep one merged file; per-browser files are rebuilt for this run's split.
    (work / "findings.json").write_text(json.dumps(merged, indent=1, ensure_ascii=False), encoding="utf-8")
    for old in [*work.glob("findings_*.json"), *work.glob("companies_*.json")]:
        if old.name != "findings_all.json":
            old.unlink()
    (work / "findings_all.json").write_text(json.dumps(merged, indent=1, ensure_ascii=False), encoding="utf-8")
    procs = []
    n = min(args.browsers, len(todo))
    for i in range(n):
        names = todo[i::n]
        part = work / f"companies_{i + 1}.json"
        part.write_text(json.dumps(names, ensure_ascii=False), encoding="utf-8")
        out = work / f"findings_{i + 1}.json"
        out.write_text(json.dumps({k: merged[key(k)] for k in names if key(k) in merged}, ensure_ascii=False),
                       encoding="utf-8")
        log = (work / f"browser_{i + 1}.log").open("a", encoding="utf-8")
        procs.append(subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--market", args.market, "--country", args.country,
             "--slot", str(args.slot_start + i), "--companies", str(part), "--out", str(out)],
            cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT, env={**os.environ, "PYTHONIOENCODING": "utf-8"}))
        print(f"browser {i + 1}: slot {args.slot_start + i}, {names}", flush=True)
        time.sleep(args.stagger)
    for p in procs:
        p.wait()
    merged = merged_findings(work)
    (work / "findings.json").write_text(json.dumps(merged, indent=1, ensure_ascii=False), encoding="utf-8")
    md = write_review(work, rows, merged)
    left = [b["company"] for b in rows if not finished(b, merged.get(key(b["company"])), skip)]
    print(f"[factcheck] done: {len(rows) - len(left)} of {len(rows)} complete -> {md}"
          + (f"; still missing (re-run to resume): {left}" if left else ""), flush=True)
    return 0 if not left else 1


if __name__ == "__main__":
    raise SystemExit(main())
