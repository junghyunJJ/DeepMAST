"""Kill-switch tests for DrugTargetConfig.critic_enabled (Task #11).

Covers:
  KS-01: DRUG_TARGET_CRITIC_ENABLED=false -> critic_enabled is False (all disable values).
  KS-02: DRUG_TARGET_CRITIC_ENABLED=garbage -> critic_enabled is True (unknown = fail-closed).
  KS-03: Explicit critic_enabled=True wins even when env says false.
  KS-04: Explicit critic_enabled=False wins even when env says true.
  KS-05: create_drug_target_agent threads config.critic_enabled into get_subagents.

All tests are deterministic (no LLM calls, no I/O). Run with:
  uv run pytest tests/agents/drug_target/test_critic_enabled_kill_switch.py -v
"""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# KS-01: env-based disable values map to False
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("env_value", ["false", "0", "no", "off"])
def test_critic_enabled_default_factory_respects_env_false(
    monkeypatch: pytest.MonkeyPatch,
    env_value: str,
) -> None:
    """DRUG_TARGET_CRITIC_ENABLED=<disable_value> -> DrugTargetConfig().critic_enabled is False.

    Tests all four canonical disable tokens and verifies the default_factory
    returns False so the critic gate is skipped.
    """
    monkeypatch.setenv("DRUG_TARGET_CRITIC_ENABLED", env_value)

    # Re-import to pick up fresh default_factory evaluation
    import src.agents.drug_target.agent as agent_mod
    importlib.reload(agent_mod)

    config = agent_mod.DrugTargetConfig()
    assert config.critic_enabled is False, (
        f"Expected critic_enabled=False for env '{env_value}'; got {config.critic_enabled}"
    )


# ---------------------------------------------------------------------------
# KS-02: unknown / typo env value stays True (fail-closed)
# ---------------------------------------------------------------------------

def test_critic_enabled_default_factory_unknown_env_stays_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DRUG_TARGET_CRITIC_ENABLED=garbage -> critic_enabled is True (fail-closed).

    An unrecognized value must NOT disable the critic — the operator must
    explicitly opt out with a known disable token.
    """
    monkeypatch.setenv("DRUG_TARGET_CRITIC_ENABLED", "garbage")

    import src.agents.drug_target.agent as agent_mod
    importlib.reload(agent_mod)

    config = agent_mod.DrugTargetConfig()
    assert config.critic_enabled is True, (
        f"Expected critic_enabled=True for unknown env value 'garbage'; got {config.critic_enabled}"
    )


# ---------------------------------------------------------------------------
# KS-03: explicit True wins over env disable
# ---------------------------------------------------------------------------

def test_critic_enabled_explicit_true_overrides_env_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DrugTargetConfig(critic_enabled=True) wins even when env says false.

    The default_factory runs only when the argument is omitted. An explicit
    caller-provided value must always take precedence.
    """
    monkeypatch.setenv("DRUG_TARGET_CRITIC_ENABLED", "false")

    import src.agents.drug_target.agent as agent_mod
    importlib.reload(agent_mod)

    config = agent_mod.DrugTargetConfig(critic_enabled=True)
    assert config.critic_enabled is True, (
        f"Explicit critic_enabled=True must win over env 'false'; got {config.critic_enabled}"
    )


# ---------------------------------------------------------------------------
# KS-04: explicit False wins over env enable (or unset)
# ---------------------------------------------------------------------------

def test_critic_enabled_explicit_false_overrides_env_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DrugTargetConfig(critic_enabled=False) wins even when env is unset/true.

    Callers that explicitly disable the critic must not be overridden by the
    default_factory.
    """
    monkeypatch.delenv("DRUG_TARGET_CRITIC_ENABLED", raising=False)

    import src.agents.drug_target.agent as agent_mod
    importlib.reload(agent_mod)

    config = agent_mod.DrugTargetConfig(critic_enabled=False)
    assert config.critic_enabled is False, (
        f"Explicit critic_enabled=False must win over unset env; got {config.critic_enabled}"
    )


# ---------------------------------------------------------------------------
# KS-05: create_drug_target_agent threads config.critic_enabled into get_subagents
# ---------------------------------------------------------------------------

def test_create_drug_target_agent_threads_critic_enabled_to_subagents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create_drug_target_agent must forward config.critic_enabled into get_subagents.

    Spies on get_subagents to confirm critic_enabled=config.critic_enabled
    is passed through regardless of env. This validates end-to-end propagation
    from the kill-switch env var all the way to the subagent factory.
    """
    monkeypatch.setenv("DRUG_TARGET_CRITIC_ENABLED", "false")

    import src.agents.drug_target.agent as agent_mod
    importlib.reload(agent_mod)

    captured_kwargs: dict = {}

    def fake_get_subagents(**kwargs: object) -> list:
        captured_kwargs.update(kwargs)
        return [
            {"name": "evidence_assessor", "description": "s", "system_prompt": "s", "tools": [], "middleware": []},
            {"name": "hypothesis_writer", "description": "s", "system_prompt": "s", "tools": [], "middleware": []},
            {"name": "summarizer", "description": "s", "system_prompt": "s", "tools": [], "middleware": []},
        ]

    dummy_agent = MagicMock()
    dummy_agent.with_config.return_value = dummy_agent

    with (
        patch.object(agent_mod, "get_subagents", side_effect=fake_get_subagents),
        patch.object(agent_mod, "create_deep_agent", return_value=dummy_agent),
        patch.object(agent_mod, "create_llm", return_value=MagicMock()),
        patch.object(agent_mod, "FilesystemBackend", return_value=MagicMock()),
        patch.object(agent_mod, "_resolve_skills_dir", return_value=MagicMock()),
        patch.object(agent_mod, "_build_subagent_skill_name_map", return_value={}),
    ):
        # Config constructed WITHOUT explicit critic_enabled -> default_factory reads env -> False
        config = agent_mod.DrugTargetConfig()
        assert config.critic_enabled is False, (
            f"Precondition: env 'false' should make critic_enabled=False; got {config.critic_enabled}"
        )
        agent_mod.create_drug_target_agent(config)

    assert "critic_enabled" in captured_kwargs, (
        f"get_subagents must receive critic_enabled kwarg; got keys: {list(captured_kwargs.keys())}"
    )
    assert captured_kwargs["critic_enabled"] is False, (
        f"Expected critic_enabled=False propagated from env; got {captured_kwargs['critic_enabled']}"
    )
