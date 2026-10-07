# The chatgpt-expand / Coherent Quadrant pipeline: full reference

A detailed map of the current pipeline: every step, what it asks Google AI
Mode, what it reads and writes, how one market's facts are corrected, and how
to run one market or a thousand. `CLAUDE.md` has the setup and the owner's
hard rules; `HANDOVER_CHAT_HISTORY.md` has the history and the owner's
preferences. (The "chatgpt" in file names is historical. Research runs through
Google AI Mode in a real browser; the DeepSeek API only writes the X/Y
parameters.)

---

## 1. One picture

```
market name + country (+ optional _pipeline/market_brief.json)
        │
 1  Discovery (AI Mode)      Step 0c market analysis → discovery rounds → verify  [only if no verified companies]
 1b Top-up (AI Mode)         discover → verify → repeat until --keep verified     [--keep]
 2  Axes (DeepSeek LLM)      5 X + 5 Y parameters + definitions for THIS market
 3  Dedupe                   one row per real company
 3b Operating status (AI Mode)   active / acquired / defunct → excluded
 3c Ownership · identity · scope · HQ (AI Mode) → automatic review (labels, adjacent, out)
 4  Quick X/Y scores (AI Mode)   2 queries per company, every company
 4b Top 20 selection         5 per quadrant (small market: adjacent fill)
 5  Deep evidence (AI Mode)  per parameter score + evidence + reasoning, Top 20 only, gap-fill rounds
 6  Composite                X/Y = parameter means, cohort band 65–100
 7  Tone                     house wording, research-team voice, gaps → "Based on primary research…"
 7b Reviews applied          analyst_review > factcheck_review > auto_review; wording; tidy
 8  Report                   HTML (interactive + classic), JSON, CSV
 8a Chart fact-check (AI Mode) status/owner/HQ/scope + every specific claim → safe decisions → re-run if changed
 8b PDF + Word
 9  VERIFY                   18 checks, all must PASS
```

Every step saves its result. Re-running the same command resumes and skips
saved work. A finished market re-runs in about 1 minute with no queries.

## 2. Inputs and outputs

**Command:**
```bat
.venv\Scripts\python.exe scripts\run_quadrant_pipeline.py --market "Global Smart Ring Market" --country global --keep 120 --slots 41-50
```
Use `--country india` (or any other country) for a single-country run, and name
the market without "Global".

**Output folder:** `output/chatgpt_expand/<slug>/`, where `<slug>` = market +
country, e.g. `accounts_payable_automation_market_global`.

| File | What |
|---|---|
| `<slug>_report.html` | the deliverable: interactive viewer with `quadrant.json` embedded |
| `<slug>_report_classic.html` | static page (VERIFY and maintenance scripts read it) |
| `<slug>_report.pdf`, `.docx` | print copies (cover, contents, one company per page) |
| `<slug>_quadrant.json` | all data: brands, scores, `score_detail` per parameter, `overall` of the long tail |
| `<slug>_companies.csv` | company list |
| `chatgpt_checkpoint_batch_all.json` | discovery checkpoint: `data.verified`, `data.rejected_mid`, `data.recalled`, `data.market_analysis` |
| `overall_only_shard*.json` | step 4 quick scores (one per browser) |
| `param_detail_prescored*.json` | step 5 evidence "sidecars" (per company → x/y → parameters → score, evidence[], assessed_on) |

**`_pipeline/` (the run's state and the market's data files):**

