from __future__ import annotations


PART4_HEADING = "## 4. Evidence-Grounded Follow-up Recommendations"


def _breast_cancer_report_data() -> dict:
    return {
        "disease": "breast cancer",
        "candidates": [],
        "template_context": {
            "celltype_resolution": {
                "interest_celltypes": ["Prolif Invasive Tumor"],
                "primary_input_celltype": "Prolif Invasive Tumor",
                "primary_match_mode": "semantic_proxy",
                "primary_resolved_celltype": "malignant cell",
            },
            "stage1_filter_results": [
                {"ligand": "EGF", "receptor": "ERBB2", "passed": True},
            ],
            "stage1_pairs": {
                "EGF_ERBB2": {
                    "ligand": "EGF",
                    "receptor": "ERBB2",
                    "string_ppi": {
                        "interaction_found": True,
                        "max_combined_score": 0.997,
                    },
                    "census_validation": {
                        "requested_cell_type": "malignant cell",
                        "resolved_cell_type": "malignant cell",
                        "target_vs_rest": {
                            "gene_a": {
                                "risk_ratio": 2.7,
                                "diff": 1.7,
                                "p_value": 0.0004,
                            },
                            "gene_b": {
                                "risk_ratio": 5.4,
                                "diff": 4.4,
                                "p_value": 0.00002,
                            },
                            "coexpression": {
                                "risk_ratio": 8.6,
                                "diff": 7.6,
                                "p_value": 0.000001,
                            },
                        },
                    },
                    "stage1_filter": {
                        "passed": True,
                        "string_combined": 0.997,
                    },
                },
            },
            "hypothesis_data": {
                "evidence_coverage_pct": 100.0,
                "hypotheses_generated": 1,
                "hypotheses_retained": 1,
                "gap_analysis": {
                    "referenced_files": 1,
                    "total_evidence_files": 1,
                    "orphan_files": [],
                },
                "hypotheses": [
                    {
                        "rank": 1,
                        "title": "ERBB2-centered malignant-cell follow-up axis",
                        "category": "Mechanism of Action",
                        "core_claim": (
                            "Stage 1 Census evidence shows EGF--ERBB2 passed "
                            "with malignant-cell target-vs-rest enrichment."
                        ),
                        "evidence_references": ["stage1_EGF--ERBB2.json"],
                        "biological_entities": {
                            "genes": ["EGF", "ERBB2"],
                            "pathways": ["EGFR/ERBB signaling"],
                            "cell_types": ["malignant cell"],
                            "drugs": [],
                        },
                        "falsifiable_prediction": (
                            "ERBB2 perturbation will reduce malignant-cell "
                            "EGF--ERBB2 coexpression and proliferation readouts."
                        ),
                        "validation_approach": (
                            "Perturb ERBB2 in malignant-cell breast cancer "
                            "models and measure EGF--ERBB2 target-vs-rest "
                            "coexpression."
                        ),
                    },
                ],
            },
        },
    }


def _part4(markdown: str) -> str:
    return markdown.split(PART4_HEADING, 1)[1].split("## 5.", 1)[0]


def test_part4_uses_interest_cell_proxy_labels_not_at2() -> None:
    from src.agents.drug_target.deterministic_report import render_report_markdown

    markdown = render_report_markdown(_breast_cancer_report_data())
    part4 = _part4(markdown)

    assert "Prolif Invasive Tumor" in part4
    assert "Census proxy: malignant cell" in part4
    assert "malignant-cell proxy" in part4
    assert "AT2" not in part4
    assert "epithelial/AT2" not in part4
    assert "AT2-intrinsic" not in part4


def test_enriched_malignant_stage1_hypothesis_is_primary_target_cell_support() -> None:
    from src.agents.drug_target.deterministic_report import render_report_markdown

    markdown = render_report_markdown(_breast_cancer_report_data())
    part4 = _part4(markdown)

    assert "### 4.1. Primary Interest-Cell Follow-up Candidates" in part4
    assert "#### 4.1.1. ERBB2-centered malignant-cell follow-up axis" in part4
    assert "Primary interest-cell intrinsic" in part4
    assert "not interest-cell-intrinsic support" not in part4
    assert "No primary" not in part4


def test_missing_stage1_pass_status_is_not_primary_target_cell_support() -> None:
    from copy import deepcopy

    from src.agents.drug_target.deterministic_report import (
        _markdown_template_context,
        _template_pair,
    )

    report_data = deepcopy(_breast_cancer_report_data())
    template_context = report_data["template_context"]
    template_context["stage1_filter_results"] = []
    template_context["stage1_pairs"]["EGF_ERBB2"].pop("stage1_filter")

    context = _markdown_template_context(report_data)
    pair = _template_pair(
        "EGF_ERBB2",
        template_context["stage1_pairs"]["EGF_ERBB2"],
        {},
    )

    assert pair["_target_cell_intrinsic_support"] is False
    assert "Primary" not in pair["hypothesis_use"]
    assert context["hypothesis_data"]["primary_hypotheses"] == []
    assert len(context["hypothesis_data"]["secondary_hypotheses"]) == 1


