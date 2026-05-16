"""Factory wiring tests for drug_target critic propagation (Task #1).

Covers:
  FW-01: get_subagents threads critic_enabled=True into get_summarizer_subagent.
  FW-02: get_subagents threads critic_enabled=False into get_summarizer_subagent.
  FW-03: get_subagents top-level subagent names are exactly the expected three.
  FW-04: get_subagents resolves critic_model from model_overrides["critic"].
  FW-05: get_subagents falls back critic_model to model_overrides["summarizer"].
  FW-06: get_subagents falls back critic_model to default_model when no override.
  FW-07: DrugTargetConfig.__post_init__ includes "critic" in subagent_models env load.
  FW-08: create_drug_target_agent passes config.critic_enabled into get_subagents.

All tests are deterministic (no LLM calls, no I/O). Run with:
  uv run pytest tests/agents/drug_target/test_drug_target_factory_wiring.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# FW-01: critic_enabled=True threads through to get_summarizer_subagent
# ---------------------------------------------------------------------------

def test_get_subagents_threads_critic_enabled_true_to_summarizer_factory() -> None:
    """get_subagents(critic_enabled=True) must call get_summarizer_subagent with
    critic_enabled=True as a keyword argument."""
    dummy_spec = {
        "name": "summarizer",
        "description": "stub",
        "system_prompt": "stub",
        "tools": [],
        "middleware": [],
    }
    with patch(
        "src.agents.drug_target.subagents.configs.get_summarizer_subagent",
        return_value=dummy_spec,
    ) as mock_factory:
        from src.agents.drug_target.subagents.configs import get_subagents

        get_subagents(critic_enabled=True)

        mock_factory.assert_called_once()
        _, kwargs = mock_factory.call_args
        assert kwargs.get("critic_enabled") is True, (
            f"Expected critic_enabled=True in call kwargs; got {kwargs}"
        )


# ---------------------------------------------------------------------------
# FW-02: critic_enabled=False threads through to get_summarizer_subagent
# ---------------------------------------------------------------------------

def test_get_subagents_threads_critic_enabled_false_to_summarizer_factory() -> None:
    """get_subagents(critic_enabled=False) must call get_summarizer_subagent with
    critic_enabled=False — the kill switch must propagate faithfully."""
    dummy_spec = {
        "name": "summarizer",
        "description": "stub",
        "system_prompt": "stub",
        "tools": [],
        "middleware": [],
    }
    with patch(
        "src.agents.drug_target.subagents.configs.get_summarizer_subagent",
        return_value=dummy_spec,
    ) as mock_factory:
        from src.agents.drug_target.subagents.configs import get_subagents

        get_subagents(critic_enabled=False)

        mock_factory.assert_called_once()
        _, kwargs = mock_factory.call_args
        assert kwargs.get("critic_enabled") is False, (
            f"Expected critic_enabled=False in call kwargs; got {kwargs}"
        )


# ---------------------------------------------------------------------------
# FW-03: top-level subagent names are exactly the expected three
# ---------------------------------------------------------------------------

def test_get_subagents_factory_output_does_not_include_top_level_critic() -> None:
    """The returned list must contain exactly evidence_assessor, hypothesis_writer,
    and summarizer — no top-level critic entry."""
    dummy_spec = {
        "name": "summarizer",
        "description": "stub",
        "system_prompt": "stub",
        "tools": [],
        "middleware": [],
    }
    with patch(
        "src.agents.drug_target.subagents.configs.get_summarizer_subagent",
        return_value=dummy_spec,
    ):
        from src.agents.drug_target.subagents.configs import get_subagents

        result = get_subagents()

    names = {s["name"] for s in result}
    assert names == {"evidence_assessor", "hypothesis_writer", "summarizer"}, (
        f"Top-level subagents must be exactly the three; got {sorted(names)}"
    )


# ---------------------------------------------------------------------------
# FW-04: critic_model resolved from model_overrides["critic"]
# ---------------------------------------------------------------------------

def test_get_subagents_resolves_critic_model_from_critic_override() -> None:
    """When model_overrides contains a 'critic' key, get_summarizer_subagent
    must receive that model as critic_model."""
    critic_model_stub = MagicMock(name="critic_model")
    dummy_spec = {
        "name": "summarizer",
        "description": "stub",
        "system_prompt": "stub",
        "tools": [],
        "middleware": [],
    }
    with patch(
        "src.agents.drug_target.subagents.configs.get_summarizer_subagent",
        return_value=dummy_spec,
    ) as mock_factory:
        from src.agents.drug_target.subagents.configs import get_subagents

        get_subagents(
            model_overrides={"critic": critic_model_stub},
            default_model=MagicMock(name="default_model"),
        )

        _, kwargs = mock_factory.call_args
        assert kwargs.get("critic_model") is critic_model_stub, (
            f"Expected critic_model from 'critic' override; got {kwargs.get('critic_model')}"
        )


# ---------------------------------------------------------------------------
# FW-05: critic_model falls back to model_overrides["summarizer"]
# ---------------------------------------------------------------------------

def test_get_subagents_critic_model_falls_back_to_summarizer_override() -> None:
    """When model_overrides has no 'critic' key but has 'summarizer', critic_model
    must be the summarizer override."""
    summarizer_model_stub = MagicMock(name="summarizer_model")
    dummy_spec = {
        "name": "summarizer",
        "description": "stub",
        "system_prompt": "stub",
        "tools": [],
        "middleware": [],
    }
    with patch(
        "src.agents.drug_target.subagents.configs.get_summarizer_subagent",
        return_value=dummy_spec,
    ) as mock_factory:
        from src.agents.drug_target.subagents.configs import get_subagents

        get_subagents(
            model_overrides={"summarizer": summarizer_model_stub},
            default_model=MagicMock(name="default_model"),
        )

        _, kwargs = mock_factory.call_args
        assert kwargs.get("critic_model") is summarizer_model_stub, (
            f"Expected critic_model from 'summarizer' fallback; got {kwargs.get('critic_model')}"
        )


# ---------------------------------------------------------------------------
# FW-06: critic_model falls back to default_model when no override
# ---------------------------------------------------------------------------

def test_get_subagents_critic_model_falls_back_to_default_model() -> None:
    """When model_overrides has neither 'critic' nor 'summarizer', critic_model
    must be the default_model."""
    default_model_stub = MagicMock(name="default_model")
    dummy_spec = {
        "name": "summarizer",
        "description": "stub",
        "system_prompt": "stub",
        "tools": [],
        "middleware": [],
    }
    with patch(
        "src.agents.drug_target.subagents.configs.get_summarizer_subagent",
        return_value=dummy_spec,
    ) as mock_factory:
        from src.agents.drug_target.subagents.configs import get_subagents

        get_subagents(default_model=default_model_stub)

        _, kwargs = mock_factory.call_args
        assert kwargs.get("critic_model") is default_model_stub, (
            f"Expected critic_model=default_model; got {kwargs.get('critic_model')}"
        )


# ---------------------------------------------------------------------------
# FW-07: DrugTargetConfig includes "critic" in subagent_models env load
# ---------------------------------------------------------------------------

def test_drug_target_config_includes_critic_in_subagent_models_env_load() -> None:
    """DrugTargetConfig.__post_init__ must call load_subagent_models_from_env
    with 'critic' in the list, so SUBAGENT_CRITIC_PROVIDER env var is respected."""
    captured_calls: list[list[str]] = []

    def fake_load(names: list[str]) -> dict:
        captured_calls.append(list(names))
        return {}

    with patch(
        "src.agents.drug_target.agent.load_subagent_models_from_env",
        side_effect=fake_load,
    ):
        from src.agents.drug_target.agent import DrugTargetConfig

        DrugTargetConfig(subagent_models=None)

    assert captured_calls, "load_subagent_models_from_env was never called"
    all_names = [n for call_names in captured_calls for n in call_names]
    assert "critic" in all_names, (
        f"'critic' must appear in load_subagent_models_from_env call; got {all_names}"
    )


# ---------------------------------------------------------------------------
# FW-08: create_drug_target_agent passes config.critic_enabled into get_subagents
# ---------------------------------------------------------------------------

def test_create_drug_target_agent_passes_critic_enabled_to_get_subagents() -> None:
    """create_drug_target_agent must forward config.critic_enabled into
    get_subagents so the kill switch propagates end-to-end."""
    captured_kwargs: dict = {}

    def fake_get_subagents(**kwargs: object) -> list:
        captured_kwargs.update(kwargs)
        return [
            {
                "name": "evidence_assessor",
                "description": "stub",
                "system_prompt": "stub",
                "tools": [],
                "middleware": [],
            },
            {
                "name": "hypothesis_writer",
                "description": "stub",
                "system_prompt": "stub",
                "tools": [],
                "middleware": [],
            },
            {
                "name": "summarizer",
                "description": "stub",
                "system_prompt": "stub",
                "tools": [],
                "middleware": [],
            },
        ]

    dummy_agent = MagicMock()
    dummy_agent.with_config.return_value = dummy_agent

    with (
        patch("src.agents.drug_target.agent.get_subagents", side_effect=fake_get_subagents),
        patch("src.agents.drug_target.agent.create_deep_agent", return_value=dummy_agent),
        patch("src.agents.drug_target.agent.create_llm", return_value=MagicMock()),
        patch("src.agents.drug_target.agent.FilesystemBackend", return_value=MagicMock()),
        patch("src.agents.drug_target.agent._resolve_skills_dir", return_value=MagicMock()),
        patch("src.agents.drug_target.agent._build_subagent_skill_name_map", return_value={}),
    ):
        from src.agents.drug_target.agent import DrugTargetConfig, create_drug_target_agent

        config = DrugTargetConfig(critic_enabled=False)
        create_drug_target_agent(config)

    assert "critic_enabled" in captured_kwargs, (
        f"get_subagents must receive critic_enabled kwarg; got keys: {list(captured_kwargs.keys())}"
    )
    assert captured_kwargs["critic_enabled"] is False, (
        f"Expected critic_enabled=False; got {captured_kwargs['critic_enabled']}"
    )
