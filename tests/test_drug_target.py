"""Tests for Drug Target Assessment Agent.

6 test classes covering:
1. TestSubagentConfigs — Tool registration & prompt content
2. TestRubric — Rubric parsing, validation, scoring
3. TestEvidenceLoader — File I/O tools (tmp_path)
4. TestToolImports — Verify all tools importable
5. TestToolMocks — External API tools with mocked responses
6. TestIntegration — Agent creation & tool wiring

All tests use mock data — zero external API calls.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Mock Input Data (biologically realistic breast cancer L-R pairs)
# ---------------------------------------------------------------------------

MOCK_LR_CANDIDATES = {
    "disease": "breast cancer",
    "disease_context": "Triple-negative breast cancer",
    "pairs": [
        {"ligand": "TGFB1", "receptor": "TGFBR2", "score": 0.95},
        {"ligand": "CDH1", "receptor": "ITGB1", "score": 0.92},
        {"ligand": "SPP1", "receptor": "CD44", "score": 0.90},
        {"ligand": "VEGFA", "receptor": "FLT1", "score": 0.88},
        {"ligand": "WNT5A", "receptor": "FZD7", "score": 0.85},
        {"ligand": "CXCL12", "receptor": "CXCR4", "score": 0.83},
        {"ligand": "HGF", "receptor": "MET", "score": 0.80},
        {"ligand": "FGF2", "receptor": "FGFR1", "score": 0.78},
        {"ligand": "PDGFB", "receptor": "PDGFRB", "score": 0.76},
        {"ligand": "BMP2", "receptor": "BMPR1A", "score": 0.74},
        {"ligand": "EFNA1", "receptor": "EPHA2", "score": 0.72},
        {"ligand": "JAG1", "receptor": "NOTCH1", "score": 0.70},
        {"ligand": "DLL4", "receptor": "NOTCH3", "score": 0.68},
        {"ligand": "GDF15", "receptor": "GFRAL", "score": 0.65},
        {"ligand": "TNFSF10", "receptor": "TNFRSF10B", "score": 0.62},
    ],
}

MOCK_SELECTED_TOP3 = [
    {"ligand": "TGFB1", "receptor": "TGFBR2"},
    {"ligand": "SPP1", "receptor": "CD44"},
    {"ligand": "VEGFA", "receptor": "FLT1"},
]

# 30 unique genes, 6 selected_top3 genes
EXPECTED_ALL_GENES = sorted({
    p["ligand"].upper() for p in MOCK_LR_CANDIDATES["pairs"]
} | {
    p["receptor"].upper() for p in MOCK_LR_CANDIDATES["pairs"]
})

EXPECTED_TOP3_GENES = sorted({"TGFB1", "TGFBR2", "SPP1", "CD44", "VEGFA", "FLT1"})


# ---------------------------------------------------------------------------
# Shared Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_data_dir(tmp_path):
    """tmp_path with lr_candidates.json + selected_top3_lr.json."""
    (tmp_path / "lr_candidates.json").write_text(json.dumps(MOCK_LR_CANDIDATES))
    (tmp_path / "selected_top3_lr.json").write_text(json.dumps(MOCK_SELECTED_TOP3))
    return tmp_path


@pytest.fixture
def mock_data_dir_with_targets(mock_data_dir):
    """mock_data_dir with targets.json containing interest_celltypes."""
    (mock_data_dir / "targets.json").write_text(
        json.dumps(
            {
                "interest_celltypes": ["Invasive tumor", "Malignant cell"],
                "data_directory": str(mock_data_dir),
            }
        )
    )
    return mock_data_dir


@pytest.fixture
def mock_data_dir_with_evidence(mock_data_dir):
    """Extends mock_data_dir with pre-populated evidence/*.json."""
    evi_dir = mock_data_dir / "evidence"
    evi_dir.mkdir()
    (evi_dir / "ot_TGFB1.json").write_text(json.dumps({
        "gene_symbol": "TGFB1",
        "target_info": {"tractability": {"smallmolecule": True}},
    }))
    (evi_dir / "gwas_all.json").write_text(json.dumps({
        "gene_signals": {"TGFB1": {"combined_signal": 0.45}},
    }))
    (evi_dir / "gene_manifest.json").write_text(json.dumps({
        "genes": [{"symbol": "TGFB1", "is_selected_top3": True}],
    }))
    return mock_data_dir


@pytest.fixture
def valid_assessment():
    """Complete valid rubric assessment dict for TGFB1."""
    return {
        "gene_symbol": "TGFB1",
        "is_selected_top3": True,
        "validated_track": {
            "existing_drug_evidence": {"score": 2, "rationale": "Galunisertib Phase 2"},
            "clinical_trial_activity": {"score": 2, "rationale": "Multiple active trials"},
            "mechanism_relevance": {"score": 3, "rationale": "Direct TGF-beta pathway"},
            "safety_profile": {"score": -1, "rationale": "Moderate immunosuppression risk"},
            "total": 6,
            "pass": True,
        },
        "exploratory_track": {
            "gwas_genetic_support": {"score": 1, "rationale": "Suggestive signals"},
            "tractability": {"score": 2, "rationale": "Clinical precedent with small molecules"},
            "biological_plausibility": {"score": 3, "rationale": "Compelling multi-evidence"},
            "novelty_opportunity": {"score": 1, "rationale": "Moderately explored"},
            "total": 7,
            "pass": True,
        },
        "classification": "validated_target",
        "priority": "high",
        "summary": "TGFB1 is a validated target with Phase 2 drug evidence.",
    }


# =========================================================================
# 1. TestSubagentConfigs
# =========================================================================

class TestSubagentConfigs:
    """Tool registration & prompt content for subagent configs."""

    def test_evidence_assessor_has_minimum_tools(self):
        from src.agents.drug_target.subagents.configs import SUBAGENT_CONFIGS
        tools = SUBAGENT_CONFIGS["evidence_assessor"]["tools"]
        assert len(tools) >= 15

    def test_report_writer_has_minimum_tools(self):
        from src.agents.drug_target.subagents.configs import SUBAGENT_CONFIGS
        tools = SUBAGENT_CONFIGS["report_writer"]["tools"]
        assert len(tools) >= 4

    def test_evidence_assessor_tool_names(self):
        from src.agents.drug_target.subagents.configs import SUBAGENT_CONFIGS
        tools = SUBAGENT_CONFIGS["evidence_assessor"]["tools"]
        names = {t.name for t in tools}
        expected = {
            "load_lr_candidates",
            "save_evidence",
            "load_evidence_files",
            "sequential_thinking",
            "query_cellxgene_lr_context",
            "query_kegg_pathways",
            "query_reactome_pathways",
            "query_string_ppi_pair",
            "query_ensembl_vep_consequence",
            "query_drugbank_target_profile",
            "query_pubmed_clinical_limitations",
            "query_alphafold_plddt",
            "run_diffdock_screen",
            "run_compare_census_lr_pair",
            "think_tool",
            "validate_quality",
        }
        assert expected.issubset(names)

    def test_workflow_order(self):
        from src.agents.drug_target.subagents.configs import WORKFLOW_ORDER
        assert WORKFLOW_ORDER == ["evidence_assessor", "report_writer"]

    def test_get_subagents_returns_2(self):
        from src.agents.drug_target.subagents.configs import get_subagents
        subagents = get_subagents()
        assert len(subagents) == 2

    def test_get_subagents_order(self):
        from src.agents.drug_target.subagents.configs import get_subagents
        subagents = get_subagents()
        names = [s["name"] for s in subagents]
        assert names == ["evidence_assessor", "report_writer"]

    def test_custom_tools_appended_to_all_subagents(self):
        from src.agents.drug_target.subagents.configs import get_subagents
        mock_tool = MagicMock(spec=["name"])
        mock_tool.name = "custom_tool"
        subagents = get_subagents(custom_tools=[mock_tool])
        for s in subagents:
            tool_names = [t.name for t in s["tools"]]
            assert "custom_tool" in tool_names

    def test_evidence_assessor_prompt_mentions_databases_and_rubric(self):
        from src.agents.drug_target.subagents.configs import SUBAGENT_CONFIGS
        prompt = SUBAGENT_CONFIGS["evidence_assessor"]["system_prompt"]
        # Database references
        for keyword in ("OpenTargets", "GWAS", "DrugBank", "AlphaFold"):
            assert keyword in prompt
        # Rubric references (merged from clinical_assessor)
        assert "rubric" in prompt.lower() or "RUBRIC" in prompt
        assert "validated" in prompt.lower()
        assert "exploratory" in prompt.lower()

    def test_evidence_assessor_prompt_mentions_4_stages(self):
        from src.agents.drug_target.subagents.configs import SUBAGENT_CONFIGS
        prompt = SUBAGENT_CONFIGS["evidence_assessor"]["system_prompt"]
        assert "Stage 1" in prompt
        assert "Stage 2" in prompt
        assert "Stage 3" in prompt
        assert "Stage 4" in prompt

    def test_evidence_assessor_prompt_mentions_census_and_gwas(self):
        from src.agents.drug_target.subagents.configs import SUBAGENT_CONFIGS
        prompt = SUBAGENT_CONFIGS["evidence_assessor"]["system_prompt"]
        assert "Census cross-validation" in prompt or "run_compare_census_lr_pair" in prompt
        assert "GWAS" in prompt

    def test_report_writer_prompt_mentions_featured_candidate(self):
        from src.agents.drug_target.subagents.configs import SUBAGENT_CONFIGS
        prompt = SUBAGENT_CONFIGS["report_writer"]["system_prompt"]
        assert "Featured Candidate" in prompt
        assert "drug.md" in prompt



# =========================================================================
# 3. TestEvidenceLoader
# =========================================================================

class TestEvidenceLoader:
    """File I/O tools for evidence loading and saving."""

    def test_load_lr_candidates_gene_count(self, mock_data_dir):
        from src.agents.drug_target.tools.evidence_loader import load_lr_candidates
        raw = load_lr_candidates.invoke({"data_dir": str(mock_data_dir)})
        result = json.loads(raw)
        assert len(result["gene_symbols"]) == 30

    def test_load_lr_candidates_lr_pairs_count(self, mock_data_dir):
        from src.agents.drug_target.tools.evidence_loader import load_lr_candidates
        raw = load_lr_candidates.invoke({"data_dir": str(mock_data_dir)})
        result = json.loads(raw)
        assert len(result["lr_pairs"]) == 15

    def test_load_lr_candidates_selected_top3_genes(self, mock_data_dir):
        from src.agents.drug_target.tools.evidence_loader import load_lr_candidates
        raw = load_lr_candidates.invoke({"data_dir": str(mock_data_dir)})
        result = json.loads(raw)
        assert sorted(result["selected_top3_genes"]) == EXPECTED_TOP3_GENES

    def test_load_lr_candidates_disease(self, mock_data_dir):
        from src.agents.drug_target.tools.evidence_loader import load_lr_candidates
        raw = load_lr_candidates.invoke({"data_dir": str(mock_data_dir)})
        result = json.loads(raw)
        assert result["disease"] == "breast cancer"

    def test_load_lr_candidates_infers_oncology_fields(self, mock_data_dir):
        from src.agents.drug_target.tools.evidence_loader import load_lr_candidates
        raw = load_lr_candidates.invoke({"data_dir": str(mock_data_dir)})
        result = json.loads(raw)
        assert result["disease_type"] == "oncology"
        assert result["oncology_flag"] is True

    def test_load_lr_candidates_adds_st_colocalization_score(self, mock_data_dir):
        from src.agents.drug_target.tools.evidence_loader import load_lr_candidates
        raw = load_lr_candidates.invoke({"data_dir": str(mock_data_dir)})
        result = json.loads(raw)
        first = result["lr_pairs"][0]
        assert "st_colocalization_score" in first
        assert first["st_colocalization_score"] == 0.95

    def test_load_lr_candidates_reads_interest_celltypes(self, mock_data_dir_with_targets):
        from src.agents.drug_target.tools.evidence_loader import load_lr_candidates

        raw = load_lr_candidates.invoke({"data_dir": str(mock_data_dir_with_targets)})
        result = json.loads(raw)
        assert result["targets_json_found"] is True
        assert result["interest_celltypes"] == ["Invasive tumor", "Malignant cell"]

    def test_load_lr_candidates_is_selected_top3_flag(self, mock_data_dir):
        from src.agents.drug_target.tools.evidence_loader import load_lr_candidates
        raw = load_lr_candidates.invoke({"data_dir": str(mock_data_dir)})
        result = json.loads(raw)
        details = {d["symbol"]: d["is_selected_top3"] for d in result["gene_details"]}
        assert details["TGFB1"] is True
        assert details["CD44"] is True
        assert details["FGF2"] is False
        assert details["NOTCH1"] is False

    def test_load_lr_candidates_missing_file(self, tmp_path):
        from src.agents.drug_target.tools.evidence_loader import load_lr_candidates
        raw = load_lr_candidates.invoke({"data_dir": str(tmp_path)})
        result = json.loads(raw)
        assert len(result["errors"]) > 0
        assert "not found" in result["errors"][0]

    def test_load_lr_candidates_missing_top3_still_works(self, tmp_path):
        from src.agents.drug_target.tools.evidence_loader import load_lr_candidates
        (tmp_path / "lr_candidates.json").write_text(json.dumps(MOCK_LR_CANDIDATES))
        # No selected_top3_lr.json
        raw = load_lr_candidates.invoke({"data_dir": str(tmp_path)})
        result = json.loads(raw)
        assert len(result["gene_symbols"]) == 30
        assert len(result["selected_top3_genes"]) == 0
        # Should note it as optional missing
        assert any("optional" in e.lower() for e in result["errors"])

    def test_load_lr_candidates_alternative_key_names(self, tmp_path):
        from src.agents.drug_target.tools.evidence_loader import load_lr_candidates
        alt_data = {
            "disease": "lung cancer",
            "lr_pairs": [  # alternative key name
                {"ligand": "EGFR", "receptor": "ERBB2", "score": 0.99},
            ],
        }
        (tmp_path / "lr_candidates.json").write_text(json.dumps(alt_data))
        raw = load_lr_candidates.invoke({"data_dir": str(tmp_path)})
        result = json.loads(raw)
        assert len(result["lr_pairs"]) == 1
        assert "EGFR" in result["gene_symbols"]

    def test_load_evidence_files(self, mock_data_dir_with_evidence):
        from src.agents.drug_target.tools.evidence_loader import load_evidence_files
        raw = load_evidence_files.invoke({"data_dir": str(mock_data_dir_with_evidence)})
        result = json.loads(raw)
        assert result["file_count"] == 3
        assert "ot_TGFB1.json" in result["files"]
        assert "gwas_all.json" in result["files"]

    def test_load_evidence_files_missing_dir(self, tmp_path):
        from src.agents.drug_target.tools.evidence_loader import load_evidence_files
        raw = load_evidence_files.invoke({"data_dir": str(tmp_path)})
        result = json.loads(raw)
        assert len(result["errors"]) > 0
        assert result["file_count"] == 0

    def test_load_evidence_files_empty_dir(self, tmp_path):
        from src.agents.drug_target.tools.evidence_loader import load_evidence_files
        (tmp_path / "evidence").mkdir()
        raw = load_evidence_files.invoke({"data_dir": str(tmp_path)})
        result = json.loads(raw)
        assert result["file_count"] == 0
        assert result["errors"] == []

    def test_save_evidence_roundtrip(self, tmp_path):
        from src.agents.drug_target.tools.evidence_loader import save_evidence, load_evidence_files
        data = {"gene": "TGFB1", "score": 0.95}
        raw = save_evidence.invoke({
            "data_dir": str(tmp_path),
            "filename": "test_gene.json",
            "data": json.dumps(data),
        })
        result = json.loads(raw)
        assert result["saved"] is True
        assert (tmp_path / "evidence" / "test_gene.json").exists()

        # Roundtrip: load it back
        raw2 = load_evidence_files.invoke({"data_dir": str(tmp_path)})
        result2 = json.loads(raw2)
        assert result2["files"]["test_gene.json"]["gene"] == "TGFB1"

    def test_save_evidence_non_json_saved_as_raw(self, tmp_path):
        from src.agents.drug_target.tools.evidence_loader import save_evidence
        raw = save_evidence.invoke({
            "data_dir": str(tmp_path),
            "filename": "notes.json",
            "data": "This is not valid JSON",
        })
        result = json.loads(raw)
        assert result["saved"] is True
        content = (tmp_path / "evidence" / "notes.json").read_text()
        assert content == "This is not valid JSON"


# =========================================================================
# 4. TestToolImports
# =========================================================================

class TestToolImports:
    """Verify all tools are importable (no circular imports)."""

    def test_import_evidence_loader(self):
        from src.agents.drug_target.tools import evidence_loader
        assert hasattr(evidence_loader, "load_lr_candidates")
        assert evidence_loader.load_lr_candidates.name == "load_lr_candidates"

    def test_import_stage_tools(self):
        from src.agents.drug_target.tools import stage_domain_tools
        assert stage_domain_tools.query_cellxgene_lr_context.name == "query_cellxgene_lr_context"
        assert stage_domain_tools.query_kegg_pathways.name == "query_kegg_pathways"
        assert stage_domain_tools.query_reactome_pathways.name == "query_reactome_pathways"
        assert stage_domain_tools.query_string_ppi_pair.name == "query_string_ppi_pair"
        assert stage_domain_tools.query_ensembl_vep_consequence.name == "query_ensembl_vep_consequence"
        assert stage_domain_tools.query_drugbank_target_profile.name == "query_drugbank_target_profile"
        assert stage_domain_tools.query_pubmed_clinical_limitations.name == "query_pubmed_clinical_limitations"
        assert stage_domain_tools.query_alphafold_plddt.name == "query_alphafold_plddt"
        assert stage_domain_tools.run_diffdock_screen.name == "run_diffdock_screen"

    def test_import_census_lr_validation_tools(self):
        from src.agents.drug_target.tools import census_lr_validation_tools

        assert (
            census_lr_validation_tools.run_compare_census_lr_pair.name
            == "run_compare_census_lr_pair"
        )

    def test_init_all_exports(self):
        from src.agents.drug_target.tools import __all__
        expected = [
            "load_lr_candidates", "load_evidence_files", "save_evidence",
            "query_cellxgene_lr_context", "query_kegg_pathways", "query_reactome_pathways",
            "query_string_ppi_pair", "query_ensembl_vep_consequence",
            "query_drugbank_target_profile", "query_pubmed_clinical_limitations",
            "query_alphafold_plddt", "run_diffdock_screen",
            "run_compare_census_lr_pair",
            "save_target_assessment",
            "think_tool", "sequential_thinking", "validate_quality",
        ]
        assert set(expected).issubset(set(__all__))

    def test_import_common_sequential_thinking(self):
        from src.agents.drug_target.tools.common import sequential_thinking
        assert sequential_thinking.name == "sequential_thinking"


# =========================================================================
# 6. TestStageContracts — Dynamic featured ranking, gating, output contract
# =========================================================================

class TestStageContracts:
    """Decision logic and JSON output contract for staged pipeline."""

    def test_rank_featured_candidates_dynamic_top_3_to_5(self):
        from src.agents.drug_target.tools.stage_logic import rank_featured_candidates

        matrix = [
            {"ligand": "A", "receptor": "B", "open_targets_score": 0.91, "st_colocalization_score": 0.95},
            {"ligand": "C", "receptor": "D", "open_targets_score": 0.80, "st_colocalization_score": 0.90},
            {"ligand": "E", "receptor": "F", "open_targets_score": 0.72, "st_colocalization_score": 0.85},
            {"ligand": "G", "receptor": "H", "open_targets_score": 0.64, "st_colocalization_score": 0.80},
            {"ligand": "I", "receptor": "J", "open_targets_score": 0.62, "st_colocalization_score": 0.75},
            {"ligand": "K", "receptor": "L", "open_targets_score": 0.31, "st_colocalization_score": 0.20},
        ]

        ranked = rank_featured_candidates(matrix)
        featured = [row for row in ranked if row["is_featured"]]
        assert 3 <= len(featured) <= 5
        assert featured[0]["ligand"] == "A"
        assert featured[0]["receptor"] == "B"

    def test_stage_gate_rules(self):
        from src.agents.drug_target.tools.stage_logic import (
            should_run_diffdock,
            should_run_pubmed,
            should_run_vep,
        )

        assert should_run_vep(oncology_flag=True, has_high_somatic_mutation=True) is True
        assert should_run_vep(oncology_flag=False, has_high_somatic_mutation=True) is False
        assert should_run_pubmed("Phase 2") is True
        assert should_run_pubmed("phase 1") is False
        assert should_run_diffdock("Small Molecule") is True
        assert should_run_diffdock("Antibody") is False

    def test_census_bonus_affects_priority_score(self):
        from src.agents.drug_target.tools.stage_logic import rank_featured_candidates

        matrix = [
            {
                "ligand": "A",
                "receptor": "B",
                "open_targets_score": 0.80,
                "st_colocalization_score": 0.80,
                "census_validation": {"p_value": 1e-6, "diff": 0.07},
            },
            {
                "ligand": "C",
                "receptor": "D",
                "open_targets_score": 0.81,
                "st_colocalization_score": 0.80,
                "census_validation": {"p_value": 0.50, "diff": 0.00},
            },
            {
                "ligand": "E",
                "receptor": "F",
                "open_targets_score": 0.60,
                "st_colocalization_score": 0.60,
                "census_validation": {"p_value": 0.50, "diff": 0.00},
            },
        ]

        ranked = rank_featured_candidates(matrix, min_featured=1, max_featured=3)
        assert ranked[0]["ligand"] == "A"
        assert ranked[0]["census_bonus"] == 0.05
        assert ranked[1]["census_bonus"] == 0.0


class TestCompareCensusTool:
    """CLI wrapper behavior for compare-census skill script."""

    def test_run_compare_census_lr_pair_parses_target_vs_rest(self, monkeypatch, tmp_path):
        import src.agents.drug_target.tools.census_lr_validation_tools as mod

        class Result:
            returncode = 0
            stdout = (
                "Target vs rest\n"
                "- target cell type: Invasive tumor\n"
                "- n_target: 100\n"
                "- n_rest: 900\n"
                "- TGFB1+: target=20.0000% | rest=10.0000% | diff=10.0000% | RR=2.0000 | z=4.2000 | p=2.000e-05\n"
                "- TGFBR2+: target=30.0000% | rest=12.0000% | diff=18.0000% | RR=2.5000 | z=5.1000 | p=1.000e-06\n"
                "- TGFB1+ & TGFBR2+: target=12.0000% | rest=4.0000% | diff=8.0000% | RR=3.0000 | z=4.9000 | p=9.000e-07\n"
            )
            stderr = ""

        monkeypatch.setattr(mod.subprocess, "run", lambda *args, **kwargs: Result())

        raw = mod.run_compare_census_lr_pair.invoke(
            {
                "data_dir": str(tmp_path),
                "disease": "breast cancer",
                "gene_a": "TGFB1",
                "gene_b": "TGFBR2",
                "target_cell_type": "Invasive tumor",
            }
        )
        result = json.loads(raw)
        assert result["executed"] is True
        coexp = result["target_vs_rest"]["coexpression"]
        assert coexp["p_value"] == 9e-07
        assert coexp["diff"] == 0.08
        assert result["resolved_cell_type"] == "Invasive tumor"

    def test_run_compare_census_lr_pair_fuzzy_retries_on_missing_celltype(self, monkeypatch, tmp_path):
        import src.agents.drug_target.tools.census_lr_validation_tools as mod

        class FailResult:
            returncode = 1
            stdout = ""
            stderr = (
                "RuntimeError: Target cell type 'Invasive tumor' not found. "
                "Examples of available cell types: Prolif Invasive Tumor(500), T cell(200)"
            )

        class OkResult:
            returncode = 0
            stdout = (
                "Target vs rest\n"
                "- target cell type: Prolif Invasive Tumor\n"
                "- n_target: 500\n"
                "- n_rest: 700\n"
                "- TGFB1+ & TGFBR2+: target=10.0000% | rest=4.0000% | diff=6.0000% | RR=2.5000 | z=3.1000 | p=1.000e-03\n"
            )
            stderr = ""

        calls = {"n": 0}

        def fake_run(*args, **kwargs):
            calls["n"] += 1
            return FailResult() if calls["n"] == 1 else OkResult()

        monkeypatch.setattr(mod.subprocess, "run", fake_run)

        raw = mod.run_compare_census_lr_pair.invoke(
            {
                "data_dir": str(tmp_path),
                "disease": "breast cancer",
                "gene_a": "TGFB1",
                "gene_b": "TGFBR2",
                "target_cell_type": "Invasive tumor",
            }
        )
        result = json.loads(raw)
        assert result["executed"] is True
        assert result["resolution_mode"] == "fuzzy"
        assert result["resolved_cell_type"] == "Prolif Invasive Tumor"

    def test_save_target_assessment_roundtrip(self, tmp_path):
        from src.agents.drug_target.tools.assessment_output import save_target_assessment

        raw = save_target_assessment.invoke({
            "data_dir": str(tmp_path),
            "project_meta": json.dumps({"disease_focus": "breast cancer", "total_input_pairs": 15}),
            "druggability_matrix": json.dumps([
                {"ligand": "TGFB1", "receptor": "TGFBR2", "is_featured": True, "open_targets_score": 0.9}
            ]),
            "featured_candidates_deep_dive": json.dumps([
                {"target_gene": "TGFBR2"}
            ]),
        })
        result = json.loads(raw)
        assert result["saved"] is True
        assert result["schema_valid"] is True
        saved = tmp_path / "target_assessment.json"
        assert saved.exists()
        payload = json.loads(saved.read_text())
        assert payload["project_meta"]["disease_focus"] == "breast cancer"
        assert payload["druggability_matrix"][0]["is_featured"] is True


# =========================================================================
# 6. TestIntegration — Agent creation & tool wiring
# =========================================================================

class TestIntegration:
    """Agent creation, config defaults, and integration wiring."""

    def test_drug_target_config_defaults(self):
        from src.agents.drug_target.agent import DrugTargetConfig
        config = DrugTargetConfig()
        assert config.provider == "openrouter"
        assert config.max_iterations == 2
        assert config.quality_threshold == 0.7
        assert config.use_checkpointer is False

    @patch("src.agents.drug_target.agent.create_deep_agent")
    @patch("src.agents.drug_target.agent.create_llm")
    def test_create_drug_target_agent_returns_runnable(
        self, mock_create_llm, mock_create_deep_agent, tmp_path
    ):
        from src.agents.drug_target.agent import create_drug_target_agent, DrugTargetConfig

        mock_create_llm.return_value = MagicMock()
        mock_agent = MagicMock()
        mock_create_deep_agent.return_value = mock_agent

        config = DrugTargetConfig(data_dir=str(tmp_path))
        result = create_drug_target_agent(config)

        assert result is mock_agent
        mock_create_llm.assert_called_once_with(provider="openrouter")
        # 2 compiled subagents + 1 orchestrator = 3 calls
        assert mock_create_deep_agent.call_count == 3

    @patch("src.agents.drug_target.agent.create_deep_agent")
    @patch("src.agents.drug_target.agent.create_llm")
    def test_create_agent_creates_data_path_and_evidence_dir(
        self, mock_create_llm, mock_create_deep_agent, tmp_path
    ):
        from src.agents.drug_target.agent import create_drug_target_agent, DrugTargetConfig

        mock_create_llm.return_value = MagicMock()
        mock_create_deep_agent.return_value = MagicMock()

        config = DrugTargetConfig(data_dir=str(tmp_path))
        create_drug_target_agent(config)

        # data_path.txt is written by the OverwriteFilesystemBackend
        assert (tmp_path / "data_path.txt").exists()
        assert (tmp_path / "evidence").is_dir()

    def test_run_drug_target_assessment_missing_lr_candidates(self, tmp_path):
        """Missing lr_candidates.json returns error JSON synchronously."""
        from src.agents.drug_target.integration import run_drug_target_assessment
        import asyncio

        raw = asyncio.run(
            run_drug_target_assessment.ainvoke({
                "data_dir": str(tmp_path),
                "disease": "breast cancer",
            })
        )
        result = json.loads(raw)
        assert "error" in result
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_run_drug_target_assessment_with_mock_agent(self, mock_data_dir):
        """Full integration: mock agent writes drug.md, integration reads it."""
        from src.agents.drug_target.integration import run_drug_target_assessment

        mock_report = "# Drug Target Assessment\n\n## Executive Summary\nMock report."
        mock_json = {
            "project_meta": {"disease_focus": "breast cancer", "total_input_pairs": 15},
            "druggability_matrix": [],
            "featured_candidates_deep_dive": [],
        }

        mock_agent = MagicMock()

        async def mock_ainvoke(input_dict, config=None):
            # Simulate agent writing drug.md
            (mock_data_dir / "drug.md").write_text(mock_report)
            (mock_data_dir / "target_assessment.json").write_text(json.dumps(mock_json))
            return {"messages": []}

        mock_agent.ainvoke = mock_ainvoke

        # Patch at source module (lazy import inside the function)
        with patch(
            "src.agents.drug_target.agent.create_drug_target_agent",
            return_value=mock_agent,
        ):
            raw = await run_drug_target_assessment.ainvoke({
                "data_dir": str(mock_data_dir),
                "disease": "breast cancer",
            })

        result = json.loads(raw)
        assert result["success"] is True
        assert "Executive Summary" in result["drug_md"]
        assert result["target_assessment"]["project_meta"]["disease_focus"] == "breast cancer"

    @patch("src.agents.drug_target.agent.create_deep_agent")
    @patch("src.agents.drug_target.agent.create_llm")
    def test_create_agent_passes_subagents_with_2_entries(
        self, mock_create_llm, mock_create_deep_agent, tmp_path
    ):
        from src.agents.drug_target.agent import create_drug_target_agent, DrugTargetConfig

        mock_create_llm.return_value = MagicMock()
        mock_create_deep_agent.return_value = MagicMock()

        config = DrugTargetConfig(data_dir=str(tmp_path))
        create_drug_target_agent(config)

        call_kwargs = mock_create_deep_agent.call_args
        subagents = call_kwargs.kwargs.get("subagents") or call_kwargs[1].get("subagents")
        assert len(subagents) == 2
