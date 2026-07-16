"""Fail-closed publication guardrail tests for agent-authored drug reports."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import AIMessage, ToolMessage

from src.agents.drug_target import report_guardrails
from src.agents.drug_target.middleware import (
    DrugReportGuardrailMiddleware,
    DrugReportRunCleanupMiddleware,
    DrugTargetManagedFilesystemGuardMiddleware,
    DrugTargetTaskAllowlistMiddleware,
)
from src.agents.drug_target.production_report_tools import (
    production_hypothesis_evidence_tool,
    production_save_drug_md_tool,
)


DRUG_MD_WITH_HYPOTHESIS = """# Drug Target Report

## 4. Mechanistic Hypothesis Recommendations

#### 4.1.1. GENE1 state tracks disease activity
**Category:** mechanistic
**Core Claim:** GENE1-associated signaling tracks disease activity.
- Genes: GENE1
- Pathways: test pathway
- Cell Types: fibroblast
- Drugs: compound A
**Falsifiable Prediction:** GENE1 perturbation changes the endpoint.
**Validation Approach:** Perturb GENE1 and measure the endpoint.
"""


def _validation(*, valid: bool, issues: list[dict] | None = None) -> dict:
    return {
        "valid": valid,
        "issue_count": len(issues or []),
        "issues": issues or [],
        "checks": {
            "data_dir": {"status": "pass"},
            "required_artifacts": {"status": "pass", "missing": []},
            "target_assessment": {"status": "pass", "issues": []},
        },
        "sources": [],
    }


def _hard(code: str = "BAD_CONTENT") -> dict[str, str]:
    return {"code": code, "severity": "critical", "message": code}


def _write_sources(data_dir: Path, markdown: str = DRUG_MD_WITH_HYPOTHESIS) -> None:
    (data_dir / "drug.md").write_text(markdown, encoding="utf-8")
    (data_dir / "target_assessment.json").write_text("{}", encoding="utf-8")


def _audit(data_dir: Path, name: str) -> dict[str, Any]:
    return json.loads((data_dir / name).read_text(encoding="utf-8"))


def _publication_paths(data_dir: Path) -> list[Path]:
    return [data_dir / name for name in report_guardrails.PUBLICATION_ARTIFACTS]


def _patch_publish(monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
    async def publish(data_dir: Path, **_kwargs: Any) -> dict[str, str]:
        calls.append("publish")
        for path in _publication_paths(data_dir):
            path.write_text("published", encoding="utf-8")
        return {"status": "published"}

    monkeypatch.setattr(report_guardrails, "_publish_report_outputs", publish)


def _request(name: str, args: dict[str, Any]) -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={"id": "call-1", "name": name, "args": args, "type": "tool_call"},
        tool=None,
        state={},
        runtime=None,  # type: ignore[arg-type]
    )


def _recording_handler(calls: list[dict[str, Any]]):
    def handler(request: ToolCallRequest) -> ToolMessage:
        calls.append(dict(request.tool_call))
        return ToolMessage(content="ok", tool_call_id=request.tool_call["id"])

    return handler


def _seed_managed(data_dir: Path) -> None:
    for name in (
        *report_guardrails.PUBLICATION_ARTIFACTS,
        *report_guardrails.GUARDRAIL_AUDIT_ARTIFACTS,
        "drug.md",
        "target_assessment.json",
    ):
        (data_dir / name).write_text(name, encoding="utf-8")


def _nonrepairable_validation(check: str) -> dict:
    result = _validation(valid=False, issues=[_hard("NONREPAIRABLE")])
    result["checks"][check] = {"status": "fail"}
    return result


def _assert_nonrepairable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, validation: dict
) -> None:
    _write_sources(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(report_guardrails, "_validate", lambda _data_dir: validation)
    monkeypatch.setattr(
        report_guardrails,
        "_repair_drug_md",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("repair called")),
    )
    _patch_publish(monkeypatch, calls)

    result = report_guardrails.run_drug_report_guardrail(tmp_path)

    assert result["status"] == "failed"
    assert result["repair_attempt_count"] == 0
    assert calls == []
    assert _audit(tmp_path, "drug_report_validation_final.json")["publication"]["status"] == "failed"


def test_nonrepairable_input_fails_without_calling_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _assert_nonrepairable(tmp_path, monkeypatch, _nonrepairable_validation("data_dir"))


def test_missing_target_assessment_fails_without_calling_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _assert_nonrepairable(tmp_path, monkeypatch, _nonrepairable_validation("target_assessment"))


def test_unreadable_required_evidence_fails_without_calling_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    validation = _validation(valid=False, issues=[_hard("UNREADABLE_EVIDENCE")])
    validation["checks"]["validate_drug_md"] = {
        "status": "fail",
        "raw": {"error": "assessment_results.json is unreadable"},
    }
    _assert_nonrepairable(tmp_path, monkeypatch, validation)


def test_malformed_required_json_fails_without_calling_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _assert_nonrepairable(tmp_path, monkeypatch, _nonrepairable_validation("required_artifacts"))


def test_guardrail_repairs_until_valid_and_writes_both_audits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_sources(tmp_path)
    calls: list[str] = []
    validations = iter([_validation(valid=False, issues=[_hard()]), _validation(valid=True)])
    monkeypatch.setattr(report_guardrails, "_validate", lambda _data_dir: next(validations))
    monkeypatch.setattr(report_guardrails, "_repair_drug_md", lambda *_args, **_kwargs: True)
    _patch_publish(monkeypatch, calls)

    result = report_guardrails.run_drug_report_guardrail(tmp_path)

    assert result["status"] == "passed"
    assert result["repair_attempt_count"] == 1
    assert result["changed_repair_count"] == 1
    assert calls == ["publish"]
    assert _audit(tmp_path, "drug_report_validation_initial.json")["issues"] == [_hard()]
    assert _audit(tmp_path, "drug_report_validation_final.json")["publication"]["status"] == "published"


def test_guardrail_stops_after_three_changed_repairs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_sources(tmp_path)
    validations = iter([_validation(valid=False, issues=[_hard()])] * 4)
    repairs: list[str] = []
    monkeypatch.setattr(report_guardrails, "_validate", lambda _data_dir: next(validations))
    monkeypatch.setattr(
        report_guardrails,
        "_repair_drug_md",
        lambda *_args, **_kwargs: repairs.append("repair") or True,
    )

    result = report_guardrails.run_drug_report_guardrail(tmp_path)

    assert result["status"] == "failed"
    assert repairs == ["repair"] * report_guardrails.MAX_DRUG_REPORT_REPAIR_PASSES
    assert result["repair_attempt_count"] == 3
    assert result["changed_repair_count"] == 3


def test_guardrail_stops_when_drug_md_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_sources(tmp_path)
    monkeypatch.setattr(
        report_guardrails, "_validate", lambda _data_dir: _validation(valid=False, issues=[_hard()])
    )
    monkeypatch.setattr(report_guardrails, "_repair_drug_md", lambda *_args, **_kwargs: False)

    result = report_guardrails.run_drug_report_guardrail(tmp_path)

    assert result["status"] == "failed"
    assert result["repair_attempt_count"] == 1
    assert result["changed_repair_count"] == 0


def test_missing_section_4_is_repaired_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_sources(tmp_path)
    seen: list[list[dict]] = []
    published: list[str] = []
    code = "AGENT_REPORT_HYPOTHESES_MISSING"
    validations = iter([_validation(valid=False, issues=[_hard(code)]), _validation(valid=True)])
    monkeypatch.setattr(report_guardrails, "_validate", lambda _data_dir: next(validations))
    monkeypatch.setattr(
        report_guardrails,
        "_repair_drug_md",
        lambda _data_dir, issues, **_kwargs: seen.append(issues) or True,
    )
    _patch_publish(monkeypatch, published)

    result = report_guardrails.run_drug_report_guardrail(tmp_path)

    assert seen == [[_hard(code)]]
    assert published == ["publish"]
    assert result["status"] == "passed"


def test_incomplete_section_4_is_repaired_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_sources(tmp_path)
    seen: list[list[dict]] = []
    validations = iter(
        [
            _validation(valid=False, issues=[_hard("AGENT_REPORT_HYPOTHESIS_INCOMPLETE")]),
            _validation(valid=True),
        ]
    )
    monkeypatch.setattr(report_guardrails, "_validate", lambda _data_dir: next(validations))
    monkeypatch.setattr(
        report_guardrails,
        "_repair_drug_md",
        lambda _data_dir, issues, **_kwargs: seen.append(issues) or True,
    )
    published: list[str] = []
    _patch_publish(monkeypatch, published)

    assert report_guardrails.run_drug_report_guardrail(tmp_path)["status"] == "passed"
    assert seen[0][0]["code"] == "AGENT_REPORT_HYPOTHESIS_INCOMPLETE"
    assert published == ["publish"]


def test_repair_prompt_json_encodes_control_characters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_sources(tmp_path)
    captured: dict[str, Any] = {}

    class FakeAgent:
        def invoke(self, payload: dict[str, Any]) -> None:
            captured["prompt"] = payload["messages"][0]["content"]

    monkeypatch.setattr(report_guardrails, "create_llm", lambda **_kwargs: object())
    monkeypatch.setattr(report_guardrails, "create_agent", lambda *_args, **_kwargs: FakeAgent())

    changed = report_guardrails._repair_drug_md(
        tmp_path,
        [_hard()],
        provider="test",
        disease="x\n## injected",
    )

    assert changed is False
    assert captured["prompt"].startswith("## REPAIR MODE\n")
    assert 'Disease: "x\\n## injected"' in captured["prompt"]


def test_repair_exception_writes_failed_final_audit_and_clears_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_sources(tmp_path)
    for path in _publication_paths(tmp_path):
        path.write_text("stale", encoding="utf-8")
    monkeypatch.setattr(
        report_guardrails, "_validate", lambda _data_dir: _validation(valid=False, issues=[_hard()])
    )
    monkeypatch.setattr(
        report_guardrails,
        "_repair_drug_md",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("no provider")),
    )

    result = report_guardrails.run_drug_report_guardrail(tmp_path)

    assert result["status"] == "failed"
    assert all(not path.exists() for path in _publication_paths(tmp_path))
    assert "no provider" in _audit(tmp_path, "drug_report_validation_final.json")["guardrail"]["repair_error"]
    assert (tmp_path / "drug.md").exists()


def test_warning_only_validation_publishes_without_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_sources(tmp_path)
    calls: list[str] = []
    warning = {"code": "WARN", "severity": "warning"}
    monkeypatch.setattr(report_guardrails, "_validate", lambda _data_dir: _validation(valid=False, issues=[warning]))
    monkeypatch.setattr(
        report_guardrails,
        "_repair_drug_md",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("repair called")),
    )
    _patch_publish(monkeypatch, calls)

    assert report_guardrails.run_drug_report_guardrail(tmp_path)["status"] == "passed"
    assert calls == ["publish"]


def test_publication_failure_removes_derived_outputs_but_keeps_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_sources(tmp_path)
    monkeypatch.setattr(report_guardrails, "_validate", lambda _data_dir: _validation(valid=True))

    async def broken_publish(*_args: Any, **_kwargs: Any) -> None:
        for path in _publication_paths(tmp_path):
            path.write_text("partial", encoding="utf-8")
        raise RuntimeError("bad html")

    monkeypatch.setattr(report_guardrails, "_publish_report_outputs", broken_publish)
    result = report_guardrails.run_drug_report_guardrail(tmp_path)

    assert result["status"] == "failed"
    assert all(not path.exists() for path in _publication_paths(tmp_path))
    assert (tmp_path / "drug.md").exists()
    assert (tmp_path / "drug_report_validation_initial.json").exists()
    assert (tmp_path / "drug_report_validation_final.json").exists()


def test_success_audit_write_failure_removes_published_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_sources(tmp_path)
    monkeypatch.setattr(report_guardrails, "_validate", lambda _data_dir: _validation(valid=True))

    async def publish(*_args: Any, **_kwargs: Any) -> dict[str, str]:
        for path in _publication_paths(tmp_path):
            path.write_text("published", encoding="utf-8")
        return {"status": "published"}

    real_write = report_guardrails._write_audit
    monkeypatch.setattr(report_guardrails, "_publish_report_outputs", publish)
    calls = 0

    def fail_final(*args: Any, **kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("disk full")
        real_write(*args, **kwargs)

    monkeypatch.setattr(report_guardrails, "_write_audit", fail_final)
    with pytest.raises(OSError, match="disk full"):
        report_guardrails.run_drug_report_guardrail(tmp_path)
    assert all(not path.exists() for path in _publication_paths(tmp_path))
    assert (tmp_path / "drug_report_validation_initial.json").exists()


def test_middleware_without_data_dir_fails_before_touching_cwd() -> None:
    middleware = DrugReportGuardrailMiddleware(None)
    with pytest.raises(RuntimeError, match="data_dir"):
        middleware.before_agent({}, None)
    with pytest.raises(RuntimeError, match="data_dir"):
        middleware.after_agent({}, None)


def test_cleanup_rejects_root_and_repository_directory_without_unlinking(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    touched: list[Path] = []
    monkeypatch.setattr(Path, "unlink", lambda self, *args, **kwargs: touched.append(self))

    for unsafe in (Path("/"), repo):
        with pytest.raises(ValueError, match="run directory"):
            report_guardrails.clear_derived_report_artifacts(unsafe)
    assert touched == []


def test_cleanup_preserves_legacy_hypothesis_and_report_data_files(tmp_path: Path) -> None:
    _seed_managed(tmp_path)
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    for name in ("hypothesis_report.json", "report_data.json"):
        (evidence / name).write_text("legacy", encoding="utf-8")
    (tmp_path / "report_data.json").write_text("legacy", encoding="utf-8")

    report_guardrails.clear_derived_report_artifacts(tmp_path)

    assert (evidence / "hypothesis_report.json").exists()
    assert (evidence / "report_data.json").exists()
    assert (tmp_path / "report_data.json").exists()
    assert (tmp_path / "drug.md").exists()
    assert all(not path.exists() for path in _publication_paths(tmp_path))
    assert all((tmp_path / name).exists() for name in report_guardrails.GUARDRAIL_AUDIT_ARTIFACTS)


def test_middleware_before_hooks_clear_stale_publication_outputs(tmp_path: Path) -> None:
    _seed_managed(tmp_path)
    middleware = DrugReportGuardrailMiddleware(tmp_path)
    assert middleware.before_agent({}, None) is None
    assert all(not path.exists() for path in _publication_paths(tmp_path))
    assert not (tmp_path / "drug.md").exists()


@pytest.mark.asyncio
async def test_middleware_before_hooks_clear_stale_source_outputs(tmp_path: Path) -> None:
    _seed_managed(tmp_path)
    await DrugReportGuardrailMiddleware(tmp_path).abefore_agent({}, None)
    assert not (tmp_path / "drug.md").exists()
    assert not (tmp_path / "target_assessment.json").exists()
    assert not (tmp_path / "drug_report_validation_initial.json").exists()


def test_noop_writer_cannot_republish_stale_source_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_managed(tmp_path)
    middleware = DrugReportGuardrailMiddleware(tmp_path)
    middleware.before_agent({}, None)
    monkeypatch.setattr(report_guardrails, "_validate", lambda _data_dir: _validation(valid=False, issues=[_hard()]))
    with pytest.raises(RuntimeError):
        middleware.after_agent({}, None)
    assert all(not path.exists() for path in _publication_paths(tmp_path))


@pytest.mark.asyncio
async def test_run_cleanup_middleware_clears_sources_audits_and_publication_outputs(
    tmp_path: Path,
) -> None:
    _seed_managed(tmp_path)
    middleware = DrugReportRunCleanupMiddleware(tmp_path)
    await middleware.abefore_agent({}, None)
    assert all(not (tmp_path / name).exists() for name in (
        *report_guardrails.PUBLICATION_ARTIFACTS,
        *report_guardrails.GUARDRAIL_AUDIT_ARTIFACTS,
        "drug.md",
        "target_assessment.json",
    ))


def test_production_hypothesis_loader_forces_scope_when_caller_requests_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.agents.drug_target import production_report_tools

    other = tmp_path / "other"
    other.mkdir()
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        production_report_tools,
        "load_evidence_files",
        lambda **kwargs: calls.append(kwargs) or "ok",
    )

    result = production_hypothesis_evidence_tool(tmp_path).invoke(
        {"data_dir": str(other), "scope": "all"}
    )

    assert result == "ok"
    assert calls == [{"data_dir": str(tmp_path.resolve()), "scope": "hypothesis"}]


def test_repair_agent_tools_cannot_switch_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.agents.drug_target import production_report_tools

    other = tmp_path / "other"
    other.mkdir()
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        production_report_tools,
        "save_drug_md",
        lambda **kwargs: calls.append(kwargs) or "ok",
    )

    result = production_save_drug_md_tool(tmp_path).invoke(
        {"data_dir": str(other), "content": "# repaired", "strip_unexpanded_markers": True}
    )

    assert result == "ok"
    assert calls == [
        {
            "data_dir": str(tmp_path.resolve()),
            "content": "# repaired",
            "strip_unexpanded_markers": False,
        }
    ]


def test_managed_filesystem_guard_blocks_content_read_write_and_execute_sync(tmp_path: Path) -> None:
    middleware = DrugTargetManagedFilesystemGuardMiddleware(tmp_path, data_dir_tool_names=set())
    calls: list[dict[str, Any]] = []
    for tool_name in ("read_file", "grep", "write_file", "edit_file", "execute"):
        result = middleware.wrap_tool_call(_request(tool_name, {}), _recording_handler(calls))
        assert isinstance(result, ToolMessage)
        assert "blocked" in str(result.content).lower()
    assert calls == []


@pytest.mark.asyncio
async def test_managed_filesystem_guard_blocks_content_read_write_and_execute_async(
    tmp_path: Path,
) -> None:
    middleware = DrugTargetManagedFilesystemGuardMiddleware(tmp_path, data_dir_tool_names=set())
    calls: list[dict[str, Any]] = []

    async def handler(request: ToolCallRequest) -> ToolMessage:
        calls.append(dict(request.tool_call))
        return ToolMessage(content="ok", tool_call_id=request.tool_call["id"])

    for tool_name in ("read_file", "grep", "write_file", "edit_file", "execute"):
        result = await middleware.awrap_tool_call(_request(tool_name, {}), handler)
        assert isinstance(result, ToolMessage)
    assert calls == []


def test_managed_filesystem_guard_forces_configured_directory_sync(tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    middleware = DrugTargetManagedFilesystemGuardMiddleware(
        tmp_path, data_dir_tool_names={"load_evidence_files"}
    )
    calls: list[dict[str, Any]] = []
    middleware.wrap_tool_call(
        _request("load_evidence_files", {"data_dir": str(other), "scope": "all"}),
        _recording_handler(calls),
    )
    assert calls[0]["args"]["data_dir"] == str(tmp_path.resolve())


@pytest.mark.asyncio
async def test_managed_filesystem_guard_forces_configured_directory_async(tmp_path: Path) -> None:
    middleware = DrugTargetManagedFilesystemGuardMiddleware(
        tmp_path, data_dir_tool_names={"save_drug_md"}
    )
    calls: list[dict[str, Any]] = []

    async def handler(request: ToolCallRequest) -> ToolMessage:
        calls.append(dict(request.tool_call))
        return ToolMessage(content="ok", tool_call_id=request.tool_call["id"])

    await middleware.awrap_tool_call(_request("save_drug_md", {"content": "x"}), handler)
    assert calls[0]["args"]["data_dir"] == str(tmp_path.resolve())


def test_managed_filesystem_guard_allows_discovery_and_domain_tools(tmp_path: Path) -> None:
    middleware = DrugTargetManagedFilesystemGuardMiddleware(
        tmp_path, data_dir_tool_names={"load_evidence_files"}
    )
    calls: list[dict[str, Any]] = []
    for request in (
        _request("ls", {"path": "."}),
        _request("glob", {"pattern": "*.json"}),
        _request("load_evidence_files", {}),
    ):
        assert isinstance(middleware.wrap_tool_call(request, _recording_handler(calls)), ToolMessage)
    assert [call["name"] for call in calls] == ["ls", "glob", "load_evidence_files"]


def test_task_allowlist_rejects_general_purpose_without_dispatch_sync() -> None:
    middleware = DrugTargetTaskAllowlistMiddleware({"evidence_assessor", "report_writer"})
    calls: list[dict[str, Any]] = []
    result = middleware.wrap_tool_call(
        _request("task", {"subagent_type": "general-purpose"}), _recording_handler(calls)
    )
    assert isinstance(result, ToolMessage)
    assert calls == []


@pytest.mark.asyncio
async def test_task_allowlist_rejects_general_purpose_without_dispatch_async() -> None:
    middleware = DrugTargetTaskAllowlistMiddleware({"evidence_assessor", "report_writer"})
    calls: list[dict[str, Any]] = []

    async def handler(request: ToolCallRequest) -> ToolMessage:
        calls.append(dict(request.tool_call))
        return ToolMessage(content="ok", tool_call_id=request.tool_call["id"])

    result = await middleware.awrap_tool_call(
        _request("task", {"subagent_type": "general-purpose"}), handler
    )
    assert isinstance(result, ToolMessage)
    assert calls == []


def test_task_allowlist_allows_only_evidence_assessor_and_report_writer() -> None:
    middleware = DrugTargetTaskAllowlistMiddleware({"evidence_assessor", "report_writer"})
    calls: list[dict[str, Any]] = []
    for name in ("evidence_assessor", "report_writer"):
        middleware.wrap_tool_call(_request("task", {"subagent_type": name}), _recording_handler(calls))
    middleware.wrap_tool_call(_request("task", {"subagent_type": "other"}), _recording_handler(calls))
    assert [call["args"]["subagent_type"] for call in calls] == ["evidence_assessor", "report_writer"]


def test_middleware_after_hooks_return_metadata_on_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.agents.drug_target.middleware.run_drug_report_guardrail",
        lambda *_args, **_kwargs: {"status": "passed", "final_error_count": 0},
    )
    result = DrugReportGuardrailMiddleware(tmp_path).after_agent({}, None)
    [message] = result["messages"]
    assert isinstance(message, AIMessage)
    assert json.loads(str(message.content))["drug_report_guardrail"]["status"] == "passed"


@pytest.mark.asyncio
async def test_middleware_after_hooks_raise_on_validation_or_publication_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.agents.drug_target.middleware.run_drug_report_guardrail",
        lambda *_args, **_kwargs: {"status": "failed", "final_error_count": 1, "publication_error": "bad html"},
    )
    with pytest.raises(RuntimeError, match="drug_report_validation_final"):
        await DrugReportGuardrailMiddleware(tmp_path).aafter_agent({}, None)


def _publisher_report_data() -> dict[str, Any]:
    return {
        "schema_version": "drug_target.report_data.v1",
        "valid": True,
        "issues": [],
        "sections": {"ok": {}},
        "candidates": [{"gene": "GENE1", "stage3_candidate": True}],
        "hypotheses": [],
    }


def _patch_publisher_happy_path(monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any]) -> None:
    def build_report(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        captured["payload"] = kwargs["hypothesis_data"]
        return _publisher_report_data()

    monkeypatch.setattr(report_guardrails, "build_report_data", build_report)
    monkeypatch.setattr(report_guardrails, "validate_report_data", lambda _report: [])
    monkeypatch.setattr(
        report_guardrails,
        "build_part4_therapeutic_synthesis",
        lambda *_args, **kwargs: {
            "schema_version": report_guardrails.PART4_SYNTHESIS_SCHEMA_VERSION,
            "featured_candidates": [{"gene": "GENE1"}],
        },
    )
    monkeypatch.setattr(report_guardrails, "part4_candidate_selector_provider_from_config", lambda _config: None)

    async def selection(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {
            "schema_version": report_guardrails.PART4_CANDIDATE_SELECTION_SCHEMA_VERSION,
            "selected_genes": ["GENE1"],
        }

    monkeypatch.setattr(report_guardrails, "generate_part4_candidate_selection", selection)
    monkeypatch.setattr(report_guardrails, "render_part4_therapeutic_synthesis_markdown", lambda _value: "# Part 4\n")
    monkeypatch.setattr(report_guardrails, "build_drug_html_context", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(report_guardrails, "render_drug_html", lambda _value: "<html>ok</html>")


def test_publication_uses_markdown_derived_hypotheses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "drug.md").write_text(DRUG_MD_WITH_HYPOTHESIS, encoding="utf-8")
    captured: dict[str, Any] = {}
    _patch_publisher_happy_path(monkeypatch, captured)

    asyncio.run(report_guardrails._publish_report_outputs(tmp_path, disease="test"))

    assert captured["payload"] == {
        "hypotheses": [
            {
                "rank": 1,
                "title": "GENE1 state tracks disease activity",
                "category": "mechanistic",
                "core_claim": "GENE1-associated signaling tracks disease activity.",
                "biological_entities": {
                    "genes": ["GENE1"],
                    "pathways": ["test pathway"],
                    "cell_types": ["fibroblast"],
                    "drugs": ["compound A"],
                },
                "falsifiable_prediction": "GENE1 perturbation changes the endpoint.",
                "validation_approach": "Perturb GENE1 and measure the endpoint.",
                "evidence_references": ["drug.md"],
            }
        ]
    }
    assert not (tmp_path / "report_data.json").exists()
    assert not (tmp_path / "evidence" / "hypothesis_report.json").exists()


@pytest.mark.parametrize(
    "markdown",
    [
        "# Drug Target Report\n\n## 4. Mechanistic Hypothesis Recommendations\n",
        *[
            DRUG_MD_WITH_HYPOTHESIS.replace(required_line, "")
            for required_line in (
                "#### 4.1.1. GENE1 state tracks disease activity\n",
                "**Category:** mechanistic\n",
                "**Core Claim:** GENE1-associated signaling tracks disease activity.\n",
                "- Genes: GENE1\n",
                "**Falsifiable Prediction:** GENE1 perturbation changes the endpoint.\n",
                "**Validation Approach:** Perturb GENE1 and measure the endpoint.\n",
            )
        ],
    ],
)
def test_publication_rejects_unparseable_or_incomplete_section_4_before_part4(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, markdown: str
) -> None:
    (tmp_path / "drug.md").write_text(markdown, encoding="utf-8")
    monkeypatch.setattr(
        report_guardrails,
        "build_report_data",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Part 4 started")),
    )
    with pytest.raises(ValueError):
        asyncio.run(report_guardrails._publish_report_outputs(tmp_path, disease="test"))
    assert all(not path.exists() for path in _publication_paths(tmp_path))


@pytest.mark.parametrize(
    "failure",
    ["candidate", "synthesis", "markdown", "html_blank", "html_nonhtml"],
)
def test_publication_failure_leaves_all_outputs_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    (tmp_path / "drug.md").write_text(DRUG_MD_WITH_HYPOTHESIS, encoding="utf-8")
    captured: dict[str, Any] = {}
    _patch_publisher_happy_path(monkeypatch, captured)
    if failure == "candidate":
        async def bad_selection(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            return {"schema_version": "wrong", "selected_genes": "GENE1"}
        monkeypatch.setattr(report_guardrails, "generate_part4_candidate_selection", bad_selection)
    elif failure == "synthesis":
        monkeypatch.setattr(
            report_guardrails,
            "build_part4_therapeutic_synthesis",
            lambda *_args, **_kwargs: {"schema_version": "wrong", "featured_candidates": []},
        )
    elif failure == "markdown":
        monkeypatch.setattr(report_guardrails, "render_part4_therapeutic_synthesis_markdown", lambda _value: "")
    elif failure == "html_blank":
        monkeypatch.setattr(report_guardrails, "render_drug_html", lambda _value: "")
    else:
        monkeypatch.setattr(report_guardrails, "render_drug_html", lambda _value: "not html")

    with pytest.raises(ValueError):
        asyncio.run(report_guardrails._publish_report_outputs(tmp_path, disease="test"))
    assert all(not path.exists() for path in _publication_paths(tmp_path))
