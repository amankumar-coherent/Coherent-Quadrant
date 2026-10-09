"""Accounts Payable Automation: AI Mode fact-check of the 20 chart companies on 10 browsers (read-only, resumable).

Every earlier findings file is merged first; only companies still missing their
status or a verdict on any specific claim are split over the browsers, each
seeded with what was already saved for its companies.
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKET, COUNTRY, BROWSERS, SLOT0 = "Accounts Payable Automation Market", "global", 10, 41
D = ROOT / "output/chatgpt_expand/accounts_payable_automation_market_global"
W = D / "_pipeline/factcheck"
W.mkdir(parents=True, exist_ok=True)
q = json.loads((D / "accounts_payable_automation_market_global_quadrant.json").read_text(encoding="utf-8"))
chart = sorted((b for b in q["brands"] if b.get("on_chart")), key=lambda b: -b["overall"])

merged: dict = {}
for f in sorted(W.glob("findings_*.json")):
    for name, rec in json.loads(f.read_text(encoding="utf-8")).items():
        cur = merged.get(name)
        if (cur is None or len(rec.get("claims") or []) > len(cur.get("claims") or [])
                or (rec.get("status") and not cur.get("status"))):
            merged[name] = rec
(W / "findings_all.json").write_text(json.dumps(merged, indent=1, ensure_ascii=False), encoding="utf-8")


def specific(claim):  # same test as chart_factcheck.py
    return bool(re.search(r"\d|\"|“|‘|'[A-Z]|contract|awarded|partner|acquir|launched|won|selected|"
                          r"certif|ISO|approved|framework|customer|client|integrat", claim, re.I))


def finished(b):
    rec = merged.get(b["company"]) or {}
    if not rec.get("status"):
        return False
    checked = {c["claim"] for c in rec.get("claims") or [] if c.get("verdict")}
    need = {e.get("claim") for ax in ("x", "y")
            for v in b["score_detail"][ax]["parameters"].values() for e in v.get("evidence") or []
            if e.get("claim") and e.get("claim") != "Not available" and specific(e.get("claim"))}
    return need <= checked


todo = [b["company"] for b in chart if not finished(b)]
print(f"[factcheck] {len(chart) - len(todo)} finished, {len(todo)} to check on {BROWSERS} browsers", flush=True)
for old in W.glob("findings_*.json"):
    if old.name != "findings_all.json":
        old.unlink()
procs = []
for i in range(min(BROWSERS, len(todo))):
    names = todo[i::BROWSERS]
    (W / f"companies_{i + 1}.json").write_text(json.dumps(names, ensure_ascii=False), encoding="utf-8")
    (W / f"findings_{i + 1}.json").write_text(
        json.dumps({n: merged[n] for n in names if n in merged}, indent=1, ensure_ascii=False), encoding="utf-8")
    log = (ROOT / "logs" / f"factcheck_ap_{i + 1}.log").open("a", encoding="utf-8")
    procs.append(subprocess.Popen([sys.executable, str(ROOT / "logs/chart_factcheck.py"), "--market", MARKET,
                                   "--country", COUNTRY, "--slot", str(SLOT0 + i), "--companies",
                                   str(W / f"companies_{i + 1}.json"), "--out", str(W / f"findings_{i + 1}.json")],
                                  cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                  env={**os.environ, "PYTHONIOENCODING": "utf-8", "GOOGLE_AI_MODE_QUERY_DELAY": "10"}))
    print(f"browser {i + 1}: slot {SLOT0 + i}, {names}", flush=True)
    time.sleep(10)
for p in procs:
    p.wait()
print("[factcheck] all browsers finished", flush=True)
