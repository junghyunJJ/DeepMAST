"""Unit tests for keyword-only deterministic pathway queries."""

from inspect import signature

from src.agents.deep_interpreter.tools.literature import (
    PATHWAY_KEYWORDS,
    _build_deterministic_pathway_queries,
    _classify_literature_query,
    _format_pathway_keyword,
    _format_pathway_keywords,
    _generate_pathway_patterns,
    _normalize_replayed_queries,
    _partition_literature_queries,
    _validate_generated_queries,
)


def test_empty_pathways_returns_empty():
    assert _build_deterministic_pathway_queries([], "breast cancer") == []


def test_mapk_resolves_to_controlled_keywords_without_genes():
    qs = _build_deterministic_pathway_queries(["mapk"], "breast cancer")
    assert len(qs) == 1
    q = qs[0]
    assert q["genes"] == []
    assert q["diseases"] == ["breast cancer"]
    assert q["keywords"] == PATHWAY_KEYWORDS["mapk"]["query_terms"][:3]
    assert q["keywords"][0] == "MAPK signaling pathway"
    assert q["query_intent"] == "deterministic_pathway"


def test_unknown_pathway_falls_back_to_keyword_only():
    qs = _build_deterministic_pathway_queries(["XYZ"], "breast cancer")
    assert len(qs) == 1
    q = qs[0]
    assert q["genes"] == []
    assert q["keywords"] == ["XYZ signaling"]
    assert q["diseases"] == ["breast cancer"]
    assert q["query_intent"] == "deterministic_pathway"


def test_semicolon_split_yields_one_keyword_only_query_per_part():
    qs = _build_deterministic_pathway_queries(["Androgen;MAPK"], "breast cancer")
    assert len(qs) == 2
    assert qs[0]["genes"] == []
    assert qs[0]["keywords"] == PATHWAY_KEYWORDS["androgen"]["query_terms"][:3]
    assert qs[0]["query_intent"] == "deterministic_pathway"
    assert qs[1]["genes"] == []
    assert qs[1]["keywords"] == PATHWAY_KEYWORDS["mapk"]["query_terms"][:3]
    assert qs[1]["query_intent"] == "deterministic_pathway"


def test_empty_disease_yields_empty_disease_list():
    qs = _build_deterministic_pathway_queries(["mapk"], "")
    assert len(qs) == 1
    assert qs[0]["genes"] == []
    assert qs[0]["diseases"] == []


def test_vegf_tnfa_trail_resolve_to_controlled_entries():
    qs = _build_deterministic_pathway_queries(
        ["vegf", "tnfa", "trail"], "breast cancer"
    )
    assert len(qs) == 3

    vegf_q, tnfa_q, trail_q = qs

    assert vegf_q["genes"] == []
    assert vegf_q["keywords"] == PATHWAY_KEYWORDS["vegf"]["query_terms"][:3]

    assert tnfa_q["genes"] == []
    assert tnfa_q["keywords"] == PATHWAY_KEYWORDS["tnfa"]["query_terms"][:3]

    assert trail_q["genes"] == []
    assert trail_q["keywords"] == PATHWAY_KEYWORDS["trail"]["query_terms"][:3]


def test_jak_and_tgf_alias_inputs_match_controlled_vocabulary():
    jak = _build_deterministic_pathway_queries(["JAK/STAT"], "breast cancer")
    tgf = _build_deterministic_pathway_queries(["TGFB"], "breast cancer")

    assert jak[0]["genes"] == []
    assert jak[0]["keywords"] == PATHWAY_KEYWORDS["jak"]["query_terms"][:3]
    assert tgf[0]["genes"] == []
    assert tgf[0]["keywords"] == PATHWAY_KEYWORDS["tgf"]["query_terms"][:3]


def test_format_pathway_keywords_substring_match():
    assert _format_pathway_keywords("mapk") == PATHWAY_KEYWORDS["mapk"]["query_terms"][:3]
    assert (
        _format_pathway_keywords("MAPK signaling")
        == PATHWAY_KEYWORDS["mapk"]["query_terms"][:3]
    )
    assert _format_pathway_keyword("mapk") == PATHWAY_KEYWORDS["mapk"]["query_terms"][0]
    assert _format_pathway_keywords("xyz") == ["xyz signaling"]


