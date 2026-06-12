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


def _stage1_pair_payload(
    ligand: str,
    receptor: str,
    *,
    passed: bool,
    string_score: float,
    gene_a_rr: float,
    gene_b_rr: float,
    coexpr_rr: float,
    coexpr_p: float = 0.0,
    resolved_celltype: str = "pulmonary alveolar type 2 cell",
) -> dict:
    return {
        "ligand": ligand,
        "receptor": receptor,
        "string_ppi": {
            "interaction_found": True,
            "max_combined_score": string_score,
        },
        "census_validation": {
            "resolved_cell_type": resolved_celltype,
            "target_vs_rest": {
                "gene_a": {
                    "risk_ratio": gene_a_rr,
                    "diff": gene_a_rr - 1.0,
                    "p_value": 0.0,
                },
                "gene_b": {
                    "risk_ratio": gene_b_rr,
                    "diff": gene_b_rr - 1.0,
                    "p_value": 0.0,
                },
                "coexpression": {
                    "risk_ratio": coexpr_rr,
                    "diff": coexpr_rr - 1.0,
                    "p_value": coexpr_p,
                },
            },
        },
        "stage1_filter": {
            "passed": passed,
            "string_combined": string_score,
        },
    }


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
    assert (workspace / "drug_report_render.json").exists()
    assert (workspace / "part4_therapeutic_synthesis.md").exists()
    assert (workspace / "report_validation.json").exists()
    validation = json.loads(
        (workspace / "report_validation.json").read_text(encoding="utf-8")
    )
    render_artifact = validation["artifacts"]["drug_report_render.json"]
    assert render_artifact["exists"] is True
    assert render_artifact["size_bytes"] > 0
    render_metadata = json.loads(
        (workspace / "drug_report_render.json").read_text(encoding="utf-8")
    )
    assert render_metadata["schema_version"] == "drug_report_render.v1"
    assert render_metadata["mode"] == "deterministic"
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
    assert "## Integrated Therapeutic Thesis" in part4_text
    assert "## Prioritized Candidates" in part4_text
    assert "## Mechanistic Intervention Map" in part4_text
    assert "- Evidence summary:" in part4_text
    assert "- Therapeutic interpretation:" in part4_text
    assert "- Main uncertainty:" in part4_text
    assert "- Falsifiable prediction:" in part4_text
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


def test_report_mvp_defaults_absent_gwas_audit_fields(tmp_path: Path) -> None:
    from src.agents.drug_target.deterministic_report import build_report_data

    workspace = _copy_baseline_workspace(tmp_path)
    report_data = build_report_data(
        str(workspace),
        "idiopathic pulmonary fibrosis",
    )

    candidate = report_data["candidates"][0]
    assert candidate["scores"]["gwas_evidence_type"] == "none"
    assert candidate["scores"]["gwas_min_pvalue"] is None
    assert candidate["scores"]["gwas_trait_match_level"] == "none"
    assert candidate["scores"]["gwas_direct_hit_count"] == 0
    assert candidate["scores"]["gwas_proximity_hit_count"] == 0


