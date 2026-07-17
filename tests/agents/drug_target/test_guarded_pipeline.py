from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from src.agents.drug_target import guarded_pipeline


class _RoleAgent:
    def __init__(self, name: str, calls: list[str]) -> None:
        self.name = name
        self.calls = calls

    async def ainvoke(
        self, _input: dict[str, Any], config: Any = None
    ) -> dict[str, Any]:
        _ = config
        self.calls.append(self.name)
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


def test_full_pipeline_runs_roles_in_code_enforced_order(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    _install_fakes(monkeypatch, calls)
    pipeline = guarded_pipeline.build_guarded_pipeline(
        _specs(),
        data_dir=str(tmp_path),
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
        disease="breast cancer",
        skip_evidence_assessor=True,
    )

    with pytest.raises(RuntimeError, match="hypothesis gate failed"):
        asyncio.run(pipeline.ainvoke({"messages": []}))

    assert calls == ["prepare", "hypothesis_writer"]
