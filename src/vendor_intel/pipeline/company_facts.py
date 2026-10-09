"""Ownership and identity facts for the chatgpt_expand quadrant pipeline, and
the evidence tidy-up every report gets.

Three generic guards (no market-specific data; the market name and scope come
from the run):

1. Ownership (Google AI Mode, ``scripts/check_company_facts.py --mode ownership``)
   -> ``_pipeline/ownership.json``: ``{name: {acquired, acquirer, year, today, note}}``.
   A company bought by another but still trading under its own name gets the
   Company column "Name (acquired by Owner)". One bought and absorbed (its own
   name gone) or closed is left out, as is an old name whose rebranded name is
   also listed (the same company twice).

2. Identity (``--mode identity``), asked one company at a time for status
   answers that gave no event ("defunct" with no closure, "renamed", unclear
   ownership) -> ``_pipeline/identity_check.json``. A company that does not
   exist, is not in this market, or is shown inactive with an event is left
   out; a bare "defunct" the check cannot confirm exists is left out too.

2b. Scope (``--mode scope``), 10 companies per query -> ``_pipeline/scope_check.json``:
   core | adjacent | out. "out" is left out of the report; "adjacent" (a
   neighbouring segment -- another value-chain step, end use or a much
   narrower variant) stays in Other Noticeable Players but is never placed on
   the chart, so the quadrant compares like with like.

3. Supporting points: a bullet that only says nothing was found reads
   "Not available"; a parameter shows "Not available" only when it has no real
   finding, and then once.

Decisions are written to ``_pipeline/auto_review.json`` (``exclude`` and
``ownership``, each with reason + source), which company_status.load_review
merges with the analyst's own ``analyst_review.json``. The analyst file always
wins: its ``ownership`` entries replace automatic ones (``"owner": ""`` clears
a label) and its ``keep`` list undoes an automatic exclusion.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from vendor_intel.pipeline.quadrant_pipeline import norm_name, write_json_atomic

OWNERSHIP_FILE = "ownership.json"
IDENTITY_FILE = "identity_check.json"
SCOPE_FILE = "scope_check.json"
HQ_FILE = "hq_check.json"
SCOPES = ("core", "adjacent", "out")
# An acquisition older than this reads "subsidiary of": "acquired by" implies
# a recent deal (an audit flagged a 1998 purchase labelled as a new one).
RECENT_DEAL_YEARS = 3
AUTO_REVIEW_FILE = "auto_review.json"
NOT_AVAILABLE = "Not available"
SOURCE = "Automatic ownership / identity review (Google AI Mode)"


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _true(v: Any) -> bool:
    return str(v).strip().lower() == "true"


# -- prompts -----------------------------------------------------------------

def ownership_prompt(market: str, scope: str) -> str:
    return (
        "You are a market research analyst checking the ownership history of companies "
        "in a market landscape. Answer from verifiable facts only: acquisitions, "
        "majority-stake purchases, mergers and asset purchases.\n"
        f"Market: {market}\n" + (f"Market scope: {scope}\n" if scope else "")
        + "For EACH company: acquired = true if another company bought it (or a majority "
        "stake in it, or its business/assets) at any time, else false. acquirer = the "
        "buyer's name; year = the year of the deal; today = one of independent | "
        "subsidiary (still trades under its own name, owned by the acquirer) | absorbed "
        "(merged into the acquirer, own name gone) | closed | unknown. note = one short "
        "factual sentence with the deal, including any rename ('rebranded as ...'). If "
        "you are not sure a deal happened, answer acquired=false with today=unknown; "
        "never guess an acquirer. A company that bought another is NOT acquired. "
        "current_name = the name the business trades under today if it differs from the "
        "listed name, else empty. brand_status = legacy if the listed brand has been "
        "retired or divested (its capabilities now sold under another name), else current.\n"
        "Return one result for EVERY company, never skip a name. Compact JSON only: "
        '{"results":[{"name":"...","acquired":true,"acquirer":"...","year":"...",'
        '"today":"...","note":"...","current_name":"","brand_status":"current"}]}'
    )


def ownership_question(name: str, website: str = "") -> str:
    return (f"Who owns {name}" + (f" ({website})" if website else "")
            + ", and has it ever been acquired by another company? Is it still operating?")


def identity_prompt(market: str, scope: str) -> str:
    return (
        f"You are a market research analyst checking a company listed in a {market} "
        "report. Use published facts only (company website, registries, stock-exchange "
        "filings, press releases, news). exists = does a real company by this name exist; "
        "website_is_theirs = does the given website belong to this company (true/false/"
        "unknown; website_owner = who it belongs to if not); operating = active | inactive "
        "| acquired | renamed | unknown, with event and year when not active; in_market = "
        "does the company actually offer what this market covers (true/false/unknown); "
        "evidence = one or two short factual sentences with the source type. Never guess.\n"
        + (f"Market scope: {scope}\n" if scope else "")
        + 'Compact JSON only: {"results":[{"name":"...","exists":"true|false|unknown",'
        '"website_is_theirs":"...","website_owner":"","operating":"...","event":"",'
        '"year":"","in_market":"true|false|unknown","evidence":"..."}]}'
    )


def scope_prompt(market: str, definition: str, core: str = "", adjacent: Iterable[str] = ()) -> str:
    """Core player, adjacent-segment player, or not in the market at all."""
    adj = "; ".join(a for a in adjacent if a)
    return (
        "You are a market research analyst building a like-for-like landscape. For EACH "
        "company decide whether its MAIN business is this market itself.\n"
        f"Market: {market}\n" + (f"Market definition: {definition}\n" if definition else "")
        + (f"Core players: {core}\n" if core else "")
        + (f"Adjacent segments (not core): {adj}\n" if adj else "")
        + "scope = core (its main business is what this market covers, at the scale the "
        "market implies) | adjacent (related but its main business is a neighbouring "
        "segment: another step of the value chain, a different end use or customer "
        "industry, or a much narrower or smaller-scale variant) | out (not in this market). "
        "The product test: core only when this market's product IS the company's main product "
        "and most of its revenue. When the company offers it as a module, feature or add-on "
        "inside a different main product or service (another software category, a services or "
        "outsourcing business, a leasing / payments / card business, a security or installation "
        "business, a data feed resold to others, or a reseller of another vendor's platform), "
        "answer adjacent -- UNLESS the market definition or core players above explicitly "
        "include such modules or platforms, in which case they are core. Judge from what the "
        "company sells today, not from one project. "
        "reason = one short factual sentence naming its main product.\n"
        "Return one result for EVERY company. Compact JSON only: "
        '{"results":[{"name":"...","scope":"core|adjacent|out","reason":"..."}]}'
    )


def hq_prompt(market: str, country: str) -> str:
    """Single-country runs: is the company run from that country, or is the
    listed address only a local branch of a company headquartered abroad?
    Observed live: Transpoco (global HQ Dublin) was listed for the UK because
    it has a UK office address."""
    return (
        "You are a market research analyst checking where companies are headquartered. Use the "
        "company's own website, registry filings and press releases.\n"
        f"Market: {market}\nCountry of this report: {country}\n"
        "For EACH company: hq = city and country of the company's OWN head office (where the "
        "operating company is run from -- not its parent group's, not a branch); in_country = true "
        f"if that head office is in {country}, false if the company is run from another country and "
        f"only has a branch, sales office or subsidiary address in {country}, unknown if unsure. A "
        f"company headquartered in {country} but owned by a foreign group is in_country = true. "
        "evidence = one short factual sentence with the source. Never guess.\n"
        "Return one result for EVERY company. Compact JSON only: "
        '{"results":[{"name":"...","hq":"...","in_country":"true|false|unknown","evidence":"..."}]}'
    )


def identity_question(name: str, market: str, website: str = "", hq: str = "") -> str:
    return (f"Company: {name}" + (f", listed website {website}" if website else "")
            + (f", listed headquarters {hq}" if hq else "")
            + f". Does this company exist, is that its website, and is it still operating "
              f"today in the {market}?")


# -- decisions ----------------------------------------------------------------

# A real purchase. "Established as a subsidiary" or "formed by a
# reorganisation" is ownership, not an acquisition, and gets no label.
# "completed the acquisition of X" / "a take-private" / "a buyout" are purchases
# too; missing them left Thoma Bravo's Coupa and TPG's AvidXchange unlabelled.
_ACQ = re.compile(r"\b(acquir\w*|acquisitions?|bought|purchas\w*|took over|takeover|majority stake|"
                  r"stake in|merge[dr]?\w*|buy-?outs?|take[- ]private|taken private)\b", re.I)
_NOT_ACQ = re.compile(r"\b(established|founded|formed|set up|incorporated|created|spun off)\b"
                      r"[^.]{0,40}?\b(as|by)\b", re.I)
_RENAMED_TO = re.compile(r"\b(?:rebranded|renamed)\s+(?:as|to|into)\s+([A-Z][^.,;()]{2,80})")


_PASSIVE_BEFORE = re.compile(r"\b(was|were|been|being|is|are|get|got)\s+(\w+\s+)?$", re.I)
_DEAL_VERB = re.compile(r"\b(acquired|bought|purchased|took over|acquires|buys)\b", re.I)


def is_buyer(name: str, rec: dict) -> bool:
    """True when the answer actually describes the company BUYING someone.

    Observed live: "Inseego UK's fleet division was acquired by Ctrack" came
    back as acquired=true for Ctrack UK, and "Moving Intelligence acquired
    Phantom Tracking" as acquired=true for Moving Intelligence -- both buyers,
    both active, both wrongly removed."""
    own = norm_name(name)
    acq = norm_name(str(rec.get("acquirer") or ""))
    if own and acq and (acq in own or own in acq):
        return True                  # the "acquirer" is the company itself
    note = str(rec.get("note") or "")
    m = _DEAL_VERB.search(note)
    if not (own and m):
        return False
    before = note[:m.start()]
    if _PASSIVE_BEFORE.search(before):
        return False                 # "X was acquired by ..." -- X was bought
    first = own.split()[0]
    return len(first) > 2 and first in norm_name(before)  # "<Company> acquired Y"


def is_unclear(rec: dict) -> bool:
    return not _true(rec.get("acquired")) and str(rec.get("today") or "").lower() in ("", "unknown")


def ownership_relation(year: Any, *, today_year: int | None = None) -> str:
    """'acquired_by' for a recent deal, 'subsidiary_of' for a long-held one
    (or when the year is unknown, which says nothing about recency)."""
    import datetime

    now = today_year or datetime.date.today().year
    m = re.search(r"(19|20)\d{2}", str(year or ""))
    if m and now - int(m.group(0)) < RECENT_DEAL_YEARS:
        return "acquired_by"
    return "subsidiary_of"


def owner_entry(name: str, rec: dict) -> dict | None:
    """Label only a real acquisition of a company that still trades under its own name."""
    owner = str(rec.get("acquirer") or "").strip()
    note = str(rec.get("note") or "").strip()
    if not (_true(rec.get("acquired")) and owner and str(rec.get("today") or "").lower() == "subsidiary"):
        return None
    if not _ACQ.search(note) or _NOT_ACQ.search(note) or is_buyer(name, rec):
        return None
    if norm_name(owner) == norm_name(name):
        return None
    # "acquired a 31% stake": a minority investment, not an owner ("the
    # remaining 49%" completes a purchase, so it does count).
    shares = [float(s) for s in re.findall(r"(\d{1,2}(?:\.\d+)?)\s*%", note)]
    if shares and max(shares) < 50 and not re.search(r"\b(?:majority|remaining|wholly|full|entire)\b", note, re.I):
        return None
    # "Emburse was acquired by Certify ... the combined company rebranded under
    # the Emburse name": the buyer took this company's name and no longer
    # exists apart from it, so there is no separate owner to show.
    first = norm_name(name).split(" ")[0] if norm_name(name) else ""
    took = re.search(r"\b(?:rebrand\w*|renam\w*)\s+(?:under|as|to|into)\s+(?:the\s+)?"
                     r"([A-Z][\w&.\- ]{1,60})", note)
    if first and len(first) > 2 and took and first in norm_name(took.group(1)) \
            and first not in norm_name(owner):
        return None
    year = str(rec.get("year") or "").strip()
    return {"company": name, "owner": owner, "year": year, "relation": ownership_relation(year),
            "reason": note or f"Acquired by {owner}" + (f" in {year}" if year else ""),
            "source": SOURCE}


def auto_review(pipe_dir: Path, pool: Iterable[str],
                status: dict[str, dict] | None = None, country: str = "") -> dict[str, list[dict]]:
    """Exclusions and owner labels from the ownership + identity answers."""
    pipe_dir = Path(pipe_dir)
    pool = list(pool)
    norms = {norm_name(n): n for n in pool}
    own = _read(pipe_dir / OWNERSHIP_FILE, {}) or {}
    ident = _read(pipe_dir / IDENTITY_FILE, {}) or {}
    status = status or {}
    scope = _read(pipe_dir / SCOPE_FILE, {}) or {}
    hq = _read(pipe_dir / HQ_FILE, {}) or {}
    exclude: dict[str, dict] = {}
    owners: list[dict] = []
    adjacent: list[dict] = []
    display: list[dict] = []

    def drop(name: str, reason: str) -> None:
        exclude.setdefault(name, {"company": name, "reason": reason, "source": SOURCE})

    for name in pool:
        rec = own.get(name) or {}
        note = str(rec.get("note") or "").strip()
        today = str(rec.get("today") or "").lower()
        if _true(rec.get("acquired")) and today in ("absorbed", "closed") and _ACQ.search(note)                 and not is_buyer(name, rec):
            drop(name, f"No longer trades under its own name: {note}")
            continue
        # The same company listed under its old and its new name: keep the new one.
        succ = [m.group(1).strip() for m in _RENAMED_TO.finditer(note)]
        st = status.get(name) or {}
        if str(st.get("status") or "").lower() == "renamed" and st.get("successor"):
            succ.append(str(st["successor"]))
        twin = next((norms[norm_name(s)] for s in succ
                     if norm_name(s) in norms and norm_name(s) != norm_name(name)), None)
        if twin:
            drop(name, f"Former name of {twin}, which is listed under its current name. {note}".strip())
            continue
        idr = ident.get(name) or {}
        if idr:
            ev = str(idr.get("evidence") or "").strip()
            op = str(idr.get("operating") or "").lower()
            if str(idr.get("exists") or "").lower() == "false":
                drop(name, f"No company of this name can be found. {ev}".strip())
                continue
            if str(idr.get("in_market") or "").lower() == "false":
                drop(name, f"Does not operate in this market. {ev}".strip())
                continue
            if op in ("inactive", "acquired") and (idr.get("event") or idr.get("year")):
                drop(name, f"Not operating: {idr.get('event') or op} {idr.get('year') or ''}. {ev}".strip())
                continue
            bare_defunct = str(st.get("status") or "").lower() == "defunct" and not st.get("note")
            if bare_defunct and str(idr.get("exists") or "").lower() != "true":
                drop(name, f"Status check returned defunct and the company cannot be shown to exist. {ev}".strip())
                continue
        # Single-country run: a company run from abroad with only a local branch
        # here is not a player headquartered in this country (no answer = kept).
        h = hq.get(name) or {}
        if country and str(h.get("in_country") or "").strip().lower() == "false":
            drop(name, f"Not headquartered in {country}: head office {h.get('hq') or 'abroad'}. "
                       f"{h.get('evidence') or ''}".strip())
            continue
        sc = scope.get(name) or {}
        kind = str(sc.get("scope") or "").strip().lower()
        if kind == "out":
            drop(name, f"Not in this market: {sc.get('reason') or ''}".strip())
            continue
        if kind == "adjacent":
            adjacent.append({"company": name, "reason": str(sc.get("reason") or "").strip(),
                             "source": SOURCE})
        entry = owner_entry(name, rec)
        if entry:
            owners.append(entry)
        # A retired / divested brand is shown under the name the business trades as today.
        current = str(rec.get("current_name") or "").strip()
        # "Ctrack" for "Ctrack UK Limited" is the same name, not a retired brand.
        cn, nn = norm_name(current), norm_name(name)
        if str(rec.get("brand_status") or "").strip().lower() == "legacy" and current \
                and cn and nn and cn not in nn and nn not in cn:
            display.append({"company": name, "current_name": current, "source": SOURCE})
    # A company owned by another company of this same list is not a separate
    # competitor: the parent represents the group (Redmap, bought by Basware,
    # beside Basware; OpusCapita, bought by GEP, beside GEP). Owners come from
    # these answers, the analyst review and the chart fact-check.
    all_owners = list(owners)
    for f in ("analyst_review.json", "factcheck_review.json"):
        all_owners += [r for r in (_read(pipe_dir / f, {}) or {}).get("ownership") or []
                       if str(r.get("owner") or "").strip()]
    for entry in all_owners:
        name = str(entry.get("company") or "")
        parent = listed_parent(str(entry.get("owner") or ""), name, pool, pipe_dir.parent)
        if parent and name in pool and name not in exclude:
            drop(name, f"Owned by {parent}, which is also in this list; the parent represents the group.")
    owners = [o for o in owners if o["company"] not in exclude]
    return {"exclude": list(exclude.values()), "ownership": owners,
            "adjacent": adjacent, "display": display}


def listed_parent(owner: str, company: str, pool: Iterable[str], out_dir: Path) -> str | None:
    """The company of ``pool`` that ``owner`` names, if any -- never ``company``
    itself. Exact matches only, on the name without legal suffixes or on the
    company's own brand ("Basware" = "Basware Oy"; "GEP" = "GEP Worldwide",
    brand GEP). No partial names: "Visma" is not "Visma Aquila Oy" (one Visma
    unit), and "Aptean" is not "Aptean Austria GmbH"."""
    on = norm_name(owner)
    if not on or len(on) < 3:
        return None
    brands = {}
    for qf in Path(out_dir).glob("*_quadrant.json"):
        for b in (_read(qf, {}) or {}).get("brands") or []:
            key = norm_name(str(b.get("company_key") or b.get("company") or ""))
            if key and b.get("brand"):
                brands.setdefault(key, set()).add(norm_name(str(b["brand"])))
    me = norm_name(company)
    for n in pool:
        nn = norm_name(n)
        if not nn or nn == me:
            continue
        if on == nn or on in brands.get(nn, set()):
            return n
    return None


def write_auto_review(pipe_dir: Path, review: dict[str, list[dict]]) -> Path:
    path = Path(pipe_dir) / AUTO_REVIEW_FILE
    path.write_text(json.dumps(review, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def identity_candidates(pipe_dir: Path, pool: Iterable[str],
                        status: dict[str, dict] | None = None) -> list[str]:
    """Companies whose answers leave doubt: a non-active status with no event,
    a rename, or an ownership answer that could not place the company."""
    own = _read(Path(pipe_dir) / OWNERSHIP_FILE, {}) or {}
    status = status or {}
    out = []
    for n in pool:
        st = status.get(n) or {}
        s = str(st.get("status") or "").lower()
        if (s and s != "active" and not st.get("note")) or s == "renamed" \
                or (n in own and is_unclear(own[n])):
            out.append(n)
    return out


# -- supporting points ----------------------------------------------------------

_PREFIX = re.compile(r"^\s*(?:none available|none found|not available|n/a)\s*[.:;,\-–—]\s+(?=\S)", re.I)
_NEG_START = re.compile(r"^\s*(?:no|none|nothing|zero|neither|there (?:is|are|was|were) no)\b", re.I)
_GAP = re.compile(
    r"could not be (?:found|located|verified|identified|confirmed)|"
    r"(?:is|are|remains?) (?:absent|unavailable|undisclosed|unverified|not (?:publicly )?"
    r"(?:available|documented|disclosed|reported|verified|detailed))|"
    r"does not (?:publish|disclose|provide|report|list|outline|specify|reveal)|"
    r"(?:were|was) not (?:found|located|identified)", re.I)
# A contrast or a figure means the bullet also states something positive.
_POSITIVE = re.compile(r"\d|\b(?:but|while|although|though|however|whereas|instead|rather|"
                       r"except|only|besides|(?<!such )as|because|since|given|and the (?:firm|company))\b|"
                       r"[;:—–]", re.I)


# Leftovers of AI Mode's citation chips: a dangling "[" / "[." where a
# footnote link was, and a source chip ("DUG Technology +1") after the last
# sentence. Neither is part of the finding.
_BRACKET_END = re.compile(r"\s*\[\s*(\.?)\s*$")
_BRACKET_MID = re.compile(r"\s\[\s*\.\s")
# The chip is a site name or a bare domain, so it may start lower-case
# ("www.basware.com +3", "jaggaer +3"); a real sentence never ends in "+N".
_CHIP_END = re.compile(r"(?<=[.!?)])\s+[\w][\w&.,'’\- ]{1,60}?\s\+\d+\s*$")
# The same chip between two sentences: "... segments. Grand View Research +2 Based on ..."
_CHIP_MID = re.compile(r"(?<=[.!?)])\s+[\w][\w&.,'’\- ]{1,60}?\s\+\d+(?=\s+[A-Z])")
# AI Mode's "note" label left after the last sentence.
_NOTE_END = re.compile(r"(?<=[.!?])\s+note\s*$", re.I)
# A bare source chip after the last sentence ("... profitability figures. Tracxn"):
# up to four capitalised words with no closing punctuation. Real text ends a
# sentence; a fragment like this is only ever the chip.
_CHIP_BARE_END = re.compile(r"(?<=[.!?])\s+[A-Z][\w&'’\-]*(?:\s+[A-Z0-9][\w&'’\-]*){0,3}\s*$")


_MD_LINK = re.compile(r"\[([^\]\[]{2,200})\]\(([^)]{1,300})\)")


def _md_link(m: re.Match) -> str:
    # Markdown link syntax leaking from an answer: "[UK Find a Tender](Stotles)".
    label, target = m.group(1).strip(), m.group(2).strip()
    return label if re.match(r"(https?://|www\.)", target, re.I) else f"{label} ({target})"


_CHIP_AFTER_NA = re.compile(rf"^({re.escape('Not available')})\.?\s+[A-Z][\w&.,'’\- ]{{1,40}}?\s\+\d+\s*$")
# Footnote markers ("[1.21]", "[1.23, 1.26]") and raw links in brackets
# ("(https://…)", "[https://…]"): the named source before them stays, the
# machinery does not belong in a research report's prose.
_FOOTNOTE = re.compile(r"\s*\[\s*\d{1,3}(?:\.\d{1,3})?(?:\s*[,;]\s*\d{1,3}(?:\.\d{1,3})?)*\s*\]")
_RAW_LINK = re.compile(r"\s*[\[(]\s*(?:https?://|www\.)[^\s\])]*\s*[\])]")


def clean_artifacts(text: str) -> str:
    t = _MD_LINK.sub(_md_link, str(text or "")).strip()
    t = _RAW_LINK.sub("", _FOOTNOTE.sub("", t))
    t = re.sub(r"\s+([.,;:])", r"\1", t)
    # "Not available Webfleet +1": a source chip stuck to the absence marker.
    t = _CHIP_AFTER_NA.sub(r"\1", t)
    t = _CHIP_MID.sub("", t)
    t = _CHIP_END.sub("", t)
    t = _NOTE_END.sub("", t)
    t = _CHIP_BARE_END.sub("", t)
    # "within the U.S.." -- an abbreviation's stop doubled by the sentence's
    t = re.sub(r"(?<!\.)\.\.(?!\.)", ".", t)
    t = _BRACKET_MID.sub(". ", t)
    if _BRACKET_END.search(t):
        t = _BRACKET_END.sub("", t)
        if t and t[-1] not in ".!?)":
            t += "."
    return t


def _employee_review_re(file: str = "employee_review_sites.txt") -> re.Pattern:
    root = Path(__file__).resolve().parents[3]
    names = []
    try:
        for ln in (root / "config" / file).read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                names.append(ln)
    except OSError:
        pass
    if not names:
        return re.compile(r"(?!x)x")
    return re.compile("|".join(names), re.I)


_EMPLOYEE_REVIEW = None
_PUBLISHERS = None
_ESTIMATES = None


def cites_estimate_site(text: str) -> bool:
    """Contact-data aggregators (config/estimate_sites.txt) publish modelled
    revenue / headcount estimates, not reported figures, so a bullet resting
    on one is not evidence."""
    global _ESTIMATES
    if _ESTIMATES is None:
        _ESTIMATES = _employee_review_re("estimate_sites.txt")
    return bool(_ESTIMATES.search(str(text or "")))


def cites_research_publisher(text: str) -> bool:
    """Market-research / analyst publishers are the report owner's
    competitors (config/research_publishers.txt): a bullet resting on one is
    removed, the same list VERIFY checks."""
    global _PUBLISHERS
    if _PUBLISHERS is None:
        root = Path(__file__).resolve().parents[3]
        try:
            names = [ln.strip() for ln in (root / "config" / "research_publishers.txt")
                     .read_text(encoding="utf-8").splitlines()
                     if ln.strip() and not ln.startswith("#")]
        except OSError:
            names = []
        _PUBLISHERS = (re.compile("|".join(r"\s*".join(map(re.escape, n.split())) for n in names), re.I)
                       if names else re.compile(r"(?!x)x"))
    return bool(_PUBLISHERS.search(str(text or "")))


def cites_employee_reviews(text: str) -> bool:
    """Employee-review sites measure workplace experience, not customer
    satisfaction, so a bullet resting on them is not evidence for any parameter."""
    global _EMPLOYEE_REVIEW
    if _EMPLOYEE_REVIEW is None:
        _EMPLOYEE_REVIEW = _employee_review_re()
    return bool(_EMPLOYEE_REVIEW.search(str(text or "")))


def tidy_claim(text: str) -> str:
    """Citation leftovers removed; 'None available. X did Y' -> 'X did Y'; a
    bullet that only reports an absence -> 'Not available'; else unchanged."""
    t = clean_artifacts(text)
    if not t:
        return t
    stripped = _PREFIX.sub("", t)
    if stripped != t:
        t = stripped[:1].upper() + stripped[1:]
    if t.lower().rstrip(".") in ("none available", "none found", "not available", "n/a", "none"):
        return NOT_AVAILABLE
    # Opens with the absence, or is a short sentence built around it.
    absence = _NEG_START.search(t) or (_GAP.search(t) and len(t) < 160)
    if absence and not _POSITIVE.search(t) and len(t) < 400:
        return NOT_AVAILABLE
    return t


def invalid_source(text: str) -> bool:
    """A bullet resting on a source that is never evidence: an employee-review
    site, a competing research publisher, or a modelled-estimate data site."""
    return cites_employee_reviews(text) or cites_research_publisher(text) or cites_estimate_site(text)


def drop_invalid_sources(out_dir: Path) -> int:
    """Run before the evidence gap-fill: remove invalid-source bullets and leave
    a parameter that had nothing else with NO evidence, so step 5 re-asks it in
    the same run (tidy_evidence later would show "Not available" next to a
    score that rested on the removed bullet)."""
    removed = 0
    for side in sorted(Path(out_dir).glob("param_detail_prescored*.json")):
        part = _read(side, None)
        if not isinstance(part, dict):
            continue
        dirty = False
        for rec in part.values():
            if not isinstance(rec, dict):
                continue
            for axis in ("x", "y"):
                for v in ((rec.get(axis) or {}).get("parameters") or {}).values():
                    if not isinstance(v, dict) or not isinstance(v.get("evidence"), list):
                        continue
                    keep = [e for e in v["evidence"] if not (isinstance(e, dict) and invalid_source(e.get("claim")))]
                    if len(keep) != len(v["evidence"]):
                        removed += len(v["evidence"]) - len(keep)
                        v["evidence"] = keep
                        dirty = True
        if dirty:
            write_json_atomic(side, part, indent=2)
    return removed


def tidy_evidence(out_dir: Path) -> int:
    """Apply tidy_claim to every supporting point, then the parameter rule:
    "Not available" only when there is no real finding, and then once."""
    changed = 0
    for side in sorted(Path(out_dir).glob("param_detail_prescored*.json")):
        part = _read(side, None)
        if not isinstance(part, dict):
            continue
        dirty = False
        for rec in part.values():
            if not isinstance(rec, dict):
                continue
            for axis in ("x", "y"):
                for v in ((rec.get(axis) or {}).get("parameters") or {}).values():
                    if not isinstance(v, dict) or not isinstance(v.get("evidence"), list):
                        continue
                    if isinstance(v.get("assessed_on"), str):
                        why = clean_artifacts(v["assessed_on"])
                        if why != v["assessed_on"].strip():
                            v["assessed_on"] = why
                            changed += 1
                            dirty = True
                    ev = v["evidence"]
                    keep = [e for e in ev if not (isinstance(e, dict) and (
                        cites_employee_reviews(e.get("claim")) or cites_research_publisher(e.get("claim"))
                        or cites_estimate_site(e.get("claim"))))]
                    if len(keep) != len(ev):
                        changed += len(ev) - len(keep)
                        dirty = True
                        ev = v["evidence"] = keep or [{"claim": NOT_AVAILABLE}]
                    for e in ev:
                        if isinstance(e, dict) and isinstance(e.get("claim"), str):
                            new = tidy_claim(e["claim"])
                            if new != e["claim"]:
                                e["claim"] = new
                                changed += 1
                                dirty = True
                    kept = collapse_not_available(ev)
                    if len(kept) != len(ev):
                        v["evidence"] = kept
                        dirty = True
        if dirty:
            write_json_atomic(side, part, indent=2)
    return changed


def collapse_not_available(ev: list) -> list:
    def claim(e: Any) -> Any:
        return e.get("claim") if isinstance(e, dict) else e

    has_finding = any(isinstance(claim(e), str) and claim(e).strip()
                      and claim(e).strip() != NOT_AVAILABLE for e in ev)
    seen: set[str] = set()
    kept = []
    for e in ev:
        c = claim(e)
        if isinstance(c, str) and (c in seen or (has_finding and c.strip() == NOT_AVAILABLE)):
            continue
        if isinstance(c, str):
            seen.add(c)
        kept.append(e)
    return kept


def gap_bullets(payload: dict) -> list[str]:
    """For VERIFY: supporting points that still read as an absence, or a
    "Not available" beside a real finding / repeated."""
    bad = []
    for b in payload.get("brands") or []:
        for axis in ("x", "y"):
            for pn, v in (((b.get("score_detail") or {}).get(axis) or {}).get("parameters") or {}).items():
                cs = [e.get("claim") if isinstance(e, dict) else e for e in (v or {}).get("evidence") or []]
                cs = [c for c in cs if isinstance(c, str)]
                n = cs.count(NOT_AVAILABLE)
                if n and (n > 1 or len(cs) > n):
                    bad.append(f"{b.get('brand')} / {pn}: 'Not available' beside a finding or repeated")
                for c in cs:
                    if c != NOT_AVAILABLE and tidy_claim(c) != c:
                        bad.append(f"{b.get('brand')} / {pn}: {c[:80]}")
                    if cites_employee_reviews(c):
                        bad.append(f"{b.get('brand')} / {pn}: employee-review site cited: {c[:60]}")
                    if cites_estimate_site(c):
                        bad.append(f"{b.get('brand')} / {pn}: modelled estimate cited: {c[:60]}")
    return bad
