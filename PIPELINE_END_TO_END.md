# Coherent Quadrant — Full Pipeline, Start to End

How a market name becomes a scored competitive quadrant, and exactly what is
asked of Google AI Mode at each step.

Companion docs:
- `GOOGLE_AI_MODE_INTEGRATION.md` — browser plumbing (Patchright, CAPTCHAs, pacing)
- `COMPANY_DISCOVERY_ROUNDS.md` — the discovery loop in detail
- `COMPANY_VERIFICATION_AI_MODE.md` — chunked verification in detail

---

## 0. One command

```bash
.\.venv\Scripts\python.exe scripts\run_chatgpt_expand.py \
    --query "Global Water Bottles Market" --target 300
```

Several markets, strictly one at a time (Google rate-limits per IP):

```bash
.\.venv\Scripts\python.exe scripts\run_market_batch.py \
    --markets-file queries\batch.txt --target 300
```

Output lands in `output/chatgpt_expand/<slug>/`:
`*_FINAL.xlsx`, `*_report.html`, `*_quadrant.json`, and a checkpoint.

---

## 1. The shape of the whole thing

```
market name
    │
 0c ├─ MARKET ANALYSIS ......... AI Mode → B2B | B2C | Hybrid B2B + B2C
    │                                    → one player type for the market
    │
 1  ├─ DISCOVERY IN ROUNDS ..... AI Mode → BRAND + the COMPANY behind it
    │   10 per round, exclusion list every round, stop on 3 empty rounds
    │
 4  ├─ VERIFY (chunks of 12) ... AI Mode → keep / drop, with confidence
    │
 5  ├─ GAP FILL ................ DeepSeek (prompt too large for a search box)
    │
 6  ├─ FINAL VERIFY (chunks of 10) AI Mode → second pass on filled rows
    │
 6c ├─ SCORE .................. AI Mode → X and Y, one query each
    │   then row-level floor-65 normalisation, then quadrants
    │
 7  └─ EXPORT ................. FINAL.xlsx + HTML report
```

Everything is checkpointed per step (and per round/chunk/company), so an
interrupted run resumes exactly where it stopped.

---

## 2. Which backend answers what, and why

| Step | Backend | Why |
|---|---|---|
| 0c market analysis | **AI Mode** | 1.6 KB prompt, fits a search query |
| 1 discovery rounds | **AI Mode** | web lookup — what AI Mode is for |
| 4 / 6 verify | **AI Mode** | ~1–5 KB per chunk, still fits |
| 5 gap fill | **DeepSeek** | ~12 KB of rules — too large for a URL |
| 6c scoring | **AI Mode** | 185-char query per axis |
| Axis parameters | **DeepSeek** | reasoning task with a JSON schema |
| Query generation | **DeepSeek** | writes the queries AI Mode then runs |

Routing is decided by `_fits_ai_mode()`, which measures the **actual encoded
URL** rather than guessing from character count:

```python
if len(build_url(prompt)) <= MAX_URL_CHARS - 200:   # 7800 limit
    return True          # AI Mode
```

> Two bugs lived here. Gap-fill's ~12 KB prompt was pushed into the search box
> and returned *"Something went wrong"* — truncation had taken the JSON
> template with it. The fix then over-corrected to a fixed 1,800-char cap,
> which needlessly diverted the 4,984-char verify chunks to the API.
> **Measure the encoded URL; do not guess from length.**

---

## 3. Step 0c — market analysis (AI Mode)

Runs **before** discovery so every later prompt knows what to look for.

```
Return JSON only:
{
  "market_type": "B2B" | "B2C" | "Hybrid B2B + B2C",
  "market_type_reason": "...",
  "market_definition": "...",
  "market_participants": [{"type","definition","why_relevant"}],
  "primary_participant": "...",
  "primary_reason": "..."
}
```

