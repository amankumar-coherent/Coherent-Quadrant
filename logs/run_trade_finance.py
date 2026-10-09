"""Global Trade Finance Market (technology & network providers), 250 companies, 10 browsers, resumable.

1. First discovery on one browser (Step 0c + a first batch), only if nothing is verified yet.
2. 10-browser top-up towards 330 verified (margin for 3b/3c removals)     -> marker parallel_topup_done
3. If still short: 10-browser COUNTRY-BY-COUNTRY top-up                   -> marker country_topup_done
4. The full pipeline on 10 browsers (--keep 250), no one-browser top-up.
The market brief (_pipeline/market_brief.json) sets scope, player type (Solution Provider) and B2B.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from vendor_intel.pipeline.quadrant_pipeline import dedupe_companies  # noqa: E402

MARKET, COUNTRY, KEEP, TOPUP_TO = "Global Trade Finance Market", "global", 250, 330
OUT = ROOT / "output/chatgpt_expand/global_trade_finance_market_global"
PIPE = OUT / "_pipeline"
CKPT = OUT / "chatgpt_checkpoint_batch_all.json"
brief = json.loads((PIPE / "market_brief.json").read_text(encoding="utf-8"))
env = {**os.environ, "PYTHONIOENCODING": "utf-8", "GOOGLE_AI_MODE_QUERY_DELAY": "10",
       "MARKET_SCOPE": " ".join(brief["scope"].split()), "MARKET_PLAYER_TYPE": brief["player_type"],
       "MARKET_TYPE": brief["market_type"], "EXPAND_DISCOVERY_XY": "0"}


def have() -> int:
    if not CKPT.exists():
        return 0
    state = json.loads(CKPT.read_text(encoding="utf-8"))
    return len(dedupe_companies(state.get("data", {}).get("verified") or [])[0])


if have() == 0:
    print("[run] first discovery (one browser)", flush=True)
    subprocess.call([sys.executable, str(ROOT / "scripts/run_chatgpt_expand.py"), "--query", MARKET,
                     "--country", COUNTRY, "--target", "60"], cwd=ROOT,
                    env={**env, "GOOGLE_AI_MODE_PROFILE_DIR": str(ROOT / "data/ai_mode_batch_41"),
                         "GOOGLE_AI_MODE_BROWSER": "chromium", "GOOGLE_AI_MODE_ENABLED": "true"})
    print(f"[run] first discovery: {have()} verified", flush=True)


# Candidates the stopped one-browser discovery found but did not verify:
# verify them on 10 browsers (each company on one browser) before the top-up.
if not (PIPE / "verify_only_done").exists():
    rc = subprocess.call([sys.executable, str(ROOT / "scripts/parallel_topup.py"), "--market", MARKET,
                          "--country", COUNTRY, "--keep", str(TOPUP_TO), "--browsers", "5", "--slot-start", "41",
                          "--verify-only", "--timeout-minutes", "30"], cwd=ROOT, env=env)
    if rc == 0:
        (PIPE / "verify_only_done").write_text("done\n", encoding="utf-8")
    print(f"[run] after verifying found candidates: {have()} verified", flush=True)


def topup(extra: list[str], marker: str) -> None:
    if (PIPE / marker).exists() or have() >= TOPUP_TO or have() == 0:
        return
    rc = subprocess.call([sys.executable, str(ROOT / "scripts/parallel_topup.py"), "--market", MARKET,
                          "--country", COUNTRY, "--keep", str(TOPUP_TO), "--browsers", "5", "--slot-start", "41",
                          "--timeout-minutes", "120"] + extra, cwd=ROOT, env=env)
    if rc == 0:
        (PIPE / marker).write_text("done\n", encoding="utf-8")


topup(["--max-rounds", "8"], "parallel_topup_done")
topup(["--countries"], "country_topup_done")
print(f"[run] discovery finished with {have()} companies; starting the pipeline", flush=True)
with open(ROOT / "logs/parallel/global_trade_finance_market_global.log", "a", encoding="utf-8") as fh:
    rc = subprocess.call([sys.executable, str(ROOT / "scripts/run_quadrant_pipeline.py"), "--market", MARKET,
                          "--country", COUNTRY, "--slots", "41-55", "--keep", str(KEEP),
                          "--max-discover-rounds", "0"], cwd=ROOT, env=env, stdout=fh, stderr=subprocess.STDOUT)
    fh.write(f"exit={rc}\n")
print(f"[run] pipeline exit {rc}", flush=True)
sys.exit(rc)
