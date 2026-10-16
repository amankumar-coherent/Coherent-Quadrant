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

## Market definitions (from the Excel)

As given in *ProFood India Expo_ CMI Dashboard Topics.xlsx* (columns: Market definition, Main inclusion segmentation, Exclusion segmentation). These are the definitions each market runs on (`profood\markets.json`).

### FP-01 — India Dairy Products Market

**Definition:** Dairy Products includes milk, cheese, yogurt, butter, fermented dairy. The India dairy products market covers sales of commercially manufactured finished food and beverage products into retail, foodservice and institutional channels. Market sizing is based on domestic manufacturer-level product revenue, excluding equipment and ingredient supplier turnover.

**Inclusion:** By offering/application: Milk, cheese, yogurt, butter, fermented dairy. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Raw milk trading; dairy machinery. Also exclude unrelated upstream/downstream market revenue.

### FP-02 — India Plant-Based Foods Market

**Definition:** Plant-Based Foods includes plant-based dairy and meat alternatives, ready-to-consume formats. The India plant-based foods market covers sales of commercially manufactured finished food and beverage products into retail, foodservice and institutional channels. Market sizing is based on domestic manufacturer-level product revenue, excluding equipment and ingredient supplier turnover.

**Inclusion:** By offering/application: Plant-based dairy and meat alternatives, ready-to-consume formats. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Conventional animal-derived products; ingredient concentrates. Also exclude unrelated upstream/downstream market revenue.

### FP-03 — India Bakery Products Market

**Definition:** Bakery Products includes bread, biscuits, cakes, pastries, industrial baked foods. The India bakery products market covers sales of commercially manufactured finished food and beverage products into retail, foodservice and institutional channels. Market sizing is based on domestic manufacturer-level product revenue, excluding equipment and ingredient supplier turnover.

**Inclusion:** By offering/application: Bread, biscuits, cakes, pastries, industrial baked foods. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Bakery equipment; baking premixes. Also exclude unrelated upstream/downstream market revenue.

### FP-04 — India Savoury Snacks Market

**Definition:** Savoury Snacks includes potato chips, namkeen, extruded snacks, roasted snacks. The India savoury snacks market covers sales of commercially manufactured finished food and beverage products into retail, foodservice and institutional channels. Market sizing is based on domestic manufacturer-level product revenue, excluding equipment and ingredient supplier turnover.

**Inclusion:** By offering/application: Potato chips, namkeen, extruded snacks, roasted snacks. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Confectionery; snack production equipment. Also exclude unrelated upstream/downstream market revenue.

### FP-05 — India Sugar Confectionery Market

**Definition:** Sugar Confectionery includes candies, gums, toffees, hard and soft confectionery. The India sugar confectionery market covers sales of commercially manufactured finished food and beverage products into retail, foodservice and institutional channels. Market sizing is based on domestic manufacturer-level product revenue, excluding equipment and ingredient supplier turnover.

**Inclusion:** By offering/application: Candies, gums, toffees, hard and soft confectionery. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Chocolate; industrial sweeteners. Also exclude unrelated upstream/downstream market revenue.

### FP-06 — India Chocolate Products Market

**Definition:** Chocolate Products includes chocolate bars, filled chocolate, cocoa confectionery. The India chocolate products market covers sales of commercially manufactured finished food and beverage products into retail, foodservice and institutional channels. Market sizing is based on domestic manufacturer-level product revenue, excluding equipment and ingredient supplier turnover.

**Inclusion:** By offering/application: Chocolate bars, filled chocolate, cocoa confectionery. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Cocoa ingredients; non-chocolate candies. Also exclude unrelated upstream/downstream market revenue.

### FP-07 — India Breakfast Cereals Market

**Definition:** Breakfast Cereals includes ready-to-eat cereals, granola, muesli, cereal flakes. The India breakfast cereals market covers sales of commercially manufactured finished food and beverage products into retail, foodservice and institutional channels. Market sizing is based on domestic manufacturer-level product revenue, excluding equipment and ingredient supplier turnover.

**Inclusion:** By offering/application: Ready-to-eat cereals, granola, muesli, cereal flakes. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Raw grains; breakfast cooking equipment. Also exclude unrelated upstream/downstream market revenue.

### FP-08 — India Pasta and Noodles Market

**Definition:** Pasta and Noodles includes dry pasta, instant noodles, fresh packaged noodles. The India pasta and noodles market covers sales of commercially manufactured finished food and beverage products into retail, foodservice and institutional channels. Market sizing is based on domestic manufacturer-level product revenue, excluding equipment and ingredient supplier turnover.

**Inclusion:** By offering/application: Dry pasta, instant noodles, fresh packaged noodles. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Raw flour; noodle production machinery. Also exclude unrelated upstream/downstream market revenue.

### FP-09 — India Ready-to-Eat Meals Market

**Definition:** Ready-to-Eat Meals includes shelf-stable and chilled fully prepared packaged meals. The India ready-to-eat meals market covers sales of commercially manufactured finished food and beverage products into retail, foodservice and institutional channels. Market sizing is based on domestic manufacturer-level product revenue, excluding equipment and ingredient supplier turnover.

**Inclusion:** By offering/application: Shelf-stable and chilled fully prepared packaged meals. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Meal delivery services; RTC meal kits. Also exclude unrelated upstream/downstream market revenue.

### FP-10 — India Ready-to-Cook Foods Market

