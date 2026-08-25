"""Market-agnostic value-chain segment filter and parent/family dedup.

axis_define.py writes X-axis parameters that describe ONE type of player per
market — e.g. "Liquefaction Capacity & Utilization" describes a company that
directly OPERATES that capability, not one that ships, trades, or buys the
finished product. Left unfiltered, discovery pulls in every player adjacent
to a market (distributors, traders, shippers, buyers, diversified investors)
alongside the direct operators the axis was written to measure, and scores
all of them on capability most of them don't hold.

This module asks one question per company, reusing evidence already
collected (no new web search, same evidence_snapshot / company_kb text the
rest of quadrant scoring uses): does this company directly own/operate the
capability the market's X-axis parameters describe? It also collapses
obvious parent/subsidiary duplicates — the same corporate family listed
under separate "brand" names (a producer and its own trading arm, a parent
and its wholly-owned subsidiary) — down to one representative row, so one
company can't occupy two quadrants at once.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

_SYSTEM = """You classify ONE company's role in a specific market's value chain, and
whether its name is even a real, specific company at all.

You are given:
- The market name and its X-axis scoring parameters (these describe what a
  DIRECT OPERATOR of this market's core capability looks like).
- Evidence text about the company.

First — is this name a REAL, SPECIFIC, identifiable company? Recall/discovery
steps sometimes fabricate plausible-sounding entries instead of admitting they
found no more real companies. The tell: the name is just the market's own
category term (in English or translated into another language) plus a
region/city/acronym suffix, with NO evidence of a distinct business beyond
that pattern — e.g. for a "Flexible Packaging" market: "Embalagens Flexíveis
do Sul (EFS)", "Flexible Packaging Northeast", "Embalagens Flexíveis Ltda."
None of these describe one particular company; they read like a template
filled in with a region name. A real regional company usually has a specific
founding story, named product line, or ownership detail in the evidence — a
generic label repeating the category term does not.

Second, if it IS a real company: does it directly own/operate the capability
the X parameters describe (a "direct operator"), or is it an adjacent/
downstream player — a distributor, trader/marketer, shipper/logistics
provider, buyer/importer/utility, or a diversified investor holding only a
minority equity stake with no operational control?

Also: if the evidence suggests this company is itself a subsidiary, brand,
trading arm, or specific project/terminal of another company (its "parent"),
name that parent's most commonly used company name exactly as it would
appear elsewhere in this same list. Leave blank if independent or no parent
is named in the evidence.

Return JSON only:
{
  "is_generic_placeholder": true/false,
  "is_direct_operator": true/false,
  "parent_family": "<parent company name, or empty string>",
  "reason": "<one short sentence>"
}

If is_generic_placeholder is true, is_direct_operator does not matter — the
row gets dropped either way.
"""


def _user_prompt(*, market: str, x_feats: list[str], brand: str, kb_text: str) -> str:
    feats = "; ".join(x_feats)
    return (
        f"Market: {market}\n"
        f"X-axis parameters (what a direct operator does): {feats}\n\n"
        f"Company: {brand}\n"
        f"Evidence:\n{kb_text[:2500]}\n"
    )


def classify_operator_segment(
    *,
    market: str,
    x_feats: list[str],
    brand: str,
    kb_text: str,
    client: Any,
    model: str | None = None,
) -> dict[str, Any]:
    """One LLM call: is `brand` a real, specific company, and if so, is it a direct operator?

    Fails open (keeps the company, assumes real + operator) on any LLM error,
    so a transient failure can't silently drop a real company out of a report.
    """
    try:
        raw = client.complete_json(
            _SYSTEM,
            _user_prompt(market=market, x_feats=x_feats, brand=brand, kb_text=kb_text),
            model=model,
            max_tokens=400,
        )
    except Exception as exc:
        return {
            "is_generic_placeholder": False,
            "is_direct_operator": True,
            "parent_family": "",
            "reason": f"classification failed ({exc}), kept by default",
        }
    data = raw if isinstance(raw, dict) else {}
    return {
        "is_generic_placeholder": bool(data.get("is_generic_placeholder", False)),
        "is_direct_operator": bool(data.get("is_direct_operator", True)),
        "parent_family": str(data.get("parent_family") or "").strip(),
        "reason": str(data.get("reason") or "").strip(),
    }


async def classify_operator_segment_async(**kwargs: Any) -> dict[str, Any]:
    return await asyncio.to_thread(classify_operator_segment, **kwargs)


def dedupe_by_family(
    rows: list[dict[str, Any]],
    classifications: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Collapse companies sharing a parent/subsidiary family to one representative row.

    Groups on two signals: (a) the LLM's parent_family naming another brand
    already in this cohort, (b) one brand name being a whole-word prefix of
    another's (e.g. "Woodside" inside "Woodside Louisiana LNG"). Within a
    group, keeps the shortest brand name (usually the parent/flagship),
    preferring a direct operator over a non-operator when lengths tie.
    """
    n = len(rows)
    if n <= 1:
        return list(rows)
    brand_of = [str(r.get("brand") or r.get("company") or "").strip() for r in rows]
    lower_brands = [b.lower() for b in brand_of]

    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    for i in range(n):
        fam_l = classifications[i].get("parent_family", "").lower().strip()
        if not fam_l:
            continue
        for j in range(n):
            if i != j and (fam_l == lower_brands[j] or fam_l in lower_brands[j]):
                union(i, j)

    for i in range(n):
        for j in range(i + 1, n):
            a, b = lower_brands[i], lower_brands[j]
            if not a or not b or a == b:
                continue
            shorter, longer = (a, b) if len(a) < len(b) else (b, a)
            if not shorter:
                continue
            if re.match(rf"^{re.escape(shorter)}\b", longer):
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    keep: list[dict[str, Any]] = []
    for idxs in groups.values():
        if len(idxs) == 1:
            keep.append(rows[idxs[0]])
            continue
        idxs_sorted = sorted(
            idxs,
            key=lambda i: (
                0 if classifications[i]["is_direct_operator"] else 1,
                len(brand_of[i]),
            ),
        )
        keep.append(rows[idxs_sorted[0]])
    return keep


async def filter_direct_operators(
    rows: list[dict[str, Any]],
    *,
    market: str,
    x_feats: list[str],
    kb_texts: list[str],
    client: Any,
    model: str | None = None,
    concurrency: int = 8,
) -> list[dict[str, Any]]:
    """Classify every row, drop fabricated placeholders and adjacent/downstream
    players, dedupe parent/subsidiary families.

    Rows already labeled "Marketer" (by market_relevance.py's own Brand/
    Marketer classification) are exempt from the is_direct_operator check —
    a Marketer is, by definition, a distributor/reseller, so failing the
    "does it directly operate the market's core capability" test is
    expected, not a reason to drop it. They still go through the
    is_generic_placeholder check and family-dedup like everyone else.

    `rows` and `kb_texts` must be the same length and index-aligned (kb_texts[i]
    is the evidence text for rows[i]).
    """
    if not rows:
        return []
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _one(i: int) -> dict[str, Any]:
        async with sem:
            brand = str(rows[i].get("brand") or rows[i].get("company") or "")
            return await classify_operator_segment_async(
                market=market,
                x_feats=x_feats,
                brand=brand,
                kb_text=kb_texts[i],
                client=client,
                model=model,
            )

    classifications = await asyncio.gather(*[_one(i) for i in range(len(rows))])
    operators = []
    for r, c in zip(rows, classifications):
        if c.get("is_generic_placeholder"):
            continue
        is_marketer = str(r.get("commercial_role") or "").strip().lower() == "marketer"
        if c["is_direct_operator"] or is_marketer:
            operators.append((r, c))
    if not operators:
        return []
    kept_rows = [r for r, _c in operators]
    kept_classifications = [c for _r, c in operators]
    return dedupe_by_family(kept_rows, kept_classifications)
