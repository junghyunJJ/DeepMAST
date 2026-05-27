from __future__ import annotations

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


def _state(workspace: Path) -> dict:
    return {
        "data_dir": str(workspace),
        "disease": "idiopathic pulmonary fibrosis",
        "messages": [],
        "featured_lr_pairs": None,
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


@pytest.mark.asyncio
async def test_finalize_report_uses_deterministic_mvp_without_llm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.drug_target.finalize_report import finalize_report

    workspace = _copy_baseline_workspace(tmp_path)

    def fail_create_llm(*args, **kwargs):
        raise AssertionError("production finalize_report must not create an LLM")

    monkeypatch.setattr("src.agents.model.create_llm", fail_create_llm)

    result = await finalize_report(_state(workspace), {})

    assert result == {
        "report_finalization_error": None,
        "evidence_truncated": False,
    }
    assert (workspace / "report_data.json").exists()
    assert (workspace / "drug.md").exists()
    assert (workspace / "drug_report.html").exists()
    assert (workspace / "part4_therapeutic_synthesis.md").exists()
    assert (workspace / "report_validation.json").exists()
    assert not (workspace / "report_expansions.json").exists()
    assert not (workspace / "report_interpretations.json").exists()
    assert "EXPAND" not in (workspace / "drug.md").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_finalize_report_mvp_does_not_call_interpretation_provider_by_default(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import finalize_report_mvp

    workspace = _copy_baseline_workspace(tmp_path)

    def fail_provider(card):
        raise AssertionError(f"provider must not be called: {card['id']}")

    result = await finalize_report_mvp(
        _state(workspace),
        {"configurable": {"report_interpretation_provider": fail_provider}},
    )

    assert result == {
        "report_finalization_error": None,
        "evidence_truncated": False,
    }
    assert not (workspace / "report_interpretations.json").exists()


@pytest.mark.asyncio
async def test_finalize_report_mvp_writes_accepted_interpretations_when_enabled(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import finalize_report_mvp

    workspace = _copy_baseline_workspace(tmp_path)
    accepted_text = (
        "FN1 anchors a deterministic opportunity in the 41-gene assessment."
    )

    def provider(card):
        if card["id"] == "executive_summary.opportunities":
            return accepted_text
        return ""

    result = await finalize_report_mvp(
        _state(workspace),
        {
            "configurable": {
                "enable_report_interpretations": True,
                "report_interpretation_provider": provider,
            }
        },
    )

    assert result == {
        "report_finalization_error": None,
        "evidence_truncated": False,
    }
    payload = json.loads(
        (workspace / "report_interpretations.json").read_text(encoding="utf-8")
    )
    assert payload["enabled"] is True
    assert payload["summary"]["accepted"] >= 1
    assert accepted_text in (workspace / "drug.md").read_text(encoding="utf-8")
    part4_text = (workspace / "part4_therapeutic_synthesis.md").read_text(
        encoding="utf-8"
    )
    assert f"accepted={payload['summary']['accepted']}" in part4_text


@pytest.mark.asyncio
async def test_finalize_report_mvp_rejects_invalid_interpretation_and_still_succeeds(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import finalize_report_mvp

    workspace = _copy_baseline_workspace(tmp_path)
    invalid_text = (
        "NINTEDANIB improves 99% outcomes through TGFB2 according to "
        "fabricated.json."
    )

    def provider(card):
        if card["id"] == "executive_summary.opportunities":
            return invalid_text
        return ""

    result = await finalize_report_mvp(
        _state(workspace),
        {
            "configurable": {
                "enable_report_interpretations": True,
                "report_interpretation_provider": provider,
            }
        },
    )

    assert result == {
        "report_finalization_error": None,
        "evidence_truncated": False,
    }
    payload = json.loads(
        (workspace / "report_interpretations.json").read_text(encoding="utf-8")
    )
    assert payload["summary"]["rejected"] >= 1
    assert invalid_text not in (workspace / "drug.md").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_finalize_report_mvp_writes_repaired_interpretation_when_retry_succeeds(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import finalize_report_mvp

    workspace = _copy_baseline_workspace(tmp_path)
    repaired_text = "Stage 1 biological validation keeps FN1 grounded."
    calls = []

    def provider(card):
        if card["id"] != "stage1_filter.interpretation":
            return ""
        calls.append(card)
        if "repair_context" in card:
            return repaired_text
        return "Stage 9 biological validation keeps FN1 grounded."

    result = await finalize_report_mvp(
        _state(workspace),
        {
            "configurable": {
                "enable_report_interpretations": True,
                "report_interpretation_provider": provider,
            }
        },
    )

    assert result == {
        "report_finalization_error": None,
        "evidence_truncated": False,
    }
    payload = json.loads(
        (workspace / "report_interpretations.json").read_text(encoding="utf-8")
    )
    snippet = payload["snippets"]["stage1_filter.interpretation"]
    assert snippet["status"] == "accepted"
    assert snippet["attempts"] == 2
    assert payload["summary"]["accepted"] == 1
    assert len(calls) == 2
    markdown = (workspace / "drug.md").read_text(encoding="utf-8")
    assert "Stage 9" not in markdown
    assert repaired_text in markdown


@pytest.mark.asyncio
async def test_finalize_report_writes_target_assessment_for_fresh_workspace(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.finalize_report import finalize_report
    from src.agents.drug_target.tools.assessment_output import (
        validate_target_assessment_file,
    )

    workspace = _copy_baseline_workspace(tmp_path)
    _write_lr_candidates(workspace)
    assert not (workspace / "target_assessment.json").exists()

    result = await finalize_report(_state(workspace), {})

    assert result == {
        "report_finalization_error": None,
        "evidence_truncated": False,
    }
    validation = validate_target_assessment_file(workspace)
    assert validation["valid"], validation["errors"]
    assert validation["matrix_pair_count"] == 2


@pytest.mark.asyncio
async def test_finalize_report_preserves_deterministic_failure_envelope(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.finalize_report import finalize_report

    workspace = _copy_baseline_workspace(tmp_path)
    (workspace / "evidence" / "assessment_results.json").unlink()

    result = await finalize_report(_state(workspace), {})

    assert result["evidence_truncated"] is False
    assert result["report_finalization_error"].startswith(
        "deterministic_report_validation_failed:"
    )
    assert not (workspace / "part4_therapeutic_synthesis.md").exists()

    validation = json.loads(
        (workspace / "report_validation.json").read_text(encoding="utf-8")
    )
    assert validation["valid"] is False
    assert any(
        issue["code"] == "MISSING_REQUIRED_EVIDENCE"
        for issue in validation["issues"]
    )
