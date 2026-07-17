from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from src.agents.drug_target import guarded_pipeline


DEFAULT_MODEL = object()


class _RoleAgent:
    def __init__(
        self,
        name: str,
        calls: list[str],
        *,
        instructions: list[str] | None = None,
        first_error: RuntimeError | None = None,
    ) -> None:
        self.name = name
        self.calls = calls
        self.instructions = instructions
        self.first_error = first_error

    async def ainvoke(
        self, _input: dict[str, Any], config: Any = None
    ) -> dict[str, Any]:
        _ = config
        if self.instructions is not None:
            self.instructions.append(str(_input["messages"][0]["content"]))
        self.calls.append(self.name)
        if self.first_error is not None:
            error, self.first_error = self.first_error, None
            raise error
        return {"messages": [{"role": "assistant", "content": f"{self.name}:done"}]}


def _specs() -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "model": object(),
            "tools": [],
            "system_prompt": name,
            "middleware": [],
        }
        for name in ("evidence_assessor", "hypothesis_writer", "report_writer")
    ]


def _install_fakes(
    monkeypatch: pytest.MonkeyPatch,
    calls: list[str],
    *,
    evidence_complete: bool = True,
    hypothesis_valid: bool = True,
) -> None:
    monkeypatch.setattr(
        guarded_pipeline,
        "create_agent",
        lambda *, name, **_kwargs: _RoleAgent(name, calls),
    )
    monkeypatch.setattr(
        guarded_pipeline,
        "clear_guarded_report_run_artifacts",
        lambda _data_dir: calls.append("prepare"),
    )

    class _StageGate:
        @staticmethod
        def invoke(_args: dict[str, str]) -> str:
            return json.dumps({"stage1_complete": evidence_complete})

    monkeypatch.setattr(guarded_pipeline, "check_stage1_completion", _StageGate())
    monkeypatch.setattr(
        guarded_pipeline,
        "validate_hypothesis_report_quality",
        lambda *_args, **_kwargs: {
            "valid": hypothesis_valid,
            "errors": []
            if hypothesis_valid
            else [{"code": "HYPOTHESIS_REPORT_MISSING", "message": "missing"}],
        },
    )


def test_compile_role_preserves_legacy_spec_without_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    default_model = object()
    spec = {
        "name": "report_writer",
        "tools": [object()],
        "system_prompt": "write report",
        "middleware": [object()],
    }

    monkeypatch.setattr(
        guarded_pipeline,
        "create_agent",
        lambda **kwargs: captured.update(kwargs) or object(),
    )

    guarded_pipeline._compile_role(spec, default_model=default_model)

    assert captured == {"model": default_model, **spec}


