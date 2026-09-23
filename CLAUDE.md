# CLAUDE.md: Coherent Quadrant pipeline (handover context)

This file is for Claude Code (and the developer using it) working in this repo.
It explains how the market-landscape + Coherent Quadrant pipeline works, how to
set it up on a new machine (Google AI Mode + the bundled CAPTCHA solver), how
to run any market with one command, and the rules the owner has set. Read it
before changing anything.

> Older docs (`PROJECT_HANDOFF.md`, `PLANNING_HLD_LLD.md`, `PIPELINE_END_TO_END.md`,
> `README_MARKET_INTELLIGENCE.md`) describe earlier pipelines (`run_pipeline.py`,
> `web_expand`, SearXNG/ddgs discovery). **The current path is the one below.**
> Use those docs only as background.

---

## 1. What it does

Input: a market name, e.g. `"Global Smart Ring Market"`, plus a country (`global`, `india`, …).
Output: a landscape report in `output/chatgpt_expand/<market>_<country>/`:

- `<slug>_report.html`: Coherent Quadrant chart (Top 20, 5 per quadrant),
  per-parameter scores with evidence, parameter definitions, and the
  **Other Noticeable Player** table (the long tail, shown as strength bubbles).
- `<slug>_quadrant.json`: full data (every score, including the long tail's
  `overall`), plus `<slug>_companies.csv`.
- `_pipeline/`: the run's state (axes spec, evidence pool, dedupe groups, logs).

## 2. Owner's rules (do not break these)

1. **Nothing market-specific in code.** No per-market keyword lists, company
   tables, role maps or `if market == ...` branches. Every market must run
   through the same code. Market knowledge comes from Google AI Mode or the LLM
   at run time, never from hardcoded data.
2. **Google AI Mode does the research.** Discovery, market analysis
   (B2B/B2C, player type), discovery-query writing, verification and evidence
   lookups go through Google AI Mode (a real browser). **The LLM (DeepSeek via
   the OpenAI-compatible API) is used only to generate the X/Y parameters and
   their definitions** (plus scoring prompts built on them). When AI Mode is on
   and the market analysis fails, the run stops. It never silently falls
   back to the API or defaults to B2C.
3. **Axes are fixed for every market:** X = **Product Capability**,
   Y = **Business Capability**. Only the parameters under them change per market.
   **Exactly 5 parameters on X and 5 on Y.** Internally the keys are still
   `"Product Strength"` / `"Business Strength"` (`axis_define.AXIS_X_FIXED`)
   because saved scores and prompt parsers use them; the report always displays
   the Capability titles (`quadrant_language.AXIS_X_TITLE`). Do not rename the
   internal keys.
4. **Other Noticeable Player = filled strength bubbles only.** No score number,
   no word label, **no hover tooltip (`title=`)** in that column. The score stays
   in the JSON (`overall`). The table is sorted by strength, descending.
5. **Keep the B2B/B2C logic** (`_is_b2b_market`, `market_type`,
   `canonical_player_type`, `primary_participant`, `BRAND_ROLES`/`TECH_ROLES`,
   `company_display_mode`). The owner built it deliberately; extend it, don't remove it.
6. Chart: 20 companies, 5/5/5/5 per quadrant; every X/Y ≥ 65 (cohort band
   65–100); X/Y = mean of their 5 parameter scores; every company has an HQ
   ("City, Country"); no hedge wording ("could not verify", "I found") in evidence.

## 3. Setup on a new machine (Windows)

Requirements: Python 3.11+, Google Chrome, a DeepSeek API key.

```bat
setup.bat
```
`setup.bat` creates `.venv`, installs `requirements.txt`, installs the bundled
Chromium (`python -m patchright install chromium`) and copies `.env.example` →
`.env`. Manual equivalent:
```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m patchright install chromium
copy .env.example .env
```

Minimum `.env`:
```
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=<key>
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_BASE_URL=https://api.deepseek.com
GOOGLE_AI_MODE_ENABLED=true
GOOGLE_AI_MODE_HEADLESS=false
GOOGLE_AI_MODE_QUERY_DELAY=10
```
Never commit `.env`. Never copy another person's `data/ai_mode_*` browser
profiles: they hold logged-in Google cookies. Fresh profiles are created on
first run.

### Google AI Mode backend
`src/vendor_intel/scraping/google_ai_mode.py` drives a real browser through
**patchright** (not plain playwright, which gets an instant CAPTCHA). The
prompt is sent as a Google AI Mode search (`?q=`), so a prompt must fit in the
URL (~8 KB); `_fits_ai_mode()` sends only oversized prompts to the API.
Queries are paced (`GOOGLE_AI_MODE_QUERY_DELAY`). Each parallel worker uses
its own profile `data/ai_mode_batch_<slot>` (`--slots 41-50` = 10 browsers).

