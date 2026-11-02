#!/usr/bin/env python3
"""Re-apply the report house wording to a finished report, in place.

    .venv\\Scripts\\python.exe scripts\\restyle_finished_report.py --folder "First Five Market" [--dry-run]

A report built before the owner changed the house lead keeps the old wording baked into its
JSON and HTML: the pipeline applies house_wording once, when the report is written, and these
markets have no saved _pipeline state to rebuild from. So the lead is replaced in the saved
payload and the payload re-embedded in the viewer HTML (<script id="quadrant-data">), which is
what the page renders from -- the same bytes the build step would have written.

Also repairs a supporting point the tone step mangled before its noun-phrase guard reached the
sentence-level fallback: "... has not disclosed company reports that <clause> and" swallowed a
reporting clause and broke off mid-sentence. The finding is restored as a company-stated claim
("The company reports that ..."), per the evidence rules. Nothing else changes -- no score, no
company, no chart position.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

OLD_LEADS = ("As per our findings", "as per our findings")
DATA_TAG = re.compile(r'(<script id="quadrant-data" type="application/json">)(.*?)(</script>)', re.S)

# "<lead>, the company has not disclosed <subject> reports that <clause> and" -- the gap wording
# wrapped around a company-stated claim. The claim is the finding; the broken gap goes.
MANGLED = re.compile(
    r"^\s*As per our (?:findings|analysis), the company has not disclosed\s+"
    r"(?:the\s+)?company reports that\s+(.+?)\s*(?:,?\s*and)?\s*\.\s*$", re.I)


_SENT_START = r"(^|(?<=[.!?])\s)"


def gap_tidy(s: str, lead: str) -> tuple[str, int]:
    """The malformed gap sentences primary_research_wording._GAP_TIDY now prevents, cleaned in a
    report already written. Same rules, with the house lead the report was written in."""
    pr = f"{lead}, the company has not disclosed"
    before = s
    s = re.sub(r"has not disclosed by the company\b", "has not disclosed", s)
    s = re.sub(r"the company has \w+ or has not disclosed\b", "the company has not disclosed", s)
    s = re.sub(rf"{_SENT_START}(?:We (?:verified|found|confirmed|noted)|The gap is) that "
               r"the company has not disclosed", rf"\g<1>{pr}", s)
    s = re.sub(rf"{_SENT_START}[Tt]he company has not disclosed", rf"\g<1>{pr}", s)
    s = re.sub(rf"{_SENT_START}has not disclosed\b", rf"\g<1>{pr}", s)
    # a supporting point that begins on a stray quote mark left by a trimmed citation
    s = re.sub(r'^\s*["“]\s*(?=[a-z])', "", s)
    return s, int(s != before)


def restyle_text(s: str, lead: str) -> str:
    for old in OLD_LEADS:
        s = s.replace(old, lead if old[0].isupper() else lead[0].lower() + lead[1:])
    return s


def repair(s: str) -> str:
    m = MANGLED.match(s)
    if not m:
        return s
    claim = m.group(1).strip().rstrip(",;")
    return f"The company reports that {claim}."


def walk(obj, lead: str, counts: dict):
    if isinstance(obj, str):
        fixed = repair(obj)
        if fixed != obj:
            counts["repaired"] += 1
            obj = fixed
        new = restyle_text(obj, lead)
        if new != obj:
            counts["reworded"] += 1
        new, tidied = gap_tidy(new, lead)
        counts["tidied"] += tidied
        return new
    if isinstance(obj, list):
        return [walk(v, lead, counts) for v in obj]
    if isinstance(obj, dict):
        return {k: walk(v, lead, counts) for k, v in obj.items()}
    return obj


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--folder", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    from vendor_intel.pipeline.house_wording import LEAD

    folder = Path(args.folder)
    total = {"reworded": 0, "repaired": 0, "tidied": 0}
    for jpath in sorted(folder.glob("*_quadrant.json")):
        payload = json.loads(jpath.read_text(encoding="utf-8"))
        counts = {"reworded": 0, "repaired": 0, "tidied": 0}
        payload = walk(payload, LEAD, counts)
        blob = json.dumps(payload, ensure_ascii=False, indent=2)
        hpath = jpath.with_name(jpath.name.replace("_quadrant.json", "_report.html"))
        html_ok = False
        if hpath.exists():
            html = hpath.read_text(encoding="utf-8")
            # The viewer renders from the embedded payload, so re-embedding it is the whole
            # update; the surrounding template is unchanged.
            new_html, n = DATA_TAG.subn(
                lambda m: m.group(1) + json.dumps(payload, ensure_ascii=False) + m.group(3), html, count=1)
            html_ok = n == 1
            if html_ok and not args.dry_run:
                hpath.write_text(new_html, encoding="utf-8")
        if not args.dry_run:
            jpath.write_text(blob + "\n", encoding="utf-8")
        for k in total:
            total[k] += counts[k]
        print(f"{jpath.name[:52]:<54} reworded={counts['reworded']:<5} repaired={counts['repaired']} tidied={counts['tidied']} "
              f"html={'ok' if html_ok else 'MISSING'}")
    print(f"\ntotal: {total['reworded']} strings reworded, {total['repaired']} repaired, {total['tidied']} tidied"
          f"{' (dry run, nothing written)' if args.dry_run else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
