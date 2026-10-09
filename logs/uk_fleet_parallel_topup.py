"""One-off driver: 10-browser top-up for the UK Connected Fleet market, then the
full pipeline. Each browser runs discover_verify_rounds.py on its own copy of
the merged checkpoint (every name already seen is excluded and only new
companies are verified); the new verified companies are merged back and
run_quadrant_pipeline.py then runs with --keep 250 on 10 browsers."""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(r"C:\Users\aman.kumar\Downloads\Coherent-Quadrant")
sys.path.insert(0, str(ROOT / "src"))
from vendor_intel.pipeline.quadrant_pipeline import dedupe_companies  # noqa: E402

MARKET, COUNTRY = "Connected Fleet Mobility Solutions Market", "united kingdom"
SLUG = "connected_fleet_mobility_solutions_market_united_kingdom"
REAL = ROOT / "output" / "chatgpt_expand" / SLUG / "chatgpt_checkpoint_batch_all.json"
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
N, KEEP = 10, 250
LOG = ROOT / "logs" / "uk_fleet_topup.log"


def log(msg):
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"[topup {time.strftime('%H:%M:%S')}] {msg}\n")


def key(row):
    return str(row.get("name") or row.get("Company") or row.get("company") or "").strip().lower()


real = json.loads(REAL.read_text(encoding="utf-8"))
before = len(dedupe_companies(real["data"].get("verified") or [])[0])
log(f"start: {before} verified companies; {N} browsers, target {KEEP}")
procs = []
for i in range(N):
    folder = f"chatgpt_expand_top{i + 1}"
    d = ROOT / "output" / folder / SLUG
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    shutil.copy(REAL, d / REAL.name)
    slot = 41 + i
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "EXPAND_OUTPUT_FOLDER": folder,
           "GOOGLE_AI_MODE_PROFILE_DIR": str(ROOT / "data" / f"ai_mode_batch_{slot:02d}"),
           "GOOGLE_AI_MODE_BROWSER": "chromium", "GOOGLE_AI_MODE_ENABLED": "true"}
    fh = (ROOT / "logs" / f"uk_topup_{i + 1}_{slot}.log").open("w", encoding="utf-8")
    p = subprocess.Popen([PY, str(ROOT / "scripts" / "discover_verify_rounds.py"), "--market", MARKET,
                          "--country", COUNTRY, "--keep", str(KEEP), "--slot", str(slot), "--max-rounds", "6"],
                         cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT, env=env)
    procs.append((p, fh, d))
    log(f"browser {i + 1}: start on slot {slot}")
    time.sleep(4)

deadline = time.time() + 75 * 60
while time.time() < deadline and any(p.poll() is None for p, _, _ in procs):
    time.sleep(30)
for p, fh, _ in procs:
    if p.poll() is None:
        p.terminate()
    fh.close()

real = json.loads(REAL.read_text(encoding="utf-8"))
verified = list(real["data"].get("verified") or [])
rejected = list(real["data"].get("rejected_mid") or [])
seen = {key(r) for r in verified}
for i, (_, _, d) in enumerate(procs, 1):
    try:
        data = json.loads((d / REAL.name).read_text(encoding="utf-8")).get("data") or {}
    except Exception as err:  # noqa: BLE001
        log(f"browser {i}: unreadable checkpoint ({err})")
        continue
    new = [r for r in data.get("verified") or [] if key(r) and key(r) not in seen]
    seen |= {key(r) for r in new}
    verified += new
    rejected += [r for r in data.get("rejected_mid") or [] if r not in rejected]
    log(f"browser {i}: {len(new)} new verified")
real["data"]["verified"], real["data"]["rejected_mid"] = verified, rejected
REAL.write_text(json.dumps(real, ensure_ascii=False), encoding="utf-8")
after = len(dedupe_companies(verified)[0])
log(f"merged: {before} -> {after} verified companies after dedupe")

log("pipeline: start (--keep 250, 10 browsers, no one-browser top-up)")
with (ROOT / "logs" / "uk_connected_fleet_run.log").open("a", encoding="utf-8") as fh:
    rc = subprocess.call([PY, str(ROOT / "scripts" / "run_quadrant_pipeline.py"), "--market", MARKET,
                          "--country", COUNTRY, "--slots", "41-50", "--keep", str(KEEP),
                          "--max-discover-rounds", "0"],
                         cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT,
                         env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    fh.write(f"exit={rc}\n")
log(f"pipeline: exit {rc}")
