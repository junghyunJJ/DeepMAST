from __future__ import annotations

import json
from pathlib import Path

from src.agents.drug_target.tools import census_batch_core
from src.agents.drug_target.tools import census_celltype_resolution as resolution
from src.agents.drug_target.tools.census_celltype_resolution import (
    apply_semantic_celltype_proxy_to_result,
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


def test_tumor_cell_requires_explicit_semantic_proxy() -> None:
    available = {
        "malignant cell": 576171,
        "macrophage": 80485,
    }

    result = resolve_celltype_matches(
        ["tumor cell"],
        available,
        disease="breast cancer",
        organism="homo_sapiens",
        disease_resolved="breast cancer",
        disease_resolution_mode="exact",
    )

    match = result["matches"][0]
    assert result["primary_resolved_celltype"] == ""
    assert result["primary_match_mode"] == "unresolved"
    assert match["matched_celltype"] == ""
    assert match["match_mode"] == "unresolved"

    updated = apply_semantic_celltype_proxy_to_result(
        result,
        available_celltype_options=[
            {"label": "malignant cell", "total_cell_count": 576171},
            {"label": "macrophage", "total_cell_count": 80485},
        ],
        input_celltype="tumor cell",
        matched_celltype="malignant cell",
        rationale="Agent selected malignant cell from saved Census options.",
        confidence="medium",
        candidate_labels_considered=["malignant cell"],
    )

    assert updated["primary_resolved_celltype"] == "malignant cell"
    assert updated["primary_match_mode"] == "semantic_proxy"
    assert updated["errors"] == []


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


def test_resolve_celltype_matches_transitional_fibroblast_records_lost_modifier() -> None:
    available = {
        "fibroblast": 1000,
    }

    result = resolve_celltype_matches(
        ["Transitional fibroblast"],
        available,
        disease="pulmonary fibrosis",
        organism="homo_sapiens",
        disease_resolved="pulmonary fibrosis",
        disease_resolution_mode="exact",
    )

    match = result["matches"][0]
    assert match["matched_celltype"] == "fibroblast"
    assert match["match_mode"] == "state_stripped_exact"
    assert match["confidence"] == "medium"
    assert match["lost_modifiers"] == ["transitional"]
    assert "transitional" in match["warnings"][0]


def test_resolve_celltype_matches_activated_at2_label_records_lost_modifier() -> None:
    available = {
        "pulmonary alveolar type 2 cell": 7545,
    }

    result = resolve_celltype_matches(
        ["Activated pulmonary alveolar type 2 cell"],
        available,
        disease="pulmonary fibrosis",
        organism="homo_sapiens",
        disease_resolved="pulmonary fibrosis",
        disease_resolution_mode="exact",
    )

    match = result["matches"][0]
    assert match["matched_celltype"] == "pulmonary alveolar type 2 cell"
    assert match["match_mode"].startswith("state_stripped_")
    assert match["confidence"] == "medium"
    assert match["lost_modifiers"] == ["activated"]


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


def test_resolve_celltype_matches_returns_compact_preview_not_full_options() -> None:
    available = {
        "malignant cell": 576171,
        "macrophage": 80485,
        "fibroblast": 62959,
        "T cell": 75981,
        "rare label": 1,
    }

    result = resolve_celltype_matches(
        ["Prolif Invasive Tumor"],
        available,
        disease="breast cancer",
        organism="homo_sapiens",
        disease_resolved="breast cancer",
        disease_resolution_mode="exact",
        preview_limit=3,
    )

    assert result["primary_resolved_celltype"] == ""
    assert result["primary_match_mode"] == "unresolved"
    assert result["available_cell_type_count"] == 5
    assert result["available_celltype_preview_limit"] == 3
    assert result["available_celltype_preview"] == [
        {"label": "malignant cell", "total_cell_count": 576171},
        {"label": "macrophage", "total_cell_count": 80485},
        {"label": "T cell", "total_cell_count": 75981},
    ]
    assert "available_celltype_options" not in result


def test_resolve_census_celltypes_writes_full_options_artifact_and_returns_preview(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        resolution,
        "_resolve_disease_for_census",
        lambda disease, organism: ("breast cancer", "exact", []),
    )
    monkeypatch.setattr(
        resolution,
        "_query_available_cell_type_counts",
        lambda *, disease_resolved, organism: (
            {
                "malignant cell": 576171,
                "macrophage": 80485,
                "fibroblast": 62959,
                "rare label": 1,
            },
            [],
        ),
    )

    raw = resolution.resolve_census_celltypes.invoke(
        {
            "interest_celltypes": ["Prolif Invasive Tumor"],
            "disease": "breast cancer",
            "organism": "human",
            "data_dir": str(tmp_path),
            "preview_limit": 2,
        }
    )
    payload = json.loads(raw)

    assert payload["available_cell_type_count"] == 4
    assert payload["available_celltype_preview"] == [
        {"label": "malignant cell", "total_cell_count": 576171},
        {"label": "macrophage", "total_cell_count": 80485},
    ]
    assert payload["available_celltype_options_path"] == "evidence/census_celltype_options.json"
    assert "available_celltype_options_sha256" in payload
    assert "available_celltype_options" not in payload

    artifact = tmp_path / "evidence" / "census_celltype_options.json"
    saved = json.loads(artifact.read_text())
    assert saved["disease_resolved"] == "breast cancer"
    assert saved["available_celltype_count"] == 4
    assert saved["available_celltype_options"][0] == {
        "label": "malignant cell",
        "total_cell_count": 576171,
    }

    search_raw = resolution.search_census_celltype_options.invoke(
        {"data_dir": str(tmp_path), "query": "malignant", "top_k": 5}
    )
    search = json.loads(search_raw)
    assert search["executed"] is True
    assert search["matches"][0] == {
        "label": "malignant cell",
        "total_cell_count": 576171,
        "score": 1,
    }


def test_search_census_celltype_options_rejects_mutated_artifact_hash(
    tmp_path: Path,
) -> None:
    options = [
        {"label": "malignant cell", "total_cell_count": 576171},
        {"label": "macrophage", "total_cell_count": 80485},
    ]
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "census_celltype_options.json").write_text(
        json.dumps(
            {
                "available_celltype_options_sha256": "not-the-options-hash",
                "available_celltype_options": options,
            }
        ),
        encoding="utf-8",
    )

    raw = resolution.search_census_celltype_options.invoke(
        {"data_dir": str(tmp_path), "query": "malignant", "top_k": 5}
    )
    payload = json.loads(raw)

    assert payload["executed"] is False
    assert payload["matches"] == []
    assert any("hash mismatch" in error for error in payload["errors"])


