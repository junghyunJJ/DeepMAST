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


def test_retry_message_names_available_reverse_stage1_pair_repair() -> None:
    message = build_hypothesis_retry_message(
        "res_ipf_drugtarget1",
        "idiopathic pulmonary fibrosis",
        quality_errors=[
            {
                "code": "HYPOTHESIS_LAST_SAVE_REJECTION",
                "message": "The last save_hypothesis_report attempt was rejected.",
                "details": {
                    "errors": [
                        (
                            "hypotheses[0] claims direct pair axis 'ITGB2--ICAM1' "
                            "without citing a matching passed Stage 1 pair file. "
                            "Expected stage1_ITGB2--ICAM1.json or "
                            "stage1_ICAM1--ITGB2.json; available: "
                            "stage1_ICAM1--ITGB2.json (passed=true)."
                        )
                    ],
                },
            }
        ],
        attempt=1,
        max_attempts=3,
    )

    assert "stage1_ICAM1--ITGB2.json" in message
    assert "cite that exact filename" in message
    assert "remove the direct pair-axis wording" in message
    assert "equivalent for direct pair support only when the cited file is a passed" in message
    assert "present in evidence_references" in message


def test_retry_message_includes_topn_missing_repair_guidance() -> None:
    message = build_hypothesis_retry_message(
        "res_bc_drugtarget",
        "breast cancer",
        quality_errors=[
            {
                "code": "HYPOTHESIS_LAST_SAVE_REJECTION",
                "message": "The last save_hypothesis_report attempt was rejected.",
                "details": {
                    "errors": [
                        "TOPN_COVERAGE_MISSING: topn_missing=['NECTIN4'] after save_hypothesis_report validation."
                    ],
                },
            }
        ],
        attempt=2,
        max_attempts=3,
    )

    assert "[FEATURED-GAP]" in message
    assert "NECTIN4" in message
    assert "stage3_<GENE>.json" in message
    assert "ot_<GENE>.json" in message
    assert "Do NOT retry the same payload" in message


def test_retry_message_includes_interest_cell_validation_repair_guidance() -> None:
    message = build_hypothesis_retry_message(
        "res_bc_drugtarget",
        "breast cancer",
        quality_errors=[
            {
                "code": "HYPOTHESIS_LAST_SAVE_REJECTION",
                "message": "The last save_hypothesis_report attempt was rejected.",
                "details": {
                    "errors": [
                        (
                            "hypotheses[0] cites target-cell-intrinsic Stage 1 "
                            "evidence (stage1_CDH1--ERBB3.json) but "
                            "validation_approach does not test the original "
                            "interest label, resolved Census cell type, or "
                            "pulmonary/alveolar epithelial equivalent."
                        ),
                        (
                            "hypotheses[2] cites target-cell-intrinsic Stage 1 "
                            "evidence (stage1_EGF--ERBB2.json) but "
                            "biological_entities.cell_types does not include "
                            "the original interest label, resolved Census cell "
                            "type, or pulmonary/alveolar epithelial equivalent."
                        ),
                    ],
                },
            }
        ],
        attempt=2,
        max_attempts=3,
    )

    assert "Interest-cell validation repair" in message
    assert "malignant cell" in message
    assert "Prolif Invasive Tumor" in message
    assert "validation_approach" in message
    assert "biological_entities.cell_types" in message
    assert "stage1_CDH1--ERBB3.json" in message
    assert "stage1_EGF--ERBB2.json" in message


def test_retry_message_includes_invalid_reference_repair_guidance() -> None:
    message = build_hypothesis_retry_message(
        "res_bc_drugtarget",
        "breast cancer",
        quality_errors=[
            {
                "code": "HYPOTHESIS_LAST_SAVE_REJECTION",
                "message": "The last save_hypothesis_report attempt was rejected.",
                "details": {
                    "errors": [
                        "hypotheses[1].evidence_references cites 'stage3_CD47.json' which is not in evidence/ directory.",
                        "hypotheses[2].evidence_references cites Stage 1 pair 'CD47--ERBB3' without proven passed=true status (no passing Stage 1 filter entry found for 'CD47--ERBB3'). Stage 1 pair citations must be eligible hypothesis evidence.",
                    ],
                },
            }
        ],
        attempt=1,
        max_attempts=3,
    )

    assert "Invalid citation repair" in message
    assert "validate_evidence_references" in message
    assert "available_files" in message
    assert "eligible_stage1_pair_files" in message
    assert "NEVER invent filenames" in message
    assert "stage3_CD47.json" in message
    assert "CD47--ERBB3" in message


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
    assert "original interest label" in message
    assert "resolved Census cell type such as malignant cell" in message
    assert "legacy AT2, Transitional AT2, pulmonary/alveolar epithelial" in message
    assert "epithelial-intrinsic, same-cell" in message
    assert "target-cell-autonomous wording" in message
    assert "from recommendations citing depleted Stage 1 files" in message
    assert "cannot support primary interest-cell intrinsic" in message
    assert "same-cell, or target-cell-autonomous wording" in message
    assert (
        "`target-cell-depleted Stage 1 Census evidence as interest-cell support` "
        "error"
        in message
    )
    assert "choose exactly one repair path for the named hypothesis" in message
    assert "keep the depleted Stage 1 pair file only after rewriting" in message
    assert "secondary cross-cell or non-interest-cell context" in message
    assert "use spatial-niche only if cited Stage 1 or spatial evidence" in message
    assert "remove that Stage 1 pair citation entirely" in message
    assert "gene-level/actionability-only" in message
    assert (
        "Do not leave the depleted Stage 1 file in a primary interest-cell, "
        "legacy AT2/epithelial, same-cell, or intrinsic recommendation"
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
    assert "secondary cross-cell or non-interest-cell context" in message
    assert "use spatial-niche only if cited Stage 1 or spatial evidence" in message
    assert "remove that Stage 1 pair citation entirely" in message
    assert "gene-level/actionability-only" in message


def test_retry_message_includes_evidence_scope_guardrails() -> None:
    message = build_hypothesis_retry_message(
        "res_ipf_drugtarget3",
        "idiopathic pulmonary fibrosis",
        quality_errors=[
            {
                "code": "HYPOTHESIS_GROUNDING_VIOLATION",
                "message": "One or more hypotheses make claims that are not grounded by cited evidence.",
                "details": {
                    "hypothesis_grounding_violations": [
                        (
                            "hypotheses[0] labels gene-level evidence as spatial/Stage1 "
                            "without citing Stage 1/spatial support."
                        )
                    ]
                },
            }
        ],
        attempt=1,
        max_attempts=3,
    )

    assert "Evidence scope guardrails" in message
    assert "Every recommendation section must be written only from cited Evidence References" in message
    assert "If no Stage 1 Census or spatial file is cited" in message
    assert "do not call the recommendation spatial-niche" in message
    assert "gene-level follow-up or actionability follow-up" in message
    assert "If only one gene in a pair has ot_<GENE>.json or stage3_<GENE>.json evidence" in message
    assert "state target-disease support or actionability only for that gene" in message
    assert "Do not describe both genes as equally actionable" in message
    assert (
        "Prefer `perturbation/actionability follow-up candidate` over "
        "`therapeutic intervention candidate`"
        in message
    )
    assert (
        "Prefer `additive or non-additive effects` over `synergistic effects` "
        "unless direct combination evidence is cited"
        in message
    )
    assert "test whether perturbation changes cited cellular readouts" in message
