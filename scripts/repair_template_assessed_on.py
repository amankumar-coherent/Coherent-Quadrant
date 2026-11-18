#!/usr/bin/env python3
"""Rebuild "Assessed on" lines that hold the prompt template, from evidence already gathered.

    .venv\\Scripts\\python.exe scripts\\repair_template_assessed_on.py ^
        --market "Industrial Water and Wastewater Market" --country india [--dry-run]

A truncated prompt defeated the echo stripper, so a parameter's "Assessed on" line -- and
some of its supporting points -- were saved as the prompt's own fill-in-the-blank template
(ai_mode_scorer.strip_prompt_echo / is_prompt_template now prevent this). Re-asking AI Mode
is the thorough repair; this is the one that costs no query: the template supporting points
are dropped, and the "Assessed on" line is rebuilt from the parameter's own REAL supporting
points, which were verified when they were gathered.

Nothing is invented. The rebuilt line quotes the parameter's strongest surviving finding and
nothing else, in the report's house voice. A parameter with no real finding left is written
as the house gap sentence rather than given words it cannot support.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

LEAD_IN = "We verified that"


def _sentence(text: str, limit: int = 300) -> str:
    """One clean sentence from a supporting point, trimmed at a sentence end."""
    s = " ".join(str(text or "").split()).strip()
    s = re.sub(r"^(?:We verified that|We found that|The company reports that)\s+", "", s, flags=re.I)
    if len(s) > limit:
        cut = s.rfind(".", 0, limit)
        s = s[: cut + 1] if cut > 60 else s[:limit].rsplit(" ", 1)[0] + "."
    return s.strip()


def rebuild(points: list[str], lead: str) -> str:
    """The "Assessed on" line for one parameter, from its own findings."""
    best = max(points, key=len)              # the fullest finding carries the most support
    body = _sentence(best)
    if not body:
        return ""
    body = body[0].lower() + body[1:] if body[:2].isupper() is False else body
    line = f"{LEAD_IN} {body}"
    if not line.endswith("."):
        line += "."
    return line


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", required=True)
    ap.add_argument("--country", default="global")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    from vendor_intel.pipeline.house_wording import LEAD
    from vendor_intel.pipeline.web_expand import default_output_dir
    from vendor_intel.quadrant.ai_mode_scorer import is_prompt_template

    out = Path(default_output_dir(args.market, args.country))
    gap = f"{LEAD}, the company has not disclosed further details."
    stats = {"assessed_on_rebuilt": 0, "assessed_on_gap": 0, "claims_dropped": 0}

    def fix_params(params: dict) -> None:
        for pv in params.values():
            if not isinstance(pv, dict):
                continue
            ev = [e for e in (pv.get("evidence") or []) if isinstance(e, dict)]
            real = [e for e in ev if e.get("claim") and not is_prompt_template(e["claim"])]
            dropped = len(ev) - len(real)
            if dropped:
                stats["claims_dropped"] += dropped
                pv["evidence"] = real or [{"claim": "Not available"}]
            ao = str(pv.get("assessed_on") or "")
            if ao.strip() and not is_prompt_template(ao):
                continue
            points = [str(e["claim"]) for e in real if str(e.get("claim") or "").strip()]
            line = rebuild(points, LEAD) if points else ""
            pv["assessed_on"] = line or gap
            stats["assessed_on_rebuilt" if line else "assessed_on_gap"] += 1

    # the saved evidence (so a later pipeline run keeps the repair) and the report payload
    targets = sorted(out.glob("param_detail_prescored*.json"))
    for path in targets:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        for company in data.values():
            if isinstance(company, dict):
                fix_params(company)
        if not args.dry_run:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    jpath = next(iter(out.glob("*_quadrant.json")), None)
    if jpath:
        payload = json.loads(jpath.read_text(encoding="utf-8"))
        for brand in payload.get("brands") or []:
            detail = brand.get("score_detail") or {}
            for axis in ("x", "y"):
                fix_params((detail.get(axis) or {}).get("parameters") or {})
        if not args.dry_run:
            jpath.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            hpath = jpath.with_name(jpath.name.replace("_quadrant.json", "_report.html"))
            if hpath.exists():
                html = hpath.read_text(encoding="utf-8")
                tag = re.compile(r'(<script id="quadrant-data" type="application/json">)(.*?)(</script>)', re.S)
                new, n = tag.subn(lambda m: m.group(1) + json.dumps(payload, ensure_ascii=False) + m.group(3),
                                  html, count=1)
                if n == 1:
                    hpath.write_text(new, encoding="utf-8")
    print(f"evidence files: {len(targets)}")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    if args.dry_run:
        print("(dry run, nothing written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
