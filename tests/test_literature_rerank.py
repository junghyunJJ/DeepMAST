"""Unit tests for LLM disease relevance filter in literature search."""

import inspect
import json

import pytest

from src.agents.deep_interpreter.tools import literature as lit


class _MockTool:
    """Minimal MCP tool mock with LangChain-like .name/.ainvoke interface."""

    def __init__(self, name: str, handler):
        self.name = name
        self._handler = handler

    async def ainvoke(self, params):
        result = self._handler(params)
        if inspect.isawaitable(result):
            return await result
        return result


class _MockResponse:
    def __init__(self, content: str):
        self.content = content


class _MockLLM:
    def __init__(self, content: str):
        self._content = content

    async def ainvoke(self, _messages):
        return _MockResponse(self._content)


@pytest.mark.asyncio
async def test_search_with_biomcp_llm_filter_drops_irrelevant(monkeypatch):
    """LLM filter drops uncertain papers judged irrelevant."""

    async def _fake_get_tools(_url):
        async def _searcher(_params):
            return [{"type": "text", "text": "PMID: 11111111\nPMID: 33333333"}]

        async def _getter(params):
            pmid = str(params["pmid"])
            if pmid == "11111111":
                return {
                    "title": "Breast cancer signaling and prognosis",
                    "abstract": "Breast cancer specific pathway analysis.",
                }
            return {
                "title": "General immune cell dynamics",
                "abstract": "T cell exhaustion in chronic viral infection context.",
            }

        return [
            _MockTool("article_searcher", _searcher),
            _MockTool("article_getter", _getter),
        ]

    # LLM filter: paper 33333333 is irrelevant to breast cancer
    monkeypatch.setattr(lit, "get_biomcp_tools", _fake_get_tools)
    monkeypatch.setattr(
        lit,
        "create_llm",
        lambda: _MockLLM(
            json.dumps([
                {"pmid": "33333333", "relevant": False},
            ])
        ),
    )

    stats = {"applied_count": 0, "dropped_count": 0}
    result = await lit._search_with_biomcp(
        genes=["BRCA1"],
        diseases=["breast cancer"],
        keywords=["tumor microenvironment"],
        page_size=10,
        enforce_disease_match=True,
        rerank_mode="llm",
        rerank_top_n=5,
        rerank_min_confidence=0.7,
        rerank_stats=stats,
    )

    pmids = {str(p.get("pmid", "")) for p in result}
    # Paper 11111111 matches canonically ("breast cancer" in text)
    assert "11111111" in pmids
    # Paper 33333333 was uncertain (no canonical match) and LLM said irrelevant
    assert "33333333" not in pmids
    assert stats["dropped_count"] == 1


@pytest.mark.asyncio
async def test_search_with_biomcp_no_llm_keeps_uncertain(monkeypatch):
    """When rerank_mode='off', uncertain papers are kept."""

    async def _fake_get_tools(_url):
        async def _searcher(_params):
            return [{"type": "text", "text": "PMID: 11111111\nPMID: 33333333"}]

        async def _getter(params):
            pmid = str(params["pmid"])
            if pmid == "11111111":
                return {
                    "title": "Breast cancer signaling",
                    "abstract": "Breast cancer pathway analysis.",
                }
            return {
                "title": "Mammary gland development",
                "abstract": "Mammary tissue remodeling study.",
            }

        return [
            _MockTool("article_searcher", _searcher),
            _MockTool("article_getter", _getter),
        ]

    monkeypatch.setattr(lit, "get_biomcp_tools", _fake_get_tools)

    result = await lit._search_with_biomcp(
        genes=["BRCA1"],
        diseases=["breast cancer"],
        page_size=10,
        enforce_disease_match=True,
        rerank_mode="off",
    )

    pmids = {str(p.get("pmid", "")) for p in result}
    # Both kept: 11111111 matches canonically, 33333333 is uncertain but kept (no LLM)
    assert "11111111" in pmids
    assert "33333333" in pmids


