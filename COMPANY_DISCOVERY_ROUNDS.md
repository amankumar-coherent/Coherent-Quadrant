# Finding Companies in Rounds: One Loop, Not Three Stages

How company discovery **should** work in this pipeline: a single loop that
asks for a small batch, records what came back, and asks again — carrying
everything already found in every request.

This replaces the current three separate stages, which all do the same job
and therefore keep returning the same companies.

---

## 1. The problem being fixed

Today the pipeline finds companies in three places:

| Stage | What it asks | Measured on Silicon Carbide |
|---|---|---|
| Step 1 recall | "list companies you know in this market" | **118 companies** |
| Step 2a discover | "find companies in this market" | 0 new |
| Step 2g list-discover | 13 template queries: "top companies in X", "leading X worldwide"… | **+1 across 9 queries** |

All three are the same question in different clothes. Once recall has taken
the obvious answers, the later stages re-ask and Google returns the same
well-known names, which are filtered out locally as duplicates.

The visible symptom is a run that looks busy — every query succeeds, no
CAPTCHAs, `JSON parse OK` throughout — while `+0` scrolls past for twenty
minutes. Roughly 35 paced queries produce almost nothing.

> **This is not a prompt bug.** Adding an exclusion list to the 2g queries
> was tried and changed nothing, because the constraint is real: Silicon
> Carbide has perhaps 150 genuine participants, and recall already found 118
> of them. No amount of asking invents companies that do not exist.

---

## 2. The replacement: one loop, N rounds

```
round 1:  ask for 10 companies, exclusion list = []
            -> 10 new     (total 10)
round 2:  ask for 10 more, exclusion list = those 10
            -> 9 new      (total 19)
round 3:  ask for 10 more, exclusion list = newest 40 of 19
            -> 7 new      (total 26)
...
round N:  -> 0 new
round N+1:-> 0 new
round N+2:-> 0 new   => three empty rounds: market exhausted, STOP
```

One prompt shape. One exclusion list. One stopping rule.

### Why batches of 10

| Batch size | Behaviour |
|---|---|
| 1 | correct but ~20 s of pacing each — 300 companies = 100 min |
| **10** | reliable; the answer never truncates, the URL stays ~2 KB |
| 25+ | the answer truncates and the tail companies vanish silently |

Ask for fewer per round than you want in total, and loop. The extraction
guide measured the same ceiling: 10 per request is reliable for a wide
schema, 20 truncates.

### Why "give me 10 MORE" needs the exclusion list every time

AI Mode is **stateless**. There is no conversation, so "10 more" means
nothing on its own — the request must carry the names already collected:

```
Give me 10 companies in the Global Silicon Carbide Market.
...
Do NOT repeat any of these (including subsidiaries, aliases or former names):
- Wolfspeed
- Coherent
- onsemi
...and 106 more already-collected companies. Prefer smaller, regional or
specialist companies not yet named.
```

---

## 3. The round prompt

Seven parts, in this order. Constraints stated *after* the output template
are applied less reliably, so the template goes last.

```
1. Market            Market: "Global Silicon Carbide Market"
2. The ask           Give me 10 companies.
3. Who qualifies     PRIMARY business must make them a Manufacturer in
                     this market — what they ARE, not what they also do.
4. Typed exclusions  with REASONS, not just labels
5. Name exclusions   newest ~40, char-capped, omitted count disclosed
6. Field rules       one line per field
7. JSON template     explicit, with empty strings
```

### Part 3: anchor on the market's single player type

Step 0c already decided the player type for the whole market (see
`COMPANY_VERIFICATION_AI_MODE.md` §4.1). The round prompt asks for exactly
that one role, so discovery and verify cannot disagree:

```
A qualifying company's PRIMARY business must make it a Manufacturer in this
market: it physically produces and sells silicon carbide substrates, devices
or components under its own name. That is what it IS, not something it also
does.
```

