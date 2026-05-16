"""Guard tests for get_summarizer_subagent factory (EV-P0-001 + EV-P0-002).

Three deterministic tests (no LLM calls):

FG-01: test_get_summarizer_subagent_default_critic_enabled_is_true
    Bare call with critic_model supplied → critic gate (SubAgentMiddleware)
    present in middleware list, confirming default critic_enabled=True.

FG-02: test_get_summarizer_subagent_raises_when_critic_enabled_and_critic_model_is_none
    critic_enabled=True, critic_model=None → ValueError with message
    mentioning SUBAGENT_CRITIC_PROVIDER and SUBAGENT_CRITIC_MODEL.

FG-03: test_get_summarizer_subagent_critic_disabled_with_no_model_does_not_raise
    critic_enabled=False, critic_model=None → no exception; spec returned
    without any SubAgentMiddleware.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from src.agents.drug_target.subagents.summarizer.agent import get_summarizer_subagent


# ---------------------------------------------------------------------------
# FG-01
# ---------------------------------------------------------------------------


def test_get_summarizer_subagent_default_critic_enabled_is_true() -> None:
    """Bare call (no critic_enabled= arg) with a valid critic_model must
    install SubAgentMiddleware, confirming the default is True.
    """
    stub_critic_spec = {"name": "critic", "model": "openai:gpt-4o", "tools": []}
    stub_backend = MagicMock(name="stub_backend")
    stub_mw_instance = MagicMock(name="stub_SubAgentMiddleware_instance")

    with (
        patch(
            "src.agents.drug_target.subagents.summarizer.agent.get_critic_subagent",
            return_value=stub_critic_spec,
        ),
        patch(
            "src.agents.drug_target.subagents.summarizer.agent.SubAgentMiddleware",
            return_value=stub_mw_instance,
        ) as mock_mw_cls,
    ):
        # No critic_enabled= argument — default must be True
        spec = get_summarizer_subagent(
            backend=stub_backend,
            critic_model="openai:gpt-4o",
        )

    # SubAgentMiddleware must have been constructed (critic gate installed)
    mock_mw_cls.assert_called_once()
    assert stub_mw_instance in spec["middleware"], (
        "SubAgentMiddleware instance must be in middleware when default critic_enabled=True"
    )


# ---------------------------------------------------------------------------
# FG-02
# ---------------------------------------------------------------------------


def test_get_summarizer_subagent_raises_when_critic_enabled_and_critic_model_is_none() -> None:
    """critic_enabled=True with critic_model=None must raise ValueError with
    an actionable message mentioning SUBAGENT_CRITIC_PROVIDER and
    SUBAGENT_CRITIC_MODEL.
    """
    with pytest.raises(ValueError) as exc_info:
        get_summarizer_subagent(critic_enabled=True, critic_model=None)

    message = str(exc_info.value)
    assert "SUBAGENT_CRITIC_PROVIDER" in message, (
        f"ValueError message must mention SUBAGENT_CRITIC_PROVIDER; got: {message!r}"
    )
    assert "SUBAGENT_CRITIC_MODEL" in message, (
        f"ValueError message must mention SUBAGENT_CRITIC_MODEL; got: {message!r}"
    )


# ---------------------------------------------------------------------------
# FG-03
# ---------------------------------------------------------------------------


def test_get_summarizer_subagent_critic_disabled_with_no_model_does_not_raise() -> None:
    """critic_enabled=False, critic_model=None must not raise and must return
    a spec without any SubAgentMiddleware in its middleware list.
    """
    with (
        patch(
            "src.agents.drug_target.subagents.summarizer.agent.SubAgentMiddleware",
        ) as mock_mw_cls,
    ):
        spec = get_summarizer_subagent(critic_enabled=False, critic_model=None)

    # No SubAgentMiddleware must have been constructed
    mock_mw_cls.assert_not_called()

    assert isinstance(spec, dict), "Must return a dict spec"
    assert isinstance(spec["middleware"], list), "middleware must be a list"
    # Confirm no SubAgentMiddleware instance in the list
    # (patch ensures the real class is replaced, so no real instances exist)
    assert mock_mw_cls.return_value not in spec["middleware"], (
        "SubAgentMiddleware must not be present when critic_enabled=False"
    )
