"""Unit smoke tests for `_build_deterministic_pathway_queries` (F1 follow-up).

These tests guard the hybrid pathway fan-out helper that recovers the 8pp
pathway coverage regression introduced by Fix A* (84.6% → 76.9%) on
`res_bc_ollama`. The helper emits one BioMCP query per pathway carrying both
the canonical pathway keyword AND the top-N hub genes registered for that
pathway in PATHWAY_TO_GENES, reusing BioMCP's gene-indexed retrieval pipeline.
"""

from src.agents.deep_interpreter.tools.literature import (
    PATHWAY_KEYWORDS,
    PATHWAY_TO_GENES,
    _build_deterministic_pathway_queries,
    _format_pathway_keyword,
)


def test_empty_pathways_returns_empty():
    assert _build_deterministic_pathway_queries([], "breast cancer") == []


def test_mapk_resolves_to_canonical_genes_and_keyword():
    """`mapk` → top-3 hub genes + canonical "erk signaling" keyword."""
    qs = _build_deterministic_pathway_queries(["mapk"], "breast cancer")
    assert len(qs) == 1
    q = qs[0]
    assert q["genes"] == ["MAPK1", "MAPK3", "RAF1"]
    assert q["diseases"] == ["breast cancer"]
    assert q["keywords"] == ["erk signaling"]


def test_unknown_pathway_falls_back_to_keyword_only():
    """Unknown pathway → empty genes, fallback "<name> signaling" keyword."""
    qs = _build_deterministic_pathway_queries(["XYZ"], "breast cancer")
    assert len(qs) == 1
    q = qs[0]
    assert q["genes"] == []
    assert q["keywords"] == ["XYZ signaling"]
    assert q["diseases"] == ["breast cancer"]


def test_semicolon_split_yields_one_query_per_part():
    """Combined pathway "Androgen;MAPK" → 2 queries (mirrors _generate_pathway_patterns)."""
    qs = _build_deterministic_pathway_queries(["Androgen;MAPK"], "breast cancer")
    assert len(qs) == 2
    # Order preserved from split
    assert qs[0]["genes"] == ["AR", "KLK3"]
    assert qs[0]["keywords"] == ["androgen receptor"]
    assert qs[1]["genes"] == ["MAPK1", "MAPK3", "RAF1"]
    assert qs[1]["keywords"] == ["erk signaling"]


def test_empty_disease_yields_empty_disease_list():
    qs = _build_deterministic_pathway_queries(["mapk"], "")
    assert len(qs) == 1
    assert qs[0]["diseases"] == []


def test_vegf_tnfa_trail_resolve_to_new_entries():
    """REV-6: VEGF/TNFa/Trail must resolve via PATHWAY_KEYWORDS + PATHWAY_TO_GENES.

    Closes the gap Critic identified — these three pathways were missing from
    PATHWAY_KEYWORDS pre-F1 and are exactly the ones that regressed post-Fix A*.
    """
    qs = _build_deterministic_pathway_queries(
        ["vegf", "tnfa", "trail"], "breast cancer"
    )
    assert len(qs) == 3

    vegf_q, tnfa_q, trail_q = qs

    assert vegf_q["genes"] == ["VEGFA", "KDR", "FLT1"]
    assert vegf_q["keywords"] == [PATHWAY_KEYWORDS["vegf"][0]]  # "vegf"

    assert tnfa_q["genes"] == ["TNF", "TNFRSF1A", "TRADD"]
    assert tnfa_q["keywords"] == [PATHWAY_KEYWORDS["tnfa"][0]]  # "tnf"

    assert trail_q["genes"] == ["TNFSF10", "TNFRSF10A", "TNFRSF10B"]
    assert trail_q["keywords"] == [PATHWAY_KEYWORDS["trail"][0]]  # "trail"


def test_max_genes_per_query_truncates():
    """`max_genes_per_query=2` truncates the gene list."""
    qs = _build_deterministic_pathway_queries(
        ["mapk"], "breast cancer", max_genes_per_query=2
    )
    assert len(qs) == 1
    assert qs[0]["genes"] == ["MAPK1", "MAPK3"]


def test_jak_key_matches_pathway_keywords_jak():
    """REV-9 regression: PATHWAY_TO_GENES["jak"] must exist and match PATHWAY_KEYWORDS["jak"].

    Guards against the prior `jak-stat` key mismatch where the hybrid pathway
    fan-out would have fallen back to keyword-only because PATHWAY_TO_GENES
    used a key that didn't agree with PATHWAY_KEYWORDS substring conventions.
    """
    assert "jak" in PATHWAY_TO_GENES
    assert "jak" in PATHWAY_KEYWORDS
    qs = _build_deterministic_pathway_queries(["jak"], "breast cancer")
    assert len(qs) == 1
    assert qs[0]["genes"] == ["JAK2", "STAT3", "STAT5A"]
    assert qs[0]["keywords"] == ["jak/stat"]


