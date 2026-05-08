from __future__ import annotations

import json
from pathlib import Path

from src.agents.drug_target.tools.report_expansion_schema import (
    canonical_json_hash,
    persist_drug_report_reference_card,
    save_report_expansions,
)


def _persist_reference(tmp_path: Path) -> str:
    ref = persist_drug_report_reference_card(
        tmp_path,
        {
            "markdown_template": "Intro\n\n<!-- EXPAND: Add summary -->\n",
            "expansion_slots": [
                {
                    "slot_id": "section:executive_summary|slot:add_summary",
                    "section": "executive_summary",
                    "slot": "add_summary",
                }
            ],
            "provenance_index": {
                "evidence/ot_CD4.json::clinical_drugs": {
                    "source_file": "evidence/ot_CD4.json",
                    "source_field": "clinical_drugs",
                    "source_class": "opentargets_clinical",
                    "source_value": ["ibalizumab"],
                },
                "evidence/stage3_CD4.json::preclinical_compounds": {
                    "source_file": "evidence/stage3_CD4.json",
                    "source_field": "preclinical_compounds",
                    "source_class": "chembl_preclinical",
                    "source_value": ["ibalizumab"],
                },
            },
        },
    )
    return canonical_json_hash(ref)


def _persist_reference_with_index(tmp_path: Path) -> str:
    ref = persist_drug_report_reference_card(
        tmp_path,
        {
            "markdown_template": "Intro\n\n<!-- EXPAND: Add summary -->\n",
            "expansion_slots": [
                {
                    "slot_id": "section:executive_summary|slot:add_summary",
                    "section": "executive_summary",
                    "slot": "add_summary",
                }
            ],
            "provenance_index": {
                "evidence/ot_CD4.json::clinical_drugs": {
                    "source_file": "evidence/ot_CD4.json",
                    "source_field": "clinical_drugs",
                    "source_class": "opentargets_clinical",
                    "source_value": ["ibalizumab"],
                }
            },
        },
    )
    return canonical_json_hash(ref)


def _base_expansion(reference_hash: str, sentence: dict) -> dict:
    return {
        "schema_version": "report_expansions.v1",
        "template_id": "drug_report.md.j2",
        "reference_card_hash": reference_hash,
        "slots": [
            {
                "slot_id": "section:executive_summary|slot:add_summary",
                "section_id": "executive_summary",
                "sentences": [sentence],
            }
        ],
    }


def test_save_report_expansions_fills_reference_card_hash(tmp_path: Path) -> None:
    reference_hash = _persist_reference_with_index(tmp_path)
    sentence = {
        "text": "CD4 has clinical-drug evidence in the local reference card. [source: clinical_drugs]",
        "source_fields": ["clinical_drugs"],
        "source_provenance": {
            "source_file": "evidence/ot_CD4.json",
            "source_field": "clinical_drugs",
            "source_class": "opentargets_clinical",
            "claim_type": "interpretation",
        },
        "interpretation": True,
        "hedging_verbs_present": True,
    }
    expansions = _base_expansion("llm-cannot-compute-this", sentence)

    result = json.loads(
        save_report_expansions.invoke(
            {"data_dir": str(tmp_path), "expansions": expansions}
        )
    )
    saved = json.loads((tmp_path / "report_expansions.json").read_text(encoding="utf-8"))

    assert result["saved"] is True, result
    assert saved["reference_card_hash"] == reference_hash
    assert saved["reference_card_hash"] != "llm-cannot-compute-this"


