from __future__ import annotations

import re
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


def _normalized_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


_FORBIDDEN_CLINICAL_PHRASES = (
    "should treat",
    "recommended therapy",
    "clinical ready",
    "standard of care",
    "patients should",
)


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


def test_part4_synthesis_does_not_reuse_drug_report_sections_verbatim(
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
    normalized_markdown = _normalized_text(markdown)
    normalized_source = _normalized_text(source_drug_md)

    assert "## 1. Executive Summary" not in markdown
    assert "## 2. Target Druggability Matrix" not in markdown
    assert "## 3. Candidate Deep Dives" not in markdown
    assert "## 4. Mechanistic Hypotheses" not in markdown
    for snippet in (
        "This report presents a comprehensive therapeutic target assessment "
        "for **pulmonary fibrosis** based on spatial transcriptomics "
        "cell-cell interaction (CCI) analysis.",
        "All seven featured candidates achieved validated_target "
        "classification with high priority, indicating substantial clinical "
        "evidence and strong therapeutic potential.",
        "The druggability matrix reveals a clear stratification of "
        "therapeutic targets across validated and exploratory evidence tracks.",
        "CD4 achieves the maximum validated_total score of 10, driven by "
        "strong existing drug evidence (5) and clinical trial activity (5), "
        "reflecting extensive clinical development of CD4-targeted therapeutics.",
    ):
        assert snippet in normalized_source
        assert snippet not in normalized_markdown


def test_part4_synthesis_uses_experimental_not_clinical_language(
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

    markdown = render_part4_therapeutic_synthesis_markdown(synthesis).lower()

    for phrase in _FORBIDDEN_CLINICAL_PHRASES:
        assert phrase not in markdown
    assert "experimental prioritization" in markdown


def test_render_part4_synthesis_scrubs_clinical_drift_from_hypotheses(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import build_report_data
    from src.agents.drug_target.therapeutic_synthesis import (
        build_part4_therapeutic_synthesis,
        render_part4_therapeutic_synthesis_markdown,
    )

    workspace = _copy_baseline_workspace(tmp_path)
    report_data = build_report_data(str(workspace), "idiopathic pulmonary fibrosis")
    report_data["hypotheses"] = [
        {
            "rank": 1,
            "title": "Synthetic hypothesis that says should treat",
            "category": "Therapeutic Strategy",
            "biological_entities": {"genes": ["CD4"], "drugs": []},
            "validation_approach": (
                "Synthetic coverage text says patients should receive the "
                "recommended therapy as standard of care because the "
                "candidate is clinical ready."
            ),
            "evidence_references": ["evidence/hypothesis_report.json"],
        }
    ]

    synthesis = build_part4_therapeutic_synthesis(
        report_data,
        validation=_validation_payload(),
        interpretations_payload=None,
    )
    markdown = render_part4_therapeutic_synthesis_markdown(synthesis)

    assert "should treat" not in markdown.lower()
    assert "patients should" not in markdown.lower()
    assert "recommended therapy" not in markdown.lower()
    assert "clinical ready" not in markdown.lower()
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
