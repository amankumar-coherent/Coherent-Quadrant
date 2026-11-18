"""Supporting points that are the prompt's own wording, or carry search-snippet
text after the finding, never reach the report (owner 2026-11-15)."""
from vendor_intel.pipeline.company_facts import cut_snippet_tail, tidy_claim
from vendor_intel.quadrant.ai_mode_scorer import _section_evidence, is_evidence_echo


def test_prompt_template_lines_are_echo():
    assert is_evidence_echo("Lines, one finding per line, at most 5")
    assert is_evidence_echo("<a specific finding on Revenue and Growth — named figure, product, contract, "
                            "facility, certification or date — and its source>")
    assert is_evidence_echo(". Look at the company's own website and press releases, regulatory filings")
    assert is_evidence_echo("Includes reported sales volumes. Look at the company's own website and press releases")


def test_real_findings_are_not_echo():
    assert not is_evidence_echo("The company reports that it launched the Ecopol 100 series of biodegradable "
                                "nonionic surfactants, according to its technical bulletin.")
    assert not is_evidence_echo("The company reports annual revenue of USD 2.1 billion in 2024.")


def test_parser_drops_echoed_template():
    section = ("Evidence: Lines, one finding per line, at most 5 Evidence: <a specific finding on Scale — named "
               "figure, product, contract, facility, certification or date — and its source> Evidence: The company "
               "reports a 120 kt ethoxylation plant in Tlaxcala.")
    claims = [e["claim"] for e in _section_evidence(section)]
    assert claims == ["The company reports a 120 kt ethoxylation plant in Tlaxcala."]


def test_snippet_tail_cut():
    text = ("The company reports that its Tlaxcala Production Plant maintains installed equipment for "
            "ethoxylation, according to its corporate website. Polaquimia División Internacional - Polaquimia "
            "Nuestra división internacional está formada por agentes … afi... Location: San Cosme, ethoxylatio...")
    assert cut_snippet_tail(text) == ("The company reports that its Tlaxcala Production Plant maintains installed "
                                      "equipment for ethoxylation, according to its corporate website.")
    assert tidy_claim(text).endswith("according to its corporate website.")


def test_no_ellipsis_unchanged():
    t = "The company reports capacity of 180 kt. This was confirmed in the 2025 filing."
    assert cut_snippet_tail(t) == t