@pytest.mark.asyncio
async def test_dynamic_search_reports_rerank_metadata(monkeypatch):
    monkeypatch.setattr(
        lit,
        "create_llm",
        lambda: _MockLLM(
            '[{"genes":["INS"],"diseases":["type 2 diabetes"],"keywords":["insulin resistance"]}]'
        ),
    )

    async def _fake_search_with_biomcp(
        genes=None,
        diseases=None,
        keywords=None,
        chemicals=None,
        page_size=20,
        include_preprints=True,
        biomcp_url=lit.DEFAULT_BIOMCP_URL,
        enforce_disease_match=False,
        rerank_mode="off",
        rerank_top_n=12,
        rerank_min_confidence=0.70,
        rerank_stats=None,
    ):
        if rerank_mode == "llm" and rerank_stats is not None:
            rerank_stats["applied_count"] = rerank_stats.get("applied_count", 0) + 2
            rerank_stats["dropped_count"] = rerank_stats.get("dropped_count", 0) + 1
        return [
            {
                "pmid": "12345678",
                "title": "Type 2 diabetes insulin resistance study",
                "abstract": "Mechanistic insulin resistance in type 2 diabetes.",
            }
        ]

    monkeypatch.setattr(lit, "_search_with_biomcp", _fake_search_with_biomcp)

    result = await lit.search_literature_dynamic_async(
        genes=["INS"],
        pathways=["PI3K/AKT"],
        celltypes=["Beta Cells"],
        disease="type 2 diabetes",
        max_results=5,
        max_iterations=1,
        rerank_mode="llm",
    )

    assert result["filter_stage"] == "hybrid_2stage"
    assert result["rerank_applied_count"] == 2
    assert result["rerank_dropped_count"] == 1
    assert "rerank_promoted_count" not in result


# =========================================================================
# Coverage-weighted truncation & gap-filling validation tests
# =========================================================================


class TestComputePaperCoverageScore:
    """Tests for _compute_paper_coverage_score helper."""

    def test_known_gene_and_pathway(self):
        paper = {
            "title": "BRCA1 mutations in breast cancer",
            "abstract": "We studied the WNT signaling pathway in BRCA1 carriers.",
        }
        score, covered = lit._compute_paper_coverage_score(
            paper,
            genes=["BRCA1", "TP53"],
            pathways=["WNT", "MAPK"],
            celltypes=["Tumor"],
        )
        assert "BRCA1" in covered
        assert "WNT" in covered
        # TP53, MAPK, Tumor not in paper
        assert "TP53" not in covered
        assert "MAPK" not in covered
        assert score > 0

    def test_zero_score_for_unrelated_paper(self):
        paper = {
            "title": "Rainfall patterns in the Amazon basin",
            "abstract": "A study on precipitation trends.",
        }
        score, covered = lit._compute_paper_coverage_score(
            paper,
            genes=["BRCA1", "TP53"],
            pathways=["WNT"],
            celltypes=["Tumor"],
        )
        assert score == 0
        assert len(covered) == 0

    def test_already_covered_filters_entities(self):
        paper = {
            "title": "BRCA1 and WNT signaling",
            "abstract": "TP53 mutations interact with BRCA1.",
        }
        # BRCA1 already covered -> should NOT count
        score, covered = lit._compute_paper_coverage_score(
            paper,
            genes=["BRCA1", "TP53"],
            pathways=["WNT"],
            celltypes=[],
            already_covered={"BRCA1"},
        )
        assert "BRCA1" not in covered
        assert "TP53" in covered
        assert "WNT" in covered

    def test_celltype_matching(self):
        paper = {
            "title": "Fibroblast activation in tumors",
            "abstract": "Cancer-associated fibroblast interactions.",
        }
        score, covered = lit._compute_paper_coverage_score(
            paper,
            genes=[],
            pathways=[],
            celltypes=["Fibroblast", "T cell"],
        )
        assert "Fibroblast" in covered
        assert "T cell" not in covered


