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


def test_ollama_generates_one_bounded_card_per_spec(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    instructions: list[str] = []
    saved_reports: list[dict[str, object]] = []
    specs = [
        {
            "id": card_id,
            "category": category,
            "genes": [gene],
            "evidence_references": [f"ot_{gene}.json", f"stage3_{gene}.json"],
            "cell_anchor": "malignant cell",
            "fallback_hypothesis": f"{gene} is a validation candidate.",
            "known_genes": ("EFNB2", "EPHB4", "ERBB2", "ERBB3", "SDC1"),
        }
        for card_id, category, gene in (
            ("mechanism", "Mechanism of Action", "EFNB2"),
            ("therapy", "Therapeutic Strategy", "EPHB4"),
            ("cross_target", "Cross-Target Interaction", "ERBB2"),
            ("novel_pathway", "Novel Pathway", "ERBB3"),
        )
    ]
    report = {"hypotheses": []}

    class _CardRole(_RoleAgent):
        async def ainvoke(self, _input: dict[str, Any], config: Any = None):
            _ = config
            self.calls.append(self.name)
            if self.name == "hypothesis_writer":
                instructions.append(str(_input["messages"][0]["content"]))
                return {"messages": [AIMessage(content="Candidate warrants validation.")]}
            return {"messages": [AIMessage(content="done")]}

    monkeypatch.setattr(
        guarded_pipeline,
        "create_agent",
        lambda *, name, **_kwargs: _CardRole(name, calls),
    )
    monkeypatch.setattr(
        guarded_pipeline,
        "clear_guarded_report_run_artifacts",
        lambda _data_dir: calls.append("prepare"),
    )
    monkeypatch.setattr(
        guarded_pipeline,
        "build_ollama_card_specs",
        lambda _data_dir: specs,
    )
    monkeypatch.setattr(
        guarded_pipeline,
        "build_ollama_hypothesis_report",
        lambda _data_dir, _card_texts: report,
    )

    class _SaveTool:
        @staticmethod
        def invoke(arguments: dict[str, object]) -> str:
            saved_reports.append(arguments["report"])
            return json.dumps({"saved": True})

    monkeypatch.setattr(guarded_pipeline, "save_hypothesis_report", _SaveTool())

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

    assert calls == [
        "prepare",
        "hypothesis_writer",
        "hypothesis_writer",
        "hypothesis_writer",
        "hypothesis_writer",
        "report_writer",
    ]
    assert [instruction.split("Card ID: ")[1].split("\n", 1)[0] for instruction in instructions] == [
        spec["id"] for spec in specs
    ]
    assert saved_reports == [report]


def test_rejected_ollama_card_retries_once_then_uses_fallback(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    saved_card_texts: dict[str, str] = {}
    specs = [
        {
            "id": card_id,
            "category": category,
            "genes": [gene],
            "evidence_references": [f"ot_{gene}.json", f"stage3_{gene}.json"],
            "cell_anchor": "malignant cell",
            "fallback_hypothesis": f"{gene} is a validation candidate.",
            "known_genes": ("EFNB2", "EPHB4", "ERBB2", "ERBB3", "SDC1"),
        }
        for card_id, category, gene in (
            ("mechanism", "Mechanism of Action", "EFNB2"),
            ("therapy", "Therapeutic Strategy", "EPHB4"),
            ("cross_target", "Cross-Target Interaction", "ERBB2"),
            ("novel_pathway", "Novel Pathway", "ERBB3"),
        )
    ]
    responses = iter(
        [
            "SDC1 warrants validation.",
            "SDC1 warrants validation.",
            "Candidate warrants validation.",
            "Candidate warrants validation.",
            "Candidate warrants validation.",
        ]
    )

    class _CardRole(_RoleAgent):
        async def ainvoke(self, _input: dict[str, Any], config: Any = None):
            _ = config
            self.calls.append(self.name)
            if self.name == "hypothesis_writer":
                return {"messages": [AIMessage(content=next(responses))]}
            return {"messages": [AIMessage(content="done")]}

    monkeypatch.setattr(
        guarded_pipeline,
        "create_agent",
        lambda *, name, **_kwargs: _CardRole(name, calls),
    )
    monkeypatch.setattr(
        guarded_pipeline,
        "clear_guarded_report_run_artifacts",
        lambda _data_dir: calls.append("prepare"),
    )
    monkeypatch.setattr(
        guarded_pipeline,
        "build_ollama_card_specs",
        lambda _data_dir: specs,
    )
    monkeypatch.setattr(
        guarded_pipeline,
        "build_ollama_hypothesis_report",
        lambda _data_dir, card_texts: saved_card_texts.update(card_texts)
        or {"hypotheses": []},
    )

    class _SaveTool:
        @staticmethod
        def invoke(_arguments: dict[str, object]) -> str:
            return json.dumps({"saved": True})

    monkeypatch.setattr(guarded_pipeline, "save_hypothesis_report", _SaveTool())

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

    assert calls.count("hypothesis_writer") == 5
    assert saved_card_texts["mechanism"] == specs[0]["fallback_hypothesis"]
