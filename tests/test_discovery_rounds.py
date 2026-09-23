"""Discovery in rounds: one loop replacing recall + discover + list-discover.

Measured on Global Silicon Carbide: recall found 118, 2a found 0 new, 2g
found +1 across 9 queries — three stages asking the same question.
"""
from __future__ import annotations

import re

from vendor_intel.pipeline import discovery_rounds as dr


def _key(name: str) -> str:
    """The pipeline's real dedupe key — strips legal suffixes and accents, so
    "Wolfspeed Inc" and "Wolfspeed" are one company."""
    from vendor_intel.pipeline.ai_mode_discovery import dedupe_key

    return dedupe_key(name)


def _co(n: str) -> dict:
    return {"name": n, "website": f"https://{n.lower()}.com", "verdict": "in_market"}


# --- the loop --------------------------------------------------------------


def test_rounds_accumulate_until_target():
    pool = [f"Co{i}" for i in range(25)]
    state = {"i": 0}

    def ask(system, user, label):
        i = state["i"]
        state["i"] += 10
        return {"companies": [_co(n) for n in pool[i : i + 10]]}

    found, stats = dr.discover_in_rounds(
        "M", "Manufacturer", ask_json=ask, target=20, dedupe_key=_key
    )
    assert len(found) >= 20
    assert stats["stopped_because"] == "target_reached"


def test_three_empty_rounds_stop_the_loop():
    """One empty round is normal as a market thins out; three means the
    market is genuinely exhausted."""
    calls = {"n": 0}

    def ask(system, user, label):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"companies": [_co("Wolfspeed")]}
        return {"companies": []}

    found, stats = dr.discover_in_rounds(
        "M", "Manufacturer", ask_json=ask, target=100, dedupe_key=_key,
        # Region escalation OFF: this test pins the BROAD stop rule. With
        # escalation on, three empty broad rounds hand over to the per-region
        # sweep instead of stopping (see test_region_escalation.py).
        escalate_regions=False,
    )
    assert len(found) == 1
    assert stats["stopped_because"] == "exhausted"
    # 1 productive + 3 empty; must not keep grinding to the target.
    assert calls["n"] == 4


def test_three_empty_rounds_hand_over_to_the_region_sweep():
    """With escalation on (the default), the broad question going quiet is
    not the end — every region is still asked about directly."""
    calls = {"n": 0}

    def ask(system, user, label):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"companies": [_co("Wolfspeed")]}
        return {"companies": []}

    _, stats = dr.discover_in_rounds(
        "M", "Manufacturer", ask_json=ask, target=100, dedupe_key=_key
    )
    assert stats["stopped_because"] == "exhausted"
    assert stats["escalated"] is True
    assert len(stats["regions_swept"]) == 9, "all nine regions asked directly"
    assert calls["n"] > 4, "must not stop at the broad rule any more"


def test_a_single_empty_round_does_not_stop():
    calls = {"n": 0}

    def ask(system, user, label):
        calls["n"] += 1
        if calls["n"] == 2:
            return {"companies": []}
        return {"companies": [_co(f"Co{calls['n']}")]}

    found, stats = dr.discover_in_rounds(
        "M", "Manufacturer", ask_json=ask, target=4, dedupe_key=_key
    )
    assert len(found) == 4, "an empty round must not end discovery"


def test_duplicates_across_rounds_are_dropped():
    def ask(system, user, label):
        return {"companies": [_co("Wolfspeed"), _co("Wolfspeed Inc")]}

    found, _ = dr.discover_in_rounds(
        "M", "Manufacturer", ask_json=ask, target=10, dedupe_key=_key
    )
    assert len(found) == 1


def test_failed_round_counts_as_empty_not_fatal():
    calls = {"n": 0}

    def ask(system, user, label):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise RuntimeError("CAPTCHA")
        return {"companies": [_co("Coherent")]}

    found, stats = dr.discover_in_rounds(
        "M", "Manufacturer", ask_json=ask, target=1, dedupe_key=_key
    )
    assert len(found) == 1, "a failed round must not abort the loop"


