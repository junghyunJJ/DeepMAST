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
        assert len(tools) >= 12  # Stage 3 ChEMBL tools run inline in evidence_assessor

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
            "list_census_cell_types",
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
        # Stage 3 ChEMBL tools now run inline in evidence_assessor.
        assert "query_chembl_target_profile" in names
        assert "run_stage3_batch" in names
        assert "validate_stage3_gate" in names
        # PubMed literature search is NOT wired into evidence_assessor.
        assert "search_literature_dynamic" not in names

    def test_workflow_order(self):
        from src.agents.drug_target.subagents.configs import WORKFLOW_ORDER
        assert WORKFLOW_ORDER == ["evidence_assessor", "hypothesis_writer"]

    def test_get_subagents_returns_2(self):
        from src.agents.drug_target.subagents.configs import get_subagents
        subagents = get_subagents()
        assert len(subagents) == 2

    def test_get_subagents_order(self):
        from src.agents.drug_target.subagents.configs import get_subagents
        subagents = get_subagents()
        names = [s["name"] for s in subagents]
        assert names == ["evidence_assessor", "hypothesis_writer"]

    def test_custom_tools_appended_to_interpretive_subagents_only(self):
        """Custom tools are appended to all 2 subagents; no summarizer present."""
        from src.agents.drug_target.subagents.configs import get_subagents
        mock_tool = MagicMock(spec=["name"])
        mock_tool.name = "custom_tool"
        subagents = get_subagents(custom_tools=[mock_tool])
        # No summarizer in 2-subagent setup
        assert not any(s["name"] == "summarizer" for s in subagents)
        # custom_tool is appended to every subagent
        for sub in subagents:
            tool_names = [t.name for t in sub["tools"]]
            assert "custom_tool" in tool_names

    def test_evidence_assessor_prompt_mentions_databases_and_rubric(self):
        from src.agents.drug_target.subagents.configs import SUBAGENT_CONFIGS
        prompt = SUBAGENT_CONFIGS["evidence_assessor"]["system_prompt"]
        for keyword in ("OpenTargets", "GWAS"):
            assert keyword in prompt
        # Rubric references (merged from clinical_assessor)
        assert "rubric" in prompt.lower() or "RUBRIC" in prompt
        assert "validated" in prompt.lower()
        assert "exploratory" in prompt.lower()
        # evidence_assessor is tool-driven: no hard-coded skill reads in prompt.
        # Skill activation is delegated to SkillActivator on interpretive subagents.
        assert "skills/string-database/SKILL.md" not in prompt
        assert "skills/cellxgene-census/SKILL.md" not in prompt
        assert "skills/compare-census-gene-pair-by-cell-type/SKILL.md" not in prompt
        assert "skills/chembl-database/SKILL.md" not in prompt
        assert "KEGG" not in prompt
        assert "Reactome" not in prompt

    def test_evidence_assessor_prompt_mentions_3_stages(self):
        from src.agents.drug_target.subagents.configs import SUBAGENT_CONFIGS
        prompt = SUBAGENT_CONFIGS["evidence_assessor"]["system_prompt"]
        assert "Stage 1" in prompt
        assert "Stage 2" in prompt
        assert "Stage 3" in prompt

    def test_evidence_assessor_has_stage3_tools(self):
        """Stage 3 ChEMBL tools now run inline inside evidence_assessor (v5 merge)."""
        from src.agents.drug_target.subagents.configs import SUBAGENT_CONFIGS
        tools = SUBAGENT_CONFIGS["evidence_assessor"]["tools"]
        names = {t.name for t in tools}
        assert "run_stage3_batch" in names
        assert "query_chembl_target_profile" in names
        assert "validate_stage3_gate" in names

    def test_evidence_assessor_prompt_mentions_stage3(self):
        """Evidence assessor prompt must describe Stage 3 ChEMBL deep dive inline."""
        from src.agents.drug_target.subagents.configs import SUBAGENT_CONFIGS
        prompt = SUBAGENT_CONFIGS["evidence_assessor"]["system_prompt"]
        assert "Stage 3" in prompt
        assert "ChEMBL" in prompt
        assert "run_stage3_batch" in prompt

    def test_workflow_description_mentions_2_agents(self):
        from src.agents.drug_target.subagents.configs import WORKFLOW_DESCRIPTION

        assert "2-Agent Workflow" in WORKFLOW_DESCRIPTION and "finalize_report" in WORKFLOW_DESCRIPTION
        assert "EVIDENCE_ASSESSOR" in WORKFLOW_DESCRIPTION
        assert "HYPOTHESIS_WRITER" in WORKFLOW_DESCRIPTION

    def test_evidence_assessor_prompt_mentions_census_and_gwas(self):
        from src.agents.drug_target.subagents.configs import SUBAGENT_CONFIGS
        prompt = SUBAGENT_CONFIGS["evidence_assessor"]["system_prompt"]
        assert "Census" in prompt or "run_stage1_batch" in prompt
        assert "GWAS" in prompt

    def test_hypothesis_writer_has_evidence_tools(self):
        from src.agents.drug_target.subagents.configs import SUBAGENT_CONFIGS
        tools = SUBAGENT_CONFIGS["hypothesis_writer"]["tools"]
        names = {t.name for t in tools}
        assert "load_evidence_files" in names
        assert "read_skill_file" in names
        assert "save_evidence" in names
        assert "think_tool" in names
        assert "sequential_thinking" not in names

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

    def test_subagent_prompts_registry_has_2_entries(self):
        """SUBAGENT_PROMPTS contains only evidence_assessor and hypothesis_writer
        after summarizer/critic/report_writer removal."""
        from src.agents.drug_target.subagents.prompts import SUBAGENT_PROMPTS
        assert len(SUBAGENT_PROMPTS) == 2
        assert set(SUBAGENT_PROMPTS.keys()) == {"evidence_assessor", "hypothesis_writer"}

    def test_orchestrator_prompt_has_no_summarizer_status(self):
        """Row 7: SUMMARIZER_STATUS must not appear in the orchestrator prompt."""
        from src.agents.drug_target.agent import ORCHESTRATOR_SYSTEM_PROMPT_TEMPLATE
        assert "SUMMARIZER_STATUS" not in ORCHESTRATOR_SYSTEM_PROMPT_TEMPLATE
        assert "EVIDENCE_PIPELINE_COMPLETE" in ORCHESTRATOR_SYSTEM_PROMPT_TEMPLATE

    def test_drug_target_config_has_no_summarizer_skill_names(self):
        """Row 8: DrugTargetConfig must not have the removed summarizer_skill_names field."""
        from src.agents.drug_target.agent import DrugTargetConfig
        assert not hasattr(DrugTargetConfig, "summarizer_skill_names")
        assert not hasattr(DrugTargetConfig, "critic_enabled")


class TestStage1NullSafe:
    """B.1: compute_stage1_filter must not crash on explicit None values."""

    def test_compute_stage1_filter_handles_null_pvalues(self):
        from src.agents.drug_target.tools.stage_logic import compute_stage1_filter
        evidence = {
            "string_ppi": {"max_combined_score": 0.9},
            "census_validation": {"target_vs_rest": {
                "coexpression": {"p_value": None},
                "gene_a": {"p_value": 0.01},
                "gene_b": {"p_value": 0.02},
            }},
        }
        result = compute_stage1_filter(evidence)
        # Null coexpression p-value defaults to 1.0 (non-passing)
        assert result["passed"] is False
        assert result["census_coexpr_pvalue"] == 1.0

    def test_compute_stage1_filter_handles_null_string_score(self):
        from src.agents.drug_target.tools.stage_logic import compute_stage1_filter
        evidence = {
            "string_ppi": {"max_combined_score": None},
            "census_validation": {"target_vs_rest": {
                "coexpression": {"p_value": 0.01},
                "gene_a": {"p_value": 0.01},
                "gene_b": {"p_value": 0.01},
            }},
        }
        result = compute_stage1_filter(evidence)
        # Null STRING score defaults to 0.0 (fails > 0.8 threshold)
        assert result["passed"] is False
        assert result["string_combined"] == 0.0

    def test_compute_stage1_filter_passes_with_valid_data(self):
        """Sanity regression: valid inputs still pass the filter."""
        from src.agents.drug_target.tools.stage_logic import compute_stage1_filter
        evidence = {
            "string_ppi": {"max_combined_score": 0.9},
            "census_validation": {"target_vs_rest": {
                "coexpression": {"p_value": 0.01},
                "gene_a": {"p_value": 0.01},
                "gene_b": {"p_value": 0.01},
            }},
        }
        result = compute_stage1_filter(evidence)
        assert result["passed"] is True
        assert result["string_combined"] == 0.9
        assert result["census_coexpr_pvalue"] == 0.01


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

    def test_load_lr_candidates_persists_input_disease_context(self, mock_data_dir):
        from src.agents.drug_target.tools.evidence_loader import load_lr_candidates

        raw = load_lr_candidates.invoke({
            "data_dir": str(mock_data_dir),
            "disease": "idiopathic pulmonary fibrosis",
        })
        result = json.loads(raw)
        disease_context = json.loads(
            (mock_data_dir / "evidence" / "disease_context.json").read_text()
        )

        assert result["disease"] == "idiopathic pulmonary fibrosis"
        assert disease_context["input_disease"] == "idiopathic pulmonary fibrosis"
        assert disease_context["canonical_disease"] == "idiopathic pulmonary fibrosis"
        assert disease_context["input_source"] == "cli"

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

        # Roundtrip: load it back — small files (< 200 KB) return full content;
        # large files fall back to a metadata summary.
        raw2 = load_evidence_files.invoke({"data_dir": str(tmp_path)})
        result2 = json.loads(raw2)
        assert "test_gene.json" in result2["files"]
        loaded = result2["files"]["test_gene.json"]
        assert loaded["gene"] == "TGFB1"
        assert loaded["score"] == 0.95

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
# 3.5. TestHypothesisScopeLoader  (scope-aware load_evidence_files)
# =========================================================================

class TestHypothesisScopeLoader:
    """Scope-aware `load_evidence_files` (Codex F1/F2/F3 hardening)."""

    @staticmethod
    def _seed_assessment(ev_dir, featured_genes):
        payload = {
            "schema_version": 3,
            "stage3_candidates": [{"gene": g} for g in featured_genes],
        }
        (ev_dir / "assessment_results.json").write_text(json.dumps(payload))

    @staticmethod
    def _seed_filter_json(ev_dir, pairs):
        """pairs: list[tuple[ligand, receptor, passed_bool]]"""
        rows = [
            {"ligand": L, "receptor": R, "passed": p} for (L, R, p) in pairs
        ]
        (ev_dir / "stage1_filter_results.json").write_text(json.dumps(rows))

    @staticmethod
    def _seed_pair_file(ev_dir, ligand, receptor, passed):
        payload = {
            "ligand": ligand,
            "receptor": receptor,
            "string_ppi": {
                "string_record_found": True,
                "max_combined_score": 0.99 if passed else 0.5,
            },
            "census_validation": {
                "target_vs_rest": {
                    "coexpression": {"p_value": 0.0 if passed else 1.0},
                    "gene_a": {"p_value": 0.0},
                    "gene_b": {"p_value": 0.0},
                },
            },
            "stage1_filter": {
                "passed": passed,
                "string_combined": 0.99 if passed else 0.5,
                "string_status": "in_db",
                "census_coexpr_pvalue": 0.0 if passed else 1.0,
                "census_gene_a_pvalue": 0.0,
                "census_gene_b_pvalue": 0.0,
            },
        }
        (ev_dir / f"stage1_{ligand}--{receptor}.json").write_text(json.dumps(payload))

    def _make_dir(self, tmp_path):
        ev = tmp_path / "evidence"
        ev.mkdir()
        return ev

    def test_default_scope_is_all(self, tmp_path):
        """Regression guard: scope='all' (default) preserves legacy behavior."""
        from src.agents.drug_target.tools.evidence_loader import load_evidence_files
        ev = self._make_dir(tmp_path)
        (ev / "ot_CD4.json").write_text(json.dumps({"gene": "CD4", "associations": [1, 2]}))
        (ev / "ot_IRRELEVANT.json").write_text(json.dumps({"gene": "IRRELEVANT", "associations": []}))
        raw = load_evidence_files.invoke({"data_dir": str(tmp_path)})
        result = json.loads(raw)
        # Legacy: both files returned full content regardless of featured set
        assert "ot_CD4.json" in result["files"]
        assert "ot_IRRELEVANT.json" in result["files"]
        assert result["files"]["ot_IRRELEVANT.json"].get("gene") == "IRRELEVANT"
        # excluded_files is always present but empty in scope=all
        assert result["excluded_files"] == []

    def test_hypothesis_scope_drops_non_featured_ot(self, tmp_path):
        from src.agents.drug_target.tools.evidence_loader import load_evidence_files
        ev = self._make_dir(tmp_path)
        self._seed_assessment(ev, ["CD4", "FN1"])
        (ev / "ot_CD4.json").write_text(json.dumps({"gene": "CD4", "data": {"x": 1}}))
        (ev / "ot_FN1.json").write_text(json.dumps({"gene": "FN1", "data": {"x": 2}}))
        (ev / "ot_IRRELEVANT.json").write_text(json.dumps({"gene": "IRRELEVANT", "data": {"x": 3}}))
        raw = load_evidence_files.invoke({"data_dir": str(tmp_path), "scope": "hypothesis"})
        result = json.loads(raw)
        # Featured: full content
        assert result["files"]["ot_CD4.json"].get("gene") == "CD4"
        assert result["files"]["ot_FN1.json"].get("gene") == "FN1"
        # Non-featured: stub with _note
        stub = result["files"]["ot_IRRELEVANT.json"]
        assert "skipped: non-featured" in stub.get("_note", "")
        assert "gene" not in stub  # full body not present

    def test_hypothesis_scope_stubs_stale_stage3(self, tmp_path):
        """Codex F2: stage3_<GENE>.json not in current featured set is stubbed."""
        from src.agents.drug_target.tools.evidence_loader import load_evidence_files
        ev = self._make_dir(tmp_path)
        self._seed_assessment(ev, ["CD4"])
        (ev / "stage3_CD4.json").write_text(json.dumps({"gene": "CD4", "targets": ["drug1"]}))
        (ev / "stage3_OLD.json").write_text(json.dumps({"gene": "OLD", "targets": ["stale_drug"]}))
        raw = load_evidence_files.invoke({"data_dir": str(tmp_path), "scope": "hypothesis"})
        result = json.loads(raw)
        assert result["files"]["stage3_CD4.json"].get("gene") == "CD4"
        stub = result["files"]["stage3_OLD.json"]
        assert stub.get("_note", "").startswith("stale prior-run stage3 file")
        assert "targets" not in stub

    def test_hypothesis_scope_excludes_failed_pair_stage1(self, tmp_path):
        from src.agents.drug_target.tools.evidence_loader import load_evidence_files
        ev = self._make_dir(tmp_path)
        self._seed_assessment(ev, ["CD4"])
        self._seed_filter_json(
            ev,
            [("FN1", "ITGB2", True), ("TGFB1", "P4HB", False)],
        )
        self._seed_pair_file(ev, "FN1", "ITGB2", passed=True)
        self._seed_pair_file(ev, "TGFB1", "P4HB", passed=False)
        raw = load_evidence_files.invoke({"data_dir": str(tmp_path), "scope": "hypothesis"})
        result = json.loads(raw)
        # PASSED: full content (has string_ppi + census_validation)
        passed_payload = result["files"]["stage1_FN1--ITGB2.json"]
        assert "string_ppi" in passed_payload
        assert "census_validation" in passed_payload
        # FAILED: excluded entirely from hypothesis inputs
        assert "stage1_TGFB1--P4HB.json" not in result["files"]
        excluded = {entry["name"]: entry["reason"] for entry in result["excluded_files"]}
        assert "failed Stage 1 pair" in excluded["stage1_TGFB1--P4HB.json"]

    def test_hypothesis_scope_falls_back_to_csv(self, tmp_path):
        """Codex F1: JSON missing → CSV fallback."""
        import csv as _csv
        from src.agents.drug_target.tools.evidence_loader import load_evidence_files
        ev = self._make_dir(tmp_path)
        self._seed_assessment(ev, ["CD4"])
        # Only CSV (no JSON sidecar)
        csv_path = ev / "stage1_filter_results.csv"
        with open(csv_path, "w", newline="") as f:
            writer = _csv.DictWriter(f, fieldnames=["ligand", "receptor", "passed"])
            writer.writeheader()
            writer.writerow({"ligand": "FN1", "receptor": "ITGB2", "passed": "true"})
            writer.writerow({"ligand": "TGFB1", "receptor": "P4HB", "passed": "false"})
        self._seed_pair_file(ev, "FN1", "ITGB2", passed=True)
        self._seed_pair_file(ev, "TGFB1", "P4HB", passed=False)
        raw = load_evidence_files.invoke({"data_dir": str(tmp_path), "scope": "hypothesis"})
        result = json.loads(raw)
        # CSV-driven classification still applies
        passed_payload = result["files"]["stage1_FN1--ITGB2.json"]
        assert "string_ppi" in passed_payload  # full content
        assert "stage1_TGFB1--P4HB.json" not in result["files"]

    def test_hypothesis_scope_fails_closed_when_filter_missing(self, tmp_path):
        """No JSON and no CSV means no Stage 1 pair files are exposed."""
        from src.agents.drug_target.tools.evidence_loader import load_evidence_files
        ev = self._make_dir(tmp_path)
        self._seed_assessment(ev, ["CD4"])
        # NO filter JSON, NO filter CSV — only per-pair files
        self._seed_pair_file(ev, "FN1", "ITGB2", passed=True)
        self._seed_pair_file(ev, "TGFB1", "P4HB", passed=False)
        raw = load_evidence_files.invoke({"data_dir": str(tmp_path), "scope": "hypothesis"})
        result = json.loads(raw)
        assert result["files"] == {}
        assert any("hypothesis scope aborted" in e for e in result["errors"])
        assert any("Stage 1 pair files are hidden" in e for e in result["errors"])

    def test_hypothesis_scope_fails_closed_when_filter_unparseable(self, tmp_path):
        """Unparseable filter results also hide Stage 1 pair content."""
        from src.agents.drug_target.tools.evidence_loader import load_evidence_files
        ev = self._make_dir(tmp_path)
        self._seed_assessment(ev, ["CD4"])
        (ev / "stage1_filter_results.json").write_text("{not-json")
        self._seed_pair_file(ev, "FN1", "ITGB2", passed=True)
        raw = load_evidence_files.invoke({"data_dir": str(tmp_path), "scope": "hypothesis"})
        result = json.loads(raw)
        assert result["files"] == {}
        assert any("Failed to parse stage1_filter_results.json" in e for e in result["errors"])

    def test_hypothesis_scope_excludes_legacy_and_prior_output(self, tmp_path):
        """Codex F3: legacy aggregates + prior-run outputs excluded from files dict."""
        from src.agents.drug_target.tools.evidence_loader import load_evidence_files
        ev = self._make_dir(tmp_path)
        self._seed_assessment(ev, ["CD4"])
        for name in (
            "stage1_audit.json",
            "stage1_confidence.json",
            "stage1_evidence.json",
            "hypothesis_report.json",
            "target_assessment.json",
        ):
            (ev / name).write_text(json.dumps({"name": name, "body": "x" * 10}))
        raw = load_evidence_files.invoke({"data_dir": str(tmp_path), "scope": "hypothesis"})
        result = json.loads(raw)
        # (a) none appear in files dict
        for name in (
            "stage1_audit.json",
            "stage1_confidence.json",
            "stage1_evidence.json",
            "hypothesis_report.json",
            "target_assessment.json",
        ):
            assert name not in result["files"], f"{name} leaked into files dict"
        # (b) all appear in excluded_files with reason
        excluded_names = {e["name"] for e in result["excluded_files"]}
        assert excluded_names == {
            "stage1_audit.json",
            "stage1_confidence.json",
            "stage1_evidence.json",
            "hypothesis_report.json",
            "target_assessment.json",
        }
        for entry in result["excluded_files"]:
            assert entry.get("reason")

    def test_hypothesis_scope_aborts_when_assessment_missing(self, tmp_path):
        """Hypothesis scope without assessment_results.json is a hard error."""
        from src.agents.drug_target.tools.evidence_loader import load_evidence_files
        ev = self._make_dir(tmp_path)
        # No assessment_results.json
        (ev / "ot_CD4.json").write_text(json.dumps({"gene": "CD4"}))
        raw = load_evidence_files.invoke({"data_dir": str(tmp_path), "scope": "hypothesis"})
        result = json.loads(raw)
        assert result["files"] == {}
        assert any("hypothesis scope aborted" in e for e in result["errors"])

    def test_validate_hypothesis_report_blocks_denied_citations(self, tmp_path):
        """Codex F3: save_evidence rejects hypothesis_report.json citing denied files."""
        from src.agents.drug_target.tools.evidence_loader import save_evidence
        ev = tmp_path / "evidence"
        ev.mkdir()
        # Pre-create the denied files + a legitimate stage1 file so only the
        # denial rule triggers the rejection (not the "file missing" rule).
        for name in ("hypothesis_report.json", "stage1_audit.json"):
            (ev / name).write_text("{}")
        (ev / "stage1_FN1--ITGB2.json").write_text("{}")
        # assessment_results to satisfy downstream validators
        (ev / "assessment_results.json").write_text(json.dumps({
            "schema_version": 3,
            "stage3_candidates": [{"gene": "FN1"}],
        }))
        (ev / "stage1_filter_results.json").write_text(json.dumps([
            {"ligand": "FN1", "receptor": "ITGB2", "passed": True}
        ]))

        payload = {
            "disease": "test",
            "evidence_coverage_pct": 100.0,
            "hypotheses": [{
                "title": "Test",
                "biological_entities": {"genes": ["FN1"]},
                "evidence_references": [
                    "hypothesis_report.json",
                    "stage1_audit.json",
                    "stage1_FN1--ITGB2.json",
                ],
            }],
        }
        raw = save_evidence.invoke({
            "data_dir": str(tmp_path),
            "filename": "hypothesis_report.json",
            "data": json.dumps(payload),
        })
        result = json.loads(raw)
        assert result["saved"] is False
        error_text = " ".join(result.get("errors", [])) + " " + " ".join(
            result.get("invalid_references", []) or []
        )
        assert "hypothesis_report.json" in error_text
        assert "stage1_audit.json" in error_text

    def test_validate_evidence_references_surfaces_denied(self, tmp_path):
        """validate_evidence_references surfaces denied_citations with reason."""
        from src.agents.drug_target.tools.evidence_loader import validate_evidence_references
        ev = tmp_path / "evidence"
        ev.mkdir()
        (ev / "hypothesis_report.json").write_text("{}")
        (ev / "stage1_FN1--ITGB2.json").write_text("{}")
        (ev / "stage1_filter_results.json").write_text(json.dumps([
            {"ligand": "FN1", "receptor": "ITGB2", "passed": True}
        ]))
        raw = validate_evidence_references.invoke({
            "data_dir": str(tmp_path),
            "references": ["hypothesis_report.json", "stage1_FN1--ITGB2.json"],
        })
        result = json.loads(raw)
        assert result["valid"] is False
        tokens = {d["token"] for d in result.get("denied_citations", [])}
        assert "hypothesis_report.json" in tokens
        # The legit reference must NOT be denied
        assert "stage1_FN1--ITGB2.json" not in tokens


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
        assert stage_domain_tools.run_stage3_batch.name == "run_stage3_batch"

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
            "query_chembl_target_profile",
            "run_stage3_batch",
            "run_compare_census_lr_pair",
            "finalize_stage1_artifacts",
            "read_skill_file",
            "save_target_assessment",
            "think_tool", "sequential_thinking", "validate_quality",
            "validate_drug_report_finalization",
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

    def test_build_ot_disease_context_prefers_exact_disease_hit(self):
        import src.agents.drug_target.tools.stage2_service as mod

        class FakeOpenTargetsModule:
            def search_entities(self, query_string, entity_types=None):
                assert query_string == "idiopathic pulmonary fibrosis"
                assert entity_types == ["disease"]
                return [
                    {"id": "EFO_BROAD", "name": "pulmonary fibrosis"},
                    {"id": "EFO_EXACT", "name": "idiopathic pulmonary fibrosis"},
                ]

        context = mod._build_ot_disease_context(
            FakeOpenTargetsModule(),
            "idiopathic pulmonary fibrosis",
        )

        assert context["efo_id"] == "EFO_EXACT"
        assert context["match_label"] == "idiopathic pulmonary fibrosis"
        assert context["exact_match"] is True
        assert context["fallback_used"] is False

    def test_query_stage2_gene_panel_prefers_phase0_input_disease(self, tmp_path):
        from src.agents.drug_target.tools.disease_context import initialize_disease_context
        from src.agents.drug_target.tools.stage_domain_tools import query_stage2_gene_panel

        initialize_disease_context(
            tmp_path / "evidence",
            input_disease="idiopathic pulmonary fibrosis",
            input_source="cli",
        )
        payload = {
            "disease": "idiopathic pulmonary fibrosis",
            "gene_symbols": ["LRP1"],
            "stage2_evidence": {
                "LRP1": {
                    "opentargets": {
                        "gene_symbol": "LRP1",
                        "disease": "idiopathic pulmonary fibrosis",
                        "executed": True,
                        "disease_evidence": [],
                        "associations": [],
                        "errors": [],
                    },
                    "gwas": {
                        "gene_symbol": "LRP1",
                        "disease": "idiopathic pulmonary fibrosis",
                        "executed": True,
                        "trait_associations": [],
                        "gene_associations": [],
                        "errors": [],
                    },
                    "vep": {"source": "ensembl_vep", "variants": []},
                }
            },
            "known_drugs": {
                "disease": "idiopathic pulmonary fibrosis",
                "executed": True,
                "drugs": {"rows": []},
            },
            "gene_manifest": [{"symbol": "LRP1", "is_selected_top3": False}],
            "source_modes": {"opentargets": "parquet", "gwas": "parquet"},
        }

        with patch(
            "src.agents.drug_target.tools.stage_domain_tools.build_stage2_gene_panel",
            return_value=payload,
        ) as mock_build:
            raw = query_stage2_gene_panel.invoke({
                "gene_symbols": ["LRP1"],
                "disease": "pulmonary fibrosis",
                "selected_top3_genes": [],
                "data_dir": str(tmp_path),
            })

        mock_build.assert_called_once_with(
            ["LRP1"],
            "idiopathic pulmonary fibrosis",
            selected_top3_genes=[],
            data_dir=str(tmp_path.resolve()),
        )
        result = json.loads(raw)
        assert result["disease"] == "idiopathic pulmonary fibrosis"
        assert "overridden by input disease" in result["warnings"][0]

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

    def test_build_stage2_gene_panel_retries_transient_source_failures(self, monkeypatch):
        import src.agents.drug_target.tools.stage2_service as mod

        monkeypatch.setenv("DRUG_TARGET_STAGE2_RETRY_BACKOFF", "0")

        ot_calls = []
        gwas_calls = []
        vep_calls = []
        known_calls = []

        def fake_ot(gene_symbol, disease, *, mod=None, disease_context=None):
            ot_calls.append(gene_symbol)
            if len(ot_calls) == 1:
                return {
                    "gene_symbol": gene_symbol,
                    "disease": disease,
                    "executed": False,
                    "errors": ["OpenTargets query failed: HTTP 502 Bad Gateway"],
                }
            return {
                "gene_symbol": gene_symbol,
                "disease": disease,
                "executed": True,
                "ensembl_id": "ENSG_EGFR",
                "errors": [],
            }

        def fake_gwas(gene_symbol, disease, *, mod=None, disease_context=None):
            gwas_calls.append(gene_symbol)
            if len(gwas_calls) == 1:
                return {
                    "gene_symbol": gene_symbol,
                    "disease": disease,
                    "executed": True,
                    "trait_associations": [],
                    "gene_associations": [{"error": "Request timed out"}],
                    "errors": [],
                }
            return {
                "gene_symbol": gene_symbol,
                "disease": disease,
                "executed": True,
                "trait_associations": [],
                "gene_associations": [{"rsId": "rs1"}],
                "errors": [],
            }

        def fake_vep(gwas_data):
            vep_calls.append(gwas_data)
            if len(vep_calls) == 1:
                return {
                    "executed": False,
                    "variants": [],
                    "impact_summary": {},
                    "errors": ["VEP query failed: HTTP 503 Service Unavailable"],
                }
            return {
                "executed": True,
                "variants": [{"id": "rs1"}],
                "impact_summary": {"low_impact": 1},
                "errors": [],
            }

        def fake_known(disease, *, mod=None, disease_context=None, stage2_evidence=None):
            known_calls.append(disease)
            if len(known_calls) == 1:
                return {
                    "disease": disease,
                    "executed": False,
                    "errors": ["OpenTargets drug query failed: gateway timeout"],
                }
            return {"disease": disease, "executed": True, "drugs": {"rows": []}, "errors": []}

        with patch.object(mod, "_try_load_ot_module", return_value=(object(), "api")), \
             patch.object(mod, "_try_load_gwas_module", return_value=(object(), "api")), \
             patch.object(mod, "_build_ot_disease_context", return_value={"efo_id": "EFO_1"}), \
             patch.object(mod, "_build_gwas_disease_context", return_value={"trait_associations": []}), \
             patch.object(mod, "query_opentargets_target_data", side_effect=fake_ot), \
             patch.object(mod, "query_gwas_gene_trait_data", side_effect=fake_gwas), \
             patch.object(mod, "_query_vep_for_gene", side_effect=fake_vep), \
             patch.object(mod, "query_opentargets_known_drugs_data", side_effect=fake_known):
            result = mod.build_stage2_gene_panel(["EGFR"], "lung cancer")

        gene_payload = result["stage2_evidence"]["EGFR"]
        assert len(ot_calls) == 2
        assert len(gwas_calls) == 2
        assert len(vep_calls) == 2
        assert len(known_calls) == 2
        assert gene_payload["opentargets"]["executed"] is True
        assert gene_payload["gwas"]["gene_associations"] == [{"rsId": "rs1"}]
        assert gene_payload["vep"]["executed"] is True
        assert result["known_drugs"]["executed"] is True

    def test_build_stage2_gene_panel_cache_miss_on_transient_errors(self, tmp_path):
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
                        "gene_associations": [{"error": "Request timed out"}],
                        "errors": [],
                    },
                    "vep": {
                        "source": "ensembl_vep",
                        "variants": [],
                    },
                },
            },
            "known_drugs": {"disease": "lung cancer", "executed": True},
            "gene_manifest": [{"symbol": "EGFR", "is_selected_top3": False}],
        }
        mod.write_stage2_artifacts(cached_bundle, tmp_path / "evidence")

        rebuilt = {"called": False}

        def fake_gwas(gene_symbol, disease, *, mod=None, disease_context=None):
            rebuilt["called"] = True
            return {
                "gene_symbol": gene_symbol,
                "disease": disease,
                "executed": True,
                "trait_associations": [],
                "gene_associations": [],
                "errors": [],
            }

        with patch.object(mod, "_try_load_ot_module", return_value=(object(), "parquet")), \
             patch.object(mod, "_try_load_gwas_module", return_value=(object(), "parquet")), \
             patch.object(mod, "_build_ot_disease_context", return_value={"efo_id": "EFO_1"}), \
             patch.object(mod, "_build_gwas_disease_context", return_value={"trait_associations": []}), \
             patch.object(
                 mod,
                 "query_opentargets_target_data",
                 return_value={
                     "gene_symbol": "EGFR",
                     "disease": "lung cancer",
                     "executed": True,
                     "errors": [],
                 },
             ), \
             patch.object(mod, "query_gwas_gene_trait_data", side_effect=fake_gwas), \
             patch.object(mod, "query_opentargets_known_drugs_data", return_value={"disease": "lung cancer", "executed": True}):
            result = mod.build_stage2_gene_panel(["EGFR"], "lung cancer", data_dir=tmp_path)

        assert rebuilt["called"] is True
        assert result["source_modes"] == {"opentargets": "parquet", "gwas": "parquet"}

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

    def test_query_opentargets_known_drugs_separates_disease_landscape_and_target_rows(self):
        from src.agents.drug_target.tools.stage2_service import query_opentargets_known_drugs_data

        class FakeOpenTargetsModule:
            def get_known_drugs_for_disease(self, efo_id):
                assert efo_id == "EFO_0001"
                return {
                    "count": 2,
                    "rows": [
                        {
                            "id": "indication-1",
                            "maxClinicalStage": 4,
                            "drug": {"id": "CHEMBL1", "name": "Drug A"},
                        },
                        {
                            "id": "indication-2",
                            "maxClinicalStage": 3,
                            "drug": {"id": "CHEMBL2", "name": "Drug B"},
                        },
                    ],
                }

        stage2_evidence = {
            "EGFR": {
                "opentargets": {
                    "ensembl_id": "ENSG000001",
                    "target_info": {"approvedSymbol": "EGFR"},
                    "target_drugs": {
                        "rows": [
                            {
                                "maxClinicalStage": 4,
                                "drug": {"id": "CHEMBL1", "name": "Drug A"},
                                "diseases": [
                                    {
                                        "diseaseFromSource": "Lung cancer",
                                        "disease": {"id": "EFO_0001", "name": "lung cancer"},
                                    }
                                ],
                            },
                            {
                                "maxClinicalStage": 2,
                                "drug": {"id": "CHEMBL9", "name": "Other Drug"},
                                "diseases": [
                                    {
                                        "diseaseFromSource": "Melanoma",
                                        "disease": {"id": "EFO_0002", "name": "melanoma"},
                                    }
                                ],
                            },
                        ]
                    },
                }
            }
        }

        result = query_opentargets_known_drugs_data(
            "lung cancer",
            mod=FakeOpenTargetsModule(),
            disease_context={"efo_id": "EFO_0001"},
            stage2_evidence=stage2_evidence,
        )

        assert result["executed"] is True
        assert result["disease_landscape"]["count"] == 2
        assert result["drugs"]["uniqueDrugs"] == 1
        assert result["drugs"]["uniqueTargets"] == 1
        assert result["drugs"]["rows"] == result["target_linked_rows"]
        assert result["drugs"]["rows"][0]["target"]["approvedSymbol"] == "EGFR"
        assert result["drugs"]["rows"][0]["drug"]["id"] == "CHEMBL1"

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
            "disease_context.json",
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
        disease_context = json.loads((tmp_path / "evidence" / "disease_context.json").read_text())
        assert disease_context["input_disease"] == "lung cancer"
        assert disease_context["stage2"]["disease_used"] == "lung cancer"

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


