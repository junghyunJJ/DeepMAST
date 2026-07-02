from __future__ import annotations

import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage


def _write_required_files(data_dir: Path) -> None:
    (data_dir / "papers.json").write_text('{"papers": []}', encoding="utf-8")
    (data_dir / "part1_final.md").write_text("## Part 1\n", encoding="utf-8")
    (data_dir / "part2_final.md").write_text("## Part 2\n", encoding="utf-8")
    (data_dir / "part3_final.md").write_text("## Part 3\n", encoding="utf-8")


def test_run_report_guardrail_skips_when_parts_are_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    (tmp_path / "papers.json").write_text('{"papers": []}', encoding="utf-8")
    (tmp_path / "part1_final.md").write_text("## Part 1\n", encoding="utf-8")

    def fail_validate(_data_dir: Path) -> list[dict[str, str]]:
        raise AssertionError("validate_report must not run before all required files exist")

    monkeypatch.setattr(report_guardrails.validate_report_script, "validate_report", fail_validate)

    result = report_guardrails.run_report_guardrail(tmp_path, provider="ollama")

    assert result["status"] == "skipped"
    assert result["missing"] == ["part2_final.md", "part3_final.md"]
    assert not (tmp_path / "report_validation_initial.json").exists()
    assert not (tmp_path / "report_validation_final.json").exists()


def test_run_report_guardrail_repairs_error_issues_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    _write_required_files(tmp_path)
    calls: list[str] = []

    def fake_validate(_data_dir: Path) -> list[dict[str, str]]:
        calls.append("validate")
        if calls.count("validate") == 1:
            return [
                {
                    "severity": "error",
                    "code": "pmid_not_in_papers",
                    "file": "part1_final.md",
                    "section": "",
                    "value": "999",
                }
            ]
        return [
            {
                "severity": "warning",
                "code": "mechanistic_overclaim",
                "file": "part1_final.md",
                "section": "## Part 1",
                "value": "hypothesis",
            }
        ]

    def fake_repair(
        data_dir: Path, issues_path: Path, *, provider: str | None = None, llm=None
    ) -> int:
        calls.append("repair")
        assert data_dir == tmp_path.resolve()
        assert issues_path == tmp_path.resolve() / "report_validation_initial.json"
        assert provider == "ollama"
        assert llm is None
        return 1

    monkeypatch.setattr(report_guardrails.validate_report_script, "validate_report", fake_validate)
    monkeypatch.setattr(report_guardrails.repair_report_script, "repair_report", fake_repair)

    result = report_guardrails.run_report_guardrail(tmp_path, provider="ollama")

    assert calls == ["validate", "repair", "validate"]
    assert result == {
        "status": "passed",
        "initial_issue_count": 1,
        "initial_error_count": 1,
        "changed_sections": 1,
        "final_issue_count": 1,
        "final_error_count": 0,
    }
    initial = json.loads((tmp_path / "report_validation_initial.json").read_text(encoding="utf-8"))
    final = json.loads((tmp_path / "report_validation_final.json").read_text(encoding="utf-8"))
    assert initial["issue_count"] == 1
    assert final["issue_count"] == 1
    assert final["issues"][0]["severity"] == "warning"


def test_run_report_guardrail_records_remaining_errors_without_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    _write_required_files(tmp_path)

    def fake_validate(_data_dir: Path) -> list[dict[str, str]]:
        return [{"severity": "error", "code": "still_bad"}]

    def fake_repair(
        data_dir: Path, issues_path: Path, *, provider: str | None = None, llm=None
    ) -> int:
        return 0

    monkeypatch.setattr(report_guardrails.validate_report_script, "validate_report", fake_validate)
    monkeypatch.setattr(report_guardrails.repair_report_script, "repair_report", fake_repair)

    result = report_guardrails.run_report_guardrail(tmp_path)

    assert result["status"] == "failed"
    assert result["final_error_count"] == 1
    final = json.loads((tmp_path / "report_validation_final.json").read_text(encoding="utf-8"))
    assert final["issues"] == [{"severity": "error", "code": "still_bad"}]


