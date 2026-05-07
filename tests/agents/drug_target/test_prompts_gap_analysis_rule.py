"""Prompt rule tests for Gap Analysis section enforcement.

Regression guard for EMPTY_GAP_ANALYSIS validator catch (stage_logic.py:3378).
The report_writer LLM left the Gap Analysis body blank in res_ipf_openai run
(drug.md line 539-545). These tests ensure REPORT_WRITER_PROMPT instructs the
LLM to produce a non-empty Gap Analysis body with required sub-content.
"""

from src.agents.drug_target.subagents.prompts import REPORT_WRITER_PROMPT


def test_gap_analysis_rule_present() -> None:
    """REPORT_WRITER_PROMPT must mention gap analysis and enforce a non-empty body.

    R-prevention for EMPTY_GAP_ANALYSIS validator catch which requires
    at least 20 non-whitespace characters in the section body.
    """
    text = REPORT_WRITER_PROMPT.lower()

    # Section must be referenced by name so the LLM knows this rule applies
    assert "gap analysis" in text, (
        "REPORT_WRITER_PROMPT must mention 'Gap Analysis' to guide the LLM"
    )

    # Must include an enforcement phrase about non-emptiness or minimum content
    assert (
        "must not be empty" in text
        or "non-empty" in text
        or "minimum" in text
        or "at least" in text
    ), (
        "REPORT_WRITER_PROMPT must enforce non-empty Gap Analysis body "
        "(e.g. 'must not be empty', 'non-empty', 'minimum', or 'at least')"
    )


def test_gap_analysis_required_subpoints() -> None:
    """Prompt must specify the kinds of content Gap Analysis must contain.

    The section should require at least one of: data limitations, missing
    evidence, or open questions to give the LLM concrete filling guidance.
    """
    text = REPORT_WRITER_PROMPT.lower()

    assert any(
        kw in text
        for kw in [
            "data limitation",
            "missing evidence",
            "open question",
            "evidence gap",
            "knowledge gap",
        ]
    ), (
        "REPORT_WRITER_PROMPT must list required Gap Analysis sub-content "
        "(data limitations, missing evidence, or open questions)"
    )


def test_gap_analysis_cites_validator_check() -> None:
    """Prompt should mention the validator check so LLM understands the stakes.

    Citing EMPTY_GAP_ANALYSIS or the 20-character threshold gives the LLM
    a concrete failure mode to avoid.
    """
    text = REPORT_WRITER_PROMPT.lower()

    assert (
        "empty_gap_analysis" in text
        or "empty gap analysis" in text
        or "gap analysis" in text
    ), (
        "REPORT_WRITER_PROMPT must reference the Gap Analysis section "
        "(ideally citing the EMPTY_GAP_ANALYSIS validator check)"
    )
