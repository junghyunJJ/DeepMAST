"""Disabled-mode end-to-end test for critic kill switch (Task #12 gap closure).

Plan Section 6 named test:
  test_critic_disabled_env_omits_local_subagent_gate

Alias documentation
-------------------
The following Plan Section 6 named tests are already covered in existing files
under slightly different names and are NOT duplicated here:

  - test_critic_enabled_default_factory_respects_env_false
      → test_critic_enabled_kill_switch.py::test_critic_enabled_default_factory_respects_env_false (KS-01)
  - test_critic_enabled_default_factory_unknown_env_stays_enabled
      → test_critic_enabled_kill_switch.py::test_critic_enabled_default_factory_unknown_env_stays_enabled (KS-02)
  - test_critic_enabled_explicit_true_overrides_env_false
      → test_critic_enabled_kill_switch.py::test_critic_enabled_explicit_true_overrides_env_false (KS-03)
  - test_critic_enabled_explicit_false_overrides_env_true
      → test_critic_enabled_kill_switch.py::test_critic_enabled_explicit_false_overrides_env_true (KS-04)
  - test_create_drug_target_agent_threads_critic_enabled_to_subagents
      → test_critic_enabled_kill_switch.py::test_create_drug_target_agent_threads_critic_enabled_to_subagents (KS-05)
  - test_get_subagents_threads_critic_enabled_to_summarizer_factory
      → test_drug_target_factory_wiring.py::test_get_subagents_threads_critic_enabled_true_to_summarizer_factory
        and test_get_subagents_threads_critic_enabled_false_to_summarizer_factory

This file covers only the consolidated disabled-mode test not provided elsewhere.

Run with:
    uv run pytest tests/agents/drug_target/test_disabled_mode_end_to_end.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_critic_disabled_env_omits_local_subagent_gate() -> None:
    """With critic_enabled=False, BOTH SubAgentMiddleware(critic) and
    CriticGateMiddleware are absent from the summarizer's middleware list AND
    the assembled system_prompt contains no critic-review instruction.

    This is the consolidated disabled-mode end-to-end test:
    - SubAgentMiddleware is not instantiated
    - CriticGateMiddleware is not in the middleware list
    - prompt contains no 'task(subagent_type="critic"' pattern
    - prompt contains no 'critic_review' text (case-insensitive)
    """
    from src.agents.drug_target.subagents.summarizer.agent import get_summarizer_subagent
    from src.agents.drug_target.subagents.summarizer.middleware import (
        CriticGateMiddleware,
        SummarizerFinalizationGuardMiddleware,
    )

    stub_backend = MagicMock(name="stub_backend")

    with (
        patch(
            "src.agents.drug_target.subagents.summarizer.agent.get_critic_subagent",
        ) as mock_get_critic,
        patch(
            "src.agents.drug_target.subagents.summarizer.agent.SubAgentMiddleware",
        ) as mock_subagent_mw,
    ):
        spec = get_summarizer_subagent(
            backend=stub_backend,
            critic_model="openai:gpt-4o",
            critic_enabled=False,
        )

    # SubAgentMiddleware must NOT be instantiated
    mock_subagent_mw.assert_not_called()
    # get_critic_subagent must NOT be called
    mock_get_critic.assert_not_called()

    mw_list: list = spec["middleware"]
    assert isinstance(mw_list, list), "middleware must be a list"

    # CriticGateMiddleware must be ABSENT
    gate_items = [m for m in mw_list if isinstance(m, CriticGateMiddleware)]
    assert len(gate_items) == 0, (
        f"CriticGateMiddleware must not appear when critic_enabled=False; "
        f"found {len(gate_items)} instance(s)"
    )

    # SummarizerFinalizationGuardMiddleware must still be present (legacy gate)
    guard_items = [m for m in mw_list if isinstance(m, SummarizerFinalizationGuardMiddleware)]
    assert len(guard_items) >= 1, (
        "SummarizerFinalizationGuardMiddleware must still be present even when critic is disabled"
    )

    # Assembled prompt must contain no critic instruction
    prompt: str = spec["system_prompt"]

    assert 'task(subagent_type="critic"' not in prompt, (
        'Disabled-mode prompt must not contain task(subagent_type="critic"'
    )
    assert "critic_review" not in prompt.lower(), (
        "Disabled-mode prompt must not contain 'critic_review' (case-insensitive)"
    )
    assert "summarizer_critic_review.v1" not in prompt, (
        "Disabled-mode prompt must not reference the critic envelope schema version"
    )
