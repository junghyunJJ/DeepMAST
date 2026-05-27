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
        "ICAM1",
        "ITGB2",
        "CD47",
    ]
    assert synthesis["candidate_counts"]["featured"] == 3
    assert synthesis["candidate_counts"]["total"] >= 3
    assert synthesis["hypotheses"]
    assert synthesis["selection_strategy"] == (
        "deterministic_mechanistic_axis_and_drug_evidence"
    )


def test_part4_synthesis_data_preserves_candidate_evidence_context(
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
        interpretations_payload=None,
    )

    candidate = synthesis["featured_candidates"][0]
    score_profile = {
        "combined_total": 10,
        "validated_total": 7,
        "exploratory_total": 3,
    }

    assert candidate["gene"] == "ICAM1"
    assert candidate["score_profile"] == score_profile
    assert candidate["combined_total"] == score_profile["combined_total"]
    assert candidate["validated_total"] == score_profile["validated_total"]
    assert candidate["exploratory_total"] == score_profile["exploratory_total"]
    assert candidate["evidence_track"] == "validated-dominant"
    assert (
        candidate["drug_signal_summary"]
        == "0 clinical and 10 preclinical structured drug signals"
    )
    assert candidate["clinical_drugs"] == []
    assert candidate["preclinical_drugs"] == [
        (
            "4-(4-Trifluoromethyl-phenoxy)-thieno[2,3-c]pyridine-2-carboxylic "
            "acid methylamide"
        ),
        (
            "4-[4-(Tetrahydro-pyran-2-yloxymethyl)-phenoxy]-thieno[2,3-c]"
            "pyridine-2-carboxylic acid amide"
        ),
        "4-(4-Cyano-phenoxy)-thieno[2,3-c]pyridine-2-carboxylic acid amide",
        (
            "4-{4-[2-(2-Methoxy-ethoxy)-ethoxymethyl]-phenoxy}-thieno[2,3-c]"
            "pyridine-2-carboxylic acid methylamide"
        ),
        "4-(4-Vinyl-phenoxy)-thieno[2,3-c]pyridine-2-carboxylic acid amide",
    ]
    assert candidate["evidence_sources"] == [
        "evidence/assessment_results.json",
        "evidence/stage3_ICAM1.json",
    ]
    assert candidate["source_count"] == 2
    assert "ICAM1" in candidate["therapeutic_rationale"]
    assert "high" in candidate["therapeutic_rationale"]
    assert "validated_target" in candidate["therapeutic_rationale"]
    assert "validated dominant support" in candidate["therapeutic_rationale"]
    assert candidate["mechanistic_hypothesis_count"] == 2
    assert candidate["best_hypothesis_rank"] == 1
    assert "ICAM1-ITGB2 Axis" in candidate["mechanistic_role_summary"]
    assert candidate["drug_target_evidence"].startswith("Preclinical:")


