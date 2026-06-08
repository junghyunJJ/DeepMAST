import asyncio

import pytest

from src.agents.deep_interpreter.tools import literature as lit


class _SlowLLM:
    async def ainvoke(self, _messages):
        await asyncio.sleep(1)
        raise AssertionError("timeout should cancel before this point")


def test_build_deterministic_lr_pair_queries_uses_every_unique_pair():
    pairs = [
        {"ligand": "APOE", "receptor": "TREM2"},
        {"ligand": "apoe", "receptor": "trem2"},
        {"ligand": "CALR", "receptor": "ITGA3"},
        {"ligand": "", "receptor": "ITGB1"},
    ]

    queries = lit._build_deterministic_lr_pair_queries(
        pairs, "idiopathic pulmonary fibrosis"
    )

    assert len(queries) == 2
    assert queries[0] == {
        "genes": ["APOE", "TREM2"],
        "diseases": ["idiopathic pulmonary fibrosis"],
        "keywords": ["ligand receptor", "cell-cell interaction", "signaling"],
        "query_intent": "deterministic_lr_pair",
    }
    assert queries[1]["genes"] == ["CALR", "ITGA3"]


def test_format_lr_pairs_for_prompt_includes_30_pairs():
    pairs = [
        {"ligand": f"L{i}", "receptor": f"R{i}"}
        for i in range(1, 31)
    ]

    formatted = lit._format_lr_pairs_for_prompt(pairs)

    assert "L1-R1" in formatted
    assert "L30-R30" in formatted


def test_partition_routes_deterministic_lr_pair_queries_to_gene_lane():
    query = lit._build_deterministic_lr_pair_queries(
        [{"ligand": "APOE", "receptor": "TREM2"}],
        "idiopathic pulmonary fibrosis",
    )[0]

    gene_records, pathway_records, keyword_records = lit._partition_literature_queries(
        [query]
    )

    assert gene_records == [(0, query, "deterministic_lr_pair")]
    assert pathway_records == []
    assert keyword_records == []


@pytest.mark.asyncio
async def test_searcher_mode_llm_timeout_continues_with_lr_pair_queries(monkeypatch):
    monkeypatch.setenv("LITERATURE_QUERY_GENERATION_TIMEOUT", "0.01")
    monkeypatch.setattr(lit, "create_llm", lambda **_kw: _SlowLLM())

    calls: list[dict] = []

    async def _fake_search_with_biomcp(**kwargs):
        calls.append(kwargs)
        return [
            {
                "pmid": str(1000 + len(calls)),
                "title": "APOE TREM2 signaling in idiopathic pulmonary fibrosis",
                "abstract": (
                    "APOE and TREM2 ligand receptor signaling is studied in "
                    "idiopathic pulmonary fibrosis."
                ),
                "matched_via_query": {
                    "genes": kwargs.get("genes") or [],
                    "diseases": kwargs.get("diseases") or [],
                    "keywords": kwargs.get("keywords") or [],
                },
            }
        ]

    monkeypatch.setattr(lit, "_search_with_biomcp", _fake_search_with_biomcp)

    result = await lit.search_literature_dynamic_async(
        genes=[],
        pathways=[],
        celltypes=[],
        disease="idiopathic pulmonary fibrosis",
        max_results=10,
        max_iterations=1,
        lr_pairs=[
            {"ligand": "APOE", "receptor": "TREM2"},
            {"ligand": "CALR", "receptor": "ITGA3"},
        ],
        enable_lr_pair_queries=True,
        sort_by_journal_quality=False,
    )

    assert [call["genes"] for call in calls[:2]] == [
        ["APOE", "TREM2"],
        ["CALR", "ITGA3"],
    ]
    assert result["generated_queries"][0]["query_intent"] == "deterministic_lr_pair"
    assert result["generated_queries"][1]["query_intent"] == "deterministic_lr_pair"
    assert result["papers"][0]["query_type"] == "lr_pair"
