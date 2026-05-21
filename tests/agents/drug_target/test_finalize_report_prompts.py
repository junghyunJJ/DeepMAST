"""#18d — CP-P1-012: Prompt template structure and hard-rules guard.

Three assertions:
1. FINALIZE_REPORT_USER_TEMPLATE contains the required format placeholders.
2. Template formats without KeyError when all 3 vars are supplied.
3. FINALIZE_REPORT_SYSTEM_PROMPT contains the 'Never invent drug names' guard.
"""

from __future__ import annotations

import pytest

from src.agents.drug_target.finalize_report_prompts import (
    FINALIZE_REPORT_SYSTEM_PROMPT,
    FINALIZE_REPORT_USER_TEMPLATE,
)


def test_user_template_contains_spec_json_placeholder() -> None:
    """FINALIZE_REPORT_USER_TEMPLATE must have {spec_json} placeholder."""
    assert "{spec_json}" in FINALIZE_REPORT_USER_TEMPLATE, (
        "FINALIZE_REPORT_USER_TEMPLATE missing {spec_json} placeholder"
    )


def test_user_template_contains_reference_card_json_placeholder() -> None:
    """FINALIZE_REPORT_USER_TEMPLATE must have {reference_card_json} placeholder."""
    assert "{reference_card_json}" in FINALIZE_REPORT_USER_TEMPLATE, (
        "FINALIZE_REPORT_USER_TEMPLATE missing {reference_card_json} placeholder"
    )


def test_user_template_contains_evidence_summary_json_placeholder() -> None:
    """FINALIZE_REPORT_USER_TEMPLATE must have {evidence_summary_json} placeholder."""
    assert "{evidence_summary_json}" in FINALIZE_REPORT_USER_TEMPLATE, (
        "FINALIZE_REPORT_USER_TEMPLATE missing {evidence_summary_json} placeholder"
    )


def test_user_template_formats_without_key_error() -> None:
    """All 3 placeholders can be substituted without KeyError."""
    rendered = FINALIZE_REPORT_USER_TEMPLATE.format(
        spec_json="X",
        reference_card_json="Y",
        evidence_summary_json="Z",
    )
    assert "X" in rendered
    assert "Y" in rendered
    assert "Z" in rendered


def test_system_prompt_contains_no_fabrication_hard_rule() -> None:
    """FINALIZE_REPORT_SYSTEM_PROMPT must contain 'Never invent drug names' guard."""
    assert "Never invent drug names" in FINALIZE_REPORT_SYSTEM_PROMPT, (
        "FINALIZE_REPORT_SYSTEM_PROMPT missing 'Never invent drug names' HARD RULE. "
        f"Actual prompt (first 300 chars): {FINALIZE_REPORT_SYSTEM_PROMPT[:300]!r}"
    )


@pytest.mark.parametrize("placeholder", ["{spec_json}", "{reference_card_json}", "{evidence_summary_json}"])
def test_user_template_contains_all_placeholders_parametrized(placeholder: str) -> None:
    """Parametrized check that each placeholder is present."""
    assert placeholder in FINALIZE_REPORT_USER_TEMPLATE
