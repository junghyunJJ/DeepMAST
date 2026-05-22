from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _clear_llm_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "LLM_PROVIDER",
    ):
        monkeypatch.delenv(name, raising=False)


def _copy_baseline_workspace(tmp_path: Path) -> Path:
    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "baseline_hallucinated"
    )
    workspace = tmp_path / "workspace"
    shutil.copytree(fixture, workspace)
    return workspace


def _issue_codes(diagnostics: dict) -> set[str]:
    return {
        str(issue.get("code"))
        for issue in diagnostics.get("issues", [])
        if isinstance(issue, dict)
    }


def test_harness_writes_diagnostics_for_successful_no_llm_report(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.report_harness import (
        HARNESS_SCHEMA_VERSION,
        run_deterministic_report_harness,
    )

    workspace = _copy_baseline_workspace(tmp_path)
    result = asyncio.run(
        run_deterministic_report_harness(
            {
                "data_dir": str(workspace),
                "disease": "idiopathic pulmonary fibrosis",
                "report_finalization_error": None,
                "evidence_truncated": False,
            },
            {},
        )
    )

    diagnostics_path = workspace / "report_harness_diagnostics.json"
    diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))

    assert result["report_finalization_error"] is None
    assert result["evidence_truncated"] is False
    assert result["report_harness_diagnostics_path"] == str(diagnostics_path)
    assert diagnostics["schema_version"] == HARNESS_SCHEMA_VERSION
    assert diagnostics["valid"] is True
    assert diagnostics["issues"] == []
    assert diagnostics["finalizer_result"] == {
        "report_finalization_error": None,
        "evidence_truncated": False,
    }
    for name in (
        "report_data.json",
        "drug.md",
        "drug_report.html",
        "report_validation.json",
    ):
        assert diagnostics["artifacts"][name]["exists"] is True
        assert diagnostics["artifacts"][name]["size_bytes"] > 0


