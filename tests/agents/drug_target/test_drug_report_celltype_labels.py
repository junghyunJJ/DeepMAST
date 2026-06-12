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
