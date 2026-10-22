"""Quantitative estimates for disclosure gaps (pipeline step 7c).

The evidence step writes a gap as "Based on primary research, the company has
not disclosed X." When X is a figure (revenue, headcount, customers,
deployments, market share, contract value, offices ...), step 7c asks Google
AI Mode (scripts/estimate_gaps.py) whether the company does in fact report the
figure, or whether quantitative first-party indicators support a defensible
range. This module turns those answers into report text, in this order:

1. disclosed figure    -> "Based on primary research, the company reports its
                           <metric> as <value>."
2. estimated range     -> "Based on primary research, the company's estimated
                           <metric> is approximately <range>, derived from <basis>."
3. no defensible basis -> the original gap sentence stays; a gap that is only
                           a figure reads "... has not disclosed sufficient
                           information to support a reliable quantitative
                           estimate for <X>."

Never a number without a basis (same rules for every market):
- every indicator is a figure with a source, and no source or basis may be a
  directory / modelled-estimate / employee-review / research-publisher site
  (config lists: their numbers are modelled, not evidence);
- every number in the basis appears in those indicators or in the company's
  own evidence already in the report (the basis cannot be invented);
- confidence is capped by the indicator count (high >= 3, medium 2, low 1) and
  only estimates at QUADRANT_ESTIMATE_MIN_CONFIDENCE (default medium) or above
  are published;
- an estimate is a range or a rounded figure (two significant digits at
  most), worded "estimated ... approximately" -- never as a reported figure.

Each published statement is also stored on the parameter as
``estimates: [{metric, value_type, value | estimated_value, confidence, basis,
source_type}]`` (additive; scores are not changed).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Iterable

from vendor_intel.pipeline.quadrant_pipeline import load_evidence, write_json_atomic

PR = "Based on primary research, the company has not disclosed"
EST_DIR = "estimates"
ANSWERS = "answers.json"
SOURCE_TYPE = "primary_research"
LEVELS = ("low", "medium", "high")
MAX_ASKS = 2

_SENT = re.compile(r"(?<=[.!?])\s+")
_GAP = re.compile(r"^(?:However,\s+)?based on primary research, the company has not disclosed\s+(.+?)\.?$", re.I)
# The gap names a figure: something counted, measured or valued.
_QUANT = re.compile(
    r"\b(?:numbers?|counts?|total|revenues?|turnover|sales|ARR|MRR|income|profit|margins?|valuations?|"
    r"market share|share of|headcount|employees?|staff|workforce|team size|customers?|clients?|users?|"
    r"subscribers?|accounts|installations?|installed base|deployments?|projects|contract (?:values?|sizes?)|"
    r"deal (?:sizes?|values?)|offices|facilities|plants|locations|branches|countries|capacity|volumes?|"
    r"percentages?|growth rates?|funding|partners|resellers|SKUs?|units sold|fleet size|transactions|"
    r"how many|figures|rates?|accuracy|uptime|latency|metrics|benchmarks?|throughput|scalability|SLAs?|"
    r"response times?|processing times?|win rates?|retention)\b", re.I)
# A gap about independent proof cannot be closed by an estimate: an estimate
# is the opposite of a third-party audit.
_PROOF = re.compile(r"\b(?:independent(?:ly)?|third[- ]party|audit\w*|certif\w*|accredit\w*|validat\w*|"
                    r"verif\w*|benchmark\w*|peer[- ]review\w*|SLAs?)\b", re.I)
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
_RANGE = re.compile(r"(\d[\d,.]*\s*%?)\s*(?:-|–|—|to)\s*(\$|€|£)?(?=\d)")
_HEDGE_LEAD = re.compile(r"^(?:approximately|approx\.?|about|around|roughly|circa|c\.|an estimated|"
                         r"estimated|~)\s*", re.I)
_LEAD_BASIS = re.compile(r"^(?:derived from|based on|from)\s+", re.I)
_MARKET_SIZE = re.compile(r"\bmarket[- ](?:siz\w*|valu\w*|estimate\w*|forecast\w*)|\b(?:TAM|CAGR)\b|"
                          r"\b(?:global|total) (?:[\w-]+ ){0,3}market (?:of|worth|at)\b", re.I)
# A share of the market needs the market's size as its denominator, and only
# research publishers (the report owner's competitors) produce that figure, so
# a share is never estimated -- whatever basis the answer names.
_SHARE = re.compile(r"\bmarket[- ]share\b|\bshare of (?:the )?(?:[\w-]+ ){0,4}market\b|\bmarket position(?:ing)? %", re.I)
# Estimated only: SIZE figures, which counts and earlier figures can bound.
# Rates, margins, growth, shares and breakdowns are ratios a count cannot
# derive (live AP run: "win rate 40-50% from 100 new logos", "touchless rate
# from an implementation rate"), so those are only ever reported as disclosed.
_SIZE_METRIC = re.compile(
    r"\b(?:revenues?|ARR|MRR|sales|turnover|bookings|employees?|headcount|staff|workforce|team size|"
    r"customers?|clients?|users?|subscribers?|accounts|contract (?:values?|sizes?)|deal (?:values?|sizes?)|"
    r"ACV|countries|offices|locations|sites|facilities|branches|deployments?|installations?|implementations?|"
    r"projects|partners?|resellers?|transactions?|invoices?|volumes?|spend|capacity)\b", re.I)
_RATIO_METRIC = re.compile(r"\b(?:rates?|margins?|profit\w*|ratios?|percent\w*|growth|shares?|break-?downs?|"
                           r"splits?|mix|EBITDA|EBIT)\b|%", re.I)
_SPLIT_METRIC = re.compile(r"break-?downs?|splits?|\bmix\b|regional|\bregions?\b|channel|\bshares?\b|%|percent", re.I)
# Performance and deal-term figures are never estimated: a company's size
# says nothing about its extraction accuracy, touchless rate, win rate or
# valuation (live AP run: "touchless rate 60-90% derived from 238 patents",
# "win rate 80% derived from 16,000 users"). Only a reported figure is used.
_NOT_ESTIMABLE = re.compile(
    r"accura\w*|touchless|straight[- ]through|\bwin\b|win[- ]?(?:loss|rates?)|retention|churn|uptime|availability|"
    r"error|latency|\bspeed\b|processing (?:rates?|times?)|cycle times?|satisfaction|NPS|valuations?|multiples?|"
    r"margins?|profit\w*|EBITDA|growth rates?|patents?", re.I)
_KEEP_GAP ="<keep the gap sentence>"  # never valid remaining words
_EXACT = re.compile(r"^(?:(its|the) )?(?:exact|precise|specific|detailed|actual)\s+", re.I)


# ---------------------------------------------------------------- tasks ---

def task_id(company: str, parameter: str, sentence: str) -> str:
    return hashlib.sha1(f"{company}|{parameter}|{sentence}".encode("utf-8")).hexdigest()[:16]


# A full stop that ends an abbreviation, not a sentence: dotted initials
# ("U.S.", "U.K.", "e.g.") and short legal / title forms ("Inc.", "Ltd.").
_ABBR = re.compile(r"(?:\b(?:[A-Za-z]\.){2,}|\b(?:Inc|Ltd|Co|Corp|Pvt|Plc|No|vs|approx|Mr|Ms|Dr|St|Jr|Sr)\.)$")
_STARTERS = {"the", "this", "these", "that", "it", "its", "as", "we", "our", "however", "based", "in", "a", "an",
             "while", "although", "since", "they", "their", "there", "for", "on", "with", "by", "from", "per"}


def sentences(text: str) -> list[str]:
    """Split into sentences, keeping an abbreviation inside its sentence: "the
    company has not disclosed U.S. sales revenue" was cut at "U.S.", so the
    estimate step asked AI Mode about "has not disclosed U.S." and got nothing
    (22 of 200 gaps left empty in U.S. Entresto, owner 2026-10-19)."""
    out: list[str] = []
    for part in _SENT.split(str(text or "").strip()):
        if not part:
            continue
        first = part.split(None, 1)[0]
        if out and _ABBR.search(out[-1]) and (
                not first[:1].isupper()
                or (re.search(r"(?:[A-Za-z]\.){2,}$", out[-1]) and first.lower().strip(",;:") not in _STARTERS)):
            out[-1] = f"{out[-1]} {part}"
        else:
            out.append(part)
    return out


def gap_object(sentence: str) -> str:
    """What the house gap sentence says was not disclosed, '' otherwise."""
    m = _GAP.match(sentence.strip())
    obj = m.group(1).strip() if m else ""
    # Step 7c's own last-fallback sentence is a decision, not a new gap.
    return "" if obj.lower().startswith("sufficient information") else obj


def estimable(obj: str) -> bool:
    return bool(obj) and bool(_QUANT.search(obj))


def _company_text(rec: dict) -> str:
    out = []
    for axis in ("x", "y"):
        for v in (rec.get(axis) or {}).values():
            out += [str(e.get("claim") or "") for e in v.get("evidence") or [] if isinstance(e, dict)]
            out.append(str(v.get("assessed_on") or ""))
    return " ".join(out)


def case_topic(topic: str, ref: str = "") -> str:
    """AI Mode's metric title in sentence case ("Revenue Growth Rate" ->
    "revenue growth rate"), keeping acronyms ("ERP", "U.S.") and every word
    the gap sentence itself writes with a capital mid-sentence ("Entresto",
    "New Jersey"): lowercasing everything printed "the company's u.s. generic
    entresto market share" (owner 2026-10-19)."""
    proper = {w.strip("(),;:") for w in str(ref or "").split()[1:] if w[:1].isupper()}
    return " ".join(w if re.fullmatch(r"\(?[A-Z0-9/&.]{2,}\)?s?", w) or w.strip("(),;:") in proper else w.lower()
                    for w in str(topic or "").split())


