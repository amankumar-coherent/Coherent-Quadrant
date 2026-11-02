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
ap.add_argument("--pipeline-browsers", type=int, default=0,
                help="browsers for the steps AFTER discovery (verify, facts, scoring, evidence). Discovery is bounded by how fast Google answers one browser, the later steps are not, so they parallelise further (owner 2026-10-29). Default: same as --browsers")
ap.add_argument("--city-wise", action="store_true",
                help="single-country run: discover area by area WITH each area's cities named "
                     "(owner 2026-10-28, Mozambique: the broad rounds ran dry at 17 companies)")
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
# The pipeline may use a wider slot range than discovery did; they never run at once.
PIPE_NB = a.pipeline_browsers or a.browsers
PIPE_FIRST, PIPE_LAST = str(S0), str(S0 + PIPE_NB - 1)
OUT = Path(default_output_dir(MARKET, COUNTRY))
PIPE = OUT / "_pipeline"
CKPT = OUT / "chatgpt_checkpoint_batch_all.json"
brief = json.loads((PIPE / "market_brief.json").read_text(encoding="utf-8"))
"""Pacing: 10s between queries, unless the operator has already set a slower one.
It was hardcoded, so a blocked market could not be slowed down without editing this
file (owner 2026-10-28, Mozambique: 188 unusable AI Mode replies against 20 usable
and 30 CAPTCHAs -- the browsers then reported the market "exhausted" after a single
empty round, which is a rate block, not an empty market)."""
env = {**os.environ, "PYTHONIOENCODING": "utf-8",
       "GOOGLE_AI_MODE_QUERY_DELAY": os.environ.get("GOOGLE_AI_MODE_QUERY_DELAY") or "10",
       "MARKET_SCOPE": " ".join(brief["scope"].split()), "MARKET_PLAYER_TYPE": brief["player_type"],
       "MARKET_TYPE": brief["market_type"], "EXPAND_DISCOVERY_XY": "0",
       # How this market qualifies a company: who MAKES the product, or who SELLS it
       # through the market's channel ("sells_in_channel"). Verify reads it too, so a
       # B2C Brand / Marketer market can still hold the marketplaces that sell the goods.
       "MARKET_SCOPE_TEST": str(brief.get("scope_test") or "")}
if a.state_wise:
    # Owner 2026-10-14: state by state from the first round, state names only.
    env.update(DISCOVER_START_TIER="state", DISCOVER_STATE_NAMES_ONLY="1")
if a.city_wise:
    # Owner 2026-10-28: area by area from the first round, each area's cities named --
    # the opposite of --state-wise, for a country whose companies sit outside the capital.
    env.update(DISCOVER_START_TIER="state")
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


def load_seeds() -> None:
    """queries/seeds/<market slug>.txt = the companies the client's sample names. The first
    one-browser discovery loads them; with Step 0c pre-filled that step is skipped, so
    they are added to the candidate list here (once; each is verified like any other)."""
    if not CKPT.exists():
        return
    from vendor_intel.pipeline import chatgpt_expand as ce

    seeds = ce._seed_candidates(MARKET, COUNTRY)
    if not seeds:
        return
    state = json.loads(CKPT.read_text(encoding="utf-8"))
    data = state.setdefault("data", {})
    known = {ce._dedupe_key(str(r.get("name") or r.get("Company") or ""))
             for k in ("recalled", "verified", "rejected_mid") for r in data.get(k) or []}
    new = [x for x in seeds if ce._dedupe_key(x["name"]) not in known]
    if new:
        data["recalled"] = list(data.get("recalled") or []) + new
        data["seeds_count"] = len(seeds)
        CKPT.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        (PIPE / "verify_only_done").unlink(missing_ok=True)  # verify them on every browser next
        print(f"[run] {len(new)} seed companies from the client's sample added to the candidates", flush=True)


load_seeds()

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
TOPUP_AFTER_CHECKS = 3  # discover-again cycles when the checks leave the report under --keep
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
def run_pipeline() -> int:
    print(f"[run] starting the pipeline on {PIPE_NB} browsers "
          f"(slots {PIPE_FIRST}-{PIPE_LAST})", flush=True)
    with open(ROOT / f"logs/parallel/{OUT.name}.log", "a", encoding="utf-8") as fh:
        code = subprocess.call(
            [sys.executable, str(ROOT / "scripts/run_quadrant_pipeline.py"), "--market", MARKET,
             "--country", COUNTRY, "--slots", f"{PIPE_FIRST}-{PIPE_LAST}",
             "--evidence-slots", f"{PIPE_FIRST}-{PIPE_LAST}", "--keep", str(KEEP),
             "--max-discover-rounds", "0"], cwd=ROOT, env=env, stdout=fh, stderr=subprocess.STDOUT)
        fh.write(f"exit={code}\n")
    return code


def in_report() -> int:
    """Companies the finished report keeps, i.e. AFTER the 3b/3c checks removed some."""
    try:
        q = json.loads((OUT / f"{OUT.name}_quadrant.json").read_text(encoding="utf-8"))
        return len(q.get("brands") or [])
    except Exception:  # noqa: BLE001 -- no report yet
        return 0


print(f"[run] discovery finished with {have()} companies", flush=True)
rc = run_pipeline()

# Owner 2026-10-29: the operating-status, ownership and scope checks remove companies
# AFTER discovery has already stopped, so a market can finish well under --keep even
# though more companies are there to be found (Biopharma Buffer: 303 discovered -> 150
# in the report). When that happens, discover again for the shortfall and rebuild, until
# the report reaches --keep or the market is genuinely exhausted.
for cycle in range(1, TOPUP_AFTER_CHECKS + 1):
    kept = in_report()
    if rc != 0 or kept >= KEEP:
        break
    before = have()
    # the shortfall, plus margin because the checks will remove some of the new ones too
    want = before + (KEEP - kept) + 25
    print(f"[run] report keeps {kept} of --keep {KEEP} after the checks; top-up {cycle}: "
          f"discovering towards {want} verified", flush=True)
    for marker in ("country_steps_done", "global_steps_done", "topup_failures.json"):
        (PIPE / marker).unlink(missing_ok=True)
    subprocess.call([sys.executable, str(ROOT / "scripts/parallel_topup.py"), "--market", MARKET,
                     "--country", COUNTRY, "--keep", str(want), "--browsers", NB,
                     "--slot-start", FIRST, "--max-rounds", "3", "--timeout-minutes", "50"],
                    cwd=ROOT, env=env)
    gained = have() - before
    print(f"[run] top-up {cycle}: +{gained} -> {have()} verified", flush=True)
    if gained < 5:
        print(f"[run] market exhausted: the report keeps {kept}, which is all it has", flush=True)
        break
    rc = run_pipeline()
print(f"[run] pipeline exit {rc}", flush=True)
sys.exit(rc)
