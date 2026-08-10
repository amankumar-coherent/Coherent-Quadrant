"""Collapse SEO doorway networks — one operator wearing fifty domains.

A real run exported 53 of 191 rows as separate "companies": ``Rupture Discs
Argentina`` on ``rupturediscsargentina.com``, ``Rupture Discs Bahrain`` on
``rupturediscsbahrain.com``, and so on through fifty countries. Every existing
gate passed them, and correctly so on the evidence each one presents: the entity
gate saw a real registered domain, the classifier saw genuine on-topic
rupture-disc content, and the export gate saw market fit. Nothing in the pipeline
was looking *across* rows, which is the only level at which the pattern exists.

The fix needs two independent signals, because either alone over-fires:

1. **Shared domain stem** — ``rupturedisc*`` across N domains. On its own this
   would merge genuinely distinct firms in a market whose name is a common word
   (``rupturediscs.com`` and ``rupturediscsolutions.com`` may be unrelated).
2. **Names differing only by a place** — strip the shared leading words and what
   remains is "Argentina", "Bahrain", "Kenya". This is what separates a doorway
   network from three real companies with similar names.

Requiring both, plus a minimum cluster size, keeps the filter conservative: it
would rather leave a doorway row in than drop a real company.
"""
from __future__ import annotations

import re
from typing import Any

MIN_CLUSTER = 3        # two similar domains is a coincidence, not a network
MIN_STEM_CHARS = 8     # shorter prefixes collide by accident
PLACE_RATIO = 0.6      # share of a cluster whose name-tail is a bare place

_PLACES = {
    # countries and territories that show up as doorway page suffixes
    "argentina", "australia", "austria", "bahrain", "bangladesh", "belgium",
    "bolivia", "brazil", "bulgaria", "canada", "chile", "china", "colombia",
    "croatia", "cyprus", "czech republic", "denmark", "ecuador", "egypt",
    "estonia", "finland", "france", "germany", "ghana", "greece", "hong kong",
    "hungary", "iceland", "india", "indonesia", "iran", "iraq", "ireland",
    "israel", "italy", "japan", "jordan", "kazakhstan", "kenya", "korea",
    "kuwait", "latvia", "lebanon", "lithuania", "luxembourg", "malaysia",
    "malta", "mexico", "morocco", "netherlands", "new zealand", "nigeria",
    "norway", "oman", "pakistan", "peru", "philippines", "poland", "portugal",
    "qatar", "romania", "russia", "saudi arabia", "serbia", "singapore",
    "slovakia", "slovenia", "south africa", "south korea", "spain", "sri lanka",
    "sweden", "switzerland", "taiwan", "thailand", "tunisia", "turkey", "uae",
    "uganda", "ukraine", "united arab emirates", "united kingdom", "uruguay",
    "usa", "uk", "venezuela", "vietnam", "zambia", "zimbabwe",
    # regions
    "africa", "asia", "asia pacific", "apac", "emea", "europe", "latin america",
    "middle east", "north america", "oceania", "south america", "scandinavia",
    "gcc", "benelux", "worldwide", "global", "international",
}


def domain_stem(domain: str) -> str:
    """First DNS label, letters only. ``rupturediscs.com.au`` -> ``rupturediscs``."""
    d = str(domain or "").strip().lower()
    d = d.removeprefix("http://").removeprefix("https://").removeprefix("www.")
    d = d.split("/")[0].split(".")[0]
    return re.sub(r"[^a-z]", "", d)