**Definition:** Ready-to-Cook Foods includes frozen and ambient cooking kits, batters, prepared mixes. The India ready-to-cook foods market covers sales of commercially manufactured finished food and beverage products into retail, foodservice and institutional channels. Market sizing is based on domestic manufacturer-level product revenue, excluding equipment and ingredient supplier turnover.

**Inclusion:** By offering/application: Frozen and ambient cooking kits, batters, prepared mixes. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Fully cooked meals; standalone food additives. Also exclude unrelated upstream/downstream market revenue.

### FP-11 — India Processed Fruits and Vegetables Market

**Definition:** Processed Fruits and Vegetables includes canned, frozen, dried and pureed fruit and vegetable foods. The India processed fruits and vegetables market covers sales of commercially manufactured finished food and beverage products into retail, foodservice and institutional channels. Market sizing is based on domestic manufacturer-level product revenue, excluding equipment and ingredient supplier turnover.

**Inclusion:** By offering/application: Canned, frozen, dried and pureed fruit and vegetable foods. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Fresh produce retail; juice beverages. Also exclude unrelated upstream/downstream market revenue.

### FP-12 — India Processed Meat and Poultry Market

**Definition:** Processed Meat and Poultry includes sausages, cured meat, frozen prepared poultry, deli meats. The India processed meat and poultry market covers sales of commercially manufactured finished food and beverage products into retail, foodservice and institutional channels. Market sizing is based on domestic manufacturer-level product revenue, excluding equipment and ingredient supplier turnover.

**Inclusion:** By offering/application: Sausages, cured meat, frozen prepared poultry, deli meats. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Live animal trade; slaughter equipment. Also exclude unrelated upstream/downstream market revenue.

### FP-13 — India Processed Seafood Market

**Definition:** Processed Seafood includes frozen, canned, dried and value-added seafood products. The India processed seafood market covers sales of commercially manufactured finished food and beverage products into retail, foodservice and institutional channels. Market sizing is based on domestic manufacturer-level product revenue, excluding equipment and ingredient supplier turnover.

**Inclusion:** By offering/application: Frozen, canned, dried and value-added seafood products. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Fresh fish auctioning; cold storage services. Also exclude unrelated upstream/downstream market revenue.

### FP-14 — India Edible Oils Market

**Definition:** Edible Oils includes consumer and foodservice packaged vegetable cooking oils. The India edible oils market covers sales of commercially manufactured finished food and beverage products into retail, foodservice and institutional channels. Market sizing is based on domestic manufacturer-level product revenue, excluding equipment and ingredient supplier turnover.

**Inclusion:** By offering/application: Consumer and foodservice packaged vegetable cooking oils. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Industrial oleochemicals; oil refining equipment. Also exclude unrelated upstream/downstream market revenue.

### FP-15 — India Spices and Seasoning Products Market

**Definition:** Spices and Seasoning Products includes retail and foodservice packaged spices, blended seasonings. The India spices and seasoning products market covers sales of commercially manufactured finished food and beverage products into retail, foodservice and institutional channels. Market sizing is based on domestic manufacturer-level product revenue, excluding equipment and ingredient supplier turnover.

**Inclusion:** By offering/application: Retail and foodservice packaged spices, blended seasonings. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Industrial flavour compounds; seasoning machinery. Also exclude unrelated upstream/downstream market revenue.

### FP-16 — India Sauces and Condiments Market

**Definition:** Sauces and Condiments includes ketchup, mayonnaise, chutneys, cooking sauces, dressings. The India sauces and condiments market covers sales of commercially manufactured finished food and beverage products into retail, foodservice and institutional channels. Market sizing is based on domestic manufacturer-level product revenue, excluding equipment and ingredient supplier turnover.

**Inclusion:** By offering/application: Ketchup, mayonnaise, chutneys, cooking sauces, dressings. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Dry spices; bottled drinks. Also exclude unrelated upstream/downstream market revenue.

### FP-17 — India Pickles and Preserved Foods Market

**Definition:** Pickles and Preserved Foods includes pickled vegetables, fermented preserves, relishes. The India pickles and preserved foods market covers sales of commercially manufactured finished food and beverage products into retail, foodservice and institutional channels. Market sizing is based on domestic manufacturer-level product revenue, excluding equipment and ingredient supplier turnover.

**Inclusion:** By offering/application: Pickled vegetables, fermented preserves, relishes. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Ambient ready meals; packaging containers. Also exclude unrelated upstream/downstream market revenue.

### FP-18 — India Packaged Rice Products Market

**Definition:** Packaged Rice Products includes consumer packaged milled, parboiled and specialty rice. The India packaged rice products market covers sales of commercially manufactured finished food and beverage products into retail, foodservice and institutional channels. Market sizing is based on domestic manufacturer-level product revenue, excluding equipment and ingredient supplier turnover.

**Inclusion:** By offering/application: Consumer packaged milled, parboiled and specialty rice. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Paddy farming; rice milling machines. Also exclude unrelated upstream/downstream market revenue.

### FP-19 — India Packaged Flour and Atta Market

**Definition:** Packaged Flour and Atta includes packaged wheat flour, multigrain flour and specialty atta. The India packaged flour and atta market covers sales of commercially manufactured finished food and beverage products into retail, foodservice and institutional channels. Market sizing is based on domestic manufacturer-level product revenue, excluding equipment and ingredient supplier turnover.

**Inclusion:** By offering/application: Packaged wheat flour, multigrain flour and specialty atta. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Grain trading; milling machinery. Also exclude unrelated upstream/downstream market revenue.