def test_apply_semantic_celltype_proxy_accepts_label_from_full_artifact_options() -> None:
    result = resolve_celltype_matches(
        ["Prolif Invasive Tumor"],
        {"malignant cell": 576171, "macrophage": 80485},
        disease="breast cancer",
        organism="homo_sapiens",
        disease_resolved="breast cancer",
        disease_resolution_mode="exact",
        preview_limit=1,
    )
    full_options = [
        {"label": "malignant cell", "total_cell_count": 576171},
        {"label": "macrophage", "total_cell_count": 80485},
    ]

    updated = apply_semantic_celltype_proxy_to_result(
        result,
        available_celltype_options=full_options,
        input_celltype="Prolif Invasive Tumor",
        matched_celltype="malignant cell",
        rationale=(
            "The ST label denotes tumor cells; malignant cell is the closest "
            "available Census cell_type label for breast cancer."
        ),
        confidence="medium",
        lost_modifiers=["prolif", "invasive"],
        candidate_labels_considered=["malignant cell", "macrophage"],
    )

    assert updated["primary_input_celltype"] == "Prolif Invasive Tumor"
    assert updated["primary_resolved_celltype"] == "malignant cell"
    assert updated["primary_match_mode"] == "semantic_proxy"
    assert updated["errors"] == []
    match = updated["matches"][0]
    assert match["matched_celltype"] == "malignant cell"
    assert match["match_mode"] == "semantic_proxy"
    assert match["confidence"] == "medium"
    assert match["literal_exact_match"] is False
    assert match["literal_substring_match"] is False
    assert match["lost_modifiers"] == ["prolif", "invasive"]
    assert match["candidate_labels_considered"] == ["malignant cell", "macrophage"]
    assert match["semantic_proxy_rationale"].startswith("The ST label denotes")
    assert "semantic proxy" in match["warnings"][0]


