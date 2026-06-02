from __future__ import annotations

from src.agents.drug_target.tools.census_celltype_resolution import (
    resolve_celltype_matches,
)


def test_resolve_celltype_matches_exact_label() -> None:
    available = {
        "pulmonary alveolar type 2 cell": 7545,
        "fibroblast": 1000,
    }

    result = resolve_celltype_matches(
        ["pulmonary alveolar type 2 cell"],
        available,
        disease="pulmonary fibrosis",
        organism="homo_sapiens",
        disease_resolved="pulmonary fibrosis",
        disease_resolution_mode="exact",
    )

    match = result["matches"][0]
    assert result["primary_resolved_celltype"] == "pulmonary alveolar type 2 cell"
    assert match["input_celltype"] == "pulmonary alveolar type 2 cell"
    assert match["matched_celltype"] == "pulmonary alveolar type 2 cell"
    assert match["match_mode"] == "exact"
    assert match["confidence"] == "high"
    assert match["literal_exact_match"] is True
    assert match["literal_substring_match"] is True
    assert match["lost_modifiers"] == []
    assert match["total_cell_count"] == 7545


def test_resolve_celltype_matches_at2_alias() -> None:
    available = {
        "pulmonary alveolar type 2 cell": 7545,
        "pulmonary alveolar epithelial cell": 73,
        "fibroblast": 1000,
    }

    result = resolve_celltype_matches(
        ["AT2"],
        available,
        disease="pulmonary fibrosis",
        organism="homo_sapiens",
        disease_resolved="pulmonary fibrosis",
        disease_resolution_mode="exact",
    )

    match = result["matches"][0]
    assert result["primary_input_celltype"] == "AT2"
    assert result["primary_resolved_celltype"] == "pulmonary alveolar type 2 cell"
    assert match["match_mode"] == "alias"
    assert match["confidence"] == "high"
    assert match["literal_exact_match"] is False
    assert match["literal_substring_match"] is False
    assert match["lost_modifiers"] == []
    assert match["warnings"] == []


def test_resolve_celltype_matches_type_ii_alias() -> None:
    available = {
        "pulmonary alveolar type 2 cell": 10,
    }

    result = resolve_celltype_matches(
        ["type II"],
        available,
        disease="pulmonary fibrosis",
        organism="homo_sapiens",
        disease_resolved="pulmonary fibrosis",
        disease_resolution_mode="exact",
    )

    match = result["matches"][0]
    assert result["primary_input_celltype"] == "type II"
    assert result["primary_resolved_celltype"] == "pulmonary alveolar type 2 cell"
    assert match["matched_celltype"] == "pulmonary alveolar type 2 cell"
    assert match["match_mode"] == "alias"


def test_resolve_celltype_matches_transitional_at2_records_lost_modifier() -> None:
    available = {
        "pulmonary alveolar type 2 cell": 7545,
        "pulmonary alveolar epithelial cell": 73,
        "fibroblast": 1000,
    }

    result = resolve_celltype_matches(
        ["AT2", "Transitional AT2"],
        available,
        disease="pulmonary fibrosis",
        organism="homo_sapiens",
        disease_resolved="pulmonary fibrosis",
        disease_resolution_mode="exact",
    )

    first, second = result["matches"]
    assert first["matched_celltype"] == "pulmonary alveolar type 2 cell"
    assert second["input_celltype"] == "Transitional AT2"
    assert second["matched_celltype"] == "pulmonary alveolar type 2 cell"
    assert second["match_mode"] == "state_stripped_alias"
    assert second["confidence"] == "medium"
    assert second["lost_modifiers"] == ["transitional"]
    assert "transitional" in second["warnings"][0]
    assert result["primary_resolved_celltype"] == "pulmonary alveolar type 2 cell"


def test_resolve_celltype_matches_unresolved_keeps_primary_empty() -> None:
    available = {
        "fibroblast": 1000,
        "macrophage": 500,
    }

    result = resolve_celltype_matches(
        ["AT2"],
        available,
        disease="pulmonary fibrosis",
        organism="homo_sapiens",
        disease_resolved="pulmonary fibrosis",
        disease_resolution_mode="exact",
    )

    match = result["matches"][0]
    assert result["primary_resolved_celltype"] == ""
    assert match["matched_celltype"] == ""
    assert match["match_mode"] == "unresolved"
    assert match["confidence"] == "none"
    assert match["warnings"] == [
        "No Census cell_type label matched interest cell type 'AT2'."
    ]
