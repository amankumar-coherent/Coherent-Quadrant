# Google AI Mode, CAPTCHA handling, search and fact-check

This file covers four things in this pipeline:

1. How Google AI Mode is set up and used.
2. How CAPTCHAs and Google blocks are handled.
3. How a search is sent and its answer read back.
4. How the chart fact-check works, and how a wrong verdict is turned into the correct sentence.

Code:
- `src/vendor_intel/scraping/google_ai_mode.py`: browser, search, CAPTCHA and recovery.
- `scripts/factcheck_chart.py`: the fact-check questions.
- `src/vendor_intel/pipeline/factcheck.py`: the fact-check decisions and corrections.

---

## 1. Implementing Google AI Mode

### 1.1 Why a real browser
AI Mode has no API. The pipeline opens Google in a real browser, sends the prompt as a search
and reads the rendered answer. The browser is driven by **patchright** (a patched Playwright).
Plain Playwright is detected at once and gets an instant CAPTCHA, so it cannot be used instead.

### 1.2 Setup
```bat
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m patchright install chromium
```
`.env`:
```
GOOGLE_AI_MODE_ENABLED=true
GOOGLE_AI_MODE_HEADLESS=false      # visible window: needed for the extension and CAPTCHA
GOOGLE_AI_MODE_QUERY_DELAY=10      # seconds between searches per browser (+0-5 s random)
```
Self-check:
```bat
.venv\Scripts\python.exe -m vendor_intel.scraping.google_ai_mode doctor
```
It should print `extensions loaded: ['Free AI ReCaptcha Solver by Raptor ...']`.

### 1.3 One browser, one profile
- `AiModeSession` keeps **one warm browser per process** and reuses it for every query. A cold
  profile draws more CAPTCHAs, and launching takes several seconds.
- The browser is a persistent context (`launch_persistent_context`) on a profile folder:
  - default: `data/ai_mode_chrome_profile`;
  - per parallel worker: `data/ai_mode_batch_<slot>_chromium` (set through `GOOGLE_AI_MODE_PROFILE_DIR`).
- `--slots 41-50` means 10 processes, 10 profiles and 10 browsers. Each browser runs only one
  query at a time.
- Every browser call runs on one dedicated thread (`_in_worker`), because patchright objects are
  bound to the thread that created them.
- Never copy another person's `data/ai_mode_*` folders: they hold Google cookies.

### 1.4 Where the LLM is used instead
AI Mode does the research: discovery, market analysis, verification, ownership, scope, scoring
evidence, estimates and fact-check. The DeepSeek API only writes the X/Y parameters and their
definitions.

A prompt is sent in the URL, so it must stay under about 8 KB (`MAX_URL_CHARS = 7800`).
`chatgpt_expand._fits_ai_mode()` sends only oversized prompts to the API. A truncated prompt
loses its JSON template and fails.

---

## 2. CAPTCHA and block handling

### 2.1 The CAPTCHA solver (CAPTCHA Raptor)
- Ships in `extensions/captcha-raptor/`; there is no install step.
- `installed_extensions()` finds every `extensions/<name>/[extension/]manifest.json` and loads
  them with one `--load-extension=a,b` flag.
- Managed Chrome ignores `--load-extension`, so the pipeline uses **bundled Chromium** when an
  extension is present.
- Raptor solves the **image-grid reCAPTCHA** only. It cannot clear the `/sorry/`
  **"Try again later"** page, because that page has no widget to solve.
- Switches:
  - `GOOGLE_AI_MODE_BUNDLED_EXTENSIONS=false` turns the bundled extensions off.
  - `GOOGLE_AI_MODE_EXTENSIONS=path1;path2` adds more extensions.

### 2.2 What each blocked page triggers
`AiModeSession.ask()` looks at every page before reading it.

