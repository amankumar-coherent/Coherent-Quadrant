"""One-off deeper re-ask of one (company, parameter); writes only if real evidence comes back."""
import json, os, sys
from pathlib import Path
ROOT = Path(r"C:\Users\aman.kumar\Downloads\Coherent-Quadrant")
sys.path.insert(0, str(ROOT / "src")); sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ["GOOGLE_AI_MODE_PROFILE_DIR"] = str(ROOT / "data" / "ai_mode_batch_49")
os.environ["GOOGLE_AI_MODE_BROWSER"] = "chromium"; os.environ["GOOGLE_AI_MODE_ENABLED"] = "true"
from vendor_intel.quadrant.ai_mode_scorer import build_forced_score_query, parse_small_group_scores
from vendor_intel.scraping.google_ai_mode import ask
D = ROOT / "output/chatgpt_expand/connected_fleet_mobility_solutions_market_united_kingdom"
NAME, AX, PN = "Journease Software Limited", "y", "UK Market Share & Penetration"
spec = json.loads((D / "_pipeline/axes_spec.json").read_text(encoding="utf-8"))
HINT = ("Bristol, UK; journease.com. Search deeply for UK market presence proxies: named UK customers "
        "(councils, NHS trusts, schools, transport operators, logistics firms), number of users, vehicles, "
        "drivers or journeys managed, published case studies, tenders or framework awards (Contracts Finder, "
        "Find a Tender, G-Cloud), Companies House accounts (turnover, headcount), customer count claims, "
        "awards. Each Evidence line must be one specific fact with its source")
q = build_forced_score_query(NAME, PN, spec["parameter_definitions"][AX], market=spec.get("market") or
                             "Connected Fleet Mobility Solutions Market (United Kingdom)",
                             market_definition=str(spec.get("market_definition") or ""), context=HINT)
print(len(q), "chars")
for attempt in range(2):
    ans = ask(q)
    got = parse_small_group_scores(ans, [PN], q).get(PN) if ans else None
    print("ANSWER:\n", ans[:2500] if ans else ans)
    if got and got.get("evidence") and any(str(e.get("claim", "")).strip() != "Not available" for e in got["evidence"]):
        break
print("PARSED:", json.dumps(got, ensure_ascii=False, indent=1))
real = got and any(str(e.get("claim", "")).strip() != "Not available" for e in got.get("evidence") or [])
if real and got.get("assessed_on") and "--write" in sys.argv:
    for side in D.glob("param_detail_prescored*.json"):
        part = json.loads(side.read_text(encoding="utf-8"))
        v = ((part.get(NAME) or {}).get(AX) or {}).get("parameters", {}).get(PN)
        if v is not None:
            part[NAME][AX]["parameters"][PN] = got
            side.write_text(json.dumps(part, ensure_ascii=False), encoding="utf-8"); print("wrote", side.name)