def gap_tasks(evidence: dict, names: Iterable[str], figures_only: bool = True) -> list[dict]:
    """Every figure gap in the companies' 'Assessed on' text, one task each
    (every gap sentence, figure or not, with figures_only=False)."""
    tasks = []
    for name in names:
        rec = evidence.get(name) or {}
        for axis in ("x", "y"):
            for p, v in (rec.get(axis) or {}).items():
                text = str(v.get("assessed_on") or "")
                for s in sentences(text):
                    obj = gap_object(s)
                    if not obj or (figures_only and not estimable(obj)):
                        continue
                    found = [str(e.get("claim") or "") for e in v.get("evidence") or []
                             if isinstance(e, dict) and str(e.get("claim") or "") != "Not available"]
                    found.append(text.replace(s, "").strip())
                    tasks.append({"id": task_id(name, p, s), "company": name, "axis": axis,
                                  "parameter": p, "gap": s, "object": obj,
                                  "findings": [f for f in found if f]})
    return tasks


def load_answers(pipe_dir: Path) -> dict[str, dict]:
    """Merged answers of every browser file, keyed by task id."""
    out: dict[str, dict] = {}
    work = Path(pipe_dir) / EST_DIR
    for f in [work / ANSWERS, *sorted(work.glob("answers_*.json"))]:
        try:
            part = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for k, v in part.items():
            if v.get("results") or k not in out:
                out[k] = v
            else:
                out[k]["asks"] = max(int(out[k].get("asks") or 0), int(v.get("asks") or 0))
    return out


def numeric_estimates_enabled() -> bool:
    """Estimates are written in words ("high", "growing", "broad across major
    ERP platforms"), never as a number or range -- the owner's choice
    (2026-10-09). QUADRANT_NUMERIC_ESTIMATES=1 brings the numeric ranges back;
    a figure the company itself reports is still quoted either way."""
    return os.environ.get("QUADRANT_NUMERIC_ESTIMATES", "0").strip().lower() in ("1", "true", "yes")


def unestimated(out_dir: Path, names: Iterable[str], answers: dict) -> list[dict]:
    """Answered gaps that still have no published estimate, asked once more
    with the firmer prompt (PUSH). A gap about an audit keeps its sentence;
    the figure behind it (an accuracy rate, say) can still be estimated."""
    if not numeric_estimates_enabled():
        return []
    out_dir = Path(out_dir)
    dec = decisions(out_dir, names)
    evidence = load_evidence(out_dir)
    return [t for t in gap_tasks(evidence, names)
            if (answers.get(t["id"]) or {}).get("results")
            and int((answers.get(t["id"]) or {}).get("asks") or 0) < MAX_ASKS
            and not any(r["value_type"] == "estimated" for r in (dec.get(t["id"]) or {}).get("estimates") or [])]


def pending(tasks: list[dict], answers: dict) -> list[dict]:
    return [t for t in tasks
            if not (answers.get(t["id"]) or {}).get("results")
            and int((answers.get(t["id"]) or {}).get("asks") or 0) < MAX_ASKS]


# ---------------------------------------------------------------- query ---