### FP-20 — India Pulses and Dal Products Market

**Definition:** Pulses and Dal Products includes packaged cleaned, split, polished and processed pulses. The India pulses and dal products market covers sales of commercially manufactured finished food and beverage products into retail, foodservice and institutional channels. Market sizing is based on domestic manufacturer-level product revenue, excluding equipment and ingredient supplier turnover.

**Inclusion:** By offering/application: Packaged cleaned, split, polished and processed pulses. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Farm-gate pulses; protein isolates. Also exclude unrelated upstream/downstream market revenue.

### FP-21 — India Frozen Potato Products Market

**Definition:** Frozen Potato Products includes frozen fries, wedges, hash browns and prepared potato sides. The India frozen potato products market covers sales of commercially manufactured finished food and beverage products into retail, foodservice and institutional channels. Market sizing is based on domestic manufacturer-level product revenue, excluding equipment and ingredient supplier turnover.

**Inclusion:** By offering/application: Frozen fries, wedges, hash browns and prepared potato sides. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Fresh potatoes; freezing machinery. Also exclude unrelated upstream/downstream market revenue.

### FP-22 — India Ice Cream and Frozen Desserts Market

**Definition:** Ice Cream and Frozen Desserts includes ice cream, kulfi, frozen dairy and non-dairy desserts. The India ice cream and frozen desserts market covers sales of commercially manufactured finished food and beverage products into retail, foodservice and institutional channels. Market sizing is based on domestic manufacturer-level product revenue, excluding equipment and ingredient supplier turnover.

**Inclusion:** By offering/application: Ice cream, kulfi, frozen dairy and non-dairy desserts. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Industrial freezing equipment; chilled yogurt. Also exclude unrelated upstream/downstream market revenue.

### FP-23 — India Non-Alcoholic Beverages Market

**Definition:** Non-Alcoholic Beverages includes packaged juices, carbonated soft drinks, energy and functional beverages. The India non-alcoholic beverages market covers sales of commercially manufactured finished food and beverage products into retail, foodservice and institutional channels. Market sizing is based on domestic manufacturer-level product revenue, excluding equipment and ingredient supplier turnover.

**Inclusion:** By offering/application: Packaged juices, carbonated soft drinks, energy and functional beverages. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Alcoholic drinks; bottling machinery. Also exclude unrelated upstream/downstream market revenue.

### FP-24 — India Packaged Drinking Water Market

**Definition:** Packaged Drinking Water includes bottled drinking water, mineral water and bulk packaged water. The India packaged drinking water market covers sales of commercially manufactured finished food and beverage products into retail, foodservice and institutional channels. Market sizing is based on domestic manufacturer-level product revenue, excluding equipment and ingredient supplier turnover.

**Inclusion:** By offering/application: Bottled drinking water, mineral water and bulk packaged water. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Municipal water supply; purification machinery. Also exclude unrelated upstream/downstream market revenue.

### FP-25 — India Foodservice Prepared Foods Market

**Definition:** Foodservice Prepared Foods includes factory-produced ready-to-serve foods sold to institutional and horeca buyers. The India foodservice prepared foods market covers sales of commercially manufactured finished food and beverage products into retail, foodservice and institutional channels. Market sizing is based on domestic manufacturer-level product revenue, excluding equipment and ingredient supplier turnover.

**Inclusion:** By offering/application: Factory-produced ready-to-serve foods sold to institutional and HoReCa buyers. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Restaurant service revenues; retail packaged RTE meals. Also exclude unrelated upstream/downstream market revenue.

### FI-01 — India Food Flavourings Market

**Definition:** Food Flavourings includes natural and synthetic flavour blends, extracts and aroma systems. The India food flavourings market covers B2B sales of food-grade formulation inputs supplied to processors, bakeries, beverage makers and other manufacturers. Market sizing captures ingredient supplier revenue in India, not the sales value of downstream finished foods.

**Inclusion:** By offering/application: Natural and synthetic flavour blends, extracts and aroma systems. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Finished beverages; spice retail. Also exclude unrelated upstream/downstream market revenue.

### FI-02 — India Food Colours Market

**Definition:** Food Colours includes natural and synthetic colourants for food formulations. The India food colours market covers B2B sales of food-grade formulation inputs supplied to processors, bakeries, beverage makers and other manufacturers. Market sizing captures ingredient supplier revenue in India, not the sales value of downstream finished foods.

**Inclusion:** By offering/application: Natural and synthetic colourants for food formulations. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Decorative packaging inks; finished foods. Also exclude unrelated upstream/downstream market revenue.

### FI-03 — India High-Intensity Sweeteners Market

**Definition:** High-Intensity Sweeteners includes stevia, sucralose, aspartame and other high-potency sweetening ingredients. The India high-intensity sweeteners market covers B2B sales of food-grade formulation inputs supplied to processors, bakeries, beverage makers and other manufacturers. Market sizing captures ingredient supplier revenue in India, not the sales value of downstream finished foods.

**Inclusion:** By offering/application: Stevia, sucralose, aspartame and other high-potency sweetening ingredients. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Bulk sugar; finished diet beverages. Also exclude unrelated upstream/downstream market revenue.

### FI-04 — India Bulk Nutritive Sweeteners Market

**Definition:** Bulk Nutritive Sweeteners includes glucose syrup, fructose syrup, dextrose and similar caloric sweeteners. The India bulk nutritive sweeteners market covers B2B sales of food-grade formulation inputs supplied to processors, bakeries, beverage makers and other manufacturers. Market sizing captures ingredient supplier revenue in India, not the sales value of downstream finished foods.

