"""Pure, market-agnostic logic behind scripts/run_quadrant_pipeline.py.

Nothing here launches a browser or names a market: dedupe, evidence merge,
gap audit and ranking all work from the checkpoint + sidecar files of
whatever market is being run, so every market goes through the same steps.
"""
from __future__ import annotations

import json
import re
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
}


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
    words = re.sub(r"[^a-z0-9 ]+", " ", str(name or "").lower()).split()
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
