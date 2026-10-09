"""One-off: ask plain questions, save the prose answer (text after the echoed question)."""
import json, os, sys
from pathlib import Path
ROOT = Path(r"C:\Users\aman.kumar\Downloads\Coherent-Quadrant")
sys.path.insert(0, str(ROOT / "src")); sys.stdout.reconfigure(encoding="utf-8", errors="replace")
slot, qfile, out_file = int(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
os.environ["GOOGLE_AI_MODE_PROFILE_DIR"] = str(ROOT / "data" / f"ai_mode_batch_{slot:02d}")
os.environ["GOOGLE_AI_MODE_BROWSER"] = "chromium"; os.environ["GOOGLE_AI_MODE_ENABLED"] = "true"
from vendor_intel.scraping.google_ai_mode import ask
out = json.loads(out_file.read_text(encoding="utf-8")) if out_file.exists() else {}
for key, q in json.loads(qfile.read_text(encoding="utf-8")).items():
    if key in out: continue
    full = q + " Answer in short bullet points, each with its date and source. Do not use RocketReach, ZoomInfo or other modelled estimates."
    ans = ask(full) or ""
    tail = ans.split(full[-60:])[-1] if full[-60:] in ans else ans[-3000:]
    out[key] = tail.split("Skip to previous prompt")[0].strip()
    out_file.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print("done", key, flush=True)
print("finished", flush=True)
