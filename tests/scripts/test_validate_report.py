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


def test_claim_windows_treats_markdown_table_rows_as_atomic_claims() -> None:
    header = "| Theme | Strength | Supporting Evidence |"
    safe_row = "| Spatial Association | Strong | Factor3 loadings exceed 0.5 |"
    unsafe_row = (
        "| Tumor-Vascular Spatial Association | Strong | "
        "Spatial plots confirm epithelial-vascular co-localization. "
        "Moran's R = 0.4767 |"
    )
    text = "\n".join(
        [
            "## Emergent Themes Summary",
            "",
            header,
            "|---|---|---|",
            safe_row,
            unsafe_row,
        ]
    )

    windows = validate_report._claim_windows(text)

    assert header in windows
    assert safe_row in windows
    assert unsafe_row in windows
    assert "|---|---|---|" not in windows
    assert not any(safe_row in window and unsafe_row in window for window in windows)


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
    assert flagged[0]["target_text"] == "Factor2 showed significant enrichment for NFkB and EGFR."
    assert "replacement_text" not in flagged[0]


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


def test_allows_pair15_plural_hypotheses_language(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana_pathway_factor.csv",
        [
            {
                "factor": "Factor3",
                "pathway": "EGFR",
                "estimate": -2.897,
                "p": 0.004,
                "adj_p": 0.028,
            },
            {
                "factor": "Factor3",
                "pathway": "Estrogen",
                "estimate": -5.480,
                "p": 4.98e-08,
                "adj_p": 4.98e-07,
            },
            {
                "factor": "Factor2",
                "pathway": "Hypoxia",
                "estimate": 7.335,
                "p": 3.59e-13,
                "adj_p": 3.59e-12,
            },
        ],
    )
    target = (
        "- **Connection to Analysis 2-7 (NMF Factor)**: The pathway enrichments "
        "provide annotation-based hypotheses for Factor3's biological program, "
        "suggesting potential associations with estrogen-independent, "
        "hypoxia-resistant states and restrained EGFR signaling."
    )
    (tmp_path / "part2_final.md").write_text(
        f"## Analysis 2-8: Pathway-Factor Enrichment\n{target}\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    assert not any(
        issue["code"] == "unsupported_pathway_factor_significance"
        and issue["value"] == "Factor3: Hypoxia"
        for issue in issues
    )


def test_allows_hypothesis_word_forms_in_triggering_pathway_claims(
    tmp_path: Path,
) -> None:
    for case, word_form in (
        ("singular", "hypothesis"),
        ("american", "hypothesized"),
        ("british", "hypothesised"),
    ):
        data_dir = tmp_path / case
        data_dir.mkdir()
        _write_json(data_dir / "papers.json", [])
        _write_csv(
            data_dir / "sig_liana_pathway_factor.csv",
            [
                {
                    "factor": "Factor3",
                    "pathway": "EGFR",
                    "estimate": -2.897,
                    "p": 0.004,
                    "adj_p": 0.028,
                },
                {
                    "factor": "Factor2",
                    "pathway": "Hypoxia",
                    "estimate": 7.335,
                    "p": 3.59e-13,
                    "adj_p": 3.59e-12,
                },
            ],
        )
        (data_dir / "part2_final.md").write_text(
            "## Analysis 2-8: Pathway-Factor Enrichment\n"
            f"Factor3 Hypoxia enrichment remains an annotation-based {word_form}.\n",
            encoding="utf-8",
        )

        issues = validate_report.validate_report(data_dir)

        assert not any(
            issue["code"] == "unsupported_pathway_factor_significance"
            and issue["value"] == "Factor3: Hypoxia"
            for issue in issues
        ), word_form


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
    assert flagged[0]["target_text"] == "Factor3 shows EGFR enrichment and activation."
    assert "replacement_text" not in flagged[0]


