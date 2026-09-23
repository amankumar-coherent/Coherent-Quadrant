"""Score a company's X (Product Strength) / Y (Business Strength) via Google
AI Mode.

Division of labour:

* The LLM still GENERATES the five parameters under each axis, because those
  are market-specific (a semiconductor market's product parameters are not a
  packaging market's). See quadrant/axis_define.py.
* AI Mode then PRODUCES THE SCORE, asked as one consolidated question per
  axis — the unweighted average of those five parameters, out of 100.

The axis names themselves are fixed for every market: X is always Product
Strength, Y is always Business Strength. Only the parameters beneath them
change.

One query per axis per company (not one per parameter): AI Mode is paced at
10s+ per query, so five separate parameter questions per axis would be ten
queries per company. Asking for the consolidated average matches how the
answer is actually wanted and keeps a market's run tractable.
"""
from __future__ import annotations

import json
import re
from typing import Any

AXIS_X_LABEL = "Product Strength"
AXIS_Y_LABEL = "Business Strength"

# A bare "NN out of 100", "score is NN", or "**NN**" in the rendered answer.
_SCORE_PATTERNS = (
    re.compile(r"\b(\d{1,3})\s*(?:out\s+of|/)\s*100\b", re.I),
    # "score ... 74". The negative lookahead stops it swallowing the "100" in
    # the question's own "score out of 100" wording, which turned a refusal
    # ("Score out of 100: not available") into a perfect 100.
    re.compile(r"score(?![^.\d]{0,20}out\s+of)[^.\d]{0,40}?\b(\d{1,3})\b", re.I),
    re.compile(r"\*\*\s*(\d{1,3})\s*\*\*"),
    # The whole answer is just the number — which is what the prompt asks for
    # and, per the rendered answers, what AI Mode most often returns. A
    # decimal is legitimate: averaging five integer ratings gives "20.4",
    # which was being discarded as unparseable.
    re.compile(r"^\s*(\d{1,3})(?:\.\d+)?\s*$"),
)

# An explicit "I don't know". Checked BEFORE the number patterns, because a
# refusal often still contains digits ("no data ... out of 100").
_REFUSAL_RE = re.compile(
    r"\b(unknown|insufficient (?:information|data)|not enough (?:information|data)|"
    r"cannot (?:provide|determine|assess)|unable to (?:provide|determine|assess)|"
    r"no (?:public|reliable|specific) (?:information|data)|"
    r"not available|n/?a\b|no data|"
    r"i (?:do not|don't) have)\b",
    re.I,
)


def build_score_query(
    company: str,
    axis_label: str,
    parameters: list[str],
    *,
    market: str = "",
    context: str = "",
) -> str:
    """One consolidated scoring question for a single axis.

    Name the company, say what market it is being judged in, name the axis,
    ask for the unweighted average of the named parameters, out of 100.

    The market and context matter. Asked cold, AI Mode answers UNKNOWN for any
    company that is not a household name — including ones it can clearly
    describe when the same name is typed into ordinary Google search. Telling
    it the market, and that a small regional player is a legitimate LOW score
    rather than an unanswerable question, is what turns those into numbers.
    """
    params = [str(p).strip() for p in parameters if str(p).strip()]
    listed = "\n".join(params)
    where = f" in the {market}" if str(market).strip() else ""
    about = f"\nAbout this company: {context.strip()}" if str(context).strip() else ""
    return (
        f"Provide a single, consolidated {axis_label} score out of 100 for "
        f"the company {company}{where} by calculating the unweighted average "
        f"of these {len(params)} parameters:\n{listed}{about}\n"
        # No scoring guide. The five parameters ARE the rubric — they are
        # generated per market for exactly this purpose, and a general band
        # table ("global leader", "best-in-class") pulls the answer toward a
        # size or reputation judgement instead of the parameters themselves.
        #
        # Two lines remain, and neither grades the company. The first says a
        # weak answer is permitted, because without it an obscure company is
        # answered "0" (which normalises to a fabricated 65) or "UNKNOWN".
        # The second keeps the reply parseable.
        "Rate each parameter from 1 to 100 and reply with their unweighted "
        "average. A low score is a valid answer.\n"
        "Reply with ONLY the number. Reply UNKNOWN only if you cannot "
        "identify this company at all."
    )


# How many companies go into one scoring query. Measured against the URL
# budget: 30 names plus the axis block is roughly 2.5 KB encoded, well inside
# the 7800-char ceiling. One query per 30 companies instead of one per company
# cuts a 230-company market from ~460 paced queries to ~16, which is also
# ~460 fewer chances to draw a CAPTCHA or trip the AI-response quota.
DEFAULT_SCORE_BATCH = 30


def build_batch_score_query(
    companies: list[str],
    axis_label: str,
    parameters: list[str],
    *,
    market: str = "",
) -> str:
    """One scoring question for MANY companies on a single axis.

    Companies are numbered and the reply is asked for as JSON keyed by that
    number, not by name: a returned name has to be matched back by string,
    and AI Mode reliably reformats them ("Co., Ltd." -> "Co Ltd"), which
    silently loses rows. An index cannot drift.
    """
    params = [str(p).strip() for p in parameters if str(p).strip()]
    listed = "\n".join(params)
    where = f" in the {market}" if str(market).strip() else ""
    numbered = "\n".join(f"{i}. {c}" for i, c in enumerate(companies, 1))
    return (
        f"For EACH of the {len(companies)} companies below, give a single "
        f"consolidated {axis_label} score out of 100{where}, calculated as "
        f"the unweighted average of these {len(params)} parameters:\n"
        f"{listed}\n\n"
        f"Companies:\n{numbered}\n\n"
        "Rate each parameter from 1 to 100 and average them. A low score is "
        "a valid answer. Score every company; use null ONLY for one you "
        "cannot identify at all.\n"
        'Reply with ONLY compact JSON keyed by the number above: '
        '{"scores":{"1":72,"2":45,"3":null}}'
    )


# What counts as EVIDENCE differs by axis, and saying so matters.
#
# Asked the same way on both, the model answers Product Strength with named
# systems and figures but Business Strength with unfalsifiable phrases --
# "maintains core technical partnerships", "a stream of high-value
# contracts". Measured on a finished market, 45% of Business claims carried
# no number at all against 15% of Product claims.
#
# Naming the KINDS of fact that constitute commercial proof turns that into
# a checkable question: a customer, a contract, a revenue figure, a count of
# sites. The instruction is per-axis, so neither one dilutes the other.
_EVIDENCE_HINT: dict[str, str] = {
    AXIS_X_LABEL: (
        "Good evidence here is a named product or model, a technical "
        "specification, a certification or standard, a facility, or a "
        "measured figure."
    ),
    AXIS_Y_LABEL: (
        "Good evidence here is COMMERCIAL fact: a named customer or "
        "contract and its value, revenue or growth figures, funding raised, "
        "headcount, number of sites, offices or countries served, units "
        "shipped or deployed, market share, or a named partner and what the "
        "partnership actually does. A phrase like \"strong partnerships\", "
        "\"growing presence\" or \"a stream of contracts\" is NOT evidence -- "
        "name the partner, the customer, the figure or the date. If a "
        "specific figure is genuinely not public, say what IS documented "
        "(a named client, a tender won, a stated deployment) rather than "
        "describing the company in general terms."
    ),
}


def evidence_hint(axis_label: str) -> str:
    """The axis-specific definition of what counts as evidence."""
    return _EVIDENCE_HINT.get(axis_label, "")


