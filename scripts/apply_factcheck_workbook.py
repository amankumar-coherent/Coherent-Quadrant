#!/usr/bin/env python3
"""Apply a fact-check workbook (<slug>_fact_check.xlsx) to a finished report,
with no new searches: rebuild the report from its own quadrant.json.

The workbook (made by an earlier AI Mode check, e.g. on another machine) has a
"Companies" sheet (Real or Fake, Active?, Acquired?, Acquired by, Year, AI Mode
reason) and a "Key Takeaways" sheet (each score rationale / evidence statement
with Fabricated? Yes / No / Not confirmed). Applied rules, the same for every
market:

- a company marked Fake or Inactive is removed (an absorbed acquisition is
  Inactive); a removed chart company is NOT replaced;
- an active company acquired by another gets "Name (acquired by Owner)" for a
  deal under 3 years old, else "(subsidiary of Owner)" -- not for a minority
  stake (a stated share under 50 %), and not when the "owner" is the company;
- a statement marked Fabricated = Yes is removed (evidence bullet), or, for a
  score rationale, replaced by a neutral basis-then-gap sentence; "Not
  confirmed" stays (unproven is not false). Statements are matched by company,
  parameter and wording (>= 85 % similar), since the workbook may come from a
  slightly reworded copy of the report;
- house wording on every text (primary research gap sentence, citation
  clean-up) and the "Not available" rule.

Writes <out>/<slug>_quadrant.json, _report.html (interactive), .pdf and .docx.

    .venv\\Scripts\\python.exe scripts\\apply_factcheck_workbook.py ^
        --report-json "...\\x_india_quadrant.json" --workbook "...\\x_india_fact_check.xlsx" --out output\\factcheck_applied\\x_india
"""
from __future__ import annotations

import argparse
import datetime
import difflib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

NOT_AVAILABLE = "Not available"
WHY_REPLACEMENT = ("The rating rests on the supporting points listed for this parameter. "
                   "Based on primary research, the company has not disclosed further independently verified details.")
_LABEL = re.compile(r"\s*\((?:acquired by|subsidiary of)\s[^)]*\)\s*$", re.I)
_PCT = re.compile(r"(\d{1,2}(?:\.\d+)?)\s*%")


def norm(s) -> str:
    from vendor_intel.pipeline.quadrant_pipeline import norm_name
    return norm_name(str(s or ""))


def minority_stake(reason: str) -> bool:
    """A stated share under 50 % is an investment, not ownership."""
    text = str(reason or "")
    shares = [float(m) for m in _PCT.findall(text)]
    return (bool(shares) and max(shares) < 50
            and not re.search(r"\b(?:majority|remaining|wholly|full|entire)\b", text, re.I))


def owner_label(owner: str, year) -> str:
    m = re.search(r"(19|20)\d{2}", str(year or ""))
    recent = bool(m) and datetime.date.today().year - int(m.group(0)) < 3
    return f"{'acquired by' if recent else 'subsidiary of'} {owner}"


def load_workbook_rows(path: Path):
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True)
    def rows(sheet):
        it = list(wb[sheet].iter_rows(values_only=True))
        head = [str(h) for h in it[0]]
        return [dict(zip(head, r)) for r in it[1:] if r and any(r)]
    return rows("Companies"), rows("Key Takeaways")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report-json", required=True)
    ap.add_argument("--workbook", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-print", action="store_true", help="skip PDF / Word")
    args = ap.parse_args()

    from primary_research_wording import to_primary
    from vendor_intel.pipeline.company_facts import clean_artifacts
    from vendor_intel.quadrant.viewer import write_viewer

    src = Path(args.report_json)
    payload = json.loads(src.read_text(encoding="utf-8"))
    companies, takeaways = load_workbook_rows(Path(args.workbook))
    status = {norm(c.get("Company")): c for c in companies}

    removed, labelled, minority = [], [], []
    kept = []
    for b in payload.get("brands") or []:
        name = str(b.get("company_key") or _LABEL.sub("", str(b.get("company") or "")))
        c = status.get(norm(name)) or status.get(norm(b.get("company")))
        if c and (str(c.get("Real or Fake")).lower() == "fake" or str(c.get("Active?")).lower() != "active"):
            removed.append((name, c.get("Real or Fake"), c.get("Active?"), str(c.get("AI Mode reason") or "")[:160]))
            continue
        if c and str(c.get("Acquired?")).lower().startswith("acquired") and str(c.get("Acquired by") or "").strip():
            owner = str(c["Acquired by"]).strip()
            if minority_stake(c.get("AI Mode reason")):
                minority.append((name, owner))
            elif norm(owner) and norm(owner) not in norm(name) and norm(name) not in norm(owner):
                b["company"] = f"{name} ({owner_label(owner, c.get('Year'))})"
                labelled.append(b["company"])
        kept.append(b)
    payload["brands"] = kept

    # Fabricated statements, matched by company + parameter + wording.
    by_key: dict[tuple[str, str], list[dict]] = {}
    for t in takeaways:
        by_key.setdefault((norm(t.get("Company")), str(t.get("Parameter") or "").strip().lower()), []).append(t)

    def fabricated(company: str, param: str, text: str) -> bool:
        best, best_r = None, 0.0
        for t in by_key.get((norm(company), param.strip().lower()), []):
            s = str(t.get("Statement") or "")
            r = 1.0 if s == text else difflib.SequenceMatcher(None, s, text).ratio()
            if r > best_r:
                best, best_r = t, r
        return bool(best) and best_r >= 0.85 and str(best.get("Fabricated?")).strip().lower() == "yes"

    n_ev = n_why = 0
    for b in payload["brands"]:
        name = str(b.get("company_key") or _LABEL.sub("", str(b.get("company") or "")))
        for ax in ("x", "y"):
            for pname, v in (((b.get("score_detail") or {}).get(ax) or {}).get("parameters") or {}).items():
                if not isinstance(v, dict):
                    continue
                why = str(v.get("assessed_on") or "")
                if why and fabricated(name, pname, why):
                    why, n_why = WHY_REPLACEMENT, n_why + 1
                v["assessed_on"] = to_primary(clean_artifacts(why)) if why else why
                ev = []
                for e in v.get("evidence") or []:
                    claim = str((e or {}).get("claim") or "")
                    if claim and claim != NOT_AVAILABLE and fabricated(name, pname, claim):
                        n_ev += 1
                        continue
                    claim = to_primary(clean_artifacts(claim)) if claim and claim != NOT_AVAILABLE else claim
                    if claim:
                        ev.append({**e, "claim": claim})
                real = [e for e in ev if e["claim"] != NOT_AVAILABLE]
                v["evidence"] = real or [{"claim": NOT_AVAILABLE}]

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    slug = src.name.replace("_quadrant.json", "")
    (out / f"{slug}_quadrant.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    html = write_viewer(payload, out / f"{slug}_report.html")
    if not args.no_print:
        for script in ("export_report_pdf.py", "export_report_docx.py"):
            subprocess.call([sys.executable, str(ROOT / "scripts" / script), "--html", str(html)], cwd=str(ROOT))
    report = {"source": str(src), "workbook": str(args.workbook), "companies_before": len(companies),
              "companies_after": len(payload["brands"]),
              "chart_after": sum(1 for b in payload["brands"] if b.get("on_chart")),
              "removed": removed, "labelled": labelled, "minority_stakes_not_labelled": minority,
              "fabricated_evidence_removed": n_ev, "fabricated_rationales_replaced": n_why}
    (out / "factcheck_applied.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in report.items()
                      if k not in ("source", "workbook")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
