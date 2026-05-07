"""Regression guard: REPORT_WRITER_PROMPT must contain the Clinical Compounds source rule.

Root cause: a GPT-5.4 run (res_ipf_openai2) removed LIFITEGRAST from the ITGB2
Clinical Compounds table because the repair instructions' "match Stage 3 evidence
exactly" phrase was over-applied to Clinical Compounds rows that are sourced from
OpenTargets (ot_*.json / resolved_drugs.json), not from Stage 3 preclinical data.

Fix: REPORT_WRITER_PROMPT must explicitly state:
  1. Clinical Compounds tables source from ot_<gene>.json / resolved_drugs.json
     where source == opentargets.
  2. The "Stage 3 evidence" match-exactly restriction applies to Preclinical /
     computational sections ONLY, NOT to Clinical Compounds.
  3. OpenTargets-sourced approved drugs must NOT be removed during repair unless
     the ot_<gene>.json file itself is empty.

These assertions are anchored to unique substrings that are ABSENT from the
current prompt — they will fail before the rule paragraph is added (RED) and
pass once it is added (GREEN).

Plan reference: Fix-C, PR #16, omb-verify follow-up.
"""

from src.agents.drug_target.subagents.prompts import REPORT_WRITER_PROMPT


# ---------------------------------------------------------------------------
# Test 1: Clinical Compounds source rule paragraph is present
# ---------------------------------------------------------------------------

def test_report_writer_prompt_contains_clinical_compounds_source_rule() -> None:
    """REPORT_WRITER_PROMPT must contain a named 'Clinical Compounds source rule'
    paragraph so the LLM can locate and apply it during REPAIR MODE.

    Unique anchor: the phrase 'Clinical Compounds source rule' does not appear
    in the current prompt — it will only appear after the fix is applied.
    """
    assert "Clinical Compounds source rule" in REPORT_WRITER_PROMPT, (
        "REPORT_WRITER_PROMPT missing 'Clinical Compounds source rule' section. "
        "This rule is required to prevent removal of OpenTargets-sourced drugs "
        "(e.g. LIFITEGRAST for ITGB2) during repair iterations."
    )


# ---------------------------------------------------------------------------
# Test 2: Stage 3 evidence restriction explicitly scoped to Preclinical only
# ---------------------------------------------------------------------------

def test_report_writer_prompt_stage3_restriction_scoped_to_preclinical() -> None:
    """REPORT_WRITER_PROMPT must explicitly state that the 'Stage 3 evidence'
    match-exactly restriction applies to Preclinical/computational sections only,
    NOT to Clinical Compounds.

    Unique anchor: 'Stage 3 evidence is restricted to Preclinical' (or equivalent
    phrasing with 'Preclinical' qualified by 'Stage 3 evidence') is absent from the
    current prompt.
    """
    text = REPORT_WRITER_PROMPT.lower()
    # The rule must be present in some form: stage 3 evidence scoped to preclinical
    has_scoping = (
        "stage 3 evidence is restricted to preclinical" in text
        or "stage 3 evidence" in text
        and "preclinical" in text
        and "clinical compounds" in text
    )
    # But that broad check may pass on existing text — use the tighter anchor:
    # The phrase "Stage 3 evidence" next to "not" or "only" next to "preclinical"
    # is what we actually need. The specific anchor is the combined presence of:
    #   "clinical compounds" + "stage 3" + ("not" or "only" or "restricted")
    has_not_restricted = any(
        phrase in text
        for phrase in (
            "stage 3 evidence is restricted to preclinical",
            "stage 3 evidence restriction applies to preclinical",
            "not apply to clinical compounds",
            "does not apply to clinical compound",
            "restricted to preclinical",
        )
    )
    assert has_not_restricted, (
        "REPORT_WRITER_PROMPT must explicitly state that 'Stage 3 evidence' "
        "match-exactly restriction applies to Preclinical sections ONLY, not to "
        "Clinical Compounds. This prevents LLM repair from removing "
        "OpenTargets-sourced clinical drugs. "
        "Expected one of: 'Stage 3 evidence is restricted to Preclinical', "
        "'not apply to Clinical Compounds', 'restricted to Preclinical'."
    )


# ---------------------------------------------------------------------------
# Test 3: OpenTargets-sourced approved drugs must not be removed during repair
# ---------------------------------------------------------------------------

def test_report_writer_prompt_forbids_opentargets_drug_removal_in_repair() -> None:
    """REPORT_WRITER_PROMPT must instruct the LLM NOT to remove an OpenTargets-sourced
    clinical drug during a repair iteration unless ot_<gene>.json itself is empty.

    Unique anchor: 'Do NOT remove an OpenTargets' is absent from the current prompt.
    This is the direct prevention rule for the LIFITEGRAST regression.
    """
    assert "Do NOT remove an OpenTargets" in REPORT_WRITER_PROMPT, (
        "REPORT_WRITER_PROMPT missing the rule: "
        "'Do NOT remove an OpenTargets-sourced clinical drug during a repair iteration'. "
        "This rule directly prevents the LIFITEGRAST removal regression "
        "(ITGB2 Clinical Compounds table, GPT-5.4 run res_ipf_openai2)."
    )