**Inclusion:** By offering/application: Glucose syrup, fructose syrup, dextrose and similar caloric sweeteners. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: High-intensity sweeteners; consumer sugar retail. Also exclude unrelated upstream/downstream market revenue.

### FI-05 — India Food Emulsifiers Market

**Definition:** Food Emulsifiers includes lecithins, mono/diglycerides and emulsifying ingredient systems. The India food emulsifiers market covers B2B sales of food-grade formulation inputs supplied to processors, bakeries, beverage makers and other manufacturers. Market sizing captures ingredient supplier revenue in India, not the sales value of downstream finished foods.

**Inclusion:** By offering/application: Lecithins, mono/diglycerides and emulsifying ingredient systems. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Stabilizing gums; finished spreads. Also exclude unrelated upstream/downstream market revenue.

### FI-06 — India Hydrocolloids and Thickeners Market

**Definition:** Hydrocolloids and Thickeners includes pectin, xanthan, guar, carrageenan and viscosity modifiers. The India hydrocolloids and thickeners market covers B2B sales of food-grade formulation inputs supplied to processors, bakeries, beverage makers and other manufacturers. Market sizing captures ingredient supplier revenue in India, not the sales value of downstream finished foods.

**Inclusion:** By offering/application: Pectin, xanthan, guar, carrageenan and viscosity modifiers. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Emulsifiers; ready-made sauces. Also exclude unrelated upstream/downstream market revenue.

### FI-07 — India Food Preservatives Market

**Definition:** Food Preservatives includes antimicrobial and oxidation-control preservative additives. The India food preservatives market covers B2B sales of food-grade formulation inputs supplied to processors, bakeries, beverage makers and other manufacturers. Market sizing captures ingredient supplier revenue in India, not the sales value of downstream finished foods.

**Inclusion:** By offering/application: Antimicrobial and oxidation-control preservative additives. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Sanitation chemicals; packaged food. Also exclude unrelated upstream/downstream market revenue.

### FI-08 — India Food Enzymes Market

**Definition:** Food Enzymes includes processing enzymes for baking, dairy, brewing and starch conversion. The India food enzymes market covers B2B sales of food-grade formulation inputs supplied to processors, bakeries, beverage makers and other manufacturers. Market sizing captures ingredient supplier revenue in India, not the sales value of downstream finished foods.

**Inclusion:** By offering/application: Processing enzymes for baking, dairy, brewing and starch conversion. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Starter cultures; enzyme processing machines. Also exclude unrelated upstream/downstream market revenue.

### FI-09 — India Starter Cultures and Probiotics Market

**Definition:** Starter Cultures and Probiotics includes microbial cultures and probiotic ingredients supplied to food makers. The India starter cultures and probiotics market covers B2B sales of food-grade formulation inputs supplied to processors, bakeries, beverage makers and other manufacturers. Market sizing captures ingredient supplier revenue in India, not the sales value of downstream finished foods.

**Inclusion:** By offering/application: Microbial cultures and probiotic ingredients supplied to food makers. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Finished probiotic foods; food enzymes. Also exclude unrelated upstream/downstream market revenue.

### FI-10 — India Food Protein Ingredients Market

**Definition:** Food Protein Ingredients includes whey, soy, pea and other protein concentrates and isolates. The India food protein ingredients market covers B2B sales of food-grade formulation inputs supplied to processors, bakeries, beverage makers and other manufacturers. Market sizing captures ingredient supplier revenue in India, not the sales value of downstream finished foods.

**Inclusion:** By offering/application: Whey, soy, pea and other protein concentrates and isolates. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Finished protein snacks; raw pulses. Also exclude unrelated upstream/downstream market revenue.

### FI-11 — India Modified Food Starches Market

**Definition:** Modified Food Starches includes chemically and physically modified starches for formulation. The India modified food starches market covers B2B sales of food-grade formulation inputs supplied to processors, bakeries, beverage makers and other manufacturers. Market sizing captures ingredient supplier revenue in India, not the sales value of downstream finished foods.

**Inclusion:** By offering/application: Chemically and physically modified starches for formulation. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Native cereal flours; hydrocolloids. Also exclude unrelated upstream/downstream market revenue.

### FI-12 — India Dietary Fibre Ingredients Market

**Definition:** Dietary Fibre Ingredients includes inulin, resistant dextrin, beta-glucan and fibre fortification inputs. The India dietary fibre ingredients market covers B2B sales of food-grade formulation inputs supplied to processors, bakeries, beverage makers and other manufacturers. Market sizing captures ingredient supplier revenue in India, not the sales value of downstream finished foods.

**Inclusion:** By offering/application: Inulin, resistant dextrin, beta-glucan and fibre fortification inputs. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Whole-grain finished foods; protein isolates. Also exclude unrelated upstream/downstream market revenue.

### FI-13 — India Vitamin Premixes Market

**Definition:** Vitamin Premixes includes vitamin ingredient blends and premixes for food fortification. The India vitamin premixes market covers B2B sales of food-grade formulation inputs supplied to processors, bakeries, beverage makers and other manufacturers. Market sizing captures ingredient supplier revenue in India, not the sales value of downstream finished foods.

**Inclusion:** By offering/application: Vitamin ingredient blends and premixes for food fortification. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Mineral-only premixes; retail supplements. Also exclude unrelated upstream/downstream market revenue.

