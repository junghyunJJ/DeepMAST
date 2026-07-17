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
from src.agents.drug_target.hybrid_report_sections import REPORT_SECTIONS_FILENAME
from src.agents.drug_target.middleware import (
    DrugReportGuardrailMiddleware,
    DrugReportRunCleanupMiddleware,
    DrugTargetManagedFilesystemGuardMiddleware,
    DrugTargetTaskAllowlistMiddleware,
    HypothesisReportGuardrailMiddleware,
    clear_guarded_report_run_artifacts,
)
from src.agents.drug_target.production_report_tools import (
    production_assessment_evidence_tool,
    production_assessment_save_evidence_tool,
    production_hypothesis_evidence_tool,
    production_save_drug_md_tool,
    production_save_target_assessment_tool,
    production_skill_reader_tool,
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


def test_hypothesis_guardrail_removes_stale_handoff_before_agent(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "hypothesis_report.json").write_text("{}", encoding="utf-8")
    (evidence / "hypothesis_report_last_rejection.json").write_text(
        "{}", encoding="utf-8"
    )

    HypothesisReportGuardrailMiddleware(tmp_path).before_agent({}, None)

    assert not (evidence / "hypothesis_report.json").exists()
    assert not (evidence / "hypothesis_report_last_rejection.json").exists()


def test_hypothesis_guardrail_rejects_missing_handoff(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="Hypothesis report guardrail failed"):
        HypothesisReportGuardrailMiddleware(tmp_path).after_agent({}, None)


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


def _write_report_sections(data_dir: Path, payload: dict[str, Any] | None = None) -> None:
    (data_dir / REPORT_SECTIONS_FILENAME).write_text(
        json.dumps(payload or {"hypothesis_report": {}}),
        encoding="utf-8",
    )


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
    assert result["publication_status"] == "skipped"
    assert result["repair_attempt_count"] == 0
    assert calls == []
    assert _audit(tmp_path, "drug_report_validation_final.json")["publication"] == {
        "status": "skipped",
        "artifacts": [],
        "error": None,
    }


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
    assert result["publication_status"] == "passed"
    assert result["repair_attempt_count"] == 1
    assert result["changed_repair_count"] == 1
    assert calls == ["publish"]
    initial = _audit(tmp_path, "drug_report_validation_initial.json")
    final = _audit(tmp_path, "drug_report_validation_final.json")
    assert initial["issues"] == [_hard()]
    assert initial["publication"] == {
        "status": "pending",
        "artifacts": [],
        "error": None,
    }
    assert final["publication"] == {
        "status": "passed",
        "artifacts": list(report_guardrails.PUBLICATION_ARTIFACTS),
        "error": None,
    }


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
    assert result["publication_status"] == "skipped"
    assert _audit(tmp_path, "drug_report_validation_final.json")["publication"] == {
        "status": "skipped",
        "artifacts": [],
        "error": None,
    }


def test_hybrid_guardrail_repairs_sections_not_markdown_and_records_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_sources(tmp_path)
    _write_report_sections(tmp_path)
    calls: list[str] = []
    validations = iter([_validation(valid=False, issues=[_hard()]), _validation(valid=True)])
    monkeypatch.setattr(report_guardrails, "_validate", lambda _data_dir: next(validations))
    monkeypatch.setattr(
        report_guardrails,
        "_repair_report_sections",
        lambda *_args, **_kwargs: calls.append("sections") or True,
        raising=False,
    )
    monkeypatch.setattr(
        report_guardrails,
        "_repair_drug_md",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("direct repair called")),
    )
    _patch_publish(monkeypatch, calls)

    assert report_guardrails.run_drug_report_guardrail(tmp_path)["status"] == "passed"
    assert calls == ["sections", "publish"]
    assert {
        "path": REPORT_SECTIONS_FILENAME,
        "sha256": report_guardrails._sha256(tmp_path / REPORT_SECTIONS_FILENAME),
    } in _audit(tmp_path, "drug_report_validation_final.json")["sources"]


