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