### FI-14 — India Mineral Fortification Ingredients Market

**Definition:** Mineral Fortification Ingredients includes iron, calcium, zinc and other food-grade mineral fortificants. The India mineral fortification ingredients market covers B2B sales of food-grade formulation inputs supplied to processors, bakeries, beverage makers and other manufacturers. Market sizing captures ingredient supplier revenue in India, not the sales value of downstream finished foods.

**Inclusion:** By offering/application: Iron, calcium, zinc and other food-grade mineral fortificants. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Vitamin premixes; pharmaceutical minerals. Also exclude unrelated upstream/downstream market revenue.

### FI-15 — India Specialty Food Fats Market

**Definition:** Specialty Food Fats includes cocoa butter equivalents, bakery shortenings and engineered fats. The India specialty food fats market covers B2B sales of food-grade formulation inputs supplied to processors, bakeries, beverage makers and other manufacturers. Market sizing captures ingredient supplier revenue in India, not the sales value of downstream finished foods.

**Inclusion:** By offering/application: Cocoa butter equivalents, bakery shortenings and engineered fats. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Consumer cooking oil; fat processing machinery. Also exclude unrelated upstream/downstream market revenue.

### FI-16 — India Cocoa Ingredients Market

**Definition:** Cocoa Ingredients includes cocoa powder, cocoa liquor and cocoa butter sold as inputs. The India cocoa ingredients market covers B2B sales of food-grade formulation inputs supplied to processors, bakeries, beverage makers and other manufacturers. Market sizing captures ingredient supplier revenue in India, not the sales value of downstream finished foods.

**Inclusion:** By offering/application: Cocoa powder, cocoa liquor and cocoa butter sold as inputs. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Finished chocolate; cocoa-flavoured drinks. Also exclude unrelated upstream/downstream market revenue.

### FI-17 — India Dairy Ingredients Market

**Definition:** Dairy Ingredients includes milk powder, lactose, casein and whey-derived non-protein dairy inputs. The India dairy ingredients market covers B2B sales of food-grade formulation inputs supplied to processors, bakeries, beverage makers and other manufacturers. Market sizing captures ingredient supplier revenue in India, not the sales value of downstream finished foods.

**Inclusion:** By offering/application: Milk powder, lactose, casein and whey-derived non-protein dairy inputs. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Retail dairy foods; isolated protein concentrates. Also exclude unrelated upstream/downstream market revenue.

### FI-18 — India Egg Ingredients Market

**Definition:** Egg Ingredients includes liquid, dried, frozen and functional egg ingredients. The India egg ingredients market covers B2B sales of food-grade formulation inputs supplied to processors, bakeries, beverage makers and other manufacturers. Market sizing captures ingredient supplier revenue in India, not the sales value of downstream finished foods.

**Inclusion:** By offering/application: Liquid, dried, frozen and functional egg ingredients. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Shell eggs at retail; poultry meat. Also exclude unrelated upstream/downstream market revenue.

### FI-19 — India Fruit Preparations and Purees Market

**Definition:** Fruit Preparations and Purees includes industrial fruit purees, concentrates and inclusions for food makers. The India fruit preparations and purees market covers B2B sales of food-grade formulation inputs supplied to processors, bakeries, beverage makers and other manufacturers. Market sizing captures ingredient supplier revenue in India, not the sales value of downstream finished foods.

**Inclusion:** By offering/application: Industrial fruit purees, concentrates and inclusions for food makers. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Finished fruit beverages; fresh fruit trade. Also exclude unrelated upstream/downstream market revenue.

### FI-20 — India Vegetable Ingredients Market

**Definition:** Vegetable Ingredients includes industrial vegetable powders, purees and dehydrated inclusions. The India vegetable ingredients market covers B2B sales of food-grade formulation inputs supplied to processors, bakeries, beverage makers and other manufacturers. Market sizing captures ingredient supplier revenue in India, not the sales value of downstream finished foods.

**Inclusion:** By offering/application: Industrial vegetable powders, purees and dehydrated inclusions. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Finished vegetable snacks; fresh produce. Also exclude unrelated upstream/downstream market revenue.

### FI-21 — India Savory Taste Enhancers Market

**Definition:** Savory Taste Enhancers includes yeast extracts, msg, nucleotides and umami ingredient systems. The India savory taste enhancers market covers B2B sales of food-grade formulation inputs supplied to processors, bakeries, beverage makers and other manufacturers. Market sizing captures ingredient supplier revenue in India, not the sales value of downstream finished foods.

**Inclusion:** By offering/application: Yeast extracts, MSG, nucleotides and umami ingredient systems. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Retail spice mixes; flavour aroma blends. Also exclude unrelated upstream/downstream market revenue.

### FI-22 — India Food Acidulants Market

**Definition:** Food Acidulants includes citric, lactic, malic and other food-grade acidulants. The India food acidulants market covers B2B sales of food-grade formulation inputs supplied to processors, bakeries, beverage makers and other manufacturers. Market sizing captures ingredient supplier revenue in India, not the sales value of downstream finished foods.

**Inclusion:** By offering/application: Citric, lactic, malic and other food-grade acidulants. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Industrial cleaning acids; preservatives. Also exclude unrelated upstream/downstream market revenue.

### FI-23 — India Anti-Caking and Flow Agents Market

