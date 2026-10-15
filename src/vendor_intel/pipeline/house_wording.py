"""Report house style for research attributions (owner 2026-10-15).

The pipeline's own steps write and recognise the phrases "Based on primary
research, ..." and "... can be estimated as ...": the tone step leaves an
estimate sentence alone by that phrase, the estimate step finds its gap
sentences by it, and the fact-check matches corrections against it. So those
phrases stay inside the pipeline, and the client-facing wording is applied
once, when the report is written (HTML, JSON, CSV, PDF and Word all read it):

  Based on primary research, the company's X can be estimated as Y, based on Z.
      -> As per our findings, the company's X is Y, based on Z.
  Based on primary research, the company has not disclosed X.
      -> As per our findings, the company has not disclosed X.
  ..., according to primary research.  /  According to primary research, ...
      -> ..., as per our findings.     /  As per our findings, ...

``to_legacy`` maps a reworded supporting point back, so a correction written
against the report text still finds its sentence in the evidence files.
"""
from __future__ import annotations

import re
from typing import Any

LEAD = "As per our findings"


# "the company's <metric> can be estimated as / at approximately"
_EST = re.compile(r"(\b[Tt]he company's (.+?)) can be estimated (as|at approximately) ")
_PAIRS = [
    (re.compile(r"\bBased on primary research,\s+"), f"{LEAD}, "),
    (re.compile(r"\bHowever, based on primary research,\s+"), f"However, {LEAD.lower()}, "),
    (re.compile(r"\bbased on primary research,\s+"), f"{LEAD.lower()}, "),
    (re.compile(r"\bAccording to primary research,\s+"), f"{LEAD}, "),
    (re.compile(r",\s+according to primary research\b"), f", {LEAD.lower()}"),
    (re.compile(r"\baccording to primary research\b"), LEAD.lower()),
]


def to_house(text: str) -> str:
    """One text in the report's house style; anything else is unchanged."""
    s = str(text or "")
    if "primary research" not in s and "can be estimated" not in s:
        return s

    def est(m: re.Match) -> str:
        # Always "is", as in the owner's own examples ("... networks and
        # formulary listings is extensive ..."): the owner's chosen wording.
        return f"{m.group(1)} is " + ("approximately " if m.group(3).startswith("at") else "")

    s = _EST.sub(est, s)
    for pat, rep in _PAIRS:
        s = pat.sub(rep, s)
    return s


def to_legacy(text: str) -> str:
    """A reworded supporting point back in the pipeline's own phrasing (for
    matching a correction written against the report text)."""
    s = str(text or "")
    s = s.replace(f", {LEAD.lower()}", ", according to primary research")
    s = re.sub(rf"^{LEAD},\s+", "According to primary research, ", s)
    return s


def apply(obj: Any) -> Any:
    """Every string in a report payload / row list, in house style."""
    if isinstance(obj, str):
        return to_house(obj)
    if isinstance(obj, list):
        return [apply(v) for v in obj]
    if isinstance(obj, dict):
        return {k: apply(v) for k, v in obj.items()}
    return obj
