#!/usr/bin/env python3
"""Verify each company against the exact market definition, via AI Mode.

No DeepSeek, no reasoning-from-snippet -- each batch asks AI Mode to
actually check whether the company genuinely executes the defined service
on client data, using the operator's own market definition and exclusion
list verbatim (same spec shape as build_strict_service_round_prompt).
Writes verdicts to a per-shard sidecar; merge_verify.py applies them to the
checkpoint's `verified` / `rejected` lists.

    .\\.venv\\Scripts\\python.exe scripts\\ai_mode_verify.py ^
        --market "Marine Seismic Data Processing Services Market" ^
        --country global --slot 41 --shard 0 --shards 4 ^
        --strict-spec config/marine_seismic_strict_query.json --batch 8
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
    return str(r.get("company") or r.get("Company") or r.get("name") or "").strip()


def _row_hq(r: dict) -> str:
    return str(r.get("headquarters") or r.get("Headquarters") or "").strip()


def _row_website(r: dict) -> str:
    return str(r.get("website") or "").strip()


def _row_hint(r: dict) -> str:
    return str(r.get("why_related") or r.get("Summary") or r.get("snippet") or "").strip()


def _build_verify_prompt(
    spec: dict, companies: list[dict]
) -> tuple[str, str]:
    system = (
        "You are a strict B2B market-research analyst verifying whether "
        "companies genuinely belong in a specific market AS A SERVICE "
        "PROVIDER. No invented values. Return compact JSON only: "
        '{"results":[{"company":"...","role":"Service Provider|Software '
        'Vendor|Equipment Supplier|Distributor|Consultancy|Internal Use '
        'Only|Other","in_market":true|false,'
        '"confidence":"high|medium|low","reason":"..."}]}'
    )

    services = "\n".join(f"- {s}" for s in spec["qualifying_services"])
    exclusions = "\n".join(f"- {e}" for e in spec["excluded_categories"])

    lines = []
    for i, c in enumerate(companies):
        letter = chr(65 + i)
        hq = _row_hq(c)
        site = _row_website(c)
        hint = _row_hint(c)
        bits = []
        if hq:
            bits.append(f"HQ: {hq}")
        if site:
            bits.append(f"website: {site}")
        if hint:
            bits.append(f"known for: {hint}")
        about = f" ({'; '.join(bits)})" if bits else ""
        lines.append(f"{letter}. {_row_name(c)}{about}")
    listing = "\n".join(lines)

    user = (
        f'Market: "{spec["market"]}"\n\n'
        f"MARKET DEFINITION:\n{spec['market_definition']}\n\n"
        "REQUIRED PLAYER TYPE:\nService Provider -- a company that itself "
        "EXECUTES the defined service on client data, for a fee, as its "
        "own commercial offering. This is a role check as well as a "
        "market-fit check: a company can be genuinely related to this "
        "market and still NOT be a Service Provider (it might sell the "
        "software instead, sell the acquisition hardware instead, buy the "
        "service for its own internal use instead, or only distribute/"
        "resell someone else's service).\n\n"
        "For EACH of the companies below, determine its role AND whether "
        "it genuinely qualifies as a Service Provider under this exact "
        "definition.\n\n"
        f"CANDIDATES:\n{listing}\n\n"
        "role must be one of:\n"
        "- Service Provider: executes the defined service itself, "
        "commercially, for external clients -- the ONLY role that "
        "qualifies.\n"
        "- Software Vendor: sells or licenses the processing software/"
        "platform but does not itself run it on client data.\n"
        "- Equipment Supplier: sells/manufactures acquisition or "
        "processing hardware.\n"
        "- Distributor: resells or channel-partners someone else's "
        "service.\n"
        "- Consultancy: advises on the market rather than executing the "
        "service.\n"
        "- Internal Use Only: an oil & gas / exploration company that "
        "processes seismic data (its own or via a contractor) only for "
        "its own projects, never as a service sold to external clients.\n"
        "- Other: none of the above (media, association, research "
        "institute, government agency, etc.).\n\n"
        "A company qualifies (in_market=true) ONLY when role=\"Service "
        "Provider\" AND it actually performs the service described above "
        f"as a commercial service for external clients, via one or more "
        f"of:\n{services}\n\n"
        "The company must actually EXECUTE the processing/service on "
        "client data. Merely owning, selling, licensing, distributing, "
        "acquiring, storing, or using the technology does NOT qualify -- "
        "set role accordingly and in_market=false.\n\n"
        f"REJECT (in_market=false) if the company is any of:\n{exclusions}\n\n"
        "Also REJECT if the company's connection to this market cannot be "
        "verified from what you actually know about it -- if unsure, "
        "in_market=false. A wrong \"true\" is worse than a correct "
        '"false".\n\n'
        "Return one result per company, in the SAME order, using the exact "
        'company name given as "company". Never skip a company.\n\n'
        "OUTPUT FORMAT: Return ONLY the JSON object shown in the system "
        "message. Do not add any prose before, after, or instead of the "
        "JSON -- no summary sentence, no offer to find more companies, no "
        "commentary of any kind."
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
    ap.add_argument("--strict-spec", required=True)
    ap.add_argument("--out-dir", default="")
    args = ap.parse_args()

    profile = ROOT / "data" / f"ai_mode_batch_{args.slot:02d}"
    os.environ["GOOGLE_AI_MODE_PROFILE_DIR"] = str(profile)
    os.environ["GOOGLE_AI_MODE_BROWSER"] = "chromium"
    os.environ["GOOGLE_AI_MODE_ENABLED"] = "true"

    from vendor_intel.pipeline.web_expand import default_output_dir
    from vendor_intel.scraping.google_ai_mode import ask as ai_ask
    from vendor_intel.scraping.google_ai_mode import parse_json_answer

    spec = json.loads(Path(args.strict_spec).read_text(encoding="utf-8"))

    out_dir = Path(args.out_dir) if args.out_dir else Path(default_output_dir(args.market, args.country))
    ckpt_path = out_dir / "chatgpt_checkpoint_batch_all.json"
    if not ckpt_path.exists():
        print(f"ERROR: no checkpoint at {ckpt_path}", file=sys.stderr)
        return 2

    state = json.loads(ckpt_path.read_text(encoding="utf-8"))
    data = state.setdefault("data", {})
    recalled = data.get("recalled") or []
    # De-dupe by name before sharding, same reasoning as every other sweep
    # here: one company must land in exactly one shard.
    by_name: dict[str, dict] = {}
    for r in recalled:
        nm = _row_name(r)
        if nm and nm not in by_name:
            by_name[nm] = r
    all_companies = list(by_name.values())

    my_companies = all_companies[args.shard::args.shards]
    print(f"shard {args.shard}/{args.shards}: {len(my_companies)} companies "
          f"of {len(all_companies)} total")

    side_path = out_dir / f"verify_shard{args.shard}.json"
    results: dict[str, dict] = {}
    if side_path.exists():
        try:
            results = json.loads(side_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            results = {}
    my_companies = [c for c in my_companies if _row_name(c) not in results]

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
        tmp.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, side_path)

    started = time.monotonic()
    size = max(1, args.batch)
    for start in range(0, len(my_companies), size):
        chunk = my_companies[start : start + size]
        system, user = _build_verify_prompt(spec, chunk)
        answer = _ask_retry(f"{system}\n\n{user}")
        parsed_results = []
        if answer:
            try:
                parsed = parse_json_answer(answer, require_key="results")
                parsed_results = (parsed or {}).get("results") or []
            except Exception:  # noqa: BLE001
                parsed_results = []
        by_result_name = {
            str(r.get("company") or "").strip().lower(): r for r in parsed_results
        }
        kept_n = 0
        for i, c in enumerate(chunk):
            name = _row_name(c)
            r = parsed_results[i] if i < len(parsed_results) else by_result_name.get(name.strip().lower())
            if not r:
                # Fail closed: a company that never got a verdict is not
                # silently kept -- it is marked unverified and dropped, the
                # same way a parse failure drops a whole chunk elsewhere in
                # this pipeline rather than defaulting to "in".
                results[name] = {"in_market": False, "role": "", "confidence": "low",
                                  "reason": "no verdict returned"}
                continue
            role = str(r.get("role") or "").strip()
            # Both must hold: the model's own in_market flag AND the role
            # it named must be exactly "Service Provider". A model that
            # says in_market=true but names a different role (it happens --
            # the model is not perfectly self-consistent) must not slip
            # through on the flag alone, since the flag is what the earlier,
            # role-less prompt was already getting wrong.
            in_market = bool(r.get("in_market")) and role == "Service Provider"
            results[name] = {
                "in_market": in_market,
                "role": role,
                "confidence": str(r.get("confidence") or "low"),
                "reason": str(r.get("reason") or ""),
            }
            if in_market:
                kept_n += 1
        _write_sidecar()
        mins = (time.monotonic() - started) / 60
        done_n = start + len(chunk)
        print(f"  [{done_n}/{len(my_companies)}] +{kept_n}/{len(chunk)} kept "
              f"({mins:.1f}m elapsed)", flush=True)

    # A batch that comes back short (partial parse, one company dropped
    # from the reply) fails that company closed rather than open -- but a
    # single missed verdict should not cost a genuine company its place in
    # the market. Retry every "no verdict returned" one at a time, the same
    # escalation prescore_verified.py uses for a company a batch skipped.
    by_company = {_row_name(c): c for c in my_companies}
    for attempt in range(1, 3):
        missing = [
            name for name, v in results.items()
            if v.get("reason") == "no verdict returned" and name in by_company
        ]
        if not missing:
            break
        print(f"\nretry pass {attempt}: {len(missing)} companies never got "
              f"a verdict -- asking again singly", flush=True)
        for name in missing:
            system, user = _build_verify_prompt(spec, [by_company[name]])
            answer = _ask_retry(f"{system}\n\n{user}")
            r = None
            if answer:
                try:
                    parsed = parse_json_answer(answer, require_key="results")
                    items = (parsed or {}).get("results") or []
                    r = items[0] if items else None
                except Exception:  # noqa: BLE001
                    r = None
            if r:
                role = str(r.get("role") or "").strip()
                results[name] = {
                    "in_market": bool(r.get("in_market")) and role == "Service Provider",
                    "role": role,
                    "confidence": str(r.get("confidence") or "low"),
                    "reason": str(r.get("reason") or ""),
                }
            _write_sidecar()

    total_kept = sum(1 for v in results.values() if v.get("in_market"))
    print(f"\ndone: {len(results)} verified, {total_kept} kept in_market "
          f"from this shard")
    print(f"sidecar: {side_path}")
    print("run merge_verify.py once every shard has finished")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