def test_report_mvp_defaults_absent_biological_audit_fields(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import build_report_data

    workspace = _copy_baseline_workspace(tmp_path)
    report_data = build_report_data(
        str(workspace),
        "idiopathic pulmonary fibrosis",
    )

    candidate = report_data["candidates"][0]
    assert candidate["scores"]["biological_basis"] == "none"
    assert candidate["scores"]["biological_evidence_types"] == ""
    assert candidate["scores"]["biological_evidence_count"] == 0
    assert candidate["scores"]["biological_max_ot_score"] is None
    assert candidate["scores"]["vep_high_impact_count"] == 0
    assert candidate["scores"]["stage1_support_pair_count"] == 0
    assert candidate["scores"]["stage1_support_pairs"] == ""


def test_report_mvp_defaults_absent_stage1_audit_fields(tmp_path: Path) -> None:
    from src.agents.drug_target.deterministic_report import build_report_data

    workspace = _copy_baseline_workspace(tmp_path)
    report_data = build_report_data(
        str(workspace),
        "idiopathic pulmonary fibrosis",
    )

    candidate = report_data["candidates"][0]
    assert candidate["scores"]["stage1_gate_status"] == "not_evaluated"
    assert candidate["scores"]["stage1_total_pair_count"] == 0
    assert candidate["scores"]["stage1_passed_pair_count"] == 0
    assert candidate["scores"]["stage1_failed_pair_count"] == 0
    assert candidate["scores"]["stage1_best_pair"] == ""
    assert candidate["scores"]["stage1_best_string_combined"] is None
    assert candidate["scores"]["stage1_best_coexpr_pvalue"] is None
    assert candidate["scores"]["stage1_best_gene_a_pvalue"] is None
    assert candidate["scores"]["stage1_best_gene_b_pvalue"] is None
    assert candidate["scores"]["stage1_source"] == "none"


def test_report_mvp_defaults_absent_tractability_safety_audit_fields(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import build_report_data

    workspace = _copy_baseline_workspace(tmp_path)
    report_data = build_report_data(
        str(workspace),
        "idiopathic pulmonary fibrosis",
    )

    candidate = report_data["candidates"][0]
    assert candidate["scores"]["tractability_basis"] == "unknown"
    assert candidate["scores"]["tractability_modalities"] == ""
    assert candidate["scores"]["tractability_evidence_label"] == "none"
    assert candidate["scores"]["safety_evidence_level"] == "no_known_liability"
    assert candidate["scores"]["safety_liability_count"] == 0
    assert candidate["scores"]["safety_liability_sources"] == ""


def test_report_mvp_defaults_absent_novelty_audit_fields(tmp_path: Path) -> None:
    from src.agents.drug_target.deterministic_report import build_report_data

    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "assessment_results.json").write_text(
        json.dumps(
            {
                "rubric_assessment": [
                    {
                        "gene": "CD4",
                        "novelty_opportunity": 5,
                        "classification": "novel_candidate",
                        "priority": "medium",
                        "stage3_candidate": True,
                    }
                ],
                "stage3_candidates": [{"gene": "CD4"}],
            }
        ),
        encoding="utf-8",
    )
    (evidence_dir / "hypothesis_report.json").write_text(
        json.dumps({"hypotheses": []}),
        encoding="utf-8",
    )
    (evidence_dir / "ot_CD4.json").write_text(
        json.dumps({"gene_symbol": "CD4", "executed": True}),
        encoding="utf-8",
    )

    report = build_report_data(str(tmp_path), disease="test disease")
    candidate = report["candidates"][0]
    assert candidate["scores"]["novelty_basis"] == "st_only_or_brand_new_target"
    assert candidate["scores"]["novelty_association_count"] == 0
    assert candidate["scores"]["novelty_target_drug_count"] == 0
    assert candidate["scores"]["novelty_bucket"] == "0-9 associations"
    assert candidate["scores"]["novelty_source"] == "list_length"


def test_report_mvp_defaults_legacy_rank_scores_from_totals(tmp_path: Path) -> None:
    from src.agents.drug_target.deterministic_report import build_report_data

    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "assessment_results.json").write_text(
        json.dumps(
            {
                "rubric_assessment": [
                    {
                        "gene": "CD4",
                        "classification": "validated_target",
                        "priority": "high",
                        "validated_total": 6,
                        "exploratory_total": 10,
                        "combined_total": 16,
                        "stage3_candidate": True,
                    }
                ],
                "stage3_candidates": [{"gene": "CD4"}],
            }
        ),
        encoding="utf-8",
    )
    (evidence_dir / "hypothesis_report.json").write_text(
        json.dumps({"hypotheses": []}),
        encoding="utf-8",
    )

    report = build_report_data(str(tmp_path), disease="test disease")

    scores = report["candidates"][0]["scores"]
    assert scores["exploratory_rank_total"] == 10
    assert scores["combined_rank_score"] == 16


def test_target_assessment_inputs_defaults_absent_gwas_audit_fields() -> None:
    from src.agents.drug_target.deterministic_report import _target_assessment_inputs

    rubric_by_gene, _, _ = _target_assessment_inputs(
        {
            "candidates": [
                {
                    "gene": "CD4",
                    "scores": {
                        "gwas_support": 0,
                    },
                }
            ]
        }
    )

    cd4 = rubric_by_gene["CD4"]
    assert cd4["gwas_evidence_type"] == "none"
    assert cd4["gwas_min_pvalue"] is None
    assert cd4["gwas_trait_match_level"] == "none"
    assert cd4["gwas_direct_hit_count"] == 0
    assert cd4["gwas_proximity_hit_count"] == 0


def test_target_assessment_inputs_defaults_absent_biological_audit_fields() -> None:
    from src.agents.drug_target.deterministic_report import _target_assessment_inputs

    rubric_by_gene, _, _ = _target_assessment_inputs(
        {
            "candidates": [
                {
                    "gene": "CD4",
                    "scores": {
                        "biological_plausibility": 0,
                    },
                }
            ]
        }
    )

    cd4 = rubric_by_gene["CD4"]
    assert cd4["biological_basis"] == "none"
    assert cd4["biological_evidence_types"] == ""
    assert cd4["biological_evidence_count"] == 0
    assert cd4["biological_max_ot_score"] is None
    assert cd4["vep_high_impact_count"] == 0
    assert cd4["stage1_support_pair_count"] == 0
    assert cd4["stage1_support_pairs"] == ""


def test_target_assessment_inputs_defaults_absent_stage1_audit_fields() -> None:
    from src.agents.drug_target.deterministic_report import _target_assessment_inputs

    rubric_by_gene, _, _ = _target_assessment_inputs(
        {
            "candidates": [
                {
                    "gene": "CD4",
                    "scores": {
                        "biological_plausibility": 0,
                    },
                }
            ]
        }
    )

    cd4 = rubric_by_gene["CD4"]
    assert cd4["stage1_gate_status"] == "not_evaluated"
    assert cd4["stage1_total_pair_count"] == 0
    assert cd4["stage1_passed_pair_count"] == 0
    assert cd4["stage1_failed_pair_count"] == 0
    assert cd4["stage1_best_pair"] == ""
    assert cd4["stage1_best_string_combined"] is None
    assert cd4["stage1_best_coexpr_pvalue"] is None
    assert cd4["stage1_best_gene_a_pvalue"] is None
    assert cd4["stage1_best_gene_b_pvalue"] is None
    assert cd4["stage1_source"] == "none"