| Page Google shows | How it is detected | What the code does |
|---|---|---|
| **Image reCAPTCHA** on `/sorry/` | URL contains `/sorry/` and the page is not "Try again later" | Waits up to 30 s for Raptor to solve it, then re-issues the query. A solve does not cost a retry |
| **"Try again later"** on `/sorry/` (IP block) | `/sorry/` plus "try again later" in the page text | Closes the browser, deletes its profile, waits a growing cool-off, opens a fresh browser and re-issues the query |
| **"Unusual traffic" text** | `CAPTCHA_MARKERS` | Same as the row above |
| **"Verifying your request"** or the **"Sign in to verify / continue"** wall | `_flagged_page_showing()` | 1st and 2nd time: clear cookies and relaunch the browser. 3rd time: full profile reset. After 6 blocks that a reset did not clear, it stops, because then the IP is blocked rather than the profile |
| **Quota page**: "reached the request limit for AI responses" | `QUOTA_MARKERS` | Profile reset with a growing cool-off (`GOOGLE_AI_MODE_QUOTA_COOLOFF` × 1, 2, 3) |
| **"Something went wrong … content wasn't generated"** | `NO_ANSWER_MARKERS` | Clear cookies and relaunch twice, then a profile reset |
| **Short refusal** ("try asking something else") | `REFUSAL_MARKERS`, page text under 600 characters | Rewords the prompt ("Answer concisely. …"); after repeated refusals, resets the session, then the profile |
| **Browser crashed or closed** | patchright "target closed" or "has been closed" | Reopens the browser on the same profile and retries |

A **session reset** (`reset_session`) clears cookies and relaunches the browser, keeping the
profile on disk.

A **profile reset** (`reset_profile`) does these steps:
1. Closes the browser.
2. Kills any orphan process that still holds a lock on the profile.
3. Renames the profile folder to `<name>_<reason>_<time>`.
4. Deletes the renamed folder in the background (`GOOGLE_AI_MODE_KEEP_ARCHIVED_PROFILES=true` keeps it).
5. Opens a fresh browser.

**Limits per query.** Each query may use up to `GOOGLE_AI_MODE_MAX_RESETS` (3) recoveries. After
that it raises `AiModeCaptcha` or `AiModeUnavailable`. It still leaves a fresh browser behind
(`_fresh_before_giving_up`), so the next query does not start on the blocked page. The step that
asked then retries later, in its own retry or gap-fill round.

**Profile reset after a CAPTCHA storm.** After 5 unsolved CAPTCHAs in one run
(`_CAPTCHAS_BEFORE_PROFILE_RESET`), the profile is reset.

### 2.3 Shared pause when Google blocks the machine
Every browser runs from the same IP, so a block on one browser applies to all of them. The
pipeline therefore keeps one pause file for all browsers: `data/ai_mode_ip_backoff.json`.

- **Any block page** calls `_ip_backoff_note_block()`.
  - **Every browser** then pauses: first 1 min, then 2, 4, 8 … up to 30 min (`GOOGLE_AI_MODE_IP_BACKOFF`, `..._MAX`).
  - The pause doubles only when a block arrives after the previous pause has ended.
  - The level resets if 30 min pass with no new block.
- **During a pause** each browser is **closed**, so no blank window sits open; it reopens on its next search.
- **When the pause ends**, only **one** browser tests Google first (`probe_until` / `probe_by`).
  The others wait, so 10 browsers do not hit a still-blocked IP together.
- **A good answer** calls `_ip_backoff_note_ok()`, which clears the pause for everyone.
- Tests turn the pause off (`GOOGLE_AI_MODE_IP_BACKOFF=0` in `tests/conftest.py`).

The real fix for frequent blocks is slower pacing: a higher `GOOGLE_AI_MODE_QUERY_DELAY`, fewer
`--slots` or workers, or another network.

---

## 3. How a search is sent and the output read

### 3.1 Sending
```python
from vendor_intel.scraping import google_ai_mode as aim
text = aim.ask("prompt ...")                                   # raw answer text
data = aim.chat_json(system, user, require_key="results")      # parsed JSON
```
1. **Build the URL** (`build_url`): `https://www.google.com/search?q=<prompt>&udm=50&hl=en`.
   - `udm=50` selects AI Mode.
   - A prompt that is too long is cut to the longest prefix that fits, with a warning. Avoid this; see 1.4.
2. **Pace** (`_pace`): wait `GOOGLE_AI_MODE_QUERY_DELAY` + 0–5 s since this browser's last query.
   Then wait for any shared pause (2.3).
3. **Navigate** with `page.goto(url, wait_until="domcontentloaded")`. The "interrupted by another
   navigation" error is harmless (AI Mode redirects to `&sei=`) and is ignored.
4. **Check for blocks** as in section 2.2.

### 3.2 Waiting for the answer
`_wait_for_answer()` returns when either:
- the page contains Google's "AI Mode response is ready" marker, or
- the text of `<main>` has stopped growing for two checks, 1.5 s apart.

