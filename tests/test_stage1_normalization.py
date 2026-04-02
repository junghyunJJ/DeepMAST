from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from src.agents.drug_target.tools.stage1_normalization import (
    build_census_validation_from_csv,
    build_microenvironment_support_from_csv,
    finalize_stage1_workspace,
    load_stage1_json,
    normalize_stage1_record,
    parse_stage1_pair_from_filename,
    rebuild_stage1_artifacts,
    resolve_stage1_context,
    validate_stage1_artifacts,
)


def _write_pair_csv(
    path: Path,
    target_cell_type: str,
    extra_rows: list[str] | None = None,
    target_row: str | None = None,
) -> None:
    rows = [
        "cell_type,n_cells,gene_a_pos,gene_a_pct,gene_b_pos,gene_b_pct,coexp_pos,coexp_pct",
        target_row or f"{target_cell_type},100,20,20.0,30,30.0,15,15.0",
        "other,100,5,5.0,10,10.0,2,2.0",
    ]
    if extra_rows:
        rows.extend(extra_rows)
    path.write_text(
        "\n".join(rows) + "\n",
        encoding="utf-8",
    )


def test_parse_stage1_pair_from_filename():
    ligand, receptor = parse_stage1_pair_from_filename("stage1_KDR--FLT1.json")
    assert ligand == "KDR"
    assert receptor == "FLT1"


def test_load_stage1_json_repairs_trailing_brace(tmp_path: Path):
    stage1_path = tmp_path / "stage1_KDR--FLT1.json"
    stage1_path.write_text('{"string_ppi": {"max_combined_score": 0.9}}}', encoding="utf-8")

    data, repairs = load_stage1_json(stage1_path)

    assert data["string_ppi"]["max_combined_score"] == 0.9
    assert repairs == ["trimmed_extra_closing_brace"]


def test_build_census_validation_from_csv(tmp_path: Path):
    csv_path = tmp_path / "census_kdr_flt1_mammary_gland_epithelial_cell.csv"
    _write_pair_csv(csv_path, "mammary gland epithelial cell")

    result = build_census_validation_from_csv(
        tmp_path,
        "KDR",
        "FLT1",
        csv_target_cell_type="mammary gland epithelial cell",
        requested_target_cell_type="mammary gland epithelial cell",
        resolved_target_cell_type="mammary gland epithelial cell",
        disease="breast carcinoma",
    )

    assert result is not None
    assert result["resolved_cell_type"] == "mammary gland epithelial cell"
    assert result["target_vs_rest"]["coexpression"]["risk_ratio"] == 7.5


def test_build_microenvironment_support_from_csv_flags_vascular_candidate(tmp_path: Path):
    csv_path = tmp_path / "census_kdr_flt1_mammary_gland_epithelial_cell.csv"
    _write_pair_csv(
        csv_path,
        "mammary gland epithelial cell",
        extra_rows=[
            "endothelial cell,165,126,76.36,135,81.81,112,67.87",
            "pericyte,92,1,1.08,1,1.08,1,1.08",
        ],
        target_row="mammary gland epithelial cell,100,1,1.0,1,1.0,0,0.0",
    )

    result = build_microenvironment_support_from_csv(
        tmp_path,
        "KDR",
        "FLT1",
        csv_target_cell_type="mammary gland epithelial cell",
        resolved_target_cell_type="mammary gland epithelial cell",
    )

    assert result == {
        "microenvironment_candidate": True,
        "context_type": "vascular",
        "supporting_cell_type": "endothelial cell",
        "supporting_gene_a_pct": 76.36,
        "supporting_gene_b_pct": 81.81,
        "supporting_coexpression_pct": 67.87,
        "supporting_csv": "census_kdr_flt1_mammary_gland_epithelial_cell.csv",
        "reason": "Primary target-cell coexpression is weak while vascular/endothelial support is strong",
    }