def test_target_assessment_inputs_defaults_absent_tractability_safety_audit_fields() -> None:
    from src.agents.drug_target.deterministic_report import _target_assessment_inputs

    rubric_by_gene, _, _ = _target_assessment_inputs(
        {"candidates": [{"gene": "CD4", "scores": {}}]}
    )

    cd4 = rubric_by_gene["CD4"]
    assert cd4["tractability_basis"] == "unknown"
    assert cd4["tractability_modalities"] == ""
    assert cd4["tractability_evidence_label"] == "none"
    assert cd4["safety_evidence_level"] == "no_known_liability"
    assert cd4["safety_liability_count"] == 0
    assert cd4["safety_liability_sources"] == ""


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
    assert "## 4. Evidence-Grounded Follow-up Recommendations" in markdown
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


def test_report_mvp_renders_stage1_biological_context_table_with_spatial_note() -> None:
    from src.agents.drug_target.deterministic_report import render_report_markdown

    report_data = {
        "disease": "idiopathic pulmonary fibrosis",
        "candidates": [
            {
                "gene": "FN1",
                "classification": "exploratory_target",
                "priority": "high",
                "stage3_candidate": True,
                "scores": {"combined_total": 12, "combined_rank_score": 12},
                "clinical_drugs": [],
                "preclinical_drugs": [],
            }
        ],
        "template_context": {
            "stage1_filter_results": [
                {"ligand": "FN1", "receptor": "MUC1", "passed": True},
                {"ligand": "FN1", "receptor": "SDC2", "passed": True},
                {"ligand": "FN1", "receptor": "PLAUR", "passed": False},
            ],
            "stage1_pairs": {
                "FN1_MUC1": _stage1_pair_payload(
                    "FN1",
                    "MUC1",
                    passed=True,
                    string_score=0.993,
                    gene_a_rr=3.36,
                    gene_b_rr=9.83,
                    coexpr_rr=17.86,
                ),
                "FN1_SDC2": _stage1_pair_payload(
                    "FN1",
                    "SDC2",
                    passed=True,
                    string_score=0.959,
                    gene_a_rr=0.24,
                    gene_b_rr=0.31,
                    coexpr_rr=0.2258,
                ),
                "FN1_PLAUR": _stage1_pair_payload(
                    "FN1",
                    "PLAUR",
                    passed=False,
                    string_score=0.697,
                    gene_a_rr=0.24,
                    gene_b_rr=0.40,
                    coexpr_rr=0.1557,
                ),
            },
            "hypothesis_data": {"hypotheses": []},
        },
    }

    markdown = render_report_markdown(report_data)
    fn1_section = markdown.split("### FN1", 1)[1].split("\n### ", 1)[0]

    assert (
        "| Pair | Stage 1 / STRING | Census coexpression in pulmonary alveolar type 2 cell |"
        in fn1_section
    )
    assert (
        "| **FN1-MUC1** | PASS; STRING=0.993; confirmed | RR=17.86, p=0.0; enriched | FN1 enriched; MUC1 enriched |"
        in fn1_section
    )
    assert "Primary AT2-intrinsic support" in fn1_section
    assert (
        "| **FN1-SDC2** | PASS; STRING=0.959; confirmed | RR=0.2258, p=0.0; depleted | FN1 depleted; SDC2 depleted |"
        in fn1_section
    )
    assert "Cross-cell/non-AT2 framing only" in fn1_section
    assert (
        "| **FN1-PLAUR** | FAIL; STRING=0.697; confirmed | RR=0.1557, p=0.0; depleted | FN1 depleted; PLAUR depleted |"
        in fn1_section
    )
    assert "Negative/contrast only" in fn1_section
    assert (
        "**Spatial context:** All ligand-receptor pairs listed above originated from significant LIANA+ spatial co-localization results"
        in fn1_section
    )
    assert "Moran" not in fn1_section