**Market type** is decided from target customers, purchasing behaviour,
distribution model, buyer type and sales channel — never from one company's
marketing language. A market that genuinely sells to both businesses and
consumers is **Hybrid B2B + B2C**, and is still ONE landscape: the brand and
the company behind it do not change with the channel.

**Player type** — the LLM names which single role the landscape is built
from, forced onto exactly four labels:

| Market | Player type |
|---|---|
| B2C | `Brand / Marketer` |
| B2B physical product | `Manufacturer` |
| B2B technology / platform | `Solution Provider` |
| B2B service | `Service Provider` |

`Contract Manufacturer` is never one of them. Every company in the market
gets the same role, so the quadrant compares like with like.

Logged up front:

```
Step 0c/6: market type = B2B | player type = Manufacturer
Step 0c/6: why B2B: purchased exclusively by industrial manufacturers...
Step 0c/6: roles present in market: Manufacturer, Technology Provider, Distributor
Step 0c/6: why this player type: technology providers and distributors only
           serve as upstream enablers or downstream channels
```

---

## 4. Step 1 — discovery in rounds (AI Mode)

One loop replaces what used to be three stages (recall, discover,
list-discover). All three asked the same question, so the later ones only
re-found known companies: measured on Silicon Carbide, recall found 118 and
the other two added **1** across 9 queries.

```
round 1: ask for 10, exclusion list = []          -> 10 new
round 2: ask for 10, exclusion list = those 10    ->  9 new
round 3: ask for 10, exclusion list = newest 40   ->  7 new
...
3 consecutive empty rounds -> exhausted, stop
```

### The round query

**System** (372 chars):

```
You identify the BRANDS sold in a market and the COMPANY behind each brand.
No invented names, no media, associations, research firms or geo labels.
Return compact JSON only:
{"companies":[{"brand":"...","company":"...","website":"https://...",
"headquarters":"City, Country","ownership":"...",
"ownership_confidence":"high|medium|low","verdict":"...","why_related":"..."}]}
```

**User** (~3 KB, seven parts in this order — constraints after the template
are applied less reliably):

```
Market: "Global Water Bottles Market"

Give me 10 BRANDS sold in this market, each with the company behind it.

WHO QUALIFIES:
A qualifying company's PRIMARY business must make it a Manufacturer in this
market. That is what it IS, not something it also does.

STRICTLY EXCLUDE, even if related to this market:
- Consultancies, market-research firms, news outlets and industry
  associations — reporting on or advising a market is not operating in it.
- Distributors and resellers — they carry other companies' product.
- CONTRACT MANUFACTURERS, OEM/ODM makers, white-label and private-label
  producers — they build to another company's specification and own no brand
  of their own here. If a company's business is making products sold under
  SOMEONE ELSE'S brand, EXCLUDE it and name the brand owner instead.
- Equipment and materials suppliers — they sell TO this market, not IN it.
- A parent that does not itself sell in THIS market (name the operating
  subsidiary instead).
If unsure, EXCLUDE.

Do NOT repeat any of these (including subsidiaries, aliases or former names):
- Cello
- Milton
...and 106 more already-collected companies. Prefer smaller, regional or
specialist companies not yet named.

FIELD RULES:
- brand: the product / consumer-facing BRAND name as buyers know it
  (e.g. "Milton"). A brand is NOT a distributor and NOT a product category.
- company: the legal entity that OWNS, manufactures under, or is responsible
  for that brand (e.g. "Hamilton Housewares Pvt. Ltd."). NEVER a distributor,
  reseller or channel partner. If a contract manufacturer merely makes the
  product, the brand OWNER still goes here.
- website: the real official company domain. NEVER LinkedIn, Bloomberg,
  Crunchbase or Wikipedia.
- headquarters: "City, Country" — one global HQ, with the state for US
  companies. NEVER "Global", "Worldwide", a bare region, or "50+ countries".
- ownership: "Independent", or "Acquired by <Parent>" / "Subsidiary of
  <Parent>". State an acquisition ONLY from an official site, acquisition
  announcement, investor-relations page, filing or reputable source. NEVER
  infer one from similar names.
- ownership_confidence: high = official source; medium = multiple reputable
  sources; low = weak/indirect.
- verdict: "in_market" only if it genuinely operates here. NEVER guess this
  field. Include the company ONLY if verdict is "in_market".
- why_related: one sentence naming what it actually makes in THIS market.

An empty string is CORRECT and preferred whenever you do not genuinely know
a value. A wrong value is much worse than an empty one.
```

