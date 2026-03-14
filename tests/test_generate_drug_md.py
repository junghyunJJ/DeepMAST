from __future__ import annotations

from scripts import generate_drug_md


def test_build_stage1_context_notes_uses_generic_wording():
    evidence = {
        "resolved_context": {
            "resolved_target_cell_type": "alveolar epithelial cell",
        },
        "stage1_confidence": {
            "KDR^FLT1": {"confidence": 0.4979},
        },
        "stage1_details": {
            "stage1_KDR_FLT1": {
                "stage1_annotations": {
                    "microenvironment_candidate": True,
                    "supporting_cell_type": "endothelial cell",
                    "supporting_coexpression_pct": 67.8788,
                }
            }
        },
    }

    notes = generate_drug_md._build_stage1_context_notes(evidence)

    assert "weak coexpression in the primary target cell type" in notes
    assert "alveolar epithelial cell" in notes
    assert "vascular microenvironment candidate" in notes
    assert "mammary" not in notes
    assert "tumor-cell candidate" not in notes
