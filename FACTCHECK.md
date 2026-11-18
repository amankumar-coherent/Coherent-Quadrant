# Chart fact-check (step 8a)

How the pipeline re-checks the 20 chart companies after the report is built: what it asks,
how it judges each supporting point, which verdicts it acts on by itself, how a corrected
sentence is rewritten and put back into the report, and what it deliberately leaves alone.

Code: `scripts/factcheck_chart.py` (asks) and `src/vendor_intel/pipeline/factcheck.py` (decides).
Output: `<market>/_pipeline/factcheck/` (raw answers) and `_pipeline/factcheck_review.json` (decisions).

Run it on its own against a finished market:

```bat
.venv\Scripts\python.exe scripts\factcheck_chart.py --market "X Market" --country india --browsers 10
```

Skip it in a pipeline run with `--no-factcheck` (the log then says so, and VERIFY records the
check as not complete).

---

## 1. Why it exists

Every number in the report came from one AI Mode answer. The fact-check asks a **second time**,
with a different prompt, and only about things that can be checked: a date, a figure, a named
client, a contract, a certification. Where the second answer contradicts the first and the
contradiction is well sourced, the report is corrected.

It runs **after** the report is written, because it checks what the report actually says.

---

## 2. What gets checked

Only **chart companies** (`chart_rows`: `on_chart`, sorted by Overall). The long tail is not
fact-checked — it carries no per-parameter evidence, only a strength bubble.

For each of them, two kinds of question.

### 2a. The company itself — one query

`STATUS_SYS` asks for the company as a whole and requires compact JSON:

| Field | Meaning |
|---|---|
| `operating` | `active` / `in_administration` / `liquidated` / `dissolved` / `acquired_absorbed` / `renamed` / `unknown` |
| `event` | the event and date, when not active |
| `current_name` | the name it trades under today |
| `owner` | parent or majority owner today, empty if independent |
| `owner_since` | year |
| `hq` | its own head office, `"City, Country"` |
| `main_product` | what it mainly sells |
| `scope` | `core` / `adjacent` / `out` for this market |
| `scope_reason` | one sentence |
| `evidence` | one factual sentence naming the source |

The question carries the market definition (600 chars), the core-player description (500) and
the adjacent segments (300), so "core or adjacent" is judged against **this** market, not a
general idea of the industry.

**The scope test follows the market brief.** When `scope_test` is `own_product_line`, the
wording is swapped for a stricter one: core means the company *makes and sells the product
itself under its own name*; a company that buys, converts for others, distributes or resells
it is adjacent. An `assert` guards that swap — if `STATUS_SYS` is reworded and the replacement
no longer matches, the run stops rather than silently asking the generic question.

### 2b. Each supporting point — 5 per query

`specific_claims` picks the points worth checking. A point qualifies when `_SPECIFIC` matches:

```
a digit, a quotation mark, contract, awarded, partner, acquir, launched, won,
selected, certif, ISO, approved, framework, customer, client, integrat
```

So *"won a 12 MLD ZLD contract at Hawassa Industrial Park in 2023"* is checked;
*"has strong engineering capability"* is not — there is nothing in it to verify.
`"Not available"` is never checked.

`CLAIM_SYS` then asks for a verdict per claim:

| Verdict | Meaning |
|---|---|
| `correct` | a source states it |
| `incorrect` | a source contradicts a fact — date, number, name, title, client, status — **or the claim belongs to another company** |
| `unverified` | no source states that detail |

For `incorrect` it must return `corrected`: **the same sentence with only the wrong detail
fixed**. For `unverified` it must name the unconfirmed detail in `note`. Both must give
`source`. "Never guess" is in the prompt.

---

## 3. How the work is split and resumed

- Claims go in **batches of 5**; one company's claims can be spread over several browsers
  (`{"company", "part", "parts"}` — part 0 also asks the status question, and each part takes
  every `parts`-th batch).
- Answers are saved after **every batch**, so a stopped run keeps what it checked.
- `merged_findings` unions every browser's file per company: the first status found, plus the
  union of claim verdicts. Keeping only the biggest file would throw away the other browsers'
  verdicts.
- A company is `finished` when it has a status **and** every specific claim has a verdict.
  `missing()` lists the rest — that is what VERIFY's "chart fact-check complete" line reads.
- **A claim is not re-asked once checked.** `was_checked` also treats a sentence that is ≥ 0.80
  similar to a checked one as already checked, so a correction that changed one detail does not
  cause the whole sentence to be asked about again.
- `applied_replacements` collects every `replace` text already written by this step or the
  analyst review; those sentences are skipped entirely.

---

## 4. Which verdicts the pipeline acts on by itself

AI Mode cites directory sites and can contradict itself, so **only these five decisions apply
automatically**. Everything else is written to `findings.md` as a lead for a human.

`build_review` writes `_pipeline/factcheck_review.json` with five lists:

### `exclude`
`operating` is `liquidated`, `dissolved` or `in_administration` **and** a dated event is given.
An acquired company that still trades is **not** excluded.

### `scope`
`adjacent` → off the chart (stays in Other Noticeable Players unless the brief sets
`adjacent_policy: exclude`). `out` → excluded from the report.

### `ownership`
An owner is recorded only when:
- the company is not already labelled by step 3c or the analyst review, **and**
- `company_facts.owner_entry` accepts it, **and**
- `owner_since` contains a real year (`(19|20)\d{2}`).