def test_save_report_expansions_accepts_writer_expansions_list_shape(
    tmp_path: Path,
) -> None:
    reference_hash = _persist_reference_with_index(tmp_path)
    writer_payload = {
        "schema_version": "report_expansions.v1",
        "expansions": [
            {
                "slot_id": "section:executive_summary|slot:add_summary",
                "sentences": [
                    {
                        "text": "CD4 has clinical-drug evidence in the local reference card. [source: clinical_drugs]",
                        "claim_type": "interpretation",
                        "source_fields": ["clinical_drugs"],
                        "source_provenance": [
                            {
                                "source_file": "evidence/ot_CD4.json",
                                "source_field": "clinical_drugs",
                                "source_class": "opentargets_clinical",
                            }
                        ],
                    }
                ],
            }
        ],
    }

    result = json.loads(
        save_report_expansions.invoke(
            {"data_dir": str(tmp_path), "expansions": writer_payload}
        )
    )
    saved = json.loads((tmp_path / "report_expansions.json").read_text(encoding="utf-8"))

    assert result["saved"] is True, result
    assert saved["reference_card_hash"] == reference_hash
    assert "slots" in saved
    assert "expansions" not in saved
    provenance = saved["slots"][0]["sentences"][0]["source_provenance"]
    assert provenance["claim_type"] == "interpretation"


def test_save_report_expansions_accepts_slot_level_expansions_alias(
    tmp_path: Path,
) -> None:
    reference_hash = _persist_reference_with_index(tmp_path)
    writer_payload = {
        "schema_version": "report_expansions.v1",
        "slots": [
            {
                "slot_id": "section:executive_summary|slot:add_summary",
                "expansions": [
                    {
                        "text": "CD4 has clinical-drug evidence in the local reference card. [source: clinical_drugs]",
                        "claim_type": "interpretation",
                        "source_fields": ["clinical_drugs"],
                        "source_provenance": [
                            {
                                "source_file": "evidence/ot_CD4.json",
                                "source_field": "clinical_drugs",
                                "source_class": "opentargets_clinical",
                            }
                        ],
                    }
                ],
            }
        ],
    }

    result = json.loads(
        save_report_expansions.invoke(
            {"data_dir": str(tmp_path), "expansions": writer_payload}
        )
    )
    saved = json.loads((tmp_path / "report_expansions.json").read_text(encoding="utf-8"))

    assert result["saved"] is True, result
    assert saved["reference_card_hash"] == reference_hash
    assert "expansions" not in saved["slots"][0]
    assert saved["slots"][0]["sentences"][0]["source_provenance"]["claim_type"] == "interpretation"


def test_save_report_expansions_rejects_existing_empty_required_slots(
    tmp_path: Path,
) -> None:
    _persist_reference_with_index(tmp_path)
    writer_payload = {
        "schema_version": "report_expansions.v1",
        "slots": [
            {
                "slot_id": "section:executive_summary|slot:add_summary",
                "expansions": [],
            }
        ],
    }

    result = json.loads(
        save_report_expansions.invoke(
            {"data_dir": str(tmp_path), "expansions": writer_payload}
        )
    )

    assert result["saved"] is False, result
    assert not (tmp_path / "report_expansions.json").exists()
    assert any("must include at least one sentence" in error["message"] for error in result["errors"])


def test_save_report_expansions_rejects_empty_writer_payload(
    tmp_path: Path,
) -> None:
    _persist_reference_with_index(tmp_path)
    writer_payload = {
        "report_expansions_version": "v1",
        "expansions": {},
    }

    result = json.loads(
        save_report_expansions.invoke(
            {"data_dir": str(tmp_path), "expansions": writer_payload}
        )
    )

    assert result["saved"] is False, result
    assert not (tmp_path / "report_expansions.json").exists()
    assert any("missing required slot_id" in error["message"] for error in result["errors"])


