import json, os, sys
from pathlib import Path
ROOT = Path(r"C:\Users\aman.kumar\Downloads\Coherent-Quadrant")
sys.path.insert(0, str(ROOT / "src")); sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ["GOOGLE_AI_MODE_PROFILE_DIR"] = str(ROOT / "data" / "ai_mode_batch_49")
os.environ["GOOGLE_AI_MODE_BROWSER"] = "chromium"; os.environ["GOOGLE_AI_MODE_ENABLED"] = "true"
from vendor_intel.config import Settings
from vendor_intel.pipeline import chatgpt_expand as ce
SYS = ("You are a fact-checker auditing a published market report. Check the ONE claim about Journease "
       "Software Limited (Bristol, UK; journease.com) against its website and published sources. "
       "verdict: correct, incorrect or unverified. For incorrect give the corrected sentence; for "
       "unverified name the unconfirmed customers in note. Compact JSON only: "
       '{"results":[{"verdict":"","corrected":"","note":"","source":""}]}')
claim = sys.argv[1]
c, m = ce._client(Settings()), ce._model(Settings())
r = ce._chat_json(c, m, SYS, "Claim: " + claim, label="one", max_tokens=2000, require_key="results")
print(json.dumps(r, ensure_ascii=False, indent=1))
