from __future__ import annotations

from src.agents.drug_target.hypothesis_retry import build_hypothesis_retry_message


def test_retry_message_includes_numeric_prediction_correction() -> None:
    message = build_hypothesis_retry_message(
        "res_ipf_ollama",
        "idiopathic pulmonary fibrosis",
        quality_errors=[
            {
                "code": "UNVERIFIED_NUMERIC_PREDICTION",
                "message": "One or more falsifiable predictions contain unverified numeric values.",
                "details": {"unverified_indices": [1, 3]},
            }
        ],
        attempt=2,
        max_attempts=3,
    )

    assert "Retry attempt 2 of 3" in message
    assert "UNVERIFIED_NUMERIC_PREDICTION" in message
    assert "unsupported numeric predicted effects" in message
    assert "fold changes" in message
    assert "p-values" in message
    assert "effect-size thresholds" in message
    assert "predictive claims in validation_approach" in message
    assert "rewrite the prediction qualitatively" in message
    assert "test whether the perturbation changes disease-relevant marker expression" in message
    assert "Do not remove legitimate protocol or control details" in message
    assert "doses, timepoints, sample sizes, assay thresholds" in message
    assert "when they are framed as experimental design rather than predicted effects" in message
    assert "may appear in experimental protocol outside falsifiable_prediction" in message
    assert "Do not copy failed numeric predictions" in message
    assert "unverified_indices" in message
    assert 'task(subagent_type="hypothesis_writer"' in message
    assert "from falsifiable_prediction and validation_approach unless" not in message


def test_retry_message_includes_numeric_prediction_correction_from_last_rejection() -> None:
    message = build_hypothesis_retry_message(
        "res_ipf_drugtarget1",
        "idiopathic pulmonary fibrosis",
        quality_errors=[
            {
                "code": "HYPOTHESIS_LAST_SAVE_REJECTION",
                "message": "The last save_hypothesis_report attempt was rejected.",
                "details": {
                    "errors": [
                        "One or more falsifiable predictions contain unverified numeric values. Use qualitative wording unless the numeric value appears in a cited evidence file."
                    ],
                    "prediction_grounding_summary": {
                        "unverified": 1,
                        "unverified_indices": [2],
                    },
                },
            }
        ],
        attempt=1,
        max_attempts=3,
    )

    assert "HYPOTHESIS_LAST_SAVE_REJECTION" in message
    assert "unsupported numeric predicted effects" in message
    assert "fold changes" in message
    assert "predictive claims in validation_approach" in message
    assert "rewrite the prediction qualitatively" in message
    assert "test whether the perturbation changes disease-relevant marker expression" in message
    assert "Do not remove legitimate protocol or control details" in message
    assert "may appear in experimental protocol outside falsifiable_prediction" in message
    assert "Do not copy failed numeric predictions" in message
    assert "unverified_indices" in message


def test_retry_message_keeps_validation_feedback_inside_task_instruction() -> None:
    message = build_hypothesis_retry_message(
        "res_ipf_ollama",
        "idiopathic pulmonary fibrosis",
        quality_errors=[
            {
                "code": "MISSING_REQUIRED_CATEGORIES",
                "message": "Hypothesis report is missing required thematic categories.",
                "details": {"missing": ["Novel Pathway"]},
            }
        ],
        attempt=1,
        max_attempts=3,
    )

    assert message.index("MISSING_REQUIRED_CATEGORIES") < message.index(
        '")\n\nFor auditability'
    )
    assert "Novel Pathway" in message
    assert "evidence-grounded follow-up recommendations" in message
    assert "mechanistic hypotheses" not in message


def test_retry_message_includes_last_save_rejection_details() -> None:
    message = build_hypothesis_retry_message(
        "res_ipf_drugtarget1",
        "idiopathic pulmonary fibrosis",
        quality_errors=[
            {
                "code": "HYPOTHESIS_LAST_SAVE_REJECTION",
                "message": "The last save_hypothesis_report attempt was rejected.",
                "details": {
                    "errors": [
                        "hypotheses[5] claims direct pair axis 'EZR--MUC1' without citing a matching passed Stage 1 pair file.",
                        "GENE_LEVEL_EVIDENCE_REFERENCE_MISSING: hypotheses[5] missing available gene-level evidence references for FEATURED genes: MUC1: ot_MUC1.json, stage3_MUC1.json",
                    ],
                    "hypothesis_grounding_violations": [
                        "hypotheses[5] claims direct pair axis 'EZR--MUC1' without citing a matching passed Stage 1 pair file.",
                    ],
                },
            }
        ],
        attempt=1,
        max_attempts=3,
    )

    assert "Last rejected save attempt details" in message
    assert "EZR--MUC1" in message
    assert "MUC1: ot_MUC1.json, stage3_MUC1.json" in message
    assert "Do not invent a direct pair axis from separate hub-partner evidence" in message
    assert "Do not use synergy or synergistic effects unless direct combination evidence is cited" in message
    assert "prefer `additive or non-additive effects`" in message
    assert (
        "If a FEATURED gene is mentioned in title, core_claim, prediction, "
        "validation_approach, or biological_entities.genes"
        in message
    )


