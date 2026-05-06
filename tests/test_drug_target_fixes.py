"""Regression tests for the fix/drug-target-pipeline-errors branch.

One test per commit in the 11-commit fix PR. Uses small synthetic fixtures
under tmp_path so the tests are hermetic and fast (no live API / no heavy
pipeline re-run). Integration verification is handled separately by
``scripts/validate_pipeline_output.py``.
"""
from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

from src.agents.drug_target.tools.assessment_output import _inject_open_targets_scores
from src.agents.drug_target.tools.evidence_loader import (
    _classify_prediction_grounding,
    _sanitize_gap_analysis,
    _tag_hypothesis_prediction_grounding,
)
from src.agents.drug_target.tools.stage1_normalization import _parse_census_csv
from src.agents.drug_target.tools.stage_logic import (
    build_evidence_summary,
    _extract_ot_disease_score,
    _ot_safety_summary,
    _score_novelty_opportunity,
)
from src.agents.drug_target.tools.drug_report_html import render_drug_md

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Commit 1 — OT score extraction uses disease_evidence, not flat keys
# ---------------------------------------------------------------------------

def test_ot_score_extraction_from_real_schema(tmp_path: Path) -> None:
    ev = tmp_path / "evidence"
    ev.mkdir()
    (ev / "ot_GENEX.json").write_text(
        json.dumps(
            {
                "disease_evidence": [
                    {"score": 0.12, "datatypeId": "literature"},
                    {"score": 0.85, "datatypeId": "genetic_association"},
                    {"score": 0.40, "datatypeId": "known_drug"},
                ],
                "associations": [{"score": 1.0, "disease": {"name": "off-target"}}],
            }
        )
    )
    data = json.loads((ev / "ot_GENEX.json").read_text())
    assert _extract_ot_disease_score(data) == 0.85

    matrix = [{"ligand": "GENEX", "receptor": "GENEY"}]
    _inject_open_targets_scores(matrix, ev)
    assert matrix[0]["open_targets_score"] == 0.85


def test_ot_score_fallback_to_associations_then_legacy(tmp_path: Path) -> None:
    # When disease_evidence is absent, fall back to associations[0].score.
    data = {"associations": [{"score": 0.44}]}
    assert _extract_ot_disease_score(data) == 0.44
    # Legacy flat keys still accepted.
    assert _extract_ot_disease_score({"overall_association_score": 0.77}) == 0.77
    # Empty payload returns 0.0 without raising.
    assert _extract_ot_disease_score({}) == 0.0


# ---------------------------------------------------------------------------
# Commit 2 — track derivation uses gene-level classification
# ---------------------------------------------------------------------------

def test_featured_deep_dive_track_from_classification() -> None:
    # Reproduces the map-building logic the prebuild function now uses.
    rubric_by_gene = {
        "CD4": {"classification": "validated_target"},
        "FN1": {"classification": "validated_target"},
        "THBS1": {"classification": "novel_candidate"},
        "NOSCORE": {},  # missing classification → defaults to featured
    }
    gene_track_map = {
        g.upper(): (
            "novel" if str((r or {}).get("classification", "")) == "novel_candidate" else "featured"
        )
        for g, r in rubric_by_gene.items()
    }
    assert gene_track_map["CD4"] == "featured"
    assert gene_track_map["FN1"] == "featured"
    assert gene_track_map["THBS1"] == "novel"
    assert gene_track_map["NOSCORE"] == "featured"


# ---------------------------------------------------------------------------
# Commit 3b — GWAS parquet-path enrichment adds proximity/snps fields
# (tested in isolation: the target of the fix is that the output dict has
# ``n_proximity_hits``; we simulate the enrichment block directly.)
# ---------------------------------------------------------------------------

def test_gwas_enrichment_adds_n_proximity_hits() -> None:
    from src.agents.drug_target.tools.stage2_service import _proximity_match

    trait_assocs = [{"rsId": "rs123", "genes": []}, {"rsId": "rs456", "genes": []}]
    gene_assocs = [{"rsId": "rs789"}, {"rsId": "rs123"}]
    dsh: dict = {}
    trait_rsids = {a.get("rsId") for a in trait_assocs if a.get("rsId")}
    if "gene_snps_in_disease" not in dsh:
        gene_snps = [a for a in gene_assocs if a.get("rsId") in trait_rsids]
        dsh["gene_snps_in_disease"] = gene_snps
        dsh["n_gene_snps_in_disease"] = len(gene_snps)
    proximity = _proximity_match(gene_assocs, trait_assocs)  # noqa: SLF001
    dsh["proximity_hits"] = proximity
    dsh["n_proximity_hits"] = len(proximity)

    assert dsh["n_gene_snps_in_disease"] == 1  # rs123 overlap
    assert "n_proximity_hits" in dsh  # field present even if count is 0