Self-check:
```bat
.venv\Scripts\python.exe -m vendor_intel.scraping.google_ai_mode doctor
```
It should print `extensions loaded: ['Free AI ReCaptcha Solver by Raptor ...']`.

### CAPTCHA Raptor (bundled, automatic)
- Ships in `extensions/captcha-raptor/` (MIT licence, ~80 MB incl. ONNX
  models). **No install step, no path to set.** `installed_extensions()` loads
  every `extensions/<name>/[extension/]manifest.json` into every AI Mode
  browser, including the per-slot ones. The same extension (matched by
  manifest name) is never loaded twice.
- Extensions force **bundled Chromium** (managed Chrome ignores
  `--load-extension`). Chromium is CAPTCHA'd more often than Chrome; the
  solver handles Google's image-grid reCAPTCHA. It **cannot** clear the
  "unusual traffic" `/sorry/` block; only slower pacing avoids that.
- Off switch: `GOOGLE_AI_MODE_BUNDLED_EXTENSIONS=false`. Extra extensions:
  `GOOGLE_AI_MODE_EXTENSIONS=path1;path2`.
- Tests disable bundled loading in `tests/conftest.py`.

## 4. Run any market (one command)

```bat
.venv\Scripts\python.exe scripts\run_quadrant_pipeline.py --market "Global Smart Ring Market" --country global --keep 120
```

| Flag | Meaning |
|---|---|
| `--market` / `--country` | the market; output folder = `default_output_dir(market, country)` |
| `--keep N` | end with exactly N verified companies (20 chart + N-20 long tail). Discovery runs **discover → verify → discover more → verify** until N verified companies exist after dedupe, then the best N by score are kept |
| `--discover-target` | first discovery batch (default: `--keep`, else 400) |
| `--max-discover-rounds` | top-up rounds cap (default 10) |
| `--top-n` | chart size (default 20) |
| `--slots 41-50` | browser profiles for parallel scoring (fewer on slow machines) |
| `--dry-run` | print the plan, open no browser |
| `--fixed-axes file.json` / `--top-list` / `--chart-top` / `--reselect` | manual overrides (rarely needed) |

Every step is resumable: re-running the same command skips saved work.
The run ends with a **VERIFY** block; every line must be `[PASS]`:
5 params on X and Y · Capability axis titles · Top companies have
score+evidence+reasoning for all 10 parameters · report keeps N (with `--keep`) ·
chart has 20 · 5/5/5/5 · X/Y = mean of parameters · no hedge wording ·
Other Noticeable Player bubbles only (no numbers, no tooltip) · sorted by
strength · every company has an HQ · every X/Y ≥ 65.

If a VERIFY line fails, fix the cause in the **generic** code and re-run.
Never patch a single market's output by hand or add a market-specific fix.

## 5. Pipeline stages and where the code lives

Orchestrator: `scripts/run_quadrant_pipeline.py` (+ helpers in
`src/vendor_intel/pipeline/quadrant_pipeline.py`: dedupe, evidence gaps, ranking).

| # | Stage | Code |
|---|---|---|
| 1 | **Discovery** (only if the market has no verified companies): Step 0c market analysis → discovery rounds → verify → fill | `scripts/run_chatgpt_expand.py` → `pipeline/chatgpt_expand.py` |
| 1b | **Top-up** (`--keep`): discover a batch, verify only new companies, repeat | `scripts/discover_verify_rounds.py` |
| 2 | **Axes spec**: 5+5 market-specific parameters + definitions (LLM), fixed axis names → `_pipeline/axes_spec.json` | `quadrant/axis_define.py` (`define_market_axes`, `explain_market_parameters`) |
| 3 | **Dedupe**: one row per real company (same registrable domain or same name minus legal suffixes; union-find) | `quadrant_pipeline.dedupe_companies` |
| 4 | **Overall-only scoring** for every unscored company (ranks the pool, feeds long-tail bubbles) | `scripts/score_overall_only.py` (sharded per slot) |
| 5 | **Evidence** for the Top N: per-parameter score + evidence + reasoning, gap-fill rounds | `prescore_verified.py`, `fill_missing_parameters.py`, `fill_missing_assessed_on.py` |
| 6 | **Composite**: X/Y/Overall, cohort band 65–100, 5 per quadrant | `scripts/seed_from_full_evidence.py` |
| 7 | **Tone**: desk-research wording, no hedges | `scripts/rewrite_assessed_on_tone.py` |
| 8 | **Report**: HTML/JSON/CSV | `scripts/build_report_from_composite.py` → `quadrant/html_report.py` |
| 9 | **Verify** | `verify()` in the orchestrator |

