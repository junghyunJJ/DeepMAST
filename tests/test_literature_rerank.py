"""Unit tests for optional LLM rerank in literature search."""

import inspect

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


def test_parse_rerank_judgments_codefence():
    response = """
    ```json
    [
      {"source":"kept","pmid":"12345678","verdict":"irrelevant","confidence":0.91},
      {"source":"removed","pmid":"87654321","verdict":"relevant","confidence":0.84}
    ]
    ```
    """
    parsed = lit._parse_rerank_judgments(response)
    assert parsed[("kept", "12345678")] == ("irrelevant", 0.91)
    assert parsed[("removed", "87654321")] == ("relevant", 0.84)


@pytest.mark.asyncio
async def test_search_with_biomcp_llm_rerank_drops_boundary_paper(monkeypatch):
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
                "title": "Mammary stromal remodeling study",
                "abstract": "Mammary microenvironment with broad tumor context.",
            }

        return [
            _MockTool("article_searcher", _searcher),
            _MockTool("article_getter", _getter),
        ]

    async def _fake_disease_synonyms(_disease, _biomcp_url=lit.DEFAULT_BIOMCP_URL):
        return ["breast cancer", "mammary"]

    monkeypatch.setattr(lit, "get_biomcp_tools", _fake_get_tools)
    monkeypatch.setattr(lit, "_get_disease_synonyms_async", _fake_disease_synonyms)
    monkeypatch.setattr(
        lit, "get_disease_match_terms", lambda _disease: ["breast cancer", "mammary"]
    )
    monkeypatch.setattr(
        lit,
        "create_llm",
        lambda: _MockLLM(
            '[{"source":"kept","pmid":"33333333","verdict":"irrelevant","confidence":0.95}]'
        ),
    )

    stats = {"applied_count": 0, "promoted_count": 0, "dropped_count": 0}
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
    assert pmids == {"11111111"}
    assert stats["applied_count"] == 1
    assert stats["dropped_count"] == 1
    assert stats["promoted_count"] == 0


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
            rerank_stats["promoted_count"] = rerank_stats.get("promoted_count", 0) + 0
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
    assert result["rerank_promoted_count"] == 0