# Two questions per company. Asked for a strict JSON verdict per gap, AI Mode
# fills the template with "insufficient" without researching (live AP test:
# 36 of 37 answers, Basware's revenue included); asked in plain language for
# the calculation, it does the analysis. So: (1) the figures the company
# itself has published, as JSON (an answer to "what does it state" -- it does
# this well); (2) per gap, a worked estimate in plain text from those figures,
# ending with one summary line per figure that parse_blocks() reads.
FACTS_SYSTEM = (
    "You are a market research analyst. List the quantitative facts the company itself has published "
    "(website, annual reports, filings, press releases, investor material, official interviews): number of "
    "customers, users, partners, employees, offices, countries, deployments, projects, transactions or "
    "invoices processed, capacity, revenue for the latest year it reported (with the year), funding. One "
    "fact per item, with its year and source. Never company-data or market-research sites (ZoomInfo, "
    "RocketReach, Crunchbase, Growjo, Tracxn, report publishers). Compact JSON only: "
    '{"results":[{"fact":"","year":"","source":""}]}')


def build_facts_query(company: str, market: str, hq: str) -> str:
    where = f", {hq}" if hq else ""
    return f"Company: {company}{where}. Market: {market}."


# "its exact ARR for 2025" invites "not disclosed" as the answer; the figure
# itself ("its ARR") is what an analyst estimates. Only the question changes,
# the report keeps its own wording.
_ASK_EXACT = re.compile(r"\b(?:exact|precise|specific|explicit|detailed|actual|granular|individual|"
                        r"standardi[sz]ed|official),?\s+", re.I)


def ask_form(obj: str) -> str:
    return re.sub(r"\s{2,}", " ", _ASK_EXACT.sub("", obj)).strip()


PUSH = ("Give an analyst's best estimate (a range) for EVERY figure, even where only indirect published "
        "figures exist: market share from its revenue against the size of the market, win rates from its "
        "customer growth, performance rates from its own product claims and case studies. Answer insufficient "
        "only when the company has published no figure at all. ")


def build_estimate_prompt(company: str, market: str, hq: str, facts: list[dict], tasks: list[dict],
                          fact_chars: int = 1800, push: bool = False) -> str:
    # Worded like the question that worked live: "estimate ... show the
    # calculation". A prompt that stresses "insufficient" / "never guess"
    # got "insufficient" for every figure, even with the figures listed.
    # The safety rules are applied afterwards by judge(), not in the prompt.
    where = f", {hq}" if hq else ""
    listed = "\n".join(f"- {f['fact']} ({' '.join(x for x in (f.get('year'), f['source']) if x)})"
                       for f in facts)[:fact_chars]
    gaps = "\n".join(f"{i}. {ask_form(t['object'])}" for i, t in enumerate(tasks, 1))
    return (f"As a market research analyst, estimate figures {company} ({market}{where}) has not disclosed. "
            "Start from figures the company itself published (customers, employees, offices, volumes, revenue "
            "it reported in earlier years, funding), not company-data or market-research sites.\n"
            + (PUSH + "\n" if push else "") +
            f"Published figures:\n{listed or '- none listed'}\n\nFigures to estimate:\n{gaps}\n\n"
            "For each, show the calculation (one line per figure when an item names several), then end with "
            "one line per figure exactly like:\n"
            "n | metric | disclosed/estimated/insufficient | value or range | its <published figures used> | "
            "sources (company's own) | confidence high/medium/low")


_BLOCK = re.compile(r"^\s*(?:#+\s*)?(\d{1,2})\s*\|([^|\n]+)\|([^|\n]+)\|([^|\n]*)\|([^|\n]*)\|([^|\n]*)\|([^|\n]*)$",
                    re.M)


def parse_blocks(text: str) -> list[dict]:
    """The summary lines of a plain-text estimate answer (the echoed prompt's
    template line has no number in front, so it is skipped)."""
    out = []
    for m in _BLOCK.finditer(str(text or "")):
        n, metric, kind, value, basis, sources, conf = (x.strip() for x in m.groups())
        kind = next((k for k in ("disclosed", "estimated", "insufficient") if k in kind.lower()), "")
        conf = next((c for c in ("high", "medium", "low") if c in conf.lower()), "low")
        out.append({"n": int(n), "metric": metric, "type": kind, "value": value,
                    "basis": re.sub(r"^basis:\s*", "", basis, flags=re.I).strip(" ."), "sources": sources,
                    "confidence": conf})
    return out


def assign_blocks(blocks: list[dict], tasks: list[dict]) -> list[list[dict]]:
    """Summary lines -> the gap each belongs to, by the figure's own words.

    AI Mode numbers the lines one per FIGURE, not per gap (live: 11 lines
    numbered 1-11 for 5 gaps), so "n" alone files answers under the wrong
    gap. A line goes to the gap sharing most words with its metric (n breaks
    a tie); a line sharing none is dropped."""
    out: list[list[dict]] = [[] for _ in tasks]
    for b in blocks:
        mw = _words(b.get("metric"))
        scores = [len(mw & _words(ask_form(t["object"]))) for t in tasks]
        best = max(scores, default=0)
        if best == 0:
            continue
        hits = [i for i, sc in enumerate(scores) if sc == best]
        i = (b["n"] - 1) if (b["n"] - 1) in hits else hits[0]
        out[i].append(b)
    return out


def to_result(block: dict, facts: list[dict]) -> dict:
    """A summary line -> the shape judge() reads. The indicators are the
    company's published facts whose figures the basis uses, so the confidence
    cap counts real published figures, not the answer's own words."""
    basis_nums = _numbers(block.get("basis"))
    inds = [{"fact": f["fact"], "source": f["source"]} for f in facts
            if _numbers(f.get("fact")) & basis_nums]
    if block.get("type") == "disclosed":
        inds = [{"fact": f"{block.get('value')} -- {block.get('basis')}", "source": block.get("sources") or ""}]
    return {"n": block["n"], "metric": block.get("metric"), "type": block.get("type"),
            "value": block.get("value"), "basis": block.get("basis"), "confidence": block.get("confidence"),
            "sources": block.get("sources") or "",
            "indicators": inds, "remaining": None}


# ------------------------------------------------------------ validation ---

def _bad_source_rx() -> re.Pattern[str]:
    from vendor_intel.pipeline.factcheck import _bad_source_rx as rx

    return rx()


def _numbers(text: str) -> set[str]:
    """The figures in a text; years (1900-2099) are dates, not figures to back."""
    nums = {n.replace(",", "").rstrip(".") for n in _NUM.findall(str(text or ""))}
    return {n for n in nums if not (len(n) == 4 and n[:2] in ("19", "20") and n.isdigit())}