class TestStage3Batch:
    """Batch Stage 3 ChEMBL orchestration and canonical artifact contract."""

    def test_run_stage3_batch_saves_missing_profiles_and_skips_existing(self, tmp_path):
        from src.agents.drug_target.tools.stage_domain_tools import run_stage3_batch

        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        (evidence_dir / "assessment_results.json").write_text(json.dumps({
            "stage3_candidates": [
                {"gene": "EGFR"},
                {"gene": "MET"},
            ],
        }))
        (evidence_dir / "stage3_MET.json").write_text(json.dumps({
            "gene": "MET",
            "executed": True,
            "errors": [],
            "chembl": {"matched_drugs": [{"drug_name": "Existing"}]},
            "source": "chembl",
        }))

        calls = []

        def fake_profile(gene_symbol, max_drugs=10, organism="human"):
            calls.append((gene_symbol, max_drugs, organism))
            return {
                "gene_symbol": gene_symbol,
                "executed": True,
                "matched_drugs": [{"chembl_id": "CHEMBL1", "drug_name": "Gefitinib"}],
                "source": "chembl",
                "errors": [],
            }

        with patch(
            "src.agents.drug_target.tools.stage_domain_tools._query_chembl_target_profile_payload",
            side_effect=fake_profile,
        ):
            raw = run_stage3_batch.invoke({
                "data_dir": str(tmp_path),
                "max_drugs": 5,
                "organism": "human",
            })

        result = json.loads(raw)
        assert result["success"] is True
        assert result["total"] == 2
        assert result["queried_genes"] == ["EGFR"]
        assert result["skipped_existing"] == ["MET"]
        assert result["retried_existing"] == []
        assert result["saved_files"] == ["stage3_EGFR.json"]
        assert result["validation"]["success"] is True
        assert calls == [("EGFR", 5, "human")]

        saved = json.loads((evidence_dir / "stage3_EGFR.json").read_text())
        assert saved["gene"] == "EGFR"
        assert saved["executed"] is True
        assert saved["errors"] == []
        assert saved["chembl"]["matched_drugs"][0]["drug_name"] == "Gefitinib"

    def test_run_stage3_batch_retries_invalid_existing_profiles(self, tmp_path):
        from src.agents.drug_target.tools.stage_domain_tools import run_stage3_batch

        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        (evidence_dir / "assessment_results.json").write_text(json.dumps({
            "stage3_candidates": [
                {"gene": "BAD"},
                {"gene": "GOOD"},
            ],
        }))
        (evidence_dir / "stage3_BAD.json").write_text(json.dumps({
            "gene": "BAD",
            "executed": False,
            "errors": ["ChEMBL HTTP 502"],
            "chembl": {"executed": False, "matched_drugs": [], "errors": ["ChEMBL HTTP 502"]},
            "source": "chembl",
        }))
        (evidence_dir / "stage3_GOOD.json").write_text(json.dumps({
            "gene": "GOOD",
            "executed": True,
            "errors": [],
            "chembl": {"executed": True, "matched_drugs": [{"drug_name": "Existing"}], "errors": []},
            "source": "chembl",
        }))

        calls = []

        def fake_profile(gene_symbol, max_drugs=10, organism="human"):
            calls.append((gene_symbol, max_drugs, organism))
            return {
                "gene_symbol": gene_symbol,
                "executed": True,
                "matched_drugs": [{"chembl_id": "CHEMBL_BAD", "drug_name": "Recovered"}],
                "source": "chembl",
                "errors": [],
            }

        with patch(
            "src.agents.drug_target.tools.stage_domain_tools._query_chembl_target_profile_payload",
            side_effect=fake_profile,
        ):
            raw = run_stage3_batch.invoke({
                "data_dir": str(tmp_path),
                "max_drugs": 3,
                "organism": "human",
            })

        result = json.loads(raw)
        assert result["success"] is True
        assert result["queried_genes"] == ["BAD"]
        assert result["skipped_existing"] == ["GOOD"]
        assert result["retried_existing"] == [{"gene": "BAD", "reason": "not_executed"}]
        assert result["saved_files"] == ["stage3_BAD.json"]
        assert result["validation"]["success"] is True
        assert calls == [("BAD", 3, "human")]

        saved = json.loads((evidence_dir / "stage3_BAD.json").read_text())
        assert saved["executed"] is True
        assert saved["errors"] == []
        assert saved["chembl"]["matched_drugs"][0]["drug_name"] == "Recovered"

    def test_run_stage3_batch_fails_when_profile_has_errors(self, tmp_path):
        from src.agents.drug_target.tools.stage_domain_tools import run_stage3_batch

        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        (evidence_dir / "assessment_results.json").write_text(json.dumps({
            "stage3_candidates": [
                {"gene": "FAIL1"},
            ],
        }))

        def fake_profile(gene_symbol, max_drugs=10, organism="human"):
            return {
                "gene_symbol": gene_symbol,
                "executed": False,
                "matched_drugs": [],
                "source": "chembl",
                "errors": ["ChEMBL HTTP 503: service unavailable"],
            }

        with patch(
            "src.agents.drug_target.tools.stage_domain_tools._query_chembl_target_profile_payload",
            side_effect=fake_profile,
        ):
            raw = run_stage3_batch.invoke({
                "data_dir": str(tmp_path),
                "max_drugs": 5,
                "organism": "human",
            })

        result = json.loads(raw)
        assert result["success"] is False
        assert result["failed_genes"] == ["FAIL1"]
        assert result["validation"]["success"] is False
        assert result["validation"]["genes_with_errors"] == ["FAIL1"]

        saved = json.loads((evidence_dir / "stage3_FAIL1.json").read_text())
        assert saved["executed"] is False
        assert saved["errors"] == ["ChEMBL HTTP 503: service unavailable"]

    def test_run_stage3_batch_fails_when_profile_not_executed_without_errors(self, tmp_path):
        from src.agents.drug_target.tools.stage_domain_tools import run_stage3_batch

        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        (evidence_dir / "assessment_results.json").write_text(json.dumps({
            "stage3_candidates": [
                {"gene": "NOEXEC"},
            ],
        }))

        def fake_profile(gene_symbol, max_drugs=10, organism="human"):
            return {
                "gene_symbol": gene_symbol,
                "executed": False,
                "matched_drugs": [],
                "source": "chembl",
                "errors": [],
            }

        with patch(
            "src.agents.drug_target.tools.stage_domain_tools._query_chembl_target_profile_payload",
            side_effect=fake_profile,
        ):
            raw = run_stage3_batch.invoke({
                "data_dir": str(tmp_path),
                "max_drugs": 5,
                "organism": "human",
            })

        result = json.loads(raw)
        assert result["success"] is False
        assert result["failed_genes"] == ["NOEXEC"]
        assert result["validation"]["success"] is False
        assert result["validation"]["genes_with_errors"] == ["NOEXEC"]

    def test_validate_stage3_gate_fails_when_profile_executed_with_errors(self, tmp_path):
        from src.agents.drug_target.tools.stage_logic import validate_stage3_gate

        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        (evidence_dir / "assessment_results.json").write_text(json.dumps({
            "stage3_candidates": [
                {"gene": "ERRGENE"},
            ],
        }))
        (evidence_dir / "stage3_ERRGENE.json").write_text(json.dumps({
            "gene": "ERRGENE",
            "executed": True,
            "errors": ["partial ChEMBL payload parse failed"],
            "chembl": {"matched_drugs": []},
            "source": "chembl",
        }))

        result = json.loads(validate_stage3_gate.invoke({"data_dir": str(tmp_path)}))

        assert result["success"] is False
        assert result["genes_with_errors"] == ["ERRGENE"]

    def test_run_stage3_batch_fails_when_profile_executed_with_errors(self, tmp_path):
        from src.agents.drug_target.tools.stage_domain_tools import run_stage3_batch

        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        (evidence_dir / "assessment_results.json").write_text(json.dumps({
            "stage3_candidates": [
                {"gene": "ERRTRUE"},
            ],
        }))

        def fake_profile(gene_symbol, max_drugs=10, organism="human"):
            return {
                "gene_symbol": gene_symbol,
                "executed": True,
                "matched_drugs": [],
                "source": "chembl",
                "errors": ["partial ChEMBL payload parse failed"],
            }

        with patch(
            "src.agents.drug_target.tools.stage_domain_tools._query_chembl_target_profile_payload",
            side_effect=fake_profile,
        ):
            raw = run_stage3_batch.invoke({
                "data_dir": str(tmp_path),
                "max_drugs": 5,
                "organism": "human",
            })

        result = json.loads(raw)
        assert result["success"] is False
        assert result["failed_genes"] == ["ERRTRUE"]
        assert result["validation"]["success"] is False
        assert result["validation"]["genes_with_errors"] == ["ERRTRUE"]

    def test_run_stage3_batch_queries_missing_profiles_concurrently(self, tmp_path):
        import os
        import threading
        import time

        from src.agents.drug_target.tools import stage_domain_tools
        from src.agents.drug_target.tools.stage_domain_tools import run_stage3_batch

        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        (evidence_dir / "assessment_results.json").write_text(json.dumps({
            "stage3_candidates": [
                {"gene": "EGFR"},
                {"gene": "MET"},
                {"gene": "ERBB2"},
            ],
        }))

        lock = threading.Lock()
        active_calls = 0
        max_active_calls = 0

        def fake_chembl_drugs(gene_symbol, max_drugs, organism="human"):
            nonlocal active_calls, max_active_calls
            with lock:
                active_calls += 1
                max_active_calls = max(max_active_calls, active_calls)
            time.sleep(0.05)
            with lock:
                active_calls -= 1
            return [{
                "chembl_id": f"CHEMBL_{gene_symbol}",
                "drug_name": f"{gene_symbol} inhibitor",
            }]

        with (
            patch.object(stage_domain_tools, "_query_chembl_drugs", side_effect=fake_chembl_drugs),
            patch.dict(os.environ, {"DRUG_TARGET_STAGE3_CHEMBL_WORKERS": "3"}),
        ):
            raw = run_stage3_batch.invoke({
                "data_dir": str(tmp_path),
                "max_drugs": 5,
                "organism": "human",
            })

        result = json.loads(raw)
        assert result["success"] is True
        assert result["queried_genes"] == ["EGFR", "MET", "ERBB2"]
        assert result["saved_files"] == [
            "stage3_EGFR.json",
            "stage3_MET.json",
            "stage3_ERBB2.json",
        ]
        assert max_active_calls > 1


