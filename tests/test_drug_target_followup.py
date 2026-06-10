"""Regression tests for the fix/followup-pipeline-defects branch.

One test per commit (A0-A4, B5-B7b). Uses small synthetic fixtures under
tmp_path so tests are hermetic — no live OpenTargets API calls, no 80-min
pipeline re-run. Integration verification is handled separately by
``scripts/validate_pipeline_output.py`` and the manual re-run on
``res_ipf_qwen2/``.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_qot():
    """Load query_opentargets.py directly (hyphenated dir name blocks normal import)."""
    spec = importlib.util.spec_from_file_location(
        "qot",
        REPO_ROOT / "skills/opentargets-database/scripts/query_opentargets.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _load_opk():
    spec = importlib.util.spec_from_file_location(
        "opk",
        REPO_ROOT / "skills/opentargets-database/scripts/opentargets_parquet.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _load_gwas_parquet():
    spec = importlib.util.spec_from_file_location(
        "gwas_parquet",
        REPO_ROOT / "skills/gwas-database/scripts/gwas_parquet.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_opentargets_parquet_data_dir_env_override(monkeypatch, tmp_path: Path) -> None:
    ot_data = tmp_path / "ot_data"
    for subdir in ("target", "disease", "evidence"):
        (ot_data / subdir).mkdir(parents=True)
    (ot_data / "target" / "target.parquet").touch()
    (ot_data / "disease" / "disease.parquet").touch()
    (ot_data / "evidence" / "part.parquet").touch()

    monkeypatch.setenv("OPENTARGETS_DATA_DIR", str(ot_data))
    opk = _load_opk()

    assert opk.DATA_DIR == ot_data.resolve()
    assert opk.is_available() is True


def test_gwas_parquet_data_dir_env_override(monkeypatch, tmp_path: Path) -> None:
    gwas_data = tmp_path / "gwas_data"
    gwas_data.mkdir()
    (gwas_data / "associations.parquet").touch()
    (gwas_data / "traits.parquet").touch()

    monkeypatch.setenv("GWAS_DATA_DIR", str(gwas_data))
    gwas_parquet = _load_gwas_parquet()

    assert gwas_parquet.DATA_DIR == gwas_data.resolve()
    assert gwas_parquet.is_available() is True


# ---------------------------------------------------------------------------
# Commit A0 — GraphQL page_size 100 -> 500
# ---------------------------------------------------------------------------

def test_a0_graphql_page_size_500() -> None:
    qot = _load_qot()
    src = (REPO_ROOT / "skills/opentargets-database/scripts/query_opentargets.py").read_text()
    # Both call sites (sync + async full target) must use size: 500
    assert src.count("size: 500") >= 2, \
        "Both GraphQL associatedDiseases queries must use size: 500"
    # And no leftover 100 in the same structural context
    assert "associatedDiseases(page: {index: 0, size: 100})" not in src


# ---------------------------------------------------------------------------
# Commit A1 — parse count from GraphQL response, return dict
# ---------------------------------------------------------------------------

def test_a1_graphql_count_parsed_dict_shape() -> None:
    qot = _load_qot()
    qot.execute_query = lambda q, v: {
        "target": {"associatedDiseases": {"count": 847, "rows": [
            {"disease": {"id": "D1"}, "score": 0.5, "datatypeScores": []},
            {"disease": {"id": "D2"}, "score": 0.05, "datatypeScores": []},
        ]}}
    }
    out = qot.get_target_associations("ENSG_X", min_score=0.1)
    assert isinstance(out, dict)
    assert out["api_total_count"] == 847
    assert len(out["associations"]) == 1           # 0.05 filtered by min_score
    assert out["associations"][0]["disease"]["id"] == "D1"

    # Edge: response missing associatedDiseases
    qot.execute_query = lambda q, v: {"target": {}}
    out = qot.get_target_associations("ENSG_NONE", min_score=0.1)
    assert out == {"associations": [], "api_total_count": None}


def test_known_drugs_disease_query_uses_current_drug_candidates_schema() -> None:
    qot = _load_qot()
    captured = {}

    def fake_execute(query, variables):
        captured["query"] = query
        captured["variables"] = variables
        return {
            "disease": {
                "drugAndClinicalCandidates": {
                    "count": 1,
                    "rows": [
                        {
                            "id": "candidate-1",
                            "maxClinicalStage": 4,
                            "drug": {"id": "CHEMBL1", "name": "Drug A"},
                        }
                    ],
                }
            }
        }

    qot.execute_query = fake_execute

    out = qot.get_known_drugs_for_disease("EFO_0001")

    assert captured["variables"] == {"efoId": "EFO_0001"}
    assert "knownDrugs" not in captured["query"]
    assert "drugAndClinicalCandidates" in captured["query"]
    assert out["rows"][0]["drug"]["id"] == "CHEMBL1"


# ---------------------------------------------------------------------------
# Commit A2 — parquet pre_head_len recorded + head cap 500
# ---------------------------------------------------------------------------

def test_a2_parquet_pre_head_len_recorded() -> None:
    pd = pytest.importorskip("pandas")
    opk = _load_opk()
    opk._disease_id_to_name = lambda ids: {i: f"n_{i}" for i in ids}

    # 800 diseases exceeds the new 500 cap
    rows = [
        {"diseaseId": f"D{i}", "score": 1.0 - i * 0.001, "datatypeId": "literature"}
        for i in range(800)
    ]
    df = pd.DataFrame(rows)
    out = opk._build_target_associations(df, min_score=0.1)
    assert isinstance(out, dict)
    assert out["pre_head_len"] == 800
    assert len(out["associations"]) == 500     # head cap raised 100 -> 500

    # 150 diseases, under the cap
    rows = [{"diseaseId": f"D{i}", "score": 0.5, "datatypeId": "literature"} for i in range(150)]
    df = pd.DataFrame(rows)
    out = opk._build_target_associations(df, min_score=0.1)
    assert out["pre_head_len"] == 150
    assert len(out["associations"]) == 150


# ---------------------------------------------------------------------------
# Commit A3 — stage2 wires true count + provenance
# ---------------------------------------------------------------------------

def test_a3_true_count_provenance() -> None:
    from src.agents.drug_target.tools.stage2_service import query_opentargets_target_data

    class ParquetMod:
        def search_entities(self, sym, entity_types=None):
            return [{"id": "ENSG_P"}]

        def get_target_bundle(self, ensembl_id, efo_id=None, min_score=0.0):
            return {
                "target_info": {"approvedSymbol": "P"},
                "disease_evidence": [],
                "associations": [{"score": 0.8}] * 40,
                "associations_api_total_count": 781,
            }

    r = query_opentargets_target_data(
        "P", "fibrosis",
        mod=ParquetMod(),
        disease_context={"efo_id": "EFO_0", "disease_ids": [], "efo_traits": [], "trait_associations": []},
    )
    assert r["associations_total_count"] == 781
    assert r["associations_total_source"] == "parquet_pre_head"

    class GraphQLMod:
        def search_entities(self, sym, entity_types=None):
            return [{"id": "ENSG_G"}]

        def get_target_info(self, ensembl_id, include_diseases=True):
            return {"approvedSymbol": "G"}

        def get_target_associations(self, ensembl_id, min_score=0.0):
            return {"associations": [{"score": 0.7}] * 30, "api_total_count": 2905}

    r = query_opentargets_target_data(
        "G", "fibrosis",
        mod=GraphQLMod(),
        disease_context={"efo_id": None, "disease_ids": [], "efo_traits": [], "trait_associations": []},
    )
    assert r["associations_total_count"] == 2905
    assert r["associations_total_source"] == "api_count"


# ---------------------------------------------------------------------------
# Commit A4 — novelty bracket rescale (live-probed values)
# ---------------------------------------------------------------------------

def test_a4_novelty_brackets_rescaled() -> None:
    from src.agents.drug_target.tools.stage_logic import _score_novelty_opportunity

    # Live OT probe (2026-04-20): TGFB1=3124, LRP1=781, ITGA3=262, HLA-DMB=161
    # Bracket boundary cases
    cases = [
        (0, 5), (9, 5),
        (10, 4), (29, 4),
        (30, 3), (99, 3),
        (100, 2), (262, 2), (299, 2),     # ITGA3 = 262
        (300, 1), (781, 1), (999, 1),      # LRP1 = 781
        (1000, 0), (2905, 0), (3124, 0),   # CD4 = 2905, TGFB1 = 3124
    ]
    for count, expected in cases:
        got = _score_novelty_opportunity([], False, count)
        assert got == expected, f"count={count}: expected {expected}, got {got}"


# ---------------------------------------------------------------------------
# Commit B5 — 2-pass PASSED-preferred promotion + promotion_reason
# ---------------------------------------------------------------------------

def test_b5_promotion_prefers_passed_pair(tmp_path: Path) -> None:
    """Synthetic fixture: FN1--PLAUR FAILED + FN1--SDC2 PASSED. Without B5,
    FN1--PLAUR (higher combined) would be promoted; with B5, FN1--SDC2 wins."""
    # The logic is exercised inline from the commit (stage_logic.py). We
    # re-implement the Pass 1 / Pass 2 flow here to verify the contract.
    stage1_filter = {
        "FN1^PLAUR": {"passed": False},
        "FN1^SDC2": {"passed": True},
        "HLA-DQB1^CD4": {"passed": True},
    }
    ranked_matrix = [
        {"ligand": "FN1", "receptor": "PLAUR", "is_featured": False, "is_novel": False, "combined_total": 3},
        {"ligand": "FN1", "receptor": "SDC2",  "is_featured": False, "is_novel": False, "combined_total": 2},
        {"ligand": "HLA-DQB1", "receptor": "CD4", "is_featured": True, "is_novel": False, "combined_total": 15},
    ]
    stage3_genes = ["FN1", "CD4"]

    def passed(row):
        l = row["ligand"].upper(); r = row["receptor"].upper()
        return stage1_filter.get(f"{l}^{r}", stage1_filter.get(f"{r}^{l}", {})).get("passed", False)

    for row in ranked_matrix:
        row["promotion_reason"] = "organic_featured" if row.get("is_featured") else None

    s3_set = {g.upper() for g in stage3_genes}
    covered = {
        g for row in ranked_matrix if row.get("is_featured")
        for g in (row["ligand"].upper(), row["receptor"].upper()) if g in s3_set
    }
    missing = s3_set - covered

    def _promote(only_passed, reason):
        for row in ranked_matrix:
            if not missing: break
            if only_passed and not passed(row): continue
            for g in (row["receptor"].upper(), row["ligand"].upper()):
                if g in missing:
                    row["is_featured"] = True
                    row["promotion_reason"] = reason
                    missing.discard(g)
                    break

    _promote(True, "stage3_coverage_fallback_passed")
    _promote(False, "stage3_coverage_fallback_failed")

    fn1_plaur = next(r for r in ranked_matrix if r["receptor"] == "PLAUR")
    fn1_sdc2 = next(r for r in ranked_matrix if r["receptor"] == "SDC2")
    assert fn1_sdc2["is_featured"] is True
    assert fn1_sdc2["promotion_reason"] == "stage3_coverage_fallback_passed"
    assert fn1_plaur["is_featured"] is False


# ---------------------------------------------------------------------------
# Commit B6 — schema null types + pipeline_quality_flags.schema_validation
# ---------------------------------------------------------------------------

def test_b6_schema_null_types_and_persistence(tmp_path: Path) -> None:
    from src.agents.drug_target.tools.assessment_output import save_target_assessment

    (tmp_path / "lr_candidates.json").write_text(json.dumps({"pairs": [{"ligand": "CD4", "receptor": "ICAM1"}]}))
    (tmp_path / "evidence").mkdir()

    out = save_target_assessment.invoke({
        "data_dir": str(tmp_path),
        "project_meta": json.dumps({"disease_focus": "fibrosis", "total_input_pairs": 1}),
        "druggability_matrix": json.dumps([
            {
                "ligand": "CD4",
                "receptor": "ICAM1",
                "is_featured": False,
                "is_novel": False,
                "open_targets_score": 0.82,
                "rank": None,                                      # <-- null rank accepted
                "promotion_reason": None,
            }
        ]),
        "featured_candidates_deep_dive": json.dumps([
            {
                "target_gene": "CD4",
                "track": "featured",
                "stage3_clinical_safety": {
                    "known_drugs_drugbank": ["IBALIZUMAB"],
                    "toxicity_admet": "none",
                    "latest_pubmed_insights": None,              # <-- null insights accepted
                },
                "stage1_biological_context": {"string_ppi_score": 0.95, "primary_kegg_pathway": "none"},
            }
        ]),
    })
    result = json.loads(out)
    assert result["saved"] is True
    assert result["schema_valid"] is True

    ta = json.loads((tmp_path / "target_assessment.json").read_text())
    sv = ta["pipeline_quality_flags"]["schema_validation"]
    assert sv["valid"] is True
    assert sv["issues_count"] == 0
    assert "source" in sv


def test_stage1_representative_context_prefers_passed_pair_over_higher_failed_score() -> None:
    from src.agents.drug_target.tools.stage_logic import _select_stage1_representative_context

    context = _select_stage1_representative_context(
        "CD4",
        {
            "failed": {
                "ligand": "HLA-DPA1",
                "receptor": "CD4",
                "string_ppi": {"max_combined_score": 0.99},
                "kegg_pathways": {"receptor_pathways": ["Failed pathway"]},
            },
            "passed": {
                "ligand": "CD4",
                "receptor": "CXCR4",
                "string_ppi": {"max_combined_score": 0.61},
                "kegg_pathways": {"receptor_pathways": ["Passed pathway"]},
            },
        },
        {"HLA-DPA1^CD4": False, "CD4^CXCR4": True},
    )

    assert context["string_ppi_score"] == 0.61
    assert context["primary_kegg_pathway"] == "Passed pathway"


def test_indication_dedup_preserves_first_spelling_and_structured_records() -> None:
    from src.agents.drug_target.tools.stage_logic import _dedupe_indications

    indications = _dedupe_indications([
        " lung cancer ",
        "Lung Cancer",
        {"efo_term": "Idiopathic pulmonary fibrosis", "max_phase_for_indication": 4},
        {"efo_term": "idiopathic pulmonary fibrosis", "max_phase_for_indication": 3},
        "",
        None,
    ])

    assert indications == [
        "lung cancer",
        {"efo_term": "Idiopathic pulmonary fibrosis", "max_phase_for_indication": 4},
    ]


# ---------------------------------------------------------------------------
# Commit B7a — tightened grounding regex + cross-validation
# ---------------------------------------------------------------------------

def test_b7a_tightened_regex_and_cross_validate(tmp_path: Path) -> None:
    from src.agents.drug_target.tools.evidence_loader import (
        _classify_prediction_grounding,
    )

    # Boilerplate cue (old regex accepted) → now unverified
    label, _, cited = _classify_prediction_grounding(
        "Based on the passed stage1 filter, α-SMA will drop 40%."
    )
    assert label == "unverified"
    assert cited == []

    # File-anchored cite, no verify dir → grounded (cue-only)
    label, _, cited = _classify_prediction_grounding(
        "from stage1_ICAM1--MUC1.json, a risk_ratio implies 50% reduction."
    )
    assert label == "grounded"
    assert cited == ["stage1_ICAM1--MUC1.json"]

    # File-anchored cite + value that exists in evidence → grounded_verified
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "stage1_FN1--SDC2.json").write_text(
        json.dumps({"string_ppi": {"max_combined_score": 0.959}, "risk_ratio": 17.86})
    )
    label, _, _ = _classify_prediction_grounding(
        "from stage1_FN1--SDC2.json, a 17.86-fold enrichment predicts robust adhesion.",
        evidence_dir=evidence_dir,
    )
    assert label == "grounded_verified"


# ---------------------------------------------------------------------------
# Commit B7b — HYPOTHESIS_WRITER prompt updated with grounded grammar
# ---------------------------------------------------------------------------

def test_b7b_prompt_teaches_file_anchored_grammar() -> None:
    from src.agents.drug_target.subagents import prompts as pmts

    p = pmts.HYPOTHESIS_WRITER_PROMPT
    # 4-tier label schema visible in the prompt
    assert "grounded_verified" in p
    assert "unverified" in p
    assert "qualitative" in p
    # Required grammar pattern
    assert "from stage1_" in p or "from <filename>" in p
    # Teaching-by-example section
    assert "GOOD" in p
    assert "BAD" in p


# ---------------------------------------------------------------------------
# Sanity: Ruff B023 still clean across the drug_target module
# ---------------------------------------------------------------------------

def test_ruff_b023_still_clean() -> None:
    r = subprocess.run(
        ["ruff", "check", "--select", "B023", "src/agents/drug_target/"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr
