"""Regression tests for query-intent routed dynamic literature filtering."""

import pytest

from src.agents.deep_interpreter.tools import literature as lit


class _MockResponse:
    def __init__(self, content: str):
        self.content = content


class _MockLLM:
    def __init__(self, responses: list[str] | str):
        if isinstance(responses, str):
            responses = [responses]
        self._responses = list(responses)

    async def ainvoke(self, _messages):
        content = self._responses.pop(0) if self._responses else "[]"
        return _MockResponse(content)


@pytest.mark.asyncio
async def test_generic_keyword_query_is_retained_without_pathway_filter(monkeypatch):
    monkeypatch.setattr(lit, "create_llm", lambda **_kw: _MockLLM("[]"))

    async def _fake_search_with_biomcp(**kwargs):
        assert kwargs["keywords"] == ["tumor associated macrophages"]
        return [
            {
                "pmid": "K1",
                "title": "Macrophage infiltration remodels invasive tumors",
                "abstract": "Myeloid infiltration reshapes the stromal niche.",
            }
        ]

    monkeypatch.setattr(lit, "_search_with_biomcp", _fake_search_with_biomcp)

    result = await lit.search_literature_dynamic_async(
        genes=[],
        pathways=[],
        celltypes=[],
        disease="breast cancer",
        max_results=5,
        max_iterations=1,
        query_cache=[
            {
                "genes": [],
                "diseases": ["breast cancer"],
                "keywords": ["tumor associated macrophages"],
            }
        ],
        sort_by_journal_quality=False,
    )

    assert [p["pmid"] for p in result["papers"]] == ["K1"]
    assert result["papers"][0]["query_type"] == "keyword"
    assert result["papers"][0]["query_index"] == 0


@pytest.mark.asyncio
async def test_deterministic_pathway_query_requires_text_confirmation(monkeypatch):
    monkeypatch.setattr(lit, "create_llm", lambda **_kw: _MockLLM("[]"))

    async def _fake_search_with_biomcp(**_kwargs):
        return [
            {
                "pmid": "P1",
                "title": "Macrophage infiltration in invasive tumors",
                "abstract": "Myeloid cells reshape the stromal niche.",
            }
        ]

    monkeypatch.setattr(lit, "_search_with_biomcp", _fake_search_with_biomcp)

    result = await lit.search_literature_dynamic_async(
        genes=[],
        pathways=["MAPK"],
        celltypes=[],
        disease="breast cancer",
        max_results=5,
        max_iterations=1,
        query_cache=[],
        enable_lr_pair_queries=True,
        sort_by_journal_quality=False,
    )

    assert result["papers"] == []
    assert result["generated_queries"][0]["query_intent"] == "deterministic_pathway"


@pytest.mark.asyncio
async def test_cached_old_pathway_query_is_replaced_with_trusted_intent(monkeypatch):
    monkeypatch.setattr(lit, "create_llm", lambda **_kw: _MockLLM("[]"))
    deterministic_query = lit._build_deterministic_pathway_queries(
        ["MAPK"], "breast cancer"
    )[0]
    calls: list[dict] = []

    async def _fake_search_with_biomcp(**kwargs):
        calls.append(kwargs)
        return [
            {
                "pmid": "P2",
                "title": "MAPK signaling pathway in breast cancer",
                "abstract": "ERK signaling is activated in breast cancer.",
            }
        ]

    monkeypatch.setattr(lit, "_search_with_biomcp", _fake_search_with_biomcp)

    result = await lit.search_literature_dynamic_async(
        genes=[],
        pathways=["MAPK"],
        celltypes=[],
        disease="breast cancer",
        max_results=5,
        max_iterations=1,
        query_cache=[
            {
                "genes": [],
                "diseases": ["breast cancer"],
                "keywords": deterministic_query["keywords"],
            }
        ],
        enable_lr_pair_queries=True,
        record_queries=True,
        sort_by_journal_quality=False,
    )

    assert result["generated_queries"] == [deterministic_query]
    assert result["query_cache"] == [deterministic_query]
    assert calls[0]["keywords"] == deterministic_query["keywords"]
    assert result["papers"][0]["query_type"] == "pathway"
    assert result["papers"][0]["query_index"] == 0


@pytest.mark.asyncio
async def test_later_iteration_query_index_uses_global_generated_query_offset(monkeypatch):
    monkeypatch.setattr(
        lit,
        "create_llm",
        lambda **_kw: _MockLLM(
            '[{"genes":[],"diseases":["breast cancer"],"keywords":["immune niche"]}]'
        ),
    )
    deterministic_keywords = lit._build_deterministic_pathway_queries(
        ["MAPK"], "breast cancer"
    )[0]["keywords"]

    async def _fake_search_with_biomcp(**kwargs):
        keywords = kwargs.get("keywords") or []
        if keywords == deterministic_keywords:
            return [
                {
                    "pmid": "DROP",
                    "title": "Unrelated macrophage study",
                    "abstract": "No disease or pathway text.",
                }
            ]
        if keywords == ["tumor associated macrophages"]:
            return [
                {
                    "pmid": "K0",
                    "title": "Macrophage infiltration remodels invasive tumors",
                    "abstract": "Myeloid cells reshape the stromal niche.",
                }
            ]
        if keywords == ["immune niche"]:
            return [
                {
                    "pmid": "K2",
                    "title": "Immune niche and MAPK signaling pathway in breast cancer",
                    "abstract": "Breast cancer niches show ERK signaling activation.",
                }
            ]
        return []

    monkeypatch.setattr(lit, "_search_with_biomcp", _fake_search_with_biomcp)

    result = await lit.search_literature_dynamic_async(
        genes=[],
        pathways=["MAPK"],
        celltypes=[],
        disease="breast cancer",
        max_results=10,
        max_iterations=2,
        query_cache=[
            {
                "genes": [],
                "diseases": ["breast cancer"],
                "keywords": ["tumor associated macrophages"],
            }
        ],
        enable_lr_pair_queries=True,
        sort_by_journal_quality=False,
    )

    assert result["generated_queries"][0]["query_intent"] == "deterministic_pathway"
    assert result["generated_queries"][1]["keywords"] == ["tumor associated macrophages"]
    assert result["generated_queries"][2]["keywords"] == ["immune niche"]

    paper_by_pmid = {paper["pmid"]: paper for paper in result["papers"]}
    assert paper_by_pmid["K2"]["query_type"] == "keyword"
    assert paper_by_pmid["K2"]["query_index"] == 2