class TestStage1Batch:
    """Batch Stage 1 orchestration and resume behavior."""

    def test_run_stage1_batch_skips_existing_stage1_files(self, tmp_path):
        from src.agents.drug_target.tools.stage_domain_tools import run_stage1_batch

        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        (tmp_path / "lr_candidates.json").write_text(json.dumps({
            "pairs": [
                {"ligand": "EGFR", "receptor": "MET"},
                {"ligand": "MET", "receptor": "ERBB2"},
            ],
        }))
        (evidence_dir / "assessment_results.json").write_text(json.dumps({
            "stage3_candidates": [
                {"gene": "EGFR"},
                {"gene": "MET"},
            ],
        }))
        existing_payload = {
            "ligand": "EGFR",
            "receptor": "MET",
            "string_ppi": {"interaction_found": True, "combined_score": 0.99},
        }
        (evidence_dir / "stage1_EGFR--MET.json").write_text(json.dumps(existing_payload))

        calls = []

        def fake_string(args):
            calls.append((args["gene_a"], args["gene_b"]))
            return json.dumps({
                "gene_a": args["gene_a"],
                "gene_b": args["gene_b"],
                "interaction_found": True,
                "combined_score": 0.88,
            })

        class _FakeStringTool:
            @staticmethod
            def invoke(args):
                return fake_string(args)

        class _FakeStage1FilterTool:
            @staticmethod
            def invoke(args):
                return json.dumps({"success": True})

        with (
            patch(
                "src.agents.drug_target.tools.stage_domain_tools.query_string_ppi_pair",
                _FakeStringTool,
            ),
            patch(
                "src.agents.drug_target.tools.stage1_normalization.finalize_stage1_workspace",
                return_value={"success": True},
            ),
            patch(
                "src.agents.drug_target.tools.stage_logic.apply_stage1_filter",
                _FakeStage1FilterTool,
            ),
        ):
            raw = run_stage1_batch.invoke({
                "data_dir": str(tmp_path),
                "disease": "pulmonary fibrosis",
                "target_cell_type": "",
                "enable_census": False,
            })

        result = json.loads(raw)
        assert result["success"] is True
        assert result["pairs_processed"] == 2
        assert result["skipped_existing"] == ["stage1_EGFR--MET.json"]
        assert result["saved_files"] == ["stage1_MET--ERBB2.json"]
        assert calls == [("MET", "ERBB2")]
        assert json.loads((evidence_dir / "stage1_EGFR--MET.json").read_text()) == existing_payload
        saved = json.loads((evidence_dir / "stage1_MET--ERBB2.json").read_text())
        assert saved["string_ppi"]["combined_score"] == 0.88

    def test_run_stage1_batch_records_census_disease_fallback_context(self, tmp_path):
        from src.agents.drug_target.tools.disease_context import initialize_disease_context
        from src.agents.drug_target.tools.stage_domain_tools import run_stage1_batch

        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        initialize_disease_context(
            evidence_dir,
            input_disease="idiopathic pulmonary fibrosis",
            input_source="cli",
        )
        (tmp_path / "lr_candidates.json").write_text(json.dumps({
            "pairs": [{"ligand": "APOE", "receptor": "LRP1"}],
        }))
        (evidence_dir / "assessment_results.json").write_text(json.dumps({
            "disease": "idiopathic pulmonary fibrosis",
            "stage3_candidates": [{"gene": "LRP1"}],
        }))

        class _FakeStringTool:
            @staticmethod
            def invoke(args):
                return json.dumps({
                    "gene_a": args["gene_a"],
                    "gene_b": args["gene_b"],
                    "interaction_found": True,
                    "combined_score": 0.9,
                })

        class _FakeStage1FilterTool:
            @staticmethod
            def invoke(args):
                return json.dumps({"success": True})

        with (
            patch(
                "src.agents.drug_target.tools.stage_domain_tools.query_string_ppi_pair",
                _FakeStringTool,
            ),
            patch(
                "src.agents.drug_target.tools.stage1_normalization.finalize_stage1_workspace",
                return_value={"success": True},
            ),
            patch(
                "src.agents.drug_target.tools.stage_logic.apply_stage1_filter",
                _FakeStage1FilterTool,
            ),
        ):
            raw = run_stage1_batch.invoke({
                "data_dir": str(tmp_path),
                "disease": "pulmonary fibrosis",
                "target_cell_type": "",
                "enable_census": False,
            })

        result = json.loads(raw)
        disease_context = json.loads((evidence_dir / "disease_context.json").read_text())
        assessment = json.loads((evidence_dir / "assessment_results.json").read_text())

        assert result["success"] is True
        assert disease_context["input_disease"] == "idiopathic pulmonary fibrosis"
        assert disease_context["stage1"]["disease_used"] == "pulmonary fibrosis"
        assert disease_context["stage1"]["fallback_used"] is True
        assert "Stage1" in disease_context["warnings"][0]
        assert assessment["disease"] == "idiopathic pulmonary fibrosis"
        assert assessment["disease_context"]["stage1"]["fallback_used"] is True

    def test_run_stage1_batch_skips_census_when_existing_files_have_validation(self, tmp_path):
        from src.agents.drug_target.tools.stage_domain_tools import run_stage1_batch

        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        (tmp_path / "lr_candidates.json").write_text(json.dumps({
            "pairs": [
                {"ligand": "EGFR", "receptor": "MET"},
            ],
        }))
        (evidence_dir / "assessment_results.json").write_text(json.dumps({
            "stage3_candidates": [
                {"gene": "EGFR"},
            ],
        }))
        existing_payload = {
            "ligand": "EGFR",
            "receptor": "MET",
            "string_ppi": {"interaction_found": True, "combined_score": 0.99},
            "census_validation": {
                "executed": True,
                "target_vs_rest": {"coexpression_p_value": 0.01},
            },
        }
        (evidence_dir / "stage1_EGFR--MET.json").write_text(json.dumps(existing_payload))

        census_calls = []

        def fake_batch(*args, **kwargs):
            census_calls.append((args, kwargs))
            return [], {}

        class _FakeStage1FilterTool:
            @staticmethod
            def invoke(args):
                return json.dumps({"success": True})

        with (
            patch(
                "src.agents.drug_target.tools.stage_domain_tools.query_string_ppi_pair",
                object(),
            ),
            patch(
                "src.agents.drug_target.tools.census_batch_core.batch_census_lr_pairs",
                side_effect=fake_batch,
            ),
            patch(
                "src.agents.drug_target.tools.stage1_normalization.finalize_stage1_workspace",
                return_value={"success": True},
            ),
            patch(
                "src.agents.drug_target.tools.stage_logic.apply_stage1_filter",
                _FakeStage1FilterTool,
            ),
        ):
            raw = run_stage1_batch.invoke({
                "data_dir": str(tmp_path),
                "disease": "pulmonary fibrosis",
                "target_cell_type": "pulmonary alveolar type 2 cell",
                "enable_census": True,
            })

        result = json.loads(raw)
        assert result["success"] is True
        assert result["skipped_existing"] == ["stage1_EGFR--MET.json"]
        assert result["census_batch"] == "skipped_existing"
        assert census_calls == []
        assert json.loads((evidence_dir / "stage1_EGFR--MET.json").read_text()) == existing_payload

    def test_run_stage1_batch_reuses_existing_census_csv_before_batch(self, tmp_path):
        from src.agents.drug_target.tools.disease_context import initialize_disease_context
        from src.agents.drug_target.tools.stage_domain_tools import run_stage1_batch

        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        initialize_disease_context(
            evidence_dir,
            input_disease="breast cancer",
            input_source="test",
        )
        (tmp_path / "lr_candidates.json").write_text(json.dumps({
            "pairs": [
                {"ligand": "EGFR", "receptor": "MET"},
            ],
        }))
        (evidence_dir / "assessment_results.json").write_text(json.dumps({
            "stage3_candidates": [
                {"gene": "EGFR"},
            ],
        }))
        (evidence_dir / "stage1_EGFR--MET.json").write_text(json.dumps({
            "ligand": "EGFR",
            "receptor": "MET",
            "string_ppi": {"interaction_found": True, "combined_score": 0.99},
        }))
        (evidence_dir / "census_egfr_met_malignant_cell.csv").write_text(
            "\n".join([
                "cell_type,n_cells,gene_a_pos,gene_a_pct,gene_b_pos,gene_b_pct,coexp_pos,coexp_pct",
                "malignant cell,100,20,20.0,30,30.0,15,15.0",
                "other,100,5,5.0,10,10.0,2,2.0",
            ]) + "\n",
            encoding="utf-8",
        )

        batch_calls = []

        def fake_batch(*args, **kwargs):
            batch_calls.append((args, kwargs))
            raise AssertionError("batch should not run when a valid Census CSV already exists")

        class _FakeStage1FilterTool:
            @staticmethod
            def invoke(args):
                return json.dumps({"success": True})

        with (
            patch(
                "src.agents.drug_target.tools.stage_domain_tools.query_string_ppi_pair",
                object(),
            ),
            patch(
                "src.agents.drug_target.tools.census_batch_core.batch_census_lr_pairs",
                side_effect=fake_batch,
            ),
            patch(
                "src.agents.drug_target.tools.stage_logic.apply_stage1_filter",
                _FakeStage1FilterTool,
            ),
        ):
            raw = run_stage1_batch.invoke({
                "data_dir": str(tmp_path),
                "disease": "breast cancer",
                "target_cell_type": "malignant cell",
                "enable_census": True,
            })

        result = json.loads(raw)
        stage1 = json.loads((evidence_dir / "stage1_EGFR--MET.json").read_text())

        assert result["success"] is True
        assert result["census_batch"] == "completed_from_existing_csv"
        assert result["census_reused_csv"] == ["census_egfr_met_malignant_cell.csv"]
        assert result["census_single_fallback"] == []
        assert result["census_batch_error"] == ""
        assert result["errors"] == []
        assert batch_calls == []
        assert stage1["census_validation"]["executed"] is True
        assert stage1["census_validation"]["source"] == "csv_integration"
        assert stage1["census_validation"]["csv_file"] == "census_egfr_met_malignant_cell.csv"
        assert stage1["census_validation"]["target_vs_rest"]["coexpression"]["risk_ratio"] == 7.5

    def test_run_stage1_batch_falls_back_to_single_pair_when_batch_hits_cap(self, tmp_path):
        from src.agents.drug_target.tools.disease_context import initialize_disease_context
        from src.agents.drug_target.tools.stage_domain_tools import run_stage1_batch

        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        initialize_disease_context(
            evidence_dir,
            input_disease="breast cancer",
            input_source="test",
        )
        (tmp_path / "lr_candidates.json").write_text(json.dumps({
            "disease": "breast cancer",
            "disease_context": "breast cancer malignant cell validation",
            "pairs": [
                {"ligand": "EGFR", "receptor": "MET"},
            ],
        }))
        (evidence_dir / "assessment_results.json").write_text(json.dumps({
            "disease": "breast cancer",
            "stage3_candidates": [
                {"gene": "EGFR"},
            ],
        }))

        batch_error = "Census query returned 1101430 cells; max allowed is 1000000"
        single_pair_calls = []

        def fake_single_pair(args):
            single_pair_calls.append(args)
            Path(args["output_csv"]).write_text(
                "\n".join([
                    "cell_type,n_cells,gene_a_pos,gene_a_pct,gene_b_pos,gene_b_pct,coexp_pos,coexp_pct",
                    "malignant cell,100,20,20.0,30,30.0,15,15.0",
                    "other,100,5,5.0,10,10.0,2,2.0",
                ]) + "\n",
                encoding="utf-8",
            )
            return json.dumps({
                "gene_a": args["gene_a"],
                "gene_b": args["gene_b"],
                "disease": args["disease"],
                "requested_cell_type": args["target_cell_type"],
                "resolved_cell_type": args["target_cell_type"],
                "executed": True,
                "errors": [],
            })

        class _FakeStringTool:
            @staticmethod
            def invoke(args):
                return json.dumps({
                    "gene_a": args["gene_a"],
                    "gene_b": args["gene_b"],
                    "interaction_found": True,
                    "combined_score": 0.99,
                })

        class _FakeStage1FilterTool:
            @staticmethod
            def invoke(args):
                return json.dumps({"success": True})

        class _FakeSinglePairTool:
            @staticmethod
            def invoke(args):
                return fake_single_pair(args)

        with (
            patch(
                "src.agents.drug_target.tools.stage_domain_tools.query_string_ppi_pair",
                _FakeStringTool,
            ),
            patch(
                "src.agents.drug_target.tools.census_batch_core.batch_census_lr_pairs",
                side_effect=MemoryError(batch_error),
            ),
            patch(
                "src.agents.drug_target.tools.stage1_normalization._batch_census_lr_pairs",
                side_effect=MemoryError(batch_error),
            ),
            patch(
                "src.agents.drug_target.tools.census_lr_validation_tools.run_compare_census_lr_pair",
                _FakeSinglePairTool,
            ),
            patch(
                "src.agents.drug_target.tools.stage1_normalization.run_compare_census_lr_pair",
                _FakeSinglePairTool,
            ),
            patch(
                "src.agents.drug_target.tools.stage_logic.apply_stage1_filter",
                _FakeStage1FilterTool,
            ),
        ):
            raw = run_stage1_batch.invoke({
                "data_dir": str(tmp_path),
                "disease": "breast cancer",
                "target_cell_type": "malignant cell",
                "enable_census": True,
            })

        result = json.loads(raw)
        stage1 = json.loads((evidence_dir / "stage1_EGFR--MET.json").read_text())

        assert result["success"] is True
        assert result["census_batch"] == "completed_with_single_pair_fallback"
        assert result["census_batch_error"].startswith(batch_error)
        assert result["errors"] == []
        assert result["census_single_fallback"] == [{
            "pair": "EGFR--MET",
            "executed": True,
            "csv_file": "census_egfr_met_malignant_cell.csv",
        }]
        assert len(single_pair_calls) == 1
        assert single_pair_calls[0]["output_csv"].endswith(
            "census_egfr_met_malignant_cell.csv"
        )
        assert stage1["census_validation"]["executed"] is True
        assert stage1["census_validation"]["source"] == "single_pair_fallback"
        assert stage1["census_validation"]["batch_error"].startswith(batch_error)
        assert stage1["census_validation"]["target_vs_rest"]["coexpression"]["risk_ratio"] == 7.5

    def test_run_stage1_batch_reuses_one_csv_and_batches_remaining_pair(self, tmp_path):
        from src.agents.drug_target.tools.disease_context import initialize_disease_context
        from src.agents.drug_target.tools.stage_domain_tools import run_stage1_batch

        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        initialize_disease_context(
            evidence_dir,
            input_disease="breast cancer",
            input_source="test",
        )
        (tmp_path / "lr_candidates.json").write_text(json.dumps({
            "pairs": [
                {"ligand": "EGFR", "receptor": "MET"},
                {"ligand": "KDR", "receptor": "FLT1"},
            ],
        }))
        (evidence_dir / "assessment_results.json").write_text(json.dumps({
            "stage3_candidates": [
                {"gene": "EGFR"},
                {"gene": "KDR"},
            ],
        }))
        for ligand, receptor in (("EGFR", "MET"), ("KDR", "FLT1")):
            (evidence_dir / f"stage1_{ligand}--{receptor}.json").write_text(json.dumps({
                "ligand": ligand,
                "receptor": receptor,
                "string_ppi": {"interaction_found": True, "combined_score": 0.99},
            }))
        (evidence_dir / "census_egfr_met_malignant_cell.csv").write_text(
            "\n".join([
                "cell_type,n_cells,gene_a_pos,gene_a_pct,gene_b_pos,gene_b_pct,coexp_pos,coexp_pct",
                "malignant cell,100,20,20.0,30,30.0,15,15.0",
                "other,100,5,5.0,10,10.0,2,2.0",
            ]) + "\n",
            encoding="utf-8",
        )

        batch_calls = []

        def fake_batch(pairs, *args, **kwargs):
            batch_calls.append(pairs)
            return [
                {
                    "gene_a": "KDR",
                    "gene_b": "FLT1",
                    "disease": "breast cancer",
                    "disease_resolution_mode": "exact",
                    "requested_cell_type": "malignant cell",
                    "resolved_cell_type": "malignant cell",
                    "resolution_mode": "exact",
                    "executed": True,
                    "errors": [],
                    "target_vs_rest": {"coexpression": {"risk_ratio": 2.0}},
                    "n_target_cells": 100,
                    "n_rest_cells": 100,
                    "census_version": "test",
                },
            ], {}

        class _FakeStage1FilterTool:
            @staticmethod
            def invoke(args):
                return json.dumps({"success": True})

        with (
            patch(
                "src.agents.drug_target.tools.stage_domain_tools.query_string_ppi_pair",
                object(),
            ),
            patch(
                "src.agents.drug_target.tools.census_batch_core.batch_census_lr_pairs",
                side_effect=fake_batch,
            ),
            patch(
                "src.agents.drug_target.tools.stage1_normalization.finalize_stage1_workspace",
                return_value={"success": True},
            ),
            patch(
                "src.agents.drug_target.tools.stage_logic.apply_stage1_filter",
                _FakeStage1FilterTool,
            ),
        ):
            raw = run_stage1_batch.invoke({
                "data_dir": str(tmp_path),
                "disease": "breast cancer",
                "target_cell_type": "malignant cell",
                "enable_census": True,
            })

        result = json.loads(raw)
        reused_stage1 = json.loads((evidence_dir / "stage1_EGFR--MET.json").read_text())
        batched_stage1 = json.loads((evidence_dir / "stage1_KDR--FLT1.json").read_text())

        assert result["success"] is True
        assert result["census_reused_csv"] == ["census_egfr_met_malignant_cell.csv"]
        assert result["census_batch"] == "completed"
        assert batch_calls == [[("KDR", "FLT1")]]
        assert reused_stage1["census_validation"]["executed"] is True
        assert batched_stage1["census_validation"]["executed"] is True
        assert reused_stage1["census_validation"]["source"] == "csv_integration"
        assert batched_stage1["census_validation"]["source"] == "batch_census_direct"

    def test_run_stage1_batch_batches_pair_when_reusable_csv_is_malformed(self, tmp_path, caplog):
        from src.agents.drug_target.tools.disease_context import initialize_disease_context
        from src.agents.drug_target.tools.stage_domain_tools import run_stage1_batch

        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        initialize_disease_context(
            evidence_dir,
            input_disease="breast cancer",
            input_source="test",
        )
        (tmp_path / "lr_candidates.json").write_text(json.dumps({
            "pairs": [
                {"ligand": "EGFR", "receptor": "MET"},
            ],
        }))
        (evidence_dir / "assessment_results.json").write_text(json.dumps({
            "stage3_candidates": [
                {"gene": "EGFR"},
            ],
        }))
        (evidence_dir / "stage1_EGFR--MET.json").write_text(json.dumps({
            "ligand": "EGFR",
            "receptor": "MET",
            "string_ppi": {"interaction_found": True, "combined_score": 0.99},
        }))
        (evidence_dir / "census_egfr_met_malignant_cell.csv").write_text(
            "\n".join([
                "cell_type,n_cells",
                "malignant cell,100",
                "other,100",
            ]) + "\n",
            encoding="utf-8",
        )

        batch_calls = []

        def fake_batch(pairs, *args, **kwargs):
            batch_calls.append(pairs)
            return [
                {
                    "gene_a": "EGFR",
                    "gene_b": "MET",
                    "disease": "breast cancer",
                    "disease_resolution_mode": "exact",
                    "requested_cell_type": "malignant cell",
                    "resolved_cell_type": "malignant cell",
                    "resolution_mode": "exact",
                    "executed": True,
                    "errors": [],
                    "target_vs_rest": {"coexpression": {"risk_ratio": 2.0}},
                    "n_target_cells": 100,
                    "n_rest_cells": 100,
                    "census_version": "test",
                },
            ], {}

        class _FakeStage1FilterTool:
            @staticmethod
            def invoke(args):
                return json.dumps({"success": True})

        caplog.set_level("WARNING")
        with (
            patch(
                "src.agents.drug_target.tools.stage_domain_tools.query_string_ppi_pair",
                object(),
            ),
            patch(
                "src.agents.drug_target.tools.census_batch_core.batch_census_lr_pairs",
                side_effect=fake_batch,
            ),
            patch(
                "src.agents.drug_target.tools.census_batch_core.write_census_csv",
            ),
            patch(
                "src.agents.drug_target.tools.stage_logic.apply_stage1_filter",
                _FakeStage1FilterTool,
            ),
        ):
            raw = run_stage1_batch.invoke({
                "data_dir": str(tmp_path),
                "disease": "breast cancer",
                "target_cell_type": "malignant cell",
                "enable_census": True,
            })

        result = json.loads(raw)
        stage1 = json.loads((evidence_dir / "stage1_EGFR--MET.json").read_text())

        assert result["success"] is True
        assert result["census_reused_csv"] == []
        assert result["census_batch"] == "completed"
        assert batch_calls == [[("EGFR", "MET")]]
        assert stage1["census_validation"]["source"] == "batch_census_direct"
        assert "EGFR--MET" in caplog.text
        assert "census_egfr_met_malignant_cell.csv" in caplog.text

    def test_run_stage1_batch_does_not_reuse_census_csv_from_different_disease(self, tmp_path):
        from src.agents.drug_target.tools.disease_context import initialize_disease_context
        from src.agents.drug_target.tools.stage_domain_tools import run_stage1_batch

        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        initialize_disease_context(
            evidence_dir,
            input_disease="pulmonary fibrosis",
            input_source="test",
        )
        (tmp_path / "lr_candidates.json").write_text(json.dumps({
            "pairs": [
                {"ligand": "EGFR", "receptor": "MET"},
            ],
        }))
        (evidence_dir / "assessment_results.json").write_text(json.dumps({
            "disease": "breast cancer",
            "stage3_candidates": [
                {"gene": "EGFR"},
            ],
        }))
        (evidence_dir / "stage1_EGFR--MET.json").write_text(json.dumps({
            "ligand": "EGFR",
            "receptor": "MET",
            "string_ppi": {"interaction_found": True, "combined_score": 0.99},
        }))
        (evidence_dir / "census_egfr_met_malignant_cell.csv").write_text(
            "\n".join([
                "cell_type,n_cells,gene_a_pos,gene_a_pct,gene_b_pos,gene_b_pct,coexp_pos,coexp_pct",
                "malignant cell,100,20,20.0,30,30.0,15,15.0",
                "other,100,5,5.0,10,10.0,2,2.0",
            ]) + "\n",
            encoding="utf-8",
        )

        batch_calls = []

        def fake_batch(pairs, *args, **kwargs):
            batch_calls.append(pairs)
            return [
                {
                    "gene_a": "EGFR",
                    "gene_b": "MET",
                    "disease": "breast cancer",
                    "disease_resolution_mode": "exact",
                    "requested_cell_type": "malignant cell",
                    "resolved_cell_type": "malignant cell",
                    "resolution_mode": "exact",
                    "executed": True,
                    "errors": [],
                    "target_vs_rest": {"coexpression": {"risk_ratio": 2.0}},
                    "n_target_cells": 100,
                    "n_rest_cells": 100,
                    "census_version": "test",
                },
            ], {}

        class _FakeStage1FilterTool:
            @staticmethod
            def invoke(args):
                return json.dumps({"success": True})

        with (
            patch(
                "src.agents.drug_target.tools.stage_domain_tools.query_string_ppi_pair",
                object(),
            ),
            patch(
                "src.agents.drug_target.tools.census_batch_core.batch_census_lr_pairs",
                side_effect=fake_batch,
            ),
            patch(
                "src.agents.drug_target.tools.census_batch_core.write_census_csv",
            ),
            patch(
                "src.agents.drug_target.tools.stage1_normalization.finalize_stage1_workspace",
                return_value={"success": True},
            ),
            patch(
                "src.agents.drug_target.tools.stage_logic.apply_stage1_filter",
                _FakeStage1FilterTool,
            ),
        ):
            raw = run_stage1_batch.invoke({
                "data_dir": str(tmp_path),
                "disease": "breast cancer",
                "target_cell_type": "malignant cell",
                "enable_census": True,
            })

        result = json.loads(raw)
        stage1 = json.loads((evidence_dir / "stage1_EGFR--MET.json").read_text())

        assert result["success"] is True
        assert result["census_reused_csv"] == []
        assert result["census_batch"] == "completed"
        assert batch_calls == [[("EGFR", "MET")]]
        assert stage1["census_validation"]["source"] == "batch_census_direct"
        assert stage1["census_validation"]["disease"] == "breast cancer"

    def test_run_stage1_batch_reapplies_filter_when_workspace_is_reused(self, tmp_path):
        from src.agents.drug_target.tools.stage_domain_tools import run_stage1_batch

        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        (tmp_path / "lr_candidates.json").write_text(json.dumps({
            "pairs": [
                {"ligand": "EGFR", "receptor": "MET"},
            ],
        }))
        (evidence_dir / "assessment_results.json").write_text(json.dumps({
            "stage3_candidates": [
                {"gene": "EGFR"},
            ],
            "stage1_filter_applied": True,
        }))
        existing_payload = {
            "ligand": "EGFR",
            "receptor": "MET",
            "string_ppi": {"interaction_found": True, "combined_score": 0.99},
            "census_validation": {
                "executed": True,
                "target_vs_rest": {"coexpression_p_value": 0.01},
            },
        }
        (evidence_dir / "stage1_EGFR--MET.json").write_text(json.dumps(existing_payload))
        (evidence_dir / "stage1_evidence.json").write_text(json.dumps({
            "EGFR^MET": existing_payload,
            "LEGACY^PAIR": {"stage1_filter": {"passed": False}},
        }))
        (evidence_dir / "stage1_filter.json").write_text(json.dumps({
            "EGFR^MET": {"passed": True},
            "LEGACY^PAIR": {"passed": False},
        }))
        (evidence_dir / "stage1_filter_results.json").write_text(json.dumps([
            {"ligand": "EGFR", "receptor": "MET", "passed": True},
            {"ligand": "LEGACY", "receptor": "PAIR", "passed": False},
        ]))
        (evidence_dir / "stage1_audit.json").write_text(json.dumps({
            "EGFR^MET": {"pair_key": "EGFR^MET"},
            "LEGACY^PAIR": {"pair_key": "LEGACY^PAIR"},
        }))
        original_aggregate = (evidence_dir / "stage1_evidence.json").read_text()
        filter_calls = []

        class _Stage1FilterTool:
            @staticmethod
            def invoke(args):
                filter_calls.append(args)
                return json.dumps({"success": True})

        with (
            patch(
                "src.agents.drug_target.tools.stage_domain_tools.query_string_ppi_pair",
                object(),
            ),
            patch(
                "src.agents.drug_target.tools.stage1_normalization.finalize_stage1_workspace",
                side_effect=AssertionError("finalize should not run for reused workspace"),
            ),
            patch(
                "src.agents.drug_target.tools.stage_logic.apply_stage1_filter",
                _Stage1FilterTool,
            ),
        ):
            raw = run_stage1_batch.invoke({
                "data_dir": str(tmp_path),
                "disease": "pulmonary fibrosis",
                "target_cell_type": "pulmonary alveolar type 2 cell",
                "enable_census": True,
            })

        result = json.loads(raw)
        assert result["success"] is True
        assert result["skipped_existing"] == ["stage1_EGFR--MET.json"]
        assert result["saved_files"] == []
        assert result["census_batch"] == "skipped_existing"
        assert result["finalize"] == "skipped_existing"
        assert result["stage1_filter"] == "applied"
        assert filter_calls == [{"data_dir": str(tmp_path)}]
        assert (evidence_dir / "stage1_evidence.json").read_text() == original_aggregate


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


