"""Pure, market-agnostic logic behind scripts/run_quadrant_pipeline.py.

Nothing here launches a browser or names a market: dedupe, evidence merge,
gap audit and ranking all work from the checkpoint + sidecar files of
whatever market is being run, so every market goes through the same steps.
"""
from __future__ import annotations

import json
import os
import random
import re
import time
import unicodedata
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

# Hosting / social platforms: a website on one of these says nothing about
# which company it is, so it must never merge two companies into one group.
_PLATFORM_DOMAINS = {
    "linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
    "youtube.com", "google.com", "amazon.com", "amazon.in", "flipkart.com",
    "wikipedia.org", "crunchbase.com", "github.com", "medium.com",
    "blogspot.com", "wordpress.com", "wixsite.com", "sites.google.com",
}
# Second-level labels under which the registrable domain is 3 labels deep
# (acme.co.uk, acme.com.au, acme.co.in ...).
_SECOND_LEVEL = {"co", "com", "net", "org", "gov", "ac", "edu", "ltd", "plc"}
_NAME_SUFFIXES = {
    "inc", "incorporated", "ltd", "limited", "llc", "llp", "lp", "plc", "co",
    "corp", "corporation", "company", "gmbh", "ag", "sa", "sas", "srl", "spa",
    "bv", "nv", "ab", "as", "asa", "oy", "pte", "pty", "pvt", "private",
    "kk", "kft", "sp", "zoo", "the",
    # Brazilian / Latin American legal forms: "Despurifil Ltda", "X Eireli" and
    # "X S/A" were kept apart from "Despurifil" and charted twice.
    "ltda", "eireli", "epp",
}


def write_json_atomic(path: Path, obj: Any, *, indent: int | None = None) -> None:
    """Write JSON through a temp file + rename.

    An evidence sidecar rewritten in place by two processes at once (or one
    stopped mid-write) ends up as two JSON documents run together; every
    later step that reads it then skips or crashes on the whole file.
    """
    path = Path(path)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj, indent=indent, ensure_ascii=False), encoding="utf-8")
    # Windows: a reader (another shard, an antivirus scan) holding the target
    # for a moment makes os.replace raise PermissionError -- retry, do not die.
    for attempt in range(8):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(0.25 * (attempt + 1))


