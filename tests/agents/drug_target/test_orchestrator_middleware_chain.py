"""Smoke test: ThinkToolQualityGateMiddleware is mounted in the orchestrator middleware list.

Verifies CV-P0-001 fix: the gate must not be dead code at runtime.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from src.agents.deep_interpreter.middleware.think_tool_quality_gate import (
    ThinkToolQualityGateMiddleware,
)
from src.agents.drug_target.agent import DrugTargetConfig


def _make_stub_agent() -> MagicMock:
    stub = MagicMock()
    stub.with_config.return_value = stub
    return stub


def test_orchestrator_middleware_includes_think_tool_quality_gate(tmp_path):
    """create_drug_target_agent must mount ThinkToolQualityGateMiddleware in its middleware list."""
    captured_kwargs: dict = {}

    def fake_create_deep_agent(**kwargs):
        captured_kwargs.update(kwargs)
        return _make_stub_agent()

    with patch(
        "src.agents.drug_target.agent.create_deep_agent",
        side_effect=fake_create_deep_agent,
    ):
        from src.agents.drug_target.agent import create_drug_target_agent

        config = DrugTargetConfig(data_dir=str(tmp_path))
        create_drug_target_agent(config=config)

    middleware_list = captured_kwargs.get("middleware", [])
    middleware_types = [type(m) for m in middleware_list]

    assert ThinkToolQualityGateMiddleware in middleware_types, (
        f"ThinkToolQualityGateMiddleware not found in orchestrator middleware list; "
        f"got: {middleware_types}"
    )
