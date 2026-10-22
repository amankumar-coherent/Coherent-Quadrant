# CLAUDE.md: Coherent Quadrant pipeline (handover context)

This file is for Claude Code (and the developer using it) working in this repo.
It explains how the market-landscape + Coherent Quadrant pipeline works, how to
set it up on a new machine (Google AI Mode + the bundled CAPTCHA solver), how
to run any market with one command, and the rules the owner has set. Read it
before changing anything.

> **Also read:** `HANDOVER_CHAT_HISTORY.md` (what was done with the owner so far,
> their preferences and working style, the state of every market, open items)
> and `PIPELINE_CHATGPT_EXPAND.md` (the full reference of the pipeline: every
> step, file, review layer, env var and script).
>
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
3. **Axis titles follow the player type:** Y = **Business Capability** always.
   X = **Service Capability** for Service Provider markets, **Technology
   Capability** for Solution Provider markets, **Product Capability** otherwise
   (`quadrant_language.x_axis_title`, from `criteria.relevance.keep_roles`, never
   a market-name list). Only the parameters under them change per market.
   **Exactly 5 parameters on X and 5 on Y.** Internally the keys are still
   `"Product Strength"` / `"Business Strength"` (`axis_define.AXIS_X_FIXED`)
   because saved scores and prompt parsers use them; the report displays the
   Capability titles. Do not rename the internal keys.
4. **Other Noticeable Player = filled strength bubbles only.** No score number,
   no word label, **no hover tooltip (`title=`)** in that column. The score stays
   in the JSON (`overall`). The table is grouped by quadrant (every Leader, then
   Challengers, Trailblazers, Emerging Players) and sorted by strength,
   descending, within each quadrant (owner 2026-10-21).
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
- Source: https://github.com/amankumar-coherent/chrome-scraper-extensions
  (`captcha-raptor/`), copied into `extensions/captcha-raptor/` as a vendored
  copy — not a git submodule, so a clone of this repo has it with no extra
  step. Pull that repo's `extension/` folder again here to update it.

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
| `--evidence-slots 41-60` | step 5 (deep evidence) only: its own browser range, e.g. 20 browsers = one chart company each; other steps keep `--slots` (default: same as `--slots`) |
| `--skip-facts` | skip step 3c's AI Mode queries (saved ownership / identity answers still apply) |
| `--no-pdf` | do not print the PDF (step 8b) |
| `--no-docx` | do not write the Word copy (step 8b) |
| `--dry-run` | print the plan, open no browser |
| `--fixed-axes file.json` / `--top-list` / `--chart-top` / `--reselect` | manual overrides (rarely needed) |

Every step is resumable: re-running the same command skips saved work.

PDF of a finished report (cover + key figures, no date, contents with page numbers,
each section on a new page, one company per page in Parameter Detail):
```bat
.venv\Scripts\python.exe scripts\export_report_pdf.py --market "Global Smart Ring Market" --country global
```
Writes `<slug>_report.pdf` next to the report. Page numbers on the contents
page need `pymupdf` (in `requirements.txt`); without it the contents prints unnumbered.
A back cover (e.g. "Thank you / Contact us") is appended when
`<market>/_pipeline/pdf_back_cover.pdf` exists (that market only) or
`config/pdf_back_cover.pdf` exists (every market); its old footer is removed
and every page gets one "Page X of Y" footer that counts it.
The Word copy (`<slug>_report.docx`, step 8b) also opens with a branded front
cover when `<market>/_pipeline/front_cover.pdf` or `config/front_cover.pdf`
exists; an "xxxxxx" title placeholder on it is filled with the market name.