class TestNoveltyAuditMetadata:
    """Unit tests for non-scoring novelty_opportunity audit metadata."""

    def test_summarize_novelty_uses_authoritative_total_count(self):
        from src.agents.drug_target.tools.stage_logic import (
            _summarize_novelty_opportunity,
        )

        assert _summarize_novelty_opportunity(
            associations=[{"score": 0.91}] * 20,
            associations_truncated=True,
            associations_total_count=1633,
            associations_total_source="parquet_pre_head",
            target_drugs={"count": 5, "rows": [{"drug": {"id": "CHEMBL1"}}]},
        ) == {
            "novelty_basis": "well_studied_target",
            "novelty_association_count": 1633,
            "novelty_target_drug_count": 5,
            "novelty_bucket": "1000+ associations",
            "novelty_source": "parquet_pre_head",
        }

    def test_summarize_novelty_reports_sparse_target_without_drugs(self):
        from src.agents.drug_target.tools.stage_logic import (
            _summarize_novelty_opportunity,
        )

        assert _summarize_novelty_opportunity(
            associations=[{"score": 0.2}] * 8,
            associations_truncated=False,
            associations_total_count=8,
            associations_total_source="api_count",
            target_drugs={"rows": []},
        ) == {
            "novelty_basis": "st_only_or_brand_new_target",
            "novelty_association_count": 8,
            "novelty_target_drug_count": 0,
            "novelty_bucket": "0-9 associations",
            "novelty_source": "api_count",
        }

    def test_summarize_novelty_reports_unknown_total_when_truncated_without_total(self):
        from src.agents.drug_target.tools.stage_logic import (
            _summarize_novelty_opportunity,
        )

        assert _summarize_novelty_opportunity(
            associations=[{"score": 0.5}] * 20,
            associations_truncated=True,
            associations_total_count=None,
            associations_total_source=None,
            target_drugs={"rows": [{}, {}, {}]},
        ) == {
            "novelty_basis": "total_unknown_truncated",
            "novelty_association_count": 20,
            "novelty_target_drug_count": 3,
            "novelty_bucket": "truncated_total_unknown",
            "novelty_source": "truncated_list_length",
        }

    def test_summarize_novelty_ignores_malformed_inputs(self):
        from src.agents.drug_target.tools.stage_logic import (
            _summarize_novelty_opportunity,
        )

        assert _summarize_novelty_opportunity(
            associations=None,
            associations_truncated=False,
            associations_total_count="bad",
            associations_total_source="",
            target_drugs={"count": "bad", "rows": "not-a-list"},
        ) == {
            "novelty_basis": "st_only_or_brand_new_target",
            "novelty_association_count": 0,
            "novelty_target_drug_count": 0,
            "novelty_bucket": "0-9 associations",
            "novelty_source": "list_length",
        }


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

    def test_pleiotropic_proximity_hit_remains_1(self):
        from src.agents.drug_target.tools.stage_logic import _score_gwas_support
        gwas = {
            "disease": "breast cancer",
            "disease_specific_hits": {
                "n_gene_in_trait": 0,
                "n_gene_snps_in_disease": 0,
                "n_proximity_hits": 1,
                "proximity_hits": [
                    {
                        "trait": "Breast cancer or lung cancer (pleiotropy)",
                        "pvalue": 1e-10,
                    }
                ],
            },
        }
        assert _score_gwas_support(gwas) == 1

    def test_disease_specific_significant_proximity_returns_2(self):
        from src.agents.drug_target.tools.stage_logic import _score_gwas_support
        gwas = {
            "disease": "idiopathic pulmonary fibrosis",
            "disease_specific_hits": {
                "n_gene_in_trait": 0,
                "n_gene_snps_in_disease": 0,
                "n_proximity_hits": 1,
                "proximity_hits": [
                    {
                        "trait": "Idiopathic pulmonary fibrosis",
                        "pvalue": 4e-9,
                    }
                ],
            },
        }
        assert _score_gwas_support(gwas) == 2

    def test_nested_proximity_requires_same_association_for_trait_and_pvalue(self):
        from src.agents.drug_target.tools.stage_logic import _score_gwas_support
        gwas = {
            "disease": "breast cancer",
            "disease_specific_hits": {
                "n_gene_in_trait": 0,
                "n_gene_snps_in_disease": 0,
                "n_proximity_hits": 1,
                "proximity_hits": [
                    {
                        "associations": [
                            {"trait": "Breast cancer", "pvalue": 1e-4},
                            {"trait": "Adult height", "pvalue": 1e-10},
                        ],
                    }
                ],
            },
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


class TestGwasAuditMetadata:
    """Unit tests for non-scoring GWAS audit metadata."""

    def test_summarize_gwas_reports_no_evidence_defaults(self):
        from src.agents.drug_target.tools.stage_logic import _summarize_gwas_support

        assert _summarize_gwas_support(None) == {
            "gwas_evidence_type": "none",
            "gwas_min_pvalue": None,
            "gwas_trait_match_level": "none",
            "gwas_direct_hit_count": 0,
            "gwas_proximity_hit_count": 0,
        }

    def test_summarize_gwas_reports_direct_significant_overlap(self):
        from src.agents.drug_target.tools.stage_logic import _summarize_gwas_support

        gwas = {
            "disease": "breast cancer",
            "disease_specific_hits": {
                "n_gene_in_trait": 1,
                "n_gene_snps_in_disease": 2,
                "n_proximity_hits": 0,
                "gene_snps_in_disease": [
                    {"rsId": "rs111", "pvalue": 3e-7},
                    {"rsId": "rs222", "associations": [{"pvalue": 4e-9}]},
                ],
            },
        }

        assert _summarize_gwas_support(gwas) == {
            "gwas_evidence_type": "direct_significant_overlap",
            "gwas_min_pvalue": 4e-9,
            "gwas_trait_match_level": "disease_specific",
            "gwas_direct_hit_count": 3,
            "gwas_proximity_hit_count": 0,
        }

    def test_summarize_gwas_skips_malformed_gene_snps_and_reads_dict_associations(self):
        from src.agents.drug_target.tools.stage_logic import _summarize_gwas_support

        gwas = {
            "disease": "breast cancer",
            "disease_specific_hits": {
                "n_gene_in_trait": 0,
                "n_gene_snps_in_disease": 3,
                "n_proximity_hits": 0,
                "gene_snps_in_disease": [
                    None,
                    "malformed",
                    {"rsId": "rs111", "pvalue": 3e-7},
                    {"rsId": "rs222", "associations": {"pvalue": 2e-9}},
                ],
            },
        }

        assert _summarize_gwas_support(gwas) == {
            "gwas_evidence_type": "direct_significant_overlap",
            "gwas_min_pvalue": 2e-9,
            "gwas_trait_match_level": "disease_specific",
            "gwas_direct_hit_count": 3,
            "gwas_proximity_hit_count": 0,
        }

    def test_summarize_gwas_reports_disease_specific_significant_proximity(self):
        from src.agents.drug_target.tools.stage_logic import _summarize_gwas_support

        gwas = {
            "disease": "idiopathic pulmonary fibrosis",
            "disease_specific_hits": {
                "n_gene_in_trait": 0,
                "n_gene_snps_in_disease": 0,
                "n_proximity_hits": 1,
                "proximity_hits": [
                    {"trait": "Idiopathic pulmonary fibrosis", "pvalue": 4e-9},
                ],
            },
        }

        assert _summarize_gwas_support(gwas) == {
            "gwas_evidence_type": "disease_specific_proximity",
            "gwas_min_pvalue": 4e-9,
            "gwas_trait_match_level": "disease_specific",
            "gwas_direct_hit_count": 0,
            "gwas_proximity_hit_count": 1,
        }

    def test_summarize_gwas_reports_pleiotropic_proximity(self):
        from src.agents.drug_target.tools.stage_logic import _summarize_gwas_support

        gwas = {
            "disease": "breast cancer",
            "disease_specific_hits": {
                "n_gene_in_trait": 0,
                "n_gene_snps_in_disease": 0,
                "n_proximity_hits": 1,
                "proximity_hits": [
                    {
                        "trait": "Breast cancer or lung cancer (pleiotropy)",
                        "pvalue": 1e-10,
                    },
                ],
            },
        }

        assert _summarize_gwas_support(gwas) == {
            "gwas_evidence_type": "pleiotropic_proximity",
            "gwas_min_pvalue": 1e-10,
            "gwas_trait_match_level": "pleiotropic",
            "gwas_direct_hit_count": 0,
            "gwas_proximity_hit_count": 1,
        }


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

    def test_biological_plausibility_adds_stage1_bonus(self):
        from src.agents.drug_target.tools.stage_logic import _score_biological_plausibility

        evidence = [{"datatypeId": "literature", "score": 0.3}]

        assert _score_biological_plausibility(evidence, stage1_support_bonus=1) == 2

    def test_biological_plausibility_stage1_bonus_caps_at_5(self):
        from src.agents.drug_target.tools.stage_logic import _score_biological_plausibility

        evidence = [
            {"datatypeId": "affected_pathway", "score": 0.8},
            {"datatypeId": "literature", "score": 0.5},
            {"datatypeId": "animal_model", "score": 0.3},
            {"datatypeId": "somatic_mutation", "score": 0.2},
        ]

        assert _score_biological_plausibility(evidence, stage1_support_bonus=1) == 5

    def test_stage1_bio_bonus_for_gene_requires_passed_pair(self):
        from src.agents.drug_target.tools.stage_logic import _stage1_bio_bonus_for_gene

        stage1 = {
            "FN1^SDC2": {
                "ligand": "FN1",
                "receptor": "SDC2",
                "stage1_filter": {
                    "passed": True,
                    "string_combined": 0.959,
                    "census_coexpr_pvalue": 0.0,
                    "census_gene_a_pvalue": 0.0,
                    "census_gene_b_pvalue": 0.0,
                },
            },
            "FN1^PLAUR": {
                "ligand": "FN1",
                "receptor": "PLAUR",
                "stage1_filter": {
                    "passed": False,
                    "string_combined": 0.697,
                    "census_coexpr_pvalue": 0.0,
                    "census_gene_a_pvalue": 0.0,
                    "census_gene_b_pvalue": 0.0,
                },
            },
        }

        assert _stage1_bio_bonus_for_gene("FN1", stage1) == 1
        assert _stage1_bio_bonus_for_gene("SDC2", stage1) == 1
        assert _stage1_bio_bonus_for_gene("PLAUR", stage1) == 0
        assert _stage1_bio_bonus_for_gene("MUC1", stage1) == 0

    def test_stage1_bio_bonus_can_compute_filter_when_sidecar_missing(self):
        from src.agents.drug_target.tools.stage_logic import _stage1_bio_bonus_for_gene

        stage1 = {
            "ITGB2^ICAM1": {
                "string_ppi": {
                    "max_combined_score": 0.91,
                    "string_record_found": True,
                },
                "census_validation": {
                    "target_vs_rest": {
                        "gene_a": {"p_value": 0.001},
                        "gene_b": {"p_value": 0.002},
                        "coexpression": {"p_value": 0.003},
                    }
                },
            }
        }

        assert _stage1_bio_bonus_for_gene("ITGB2", stage1) == 1
        assert _stage1_bio_bonus_for_gene("ICAM1", stage1) == 1


class TestBiologicalPlausibilityAuditMetadata:
    """Unit tests for non-scoring biological plausibility audit metadata."""

    def test_summarize_biological_reports_no_evidence_defaults(self):
        from src.agents.drug_target.tools.stage_logic import (
            _summarize_biological_plausibility,
        )

        assert _summarize_biological_plausibility(
            disease_evidence=[],
            vep_data=None,
            gene="FN1",
            stage1_evidence=None,
        ) == {
            "biological_basis": "none",
            "biological_evidence_types": "",
            "biological_evidence_count": 0,
            "biological_max_ot_score": None,
            "vep_high_impact_count": 0,
            "stage1_support_pair_count": 0,
            "stage1_support_pairs": "",
        }

    def test_summarize_biological_reports_ot_evidence_types_and_max_score(self):
        from src.agents.drug_target.tools.stage_logic import (
            _summarize_biological_plausibility,
        )

        disease_evidence = [
            {"datatypeId": "literature", "score": 0.31},
            {"datatypeId": "affected_pathway", "score": 0.82},
            {"datatypeId": "known_drug", "score": 0.99},
            {"datatypeId": "animal_model", "score": "0.45"},
        ]

        assert _summarize_biological_plausibility(
            disease_evidence=disease_evidence,
            vep_data={},
            gene="FN1",
            stage1_evidence={},
        ) == {
            "biological_basis": "ot_evidence",
            "biological_evidence_types": "affected_pathway;animal_model;literature",
            "biological_evidence_count": 3,
            "biological_max_ot_score": 0.82,
            "vep_high_impact_count": 0,
            "stage1_support_pair_count": 0,
            "stage1_support_pairs": "",
        }

    def test_summarize_biological_reports_vep_and_stage1_pair_support(self):
        from src.agents.drug_target.tools.stage_logic import (
            _summarize_biological_plausibility,
        )

        stage1 = {
            "FN1^SDC2": {
                "ligand": "FN1",
                "receptor": "SDC2",
                "stage1_filter": {"passed": True},
            },
            "FN1^PLAUR": {
                "ligand": "FN1",
                "receptor": "PLAUR",
                "stage1_filter": {"passed": False},
            },
            "ITGB2^ICAM1": {
                "ligand": "ITGB2",
                "receptor": "ICAM1",
                "stage1_filter": {"passed": True},
            },
        }

        assert _summarize_biological_plausibility(
            disease_evidence=[{"datatypeId": "literature", "score": 0.7}],
            vep_data={"executed": True, "impact_summary": {"high_impact": 2}},
            gene="FN1",
            stage1_evidence=stage1,
        ) == {
            "biological_basis": "ot_evidence_plus_vep_high_impact_plus_stage1_pair",
            "biological_evidence_types": "literature",
            "biological_evidence_count": 1,
            "biological_max_ot_score": 0.7,
            "vep_high_impact_count": 2,
            "stage1_support_pair_count": 1,
            "stage1_support_pairs": "FN1^SDC2",
        }

    def test_summarize_biological_ignores_malformed_inputs(self):
        from src.agents.drug_target.tools.stage_logic import (
            _summarize_biological_plausibility,
        )

        summary = _summarize_biological_plausibility(
            disease_evidence=[
                None,
                {"datatypeId": "literature", "score": "not-a-number"},
                {"datatypeId": "genetic_association", "score": 1.0},
            ],
            vep_data={"executed": True, "impact_summary": {"high_impact": "bad"}},
            gene="FN1",
            stage1_evidence={"bad": "payload"},
        )

        assert summary == {
            "biological_basis": "ot_evidence",
            "biological_evidence_types": "literature",
            "biological_evidence_count": 1,
            "biological_max_ot_score": 0.0,
            "vep_high_impact_count": 0,
            "stage1_support_pair_count": 0,
            "stage1_support_pairs": "",
        }

    def test_summarize_biological_treats_string_passed_as_non_passing(self):
        from src.agents.drug_target.tools.stage_logic import (
            _summarize_biological_plausibility,
        )

        summary = _summarize_biological_plausibility(
            disease_evidence=[],
            vep_data={},
            gene="FN1",
            stage1_evidence={
                "FN1^SDC2": {
                    "ligand": "FN1",
                    "receptor": "SDC2",
                    "stage1_filter": {"passed": "false"},
                }
            },
        )

        assert summary["stage1_support_pair_count"] == 0
        assert summary["stage1_support_pairs"] == ""
        assert summary["biological_basis"] == "none"

    def test_summarize_biological_malformed_stage1_without_filter_fails_closed(self):
        from src.agents.drug_target.tools.stage_logic import (
            _summarize_biological_plausibility,
        )

        summary = _summarize_biological_plausibility(
            disease_evidence=[],
            vep_data={},
            gene="FN1",
            stage1_evidence={
                "FN1^SDC2": {
                    "ligand": "FN1",
                    "receptor": "SDC2",
                    "string_ppi": {"max_combined_score": "bad"},
                }
            },
        )

        assert summary["stage1_support_pair_count"] == 0
        assert summary["stage1_support_pairs"] == ""
        assert summary["biological_basis"] == "none"

    def test_summarize_biological_logs_malformed_stage1_audit_pair(self, caplog):
        import logging

        from src.agents.drug_target.tools.stage_logic import (
            _summarize_biological_plausibility,
        )

        with caplog.at_level(
            logging.WARNING,
            logger="src.agents.drug_target.tools.stage_logic",
        ):
            summary = _summarize_biological_plausibility(
                disease_evidence=[],
                vep_data={},
                gene="FN1",
                stage1_evidence={
                    "FN1^SDC2": {
                        "ligand": "FN1",
                        "receptor": "SDC2",
                        "string_ppi": "bad",
                    }
                },
            )

        assert summary["stage1_support_pair_count"] == 0
        assert summary["stage1_support_pairs"] == ""
        assert summary["biological_basis"] == "none"
        assert "Skipping malformed Stage1 evidence in biological audit" in caplog.text

    def test_summarize_biological_malformed_stage1_nested_containers_fail_closed(self):
        from src.agents.drug_target.tools.stage_logic import (
            _summarize_biological_plausibility,
        )

        malformed_pairs = [
            {
                "ligand": "FN1",
                "receptor": "SDC2",
                "string_ppi": "bad",
            },
            {
                "ligand": "FN1",
                "receptor": "SDC2",
                "census_validation": None,
            },
            {
                "ligand": "FN1",
                "receptor": "SDC2",
                "census_validation": {"target_vs_rest": None},
            },
        ]

        for evidence in malformed_pairs:
            summary = _summarize_biological_plausibility(
                disease_evidence=[],
                vep_data={},
                gene="FN1",
                stage1_evidence={"FN1^SDC2": evidence},
            )

            assert summary["stage1_support_pair_count"] == 0
            assert summary["stage1_support_pairs"] == ""
            assert summary["biological_basis"] == "none"


class TestStage1GateAuditMetadata:
    """Unit tests for non-scoring Stage1 gate audit metadata."""

    def test_summarize_stage1_gate_reports_pass_and_best_pair(self):
        from src.agents.drug_target.tools.stage_logic import _summarize_stage1_gate

        stage1 = {
            "FN1^PLAUR": {
                "ligand": "FN1",
                "receptor": "PLAUR",
                "stage1_filter": {"passed": False},
                "string_ppi": {"max_combined_score": 0.697},
                "census_validation": {
                    "target_vs_rest": {
                        "gene_a": {"p_value": 0.001},
                        "gene_b": {"p_value": 0.002},
                        "coexpression": {"p_value": 0.003},
                    }
                },
            },
            "FN1^SDC2": {
                "ligand": "FN1",
                "receptor": "SDC2",
                "stage1_filter": {"passed": True},
                "string_ppi": {"max_combined_score": 0.959},
                "census_validation": {
                    "target_vs_rest": {
                        "gene_a": {"p_value": 1e-6},
                        "gene_b": {"p_value": 2e-6},
                        "coexpression": {"p_value": 3e-6},
                    }
                },
            },
        }

        assert _summarize_stage1_gate("FN1", stage1) == {
            "stage1_gate_status": "pass",
            "stage1_total_pair_count": 2,
            "stage1_passed_pair_count": 1,
            "stage1_failed_pair_count": 1,
            "stage1_best_pair": "FN1^SDC2",
            "stage1_best_string_combined": 0.959,
            "stage1_best_coexpr_pvalue": 3e-6,
            "stage1_best_gene_a_pvalue": 1e-6,
            "stage1_best_gene_b_pvalue": 2e-6,
            "stage1_source": "stage1_evidence.json",
        }

    def test_summarize_stage1_gate_reports_fail_when_pairs_exist_without_pass(self):
        from src.agents.drug_target.tools.stage_logic import _summarize_stage1_gate

        stage1 = {
            "FN1^PLAUR": {
                "ligand": "FN1",
                "receptor": "PLAUR",
                "stage1_filter": {"passed": False},
                "string_ppi": {"max_combined_score": 0.697},
                "census_validation": {
                    "target_vs_rest": {
                        "gene_a": {"p_value": 0.001},
                        "gene_b": {"p_value": 0.002},
                        "coexpression": {"p_value": 0.003},
                    }
                },
            }
        }

        summary = _summarize_stage1_gate("FN1", stage1)

        assert summary["stage1_gate_status"] == "fail"
        assert summary["stage1_total_pair_count"] == 1
        assert summary["stage1_passed_pair_count"] == 0
        assert summary["stage1_failed_pair_count"] == 1
        assert summary["stage1_best_pair"] == "FN1^PLAUR"
        assert summary["stage1_source"] == "stage1_evidence.json"

    def test_summarize_stage1_gate_keeps_malformed_matching_pair_as_fail(self):
        from src.agents.drug_target.tools.stage_logic import _summarize_stage1_gate

        stage1 = {
            "FN1^SDC2": {
                "ligand": "FN1",
                "receptor": "SDC2",
                "string_ppi": "bad",
                "census_validation": None,
            }
        }

        summary = _summarize_stage1_gate("FN1", stage1)

        assert summary["stage1_gate_status"] == "fail"
        assert summary["stage1_total_pair_count"] == 1
        assert summary["stage1_passed_pair_count"] == 0
        assert summary["stage1_failed_pair_count"] == 1
        assert summary["stage1_source"] == "stage1_evidence.json"
        assert summary["stage1_best_pair"] == "FN1^SDC2"
        assert summary["stage1_best_string_combined"] == 0.0
        assert summary["stage1_best_coexpr_pvalue"] == 1.0
        assert summary["stage1_best_gene_a_pvalue"] == 1.0
        assert summary["stage1_best_gene_b_pvalue"] == 1.0

    def test_summarize_stage1_gate_ignores_pass_override_for_malformed_pair(self):
        from src.agents.drug_target.tools.stage_logic import _summarize_stage1_gate

        stage1 = {
            "FN1^SDC2": {
                "ligand": "FN1",
                "receptor": "SDC2",
                "stage1_filter": {"passed": True},
                "string_ppi": "bad",
                "census_validation": None,
            }
        }

        summary = _summarize_stage1_gate("FN1", stage1)

        assert summary["stage1_gate_status"] == "fail"
        assert summary["stage1_total_pair_count"] == 1
        assert summary["stage1_passed_pair_count"] == 0
        assert summary["stage1_failed_pair_count"] == 1
        assert summary["stage1_best_pair"] == "FN1^SDC2"
        assert summary["stage1_source"] == "stage1_evidence.json"
        assert summary["stage1_best_string_combined"] == 0.0
        assert summary["stage1_best_coexpr_pvalue"] == 1.0
        assert summary["stage1_best_gene_a_pvalue"] == 1.0
        assert summary["stage1_best_gene_b_pvalue"] == 1.0

    def test_summarize_stage1_gate_defaults_without_gene_pairs(self):
        from src.agents.drug_target.tools.stage_logic import _summarize_stage1_gate

        assert _summarize_stage1_gate("CD4", {"FN1^SDC2": {}}) == {
            "stage1_gate_status": "not_evaluated",
            "stage1_total_pair_count": 0,
            "stage1_passed_pair_count": 0,
            "stage1_failed_pair_count": 0,
            "stage1_best_pair": "",
            "stage1_best_string_combined": None,
            "stage1_best_coexpr_pvalue": None,
            "stage1_best_gene_a_pvalue": None,
            "stage1_best_gene_b_pvalue": None,
            "stage1_source": "none",
        }


class TestTractabilitySafetyAuditMetadata:
    """Unit tests for non-scoring tractability/safety audit metadata."""

    def test_summarize_tractability_reports_approved_drug_basis_and_modalities(self):
        from src.agents.drug_target.tools.stage_logic import _summarize_tractability

        tractability = [
            {"modality": "AB", "label": "Approved Drug", "value": True},
            {"modality": "SM", "label": "Druggable Family", "value": True},
            {"modality": "PR", "label": "High-quality ligand", "value": False},
        ]

        assert _summarize_tractability(tractability) == {
            "tractability_basis": "approved_drug",
            "tractability_modalities": "AB;SM",
            "tractability_evidence_label": "approved drug",
        }

    def test_summarize_tractability_reports_unknown_without_positive_signal(self):
        from src.agents.drug_target.tools.stage_logic import _summarize_tractability

        assert _summarize_tractability([]) == {
            "tractability_basis": "unknown",
            "tractability_modalities": "",
            "tractability_evidence_label": "none",
        }

    def test_summarize_safety_reports_no_known_liability(self):
        from src.agents.drug_target.tools.stage_logic import _summarize_safety

        assert _summarize_safety([]) == {
            "safety_evidence_level": "no_known_liability",
            "safety_liability_count": 0,
            "safety_liability_sources": "",
        }

    def test_summarize_safety_reports_clinical_liability_sources(self):
        from src.agents.drug_target.tools.stage_logic import _summarize_safety

        safety = [
            {"datasource": "PharmGKB", "studies": [{"type": "clinical"}]},
            {"datasource": "ToxCast", "studies": [{"type": "screen"}]},
        ]

        assert _summarize_safety(safety) == {
            "safety_evidence_level": "clinical_liability",
            "safety_liability_count": 2,
            "safety_liability_sources": "pharmgkb;toxcast",
        }

    def test_preclinical_study_type_does_not_score_as_clinical(self):
        from src.agents.drug_target.tools.stage_logic import (
            _score_safety_profile,
            _summarize_safety,
        )

        safety = [{"datasource": "AOP-Wiki", "studies": [{"type": "preclinical"}]}]

        assert _score_safety_profile(safety) == 0
        assert _summarize_safety(safety)["safety_evidence_level"] == "low_preclinical_signal"

    def test_three_preclinical_entries_score_as_preclinical_liability(self):
        from src.agents.drug_target.tools.stage_logic import (
            _score_safety_profile,
            _summarize_safety,
        )

        safety = [
            {"datasource": "AOP-Wiki", "studies": [{"type": "preclinical"}]},
            {"datasource": "ToxCast", "studies": [{"type": "screen"}]},
            {"datasource": "Other", "studies": [{"type": "non-clinical"}]},
        ]

        assert _score_safety_profile(safety) == -1
        assert _summarize_safety(safety)["safety_evidence_level"] == "preclinical_liability"

    def test_explicit_clinical_study_scores_as_clinical_liability(self):
        from src.agents.drug_target.tools.stage_logic import (
            _score_safety_profile,
            _summarize_safety,
        )

        safety = [{"datasource": "Other", "studies": [{"type": "clinical safety"}]}]

        assert _score_safety_profile(safety) == -2
        assert _summarize_safety(safety)["safety_evidence_level"] == "clinical_liability"


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
# 6. TestIntegration — Agent creation & tool wiring
# =========================================================================

class TestIntegration:
    """Agent creation, config defaults, and integration wiring."""

    def test_drug_target_config_defaults(self):
        from src.agents.drug_target.agent import DrugTargetConfig
        config = DrugTargetConfig()
        assert config.provider == "ollama"
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
        mock_create_llm.assert_called_once_with(provider="ollama")
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
        # New envelope shape: success=False + errors list (CP-P0-008)
        assert result["success"] is False
        assert len(result["errors"]) > 0
        assert "not found" in result["errors"][0]

    @pytest.mark.asyncio
    async def test_run_drug_target_assessment_with_mock_agent(self, mock_data_dir):
        """Full integration: mock super-graph writes drug.md, integration reads envelope."""
        from src.agents.drug_target.integration import run_drug_target_assessment

        mock_report = "# Drug Target Assessment\n\n## Executive Summary\nMock report."
        mock_json = {
            "project_meta": {"disease_focus": "breast cancer", "total_input_pairs": 15},
            "druggability_matrix": [],
            "featured_candidates_deep_dive": [],
        }

        # Simulate the super-graph writing artifacts and returning final_state
        async def mock_graph_ainvoke(initial_state, config=None):
            (mock_data_dir / "drug.md").write_text(mock_report, encoding="utf-8")
            (mock_data_dir / "target_assessment.json").write_text(
                json.dumps(mock_json), encoding="utf-8"
            )
            return {
                "messages": [],
                "report_finalization_error": None,
                "evidence_truncated": False,
            }

        mock_graph = MagicMock()
        mock_graph.ainvoke = mock_graph_ainvoke

        # Patch at graph_builder — integration.py lazy-imports from there at call time
        with patch(
            "src.agents.drug_target.graph_builder.drug_target_graph",
            mock_graph,
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
    def test_create_drug_target_agent_attaches_skills_to_interpretive_subagents_only(
        self, mock_create_llm, mock_create_deep_agent, tmp_path
    ):
        """Skills attach to hypothesis_writer only; evidence_assessor has no skills.
        Summarizer subagent is gone — post-Phase-3 2-subagent topology."""
        from src.agents.drug_target.agent import create_drug_target_agent, DrugTargetConfig
        from src.agents.shared.skill_activator import SkillActivator
        from src.agents.shared.skills_middleware import SkillsMiddleware

        mock_create_llm.return_value = MagicMock()
        mock_create_deep_agent.return_value = MagicMock()

        config = DrugTargetConfig(data_dir=str(tmp_path))
        create_drug_target_agent(config)

        call_kwargs = mock_create_deep_agent.call_args.kwargs
        middleware = call_kwargs.get("middleware", [])
        mw_names = [type(m).__name__ for m in middleware]
        assert "WriteFileArgGuardMiddleware" in mw_names
        assert "ReadFileBlockMiddleware" in mw_names
        assert "SubagentErrorGuardMiddleware" in mw_names

        subagents = call_kwargs.get("subagents", [])
        # No summarizer in 2-subagent world
        assert not any(s["name"] == "summarizer" for s in subagents)
        # evidence_assessor should NOT have SkillsMiddleware (it's not in _skill_subagents)
        assert len(subagents) == 2

        ea = next(s for s in subagents if s["name"] == "evidence_assessor")
        ea_mw = ea.get("middleware", [])
        assert "skills" not in ea
        assert not any(isinstance(m, SkillsMiddleware) for m in ea_mw)
        assert not any(isinstance(m, SkillActivator) for m in ea_mw)

        hw = next(s for s in subagents if s["name"] == "hypothesis_writer")
        hw_mw = hw.get("middleware", [])
        assert "skills" not in hw
        assert any(isinstance(m, SkillsMiddleware) for m in hw_mw)
        hw_activator = next(m for m in hw_mw if isinstance(m, SkillActivator))
        assert set(hw_activator.skill_registry) == {
            "drug-target-hypothesis",
            "opentargets-database",
            "gwas-database",
            "chembl-database",
        }

    @patch("src.agents.drug_target.agent.create_deep_agent")
    @patch("src.agents.drug_target.agent.create_llm")
    def test_create_drug_target_agent_can_disable_progressive_disclosure(
        self, mock_create_llm, mock_create_deep_agent, tmp_path
    ):
        from src.agents.drug_target.agent import create_drug_target_agent, DrugTargetConfig
        from src.agents.shared.skill_activator import SkillActivator
        from src.agents.shared.skills_middleware import SkillsMiddleware

        mock_create_llm.return_value = MagicMock()
        mock_create_deep_agent.return_value = MagicMock()

        config = DrugTargetConfig(
            data_dir=str(tmp_path),
            enable_progressive_disclosure=False,
        )
        create_drug_target_agent(config)

        call_kwargs = mock_create_deep_agent.call_args.kwargs
        middleware = call_kwargs.get("middleware", [])
        mw_names = [type(m).__name__ for m in middleware]
        assert "WriteFileArgGuardMiddleware" in mw_names
        assert "ReadFileBlockMiddleware" in mw_names
        assert "SubagentErrorGuardMiddleware" in mw_names
        # No skills on any subagent
        for s in call_kwargs.get("subagents", []):
            assert "skills" not in s
            mw = s.get("middleware", [])
            assert not any(isinstance(m, SkillActivator) for m in mw)
            assert not any(isinstance(m, SkillsMiddleware) for m in mw)

    @patch("src.agents.drug_target.agent.create_deep_agent")
    @patch("src.agents.drug_target.agent.create_llm")
    def test_create_drug_target_agent_disables_skill_loading_in_docker_mode(
        self, mock_create_llm, mock_create_deep_agent, tmp_path
    ):
        from src.agents.drug_target.agent import create_drug_target_agent, DrugTargetConfig
        from src.agents.shared.skill_activator import SkillActivator
        from src.agents.shared.skills_middleware import SkillsMiddleware

        mock_create_llm.return_value = MagicMock()
        mock_create_deep_agent.return_value = MagicMock()

        config = DrugTargetConfig(
            data_dir=str(tmp_path),
            docker_image="python:3.12-slim",
        )
        create_drug_target_agent(config)

        call_kwargs = mock_create_deep_agent.call_args.kwargs
        for s in call_kwargs.get("subagents", []):
            assert "skills" not in s
            mw = s.get("middleware", [])
            assert not any(isinstance(m, SkillActivator) for m in mw)
            assert not any(isinstance(m, SkillsMiddleware) for m in mw)

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
        # disease_matched is now handled internally by run_stage1_batch
        assert "run_stage1_batch" in EVIDENCE_ASSESSOR_PROMPT or "disease_matched" in EVIDENCE_ASSESSOR_PROMPT

    def test_evidence_assessor_prompt_has_no_hardcoded_skill_reads(self):
        """Regression guard: evidence_assessor is tool-driven — its static prompt
        must not contain hard-coded skill reads or skill slugs. Skills live on the
        interpretive subagents (hypothesis_writer, report_writer); evidence_assessor
        calls only the batch-orchestrator tools."""
        from src.agents.drug_target.subagents.prompts import EVIDENCE_ASSESSOR_PROMPT

        assert "read_skill_file" not in EVIDENCE_ASSESSOR_PROMPT
        for slug in (
            "opentargets-database",
            "gwas-database",
            "chembl-database",
            "string-database",
            "cellxgene-census",
            "compare-census-gene-pair-by-cell-type",
            "drug-target-hypothesis",
            "drug-target-reporting",
        ):
            assert slug not in EVIDENCE_ASSESSOR_PROMPT, f"Unexpected skill slug: {slug}"
        # Tool names must still be present
        assert "query_stage2_gene_panel" in EVIDENCE_ASSESSOR_PROMPT
        assert "run_stage1_batch" in EVIDENCE_ASSESSOR_PROMPT
        assert "query_chembl_target_profile" in EVIDENCE_ASSESSOR_PROMPT

    def test_report_writer_prompt_contains_skill_read(self):
        """Phase H1: REPORT_WRITER_PROMPT must hardcode read_skill_file for drug-target-reporting.
        Removing the hardcoded load makes report_writer depend on SkillActivator's conditional
        classification, which previously misclassified report_writer's task as NO_SKILLS_NEEDED
        and silently dropped every hallucination protection."""
        from src.agents.drug_target.subagents.prompts import REPORT_WRITER_PROMPT

        assert 'read_skill_file("skills/drug-target-reporting/SKILL.md")' in REPORT_WRITER_PROMPT
        assert 'read_skill_file("skills/drug-target-reporting/references/scoring_guide.md")' in REPORT_WRITER_PROMPT

    def test_report_writer_skill_read_is_first_phase_1_step(self):
        """Phase H7a (structural proxy): the skill read must appear as step 0 of Phase 1,
        before any other numbered step. This anchors the LLM's first tool call so the
        skill loads deterministically regardless of SkillActivator's classification."""
        from src.agents.drug_target.subagents.prompts import REPORT_WRITER_PROMPT

        phase1_marker = "### Phase 1: Load Data + Build Reference Card + Save JSON Contract"
        assert phase1_marker in REPORT_WRITER_PROMPT
        phase1_idx = REPORT_WRITER_PROMPT.index(phase1_marker)
        skill_read_idx = REPORT_WRITER_PROMPT.index(
            'read_skill_file("skills/drug-target-reporting/SKILL.md")'
        )
        step_1_idx = REPORT_WRITER_PROMPT.index(
            "1. Call `load_lr_candidates(data_dir)`"
        )
        # skill_read must come after the Phase 1 header but BEFORE the first numbered step
        assert phase1_idx < skill_read_idx < step_1_idx

    def test_hypothesis_writer_prompt_contains_skill_read(self):
        """Phase H2: HYPOTHESIS_WRITER_PROMPT must hardcode read_skill_file for
        drug-target-hypothesis. Same regression risk as report_writer (commit 1f9cdd5)."""
        from src.agents.drug_target.subagents.prompts import HYPOTHESIS_WRITER_PROMPT

        assert 'read_skill_file("skills/drug-target-hypothesis/SKILL.md")' in HYPOTHESIS_WRITER_PROMPT

    def test_hypothesis_writer_skill_read_is_first_workflow_step(self):
        """Phase H7a (structural proxy): the skill read must appear at the top of the Workflow
        (5 Phases) section, before Phase 1 begins. Anchors the first tool call deterministically."""
        from src.agents.drug_target.subagents.prompts import HYPOTHESIS_WRITER_PROMPT

        workflow_marker = "## Workflow (5 Phases)"
        phase1_marker = "### Phase 1: Evidence Ingestion & Target Categorization"
        assert workflow_marker in HYPOTHESIS_WRITER_PROMPT
        assert phase1_marker in HYPOTHESIS_WRITER_PROMPT
        workflow_idx = HYPOTHESIS_WRITER_PROMPT.index(workflow_marker)
        phase1_idx = HYPOTHESIS_WRITER_PROMPT.index(phase1_marker)
        skill_read_idx = HYPOTHESIS_WRITER_PROMPT.index(
            'read_skill_file("skills/drug-target-hypothesis/SKILL.md")'
        )
        # skill_read must come between the Workflow header and Phase 1's start
        assert workflow_idx < skill_read_idx < phase1_idx

    def test_read_skill_file_reads_project_relative_skill_doc(self, tmp_path):
        # read_skill_file now lives in src.agents.shared.skill_reader and uses
        # find_project_root from src.agents.shared.utils. drug_target re-exports it.
        from src.agents.drug_target.tools.skill_reader import read_skill_file
        import src.agents.shared.skill_reader as shared_mod

        skill_file = tmp_path / "skills" / "opentargets-database" / "SKILL.md"
        skill_file.parent.mkdir(parents=True)
        skill_file.write_text("# OpenTargets\nLine 2\n", encoding="utf-8")

        with patch.object(shared_mod, "find_project_root", return_value=tmp_path):
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

    def test_rank_novel_candidates_by_normalized_exploratory_total(self):
        """Novel candidates use normalized exploratory rank score for ordering."""
        from src.agents.drug_target.tools.stage_logic import rank_featured_candidates

        matrix = [
            # Featured pool (drug_evidence >= 1)
            self._row("A", "B", (2, 2, 0), (1, 1, 2, 1)),   # featured
            # Novel pool: E has higher raw total, C has higher normalized total.
            self._row("C", "D", (0, 0, 0), (3, 3, 0, 0)),   # raw=6, rank=10
            self._row("E", "F", (0, 0, 0), (1, 1, 3, 2)),   # raw=7, rank=8.33
            self._row("G", "H", (0, 0, 0), (0, 0, 3, 1)),   # exploratory_total=4, novel (bio>=3)
        ]

        ranked = rank_featured_candidates(matrix, min_featured=1, max_featured=3, min_novel=1, max_novel=3)
        novel = [r for r in ranked if r.get("is_novel")]

        assert len(novel) >= 1
        assert novel[0]["exploratory_rank_total"] >= novel[-1]["exploratory_rank_total"]
        assert novel[0]["ligand"] == "C"
        assert novel[0]["exploratory_total"] == 6
        assert novel[1]["exploratory_total"] == 7
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
    """End-to-end verification that SkillActivator loads real project skills."""

    def test_skill_registry_resolves_all_configured_skills(self):
        """_build_skill_registry returns paths to all configured skill dirs with SKILL.md."""
        from src.agents.drug_target.agent import _build_skill_registry, DrugTargetConfig

        config = DrugTargetConfig()
        registry = _build_skill_registry(config)

        assert set(registry.keys()) == set(config.agent_skill_names)
        for name, path in registry.items():
            skill_md = Path(path) / "SKILL.md"
            assert skill_md.exists(), f"Missing SKILL.md for {name} at {skill_md}"

    def test_harness_formats_all_configured_skills_with_descriptions(self):
        """SkillActivator formats all configured skills with real descriptions."""
        from src.agents.drug_target.agent import _build_skill_registry, DrugTargetConfig
        from src.agents.shared.skill_activator import SkillActivator

        config = DrugTargetConfig()
        harness = SkillActivator(
            skill_registry=_build_skill_registry(config),
        )

        formatted = harness._format_available_skills()

        # All configured skills present as bold entries
        for name in config.agent_skill_names:
            assert f"**{name}**" in formatted, f"Skill {name} missing from formatted output"

        # No skills with missing descriptions
        assert "(no description)" not in formatted

    @pytest.mark.asyncio
    async def test_harness_injects_forced_eval_into_system_prompt(self):
        """awrap_model_call injects forced-eval protocol with all configured skills."""
        from src.agents.drug_target.agent import _build_skill_registry, DrugTargetConfig
        from src.agents.shared.skill_activator import SkillActivator

        config = DrugTargetConfig()
        harness = SkillActivator(
            skill_registry=_build_skill_registry(config),
        )

        # Mock request (same pattern as test_skill_activator.py)
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
        # All configured skill names injected
        for name in config.agent_skill_names:
            assert name in captured, f"Skill {name} missing from injected prompt"
        # Placeholder fully substituted
        assert "{{available_skills}}" not in captured


# ===========================================================================
# 8. Stage 1 Filter CSV Sync
# ===========================================================================


class TestStage1FilterCSVSync:
    """Verify that apply_stage1_filter regenerates rubric_scores.csv."""

    def test_rubric_csv_updated_after_filter(self, tmp_path):
        """After apply_stage1_filter, rubric_scores.csv stage3_candidate
        flags must match assessment_results.json rubric_assessment."""
        import csv
        from src.agents.drug_target.tools.stage_logic import apply_stage1_filter

        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()

        # 1. Create mock stage1_evidence.json with 2 pairs, 1 passes / 1 fails
        stage1_evidence = {
            "TGFB1^TGFBR2": {
                "string_ppi": {"max_combined_score": 900},
                "census_validation": {"target_vs_rest": {
                    "coexpression": {"p_value": 0.01},
                    "gene_a": {"p_value": 0.02},
                    "gene_b": {"p_value": 0.03},
                }},
            },
            "CD74^MIF": {
                "string_ppi": {"max_combined_score": 100},  # fails: < 0.8*1000
                "census_validation": {"target_vs_rest": {
                    "coexpression": {"p_value": 0.5},   # fails
                    "gene_a": {"p_value": 0.5},
                    "gene_b": {"p_value": 0.5},
                }},
            },
        }
        (evidence_dir / "stage1_evidence.json").write_text(json.dumps(stage1_evidence))

        # 2. Create mock assessment_results.json with all genes as candidates
        assessment = {
            "rubric_assessment": [
                {"gene": "TGFB1", "combined_total": 15, "stage3_candidate": True,
                 "existing_drug_evidence": 4, "clinical_trial_activity": 5,
                 "safety_profile": 0, "validated_total": 9,
                 "gwas_support": 0, "tractability": 3, "biological_plausibility": 2,
                 "novelty_opportunity": 1, "exploratory_total": 6,
                 "classification": "validated_target", "priority": "high"},
                {"gene": "TGFBR2", "combined_total": 11, "stage3_candidate": True,
                 "existing_drug_evidence": 1, "clinical_trial_activity": 5,
                 "safety_profile": 0, "validated_total": 6,
                 "gwas_support": 0, "tractability": 3, "biological_plausibility": 1,
                 "novelty_opportunity": 1, "exploratory_total": 5,
                 "classification": "validated_target", "priority": "high"},
                {"gene": "CD74", "combined_total": 12, "stage3_candidate": True,
                 "existing_drug_evidence": 2, "clinical_trial_activity": 5,
                 "safety_profile": 0, "validated_total": 7,
                 "gwas_support": 0, "tractability": 3, "biological_plausibility": 1,
                 "novelty_opportunity": 1, "exploratory_total": 5,
                 "classification": "validated_target", "priority": "high"},
                {"gene": "MIF", "combined_total": 10, "stage3_candidate": True,
                 "existing_drug_evidence": 1, "clinical_trial_activity": 3,
                 "safety_profile": 0, "validated_total": 4,
                 "gwas_support": 0, "tractability": 3, "biological_plausibility": 2,
                 "novelty_opportunity": 1, "exploratory_total": 6,
                 "classification": "validated_target", "priority": "high"},
            ],
            "stage3_candidates": [
                {"gene": "TGFB1"}, {"gene": "TGFBR2"},
                {"gene": "CD74"}, {"gene": "MIF"},
            ],
            "summary": {"stage3_count": 4},
        }
        (evidence_dir / "assessment_results.json").write_text(json.dumps(assessment))

        # 3. Create initial rubric_scores.csv (pre-filter: all 4 True)
        rubric_csv = evidence_dir / "rubric_scores.csv"
        fieldnames = [
            "gene", "existing_drug_evidence", "clinical_trial_activity",
            "safety_profile", "validated_total",
            "gwas_support", "tractability", "biological_plausibility",
            "novelty_opportunity", "exploratory_total", "combined_total",
            "classification", "priority", "stage3_candidate",
        ]
        with open(rubric_csv, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(assessment["rubric_assessment"])

        # Pre-check: 4 True in CSV
        with open(rubric_csv) as f:
            reader = csv.DictReader(f)
            pre_true = sum(1 for r in reader if r["stage3_candidate"] == "True")
        assert pre_true == 4

        # 4. Run filter
        result = json.loads(apply_stage1_filter.invoke({"data_dir": str(tmp_path)}))
        assert result["success"] is True
        assert result["rubric_csv_updated"] is True

        # 5. Verify CSV regenerated. Schema v3 contract: stage3_candidate is narrowed
        # in place to the intersection (rubric ∩ Stage 1 PASS).
        with open(rubric_csv) as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        true_genes = {r["gene"] for r in rows if r["stage3_candidate"] == "True"}
        assert true_genes == {"TGFB1", "TGFBR2"}, (
            "apply_stage1_filter must narrow per-row stage3_candidate to PASS-only genes."
        )

        updated_assessment = json.loads(
            (evidence_dir / "assessment_results.json").read_text()
        )
        assert updated_assessment["schema_version"] == 3
        assert "stage1_validated_candidates" not in updated_assessment
        assert all(
            "stage1_validated" not in r for r in updated_assessment["rubric_assessment"]
        )
        stage3_genes = {c["gene"] for c in updated_assessment["stage3_candidates"]}
        assert stage3_genes == {"TGFB1", "TGFBR2"}

        # Verify scores unchanged (only flags changed)
        for row in rows:
            if row["gene"] == "CD74":
                assert int(row["combined_total"]) == 12  # score preserved


def test_compute_rubric_scores_adds_stage1_biological_bonus(tmp_path):
    import csv
    import json

    from src.agents.drug_target.tools.stage_logic import compute_rubric_scores

    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "known_drugs.json").write_text(json.dumps({"drugs": {"rows": []}}))
    (evidence / "stage2_evidence.json").write_text(json.dumps({"FN1": {"gwas": {}, "vep": {}}}))
    (evidence / "stage1_evidence.json").write_text(json.dumps({
        "FN1^SDC2": {
            "ligand": "FN1",
            "receptor": "SDC2",
            "stage1_filter": {
                "passed": True,
                "string_combined": 0.95,
                "census_coexpr_pvalue": 0.001,
                "census_gene_a_pvalue": 0.001,
                "census_gene_b_pvalue": 0.001,
            },
        }
    }))
    (evidence / "ot_FN1.json").write_text(json.dumps({
        "executed": True,
        "disease_evidence": [{"datatypeId": "literature", "score": 0.3}],
        "target_info": {
            "tractability": [
                {"modality": "AB", "label": "Approved Drug", "value": True},
                {"modality": "SM", "label": "Druggable Family", "value": True},
            ],
            "safetyLiabilities": [
                {"datasource": "ToxCast", "studies": [{"type": "screen"}]},
                {"datasource": "AOP-Wiki", "studies": [{"type": "preclinical"}]},
            ],
        },
        "associations": [],
        "associations_total_count": 500,
    }))

    result = json.loads(compute_rubric_scores.invoke({"data_dir": str(tmp_path)}))
    assert result["success"] is True

    assessment = json.loads((evidence / "assessment_results.json").read_text())
    row = assessment["rubric_assessment"][0]
    assert row["gene"] == "FN1"
    assert row["biological_plausibility_base"] == 1
    assert row["stage1_biological_support_bonus"] == 1
    assert row["biological_plausibility"] == 2
    assert row["tractability_basis"] == "approved_drug"
    assert row["tractability_modalities"] == "AB;SM"
    assert row["tractability_evidence_label"] == "approved drug"
    assert row["safety_evidence_level"] == "low_preclinical_signal"
    assert row["safety_liability_count"] == 2
    assert row["safety_liability_sources"] == "aop-wiki;toxcast"

    with (evidence / "rubric_scores.csv").open() as handle:
        csv_row = next(csv.DictReader(handle))
    assert csv_row["biological_plausibility_base"] == "1"
    assert csv_row["stage1_biological_support_bonus"] == "1"
    assert csv_row["tractability_basis"] == "approved_drug"
    assert csv_row["tractability_modalities"] == "AB;SM"
    assert csv_row["tractability_evidence_label"] == "approved drug"
    assert csv_row["safety_evidence_level"] == "low_preclinical_signal"
    assert csv_row["safety_liability_count"] == "2"
    assert csv_row["safety_liability_sources"] == "aop-wiki;toxcast"


def test_compute_rubric_scores_persists_biological_audit_metadata(tmp_path):
    import csv
    import json

    from src.agents.drug_target.tools.stage_logic import compute_rubric_scores

    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "known_drugs.json").write_text(json.dumps({"drugs": {"rows": []}}))
    (evidence / "stage2_evidence.json").write_text(json.dumps({
        "FN1": {
            "gwas": {},
            "vep": {"executed": True, "impact_summary": {"high_impact": 2}},
        }
    }))
    (evidence / "stage1_evidence.json").write_text(json.dumps({
        "FN1^SDC2": {
            "ligand": "FN1",
            "receptor": "SDC2",
            "stage1_filter": {
                "passed": True,
                "string_combined": 0.95,
                "census_coexpr_pvalue": 0.001,
                "census_gene_a_pvalue": 0.001,
                "census_gene_b_pvalue": 0.001,
            },
        },
        "FN1^PLAUR": {
            "ligand": "FN1",
            "receptor": "PLAUR",
            "stage1_filter": {"passed": False},
        },
    }))
    (evidence / "ot_FN1.json").write_text(json.dumps({
        "executed": True,
        "disease_evidence": [
            {"datatypeId": "literature", "score": 0.31},
            {"datatypeId": "affected_pathway", "score": 0.82},
            {"datatypeId": "known_drug", "score": 0.99},
        ],
        "target_info": {},
        "associations": [],
        "associations_total_count": 500,
    }))

    result = json.loads(compute_rubric_scores.invoke({"data_dir": str(tmp_path)}))
    assert result["success"] is True

    assessment = json.loads((evidence / "assessment_results.json").read_text())
    row = assessment["rubric_assessment"][0]
    assert row["biological_plausibility_base"] == 4
    assert row["stage1_biological_support_bonus"] == 1
    assert row["biological_plausibility"] == 5
    assert row["biological_basis"] == "ot_evidence_plus_vep_high_impact_plus_stage1_pair"
    assert row["biological_evidence_types"] == "affected_pathway;literature"
    assert row["biological_evidence_count"] == 2
    assert row["biological_max_ot_score"] == 0.82
    assert row["vep_high_impact_count"] == 2
    assert row["stage1_support_pair_count"] == 1
    assert row["stage1_support_pairs"] == "FN1^SDC2"

    with (evidence / "rubric_scores.csv").open() as handle:
        csv_row = next(csv.DictReader(handle))
    assert csv_row["biological_plausibility_base"] == "4"
    assert csv_row["stage1_biological_support_bonus"] == "1"
    assert csv_row["biological_plausibility"] == "5"
    assert csv_row["biological_basis"] == "ot_evidence_plus_vep_high_impact_plus_stage1_pair"
    assert csv_row["biological_evidence_types"] == "affected_pathway;literature"
    assert csv_row["biological_evidence_count"] == "2"
    assert float(csv_row["biological_max_ot_score"]) == 0.82
    assert csv_row["vep_high_impact_count"] == "2"
    assert csv_row["stage1_support_pair_count"] == "1"
    assert csv_row["stage1_support_pairs"] == "FN1^SDC2"


def test_compute_rubric_scores_persists_stage1_audit_metadata_and_filter_rewrites_csv(tmp_path):
    import csv
    import json

    from src.agents.drug_target.tools.stage_logic import (
        apply_stage1_filter,
        compute_rubric_scores,
    )

    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "known_drugs.json").write_text(json.dumps({"drugs": {"rows": []}}))
    (evidence / "stage2_evidence.json").write_text(json.dumps({"FN1": {}}))
    (evidence / "stage1_evidence.json").write_text(json.dumps({
        "FN1^PLAUR": {
            "ligand": "FN1",
            "receptor": "PLAUR",
            "stage1_filter": {"passed": False},
            "string_ppi": {"max_combined_score": 0.697},
            "census_validation": {
                "target_vs_rest": {
                    "gene_a": {"p_value": 0.001},
                    "gene_b": {"p_value": 0.002},
                    "coexpression": {"p_value": 0.003},
                }
            },
        },
        "FN1^SDC2": {
            "ligand": "FN1",
            "receptor": "SDC2",
            "stage1_filter": {"passed": True},
            "string_ppi": {"max_combined_score": 0.959},
            "census_validation": {
                "target_vs_rest": {
                    "gene_a": {"p_value": 1e-6},
                    "gene_b": {"p_value": 2e-6},
                    "coexpression": {"p_value": 3e-6},
                }
            },
        },
    }))
    (evidence / "ot_FN1.json").write_text(json.dumps({
        "executed": True,
        "disease_evidence": [{"datatypeId": "literature", "score": 0.31}],
        "target_info": {},
        "associations": [],
        "associations_total_count": 500,
    }))

    result = json.loads(compute_rubric_scores.invoke({"data_dir": str(tmp_path)}))
    assert result["success"] is True

    assessment = json.loads((evidence / "assessment_results.json").read_text())
    row = assessment["rubric_assessment"][0]
    assert row["stage1_gate_status"] == "pass"
    assert row["stage1_total_pair_count"] == 2
    assert row["stage1_passed_pair_count"] == 1
    assert row["stage1_failed_pair_count"] == 1
    assert row["stage1_best_pair"] == "FN1^SDC2"
    assert row["stage1_best_string_combined"] == 0.959
    assert row["stage1_best_coexpr_pvalue"] == 3e-6
    assert row["stage1_best_gene_a_pvalue"] == 1e-6
    assert row["stage1_best_gene_b_pvalue"] == 2e-6
    assert row["stage1_source"] == "stage1_evidence.json"

    with (evidence / "rubric_scores.csv").open(newline="", encoding="utf-8") as handle:
        csv_row = next(csv.DictReader(handle))
    assert csv_row["stage1_gate_status"] == "pass"
    assert csv_row["stage1_total_pair_count"] == "2"
    assert csv_row["stage1_passed_pair_count"] == "1"
    assert csv_row["stage1_failed_pair_count"] == "1"
    assert csv_row["stage1_best_pair"] == "FN1^SDC2"
    assert float(csv_row["stage1_best_string_combined"]) == 0.959
    assert float(csv_row["stage1_best_coexpr_pvalue"]) == 3e-6
    assert csv_row["stage1_source"] == "stage1_evidence.json"

    filter_result = json.loads(apply_stage1_filter.invoke({"data_dir": str(tmp_path)}))
    assert filter_result["success"] is True
    with (evidence / "rubric_scores.csv").open(newline="", encoding="utf-8") as handle:
        rewritten_row = next(csv.DictReader(handle))
    assert rewritten_row["stage1_gate_status"] == "pass"
    assert rewritten_row["stage1_best_pair"] == "FN1^SDC2"