It times out at 90 s. It never waits for a minimum length, because that made every short answer
wait for the full timeout.

### 3.3 Reading the answer
`_EXTRACT_JS` runs in the page:
- It takes `<main>`'s visible text.
- It hides `<script>` and `<style>`.
- It writes every outside link as `link text (https://url)`, so sources survive in the text.

The text is then checked against the quota, no-answer and refusal markers. Only a clean, non-empty
answer is returned. A good answer also resets the failure counters and clears the shared pause.

### 3.4 Getting structured data
Prompts ask for **compact JSON only**. `chat_json` adds a line telling AI Mode to leave unknown
fields blank rather than guess. `parse_json_answer()` then:

1. Strips Google's footer ("Use code with caution."), Markdown code-block markers (```` ``` ````) and a stray `json` tag.
2. Finds every `{"key"` or `[{"key"` start and slices each complete structure by matching brackets
   (`_balanced_slice`). A plain `rfind` swallowed a following echo into one broken blob.
3. **Ignores any JSON copied from the prompt itself.** The page shows the echoed question, and its
   template must never be read as the answer.
4. With `require_key`, it returns the first structure whose key has real values. Otherwise it
   returns the largest structure with values, or raises `JSONDecodeError`.

The caller treats an unparseable answer as "no answer": DROP in verify, re-ask in gap-fill. It is
never treated as a real result.

---

## 4. Fact-check (step 8a)

Runs after the report is built, on the **20 chart companies** only:
```bat
.venv\Scripts\python.exe scripts\factcheck_chart.py --market "X Market" --country global --browsers 10
```

### 4.1 Question 1: the company (one query per company)
`STATUS_SYS` gets the market definition, core scope and adjacent segments, and asks for JSON with
these fields:
- `operating`: active / in_administration / liquidated / dissolved / acquired_absorbed / renamed / unknown
- `event`, `current_name`, `owner`, `owner_since`, `hq` ("City, Country"), `main_product`
- `scope`: core / adjacent / out, with `scope_reason`
- `evidence`

### 4.2 Question 2: each supporting point (5 per query)
Only **specific** points are checked. A point is specific when it contains a digit, a quote, or a
word such as contract, awarded, partner, acquired, launched, won, selected, certified, ISO,
approved, framework, customer, client or integrat… (`_SPECIFIC`). A vague point like "strong
engineering capability" has nothing to check. "Not available" is never checked.

`CLAIM_SYS` prompt, as sent:
```
For EACH numbered claim, check it against published sources (company site, press releases,
filings, reputable news).
verdict = correct   (the source states it)
        | incorrect (a source contradicts a fact: date, number, name, title, client, status,
                     or the claim belongs to another company)
        | unverified (no source states that detail)
For incorrect, give corrected = the same sentence with only the wrong detail fixed;
for unverified, name the unconfirmed detail in note. source = where you checked. Never guess.
{"results":[{"n":1,"verdict":"...","corrected":"","note":"","source":""}]}
```

### 4.3 Split and resume
- One company's claim batches are shared over several browsers (`part` / `parts`). Part 0 also
  asks the company question.
- Answers are saved after every batch to `_pipeline/factcheck/findings*.json`.
  `merged_findings` combines all browsers' verdicts.
- **A claim already checked is never asked again**, nor is a sentence at least 80% similar to one
  (`was_checked`), nor a sentence that a correction already wrote.
- A company counts as finished when it has a status and a verdict for every specific claim.
  VERIFY's line "Chart fact-check complete" reads this.

### 4.4 What is applied automatically
`build_review` writes `_pipeline/factcheck_review.json`. AI Mode sometimes cites directory sites
and contradicts itself, so **only these decisions are applied automatically**:

| Finding | Action |
|---|---|
| liquidated, dissolved or in administration, **with a stated event** | excluded (an acquired company that still trades stays) |
| scope `adjacent` | taken off the chart; stays in Other Noticeable Players |
| scope `out` | excluded |
| an owner not already labelled, accepted by `owner_entry`, with a real year | "(acquired by / subsidiary of Owner)" label |
| HQ in a different **country** (city-only differences are ignored) | HQ corrected |
| a claim judged **incorrect** | corrected sentence (section 5) |
| a claim that belongs to another company | point removed |

