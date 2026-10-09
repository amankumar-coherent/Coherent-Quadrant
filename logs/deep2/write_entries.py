"""One-off: write the confirmed deep-search findings + AI Mode scores into the UK evidence sidecars."""
import glob
import json
from pathlib import Path

ROOT = Path(r"C:\Users\aman.kumar\Downloads\Coherent-Quadrant")
D = ROOT / "output/chatgpt_expand/connected_fleet_mobility_solutions_market_united_kingdom"
conf = {(j["company"], j["axis"], j["param"]): j["claims"]
        for j in json.load(open(ROOT / "logs/deep2/confirmed.json", encoding="utf-8"))}
sc = json.load(open(ROOT / "logs/deep2/rescored.json", encoding="utf-8"))
PR = "Based on primary research, the company has not disclosed"
WHY = {
    ("Contel Ltd", "y", "UK Market Share & Penetration"):
        f"The rating rests on the company's named UK clients across waste, highways and other fleet sectors, including Biffa, FCC Environment and Canenco. {PR} its total vehicles under management or its UK market share.",
    ("Terramar Networks Limited", "y", "UK Market Share & Penetration"):
        f"The rating rests on international humanitarian deployments such as Oxfam and a 2020 World Health Organization contract, rather than UK fleet counts. {PR} its UK vehicle connections or market share.",
    ("Fleet Software Solutions Ltd", "x", "Scalability & Interoperability"):
        f"The rating rests on the company's links from tracking data into CRM, payroll and maintenance systems and its flexible rolling contracts. {PR} API documentation or large multi-thousand vehicle deployments.",
    ("FFAVS Ltd", "y", "Revenue & Growth in UK"):
        f"The rating rests on a stable headcount of 22 employees in its filed accounts, with no revenue figures filed. {PR} UK-specific revenue, year-over-year growth, or profitability.",
    ("FFAVS Ltd", "y", "UK Market Share & Penetration"):
        f"The rating rests on the company's named UK clients and documented fleet rollouts such as OPEX Logistics (77 vehicles) and Bretts Transport (24 vehicles). {PR} its total vehicles under management or UK market share.",
    ("KONEXIT FLEET LTD", "y", "Revenue & Growth in UK"):
        f"The rating rests on an early-stage company's first large project, a Shippeo integration covering more than 500 trailers. {PR} revenue, year-over-year growth, or profitability.",
    ("KONEXIT FLEET LTD", "y", "Partnership & Channel Network"):
        f"The rating rests on the company's Shippeo integration, its Teltonika hardware launch and its Thames Valley Transport partnership. {PR} reseller, leasing or insurer channel partnerships.",
    ("Advanced Telematics Ltd", "x", "Data Security & Compliance"):
        f"The rating rests on the company's TASSA-certified and Thatcham-approved installation credentials. {PR} ISO 27001 or Cyber Essentials certification, encryption standards, or its data protection registration.",
    ("Franstrack Ltd", "y", "Partnership & Channel Network"):
        f"The rating rests on the company's hardware compatibility with Teltonika, Queclink, Concox and Digital Matter devices rather than formal channel partnerships. {PR} named resellers, OEM alliances, or co-marketing agreements.",
}
for side in glob.glob(str(D / "param_detail_prescored*.json")):
    part = json.load(open(side, encoding="utf-8"))
    dirty = False
    for key, claims in conf.items():
        co, ax, pn = key
        params = ((part.get(co) or {}).get(ax) or {}).get("parameters") or {}
        if pn in params:
            s = sc[f"{co}|{ax}|{pn}"]["score"]
            params[pn] = {"score": s, "evidence": [{"claim": c} for c in claims], "assessed_on": WHY[key]}
            dirty = True
            print(Path(side).name, co, pn, "->", s)
    if dirty:
        json.dump(part, open(side, "w", encoding="utf-8"), ensure_ascii=False)
