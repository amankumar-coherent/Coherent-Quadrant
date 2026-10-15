# ProFood India — 75 Coherent Quadrant markets (one command)

Runs the 75 ProFood India topics (from *ProFood India Expo_ CMI Dashboard Topics.xlsx*)
through the Coherent Quadrant pipeline, one market after another, without anyone watching.
Each finished market gets its report in `output\chatgpt_expand\<market>_india\`
(HTML, PDF, Word, JSON, CSV).

## Run it (one command)

From the project folder, in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File profood\start.ps1
```

That's it. The first time on a machine it installs everything, then it starts the queue in
the background and returns. You can close the window; the run continues. Run the same
command again any time to **resume**: finished markets are skipped and each market continues
from its saved work.

| What | Command |
|---|---|
| Progress | `.venv\Scripts\python.exe profood\run_queue.py --status` |
| Live log | `logs\profood\queue.log` (one log per market in `logs\profood\`) |
| Stop (everything is saved) | `powershell -ExecutionPolicy Bypass -File profood\stop.ps1` |
| Run only some markets | `powershell -ExecutionPolicy Bypass -File profood\start.ps1 --only FP-01,FI-03` |
| Re-run stalled / failed markets | `powershell -ExecutionPolicy Bypass -File profood\start.ps1 --retry-failed` |

## First time on a new laptop

1. Install **Python 3.11+** (tick "Add to PATH") and **Git**.
2. Get the project: `git clone <repo url>` (or copy the folder), then `cd Coherent-Quadrant`.
3. Run the one command above. It runs `setup.bat` (creates `.venv`, installs the libraries and
   the bundled Chromium browser) and creates `.env` from `.env.example`.
4. Open `.env`, set your key: `DEEPSEEK_API_KEY=sk-...`, save, and run the command again.

Nothing else to install: the CAPTCHA solver (CAPTCHA Raptor) ships with the project in
`extensions\captcha-raptor\` and loads into every browser automatically. Never copy another
machine's `data\ai_mode_*` folders (they hold Google cookies); fresh ones are created on first run.

## How each market runs

| Setting | Value |
|---|---|
| Browsers | **5 at a time** (browser slots 41–45), one market at a time |
| Geography | **India only** — companies headquartered in India |
| Search | **State by state** across India (each of the 5 browsers takes its own states) |
| Cap | **120 verified companies** per market |
| Moves on | at **120 verified**, or earlier when a pass over the states adds fewer than 5 new companies (all states searched, market exhausted) — then the full report is built on what was found |
| Next market | starts **automatically** when one finishes |
| Report | Top 20 chart (5 per quadrant), up to 120 companies, research panel, PDF, Word |

Order: FP-01 … FP-25, then FI-01 … FI-25, then FMT-01 … FMT-25. Expect roughly 1.5–3 hours
per market on 5 browsers, so the full 75 take several days; it can be stopped and resumed any time.

## Stuck browsers and CAPTCHAs (automatic)

- **CAPTCHA grid:** solved by CAPTCHA Raptor in the browser.
- **CAPTCHA that keeps coming / "Verifying your request" / quota page / "content wasn't generated":**
  the pipeline clears the cookies and relaunches the browser, then resets the whole profile and
  opens a new browser — no waiting, the query is asked again.
- **A browser that hangs** (no log activity for 25 minutes): the queue stops that market, archives
  its 5 browser profiles (fresh cookies on the next start), and restarts the market from its saved
  work. After 3 restarts it marks the market `stalled` and moves on (`--retry-failed` re-runs it).
- **Market status** in `profood\state.json`: `done` (report built, every VERIFY line passed),
  `done_check_verify` (report built, one VERIFY line to look at in `logs\parallel\<market>_india.log`),
  `stalled`, `failed`.

## Saving and resuming (every step, every company)

Everything is saved as it happens, so a stop (`stop.ps1`, closing the laptop, a power cut, a
crash) loses at most the one question that was being asked. Run `profood\start.ps1` again and
each market continues from its last company:

| Step | Saved after | On resume |
|---|---|---|
| Queue | every market | finished markets are skipped; the interrupted one continues |
| Discovery | every batch, per browser | companies already verified are merged in; companies found but **not yet verified are verified first**, before any new search |
| Verification | every 12 companies | checked companies are not asked again |
| Status / ownership / scope / HQ checks | every 10 companies | only unchecked companies are asked |
| Quick X/Y scores | every company | only unscored companies are scored |
| Deep evidence (Top 20) | every company / parameter | only missing parameters are asked |
| Missing parameter parts | every part | a part already asked is not asked again |
| Gap estimates | every company | only open gaps are asked |
| Report, fact-check, PDF, Word | every company (fact-check) | checked companies are not re-checked; the report is rebuilt from saved data |

Saved files: `output\chatgpt_expand\<market>_india\` (and its `_pipeline\` folder) for each market,
`profood\state.json` for the queue. To continue on another laptop, copy (or commit and pull) the
project folder including `output\`; never copy `data\ai_mode_*` (browser cookies).

## Changing a market

Every market's definition, inclusions, exclusions, player type and B2B/B2C are in
`profood\markets.json` (taken from the Excel). Edit a market there, then:

```powershell
.venv\Scripts\python.exe profood\setup_briefs.py profood\markets.json --force
```

Excluded company types (from the "Exclusion" column, plus distributors / resellers and buyers)
are removed from the report entirely.

## Files

| File | Purpose |
|---|---|
| `profood\start.ps1` | the one command: install if needed, start the queue in the background |
| `profood\stop.ps1` | stop the queue and its browsers (progress is kept) |
| `profood\run_queue.py` | the queue: 5 browsers, cap 120, next market, stall recovery |
| `profood\setup_briefs.py` | writes each market's brief from `markets.json` (keeps existing ones) |
| `profood\markets.json` | the 75 markets (definition, inclusion, exclusion, player type) |
| `profood\state.json` | queue progress (created when it runs) |

These files only call the existing pipeline (`logs\run_market.py`); they do not change it.

## The 75 markets

| ID | Market | Companies compared |
|---|---|---|
| FP-01 | India Dairy Products Market | Brand / Marketer (B2C) |
| FP-02 | India Plant-Based Foods Market | Brand / Marketer (B2C) |
| FP-03 | India Bakery Products Market | Brand / Marketer (B2C) |
| FP-04 | India Savoury Snacks Market | Brand / Marketer (B2C) |
| FP-05 | India Sugar Confectionery Market | Brand / Marketer (B2C) |
| FP-06 | India Chocolate Products Market | Brand / Marketer (B2C) |
| FP-07 | India Breakfast Cereals Market | Brand / Marketer (B2C) |
| FP-08 | India Pasta and Noodles Market | Brand / Marketer (B2C) |
| FP-09 | India Ready-to-Eat Meals Market | Brand / Marketer (B2C) |
| FP-10 | India Ready-to-Cook Foods Market | Brand / Marketer (B2C) |
| FP-11 | India Processed Fruits and Vegetables Market | Brand / Marketer (B2C) |
| FP-12 | India Processed Meat and Poultry Market | Brand / Marketer (B2C) |
| FP-13 | India Processed Seafood Market | Brand / Marketer (B2C) |
| FP-14 | India Edible Oils Market | Brand / Marketer (B2C) |
| FP-15 | India Spices and Seasoning Products Market | Brand / Marketer (B2C) |
| FP-16 | India Sauces and Condiments Market | Brand / Marketer (B2C) |
| FP-17 | India Pickles and Preserved Foods Market | Brand / Marketer (B2C) |
| FP-18 | India Packaged Rice Products Market | Brand / Marketer (B2C) |
| FP-19 | India Packaged Flour and Atta Market | Brand / Marketer (B2C) |
| FP-20 | India Pulses and Dal Products Market | Brand / Marketer (B2C) |
| FP-21 | India Frozen Potato Products Market | Brand / Marketer (B2C) |
| FP-22 | India Ice Cream and Frozen Desserts Market | Brand / Marketer (B2C) |
| FP-23 | India Non-Alcoholic Beverages Market | Brand / Marketer (B2C) |
| FP-24 | India Packaged Drinking Water Market | Brand / Marketer (B2C) |
| FP-25 | India Foodservice Prepared Foods Market | Manufacturer (B2B) |
| FI-01 | India Food Flavourings Market | Manufacturer (B2B) |
| FI-02 | India Food Colours Market | Manufacturer (B2B) |
| FI-03 | India High-Intensity Sweeteners Market | Manufacturer (B2B) |
| FI-04 | India Bulk Nutritive Sweeteners Market | Manufacturer (B2B) |
| FI-05 | India Food Emulsifiers Market | Manufacturer (B2B) |
| FI-06 | India Hydrocolloids and Thickeners Market | Manufacturer (B2B) |
| FI-07 | India Food Preservatives Market | Manufacturer (B2B) |
| FI-08 | India Food Enzymes Market | Manufacturer (B2B) |
| FI-09 | India Starter Cultures and Probiotics Market | Manufacturer (B2B) |
| FI-10 | India Food Protein Ingredients Market | Manufacturer (B2B) |
| FI-11 | India Modified Food Starches Market | Manufacturer (B2B) |
| FI-12 | India Dietary Fibre Ingredients Market | Manufacturer (B2B) |
| FI-13 | India Vitamin Premixes Market | Manufacturer (B2B) |
| FI-14 | India Mineral Fortification Ingredients Market | Manufacturer (B2B) |
| FI-15 | India Specialty Food Fats Market | Manufacturer (B2B) |
| FI-16 | India Cocoa Ingredients Market | Manufacturer (B2B) |
| FI-17 | India Dairy Ingredients Market | Manufacturer (B2B) |
| FI-18 | India Egg Ingredients Market | Manufacturer (B2B) |
| FI-19 | India Fruit Preparations and Purees Market | Manufacturer (B2B) |
| FI-20 | India Vegetable Ingredients Market | Manufacturer (B2B) |
| FI-21 | India Savory Taste Enhancers Market | Manufacturer (B2B) |
| FI-22 | India Food Acidulants Market | Manufacturer (B2B) |
| FI-23 | India Anti-Caking and Flow Agents Market | Manufacturer (B2B) |
| FI-24 | India Leavening Ingredients Market | Manufacturer (B2B) |
| FI-25 | India Food Glazing and Coating Agents Market | Manufacturer (B2B) |
| FMT-01 | India Food Mixing and Blending Equipment Market | Manufacturer (B2B) |
| FMT-02 | India Food Size-Reduction Equipment Market | Manufacturer (B2B) |
| FMT-03 | India Food Extrusion Equipment Market | Manufacturer (B2B) |
| FMT-04 | India Industrial Frying Equipment Market | Manufacturer (B2B) |
| FMT-05 | India Industrial Baking Equipment Market | Manufacturer (B2B) |
| FMT-06 | India Food Thermal Processing Equipment Market | Manufacturer (B2B) |
| FMT-07 | India Food Drying and Dehydration Equipment Market | Manufacturer (B2B) |
| FMT-08 | India Food Freezing Equipment Market | Manufacturer (B2B) |
| FMT-09 | India Industrial Food Refrigeration Systems Market | Manufacturer (B2B) |
| FMT-10 | India Food Filling and Dosing Machinery Market | Manufacturer (B2B) |
| FMT-11 | India Food Form-Fill-Seal Machinery Market | Manufacturer (B2B) |
| FMT-12 | India Food End-of-Line Packaging Equipment Market | Manufacturer (B2B) |
| FMT-13 | India Food Labeling and Coding Equipment Market | Manufacturer (B2B) |
| FMT-14 | India Food Inspection and Sorting Equipment Market | Manufacturer (B2B) |
| FMT-15 | India Food Testing Instruments Market | Manufacturer (B2B) |
| FMT-16 | India Food Plant Automation and Control Systems Market | Solution Provider (B2B) |
| FMT-17 | India Food Processing Robotics Market | Manufacturer (B2B) |
| FMT-18 | India Food Manufacturing Execution Software Market | Solution Provider (B2B) |
| FMT-19 | India Food Traceability Software Market | Solution Provider (B2B) |
| FMT-20 | India Food Conveying Systems Market | Manufacturer (B2B) |
| FMT-21 | India Bulk Ingredient Handling and Storage Systems Market | Manufacturer (B2B) |
| FMT-22 | India Food Plant Hygienic Pumps and Valves Market | Manufacturer (B2B) |
| FMT-23 | India Food Plant Cleaning and Sanitation Systems Market | Manufacturer (B2B) |
| FMT-24 | India Food Processing Water Treatment Equipment Market | Manufacturer (B2B) |
| FMT-25 | India Food Plant Steam and Heat Utility Equipment Market | Manufacturer (B2B) |
