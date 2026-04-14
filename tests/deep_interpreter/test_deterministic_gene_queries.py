"""Unit smoke tests for `_build_deterministic_gene_queries` (Fix A* Step 5).

These tests guard the deterministic gene fan-out helper that closes the SEARCHER
hub-gene coverage ceiling at 36.7% on `res_bc_ollama` (root cause: genes[:5] hard
cap × 2 LLM gene queries = 10 hub gene slots for 30 hub genes).
"""

from src.agents.deep_interpreter.tools.literature import _build_deterministic_gene_queries


def test_chunks_13_genes_into_3_queries():
    genes = [f"G{i}" for i in range(1, 14)]
    qs = _build_deterministic_gene_queries(genes, "breast cancer", chunk_size=5)
    assert len(qs) == 3
    assert [len(q["genes"]) for q in qs] == [5, 5, 3]
    assert {g for q in qs for g in q["genes"]} == set(genes)
    assert all(q["diseases"] == ["breast cancer"] for q in qs)
    assert all(q["keywords"] == [] for q in qs)


def test_chunks_30_genes_into_6_queries():
    """Production-scale case: 30 hub genes -> 6 queries, each with 5 gene slots.

    This is the exact case Fix A* targets for res_bc_ollama (30 hub genes).
    """
    genes = [f"GENE{i}" for i in range(30)]
    qs = _build_deterministic_gene_queries(genes, "breast cancer", chunk_size=5)
    assert len(qs) == 6
    assert all(len(q["genes"]) == 5 for q in qs)
    # Every input gene must appear in at least one query.
    assert {g for q in qs for g in q["genes"]} == set(genes)


def test_empty_genes_returns_empty():
    assert _build_deterministic_gene_queries([], "breast cancer") == []


def test_no_disease_yields_empty_disease_list():
    qs = _build_deterministic_gene_queries(["A", "B"], "", chunk_size=5)
    assert len(qs) == 1
    assert qs[0]["diseases"] == []
    assert qs[0]["genes"] == ["A", "B"]


def test_chunk_size_smaller_than_input():
    genes = ["A", "B", "C"]
    qs = _build_deterministic_gene_queries(genes, "x", chunk_size=2)
    assert len(qs) == 2
    assert qs[0]["genes"] == ["A", "B"]
    assert qs[1]["genes"] == ["C"]


def test_filters_falsy_gene_strings():
    """Empty strings and None entries are dropped silently."""
    genes = ["A", "", "B", None, "C"]  # type: ignore[list-item]
    qs = _build_deterministic_gene_queries(genes, "x", chunk_size=5)  # type: ignore[arg-type]
    # Single chunk, falsy entries removed.
    assert len(qs) == 1
    assert qs[0]["genes"] == ["A", "B", "C"]
