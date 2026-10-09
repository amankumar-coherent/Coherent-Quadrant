"""One-off audit of the UK Connected Fleet chart companies (read-only).

For each company given: one status question, one ownership question, then its
specific supporting points in batches of 5 -- each judged correct / incorrect /
unverified against published sources. Writes findings JSON; changes nothing.

    python logs/uk_fleet_factcheck.py <slot> <companies.json> <out.json>
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\aman.kumar\Downloads\Coherent-Quadrant")
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
slot, comp_file, out_file = int(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
os.environ["GOOGLE_AI_MODE_PROFILE_DIR"] = str(ROOT / "data" / f"ai_mode_batch_{slot:02d}")
os.environ["GOOGLE_AI_MODE_BROWSER"] = "chromium"
os.environ["GOOGLE_AI_MODE_ENABLED"] = "true"

from vendor_intel.config import Settings  # noqa: E402
from vendor_intel.pipeline import chatgpt_expand as ce  # noqa: E402

MARKET = "Connected Fleet Mobility Solutions Market (United Kingdom)"
D = ROOT / "output/chatgpt_expand/connected_fleet_mobility_solutions_market_united_kingdom"
q = json.loads((D / "connected_fleet_mobility_solutions_market_united_kingdom_quadrant.json").read_text(encoding="utf-8"))
by = {b.get("company_key") or b["company"]: b for b in q["brands"]}
companies = json.loads(comp_file.read_text(encoding="utf-8"))
done = json.loads(out_file.read_text(encoding="utf-8")) if out_file.exists() else {}
client, model = ce._client(Settings()), ce._model(Settings())


def ask(system, user, label):
    try:
        res = ce._chat_json(client, model, system, user, label=label, max_tokens=3000, require_key="results")
        return [r for r in (res or {}).get("results") or [] if isinstance(r, dict)]
    except Exception as err:  # noqa: BLE001
        print("failed", label, err, flush=True)
        return []


STATUS_SYS = (
    "You are a market research analyst auditing a published market report. Use current, "
    "verifiable facts only (Companies House, administration/liquidation notices, press releases, news). "
    "For the company: operating = active | in_administration | liquidated | dissolved | acquired_absorbed | "
    "renamed | unknown; event = the event and date if not active; current_name = the name it trades under "
    "today; owner = its parent company today (empty if independent); owner_since = year; evidence = one "
    "factual sentence with the source. Never guess. Compact JSON only: "
    '{"results":[{"operating":"...","event":"","current_name":"","owner":"","owner_since":"","evidence":"..."}]}')
CLAIM_SYS = (
    "You are a fact-checker auditing a published market report. For EACH numbered claim about the "
    "company, check it against published sources (company site, press releases, filings, reputable news). "
    "verdict = correct (the source states it) | incorrect (a source contradicts a fact: date, number, name, "
    "title, client, status) | unverified (no source states that detail -- e.g. an exact figure or "
    "'directly awarded'). For incorrect, give corrected = the same sentence with only the wrong detail "
    "fixed; for unverified, name the unconfirmed detail in note. source = where you checked. Never guess; "
    "a claim with an unconfirmed specific is unverified, not correct. Compact JSON only: "
    '{"results":[{"n":1,"verdict":"correct|incorrect|unverified","corrected":"","note":"","source":""}]}')


def specific(claim):
    return bool(re.search(r"\d|\"|“|‘|'[A-Z]|contract|awarded|partner|acquir|launched|won|selected|"
                          r"certif|ISO|approved|framework", claim, re.I))


for name in companies:
    rec = done.get(name) or {}
    b = by.get(name) or {}
    if "status" not in rec:
        got = ask(STATUS_SYS, f"Company: {name} (brand {b.get('brand')}), HQ {b.get('hq_location')}, "
                              f"listed in the {MARKET}. Is it operating today and who owns it?",
                  f"status-{name[:20]}")
        rec["status"] = got[0] if got else {}
        rec["label"] = b.get("company")
        done[name] = rec
        out_file.write_text(json.dumps(done, indent=1, ensure_ascii=False), encoding="utf-8")
    claims = []
    for ax in ("x", "y"):
        for pn, v in (((b.get("score_detail") or {}).get(ax) or {}).get("parameters") or {}).items():
            for e in v.get("evidence") or []:
                c = str(e.get("claim") or "")
                if c and c != "Not available" and specific(c):
                    claims.append({"parameter": pn, "claim": c})
    rec.setdefault("claims", [])
    have = {c["claim"] for c in rec["claims"]}
    todo = [c for c in claims if c["claim"] not in have]
    for i in range(0, len(todo), 5):
        chunk = todo[i:i + 5]
        user = (f"Company: {name} ({b.get('brand')}), {b.get('hq_location')}.\nClaims:\n"
                + "\n".join(f"{k + 1}. {c['claim']}" for k, c in enumerate(chunk)))
        got = ask(CLAIM_SYS, user, f"claims-{name[:14]}-{i // 5 + 1}")
        byn = {int(r.get("n") or 0): r for r in got if str(r.get("n") or "").isdigit()}
        for k, c in enumerate(chunk, 1):
            r = byn.get(k) or {}
            rec["claims"].append({**c, "verdict": r.get("verdict", ""), "corrected": r.get("corrected", ""),
                                  "note": r.get("note", ""), "source": r.get("source", "")})
        out_file.write_text(json.dumps(done, indent=1, ensure_ascii=False), encoding="utf-8")
        print("saved", name, len(rec["claims"]), flush=True)
print("finished", flush=True)