def test_part4_synthesis_data_preserves_hypothesis_context(
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
        interpretations_payload=None,
    )

    hypothesis = synthesis["hypotheses"][0]

    assert hypothesis["rank"] == 1
    assert (
        hypothesis["title"]
        == "ICAM1-ITGB2 Axis Drives Fibroblast Activation and ECM Deposition "
        "in IPF [MoA - Immune Modulation]"
    )
    assert hypothesis["category"] == "Mechanism of Action"
    assert hypothesis["genes"] == ["ICAM1", "ITGB2"]
    assert hypothesis["pathways"] == [
        "integrin signaling",
        "cell adhesion",
        "fibroblast activation",
    ]
    assert hypothesis["cell_types"] == [
        "fibroblasts",
        "immune cells",
        "alveolar type 2 cells",
    ]
    assert hypothesis["score_profile"] == {
        "actionability": 0.9,
        "composite": 0.775,
        "evidence_coverage": 0.85,
        "novelty": 0.6,
        "specificity": 0.8,
    }
    assert hypothesis["evidence_references"] == [
        "stage1_ICAM1--ITGB2.json",
        "stage3_ICAM1.json",
        "ot_ICAM1.json",
        "stage3_ITGB2.json",
        "ot_ITGB2.json",
    ]
    assert hypothesis["source_count"] == 5
    assert (
        "ICAM1-ITGB2 interaction forms a critical adhesion signaling hub"
        in hypothesis["core_claim"]
    )
    assert (
        "blocking the ICAM1-ITGB2 interaction with Lifitegrast"
        in hypothesis["falsifiable_prediction"]
    )
    assert (
        "Primary IPF fibroblast cultures treated with Lifitegrast"
        in hypothesis["validation_approach"]
    )


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
    assert "## Mechanistic Intervention Map" in markdown
    assert "## Validation Next Steps" in markdown
    assert "## Confidence and Caveats" in markdown
    assert "ICAM1" in markdown
    assert "ITGB2" in markdown
    assert "CD47" in markdown
    assert "validated_target" in markdown
    assert "EXPAND" not in markdown
    assert "recommended therapy" not in markdown.lower()
    assert "standard of care" not in markdown.lower()


