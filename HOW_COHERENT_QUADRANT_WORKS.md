# How the Coherent Quadrant works

This guide explains, in plain terms, how one market report is produced: from a market name and a
definition to a finished Coherent Quadrant report (HTML, PDF, Word). It covers the **ChatGPT-expand
pipeline**, the path every market runs today.

For the full technical reference (every flag, file and setting) see `CLAUDE.md` and
`PIPELINE_CHATGPT_EXPAND.md`.

---

## 1. What you get

For each market, in `output/chatgpt_expand/<market>_<country>/`:

| File | What it is |
|---|---|
| `<slug>_report.html` | The interactive report: the Quadrant chart, scores, evidence, Other Noticeable Players |
| `<slug>_report.pdf` | Printable copy: cover, contents, one company per page |
| `<slug>_report.docx` | Word copy of the same pages |
| `<slug>_companies.csv` | The company list (opens in Excel) |
| `<slug>_quadrant.json` | Every score and piece of evidence, as data |
| `_pipeline/` | The run's working files (briefs, checks, reviews, logs) |

The report has:

* **The Quadrant chart**: 20 companies, 5 in each quadrant.
  * **X axis**: Product Capability, Technology Capability or Service Capability, depending on what the companies sell.
  * **Y axis**: Business Capability.
  * Each axis is the average of **5 parameters** written for that market.
* **Quadrants**:
  * **Leaders**: strong on both axes.
  * **Challengers**: strong Business, weaker Product.
  * **Trailblazers**: strong Product, weaker Business.
  * **Emerging Players**: weaker on both.
* **Parameter detail**: for each chart company and parameter, a score, a reasoning line, and up to 5 supporting points with sources.
* **Other Noticeable Players**: every other company that qualified.
  * Strength is shown as bubbles only.
  * Rows are grouped by quadrant, strongest first.
* **Research panel**, Market Classification and parameter definitions.

---

## 2. The idea in one paragraph

Google **AI Mode** (driven in a real Chromium browser) does all the research: it finds companies, checks
them, scores them and finds evidence. **DeepSeek** (an LLM) is used only to write the 5 + 5 parameters and
their definitions. Every market runs through the **same code**; what makes a market different is its
**market brief** (definition, who counts, exclusions), never market-specific code.

---

## 3. Before the run: the market brief

Every market starts from `_pipeline/market_brief.json`, written from the client's brief and sample report:

| Field | Meaning |
|---|---|
| `market_definition` | The client's definition, word for word, plus the segmentation |
| `player_type` | Who is compared: **Manufacturer**, **Brand / Marketer**, **Solution Provider** or **Service Provider** |
| `scope` | The rule every company is checked against: who counts, and an explicit **NOT in this market** list (max 900 characters, the checker reads no more) |
| `adjacent_segments` | The client's exclusions, word for word |
| `adjacent_policy: exclude` | An excluded company is removed from the whole report, not moved to the long tail |
| `chart_selection: top_overall` | The chart is the 20 strongest companies by Overall score |
| `focus_areas` | Countries searched first |

**Seeds**: the companies named in the sample report / client list are added as starting candidates. They are
still verified like everyone else.

Geography:
* **Global run** (`--country global`): any headquarters, unless the scope says otherwise
  (e.g. "headquartered in the US, Canada or Europe").
* **Country run** (`--country india`): companies headquartered in that country; a foreign group's local
  branch or subsidiary is dropped at verification. Discovery goes state by state when the broad search runs dry.

---

## 4. The pipeline, step by step

