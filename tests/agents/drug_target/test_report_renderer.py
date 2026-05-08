from __future__ import annotations

import json
from pathlib import Path

from src.agents.drug_target.tools.report_expansion_schema import (
    canonical_json_hash,
    persist_drug_report_reference_card,
    save_report_expansions,
)
from src.agents.drug_target.tools.report_renderer import (
    render_drug_md_from_expansions,
)


def _reference_card(data_dir: Path) -> dict:
    return {
        "disease": "IPF",
        "stage3_candidates": ["CD4"],
        "markdown_template": (
            "# Report\n\n"
            "### 4.1. CD4 test hypothesis\n\n"
            "<!-- EXPAND: Add summary -->\n"
        ),
        "hypothesis_data": {
            "hypotheses": [
                {
                    "rank": 1,
                    "title": "CD4 test hypothesis",
                    "gap_type": "featured_coverage",
                }
            ]
        },
        "provenance_index": {
            "evidence/stage3_CD4.json::clinical_drugs": {
                "source_file": "evidence/stage3_CD4.json",
                "source_field": "clinical_drugs",
                "source_class": "chembl_preclinical",
                "source_value": [{"drug_name": "Example"}],
            }
        },
    }


def _loop_reference_card() -> dict:
    return {
        "disease": "IPF",
        "stage3_candidates": ["CD4", "MUC1"],
        "markdown_template": (
            "# Report\n\n"
            "### CD4\n"
            "<!-- EXPAND: Describe what drugs exist and their approved indications. -->\n"
            "### MUC1\n"
            "<!-- EXPAND: Describe what drugs exist and their approved indications. -->\n"
        ),
    }


def _disease_scope() -> dict:
    return {
        "requested_disease": "idiopathic pulmonary fibrosis",
        "evidence_diseases": ["pulmonary fibrosis"],
        "requires_proxy_note": True,
        "proxy_note": (
            "Scope note: Stage 1 Census evidence for these hypotheses is labeled "
            "pulmonary fibrosis and is used here as a proxy for idiopathic pulmonary "
            "fibrosis; Section 4 statements should be read as IPF-oriented hypotheses "
            "rather than direct disease-specific proof. [source: disease_scope]"
        ),
    }


def _expansions(data_dir: Path, reference_hash: str) -> dict:
    return {
        "schema_version": "report_expansions.v1",
        "template_id": "drug_report.md.j2",
        "reference_card_hash": reference_hash,
        "slots": [
            {
                "slot_id": "section:executive_summary|slot:add_summary",
                "section_id": "executive_summary",
                "sentences": [
                    {
                        "text": "CD4 has a recorded target profile in source data.",
                        "source_fields": ["stage3.CD4.clinical_drugs"],
                        "source_provenance": {
                            "source_file": "evidence/stage3_CD4.json",
                            "source_field": "clinical_drugs",
                            "source_class": "chembl_preclinical",
                            "source_value": [{"drug_name": "Example"}],
                            "claim_type": "direct_value",
                        },
                        "interpretation": False,
                        "hedging_verbs_present": False,
                    }
                ],
            }
        ],
    }


def test_render_drug_md_from_expansions_is_deterministic_and_labels_gap(tmp_path: Path) -> None:
    ref = persist_drug_report_reference_card(tmp_path, _reference_card(tmp_path))
    reference_hash = canonical_json_hash(ref)
    saved = json.loads(
        save_report_expansions.invoke(
            {"data_dir": str(tmp_path), "expansions": _expansions(tmp_path, reference_hash)}
        )
    )
    assert saved["saved"] is True, saved

    first = json.loads(render_drug_md_from_expansions.invoke({"data_dir": str(tmp_path)}))
    first_text = (tmp_path / "drug.md").read_text(encoding="utf-8")
    second = json.loads(render_drug_md_from_expansions.invoke({"data_dir": str(tmp_path)}))
    second_text = (tmp_path / "drug.md").read_text(encoding="utf-8")

    assert first["rendered"] is True, first
    assert second["rendered"] is True, second
    assert first_text == second_text
    assert "### 4.1. [FEATURED-GAP] CD4 test hypothesis" in first_text
    assert "CD4 has a recorded target profile in source data. [source: clinical_drugs]" in first_text
    metadata = json.loads((tmp_path / "drug_report_render.json").read_text())
    assert metadata["schema_version"] == "drug_report_render.v1"
    assert metadata["source_hashes"]["reference_card"] == reference_hash
    assert metadata["required_slot_count"] == 1
    assert metadata["rendered_slot_count"] == 1