def test_format_pathway_keyword_substring_match():
    """Substring match mirrors _generate_pathway_patterns at literature.py:1586."""
    # Exact-key
    assert _format_pathway_keyword("mapk") == "erk signaling"
    # Substring (e.g., "MAPK signaling")
    assert _format_pathway_keyword("MAPK signaling") == "erk signaling"
    # Unknown → fallback
    assert _format_pathway_keyword("xyz") == "xyz signaling"


def test_filters_falsy_pathway_strings():
    """Empty strings and None entries are dropped silently."""
    qs = _build_deterministic_pathway_queries(
        ["mapk", "", "vegf"], "breast cancer"  # type: ignore[list-item]
    )
    assert len(qs) == 2
    assert qs[0]["genes"] == ["MAPK1", "MAPK3", "RAF1"]
    assert qs[1]["genes"] == ["VEGFA", "KDR", "FLT1"]


def test_tgf_key_parity_with_pathway_keywords():
    """REV-9 parity guard: both `TGF` and `TGFB` inputs must resolve to genes.

    Pre-fix the key was `tgfb` in PATHWAY_TO_GENES which mismatched PATHWAY_KEYWORDS["tgf"].
    Architect review flagged this — input "TGF" would miss gene resolution.
    """
    assert "tgf" in PATHWAY_TO_GENES
    assert "tgf" in PATHWAY_KEYWORDS
    # Both short ("TGF") and long ("TGFB") forms must resolve to the same genes.
    qs_short = _build_deterministic_pathway_queries(["TGF"], "breast cancer")
    qs_long = _build_deterministic_pathway_queries(["TGFB"], "breast cancer")
    assert len(qs_short) == 1
    assert len(qs_long) == 1
    assert qs_short[0]["genes"] == ["TGFB1", "SMAD4", "ACVR2B"]
    assert qs_long[0]["genes"] == ["TGFB1", "SMAD4", "ACVR2B"]
    assert qs_short[0]["keywords"] == ["tgf-beta"]
    assert qs_long[0]["keywords"] == ["tgf-beta"]


def test_all_pathway_to_genes_keys_have_keyword_counterparts():
    """Full REV-9 parity contract: every PATHWAY_TO_GENES key must exist in PATHWAY_KEYWORDS."""
    missing = [k for k in PATHWAY_TO_GENES if k not in PATHWAY_KEYWORDS]
    assert missing == [], f"PATHWAY_TO_GENES keys missing from PATHWAY_KEYWORDS: {missing}"


def test_p53_and_hypoxia_resolve_to_canonical_keywords():
    """Nit 2 fix: p53/hypoxia now have PATHWAY_KEYWORDS entries, not just generic fallback."""
    qs = _build_deterministic_pathway_queries(["p53", "hypoxia"], "breast cancer")
    assert len(qs) == 2
    p53_q, hypoxia_q = qs
    assert p53_q["genes"] == ["TP53", "MDM2", "CDKN1A"]
    assert p53_q["keywords"] == [PATHWAY_KEYWORDS["p53"][0]]  # "p53"
    assert hypoxia_q["genes"] == ["HIF1A", "VHL", "EPAS1"]
    assert hypoxia_q["keywords"] == [PATHWAY_KEYWORDS["hypoxia"][0]]  # "hif-1alpha"


def test_wnt_resolves_to_canonical_hub_genes():
    """Closes the PROGENy WNT coverage gap.

    Prior to this fix, PATHWAY_TO_GENES had no "wnt" key and "WNT" inputs
    fell through substring-matching to an empty genes list — production
    WNT L-R pairs got keyword-only BioMCP queries with no hub gene anchor.
    WNT is the 14th PROGENy pathway; this entry completes the dict's
    PROGENy coverage.
    """
    assert "wnt" in PATHWAY_TO_GENES
    assert "wnt" in PATHWAY_KEYWORDS
    qs = _build_deterministic_pathway_queries(["WNT"], "breast cancer")
    assert len(qs) == 1
    assert qs[0]["genes"] == ["CTNNB1", "WNT3A", "LEF1"]
    assert qs[0]["keywords"] == [PATHWAY_KEYWORDS["wnt"][0]]  # "beta-catenin"
    assert qs[0]["diseases"] == ["breast cancer"]
