"""Global Empty Capsules Market (empty capsule manufacturers), 150 companies, 15 browsers, resumable.

1. First discovery on one browser (Step 0c + a first batch), only if nothing is verified yet.
2. 15-browser verify of every candidate found so far (marker verify_only_done)
3. 15-browser COUNTRY-BY-COUNTRY passes of ~25 finds per browser, verified each pass,
   towards 200 verified (margin for 3b/3c removals)                     -> marker country_steps_done
4. The full pipeline on 15 browsers (--keep 150), no one-browser top-up.
The market brief (_pipeline/market_brief.json) sets scope, player type (Manufacturer) and B2B; queries/seeds holds the 21 companies the client sample names.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from vendor_intel.pipeline.quadrant_pipeline import dedupe_companies  # noqa: E402

MARKET, COUNTRY, KEEP, TOPUP_TO = "Global Empty Capsules Market", "global", 150, 200
OUT = ROOT / "output/chatgpt_expand/global_empty_capsules_market_global"
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


def analysed() -> bool:
    """Step 0c (market analysis) saved: discovery goes straight to 15 browsers."""
    if not CKPT.exists():
        return False
    return bool((json.loads(CKPT.read_text(encoding="utf-8")).get("data") or {}).get("market_analysis"))


# Owner 2026-10-11: discovery on 15 browsers, country by country. The one-browser
# run is only needed for Step 0c (and is skipped once that is saved).
if have() == 0 and not analysed():
    print("[run] first discovery (one browser)", flush=True)
    subprocess.call([sys.executable, str(ROOT / "scripts/run_chatgpt_expand.py"), "--query", MARKET,
                     "--country", COUNTRY, "--target", "60"], cwd=ROOT,
                    env={**env, "GOOGLE_AI_MODE_PROFILE_DIR": str(ROOT / "data/ai_mode_batch_41"),
                         "GOOGLE_AI_MODE_BROWSER": "chromium", "GOOGLE_AI_MODE_ENABLED": "true"})
    print(f"[run] first discovery: {have()} verified", flush=True)


# Candidates the stopped one-browser discovery found but did not verify:
# verify them on 15 browsers (each company on one browser) before the top-up.
if not (PIPE / "verify_only_done").exists():
    rc = subprocess.call([sys.executable, str(ROOT / "scripts/parallel_topup.py"), "--market", MARKET,
                          "--country", COUNTRY, "--keep", str(TOPUP_TO), "--browsers", "15", "--slot-start", "41",
                          "--verify-only", "--timeout-minutes", "30"], cwd=ROOT, env=env)
    if rc == 0:
        (PIPE / "verify_only_done").write_text("done\n", encoding="utf-8")
    print(f"[run] after verifying found candidates: {have()} verified", flush=True)


def topup(extra: list[str], marker: str) -> None:
    if (PIPE / marker).exists() or have() >= TOPUP_TO or not analysed():
        return
    rc = subprocess.call([sys.executable, str(ROOT / "scripts/parallel_topup.py"), "--market", MARKET,
                          "--country", COUNTRY, "--keep", str(TOPUP_TO), "--browsers", "15", "--slot-start", "41",
                          "--timeout-minutes", "120"] + extra, cwd=ROOT, env=env)
    if rc == 0:
        (PIPE / marker).write_text("done\n", encoding="utf-8")


# Country sweep in small steps (owner 2026-10-11): parallel_topup hands every
# browser the WHOLE gap (each one then discovers ~260 before verifying, since
# no browser sees the others' finds). A per-pass target a little above the
# current count keeps each browser to ~25 finds -> verify -> merge, so the
# verified count moves every pass. Stops at TOPUP_TO or when a pass adds < 5.
STEP = 13  # new verified per browser per pass -> batch of 25 candidates
for n in range(1, 9):
    if (PIPE / "country_steps_done").exists() or have() >= TOPUP_TO or not analysed():
        break
    before = have()
    print(f"[run] country pass {n}: {before} verified", flush=True)
    subprocess.call([sys.executable, str(ROOT / "scripts/parallel_topup.py"), "--market", MARKET,
                     "--country", COUNTRY, "--keep", str(before + STEP), "--browsers", "15",
                     "--slot-start", "41", "--max-rounds", "1", "--timeout-minutes", "40", "--countries"],
                    cwd=ROOT, env=env)
    print(f"[run] country pass {n}: +{have() - before} -> {have()} verified", flush=True)
    if have() - before < 5:
        break
(PIPE / "country_steps_done").write_text("done\n", encoding="utf-8")
print(f"[run] discovery finished with {have()} companies; starting the pipeline", flush=True)
with open(ROOT / "logs/parallel/global_empty_capsules_market_global.log", "a", encoding="utf-8") as fh:
    rc = subprocess.call([sys.executable, str(ROOT / "scripts/run_quadrant_pipeline.py"), "--market", MARKET,
                          "--country", COUNTRY, "--slots", "41-55", "--evidence-slots", "41-60", "--keep", str(KEEP),
                          "--max-discover-rounds", "0"], cwd=ROOT, env=env, stdout=fh, stderr=subprocess.STDOUT)
    fh.write(f"exit={rc}\n")
print(f"[run] pipeline exit {rc}", flush=True)
sys.exit(rc)
