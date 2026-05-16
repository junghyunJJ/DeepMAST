"""Tests for the critic subagent spec (task #2 — Phase 1).

Three deterministic tests (no LLM calls, no filesystem, <1s):

  TC-01: get_critic_subagent has name="critic", a non-None model argument,
         and tools=[] (read-only constraint).
  TC-02: Critic prompt explicitly forbids judging whether a medical claim is
         generally true — it may only judge cited source/provenance support.
  TC-03: Critic prompt instructs JSON output to include the canonical fields:
         valid, findings, findings_count, payload_hash, and per-finding
         finding_type, severity, slot_ids, sentence, reason,
         repair_instruction.

All three tests run under ``uv run pytest tests/agents/drug_target/ -m "not llm"``
and must complete in <1s.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# TC-01
# ---------------------------------------------------------------------------


def test_critic_subagent_has_name_model_and_empty_tools() -> None:
    """Spec must carry name='critic', a concrete model string, and tools=[]."""
    from src.agents.drug_target.subagents.critic import get_critic_subagent  # noqa: PLC0415

    spec = get_critic_subagent(model="gpt-4o")

    assert isinstance(spec, dict), "get_critic_subagent must return a dict"

    # name
    assert spec.get("name") == "critic", (
        f"Expected name='critic', got {spec.get('name')!r}"
    )

    # model must be the string passed in — not None, not a default
    assert spec.get("model") == "gpt-4o", (
        f"Expected model='gpt-4o', got {spec.get('model')!r}"
    )

    # tools must be an empty list — critic is read-only
    assert spec.get("tools") == [], (
        f"Critic must have no tools (read-only), got {spec.get('tools')!r}"
    )

    # prompt must be present and start with the canonical first line
    prompt = spec.get("system_prompt") or spec.get("prompt") or ""
    assert prompt.strip().startswith(
        "You are the read-only critic for the drug_target summarizer."
    ), (
        "Critic prompt must start with the canonical first line from Appendix A"
    )


# ---------------------------------------------------------------------------
# TC-02
# ---------------------------------------------------------------------------


def test_critic_subagent_prompt_forbids_medical_truth_judgment() -> None:
    """The prompt must explicitly forbid judging whether a medical claim is
    generally true.  It may only judge whether cited source/provenance text
    supports the sentence."""
    from src.agents.drug_target.subagents.critic import get_critic_subagent  # noqa: PLC0415

    spec = get_critic_subagent(model="gpt-4o")
    prompt: str = spec.get("system_prompt") or spec.get("prompt") or ""

    # The Appendix A draft contains this exact prohibition.
    assert "Do not judge whether a medical claim is generally true" in prompt, (
        "Critic prompt must contain the literal phrase "
        "'Do not judge whether a medical claim is generally true' "
        "to prevent the LLM from injecting external knowledge."
    )

    # Also confirm the positive instruction about cited-source grounding.
    assert "cited source" in prompt.lower() or "cited text" in prompt.lower(), (
        "Critic prompt must instruct the LLM to judge only whether cited "
        "source/provenance text supports the sentence."
    )


# ---------------------------------------------------------------------------
# TC-03
# ---------------------------------------------------------------------------


def test_critic_subagent_schema_requires_valid_findings_payload_hash() -> None:
    """The prompt must instruct JSON output that contains all canonical keys:
    valid, findings, findings_count, payload_hash at the envelope level, and
    finding_type, severity, slot_ids, sentence, reason, repair_instruction at
    the per-finding level.

    String search is sufficient here — full LLM behavior is tested in the
    @pytest.mark.llm suite (task #12).
    """
    from src.agents.drug_target.subagents.critic import get_critic_subagent  # noqa: PLC0415

    spec = get_critic_subagent(model="gpt-4o")
    prompt: str = spec.get("system_prompt") or spec.get("prompt") or ""

    envelope_keys = ["valid", "findings", "findings_count", "payload_hash"]
    per_finding_keys = [
        "finding_type",
        "severity",
        "slot_ids",
        "sentence",
        "reason",
        "repair_instruction",
    ]

    for key in envelope_keys:
        assert f'"{key}"' in prompt, (
            f"Critic prompt must reference JSON key \"{key}\" in the output schema "
            f"(envelope level). Missing from prompt."
        )

    for key in per_finding_keys:
        assert f'"{key}"' in prompt, (
            f"Critic prompt must reference JSON key \"{key}\" in the output schema "
            f"(per-finding level). Missing from prompt."
        )