**Definition:** Anti-Caking and Flow Agents includes silicates, phosphates and flow-aid ingredients for powdered foods. The India anti-caking and flow agents market covers B2B sales of food-grade formulation inputs supplied to processors, bakeries, beverage makers and other manufacturers. Market sizing captures ingredient supplier revenue in India, not the sales value of downstream finished foods.

**Inclusion:** By offering/application: Silicates, phosphates and flow-aid ingredients for powdered foods. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Powder handling machinery; food packaging. Also exclude unrelated upstream/downstream market revenue.

### FI-24 — India Leavening Ingredients Market

**Definition:** Leavening Ingredients includes baking powder, bicarbonate systems and chemical raising agents. The India leavening ingredients market covers B2B sales of food-grade formulation inputs supplied to processors, bakeries, beverage makers and other manufacturers. Market sizing captures ingredient supplier revenue in India, not the sales value of downstream finished foods.

**Inclusion:** By offering/application: Baking powder, bicarbonate systems and chemical raising agents. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Yeast starter cultures; baked finished goods. Also exclude unrelated upstream/downstream market revenue.

### FI-25 — India Food Glazing and Coating Agents Market

**Definition:** Food Glazing and Coating Agents includes edible waxes, confectionery glazing agents and protective edible coatings. The India food glazing and coating agents market covers B2B sales of food-grade formulation inputs supplied to processors, bakeries, beverage makers and other manufacturers. Market sizing captures ingredient supplier revenue in India, not the sales value of downstream finished foods.

**Inclusion:** By offering/application: Edible waxes, confectionery glazing agents and protective edible coatings. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Industrial packaging coatings; confectionery products. Also exclude unrelated upstream/downstream market revenue.

### FMT-01 — India Food Mixing and Blending Equipment Market

**Definition:** Food Mixing and Blending Equipment includes industrial batch and continuous mixers, blenders, kneaders. The India food mixing and blending equipment market covers supplier revenue from dedicated industrial systems sold for use in food and beverage manufacturing facilities. Market sizing includes equipment and directly associated embedded controls, excluding the value of food output and unrelated plant services.

**Inclusion:** By offering/application: Industrial batch and continuous mixers, blenders, kneaders. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Ingredient sales; standalone grinding machines. Also exclude unrelated upstream/downstream market revenue.

### FMT-02 — India Food Size-Reduction Equipment Market

**Definition:** Food Size-Reduction Equipment includes industrial grinders, crushers, slicers, cutters and mills. The India food size-reduction equipment market covers supplier revenue from dedicated industrial systems sold for use in food and beverage manufacturing facilities. Market sizing includes equipment and directly associated embedded controls, excluding the value of food output and unrelated plant services.

**Inclusion:** By offering/application: Industrial grinders, crushers, slicers, cutters and mills. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Farm machinery; extrusion lines. Also exclude unrelated upstream/downstream market revenue.

### FMT-03 — India Food Extrusion Equipment Market

**Definition:** Food Extrusion Equipment includes single/twin-screw food extruders and integrated extrusion systems. The India food extrusion equipment market covers supplier revenue from dedicated industrial systems sold for use in food and beverage manufacturing facilities. Market sizing includes equipment and directly associated embedded controls, excluding the value of food output and unrelated plant services.

**Inclusion:** By offering/application: Single/twin-screw food extruders and integrated extrusion systems. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Extruded snack product revenue; standalone mixers. Also exclude unrelated upstream/downstream market revenue.

### FMT-04 — India Industrial Frying Equipment Market

**Definition:** Industrial Frying Equipment includes continuous and batch fryers, oil filtration within frying lines. The India industrial frying equipment market covers supplier revenue from dedicated industrial systems sold for use in food and beverage manufacturing facilities. Market sizing includes equipment and directly associated embedded controls, excluding the value of food output and unrelated plant services.

**Inclusion:** By offering/application: Continuous and batch fryers, oil filtration within frying lines. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Retail frying appliances; edible oil. Also exclude unrelated upstream/downstream market revenue.

### FMT-05 — India Industrial Baking Equipment Market

**Definition:** Industrial Baking Equipment includes commercial tunnel, rack and rotary ovens, proofing equipment. The India industrial baking equipment market covers supplier revenue from dedicated industrial systems sold for use in food and beverage manufacturing facilities. Market sizing includes equipment and directly associated embedded controls, excluding the value of food output and unrelated plant services.

**Inclusion:** By offering/application: Commercial tunnel, rack and rotary ovens, proofing equipment. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Baked goods; industrial boilers. Also exclude unrelated upstream/downstream market revenue.

### FMT-06 — India Food Thermal Processing Equipment Market

**Definition:** Food Thermal Processing Equipment includes retorts, pasteurizers, sterilizers and uht thermal systems. The India food thermal processing equipment market covers supplier revenue from dedicated industrial systems sold for use in food and beverage manufacturing facilities. Market sizing includes equipment and directly associated embedded controls, excluding the value of food output and unrelated plant services.

**Inclusion:** By offering/application: Retorts, pasteurizers, sterilizers and UHT thermal systems. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Commercial baking ovens; finished milk. Also exclude unrelated upstream/downstream market revenue.

### FMT-07 — India Food Drying and Dehydration Equipment Market

**Definition:** Food Drying and Dehydration Equipment includes spray, freeze, belt and tray drying systems for foods. The India food drying and dehydration equipment market covers supplier revenue from dedicated industrial systems sold for use in food and beverage manufacturing facilities. Market sizing includes equipment and directly associated embedded controls, excluding the value of food output and unrelated plant services.

