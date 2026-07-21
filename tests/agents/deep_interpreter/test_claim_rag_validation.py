from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

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
    assert group["claims"][0]["inline_pmids"] == ["11111111"]
    assert group["claims"][1]["candidate_pmids"] == ["22222222", "33333333"]
    assert group["claims"][0]["hedged"] is True


def test_claim_items_expand_each_inline_pmid_into_exact_candidate() -> None:
    items = claim_rag_validation._claim_items(
        ["TGFB drives fibrosis (PMID: 11111111; PMID: 22222222)."],
        [],
        {"11111111", "22222222"},
    )

    assert [
        (item["source_claim_index"], item["inline_pmid"], item["candidate_pmids"])
        for item in items
    ] == [
        (0, "11111111", ["11111111"]),
        (0, "22222222", ["22222222"]),
    ]
    assert [item["index"] for item in items] == [0, 1]


def test_inline_claim_issue_retains_citation_coordinates() -> None:
    issue = claim_rag_validation._issue_for(
        {
            "status": "unsupported",
            "hedged": False,
            "supporting_pmids": [],
            "evidence_quote": "",
            "reason": "The cited paper does not support this claim.",
            "file": "part1_final.md",
            "section": "## Biology",
            "source_claim_index": 3,
            "inline_pmid": "22222222",
            "claim": "TGFB drives fibrosis (PMID: 22222222).",
        }
    )

    assert issue is not None
    assert issue["code"] == "inline_citation_unsupported"
    assert issue["source_claim_index"] == 3
    assert issue["inline_pmid"] == "22222222"


def test_reference_pmid_list_creates_no_claim_item(tmp_path: Path) -> None:
    _write_papers(tmp_path / "papers.json")
    (tmp_path / "part1_final.md").write_text(
        "## Analysis 1-1\n"
        "### Biological Interpretation\n"
        "### References\n"
        "- PMID: 11111111\n",
        encoding="utf-8",
    )

    groups = claim_rag_validation._extract_claim_groups(tmp_path, ("part1_final.md",))

    assert groups == []


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
    def with_structured_output(self, _schema, *, method=None):
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


class EchoSupportingPmidsModel:
    def __init__(self, supporting_pmids: list[str] | None = None) -> None:
        self.supporting_pmids = supporting_pmids

    def with_structured_output(self, _schema, *, method=None):
        return self

    def invoke(self, messages):
        payload = json.loads(
            messages[0].content.split("Claims and evidence:\n", maxsplit=1)[1]
        )
        return claim_rag_validation.ClaimJudgmentBatch(
            judgments=[
                claim_rag_validation.ClaimJudgment(
                    claim_index=item["claim_index"],
                    status="supported",
                    reason="The supplied evidence directly supports the claim.",
                    supporting_pmids=self.supporting_pmids
                    if self.supporting_pmids is not None
                    else item["candidate_pmids"],
                    evidence_quote="Evidence supports the claim.",
                )
                for item in payload
            ]
        )


def test_validate_claims_retrieves_bounded_union_of_claim_categories(
    tmp_path: Path, monkeypatch
) -> None:
    _write_papers(tmp_path / "papers.json")
    (tmp_path / "part1_final.md").write_text(
        "## Analysis 1-1\n"
        "### Biological Interpretation\n"
        "TGFB drives fibrosis (PMID: 11111111).\n"
        "The spatial pattern contains three clusters.\n"
        "CXCL12 marks the migratory region (PMID: 22222222).\n"
        "ERBB has established roles in proliferation.\n"
        "### References\n"
        "- PMID: 11111111\n"
        "- PMID: 22222222\n"
        "- PMID: 33333333\n",
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
        "CXCL12 marks the migratory region (PMID: 22222222).",
        "ERBB has established roles in proliferation.",
    ]
    assert [claim["selection_reason"] for claim in result["claims"]] == [
        "high_risk",
        "inline_pmid",
        "external_evidence",
    ]
    assert result["selection"]["extracted_claim_count"] == 4
    assert result["selection"]["selected_claim_count"] == 3
    assert result["selection"]["selection_reason_counts"] == {
        "high_risk": 1,
        "inline_pmid": 1,
        "external_evidence": 1,
    }
    assert result["selection"]["skipped_claims"] == [
        {
            "file": "part1_final.md",
            "section": "## Analysis 1-1",
            "index": 1,
            "claim": "The spatial pattern contains three clusters.",
            "reason": "outside_claim_rag_scope",
        }
    ]