### `hq`
Only when the **country** differs from the HQ the report showed at the time of the check —
not the city. Country names are normalised first (`usa`, `united states`, `u.s.` → `us`;
`uk`, `england`, `great britain` → `uk`), so a different spelling is not read as a different
country. A placeholder (`"Country"`, `"unknown"`, `"n/a"`) counts as no country at all, so it
can never replace a real HQ — four Brazilian companies once came back as `"Jundiaí, Country"`.

### `corrections`
Covered in full below.

**A decision stays once made.** Entries for companies no longer on the chart are carried over
from the previous `factcheck_review.json`; dropping them would put an excluded company straight
back on the chart.

---

## 5. How a supporting point is corrected

`_claim_decision` is the gate. A correction is produced **only** when every one of these holds:

1. **Verdict is `incorrect`.** `unverified` never changes the report — not being able to find a
   source is not evidence that something is wrong.
2. **A source is given**, and it is not a banned source. `_bad_source_rx` is built from four
   config lists: `estimate_sites.txt` (RocketReach, ZoomInfo, Crunchbase, …), `directory_sites.txt`,
   `employee_review_sites.txt` and `research_publishers.txt`. A "correction" resting on a
   directory page is thrown away. The *corrected sentence* is checked against the same list.
3. **The edit is small.** `difflib.SequenceMatcher(claim, corrected).ratio() >= 0.75`. Below
   that it is a rewrite, not a fix of one detail, and it is rejected.
4. **No other check of the same company backs the old figure.** Every number removed by the
   edit (`_NUM`) is looked for in that company's other claims — in the claim text where the
   verdict was `correct`, in the corrected text otherwise. If another verdict still supports
   the old number, the correction is dropped as self-contradictory.
5. **The corrected sentence is rewritten in house style** before it enters the report:
   `_house_style` runs `company_facts.clean_artifacts` (citation leftovers, footnote markers,
   raw URLs, page furniture) and then `primary_research_wording.to_primary` — the same tone
   pass step 7 applies. So a fact-check sentence reads exactly like every other sentence:
   research-team voice, no hedges, gaps in the house wording.
6. **The result differs from the original.** If the "fix" is identical to the claim, nothing
   is written.

### A claim that belongs to another company
If `note` or `source` matches `_OTHER_COMPANY` — *"belongs to"*, *"another company/vendor/firm"*,
*"different company"*, *"not a product of"* — the point is **removed** rather than corrected:
the correction is written with `"replace": ""`.

### How the replacement reaches the report
`company_status.apply_corrections` does an **exact `find` → `replace`** in that company's
evidence across every `param_detail_prescored*.json`, then the report is rebuilt. Three details
make it reliable:

- **Idempotent.** Once replaced, `find` no longer occurs, so re-running changes nothing.
- **Any of the company's names works.** Sidecars key a company by whichever name scored it
  (legal name, deduped variant or brand); `company_aliases` maps them together.
- **House wording is mapped back.** A correction written against the *report* text carries the
  client-facing lead (`"…, as per our analysis"`); the evidence files keep the pipeline's own
  phrasing. `house_wording.to_legacy` converts the report form back so the sentence is found.
- Each correction reports **how many places changed**. `0` means not found or already applied,
  and the caller prints it — a mistyped entry is never silently ignored.

---

## 6. The re-run loop

When `write_review` finds the decisions differ from the saved ones, the pipeline **re-runs
itself from saved work**:

1. steps 3b/3c drop or move the companies the decisions name;
2. the chart refills its vacated slots from core companies (`refill_top_by_quadrant(keep_all=True)`
   — every surviving chart company is kept, only the empty slots are filled);
3. step 5 gathers evidence for the new entrants;
4. step 7b applies corrections, owners and HQs;
5. step 8 rebuilds the report;
6. step 8a checks **only the new chart entrants**.

Up to 8 passes (`QUADRANT_FACTCHECK_MAX_PASSES`). Three were once too few for a market with a
thin core: every refill brought a company the scope check called core and the fact-check called
adjacent, and the run ended with the last decision unapplied. Each pass is cheap because
everything already checked is cached.

The loop ends when a pass produces the same decisions as the one before it.

---

## 7. Precedence

```
analyst_review.json   (a person)        — always wins
      ↓
factcheck_review.json (this step)       — automatic layer
      ↓
auto_review.json      (steps 3b / 3c)
```

`_pipeline/analyst_review.json` overrides anything here. A `keep` entry undoes an automatic
exclusion; an `ownership` entry replaces an automatic owner label; a `scope` entry overrides
the scope verdict. That is the sanctioned way to overrule the fact-check — never by editing the
report HTML or JSON.

---

## 8. What it will not do

- **Judge a vague point.** No figure, date or name means nothing to check.
- **Act on `unverified`.** Silence from a source is not a contradiction.
- **Act on a directory, estimate, employee-review or research-publisher source.**
- **Accept a rewrite.** Below 0.75 similarity the "correction" is rejected.
- **Overrule itself.** If another verdict for the same company supports the old figure, no change.
- **Change a city.** Only a differing HQ *country* is acted on.
- **Exclude an acquired company that still trades.** It is labelled, not removed.
- **Re-check what it already checked**, including a sentence a fix has since altered.

---

## 9. Files

| Path | What it holds |
|---|---|
| `_pipeline/factcheck/findings*.json` | one file per browser: raw status and claim verdicts |
| `_pipeline/factcheck/findings.md` | the review list, company by company, for a person to read |
| `_pipeline/factcheck/browser_*.log` | per-browser run log (`saved <company> <n>`, `finished`) |
| `_pipeline/factcheck_review.json` | the five automatic decision lists |
| `_pipeline/analyst_review.json` | a person's overrides — wins over everything above |