class TestGreedyCoverageSort:
    """Tests for _greedy_coverage_sort."""

    def _make_paper(self, pmid, title, abstract, sjr=0.5):
        return {
            "pmid": pmid,
            "title": title,
            "abstract": abstract,
            "journal_quality": sjr,
        }

    def test_coverage_papers_ranked_above_pure_sjr(self):
        """A paper covering target genes should rank above a high-SJR paper
        that covers nothing."""
        high_sjr_no_coverage = self._make_paper(
            "1", "Unrelated study", "Ocean currents and climate.", sjr=0.95,
        )
        low_sjr_good_coverage = self._make_paper(
            "2", "BRCA1 in breast cancer",
            "BRCA1 mutations and WNT signaling in tumor cells.", sjr=0.3,
        )
        result = lit._greedy_coverage_sort(
            [high_sjr_no_coverage, low_sjr_good_coverage],
            genes=["BRCA1"],
            pathways=["WNT"],
            celltypes=["Tumor"],
            max_results=2,
            alpha=0.4,
        )
        # Coverage paper should come first despite lower SJR
        assert result[0]["pmid"] == "2"

    def test_greedy_marginal_contribution(self):
        """Second pick should favour a paper covering NEW entities."""
        paper_a = self._make_paper(
            "A", "BRCA1 signaling", "BRCA1 and breast cancer.", sjr=0.7,
        )
        paper_b = self._make_paper(
            "B", "BRCA1 and WNT", "BRCA1 drives WNT activation.", sjr=0.8,
        )
        paper_c = self._make_paper(
            "C", "TP53 in MAPK", "TP53 mutations affect MAPK signaling.", sjr=0.5,
        )
        result = lit._greedy_coverage_sort(
            [paper_a, paper_b, paper_c],
            genes=["BRCA1", "TP53"],
            pathways=["WNT", "MAPK"],
            celltypes=[],
            max_results=3,
            alpha=0.4,
        )
        # First pick: paper_b (BRCA1 + WNT, higher SJR than A)
        assert result[0]["pmid"] == "B"
        # Second pick: paper_c (TP53 + MAPK are NEW entities)
        assert result[1]["pmid"] == "C"

    def test_empty_entities_falls_back_to_sjr(self):
        p1 = self._make_paper("1", "A", "a", sjr=0.3)
        p2 = self._make_paper("2", "B", "b", sjr=0.9)
        result = lit._greedy_coverage_sort(
            [p1, p2], genes=[], pathways=[], celltypes=[], max_results=2,
        )
        # Pure SJR order
        assert result[0]["pmid"] == "2"

    def test_max_results_respected(self):
        papers = [self._make_paper(str(i), f"P{i}", f"text{i}") for i in range(10)]
        result = lit._greedy_coverage_sort(
            papers, genes=["X"], pathways=[], celltypes=[], max_results=3,
        )
        assert len(result) <= 3


