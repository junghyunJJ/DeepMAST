"""Tests for Drug Target Assessment Agent.

7 test classes covering:
1. TestSubagentConfigs — Tool registration & prompt content
2. TestRubric — Rubric parsing, validation, scoring
3. TestEvidenceLoader — File I/O tools (tmp_path)
4. TestToolImports — Verify all tools importable
5. TestToolMocks — External API tools with mocked responses
5b. TestStage1Confidence — Stage 1 confidence scoring & filtering
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
    """tmp_path with lr_candidates.json only (no selected_top3_lr.json)."""
    (tmp_path / "lr_candidates.json").write_text(json.dumps(MOCK_LR_CANDIDATES))
    return tmp_path


@pytest.fixture
def mock_data_dir_with_top3(mock_data_dir):
    """mock_data_dir with selected_top3_lr.json for backward compat tests."""
    (mock_data_dir / "selected_top3_lr.json").write_text(json.dumps(MOCK_SELECTED_TOP3))
    return mock_data_dir


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
    (evi_dir / "gene_manifest.json").write_text(json.dumps([
        {"symbol": "TGFB1", "is_selected_top3": True},
    ]))
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
            "safety_profile": {"score": -1, "rationale": "Moderate immunosuppression risk"},
            "total": 3,
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
        "priority": "medium",
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
        assert len(tools) >= 12  # Stage 3 tools moved to deep_diver

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
            "finalize_stage1_artifacts",
            "sequential_thinking",
            "query_cellxgene_lr_context",
            "list_census_diseases",
            "query_kegg_pathways",
            "query_reactome_pathways",
            "query_string_ppi_pair",
            "query_stage2_gene_panel",
            "query_ensembl_vep_consequence",
            "run_compare_census_lr_pair",
            "run_batch_census_lr_pairs",
            "read_skill_file",
            "think_tool",
            "validate_quality",
        }
        assert expected.issubset(names)
        # Stage 3 tools must NOT be in evidence_assessor
        assert "query_chembl_target_profile" not in names
        assert "search_literature_dynamic" not in names
        assert "validate_stage3_gate" not in names

    def test_workflow_order(self):
        from src.agents.drug_target.subagents.configs import WORKFLOW_ORDER
        assert WORKFLOW_ORDER == ["evidence_assessor", "deep_diver", "hypothesis_writer", "report_writer"]

    def test_get_subagents_returns_4(self):
        from src.agents.drug_target.subagents.configs import get_subagents
        subagents = get_subagents()
        assert len(subagents) == 4

    def test_get_subagents_order(self):
        from src.agents.drug_target.subagents.configs import get_subagents
        subagents = get_subagents()
        names = [s["name"] for s in subagents]
        assert names == ["evidence_assessor", "deep_diver", "hypothesis_writer", "report_writer"]

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
        # Database references (ChEMBL moved to deep_diver)
        for keyword in ("OpenTargets", "GWAS"):
            assert keyword in prompt
        # Rubric references (merged from clinical_assessor)
        assert "rubric" in prompt.lower() or "RUBRIC" in prompt
        assert "validated" in prompt.lower()
        assert "exploratory" in prompt.lower()

    def test_evidence_assessor_prompt_mentions_2_stages(self):
        from src.agents.drug_target.subagents.configs import SUBAGENT_CONFIGS
        prompt = SUBAGENT_CONFIGS["evidence_assessor"]["system_prompt"]
        assert "Stage 1" in prompt
        assert "Stage 2" in prompt
        assert "2-Stage Funnel" in prompt

    def test_workflow_description_mentions_4_agents(self):
        from src.agents.drug_target.subagents.configs import WORKFLOW_DESCRIPTION

        assert "4-Agent Workflow" in WORKFLOW_DESCRIPTION
        assert "EVIDENCE_ASSESSOR" in WORKFLOW_DESCRIPTION
        assert "DEEP_DIVER" in WORKFLOW_DESCRIPTION
        assert "HYPOTHESIS_WRITER" in WORKFLOW_DESCRIPTION
        assert "REPORT_WRITER" in WORKFLOW_DESCRIPTION

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

    def test_deep_diver_has_stage3_tools(self):
        from src.agents.drug_target.subagents.configs import SUBAGENT_CONFIGS
        tools = SUBAGENT_CONFIGS["deep_diver"]["tools"]
        names = {t.name for t in tools}
        assert "query_chembl_target_profile" in names
        assert "search_literature_dynamic" in names
        assert "validate_stage3_gate" in names
        assert "save_evidence" in names
        assert "load_evidence_files" in names
        assert "read_skill_file" in names

    def test_deep_diver_prompt_contains_stage3(self):
        from src.agents.drug_target.subagents.configs import SUBAGENT_CONFIGS
        prompt = SUBAGENT_CONFIGS["deep_diver"]["system_prompt"]
        assert "Stage 3" in prompt
        assert "ChEMBL" in prompt
        assert "validate_stage3_gate" in prompt
        assert "Plan" in prompt and "Execute" in prompt and "Reflect" in prompt

    def test_hypothesis_writer_has_evidence_tools(self):
        from src.agents.drug_target.subagents.configs import SUBAGENT_CONFIGS
        tools = SUBAGENT_CONFIGS["hypothesis_writer"]["tools"]
        names = {t.name for t in tools}
        assert "load_evidence_files" in names
        assert "read_skill_file" in names
        assert "save_evidence" in names
        assert "think_tool" in names
        assert "sequential_thinking" in names

    def test_hypothesis_writer_has_no_db_tools(self):
        from src.agents.drug_target.subagents.configs import SUBAGENT_CONFIGS
        tools = SUBAGENT_CONFIGS["hypothesis_writer"]["tools"]
        names = {t.name for t in tools}
        # No database query tools
        db_tools = {
            "query_chembl_target_profile",
            "search_literature_dynamic",
            "query_stage2_gene_panel",
            "query_cellxgene_lr_context",
            "query_kegg_pathways",
            "query_reactome_pathways",
            "query_string_ppi_pair",
        }
        assert names.isdisjoint(db_tools)

    def test_hypothesis_writer_prompt_contains_ucb(self):
        from src.agents.drug_target.subagents.configs import SUBAGENT_CONFIGS
        prompt = SUBAGENT_CONFIGS["hypothesis_writer"]["system_prompt"]
        assert "UCB" in prompt
        assert "hypothesis" in prompt.lower()
        assert "hypothesis_report.json" in prompt
        assert "Evidence_Coverage" in prompt
        assert "Specificity" in prompt

    def test_subagent_prompts_registry_has_4_entries(self):
        from src.agents.drug_target.subagents.prompts import SUBAGENT_PROMPTS
        assert len(SUBAGENT_PROMPTS) == 4
        assert set(SUBAGENT_PROMPTS.keys()) == {
            "evidence_assessor", "deep_diver", "hypothesis_writer", "report_writer",
        }


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

    def test_load_lr_candidates_selected_top3_genes(self, mock_data_dir_with_top3):
        from src.agents.drug_target.tools.evidence_loader import load_lr_candidates
        raw = load_lr_candidates.invoke({"data_dir": str(mock_data_dir_with_top3)})
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

    def test_load_lr_candidates_is_selected_top3_flag(self, mock_data_dir_with_top3):
        from src.agents.drug_target.tools.evidence_loader import load_lr_candidates
        raw = load_lr_candidates.invoke({"data_dir": str(mock_data_dir_with_top3)})
        result = json.loads(raw)
        top3 = set(result["selected_top3_genes"])
        assert "TGFB1" in top3
        assert "CD44" in top3
        assert "FGF2" not in top3
        assert "NOTCH1" not in top3

    def test_load_lr_candidates_missing_file(self, tmp_path):
        from src.agents.drug_target.tools.evidence_loader import load_lr_candidates
        raw = load_lr_candidates.invoke({"data_dir": str(tmp_path)})
        result = json.loads(raw)
        assert len(result["errors"]) > 0
        assert "not found" in result["errors"][0]

    def test_load_lr_candidates_missing_top3_still_works(self, tmp_path):
        from src.agents.drug_target.tools.evidence_loader import load_lr_candidates
        (tmp_path / "lr_candidates.json").write_text(json.dumps(MOCK_LR_CANDIDATES))
        # No selected_top3_lr.json — this is the default now
        raw = load_lr_candidates.invoke({"data_dir": str(tmp_path)})
        result = json.loads(raw)
        assert len(result["gene_symbols"]) == 30
        assert len(result["selected_top3_genes"]) == 0
        # No error for missing top3 (it's info-level now, not an error)
        assert not any("selected_top3" in e.lower() for e in result["errors"])

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

    def test_load_lr_candidates_no_top3_default(self, mock_data_dir):
        """Without selected_top3_lr.json, selected_top3_genes should be empty."""
        from src.agents.drug_target.tools.evidence_loader import load_lr_candidates
        raw = load_lr_candidates.invoke({"data_dir": str(mock_data_dir)})
        result = json.loads(raw)
        assert len(result["selected_top3_genes"]) == 0
        # No errors related to missing top3
        assert not any("selected_top3" in e.lower() for e in result["errors"])

    def test_load_lr_candidates_candidate_pairs_key(self, tmp_path):
        """Verify candidate_pairs key fallback works."""
        from src.agents.drug_target.tools.evidence_loader import load_lr_candidates
        alt_data = {
            "disease": "glioblastoma",
            "candidate_pairs": [  # legacy key name from old lr_prioritizer
                {"ligand": "PDGFA", "receptor": "PDGFRA", "score": 0.91},
                {"ligand": "EGF", "receptor": "EGFR", "score": 0.88},
            ],
        }
        (tmp_path / "lr_candidates.json").write_text(json.dumps(alt_data))
        raw = load_lr_candidates.invoke({"data_dir": str(tmp_path)})
        result = json.loads(raw)
        assert len(result["lr_pairs"]) == 2
        assert "PDGFA" in result["gene_symbols"]
        assert "EGFR" in result["gene_symbols"]

    def test_rank_featured_candidates_ignores_selected_top3(self):
        """rank_featured_candidates output should be identical with/without is_selected_top3."""
        from src.agents.drug_target.tools.stage_logic import rank_featured_candidates
        base_row = {
            "gene_symbol": "TGFB1",
            "validated_track": {
                "existing_drug_evidence": {"score": 2, "rationale": "test"},
                "clinical_trial_activity": {"score": 1, "rationale": "test"},
                "safety_profile": {"score": 0, "rationale": "test"},
            },
            "exploratory_track": {
                "gwas_genetic_support": {"score": 1, "rationale": "test"},
                "tractability": {"score": 2, "rationale": "test"},
                "biological_plausibility": {"score": 2, "rationale": "test"},
                "novelty_opportunity": {"score": 1, "rationale": "test"},
            },
        }
        row_with = {**base_row, "is_selected_top3": True}
        row_without = {**base_row}
        result_with = rank_featured_candidates([row_with])
        result_without = rank_featured_candidates([row_without])
        # Same ranking regardless of is_selected_top3
        assert result_with[0]["is_featured"] == result_without[0]["is_featured"]
        assert result_with[0]["combined_total"] == result_without[0]["combined_total"]

    def test_load_evidence_files(self, mock_data_dir_with_evidence):
        from src.agents.drug_target.tools.evidence_loader import load_evidence_files
        raw = load_evidence_files.invoke({"data_dir": str(mock_data_dir_with_evidence)})
        result = json.loads(raw)
        assert result["file_count"] == 2
        assert "ot_TGFB1.json" in result["files"]

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

        # Roundtrip: load it back (returns summary metadata, not full content)
        raw2 = load_evidence_files.invoke({"data_dir": str(tmp_path)})
        result2 = json.loads(raw2)
        assert "test_gene.json" in result2["files"]
        assert "gene" in result2["files"]["test_gene.json"]["top_keys"]

    def test_save_evidence_non_json_rejected(self, tmp_path):
        from src.agents.drug_target.tools.evidence_loader import save_evidence
        raw = save_evidence.invoke({
            "data_dir": str(tmp_path),
            "filename": "notes.json",
            "data": "This is not valid JSON",
        })
        result = json.loads(raw)
        assert result["saved"] is False
        assert any("not valid JSON" in e for e in result["errors"])


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
        assert stage_domain_tools.query_stage2_gene_panel.name == "query_stage2_gene_panel"
        assert stage_domain_tools.query_ensembl_vep_consequence.name == "query_ensembl_vep_consequence"
        assert stage_domain_tools.query_chembl_target_profile.name == "query_chembl_target_profile"
        assert stage_domain_tools.query_pubmed_clinical_limitations.name == "query_pubmed_clinical_limitations"

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
            "query_cellxgene_lr_context", "list_census_diseases",
            "query_kegg_pathways", "query_reactome_pathways",
            "query_string_ppi_pair", "query_ensembl_vep_consequence",
            "query_opentargets_target", "query_opentargets_known_drugs",
            "query_gwas_gene_trait", "query_stage2_gene_panel",
            "query_chembl_target_profile", "query_pubmed_clinical_limitations",
            "run_compare_census_lr_pair",
            "finalize_stage1_artifacts",
            "read_skill_file",
            "save_target_assessment",
            "think_tool", "sequential_thinking", "validate_quality",
        ]
        assert set(expected).issubset(set(__all__))

    def test_import_common_sequential_thinking(self):
        from src.agents.drug_target.tools.common import sequential_thinking
        assert sequential_thinking.name == "sequential_thinking"


# =========================================================================
# 5. TestStage2Service
# =========================================================================

class TestStage2Service:
    """Batch Stage 2 orchestration and canonical artifact contract."""

    def test_load_stage2_inputs_extracts_candidate_pairs_and_selected_top3(self, tmp_path):
        from src.agents.drug_target.tools.stage2_service import load_stage2_inputs

        (tmp_path / "lr_candidates.json").write_text(json.dumps({
            "disease_context": "lung cancer",
            "candidate_pairs": [
                {"ligand": "met", "receptor": "EGFR"},
                {"ligand": "MET", "receptor": "erbb2"},
            ],
        }))
        (tmp_path / "selected_top3_lr.json").write_text(json.dumps({
            "selected_pairs": [{"ligand": "EGFR", "receptor": "ERBB2"}],
        }))

        result = load_stage2_inputs(tmp_path)

        assert result["disease"] == "lung cancer"
        assert result["gene_symbols"] == ["EGFR", "ERBB2", "MET"]
        assert result["selected_top3_genes"] == ["EGFR", "ERBB2"]
        assert len(result["pairs"]) == 2

    def test_build_stage2_gene_panel_dedups_and_sorts_genes(self):
        import src.agents.drug_target.tools.stage2_service as mod

        ot_calls = []
        gwas_calls = []

        def fake_ot(gene_symbol, disease, *, mod=None, disease_context=None):
            ot_calls.append((gene_symbol, disease_context))
            return {"gene_symbol": gene_symbol, "executed": True, "errors": []}

        def fake_gwas(gene_symbol, disease, *, mod=None, disease_context=None):
            gwas_calls.append((gene_symbol, disease_context))
            return {"gene_symbol": gene_symbol, "executed": True, "errors": []}

        with patch.object(mod, "_try_load_ot_module", return_value=(object(), "parquet")), \
             patch.object(mod, "_try_load_gwas_module", return_value=(object(), "parquet")), \
             patch.object(mod, "_build_ot_disease_context", return_value={"efo_id": "EFO_1"}) as ot_ctx, \
             patch.object(mod, "_build_gwas_disease_context", return_value={"trait_associations": []}) as gwas_ctx, \
             patch.object(mod, "query_opentargets_target_data", side_effect=fake_ot), \
             patch.object(mod, "query_gwas_gene_trait_data", side_effect=fake_gwas), \
             patch.object(mod, "query_opentargets_known_drugs_data", return_value={"executed": True, "errors": []}):
            result = mod.build_stage2_gene_panel(
                ["met", "EGFR", "egfr", " MET "],
                "lung cancer",
                selected_top3_genes=["met"],
            )

        assert result["gene_symbols"] == ["EGFR", "MET"]
        assert list(result["stage2_evidence"]) == ["EGFR", "MET"]
        assert result["gene_manifest"] == [
            {"symbol": "EGFR", "is_selected_top3": False},
            {"symbol": "MET", "is_selected_top3": True},
        ]
        assert [call[0] for call in ot_calls] == ["EGFR", "MET"]
        assert [call[0] for call in gwas_calls] == ["EGFR", "MET"]
        assert ot_ctx.call_count == 1
        assert gwas_ctx.call_count == 1

    def test_build_stage2_gene_panel_uses_workspace_cache_when_exact_match(self, tmp_path):
        import src.agents.drug_target.tools.stage2_service as mod

        bundle = {
            "disease": "lung cancer",
            "gene_symbols": ["EGFR"],
            "stage2_evidence": {
                "EGFR": {
                    "opentargets": {
                        "gene_symbol": "EGFR",
                        "disease": "lung cancer",
                        "executed": True,
                        "errors": [],
                    },
                    "gwas": {
                        "gene_symbol": "EGFR",
                        "disease": "lung cancer",
                        "executed": True,
                        "errors": [],
                    },
                    "vep": {
                        "source": "ensembl_vep",
                        "variants": [],
                    },
                },
            },
            "known_drugs": {"disease": "lung cancer", "executed": True},
            "gene_manifest": [{"symbol": "EGFR", "is_selected_top3": True}],
        }
        mod.write_stage2_artifacts(bundle, tmp_path / "evidence")

        with patch.object(mod, "_try_load_ot_module", side_effect=AssertionError("cache should bypass OT setup")), \
             patch.object(mod, "_try_load_gwas_module", side_effect=AssertionError("cache should bypass GWAS setup")):
            result = mod.build_stage2_gene_panel(
                ["EGFR"],
                "lung cancer",
                selected_top3_genes=["EGFR"],
                data_dir=tmp_path,
            )

        assert result["stage2_evidence"] == bundle["stage2_evidence"]
        assert result["known_drugs"] == bundle["known_drugs"]
        assert result["gene_manifest"] == bundle["gene_manifest"]
        assert result["source_modes"] == {"opentargets": "cache", "gwas": "cache"}

    def test_build_stage2_gene_panel_cache_miss_rebuilds_on_manifest_mismatch(self, tmp_path):
        import src.agents.drug_target.tools.stage2_service as mod

        cached_bundle = {
            "disease": "lung cancer",
            "gene_symbols": ["EGFR"],
            "stage2_evidence": {
                "EGFR": {
                    "opentargets": {
                        "gene_symbol": "EGFR",
                        "disease": "lung cancer",
                        "executed": True,
                        "errors": [],
                    },
                    "gwas": {
                        "gene_symbol": "EGFR",
                        "disease": "lung cancer",
                        "executed": True,
                        "errors": [],
                    },
                },
            },
            "known_drugs": {"disease": "lung cancer", "executed": True},
            "gene_manifest": [{"symbol": "EGFR", "is_selected_top3": True}],
        }
        mod.write_stage2_artifacts(cached_bundle, tmp_path / "evidence")

        ot_calls = []
        gwas_calls = []

        def fake_ot(gene_symbol, disease, *, mod=None, disease_context=None):
            ot_calls.append(gene_symbol)
            return {"gene_symbol": gene_symbol, "disease": disease, "executed": True, "errors": []}

        def fake_gwas(gene_symbol, disease, *, mod=None, disease_context=None):
            gwas_calls.append(gene_symbol)
            return {"gene_symbol": gene_symbol, "disease": disease, "executed": True, "errors": []}

        with patch.object(mod, "_try_load_ot_module", return_value=(object(), "parquet")), \
             patch.object(mod, "_try_load_gwas_module", return_value=(object(), "parquet")), \
             patch.object(mod, "_build_ot_disease_context", return_value={"efo_id": "EFO_1"}), \
             patch.object(mod, "_build_gwas_disease_context", return_value={"trait_associations": []}), \
             patch.object(mod, "query_opentargets_target_data", side_effect=fake_ot), \
             patch.object(mod, "query_gwas_gene_trait_data", side_effect=fake_gwas), \
             patch.object(mod, "query_opentargets_known_drugs_data", return_value={"disease": "lung cancer", "executed": True}):
            result = mod.build_stage2_gene_panel(
                ["EGFR"],
                "lung cancer",
                selected_top3_genes=[],
                data_dir=tmp_path,
            )

        assert ot_calls == ["EGFR"]
        assert gwas_calls == ["EGFR"]
        assert result["gene_manifest"] == [{"symbol": "EGFR", "is_selected_top3": False}]
        assert result["source_modes"] == {"opentargets": "parquet", "gwas": "parquet"}

    def test_query_opentargets_target_data_uses_bundle_helper(self):
        from src.agents.drug_target.tools.stage2_service import query_opentargets_target_data

        bundle_calls = []

        class FakeOpenTargetsModule:
            def search_entities(self, query_string, entity_types=None):
                if entity_types == ["target"]:
                    return [{"id": "ENSG000001"}]
                return [{"id": "EFO_0001"}]

            def get_target_bundle(self, ensembl_id, efo_id=None, min_score=0.0):
                bundle_calls.append((ensembl_id, efo_id, min_score))
                return {
                    "target_info": {"approvedSymbol": "EGFR"},
                    "disease_evidence": [{"datasourceId": "ot"}],
                    "associations": [{"score": 0.9}],
                }

            def get_target_info(self, *args, **kwargs):
                raise AssertionError("get_target_info should not be called when bundle helper exists")

            def get_target_disease_evidence(self, *args, **kwargs):
                raise AssertionError("get_target_disease_evidence should not be called when bundle helper exists")

            def get_target_associations(self, *args, **kwargs):
                raise AssertionError("get_target_associations should not be called when bundle helper exists")

        result = query_opentargets_target_data(
            "EGFR",
            "lung cancer",
            mod=FakeOpenTargetsModule(),
            disease_context={"efo_id": "EFO_0001"},
        )

        assert result["executed"] is True
        assert bundle_calls == [("ENSG000001", "EFO_0001", 0.1)]
        assert result["target_info"]["approvedSymbol"] == "EGFR"

    def test_build_stage2_gene_panel_reuses_gwas_disease_context_once(self):
        import src.agents.drug_target.tools.stage2_service as mod

        class FakeOpenTargetsModule:
            def search_entities(self, query_string, entity_types=None):
                if entity_types == ["target"]:
                    return [{"id": f"ENSG_{query_string.upper()}"}]
                return [{"id": "EFO_0001"}]

            def get_target_bundle(self, ensembl_id, efo_id=None, min_score=0.0):
                return {
                    "target_info": {"id": ensembl_id},
                    "disease_evidence": [],
                    "associations": [],
                }

            def get_known_drugs_for_disease(self, efo_id):
                return {"rows": [], "uniqueDrugs": 0, "uniqueTargets": 0}

        class FakeGWASModule:
            def __init__(self):
                self.context_calls = 0
                self.query_calls = 0

            def build_disease_context(self, disease):
                self.context_calls += 1
                return {
                    "disease": disease,
                    "efo_traits": [{"shortForm": "EFO_0001"}],
                    "trait_associations": [],
                }

            def query_gene_trait_with_context(self, gene_symbol, disease, *, disease_context=None):
                self.query_calls += 1
                return {
                    "gene_symbol": gene_symbol,
                    "disease": disease,
                    "executed": True,
                    "efo_traits": disease_context["efo_traits"],
                    "trait_associations": disease_context["trait_associations"],
                    "gene_associations": [],
                    "errors": [],
                }

        fake_gwas = FakeGWASModule()

        with patch.object(mod, "_try_load_ot_module", return_value=(FakeOpenTargetsModule(), "parquet")), \
             patch.object(mod, "_try_load_gwas_module", return_value=(fake_gwas, "parquet")):
            result = mod.build_stage2_gene_panel(["EGFR", "MET"], "lung cancer")

        assert fake_gwas.context_calls == 1
        assert fake_gwas.query_calls == 2
        assert result["gene_symbols"] == ["EGFR", "MET"]

    def test_build_stage2_gene_panel_keeps_partial_source_failures_nonfatal(self):
        import src.agents.drug_target.tools.stage2_service as mod

        with patch.object(mod, "_try_load_ot_module", side_effect=RuntimeError("ot down")), \
             patch.object(mod, "_try_load_gwas_module", return_value=(object(), "parquet")), \
             patch.object(mod, "_build_gwas_disease_context", return_value={"trait_associations": []}), \
             patch.object(
                 mod,
                 "query_gwas_gene_trait_data",
                 return_value={"gene_symbol": "EGFR", "executed": True, "errors": []},
             ):
            result = mod.build_stage2_gene_panel(["EGFR"], "lung cancer")

        ot_result = result["stage2_evidence"]["EGFR"]["opentargets"]
        gwas_result = result["stage2_evidence"]["EGFR"]["gwas"]
        assert result["source_modes"]["opentargets"] == "unavailable"
        assert ot_result["executed"] is False
        assert "OpenTargets setup failed" in ot_result["errors"][0]
        assert result["known_drugs"]["executed"] is False
        assert gwas_result["executed"] is True

    def test_write_stage2_artifacts_writes_canonical_files(self, tmp_path):
        from src.agents.drug_target.tools.stage2_service import write_stage2_artifacts

        bundle = {
            "gene_symbols": ["EGFR", "MET"],
            "stage2_evidence": {
                "EGFR": {
                    "opentargets": {"gene_symbol": "EGFR", "executed": True},
                    "gwas": {"gene_symbol": "EGFR", "executed": True},
                },
                "MET": {
                    "opentargets": {"gene_symbol": "MET", "executed": False},
                    "gwas": {"gene_symbol": "MET", "executed": True},
                },
            },
            "known_drugs": {"disease": "lung cancer", "executed": True},
            "gene_manifest": [
                {"symbol": "EGFR", "is_selected_top3": False},
                {"symbol": "MET", "is_selected_top3": True},
            ],
        }

        written = write_stage2_artifacts(bundle, tmp_path / "evidence")

        assert {path.name for path in written} == {
            "stage2_evidence.json",
            "known_drugs.json",
            "gene_manifest.json",
            "ot_EGFR.json",
            "ot_MET.json",
        }
        assert json.loads((tmp_path / "evidence" / "gene_manifest.json").read_text()) == [
            {"symbol": "EGFR", "is_selected_top3": False},
            {"symbol": "MET", "is_selected_top3": True},
        ]
        assert json.loads((tmp_path / "evidence" / "ot_EGFR.json").read_text()) == {
            "gene_symbol": "EGFR",
            "executed": True,
        }

    def test_query_stage2_gene_panel_tool_returns_bundle_json(self, tmp_path):
        from src.agents.drug_target.tools.stage_domain_tools import query_stage2_gene_panel

        payload = {
            "disease": "lung cancer",
            "gene_symbols": ["EGFR"],
            "stage2_evidence": {
                "EGFR": {
                    "opentargets": {
                        "executed": True,
                        "ensembl_id": "ENSG00000146648",
                        "disease_evidence": [],
                        "associations": [],
                        "errors": [],
                    },
                    "gwas": {
                        "executed": True,
                        "trait_associations": [],
                        "gene_associations": [],
                        "errors": [],
                    },
                }
            },
            "known_drugs": {"executed": True, "drugs": {"EGFR": []}},
            "gene_manifest": [{"symbol": "EGFR", "is_selected_top3": True}],
            "source_modes": {"opentargets": "parquet", "gwas": "parquet"},
        }

        data_dir = str(tmp_path)
        with patch(
            "src.agents.drug_target.tools.stage_domain_tools.build_stage2_gene_panel",
            return_value=payload,
        ) as mock_build:
            raw = query_stage2_gene_panel.invoke({
                "gene_symbols": ["EGFR"],
                "disease": "lung cancer",
                "selected_top3_genes": ["EGFR"],
                "data_dir": data_dir,
            })

        mock_build.assert_called_once_with(
            ["EGFR"],
            "lung cancer",
            selected_top3_genes=["EGFR"],
            data_dir=data_dir,
        )
        result = json.loads(raw)
        assert result["disease"] == "lung cancer"
        assert result["gene_count"] == 1
        assert result["gene_symbols"] == ["EGFR"]
        assert result["known_drugs_executed"] is True
        assert result["source_modes"] == {"opentargets": "parquet", "gwas": "parquet"}
        assert result["gene_manifest"] == [{"symbol": "EGFR", "is_selected_top3": True}]
        assert result["evidence_dir"] == str(tmp_path / "evidence")
        # Gene summary
        egfr = result["gene_summaries"]["EGFR"]
        assert egfr["has_ensembl_id"] is True
        assert egfr["ot_executed"] is True
        assert egfr["gwas_executed"] is True


# =========================================================================
# 6. TestStageContracts — Dynamic featured ranking, gating, output contract
# =========================================================================

class TestStageContracts:
    """Decision logic and JSON output contract for staged pipeline."""

    def test_rank_featured_candidates_dual_track(self):
        from src.agents.drug_target.tools.stage_logic import rank_featured_candidates

        def _row(ligand, receptor, vt_scores, et_scores):
            return {
                "ligand": ligand,
                "receptor": receptor,
                "open_targets_score": 0.5,
                "validated_track": dict(zip(
                    ("existing_drug_evidence", "clinical_trial_activity", "safety_profile"),
                    vt_scores,
                )),
                "exploratory_track": dict(zip(
                    ("gwas_genetic_support", "tractability", "biological_plausibility", "novelty_opportunity"),
                    et_scores,
                )),
            }

        matrix = [
            # Featured pool (drug_evidence >= 1)
            _row("A", "B", (3, 3, 0), (3, 3, 3, 3)),   # combined=18
            _row("C", "D", (2, 2, -1), (2, 2, 2, 2)),   # combined=11
            _row("E", "F", (1, 1, 0), (1, 1, 2, 1)),    # combined=7
            _row("G", "H", (1, 0, 0), (1, 1, 1, 1)),    # combined=5
            # Novel pool (drug_evidence == 0)
            _row("I", "J", (0, 1, 0), (1, 1, 1, 0)),    # exploratory_total=3
            _row("K", "L", (0, 0, 0), (0, 0, 1, 0)),    # exploratory_total=1
        ]

        ranked = rank_featured_candidates(matrix)
        featured = [row for row in ranked if row["is_featured"]]
        novel = [row for row in ranked if row.get("is_novel")]

        # Featured: drug_evidence >= 1 rows
        assert 2 <= len(featured) <= 5
        assert featured[0]["ligand"] == "A"
        assert featured[0]["combined_total"] == 18
        assert all(not r["is_novel"] for r in featured)

        # Novel: drug_evidence == 0 rows
        assert len(novel) >= 1
        assert all(not r["is_featured"] for r in novel)

        # All rows have both flags
        for r in ranked:
            assert "is_featured" in r
            assert "is_novel" in r

    def test_stage_gate_rules(self):
        from src.agents.drug_target.tools.stage_logic import should_run_pubmed

        # VEP now runs automatically for all genes (no gate needed)
        assert should_run_pubmed("Phase 2") is True
        assert should_run_pubmed("phase 1") is False

    def test_insufficient_evidence_excluded_from_both_tracks(self):
        from src.agents.drug_target.tools.stage_logic import rank_featured_candidates

        def _row(ligand, receptor, vt_scores, et_scores):
            return {
                "ligand": ligand,
                "receptor": receptor,
                "open_targets_score": 0.5,
                "validated_track": dict(zip(
                    ("existing_drug_evidence", "clinical_trial_activity", "safety_profile"),
                    vt_scores,
                )),
                "exploratory_track": dict(zip(
                    ("gwas_genetic_support", "tractability", "biological_plausibility", "novelty_opportunity"),
                    et_scores,
                )),
            }

        matrix = [
            # Featured pool (drug_evidence >= 1)
            _row("A", "B", (2, 2, 0), (2, 2, 3, 2)),    # validated_target, combined=13
            _row("C", "D", (1, 1, 0), (1, 2, 2, 1)),    # validated_target, combined=8
            # Novel pool (drug_evidence == 0, eligible)
            _row("E", "F", (0, 0, 0), (2, 1, 2, 1)),    # exploratory_target, exploratory_total=6
            # insufficient_evidence — must NOT be featured or novel
            _row("G", "H", (0, 0, 0), (0, 0, 0, 0)),    # insufficient_evidence, combined=0
            _row("I", "J", (0, 0, 0), (0, 0, 1, 0)),    # insufficient_evidence, combined=1
        ]

        ranked = rank_featured_candidates(matrix, min_featured=2, max_featured=5)

        featured = [r for r in ranked if r["is_featured"]]
        novel = [r for r in ranked if r.get("is_novel")]

        # 2 featured (drug_evidence >= 1)
        assert len(featured) == 2
        assert all(r["classification"] != "insufficient_evidence" for r in featured)

        # 1 novel (drug_evidence == 0, eligible)
        assert len(novel) == 1
        assert novel[0]["ligand"] == "E"

        # insufficient_evidence rows have rank=None, is_featured=False, is_novel=False
        for r in ranked:
            if r["classification"] == "insufficient_evidence":
                assert r["rank"] is None
                assert r["is_featured"] is False
                assert r["is_novel"] is False


# =========================================================================
# 5. TestVepTool — Ensembl VEP with mocked HTTP responses
# =========================================================================

class TestVepTool:
    """query_ensembl_vep_consequence with mocked requests."""

    def test_vep_single_variant_missense(self, monkeypatch):
        import src.agents.drug_target.tools.stage_domain_tools as mod

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = [
            {
                "input": "rs1042522",
                "id": "rs1042522",
                "most_severe_consequence": "missense_variant",
            }
        ]
        monkeypatch.setattr(mod.requests, "post", lambda *a, **kw: mock_resp)

        raw = mod.query_ensembl_vep_consequence.invoke({
            "variant_ids": "rs1042522",
        })
        result = json.loads(raw)
        assert result["executed"] is True
        assert len(result["variants"]) == 1
        assert result["variants"][0]["most_severe_consequence"] == "missense_variant"
        assert result["variants"][0]["id"] == "rs1042522"

    def test_vep_multiple_variants(self, monkeypatch):
        import src.agents.drug_target.tools.stage_domain_tools as mod

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = [
            {"input": "rs699", "id": "rs699", "most_severe_consequence": "missense_variant"},
            {"input": "rs28934578", "id": "rs28934578", "most_severe_consequence": "stop_gained"},
        ]
        monkeypatch.setattr(mod.requests, "post", lambda *a, **kw: mock_resp)

        raw = mod.query_ensembl_vep_consequence.invoke({
            "variant_ids": "rs699, rs28934578",
        })
        result = json.loads(raw)
        assert result["executed"] is True
        assert len(result["variants"]) == 2
        consequences = {v["id"]: v["most_severe_consequence"] for v in result["variants"]}
        assert consequences["rs699"] == "missense_variant"
        assert consequences["rs28934578"] == "stop_gained"

    def test_vep_empty_variant_ids(self):
        from src.agents.drug_target.tools.stage_domain_tools import query_ensembl_vep_consequence

        raw = query_ensembl_vep_consequence.invoke({"variant_ids": ""})
        result = json.loads(raw)
        assert result["executed"] is False
        assert "No variant IDs" in result["errors"][0]

    def test_vep_api_failure(self, monkeypatch):
        import src.agents.drug_target.tools.stage_domain_tools as mod

        def raise_error(*a, **kw):
            raise ConnectionError("Ensembl API unreachable")
        monkeypatch.setattr(mod.requests, "post", raise_error)

        raw = mod.query_ensembl_vep_consequence.invoke({
            "variant_ids": "rs1042522",
        })
        result = json.loads(raw)
        assert result["executed"] is False
        assert "VEP query failed" in result["errors"][0]

    def test_vep_functional_impact_detection(self):
        """VEP impact detection identifies high and moderate impact variants."""
        from src.agents.drug_target.tools.stage_logic import _has_vep_functional_impact

        # High impact
        assert _has_vep_functional_impact(
            {"executed": True, "impact_summary": {"high_impact": 1, "low_impact": 5}}
        ) is True
        # Moderate impact
        assert _has_vep_functional_impact(
            {"executed": True, "impact_summary": {"moderate_impact": 3, "low_impact": 10}}
        ) is True
        # Low impact only
        assert _has_vep_functional_impact(
            {"executed": True, "impact_summary": {"low_impact": 13}}
        ) is False
        # Not executed
        assert _has_vep_functional_impact({"executed": False}) is False
        # None
        assert _has_vep_functional_impact(None) is False

    def test_classify_vep_consequence(self):
        """classify_vep_consequence categorizes impact severity."""
        from src.agents.drug_target.tools.stage_logic import classify_vep_consequence

        # High impact
        assert classify_vep_consequence("stop_gained") == "high_impact"
        assert classify_vep_consequence("frameshift_variant") == "high_impact"
        assert classify_vep_consequence("splice_donor_variant") == "high_impact"
        # Moderate impact
        assert classify_vep_consequence("missense_variant") == "moderate_impact"
        assert classify_vep_consequence("inframe_deletion") == "moderate_impact"
        # Low impact
        assert classify_vep_consequence("synonymous_variant") == "low_impact"
        assert classify_vep_consequence("intron_variant") == "low_impact"

    def test_vep_consequence_severity_interpretation(self, monkeypatch):
        """Driver mutations (stop_gained, frameshift) vs passenger (synonymous)."""
        import src.agents.drug_target.tools.stage_domain_tools as mod

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = [
            {"input": "rs111", "id": "rs111", "most_severe_consequence": "stop_gained"},
            {"input": "rs222", "id": "rs222", "most_severe_consequence": "synonymous_variant"},
            {"input": "rs333", "id": "rs333", "most_severe_consequence": "frameshift_variant"},
        ]
        monkeypatch.setattr(mod.requests, "post", lambda *a, **kw: mock_resp)

        raw = mod.query_ensembl_vep_consequence.invoke({
            "variant_ids": "rs111,rs222,rs333",
        })
        result = json.loads(raw)
        assert result["executed"] is True

        consequences = {v["id"]: v["most_severe_consequence"] for v in result["variants"]}
        # Driver-like
        assert consequences["rs111"] == "stop_gained"
        assert consequences["rs333"] == "frameshift_variant"
        # Passenger-like
        assert consequences["rs222"] == "synonymous_variant"


# =========================================================================
# 5b. TestRubricScoring — RUBRIC validation, classification, priority
# =========================================================================

class TestRubricScoring:
    """DRUG_TARGET_RUBRIC scoring logic from stage_logic.py."""

    # --- Schema validation ---

    def test_valid_assessment_passes_validation(self, valid_assessment):
        from src.agents.drug_target.tools.stage_logic import validate_rubric_assessment
        errors = validate_rubric_assessment(valid_assessment)
        assert errors == []

    def test_missing_validated_track(self):
        from src.agents.drug_target.tools.stage_logic import validate_rubric_assessment
        errors = validate_rubric_assessment({"exploratory_track": {
            "gwas_genetic_support": 1, "tractability": 1,
            "biological_plausibility": 1, "novelty_opportunity": 1,
        }})
        assert any("validated_track" in e for e in errors)

    def test_missing_exploratory_track(self):
        from src.agents.drug_target.tools.stage_logic import validate_rubric_assessment
        errors = validate_rubric_assessment({"validated_track": {
            "existing_drug_evidence": 1, "clinical_trial_activity": 1,
            "safety_profile": 0,
        }})
        assert any("exploratory_track" in e for e in errors)

    def test_missing_criterion_detected(self):
        from src.agents.drug_target.tools.stage_logic import validate_rubric_assessment
        errors = validate_rubric_assessment({
            "validated_track": {
                "existing_drug_evidence": 2,
                # missing clinical_trial_activity, safety_profile
            },
            "exploratory_track": {
                "gwas_genetic_support": 1, "tractability": 1,
                "biological_plausibility": 1, "novelty_opportunity": 1,
            },
        })
        assert any("clinical_trial_activity" in e for e in errors)

    def test_safety_profile_out_of_range(self):
        from src.agents.drug_target.tools.stage_logic import validate_rubric_assessment
        errors = validate_rubric_assessment({
            "validated_track": {
                "existing_drug_evidence": {"score": 2, "rationale": ""},
                "clinical_trial_activity": {"score": 1, "rationale": ""},
                "safety_profile": {"score": 1, "rationale": "should be <=0"},
            },
            "exploratory_track": {
                "gwas_genetic_support": {"score": 1, "rationale": ""},
                "tractability": {"score": 1, "rationale": ""},
                "biological_plausibility": {"score": 1, "rationale": ""},
                "novelty_opportunity": {"score": 1, "rationale": ""},
            },
        })
        assert any("safety_profile" in e for e in errors)

    def test_score_above_max_detected(self):
        from src.agents.drug_target.tools.stage_logic import validate_rubric_assessment
        errors = validate_rubric_assessment({
            "validated_track": {
                "existing_drug_evidence": {"score": 6, "rationale": "too high"},
                "clinical_trial_activity": {"score": 1, "rationale": ""},
                "safety_profile": {"score": 0, "rationale": ""},
            },
            "exploratory_track": {
                "gwas_genetic_support": {"score": 1, "rationale": ""},
                "tractability": {"score": 1, "rationale": ""},
                "biological_plausibility": {"score": 1, "rationale": ""},
                "novelty_opportunity": {"score": 1, "rationale": ""},
            },
        })
        assert any("existing_drug_evidence" in e for e in errors)

    # --- Validated track pass logic ---

    def test_validated_pass_drug_evidence_ge_2(self):
        from src.agents.drug_target.tools.stage_logic import compute_validated_track
        result = compute_validated_track({"validated_track": {
            "existing_drug_evidence": 2, "clinical_trial_activity": 0,
            "safety_profile": 0,
        }})
        assert result["pass"] is True

    def test_validated_pass_drug_1_and_trial_1(self):
        from src.agents.drug_target.tools.stage_logic import compute_validated_track
        result = compute_validated_track({"validated_track": {
            "existing_drug_evidence": 1, "clinical_trial_activity": 1,
            "safety_profile": 0,
        }})
        assert result["pass"] is True

    def test_validated_fail_drug_0(self):
        from src.agents.drug_target.tools.stage_logic import compute_validated_track
        result = compute_validated_track({"validated_track": {
            "existing_drug_evidence": 0, "clinical_trial_activity": 3,
            "safety_profile": 0,
        }})
        assert result["pass"] is False

    def test_validated_fail_drug_1_trial_0(self):
        from src.agents.drug_target.tools.stage_logic import compute_validated_track
        result = compute_validated_track({"validated_track": {
            "existing_drug_evidence": 1, "clinical_trial_activity": 0,
            "safety_profile": 0,
        }})
        assert result["pass"] is False

    def test_validated_total_includes_negative_safety(self):
        from src.agents.drug_target.tools.stage_logic import compute_validated_track
        result = compute_validated_track({"validated_track": {
            "existing_drug_evidence": 3, "clinical_trial_activity": 2,
            "safety_profile": -2,
        }})
        assert result["total"] == 3  # 3+2+(-2)
        assert result["pass"] is True

    # --- Exploratory track pass logic ---

    def test_exploratory_pass_gwas_1_tract_1(self):
        from src.agents.drug_target.tools.stage_logic import compute_exploratory_track
        result = compute_exploratory_track({"exploratory_track": {
            "gwas_genetic_support": 1, "tractability": 1,
            "biological_plausibility": 0, "novelty_opportunity": 0,
        }})
        assert result["pass"] is True

    def test_exploratory_pass_gwas_1_bio_3(self):
        from src.agents.drug_target.tools.stage_logic import compute_exploratory_track
        result = compute_exploratory_track({"exploratory_track": {
            "gwas_genetic_support": 1, "tractability": 0,
            "biological_plausibility": 3, "novelty_opportunity": 0,
        }})
        assert result["pass"] is True

    def test_exploratory_pass_no_gwas_but_tract_2(self):
        """tractability >= 2 alone is enough for exploratory pass."""
        from src.agents.drug_target.tools.stage_logic import compute_exploratory_track
        result = compute_exploratory_track({"exploratory_track": {
            "gwas_genetic_support": 0, "tractability": 2,
            "biological_plausibility": 0, "novelty_opportunity": 0,
        }})
        assert result["pass"] is True

    def test_exploratory_pass_gwas_1_alone(self):
        """gwas >= 1 alone is enough for exploratory pass."""
        from src.agents.drug_target.tools.stage_logic import compute_exploratory_track
        result = compute_exploratory_track({"exploratory_track": {
            "gwas_genetic_support": 1, "tractability": 0,
            "biological_plausibility": 0, "novelty_opportunity": 0,
        }})
        assert result["pass"] is True

    def test_exploratory_fail_all_below_threshold(self):
        """No single criterion meets the exploratory threshold."""
        from src.agents.drug_target.tools.stage_logic import compute_exploratory_track
        result = compute_exploratory_track({"exploratory_track": {
            "gwas_genetic_support": 0, "tractability": 1,
            "biological_plausibility": 2, "novelty_opportunity": 3,
        }})
        assert result["pass"] is False

    # --- Classification ---

    def test_classify_validated_target(self, valid_assessment):
        from src.agents.drug_target.tools.stage_logic import classify_target
        assert classify_target(valid_assessment) == "validated_target"

    def test_classify_exploratory_target(self):
        from src.agents.drug_target.tools.stage_logic import classify_target
        assessment = {
            "validated_track": {
                "existing_drug_evidence": 0, "clinical_trial_activity": 0,
                "safety_profile": 0,
            },
            "exploratory_track": {
                "gwas_genetic_support": 2, "tractability": 2,
                "biological_plausibility": 2, "novelty_opportunity": 1,
            },
        }
        assert classify_target(assessment) == "exploratory_target"

    def test_classify_exploratory_via_bio_plausibility(self):
        """bio >= 3 alone triggers exploratory_target (no gwas needed)."""
        from src.agents.drug_target.tools.stage_logic import classify_target
        assessment = {
            "validated_track": {
                "existing_drug_evidence": 0, "clinical_trial_activity": 0,
                "safety_profile": 0,
            },
            "exploratory_track": {
                "gwas_genetic_support": 0, "tractability": 0,
                "biological_plausibility": 3, "novelty_opportunity": 0,
            },
        }
        assert classify_target(assessment) == "exploratory_target"

    def test_classify_novel_candidate_via_bio_2(self):
        """bio >= 2 (but < 3) triggers novel_candidate."""
        from src.agents.drug_target.tools.stage_logic import classify_target
        assessment = {
            "validated_track": {
                "existing_drug_evidence": 0, "clinical_trial_activity": 0,
                "safety_profile": 0,
            },
            "exploratory_track": {
                "gwas_genetic_support": 0, "tractability": 0,
                "biological_plausibility": 2, "novelty_opportunity": 0,
            },
        }
        assert classify_target(assessment) == "novel_candidate"

    def test_classify_novel_candidate_via_novelty(self):
        from src.agents.drug_target.tools.stage_logic import classify_target
        assessment = {
            "validated_track": {
                "existing_drug_evidence": 0, "clinical_trial_activity": 0,
                "safety_profile": 0,
            },
            "exploratory_track": {
                "gwas_genetic_support": 0, "tractability": 0,
                "biological_plausibility": 0, "novelty_opportunity": 3,
            },
        }
        assert classify_target(assessment) == "novel_candidate"

    def test_classify_insufficient_evidence(self):
        from src.agents.drug_target.tools.stage_logic import classify_target
        assessment = {
            "validated_track": {
                "existing_drug_evidence": 0, "clinical_trial_activity": 0,
                "safety_profile": 0,
            },
            "exploratory_track": {
                "gwas_genetic_support": 0, "tractability": 0,
                "biological_plausibility": 1, "novelty_opportunity": 1,
            },
        }
        assert classify_target(assessment) == "insufficient_evidence"

    # --- Priority ---

    def test_priority_high_validated(self, valid_assessment):
        from src.agents.drug_target.tools.stage_logic import compute_priority
        # valid_assessment: combined_total = validated(3) + exploratory(7) = 10 -> high
        assert compute_priority(valid_assessment) == "high"

    def test_priority_medium_validated(self):
        from src.agents.drug_target.tools.stage_logic import compute_priority
        assessment = {
            "validated_track": {
                "existing_drug_evidence": 2, "clinical_trial_activity": 1,
                "safety_profile": 0,
            },
            "exploratory_track": {
                "gwas_genetic_support": 0, "tractability": 0,
                "biological_plausibility": 0, "novelty_opportunity": 0,
            },
        }
        # existing_drug=2>=1, validated_total=3>=3 -> validated_target; combined=3 < 5 -> low
        assert compute_priority(assessment) == "low"

    def test_priority_high_exploratory(self):
        from src.agents.drug_target.tools.stage_logic import compute_priority
        assessment = {
            "validated_track": {
                "existing_drug_evidence": 0, "clinical_trial_activity": 0,
                "safety_profile": 0,
            },
            "exploratory_track": {
                "gwas_genetic_support": 3, "tractability": 2,
                "biological_plausibility": 4, "novelty_opportunity": 3,
            },
        }
        # exploratory total=12 -> high
        assert compute_priority(assessment) == "high"

    def test_priority_medium_exploratory(self):
        from src.agents.drug_target.tools.stage_logic import compute_priority
        assessment = {
            "validated_track": {
                "existing_drug_evidence": 0, "clinical_trial_activity": 0,
                "safety_profile": 0,
            },
            "exploratory_track": {
                "gwas_genetic_support": 2, "tractability": 1,
                "biological_plausibility": 3, "novelty_opportunity": 2,
            },
        }
        # exploratory total=8 -> medium (threshold: >=7 medium, >=12 high)
        assert compute_priority(assessment) == "medium"

    def test_priority_unranked_insufficient(self):
        from src.agents.drug_target.tools.stage_logic import compute_priority
        assessment = {
            "validated_track": {
                "existing_drug_evidence": 0, "clinical_trial_activity": 0,
                "safety_profile": 0,
            },
            "exploratory_track": {
                "gwas_genetic_support": 0, "tractability": 0,
                "biological_plausibility": 0, "novelty_opportunity": 0,
            },
        }
        assert compute_priority(assessment) == "unranked"

    def test_priority_low_novel_candidate(self):
        from src.agents.drug_target.tools.stage_logic import compute_priority
        assessment = {
            "validated_track": {
                "existing_drug_evidence": 0, "clinical_trial_activity": 0,
                "safety_profile": 0,
            },
            "exploratory_track": {
                "gwas_genetic_support": 0, "tractability": 0,
                "biological_plausibility": 3, "novelty_opportunity": 0,
            },
        }
        assert compute_priority(assessment) == "low"

    # --- Dict with score/rationale format ---

    def test_rubric_with_dict_scores(self):
        from src.agents.drug_target.tools.stage_logic import compute_validated_track, compute_exploratory_track
        assessment = {
            "validated_track": {
                "existing_drug_evidence": {"score": 2, "rationale": "Phase 2"},
                "clinical_trial_activity": {"score": 2, "rationale": "Active"},
                "safety_profile": {"score": -1, "rationale": "Moderate risk"},
            },
            "exploratory_track": {
                "gwas_genetic_support": {"score": 1, "rationale": "Suggestive"},
                "tractability": {"score": 2, "rationale": "Clinical precedent"},
                "biological_plausibility": {"score": 3, "rationale": "Strong"},
                "novelty_opportunity": {"score": 1, "rationale": "Moderate"},
            },
        }
        vt = compute_validated_track(assessment)
        et = compute_exploratory_track(assessment)
        assert vt["total"] == 3  # 2+2+(-1)
        assert vt["pass"] is True
        assert et["total"] == 7  # 1+2+3+1
        assert et["pass"] is True


class TestScoreGwasSupport:
    """Unit tests for disease-specific _score_gwas_support scoring."""

    def test_none_returns_0(self):
        from src.agents.drug_target.tools.stage_logic import _score_gwas_support
        assert _score_gwas_support(None) == 0

    def test_empty_dict_returns_0(self):
        from src.agents.drug_target.tools.stage_logic import _score_gwas_support
        assert _score_gwas_support({}) == 0

    def test_gene_associations_only_no_disease_hits_returns_0(self):
        """gene_associations without disease_specific_hits should score 0."""
        from src.agents.drug_target.tools.stage_logic import _score_gwas_support
        gwas = {
            "gene_associations": [
                {"rsId": "rs123", "p_value": 1e-10},
                {"rsId": "rs456", "p_value": 2e-9},
            ],
            # No disease_specific_hits
        }
        assert _score_gwas_support(gwas) == 0

    def test_disease_specific_hits_empty_counts_returns_0(self):
        from src.agents.drug_target.tools.stage_logic import _score_gwas_support
        gwas = {
            "disease_specific_hits": {
                "n_gene_in_trait": 0,
                "n_gene_snps_in_disease": 0,
                "n_proximity_hits": 0,
            }
        }
        assert _score_gwas_support(gwas) == 0

    def test_proximity_hits_only_returns_1(self):
        from src.agents.drug_target.tools.stage_logic import _score_gwas_support
        gwas = {
            "disease_specific_hits": {
                "n_gene_in_trait": 0,
                "n_gene_snps_in_disease": 0,
                "n_proximity_hits": 3,
            }
        }
        assert _score_gwas_support(gwas) == 1

    def test_gene_in_trait_returns_2(self):
        from src.agents.drug_target.tools.stage_logic import _score_gwas_support
        gwas = {
            "disease_specific_hits": {
                "n_gene_in_trait": 2,
                "n_gene_snps_in_disease": 0,
                "n_proximity_hits": 0,
            }
        }
        assert _score_gwas_support(gwas) == 2

    def test_gene_snps_weak_pvalue_returns_2(self):
        """gene_snps_in_disease present but p-value not genome-wide significant."""
        from src.agents.drug_target.tools.stage_logic import _score_gwas_support
        gwas = {
            "disease_specific_hits": {
                "n_gene_in_trait": 0,
                "n_gene_snps_in_disease": 1,
                "n_proximity_hits": 0,
                "gene_snps_in_disease": [
                    {"rsId": "rs789", "pvalue": 1e-5},
                ],
            }
        }
        assert _score_gwas_support(gwas) == 2

    def test_gene_snps_genome_wide_significant_returns_3(self):
        from src.agents.drug_target.tools.stage_logic import _score_gwas_support
        gwas = {
            "disease_specific_hits": {
                "n_gene_in_trait": 0,
                "n_gene_snps_in_disease": 2,
                "n_proximity_hits": 0,
                "gene_snps_in_disease": [
                    {"rsId": "rs111", "pvalue": 3e-9},
                    {"rsId": "rs222", "associations": [{"pvalue": 1e-10}]},
                ],
            }
        }
        assert _score_gwas_support(gwas) == 3

    def test_combined_evidence_highest_tier_wins(self):
        """When multiple signals exist, highest tier wins."""
        from src.agents.drug_target.tools.stage_logic import _score_gwas_support
        gwas = {
            "disease_specific_hits": {
                "n_gene_in_trait": 1,
                "n_gene_snps_in_disease": 1,
                "n_proximity_hits": 5,
                "gene_snps_in_disease": [
                    {"rsId": "rs333", "pvalue": 2e-8},
                ],
            }
        }
        assert _score_gwas_support(gwas) == 3  # gene_snps with p < 5e-8


class TestScoreBiologicalPlausibility:
    """Unit tests for _score_biological_plausibility breadth-weighted scoring (0-5)."""

    def test_empty_evidence_returns_0(self):
        from src.agents.drug_target.tools.stage_logic import _score_biological_plausibility
        assert _score_biological_plausibility([]) == 0

    def test_only_excluded_types_returns_0(self):
        """known_drug and genetic_association should be filtered out."""
        from src.agents.drug_target.tools.stage_logic import _score_biological_plausibility
        evidence = [
            {"datatypeId": "known_drug", "score": 0.9},
            {"datatypeId": "genetic_association", "score": 0.8},
        ]
        assert _score_biological_plausibility(evidence) == 0

    def test_single_type_low_score(self):
        from src.agents.drug_target.tools.stage_logic import _score_biological_plausibility
        evidence = [{"datatypeId": "literature", "score": 0.3}]
        assert _score_biological_plausibility(evidence) == 1

    def test_single_type_high_score_gets_bonus(self):
        from src.agents.drug_target.tools.stage_logic import _score_biological_plausibility
        evidence = [{"datatypeId": "affected_pathway", "score": 0.8}]
        assert _score_biological_plausibility(evidence) == 2  # 1 type + 1 bonus

    def test_two_types_no_bonus(self):
        from src.agents.drug_target.tools.stage_logic import _score_biological_plausibility
        evidence = [
            {"datatypeId": "literature", "score": 0.3},
            {"datatypeId": "animal_model", "score": 0.5},
        ]
        assert _score_biological_plausibility(evidence) == 2  # 2 types, max < 0.7

    def test_two_types_with_bonus(self):
        from src.agents.drug_target.tools.stage_logic import _score_biological_plausibility
        evidence = [
            {"datatypeId": "literature", "score": 0.8},
            {"datatypeId": "somatic_mutation", "score": 0.4},
        ]
        assert _score_biological_plausibility(evidence) == 3  # 2 + 1 bonus

    def test_three_types_no_bonus(self):
        from src.agents.drug_target.tools.stage_logic import _score_biological_plausibility
        evidence = [
            {"datatypeId": "affected_pathway", "score": 0.5},
            {"datatypeId": "literature", "score": 0.3},
            {"datatypeId": "animal_model", "score": 0.2},
        ]
        assert _score_biological_plausibility(evidence) == 3  # min(5, 3+0)

    def test_three_types_with_bonus(self):
        from src.agents.drug_target.tools.stage_logic import _score_biological_plausibility
        evidence = [
            {"datatypeId": "affected_pathway", "score": 0.8},
            {"datatypeId": "literature", "score": 0.5},
            {"datatypeId": "animal_model", "score": 0.3},
        ]
        assert _score_biological_plausibility(evidence) == 4  # min(5, 3+1)

    def test_four_types_no_bonus(self):
        from src.agents.drug_target.tools.stage_logic import _score_biological_plausibility
        evidence = [
            {"datatypeId": "affected_pathway", "score": 0.5},
            {"datatypeId": "literature", "score": 0.3},
            {"datatypeId": "animal_model", "score": 0.4},
            {"datatypeId": "somatic_mutation", "score": 0.2},
        ]
        assert _score_biological_plausibility(evidence) == 4  # min(5, 4+0)

    def test_four_types_with_bonus(self):
        from src.agents.drug_target.tools.stage_logic import _score_biological_plausibility
        evidence = [
            {"datatypeId": "affected_pathway", "score": 0.9},
            {"datatypeId": "literature", "score": 0.5},
            {"datatypeId": "animal_model", "score": 0.4},
            {"datatypeId": "somatic_mutation", "score": 0.3},
        ]
        assert _score_biological_plausibility(evidence) == 5  # min(5, 4+1)

    def test_mixed_qualifying_and_excluded(self):
        """Only qualifying types should contribute to score."""
        from src.agents.drug_target.tools.stage_logic import _score_biological_plausibility
        evidence = [
            {"datatypeId": "known_drug", "score": 0.9},
            {"datatypeId": "genetic_association", "score": 0.8},
            {"datatypeId": "literature", "score": 0.3},
        ]
        assert _score_biological_plausibility(evidence) == 1

    def test_vep_boost_adds_one(self):
        from src.agents.drug_target.tools.stage_logic import _score_biological_plausibility
        evidence = [{"datatypeId": "literature", "score": 0.3}]
        vep = {"executed": True, "impact_summary": {"high_impact": 2}}
        assert _score_biological_plausibility(evidence, vep) == 2  # 1 + 1

    def test_vep_boost_caps_at_5(self):
        from src.agents.drug_target.tools.stage_logic import _score_biological_plausibility
        evidence = [
            {"datatypeId": "affected_pathway", "score": 0.9},
            {"datatypeId": "literature", "score": 0.5},
            {"datatypeId": "animal_model", "score": 0.4},
            {"datatypeId": "somatic_mutation", "score": 0.3},
        ]
        vep = {"executed": True, "impact_summary": {"high_impact": 1}}
        # 4 types + 1 bonus = 5, + VEP = still 5 (capped)
        assert _score_biological_plausibility(evidence, vep) == 5

    def test_vep_no_boost_when_no_high_impact(self):
        from src.agents.drug_target.tools.stage_logic import _score_biological_plausibility
        evidence = [{"datatypeId": "literature", "score": 0.3}]
        vep = {"executed": True, "impact_summary": {"high_impact": 0, "moderate_impact": 5}}
        assert _score_biological_plausibility(evidence, vep) == 1

    def test_vep_boost_on_zero_base(self):
        """VEP boost should work even when no qualifying disease evidence."""
        from src.agents.drug_target.tools.stage_logic import _score_biological_plausibility
        vep = {"executed": True, "impact_summary": {"high_impact": 1}}
        assert _score_biological_plausibility([], vep) == 1  # 0 + 1

    def test_score_boundary_0_7(self):
        """Score of exactly 0.7 should trigger the bonus."""
        from src.agents.drug_target.tools.stage_logic import _score_biological_plausibility
        evidence = [{"datatypeId": "animal_model", "score": 0.7}]
        assert _score_biological_plausibility(evidence) == 2  # 1 type + 1 bonus


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

    def test_disease_fuzzy_resolution_on_no_cells_matched(self, monkeypatch, tmp_path):
        """First attempt fails (disease mismatch) → fuzzy disease resolve → retry succeeds."""
        import src.agents.drug_target.tools.census_lr_validation_tools as mod

        class FailResult:
            returncode = 1
            stdout = ""
            stderr = "RuntimeError: No cells matched the provided obs filter."

        class OkResult:
            returncode = 0
            stdout = (
                "Target vs rest\n"
                "- TGFB1+ & TGFBR2+: target=10.0000% | rest=4.0000% | diff=6.0000% | RR=2.5000 | z=3.1000 | p=1.000e-03\n"
            )
            stderr = ""

        calls = {"n": 0}

        def fake_run(*args, **kwargs):
            calls["n"] += 1
            return FailResult() if calls["n"] == 1 else OkResult()

        monkeypatch.setattr(mod.subprocess, "run", fake_run)

        # Mock list_census_diseases to return candidates with fuzzy match
        # "breast cancer" is a substring of "invasive breast cancer"
        mock_diseases_result = json.dumps({
            "executed": True,
            "diseases": [
                {"label": "normal", "total_cell_count": 50000},
                {"label": "invasive breast cancer", "total_cell_count": 12000},
                {"label": "lung adenocarcinoma", "total_cell_count": 8000},
            ],
        })
        import src.agents.drug_target.tools.stage_domain_tools as domain_mod
        mock_tool = MagicMock()
        mock_tool.invoke = MagicMock(return_value=mock_diseases_result)
        monkeypatch.setattr(domain_mod, "list_census_diseases", mock_tool)

        raw = mod.run_compare_census_lr_pair.invoke({
            "data_dir": str(tmp_path),
            "disease": "breast cancer",
            "gene_a": "TGFB1",
            "gene_b": "TGFBR2",
            "target_cell_type": "Invasive tumor",
        })
        result = json.loads(raw)
        assert result["executed"] is True
        assert result["disease_resolved"] == "invasive breast cancer"
        assert result["disease_resolution_mode"] == "fuzzy"
        assert result["disease"] == "invasive breast cancer"

    def test_disease_resolution_exact_match(self, monkeypatch, tmp_path):
        """Disease differs only by case → exact match resolution."""
        import src.agents.drug_target.tools.census_lr_validation_tools as mod

        class FailResult:
            returncode = 1
            stdout = ""
            stderr = "RuntimeError: No cells matched the provided obs filter."

        class OkResult:
            returncode = 0
            stdout = (
                "Target vs rest\n"
                "- TGFB1+ & TGFBR2+: target=10.0000% | rest=4.0000% | diff=6.0000% | RR=2.5000 | z=3.1000 | p=1.000e-03\n"
            )
            stderr = ""

        calls = {"n": 0}

        def fake_run(*args, **kwargs):
            calls["n"] += 1
            return FailResult() if calls["n"] == 1 else OkResult()

        monkeypatch.setattr(mod.subprocess, "run", fake_run)

        mock_diseases_result = json.dumps({
            "executed": True,
            "diseases": [
                {"label": "Breast Carcinoma", "total_cell_count": 12000},
            ],
        })
        import src.agents.drug_target.tools.stage_domain_tools as domain_mod
        mock_tool = MagicMock()
        mock_tool.invoke = MagicMock(return_value=mock_diseases_result)
        monkeypatch.setattr(domain_mod, "list_census_diseases", mock_tool)

        raw = mod.run_compare_census_lr_pair.invoke({
            "data_dir": str(tmp_path),
            "disease": "breast carcinoma",
            "gene_a": "TGFB1",
            "gene_b": "TGFBR2",
            "target_cell_type": "Invasive tumor",
        })
        result = json.loads(raw)
        assert result["executed"] is True
        assert result["disease_resolved"] == "Breast Carcinoma"
        assert result["disease_resolution_mode"] == "exact"

    def test_disease_resolution_fallback_to_celltype(self, monkeypatch, tmp_path):
        """Disease resolution fails → falls back to cell type resolution (existing behavior)."""
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
                "- TGFB1+ & TGFBR2+: target=10.0000% | rest=4.0000% | diff=6.0000% | RR=2.5000 | z=3.1000 | p=1.000e-03\n"
            )
            stderr = ""

        calls = {"n": 0}

        def fake_run(*args, **kwargs):
            calls["n"] += 1
            return FailResult() if calls["n"] == 1 else OkResult()

        monkeypatch.setattr(mod.subprocess, "run", fake_run)

        # Disease resolution returns no match → should skip disease retry
        mock_diseases_result = json.dumps({
            "executed": True,
            "diseases": [
                {"label": "normal", "total_cell_count": 50000},
                {"label": "lung adenocarcinoma", "total_cell_count": 8000},
            ],
        })
        import src.agents.drug_target.tools.stage_domain_tools as domain_mod
        mock_tool = MagicMock()
        mock_tool.invoke = MagicMock(return_value=mock_diseases_result)
        monkeypatch.setattr(domain_mod, "list_census_diseases", mock_tool)

        raw = mod.run_compare_census_lr_pair.invoke({
            "data_dir": str(tmp_path),
            "disease": "breast cancer",
            "gene_a": "TGFB1",
            "gene_b": "TGFBR2",
            "target_cell_type": "Invasive tumor",
        })
        result = json.loads(raw)
        assert result["executed"] is True
        assert result["disease_resolved"] is None  # no disease resolution
        assert result["retried"] is True  # cell type resolution happened
        assert result["resolved_cell_type"] == "Prolif Invasive Tumor"

    def test_disease_resolution_census_unavailable(self, monkeypatch, tmp_path):
        """list_census_diseases raises → graceful skip, falls back to cell type logic."""
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
                "- TGFB1+ & TGFBR2+: target=10.0000% | rest=4.0000% | diff=6.0000% | RR=2.5000 | z=3.1000 | p=1.000e-03\n"
            )
            stderr = ""

        calls = {"n": 0}

        def fake_run(*args, **kwargs):
            calls["n"] += 1
            return FailResult() if calls["n"] == 1 else OkResult()

        monkeypatch.setattr(mod.subprocess, "run", fake_run)

        # Make list_census_diseases raise an exception
        import src.agents.drug_target.tools.stage_domain_tools as domain_mod
        mock_tool = MagicMock()
        mock_tool.invoke = MagicMock(side_effect=RuntimeError("Census unavailable"))
        monkeypatch.setattr(domain_mod, "list_census_diseases", mock_tool)

        raw = mod.run_compare_census_lr_pair.invoke({
            "data_dir": str(tmp_path),
            "disease": "breast cancer",
            "gene_a": "TGFB1",
            "gene_b": "TGFBR2",
            "target_cell_type": "Invasive tumor",
        })
        result = json.loads(raw)
        assert result["executed"] is True
        assert result["disease_resolved"] is None  # disease resolution skipped
        assert result["retried"] is True  # fell back to cell type resolution
        assert result["resolved_cell_type"] == "Prolif Invasive Tumor"

    def test_save_target_assessment_roundtrip(self, tmp_path):
        from src.agents.drug_target.tools.assessment_output import save_target_assessment

        (tmp_path / "lr_candidates.json").write_text(json.dumps({
            "pairs": [
                {"ligand": "TGFB1", "receptor": "TGFBR2"},
            ]
        }))
        raw = save_target_assessment.invoke({
            "data_dir": str(tmp_path),
            "project_meta": json.dumps({"disease_focus": "breast cancer", "total_input_pairs": 1}),
            "druggability_matrix": json.dumps([
                {
                    "ligand": "TGFB1",
                    "receptor": "TGFBR2",
                    "open_targets_score": 0.9,
                    "validated_track": {
                        "existing_drug_evidence": 2,
                        "clinical_trial_activity": 2,
                        "safety_profile": 0,
                    },
                    "exploratory_track": {
                        "gwas_genetic_support": 2,
                        "tractability": 2,
                        "biological_plausibility": 3,
                        "novelty_opportunity": 1,
                    },
                }
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
        assert payload["druggability_matrix"][0]["is_novel"] is False
        assert payload["druggability_matrix"][0]["combined_total"] == 12

    def test_save_target_assessment_rejects_pair_set_mismatch(self, tmp_path):
        from src.agents.drug_target.tools.assessment_output import save_target_assessment

        (tmp_path / "lr_candidates.json").write_text(json.dumps({
            "pairs": [
                {"ligand": "TGFB1", "receptor": "TGFBR2"},
            ]
        }))
        raw = save_target_assessment.invoke({
            "data_dir": str(tmp_path),
            "project_meta": json.dumps({"disease_focus": "breast cancer", "total_input_pairs": 1}),
            "druggability_matrix": json.dumps([
                {
                    "ligand": "TGFB1",
                    "receptor": "FLT1",
                    "open_targets_score": 0.9,
                    "validated_track": {
                        "existing_drug_evidence": 2,
                        "clinical_trial_activity": 2,
                        "safety_profile": 0,
                    },
                    "exploratory_track": {
                        "gwas_genetic_support": 2,
                        "tractability": 2,
                        "biological_plausibility": 3,
                        "novelty_opportunity": 1,
                    },
                }
            ]),
            "featured_candidates_deep_dive": json.dumps([]),
        })
        result = json.loads(raw)
        assert result["saved"] is False
        assert "pair-set" in result["errors"][0]
        assert not (tmp_path / "target_assessment.json").exists()


# =========================================================================
# Stage 1 Confidence Filtering Tests
# =========================================================================

class TestStage1Confidence:
    """Tests for compute_stage1_confidence and filter_by_stage1_confidence."""

    def test_compute_stage1_confidence_full_evidence(self):
        """Full evidence (strong PPI + significant census + shared pathway + expression) → high confidence."""
        from src.agents.drug_target.tools.stage_logic import compute_stage1_confidence

        evidence = {
            "ligand": "TGFB1",
            "receptor": "TGFBR2",
            "string_ppi": {"max_combined_score": 0.999},  # 0-1 scale from STRING API
            "census_validation": {
                "coexpression": {"p_value": 0.001, "risk_ratio": 3.0},  # 1.0 * 1.0
                "target_vs_rest": {
                    "gene_a": {"target_pct": 5.2},
                    "gene_b": {"target_pct": 3.1},
                    "coexpression": {"p_value": 0.001, "risk_ratio": 3.0},
                },
            },
            "kegg_pathways": {
                "ligand_pathways": [{"pathway_id": "hsa04350"}, {"pathway_id": "hsa04060"}],
                "receptor_pathways": [{"pathway_id": "hsa04350"}, {"pathway_id": "hsa04010"}],
            },  # shared hsa04350 → 1.0
            "reactome_pathways": {
                "ligand_pathways": [{"reactome_id": "R-HSA-2173789"}],
                "receptor_pathways": [{"reactome_id": "R-HSA-2173789"}],
            },
            "cellxgene": {"available_genes": ["TGFB1", "TGFBR2"]},  # fallback (not used)
        }
        result = compute_stage1_confidence(evidence)
        assert result["confidence"] >= 0.99  # 0.999 string → rounds to ~1.0
        assert result["string_score"] >= 0.99  # 0.999 from STRING API (0-1 scale)
        assert result["census_score"] == 1.0
        assert result["pathway_score"] == 1.0
        assert result["expression_score"] == 1.0

    def test_compute_stage1_confidence_missing_signals(self):
        """Partial evidence (weak STRING, no census, no shared pathway, 1 gene) → low confidence.

        No target_vs_rest in census_validation → fallback to available_genes.
        """
        from src.agents.drug_target.tools.stage_logic import compute_stage1_confidence

        evidence = {
            "ligand": "GDF15",
            "receptor": "GFRAL",
            "string_ppi": {"max_combined_score": 0.222},  # 0-1 scale from STRING API
            "census_validation": {
                "coexpression": {"p_value": 0.1, "risk_ratio": 1.5},  # p>=0.05 → 0.0
            },
            "kegg_pathways": {
                "ligand_pathways": [{"pathway_id": "hsa04060"}],
                "receptor_pathways": [{"pathway_id": "hsa04010"}],
            },  # no overlap → 0.0
            "reactome_pathways": {
                "ligand_pathways": [],
                "receptor_pathways": [],
            },
            "cellxgene": {"available_genes": ["GDF15"]},  # fallback: 1/2 = 0.5
        }
        result = compute_stage1_confidence(evidence)
        # 0.35 * 0.222 + 0.30 * 0.0 + 0.20 * 0.0 + 0.15 * 0.5 ≈ 0.153
        assert result["confidence"] < 0.2
        assert result["census_score"] == 0.0
        assert result["pathway_score"] == 0.0
        assert result["expression_score"] == 0.5

    def test_compute_stage1_confidence_shared_kegg_pathway(self):
        """KEGG shared pathway only → pathway_score = 1.0."""
        from src.agents.drug_target.tools.stage_logic import compute_stage1_confidence

        evidence = {
            "ligand": "TNFSF10",
            "receptor": "TNFRSF10C",
            "string_ppi": {"max_combined_score": 0},
            "kegg_pathways": {
                "ligand_pathways": [{"pathway_id": "hsa04060"}, {"pathway_id": "hsa04061"}],
                "receptor_pathways": [{"pathway_id": "hsa04060"}, {"pathway_id": "hsa04210"}],
            },  # shared hsa04060 → 1.0
            "reactome_pathways": {
                "ligand_pathways": [],
                "receptor_pathways": [],
            },
            "cellxgene": {"available_genes": []},
        }
        result = compute_stage1_confidence(evidence)
        assert result["pathway_score"] == 1.0

    def test_compute_stage1_confidence_no_shared_pathway(self):
        """Both have pathways but no overlap → pathway_score = 0.0."""
        from src.agents.drug_target.tools.stage_logic import compute_stage1_confidence

        evidence = {
            "ligand": "GDF15",
            "receptor": "GFRAL",
            "string_ppi": {"max_combined_score": 0},
            "kegg_pathways": {
                "ligand_pathways": [{"pathway_id": "hsa04060"}],
                "receptor_pathways": [{"pathway_id": "hsa04010"}],
            },
            "reactome_pathways": {
                "ligand_pathways": [{"reactome_id": "R-HSA-111"}],
                "receptor_pathways": [{"reactome_id": "R-HSA-222"}],
            },  # no overlap in either DB → 0.0
            "cellxgene": {"available_genes": []},
        }
        result = compute_stage1_confidence(evidence)
        assert result["pathway_score"] == 0.0

    def test_compute_stage1_confidence_old_format_fallback(self):
        """Old flat 'pathways' list format → count-based fallback."""
        from src.agents.drug_target.tools.stage_logic import compute_stage1_confidence

        evidence = {
            "ligand": "TGFB1",
            "receptor": "TGFBR2",
            "string_ppi": {"max_combined_score": 0},
            "kegg_pathways": {"pathways": ["p1", "p2"]},
            "reactome_pathways": {"pathways": ["r1", "r2"]},  # 4/4 = 1.0
            "cellxgene": {"available_genes": []},
        }
        result = compute_stage1_confidence(evidence)
        assert result["pathway_score"] == 1.0

    def test_compute_stage1_confidence_nested_census(self):
        """Census data under target_vs_rest.coexpression is also handled."""
        from src.agents.drug_target.tools.stage_logic import compute_stage1_confidence

        evidence = {
            "ligand": "VEGFA",
            "receptor": "FLT1",
            "string_ppi": {"max_combined_score": 450},
            "census_validation": {
                "target_vs_rest": {
                    "coexpression": {"p_value": 0.01, "risk_ratio": 2.0},
                },
            },
            "kegg_pathways": {
                "ligand_pathways": [{"pathway_id": "hsa04370"}],
                "receptor_pathways": [{"pathway_id": "hsa04370"}],
            },
            "reactome_pathways": {
                "ligand_pathways": [],
                "receptor_pathways": [],
            },
            "cellxgene": {"available_genes": ["VEGFA", "FLT1"]},
        }
        result = compute_stage1_confidence(evidence)
        assert result["census_score"] > 0  # p<0.05 and rr>0

    def test_compute_stage1_confidence_empty_evidence(self):
        """Completely empty evidence → zero confidence."""
        from src.agents.drug_target.tools.stage_logic import compute_stage1_confidence

        result = compute_stage1_confidence({})
        assert result["confidence"] == 0.0

    def test_expression_score_from_census_target_pct(self):
        """Both genes have target_pct > 0 → expression_score = 1.0."""
        from src.agents.drug_target.tools.stage_logic import compute_stage1_confidence

        evidence = {
            "ligand": "TGFB1",
            "receptor": "TGFBR2",
            "string_ppi": {"max_combined_score": 0},
            "census_validation": {
                "target_vs_rest": {
                    "gene_a": {"target_pct": 5.2},
                    "gene_b": {"target_pct": 3.1},
                },
            },
            "kegg_pathways": {"ligand_pathways": [], "receptor_pathways": []},
            "reactome_pathways": {"ligand_pathways": [], "receptor_pathways": []},
        }
        result = compute_stage1_confidence(evidence)
        assert result["expression_score"] == 1.0

    def test_expression_score_one_gene_expressed(self):
        """Only one gene has target_pct > 0 → expression_score = 0.5."""
        from src.agents.drug_target.tools.stage_logic import compute_stage1_confidence

        evidence = {
            "ligand": "GDF15",
            "receptor": "GFRAL",
            "string_ppi": {"max_combined_score": 0},
            "census_validation": {
                "target_vs_rest": {
                    "gene_a": {"target_pct": 4.0},
                    "gene_b": {"target_pct": 0},
                },
            },
            "kegg_pathways": {"ligand_pathways": [], "receptor_pathways": []},
            "reactome_pathways": {"ligand_pathways": [], "receptor_pathways": []},
        }
        result = compute_stage1_confidence(evidence)
        assert result["expression_score"] == 0.5

    def test_expression_score_fallback_old_format(self):
        """No target_vs_rest in census → fallback to available_genes."""
        from src.agents.drug_target.tools.stage_logic import compute_stage1_confidence

        evidence = {
            "ligand": "VEGFA",
            "receptor": "FLT1",
            "string_ppi": {"max_combined_score": 0},
            "census_validation": {
                "coexpression": {"p_value": 0.5, "risk_ratio": 0.5},
            },
            "kegg_pathways": {"ligand_pathways": [], "receptor_pathways": []},
            "reactome_pathways": {"ligand_pathways": [], "receptor_pathways": []},
            "cellxgene": {"available_genes": ["VEGFA", "FLT1"]},
        }
        result = compute_stage1_confidence(evidence)
        assert result["expression_score"] == 1.0

    def test_filter_by_stage1_confidence_basic(self):
        """All pairs pass; low-confidence ones are tagged."""
        from src.agents.drug_target.tools.stage_logic import filter_by_stage1_confidence

        pairs = [
            {"name": f"pair_{i}", "stage1_confidence": {"confidence": c}}
            for i, c in enumerate([0.8, 0.7, 0.6, 0.5, 0.45, 0.3, 0.2, 0.1, 0.05, 0.0])
        ]
        passed, filtered = filter_by_stage1_confidence(pairs, threshold=0.4, min_remaining=3)
        assert len(passed) == 10  # all pairs pass
        assert len(filtered) == 0
        # Low-confidence pairs tagged
        low = [p for p in passed if p.get("stage1_low_confidence")]
        assert len(low) == 5  # 0.3, 0.2, 0.1, 0.05, 0.0
        high = [p for p in passed if not p.get("stage1_low_confidence")]
        assert len(high) == 5  # 0.8, 0.7, 0.6, 0.5, 0.45

    def test_filter_by_stage1_confidence_graduated_relaxation(self):
        """All pairs pass; below-threshold pairs are tagged."""
        from src.agents.drug_target.tools.stage_logic import filter_by_stage1_confidence

        pairs = [
            {"name": f"pair_{i}", "stage1_confidence": {"confidence": c}}
            for i, c in enumerate([0.5, 0.45, 0.35, 0.30, 0.25, 0.22, 0.15, 0.10])
        ]
        passed, filtered = filter_by_stage1_confidence(pairs, threshold=0.4, min_remaining=5)
        assert len(passed) == 8  # all pairs pass
        assert len(filtered) == 0
        low = [p for p in passed if p.get("stage1_low_confidence")]
        assert len(low) == 6  # 0.35, 0.30, 0.25, 0.22, 0.15, 0.10

    def test_filter_by_stage1_confidence_no_filtering_fallback(self):
        """All low-confidence pairs still pass with tag."""
        from src.agents.drug_target.tools.stage_logic import filter_by_stage1_confidence

        pairs = [
            {"name": f"pair_{i}", "stage1_confidence": {"confidence": c}}
            for i, c in enumerate([0.15, 0.10, 0.05])
        ]
        passed, filtered = filter_by_stage1_confidence(pairs, threshold=0.4, min_remaining=5)
        assert len(passed) == 3
        assert len(filtered) == 0
        assert all(p.get("stage1_low_confidence") for p in passed)


# =========================================================================
# 6. TestIntegration — Agent creation & tool wiring
# =========================================================================

class TestIntegration:
    """Agent creation, config defaults, and integration wiring."""

    def test_drug_target_config_defaults(self):
        from src.agents.drug_target.agent import DrugTargetConfig
        config = DrugTargetConfig()
        assert config.provider == "openrouter"
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

        # create_drug_target_agent returns (agent, backend_or_None)
        from deepagents.backends import FilesystemBackend
        agent, backend = result
        # Agent is now wrapped with .with_config(recursion_limit=2000)
        assert agent is mock_agent.with_config.return_value
        assert isinstance(backend, FilesystemBackend)
        mock_create_llm.assert_called_once_with(provider="openrouter")
        mock_create_deep_agent.assert_called_once()

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

        # evidence directory is created during agent initialization
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
        # create_drug_target_agent returns (agent, backend_or_None)
        with patch(
            "src.agents.drug_target.agent.create_drug_target_agent",
            return_value=(mock_agent, None),
        ), patch(
            "src.agents.drug_target.integration.finalize_stage1_workspace",
            return_value={"success": True, "post_validation": {"errors": []}},
        ), patch(
            "src.agents.drug_target.integration.validate_target_assessment_file",
            return_value={"valid": True, "errors": []},
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
    def test_create_agent_passes_subagents_with_4_entries(
        self, mock_create_llm, mock_create_deep_agent, tmp_path
    ):
        from src.agents.drug_target.agent import create_drug_target_agent, DrugTargetConfig

        mock_create_llm.return_value = MagicMock()
        mock_create_deep_agent.return_value = MagicMock()

        config = DrugTargetConfig(data_dir=str(tmp_path))
        create_drug_target_agent(config)

        call_kwargs = mock_create_deep_agent.call_args
        subagents = call_kwargs.kwargs.get("subagents") or call_kwargs[1].get("subagents")
        assert len(subagents) == 4

    def test_shared_skills_middleware_filters_allowed_skill_names(self, tmp_path):
        import asyncio
        from src.agents.shared.skills_middleware import SkillsMiddleware

        skills_dir = tmp_path / "skills"
        for name in ["opentargets-database", "gwas-database", "chembl-database", "string-database"]:
            skill_dir = skills_dir / name
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: test\n---\n# {name}\n",
                encoding="utf-8",
            )

        middleware = SkillsMiddleware(
            skills_dir=skills_dir,
            allowed_skill_names=("opentargets-database", "gwas-database", "chembl-database"),
        )

        asyncio.run(middleware.abefore_agent(state={}, runtime=None))

        assert middleware._skills_cache is not None
        assert [s["name"] for s in middleware._skills_cache] == [
            "opentargets-database",
            "gwas-database",
            "chembl-database",
        ]

    @patch("src.agents.drug_target.agent.create_deep_agent")
    @patch("src.agents.drug_target.agent.create_llm")
    def test_create_drug_target_agent_attaches_skills_to_evidence_assessor(
        self, mock_create_llm, mock_create_deep_agent, tmp_path
    ):
        from src.agents.drug_target.agent import create_drug_target_agent, DrugTargetConfig

        mock_create_llm.return_value = MagicMock()
        mock_create_deep_agent.return_value = MagicMock()

        config = DrugTargetConfig(data_dir=str(tmp_path))
        create_drug_target_agent(config)

        call_kwargs = mock_create_deep_agent.call_args.kwargs
        # Orchestrator middleware: WriteFileArgGuard + ReadFileBlock + SubagentErrorGuard
        middleware = call_kwargs.get("middleware", [])
        assert len(middleware) == 3
        mw_names = [type(m).__name__ for m in middleware]
        assert "WriteFileArgGuardMiddleware" in mw_names
        assert "ReadFileBlockMiddleware" in mw_names
        assert "SubagentErrorGuardMiddleware" in mw_names
        # evidence_assessor subagent has skills attached
        subagents = call_kwargs.get("subagents", [])
        ea = next(s for s in subagents if s["name"] == "evidence_assessor")
        assert "skills" in ea
        # report_writer has NO skills
        rw = next(s for s in subagents if s["name"] == "report_writer")
        assert "skills" not in rw

    @patch("src.agents.drug_target.agent.create_deep_agent")
    @patch("src.agents.drug_target.agent.create_llm")
    def test_create_drug_target_agent_can_disable_progressive_disclosure(
        self, mock_create_llm, mock_create_deep_agent, tmp_path
    ):
        from src.agents.drug_target.agent import create_drug_target_agent, DrugTargetConfig
        from src.agents.shared.skill_load_harness import SkillLoadHarness

        mock_create_llm.return_value = MagicMock()
        mock_create_deep_agent.return_value = MagicMock()

        config = DrugTargetConfig(
            data_dir=str(tmp_path),
            enable_progressive_disclosure=False,
        )
        create_drug_target_agent(config)

        call_kwargs = mock_create_deep_agent.call_args.kwargs
        # Orchestrator still has all 3 guard middlewares
        middleware = call_kwargs.get("middleware", [])
        assert len(middleware) == 3
        mw_names = [type(m).__name__ for m in middleware]
        assert "WriteFileArgGuardMiddleware" in mw_names
        assert "ReadFileBlockMiddleware" in mw_names
        assert "SubagentErrorGuardMiddleware" in mw_names
        # No skills on any subagent
        subagents = call_kwargs.get("subagents", [])
        for s in subagents:
            assert "skills" not in s
            mw = s.get("middleware", [])
            assert not any(isinstance(m, SkillLoadHarness) for m in mw)


# =========================================================================
# 9. TestCensusDiseaseTool — list_census_diseases + disease_matched flag
# =========================================================================

class TestCensusDiseaseTool:
    """Tests for list_census_diseases tool and disease_matched flag."""

    def test_list_census_diseases_returns_disease_list(self):
        """Mock summary_cell_counts returns disease list."""
        import pandas as pd
        from src.agents.drug_target.tools.stage_domain_tools import list_census_diseases

        mock_df = pd.DataFrame({
            "organism": ["Homo sapiens", "Homo sapiens", "Homo sapiens"],
            "category": ["disease", "disease", "cell_type"],
            "label": ["normal", "breast carcinoma", "fibroblast"],
            "total_cell_count": [1000000, 50000, 200000],
        })

        mock_table = MagicMock()
        mock_table.read.return_value.concat.return_value.to_pandas.return_value = mock_df

        mock_census = MagicMock()
        mock_census.__getitem__ = lambda self, key: {
            "census_info": {"summary_cell_counts": mock_table},
        }[key]

        with patch("cellxgene_census.open_soma") as mock_open:
            mock_open.return_value.__enter__ = lambda s: mock_census
            mock_open.return_value.__exit__ = MagicMock(return_value=False)
            raw = list_census_diseases.invoke({"organism": "homo_sapiens"})

        result = json.loads(raw)
        assert result["executed"] is True
        assert len(result["diseases"]) == 2
        labels = [d["label"] for d in result["diseases"]]
        assert "normal" in labels
        assert "breast carcinoma" in labels

    def test_list_census_diseases_sorted_descending(self):
        """Disease list is sorted by total_cell_count descending."""
        import pandas as pd
        from src.agents.drug_target.tools.stage_domain_tools import list_census_diseases

        mock_df = pd.DataFrame({
            "organism": ["Homo sapiens", "Homo sapiens", "Homo sapiens"],
            "category": ["disease", "disease", "disease"],
            "label": ["small_disease", "big_disease", "medium_disease"],
            "total_cell_count": [100, 100000, 5000],
        })

        mock_table = MagicMock()
        mock_table.read.return_value.concat.return_value.to_pandas.return_value = mock_df

        mock_census = MagicMock()
        mock_census.__getitem__ = lambda self, key: {
            "census_info": {"summary_cell_counts": mock_table},
        }[key]

        with patch("cellxgene_census.open_soma") as mock_open:
            mock_open.return_value.__enter__ = lambda s: mock_census
            mock_open.return_value.__exit__ = MagicMock(return_value=False)
            raw = list_census_diseases.invoke({"organism": "homo_sapiens"})

        result = json.loads(raw)
        assert result["executed"] is True
        counts = [d["total_cell_count"] for d in result["diseases"]]
        assert counts == sorted(counts, reverse=True)
        assert result["diseases"][0]["label"] == "big_disease"

    def test_list_census_diseases_cellxgene_unavailable(self):
        """Graceful error when cellxgene_census not installed."""
        from src.agents.drug_target.tools.stage_domain_tools import list_census_diseases

        original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

        def guarded_import(name, *args, **kwargs):
            if name == "cellxgene_census":
                raise ImportError("no module named 'cellxgene_census'")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=guarded_import):
            raw = list_census_diseases.invoke({"organism": "homo_sapiens"})

        result = json.loads(raw)
        assert result["executed"] is False
        assert any("unavailable" in e for e in result["errors"])

    def test_disease_matched_true_when_rows_found(self):
        """disease_matched is True when disease filter returns rows."""
        import pandas as pd
        from src.agents.drug_target.tools.stage_domain_tools import (
            query_cellxgene_lr_context,
        )

        mock_obs = pd.DataFrame({"cell_type": ["fibroblast"] * 10})
        mock_var = pd.DataFrame({"feature_name": ["TGFB1", "TGFBR2"]})

        with patch("cellxgene_census.open_soma") as mock_open, \
             patch("cellxgene_census.get_obs", return_value=mock_obs), \
             patch("cellxgene_census.get_var", return_value=mock_var):
            mock_open.return_value.__enter__ = MagicMock()
            mock_open.return_value.__exit__ = MagicMock(return_value=False)
            raw = query_cellxgene_lr_context.invoke({
                "ligand": "TGFB1",
                "receptor": "TGFBR2",
                "disease": "breast carcinoma",
            })

        result = json.loads(raw)
        assert result["executed"] is True
        assert result["disease_matched"] is True

    def test_disease_matched_false_on_fallback(self):
        """disease_matched is False when disease filter returns 0 rows (fallback)."""
        import pandas as pd
        from src.agents.drug_target.tools.stage_domain_tools import (
            query_cellxgene_lr_context,
        )

        empty_obs = pd.DataFrame({"cell_type": []})
        fallback_obs = pd.DataFrame({"cell_type": ["fibroblast"] * 5})
        mock_var = pd.DataFrame({"feature_name": ["TGFB1"]})

        with patch("cellxgene_census.open_soma") as mock_open, \
             patch("cellxgene_census.get_obs", side_effect=[empty_obs, fallback_obs]), \
             patch("cellxgene_census.get_var", return_value=mock_var):
            mock_open.return_value.__enter__ = MagicMock()
            mock_open.return_value.__exit__ = MagicMock(return_value=False)
            raw = query_cellxgene_lr_context.invoke({
                "ligand": "TGFB1",
                "receptor": "TGFBR2",
                "disease": "nonexistent disease xyz",
            })

        result = json.loads(raw)
        assert result["executed"] is True
        assert result["disease_matched"] is False
        assert any("not matched" in e for e in result["errors"])
        assert any("list_census_diseases" in e for e in result["errors"])

    def test_list_census_diseases_registered_in_evidence_assessor(self):
        """list_census_diseases is in evidence_assessor tools."""
        from src.agents.drug_target.subagents.configs import SUBAGENT_CONFIGS
        tools = SUBAGENT_CONFIGS["evidence_assessor"]["tools"]
        names = {t.name for t in tools}
        assert "list_census_diseases" in names

    def test_evidence_assessor_prompt_mentions_disease_matching(self):
        """Prompt contains disease matching keywords."""
        from src.agents.drug_target.subagents.prompts import EVIDENCE_ASSESSOR_PROMPT
        assert "list_census_diseases" in EVIDENCE_ASSESSOR_PROMPT
        assert "census_disease" in EVIDENCE_ASSESSOR_PROMPT
        assert "disease_matched" in EVIDENCE_ASSESSOR_PROMPT

    def test_evidence_assessor_prompt_mentions_selected_skill_reads(self):
        """Prompt contains stage-specific progressive disclosure guidance."""
        from src.agents.drug_target.subagents.prompts import EVIDENCE_ASSESSOR_PROMPT, DEEP_DIVER_PROMPT

        assert "read_skill_file" in EVIDENCE_ASSESSOR_PROMPT
        assert "query_stage2_gene_panel" in EVIDENCE_ASSESSOR_PROMPT
        assert "opentargets-database" in EVIDENCE_ASSESSOR_PROMPT
        assert "gwas-database" in EVIDENCE_ASSESSOR_PROMPT
        # chembl-database moved to deep_diver prompt
        assert "chembl-database" not in EVIDENCE_ASSESSOR_PROMPT
        assert "chembl-database" in DEEP_DIVER_PROMPT
        assert "cellxgene-census" not in EVIDENCE_ASSESSOR_PROMPT

    def test_read_skill_file_reads_project_relative_skill_doc(self, tmp_path):
        from src.agents.drug_target.tools.skill_reader import read_skill_file
        import src.agents.drug_target.tools.skill_reader as mod

        skill_file = tmp_path / "skills" / "opentargets-database" / "SKILL.md"
        skill_file.parent.mkdir(parents=True)
        skill_file.write_text("# OpenTargets\nLine 2\n", encoding="utf-8")

        with patch.object(mod, "_find_project_root", return_value=tmp_path):
            raw = read_skill_file.invoke({"skill_path": "skills/opentargets-database/SKILL.md"})

        assert "OpenTargets" in raw


# =========================================================================
# 10. TestNovelCandidates — Dual-track Featured vs Novel selection
# =========================================================================

class TestNovelCandidates:
    """Novel candidate selection, tier assignment, and slot allocation."""

    @staticmethod
    def _row(ligand, receptor, vt_scores, et_scores):
        return {
            "ligand": ligand,
            "receptor": receptor,
            "open_targets_score": 0.5,
            "validated_track": dict(zip(
                ("existing_drug_evidence", "clinical_trial_activity", "safety_profile"),
                vt_scores,
            )),
            "exploratory_track": dict(zip(
                ("gwas_genetic_support", "tractability", "biological_plausibility", "novelty_opportunity"),
                et_scores,
            )),
        }

    def test_rank_novel_candidates_by_exploratory_total(self):
        """Novel candidates (drug_evidence=0) are marked is_novel and sorted by exploratory_total."""
        from src.agents.drug_target.tools.stage_logic import rank_featured_candidates

        matrix = [
            # Featured pool (drug_evidence >= 1)
            self._row("A", "B", (2, 2, 0), (1, 1, 2, 1)),   # featured
            # Novel pool (drug_evidence == 0), different exploratory totals
            self._row("C", "D", (0, 0, 0), (2, 1, 2, 1)),   # exploratory_total=6
            self._row("E", "F", (0, 0, 0), (1, 2, 3, 2)),   # exploratory_total=8
            self._row("G", "H", (0, 0, 0), (0, 0, 3, 1)),   # exploratory_total=4, novel (bio>=3)
        ]

        ranked = rank_featured_candidates(matrix, min_featured=1, max_featured=3, min_novel=1, max_novel=3)
        novel = [r for r in ranked if r.get("is_novel")]

        assert len(novel) >= 1
        # Novel sorted by exploratory_total descending
        assert novel[0]["exploratory_total"] >= novel[-1]["exploratory_total"]
        # Highest exploratory_total novel is E (8)
        assert novel[0]["ligand"] == "E"
        # All novel have is_featured=False
        assert all(not r["is_featured"] for r in novel)

    def test_novel_tier_assignment(self):
        """Novel Tier 1 (GWAS/tractability) vs Tier 2 (ST-only)."""
        from src.agents.drug_target.tools.stage_logic import rank_featured_candidates

        matrix = [
            # Novel with GWAS support → Tier 1
            self._row("A", "B", (0, 0, 0), (2, 0, 3, 1)),   # gwas=2, bio=3 → tier 1
            # Novel with tractability → Tier 1
            self._row("C", "D", (0, 0, 0), (0, 2, 3, 1)),   # tract=2, bio=3 → tier 1
            # Novel without GWAS or tractability → Tier 2
            self._row("E", "F", (0, 0, 0), (0, 0, 3, 2)),   # gwas=0, tract=0, bio=3 → tier 2
        ]

        ranked = rank_featured_candidates(matrix, min_featured=0, max_featured=0, min_novel=1, max_novel=3)
        novel = [r for r in ranked if r.get("is_novel")]

        tier_map = {r["ligand"]: r.get("novel_tier") for r in novel}
        assert tier_map["A"] == 1  # GWAS support
        assert tier_map["C"] == 1  # tractability support
        assert tier_map["E"] == 2  # ST-only

    def test_featured_and_novel_coexist(self):
        """Both featured (drug evidence) and novel (no drug evidence) tracks populated."""
        from src.agents.drug_target.tools.stage_logic import rank_featured_candidates

        matrix = [
            # Featured (drug_evidence >= 1)
            self._row("A", "B", (3, 2, 0), (2, 2, 3, 1)),   # validated
            self._row("C", "D", (1, 1, 0), (1, 1, 2, 1)),   # validated
            # Novel (drug_evidence == 0)
            self._row("E", "F", (0, 0, 0), (2, 1, 3, 2)),   # exploratory
            self._row("G", "H", (0, 0, 0), (0, 0, 3, 2)),   # novel_candidate (bio>=3)
        ]

        ranked = rank_featured_candidates(matrix, min_featured=2, max_featured=3, min_novel=1, max_novel=2)
        featured = [r for r in ranked if r["is_featured"]]
        novel = [r for r in ranked if r.get("is_novel")]

        assert len(featured) >= 2
        assert len(novel) >= 1
        # No overlap between tracks
        featured_ligands = {r["ligand"] for r in featured}
        novel_ligands = {r["ligand"] for r in novel}
        assert featured_ligands.isdisjoint(novel_ligands)
        # All featured have drug_evidence >= 1
        for r in featured:
            ede = r["validated_track"]["existing_drug_evidence"]
            score = ede["score"] if isinstance(ede, dict) else ede
            assert score >= 1

    def test_novel_slot_allocation_dynamic(self):
        """When fewer featured candidates, more novel slots are allocated (up to max_total)."""
        from src.agents.drug_target.tools.stage_logic import rank_featured_candidates

        matrix = [
            # Only 1 featured candidate
            self._row("A", "B", (2, 1, 0), (1, 1, 2, 1)),   # drug_evidence=2
            # 4 novel candidates
            self._row("C", "D", (0, 0, 0), (2, 2, 3, 2)),   # exploratory_total=9
            self._row("E", "F", (0, 0, 0), (1, 2, 2, 1)),   # exploratory_total=6
            self._row("G", "H", (0, 0, 0), (1, 1, 2, 1)),   # exploratory_total=5
            self._row("I", "J", (0, 0, 0), (0, 0, 3, 1)),   # exploratory_total=4, novel (bio>=3)
        ]

        ranked = rank_featured_candidates(
            matrix, min_featured=1, max_featured=3, min_novel=1, max_novel=3, max_total=5
        )
        featured = [r for r in ranked if r["is_featured"]]
        novel = [r for r in ranked if r.get("is_novel")]

        # Only 1 featured available → 1 featured
        assert len(featured) == 1
        # Remaining slots (5 - 1 = 4) → capped by max_novel=3
        assert len(novel) == 3
        # Total does not exceed max_total
        assert len(featured) + len(novel) <= 5

    def test_all_novel_no_featured(self):
        """When all candidates have drug_evidence=0, all go to novel track."""
        from src.agents.drug_target.tools.stage_logic import rank_featured_candidates

        matrix = [
            self._row("A", "B", (0, 0, 0), (2, 2, 3, 2)),   # exploratory_total=9
            self._row("C", "D", (0, 0, 0), (1, 1, 2, 1)),   # exploratory_total=5
            self._row("E", "F", (0, 0, 0), (0, 0, 2, 2)),   # exploratory_total=4
        ]

        ranked = rank_featured_candidates(
            matrix, min_featured=2, max_featured=5, min_novel=1, max_novel=3, max_total=7
        )
        featured = [r for r in ranked if r["is_featured"]]
        novel = [r for r in ranked if r.get("is_novel")]

        # No featured candidates (all drug_evidence=0)
        assert len(featured) == 0
        # All eligible are novel
        assert len(novel) == 3
        # Sorted by exploratory_total descending
        assert novel[0]["exploratory_total"] == 9
        assert novel[1]["exploratory_total"] == 5
        assert novel[2]["exploratory_total"] == 4


# =========================================================================
# 11. TestSkillLoadingEndToEnd — Verify skills load from real SKILL.md files
# =========================================================================

class TestSkillLoadingEndToEnd:
    """End-to-end verification that SkillLoadHarness loads real project skills."""

    def test_skill_registry_resolves_all_5_skills(self):
        """_build_skill_registry returns paths to all 5 skill dirs with SKILL.md."""
        from src.agents.drug_target.agent import _build_skill_registry, DrugTargetConfig

        config = DrugTargetConfig()
        registry = _build_skill_registry(config)

        expected_names = {
            "opentargets-database",
            "gwas-database",
            "chembl-database",
            "kegg-database",
            "string-database",
        }
        assert set(registry.keys()) == expected_names
        for name, path in registry.items():
            skill_md = Path(path) / "SKILL.md"
            assert skill_md.exists(), f"Missing SKILL.md for {name} at {skill_md}"

    def test_harness_formats_all_skills_with_descriptions(self):
        """SkillLoadHarness formats all 5 skills with real descriptions."""
        from src.agents.drug_target.agent import _build_skill_registry, DrugTargetConfig
        from src.agents.shared.skill_load_harness import SkillLoadHarness

        config = DrugTargetConfig()
        harness = SkillLoadHarness(
            skill_registry=_build_skill_registry(config),
        )

        formatted = harness._format_available_skills()

        # All 3 skills present as bold entries
        for name in config.agent_skill_names:
            assert f"**{name}**" in formatted, f"Skill {name} missing from formatted output"

        # No skills with missing descriptions
        assert "(no description)" not in formatted

    @pytest.mark.asyncio
    async def test_harness_injects_forced_eval_into_system_prompt(self):
        """awrap_model_call injects forced-eval protocol with all 5 real skills."""
        from src.agents.drug_target.agent import _build_skill_registry, DrugTargetConfig
        from src.agents.shared.skill_load_harness import SkillLoadHarness

        config = DrugTargetConfig()
        harness = SkillLoadHarness(
            skill_registry=_build_skill_registry(config),
        )

        # Mock request (same pattern as test_skill_load_harness.py)
        class _Msg:
            def __init__(self, content):
                self.content = content

        class _Req:
            def __init__(self, text):
                self.system_message = _Msg(text)
                self.system_prompt = None
            def override(self, **kw):
                obj = _Req.__new__(_Req)
                obj.system_message = self.system_message
                obj.system_prompt = self.system_prompt
                for k, v in kw.items():
                    setattr(obj, k, v)
                return obj

        captured = None

        async def handler(req):
            nonlocal captured
            captured = str(req.system_message.content)
            return "mock"

        await harness.awrap_model_call(_Req("You are evidence_assessor."), handler)

        assert captured is not None
        # Original prompt preserved
        assert "You are evidence_assessor." in captured
        # Forced-eval 3-phase protocol
        assert "Phase 1" in captured
        assert "Phase 2" in captured
        assert "Phase 3" in captured
        # All 3 skill names injected
        for name in config.agent_skill_names:
            assert name in captured, f"Skill {name} missing from injected prompt"
        # Placeholder fully substituted
        assert "{{available_skills}}" not in captured
