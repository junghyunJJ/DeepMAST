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


def _state(workspace: Path) -> dict[str, object]:
    return {
        "data_dir": str(workspace),
        "disease": "idiopathic pulmonary fibrosis",
        "report_finalization_error": None,
        "evidence_truncated": False,
    }


def _write_lr_candidates(workspace: Path) -> None:
    (workspace / "lr_candidates.json").write_text(
        json.dumps(
            {
                "pairs": [
                    {"ligand": "ICAM1", "receptor": "MUC1"},
                    {"ligand": "FN1", "receptor": "PLAUR"},
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _issue_codes(diagnostics: dict[str, object]) -> set[str]:
    issues = diagnostics.get("issues", [])
    assert isinstance(issues, list)
    return {
        str(issue.get("code"))
        for issue in issues
        if isinstance(issue, dict)
    }


def test_harness_success_includes_mvp4_checks(tmp_path: Path) -> None:
    from src.agents.drug_target.report_harness import (
        run_deterministic_report_harness,
    )

    workspace = _copy_baseline_workspace(tmp_path)

    result = asyncio.run(run_deterministic_report_harness(_state(workspace), {}))
    diagnostics = result["report_harness_diagnostics"]
    checks = diagnostics["checks"]

    assert diagnostics["valid"] is True
    assert checks["artifact_validity"]["status"] == "pass"
    assert checks["source_consistency"]["status"] == "pass"
    assert checks["target_assessment"]["status"] == "skipped"
    assert checks["target_assessment"]["expected"] is False
    assert checks["optional_legacy_artifacts"]["status"] == "absent"
    assert checks["interpretations"]["status"] == "absent"
    assert checks["no_llm_success"]["status"] == "pass"


def test_no_llm_success_fails_when_evidence_truncated() -> None:
    from src.agents.drug_target.report_harness import _no_llm_success_check

    check = _no_llm_success_check(
        {
            "report_finalization_error": None,
            "evidence_truncated": True,
        },
        diagnostics_valid=True,
    )

    assert check["status"] == "fail"
    assert check["evidence_truncated"] is True


def test_source_hash_mismatch_after_finalization_is_flagged(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.report_harness import (
        collect_report_harness_diagnostics,
        run_deterministic_report_harness,
    )

    workspace = _copy_baseline_workspace(tmp_path)
    result = asyncio.run(run_deterministic_report_harness(_state(workspace), {}))
    assert result["report_harness_diagnostics"]["valid"] is True

    source_path = workspace / "evidence" / "assessment_results.json"
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    payload["post_finalization_mutation"] = True
    source_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    diagnostics = collect_report_harness_diagnostics(str(workspace))

    assert diagnostics["valid"] is False
    assert diagnostics["checks"]["source_consistency"]["status"] == "fail"
    assert "SOURCE_HASH_MISMATCH" in _issue_codes(diagnostics)


def test_valid_target_assessment_tracked_when_lr_candidates_exist(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.report_harness import (
        run_deterministic_report_harness,
    )

    workspace = _copy_baseline_workspace(tmp_path)
    _write_lr_candidates(workspace)

    result = asyncio.run(run_deterministic_report_harness(_state(workspace), {}))
    diagnostics = result["report_harness_diagnostics"]
    target_check = diagnostics["checks"]["target_assessment"]

    assert diagnostics["valid"] is True
    assert target_check["expected"] is True
    assert target_check["status"] == "pass"
    assert target_check["target_assessment"]["exists"] is True
    assert target_check["validation"]["valid"] is True
    assert target_check["validation"]["matrix_pair_count"] == 2


def test_optional_legacy_artifacts_presence_tracked_without_deletion(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import finalize_report_mvp
    from src.agents.drug_target.report_harness import (
        collect_report_harness_diagnostics,
    )

    workspace = _copy_baseline_workspace(tmp_path)
    result = asyncio.run(finalize_report_mvp(_state(workspace), {}))
    assert result["report_finalization_error"] is None

    optional_payloads = {
        "report_expansions.json": {"schema_version": "legacy.expansions.v1"},
        "drug_report_render.json": {"schema_version": "legacy.render.v1"},
        "report_interpretations.json": {
            "schema_version": "drug_target.report_interpretations.v1",
            "summary": {"accepted": 1, "rejected": 0},
        },
    }
    for name, payload in optional_payloads.items():
        (workspace / name).write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )

    diagnostics = collect_report_harness_diagnostics(str(workspace))
    optional_check = diagnostics["checks"]["optional_legacy_artifacts"]

    assert diagnostics["valid"] is True
    assert optional_check["status"] == "present"
    for name in optional_payloads:
        assert (workspace / name).exists()
        assert optional_check["artifacts"][name]["exists"] is True
        assert optional_check["artifacts"][name]["valid_json"] is True
    assert diagnostics["checks"]["interpretations"]["status"] == "present"
    assert diagnostics["checks"]["interpretations"]["summary"] == {
        "accepted": 1,
        "rejected": 0,
    }