**Inclusion:** By offering/application: Spray, freeze, belt and tray drying systems for foods. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Dried finished food revenue; refrigeration systems. Also exclude unrelated upstream/downstream market revenue.

### FMT-08 — India Food Freezing Equipment Market

**Definition:** Food Freezing Equipment includes iqf, blast, spiral and cryogenic food freezers. The India food freezing equipment market covers supplier revenue from dedicated industrial systems sold for use in food and beverage manufacturing facilities. Market sizing includes equipment and directly associated embedded controls, excluding the value of food output and unrelated plant services.

**Inclusion:** By offering/application: IQF, blast, spiral and cryogenic food freezers. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Frozen food sales; cold warehouses. Also exclude unrelated upstream/downstream market revenue.

### FMT-09 — India Industrial Food Refrigeration Systems Market

**Definition:** Industrial Food Refrigeration Systems includes process chillers, compressors and refrigeration plants for food facilities. The India industrial food refrigeration systems market covers supplier revenue from dedicated industrial systems sold for use in food and beverage manufacturing facilities. Market sizing includes equipment and directly associated embedded controls, excluding the value of food output and unrelated plant services.

**Inclusion:** By offering/application: Process chillers, compressors and refrigeration plants for food facilities. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Transport refrigeration; cold-storage real estate. Also exclude unrelated upstream/downstream market revenue.

### FMT-10 — India Food Filling and Dosing Machinery Market

**Definition:** Food Filling and Dosing Machinery includes volumetric, gravimetric, aseptic and liquid filling/dosing systems. The India food filling and dosing machinery market covers supplier revenue from dedicated industrial systems sold for use in food and beverage manufacturing facilities. Market sizing includes equipment and directly associated embedded controls, excluding the value of food output and unrelated plant services.

**Inclusion:** By offering/application: Volumetric, gravimetric, aseptic and liquid filling/dosing systems. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Packaging material; labeling machinery. Also exclude unrelated upstream/downstream market revenue.

### FMT-11 — India Food Form-Fill-Seal Machinery Market

**Definition:** Food Form-Fill-Seal Machinery includes vertical and horizontal ffs packaging machines for food. The India food form-fill-seal machinery market covers supplier revenue from dedicated industrial systems sold for use in food and beverage manufacturing facilities. Market sizing includes equipment and directly associated embedded controls, excluding the value of food output and unrelated plant services.

**Inclusion:** By offering/application: Vertical and horizontal FFS packaging machines for food. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Pouches and films; standalone fillers. Also exclude unrelated upstream/downstream market revenue.

### FMT-12 — India Food End-of-Line Packaging Equipment Market

**Definition:** Food End-of-Line Packaging Equipment includes case packers, palletizers, stretch wrappers and cartoners. The India food end-of-line packaging equipment market covers supplier revenue from dedicated industrial systems sold for use in food and beverage manufacturing facilities. Market sizing includes equipment and directly associated embedded controls, excluding the value of food output and unrelated plant services.

**Inclusion:** By offering/application: Case packers, palletizers, stretch wrappers and cartoners. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Primary FFS machinery; packaging material. Also exclude unrelated upstream/downstream market revenue.

### FMT-13 — India Food Labeling and Coding Equipment Market

**Definition:** Food Labeling and Coding Equipment includes print-and-apply labeling, inkjet coding and laser marking systems. The India food labeling and coding equipment market covers supplier revenue from dedicated industrial systems sold for use in food and beverage manufacturing facilities. Market sizing includes equipment and directly associated embedded controls, excluding the value of food output and unrelated plant services.

**Inclusion:** By offering/application: Print-and-apply labeling, inkjet coding and laser marking systems. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Label consumables; inspection cameras. Also exclude unrelated upstream/downstream market revenue.

### FMT-14 — India Food Inspection and Sorting Equipment Market

**Definition:** Food Inspection and Sorting Equipment includes metal detectors, x-ray inspection, optical sorters and checkweighers. The India food inspection and sorting equipment market covers supplier revenue from dedicated industrial systems sold for use in food and beverage manufacturing facilities. Market sizing includes equipment and directly associated embedded controls, excluding the value of food output and unrelated plant services.

**Inclusion:** By offering/application: Metal detectors, X-ray inspection, optical sorters and checkweighers. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Laboratory food testing; quality certification. Also exclude unrelated upstream/downstream market revenue.

### FMT-15 — India Food Testing Instruments Market

**Definition:** Food Testing Instruments includes chromatography, spectroscopy, microbiology and rapid test instruments. The India food testing instruments market covers supplier revenue from dedicated industrial systems sold for use in food and beverage manufacturing facilities. Market sizing includes equipment and directly associated embedded controls, excluding the value of food output and unrelated plant services.

**Inclusion:** By offering/application: Chromatography, spectroscopy, microbiology and rapid test instruments. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Contract laboratory services; inline sorters. Also exclude unrelated upstream/downstream market revenue.

### FMT-16 — India Food Plant Automation and Control Systems Market

**Definition:** Food Plant Automation and Control Systems includes plc, scada, sensors and process control hardware/software for food plants. The India food plant automation and control systems market covers supplier revenue from dedicated industrial systems sold for use in food and beverage manufacturing facilities. Market sizing includes equipment and directly associated embedded controls, excluding the value of food output and unrelated plant services.

**Inclusion:** By offering/application: PLC, SCADA, sensors and process control hardware/software for food plants. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Industrial robots; ERP applications. Also exclude unrelated upstream/downstream market revenue.