def test_build_microenvironment_support_from_csv_skips_when_target_is_also_strong(tmp_path: Path):
    csv_path = tmp_path / "census_efnb2_ephb4_mammary_gland_epithelial_cell.csv"
    _write_pair_csv(
        csv_path,
        "mammary gland epithelial cell",
        extra_rows=[
            "endothelial cell,165,108,65.45,93,56.36,66,40.0",
        ],
    )

    result = build_microenvironment_support_from_csv(
        tmp_path,
        "EFNB2",
        "EPHB4",
        csv_target_cell_type="mammary gland epithelial cell",
        resolved_target_cell_type="mammary gland epithelial cell",
    )

    assert result is None


def test_normalize_stage1_record_preserves_legacy_and_adds_latest_fields(tmp_path: Path):
    _write_pair_csv(
        tmp_path / "census_efnb2_ephb4_mammary_gland_epithelial_cell.csv",
        "mammary gland epithelial cell",
    )
    _write_pair_csv(
        tmp_path / "census_efnb2_ephb4_unknown.csv",
        "malignant cell",
    )

    legacy = {
        "cellxgene_context": {"disease_matched": True},
        "census_cross_validation": {
            "target_cell_type": "malignant cell",
            "gene_a_expression": {"target_pct": 0.08},
            "gene_b_expression": {"target_pct": 0.15},
            "coexpression": {"target_pct": None, "rest_pct": None},
        },
        "string_ppi": {"max_combined_score": 0.999},
        "kegg_pathways": {
            "ligand_pathways": [{"pathway_id": "hsa04360"}],
            "receptor_pathways": [{"pathway_id": "hsa04360"}],
        },
        "reactome_pathways": {"ligand_pathways": [], "receptor_pathways": []},
    }

    normalized, audit = normalize_stage1_record(
        legacy,
        ligand="EFNB2",
        receptor="EPHB4",
        evidence_dir=tmp_path,
        requested_target_cell_type="mammary gland epithelial cell",
        resolved_target_cell_type="mammary gland epithelial cell",
        csv_target_cell_type="mammary gland epithelial cell",
        disease="breast carcinoma",
    )

    assert normalized["ligand"] == "EFNB2"
    assert normalized["receptor"] == "EPHB4"
    assert normalized["census_validation"]["target_vs_rest"]["coexpression"]["risk_ratio"] == 7.5
    assert normalized["cellxgene"]["available_genes"] == ["EFNB2", "EPHB4"]
    assert normalized["legacy_stage1"]["census_cross_validation"]["target_cell_type"] == "malignant cell"
    assert normalized["stage1_confidence"]["confidence"] > 0.8
    assert audit["legacy_unknown_csv"]["coexpression"]["risk_ratio"] == 7.5


def test_resolve_stage1_context_prefers_metadata_sources(tmp_path: Path):
    data_dir = tmp_path / "res_generic"
    (data_dir / "evidence").mkdir(parents=True)
    (data_dir / "lr_candidates.json").write_text(
        json.dumps({"disease": "lupus nephritis"}),
        encoding="utf-8",
    )
    (data_dir / "targets.json").write_text(
        json.dumps({"interest_celltypes": ["podocyte"]}),
        encoding="utf-8",
    )

    result = resolve_stage1_context(data_dir)

    assert result["disease"] == "lupus nephritis"
    assert result["disease_source"] == "lr_candidates.json:disease"
    assert result["requested_target_cell_type"] == "podocyte"
    assert result["resolved_target_cell_type"] == "podocyte"
    assert result["requested_target_cell_type_source"] == "targets.json:interest_celltypes[0]"
    assert result["resolved_target_cell_type_source"] == "targets.json:interest_celltypes[0]"


