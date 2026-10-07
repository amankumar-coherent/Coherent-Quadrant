"""Hedge lead-in rewriting in rewrite_assessed_on_tone.py.

Regression coverage for a real VERIFY failure: three finished drone-market
reports each carried a leftover "could not verify" sentence in the report,
because the mid-sentence hedge pattern only matched when the model wrote
", but I/we could not verify ..." -- a comma directly followed by "I"/"we"
with no "but" (which the model does write) slipped through untouched.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "rewrite_assessed_on_tone", ROOT / "scripts" / "rewrite_assessed_on_tone.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load_module()


def test_mid_sentence_hedge_without_but_is_rewritten():
    """Live case: Anti-Drone Systems report, Armory Defence Technologies."""
    s = (
        "Armory is bidding on government anti-drone infrastructure tenders, "
        "we could not verify any finalized, standalone procurement contracts "
        "or figures specifically awarded to the company."
    )
    out = mod.rewrite_sentence(s)
    assert "could not verify" not in out.lower()
    assert "based on primary research, the company has not disclosed" in out.lower()


def test_mid_sentence_hedge_without_but_singular_pronoun():
    s = (
        "The company holds several patents, I could not verify their "
        "commercial deployment status."
    )
    out = mod.rewrite_sentence(s)
    assert "could not verify" not in out.lower()


def test_existing_but_pattern_still_rewritten():
    """Regression guard: the original ', but we could not verify' pattern
    must keep working after adding the no-"but" variant."""
    s = (
        "Revenue grew 20%, but we could not verify the exact figure from "
        "public filings."
    )
    out = mod.rewrite_sentence(s)
    assert "could not verify" not in out.lower()


def test_sentence_start_hedge_still_rewritten():
    s = "We could not verify the company's total headcount."
    out = mod.rewrite_sentence(s)
    assert "could not verify" not in out.lower()


def test_no_hedge_text_is_left_unchanged():
    s = "The company operates three manufacturing facilities in Bengaluru."
    assert mod.rewrite_sentence(s) == s


def test_mid_sentence_hedge_with_and_connector():
    """Live case: Drone Sensors report."""
    s = (
        "The company demonstrates strong capabilities for tactical drones, "
        "the available evidence is self-reported by the company, and we "
        "could not verify specific third-party patent logs or documented "
        "joint institutional R&D project metrics to prove independent "
        "validation."
    )
    out = mod.rewrite_sentence(s)
    assert "could not verify" not in out.lower()


def test_but_with_no_comma_and_no_pronoun():
    """Live case: Drone Imaging report -- "but could not verify" with no
    comma before "but" and no pronoun immediately before "could not
    verify" (the "We" is earlier in the sentence)."""
    s = (
        "We verified the company's domestic operational focus within India "
        "but could not verify any standalone international sales, overseas "
        "distributors, or compliance with foreign aviation frameworks."
    )
    out = mod.rewrite_sentence(s)
    assert "could not verify" not in out.lower()


def test_unrelated_subject_is_not_mangled():
    """"could not verify" with a DIFFERENT subject and no comma/connector
    boundary must be left alone -- rewriting it would cut the sentence into
    a meaningless fragment. Caught in testing before this shipped: an
    earlier, more permissive version of the mid-sentence pattern turned
    "Independent auditors could not verify the claim..." into "Independent
    auditors. This is not disclosed by the company, ..." """
    s = "Independent auditors could not verify the claim due to insufficient documentation."
    assert mod.rewrite_sentence(s) == s


def test_more_gap_phrasings_become_primary_research():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from primary_research_wording import PR, to_primary
    cases = {
        "The company does not publicly report the specific cryptographic algorithms used.":
            f"{PR} the specific cryptographic algorithms used.",
        "API data limits for custom tiers are not publicly detailed.": f"{PR} API data limits for custom tiers.",
        "We found no public reporting of strategic alliances with OEMs.": f"{PR} strategic alliances with OEMs.",
        "No evidence exists of any proprietary hardware lines.": f"{PR} any proprietary hardware lines.",
        "We verified that the rating rests on its ISO 27001 data centres.": "The rating rests on its ISO 27001 data centres.",
    }
    for old, new in cases.items():
        assert to_primary(old) == new, old


def test_no_specific_public_evidence_dropped():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from primary_research_wording import PR, to_primary
    gap = f"{PR} UK-specific revenue."
    assert to_primary("No specific public evidence or disclosed financial tracking records were found "
                      f"concerning its regional performance. {gap}") == gap


def test_no_metrics_available_sentence_dropped():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from primary_research_wording import PR, to_primary
    gap = f"{PR} UK-specific revenue."
    assert to_primary(f"We verified that no public financial statements or investor reports are available for it. {gap}") == gap
    assert to_primary(f"We verified that no specific public reports or financial statements exist regarding it. {gap}") == gap


def test_standalone_remain_undisclosed_becomes_house_sentence():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from primary_research_wording import PR, to_primary
    assert to_primary("It rests on a leasing alliance. Exact channel revenue shares remain undisclosed.") == \
        f"It rests on a leasing alliance. {PR} exact channel revenue shares."


def test_there_is_no_specific_public_evidence_becomes_house_sentence():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from primary_research_wording import PR, to_primary
    assert to_primary("It deploys swapping systems, there is no specific public evidence of BIS certificates.") == \
        f"It deploys swapping systems, {PR[0].lower()}{PR[1:]} BIS certificates."
    assert to_primary(f"We verified that no specific public evidence of OEM contracts could be established. {PR} partners.") == \
        f"{PR} partners."


def test_sentence_level_gap_rewrite():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from primary_research_wording import PR, to_primary
    # clause after a finding, no house sentence yet -> finding kept, gap rewritten
    assert to_primary("We verified its Coimbatore office, but found no verifiable evidence of a dealer network, "
                      "placing it in a weak scoring band.") == \
        f"We verified its Coimbatore office. {PR} a dealer network."
    # subject form names what was not disclosed
    assert to_primary("We verified RF scanning; however, exact frequency bands were not publicly detailed.") == \
        f"We verified RF scanning; however, {PR[0].lower()}{PR[1:]} exact frequency bands."
    # 'While X remain undisclosed, Y.'
    assert to_primary("While precise unit counts remain undisclosed, the military contracts establish presence.") == \
        f"The military contracts establish presence. {PR} precise unit counts."
    # a real finding with 'placing' but no band word is untouched
    s = "It won the 2025 award, placing it among India's leading suppliers."
    assert to_primary(s) == s


def test_double_gap_inside_house_sentence_cleaned():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from primary_research_wording import PR, to_primary
    assert to_primary(f"{PR} IP ratings for Indian conditions remains undisclosed or self-reported.") == \
        f"{PR} IP ratings for Indian conditions."