def test_tnfa_msigdb_phrase_resolves_to_tnfa_not_nfkb():
    assert (
        _format_pathway_keywords("TNFA signaling via NFKB")
        == PATHWAY_KEYWORDS["tnfa"]["query_terms"][:3]
    )
    patterns = set(_generate_pathway_patterns("TNFA signaling via NFKB"))
    assert "tnf" in patterns
    assert "nf-kb" not in patterns


def test_controlled_vocabulary_entries_have_source_metadata():
    for key, entry in PATHWAY_KEYWORDS.items():
        assert entry["canonical_label"], key
        assert 1 <= len(entry["query_terms"]) <= 3, key
        assert entry["query_terms"][0] == entry["canonical_label"], key
        assert entry["match_aliases"], key
        assert entry["source_refs"], key
        assert all("source" in ref and "term" in ref for ref in entry["source_refs"]), key
        assert all(ref["source"] != "STRING" for ref in entry["source_refs"]), key


def test_generate_pathway_patterns_uses_controlled_aliases():
    patterns = {p.lower() for p in _generate_pathway_patterns("MAPK")}
    assert "mapk signaling pathway" in patterns
    assert "erk signaling" in patterns
    assert "mek/erk" in patterns


def test_pathway_helper_signature_has_no_gene_anchor_options():
    params = signature(_build_deterministic_pathway_queries).parameters
    assert "pathway_to_genes" not in params
    assert "max_genes_per_query" not in params


def test_filters_falsy_pathway_strings():
    qs = _build_deterministic_pathway_queries(
        ["mapk", "", "vegf"], "breast cancer"  # type: ignore[list-item]
    )
    assert len(qs) == 2
    assert qs[0]["genes"] == []
    assert qs[1]["genes"] == []


def test_classify_literature_query_uses_explicit_intent_only():
    assert _classify_literature_query(
        {"genes": ["CDH1"], "diseases": [], "keywords": []}
    ) == "gene"
    assert _classify_literature_query(
        {
            "genes": [],
            "diseases": ["breast cancer"],
            "keywords": ["MAPK signaling pathway"],
            "query_intent": "deterministic_pathway",
        }
    ) == "deterministic_pathway"
    assert _classify_literature_query(
        {
            "genes": [],
            "diseases": ["breast cancer"],
            "keywords": ["tumor associated macrophages"],
        }
    ) == "keyword"


def test_validate_generated_queries_ignores_raw_query_intent():
    validated = _validate_generated_queries([
        {
            "genes": [],
            "diseases": ["breast cancer"],
            "keywords": ["tumor associated macrophages"],
            "query_intent": "deterministic_pathway",
        }
    ])

    assert validated == [
        {
            "genes": [],
            "diseases": ["breast cancer"],
            "keywords": ["tumor associated macrophages"],
        }
    ]
    assert _classify_literature_query(validated[0]) == "keyword"


def test_normalize_replayed_queries_strips_cached_query_intent():
    normalized = _normalize_replayed_queries([
        {
            "genes": [],
            "diseases": ["breast cancer"],
            "keywords": ["tumor associated macrophages"],
            "query_intent": "deterministic_pathway",
        }
    ])

    assert "query_intent" not in normalized[0]
    assert _classify_literature_query(normalized[0]) == "keyword"


def test_partition_literature_queries_preserves_original_indices():
    queries = [
        {"genes": ["CDH1"], "diseases": [], "keywords": []},
        {
            "genes": [],
            "diseases": ["breast cancer"],
            "keywords": ["MAPK signaling pathway"],
            "query_intent": "deterministic_pathway",
        },
        {
            "genes": [],
            "diseases": ["breast cancer"],
            "keywords": ["tumor associated macrophages"],
        },
    ]

    gene_records, pathway_records, keyword_records = _partition_literature_queries(queries)

    assert gene_records == [(0, queries[0], "gene")]
    assert pathway_records == [(1, queries[1], "deterministic_pathway")]
    assert keyword_records == [(2, queries[2], "keyword")]