def test_verdict_gate_is_applied():
    def ask(system, user, label):
        return {
            "companies": [
                {"name": "Wolfspeed", "verdict": "in_market"},
                {"name": "MarketsandMarkets", "verdict": "unrelated"},
            ]
        }

    found, _ = dr.discover_in_rounds(
        "M",
        "Manufacturer",
        ask_json=ask,
        target=5,
        dedupe_key=_key,
        accept=lambda r: str(r.get("verdict", "")).lower() == "in_market",
    )
    assert [c["name"] for c in found] == ["Wolfspeed"]


def test_every_round_is_checkpointable():
    seen_rounds = []

    def ask(system, user, label):
        return {"companies": [_co(f"Co{len(seen_rounds)}")]}

    dr.discover_in_rounds(
        "M",
        "Manufacturer",
        ask_json=ask,
        target=3,
        dedupe_key=_key,
        on_round=lambda n, new, found: seen_rounds.append((n, len(found))),
    )
    assert seen_rounds == [(1, 1), (2, 2), (3, 3)]


# --- the prompt ------------------------------------------------------------


def test_exclusion_list_is_carried_every_round():
    """AI Mode is stateless — "give me 10 more" means nothing on its own."""
    prompts = []

    def ask(system, user, label):
        prompts.append(user)
        n = len(prompts)
        return {"companies": [_co(f"Co{n}")]}

    dr.discover_in_rounds("M", "Manufacturer", ask_json=ask, target=3, dedupe_key=_key)
    assert "Co1" in prompts[1], "round 2 must exclude round 1's companies"
    assert "Co2" in prompts[2]


def test_exclusion_block_is_char_capped_and_newest_first():
    block = dr.format_exclusions([f"Company Number {i} Holdings Ltd" for i in range(400)])
    assert len(block) <= dr.MAX_EXCLUSION_CHARS + 300
    assert "Company Number 399" in block, "newest first"
    assert "more already-collected companies" in block, "disclose the omission"
    assert "smaller, regional or specialist" in block, "with a strategy"


def test_round_prompt_asks_for_the_single_player_type():
    _, user = dr.build_round_prompt("Global Silicon Carbide Market", "Manufacturer", excluded_names=[])
    assert "make it a Manufacturer in this market" in user
    assert "what it IS, not something it also does" in user


def test_round_prompt_exclusions_carry_reasons():
    _, user = dr.build_round_prompt("M", "Manufacturer", excluded_names=[])
    assert "reporting on or advising a market is not operating in it" in user
    assert "they sell TO this market, not IN it" in user.replace("They", "they")


def test_round_prompt_template_comes_last_and_prefers_blank():
    system, user = dr.build_round_prompt("M", "Manufacturer", excluded_names=[])
    assert '"verdict"' in system, "JSON shape belongs in the system prompt"
    assert "NEVER guess this field" in user
    assert "empty string is CORRECT and preferred" in user
    assert "no field may be blank" not in user.lower()


def test_round_prompt_fits_the_url_budget():
    from vendor_intel.scraping.google_ai_mode import MAX_URL_CHARS, build_url

    system, user = dr.build_round_prompt(
        "Global Silicon Carbide Market",
        "Manufacturer",
        excluded_names=[f"Company Number {i} Holdings Ltd" for i in range(400)],
    )
    assert len(build_url(f"{system}\n\n{user}")) <= MAX_URL_CHARS


def test_b2c_prompt_asks_for_consumer_brands():
    _, user = dr.build_round_prompt(
        "Potato Chips Market", "Brand / Marketer", excluded_names=[], market_type="B2C"
    )
    assert "consumer-facing brand" in user


# --- details collected during discovery, not in a later pass ---------------


def test_round_prompt_asks_for_company_details():
    """Finding a company and looking up its details are the same lookup.
    Splitting them costs a second query per company — and when Step 5's
    legacy sources are unavailable it filled NOTHING ("sources applied: none"
    on all 70 rows), pushing every gap into the slow residual pass."""
    _, user = dr.build_round_prompt("M", "Manufacturer", excluded_names=[])
    # Only what the 8 report columns need. AI Mode scoring takes the company
    # NAME alone, so firmographics it never reads are not worth a lookup.
    for field in ("brand", "company", "headquarters", "ownership"):
        assert f"- {field}:" in user, f"{field} must be collected during discovery"
    for unused in ("founded", "employees", "categories", "offering"):
        assert f"- {unused}:" not in user, f"{unused} is used by no column or scorer"


