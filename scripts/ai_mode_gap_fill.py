#!/usr/bin/env python3
"""Fill website / ownership / clean headquarters for specific rows via AI Mode.

For companies added from an operator-supplied list (tagged with a
`_source` marker) that only carry a name and a loose "Country / Region"
string -- no website, no verified single-city headquarters, no ownership.
Asks AI Mode directly, one small batch of companies at a time, and writes
the answers back onto the SAME row objects in the checkpoint's `recalled`
list (matched by company name), so downstream verify/scoring find the
completed rows already there.

    .\\.venv\\Scripts\\python.exe scripts\\ai_mode_gap_fill.py ^
        --market "Marine Seismic Data Processing Services Market" ^
        --country global --slot 41 --shard 0 --shards 4 ^
        --source-tag user_400_list --batch 8
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


def _row_name(r: dict) -> str:
    """Company name, whichever shape the row is in.

    Rows added from the user's 400-company file use lowercase keys
    (company/brand/headquarters); rows from the AI Mode discovery sweep use
    the pipeline's own PascalCase keys (Company/Market Offering/brand_name/
    Headquarters). Both need to go through the same gap-fill pass.
    """
    return str(r.get("company") or r.get("Company") or r.get("name") or "").strip()


def _row_hq(r: dict) -> str:
    return str(r.get("headquarters") or r.get("Headquarters") or "").strip()


def _row_hint(r: dict) -> str:
    return str(r.get("why_related") or r.get("Summary") or r.get("snippet") or "").strip()


def _build_brand_only_prompt(companies: list[dict]) -> tuple[str, str]:
    system = (
        "You research companies and identify the NAMED SERVICE, product "
        "line, platform or division each one delivers a specific service "
        "under. No invented values. Return compact JSON only: "
        '{"results":[{"company":"...","brand":"..."}]}'
    )
    lines = []
    for i, c in enumerate(companies):
        letter = chr(65 + i)
        hq = _row_hq(c)
        hint = _row_hint(c)
        bits = [f"headquartered in {hq}" if hq else ""]
        if hint:
            bits.append(f"known for: {hint}")
        about = f" ({'; '.join(b for b in bits if b)})" if any(bits) else ""
        lines.append(f"{letter}. {_row_name(c)}{about}")
    listing = "\n".join(lines)
    user = (
        f"For EACH of these {len(companies)} companies, identify their "
        f"BRAND for this Service Provider market:\n\n{listing}\n\n"
        "BRAND RULE:\n"
        "Brand is a REAL, OFFICIALLY-NAMED product, platform, service line "
        "or division -- a proper noun a customer or the company's own "
        "marketing would recognize as its own name, the kind you would see "
        "as a heading on the company's own website (e.g. company \"SLB\", "
        "brand \"WesternGeco\"; company \"TGS\", brand \"Spectrum Africa\"). "
        "It is a NAME, never a description of what the company does.\n\n"
        "DO NOT invent, guess, or generalize a brand. NEVER return a bare "
        "category word or generic service description as brand -- "
        '"Imaging", "Geophysical Services", "Seismic Processing", '
        '"Marine Services" and similar phrases are NOT brands, they are '
        "descriptions, and must never be returned even if they sound "
        "plausible. If you cannot name a REAL, VERIFIABLE, officially-named "
        "product/platform/division for a company, use the company's own "
        "name as brand instead -- that is the correct, expected answer for "
        "most companies here, not a fallback to avoid.\n\n"
        "Return one result per company, in the SAME order, using the exact "
        'company name given as "company".'
    )
    return system, user


def _build_prompt(companies: list[dict]) -> tuple[str, str]:
    system = (
        "You research companies and return their VERIFIED public details. "
        "No invented values. Return compact JSON only: "
        '{"results":[{"company":"...","brand":"...","website":"https://...",'
        '"headquarters":"City, Country","ownership":"...",'
        '"ownership_confidence":"high|medium|low"}]}'
    )
    lines = []
    for i, c in enumerate(companies):
        letter = chr(65 + i)
        hint = _row_hint(c)
        rough_hq = _row_hq(c)
        bits = [f"roughly headquartered in {rough_hq}" if rough_hq else ""]
        if hint:
            bits.append(f"known for: {hint}")
        about = f" ({'; '.join(b for b in bits if b)})" if any(bits) else ""
        lines.append(f"{letter}. {_row_name(c)}{about}")
    listing = "\n".join(lines)
    user = (
        f"For EACH of these {len(companies)} companies, find:\n\n{listing}\n\n"
        "FIELD RULES:\n"
        "- brand: this is a Service Provider market -- brand is a REAL, "
        "OFFICIALLY-NAMED product, platform, service line or division, a "
        "proper noun the company's own marketing uses as its own name "
        "(e.g. company \"SLB\", brand \"WesternGeco\"). It is a NAME, never "
        "a description. NEVER return a bare category word or generic "
        'service description ("Imaging", "Geophysical Services", "Seismic '
        'Processing" and similar are NOT brands). If you cannot name a '
        "REAL, VERIFIABLE, officially-named product/platform/division, use "
        "the company's own name as brand instead -- that is the correct, "
        "expected answer for most companies, not a fallback to avoid.\n"
        "- company: the clean legal/commercial entity name, with any "
        "parenthetical aliases, merger notes or slashes removed -- just the "
        "name itself.\n"
        "- website: the real official company domain. NEVER a LinkedIn, "
        "Bloomberg, Crunchbase or Wikipedia page. Leave empty if you cannot "
        "verify it.\n"
        '- headquarters: "City, Country" -- exactly ONE global HQ city, with '
        'the state for US companies (e.g. "Thousand Oaks, California, USA"). '
        'NEVER "Global", "Worldwide", a bare country, or a count of '
        "countries. If the company is a joint venture or a division and has "
        "no single headquarters of its own, use its parent/operating "
        "entity's HQ.\n"
        '- ownership: "Independent", or "Acquired by <Parent>" / '
        '"Subsidiary of <Parent>" using the real parent name, only when '
        "verifiable from an official source, acquisition announcement, "
        'regulatory filing or reputable business source. Otherwise '
        '"Independent".\n'
        "- ownership_confidence: high/medium/low, honestly.\n\n"
        "An empty string is CORRECT and preferred over a guess. Return one "
        "result per company, in the SAME order, using the exact company "
        'name given as "company".'
    )
    return system, user


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--market", required=True)
    ap.add_argument("--country", default="global")
    ap.add_argument("--slot", type=int, required=True)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument(
        "--source-tag", default="",
        help="only fill rows whose _source equals this value; empty means "
             "every row missing a website",
    )
    ap.add_argument("--out-dir", default="")
    ap.add_argument(
        "--refresh-brand-only", action="store_true",
        help="re-resolve brand for rows that already have a website (the "
             "discovery-sweep rows use Company/Market Offering/brand_name "
             "keys and got a bare trimmed-company-name brand, not a real "
             "named service/division) -- leaves website/headquarters/"
             "ownership untouched, only overwrites brand",
    )
    args = ap.parse_args()

    profile = ROOT / "data" / f"ai_mode_batch_{args.slot:02d}"
    os.environ["GOOGLE_AI_MODE_PROFILE_DIR"] = str(profile)
    os.environ["GOOGLE_AI_MODE_BROWSER"] = "chromium"
    os.environ["GOOGLE_AI_MODE_ENABLED"] = "true"

    from vendor_intel.pipeline.web_expand import default_output_dir
    from vendor_intel.scraping.google_ai_mode import ask as ai_ask
    from vendor_intel.scraping.google_ai_mode import parse_json_answer

    out_dir = Path(args.out_dir) if args.out_dir else Path(default_output_dir(args.market, args.country))
    ckpt_path = out_dir / "chatgpt_checkpoint_batch_all.json"
    if not ckpt_path.exists():
        print(f"ERROR: no checkpoint at {ckpt_path}", file=sys.stderr)
        return 2

    state = json.loads(ckpt_path.read_text(encoding="utf-8"))
    data = state.setdefault("data", {})
    recalled = data.get("recalled") or []

    def _needs_fill(r: dict) -> bool:
        if args.source_tag and r.get("_source") != args.source_tag:
            return False
        if args.refresh_brand_only:
            # These rows already have a website; that is what makes them
            # eligible for the brand-only pass, not a reason to skip them.
            return bool(str(r.get("website") or "").strip())
        return not str(r.get("website") or "").strip()

    targets = [r for r in recalled if _needs_fill(r)]
    my_targets = targets[args.shard::args.shards]
    print(f"shard {args.shard}/{args.shards}: {len(my_targets)} companies "
          f"of {len(targets)} needing fill ({len(recalled)} total rows)")

    # Sidecar per shard: several shards writing the SAME checkpoint with a
    # non-atomic read-modify-write would drop each other's fills. Each shard
    # writes {company_name: {website, headquarters, ownership, ...}} to its
    # own file; merge_gap_fill.py applies them all to the checkpoint once
    # every shard is done.
    suffix = "_brand" if args.refresh_brand_only else ""
    side_path = out_dir / f"gap_fill_shard{args.shard}{suffix}.json"
    filled: dict[str, dict] = {}
    if side_path.exists():
        try:
            filled = json.loads(side_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            filled = {}
    my_targets = [c for c in my_targets if _row_name(c) not in filled]

    def _ask_retry(prompt: str, attempts: int = 3) -> str:
        for i in range(1, attempts + 1):
            try:
                out = ai_ask(prompt)
                if out and len(str(out).strip()) > 80:
                    return out
            except Exception as err:  # noqa: BLE001
                print(f"    attempt {i}: {type(err).__name__}: {str(err)[:70]}",
                      flush=True)
            if i < attempts:
                time.sleep(30)
        return ""

    def _write_sidecar() -> None:
        tmp = side_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(filled, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, side_path)

    started = time.monotonic()
    size = max(1, args.batch)
    for start in range(0, len(my_targets), size):
        chunk = my_targets[start : start + size]
        if args.refresh_brand_only:
            system, user = _build_brand_only_prompt(chunk)
        else:
            system, user = _build_prompt(chunk)
        answer = _ask_retry(f"{system}\n\n{user}")
        results = []
        if answer:
            try:
                parsed = parse_json_answer(answer, require_key="results")
                results = (parsed or {}).get("results") or []
            except Exception:  # noqa: BLE001
                results = []
        # Match by POSITION: the prompt asks the model to clean up `company`
        # (drop parenthetical aliases), so the returned name usually no
        # longer equals the original row's messy name -- a name match would
        # miss almost every row. The model is told to keep the same order
        # and count, so position is the reliable key; a name match is only
        # a fallback for when the model dropped or reordered an entry.
        by_name = {str(r.get("company") or "").strip().lower(): r for r in results}
        for i, c in enumerate(chunk):
            name = _row_name(c)
            r = results[i] if i < len(results) else by_name.get(name.strip().lower())
            if not r:
                continue
            if args.refresh_brand_only:
                filled[name] = {
                    "brand": str(r.get("brand") or r.get("company") or "").strip() or name,
                }
            else:
                filled[name] = {
                    "brand": str(r.get("brand") or r.get("company") or "").strip() or c.get("brand", ""),
                    "clean_company": str(r.get("company") or "").strip(),
                    "website": str(r.get("website") or "").strip(),
                    "headquarters": str(r.get("headquarters") or "").strip() or c.get("headquarters", ""),
                    "ownership": str(r.get("ownership") or "Independent").strip(),
                    "ownership_confidence": str(r.get("ownership_confidence") or "low").strip(),
                }
        _write_sidecar()
        mins = (time.monotonic() - started) / 60
        done_n = start + len(chunk)
        print(f"  [{done_n}/{len(my_targets)}] +{len(results)} filled "
              f"({mins:.1f}m elapsed)", flush=True)

    print(f"\ndone: {len(filled)} companies filled from this shard")
    print(f"sidecar: {side_path}")
    print("run merge_gap_fill.py once every shard has finished")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