def _sig_digits(num: str) -> str:
    """The significant digits of a figure ('40,000' -> '4', '166.67' -> '16667')."""
    return num.replace(",", "").replace(".", "").lstrip("0").rstrip("0")


_UNIT = r"(?:%|ms|bn|[KMBkm]|[Tt]housand|[Mm]illion|[Bb]illion|[Tt]rillion)"
_CUR = r"(?:[$€£₹]|(?:INR|USD|EUR|GBP|AUD|SGD|CAD|AED|Rs\.?)\s?)"
_FIG = rf"({_CUR}?)(\d[\d,.]*)\s?({_UNIT})?(?![\w])"
_FIG_RANGE = re.compile(rf"^{_FIG}(?:\s*(?:-|–|—|to)\s*{_FIG})?")


def _unit(u: str) -> str:
    return u.lower() if u and u.lower() in ("thousand", "million", "billion", "trillion") else (u or "")


def _num(x: str) -> float:
    try:
        return float(x.replace(",", ""))
    except ValueError:
        return -1.0


_SPLIT_ITEM = re.compile(r"(\d{1,2}(?:\s*[-–]\s*\d{1,2})?)\s*%\s+([A-Za-z][A-Za-z &.-]{1,30}?)\s*(?=[/,;]|\band\b|$)")


def _breakdown(v: str) -> str:
    """'35% Nordics / 40% Rest of Europe / 25% Americas & APAC' ->
    '35% Nordics, 40% Rest of Europe and 25% Americas and APAC'; '' when the
    value is not a split whose shares add up to about 100%."""
    items = _SPLIT_ITEM.findall(v)
    if len(items) < 2:
        return ""
    mids = []
    for share, _ in items:
        ends = [float(x) for x in re.findall(r"\d+", share)]
        mids.append(sum(ends) / len(ends))
    if not 90 <= sum(mids) <= 110:
        return ""
    parts = [f"{re.sub(r'\s*[-–]\s*', '–', share)}% {label.strip().replace(' & ', ' and ')}"
             for share, label in items]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def clean_value(value: str, estimated: bool, metric: str = "") -> str:
    """'approximately $180 million - $210 million' -> '$180–210 million'.

    '' when the value is not a plain figure or range: open-ended ('120,000+'),
    zero or negative, a label instead of a number ('Average $17K ARR'), two
    different units, or an estimate with false precision ('127'). Words after
    the figure stay only when they name the metric ('30–50 countries')."""
    v = _HEDGE_LEAD.sub("", str(value or "").strip()).strip(" .")
    v = re.sub(r"\s*\([^)]*\)", "", v).strip(" .,;")
    v = re.split(r"\s+(?:annually|per year|a year|globally|worldwide)\b", v)[0].strip(" .,;")
    split = _breakdown(v)
    if split:
        return split
    # "30–40% of total bookings": a percentage keeps what it is a share of
    of = re.match(r"^(.*?%)\s+(of (?:total |all |its )?[a-z][\w -]{2,30})$", v)
    if of and clean_value(of.group(1), estimated, metric):
        return f"{clean_value(of.group(1), estimated, metric)} {of.group(2).strip()}"
    m = _FIG_RANGE.match(v)
    if not m or len(v) > 60:
        return ""
    cur1, lo, u1, cur2, hi, u2 = m.groups()
    rest = v[m.end():].strip()
    if (estimated and rest.startswith("+")) or (u1 and u2 and u1.lower() != u2.lower()):
        return ""
    nums = [_num(x) for x in (lo, hi) if x]
    if any(n <= 0 for n in nums) or (hi and _num(hi) < _num(lo)):
        return ""
    u1, u2 = _unit(u1), _unit(u2)
    lo = re.sub(r"\.0+$", "", lo)
    hi = re.sub(r"\.0+$", "", hi) if hi else hi
    unit = u2 or u1 or ""
    cur = cur1 or cur2 or ""
    if not unit and all(n >= 1_000_000 for n in nums):
        # '€20,000,000–30,000,000' reads as '€20–30 million'
        nums = [n / 1_000_000 for n in nums]
        lo, hi, unit = f"{nums[0]:g}", (f"{nums[1]:g}" if hi else None), "million"
    if estimated:
        # An estimate is round: '127' or '59' is false precision, and so is
        # a range end like '166.67'.
        sig = _sig_digits(lo)
        if not hi and unit != "%" and not (len(sig) == 1 or (len(sig) == 2 and sig[-1] in "05")):
            return ""
        if hi and max(len(_sig_digits(lo)), len(_sig_digits(hi))) > 4:
            return ""
    sep = "" if unit in ("%", "M", "B", "K", "k", "m", "bn") else " "
    fig = f"{cur}{lo}" + (f"–{hi}" if hi else "") + (f"{sep}{unit}" if unit else "")
    tail = re.findall(r"[A-Za-z][\w-]*", rest.lstrip("+ "))
    if estimated:
        if len(tail) > 4 or re.search(r"\d", rest.lstrip("+ ")):
            return ""
        words = rest.lstrip("+ ").strip(" .,;")
        return f"{fig} {words}" if words else fig
    if any(w[:5].lower() not in _words(metric) and w.lower() not in metric.lower() for w in tail):
        return ""
    return fig


def _words(text: str) -> set[str]:
    return {w[:5] for w in re.findall(r"[a-z]{4,}", str(text or "").lower())}


def _metric_ok(metric: str, obj: str) -> bool:
    return (2 < len(metric) <= 60 and not _NUM.search(metric)
            and bool(_words(metric) & _words(obj)))


def _remaining_ok(remaining: str, obj: str) -> bool:
    """The rest of the gap may only reuse the gap's own words (nothing new)."""
    words = set(re.findall(r"[a-z]{4,}", remaining.lower()))
    return bool(words) and words <= set(re.findall(r"[a-z]{4,}", obj.lower()))


