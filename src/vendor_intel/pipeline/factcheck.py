"""Chart fact-check (pipeline step 8a): findings -> safe automatic decisions.

scripts/factcheck_chart.py asks Google AI Mode, per chart company, for its
status / owner / head office / scope and a verdict on every specific
supporting point (correct / incorrect / unverified). AI Mode's verdicts are
leads, not facts: in live runs it cited company-data directories, reported
"corrections" identical to the original and contradicted itself across two
claims. So only what passes the generic rules below is applied, written to
``_pipeline/factcheck_review.json`` in the analyst-review schema; the
analyst's own ``analyst_review.json`` always wins over it. Everything else
stays in ``_pipeline/factcheck/findings.md`` for a person.

Rules (the same for every market):
- status liquidated / dissolved / in administration WITH a stated event ->
  excluded (an acquired company that still trades is NOT excluded);
- scope adjacent -> off the chart (stays in Other Noticeable Players);
  scope out -> excluded;
- owner -> label only through company_facts.owner_entry (a real purchase,
  not a buyer, not a reverse merger);
- head office -> corrected only when the COUNTRY differs;
- a claim judged incorrect -> replaced by the corrected sentence only when
  the source is not a directory / estimate / review / research-publisher
  site, the edit is small, and the figure it removes is not confirmed by
  another check of the same company; a claim AI Mode says belongs to another
  company is removed.
"""
from __future__ import annotations

import difflib
import json
import re
from pathlib import Path
from typing import Any

from vendor_intel.pipeline.quadrant_pipeline import norm_name, write_json_atomic

FACTCHECK_DIR = "factcheck"
FACTCHECK_FILE = "factcheck_review.json"
SOURCE = "Automatic chart fact-check (Google AI Mode)"
# A supporting point worth checking names a figure, a date, a name or a deal.
_SPECIFIC = re.compile(r"\d|\"|“|‘|'[A-Z]|contract|awarded|partner|acquir|launched|won|selected|"
                       r"certif|ISO|approved|framework|customer|client|integrat", re.I)
_LABEL = re.compile(r"\s*\((?:acquired by|subsidiary of)\s[^)]*\)\s*$", re.I)
_GONE = {"liquidated", "dissolved", "in_administration"}
_OTHER_COMPANY = re.compile(r"\bbelongs? to\b|\banother (?:company|vendor|firm)\b|\bdifferent (?:company|vendor)\b|"
                            r"\bnot (?:a|the) (?:product|claim) of\b", re.I)
_NUM = re.compile(r"\d[\d,.]*")
_COUNTRY_ALIASES = {"usa": "us", "united states": "us", "united states of america": "us", "u.s.": "us",
                    "u.s.a.": "us", "uk": "uk", "united kingdom": "uk", "england": "uk", "great britain": "uk",
                    "uae": "uae", "united arab emirates": "uae"}


def _lines(path: Path) -> list[str]:
    try:
        return [x.strip() for x in path.read_text(encoding="utf-8").splitlines()
                if x.strip() and not x.lstrip().startswith("#")]
    except OSError:
        return []


def _bad_source_rx() -> re.Pattern[str]:
    """Sources that are not evidence: directories, modelled estimates,
    employee reviews and research publishers (all config lists)."""
    root = Path(__file__).resolve().parents[3] / "config"
    pats = []
    for name in ("estimate_sites.txt", "employee_review_sites.txt", "directory_sites.txt"):
        pats += _lines(root / name)
    pats += [re.escape(p) for p in _lines(root / "research_publishers.txt")]
    return re.compile("|".join(f"(?:{p})" for p in pats) or r"(?!x)x", re.I)


def chart_rows(out_dir: Path) -> list[dict]:
    q = json.loads(next(Path(out_dir).glob("*_quadrant.json")).read_text(encoding="utf-8"))
    return sorted((b for b in q["brands"] if b.get("on_chart")), key=lambda b: -float(b.get("overall") or 0))


def company_name(b: dict) -> str:
    """The name the review files and the pool use (no owner label)."""
    return str(b.get("company_key") or _LABEL.sub("", str(b.get("company") or ""))).strip()


