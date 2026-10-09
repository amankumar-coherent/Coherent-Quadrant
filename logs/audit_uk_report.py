"""Read-only audit of the finished UK Connected Fleet report against every rule the
report owner set (wording, competitors, Marine audit workbook issue types, Marine
review comments). Prints one section per rule with every hit."""
import html as htmlmod
import json
import re
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\aman.kumar\Downloads\Coherent-Quadrant")
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from vendor_intel.pipeline.company_facts import (cites_employee_reviews, cites_estimate_site,  # noqa: E402
                                                 cites_research_publisher)

D = ROOT / "output/chatgpt_expand/connected_fleet_mobility_solutions_market_united_kingdom"
SLUG = "connected_fleet_mobility_solutions_market_united_kingdom"
q = json.loads((D / f"{SLUG}_quadrant.json").read_text(encoding="utf-8"))
page = (D / f"{SLUG}_report_classic.html").read_text(encoding="utf-8")
text = htmlmod.unescape(re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S))
text = re.sub(r"<[^>]+>", " ", text)
text = re.sub(r"\s+", " ", text)
PR = "Based on primary research, the company has not disclosed"

chart = [b for b in q["brands"] if b.get("on_chart")]
texts = []  # (company, parameter, kind, text, on_chart)
for b in q["brands"]:
    for ax in ("x", "y"):
        for pn, v in ((b.get("score_detail") or {}).get(ax) or {}).get("parameters", {}).items():
            for e in v.get("evidence") or []:
                texts.append((b["company_key"], pn, "EV", str(e.get("claim") or ""), bool(b.get("on_chart"))))
            texts.append((b["company_key"], pn, "WHY", str(v.get("assessed_on") or ""), bool(b.get("on_chart"))))

RULES = {
    "1 gap wording not in house style ('not publicly', 'no evidence', 'could not' ...)": re.compile(
        r"not (?:been )?publicly|publicly (?:reported|disclosed|available|documented)|does not (?:publicly )?disclose|"
        r"do not (?:publicly )?disclose|not disclosed by|could not|unable to|cannot be (?:verified|confirmed)|"
        r"no (?:public|publicly)|no evidence|no (?:specific|direct|verifiable|documented|independent) evidence|"
        r"found no|were not found|was not found|not found in|no information|no data (?:is|are|was|were)|"
        r"limited (?:public )?information|in the public domain|not (?:made )?public\b|is unknown|remain(?:s)? unclear|"
        r"not available in|not specified|not stated|undisclosed|absence of", re.I),
    "2 desk-research wording": re.compile(r"desk[- ]research", re.I),
    "3 first person / 'We verified that the rating'": re.compile(
        r"\bI (?:verified|found|searched|confirmed|could|was|have|am|think|believe)\b|\bmy (?:search|research)\b|"
        r"We (?:verified|found|confirmed|noted) that (?:the|our) (?:rating|assessment|score|evaluation)", re.I),
    "4 hedge words": re.compile(r"\b(?:appears to|appear to|seems to|it seems|likely|possibly|presumably|reportedly|"
                                r"may have|might|purportedly|allegedly|unconfirmed|unverified)\b", re.I),
    "5 citation leftovers / prompt leakage": re.compile(
        r"\[\s*\d+(?:\.\d+)?(?:\s*,\s*\d+(?:\.\d+)?)*\s*\]|[\[(]\s*https?://|\]\(|\s\+\d+\s*$|Show all|"
        r"<[a-z ]+>|\bNN\b|Score:\s*\d|Evidence:|Assessed on:|WHAT THIS MEASURES|SCORING SCALE", re.I),
    "6 'verified' on a company's own claim": re.compile(
        r"verified to be|it was verified|verified presence|records verify|as verified by|independently verified that "
        r"the company reports|The company reports[^.]*\bverified\b", re.I),
    "7 status 'completed' (check the source calls it completed)": re.compile(
        r"\bcomplet(?:ed|ion)\b|\bfinished\b|\bsuccessfully delivered\b", re.I),
    "8 score-band jargon": re.compile(r"\b\d{2}\s*[-–]\s*\d{2,3}\b band|market-leading band|1-39 band|"
                                      r"\bband\b of|score band", re.I),
    "9 old gap template ('This is not disclosed by the company, so')": re.compile(
        r"This is not disclosed by the company|not disclosed by the company, so", re.I),
}
for name, rx in RULES.items():
    hits = [(c, p, k, t) for c, p, k, t, oc in texts if t and t != "Not available" and rx.search(t)]
    hits_chart = [h for h in hits if h[0] in {b["company_key"] for b in chart}]
    print(f"\n#### {name}: {len(hits_chart)} on chart / {len(hits)} in whole report")
    for c, p, k, t in hits_chart[:40]:
        m = rx.search(t)
        print(f"   - {c} | {p} | {k} | «{m.group(0)}» | {t[:220]}")

