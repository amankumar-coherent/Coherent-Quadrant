"""One market, resumable: python logs/run_market.py "Global X Market" [--keep 150] [--browsers 20].

1. First discovery on one browser (Step 0c + a first batch), only if nothing is verified yet.
2. 15-browser verify of every candidate found so far (marker verify_only_done)
3. 15-browser COUNTRY-BY-COUNTRY passes of ~25 finds per browser, verified each pass,
   towards 200 verified (margin for 3b/3c removals)                     -> marker country_steps_done
4. The full pipeline on 15 browsers (--keep 150), no one-browser top-up.
The market brief (_pipeline/market_brief.json) sets scope, player type (Manufacturer) and B2B; queries/seeds holds the 21 companies the client sample names.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from vendor_intel.pipeline.quadrant_pipeline import dedupe_companies  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("market")
ap.add_argument("--country", default="global")
ap.add_argument("--keep", type=int, default=150)
ap.add_argument("--browsers", type=int, default=20)
ap.add_argument("--discovery-only", action="store_true", help="stop before the pipeline")
ap.add_argument("--slot-start", type=int, default=41, help="first browser slot (one market per slot range)")
ap.add_argument("--state-wise", action="store_true",
                help="single-country run: discover state by state (state names only, no cities)")
ap.add_argument("--discover-to", type=int, default=0,
                help="stop discovery at this many verified (default: keep x 4/3)")
ap.add_argument("--global-focus", action="store_true",
                help="no country-by-country passes: global passes, focus areas from the brief first")
a = ap.parse_args()
from vendor_intel.pipeline.web_expand import default_output_dir  # noqa: E402

MARKET, COUNTRY, KEEP = a.market, a.country, a.keep
TOPUP_TO = round(KEEP * 4 / 3)  # margin for the status / ownership / scope removals
if a.discover_to:
    TOPUP_TO = a.discover_to  # owner 2026-10-14: move on once this many are verified
NB = str(a.browsers)
S0 = a.slot_start
FIRST, LAST = str(S0), str(S0 + a.browsers - 1)
OUT = Path(default_output_dir(MARKET, COUNTRY))
PIPE = OUT / "_pipeline"
CKPT = OUT / "chatgpt_checkpoint_batch_all.json"
brief = json.loads((PIPE / "market_brief.json").read_text(encoding="utf-8"))
env = {**os.environ, "PYTHONIOENCODING": "utf-8", "GOOGLE_AI_MODE_QUERY_DELAY": "10",
       "MARKET_SCOPE": " ".join(brief["scope"].split()), "MARKET_PLAYER_TYPE": brief["player_type"],
       "MARKET_TYPE": brief["market_type"], "EXPAND_DISCOVERY_XY": "0"}
if a.state_wise:
    # Owner 2026-10-14: state by state from the first round, state names only.
    env.update(DISCOVER_START_TIER="state", DISCOVER_STATE_NAMES_ONLY="1")
if a.global_focus:
    # Owner 2026-10-14: search globally; the countries / areas the market names come first.
    env.update(DISCOVER_FOCUS_AREAS=";".join(brief.get("focus_areas") or []), DISCOVER_SKIP_COUNTRY_TIER="1")
    if not (PIPE / "country_steps_done").exists():
        (PIPE / "country_steps_done").write_text("skipped: --global-focus\n", encoding="utf-8")


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
                     "--country", COUNTRY, "--target", "40"], cwd=ROOT,
                    env={**env, "GOOGLE_AI_MODE_PROFILE_DIR": str(ROOT / f"data/ai_mode_batch_{S0}"),
                         "GOOGLE_AI_MODE_BROWSER": "chromium", "GOOGLE_AI_MODE_ENABLED": "true"})
    print(f"[run] first discovery: {have()} verified", flush=True)


# Candidates the stopped one-browser discovery found but did not verify:
# verify them on every browser (each company on one browser) before the top-up.
if not (PIPE / "verify_only_done").exists():
    rc = subprocess.call([sys.executable, str(ROOT / "scripts/parallel_topup.py"), "--market", MARKET,
                          "--country", COUNTRY, "--keep", str(TOPUP_TO), "--browsers", NB, "--slot-start", FIRST,
                          "--verify-only", "--timeout-minutes", "30"], cwd=ROOT, env=env)
    if rc == 0:
        (PIPE / "verify_only_done").write_text("done\n", encoding="utf-8")
    print(f"[run] after verifying found candidates: {have()} verified", flush=True)


def topup(extra: list[str], marker: str) -> None:
    if (PIPE / marker).exists() or have() >= TOPUP_TO or not analysed():
        return
    rc = subprocess.call([sys.executable, str(ROOT / "scripts/parallel_topup.py"), "--market", MARKET,
                          "--country", COUNTRY, "--keep", str(TOPUP_TO), "--browsers", NB, "--slot-start", FIRST,
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
                     "--country", COUNTRY, "--keep", str(before + STEP), "--browsers", NB,
                     "--slot-start", FIRST, "--max-rounds", "1", "--timeout-minutes", "40", "--countries"],
                    cwd=ROOT, env=env)
    print(f"[run] country pass {n}: +{have() - before} -> {have()} verified", flush=True)
    if have() - before < 5:
        break
(PIPE / "country_steps_done").write_text("done\n", encoding="utf-8")

# Owner 2026-10-14: a market that stays small after the country passes is searched
# GLOBALLY too (no --countries): the broad question, then region by region, each
# browser on its own regions (GEO_AREA_SHARD). 3 rounds per browser per pass; stops
# when a pass adds < 5 or at the target.
for n in range(1, 7 if a.browsers > 3 else 13):
    if (PIPE / "global_steps_done").exists() or have() >= TOPUP_TO or not analysed():
        break
    before = have()
    print(f"[run] discovery pass {n} ({COUNTRY}): {before} verified", flush=True)
    subprocess.call([sys.executable, str(ROOT / "scripts/parallel_topup.py"), "--market", MARKET,
                     "--country", COUNTRY, "--keep", str(before + STEP * 2), "--browsers", NB,
                     "--slot-start", FIRST, "--max-rounds", "3", "--timeout-minutes", "50"],
                    cwd=ROOT, env=env)
    print(f"[run] discovery pass {n} ({COUNTRY}): +{have() - before} -> {have()} verified", flush=True)
    if have() - before < 5:
        break
(PIPE / "global_steps_done").write_text("done\n", encoding="utf-8")
if a.discovery_only:
    print(f"[run] discovery finished with {have()} companies; --discovery-only: pipeline not started", flush=True)
    sys.exit(0)
print(f"[run] discovery finished with {have()} companies; starting the pipeline", flush=True)
with open(ROOT / f"logs/parallel/{OUT.name}.log", "a", encoding="utf-8") as fh:
    rc = subprocess.call([sys.executable, str(ROOT / "scripts/run_quadrant_pipeline.py"), "--market", MARKET,
                          "--country", COUNTRY, "--slots", f"{FIRST}-{LAST}", "--evidence-slots", f"{FIRST}-{LAST}", "--keep", str(KEEP),
                          "--max-discover-rounds", "0"], cwd=ROOT, env=env, stdout=fh, stderr=subprocess.STDOUT)
    fh.write(f"exit={rc}\n")
print(f"[run] pipeline exit {rc}", flush=True)
sys.exit(rc)