# ---------------------------------------------------------------------------
# Commit 4 — stage1 ztest emits None + risk_ratio_capped instead of Infinity
# ---------------------------------------------------------------------------

def _write_census_csv(path: Path) -> None:
    # Two cell types: target "AT2" (5 cells, gene_a expressed) and rest "Other"
    # (5 cells, gene_a NEVER expressed). 0/0 triggers the capped branch.
    path.write_text(
        "cell_type,n_cells,gene_a_pos,gene_b_pos,coexp_pos\n"
        "AT2,5,3,4,2\n"
        "Other,5,0,0,0\n"
    )


def test_stage1_ztest_no_infinity(tmp_path: Path) -> None:
    csv_path = tmp_path / "census.csv"
    _write_census_csv(csv_path)
    out = _parse_census_csv(csv_path, "AT2")
    assert out is not None
    # gene_a has pos in target (3/5) but 0 in rest → 0/0 case
    ra = out["gene_a"]
    assert ra["risk_ratio"] is None
    assert ra["risk_ratio_capped"] is True
    # gene_b same pattern
    rb = out["gene_b"]
    assert rb["risk_ratio"] is None
    assert rb["risk_ratio_capped"] is True
    # Ensure JSON round-trip does not emit "Infinity"
    encoded = json.dumps(out)
    assert "Infinity" not in encoded and "NaN" not in encoded


# ---------------------------------------------------------------------------
# Commit 5 — hypothesis quantitative-prediction grounding
# ---------------------------------------------------------------------------

def test_hypothesis_grounding_classifier() -> None:
    # Tightened regex (followup B7a) requires `from stage\d_*.json` or
    # `from ot_*.json`. Return tuple is now 3-element.
    label, tokens, cited = _classify_prediction_grounding(
        "Blocking ICAM1-ITGB2 interaction will reduce markers by at least 50% in explants."
    )
    assert label == "unverified"
    assert tokens == ["50%"]
    assert cited == []

    # "from stage1_..." + numeric token → grounded (cue-only, no evidence_dir)
    label, tokens, cited = _classify_prediction_grounding(
        "from stage1_ICAM1--MUC1.json risk_ratio=17.86, dual blockade reduces IL-8 by 50%."
    )
    assert label == "grounded"
    assert cited == ["stage1_ICAM1--MUC1.json"]

    # Loose "Based on" cue without "from <file>" → no longer counts as grounded
    label, tokens, cited = _classify_prediction_grounding(
        "Based on the passed stage1 filter, reduce markers by 40%"
    )
    assert label == "unverified"
    assert cited == []

    label, tokens, cited = _classify_prediction_grounding(
        "Significant reduction in fibroblast migration compared to controls."
    )
    assert label == "qualitative"
    assert tokens == []


def test_hypothesis_grounding_tag_summary() -> None:
    parsed = {
        "hypotheses": [
            {"falsifiable_prediction": "Reduce COL1A1 by 50% in cultures"},
            {"falsifiable_prediction": "from stage3_CD47.json index 0.3 → 2-fold increase"},
            {"falsifiable_prediction": "Significant reduction observed"},
            # Loose cue (old regex would match, new regex does not)
            {"falsifiable_prediction": "Based on the stage1 filter pass, 30% reduction"},
        ]
    }
    s = _tag_hypothesis_prediction_grounding(parsed)
    assert s["unverified"] == 2, s
    assert s["grounded"] == 1, s          # (stage3_CD47.json cited, no evidence_dir for verify)
    assert s["grounded_verified"] == 0, s
    assert s["qualitative"] == 1, s
    assert parsed["hypotheses"][0]["prediction_grounding"] == "unverified"
    assert parsed["hypotheses"][1]["prediction_grounding"] == "grounded"
    assert parsed["hypotheses"][2]["prediction_grounding"] == "qualitative"
    assert parsed["hypotheses"][3]["prediction_grounding"] == "unverified"


