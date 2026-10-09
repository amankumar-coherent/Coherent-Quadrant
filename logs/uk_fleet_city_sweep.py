"""One-off driver: UK Connected Fleet -- merge the previous top-up, then a
10-browser city/region sweep (each browser gets 2 of the 20 UK areas via
GEO_AREA_SHARD), merge the new verified companies, then the full pipeline with
--keep 250 on 10 browsers (no one-browser top-up)."""
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
LOG = ROOT / "logs" / "uk_fleet_city.log"


def log(msg):
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"[city {time.strftime('%H:%M:%S')}] {msg}\n")


def key(row):
    return str(row.get("name") or row.get("Company") or row.get("company") or "").strip().lower()


def merge(prefix):
    real = json.loads(REAL.read_text(encoding="utf-8"))
    data = real.setdefault("data", {})
    verified = list(data.get("verified") or [])
    rejected = list(data.get("rejected_mid") or [])
    recalled = list(data.get("recalled") or [])
    seen = {key(r) for r in verified}
    seen_rej = {key(r) for r in rejected if isinstance(r, dict)}
    seen_rec = {key(r) if isinstance(r, dict) else str(r).lower() for r in recalled}
    added = 0
    for i in range(1, N + 1):
        p = ROOT / "output" / f"{prefix}{i}" / SLUG / REAL.name
        if not p.exists():
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8")).get("data") or {}
        except Exception as err:  # noqa: BLE001
            log(f"{prefix}{i}: unreadable ({err})")
            continue
        new = [r for r in d.get("verified") or [] if key(r) and key(r) not in seen]
        seen |= {key(r) for r in new}
        verified += new
        added += len(new)
        for r in d.get("rejected_mid") or []:
            if isinstance(r, dict) and key(r) not in seen_rej:
                seen_rej.add(key(r))
                rejected.append(r)
        # Keep every name already discovered, so later rounds exclude it.
        for r in d.get("recalled") or []:
            k = key(r) if isinstance(r, dict) else str(r).lower()
            if k and k not in seen_rec:
                seen_rec.add(k)
                recalled.append(r)
    data["verified"], data["rejected_mid"], data["recalled"] = verified, rejected, recalled
    REAL.write_text(json.dumps(real, ensure_ascii=False), encoding="utf-8")
    have = len(dedupe_companies(verified)[0])
    log(f"merged {prefix}*: +{added} rows -> {have} verified companies after dedupe")
    return have


before = merge("chatgpt_expand_top")
log(f"start city sweep: {before} verified; {N} browsers x 2 UK areas each, target {KEEP}")
procs = []
for i in range(N):
    folder = f"chatgpt_expand_city{i + 1}"
    d = ROOT / "output" / folder / SLUG
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    shutil.copy(REAL, d / REAL.name)
    slot = 41 + i
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "EXPAND_OUTPUT_FOLDER": folder,
           "GEO_AREA_SHARD": f"{i + 1}/{N}",
           "GOOGLE_AI_MODE_PROFILE_DIR": str(ROOT / "data" / f"ai_mode_batch_{slot:02d}"),
           "GOOGLE_AI_MODE_BROWSER": "chromium", "GOOGLE_AI_MODE_ENABLED": "true"}
    fh = (ROOT / "logs" / f"uk_city_{i + 1}_{slot}.log").open("w", encoding="utf-8")
    p = subprocess.Popen([PY, str(ROOT / "scripts" / "discover_verify_rounds.py"), "--market", MARKET,
                          "--country", COUNTRY, "--keep", str(KEEP), "--slot", str(slot), "--max-rounds", "4"],
                         cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT, env=env)
    procs.append((p, fh))
    log(f"browser {i + 1}: slot {slot}, areas shard {i + 1}/{N}")
    time.sleep(4)

deadline = time.time() + 80 * 60
while time.time() < deadline and any(p.poll() is None for p, _ in procs):
    time.sleep(30)
for p, fh in procs:
    if p.poll() is None:
        p.terminate()
    fh.close()
after = merge("chatgpt_expand_city")
log(f"city sweep done: {before} -> {after} verified companies")

log("pipeline: start (--keep 250, 10 browsers, no one-browser top-up)")
with (ROOT / "logs" / "uk_connected_fleet_run.log").open("a", encoding="utf-8") as fh:
    rc = subprocess.call([PY, str(ROOT / "scripts" / "run_quadrant_pipeline.py"), "--market", MARKET,
                          "--country", COUNTRY, "--slots", "41-50", "--keep", str(KEEP),
                          "--max-discover-rounds", "0"],
                         cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT,
                         env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    fh.write(f"exit={rc}\n")
log(f"pipeline: exit {rc}")
