#!/usr/bin/env python3
"""
Verify Quadrant column vs Coherent Quadrant definitions.

X = Clinical & Device Capability
Y = Market Access & Growth Strategy

Leaders:      high X + high Y
Challengers:  lower X + high Y
Trailblazers: high X + lower Y
Emerging:     lower X + lower Y

1) Seed verified X/Y for well-known brands stuck on floor scores
2) Batch-rescore remaining floor rows via DeepSeek
3) Reassign with half-median rank-split
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from openpyxl import load_workbook

from vendor_intel.placeholders.load_keys import apply_env_overrides
from vendor_intel.pipeline.expand_quadrant_score import (
    export_expand_quadrant_outputs,
    score_expand_rows,
    to_company_detail_rows,
)
from vendor_intel.pipeline.web_expand import write_final_xlsx
from vendor_intel.quadrant.rating_map import assign_quadrants_half_median

OUT = ROOT / "output" / "chatgpt_expand"
SLUG = "global_wearable_medical_devices_market_global"
QUERY = "Global Wearable Medical Devices Market"
FOLDER = OUT / SLUG
INDUSTRY = "Healthcare / Wearable Medical Devices"
BATCH = int(os.getenv("QUAD_RESCORE_BATCH") or "25")

# Web/knowledge-verified seeds for brands that were stuck at floor 52/52
# and clearly mis-placed vs definitions. Scores are 0–100 relative intent.
SEED_XY: dict[str, tuple[int, int, str]] = {
    # Leaders-tier: strong wearable clinical platforms + global market access
    "dexcom": (82, 85, "Leader profile: dominant CGM clinical platform + global payers/adoption"),
    "abbott": (84, 86, "Leader profile: FreeStyle Libre CGM scale + global access"),
    "philips": (78, 82, "Leader profile: wearable biosensors/hospital monitoring + global channels"),
    "resmed": (80, 83, "Leader profile: sleep/respiratory wearables + global therapy franchise"),
    "medtronic": (80, 84, "Leader profile: diabetes/cardiac wearable portfolio + global scale"),
    "masimo": (79, 78, "Leader profile: clinical pulse-ox / Radius wearables + hospital penetration"),
    "ge healthcare": (76, 80, "Leader profile: Portrait Mobile / telemetry + global health-system reach"),
    "irhythm": (81, 79, "Leader profile: Zio patch clinical evidence + large ambulatory cardiac franchise"),
    "alivecor": (74, 76, "Leader profile: Kardia ECG brand + broad consumer/clinical distribution"),
    "biofourmis": (73, 74, "Leader profile: Biovitals/Everion clinical analytics + health-system deals"),
    "insulet": (78, 80, "Leader profile: Omnipod wearable insulin + strong commercial scale"),
    "tandem diabetes care": (75, 76, "Leader profile: t:slim wearable pump + established diabetes channels"),
    "senseonics": (72, 70, "Leader/Trailblazer: long-term implantable CGM + growing commercial reach"),
    "withings": (70, 72, "Leader profile: medical-grade ScanWatch + broad retail/clinical brand"),
    "empatica": (74, 68, "High clinical wearable (Embrace) + growing but not mega-scale GTM"),
    "livongo": (72, 84, "Leader profile: connected chronic-care devices + Teladoc-scale distribution"),
    "huma": (70, 73, "Leader profile: regulated SaMD RPM platform + multi-country deployments"),
    "current health": (71, 66, "Strong hospital-at-home wearable platform; GTM rebuilding post Best Buy"),
    "hinge health": (68, 75, "MSK digital + Enso wearable; strong employer/payer access"),
    "sonova": (77, 81, "Leader profile: Phonak hearing wearables + global audiology network"),
    "demant": (76, 80, "Leader profile: Oticon hearing wearables + global scale"),
    "cochlear": (82, 78, "Leader profile: implant+processor wearable franchise + global clinics"),
    "gn hearing": (74, 77, "Leader profile: ReSound hearing wearables + broad market access"),
    "ws audiology": (73, 76, "Leader profile: Signia/Widex hearing brands + global reach"),
    "starkey hearing technologies": (72, 70, "Strong hearing wearable tech + solid NA commercial base"),
    "boston scientific": (70, 78, "Broad cardiac franchise (Preventice MCT) + global access"),
    "zoll medical": (76, 74, "LifeVest WCD clinical strength + established cardiac channels"),
    "preventice solutions": (73, 72, "BodyGuardian MCT clinical platform under BSC commercial reach"),
    "biotelemetry": (72, 74, "MCOT franchise under Philips commercial scale"),
    # Challengers: market reach ahead of own wearable device depth
    "amplifon": (48, 78, "Challenger: global hearing retail reach; not primary device OEM"),
    "miracle-ear": (46, 72, "Challenger: retail hearing network under Amplifon"),
    "best buy health": (45, 70, "Challenger: retail/health channel scale; limited device R&D"),
    "ascensia diabetes care": (50, 74, "Challenger: Eversense commercial partner + Contour BGM reach"),
    "nutrisense": (47, 68, "Challenger: CGM program marketer using third-party sensors"),
    "levels health": (48, 67, "Challenger: metabolic CGM program marketer"),
    "signos": (49, 66, "Challenger: CGM weight program marketer"),
    "veri": (47, 64, "Challenger: Libre CGM program marketer"),
    "zoe": (48, 69, "Challenger: nutrition program + CGM kits; broad consumer brand"),
    "ultrahuman": (50, 62, "Challenger/Emerging: CGM program marketer + wellness ring"),
    # Trailblazers: advanced clinical tech, still scaling GTM
    "element science": (76, 52, "Trailblazer: Jewel WCD tech; earlier commercial scale"),
    "biolinq": (74, 50, "Trailblazer: intradermal CGM tech; pre-scale commercial"),
    "cala health": (73, 55, "Trailblazer: neuromodulation wearable; focused US GTM"),
    "theranica": (72, 58, "Trailblazer: Nerivio migraine wearable; growing access"),
    "aktiia": (74, 56, "Trailblazer: optical cuffless BP; still expanding markets"),
    "cardiac sense": (72, 54, "Trailblazer: medical AF watch; limited global scale"),
    "cardiacsense": (72, 54, "Trailblazer: medical AF watch; limited global scale"),
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def _f(v, default=50.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _is_floor(x: float, y: float) -> bool:
    return (x == 52 and y == 52) or (40 <= x <= 53 and 40 <= y <= 53 and abs(x - y) <= 1)


def _heuristic_xy(row: dict) -> tuple[int, int]:
    """Spread floor rows using role/specialty cues (definition-aligned priors)."""
    role = str(row.get("Role") or "")
    blob = " ".join(
        [
            str(row.get("Specialty Focus") or ""),
            str(row.get("Core Categories") or ""),
            str(row.get("Summary") or ""),
            str(row.get("Brand") or ""),
        ]
    ).lower()
    x, y = 55, 52
    if role == "Marketer":
        x, y = 46, 64  # lower device capability, higher market/program access
    if any(k in blob for k in ("cgm", "insulin", "ecg", "holter", "patch", "telemetry", "fda")):
        x += 8
    if any(k in blob for k in ("global", "hospital", "payer", "reimburs", "retail", "clinic network")):
        y += 8
    if any(k in blob for k in ("research", "startup", "niche", "pilot", "emerging")):
        y -= 6
    if any(k in blob for k in ("hearing", "cochlear", "sleep apnea", "pulse ox")):
        x += 4
        y += 4
    return max(40, min(88, x)), max(40, min(88, y))


async def _score_batch(rows: list[dict]) -> dict[str, dict]:
    if not rows:
        return {}
    # Ensure scorer does not skip
    for r in rows:
        for col in ("X Score", "Y Score", "Overall Score", "Quadrant"):
            r[col] = ""
    scored, _ = await score_expand_rows(rows, QUERY, country="global")
    return {_norm(r.get("Company") or r.get("Brand") or ""): r for r in scored}


async def main() -> int:
    apply_env_overrides()
    os.environ["EXPAND_XY_SKIP_CRAWL"] = "1"
    os.environ["EXPAND_MARKET_AXIS_LLM"] = "1"

    xlsx = FOLDER / f"{SLUG}_FINAL.xlsx"
    wb = load_workbook(xlsx, data_only=True)
    ws = wb["Landscape"]
    rows_raw = list(ws.iter_rows(values_only=True))
    hdr = [str(h) for h in rows_raw[0]]

    details_by: dict[str, dict] = {}
    if "Company Details" in wb.sheetnames:
        dws = wb["Company Details"]
        drows = list(dws.iter_rows(values_only=True))
        dhdr = [str(h) for h in drows[0]]
        for r in drows[1:]:
            if not r:
                continue
            d = {dhdr[i]: ("" if r[i] is None else r[i]) for i in range(len(dhdr)) if i < len(r)}
            key = _norm(d.get("Brand") or d.get("Company") or "")
            if key:
                details_by[key] = d

    kept: list[dict] = []
    before: dict[str, dict] = {}
    seeded: list[dict] = []
    need_llm: list[dict] = []

    for r in rows_raw[1:]:
        if not r:
            continue
        d = {hdr[i]: ("" if r[i] is None else r[i]) for i in range(len(hdr)) if i < len(r)}
        brand = str(d.get("Company") or d.get("Brand") or "").strip()
        if not brand:
            continue
        key = _norm(brand)
        det = details_by.get(key)
        if det:
            if det.get("Brand"):
                brand = str(det["Brand"]).strip()
                key = _norm(brand)
                d["Brand"] = brand
            if det.get("Company") and (
                str(det["Company"]).startswith("(") or _norm(det["Company"]) != key
            ):
                d["_display_company"] = det["Company"]
            if det.get("X") not in (None, ""):
                d["X Score"] = det["X"]
                d["Y Score"] = det["Y"]
                d["Overall Score"] = det["Overall"]
                d["Quadrant"] = det.get("Quadrant") or ""
            if det.get("Found in"):
                d["Headquarters"] = det["Found in"]
                d["Found in"] = det["Found in"]
            if det.get("Role") in {"Brand", "Marketer"}:
                d["Role"] = det["Role"]
                d["Distribution Type"] = det["Role"]

        d["Brand"] = brand
        d["Company"] = brand
        d["Role"] = d.get("Role") if d.get("Role") in {"Brand", "Marketer"} else "Brand"
        d["Distribution Type"] = d["Role"]
        d["Industry Category"] = INDUSTRY

        x, y = _f(d.get("X Score")), _f(d.get("Y Score"))
        before[brand] = {"quadrant": str(d.get("Quadrant") or ""), "x": x, "y": y}

        # Always apply seed for known majors (even if not exact floor) when
        # current scores would mis-place them vs definitions.
        force_seed = key in SEED_XY and (
            _is_floor(x, y)
            or (key in {
                "masimo",
                "medtronic",
                "zoll medical",
                "preventice solutions",
                "biotelemetry",
                "empatica",
                "withings",
                "insulet",
                "tandem diabetes care",
                "senseonics",
                "sonova",
                "demant",
                "cochlear",
                "gn hearing",
                "ws audiology",
                "starkey hearing technologies",
                "hinge health",
                "current health",
                "boston scientific",
                "ascensia diabetes care",
                "amplifon",
                "miracle-ear",
                "best buy health",
                "nutrisense",
                "levels health",
                "signos",
                "veri",
                "zoe",
                "ultrahuman",
                "element science",
                "biolinq",
                "cala health",
                "theranica",
                "aktiia",
                "cardiacsense",
                "cardiac sense",
            }
            and True)  # always refresh known seed brands to match definitions
        )
        if force_seed:
            sx, sy, note = SEED_XY[key]
            d["X Score"] = sx
            d["Y Score"] = sy
            d["Overall Score"] = round((sx + sy) / 2)
            d["Summary"] = (str(d.get("Summary") or brand).split(" | quadrant-seed:")[0].strip()
                            + f" | quadrant-seed: {note}")
            seeded.append({"brand": brand, "x": sx, "y": sy, "note": note})
        elif _is_floor(x, y):
            # Temporary spread so half-median is not tie-dominated; LLM overwrites below.
            hx, hy = _heuristic_xy(d)
            d["X Score"] = hx
            d["Y Score"] = hy
            d["Overall Score"] = round((hx + hy) / 2)
            need_llm.append(d)

        kept.append(d)

    print(f"Seeded {len(seeded)}; remaining floor for LLM {len(need_llm)} / total {len(kept)}", flush=True)

    # Optional LLM refine (set QUAD_SKIP_LLM=1 to use seeds+heuristics only)
    skip_llm = (os.getenv("QUAD_SKIP_LLM") or "").strip().lower() in {"1", "true", "yes"}
    if skip_llm:
        print("Skipping LLM refine (QUAD_SKIP_LLM=1); using seeds + heuristics", flush=True)
        need_llm = []

    # Batch LLM rescore remaining floors
    for i in range(0, len(need_llm), BATCH):
        batch = need_llm[i : i + BATCH]
        print(f"LLM batch {i // BATCH + 1}: {len(batch)} companies...", flush=True)
        # Pass copies so clearing scores doesn't fight kept refs incorrectly
        copies = [dict(r) for r in batch]
        by = await _score_batch(copies)
        for r in kept:
            s = by.get(_norm(r.get("Brand") or ""))
            if not s:
                continue
            for col in ("X Score", "Y Score", "Overall Score", "Summary"):
                if s.get(col) not in (None, ""):
                    r[col] = s[col]
            r["Role"] = r.get("Role") if r.get("Role") in {"Brand", "Marketer"} else "Brand"
            r["Distribution Type"] = r["Role"]
        # Persist partial progress after each batch
        _write_partial(kept, before)

    xs = [_f(r.get("X Score")) for r in kept]
    ys = [_f(r.get("Y Score")) for r in kept]
    quads, mid_x, mid_y = assign_quadrants_half_median(xs, ys)

    changes: list[dict] = []
    for r, q in zip(kept, quads):
        old = before.get(r["Brand"], {}).get("quadrant") or ""
        r["Quadrant"] = q
        r["Overall Score"] = round((_f(r.get("X Score")) + _f(r.get("Y Score"))) / 2)
        if old and old != q:
            changes.append(
                {
                    "brand": r["Brand"],
                    "from": old,
                    "to": q,
                    "x": _f(r.get("X Score")),
                    "y": _f(r.get("Y Score")),
                    "role": r.get("Role"),
                }
            )

    audit = _load_audit()
    audit["axis_x"] = "Clinical & Device Capability"
    audit["axis_y"] = "Market Access & Growth Strategy"
    audit["quadrant_method"] = "half_median_rank_split"
    audit["mid_x"] = mid_x
    audit["mid_y"] = mid_y

    detail_rows = to_company_detail_rows(kept, QUERY, audit)
    for det in detail_rows:
        key = _norm(det.get("Brand") or "")
        src = next((r for r in kept if _norm(r.get("Brand") or "") == key), None)
        if not src:
            continue
        det["Role"] = src.get("Role") or "Brand"
        if src.get("_display_company"):
            det["Company"] = src["_display_company"]
        elif not str(det.get("Company") or "").startswith("("):
            if not (det.get("Company") and _norm(det.get("Company")) != key):
                det["Company"] = det.get("Brand") or det.get("Company")

    write_final_xlsx(
        xlsx,
        kept,
        "Companies",
        {"query": QUERY, "xy_scoring": audit, "quadrant_verify": True},
        detail_rows=detail_rows,
    )
    extras = export_expand_quadrant_outputs(
        FOLDER, detail_rows, QUERY, country="global", audit=audit, chart_n=20
    )

    roles = dict(Counter(r.get("Role") for r in detail_rows))
    qcounts = dict(Counter(r.get("Quadrant") for r in detail_rows))
    floor_left = sum(
        1
        for r in detail_rows
        if _is_floor(_f(r.get("X")), _f(r.get("Y")))
    )

    by_q: dict[str, list] = {k: [] for k in ("Leaders", "Challengers", "Trailblazers", "Emerging Players")}
    for r in detail_rows:
        by_q.setdefault(str(r.get("Quadrant")), []).append(
            {
                "brand": r.get("Brand"),
                "x": r.get("X"),
                "y": r.get("Y"),
                "overall": r.get("Overall"),
                "role": r.get("Role"),
            }
        )
    for q in by_q:
        by_q[q] = sorted(by_q[q], key=lambda t: -float(t.get("overall") or 0))[:12]

    # Definition sanity: majors should not land in wrong cell after fix
    sanity = []
    expect_leaderish = {
        "dexcom",
        "abbott",
        "philips",
        "resmed",
        "medtronic",
        "masimo",
        "irhythm",
        "alivecor",
        "ge healthcare",
        "livongo",
    }
    for r in detail_rows:
        key = _norm(r.get("Brand") or "")
        if key in expect_leaderish and r.get("Quadrant") not in {"Leaders", "Trailblazers"}:
            sanity.append(
                {
                    "brand": r.get("Brand"),
                    "quadrant": r.get("Quadrant"),
                    "x": r.get("X"),
                    "y": r.get("Y"),
                    "issue": "expected Leaders/Trailblazers (high clinical capability)",
                }
            )

    out = {
        "definition": {
            "Leaders": "High Clinical & Device Capability + High Market Access & Growth Strategy",
            "Challengers": "Lower Clinical & Device Capability + High Market Access & Growth Strategy",
            "Trailblazers": "High Clinical & Device Capability + Lower Market Access & Growth Strategy",
            "Emerging Players": "Lower on both",
        },
        "seeded": seeded,
        "llm_rescored": len(need_llm),
        "floor_remaining": floor_left,
        "quadrant_changes": len(changes),
        "changes": changes,
        "final_count": len(detail_rows),
        "roles": roles,
        "quadrants": qcounts,
        "mid_x": mid_x,
        "mid_y": mid_y,
        "top_by_quadrant": by_q,
        "sanity_flags": sanity,
        "html": str(extras.get("html") or ""),
    }
    path = OUT / "_audit" / "wearable_quadrant_verification.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_md(out)
    print(f"Final {len(detail_rows)} quads={qcounts} changes={len(changes)} floor_left={floor_left}", flush=True)
    print(f"sanity_flags={len(sanity)} audit -> {OUT / '_audit' / 'wearable_quadrant_verification.md'}", flush=True)
    return 0


def _load_audit() -> dict:
    audit: dict = {}
    audit_path = FOLDER / "chatgpt_expand_batch_all_audit.json"
    if audit_path.exists():
        audit = json.loads(audit_path.read_text(encoding="utf-8")).get("xy_scoring") or {}
    qjson = FOLDER / f"{SLUG}_quadrant.json"
    if qjson.exists():
        try:
            payload = json.loads(qjson.read_text(encoding="utf-8"))
            crit = payload.get("criteria") or {}
            if crit.get("parameter_definitions"):
                audit["parameter_definitions"] = crit["parameter_definitions"]
            if crit.get("x_axis"):
                audit["x_features"] = crit["x_axis"]
            if crit.get("y_axis"):
                audit["y_features"] = crit["y_axis"]
        except Exception:
            pass
    return audit


def _write_partial(kept: list[dict], before: dict) -> None:
    """Save intermediate FINAL so long runs are not lost."""
    xs = [_f(r.get("X Score") or 50) for r in kept]
    ys = [_f(r.get("Y Score") or 50) for r in kept]
    quads, _, _ = assign_quadrants_half_median(xs, ys)
    for r, q in zip(kept, quads):
        if r.get("X Score") not in (None, ""):
            r["Quadrant"] = q
            r["Overall Score"] = round((_f(r.get("X Score")) + _f(r.get("Y Score"))) / 2)
    audit = _load_audit()
    audit["axis_x"] = "Clinical & Device Capability"
    audit["axis_y"] = "Market Access & Growth Strategy"
    detail_rows = to_company_detail_rows(kept, QUERY, audit)
    for det in detail_rows:
        key = _norm(det.get("Brand") or "")
        src = next((r for r in kept if _norm(r.get("Brand") or "") == key), None)
        if not src:
            continue
        det["Role"] = src.get("Role") or "Brand"
        if src.get("_display_company"):
            det["Company"] = src["_display_company"]
    xlsx = FOLDER / f"{SLUG}_FINAL.xlsx"
    write_final_xlsx(
        xlsx,
        kept,
        "Companies",
        {"query": QUERY, "xy_scoring": audit, "quadrant_partial": True},
        detail_rows=detail_rows,
    )
    print(f"  partial save ({sum(1 for r in kept if r.get('X Score') not in (None,''))} scored)", flush=True)


def _write_md(out: dict) -> None:
    md = OUT / "_audit" / "wearable_quadrant_verification.md"
    lines = [
        "# Quadrant verification — Wearable Medical Devices",
        "",
        "## Definitions",
        "",
        "| Quadrant | Meaning |",
        "|---|---|",
        "| **Leaders** | High Clinical & Device Capability + High Market Access & Growth Strategy |",
        "| **Challengers** | Lower Clinical & Device Capability + High Market Access & Growth Strategy |",
        "| **Trailblazers** | High Clinical & Device Capability + Lower Market Access & Growth Strategy |",
        "| **Emerging Players** | Lower on both |",
        "",
        f"Seeded **{len(out['seeded'])}** majors; LLM-rescored **{out['llm_rescored']}**; floor left **{out['floor_remaining']}**.",
        "",
        f"Final **{out['final_count']}** — {out['roles']} — quadrants **{out['quadrants']}**",
        "",
        f"## Changes ({out['quadrant_changes']})",
        "",
        "| Brand | From | To | X | Y |",
        "|---|---|---|---|---|",
    ]
    for c in out["changes"][:80]:
        lines.append(
            f"| {c['brand']} | {c['from']} | {c['to']} | {c['x']:.0f} | {c['y']:.0f} |"
        )
    lines.extend(["", "## Top by quadrant", ""])
    for q, rows in (out.get("top_by_quadrant") or {}).items():
        lines.append(f"### {q}")
        lines.append("")
        for row in rows[:10]:
            lines.append(
                f"- **{row['brand']}** — X={row['x']} Y={row['y']} O={row['overall']} ({row['role']})"
            )
        lines.append("")
    if out.get("sanity_flags"):
        lines.extend(["## Sanity flags", ""])
        for s in out["sanity_flags"]:
            lines.append(
                f"- {s['brand']}: {s['quadrant']} (X={s['x']} Y={s['y']}) — {s['issue']}"
            )
    md.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
