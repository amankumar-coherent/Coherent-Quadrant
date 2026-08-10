"""Tell brand owners apart from the supply chain behind them.

The classifier assigns a value-chain role — Manufacturer, Distributor, Supplier.
That answers "what does this company do", but not "is this a company a buyer
chooses". In the Rupture Disc Market it labelled 82 companies `Manufacturer`
and zero as `Brand`, yet Fike, BS&B and Continental Disc plainly are brands:
they sell finished, branded product under their own name. A contract
manufacturer and a steel-alloy supplier carry the same `Manufacturer` /
`Supplier` label and are not.

The distinction is a separate question from the role, so it gets its own pass:

    Brand   — sells finished product under its own name, chosen by buyers
    Marketer— markets and sells the product without making it
    Solution Developer — builds the technology/solution rather than reselling
    (none)  — contract manufacturer, component or material supplier, pure reseller

A company keeps its value-chain role; this ADDS the commercial role. That matters
because a quadrant of "who competes for the buyer" should contain brands, while a
landscape report still needs the whole chain.
"""
from __future__ import annotations

import json
from typing import Any

_SYSTEM = """You classify a company's COMMERCIAL role in a market, separately from its
place in the value chain.

Return one of:
- "Brand": sells finished, branded product in this market under its own name. A buyer
  can choose it. Most established manufacturers of a finished product ARE brands.
- "Marketer": markets and sells the product but does not make it (own-label sellers,
  brand licensors).
- "Solution Developer": builds the technology, software or engineered solution itself
  rather than reselling someone else's.
- "": none of the above — a contract manufacturer making others' products, a raw
  material or component supplier, or a pure reseller/distributor of other brands.

Judge from the evidence. A distributor that also sells its OWN branded line is a Brand.
A famous parent company that does not sell in THIS market is not.

Return JSON only: {"items":[{"i":<index>,"commercial_role":"<one of the above>","confidence":0.0-1.0}]}"""


def _summary(row: dict[str, Any]) -> str:
    for key in ("company_summary", "summary", "role_description", "Functionality"):
        text = str(row.get(key) or "").strip()
        if text:
            return text[:600]
    return ""


def classify(
    rows: list[dict[str, Any]],
    market: str,
    *,
    settings: Any = None,
    client: Any = None,
    batch_size: int = 10,
    min_confidence: float = 0.6,
) -> int:
    """Tag each row with ``commercial_role``. Returns how many got one.

    Best-effort: without an LLM nothing is tagged, and a failed batch leaves those
    rows untagged rather than guessing.
    """
    if client is None:
        try:
            from vendor_intel.clients.claude import ClaudeClient

            client = ClaudeClient(settings) if settings is not None else None
        except Exception:
            client = None
    if client is None or not getattr(client, "available", False):
        return 0

    items = [
        {"i": i, "name": str(r.get("company_raw") or r.get("company") or ""),
         "role": str(r.get("role") or ""), "summary": _summary(r)}
        for i, r in enumerate(rows)
    ]
    tagged = 0
    for start in range(0, len(items), batch_size):
        batch = items[start : start + batch_size]
        user = f"MARKET: {market}\n\nCOMPANIES:\n" + "\n".join(
            json.dumps(b, ensure_ascii=False) for b in batch
        )
        try:
            out = client.complete_json(
                _SYSTEM, user,
                model=getattr(settings, "classifier_model", None),
                max_tokens=1200,
            )
        except Exception as exc:
            print(f"  [brand] batch failed: {exc}", flush=True)
            continue
        arr = out.get("items") if isinstance(out, dict) else out
        for entry in arr or []:
            try:
                idx = int(entry.get("i"))
                conf = float(entry.get("confidence") or 0)
            except (TypeError, ValueError):
                continue
            role = str(entry.get("commercial_role") or "").strip()
            if not role or conf < min_confidence or not (0 <= idx < len(rows)):
                continue
            rows[idx]["commercial_role"] = role
            rows[idx]["commercial_role_confidence"] = round(conf, 3)
            tagged += 1
    return tagged


def commercial_roles(row: dict[str, Any]) -> set[str]:
    """Every commercial role this row carries, including ones the value-chain
    role already implies (an explicitly-labelled Brand stays a Brand)."""
    from vendor_intel.pipeline.role_rules import roles_of

    out = {r for r in roles_of(row) if r in {"Brand", "Marketer", "Solution Developer"}}
    tag = str(row.get("commercial_role") or "").strip()
    if tag:
        out.add(tag)
    return out


def filter_to_commercial(
    rows: list[dict[str, Any]], keep: set[str] | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split into (buyer-facing companies, supply chain)."""
    keep = keep or {"Brand", "Marketer", "Solution Developer"}
    kept, dropped = [], []
    for row in rows:
        if commercial_roles(row) & keep:
            kept.append(row)
        else:
            dropped.append(row)
    return kept, dropped