| File | Written by | Purpose |
|---|---|---|
| `market_brief.json` | **you** (optional) | client definition: `market_definition`, `core_scope`, `adjacent_segments`, `scope` (≤ ~900 chars). `scope` becomes `MARKET_SCOPE` for discovery, verify, axes and scope checks |
| `analyst_review.json` | **you** | the sanctioned per-market fixes (§7); always wins |
| `wording_review.json` | you | {current reasoning text: approved rewrite} |
| `axes_spec.json` | step 2 | the 5+5 parameters + definitions (frozen once written; delete it to regenerate) |
| `dedupe_groups.json` | step 3 | names merged into one company |
| `operating_status.json`, `status_shard*.json`, `excluded_companies.json` | 3b | status answers, exclusions |
| `ownership.json`, `identity_check.json`, `scope_check.json`, `hq_check.json`, `facts_*_shard*.json` | 3c | AI Mode answers |
| `auto_review.json` | 3c | automatic decisions (exclude, ownership labels, adjacent, display names) |
| `overall_names.json`, `long_tail.json`, `evidence_pool.json`, `chart_fill_adjacent.json` | 4 / 4b | scoring pool and chart choice |
| `evidence_r*_names.json`, `reasoning_r*_names.json`, `evidence_complete.json` | 5 | gap-fill bookkeeping |
| `chart_final.json`, `top20_names.json` | 6 / 8 | the chart list passed to the report |
| `factcheck/findings.json`, `findings.md`, `browser_*.log` | 8a | fact-check answers and the review list |
| `factcheck_review.json` | 8a | automatic decisions from the fact-check |
| `logs/*.log` | all | per-step logs (report.log, factcheck.log, …) |
| marker files (`parallel_topup_done`, …) | run scripts | let a launcher skip a finished stage |

## 3. Google AI Mode (the research engine)

- `src/vendor_intel/scraping/google_ai_mode.py` drives a **patchright** Chromium
  per profile slot: `data/ai_mode_batch_<slot>[_chromium]`, slots 41–50 = 10
  browsers.
- The CAPTCHA Raptor extension (`extensions/captcha-raptor/`) is loaded
  automatically.
- The prompt is sent as a Google search URL (`?q=…&udm=50`), so it must fit in
  about 7,800 URL characters. `chatgpt_expand._fits_ai_mode` decides.
  Verification shrinks its batch until the prompt fits, rather than using the
  API.
- Answers are parsed as JSON. `parse_json_answer(..., prompt=)` rejects JSON
  copied verbatim from the prompt's example.
- Automatic recovery:
  - **Quota page:** profile reset with a growing cool-off.
  - **"Content wasn't generated" / "Verifying your request":** cookies
    cleared and browser relaunched twice, then a profile reset.
  - **Crash:** the browser is reopened.
  - Archived profiles are renamed, not deleted.
- Pacing: `GOOGLE_AI_MODE_QUERY_DELAY` (the owner's runs use 10 s).
- Rate limits: ten browsers on one IP get "Verifying your request" often, and
  the `/sorry/` block cannot be solved. Use fewer browsers or wait.

## 4. Steps in detail

### Step 1: Discovery (`scripts/run_chatgpt_expand.py` → `pipeline/chatgpt_expand.py`)
Runs only when the checkpoint has no verified companies. Internal sub-steps:

- **0c Market analysis** (`_analyze_market_for_discovery`, AI Mode): returns
  `market_type` (B2B/B2C), `market_participants`, `primary_participant`,
  `core_scope`, `adjacent_segments`.
  - `canonical_player_type` maps the player type onto: Brand / Marketer,
    Manufacturer, Solution Provider, Service Provider.
  - `publish_discovery_market` shares it with discovery and verify.
  - If AI Mode fails here, the run **stops**. It never falls back.
  - With a market brief, the orchestrator overwrites `market_definition`,
    `core_scope` and `adjacent_segments` with the client's text.
- **1 Discovery rounds** (`pipeline/discovery_rounds.py::discover_in_rounds`, AI Mode):
  - Each round asks for about 10 more companies (`DISCOVER_BATCH`).
  - Each prompt has WHO QUALIFIES, STRICTLY EXCLUDE (consultancies,
    distributors, contract manufacturers, suppliers, non-selling parents),
    and a "Do NOT repeat" list.
  - From round 2 the rounds steer toward under-covered regions. After 3
    empty rounds they go region by region, then country by country
    (single-country runs go state by state, India and the UK).
  - The `is_contract_manufacturer` filter skips markers that name the
    market itself.
- **2/3 Web discovery / ddgs harvest:** skipped when AI Mode is on.
- **4 Verify** (`gpt_verify_market`, AI Mode): batches of up to 12, shrunk to
  fit the URL.
  - Prompt: `verify_criteria_prompt` + `MARKET_SCOPE` (stated once) + an HQ
    RULE for country runs.
  - `verify_should_keep` keeps a company only when it is in the market,
    builds/owns the product, has confidence ≥ 70, its role matches the
    market's player type or categories (checked **before** the channel drop
    list), and it is `active`. When unsure, it drops.
  - 4b merges rows. 4c runs the generic market gate
    (`expand_market_gate.py`, one `"*"` profile).
