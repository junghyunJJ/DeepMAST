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
        "DEEPMAST_ENABLE_PART4_CANDIDATE_SELECTOR",
    ):
        monkeypatch.delenv(name, raising=False)


def _copy_baseline_workspace(tmp_path: Path, name: str = "workspace") -> Path:
    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "baseline_hallucinated"
    )
    workspace = tmp_path / name
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


def _accepted_selector_response(selected_genes: list[str]) -> str:
    return json.dumps(
        {
            "schema_version": "drug_target.part4_candidate_selection.v1",
            "mode": "llm_rerank",
            "selected_genes": selected_genes,
            "selection_rationales": {
                gene: f"{gene} has bounded deterministic support."
                for gene in selected_genes
            },
            "excluded_high_score_candidates": {},
            "evidence_references": ["drug.md"],
        }
    )


def _candidate_headings(markdown: str) -> list[str]:
    return [
        line.removeprefix("### Candidate: ").strip()
        for line in markdown.splitlines()
        if line.startswith("### Candidate: ")
    ]


@pytest.mark.asyncio
async def test_finalize_report_writes_disabled_selector_audit_without_provider_call(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import finalize_report_mvp
    from src.agents.drug_target.part4_candidate_selector import (
        PART4_CANDIDATE_SELECTION_FILENAME,
    )

    workspace = _copy_baseline_workspace(tmp_path)
    calls: list[str] = []

    def provider(prompt: str) -> str:
        calls.append(prompt)
        return _accepted_selector_response(["CD47", "ITGB2", "ICAM1"])

    result = await finalize_report_mvp(
        _state(workspace),
        {"configurable": {"part4_candidate_selector_provider": provider}},
    )

    assert calls == []
    assert result == {
        "report_finalization_error": None,
        "evidence_truncated": False,
    }
    payload = json.loads(
        (workspace / PART4_CANDIDATE_SELECTION_FILENAME).read_text(encoding="utf-8")
    )
    assert payload["status"] == "fallback"
    assert payload["fallback_reason"] == "disabled"
    assert payload["mode"] == "deterministic_fallback"
    assert (workspace / "part4_therapeutic_synthesis.md").exists()


@pytest.mark.asyncio
async def test_finalize_report_accepts_opt_in_selector_and_orders_part4(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import finalize_report_mvp
    from src.agents.drug_target.part4_candidate_selector import (
        PART4_CANDIDATE_SELECTION_FILENAME,
    )

    workspace = _copy_baseline_workspace(tmp_path)

    def provider(prompt: str) -> str:
        return _accepted_selector_response(["CD47", "ITGB2", "ICAM1"])

    result = await finalize_report_mvp(
        _state(workspace),
        {
            "configurable": {
                "enable_part4_candidate_selector": True,
                "part4_candidate_selector_provider": provider,
            }
        },
    )

    assert result == {
        "report_finalization_error": None,
        "evidence_truncated": False,
    }
    payload = json.loads(
        (workspace / PART4_CANDIDATE_SELECTION_FILENAME).read_text(encoding="utf-8")
    )
    assert payload["status"] == "accepted"
    assert payload["selected_genes"] == ["CD47", "ITGB2", "ICAM1"]
    assert _candidate_headings(
        (workspace / "part4_therapeutic_synthesis.md").read_text(encoding="utf-8")
    ) == ["CD47", "ITGB2", "ICAM1"]


@pytest.mark.asyncio
async def test_finalize_report_falls_back_when_selector_returns_invalid_gene(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import finalize_report_mvp
    from src.agents.drug_target.part4_candidate_selector import (
        PART4_CANDIDATE_SELECTION_FILENAME,
    )

    baseline_workspace = _copy_baseline_workspace(tmp_path, "baseline")
    baseline_result = await finalize_report_mvp(_state(baseline_workspace), {})
    assert baseline_result["report_finalization_error"] is None
    baseline_headings = _candidate_headings(
        (baseline_workspace / "part4_therapeutic_synthesis.md").read_text(
            encoding="utf-8"
        )
    )

    workspace = _copy_baseline_workspace(tmp_path, "selector_invalid")

    def provider(prompt: str) -> str:
        return _accepted_selector_response(["CXCR4", "ITGB2", "ICAM1"])

    result = await finalize_report_mvp(
        _state(workspace),
        {
            "configurable": {
                "enable_part4_candidate_selector": True,
                "part4_candidate_selector_provider": provider,
            }
        },
    )

    assert result == {
        "report_finalization_error": None,
        "evidence_truncated": False,
    }
    payload = json.loads(
        (workspace / PART4_CANDIDATE_SELECTION_FILENAME).read_text(encoding="utf-8")
    )
    assert payload["status"] == "fallback"
    assert payload["fallback_reason"] == "validation_failed"
    assert [
        issue["code"] for issue in payload["validation_issues"]
    ] == ["GENE_OUTSIDE_STAGE3_POOL"]
    assert _candidate_headings(
        (workspace / "part4_therapeutic_synthesis.md").read_text(encoding="utf-8")
    ) == baseline_headings
