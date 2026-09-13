from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


def _write_required_report(data_dir: Path) -> None:
    (data_dir / "papers.json").write_text('{"papers": []}', encoding="utf-8")
    for name in ("part1_final.md", "part2_final.md", "part3_final.md"):
        (data_dir / name).write_text(f"# {name}\n", encoding="utf-8")
    (data_dir / "synthesis.md").write_text("# Synthesis\n", encoding="utf-8")
    (data_dir / "CCI_Analysis_Report.html").write_text("<html>ok</html>", encoding="utf-8")


def test_without_report_guardrails_disables_parts_and_synthesis_but_renders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.sni_guardrail_ablation_support import without_report_guardrails
    from src.agents.deep_interpreter.middleware import report_guardrail as middleware_guardrail
    from src.agents.deep_interpreter.tools import report as report_tool

    _write_required_report(tmp_path)

    def fail_parts(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("parts guardrail/repair must stay disabled")

    def fail_synthesis(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("synthesis guardrail/repair must stay disabled")

    monkeypatch.setattr(middleware_guardrail, "run_report_guardrail", fail_parts)
    monkeypatch.setattr(report_tool, "_run_synthesis_guardrail_before_html", fail_synthesis)

    with without_report_guardrails():
        assert middleware_guardrail.ReportGuardrailMiddleware(data_dir=tmp_path)._run() is None
        result = report_tool.generate_html_report.invoke(
            {
                "parts": {
                    "title": "CCI Analysis Report",
                    "part1": {},
                    "part2": {},
                    "part3": {},
                    "synthesis": "Kept as written.",
                },
                "output_path": "CCI_Analysis_Report.html",
                "data_dir": str(tmp_path),
            }
        )

    assert "Report generated successfully" in result
    assert "guardrail_ablation" in result


def test_without_report_guardrails_works_with_existing_capture(
    tmp_path: Path,
) -> None:
    from scripts import run_bc_sni_repair_ablation as runner
    from scripts.sni_guardrail_ablation_support import without_report_guardrails
    from src.agents.deep_interpreter.middleware import report_guardrail as middleware_guardrail
    from src.agents.deep_interpreter.tools import report as report_tool

    _write_required_report(tmp_path)
    (tmp_path / "before").mkdir()

    with without_report_guardrails():
        restore = runner._install_guardrail_capture(tmp_path)
        try:
            parts = middleware_guardrail.run_report_guardrail(tmp_path)
            synthesis = report_tool._run_synthesis_guardrail_before_html(str(tmp_path))
        finally:
            restore()

    assert parts["status"] == "disabled"
    assert synthesis["status"] == "disabled"
    assert json.loads((tmp_path / "parts_guardrail_result.json").read_text())["reason"] == "guardrail_ablation"
    assert json.loads((tmp_path / "synthesis_guardrail_result.json").read_text())["reason"] == "guardrail_ablation"


def test_without_report_guardrails_restores_after_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.sni_guardrail_ablation_support import without_report_guardrails
    from src.agents.deep_interpreter.middleware import report_guardrail as middleware_guardrail
    from src.agents.deep_interpreter.tools import report as report_tool

    original_parts = middleware_guardrail.ReportGuardrailMiddleware._run
    original_synthesis = report_tool._run_synthesis_guardrail_before_html

    with pytest.raises(RuntimeError, match="boom"):
        with without_report_guardrails():
            raise RuntimeError("boom")

    assert middleware_guardrail.ReportGuardrailMiddleware._run is original_parts
    assert report_tool._run_synthesis_guardrail_before_html is original_synthesis


def test_without_report_guardrails_allows_reporter_recovery_to_complete_rendering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.sni_guardrail_ablation_support import without_report_guardrails
    from src.agents.deep_interpreter import reporter_recovery

    (tmp_path / "synthesis.md").write_text("# Synthesis\n", encoding="utf-8")
    (tmp_path / "synthesis_validation.json").write_text(
        json.dumps({"synthesis_guardrail": {"status": "disabled", "validation_performed": False}}),
        encoding="utf-8",
    )
    (tmp_path / "synthesis_targets.json").write_text("{}", encoding="utf-8")
    (tmp_path / "CCI_Analysis_Report.html").write_text("<!doctype html><html></html>", encoding="utf-8")
    monkeypatch.setattr(reporter_recovery, "_reporter_artifact_validity", lambda _path: {
        "synthesis_validation.json": True,
        "synthesis_targets.json": True,
        "CCI_Analysis_Report.html": True,
    })

    assert reporter_recovery.inspect_reporter_completion(tmp_path)["complete"] is False
    with without_report_guardrails():
        assert reporter_recovery.inspect_reporter_completion(tmp_path)["complete"] is True


def test_evaluate_report_marks_missing_required_artifacts_incomplete(tmp_path: Path) -> None:
    from scripts.sni_guardrail_ablation_support import evaluate_report

    _write_required_report(tmp_path)
    (tmp_path / "CCI_Analysis_Report.html").unlink()

    result = evaluate_report(tmp_path)

    assert result["status"] == "incomplete"
    assert result["complete"] is False
    assert result["usable"] is False
    assert result["hard_error_count"] is None
    assert result["issues"][0]["code"] == "missing_required_artifact"


def test_evaluate_report_counts_common_validator_errors_without_mutating(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import sni_guardrail_ablation_support as support

    _write_required_report(tmp_path)
    before_text = (tmp_path / "part1_final.md").read_text(encoding="utf-8")

    def fake_parts(*_args: Any, **_kwargs: Any) -> tuple[Any, ...]:
        return ([{"severity": "error", "code": "bad_part", "file": "part1_final.md"}], [], None, None, "deterministic")

    def fake_synthesis(*_args: Any, **_kwargs: Any) -> tuple[Any, ...]:
        return ([], [], {"issues": [], "results": []}, None, None, "semantic")

    monkeypatch.setattr(support.report_guardrails, "_validate_part_reports", fake_parts)
    monkeypatch.setattr(support.report_guardrails, "_validate_synthesis_guardrails", fake_synthesis)

    result = support.evaluate_report(tmp_path)

    assert result["status"] == "evaluated"
    assert result["complete"] is True
    assert result["usable"] is False
    assert result["hard_error_count"] == 1
    assert result["phases"] == {"parts": "deterministic", "synthesis": "semantic"}
    assert (tmp_path / "part1_final.md").read_text(encoding="utf-8") == before_text
    assert result["hashes_before"] == result["hashes_after"]


@pytest.mark.parametrize("content_issues", [[], [{"severity": "error", "code": "bad_content"}]])
def test_evaluate_report_never_passes_incomplete_claim_judging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    content_issues: list[dict[str, str]],
) -> None:
    from scripts import sni_guardrail_ablation_support as support

    _write_required_report(tmp_path)

    def fake_parts(*_args: Any, **_kwargs: Any) -> tuple[Any, ...]:
        return (
            content_issues,
            [{"status": "unverifiable", "reason": "Claim judge omitted this claim."}],
            None,
            None,
            "semantic",
        )

    def fake_synthesis(*_args: Any, **_kwargs: Any) -> tuple[Any, ...]:
        return ([], [], {"issues": [], "results": []}, None, None, "semantic")

    monkeypatch.setattr(support.report_guardrails, "_validate_part_reports", fake_parts)
    monkeypatch.setattr(support.report_guardrails, "_validate_synthesis_guardrails", fake_synthesis)

    result = support.evaluate_report(tmp_path)

    assert result["status"] == "evaluation_failed"
    assert result["usable"] is None
    assert result["hard_error_count"] is None
    assert all(issue in result["issues"] for issue in content_issues)
    assert result["phases"] == {"parts": "semantic", "synthesis": "semantic"}
    assert result["issues"][0]["code"] == "claim_evaluation_incomplete"
    assert result["issues"][0]["reason"] == "Claim judge omitted this claim."
    assert result["hashes_before"] == result["hashes_after"]


def test_evaluate_report_allows_legitimate_unverifiable_claims(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import sni_guardrail_ablation_support as support

    _write_required_report(tmp_path)

    def fake_parts(*_args: Any, **_kwargs: Any) -> tuple[Any, ...]:
        return (
            [],
            [{"status": "unverifiable", "reason": "Evidence is absent."}],
            None,
            None,
            "semantic",
        )

    def fake_synthesis(*_args: Any, **_kwargs: Any) -> tuple[Any, ...]:
        return ([], [], {"issues": [], "results": []}, None, None, "semantic")

    monkeypatch.setattr(support.report_guardrails, "_validate_part_reports", fake_parts)
    monkeypatch.setattr(support.report_guardrails, "_validate_synthesis_guardrails", fake_synthesis)

    result = support.evaluate_report(tmp_path)

    assert result["status"] == "evaluated"
    assert result["usable"] is True
    assert result["hard_error_count"] == 0


def test_evaluate_report_never_passes_failed_evaluation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import sni_guardrail_ablation_support as support

    _write_required_report(tmp_path)

    def broken_parts(*_args: Any, **_kwargs: Any) -> tuple[Any, ...]:
        raise RuntimeError("validator unavailable")

    monkeypatch.setattr(support.report_guardrails, "_validate_part_reports", broken_parts)

    result = support.evaluate_report(tmp_path)

    assert result["status"] == "evaluation_failed"
    assert result["complete"] is True
    assert result["usable"] is None
    assert result["hard_error_count"] is None
    assert json.loads(json.dumps(result["issues"]))


def test_evaluate_report_never_passes_report_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import sni_guardrail_ablation_support as support

    _write_required_report(tmp_path)

    def mutating_parts(data_dir: Path, *_args: Any, **_kwargs: Any) -> tuple[Any, ...]:
        (data_dir / "part1_final.md").write_text("changed\n", encoding="utf-8")
        return ([], [], None, None, "semantic")

    def fake_synthesis(*_args: Any, **_kwargs: Any) -> tuple[Any, ...]:
        return ([], [], {"issues": [], "results": []}, None, None, "semantic")

    monkeypatch.setattr(support.report_guardrails, "_validate_part_reports", mutating_parts)
    monkeypatch.setattr(support.report_guardrails, "_validate_synthesis_guardrails", fake_synthesis)

    result = support.evaluate_report(tmp_path)

    assert result["status"] == "evaluation_failed"
    assert result["usable"] is None
    assert result["hard_error_count"] is None
    assert result["issues"][0]["code"] == "report_mutated_by_evaluation"
