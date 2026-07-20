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


def test_validate_claims_retrieves_only_high_risk_biological_claims(
    tmp_path: Path, monkeypatch
) -> None:
    _write_papers(tmp_path / "papers.json")
    (tmp_path / "part1_final.md").write_text(
        "## Analysis 1-1\n"
        "### Biological Interpretation\n"
        "TGFB drives fibrosis (PMID: 11111111).\n"
        "The spatial pattern contains three clusters (PMID: 11111111).\n"
        "CXCL12 is a therapeutic target (PMID: 22222222).\n"
        "### References\n"
        "- PMID: 11111111\n"
        "- PMID: 22222222\n",
        encoding="utf-8",
    )
    searched: list[str] = []
    monkeypatch.setattr(
        claim_rag_validation.search_literature_fulltext,
        "invoke",
        lambda args: searched.append(args["query"])
        or [
            {
                "page_content": "TGFB is associated with fibrosis.",
                "metadata": {"filename": "pmid_11111111.txt"},
            }
        ],
    )

    result = claim_rag_validation.validate_claims(
        tmp_path, ("part1_final.md",), llm=FakeStructuredModel()
    )

    assert searched == [
        "TGFB drives fibrosis (PMID: 11111111).",
        "CXCL12 is a therapeutic target (PMID: 22222222).",
    ]
    assert result["selection"]["extracted_claim_count"] == 3
    assert result["selection"]["selected_claim_count"] == 2
    assert result["selection"]["skipped_claims"] == [
        {
            "file": "part1_final.md",
            "section": "## Analysis 1-1",
            "index": 1,
            "claim": "The spatial pattern contains three clusters (PMID: 11111111).",
            "reason": "outside_high_risk_scope",
        }
    ]


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


def test_create_judge_llm_uses_bounded_reasoning_configuration(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        claim_rag_validation,
        "create_llm",
        lambda provider, **kwargs: captured.update(provider=provider, **kwargs)
        or object(),
    )
    monkeypatch.setenv("OLLAMA_NUM_PREDICT", "12000")

    claim_rag_validation._create_judge_llm("ollama")

    assert captured == {
        "provider": "ollama",
        "reasoning": True,
        "num_predict": 3000,
        "request_timeout": 300.0,
    }


class TimeoutPrimaryModel(BatchLimitedStructuredModel):
    def invoke(self, messages):
        payload = json.loads(
            messages[0].content.split("Claims and evidence:\n", maxsplit=1)[1]
        )
        self.batch_sizes.append(len(payload))
        raise TimeoutError("primary timed out")


class SingleClaimFallbackModel(BatchLimitedStructuredModel):
    def invoke(self, messages):
        payload = json.loads(
            messages[0].content.split("Claims and evidence:\n", maxsplit=1)[1]
        )
        if len(payload) != 1:
            raise AssertionError("fallback must receive one claim")
        return super().invoke(messages)


class FailingFallbackModel(SingleClaimFallbackModel):
    def invoke(self, messages):
        payload = json.loads(
            messages[0].content.split("Claims and evidence:\n", maxsplit=1)[1]
        )
        self.batch_sizes.append(len(payload))
        raise RuntimeError("fallback failed")


def test_judge_group_falls_back_to_single_claim_batches_after_primary_timeout() -> None:
    primary = TimeoutPrimaryModel()
    fallback = SingleClaimFallbackModel()
    checkpoint = {"version": 1, "batches": {}}
    flushes = 0
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
            for index in range(2)
        ],
    }

    def flush() -> None:
        nonlocal flushes
        flushes += 1

    results = claim_rag_validation._judge_group(group, primary, fallback, checkpoint, flush)

    assert primary.batch_sizes == [2]
    assert fallback.batch_sizes == [1, 1]
    assert [item["status"] for item in results] == ["supported", "supported"]
    assert flushes == 1


def test_judge_group_does_not_persist_failed_judge_results() -> None:
    primary = TimeoutPrimaryModel()
    fallback = FailingFallbackModel()
    checkpoint = {"version": 1, "batches": {}}
    flushes = 0
    group = {
        "file": "synthesis.md",
        "section": "## Therapeutic Implications",
        "claims": [
            {
                "index": 0,
                "claim": "Claim 0 is supported.",
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
        ],
    }

    def flush() -> None:
        nonlocal flushes
        flushes += 1

    results = claim_rag_validation._judge_group(group, primary, fallback, checkpoint, flush)

    assert results[0]["reason"] == "Claim judge failed: RuntimeError."
    assert checkpoint["batches"] == {}
    assert flushes == 0


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


class InterruptOnSecondBatchModel(BatchLimitedStructuredModel):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        if self.calls == 2:
            raise KeyboardInterrupt
        return super().invoke(messages)


def test_validate_claims_persists_completed_batches_before_keyboard_interrupt(
    tmp_path: Path, monkeypatch
) -> None:
    _write_papers(tmp_path / "papers.json")
    (tmp_path / "part1_final.md").write_text(
        "## Analysis 1-1\n"
        "### Biological Interpretation\n"
        "TGFB drives fibrosis (PMID: 11111111).\n"
        "### References\n"
        "- PMID: 11111111\n"
        "## Analysis 1-2\n"
        "### Biological Interpretation\n"
        "CXCL12 regulates immune migration (PMID: 22222222).\n"
        "### References\n"
        "- PMID: 22222222\n",
        encoding="utf-8",
    )
    searched: list[str] = []

    def fake_search(args):
        searched.append(args["query"])
        pmid = "22222222" if "CXCL12" in args["query"] else "11111111"
        return [
            {
                "page_content": "Evidence supports the claim.",
                "metadata": {"filename": f"pmid_{pmid}.txt"},
            }
        ]

    monkeypatch.setattr(
        claim_rag_validation.search_literature_fulltext, "invoke", fake_search
    )

    try:
        claim_rag_validation.validate_claims(
            tmp_path, ("part1_final.md",), llm=InterruptOnSecondBatchModel()
        )
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("KeyboardInterrupt must propagate")

    checkpoint_path = tmp_path / claim_rag_validation.CLAIM_RAG_CHECKPOINT_FILENAME
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert len(checkpoint["batches"]) == 1

    searched.clear()
    successful = BatchLimitedStructuredModel()
    result = claim_rag_validation.validate_claims(
        tmp_path, ("part1_final.md",), llm=successful
    )

    assert searched == ["CXCL12 regulates immune migration (PMID: 22222222)."]
    assert successful.batch_sizes == [1]
    assert [item["status"] for item in result["claims"]] == ["supported", "supported"]
    assert result["selection"]["checkpoint_hits"] == 1


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

    assert first["claims"] == second["claims"]
    assert first["issues"] == second["issues"]
    assert search_calls == 1