def test_save_report_expansions_maps_rubric_source_fields_to_reference_card_provenance(
    tmp_path: Path,
) -> None:
    ref = persist_drug_report_reference_card(
        tmp_path,
        {
            "markdown_template": "Intro\n\n<!-- EXPAND: Add summary -->\n",
            "expansion_slots": [
                {
                    "slot_id": "section:executive_summary|slot:add_summary",
                    "section": "executive_summary",
                    "slot": "add_summary",
                }
            ],
            "featured_genes": [
                {
                    "gene": "CD4",
                    "rubric": {
                        "combined_total": 14,
                        "classification": "validated_target",
                        "stage3_candidate": True,
                    },
                    "stage3": {},
                }
            ],
        },
    )
    writer_payload = {
        "schema_version": "report_expansions.v1",
        "expansions": [
            {
                "slot_id": "section:executive_summary|slot:add_summary",
                "sentences": [
                    {
                        "text": "CD4 remains prioritized by the rubric because its combined score is high. [source: combined_total]",
                        "claim_type": "interpretation",
                        "source_fields": ["combined_total"],
                        "source_provenance": [
                            {
                                "source_file": "evidence/ot_CD4.json",
                                "source_field": "combined_total",
                                "source_class": "opentargets_clinical",
                            }
                        ],
                    }
                ],
            }
        ],
    }

    result = json.loads(
        save_report_expansions.invoke(
            {"data_dir": str(tmp_path), "expansions": writer_payload}
        )
    )
    saved = json.loads((tmp_path / "report_expansions.json").read_text(encoding="utf-8"))
    provenance = saved["slots"][0]["sentences"][0]["source_provenance"]

    assert result["saved"] is True, result
    assert saved["reference_card_hash"] == canonical_json_hash(ref)
    assert "CD4 remains prioritized by the rubric" in saved["slots"][0]["sentences"][0]["text"]
    assert "summarized conservatively" not in saved["slots"][0]["sentences"][0]["text"]
    assert provenance == {
        "source_file": "drug_report_reference_card.json",
        "source_field": "combined_total",
        "source_class": "reference_card",
        "claim_type": "interpretation",
    }


def test_save_report_expansions_remaps_stage1_slot_from_wrong_clinical_provenance(
    tmp_path: Path,
) -> None:
    ref = persist_drug_report_reference_card(
        tmp_path,
        {
            "markdown_template": "Intro\n\n<!-- EXPAND: Add summary -->\n",
            "expansion_slots": [
                {
                    "slot_id": "section:stage1_filter|slot:filter_interpretation",
                    "section": "stage1_filter",
                    "slot": "filter_interpretation",
                }
            ],
            "provenance_index": {
                "evidence/ot_MUC1.json::clinical_drugs": {
                    "source_file": "evidence/ot_MUC1.json",
                    "source_field": "clinical_drugs",
                    "source_class": "opentargets_clinical",
                    "source_value": [],
                },
                "drug_report_reference_card.json::stage1_filter_results": {
                    "source_file": "drug_report_reference_card.json",
                    "source_field": "stage1_filter_results",
                    "source_class": "reference_card",
                    "source_value": [],
                },
            },
        },
    )
    writer_payload = {
        "schema_version": "report_expansions.v1",
        "slots": [
            {
                "slot_id": "section:stage1_filter|slot:filter_interpretation",
                "sentences": [
                    {
                        "text": "Stage 1 retained ICAM1-MUC1 with STRING support. [source: clinical_drugs]",
                        "claim_type": "interpretation",
                        "source_fields": ["clinical_drugs"],
                        "source_provenance": {
                            "source_file": "evidence/ot_MUC1.json",
                            "source_field": "clinical_drugs",
                            "source_class": "opentargets_clinical",
                        },
                    }
                ],
            }
        ],
    }

    result = json.loads(
        save_report_expansions.invoke(
            {"data_dir": str(tmp_path), "expansions": writer_payload}
        )
    )
    saved = json.loads((tmp_path / "report_expansions.json").read_text(encoding="utf-8"))
    sentence = saved["slots"][0]["sentences"][0]

    assert result["saved"] is True, result
    assert saved["reference_card_hash"] == canonical_json_hash(ref)
    assert "STRING support" not in sentence["text"]
    assert "summarized conservatively" in sentence["text"]
    assert sentence["source_fields"] == ["stage1_filter_results"]
    assert sentence["source_provenance"] == {
        "source_file": "drug_report_reference_card.json",
        "source_field": "stage1_filter_results",
        "source_class": "reference_card",
        "claim_type": "interpretation",
    }