### Part 4: exclusions need reasons

```
STRICTLY EXCLUDE, even if related to this market:
- Consultancies, market-research firms, news outlets and industry
  associations — reporting on or advising a market is not operating in it.
- Distributors and resellers — they carry other companies' product.
- Equipment and materials suppliers — they sell TO this market, not IN it.
- A parent that does not itself sell in THIS market (name the operating
  subsidiary instead).
If unsure, EXCLUDE.
```

The parentheticals do the work. *"They sell TO this market, not IN it"*
removes a whole class the bare label "supplier" does not.

### Part 6-7: fields and template

```
FIELD RULES:
- name: the operating company's own legal or trade name.
- website: the real official domain. NEVER LinkedIn, Bloomberg, Crunchbase
  or Wikipedia.
- country: HQ country only.
- verdict: "in_market" only if it genuinely operates in this market;
  otherwise "unrelated" or "unknown". NEVER guess this field. Include the
  company ONLY if verdict is "in_market".
- why_related: one sentence naming what it actually makes in THIS market.

An empty string is CORRECT and preferred whenever you do not genuinely know
a value. A wrong value is much worse than an empty one.

Reply with ONLY a JSON array, no markdown fences and no commentary:
[{"name": "", "website": "", "country": "", "verdict": "", "why_related": ""}]
```

---

## 4. The exclusion list is a budget, not a list

The whole prompt rides in `?q=` and Google 400s past ~8 KB. The exclusion
list is the only part that grows per round, so it must be capped by
**characters**, not just by count.

> Measured: 120 real company names is ~4.7 KB of JSON, which pushed the URL
> to 8,486 chars. `build_url` truncated it — taking the JSON template with
> it — and AI Mode answered *"Something went wrong."*

```python
_MAX_EXCLUDED_IN_PROMPT = 40      # newest first
_MAX_EXCLUSION_CHARS    = 1500    # budget for the block alone
```

Three details that make the cap work:

- **Newest first.** A repeat is likeliest among names just returned.
- **Disclose the omission with a strategy.** *"...and 106 more; prefer
  smaller, regional or specialist companies"* keeps the model productive far
  longer than silent truncation.
- **Trimming is safe.** The prompt list is only a hint; the authoritative
  duplicate guard is the local `seen` set checked against full history, so a
  trimmed name that comes back is dropped in code.

---

## 5. Stopping: three empty rounds, not one

An empty round is normal — a market thins out. Three consecutive empty
rounds means the market is genuinely exhausted.

```python
empty_streak = 0
while len(found) < target and rounds < max_rounds:
    batch = ask_round(market, player_type, excluded=found)
    new = [c for c in batch if dedupe_key(c) not in seen]
    empty_streak = 0 if new else empty_streak + 1
    if empty_streak >= 3:
        log(f"3 empty rounds — market exhausted at {len(found)}")
        break
```

**Never stop on the first empty round**, and never conflate "exhausted" with
"blocked". An empty result has three causes needing opposite responses:

| Cause | Evidence | Response |
|---|---|---|
| Rate limited | `/sorry/`, "unusual traffic" | cool off 5+ min |
| AI-response quota | "reached the request limit for AI responses" | cool off 15+ min |
| Model refused | "no response available", "something went wrong" | reset session, retry now |
| Genuinely exhausted | none of the above | stop |

> A run once reported *"exhausted"* while actually CAPTCHA'd. Track a
> `last_captcha_at` timestamp that a successful solve does **not** clear, and
> log the evidence with the conclusion: `"exhausted at 118 (0 CAPTCHAs this
> run)"`.

---

## 5b. Geographic rotation: the exclusion list does not fix this

The name-exclusion list stops the model repeating a **company**. It does
nothing about the model's geographic habit: asked ten times for brands in a
market, it answers with the USA, Germany and Japan every time, naming the
fifth-largest German firm before it names the largest Brazilian one. A market
can finish at 300 companies and still have never mentioned Latin America,
Africa or Southeast Asia.

