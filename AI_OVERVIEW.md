# Google AI Overview collector

Reads Google AI Overview answers in your own Chrome session and feeds them to the
pipeline as evidence. Two consumers use the same cache:

| Consumer | What it gains |
|----------|---------------|
| **Quadrant KB** (`quadrant/company_kb.py`) | Brand scoring cites real evidence instead of falling back to unsourced model knowledge on thin crawls. Revenue / YoY often become extractable. |
| **Discovery** (`pipeline/orchestrator.py`) | An extra discovery channel that names companies plain search ranks poorly — AI Overview summarises across sources. |

---

## Why it is built this way

The pipeline cannot drive a browser, and a Chrome extension cannot write files.
So neither side calls the other directly — they meet at a disk cache:

```text
  pipeline run                    Chrome extension
       │                                 │
       │ cache miss                      │ GET /pending
       ▼                                 ▼
  _pending.jsonl  ◄────────────►  bridge :15552  ◄──── POST /answers
       │                                 │
       └──────► answers/<key>.json ◄─────┘
                       │
              next pipeline run reads them
```

A cache miss **never blocks**. The question is queued, the run continues, and the
next run is richer. That is what makes this a loop rather than a single pass —
run, collect, re-run.

---

## Setup (once)

1. **Enable it** in `.env`:

   ```env
   AI_OVERVIEW_ENABLED=true      # quadrant KB reads the cache
   AI_OVERVIEW_DISCOVERY=true    # discovery mines company names from it
   # AI_OVERVIEW_CACHE_DIR=data/ai_overview_cache
   ```

2. **Load the extension**: `chrome://extensions` → enable **Developer mode** →
   **Load unpacked** → select the `extension/` folder.

---

## Running a collection round

```powershell
# 1. Produce questions — any pipeline or quadrant run with the flags on
python run_pipeline.py --industry "Rupture Disc Market" --country Brazil --live

# 2. Start the bridge
python run_ai_bridge.py --market "Rupture Disc Market"

# 3. Open the extension popup → Start.
#    It works through the queue in one reused tab and stops when empty.

# 4. Re-run the pipeline — now the answers are cached evidence
python run_pipeline.py --industry "Rupture Disc Market" --country Brazil --live
```

Check progress any time:

```powershell
curl http://127.0.0.1:15552/health
curl "http://127.0.0.1:15552/stats?market=rupture_disc_market"
```

---

## Bridge API

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Liveness, known markets, pending count |
| `GET /markets` | Every market with a cache directory |
| `GET /pending?limit=25&market=` | Next batch of questions |
| `POST /answers` | One answer, or `{"answers": [...]}` |
| `POST /enqueue` | Inject a question manually (testing) |
| `GET /stats?market=` | Cache counters |

An answer needs either `question` or a `key` that is already queued:

```json
{ "question": "Which companies make rupture discs?",
  "markdown": "- **Fike Corporation** — US maker",
  "citations": [{"title": "Fike", "url": "https://fike.com"}] }
```

---

## Cache layout

```text
data/ai_overview_cache/<market_slug>/
├── _pending.jsonl        # one question per line
└── answers/<key>.json    # key = sha256(normalised question)[:40]
```

The payload matches `google_ai_scraper.google_ai_ask()` — `markdown`,
`citations`, `ai_overview_missing`, `error` — so any relay can fill the same
cache and none of them need to know about each other.

Answers are **re-cleaned on read**, not just on write. Improving a cleaning regex
applies retroactively to the whole cache instead of forcing a re-scrape.

---

## Pacing

The extension is deliberately serial: one question at a time, one reused tab,
4–9 s of jitter between queries. Bursting both degrades answer quality (overviews
stop rendering) and hammers a service we do not control. Tune in
`extension/background.js` → `DEFAULTS`.

---

## When Google changes the markup

`content.js` never depends on one selector. It tries, in order:

1. known overview attributes (`data-subtree="aio"`, `data-attrid="SGE"`, …)
2. the literal "AI Overview" heading, climbing to the ancestor holding the prose
3. the tightest text block above the first organic result

Each answer records which strategy worked (`how` in the popup status), so when
Google rotates markup the logs say *how* it changed rather than going quiet. If
every strategy starts returning `not-found`, strategy 1 is the one to update.

---

## Troubleshooting

| Symptom | Cause |
|---------|-------|
| Popup shows `bridge unreachable` | `run_ai_bridge.py` not running, or the URL in the popup is wrong |
| Everything comes back `no overview` | Google is not rendering overviews for these queries — often too-narrow phrasing; or you are signed out |
| `content script unreachable` | A consent interstitial is showing. Open google.com in that tab once, accept, and press Start again |
| Questions queue but never clear | The extension is pointed at a different market than the one the pipeline wrote |
| KB source stays `pipeline_evidence_snapshot` | `AI_OVERVIEW_ENABLED` is not `true`, or no answers cached yet for that market |