def test_retry_message_includes_depleted_stage1_repair_guidance() -> None:
    message = build_hypothesis_retry_message(
        "res_ipf_drugtarget3",
        "idiopathic pulmonary fibrosis",
        quality_errors=[
            {
                "code": "HYPOTHESIS_LAST_SAVE_REJECTION",
                "message": "The last save_hypothesis_report attempt was rejected.",
                "details": {
                    "errors": [
                        "hypotheses[1] uses target-cell-depleted Stage 1 Census evidence as interest-cell support: stage1_FN1--SDC2.json has negative target-vs-rest diff values for [gene_a, gene_b, coexpression].",
                        "hypotheses[2] uses coexpression-depleted Stage 1 Census evidence as an interest-cell intrinsic same-cell claim: stage1_ICAM1--ITGB2.json.",
                    ],
                },
            }
        ],
        attempt=2,
        max_attempts=3,
    )

    assert "Depleted Stage 1 repair" in message
    assert "remove AT2, Transitional AT2, pulmonary/alveolar epithelial" in message
    assert "resolved Census cell-type, epithelial-intrinsic, same-cell" in message
    assert "target-cell-autonomous wording" in message
    assert "from recommendations citing depleted Stage 1 files" in message
    assert (
        "use the depleted Stage 1 file only as secondary "
        "spatial-niche/cross-cell framing"
        in message
    )
    assert (
        "support target/actionability with exact stage3_<GENE>.json and "
        "ot_<GENE>.json citations"
        in message
    )
    assert (
        "`target-cell-depleted Stage 1 Census evidence as interest-cell support` "
        "error"
        in message
    )
    assert "choose exactly one repair path for the named hypothesis" in message
    assert "keep the depleted Stage 1 pair file only after rewriting" in message
    assert "secondary spatial-niche/cross-cell or non-interest-cell context" in message
    assert "remove that Stage 1 pair citation entirely" in message
    assert "gene-level/actionability-only" in message
    assert (
        "Do not leave the depleted Stage 1 file in a primary AT2/epithelial, "
        "interest-cell, same-cell, or intrinsic recommendation"
        in message
    )


def test_retry_message_names_res3_final_depleted_stage1_blocker() -> None:
    message = build_hypothesis_retry_message(
        "res_ipf_drugtarget3",
        "idiopathic pulmonary fibrosis",
        quality_errors=[
            {
                "code": "HYPOTHESIS_LAST_SAVE_REJECTION",
                "message": "The last save_hypothesis_report attempt was rejected.",
                "details": {
                    "errors": [
                        (
                            "hypotheses[2] uses target-cell-depleted Stage 1 "
                            "Census evidence as interest-cell support: "
                            "stage1_FN1--SDC2.json has negative target-vs-rest "
                            "diff values for [gene_a, gene_b, coexpression]."
                        )
                    ],
                    "hypothesis_grounding_violations": [
                        (
                            "hypotheses[2] uses target-cell-depleted Stage 1 "
                            "Census evidence as interest-cell support: "
                            "stage1_FN1--SDC2.json has negative target-vs-rest "
                            "diff values for [gene_a, gene_b, coexpression]."
                        )
                    ],
                },
            }
        ],
        attempt=1,
        max_attempts=1,
    )

    assert "stage1_FN1--SDC2.json" in message
    assert "target-cell-depleted Stage 1 Census evidence as interest-cell support" in message
    assert "choose exactly one repair path for the named hypothesis" in message
    assert "secondary spatial-niche/cross-cell or non-interest-cell context" in message
    assert "remove that Stage 1 pair citation entirely" in message
    assert "gene-level/actionability-only" in message
