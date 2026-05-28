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


def _accepted_selector_payload(selected_genes: list[str]) -> dict[str, object]:
    return {
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


def _candidate_headings(markdown: str) -> list[str]:
    return [
        line.split(". Candidate: ", 1)[1].strip()
        for line in markdown.splitlines()
        if line.startswith("### ") and ". Candidate: " in line
    ]


@pytest.mark.asyncio
async def test_finalize_report_uses_selector_provider_by_default(
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

    assert len(calls) == 1
    assert result == {
        "report_finalization_error": None,
        "evidence_truncated": False,
    }
    payload = json.loads(
        (workspace / PART4_CANDIDATE_SELECTION_FILENAME).read_text(encoding="utf-8")
    )
    assert payload["status"] == "accepted"
    assert payload["fallback_reason"] is None
    assert payload["mode"] == "llm_rerank"
    assert payload["selected_genes"] == ["CD47", "ITGB2", "ICAM1"]
    assert _candidate_headings(
        (workspace / "part4_therapeutic_synthesis.md").read_text(encoding="utf-8")
    ) == ["CD47", "ITGB2", "ICAM1"]


@pytest.mark.asyncio
async def test_finalize_report_respects_explicit_disabled_selector(
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
        {
            "configurable": {
                "enable_part4_candidate_selector": False,
                "part4_candidate_selector_provider": provider,
            }
        },
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
async def test_finalize_report_respects_env_disabled_selector_with_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.drug_target.deterministic_report import finalize_report_mvp
    from src.agents.drug_target.part4_candidate_selector import (
        ENABLE_PART4_CANDIDATE_SELECTOR_ENV,
        PART4_CANDIDATE_SELECTION_FILENAME,
    )

    monkeypatch.setenv(ENABLE_PART4_CANDIDATE_SELECTOR_ENV, "false")
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
@pytest.mark.parametrize(
    ("provider_output", "expected_issue_code", "invalid_selected_genes"),
    [
        pytest.param(
            "not json",
            "MALFORMED_JSON",
            [],
            id="malformed_json",
        ),
        pytest.param(
            json.dumps(
                _accepted_selector_payload(["CXCR4", "ITGB2", "ICAM1"])
            ),
            "GENE_OUTSIDE_STAGE3_POOL",
            ["CXCR4", "ITGB2", "ICAM1"],
            id="gene_outside_stage3_pool",
        ),
        pytest.param(
            json.dumps(_accepted_selector_payload(["CD47", "ITGB2"])),
            "INVALID_SELECTED_GENE_COUNT",
            ["CD47", "ITGB2"],
            id="invalid_selected_gene_count",
        ),
        pytest.param(
            json.dumps(_accepted_selector_payload(["CD47", "ITGB2", "CD47"])),
            "DUPLICATE_SELECTED_GENE",
            ["CD47", "ITGB2", "CD47"],
            id="duplicate_selected_gene",
        ),
        pytest.param(
            json.dumps(
                {
                    **_accepted_selector_payload(["CD47", "ITGB2", "ICAM1"]),
                    "selection_rationales": {
                        "CD47": "Patients should receive this target.",
                        "ITGB2": "ITGB2 has bounded deterministic support.",
                        "ICAM1": "ICAM1 has bounded deterministic support.",
                    },
                }
            ),
            "CLINICAL_RECOMMENDATION_LANGUAGE",
            ["CD47", "ITGB2", "ICAM1"],
            id="clinical_recommendation_language",
        ),
        pytest.param(
            json.dumps(
                {
                    **_accepted_selector_payload(["CD47", "ITGB2", "ICAM1"]),
                    "selection_rationales": {
                        "CD47": "x" * 501,
                        "ITGB2": "ITGB2 has bounded deterministic support.",
                        "ICAM1": "ICAM1 has bounded deterministic support.",
                    },
                }
            ),
            "RATIONALE_TOO_LONG",
            ["CD47", "ITGB2", "ICAM1"],
            id="rationale_too_long",
        ),
    ],
)
async def test_finalize_report_invalid_selector_outputs_fallback(
    tmp_path: Path,
    provider_output: str,
    expected_issue_code: str,
    invalid_selected_genes: list[str],
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
        return provider_output

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
    assert expected_issue_code in {
        issue["code"] for issue in payload["validation_issues"]
    }
    assert payload["selected_genes"] == baseline_headings
    if len(invalid_selected_genes) == 3:
        assert payload["selected_genes"] != invalid_selected_genes
    synthesis_path = workspace / "part4_therapeutic_synthesis.md"
    assert synthesis_path.exists()
    assert _candidate_headings(
        synthesis_path.read_text(encoding="utf-8")
    ) == baseline_headings