@pytest.mark.parametrize(
    "claim",
    [
        "TGFB is associated with fibrosis.",
        "TGFB and CXCL12 have crosstalk.",
        "TGFB interacts with CXCL12.",
        "TGFB may be relevant to fibrosis.",
    ],
)
def test_selection_reason_excludes_generic_associations_and_hedges(claim: str) -> None:
    assert claim_rag_validation._selection_reason(
        {"claim": claim, "inline_pmids": []}
    ) is None


def test_validate_claims_caps_skipped_claim_details_when_low_risk_claims_exceed_sample_limit(
    tmp_path: Path,
) -> None:
    max_samples = claim_rag_validation.MAX_SKIPPED_CLAIM_SAMPLES
    claim_count = max_samples + 3
    _write_papers(tmp_path / "papers.json")
    low_risk_claims = "\n".join(
        f"Spatial cluster {index} contains marker-enriched cells."
        for index in range(claim_count)
    )
    (tmp_path / "part1_final.md").write_text(
        "## Analysis 1-1\n"
        "### Biological Interpretation\n"
        f"{low_risk_claims}\n"
        "### References\n"
        "- PMID: 11111111\n",
        encoding="utf-8",
    )

    result = claim_rag_validation.validate_claims(
        tmp_path, ("part1_final.md",), llm=FakeStructuredModel()
    )

    assert result["selection"]["extracted_claim_count"] == claim_count
    assert result["selection"]["selected_claim_count"] == 0
    assert result["selection"]["skipped_claim_count"] == claim_count
    assert len(result["selection"]["skipped_claims"]) == max_samples
    assert result["selection"]["skipped_claims_truncated"] is True


def test_validate_claims_caps_matching_claims_and_audits_overflow(
    tmp_path: Path, monkeypatch
) -> None:
    max_claims = 30
    claims = [
        f"TGFB drives fibrosis in sample {index}."
        for index in range(max_claims + 2)
    ]
    _write_papers(tmp_path / "papers.json")
    (tmp_path / "part1_final.md").write_text(
        "## Analysis 1-1\n"
        "### Biological Interpretation\n"
        + "\n".join(claims[:29])
        + "\n### References\n"
        "- PMID: 11111111\n"
        "## Analysis 1-2\n"
        "### Biological Interpretation\n"
        + "\n".join(claims[29:])
        + "\n### References\n"
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
            }
        ],
    )

    result = claim_rag_validation.validate_claims(
        tmp_path, ("part1_final.md",), llm=BatchLimitedStructuredModel()
    )

    assert [claim["claim"] for claim in result["claims"]] == claims[:max_claims]
    assert result["selection"]["extracted_claim_count"] == len(claims)
    assert result["selection"]["selected_claim_count"] == max_claims
    assert result["selection"]["selection_reason_counts"] == {
        "high_risk": max_claims
    }
    assert result["selection"]["skipped_claim_count"] == 2
    assert result["selection"]["skipped_claims"] == [
        {
            "file": "part1_final.md",
            "section": "## Analysis 1-2",
            "index": index - 29,
            "claim": claims[index],
            "reason": "selection_limit_reached",
        }
        for index in range(max_claims, len(claims))
    ]


def test_inline_pairs_bypass_the_non_inline_selection_cap(
    tmp_path: Path, monkeypatch
) -> None:
    non_inline_claims = [
        f"TGFB drives fibrosis in sample {index}." for index in range(31)
    ]
    _write_papers(tmp_path / "papers.json")
    (tmp_path / "part1_final.md").write_text(
        "## Analysis 1-1\n"
        "### Biological Interpretation\n"
        + "\n".join(non_inline_claims)
        + "\nTGFB drives fibrosis (PMID: 11111111; PMID: 22222222).\n"
        "### References\n"
        "- PMID: 11111111\n"
        "- PMID: 22222222\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        claim_rag_validation.search_literature_fulltext,
        "invoke",
        lambda args: [
            {
                "page_content": "Evidence supports the claim.",
                "metadata": {"filename": f"pmid_{pmid}.txt"},
            }
            for pmid in ("11111111", "22222222", "33333333")
            if pmid in args["query"] or "PMID:" not in args["query"]
        ],
    )

    result = claim_rag_validation.validate_claims(
        tmp_path, ("part1_final.md",), llm=EchoSupportingPmidsModel()
    )

    assert result["selection"]["non_inline_selected_count"] == 30
    assert result["selection"]["inline_citation_expected_count"] == 2
    assert result["selection"]["selected_claim_count"] == 32
    assert result["inline_citation_coverage"]["expected_count"] == 2