def test_apply_semantic_celltype_proxy_tool_reads_full_artifact_options(
    tmp_path: Path,
) -> None:
    options = [
        {"label": "malignant cell", "total_cell_count": 576171},
        {"label": "macrophage", "total_cell_count": 80485},
    ]
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "census_celltype_options.json").write_text(
        json.dumps(
            {
                "available_celltype_options_sha256": resolution._options_sha256(
                    options
                ),
                "available_celltype_options": options,
            }
        ),
        encoding="utf-8",
    )
    result = resolve_celltype_matches(
        ["Prolif Invasive Tumor"],
        {"malignant cell": 576171, "macrophage": 80485},
        disease="breast cancer",
        organism="homo_sapiens",
        disease_resolved="breast cancer",
        disease_resolution_mode="exact",
        preview_limit=1,
    )

    raw = resolution.apply_semantic_celltype_proxy.invoke(
        {
            "resolution_result": result,
            "data_dir": str(tmp_path),
            "input_celltype": "Prolif Invasive Tumor",
            "matched_celltype": "malignant cell",
            "rationale": "Agent selected malignant cell from saved Census options.",
            "confidence": "medium",
        }
    )
    payload = json.loads(raw)

    assert payload["primary_resolved_celltype"] == "malignant cell"
    assert payload["primary_match_mode"] == "semantic_proxy"
    assert payload["matches"][0]["match_mode"] == "semantic_proxy"


def test_apply_semantic_celltype_proxy_rejects_stale_artifact_hash(
    tmp_path: Path,
) -> None:
    result = resolve_celltype_matches(
        ["Prolif Invasive Tumor"],
        {"macrophage": 80485},
        disease="breast cancer",
        organism="homo_sapiens",
        disease_resolved="breast cancer",
        disease_resolution_mode="exact",
        preview_limit=1,
    )
    options = [{"label": "malignant cell", "total_cell_count": 576171}]
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "census_celltype_options.json").write_text(
        json.dumps(
            {
                "available_celltype_options_sha256": resolution._options_sha256(
                    options
                ),
                "available_celltype_options": options,
            }
        ),
        encoding="utf-8",
    )

    raw = resolution.apply_semantic_celltype_proxy.invoke(
        {
            "resolution_result": result,
            "data_dir": str(tmp_path),
            "input_celltype": "Prolif Invasive Tumor",
            "matched_celltype": "malignant cell",
            "rationale": "Agent selected malignant cell from saved Census options.",
            "confidence": "medium",
        }
    )
    payload = json.loads(raw)

    assert payload["primary_resolved_celltype"] == ""
    assert payload["primary_match_mode"] == "unresolved"
    assert payload["matches"][0]["matched_celltype"] == ""
    assert any(
        "artifact hash does not match resolver result" in error
        for error in payload["errors"]
    )


