"""Task #9: Deterministic RED tests for prompts.py cleanup.

Three tests verify:
1. SUBAGENT_PROMPTS["critic"] does not expose the legacy claim/verdict schema.
2. REPORT_WRITER_PROMPT dead-code removal is blocked (live readers found — test
   documents the STOP outcome: we assert the symbol still exists so the test
   suite remains honest about the current state).
3. validate_drug_report_finalization signature with require_critic param remains
   importable and callable.

All tests are deterministic (no LLM calls, no filesystem). Run with:
    uv run pytest tests/agents/drug_target/test_subagent_prompts_cleanup.py -v
"""

from __future__ import annotations

import inspect

import pytest


# ---------------------------------------------------------------------------
# Test 1: SUBAGENT_PROMPTS["critic"] must NOT expose legacy claim/verdict schema
# ---------------------------------------------------------------------------


def test_subagent_prompts_critic_schema_is_not_legacy_claim_verdict_schema() -> None:
    """SUBAGENT_PROMPTS["critic"] must either be absent or must not contain
    the legacy claim/verdict JSON schema keywords that predate task #2's new
    CriticOutput schema (finding_type / slot_ids / payload_hash).

    The legacy CRITIC_PROMPT uses keys 'claim_text' and 'verdict' in its JSON
    output schema. The new critic gate (task #2, subagents/critic/agent.py)
    uses 'valid', 'findings', 'findings_count', 'payload_hash', 'finding_type',
    'slot_ids', 'sentence', 'reason', 'repair_instruction'.

    Passing condition (either):
      (a) "critic" key is absent from SUBAGENT_PROMPTS, OR
      (b) the value does not contain the string '"claim_text"' AND '"verdict"'
          together (which would indicate the legacy schema is still exposed).
    """
    from src.agents.drug_target.subagents import prompts  # noqa: PLC0415

    registry = getattr(prompts, "SUBAGENT_PROMPTS", {})

    if "critic" not in registry:
        # Approach (b) succeeded: entry removed entirely — PASS
        return

    critic_text: str = registry["critic"]

    # Legacy schema markers: both must be absent if the entry still exists
    has_legacy_claim_text = '"claim_text"' in critic_text
    has_legacy_verdict = '"verdict"' in critic_text

    assert not (has_legacy_claim_text and has_legacy_verdict), (
        "SUBAGENT_PROMPTS['critic'] still exposes the legacy claim/verdict schema. "
        "Either remove the 'critic' key from SUBAGENT_PROMPTS or replace the "
        "value with the new Appendix-A prompt from subagents/critic/agent.py. "
        f"Found '\"claim_text\"': {has_legacy_claim_text}, "
        f"Found '\"verdict\"': {has_legacy_verdict}."
    )


# ---------------------------------------------------------------------------
# Test 2: REPORT_WRITER_PROMPT cleanup status — live readers found, STOP
# ---------------------------------------------------------------------------


def test_report_writer_prompt_is_registered_as_a_production_surface() -> None:
    from src.agents.drug_target.subagents import prompts  # noqa: PLC0415

    assert prompts.SUBAGENT_PROMPTS["report_writer"] is prompts.REPORT_WRITER_PROMPT


# ---------------------------------------------------------------------------
# Test 3: validate_drug_report_finalization legacy path remains callable
# ---------------------------------------------------------------------------


def test_validate_drug_report_finalization_require_critic_remains_legacy_path() -> None:
    """validate_drug_report_finalization must remain importable with its
    require_critic parameter intact (legacy persisted-report path).

    This test does NOT invoke the function body — it only verifies the
    signature so that the legacy path is not accidentally removed.
    """
    from src.agents.drug_target.tools import validate_drug_report_finalization  # noqa: PLC0415

    # Must be importable
    assert validate_drug_report_finalization is not None

    # Unwrap LangChain tool wrapper to inspect the underlying callable
    underlying = getattr(validate_drug_report_finalization, "func", None)
    assert callable(underlying)

    sig = inspect.signature(underlying)
    params = sig.parameters

    assert "data_dir" in params, (
        "validate_drug_report_finalization must accept 'data_dir' parameter."
    )
    assert "require_critic" in params, (
        "validate_drug_report_finalization must retain 'require_critic' parameter "
        "— it is the legacy persisted-report gate path."
    )

    # require_critic must default to False (non-breaking default)
    default = params["require_critic"].default
    assert default is False, (
        f"require_critic must default to False (legacy compat), got {default!r}."
    )