def test_report_mvp_splits_hypotheses_by_epithelial_intrinsic_support() -> None:
    from src.agents.drug_target.deterministic_report import render_report_markdown

    report_data = {
        "disease": "idiopathic pulmonary fibrosis",
        "candidates": [
            {
                "gene": "ICAM1",
                "classification": "exploratory_target",
                "priority": "high",
                "stage3_candidate": True,
                "scores": {"combined_total": 12, "combined_rank_score": 12},
                "clinical_drugs": [],
                "preclinical_drugs": [],
            }
        ],
        "template_context": {
            "stage1_filter_results": [
                {"ligand": "ICAM1", "receptor": "MUC1", "passed": True},
                {"ligand": "FN1", "receptor": "SDC2", "passed": True},
            ],
            "stage1_pairs": {
                "ICAM1_MUC1": _stage1_pair_payload(
                    "ICAM1",
                    "MUC1",
                    passed=True,
                    string_score=0.993,
                    gene_a_rr=3.36,
                    gene_b_rr=9.83,
                    coexpr_rr=17.86,
                ),
                "FN1_SDC2": _stage1_pair_payload(
                    "FN1",
                    "SDC2",
                    passed=True,
                    string_score=0.959,
                    gene_a_rr=0.24,
                    gene_b_rr=0.31,
                    coexpr_rr=0.2258,
                ),
            },
            "hypothesis_data": {
                "evidence_coverage_pct": 80.0,
                "hypotheses_generated": 2,
                "hypotheses_retained": 2,
                "gap_analysis": {
                    "referenced_files": 3,
                    "total_evidence_files": 5,
                    "orphan_files": [
                        "stage1_FN1--SDC2.json",
                        "stage1_ICAM1--PECAM1.json",
                    ],
                },
                "hypotheses": [
                    {
                        "rank": 1,
                        "title": "FN1-SDC2 spatial-niche follow-up candidate",
                        "category": "Mechanism of Action",
                        "core_claim": "FN1-SDC2 is a fibroblast niche signal.",
                        "evidence_references": [
                            "stage1_FN1--SDC2.json",
                            "ot_FN1.json",
                            "stage3_FN1.json",
                        ],
                        "biological_entities": {
                            "genes": ["FN1", "SDC2"],
                            "pathways": ["ECM"],
                            "cell_types": ["fibroblast"],
                            "drugs": [],
                        },
                        "falsifiable_prediction": "FN1 perturbation will alter SDC2 signaling.",
                        "validation_approach": "Fibroblast culture assay.",
                    },
                    {
                        "rank": 2,
                        "title": "ICAM1-MUC1 nominates an AT2 epithelial program candidate",
                        "category": "Therapeutic Strategy",
                        "core_claim": "ICAM1-MUC1 is an AT2 epithelial program.",
                        "evidence_references": [
                            "stage1_ICAM1--MUC1.json",
                            "ot_ICAM1.json",
                            "stage3_ICAM1.json",
                        ],
                        "biological_entities": {
                            "genes": ["ICAM1", "MUC1"],
                            "pathways": ["inflammatory signaling"],
                            "cell_types": ["pulmonary alveolar type 2 cell"],
                            "drugs": [],
                        },
                        "falsifiable_prediction": "AT2 perturbation will alter ICAM1 signaling.",
                        "validation_approach": "IPF-derived AT2 epithelial culture assay.",
                    },
                ],
            },
        },
    }

    markdown = render_report_markdown(report_data)

    primary_heading = "### 4.1. Primary AT2/Epithelial Follow-up Candidates"
    secondary_heading = "### 4.2. Secondary Spatial-Niche Follow-up Candidates"
    assert primary_heading in markdown
    assert secondary_heading in markdown
    assert markdown.index(primary_heading) < markdown.index(secondary_heading)
    assert "#### 4.1.1. ICAM1-MUC1 nominates an AT2 epithelial program candidate" in markdown
    assert "#### 4.2.1. FN1-SDC2 spatial-niche follow-up candidate" in markdown
    assert "Primary epithelial/AT2-intrinsic" in markdown
    assert "Secondary epithelial-associated niche" in markdown
    assert (
        "not as interest-cell-intrinsic target mechanisms"
        in markdown
    )
    assert "**Biological Grounding:**" in markdown
    assert "**Target-Disease Support:**" in markdown
    assert "**Actionability:**" in markdown
    assert "**Interpretation Constraint:**" in markdown
    assert "#### Secondary Stage 1 Framing Evidence" in markdown
    assert "| Pair | Census direction | Usage | Source |" in markdown
    assert "FN1-SDC2" in markdown
    assert "stage1_FN1--SDC2.json" in markdown
    assert "Cross-cell/spatial-niche framing only" in markdown
    assert "not AT2-intrinsic support" in markdown
    gap_section = markdown.split("### Gap Analysis", 1)[1]
    assert "stage1_FN1--SDC2.json" not in gap_section
    assert (
        "framing evidence for non-interest-cell or cross-cell follow-up, not as "
        "interest-cell-intrinsic support"
    ) in markdown


