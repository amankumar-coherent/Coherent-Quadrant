"""One-off: ask each job's question in AI Mode, save the prose answer. Read-only."""
import json, os, sys
from pathlib import Path
ROOT = Path(r"C:\Users\aman.kumar\Downloads\Coherent-Quadrant")
sys.path.insert(0, str(ROOT / "src")); sys.stdout.reconfigure(encoding="utf-8", errors="replace")
slot, jobs_file, out_file = int(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
os.environ["GOOGLE_AI_MODE_PROFILE_DIR"] = str(ROOT / "data" / f"ai_mode_batch_{slot:02d}")
os.environ["GOOGLE_AI_MODE_BROWSER"] = "chromium"; os.environ["GOOGLE_AI_MODE_ENABLED"] = "true"
from vendor_intel.scraping.google_ai_mode import ask
out = json.loads(out_file.read_text(encoding="utf-8")) if out_file.exists() else {}
TAIL = (" Answer in short bullet points; each bullet one specific fact with its date and source. "
        "Use the company's own website, Companies House filings, press releases, trade press, public tenders. "
        "Do not use RocketReach, ZoomInfo, Endole, Dun & Bradstreet, Tracxn, Crunchbase, GlobalDatabase, CB Insights, "
        "PitchBook, employee-review sites or market-research publishers. If nothing specific exists, say so.")
for job in json.loads(jobs_file.read_text(encoding="utf-8")):
    key = f"{job['company']}|{job['axis']}|{job['param']}"
    if key in out: continue
    q = job["question"] + TAIL
    ans = ask(q) or ""
    tail = ans.split(q[-80:])[-1] if q[-80:] in ans else ans[-3500:]
    out[key] = {"job": job, "answer": tail.split("Skip to previous prompt")[0].strip()}
    out_file.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print("done", key, flush=True)
print("finished", flush=True)