`unverified` **never changes the report**: not finding a source is not proof of an error.
Everything else goes to `_pipeline/factcheck/findings.md` for a person to review.

---

## 5. When the verdict is "incorrect": writing the correct sentence

### 5.1 The gate: `_claim_decision()`
A correction is made **only if all of these hold**:

1. **The verdict is `incorrect`**, and a `corrected` sentence was given.
2. **There is a source, and it is not banned.** The source and the corrected sentence are checked
   against:
   - `config/estimate_sites.txt` (RocketReach, ZoomInfo, Crunchbase …),
   - `config/directory_sites.txt`,
   - `config/employee_review_sites.txt`,
   - `config/research_publishers.txt`.

   Matching ignores spaces ("wiseguyreports" also matches "Wise Guy Reports").
3. **Only a small detail changed.** `difflib.SequenceMatcher(claim, corrected).ratio() >= 0.75`.
   Below that, it is a rewrite rather than a fix, and is rejected.
4. **Nothing else backs the old figure.** Every number the edit removes is looked for in the
   company's other checked claims. If another verdict still supports the old number, the
   correction is dropped as contradictory.
5. **House style.** `_house_style()` runs `company_facts.clean_artifacts` (footnote markers like
   `[1.21]`, raw links, page leftovers) and then `primary_research_wording.to_primary` (research-team
   voice, no hedges). The fixed sentence then reads like the rest of the report.
6. **It actually differs** from the original. Otherwise nothing is written.

**A claim that belongs to another company.** If the note or source says so ("belongs to",
"another company", "different company", "not a product of"), the correction is written with
`"replace": ""`. The point is removed rather than rewritten.

### 5.2 Example
```
claim     : The company won a 12 MLD ZLD contract at Hawassa Industrial Park in 2021.
verdict   : incorrect
corrected : The company won a 12 MLD ZLD contract at Hawassa Industrial Park in 2023.
source    : company press release, March 2023
```
Similarity is about 0.98, the source is allowed, and no other claim says 2021. The entry written
to `factcheck_review.json` is:
```json
{"company": "Acme Water Ltd", "find": "...in 2021.", "replace": "...in 2023.",
 "reason": "fact-check: incorrect", "source": "company press release, March 2023"}
```

### 5.3 How the fix reaches the report
1. `company_status.apply_corrections` replaces `find` exactly with `replace` in that company's
   evidence in every `param_detail_prescored*.json`.
   - Any of the company's names matches: legal name, deduped variant or brand (`company_aliases`).
   - Report wording ("As per our analysis …") is mapped back to the pipeline's wording
     (`house_wording.to_legacy`) so the text is found.
   - The step prints how many places changed. 0 means not found or already applied; a wrong entry is never silently ignored.
   - Re-running is safe: once replaced, `find` no longer exists.
2. The report is rebuilt (step 8).
3. If any decision changed, the pipeline **re-runs itself from saved work**: drop or move
   companies, refill chart slots, evidence for new entrants, fact-check only the new entrants.
   - It stops after at most 8 passes (`QUADRANT_FACTCHECK_MAX_PASSES`), or earlier when a pass makes no new decisions.
   - A decision stays once made, so a company moved off the chart does not come back.

### 5.4 Overriding the fact-check by hand
A person's file `_pipeline/analyst_review.json` always wins over `factcheck_review.json`, which in
turn wins over `auto_review.json`.

To fix a sentence by hand, or to undo a wrong automatic fix:
```json
{"corrections": [{"company": "Acme Water Ltd", "find": "exact text in the report",
                  "replace": "correct sentence", "reason": "...", "source": "..."}],
 "keep": [{"company": "...", "reason": "undo an automatic exclusion"}]}
```
Then re-run the same pipeline command. Never edit the report HTML or JSON directly.

---

## 6. Files at a glance

| Path | Contents |
|---|---|
| `data/ai_mode_batch_<slot>_chromium/` | one browser profile per slot |
| `data/ai_mode_ip_backoff.json` | shared pause after a Google block |
| `extensions/captcha-raptor/` | bundled CAPTCHA solver |
| `_pipeline/factcheck/findings*.json` | raw fact-check answers, one file per browser |
| `_pipeline/factcheck/findings.md` | review list for a person |
| `_pipeline/factcheck_review.json` | automatic decisions and corrections |
| `_pipeline/analyst_review.json` | a person's overrides (always wins) |
