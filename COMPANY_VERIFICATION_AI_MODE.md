# Verifying Companies in Chunks via Google AI Mode

How this pipeline decides whether a discovered company **actually belongs in
a market**, how the work is split into chunks, and how the verification
query is written so AI Mode answers it reliably.

Companion to the discovery guide (that one is *queries in, companies out*).
This one is only about **candidates in, keep/drop out**.

Reference implementation:
- `src/vendor_intel/pipeline/chatgpt_expand.py`
  - `verify_criteria_prompt()` — the market-driven criteria block
  - `gpt_verify_market()` — Step 4, first pass
  - `gpt_final_verify_rows()` — Step 6, second pass
  - `verify_should_keep()` — the code-side gate
  - `_fits_ai_mode()` — routing guard

---

## 1. Why verify at all, and why twice

Discovery is deliberately generous: a broad query returns market-research
firms, industry associations, parent holding companies and retailers
alongside real participants. Precision is recovered afterwards, in two
passes at different points in the pipeline:

| Pass | Step | Runs on | Chunk | Evidence available |
|---|---|---|---|---|
| First verify | 4 | discovered candidates | **12** | name, website, snippet, claimed role |
| Final verify | 6 | filled rows | **10** | + Summary, Core Categories, Specialty Focus |

The second pass is not redundant. Step 5 fills in each company's summary and
categories, so the final pass judges on real evidence rather than a search
snippet. Measured on Global Daily Multivitamins: the first pass kept 359 of
400 candidates, the final pass reduced that to ~222.

---

## 2. The shape of the whole thing

```
candidates (name, website, snippet)
        ↓
split into chunks of 10-12
        ↓
per chunk: criteria block + JSON rows  ->  one AI Mode query
        ↓
rendered page text -> strip echo -> json.loads
        ↓
per-company verdict -> verify_should_keep() gate in CODE
        ↓
checkpoint the offset, then next chunk
```

Three properties of AI Mode drive every decision below:

1. **Stateless.** Each chunk is a self-contained question. Nothing carries
   over, so the criteria block is repeated in every request.
2. **The whole prompt rides in the URL.** Google 400s past ~8 KB, so chunk
   size and payload width are a budget, not a preference.
3. **It is a search box, not a chat endpoint.** A prompt long enough to be
   truncated loses its JSON template and returns *"Something went wrong, and
   an AI response wasn't generated."*

---

## 3. Why chunks of 10-12, not 1 and not 50

| Chunk size | Behaviour |
|---|---|
| 1 company | correct, but ~10 s of pacing each — 300 companies = ~50 min |
| **10-12** | reliable; whole prompt encodes to ~2.2-5.3 KB of URL |
| 25+ | the answer truncates and the tail companies silently vanish |

The limits come from opposite ends. Small chunks waste paced queries; large
chunks overflow both the answer and the URL.

Measured on a real final-verify chunk:

```
SYSTEM  1,281 chars
USER      546 chars   (2 companies)
URL     2,248 chars   (limit 7,800)
```

At 10 companies the payload is ~2.5 KB, so the URL lands near 5 KB — inside
the limit with headroom. That is why `chunk_size = 10` for the final pass
(wider payload: Summary + categories) and `12` for the first pass (narrower:
snippet only).

**Truncate the payload fields, not the chunk.** `Summary` is capped at 180
chars and `snippet` at 280. One verbose company must not push the rest of
its chunk out of the URL.

---

## 4. Anatomy of the verification query

