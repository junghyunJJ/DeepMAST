from __future__ import annotations

import json
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from langchain.agents.middleware import AgentState
from langchain_core.messages import AIMessage


def _agent_state() -> AgentState[Any]:
    return {"messages": []}


@pytest.fixture(autouse=True)
def _stub_claim_rag_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.agents.deep_interpreter import report_guardrails

    monkeypatch.setattr(
        report_guardrails.claim_rag_validation,
        "validate_claims",
        lambda *_args, **_kwargs: {"claims": [], "issues": []},
    )


def _write_required_files(data_dir: Path) -> None:
    (data_dir / "papers.json").write_text('{"papers": []}', encoding="utf-8")
    (data_dir / "part1_final.md").write_text("## Part 1\n", encoding="utf-8")
    (data_dir / "part2_final.md").write_text("## Part 2\n", encoding="utf-8")
    (data_dir / "part3_final.md").write_text("## Part 3\n", encoding="utf-8")


def _write_synthesis_required_files(data_dir: Path) -> None:
    (data_dir / "papers.json").write_text(
        json.dumps({"papers": [{"pmid": "12345678", "title": "Supported paper"}]}),
        encoding="utf-8",
    )
    (data_dir / "synthesis.md").write_text(
        "## Executive Summary\n\n"
        "MISTy spatial evidence drives a therapy-resistant subpopulation (PMID: 87654321).\n",
        encoding="utf-8",
    )


def _write_consistency_guardrail_fixture(data_dir: Path, synthesis: str) -> None:
    (data_dir / "papers.json").write_text('{"papers": []}', encoding="utf-8")
    (data_dir / "part1_final.md").write_text("## Part 1\n", encoding="utf-8")
    (data_dir / "part2_final.md").write_text("## Part 2\n", encoding="utf-8")
    (data_dir / "part3_final.md").write_text("## Part 3\n", encoding="utf-8")
    (data_dir / "part4_candidate_selection.json").write_text(
        json.dumps(
            {
                "selected_genes": ["ERBB3"],
                "selected_lr_pairs": [
                    {"interaction": "CDH1^ERBB3", "combinedscore": 0.8141}
                ],
            }
        ),
        encoding="utf-8",
    )
    (data_dir / "part4_therapeutic_synthesis.md").write_text(
        "### 1. Candidate: ERBB3\n"
        "- Score profile: combined 16 = validated 10 + exploratory 6.\n",
        encoding="utf-8",
    )
    (data_dir / "synthesis.md").write_text(synthesis, encoding="utf-8")


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


