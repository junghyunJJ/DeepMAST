"""Task #4 tests: SubAgentMiddleware install in get_summarizer_subagent.

Three deterministic tests (no LLM calls):

TN-01: test_summarizer_installs_subagent_middleware_when_critic_enabled
    critic_enabled=True → exactly one SubAgentMiddleware in middleware list
    and its subagents contains the critic spec.

TN-02: test_summarizer_omits_subagent_middleware_when_critic_disabled
    critic_enabled=False → NO SubAgentMiddleware in middleware list.

TN-03: test_summarizer_passes_critic_model_to_get_critic_subagent
    spy confirms get_critic_subagent receives model=<critic_model> from factory.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from src.agents.drug_target.subagents.summarizer import get_summarizer_subagent


# ---------------------------------------------------------------------------
# TN-01
# ---------------------------------------------------------------------------


def test_summarizer_installs_subagent_middleware_when_critic_enabled() -> None:
    """get_summarizer_subagent(critic_enabled=True) must install exactly one
    SubAgentMiddleware and its subagents list must contain the critic spec."""
    stub_critic_spec = {"name": "critic", "model": "openai:gpt-4o", "tools": []}
    stub_backend = MagicMock(name="stub_backend")
    stub_mw_instance = MagicMock(name="stub_SubAgentMiddleware_instance")

    with (
        patch(
            "src.agents.drug_target.subagents.summarizer.agent.get_critic_subagent",
            return_value=stub_critic_spec,
        ) as mock_get_critic,
        patch(
            "src.agents.drug_target.subagents.summarizer.agent.SubAgentMiddleware",
            return_value=stub_mw_instance,
        ) as mock_mw_cls,
    ):
        spec = get_summarizer_subagent(
            backend=stub_backend,
            critic_model="openai:gpt-4o",
            critic_enabled=True,
        )

    # SubAgentMiddleware must have been constructed once
    mock_mw_cls.assert_called_once()
    _, kwargs = mock_mw_cls.call_args
    assert kwargs["backend"] is stub_backend, (
        "SubAgentMiddleware must receive the same backend passed to get_summarizer_subagent"
    )
    assert stub_critic_spec in kwargs["subagents"], (
        "SubAgentMiddleware subagents must contain the critic spec"
    )

    # The instance must appear in middleware
    assert stub_mw_instance in spec["middleware"], (
        "SubAgentMiddleware instance must be in the returned middleware list"
    )

    # Exactly one SubAgentMiddleware-typed item (mocked as stub_mw_instance)
    mw_instances = [m for m in spec["middleware"] if m is stub_mw_instance]
    assert len(mw_instances) == 1, (
        f"Expected exactly 1 SubAgentMiddleware, found {len(mw_instances)}"
    )

    # get_critic_subagent was called
    mock_get_critic.assert_called_once()


# ---------------------------------------------------------------------------
# TN-02
# ---------------------------------------------------------------------------


def test_summarizer_omits_subagent_middleware_when_critic_disabled() -> None:
    """get_summarizer_subagent(critic_enabled=False) must NOT install any
    SubAgentMiddleware regardless of backend/critic_model values."""
    stub_backend = MagicMock(name="stub_backend")

    with (
        patch(
            "src.agents.drug_target.subagents.summarizer.agent.get_critic_subagent",
        ) as mock_get_critic,
        patch(
            "src.agents.drug_target.subagents.summarizer.agent.SubAgentMiddleware",
        ) as mock_mw_cls,
    ):
        spec = get_summarizer_subagent(
            backend=stub_backend,
            critic_model="openai:gpt-4o",
            critic_enabled=False,
        )

    # SubAgentMiddleware must NOT have been instantiated
    mock_mw_cls.assert_not_called()
    # get_critic_subagent must NOT have been called
    mock_get_critic.assert_not_called()

    # Middleware list must contain no SubAgentMiddleware instances
    # (since SubAgentMiddleware is patched and not called, none can exist)
    assert spec["middleware"] is not None
    assert isinstance(spec["middleware"], list)


# ---------------------------------------------------------------------------
# TN-03
# ---------------------------------------------------------------------------


def test_summarizer_passes_critic_model_to_get_critic_subagent() -> None:
    """get_summarizer_subagent must forward critic_model to get_critic_subagent
    as the positional model= argument."""
    stub_critic_spec = {"name": "critic", "model": "openai:gpt-4o-mini", "tools": []}
    stub_backend = MagicMock(name="stub_backend")
    stub_mw_instance = MagicMock(name="stub_mw_instance")

    with (
        patch(
            "src.agents.drug_target.subagents.summarizer.agent.get_critic_subagent",
            return_value=stub_critic_spec,
        ) as mock_get_critic,
        patch(
            "src.agents.drug_target.subagents.summarizer.agent.SubAgentMiddleware",
            return_value=stub_mw_instance,
        ),
    ):
        get_summarizer_subagent(
            backend=stub_backend,
            critic_model="openai:gpt-4o-mini",
            critic_enabled=True,
        )

    # Must have been called with model= set to the critic_model value
    mock_get_critic.assert_called_once_with(model="openai:gpt-4o-mini")