Two parts: a **criteria block** (identical for every chunk in a market) and
a **rows payload** (this chunk's companies as JSON).

### 4.1 The criteria block is generated from the market, never hand-written

`verify_criteria_prompt()` builds it from that market's own Stage 1 analysis
(B2B/B2C plus dynamically generated participant categories). One template
serves any market:

```
You are a strict market-landscape verifier. Decide KEEP or DROP for each company.
Market: Global Daily Multivitamins Market
Required type: Brand / Marketer
KEEP: companies whose brand is sold in this market, or who manufacture and
market the product under their own name.
Judge by the company's PRIMARY business — what it IS, not something it also does.
DROP: consultancies, market-research firms, news/media outlets and industry
associations (reporting on or advising a market is not operating in it), pure
holding companies, governments, country/city/geo labels, and any company that
does not genuinely operate in this market.
A parent that does not itself sell in THIS market is a DROP — the operating
subsidiary is the company that belongs here.
If you are not sure the company genuinely operates in this market, DROP.
Expected role label: Brand / Marketer.
```

For a B2B market the same code emits that market's own roles instead:

```
Required type: Manufacturer OR Service Provider
KEEP: companies whose PRIMARY business in this market makes them one of:
Manufacturer OR Service Provider.
...
In the JSON role field return exactly one of: Manufacturer, Service Provider.
```

Four techniques carry the weight:

- **`Required type:` states the target explicitly** rather than leaving the
  model to infer it from the market name.
- **`PRIMARY business — what it IS, not something it also does`** stops
  manufacturers who also distribute from being kept as distributors.
- **Exclusions carry reasons.** *"reporting on or advising a market is not
  operating in it"* rejects research firms far more reliably than naming the
  category alone.
- **The parenthetical closes a loophole.** *"A parent that does not itself
  sell in THIS market is a DROP"* is the single line that removes holding
  companies.

Earlier versions short-circuited to hand-written prompts when the market
name contained `semiconductor`, `packaging` or `glp-1`. That cannot scale
past those few markets and silently ignored the market analysis, so it was
removed.

### 4.2 Ask for a verdict per company, with a confidence

```
This is a second pass after columns were filled. Use Summary and categories.
For EACH company return one result. Never skip a name.
When unsure, fits_criteria=false.
Return compact JSON only:
{"results":[{"Company":"...","in_market":true|false,"builds_or_owns":true|false,
"role":"Solution Provider|Brand|Marketer|Reseller|Retailer|Distributor|Media|Other",
"fits_criteria":true|false,"confidence":0-100,"reason":"..."}]}
```

- **`For EACH company return one result. Never skip a name.`** Without it,
  the model quietly returns 7 results for 10 companies, and the missing
  three are indistinguishable from rejections.
- **`When unsure, fits_criteria=false`** makes ambiguity fail closed.
- **`reason`** forces justification, which measurably improves the verdict.
- **Four separate signals** rather than one keep/drop flag: `in_market`,
  `builds_or_owns`, `fits_criteria` and `confidence` can each be gated
  independently in code.

### 4.3 The rows payload

```json
[{"Company": "Centrum",
  "Website": "https://www.centrum.com",
  "Distribution Type": "Brand / Marketer",
  "Core Categories": "Multivitamins",
  "Specialty Focus": "Adult daily multivitamins",
  "Summary": "Consumer multivitamin brand owned by Haleon."}]
```

Send only the fields that inform the decision. Employees, contact details
and geography do not help a keep/drop call and cost URL budget.

---

## 5. Never trust the reply: the code-side gate

The prompt is a request, not a guarantee. `verify_should_keep()` re-checks
every rule:

```python
def verify_should_keep(*, in_market, role, builds_or_owns, confidence,
                       expected_role, min_confidence=70):
    if not in_market or not builds_or_owns:
        return False
    if int(confidence or 0) < int(min_confidence):
        return False
    ...  # role must match the expected role family for this market
```

`VERIFY_MIN_CONFIDENCE = 70`. A company the model kept at 55 confidence is
dropped: on a 400-company landscape, a plausible-but-wrong company costs
more than a missing one.

---

## 6. Fail closed on an unparseable chunk

```python
if not isinstance(results, list) or not results:
    _log(f"substep 4a.{idx}: empty/invalid verify JSON — DROP chunk (fail closed)")
```

An unreadable answer drops the whole chunk rather than keeping it. This is
deliberate: a parse failure is *no evidence*, and treating no-evidence as
approval is how research firms and geo labels reach a final report.

Because the offset is checkpointed per chunk, a dropped chunk can be re-run
later without redoing the rest.

---

## 7. Checkpoint every chunk

```python
ckpt.bump("6_final", f"6a.{idx}",
          progress={"final_verify_offset": i + chunk_size,
                    "final_verify_chunk": idx})
```

A run *will* be interrupted — a CAPTCHA, a stop, a machine restart. The
offset makes resume exact:

```
substep 6a: final QA on 302 rows as Brand / Marketer in 31 chunk(s) (resume offset=230)
substep 6a.24: final-verify chunk 24/31…
```

Chunks 1-23 are not re-queried. At ~10 s per paced query that is the
difference between resuming in seconds and losing 40 minutes.

---

## 8. Routing: verify belongs on AI Mode, gap-fill does not

Both verify passes go through AI Mode. A `_fits_ai_mode()` guard measures
the **actual encoded URL** rather than guessing from character count:

```python
encoded = len(build_url(prompt))
if encoded <= MAX_URL_CHARS - 200:
    return True   # AI Mode
```

Percent-encoding inflates by only ~7%, so:

| Call | Prompt | URL | Routes to |
|---|---|---|---|
| Step 2 discovery query | 60 | 106 | AI Mode |
| Step 6 scoring query | 186 | 241 | AI Mode |
| Step 1 recall | 1,410 | 1,541 | AI Mode |
| **Step 6 final-verify chunk** | 4,984 | 5,339 | **AI Mode** |
| Step 5 gap-fill | 12,000 | truncated | API backend |

> **Two bugs lived here.** First, gap-fill's ~12 KB prompt was pushed into
> the search box and returned *"Something went wrong"* — truncation had taken
> the JSON template with it. Then the fix over-corrected to a fixed
> 1,800-char cap, which needlessly diverted the 4,984-char verify chunks to
> the API. Measure the encoded URL; do not guess from length.

---

## 9. Checklist

```
PROMPT
[ ] Generate the criteria block from the market analysis, never hand-write
[ ] State "Required type:" explicitly
[ ] Anchor on PRIMARY business ("what it IS, not what it also does")
[ ] Give every exclusion a REASON, not just a label
[ ] Close the parent/subsidiary loophole explicitly
[ ] "For EACH company return one result. Never skip a name."
[ ] "When unsure, fits_criteria=false" — ambiguity fails closed
[ ] Ask for a reason and a 0-100 confidence
[ ] End with the explicit JSON template

CHUNKING
[ ] 10-12 companies per chunk; never 1 (pacing) or 25+ (truncation)
[ ] Cap wide fields (Summary 180, snippet 280) — not the chunk
[ ] Send only decision-relevant fields
[ ] Verify the encoded URL fits; do not guess from char count

VALIDATION
[ ] Re-check every rule in code (verify_should_keep)
[ ] Enforce a confidence floor (70)
[ ] Match names back by a normalised key, not a raw string
[ ] Fail CLOSED on an unparseable chunk — drop, never keep

LOOP
[ ] Checkpoint the offset after every chunk
[ ] Resume from the offset; never re-query completed chunks
```
