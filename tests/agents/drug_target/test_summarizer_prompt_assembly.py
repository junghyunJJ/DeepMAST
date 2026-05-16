"""Tests for summarizer prompt assembly (task #10).

Verifies that:
- critic_enabled=False produces a prompt with NO critic task instruction.
- critic_enabled=True injects CRITIC_REVIEW_STEP_FRAGMENT with the required
  schema_version, repair-cap, and provenance_context constraints.
- SUMMARIZER_PROMPT_CORE itself does not contain contradictory
  "no inner subagents" language.
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

from src.agents.drug_target.subagents import prompts as prompts_module
from src.agents.drug_target.subagents.summarizer.agent import get_summarizer_subagent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_system_prompt(spec: dict) -> str:
    """Extract system_prompt from a summarizer spec dict."""
    return spec["system_prompt"]


def _make_summarizer_spec_enabled() -> dict:
    """Build a summarizer spec with critic_enabled=True.

    Patches SubAgentMiddleware so no real model resolution occurs —
    we only care about the assembled system_prompt string here.
    """
    fake_middleware = MagicMock()
    with patch(
        "src.agents.drug_target.subagents.summarizer.agent.SubAgentMiddleware",
        return_value=fake_middleware,
    ), patch(
        "src.agents.drug_target.subagents.summarizer.agent.get_critic_subagent",
        return_value={"name": "critic", "tools": []},
    ):
        return get_summarizer_subagent(critic_enabled=True, critic_model="openai:gpt-4o")


# ---------------------------------------------------------------------------
# Test: disabled mode must contain NO critic instruction
# ---------------------------------------------------------------------------

def test_summarizer_prompt_disabled_mode_contains_no_critic_task_instruction():
    """critic_enabled=False must not mention critic task invocation at all."""
    spec = get_summarizer_subagent(critic_enabled=False)
    prompt = _get_system_prompt(spec)

    # Must not contain the literal task call pattern
    assert 'task(subagent_type="critic"' not in prompt, (
        "Disabled mode prompt must not contain task(subagent_type=\"critic\")"
    )

    # Must not contain any CRITIC_REVIEW casing variant
    assert "CRITIC_REVIEW" not in prompt.upper() or (
        # Allow the word "CRITIC_REVIEW" only if it appears solely in a
        # comment/docstring — but since this is a runtime string, any
        # occurrence is a violation.
        False
    ), "Disabled mode prompt must not contain CRITIC_REVIEW"

    # Simpler check: case-insensitive scan for critic_review
    assert "critic_review" not in prompt.lower(), (
        "Disabled mode prompt must not contain 'critic_review' (case-insensitive)"
    )


# ---------------------------------------------------------------------------
# Test: enabled mode must contain the critic fragment
# ---------------------------------------------------------------------------

def test_summarizer_prompt_enabled_mode_contains_critic_fragment():
    """critic_enabled=True must inject CRITIC_REVIEW_STEP_FRAGMENT."""
    spec = _make_summarizer_spec_enabled()
    prompt = _get_system_prompt(spec)

    # Must reference the v1 schema_version so the middleware can parse it
    assert "summarizer_critic_review.v1" in prompt, (
        "Enabled mode prompt must contain 'summarizer_critic_review.v1'"
    )

    # Must mention the cited-only provenance_context constraint
    assert "provenance_context" in prompt, (
        "Enabled mode prompt must mention 'provenance_context' (cited-only constraint)"
    )
    assert "cited" in prompt.lower(), (
        "Enabled mode prompt must mention that provenance_context is cited-only"
    )

    # Must mention the 2-attempt repair cap
    # Accept "2" appearing near "attempt", "repair", "retry", or "blocker"
    cap_pattern = re.compile(
        r"(2\s*(attempt|repair|retry|blocker|time)|"
        r"(attempt|repair|retry|blocker|time)\s*2)",
        re.IGNORECASE,
    )
    assert cap_pattern.search(prompt) is not None, (
        "Enabled mode prompt must mention the 2-attempt repair cap"
    )


# ---------------------------------------------------------------------------
# Test: SUMMARIZER_PROMPT_CORE must not contradict critic enablement
# ---------------------------------------------------------------------------

def test_summarizer_prompt_core_constant_no_longer_mentions_no_inner_subagents():
    """SUMMARIZER_PROMPT_CORE must not contain language that says there are
    no inner subagents, as that contradicts critic enablement.
    """
    core = prompts_module.SUMMARIZER_PROMPT_CORE

    forbidden_phrases = [
        "no inner subagents",
        "without subagents",
        "there are no inner subagent",
        "there are no subagent",
        "no subagents",
    ]
    for phrase in forbidden_phrases:
        assert phrase.lower() not in core.lower(), (
            f"SUMMARIZER_PROMPT_CORE must not contain '{phrase}' — "
            "this contradicts critic enablement"
        )