def judge(result: dict, task: dict, company_text: str, *, bad=None,
          min_conf: str | None = None) -> dict | None:
    """One answer -> a publishable record, or None (nothing defensible)."""
    bad = bad or _bad_source_rx()
    min_conf = (min_conf or os.environ.get("QUADRANT_ESTIMATE_MIN_CONFIDENCE") or "low").lower()
    kind = str(result.get("type") or "").lower().strip()
    metric = re.sub(r"\s+", " ", str(result.get("metric") or "")).split(" / ")[0].strip(" .")
    metric = re.sub(r"\s{2,}", " ", _ASK_EXACT.sub("", metric).replace(" ,", "")).strip(" ,.")
    metric = re.sub(r"\b(?:for |in )?(?:fiscal year |FY ?)?(?:19|20)\d\d\b|\bFY\d{2}\b", "", metric)
    metric = re.sub(r"\b(?:audited|independently|independent|third-party|verified|validated|documented|"
                    r"guaranteed|maximum|minimum)\s+", "", metric, flags=re.I)
    metric = re.sub(r"\s{2,}", " ", metric).strip(" ,.")
    metric = case_topic(metric, task.get("gap", ""))
    if kind not in ("disclosed", "estimated") or not _metric_ok(metric, task["object"]):
        return None
    if kind == "estimated" and not numeric_estimates_enabled():
        return None  # owner's choice: estimates are written in words, never as a range
    indicators = []
    for ind in result.get("indicators") or []:
        if not isinstance(ind, dict):
            continue
        fact, src = str(ind.get("fact") or "").strip(), str(ind.get("source") or "").strip()
        if fact and src and _NUM.search(fact) and not bad.search(f"{fact} {src}"):
            indicators.append({"fact": fact, "source": src})
    if not indicators and kind == "estimated":
        # The basis may rest on a figure the report's own evidence already
        # states (company-reported, gathered in step 5).
        want = _numbers(result.get("basis"))
        indicators = [{"fact": s.strip(), "source": "company-reported evidence in this report"}
                      for s in sentences(company_text)
                      if want & _numbers(s) and not bad.search(s)][:3]
    stated = False
    # An answer whose every source was a banned data / research site rests
    # on modelled numbers: it never falls back to its stated basis.
    gave_only_bad = bool(result.get("indicators")) and not indicators
    if (not indicators and not gave_only_bad and kind == "estimated"
            and _NUM.search(str(result.get("basis") or ""))
            and not bad.search(str(result.get("sources") or ""))):
        indicators = [{"fact": str(result.get("basis")), "source": str(result.get("sources") or "primary research")}]
        stated = True
    if not indicators:
        return None
    cited = _numbers(" ".join(i["fact"] for i in indicators))
    known = cited | _numbers(company_text)
    value = clean_value(str(result.get("value") or ""), kind == "estimated", metric)
    if not value:
        return None
    if kind == "disclosed":
        # The figure itself must come from a cited first-party statement.
        if not _numbers(value) <= cited:
            return None
        return {"metric": metric, "value_type": "disclosed", "value": value,
                "source": indicators[0]["source"], "source_type": SOURCE_TYPE}
    basis = _LEAD_BASIS.sub("", re.sub(r"\s+", " ", str(result.get("basis") or "")).strip(" ."))
    basis = re.sub(r"\s*;\s*", ", ", basis.replace(" / ", " and "))
    # Every estimate rests on at least one figure the company itself
    # published (or the report already states); it never names a research
    # firm or data site. Owner's choice: estimate every figure gap -- market
    # share and performance figures included -- in the analyst's voice.
    if (not basis or len(basis) > 260 or "http" in basis or bad.search(basis)
            or not _NUM.search(basis) or not (_numbers(basis) & known)):
        return None
    cap = "low" if stated else "high" if len(indicators) >= 3 else "medium" if len(indicators) == 2 else "low"
    said = str(result.get("confidence") or "low").lower()
    conf = LEVELS[min(LEVELS.index(said) if said in LEVELS else 0, LEVELS.index(cap))]
    if LEVELS.index(conf) < LEVELS.index(min_conf if min_conf in LEVELS else "medium"):
        return None
    # list items read as one phrase: "Processes $300 billion" -> "processes ..."
    items = re.split(r"(, | and )", basis)
    basis = "".join(x if x in (", ", " and ") or re.match(r"[A-Z]{2,}|[A-Z][a-z]*[A-Z]", x)
                    else x[:1].lower() + x[1:] for x in items)
    if " and " not in basis and basis.count(", ") >= 1:
        head, _, last = basis.rpartition(", ")
        basis = f"{head} and {last}"
    if re.match(r"(?:serves|served|processes|processed|operates|powers|automates|manages|handles|supports|"
                r"reports|reported|has|had|employs|reaches|reached|surpassed|raised|counts|covers|works)\b",
                basis, re.I):
        basis = "the fact that it " + basis[0].lower() + basis[1:]
    elif not basis.lower().startswith(("its ", "the ", "a ", "an ")):
        basis = "its " + basis[0].lower() + basis[1:] if not basis[:2].isupper() else basis
    return {"metric": metric, "value_type": "estimated", "estimated_value": value, "confidence": conf,
            "basis": basis, "indicators": indicators, "source_type": SOURCE_TYPE}


def _verb(metric: str) -> str:
    """'is' / 'are' for the metric's head noun ('number of countries' -> is)."""
    head = re.sub(r"\s*\(.*?\)", "", metric).split(" of ")[0].split()[-1:] or [""]
    w = head[0].lower()
    return "are" if w.endswith("s") and not w.endswith(("ss", "us", "is")) and w not in ("sales",) else "is"


def statement(rec: dict) -> str:
    if rec["value_type"] == "disclosed":
        return f"Based on primary research, the company reports its {rec['metric']} as {rec['value']}."
    if rec["value_type"] == "estimated":
        # The analyst's own estimate, beside the gap it answers: "can be
        # estimated at approximately", never worded as a reported figure.
        return (f"The company's {rec['metric']} can be estimated at approximately {rec['estimated_value']}, "
                f"derived from {rec['basis']}.")
    if rec["value_type"] == "estimated_qualitative":
        return f"The company's {rec['metric']} can be estimated as {rec['estimated_value']}, based on {rec['basis']}."
    return f"{PR} sufficient information to support a reliable quantitative estimate for {rec['metric']}."


def after_gap(gap: str, recs: list[dict]) -> str:
    """The estimate IN PLACE OF the gap sentence (owner's choice): 'Based on
    primary research, the company's X can be estimated as high, based on ...'.
    The 'has not disclosed' sentence is not kept beside it; a second estimate
    for the same gap follows without repeating the lead-in. Without any
    estimate the gap sentence stays."""
    est_parts = [statement(r) for r in recs if r["value_type"] in ("estimated", "estimated_qualitative")]
    if not est_parts:
        return gap
    est_parts[0] = "Based on primary research, the" + est_parts[0][len("The"):]
    return " ".join(est_parts)