Encoded URL: **~3.9 KB** of the 7,800 limit, even with 100+ exclusions.

### Why these choices

- **Brand-first.** Asking "what companies exist?" produced rows where Brand
  and Company were the same string, which tells a reader nothing. Asking for
  the brand *then* its owner gives `Milton → Hamilton Housewares Pvt. Ltd.`
- **10 per round.** 1 wastes pacing (~20 s each); 25+ truncates the answer
  and the tail companies vanish silently.
- **Exclusion list every round.** AI Mode is stateless — "give me 10 more"
  means nothing on its own. Capped at 40 names / 1,500 chars, newest first,
  with the omitted count disclosed *and a strategy*.
- **Exclusions carry reasons.** A bare label lets the model apply its own
  looser definition; the parentheticals do the real work.

### Stopping

| Cause | Evidence | Response |
|---|---|---|
| Rate limited | `/sorry/`, "unusual traffic" | cool off 5 min |
| AI-response quota | "reached the request limit" | cool off 15/30/45 min |
| Model refused | "no response available", "something went wrong" | reset session, retry |
| Genuinely exhausted | 3 empty rounds | stop |

Blocked rounds are counted **separately** and never reported as "exhausted".

> A live run once stopped at 10 companies claiming exhaustion while actually
> hitting the AI-response quota — the loop was catching every exception as an
> empty round.

---

## 5. Steps 4 & 6 — verification (AI Mode, chunked)

Discovery is deliberately generous; precision is recovered in two passes.

| Pass | Step | Chunk | Evidence available |
|---|---|---|---|
| First | 4 | 12 | name, website, snippet |
| Final | 6 | 10 | + Summary, categories (after gap fill) |

Criteria block (~1 KB), generated from the market analysis — never
hand-written per market:

```
You are a strict market-landscape verifier. Decide KEEP or DROP for each company.
Market: Global Water Bottles Market
Required type: Manufacturer
KEEP: companies whose PRIMARY business in this market makes them one of: Manufacturer.
Judge by the company's PRIMARY business — what it IS, not something it also does.
DROP: consultancies, market-research firms, news/media outlets and industry
associations, pure holding companies, governments, country/city/geo labels.
A parent that does not itself sell in THIS market is a DROP.
CONTRACT MANUFACTURERS, OEM/ODM makers and white-label producers are a DROP.
If you are not sure the company genuinely operates in this market, DROP.
In the JSON role field return exactly one of: Manufacturer.
```

Then per company: `in_market`, `builds_or_owns`, `role`, `fits_criteria`,
`confidence` 0-100, `reason`.

**Gated in code**, never trusted implicitly: `verify_should_keep()` requires
`in_market AND builds_or_owns AND confidence >= 70` and a matching role. An
unparseable chunk **fails closed** — a parse failure is no evidence, and
treating no-evidence as approval is how research firms reach a final report.

---

## 6. Step 5 — gap fill (DeepSeek)

Fills whatever discovery left empty. Routed to DeepSeek because the prompt is
~12 KB of field rules — far past what a search URL can carry.

Because Step 1 now collects `headquarters`, `ownership` and the brand during
discovery, this step usually has little left to do.

Six contact fields (Contact Person, Role, Email, LinkedIn, Office No.) are
**not researched at all**. Demanding a complete row makes the model invent
values — measured elsewhere, 94% of one email column was
`info@<own-domain>`. `scripts/check_fabrication.py` audits a finished market
for exactly that pattern.

---

