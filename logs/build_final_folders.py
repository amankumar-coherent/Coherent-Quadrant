"""Fill Desktop\\Final Drone Quadrant and Desktop\\Final Fire Quadrant with the checked markets.

Per market: <slug>_report.html, <slug>_quadrant.json and <slug>_companies.xlsx.
A market is included only when it is checked and finished:
  - checked here: output/chatgpt_expand/<slug>_india with ownership + scope + status answers
    and a finished report (for the 10 fire markets re-run on 2026-10-08: their run log ends with exit=0);
  - checked on the other laptop: output/factcheck_applied/<slug>_india (fact-check workbook applied).
Re-run any time; it copies whatever is finished and lists what is still missing.
"""
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
DESK = Path(r"C:\Users\aman.kumar\Desktop")
OUT = ROOT / "output" / "chatgpt_expand"
DOWNLOADS = Path(r"C:\Users\aman.kumar\Downloads")
RERUN_10 = {"battery_fire_safety_industry_analysis", "critical_infrastructure_fire_safety_industry_analysis",
            "disaster_response_industry_analysis", "electrical_fire_safety_industry_analysis",
            "emergency_communications_industry_analysis", "fire_vehicles_industry_analysis",
            "firefighting_equipment_industry_analysis", "life_safety_industry_analysis",
            "rescue_equipment_industry_analysis", "smoke_control_systems_industry_analysis"}


def markets(folder: str) -> list[str]:
    """Every India market in the original Desktop folder (its *_india_quadrant.json files)."""
    return sorted(p.name.replace("_india_quadrant.json", "")
                  for p in (DESK / folder).glob("*_india_quadrant.json"))


def finished_here(base: str) -> Path | None:
    d = OUT / f"{base}_india"
    pipe = d / "_pipeline"
    if base in RERUN_10:
        # Checks-only update of the original report (--update-report): done
        # when the update marker and the rewritten report exist.
        ok = (pipe / "report_update_done").exists() and (d / f"{base}_india_report.html").exists()
        return d if ok else None
    if not all((pipe / f).exists() for f in ("operating_status.json", "ownership.json", "scope_check.json")):
        return None
    if not (d / f"{base}_india_report.html").exists():
        return None
    if base in RERUN_10:
        log = ROOT / "logs" / "parallel" / f"{base}_india.log"
        text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
        if not text.rstrip().endswith("exit=0") or "1. verified rows" not in text.split("exit=")[-1] + text:
            return None
    return d


def excel(payload: dict, path: Path) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = "Companies"
    ws.append(["Brand", "Company", "Role", "Headquarters", "Quadrant", "Placement", "X", "Y", "Overall"])
    rows = sorted(payload.get("brands") or [], key=lambda b: (not b.get("on_chart"), -float(b.get("overall") or 0)))
    for b in rows:
        ws.append([b.get("brand") or "", b.get("company") or "", b.get("commercial_role") or "",
                   b.get("hq_location") or "", b.get("quadrant") or "",
                   "Top chart" if b.get("on_chart") else "Other Noticeable Player",
                   b.get("execution"), b.get("innovation"), b.get("overall")])
    for c in ws[1]:
        c.font = Font(bold=True)
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = min(55, max(10, max(len(str(c.value or "")) for c in col) + 2))
    ws.freeze_panes = "A2"
    wb.save(path)


def build(src_folder: str, dest_name: str) -> None:
    dest = DESK / dest_name
    dest.mkdir(exist_ok=True)
    done, missing = [], []
    for base in markets(src_folder):
        slug = f"{base}_india"
        d = finished_here(base)
        downloaded = DOWNLOADS / f"{slug}_fact_check.xlsx"
        if d:
            shutil.copy2(d / f"{slug}_report.html", dest / f"{slug}_report.html")
            shutil.copy2(d / f"{slug}_quadrant.json", dest / f"{slug}_quadrant.json")
            excel(json.loads((d / f"{slug}_quadrant.json").read_text(encoding="utf-8")), dest / f"{slug}_companies.xlsx")
            done.append((base, "checked here"))
        elif downloaded.exists():
            # Verified on the other laptop: the original report and its
            # fact-check workbook go in exactly as they are.
            src = DESK / src_folder
            shutil.copy2(src / f"{slug}_report.html", dest / f"{slug}_report.html")
            shutil.copy2(src / f"{slug}_quadrant.json", dest / f"{slug}_quadrant.json")
            shutil.copy2(downloaded, dest / downloaded.name)
            (dest / f"{slug}_companies.xlsx").unlink(missing_ok=True)
            done.append((base, "verified on other laptop (original files + downloaded fact-check)"))
        else:
            missing.append(base)
    print(f"== {dest_name}: {len(done)} done, {len(missing)} not ready")
    for b, how in done:
        print(f"   OK  {b}  ({how})")
    for b in missing:
        print(f"   ..  {b}  (not finished yet)")


build("Drone Market Quadrant", "Final Drone Quadrant")
build("Fire Market Quadrant", "Final Fire Quadrant")