def test_report_guardrail_middleware_returns_message_when_guardrail_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.deep_interpreter.middleware.report_guardrail import ReportGuardrailMiddleware

    def fake_run(data_dir: Path, *, provider: str | None = None) -> dict[str, object]:
        assert data_dir == tmp_path
        assert provider == "ollama"
        return {
            "status": "passed",
            "initial_issue_count": 1,
            "initial_error_count": 1,
            "changed_sections": 1,
            "final_issue_count": 0,
            "final_error_count": 0,
        }

    monkeypatch.setattr(
        "src.agents.deep_interpreter.middleware.report_guardrail.run_report_guardrail",
        fake_run,
    )

    result = ReportGuardrailMiddleware(data_dir=tmp_path, provider="ollama").after_agent({}, None)

    assert result is not None
    [message] = result["messages"]
    assert isinstance(message, AIMessage)
    payload = json.loads(str(message.content))
    assert payload["report_guardrail"]["status"] == "passed"
    assert payload["report_guardrail"]["changed_sections"] == 1


def test_report_guardrail_middleware_is_silent_when_guardrail_skips(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.deep_interpreter.middleware.report_guardrail import ReportGuardrailMiddleware

    def fake_run(data_dir: Path, *, provider: str | None = None) -> dict[str, object]:
        return {"status": "skipped", "missing": ["part3_final.md"]}

    monkeypatch.setattr(
        "src.agents.deep_interpreter.middleware.report_guardrail.run_report_guardrail",
        fake_run,
    )

    result = ReportGuardrailMiddleware(data_dir=tmp_path).after_agent({}, None)

    assert result is None


def test_report_guardrail_middleware_export_uses_env_data_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.deep_interpreter.middleware import ReportGuardrailMiddleware

    seen: list[Path] = []

    def fake_run(data_dir: Path, *, provider: str | None = None) -> dict[str, object]:
        seen.append(data_dir)
        return {
            "status": "passed",
            "initial_issue_count": 0,
            "initial_error_count": 0,
            "changed_sections": 0,
            "final_issue_count": 0,
            "final_error_count": 0,
        }

    monkeypatch.setenv("DEEP_INTERPRETER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        "src.agents.deep_interpreter.middleware.report_guardrail.run_report_guardrail",
        fake_run,
    )

    result = ReportGuardrailMiddleware().after_agent({}, None)

    assert result is not None
    assert seen == [tmp_path]


@pytest.mark.asyncio
async def test_report_guardrail_middleware_async_hook_uses_same_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.deep_interpreter.middleware.report_guardrail import ReportGuardrailMiddleware

    def fake_run(data_dir: Path, *, provider: str | None = None) -> dict[str, object]:
        assert data_dir == tmp_path
        return {
            "status": "failed",
            "initial_issue_count": 1,
            "initial_error_count": 1,
            "changed_sections": 0,
            "final_issue_count": 1,
            "final_error_count": 1,
        }

    monkeypatch.setattr(
        "src.agents.deep_interpreter.middleware.report_guardrail.run_report_guardrail",
        fake_run,
    )

    result = await ReportGuardrailMiddleware(data_dir=tmp_path).aafter_agent({}, None)

    assert result is not None
    payload = json.loads(str(result["messages"][0].content))
    assert payload["report_guardrail"]["status"] == "failed"
    assert payload["report_guardrail"]["final_error_count"] == 1


def test_get_subagents_attaches_report_guardrail_only_to_interpreter() -> None:
    from src.agents.deep_interpreter.middleware import ReportGuardrailMiddleware
    from src.agents.deep_interpreter.subagents.configs import get_subagents

    subagents = get_subagents(data_dir="/tmp/deepmast-report-guardrail-test")
    by_name = {subagent["name"]: subagent for subagent in subagents}

    interpreter_middleware = by_name["interpreter"]["middleware"]
    assert any(isinstance(middleware, ReportGuardrailMiddleware) for middleware in interpreter_middleware)

    for name in ("planner", "searcher", "reporter"):
        assert not any(
            isinstance(middleware, ReportGuardrailMiddleware)
            for middleware in by_name[name].get("middleware", [])
        )