def test_hybrid_guardrail_stops_after_three_invalid_sections_repairs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_sources(tmp_path)
    _write_report_sections(tmp_path)
    validations = iter([_validation(valid=False, issues=[_hard()])] * 4)
    repairs: list[str] = []
    monkeypatch.setattr(report_guardrails, "_validate", lambda _data_dir: next(validations))
    monkeypatch.setattr(
        report_guardrails,
        "_repair_report_sections",
        lambda *_args, **_kwargs: repairs.append("sections") or True,
        raising=False,
    )
    monkeypatch.setattr(
        report_guardrails,
        "_repair_drug_md",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("direct repair called")),
    )
    monkeypatch.setattr(
        report_guardrails,
        "_publish_report_outputs",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("publish called")),
    )

    result = report_guardrails.run_drug_report_guardrail(tmp_path)

    assert result["status"] == "failed"
    assert repairs == ["sections"] * report_guardrails.MAX_DRUG_REPORT_REPAIR_PASSES
    assert all(not path.exists() for path in _publication_paths(tmp_path))
    final = _audit(tmp_path, "drug_report_validation_final.json")
    assert final["issues"] == [_hard()]
    assert final["publication"] == {"status": "skipped", "artifacts": [], "error": None}


def test_legacy_guardrail_keeps_direct_markdown_repair_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_sources(tmp_path)
    calls: list[str] = []
    validations = iter([_validation(valid=False, issues=[_hard()]), _validation(valid=True)])
    monkeypatch.setattr(report_guardrails, "_validate", lambda _data_dir: next(validations))
    monkeypatch.setattr(
        report_guardrails,
        "_repair_report_sections",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("sections repair called")),
        raising=False,
    )
    monkeypatch.setattr(
        report_guardrails,
        "_repair_drug_md",
        lambda *_args, **_kwargs: calls.append("markdown") or True,
    )
    _patch_publish(monkeypatch, calls)

    assert report_guardrails.run_drug_report_guardrail(tmp_path)["status"] == "passed"
    assert calls == ["markdown", "publish"]


@pytest.mark.parametrize("sections_contents", [None, ""], ids=["missing", "empty"])
def test_guarded_middleware_fails_closed_without_nonempty_report_sections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sections_contents: str | None
) -> None:
    _write_sources(tmp_path)
    if sections_contents is not None:
        (tmp_path / REPORT_SECTIONS_FILENAME).write_text(sections_contents, encoding="utf-8")
    calls: list[str] = []
    monkeypatch.setattr(
        report_guardrails,
        "_validate",
        lambda _data_dir: _validation(valid=True),
    )
    monkeypatch.setattr(
        report_guardrails,
        "_repair_drug_md",
        lambda *_args, **_kwargs: calls.append("markdown") or True,
    )
    _patch_publish(monkeypatch, calls)

    with pytest.raises(RuntimeError, match="drug_report_validation_final"):
        DrugReportGuardrailMiddleware(tmp_path).after_agent({}, None)

    assert calls == []
    final = _audit(tmp_path, "drug_report_validation_final.json")
    assert final["valid"] is False
    assert final["guardrail"]["status"] == "failed"
    assert final["issues"] == [
        {
            "code": "REPORT_SECTIONS_REQUIRED",
            "severity": "critical",
            "message": "guarded report publication requires nonempty report_sections.json",
        }
    ]
    assert final["publication"] == {"status": "skipped", "artifacts": [], "error": None}
    assert not (tmp_path / "drug.md").exists()
    assert not (tmp_path / "target_assessment.json").exists()
    assert all(not path.exists() for path in _publication_paths(tmp_path))


def test_guardrail_stops_when_repair_revalidation_becomes_nonrepairable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_sources(tmp_path)
    repairs: list[str] = []
    initial = _validation(valid=False, issues=[_hard("REPAIRABLE_CONTENT")])
    post_repair = _validation(valid=False, issues=[_hard("MISSING_REQUIRED_ARTIFACT")])
    post_repair["checks"]["required_artifacts"] = {
        "status": "fail",
        "missing": ["evidence/assessment_results.json"],
    }
    validations = iter([initial, post_repair])
    monkeypatch.setattr(report_guardrails, "_validate", lambda _data_dir: next(validations))
    monkeypatch.setattr(
        report_guardrails,
        "_repair_drug_md",
        lambda *_args, **_kwargs: repairs.append("repair") or True,
    )
    monkeypatch.setattr(
        report_guardrails,
        "_publish_report_outputs",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("publish called")),
    )

    result = report_guardrails.run_drug_report_guardrail(tmp_path)

    assert result["status"] == "failed"
    assert result["repair_attempt_count"] == 1
    assert repairs == ["repair"]
    final = _audit(tmp_path, "drug_report_validation_final.json")
    assert final["checks"]["required_artifacts"]["status"] == "fail"
    assert final["publication"] == {"status": "skipped", "artifacts": [], "error": None}


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
    assert result["publication_status"] == "skipped"
    assert _audit(tmp_path, "drug_report_validation_final.json")["publication"] == {
        "status": "skipped",
        "artifacts": [],
        "error": None,
    }


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


