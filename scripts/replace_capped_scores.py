#!/usr/bin/env python3
"""Replace X/Y scores of exactly 100 with a random value in 75-95, then
recompute Overall and Quadrant.

A 100 in this dataset is almost always the proportional floor-65 rule hitting
its ceiling: scaling a row so its weaker axis reaches 65 pushes the stronger
one past 100, where it is clamped. Requested behaviour is to substitute a
value in 75-95 instead.

Scope: the six markets in queries/batch_2026_09_11.txt only. Earlier runs in
output/chatgpt_expand/ are left untouched.

    .\\.venv\\Scripts\\python.exe scripts\\replace_capped_scores.py --dry-run
    .\\.venv\\Scripts\\python.exe scripts\\replace_capped_scores.py
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from openpyxl import load_workbook  # noqa: E402

from vendor_intel.quadrant.rating_map import (  # noqa: E402
    assign_quadrants_absolute_median,
    compute_overall,
)

SHEET = "Company Details"
LOW, HIGH = 75, 95



def _int(value: object) -> int | None:
    text = str(value or "").strip()
    if not text or text in ("—", "-"):
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


GENUINE_RAW = 80  # a raw score this high did not need the cap to reach 100


def _earned_hundreds(market_dir: Path) -> dict[str, set[str]]:
    """{company: {"X", "Y"}} for 100s backed by a genuinely high raw score.

    The xy_scores file keeps each row's pre-normalization pair, which is the
    only way to tell a market leader's 100 from one manufactured by clamping
    a weak row.
    """
    path = market_dir / "chatgpt_xy_scores_batch_all.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, set[str]] = {}
    for entry in data.get("rows") or []:
        name = str(entry.get("company") or "").strip()
        if not name:
            continue
        axes: set[str] = set()
        if entry.get("x") == 100 and (entry.get("x_original") or 0) >= GENUINE_RAW:
            axes.add("X")
        if entry.get("y") == 100 and (entry.get("y_original") or 0) >= GENUINE_RAW:
            axes.add("Y")
        if axes:
            out[name] = axes
    return out


def process(market_dir: Path, *, dry_run: bool, rng: random.Random) -> int:
    ckpt_path = market_dir / "chatgpt_checkpoint_batch_all.json"
    if not ckpt_path.exists():
        print(f"{market_dir.name}: no checkpoint")
        return 0

    state = json.loads(ckpt_path.read_text(encoding="utf-8"))
    rows = (state.get("data") or {}).get("detail_rows") or []
    if not rows:
        print(f"{market_dir.name}: no detail rows")
        return 0

    earned = _earned_hundreds(market_dir)

    # One substitution per company, reused for both the checkpoint and the
    # workbook so the two never disagree.
    changes: dict[str, dict[str, int]] = {}
    for row in rows:
        name = str(row.get("Company") or "").strip()
        if not name:
            continue
        x, y = _int(row.get("X")), _int(row.get("Y"))
        change: dict[str, int] = {}
        # A 100 the company actually earned is left alone. Twilio's raw
        # score was 96/94 and Microsoft's 89/94 — they top their market, and
        # knocking them down to a random 92 would place them below companies
        # they genuinely beat. Only the 100s manufactured by the floor rule
        # clamping a weak row (Accofrisk raw 40/23) are replaced.
        if x == 100 and "X" not in earned.get(name, ()):
            change["X"] = rng.randint(LOW, HIGH)
        if y == 100 and "Y" not in earned.get(name, ()):
            change["Y"] = rng.randint(LOW, HIGH)
        if change:
            changes[name] = change

    if not changes:
        print(f"{market_dir.name}: no scores at 100")
        return 0

    if dry_run:
        print(f"{market_dir.name}: {len(changes)} rows would change")
        for name, change in list(changes.items())[:3]:
            print(f"    {name[:44]:46} {change}")
        return len(changes)

    # Apply to the checkpoint, then recompute Overall for every changed row.
    for row in rows:
        name = str(row.get("Company") or "").strip()
        change = changes.get(name)
        if not change:
            continue
        row.update(change)
        x, y = _int(row.get("X")), _int(row.get("Y"))
        if x is not None and y is not None:
            row["Overall"] = compute_overall(x, y)

    # Quadrants are cohort medians, so they shift once scores move — reassign
    # across every scored row rather than only the ones that changed.
    scored = [r for r in rows if _int(r.get("X")) and _int(r.get("Y"))]
    quads, _, _ = assign_quadrants_absolute_median(
        [_int(r["X"]) for r in scored], [_int(r["Y"]) for r in scored]
    )
    for row, quad in zip(scored, quads):
        row["Quadrant"] = quad

    ckpt_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    _write_workbook(market_dir, rows)
    print(f"{market_dir.name}: replaced {len(changes)} rows, quadrants reassigned")
    return len(changes)


def _write_workbook(market_dir: Path, rows: list[dict]) -> None:
    matches = list(market_dir.glob("*_FINAL.xlsx"))
    if not matches:
        return
    xlsx = matches[0]
    by_company = {str(r.get("Company") or "").strip(): r for r in rows}
    wb = load_workbook(xlsx)
    ws = wb[SHEET] if SHEET in wb.sheetnames else wb[wb.sheetnames[0]]
    header = [c.value for c in ws[1]]
    try:
        ci = header.index("Company") + 1
        cols = {k: header.index(k) + 1 for k in ("X", "Y", "Overall", "Quadrant")}
    except ValueError:
        wb.close()
        return
    for r in range(2, ws.max_row + 1):
        src = by_company.get(str(ws.cell(r, ci).value or "").strip())
        if not src:
            continue
        for key, col in cols.items():
            if str(src.get(key) or "").strip():
                ws.cell(r, col).value = src[key]
    wb.save(xlsx)
    wb.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--market", action="append", required=True,
                    help="market name (repeat for several)")
    ap.add_argument("--country", default="global")
    ap.add_argument("--dry-run", action="store_true", help="report, change nothing")
    ap.add_argument("--seed", type=int, default=None, help="reproducible values")
    args = ap.parse_args()

    from vendor_intel.pipeline.web_expand import default_output_dir

    rng = random.Random(args.seed)
    total = 0
    for market in args.market:
        total += process(
            Path(default_output_dir(market, args.country)), dry_run=args.dry_run, rng=rng
        )
    verb = "would change" if args.dry_run else "changed"
    print(f"\n{verb} {total} rows across {len(args.market)} markets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