def test_resolve_stage1_context_uses_metadata_and_existing_stage1_fallback(tmp_path: Path):
    data_dir = tmp_path / "res_rebuild"
    evidence_dir = data_dir / "evidence"
    evidence_dir.mkdir(parents=True)
    (data_dir / "targets.json").write_text(
        json.dumps({"interest_celltypes": ["Prolif Invasive Tumor"]}),
        encoding="utf-8",
    )
    (evidence_dir / "known_drugs.json").write_text(
        json.dumps({"disease": "lung carcinoma"}),
        encoding="utf-8",
    )
    (evidence_dir / "stage1_KDR--FLT1.json").write_text(
        json.dumps(
            {
                "ligand": "KDR",
                "receptor": "FLT1",
                "census_validation": {
                    "disease": "lung carcinoma",
                    "requested_cell_type": "alveolar epithelial cell",
                    "resolved_cell_type": "alveolar epithelial cell",
                },
            }
        ),
        encoding="utf-8",
    )

    result = resolve_stage1_context(data_dir, allow_existing_evidence_fallback=True)

    assert result["disease"] == "lung carcinoma"
    assert result["disease_source"] == "evidence/known_drugs.json:disease"
    assert result["requested_target_cell_type"] == "Prolif Invasive Tumor"
    assert result["resolved_target_cell_type"] == "alveolar epithelial cell"
    assert result["csv_target_cell_type"] == "alveolar epithelial cell"


def test_resolve_stage1_context_fails_without_metadata(tmp_path: Path):
    data_dir = tmp_path / "res_missing"
    (data_dir / "evidence").mkdir(parents=True)

    try:
        resolve_stage1_context(data_dir, allow_existing_evidence_fallback=False)
    except ValueError as exc:
        assert "Could not resolve disease" in str(exc)
    else:
        raise AssertionError("resolve_stage1_context should fail without disease metadata")


def test_rebuild_stage1_artifacts_writes_aggregates_and_normalized_files(tmp_path: Path):
    data_dir = tmp_path / "res_bc"
    evidence_dir = data_dir / "evidence"
    evidence_dir.mkdir(parents=True)

    stage1_path = evidence_dir / "stage1_KDR--FLT1.json"
    stage1_path.write_text(
        json.dumps(
            {
                "string_ppi": {"max_combined_score": 0.994},
                "kegg_pathways": {"ligand_pathways": [], "receptor_pathways": []},
                "reactome_pathways": {"ligand_pathways": [], "receptor_pathways": []},
                "cellxgene_context": {"disease_matched": True},
                "census_cross_validation": {
                    "target_cell_type": "malignant cell",
                    "gene_a_expression": None,
                    "gene_b_expression": None,
                    "coexpression": None,
                },
            }
        )
        + "}",
        encoding="utf-8",
    )
    _write_pair_csv(
        evidence_dir / "census_kdr_flt1_mammary_gland_epithelial_cell.csv",
        "mammary gland epithelial cell",
        extra_rows=[
            "endothelial cell,165,126,76.36,135,81.81,112,67.87",
        ],
        target_row="mammary gland epithelial cell,100,1,1.0,1,1.0,0,0.0",
    )
    _write_pair_csv(
        evidence_dir / "census_kdr_flt1_unknown.csv",
        "malignant cell",
    )

    result = rebuild_stage1_artifacts(
        data_dir,
        disease="breast carcinoma",
        target_cell_type="mammary gland epithelial cell",
    )

    normalized = json.loads(stage1_path.read_text())
    assert normalized["ligand"] == "KDR"
    assert normalized["receptor"] == "FLT1"
    assert "legacy_stage1" in normalized
    assert normalized["stage1_annotations"]["microenvironment_candidate"] is True
    assert normalized["stage1_confidence"]["expression_score"] == 1.0

    aggregate = json.loads((evidence_dir / "stage1_confidence.json").read_text())
    evidence = json.loads((evidence_dir / "stage1_evidence.json").read_text())
    audit = json.loads((evidence_dir / "stage1_audit.json").read_text())

    assert "KDR^FLT1" in result["stage1_confidence"]
    assert aggregate["KDR^FLT1"]["confidence"] == normalized["stage1_confidence"]["confidence"]
    assert evidence["KDR^FLT1"]["stage1_annotations"]["supporting_cell_type"] == "endothelial cell"
    assert audit["KDR^FLT1"]["microenvironment_support"]["supporting_coexpression_pct"] == 67.87
    assert audit["KDR^FLT1"]["resolved_disease"] == "breast carcinoma"
    assert audit["KDR^FLT1"]["disease_source"] == "cli"
    assert audit["KDR^FLT1"]["target_cell_type_source"] == "cli"
    assert audit["KDR^FLT1"]["repairs"] == ["trimmed_extra_closing_brace"]