def test_report_mvp_renders_asymmetric_stage2_stage3_refs_for_primary_pair() -> None:
    from src.agents.drug_target.deterministic_report import render_report_markdown

    report_data = {
        "disease": "idiopathic pulmonary fibrosis",
        "candidates": [],
        "template_context": {
            "stage1_filter_results": [
                {"ligand": "ICAM1", "receptor": "EZR", "passed": True},
            ],
            "stage1_pairs": {
                "ICAM1_EZR": _stage1_pair_payload(
                    "ICAM1",
                    "EZR",
                    passed=True,
                    string_score=0.998,
                    gene_a_rr=3.36,
                    gene_b_rr=1.13,
                    coexpr_rr=4.49,
                ),
            },
            "hypothesis_data": {
                "evidence_coverage_pct": 100.0,
                "hypotheses_generated": 1,
                "hypotheses_retained": 1,
                "gap_analysis": {
                    "referenced_files": 3,
                    "total_evidence_files": 3,
                    "orphan_files": [],
                },
                "hypotheses": [
                    {
                        "rank": 1,
                        "title": "ICAM1-EZR coexpression nominates an ICAM1-anchored epithelial follow-up axis",
                        "category": "Mechanism of Action",
                        "core_claim": (
                            "Stage 1 Census evidence shows ICAM1--EZR passed the filter in the resolved epithelial cell type. "
                            "ICAM1 has cited Stage 2/3 support, while EZR is a Stage 1 coexpression-context partner. "
                            "Not yet established: whether ICAM1-EZR coexpression is causal or marks an epithelial stress state."
                        ),
                        "evidence_references": [
                            "stage1_ICAM1--EZR.json",
                            "ot_ICAM1.json",
                            "stage3_ICAM1.json",
                        ],
                        "biological_entities": {
                            "genes": ["ICAM1", "EZR"],
                            "pathways": ["cell adhesion"],
                            "cell_types": ["pulmonary alveolar type 2 cell"],
                            "drugs": [],
                        },
                        "falsifiable_prediction": (
                            "Test whether ICAM1-centered perturbation changes epithelial injury, "
                            "adhesion, or cell-state readouts while measuring EZR localization or "
                            "coexpression as a secondary readout."
                        ),
                        "validation_approach": (
                            "Perturb ICAM1 in AT2-enriched models and measure epithelial readouts; "
                            "measure EZR only as a contextual coexpression or localization readout."
                        ),
                    },
                ],
            },
        },
    }

    markdown = render_report_markdown(report_data)
    heading = (
        "#### 4.1.1. ICAM1-EZR coexpression nominates an ICAM1-anchored epithelial follow-up axis"
    )
    section = heading + markdown.split(heading, 1)[1].split("---", 1)[0]

    assert "ICAM1-anchored" in section
    assert "Treat ICAM1 as the Stage 2/3-supported anchor" in section
    assert "EZR as a coexpression-context partner" in section
    assert (
        "do not infer gene-level target-disease support or drug actionability for EZR"
        in section
    )
    assert "ICAM1-centered" in section
    assert "EZR localization or coexpression as a secondary readout" in section
    assert "**Target-Disease Support:** ot_ICAM1.json" in section
    assert "**Actionability:** stage3_ICAM1.json" in section
    assert "- stage1_ICAM1--EZR.json" in section
    assert "- ot_ICAM1.json" in section
    assert "- stage3_ICAM1.json" in section
    assert "ot_EZR.json" not in section
    assert "stage3_EZR.json" not in section
    assert "No Stage 2 OpenTargets evidence cited" not in section
    assert "No Stage 3 druggability evidence cited" not in section


def test_report_mvp_asymmetric_primary_constraint_ignores_failed_pair() -> None:
    from src.agents.drug_target.deterministic_report import render_report_markdown

    report_data = {
        "disease": "idiopathic pulmonary fibrosis",
        "candidates": [],
        "template_context": {
            "stage1_filter_results": [
                {"ligand": "FGFR1", "receptor": "FZD2", "passed": False},
                {"ligand": "ICAM1", "receptor": "EZR", "passed": True},
            ],
            "stage1_pairs": {
                "FGFR1_FZD2": _stage1_pair_payload(
                    "FGFR1",
                    "FZD2",
                    passed=False,
                    string_score=0.42,
                    gene_a_rr=3.0,
                    gene_b_rr=1.4,
                    coexpr_rr=4.2,
                ),
                "ICAM1_EZR": _stage1_pair_payload(
                    "ICAM1",
                    "EZR",
                    passed=True,
                    string_score=0.998,
                    gene_a_rr=3.36,
                    gene_b_rr=1.13,
                    coexpr_rr=4.49,
                ),
            },
            "hypothesis_data": {
                "hypotheses_generated": 1,
                "hypotheses_retained": 1,
                "hypotheses": [
                    {
                        "rank": 1,
                        "title": "Mixed evidence keeps ICAM1 as the epithelial anchor",
                        "category": "Mechanism of Action",
                        "core_claim": (
                            "ICAM1--EZR is the primary epithelial pair; "
                            "FGFR1--FZD2 is cited only as failed contrast."
                        ),
                        "evidence_references": [
                            "stage1_FGFR1--FZD2.json",
                            "ot_FGFR1.json",
                            "stage3_FGFR1.json",
                            "stage1_ICAM1--EZR.json",
                            "ot_ICAM1.json",
                            "stage3_ICAM1.json",
                        ],
                        "biological_entities": {
                            "genes": ["ICAM1", "EZR", "FGFR1", "FZD2"],
                            "pathways": [],
                            "cell_types": ["pulmonary alveolar type 2 cell"],
                            "drugs": [],
                        },
                        "falsifiable_prediction": "Test ICAM1-centered epithelial readouts.",
                        "validation_approach": "Perturb ICAM1 in AT2-enriched models.",
                    },
                ],
            },
        },
    }

    markdown = render_report_markdown(report_data)
    heading = "#### 4.1.1. Mixed evidence keeps ICAM1 as the epithelial anchor"
    section = heading + markdown.split(heading, 1)[1].split("---", 1)[0]
    constraint = next(
        line
        for line in section.splitlines()
        if line.startswith("**Interpretation Constraint:**")
    )

    assert "Treat ICAM1 as the Stage 2/3-supported anchor" in constraint
    assert (
        "do not infer gene-level target-disease support or drug actionability for EZR"
        in constraint
    )
    assert "Treat FGFR1 as the Stage 2/3-supported anchor" not in constraint
    assert (
        "do not infer gene-level target-disease support or drug actionability for FZD2"
        not in constraint
    )


