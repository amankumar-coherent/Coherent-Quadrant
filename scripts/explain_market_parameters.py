#!/usr/bin/env python3
"""LLM-write definitions for each market's 10 scoring parameters and rebuild HTML.

Does not re-score companies — only explains the parameters already used.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vendor_intel.quadrant.axis_define import explain_market_parameters
from vendor_intel.quadrant.html_report import write_quadrant_html_report

OUT = ROOT / "output" / "chatgpt_expand"

MARKETS = [
    ("global_flexible_packaging_market_global", "Global Flexible Packaging Market"),
    ("global_wearable_medical_devices_market_global", "Global Wearable Medical Devices Market"),
    ("global_semiconductor_market_global", "Global Semiconductor Market"),
    ("global_liquefied_natural_gas_market_global", "Global Liquefied Natural Gas Market"),
]


def main() -> int:
    from vendor_intel.placeholders.load_keys import apply_env_overrides

    apply_env_overrides()
    only = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()
    for slug, query in MARKETS:
        if only and only not in slug and only not in query.lower():
            continue
        folder = OUT / slug
        jp = folder / f"{slug}_quadrant.json"
        if not jp.exists():
            print(f"skip {slug}: no quadrant JSON")
            continue
        payload = json.loads(jp.read_text(encoding="utf-8"))
        crit = payload.setdefault("criteria", {})
        labels = crit.get("axis_labels") or {}
        x_name = str(labels.get("x") or "X")
        y_name = str(labels.get("y") or "Y")
        x_feats = list(crit.get("x_axis") or [])
        y_feats = list(crit.get("y_axis") or [])
        if not x_feats and not y_feats:
            print(f"skip {slug}: no parameters")
            continue

        print(f"=== {query} ===", flush=True)
        print(f"  explaining {len(x_feats)} X + {len(y_feats)} Y parameters…", flush=True)
        defs = explain_market_parameters(
            query,
            x_feats,
            y_feats,
            axis_x=x_name,
            axis_y=y_name,
            geography=str(payload.get("geography") or "global"),
        )
        crit["parameter_definitions"] = defs
        payload["criteria"] = crit

        # Also stash on xy audit if present
        audit_path = folder / "chatgpt_xy_scores_batch_all.json"
        if audit_path.exists():
            try:
                audit = json.loads(audit_path.read_text(encoding="utf-8"))
                audit["parameter_definitions"] = defs
                audit_path.write_text(
                    json.dumps(audit, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            except Exception as exc:
                print(f"  audit update skipped: {exc}", flush=True)

        jp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        hp = folder / f"{slug}_report.html"
        write_quadrant_html_report(payload, hp, open_browser=False)
        print(f"  X defs: {len(defs.get('x') or {})}", flush=True)
        print(f"  Y defs: {len(defs.get('y') or {})}", flush=True)
        # show one sample
        sample_feat = x_feats[0] if x_feats else ""
        if sample_feat:
            print(f"  sample: {sample_feat}", flush=True)
            print(f"    → {(defs.get('x') or {}).get(sample_feat, '')[:160]}", flush=True)
        print(f"  html → {hp}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