def test_allows_cluster_enrichment_with_negative_pathway_depletion(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana_pathway_factor.csv",
        [
            {"factor": "Factor3", "pathway": "Estrogen", "estimate": -5.4798, "pval": 0.004, "adj_pval": 0.028},
            {"factor": "Factor3", "pathway": "EGFR", "estimate": -2.8971, "pval": 0.004, "adj_pval": 0.028},
            {"factor": "Factor3", "pathway": "NFkB", "estimate": -1.5, "pval": 0.004, "adj_pval": 0.028},
        ],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-8: Pathway-Factor\n"
        "### Biological Interpretation\n"
        "**Factor3 Signature**: Factor3 is enriched in clusters 17, 4, and 14 "
        "(loadings 0.538-0.601) and shows a unique pathway signature with depletion of "
        "Estrogen, EGFR, and NFkB, suggesting a distinct regulatory state in Prolif "
        "Invasive Tumor cells.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    assert not any(i["code"] == "factor_pathway_direction_mismatch" for i in issues)
    flagged = [i for i in issues if i["code"] == "factor_pathway_direction_ambiguous"]
    assert flagged
    assert all(i["severity"] == "warning" for i in flagged)
    assert all("target_text" not in i for i in flagged)


def test_allows_descriptor_cluster_enrichment_with_negative_pathway_depletion(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana_pathway_factor.csv",
        [
            {"factor": "Factor3", "pathway": "Estrogen", "estimate": -5.48, "pval": 4.98e-08, "adj_pval": 0.001},
            {"factor": "Factor3", "pathway": "EGFR", "estimate": -2.90, "pval": 0.0038, "adj_pval": 0.028},
            {"factor": "Factor3", "pathway": "NFkB", "estimate": -2.59, "pval": 0.0097, "adj_pval": 0.04},
        ],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-8: Pathway-Factor\n"
        "### Biological Interpretation\n"
        "**Factor3 transcriptional program** is specifically enriched in proliferative invasive tumor clusters "
        "(4, 17, 14) with scores 0.51-0.60, showing depletion for Estrogen "
        "(estimate = -5.48, p = 4.98e-08), EGFR (estimate = -2.90, p = 0.0038), "
        "and NFkB (estimate = -2.59, p = 0.0097) pathways\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    assert not any(i["code"] == "factor_pathway_direction_mismatch" for i in issues)
    flagged = [i for i in issues if i["code"] == "factor_pathway_direction_ambiguous"]
    assert flagged
    assert all(i["severity"] == "warning" for i in flagged)
    assert all("target_text" not in i for i in flagged)


def test_warns_for_mixed_cluster_pathway_direction_without_hard_error(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana_pathway_factor.csv",
        [{"factor": "Factor3", "pathway": "EGFR", "estimate": 2.8971, "pval": 0.004, "adj_pval": 0.028}],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-8: Pathway-Factor\n"
        "### Biological Interpretation\n"
        "**Factor3 Signature**: Factor3 is enriched in clusters 17, 4, and 14 "
        "(loadings 0.538-0.601) and shows a unique pathway signature with depletion of EGFR.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    assert not [issue for issue in issues if issue["code"] == "factor_pathway_direction_mismatch"]
    flagged = [issue for issue in issues if issue["code"] == "factor_pathway_direction_ambiguous"]
    assert flagged
    assert all("target_text" not in issue for issue in flagged)


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
        "Factor3 shows EGFR depletion.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    flagged = [i for i in issues if i["code"] == "factor_pathway_direction_mismatch"]
    assert len(flagged) == 1
    assert flagged[0]["value"] == "Factor3: EGFR estimate=2.897"


def test_flags_plural_factor_pathway_direction_mismatch(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana_pathway_factor.csv",
        [{"factor": "Factor3", "pathway": "EGFR", "estimate": -2.897, "pval": 0.004, "adj_pval": 0.028}],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-8: Pathway-Factor\n"
        "### Biological Interpretation\n"
        "Factor3 shows EGFR enrichments.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    flagged = [i for i in issues if i["code"] == "factor_pathway_direction_mismatch"]
    assert len(flagged) == 1
    assert flagged[0]["value"] == "Factor3: EGFR estimate=-2.897"


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

    assert not [i for i in issues if i["code"] == "factor_pathway_direction_mismatch"]
    flagged = {i["value"] for i in issues if i["code"] == "factor_pathway_direction_ambiguous"}
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

    assert not [i for i in issues if i["code"] == "factor_pathway_direction_mismatch"]
    flagged = {i["value"] for i in issues if i["code"] == "factor_pathway_direction_ambiguous"}
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


def test_allows_negatively_associated_factor_pathways_with_negative_estimates(
    tmp_path: Path,
) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana_pathway_factor.csv",
        [
            {
                "factor": "Factor3",
                "pathway": "Estrogen",
                "estimate": -5.4798,
                "p": 4.98e-08,
                "adj_p": 1.0e-06,
            },
            {
                "factor": "Factor3",
                "pathway": "EGFR",
                "estimate": -2.8971,
                "p": 0.0038,
                "adj_p": 0.02,
            },
        ],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-8\n"
        "The pathway enrichment analysis shows Factor3 is negatively associated "
        "with Estrogen and EGFR.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    assert not [
        issue
        for issue in issues
        if issue["code"] == "factor_pathway_direction_mismatch"
    ]


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
    assert flagged[0]["target_text"] == offending
    assert "replacement_text" not in flagged[0]
    assert flagged[0]["section"] == "## Analysis 3-10: Selected Gene L-R Spatial Evidence"


def test_allows_part3_part4_boundary_sentence(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    (tmp_path / "part3_final.md").write_text(
        "## Analysis 3-10: Selected Gene L-R Spatial Evidence\n"
        "### Biological Interpretation\n"
        "therapeutic synthesis and clinical prioritization are reserved for Part 4\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    assert not [i for i in issues if i["code"] == "part3_therapeutic_spillover"]


def test_flags_soft_wrapped_part3_therapeutic_spillover_as_one_value(
    tmp_path: Path,
) -> None:
    _write_json(tmp_path / "papers.json", [])
    offending = (
        "MIF-CD74 is a high-confidence therapeutic target and should be\n"
        "prioritized for druggability."
    )
    body = (
        "### Biological Interpretation\n"
        "The Moran signal remains spatial evidence only.\n"
        f"{offending}\n"
        "MIF-CD74 remains selected for spatial follow-up.\n"
    )
    (tmp_path / "part3_final.md").write_text(
        "## Analysis 3-10: Selected Gene L-R Spatial Evidence\n" + body,
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    flagged = [i for i in issues if i["code"] == "part3_therapeutic_spillover"]
    assert len(flagged) == 1
    assert flagged[0]["value"] == offending
    assert flagged[0]["value"] in body


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


def test_lr_metric_mismatch_emits_exact_target_and_deterministic_replacement(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana.csv",
        [
            {
                "interaction": "LRIG1^ERBB3",
                "ligand": "LRIG1",
                "receptor": "ERBB3",
                "morans": 0.3629,
                "genept_score": 0.7,
                "combinedscore": 0.8,
            }
        ],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-6: LIANA Moran's R\n"
        "### Biological Interpretation\n"
        "LRIG1-ERBB3 Moran's R = 0.4213.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    issue = next(i for i in issues if i["code"] == "lr_metric_value_mismatch")
    assert issue["target_text"] == "LRIG1-ERBB3 Moran's R = 0.4213"
    assert issue["replacement_text"] == "LRIG1-ERBB3 Moran's R = 0.3629"


def test_lr_metric_mismatches_in_one_sentence_emit_distinct_targets(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana.csv",
        [
            {
                "interaction": "LRIG1^ERBB3",
                "ligand": "LRIG1",
                "receptor": "ERBB3",
                "morans": 0.3629,
                "genept_score": 0.7,
                "combinedscore": 0.8,
            },
            {
                "interaction": "LAMA5^ITGB4",
                "ligand": "LAMA5",
                "receptor": "ITGB4",
                "morans": 0.3265,
                "genept_score": 0.8,
                "combinedscore": 0.7,
            },
        ],
    )
    sentence = "LRIG1-ERBB3 Moran's R = 0.4213, while LAMA5-ITGB4 Moran's R = 0.7171."
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-6: LIANA Moran's R\n"
        "### Biological Interpretation\n"
        f"{sentence}\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    flagged = [i for i in issues if i["code"] == "lr_metric_value_mismatch"]
    assert [i["target_text"] for i in flagged] == [
        "LRIG1-ERBB3 Moran's R = 0.4213",
        "LAMA5-ITGB4 Moran's R = 0.7171",
    ]
    assert [i["replacement_text"] for i in flagged] == [
        "LRIG1-ERBB3 Moran's R = 0.3629",
        "LAMA5-ITGB4 Moran's R = 0.3265",
    ]
    assert all(i["target_text"] in sentence for i in flagged)
    assert flagged[0]["target_text"] != flagged[1]["target_text"]


def _write_multi_pair_lr_fixture(tmp_path: Path, sentence: str) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana.csv",
        [
            {
                "interaction": "CDH1^ERBB3",
                "ligand": "CDH1",
                "receptor": "ERBB3",
                "morans": 0.47670004,
                "genept_score": 0.6969726,
                "combinedscore": 0.8140706,
            },
            {
                "interaction": "LRIG1^ERBB2",
                "ligand": "LRIG1",
                "receptor": "ERBB2",
                "morans": 0.42133662,
                "genept_score": 0.7194545,
                "combinedscore": 0.6365551,
            },
            {
                "interaction": "LRIG1^ERBB3",
                "ligand": "LRIG1",
                "receptor": "ERBB3",
                "morans": 0.3629111,
                "genept_score": 0.7424312,
                "combinedscore": 0.7498696,
            },
            {
                "interaction": "LAMA5^BCAM",
                "ligand": "LAMA5",
                "receptor": "BCAM",
                "morans": 0.41454938,
                "genept_score": 0.694878,
                "combinedscore": 0.6518967,
            },
            {
                "interaction": "LAMA5^ITGB4",
                "ligand": "LAMA5",
                "receptor": "ITGB4",
                "morans": 0.32653028,
                "genept_score": 0.8060464,
                "combinedscore": 0.7170684,
            },
        ],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-6: LIANA Moran's R\n"
        "### Biological Interpretation\n"
        f"{sentence}\n",
        encoding="utf-8",
    )


def test_allows_correct_respectively_mapped_lr_metrics(tmp_path: Path) -> None:
    sentences = [
        (
            "The LRIG1-ERBB2 and LRIG1-ERBB3 pairs show substantial spatial "
            "co-localization (Moran's R = 0.4213 and 0.3629, respectively)."
        ),
        (
            "The LAMA5-ITGB4 and LAMA5-BCAM interactions "
            "(Moran's R = 0.3265 and 0.4145, respectively)."
        ),
        (
            "CDH1-ERBB3 (combined score = 0.8141) and LRIG1-ERBB3 "
            "(combined score = 0.7499) have strong spatial co-localization "
            "(Moran's R = 0.477 and 0.363, respectively)."
        ),
    ]

    for index, sentence in enumerate(sentences):
        case_dir = tmp_path / str(index)
        case_dir.mkdir()
        _write_multi_pair_lr_fixture(case_dir, sentence)
        issues = validate_report.validate_report(case_dir)
        assert not [issue for issue in issues if issue["code"] == "lr_metric_value_mismatch"]


def test_respectively_mapped_lr_mismatch_emits_one_atomic_replacement(tmp_path: Path) -> None:
    _write_multi_pair_lr_fixture(
        tmp_path,
        (
            "LRIG1-ERBB2 and LRIG1-ERBB3 pairs show "
            "Moran's R = 0.4213 and 0.4000, respectively."
        ),
    )

    issues = validate_report.validate_report(tmp_path)

    flagged = [issue for issue in issues if issue["code"] == "lr_metric_value_mismatch"]
    assert len(flagged) == 1
    assert flagged[0]["target_text"] == "Moran's R = 0.4213 and 0.4000, respectively"
    assert flagged[0]["replacement_text"] == "Moran's R = 0.4213 and 0.3629, respectively"


def test_warns_without_repair_when_multi_pair_metric_alignment_is_ambiguous(
    tmp_path: Path,
) -> None:
    _write_multi_pair_lr_fixture(
        tmp_path,
        "LRIG1-ERBB2 and LRIG1-ERBB3 have Moran's R = 0.4213.",
    )

    issues = validate_report.validate_report(tmp_path)

    assert not [issue for issue in issues if issue["code"] == "lr_metric_value_mismatch"]
    warning = next(
        issue for issue in issues if issue["code"] == "lr_metric_alignment_ambiguous"
    )
    assert warning["severity"] == "warning"
    assert "target_text" not in warning
    assert "replacement_text" not in warning


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


def test_unhedged_mechanistic_overclaim_is_warning_without_repair_target(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    (tmp_path / "part1_final.md").write_text(
        "## Analysis 1-5: MISTy\n"
        "### Biological Interpretation\n"
        "The MISTy association confirms that hypoxic conditions drive proliferative tumor cell behavior.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    flagged = [i for i in issues if i["code"] == "mechanistic_interpretation_warning"]
    assert len(flagged) == 1
    assert flagged[0]["severity"] == "warning"
    assert flagged[0]["section"] == "## Analysis 1-5: MISTy"
    assert "target_text" not in flagged[0]
    assert "replacement_text" not in flagged[0]


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
    assert "target_text" not in flagged[0]
    assert not any(i["code"] == "unsupported_mechanistic_interpretation" for i in issues)


def test_warns_on_unhedged_mechanistic_overclaim_even_when_inferred_is_present(
    tmp_path: Path,
) -> None:
    _write_json(tmp_path / "papers.json", [])
    (tmp_path / "part1_final.md").write_text(
        "## Analysis 1-5: MISTy\n"
        "### Biological Interpretation\n"
        "MISTy-inferred spatial pattern confirms that hypoxia drives tumor behavior.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    flagged = [i for i in issues if i["code"] == "mechanistic_interpretation_warning"]
    assert len(flagged) == 1
    assert flagged[0]["severity"] == "warning"
    assert "target_text" not in flagged[0]


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
