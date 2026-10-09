"""Re-run markets one after another on one browser slot; log a one-line VERIFY result per market.

    python logs/rerun_markets.py <slot> "Market A|india" "Market B|india" ...
"""
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
slot, items = sys.argv[1], sys.argv[2:]
out = ROOT / "logs" / "rerun_markets.log"
for item in items:
    market, country = item.split("|")
    t0 = time.time()
    with open(out, "a", encoding="utf-8") as f:
        f.write(f"[rerun] START {market}\n")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "run_quadrant_pipeline.py"), "--market", market,
                        "--country", country, "--slots", slot, "--top-n", "20", "--keep", "120",
                        "--max-discover-rounds", "0"],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    text = r.stdout + r.stderr
    slug = re.sub(r"[^a-z0-9]+", "_", f"{market} {country}".lower()).strip("_")
    (ROOT / "logs" / "parallel" / f"{slug}_rerun.log").write_text(text, encoding="utf-8")
    passed = text.count("[PASS]")
    fails = [ln.strip() for ln in text.splitlines() if "[FAIL]" in ln]
    with open(out, "a", encoding="utf-8") as f:
        f.write(f"[rerun] END {market} exit={r.returncode} pass={passed} fail={len(fails)} "
                f"{int((time.time() - t0) / 60)} min\n")
        for ln in fails:
            f.write(f"    {ln[:300]}\n")
with open(out, "a", encoding="utf-8") as f:
    f.write("[rerun] ALL DONE\n")
