"""Tests for Drug Target Assessment Agent (Phase 4.7).

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
import math
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

    def test_evidence_collector_has_14_tools(self):
        from src.agents.drug_target.subagents.configs import SUBAGENT_CONFIGS
        tools = SUBAGENT_CONFIGS["evidence_collector"]["tools"]
        assert len(tools) == 14

    def test_clinical_assessor_has_5_tools(self):
        from src.agents.drug_target.subagents.configs import SUBAGENT_CONFIGS
        tools = SUBAGENT_CONFIGS["clinical_assessor"]["tools"]
        assert len(tools) == 5

    def test_report_writer_has_4_tools(self):
        from src.agents.drug_target.subagents.configs import SUBAGENT_CONFIGS
        tools = SUBAGENT_CONFIGS["report_writer"]["tools"]
        assert len(tools) == 4

    def test_evidence_collector_tool_names(self):
        from src.agents.drug_target.subagents.configs import SUBAGENT_CONFIGS
        tools = SUBAGENT_CONFIGS["evidence_collector"]["tools"]
        names = {t.name for t in tools}
        expected = {
            "load_lr_candidates",
            "sequential_thinking",
            "query_ot_target_info",
            "query_ot_known_drugs",
            "query_ot_drug_details",
            "query_gwas_trait_associations",
            "query_gwas_variant_details",
            "query_chembl_target_bioactivity",
            "query_chembl_drug_info",
            "search_clinical_trials",
            "query_fda_drug_label",
            "query_fda_adverse_events",
            "save_evidence",
            "think_tool",
        }
        assert names == expected

    def test_workflow_order(self):
        from src.agents.drug_target.subagents.configs import WORKFLOW_ORDER
        assert WORKFLOW_ORDER == ["evidence_collector", "clinical_assessor", "report_writer"]

    def test_get_subagents_returns_3(self):
        from src.agents.drug_target.subagents.configs import get_subagents
        subagents = get_subagents()
        assert len(subagents) == 3

    def test_get_subagents_order(self):
        from src.agents.drug_target.subagents.configs import get_subagents
        subagents = get_subagents()
        names = [s["name"] for s in subagents]
        assert names == ["evidence_collector", "clinical_assessor", "report_writer"]

    def test_custom_tools_appended_to_all_subagents(self):
        from src.agents.drug_target.subagents.configs import get_subagents
        mock_tool = MagicMock(spec=["name"])
        mock_tool.name = "custom_tool"
        subagents = get_subagents(custom_tools=[mock_tool])
        for s in subagents:
            tool_names = [t.name for t in s["tools"]]
            assert "custom_tool" in tool_names

    def test_evidence_collector_prompt_mentions_databases(self):
        from src.agents.drug_target.subagents.configs import SUBAGENT_CONFIGS
        prompt = SUBAGENT_CONFIGS["evidence_collector"]["system_prompt"]
        for keyword in ("OpenTargets", "GWAS", "ChEMBL", "FDA"):
            assert keyword in prompt

    def test_clinical_assessor_prompt_mentions_rubric(self):
        from src.agents.drug_target.subagents.configs import SUBAGENT_CONFIGS
        prompt = SUBAGENT_CONFIGS["clinical_assessor"]["system_prompt"]
        assert "rubric" in prompt.lower()
        assert "validated" in prompt.lower()
        assert "exploratory" in prompt.lower()

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

    def test_import_opentargets_tools(self):
        from src.agents.drug_target.tools import opentargets_tools
        assert opentargets_tools.query_ot_target_info.name == "query_ot_target_info"
        assert opentargets_tools.query_ot_known_drugs.name == "query_ot_known_drugs"
        assert opentargets_tools.query_ot_drug_details.name == "query_ot_drug_details"

    def test_import_gwas_tools(self):
        from src.agents.drug_target.tools import gwas_tools
        assert gwas_tools.query_gwas_trait_associations.name == "query_gwas_trait_associations"
        assert gwas_tools.query_gwas_variant_details.name == "query_gwas_variant_details"

    def test_import_chembl_tools(self):
        from src.agents.drug_target.tools import chembl_tools
        assert chembl_tools.query_chembl_target_bioactivity.name == "query_chembl_target_bioactivity"
        assert chembl_tools.query_chembl_drug_info.name == "query_chembl_drug_info"

    def test_import_clinical_trials_tools(self):
        from src.agents.drug_target.tools import clinical_trials_tools
        assert clinical_trials_tools.search_clinical_trials.name == "search_clinical_trials"

    def test_import_fda_tools(self):
        from src.agents.drug_target.tools import fda_tools
        assert fda_tools.query_fda_drug_label.name == "query_fda_drug_label"
        assert fda_tools.query_fda_adverse_events.name == "query_fda_adverse_events"

    def test_init_all_exports(self):
        from src.agents.drug_target.tools import __all__
        expected = [
            "query_ot_target_info", "query_ot_known_drugs", "query_ot_drug_details",
            "query_gwas_trait_associations", "query_gwas_variant_details",
            "query_chembl_target_bioactivity", "query_chembl_drug_info",
            "search_clinical_trials",
            "query_fda_drug_label", "query_fda_adverse_events",
            "load_lr_candidates", "load_evidence_files", "save_evidence",
            "think_tool", "sequential_thinking", "validate_quality",
        ]
        assert set(__all__) == set(expected)

    def test_import_common_sequential_thinking(self):
        from src.agents.drug_target.tools.common import sequential_thinking
        assert sequential_thinking.name == "sequential_thinking"


# =========================================================================
# 5. TestToolMocks — External API tools with mocked responses
# =========================================================================

class TestToolMocks:
    """External API tools tested with monkeypatched module-level references."""

    # --- OpenTargets ---

    def test_query_ot_target_info(self, monkeypatch):
        import src.agents.drug_target.tools.opentargets_tools as ot_mod

        monkeypatch.setattr(ot_mod, "search_entities", lambda q, entity_types=None: [
            {"id": "ENSG00000105329", "name": "TGFB1"}
        ])
        monkeypatch.setattr(ot_mod, "get_target_info", lambda eid, include_diseases=False: {
            "approvedSymbol": "TGFB1",
            "tractability": {"smallmolecule": {"topCategory": "clinical_precedence"}},
        })
        monkeypatch.setattr(ot_mod, "get_target_disease_evidence", lambda eid, efo: [
            {"score": 0.8, "datatypeId": "genetic_association"}
        ])
        monkeypatch.setattr(ot_mod, "get_target_associations", lambda eid, min_score=0: [
            {"disease": {"name": "breast carcinoma"}, "score": 0.75}
        ])

        raw = ot_mod.query_ot_target_info.invoke({
            "gene_symbol": "TGFB1",
            "disease": "breast cancer",
        })
        result = json.loads(raw)
        assert result["ensembl_id"] == "ENSG00000105329"
        assert result["target_info"]["approvedSymbol"] == "TGFB1"
        assert len(result["disease_evidence"]) == 1

    def test_query_ot_known_drugs(self, monkeypatch):
        import src.agents.drug_target.tools.opentargets_tools as ot_mod

        monkeypatch.setattr(ot_mod, "search_entities", lambda q, entity_types=None: [
            {"id": "EFO_0000305"}
        ])
        monkeypatch.setattr(ot_mod, "get_known_drugs_for_disease", lambda efo_id: {
            "uniqueDrugs": 42,
            "uniqueTargets": 15,
            "rows": [{"drug": {"name": "Trastuzumab"}, "phase": 4}],
        })

        raw = ot_mod.query_ot_known_drugs.invoke({"disease": "breast cancer"})
        result = json.loads(raw)
        assert result["unique_drugs"] == 42
        assert len(result["drugs"]) == 1

    def test_query_ot_target_info_unresolvable_gene(self, monkeypatch):
        import src.agents.drug_target.tools.opentargets_tools as ot_mod
        monkeypatch.setattr(ot_mod, "search_entities", lambda q, entity_types=None: [])

        raw = ot_mod.query_ot_target_info.invoke({
            "gene_symbol": "FAKEGENE",
            "disease": "breast cancer",
        })
        result = json.loads(raw)
        assert result["ensembl_id"] is None
        assert any("Could not resolve" in e for e in result["errors"])

    # --- GWAS ---

    def test_query_gwas_trait_associations(self, monkeypatch):
        import src.agents.drug_target.tools.gwas_tools as gwas_mod

        call_count = {"n": 0}

        def mock_fetch(url, params=None):
            call_count["n"] += 1
            if "findByEfoTrait" in url:
                return {"_embedded": {"efoTraits": [{"shortForm": "EFO_0000305"}]}}
            if "associations" in url:
                return {
                    "_embedded": {"associations": [{
                        "pvalue": 5e-9,
                        "strongestRiskAlleles": [{"riskAlleleName": "rs123-A"}],
                        "loci": [{"authorReportedGenes": [{"geneName": "TGFB1"}]}],
                        "snps": [],
                    }]},
                    "page": {"totalPages": 1},
                }
            return {}

        monkeypatch.setattr(gwas_mod, "_fetch_json", mock_fetch)

        raw = gwas_mod.query_gwas_trait_associations.invoke({
            "disease": "breast cancer",
            "gene_symbols": "TGFB1,VEGFA",
        })
        result = json.loads(raw)
        assert result["trait_id"] == "EFO_0000305"
        assert result["gene_signals"]["TGFB1"]["reported_hits"] >= 1
        assert result["total_associations_scanned"] == 1

    def test_query_gwas_variant_details(self, monkeypatch):
        import src.agents.drug_target.tools.gwas_tools as gwas_mod

        def mock_fetch(url, params=None):
            return {
                "genomicContexts": [
                    {"gene": {"geneName": "TGFB1"}, "distance": 0,
                     "isClosestGene": True, "isIntergenic": False}
                ],
                "locations": [{"chromosomeName": "19", "chromosomePosition": 41836812}],
                "functionalClass": "missense_variant",
            }

        monkeypatch.setattr(gwas_mod, "_fetch_json", mock_fetch)

        raw = gwas_mod.query_gwas_variant_details.invoke({"rs_ids": "rs1800469"})
        result = json.loads(raw)
        assert "rs1800469" in result["variants"]
        assert result["variants"]["rs1800469"]["functional_class"] == "missense_variant"

    def test_association_signal_genome_wide(self):
        from src.agents.drug_target.tools.gwas_tools import _association_signal
        score = _association_signal(5e-8)
        expected = -math.log10(5e-8) / 12.0
        assert abs(score - expected) < 1e-6

    def test_association_signal_zero_pvalue(self):
        from src.agents.drug_target.tools.gwas_tools import _association_signal
        assert _association_signal(0) == 1.0

    def test_association_signal_large_pvalue(self):
        from src.agents.drug_target.tools.gwas_tools import _association_signal
        score = _association_signal(0.5)
        assert 0.0 < score < 0.1  # weak signal

    # --- ChEMBL ---

    def test_query_chembl_target_bioactivity(self, monkeypatch):
        import src.agents.drug_target.tools.chembl_tools as chembl_mod

        mock_search = MagicMock(return_value=[
            {"target_chembl_id": "CHEMBL4439", "pref_name": "TGFB1",
             "organism": "Homo sapiens", "target_type": "SINGLE PROTEIN"},
        ])
        mock_bioactivity = MagicMock(return_value=[
            {"molecule_chembl_id": "CHEMBL123", "molecule_pref_name": "Galunisertib",
             "standard_type": "IC50", "standard_value": "56", "pchembl_value": "7.25"},
        ])

        monkeypatch.setattr(chembl_mod, "_import_chembl", lambda: (
            mock_search, mock_bioactivity, None
        ))

        raw = chembl_mod.query_chembl_target_bioactivity.invoke({"gene_symbol": "TGFB1"})
        result = json.loads(raw)
        assert len(result["targets"]) == 1
        assert result["targets"][0]["chembl_id"] == "CHEMBL4439"
        assert result["bioactivity_count"] == 1

    def test_query_chembl_drug_info(self, monkeypatch):
        import src.agents.drug_target.tools.chembl_tools as chembl_mod

        mock_get_drug = MagicMock(return_value=(
            {"pref_name": "Aspirin", "max_phase": 4, "first_approval": 1899,
             "molecule_type": "Small molecule", "withdrawn_flag": False},
            [{"action_type": "INHIBITOR", "mechanism_of_action": "COX inhibition",
              "target_pref_name": "COX-2", "target_chembl_id": "CHEMBL230"}],
            [{"mesh_heading": "Pain", "max_phase_for_ind": 4}],
        ))

        monkeypatch.setattr(chembl_mod, "_import_chembl", lambda: (None, None, mock_get_drug))

        raw = chembl_mod.query_chembl_drug_info.invoke({"chembl_id": "CHEMBL25"})
        result = json.loads(raw)
        assert result["drug_info"]["name"] == "Aspirin"
        assert result["drug_info"]["max_phase"] == 4
        assert len(result["mechanisms"]) == 1

    def test_chembl_unavailable_returns_error(self, monkeypatch):
        import src.agents.drug_target.tools.chembl_tools as chembl_mod
        monkeypatch.setattr(chembl_mod, "_import_chembl", lambda: (None, None, None))

        raw = chembl_mod.query_chembl_target_bioactivity.invoke({"gene_symbol": "TGFB1"})
        result = json.loads(raw)
        assert any("not installed" in e for e in result["errors"])

    # --- Clinical Trials ---

    def test_search_clinical_trials(self, monkeypatch):
        import src.agents.drug_target.tools.clinical_trials_tools as ct_mod

        monkeypatch.setattr(ct_mod, "search_studies", lambda condition, intervention=None, page_size=50: {
            "totalCount": 5,
            "studies": [
                {"mock_study": True},
                {"mock_study": True},
            ],
        })
        monkeypatch.setattr(ct_mod, "extract_study_summary", lambda study: {
            "nct_id": "NCT12345678",
            "title": "TGFB1 inhibitor Phase 2",
            "status": "RECRUITING",
            "phase": ["PHASE2"],
            "enrollment": 120,
        })

        raw = ct_mod.search_clinical_trials.invoke({
            "disease": "breast cancer",
            "gene_symbol": "TGFB1",
        })
        result = json.loads(raw)
        assert result["trial_count"] == 5
        assert result["phase_distribution"]["PHASE2"] == 2
        assert result["top_trials"][0]["nct_id"] == "NCT12345678"

    def test_search_clinical_trials_missing_total_count_falls_back_to_study_count(self, monkeypatch):
        import src.agents.drug_target.tools.clinical_trials_tools as ct_mod

        monkeypatch.setattr(ct_mod, "search_studies", lambda condition, intervention=None, page_size=50: {
            "studies": [
                {"mock_study": True},
                {"mock_study": True},
                {"mock_study": True},
            ],
        })
        monkeypatch.setattr(ct_mod, "extract_study_summary", lambda study: {
            "nct_id": "NCT12345678",
            "title": "TGFB1 inhibitor Phase 2",
            "status": "RECRUITING",
            "phase": ["PHASE2"],
            "enrollment": 120,
        })

        raw = ct_mod.search_clinical_trials.invoke({
            "disease": "breast cancer",
            "gene_symbol": "TGFB1",
        })
        result = json.loads(raw)
        assert result["trial_count"] == 3
        assert result["phase_distribution"]["PHASE2"] == 3

    # --- FDA ---

    def test_query_fda_drug_label(self, monkeypatch):
        import src.agents.drug_target.tools.fda_tools as fda_mod

        mock_client = MagicMock()
        mock_client.query_drug_label.return_value = {
            "results": [{
                "indications_and_usage": ["Treatment of breast cancer"],
                "warnings": ["Cardiotoxicity risk"],
                "contraindications": ["Hypersensitivity"],
                "adverse_reactions": ["Nausea, fatigue"],
            }],
        }
        monkeypatch.setattr(fda_mod, "_get_fda_client", lambda: mock_client)

        raw = fda_mod.query_fda_drug_label.invoke({"drug_name": "trastuzumab"})
        result = json.loads(raw)
        assert result["label_found"] is True
        assert "breast cancer" in result["indications"]

    def test_query_fda_adverse_events(self, monkeypatch):
        import src.agents.drug_target.tools.fda_tools as fda_mod

        mock_client = MagicMock()
        mock_client.query.return_value = {
            "results": [
                {"term": "Nausea", "count": 500},
                {"term": "Fatigue", "count": 300},
            ],
        }
        monkeypatch.setattr(fda_mod, "_get_fda_client", lambda: mock_client)

        raw = fda_mod.query_fda_adverse_events.invoke({"drug_name": "trastuzumab"})
        result = json.loads(raw)
        assert result["total_events"] == 800
        assert len(result["top_reactions"]) == 2
        assert result["top_reactions"][0]["reaction"] == "Nausea"


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
        # 3 compiled subagents + 1 orchestrator
        assert mock_create_deep_agent.call_count == 4

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

        mock_agent = MagicMock()

        async def mock_ainvoke(input_dict, config=None):
            # Simulate agent writing drug.md
            (mock_data_dir / "drug.md").write_text(mock_report)
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

    @patch("src.agents.drug_target.agent.create_deep_agent")
    @patch("src.agents.drug_target.agent.create_llm")
    def test_create_agent_passes_subagents_with_3_entries(
        self, mock_create_llm, mock_create_deep_agent, tmp_path
    ):
        from src.agents.drug_target.agent import create_drug_target_agent, DrugTargetConfig

        mock_create_llm.return_value = MagicMock()
        mock_create_deep_agent.return_value = MagicMock()

        config = DrugTargetConfig(data_dir=str(tmp_path))
        create_drug_target_agent(config)

        call_kwargs = mock_create_deep_agent.call_args
        subagents = call_kwargs.kwargs.get("subagents") or call_kwargs[1].get("subagents")
        assert len(subagents) == 3