def test_report_mvp_renders_both_section4_headings_with_single_tier() -> None:
    from src.agents.drug_target.deterministic_report import render_report_markdown

    report_data = {
        "disease": "idiopathic pulmonary fibrosis",
        "candidates": [],
        "template_context": {
            "stage1_filter_results": [
                {"ligand": "FN1", "receptor": "SDC2", "passed": True},
            ],
            "stage1_pairs": {
                "FN1_SDC2": _stage1_pair_payload(
                    "FN1",
                    "SDC2",
                    passed=True,
                    string_score=0.959,
                    gene_a_rr=0.24,
                    gene_b_rr=0.31,
                    coexpr_rr=0.2258,
                ),
            },
            "hypothesis_data": {
                "hypotheses": [
                    {
                        "rank": 1,
                        "title": "FN1-SDC2 spatial-niche follow-up candidate",
                        "category": "Mechanism of Action",
                        "core_claim": "FN1-SDC2 is a fibroblast niche signal.",
                        "evidence_references": ["stage1_FN1--SDC2.json"],
                        "biological_entities": {
                            "genes": ["FN1", "SDC2"],
                            "pathways": ["ECM"],
                            "cell_types": ["fibroblast"],
                            "drugs": [],
                        },
                        "falsifiable_prediction": "FN1 perturbation will alter SDC2 signaling.",
                        "validation_approach": "Fibroblast culture assay.",
                    },
                ],
            },
        },
    }

    markdown = render_report_markdown(report_data)

    assert "### 4.1. Primary AT2/Epithelial Follow-up Candidates" in markdown
    assert "### 4.2. Secondary Spatial-Niche Follow-up Candidates" in markdown
    assert (
        "No primary AT2/epithelial follow-up candidates met the Stage 1 "
        "intrinsic-support criteria."
    ) in markdown
    assert "#### 4.2.1. FN1-SDC2 spatial-niche follow-up candidate" in markdown


def test_report_mvp_excludes_failed_stage1_pairs_from_secondary_framing() -> None:
    from src.agents.drug_target.deterministic_report import render_report_markdown

    report_data = {
        "disease": "idiopathic pulmonary fibrosis",
        "candidates": [],
        "template_context": {
            "stage1_filter_results": [
                {"ligand": "FN1", "receptor": "SDC2", "passed": False},
            ],
            "stage1_pairs": {
                "FN1_SDC2": _stage1_pair_payload(
                    "FN1",
                    "SDC2",
                    passed=False,
                    string_score=0.759,
                    gene_a_rr=0.24,
                    gene_b_rr=0.31,
                    coexpr_rr=0.2258,
                ),
            },
            "hypothesis_data": {
                "hypotheses": [
                    {
                        "rank": 1,
                        "title": "FN1-SDC2 spatial-niche follow-up candidate",
                        "category": "Mechanism of Action",
                        "core_claim": "FN1-SDC2 is a fibroblast niche signal.",
                        "evidence_references": ["stage1_FN1--SDC2.json"],
                        "biological_entities": {
                            "genes": ["FN1", "SDC2"],
                            "pathways": ["ECM"],
                            "cell_types": ["fibroblast"],
                            "drugs": [],
                        },
                        "falsifiable_prediction": "FN1 perturbation will alter SDC2 signaling.",
                        "validation_approach": "Fibroblast culture assay.",
                    },
                ],
            },
        },
    }

    markdown = render_report_markdown(report_data)

    assert "#### 4.2.1. FN1-SDC2 spatial-niche follow-up candidate" in markdown
    assert "#### Secondary Stage 1 Framing Evidence" not in markdown
    assert "| FN1-SDC2 |" not in markdown


def test_report_mvp_does_not_add_uncited_stage1_pairs_to_secondary_framing() -> None:
    from src.agents.drug_target.deterministic_report import render_report_markdown

    report_data = {
        "disease": "idiopathic pulmonary fibrosis",
        "candidates": [],
        "template_context": {
            "stage1_filter_results": [
                {"ligand": "FN1", "receptor": "SDC2", "passed": True},
            ],
            "stage1_pairs": {
                "FN1_SDC2": _stage1_pair_payload(
                    "FN1",
                    "SDC2",
                    passed=True,
                    string_score=0.959,
                    gene_a_rr=0.24,
                    gene_b_rr=0.31,
                    coexpr_rr=0.2258,
                ),
            },
            "hypothesis_data": {
                "evidence_coverage_pct": 50.0,
                "hypotheses_generated": 1,
                "hypotheses_retained": 1,
                "gap_analysis": {
                    "referenced_files": 1,
                    "total_evidence_files": 2,
                    "orphan_files": ["stage1_FN1--SDC2.json"],
                },
                "hypotheses": [
                    {
                        "rank": 1,
                        "title": "FN1-SDC2 spatial-niche follow-up candidate",
                        "category": "Mechanism of Action",
                        "core_claim": "FN1-SDC2 is a fibroblast niche signal.",
                        "evidence_references": ["stage3_FN1.json"],
                        "biological_entities": {
                            "genes": ["FN1", "SDC2"],
                            "pathways": ["ECM"],
                            "cell_types": ["fibroblast"],
                            "drugs": [],
                        },
                        "falsifiable_prediction": "FN1 perturbation will alter SDC2 signaling.",
                        "validation_approach": "Fibroblast culture assay.",
                    },
                ],
            },
        },
    }

    markdown = render_report_markdown(report_data)

    assert "### 4.3. Gene-Level/Actionability Follow-up Candidates" in markdown
    assert "#### 4.3.1. FN1-SDC2 spatial-niche follow-up candidate" in markdown
    assert "### 4.2. Secondary Spatial-Niche Follow-up Candidates" not in markdown
    assert "#### Secondary Stage 1 Framing Evidence" not in markdown
    recommendation = markdown.split(
        "#### 4.3.1. FN1-SDC2 spatial-niche follow-up candidate",
        1,
    )[1]
    assert (
        "**Biological Grounding:** No Stage 1/spatial grounding reference cited."
        in recommendation
    )
    gap_section = markdown.split("### Gap Analysis", 1)[1]
    assert "stage1_FN1--SDC2.json" in gap_section