def test_direct_repair_agent_keeps_legacy_prompt_and_tool_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.drug_target.subagents.prompts import DIRECT_MARKDOWN_REPAIR_PROMPT

    _write_sources(tmp_path)
    captured: dict[str, Any] = {}

    class FakeAgent:
        def invoke(self, _payload: dict[str, Any]) -> None:
            return None

    monkeypatch.setattr(report_guardrails, "create_llm", lambda **_kwargs: object())
    monkeypatch.setattr(
        report_guardrails,
        "create_agent",
        lambda **kwargs: captured.update(kwargs) or FakeAgent(),
    )

    assert report_guardrails._repair_drug_md(
        tmp_path,
        [_hard()],
        provider="test",
        disease="IPF",
    ) is False
    assert captured["system_prompt"] == DIRECT_MARKDOWN_REPAIR_PROMPT
    assert [tool.name for tool in captured["tools"]] == [
        "load_evidence_files",
        "save_drug_md",
    ]
    assert "save_drug_md" in DIRECT_MARKDOWN_REPAIR_PROMPT
    assert "save_report_sections" not in DIRECT_MARKDOWN_REPAIR_PROMPT


def test_hybrid_repair_agent_uses_bounded_sections_payload_and_safe_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.drug_target.subagents.prompts import REPORT_WRITER_PROMPT

    _write_sources(tmp_path)
    _write_report_sections(tmp_path)
    captured: dict[str, Any] = {}

    class FakeAgent:
        def invoke(self, payload: dict[str, Any]) -> None:
            captured["prompt"] = payload["messages"][0]["content"]

    monkeypatch.setattr(report_guardrails, "create_llm", lambda **_kwargs: object())
    monkeypatch.setattr(
        report_guardrails,
        "create_agent",
        lambda **kwargs: captured.update(kwargs) or FakeAgent(),
    )
    findings = [_hard(f"ISSUE_{index}") for index in range(25)]

    assert report_guardrails._repair_report_sections(
        tmp_path,
        findings,
        provider="test",
        disease="IPF",
    ) is False
    assert captured["system_prompt"] == REPORT_WRITER_PROMPT
    assert [tool.name for tool in captured["tools"]] == [
        "load_evidence_files",
        "save_report_sections",
    ]
    assert "Current report_sections.json SHA-256:" in captured["prompt"]
    assert "ISSUE_19" in captured["prompt"]
    assert "ISSUE_20" not in captured["prompt"]


@pytest.mark.parametrize("repair_name", ["_repair_drug_md", "_repair_report_sections"])
def test_repairs_construct_llm_with_selected_model_and_request_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    repair_name: str,
) -> None:
    _write_sources(tmp_path)
    if repair_name == "_repair_report_sections":
        _write_report_sections(tmp_path)
    captured: dict[str, Any] = {}

    class FakeAgent:
        def invoke(self, _payload: dict[str, Any]) -> None:
            return None

    monkeypatch.setattr(
        report_guardrails,
        "create_llm",
        lambda **kwargs: captured.setdefault("llm_kwargs", kwargs) and object(),
    )
    monkeypatch.setattr(report_guardrails, "create_agent", lambda **_kwargs: FakeAgent())

    repair = getattr(report_guardrails, repair_name)
    assert repair(
        tmp_path,
        [_hard()],
        provider="ollama-openai",
        model="qwen3.5:122b",
        request_timeout_seconds=45.0,
        disease="IPF",
    ) is False

    assert captured["llm_kwargs"] == {
        "provider": "ollama-openai",
        "model": "qwen3.5:122b",
        "request_timeout": 45.0,
    }