- **5 column fill / 6 final verify:** off by default.
- **6c X/Y scoring:** **skipped** (`EXPAND_DISCOVERY_XY=0`, set by the
  orchestrator); steps 2 and 4 do it once.
- **6d detail rows.**

### Step 1b: Top-up (`scripts/discover_verify_rounds.py`)
With `--keep N`: discover a batch, verify only the new ones, repeat until N
verified companies exist after dedupe (up to `--max-discover-rounds`, default
10). If the market runs out, it warns and keeps what exists, never padding.
For more speed, use `scripts/parallel_topup.py` (§9).

### Step 2: Axes (`quadrant/axis_define.py::define_market_axes`, DeepSeek)
- The LLM gets **only** the market name, geography and `MARKET_SCOPE`. There
  is no industry catalog, no sector label and no fallback.
- It must return 5 X + 5 Y parameters with definitions. A short answer is
  retried up to 3 times, then the run stops.
- Written once to `axes_spec.json` and reused by every step.
- Internal keys stay "Product Strength" / "Business Strength". The displayed
  titles come from the player type: X = Service / Technology / Product
  Capability, Y = Business Capability. `QUADRANT_X_TITLE` passes the X title
  to the quick scorer.

### Step 3: Dedupe (`quadrant_pipeline.dedupe_companies`)
Union-find on same registrable domain or same name minus legal suffixes.
Saved to `dedupe_groups.json`.

### Step 3b: Operating status (`scripts/check_operating_status.py`, AI Mode)
- 10 companies per query, split across every browser.
- Excluded: a company acquired, defunct or exited **with a stated event**.
  No answer means kept.
- Also excluded: `exclude` entries from the analyst and fact-check reviews.
- A pinned chart that loses a company refills that quadrant.

### Step 3c: Facts (`scripts/check_company_facts.py`, `pipeline/company_facts.py`, AI Mode)
- **Ownership:** 10 per query; unclear answers are re-asked one by one.
- **Identity:** a one-company check when an answer is doubtful.
- **Scope:** 10 per query, judged core / adjacent / out against the brief or
  Step 0c by the **product test**. Core means the market's product is the main
  product. A module inside a different main product is adjacent, unless the
  definition explicitly includes such modules. Services firms and resellers
  are out.
- **HQ:** country runs only.
- `auto_review` turns the answers into decisions:
  - Excluded: absorbed companies, duplicate old names, non-existent
    companies and `out`.
  - Adjacent companies are kept in the long tail, off the chart.
- Owner labels come from `owner_entry`. It requires a real purchase:
  "acquired", "acquisition", "take-private", "buyout" or "majority stake". It
  rejects the case where the company was the buyer, and a reverse merger
  where the buyer took this company's name. The label reads "acquired by"
  under 3 years, "subsidiary of" after.

### Step 4: Quick scores (`scripts/score_overall_only.py`, sharded per browser, AI Mode)
- Every kept company gets 2 queries: an X scorecard (5 parameters) and a Y
  scorecard. A parameter the answer skips is re-asked alone.
- X/Y are the parameter means; Overall = (X+Y)/2. Feeds the long-tail bubbles
  and the chart choice.

### Step 4b: Top 20 (`quadrant_pipeline.select_top_by_quadrant`)
- Split at the pool's median X and Y; take the best 5 by Overall from each
  quadrant. A short quadrant's slots go to the best remaining.
- Adjacent companies are never charted. Exception for a **small market**:
  when there are fewer core companies than slots, the strongest adjacent
  companies fill the rest, recorded in `chart_fill_adjacent.json`.
- `--reselect` re-picks from an enlarged pool; `--chart-top` pins the chart
  by hand.

### Step 5: Deep evidence (`prescore_verified.py`, `fill_missing_parameters.py`, `fill_missing_assessed_on.py`, AI Mode)
- Top 20 only: for each of the 10 parameters, a score, evidence bullets and
  "why" reasoning.
- Gap-fill rounds (`--max-rounds`, default 3) re-ask missing parameters.
- Prompts carry `ai_mode_scorer.EVIDENCE_RULES`: status and dates as the
  source states; company claims written "The company reports …"; "verified"
  only for independent sources; no directory, estimate or review sites; no
  footnotes or URLs; current names.
