"""Google AI Overview evidence, cached on disk and queueable when absent.

Ported from the customer-intel pipeline, where the extraction rules below were
hardened against live runs — the rejection cases named in the comments are all
real rows that got through an earlier version.

The pipeline cannot call a browser itself. So instead of blocking on a live
scraper, an unanswered question is *recorded* and the run continues with that
branch marked unresolved. A driver — the Chrome extension in ``extension/`` via
the bridge in :mod:`vendor_intel.evidence.bridge`, or any HTTP relay — drains the
queue and writes answers back. Re-running the pipeline then picks them up and
goes further, which is what makes the whole thing a loop rather than a single
pass.

The stored payload is deliberately shaped like ``google_ai_scraper.google_ai_ask()``:
``markdown``, ``citations``, ``ai_overview_missing``, ``error``. Any filler can
populate the same cache and none of them know about each other.

Two consumers read this cache:

* :mod:`vendor_intel.quadrant.company_kb` — adds answers as KB chunks so brand
  scoring cites real evidence instead of falling back to model knowledge.
* :mod:`vendor_intel.pipeline.orchestrator` — mines company names out of answers
  as an extra discovery channel.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable


def _project_root() -> Path:
    # src/vendor_intel/evidence/ai_overview.py -> repo root
    return Path(__file__).resolve().parents[3]


def market_slug(market: str) -> str:
    """Folder-safe key for a market. One cache directory per market."""
    s = re.sub(r"[^a-z0-9]+", "_", (market or "market").strip().lower())
    return s.strip("_")[:80] or "market"


def default_cache_dir(market: str = "") -> Path:
    """Where answers live. ``AI_OVERVIEW_CACHE_DIR`` overrides the root."""
    root = (os.getenv("AI_OVERVIEW_CACHE_DIR") or "").strip()
    base = Path(root) if root else _project_root() / "data" / "ai_overview_cache"
    return base / market_slug(market) if market else base


def resolve_market_key(
    query_context: dict[str, Any] | None = None,
    scope: dict[str, Any] | None = None,
) -> str:
    """The one market string every consumer must key its cache on.

    ``scope["market"]`` is the *normalised search topic* ("rupture disc"), while
    ``query_context["industry"]`` is the market as the operator typed it
    ("Rupture Disc Market") — which is also what they pass to
    ``run_ai_bridge.py --market``. Keying off scope split one market across two
    cache directories, so answers collected by discovery were invisible to the
    quadrant. Prefer the operator's own string; fall back to scope.
    """
    query_context = query_context or {}
    scope = scope or {}
    for candidate in (
        query_context.get("industry"),
        scope.get("market"),
        query_context.get("query"),
    ):
        text = str(candidate or "").strip()
        if text:
            return text
    return ""


def ai_overview_enabled() -> bool:
    return (os.getenv("AI_OVERVIEW_ENABLED") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

_WS = re.compile(r"\s+")

# Lines of Google SERP furniture that are never evidence.
_CHROME_LINE = re.compile(
    r"^(skip to|accessibility|sign in|google apps|search results|ai mode|all\b|"
    r"images\b|videos\b|news\b|shopping\b|forums\b|more\b|web results|"
    r"people also ask|short videos|show all|show more|tools\b|about \d|"
    r"filter|settings|privacy|terms|feedback)\b",
    re.I,
)
_NO_OVERVIEW = re.compile(
    r"(ai overview is not available|can'?t generate an ai overview|"
    r"unable to generate an ai overview|no ai overview)",
    re.I,
)


def question_key(text: str) -> str:
    """Stable cache key for a question. Whitespace and case are not meaningful."""
    norm = _WS.sub(" ", (text or "").strip().lower())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:40]


@dataclass
class Question:
    """One thing we need Google to tell us.

    ``layer`` and ``purpose`` are carried through to the drain manifest so a human
    (or an agent) reading the queue can tell what each question is *for* without
    re-deriving it.
    """

    text: str
    layer: str = ""            # "L0" | "L1" | "L2" | "L3" | "L4"
    purpose: str = ""          # e.g. "buyer_types_for_application"
    subject: str = ""          # the node this question is about
    market: str = ""
    key: str = ""

    def __post_init__(self) -> None:
        if not self.key:
            self.key = question_key(self.text)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Answer:
    """A cached AI Overview response."""

    key: str
    question: str
    markdown: str = ""
    citations: list[dict[str, str]] = field(default_factory=list)
    overview_missing: bool = False
    error: str = ""
    source: str = "ai_overview"     # who filled it: chrome | relay | operator
    saved_at: float = 0.0

    @property
    def ok(self) -> bool:
        return bool(self.markdown.strip()) and not self.overview_missing

    @property
    def urls(self) -> list[str]:
        out: list[str] = []
        for c in self.citations:
            u = str(c.get("url") or c.get("link") or "").strip()
            if u.startswith("http") and u not in out:
                out.append(u)
        return out


# Google prefixes some answers with a language-toggle token in the local script
# ("मराठी", "हिन्दी", "中文"). It is UI furniture and must not become evidence.
_LANG_TOGGLE = re.compile(
    r"^\s*[^\x00-\x7F]{2,20}\s+(?=[A-Z0-9])|^\s*[^\x00-\x7F]{2,20}\s*$"
)


def clean_overview_markdown(raw: str, *, max_chars: int = 12000) -> str:
    """Strip SERP chrome, keep the substance."""
    text = (raw or "").replace("\x00", " ")
    lines: list[str] = []
    for line in text.splitlines():
        s = _LANG_TOGGLE.sub("", line.strip()).strip()
        if not s:
            if lines and lines[-1]:
                lines.append("")
            continue
        if _CHROME_LINE.match(s) or _NO_OVERVIEW.search(s):
            continue
        if s.lower() in {"ai overview", "ai mode", "pro", "read more", "show more"}:
            continue
        if len(s) <= 2 and not s.isalnum():
            continue
        lines.append(s)
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return out[:max_chars]


class AiOverviewStore:
    """Disk cache plus a pending-question queue.

    >>> store = AiOverviewStore(tmp_path)                       # doctest: +SKIP
    >>> store.ask(Question(text="who buys smartphones in bulk"))  # doctest: +SKIP
    None
    >>> store.pending()                                          # doctest: +SKIP
    [Question(text='who buys smartphones in bulk', ...)]
    """

    def __init__(self, cache_dir: Path | str, *, ttl_days: float = 30.0) -> None:
        self.dir = Path(cache_dir)
        self.answers_dir = self.dir / "answers"
        self.answers_dir.mkdir(parents=True, exist_ok=True)
        self.queue_path = self.dir / "_pending.jsonl"
        # ttl_days=0 means "treat everything as stale" — useful for a forced refresh.
        self.ttl_sec = max(0.0, float(ttl_days) * 86400.0)
        self._queued: dict[str, Question] = {}
        self._load_queue()
        self.hits = 0
        self.misses = 0

    # ── queue ───────────────────────────────────────────────────────────
    def reload_queue(self) -> int:
        """Re-read the queue file, picking up writes from other processes.

        The pipeline enqueues from its own process while the bridge is already
        running. Without this the bridge serves whatever the queue held when it
        started and never sees a new question, so the collect-and-rerun loop
        silently stops after the first batch. Returns the pending count.
        """
        self._queued = {}
        self._load_queue()
        return len(self.pending())

    def _load_queue(self) -> None:
        if not self.queue_path.is_file():
            return
        for line in self.queue_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                q = Question(**{k: v for k, v in row.items() if k in Question.__dataclass_fields__})
                self._queued[q.key] = q
            except Exception:
                continue

    def _write_queue(self) -> None:
        rows = [json.dumps(q.to_dict(), ensure_ascii=False) for q in self._queued.values()]
        self.queue_path.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")

    def enqueue(self, question: Question) -> None:
        """Record a question we could not answer from cache.

        Re-reads first: the queue file is shared with other processes (the
        pipeline enqueues while the bridge serves), and ``_write_queue`` rewrites
        the whole file from memory. Without the reload, whichever process writes
        last silently discards everything the others added.
        """
        self.reload_queue()
        if question.key in self._queued:
            return
        self._queued[question.key] = question
        self._write_queue()

    def reset_queue(self) -> int:
        """Drop every queued question, keeping cached answers.

        Used by ``--fresh``: question templates change during development, and a
        stale queue would otherwise keep asking questions no layer wants.
        """
        n = len(self._queued)
        self._queued = {}
        self._write_queue()
        return n

    def pending(self, *, limit: int = 0) -> list[Question]:
        """Questions still awaiting an answer (answered ones are dropped)."""
        out = [q for q in self._queued.values() if not self._answer_path(q.key).is_file()]
        return out[:limit] if limit else out

    def clear_answered(self) -> int:
        """Drop queue entries that now have a cached answer."""
        before = len(self._queued)
        self._queued = {
            k: q for k, q in self._queued.items() if not self._answer_path(k).is_file()
        }
        if len(self._queued) != before:
            self._write_queue()
        return before - len(self._queued)

    # ── cache ───────────────────────────────────────────────────────────
    def _answer_path(self, key: str) -> Path:
        return self.answers_dir / f"{key}.json"

    def get(self, question: Question | str) -> Answer | None:
        """Return a cached answer, or ``None`` on miss or expiry."""
        key = question.key if isinstance(question, Question) else question_key(question)
        path = self._answer_path(key)
        if not path.is_file():
            return None
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        saved_at = float(row.get("saved_at") or 0.0)
        if self.ttl_sec <= 0 or (saved_at and time.time() - saved_at > self.ttl_sec):
            return None
        # Re-clean on read, not just on write. Cleaning rules keep improving,
        # and re-scraping 300 answers to apply a regex fix would be absurd —
        # this makes every cleaning fix retroactive across the whole cache.
        return Answer(
            key=key,
            question=str(row.get("question") or ""),
            markdown=clean_overview_markdown(str(row.get("markdown") or "")),
            citations=list(row.get("citations") or []),
            overview_missing=bool(row.get("ai_overview_missing")),
            error=str(row.get("error") or ""),
            source=str(row.get("source") or "ai_overview"),
            saved_at=saved_at,
        )

    def ask(self, question: Question) -> Answer | None:
        """Cache lookup; on a miss the question is queued and ``None`` returned."""
        hit = self.get(question)
        if hit is not None:
            self.hits += 1
            return hit
        self.misses += 1
        self.enqueue(question)
        return None

    def put(
        self,
        question: Question | str,
        markdown: str,
        *,
        citations: Iterable[dict[str, str]] | None = None,
        overview_missing: bool = False,
        error: str = "",
        source: str = "chrome",
    ) -> Answer:
        """Write an answer into the cache and drop it from the queue."""
        if isinstance(question, Question):
            key, text = question.key, question.text
        else:
            key, text = question_key(question), question
        cleaned = clean_overview_markdown(markdown)
        payload = {
            "key": key,
            "question": text,
            "markdown": cleaned,
            "markdown_raw": markdown or "",
            "citations": [dict(c) for c in (citations or [])],
            "ai_overview_missing": bool(overview_missing) or not cleaned.strip(),
            "error": error,
            "source": source,
            "saved_at": time.time(),
        }
        self._answer_path(key).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # Same shared-file hazard as enqueue(): rewriting the queue from a stale
        # in-memory copy would resurrect questions other processes removed, or
        # erase ones they added.
        self.reload_queue()
        if key in self._queued:
            del self._queued[key]
            self._write_queue()
        return Answer(
            key=key,
            question=text,
            markdown=cleaned,
            citations=payload["citations"],
            overview_missing=bool(payload["ai_overview_missing"]),
            error=error,
            source=source,
            saved_at=float(payload["saved_at"]),
        )

    # ── driver hand-off ─────────────────────────────────────────────────
    def write_manifest(self, path: Path | str, *, limit: int = 0) -> Path:
        """Write the pending queue where a browser driver can pick it up."""
        rows = [q.to_dict() for q in self.pending(limit=limit)]
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps({"count": len(rows), "questions": rows}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return p

    def ingest_manifest(self, path: Path | str, *, source: str = "chrome") -> int:
        """Read answers produced by a driver back into the cache.

        Accepts either ``{"answers": [...]}`` or a bare list. Each entry needs a
        ``question`` (or ``key``) plus ``markdown``; ``citations`` is optional.
        """
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        rows = raw.get("answers") if isinstance(raw, dict) else raw
        if not isinstance(rows, list):
            return 0
        n = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            text = str(row.get("question") or "").strip()
            key = str(row.get("key") or "").strip()
            if not text and key:
                q = self._queued.get(key)
                text = q.text if q else ""
            if not text:
                continue
            self.put(
                text,
                str(row.get("markdown") or row.get("answer") or ""),
                citations=row.get("citations") or [],
                overview_missing=bool(row.get("ai_overview_missing")),
                error=str(row.get("error") or ""),
                source=source,
            )
            n += 1
        return n

    def stats(self) -> dict[str, Any]:
        return {
            "cache_dir": str(self.dir),
            "cached_answers": len(list(self.answers_dir.glob("*.json"))),
            "pending": len(self.pending()),
            "hits": self.hits,
            "misses": self.misses,
        }


# ── list extraction ───────────────────────────────────────────────────────
_BULLET = re.compile(r"^\s*(?:[-*•·]|\d+[.)])\s+(.+)$")
_BOLD = re.compile(r"\*\*([^*\n]{2,80})\*\*")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")

_NOT_A_NAME = re.compile(
    # "top \d" needed the \s*\d+ form: "Top 10" has no word boundary after the
    # first digit, so the old pattern let listicle headings through as companies.
    r"^(?:ai overview|google|wikipedia|here (?:are|is)|top\s*\d+|list of|"
    r"for example|these|this|the following|other|others|various|many|some|"
    r"include|including|note|summary|overview|conclusion|source|according|"
    # Assistant filler that leaks in when the overview answers conversationally:
    # "I can help you find rupture disc suppliers in Canada".
    r"i can|i'?ll|i would|let me|you can|we can|if you|would you|please)\b",
    re.I,
)

# A locative tail is not part of the name: "Continental Disc Corporation located
# in Liberty, Missouri" is one real company plus prose. Cutting the tail RECOVERS
# the company; rejecting the whole string would lose it.
_LOCATIVE_TAIL = re.compile(
    r"\s+(?:located|based|headquartered|situated|founded|established|"
    r"operating|headquarters)\s+(?:in|at|out of)\b.*$",
    re.I,
)

# Descriptive tails that similarly run past the end of a name.
_DESCRIPTIVE_TAIL = re.compile(
    r"\s+(?:which|who|that)\s+.*$|"
    r"\s+(?:is|are|was|were|has|have|offers?|provides?|supplies|manufactures?|"
    r"specializes?|specialises?)\s+.*$",
    re.I,
)


def strip_trailing_clause(name: str) -> str:
    """Cut prose that ran past the end of a company name."""
    out = _LOCATIVE_TAIL.sub("", name or "")
    out = _DESCRIPTIVE_TAIL.sub("", out)
    return out.strip(" ,;:-–—")


# A sentence boundary inside a "name" means a marketing blurb was swallowed
# whole: "About ZOOK. Your Pressure Relief Partner. ZOOK".
_SENTENCE_RUN = re.compile(r"[a-z]\.\s+[A-Z]")


def split_conjoined_names(name: str) -> list[str]:
    """Split "Fike Corporation & Continental Disc Corporation" into two names.

    Only splits when BOTH sides are multi-word, so real names that contain a
    spaced ampersand survive: "Procter & Gamble" has a one-word left side and is
    left alone, and "BS&B Safety Systems" has no spaces around its ampersand.
    """
    parts = re.split(r"\s+(?:&|and)\s+", name or "")
    if len(parts) != 2:
        return [name]
    left, right = (p.strip() for p in parts)
    if left.count(" ") >= 1 and right.count(" ") >= 1:
        return [left, right]
    return [name]

# Generic phrases that are activities or categories, never organisations.
_GENERIC_NAME = re.compile(
    r"^(?:workflow|communication|documentation|tracking|scanning|reporting|"
    r"monitoring|management|assistance|coordination|productivity|navigation|"
    r"messaging|training|scheduling|security|connectivity|efficiency|"
    r"real[- ]time|bring your own device|byod|stipends?|"
    # Editorial furniture that reads like a labelled entry:
    # "Editor's note: ...", "Disclaimer: ...", "Update: ..."
    r"editor|editor'?s note|disclaimer|update|correction|caveat|"
    r"methodology|sources?|references?|footnote|see also)\b",
    re.I,
)

# Place names that turn up when an answer localises itself.
_PLACE_ONLY = re.compile(
    r"^(?:singapore|north america|south america|latin america|europe|asia|"
    r"asia pacific|africa|middle east|the us|the uk|usa|uk|india|china|japan|"
    r"germany|france|australia|canada|global|worldwide|"
    r"brazil|mexico|spain|italy|netherlands|sweden|switzerland|poland|turkey|"
    r"korea|south korea|indonesia|malaysia|thailand|vietnam|"
    # Cities turn up when an answer localises an example; "London uses
    # industrial air compressors extensively" is about the city, not a buyer.
    r"london|paris|berlin|madrid|rome|tokyo|beijing|shanghai|mumbai|delhi|"
    r"new york|chicago|houston|toronto|sydney|dubai|shenzhen|seoul|"
    r"amsterdam|munich|milan|barcelona|bangalore|chennai|pune|"
    # US states and Canadian provinces: splitting "…in Liberty, Missouri" on the
    # comma leaves the state standing alone as a candidate company.
    r"alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|"
    r"florida|georgia|hawaii|idaho|illinois|indiana|iowa|kansas|kentucky|"
    r"louisiana|maine|maryland|massachusetts|michigan|minnesota|mississippi|"
    r"missouri|montana|nebraska|nevada|new hampshire|new jersey|new mexico|"
    r"north carolina|north dakota|ohio|oklahoma|oregon|pennsylvania|"
    r"rhode island|south carolina|south dakota|tennessee|texas|utah|vermont|"
    r"virginia|washington|west virginia|wisconsin|wyoming|"
    r"ontario|quebec|alberta|manitoba|saskatchewan|nova scotia|"
    r"british columbia|new brunswick|newfoundland|prince edward island)\s*$",
    re.I,
)


def _is_plausible_entity(name: str) -> bool:
    """Reject the debris that enumeration parsing inevitably produces.

    Every one of these was a real row in a live run: ``"Zebra handhelds) or
    Bring Yo"``, ``"Singapore or North America)"``, ``"Workflow assistance"``,
    ``"Apollo Hospitals has"``, ``"Bed Count vs. Scale"``.
    """
    if name.count("(") != name.count(")"):
        return False
    # A colon or a currency figure means we sliced through a sentence, not a name.
    if ":" in name or re.search(r"[₹$€£¥]\s*[\d,.]", name):
        return False
    # An underscore is a scraped template artefact ("Table_title").
    if "_" in name:
        return False
    # "No Free Giveaways" — a heading lifted out of a negative answer.
    if re.match(r"^(?:no|not|none|nothing|never)\b", name, re.I):
        return False
    # "X vs. Y" is a comparison heading.
    if re.search(r"\bv[s\.]{1,3}\b", name, re.I):
        return False
    # A dangling verb means the sentence continued past the cut.
    if re.search(r"\b(?:has|have|had|is|are|was|were|will|can|does|do|and|or|"
                 r"with|for|from|that|which|who|by|in|on|at|to|of|the|a|an)$",
                 name, re.I):
        return False
    if any(ch.isdigit() for ch in name) and name.count(" ") >= 3:
        return False
    if re.search(r"\b(?:or|and)\b", name, re.I) and name.count(" ") >= 3:
        # "Novade or Hubble for daily l" — an alternation, not a name.
        return False
    if _GENERIC_NAME.match(name) or _PLACE_ONLY.match(name):
        return False
    if not name[:1].isupper():
        return False
    words = re.findall(r"[A-Za-z]+", name)
    if not words:
        return False
    # An acronym is a legitimate whole name — "AT&T", "UPS", "DHL", "BT".
    letters = "".join(words)
    if len(letters) >= 2 and letters.isupper():
        return True
    # Otherwise a name needs at least one substantial word.
    return any(len(w) > 2 for w in words)

# A trailing period that belongs to the name rather than ending a sentence:
# "Orange S.A.", "Reliance Industries Ltd.", "Foxconn Technology Co."
_ABBREV_END = re.compile(
    r"(?:\b[A-Za-z]\.(?:[A-Za-z]\.)+|"
    r"\b(?:Inc|Ltd|Co|Cos|Corp|Plc|LLC|LLP|GmbH|AG|NV|SA|SpA|Pvt|Pte|Bhd|Sdn|Bros|Jr|Sr)\.)$",
    re.I,
)


@dataclass
class Entry:
    """A list item from an answer: the name, plus whatever described it.

    The description is not decoration. "Binah.ai: Provides video-based vital
    sign measurements via a smartphone camera" and "Walmart: Uses Store Mode in
    its app" are both smartphone-related bullets, but only one of them is a
    customer. Dropping the description throws away the only signal that
    separates them, so it is carried through to the verification stage.
    """

    name: str
    description: str = ""

    @property
    def text(self) -> str:
        return "%s %s" % (self.name, self.description) if self.description else self.name


def extract_entries(markdown: str, *, max_words: int = 8, limit: int = 200) -> list[Entry]:
    """Pull list entries with their descriptions, in document order."""
    text = clean_overview_markdown(markdown or "")
    found: list[Entry] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        line = _MD_LINK.sub(r"\1", raw or "")
        line = _WS.sub(" ", line).strip()
        name, description = line, ""
        # "Acme Corp — a maker of X" / "Acme Corp: makes X" -> name + description
        for sep in (" — ", " – ", " - ", ": "):
            if sep in line:
                head, tail = line.split(sep, 1)
                if len(head.strip()) >= 3:
                    name, description = head.strip(), tail.strip()
                break
        name = name.strip(" *_,;:|–—-")
        # A trailing parenthetical is a qualifier, not part of the name:
        # "Cleveland Clinic Main Campus (Cleveland, OH)". Keeping it also breaks
        # dedup against the same organisation named without it.
        trailing = re.search(r"\s*\(([^()]*)\)\s*$", name)
        if trailing:
            name = name[:trailing.start()].strip()
            if not description:
                description = trailing.group(1).strip()
        # "Continental Disc Corporation located in Liberty" is a real company
        # plus prose — cut the tail rather than reject the whole entry.
        name = strip_trailing_clause(name.strip(" *_,;:|–—-"))
        # Keep the period in "Orange S.A."; drop the one ending a sentence.
        while name.endswith(".") and not _ABBREV_END.search(name):
            name = name[:-1].strip()
        if not (2 < len(name) <= 80):
            return
        if _NOT_A_NAME.match(name) or name.lower().startswith("http"):
            return
        if _SENTENCE_RUN.search(name):
            return  # a whole blurb was swallowed, not a name
        if name.count(" ") >= max_words or name.endswith(("?", "!")):
            return
        if not _is_plausible_entity(name):
            return
        key = re.sub(r"[^a-z0-9]", "", name.lower())
        if len(key) < 3 or key in seen:
            return
        seen.add(key)
        # A description with no words is a truncated figure ("₹21,0"), not evidence.
        if description and not re.search(r"[A-Za-z]{3}", description):
            description = ""
        found.append(Entry(name=name, description=description))

    for line in text.splitlines():
        m = _BULLET.match(line)
        if m:
            add(m.group(1))
        if len(found) >= limit:
            return found

    # Unbulleted "Name: description" lines — the richest source when present.
    for line in text.splitlines():
        m = _LABELLED_LINE.match(line)
        if not m:
            continue
        head, tail = m.group(1).strip(), m.group(2).strip()
        if _SECTION_HEAD.match(head) or head.count(" ") >= max_words:
            continue
        add("%s: %s" % (head, tail))
        if len(found) >= limit:
            return found

    if len(found) < 3:
        for m in _BOLD.finditer(text):
            add(m.group(1))
            if len(found) >= limit:
                break

    # Prose enumerations run ALWAYS, not just as a fallback. A single answer
    # routinely carries both — "such as DHL, FedEx, UPS and Maersk" in the
    # opening sentence, then capability headings ("Route Optimization: ...")
    # below. Treating prose as a last resort meant the headings satisfied the
    # threshold and the actual company names were never read.
    for entry in extract_prose_entries(text, max_words=max_words):
        key = re.sub(r"[^a-z0-9]", "", entry.name.lower())
        if key and key not in seen:
            seen.add(key)
            found.append(entry)
        if len(found) >= limit:
            break
    return found[:limit]


# "such as X, Y and Z" / "examples include X, Y and Z".
# "like" is deliberately NOT a trigger: it fires on "mobile apps like Novade or
# Hubble", harvesting software names as though they were buyers. Anything it
# would have caught is picked up by the labelled-line parser instead.
_LIST_TRIGGER = re.compile(
    r"\b(?:examples?\s+(?:include|are)|such\s+as|includ(?:e|es|ing)|namely|"
    r"e\.g\.|these\s+are)\b[:\s]+",
    re.I,
)

# "Sentara Health: Equips thousands of clinicians across its 12 hospitals..."
# Google's AI Overview writes these WITHOUT a bullet marker, so the bullet
# parser never sees them — and they carry the richest evidence in the answer.
_LABELLED_LINE = re.compile(r"^\s*([A-Z][^:\n]{2,60}?):\s+(\S.{9,})$")

# Section headings share that shape ("Staff Eligibility: ...", "Data and
# Security: ..."), so heads opening with a generic label word are skipped.
_SECTION_HEAD = re.compile(
    r"^(?:staff|data|software|hardware|security|privacy|cost|pricing|benefit|"
    r"challenge|how|why|what|when|where|which|who|key|main|other|note|summary|"
    r"overview|integration|eligibility|example|type|feature|use case|pros|cons|"
    r"tip|step|phase|option|purpose|central|result|impact|conclusion|background|"
    r"industry|company|companies|device|mobile|enterprise|general)\b",
    re.I,
)
# Ends the enumeration: sentence stop, dash aside, or a new clause.
_ENUM_END = re.compile(r"[.;—–]|\bwhich\b|\bwhere\b|\bwhile\b|\bbecause\b", re.I)


def _split_top_level(text: str) -> list[str]:
    """Split on commas that are not inside brackets."""
    out: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    out.append("".join(buf))
    return [c for c in out if c.strip()]


def extract_prose_entries(text: str, *, max_words: int = 8) -> list[Entry]:
    """Pull named entities out of a prose enumeration, with their parentheticals.

    The parenthetical is kept as the description because it is usually the
    strongest evidence available — "Sentara Health (equipping clinicians across
    its 12 hospitals with nearly 6,000 secure clinical smartphones)" states the
    consumption outright.
    """
    entries: list[Entry] = []
    seen: set[str] = set()

    for trigger in _LIST_TRIGGER.finditer(text):
        tail = text[trigger.end():]
        # Find the end of the enumeration, ignoring anything inside brackets.
        depth = 0
        cut = len(tail)
        for i, ch in enumerate(tail):
            if ch in "([":
                depth += 1
            elif ch in ")]":
                depth = max(0, depth - 1)
            elif depth == 0 and _ENUM_END.match(tail, i):
                cut = i
                break
        span = tail[:cut]
        if len(span) < 3:
            continue

        for chunk in _split_top_level(span):
            piece = re.sub(r"^\s*(?:and|or)\s+", "", chunk.strip(), flags=re.I)
            # "international facilities like Vejthani Hospital" -> the name only
            piece = re.split(r"\b(?:like|such as)\b", piece, flags=re.I)[-1].strip()

            description = ""
            paren = re.search(r"\(([^)]*)\)", piece)
            if paren:
                description = paren.group(1).strip()
                piece = piece[:paren.start()].strip()

            name = strip_trailing_clause(piece.strip(" *_,;:|–—-\"'"))
            while name.endswith(".") and not _ABBREV_END.search(name):
                name = name[:-1].strip()
            if not (2 < len(name) <= 80) or name.count(" ") >= max_words:
                continue
            if _NOT_A_NAME.match(name) or not _is_plausible_entity(name):
                continue
            key = re.sub(r"[^a-z0-9]", "", name.lower())
            if len(key) < 3 or key in seen:
                continue
            seen.add(key)
            entries.append(Entry(name=name, description=description))
    return entries


def extract_names(markdown: str, *, max_words: int = 8, limit: int = 200) -> list[str]:
    """Names only — for callers that do not need the descriptions.

    Deliberately conservative: it favours dropping a real name over inventing one,
    because every extracted string becomes a graph node that later stages spend
    real effort verifying.
    """
    out: list[str] = []
    for entry in extract_entries(markdown, max_words=max_words, limit=limit):
        for part in split_conjoined_names(entry.name):
            if part and part not in out:
                out.append(part)
    return out