def test_legacy_at2_fallback_context_preserves_epithelial_tier_labels() -> None:
    from copy import deepcopy

    from src.agents.drug_target.deterministic_report import _markdown_template_context

    report_data = deepcopy(_breast_cancer_report_data())
    template_context = report_data["template_context"]
    template_context.pop("celltype_resolution")
    census_validation = template_context["stage1_pairs"]["EGF_ERBB2"][
        "census_validation"
    ]
    census_validation["requested_cell_type"] = "pulmonary alveolar type 2 cell"
    census_validation["resolved_cell_type"] = "pulmonary alveolar type 2 cell"

    context = _markdown_template_context(report_data)
    primary = context["hypothesis_data"]["primary_hypotheses"]

    assert context["celltype_context"]["primary_tier_label"] == (
        "Primary epithelial/AT2-intrinsic"
    )
    assert context["celltype_context"]["secondary_tier_label"] == (
        "Secondary epithelial-associated niche"
    )
    assert primary[0]["_tier_label"] == "Primary epithelial/AT2-intrinsic"
    assert (
        primary[0]["_interpretation_constraint"]
        == "AT2/epithelial same-cell coexpression enrichment supports "
        "target-cell context, but not causal mechanism."
    )


def test_build_report_data_carries_celltype_resolution(tmp_path) -> None:
    import json
    import shutil
    from pathlib import Path

    from src.agents.drug_target.deterministic_report import build_report_data

    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "baseline_hallucinated"
    )
    workspace = tmp_path / "workspace"
    shutil.copytree(fixture, workspace)
    resolution = {
        "primary_input_celltype": "Prolif Invasive Tumor",
        "primary_match_mode": "semantic_proxy",
        "primary_resolved_celltype": "malignant cell",
        "interest_celltypes": ["Prolif Invasive Tumor"],
    }
    (workspace / "evidence" / "celltype_resolution.json").write_text(
        json.dumps(resolution),
        encoding="utf-8",
    )

    report_data = build_report_data(str(workspace), "breast cancer")

    assert (
        report_data["template_context"]["celltype_resolution"]
        ["primary_input_celltype"]
        == "Prolif Invasive Tumor"
    )
    assert "evidence/celltype_resolution.json" in report_data["sources"]


def test_legacy_drug_md_renderer_uses_celltype_context() -> None:
    from src.agents.drug_target.tools.drug_report_html import render_drug_md

    hypothesis = {
        "rank": 1,
        "title": "Synthetic primary candidate",
        "category": "Mechanism of Action",
        "core_claim": "Synthetic claim.",
        "evidence_references": ["stage1_EGF--ERBB2.json"],
        "biological_entities": {
            "genes": ["ERBB2"],
            "pathways": [],
            "cell_types": ["malignant cell"],
            "drugs": [],
        },
        "falsifiable_prediction": "Synthetic prediction.",
        "validation_approach": "Synthetic validation.",
    }
    markdown = render_drug_md(
        disease="breast cancer",
        stage3_genes=[],
        featured_cards=[],
        all_genes_matrix=[],
        stage1_data={},
        stage1_filter_results=[],
        hypothesis_data={
            "hypotheses_generated": 1,
            "hypotheses_retained": 1,
            "evidence_coverage_pct": 0,
            "hypotheses": [hypothesis],
            "primary_hypotheses": [hypothesis],
            "secondary_hypotheses": [],
            "gene_level_hypotheses": [],
        },
        celltype_resolution={
            "primary_input_celltype": "Prolif Invasive Tumor",
            "primary_match_mode": "semantic_proxy",
            "primary_resolved_celltype": "malignant cell",
            "interest_celltypes": ["Prolif Invasive Tumor"],
        },
    )
    part4 = _part4(markdown)

    assert "Prolif Invasive Tumor" in part4
    assert "Census proxy: malignant cell" in part4
    assert "AT2" not in part4


def test_legacy_celltype_context_normalizes_interest_celltypes_shapes() -> None:
    from src.agents.drug_target.tools.drug_report_html import (
        _legacy_celltype_context,
    )

    cases = [
        (
            {"interest_celltypes": "Prolif Invasive Tumor"},
            "Prolif Invasive Tumor",
        ),
        (
            {"interest_celltypes": ["", "Prolif Invasive Tumor"]},
            "Prolif Invasive Tumor",
        ),
        (
            {"interest_celltypes": ("", "Prolif Invasive Tumor")},
            "Prolif Invasive Tumor",
        ),
        ({"interest_celltypes": 42}, "resolved interest cell type"),
        (
            {"interest_celltypes": {"label": "Prolif Invasive Tumor"}},
            "resolved interest cell type",
        ),
        ({}, "resolved interest cell type"),
        (None, "resolved interest cell type"),
        (42, "resolved interest cell type"),
    ]

    for celltype_resolution, expected_detail in cases:
        context = _legacy_celltype_context(celltype_resolution, None)

        assert context["focus_detail"] == expected_detail


def test_legacy_celltype_context_uses_stage1_census_fallback() -> None:
    from src.agents.drug_target.tools.drug_report_html import (
        _legacy_celltype_context,
    )

    context = _legacy_celltype_context(
        None,
        {
            "EGF_ERBB2": {
                "census_validation": {
                    "requested_cell_type": "malignant cell",
                    "resolved_cell_type": "malignant cell",
                },
            },
        },
    )

    assert context["focus_detail"] == "malignant cell"
    assert context["focus_short"] == "interest-cell"


def test_render_drug_md_preserves_positional_novelty_legend_argument() -> None:
    from src.agents.drug_target.tools.drug_report_html import render_drug_md

    custom_legend = "custom positional novelty legend"
    markdown = render_drug_md(
        "test disease",
        [],
        [],
        [],
        {},
        [],
        None,
        None,
        None,
        None,
        custom_legend,
    )

    assert custom_legend in markdown