def applied_replacements(pipe_dir: Path) -> set[str]:
    """Texts a correction wrote (this step's or the analyst's): they are not
    re-checked, or every applied fix would be asked about again."""
    out: set[str] = set()
    for f in (FACTCHECK_FILE, "analyst_review.json"):
        for c in _read(Path(pipe_dir) / f).get("corrections") or []:
            if c.get("replace"):
                out.add(str(c["replace"]))
    return out


def key(name: str) -> str:
    """Findings are matched on the plain company name: the report's name
    gains an owner label ("X (acquired by Y)") after a check."""
    return norm_name(_LABEL.sub("", str(name or "")))


def specific_claims(b: dict, skip: set[str] | None = None) -> list[dict]:
    out = []
    for ax in ("x", "y"):
        for pn, v in (((b.get("score_detail") or {}).get(ax) or {}).get("parameters") or {}).items():
            for e in v.get("evidence") or []:
                c = str(e.get("claim") or "")
                if c and c != "Not available" and _SPECIFIC.search(c) and c not in (skip or set()):
                    out.append({"parameter": pn, "claim": c})
    return out


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return {}


def merged_findings(work: Path) -> dict:
    merged: dict = {}
    for f in sorted(Path(work).glob("findings*.json")):
        for name, rec in _read(f).items():
            if not isinstance(rec, dict):
                continue
            name = key(name)
            cur = merged.get(name)
            if (cur is None or len(rec.get("claims") or []) > len(cur.get("claims") or [])
                    or (rec.get("status") and not cur.get("status"))):
                merged[name] = rec
    return merged


def was_checked(claim: str, checked: set[str] | list[str]) -> bool:
    """Checked already, or a corrected copy of a checked sentence (a review
    fix changes one detail; asking about it again would undo nothing new)."""
    if claim in checked:
        return True
    for c in checked:
        m = difflib.SequenceMatcher(None, claim, c)
        if m.real_quick_ratio() >= 0.8 and m.quick_ratio() >= 0.8 and m.ratio() >= 0.8:
            return True
    return False


def finished(b: dict, rec: dict | None, skip: set[str] | None = None) -> bool:
    if not rec or not rec.get("status"):
        return False
    checked = {c["claim"] for c in rec.get("claims") or [] if c.get("verdict")}
    return all(was_checked(c["claim"], checked) for c in specific_claims(b, skip))


def missing(out_dir: Path) -> list[str]:
    """Chart companies whose fact-check is not complete (VERIFY uses this)."""
    out_dir = Path(out_dir)
    pipe = out_dir / "_pipeline"
    findings = merged_findings(pipe / FACTCHECK_DIR)
    skip = applied_replacements(pipe)
    return [b["company"] for b in chart_rows(out_dir) if not finished(b, findings.get(key(b["company"])), skip)]