class TestQueryCacheReplay:
    """Tests for iteration-0 query cache record/replay."""

    @pytest.mark.asyncio
    async def test_record_queries_returns_cache(self, monkeypatch):
        """record_queries=True should populate query_cache in the result."""
        llm_queries = '[{"genes":["CDH1"],"diseases":["breast cancer"],"keywords":["EMT"]}]'
        monkeypatch.setattr(lit, "create_llm", lambda **kw: _MockLLM(llm_queries))

        async def _fake_search_with_biomcp(**kwargs):
            return [
                {"pmid": "99990001", "title": "CDH1 EMT study", "abstract": "CDH1 in breast cancer EMT."},
            ]

        monkeypatch.setattr(lit, "_search_with_biomcp", _fake_search_with_biomcp)

        result = await lit.search_literature_dynamic_async(
            genes=["CDH1"], pathways=["EMT"], celltypes=[], disease="breast cancer",
            max_results=5, max_iterations=1, record_queries=True,
        )

        assert "query_cache" in result
        assert len(result["query_cache"]) == 1
        assert result["query_cache"][0]["genes"] == ["CDH1"]

    @pytest.mark.asyncio
    async def test_replay_skips_llm(self, monkeypatch):
        """query_cache provided should skip LLM and use cached queries."""
        llm_called = {"count": 0}

        class _CountingLLM:
            async def ainvoke(self, _messages):
                llm_called["count"] += 1
                return _MockResponse('[{"genes":["WRONG"],"diseases":["wrong"],"keywords":["wrong"]}]')

        monkeypatch.setattr(lit, "create_llm", lambda **kw: _CountingLLM())

        async def _fake_search_with_biomcp(**kwargs):
            genes = kwargs.get("genes") or []
            return [
                {"pmid": "99990002", "title": f"{genes[0] if genes else 'X'} study",
                 "abstract": f"{genes[0] if genes else 'X'} in breast cancer."},
            ]

        monkeypatch.setattr(lit, "_search_with_biomcp", _fake_search_with_biomcp)

        cached = [{"genes": ["CDH1"], "diseases": ["breast cancer"], "keywords": ["EMT"]}]
        result = await lit.search_literature_dynamic_async(
            genes=["CDH1"], pathways=["EMT"], celltypes=[], disease="breast cancer",
            max_results=5, max_iterations=1, query_cache=cached,
        )

        # LLM should NOT have been called for iteration 0
        assert llm_called["count"] == 0
        assert len(result["papers"]) >= 1
        # query_cache should NOT be in result (record_queries was False)
        assert "query_cache" not in result

    @pytest.mark.asyncio
    async def test_replay_gap_filling_still_calls_llm(self, monkeypatch):
        """Iteration 1+ should always call LLM even when query_cache is provided."""
        llm_call_iterations: list[int] = []
        call_count = {"n": 0}

        class _TrackingLLM:
            async def ainvoke(self, messages):
                call_count["n"] += 1
                # Return gap-filling queries
                return _MockResponse(
                    '[{"genes":["VIM"],"diseases":["breast cancer"],"keywords":["mesenchymal"]}]'
                )

        monkeypatch.setattr(lit, "create_llm", lambda **kw: _TrackingLLM())

        search_call_count = {"n": 0}

        async def _fake_search_with_biomcp(**kwargs):
            search_call_count["n"] += 1
            return [
                {"pmid": f"8888000{search_call_count['n']}", "title": "Some paper",
                 "abstract": "CDH1 and EMT in breast cancer."},
            ]

        monkeypatch.setattr(lit, "_search_with_biomcp", _fake_search_with_biomcp)

        cached = [{"genes": ["CDH1"], "diseases": ["breast cancer"], "keywords": ["EMT"]}]
        result = await lit.search_literature_dynamic_async(
            genes=["CDH1", "VIM"], pathways=["EMT"], celltypes=[],
            disease="breast cancer",
            max_results=30, max_iterations=2, query_cache=cached,
        )

        # Iteration 0 used cache (no LLM), iteration 1 should call LLM for gap-filling
        assert call_count["n"] >= 1, "LLM should be called for gap-filling iterations"

    @pytest.mark.asyncio
    async def test_no_cache_backward_compatible(self, monkeypatch):
        """Without query_cache or record_queries, behavior is unchanged."""
        llm_queries = '[{"genes":["INS"],"diseases":["diabetes"],"keywords":["insulin"]}]'
        monkeypatch.setattr(lit, "create_llm", lambda **kw: _MockLLM(llm_queries))

        async def _fake_search_with_biomcp(**kwargs):
            return [
                {"pmid": "77770001", "title": "Insulin study", "abstract": "INS in diabetes."},
            ]

        monkeypatch.setattr(lit, "_search_with_biomcp", _fake_search_with_biomcp)

        result = await lit.search_literature_dynamic_async(
            genes=["INS"], pathways=["PI3K"], celltypes=[], disease="diabetes",
            max_results=5, max_iterations=1,
        )

        assert "query_cache" not in result
        assert "papers" in result
        assert len(result["papers"]) >= 1


class TestGapFillingValidation:
    """Tests for Option D: gap-filling iteration validation logic."""

    def test_compute_score_distinguishes_on_vs_off_target(self):
        """On-target paper should get score > 0, off-target should get 0."""
        on_target = {
            "title": "CDH1 expression in EMT",
            "abstract": "CDH1 downregulation drives epithelial-mesenchymal transition.",
        }
        off_target = {
            "title": "Climate change policy",
            "abstract": "Global warming mitigation strategies reviewed.",
        }
        score_on, _ = lit._compute_paper_coverage_score(
            on_target, genes=["CDH1"], pathways=["EMT"], celltypes=[],
        )
        score_off, _ = lit._compute_paper_coverage_score(
            off_target, genes=["CDH1"], pathways=["EMT"], celltypes=[],
        )
        assert score_on > 0
        assert score_off == 0