def test_save_report_expansions_remaps_therapeutic_opportunity_slot_by_slot_id(
    tmp_path: Path,
) -> None:
    ref = persist_drug_report_reference_card(
        tmp_path,
        {
            "markdown_template": "Intro\n\n<!-- EXPAND: Add summary -->\n",
            "expansion_slots": [
                {
                    "slot_id": "section:executive_summary|slot:therapeutic_opportunities",
                    "section": "executive_summary",
                }
            ],
            "provenance_index": {
                "evidence/ot_MUC1.json::clinical_drugs": {
                    "source_file": "evidence/ot_MUC1.json",
                    "source_field": "clinical_drugs",
                    "source_class": "opentargets_clinical",
                    "source_value": [],
                },
                "drug_report_reference_card.json::stage3_candidates": {
                    "source_file": "drug_report_reference_card.json",
                    "source_field": "stage3_candidates",
                    "source_class": "reference_card",
                    "source_value": ["MUC1"],
                },
            },
        },
    )
    writer_payload = {
        "schema_version": "report_expansions.v1",
        "slots": [
            {
                "slot_id": "section:executive_summary|slot:therapeutic_opportunities",
                "sentences": [
                    {
                        "text": "The featured set includes MUC1. [source: clinical_drugs]",
                        "source_fields": ["clinical_drugs"],
                        "source_provenance": {
                            "source_file": "evidence/ot_MUC1.json",
                            "source_field": "clinical_drugs",
                            "source_class": "opentargets_clinical",
                        },
                    }
                ],
            }
        ],
    }

    result = json.loads(
        save_report_expansions.invoke(
            {"data_dir": str(tmp_path), "expansions": writer_payload}
        )
    )
    saved = json.loads((tmp_path / "report_expansions.json").read_text(encoding="utf-8"))
    sentence = saved["slots"][0]["sentences"][0]

    assert result["saved"] is True, result
    assert saved["reference_card_hash"] == canonical_json_hash(ref)
    assert "The featured set includes MUC1" not in sentence["text"]
    assert "summarized conservatively" in sentence["text"]
    assert sentence["source_fields"] == ["stage3_candidates"]
    assert sentence["source_provenance"]["source_field"] == "stage3_candidates"


def test_false_absence_claim_rejected_when_source_value_non_empty(tmp_path: Path) -> None:
    reference_hash = _persist_reference(tmp_path)
    sentence = {
        "text": "Clinical compounds are not available in source data.",
        "source_fields": ["clinical_drugs"],
        "source_provenance": {
            "source_file": "evidence/ot_CD4.json",
            "source_field": "clinical_drugs",
            "source_class": "opentargets_clinical",
            "source_value": ["ibalizumab"],
            "claim_type": "absence",
        },
        "interpretation": False,
        "hedging_verbs_present": False,
    }

    result = json.loads(
        save_report_expansions.invoke(
            {"data_dir": str(tmp_path), "expansions": _base_expansion(reference_hash, sentence)}
        )
    )

    assert result["saved"] is False
    assert any(err["code"] == "FALSE_ABSENCE_CLAIM" for err in result["errors"])


def test_source_class_conflation_is_rejected(tmp_path: Path) -> None:
    reference_hash = _persist_reference(tmp_path)
    sentence = {
        "text": "The OpenTargets clinical compounds include ibalizumab.",
        "source_fields": ["preclinical_compounds"],
        "source_provenance": {
            "source_file": "evidence/stage3_CD4.json",
            "source_field": "preclinical_compounds",
            "source_class": "opentargets_clinical",
            "source_value": ["ibalizumab"],
            "claim_type": "direct_value",
        },
        "interpretation": False,
        "hedging_verbs_present": False,
    }

    result = json.loads(
        save_report_expansions.invoke(
            {"data_dir": str(tmp_path), "expansions": _base_expansion(reference_hash, sentence)}
        )
    )

    assert result["saved"] is False
    assert any(err["code"] == "SOURCE_PROVENANCE_MISMATCH" for err in result["errors"])


def test_false_absence_uses_reference_card_provenance_index(tmp_path: Path) -> None:
    reference_hash = _persist_reference_with_index(tmp_path)
    sentence = {
        "text": "Clinical compounds are not available in source data.",
        "source_fields": ["clinical_drugs"],
        "source_provenance": {
            "source_file": "evidence/ot_CD4.json",
            "source_field": "clinical_drugs",
            "source_class": "opentargets_clinical",
            "source_value": [],
            "claim_type": "absence",
        },
        "interpretation": False,
        "hedging_verbs_present": False,
    }

    result = json.loads(
        save_report_expansions.invoke(
            {"data_dir": str(tmp_path), "expansions": _base_expansion(reference_hash, sentence)}
        )
    )

    assert result["saved"] is False
    assert any(err["code"] == "FALSE_ABSENCE_CLAIM" for err in result["errors"])