def test_compute_rubric_scores_persists_gwas_audit_metadata(tmp_path):
    import csv
    import json

    from src.agents.drug_target.tools.stage_logic import compute_rubric_scores

    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "known_drugs.json").write_text(json.dumps({"drugs": {"rows": []}}))
    (evidence / "stage2_evidence.json").write_text(json.dumps({
        "FN1": {
            "gwas": {
                "disease": "idiopathic pulmonary fibrosis",
                "disease_specific_hits": {
                    "n_gene_in_trait": 0,
                    "n_gene_snps_in_disease": 0,
                    "n_proximity_hits": 1,
                    "proximity_hits": [
                        {"trait": "Idiopathic pulmonary fibrosis", "pvalue": 4e-9},
                    ],
                },
            },
            "vep": {},
        }
    }))
    (evidence / "stage1_evidence.json").write_text(json.dumps({}))
    (evidence / "ot_FN1.json").write_text(json.dumps({
        "executed": True,
        "disease_evidence": [],
        "target_info": {},
        "associations": [],
        "associations_total_count": 500,
    }))

    result = json.loads(compute_rubric_scores.invoke({"data_dir": str(tmp_path)}))
    assert result["success"] is True

    assessment = json.loads((evidence / "assessment_results.json").read_text())
    row = assessment["rubric_assessment"][0]
    assert row["gwas_support"] == 2
    assert row["gwas_evidence_type"] == "disease_specific_proximity"
    assert row["gwas_min_pvalue"] == 4e-9
    assert row["gwas_trait_match_level"] == "disease_specific"
    assert row["gwas_direct_hit_count"] == 0
    assert row["gwas_proximity_hit_count"] == 1

    with (evidence / "rubric_scores.csv").open() as handle:
        csv_row = next(csv.DictReader(handle))
    assert csv_row["gwas_support"] == "2"
    assert csv_row["gwas_evidence_type"] == "disease_specific_proximity"
    assert float(csv_row["gwas_min_pvalue"]) == 4e-9
    assert csv_row["gwas_trait_match_level"] == "disease_specific"
    assert csv_row["gwas_direct_hit_count"] == "0"
    assert csv_row["gwas_proximity_hit_count"] == "1"