def build_defined_small_group_query(
    company: str,
    params: list[str],
    definitions: dict[str, str],
    *,
    market: str = "",
    market_definition: str = "",
    context: str = "",
    headquarters: str = "",
) -> str:
    """1 or 2 parameters, each judged against its OPERATOR-WRITTEN definition.

    build_defined_parameter_score_query() asks for all 5 parameters of an
    axis in one query. Under real load that reliably collapsed to a single
    synthesized summary paragraph with no per-parameter breakdown at all --
    confirmed live, twice, even with an explicit numbered checklist and
    repeated "do not summarise" warnings stated at the start, middle and
    end of the prompt. The model plainly computes the individual numbers
    (they showed up embedded IN the summary prose) but will not commit to
    the structured format across 5 parameters in a single answer.

    A SMALL group -- 1 or 2 parameters -- does not hit that failure
    (confirmed live for both sizes: 1 parameter and 2 parameters each
    returned a full, separately-scored, separately-evidenced section on the
    first attempt). Asking for 2 at once instead of 1 halves the fallback
    query count for whatever the cheap 5-in-1 axis query missed, at the
    same reliability.
    """
    params = [p for p in params if str(p).strip()]
    if not params:
        raise ValueError("build_defined_small_group_query needs at least one parameter")
    where = f" in the {market}" if str(market).strip() else ""
    scope = (
        f"\nMARKET DEFINITION: {market_definition.strip()}"
        if str(market_definition).strip() else ""
    )
    bits = []
    if str(headquarters).strip():
        bits.append(f"headquartered in {headquarters.strip()}")
    if str(context).strip():
        bits.append(context.strip())
    about = f"\nAbout this company: {'; '.join(bits)}" if bits else ""

    if len(params) == 1:
        count_phrase = "this ONE parameter"
        all_phrase = "this ONE parameter"
    else:
        count_phrase = f"these {len(params)} parameters"
        all_phrase = f"ALL {len(params)} parameters"

    listed = "\n\n".join(
        f"{i}. {p}\n   WHAT THIS MEASURES: {definitions.get(p, '')}"
        for i, p in enumerate(params, 1)
    )
    sections = "\n\n".join(
        f"{i}. {p}\n"
        "Evidence: <first specific finding — named project, client, "
        "facility, algorithm, figure or case study — and its source>\n"
        "Evidence: <a SECOND, different finding>\n"
        "Assessed on: <one sentence: which parts of WHAT THIS MEASURES you "
        "verified, which you could not, and why that puts it in this "
        "score band>\n"
        "Score: NN / 100"
        for i, p in enumerate(params, 1)
    )
    group_reminder = (
        "Score ONLY against WHAT THIS MEASURES above, not your own idea "
        "of the parameter."
        if len(params) == 1 else
        f"You must give {all_phrase} their own separate, numbered section "
        "-- a single combined answer is not acceptable. Score each ONLY "
        "against its own WHAT THIS MEASURES, not your own idea of the "
        "parameter."
    )
    return (
        f"Evaluate the company {company}{where} on {count_phrase}:"
        f"{scope}{about}\n\n{listed}\n\n"
        f"Search for real evidence, then answer in EXACTLY this format"
        f"{' -- ' + all_phrase + ', each with its own section' if len(params) > 1 else ''}:\n\n"
        f"{sections}\n\n"
        "SCORING SCALE: 85-100 market-leading, third-party verified. "
        "70-84 clear verifiable capability, not leading-edge. 55-69 "
        "present but partial or self-reported evidence. 40-54 weak or "
        "unproven on this measure. 1-39 little or no evidence.\n\n"
        f"{group_reminder} Use only real sources. Do not invent a source "
        "or a figure. Where you cannot verify something, say so in "
        "'Assessed on' and score it lower rather than assuming it is true."
    )


def build_forced_score_query(
    company: str,
    param: str,
    definitions: dict[str, str],
    *,
    market: str = "",
    market_definition: str = "",
    context: str = "",
    headquarters: str = "",
) -> str:
    """Single-parameter query for stragglers that refused to score at all.

    build_defined_small_group_query() is reliable at producing a
    structured, per-parameter section, but a company with genuinely thin
    public information can still make the model answer with something like
    "insufficient information to score" and no "Score: NN / 100" line --
    parse_small_group_scores() then finds no match and the parameter stays
    permanently empty no matter how many times the same query is retried.
    This variant is explicit that a low score for weak/absent evidence is
    the CORRECT answer, not a failure to find enough -- it must never
    refuse to output a number.
    """
    where = f" in the {market}" if str(market).strip() else ""
    scope = (
        f"\nMARKET DEFINITION: {market_definition.strip()}"
        if str(market_definition).strip() else ""
    )
    bits = []
    if str(headquarters).strip():
        bits.append(f"headquartered in {headquarters.strip()}")
    if str(context).strip():
        bits.append(context.strip())
    about = f"\nAbout this company: {'; '.join(bits)}" if bits else ""
    definition = str(definitions.get(param) or "").strip()
    return (
        f"Evaluate the company {company}{where} on this ONE parameter:"
        f"{scope}{about}\n\n"
        f"{param}\n   WHAT THIS MEASURES: {definition}\n\n"
        "Search for real evidence, then answer in EXACTLY this format:\n\n"
        "Evidence: <best specific finding you can locate, or 'No public "
        "evidence located' if genuinely none exists>\n"
        "Evidence: <a second finding if one exists, else omit this line>\n"
        "Assessed on: <one sentence: what you found or could not find, and "
        "why that puts it in this score band>\n"
        "Score: NN / 100\n\n"
        "SCORING SCALE: 85-100 market-leading, third-party verified. "
        "70-84 clear verifiable capability, not leading-edge. 55-69 "
        "present but partial or self-reported evidence. 40-54 weak or "
        "unproven on this measure. 1-39 little or no evidence.\n\n"
        "You MUST end your answer with a 'Score: NN / 100' line -- this is "
        "mandatory even if you found little or nothing on this company: "
        "sparse or absent evidence is itself a valid basis for a LOW score "
        "(use the 1-39 band), it is never a reason to withhold a number. "
        "Do not invent a source or a figure; do not write a prose summary "
        "instead of this format."
    )


def build_defined_parameter_score_query(
    company: str,
    axis_label: str,
    parameters: list[str],
    definitions: dict[str, str],
    *,
    market: str = "",
    market_definition: str = "",
    context: str = "",
    headquarters: str = "",
) -> str:
    """Per-parameter scores judged against OPERATOR-WRITTEN definitions.

    build_parameter_score_query() passes bare parameter NAMES, so the model
    invents its own reading of what "Turnaround Time" or "Price-to-Value
    Positioning" is worth measuring -- two companies then get scores that
    are not on the same scale, and the stored evidence explains the company
    rather than the score. Here each parameter carries the operator's own
    "what it measures" text, and the reply must name which of those stated
    criteria it actually found evidence for, so a score is auditable against
    the definition it was supposed to be measured by.

    Output shape is deliberately identical to build_parameter_score_query()
    (numbered heading, Evidence lines, "Score: NN / 100") so
    parse_parameter_scores() reads both without a branch.
    """
    params = [str(p).strip() for p in parameters if str(p).strip()]
    blocks = []
    for i, p in enumerate(params, 1):
        definition = str(definitions.get(p) or "").strip()
        blocks.append(f"{i}. {p}\n   WHAT THIS MEASURES: {definition}" if definition else f"{i}. {p}")
    numbered = "\n".join(blocks)
    where = f" in the {market}" if str(market).strip() else ""
    scope = (
        f"\nMARKET DEFINITION: {market_definition.strip()}"
        if str(market_definition).strip() else ""
    )
    bits = []
    if str(headquarters).strip():
        bits.append(f"headquartered in {headquarters.strip()}")
    if str(context).strip():
        bits.append(context.strip())
    about = f"\nAbout this company: {'; '.join(bits)}" if bits else ""
    first = params[0] if params else "the first parameter"
    checklist = "\n".join(f"[ ] {i}. {p}" for i, p in enumerate(params, 1))
    # The "do not summarise" warning used to sit AFTER the format template,
    # said once. Under concurrent load the model reverted to AI Mode's
    # default behaviour -- a single synthesized overview paragraph with no
    # per-parameter breakdown at all (confirmed live: 0/5 parsed on a query
    # that had real per-project evidence sitting right there in its own
    # search results). Leading with the instruction, repeating it, and
    # giving the model a checklist to complete is what a one-line warning
    # buried at the end could not do.
    return (
        f"You must score EACH of these {len(params)} parameters SEPARATELY "
        "for the company below -- a single overall paragraph or a composite-"
        "only answer is NOT an acceptable reply, no matter how well "
        "supported. Score PARAMETER BY PARAMETER, in order:\n\n"
        f"{checklist}\n\n"
        f"Evaluate the company {company}{where} on {axis_label}.{scope}{about}\n\n"
        f"Each parameter states EXACTLY what it measures -- score ONLY "
        f"against that stated measure, not against your own idea of the "
        f"parameter:\n\n{numbered}\n\n"
        "Answer in EXACTLY this format -- ONE numbered section per "
        "parameter above, giving EVERY parameter its own score, in the "
        "SAME order as the checklist:\n\n"
        f"1. {first}\n"
        "Evidence: <first specific finding — named project, client, "
        "facility, algorithm, figure or case study — and its source>\n"
        "Evidence: <a SECOND, different finding for this same parameter>\n"
        "Evidence: <a THIRD finding, if one genuinely exists>\n"
        "Assessed on: <one sentence: which parts of WHAT THIS MEASURES you "
        "verified, which you could not, and why that puts it in this score "
        "band>\n"
        "Score: NN / 100\n\n"
        f"(repeat for parameter 2, 3, ... through {len(params)} -- EVERY "
        "parameter in the checklist needs its own numbered section)\n\n"
        f"Composite {axis_label} Score: NN / 100\n\n"
        "SCORING SCALE: 85-100 market-leading, third-party verified. "
        "70-84 clear verifiable capability, not leading-edge. 55-69 "
        "present but partial or self-reported evidence. 40-54 weak or "
        "unproven on this measure. 1-39 little or no evidence.\n\n"
        f"REMINDER: this is {len(params)} SEPARATE scores, one per "
        "parameter above, each with its own Evidence lines, its own "
        "'Assessed on' line and its own Score line. Do not merge them into "
        "one paragraph or one score. Do not offer to write a fuller report "
        "afterward -- give the full per-parameter breakdown now, in this "
        "reply.\n"
        f"{evidence_hint(axis_label)}\n"
        "Score each parameter relative to this market as a whole. Every "
        "parameter must get a number between 1 and 100.\n"
        "Use only real sources. Do not invent a source or a figure. Where "
        "you cannot verify something, say so in 'Assessed on' and score it "
        "lower rather than assuming it is true."
    )