### Many markets at once (one Chromium browser per market)
```bat
.venv\Scripts\python.exe scripts\run_markets_parallel.py --markets-file queries\my_markets.txt --workers 10 --keep 120
```
`queries\my_markets.txt`: one market per line, optional `| country`
(`Smart Ring Market | india`). Each market runs the full
`run_quadrant_pipeline.py` pinned to ONE browser slot
(`data/ai_mode_batch_<slot>`, Chromium, CAPTCHA Raptor loaded), so
`--workers 10` = 10 browsers = 10 markets in parallel; when one finishes, the
next market takes its slot. Slots `--slot-start 41` .. 50 (must stay ≤ 99).
`--stagger` spaces browser launches (default 20 s). Logs:
`logs/parallel/<market>_<country>.log`; summary `logs/parallel/summary.json`.
Extra flags after `--` go to every pipeline run. Don't run two launchers with
overlapping slot ranges. Ten browsers on one IP raise Google's block rate: if
many markets hit "unusual traffic", use fewer workers or a higher
`GOOGLE_AI_MODE_QUERY_DELAY`.

The run ends with a **VERIFY** block; every line must be `[PASS]`:
5 params on X and Y · Capability axis titles (X by player type) · no
inactive / acquired / review-excluded company listed (a brand that reads like a
different checked company does not count: "Liquify Digital Ltd" is not the
excluded "Liquify Ltd.") · no company whose owner or co-owner is also listed · no market-research
publisher named (competitors; list in `config/research_publishers.txt`, the
evidence prompts forbid citing them) · Top companies have
score+evidence+reasoning for all 10 parameters · report keeps N (with `--keep`) ·
chart has 20 · 5/5/5/5 · X/Y = mean of parameters · no hedge wording ·
Other Noticeable Player bubbles only (no numbers, no tooltip) · grouped by
quadrant, sorted by strength within each · no adjacent-segment company on the chart · supporting points: an
absence reads "Not available", shown only when a parameter has no real
finding, and then once; no citation leftovers (footnote markers like "[1.21]",
raw links in brackets); no employee-review site
(`config/employee_review_sites.txt`) and no modelled-estimate site
(`config/estimate_sites.txt`: RocketReach, ZoomInfo, Endole, D&B, GlobalDatabase, Crunchbase, …) cited; such bullets are also removed before step 5, so a parameter left empty is re-asked in the same run · every company
has an HQ · every X/Y ≥ 65 · estimated figures labelled "estimated … approximately", with basis
and confidence · chart fact-check complete for every chart company · research panel above
the chart (organisation types incl. manufacturers, designations) · market definition shown
is short (<= 100 words) with no internal file note · report wording is
"As per our findings", estimates read "... is ..." (no "Based on primary research" /
"can be estimated" left).

Evidence prompts also carry EVIDENCE RULES (`ai_mode_scorer.EVIDENCE_RULES`):
project status and date exactly as the source states; company-stated claims
written "The company reports …", "verified" only for independent sources;
partner technology credited to the partnership; employee reviews are not
customer feedback; how long a client's project ran is not the company's own
delivery time; current company name.

If a VERIFY line fails, fix the cause in the **generic** code and re-run.
Never patch a single market's output by hand or add a market-specific fix.

### Chart fact-check (step 8a, every run)
After the report is built, `scripts/factcheck_chart.py` asks AI Mode, per chart
company, its status, owner, HQ and scope (against the market brief or Step 0c),
then judges every specific supporting point correct / incorrect / unverified,
split over all `--slots` browsers, resumable (checked companies, and sentences
a review fix changed, are not re-asked). Findings: `_pipeline/factcheck/findings.json`
and `findings.md` (the review list). `vendor_intel.pipeline.factcheck` turns them
into `_pipeline/factcheck_review.json` (analyst-review schema), applied as an
automatic layer that `analyst_review.json` overrides. Because AI Mode cites
directory sites and can contradict itself, only these apply automatically:
liquidated / dissolved / in administration with a stated event → excluded (an
acquired company still trading stays); scope adjacent → off the chart, out →
excluded; an owner that passes `company_facts.owner_entry` and is not already
labelled; an HQ whose **country** differs; a claim judged incorrect → its
corrected sentence (house style applied) when the source is not a directory /
estimate / review / research-publisher site (`config/directory_sites.txt` and
the other lists), the edit is small (≥ 0.75 similar) and no other check of the
company backs the old figure; a claim that belongs to another company → removed.
When decisions change, the pipeline re-runs itself from saved work (refill,
evidence for new entrants, 8a for them; max 8 passes, `QUADRANT_FACTCHECK_MAX_PASSES`). A decision stays once
made, so a company moved off the chart does not come back. Review-file
`company` may be the legal name, any deduped variant or the brand
(`company_status.company_aliases`). Stand-alone: `scripts\factcheck_chart.py
--market "X" --country global --browsers 10`.

