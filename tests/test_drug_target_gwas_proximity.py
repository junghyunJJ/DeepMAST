"""Regression tests for fix/gwas-proximity-correctness.

Covers Bug A (format gate) + Bug B (chr/pos surfacing) fixes.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_parquet_mod():
    spec = importlib.util.spec_from_file_location(
        "gpq",
        REPO_ROOT / "skills/gwas-database/scripts/gwas_parquet.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_get_trait_associations_surfaces_chromosome_position(monkeypatch):
    """Bug B fix: get_trait_associations must propagate chr/pos from parquet."""
    pd = pytest.importorskip("pandas")
    gpq = _load_parquet_mod()

    df = pd.DataFrame([
        {
            "efoId": "EFO_IPF",
            "rsId": "rs35705950",
            "pvalue": 1e-40,
            "chromosome": "11",
            "position": 1219991,
            "genes_list": [],
            "studyAccession": "GCST001",
            "trait": "pulmonary fibrosis",
            "riskAllele": "T",
            "orBeta": 4.51,
        },
    ])
    monkeypatch.setattr(gpq, "_load_associations", lambda: df)
    out = gpq.get_trait_associations("EFO_IPF")
    assert len(out) == 1
    assert out[0]["chromosome"] == "11"
    assert out[0]["position"] == 1219991
    assert out[0]["rsId"] == "rs35705950"


def test_proximity_match_uses_structured_coords():
    """Bug A fix: _proximity_match works on (chr, pos) fields, not only chr:pos rsIds."""
    from src.agents.drug_target.tools.stage2_service import _proximity_match

    gene_assocs = [
        {"rsId": "rs2855535", "locations": [{"chromosome": "12", "position": 6800000}]},
    ]
    trait_assocs_structured = [
        {"rsId": "rs35705950", "chromosome": "12", "position": 6850000},   # 50 kb -> hit
        {"rsId": "rs99999999", "chromosome": "1", "position": 1},          # different chrom
        {"rsId": "rs88888888", "chromosome": "12", "position": 8_000_000}, # 1.2 Mb -> miss
    ]
    hits = _proximity_match(gene_assocs, trait_assocs_structured)
    assert [h["rsId"] for h in hits] == ["rs35705950"]


def test_proximity_match_legacy_chr_pos_rsid_still_supported():
    """Backward compat: chr:pos rsId form still works."""
    from src.agents.drug_target.tools.stage2_service import _proximity_match

    gene_assocs = [
        {"locations": [{"chromosome": "11", "position": 1220000}]},
    ]
    trait_assocs_legacy = [
        {"rsId": "chr11:1219991"},  # 9 bp away -> hit
        {"rsId": "chr11:5000000"},  # 3.78 Mb -> miss
    ]
    hits = _proximity_match(gene_assocs, trait_assocs_legacy)
    assert [h["rsId"] for h in hits] == ["chr11:1219991"]


def test_proximity_match_empty_inputs():
    from src.agents.drug_target.tools.stage2_service import _proximity_match

    assert _proximity_match([], []) == []
    # Gene assocs missing locations → empty result.
    assert _proximity_match([{"rsId": "rs1"}], [{"chromosome": "1", "position": 1}]) == []


def test_proximity_match_dedupes_on_rsid():
    from src.agents.drug_target.tools.stage2_service import _proximity_match

    gene_assocs = [{"locations": [{"chromosome": "1", "position": 100}]}]
    trait_assocs = [
        {"rsId": "rs1", "chromosome": "1", "position": 150},
        {"rsId": "rs1", "chromosome": "1", "position": 200},  # same rsId
        {"rsId": "rs2", "chromosome": "1", "position": 200},
    ]
    hits = _proximity_match(gene_assocs, trait_assocs)
    assert sorted(h["rsId"] for h in hits) == ["rs1", "rs2"]