def test_detail_field_rules_prevent_known_bad_values():
    _, user = dr.build_round_prompt("M", "Manufacturer", excluded_names=[])
    assert '"Global"' in user and "50+ countries" in user      # vague geography
    assert "NEVER a distributor" in user                        # company != distributor
    assert "Acquired by <Parent>" in user                       # Company column format


def test_round_prompt_with_details_still_fits_the_url():
    from vendor_intel.scraping.google_ai_mode import MAX_URL_CHARS, build_url

    system, user = dr.build_round_prompt(
        "Global Silicon Carbide Market",
        "Manufacturer",
        excluded_names=[f"Company Number {i} Holdings Ltd" for i in range(400)],
    )
    assert len(build_url(f"{system}\n\n{user}")) <= MAX_URL_CHARS


def test_details_map_into_landscape_columns():
    from vendor_intel.pipeline.chatgpt_expand import _as_seed_rows

    rows = _as_seed_rows(
        [
            {
                "brand": "SmartCut",
                "company": "Soitec",
                "website": "https://soitec.com",
                "headquarters": "Grenoble, France",
                "ownership": "Independent",
                "why_related": "Produces SiC substrates.",
            }
        ]
    )
    row = rows[0]
    assert row["Headquarters"] == "Grenoble, France"
    assert row["Ownership"] == "Independent"
    assert row["Market Offering"] == "SmartCut"   # -> Brand column
    assert row["Company"] == "Soitec"
    assert row["Summary"]


def test_placeholder_details_are_not_written():
    """An "unknown" must stay empty rather than becoming literal text."""
    from vendor_intel.pipeline.chatgpt_expand import _as_seed_rows

    row = _as_seed_rows(
        [{"brand": "X", "company": "X Ltd", "website": "https://x.com",
          "headquarters": "unknown", "ownership": "N/A"}]
    )[0]
    assert "Headquarters" not in row
    assert "Ownership" not in row


# --- the three report columns come from Step 1 -----------------------------


def test_report_columns_are_sourced_from_discovery():
    """Brand, Company and "Found in" must be filled by the discovery round —
    not by a later gap-fill pass, which was filling nothing at all."""
    from vendor_intel.pipeline.chatgpt_expand import _as_seed_rows
    from vendor_intel.pipeline.expand_quadrant_score import to_company_detail_rows

    found = [
        {
            "brand": "Coherent SiC",
            "company": "Coherent",
            "website": "https://coherent.com",
            "headquarters": "Saxonburg, Pennsylvania, USA",
            "ownership": "Acquired by II-VI",
            "verdict": "in_market",
        },
        {
            "brand": "SiCrystal",
            "company": "SiCrystal GmbH",
            "website": "https://sicrystal.de",
            "headquarters": "Nuremberg, Germany",
            "ownership": "Subsidiary of ROHM",
            "verdict": "in_market",
        },
        {
            "brand": "SmartCut",
            "company": "Soitec",
            "website": "https://soitec.com",
            "headquarters": "Grenoble, France",
            "ownership": "Independent",
            "verdict": "in_market",
        },
    ]
    rows = _as_seed_rows(found)
    for r in rows:
        r.update(
            {
                "Company": r["name"],
                "Website": r["website"],
                "Distribution Type": "Manufacturer",
                "commercial_roles": ["Manufacturer"],
                "X Score": "80",
                "Y Score": "78",
                "Overall Score": "79",
                "Quadrant": "Leaders",
            }
        )
    out = {o["Company"]: o for o in to_company_detail_rows(rows, "Global Silicon Carbide Market")}

    # Company: "Name (acquired by Parent)" when owned, plain when independent.
    assert "Coherent (acquired by II-VI)" in out
    assert "SiCrystal GmbH (subsidiary of ROHM)" in out
    assert "Soitec" in out

    # Brand: the market offering, not a repeat of the company name.
    assert out["Coherent (acquired by II-VI)"]["Brand"] == "Coherent SiC"
    assert out["Soitec"]["Brand"] == "SmartCut"

    # Found in: the researched HQ location.
    assert out["Soitec"]["Found in"] == "Grenoble, France"
    assert out["SiCrystal GmbH (subsidiary of ROHM)"]["Found in"] == "Nuremberg, Germany"


