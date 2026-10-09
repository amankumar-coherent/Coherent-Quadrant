"""Second pass for the 10 fire India markets, after the checks-only batch finishes.

Re-runs --update-report (checks only; saved answers are reused, so only new companies are asked)
with --refill-chart for every market that
  - got placeholder-HQ companies added after its first pass started, or
  - ended with fewer than 20 companies on its chart (refilled from its own long tail).
Then refreshes Desktop\\Final Fire Quadrant.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "chatgpt_expand"
MARKETS = {
    "battery_fire_safety_industry_analysis": "Battery Fire Safety Industry Analysis",
    "critical_infrastructure_fire_safety_industry_analysis": "Critical Infrastructure Fire Safety Industry Analysis",
    "disaster_response_industry_analysis": "Disaster Response Industry Analysis",
    "electrical_fire_safety_industry_analysis": "Electrical Fire Safety Industry Analysis",
    "emergency_communications_industry_analysis": "Emergency Communications Industry Analysis",
    "fire_vehicles_industry_analysis": "Fire Vehicles Industry Analysis",
    "firefighting_equipment_industry_analysis": "Firefighting Equipment Industry Analysis",
    "life_safety_industry_analysis": "Life Safety Industry Analysis",
    "rescue_equipment_industry_analysis": "Rescue Equipment Industry Analysis",
    "smoke_control_systems_industry_analysis": "Smoke Control Systems Industry Analysis",
}
HQ_ADDED = {"disaster_response_industry_analysis", "electrical_fire_safety_industry_analysis",
            "emergency_communications_industry_analysis"}

batch_log = ROOT / "logs" / "run_fire_india_10.log"
# The batch log holds several launches; wait for the "exit=" of the latest one.
while "exit=" not in batch_log.read_text(encoding="utf-8", errors="replace").split("extension(s) loaded")[-1]:
    time.sleep(30)

todo = []
for slug, name in MARKETS.items():
    q = OUT / f"{slug}_india" / f"{slug}_india_quadrant.json"
    chart = sum(1 for b in json.loads(q.read_text(encoding="utf-8")).get("brands") or [] if b.get("on_chart")) \
        if q.exists() else 0
    if slug in HQ_ADDED or chart < 20:
        todo.append(name)
        (OUT / f"{slug}_india" / "_pipeline" / "report_update_done").unlink(missing_ok=True)
        print(f"second pass: {name} (chart {chart})", flush=True)
(ROOT / "queries" / "fire_india_second_pass.txt").write_text(
    "\n".join(f"{n} | india" for n in todo) + "\n", encoding="utf-8")
if todo:
    subprocess.call([sys.executable, str(ROOT / "scripts" / "run_markets_parallel.py"),
                     "--markets-file", str(ROOT / "queries" / "fire_india_second_pass.txt"),
                     "--workers", str(min(5, len(todo))), "--slot-start", "46", "--top-n", "20",
                     "--", "--max-discover-rounds", "0", "--update-report", "auto", "--refill-chart"], cwd=ROOT)
subprocess.call([sys.executable, str(ROOT / "logs" / "build_final_folders.py")], cwd=ROOT)
print("second pass finished", flush=True)