def decide(task: dict, results: list[dict], company_text: str, *, bad=None,
           min_conf: str | None = None) -> dict | None:
    """{"text": replacement for the gap sentence, "estimates": [...]} or None
    when the gap sentence stays as it is."""
    mine = [r for r in results if isinstance(r, dict)]
    recs, seen = [], set()
    for r in mine:
        rec = judge(r, task, company_text, bad=bad, min_conf=min_conf)
        # one figure of each kind per gap: "standalone revenue" and "ARR" for
        # the same gap are two ranges for one number
        if rec and figure_kind(rec["metric"]) not in seen:
            seen.add(figure_kind(rec["metric"]))
            recs.append(rec)
    remaining = next((str(r.get("remaining") or "").strip(" .") for r in mine
                      if str(r.get("remaining") or "").strip(" .")), "")
    obj = task["object"]
    if mine and all(r.get("remaining", "") is None for r in mine):
        # Plain-text answer: no "remaining" words. The gap sentence goes only
        # when every figure it names was answered with a published figure.
        if not recs:
            if all(str(r.get("type") or "") == "insufficient" for r in mine) and not _PROOF.search(obj):
                remaining = ""
            else:
                return None
        elif (len(recs) == len(mine) and not _PROOF.search(obj)
              and any(r["value_type"] == "disclosed" for r in recs)):
            # a reported figure answers the gap: "not disclosed" would be wrong
            return {"text": " ".join(map(statement, recs)), "estimates": recs}
        else:
            # Estimates only: the gap stays and the analyst's estimate follows
            # it ("has not disclosed X. However, X can be estimated at ...").
            remaining = _KEEP_GAP
    if not recs:
        # Last fallback: a gap that is only a figure, judged insufficient.
        if (mine and all(str(r.get("type") or "").lower() == "insufficient" for r in mine)
                and not remaining and not _PROOF.search(obj)):
            what = _EXACT.sub(lambda m: f"{m.group(1)} " if m.group(1) else "", obj)
            rec = {"metric": what, "value_type": "not_available", "confidence": "low",
                   "reason": "Insufficient primary evidence to support a defensible quantitative estimate.",
                   "source_type": SOURCE_TYPE}
            return {"text": statement(rec), "estimates": [rec]}
        return None
    if (remaining and not _remaining_ok(remaining, obj)) or (not remaining and _PROOF.search(obj)):
        # The rest of the gap cannot be restated safely: keep the original
        # sentence and add only estimates (an estimate sits beside "not
        # disclosed"; a disclosed figure would contradict it).
        recs = [r for r in recs if r["value_type"] == "estimated"]
        if not recs:
            return None
        return {"text": after_gap(task["gap"], recs), "estimates": recs}
    if not any(r["value_type"] == "disclosed" for r in recs):
        return {"text": after_gap(task["gap"], recs), "estimates": recs}
    parts = [statement(r) for r in recs]
    if remaining:
        parts.append(f"{PR} {remaining}.")
    return {"text": " ".join(parts), "estimates": recs}


# ---------------------------------------------------------------- apply ---

_KINDS = (("revenue", r"revenue|ARR|MRR|sales|turnover|bookings"), ("contract", r"contract|deal|ACV"),
          ("employees", r"employee|headcount|staff|workforce|team size"),
          ("customers", r"customer|client|user|subscriber|accounts"),
          ("footprint", r"countr|office|location|site|facilit|branch"),
          ("deployments", r"deployment|installation|implementation|project"),
          ("partners", r"partner|reseller"), ("volume", r"transaction|invoice|volume|spend|capacity"))


def figure_kind(metric: str) -> str:
    # A split or share of the business (regional revenue break-down, channel
    # share of sales) is its own figure, not a second estimate of the total.
    if _SPLIT_METRIC.search(metric):
        return metric.lower()
    for kind, rx in _KINDS:
        if re.search(rx, metric, re.I):
            return kind
    return metric.lower()


def decisions(out_dir: Path, names: Iterable[str] | None = None, *, min_conf: str | None = None
              ) -> dict[str, dict]:
    out_dir = Path(out_dir)
    evidence = load_evidence(out_dir)
    names = list(names) if names is not None else list(evidence)
    answers = load_answers(out_dir / "_pipeline")
    bad = _bad_source_rx()
    text = {n: _company_text(evidence.get(n) or {}) for n in names}
    out = {}
    # One estimate per kind of figure per company: answers to different gaps
    # gave the same company three different revenue ranges (live AP run).
    # The first stands; a later one of the same kind is not published.
    seen: set[tuple[str, str]] = set()
    for t in gap_tasks(evidence, names):
        res = (answers.get(t["id"]) or {}).get("results") or []
        res = [r for r in res if str(r.get("type") or "") != "estimated"
               or (t["company"], figure_kind(str(r.get("metric") or "").split(" / ")[0])) not in seen]
        d = decide(t, res, text[t["company"]], bad=bad, min_conf=min_conf) if res else None
        for r in (d or {}).get("estimates") or []:
            if r["value_type"] == "estimated":
                seen.add((t["company"], figure_kind(r["metric"])))
        if d:
            out[t["id"]] = {**d, "company": t["company"], "parameter": t["parameter"], "gap": t["gap"]}
    # Every other gap sentence (and a figure gap no figure could answer)
    # gets the analyst's estimate in words (owner: an estimate after every
    # "has not disclosed", numbers only where a figure is defensible).
    for t in gap_tasks(evidence, names, figures_only=False):
        cur = out.get(t["id"])
        if cur and any(r["value_type"] in ("estimated", "disclosed") for r in cur["estimates"]):
            continue
        res = (answers.get(WORDED + t["id"]) or {}).get("results") or []
        recs, topics = [], set()
        for r in res:
            rec = judge_worded(r, t, bad=bad)
            if rec and rec["metric"] not in topics:
                topics.add(rec["metric"])
                recs.append(rec)
        if recs:
            out[t["id"]] = {"text": after_gap(t["gap"], recs[:2]), "estimates": recs[:2],
                            "company": t["company"], "parameter": t["parameter"], "gap": t["gap"]}
    return out


# ------------------------------------------------------ worded estimates ---
# A gap that is not a number ("independent performance data on turnaround",
# "native connectors for SAP") still gets an analyst's estimate -- in words,
# never a figure: "However, the company's approval turnaround can be
# estimated as fast for most approvals, based on its conditional routing
# rules and mobile approvals."
WORDED = "w"
# A figure in the estimate itself (not a digit inside a name like "B2B" or "S/4HANA").
_FIGURE = re.compile(r"(?<![A-Za-z/])\d[\d,.]*(?![A-Za-z])")


