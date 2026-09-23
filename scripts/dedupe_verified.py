#!/usr/bin/env python3
"""Collapse verified rows that are the SAME company under name variants.

Name-based de-duplication cannot catch these: "CB Geophysical LLC" and
"CB Geophysical Solutions Limited" share no exact key, "PGS" and "TGS" are
one company post-merger, and "WesternGeco" is a brand of SLB. What they DO
share is the official website resolved during gap-fill, so the domain is
the grouping key here.

Within a group the survivor is chosen, in order:
  1. the row that already carries scored parameter detail (never throw away
     work that has been paid for),
  2. the shortest name that is a prefix of the others (the plain corporate
     name, not a regional office or legal-suffix variant),
  3. the longest name (most specific), as a stable fallback.

Everything dropped is recorded in `deduped_into` on the survivor, so the
merge is auditable and reversible rather than a silent deletion.

    .\\.venv\\Scripts\\python.exe scripts\\dedupe_verified.py ^
        --market "Marine Seismic Data Processing Services Market" ^
        --country global --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

# Company names here carry Polish, Portuguese and Estonian diacritics, which
# the Windows console codepage cannot encode -- printing the plan crashed on
# "Geofizyka Toruń" before writing anything.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _name(r: dict) -> str:
    return str(r.get("Company") or r.get("company") or r.get("name") or "").strip()


def _domain(r: dict) -> str:
    url = str(r.get("website") or "").strip()
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _norm(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


# Legal-form and regional tokens. A name carrying these is a variant of the
# company's plain name ("CB Geophysical Solutions Limited" / "BGP Norway
# Branch"), not the name a reader recognises it by, so it loses the pick.
_NOISE_TOKENS = {
    "ltd", "ltda", "limited", "llc", "lp", "llp", "inc", "incorporated",
    "gmbh", "co", "kg", "sa", "sas", "spa", "srl", "as", "asa", "ab", "nv",
    "bv", "plc", "pty", "pte", "sdn", "bhd", "oy", "ou", "oü", "ag", "se",
    "jsc", "ojsc", "pjsc", "corporation", "corp", "company", "holding",
    "holdings", "group", "services", "international", "branch", "hub",
    "africa", "europe", "asia", "pacific", "americas", "china", "india",
    "norway", "brazil", "australia", "houston", "uk", "usa",
}


def _noise_score(name: str) -> int:
    """How many legal-form / regional tokens a name carries."""
    tokens = [t.strip(".,()&").lower() for t in name.split()]
    return sum(1 for t in tokens if t in _NOISE_TOKENS)


# A handful of groups where the parent's name is not a stem of any variant,
# so no ordering rule finds it: Viridien's group contains "ANR" and CGG
# legacy names, Fugro's contains its Gardline subsidiary. Naming the
# survivor outright is honest and auditable; inventing a rule that happens
# to pick it would not generalise anyway.
_PREFERRED_BY_DOMAIN = {
    "viridien.com": "Viridien SA",
    "viridiengroup.com": "Viridien",
    "fugro.com": "Fugro N.V.",
}


def _pick_survivor(rows: list[dict], scored: set[str], domain: str = "") -> dict:
    preferred = _PREFERRED_BY_DOMAIN.get(domain)
    if preferred:
        for r in rows:
            if _name(r) == preferred:
                return r
    # 1. A row that already has scored parameter detail wins outright:
    #    never throw away work that has already been paid for.
    for r in rows:
        if _name(r) in scored:
            return r
    names = [n for n in {_name(r) for r in rows} if n]
    if names:
        # 2. Prefer the name the OTHERS are built from. "TGS" is the stem of
        #    "TGS ASA" / "TGS Africa" / "TGS Asia Pacific", while "PGS" is
        #    the stem of nothing in that group -- picking on brevity alone
        #    kept the acquired company (PGS) over the acquirer (TGS), and
        #    kept regional offices ("Shearwater APAC", "BGP Offshore") over
        #    the parent. Ties fall back to fewest legal-form tokens, then
        #    to the shortest name.
        def _stem_count(n: str) -> int:
            key = _norm(n)
            return sum(1 for o in names if o != n and _norm(o).startswith(key))

        best = sorted(
            names, key=lambda n: (-_stem_count(n), _noise_score(n), len(n))
        )[0]
        for r in rows:
            if _name(r) == best:
                return r
    return rows[0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--market", required=True)
    ap.add_argument("--country", default="global")
    ap.add_argument("--out-dir", default="")
    ap.add_argument(
        "--apply", action="store_true",
        help="write the change; without it this only prints the plan",
    )
    args = ap.parse_args()

    from vendor_intel.pipeline.web_expand import default_output_dir

    out_dir = Path(args.out_dir) if args.out_dir else Path(
        default_output_dir(args.market, args.country)
    )
    ckpt_path = out_dir / "chatgpt_checkpoint_batch_all.json"
    state = json.loads(ckpt_path.read_text(encoding="utf-8"))
    data = state.setdefault("data", {})
    verified = data.get("verified") or []

    # Companies that already have parameter detail must survive their group.
    scored: set[str] = set()
    for side in out_dir.glob("param_detail_prescored*.json"):
        try:
            part = json.loads(side.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        for name, rec in part.items():
            if (rec.get("x") or {}).get("parameters") and (rec.get("y") or {}).get("parameters"):
                scored.add(name)

    groups: dict[str, list[dict]] = defaultdict(list)
    no_domain: list[dict] = []
    for r in verified:
        dom = _domain(r)
        if dom:
            groups[dom].append(r)
        else:
            no_domain.append(r)

    kept: list[dict] = []
    collapsed = 0
    for dom, rows in groups.items():
        if len(rows) == 1:
            kept.append(rows[0])
            continue
        survivor = _pick_survivor(rows, scored, dom)
        dropped = [_name(r) for r in rows if r is not survivor and _name(r)]
        if dropped:
            survivor = dict(survivor)
            survivor["deduped_into"] = dropped
            collapsed += len(dropped)
        kept.append(survivor)
        print(f"{dom}: keep {_name(survivor)!r}  (dropped {len(dropped)})")
        for d in dropped:
            print(f"      - {d}")
    kept.extend(no_domain)

    print()
    print(f"verified before      : {len(verified)}")
    print(f"rows collapsed away  : {collapsed}")
    print(f"rows with no website : {len(no_domain)}")
    print(f"verified after       : {len(kept)}")

    if not args.apply:
        print("\n(dry run — pass --apply to write)")
        return 0

    data["verified"] = kept
    ckpt_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {ckpt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