def test_render_drug_md_inserts_required_hypothesis_disease_scope_note(
    tmp_path: Path,
) -> None:
    ref = persist_drug_report_reference_card(
        tmp_path,
        {
            "disease": "idiopathic pulmonary fibrosis",
            "stage3_candidates": [],
            "markdown_template": (
                "# Report\n\n"
                "## 4. Hypothesis-Driven Analysis\n\n"
                "Evidence coverage: 100% (1 hypotheses retained from 1 generated)\n\n"
                "### 4.1. Test hypothesis\n\n"
                "**Core Claim:** In idiopathic pulmonary fibrosis, a test claim is made.\n"
            ),
            "disease_scope": _disease_scope(),
            "provenance_index": {
                "drug_report_reference_card.json::disease_scope": {
                    "source_file": "drug_report_reference_card.json",
                    "source_field": "disease_scope",
                    "source_class": "reference_card",
                    "source_value": _disease_scope(),
                }
            },
        },
    )
    reference_hash = canonical_json_hash(ref)
    saved = json.loads(
        save_report_expansions.invoke(
            {
                "data_dir": str(tmp_path),
                "expansions": {
                    "schema_version": "report_expansions.v1",
                    "reference_card_hash": reference_hash,
                    "slots": [],
                },
            }
        )
    )
    assert saved["saved"] is True, saved

    result = json.loads(render_drug_md_from_expansions.invoke({"data_dir": str(tmp_path)}))
    text = (tmp_path / "drug.md").read_text(encoding="utf-8")

    assert result["rendered"] is True, result
    assert _disease_scope()["proxy_note"] in text
    assert text.index(_disease_scope()["proxy_note"]) < text.index("**Core Claim:**")


def test_reference_card_derives_unique_gene_slot_ids_for_loop_markers(tmp_path: Path) -> None:
    ref = persist_drug_report_reference_card(tmp_path, _loop_reference_card())

    slot_ids = [slot["slot_id"] for slot in ref["expansion_slots"]]

    assert slot_ids == [
        "section:featured_candidate|gene:CD4|slot:drug_profile",
        "section:featured_candidate|gene:MUC1|slot:drug_profile",
    ]
    assert len(slot_ids) == len(set(slot_ids))


def test_reference_card_drug_profile_marker_wins_over_negative_therapeutic_opportunity_phrase(
    tmp_path: Path,
) -> None:
    ref = persist_drug_report_reference_card(
        tmp_path,
        {
            "disease": "IPF",
            "stage3_candidates": ["MUC1", "FN1"],
            "markdown_template": (
                "# Report\n\n"
                "### MUC1\n"
                "<!-- EXPAND: Describe what drugs exist and their approved indications. "
                "Do NOT speculate about repurposing potential or therapeutic opportunities "
                "for the study disease. State only what is known from the listed data. -->\n"
                "### FN1\n"
                "<!-- EXPAND: Describe what drugs exist and their approved indications. "
                "Do NOT speculate about repurposing potential or therapeutic opportunities "
                "for the study disease. State only what is known from the listed data. -->\n"
            ),
        },
    )

    slot_ids = [slot["slot_id"] for slot in ref["expansion_slots"]]

    assert slot_ids == [
        "section:featured_candidate|gene:MUC1|slot:drug_profile",
        "section:featured_candidate|gene:FN1|slot:drug_profile",
    ]
    assert len(slot_ids) == len(set(slot_ids))


def test_render_drug_md_from_expansions_cites_stage1_census_lines(
    tmp_path: Path,
) -> None:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "stage1_ICAM1--MUC1.json").write_text("{}", encoding="utf-8")
    ref = persist_drug_report_reference_card(
        tmp_path,
        {
            **_reference_card(tmp_path),
            "markdown_template": (
                "# Report\n\n"
                "- **ICAM1–MUC1**: STRING PPI score=0.9, interaction=confirmed\n"
                "  - Census: risk_ratio=17.863, p_value=0.0\n\n"
                "<!-- EXPAND: Add summary -->\n"
            ),
        },
    )
    reference_hash = canonical_json_hash(ref)
    saved = json.loads(
        save_report_expansions.invoke(
            {"data_dir": str(tmp_path), "expansions": _expansions(tmp_path, reference_hash)}
        )
    )
    assert saved["saved"] is True, saved

    rendered = json.loads(render_drug_md_from_expansions.invoke({"data_dir": str(tmp_path)}))
    text = (tmp_path / "drug.md").read_text(encoding="utf-8")

    assert rendered["rendered"] is True, rendered
    assert (
        "  - Census: risk_ratio=17.863, p_value=0.0 "
        "[from stage1_ICAM1--MUC1.json]"
    ) in text


