"""Run the Accounts Payable Automation market on 10 browsers, resumable.

1. 10-browser broad top-up towards 250 (scripts/parallel_topup.py)       -> marker parallel_topup_done
2. If still short: 10-browser COUNTRY-BY-COUNTRY top-up (--countries)    -> marker country_topup_done
3. The full pipeline on 10 browsers with no one-browser top-up.
MARKET_SCOPE comes from the market brief so discovery and verify use it.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from vendor_intel.pipeline.quadrant_pipeline import dedupe_companies  # noqa: E402

MARKET, COUNTRY, KEEP = "Accounts Payable Automation Market", "global", 239  # 250 - 5 (player check) - 3 (client review) - 3 (owned by a listed parent), no refill
OUT = ROOT / "output/chatgpt_expand/accounts_payable_automation_market_global"
PIPE = OUT / "_pipeline"
brief = json.loads((PIPE / "market_brief.json").read_text(encoding="utf-8"))
env = {**os.environ, "MARKET_SCOPE": " ".join(brief["scope"].split()), "PYTHONIOENCODING": "utf-8", "GOOGLE_AI_MODE_QUERY_DELAY": "10"}  # overrides .env (20) for this run


def have() -> int:
    state = json.loads((OUT / "chatgpt_checkpoint_batch_all.json").read_text(encoding="utf-8"))
    return len(dedupe_companies(state["data"].get("verified") or [])[0])


def topup(extra: list[str], marker: str) -> None:
    if (PIPE / marker).exists() or have() >= KEEP:
        return
    rc = subprocess.call([sys.executable, str(ROOT / "scripts/parallel_topup.py"), "--market", MARKET,
                          "--country", COUNTRY, "--keep", str(KEEP), "--browsers", "10", "--slot-start", "41",
                          "--timeout-minutes", "120"] + extra, cwd=ROOT, env=env)
    if rc == 0:
        (PIPE / marker).write_text("done\n", encoding="utf-8")


topup(["--max-rounds", "8"], "parallel_topup_done")
topup(["--countries"], "country_topup_done")
print(f"[run] discovery finished with {have()} companies; starting the pipeline", flush=True)
with open(ROOT / "logs/parallel/accounts_payable_automation_market_global.log", "a", encoding="utf-8") as fh:
    rc = subprocess.call([sys.executable, str(ROOT / "scripts/run_quadrant_pipeline.py"), "--market", MARKET,
                          "--country", COUNTRY, "--slots", "41-50", "--keep", str(KEEP),
                          "--max-discover-rounds", "0"], cwd=ROOT, env=env, stdout=fh, stderr=subprocess.STDOUT)
    fh.write(f"exit={rc}\n")
print(f"[run] pipeline exit {rc}", flush=True)
sys.exit(rc)
