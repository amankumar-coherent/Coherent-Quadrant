"""One-off: factcheck6 findings -> UK analyst_review.json corrections + owner labels (market data only)."""
import glob
import json
from pathlib import Path

ROOT = Path(r"C:\Users\aman.kumar\Downloads\Coherent-Quadrant")
claims = {}
for f in glob.glob(str(ROOT / "logs/factcheck6/out_*.json")):
    for n, r in json.load(open(f, encoding="utf-8")).items():
        claims[n] = [c["claim"] for c in r.get("claims", [])]


def full(co, start):
    m = [v for v in claims.get(co, []) if v.startswith(start)]
    assert len(m) == 1, (co, start, len(m))
    return m[0]


FX = []


def whole(co, start, new, why):
    FX.append((co, full(co, start), new, why))


def part(co, start, find, new, why):
    assert find in full(co, start), (co, find)
    FX.append((co, find, new, why))


QX, AM, CT, VU, RT, NV = ("Quartix Limited", "Airmax Remote Limited", "Ctrack UK Limited", "VUE Group",
                          "Redtail Telematics Limited", "Navstar")
part(QX, "The company reports that its core tracking devices (TCSV11", "(1Hz event monitoring)", "(10Hz event monitoring)",
     "100ms sampling is 10Hz")
part(QX, "The company reports that its global fleet subscription base reached",
     ", with UK operations generating £18.0 million out of £35.7 million in total group revenue,", ",",
     "UK revenue split unconfirmed")
whole(QX, "The company reports in its H1 2026 interim results presentation", "", "UK ARR and dashcam contribution unconfirmed")
part(AM, "Airmax Remote Limited has achieved and continuously maintained", "(first attained in 2019)",
     "(first attained in 2013)", "ISO 27001 first attained in 2013")
part(AM, "Airmax Remote reports that its Airmax Connect", "a driver license data integration partnership",
     "a driver behaviour data integration partnership", "Licence Check integration shares driver behaviour data")
whole(AM, "Financial statements submitted to Companies House for the period ending 31 March 2025", "",
      "Net worth and asset figures unconfirmed")
part(AM, "A five-year contract valued at an estimated", " starting in April 2026", "", "Start date unconfirmed")
part(CT, "The company reports offering secure telematics API connections", "to stream real-time fleet analytics",
     "to share real-time tracking data with its workforce management solution", "Announcement: real-time tracking data")
part(CT, "RDM Electrical & Mechanical Services deployed",
     "to monitor driver behaviour, vehicle utilisation, and fuel efficiency metrics",
     "to monitor vehicle operations, unauthorised use, job allocation and fuel consumption", "Source lists these uses")
part(CT, "Public sector procurement records show Ctrack UK Limited", "published on February 3, 2026",
     "published on March 25, 2026", "Notice published 25 March 2026")
part(CT, "The company reports that its telematics tracking systems are deployed in over 1.2 million vehicles",
     "more than 50 countries", "more than 60 countries", "60+ countries")
whole(CT, "The company reports providing 24/7 customer ticketing availability",
      "The company reports providing a Customer Self-Service Portal integrated with its internal CRM system.",
      "24/7 availability and 'no offshore call centres' unconfirmed for Ctrack UK")
part(VU, "In a fleet management deployment for the UK Ministry of Defence",
     " to feed real-time convoy tracking data directly to the VUEhub operations portal", "",
     "VUEhub detail unconfirmed")
whole(VU, "VUE Group implemented customized cybersecurity measures", "", "Cybersecurity/GDPR project claim unconfirmed")
whole(RT, "The company reports that its VAM-HDR quick-fit tracking device",
      "The company reports that its VAM-HDR quick-fit tracking device supports LTE Cat-M cellular connectivity with a standard 1 Hz GPS refresh rate.",
      "NB-IoT and internal antenna details unconfirmed")
whole(RT, "Redtail Telematics maintains an operational software integration with Route4Me", "",
      "No Route4Me integration")
whole(RT, "The company reports its VAM onboard hardware device family",
      "The company reports its VAM onboard hardware family, including the VAM-HUB, VAM-OBD, VAM-HDR and the IP67-rated solar-augmented VAM-Rugged.",
      "Device role descriptions unconfirmed")
whole(RT, "Redtail Telematics Limited provides ready-made telematics gateways", "", "Route4Me integration unverified")
part(RT, "The company achieved a total annual turnover of £11.4 million", "61.11%", "61%", "Index reports 61%")
part(RT, "Official registry filings from Companies House confirm", " with a recorded headcount of fewer than 50 employees", "",
     "Headcount unconfirmed")
part(NV, "The company reports that its technology offerings include 4G/GPS", "as stated in the Navstar Tracking Privacy Policy",
     "as stated on the Our Products page of the Navstar Tracking website", "Source is the Our Products page")
whole(NV, "Telco NE Ltd, the operator of Navstar Vehicle Tracking", "", "O2 partnership unconfirmed")
whole(NV, "The company reports offering its basic GO GPS vehicle tracking",
      "The company reports offering basic GO GPS self-fit vehicle tracking systems on its official product website.",
      "Price unconfirmed")

p = ROOT / "output/chatgpt_expand/connected_fleet_mobility_solutions_market_united_kingdom/_pipeline/analyst_review.json"
r = json.loads(p.read_text(encoding="utf-8"))
SRC = "AI Mode fact-check of chart entrants (logs/factcheck6), 2026-10-02"
have = {(c["company"], c["find"]) for c in r["corrections"]}
n = 0
for co, f, rep, why in FX:
    if (co, f) not in have:
        r["corrections"].append({"company": co, "find": f, "replace": rep, "reason": why, "source": SRC})
        n += 1
own = [o for o in r.setdefault("ownership", []) if o.get("company") not in (CT, VU)]
own += [{"company": CT, "owner": "Convergence Partners", "year": "2024", "reason": "Ctrack acquired by Convergence Partners",
         "source": "AI Mode fact-check (logs/factcheck6)"},
        {"company": VU, "owner": "Radius", "year": "2021", "reason": "VUE Group part of Radius since 2021",
         "source": "AI Mode fact-check (logs/factcheck6)"}]
r["ownership"] = own
p.write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")
print("corrections added", n, "| total", len(r["corrections"]))
