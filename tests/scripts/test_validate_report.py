from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "validate_report.py"
SPEC = importlib.util.spec_from_file_location("validate_report", SCRIPT_PATH)
assert SPEC and SPEC.loader
validate_report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validate_report)


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def test_flags_pmid_not_in_papers_json(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [{"pmid": "11111111", "title": "known"}])
    (tmp_path / "part1_final.md").write_text(
        "Supported PMID:11111111\nFake PMID:99999999\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    assert any(i["code"] == "pmid_not_in_papers" and i["value"] == "99999999" for i in issues)


def test_flags_pmid_when_papers_json_is_empty_handoff(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    (tmp_path / "part1_final.md").write_text("Fake PMID:99999999\n", encoding="utf-8")

    issues = validate_report.validate_report(tmp_path)

    assert any(i["code"] == "pmid_not_in_papers" and i["value"] == "99999999" for i in issues)


def test_reads_pmids_from_papers_json_object_shape(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", {"papers": [{"pmid": "11111111", "title": "known"}]})
    (tmp_path / "part1_final.md").write_text("Supported PMID:11111111\n", encoding="utf-8")

    issues = validate_report.validate_report(tmp_path)

    assert not any(i["code"] == "pmid_not_in_papers" for i in issues)


def test_flags_papers_json_when_unreadable(tmp_path: Path) -> None:
    (tmp_path / "papers.json").mkdir()
    (tmp_path / "part1_final.md").write_text("PMID:99999999\n", encoding="utf-8")

    issues = validate_report.validate_report(tmp_path)

    assert any(i["code"] == "papers_json_unreadable" for i in issues)


def test_flags_papers_json_when_malformed(tmp_path: Path) -> None:
    (tmp_path / "papers.json").write_text("{", encoding="utf-8")
    (tmp_path / "part1_final.md").write_text("PMID:99999999\n", encoding="utf-8")

    issues = validate_report.validate_report(tmp_path)

    assert any(i["code"] == "papers_json_malformed" for i in issues)


def test_flags_factor_pathway_significance_when_csv_lacks_claimed_pair(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana_pathway_factor.csv",
        [
            {"factor": "Factor2", "pathway": "NFkB", "estimate": -3.28, "p": 0.001, "adj_p": 0.025},
            {"factor": "Factor3", "pathway": "EGFR", "estimate": 2.5, "p": 0.001, "adj_p": 0.025},
        ],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-8: Pathway Factor Heatmap\n"
        "### Biological Interpretation\n"
        "Factor2 showed significant enrichment for NFkB and EGFR.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    flagged = [i for i in issues if i["code"] == "unsupported_pathway_factor_significance"]
    assert len(flagged) == 1
    assert flagged[0]["value"] == "Factor2: EGFR"


def test_flags_only_unsupported_claimed_pathways_for_same_factor(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana_pathway_factor.csv",
        [
            {"factor": "Factor4", "pathway": "Hypoxia", "estimate": 2.1, "p": 0.001, "adj_p": 0.025},
            {"factor": "Factor8", "pathway": "MAPK", "estimate": 2.1, "p": 0.001, "adj_p": 0.025},
        ],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-8: Pathway Factor Heatmap\n"
        "### Biological Interpretation\n"
        "Factor4 showed significant enrichment for MAPK and Hypoxia.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    flagged = [i for i in issues if i["code"] == "unsupported_pathway_factor_significance"]
    assert len(flagged) == 1
    assert flagged[0]["value"] == "Factor4: MAPK"


def test_ignores_negated_factor1_pathway_significance(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana_pathway_factor.csv",
        [{"factor": "Factor1", "pathway": "Hypoxia", "estimate": 2.1, "p": 0.001, "adj_p": 0.025}],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-8: Pathway Factor Heatmap\n"
        "### Biological Interpretation\n"
        "Factor1 showed significant enrichment for Hypoxia. MAPK was not significant for Factor1.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    assert not any(i["code"] == "unsupported_pathway_factor_significance" for i in issues)


def test_allows_factor1_hypothesis_language(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana_pathway_factor.csv",
        [{"factor": "Factor2", "pathway": "NFkB", "estimate": -3.28, "p": 0.001, "adj_p": 0.025}],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-8: Pathway Factor Heatmap\n"
        "### Biological Interpretation\n"
        "Factor1 may reflect TGFb/MAPK programs inferred from LR annotations, not pathway-factor significance.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    assert not any(i["code"] == "unsupported_pathway_factor_significance" for i in issues)


def test_flags_factor_pathway_claim_when_pathway_only_exists_in_decoupler_vocab(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana_pathway_factor.csv",
        [{"factor": "Factor3", "pathway": "EGFR", "estimate": -2.9, "pval": 0.004, "adj_pval": 0.028}],
    )
    _write_csv(
        tmp_path / "sig_PathwayEnrich_decoupler.csv",
        [{"group": "4", "reference": "rest", "name": "PI3K", "stat": 33.0, "meanchange": 3.7, "pval": 0.0, "fdr": 0.0}],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-8: Pathway-Factor\n"
        "### Biological Interpretation\n"
        "Factor3 shows significant PI3K enrichment.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    flagged = [i for i in issues if i["code"] == "unsupported_pathway_factor_significance"]
    assert len(flagged) == 1
    assert flagged[0]["value"] == "Factor3: PI3K"


def test_flags_factor_pathway_direction_mismatch_for_negative_estimate(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana_pathway_factor.csv",
        [{"factor": "Factor3", "pathway": "EGFR", "estimate": -2.897, "pval": 0.004, "adj_pval": 0.028}],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-8: Pathway-Factor\n"
        "### Biological Interpretation\n"
        "Factor3 shows EGFR enrichment and activation.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    flagged = [i for i in issues if i["code"] == "factor_pathway_direction_mismatch"]
    assert len(flagged) == 1
    assert flagged[0]["value"] == "Factor3: EGFR estimate=-2.897"


def test_allows_multi_factor_sentence_when_local_factor_pathway_pairs_match(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana_pathway_factor.csv",
        [
            {"factor": "Factor2", "pathway": "Hypoxia", "estimate": 2.1, "pval": 0.004, "adj_pval": 0.028},
            {"factor": "Factor3", "pathway": "Estrogen", "estimate": -1.7, "pval": 0.004, "adj_pval": 0.028},
            {"factor": "Factor1", "pathway": "TGFb", "estimate": 1.4, "pval": 0.004, "adj_pval": 0.028},
        ],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-8: Pathway-Factor\n"
        "### Biological Interpretation\n"
        "Proposed patterns include a Hypoxia alignment in Factor2, potential Estrogen signaling depletion in "
        "Factor3, and TGFb alignment in Factor1.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    assert not any(
        i["code"] in {"unsupported_pathway_factor_significance", "factor_pathway_direction_mismatch"}
        for i in issues
    )


def test_flags_unsupported_pathway_in_factor_continuation_clause(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana_pathway_factor.csv",
        [{"factor": "Factor2", "pathway": "NFkB", "estimate": 2.1, "pval": 0.004, "adj_pval": 0.028}],
    )
    _write_csv(
        tmp_path / "sig_PathwayEnrich_decoupler.csv",
        [{"group": "4", "reference": "rest", "name": "EGFR", "stat": 33.0, "meanchange": 3.7, "pval": 0.0, "fdr": 0.0}],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-8: Pathway-Factor\n"
        "### Biological Interpretation\n"
        "Factor2 showed significant enrichment, including NFkB and EGFR.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    flagged = [i for i in issues if i["code"] == "unsupported_pathway_factor_significance"]
    assert len(flagged) == 1
    assert flagged[0]["value"] == "Factor2: EGFR"


def test_flags_direction_mismatch_in_factor_continuation_clause(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana_pathway_factor.csv",
        [{"factor": "Factor2", "pathway": "NFkB", "estimate": 2.1, "pval": 0.004, "adj_pval": 0.028}],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-8: Pathway-Factor\n"
        "### Biological Interpretation\n"
        "Factor2 showed significant depletion, including NFkB.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    flagged = [i for i in issues if i["code"] == "factor_pathway_direction_mismatch"]
    assert len(flagged) == 1
    assert flagged[0]["value"] == "Factor2: NFkB estimate=2.1"


def test_flags_shared_pathway_direction_mismatch_for_each_factor(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana_pathway_factor.csv",
        [
            {"factor": "Factor1", "pathway": "TGFb", "estimate": 1.4, "pval": 0.004, "adj_pval": 0.028},
            {"factor": "Factor2", "pathway": "TGFb", "estimate": -2.1, "pval": 0.004, "adj_pval": 0.028},
        ],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-8: Pathway-Factor\n"
        "### Biological Interpretation\n"
        "TGFb activity is enriched in Factor1 and Factor2.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    flagged = [i for i in issues if i["code"] == "factor_pathway_direction_mismatch"]
    assert len(flagged) == 1
    assert flagged[0]["value"] == "Factor2: TGFb estimate=-2.1"


def test_allows_hypothetical_factor_pathway_language(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana_pathway_factor.csv",
        [{"factor": "Factor2", "pathway": "NFkB", "estimate": -3.28, "p": 0.001, "adj_p": 0.025}],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-8: Pathway Factor Heatmap\n"
        "### Biological Interpretation\n"
        "Factor1 has a hypothesized TGFb enrichment, hypothesised MAPK activation, and hypothetical PI3K activation.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    assert not any(i["code"] == "unsupported_pathway_factor_significance" for i in issues)


def test_flags_factor_pathway_direction_mismatch_for_positive_estimate_written_as_depletion(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana_pathway_factor.csv",
        [{"factor": "Factor3", "pathway": "EGFR", "estimate": 2.897, "pval": 0.004, "adj_pval": 0.028}],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-8: Pathway-Factor\n"
        "### Biological Interpretation\n"
        "Factor3 shows EGFR depletion and reduced activity.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    flagged = [i for i in issues if i["code"] == "factor_pathway_direction_mismatch"]
    assert len(flagged) == 1
    assert flagged[0]["value"] == "Factor3: EGFR estimate=2.897"


def test_allows_negative_factor_pathway_when_written_as_depletion(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana_pathway_factor.csv",
        [{"factor": "Factor3", "pathway": "EGFR", "estimate": -2.897, "pval": 0.004, "adj_pval": 0.028}],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-8: Pathway-Factor\n"
        "### Biological Interpretation\n"
        "Factor3 shows EGFR depletion.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    assert not any(i["code"] == "factor_pathway_direction_mismatch" for i in issues)


def test_allows_mixed_factor_pathway_sentence_when_local_directions_match(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana_pathway_factor.csv",
        [
            {"factor": "Factor3", "pathway": "EGFR", "estimate": 2.897, "pval": 0.004, "adj_pval": 0.028},
            {"factor": "Factor3", "pathway": "MAPK", "estimate": -1.25, "pval": 0.004, "adj_pval": 0.028},
        ],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-8: Pathway-Factor\n"
        "### Biological Interpretation\n"
        "Factor3 shows EGFR enrichment and MAPK depletion.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    assert not any(i["code"] == "factor_pathway_direction_mismatch" for i in issues)


def test_allows_mixed_factor_pathway_sentence_with_direction_before_pathway(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana_pathway_factor.csv",
        [
            {"factor": "Factor3", "pathway": "EGFR", "estimate": 2.897, "pval": 0.004, "adj_pval": 0.028},
            {"factor": "Factor3", "pathway": "MAPK", "estimate": -1.5, "pval": 0.004, "adj_pval": 0.028},
        ],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-8: Pathway-Factor\n"
        "### Biological Interpretation\n"
        "Factor3 shows enrichment of EGFR and depletion of MAPK.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    assert not any(i["code"] == "factor_pathway_direction_mismatch" for i in issues)


def test_allows_positive_factor_pathway_when_written_as_enrichment_not_depletion(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana_pathway_factor.csv",
        [{"factor": "Factor3", "pathway": "EGFR", "estimate": 2.897, "pval": 0.004, "adj_pval": 0.028}],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-8: Pathway-Factor\n"
        "### Biological Interpretation\n"
        "Factor3 shows EGFR enrichment, not depletion.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    assert not any(i["code"] == "factor_pathway_direction_mismatch" for i in issues)


def test_flags_coordinated_factor_pathway_depletion_before_pathways(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana_pathway_factor.csv",
        [
            {"factor": "Factor3", "pathway": "EGFR", "estimate": 2.897, "pval": 0.004, "adj_pval": 0.028},
            {"factor": "Factor3", "pathway": "MAPK", "estimate": 1.5, "pval": 0.004, "adj_pval": 0.028},
        ],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-8: Pathway-Factor\n"
        "### Biological Interpretation\n"
        "Factor3 shows depletion of EGFR and MAPK.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    flagged = {i["value"] for i in issues if i["code"] == "factor_pathway_direction_mismatch"}
    assert flagged == {"Factor3: EGFR estimate=2.897", "Factor3: MAPK estimate=1.5"}


def test_flags_coordinated_factor_pathway_depletion_after_pathways(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana_pathway_factor.csv",
        [
            {"factor": "Factor3", "pathway": "EGFR", "estimate": 2.897, "pval": 0.004, "adj_pval": 0.028},
            {"factor": "Factor3", "pathway": "MAPK", "estimate": 1.5, "pval": 0.004, "adj_pval": 0.028},
        ],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-8: Pathway-Factor\n"
        "### Biological Interpretation\n"
        "Factor3 shows EGFR and MAPK depletion.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    flagged = {i["value"] for i in issues if i["code"] == "factor_pathway_direction_mismatch"}
    assert flagged == {"Factor3: EGFR estimate=2.897", "Factor3: MAPK estimate=1.5"}


def test_flags_negative_factor_pathway_with_enrichment_not_depletion(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana_pathway_factor.csv",
        [{"factor": "Factor3", "pathway": "EGFR", "estimate": -2.897, "pval": 0.004, "adj_pval": 0.028}],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-8: Pathway-Factor\n"
        "### Biological Interpretation\n"
        "Factor3 shows EGFR enrichment, not depletion.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    flagged = [i for i in issues if i["code"] == "factor_pathway_direction_mismatch"]
    assert len(flagged) == 1
    assert flagged[0]["value"] == "Factor3: EGFR estimate=-2.897"


def test_flags_part3_therapeutic_spillover(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    offending = (
        "MIF-CD74 is a high-confidence therapeutic target and should be "
        "prioritized for druggability."
    )
    (tmp_path / "part3_final.md").write_text(
        "## Analysis 3-10: Selected Gene L-R Spatial Evidence\n"
        "### Biological Interpretation\n"
        "The Moran signal remains spatial evidence only.\n"
        f"{offending}\n"
        "MIF-CD74 remains selected for spatial follow-up.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    flagged = [i for i in issues if i["code"] == "part3_therapeutic_spillover"]
    assert len(flagged) == 1
    assert flagged[0]["value"] == offending
    assert flagged[0]["section"] == "## Analysis 3-10: Selected Gene L-R Spatial Evidence"


def test_flags_part3_missing_selected_lr_pairs(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_json(
        tmp_path / "part4_candidate_selection.json",
        {
            "selected_genes": ["ICAM1", "MUC1", "CD74"],
            "selected_lr_pairs": [
                {"interaction": "ICAM1^PECAM1"},
                {"interaction": "ICAM1^MUC1"},
                {"interaction": "MIF^CD74"},
            ],
        },
    )
    (tmp_path / "part3_final.md").write_text(
        "## Analysis 3-10: Selected Gene L-R Spatial Evidence\n"
        "### Biological Interpretation\n"
        "ICAM1 and MUC1 spatial signals were reviewed.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    missing = [i for i in issues if i["code"] == "missing_selected_lr_pair"]
    assert {i["value"] for i in missing} == {"ICAM1^PECAM1", "ICAM1^MUC1", "MIF^CD74"}


def test_flags_lr_metric_value_mismatch_against_sig_liana(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana.csv",
        [
            {
                "interaction": "LAMA5^ITGB4",
                "ligand": "LAMA5",
                "receptor": "ITGB4",
                "morans": 0.32653028,
                "morans_pvals": 0.0,
                "genept_score": 0.8060191,
                "combinedscore": 0.71706842,
            }
        ],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-6: LIANA Moran's R\n"
        "### Biological Interpretation\n"
        "LAMA5-ITGB4 exhibits a Moran's R of 0.7171.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    flagged = [i for i in issues if i["code"] == "lr_metric_value_mismatch"]
    assert len(flagged) == 1
    assert flagged[0]["file"] == "part2_final.md"
    assert flagged[0]["section"] == "## Analysis 2-6: LIANA Moran's R"
    assert flagged[0]["value"] == "LAMA5^ITGB4 morans=0.7171"
    assert "sig_liana.csv has morans=0.3265" in flagged[0]["evidence"]


def test_flags_lr_metric_value_mismatch_in_part3(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana.csv",
        [
            {
                "interaction": "LAMA5^ITGB4",
                "ligand": "LAMA5",
                "receptor": "ITGB4",
                "morans": 0.32653028,
                "morans_pvals": 0.0,
                "genept_score": 0.8060191,
                "combinedscore": 0.71706842,
            }
        ],
    )
    (tmp_path / "part3_final.md").write_text(
        "## Analysis 3-10: Selected Gene L-R Spatial Evidence\n"
        "### Biological Interpretation\n"
        "LAMA5-ITGB4 exhibits a Moran's R of 0.7171.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    flagged = [i for i in issues if i["code"] == "lr_metric_value_mismatch"]
    assert len(flagged) == 1
    assert flagged[0]["file"] == "part3_final.md"
    assert flagged[0]["value"] == "LAMA5^ITGB4 morans=0.7171"


def test_flags_lr_metric_value_mismatch_with_morans_i_label(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana.csv",
        [
            {
                "interaction": "LAMA5^ITGB4",
                "ligand": "LAMA5",
                "receptor": "ITGB4",
                "morans": 0.32653028,
                "morans_pvals": 0.0,
                "genept_score": 0.8060191,
                "combinedscore": 0.71706842,
            }
        ],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-6: LIANA Moran's I\n"
        "### Biological Interpretation\n"
        "LAMA5-ITGB4 exhibits a Moran's I of 0.7171.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    flagged = [i for i in issues if i["code"] == "lr_metric_value_mismatch"]
    assert len(flagged) == 1
    assert flagged[0]["value"] == "LAMA5^ITGB4 morans=0.7171"


def test_allows_lr_metric_value_when_claim_matches_sig_liana(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana.csv",
        [
            {
                "interaction": "LAMA5^ITGB4",
                "ligand": "LAMA5",
                "receptor": "ITGB4",
                "morans": 0.32653028,
                "morans_pvals": 0.0,
                "genept_score": 0.8060191,
                "combinedscore": 0.71706842,
            }
        ],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-6: LIANA Moran's R\n"
        "### Biological Interpretation\n"
        "LAMA5-ITGB4 has Moran's R = 0.3265 and combined score = 0.7171.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    assert not any(i["code"] == "lr_metric_value_mismatch" for i in issues)


def test_flags_morans_r_without_apostrophe_as_lr_metric_label(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana.csv",
        [
            {
                "interaction": "LAMA5^ITGB4",
                "ligand": "LAMA5",
                "receptor": "ITGB4",
                "morans": 0.32653028,
                "morans_pvals": 0.0,
                "genept_score": 0.8060191,
                "combinedscore": 0.71706842,
            }
        ],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-6: LIANA Moran's R\n"
        "### Biological Interpretation\n"
        "LAMA5-ITGB4 exhibits Morans R of 0.7171.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    flagged = [i for i in issues if i["code"] == "lr_metric_value_mismatch"]
    assert len(flagged) == 1
    assert flagged[0]["value"] == "LAMA5^ITGB4 morans=0.7171"


def test_allows_multiple_lr_metric_pairs_with_correct_local_values(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana.csv",
        [
            {
                "interaction": "LAMA5^ITGB4",
                "ligand": "LAMA5",
                "receptor": "ITGB4",
                "morans": 0.32653028,
                "morans_pvals": 0.0,
                "genept_score": 0.8060191,
                "combinedscore": 0.71706842,
            },
            {
                "interaction": "CDH1^ERBB3",
                "ligand": "CDH1",
                "receptor": "ERBB3",
                "morans": 0.47670004,
                "morans_pvals": 0.0,
                "genept_score": 0.6969726,
                "combinedscore": 0.8140698,
            },
        ],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-6: LIANA Moran's R\n"
        "### Biological Interpretation\n"
        "LAMA5-ITGB4 has Moran's R = 0.3265, while CDH1-ERBB3 has Moran's R = 0.4767.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    assert not any(i["code"] == "lr_metric_value_mismatch" for i in issues)


def test_flags_lr_metric_value_mismatch_with_morans_r_score_parentheses(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana.csv",
        [
            {
                "interaction": "LAMA5^ITGB4",
                "ligand": "LAMA5",
                "receptor": "ITGB4",
                "morans": 0.32653028,
                "morans_pvals": 0.0,
                "genept_score": 0.8060191,
                "combinedscore": 0.71706842,
            }
        ],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-6: LIANA Moran's R\n"
        "### Biological Interpretation\n"
        "LAMA5-ITGB4 has a Moran's R score (0.7171).\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    flagged = [i for i in issues if i["code"] == "lr_metric_value_mismatch"]
    assert len(flagged) == 1
    assert flagged[0]["value"] == "LAMA5^ITGB4 morans=0.7171"


def test_flags_lr_metric_value_mismatch_with_morans_r_value_of(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana.csv",
        [
            {
                "interaction": "LAMA5^ITGB4",
                "ligand": "LAMA5",
                "receptor": "ITGB4",
                "morans": 0.32653028,
                "morans_pvals": 0.0,
                "genept_score": 0.8060191,
                "combinedscore": 0.71706842,
            }
        ],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-6: LIANA Moran's R\n"
        "### Biological Interpretation\n"
        "LAMA5-ITGB4 has a Moran's R value of 0.7171.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    flagged = [i for i in issues if i["code"] == "lr_metric_value_mismatch"]
    assert len(flagged) == 1
    assert flagged[0]["value"] == "LAMA5^ITGB4 morans=0.7171"


def test_flags_unhedged_mechanistic_overclaim_in_biological_interpretation(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    (tmp_path / "part1_final.md").write_text(
        "## Analysis 1-5: MISTy\n"
        "### Biological Interpretation\n"
        "The MISTy association confirms that hypoxic conditions drive proliferative tumor cell behavior.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    flagged = [i for i in issues if i["code"] == "unsupported_mechanistic_interpretation"]
    assert len(flagged) == 1
    assert flagged[0]["severity"] == "error"
    assert flagged[0]["section"] == "## Analysis 1-5: MISTy"


def test_warns_on_hedged_mechanistic_interpretation(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-6: LIANA Moran's R\n"
        "### Biological Interpretation\n"
        "The spatial co-localization suggests that LRIG1-expressing cells may be attempting to suppress ERBB2 signaling.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    flagged = [i for i in issues if i["code"] == "mechanistic_interpretation_warning"]
    assert len(flagged) == 1
    assert flagged[0]["severity"] == "warning"
    assert not any(i["code"] == "unsupported_mechanistic_interpretation" for i in issues)


def test_flags_unhedged_mechanistic_overclaim_even_when_inferred_is_present(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    (tmp_path / "part1_final.md").write_text(
        "## Analysis 1-5: MISTy\n"
        "### Biological Interpretation\n"
        "MISTy-inferred spatial pattern confirms that hypoxia drives tumor behavior.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    flagged = [i for i in issues if i["code"] == "unsupported_mechanistic_interpretation"]
    assert len(flagged) == 1
    assert flagged[0]["severity"] == "error"
    assert not any(i["code"] == "mechanistic_interpretation_warning" for i in issues)


def test_ignores_mechanistic_trigger_outside_biological_interpretation(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    (tmp_path / "part1_final.md").write_text(
        "## Analysis 1-5: MISTy\n"
        "### Results\n"
        "MISTy-inferred spatial pattern confirms that hypoxia drives tumor behavior.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    assert not any(i["code"] == "unsupported_mechanistic_interpretation" for i in issues)
    assert not any(i["code"] == "mechanistic_interpretation_warning" for i in issues)


def test_ignores_general_literature_mechanism_without_report_evidence_terms(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    (tmp_path / "part1_final.md").write_text(
        "## Analysis 1-4: Decoupler Pathway\n"
        "### Biological Interpretation\n"
        "The MAPK pathway drives cell cycle progression through ERK-mediated transcription.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    assert not any(i["code"] == "unsupported_mechanistic_interpretation" for i in issues)
    assert not any(i["code"] == "mechanistic_interpretation_warning" for i in issues)


def test_flags_ambiguous_lr_annotation_factor_sentence(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana_pathway_factor.csv",
        [
            {
                "factor": "Factor2",
                "pathway": "NFkB",
                "estimate": -3.2899,
                "pval": 0.0011,
                "adj_pval": 0.0254,
            }
        ],
    )
    _write_csv(
        tmp_path / "sig_PathwayEnrich_decoupler.csv",
        [
            {
                "group": "1",
                "reference": "rest",
                "name": "TNFa",
                "stat": 81.4,
                "meanchange": 3.13,
                "pval": 0.0,
                "fdr": 0.0,
            }
        ],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-8: Pathway-Factor Enrichment\n"
        "- The NFkB annotation for ICAM1^MUC1 "
        "(JAK-STAT;NFkB;TNFa) provides context for Factor2 regions, "
        "suggesting pathway involvement despite lack of enrichment significance.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    assert any(
        issue["code"] == "unsupported_pathway_factor_significance"
        and issue["value"] == "Factor2: TNFa"
        for issue in issues
    )


def test_accepts_separated_lr_annotation_and_factor_measurement(
    tmp_path: Path,
) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana_pathway_factor.csv",
        [
            {
                "factor": "Factor2",
                "pathway": "NFkB",
                "estimate": -3.2899,
                "pval": 0.0011,
                "adj_pval": 0.0254,
            }
        ],
    )
    _write_csv(
        tmp_path / "sig_PathwayEnrich_decoupler.csv",
        [
            {
                "group": "1",
                "reference": "rest",
                "name": "TNFa",
                "stat": 81.4,
                "meanchange": 3.13,
                "pval": 0.0,
                "fdr": 0.0,
            }
        ],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-8: Pathway-Factor Enrichment\n"
        "ICAM1^MUC1 carries NFkB and TNFa labels in the L-R annotation dataset.\n\n"
        "Only Factor2-NFkB was supported by sig_liana_pathway_factor.csv. "
        "No measured Factor2-TNFa association was identified; TNFa involvement "
        "therefore remains an annotation-based hypothesis.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    assert not any(
        issue["code"] == "unsupported_pathway_factor_significance"
        for issue in issues
    )