```
Brief + seeds
   │
1  Discovery ── AI Mode finds companies, 10 per round, region by region
1b Verification ── each candidate checked against the scope (keep / drop)
   │           (discover → verify → discover more … until the target or the market runs dry)
2  Axes ── DeepSeek writes 5 X + 5 Y parameters and definitions
2c Research panel ── organisations surveyed, designations, short definition
3  Dedupe ── one row per real company
3b Operating status ── still trading? acquired? closed?
3c Ownership, identity, scope, HQ ── owner, real name, core / adjacent / out, head office
4  Quick scores ── every company scored on all 10 parameters
4b Top 20 ── the chart companies
5  Deep evidence ── for the 20: score + reasoning + up to 5 supporting points per parameter
5b Gap-fill ── missing parameter parts asked again
6  Composite ── X / Y / Overall, 5 per quadrant
7  Tone ── research-team voice, no hedges
7c Estimates ── every undisclosed figure gets a worded estimate
7b Analyst review ── manual corrections, HQs, owners; supporting-point tidy
8  Report ── HTML / JSON / CSV
8a Fact-check ── every chart company and supporting point checked again
8b PDF + Word
9  VERIFY ── 24 checks, all must pass
```

### Step 1: Discovery

AI Mode is asked for **10 more companies per round** that fit the scope. Every prompt includes:

* the market and the scope text;
* **who qualifies** (the player type);
* **strictly exclude**: consultancies, distributors, contract manufacturers, suppliers, non-selling parents;
* a **do-not-repeat list** of names already found.

When a round finds nothing new, discovery switches from the broad search to region by region, then country
by country (or state by state for a country run). It never invents companies: when the market is exhausted
it stops.

Large runs use **many browsers in parallel** (`--browsers 10`/`20`), each searching its own share of
regions, then merging (passes of up to 50 minutes).

### Step 1b: Verification

Each candidate is checked, 12 at a time, against the scope. A company is kept only if:

* it operates in this market;
* it builds, owns or delivers the product or service itself;
* confidence is 70 or more;
* its role matches the player type;
* it is still active.

Anything unclear is dropped.

The **cap** (`--discover-to`, `--keep`) controls how many are gathered and kept:

* **`--keep 120`**: the report keeps the best 120 after all checks.
* **`--keep 1000`**: keep everyone.

### Step 2: Axes (the only LLM step)

DeepSeek writes **5 Product/Technology/Service parameters** and **5 Business parameters** for this
market, each with a definition. Example: *"U.S. Market Share and Revenue"*, *"Regulatory Compliance and
Quality Systems"*.

### Step 3–3c: Cleaning the list

* **Dedupe**: the same company under several names or websites becomes one row.
* **Status**: companies that closed, were absorbed, or left the market are removed. An event must be stated.
* **Ownership**: the owner is recorded and shown as "Name (acquired by / subsidiary of Owner)".
* **Scope check** against the definition:
  * **core**: the market's product is the company's own product line;
  * **adjacent** or **out**: removed.
* **HQ**: every company needs a "City, Country"; for country runs the head office must be in that country.
* **One company per parent group**: when two listed companies share an owner, only the stronger stays.

### Step 4–4b: Scoring and the chart

* Every company gets a **quick scorecard**: two AI Mode queries rate all 10 parameters.
* **X** = the mean of the 5 X scores, **Y** = the mean of the 5 Y scores, **Overall** = (X + Y) / 2.
* The **top 20 by Overall** go on the chart.

### Step 5–5b: Deep evidence for the 20

For each chart company and each parameter, AI Mode gives:

* a **score**;
* a **reasoning line** ("why");
* up to **5 supporting points**, each with its source.

Evidence rules:

* **Points are shared across parameter parts**: "Revenue & Growth" gets points on revenue *and* on growth.
* **Company claims** are written as "The company reports …".
* **Never cited**: market-research firms, employee-review sites or modelled-data sites.

Parts with no point are asked again. A parameter that has only "Not available" gets one more dedicated search.

### Step 6: Composite

Scores are spread across a **65–100 band** within the market. The 20 are placed **5 per quadrant**.

### Step 7–7c: Wording and estimates

* **Tone**: research-team voice ("We verified …"), no hedging.
* **Estimates**: every *"has not disclosed X"* becomes a worded estimate with its basis. For example:
  > *As per our findings, the company's U.S. sales revenue and market share is minimal due to recent market
  > entry, based on its final FDA approval in September 2026.*

  The estimate is in words; figures appear only in the basis.

### Step 7b: Analyst review (the only manual lever)

`_pipeline/analyst_review.json` holds human decisions for that market:

