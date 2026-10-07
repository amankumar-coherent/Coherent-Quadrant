# Handover: what was done with the owner, and how they work

For Claude Code (and the developer) continuing this project on another machine.
`CLAUDE.md` holds the setup and the hard rules; `PIPELINE_CHATGPT_EXPAND.md` holds
the full pipeline reference. This file holds what those do not: the owner's
preferences and working style, the history of the work up to 2026-10-07, the
state of each market, and the lessons learned. Read it once at the start.

---

## 1. Who the owner is and how they work

- They build **Coherent Quadrant** market reports, a market-research firm's
  client deliverable: an interactive HTML report, plus PDF, Word, JSON and CSV
  copies. Each report has a Top 20 chart (5 per quadrant) and an "Other
  Noticeable Player" long tail.
- They write short messages, often with typos. The common ones:
  - "How many done?" / "At what step now?": report progress in a few lines.
    Give counts, the current step, what is next and any blocker.
  - "Resume": **continue from the last saved step, never restart.** Every
    step is checkpointed, so re-running the same command resumes. Once they
    rejected a command because it looked like a restart ("Not restart
    resume"); say that it resumes.
  - "Stop all the process and save": kill the run. Everything is saved per
    step, so a later resume continues.
  - "Reset browser / cookies / profile": close every Chromium first, archive
    the profiles (rename `data/ai_mode_batch_<slot>*` into
    `data/_archived_profiles_<time>/`) and start on fresh profiles.
- **Launch runs from PowerShell, not cmd.** Use a `.ps1` started with WMI so
  the run survives the Claude/VS Code session ending:
  ```powershell
  Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\...\logs\run_x.ps1"';
    CurrentDirectory = 'C:\...\Coherent-Quadrant' }
  ```
  In the `.ps1`, pipe Python output with `Out-File -Encoding utf8`. A bare
  `*>>` writes UTF-16 and garbles the log.
- **Browser count:** they usually want **10 browsers** (slots 41–50), but
  switch between 10, 5 and 2 when Google blocks. Use the number they ask for.
  When many browsers hit "Verifying your request" or CAPTCHAs, suggest fewer
  browsers or a higher delay. They sometimes change their IP (VPN) when blocked.
- **Pacing:** `.env` has `GOOGLE_AI_MODE_QUERY_DELAY=20`. They asked to "remove
  the 20s pacing", so the run scripts override it to `10`.
- **AI Mode for research, always.** When they asked for a fact-check they
  rejected web-search sub-agents with "Use google ai mode". Research
  (discovery, verification, facts, evidence) goes through the pipeline's AI
  Mode browsers; the DeepSeek API is only for the X/Y parameters.
- **Generic code only.** "Nothing hardcoded for one market. If I run 1000
  markets, every step must work." One market's facts go only into that
  market's `_pipeline/analyst_review.json` (or `market_brief.json`).
- **Mandatory checks, not optional ones.** "Implement fact check in my
  pipeline, don't do optional." Build checks into the pipeline and VERIFY.
- They want reports copied into Desktop folders when a batch is done (see §4).

## 2. Standing rules for report content (from the owner, all markets)

These came from the owner's corrections. They are enforced in code and VERIFY;
keep them.

1. **Research-firm voice.** No AI / LLM / AI Mode / crawling / scraping /
   search-query / tool wording anywhere in a report (methodology included).
   "We verified …" (team voice) is wanted; singular "I / my" is wrong.
2. **Gap wording.** Every missing fact reads exactly: *"Based on primary
   research, the company has not disclosed <what>."* Never "not publicly
   reported / disclosed / available", "could not be found in public records",
   "Desk research could not confirm", "remains undisclosed", "no specific
   evidence was found". Score reasoning states the basis first, then the gap
   once. No score numbers or band/tier jargon in the text, and never guess why
   information is missing ("kept confidential").
3. **"Not available".** A supporting-point bullet that only says nothing was
   found reads exactly "Not available". It is shown only when a parameter has
   no real finding, and then once.
4. **No competitor research firms named** (MarketsandMarkets, Fortune Business
   Insights, Technavio, Mordor, IMARC, Grand View, Tracxn, PitchBook, CB
   Insights, …). The list is `config/research_publishers.txt`. Keep the
   finding with neutral wording ("an industry market report").
5. **No company-data / estimate / employee-review / directory sites as
   sources**: RocketReach, ZoomInfo, Crunchbase, Tracxn, D&B, Glassdoor,
   SourceForge, Capterra, G2, … (`config/estimate_sites.txt`,
   `employee_review_sites.txt`, `directory_sites.txt`).
6. **Only companies operating today.** Bankrupt, liquidated, absorbed or
   renamed-out-of-market companies are removed. An acquired company that still
   trades stays, labelled "Name (acquired by Owner)" for a deal under 3 years
   old, else "Name (subsidiary of Owner)".
7. **Strict main-product scope.** A company is on the chart only when the
   market's product is its main product. If the product is a module of a
   different main product, the company is "adjacent": it stays in Other
   Noticeable Players, off the chart. The market brief can widen this (AP
   Automation counts ERP / P2P / S2P suite modules as core).
8. **Axes:** Y = Business Capability. X = Service / Technology / Product
   Capability by player type. Exactly 5 + 5 parameters from the LLM per market.
9. **Other Noticeable Player:** filled bubbles only. No number, no label, no
   tooltip. Sorted by strength.
10. **"Verified" only for independent sources.** A company's own claim reads
    "The company reports …". "Verified self-reported" is a contradiction.
11. IndiaMART-sourced claims read "According to primary research, …" with no
    IndiaMART name in the text.
12. After any chart change, **every new chart company gets the full check**:
    scope, status / owner fact-check and the wording audit. This is now
    automatic: step 8a, see the pipeline doc.
13. Never hand-edit a report's HTML/JSON. Fix the generic code or the
    market's review file, then re-run (cached).

These rules were also saved as Claude memories on the old machine. Memories do
**not** travel with the repo, which is why they are written out here.

## 3. Timeline of the work (until 2026-10-07)

### 3.1 UK Connected Fleet Mobility Solutions Market (United Kingdom)
- Fact-checked the chart companies, and ran deep searches to replace "Not
  available" evidence.
- Applied the Marine Seismic audit-workbook error types (wrong status, wrong
  owner, unsupported specifics, HQ) to the UK report.
- Introduced the strict main-product scope test, so adjacent companies stay
  off the chart.
- Banned third-party data sites (Tracxn etc.) as sources.
- The owner had to point out 175 "not publicly reported" lines. That led to
  the house gap sentence and `scripts/primary_research_wording.py`.
- One-off scripts from this phase are in `logs/uk_fleet_*.py` and
  `logs/audit_uk_report.py` (read-only audit of a finished report).

### 3.2 Batch of 33 markets: 13 drone (India) + 20 fire
- Re-run with every current check: active status, acquired logic, scope and
  wording ("do same as UK").
- 17 markets were excluded on purpose and were not run:
  - Drone: UAV Systems, Drone Mapping, Navigation, Composites, Components,
    Communications, Batteries, Cloud Platforms, Inspection, Surveillance,
    Testing, Training.
  - Fire: Fire Safety Training, Smart Fire Safety, Fire AI & Robotics, Fire
    Drones & GIS, Fire Safety Testing.
- Small markets (fewer than 20 core companies): the owner chose **"fill with
  adjacent now"**. The strongest adjacent companies fill the chart, recorded
  in `_pipeline/chart_fill_adjacent.json`, and VERIFY accepts exactly those.
- All 33 passed VERIFY. Reports were copied to the Desktop folders
  `C:\Users\aman.kumar\Desktop\Drone Market Quadrant` and `...\Fire Ecosystem
  Quadrant`; the older versions were moved into `_old_reports_2026-10-07`
  subfolders there.
- Helpers: `queries/drone_fire_33.txt`, `queries/resume_remaining.txt`,
  `logs/rerun_markets.py`, `logs/resume_drone_fire.cmd`.

### 3.3 Accounts Payable Automation Market (global), the latest market
- **Client brief** (definition and taxonomy) saved as
  `output/chatgpt_expand/accounts_payable_automation_market_global/_pipeline/market_brief.json`:
  - Software that automates the supplier invoice-to-payment lifecycle.
  - Standalone AP platforms and AP modules in ERP / P2P / S2P /
    spend-management suites are **core**.
  - **AP Services (BPO / outsourcing) are excluded.**
- Owner decisions:
  - Global market, 250 companies.
  - ERP modules are eligible for the chart.
  - Remove 12 flagged companies: Circula, Semine, four panels, SAGES
    Informatique, Expensya, Pro Archives Systèmes, Receipt Bank, Procurwave,
    Digithera, Groupe T2i, Pagero, VV Finly.
  - SAP was moved to core.
- Discovery: a 10-browser broad top-up, then a country-by-country top-up,
  reaching **407 verified companies** (after dedupe).
- A targeted ERP/suite-vendor discovery found 246 more candidates. The owner
  then said **"leave discovery, keep only the 407"**, so those were dropped.
  Oracle, Microsoft, Workday, Sage Intacct and NetSuite are therefore **not in
  the report**. A known gap; tell the owner if they ask.
- Result:
  - 250 companies kept (20 chart + 230 long tail).
  - 27 left out at 3b (inactive or flagged) and 19 at 3c; about 225 adjacent.
  - X = Technology Capability (Solution Provider market).
- Wording audit: citation chips and stray "note" labels removed, "verified
  self-reported" fixed, the garbled Klak sentence corrected. No competitor
  firm and no banned site anywhere.
- AI Mode fact-check of all 20 chart companies (280 claims; scope all core):
  - 18 corrections plus 3 owner labels (Basware → Accel-KKR, Tungsten →
    Clearlake & TA, Medius → Marlin) recorded in `analyst_review.json`.
  - The wrong Emburse ← Certify label was removed.
  - Then the automatic step 8a applied 4 more corrections.
- Solution Provider re-check of all 250 companies through AI Mode
  (`scripts/recheck_player_type.py`): 245 passed. The owner removed the 5
  that failed: SL Information Solutions (reseller / implementer), Aruba (IT
  hosting), NetBaron (absorbed into Confirma), Paymerang (bought by Corpay),
  Abby (freelancer invoicing). The owner said **"don't add any more
  companies, leave them on 245"**, so the report keeps 245 with no refill
  (`KEEP = 245` in `logs/run_ap_automation.py`; the 5 are `exclude` entries
  in `analyst_review.json`).
- PDF and Word have the same branded front cover (market name filled into
  the "xxxxxx" placeholder) and "Thank you / Contact us" back cover as the UK
  Fleet report: copied from the UK market's `_pipeline/front_cover.pdf` and
  `pdf_back_cover.pdf` into AP's `_pipeline/`. To give every market these
  covers, put the two files in `config/` instead.
- **Final state: 245 companies (20 chart + 225 long tail), VERIFY 18/18 PASS.**
  HTML, PDF, Word, JSON and CSV are in that folder.

| Quadrant | Top 20 |
|---|---|
| Leaders | Coupa (subsidiary of Thoma Bravo), Basware (subsidiary of Accel-KKR), Medius (subsidiary of Marlin Equity Partners), Tungsten Automation (subsidiary of Clearlake Capital and TA Associates), AvidXchange (acquired by TPG and Corpay) |
| Trailblazers | Tipalti, cisbox (acquired by Main Capital Partners), Candis, Zone & Co, Dooap |
| Challengers | Sansan (Bill One), Redmap (acquired by Basware), Alii, Synertrade, Supplycart |
| Emerging Players | Traild Software, Payflows, Peakflo, Digipharmacie (acquired by Equasens), Klak |

- To re-run AP (cached, about 1 minute; step 8a only checks new text): start
  `logs\run_ap_automation.ps1`. The log goes to `logs/run_ap_automation.log`
  and `logs/parallel/accounts_payable_automation_market_global.log`.
- AP-only launchers in `logs/` hardcode this market on purpose. They are
  run scripts, not pipeline code: `run_ap_automation.*`, `run_ap_erp_topup.*`,
  `run_ap_factcheck.*`, `chart_factcheck.py` (superseded by
  `scripts/factcheck_chart.py`).

### 3.4 Pipeline made fully generic (owner: "make sure nothing is hardcoded")
Three code sweeps found market-specific code on the live path. All of it was
removed. Details are in `PIPELINE_CHATGPT_EXPAND.md` §11. In short:
- **Axes:** the X/Y parameters were seeded from a 26-industry catalog chosen by
  keywords in the market name. They now come from the LLM, given only the
  market, its geography and its definition.
- **Removed:**
  - a packaging company table (`role_split.py`);
  - market-name gate profiles (semiconductor, glucose, GLP-1, packaging);
  - sector words in the verify role lists;
  - a marine-seismic evidence rule sent to every market;
  - fuzzy seed-file matching;
  - drone names in a wording script.
- **Bugs fixed:**
  - In distributor or retailer markets, verify dropped the market's own
    players.
  - In foundry or EMS markets, the contract-manufacturer filter dropped the
    market's own players.
  - The chart was always 20 (`--top-n` was ignored).
  - The quick scorer always titled the X axis "Product Capability".
  - Discovery scored every company, then the pipeline scored them again.
    Discovery no longer scores, which halves AI Mode use.
- **Problems found in the AP run, fixed generically:**
  - Verify prompts too long for AI Mode fell back to the API. Batches now
    shrink until they fit.
  - An evidence file corrupted when two writers overlapped. All evidence
    writes are now atomic.
  - The owner-label rule missed "acquisition" / "take-private" and got
    reverse mergers backwards.
  - Review corrections now match a company by legal name, variant or brand.
  - New gap wording forms added ("has not been disclosed", ", though …").

### 3.5 Chart fact-check made a pipeline step (step 8a, every run)
Built because the owner asked for it to be part of the pipeline, not optional.
See `PIPELINE_CHATGPT_EXPAND.md` §6. Tested on AP: VERIFY 18/18. Unit tests are
in `tests/test_factcheck.py`.

## 4. Open items / ideas (not done)
- AP: the big ERP vendors (Oracle, Microsoft, Workday, Sage Intacct, NetSuite)
  are missing because the owner stopped discovery. To add them later, run a
  top-up (`scripts/parallel_topup.py`) and then the pipeline with `--reselect`.
- The AP report has not been copied to a Desktop folder. Ask the owner where.
- `config/default.yaml` `junk_filters.blocked_names` still has old exact junk
  titles (pharma / cyber). They are only used by the old web-scraping
  discovery, which is off when AI Mode is on.
- Comments and docstrings still mention old markets as examples (no effect).
- Nothing from this session is committed to git yet. Commit only when the
  owner asks.

## 5. Lessons and gotchas for Claude

- **Git Bash heredocs on this Windows machine collapse `\\` to `\`.** Python
  written via `cat <<'EOF'` therefore turned `\\b` into a backspace character
  (`\x08`) inside regexes. Edit code with the Edit tool. If a script must emit
  a backslash, use `chr(92)`. After any scripted edit, check with
  `grep -c $'\x08' <file>`.
- **Test baseline: 24 known failures** (listed in CLAUDE.md §6). More than 24
  means you broke something.
- **After a code change, re-run a finished market as a regression check.** It
  is cached (no queries, about 1 minute), and VERIFY must stay all PASS. The
  owner once asked "why you do re run". Explain that it is a free safety
  check, not new research.
- **Stopping a run:** kill `python.exe` whose command line contains
  `Coherent-Quadrant`, plus `chrome.exe` / `chromium.exe` whose command line
  contains `ai_mode_batch_`. Also kill the `powershell.exe` launcher.
  Everything resumes from the saved steps.
- **Monitoring:**
  - the pipeline log `logs/parallel/<market>_<country>.log` (lines
    `[pipeline hh:mm:ss] <step>. …`);
  - per-browser logs (`logs/topup_*_<i>.log`, `_pipeline/factcheck/browser_<i>.log`);
  - count blocks with `grep -ciE 'captcha|verifying your request'`.
- **Google blocks:** many "Verifying your request" pages mean too many browsers
  on one IP. The code clears cookies and resets profiles itself; if it keeps
  happening, use fewer browsers.
- **AI Mode's fact-check verdicts are leads, not facts.** In the AP run it:
  - cited Tracxn, Crunchbase, SourceForge, Capterra and Built In;
  - returned "corrections" identical to the original;
  - contradicted itself (Sansan ARR);
  - attributed a claim to the wrong company.
  
  That is why step 8a applies only rule-passing changes and lists the rest.
- **Quick checks:**
  - Count new candidates in parallel-browser copies by reading
    `output/chatgpt_expand_top<i>/<slug>/chatgpt_checkpoint_batch_all.json`
    (`recalled`, `verified`, `rejected_mid`).
  - The main list is the real market's checkpoint `data.verified`, deduped
    with `quadrant_pipeline.dedupe_companies`.