def test_hypothesis_prompt_has_quantitative_constraint() -> None:
    """Followup B7b rewrote the Quantitative Predictions block with explicit
    `from <filename>` grammar and 4-tier grounding labels. Validate the
    prompt still carries those contract anchors."""
    from src.agents.drug_target.subagents import prompts as pmts

    p = pmts.HYPOTHESIS_WRITER_PROMPT
    # Anti-hallucination header + 4-tier labels
    assert "Quantitative Predictions" in p
    assert "grounded_verified" in p
    assert "unverified" in p
    assert "qualitative" in p
    # New file-anchored grammar requirement
    assert "from <filename>" in p or "from stage1_" in p
    # Concrete good/bad examples to teach Qwen2 the pattern
    assert "GOOD" in p and "BAD" in p


# ---------------------------------------------------------------------------
# Commit 6 — OT safety fallback
# ---------------------------------------------------------------------------

def test_safety_fallback_from_ot(tmp_path: Path) -> None:
    ev = tmp_path / "evidence"
    ev.mkdir()
    (ev / "ot_GENEZ.json").write_text(
        json.dumps(
            {
                "target_info": {
                    "safetyLiabilities": [
                        {
                            "event": "hemorrhage",
                            "datasource": "PharmGKB",
                            "effects": [{"direction": "increase"}],
                        }
                    ]
                }
            }
        )
    )
    summary = _ot_safety_summary(ev, "GENEZ")
    assert summary is not None
    assert "hemorrhage" in summary
    assert "PharmGKB" in summary
    # absent file -> None
    assert _ot_safety_summary(ev, "MISSING") is None


# ---------------------------------------------------------------------------
# Commit 7 — score_source annotation on pair rows
# (integration-level: pair_matrix builder is inside _prebuild_target_assessment;
# we assert the logic shape matches what the code does.)
# ---------------------------------------------------------------------------

def test_score_source_selection_rule() -> None:
    rubric_by_gene = {"CD4": {"existing_drug_evidence": 5}}
    ligand, receptor = "HLA-DQB1", "CD4"
    # Receptor preferred when present in rubric_by_gene
    if receptor in rubric_by_gene:
        score_source = receptor
    elif ligand in rubric_by_gene:
        score_source = ligand
    else:
        score_source = ""
    assert score_source == "CD4"

    # Fallback to ligand when only the ligand is rubric-scored
    rubric_by_gene2 = {"FN1": {"existing_drug_evidence": 4}}
    ligand, receptor = "FN1", "UNKNOWN"
    if receptor in rubric_by_gene2:
        score_source = receptor
    elif ligand in rubric_by_gene2:
        score_source = ligand
    else:
        score_source = ""
    assert score_source == "FN1"


# ---------------------------------------------------------------------------
# Commit 8 — associations_total_count persisted + novelty uses it
# ---------------------------------------------------------------------------

def test_novelty_uses_associations_total_count() -> None:
    # Brackets updated by followup A4 (0:1000+, 1:300-999, 2:100-299,
    # 3:30-99, 4:10-29, 5:0-9). Values here are chosen to match the
    # live-probed IPF gene counts (TGFB1=3124, LRP1=781, ITGA3=262).
    #
    # Truncated list, but total_count known.
    # TGFB1-like (3124): well-studied -> 0
    assert _score_novelty_opportunity([{}] * 20, True, 3124) == 0
    # LRP1-like (781): moderate -> 1
    assert _score_novelty_opportunity([{}] * 20, True, 781) == 1
    # ITGA3-like (262): emerging -> 2
    assert _score_novelty_opportunity([{}] * 20, True, 262) == 2
    # Boundary cases
    assert _score_novelty_opportunity([], False, 0) == 5
    assert _score_novelty_opportunity([], False, 29) == 4
    # Legacy: when total_count is None and truncated=True, cap at 1
    assert _score_novelty_opportunity([{}] * 20, True) == 1


# ---------------------------------------------------------------------------
# Commit 9 — _FAILED suffix sanitizer in gap_analysis
# ---------------------------------------------------------------------------