def update_json_locked(path: Path, mutate, *, indent: int | None = None, timeout: float = 180.0,
                       stale_after: float = 90.0) -> None:
    """Read-modify-write of a JSON file several browsers share.

    Every shard of the gap-fill step writes its fix into the SAME evidence
    files. Unlocked, two shards read the same version and the later write
    drops the earlier fix; with a shared temp name they also overwrote each
    other's temp file (a damaged "Extra data" JSON, or PermissionError on
    rename) -- seen live with 11 browsers. The lock is a file created
    exclusively next to the target; one whose holder died is taken over
    after `stale_after` seconds. `mutate(data)` edits the parsed JSON in place.
    """
    path = Path(path)
    lock = path.with_name(path.name + ".lock")
    deadline = time.monotonic() + timeout
    while True:
        try:
            os.close(os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except (FileExistsError, PermissionError):
            # Windows reports "permission denied" (not "exists") while the
            # holder is deleting the lock: busy either way, try again.
            try:
                if time.time() - lock.stat().st_mtime > stale_after:
                    lock.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            if time.monotonic() > deadline:
                raise TimeoutError(f"could not lock {path.name} within {timeout:.0f}s")
            time.sleep(0.1 + random.random() * 0.3)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        mutate(data)
        write_json_atomic(path, data, indent=indent)
    finally:
        lock.unlink(missing_ok=True)


def row_name(r: dict) -> str:
    return str(r.get("Company") or r.get("company") or r.get("name") or "").strip()


def row_hq(r: dict) -> str:
    return str(r.get("Headquarters") or r.get("headquarters") or "").strip()


def row_website(r: dict) -> str:
    return str(r.get("Website") or r.get("website") or r.get("domain") or "").strip()


def domain_of(url: str) -> str:
    """Registrable domain of a website, or '' when there is no usable one."""
    raw = str(url or "").strip().lower()
    if not raw or " " in raw or "." not in raw:
        return ""
    if "//" not in raw:
        raw = "https://" + raw
    try:
        host = urlparse(raw).netloc.split("@")[-1].split(":")[0]
    except ValueError:
        return ""
    labels = [p for p in host.split(".") if p and p != "www"]
    if len(labels) < 2:
        return ""
    keep = 3 if len(labels) >= 3 and labels[-2] in _SECOND_LEVEL else 2
    dom = ".".join(labels[-keep:])
    return "" if dom in _PLATFORM_DOMAINS else dom


def norm_name(name: str) -> str:
    # Dotted legal forms ("S.p.A.", "S.r.l.", "S.A.", "B.V.") become one word
    # first, so they match the suffix list like "SpA" / "Srl" / "SA" / "BV".
    text = re.sub(r"\b(?:[A-Za-z]\.){1,3}[A-Za-z]\.?(?=\s|$|,)",
                  lambda m: m.group(0).replace(".", ""), str(name or ""))
    # Accents folded, not dropped: "Indústria" and "Industria" are one word
    # ("ind stria" never matched its unaccented spelling).
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    text = re.sub(r"\bS\s*/\s*A\b", "SA", text, flags=re.I)  # "S/A" = "SA"
    words = re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split()
    core = [w for w in words if w not in _NAME_SUFFIXES]
    return " ".join(core or words)


def dedupe_companies(
    verified: Iterable[dict], prefer: Iterable[str] | dict[str, int] = ()
) -> tuple[list[str], dict[str, list[str]]]:
    """One representative name per real company.

    Two names are the same company when they share a registrable website
    domain, or normalise to the same name once legal suffixes are dropped
    ("Alertgy" / "Alertgy, Inc."). Returns (representatives, groups) where
    groups maps each representative to every name folded into it.

    Representative choice: the name with the best `prefer` priority (a dict
    of name -> tier, lower wins -- e.g. 0 = full evidence, 1 = pinned,
    2 = score only; a plain iterable means tier 0 for all), then one with a
    known HQ, then the shortest name -- a parent ("Abbott Laboratories") is
    usually shorter than its own division ("Abbott Diabetes Care Inc.").
    """
    tier = dict(prefer) if isinstance(prefer, dict) else {n: 0 for n in prefer}
    rows: dict[str, dict] = {}
    for r in verified:
        n = row_name(r)
        if not n:
            continue
        if n not in rows or (row_hq(r) and not row_hq(rows[n])):
            rows[n] = r

    parent: dict[str, str] = {n: n for n in rows}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    by_key: dict[str, str] = {}
    for n, r in rows.items():
        for key in (f"d:{domain_of(row_website(r))}", f"n:{norm_name(n)}"):
            if key in ("d:", "n:"):
                continue
            if key in by_key:
                union(by_key[key], n)
            else:
                by_key[key] = n

    members: dict[str, list[str]] = {}
    for n in rows:
        members.setdefault(find(n), []).append(n)

    reps: list[str] = []
    groups: dict[str, list[str]] = {}
    for names in members.values():
        rep = sorted(
            names,
            key=lambda n: (tier.get(n, 99), not row_hq(rows[n]), len(n), n),
        )[0]
        reps.append(rep)
        groups[rep] = sorted(names)
    reps.sort()
    return reps, groups


def load_evidence(out_dir: Path) -> dict[str, dict[str, dict[str, Any]]]:
    """Union of every param_detail_prescored*.json sidecar per company.

    Per parameter, a copy that carries its assessed_on reasoning beats one
    that does not, whichever sidecar it came from.
    """
    merged: dict[str, dict[str, dict[str, Any]]] = {}
    for side in sorted(Path(out_dir).glob("param_detail_prescored*.json")):
        try:
            part = json.loads(side.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - half-written sidecar skipped
            continue
        for name, rec in part.items():
            dest = merged.setdefault(name, {"x": {}, "y": {}})
            for axis in ("x", "y"):
                for p, v in ((rec.get(axis) or {}).get("parameters") or {}).items():
                    if not isinstance(v, dict) or v.get("score") is None:
                        continue
                    cur = dest[axis].get(p)
                    if cur is None or (not cur.get("assessed_on") and v.get("assessed_on")):
                        dest[axis][p] = v
    return merged


def evidence_gaps(
    evidence: dict, names: Iterable[str], x_params: list[str], y_params: list[str]
) -> dict[str, dict[str, list[str]]]:
    """{name: {"missing": [...], "no_reasoning": [...]}} -- only names with a gap."""
    gaps: dict[str, dict[str, list[str]]] = {}
    for n in names:
        rec = evidence.get(n) or {"x": {}, "y": {}}
        missing, no_reason = [], []
        for axis, params in (("x", x_params), ("y", y_params)):
            for p in params:
                v = rec[axis].get(p)
                if v is None:
                    missing.append(p)
                elif not v.get("assessed_on") or not v.get("evidence"):
                    no_reason.append(p)
        if missing or no_reason:
            gaps[n] = {"missing": missing, "no_reasoning": no_reason}
    return gaps


PART_ASKED_FILE = "part_fill_asked.json"


def part_gaps(
    evidence: dict, names: Iterable[str], x_params: list[str], y_params: list[str],
    asked: Iterable[str] = (),
) -> dict[str, list[list[str]]]:
    """{name: [[axis, parameter, part], ...]} -- parts of a multi-part parameter
    ("Revenue & Growth" -> growth) that no supporting point covers yet and that
    were not asked about already (each part is asked once per market: a part
    with nothing documented stays as it is). Owner 2026-10-15."""
    from vendor_intel.quadrant.ai_mode_scorer import uncovered_parts

    done = set(asked)
    out: dict[str, list[list[str]]] = {}
    for n in names:
        rec = evidence.get(n) or {"x": {}, "y": {}}
        for axis, params in (("x", x_params), ("y", y_params)):
            for p in params:
                v = rec[axis].get(p)
                if not v:
                    continue
                claims = [str(e.get("claim") or "") for e in v.get("evidence") or [] if isinstance(e, dict)]
                for part in uncovered_parts(p, claims):
                    if f"{n}|{p}|{part}" not in done:
                        out.setdefault(n, []).append([axis, p, part])
    return out


def is_complete(evidence: dict, name: str, x_params: list[str], y_params: list[str]) -> bool:
    return name not in evidence_gaps(evidence, [name], x_params, y_params)


def load_overall_only(out_dir: Path) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for side in sorted(Path(out_dir).glob("overall_only_shard*.json")):
        try:
            out.update(json.loads(side.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            continue
    return out


def rank_score(
    name: str,
    evidence: dict,
    overall_only: dict,
    x_params: list[str],
    y_params: list[str],
) -> float | None:
    """Best available raw Overall for ranking: full evidence mean first,
    then a fresh Overall-only score. None when the company has neither."""
    if is_complete(evidence, name, x_params, y_params):
        rec = evidence[name]
        xs = [rec["x"][p]["score"] for p in x_params]
        ys = [rec["y"][p]["score"] for p in y_params]
        return (sum(xs) / len(xs) + sum(ys) / len(ys)) / 2
    if name in overall_only and overall_only[name].get("overall") is not None:
        return float(overall_only[name]["overall"])
    return None


def axis_xy(
    name: str,
    evidence: dict,
    overall_only: dict,
    x_params: list[str],
    y_params: list[str],
) -> tuple[float, float] | None:
    """(X, Y) for selection: full-evidence means first, then the quick
    scorecard scores. None when the company has neither."""
    if is_complete(evidence, name, x_params, y_params):
        rec = evidence[name]
        xs = [rec["x"][p]["score"] for p in x_params]
        ys = [rec["y"][p]["score"] for p in y_params]
        return sum(xs) / len(xs), sum(ys) / len(ys)
    rec = overall_only.get(name) or {}
    if rec.get("x_score") is not None and rec.get("y_score") is not None:
        return float(rec["x_score"]), float(rec["y_score"])
    return None


def quadrant_of(x: float, y: float, mid_x: float, mid_y: float) -> str:
    """Same rule as rating_map: Leaders high/high, Challengers low X high Y,
    Trailblazers high X low Y, Emerging Players low/low."""
    if x >= mid_x:
        return "Leaders" if y >= mid_y else "Trailblazers"
    return "Challengers" if y >= mid_y else "Emerging Players"


def select_top_by_quadrant(
    xy: dict[str, tuple[float, float]], top_n: int = 20
) -> list[str]:
    """The chart's Top N: the best top_n/4 companies (by Overall = mean of
    X and Y) from EACH quadrant of the scored pool.

    Quadrants are split at the pool's median X and median Y, so every
    quadrant has companies to choose from whatever the market's score
    level. Ranking the whole pool by Overall alone would fill the chart
    with the strongest all-rounders and leave Challengers / Trailblazers /
    Emerging Players empty. A quadrant with fewer than its share gives its
    free slots to the best remaining companies overall.
    """
    names = sorted(xy)
    overall = {n: (xy[n][0] + xy[n][1]) / 2 for n in names}
    by_overall = sorted(names, key=lambda n: (-overall[n], n))
    if len(names) <= top_n:
        return by_overall
    xs = sorted(v[0] for v in xy.values())
    ys = sorted(v[1] for v in xy.values())
    mid = len(xs) // 2
    mid_x = xs[mid] if len(xs) % 2 else (xs[mid - 1] + xs[mid]) / 2
    mid_y = ys[mid] if len(ys) % 2 else (ys[mid - 1] + ys[mid]) / 2

    share = top_n // 4
    picked: list[str] = []
    for quad in ("Leaders", "Challengers", "Trailblazers", "Emerging Players"):
        members = [n for n in by_overall if quadrant_of(*xy[n], mid_x, mid_y) == quad]
        picked += members[:share]
    for n in by_overall:  # quadrants short of their share
        if len(picked) >= top_n:
            break
        if n not in picked:
            picked.append(n)
    return sorted(picked, key=lambda n: (-overall[n], n))