def build_worded_prompt(company: str, market: str, hq: str, facts: list[dict], tasks: list[dict],
                        fact_chars: int = 1500) -> str:
    where = f", {hq}" if hq else ""
    listed = "\n".join(f"- {f['fact']}" for f in facts)[:fact_chars]
    gaps = "\n".join(f"{i}. {ask_form(t['object'])}" for i, t in enumerate(tasks, 1))
    return (f"As a market research analyst, give your best estimate IN WORDS (no numbers) for each item "
            f"{company} ({market}{where}) has not disclosed, from what the company itself has published "
            "(features, customers, case studies, partners, press releases), not company-data or "
            "market-research sites. Examples of an estimate: 'high', 'growing steadily', 'fast for most approvals', 'broad across the "
            "major ERP platforms', 'limited to a few markets', 'strong, in line with leading vendors'. Use words "
            "only: no number, percentage or range in the estimate (figures belong in the basis). Never "
            "answer unknown, unverified or unavailable. For an item about third-party verification, audits or "
            "certification, estimate the underlying capability or performance itself (e.g. 'fast for most "
            "approvals'), not whether it is verified. The estimate is in words; the basis is a short phrase starting "
            "with 'its' and may use the company's own figures (e.g. 'its 6,500 customers and SAP partnership').\n"
            f"Published facts:\n{listed or '- none listed'}\n\nItems:\n{gaps}\n\n"
            "End with one line per item exactly like:\n"
            "n | what is estimated (short noun phrase) | estimate in words | its <published facts used, in "
            "words> | sources (company's own) | confidence high/medium/low")


_WBLOCK = re.compile(r"^\s*(?:#+\s*)?(\d{1,2})\s*\|([^|\n]+)\|([^|\n]+)\|([^|\n]*)\|([^|\n]*)\|([^|\n]*)$", re.M)


def parse_worded(text: str) -> list[dict]:
    out = []
    for m in _WBLOCK.finditer(str(text or "")):
        n, topic, value, basis, sources, conf = (x.strip() for x in m.groups())
        if topic.lower().startswith("what is estimated"):
            continue
        out.append({"n": int(n), "metric": topic, "type": "worded", "value": value, "basis": basis,
                    "sources": sources, "confidence": next((c for c in LEVELS if c in conf.lower()), "low")})
    return out


_NO_ESTIMATE = re.compile(r"\b(?:unknown|undisclosed|not (?:disclosed|available|known|public)|unclear|cannot|"
                          r"insufficient|no (?:data|information|evidence)|n/a|unverified|not determinable|"
                          r"unavailable|proprietary|confidential|non-public|not published)\b",
                          re.I)

_ONES = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen".split())}
_TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if i > 1}
_SCALE = {"thousand": 1_000, "million": 1_000_000}
_BIG = ("million", "billion", "trillion")
_MONTHS = ("January|February|March|April|May|June|July|August|September|October|November|December|"
           "Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec")
_NUMWORD = r"(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|" \
           r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|" \
           r"thousand|million|billion|trillion|point)"
_NUMRUN = re.compile(rf"\b{_NUMWORD}(?:(?:[\s-]+|\s+and\s+){_NUMWORD})*\b", re.I)


def _run_value(words: list[str]) -> str | None:
    """['two', 'thousand', 'seventy-seven'] -> '2,077'; ['three', 'point', 'five'] -> '3.5'."""
    if "point" in words:
        i = words.index("point")
        whole = _run_value(words[:i]) if words[:i] else "0"
        digits = "".join(str(_ONES[w]) for w in words[i + 1:] if w in _ONES and _ONES[w] < 10)
        if whole is None or not digits:
            return None
        return f"{whole}.{digits}"
    total, cur = 0, 0
    for w in words:
        if w in _ONES:
            cur += _ONES[w]
        elif w in _TENS:
            cur += _TENS[w]
        elif w == "hundred":
            cur = (cur or 1) * 100
        elif w in _SCALE:
            total += (cur or 1) * _SCALE[w]
            cur = 0
        elif w != "and":
            return None
    n = total + cur
    return f"{n:,}"


def words_to_figures(text: str) -> str:
    """'two thousand seventy-seven employees' -> '2,077 employees', 'thirty million
    dollars' -> '30 million dollars', 'eighty percent' -> '80%'. A lone 'one' is left."""
    def sub(m: re.Match) -> str:
        words = [w for w in re.split(r"[\s-]+", m.group(0).lower()) if w]
        if words == ["one"] or all(w == "and" for w in words):
            return m.group(0)
        if words[-1] in _BIG:  # "ten trillion" -> "10 trillion", not 10,000,000,000,000
            head = _run_value(words[:-1]) if len(words) > 1 else None
            return f"{head} {words[-1]}" if head is not None else m.group(0)
        val = _run_value(words)
        if val is None:
            return m.group(0)
        # A year is written without a thousands comma: "in September two
        # thousand twenty-six" read "September 2,026" (owner 2026-10-19).
        before = m.string[max(0, m.start() - 12):m.start()]
        if re.fullmatch(r"(?:19|20)\d\d", val.replace(",", "")) and re.search(
                rf"\b(?:{_MONTHS}|in|since|until|year|fiscal|FY)\s*$", before, re.I):
            return val.replace(",", "")
        return val

    out = _NUMRUN.sub(sub, str(text or ""))
    out = re.sub(r"(\d)\s+percent\b", r"\1%", out)
    return re.sub(r"(\d[\d,.]*)\s+(million|billion|trillion)\s+(?:US\s+)?dollars\b", r"$\1 \2", out)