def test_unknown_inline_pmid_is_expected_in_incomplete_coverage(tmp_path: Path) -> None:
    _write_papers(tmp_path / "papers.json")
    (tmp_path / "part1_final.md").write_text(
        "## Analysis 1-1\n"
        "### Biological Interpretation\n"
        "TGFB drives fibrosis (PMID: 99999999).\n"
        "### References\n"
        "- PMID: 11111111\n",
        encoding="utf-8",
    )

    result = claim_rag_validation.validate_claims(
        tmp_path, ("part1_final.md",), llm=EchoSupportingPmidsModel()
    )

    assert result["inline_citation_coverage"]["coverage_complete"] is False
    assert result["inline_citation_coverage"]["citations"] == [
        {
            "file": "part1_final.md",
            "section": "## Analysis 1-1",
            "source_claim_index": 0,
            "inline_pmid": "99999999",
            "claim": "TGFB drives fibrosis (PMID: 99999999).",
            "status": "unverifiable",
            "supporting_pmids": [],
            "evidence_quote": "",
            "reason": "No allowed PMID evidence was retrieved.",
        }
    ]


def test_inline_supported_status_requires_exact_pmid(tmp_path: Path, monkeypatch) -> None:
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
                "page_content": "Evidence supports the claim.",
                "metadata": {"filename": "pmid_11111111.txt"},
            }
        ],
    )

    result = claim_rag_validation.validate_claims(
        tmp_path,
        ("part1_final.md",),
        llm=EchoSupportingPmidsModel(["22222222"]),
    )

    assert result["claims"][0]["status"] == "unverifiable"
    assert result["claims"][0]["reason"] == (
        "Inline citation PMID 11111111 was not included in supporting_pmids."
    )
    assert result["inline_citation_coverage"]["coverage_complete"] is False


class BatchLimitedStructuredModel:
    def __init__(self) -> None:
        self.batch_sizes: list[int] = []

    def with_structured_output(self, _schema, *, method=None):
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
                    supporting_pmids=item["candidate_pmids"],
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
    monkeypatch.setenv("OLLAMA_REASONING", "true")

    claim_rag_validation._create_judge_llm("ollama")

    assert captured == {
        "provider": "ollama",
        "reasoning": False,
        "num_predict": 3000,
        "request_timeout": 300.0,
    }