def build_parameter_score_query(
    company: str,
    axis_label: str,
    parameters: list[str],
    *,
    market: str = "",
    context: str = "",
    headquarters: str = "",
) -> str:
    """Per-PARAMETER scores with the evidence behind each one.

    The consolidated query returns a single number, which is enough to plot a
    company but says nothing about WHY. This asks for each parameter
    separately, plus the claim and source that justify it, so the backend can
    keep an audit trail. The evidence never reaches the HTML — see
    html_report.build_view_model.
    """
    params = [str(p).strip() for p in parameters if str(p).strip()]
    numbered = "\n".join(f"{i}. {p}" for i, p in enumerate(params, 1))
    where = f" in the {market}" if str(market).strip() else ""
    # Identify the company properly. A bare trading name ("A-One Coated
    # Abrasive") is ambiguous and led the model to judge an abrasives maker
    # against semiconductor wafer parameters and return 0/100. The HQ and the
    # one-line description are already on the row, so they cost nothing.
    bits = []
    if str(headquarters).strip():
        bits.append(f"headquartered in {headquarters.strip()}")
    if str(context).strip():
        bits.append(context.strip())
    about = f"\nAbout this company: {'; '.join(bits)}" if bits else ""
    # Ask it to SEARCH and justify, then score. Demanding bare JSON up front
    # suppressed the research step and produced thin, generic claims; asking
    # for evidence first is what yields the specific, checkable findings
    # (named acquisitions, standards, percentages) this template is built on.
    first = params[0] if params else "the first parameter"
    return (
        f"Evaluate the company {company}{where} on {axis_label}.{about}\n\n"
        f"Score these {len(params)} parameters:\n{numbered}\n\n"
        # Spell out the layout. Left to its own devices the model answers in
        # one prose paragraph with a single number, which carries no
        # per-parameter breakdown at all — the exact failure this replaces.
        "Answer in EXACTLY this format, one numbered section per parameter, "
        "using the parameter names above:\n\n"
        f"1. {first}\n"
        # TWO OR THREE findings, not one. A single Evidence line is a
        # single sentence, and the report renders each finding as its own
        # bullet -- with one line there is nothing to break apart, and a
        # client reviewing a score sees one assertion instead of the
        # argument behind it.
        "Evidence: <first specific finding — named product, facility, "
        "standard or figure — and its source>\n"
        "Evidence: <a SECOND, different finding for this same parameter>\n"
        "Evidence: <a THIRD finding, if one genuinely exists>\n"
        "Score: NN / 100\n\n"
        "(then 2., 3., and so on for every parameter)\n\n"
        f"Composite {axis_label} Score: NN / 100\n\n"
        # Judge the company at what it does. Scoring an abrasives maker on
        # semiconductor wafer parameters produced a flat 0/100, which is a
        # category error rather than an assessment.
        f"{evidence_hint(axis_label)}\n"
        "Score each parameter relative to this market as a whole. If the "
        "company serves a different segment of this market than the "
        "parameter implies, score it on its own segment rather than giving "
        "0. Every parameter must get a number between 1 and 100.\n"
        "Use only real sources. Do not invent a source or a figure."
    )


# "Score: 92 / 100", "Score: 92/100", "**Score:** 92 / 100"
_PARAM_SCORE_RE = re.compile(
    r"score[:\s*]*\b(\d{1,3})\s*(?:/|out\s+of)\s*100", re.I
)
# "Composite Product Strength Score: 92 / 100" — the model's own aggregate.
_COMPOSITE_RE = re.compile(
    r"composite[^\n]{0,60}?score[:\s*]*\b(\d{1,3})\s*(?:/|out\s+of)\s*100", re.I
)
_URL_RE = re.compile(r"https?://[^\s)<>\]]+")


# Companies per parameter-detail query.
#
# Batching 5 makes the model compress: it drops the per-parameter evidence
# and returns bare numbers, which is the whole thing this pass exists to
# avoid. Measured against live AI Mode, 3 does NOT — evidence coverage was
# 100% at both 1 and 3, with findings as specific as "RESEPI payload
# ~0.9-1.2kg" and "tested endurance of 50 minutes".
#
# The cost of batching is blast radius, not quality: one CAPTCHA loses the
# whole batch, and there is no retry above this function. That is handled by
# falling back to per-company queries for whoever a batch misses (see
# score_parameters_for_companies), which caps a failure at one company while
# keeping the ~3x query saving.
#
# Override per run with AI_MODE_PARAM_BATCH. Kept at 1 by default so an
# existing run's behaviour does not change underneath it.
def _default_param_batch() -> int:
    import os

    try:
        value = int((os.getenv("AI_MODE_PARAM_BATCH") or "1").strip())
    except (TypeError, ValueError):
        return 1
    # Capped at 6. The batch query carries the worked example and the
    # per-company detail that keep the evidence intact (see
    # build_batch_parameter_query). Measured live, 10 collapses into a single
    # summary paragraph with no per-company blocks at all, so the ceiling is
    # real -- 6 leaves headroom below it without inviting that failure.
    return value if 1 <= value <= 6 else 1


DEFAULT_PARAM_BATCH = _default_param_batch()


def build_batch_parameter_query(
    companies: list[str],
    axis_label: str,
    parameters: list[str],
    *,
    market: str = "",
    context_by_company: dict[str, str] | None = None,
    hq_by_company: dict[str, str] | None = None,
) -> str:
    """Evidence-backed parameter scores for SEVERAL companies, one axis.

    Companies are lettered (A, B, C...) and parameters numbered, so a reply
    can be attributed without matching on company names -- AI Mode reformats
    those ("Co., Ltd." -> "Co Ltd") and a name match silently loses rows.

    This mirrors the single-company query deliberately. An earlier version
    asked for the same data in three terse lines and the model answered with
    a compressed table of bare numbers, dropping the evidence that the whole
    pass exists to collect. What brings the evidence back is the same four
    things the single-company prompt has:

      * a WORKED EXAMPLE of the exact layout, so the shape is copied rather
        than invented,
      * each company identified by HQ and description, so a trading name is
        not judged against the wrong segment,
      * the "score it on its own segment rather than giving 0" rule, and
      * "every parameter must get a number between 1 and 100".

    Per-company detail is what makes this safe to batch: without it the model
    conflates similarly named firms and the batch is worse than useless.
    """
    params = [str(p).strip() for p in parameters if str(p).strip()]
    numbered = "\n".join(f"{i}. {p}" for i, p in enumerate(params, 1))

    # Identify each company the way the single-company query does. A bare
    # trading name led the model to judge an abrasives maker against
    # semiconductor parameters and return 0/100; in a batch that error
    # compounds across every company in the group.
    lines = []
    for i, c in enumerate(companies):
        bits = []
        hq = str((hq_by_company or {}).get(c, "")).strip()
        ctx = str((context_by_company or {}).get(c, "")).strip()
        if hq:
            bits.append(f"headquartered in {hq}")
        if ctx:
            bits.append(ctx)
        suffix = f" — {'; '.join(bits)}" if bits else ""
        lines.append(f"{chr(65 + i)}. {c}{suffix}")
    lettered = "\n".join(lines)

    where = f" in the {market}" if str(market).strip() else ""
    first = params[0] if params else "the first parameter"
    second = params[1] if len(params) > 1 else "the second parameter"
    a_name = companies[0] if companies else "the first company"
    b_name = companies[1] if len(companies) > 1 else "the second company"
    last_letter = chr(65 + len(companies) - 1) if companies else "A"

    n_lines = len(companies) * (len(params) * 2 + 2)
    return (
        # Lead with the OUTPUT SHAPE. Asked to "evaluate these 10
        # companies", the model answered with one summary paragraph
        # about the market and no per-company blocks at all -- it read
        # the request as a research question rather than a form to fill.
        f"Produce a SCORING TABLE in the exact format below for all "
        f"{len(companies)} companies. Do not summarise, do not write an "
        f"introduction, and do not answer in prose: the reply must be "
        f"{len(companies)} labelled blocks and nothing else "
        f"(about {n_lines} lines).\n\n"
        f"Companies to score{where}:\n{lettered}\n\n"
        f"Score these {len(params)} parameters for EVERY company:\n"
        f"{numbered}\n\n"
        # The worked example is the load-bearing part. Without it the model
        # compresses a multi-company answer into a table of bare numbers.
        "Answer in EXACTLY this format. Repeat the whole block for every "
        "company, keeping its letter and name as the heading:\n\n"
        f"A. {a_name}\n"
        f"1. {first}\n"
        "Evidence: <first specific finding — named product, facility, "
        "standard or figure — and its source>\n"
        "Evidence: <a SECOND, different finding for this same parameter>\n"
        "Evidence: <a THIRD finding, if one genuinely exists>\n"
        "Score: NN / 100\n"
        f"2. {second}\n"
        "Evidence: <first finding for this parameter and its source>\n"
        "Evidence: <a second, different finding>\n"
        "Score: NN / 100\n"
        "(then the remaining parameters, in order)\n"
        f"Composite {axis_label} Score: NN / 100\n\n"
        f"B. {b_name}\n"
        "(the same block again, for this company)\n\n"
        f"...continue through {last_letter}.\n\n"
        f"CHECK BEFORE ANSWERING: your reply must contain exactly "
        f"{len(companies)} blocks, one per company letter A-{last_letter}, "
        f"each with {len(params)} numbered parameters, and each parameter "
        f"must carry AT LEAST TWO Evidence lines and one Score line, plus "
        f"one Composite line per company. That is at least "
        f"{len(companies) * len(params) * 2} Evidence lines in total.\n"
        "Each Evidence line must be a DIFFERENT fact — do not restate the "
        "same finding in other words, and do not pad with generic "
        "description. If only one fact is genuinely documented for a "
        "parameter, give one rather than inventing a second.\n"
        "Do not write an opening summary. Do not merge companies. Do not "
        "answer with a markdown table. Do not summarise several "
        "parameters into one line. Do not skip a company.\n"
        f"{evidence_hint(axis_label)}\n"
        "Score each parameter relative to this market as a whole. If a "
        "company serves a different segment of this market than the "
        "parameter implies, score it on its own segment rather than giving "
        "0. Every parameter must get a number between 1 and 100.\n"
        "Use only real sources. Do not invent a source or a figure."
    )


