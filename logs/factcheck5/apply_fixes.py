"""One-off: turn the factcheck5 findings into analyst_review.json corrections (UK market data only)."""
import glob
import json
from pathlib import Path

ROOT = Path(r"C:\Users\aman.kumar\Downloads\Coherent-Quadrant")
claims = {}
for f in glob.glob(str(ROOT / "logs/factcheck5/out_*.json")):
    for n, r in json.load(open(f, encoding="utf-8")).items():
        for c in r.get("claims", []):
            claims.setdefault(n, []).append(c["claim"])


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


FSS, FG, T8, MB = "Fleet Software Solutions Ltd", "FleetGS", "Trakm8 Limited", "Mobil Information Systems UK Ltd"
VT, KX, FC, TT = "VisionTrack Limited", "KONEXIT FLEET LTD", "Fleetclear", "TT-Matics"

whole(FSS, "The company reports that its tracking platform supports compliance with UK GDPR", "",
      "Unconfirmed: GDPR/ICO guideline details and 2026 guide")
part(FSS, "Fleet Software Solutions provided a branded", "featuring 10-second live updates, anti-tamper",
     "featuring anti-tamper", "Unconfirmed 10-second update detail")
part(FSS, "The company reports maintaining a nationwide", " across regional hubs", "", "Unconfirmed 'regional hubs'")
part(FSS, "In a commercial deployment for client John E Wright",
     "utilized its dedicated engineering network to execute the physical installation",
     "carried out the physical installation", "Unconfirmed 'dedicated engineering network'")
whole(FG, "The company markets a specific hardware offering, the FleetGS FMT100", "",
      "No source for a FleetGS FMT100 tracker")
part(FG, "The company announced the release of its mobile application",
     "announced the release of its mobile application on the Apple App Store in October 2025 to enable",
     "offers a mobile application on the Apple App Store to enable", "Release month unconfirmed")
whole(FG, "Commercial sales channels show direct integration",
      "Commercial sales channels show direct integration capabilities with Teltonika hardware models such as "
      "the FMC880, FMC920 and FMC150, pre-configured for the UK FleetGS platform.",
      "Platform supports generic Teltonika models, not a FleetGS FMT100")
part(FG, "FleetGS operates an affiliate partner programme", "and commercial lease brokers",
     "commercial vehicle dealers and lease brokers", "Programme lists commercial vehicle dealers and lease brokers")
part(FG, "The company reports that its software architecture is designed to scale", "between 5 and 500 vehicles",
     "between 5 and 50 vehicles", "Site states 5 to 50 vehicles")
whole(T8, "Trakm8 Limited achieved formal ISO 27001",
      "Trakm8 Limited holds ISO 27001 accreditation for its information security management.",
      "GDPR-process and publication details unconfirmed")
part(T8, "The company reports its Trakm8 Insight platform features an Open API",
     "includes low-level vehicle routing algorithms, energy APIs, and specific integration endpoints for ERP and "
     "Electronic Proof of Delivery (ePOD) workflows",
     "supports Electronic Proof of Delivery (ePOD) workflows", "Routing/energy API/ERP endpoint details unconfirmed")
whole(T8, "Selco Builders Warehouse renewed",
      "Selco Builders Warehouse renewed its fleet telematics contract with the company for four years, extending "
      "a 10-year partnership, to deploy the Trakm8 Insight Business Platform across its company car operations.",
      "Four-year renewal within a 10-year partnership")
whole(T8, "In its final financial results for the year ended 31 March 2024",
      "In its final financial results for the year ended 31 March 2024, the company reported total revenue of "
      "£16.09 million.", "Revenue was £16.09m; the £1.5m fleet-software drop is unconfirmed")
part(T8, "The company reports that it has over 240,000 active connections",
     "according to its June 2026 annual report announcement", "according to its July 2026 AGM announcement",
     "Source is the July 2026 AGM announcement")
part(MB, 'The company introduced "Fleet Emissions Intelligence"',
     "TRL PPR987 idle rates and European Commission guidelines", "TRL PPR987 idle rates",
     "European Commission guidelines not in source")
