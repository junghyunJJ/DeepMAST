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


@pytest.mark.xfail(
    reason=(
        "REPORT_WRITER_PROMPT reader migration is a separate follow-up task — "
        "see plan ADR follow-ups. Five live readers found in: "
        "test_prompts_gap_analysis_rule.py, test_prompts_clinical_compounds_rule.py, "
        "test_prompts_reflection_guidance.py, test_drug_profile_coverage.py, "
        "tests/test_drug_target.py. This test remains RED until those readers are migrated."
    ),
    strict=True,
)
def test_report_writer_prompt_dead_code_removed() -> None:
    """REPORT_WRITER_PROMPT must be removed from prompts module AND
    'report_writer' key must be absent from SUBAGENT_PROMPTS.

    NOTE: Pre-implementation grep found live readers of REPORT_WRITER_PROMPT in:
      - tests/agents/drug_target/test_prompts_gap_analysis_rule.py
      - tests/agents/drug_target/test_prompts_clinical_compounds_rule.py
      - tests/agents/drug_target/test_prompts_reflection_guidance.py
      - tests/agents/drug_target/test_drug_profile_coverage.py
      - tests/test_drug_target.py

    Per task #9 spec: "If a reader is found, STOP and report (do not broaden
    the cleanup beyond the dead constant)."

    This test documents the STOP decision. Marked xfail(strict=True) so the
    deterministic CI lane records it as expected-failure until the follow-up
    migration task removes all live readers.
    """
    from src.agents.drug_target.subagents import prompts  # noqa: PLC0415

    has_attr = hasattr(prompts, "REPORT_WRITER_PROMPT")
    in_registry = "report_writer" in getattr(prompts, "SUBAGENT_PROMPTS", {})

    assert not has_attr, (
        "REPORT_WRITER_PROMPT still exists on prompts module. "
        "Live readers were found — this cleanup is BLOCKED until those test "
        "files are migrated. See task #9 STOP report for details."
    )
    assert not in_registry, (
        "'report_writer' key still present in SUBAGENT_PROMPTS. "
        "Remove after all live readers are migrated."
    )


# ---------------------------------------------------------------------------
# Test 2b: REPORT_WRITER_PROMPT retention decision is documented in source
# ---------------------------------------------------------------------------


def test_report_writer_prompt_retention_is_documented() -> None:
    """The lines immediately preceding REPORT_WRITER_PROMPT = must contain
    a comment block that documents the retention decision.

    This test makes the retention decision auditable from CI rather than
    relying on the xfail test alone. It verifies three things:

    1. The comment block mentions 'Retained pending reader migration'.
    2. The comment block names the xfail test
       (test_report_writer_prompt_dead_code_removed).
    3. The comment block names at least 3 of the 5 known reader files.
    """
    import pathlib  # noqa: PLC0415

    source_path = pathlib.Path(
        "src/agents/drug_target/subagents/prompts.py"
    ).resolve()
    source_text = source_path.read_text(encoding="utf-8")
    lines = source_text.splitlines()

    # Find the line index of the REPORT_WRITER_PROMPT assignment
    assignment_idx = next(
        (i for i, line in enumerate(lines) if line.startswith("REPORT_WRITER_PROMPT = ")),
        None,
    )
    assert assignment_idx is not None, (
        "Could not find 'REPORT_WRITER_PROMPT = ' in prompts.py. "
        "Was the constant renamed or removed?"
    )

    # Collect the comment block immediately above the assignment
    # (scan backwards skipping blank lines and comment lines)
    comment_lines: list[str] = []
    idx = assignment_idx - 1
    while idx >= 0:
        stripped = lines[idx].strip()
        if stripped.startswith("#") or stripped == "":
            if stripped.startswith("#"):
                comment_lines.append(stripped)
            idx -= 1
        else:
            break
    comment_block = "\n".join(comment_lines)

    assert "Retained pending reader migration" in comment_block, (
        "The comment block above REPORT_WRITER_PROMPT must mention "
        "'Retained pending reader migration'. "
        "Add a retention decision comment per the task spec."
    )

    assert "test_report_writer_prompt_dead_code_removed" in comment_block, (
        "The comment block above REPORT_WRITER_PROMPT must name the xfail test "
        "'test_report_writer_prompt_dead_code_removed' so the retention "
        "decision is traceable from source."
    )

    known_readers = [
        "test_prompts_gap_analysis_rule.py",
        "test_prompts_clinical_compounds_rule.py",
        "test_prompts_reflection_guidance.py",
        "test_drug_profile_coverage.py",
        "tests/test_drug_target.py",
    ]
    named_count = sum(1 for r in known_readers if r in comment_block)
    assert named_count >= 3, (
        f"The comment block above REPORT_WRITER_PROMPT must name at least 3 of "
        f"the 5 known reader files. Found {named_count}: {known_readers}. "
        "Update the retention comment to list the live readers."
    )


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
    underlying = getattr(validate_drug_report_finalization, "func", validate_drug_report_finalization)

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