## 7. Step 6c — scoring (AI Mode)

**Axes are fixed for every market**; only the 5 parameters under each change:

- **X = Product Strength**
- **Y = Business Strength**

The 5+5 parameters are generated per market by DeepSeek (`method=llm` is
mandatory — the generic catalog fallback raises rather than silently
producing untuned parameters).

One consolidated query per axis (185 chars):

```
Provide a single, consolidated Product Strength score out of 100 for Milton
by calculating the unweighted average of these 5 parameters:
Product Portfolio Breadth
Material & Build Quality
...
Reply with just the number out of 100.
```

Two queries per company, run strictly serially. An unparseable answer leaves
the row **unscored for retry** — never written as 0, because a CAPTCHA is
missing data, not a company with no strength.

### Normalisation — row level, independent

```
both >= 65          -> unchanged
both < 65           -> scale both by 65/min(x,y), cap 100   (ratio preserved)
exactly one < 65    -> raise that one to 65, leave the other
```

Then `Overall = round((X + Y) / 2)` from the **normalised** pair — never
`max(original, 65)`. One company's score can never affect another's.

| Raw | Normalised | Overall |
|---|---|---|
| 50 / 40 | 81.25 / 65 | 73 |
| 52 / 78 | 65 / 78 | 72 |
| 80 / 90 | unchanged | 85 |

---

## 8. Step 7 — output

Report columns:

```
Brand    | Company                                | Role         | Quadrant | X | Y | Overall | Found in
Milton   | Hamilton Housewares Pvt. Ltd.          | Manufacturer | Leaders  |90 |88 |   89    | Mumbai, India
XYZ      | ABC Corporation (acquired by DEF Corp) | Manufacturer | ...
Cello    | Cello World Ltd.                       | ...
Borosil  | Cello World Ltd.                       | ...
```

- **Brand** — the product brand the market knows
- **Company** — the entity behind it, with `(acquired by X)` when verified
- One company can own several brands, so it may appear in several rows
- **Found in** — one clean HQ location
- `Role` is the market's single player type, identical on every row

The 26-column `Landscape` sheet is still written for the fuller record.

**Never in user-facing output:** the words "crawled", "AI generated",
"LLM generated", or the internal per-role reasons (kept for audit only).

---

## 9. Operating notes

- **One market at a time.** Two pipelines on one IP is the direct cause of
  repeated throttling.
- **Keep the Chromium window visible.** A CAPTCHA can only be solved in a
  visible window, and MV3 extensions do not run reliably headless.
- **Pacing is the only real lever.** `GOOGLE_AI_MODE_QUERY_DELAY=20` (25 for
  long unattended runs).
- **Budget.** ~2 queries per company for scoring dominates: 200 companies
  ≈ 400 paced queries ≈ 2 hours.
- **Quota is per IP.** Clearing cookies does not clear it; only waiting does.
  A soured *session* (repeated "something went wrong") IS fixed by the
  automatic cookie clear + browser relaunch.
- **Resume is free.** Re-run the same command; completed steps skip from the
  checkpoint.

---

## 10. Checklist

```
BEFORE A RUN
[ ] pip install patchright   (NOT playwright)
[ ] GOOGLE_AI_MODE_ENABLED=true, HEADLESS=false, QUERY_DELAY=20
[ ] Only one market running
[ ] Chromium window visible for CAPTCHAs

WHAT GOOD LOOKS LIKE
[ ] Step 0c logs market type, player type, and WHY
[ ] Rounds show +N per round, declining, then 3 empty -> "exhausted"
[ ] Verify keeps most of what discovery found (not 2 of 24)
[ ] Brand != Company on most rows
[ ] X/Y between 65 and 100

WHEN IT STOPS
[ ] "exhausted"  -> real ceiling, market has no more companies
[ ] "blocked"    -> quota/CAPTCHA, wait and resume
[ ] Check the log for "request limit" before believing "exhausted"
[ ] scripts/check_fabrication.py after a market completes
```
