"""Verify that reflection grounding requirements are present in subagent prompts.

The ThinkToolQualityGateMiddleware (plan §1.2 R2) enforces server-side that
reflections contain either:
  - a filename pattern matching [a-z0-9_]+.json (e.g. stage3_ITGB2.json)
  - a numeric value (e.g. score=0.85, 7 issues, 10 drugs)

These tests verify that the prompt text instructs the LLM to include such
grounding evidence in its think_tool reflections, making ungrounded reflections
rare before they reach the middleware gate.

Plan reference: §1.2 R2 (grounding patterns), §2 tech stack (prompts.py).
"""

from src.agents.drug_target.subagents import prompts as _prompts

# ---------------------------------------------------------------------------
# Constants: the phrases we require in each prompt's reflection guidance
# ---------------------------------------------------------------------------

# Phrases anchored to filename-reference requirement
_JSON_EXAMPLE_MARKER = ".json"  # must show a .json filename example

# Phrases anchored to numeric-value requirement
_NUMERIC_MARKERS = ("numeric", "specific number", "score=", "count", "value")

# Phrases anchored to next-action requirement
_NEXT_ACTION_MARKERS = ("next action", "next step", "will retry", "continue to")

# Phrase anchored to the grounding requirement section header/intro
_GROUNDING_SECTION_MARKERS = (
    "reflection grounding",
    "grounding requirement",
    "reflection requirement",
    "reflections lacking",
    "reflection must",
)

# Prompts that have an explicit REFLECT / think_tool instruction and must
# contain grounding requirements.
_REFLECT_PROMPTS = [
    ("EVIDENCE_ASSESSOR_PROMPT", _prompts.EVIDENCE_ASSESSOR_PROMPT),
    ("HYPOTHESIS_WRITER_PROMPT", _prompts.HYPOTHESIS_WRITER_PROMPT),
    ("REPORT_WRITER_PROMPT", _prompts.REPORT_WRITER_PROMPT),
]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _lower(text: str) -> str:
    return text.lower()


# ---------------------------------------------------------------------------
# RED tests: these must FAIL before the prompt update, PASS after.
# ---------------------------------------------------------------------------


def test_evidence_assessor_prompt_reflection_cites_filenames() -> None:
    """EVIDENCE_ASSESSOR_PROMPT must instruct the LLM to cite source filenames
    (e.g. stage3_ITGB2.json) in think_tool reflections."""
    text = _lower(_prompts.EVIDENCE_ASSESSOR_PROMPT)
    assert _JSON_EXAMPLE_MARKER in text or any(
        m in text for m in ("stage3_", "chembl_lookup", "ranked_targets")
    ), (
        "EVIDENCE_ASSESSOR_PROMPT reflection guidance must include a .json filename "
        "example to align with R2 grounding check."
    )
    # The grounding section itself
    assert any(m in text for m in _GROUNDING_SECTION_MARKERS), (
        "EVIDENCE_ASSESSOR_PROMPT missing reflection grounding requirement section."
    )


def test_evidence_assessor_prompt_reflection_requires_numeric_values() -> None:
    """EVIDENCE_ASSESSOR_PROMPT reflection section must require numeric values."""
    text = _lower(_prompts.EVIDENCE_ASSESSOR_PROMPT)
    # Check the grounding section exists (not generic numeric mentions)
    assert any(m in text for m in _GROUNDING_SECTION_MARKERS), (
        "EVIDENCE_ASSESSOR_PROMPT missing reflection grounding requirement section "
        "that specifies numeric values."
    )
    assert any(m in text for m in _NUMERIC_MARKERS), (
        "EVIDENCE_ASSESSOR_PROMPT reflection guidance must require numeric values "
        "(e.g. score=0.85, 7 issues) to pass R2 grounding gate."
    )


def test_evidence_assessor_prompt_reflection_requires_next_action() -> None:
    """EVIDENCE_ASSESSOR_PROMPT reflection section must require a next-action statement."""
    text = _lower(_prompts.EVIDENCE_ASSESSOR_PROMPT)
    assert any(m in text for m in _NEXT_ACTION_MARKERS), (
        "EVIDENCE_ASSESSOR_PROMPT reflection guidance must include a next-action "
        "statement requirement (e.g. 'next action', 'will retry with')."
    )


