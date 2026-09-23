"""Print a per-caller DeepSeek spend/request breakdown from
output/cost_dashboard/deepseek_calls.jsonl, and (optionally) reconcile it
against DeepSeek's own billing CSV export.

Usage:
    python scripts/deepseek_cost_report.py
    python scripts/deepseek_cost_report.py --reconcile amount-2026-08-01_2026-08-28.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vendor_intel.pipeline.deepseek_tracker import (  # noqa: E402
    load_calls,
    totals_by_caller,
    write_summary_snapshot,
)


def _print_by_caller() -> None:
    by_caller = totals_by_caller()
    if not by_caller:
        print("No calls recorded yet in output/cost_dashboard/deepseek_calls.jsonl")
        return
    rows = sorted(by_caller.items(), key=lambda kv: -kv[1]["estimated_cost_usd"])
    print(f"{'caller':<45} {'requests':>9} {'tokens':>12} {'est_cost_usd':>13}")
    print("-" * 82)
    total_req = total_cost = 0
    for caller, agg in rows:
        tokens = agg["prompt_tokens"] + agg["completion_tokens"]
        print(f"{caller:<45} {agg['requests']:>9} {tokens:>12} {agg['estimated_cost_usd']:>13.4f}")
        total_req += agg["requests"]
        total_cost += agg["estimated_cost_usd"]
    print("-" * 82)
    print(f"{'TOTAL':<45} {total_req:>9} {'':>12} {total_cost:>13.4f}")


def _reconcile(csv_path: Path) -> None:
    calls = load_calls()
    by_day: dict[str, int] = {}
    for row in calls:
        day = row["ts"][:10]
        by_day[day] = by_day.get(day, 0) + 1

    billed: dict[str, int] = {}
    with csv_path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("type") != "request_count":
                continue
            day = row["start_time_iso"][:10]
            billed[day] = billed.get(day, 0) + int(row["amount"])

    print(f"\n{'date':<12} {'billed_requests':>16} {'tracked_requests':>17} {'coverage':>10}")
    print("-" * 58)
    for day in sorted(set(billed) | set(by_day)):
        b = billed.get(day, 0)
        t = by_day.get(day, 0)
        cov = f"{(t / b * 100):.1f}%" if b else "n/a"
        print(f"{day:<12} {b:>16} {t:>17} {cov:>10}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--reconcile", type=Path, default=None, help="Path to DeepSeek amount-*.csv")
    args = ap.parse_args()

    write_summary_snapshot()
    _print_by_caller()
    if args.reconcile:
        _reconcile(args.reconcile)
