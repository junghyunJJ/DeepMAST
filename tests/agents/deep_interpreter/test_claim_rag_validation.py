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


def test_evidence_filter_rejects_results_outside_allowed_pmids(
    tmp_path: Path, monkeypatch
) -> None:
    _write_papers(tmp_path / "papers.json")

    monkeypatch.setattr(
        claim_rag_validation.search_literature_fulltext,
        "invoke",
        lambda _args: [
            {
                "page_content": "Unrelated ERBB evidence.",
                "metadata": {"filename": "pmid_33333333.txt"},
                "score": 0.99,
            },
            {
                "page_content": "TGFB is associated with fibrosis.",
                "metadata": {"filename": "pmid_11111111.txt"},
                "score": 0.80,
            },
        ],
    )

    evidence = claim_rag_validation._retrieve_evidence(
        "TGFB drives fibrosis.", ["11111111"], tmp_path
    )

    assert [item["pmid"] for item in evidence] == ["11111111"]
    assert evidence[0]["source"] == "full_text"


def test_abstract_fallback_is_limited_to_allowed_pmids(tmp_path: Path, monkeypatch) -> None:
    _write_papers(tmp_path / "papers.json")
    monkeypatch.setattr(
        claim_rag_validation.search_literature_fulltext,
        "invoke",
        lambda _args: [],
    )

    evidence = claim_rag_validation._retrieve_evidence(
        "CXCL12 regulates immune migration.", ["22222222"], tmp_path
    )

    assert evidence == [
        {
            "pmid": "22222222",
            "source": "abstract",
            "text": "CXCL12 regulates immune migration.",
        }
    ]


class FakeStructuredModel:
    def with_structured_output(self, _schema):
        return self

    def invoke(self, _messages):
        return claim_rag_validation.ClaimJudgmentBatch(
            judgments=[
                claim_rag_validation.ClaimJudgment(
                    claim_index=0,
                    status="overclaimed",
                    reason="The evidence supports association, not causation.",
                    supporting_pmids=["11111111"],
                    evidence_quote="TGFB is associated with fibrosis.",
                )
            ]
        )


class BatchLimitedStructuredModel:
    def __init__(self) -> None:
        self.batch_sizes: list[int] = []

    def with_structured_output(self, _schema):
        return self

    def invoke(self, messages):
        payload = json.loads(
            messages[0].content.split("Claims and evidence:\n", maxsplit=1)[1]
        )
        self.batch_sizes.append(len(payload))
        if len(payload) > 5:
            raise RuntimeError("structured output batch is too large")
        return claim_rag_validation.ClaimJudgmentBatch(
            judgments=[
                claim_rag_validation.ClaimJudgment(
                    claim_index=item["claim_index"],
                    status="supported",
                    reason="The supplied evidence directly supports the claim.",
                    supporting_pmids=["11111111"],
                    evidence_quote="Evidence supports the claim.",
                )
                for item in payload
            ]
        )


def test_judge_group_splits_large_sections_into_bounded_batches() -> None:
    model = BatchLimitedStructuredModel()
    group = {
        "file": "synthesis.md",
        "section": "## Therapeutic Implications",
        "claims": [
            {
                "index": index,
                "claim": f"Claim {index} is supported.",
                "candidate_pmids": ["11111111"],
                "hedged": False,
                "file": "synthesis.md",
                "section": "## Therapeutic Implications",
                "evidence": [
                    {
                        "pmid": "11111111",
                        "source": "abstract",
                        "text": "Evidence supports the claim.",
                    }
                ],
            }
            for index in range(25)
        ],
    }

    results = claim_rag_validation._judge_group(group, model)

    assert model.batch_sizes == [5, 5, 5, 5, 5]
    assert [result["status"] for result in results] == ["supported"] * 25


def test_validate_claims_maps_overclaim_to_repairable_issue(
    tmp_path: Path, monkeypatch
) -> None:
    _write_papers(tmp_path / "papers.json")
    (tmp_path / "part1_final.md").write_text(
        "## Analysis 1-1\n"
        "### Biological Interpretation\n"
        "TGFB drives fibrosis (PMID: 11111111).\n"
        "### References\n"
        "- PMID: 11111111\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        claim_rag_validation.search_literature_fulltext,
        "invoke",
        lambda _args: [
            {
                "page_content": "TGFB is associated with fibrosis.",
                "metadata": {"filename": "pmid_11111111.txt"},
                "score": 0.8,
            }
        ],
    )

    result = claim_rag_validation.validate_claims(
        tmp_path,
        ("part1_final.md",),
        llm=FakeStructuredModel(),
    )

    assert result["claims"][0]["status"] == "overclaimed"
    assert result["issues"] == [
        {
            "code": "claim_rag_overclaimed",
            "severity": "error",
            "file": "part1_final.md",
            "section": "## Analysis 1-1",
            "value": "TGFB drives fibrosis (PMID: 11111111).",
            "evidence": (
                "The evidence supports association, not causation. "
                "PMIDs: 11111111. Evidence: TGFB is associated with fibrosis."
            ),
            "repair_instruction": (
                "Rewrite only this claim to match the supported association; do not add a new PMID."
            ),
        }
    ]


def test_missing_evidence_becomes_warning_without_model_call(
    tmp_path: Path, monkeypatch
) -> None:
    _write_papers(tmp_path / "papers.json")
    (tmp_path / "part1_final.md").write_text(
        "## Analysis 1-1\n"
        "### Biological Interpretation\n"
        "An uncited disease mechanism is asserted here.\n"
        "### References\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        claim_rag_validation.search_literature_fulltext,
        "invoke",
        lambda _args: [],
    )

    class FailModel:
        def with_structured_output(self, _schema):
            raise AssertionError("No evidence must not invoke the judge")

    result = claim_rag_validation.validate_claims(
        tmp_path, ("part1_final.md",), llm=FailModel()
    )

    assert result["claims"][0]["status"] == "unverifiable"
    assert result["issues"][0]["severity"] == "warning"


def test_section_cache_skips_unchanged_retrieval_and_judgment(
    tmp_path: Path, monkeypatch
) -> None:
    _write_papers(tmp_path / "papers.json")
    (tmp_path / "part1_final.md").write_text(
        "## Analysis 1-1\n"
        "### Biological Interpretation\n"
        "TGFB drives fibrosis (PMID: 11111111).\n"
        "### References\n"
        "- PMID: 11111111\n",
        encoding="utf-8",
    )
    search_calls = 0

    def fake_search(_args):
        nonlocal search_calls
        search_calls += 1
        return [
            {
                "page_content": "TGFB is associated with fibrosis.",
                "metadata": {"filename": "pmid_11111111.txt"},
                "score": 0.8,
            }
        ]

    monkeypatch.setattr(
        claim_rag_validation.search_literature_fulltext, "invoke", fake_search
    )
    cache: dict[str, list[dict]] = {}

    first = claim_rag_validation.validate_claims(
        tmp_path, ("part1_final.md",), llm=FakeStructuredModel(), cache=cache
    )
    second = claim_rag_validation.validate_claims(
        tmp_path, ("part1_final.md",), llm=FakeStructuredModel(), cache=cache
    )

    assert first == second
    assert search_calls == 1