def judge_worded(result: dict, task: dict, *, bad=None) -> dict | None:
    """A worded estimate -> a publishable record, or None. No figure in the
    estimate itself, a basis that names no research firm or data site."""
    bad = bad or _bad_source_rx()
    topic = re.sub(r"\s+", " ", str(result.get("metric") or "")).split(" / ")[0].strip(" .")
    topic = re.sub(r"\b(?:audited|independently|independent|third-party|verified|validated|documented|"
                   r"certified|guaranteed|exact|precise|specific|explicit|detailed)\s+", "", topic, flags=re.I)
    topic = case_topic(topic, task.get("gap", ""))
    topic = re.sub(r"^(?:its|the company's|the)\s+", "", topic).strip(" ,.")
    value = re.sub(r"\s+", " ", str(result.get("value") or "")).strip(" .")
    value = value[:1].lower() + value[1:] if value[:2] != value[:2].upper() else value
    basis = _LEAD_BASIS.sub("", re.sub(r"\s+", " ", str(result.get("basis") or "")).strip(" ."))
    basis = words_to_figures(re.sub(r"\s*;\s*", ", ", basis.replace(" / ", " and ")))
    topic = topic[:110].rsplit(" ", 1)[0] if len(topic) > 110 else topic
    if (not topic or not (_words(topic) & _words(task["object"]))
            or not value or _FIGURE.search(value) or not 1 <= len(value.split()) <= 25 or _NO_ESTIMATE.search(value)
            or not basis or len(basis) > 240 or "http" in basis or _NO_ESTIMATE.search(basis)
            or bad.search(f"{value} {basis} {result.get('sources') or ''}")):
        return None
    if re.match(r"(?:serves|offers|provides|supports|processes|operates|has|reports|integrates|uses)\b", basis, re.I):
        basis = "the fact that it " + basis[0].lower() + basis[1:]
    elif not basis.lower().startswith(("its ", "the ", "a ", "an ")):
        basis = "its " + basis[0].lower() + basis[1:] if not basis[:2].isupper() else basis
    return {"metric": topic, "value_type": "estimated_qualitative", "estimated_value": value,
            "confidence": next((c for c in LEVELS if c == str(result.get("confidence") or "").lower()), "low"),
            "basis": basis, "source": str(result.get("sources") or ""), "source_type": SOURCE_TYPE}


def worded_needed(out_dir: Path, names: Iterable[str], answers: dict) -> list[dict]:
    """Gap sentences still without any estimate, to ask for one in words."""
    out_dir = Path(out_dir)
    dec = decisions(out_dir, names)
    evidence = load_evidence(out_dir)
    out = []
    for t in gap_tasks(evidence, names, figures_only=False):
        if any(r["value_type"] in ("estimated", "disclosed", "estimated_qualitative")
               for r in (dec.get(t["id"]) or {}).get("estimates") or []):
            continue
        prev = answers.get(WORDED + t["id"]) or {}
        if int(prev.get("asks") or 0) >= MAX_ASKS:
            continue
        out.append({**t, "id": WORDED + t["id"], "mode": "worded", "asks": int(prev.get("asks") or 0),
                    "prev": prev.get("results") or []})
    return out


def apply_estimates(out_dir: Path, names: Iterable[str] | None = None) -> dict[str, int]:
    """Write the decisions into every evidence sidecar ('Assessed on' text +
    the parameter's ``estimates`` list); re-running is a no-op."""
    out_dir = Path(out_dir)
    dec = decisions(out_dir, names)
    counts = {"disclosed": 0, "estimated": 0, "estimated_qualitative": 0, "not_available": 0}
    for d in dec.values():
        for r in d["estimates"]:
            counts[r["value_type"]] += 1
    if not dec:
        return counts
    for side in sorted(out_dir.glob("param_detail_prescored*.json")):
        try:
            part = json.loads(side.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        changed = False
        for name, rec in part.items():
            for axis in ("x", "y"):
                for p, v in ((rec.get(axis) or {}).get("parameters") or {}).items():
                    if not isinstance(v, dict) or not v.get("assessed_on"):
                        continue
                    text = str(v["assessed_on"])
                    for s in sentences(text):
                        d = dec.get(task_id(name, p, s))
                        # the gap sentence stays beside its estimate, so a
                        # re-run finds it again: already applied = skip
                        if not d or d["text"] in text:
                            continue
                        text = text.replace(s, d["text"])
                        have = {(e.get("metric"), e.get("value_type")) for e in v.get("estimates") or []}
                        v["estimates"] = [*(v.get("estimates") or []),
                                          *(e for e in d["estimates"]
                                            if (e["metric"], e["value_type"]) not in have)]
                    if text != v["assessed_on"]:
                        v["assessed_on"] = text
                        changed = True
        if changed:
            write_json_atomic(side, part, indent=1)
    write_review(out_dir / "_pipeline", dec)
    return counts


def write_review(pipe_dir: Path, dec: dict[str, dict]) -> Path:
    """estimates.md: every published figure with its basis, for an analyst."""
    lines = ["# Quantitative estimates (step 7c) -- for analyst review", "",
             "Fix or remove one with a `corrections` entry in analyst_review.json "
             "(find = the sentence below).", ""]
    for d in sorted(dec.values(), key=lambda d: (d["company"], d["parameter"])):
        lines.append(f"## {d['company']} / {d['parameter']}")
        lines.append(f"- was: {d['gap']}")
        lines.append(f"- now: {d['text']}")
        for r in d["estimates"]:
            if r["value_type"] == "estimated":
                lines.append(f"  - {r['confidence']} confidence; indicators: "
                             + "; ".join(f"{i['fact']} ({i['source']})" for i in r.get("indicators") or []))
        lines.append("")
    work = Path(pipe_dir) / EST_DIR
    work.mkdir(parents=True, exist_ok=True)
    path = work / "estimates.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def verify_report(brands: list[dict]) -> list[str]:
    """Problems with the estimate statements of a built report ([] = fine)."""
    bad = []
    for b in brands:
        for axis in ("x", "y"):
            for p, v in (((b.get("score_detail") or {}).get(axis) or {}).get("parameters") or {}).items():
                text = str(v.get("assessed_on") or "")
                for e in v.get("estimates") or []:
                    # The report carries the house wording ("... is approximately",
                    # "... is <estimate>, based on ..."; house_wording.py); the old
                    # "can be estimated" form is still accepted.
                    m, val = e.get("metric"), e.get("estimated_value")
                    if e.get("value_type") == "estimated" and not (
                            e.get("basis") and e.get("confidence") in LEVELS
                            and (f"{m} can be estimated at approximately {val}" in text
                                 or f"{m} is approximately {val}" in text)):
                        bad.append(f"{b.get('company')} / {p}: {m}")
                    if e.get("value_type") == "estimated_qualitative":
                        s = next((s for s in sentences(text) if f"{m} is {val}" in s
                                  or f"{m} can be estimated as {val}" in s), "")
                        if s and (", based on " not in s or _FIGURE.search(str(val or ""))):
                            bad.append(f"{b.get('company')} / {p}: worded estimate without basis or with a number")
                for s in sentences(text):
                    if " can be estimated at " in s and not ("approximately" in s and "derived from" in s):
                        bad.append(f"{b.get('company')} / {p}: unlabelled estimate")
                    if " can be estimated as " in s and (", based on " not in s or _FIGURE.search(
                            s.split(" can be estimated as ", 1)[1].split(", based on ")[0])):
                        bad.append(f"{b.get('company')} / {p}: worded estimate without basis or with a number")
    return bad