def test_validate_stage1_artifacts_reports_missing_csv_and_aggregates(tmp_path: Path):
    data_dir = tmp_path / "res_bc"
    evidence_dir = data_dir / "evidence"
    evidence_dir.mkdir(parents=True)
    (data_dir / "lr_candidates.json").write_text(
        json.dumps({"disease": "breast carcinoma", "pairs": [{"ligand": "KDR", "receptor": "FLT1"}]}),
        encoding="utf-8",
    )
    (data_dir / "targets.json").write_text(
        json.dumps({"interest_celltypes": ["mammary gland epithelial cell"]}),
        encoding="utf-8",
    )
    (evidence_dir / "stage1_KDR--FLT1.json").write_text(
        json.dumps({"string_ppi": {"max_combined_score": 0.994}}),
        encoding="utf-8",
    )

    result = validate_stage1_artifacts(data_dir)

    assert result["valid"] is False
    assert "census_kdr_flt1_mammary_gland_epithelial_cell.csv" in result["missing_csv_files"]
    assert sorted(result["missing_aggregate_files"]) == [
        "stage1_audit.json",
        "stage1_confidence.json",
        "stage1_evidence.json",
    ]


def test_finalize_stage1_workspace_reruns_missing_csv_and_writes_canonical_outputs(
    tmp_path: Path,
    monkeypatch,
):
    data_dir = tmp_path / "res_bc"
    evidence_dir = data_dir / "evidence"
    evidence_dir.mkdir(parents=True)
    (data_dir / "lr_candidates.json").write_text(
        json.dumps({"disease": "breast carcinoma", "pairs": [{"ligand": "KDR", "receptor": "FLT1"}]}),
        encoding="utf-8",
    )
    (data_dir / "targets.json").write_text(
        json.dumps({"interest_celltypes": ["mammary gland epithelial cell"]}),
        encoding="utf-8",
    )
    (evidence_dir / "stage1_KDR--FLT1.json").write_text(
        json.dumps(
            {
                "string_ppi": {"interaction_found": True, "max_combined_score": 0.994},
                "kegg_pathways": {"ligand_pathways": [], "receptor_pathways": []},
                "reactome_pathways": {"ligand_pathways": [], "receptor_pathways": []},
                "cellxgene_context": {"disease_matched": True},
                "census_cross_validation": {"target_cell_type": "malignant cell"},
            }
        ),
        encoding="utf-8",
    )
    _write_pair_csv(
        evidence_dir / "census_kdr_flt1_unknown.csv",
        "malignant cell",
    )

    def _fake_invoke(payload):
        csv_path = Path(payload["output_csv"])
        _write_pair_csv(
            csv_path,
            "mammary gland epithelial cell",
            extra_rows=[
                "endothelial cell,165,126,76.36,135,81.81,112,67.87",
            ],
            target_row="mammary gland epithelial cell,100,1,1.0,1,1.0,0,0.0",
        )
        return json.dumps({
            "executed": True,
            "disease": payload["disease"],
            "requested_cell_type": payload["target_cell_type"],
            "resolved_cell_type": "mammary gland epithelial cell",
            "target_vs_rest": {"coexpression": {"risk_ratio": 0.0, "p_value": 1.0}},
            "errors": [],
        })

    monkeypatch.setattr(
        "src.agents.drug_target.tools.stage1_normalization.run_compare_census_lr_pair",
        MagicMock(invoke=_fake_invoke),
    )

    result = finalize_stage1_workspace(data_dir)

    assert result["success"] is True
    assert result["rerun_results"][0]["executed"] is True
    assert (evidence_dir / "stage1_evidence.json").exists()
    assert (evidence_dir / "stage1_confidence.json").exists()
    assert (evidence_dir / "stage1_audit.json").exists()
