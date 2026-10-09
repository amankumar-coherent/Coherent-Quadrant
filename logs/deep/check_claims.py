import json, os, sys
from pathlib import Path
ROOT = Path(r"C:\Users\aman.kumar\Downloads\Coherent-Quadrant")
sys.path.insert(0, str(ROOT / "src")); sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ["GOOGLE_AI_MODE_PROFILE_DIR"] = str(ROOT / "data" / f"ai_mode_batch_{int(os.environ.get("SLOT", "47")):02d}")
os.environ["GOOGLE_AI_MODE_BROWSER"] = "chromium"; os.environ["GOOGLE_AI_MODE_ENABLED"] = "true"
from vendor_intel.config import Settings
from vendor_intel.pipeline import chatgpt_expand as ce
company, claims = sys.argv[1], json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
SYS = (f"You are a fact-checker auditing a published market report. Check each numbered claim about {company} "
       "against its website and published sources. verdict: correct, incorrect or unverified. For incorrect give "
       "the corrected sentence; for unverified name the unconfirmed detail in note. Compact JSON only: "
       '{"results":[{"n":0,"verdict":"","corrected":"","note":"","source":""}]}')
c, m = ce._client(Settings()), ce._model(Settings())
r = ce._chat_json(c, m, SYS, "Claims:\n" + "\n".join(f"{i+1}. {t}" for i, t in enumerate(claims)),
                  label="claims", max_tokens=3000, require_key="results")
print(json.dumps(r, ensure_ascii=False, indent=1))
