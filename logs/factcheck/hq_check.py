import os, sys, json
from pathlib import Path
ROOT = Path(r"C:\Users\aman.kumar\Downloads\Coherent-Quadrant")
sys.path.insert(0, str(ROOT / "src"))
os.environ.update(GOOGLE_AI_MODE_PROFILE_DIR=str(ROOT / "data" / "ai_mode_batch_41"), GOOGLE_AI_MODE_BROWSER="chromium", GOOGLE_AI_MODE_ENABLED="true")
from vendor_intel.config import Settings
from vendor_intel.pipeline import chatgpt_expand as ce
c, m = ce._client(Settings()), ce._model(Settings())
sysm = ("You are a market research analyst. Use registry and company-website facts only. For EACH company give "
        "global_hq = city and country of its global headquarters (where the parent operating company is based), "
        "uk_entity = its UK company name if any, uk_role = headquarters | branch/subsidiary of a foreign company | none, "
        "evidence = one factual sentence. Compact JSON only: "
        '{"results":[{"name":"...","global_hq":"...","uk_entity":"...","uk_role":"...","evidence":"..."}]}')
names = ["Transpoco Limited", "Pocket Box Ltd", "Terramar Networks Limited", "AGM Technologies Ltd", "Asset Monitoring Solutions Ltd"]
res = ce._chat_json(c, m, sysm, "Companies (connected fleet / telematics):\n" + "\n".join(names), label="hq-check", max_tokens=2500, require_key="results")
print(json.dumps(res, indent=1, ensure_ascii=False))
