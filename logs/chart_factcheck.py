"""Read-only audit of a finished report's chart companies through Google AI Mode.

Per company: one status / ownership / HQ / scope question, then its specific
supporting points in batches of 5 -- each judged correct / incorrect /
unverified against published sources. Writes findings JSON; changes nothing.
Scope is judged against the market's own definition (the market brief in
_pipeline/market_brief.json when it exists, else Step 0c's analysis).

    python logs/chart_factcheck.py --market "X Market" --country global --slot 41 \
        --companies part.json --out findings_41.json
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ap = argparse.ArgumentParser()
ap.add_argument("--market", required=True)
ap.add_argument("--country", default="global")
ap.add_argument("--slot", type=int, required=True)
ap.add_argument("--companies", required=True, help="JSON list of chart company names (report 'company' field)")
ap.add_argument("--out", required=True)
args = ap.parse_args()
os.environ["GOOGLE_AI_MODE_PROFILE_DIR"] = str(ROOT / "data" / f"ai_mode_batch_{args.slot:02d}")
os.environ["GOOGLE_AI_MODE_BROWSER"] = "chromium"
os.environ["GOOGLE_AI_MODE_ENABLED"] = "true"

from vendor_intel.config import Settings  # noqa: E402
from vendor_intel.pipeline import chatgpt_expand as ce  # noqa: E402
from vendor_intel.pipeline.web_expand import default_output_dir  # noqa: E402

D = Path(default_output_dir(args.market, args.country))
q = json.loads(next(D.glob("*_quadrant.json")).read_text(encoding="utf-8"))
by = {b["company"]: b for b in q["brands"]}
brief_path = D / "_pipeline" / "market_brief.json"
if brief_path.exists():
    brief = json.loads(brief_path.read_text(encoding="utf-8"))
    definition, core = brief.get("market_definition", ""), brief.get("core_scope", "")
    adjacent = "; ".join(brief.get("adjacent_segments") or [])
else:
    ckpt = json.loads((D / "chatgpt_checkpoint_batch_all.json").read_text(encoding="utf-8"))
    ma = ckpt["data"].get("market_analysis") or {}
    definition, core = ma.get("market_definition", ""), ma.get("core_scope", "")
    adjacent = "; ".join(ma.get("adjacent_segments") or [])
companies = json.loads(Path(args.companies).read_text(encoding="utf-8"))
out_file = Path(args.out)
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


def specific(claim):
    return bool(re.search(r"\d|\"|“|‘|'[A-Z]|contract|awarded|partner|acquir|launched|won|selected|"
                          r"certif|ISO|approved|framework|customer|client|integrat", claim, re.I))


for name in companies:
    rec = done.get(name) or {}
    b = by.get(name) or {}
    if not rec.get("status"):
        got = ask(STATUS_SYS,
                  f"Market: {args.market}. Definition: {definition[:600]}\nCore players: {core[:500]}\n"
                  f"Adjacent segments: {adjacent[:300]}\n\nCompany: {name} (brand {b.get('brand')}), "
                  f"listed HQ {b.get('hq_location')}. Is it operating today, who owns it, where is its head "
                  "office, and is it core / adjacent / out for this market?",
                  f"status-{name[:20]}")
        rec["status"] = got[0] if got else {}
        rec["label"] = b.get("company")
        rec["listed_hq"] = b.get("hq_location")
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
    have = {c["claim"] for c in rec["claims"] if c.get("verdict")}
    rec["claims"] = [c for c in rec["claims"] if c.get("verdict")]
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
