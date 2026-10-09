#!/usr/bin/env python3
"""Step 7c: ask Google AI Mode for a disclosed figure or a defensible estimate
behind every figure gap ("Based on primary research, the company has not
disclosed <a number>") in the companies' 'Assessed on' text.

Companies are split over N browsers (one profile slot each); each company's
gaps go in as few queries as fit the AI Mode URL. Answers are saved as they
arrive (<market>/_pipeline/estimates/answers_<i>.json, merged into
answers.json), so a re-run only asks what is still missing. This script only
collects answers: vendor_intel.pipeline.estimates judges them (basis, sources,
precision, confidence) and writes the report text.

    .venv\\Scripts\\python.exe scripts\\estimate_gaps.py --market "X Market" --country global ^
        --browsers 8 --slot-start 41 [--names-file names.json]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from vendor_intel.pipeline import estimates as est  # noqa: E402
from vendor_intel.pipeline.quadrant_pipeline import load_evidence  # noqa: E402


def _hq(out_dir: Path) -> dict[str, str]:
    try:
        ckpt = json.loads((out_dir / "chatgpt_checkpoint_batch_all.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    rows = (ckpt.get("data") or {}).get("verified") or []
    return {str(r.get("Company") or ""): str(r.get("Headquarters") or "") for r in rows if isinstance(r, dict)}


def worker(args) -> int:
    """One browser: ask for the tasks in --tasks, saving to --out."""
    os.environ["GOOGLE_AI_MODE_PROFILE_DIR"] = str(ROOT / "data" / f"ai_mode_batch_{args.slot:02d}")
    os.environ["GOOGLE_AI_MODE_BROWSER"] = "chromium"
    os.environ["GOOGLE_AI_MODE_ENABLED"] = "true"
    from vendor_intel.config import Settings
    from vendor_intel.pipeline import chatgpt_expand as ce
    from vendor_intel.pipeline.web_expand import default_output_dir

    out_dir = Path(default_output_dir(args.market, args.country))
    hq = _hq(out_dir)
    tasks = json.loads(Path(args.tasks).read_text(encoding="utf-8"))
    out_file = Path(args.out)
    done = json.loads(out_file.read_text(encoding="utf-8")) if out_file.exists() else {}
    client, model = ce._client(Settings()), ce._model(Settings())

    def save() -> None:
        tmp = out_file.with_name(out_file.name + ".tmp")
        tmp.write_text(json.dumps(done, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, out_file)

    from vendor_intel.scraping import google_ai_mode as gam

    bad = est._bad_source_rx()
    by_company: dict[str, list[dict]] = {}
    for t in tasks:
        by_company.setdefault(t["company"], []).append(t)
    for company, todo in by_company.items():
        where = hq.get(company, "")
        # 1. What the company itself has published (asked once per company).
        facts = todo[0].get("facts")
        if facts is None:
            try:
                res = ce._chat_json(client, model, est.FACTS_SYSTEM,
                                    est.build_facts_query(company, args.market, where),
                                    label=f"facts-{company[:20]}", max_tokens=3000, require_key="results")
                facts = [{k: str(r.get(k) or "").strip() for k in ("fact", "year", "source")}
                         for r in (res or {}).get("results") or [] if isinstance(r, dict)]
                facts = [f for f in facts if f["fact"] and f["source"] and est._NUM.search(f["fact"])
                         and not bad.search(f"{f['fact']} {f['source']}")]
                done[f"facts:{company}"] = {"company": company, "facts": facts}
                save()
            except Exception as err:  # noqa: BLE001 -- the estimates below still run without them
                print("failed facts", company, err, flush=True)
                facts = []
        # 2. A worked estimate per gap, in plain text, up to 5 gaps a query
        # (more and the analysis gets shallow), as many as fit the URL: a
        # prompt that does not fit would go to the API, which never does
        # research in this pipeline.
        # Figure gaps and worded gaps go in separate questions (different
        # answer lines).
        for worded in (False, True):
            queue = [t for t in todo if (t.get("mode") == "worded") == worded]
            while queue:
                k, chars = min(5, len(queue)), 1800
                while True:
                    if worded:
                        prompt = est.build_worded_prompt(company, args.market, where, facts, queue[:k], chars)
                    else:
                        prompt = est.build_estimate_prompt(company, args.market, where, facts, queue[:k], chars,
                                                           push=any(t.get("push") for t in queue[:k]))
                    if ce._ai_mode_url_fits("", prompt):
                        break
                    if k > 1:
                        k -= 1
                    elif chars > 300:
                        chars -= 300
                    else:
                        break
                chunk, queue = queue[:k], queue[k:]
                blocks: list[dict] = []
                for attempt in (1, 2):
                    try:
                        answer = gam.ask(prompt)
                        blocks = est.parse_worded(answer) if worded else est.parse_blocks(answer)
                    except Exception as err:  # noqa: BLE001 -- one failed query must not stop the rest
                        print("failed", company, err, flush=True)
                    if blocks:
                        break
                for t, mine in zip(chunk, est.assign_blocks(blocks, chunk)):
                    new = mine if worded else [est.to_result(b, facts) for b in mine]
                    done[t["id"]] = {"company": company, "parameter": t["parameter"], "gap": t["gap"],
                                     # a second (firmer) ask adds to the first answer; judge() picks
                                     "results": [*(t.get("prev") or []), *new],
                                     "asks": int(t.get("asks") or 0) + 1}
                save()
                print("saved", company, len(chunk), "worded" if worded else "figure", "gap(s),",
                      len(blocks), "line(s)", flush=True)
    print("finished", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", required=True)
    ap.add_argument("--country", default="global")
    ap.add_argument("--browsers", type=int, default=8)
    ap.add_argument("--slot-start", type=int, default=41)
    ap.add_argument("--names-file", default="", help="JSON list of companies (default: every company "
                                                     "with full evidence)")
    ap.add_argument("--stagger", type=float, default=10.0, help="seconds between browser launches")
    ap.add_argument("--slot", type=int, default=0, help=argparse.SUPPRESS)
    ap.add_argument("--tasks", default="", help=argparse.SUPPRESS)
    ap.add_argument("--out", default="", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.tasks:
        return worker(args)

    from vendor_intel.pipeline.web_expand import default_output_dir

    out_dir = Path(default_output_dir(args.market, args.country))
    work = out_dir / "_pipeline" / est.EST_DIR
    work.mkdir(parents=True, exist_ok=True)
    evidence = load_evidence(out_dir)
    names = (json.loads(Path(args.names_file).read_text(encoding="utf-8")) if args.names_file
             else list(evidence))
    answers = est.load_answers(out_dir / "_pipeline")
    # One merged file; per-browser files are rebuilt for this run's split.
    (work / est.ANSWERS).write_text(json.dumps(answers, indent=1, ensure_ascii=False), encoding="utf-8")
    for old in [*work.glob("answers_*.json"), *work.glob("tasks_*.json")]:
        old.unlink()
    tasks = est.gap_tasks(evidence, names)
    todo = [{**t, "asks": int((answers.get(t["id"]) or {}).get("asks") or 0),
             "facts": (answers.get(f"facts:{t['company']}") or {}).get("facts")}
            for t in (est.pending(tasks, answers) if est.numeric_estimates_enabled() else [])]
    # Answered gaps still without an estimate: asked once more, firmer.
    todo += [{**t, "asks": int(answers[t["id"]].get("asks") or 0), "push": True,
              "prev": answers[t["id"]].get("results") or [],
              "facts": (answers.get(f"facts:{t['company']}") or {}).get("facts")}
             for t in est.unestimated(out_dir, names, answers)]
    def run_round(todo: list[dict], label: str) -> dict:
        """Split `todo` by company over the browsers, wait, return merged answers."""
        companies = list(dict.fromkeys(t["company"] for t in todo))
        n = min(args.browsers, len(companies))
        print(f"[estimates] {label}: {len(todo)} to ask ({len(companies)} companies) on {n} browser(s)",
              flush=True)
        procs = []
        for i in range(n):
            mine = set(companies[i::n])
            part = work / f"tasks_{label}_{i + 1}.json"
            part.write_text(json.dumps([t for t in todo if t["company"] in mine], ensure_ascii=False),
                            encoding="utf-8")
            log = (work / f"browser_{i + 1}.log").open("a", encoding="utf-8")
            procs.append(subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "--market", args.market, "--country",
                 args.country, "--slot", str(args.slot_start + i), "--tasks", str(part),
                 "--out", str(work / f"answers_{label}_{i + 1}.json")],
                cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"}))
            time.sleep(args.stagger)
        for p in procs:
            p.wait()
        merged = est.load_answers(out_dir / "_pipeline")
        (work / est.ANSWERS).write_text(json.dumps(merged, indent=1, ensure_ascii=False), encoding="utf-8")
        return merged

    print(f"[estimates] {len(tasks)} figure gap(s) in {len(names)} companies", flush=True)
    if todo:
        answers = run_round(todo, "figures")
    # Round 2: every gap sentence still without an estimate -- not about a
    # number, or a number no figure could answer -- gets one in words.
    worded = [{**t, "facts": (answers.get(f"facts:{t['company']}") or {}).get("facts") or []}
              for t in est.worded_needed(out_dir, names, answers)]
    if worded:
        answers = run_round(worded, "worded")
    left = est.pending(tasks, answers)
    print(f"[estimates] done: {len(tasks) - len(left)} of {len(tasks)} answered"
          + (f"; {len(left)} still to ask (re-run to resume)" if left else ""), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
