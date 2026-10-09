"""Accounts Payable Automation: targeted discovery for suite vendors with AP modules, then re-pick.

1. 10-browser top-up with a scope text aimed at ERP / finance / P2P / S2P / spend-suite
   vendors that sell an AP automation module (categories only, no company names);
   every company already found is excluded.                         -> marker erp_topup_done
2. The full pipeline (client brief scope) with --reselect, so the Top 20 is re-picked
   from the enlarged pool; saved answers / scores / evidence are reused.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKET, COUNTRY, KEEP = "Accounts Payable Automation Market", "global", 250
OUT = ROOT / "output/chatgpt_expand/accounts_payable_automation_market_global"
PIPE = OUT / "_pipeline"
brief = json.loads((PIPE / "market_brief.json").read_text(encoding="utf-8"))
base_env = {**os.environ, "PYTHONIOENCODING": "utf-8", "GOOGLE_AI_MODE_QUERY_DELAY": "10"}
ERP_SCOPE = ("Software vendors whose ERP, financial management, accounting, procure-to-pay, source-to-pay or "
             "spend-management suite includes an accounts payable automation module or application: supplier invoice "
             "capture and matching, AP approval workflow, supplier payment automation, AP reconciliation or AP "
             "analytics. Include large global ERP and finance-suite vendors and mid-market suite vendors. Standalone AP "
             "automation platforms are already covered. EXCLUDED: AP outsourcing / BPO, consultancies, resellers and "
             "implementation partners.")
if not (PIPE / "erp_topup_done").exists():
    # Discovery was stopped by the user: verify what the browsers already found (client brief scope).
    rc = subprocess.call([sys.executable, str(ROOT / "scripts/parallel_topup.py"), "--market", MARKET,
                          "--country", COUNTRY, "--keep", "470", "--browsers", "10", "--slot-start", "41",
                          "--verify-only", "--timeout-minutes", "60"], cwd=ROOT,
                         env={**base_env, "MARKET_SCOPE": " ".join(brief["scope"].split())})
    if rc == 0:
        (PIPE / "erp_topup_done").write_text("done\n", encoding="utf-8")
env = {**base_env, "MARKET_SCOPE": " ".join(brief["scope"].split())}
with open(ROOT / "logs/parallel/accounts_payable_automation_market_global.log", "a", encoding="utf-8") as fh:
    rc = subprocess.call([sys.executable, str(ROOT / "scripts/run_quadrant_pipeline.py"), "--market", MARKET,
                          "--country", COUNTRY, "--slots", "41-50", "--keep", str(KEEP), "--reselect",
                          "--max-discover-rounds", "0"], cwd=ROOT, env=env, stdout=fh, stderr=subprocess.STDOUT)
    fh.write(f"exit={rc}\n")
print(f"[run] pipeline exit {rc}", flush=True)
sys.exit(rc)