def test_hypothesis_writer_prompt_reflection_cites_filenames() -> None:
    """HYPOTHESIS_WRITER_PROMPT must instruct LLM to cite source filenames in
    think_tool reflections."""
    text = _lower(_prompts.HYPOTHESIS_WRITER_PROMPT)
    assert _JSON_EXAMPLE_MARKER in text or any(
        m in text for m in ("stage3_", "chembl_lookup", "ranked_targets")
    ), (
        "HYPOTHESIS_WRITER_PROMPT reflection guidance must include a .json filename "
        "example to align with R2 grounding check."
    )
    assert any(m in text for m in _GROUNDING_SECTION_MARKERS), (
        "HYPOTHESIS_WRITER_PROMPT missing reflection grounding requirement section."
    )


def test_hypothesis_writer_prompt_reflection_requires_numeric_values() -> None:
    """HYPOTHESIS_WRITER_PROMPT reflection section must require numeric values."""
    text = _lower(_prompts.HYPOTHESIS_WRITER_PROMPT)
    assert any(m in text for m in _GROUNDING_SECTION_MARKERS), (
        "HYPOTHESIS_WRITER_PROMPT missing reflection grounding requirement section."
    )
    assert any(m in text for m in _NUMERIC_MARKERS), (
        "HYPOTHESIS_WRITER_PROMPT reflection guidance must require numeric values."
    )


def test_hypothesis_writer_prompt_reflection_requires_next_action() -> None:
    """HYPOTHESIS_WRITER_PROMPT reflection section must require a next-action statement."""
    text = _lower(_prompts.HYPOTHESIS_WRITER_PROMPT)
    assert any(m in text for m in _NEXT_ACTION_MARKERS), (
        "HYPOTHESIS_WRITER_PROMPT reflection guidance must include a next-action "
        "statement requirement."
    )


def test_report_writer_prompt_reflection_cites_filenames() -> None:
    """REPORT_WRITER_PROMPT must instruct LLM to cite source filenames in
    think_tool reflections."""
    text = _lower(_prompts.REPORT_WRITER_PROMPT)
    assert _JSON_EXAMPLE_MARKER in text or any(
        m in text for m in ("stage3_", "chembl_lookup", "ranked_targets")
    ), (
        "REPORT_WRITER_PROMPT reflection guidance must include a .json filename "
        "example to align with R2 grounding check."
    )
    assert any(m in text for m in _GROUNDING_SECTION_MARKERS), (
        "REPORT_WRITER_PROMPT missing reflection grounding requirement section."
    )


def test_report_writer_prompt_reflection_requires_numeric_values() -> None:
    """REPORT_WRITER_PROMPT reflection section must require numeric values."""
    text = _lower(_prompts.REPORT_WRITER_PROMPT)
    assert any(m in text for m in _GROUNDING_SECTION_MARKERS), (
        "REPORT_WRITER_PROMPT missing reflection grounding requirement section."
    )
    assert any(m in text for m in _NUMERIC_MARKERS), (
        "REPORT_WRITER_PROMPT reflection guidance must require numeric values."
    )


def test_report_writer_prompt_reflection_requires_next_action() -> None:
    """REPORT_WRITER_PROMPT reflection section must require a next-action statement."""
    text = _lower(_prompts.REPORT_WRITER_PROMPT)
    assert any(m in text for m in _NEXT_ACTION_MARKERS), (
        "REPORT_WRITER_PROMPT reflection guidance must include a next-action "
        "statement requirement."
    )


def test_rejected_reflections_warning_present_in_at_least_one_prompt() -> None:
    """At least one prompt must warn that ungrounded reflections will be rejected.

    This sentence aligns the LLM's expectation with the middleware's actual
    behavior (retry signal on R2 failure).
    """
    warning_phrases = (
        "will be rejected",
        "will be retried",
        "retry required",
        "rejected and you will be asked to retry",
        "reflections lacking",
    )
    found = False
    for _name, prompt_text in _REFLECT_PROMPTS:
        text = _lower(prompt_text)
        if any(p in text for p in warning_phrases):
            found = True
            break
    assert found, (
        "At least one of EVIDENCE_ASSESSOR_PROMPT, HYPOTHESIS_WRITER_PROMPT, "
        "REPORT_WRITER_PROMPT must warn that ungrounded reflections will be "
        "rejected/retried by the quality gate."
    )
