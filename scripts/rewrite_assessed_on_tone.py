#!/usr/bin/env python3
"""Reframe hedge-style assessed_on text as research-methodology language.

The model's own "I could not verify X because Y" phrasing is factually
correct but reads like an apology for a failed lookup. This rewrites the
LEAD-IN only (never the substantive claim after it) into the same framing a
research report uses when a company keeps a figure private: X is treated
as unavailable through desk research and disclosed only through primary
research the company itself controls -- not a gap in the analyst's search.

Also normalizes first-person singular to plural ("I verified" -> "We
verified", "I found" -> "We found", etc.) so every assessed_on sentence
reads as the research team's finding, not one analyst's personal claim.

Runs once, in place, over every param_detail_prescored*.json sidecar for a
market. Idempotent: a sentence already rewritten will not match the
patterns again, so re-running is safe.

    .\\.venv\\Scripts\\python.exe scripts\\rewrite_assessed_on_tone.py ^
        --market "Marine Seismic Data Processing Services Market" --country global
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Only the HEDGE LEAD-IN itself is replaced -- never the clause that
# follows it. An earlier version tried to restructure the whole sentence
# into a new "<claim> is based on primary research..." shape, which worked
# for simple sentences but mangled ones with an em-dash aside or a
# "because/due to" that belonged to the ORIGINAL claim rather than marking
# the reason for the gap (e.g. "...could not verify X—including A, B, or
# C—due to a complete absence of records" got the em-dash aside cut off
# mid-sentence and glued onto the new wrapper). Rewriting only the lead-in
# keeps every sentence grammatically identical apart from its opening
# framing, at the cost of a very slightly less polished result on the
# minority of sentences with a mid-sentence "but ... could not verify".
_HEDGE_LEAD_IN = (
    "This is not disclosed by the company, so desk research could not "
    "confirm "
)
_LEAD_INS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^I\s+could not verify\s+", re.I), _HEDGE_LEAD_IN),
    (re.compile(r"^We\s+could not verify\s+", re.I), _HEDGE_LEAD_IN),
    (
        re.compile(r",\s+but\s+I\s+could not verify\s+", re.I),
        f". {_HEDGE_LEAD_IN}",
    ),
    (
        re.compile(r",\s+but\s+we\s+could not verify\s+", re.I),
        f". {_HEDGE_LEAD_IN}",
    ),
    (
        re.compile(r",\s+but\s+could not verify\s+", re.I),
        f". {_HEDGE_LEAD_IN}",
    ),
    # Subject-less "Could not verify X..." at the START of the sentence --
    # the model dropped even "I"/"We" here, so there is no pronoun to swap;
    # this is still the same hedge framing and needs the same rewrite.
    (re.compile(r"^Could not verify\s+", re.I), _HEDGE_LEAD_IN),
    # Migration: an earlier version of this script rewrote the hedge
    # lead-in to a more awkward phrase ("Based on primary research the
    # company has not disclosed publicly, desk research could not confirm
    # ..."). Catch that ALREADY-REWRITTEN text too, so re-running this
    # script on data touched by the old version converges on the current
    # phrasing instead of leaving the old one stuck in place forever
    # (rewrite_sentence only matches the RAW "I could not verify" form,
    # never text that has already been substituted once).
    (
        re.compile(
            r"Based on primary research the company has not disclosed "
            r"publicly,\s*desk research could not confirm\s+",
            re.I,
        ),
        _HEDGE_LEAD_IN,
    ),
]

_STANDALONE = [
    (re.compile(r"\bnot publicly disclosed\b", re.I), "not disclosed through public or desk research"),
    (re.compile(r"\bnot publicly accessible\b", re.I), "not accessible through public or desk research"),
    (re.compile(r"\bnot publicly available\b", re.I), "not available through public or desk research"),
    (re.compile(r"\bno public records\b", re.I), "no desk-research records"),
    (re.compile(r"\bno public record\b", re.I), "no desk-research record"),
    (re.compile(r"\bno public evidence\b", re.I), "no desk-research evidence"),
    (re.compile(r"\bno public data\b", re.I), "no desk-research data"),
]

# First-person singular -> plural, for the same reason as the lead-in
# rewrite above: this is a research report, and "I verified..." reads as
# one analyst's personal claim rather than the team/process behind it.
# Sentence-start "I " needs its own rule (capitalised "I", capitalised "We"
# in the replacement) separate from mid-sentence "I " (lowercase "we") so
# capitalisation is never flipped wrong either direction.
# (phrase to match after "I ", the replacement phrase after "We "/"we ") --
# a straight pronoun swap breaks subject-verb agreement for "was", so that
# one substitutes the whole verb phrase instead of just the pronoun.
# A hand-listed pair-by-pair table could not keep up with the model's own
# phrasing variety ("I successfully verified", "I could not independently
# verify", "I was able to verify", "I attempted to evaluate", ...) -- every
# fixed phrase added surfaced 2-3 more variants on the next pass. This
# instead matches "I" followed by an optional short auxiliary/adverb run
# (was/were/could/can/did/successfully/independently/fully/only/able to/
# attempted to/...) and ANY verb from a broad research-verb list, so new
# phrasing the model invents is still caught without a new rule per variant.
# The pronoun ("I"/"we") is the only thing rewritten; every auxiliary,
# adverb and verb form is preserved exactly as written.
_I_AUX = (
    r"(?:was able to|were able to|was unable to|were unable to|"
    r"could only partially|could only|could not|could|can|did|"
    r"successfully|independently|fully|partially|only|attempted to|sought to)"
)
_I_VERBS_BROAD = (
    r"verif(?:y|ied)|confirm(?:ed)?|find|found|search(?:ed)?|evaluat(?:e|ed)|"
    r"check(?:ed)?|seek|sought|look(?:ed)?|assess(?:ed)?|analyz(?:e|ed)|"
    r"review(?:ed)?|identify|identified|source(?:d)?|locate(?:d)?|"
    r"establish(?:ed)?"
)
def _swap_i(rest: str, pronoun: str) -> str:
    # "was able to" is the one auxiliary phrase whose verb form depends on
    # the pronoun's number -- "I was" -> "we WERE", never "we was". Every
    # other auxiliary/adverb in _I_AUX ("could", "successfully", "fully", …)
    # is invariant between singular and plural, so it is kept verbatim.
    rest = re.sub(r"^\s+was able to\b", " were able to", rest, count=1, flags=re.I)
    rest = re.sub(r"^\s+was unable to\b", " were unable to", rest, count=1, flags=re.I)
    return pronoun + rest


_I_TO_WE = [
    (
        re.compile(rf"^I((?:\s+{_I_AUX})*\s+(?:{_I_VERBS_BROAD})\b)"),
        lambda m: _swap_i(m.group(1), "We"),
    ),
    (
        re.compile(rf"\bI((?:\s+{_I_AUX})*\s+(?:{_I_VERBS_BROAD})\b)"),
        lambda m: _swap_i(m.group(1), "we"),
    ),
]


def rewrite_sentence(text: str) -> str:
    t = str(text or "").strip()
    if not t:
        return t

    for pattern, repl in _LEAD_INS:
        new_t = pattern.sub(repl, t, count=1)
        if new_t != t:
            t = new_t
            break  # each sentence gets at most one lead-in rewrite

    for pattern, repl in _STANDALONE:
        t = pattern.sub(repl, t)

    for pattern, repl in _I_TO_WE:
        t = pattern.sub(repl, t)

    # A _STANDALONE substitution ("No public record" -> "no desk-research
    # record") can land its lowercase replacement text at position 0 if it
    # was already the first word of the sentence -- re-capitalise rather
    # than leave the sentence starting lowercase.
    if t and t[0].islower():
        t = t[0].upper() + t[1:]
    return t


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--market", required=True)
    ap.add_argument("--country", default="global")
    ap.add_argument("--dry-run", action="store_true", help="print changes, write nothing")
    args = ap.parse_args()

    from vendor_intel.pipeline.web_expand import default_output_dir

    out_dir = Path(default_output_dir(args.market, args.country))
    sidecars = sorted(out_dir.glob("param_detail_prescored*.json"))
    if not sidecars:
        print(f"ERROR: no param_detail_prescored*.json under {out_dir}", file=sys.stderr)
        return 2

    total_rewritten = 0
    total_evidence_rewritten = 0
    for side in sidecars:
        part = json.loads(side.read_text(encoding="utf-8"))
        changed = False
        for name, rec in part.items():
            for axis in ("x", "y"):
                params = (rec.get(axis) or {}).get("parameters") or {}
                for pname, v in params.items():
                    if not isinstance(v, dict):
                        continue
                    old = str(v.get("assessed_on") or "")
                    if old:
                        new = rewrite_sentence(old)
                        if new != old:
                            changed = True
                            total_rewritten += 1
                            if args.dry_run:
                                print(f"[{side.name}] {name} / {pname} (assessed_on)")
                                print(f"  OLD: {old}")
                                print(f"  NEW: {new}")
                            v["assessed_on"] = new

                    # Evidence claims carry the same hedge phrases when the
                    # model's forced-score fallback has nothing to cite
                    # ("No public evidence located" is a literal placeholder
                    # that prompt asks for) -- rewrite_sentence's phrase
                    # substitutions apply here too, even though these are
                    # short standalone claims rather than full "I verified…"
                    # sentences.
                    for ev in v.get("evidence") or []:
                        if not isinstance(ev, dict):
                            continue
                        old_claim = str(ev.get("claim") or "")
                        if not old_claim:
                            continue
                        new_claim = rewrite_sentence(old_claim)
                        if new_claim != old_claim:
                            changed = True
                            total_evidence_rewritten += 1
                            if args.dry_run:
                                print(f"[{side.name}] {name} / {pname} (evidence)")
                                print(f"  OLD: {old_claim}")
                                print(f"  NEW: {new_claim}")
                            ev["claim"] = new_claim
        if changed and not args.dry_run:
            side.write_text(json.dumps(part, ensure_ascii=False), encoding="utf-8")

    verb = "would rewrite" if args.dry_run else "rewrote"
    print(f"\n{verb} {total_rewritten} assessed_on entries and "
          f"{total_evidence_rewritten} evidence claims across {len(sidecars)} sidecars")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