def test_harness_classifies_missing_required_evidence_without_llm(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.report_harness import (
        run_deterministic_report_harness,
    )

    workspace = _copy_baseline_workspace(tmp_path)
    (workspace / "evidence" / "assessment_results.json").unlink()

    result = asyncio.run(
        run_deterministic_report_harness(
            {
                "data_dir": str(workspace),
                "disease": "idiopathic pulmonary fibrosis",
                "report_finalization_error": None,
                "evidence_truncated": False,
            },
            {},
        )
    )
    diagnostics = result["report_harness_diagnostics"]

    assert result["report_finalization_error"].startswith(
        "deterministic_report_validation_failed:"
    )
    assert diagnostics["valid"] is False
    assert "MISSING_REQUIRED_EVIDENCE" in _issue_codes(diagnostics)
    assert diagnostics["evidence"]["evidence/assessment_results.json"]["exists"] is False


def test_harness_classifies_malformed_required_evidence_json(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.report_harness import (
        run_deterministic_report_harness,
    )

    workspace = _copy_baseline_workspace(tmp_path)
    (workspace / "evidence" / "hypothesis_report.json").write_text(
        "{",
        encoding="utf-8",
    )

    result = asyncio.run(
        run_deterministic_report_harness(
            {
                "data_dir": str(workspace),
                "disease": "idiopathic pulmonary fibrosis",
                "report_finalization_error": None,
                "evidence_truncated": False,
            },
            {},
        )
    )
    diagnostics = result["report_harness_diagnostics"]

    assert diagnostics["valid"] is False
    assert "MALFORMED_REQUIRED_EVIDENCE_JSON" in _issue_codes(diagnostics)
    assert (
        diagnostics["evidence"]["evidence/hypothesis_report.json"]["valid_json"]
        is False
    )


def test_harness_flags_unexpanded_markers_after_artifact_generation(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import finalize_report_mvp
    from src.agents.drug_target.report_harness import (
        collect_report_harness_diagnostics,
    )

    workspace = _copy_baseline_workspace(tmp_path)
    result = asyncio.run(
        finalize_report_mvp(
            {
                "data_dir": str(workspace),
                "disease": "idiopathic pulmonary fibrosis",
                "report_finalization_error": None,
                "evidence_truncated": False,
            },
            {},
        )
    )
    assert result["report_finalization_error"] is None

    (workspace / "drug.md").write_text(
        "# Broken report\n\n<!-- EXPAND:featured_candidate -->\n",
        encoding="utf-8",
    )

    diagnostics = collect_report_harness_diagnostics(str(workspace))

    assert diagnostics["valid"] is False
    assert "UNEXPANDED_PLACEHOLDER" in _issue_codes(diagnostics)


def test_harness_classifies_missing_required_artifact(tmp_path: Path) -> None:
    from src.agents.drug_target.deterministic_report import finalize_report_mvp
    from src.agents.drug_target.report_harness import (
        collect_report_harness_diagnostics,
    )

    workspace = _copy_baseline_workspace(tmp_path)
    result = asyncio.run(
        finalize_report_mvp(
            {
                "data_dir": str(workspace),
                "disease": "idiopathic pulmonary fibrosis",
                "report_finalization_error": None,
                "evidence_truncated": False,
            },
            {},
        )
    )
    assert result["report_finalization_error"] is None

    (workspace / "drug_report.html").unlink()

    diagnostics = collect_report_harness_diagnostics(str(workspace))

    assert diagnostics["valid"] is False
    assert "MISSING_REQUIRED_ARTIFACT" in _issue_codes(diagnostics)
    assert diagnostics["artifacts"]["drug_report.html"]["exists"] is False


def test_harness_classifies_malformed_artifact_json(tmp_path: Path) -> None:
    from src.agents.drug_target.deterministic_report import finalize_report_mvp
    from src.agents.drug_target.report_harness import (
        collect_report_harness_diagnostics,
    )

    workspace = _copy_baseline_workspace(tmp_path)
    result = asyncio.run(
        finalize_report_mvp(
            {
                "data_dir": str(workspace),
                "disease": "idiopathic pulmonary fibrosis",
                "report_finalization_error": None,
                "evidence_truncated": False,
            },
            {},
        )
    )
    assert result["report_finalization_error"] is None

    (workspace / "report_data.json").write_text("{", encoding="utf-8")

    diagnostics = collect_report_harness_diagnostics(str(workspace))

    assert diagnostics["valid"] is False
    assert "MALFORMED_ARTIFACT_JSON" in _issue_codes(diagnostics)
    assert diagnostics["artifacts"]["report_data.json"]["valid_json"] is False


def test_harness_classifies_failed_report_validation(tmp_path: Path) -> None:
    from src.agents.drug_target.deterministic_report import finalize_report_mvp
    from src.agents.drug_target.report_harness import (
        collect_report_harness_diagnostics,
    )

    workspace = _copy_baseline_workspace(tmp_path)
    result = asyncio.run(
        finalize_report_mvp(
            {
                "data_dir": str(workspace),
                "disease": "idiopathic pulmonary fibrosis",
                "report_finalization_error": None,
                "evidence_truncated": False,
            },
            {},
        )
    )
    assert result["report_finalization_error"] is None

    (workspace / "report_validation.json").write_text(
        json.dumps(
            {
                "schema_version": "drug_target.report_validation.v1",
                "valid": False,
                "issues": [
                    {
                        "code": "SYNTHETIC_VALIDATION_FAILURE",
                        "severity": "critical",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    diagnostics = collect_report_harness_diagnostics(str(workspace))

    assert diagnostics["valid"] is False
    assert "REPORT_VALIDATION_FAILED" in _issue_codes(diagnostics)
    validation_issue = next(
        issue
        for issue in diagnostics["issues"]
        if issue["code"] == "REPORT_VALIDATION_FAILED"
    )
    assert validation_issue["issue_count"] == 1


def test_mvp2_harness_contract_keeps_deepagents_out_of_artifact_authoring() -> None:
    from src.agents.drug_target.report_harness import deepagents_boundary_contract

    contract = deepagents_boundary_contract()

    assert contract["deepagents"]["allowed"] == [
        "collect_evidence",
        "write_hypothesis_report",
        "optional_interpretation",
        "orchestration",
        "critique",
        "harness_diagnostics",
    ]
    assert contract["deepagents"]["forbidden"] == [
        "write_report_data",
        "write_drug_md",
        "write_drug_report_html",
        "choose_provenance_keys",
        "decide_final_success",
    ]
    assert contract["deterministic_code"]["owns"] == [
        "report_data_json",
        "drug_md",
        "drug_report_html",
        "report_validation_json",
        "report_harness_diagnostics_json",
        "final_success_or_failure",
    ]


def test_mvp2_harness_stays_out_of_production_graph_routing() -> None:
    super_graph_source = Path("src/agents/drug_target/super_graph.py").read_text(
        encoding="utf-8"
    )
    harness_source = Path("src/agents/drug_target/report_harness.py").read_text(
        encoding="utf-8"
    )

    assert "from src.agents.drug_target.finalize_report import finalize_report" in (
        super_graph_source
    )
    assert 'graph.add_node("finalize_report", finalize_report)' in super_graph_source
    assert "finalize_report_mvp" not in super_graph_source
    assert "create_llm" not in harness_source
    assert "create_deep_agent" not in harness_source