| Key | Use |
|---|---|
| `exclude` | Remove a company (duplicate, wrong country, out of scope…) with a reason and source |
| `keep` | Keep a company an automatic check removed (e.g. named in the client's sample) |
| `scope` | Force core / adjacent / out |
| `corrections` | Exact find / replace in one company's evidence |
| `hq`, `ownership`, `display` | Confirmed head office, owner label, chart label |

It always wins over the automatic checks and survives re-runs. **Reports are never edited by hand.**

### Step 8–8b: Report, fact-check, PDF

* **Report**: the HTML / JSON / CSV are built. House wording such as "As per our findings" is applied here.
* **Fact-check**: AI Mode re-checks every chart company (status, owner, HQ, scope) and every specific
  supporting point. Wrong points are corrected; companies that turn out to be out of scope leave the chart
  and are replaced.
  * Example: veterinary-only 503B facilities.
* **Re-run from saved work**: when the fact-check changes anything, the pipeline re-runs itself from saved
  work, with no new searches except for new chart companies.
* **PDF and Word**: the PDF and Word copies are printed from the same pages.

### Step 9: VERIFY

The run ends with **24 checks**; every one must read `[PASS]`. Among them:

* 5 + 5 parameters, correct axis titles;
* 20 on the chart, split 5 / 5 / 5 / 5, every X and Y of 65 or more;
* no inactive or excluded company listed; no company listed beside its own owner;
* every chart company has a score, evidence and reasoning for all 10 parameters;
* no hedge wording, no research publisher or third-party source named;
* every company has an HQ;
* Other Noticeable Players shows bubbles only, grouped by quadrant and sorted by strength within each;
* the fact-check is complete.

If a check fails, the cause is fixed in the generic code (or the analyst review) and the market is re-run.

---

## 5. Running a market

One market (resumable; re-running skips saved work):

```bat
.venv\Scripts\python.exe scripts\run_quadrant_pipeline.py --market "Global Smart Ring Market" --country global --keep 120
```

Large market with many browsers (discovery in parallel passes, then the pipeline):

```bat
.venv\Scripts\python.exe logs\run_market.py "U.S. 503B Compounding Pharmacies Market" --country global --keep 150 --discover-to 200 --browsers 10 --slot-start 41 --global-focus
```

Many markets at once, one browser each:

```bat
.venv\Scripts\python.exe scripts\run_markets_parallel.py --markets-file queries\my_markets.txt --workers 10 --keep 120
```

Unattended runs: `profood\watchdog.py` checks every 10 minutes. Any market that crashed, or made no real
progress for 45 minutes, is restarted from its saved work in a **new browser with fresh cookies**. It
stops once every market has passed VERIFY.

```bat
.venv\Scripts\python.exe profood\watchdog.py profood\fmt_india_markets.json --every 10 --stall 45
```

**Stopping safely**: stop the processes at any time; every step is saved. **Resuming**: run the same command
again (or the watchdog).

---

## 6. How the browsers stay healthy

* **CAPTCHAs**: the bundled CAPTCHA Raptor extension solves them in every browser.
* **Quota pages, "Verifying your request" pages, empty answers**: the browser clears its cookies and relaunches; if that keeps happening, its profile is archived and a fresh one opens.
* **"Unusual traffic" blocks**: these cannot be solved; the fix is fewer browsers at once or slower queries (`GOOGLE_AI_MODE_QUERY_DELAY`).
* **How many browsers**: about 10–20 at once is reliable. At 25 or more on one connection, Google starts refusing answers; the watchdog restarts what stops.

---

## 7. House rules (owner's decisions)

* **No market-specific code**: market knowledge comes from the brief, AI Mode or the analyst review.
* **Exclusions are absolute**: an excluded company type never appears, not even in the long tail.
* **One company per parent group**: the stronger stays.
* **Up to 5 supporting points per parameter**, shared across the parameter's parts.
* **"Not available"** is shown only when nothing real was found; the reasoning still carries a worded estimate.
* **Other Noticeable Players**: bubbles only, with no numbers or tooltips, grouped by quadrant, strongest first.
* **Report wording**: "As per our findings …"; no "I", no "could not verify".