def test_run_report_guardrail_fails_when_papers_json_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    _write_required_files(tmp_path)
    (tmp_path / "papers.json").unlink()

    def fail_claim_validate(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("claim validation must not run without papers.json")

    monkeypatch.setattr(
        report_guardrails.claim_rag_validation,
        "validate_claims",
        fail_claim_validate,
    )

    result = report_guardrails.run_report_guardrail(tmp_path, provider="ollama")

    initial = json.loads((tmp_path / "report_validation_initial.json").read_text(encoding="utf-8"))
    final = json.loads((tmp_path / "report_validation_final.json").read_text(encoding="utf-8"))
    assert result["status"] == "failed"
    assert result["initial_error_count"] == 1
    assert result["final_error_count"] == 1
    assert initial["issues"][0]["code"] == "papers_json_missing"
    assert final["issues"][0]["code"] == "papers_json_missing"
    assert initial["claim_validation"] == []
    assert final["claim_validation"] == []


def test_run_synthesis_guardrail_skips_until_synthesis_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    (tmp_path / "papers.json").write_text('{"papers": []}', encoding="utf-8")

    def fail_validate(_data_dir: Path) -> list[dict[str, str]]:
        raise AssertionError("part-level validate_report must not run for synthesis guardrail")

    monkeypatch.setattr(report_guardrails.validate_report_script, "validate_report", fail_validate)

    result = report_guardrails.run_synthesis_guardrail(tmp_path)

    assert result == {"status": "skipped", "missing": ["synthesis.md"]}
    assert not (tmp_path / "synthesis_guardrail_initial.json").exists()
    assert not (tmp_path / "synthesis_guardrail_final.json").exists()


def test_run_synthesis_guardrail_repairs_invalid_pmid_and_softens_overclaim(
    tmp_path: Path,
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    _write_synthesis_required_files(tmp_path)

    result = report_guardrails.run_synthesis_guardrail(tmp_path)

    synthesis = (tmp_path / "synthesis.md").read_text(encoding="utf-8")
    initial = json.loads((tmp_path / "synthesis_guardrail_initial.json").read_text(encoding="utf-8"))
    final = json.loads((tmp_path / "synthesis_guardrail_final.json").read_text(encoding="utf-8"))

    assert result["status"] == "passed"
    assert result["artifact"] == "synthesis.md"
    assert result["initial_error_count"] >= 1
    assert result["repair_attempt_count"] == 1
    assert result["changed_claims"] >= 1
    assert result["final_error_count"] == 0
    assert "87654321" not in synthesis
    assert "hypothesis requiring validation" in synthesis.lower()
    assert initial["issue_count"] >= 1
    assert final["issue_count"] >= 1
    assert all(issue["severity"] != "error" for issue in final["issues"])


def test_run_synthesis_guardrail_never_calls_claim_rag_and_keeps_empty_claim_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    (tmp_path / "papers.json").write_text(
        json.dumps({"papers": [{"pmid": "11111111", "abstract": "association"}]}),
        encoding="utf-8",
    )
    claim = "MISTy spatial evidence drives fibrosis (PMID: 11111111)."
    (tmp_path / "synthesis.md").write_text(
        f"## Cross-Part Themes\n\n{claim}\n",
        encoding="utf-8",
    )

    def fail_claim_validate(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("synthesis guardrail must not call Claim RAG")

    monkeypatch.setattr(
        report_guardrails.claim_rag_validation, "validate_claims", fail_claim_validate
    )

    result = report_guardrails.run_synthesis_guardrail(tmp_path, provider="ollama")

    initial = json.loads(
        (tmp_path / "synthesis_guardrail_initial.json").read_text(encoding="utf-8")
    )
    final = json.loads(
        (tmp_path / "synthesis_guardrail_final.json").read_text(encoding="utf-8")
    )
    synthesis = (tmp_path / "synthesis.md").read_text(encoding="utf-8")
    assert result["status"] == "passed"
    assert result["repair_attempt_count"] == 1
    assert result["claims_validated"] == 0
    assert result["claims_by_status"] == {
        "supported": 0,
        "overclaimed": 0,
        "unsupported": 0,
        "unverifiable": 0,
    }
    assert result["validation_results"] == []
    assert initial["claim_validation"] == []
    assert final["claim_validation"] == []
    assert "hypothesis requiring validation" in synthesis.lower()


def test_run_synthesis_guardrail_repairs_consistency_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    _write_consistency_guardrail_fixture(
        tmp_path,
        "### 1. ERBB3 (Combined Score: 15)\n",
    )

    def fail_claim_validate(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("synthesis consistency guardrail must not call Claim RAG")

    monkeypatch.setattr(
        report_guardrails.claim_rag_validation, "validate_claims", fail_claim_validate
    )

    result = report_guardrails.run_synthesis_guardrail(tmp_path)

    assert result["status"] == "passed"
    assert result["repair_attempt_count"] == 1
    assert result["consistency_issue_count"] == 1
    assert "Combined Score: 16" in (tmp_path / "synthesis.md").read_text(
        encoding="utf-8"
    )
    final = json.loads(
        (tmp_path / "synthesis_guardrail_final.json").read_text(encoding="utf-8")
    )
    assert final["claim_validation"] == []
    assert final["consistency_validation"]
    assert not [issue for issue in final["issues"] if issue["severity"] == "error"]


def test_run_synthesis_guardrail_fails_unresolved_consistency_issue(
    tmp_path: Path,
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    synthesis = "### 1. EGFR (Combined Score: 15)\n"
    _write_consistency_guardrail_fixture(tmp_path, synthesis)

    result = report_guardrails.run_synthesis_guardrail(tmp_path)

    final = json.loads(
        (tmp_path / "synthesis_guardrail_final.json").read_text(encoding="utf-8")
    )
    assert (tmp_path / "synthesis.md").read_text(encoding="utf-8") == synthesis
    assert result["status"] == "failed"
    assert result["repair_attempt_count"] == 1
    assert final["issues"][-1]["code"] == "synthesis_consistency_unresolved"


def test_run_synthesis_guardrail_rejects_html_fragment_synthesis(
    tmp_path: Path,
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    (tmp_path / "papers.json").write_text('{"papers": []}', encoding="utf-8")
    (tmp_path / "synthesis.md").write_text(
        '<div class="summary-box"><p>HTML belongs in the rendered report.</p></div>\n',
        encoding="utf-8",
    )

    result = report_guardrails.run_synthesis_guardrail(tmp_path)
    final = json.loads((tmp_path / "synthesis_guardrail_final.json").read_text(encoding="utf-8"))

    assert result["status"] == "failed"
    assert result["repair_attempt_count"] == 1
    assert result["final_error_count"] == 1
    assert final["issues"][0]["code"] == "synthesis_not_markdown"


def test_run_synthesis_guardrail_allows_neutral_clinical_context(
    tmp_path: Path,
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    (tmp_path / "papers.json").write_text(
        json.dumps({"papers": [{"pmid": "12345678", "title": "Supported paper"}]}),
        encoding="utf-8",
    )
    synthesis = (
        "## Executive Summary\n\n"
        "MISTy spatial analysis used clinical metadata from the treatment cohort "
        "(PMID: 12345678).\n"
    )
    (tmp_path / "synthesis.md").write_text(synthesis, encoding="utf-8")

    result = report_guardrails.run_synthesis_guardrail(tmp_path)

    assert result["status"] == "passed"
    assert result["changed_claims"] == 0
    assert result["repair_attempt_count"] == 0
    assert result["initial_error_count"] == 0
    assert result["final_error_count"] == 0
    assert (tmp_path / "synthesis.md").read_text(encoding="utf-8") == synthesis


def test_run_synthesis_guardrail_repairs_duplicate_overclaims_once_each(
    tmp_path: Path,
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    (tmp_path / "papers.json").write_text(
        json.dumps({"papers": [{"pmid": "12345678", "title": "Supported paper"}]}),
        encoding="utf-8",
    )
    claim = "MISTy spatial evidence drives a therapy-resistant subpopulation (PMID: 12345678)."
    (tmp_path / "synthesis.md").write_text(
        f"## Executive Summary\n\n{claim}\n\n{claim}\n",
        encoding="utf-8",
    )

    result = report_guardrails.run_synthesis_guardrail(tmp_path)
    synthesis = (tmp_path / "synthesis.md").read_text(encoding="utf-8")

    assert result["status"] == "passed"
    assert result["changed_claims"] == 2
    assert synthesis.count("hypothesis requiring validation") == 2
    assert f"{claim} this remains a hypothesis requiring validation. this remains" not in synthesis


def test_run_synthesis_guardrail_allows_negated_therapeutic_limitation(
    tmp_path: Path,
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    (tmp_path / "papers.json").write_text(
        json.dumps({"papers": [{"pmid": "12345678", "title": "Supported paper"}]}),
        encoding="utf-8",
    )
    synthesis = (
        "## Limitations\n\n"
        "MISTy spatial evidence does not establish a therapeutic vulnerability "
        "(PMID: 12345678).\n"
    )
    (tmp_path / "synthesis.md").write_text(synthesis, encoding="utf-8")

    result = report_guardrails.run_synthesis_guardrail(tmp_path)

    assert result["status"] == "passed"
    assert result["changed_claims"] == 0
    assert result["initial_error_count"] == 0
    assert result["final_error_count"] == 0
    assert (tmp_path / "synthesis.md").read_text(encoding="utf-8") == synthesis


def test_run_synthesis_guardrail_allows_negated_therapeutic_proof_limitation(
    tmp_path: Path,
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    (tmp_path / "papers.json").write_text(
        json.dumps({"papers": [{"pmid": "12345678", "title": "Supported paper"}]}),
        encoding="utf-8",
    )
    synthesis = (
        "## Limitations\n\n"
        "MISTy spatial evidence does not prove therapeutic vulnerability "
        "(PMID: 12345678).\n"
    )
    (tmp_path / "synthesis.md").write_text(synthesis, encoding="utf-8")

    result = report_guardrails.run_synthesis_guardrail(tmp_path)

    assert result["status"] == "passed"
    assert result["changed_claims"] == 0
    assert result["initial_error_count"] == 0
    assert result["final_error_count"] == 0
    assert (tmp_path / "synthesis.md").read_text(encoding="utf-8") == synthesis


def test_run_synthesis_guardrail_retries_up_to_three_repairs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    _write_synthesis_required_files(tmp_path)
    validate_count = 0
    repair_count = 0

    def fake_validate(_data_dir: Path) -> list[dict[str, str]]:
        nonlocal validate_count
        validate_count += 1
        severity = "warning" if validate_count == 4 else "error"
        return [{"severity": severity, "code": "bounded_synthesis_retry"}]

    def fake_repair(_data_dir: Path, _issues: list[dict[str, str]]) -> int:
        nonlocal repair_count
        repair_count += 1
        return 1

    monkeypatch.setattr(report_guardrails, "validate_synthesis_report", fake_validate)
    monkeypatch.setattr(report_guardrails, "repair_synthesis_report", fake_repair)

    result = report_guardrails.run_synthesis_guardrail(tmp_path)

    assert validate_count == 4
    assert repair_count == 3
    assert result["status"] == "passed"
    assert result["repair_attempt_count"] == 3
    assert result["changed_claims"] == 3
    assert result["final_error_count"] == 0


def test_run_report_guardrail_stops_after_first_successful_repair(
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
        "repair_attempt_count": 1,
        "changed_sections": 1,
        "final_issue_count": 1,
        "final_error_count": 0,
    }
    initial = json.loads((tmp_path / "report_validation_initial.json").read_text(encoding="utf-8"))
    final = json.loads((tmp_path / "report_validation_final.json").read_text(encoding="utf-8"))
    assert initial["issue_count"] == 1
    assert final["issue_count"] == 1
    assert final["issues"][0]["severity"] == "warning"


def test_run_report_guardrail_merges_claim_errors_and_revalidates_after_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    _write_required_files(tmp_path)
    claim_calls = 0

    monkeypatch.setattr(
        report_guardrails.validate_report_script,
        "validate_report",
        lambda _data_dir: [],
    )

    def fake_claim_validate(*_args, **_kwargs):
        nonlocal claim_calls
        claim_calls += 1
        if claim_calls == 1:
            return {
                "claims": [{"status": "overclaimed", "claim": "TGFB drives fibrosis."}],
                "issues": [
                    {
                        "code": "claim_rag_overclaimed",
                        "severity": "error",
                        "file": "part1_final.md",
                        "section": "## Part 1",
                        "value": "TGFB drives fibrosis.",
                        "evidence": "The paper supports association only.",
                        "repair_instruction": "Rewrite as association.",
                    }
                ],
            }
        return {
            "claims": [{"status": "supported", "claim": "TGFB is associated with fibrosis."}],
            "issues": [],
        }

    repair_calls = 0

    def fake_repair(*_args, **_kwargs):
        nonlocal repair_calls
        repair_calls += 1
        return 1

    monkeypatch.setattr(
        report_guardrails.claim_rag_validation, "validate_claims", fake_claim_validate
    )
    monkeypatch.setattr(
        report_guardrails.repair_report_script, "repair_report", fake_repair
    )

    result = report_guardrails.run_report_guardrail(tmp_path, provider="ollama")

    initial = json.loads(
        (tmp_path / "report_validation_initial.json").read_text(encoding="utf-8")
    )
    final = json.loads(
        (tmp_path / "report_validation_final.json").read_text(encoding="utf-8")
    )
    assert result["status"] == "passed"
    assert result["repair_attempt_count"] == 1
    assert claim_calls == 2
    assert repair_calls == 1
    assert initial["issues"][0]["code"] == "claim_rag_overclaimed"
    assert initial["claim_validation"][0]["status"] == "overclaimed"
    assert final["claim_validation"][0]["status"] == "supported"


def test_run_report_guardrail_retries_up_to_three_repairs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    _write_required_files(tmp_path)
    calls: list[str] = []

    def fake_validate(_data_dir: Path) -> list[dict[str, str]]:
        calls.append("validate")
        severity = "warning" if calls.count("validate") == 4 else "error"
        return [{"severity": severity, "code": "bounded_retry"}]

    def fake_repair(
        data_dir: Path, issues_path: Path, *, provider: str | None = None, llm=None
    ) -> int:
        calls.append("repair")
        assert data_dir == tmp_path.resolve()
        assert issues_path in {
            tmp_path.resolve() / "report_validation_initial.json",
            tmp_path.resolve() / "report_validation_final.json",
        }
        return 1

    monkeypatch.setattr(report_guardrails.validate_report_script, "validate_report", fake_validate)
    monkeypatch.setattr(report_guardrails.repair_report_script, "repair_report", fake_repair)

    result = report_guardrails.run_report_guardrail(tmp_path, provider="ollama")

    assert calls == [
        "validate",
        "repair",
        "validate",
        "repair",
        "validate",
        "repair",
        "validate",
    ]
    assert result["status"] == "passed"
    assert result["repair_attempt_count"] == 3
    assert result["changed_sections"] == 3
    assert result["final_error_count"] == 0


def test_run_report_guardrail_records_remaining_errors_without_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    _write_required_files(tmp_path)
    validate_count = 0
    repair_count = 0

    def fake_validate(_data_dir: Path) -> list[dict[str, str]]:
        nonlocal validate_count
        validate_count += 1
        return [{"severity": "error", "code": "still_bad"}]

    def fake_repair(
        data_dir: Path, issues_path: Path, *, provider: str | None = None, llm=None
    ) -> int:
        nonlocal repair_count
        repair_count += 1
        return 0

    monkeypatch.setattr(report_guardrails.validate_report_script, "validate_report", fake_validate)
    monkeypatch.setattr(report_guardrails.repair_report_script, "repair_report", fake_repair)

    result = report_guardrails.run_report_guardrail(tmp_path)

    assert validate_count == 2
    assert repair_count == 1
    assert result["status"] == "failed"
    assert result["repair_attempt_count"] == 1
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

    result = ReportGuardrailMiddleware(data_dir=tmp_path, provider="ollama").after_agent(
        _agent_state(), None
    )

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

    result = ReportGuardrailMiddleware(data_dir=tmp_path).after_agent(_agent_state(), None)

    assert result is None


def _failed_guardrail_result() -> dict[str, object]:
    return {
        "status": "failed",
        "initial_issue_count": 1,
        "initial_error_count": 1,
        "repair_attempt_count": 3,
        "changed_sections": 0,
        "final_issue_count": 1,
        "final_error_count": 1,
    }


def test_report_guardrail_middleware_raises_when_hard_errors_remain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.deep_interpreter.middleware.report_guardrail import ReportGuardrailMiddleware

    monkeypatch.setattr(
        "src.agents.deep_interpreter.middleware.report_guardrail.run_report_guardrail",
        lambda *_args, **_kwargs: _failed_guardrail_result(),
    )

    with pytest.raises(
        RuntimeError,
        match=r"Report guardrail failed with 1 hard error\(s\).*report_validation_final\.json",
    ):
        ReportGuardrailMiddleware(data_dir=tmp_path).after_agent(_agent_state(), None)


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

    result = ReportGuardrailMiddleware().after_agent(_agent_state(), None)

    assert result is not None
    assert seen == [tmp_path]


@pytest.mark.asyncio
async def test_report_guardrail_middleware_async_hook_raises_when_hard_errors_remain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.deep_interpreter.middleware.report_guardrail import ReportGuardrailMiddleware

    monkeypatch.setattr(
        "src.agents.deep_interpreter.middleware.report_guardrail.run_report_guardrail",
        lambda *_args, **_kwargs: _failed_guardrail_result(),
    )

    with pytest.raises(
        RuntimeError,
        match=r"Report guardrail failed with 1 hard error\(s\).*report_validation_final\.json",
    ):
        await ReportGuardrailMiddleware(data_dir=tmp_path).aafter_agent(_agent_state(), None)


def test_get_subagents_attaches_report_guardrail_only_to_interpreter() -> None:
    from src.agents.deep_interpreter.middleware import ReportGuardrailMiddleware
    from src.agents.deep_interpreter.subagents.configs import get_subagents

    subagents = get_subagents(
        data_dir="/tmp/deepmast-report-guardrail-test",
        provider="ollama",
    )
    by_name = {subagent["name"]: subagent for subagent in subagents}

    interpreter_middleware = by_name["interpreter"]["middleware"]
    report_guardrails = [
        middleware
        for middleware in interpreter_middleware
        if isinstance(middleware, ReportGuardrailMiddleware)
    ]
    assert len(report_guardrails) == 1
    assert report_guardrails[0]._provider == "ollama"

    for name in ("planner", "searcher", "reporter"):
        assert not any(
            isinstance(middleware, ReportGuardrailMiddleware)
            for middleware in by_name[name].get("middleware", [])
        )


def test_standalone_subagent_graph_uses_configured_middleware(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class FakeAgent:
        def with_config(self, config: dict[str, int]) -> SimpleNamespace:
            return SimpleNamespace(config=config)

    def fake_create_agent(*_args: Any, **kwargs: Any) -> FakeAgent:
        calls.append(kwargs)
        return FakeAgent()

    monkeypatch.setenv("DEEP_INTERPRETER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("langchain.agents.create_agent", fake_create_agent)
    monkeypatch.setattr(
        "src.agents.deep_interpreter.agent.create_deep_interpreter_agent",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "src.agents.deep_interpreter.wrapper_agent.DeepInterpreterWrapperAgent",
        lambda *_args, **_kwargs: SimpleNamespace(graph=SimpleNamespace()),
    )
    monkeypatch.setattr(
        "src.agents.model.create_llm",
        lambda *_args, **_kwargs: object(),
    )

    sys.modules.pop("src.agents.deep_interpreter.graph_builder", None)
    graph_builder = importlib.import_module("src.agents.deep_interpreter.graph_builder")
    from src.agents.deep_interpreter.middleware import (
        ReportGuardrailMiddleware,
        WriteFileArgGuardMiddleware,
    )

    graph = graph_builder.create_subagent_graph("interpreter", provider="ollama")

    call = calls[-1]
    middleware = call["middleware"]
    assert graph.config == {"recursion_limit": 200}
    assert any(isinstance(item, WriteFileArgGuardMiddleware) for item in middleware)
    report_guardrails = [item for item in middleware if isinstance(item, ReportGuardrailMiddleware)]
    assert len(report_guardrails) == 1
    assert report_guardrails[0]._resolved_data_dir() == tmp_path.resolve()
    assert report_guardrails[0]._provider == "ollama"

    graph = graph_builder.create_subagent_graph("reporter", provider="ollama")

    call = calls[-1]
    middleware = call["middleware"]
    assert graph.config == {"recursion_limit": 200}
    assert any(isinstance(item, WriteFileArgGuardMiddleware) for item in middleware)
    assert not any(isinstance(item, ReportGuardrailMiddleware) for item in middleware)