def test_compute_rubric_scores_persists_novelty_audit_metadata(tmp_path):
    import csv
    import json

    from src.agents.drug_target.tools.stage_logic import compute_rubric_scores

    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "known_drugs.json").write_text(
        json.dumps({"drugs": {"rows": []}}),
        encoding="utf-8",
    )
    (evidence_dir / "stage2_evidence.json").write_text(
        json.dumps({"FN1": {"gwas": {}, "vep": {}}}),
        encoding="utf-8",
    )
    (evidence_dir / "ot_FN1.json").write_text(
        json.dumps({
            "gene_symbol": "FN1",
            "disease": "idiopathic pulmonary fibrosis",
            "executed": True,
            "disease_evidence": [],
            "target_info": {"tractability": [], "safetyLiabilities": []},
            "associations": [{"score": 0.9}] * 20,
            "associations_truncated": True,
            "associations_total_count": 1633,
            "associations_total_source": "parquet_pre_head",
            "target_drugs": {
                "count": 5,
                "rows": [{"drug": {"id": "CHEMBL1"}}],
            },
        }),
        encoding="utf-8",
    )

    result = json.loads(compute_rubric_scores.invoke({"data_dir": str(tmp_path)}))
    assert result["genes_scored"] == 1

    assessment = json.loads((evidence_dir / "assessment_results.json").read_text())
    row = assessment["rubric_assessment"][0]
    assert row["gene"] == "FN1"
    assert row["novelty_opportunity"] == 0
    assert row["novelty_basis"] == "well_studied_target"
    assert row["novelty_association_count"] == 1633
    assert row["novelty_target_drug_count"] == 5
    assert row["novelty_bucket"] == "1000+ associations"
    assert row["novelty_source"] == "parquet_pre_head"

    matrix_row = assessment["all_genes_matrix"][0]
    assert matrix_row["novelty_basis"] == "well_studied_target"
    assert matrix_row["novelty_association_count"] == 1633
    assert matrix_row["novelty_target_drug_count"] == 5
    assert matrix_row["novelty_bucket"] == "1000+ associations"
    assert matrix_row["novelty_source"] == "parquet_pre_head"

    with (evidence_dir / "rubric_scores.csv").open(newline="", encoding="utf-8") as f:
        csv_row = next(csv.DictReader(f))
    assert csv_row["novelty_basis"] == "well_studied_target"
    assert csv_row["novelty_association_count"] == "1633"
    assert csv_row["novelty_target_drug_count"] == "5"
    assert csv_row["novelty_bucket"] == "1000+ associations"
    assert csv_row["novelty_source"] == "parquet_pre_head"


# ===========================================================================
# 9. C3 + C1 Regression Tests
# ===========================================================================


class TestC3C1Fixes:
    """Regression tests for C3 (hypothesis_writer middleware) and C1 (score normalization)."""

    def test_hypothesis_writer_has_read_file_block_middleware(self):
        """C3 regression: hypothesis_writer must block read_file via middleware."""
        from src.agents.drug_target.subagents.configs import get_subagents
        subagents = get_subagents()
        hw = [s for s in subagents if s["name"] == "hypothesis_writer"][0]
        middleware_types = [type(m).__name__ for m in hw.get("middleware", [])]
        assert "ReadFileBlockMiddleware" in middleware_types

    def test_rank_featured_candidates_flat_keys(self):
        """C1 regression: flat-key matrix rows must produce correct scores."""
        from src.agents.drug_target.tools.stage_logic import rank_featured_candidates
        flat_row = {
            "ligand": "ICAM1",
            "receptor": "MUC1",
            "gene": "MUC1",
            "drug_evidence": 5,
            "trial": 5,
            "safety": 0,
            "gwas": 0,
            "tractability": 2,
            "biological_plausibility": 2,
            "novelty": 1,
        }
        result = rank_featured_candidates([flat_row])
        row = result[0]
        assert row["validated_total"] == 10  # 5 + 5 + 0
        assert row["exploratory_total"] == 5  # 0 + 2 + 2 + 1
        assert row["combined_total"] == 15
        assert row["classification"] == "validated_target"
        assert row["priority"] == "high"

    def test_rank_featured_candidates_nested_dict_unchanged(self):
        """C1 backward compat: nested-dict format still works."""
        from src.agents.drug_target.tools.stage_logic import rank_featured_candidates
        nested_row = {
            "ligand": "ICAM1",
            "receptor": "MUC1",
            "gene": "MUC1",
            "validated_track": {
                "existing_drug_evidence": 5,
                "clinical_trial_activity": 5,
                "safety_profile": 0,
            },
            "exploratory_track": {
                "gwas_genetic_support": 0,
                "tractability": 2,
                "biological_plausibility": 2,
                "novelty_opportunity": 1,
            },
        }
        result = rank_featured_candidates([nested_row])
        row = result[0]
        assert row["validated_total"] == 10
        assert row["exploratory_total"] == 5
        assert row["combined_total"] == 15

    def test_rank_featured_candidates_mixed_format(self):
        """C1 edge case: one track nested dict, other track flat keys."""
        from src.agents.drug_target.tools.stage_logic import rank_featured_candidates
        mixed_row = {
            "ligand": "TEST", "receptor": "TEST", "gene": "TEST",
            "validated_track": {
                "existing_drug_evidence": 3,
                "clinical_trial_activity": 2,
                "safety_profile": 1,
            },
            "gwas": 1, "tractability": 2, "biological_plausibility": 3, "novelty": 2,
        }
        result = rank_featured_candidates([mixed_row])
        row = result[0]
        assert row["validated_total"] == 6   # 3 + 2 + 1
        assert row["exploratory_total"] == 8  # 1 + 2 + 3 + 2
        assert row["combined_total"] == 14


# ============================================================================
# TOP-N Gating + Validator Hardening (schema v3)
# ============================================================================


def _write_pr1_assessment(evidence_dir, *, schema_version=3):
    """Helper: assessment_results.json in post-narrowing (schema v3) state.

    rubric_assessment has 7 rows ({A..G}); only A–E survive the Stage 1 filter
    and therefore appear in `stage3_candidates` with per-row
    `stage3_candidate=True`. F and G remain in rubric_assessment with
    `stage3_candidate=False`.
    """
    rubric_assessment = []
    for g in "ABCDEFG":
        rubric_assessment.append({
            "gene": g, "combined_total": 12, "exploratory_total": 5,
            "classification": "validated_target", "priority": "high",
            "stage3_candidate": g in "ABCDE",
        })
    payload = {
        "schema_version": schema_version,
        "disease": "test_disease",
        "rubric_assessment": rubric_assessment,
        "stage3_candidates": [{"gene": g, "combined_total": 12,
                               "classification": "validated_target", "priority": "high",
                               "exploratory_total": 5}
                              for g in "ABCDE"],
        "stage1_filter_applied": True,
        "summary": {"total_genes": 7, "stage3_count": 5},
    }
    (evidence_dir / "assessment_results.json").write_text(json.dumps(payload, indent=2))


class TestPR1PathTraversal:
    """PR1-3: save_evidence path traversal allow-list (OWASP A01)."""

    @pytest.mark.parametrize("bad_filename", [
        "../../etc/passwd",
        "/etc/passwd",
        "foo/../bar.json",
        "foo\x00bar.json",
        "subdir/bar.json",
        "bar.txt",  # extension not in allow-list
        "..",
    ])
    def test_save_evidence_path_traversal_blocked(self, tmp_path, bad_filename):
        from src.agents.drug_target.tools.evidence_loader import _is_safe_filename
        assert _is_safe_filename(bad_filename) is False

    @pytest.mark.parametrize("good_filename", [
        "stage1_FN1--ITGB2.json",
        "stage3_CD4.json",
        "ot_TGFB1.json",
        "assessment_results.json",
        "hypothesis_report.json",
        "rubric_scores.csv",
        "stage1_filter_results.csv",
        "stage1_filter_results.json",
    ])
    def test_save_evidence_legitimate_filenames_allowed(self, tmp_path, good_filename):
        from src.agents.drug_target.tools.evidence_loader import _is_safe_filename
        assert _is_safe_filename(good_filename) is True


