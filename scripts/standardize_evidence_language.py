#!/usr/bin/env python3
"""Standardise research-attribution wording in finished quadrant reports.

Rewrites every evidence claim and score justification ("assessed_on") in a
folder of <slug>_quadrant.json + <slug>_report.html pairs so the text states
which research stream supports it:

  * IndiaMART-sourced positive claims  -> "According to primary research
    ..." for claims sourced from IndiaMART (the only primary source present in
    the data; published media interviews are NOT relabelled as primary).
  * First-person desk findings ("We verified ...") -> "Desk research
    confirmed ...".
  * Unverified / missing items -> "Could not be verified through primary
    research", with desk research named as what was actually searched.
  * A parameter whose every claim is a no-evidence placeholder keeps its
    score (never changed here) and is flagged for manual review.

Rules are deterministic and idempotent: re-running on already-standardised
text changes nothing. Scores, keys, company rows and HTML markup are never
touched; only the text inside the evidence cells changes. HTML cells are
re-rendered with html_report's own _esc/_evidence_bullets so JSON and HTML
stay identical; cells from older report layouts that do not match the JSON
are rewritten in place with the same rules.

    .\\.venv\\Scripts\\python.exe scripts\\standardize_evidence_language.py ^
        --folder "C:\\Users\\me\\Desktop\\Fire Market Quadrant" ^
        --review-dir "C:\\Users\\me\\Desktop\\Evidence Language Review" [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import html as html_lib
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PRIMARY_UNVERIFIED = "Could not be verified through primary research."
CLOSING_NOTE = ("Information not confirmed through desk research could not be "
                "verified through primary research.")
UNSUPPORTED_NOTE = ("Could not be verified through primary research. The available "
                    "evidence is insufficient to substantiate this parameter or to "
                    "justify the assigned score.")
INDIAMART_PREFIX = "According to primary research, "

_I = re.I

# --- placeholder / no-evidence claims --------------------------------------
_PLACEHOLDER_BARE = re.compile(
    r"^\s*(?:There is\s+)?no\s+(?:desk[- ]research|public)\s+evidence(?:\s+(?:was\s+)?located)?\.?\s*$", _I)
_PLACEHOLDER_LEAD = re.compile(
    r"^\s*(?:There is\s+)?no\s+(?:desk[- ]research|public)\s+evidence(?:\s+(?:was\s+)?located)?", _I)
_NONE_FOUND = re.compile(r"^\s*None found\.\s*", _I)
_NEGATIVE_LEAD = re.compile(
    r"^\s*(?:There (?:is|are|was|were)\s+)?(?:no|none|zero)\b|^\s*(?:could not|not)\b", _I)

# --- lead-in introduced by an earlier tone pass (asserted non-disclosure) ---
# An earlier pass split "While A, we could not verify B" into "While A. This
# is not disclosed ..., so desk research could not confirm B", leaving
# "While A." as a fragment with no main clause -- rejoin it into one sentence.
_WHILE_FRAGMENT = re.compile(
    r"((?:^|[.!?]\s+)(?:While|Although|Though|Whereas)\b[^.!?]*?)\.\s+"
    r"This is not disclosed by the company(?:,\s*so|\.)\s*desk research could not confirm\s+", _I)

_OLD_LEADINS = [
    re.compile(r"This is not disclosed by the company(?:,\s*so|\.)\s*desk research could not confirm\s+", _I),
    re.compile(r"Based on primary research the company has not disclosed publicly,\s*"
               r"desk research could not confirm\s+", _I),
]

_CONFIRM_VERBS = r"(?:independently\s+)?(?:verify|confirm|validate|corroborate|substantiate|establish|ascertain)"
_FIND_VERBS = r"(?:find|locate|identify|source|obtain|trace|access|uncover|detect)"
_DETERMINE_VERBS = r"(?:isolate|determine|quantify|pinpoint|disaggregate|measure)"

_ADV = (r"(?:also|only|further|additionally|successfully|independently|partially|clearly|explicitly|"
        r"directly|then|first|reliably|fully|thoroughly|extensively|broadly|specifically)")

_FIRST_PERSON = [
    # Inverted forms: "nor could we establish X", "nor did we find X".
    (re.compile(rf"\b(nor|and|or)\s+(?:could|did|were)\s+we\s+(?:able to\s+)?{_CONFIRM_VERBS}\b", _I),
     lambda m: f"{m.group(1)} could desk research confirm"),
    (re.compile(rf"\b(nor|and|or)\s+(?:could|did|were)\s+we\s+(?:able to\s+)?{_FIND_VERBS}\b", _I),
     lambda m: f"{m.group(1)} did desk research identify"),
    (re.compile(r"\b(nor|and|or)\s+(could|did)\s+we\s+(\w+)\b", _I),
     lambda m: f"{m.group(1)} {m.group(2)} desk research {m.group(3)}"),
    # "we could not <verb>" / "we were unable to <verb>" / "we cannot <verb>"
    (re.compile(rf"\b(we|I)\s+(?:could not|couldn't|were unable to|was unable to|cannot|can't|did not|didn't)\s+{_CONFIRM_VERBS}\b", _I),
     "desk research could not confirm"),
    (re.compile(rf"\b(we|I)\s+(?:could not|couldn't|were unable to|was unable to|cannot|can't|did not|didn't)\s+{_FIND_VERBS}\b", _I),
     "desk research did not identify"),
    (re.compile(rf"\b(we|I)\s+(?:could not|couldn't|were unable to|was unable to|cannot|can't|did not|didn't)\s+{_DETERMINE_VERBS}\b", _I),
     "desk research could not determine"),
    (re.compile(r"\b(we|I)\s+(?:could not|couldn't|were unable to|was unable to|cannot|can't)\b", _I),
     "desk research could not"),
    # "we could only (partially) verify"
    (re.compile(rf"\b(we|I)\s+could\s+only\s+(partially\s+)?{_CONFIRM_VERBS}\b", _I),
     lambda m: f"desk research could only {m.group(2) or ''}confirm"),
    (re.compile(rf"\b(we|I)\s+could\s+((?:partially|largely|broadly|mostly|only partially)\s+){_CONFIRM_VERBS}\b", _I),
     lambda m: f"desk research could {m.group(2).lower()}confirm"),
    (re.compile(rf"\b(we|I)\s+(?:could|were able to|was able to)\s+{_CONFIRM_VERBS}\b", _I),
     "desk research confirmed"),
    (re.compile(r"\b(we|I)\s+could\s+(?:only\s+)?find\b", _I), "desk research identified"),
    (re.compile(r"\b(we|I)\s+could\s+(only\s+)?(review|evaluate|assess|examine|analy[sz]e|check|see|identify|"
                r"locate|establish|document|observe|trace|source)\b", _I),
     lambda m: f"desk research could {m.group(2) or ''}{m.group(3).lower()}"),
    # "we (also|successfully ...) verified/found/evaluated ..."
    (re.compile(rf"\b(we|I)\s+((?:{_ADV}\s+)*)(verified|validated|confirmed|found|discovered|uncovered|detected|saw|"
                r"identified|located|evaluated|assessed|reviewed|checked|analy[sz]ed|examined|observed|noted|"
                r"sought|looked|established|sourced|traced|searched|cross-referenced|cross-checked|"
                r"documented|recorded|compared|attempted|tried)\b", _I),
     None),  # handled by _first_person_verb
    (re.compile(r"\bThe (?:evaluation|assessment|review) (verified|confirmed|validated)\b"),
     "Desk research confirmed"),
    (re.compile(r"\bThe (?:evaluation|assessment|review) found\b"), "Desk research identified"),
]

_VERB_MAP = {
    "verified": "confirmed", "validated": "confirmed", "confirmed": "confirmed",
    "found": "identified", "discovered": "identified", "uncovered": "identified",
    "detected": "identified", "saw": "identified",
}


def _first_person_verb(m: re.Match) -> str:
    advs = [a for a in (m.group(2) or "").split() if a.lower() != "successfully"]
    verb = m.group(3)
    verb = _VERB_MAP.get(verb.lower(), verb.lower())
    return " ".join(["desk research", *[a.lower() for a in advs], verb])


# --- passive / adjectival "unverified" forms -------------------------------
_SOURCE_TAIL = (r"(?:\s+(?:through|from|via|using|in|with|by)\s+(?:(?:public|publicly available|"
                r"independent|third-party|external|official|open|available)\s+)*"
                r"(?:records?|data|sources?|disclosures?|reports?|documentation|information|"
                r"filings|evidence|audits?|channels|domain))?")
_UNVERIFIED_FORMS = [
    # Subject-less "Could not verify X" at a sentence start or after a
    # connector ("..., but could not verify X") names no researcher at all;
    # the stream that searched was desk research.
    (re.compile(rf"(^|[.;!?]\s+|,\s*(?:but|and|yet|however)?\s*|\b(?:but|and|yet|however)\s+)"
                rf"could not\s+{_CONFIRM_VERBS}\b", _I),
     r"\1desk research could not confirm"),
    (re.compile(rf"(^|[.;!?]\s+|,\s*(?:but|and|yet|however)?\s*|\b(?:but|and|yet|however)\s+)"
                rf"could not\s+{_FIND_VERBS}\b", _I),
     r"\1desk research did not identify"),
    # Any other subject ("Independent auditors could not verify") keeps its
    # subject; only the verb changes so the sentence is not a hedge phrase.
    (re.compile(r"\bcould not verify\b", _I), "could not confirm"),
    # The standard phrases themselves must never be rewritten (idempotence).
    (re.compile(r"\b(could not|cannot|can not|could not yet) be\s+"
                r"(?!verified through primary research|confirmed through desk research)"
                r"(?:(?:independently|publicly|fully|"
                r"externally|third-party|reliably|directly|clearly|explicitly|formally)\s+)*"
                r"(?:verified|confirmed|validated|established|found|isolated|corroborated|substantiated|"
                r"located|identified|quantified|determined|traced|ascertained)" + _SOURCE_TAIL, _I),
     "could not be confirmed through desk research"),
    (re.compile(r"\bremains?\s+unverified\s+by\s+", _I), "could not be confirmed through desk research or by "),
    (re.compile(r"\bremains?\s+(?:publicly\s+)?unverified(?:\s+publicly)?\b", _I),
     "could not be confirmed through desk research"),
    (re.compile(r"\bnot\s+(disclosed|accessible|available)\s+through\s+public\s+or\s+desk\s+research\b", _I),
     r"not \1 through desk research"),
    (re.compile(r"\bnot\s+publicly\s+(disclosed|available|accessible|detailed|documented|isolated|reported|"
                r"released|shared|quantified|confirmed|verified|itemi[sz]ed|broken out|specified)\b", _I),
     r"not \1 in sources available to desk research"),
    (re.compile(r"\b(n)o\s+(?:desk-research|public)\s+(records?|evidence|data|information|documentation)\b", _I),
     lambda m: f"{m.group(1)}o desk research {m.group(2)}"),
    (re.compile(r"\bdesk-research\b", _I), "desk research"),
]

_UNVERIFIED_MARKERS = re.compile(
    r"could not|cannot be|not (?:confirmed|verified|identified|disclosed|available|accessible)|"
    r"did not identify|unverified|no desk research|identified no|no (?:verifiable|independent|third-party) |"
    r"lack(?:s|ing)? (?:of )?(?:any )?(?:documented|verifiable|independent|third-party|public)|"
    r"absence of|insufficient|(?:no|zero) (?:\w+ )?evidence|without (?:any |publishing )|"
    r"lacks? (?:publicly|any)|lacking public", _I)


# Weak/lowest rubric-band placements ("..., placing it in the weak or unproven
# score band") describe the RAW score before cohort banding onto 65-100, so
# they contradict the displayed number; the finding itself stays.
_NEG_BAND_WORD = (r"(?:weak|weakest|lowest|lower|low|unproven|minimal|bottom|poor|nascent|limited|"
                  r"entry|entry-level|negligible)")
# "tier-1 supplier" / "tier 2 cities" are findings, not rubric bands.
_BAND_NOUN = r"(?:band|tier|bracket|bucket)(?![-\s]*\d|-)"
_BAND_TAIL = (r"(?:\s+(?:for|on|in|under)\s+(?:this|the|that)\s+(?:specific\s+|narrow\s+|particular\s+)?"
              r"(?:parameter|metric|criterion|axis|dimension|category|measure|evaluation|assessment))?")
# Participles can hang off any clause ("..., placing it in the weak band");
# finite verbs are only removable when a relative/connector introduces them
# ("..., which places it in ..."). A bare finite verb is the sentence's main
# verb ("its closure places it in the lowest band") -- removing it would
# leave a fragment, so that form is rewritten instead (see _NEG_BAND_MAIN).
_PLACE_PARTICIPLE = (r"(?:placing|placement|placed|positioning|positioned|putting|landing|resulting in|leaving|"
                     r"keeping|capping|restricting|limiting|relegating|confining|anchoring|consigning|justifying|"
                     r"warranting|falling|fitting|scoring|dropping|assigning|pushing|requiring|moving|"
                     r"pointing to|indicating|suggesting|reflecting)")
_FINITE_SING = (r"places|puts|positions|lands|results in|leaves|keeps|caps|restricts|limits|relegates|"
                r"confines|anchors|justifies|warrants|drops|assigns|pushes|requires|moves|points to|"
                r"indicates|suggests|reflects")
_FINITE_PLUR = r"place|put|position|land|result in|leave|keep|cap|restrict|limit|relegate|confine|drop|push|require"
_FINITE_PAST = r"placed|kept|left|justified|positioned|dropped|assigned|pushed|required|relegated|limited"
_FINITE_FALL = r"falls|fits|sits|fall|fit|sit|fell"
_PLACE_FINITE = rf"(?:{_FINITE_SING}|{_FINITE_PLUR}|{_FINITE_PAST}|{_FINITE_FALL})"
_BAND_OBJECT = (rf"(?:\s+(?:it|them|the company|the firm|the score|the evaluation|the rating|the entity|"
                rf"its standing|its score|its evaluation(?: for this (?:specific )?parameter)?|a score|"
                rf"the provider|the manufacturer|this company|the brand|the parameter|"
                rf"[A-Z][\w&.'-]*(?:\s+[A-Z][\w&.'-]*){{0,4}}))?\s+(?:squarely\s+|firmly\s+|only\s+|solidly\s+|"
                rf"strictly\s+|clearly\s+)?")
# The window between the determiner and the band noun must not cross into
# another clause ("... durability and places it in the lowest band"): that
# would delete a real finding along with the band label.
_NO_CLAUSE = r"(?:(?!\b(?:and|but|while|which|that|places?|placing|puts?|putting|leaves?|leaving)\b)[^.;!?])"
# Between the weak word and the band noun "and"/"or" are part of the label
# ("the weak and unproven score band"), so only verbs end the window there.
_NO_VERB = r"(?:(?!\b(?:which|while|places?|placing|puts?|putting|leaves?|leaving)\b)[^.;!?])"
_BAND_TARGET = (rf"(?:(?:in|into|within|at|to)\s+)?(?:the|a|an|this|that|its)\s+{_NO_CLAUSE}{{0,80}}?"
                rf"\b{_NEG_BAND_WORD}\b{_NO_VERB}{{0,40}}?\b{_BAND_NOUN}\b{_BAND_TAIL}")
_NEG_BAND_CLAUSE = re.compile(
    rf",?\s*(?:(?:and|thus|thereby|so)\s+)?{_PLACE_PARTICIPLE}\b{_BAND_OBJECT}{_BAND_TARGET}", _I)
_NEG_BAND_RELATIVE = re.compile(
    rf",?\s*(?:which|that|this|and this|and which)\s+(?:(?:thus|therefore|directly|ultimately|only)\s+)?"
    rf"{_PLACE_FINITE}\b{_BAND_OBJECT}{_BAND_TARGET}", _I)
# "<subject> places it in the lowest score band" -> "<subject> limits the score"
# keeps the sentence grammatical while dropping the band label.
_NEG_BAND_MAIN = re.compile(rf"\b({_PLACE_FINITE})\b{_BAND_OBJECT}{_BAND_TARGET}", _I)


def _main_verb_repl(m: re.Match) -> str:
    """Keep subject-verb agreement and tense of the verb being replaced."""
    verb = m.group(1).lower()
    if re.fullmatch(_FINITE_FALL, verb):
        return "scored lower on this parameter" if verb == "fell" else (
            "scores lower on this parameter" if verb.endswith("s") else "score lower on this parameter")
    if re.fullmatch(_FINITE_PAST, verb):
        return "limited the score"
    if re.fullmatch(_FINITE_PLUR, verb):
        return "limit the score"
    return "limits the score"
# A sentence that is ONLY a band placement ("This places the company in the
# weak or unproven band.") carries no finding and is dropped whole.
_NEG_BAND_SENTENCE = re.compile(
    rf"(?:^|(?<=[.!?])\s+)(?:This|That|It|Such an? \w+|These \w+|This \w+)\s+(?:therefore\s+|thus\s+)?"
    rf"{_PLACE_FINITE}\b{_BAND_OBJECT}{_BAND_TARGET}\s*[.!?]", _I)


def strip_negative_bands(text: str) -> str:
    t = _NEG_BAND_SENTENCE.sub("", text)
    t = _NEG_BAND_RELATIVE.sub("", t)
    t = _NEG_BAND_CLAUSE.sub("", t)
    t = _NEG_BAND_MAIN.sub(_main_verb_repl, t)
    if t == text:
        return text
    t = re.sub(r",\s*([.;!?])", r"\1", t)
    return re.sub(r"\s{2,}", " ", t).strip()


# --- sentence polish -------------------------------------------------------
# Residue from Google AI Mode's answer page: source chips ("Tracxn +2"),
# bare domains, Markdown links and cut-off link titles ("... anti-drone ...").
_CHIP_ONLY = re.compile(r"\s*((?:[^\s+,]+\s){0,5}[^\s+,]+)\s\+\d{1,2}\.?\s*")
# Chip tokens never end in "." -- so "... Pvt. Ltd. +1" is not cut after "Pvt."
_CHIP_TRAILING = re.compile(r"(?<=[.!?])\s+(?:[^\s+]*[^\s+.]\s){0,4}[^\s+]*[^\s+.]\s\+\d{1,2}\.?\s*$")
_SOURCE_SENTENCE = re.compile(r"\.\s+\(Source:\s*([^)]+)\)\.?\s*$")
_MD_LINK = re.compile(r"\[([^\]]+)\]\((?:url:\s*)?[^)]*\)")
_DOMAIN = r"(?:https?://)?(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|in|co|org|net|io|aero|info|biz|gov|edu)(?:\.[a-z]{2})?(?:/[\w./?=&%-]*)?"
_DOMAIN_PAREN = re.compile(rf"\s*[\(\[](?:Source:\s*)?{_DOMAIN}[^\)\]]{{0,10}}[\)\]]", re.I)
_TRUNC_TITLE = re.compile(r"\s*\((?=[^()]*(?:\.\.\.|…))[^()]*\)")
_DANGLING_OPEN = re.compile(r"\s*[\(\[]\s*$")
_TRAIL_DOMAIN = re.compile(rf"(?<=[.!?])\s+{_DOMAIN}\s*$", re.I)
_INFORMAL = [
    (re.compile(r"\bmassive\b", _I), "substantial"),
    (re.compile(r"\bhuge\b", _I), "large"),
    (re.compile(r"\belite\b", _I), "strong"),
    (re.compile(r"\bzero evidence\b", _I), "no evidence"),
    (re.compile(r"\babsolutely\s+", _I), ""),
    (re.compile(r"\btotally\b", _I), "entirely"),
    (re.compile(r"\btons of\b", _I), "large quantities of"),
    (re.compile(r"\bboasts\b", _I), "reports"),
    (re.compile(r"\bboast\b", _I), "report"),
    (re.compile(r"\bboasting\b", _I), "reporting"),
    # Research wording, not tool wording: an analyst "looks for" or "reviews";
    # "search queries ... returned" reads like a search engine log.
    (re.compile(r"\b([Dd]esk research) searched (extensively )?for\b"), r"\1 looked \2for"),
    (re.compile(r"\b([Dd]esk research) searched\b"), r"\1 reviewed"),
    (re.compile(r"\bSearch queries across\b"), "A review of"),
    (re.compile(r"\bsearch queries across\b"), "a review of"),
    (re.compile(r"^Searches for\b"), "A review of"),
]


def _fix_garbled_numbers(t: str) -> str:
    """'4 . 5 k g' -> '4.5 kg'; '120 1 2 0 minutes' -> '120 minutes' (math-rendering residue)."""
    def collapse(m: re.Match) -> str:
        segs: list[list[str]] = []
        kind = None
        for ch in m.group(0).split(" "):
            k = "num" if re.match(r"[0-9,−%]", ch) else ("alpha" if ch.isalpha() else None)
            if k and k != kind and segs:
                segs.append([ch])
            elif not segs:
                segs.append([ch])
            else:
                segs[-1].append(ch)
            kind = k or kind
        return " ".join("".join(s) for s in segs).replace("−", "–")
    t = re.sub(r"(?<![\w.])(?:[0-9a-zA-Z.,−%]\s){2,}[0-9a-zA-Z.,−%](?![\w])",
               lambda m: collapse(m) if re.search(r"\d \S|\S \d|\b[a-z] [a-z] [a-z]\b", m.group(0)) else m.group(0), t)
    # "120 120 minutes" / "0.6 0.6" -- the plain number followed by its collapsed duplicate
    t = re.sub(r"(?<![\d.,])(\d[\d.,]*\d|\d)\s+\1(?![\d.,]*\d)", r"\1", t)
    # "30 3 0 hours" / "10 1 0 acres": a number followed by its own digits spelled out
    t = re.sub(r"\b(\d{2,})\s+((?:\d\s)+\d)\b(?!\s*[.,]\s*\d)",
               lambda m: m.group(1) if m.group(2).replace(" ", "") == m.group(1) else m.group(0), t)
    return re.sub(r"\(\s+", "(", t)


_SOURCE_LABEL = re.compile(r"\b(?:Page|Profile|Portal|Map|Website|Site|Listing|Report|Home|Booklet|Brochure|Catalog|Catalogue|Registry)\b")
_ATTRIB_PREV = {"on", "via", "by", "from", "in", "at", "of", "the", "per", "to", "its", "their", "and", "or",
                "for", "with", "under", "as"}


def _md_link_repl(m: re.Match) -> str:
    """[label](url) -> label; a trailing page/profile title becomes an attribution."""
    label = m.group(1).strip()
    before = m.string[: m.start()].rstrip()
    prev = before.split()[-1].lower() if before.split() else ""
    after = m.string[m.end():].lstrip()
    at_end = not after or after[0] in ".;!?"
    if at_end and _SOURCE_LABEL.search(label) and prev not in _ATTRIB_PREV:
        return f", according to the {label}"
    return label


_GLUED_SOURCE = re.compile(
    rf"(\b[a-z][\w-]*)\s+((?:[A-Z][\w&'-]*\s){{0,2}}[A-Z][\w&'-]*)\s*[\(\[](?:Source:\s*)?({_DOMAIN})"
    rf"[^\)\]]{{0,10}}[\)\]](?=\s*(?:[.;!?]|$))")


def _glued_source_repl(m: re.Match) -> str:
    """'optimized for mapping Indrones (indrones.com)' -> 'optimized for mapping, according to Indrones'."""
    prev, name, domain = m.group(1), m.group(2), re.sub(r"[^a-z0-9]", "", m.group(3).lower())
    key = re.sub(r"[^a-z0-9]", "", name.lower())
    if len(key) >= 4 and key in domain and prev.lower() not in _ATTRIB_PREV:
        return f"{prev}, according to {name}"
    return m.group(0)


_LABEL_WORD = r"(?:·?[A-Z0-9][\w.&'’+-]*|&|–|-|·|of|and|the|for|on)"
_BARE_LABEL = re.compile(rf"(?:Source:\s*)?{_LABEL_WORD}(?:\s+{_LABEL_WORD}){{0,6}}\.?")
_CHIP_LABEL = re.compile(r"(?:[^\s+]+\s){0,5}[^\s+]+\s\+\d{1,2}\.?")


def _source_label_sentences(t: str) -> str:
    """Drop citation-chip sentences ("AiRotor Labs +1.") and turn a bare
    source-name sentence ("LinkedIn India.", "Source: The Hindu.") into a
    "(Source: X)" attribution on the sentence before it."""
    from vendor_intel.quadrant.html_report import _split_sentences

    parts = _split_sentences(t)
    if len(parts) < 2:
        return t
    out: list[str] = []
    for p in parts:
        if out and _CHIP_LABEL.fullmatch(p):
            continue
        if out and _BARE_LABEL.fullmatch(p) and not re.search(r"\b(?:is|are|was|were|has|have)\b", p) \
                and not p.startswith(("Could not", "Information not", "Desk research")):
            label = re.sub(r"^Source:\s*", "", p).rstrip(".").strip()
            prev = out[-1].rstrip()
            out[-1] = (prev[:-1] if prev.endswith(".") else prev) + f" (Source: {label})."
            continue
        out.append(p)
    return " ".join(out)


def polish_text(text: str) -> str:
    t = str(text or "")
    if not t.strip():
        return t
    from vendor_intel.quadrant.html_report import _split_sentences

    m = _CHIP_ONLY.fullmatch(t)
    if m and len(_split_sentences(t)) == 1:
        # The whole entry is a source chip: keep the entry, state the source.
        return f"Source: {m.group(1).strip().rstrip('.')}."
    t = _MD_LINK.sub(_md_link_repl, t)
    t = _TRUNC_TITLE.sub("", t)
    t = _GLUED_SOURCE.sub(_glued_source_repl, t)
    t = _DOMAIN_PAREN.sub("", t)
    t = _CHIP_TRAILING.sub("", t)
    t = _TRAIL_DOMAIN.sub("", t)
    t = _SOURCE_SENTENCE.sub(lambda m: f" (Source: {m.group(1).strip()}).", t)
    t = _DANGLING_OPEN.sub("", t)
    t = re.sub(r"\s*[\[(]\s*(?=[.;!?](?:\s|$))", "", t)  # "... demonstrations [." -> "... demonstrations."
    t = _source_label_sentences(t)
    if re.search(r"\d(?: \d){2,}|\d \. \d|\d , \d|\b[a-z] [a-z] [a-z]\b", t):
        t = _fix_garbled_numbers(t)
    for rx, repl in _INFORMAL:
        t = rx.sub(repl, t)
    t = re.sub(r"\bthe\s+(The\b)", r"\1", t)
    # A doubled lower-case word is a typo ("the the"); a doubled capitalised
    # word is often a real name (a place such as "Budge Budge", "Baden-Baden"),
    # so only lower-case repeats are collapsed -- no list of names.
    t = re.sub(r"\b([a-z]\w{2,})\s+\1\b(?![-\w])", r"\1", t)
    t = re.sub(r"\s+\)", ")", t)
    t = re.sub(r"\s+([,;:])(?=\s|$)", r"\1", t)
    t = re.sub(r"(\S)\s+\.(?=\s|$)", r"\1.", t)
    t = re.sub(r"[,;:]\s*\.", ".", t)
    t = re.sub(r"(?<!\.)\.\.(?=\s|$)", ".", t)  # "Ltd.." -> "Ltd." but never touch "..."
    t = re.sub(r"\s{2,}", " ", t).strip()
    if t and t[-1] not in ".!?\"'”’)":
        t += "."
    # A word written lower-case-first with a capital inside is a name or unit
    # as styled by its owner (camel case such as "iPhone", "eVTOL", "mAh"):
    # keep it. Generic shape test, no list of names.
    if t and t[0].islower() and not re.match(r"(?:e\.g\.|i\.e\.|[a-z]+[A-Z]\w*|kW\b)", t):
        t = t[0].upper() + t[1:]
    return t


def _cap_sentence_starts(text: str) -> str:
    """'desk research' at the start of a sentence -> 'Desk research'."""
    text = re.sub(r"^(\s*)desk research", lambda m: m.group(1) + "Desk research", text)
    text = re.sub(r"([.!?]\s+)desk research", lambda m: m.group(1) + "Desk research", text)
    # Inside a sentence (after ";", ":" or ",") it stays lower-case.
    return re.sub(r"([;:,]\s+)Desk research", lambda m: m.group(1) + "desk research", text)


def _apply_common(text: str) -> tuple[str, set[str]]:
    tags: set[str] = set()
    t = text
    t = re.sub(r"\bAccording to primary research conducted through IndiaMART\b", "According to primary research", t)
    # "This is not disclosed by the company." was inserted by an earlier tone
    # pass, never by evidence; collapse repeats before rejoining fragments.
    t2 = re.sub(r"(?:This is not disclosed by the company\.\s+)+(?=This is not disclosed by the company)", "", t)
    if t2 != t:
        tags.add("unverified")
        t = t2
    t2 = _WHILE_FRAGMENT.sub(r"\1, desk research could not confirm ", t)
    if t2 != t:
        tags.add("unverified")
        t = t2
    for rx in _OLD_LEADINS:
        t2 = rx.sub("Desk research could not confirm ", t)
        if t2 != t:
            tags.add("unverified")
            t = t2
    t2 = re.sub(r"(^|(?<=[.!?])\s+)This is not disclosed by the company\.(?=\s|$)", r"\1", t).strip()
    if t2 != t:
        tags.add("unverified")
        t = t2
    for rx, repl in _FIRST_PERSON:
        fn = _first_person_verb if repl is None else repl
        t2 = rx.sub(fn, t)
        if t2 != t:
            tags.add("attribution")
            t = t2
    for rx, repl in _UNVERIFIED_FORMS:
        t2 = rx.sub(repl, t)
        if t2 != t:
            tags.add("unverified")
            t = t2
    t2 = strip_negative_bands(t)
    if t2 != t:
        tags.add("band_removed")
        t = t2
    t = re.sub(r"\bdesk research desk research\b", "desk research", t, flags=_I)
    t = _cap_sentence_starts(t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t, tags


_NEGATIVE_CLAIM = re.compile(r"^\s*(?:(?:There (?:is|are|was|were)\s+)(?:no|zero)\b|(?:No|Zero)\b(?!\.))")


def is_placeholder_claim(claim: str) -> bool:
    c = str(claim or "").strip()
    return (bool(_PLACEHOLDER_LEAD.match(c)) or bool(_NONE_FOUND.match(c))
            or bool(_NEGATIVE_CLAIM.match(c)) or c.startswith(PRIMARY_UNVERIFIED))


def _is_indiamart_primary(claim: str) -> bool:
    c = str(claim or "")
    if not re.search(r"india\s?mart", c, _I):
        return False
    if c.startswith("According to primary research") or c.startswith(PRIMARY_UNVERIFIED):
        return False
    return not _NEGATIVE_LEAD.match(c) and not re.search(r"zero evidence|no evidence", c, _I)


def _lower_first_word(s: str) -> str:
    """Lowercase the opening word only when it is a common word, never a name."""
    m = re.match(r"(\s*)([A-Z][\w-]*)(?=[\s,])", s)
    common = {"The", "A", "An", "Its", "Their", "This", "These", "Product", "Products",
              "Commercial", "Company", "Supplier", "Retailer", "Data", "Provision", "Catalog",
              "Catalogs", "Records", "Listings", "Listing", "As", "Based", "Official", "Officially",
              "Business", "Corporate", "Verified", "Trade", "Online", "Public", "Publicly", "Multiple",
              "Third-party", "General", "Self-reported", "Profile", "Industry", "On", "E-commerce",
              "Customer", "Execution", "Operational", "For", "Visible", "While", "Headquartered",
              "High-resolution", "High", "Marketing", "Marketplace", "Supply", "Registered"}
    if m and m.group(2) in common:
        return s[: m.start(2)] + m.group(2).lower() + s[m.end(2):]
    return s


# Reviewed sentence-level rewrites (fragment -> complete sentence), loaded
# from --sentence-map. Applied last, by exact sentence match, so a sentence
# already rewritten never matches again.
_SENTENCE_MAP: dict[str, str] = {}
# Reviewed analyst-voice rewrites (--voice-map): whole justification bodies
# (without the standard notes) and whole claims, matched exactly.
_VOICE_MAP: dict[str, str] = {}
_VOICE_NOTE_REQUIRED: set[str] = set()


def _apply_sentence_map(text: str) -> str:
    if not _SENTENCE_MAP or not text:
        return text
    from vendor_intel.quadrant.html_report import _split_sentences

    for _ in range(3):  # a reviewed rewrite can itself have a reviewed follow-up
        before = text
        for s in _split_sentences(text):
            new = _SENTENCE_MAP.get(s)
            if new and new != s:
                text = text.replace(s, new, 1)
        if text == before:
            break
    return text


def _finish(new: str, tags: set[str]) -> tuple[str, set[str]]:
    polished = polish_text(new)
    if polished != new:
        tags = tags | {"polished"}
    mapped = _apply_sentence_map(polished)
    if mapped != polished:
        tags = tags | {"sentence_rewritten"}
        mapped = polish_text(mapped)  # reviewed sentences get the same punctuation rules
    return mapped, tags


def rewrite_claim(claim: str) -> tuple[str, set[str]]:
    new, tags = _finish(*_rewrite_claim_core(claim))
    if new in _VOICE_MAP:
        new, tags = polish_text(_VOICE_MAP[new]), tags | {"voice"}
    return new, tags


def rewrite_basis(basis: str, *, unsupported: bool, claims_unverified: bool) -> tuple[str, set[str]]:
    return _finish(*_rewrite_basis_core(basis, unsupported=unsupported, claims_unverified=claims_unverified))


def _rewrite_claim_core(claim: str) -> tuple[str, set[str]]:
    c = str(claim or "").strip()
    # "[no desk research evidence located]." -- a bracketed placeholder
    m = re.fullmatch(r"\[([^\[\]]+)\]\.?", c)
    if m:
        c = m.group(1).strip()
        c = c[0].upper() + c[1:] if c else c
    if not c:
        return c, set()
    tags: set[str] = set()
    # Already standardised: keep the classification so counts and the
    # parameter-level note come out the same on every run.
    if c.startswith(PRIMARY_UNVERIFIED):
        c2, t = _apply_common(c)
        return c2, t | {"placeholder"}
    if c.startswith("According to primary research"):
        c2, t = _apply_common(c)
        return c2, t | {"primary_indiamart"}
    if _NONE_FOUND.match(c):
        c = _NONE_FOUND.sub("", c)
        c, t = _apply_common(c)
        return f"{PRIMARY_UNVERIFIED} {c}".strip(), tags | t | {"placeholder"}
    if not c.startswith(PRIMARY_UNVERIFIED) and _PLACEHOLDER_LEAD.match(c):
        if _PLACEHOLDER_BARE.match(c):
            return f"{PRIMARY_UNVERIFIED} Desk research identified no supporting evidence.", {"placeholder"}
        rest = _PLACEHOLDER_LEAD.sub("Desk research identified no evidence", c, count=1)
        rest, t = _apply_common(rest)
        return f"{PRIMARY_UNVERIFIED} {rest}", tags | t | {"placeholder"}
    # Any other claim that is itself a statement of absence ("No export
    # contracts were found ...") is a missing-evidence entry, not a finding.
    if not c.startswith(PRIMARY_UNVERIFIED) and _NEGATIVE_CLAIM.match(c):
        rest, t = _apply_common(c)
        return f"{PRIMARY_UNVERIFIED} {rest}", t | {"placeholder"}
    if _is_indiamart_primary(c):
        body = re.sub(r"^\s*Indiamart\.com\s+", "", c, flags=_I)
        body, t = _apply_common(body)
        m = re.match(r"According to ([^,]*india\s?mart[^,]*),\s*(.*)$", body, _I)
        if m:
            new = f"According to primary research ({m.group(1)}), {m.group(2)}"
        else:
            new = INDIAMART_PREFIX + _lower_first_word(body)
        return new, t | {"primary_indiamart"}
    c2, t = _apply_common(c)
    return c2, t


def _rewrite_basis_core(basis: str, *, unsupported: bool, claims_unverified: bool) -> tuple[str, set[str]]:
    b = str(basis or "").strip()
    b2, tags = _apply_common(b)
    body = b2.replace(UNSUPPORTED_NOTE, "").replace(CLOSING_NOTE, "").strip()
    # The note is decided from the pre-rewrite wording too, so an analyst
    # rewrite that words a gap differently never drops the standard note.
    needs_note = bool(_UNVERIFIED_MARKERS.search(body))
    if body in _VOICE_MAP:
        body = _VOICE_MAP[body]
        tags.add("voice")
    needs_note = needs_note or bool(_UNVERIFIED_MARKERS.search(body)) or body in _VOICE_NOTE_REQUIRED
    if unsupported:
        tags.add("unsupported")
        return f"{UNSUPPORTED_NOTE} {body}".strip(), tags
    if claims_unverified or needs_note:
        tags.add("unverified")
        body = body.rstrip()
        if body and body[-1] not in ".!?":
            body += "."
        return f"{body} {CLOSING_NOTE}".strip(), tags
    return body, tags


_GARBLED_NUMBERS = re.compile(r"\b\d(?: \d){2,}\b|\d , \d|\b[a-z] [a-z] [a-z]\b(?= |\.|,)")

_STRONG_POSITIVE = re.compile(
    r"market-leading|market leader|strong|robust|extensive|comprehensive|well-established|"
    r"clear and verifiable|leading|exceptional|excellent|dominant", _I)
_WEAK_BAND = re.compile(
    r"lowest (?:scoring )?band|weak or unproven|weak and unproven|unproven band|minimal band|"
    r"bottom (?:score )?band|lowest tier|lowest score", _I)


def _legacy_strip_links(text: str) -> str:
    """Link stripping as done before the URL pattern stopped at ')' / final '.'."""
    from vendor_intel.quadrant.html_report import _MD_LINK

    out = _MD_LINK.sub(r"\1", str(text or ""))
    out = re.sub(r"<?https?://\S+>?", "", out)
    return " ".join(out.replace("()", "").split())


def _legacy_bullet_variants(evidence: list) -> set[str]:
    """Every way earlier renderer versions could have drawn this bullet list
    (old/new sentence splitter x old link stripping x with/without the
    post-link tidy), so reports built with any of them can still be located."""
    from vendor_intel.quadrant.html_report import _esc, _split_sentences, _tidy_after_links

    variants: set[str] = set()
    for split in (lambda f: [p.strip() for p in re.split(r"(?<=[.!?])\s+(?=[A-Z(])", f)], _split_sentences):
        for tidy in (lambda f: f, _tidy_after_links):
            items: list[str] = []
            seen: set[str] = set()
            for entry in evidence or []:
                flat = tidy(_legacy_strip_links((entry or {}).get("claim") if isinstance(entry, dict) else ""))
                for s in split(flat):
                    if not s or s.lower() in seen:
                        continue
                    seen.add(s.lower())
                    items.append(f"<li>{_esc(s)}</li>")
            if items:
                variants.add(f'<ul class="cq-ta-points">{"".join(items)}</ul>')
    return variants


def process_folder(folder: Path, review_dir: Path, dry_run: bool) -> dict:
    from vendor_intel.quadrant.html_report import _esc, _evidence_bullets, _split_sentences

    stats = Counter()
    review_rows: list[dict] = []
    change_rows: list[dict] = []
    problems: list[str] = []

    pairs = sorted(folder.glob("*_quadrant.json"))
    for jpath in pairs:
        hpath = jpath.with_name(jpath.name.replace("_quadrant.json", "_report.html"))
        market = jpath.name.replace("_quadrant.json", "")
        stats["files_reviewed"] += 1 + int(hpath.exists())
        try:
            payload = json.loads(jpath.read_text(encoding="utf-8"))
        except Exception as err:  # noqa: BLE001
            problems.append(f"{jpath.name}: unreadable JSON ({err})")
            continue
        html_text = hpath.read_text(encoding="utf-8") if hpath.exists() else None
        if html_text is None:
            problems.append(f"{hpath.name}: missing HTML report")
        html_new = html_text
        regenerated: set[str] = set()
        json_changed = False
        cell_hits = cell_total = 0

        for brand in payload.get("brands") or []:
            company = brand.get("company") or brand.get("brand") or ""
            for axis in ("x", "y"):
                params = ((brand.get("score_detail") or {}).get(axis) or {}).get("parameters") or {}
                for pname, v in params.items():
                    if not isinstance(v, dict):
                        continue
                    old_evidence = v.get("evidence") or []
                    old_basis = str(v.get("assessed_on") or "").strip()
                    new_evidence = []
                    claim_unverified = False
                    placeholders = 0
                    for e in old_evidence:
                        if not isinstance(e, dict):
                            new_evidence.append(e)
                            continue
                        old_c = str(e.get("claim") or "")
                        new_c, tags = rewrite_claim(old_c)
                        stats["claims_reviewed"] += 1
                        if "placeholder" in tags or is_placeholder_claim(old_c):
                            placeholders += 1
                        if "primary_indiamart" in tags:
                            stats["primary_indiamart_claims"] += 1
                        # Decided from the final text, not from which rule fired,
                        # so a re-run reaches the same parameter-level note.
                        if "placeholder" in tags or _UNVERIFIED_MARKERS.search(new_c):
                            claim_unverified = True
                        if "placeholder" in tags:
                            stats["missing_evidence_claims"] += 1
                        elif "unverified" in tags:
                            stats["unverified_claims_updated"] += 1
                        if "attribution" in tags and "primary_indiamart" not in tags:
                            stats["desk_attribution_claims"] += 1
                        if _GARBLED_NUMBERS.search(old_c):
                            stats["garbled_number_claims"] += 1
                            review_rows.append({"market": market, "company": company,
                                                "on_chart": bool(brand.get("on_chart")), "axis": axis,
                                                "parameter": pname, "score": v.get("score"),
                                                "issue": "Garbled numeric text in source evidence (digits "
                                                         "split by spaces) -- correct against the source",
                                                "justification": old_c[:400]})
                        ne = dict(e)
                        ne["claim"] = new_c
                        new_evidence.append(ne)
                        if new_c != old_c:
                            change_rows.append({"market": market, "company": company, "axis": axis,
                                                "parameter": pname, "field": "evidence.claim",
                                                "tags": ",".join(sorted(tags)), "old": old_c, "new": new_c})
                    claims = [e for e in old_evidence if isinstance(e, dict)]
                    unsupported = bool(claims) and placeholders == len(claims)
                    if not claims:
                        unsupported = v.get("score") is not None
                    new_basis, btags = rewrite_basis(old_basis, unsupported=unsupported,
                                                     claims_unverified=claim_unverified)
                    stats["justifications_reviewed"] += 1
                    if "unsupported" in btags:
                        stats["unsupported_scores"] += 1
                    elif "unverified" in btags:
                        stats["unverified_justifications_updated"] += 1
                    if "attribution" in btags:
                        stats["desk_attribution_justifications"] += 1
                    if new_basis != old_basis:
                        change_rows.append({"market": market, "company": company, "axis": axis,
                                            "parameter": pname, "field": "assessed_on",
                                            "tags": ",".join(sorted(btags)), "old": old_basis, "new": new_basis})

                    score = v.get("score")
                    on_chart = bool(brand.get("on_chart"))
                    if unsupported:
                        reason = "Score assigned without verifiable supporting evidence"
                        if _STRONG_POSITIVE.search(old_basis):
                            reason += "; justification asserts capability with no evidence (contradictory)"
                        review_rows.append({"market": market, "company": company, "on_chart": on_chart,
                                            "axis": axis, "parameter": pname, "score": score,
                                            "issue": reason, "justification": old_basis[:400]})
                    elif score is not None and score >= 85 and _WEAK_BAND.search(old_basis):
                        review_rows.append({"market": market, "company": company, "on_chart": on_chart,
                                            "axis": axis, "parameter": pname, "score": score,
                                            "issue": "Displayed score is high but justification describes a "
                                                     "weak/lowest band (cohort normalisation) -- contradictory",
                                            "justification": old_basis[:400]})
                        stats["score_justification_mismatch"] += 1

                    if new_basis != old_basis or new_evidence != old_evidence:
                        if new_basis or "assessed_on" in v:
                            v["assessed_on"] = new_basis
                        if "evidence" in v:
                            v["evidence"] = new_evidence
                        json_changed = True

                    if html_new is not None and on_chart:
                        cell_total += 1
                        hit = False
                        new_ul = _evidence_bullets(new_evidence)
                        if old_basis:
                            ob = f'<div class="cq-ta-basis">{_esc(old_basis)}</div>'
                            nb = f'<div class="cq-ta-basis">{_esc(new_basis)}</div>'
                            if ob in html_new:
                                html_new = html_new.replace(ob, nb)
                                hit = True
                            elif nb in html_new:
                                hit = True
                            regenerated.add(nb)
                        # Reports built before the abbreviation-aware splitter
                        # render the same evidence as different bullets.
                        for ou in {_evidence_bullets(old_evidence), *_legacy_bullet_variants(old_evidence)}:
                            if ou and ou in html_new:
                                html_new = html_new.replace(ou, new_ul)
                                hit = True
                        if new_ul and new_ul in html_new:
                            hit = True
                        if new_ul:
                            regenerated.add(new_ul)
                        cell_hits += int(hit)

        # Older report layouts: evidence cells whose text no longer matches the
        # JSON are rewritten in place with the same rules, sentence by sentence.
        if html_new is not None:
            def _fix_basis(m: re.Match) -> str:
                old = html_lib.unescape(m.group(1))
                new, _ = rewrite_basis(old, unsupported=False, claims_unverified=False)
                return f'<div class="cq-ta-basis">{_esc(new)}</div>'

            def _fix_li(m: re.Match) -> str:
                old = html_lib.unescape(m.group(1))
                new, _ = rewrite_claim(old)
                if new == old.strip():
                    return m.group(0)
                return "".join(f"<li>{_esc(s)}</li>" for s in _split_sentences(new))

            def _fix_cell(m: re.Match) -> str:
                cell = m.group(0)
                # Cells regenerated from the JSON above are already final.
                if any(frag in cell for frag in regenerated):
                    return cell
                before = cell
                cell = re.sub(r'<div class="cq-ta-basis">(.*?)</div>', _fix_basis, cell, flags=re.S)
                cell = re.sub(r"<li>(.*?)</li>", _fix_li, cell, flags=re.S)
                if cell != before:
                    stats["html_cells_rewritten_in_place"] += 1
                return cell

            html_new = re.sub(r'<td><div class="cq-ta-score-line">.*?</td>', _fix_cell, html_new, flags=re.S)

        stats["html_cells_matched_to_json"] += cell_hits
        if html_text is not None and cell_total and cell_hits < cell_total:
            shown = html_text.count('class="cq-ta-basis"')
            problems.append(f"{hpath.name}: report displays evidence for {shown} of {cell_total} chart "
                            f"parameter cells in the JSON (older report layout); only displayed cells "
                            f"were updated")

        if json_changed:
            stats["json_files_modified"] += 1
        if html_new is not None and html_new != html_text:
            stats["html_files_modified"] += 1
        if not dry_run:
            if json_changed:
                jpath.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            if html_new is not None and html_new != html_text:
                hpath.write_text(html_new, encoding="utf-8")

    review_dir.mkdir(parents=True, exist_ok=True)
    tag = folder.name.replace(" ", "_")
    with (review_dir / f"{tag}_manual_review.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["market", "company", "on_chart", "axis", "parameter",
                                           "score", "issue", "justification"])
        w.writeheader()
        w.writerows(review_rows)
    with (review_dir / f"{tag}_change_log.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["market", "company", "axis", "parameter", "field",
                                           "tags", "old", "new"])
        w.writeheader()
        w.writerows(change_rows)
    return {"folder": str(folder), "stats": dict(stats), "problems": problems,
            "review_rows": len(review_rows), "changes": len(change_rows)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--folder", action="append", required=True)
    ap.add_argument("--review-dir", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sentence-map", default="",
                    help="JSON {old sentence: reviewed complete sentence} applied after the rules")
    ap.add_argument("--voice-map", default="",
                    help="JSON {old justification body or claim: reviewed analyst-voice rewrite}")
    args = ap.parse_args()
    if args.sentence_map:
        _SENTENCE_MAP.update(json.loads(Path(args.sentence_map).read_text(encoding="utf-8")))
    if args.voice_map:
        vm = json.loads(Path(args.voice_map).read_text(encoding="utf-8"))
        _VOICE_MAP.update(vm)
        _VOICE_NOTE_REQUIRED.update(new for old, new in vm.items() if _UNVERIFIED_MARKERS.search(old))
    results = [process_folder(Path(f), Path(args.review_dir), args.dry_run) for f in args.folder]
    print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