def test_apply_semantic_celltype_proxy_rejects_label_not_in_full_options() -> None:
    result = resolve_celltype_matches(
        ["Prolif Invasive Tumor"],
        {"macrophage": 80485},
        disease="breast cancer",
        organism="homo_sapiens",
        disease_resolved="breast cancer",
        disease_resolution_mode="exact",
    )

    updated = apply_semantic_celltype_proxy_to_result(
        result,
        available_celltype_options=[{"label": "macrophage", "total_cell_count": 80485}],
        input_celltype="Prolif Invasive Tumor",
        matched_celltype="malignant cell",
        rationale="The agent attempted a malignant-cell proxy.",
        confidence="medium",
        lost_modifiers=["prolif", "invasive"],
        candidate_labels_considered=["malignant cell"],
    )

    assert updated["primary_resolved_celltype"] == ""
    assert updated["primary_match_mode"] == "unresolved"
    assert updated["matches"][0]["matched_celltype"] == ""
    assert updated["errors"] == [
        "Semantic proxy label 'malignant cell' is not present in available Census cell_type labels."
    ]


def test_resolve_celltype_matches_empty_interest_unresolved() -> None:
    available = {
        "pulmonary alveolar type 2 cell": 7545,
        "fibroblast": 1000,
    }

    result = resolve_celltype_matches(
        [""],
        available,
        disease="pulmonary fibrosis",
        organism="homo_sapiens",
        disease_resolved="pulmonary fibrosis",
        disease_resolution_mode="exact",
    )

    match = result["matches"][0]
    assert result["primary_resolved_celltype"] == ""
    assert result["primary_match_mode"] == "unresolved"
    assert match["matched_celltype"] == ""
    assert match["match_mode"] == "unresolved"
    assert match["confidence"] == "none"
    assert match["warnings"] == [
        "No Census cell_type label matched interest cell type ''."
    ]


def test_resolve_census_celltypes_reports_disease_resolution_failure(
    monkeypatch,
) -> None:
    def fail_resolve_disease(disease: str, organism: str):
        raise RuntimeError("resolver exploded")

    monkeypatch.setattr(
        census_batch_core,
        "_resolve_disease_name",
        fail_resolve_disease,
    )
    monkeypatch.setattr(
        resolution,
        "_query_available_cell_type_counts",
        lambda *, disease_resolved, organism: (
            {"pulmonary alveolar type 2 cell": 10},
            [],
        ),
    )

    raw = resolution.resolve_census_celltypes.invoke(
        {
            "interest_celltypes": ["AT2"],
            "disease": "pulmonary fibrosis",
            "organism": "human",
        }
    )

    payload = json.loads(raw)
    assert payload["organism"] == "homo_sapiens"
    assert payload["disease_resolved"] == "pulmonary fibrosis"
    assert payload["disease_resolution_mode"] == "input"
    assert payload["executed"] is False
    assert payload["errors"] == [
        "Census disease resolution failed for 'pulmonary fibrosis': resolver exploded"
    ]


def test_resolve_census_celltypes_offline_wrapper_json_contract(monkeypatch) -> None:
    monkeypatch.setattr(
        resolution,
        "_resolve_disease_for_census",
        lambda disease, organism: ("pulmonary fibrosis", "exact", []),
    )
    monkeypatch.setattr(
        resolution,
        "_query_available_cell_type_counts",
        lambda *, disease_resolved, organism: (
            {"pulmonary alveolar type 2 cell": 10},
            [],
        ),
    )

    raw = resolution.resolve_census_celltypes.invoke(
        {
            "interest_celltypes": ["AT2"],
            "disease": "pulmonary fibrosis",
            "organism": "human",
        }
    )

    payload = json.loads(raw)
    assert payload["organism"] == "homo_sapiens"
    assert payload["disease_input"] == "pulmonary fibrosis"
    assert payload["disease_resolved"] == "pulmonary fibrosis"
    assert payload["disease_resolution_mode"] == "exact"
    assert payload["interest_celltypes"] == ["AT2"]
    assert payload["available_cell_type_count"] == 1
    assert payload["primary_input_celltype"] == "AT2"
    assert payload["primary_resolved_celltype"] == "pulmonary alveolar type 2 cell"
    assert payload["primary_match_mode"] == "alias"
    assert payload["matches"][0]["total_cell_count"] == 10
    assert payload["warnings"] == []
    assert payload["errors"] == []
    assert payload["executed"] is True
    assert payload["census_version"]