def test_pipeline_uses_default_model_only_for_missing_role_models(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    models: dict[str, object] = {}
    specs = _specs()
    explicit_model = specs[0]["model"]
    specs[-1].pop("model")
    _install_fakes(monkeypatch, calls)

    def capture_model(*, name: str, model: object, **_kwargs: Any) -> _RoleAgent:
        models[name] = model
        return _RoleAgent(name, calls)

    monkeypatch.setattr(guarded_pipeline, "create_agent", capture_model)
    pipeline = guarded_pipeline.build_guarded_pipeline(
        specs,
        data_dir=str(tmp_path),
        default_model=DEFAULT_MODEL,
        disease="breast cancer",
        skip_evidence_assessor=False,
    )

    asyncio.run(pipeline.ainvoke({"messages": []}))

    assert models["evidence_assessor"] is explicit_model
    assert models["report_writer"] is DEFAULT_MODEL


def test_full_pipeline_runs_roles_in_code_enforced_order(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    _install_fakes(monkeypatch, calls)
    pipeline = guarded_pipeline.build_guarded_pipeline(
        _specs(),
        data_dir=str(tmp_path),
        default_model=DEFAULT_MODEL,
        disease="breast cancer",
        skip_evidence_assessor=False,
    )

    asyncio.run(pipeline.ainvoke({"messages": []}))

    assert calls == [
        "prepare",
        "evidence_assessor",
        "hypothesis_writer",
        "report_writer",
    ]


def test_resume_pipeline_skips_only_evidence_assessor(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    _install_fakes(monkeypatch, calls)
    pipeline = guarded_pipeline.build_guarded_pipeline(
        _specs(),
        data_dir=str(tmp_path),
        default_model=DEFAULT_MODEL,
        disease="breast cancer",
        skip_evidence_assessor=True,
    )

    asyncio.run(pipeline.ainvoke({"messages": []}))

    assert calls == ["prepare", "hypothesis_writer", "report_writer"]


def test_invalid_evidence_stops_before_hypothesis_and_report(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    _install_fakes(monkeypatch, calls, evidence_complete=False)
    pipeline = guarded_pipeline.build_guarded_pipeline(
        _specs(),
        data_dir=str(tmp_path),
        default_model=DEFAULT_MODEL,
        disease="breast cancer",
        skip_evidence_assessor=True,
    )

    with pytest.raises(RuntimeError, match="evidence gate failed"):
        asyncio.run(pipeline.ainvoke({"messages": []}))

    assert calls == ["prepare"]


def test_invalid_hypothesis_never_invokes_report_writer(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    _install_fakes(monkeypatch, calls, hypothesis_valid=False)
    pipeline = guarded_pipeline.build_guarded_pipeline(
        _specs(),
        data_dir=str(tmp_path),
        default_model=DEFAULT_MODEL,
        disease="breast cancer",
        skip_evidence_assessor=True,
    )

    with pytest.raises(RuntimeError, match="hypothesis gate failed"):
        asyncio.run(pipeline.ainvoke({"messages": []}))

    assert calls == ["prepare", "hypothesis_writer"]


def test_missing_hypothesis_report_retries_writer_once_before_report(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    instructions: list[str] = []
    missing = RuntimeError("Hypothesis report guardrail failed with HYPOTHESIS_REPORT_MISSING")

    def fake_create_agent(*, name: str, **_kwargs: Any) -> _RoleAgent:
        return _RoleAgent(
            name,
            calls,
            instructions=instructions if name == "hypothesis_writer" else None,
            first_error=missing if name == "hypothesis_writer" else None,
        )

    monkeypatch.setattr(guarded_pipeline, "create_agent", fake_create_agent)
    monkeypatch.setattr(
        guarded_pipeline,
        "clear_guarded_report_run_artifacts",
        lambda _data_dir: calls.append("prepare"),
    )
    class _StageGate:
        @staticmethod
        def invoke(_args: dict[str, str]) -> str:
            return json.dumps({"stage1_complete": True})

    monkeypatch.setattr(guarded_pipeline, "check_stage1_completion", _StageGate())
    monkeypatch.setattr(
        guarded_pipeline,
        "validate_hypothesis_report_quality",
        lambda *_args, **_kwargs: {"valid": True, "errors": []},
    )

    pipeline = guarded_pipeline.build_guarded_pipeline(
        _specs(),
        data_dir=str(tmp_path),
        default_model=DEFAULT_MODEL,
        disease="breast cancer",
        skip_evidence_assessor=True,
    )

    asyncio.run(pipeline.ainvoke({"messages": []}))

    assert calls == ["prepare", "hypothesis_writer", "hypothesis_writer", "report_writer"]
    assert "save_hypothesis_report" in instructions[1]


def test_nonmissing_hypothesis_error_is_not_retried(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    error = RuntimeError("Hypothesis report guardrail failed with HYPOTHESIS_LAST_SAVE_REJECTION")

    def fake_create_agent(*, name: str, **_kwargs: Any) -> _RoleAgent:
        return _RoleAgent(name, calls, first_error=error if name == "hypothesis_writer" else None)

    monkeypatch.setattr(guarded_pipeline, "create_agent", fake_create_agent)
    monkeypatch.setattr(
        guarded_pipeline,
        "clear_guarded_report_run_artifacts",
        lambda _data_dir: calls.append("prepare"),
    )
    class _StageGate:
        @staticmethod
        def invoke(_args: dict[str, str]) -> str:
            return json.dumps({"stage1_complete": True})

    monkeypatch.setattr(guarded_pipeline, "check_stage1_completion", _StageGate())

    pipeline = guarded_pipeline.build_guarded_pipeline(
        _specs(),
        data_dir=str(tmp_path),
        default_model=DEFAULT_MODEL,
        disease="breast cancer",
        skip_evidence_assessor=True,
    )

    with pytest.raises(RuntimeError, match="HYPOTHESIS_LAST_SAVE_REJECTION"):
        asyncio.run(pipeline.ainvoke({"messages": []}))

    assert calls == ["prepare", "hypothesis_writer"]


def test_ollama_hypothesis_persists_final_json_before_report(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    persisted: list[str] = []

    class _JsonRole(_RoleAgent):
        async def ainvoke(self, _input: dict[str, Any], config: Any = None):
            _ = config
            self.calls.append(self.name)
            if self.name == "hypothesis_writer":
                return {
                    "messages": [
                        AIMessage(content='{"hypotheses": []}')
                    ]
                }
            return {"messages": [AIMessage(content="done")]}

    monkeypatch.setattr(
        guarded_pipeline,
        "create_agent",
        lambda *, name, **_kwargs: _JsonRole(name, calls),
    )
    monkeypatch.setattr(
        guarded_pipeline,
        "clear_guarded_report_run_artifacts",
        lambda _data_dir: calls.append("prepare"),
    )
    monkeypatch.setattr(
        guarded_pipeline,
        "save_hypothesis_report_from_text",
        lambda _data_dir, text: persisted.append(text) or {"saved": True},
    )

    class _StageGate:
        @staticmethod
        def invoke(_args: dict[str, str]) -> str:
            return json.dumps({"stage1_complete": True})

    monkeypatch.setattr(guarded_pipeline, "check_stage1_completion", _StageGate())
    monkeypatch.setattr(
        guarded_pipeline,
        "validate_hypothesis_report_quality",
        lambda *_args, **_kwargs: {"valid": True, "errors": []},
    )
    pipeline = guarded_pipeline.build_guarded_pipeline(
        _specs(),
        data_dir=str(tmp_path),
        default_model=DEFAULT_MODEL,
        disease="breast cancer",
        skip_evidence_assessor=True,
        provider="ollama",
    )

    asyncio.run(pipeline.ainvoke({"messages": []}))

    assert calls == ["prepare", "hypothesis_writer", "report_writer"]
    assert persisted == ['{"hypotheses": []}']