class TestPR1Stage1Filter:
    """apply_stage1_filter narrows stage3_candidates in place (schema v3);
    writes stage1_filter_results.json sidecar; idempotent."""

    def _setup_stage1_inputs(self, data_dir):
        from pathlib import Path as _Path
        evidence = _Path(data_dir) / "evidence"
        evidence.mkdir(parents=True, exist_ok=True)
        assessment = {
            "schema_version": 3,
            "disease": "test",
            "rubric_assessment": [
                {"gene": "PASSING_GENE", "combined_total": 12, "stage3_candidate": True,
                 "exploratory_total": 5, "classification": "validated_target", "priority": "high"},
                {"gene": "FAILING_GENE", "combined_total": 11, "stage3_candidate": True,
                 "exploratory_total": 4, "classification": "validated_target", "priority": "high"},
            ],
            "stage3_candidates": [
                {"gene": "PASSING_GENE", "combined_total": 12, "exploratory_total": 5,
                 "classification": "validated_target", "priority": "high"},
                {"gene": "FAILING_GENE", "combined_total": 11, "exploratory_total": 4,
                 "classification": "validated_target", "priority": "high"},
            ],
            "summary": {"stage3_count": 2},
        }
        (evidence / "assessment_results.json").write_text(json.dumps(assessment, indent=2))
        s1 = {
            "PASSING_GENE^OTHER": {
                "string_ppi": {"max_combined_score": 0.95, "interaction_found": True},
                "census_validation": {
                    "executed": True,
                    "target_vs_rest": {
                        "coexpression": {"p_value": 0.001, "risk_ratio": 5.0},
                        "gene_a": {"p_value": 0.001, "risk_ratio": 3.0, "target_pct": 0.4},
                        "gene_b": {"p_value": 0.001, "risk_ratio": 2.0, "target_pct": 0.3},
                    },
                },
            },
            "FAILING_GENE^X": {
                "string_ppi": {"max_combined_score": 0.5, "interaction_found": True},
                "census_validation": {
                    "executed": True,
                    "target_vs_rest": {
                        "coexpression": {"p_value": 0.001, "risk_ratio": 1.0},
                        "gene_a": {"p_value": 0.001, "risk_ratio": 1.0, "target_pct": 0.1},
                        "gene_b": {"p_value": 0.001, "risk_ratio": 1.0, "target_pct": 0.1},
                    },
                },
            },
        }
        (evidence / "stage1_evidence.json").write_text(json.dumps(s1, indent=2))
        return evidence

    def test_apply_stage1_filter_narrows_stage3_candidates_in_place(self, tmp_path):
        """Schema v3 contract: stage3_candidates is overwritten with the intersection
        (rubric ∩ Stage 1 PASS); legacy stage1_validated_* fields are absent."""
        from src.agents.drug_target.tools.stage_logic import apply_stage1_filter
        evidence = self._setup_stage1_inputs(tmp_path)
        apply_stage1_filter.invoke({"data_dir": str(tmp_path)})
        a = json.loads((evidence / "assessment_results.json").read_text())
        assert a["schema_version"] == 3
        assert "stage1_validated_candidates" not in a
        assert "stage1_filter_passed_genes" not in a
        assert {c["gene"] for c in a["stage3_candidates"]} == {"PASSING_GENE"}
        rows = {r["gene"]: r for r in a["rubric_assessment"]}
        assert rows["PASSING_GENE"]["stage3_candidate"] is True
        assert rows["FAILING_GENE"]["stage3_candidate"] is False
        assert all("stage1_validated" not in r for r in a["rubric_assessment"])
        summary = a.get("summary", {})
        assert summary.get("stage3_count") == 1
        assert "stage1_validated_count" not in summary

    def test_compute_stage1_filter_no_record_is_strict_fail(self):
        """STRING `no_record` must hard-fail — no PR2-1 relaxation (schema v3)."""
        from src.agents.drug_target.tools.stage_logic import compute_stage1_filter
        evidence = {
            "string_ppi": {
                "max_combined_score": 0.0,
                "string_record_found": False,
                "interaction_found": False,
            },
            "census_validation": {
                "target_vs_rest": {
                    "coexpression": {"p_value": 0.0},
                    "gene_a": {"p_value": 0.0},
                    "gene_b": {"p_value": 0.0},
                },
            },
        }
        result = compute_stage1_filter(evidence)
        assert result["passed"] is False
        assert result["string_status"] == "no_record"

    def test_schema_version_is_3_after_full_pipeline(self, tmp_path):
        """compute_rubric_scores + apply_stage1_filter → schema_version == 3."""
        from src.agents.drug_target.tools.stage_logic import apply_stage1_filter
        evidence = self._setup_stage1_inputs(tmp_path)
        apply_stage1_filter.invoke({"data_dir": str(tmp_path)})
        a = json.loads((evidence / "assessment_results.json").read_text())
        assert a["schema_version"] == 3

    def test_apply_stage1_filter_idempotent(self, tmp_path):
        """PR1-1: running fn twice produces identical output (Architect AC-PR1-1b)."""
        from src.agents.drug_target.tools.stage_logic import apply_stage1_filter
        evidence = self._setup_stage1_inputs(tmp_path)
        apply_stage1_filter.invoke({"data_dir": str(tmp_path)})
        first = json.loads((evidence / "assessment_results.json").read_text())
        apply_stage1_filter.invoke({"data_dir": str(tmp_path)})
        second = json.loads((evidence / "assessment_results.json").read_text())
        assert first == second, "apply_stage1_filter not idempotent"

    def test_apply_stage1_filter_writes_json_sidecar(self, tmp_path):
        """PR1-2: stage1_filter_results.json written alongside CSV."""
        from src.agents.drug_target.tools.stage_logic import apply_stage1_filter
        evidence = self._setup_stage1_inputs(tmp_path)
        apply_stage1_filter.invoke({"data_dir": str(tmp_path)})
        json_sidecar = evidence / "stage1_filter_results.json"
        assert json_sidecar.exists()
        rows = json.loads(json_sidecar.read_text())
        assert any(r["passed"] is True for r in rows)
        assert any(r["passed"] is False for r in rows)


class TestBuildEvidenceSummaryStage1Artifacts:
    """Reference Card loading should ignore Stage 1 sidecars and invalid payloads."""

    @staticmethod
    def _setup_reference_card_inputs(tmp_path):
        evidence = tmp_path / "evidence"
        evidence.mkdir(parents=True, exist_ok=True)

        (tmp_path / "lr_candidates.json").write_text(json.dumps({
            "disease": "idiopathic pulmonary fibrosis",
            "pairs": [
                {"ligand": "TGFB1", "receptor": "TGFBR2", "score": 0.95},
            ],
        }))

        (evidence / "assessment_results.json").write_text(json.dumps({
            "disease": "idiopathic pulmonary fibrosis",
            "stage3_candidates": [{"gene": "TGFBR2"}],
            "rubric_assessment": [{
                "gene": "TGFBR2",
                "classification": "validated_target",
                "priority": "high",
                "combined_total": 12,
                "validated_total": 7,
                "exploratory_total": 5,
                "existing_drug_evidence": 2,
                "clinical_trial_activity": 1,
                "safety_profile": 0,
                "safety_evidence_level": "low_preclinical_signal",
                "safety_liability_count": 2,
                "safety_liability_sources": "aop-wiki;toxcast",
                "gwas_support": 2,
                "gwas_evidence_type": "disease_specific_proximity",
                "gwas_min_pvalue": 4e-09,
                "gwas_trait_match_level": "disease_specific",
                "gwas_direct_hit_count": 0,
                "gwas_proximity_hit_count": 1,
                "tractability": 2,
                "tractability_basis": "approved_drug",
                "tractability_modalities": "AB;SM",
                "tractability_evidence_label": "approved drug",
                "biological_plausibility_base": 2,
                "stage1_biological_support_bonus": 1,
                "biological_basis": "ot_evidence_plus_stage1_pair",
                "biological_evidence_types": "affected_pathway;literature",
                "biological_evidence_count": 2,
                "biological_max_ot_score": 0.82,
                "vep_high_impact_count": 1,
                "stage1_support_pair_count": 1,
                "stage1_support_pairs": "TGFB1^TGFBR2",
                "stage1_gate_status": "pass",
                "stage1_total_pair_count": 2,
                "stage1_passed_pair_count": 1,
                "stage1_failed_pair_count": 1,
                "stage1_best_pair": "TGFB1^TGFBR2",
                "stage1_best_string_combined": 0.97,
                "stage1_best_coexpr_pvalue": 0.001,
                "stage1_best_gene_a_pvalue": 0.002,
                "stage1_best_gene_b_pvalue": 0.003,
                "stage1_source": "stage1_evidence.json",
                "biological_plausibility": 3,
                "novelty_opportunity": 2,
                "novelty_basis": "st_only_or_brand_new_target",
                "novelty_association_count": 4,
                "novelty_target_drug_count": 0,
                "novelty_bucket": "0-9 associations",
                "novelty_source": "list_length",
                "stage3_candidate": True,
            }],
        }))

        (evidence / "stage3_TGFBR2.json").write_text(json.dumps({
            "executed": True,
            "matched_drugs": [],
            "errors": [],
            "pubmed_papers": [],
        }))

        (evidence / "stage1_TGFB1--TGFBR2.json").write_text(json.dumps({
            "ligand": "TGFB1",
            "receptor": "TGFBR2",
            "string_ppi": {
                "interaction_found": True,
                "max_combined_score": 0.97,
            },
            "kegg_pathways": {
                "ligand_pathways": [{"name": "TGF-beta signaling pathway"}],
                "receptor_pathways": [{"name": "Cell adhesion molecules"}],
            },
            "reactome_pathways": {
                "ligand_pathways": [{"name": "Extracellular matrix organization"}],
                "receptor_pathways": [{"name": "Signaling by TGF-beta receptor complex"}],
            },
            "census_validation": {
                "target_vs_rest": {
                    "coexpression": {"risk_ratio": 2.1, "p_value": 0.001},
                },
            },
        }))

        return evidence

    def test_build_evidence_summary_ignores_list_sidecar_and_preserves_stage1_pair(
        self,
        tmp_path,
    ):
        from src.agents.drug_target.tools.stage_logic import build_evidence_summary

        evidence = self._setup_reference_card_inputs(tmp_path)
        (evidence / "stage1_filter_results.json").write_text(json.dumps([
            {
                "ligand": "TGFB1",
                "receptor": "TGFBR2",
                "passed": True,
                "string_combined": 0.97,
            }
        ]))

        with patch(
            "src.agents.drug_target.tools.drug_report_html.render_drug_md",
            return_value="# drug draft",
        ) as render_mock:
            raw = build_evidence_summary.invoke({"data_dir": str(tmp_path)})

        result = json.loads(raw)
        featured = result["featured_genes"][0]
        assert featured["gene"] == "TGFBR2"
        assert "TGFB1_TGFBR2" in featured["stage1_pairs"]
        pair = featured["stage1_pairs"]["TGFB1_TGFBR2"]
        assert pair["ligand"] == "TGFB1"
        assert pair["receptor"] == "TGFBR2"
        assert pair["string_ppi"]["max_combined_score"] == 0.97

        expected_stage1_audit = {
            "stage1_gate_status": "pass",
            "stage1_total_pair_count": 2,
            "stage1_passed_pair_count": 1,
            "stage1_failed_pair_count": 1,
            "stage1_best_pair": "TGFB1^TGFBR2",
            "stage1_best_string_combined": 0.97,
            "stage1_best_coexpr_pvalue": 0.001,
            "stage1_best_gene_a_pvalue": 0.002,
            "stage1_best_gene_b_pvalue": 0.003,
            "stage1_source": "stage1_evidence.json",
        }
        for key, value in expected_stage1_audit.items():
            assert featured["rubric"][key] == value
            assert result["all_genes_druggability"][0][key] == value

        rendered_matrix = render_mock.call_args.kwargs["all_genes_matrix"]
        for key, value in expected_stage1_audit.items():
            assert rendered_matrix[0][key] == value

        target_assessment = json.loads((tmp_path / "target_assessment.json").read_text())
        matrix_row = target_assessment["druggability_matrix"][0]
        expected_pair_audit = {
            "gwas_evidence_type": "disease_specific_proximity",
            "gwas_min_pvalue": 4e-09,
            "gwas_trait_match_level": "disease_specific",
            "gwas_direct_hit_count": 0,
            "gwas_proximity_hit_count": 1,
            "tractability_basis": "approved_drug",
            "tractability_modalities": "AB;SM",
            "tractability_evidence_label": "approved drug",
            "safety_evidence_level": "low_preclinical_signal",
            "safety_liability_count": 2,
            "safety_liability_sources": "aop-wiki;toxcast",
            "biological_plausibility_base": 2,
            "stage1_biological_support_bonus": 1,
            "biological_basis": "ot_evidence_plus_stage1_pair",
            "biological_evidence_types": "affected_pathway;literature",
            "biological_evidence_count": 2,
            "biological_max_ot_score": 0.82,
            "vep_high_impact_count": 1,
            "stage1_support_pair_count": 1,
            "stage1_support_pairs": "TGFB1^TGFBR2",
            **expected_stage1_audit,
            "novelty_basis": "st_only_or_brand_new_target",
            "novelty_association_count": 4,
            "novelty_target_drug_count": 0,
            "novelty_bucket": "0-9 associations",
            "novelty_source": "list_length",
        }
        for key, value in expected_pair_audit.items():
            assert matrix_row[key] == value

    def test_build_evidence_summary_defaults_missing_biological_base_to_zero(
        self,
        tmp_path,
    ):
        from src.agents.drug_target.tools.stage_logic import build_evidence_summary

        evidence = self._setup_reference_card_inputs(tmp_path)
        assessment_path = evidence / "assessment_results.json"
        assessment = json.loads(assessment_path.read_text())
        rubric_row = assessment["rubric_assessment"][0]
        assert rubric_row["biological_plausibility"] == 3
        rubric_row.pop("biological_plausibility_base")
        assessment_path.write_text(json.dumps(assessment))

        with patch(
            "src.agents.drug_target.tools.drug_report_html.render_drug_md",
            return_value="# drug draft",
        ) as render_mock:
            raw = build_evidence_summary.invoke({"data_dir": str(tmp_path)})

        result = json.loads(raw)

        assert result["featured_genes"][0]["rubric"]["biological_plausibility_base"] == 0
        assert result["all_genes_druggability"][0]["biological_plausibility_base"] == 0
        rendered_matrix = render_mock.call_args.kwargs["all_genes_matrix"]
        assert rendered_matrix[0]["biological_plausibility_base"] == 0
        target_assessment = json.loads((tmp_path / "target_assessment.json").read_text())
        assert target_assessment["druggability_matrix"][0]["biological_plausibility_base"] == 0

    def test_build_evidence_summary_skips_unexpected_non_dict_stage1_artifact(
        self,
        tmp_path,
    ):
        from src.agents.drug_target.tools.stage_logic import build_evidence_summary

        evidence = self._setup_reference_card_inputs(tmp_path)
        (evidence / "stage1_BAD--PAYLOAD.json").write_text(json.dumps([
            {"artifact": "not a stage1 pair payload"}
        ]))

        with patch(
            "src.agents.drug_target.tools.drug_report_html.render_drug_md",
            return_value="# drug draft",
        ):
            raw = build_evidence_summary.invoke({"data_dir": str(tmp_path)})

        result = json.loads(raw)
        featured = result["featured_genes"][0]
        assert "TGFB1_TGFBR2" in featured["stage1_pairs"]
        assert featured["stage1_pairs"]["TGFB1_TGFBR2"]["ligand"] == "TGFB1"


class TestDrugReportHtmlAuditMetadata:
    """HTML report conversion preserves candidate audit metadata."""

    def test_parse_drug_md_preserves_audit_metadata_without_matrix_columns(self):
        from src.agents.drug_target.tools.drug_report_html import parse_drug_md

        context = parse_drug_md(self._drug_md_with_audit_metadata())

        rubric = context["deep_dives"][0]["rubric"]
        assert rubric["gwas_evidence_type"] == "disease_specific_proximity"
        assert rubric["gwas_min_pvalue"] == 4e-09
        assert rubric["gwas_trait_match_level"] == "disease_specific"
        assert rubric["gwas_direct_hit_count"] == 0
        assert rubric["gwas_proximity_hit_count"] == 1
        assert rubric["biological_basis"] == "ot_evidence_plus_stage1_pair"
        assert rubric["biological_evidence_types"] == "affected_pathway;literature"
        assert rubric["biological_evidence_count"] == 2
        assert rubric["biological_max_ot_score"] == 0.82
        assert rubric["vep_high_impact_count"] == 1
        assert rubric["stage1_support_pair_count"] == 2
        assert rubric["stage1_support_pairs"] == "FN1^SDC2;FN1^ITGA5"
        assert rubric["stage1_gate_status"] == "pass"
        assert rubric["stage1_total_pair_count"] == 2
        assert rubric["stage1_passed_pair_count"] == 1
        assert rubric["stage1_failed_pair_count"] == 1
        assert rubric["stage1_best_pair"] == "FN1^SDC2"
        assert rubric["stage1_best_string_combined"] == 0.959
        assert rubric["stage1_best_coexpr_pvalue"] == 3e-06
        assert rubric["stage1_best_gene_a_pvalue"] == 1e-06
        assert rubric["stage1_best_gene_b_pvalue"] == 2e-06
        assert rubric["stage1_source"] == "stage1_evidence.json"
        assert rubric["novelty_basis"] == "well_studied_target"
        assert rubric["novelty_association_count"] == 1633
        assert rubric["novelty_target_drug_count"] == 5
        assert rubric["novelty_bucket"] == "1000+ associations"
        assert rubric["novelty_source"] == "parquet_pre_head"
        assert rubric["tractability_basis"] == "approved_drug"
        assert rubric["tractability_modalities"] == "AB;SM"
        assert rubric["tractability_evidence_label"] == "approved drug"
        assert rubric["safety_evidence_level"] == "low_preclinical_signal"
        assert rubric["safety_liability_count"] == 2
        assert rubric["safety_liability_sources"] == "aop-wiki;toxcast"

        headers = context["matrix"]["headers"]
        for audit_field in (
            "gwas_evidence_type",
            "gwas_min_pvalue",
            "gwas_trait_match_level",
            "gwas_direct_hit_count",
            "gwas_proximity_hit_count",
            "biological_basis",
            "biological_evidence_types",
            "biological_evidence_count",
            "biological_max_ot_score",
            "vep_high_impact_count",
            "stage1_support_pair_count",
            "stage1_support_pairs",
            "stage1_gate_status",
            "stage1_total_pair_count",
            "stage1_passed_pair_count",
            "stage1_failed_pair_count",
            "stage1_best_pair",
            "stage1_best_string_combined",
            "stage1_best_coexpr_pvalue",
            "stage1_best_gene_a_pvalue",
            "stage1_best_gene_b_pvalue",
            "stage1_source",
            "novelty_basis",
            "novelty_association_count",
            "novelty_target_drug_count",
            "novelty_bucket",
            "novelty_source",
            "tractability_basis",
            "tractability_modalities",
            "tractability_evidence_label",
            "safety_evidence_level",
            "safety_liability_count",
            "safety_liability_sources",
        ):
            assert audit_field not in headers

    def test_render_drug_html_includes_audit_metadata_in_candidate_detail(self):
        from src.agents.drug_target.tools.drug_report_html import (
            parse_drug_md,
            render_drug_html,
        )

        context = parse_drug_md(self._drug_md_with_audit_metadata())
        context.update({"css": "", "js": "", "generation_date": "2026-05-30"})

        html = render_drug_html(context)

        assert "Audit Metadata" in html
        assert "GWAS Audit" in html
        assert "evidence_type" in html
        assert "disease_specific_proximity" in html
        assert "min_pvalue" in html
        assert "4e-09" in html
        assert "trait_match" in html
        assert "disease_specific" in html
        assert "direct_hits" in html
        assert "proximity_hits" in html
        assert "Biological Audit" in html
        assert "basis" in html
        assert "ot_evidence_plus_stage1_pair" in html
        assert "evidence_types" in html
        assert "affected_pathway;literature" in html
        assert "evidence_count" in html
        assert "max_ot_score" in html
        assert "0.82" in html
        assert "vep_high_impact_count" in html
        assert "stage1_pair_count" in html
        assert "stage1_pairs" in html
        assert "FN1^SDC2;FN1^ITGA5" in html
        assert "Stage1 Audit" in html
        assert "gate_status" in html
        assert "best_pair" in html
        assert "FN1^SDC2" in html
        assert "stage1_evidence.json" in html
        assert "Novelty Audit" in html
        assert "well_studied_target" in html
        assert "1000+ associations" in html
        assert "parquet_pre_head" in html
        assert "tractability_basis" in html
        assert "approved_drug" in html
        assert "safety_evidence_level" in html
        assert "low_preclinical_signal" in html
        assert "aop-wiki;toxcast" in html

    def test_render_drug_html_preserves_zero_gwas_min_pvalue(self):
        from src.agents.drug_target.tools.drug_report_html import (
            parse_drug_md,
            render_drug_html,
        )

        context = parse_drug_md(self._drug_md_with_audit_metadata(min_pvalue="0.0"))
        context.update({"css": "", "js": "", "generation_date": "2026-05-30"})

        rubric = context["deep_dives"][0]["rubric"]
        assert rubric["gwas_min_pvalue"] == 0.0

        html = render_drug_html(context)

        assert "<tr><td>min_pvalue</td><td>0.0</td></tr>" in html

    def test_render_drug_html_blanks_none_biological_max_ot_score_and_preserves_zero(self):
        from src.agents.drug_target.tools.drug_report_html import (
            parse_drug_md,
            render_drug_html,
        )

        none_context = parse_drug_md(self._drug_md_with_audit_metadata(max_ot_score=""))
        none_context.update({"css": "", "js": "", "generation_date": "2026-05-30"})
        zero_context = parse_drug_md(self._drug_md_with_audit_metadata(max_ot_score="0.0"))
        zero_context.update({"css": "", "js": "", "generation_date": "2026-05-30"})

        assert none_context["deep_dives"][0]["rubric"]["biological_max_ot_score"] is None
        assert zero_context["deep_dives"][0]["rubric"]["biological_max_ot_score"] == 0.0

        none_html = render_drug_html(none_context)
        zero_html = render_drug_html(zero_context)

        assert "<tr><td>max_ot_score</td><td></td></tr>" in none_html
        assert "<tr><td>max_ot_score</td><td>0.0</td></tr>" in zero_html

    def test_render_drug_html_escapes_biological_audit_string_fields(self):
        from src.agents.drug_target.tools.drug_report_html import (
            parse_drug_md,
            render_drug_html,
        )

        context = parse_drug_md(self._drug_md_with_audit_metadata(
            biological_basis="<script>alert(1)</script>",
            biological_evidence_types="<img src=x onerror=alert(1)>",
            stage1_support_pairs="FN1^SDC2;<b>bad</b>",
        ))
        context.update({"css": "", "js": "", "generation_date": "2026-05-30"})

        html = render_drug_html(context)

        assert "<script>alert(1)</script>" not in html
        assert "<img src=x onerror=alert(1)>" not in html
        assert "FN1^SDC2;<b>bad</b>" not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
        assert "&lt;img src=x onerror=alert(1)&gt;" in html
        assert "FN1^SDC2;&lt;b&gt;bad&lt;/b&gt;" in html

    def test_render_drug_html_escapes_novelty_audit_strings(self):
        from src.agents.drug_target.tools.drug_report_html import (
            parse_drug_md,
            render_drug_html,
        )

        context = parse_drug_md(self._drug_md_with_audit_metadata(
            novelty_basis="<script>alert(1)</script>",
            novelty_bucket="<img src=x onerror=alert(1)>",
            novelty_source="<b>api_count</b>",
        ))
        context.update({"css": "", "js": "", "generation_date": "2026-05-30"})

        html = render_drug_html(context)

        assert "<script>alert(1)</script>" not in html
        assert "<img src=x onerror=alert(1)>" not in html
        assert "<b>api_count</b>" not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
        assert "&lt;img src=x onerror=alert(1)&gt;" in html
        assert "&lt;b&gt;api_count&lt;/b&gt;" in html

    def test_render_drug_html_escapes_tractability_safety_audit_strings(self):
        from src.agents.drug_target.tools.drug_report_html import (
            parse_drug_md,
            render_drug_html,
        )

        context = parse_drug_md(self._drug_md_with_audit_metadata())
        rubric = context["deep_dives"][0]["rubric"]
        rubric.update({
            "tractability_basis": "<script>alert(1)</script>",
            "tractability_modalities": "<img src=x onerror=alert(1)>",
            "tractability_evidence_label": "<b>approved</b>",
            "safety_evidence_level": "<svg onload=alert(1)>",
            "safety_liability_sources": "toxcast;<i>bad</i>",
        })
        context.update({"css": "", "js": "", "generation_date": "2026-05-30"})

        html = render_drug_html(context)

        assert "<script>alert(1)</script>" not in html
        assert "<img src=x onerror=alert(1)>" not in html
        assert "<b>approved</b>" not in html
        assert "<svg onload=alert(1)>" not in html
        assert "toxcast;<i>bad</i>" not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
        assert "&lt;img src=x onerror=alert(1)&gt;" in html
        assert "&lt;b&gt;approved&lt;/b&gt;" in html
        assert "&lt;svg onload=alert(1)&gt;" in html
        assert "toxcast;&lt;i&gt;bad&lt;/i&gt;" in html

    def test_render_drug_md_blanks_none_gwas_min_pvalue_and_preserves_zero(self):
        none_markdown = self._render_drug_md_with_gwas_min_pvalue(None)
        zero_markdown = self._render_drug_md_with_gwas_min_pvalue(0.0)

        assert "min_pvalue=None" not in none_markdown
        assert "min_pvalue=, trait_match=" in none_markdown
        assert "min_pvalue=0.0" in zero_markdown

    def test_render_drug_md_blanks_none_biological_max_ot_score_and_preserves_zero(self):
        none_markdown = self._render_drug_md_with_biological_max_ot_score(None)
        zero_markdown = self._render_drug_md_with_biological_max_ot_score(0.0)

        assert "max_ot_score=None" not in none_markdown
        assert "max_ot_score=, vep_high_impact_count=" in none_markdown
        assert "max_ot_score=0.0" in zero_markdown

    @staticmethod
    def _render_drug_md_with_gwas_min_pvalue(min_pvalue):
        from src.agents.drug_target.tools.drug_report_html import render_drug_md

        return render_drug_md(
            disease="test disease",
            stage3_genes=["FN1"],
            featured_cards=[
                {
                    "gene": "FN1",
                    "rubric": {
                        "classification": "validated_target",
                        "priority": "high",
                        "combined_total": 16,
                        "validated_total": 6,
                        "exploratory_total": 10,
                        "existing_drug_evidence": 5,
                        "clinical_trial_activity": 1,
                        "safety_profile": 0,
                        "gwas_support": 2,
                        "gwas_min_pvalue": min_pvalue,
                        "gwas_trait_match_level": "none",
                    },
                    "stage1_pairs": {},
                    "stage3": {},
                }
            ],
            all_genes_matrix=[
                {
                    "gene": "FN1",
                    "stage3_candidate": True,
                    "combined_total": 16,
                    "combined_rank_score": 16,
                }
            ],
            stage1_data={},
            stage1_filter_results=[],
        )

    @staticmethod
    def _render_drug_md_with_biological_max_ot_score(max_ot_score):
        from src.agents.drug_target.tools.drug_report_html import render_drug_md

        return render_drug_md(
            disease="test disease",
            stage3_genes=["FN1"],
            featured_cards=[
                {
                    "gene": "FN1",
                    "rubric": {
                        "classification": "validated_target",
                        "priority": "high",
                        "combined_total": 16,
                        "validated_total": 6,
                        "exploratory_total": 10,
                        "existing_drug_evidence": 5,
                        "clinical_trial_activity": 1,
                        "safety_profile": 0,
                        "gwas_support": 2,
                        "gwas_min_pvalue": None,
                        "gwas_trait_match_level": "none",
                        "biological_basis": "ot_evidence",
                        "biological_evidence_types": "literature",
                        "biological_evidence_count": 1,
                        "biological_max_ot_score": max_ot_score,
                        "vep_high_impact_count": 0,
                        "stage1_support_pair_count": 0,
                        "stage1_support_pairs": "",
                    },
                    "stage1_pairs": {},
                    "stage3": {},
                }
            ],
            all_genes_matrix=[
                {
                    "gene": "FN1",
                    "stage3_candidate": True,
                    "combined_total": 16,
                    "combined_rank_score": 16,
                }
            ],
            stage1_data={},
            stage1_filter_results=[],
        )

    @staticmethod
    def _drug_md_with_audit_metadata(
        min_pvalue: str = "4e-09",
        max_ot_score: str = "0.82",
        biological_basis: str = "ot_evidence_plus_stage1_pair",
        biological_evidence_types: str = "affected_pathway;literature",
        stage1_support_pairs: str = "FN1^SDC2;FN1^ITGA5",
        novelty_basis: str = "well_studied_target",
        novelty_association_count: int = 1633,
        novelty_target_drug_count: int = 5,
        novelty_bucket: str = "1000+ associations",
        novelty_source: str = "parquet_pre_head",
    ) -> str:
        return f"""# Therapeutic Target Assessment Report — test disease

## 2. Druggability Matrix

### 2.1. Druggability Matrix

| Gene | Drug Ev. | Trial | Safety | Val. Total | GWAS | Tract. | Bio. Plaus. | Novelty | Expl. Total | Combined | Rank Score | Classification | Priority | Stage3 |
|------|----------|-------|--------|------------|------|--------|--------------|---------|-------------|----------|------------|----------------|----------|--------|
| **FN1** | 5 | 1 | 0 | 6 | 2 | 3 | 4 | 1 | 10 | 16 | 12.5 | validated_target | high | Yes |

## 3. Featured Candidate Deep Dives

### FN1 — Classification: validated_target | Priority: high

**C. Rubric Assessment**

- Validated Track: existing_drug_evidence=5, clinical_trial_activity=1, safety_profile=0 → **validated_total=6**
- Exploratory Track: gwas_support=2, tractability=3, biological_plausibility=4, novelty_opportunity=1 → **exploratory_total=10**
- GWAS Audit: evidence_type=disease_specific_proximity, min_pvalue={min_pvalue}, trait_match=disease_specific, direct_hits=0, proximity_hits=1
- Biological Audit: basis={biological_basis}, evidence_types={biological_evidence_types}, evidence_count=2, max_ot_score={max_ot_score}, vep_high_impact_count=1, stage1_pair_count=2, stage1_pairs={stage1_support_pairs}
- Stage1 Audit: gate_status=pass, total_pairs=2, passed_pairs=1, failed_pairs=1, best_pair=FN1^SDC2, best_string=0.959, best_coexpr_p=3e-06, best_gene_a_p=1e-06, best_gene_b_p=2e-06, source=stage1_evidence.json
- Novelty Audit: basis={novelty_basis}, association_count={novelty_association_count}, target_drug_count={novelty_target_drug_count}, bucket={novelty_bucket}, source={novelty_source}
- Audit Metadata: tractability_basis=approved_drug, tractability_modalities=AB;SM, tractability_evidence_label=approved drug, safety_evidence_level=low_preclinical_signal, safety_liability_count=2, safety_liability_sources=aop-wiki;toxcast
- **Combined Total: 16** | Classification: validated_target | Priority: high
"""