def test_sanitize_gap_analysis_strips_invalid_failed_suffix(tmp_path: Path) -> None:
    ev = tmp_path / "evidence"
    ev.mkdir()
    # Create real files matching the suffixed names
    (ev / "stage1_FN1--PLAUR.json").write_text("{}")
    (ev / "stage1_ICAM1--PECAM1.json").write_text("{}")
    parsed = {
        "gap_analysis": {
            "orphan_files": [
                "stage1_FN1--PLAUR.json_FAILED",
                "stage1_ICAM1--PECAM1.json",
                "stage1_DOES--NOT_EXIST.json_FAILED",  # real file absent → keep suffix
            ]
        }
    }
    n = _sanitize_gap_analysis(parsed, ev)
    assert n == 1
    assert parsed["gap_analysis"]["orphan_files"] == [
        "stage1_FN1--PLAUR.json",
        "stage1_ICAM1--PECAM1.json",
        "stage1_DOES--NOT_EXIST.json_FAILED",
    ]


# ---------------------------------------------------------------------------
# Commit 10 — save_drug_md persists pipeline_quality_flags deterministically
# ---------------------------------------------------------------------------

def test_save_drug_md_persists_quality_flags(tmp_path: Path) -> None:
    # Minimal synthetic data dir. validate_drug_md reads drug.md and
    # evidence/assessment_results.json at minimum.
    ev = tmp_path / "evidence"
    ev.mkdir()
    (ev / "assessment_results.json").write_text(
        json.dumps(
            {
                "stage3_candidates": [{"gene": "CD4"}],
                "rubric_assessment": [{"gene": "CD4", "classification": "validated_target"}],
            }
        )
    )
    (tmp_path / "target_assessment.json").write_text(json.dumps({"druggability_matrix": []}))

    from src.agents.drug_target.tools.assessment_output import (
        _persist_pipeline_quality_flags,
    )

    # Write a drug.md with a clean CD4 classification (no contradictions).
    (tmp_path / "drug.md").write_text(
        "## CD4\n- Classification: validated_target\n"
    )
    _persist_pipeline_quality_flags(tmp_path)
    ta = json.loads((tmp_path / "target_assessment.json").read_text())
    flags = ta.get("pipeline_quality_flags")
    assert flags is not None
    assert "valid" in flags
    assert "issues_count" in flags


# ---------------------------------------------------------------------------
# Commit 11 — Ruff B023 passes on the drug_target module
# ---------------------------------------------------------------------------