def test_independent_company_has_no_acquisition_suffix():
    from vendor_intel.pipeline.chatgpt_expand import _as_seed_rows
    from vendor_intel.pipeline.expand_quadrant_score import to_company_detail_rows

    rows = _as_seed_rows(
        [
            {
                "brand": "Wolfspeed",
                "company": "Wolfspeed",
                "website": "https://wolfspeed.com",
                "headquarters": "Durham, North Carolina, USA",
                "ownership": "Independent",
                "verdict": "in_market",
            }
        ]
    )
    rows[0].update(
        {
            "Company": "Wolfspeed",
            "Distribution Type": "Manufacturer",
            "commercial_roles": ["Manufacturer"],
            "X Score": "90",
            "Y Score": "88",
            "Overall Score": "89",
            "Quadrant": "Leaders",
        }
    )
    out = to_company_detail_rows(rows, "Global Silicon Carbide Market")[0]
    assert out["Company"] == "Wolfspeed"
    assert "(" not in out["Company"]


def test_json_template_lists_every_field_the_rules_ask_for():
    """Regression: the field RULES were updated to ask for headquarters /
    ownership / offering, but the JSON TEMPLATE in the system prompt still
    listed only name/website/country/verdict/why_related — so AI Mode
    returned exactly those five and the report columns stayed empty.

    The template is what the model copies, so the two must never drift."""
    system, user = dr.build_round_prompt("M", "Manufacturer", excluded_names=[])
    template = system[system.index('{"companies"') :]

    rule_fields = {
        line.split(":")[0][2:]
        for line in user.split("\n")
        if line.startswith("- ") and ":" in line[:18]
    }
    for field in rule_fields:
        assert f'"{field}"' in template, f"{field} has a rule but is not in the template"


def test_template_carries_the_three_report_inputs():
    system, _ = dr.build_round_prompt("M", "Manufacturer", excluded_names=[])
    for field in ("brand", "company", "headquarters", "ownership"):
        assert f'"{field}"' in system, f"{field} feeds a report column"


# --- a block is not an empty market ----------------------------------------


def test_quota_rounds_are_not_reported_as_exhausted():
    """Regression: the loop caught EVERY exception as "empty round", so three
    AI-response quota errors looked identical to a finished market — a live
    run stopped at 10 companies and reported "exhausted"."""
    def ask(system, user, label):
        raise RuntimeError("AI response request limit reached for this IP")

    found, stats = dr.discover_in_rounds(
        "M", "Manufacturer", ask_json=ask, target=100, dedupe_key=_key
    )
    assert stats["stopped_because"] == "blocked", "must not claim exhaustion"
    assert stats["blocked_rounds"] >= dr.MAX_BLOCKED_ROUNDS
    assert stats["empty_streak"] == 0, "a block must not count as an empty round"


def test_captcha_rounds_are_treated_as_blocked():
    from vendor_intel.scraping.google_ai_mode import AiModeCaptcha

    def ask(system, user, label):
        raise AiModeCaptcha("blocked page text (unusual traffic)")

    _, stats = dr.discover_in_rounds(
        "M", "Manufacturer", ask_json=ask, target=50, dedupe_key=_key
    )
    assert stats["stopped_because"] == "blocked"


def test_a_parse_failure_still_counts_as_an_empty_round():
    """Only BLOCKS get special treatment — a bad reply is genuinely empty."""
    def ask(system, user, label):
        raise ValueError("no JSON object found")

    _, stats = dr.discover_in_rounds(
        "M", "Manufacturer", ask_json=ask, target=50, dedupe_key=_key
    )
    assert stats["stopped_because"] == "exhausted"


def test_block_detection_distinguishes_causes():
    from vendor_intel.scraping.google_ai_mode import AiModeCaptcha

    assert dr._is_blocked(RuntimeError("AI response request limit reached"))
    assert dr._is_blocked(AiModeCaptcha("x"))
    assert not dr._is_blocked(ValueError("bad json"))
