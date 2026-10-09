"""One-off fact-finding questions (JSON). Read-only: saves findings to <out>.json."""
import json, os, sys
from pathlib import Path
ROOT = Path(r"C:\Users\aman.kumar\Downloads\Coherent-Quadrant")
sys.path.insert(0, str(ROOT / "src")); sys.stdout.reconfigure(encoding="utf-8", errors="replace")
slot, jobs_file, out_file = int(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
os.environ["GOOGLE_AI_MODE_PROFILE_DIR"] = str(ROOT / "data" / f"ai_mode_batch_{slot:02d}")
os.environ["GOOGLE_AI_MODE_BROWSER"] = "chromium"; os.environ["GOOGLE_AI_MODE_ENABLED"] = "true"
from vendor_intel.config import Settings
from vendor_intel.pipeline import chatgpt_expand as ce
SYS = ("You are a research analyst. Answer the question with specific, dated, sourced facts only. "
       "Never use modelled estimates from contact-data sites (RocketReach, ZoomInfo, Growjo, Owler) or "
       "market-research publishers. If nothing specific exists, return an empty list. Compact JSON only: "
       '{"results":[{"fact":"","date":"","source":""}]}')
c, m = ce._client(Settings()), ce._model(Settings())
out = json.loads(out_file.read_text(encoding="utf-8")) if out_file.exists() else {}
for job in json.loads(jobs_file.read_text(encoding="utf-8")):
    for qi, qtext in enumerate(job["questions"]):
        key = f"{job['company']}|{job['param']}|{qi}"
        if key in out:
            continue
        try:
            r = ce._chat_json(c, m, SYS, qtext, label=f"find-{qi}", max_tokens=3000, require_key="results")
            facts = [x for x in (r or {}).get("results") or [] if isinstance(x, dict) and str(x.get("fact") or "").strip()]
        except Exception as err:  # noqa: BLE001
            print("failed", key, err, flush=True); facts = None
        out[key] = {"question": qtext, "facts": facts}
        out_file.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
        print("done", key, len(facts or []), flush=True)
print("finished", flush=True)
