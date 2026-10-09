"""One-off strict scope check, one company per query. Read-only."""
import json, os, sys
from pathlib import Path
ROOT = Path(r"C:\Users\aman.kumar\Downloads\Coherent-Quadrant")
sys.path.insert(0, str(ROOT / "src")); sys.stdout.reconfigure(encoding="utf-8", errors="replace")
slot, names_file, out_file = int(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
os.environ["GOOGLE_AI_MODE_PROFILE_DIR"] = str(ROOT / "data" / f"ai_mode_batch_{slot:02d}")
os.environ["GOOGLE_AI_MODE_BROWSER"] = "chromium"; os.environ["GOOGLE_AI_MODE_ENABLED"] = "true"
from vendor_intel.config import Settings
from vendor_intel.pipeline import chatgpt_expand as ce
SYS = ("You are a market research analyst defining the peer set for a UK Connected Fleet Mobility Solutions "
       "quadrant: companies whose MAIN product is a connected-fleet platform -- vehicle telematics, GPS vehicle "
       "tracking, video telematics, and the fleet management software built on that vehicle data. "
       "Classify the company: core = that is its main product and most of its revenue; adjacent = vehicle "
       "tracking is a module or add-on inside a different main product (field service / job management, bus "
       "ticketing, transport or courier management, fleet outsourcing or leasing services, fuel cards, vehicle "
       "security/CCTV installation, OEM data APIs, compliance software that integrates other vendors' telematics); "
       "out = not in this market. main_product = its main product in a few words. Compact JSON only: "
       '{"results":[{"scope":"core|adjacent|out","main_product":"","reason":"","source":""}]}')
c, m = ce._client(Settings()), ce._model(Settings())
out = json.loads(out_file.read_text(encoding="utf-8")) if out_file.exists() else {}
for row in json.loads(names_file.read_text(encoding="utf-8")):
    if row["company"] in out: continue
    try:
        r = ce._chat_json(c, m, SYS, f"Company: {row['company']} (brand {row['brand']}, {row['hq']}, {row['site']}).",
                          label="scope", max_tokens=1500, require_key="results")
        res = ((r or {}).get("results") or [{}])[0]
    except Exception as err:  # noqa: BLE001
        print("failed", row["company"], err, flush=True); continue
    if str(res.get("scope", "")).lower() not in ("core", "adjacent", "out"):
        print("bad", row["company"], res, flush=True); continue
    out[row["company"]] = res
    out_file.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print("done", row["company"], res.get("scope"), flush=True)
print("finished", flush=True)