def parse_batch_parameter_scores(
    answer: str, companies: list[str], parameters: list[str], prompt: str = ""
) -> dict[str, dict[str, Any]]:
    """{company: {"parameters": {...}, "composite": int|None}} from one reply.

    The answer is split on the company letters first, then each block is read
    by the same per-company prose parser — so one company's evidence can never
    be attributed to another.
    """
    body = answer_body(answer, prompt)
    if not body:
        return {}

    bounds: list[tuple[int, str]] = []
    for i, name in enumerate(companies):
        letter = chr(65 + i)
        # "A." / "A)" / "**A.**" at a heading position, or the company's own
        # name as a heading when the model drops the letter.
        pattern = re.compile(
            rf"(?:^|\n|\s)[*#\s]*{letter}[.)]\s*[*#\s]*(?={re.escape(name[:18])}|\s|$)",
            re.I,
        )
        match = pattern.search(body)
        if not match:
            pattern = re.compile(rf"(?:^|\n)[*#\s]*{re.escape(name)}", re.I)
            match = pattern.search(body)
        if match:
            bounds.append((match.start(), name))
    if not bounds:
        return {}
    bounds.sort()

    out: dict[str, dict[str, Any]] = {}
    for i, (start, name) in enumerate(bounds):
        end = bounds[i + 1][0] if i + 1 < len(bounds) else len(body)
        block = body[start:end]
        detail = _parse_parameters_prose(block, parameters)
        if not detail:
            continue
        composite = _COMPOSITE_RE.search(block)
        out[name] = {
            "parameters": detail,
            "composite": int(composite.group(1)) if composite else None,
        }
    return out


