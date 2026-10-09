#!/usr/bin/env python3
"""Rewrite missing-evidence wording in finished reports into primary-research
language, per the report owner's house style:

    "Desk research could not confirm X"
        -> "Based on primary research, the company has not disclosed X"
    "Desk research identified no evidence of X"
        -> "Based on primary research, the company has not disclosed evidence of X"
    "X is not publicly reported and could not be verified through primary research."
        -> "Based on primary research, the company has not disclosed X."
    "Could not be verified through primary research."  (standard note)
        -> "Based on primary research, the company has not disclosed this information."
    "Information not confirmed through desk research could not be verified
     through primary research."  (standard closing note)
        -> "Based on primary research, the company has not disclosed further details."

A POSITIVE finding is never relabelled as primary research (that would
invent a confirmed result): "Desk research confirms X" -> "Secondary research
confirms X", the standard industry term for the same thing.

Sentences the rules cannot rewrite safely are left untouched and listed in
<review-dir>/leftovers.json; a reviewed map of {old text: new text} can be
passed back with --map. Only evidence claims and "why" justifications change
-- scores, keys, company data and HTML structure do not. HTML cells are
regenerated from the JSON exactly as standardize_evidence_language.py does.

    .\\.venv\\Scripts\\python.exe scripts\\primary_research_wording.py ^
        --folder "C:\\Users\\me\\Desktop\\Fire Market Quadrant" --review-dir out [--map m.json] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_I = re.I
PR = "Based on primary research, the company has not disclosed"
NOTE_ITEM = f"{PR} this information."
NOTE_CLOSING = f"{PR} further details."
NOTE_OPEN = f"{PR} information for this parameter."

# What must not survive in evidence or justifications.
PROHIBITED = re.compile(
    r"desk[- ]research|could not (?:be )?(?:verif|confirm)\w*|unable to (?:verif|confirm)\w*|"
    r"cannot be (?:verified|confirmed)|not (?:be )?(?:verified|confirmed)\b|could not verify", _I)

_NEG_VERB = r"(?:could not|was unable to|were unable to|did not|cannot|could not independently)"
_CONFIRM = r"(?:confirm|verify|validate|corroborate|substantiate|establish|identify|locate|find|trace|isolate|determine|quantify)"
_SUBJ_END = (r"(?:could not|cannot|can not) be (?:independently )?(?:confirmed|verified|validated|"
             r"substantiated|established|corroborated|authenticated|determined|quantified|isolated|"
             r"located|identified|found|traced)(?: (?:through|via|from|in|by|using) (?:desk[- ]research|"
             r"secondary research|public|third-party|independent|open)[^,.;]*)?")
# A noun phrase: never crosses a verb or a "but / though" clause, so a
# positive finding earlier in the sentence is never swallowed into the
# "has not disclosed" object.
_NP = (r"(?:(?!\b(?:but|though|although|while|whereas|however|is|are|was|were|has|have|had|"
       r"confirms?|confirmed|verified|shows|outlines|provides|operates|indicates?|demonstrates?)\b)"
       r"[^.;!?])*?")
# "... not publicly reported in the company's tracking summaries." -- a trailing
# where-it-was-looked phrase the rewrite drops with the gap wording.
_GAP_TAIL = r"(?:\s+(?:in|on|by|through|within|for|across|under)\s[^.]*)?"
# The gap's own noun phrase may say "independently verified share" -- that is
# part of what was not disclosed -- so only "confirms/verified" are allowed back.
_NP_GAP = _NP.replace("confirms?|confirmed|verified|", "")
_RULES: list[tuple[re.Pattern[str], str]] = [
    # the two standard notes, as whole sentences
    (re.compile(r"Information not confirmed through desk research could not be verified through "
                r"primary research\."), NOTE_CLOSING),
    (re.compile(r"(^|(?<=[.!?])\s+)Could not be verified through primary research\."),
     lambda m: f"{m.group(1)}{NOTE_ITEM}"),
    # "<X> is/are not publicly reported and could not be verified through primary research."
    (re.compile(rf"(^|[.!?]\s+|;\s+)([A-Z]{_NP}) (?:is|are|was|were) not publicly reported and "
                r"could not be verified through primary research\."),
     lambda m: f"{m.group(1)}{PR} {_lower_head(m.group(2).rstrip(" —–-"))}."),
    # The short form the evidence prompts produce: "<X> is/are not publicly reported."
    # (also "disclosed / available / documented"), optionally after "However,".
    # "We verified that <gap sentence>" -- the lead-in claims a check the gap
    # cannot show; drop it so the gap rules below can rewrite the sentence.
    (re.compile(r"(^|[.!?]\s+)We (?:verified|found|confirmed|noted) that (\w)"
                r"(?=[^.]*\bnot publicly (?:reported|disclosed|available|documented|detailed|specified|stated|published|shared|quantified)\b)"),
     lambda m: f"{m.group(1)}{m.group(2).upper()}"),
    # "We verified <X> are not publicly reported." (no "that", no clause before the gap)
    (re.compile(r"(^|[.!?]\s+)We (?:verified|found|confirmed|noted) (\w)(?=[^.,;]*\snot publicly)"
                r"(?=[^.,;]*\snot publicly (?:reported|disclosed|available|documented|detailed|specified|stated|published|shared|quantified))"),
     lambda m: f"{m.group(1)}{m.group(2).upper()}"),
    # "We verified that the rating rests on ..." -- the lead-in adds nothing.
    (re.compile(r"(^|[.!?]\s+)We (?:verified|found|confirmed|noted) that (?:the|our) "
                r"(rating|assessment|evaluation|score) (?=rests|is based|is supported|reflects|draws)"),
     lambda m: f"{m.group(1)}The {m.group(2)} "),
    # "(However,) (We verified that) <the company | Name> does not publicly report/disclose <X>."
    (re.compile(rf"(^|[.!?]\s+|;\s+)(However,\s+)?(?:We (?:verified|found|confirmed|noted) that )?"
                rf"(?:[Tt]he company|[Ii]t|[A-Z][\w&.'’\- ]{{1,60}}?) (?:does|do) not (?:publicly )?"
                rf"(?:report|disclose|detail|publish|share|specify|publicise|publicize|quantify)(?: publicly)? "
                rf"({_NP_GAP}){_GAP_TAIL}\."),
     lambda m: f"{m.group(1)}{'However, ' + PR[0].lower() + PR[1:] if m.group(2) else PR} "
               f"{_lower_head(m.group(3).rstrip(' —–-'))}."),
    # "We found no public reporting of <X>."
    (re.compile(rf"(^|[.!?]\s+)We (?:found|identified|located) no public (?:reporting|records?|evidence|"
                rf"information|data|disclosures?) (?:of|on|regarding|about|for|concerning) ({_NP_GAP})\."),
     lambda m: f"{m.group(1)}{PR} {_lower_head(m.group(2).rstrip(' —–-'))}."),
    # "No evidence exists of <X>."
    (re.compile(rf"(^|[.!?]\s+)No (?:evidence|record|information|data) exists (?:of|for|regarding|on) ({_NP_GAP})\."),
     lambda m: f"{m.group(1)}{PR} {_lower_head(m.group(2).rstrip(' —–-'))}."),
    # "No (verified) <X> are available in the public domain."
    (re.compile(rf"(^|[.!?]\s+)No ({_NP_GAP})\s*(?:is|are|was|were) (?:available|found|located|identified) "
                rf"in the public domain(?:\s+to\s[^.]*)?\."),
     lambda m: f"{m.group(1)}{PR} {_lower_head(m.group(2).rstrip(' —–-'))}."),
    # "Details regarding <X> are not public."
    (re.compile(rf"(^|[.!?]\s+)Details (?:regarding|on|about|of) ({_NP_GAP})\s*(?:is|are|was|were) not (?:made )?public\."),
     lambda m: f"{m.group(1)}{PR} details of {_lower_head(m.group(2).rstrip(' —–-'))}."),
    # "What is not publicly reported are <X>."
    (re.compile(rf"(^|[.!?]\s+)What (?:is|was) not publicly (?:reported|disclosed|documented) (?:is|are|was|were) ({_NP_GAP})\."),
     lambda m: f"{m.group(1)}{PR} {_lower_head(m.group(2).rstrip(' —–-'))}."),
    # "No information is publicly reported regarding <X>."
    (re.compile(rf"(^|[.!?]\s+)No (?:information|data|details|evidence|figures) (?:is|are|was|were|has been|have been) "
                rf"publicly (?:reported|disclosed|available|documented|detailed|specified|stated|published|shared|quantified) (?:regarding|on|about|concerning|for) ({_NP_GAP})\."),
     lambda m: f"{m.group(1)}{PR} {_lower_head(m.group(2).rstrip(' —–-'))}."),
    # "..., but no <X> are publicly reported."
    (re.compile(rf"(,\s+(?:but|while|although|though|yet)\s+)no ({_NP_GAP})\s*(?:is|are|was|were|has been|have been) "
                rf"publicly (?:reported|disclosed|available|documented|detailed|specified|stated|published|shared|quantified){_GAP_TAIL}\."),
     lambda m: f"{m.group(1)}{PR[0].lower()}{PR[1:]} {_lower_head(m.group(2).rstrip(' —–-'))}."),
    # "While <A>, <X> is not publicly reported."
    (re.compile(rf"(^|[.!?]\s+)While ([^,.]+), ({_NP_GAP})\s*(?:is|are|was|were) not publicly "
                rf"(?:reported|disclosed|available|documented|detailed|specified|stated|published|shared|quantified){_GAP_TAIL}\."),
     lambda m: f"{m.group(1)}While {m.group(2)}, {PR[0].lower()}{PR[1:]} "
               f"{_lower_head(m.group(3).rstrip(' —–-'))}."),
    (re.compile(rf"(^|[.!?]\s+|;\s+)However,\s+([A-Za-z]{_NP_GAP})\s*(?:is|are|was|were) not publicly "
                rf"(?:reported|disclosed|available|documented|detailed|specified|stated|published|shared|quantified){_GAP_TAIL}\."),
     lambda m: f"{m.group(1)}However, {PR[0].lower()}{PR[1:]} {_lower_head(m.group(2).rstrip(' —–-'))}."),
    (re.compile(rf"(^|[.!?]\s+|;\s+)([A-Z]{_NP_GAP})\s*(?:is|are|was|were) not publicly "
                rf"(?:reported|disclosed|available|documented|detailed|specified|stated|published|shared|quantified){_GAP_TAIL}\."),
     lambda m: f"{m.group(1)}{PR} {_lower_head(m.group(2).rstrip(' —–-'))}."),
    # "No <X> are publicly reported."
    (re.compile(rf"(^|[.!?]\s+)No ({_NP_GAP})\s*(?:is|are|was|were|has been|have been) publicly "
                rf"(?:reported|disclosed|available|documented|detailed|specified|stated|published|shared|quantified){_GAP_TAIL}\."),
     lambda m: f"{m.group(1)}{PR} {_lower_head(m.group(2).rstrip(' —–-'))}."),
    # "..., but <X> is not publicly reported." after a finding in the same sentence.
    (re.compile(rf"(,\s+(?:but|while|although|though|yet|meaning|so)\s+|;\s+(?:however,\s+)?)({_NP_GAP})\s*(?:is|are|was|were) "
                rf"not publicly (?:reported|disclosed|available|documented|detailed|specified|stated|published|shared|quantified){_GAP_TAIL}\."),
     lambda m: f"{m.group(1)}{PR[0].lower()}{PR[1:]} {_lower_head(m.group(2).rstrip(' —–-'))}."),
    # "(We verified that) there is no publicly reported evidence ... concerning <X>."
    (re.compile(rf"(^|[.!?]\s+)(?:We (?:verified|found) that )?[Tt]here (?:is|are|was|were) no publicly "
                r"(?:reported|available|disclosed) (?:evidence|data|information|figures)[^.]*? "
                rf"(?:concerning|regarding|on|about|of|for) ({_NP})\."),
     lambda m: f"{m.group(1)}{PR} {_lower_head(m.group(2).rstrip(" —–-"))}."),
    # "...; <X> could not be verified through primary research."
    (re.compile(rf"(;\s+|,\s+and\s+|,\s+)({_NP}) (?:could not|cannot) be verified through primary research\."),
     lambda m: f"{m.group(1)}{PR[0].lower()}{PR[1:]} {_lower_head(m.group(2).rstrip(" —–-"))}."),
    (re.compile(rf"(^|[.!?]\s+)([A-Z]{_NP}) (?:could not|cannot) be verified through primary research\."),
     lambda m: f"{m.group(1)}{PR} {_lower_head(m.group(2).rstrip(" —–-"))}."),
    (re.compile(r"\bnot disclosed through public or desk[- ]research\b", _I), "not disclosed by the company"),
    # "<X> could not be confirmed (through desk research ...)" -- the subject is
    # what was not found, so it becomes what the company has not disclosed.
    (re.compile(rf"(^|[.!?]\s+)([A-Z]{_NP}) {_SUBJ_END}"),
     lambda m: f"{m.group(1)}{PR} {_lower_head(m.group(2).rstrip(" —–-"))}"),
    (re.compile(rf"(,\s+(?:but|while|although|though|and|yet|however,?)\s+|;\s+(?:however,\s+)?|\bbut\s+)"
                rf"({_NP}) {_SUBJ_END}"),
     lambda m: f"{m.group(1)}{PR[0].lower()}{PR[1:]} {_lower_head(m.group(2).rstrip(" —–-"))}"),
    # "..., but it could not confirm X" (it = the research)
    (re.compile(rf"\b(?:it|this|the assessment|the review|the research) {_NEG_VERB} {_CONFIRM}\s+"),
     f"{PR[0].lower()}{PR[1:]} "),
    (re.compile(rf"(^|[.!?]\s+)(?:It|This|The assessment|The review|The research) {_NEG_VERB} {_CONFIRM}\s+"),
     lambda m: f"{m.group(1)}{PR} "),
    # "..., but <X> were not verified, leaving ..."
    (re.compile(rf"(,\s+(?:but|while|although|though|and|yet)\s+|;\s+|\bbut\s+)({_NP}) (?:is|are|was|were) "
                r"not (?:independently )?(?:verified|confirmed)\b"),
     lambda m: f"{m.group(1)}{PR[0].lower()}{PR[1:]} {_lower_head(m.group(2).rstrip(" —–-"))}"),
    (re.compile(rf"(^|[.!?]\s+)([A-Z]{_NP}) (?:is|are|was|were) not (?:independently )?(?:verified|confirmed)\b"),
     lambda m: f"{m.group(1)}{PR} {_lower_head(m.group(2).rstrip(" —–-"))}"),
    # "Desk research could not confirm X" (sentence start / after a clause)
    (re.compile(rf"(^|[.!?]\s+)Desk[- ]research {_NEG_VERB} {_CONFIRM}\s+"), lambda m: f"{m.group(1)}{PR} "),
    (re.compile(rf"([,;]\s+)desk[- ]research {_NEG_VERB} {_CONFIRM}\s+", _I),
     lambda m: f"{m.group(1)}{PR[0].lower()}{PR[1:]} "),
    (re.compile(rf"(\s)(?:but|and|yet) desk[- ]research {_NEG_VERB} {_CONFIRM}\s+", _I),
     lambda m: f", but {PR[0].lower()}{PR[1:]} "),
    # "Desk research identified/found no (supporting) evidence (of|for|regarding ...) X"
    (re.compile(r"(^|[.!?]\s+)Desk[- ]research (?:identified|found|located|uncovered|revealed) no "
                r"(supporting |verifiable |public |specific |direct |documented )?evidence"),
     lambda m: f"{m.group(1)}{PR} {(m.group(2) or '')}evidence"),
    (re.compile(r"([,;]\s+)desk[- ]research (?:identified|found|located|uncovered|revealed) no "
                r"(supporting |verifiable |public |specific |direct |documented )?evidence", _I),
     lambda m: f"{m.group(1)}{PR[0].lower()}{PR[1:]} {(m.group(2) or '')}evidence"),
    # "We were unable to verify X" / "We could not verify X"
    (re.compile(rf"(^|[.!?]\s+)(?:We|I) {_NEG_VERB} {_CONFIRM}\s+"), lambda m: f"{m.group(1)}{PR} "),
    # "not confirmed through desk research" inside a sentence
    (re.compile(r"\bnot confirmed through desk[- ]research\b", _I), "not disclosed by the company"),
    # positive desk-research findings keep their meaning under the industry term
    (re.compile(r"\bDesk[- ]research\b"), "Secondary research"),
    (re.compile(r"\bdesk[- ]research\b"), "secondary research"),
]
# A lone-standing primary-research note is redundant after a sentence that
# already says "Based on primary research, the company has not disclosed ...".
_DUP_NOTE = re.compile(rf"({re.escape(PR)}[^.]*\.)\s+{re.escape(PR)} (?:this information|further details)\.")
_DUP_ITEM_CLOSING = re.compile(rf"{re.escape(NOTE_ITEM)}\s+{re.escape(NOTE_CLOSING)}")
# ... and before one: "…this information. Based on primary research, the company has not disclosed X."
_NOTE_BEFORE_PR = re.compile(rf"{re.escape(NOTE_ITEM)}\s+(?={re.escape(PR)})")

_NO_FIND_SENT = re.compile(
    r"(^|(?<=[.!?])\s)\s*(?:We (?:verified|found|confirmed|noted) that |The (?:rating|evaluation|assessment) "
    r"(?:rests|is based) on the fact that )?[Nn]o (?:[\w-]+\s+){0,10}?(?:evidence|data|records?|information|"
    r"findings|metrics|reports|statements|figures|details)\b[^.]*?"
    r"\b(?:(?:is|are|was|were|could be) (?:found|identified|located|available|established|confirmed|verified)|"
    r"exists?)\b[^.]*\.\s*")
# "..., there is no specific public evidence of X." -- the gap as a clause,
# with or without a house sentence elsewhere in the text.
_THERE_IS_NO = re.compile(
    r"(^|[.!?]\s+|,\s+(?:but\s+|and\s+|while\s+)?)(?:[Tt]here (?:is|are|was|were) )no (?:(?:specific|public|"
    r"confirmed|direct|verifiable|independent|documented|publicly available)\s+)+(?:evidence|data|information|"
    r"records?) (?:of|for|regarding|on|about|concerning) ([^.;]+?)\.")
_NO_FIND_CLAUSE = re.compile(
    r",\s*(?:while|but|and|whereas)\s+(?:no (?:[\w-]+\s+){0,10}?(?:evidence|data|records?|information|findings|"
    r"metrics|reports|statements|figures|details)\b[^.]*?(?:is|are|was|were) (?:identified|found|available)|"
    r"[^,.]*?\bremains? undisclosed)(?=\.)")

# "We verified that no specific funding rounds ... have been publicly recorded
# for the company." -- a gap sentence beside the house one, whatever its noun.
_NONE_RECORDED = re.compile(
    r"(^|(?<=[.!?])\s)\s*(?:We (?:verified|found|confirmed|noted) that )?[Nn]o [^.]{3,240}?\b(?:has|have|had) "
    r"been (?:publicly |formally )?(?:recorded|reported|announced|disclosed|documented|published)\b[^.]*\.\s*")

# Sentence-level fallback for gap wording the specific rules above do not
# match: the model phrases "we could not find it" in endless ways, so any
# sentence or clause carrying a gap phrase is rewritten as a whole.
_GAP_ANY = re.compile(
    r"\bno (?:[\w-]+,? ){0,10}?(?:evidence|data|records?|information|findings|metrics|reports|statements|"
    r"figures|details|documentation)\b|\bfound no\b|\bnot publicly\b|\bremains? undisclosed\b|"
    r"\b(?:is|are|was|were|has been|have been|had been) not (?:publicly )?(?:detailed|disclosed|reported|available|documented)\b|"
    r"\b(?:has|have|had) not been (?:publicly |officially )?(?:detailed|disclosed|reported|made public|documented)\b", re.I)
# ", though X were not disclosed" is a gap clause after a finding: without the
# split the whole finding became the object of "has not disclosed".
_CLAUSE_SPLIT = re.compile(r",\s+but\s+|;\s*however,?\s+|,\s+however,?\s+|,\s+while\s+|\s+but\s+|;\s+|"
                           r",\s+(?:al)?though\s+")
_GAP_OBJECT = re.compile(r"\b(?:evidence|documentation|data|records?|information|details|metrics|figures|reports|"
                         r"statements|findings)\s+(?:of|regarding|concerning|on|about|for|detailing|confirming)\s+(.+)$"
                         r"|\b(?:regarding|concerning)\s+(.+)$", re.I)
_BAND_TAIL = re.compile(r",\s*(?:placing|positioning|which (?:places|positions|puts|keeps))\b[^.]*?"
                        r"\b(?:band|score|scoring|tier|rating)\b[^.]*", re.I)
_SUBJECT_GAP = re.compile(r"^(?:the\s+)?(.+?)\s+(?:(?:is|are|was|were) not|(?:has|have|had) not been) (?:publicly |officially )?"
                          r"(?:detailed|disclosed|reported|available|documented)\b", re.I)


def _gap_object(part: str) -> str:
    ms = _SUBJECT_GAP.search(part.strip())
    if ms and not re.match(r"(?:we|it|this|there)\b", ms.group(1), re.I):
        return _lower_head(ms.group(1).strip(" ,.;"))
    m = _GAP_OBJECT.search(part)
    obj = (m.group(1) or m.group(2)) if m else ""
    if not obj:
        # "No independent findings or verified figures exist to ..." -- the
        # gap is the noun phrase itself.
        mn = re.search(r"\bno\s+(.+?)\s+(?:exists?|(?:is|are|was|were) (?:found|available|identified))\b", part, re.I)
        obj = mn.group(1) if mn else ""
    obj = re.sub(r"\s+(?:could|can|was|were|is|are|has|have)\b.*$", "", obj or "").strip(" ,.;")
    obj = re.sub(r"\s+(?:in|within|from) (?:public|published|the public)\b.*$", "", obj).strip(" ,.;")
    return _lower_head(obj) if obj else "further details"


def _rewrite_gap_sentences(t: str) -> str:
    t = _BAND_TAIL.sub("", t)
    # "...has not disclosed X remains undisclosed (or self-reported)." -- a
    # gap stated twice inside the house sentence; keep the house wording.
    t = re.sub(rf"({re.escape(PR)}[^.]*?)\s+(?:remains?|is|are) (?:undisclosed|not disclosed)"
               r"(?:\s+or\s+self-reported)?(?=\.)", r"\1", t)
    has_pr = PR.lower() in t.lower()
    out = []
    for s in re.split(r"(?<=[.!?])\s+", t.strip()):
        if not s or s.startswith(PR) or not _GAP_ANY.search(s):
            out.append(s)
            continue
        body = s.rstrip(".")
        # "While X remain undisclosed, Y." -> "Y." (+ the gap, if not stated yet)
        mw = re.match(r"^While\s+(.+?)\s+remains?\s+undisclosed,\s+(.+)$", body)
        if mw:
            rest = mw.group(2)
            out.append(rest[:1].upper() + rest[1:] + ".")
            if not has_pr:
                out.append(f"{PR} {_lower_head(mw.group(1))}.")
                has_pr = True
            continue
        g = _GAP_ANY.search(body)
        cut = None
        for c in _CLAUSE_SPLIT.finditer(body):
            if c.start() < g.start():
                cut = c
        head = body[: cut.start()].strip() if cut else ""
        gap = body[cut.end():] if cut else body
        if head and not _GAP_ANY.search(head):
            out.append(head.rstrip(",;") + ".")
        if not has_pr:
            out.append(f"{PR} {_gap_object(gap)}.")
            has_pr = True
    return " ".join(x for x in out if x)


_KEEP_CASE = re.compile(r"^(?:[A-Z]{2,}|[A-Z][a-z]*[A-Z]|[A-Z]\w*\d)")


def _lower_head(s: str) -> str:
    """Lower-case the first word of a noun phrase unless it is a name/acronym."""
    s = s.strip()
    first = s.split(" ", 1)[0]
    if not first or _KEEP_CASE.match(first):
        return s
    if first in {"The", "Its", "Their", "Any", "Specific", "Named", "Independent", "Third-party",
                 "Detailed", "Quantitative", "Formal", "Documented", "Audited", "Verified", "Public",
                 "Contracts", "Customer", "Client", "Commercial", "Operational", "Exact", "Direct",
                 "Standalone", "Proprietary", "Peer-comparable", "Published", "Further", "Delivery",
                 "Cost", "Pricing", "Revenue", "Market", "Industry", "Company", "Project", "Turnaround",
                 "Independently", "Third", "Recent", "Current", "Global", "Regional", "Financial",
                 "Benchmarks", "Case", "Milestone", "Wider", "Broader", "Explicit", "Measurable",
                 "Advanced", "Dedicated", "Large-scale", "Quantified", "Individual"}:
        return first.lower() + s[len(first):]
    return s


MAP: dict[str, str] = {}


_ESTIMATE_SENT = re.compile(r"\bcan be estimated (?:as|at approximately) ")


def to_primary(text: str) -> str:
    """House wording for gaps. A sentence that is an analyst estimate (step 7c:
    "... can be estimated as high, based on ...") is left exactly as written:
    its words ("no evidence of limits", "not publicly ...") would otherwise be
    read as a gap and rewritten into "has not disclosed ..." on a re-run."""
    t = str(text or "")
    if not _ESTIMATE_SENT.search(t):
        return _to_primary(t)
    parts = re.split(r"(?<=[.!?])\s+", t.strip())
    return " ".join(p if _ESTIMATE_SENT.search(p) else _to_primary(p) for p in parts if p)


def _to_primary(text: str) -> str:
    t = str(text or "")
    if not t.strip():
        return t
    if t in MAP:
        return MAP[t]
    for rx, repl in _RULES:
        t = rx.sub(repl, t)
    # "has not disclosed Historical milestone records" -> "historical": a
    # sentence-initial capital carried over from the old subject. A capitalised
    # word followed by a lower-case one is ordinary wording; "Full Waveform
    # Inversion" (a name) keeps its capitals.
    t = re.sub(rf"({re.escape(PR[1:])} )([A-Z][a-z]+)(?=\s+(?:[a-z(]|[A-Z]{{2,}}\b)|[,.;])",
               lambda m: m.group(1) + m.group(2).lower(), t)
    # "the company has not disclosed the company's X" -> "... its X"
    t = t.replace(f"{PR[1:]} the company's ", f"{PR[1:]} its ")
    # "<X> remain(s) undisclosed." as its own sentence -> the house gap sentence.
    # The subject never crosses a comma: "A, but X remain undisclosed." is a
    # clause after a finding, handled by _NO_FIND_CLAUSE below.
    t = re.sub(r"(^|(?<=[.!?])\s)([A-Z][^.,;]*?)\s+remains? undisclosed\.",
               lambda m: f"{m.group(1)}{PR} {_lower_head(m.group(2))}.", t)
    # "there is no specific public evidence of X" -> the house gap sentence.
    t = _THERE_IS_NO.sub(
        lambda m: (f"{m.group(1)}{PR} {_lower_head(m.group(2))}." if not m.group(1).startswith(",")
                   else f"{m.group(1)}{PR[0].lower()}{PR[1:]} {_lower_head(m.group(2))}."), t)
    # "..., but X remain undisclosed." with no house gap sentence yet -> becomes it.
    if PR.lower() not in t.lower():
        t = re.sub(r",\s*(but|while|though|although|whereas|yet)\s+([^,.;]*?)\s+remains? undisclosed\.",
                   lambda m: f", {m.group(1)} {PR[0].lower()}{PR[1:]} {_lower_head(m.group(2))}.", t)
    # A text that already states its gap in house words does not also need
    # "No specific evidence ... was found" / ", but X remain undisclosed":
    # the same gap twice, once in the wording the house style forbids.
    if PR.lower() in t.lower():
        t = _NO_FIND_SENT.sub(lambda m: m.group(1), t)
        t = _NO_FIND_CLAUSE.sub("", t)
        t = _NONE_RECORDED.sub(lambda m: m.group(1), t)
    # "verified self-reported" contradicts itself: a company's own claim is
    # self-reported, and "verified" is kept for independent sources.
    t = re.sub(r"\bverified (self-reported)\b", r"\1", t, flags=re.I)
    # "We verified that the company's rating rests on" -> "The rating rests on"
    t = re.sub(r"\bWe verified that the (?:company's )?(rating|evaluation|assessment) (rests|is based)\b",
               lambda m: f"The {m.group(1)} {m.group(2)}", t)
    t = _DUP_ITEM_CLOSING.sub(NOTE_ITEM, t)
    t = _NOTE_BEFORE_PR.sub("", t)
    # Opening a text, "this information" has nothing to point back to.
    if t.startswith(NOTE_ITEM):
        t = NOTE_OPEN + t[len(NOTE_ITEM):]
    t = _DUP_NOTE.sub(r"\1", t)
    # The closing note repeats a gap the text has already stated in the same
    # primary-research words, so it is dropped there.
    if t.endswith(NOTE_CLOSING) and PR.lower() in t[: -len(NOTE_CLOSING)].lower():
        t = t[: -len(NOTE_CLOSING)].rstrip()
    t = _rewrite_gap_sentences(t)
    t = t.replace(f"{PR[1:]} the company's ", f"{PR[1:]} its ")
    t = re.sub(r"\s{2,}", " ", t).replace(" ,", ",").strip()
    # "..., but based on primary research" after a comma already present
    t = t.replace(",, but", ", but").replace(", , but", ", but")
    return t


def _rewrite(text: str, **_kw) -> tuple[str, set[str]]:
    new = to_primary(text)
    return new, ({"primary_wording"} if new != str(text or "") else set())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--folder", action="append", required=True)
    ap.add_argument("--review-dir", required=True)
    ap.add_argument("--map", default="", help="reviewed {old text: new text} JSON for leftovers")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.map:
        MAP.update(json.loads(Path(args.map).read_text(encoding="utf-8")))

    import standardize_evidence_language as sel

    # Same JSON->HTML machinery, new wording only: every other rule of that
    # script (notes, band removal, link tidying) already ran on these reports.
    sel.rewrite_claim = _rewrite
    sel.rewrite_basis = _rewrite
    review = Path(args.review_dir)
    review.mkdir(parents=True, exist_ok=True)
    leftovers: dict[str, dict] = {}
    for folder in args.folder:
        res = sel.process_folder(Path(folder), review, args.dry_run)
        print(json.dumps({"folder": res["folder"], "changes": res["changes"],
                          "json_files_modified": res["stats"].get("json_files_modified", 0),
                          "html_files_modified": res["stats"].get("html_files_modified", 0),
                          "html_cells_matched_to_json": res["stats"].get("html_cells_matched_to_json", 0)},
                         ensure_ascii=False))
        for jp in sorted(Path(folder).glob("*_quadrant.json")):
            p = json.loads(jp.read_text(encoding="utf-8"))
            for b in p.get("brands") or []:
                for ax in ("x", "y"):
                    for pname, v in ((b.get("score_detail") or {}).get(ax, {}).get("parameters") or {}).items():
                        texts = [("why", v.get("assessed_on") or "")] + [
                            ("claim", e.get("claim", "")) for e in v.get("evidence") or [] if isinstance(e, dict)]
                        for where, t in texts:
                            new = to_primary(t) if args.dry_run else t
                            if PROHIBITED.search(new):
                                leftovers.setdefault(new, {"file": jp.name, "company": b.get("company"),
                                                           "parameter": pname, "where": where,
                                                           "on_chart": bool(b.get("on_chart"))})
    (review / "leftovers.json").write_text(json.dumps(leftovers, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"leftover texts with prohibited wording: {len(leftovers)} -> {review / 'leftovers.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