def test_repair_omits_unset_model_and_request_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_sources(tmp_path)
    captured: dict[str, Any] = {}

    class FakeAgent:
        def invoke(self, _payload: dict[str, Any]) -> None:
            return None

    monkeypatch.setattr(
        report_guardrails,
        "create_llm",
        lambda **kwargs: captured.setdefault("llm_kwargs", kwargs) and object(),
    )
    monkeypatch.setattr(report_guardrails, "create_agent", lambda **_kwargs: FakeAgent())

    assert report_guardrails._repair_drug_md(
        tmp_path, [_hard()], provider="ollama-openai", disease="IPF"
    ) is False
    assert captured["llm_kwargs"] == {"provider": "ollama-openai"}


def test_repair_exception_writes_skipped_final_audit_and_clears_outputs(
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
    assert result["publication_status"] == "skipped"
    assert all(not path.exists() for path in _publication_paths(tmp_path))
    final = _audit(tmp_path, "drug_report_validation_final.json")
    assert "no provider" in final["guardrail"]["repair_error"]
    assert final["publication"] == {"status": "skipped", "artifacts": [], "error": None}
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
    assert result["publication_status"] == "failed"
    assert all(not path.exists() for path in _publication_paths(tmp_path))
    assert (tmp_path / "drug.md").exists()
    assert (tmp_path / "drug_report_validation_initial.json").exists()
    assert (tmp_path / "drug_report_validation_final.json").exists()
    assert _audit(tmp_path, "drug_report_validation_final.json")["publication"] == {
        "status": "failed",
        "artifacts": [],
        "error": "RuntimeError: bad html",
    }


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
            (tmp_path / "drug_report_validation_final.json.tmp").write_text(
                "partial audit", encoding="utf-8"
            )
            raise OSError("disk full")
        real_write(*args, **kwargs)

    monkeypatch.setattr(report_guardrails, "_write_audit", fail_final)
    with pytest.raises(OSError, match="disk full"):
        report_guardrails.run_drug_report_guardrail(tmp_path)
    assert all(not path.exists() for path in _publication_paths(tmp_path))
    assert (tmp_path / "drug_report_validation_initial.json").exists()
    assert not (tmp_path / "drug_report_validation_final.json.tmp").exists()


def test_final_audit_temp_unlink_failure_still_rolls_back_publication(
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
    final_tmp = tmp_path / "drug_report_validation_final.json.tmp"

    def fail_final(*args: Any, **kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            final_tmp.write_text("partial audit", encoding="utf-8")
            raise OSError("disk full")
        real_write(*args, **kwargs)

    original_unlink = Path.unlink

    def fail_only_final_tmp_unlink(self: Path, *args: Any, **kwargs: Any) -> None:
        if self == final_tmp:
            raise OSError("temp cleanup blocked")
        original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(report_guardrails, "_write_audit", fail_final)
    monkeypatch.setattr(Path, "unlink", fail_only_final_tmp_unlink)

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


def test_top_level_cleanup_before_agent_removes_guarded_stale_artifacts_but_keeps_legacy_sidecars(
    tmp_path: Path,
) -> None:
    _seed_managed(tmp_path)
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    for name in ("hypothesis_report.json", "report_data.json"):
        (evidence / name).write_text("legacy", encoding="utf-8")
    (tmp_path / "report_data.json").write_text("legacy", encoding="utf-8")

    assert DrugReportRunCleanupMiddleware(tmp_path).before_agent({}, None) is None

    assert not (tmp_path / "drug.md").exists()
    assert not (tmp_path / "target_assessment.json").exists()
    assert all(not path.exists() for path in _publication_paths(tmp_path))
    assert (evidence / "hypothesis_report.json").read_text(encoding="utf-8") == "legacy"
    assert (evidence / "report_data.json").read_text(encoding="utf-8") == "legacy"
    assert not (tmp_path / "report_data.json").exists()


def test_public_guarded_run_cleanup_removes_hybrid_temporary_and_staging_outputs(
    tmp_path: Path,
) -> None:
    _seed_managed(tmp_path)
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "keep.json").write_text("evidence", encoding="utf-8")
    for name in (REPORT_SECTIONS_FILENAME, "report_data.json", "drug_report_render.json"):
        path = tmp_path / name
        path.write_text("stale", encoding="utf-8")
        path.with_suffix(f"{path.suffix}.tmp").write_text("temporary", encoding="utf-8")
    staging = tmp_path / ".report-sections-stale"
    staging.mkdir()
    (staging / "partial.json").write_text("stale", encoding="utf-8")

    clear_guarded_report_run_artifacts(tmp_path)

    assert (evidence / "keep.json").read_text(encoding="utf-8") == "evidence"
    for name in (
        *report_guardrails.PUBLICATION_ARTIFACTS,
        *report_guardrails.GUARDRAIL_AUDIT_ARTIFACTS,
        "drug.md",
        "target_assessment.json",
        REPORT_SECTIONS_FILENAME,
        "report_data.json",
        "drug_report_render.json",
    ):
        path = tmp_path / name
        assert not path.exists()
        assert not path.with_suffix(f"{path.suffix}.tmp").exists()
    assert not staging.exists()


def test_top_level_cleanup_removes_stale_hybrid_artifacts_but_post_writer_guardrail_keeps_new_sections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_managed(tmp_path)
    _write_report_sections(tmp_path, {"stale": True})
    for name in ("report_data.json", "drug_report_render.json"):
        (tmp_path / name).write_text("stale", encoding="utf-8")
    for name in (REPORT_SECTIONS_FILENAME, "report_data.json", "drug_report_render.json"):
        path = tmp_path / name
        path.with_suffix(f"{path.suffix}.tmp").write_text("temporary", encoding="utf-8")
    staging = tmp_path / ".report-sections-stale"
    staging.mkdir()
    (staging / "drug.md").write_text("stale", encoding="utf-8")

    assert DrugReportRunCleanupMiddleware(tmp_path).before_agent({}, None) is None

    for name in (REPORT_SECTIONS_FILENAME, "report_data.json", "drug_report_render.json"):
        path = tmp_path / name
        assert not path.exists()
        assert not path.with_suffix(f"{path.suffix}.tmp").exists()
    assert not staging.exists()

    fresh = {"hypothesis_report": {"fresh": True}}
    _write_report_sections(tmp_path, fresh)
    validations = iter([_validation(valid=False, issues=[_hard()]), _validation(valid=True)])
    repairs: list[str] = []
    monkeypatch.setattr(report_guardrails, "_validate", lambda _data_dir: next(validations))

    def repair_sections(data_dir: Path, *_args: Any, **_kwargs: Any) -> bool:
        assert json.loads((data_dir / REPORT_SECTIONS_FILENAME).read_text()) == fresh
        repairs.append("sections")
        return True

    monkeypatch.setattr(report_guardrails, "_repair_report_sections", repair_sections)
    monkeypatch.setattr(
        report_guardrails,
        "_repair_drug_md",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("direct repair called")),
    )
    published: list[str] = []
    _patch_publish(monkeypatch, published)

    DrugReportGuardrailMiddleware(tmp_path).after_agent({}, None)

    assert repairs == ["sections"]
    assert published == ["publish"]
    assert json.loads((tmp_path / REPORT_SECTIONS_FILENAME).read_text()) == fresh


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


def test_production_wrappers_force_run_directory_and_fixed_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Caller values cannot change a guarded wrapper's run directory or options."""
    from src.agents.drug_target import production_report_tools

    other = tmp_path / "other"
    other.mkdir()
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        production_report_tools,
        "load_evidence_files",
        lambda **kwargs: calls.append(("evidence", kwargs)) or "evidence",
    )
    monkeypatch.setattr(
        production_report_tools,
        "save_evidence",
        lambda **kwargs: calls.append(("save_evidence", kwargs)) or "saved",
    )
    monkeypatch.setattr(
        production_report_tools,
        "save_target_assessment",
        lambda **kwargs: calls.append(("assessment", kwargs)) or "assessment",
    )

    assert production_assessment_evidence_tool(tmp_path).invoke(
        {"data_dir": str(other), "scope": "hypothesis"}
    ) == "evidence"
    assert production_assessment_save_evidence_tool(tmp_path).invoke(
        {"data_dir": str(other), "filename": "stage2_note.json", "data": {"ok": True}}
    ) == "saved"
    assert production_save_target_assessment_tool(tmp_path).invoke(
        {
            "data_dir": str(other),
            "project_meta": {"id": "x"},
            "druggability_matrix": [],
            "featured_candidates_deep_dive": [],
        }
    ) == "assessment"

    safe = str(tmp_path.resolve())
    assert calls == [
        ("evidence", {"data_dir": safe, "scope": "assessment"}),
        (
            "save_evidence",
            {"data_dir": safe, "filename": "stage2_note.json", "data": {"ok": True}},
        ),
        (
            "assessment",
            {
                "data_dir": safe,
                "project_meta": {"id": "x"},
                "druggability_matrix": [],
                "featured_candidates_deep_dive": [],
            },
        ),
    ]


