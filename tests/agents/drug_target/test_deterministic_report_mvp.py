from __future__ import annotations

import asyncio
import json
import shutil
import warnings
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _clear_llm_provider_env(monkeypatch):
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


def _write_opentargets_drug_evidence(workspace: Path, gene: str = "FN1") -> None:
    evidence = workspace / "evidence"
    (evidence / f"ot_{gene}.json").write_text(
        json.dumps(
            {
                "gene_symbol": gene,
                "target_drugs": {
                    "count": 2,
                    "rows": [
                        {
                            "maxClinicalStage": 4,
                            "drug": {
                                "id": "CHEMBL2095222",
                                "name": "CHEMBL2095222",
                                "maximumClinicalStage": 4,
                            },
                            "diseases": [
                                {"disease": {"name": "macular degeneration"}},
                                {"disease": {"name": "eye disease"}},
                            ],
                        },
                        {
                            "maxClinicalStage": 1,
                            "drug": {
                                "id": "CHEMBL2109412",
                                "name": "CHEMBL2109412",
                                "maximumClinicalStage": 1,
                            },
                            "diseases": [
                                {"disease": {"name": "cancer"}},
                            ],
                        },
                    ],
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (evidence / "resolved_drugs.json").write_text(
        json.dumps(
            [
                {
                    "gene": gene,
                    "chembl_id": "CHEMBL2095222",
                    "resolved_name": "OCRIPLASMIN",
                    "molecule_type": "Enzyme",
                    "max_phase": 4,
                    "first_approval": 2012,
                    "mechanism_of_action": (
                        "Collagen hydrolytic enzyme | Fibronectin proteolytic enzyme"
                    ),
                    "source": "opentargets",
                },
                {
                    "gene": gene,
                    "chembl_id": "CHEMBL2109412",
                    "resolved_name": "L19SIP 131I",
                    "molecule_type": "Protein",
                    "max_phase": 1,
                    "first_approval": None,
                    "mechanism_of_action": "Fibronectin other",
                    "source": "opentargets",
                },
            ],
            indent=2,
        ),
        encoding="utf-8",
    )


def test_report_mvp_renders_without_llm(tmp_path: Path) -> None:
    from src.agents.drug_target.deterministic_report import finalize_report_mvp

    workspace = _copy_baseline_workspace(tmp_path)
    stale_drug_md = workspace / "drug.md"
    stale_text = stale_drug_md.read_text(encoding="utf-8")
    stale_drug_md.unlink()

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

    assert result == {
        "report_finalization_error": None,
        "evidence_truncated": False,
    }
    assert (workspace / "report_data.json").exists()
    assert (workspace / "drug.md").exists()
    assert (workspace / "drug_report.html").exists()
    assert (workspace / "part4_therapeutic_synthesis.md").exists()
    assert (workspace / "report_validation.json").exists()
    validation = json.loads(
        (workspace / "report_validation.json").read_text(encoding="utf-8")
    )
    part4_artifact = validation["artifacts"]["part4_therapeutic_synthesis.md"]
    assert part4_artifact["exists"] is True
    assert part4_artifact["size_bytes"] > 0
    self_artifact = validation["artifacts"]["report_validation.json"]
    assert self_artifact["exists"] is True
    assert "size_bytes" not in self_artifact
    assert "sha256" not in self_artifact
    rendered_text = (workspace / "drug.md").read_text(encoding="utf-8")
    assert rendered_text != stale_text
    assert "# Therapeutic Target Assessment Report" in rendered_text
    assert "## 1. Executive Summary" in rendered_text
    assert "EXPAND" not in rendered_text
    part4_text = (workspace / "part4_therapeutic_synthesis.md").read_text(
        encoding="utf-8"
    )
    assert part4_text.startswith("# Part 4: Therapeutic Synthesis")
    assert part4_text != rendered_text
    assert "## Candidate Triage" in part4_text
    assert "EXPAND" not in part4_text


def test_report_mvp_never_creates_llm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from src.agents.drug_target import deterministic_report

    workspace = _copy_baseline_workspace(tmp_path)

    def fail_create_llm(*args, **kwargs):
        raise AssertionError("deterministic report MVP must not create an LLM")

    monkeypatch.setattr(
        "src.agents.model.create_llm",
        fail_create_llm,
    )

    result = asyncio.run(
        deterministic_report.finalize_report_mvp(
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


def test_report_mvp_keeps_section_sources_deterministic(tmp_path: Path) -> None:
    from src.agents.drug_target.deterministic_report import build_report_data

    workspace = _copy_baseline_workspace(tmp_path)
    report_data = build_report_data(
        str(workspace),
        "idiopathic pulmonary fibrosis",
    )

    sections = report_data["sections"]
    assert sections["executive_summary"]["sources"] == [
        "evidence/assessment_results.json"
    ]
    assert "evidence/hypothesis_report.json" in sections["hypotheses"]["sources"]

    candidates = report_data["candidates"]
    assert candidates
    for candidate in candidates:
        assert candidate["gene"]
        assert candidate["sources"]
        assert "evidence/assessment_results.json" in candidate["sources"]


def test_report_mvp_markdown_has_required_sections(tmp_path: Path) -> None:
    from src.agents.drug_target.deterministic_report import (
        build_report_data,
        render_report_markdown,
    )

    workspace = _copy_baseline_workspace(tmp_path)
    markdown = render_report_markdown(
        build_report_data(str(workspace), "idiopathic pulmonary fibrosis")
    )

    assert "# Therapeutic Target Assessment Report" in markdown
    assert "## 1. Executive Summary" in markdown
    assert "## 2. Gene & L-R Pair Prioritization" in markdown
    assert "## 3. Featured Candidate Deep Dives" in markdown
    assert "## 4. Hypothesis-Driven Analysis" in markdown
    assert "## 5. Pipeline Execution Summary & Recommendations" in markdown
    assert "EXPAND" not in markdown


def test_report_mvp_markdown_uses_drug_target_reporting_template(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import (
        build_report_data,
        render_report_markdown,
    )

    workspace = _copy_baseline_workspace(tmp_path)
    markdown = render_report_markdown(
        build_report_data(str(workspace), "idiopathic pulmonary fibrosis")
    )

    assert "## 2. Gene & L-R Pair Prioritization" in markdown
    assert "### 2.1. Druggability Matrix" in markdown
    assert "### 2.2. Biological Interaction Filter Results" in markdown
    assert "Stage 1 Filter Criteria" in markdown
    assert "## 5. Pipeline Execution Summary & Recommendations" in markdown
    assert "<!-- EXPAND:" not in markdown


def test_report_mvp_markdown_template_path_can_be_configured(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.agents.drug_target import deterministic_report

    template_path = tmp_path / "custom_drug_report.md.j2"
    template_path.write_text(
        "# Custom configured report for {{ disease }}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DRUG_TARGET_REPORT_TEMPLATE_PATH", str(template_path))

    workspace = _copy_baseline_workspace(tmp_path)
    markdown = deterministic_report.render_report_markdown(
        deterministic_report.build_report_data(
            str(workspace),
            "idiopathic pulmonary fibrosis",
        )
    )

    assert markdown == "# Custom configured report for idiopathic pulmonary fibrosis\n"


def test_report_mvp_has_package_local_markdown_template_fallback() -> None:
    from src.agents.drug_target import deterministic_report

    fallback_path = deterministic_report._PACKAGE_MARKDOWN_TEMPLATE

    assert fallback_path.exists()
    template = fallback_path.read_text(encoding="utf-8")
    assert "## 2. Gene & L-R Pair Prioritization" in template
    assert "**Clinical Compounds (OpenTargets):**" in template


def test_report_mvp_drug_profile_renders_opentargets_clinical_table(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import (
        build_report_data,
        render_report_markdown,
    )

    workspace = _copy_baseline_workspace(tmp_path)
    _write_opentargets_drug_evidence(workspace, "FN1")

    markdown = render_report_markdown(
        build_report_data(str(workspace), "idiopathic pulmonary fibrosis")
    )
    fn1_section = markdown.split("### FN1", 1)[1].split("\n### ", 1)[0]

    assert "**Clinical Compounds (OpenTargets):**" in fn1_section
    assert "| Drug | ChEMBL ID | Mechanism of Action | Phase | Indications |" in fn1_section
    assert "| **OCRIPLASMIN** | CHEMBL2095222 | Collagen hydrolytic enzyme \\| Fibronectin proteolytic enzyme | 4 | macular degeneration, eye disease |" in fn1_section
    assert "| **L19SIP 131I** | CHEMBL2109412 | Fibronectin other | 1 | cancer |" in fn1_section
    assert "- No known drugs targeting this gene" not in fn1_section


def test_report_mvp_markdown_template_escapes_pipes_without_warning(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import (
        build_report_data,
        render_report_markdown,
    )

    workspace = _copy_baseline_workspace(tmp_path)
    _write_opentargets_drug_evidence(workspace, "FN1")
    report_data = build_report_data(
        str(workspace),
        "idiopathic pulmonary fibrosis",
    )

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        markdown = render_report_markdown(report_data)

    assert "Collagen hydrolytic enzyme \\| Fibronectin proteolytic enzyme" in markdown


def test_report_mvp_report_data_splits_clinical_and_preclinical_drugs(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import build_report_data

    workspace = _copy_baseline_workspace(tmp_path)
    _write_opentargets_drug_evidence(workspace, "FN1")

    report_data = build_report_data(
        str(workspace),
        "idiopathic pulmonary fibrosis",
    )
    fn1 = next(c for c in report_data["candidates"] if c["gene"] == "FN1")

    assert fn1["clinical_drug_count"] == 2
    assert fn1["preclinical_drug_count"] == 0
    assert fn1["drug_count"] == 2
    assert fn1["clinical_drugs"][0] == {
        "name": "OCRIPLASMIN",
        "chembl_id": "CHEMBL2095222",
        "phase": 4,
        "first_approval": 2012,
        "mechanism_of_action": (
            "Collagen hydrolytic enzyme | Fibronectin proteolytic enzyme"
        ),
        "indications": ["macular degeneration", "eye disease"],
        "source": "opentargets",
    }
    assert "evidence/ot_FN1.json" in fn1["sources"]
    assert "evidence/resolved_drugs.json" in fn1["sources"]


def test_report_mvp_dedupes_preclinical_drugs_already_clinical(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import (
        build_report_data,
        render_report_markdown,
    )

    workspace = _copy_baseline_workspace(tmp_path)
    _write_opentargets_drug_evidence(workspace, "FN1")
    (workspace / "evidence" / "stage3_FN1.json").write_text(
        json.dumps(
            {
                "gene": "FN1",
                "chembl": {
                    "matched_drugs": [
                        {
                            "chembl_id": "CHEMBL2095222",
                            "drug_name": "OCRIPLASMIN",
                            "mechanism_of_action": "duplicate ChEMBL record",
                            "indications": ["duplicate indication"],
                        },
                        {
                            "chembl_id": "CHEMBL_UNIQUE_PRECLINICAL",
                            "drug_name": "FN1 PRECLINICAL TOOL",
                            "mechanism_of_action": None,
                            "indications": [],
                        },
                    ]
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    report_data = build_report_data(
        str(workspace),
        "idiopathic pulmonary fibrosis",
    )
    fn1 = next(c for c in report_data["candidates"] if c["gene"] == "FN1")
    preclinical_ids = {drug["chembl_id"] for drug in fn1["preclinical_drugs"]}

    assert fn1["clinical_drug_count"] == 2
    assert fn1["preclinical_drug_count"] == 1
    assert "CHEMBL2095222" not in preclinical_ids
    assert "CHEMBL_UNIQUE_PRECLINICAL" in preclinical_ids

    markdown = render_report_markdown(report_data)
    fn1_section = markdown.split("### FN1", 1)[1].split("\n### ", 1)[0]
    assert fn1_section.count("CHEMBL2095222") == 1
    assert "FN1 PRECLINICAL TOOL" in fn1_section


def test_report_mvp_ignores_malformed_optional_evidence(tmp_path: Path) -> None:
    from src.agents.drug_target.deterministic_report import build_report_data

    workspace = _copy_baseline_workspace(tmp_path)
    evidence = workspace / "evidence"
    (evidence / "resolved_drugs.json").write_text("{", encoding="utf-8")
    (evidence / "ot_FN1.json").write_text("{", encoding="utf-8")
    (evidence / "stage3_FN1.json").write_text("{", encoding="utf-8")
    (evidence / "stage1_evidence.json").write_text("{", encoding="utf-8")

    report_data = build_report_data(
        str(workspace),
        "idiopathic pulmonary fibrosis",
    )
    fn1 = next(c for c in report_data["candidates"] if c["gene"] == "FN1")

    assert report_data["valid"] is True
    assert fn1["clinical_drug_count"] == 0
    assert fn1["preclinical_drug_count"] == 0
    assert "evidence/ot_FN1.json" in fn1["sources"]
    assert "evidence/stage3_FN1.json" in fn1["sources"]
    assert "evidence/resolved_drugs.json" not in fn1["sources"]


def test_report_mvp_resolved_drugs_source_requires_used_enrichment(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import build_report_data

    workspace = _copy_baseline_workspace(tmp_path)
    _write_opentargets_drug_evidence(workspace, "FN1")
    resolved_path = workspace / "evidence" / "resolved_drugs.json"
    resolved_path.write_text(
        json.dumps(
            [
                {
                    "gene": "FN1",
                    "chembl_id": "CHEMBL_DOES_NOT_MATCH",
                    "resolved_name": "Unused enrichment",
                }
            ]
        ),
        encoding="utf-8",
    )

    report_data = build_report_data(
        str(workspace),
        "idiopathic pulmonary fibrosis",
    )
    fn1 = next(c for c in report_data["candidates"] if c["gene"] == "FN1")

    assert fn1["clinical_drug_count"] == 2
    assert "evidence/ot_FN1.json" in fn1["sources"]
    assert "evidence/resolved_drugs.json" not in fn1["sources"]


def test_report_mvp_does_not_write_legacy_expansions(tmp_path: Path) -> None:
    from src.agents.drug_target.deterministic_report import finalize_report_mvp

    workspace = _copy_baseline_workspace(tmp_path)
    asyncio.run(
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

    assert not (workspace / "report_expansions.json").exists()
    assert not (workspace / "report_interpretations.json").exists()


def test_report_mvp_validation_fails_without_assessment_results(tmp_path: Path) -> None:
    from src.agents.drug_target.deterministic_report import finalize_report_mvp

    workspace = _copy_baseline_workspace(tmp_path)
    (workspace / "evidence" / "assessment_results.json").unlink()

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
    self_artifact = validation["artifacts"]["report_validation.json"]
    assert self_artifact["exists"] is True
    assert "size_bytes" not in self_artifact
    assert "sha256" not in self_artifact


@pytest.mark.parametrize(
    "filename",
    [
        "assessment_results.json",
        "hypothesis_report.json",
    ],
)
def test_report_mvp_validation_fails_for_malformed_required_json(
    tmp_path: Path,
    filename: str,
) -> None:
    from src.agents.drug_target.deterministic_report import finalize_report_mvp

    workspace = _copy_baseline_workspace(tmp_path)
    (workspace / "evidence" / filename).write_text("{", encoding="utf-8")

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
        issue["code"] == "INVALID_REQUIRED_EVIDENCE_JSON"
        and issue["path"] == f"evidence/{filename}"
        for issue in validation["issues"]
    )
