import json, os, sys
from pathlib import Path
ROOT = Path(r"C:\Users\aman.kumar\Downloads\Coherent-Quadrant")
sys.path.insert(0, str(ROOT / "src")); sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ["GOOGLE_AI_MODE_PROFILE_DIR"] = str(ROOT / "data" / "ai_mode_batch_49")
os.environ["GOOGLE_AI_MODE_BROWSER"] = "chromium"; os.environ["GOOGLE_AI_MODE_ENABLED"] = "true"
from vendor_intel.config import Settings
from vendor_intel.pipeline import chatgpt_expand as ce
f = ROOT / "logs/factcheck4/out_2.json"; d = json.loads(f.read_text(encoding="utf-8"))
rec = d["Journease Software Limited"]
SYS = ("You are a fact-checker auditing a published market report. Check the ONE claim about Journease "
       "Software Limited (Bristol, UK) against published sources. Choose exactly one verdict word: correct, "
       "incorrect or unverified. incorrect = a source contradicts a detail (give corrected sentence); "
       "unverified = no source states a specific detail (name it in note). Compact JSON only: "
       '{"results":[{"verdict":"unverified","corrected":"","note":"","source":""}]}')
client, model = ce._client(Settings()), ce._model(Settings())
for c in rec["claims"]:
    if c["verdict"] in ("correct", "incorrect", "unverified"):
        continue
    try:
        res = ce._chat_json(client, model, SYS, "Claim: " + c["claim"], label="one", max_tokens=2000, require_key="results")
        r = (res.get("results") or [{}])[0]
    except Exception as e:
        print("failed", e); continue
    c.update(verdict=str(r.get("verdict", "")).lower(), corrected=r.get("corrected", ""), note=r.get("note", ""), source=r.get("source", ""))
    print(c["verdict"], "|", c["claim"][:70], "|", c["corrected"], "|", c["note"], flush=True)
    f.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