### Kept generic (do not reintroduce)
- Axes: `define_market_axes` gets the market, geography and `MARKET_SCOPE`
  only -- no sector catalog baseline (`config/quadrant_industry_criteria.yaml`
  is not used on the live path), no catalog fallback, a short answer is retried.
- `config/expand_market_gates.yaml` has one `"*"` profile; profiles are never
  picked by words in the market name. `role_split.py` has no market branches.
- Verify keeps a role that is the market's own player type BEFORE the channel
  drop list (a distribution market's distributors are the market); the
  contract-manufacturer filter skips markers that name the market itself.
- Seed files apply only on an exact market-slug match.
- Discovery does not score (`EXPAND_DISCOVERY_XY=0`, set by the orchestrator
  and split discovery): steps 2 and 4 derive the axes and score once.
- `scripts/parallel_topup.py --verify-only` verifies what stopped browsers
  already found (each company on one browser) and merges it.
- **One company per owner group, the stronger stays** (owner's decisions
  2026-10-09). Step 3c finds pairs where a company's owner is itself in the
  same list (`company_facts.listed_parent`: exact name without legal suffixes,
  or that company's brand) and records them (`auto_review.json` `listed_owner`);
  step 4a, once scores exist, keeps the **stronger** member of each group and
  leaves out the rest (`resolve_listed_groups`). Stronger = on the saved chart
  first, then the higher score (full evidence where both have it, else quick);
  tie or no score keeps the parent. So Redmap (Challenger) goes beside the
  Leader Basware, and the Leader AvidXchange stays beside its co-owner Corpay
  (long tail), which goes. The decision is saved
  (`_pipeline/listed_owner_decisions.json`) and reused while the group is
  unchanged. In a joint deal any listed co-owner counts
  (`company_facts.owner_names` splits "TPG and Corpay" on and / & / , / ; / "/";
  the whole name is tried first). Owners from the ownership answers, the
  analyst review and the fact-check; investment firms or groups not in the list
  do not count; partial names never match ("Visma" is not "Visma Aquila Oy").
  `keep` in the analyst review overrides it. `--update-report` decides on the
  existing report's chart and Overall. VERIFY checks the final report too ("No
  company whose owner is also listed", read from its "(acquired by / subsidiary of …)" labels).
- A chart refill keeps **every surviving chart company** and fills only the
  vacated slots (`refill_top_by_quadrant(keep_all=True)`): the composite step
  re-splits the chart 5 per quadrant by rank, so trimming a "full" quadrant
  would drop companies a reviewer already approved.
- **A file that several browsers write is updated under a lock**
  (`quadrant_pipeline.update_json_locked`: lock file, temp name per process, retry when Windows reports the
  file busy). The gap-fill step (`fill_missing_assessed_on.py`) writes every browser's fix into the same
  evidence files; unlocked, 11 browsers lost each other's fixes, left a damaged JSON ("Extra data") and
  crashed with PermissionError. Any new step where shards write one shared file must use it.
- `norm_name` joins dotted legal forms ("S.p.A.", "S.r.l.", "B.V.") before
  stripping suffixes, so "Acme S.r.l." and "Acme Srl" are one company.

## 5. Pipeline stages and where the code lives

Orchestrator: `scripts/run_quadrant_pipeline.py` (+ helpers in
`src/vendor_intel/pipeline/quadrant_pipeline.py`: dedupe, evidence gaps, ranking).

| # | Stage | Code |
|---|---|---|
| 1 | **Discovery** (only if the market has no verified companies): Step 0c market analysis → discovery rounds → verify → fill | `scripts/run_chatgpt_expand.py` → `pipeline/chatgpt_expand.py` |
| 1b | **Top-up** (`--keep`): discover a batch, verify only new companies, repeat | `scripts/discover_verify_rounds.py` |
| 2 | **Axes spec**: 5+5 market-specific parameters + definitions (LLM), fixed axis names → `_pipeline/axes_spec.json` | `quadrant/axis_define.py` (`define_market_axes`, `explain_market_parameters`) |
| 2c | **Report framing** (AI Mode, once per market, from the market definition) → `_pipeline/research_panel.json`: "Organisations We Surveyed" (5 organisation types, **manufacturers always one of them**) and "Designations We Spoke To" (5 job titles), shown directly above the chart; `report_definition` (the short 2-sentence market definition the report's Market Classification shows -- the long definition stays for discovery and the checks); `player_type_reason` (the line under "Provider Categories", in that player type's own language). Missing pieces are asked for on the next run; a market brief's own `report_definition` / `player_type_reason` override them; an internal file note never reaches the report | `scripts/research_panel.py` |
| 3 | **Dedupe**: one row per real company (same registrable domain or same name minus legal suffixes; union-find) | `quadrant_pipeline.dedupe_companies` |
| 3b | **Operating status**: AI Mode asks, 10 companies per query, split across every `--slots` browser (one answer file per browser, merged into `operating_status.json`), whether each company still operates today (active / acquired / defunct / renamed) → `_pipeline/operating_status.json`; every non-active company and every `exclude` in `_pipeline/analyst_review.json` is left out (`_pipeline/excluded_companies.json`). A pinned Top 20 that loses a company keeps the rest and refills that quadrant (`company_status.refill_top_by_quadrant`). No answer = kept (a failed query is not evidence of closure) | `scripts/check_operating_status.py`, `pipeline/company_status.py` |
| 3c | **Ownership + identity + scope** (AI Mode): 10 companies per query "acquired? by whom? trading under its own name? current name / legacy brand?" (`_pipeline/ownership.json`; unclear answers re-asked one by one), one-company identity checks for doubtful answers (`_pipeline/identity_check.json`), and a scope check, 10 per query: **core / adjacent / out** against the market definition and Step 0c's `core_scope` / `adjacent_segments` (`_pipeline/scope_check.json`). The product test: core only when the market's product IS the company's main product; offered as a module or add-on inside a different main product (another software category, a services / leasing / card / security business, a resold data feed, a reseller of another vendor's platform) = adjacent. Decisions go to `_pipeline/auto_review.json`: bought-and-absorbed companies, old names of rebranded companies listed twice, companies that do not exist and `out` companies are left out; **adjacent-segment companies stay in Other Noticeable Players but never go on the chart** (like-for-like quadrant; their slots refill from core companies). A company bought but still trading gets **"Name (acquired by Owner)"** for a deal under 3 years old, else **"Name (subsidiary of Owner)"**; a retired/divested brand is shown under its current name ("SLB (WesternGeco legacy)"). The analyst review always wins | `scripts/check_company_facts.py`, `pipeline/company_facts.py` |
| 4 | **Quick X/Y scores** for every verified company: 2 AI Mode queries each, a Product Capability scorecard (all 5 X parameters, one line each) and a Business Capability scorecard (all 5 Y). X/Y = parameter means, Overall = (X+Y)/2. A parameter the answer skips is re-asked alone. Feeds long-tail bubbles | `scripts/score_overall_only.py` (sharded per slot); `ai_mode_scorer.build_axis_scorecard_query` / `parse_axis_scorecard` |
| 4b | **Top 20 selection**: best 5 by Overall from EACH quadrant, split at the pool's median X and Y; a short quadrant's slots go to the best remaining. A market brief may set `"chart_selection": "top_overall"`: the 20 strongest by Overall instead (refills too), still placed 5 per quadrant by rank in step 6 -- for a large market whose leading brands all score high (owner 2026-10-20, India Spices). **Small market:** when fewer core companies than chart slots exist, every core company is charted and the strongest adjacent companies (by quick score) fill the rest (`_pipeline/chart_fill_adjacent.json`; VERIFY accepts exactly these) | `quadrant_pipeline.select_top_by_quadrant` |
| 5 | **Deep evidence** for the Top 20 only: per-parameter score + evidence + "why" reasoning, gap-fill rounds. Supporting points: **at most 5 per parameter** (`ai_mode_scorer.MAX_SUPPORTING_POINTS`, owner 2026-10-19), shared out over the parts a parameter joins ("Revenue & Growth" is asked for 2 on revenue, 2 on growth, 1 more; `ai_mode_scorer.parameter_parts` / `evidence_lines`); step 7b trims any parameter above 5 taking points in turn from each part, so no part loses its share (`company_facts.cap_points`) | `prescore_verified.py`, `fill_missing_parameters.py`, `fill_missing_assessed_on.py` |
| 5b | **Part gap-fill**: a part of a multi-part parameter that no supporting point covers (revenue facts, nothing on growth) is asked about alone and its findings are added to that parameter (score and "why" unchanged); a parameter whose only supporting point is "Not available" is asked about once more as a whole (company site, filings and approvals, annual reports, trade news); each part / parameter asked once per market (`_pipeline/part_fill_asked.json`) | `scripts/fill_missing_parts.py`, `quadrant_pipeline.part_gaps` |
| 6 | **Composite**: X/Y/Overall, cohort band 65–100, 5 per quadrant (split on the unrounded banded X/Y, so rounding never makes a false tie at the cut); the long tail is banded together with the chart companies' quick scores (never across the tail alone, which lifted a weak tail company above the chart) | `scripts/seed_from_full_evidence.py` |
| 7 | **Tone**: research-team voice ("We verified …", never "I"), no hedges; every gap written in the house sentence "Based on primary research, the company has not disclosed <what>." (never "not publicly reported / disclosed", "could not be found", "Desk research could not confirm"); citation leftovers removed | `scripts/rewrite_assessed_on_tone.py` → `scripts/primary_research_wording.to_primary` |
| 7c | **Gap estimates** (AI Mode): every "Based on primary research, the company has not disclosed X" sentence in a chart company's "Assessed on" text is REPLACED by the analyst's estimate, written in words (owner's decisions 2026-10-08/09): "Based on primary research, the company's data extraction accuracy rates can be estimated as exceptional and industry leading, based on its 10 trillion dollar community dataset." The estimate itself is never a number or range ("high", "growing steadily", "broad across the major ERP platforms"); figures appear only in the "based on" part; a second estimate for the same gap follows without the lead-in; with no estimate the gap sentence stays; a figure the company itself reports is still quoted. Per company, split over every `--slots` browser: (1) the company's own published facts (JSON, asked once), (2) a worked estimate for up to 5 gaps in plain language ending with one summary line per gap (`estimates.parse_worded`) -- a strict JSON verdict per gap made AI Mode answer "insufficient" without researching, so the rules live in `judge_worded`, not the prompt; 'unknown / unverified / unavailable / proprietary' answers are rejected and asked again (max 2 asks). Always: no figure in the estimate ("B2B", "S/4HANA" are fine), a basis is required, no research firm or data site (`config/research_publishers.txt`, `estimate_sites.txt`, `directory_sites.txt`) in basis or source, numbers AI Mode spells out in the basis are turned back into figures (`words_to_figures`), for a gap about third-party proof the underlying performance is estimated. `QUADRANT_NUMERIC_ESTIMATES=1` brings back the numeric ranges ("... can be estimated at approximately 3-6%, derived from ...", the owner's first version; default off). Only the "Assessed on" text changes -- supporting points, scores, names and the chart do not. Metadata per parameter: `estimates: [{metric, value_type, estimated_value, confidence, basis, source_type}]`. Answers `_pipeline/estimates/answers.json` (resumable), review list `estimates.md`; an analyst `corrections` entry can fix or remove one (7c runs before 7b). The tone step never rewrites an estimate sentence (`primary_research_wording.to_primary` skips them), so a re-run or fact-check pass cannot turn one back into a gap | `scripts/estimate_gaps.py`, `pipeline/estimates.py` |
| 7b | **Analyst review**: `_pipeline/analyst_review.json` `corrections` (exact find/replace in one company's evidence), `hq` (confirmed headquarters) and `ownership` (merged with the automatic owners) applied; `_pipeline/wording_review.json` rewrites; then the supporting-point tidy: absence-only bullets become "Not available", dropped beside a real finding, never repeated | `company_status.apply_corrections`, `apply_hq_corrections`, `apply_ownership_corrections`, `company_facts.tidy_evidence` |
| 8 | **Report**: HTML/JSON/CSV. **House wording** (owner 2026-10-15) is applied here, once, to everything the report writes: "Based on primary research, the company's X can be estimated as Y, based on Z" → "As per our findings, the company's X is Y, based on Z"; "Based on primary research, the company has not disclosed X" → "As per our findings, ..."; "... can be estimated at approximately" → "... is approximately"; "according to primary research" → "as per our findings". The pipeline's own steps keep the old phrases (tone, estimates and fact-check match on them), so never change those phrases upstream; `house_wording.to_legacy` maps a report sentence back for a correction (`apply_corrections`). `<slug>_report.html` is the interactive design (quadrant.json embedded, rendered in the browser; template `quadrant/templates/quadrant_viewer.html`); the static page is kept as `<slug>_report_classic.html` for VERIFY and maintenance scripts | `scripts/build_report_from_composite.py` → `quadrant/html_report.py`, then `quadrant/viewer.py` |
| 8a | **Chart fact-check** (every run, before 8b): status / owner / HQ / scope + every specific supporting point of each chart company in AI Mode; safe decisions applied as `_pipeline/factcheck_review.json`, then a re-run from saved work when they change (see "Chart fact-check") | `scripts/factcheck_chart.py`, `pipeline/factcheck.py` |
| 8b | **PDF**: cover with key figures, contents with page numbers, each section on a new page, one company per page in Parameter Detail → `<slug>_report.pdf`; then the **Word copy** `<slug>_report.docx`, its text read from the same printed page (so it matches the PDF), chart as an image, contents refreshed by Word when installed | `scripts/export_report_pdf.py`, `scripts/export_report_docx.py` |
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
STATUS RULE; "when unsure, DROP"; JSON `name, in_market, builds_or_owns, role,
fits_criteria, confidence, reason, operating_status, status_note`).
`verify_should_keep()` keeps a company only if in market + builds/owns +
confidence ≥ 70 + role not a channel/media role + role matches the required
type (any of the four player types or the market's own categories), and
`operating_status` must be `active` (fail closed: bankrupt, liquidated,
absorbed by an acquirer or renamed out of the market = DROP). Unparseable or
skipped answers = DROP.

### Analyst review file (per market, data not code)
When a reviewer finds a factual error in a finished report, record it in
`<market>/_pipeline/analyst_review.json` and re-run the same command (cached,
no new queries unless the chart changes):
```json
{"exclude": [{"company": "...", "reason": "...", "source": "..."}],
 "corrections": [{"company": "...", "find": "exact text", "replace": "...", "reason": "...", "source": "..."}],
 "hq": [{"company": "...", "headquarters": "City, Country", "source": "..."}],
 "ownership": [{"company": "...", "owner": "...", "year": "...", "reason": "...", "source": "..."}],
 "keep": [{"company": "...", "reason": "..."}],
 "scope": [{"company": "...", "scope": "core|adjacent|out", "reason": "..."}],
 "display": [{"company": "...", "current_name": "...", "source": "..."}]}
```
A market brief (`_pipeline/market_brief.json`) may set `"adjacent_policy": "exclude"`: then a
company the scope check calls adjacent is left out of the report entirely instead of going to
Other Noticeable Players -- for a client report that covers ONE player type only (Medical
Films = medical-grade polymer suppliers, not the film makers that buy them).
`scope` overrides the automatic scope check; `display` shows a company under
the name it trades as today (`"current_name": ""` clears it).
`keep` undoes an automatic exclusion from step 3b (status answer) or 3c; an `ownership` entry
replaces the automatic label for that company (`"owner": ""` removes it).
`ownership` sets the confirmed owner on the company's verified rows; the
Company column (HTML, PDF, JSON `company`, CSV) then reads
"Name (acquired by Owner)". The brand and every internal lookup keep the plain
name, and chart bubbles show the brand only.
This is the only sanctioned way to fix one market's facts: it lives with that
market's output, keeps an audit trail, and survives re-runs. Never edit the
report HTML/JSON by hand.

### Country runs (`--country india`, `germany`, …)
Any country other than `global` is a single-country run
(`geo_rotation.is_single_country`). Every discovery round asks for companies
**HEADQUARTERED IN <country>** (a foreign company's local office, plant,
subsidiary or distributor does not qualify). When the broad rounds run dry it
sweeps states/regions (only countries with a list in `geo_rotation.STATES_BY_COUNTRY`:
India and the United Kingdom), and never escalates to other regions or countries.
`GEO_AREA_SHARD=k/N` gives each of N parallel discovery browsers its own share
of those areas, so a 10-browser top-up sweeps different cities instead of
repeating itself.
Verification adds an **HQ RULE** and an `hq_in_country` field; a company is
kept only if the answer is `true` (fail closed).
Step 3c then asks AI Mode (10 companies per query, all browsers) where each
company's OWN head office is (`_pipeline/hq_check.json`): a company run from
abroad that only has a branch or office address in the country (e.g. a Dublin
company with a UK office) is left out; a company headquartered in the country
but owned by a foreign group stays (no answer = kept). Name the market without
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
| Quota page ("reached the request limit for AI responses") | **Automatic:** profile archived (`data/ai_mode_batch_<slot>_chromium_quota_<time>`), browser reopened on a fresh profile, query retried; up to `GOOGLE_AI_MODE_MAX_RESETS` (3) per query with a growing wait (`GOOGLE_AI_MODE_QUOTA_COOLOFF` × 1, 2, 3). Then the query fails and the step's own retry/gap-fill picks it up later |
| "Something went wrong and the content wasn't generated" / "…an AI response wasn't generated" | **Automatic:** matched anywhere on the page (the echoed prompt makes it long); 1st and 2nd time in a query clear cookies + relaunch the browser, 3rd time full profile reset + fresh browser (`…_noanswer_<time>`); the query is re-issued each time without costing a retry |
| "Verifying your request … Continue" page | **Automatic:** Google's interstitial when many browsers share one IP (not a reCAPTCHA, so Raptor does nothing). The session is treated as flagged: 1st and 2nd time in a query, cookies are cleared and the browser relaunched; 3rd time, a full profile reset (old profile archived as `…_verify_<time>`). The query is re-issued each time without costing a retry. Frequent = too many browsers on one IP: raise `GOOGLE_AI_MODE_QUERY_DELAY` or use fewer slots |
| Browser crashed / closed | **Automatic:** browser reopened on the same profile, query retried |
| Unusual-traffic `/sorry/` block | Google rate block (not solvable). Raise `GOOGLE_AI_MODE_QUERY_DELAY`, use fewer `--slots`/workers, wait. 5+ CAPTCHAs in a run also trigger a profile reset |
| `data/` growing large | every reset archives the old profile folder (renamed, not deleted). Old `data/ai_mode_batch_*_quota_*`, `*_captchas_*`, `*_noanswer_*`, `*_reset_*` folders can be deleted when no run is active |
| `JSONDecodeError: Extra data` / `PermissionError ... being used by another process` on a `param_detail_prescored*.json` | Two browsers wrote the same evidence file without the lock (fixed: `update_json_locked`). Stop the run, keep the first valid JSON document of the damaged file (`json.JSONDecoder().raw_decode`), re-run: the gap-fill round re-asks anything lost |
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