- Before step 5, `drop_invalid_sources` removes bullets citing banned sites,
  so the parameter is re-asked.
- Sidecars are written atomically (temp file + rename).

### Step 6: Composite (`scripts/seed_from_full_evidence.py`)
X/Y = mean of the 5 parameter scores, rescaled into the cohort band 65–100,
5 per quadrant.

### Step 7: Tone (`scripts/rewrite_assessed_on_tone.py` → `primary_research_wording.to_primary`)
- Applies the house style to every reasoning text and bullet: team voice;
  gaps become the single sentence "Based on primary research, the company has
  not disclosed <what>."
- Recognised gap forms: "not publicly …", "remains undisclosed", "no …
  evidence was found", "there is no …", "has/have not been disclosed",
  ", though … were not disclosed", "We verified that no … have been recorded".
- Also: "verified self-reported" becomes "self-reported"; "We verified that
  the company's rating rests on" becomes "The rating rests on".
- It fails loudly on an unreadable sidecar, and the pipeline stops.

### Step 7b: Reviews applied (`company_status.load_review` + `apply_*`)
- HQ, display name, ownership and corrections are applied.
- `wording_review.json` rewrites are applied.
- `tidy_evidence`:
  - removes citation leftovers: footnotes, raw links, source chips such as
    "www.x.com +3" or "jaggaer +3", a trailing "note", "U.S..";
  - turns absence-only bullets into "Not available", shown only alone and
    once.

### Step 8: Report (`build_report_from_composite.py` → `quadrant/html_report.py`, then `quadrant/viewer.py`)
- Builds HTML, JSON and CSV. The chart is the orchestrator's list
  (`--fixed-top20`); `--top-n` sets the size.
- The interactive viewer (template `quadrant/templates/quadrant_viewer.html`)
  becomes `<slug>_report.html`, with the static page kept as `_classic`.

### Step 8a: Chart fact-check (every run), see §6.

### Step 8b: PDF + Word (`export_report_pdf.py`, `export_report_docx.py`)
- The PDF has a cover with key figures, contents with page numbers, each
  section on a new page and one company per page.
- Optional covers: `_pipeline/front_cover.pdf` / `pdf_back_cover.pdf`, or the
  same files in `config/`.
- The Word text is read from the printed page.

### Step 9: VERIFY (`verify()` in the orchestrator), all must PASS
1. 5 params on X and Y
2. Capability axis titles
3. no inactive, acquired or excluded company listed
4. Top companies have score + evidence + reasoning for all 10 parameters
5. report keeps N
6. chart has 20
7. 5/5/5/5 split
8. X/Y = mean of parameters
9. no hedge wording or first person
10. Other Noticeable Player bubbles only
11. interactive data embedded, no tooltip
12. long tail sorted by strength
13. no research-publisher name
14. no adjacent company on the chart (except the recorded small-market fill)
15. supporting-point rules ("Not available", no citation leftovers, no banned sites)
16. every company has an HQ
17. every X/Y ≥ 65
18. **chart fact-check complete** for every chart company

When a line fails, fix the cause in generic code (or the market's review
file) and re-run.

## 5. The review layers (how decisions combine)

`company_status.load_review(pipe_dir)` merges three layers. **The analyst
always wins.**

```
analyst_review.json      (you)            ── wins over ──┐
factcheck_review.json    (step 8a, auto)  ── wins over ──┤→ exclude / adjacent / ownership / hq / corrections / display
auto_review.json         (step 3c, auto)                 ┘
```

- Analyst `keep` undoes an automatic exclusion. An analyst `scope` entry
  replaces the automatic one. An analyst `ownership` entry replaces the label
  (`"owner": ""` removes it).
- A fact-check correction is dropped if the analyst already corrected part of
  the same sentence.