def test_missing_provenance_index_entry_is_rejected(tmp_path: Path) -> None:
    reference_hash = _persist_reference_with_index(tmp_path)
    sentence = {
        "text": "MUC1 compounds are not available in source data.",
        "source_fields": ["clinical_drugs"],
        "source_provenance": {
            "source_file": "evidence/ot_MUC1.json",
            "source_field": "clinical_drugs",
            "source_class": "opentargets_clinical",
            "source_value": [],
            "claim_type": "absence",
        },
        "interpretation": False,
        "hedging_verbs_present": False,
    }

    result = json.loads(
        save_report_expansions.invoke(
            {"data_dir": str(tmp_path), "expansions": _base_expansion(reference_hash, sentence)}
        )
    )

    assert result["saved"] is False
    assert any(err["code"] == "SOURCE_PROVENANCE_MISSING" for err in result["errors"])


def test_count_claim_must_match_reference_card_source_value(tmp_path: Path) -> None:
    reference_hash = _persist_reference_with_index(tmp_path)
    sentence = {
        "text": "CD4 has 2 clinical compounds.",
        "source_fields": ["clinical_drugs"],
        "source_provenance": {
            "source_file": "evidence/ot_CD4.json",
            "source_field": "clinical_drugs",
            "source_class": "opentargets_clinical",
            "source_value": 2,
            "claim_type": "count",
        },
        "interpretation": False,
        "hedging_verbs_present": False,
    }

    result = json.loads(
        save_report_expansions.invoke(
            {"data_dir": str(tmp_path), "expansions": _base_expansion(reference_hash, sentence)}
        )
    )

    assert result["saved"] is False
    assert any(err["code"] == "SOURCE_PROVENANCE_MISMATCH" for err in result["errors"])


def test_direct_value_must_match_reference_card_source_value(tmp_path: Path) -> None:
    reference_hash = _persist_reference_with_index(tmp_path)
    sentence = {
        "text": "CD4 clinical compounds include fabricated-drug.",
        "source_fields": ["clinical_drugs"],
        "source_provenance": {
            "source_file": "evidence/ot_CD4.json",
            "source_field": "clinical_drugs",
            "source_class": "opentargets_clinical",
            "source_value": ["fabricated-drug"],
            "claim_type": "direct_value",
        },
        "interpretation": False,
        "hedging_verbs_present": False,
    }

    result = json.loads(
        save_report_expansions.invoke(
            {"data_dir": str(tmp_path), "expansions": _base_expansion(reference_hash, sentence)}
        )
    )

    assert result["saved"] is False
    assert any(err["code"] == "SOURCE_PROVENANCE_MISMATCH" for err in result["errors"])


def test_reference_card_routes_clinical_and_preclinical_sources_by_origin(tmp_path: Path) -> None:
    card = persist_drug_report_reference_card(
        tmp_path,
        {
            "markdown_template": "Intro\n\n<!-- EXPAND: Add summary -->\n",
            "featured_genes": [
                {
                    "gene": "CD4",
                    "stage3": {
                        "clinical_drugs": ["ibalizumab"],
                        "preclinical_compounds": ["CHEMBL123"],
                    },
                }
            ],
        },
    )

    index = card["provenance_index"]
    assert index["evidence/ot_CD4.json::clinical_drugs"] == {
        "source_file": "evidence/ot_CD4.json",
        "source_field": "clinical_drugs",
        "source_class": "opentargets_clinical",
        "source_value": ["ibalizumab"],
    }
    assert index["evidence/stage3_CD4.json::preclinical_compounds"] == {
        "source_file": "evidence/stage3_CD4.json",
        "source_field": "preclinical_compounds",
        "source_class": "chembl_preclinical",
        "source_value": ["CHEMBL123"],
    }
    assert "evidence/stage3_CD4.json::clinical_drugs" not in index
