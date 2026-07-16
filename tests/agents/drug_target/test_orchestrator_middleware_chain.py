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
from src.agents.drug_target.middleware import (
    DrugReportRunCleanupMiddleware,
    DrugTargetManagedFilesystemGuardMiddleware,
    DrugTargetTaskAllowlistMiddleware,
)


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


def test_guarded_orchestrator_exposes_only_bound_topology(tmp_path, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr("src.agents.drug_target.agent.create_llm", lambda **_: FakeListChatModel(responses=["ok"]))
    monkeypatch.setattr("src.agents.drug_target.agent.create_deep_agent", lambda **kwargs: captured.update(kwargs) or _make_stub_agent())

    from src.agents.drug_target.agent import create_drug_target_agent

    create_drug_target_agent(DrugTargetConfig(data_dir=str(tmp_path), provider="ollama"))

    assert {tool.name for tool in captured["tools"]} == {"load_lr_candidates"}
    assert [item["name"] for item in captured["subagents"]] == ["evidence_assessor", "report_writer"]
    middleware = captured["middleware"]
    assert sum(isinstance(item, DrugReportRunCleanupMiddleware) for item in middleware) == 1
    assert sum(isinstance(item, DrugTargetManagedFilesystemGuardMiddleware) for item in middleware) == 1
    assert sum(isinstance(item, DrugTargetTaskAllowlistMiddleware) for item in middleware) == 1
    assert "REPORT_PIPELINE_COMPLETE" in captured["system_prompt"]
    assert "hypothesis_writer" not in captured["system_prompt"]


def test_legacy_orchestrator_keeps_compatibility_surface(tmp_path, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr("src.agents.drug_target.agent.create_llm", lambda **_: FakeListChatModel(responses=["ok"]))
    monkeypatch.setattr("src.agents.drug_target.agent.create_deep_agent", lambda **kwargs: captured.update(kwargs) or _make_stub_agent())

    from src.agents.drug_target.agent import create_drug_target_agent

    create_drug_target_agent(
        DrugTargetConfig(data_dir=str(tmp_path), provider="ollama", workflow_mode="legacy_hypothesis")
    )
    assert "read_skill_file" in {tool.name for tool in captured["tools"]}
    assert [item["name"] for item in captured["subagents"]] == ["evidence_assessor", "hypothesis_writer"]
    assert not any(isinstance(item, (DrugReportRunCleanupMiddleware, DrugTargetManagedFilesystemGuardMiddleware, DrugTargetTaskAllowlistMiddleware)) for item in captured["middleware"])
    assert "hypothesis_writer" in captured["system_prompt"]