- A review entry's `company` may be the legal name, any deduped variant or the
  brand (`company_status.company_aliases` uses `dedupe_groups.json` and the
  report's brand / company key).
- `corrections` are exact find/replace in that company's evidence and
  reasoning. An empty `replace` of a whole bullet removes it.

`analyst_review.json` schema:
```json
{"exclude":     [{"company": "...", "reason": "...", "source": "..."}],
 "corrections": [{"company": "...", "find": "exact text", "replace": "...", "reason": "...", "source": "..."}],
 "hq":          [{"company": "...", "headquarters": "City, Country", "source": "..."}],
 "ownership":   [{"company": "...", "owner": "...", "year": "...", "reason": "...", "source": "..."}],
 "keep":        [{"company": "...", "reason": "..."}],
 "scope":       [{"company": "...", "scope": "core|adjacent|out", "reason": "..."}],
 "display":     [{"company": "...", "current_name": "...", "source": "..."}]}
```

## 6. Step 8a: chart fact-check (every run)

**Ask** (`scripts/factcheck_chart.py`, AI Mode):
- Per chart company: one question for operating status, event, current
  name, owner and year, HQ, main product and scope (with the brief or Step 0c
  definition).
- Then every *specific* supporting point (figures, dates, names, deals,
  customers, integrations), 5 per query, each judged **correct / incorrect /
  unverified** with a corrected sentence and a source.
- Companies are split over all `--slots` browsers. Answers are saved as they
  arrive; companies already checked are not re-asked.
- A sentence a review fix changed, or one ≥ 80 % similar to a checked one,
  counts as checked.

**Decide** (`pipeline/factcheck.py::build_review`). Only these apply:

| Finding | Applied as |
|---|---|
| liquidated / dissolved / in administration **with an event** | exclude (an acquired company still trading stays) |
| scope adjacent / out | off the chart / exclude |
| owner | label via `owner_entry`, only if not already labelled by 3c or the analyst, with a year |
| HQ | only when the **country** differs from the HQ shown when checked |
| claim incorrect | replaced by the corrected sentence (house style applied) when the source is not a directory, estimate, review or research-publisher site; the edit is small (≥ 0.75 similar); and no other check of the company backs the old figure |
| claim belongs to another company | bullet removed |

Everything else (unverified claims, weak-source corrections, big rewrites)
goes to `factcheck/findings.md` for a person.

**Apply:**
- Decisions go to `factcheck_review.json`.
- If they changed, the orchestrator **re-runs itself from saved work**
  (`QUADRANT_FACTCHECK_PASS`, max 3 passes). Steps 3b/3c drop or move
  companies, the chart refills, step 5 gathers evidence for the new entrants,
  7b writes the fixes, 8 rebuilds, and 8a checks only the new entrants.
- A decision stays once made, so a company moved off the chart does not come
  back and the loop is stable.

## 7. Fixing one market's facts

1. Find the error in the report (or in `_pipeline/factcheck/findings.md`).
2. Confirm it from a primary source: the company site, a press release, a
   filing or reputable news. Not a directory or estimate site.
3. Add an entry to `_pipeline/analyst_review.json` with reason and source.
4. Re-run the same command. It is cached and takes about 1 minute; there are
   no new queries unless the chart changes.

Never edit the report files by hand. Never add a market-specific branch to code.

## 8. Configuration

**Config lists (data, generic, one per line):**

| File | Used for |
|---|---|
| `config/research_publishers.txt` | competitor publishers: never named (VERIFY + prompts) |
| `config/estimate_sites.txt` | modelled-estimate / company-data sites (RocketReach, ZoomInfo, Crunchbase, …): not sources |
| `config/employee_review_sites.txt` | Glassdoor etc.: not customer evidence |
| `config/directory_sites.txt` | SourceForge, Capterra, G2, Built In, …: not sources (fact-check rules) |
| `config/expand_market_gates.yaml` | one generic `"*"` gate profile |
| `config/front_cover.pdf`, `config/pdf_back_cover.pdf` | optional report covers |

`config/quadrant_industry_criteria.yaml` and the per-market `config/*_axes.json`
files are **not** used on the live path. They are legacy, and only used if
passed by hand with `--fixed-axes`.

**Environment (`.env` + run-time):**

| Variable | Meaning |
|---|---|
| `LLM_PROVIDER=deepseek`, `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL`, `DEEPSEEK_BASE_URL` | the LLM (axes only) |
| `GOOGLE_AI_MODE_ENABLED=true`, `GOOGLE_AI_MODE_HEADLESS=false` | AI Mode on, visible browsers |
| `GOOGLE_AI_MODE_QUERY_DELAY` | seconds between queries per browser (owner's runs: 10) |
| `GOOGLE_AI_MODE_MAX_RESETS`, `GOOGLE_AI_MODE_QUOTA_COOLOFF` | quota recovery |
| `GOOGLE_AI_MODE_PROFILE_DIR`, `GOOGLE_AI_MODE_BROWSER` | set per slot by the scripts |
| `GOOGLE_AI_MODE_BUNDLED_EXTENSIONS`, `GOOGLE_AI_MODE_EXTENSIONS` | CAPTCHA Raptor on/off, extra extensions |
| `MARKET_SCOPE` | market scope text (from `market_brief.json`) for discovery, verify, axes, scope |
| `EXPAND_DISCOVERY_XY` | `0` = discovery does not score (set by the orchestrator) |
| `EXPAND_OUTPUT_FOLDER` | alternate output root for parallel discovery copies |
| `GEO_AREA_SHARD=k/N` | give browser k its share of regions / countries / states |
| `DISCOVER_START_TIER=country` | start discovery country by country |
| `DISCOVER_BATCH`, `DISCOVER_EMPTY_BEFORE_ESCALATE` | discovery round size, escalation |
| `QUADRANT_X_TITLE`, `QUADRANT_FACTCHECK_PASS` | set internally by the orchestrator |

## 9. Scripts you run

| Script | Use |
|---|---|
| `scripts/run_quadrant_pipeline.py` | **the** pipeline for one market (all steps) |
| `scripts/run_markets_parallel.py --markets-file f.txt --workers 10 --keep 120` | many markets, one browser each (`Market | country` per line; logs in `logs/parallel/`) |
| `scripts/run_markets_split_discovery.py` | many markets, 2+ browsers per market during discovery, then the pipeline |
| `scripts/discover_split_merge.py` | one market's discovery on N browsers, merged |
| `scripts/parallel_topup.py --keep N --browsers 10 [--countries] [--verify-only]` | top up a market on N browsers (each its own copy + geo share), merge. `--countries` starts country by country; `--verify-only` verifies what stopped browsers already found |
| `scripts/factcheck_chart.py --browsers 10` | step 8a stand-alone |
| `scripts/export_report_pdf.py`, `export_report_docx.py` | rebuild print copies |
| `scripts/primary_research_wording.py --folder <dir> --review-dir <dir>` | rewrite gap wording in finished reports outside the pipeline |
| `python -m vendor_intel.scraping.google_ai_mode doctor` | browser + extension self-check |

Then run the pipeline with `--max-discover-rounds 0` after a parallel top-up,
so it does not top up again on one browser.

## 10. Running 1000 markets
- Put them in a markets file and use `run_markets_parallel.py` with as many
  workers as the IP tolerates (10 is the practical maximum on one IP; use
  fewer, or a higher delay, when "Verifying your request" appears often).
- Everything is generic: the player type, scope, parameters and checks all
  come from AI Mode or the LLM per market at run time.
- Per-market input is only optional data: `_pipeline/market_brief.json` and
  `_pipeline/analyst_review.json`.
- Every step is resumable, and a failed market can be re-run alone.
- Read `logs/parallel/summary.json`, plus each market's VERIFY block.

## 11. Generic-code guarantees (do not reintroduce)
- No market names, company tables or sector keyword lists on the live path.
  Removed so far:
  - the industry catalog seeding the axes;
  - market-name gate profiles;
  - a packaging company table;
  - sector words in the verify role lists;
  - a marine-seismic evidence rule;
  - fuzzy seed-file matching.
- A market's own player type or category is kept before any channel or
  contract-manufacturer filter.
- Discovery does not score; scoring happens once (step 4).
- Evidence sidecars are written atomically.
- Verification never falls back to the API for length (batches shrink).
- Comments and docstrings may mention past markets as examples. They have no
  effect.

## 12. Tests
```bat
set PYTHONPATH=src
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```
The baseline is **24 known failures** (listed in CLAUDE.md §6). Fact-check
rules: `tests/test_factcheck.py`. Axes rules: `tests/test_axis_fixed.py`.
Verify scope: `tests/test_verify_scope.py`.
A cached re-run of a finished market (VERIFY all PASS) is the end-to-end
regression check.
