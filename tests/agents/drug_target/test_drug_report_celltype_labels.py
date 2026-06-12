from __future__ import annotations

from typing import Any, cast


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


def _part4_html(html: str) -> str:
    return html.split('<div id="hypothesis"', 1)[1].split(
        '<div id="recommendations"',
        1,
    )[0]


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


def test_legacy_raw_gene_level_hypothesis_uses_celltype_context_constraint() -> None:
    from src.agents.drug_target.tools.drug_report_html import render_drug_md

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
            "hypotheses": [
                {
                    "rank": 1,
                    "title": "ERBB2 actionability follow-up candidate",
                    "category": "Therapeutic Strategy",
                    "core_claim": "Synthetic gene-level claim.",
                    "evidence_references": ["stage3_ERBB2.json", "ot_ERBB2.json"],
                    "biological_entities": {
                        "genes": ["ERBB2"],
                        "pathways": [],
                        "cell_types": ["malignant cell"],
                        "drugs": [],
                    },
                    "falsifiable_prediction": "Synthetic prediction.",
                    "validation_approach": "Synthetic validation.",
                }
            ],
        },
        celltype_resolution={
            "primary_input_celltype": "Prolif Invasive Tumor",
            "primary_match_mode": "semantic_proxy",
            "primary_resolved_celltype": "malignant cell",
            "interest_celltypes": ["Prolif Invasive Tumor"],
        },
    )
    part4 = _part4(markdown)

    assert (
        "Gene-level support only; do not interpret as interest-cell-intrinsic "
        "or spatial-niche evidence for Prolif Invasive Tumor; Census proxy: "
        "malignant cell."
    ) in part4
    assert "AT2" not in part4


def test_html_part4_uses_interest_cell_proxy_labels_not_at2() -> None:
    from src.agents.drug_target.deterministic_report import render_report_markdown
    from src.agents.drug_target.tools.drug_report_html import (
        parse_drug_md,
        render_drug_html,
    )

    markdown = render_report_markdown(_breast_cancer_report_data())
    html = render_drug_html(parse_drug_md(markdown))
    part4_html = _part4_html(html)

    assert "Primary Interest-Cell Follow-up Candidates" in part4_html
    assert "Prolif Invasive Tumor" in part4_html
    assert "Census proxy: malignant cell" in part4_html
    assert "AT2" not in part4_html
    assert "AT2-intrinsic" not in part4_html


def test_parse_drug_md_buckets_old_style_tier_labels_without_numeric_tier_headings() -> None:
    from src.agents.drug_target.tools.drug_report_html import (
        parse_drug_md,
        render_drug_html,
    )

    markdown = """# Drug Target Assessment Report: test disease

## 4. Evidence-Grounded Follow-up Recommendations

### 4.1. Old AT2 primary candidate

**Interpretation Tier:** Primary epithelial/AT2-intrinsic
**Category:** Mechanism of Action
**Conservative Interpretation:** Primary AT2 claim.

### 4.2. Current interest-cell primary candidate

**Interpretation Tier:** Primary interest-cell intrinsic
**Category:** Mechanism of Action
**Conservative Interpretation:** Primary interest-cell claim.

### 4.3. Old epithelial niche candidate

**Interpretation Tier:** Secondary epithelial-associated niche
**Category:** Spatial Biology
**Conservative Interpretation:** Secondary epithelial niche claim.

### 4.4. Current spatial niche candidate

**Interpretation Tier:** Secondary spatial-niche/cross-cell
**Category:** Spatial Biology
**Conservative Interpretation:** Secondary spatial niche claim.

### 4.5. Gene-level actionability candidate

**Interpretation Tier:** Gene-level/actionability follow-up
**Category:** Therapeutic Strategy
**Conservative Interpretation:** Gene-level claim.

## 5. Pipeline Execution Summary
"""

    context = parse_drug_md(markdown)

    assert [h["title"] for h in context["primary_hypotheses"]] == [
        "Old AT2 primary candidate",
        "Current interest-cell primary candidate",
    ]
    assert [h["title"] for h in context["secondary_hypotheses"]] == [
        "Old epithelial niche candidate",
        "Current spatial niche candidate",
    ]
    assert [h["title"] for h in context["gene_level_hypotheses"]] == [
        "Gene-level actionability candidate",
    ]
    assert context["unbucketed_hypotheses"] == []

    part4_html = _part4_html(render_drug_html(context))

    assert "Primary AT2/Epithelial Follow-up Candidates" in part4_html
    assert "<h3>4.1. Old AT2 primary candidate</h3>" not in part4_html
    assert (
        "<p style=\"color: var(--text-secondary);\">"
        "**Interpretation Tier:** Primary epithelial/AT2-intrinsic"
        "</p>"
        not in part4_html
    )


def test_legacy_drug_md_renderer_preserves_at2_stage1_fallback_context() -> None:
    from src.agents.drug_target.tools.drug_report_html import (
        parse_drug_md,
        render_drug_html,
        render_drug_md,
    )

    hypothesis = {
        "rank": 1,
        "title": "Synthetic AT2 candidate",
        "category": "Mechanism of Action",
        "core_claim": "Synthetic claim.",
        "evidence_references": ["stage1_ICAM1--MUC1.json"],
        "biological_entities": {
            "genes": ["ICAM1", "MUC1"],
            "pathways": [],
            "cell_types": ["pulmonary alveolar type 2 cell"],
            "drugs": [],
        },
        "falsifiable_prediction": "Synthetic prediction.",
        "validation_approach": "Synthetic validation.",
    }
    markdown = render_drug_md(
        disease="idiopathic pulmonary fibrosis",
        stage3_genes=[],
        featured_cards=[],
        all_genes_matrix=[],
        stage1_data={
            "ICAM1_MUC1": {
                "census_validation": {
                    "requested_cell_type": "pulmonary alveolar type 2 cell",
                    "resolved_cell_type": "pulmonary alveolar type 2 cell",
                },
            },
        },
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
    )
    part4 = _part4(markdown)

    assert "### 4.1. Primary AT2/Epithelial Follow-up Candidates" in part4
    assert "epithelial/AT2 cell context" in part4
    assert "AT2/epithelial follow-up candidates" in part4

    html = render_drug_html(parse_drug_md(markdown))
    part4_html = _part4_html(html)

    assert "Primary AT2/Epithelial Follow-up Candidates" in part4_html
    assert "epithelial/AT2 cell context" in part4_html
    assert "AT2/epithelial follow-up candidates" in part4_html


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


def test_build_evidence_summary_ignores_malformed_celltype_resolution_json(
    tmp_path,
    monkeypatch,
) -> None:
    import json

    from src.agents.drug_target.tools import drug_report_html
    from src.agents.drug_target.tools.stage_logic import build_evidence_summary

    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "assessment_results.json").write_text(
        json.dumps(
            {
                "disease": "test disease",
                "stage3_candidates": [],
                "rubric_assessment": [],
            }
        ),
        encoding="utf-8",
    )
    (evidence_dir / "celltype_resolution.json").write_text("{", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_render_drug_md(**kwargs):
        captured["celltype_resolution"] = kwargs["celltype_resolution"]
        return "# stub drug draft"

    monkeypatch.setattr(drug_report_html, "render_drug_md", fake_render_drug_md)

    raw = cast(Any, build_evidence_summary).func(str(tmp_path))

    result = json.loads(raw)
    assert captured["celltype_resolution"] == {}
    assert result["markdown_template"] == "# stub drug draft"