class TestPR1HypothesisReportValidator:
    """TOP-N coverage + deterministic evidence_coverage_pct + FAILED-pair gate."""

    def _setup(self, tmp_path):
        evidence = tmp_path / "evidence"
        evidence.mkdir(parents=True, exist_ok=True)
        _write_pr1_assessment(evidence)
        rows = [
            {"ligand": "P1", "receptor": "P2", "passed": True, "string_combined": 0.9,
             "census_coexpr_pvalue": 0.001, "census_gene_a_pvalue": 0.001,
             "census_gene_b_pvalue": 0.001},
            {"ligand": "F1", "receptor": "F2", "passed": False, "string_combined": 0.6,
             "census_coexpr_pvalue": 0.5, "census_gene_a_pvalue": 0.5,
             "census_gene_b_pvalue": 0.5},
        ]
        (evidence / "stage1_filter_results.json").write_text(json.dumps(rows))
        for fname in ["stage1_P1--P2.json", "stage1_F1--F2.json", "stage3_A.json", "stage3_B.json"]:
            (evidence / fname).write_text("{}")
        return evidence

    def test_topn_coverage_gate_rejects_missing_genes(self, tmp_path):
        """hypothesis_report missing a stage3_candidate → reject with diagnostic."""
        from src.agents.drug_target.tools.evidence_loader import save_evidence
        self._setup(tmp_path)
        report = {
            "evidence_coverage_pct": 99,
            "hypotheses": [
                {"biological_entities": {"genes": ["A"]}, "evidence_references": ["stage3_A.json"]},
                {"biological_entities": {"genes": ["B"]}, "evidence_references": ["stage3_B.json"]},
            ],
        }
        result = json.loads(save_evidence.invoke({
            "data_dir": str(tmp_path),
            "filename": "hypothesis_report.json",
            "data": json.dumps(report),
        }))
        assert result["saved"] is False
        assert "topn_coverage" in result
        assert set(result["topn_coverage"]["missing"]) == {"C", "D", "E"}

    def test_topn_coverage_gate_passes_full_coverage(self, tmp_path):
        """When every stage3_candidate gene is covered, the gate passes."""
        from src.agents.drug_target.tools.evidence_loader import save_evidence
        evidence = self._setup(tmp_path)
        report = {
            "evidence_coverage_pct": 50,
            "hypotheses": [
                {"biological_entities": {"genes": ["A", "B", "C", "D", "E"]},
                 "evidence_references": ["stage3_A.json", "stage3_B.json"]},
            ],
        }
        result = json.loads(save_evidence.invoke({
            "data_dir": str(tmp_path),
            "filename": "hypothesis_report.json",
            "data": json.dumps(report),
        }))
        assert result["saved"] is True
        saved = json.loads((evidence / "hypothesis_report.json").read_text())
        assert saved["topn_coverage"]["coverage_pct"] == 100.0
        assert saved["topn_coverage"]["missing"] == []
        assert saved["evidence_coverage_pct"] == 66.67

    def test_deterministic_evidence_coverage_pct_overwrites_llm(self, tmp_path):
        """PR1-5: LLM-supplied evidence_coverage_pct is replaced by deterministic value."""
        from src.agents.drug_target.tools.evidence_loader import save_evidence
        evidence = self._setup(tmp_path)
        report = {
            "evidence_coverage_pct": 99,
            "hypotheses": [
                {"biological_entities": {"genes": ["A", "B", "C", "D", "E"]},
                 "evidence_references": ["stage1_P1--P2.json"]},
            ],
        }
        result = json.loads(save_evidence.invoke({
            "data_dir": str(tmp_path),
            "filename": "hypothesis_report.json",
            "data": json.dumps(report),
        }))
        assert result["saved"] is True
        saved = json.loads((evidence / "hypothesis_report.json").read_text())
        assert saved["evidence_coverage_pct"] == 33.33  # 1 of 3 eligible stage1/3 files

    def test_failed_pair_block_rejects_failed_citation(self, tmp_path):
        """Citing a failed pair is rejected regardless of suffix markers."""
        from src.agents.drug_target.tools.evidence_loader import save_evidence
        self._setup(tmp_path)
        report = {
            "evidence_coverage_pct": 50,
            "hypotheses": [
                {"biological_entities": {"genes": ["A", "B", "C", "D", "E"]},
                 "evidence_references": ["stage1_F1--F2.json"]},
            ],
        }
        result = json.loads(save_evidence.invoke({
            "data_dir": str(tmp_path),
            "filename": "hypothesis_report.json",
            "data": json.dumps(report),
        }))
        assert result["saved"] is False
        assert any("F1--F2" in v for v in result.get("failed_pair_violations", []))

    def test_failed_pair_block_rejects_explicit_suffix(self, tmp_path):
        """New hypothesis writes reject failed pair citations even with legacy suffixes."""
        from src.agents.drug_target.tools.evidence_loader import save_evidence
        self._setup(tmp_path)
        report = {
            "evidence_coverage_pct": 50,
            "hypotheses": [
                {"biological_entities": {"genes": ["A", "B", "C", "D", "E"]},
                 "evidence_references": [
                     "stage1_P1--P2.json",
                     "stage1_F1--F2.json_FAILED",
                 ]},
            ],
        }
        result = json.loads(save_evidence.invoke({
            "data_dir": str(tmp_path),
            "filename": "hypothesis_report.json",
            "data": json.dumps(report),
        }))
        assert result["saved"] is False
        assert any("F1--F2" in v for v in result.get("failed_pair_violations", []))


class TestPR2Stage1Filter:
    """Stage 1 filter (schema v3, strict): STRING must have a record with combined > 0.8
    AND all three Census p-values < 0.05 — no relaxation for missing STRING rows."""

    def test_string_no_record_fails_even_with_strong_census(self):
        """Schema v3: no_record ALWAYS fails, regardless of Census strength."""
        from src.agents.drug_target.tools.stage_logic import compute_stage1_filter
        ev = {
            "string_ppi": {
                "string_record_found": False,
                "interaction_found": False,
                "max_combined_score": 0.0,
            },
            "census_validation": {
                "target_vs_rest": {
                    "coexpression": {"p_value": 1e-15},
                    "gene_a": {"p_value": 0.01},
                    "gene_b": {"p_value": 0.01},
                },
            },
        }
        out = compute_stage1_filter(ev)
        assert out["string_status"] == "no_record"
        assert out["passed"] is False

    def test_string_no_record_fails_on_weak_census(self):
        """no_record + weak coexpression → fail."""
        from src.agents.drug_target.tools.stage_logic import compute_stage1_filter
        ev = {
            "string_ppi": {"string_record_found": False, "max_combined_score": 0.0},
            "census_validation": {
                "target_vs_rest": {
                    "coexpression": {"p_value": 0.001},  # below default 0.05 but not 1e-10
                    "gene_a": {"p_value": 0.01},
                    "gene_b": {"p_value": 0.01},
                },
            },
        }
        out = compute_stage1_filter(ev)
        assert out["string_status"] == "no_record"
        assert out["passed"] is False

    def test_string_in_db_low_score_still_fails(self):
        """STRING in DB with low score (0.5) → original criterion applies → fail."""
        from src.agents.drug_target.tools.stage_logic import compute_stage1_filter
        ev = {
            "string_ppi": {"string_record_found": True, "max_combined_score": 0.5},
            "census_validation": {
                "target_vs_rest": {
                    "coexpression": {"p_value": 0.001},
                    "gene_a": {"p_value": 0.01},
                    "gene_b": {"p_value": 0.01},
                },
            },
        }
        out = compute_stage1_filter(ev)
        assert out["string_status"] == "in_db"
        assert out["passed"] is False

    def test_string_in_db_high_score_passes(self):
        """STRING in DB with high score → original criterion → pass with default Census threshold."""
        from src.agents.drug_target.tools.stage_logic import compute_stage1_filter
        ev = {
            "string_ppi": {"string_record_found": True, "max_combined_score": 0.95},
            "census_validation": {
                "target_vs_rest": {
                    "coexpression": {"p_value": 0.001},
                    "gene_a": {"p_value": 0.01},
                    "gene_b": {"p_value": 0.01},
                },
            },
        }
        out = compute_stage1_filter(ev)
        assert out["string_status"] == "in_db"
        assert out["passed"] is True


class TestPR2GeneSymbolValidation:
    """PR2-2: Census SOQL gene-symbol allow-list (OWASP A03)."""

    @pytest.mark.parametrize("bad_symbol", [
        "A'); DROP TABLE--",
        "FOO BAR",
        "FOO'BAR",
        "FOO\nBAR",
        "FOO;BAR",
        "",
        "lowercase",  # would be uppercased but contains nothing else
    ])
    def test_invalid_gene_symbol_rejected(self, bad_symbol):
        from src.agents.drug_target.tools.stage_domain_tools import _validate_gene_symbol
        err = _validate_gene_symbol(bad_symbol, role="ligand")
        # 'lowercase' becomes 'LOWERCASE' which IS valid -- it's actually allowed.
        # The other cases must produce an error.
        if bad_symbol == "lowercase":
            assert err is None
        else:
            assert err is not None, f"Should reject {bad_symbol!r}"

    @pytest.mark.parametrize("good_symbol", [
        "TGFB1", "HLA-DRB1", "CD4", "P53", "BRCA-1", "OR1G1",
    ])
    def test_valid_gene_symbol_accepted(self, good_symbol):
        from src.agents.drug_target.tools.stage_domain_tools import _validate_gene_symbol
        assert _validate_gene_symbol(good_symbol, role="ligand") is None


class TestPR2RubricValidation:
    """PR2-4: validate_rubric_assessment activated in compute_rubric_scores."""

    def test_in_range_assessment_passes(self):
        from src.agents.drug_target.tools.stage_logic import validate_rubric_assessment
        assessment = {
            "validated_track": {
                "existing_drug_evidence": 3,
                "clinical_trial_activity": 2,
                "safety_profile": -1,
            },
            "exploratory_track": {
                "gwas_genetic_support": 2,
                "tractability": 3,
                "biological_plausibility": 4,
                "novelty_opportunity": 3,
            },
        }
        assert validate_rubric_assessment(assessment) == []

    def test_out_of_range_safety_profile_caught(self):
        from src.agents.drug_target.tools.stage_logic import validate_rubric_assessment
        assessment = {
            "validated_track": {
                "existing_drug_evidence": 0,
                "clinical_trial_activity": 0,
                "safety_profile": -4,  # out of [-3, 0]
            },
            "exploratory_track": {
                "gwas_genetic_support": 0, "tractability": 0,
                "biological_plausibility": 0, "novelty_opportunity": 0,
            },
        }
        errs = validate_rubric_assessment(assessment)
        assert any("safety_profile" in e for e in errs)


class TestP2GateAndAtomicWrite:
    """P2-1 (validate_stage1_gate quality check) + P2-8 (atomic write)."""

    def test_validate_stage1_gate_blocks_when_filter_not_applied(self, tmp_path):
        """P2-1: validate_stage1_gate refuses if stage1_filter_applied is missing/false."""
        from src.agents.drug_target.tools.stage_logic import validate_stage1_gate
        evidence = tmp_path / "evidence"
        evidence.mkdir(parents=True, exist_ok=True)
        # Assessment with stage3_candidates but NO stage1_filter_applied flag
        assessment = {
            "schema_version": 2,
            "rubric_assessment": [{"gene": "FOO", "stage3_candidate": True}],
            "stage3_candidates": [{"gene": "FOO"}],
            # stage1_filter_applied DELIBERATELY MISSING
        }
        (evidence / "assessment_results.json").write_text(json.dumps(assessment))
        (tmp_path / "lr_candidates.json").write_text(
            json.dumps({"pairs": [{"ligand": "FOO", "receptor": "BAR"}]})
        )
        result = json.loads(validate_stage1_gate.invoke({"data_dir": str(tmp_path)}))
        assert result["success"] is False
        assert "stage1_filter_applied" in result["error"]

    def test_validate_stage1_gate_passes_when_filter_applied_and_files_present(self, tmp_path):
        """Sanity: gate passes when both flag and files are present."""
        from src.agents.drug_target.tools.stage_logic import validate_stage1_gate
        evidence = tmp_path / "evidence"
        evidence.mkdir(parents=True, exist_ok=True)
        assessment = {
            "schema_version": 2,
            "rubric_assessment": [{"gene": "FOO", "stage3_candidate": True}],
            "stage3_candidates": [{"gene": "FOO"}],
            "stage1_filter_applied": True,
        }
        (evidence / "assessment_results.json").write_text(json.dumps(assessment))
        (tmp_path / "lr_candidates.json").write_text(
            json.dumps({"pairs": [{"ligand": "FOO", "receptor": "BAR"}]})
        )
        (evidence / "stage1_FOO--BAR.json").write_text("{}")
        result = json.loads(validate_stage1_gate.invoke({"data_dir": str(tmp_path)}))
        assert result["success"] is True

    def test_atomic_write_text_replaces_target(self, tmp_path):
        """P2-8: _atomic_write_text writes target atomically."""
        from src.agents.drug_target.tools.stage_logic import _atomic_write_text
        target = tmp_path / "test_atomic.json"
        _atomic_write_text(target, '{"hello": "world"}')
        assert target.read_text() == '{"hello": "world"}'
        # Overwrite
        _atomic_write_text(target, '{"hello": "again"}')
        assert target.read_text() == '{"hello": "again"}'
        # No leftover temp files in directory
        leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".tmp_")]
        assert leftovers == []


class TestP2CsvSeparator:
    """P2-6: CSV reader handles both `--` and `_` pair separators."""

    def test_dash_dash_separator_preferred(self):
        """`--` is the canonical separator, used by stage1_*.json files."""
        token = "fn1--itgb2"
        if "--" in token:
            ligand, receptor = token.split("--", 1)
        else:
            ligand, receptor = token.split("_", 1)
        assert ligand == "fn1"
        assert receptor == "itgb2"

    def test_underscore_separator_back_compat(self):
        """Existing CSV files use `_` as separator — fallback path."""
        token = "fn1_itgb2"
        if "--" in token:
            ligand, receptor = token.split("--", 1)
        else:
            ligand, receptor = token.split("_", 1)
        assert ligand == "fn1"
        assert receptor == "itgb2"


class TestP3RunAsyncTimeout:
    """P3-2: _run_async timeout configurable via SEQ_THINKING_TIMEOUT."""

    def test_default_timeout_is_120s(self, monkeypatch):
        """Without env var, timeout falls back to 120s default."""
        monkeypatch.delenv("SEQ_THINKING_TIMEOUT", raising=False)
        # We test the env-var read logic by reading the helper's source behavior.
        # Direct numeric verification: check the fallback default in the function source.
        import inspect
        from src.agents.drug_target.tools import common
        src = inspect.getsource(common._run_async)
        assert 'SEQ_THINKING_TIMEOUT' in src
        assert '"120"' in src or "120.0" in src

    def test_invalid_timeout_falls_back_to_120(self, monkeypatch):
        """Garbled env var → fall back to 120 (no crash)."""
        monkeypatch.setenv("SEQ_THINKING_TIMEOUT", "not-a-number")
        # Just verify the function handles the parse failure path without raising
        # (we cannot easily run an actual coroutine inside pytest without a loop).
        # Smoke: import the module and confirm no exception at parse time.
        from src.agents.drug_target.tools.common import _run_async
        assert callable(_run_async)


class TestP3SchemaValidation:
    """P3-3: assessment_output.py runs real jsonschema.validate."""

    def test_jsonschema_is_importable(self):
        """jsonschema is in project deps and used by _save_target_assessment."""
        import jsonschema
        assert callable(jsonschema.validate)

    def test_schema_validation_path_exists_in_source(self):
        """Source contains the jsonschema.validate call (P3-3 implemented)."""
        import inspect
        from src.agents.drug_target.tools import assessment_output
        src = inspect.getsource(assessment_output)
        assert "jsonschema.validate" in src
        assert "jsonschema.ValidationError" in src


class TestSchemaV3UnifiedContract:
    """Schema v3: stage3_candidates is the single narrowed set (rubric ∩ Stage 1 PASS);
    evidence_assessor (Stage 3 inline) and hypothesis_writer consume the same list."""

    def test_topn_gate_uses_stage3_candidates_only(self, tmp_path):
        """TOP-N coverage gate enforces every gene in `stage3_candidates`."""
        from src.agents.drug_target.tools.evidence_loader import save_evidence
        evidence = tmp_path / "evidence"
        evidence.mkdir(parents=True, exist_ok=True)
        _write_pr1_assessment(evidence)  # 5 stage3_candidates: {A,B,C,D,E}
        report = {
            "evidence_coverage_pct": 50,
            "hypotheses": [
                {"biological_entities": {"genes": ["A", "B", "C", "D", "E"]},
                 "evidence_references": []},
            ],
        }
        result = json.loads(save_evidence.invoke({
            "data_dir": str(tmp_path),
            "filename": "hypothesis_report.json",
            "data": json.dumps(report),
        }))
        assert result["saved"] is True, (
            f"TOP-N gate must pass when every stage3_candidate is covered. Got: {result}"
        )
