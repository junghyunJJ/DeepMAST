from __future__ import annotations

import shutil
from pathlib import Path


def _copy_baseline_workspace(tmp_path: Path) -> Path:
    fixture = Path(__file__).resolve().parent / "fixtures" / "baseline_hallucinated"
    workspace = tmp_path / "workspace"
    shutil.copytree(fixture, workspace)
    return workspace


def _validation_payload(valid: bool = True) -> dict:
    return {
        "schema_version": "drug_target.report_validation.v1",
        "valid": valid,
        "issues": []
        if valid
        else [
            {
                "code": "TEST_INVALID_ARTIFACT",
                "severity": "warning",
                "message": "Synthetic invalid metadata for renderer coverage",
            }
        ],
        "artifacts": {
            "drug.md": {"exists": True},
            "report_data.json": {"exists": True},
        },
    }


def test_part4_synthesis_data_prioritizes_featured_candidates(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import build_report_data
    from src.agents.drug_target.therapeutic_synthesis import (
        build_part4_therapeutic_synthesis,
    )

    workspace = _copy_baseline_workspace(tmp_path)
    report_data = build_report_data(str(workspace), "idiopathic pulmonary fibrosis")

    synthesis = build_part4_therapeutic_synthesis(
        report_data,
        validation=_validation_payload(),
        interpretations_payload={
            "summary": {
                "accepted": 2,
                "rejected": 1,
                "missing": 3,
                "provider_errors": 0,
                "criteria_met": False,
            }
        },
    )

    assert synthesis["schema_version"] == "drug_target.part4_therapeutic_synthesis.v1"
    assert synthesis["disease"] == "idiopathic pulmonary fibrosis"
    assert synthesis["report_valid"] is True
    assert synthesis["interpretation_summary"]["accepted"] == 2
    assert [item["gene"] for item in synthesis["featured_candidates"][:3]] == [
        "CD4",
        "FN1",
        "MUC1",
    ]
    assert synthesis["candidate_counts"]["featured"] == 3
    assert synthesis["candidate_counts"]["total"] >= 3
    assert synthesis["hypotheses"]


def test_render_part4_synthesis_markdown_is_not_drug_md_copy(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import build_report_data
    from src.agents.drug_target.therapeutic_synthesis import (
        build_part4_therapeutic_synthesis,
        render_part4_therapeutic_synthesis_markdown,
    )

    workspace = _copy_baseline_workspace(tmp_path)
    report_data = build_report_data(str(workspace), "idiopathic pulmonary fibrosis")
    synthesis = build_part4_therapeutic_synthesis(
        report_data,
        validation=_validation_payload(),
        interpretations_payload=None,
    )

    markdown = render_part4_therapeutic_synthesis_markdown(synthesis)
    source_drug_md = (workspace / "drug.md").read_text(encoding="utf-8")

    assert markdown != source_drug_md
    assert markdown.startswith("# Part 4: Therapeutic Synthesis")
    assert "## Therapeutic Opportunity Landscape" in markdown
    assert "## Candidate Triage" in markdown
    assert "## Hypothesis-to-Intervention Map" in markdown
    assert "## Validation Next Steps" in markdown
    assert "## Confidence and Caveats" in markdown
    assert "CD4" in markdown
    assert "FN1" in markdown
    assert "MUC1" in markdown
    assert "validated_target" in markdown
    assert "EXPAND" not in markdown
    assert "recommended therapy" not in markdown.lower()
    assert "standard of care" not in markdown.lower()


def test_render_part4_synthesis_handles_invalid_validation_metadata(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import build_report_data
    from src.agents.drug_target.therapeutic_synthesis import (
        build_part4_therapeutic_synthesis,
        render_part4_therapeutic_synthesis_markdown,
    )

    workspace = _copy_baseline_workspace(tmp_path)
    report_data = build_report_data(str(workspace), "idiopathic pulmonary fibrosis")

    synthesis = build_part4_therapeutic_synthesis(
        report_data,
        validation=_validation_payload(valid=False),
        interpretations_payload=None,
    )
    markdown = render_part4_therapeutic_synthesis_markdown(synthesis)

    assert synthesis["report_valid"] is False
    assert "report validation status is invalid" in markdown.lower()
    assert "TEST_INVALID_ARTIFACT" in markdown
