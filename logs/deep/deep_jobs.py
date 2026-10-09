"""One-off deeper re-ask of (company, axis, parameter) jobs. Read-only: saves answers to <out>.json."""
import json, os, sys
from pathlib import Path
ROOT = Path(r"C:\Users\aman.kumar\Downloads\Coherent-Quadrant")
sys.path.insert(0, str(ROOT / "src")); sys.stdout.reconfigure(encoding="utf-8", errors="replace")
slot, jobs_file, out_file = int(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
os.environ["GOOGLE_AI_MODE_PROFILE_DIR"] = str(ROOT / "data" / f"ai_mode_batch_{slot:02d}")
os.environ["GOOGLE_AI_MODE_BROWSER"] = "chromium"; os.environ["GOOGLE_AI_MODE_ENABLED"] = "true"
from vendor_intel.quadrant.ai_mode_scorer import build_forced_score_query, parse_small_group_scores
from vendor_intel.scraping.google_ai_mode import ask
D = ROOT / "output/chatgpt_expand/connected_fleet_mobility_solutions_market_united_kingdom"
spec = json.loads((D / "_pipeline/axes_spec.json").read_text(encoding="utf-8"))
out = json.loads(out_file.read_text(encoding="utf-8")) if out_file.exists() else {}
for job in json.loads(jobs_file.read_text(encoding="utf-8")):
    key = f"{job['company']}|{job['axis']}|{job['param']}"
    if out.get(key, {}).get("parsed"):
        continue
    q = build_forced_score_query(job["company"], job["param"], spec["parameter_definitions"][job["axis"]],
                                 market="Connected Fleet Mobility Solutions Market (United Kingdom)",
                                 market_definition=str(spec.get("market_definition") or ""), context=job["hint"])
    got, ans = None, ""
    for attempt in range(2):
        ans = ask(q) or ""
        got = parse_small_group_scores(ans, [job["param"]], q).get(job["param"]) if ans else None
        if got and got.get("assessed_on") and "WHAT THIS MEASURES" not in json.dumps(got):
            break
        got = None
    out[key] = {"job": job, "parsed": got, "answer_tail": ans[-3000:]}
    out_file.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print("done", key, "parsed" if got else "NOT PARSED", flush=True)
print("finished", flush=True)
