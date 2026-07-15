from __future__ import annotations

import json
from pathlib import Path

from src.agents.deep_interpreter import claim_rag_validation


def _write_papers(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "papers": [
                    {"pmid": "11111111", "abstract": "TGFB is associated with fibrosis."},
                    {"pmid": "22222222", "abstract": "CXCL12 regulates immune migration."},
                    {"pmid": "33333333", "abstract": "ERBB signaling supports proliferation."},
                ]
            }
        ),
        encoding="utf-8",
    )


def test_part_claims_prefer_inline_pmid_then_section_references(tmp_path: Path) -> None:
    _write_papers(tmp_path / "papers.json")
    (tmp_path / "part1_final.md").write_text(
        "## Analysis 1-1: Spatial Clustering\n"
        "### Biological Interpretation\n"
        "TGFB may promote fibrosis (PMID: 11111111).\n"
        "CXCL12 may regulate immune migration.\n"
        "### Novel Findings\n"
        "A novel spatial observation.\n"
        "### References\n"
        "- PMID: 22222222\n"
        "- PMID: 33333333\n",
        encoding="utf-8",
    )

    [group] = claim_rag_validation._extract_claim_groups(
        tmp_path, ("part1_final.md",)
    )

    assert group["section"] == "## Analysis 1-1: Spatial Clustering"
    assert [item["claim"] for item in group["claims"]] == [
        "TGFB may promote fibrosis (PMID: 11111111).",
        "CXCL12 may regulate immune migration.",
    ]
    assert group["claims"][0]["candidate_pmids"] == ["11111111"]
    assert group["claims"][1]["candidate_pmids"] == ["22222222", "33333333"]
    assert group["claims"][0]["hedged"] is True


def test_synthesis_claim_without_inline_pmid_uses_papers_universe(tmp_path: Path) -> None:
    _write_papers(tmp_path / "papers.json")
    (tmp_path / "synthesis.md").write_text(
        "# Integrated Biological Narrative\n\n"
        "## Cross-Part Themes\n\n"
        "TGFB and CXCL12 form a coordinated disease-associated program.\n",
        encoding="utf-8",
    )

    [group] = claim_rag_validation._extract_claim_groups(tmp_path, ("synthesis.md",))

    assert group["section"] == "## Cross-Part Themes"
    assert group["claims"][0]["candidate_pmids"] == [
        "11111111",
        "22222222",
        "33333333",
    ]


def test_synthesis_references_do_not_narrow_non_inline_pmid_pool(tmp_path: Path) -> None:
    _write_papers(tmp_path / "papers.json")
    (tmp_path / "synthesis.md").write_text(
        "## Cross-Part Themes\n\n"
        "TGFB and CXCL12 form a coordinated disease-associated program.\n"
        "### References\n"
        "- PMID: 11111111\n",
        encoding="utf-8",
    )

    [group] = claim_rag_validation._extract_claim_groups(tmp_path, ("synthesis.md",))

    assert group["claims"][0]["candidate_pmids"] == [
        "11111111",
        "22222222",
        "33333333",
    ]


def test_inline_pmid_outside_papers_json_is_not_an_evidence_candidate(
    tmp_path: Path,
) -> None:
    _write_papers(tmp_path / "papers.json")
    (tmp_path / "part1_final.md").write_text(
        "## Analysis 1-1\n"
        "### Biological Interpretation\n"
        "TGFB drives fibrosis (PMID: 99999999).\n"
        "### References\n"
        "- PMID: 11111111\n",
        encoding="utf-8",
    )

    [group] = claim_rag_validation._extract_claim_groups(
        tmp_path, ("part1_final.md",)
    )

    assert group["claims"][0]["candidate_pmids"] == []


def test_explicit_hypothesis_marker_is_not_extracted_as_asserted_claim(tmp_path: Path) -> None:
    _write_papers(tmp_path / "papers.json")
    (tmp_path / "synthesis.md").write_text(
        "## Novel Findings Summary\n\n"
        "TGFB coordinates all observed interactions. This remains a hypothesis requiring validation.\n",
        encoding="utf-8",
    )

    groups = claim_rag_validation._extract_claim_groups(tmp_path, ("synthesis.md",))

    assert groups[0]["claims"][0]["claim"] == "TGFB coordinates all observed interactions."
    assert groups[0]["claims"][0]["hedged"] is True