def _house_style(text: str) -> str:
    import sys

    from vendor_intel.pipeline.company_facts import clean_artifacts

    scripts = str(Path(__file__).resolve().parents[3] / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from primary_research_wording import to_primary

    return to_primary(clean_artifacts(text)).strip()


def _country(hq: str) -> str:
    c = str(hq or "").split(",")[-1].strip().lower().rstrip(".")
    # AI Mode sometimes copies the template word back ("Jundiaí, Country"); a
    # placeholder is no country at all, so it can never "differ" and replace a
    # real HQ (four Brazil RO companies showed "City, Country").
    if c in {"country", "unknown", "n/a", "na", "none", "not disclosed", ""}:
        return ""
    return _COUNTRY_ALIASES.get(c, c)


def _claim_decision(name: str, c: dict, others: list[dict], bad: re.Pattern[str]) -> dict | None:
    claim, fixed = str(c.get("claim") or ""), str(c.get("corrected") or "").strip()
    src, note = str(c.get("source") or ""), str(c.get("note") or "")
    if c.get("verdict") != "incorrect" or not src.strip() or bad.search(src) or bad.search(fixed):
        return None
    if _OTHER_COMPANY.search(note) or _OTHER_COMPANY.search(src):
        return {"company": name, "find": claim, "replace": "",
                "reason": f"Supporting point belongs to another company: {note[:200]}", "source": f"{SOURCE}: {src[:200]}"}
    if fixed:
        # The sentence AI Mode wrote enters the report after step 7's wording
        # pass, so it gets the same house style and citation clean-up here.
        fixed = _house_style(fixed)
    if not fixed or fixed == claim:
        return None
    if difflib.SequenceMatcher(None, claim, fixed).ratio() < 0.75:
        return None                       # a rewrite, not a fix of one detail
    removed = set(_NUM.findall(claim)) - set(_NUM.findall(fixed))
    for o in others:
        if o is c:
            continue
        text = o.get("claim", "") if o.get("verdict") == "correct" else o.get("corrected", "")
        if any(n in str(text or "") for n in removed):
            return None                   # another check of this company backs the old figure
    return {"company": name, "find": claim, "replace": fixed,
            "reason": f"Fact-check: {note[:200]}".rstrip(": "), "source": f"{SOURCE}: {src[:200]}"}


def build_review(out_dir: Path) -> dict[str, list[dict]]:
    """The automatic decisions from the saved findings (no queries)."""
    from vendor_intel.pipeline.company_facts import owner_entry

    out_dir = Path(out_dir)
    pipe = out_dir / "_pipeline"
    findings = merged_findings(pipe / FACTCHECK_DIR)
    bad = _bad_source_rx()
    keys = ("exclude", "scope", "ownership", "hq", "corrections")
    review: dict[str, list[dict]] = {k: [] for k in keys}
    rows = chart_rows(out_dir)
    on_chart = {norm_name(company_name(b)) for b in rows}
    # A decision stays once made: the company it moved off the chart is no
    # longer checked, and dropping its entry would put it straight back.
    prev = _read(pipe / FACTCHECK_FILE)
    for k in keys:
        review[k] = [r for r in prev.get(k) or [] if norm_name(r.get("company") or "") not in on_chart]
    # Owners already labelled by step 3c or the analyst are not re-labelled.
    labelled = {norm_name(r.get("company") or "")
                for f in ("auto_review.json", "analyst_review.json")
                for r in _read(pipe / f).get("ownership") or []}
    for b in rows:
        rec = findings.get(key(b["company"])) or {}
        s = rec.get("status") or {}
        name = company_name(b)
        evidence = str(s.get("evidence") or "")
        op, event = str(s.get("operating") or "").lower(), str(s.get("event") or "").strip()
        if op in _GONE and event:
            review["exclude"].append({"company": name, "reason": f"{op}: {event}", "source": SOURCE})
        scope = str(s.get("scope") or "").lower()
        if scope in ("adjacent", "out"):
            review["scope"].append({"company": name, "scope": scope,
                                    "reason": str(s.get("scope_reason") or "")[:300], "source": SOURCE})
        owner = str(s.get("owner") or "").strip()
        if owner and norm_name(name) not in labelled:
            entry = owner_entry(name, {"acquired": True, "acquirer": owner, "year": s.get("owner_since"),
                                       "today": "subsidiary", "note": evidence})
            if entry and re.search(r"(19|20)\d{2}", str(s.get("owner_since") or "")):
                review["ownership"].append({k: entry[k] for k in ("company", "owner", "year", "reason")}
                                           | {"source": SOURCE})
        # Against the HQ the report showed when checked: once corrected, the
        # entry must stay, not disappear because the report now agrees.
        hq, listed = str(s.get("hq") or "").strip(), str(rec.get("listed_hq") or b.get("hq_location") or "")
        if hq and "," in hq and listed and _country(hq) and _country(hq) != _country(listed):
            review["hq"].append({"company": name, "headquarters": hq, "source": f"{SOURCE}: {evidence[:200]}"})
        claims = rec.get("claims") or []
        for c in claims:
            d = _claim_decision(name, c, claims, bad)
            if d:
                review["corrections"].append(d)
    return review


def write_review(pipe_dir: Path, review: dict) -> bool:
    """Save the decisions; True when they differ from the saved ones."""
    path = Path(pipe_dir) / FACTCHECK_FILE
    old = _read(path)
    if old == review:
        return False
    write_json_atomic(path, review, indent=2)
    return True