@pytest.mark.parametrize(
    "filename",
    [
        "hypothesis_report.json",
        "hypothesis_report.summarizer_sanitized.json",
        "hypothesis_report_last_rejection.json",
        "hypothesis_report_draft.json",
        "report_data.json",
    ],
)
def test_assessment_save_evidence_rejects_reserved_prior_report_outputs_without_raw_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, filename: str
) -> None:
    from src.agents.drug_target import production_report_tools

    raw_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        production_report_tools,
        "save_evidence",
        lambda **kwargs: raw_calls.append(kwargs) or "unexpected",
    )

    result = production_assessment_save_evidence_tool(tmp_path).invoke(
        {"filename": filename, "data": {"legacy": True}}
    )

    assert json.loads(result)["saved"] is False
    assert raw_calls == []


def test_production_skill_reader_rejects_traversal_outside_and_symlink_escape(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    allowed = skills / "drug-target-reporting"
    allowed.mkdir(parents=True)
    (allowed / "SKILL.md").write_text("safe guidance", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    (allowed / "escape.md").symlink_to(outside)

    reader = production_skill_reader_tool(skills, ("drug-target-reporting",))
    assert "safe guidance" in reader.invoke(
        {"skill_path": "skills/drug-target-reporting/SKILL.md"}
    )
    assert "safe guidance" in reader.invoke({"skill_path": str(allowed / "SKILL.md")})
    for attempted_path in ("../outside.md", str(outside), "drug-target-reporting/escape.md"):
        result = reader.invoke({"skill_path": attempted_path})
        assert "not in the allowed skills" in result


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


def test_managed_filesystem_guard_rewrites_any_registered_data_dir_tool(tmp_path: Path) -> None:
    """The data_dir rewrite is driven by the guarded tool schema, not hard-coded names."""
    other = tmp_path / "other"
    other.mkdir()
    middleware = DrugTargetManagedFilesystemGuardMiddleware(
        tmp_path, data_dir_tool_names={"future_domain_tool"}
    )
    calls: list[dict[str, Any]] = []

    middleware.wrap_tool_call(
        _request("future_domain_tool", {"data_dir": str(other), "query": "GENE1"}),
        _recording_handler(calls),
    )

    assert calls == [
        {
            "id": "call-1",
            "name": "future_domain_tool",
            "args": {"data_dir": str(tmp_path.resolve()), "query": "GENE1"},
            "type": "tool_call",
        }
    ]


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


def test_task_allowlist_allows_only_production_subagents() -> None:
    middleware = DrugTargetTaskAllowlistMiddleware(
        {"evidence_assessor", "hypothesis_writer", "report_writer"}
    )
    calls: list[dict[str, Any]] = []
    for name in ("evidence_assessor", "hypothesis_writer", "report_writer"):
        middleware.wrap_tool_call(
            _request("task", {"subagent_type": name}), _recording_handler(calls)
        )
    middleware.wrap_tool_call(
        _request("task", {"subagent_type": "other"}), _recording_handler(calls)
    )
    assert [call["args"]["subagent_type"] for call in calls] == [
        "evidence_assessor",
        "hypothesis_writer",
        "report_writer",
    ]


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


def test_middleware_forwards_selected_model_and_request_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    def run_guardrail(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"status": "passed", "final_error_count": 0}

    monkeypatch.setattr(
        "src.agents.drug_target.middleware.run_drug_report_guardrail", run_guardrail
    )

    DrugReportGuardrailMiddleware(
        tmp_path,
        provider="ollama-openai",
        model="qwen3.5:122b",
        request_timeout_seconds=45.0,
        disease="IPF",
    ).after_agent({}, None)

    assert captured == {
        "provider": "ollama-openai",
        "model": "qwen3.5:122b",
        "request_timeout_seconds": 45.0,
        "disease": "IPF",
        "require_report_sections": True,
    }


def test_middleware_omits_unset_model_and_request_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    def run_guardrail(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"status": "passed", "final_error_count": 0}

    monkeypatch.setattr(
        "src.agents.drug_target.middleware.run_drug_report_guardrail", run_guardrail
    )

    DrugReportGuardrailMiddleware(tmp_path, provider="ollama-openai", disease="IPF").after_agent(
        {}, None
    )

    assert captured == {
        "provider": "ollama-openai",
        "disease": "IPF",
        "require_report_sections": True,
    }


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
        captured["hypothesis_source"] = kwargs.get("hypothesis_source")
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


def test_publication_uses_canonical_hypotheses_from_report_sections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "drug.md").write_text("not parsed", encoding="utf-8")
    _write_report_sections(tmp_path, {"hypothesis_report": {"untrusted": True}})
    canonical = {"schema_version": "hypothesis_report.v2", "hypotheses": []}
    captured: dict[str, Any] = {}
    _patch_publisher_happy_path(monkeypatch, captured)
    monkeypatch.setattr(
        report_guardrails,
        "_hypothesis_payload_from_markdown",
        lambda *_args: (_ for _ in ()).throw(AssertionError("Markdown parsed")),
    )
    monkeypatch.setattr(
        report_guardrails,
        "canonicalize_hypothesis_report",
        lambda *_args, **_kwargs: (canonical, [], []),
        raising=False,
    )
    monkeypatch.setattr(
        report_guardrails,
        "validate_canonical_hypothesis_report",
        lambda *_args, **_kwargs: [],
        raising=False,
    )

    asyncio.run(report_guardrails._publish_report_outputs(tmp_path, disease="test"))

    assert captured["payload"] == canonical
    assert captured["hypothesis_source"] == REPORT_SECTIONS_FILENAME


def test_publication_passes_selected_llm_configuration_to_part4_selector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "drug.md").write_text(DRUG_MD_WITH_HYPOTHESIS, encoding="utf-8")
    captured: dict[str, Any] = {}
    _patch_publisher_happy_path(monkeypatch, captured)

    async def selection(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        captured["selector_config"] = kwargs["config"]
        return {
            "schema_version": report_guardrails.PART4_CANDIDATE_SELECTION_SCHEMA_VERSION,
            "selected_genes": ["GENE1"],
        }

    monkeypatch.setattr(report_guardrails, "generate_part4_candidate_selection", selection)

    asyncio.run(
        report_guardrails._publish_report_outputs(
            tmp_path,
            disease="IPF",
            provider="ollama-openai",
            model="qwen3.5:122b",
            request_timeout_seconds=45.0,
        )
    )

    assert captured["selector_config"] == {
        "configurable": {
            "llm_provider": "ollama-openai",
            "llm_model": "qwen3.5:122b",
            "llm_request_timeout_seconds": 45.0,
        }
    }


def test_publication_omits_unset_llm_configuration_from_part4_selector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "drug.md").write_text(DRUG_MD_WITH_HYPOTHESIS, encoding="utf-8")
    captured: dict[str, Any] = {}
    _patch_publisher_happy_path(monkeypatch, captured)

    async def selection(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        captured["selector_config"] = kwargs["config"]
        return {
            "schema_version": report_guardrails.PART4_CANDIDATE_SELECTION_SCHEMA_VERSION,
            "selected_genes": ["GENE1"],
        }

    monkeypatch.setattr(report_guardrails, "generate_part4_candidate_selection", selection)

    asyncio.run(report_guardrails._publish_report_outputs(tmp_path, disease="IPF"))

    assert captured["selector_config"] == {}


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
