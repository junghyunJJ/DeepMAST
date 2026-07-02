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


def test_flags_part3_therapeutic_spillover(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    (tmp_path / "part3_final.md").write_text(
        "## Analysis 3-10: Selected Gene L-R Spatial Evidence\n"
        "### Biological Interpretation\n"
        "MIF-CD74 is a high-confidence therapeutic target and should be prioritized for druggability.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    assert any(i["code"] == "part3_therapeutic_spillover" for i in issues)


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