def test_create_judge_llm_uses_vllm_thinking_configuration(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        claim_rag_validation,
        "create_llm",
        lambda provider, **kwargs: captured.update(provider=provider, **kwargs)
        or object(),
    )

    claim_rag_validation._create_judge_llm("vllm")

    assert captured == {
        "provider": "vllm",
        "enable_thinking": False,
        "num_predict": 3000,
        "request_timeout": 300.0,
    }

    captured.clear()
    claim_rag_validation._create_judge_llm("ollama-openai")

    assert captured == {
        "provider": "ollama-openai",
        "enable_thinking": False,
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


class SlowAsyncStructuredModel:
    def with_structured_output(self, _schema, *, method=None):
        return self

    async def ainvoke(self, _messages):
        await asyncio.sleep(0.05)
        return claim_rag_validation.ClaimJudgmentBatch(judgments=[])


def test_invoke_judgment_uses_function_calling_structured_output() -> None:
    class CapturingModel(FakeStructuredModel):
        schema = None
        method = None

        def with_structured_output(self, schema, *, method=None):
            self.schema = schema
            self.method = method
            return self

    model = CapturingModel()
    group = {
        "file": "synthesis.md",
        "section": "## Therapeutic Implications",
        "claims": [
            {
                "index": 0,
                "claim": "TGFB drives fibrosis.",
                "candidate_pmids": ["11111111"],
                "evidence": [
                    {
                        "pmid": "11111111",
                        "source": "abstract",
                        "text": "TGFB is associated with fibrosis.",
                    }
                ],
            }
        ],
    }

    claim_rag_validation._invoke_judgment(model, group)

    assert model.schema is claim_rag_validation.ClaimJudgmentBatch
    assert model.method == "function_calling"


def test_invoke_judgment_enforces_total_wall_clock_timeout() -> None:
    group = {
        "file": "synthesis.md",
        "section": "## Therapeutic Implications",
        "claims": [
            {
                "index": 0,
                "claim": "TGFB drives fibrosis.",
                "candidate_pmids": ["11111111"],
                "evidence": [
                    {
                        "pmid": "11111111",
                        "source": "abstract",
                        "text": "TGFB is associated with fibrosis.",
                    }
                ],
            }
        ],
    }

    start = time.perf_counter()
    with pytest.raises(TimeoutError):
        claim_rag_validation._invoke_judgment(
            SlowAsyncStructuredModel(), group, timeout_seconds=0.01
        )
    elapsed = time.perf_counter() - start

    assert elapsed < 0.2


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


def test_judge_group_does_not_reuse_checkpoint_without_selection_reason() -> None:
    model = BatchLimitedStructuredModel()
    group = {
        "file": "synthesis.md",
        "section": "## Therapeutic Implications",
        "claims": [
            {
                "index": 0,
                "claim": "TGFB drives fibrosis.",
                "candidate_pmids": ["11111111"],
                "hedged": False,
                "selection_reason": "high_risk",
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
    legacy_claim = {
        key: value
        for key, value in group["claims"][0].items()
        if key != "selection_reason"
    }
    checkpoint = {
        "version": 1,
        "batches": {
            claim_rag_validation._checkpoint_key(group, [legacy_claim]): {
                "results": [{"status": "unsupported"}]
            }
        },
    }

    results = claim_rag_validation._judge_group(group, model, checkpoint=checkpoint)

    assert model.batch_sizes == [1]
    assert [result["status"] for result in results] == ["supported"]


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


def test_judge_group_does_not_persist_batch_when_judge_omits_evidence_claim() -> None:
    class OmitSecondClaimModel(BatchLimitedStructuredModel):
        def invoke(self, messages):
            payload = json.loads(
                messages[0].content.split("Claims and evidence:\n", maxsplit=1)[1]
            )
            self.batch_sizes.append(len(payload))
            return claim_rag_validation.ClaimJudgmentBatch(
                judgments=[
                    claim_rag_validation.ClaimJudgment(
                        claim_index=payload[0]["claim_index"],
                        status="supported",
                        reason="The supplied evidence directly supports the claim.",
                        supporting_pmids=["11111111"],
                        evidence_quote="Evidence supports the claim.",
                    )
                ]
            )

    model = OmitSecondClaimModel()
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

    results = claim_rag_validation._judge_group(group, model, None, checkpoint, flush)

    assert model.batch_sizes == [2]
    assert [item["status"] for item in results] == ["supported", "unverifiable"]
    assert results[1]["reason"] == "Claim judge omitted this claim."
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
            "code": "inline_citation_overclaimed",
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
            "source_claim_index": 0,
            "inline_pmid": "11111111",
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
        def with_structured_output(self, _schema, *, method=None):
            raise AssertionError("No evidence must not invoke the judge")

    result = claim_rag_validation.validate_claims(
        tmp_path, ("part1_final.md",), llm=FailModel()
    )

    assert result["claims"][0]["status"] == "unverifiable"
    assert result["issues"][0]["severity"] == "warning"


def test_retrieval_outage_is_unverifiable_without_judge_or_checkpoint(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "papers.json").write_text(
        json.dumps({"papers": [{"pmid": "11111111", "abstract": ""}]}),
        encoding="utf-8",
    )
    (tmp_path / "part1_final.md").write_text(
        "## Analysis 1-1\n"
        "### Biological Interpretation\n"
        "TGFB drives fibrosis (PMID: 11111111).\n"
        "### References\n"
        "- PMID: 11111111\n",
        encoding="utf-8",
    )

    def fail_search(_args):
        raise RuntimeError("rag down")

    monkeypatch.setattr(
        claim_rag_validation.search_literature_fulltext, "invoke", fail_search
    )

    class FailModel:
        def with_structured_output(self, _schema, *, method=None):
            raise AssertionError("Retrieval failure must not invoke the judge")

    result = claim_rag_validation.validate_claims(
        tmp_path, ("part1_final.md",), llm=FailModel()
    )

    assert result["claims"][0]["status"] == "unverifiable"
    assert (
        result["claims"][0]["reason"]
        == "Literature retrieval failed: RuntimeError: rag down."
    )
    assert not (
        tmp_path / claim_rag_validation.CLAIM_RAG_CHECKPOINT_FILENAME
    ).exists()


def test_validate_claims_does_not_cache_transient_retrieval_failures(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "papers.json").write_text(
        json.dumps({"papers": [{"pmid": "11111111", "abstract": ""}]}),
        encoding="utf-8",
    )
    (tmp_path / "part1_final.md").write_text(
        "## Analysis 1-1\n"
        "### Biological Interpretation\n"
        "TGFB drives fibrosis (PMID: 11111111).\n"
        "### References\n"
        "- PMID: 11111111\n",
        encoding="utf-8",
    )
    searches = 0

    def transient_search(_args):
        nonlocal searches
        searches += 1
        if searches == 1:
            raise RuntimeError("rag down")
        return [
            {
                "page_content": "TGFB drives fibrosis.",
                "metadata": {"filename": "pmid_11111111.txt"},
                "score": 0.8,
            }
        ]

    class SupportedModel:
        calls = 0

        def with_structured_output(self, _schema, *, method=None):
            return self

        def invoke(self, _messages):
            self.calls += 1
            return claim_rag_validation.ClaimJudgmentBatch(
                judgments=[
                    claim_rag_validation.ClaimJudgment(
                        claim_index=0,
                        status="supported",
                        reason="The supplied evidence directly supports the claim.",
                        supporting_pmids=["11111111"],
                        evidence_quote="TGFB drives fibrosis.",
                    )
                ]
            )

    monkeypatch.setattr(
        claim_rag_validation.search_literature_fulltext, "invoke", transient_search
    )
    cache: dict[str, list[dict]] = {}
    model = SupportedModel()

    first = claim_rag_validation.validate_claims(
        tmp_path, ("part1_final.md",), llm=model, cache=cache
    )
    second = claim_rag_validation.validate_claims(
        tmp_path, ("part1_final.md",), llm=model, cache=cache
    )

    assert first["claims"][0]["reason"].startswith("Literature retrieval failed:")
    assert searches == 2
    assert model.calls == 1
    assert second["claims"][0]["status"] == "supported"


def test_validate_claims_uses_strict_search_and_retries_strict_failures(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "papers.json").write_text(
        json.dumps({"papers": [{"pmid": "11111111", "abstract": ""}]}),
        encoding="utf-8",
    )
    (tmp_path / "part1_final.md").write_text(
        "## Analysis 1-1\n"
        "### Biological Interpretation\n"
        "TGFB drives fibrosis (PMID: 11111111).\n"
        "### References\n"
        "- PMID: 11111111\n",
        encoding="utf-8",
    )
    calls: list[dict[str, object]] = []

    def strict_failure(args):
        calls.append(args)
        if args.get("strict") is True:
            raise RuntimeError("strict rag down")
        return []

    monkeypatch.setattr(
        claim_rag_validation.search_literature_fulltext, "invoke", strict_failure
    )

    class FailModel:
        def with_structured_output(self, _schema, *, method=None):
            raise AssertionError("Retrieval failure must not invoke the judge")

    cache: dict[str, list[dict]] = {}

    first = claim_rag_validation.validate_claims(
        tmp_path, ("part1_final.md",), llm=FailModel(), cache=cache
    )
    second = claim_rag_validation.validate_claims(
        tmp_path, ("part1_final.md",), llm=FailModel(), cache=cache
    )

    assert [call["strict"] for call in calls] == [True, True]
    assert first["claims"][0]["reason"].startswith("Literature retrieval failed:")
    assert second["claims"][0]["reason"].startswith("Literature retrieval failed:")
    assert cache == {}


def test_validate_claims_does_not_fallback_to_abstract_or_cache_when_strict_search_fails(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "papers.json").write_text(
        json.dumps(
            {
                "papers": [
                    {
                        "pmid": "11111111",
                        "abstract": "TGFB drives fibrosis in disease tissue.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "part1_final.md").write_text(
        "## Analysis 1-1\n"
        "### Biological Interpretation\n"
        "TGFB drives fibrosis (PMID: 11111111).\n"
        "### References\n"
        "- PMID: 11111111\n",
        encoding="utf-8",
    )

    def fail_search(_args):
        raise RuntimeError("strict rag down")

    monkeypatch.setattr(
        claim_rag_validation.search_literature_fulltext, "invoke", fail_search
    )

    class FailModel:
        def with_structured_output(self, _schema, *, method=None):
            raise AssertionError("Retrieval failure must not invoke the judge")

    cache: dict[str, list[dict]] = {}

    result = claim_rag_validation.validate_claims(
        tmp_path, ("part1_final.md",), llm=FailModel(), cache=cache
    )

    assert result["claims"][0]["status"] == "unverifiable"
    assert result["claims"][0]["reason"].startswith("Literature retrieval failed:")
    assert not (
        tmp_path / claim_rag_validation.CLAIM_RAG_CHECKPOINT_FILENAME
    ).exists()
    assert cache == {}


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
