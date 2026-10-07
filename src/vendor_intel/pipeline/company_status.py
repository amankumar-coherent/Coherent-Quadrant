"""Is each company still operating? Plus the analyst review file.

A landscape lists companies a client could hire or buy from today. Discovery
and verification judge what a company DOES, and a company that went bankrupt,
was liquidated, or was bought and absorbed still has a website, case studies
and papers -- so it verified and scored like a live competitor (a Chapter 7
filing from 2016 sat in a Top 20). Two generic guards, no market-specific data:

1. Operating-status check (Google AI Mode, like every other research step):
   every verified company is asked about once, in batches, and the answer is
   saved to ``_pipeline/operating_status.json``:
   ``{name: {"status": active|acquired|defunct|renamed, "note": ..., "successor": ...}}``.
   New markets get the same rule inside verification (chatgpt_expand.STATUS_RULE);
   this module re-checks markets verified before that rule existed.

2. Analyst review (``_pipeline/analyst_review.json``), written by a person
   reviewing the finished report::

       {"exclude": [{"company": "...", "reason": "...", "source": "..."}],
        "corrections": [{"company": "...", "find": "...", "replace": "...",
                         "reason": "...", "source": "..."}],
        "hq": [{"company": "...", "headquarters": "City, Country", "source": "..."}]}

   ``exclude`` removes a company whatever the status check said (a reviewer's
   confirmed finding outranks a model's answer). ``corrections`` replace an
   exact piece of evidence text for one company. Both are DATA kept with the
   market's own output, never code, and every entry records why and where
   from, so the report stays auditable. ``hq`` sets a confirmed headquarters.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Iterable

from vendor_intel.pipeline.quadrant_pipeline import norm_name, quadrant_of, row_name, write_json_atomic

STATUS_FILE = "operating_status.json"
REVIEW_FILE = "analyst_review.json"
WORDING_FILE = "wording_review.json"
# Evidence bullet for a parameter with no finding (see apply_wording).
NOT_AVAILABLE = "Not available"
STATUS_BATCH = 10


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


_LABEL = re.compile(r"\s*\((?:acquired by|subsidiary of)\s[^)]*\)\s*$", re.I)


def company_aliases(out_dir: Path) -> dict[str, set[str]]:
    """norm_name -> every normalised name of the same company.

    From the dedupe groups (one company listed under several names) and the
    last report's brand / company key / display name, both saved per market.
    """
    out_dir = Path(out_dir)
    groups: list[set[str]] = []
    for rep, names in (_read(out_dir / "_pipeline" / "dedupe_groups.json", {}) or {}).items():
        groups.append({norm_name(n) for n in [rep, *(names or [])]})
    for qf in out_dir.glob("*_quadrant.json"):
        for b in (_read(qf, {}) or {}).get("brands") or []:
            names = [b.get("company_key"), b.get("brand"), b.get("display_name"),
                     _LABEL.sub("", str(b.get("company") or ""))]
            groups.append({norm_name(str(n)) for n in names if n})
    parent: dict[str, str] = {}

    def root(n: str) -> str:
        while parent.setdefault(n, n) != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    for g in groups:
        g.discard("")
        first = next(iter(g), None)
        for n in g:
            parent[root(n)] = root(first)
    members: dict[str, set[str]] = {}
    for n in list(parent):
        members.setdefault(root(n), set()).add(n)
    return {n: members[root(n)] for n in parent}


def load_status(pipe_dir: Path) -> dict[str, dict[str, str]]:
    return _read(Path(pipe_dir) / STATUS_FILE, {}) or {}


def save_status(pipe_dir: Path, status: dict[str, dict[str, str]]) -> None:
    path = Path(pipe_dir) / STATUS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")


def load_review(pipe_dir: Path, *, include_auto: bool = True) -> dict[str, list[dict[str, str]]]:
    """The analyst review merged with the automatic one (company_facts).

    The analyst always wins: ``keep`` undoes an automatic exclusion, and an
    analyst ``ownership`` entry replaces the automatic one for that company
    (``"owner": ""`` clears the label)."""
    from vendor_intel.pipeline.company_facts import AUTO_REVIEW_FILE

    review = _read(Path(pipe_dir) / REVIEW_FILE, {}) or {}
    # Step 3b runs before 3c recomputes the automatic review, so it must not
    # act on the previous run's (possibly superseded) automatic decisions.
    auto = dict((_read(Path(pipe_dir) / AUTO_REVIEW_FILE, {}) or {}) if include_auto else {})
    # The chart fact-check (step 8a) is another automatic layer: it is not
    # recomputed by 3c, so it applies at 3b as well. The analyst still wins.
    from vendor_intel.pipeline.factcheck import FACTCHECK_FILE

    fc = _read(Path(pipe_dir) / FACTCHECK_FILE, {}) or {}
    fc_own = {norm_name(r.get("company") or "") for r in fc.get("ownership") or []}
    auto["exclude"] = list(auto.get("exclude") or []) + list(fc.get("exclude") or []) + [
        {"company": r["company"], "reason": r.get("reason") or "fact-check: not in this market",
         "source": r.get("source") or "fact-check"}
        for r in fc.get("scope") or [] if str(r.get("scope") or "").lower() == "out"]
    auto["adjacent"] = list(auto.get("adjacent") or []) + [
        r for r in fc.get("scope") or [] if str(r.get("scope") or "").lower() == "adjacent"]
    auto["ownership"] = [r for r in auto.get("ownership") or []
                         if norm_name(r.get("company") or "") not in fc_own] + list(fc.get("ownership") or [])
    manual_hq = {norm_name(r.get("company") or "") for r in review.get("hq") or []}
    fc_hq = [r for r in fc.get("hq") or [] if norm_name(r.get("company") or "") not in manual_hq]
    # A fact-check fix of a sentence the analyst already corrected (any part
    # of it, under any of the company's names) is dropped: the analyst wins.
    fc_fix = list(fc.get("corrections") or [])
    if fc_fix and review.get("corrections"):
        same = company_aliases(Path(pipe_dir).parent)

        def _names(n: str) -> set[str]:
            return same.get(norm_name(n), {norm_name(n)})

        manual = [(_names(r.get("company") or ""), str(r.get("find") or "")) for r in review["corrections"]]
        fc_fix = [r for r in fc_fix
                  if not any(norm_name(r.get("company") or "") in names and find and find in str(r.get("find") or "")
                             for names, find in manual)]
    keep = {norm_name(r.get("company") or "") for r in review.get("keep") or []}
    manual_own = {norm_name(r.get("company") or "") for r in review.get("ownership") or []}
    manual_disp = {norm_name(r.get("company") or "") for r in review.get("display") or []}
    # An analyst scope entry (core | adjacent | out) replaces the automatic one.
    scope = {norm_name(r.get("company") or ""): str(r.get("scope") or "").strip().lower()
             for r in review.get("scope") or [] if r.get("company")}
    exclude = [r for r in auto.get("exclude") or []
               if norm_name(r.get("company") or "") not in keep
               and scope.get(norm_name(r.get("company") or ""), "out") == "out"]
    exclude += [{"company": r["company"], "reason": r.get("reason") or "analyst review: not in this market",
                 "source": r.get("source") or "analyst review"}
                for r in review.get("scope") or [] if str(r.get("scope") or "").lower() == "out"]
    exclude += list(review.get("exclude") or [])
    adjacent = [r for r in auto.get("adjacent") or [] if norm_name(r.get("company") or "") not in scope]
    adjacent += [r for r in review.get("scope") or [] if str(r.get("scope") or "").lower() == "adjacent"]
    ownership = [r for r in auto.get("ownership") or []
                 if norm_name(r.get("company") or "") not in manual_own] + list(review.get("ownership") or [])
    display = [r for r in auto.get("display") or []
               if norm_name(r.get("company") or "") not in manual_disp] + list(review.get("display") or [])
    return {"exclude": exclude,
            "corrections": list(review.get("corrections") or []) + fc_fix,
            "hq": list(review.get("hq") or []) + fc_hq,
            "ownership": ownership,
            "adjacent": adjacent,
            "display": display,
            "keep": list(review.get("keep") or [])}


def chart_ineligible(pipe_dir: Path) -> set[str]:
    """Normalised names of adjacent-segment companies: listed, but never on
    the chart (the quadrant compares core players like with like)."""
    return {norm_name(r.get("company") or "") for r in load_review(pipe_dir)["adjacent"]}


# Answers that remove a company -- only with a stated event (see below).
GONE_STATUSES = ("acquired", "defunct", "exited")


def inactive_companies(pipe_dir: Path, *, include_auto: bool = True) -> dict[str, str]:
    """{normalised name: reason} for every company that must not be listed.

    A company is removed only by an answer that it was acquired, is defunct
    or has exited the market AND that names the event ("Liquidated in 2019.")
    -- or by a reviewer's exclusion. A bare "defunct" with no event, a
    "renamed" (same business, new name) and a missing answer all keep the
    company: none of them is evidence that it closed. Those go to
    status_needs_review() for a person to confirm.
    """
    out: dict[str, str] = {}
    for name, rec in load_status(pipe_dir).items():
        st = str((rec or {}).get("status") or "").strip().lower()
        note = str((rec or {}).get("note") or "").strip()
        if st in GONE_STATUSES and note:
            out[norm_name(name)] = f"{st}: {note}"
    for row in load_review(pipe_dir, include_auto=include_auto)["exclude"]:
        name = str(row.get("company") or "").strip()
        if name:
            out[norm_name(name)] = "analyst review: " + str(row.get("reason") or "excluded").strip()
    return out


def is_inactive(name: str, inactive: dict[str, str]) -> bool:
    return norm_name(name) in inactive


def status_needs_review(pipe_dir: Path) -> dict[str, str]:
    """{name: answer} for status answers that were NOT acted on but deserve a
    person's look: renamed companies (listed under their old name) and
    non-active answers that gave no event."""
    excluded = {norm_name(r.get("company") or "") for r in load_review(pipe_dir)["exclude"]}
    out: dict[str, str] = {}
    for name, rec in load_status(pipe_dir).items():
        st = str((rec or {}).get("status") or "").strip().lower()
        note = str((rec or {}).get("note") or "").strip()
        if norm_name(name) in excluded or st == "active" or (st in GONE_STATUSES and note):
            continue
        succ = str((rec or {}).get("successor") or "").strip()
        out[name] = st + (f": {note}" if note else " (no event given)") + (f" -> {succ}" if succ else "")
    return out


# -- status check (AI Mode) --------------------------------------------------

def status_prompt(market: str, scope: str) -> str:
    from vendor_intel.pipeline.chatgpt_expand import STATUS_RULE

    return (
        "You are checking whether companies in a market landscape still operate "
        "today. Answer from current, verifiable facts: bankruptcy or insolvency "
        "filings, liquidations, acquisitions, mergers and renamings.\n"
        f"Market: {market}\n"
        + (f"Market scope: {scope}\n" if scope else "")
        + STATUS_RULE
        + "status_note: one short factual sentence with the event and year "
        '(e.g. "Filed for Chapter 7 bankruptcy in 2016."); empty when active. '
        "successor: the new name, or the company that now owns or replaced it, "
        "else empty.\n"
        "Return one result for EVERY company, never skip a name. Return compact "
        'JSON only: {"results":[{"name":"...","operating_status":'
        '"active|acquired|defunct|renamed","status_note":"...","successor":"..."}]}'
    )


def check_status(
    ask: Callable[[str, str, str], Any],
    market: str,
    scope: str,
    companies: list[dict[str, str]],
    status: dict[str, dict[str, str]],
    on_batch: Callable[[dict[str, dict[str, str]]], None] | None = None,
) -> dict[str, dict[str, str]]:
    """Ask about every company not yet in ``status``; returns the updated map.

    ``ask(system, user, label)`` returns parsed JSON (chatgpt_expand._chat_json
    bound to the market's client), so the check runs on whichever research
    backend the pipeline uses -- Google AI Mode when it is on.
    """
    todo = [c for c in companies if c.get("name") and c["name"] not in status]
    system = status_prompt(market, scope)
    for i in range(0, len(todo), STATUS_BATCH):
        chunk = todo[i: i + STATUS_BATCH]
        payload = [{"name": c["name"], "website": c.get("website") or ""} for c in chunk]
        data = ask(system, f"Companies:\n{json.dumps(payload, ensure_ascii=False)}",
                   f"status-{i // STATUS_BATCH + 1}")
        results = data.get("results") if isinstance(data, dict) else None
        by_key = {norm_name(c["name"]): c["name"] for c in chunk}
        for r in results if isinstance(results, list) else []:
            if not isinstance(r, dict):
                continue
            name = by_key.get(norm_name(str(r.get("name") or "")))
            st = str(r.get("operating_status") or "").strip().lower()
            if name and st in ("active", "renamed", "acquired", "defunct", "exited"):
                status[name] = {"status": st,
                                "note": str(r.get("status_note") or "").strip(),
                                "successor": str(r.get("successor") or "").strip()}
        if on_batch:
            on_batch(status)
    return status


# -- analyst corrections -----------------------------------------------------

def apply_corrections(out_dir: Path, corrections: Iterable[dict[str, str]],
                      normalize: Callable[[str], str] | None = None) -> list[dict[str, Any]]:
    """Replace each correction's exact ``find`` text in that company's evidence
    (claims and reasoning) in every param_detail_prescored*.json sidecar.

    Idempotent: once replaced, ``find`` no longer occurs. Returns one row per
    correction with how many places changed (0 = not found or already done,
    which the caller reports so a mistyped entry is never silently ignored).
    """
    rows = [dict(c) for c in corrections if c.get("company") and c.get("find")]
    same = company_aliases(out_dir)
    for row in rows:
        row["changed"] = 0
        # A removal (empty replace) leaves nothing to find once applied.
        row["already_applied"] = False
        # Sidecars key a company by whichever name scored it ("Coupa Software",
        # "Coupa Software Inc.", brand "Coupa"); a reviewer may use any of them.
        row["_names"] = same.get(norm_name(row["company"]), {norm_name(row["company"])})
    for side in sorted(Path(out_dir).glob("param_detail_prescored*.json")):
        part = _read(side, None)
        if not isinstance(part, dict):
            continue
        dirty = False
        for name, rec in part.items():
            for row in rows:
                if norm_name(name) not in row["_names"]:
                    continue
                for axis in ("x", "y"):
                    for v in ((rec.get(axis) or {}).get("parameters") or {}).values():
                        if not isinstance(v, dict):
                            continue
                        texts = [(v, "assessed_on")] + [
                            (e, "claim") for e in v.get("evidence") or [] if isinstance(e, dict)]
                        for obj, key in texts:
                            t = str(obj.get(key) or "")
                            # Later wording steps (house style) may have reworded
                            # the replacement itself; it still counts as applied.
                            rep = row.get("replace") or ""
                            done = bool(rep) and (rep in t or bool(normalize) and normalize(rep) in t)
                            if row["find"] in t and not (done and row["find"] in row["replace"]):
                                obj[key] = t.replace(row["find"], row.get("replace", ""))
                                row["changed"] += 1
                                dirty = True
                            elif done:
                                row["already_applied"] = True
                        # An empty "replace" of a whole claim removes that
                        # evidence item (a finding that cannot be supported),
                        # rather than leaving a blank bullet in the report.
                        if isinstance(v.get("evidence"), list):
                            kept = [e for e in v["evidence"]
                                    if not (isinstance(e, dict) and not str(e.get("claim") or "").strip())]
                            if len(kept) != len(v["evidence"]):
                                v["evidence"] = kept
                                dirty = True
        if dirty:
            write_json_atomic(side, part, indent=2)
    return rows


def load_wording(pipe_dir: Path) -> dict[str, str]:
    """``_pipeline/wording_review.json``: {current justification: approved rewrite}.

    Reviewed analyst rewrites of "why" lines (basis first, then the gap),
    kept as data with the market so a re-run re-applies them.
    """
    return dict(_read(Path(pipe_dir) / WORDING_FILE, {}) or {})


def apply_wording(out_dir: Path, mapping: dict[str, str]) -> int:
    """Replace every assessed_on that exactly matches a key. Idempotent."""
    if not mapping:
        return 0
    changed = 0
    for side in sorted(Path(out_dir).glob("param_detail_prescored*.json")):
        part = _read(side, None)
        if not isinstance(part, dict):
            continue
        dirty = False
        for rec in part.values():
            for axis in ("x", "y"):
                for v in ((rec.get(axis) or {}).get("parameters") or {}).values():
                    if not isinstance(v, dict):
                        continue
                    # Justifications and evidence claims alike; a rewrite of a
                    # rewrite is followed to its end (reviews build on each other).
                    slots = [(v, "assessed_on")] + [
                        (e, "claim") for e in v.get("evidence") or [] if isinstance(e, dict)]
                    for obj, key in slots:
                        cur, hops = obj.get(key), 0
                        while cur in mapping and mapping[cur] != cur and hops < 5:
                            cur, hops = mapping[cur], hops + 1
                        if hops:
                            obj[key] = cur
                            changed += 1
                            dirty = True
                    # Several gap bullets can collapse to the same reviewed
                    # text ("Not available"); a parameter lists each once.
                    # "Not available" appears only when the parameter has no
                    # real finding at all -- beside a finding it contradicts it.
                    ev = v.get("evidence")
                    if isinstance(ev, list):
                        from vendor_intel.pipeline.company_facts import collapse_not_available

                        kept = collapse_not_available(ev)
                        if len(kept) != len(ev):
                            v["evidence"] = kept
                            dirty = True
        if dirty:
            write_json_atomic(side, part, indent=2)
    return changed


def apply_hq_corrections(ckpt_path: Path, fixes: Iterable[dict[str, str]]) -> list[dict[str, Any]]:
    """Set a reviewer-confirmed headquarters on the company's verified rows in
    the market checkpoint (the report reads HQ from there). Idempotent."""
    rows = [dict(f, changed=0, matched=False) for f in fixes
            if f.get("company") and f.get("headquarters")]
    if not rows:
        return rows
    state = _read(Path(ckpt_path), None)
    if not isinstance(state, dict):
        return rows
    dirty = False
    for r in (state.get("data") or {}).get("verified") or []:
        names = {norm_name(row_name(r)), norm_name(str(r.get("brand") or r.get("Brand") or ""))}
        for fix in rows:
            if norm_name(fix["company"]) not in names:
                continue
            fix["matched"] = True
            for key in ("headquarters", "Headquarters"):
                if key in r and r[key] != fix["headquarters"]:
                    r[key] = fix["headquarters"]
                    fix["changed"] += 1
                    dirty = True
            if "headquarters" not in r and "Headquarters" not in r:
                r["headquarters"] = fix["headquarters"]
                fix["changed"] += 1
                dirty = True
    if dirty:
        Path(ckpt_path).write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    return rows


def apply_ownership_corrections(ckpt_path: Path, fixes: Iterable[dict[str, str]]) -> list[dict[str, Any]]:
    """Set a reviewer-confirmed owner on the company's verified rows in the
    market checkpoint. brand_meta.brand_display_fields then writes the Company
    column as "Name (acquired by Owner)"; the brand -- the scoring key -- is
    untouched. Confidence is set high because a reviewer confirmed the deal
    (a "low" would suppress the suffix). ``"owner": ""`` clears a label that
    an earlier run set. Idempotent."""
    rows = [dict(f, changed=0, matched=False) for f in fixes
            if f.get("company") and "owner" in f]
    if not rows:
        return rows
    state = _read(Path(ckpt_path), None)
    if not isinstance(state, dict):
        return rows
    dirty = False
    for r in (state.get("data") or {}).get("verified") or []:
        names = {norm_name(row_name(r)), norm_name(str(r.get("brand") or r.get("Brand") or ""))}
        for fix in rows:
            if norm_name(fix["company"]) not in names:
                continue
            fix["matched"] = True
            owner = str(fix["owner"] or "").strip()
            if not owner:
                for key in ("parent_owner", "ownership_relation"):
                    if r.pop(key, None) is not None:
                        dirty = True
                        fix["changed"] = 1
                continue
            # "acquired by" only for a recent deal; a long-held company reads
            # "subsidiary of" (a 1998 purchase labelled "acquired by" reads as news).
            from vendor_intel.pipeline.company_facts import ownership_relation

            want = {"parent_owner": owner,
                    "ownership_relation": fix.get("relation") or ownership_relation(fix.get("year")),
                    "ownership_confidence": "high"}
            for key in ("ownership", "Ownership"):
                if key in r:
                    want[key] = f"Acquired by {owner}"
            for key, val in want.items():
                if r.get(key) != val:
                    r[key] = val
                    dirty = True
                    fix["changed"] = 1
    if dirty:
        Path(ckpt_path).write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    return rows


def apply_display_corrections(ckpt_path: Path, fixes: Iterable[dict[str, str]]) -> list[dict[str, Any]]:
    """A retired or divested brand is shown under the name the business trades
    as today: Company column = the current name, Brand column = "Current
    (Legacy legacy)". Only display fields are written; the company's own name
    stays the key every lookup uses. ``"current_name": ""`` clears it. Idempotent."""
    rows = [dict(f, changed=0, matched=False) for f in fixes
            if f.get("company") and "current_name" in f]
    state = _read(Path(ckpt_path), None)
    if not isinstance(state, dict):
        return rows
    dirty = False
    wanted = {norm_name(f["company"]) for f in rows}
    for r in (state.get("data") or {}).get("verified") or []:
        names = {norm_name(row_name(r)), norm_name(str(r.get("brand") or r.get("Brand") or ""))}
        # A display set by an earlier run that no review asks for any more.
        if not names & wanted:
            for key in ("current_company", "brand_label"):
                if r.pop(key, None) is not None:
                    dirty = True
            continue
        for fix in rows:
            if norm_name(fix["company"]) not in names:
                continue
            fix["matched"] = True
            current = str(fix["current_name"] or "").strip()
            brand = str(r.get("brand_name") or r.get("brand") or r.get("Brand") or row_name(r)).strip()
            same = bool(current) and (norm_name(brand) in norm_name(current)
                                      or norm_name(current) in norm_name(brand))
            want = ({"current_company": current,
                     "brand_label": fix.get("brand_label") or (current if same else f"{current} ({brand} legacy)")}
                    if current else {})
            for key in ("current_company", "brand_label"):
                if key not in want and r.pop(key, None) is not None:
                    dirty = True
                    fix["changed"] = 1
                elif key in want and r.get(key) != want[key]:
                    r[key] = want[key]
                    dirty = True
                    fix["changed"] = 1
    if dirty:
        Path(ckpt_path).write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    return rows


# -- chart refill --------------------------------------------------------------

def refill_top_by_quadrant(
    keep: list[str], xy: dict[str, tuple[float, float]], top_n: int = 20,
    eligible: Callable[[str], bool] | None = None,
) -> list[str]:
    """The chart after 3b changed the pool: surviving companies stay, and each
    quadrant short of its share (top_n/4) takes the best remaining company of
    that quadrant by Overall -- the same rule as select_top_by_quadrant,
    without reshuffling the companies that stayed.

    Removing even long-tail companies moves the pool's median X/Y, so a chart
    company near the split can cross into a neighbouring quadrant (6/5/4/5).
    A quadrant over its share keeps its best companies by Overall; the extra
    ones leave so the short quadrant can be filled.

    ``eligible`` limits who may hold a chart slot (adjacent-segment companies
    may not); the median split still uses every scored company, as the
    composite step does.
    """
    ok = eligible or (lambda n: True)
    names = sorted(xy)
    if len(names) <= top_n:
        return sorted((n for n in names if ok(n)), key=lambda n: -(xy[n][0] + xy[n][1]))
    overall = {n: (xy[n][0] + xy[n][1]) / 2 for n in names}
    by_overall = sorted((n for n in names if ok(n)), key=lambda n: (-overall[n], n))
    xs, ys = sorted(v[0] for v in xy.values()), sorted(v[1] for v in xy.values())
    mid = len(xs) // 2
    mid_x = xs[mid] if len(xs) % 2 else (xs[mid - 1] + xs[mid]) / 2
    mid_y = ys[mid] if len(ys) % 2 else (ys[mid - 1] + ys[mid]) / 2
    picked = [n for n in keep if n in xy and ok(n)]
    share = top_n // 4
    for quad in ("Leaders", "Challengers", "Trailblazers", "Emerging Players"):
        members = sorted((n for n in picked if quadrant_of(*xy[n], mid_x, mid_y) == quad),
                         key=lambda n: (-overall[n], n))
        picked = [n for n in picked if n not in set(members[share:])]
    for quad in ("Leaders", "Challengers", "Trailblazers", "Emerging Players"):
        have = sum(1 for n in picked if quadrant_of(*xy[n], mid_x, mid_y) == quad)
        for n in by_overall:
            if have >= share or len(picked) >= top_n:
                break
            if n not in picked and quadrant_of(*xy[n], mid_x, mid_y) == quad:
                picked.append(n)
                have += 1
    for n in by_overall:
        if len(picked) >= top_n:
            break
        if n not in picked:
            picked.append(n)
    return sorted(picked, key=lambda n: (-overall[n], n))