### FMT-17 — India Food Processing Robotics Market

**Definition:** Food Processing Robotics includes robotic picking, handling and product manipulation within food lines. The India food processing robotics market covers supplier revenue from dedicated industrial systems sold for use in food and beverage manufacturing facilities. Market sizing includes equipment and directly associated embedded controls, excluding the value of food output and unrelated plant services.

**Inclusion:** By offering/application: Robotic picking, handling and product manipulation within food lines. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: General conveyor systems; palletizers. Also exclude unrelated upstream/downstream market revenue.

### FMT-18 — India Food Manufacturing Execution Software Market

**Definition:** Food Manufacturing Execution Software includes mes, batch traceability, production scheduling and plant execution software. The India food manufacturing execution software market covers supplier revenue from dedicated industrial systems sold for use in food and beverage manufacturing facilities. Market sizing includes equipment and directly associated embedded controls, excluding the value of food output and unrelated plant services.

**Inclusion:** By offering/application: MES, batch traceability, production scheduling and plant execution software. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Generic ERP; PLC hardware. Also exclude unrelated upstream/downstream market revenue.

### FMT-19 — India Food Traceability Software Market

**Definition:** Food Traceability Software includes lot-level provenance, recall and supply-chain tracking platforms. The India food traceability software market covers supplier revenue from dedicated industrial systems sold for use in food and beverage manufacturing facilities. Market sizing includes equipment and directly associated embedded controls, excluding the value of food output and unrelated plant services.

**Inclusion:** By offering/application: Lot-level provenance, recall and supply-chain tracking platforms. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Physical product inspection; generic warehouse ERP. Also exclude unrelated upstream/downstream market revenue.

### FMT-20 — India Food Conveying Systems Market

**Definition:** Food Conveying Systems includes belt, screw, pneumatic and sanitary conveying equipment for food. The India food conveying systems market covers supplier revenue from dedicated industrial systems sold for use in food and beverage manufacturing facilities. Market sizing includes equipment and directly associated embedded controls, excluding the value of food output and unrelated plant services.

**Inclusion:** By offering/application: Belt, screw, pneumatic and sanitary conveying equipment for food. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Warehouse forklifts; mixers. Also exclude unrelated upstream/downstream market revenue.

### FMT-21 — India Bulk Ingredient Handling and Storage Systems Market

**Definition:** Bulk Ingredient Handling and Storage Systems includes silos, bins, bulk discharge and powder transfer/storage systems. The India bulk ingredient handling and storage systems market covers supplier revenue from dedicated industrial systems sold for use in food and beverage manufacturing facilities. Market sizing includes equipment and directly associated embedded controls, excluding the value of food output and unrelated plant services.

**Inclusion:** By offering/application: Silos, bins, bulk discharge and powder transfer/storage systems. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Retail warehousing; finished food packaging. Also exclude unrelated upstream/downstream market revenue.

### FMT-22 — India Food Plant Hygienic Pumps and Valves Market

**Definition:** Food Plant Hygienic Pumps and Valves includes sanitary pumps, process valves and hygienic flow components. The India food plant hygienic pumps and valves market covers supplier revenue from dedicated industrial systems sold for use in food and beverage manufacturing facilities. Market sizing includes equipment and directly associated embedded controls, excluding the value of food output and unrelated plant services.

**Inclusion:** By offering/application: Sanitary pumps, process valves and hygienic flow components. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Non-food industrial valves; food ingredients. Also exclude unrelated upstream/downstream market revenue.

### FMT-23 — India Food Plant Cleaning and Sanitation Systems Market

**Definition:** Food Plant Cleaning and Sanitation Systems includes cip skids, cop equipment, industrial washdown and sanitation hardware. The India food plant cleaning and sanitation systems market covers supplier revenue from dedicated industrial systems sold for use in food and beverage manufacturing facilities. Market sizing includes equipment and directly associated embedded controls, excluding the value of food output and unrelated plant services.

**Inclusion:** By offering/application: CIP skids, COP equipment, industrial washdown and sanitation hardware. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Sanitizing chemical sales; food testing. Also exclude unrelated upstream/downstream market revenue.

### FMT-24 — India Food Processing Water Treatment Equipment Market

**Definition:** Food Processing Water Treatment Equipment includes filtration, ro, uv and wastewater treatment equipment for food factories. The India food processing water treatment equipment market covers supplier revenue from dedicated industrial systems sold for use in food and beverage manufacturing facilities. Market sizing includes equipment and directly associated embedded controls, excluding the value of food output and unrelated plant services.

**Inclusion:** By offering/application: Filtration, RO, UV and wastewater treatment equipment for food factories. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Municipal water treatment; packaged water sales. Also exclude unrelated upstream/downstream market revenue.

### FMT-25 — India Food Plant Steam and Heat Utility Equipment Market

**Definition:** Food Plant Steam and Heat Utility Equipment includes steam boilers, heat exchangers and thermal utility equipment for food factories. The India food plant steam and heat utility equipment market covers supplier revenue from dedicated industrial systems sold for use in food and beverage manufacturing facilities. Market sizing includes equipment and directly associated embedded controls, excluding the value of food output and unrelated plant services.

**Inclusion:** By offering/application: Steam boilers, heat exchangers and thermal utility equipment for food factories. By buyer: industrial food manufacturers; relevant foodservice/retail channels where applicable.

**Exclusion:** Exclude: Direct food pasteurization lines; ovens. Also exclude unrelated upstream/downstream market revenue.