def test_report_mvp_labels_gene_level_only_candidates_without_spatial_niche() -> None:
    from src.agents.drug_target.deterministic_report import render_report_markdown
    from src.agents.drug_target.tools.drug_report_html import (
        parse_drug_md,
        render_drug_html,
    )

    report_data = {
        "disease": "idiopathic pulmonary fibrosis",
        "candidates": [],
        "template_context": {
            "hypothesis_data": {
                "hypotheses_generated": 1,
                "hypotheses_retained": 1,
                "hypotheses": [
                    {
                        "rank": 1,
                        "title": "CD47 actionability follow-up candidate",
                        "category": "Therapeutic Strategy",
                        "core_claim": (
                            "CD47 has cited gene-level actionability support. "
                            "Not yet established: whether CD47 perturbation "
                            "changes IPF-relevant macrophage-fibroblast readouts."
                        ),
                        "evidence_references": ["stage3_CD47.json", "ot_CD47.json"],
                        "biological_entities": {
                            "genes": ["CD47"],
                            "pathways": ["immune modulation"],
                            "cell_types": ["macrophage"],
                            "drugs": [],
                        },
                        "falsifiable_prediction": (
                            "Test whether CD47 perturbation changes "
                            "macrophage-fibroblast readouts."
                        ),
                        "validation_approach": (
                            "Use macrophage-fibroblast co-culture and measure "
                            "qualitative activation readouts."
                        ),
                    }
                ],
            },
        },
    }

    markdown = render_report_markdown(report_data)

    gene_level_heading = "### 4.3. Gene-Level/Actionability Follow-up Candidates"
    cd47_heading = "#### 4.3.1. CD47 actionability follow-up candidate"

    assert gene_level_heading in markdown
    assert cd47_heading in markdown
    assert markdown.index(gene_level_heading) < markdown.index(cd47_heading)
    assert "### 4.2. Secondary Spatial-Niche Follow-up Candidates" not in markdown
    assert "#### 4.2.1. CD47 actionability follow-up candidate" not in markdown
    assert "Gene-level/actionability follow-up" in markdown
    assert "No Stage 1/spatial grounding reference cited" in markdown
    assert "do not interpret as AT2-intrinsic or spatial-niche evidence" in markdown
    assert "Secondary epithelial-associated niche" not in markdown

    context = parse_drug_md(markdown)
    html = render_drug_html(context)

    assert len(context["gene_level_hypotheses"]) == 1
    assert len(context["secondary_hypotheses"]) == 0
    assert "4.3. Gene-Level/Actionability Follow-up Candidates" in html
    assert "4.2. Secondary Spatial-Niche Follow-up Candidates" not in html


def test_render_drug_md_buckets_raw_gene_level_only_candidate() -> None:
    from src.agents.drug_target.tools.drug_report_html import render_drug_md

    markdown = render_drug_md(
        disease="idiopathic pulmonary fibrosis",
        stage3_genes=[],
        featured_cards=[],
        all_genes_matrix=[],
        stage1_data={},
        stage1_filter_results=[],
        hypothesis_data={
            "hypotheses_generated": 1,
            "hypotheses_retained": 1,
            "hypotheses": [
                {
                    "rank": 1,
                    "title": "CD47 actionability follow-up candidate",
                    "category": "Therapeutic Strategy",
                    "core_claim": (
                        "CD47 has cited gene-level actionability support. "
                        "Not yet established: whether CD47 perturbation changes "
                        "IPF-relevant macrophage-fibroblast readouts."
                    ),
                    "evidence_references": ["stage3_CD47.json", "ot_CD47.json"],
                    "biological_entities": {
                        "genes": ["CD47"],
                        "pathways": ["immune modulation"],
                        "cell_types": ["macrophage"],
                        "drugs": [],
                    },
                    "falsifiable_prediction": (
                        "Test whether CD47 perturbation changes "
                        "macrophage-fibroblast readouts."
                    ),
                    "validation_approach": (
                        "Use macrophage-fibroblast co-culture and measure "
                        "qualitative activation readouts."
                    ),
                }
            ],
        },
    )

    gene_level_heading = "### 4.3. Gene-Level/Actionability Follow-up Candidates"
    cd47_heading = "#### 4.3.1. CD47 actionability follow-up candidate"

    assert gene_level_heading in markdown
    assert cd47_heading in markdown
    assert markdown.index(gene_level_heading) < markdown.index(cd47_heading)
    assert "#### 4.1. CD47 actionability follow-up candidate" not in markdown
    assert "### 4.2. Secondary Spatial-Niche Follow-up Candidates" not in markdown
    assert "#### 4.2.1. CD47 actionability follow-up candidate" not in markdown