print("\n#### 10 competitor research firms named (config/research_publishers.txt)")
pub = [(c, p, t) for c, p, k, t, oc in texts if cites_research_publisher(t)]
print("   evidence/why:", len(pub), pub[:5])
print("   page text:", cites_research_publisher(text))
generic_pub = re.findall(r"[A-Z][\w&]+(?: [A-Z][\w&]+)* (?:Research|Insights|Intelligence|Consulting|Analytics)\b", text)
print("   names ending Research/Insights/Intelligence (review):", sorted(set(generic_pub))[:40])

print("\n#### 11 employee-review / modelled-estimate sites")
print("   employee:", [(c, p) for c, p, k, t, oc in texts if cites_employee_reviews(t)][:5])
print("   estimate:", [(c, p) for c, p, k, t, oc in texts if cites_estimate_site(t)][:5])

print("\n#### 12 axis titles (Marine review: 'Product Strength' shown) -- expected Technology / Business Capability")
for w in ("Product Strength", "Business Strength", "Product Capability", "Service Capability",
          "Technology Capability", "Business Capability"):
    print(f"   {w!r}: {text.count(w)} in page | axis_titles: {json.dumps(q.get('axis_titles'), ensure_ascii=False)[:160] if w == 'Product Strength' else ''}")

print("\n#### 13 gap sentences in house style per chart company (WHY lines)")
for b in chart:
    whys = [t for c, p, k, t, oc in texts if c == b["company_key"] and k == "WHY"]
    print(f"   {b['brand'][:28]:28} WHY lines {len(whys)}, with house gap sentence {sum(PR in w for w in whys)}")

print("\n#### 14 'Not available' rules (absence-only bullet; never beside a finding; once)")
bad = []
for b in chart:
    for ax in ("x", "y"):
        for pn, v in b["score_detail"][ax]["parameters"].items():
            cs = [e.get("claim") for e in v.get("evidence") or []]
            if cs.count("Not available") and (len(cs) > 1):
                bad.append((b["brand"], pn, cs))
            for c in cs:
                if c and c != "Not available" and re.match(r"(?:None|No|Not)\b", c):
                    bad.append((b["brand"], pn, c[:120]))
print("  ", bad or "none")

print("\n#### 15 duplicate bullets inside a parameter")
dups = []
for b in chart:
    for ax in ("x", "y"):
        for pn, v in b["score_detail"][ax]["parameters"].items():
            cs = [re.sub(r"\W+", " ", (e.get("claim") or "").lower()).strip() for e in v.get("evidence") or []]
            if len(cs) != len(set(cs)):
                dups.append((b["brand"], pn))
print("  ", dups or "none")

print("\n#### 16 stale evidence (chart companies whose dated bullets are mostly 2021 or older)")
for b in chart:
    yrs = [int(y) for c, p, k, t, oc in texts if c == b["company_key"] and k == "EV"
           for y in re.findall(r"\b(20[0-2]\d)\b", t)]
    if yrs:
        old = sum(y <= 2021 for y in yrs)
        if old / len(yrs) >= 0.5:
            print(f"   {b['brand']}: {old}/{len(yrs)} dated mentions are 2021 or older")

print("\n#### 17 ownership labels: 'acquired by' only for deals under 3 years old")
P = D / "_pipeline"
own = json.loads((P / "ownership.json").read_text(encoding="utf-8"))
review = json.loads((P / "analyst_review.json").read_text(encoding="utf-8"))
rev_own = {o["company"]: o for o in review.get("ownership") or []}
for b in chart:
    o = rev_own.get(b["company_key"]) or own.get(b["company_key"]) or {}
    if "(" in b["company"] or o.get("acquired"):
        print(f"   {b['company']} | year {o.get('year')} | today {o.get('today', '')}")

print("\n#### 18 HQ present and in the UK (single-country run)")
print("  ", [(b["brand"], b.get("hq_location")) for b in chart
             if not b.get("hq_location") or "United Kingdom" not in str(b.get("hq_location"))] or "all chart HQs in the UK")

print("\n#### 19 report-wide text (definitions, methodology) for gap / hedge / competitor wording")
other = json.dumps({k: q.get(k) for k in ("quadrant_definitions", "research_methodology", "criteria")}, ensure_ascii=False)
for name, rx in list(RULES.items())[:4]:
    m = rx.findall(other)
    if m:
        print(f"   {name}: {sorted(set(m))[:10]}")