def test_render_drug_md_from_expansions_labels_low_rr_as_not_enrichment(
    tmp_path: Path,
) -> None:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "stage1_HLA-DQB1--CD4.json").write_text("{}", encoding="utf-8")
    ref = persist_drug_report_reference_card(
        tmp_path,
        {
            **_reference_card(tmp_path),
            "markdown_template": (
                "# Report\n\n"
                "- **HLA-DQB1–CD4**: STRING PPI score=0.951, interaction=confirmed\n"
                "  - Census: risk_ratio=0.0523, p_value=0.0\n\n"
                "<!-- EXPAND: Add summary -->\n"
            ),
        },
    )
    reference_hash = canonical_json_hash(ref)
    saved = json.loads(
        save_report_expansions.invoke(
            {"data_dir": str(tmp_path), "expansions": _expansions(tmp_path, reference_hash)}
        )
    )
    assert saved["saved"] is True, saved

    rendered = json.loads(render_drug_md_from_expansions.invoke({"data_dir": str(tmp_path)}))
    text = (tmp_path / "drug.md").read_text(encoding="utf-8")

    assert rendered["rendered"] is True, rendered
    assert (
        "  - Census: risk_ratio=0.0523, p_value=0.0 "
        "(direction=lower_target_vs_rest; RR<1 is not enrichment) "
        "[from stage1_HLA-DQB1--CD4.json]"
    ) in text


def test_render_drug_md_from_expansions_suppresses_hypothesis_fallback_text(
    tmp_path: Path,
) -> None:
    ref = persist_drug_report_reference_card(
        tmp_path,
        {
            "disease": "IPF",
            "stage3_candidates": [],
            "markdown_template": (
                "# Report\n\n"
                "## 4. Hypothesis-Driven Analysis\n\n"
                "<!-- EXPAND: Add 2-3 sentences summarizing the hypothesis generation "
                "approach and key themes -->\n"
            ),
            "hypothesis_data": {"hypotheses": []},
            "provenance_index": {
                "drug_report_reference_card.json::hypothesis_data": {
                    "source_file": "drug_report_reference_card.json",
                    "source_field": "hypothesis_data",
                    "source_class": "reference_card",
                    "source_value": {"hypotheses": []},
                }
            },
        },
    )
    reference_hash = canonical_json_hash(ref)
    expansions = {
        "schema_version": "report_expansions.v1",
        "template_id": "drug_report.md.j2",
        "reference_card_hash": reference_hash,
        "slots": [
            {
                "slot_id": "section:hypothesis_summary|slot:themes",
                "section_id": "hypothesis_summary",
                "sentences": [
                    {
                        "text": (
                            "hypothesis summary summary is summarized conservatively from "
                            "the current reference card and should be interpreted as "
                            "evidence-limited local context. [source: hypothesis_data]"
                        ),
                        "source_fields": ["hypothesis_data"],
                        "source_provenance": {
                            "source_file": "drug_report_reference_card.json",
                            "source_field": "hypothesis_data",
                            "source_class": "reference_card",
                        },
                    }
                ],
            }
        ],
    }
    saved = json.loads(
        save_report_expansions.invoke(
            {"data_dir": str(tmp_path), "expansions": expansions}
        )
    )
    assert saved["saved"] is True, saved

    rendered = json.loads(render_drug_md_from_expansions.invoke({"data_dir": str(tmp_path)}))
    text = (tmp_path / "drug.md").read_text(encoding="utf-8")

    assert rendered["rendered"] is True, rendered
    assert "hypothesis summary" not in text
    assert "<!-- EXPAND" not in text


def test_render_drug_md_from_expansions_removes_empty_gap_analysis(
    tmp_path: Path,
) -> None:
    ref = persist_drug_report_reference_card(
        tmp_path,
        {
            **_reference_card(tmp_path),
            "markdown_template": (
                "# Report\n\n"
                "### Gap Analysis\n\n\n"
                "## 5. Pipeline Summary\n\n"
                "<!-- EXPAND: Add summary -->\n"
            ),
        },
    )
    reference_hash = canonical_json_hash(ref)
    saved = json.loads(
        save_report_expansions.invoke(
            {"data_dir": str(tmp_path), "expansions": _expansions(tmp_path, reference_hash)}
        )
    )
    assert saved["saved"] is True, saved

    rendered = json.loads(render_drug_md_from_expansions.invoke({"data_dir": str(tmp_path)}))
    text = (tmp_path / "drug.md").read_text(encoding="utf-8")

    assert rendered["rendered"] is True, rendered
    assert "### Gap Analysis" not in text
    assert "## 5. Pipeline Summary" in text