part(MB, "The company provides a scalable multi-camera DVR", "up to 12 channels", "up to 8 channels",
     "Supports up to 8 channels")
whole(MB, "Open corporate data platforms like Endole", "", "Modelled size band from a company-data site")
part(VT, "VisionTrack's cloud-based IoT video telematics platform", " and 292 billion data points annually", "",
     "292bn figure belongs to an older device count")
whole(VT, "The company reports that its VT3000-AI hardware",
      "The company reports that its VT3000-AI hardware works with separate 4G connectivity and driver status "
      "monitoring (DSM) modules to transmit real-time telemetry and upload advanced driver assist system (ADAS) "
      "and DSM alerts to the cloud.", "4G and DSM are separate modules, not built in")
whole(VT, "An anonymized regional logistics company",
      "A case study on the Geotab Marketplace reports that a logistics company using VisionTrack's vehicle data "
      "and driver coaching achieved a 35% reduction in harsh braking events.",
      "Company description and six-month timeframe unconfirmed")
part(VT, "Tonbridge School implemented", ", ruggedized anti-vibration MDVRs,", ",", "Unconfirmed MDVR detail")
whole(VT, "A September 2026 fleet deployment project with Loomis UK",
      "A September 2026 fleet deployment project with Loomis UK confirms the implementation of VisionTrack's "
      "video telematics across a 500+ vehicle fleet.", "Platform, Azure and certification details unconfirmed")
whole(VT, "According to filing data from the UK Companies House register, VisionTrack", "",
      "Turnover, net worth and cash figures unconfirmed")
part(VT, "VisionTrack announced a strategic partnership with driver risk", "verified by its computer vision tool",
     "verified by its AI post-analysis tool, NARA", "Tool is NARA")
part(VT, "The company reports its operational customer services",
     ", alongside a distinct morning window on Saturdays from 9:00am to 1:00pm", "", "No Saturday hours")
whole(KX, "Optimus Group reported an in-progress council project", "", "Council project details unconfirmed")
whole(KX, "Financial profiles tracking corporate registers show that KONEXIT", "", "Modelled size band, unconfirmed")
whole(KX, "The company reports partnering with major insurance providers", "", "Insurance partnership unconfirmed")
part(KX, "The company reports providing UK-wide support from its base in Mid Wales",
     "with over 15 years of remote data solutions experience", "with over 30 years of combined experience",
     "Site states 30+ years combined experience")
part(FC, "Suez Recycling and Recovery UK adopted",
     ", utilizing 4G connectivity to support live video streaming and remote data downloads", "",
     "4G streaming detail unconfirmed")
part(FC, "The company reports that its Vehicle Digital Video Recording",
     " to house 720p/1080p HD cameras integrated with artificial intelligence for forward blind-spot alerts and "
     "near-side collision notifications", "", "Camera/AI details unconfirmed")
part(FC, "Kirklees Council awarded Fleetclear", "with a 1-year extension option",
     "with an option to extend for up to two twelve-month periods", "Two 12-month extension options")
whole(TT, "Dun & Bradstreet reported a sales revenue", "", "Modelled revenue estimate from a company-data site")

p = ROOT / "output/chatgpt_expand/connected_fleet_mobility_solutions_market_united_kingdom/_pipeline/analyst_review.json"
r = json.loads(p.read_text(encoding="utf-8"))
SRC = "AI Mode fact-check of chart entrants after strict scope refill (logs/factcheck5), 2026-10-02"
have = {(c["company"], c["find"]) for c in r["corrections"]}
n = 0
for co, f, rep, why in FX:
    if (co, f) not in have:
        r["corrections"].append({"company": co, "find": f, "replace": rep, "reason": why, "source": SRC})
        n += 1
own = [o for o in r.setdefault("ownership", []) if o.get("company") != VT]
own.append({"company": VT, "owner": "Markerstudy Group", "year": "", "reason": "Operates as part of Markerstudy Group",
            "source": "AI Mode fact-check (logs/factcheck5): Companies House and press releases"})
r["ownership"] = own
p.write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")
print("corrections added", n, "| total", len(r["corrections"]))