def score_parameters_for_companies(
    companies: list[str],
    *,
    x_parameters: list[str],
    y_parameters: list[str],
    ask: Any = None,
    market: str = "",
    batch: int = DEFAULT_PARAM_BATCH,
    on_batch: Any = None,
    context_by_company: dict[str, str] | None = None,
    hq_by_company: dict[str, str] | None = None,
    x_definitions: dict[str, str] | None = None,
    y_definitions: dict[str, str] | None = None,
    market_definition: str = "",
    x_axis_label: str = AXIS_X_LABEL,
    y_axis_label: str = AXIS_Y_LABEL,
    skip_batch: bool = False,
    group_size: int = 2,
) -> dict[str, dict[str, Any]]:
    """Parameter detail for many companies: 2 queries per batch of `batch`.

    Returns {company: score_detail}, the same shape score_company_detailed
    produces, so callers and the HTML view model are unchanged.

    When x_definitions / y_definitions are supplied, each parameter is
    scored against its OPERATOR-WRITTEN "what it measures" text and the
    reply must state which parts of that measure it verified -- see
    build_defined_parameter_score_query(). Without them the behaviour is
    unchanged, so existing callers keep the bare-name prompt.

    skip_batch=True goes straight to the small-group fallback (at
    group_size parameters per query, default 2) without first trying the
    5-in-1 axis query -- for callers who already know a company's batch
    query reliably fails (a persistent straggler after several runs) and
    would rather not spend a query confirming that again. group_size=1
    forces true one-parameter-at-a-time, the most reliable and slowest
    path, for stragglers that even the group-of-2 fallback missed.
    """
    if ask is None:
        from vendor_intel.scraping.google_ai_mode import ask as _ask

        ask = _ask

    names = [str(c).strip() for c in companies if str(c).strip()]
    out: dict[str, dict[str, Any]] = {}
    size = max(1, int(batch or DEFAULT_PARAM_BATCH))

    def _ask_defined_params_one_by_one(
        company: str, label: str, params: list[str], definitions: dict[str, str],
        already: dict[str, dict[str, Any]] | None = None,
        group_size: int = 2,
    ) -> dict[str, dict[str, Any]] | None:
        """The parameters NOT already in `already`, `group_size` per query.

        Only used as a fallback for whichever parameters the cheap 5-in-1
        query (build_defined_parameter_score_query) failed to parse -- that
        query costs one call for the whole axis and works most of the time;
        it only reliably collapses into an unparseable summary paragraph
        under load, and even then usually still yields SOME parameters (the
        model embeds the scores in its prose even when it drops the
        required format). A group of 2 (confirmed live: reliably returns
        both parameters, fully evidenced, on the first attempt -- same
        success rate as 1-at-a-time) halves the fallback query count versus
        asking one at a time, at no cost in reliability. A caller that
        already knows a company is a persistent straggler (failed the 5-in-1
        across several runs) can force group_size=1 for the most reliable,
        if slowest, path.

        Returns None only if EVERY parameter failed to parse.
        """
        def _ask_group(group: list[str]) -> dict[str, dict[str, Any]]:
            query = build_defined_small_group_query(
                company, group, definitions, market=market,
                market_definition=market_definition,
                context=(context_by_company or {}).get(company, ""),
                headquarters=(hq_by_company or {}).get(company, ""),
            )
            try:
                answer = ask(query)
            except Exception as err:  # noqa: BLE001
                print(f"      · params {group!r} for {company}: "
                      f"{type(err).__name__}: {str(err)[:90]}", flush=True)
                return {}
            return parse_small_group_scores(answer, group, query)

        detail: dict[str, dict[str, Any]] = dict((already or {}))
        missing = [p for p in params if p not in detail]
        size = max(1, int(group_size or 2))
        for i in range(0, len(missing), size):
            group = missing[i : i + size]
            got = _ask_group(group)
            detail.update(got)
            # A group of >1 that came back short (this group's own query
            # failed or dropped a parameter) is retried ONE AT A TIME before
            # moving on -- without this, a pair that fails together was
            # silently dropped for good: confirmed live, the same two
            # parameters (e.g. "Customer Feedback / Peer Standing" +
            # "Delivery Reliability") kept going missing together across
            # dozens of companies because nothing ever asked about them
            # again once their shared group query failed once.
            still_missing = [p for p in group if p not in got]
            for p in still_missing:
                one = _ask_group([p])
                detail.update(one)
        if not detail:
            return None
        return {company: {"parameters": detail, "composite": None}}

    def _ask_axis(
        group: list[str], label: str, params: list[str], tag: str,
        definitions: dict[str, str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """One axis for one group of companies. {} when the query fails."""
        # One company: use the single-company prompt, which asks the model
        # to search and justify. The multi-company form makes it compress
        # to bare numbers and drop the evidence entirely.
        single = len(group) == 1
        if single and definitions:
            company = group[0]
            if skip_batch:
                print(f"      · params {tag} {label}: skipping 5-in-1 for "
                      f"{company} (known straggler) -- asking "
                      f"{group_size} at a time", flush=True)
                result = _ask_defined_params_one_by_one(
                    company, label, params, definitions, group_size=group_size
                )
                return result or {}
            query = build_defined_parameter_score_query(
                company, label, params, definitions, market=market,
                market_definition=market_definition,
                context=(context_by_company or {}).get(company, ""),
                headquarters=(hq_by_company or {}).get(company, ""),
            )
            try:
                answer = ask(query)
                detail = parse_parameter_scores(answer, params, query)
            except Exception as err:  # noqa: BLE001
                print(f"      · params {tag} {label}: "
                      f"{type(err).__name__}: {str(err)[:90]}", flush=True)
                detail = {}
            missing_params = [p for p in params if p not in detail]
            if missing_params:
                # The 5-in-1 query either failed outright or collapsed to a
                # summary that yielded fewer than 5 parameters -- ask
                # one-by-one for exactly the gap rather than redoing the
                # whole axis.
                print(f"      · params {tag} {label}: 5-in-1 query "
                      f"returned {len(detail)}/{len(params)} for {company} "
                      f"-- asking {len(missing_params)} at a time in "
                      f"groups of {group_size}", flush=True)
                result = _ask_defined_params_one_by_one(
                    company, label, missing_params, definitions, already=detail,
                    group_size=group_size,
                )
                return result or {}
            return {company: {"parameters": detail, "composite": parse_composite_score(answer, query)}}
        elif single:
            query = build_parameter_score_query(
                group[0], label, params, market=market,
                context=(context_by_company or {}).get(group[0], ""),
                headquarters=(hq_by_company or {}).get(group[0], ""),
            )
        else:
            query = build_batch_parameter_query(
                group, label, params, market=market,
                context_by_company=context_by_company,
                hq_by_company=hq_by_company,
            )
        try:
            answer = ask(query)
        except Exception as err:  # noqa: BLE001
            print(
                f"      · params {tag} {label}: "
                f"{type(err).__name__}: {str(err)[:90]}",
                flush=True,
            )
            return {}
        if single:
            detail = parse_parameter_scores(answer, params, query)
            if not detail:
                return {}
            return {
                group[0]: {
                    "parameters": detail,
                    "composite": parse_composite_score(answer, query),
                }
            }
        return parse_batch_parameter_scores(answer, group, params, query)

    for start in range(0, len(names), size):
        chunk = names[start : start + size]
        per_axis: dict[str, dict[str, dict[str, Any]]] = {}
        for key, label, params, defs in (
            ("x", x_axis_label, x_parameters, x_definitions),
            ("y", y_axis_label, y_parameters, y_definitions),
        ):
            tag = f"[{start + 1}-{start + len(chunk)}]"
            got = _ask_axis(chunk, label, params, tag, defs)

            # Fall back to one query per company for whoever the batch did
            # not return. A batched query is ~3x cheaper, but one CAPTCHA
            # loses the WHOLE batch, and the scorer has no retry above this
            # point -- those companies would simply ship unscored. Retrying
            # only the missing ones keeps the cheap path and caps the blast
            # radius of a failure at one company.
            missing = [n for n in chunk if n not in got] if len(chunk) > 1 else []
            if missing:
                print(
                    f"      · params {tag} {label}: batch returned "
                    f"{len(got)}/{len(chunk)} — retrying {len(missing)} singly",
                    flush=True,
                )
                for name in missing:
                    one = _ask_axis([name], label, params, tag, defs)
                    if one:
                        got.update(one)
            per_axis[key] = got

        for name in chunk:
            record: dict[str, Any] = {}
            for key, label in (("x", x_axis_label), ("y", y_axis_label)):
                got = per_axis.get(key, {}).get(name) or {}
                detail = got.get("parameters") or {}
                composite = got.get("composite")
                score = composite
                if score is None and detail:
                    values = [d["score"] for d in detail.values()]
                    score = int(round(sum(values) / len(values)))
                record[key] = {
                    "score": score,
                    "axis": label,
                    "composite_reported": composite,
                    "evidence": [e for d in detail.values() for e in d["evidence"]],
                    "parameters": detail,
                }
            out[name] = record
            # Save as soon as THIS company has both axes, not after the
            # whole chunk. A chunk of 6 companies whose batch query fails
            # falls back to up to 12 sequential single-company queries (6 x
            # 2 axes) before the old per-chunk callback ever fired --
            # real evidence was being generated the whole time (confirmed
            # live in the browser) but nothing reached disk until every
            # company in the chunk finished. One callback per company
            # means an interruption after company 1 of 6 still keeps company
            # 1's evidence.
            if on_batch is not None and record["x"]["parameters"] and record["y"]["parameters"]:
                on_batch(start, [name], {name: record})

        done = sum(
            1 for n in chunk if out[n]["x"]["parameters"] and out[n]["y"]["parameters"]
        )
        print(
            f"      · params [{start + 1}-{start + len(chunk)}]: "
            f"{done}/{len(chunk)} companies detailed",
            flush=True,
        )

    return out


def parse_composite_score(answer: str, prompt: str = "") -> int | None:
    """The model's own "Composite ... Score: N / 100", when it gave one."""
    body = answer_body(answer, prompt)
    match = _COMPOSITE_RE.search(body)
    if not match:
        return None
    try:
        value = int(match.group(1))
    except (TypeError, ValueError):
        return None
    return value if 1 <= value <= 100 else None


# --- Quick scorecard: ALL parameters of one axis in ONE query -------------
#
# Used to rank every verified company before the Top 20 are chosen. It asks
# for a SCORECARD -- one short line per parameter -- not the full
# Evidence / Assessed-on sections. The full format across 5 parameters is
# what collapsed into a single summary paragraph (see
# build_defined_small_group_query); a one-line-per-parameter scorecard is a
# far lighter answer, and the short reason on each line keeps AI Mode
# answering rather than echoing (a bare "reply with only the number" format
# failed that way). Deep evidence is gathered later, for the Top 20 only.

_SCORECARD_LINE_RE = re.compile(
    r"(?:score[:\s*]*)?\b(\d{1,3})\s*(?:/|out\s+of)\s*100", re.I
)


def build_axis_scorecard_query(
    company: str,
    axis_title: str,
    params: list[str],
    definitions: dict[str, str],
    *,
    market: str = "",
    market_definition: str = "",
) -> str:
    """One query: ``company``'s score on every parameter of one axis."""
    params = [p for p in params if str(p).strip()]
    if not params:
        raise ValueError("build_axis_scorecard_query needs at least one parameter")
    where = f" in the {market}" if str(market).strip() else ""
    scope = (
        f"\nMARKET DEFINITION: {market_definition.strip()}"
        if str(market_definition).strip() else ""
    )
    listed = "\n".join(
        f"{i}. {p}: {definitions.get(p, '')}".rstrip(": ")
        for i, p in enumerate(params, 1)
    )
    template = "\n".join(
        f"{i}. {p} | Score: NN/100 | <one short reason>"
        for i, p in enumerate(params, 1)
    )
    n = len(params)
    return (
        f"Give the {axis_title} scorecard for the company {company}{where}: "
        f"one score out of 100 for EACH of these {n} parameters.{scope}\n\n"
        f"{listed}\n\n"
        f"Search for real information, then reply with exactly {n} lines, "
        f"one per parameter, in this format:\n{template}\n\n"
        "SCORING SCALE: 85-100 market-leading, third-party verified. "
        "70-84 clear verifiable capability, not leading-edge. 55-69 present "
        "but partial or self-reported evidence. 40-54 weak or unproven on "
        "this measure. 1-39 little or no evidence.\n\n"
        f"Every one of the {n} parameters needs its own line and its own "
        "score -- do not merge them into one paragraph. Use only real "
        "information; where you cannot verify something, score it lower "
        "rather than assuming it is true."
    )


def parse_axis_scorecard(
    answer: str, params: list[str], prompt: str = ""
) -> dict[str, int]:
    """{parameter: score} for a reply to build_axis_scorecard_query(), only
    for parameters that parsed. Tolerates the numbered-line format asked
    for, a Markdown table, or prose -- each parameter's score is the first
    "NN/100" after its own name and before the next parameter's name.
    """
    nav_parts = _CONVERSATION_RE.split(answer or "")
    text = nav_parts[-1] if len(nav_parts) > 1 else (answer or "")
    flat = " ".join(text.split())
    if prompt:
        # AI Mode can echo the prompt (template included) before answering;
        # everything up to the LAST verbatim echo is not the answer.
        flat_prompt = " ".join(prompt.split())
        idx = flat.rfind(flat_prompt)
        if idx >= 0:
            flat = flat[idx + len(flat_prompt):]
    if not flat.strip():
        return {}

    bounds: list[tuple[int, str]] = []
    for name in params:
        match = re.search(re.escape(name), flat, re.I)
        if match:
            bounds.append((match.end(), name))
    bounds.sort()
    out: dict[str, int] = {}
    for i, (start, name) in enumerate(bounds):
        end = bounds[i + 1][0] if i + 1 < len(bounds) else len(flat)
        m = _SCORECARD_LINE_RE.search(flat[start:end])
        if not m:
            continue
        try:
            score = int(m.group(1))
        except (TypeError, ValueError):
            continue
        if 1 <= score <= 100:
            out[name] = score
    return out


def parse_small_group_scores(
    answer: str, params: list[str], prompt: str = ""
) -> dict[str, dict[str, Any]]:
    """{parameter_name: {"score", "evidence", "assessed_on"}} for a reply to
    build_defined_small_group_query() (1 or 2 parameters), keyed only by
    the parameters that actually parsed.

    Echo removal first: this prompt is instructed to render the placeholder
    "Score: NN / 100" and its own "Evidence:" labels, and AI Mode echoed it
    back TWICE in testing (once flattened, once with its original line
    breaks) before the real answer -- both copies survived answer_body()'s
    line-based echo stripper, which expects exactly one echo occurrence.
    Rather than patch that shared stripper (every other parser in this file
    depends on its current behaviour), this cuts past the LAST verbatim
    occurrence of the flattened prompt directly: whatever remains is
    guaranteed to be the model's own answer, never an echo.

    For a single parameter the remaining text IS the one section. For two,
    the real answer repeats each parameter's own name as a numbered
    heading ("1. <name>", "2. <name>") exactly as asked, so those bound
    each parameter's own Evidence/Assessed-on/Score block.
    """
    nav_parts = _CONVERSATION_RE.split(answer or "")
    text = nav_parts[-1] if len(nav_parts) > 1 else (answer or "")
    flat_text = " ".join(text.split())
    if prompt:
        flat_prompt = " ".join(prompt.split())
        idx = flat_text.rfind(flat_prompt)
        if idx >= 0:
            flat_text = flat_text[idx + len(flat_prompt):].strip()
    if not flat_text:
        return {}

    out: dict[str, dict[str, Any]] = {}
    if len(params) <= 1:
        matches = list(_PARAM_SCORE_RE.finditer(flat_text))
        if not matches:
            return {}
        score_match = matches[-1]
        try:
            score = int(score_match.group(1))
        except (TypeError, ValueError):
            return {}
        if not 1 <= score <= 100:
            return {}
        section = flat_text[: score_match.end()]
        entry: dict[str, Any] = {"score": score, "evidence": _section_evidence(section)}
        basis = _section_basis(section)
        if basis:
            entry["assessed_on"] = basis
        if params:
            out[params[0]] = entry
        return out

    # Two (or more) parameters: bound each one's section by its own
    # numbered heading, same approach _parse_parameters_prose uses for the
    # 5-in-1 query, just applied to the already echo-stripped remainder.
    bounds: list[tuple[int, int, str]] = []
    for idx, name in enumerate(params, 1):
        pattern = re.compile(
            rf"(?:^|(?<![\d.]))(?:{idx}[.)]\s*)?[*#\s]*{re.escape(name)}", re.I
        )
        match = pattern.search(flat_text)
        if match:
            bounds.append((match.start(), idx, name))
    if not bounds:
        return {}
    bounds.sort()
    for i, (start, _idx, name) in enumerate(bounds):
        end = bounds[i + 1][0] if i + 1 < len(bounds) else len(flat_text)
        section = flat_text[start:end]
        score_match = _PARAM_SCORE_RE.search(section)
        if not score_match:
            continue
        try:
            score = int(score_match.group(1))
        except (TypeError, ValueError):
            continue
        if not 1 <= score <= 100:
            continue
        entry = {"score": score, "evidence": _section_evidence(section)}
        basis = _section_basis(section)
        if basis:
            entry["assessed_on"] = basis
        out[name] = entry
    return out


def parse_parameter_scores(
    answer: str, parameters: list[str], prompt: str = ""
) -> dict[str, dict[str, Any]]:
    """{parameter_name: {"score": int, "evidence": [{claim, source}]}}.

    Handles both reply shapes: the numbered prose the evidence template
    produces ("1. Substrate & Epitaxy Quality / Evidence: ... / Score: 92 /
    100"), and compact JSON if the model returns that instead.

    A parameter the model could not rate is simply absent, so the caller can
    tell a missing score from a low one. Evidence is never invented — a
    section with no prose yields an empty list, not a placeholder.
    """
    body = answer_body(answer, prompt)
    if not body:
        return {}
    parsed = _parse_parameters_json(body, parameters)
    if parsed:
        return parsed
    return _parse_parameters_prose(body, parameters)


def _parse_parameters_json(
    body: str, parameters: list[str]
) -> dict[str, dict[str, Any]]:
    blob = _balanced_json(body)
    if not blob:
        return {}
    try:
        data = json.loads(blob)
    except Exception:  # noqa: BLE001
        return {}
    entries = data.get("parameters") if isinstance(data, dict) else None
    if not isinstance(entries, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, raw in entries.items():
        try:
            idx = int(str(key).strip())
        except (TypeError, ValueError):
            continue
        if not 1 <= idx <= len(parameters) or not isinstance(raw, dict):
            continue
        try:
            score = int(float(raw.get("score")))
        except (TypeError, ValueError):
            continue
        if not 1 <= score <= 100:
            continue
        out[parameters[idx - 1]] = {
            "score": score,
            "evidence": _evidence_item(
                str(raw.get("claim") or ""), str(raw.get("source") or "")
            ),
        }
    return out


def _parse_parameters_prose(
    body: str, parameters: list[str]
) -> dict[str, dict[str, Any]]:
    """Split the answer on the numbered parameter headings, then read each.

    Splitting on the heading (rather than scanning for scores globally) keeps
    a parameter's evidence attached to its own score even when the model
    reorders sections or adds commentary between them.
    """
    bounds: list[tuple[int, int, str]] = []
    for idx, name in enumerate(parameters, 1):
        # "1. Substrate & Epitaxy Quality", with optional bold/heading markup.
        # NOT anchored to line starts: the rendered page arrives as one
        # flattened line (answer_body normalises whitespace to strip the
        # echoed prompt), so ^/$ anchors would never match.
        # The number is OPTIONAL. Asked for "1. <name>", the model often
        # renders just "<name>" as a heading and drops the numbering, which
        # made a perfectly good reply parse as zero parameters.
        #
        # `(?<![\d.])` alone also fails when the heading is the very first
        # thing in the body — a lookbehind cannot match at position 0 — and
        # the live replies start exactly there.
        pattern = re.compile(
            rf"(?:^|(?<![\d.]))(?:{idx}[.)]\s*)?[*#\s]*{re.escape(name)}", re.I
        )
        match = pattern.search(body)
        if match:
            bounds.append((match.start(), idx, name))
    if not bounds:
        return {}
    bounds.sort()

    out: dict[str, dict[str, Any]] = {}
    for i, (start, _idx, name) in enumerate(bounds):
        end = bounds[i + 1][0] if i + 1 < len(bounds) else len(body)
        section = body[start:end]
        score_match = _PARAM_SCORE_RE.search(section)
        if not score_match:
            continue
        try:
            score = int(score_match.group(1))
        except (TypeError, ValueError):
            continue
        if not 1 <= score <= 100:
            continue
        entry: dict[str, Any] = {
            "score": score,
            "evidence": _section_evidence(section),
        }
        basis = _section_basis(section)
        if basis:
            entry["assessed_on"] = basis
        out[name] = entry
    return out


def _section_basis(section: str) -> str:
    """The "Assessed on:" rationale for one parameter, if the reply gave one.

    build_defined_parameter_score_query() asks the model to name which parts
    of the parameter's stated measure it actually found evidence for. That
    sentence is what justifies the NUMBER (the Evidence lines justify the
    facts), so it is stored separately rather than folded into the evidence
    list -- the report shows it as the "why this score" line.
    """
    match = re.search(
        r"assessed\s*on[:\s*]*(.+?)(?=[-*•]?\s*\**\s*score[:\s*]*\d|\Z)",
        section,
        re.I | re.S,
    )
    if not match:
        return ""
    text = re.sub(r"[*#]+", "", match.group(1))
    return " ".join(text.split()).strip(" -•:")


def _section_evidence(section: str) -> list[dict[str, str]]:
    """Every Evidence finding for one parameter, each as its own entry.

    The prompt asks for two or three findings per parameter, and the report
    renders each as its own bullet. Capturing the whole run as ONE claim
    would collapse them back into a single paragraph, which is the thing the
    multi-finding ask exists to avoid.

    Splitting is on the "Evidence:" labels themselves rather than on
    sentence boundaries: a single finding often spans two sentences ("...
    capacity of 180 kt. This was confirmed in the 2025 filing."), and those
    belong together.
    """
    # Everything between the first Evidence label and the Score marker,
    # which may sit mid-line once the page text has been flattened
    # ("... reliance. - Score: 92 / 100").
    # Stop at "Assessed on" as well as at Score: that line is the model's
    # rationale for the NUMBER, captured separately by _section_basis().
    # Without this bound it is swallowed into the final Evidence claim and
    # renders as a bullet that reads like a finding when it is not one.
    block = re.search(
        r"evidence[:\s*]*(.+?)"
        r"(?=[-*•]?\s*\**\s*assessed\s*on|[-*•]?\s*\**\s*score[:\s*]*\d|\Z)",
        section,
        re.I | re.S,
    )
    if not block:
        return []
    body = re.sub(r"[*#]+", "", block.group(1))

    # Later findings keep their own "Evidence:" label; the first one's label
    # was consumed by the match above.
    parts = re.split(r"(?:^|\n|\s)[-*•]?\s*evidence\s*[:\-]", body, flags=re.I)
    url = _URL_RE.search(section)
    source = url.group(0) if url else ""

    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for part in parts:
        claim = " ".join(part.split()).strip(" -•:")
        if not claim:
            continue
        key = claim.lower()
        if key in seen:
            continue
        seen.add(key)
        out.extend(_evidence_item(claim, source))
    return out


def _evidence_item(claim: str, source: str) -> list[dict[str, str]]:
    """One evidence entry, or none. Never fabricates a source for a claim."""
    claim = (claim or "").strip()
    if not claim:
        return []
    item = {"claim": claim}
    if source.strip():
        item["source"] = source.strip()
    return [item]


def score_axis_parameters(
    company: str,
    axis_label: str,
    parameters: list[str],
    *,
    ask: Any = None,
    market: str = "",
    context: str = "",
) -> tuple[dict[str, dict[str, Any]], int | None]:
    """One query: every parameter on one axis, plus the composite it gave.

    Returns ({parameter: {score, evidence}}, composite_or_None). The composite
    is the model's own "Composite <axis> Score", kept separate so the caller
    decides whether to use it or an average.
    """
    if not company or not parameters:
        return {}, None
    if ask is None:
        from vendor_intel.scraping.google_ai_mode import ask as _ask

        ask = _ask
    query = build_parameter_score_query(
        company, axis_label, parameters, market=market, context=context
    )
    try:
        answer = ask(query)
    except Exception as err:  # noqa: BLE001 - caller keeps the axis score
        print(
            f"      · params {company[:36]} [{axis_label}]: "
            f"{type(err).__name__}: {str(err)[:90]}",
            flush=True,
        )
        return {}, None
    return (
        parse_parameter_scores(answer, parameters, query),
        parse_composite_score(answer, query),
    )


def parse_batch_scores(
    answer: str, companies: list[str], prompt: str = ""
) -> dict[str, int]:
    """Map company name -> score from a batched reply.

    Missing, null and out-of-range entries are simply absent from the result,
    so a caller can tell exactly which companies still need scoring rather
    than being handed a zero.
    """
    body = answer_body(answer, prompt)
    out: dict[str, int] = {}
    if not body:
        return out
    blob = _balanced_json(body)
    if not blob:
        return out
    try:
        data = json.loads(blob)
    except Exception:  # noqa: BLE001
        return out
    scores = data.get("scores") if isinstance(data, dict) else None
    if not isinstance(scores, dict):
        return out
    for key, raw in scores.items():
        try:
            idx = int(str(key).strip())
        except (TypeError, ValueError):
            continue
        if not 1 <= idx <= len(companies):
            continue
        try:
            # Accept 72, "72" and 72.4 — averaging five integers gives a
            # decimal, and the model quotes numbers about half the time.
            value = int(float(raw))
        except (TypeError, ValueError):
            continue  # null / "UNKNOWN" -> leave the company unscored
        if 1 <= value <= 100:
            out[companies[idx - 1]] = value
    return out


def _balanced_json(text: str) -> str:
    """The first balanced {...} block, or "".

    A brace-counting scan, not a regex: the reply often has prose either side
    of the JSON, and `rfind("}")` over-reaches into trailing page furniture.
    """
    start = text.find("{")
    if start < 0:
        return ""
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return ""


# AI Mode's rendered page is returned whole: nav chrome, then the prompt
# echoed back (twice — once as "AI Mode conversation: <prompt>", once as the
# bubble), then the actual answer. Every one of those carries digits, so
# parsing the raw text scored the page furniture instead of the reply:
# four different companies all came back "10" (a nav digit), and a refusal
# came back "100" (from the prompt's own "out of 100").
_CONVERSATION_RE = re.compile(r"AI Mode conversation:\s*", re.I)
# Rendered after the reply ("88 AI Mode response is ready"), so a bare-number
# answer stops looking like a bare number.
_READY_MARKER_RE = re.compile(r"\s*AI Mode response is ready\s*", re.I)

# Furniture rendered AFTER the answer. Each of these turned a real score into
# a lost row: "20.4 Show Code", "43 AI responses may include mistakes...".
_TRAILING_NOISE_RE = re.compile(
    r"\s*(?:"
    r"Show Code|Show more|Show less|Sources|Learn more|"
    r"AI responses may include mistakes\.?.*|"
    r"For financial advice, consult a professional\.?.*|"
    r"Export|Copy|Share|Thumbs up|Thumbs down"
    r")\s*$",
    re.I,
)
_CHROME_PREFIX_RE = re.compile(
    r"^(?:skip to main content|accessibility help|ai mode|all|images|videos|"
    r"news|shopping|more|sign in|tools|short videos|web|maps|books|flights|"
    r"finance"
    # A bare Google URL line sits among the nav items and carries digits
    # (".co.in", "tab=wh"), so it must go too.
    r"|\(?https?://\S*google\.\S*\)?)\s*$",
    re.I,
)


# "A. Alpha Ltd" -- a lettered company heading. Present in a batched
# prompt AND in the answer that replies under it, so it must survive
# echo-stripping or the per-company split has nothing to split on.
_LETTERED_ITEM_RE = re.compile(r"^[*#\s]*[A-Z][.)]\s+\S")


def _echo_end_line(lines: list[str], flat_prompt: str) -> int:
    """Index just past the LAST run of lines that reproduces the prompt.

    The echo may span several lines (a multi-line prompt is rendered as
    written) or sit on one (a flattened bubble). Matching a consecutive run
    handles both, and stopping at a line boundary preserves the answer's own
    formatting — flattening the whole page instead used to merge every
    parameter section into a single unparseable line.
    """
    end = 0
    for start in range(len(lines)):
        joined = ""
        for i in range(start, len(lines)):
            part = " ".join(lines[i].split())
            joined = f"{joined} {part}".strip() if joined else part
            if joined == flat_prompt:
                end = i + 1
                break
            if not flat_prompt.startswith(joined):
                break
    return end


def answer_body(answer: str, prompt: str = "") -> str:
    """The model's reply with page chrome and the echoed prompt removed.

    When the prompt is known, every echo of its lines is dropped — that is the
    reliable signal, since AI Mode reproduces the question verbatim before
    answering. Otherwise only the nav chrome is stripped.
    """
    text = answer or ""
    # The nav sits before this marker; the prompt echo and the answer after.
    parts = _CONVERSATION_RE.split(text)
    if len(parts) > 1:
        text = parts[-1]

    if prompt:
        # The echo is the whole prompt rendered as ONE line with its newlines
        # collapsed, so line-by-line matching never sees it. Cut past the last
        # echo that appears in the LEADING part of the page — a prompt long
        # enough to be echoed can also occur by coincidence inside a long
        # answer, and cutting there discarded the reply.
        flat_prompt = " ".join(prompt.split())
        if flat_prompt:
            lines = text.split("\n")
            keep_from = _echo_end_line(lines, flat_prompt)
            if keep_from:
                # The echo occupied whole lines, so cutting at a line boundary
                # leaves the answer's own line structure intact — which the
                # prose parser needs to tell one parameter section from the
                # next.
                text = "\n".join(lines[keep_from:])
            else:
                flat_text = " ".join(text.split())
                idx = flat_text.find(flat_prompt)
                if idx >= 0:
                    text = flat_text[idx + len(flat_prompt) :].strip()
                else:
                    # Last resort: drop lines that repeat the prompt.
                    #
                    # EXCEPT the lettered company list. A batched prompt
                    # lists "A. Alpha Ltd", and the model answers under
                    # that same heading -- dropping it destroys the
                    # company boundaries parse_batch_parameter_scores
                    # splits on, so a perfectly good batch reply parsed
                    # as zero companies.
                    echoed = {
                        ln.strip()
                        for ln in prompt.split("\n")
                        if ln.strip() and not _LETTERED_ITEM_RE.match(ln.strip())
                    }
                    text = "\n".join(
                        ln for ln in text.split("\n") if ln.strip() not in echoed
                    )

    # The page appends its own completion marker after the reply, which breaks
    # the "the whole answer is one number" match.
    text = _READY_MARKER_RE.sub(" ", text)
    # Strip trailing furniture repeatedly: "43 AI responses may include
    # mistakes. ... Learn more" carries two of them in sequence.
    for _ in range(4):
        stripped = _TRAILING_NOISE_RE.sub("", text).strip()
        if stripped == text.strip():
            break
        text = stripped
    kept = [ln for ln in text.split("\n") if not _CHROME_PREFIX_RE.match(ln.strip())]
    return "\n".join(kept).strip()


def parse_score(answer: str, prompt: str = "") -> int | None:
    """Pull the 1-100 score out of a rendered AI Mode answer.

    Returns None rather than a guess when no defensible number is present —
    the row is then left unscored for a later retry instead of carrying an
    invented number.

    A bare ``0`` is treated as NO ANSWER, not as a score. AI Mode replies "0"
    when it has never heard of a company, and a real market participant does
    not have zero product strength. Taking it literally was actively harmful:
    ``normalize_row_score_floor(0, 0)`` returns ``(65, 65)``, so an unknown
    company was silently promoted to a mid-tier score and placed in a
    quadrant, indistinguishable from a company that had genuinely been
    assessed.
    """
    text = answer_body(answer, prompt).replace(",", "")
    if not text:
        return None
    if _REFUSAL_RE.search(text):
        return None
    for pattern in _SCORE_PATTERNS:
        for match in pattern.finditer(text):
            try:
                value = int(match.group(1))
            except (TypeError, ValueError):
                continue
            if 1 <= value <= 100:
                return value
    return None


_ZERO_REPLY_RE = re.compile(r"^\s*0(?:\.0+)?\s*$")


def _looks_like_zero(body: str) -> bool:
    """True when the whole reply is just "0" — a decline, not a rating.

    Distinguished from an unreadable reply because it has a specific, cheap
    remedy: ask again and say 0 is not on the scale.
    """
    return bool(_ZERO_REPLY_RE.match(body or ""))


def score_axis(
    company: str,
    axis_label: str,
    parameters: list[str],
    *,
    ask: Any = None,
    market: str = "",
    context: str = "",
) -> int | None:
    """Ask AI Mode for one axis score. None when unavailable or unparseable."""
    if not company or not parameters:
        return None
    if ask is None:
        from vendor_intel.scraping.google_ai_mode import ask as _ask

        ask = _ask
    query = build_score_query(
        company, axis_label, parameters, market=market, context=context
    )
    try:
        answer = ask(query)
    except Exception as err:  # noqa: BLE001 - row is left unscored for a retry
        # Say WHY. Swallowing this printed "AI Mode unavailable" for every
        # failure, so a quota block, a refusal and a parse failure were
        # indistinguishable in the log — and each needs a different response.
        print(
            f"      · score {company[:40]}: {type(err).__name__}: "
            f"{str(err)[:120]}",
            flush=True,
        )
        return None
    score = parse_score(answer, query)
    if score is None and _looks_like_zero(answer_body(answer, query)):
        # A bare "0" is the model declining, not a verdict — NXP Semiconductors
        # came back 0. These companies already passed market verification, so
        # dropping the row loses a real participant. Ask once more, saying
        # plainly that 0 is not available.
        retry_q = query + (
            "\n0 is NOT a valid answer. This company does operate in this "
            "market. Give your best estimate between 1 and 100, or UNKNOWN "
            "if you genuinely cannot identify the company."
        )
        try:
            answer = ask(retry_q)
            score = parse_score(answer, retry_q)
            query = retry_q
        except Exception:  # noqa: BLE001 - fall through to the unscored path
            pass
    if score is None:
        # Reached the model but could not read a number out of the reply.
        # That is a PARSE problem, not an availability one, and it is the
        # case most likely to be silently losing real scores.
        print(
            f"      · score {company[:40]}: unparsed reply "
            f"{answer_body(answer, query)[:100]!r}",
            flush=True,
        )
    # `query` is passed to parse_score so the echoed prompt can be stripped:
    # the rendered page repeats the question, and "score out of 100" in the
    # question would otherwise be read as the answer.
    return score


def score_company(
    company: str,
    *,
    x_parameters: list[str],
    y_parameters: list[str],
    ask: Any = None,
    market: str = "",
    context: str = "",
) -> tuple[int | None, int | None]:
    """Both axis scores for one company: (x, y). Either may be None."""
    x = score_axis(
        company, AXIS_X_LABEL, x_parameters, ask=ask, market=market, context=context
    )
    y = score_axis(
        company, AXIS_Y_LABEL, y_parameters, ask=ask, market=market, context=context
    )
    return x, y


def score_companies(
    companies: list[str],
    *,
    x_parameters: list[str],
    y_parameters: list[str],
    ask: Any = None,
    market: str = "",
    batch: int = DEFAULT_SCORE_BATCH,
    on_batch: Any = None,
) -> dict[str, tuple[int | None, int | None]]:
    """Score MANY companies: two queries per batch, not two per company.

    A 230-company market goes from ~460 paced queries to ~16. Beyond the time
    saved, each query is a chance to draw a CAPTCHA or trip the AI-response
    quota, and those blocks are what has repeatedly cost whole scoring runs.

    Returns {company: (x, y)}; either value may be None when the model could
    not identify that company. A company missing from a batch reply is simply
    left unscored rather than defaulted — a wrong number is worse than a gap.
    """
    if ask is None:
        from vendor_intel.scraping.google_ai_mode import ask as _ask

        ask = _ask

    names = [str(c).strip() for c in companies if str(c).strip()]
    out: dict[str, tuple[int | None, int | None]] = {n: (None, None) for n in names}
    size = max(1, int(batch or DEFAULT_SCORE_BATCH))

    for start in range(0, len(names), size):
        chunk = names[start : start + size]
        axis_scores: dict[str, dict[str, int]] = {}
        for axis, params in (
            (AXIS_X_LABEL, x_parameters),
            (AXIS_Y_LABEL, y_parameters),
        ):
            query = build_batch_score_query(chunk, axis, params, market=market)
            try:
                answer = ask(query)
                axis_scores[axis] = parse_batch_scores(answer, chunk, query)
            except Exception as err:  # noqa: BLE001
                # Name the failure. Swallowing it made a quota block, a
                # refusal and a parse failure look identical in the log.
                print(
                    f"      · batch {axis} [{start + 1}-{start + len(chunk)}]: "
                    f"{type(err).__name__}: {str(err)[:100]}",
                    flush=True,
                )
                axis_scores[axis] = {}

        xs = axis_scores.get(AXIS_X_LABEL, {})
        ys = axis_scores.get(AXIS_Y_LABEL, {})
        for name in chunk:
            out[name] = (xs.get(name), ys.get(name))
        got = sum(1 for n in chunk if out[n][0] is not None and out[n][1] is not None)
        print(
            f"      · batch [{start + 1}-{start + len(chunk)}]: "
            f"{got}/{len(chunk)} scored",
            flush=True,
        )
        if on_batch is not None:
            on_batch(start, chunk, out)

    return out


def score_company_detailed(
    company: str,
    *,
    x_parameters: list[str],
    y_parameters: list[str],
    ask: Any = None,
    market: str = "",
    context: str = "",
    x_score: int | None = None,
    y_score: int | None = None,
) -> dict[str, Any]:
    """The full backend record: axis scores, per-parameter scores, evidence.

    Shape (parameter NAMES come from the market's own axis configuration —
    nothing here is hardcoded)::

        {"x": {"score": 82,
               "evidence": [...],
               "parameters": {"<param>": {"score": 85,
                                          "evidence": [{"claim", "source"}]}}},
         "y": {...},
         "overall_score": 79}

    `x_score`/`y_score` let a caller pass axis scores it already has (from the
    cheap batch pass) so this only spends queries on the parameter detail.
    When they are absent the axis score is derived from the parameter scores,
    which is the same unweighted average the consolidated query asks for.
    """
    if ask is None:
        from vendor_intel.scraping.google_ai_mode import ask as _ask

        ask = _ask

    out: dict[str, Any] = {}
    for key, label, params, given in (
        ("x", AXIS_X_LABEL, x_parameters, x_score),
        ("y", AXIS_Y_LABEL, y_parameters, y_score),
    ):
        detail, composite = score_axis_parameters(
            company, label, params, ask=ask, market=market, context=context
        )
        # Precedence: a score the caller already has (the cheap batch pass),
        # then the model's own composite, then the average of the parameters.
        score = given
        if score is None:
            score = composite
        if score is None and detail:
            values = [d["score"] for d in detail.values()]
            score = int(round(sum(values) / len(values)))
        out[key] = {
            "score": score,
            "axis": label,
            "composite_reported": composite,
            # Aggregate evidence is the union of what justified each
            # parameter. The aggregate is arithmetic, so it has no separate
            # source of its own — inventing one would be fabrication.
            "evidence": [e for d in detail.values() for e in d["evidence"]],
            "parameters": detail,
        }

    x_val, y_val = out["x"]["score"], out["y"]["score"]
    out["overall_score"] = (
        int(round((x_val + y_val) / 2)) if x_val and y_val else None
    )
    return out


def enabled() -> bool:
    """AI Mode is the only X/Y scorer — there is no LLM scoring fallback.

    Kept as a single source of truth for callers that want to check the
    backend is reachable before starting a long scoring run.
    """
    from vendor_intel.scraping.google_ai_mode import enabled as ai_mode_on

    return ai_mode_on()