def _common_prefix(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def ends_with_place(name: str) -> str:
    """The trailing place in a name, or "" — ``Rupture Discs Bahrain`` -> ``bahrain``.

    Deliberately checks the *tail* rather than stripping a prefix the cluster has
    in common. A shared-prefix approach broke on the real data: one member was
    ``Rupture Disc Solutions`` (singular), which cut the common prefix to a single
    word and left tails like ``"discs australia"`` that matched no place.
    """
    words = re.sub(r"[^a-z0-9 ]", " ", str(name or "").lower()).split()
    for n in (3, 2, 1):  # "united arab emirates" before "emirates"
        if len(words) > n:  # never let the place BE the whole name
            tail = " ".join(words[-n:])
            if tail in _PLACES:
                return tail
    return ""


def find_clusters(rows: list[dict[str, Any]]) -> list[list[int]]:
    """Row-index clusters that share a long domain stem. Signal 1 only."""
    indexed = [(i, domain_stem(r.get("domain") or r.get("website"))) for i, r in enumerate(rows)]
    indexed = [(i, s) for i, s in indexed if len(s) >= MIN_STEM_CHARS]
    indexed.sort(key=lambda x: x[1])

    clusters: list[list[int]] = []
    current: list[int] = []
    for pos, (idx, stem) in enumerate(indexed):
        if not current:
            current = [idx]
            continue
        prev_stem = indexed[pos - 1][1]
        if _common_prefix(prev_stem, stem) >= MIN_STEM_CHARS:
            current.append(idx)
        else:
            if len(current) >= MIN_CLUSTER:
                clusters.append(current)
            current = [idx]
    if len(current) >= MIN_CLUSTER:
        clusters.append(current)
    return clusters


def is_doorway_cluster(rows: list[dict[str, Any]], cluster: list[int]) -> bool:
    """Signal 2: are these the same name repeated per country?"""
    names = [str(rows[i].get("company") or "") for i in cluster]
    placey = sum(1 for n in names if ends_with_place(n))
    return placey / max(len(names), 1) >= PLACE_RATIO


def _keep_index(rows: list[dict[str, Any]], cluster: list[int]) -> int:
    """Keep the canonical member: best evidence, then shortest name."""
    def score(i: int) -> tuple[float, int]:
        r = rows[i]
        q = float(r.get("quality_score") or 0) + float(r.get("confidence") or 0)
        return (q, -len(str(r.get("company") or "")))

    return max(cluster, key=score)


def filter_doorways(
    rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (kept, dropped). One canonical row survives each doorway network."""
    drop: dict[int, str] = {}
    for cluster in find_clusters(rows):
        if not is_doorway_cluster(rows, cluster):
            continue
        keep = _keep_index(rows, cluster)
        canonical = str(rows[keep].get("company") or "")
        for i in cluster:
            if i != keep:
                drop[i] = f"doorway_network:{canonical}"

    kept, dropped = [], []
    for i, row in enumerate(rows):
        if i in drop:
            dropped.append({**row, "export_reject": drop[i]})
        else:
            kept.append(row)
    return kept, dropped


def dedupe_name_variants(
    rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Collapse "Parker Hannifin" / "Parker Hannifin Corporation".

    The region merge keys on domain, so the same firm reached the export twice
    when two countries recorded it under different domains (or none). Legal-form
    suffixes are already stripped by ``company_dedupe_key``.
    """
    from vendor_intel.utils.domains import company_dedupe_key

    best: dict[str, int] = {}
    drop: dict[int, str] = {}
    for i, row in enumerate(rows):
        key = company_dedupe_key(str(row.get("company") or ""))
        if not key:
            continue
        if key not in best:
            best[key] = i
            continue
        prev = best[key]
        q_new = float(row.get("quality_score") or 0) + float(row.get("confidence") or 0)
        q_old = float(rows[prev].get("quality_score") or 0) + float(rows[prev].get("confidence") or 0)
        loser, winner = (prev, i) if q_new > q_old else (i, prev)
        best[key] = winner
        drop[loser] = f"duplicate_name:{rows[winner].get('company')}"

    kept, dropped = [], []
    for i, row in enumerate(rows):
        if i in drop:
            dropped.append({**row, "export_reject": drop[i]})
        else:
            kept.append(row)
    return kept, dropped
