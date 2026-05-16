"""Tests for the rubric-score provenance index admission (Issue #22).

Covers the per-gene rubric entries added by ``_build_provenance_index``
(Decision D2) and the example_sentence anchor preservation in
``build_expansion_schema_spec`` (Decision D3).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.agents.drug_target.tools.report_expansion_schema import (
    RUBRIC_FIELDS,
    RUBRIC_SOURCE_CLASS,
    RUBRIC_SOURCE_FILE,
    _build_provenance_index,
    _provenance_error,
    persist_drug_report_reference_card,
)


def _full_rubric(combined_total: int = 15) -> dict[str, Any]:
    """Build a rubric dict carrying all 13 fields from rubric_by_gene."""
    return {
        "classification": "validated_target",
        "priority": "high",
        "validated_total": 10,
        "exploratory_total": 5,
        "combined_total": combined_total,
        "existing_drug_evidence": 5,
        "clinical_trial_activity": 5,
        "safety_profile": 0,
        "gwas_support": 0,
        "tractability": 3,
        "biological_plausibility": 2,
        "novelty_opportunity": 0,
        "stage3_candidate": True,
    }


def _featured_card(
    gene: str,
    *,
    rubric: dict[str, Any] | None = None,
    with_stage3: bool = True,
) -> dict[str, Any]:
    card: dict[str, Any] = {"gene": gene}
    if with_stage3:
        card["stage3"] = {
            "clinical_drugs": [{"name": f"{gene}-drug"}],
            "preclinical_compounds": [{"name": f"{gene}-cpd"}],
        }
    if rubric is not None:
        card["rubric"] = rubric
    return card


def _reference_card(cards: list[dict[str, Any]]) -> dict[str, Any]:
    return {"featured_genes": cards}


# --------------------------------------------------------------------------
# T4 — index admits 13 rubric keys per gene with scalar source_value
# --------------------------------------------------------------------------
def test_build_provenance_index_admits_per_gene_rubric_fields() -> None:
    card = _reference_card(
        [
            _featured_card("CD4", rubric=_full_rubric(combined_total=15)),
            _featured_card("MUC1", rubric=_full_rubric(combined_total=14)),
        ]
    )

    index = _build_provenance_index(card)

    expected_keys = {
        f"{RUBRIC_SOURCE_FILE}::{gene}::{field}"
        for gene in ("CD4", "MUC1")
        for field in RUBRIC_FIELDS
    }
    assert expected_keys.issubset(index.keys())
    # 13 fields × 2 genes = 26 rubric entries.
    rubric_keys = [k for k in index if k.startswith(f"{RUBRIC_SOURCE_FILE}::")]
    assert len(rubric_keys) == 26

    cd4_combined = index[f"{RUBRIC_SOURCE_FILE}::CD4::combined_total"]
    assert cd4_combined == {
        "source_file": RUBRIC_SOURCE_FILE,
        "source_field": "CD4::combined_total",
        "source_class": RUBRIC_SOURCE_CLASS,
        "source_value": 15,
    }
    # Confirm scalar — not wrapped in a list.
    assert not isinstance(cd4_combined["source_value"], (list, dict))
    # MUC1 isolated from CD4.
    muc1_combined = index[f"{RUBRIC_SOURCE_FILE}::MUC1::combined_total"]
    assert muc1_combined["source_value"] == 14


# --------------------------------------------------------------------------
# T5 — validator accepts gene-prefixed rubric citation
# --------------------------------------------------------------------------
def test_provenance_error_accepts_gene_prefixed_rubric_citation() -> None:
    card = _reference_card([_featured_card("CD4", rubric=_full_rubric())])
    index = _build_provenance_index(card)

    sentence = {
        "text": "CD4 achieves a combined score of 15.",
        "source_fields": ["combined_total"],
        "source_provenance": {
            "source_file": RUBRIC_SOURCE_FILE,
            "source_field": "CD4::combined_total",
            "source_class": RUBRIC_SOURCE_CLASS,
            "claim_type": "direct_value",
            "source_value": 15,
        },
    }

    assert _provenance_error(sentence, index) is None


# --------------------------------------------------------------------------
# T6 — fabricated source_field rejected; gene-scoping at KEY level only
# --------------------------------------------------------------------------
def test_provenance_error_rejects_fabricated_gene_field() -> None:
    card = _reference_card([_featured_card("CD4", rubric=_full_rubric())])
    index = _build_provenance_index(card)

    fabricated = {
        "text": "CD4 has a fabricated metric.",
        "source_fields": ["nonexistent_field"],
        "source_provenance": {
            "source_file": RUBRIC_SOURCE_FILE,
            "source_field": "CD4::nonexistent_field",
            "source_class": RUBRIC_SOURCE_CLASS,
            "claim_type": "direct_value",
            "source_value": 99,
        },
    }

    err = _provenance_error(fabricated, index)
    assert isinstance(err, dict)
    assert err["code"] == "SOURCE_PROVENANCE_MISSING"


def test_provenance_error_does_not_parse_prose_gene_attribution() -> None:
    """Document the contract: gene-scoping protection lives in the KEY,
    not the sentence prose. A sentence whose text names gene MUC1 but
    submits CD4's rubric key passes validation because the validator
    never parses prose. The protection model relies on the LLM emitting
    correct (gene, key) pairs guided by the prompt."""
    card = _reference_card(
        [
            _featured_card("CD4", rubric=_full_rubric(combined_total=15)),
            _featured_card("MUC1", rubric=_full_rubric(combined_total=14)),
        ]
    )
    index = _build_provenance_index(card)

    misattributed = {
        "text": "MUC1 achieves a combined score of 15.",  # prose: MUC1
        "source_fields": ["combined_total"],
        "source_provenance": {
            "source_file": RUBRIC_SOURCE_FILE,
            "source_field": "CD4::combined_total",  # key: CD4
            "source_class": RUBRIC_SOURCE_CLASS,
            "claim_type": "direct_value",
            "source_value": 15,
        },
    }

    # Validator passes — prose-level mismatch is out of scope.
    assert _provenance_error(misattributed, index) is None


# --------------------------------------------------------------------------
# T7 — example_sentence anchors on drug-evidence key (D3)
# --------------------------------------------------------------------------
def test_expansion_schema_spec_anchors_example_on_drug_evidence(
    tmp_path: Path,
) -> None:
    card = _reference_card(
        [
            _featured_card("CD4", rubric=_full_rubric()),
            _featured_card("MUC1", rubric=_full_rubric()),
        ]
    )

    persist_drug_report_reference_card(tmp_path, card)

    spec_path = tmp_path / "expansion_schema_spec.json"
    spec = json.loads(spec_path.read_text())

    anchor_file = spec["example_sentence"]["source_provenance"]["source_file"]
    assert anchor_file.startswith("evidence/ot_") or anchor_file.startswith(
        "evidence/stage3_"
    )
    # Rubric file must NOT be the anchor (D3).
    assert not anchor_file.startswith(RUBRIC_SOURCE_FILE)


# --------------------------------------------------------------------------
# T8 — empty rubric dict emits no rubric entries, no crash
# --------------------------------------------------------------------------
def test_build_provenance_index_empty_rubric_emits_no_rubric_entries() -> None:
    card = _reference_card([_featured_card("CD4", rubric={})])

    index = _build_provenance_index(card)

    rubric_keys = [k for k in index if k.startswith(f"{RUBRIC_SOURCE_FILE}::")]
    assert rubric_keys == []
    # Drug-evidence entries still present.
    assert "evidence/ot_CD4.json::clinical_drugs" in index


# --------------------------------------------------------------------------
# T9 — missing rubric key on card → graceful skip (no KeyError)
# --------------------------------------------------------------------------
def test_build_provenance_index_missing_rubric_key_skipped() -> None:
    card = _reference_card(
        [_featured_card("CD4", rubric=None, with_stage3=True)]
    )

    # Should not raise.
    index = _build_provenance_index(card)

    rubric_keys = [k for k in index if k.startswith(f"{RUBRIC_SOURCE_FILE}::")]
    assert rubric_keys == []
    assert "evidence/ot_CD4.json::clinical_drugs" in index


# --------------------------------------------------------------------------
# Edge cases — partial rubric (subset of 13 fields)
# --------------------------------------------------------------------------
def test_build_provenance_index_partial_rubric_emits_only_present_fields() -> None:
    partial_rubric = {
        "combined_total": 12,
        "classification": "validated_target",
    }
    card = _reference_card(
        [_featured_card("CD4", rubric=partial_rubric)]
    )

    index = _build_provenance_index(card)

    rubric_keys = [k for k in index if k.startswith(f"{RUBRIC_SOURCE_FILE}::")]
    assert sorted(rubric_keys) == sorted(
        [
            f"{RUBRIC_SOURCE_FILE}::CD4::combined_total",
            f"{RUBRIC_SOURCE_FILE}::CD4::classification",
        ]
    )


# --------------------------------------------------------------------------
# Sanity: drug-evidence entries shape unchanged (regression check)
# --------------------------------------------------------------------------
def test_drug_evidence_entries_shape_unchanged() -> None:
    card = _reference_card([_featured_card("CD4", rubric=_full_rubric())])

    index = _build_provenance_index(card)

    entry = index["evidence/ot_CD4.json::clinical_drugs"]
    assert entry["source_file"] == "evidence/ot_CD4.json"
    assert entry["source_field"] == "clinical_drugs"
    assert entry["source_class"] == "opentargets_clinical"
    assert entry["source_value"] == [{"name": "CD4-drug"}]