### Market analysis (Step 0c) and B2B/B2C
`_analyze_market_for_discovery()` asks AI Mode for `market_type` (B2B/B2C),
`market_participants`, `primary_participant`. `canonical_player_type()`
forces the player type onto four labels: **Brand / Marketer** (B2C),
**Manufacturer**, **Solution Provider**, **Service Provider**.
`publish_discovery_market()` publishes it to discovery and verify, so the
first batch and every top-up batch ask for the same company type.

### How discovery queries are written (no manual queries)
`pipeline/discovery_rounds.py::build_round_prompt`: each round asks for
10 more (`DISCOVER_BATCH`, 5–20). B2C asks for brands + the company behind
each; service markets ask for companies directly. Every prompt has
WHO QUALIFIES, STRICTLY EXCLUDE (consultancies, distributors, contract
manufacturers, suppliers, non-selling parents), and a "Do NOT repeat" list
(newest 40 names / 1,500 chars + "…and N more, prefer smaller/regional").
From round 2 it steers toward under-covered regions; after 3 empty rounds
(`DISCOVER_EMPTY_BEFORE_ESCALATE`) it asks region by region, then country by
country, then re-sweeps regions (single-country runs go state by state).
Stops at target, or reports "exhausted" (never invents companies). AI Mode
also writes up to 8 market-specific queries (`_generate_discovery_queries`).

### How verification works
`chatgpt_expand.gpt_verify_market`: batches of 12 companies, prompt from
`verify_criteria_prompt()` (required type from Step 0c; KEEP/DROP rules;
"when unsure, DROP"; JSON `name, in_market, builds_or_owns, role,
fits_criteria, confidence, reason`). `verify_should_keep()` keeps a company
only if in market + builds/owns + confidence ≥ 70 + role not a
channel/media role + role matches the required type (any of the four player
types or the market's own categories). Unparseable or skipped answers = DROP.

### Country runs (`--country india`, `germany`, …)
Any country other than `global` is a single-country run
(`geo_rotation.is_single_country`). Every discovery round asks for companies
**HEADQUARTERED IN <country>** (a foreign company's local office, plant,
subsidiary or distributor does not qualify). When the broad rounds run dry it
sweeps states (only countries with a list in `geo_rotation.STATES_BY_COUNTRY`,
currently India), and never escalates to other regions or countries.
Verification adds an **HQ RULE** and an `hq_in_country` field; a company is
kept only if the answer is `true` (fail closed). Name the market without
"Global" for a country run, e.g. `--market "Smart Ring Market" --country india`.

## 6. Tests

```bat
set PYTHONPATH=src
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```
Baseline: **24 failures already exist** (test_ai_overview, test_brand_owner,
test_candidate_pool, test_company_registry, test_expand_detail_columns,
test_hybrid_validation, test_market_registry, test_quadrant_brand_meta,
test_catalog_loads_medical_devices, test_role_rules Avocado profile,
test_scrape_fetch_selenium). Anything beyond those 24 is a regression.
`tests/conftest.py` forces `GOOGLE_AI_MODE_ENABLED=false` so no test opens a browser.

Reference markets that pass every VERIFY check:
`Marine Seismic Data Processing Services Market` (B2B, Service Provider) and
`Global Wearable Glucometer Market` (B2C). Re-running them (no new queries,
everything saved) is the quickest regression check after a change, **if**
their `output/` folders were shared.

## 7. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Browser shows CAPTCHA grid | Raptor solves it; if not, solve by hand in the window. The run continues |
| "Something went wrong" / unusual-traffic page | Google rate block. Raise `GOOGLE_AI_MODE_QUERY_DELAY`, use fewer `--slots`, wait |
| "Opening in existing browser session" | orphaned Chromium holds the profile; the code kills orphans, else close Chromium |
| Step 0c RuntimeError | AI Mode failed on market analysis (by design, no fallback). Re-run; it is checkpointed |
| `axes_spec.json has N X / M Y parameters` | delete `_pipeline/axes_spec.json` to regenerate with 5+5 |
| Fewer than `--keep` companies | market exhausted; the run warns and keeps what exists (never pads) |
| Discovery re-run finds nothing new | discovery is checkpointed per step; use `--keep` (top-up rounds), not a bigger `--discover-target`, on an existing market |

## 8. Conventions for changes

- Match surrounding code style; comments explain *why*.
- Generic fixes only (see rule 1). If you find a hardcoded market list,
  company table or keyword map on the live path, remove it or move the data
  out of code.
- Keep `CLAUDE.md`, `README.md` and `.env.example` in sync when flags,
  env vars or stages change.