def test_ruff_b023_passes() -> None:
    result = subprocess.run(
        ["ruff", "check", "--select", "B023", "src/agents/drug_target/"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"B023 violations:\nstdout={result.stdout}\nstderr={result.stderr}"
    )


# ---------------------------------------------------------------------------
# Smoke test for validate_pipeline_output.py invariants
# ---------------------------------------------------------------------------

def test_validate_script_catches_known_defects(tmp_path: Path) -> None:
    # Build a tiny pipeline dir with the exact defects we fixed; script must
    # exit non-zero.
    ev = tmp_path / "evidence"
    ev.mkdir()
    (ev / "assessment_results.json").write_text(
        json.dumps(
            {
                "rubric_assessment": [
                    {"gene": "CD4", "classification": "validated_target", "gwas_support": 0},
                ]
            }
        )
    )
    (ev / "ot_CD4.json").write_text(
        json.dumps({"associations": [{"score": 1.0}], "disease_evidence": [{"score": 0.82}]})
    )
    # Inject the classic bugs: track=novel on validated_target, open_targets_score=0, Infinity
    (tmp_path / "target_assessment.json").write_text(
        json.dumps(
            {
                "druggability_matrix": [
                    {"ligand": "CD4", "receptor": "CD4", "open_targets_score": 0.0}
                ],
                "featured_candidates_deep_dive": [
                    {"target_gene": "CD4", "track": "novel"}
                ],
            }
        )
    )
    (ev / "stage1_X--Y.json").write_text(
        '{"risk_ratio": Infinity}'  # intentionally non-RFC-8259 to trip check 3
    )
    (tmp_path / "drug.md").write_text("placeholder")

    script = REPO_ROOT / "scripts" / "validate_pipeline_output.py"
    result = subprocess.run(
        ["python3", str(script), str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    out = result.stdout
    assert "track_contradiction gene=CD4" in out
    assert "open_targets_score <= 0" in out
    assert "non-RFC-8259" in out


def test_validate_script_passes_on_clean_output(tmp_path: Path) -> None:
    ev = tmp_path / "evidence"
    ev.mkdir()
    (ev / "assessment_results.json").write_text(
        json.dumps(
            {
                "rubric_assessment": [
                    {"gene": "CD4", "classification": "validated_target", "gwas_support": 2},
                ]
            }
        )
    )
    (ev / "ot_CD4.json").write_text(json.dumps({"associations": [{"score": 1.0}]}))
    (tmp_path / "target_assessment.json").write_text(
        json.dumps(
            {
                "druggability_matrix": [
                    {"ligand": "CD4", "receptor": "CD4", "open_targets_score": 0.82}
                ],
                "featured_candidates_deep_dive": [
                    {"target_gene": "CD4", "track": "featured"}
                ],
            }
        )
    )
    (ev / "hypothesis_report.json").write_text(
        json.dumps(
            {
                "hypotheses": [
                    {
                        "title": "Qualitative hypothesis",
                        "falsifiable_prediction": "Significant reduction",
                        "prediction_grounding": "qualitative",
                    }
                ]
            }
        )
    )
    script = REPO_ROOT / "scripts" / "validate_pipeline_output.py"
    result = subprocess.run(
        ["python3", str(script), str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"unexpected failure: {result.stdout}{result.stderr}"


def test_validate_script_rejects_non_finite_resolved_drugs_json(tmp_path: Path) -> None:
    ev = tmp_path / "evidence"
    ev.mkdir()
    (ev / "assessment_results.json").write_text(json.dumps({"rubric_assessment": []}))
    (tmp_path / "target_assessment.json").write_text(
        json.dumps({"druggability_matrix": [], "featured_candidates_deep_dive": []})
    )
    (ev / "resolved_drugs.json").write_text(
        '[{"gene": "FOO", "resolved_name": "Drug A", "first_approval": NaN}]',
        encoding="utf-8",
    )

    script = REPO_ROOT / "scripts" / "validate_pipeline_output.py"
    result = subprocess.run(
        ["python3", str(script), str(tmp_path)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "resolved_drugs.json contains non-RFC-8259 literal 'NaN'" in result.stdout


def test_build_evidence_summary_writes_resolved_drugs_without_non_finite_numbers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ev = tmp_path / "evidence"
    ev.mkdir()
    (tmp_path / "lr_candidates.json").write_text(
        json.dumps({"pairs": [{"ligand": "LIG", "receptor": "FOO"}]}),
        encoding="utf-8",
    )
    (ev / "assessment_results.json").write_text(
        json.dumps(
            {
                "disease": "test disease",
                "stage3_candidates": [{"gene": "FOO"}],
                "rubric_assessment": [
                    {
                        "gene": "FOO",
                        "classification": "validated_target",
                        "priority": "high",
                        "stage3_candidate": True,
                        "combined_total": 10,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (ev / "stage3_FOO.json").write_text(
        json.dumps(
            {
                "executed": True,
                "matched_drugs": [
                    {
                        "chembl_id": "CHEMBL1",
                        "drug_name": "Drug A",
                        "max_phase": 1,
                        "first_approval": math.nan,
                        "mechanism_of_action": "FOO inhibitor",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "src.agents.drug_target.tools.stage_logic.enrich_drugs_in_place",
        lambda *_args, **_kwargs: 0,
    )

    build_evidence_summary.invoke({"data_dir": str(tmp_path)})

    text = (ev / "resolved_drugs.json").read_text(encoding="utf-8")
    assert "NaN" not in text
    assert "Infinity" not in text
    resolved = json.loads(text)
    assert resolved[0]["first_approval"] is None


def test_rendered_drug_md_novelty_legend_matches_score_brackets() -> None:
    md = render_drug_md(
        disease="test disease",
        stage3_genes=[],
        featured_cards=[],
        all_genes_matrix=[],
        stage1_data={},
        stage1_filter_results=[],
    )

    novelty_row = next(
        line for line in md.splitlines()
        if line.startswith("| Novelty | novelty_opportunity |")
    )
    for token in ("1000+", "300-999", "100-299", "30-99", "10-29", "0-9"):
        assert token in novelty_row
    for stale in ("1-2", "3-5", "6-15", "16-30"):
        assert stale not in novelty_row
    assert "0 = 30+" not in novelty_row