So each round after the first states which regions are thin:

```
GEOGRAPHIC COVERAGE: this market's companies so far are concentrated
elsewhere. PREFER brands headquartered in: Latin America, Africa,
Southeast Asia. Only name a company that genuinely operates in this
market — do NOT invent one to satisfy a region, ...
```

Four things make this safe:

* **A nudge, not a filter.** Nothing rejects a company for sitting in a
  well-covered region. A market really can be concentrated in one place, and
  a filter would delete its actual leaders.
* **Round 1 is unsteered**, so the market shows where it naturally sits
  before anything pushes it.
* **The anti-fabrication clause is mandatory.** A geographic target is
  exactly the kind of instruction that invites an invented company; the
  prompt closes that door in the same breath as it opens the region.
* **An unrecognised HQ steers nothing.** `region_of("Global")` returns `""`
  rather than guessing, because a wrong region skews the counts and sends the
  next round to the wrong place.

The country is read from the **last** comma-separated element of the HQ
string, so `"Thousand Oaks, California, USA"` resolves to the USA and not to
an unknown country called California.

`stats["region_coverage"]` reports the final spread, so a run is *audited*
for diversity rather than assumed to have it because the steer was enabled.

---

## 6. Dedupe at three levels

Normalise before comparing, or `Wolfspeed` and `Wolfspeed Inc` are two
companies:

```python
def dedupe_key(name: str) -> str:
    raw = strip_accents(name).lower()             # Nestlé -> nestle
    raw = drop_legal_suffixes(raw)                # Inc/Ltd/GmbH/AG/Holdings
    return re.sub(r"[^a-z0-9]", "", raw)          # "One A Day" == "One-A-Day"
```

Check it in three places: within one reply, against this round's accepted
set, and against all persisted history.

---

## 7. Persist after every round

A run *will* be interrupted — a CAPTCHA, a stop, a machine shutdown. Write
the checkpoint after each round so resume is exact:

```python
ckpt.bump("discover", f"round.{n}",
          progress={"round": n, "found": len(found)},
          discovered=found)
```

At ~20 s per paced query, losing a round is cheap; losing 118 companies is
not.

---

## 8. What this replaces

| Remove | Reason |
|---|---|
| Step 1 recall (9 pages × 35) | same question as discovery |
| Step 2a discover (75 pages) | same question as recall |
| Step 2g list-discover (13 template queries) | same question again, no exclusions |

Replace all three with **one `discover_companies_in_rounds()` loop**.

Expected effect on Silicon Carbide: the same ~119 companies, found in ~12
rounds instead of ~35 near-empty queries — and the stop is *explained*
("3 empty rounds, 0 CAPTCHAs") rather than the run grinding through templates
that cannot produce anything new.

---

## 9. Checklist

```
LOOP
[ ] ONE loop, not three stages that ask the same question
[ ] 10 companies per round; never 1 (pacing) or 25+ (truncation)
[ ] Carry the exclusion list in EVERY round — AI Mode is stateless
[ ] Cap the exclusion block by CHARACTERS (~1500), newest first
[ ] Disclose the omitted count with a strategy
[ ] Stop after 3 consecutive empty rounds, never 1
[ ] Distinguish blocked / quota / refused / exhausted before stopping
[ ] Log the evidence with the conclusion
[ ] Persist after every round

PROMPT
[ ] Ask for the market's ONE player type (from Step 0c)
[ ] Anchor on PRIMARY business ("what it IS, not what it also does")
[ ] Give every exclusion a REASON, not just a label
[ ] verdict field marked "NEVER guess this field"
[ ] "" preferred over a guess — never "no field may be blank"
[ ] JSON template LAST

VALIDATION
[ ] Gate on verdict in code — never trust the category implicitly
[ ] Dedupe on a normalised key at all three levels
[ ] Reject malformed values; never repair them
```
