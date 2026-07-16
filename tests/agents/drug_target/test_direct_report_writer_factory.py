"""Construction contract for the diagnostic-only guarded report writer."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.agents.drug_target import agent
from src.agents.drug_target.middleware import DrugReportGuardrailMiddleware
from src.agents.shared.skill_activator import SkillActivator
from src.agents.shared.skills_middleware import SkillsMiddleware


def test_direct_factory_recompiles_the_canonical_guarded_report_writer(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected_model = MagicMock()
    compiled_writer = MagicMock()
    captured: dict[str, object] = {}
    tools = [MagicMock(name="report_tool")]
    system_prompt = "canonical report writer prompt"

    def fake_get_subagents(**kwargs):
        captured["subagent_kwargs"] = kwargs
        guardrail = DrugReportGuardrailMiddleware(
            tmp_path,
            provider=kwargs["provider"],
            model=kwargs["report_writer_model"],
            request_timeout_seconds=kwargs["report_writer_request_timeout_seconds"],
            disease=kwargs["disease"],
        )
        captured["writer_middleware"] = [guardrail]
        return [
            {"name": "evidence_assessor"},
            {
                "name": "report_writer",
                "model": selected_model,
                "tools": tools,
                "system_prompt": system_prompt,
                "middleware": captured["writer_middleware"],
            },
        ]

    def fake_create_agent(**kwargs):
        captured["create_agent_kwargs"] = kwargs
        return compiled_writer

    monkeypatch.setattr(
        agent,
        "create_llm",
        lambda **kwargs: captured.setdefault("llm_kwargs", kwargs) and selected_model,
    )
    monkeypatch.setattr(agent, "get_subagents", fake_get_subagents)
    monkeypatch.setattr(agent, "create_agent", fake_create_agent, raising=False)

    writer = agent.create_guarded_report_writer(
        agent.DrugTargetConfig(
            provider="ollama-openai",
            model="qwen3.5:122b",
            request_timeout_seconds=45.0,
            data_dir=str(tmp_path),
            disease="IPF",
            subagent_models={},
        )
    )

    assert writer is compiled_writer
    assert captured["llm_kwargs"] == {
        "provider": "ollama-openai",
        "model": "qwen3.5:122b",
        "request_timeout": 45.0,
    }
    subagent_kwargs = captured["subagent_kwargs"]
    assert subagent_kwargs["report_writer_model"] == "qwen3.5:122b"
    assert subagent_kwargs["report_writer_request_timeout_seconds"] == 45.0
    assert subagent_kwargs["model_overrides"] == {"report_writer": selected_model}
    assert captured["create_agent_kwargs"] == {
        "model": selected_model,
        "tools": tools,
        "system_prompt": system_prompt,
        "middleware": captured["writer_middleware"],
        "name": "report_writer",
    }
    guardrails = [
        middleware
        for middleware in captured["create_agent_kwargs"]["middleware"]
        if isinstance(middleware, DrugReportGuardrailMiddleware)
    ]
    assert len(guardrails) == 1
    assert guardrails[0]._provider == "ollama-openai"
    assert guardrails[0]._model == "qwen3.5:122b"
    assert guardrails[0]._request_timeout_seconds == 45.0


@pytest.mark.parametrize("subagent_specs", [[], [{"name": "report_writer"}] * 2])
def test_direct_factory_requires_exactly_one_report_writer_spec(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    subagent_specs: list[dict[str, object]],
) -> None:
    monkeypatch.setattr(agent, "get_subagents", lambda **_kwargs: subagent_specs)

    with pytest.raises(ValueError, match="exactly one report_writer"):
        agent.create_guarded_report_writer(
            agent.DrugTargetConfig(data_dir=str(tmp_path), subagent_models={})
        )


def test_direct_factory_rejects_legacy_output_mode(tmp_path) -> None:
    with pytest.raises(ValueError, match="workflow_mode='guarded_report'"):
        agent.create_guarded_report_writer(
            agent.DrugTargetConfig(
                workflow_mode="legacy_hypothesis",
                data_dir=str(tmp_path),
                subagent_models={},
            )
        )


def test_direct_factory_matches_production_docker_skill_middleware(tmp_path, monkeypatch) -> None:
    compiled_writer = MagicMock()
    captured: dict[str, object] = {}

    monkeypatch.setattr(agent, "create_llm", lambda **_kwargs: MagicMock())
    monkeypatch.setattr(
        agent,
        "create_agent",
        lambda **kwargs: captured.update(kwargs) or compiled_writer,
    )

    writer = agent.create_guarded_report_writer(
        agent.DrugTargetConfig(
            data_dir=str(tmp_path),
            docker_image="python:3.12-slim",
            subagent_models={},
        )
    )

    assert writer is compiled_writer
    assert not any(
        isinstance(middleware, (SkillsMiddleware, SkillActivator))
        for middleware in captured["middleware"]
    )


def test_production_factory_still_builds_the_outer_deep_agent(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected_model = MagicMock()
    compiled_agent = MagicMock()
    compiled_agent.with_config.return_value = compiled_agent
    captured: dict[str, object] = {}
    production_specs = [
        {"name": "evidence_assessor"},
        {"name": "report_writer", "model": selected_model},
    ]

    monkeypatch.setattr(agent, "create_llm", lambda **_kwargs: selected_model)
    monkeypatch.setattr(agent, "get_subagents", lambda **_kwargs: production_specs)
    monkeypatch.setattr(
        agent,
        "create_deep_agent",
        lambda **kwargs: captured.update(kwargs) or compiled_agent,
    )

    result, _ = agent.create_drug_target_agent(
        agent.DrugTargetConfig(data_dir=str(tmp_path), subagent_models={})
    )

    assert result is compiled_agent
    assert captured["subagents"] is production_specs