def test_render_part4_synthesis_has_rich_candidate_triage(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import build_report_data
    from src.agents.drug_target.therapeutic_synthesis import (
        build_part4_therapeutic_synthesis,
        render_part4_therapeutic_synthesis_markdown,
    )

    workspace = _copy_baseline_workspace(tmp_path)
    report_data = build_report_data(str(workspace), "idiopathic pulmonary fibrosis")
    markdown = render_part4_therapeutic_synthesis_markdown(
        build_part4_therapeutic_synthesis(
            report_data,
            validation=_validation_payload(),
            interpretations_payload=None,
        )
    )

    assert "## Integrated Therapeutic Thesis" in markdown
    assert "### Candidate: ICAM1" in markdown
    assert "### Candidate: ITGB2" in markdown
    assert "### Candidate: CD47" in markdown
    assert (
        "- Evidence track: validated-dominant with combined score 10 "
        "(validated 7, exploratory 3)."
    ) in markdown
    assert "- Evidence track:" in markdown
    assert "- Therapeutic rationale:" in markdown
    assert "- Drug signal:" in markdown
    assert "**Clinical Compounds (OpenTargets):**" in markdown
    assert "No named clinical compounds were available." in markdown
    assert "- Preclinical signal:" in markdown
    assert "- Mechanistic synthesis role:" in markdown
    assert "- Experimental discriminator:" in markdown
    assert "IPF cell states" not in markdown


def test_part4_synthesis_selects_primary_mechanistic_axis_before_score_top3() -> None:
    from src.agents.drug_target.therapeutic_synthesis import (
        build_part4_therapeutic_synthesis,
        render_part4_therapeutic_synthesis_markdown,
    )

    def candidate(
        gene: str,
        combined: int,
        clinical_drugs: list[dict] | None = None,
        preclinical_drugs: list[dict] | None = None,
    ) -> dict:
        clinical_drugs = clinical_drugs or []
        preclinical_drugs = preclinical_drugs or []
        return {
            "gene": gene,
            "classification": "validated_target",
            "priority": "high",
            "stage3_candidate": True,
            "scores": {
                "combined_total": combined,
                "validated_total": min(combined, 10),
                "exploratory_total": max(combined - 10, 0),
            },
            "clinical_drug_count": len(clinical_drugs),
            "preclinical_drug_count": len(preclinical_drugs),
            "clinical_drugs": clinical_drugs,
            "preclinical_drugs": preclinical_drugs,
            "sources": [f"evidence/stage3_{gene}.json"],
        }

    report_data = {
        "disease": "IPF",
        "candidates": [
            candidate("FN1", 15),
            candidate("MUC1", 15),
            candidate("CD4", 14),
            candidate(
                "CD47",
                11,
                [
                    {
                        "name": "EVORPACEPT",
                        "chembl_id": "CHEMBL4297880",
                        "phase": 2,
                        "mechanism_of_action": (
                            "Leukocyte surface antigen CD47 inhibitor"
                        ),
                        "indications": ["acute myeloid leukemia", "multiple myeloma"],
                        "source": "opentargets",
                    },
                    {
                        "name": "MAGROLIMAB",
                        "chembl_id": "CHEMBL4297985",
                        "phase": 3,
                        "mechanism_of_action": (
                            "Leukocyte surface antigen CD47 inhibitor"
                        ),
                        "indications": ["acute myeloid leukemia"],
                        "source": "opentargets",
                    },
                ],
            ),
            candidate(
                "ITGB2",
                11,
                [
                    {
                        "name": "LIFITEGRAST",
                        "chembl_id": "CHEMBL2048028",
                        "phase": 4,
                        "mechanism_of_action": (
                            "Integrin alpha-L/beta-2 (LFA-1) antagonist"
                        ),
                        "indications": ["dry eye syndrome"],
                        "source": "opentargets",
                    }
                ],
                [
                    {
                        "name": "SHOULD_NOT_RENDER_PRECLINICAL",
                        "chembl_id": "CHEMBL-PRECLINICAL",
                        "source": "chembl",
                    }
                ],
            ),
            candidate(
                "ICAM1",
                10,
                [
                    {
                        "name": "ALICAFORSEN",
                        "chembl_id": "CHEMBL2108326",
                        "phase": 3,
                        "mechanism_of_action": (
                            "Intercellular adhesion molecule-1 mRNA 3'UTR "
                            "antisense inhibitor"
                        ),
                        "indications": ["ulcerative colitis"],
                        "source": "opentargets",
                    }
                ],
            ),
        ],
        "hypotheses": [
            {
                "rank": 1,
                "title": (
                    "THBS1-CD47 and ICAM1-ITGB2 convergence defines an "
                    "immune-retention program"
                ),
                "category": "Cross-Target Interaction",
                "biological_entities": {
                    "genes": ["THBS1", "CD47", "ITGB2", "ICAM1"],
                    "drugs": [],
                },
                "scores": {"composite": 0.852},
                "evidence_references": ["stage1_ICAM1--ITGB2.json"],
            }
        ],
    }

    synthesis = build_part4_therapeutic_synthesis(
        report_data,
        validation=_validation_payload(),
        interpretations_payload=None,
    )
    markdown = render_part4_therapeutic_synthesis_markdown(synthesis)

    assert [item["gene"] for item in synthesis["featured_candidates"]] == [
        "CD47",
        "ITGB2",
        "ICAM1",
    ]
    assert "### Candidate: CD47" in markdown
    assert "### Candidate: ITGB2" in markdown
    assert "### Candidate: ICAM1" in markdown
    assert markdown.index("### Candidate: CD47") < markdown.index(
        "### Candidate: ITGB2"
    )
    assert markdown.index("### Candidate: ITGB2") < markdown.index(
        "### Candidate: ICAM1"
    )
    assert "| Drug | ChEMBL ID | Mechanism of Action | Phase | Indications |" in markdown
    assert (
        "| **EVORPACEPT** | CHEMBL4297880 | Leukocyte surface antigen CD47 "
        "inhibitor | phase 2 | acute myeloid leukemia, multiple myeloma |"
    ) in markdown
    assert (
        "| **MAGROLIMAB** | CHEMBL4297985 | Leukocyte surface antigen CD47 "
        "inhibitor | phase 3 | acute myeloid leukemia |"
    ) in markdown
    assert (
        "| **LIFITEGRAST** | CHEMBL2048028 | Integrin alpha-L/beta-2 "
        "(LFA-1) antagonist | phase 4 | dry eye syndrome |"
    ) in markdown
    assert (
        "| **ALICAFORSEN** | CHEMBL2108326 | Intercellular adhesion molecule-1 "
        "mRNA 3'UTR antisense inhibitor | phase 3 | ulcerative colitis |"
    ) in markdown
    assert "- Preclinical signal: 0 ChEMBL bioactivity records" in markdown
    assert "- Preclinical signal: 1 ChEMBL bioactivity records" in markdown
    assert "SHOULD_NOT_RENDER_PRECLINICAL" not in markdown


def test_render_part4_synthesis_has_mechanistic_intervention_map(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import build_report_data
    from src.agents.drug_target.therapeutic_synthesis import (
        build_part4_therapeutic_synthesis,
        render_part4_therapeutic_synthesis_markdown,
    )

    workspace = _copy_baseline_workspace(tmp_path)
    report_data = build_report_data(str(workspace), "idiopathic pulmonary fibrosis")
    markdown = render_part4_therapeutic_synthesis_markdown(
        build_part4_therapeutic_synthesis(
            report_data,
            validation=_validation_payload(),
            interpretations_payload=None,
        )
    )

    assert "## Mechanistic Intervention Map" in markdown
    assert (
        "### Hypothesis 1: ICAM1-ITGB2 Axis Drives Fibroblast Activation "
        "and ECM Deposition in IPF [MoA - Immune Modulation]"
    ) in markdown
    assert "**Category:** Mechanism of Action" in markdown
    assert "**Genes:** ICAM1, ITGB2" in markdown
    assert (
        "**Pathways:** integrin signaling, cell adhesion, fibroblast activation"
    ) in markdown
    assert (
        "**Cell types:** fibroblasts, immune cells, alveolar type 2 cells"
    ) in markdown
    assert "**Candidate compounds:** Lifitegrast" in markdown
    assert "**Core claim:**" in markdown
    assert "**Falsifiable prediction:**" in markdown
    assert "**Validation design:**" in markdown
    assert "**Evidence anchors:**" in markdown
    assert (
        "stage1_ICAM1--ITGB2.json, stage3_ICAM1.json, ot_ICAM1.json, "
        "stage3_ITGB2.json, ot_ITGB2.json"
    ) in markdown
    assert "**Composite score:** 0.775" in markdown


def test_render_part4_synthesis_mechanistic_map_uses_stable_fallbacks() -> None:
    from src.agents.drug_target.therapeutic_synthesis import (
        render_part4_therapeutic_synthesis_markdown,
    )

    markdown = render_part4_therapeutic_synthesis_markdown(
        {
            "disease": "idiopathic pulmonary fibrosis",
            "report_valid": True,
            "candidate_counts": {},
            "featured_candidates": [],
            "hypotheses": [
                {
                    "rank": 1,
                    "title": "Sparse deterministic hypothesis",
                    "category": "Mechanism of Action",
                    "genes": "ICAM1",
                    "pathways": None,
                    "cell_types": {"name": "fibroblasts"},
                    "drugs": [],
                    "evidence_references": None,
                }
            ],
            "interpretation_summary": {},
            "validation_issues": [],
        }
    )

    assert "### Hypothesis 1: Sparse deterministic hypothesis" in markdown
    assert (
        "No explicit core claim was available in the deterministic hypothesis "
        "artifact."
    ) in markdown
    assert (
        "No explicit falsifiable prediction was available in the deterministic "
        "hypothesis artifact."
    ) in markdown
    assert (
        "No explicit validation design was available in the deterministic "
        "hypothesis artifact."
    ) in markdown
    assert "No genes were recorded." in markdown
    assert "No pathways were recorded." in markdown
    assert "No cell types were recorded." in markdown
    assert "No evidence references were recorded." in markdown
    assert "No composite score was recorded." in markdown


def test_render_part4_synthesis_bounds_mechanistic_map_fields() -> None:
    from src.agents.drug_target.therapeutic_synthesis import (
        render_part4_therapeutic_synthesis_markdown,
    )

    long_text = "LONG_SENTINEL_" * 160
    long_items = [f"ANCHOR_{index}_" + ("X" * 200) for index in range(8)]

    markdown = render_part4_therapeutic_synthesis_markdown(
        {
            "disease": "idiopathic pulmonary fibrosis",
            "report_valid": True,
            "candidate_counts": {},
            "featured_candidates": [],
            "hypotheses": [
                {
                    "rank": 1,
                    "title": long_text,
                    "category": long_text,
                    "genes": [
                        long_text,
                        long_text,
                        long_text,
                        long_text,
                        long_text,
                        long_text,
                    ],
                    "pathways": [
                        long_text,
                        long_text,
                        long_text,
                        long_text,
                        long_text,
                        long_text,
                    ],
                    "cell_types": [
                        long_text,
                        long_text,
                        long_text,
                        long_text,
                        long_text,
                        long_text,
                    ],
                    "drugs": [
                        long_text,
                        long_text,
                        long_text,
                        long_text,
                        long_text,
                        long_text,
                    ],
                    "core_claim": long_text,
                    "falsifiable_prediction": long_text,
                    "validation_approach": long_text,
                    "evidence_references": long_items,
                    "score_profile": {"composite": long_text},
                }
            ],
            "interpretation_summary": {},
            "validation_issues": [],
        }
    )

    section = markdown.split("## Mechanistic Intervention Map", maxsplit=1)[1].split(
        "## Validation Next Steps",
        maxsplit=1,
    )[0]

    assert "## Mechanistic Intervention Map" in markdown
    assert "**Core claim:**" in section
    assert "**Falsifiable prediction:**" in section
    assert "**Validation design:**" in section
    assert "**Evidence anchors:**" in section
    assert long_text not in section
    assert "..." in section
    assert "ANCHOR_0_" in section
    assert "ANCHOR_4_" in section
    assert "ANCHOR_5_" not in section
    assert len(section) < 8_000


def test_render_part4_synthesis_candidate_triage_uses_flat_score_fallback() -> None:
    from src.agents.drug_target.therapeutic_synthesis import (
        render_part4_therapeutic_synthesis_markdown,
    )

    markdown = render_part4_therapeutic_synthesis_markdown(
        {
            "disease": "systemic sclerosis",
            "report_valid": True,
            "candidate_counts": {
                "total": 1,
                "featured": 1,
                "stage3_total": 1,
                "validated": 1,
                "exploratory": 0,
            },
            "featured_candidates": [
                {
                    "gene": "TGFB1",
                    "combined_total": 9,
                    "validated_total": 8,
                    "exploratory_total": 1,
                    "therapeutic_rationale": (
                        "TGFB1 is a deterministic candidate for fibrosis "
                        "mechanism testing."
                    ),
                    "drug_signal_summary": (
                        "1 clinical and 2 preclinical structured drug signals"
                    ),
                }
            ],
            "hypotheses": [],
            "interpretation_summary": {},
            "validation_issues": [],
        }
    )

    assert "### Candidate: TGFB1" in markdown
    assert (
        "- Evidence track: validated-dominant with combined score 9 "
        "(validated 8, exploratory 1)."
    ) in markdown
    assert "disease-relevant cell states" in markdown
    assert "IPF cell states" not in markdown


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


def test_rich_part4_synthesis_keeps_guardrails(
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

    assert "EXPAND" not in markdown
    for phrase in _FORBIDDEN_CLINICAL_PHRASES:
        assert phrase not in markdown.lower()
    assert "## 1. Executive Summary" not in markdown
    assert (
        "This report presents a comprehensive therapeutic target assessment"
        not in markdown
    )


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
    caveat_index = markdown.index("## Data Validity Caveat")
    thesis_index = markdown.index("## Integrated Therapeutic Thesis")
    triage_index = markdown.index("## Candidate Triage")

    assert caveat_index < thesis_index < triage_index
    assert "report validation status is invalid" in markdown.lower()
    assert "TEST_INVALID_ARTIFACT" in markdown
