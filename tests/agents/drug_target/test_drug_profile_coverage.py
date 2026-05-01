"""T9 RED: REPORT_WRITER_PROMPT drug-profile section must broaden the data
source to the allowlist union (resolved_drugs.json + stage3 matched_drugs +
stage3 preclinical_compounds).

The test does NOT run a live LLM. It checks the prompt text directly to
confirm D3 wording is present:

1. Mentions ``resolved_drugs.json`` as a drug-profile data source.
2. Instructs the writer to consult it BEFORE concluding "No known drugs"
   when ``stage3.matched_drugs`` is empty.
"""

from __future__ import annotations


def _report_writer_prompt() -> str:
    from src.agents.drug_target.subagents.prompts import SUBAGENT_PROMPTS

    return SUBAGENT_PROMPTS["report_writer"]


def test_drug_profile_data_source_mentions_resolved_drugs() -> None:
    prompt = _report_writer_prompt()
    assert "resolved_drugs.json" in prompt, (
        "Drug-profile data source rule must reference resolved_drugs.json so "
        "report_writer broadens its drug list beyond stage3.matched_drugs."
    )


def test_drug_profile_does_not_default_to_no_known_drugs_when_resolved_has_entries() -> None:
    prompt = _report_writer_prompt()
    # Look for guidance that prevents the bug: "No known drugs" only when
    # the union is empty (not just stage3 empty).
    lowered = prompt.lower()
    assert "resolved_drugs" in lowered and "matched_drugs" in lowered, (
        "Prompt must reference both resolved_drugs and matched_drugs in the "
        "drug-profile section so the writer knows to union the two sources."
    )
    # Either explicit union mention OR an instruction to check resolved_drugs
    # before defaulting.
    has_union_guidance = (
        "union" in lowered
        or ("check" in lowered and "resolved_drugs" in lowered)
        or "do not default" in lowered
    )
    assert has_union_guidance, (
        "Prompt must instruct: do NOT default to 'No known drugs' just because "
        "stage3.matched_drugs is empty — check resolved_drugs.json first."
    )