def test_drug_report_html_preserves_section4_tier_split_and_framing_table() -> None:
    from src.agents.drug_target.deterministic_report import render_report_markdown
    from src.agents.drug_target.tools.drug_report_html import (
        parse_drug_md,
        render_drug_html,
    )

    report_data = {
        "disease": "idiopathic pulmonary fibrosis",
        "candidates": [],
        "template_context": {
            "stage1_filter_results": [
                {"ligand": "ICAM1", "receptor": "MUC1", "passed": True},
                {"ligand": "FN1", "receptor": "SDC2", "passed": True},
            ],
            "stage1_pairs": {
                "ICAM1_MUC1": _stage1_pair_payload(
                    "ICAM1",
                    "MUC1",
                    passed=True,
                    string_score=0.993,
                    gene_a_rr=3.36,
                    gene_b_rr=9.83,
                    coexpr_rr=17.86,
                ),
                "FN1_SDC2": _stage1_pair_payload(
                    "FN1",
                    "SDC2",
                    passed=True,
                    string_score=0.959,
                    gene_a_rr=0.24,
                    gene_b_rr=0.31,
                    coexpr_rr=0.2258,
                ),
            },
            "hypothesis_data": {
                "hypotheses": [
                    {
                        "rank": 1,
                        "title": "ICAM1-MUC1 nominates an AT2 epithelial program candidate",
                        "category": "Therapeutic Strategy",
                        "core_claim": "ICAM1-MUC1 is an AT2 epithelial program.",
                        "evidence_references": ["stage1_ICAM1--MUC1.json"],
                        "biological_entities": {
                            "genes": ["ICAM1", "MUC1"],
                            "pathways": ["inflammatory signaling"],
                            "cell_types": ["pulmonary alveolar type 2 cell"],
                            "drugs": [],
                        },
                        "falsifiable_prediction": "AT2 perturbation will alter ICAM1 signaling.",
                        "validation_approach": "IPF-derived AT2 epithelial culture assay.",
                    },
                    {
                        "rank": 2,
                        "title": "FN1-SDC2 spatial-niche follow-up candidate",
                        "category": "Mechanism of Action",
                        "core_claim": "FN1-SDC2 is a fibroblast niche signal.",
                        "evidence_references": ["stage1_FN1--SDC2.json"],
                        "biological_entities": {
                            "genes": ["FN1", "SDC2"],
                            "pathways": ["ECM"],
                            "cell_types": ["fibroblast"],
                            "drugs": [],
                        },
                        "falsifiable_prediction": "FN1 perturbation will alter SDC2 signaling.",
                        "validation_approach": "Fibroblast culture assay.",
                    },
                ],
            },
        },
    }

    context = parse_drug_md(render_report_markdown(report_data))
    html = render_drug_html(context)

    assert len(context["primary_hypotheses"]) == 1
    assert len(context["secondary_hypotheses"]) == 1
    assert context["secondary_stage1_framing_pairs"][0]["source"] == (
        "stage1_FN1--SDC2.json"
    )
    assert "4.1. Primary AT2/Epithelial Follow-up Candidates" in html
    assert "4.2. Secondary Spatial-Niche Follow-up Candidates" in html
    assert "Secondary Stage 1 Framing Evidence" in html
    assert "stage1_FN1--SDC2.json" in html


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


def test_report_mvp_failure_removes_stale_part4_artifact(tmp_path: Path) -> None:
    from src.agents.drug_target.deterministic_report import finalize_report_mvp

    workspace = _copy_baseline_workspace(tmp_path)
    state = {
        "data_dir": str(workspace),
        "disease": "idiopathic pulmonary fibrosis",
        "report_finalization_error": None,
        "evidence_truncated": False,
    }
    first_result = asyncio.run(finalize_report_mvp(state, {}))
    part4_path = workspace / "part4_therapeutic_synthesis.md"

    assert first_result["report_finalization_error"] is None
    assert part4_path.exists()

    (workspace / "evidence" / "assessment_results.json").unlink()
    second_result = asyncio.run(finalize_report_mvp(state, {}))

    assert second_result["evidence_truncated"] is False
    assert second_result["report_finalization_error"].startswith(
        "deterministic_report_validation_failed:"
    )
    assert not part4_path.exists()
    validation = json.loads(
        (workspace / "report_validation.json").read_text(encoding="utf-8")
    )
    assert validation["valid"] is False
    assert any(
        issue["code"] == "MISSING_REQUIRED_EVIDENCE"
        for issue in validation["issues"]
    )


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
