"""Update an existing report with fresh checks, without re-scoring.

run_quadrant_pipeline.py --update-report <base quadrant.json> runs only the
checks (3b operating status, 3c ownership + identity) on the report's own
company list, then rewrites that report:

- companies left out by the checks (closed, absorbed by an acquirer, not shown
  to exist, or excluded by the analyst / fact-check review) are removed; a
  removed chart company is not replaced (no new search, no re-scoring);
- a company bought but still trading gets "(acquired by Owner)" for a deal
  under 3 years old, else "(subsidiary of Owner)" -- the same labels as step 3c;
- house wording on every text (the primary-research gap sentence, research-team
  voice, citation clean-up) and the "Not available" rule;
- scores, quadrants, parameters and evidence are otherwise kept as they were.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

from vendor_intel.pipeline.quadrant_pipeline import norm_name, write_json_atomic

NOT_AVAILABLE = "Not available"
_LABEL = re.compile(r"\s*\((?:acquired by|subsidiary of)\s[^)]*\)\s*$", re.I)


def _house_style():
    scripts = str(Path(__file__).resolve().parents[3] / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from primary_research_wording import to_primary

    from vendor_intel.pipeline.company_facts import clean_artifacts

    return lambda t: to_primary(clean_artifacts(t))


QUADRANTS = ("Leaders", "Challengers", "Trailblazers", "Emerging Players")


def _plain(b: dict) -> str:
    return str(b.get("company_key") or _LABEL.sub("", str(b.get("company") or ""))).strip()


def refill_plan(payload: dict, per_quadrant: int = 5, spare: int = 1) -> dict[str, list[str]]:
    """Long-tail companies of the report to bring onto a chart that lost
    companies: per quadrant short of ``per_quadrant``, the strongest of that
    quadrant by overall score (plus ``spare`` in case one cannot be scored).
    Only companies already in the report -- never a new search."""
    brands = payload.get("brands") or []
    plan: dict[str, list[str]] = {}
    for q in QUADRANTS:
        have = sum(1 for b in brands if b.get("on_chart") and b.get("quadrant") == q)
        need = per_quadrant - have
        if need <= 0:
            continue
        tail = sorted((b for b in brands if not b.get("on_chart") and b.get("quadrant") == q),
                      key=lambda b: -float(b.get("overall") or 0))
        plan[q] = [_plain(b) for b in tail[: need + spare]]
    return plan


def axes_spec(payload: dict) -> dict:
    """The report's own 5+5 parameters and definitions, as a --fixed-axes spec,
    so refills are scored on exactly what the chart companies were."""
    c = payload.get("criteria") or {}
    return {"market": payload.get("market"), "axis_x": "Product Strength", "axis_y": "Business Strength",
            "x": list(c.get("x_axis") or []), "y": list(c.get("y_axis") or []),
            "parameter_definitions": c.get("parameter_definitions") or {"x": {}, "y": {}}}


def apply_refills(payload: dict, plan: dict[str, list[str]], evidence: dict[str, dict],
                  per_quadrant: int = 5) -> list[str]:
    """Put scored refills on the chart: only companies with all 10 parameters
    scored; X / Y = mean of their parameter scores (the chart's rule); the
    quadrant stays the report's own; old placeholder plot positions are
    cleared so the viewer places them from their scores."""
    style = _house_style()
    spec = axes_spec(payload)
    by = {norm_name(_plain(b)): b for b in payload.get("brands") or []}
    ev = {norm_name(k): v for k, v in evidence.items()}
    added: list[str] = []
    for q, names in plan.items():
        room = per_quadrant - sum(1 for b in payload["brands"] if b.get("on_chart") and b.get("quadrant") == q)
        for n in names:
            if room <= 0:
                break
            b, rec = by.get(norm_name(n)), ev.get(norm_name(n)) or {}
            params = {ax: ((rec.get(ax) or {}).get("parameters") or {}) for ax in ("x", "y")}
            if not b or any(not all(p in params[ax] and params[ax][p].get("score") is not None
                                    for p in spec[ax]) for ax in ("x", "y")):
                continue
            detail = {}
            for ax in ("x", "y"):
                ps = {}
                for p in spec[ax]:
                    v = dict(params[ax][p])
                    v["assessed_on"] = style(str(v.get("assessed_on") or "")) if v.get("assessed_on") else ""
                    claims = [style(str(e.get("claim") or "")) for e in v.get("evidence") or [] if isinstance(e, dict)]
                    claims = [c for c in claims if c and c != NOT_AVAILABLE]
                    v["evidence"] = [{"claim": c} for c in claims] or [{"claim": NOT_AVAILABLE}]
                    ps[p] = v
                detail[ax] = {"parameters": ps}
            b["score_detail"] = detail
            b["execution"] = round(sum(float(v["score"]) for v in detail["x"]["parameters"].values()) / len(spec["x"]))
            b["innovation"] = round(sum(float(v["score"]) for v in detail["y"]["parameters"].values()) / len(spec["y"]))
            b["overall"] = round((b["execution"] + b["innovation"]) / 2)
            b["on_chart"] = True
            b.pop("left_pct", None)
            b.pop("top_pct", None)
            added.append(b["company"])
            room -= 1
    return added


def update_report(base_json: Path, out_dir: Path, pipe_dir: Path, removed: Iterable[str],
                  slug: str) -> dict[str, Any]:
    from vendor_intel.pipeline.company_facts import ownership_relation
    from vendor_intel.pipeline.company_status import load_review
    from vendor_intel.quadrant.viewer import write_viewer

    payload = json.loads(Path(base_json).read_text(encoding="utf-8"))
    gone = {norm_name(n) for n in removed}
    # A head office the report stored as a placeholder ("Mumbai, Country") is
    # replaced by the one confirmed for that company in the checkpoint
    # (scripts/fill_missing_hq.py).
    ckpt = Path(out_dir) / "chatgpt_checkpoint_batch_all.json"
    rows = (json.loads(ckpt.read_text(encoding="utf-8")).get("data") or {}).get("verified") or [] \
        if ckpt.exists() else []
    hq_of = {norm_name(str(r.get("name") or r.get("Company") or "")): str(r.get("Headquarters") or "").strip()
             for r in rows}
    owners = {norm_name(r.get("company") or ""): r for r in load_review(pipe_dir)["ownership"]}
    style = _house_style()
    kept, dropped, labelled = [], [], []
    for b in payload.get("brands") or []:
        name = str(b.get("company_key") or _LABEL.sub("", str(b.get("company") or ""))).strip()
        if norm_name(name) in gone:
            dropped.append(name)
            continue
        o = owners.get(norm_name(name))
        owner = str((o or {}).get("owner") or "").strip()
        b["company"] = name
        hq = str(b.get("hq_location") or "").strip()
        if (not hq or hq.lower() == "country" or hq.endswith(", Country")) and hq_of.get(norm_name(name)):
            b["hq_location"] = hq_of[norm_name(name)]
            b["country"] = b["hq_location"].split(",")[-1].strip()
        if owner:
            rel = "acquired by" if ownership_relation(o.get("year")) == "acquired_by" else "subsidiary of"
            b["company"] = f"{name} ({rel} {owner})"
            labelled.append(b["company"])
        for ax in ("x", "y"):
            for v in (((b.get("score_detail") or {}).get(ax) or {}).get("parameters") or {}).values():
                if not isinstance(v, dict):
                    continue
                if v.get("assessed_on"):
                    v["assessed_on"] = style(str(v["assessed_on"]))
                ev = []
                for e in v.get("evidence") or []:
                    claim = str((e or {}).get("claim") or "")
                    if claim and claim != NOT_AVAILABLE:
                        claim = style(claim)
                    if claim:
                        ev.append({**(e or {}), "claim": claim})
                real = [e for e in ev if e["claim"] != NOT_AVAILABLE]
                v["evidence"] = real or [{"claim": NOT_AVAILABLE}]
        kept.append(b)
    payload["brands"] = kept
    out_dir = Path(out_dir)
    write_json_atomic(out_dir / f"{slug}_quadrant.json", payload, indent=2)
    html = write_viewer(payload, out_dir / f"{slug}_report.html")
    stats = {"base_report": str(base_json), "companies_before": len(kept) + len(dropped),
             "companies_after": len(kept), "chart_after": sum(1 for b in kept if b.get("on_chart")),
             "removed": dropped, "labelled": labelled}
    write_json_atomic(Path(pipe_dir) / "report_update.json", stats, indent=1)
    stats["html"] = str(html)
    return stats
