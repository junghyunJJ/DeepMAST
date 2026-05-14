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
    metadata = json.loads((tmp_path / "drug_report_render.json").read_text())
    assert metadata["schema_version"] == "drug_report_render.v1"
    assert metadata["source_hashes"]["reference_card"] == reference_hash
    assert metadata["required_slot_count"] == 1
    assert metadata["rendered_slot_count"] == 1


def test_reference_card_derives_unique_gene_slot_ids_for_loop_markers(tmp_path: Path) -> None:
    ref = persist_drug_report_reference_card(tmp_path, _loop_reference_card())

    slot_ids = [slot["slot_id"] for slot in ref["expansion_slots"]]

    assert slot_ids == [
        "section:featured_candidate|gene:CD4|slot:drug_profile",
        "section:featured_candidate|gene:MUC1|slot:drug_profile",
    ]
    assert len(slot_ids) == len(set(slot_ids))
