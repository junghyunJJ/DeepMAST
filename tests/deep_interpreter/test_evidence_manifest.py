"""Unit tests for F2 Evidence Manifest (retrieval-time provenance stamp).

Guards two-tier provenance accounting:
  - `_search_with_biomcp` stamps every returned article with `matched_via_query`.
  - `_calculate_coverage(use_retrieval_tags=True)` emits
    `biomcp_tag+text_confirmed` vs `biomcp_tag_only` labels in
    `genes_matched_by` / `pathways_matched_by`.
  - `_compute_paper_coverage_score` unconditionally honors the stamp but is
    unreachable on PLANNER/REPORTER paths via the REV-7 dead-code chain.
"""

from unittest.mock import AsyncMock, patch

import pytest

from src.agents.deep_interpreter.tools import literature as lit
from src.agents.deep_interpreter.tools.literature import (
    _calculate_coverage,
    _compute_paper_coverage_score,
    _search_with_biomcp,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

def _paper(pmid: str, title: str = "", abstract: str = "", stamp: dict | None = None) -> dict:
    p = {"pmid": pmid, "title": title, "abstract": abstract}
    if stamp is not None:
        p["matched_via_query"] = stamp
    return p


# ---------------------------------------------------------------------------
# (a) Stamp attaches on the success branch (REV-8 1a)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_with_biomcp_stamps_success_branch():
    """Mocked BioMCP success path — article is stamped via REV-8 (1a)."""
    fake_searcher = AsyncMock()
    fake_searcher.name = "article_searcher"
    fake_getter = AsyncMock()
    fake_getter.name = "article_getter"

    async def _fake_tools(_url):
        return [fake_searcher, fake_getter]

    with patch.object(lit, "get_biomcp_tools", side_effect=_fake_tools), \
         patch.object(lit, "_parse_pmids", return_value=["12345"]), \
         patch.object(
             lit, "_parse_article",
             return_value={"pmid": "12345", "title": "BRCA1 study", "abstract": "abstract"},
         ):
        fake_getter.ainvoke = AsyncMock(return_value={})
        fake_searcher.ainvoke = AsyncMock(return_value={})
        articles = await _search_with_biomcp(
            genes=["BRCA1"], diseases=["breast cancer"], keywords=["dna repair"],
        )

    assert len(articles) == 1
    stamp = articles[0].get("matched_via_query")
    assert stamp == {
        "genes": ["BRCA1"],
        "diseases": ["breast cancer"],
        "keywords": ["dna repair"],
    }


# ---------------------------------------------------------------------------
# (h) Stamp attaches on exception + pmid-only fallback branches (REV-8 1b/1c)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_with_biomcp_stamps_exception_fallback():
    """Mocked BioMCP exception path — err_article stamped via REV-8 (1b)."""
    fake_searcher = AsyncMock()
    fake_getter = AsyncMock()

    async def _fake_tools(_url):
        return [fake_searcher, fake_getter]

    with patch.object(lit, "get_biomcp_tools", side_effect=_fake_tools), \
         patch.object(lit, "_parse_pmids", return_value=["99999"]):
        fake_searcher.ainvoke = AsyncMock(return_value={})
        # Getter raises — triggers exception fallback branch
        fake_getter.ainvoke = AsyncMock(side_effect=RuntimeError("boom"))
        articles = await _search_with_biomcp(
            genes=["INSR"], diseases=["breast cancer"], keywords=[],
        )

    assert len(articles) == 1
    assert articles[0]["title"] == "Article 99999"
    assert articles[0]["matched_via_query"] == {
        "genes": ["INSR"], "diseases": ["breast cancer"], "keywords": [],
    }


@pytest.mark.asyncio
async def test_search_with_biomcp_stamps_pmid_only_fallback():
    """Missing article_getter — fallback_article stamped via REV-8 (1c)."""
    fake_searcher = AsyncMock()
    fake_searcher.name = "article_searcher"

    async def _fake_tools(_url):
        # Only searcher tool available — no getter
        return [fake_searcher]

    with patch.object(lit, "get_biomcp_tools", side_effect=_fake_tools), \
         patch.object(lit, "_parse_pmids", return_value=["77777"]):
        fake_searcher.ainvoke = AsyncMock(return_value={})
        articles = await _search_with_biomcp(
            genes=["SEMA3F"], diseases=["breast cancer"], keywords=["axon guidance"],
        )

    assert len(articles) == 1
    assert articles[0]["pmid"] == "77777"
    assert articles[0]["matched_via_query"] == {
        "genes": ["SEMA3F"],
        "diseases": ["breast cancer"],
        "keywords": ["axon guidance"],
    }


# ---------------------------------------------------------------------------
# (b) use_retrieval_tags=True marks INSR as `biomcp_tag_only` when stamped
# ---------------------------------------------------------------------------

def test_calculate_coverage_marks_biomcp_tag_only():
    """INSR stamped, empty abstract → `biomcp_tag_only` tier."""
    papers = [
        _paper(
            "1",
            title="Unrelated title",
            abstract="",
            stamp={"genes": ["INSR"], "diseases": [], "keywords": []},
        ),
    ]
    cov = _calculate_coverage(
        papers, genes=["INSR"], pathways=[], celltypes=[],
        use_retrieval_tags=True,
    )
    assert "INSR" in cov["genes_covered"]
    assert cov["genes_matched_by"]["INSR"] == "biomcp_tag_only"


# ---------------------------------------------------------------------------
# (c) use_retrieval_tags=True marks BRCA1 as `biomcp_tag+text_confirmed`
# ---------------------------------------------------------------------------

def test_calculate_coverage_marks_biomcp_tag_text_confirmed():
    """BRCA1 stamped AND present in abstract → confirmed tier."""
    papers = [
        _paper(
            "1",
            title="",
            abstract="BRCA1 mutation in hereditary breast cancer",
            stamp={"genes": ["BRCA1"], "diseases": ["breast cancer"], "keywords": []},
        ),
    ]
    cov = _calculate_coverage(
        papers, genes=["BRCA1"], pathways=[], celltypes=[],
        use_retrieval_tags=True,
    )
    assert "BRCA1" in cov["genes_covered"]
    assert cov["genes_matched_by"]["BRCA1"] == "biomcp_tag+text_confirmed"


# ---------------------------------------------------------------------------
# (d) use_retrieval_tags=False ignores stamp — byte-identical to pre-F2 legacy
# ---------------------------------------------------------------------------

def test_calculate_coverage_use_retrieval_tags_false_ignores_stamp():
    """With the kwarg off, the stamp is ignored; legacy regex path runs.

    INSR has no text match and no tag consultation → missing.
    BRCA1 has a text match → legacy label (the matched pattern), NOT a tier.
    """
    papers = [
        _paper(
            "1", title="", abstract="BRCA1 mutation present",
            stamp={"genes": ["INSR", "BRCA1"], "diseases": [], "keywords": []},
        ),
    ]
    cov = _calculate_coverage(
        papers, genes=["INSR", "BRCA1"], pathways=[], celltypes=[],
        use_retrieval_tags=False,
    )
    assert "INSR" not in cov["genes_covered"]  # tag ignored
    assert "BRCA1" in cov["genes_covered"]  # legacy text match
    # Legacy label is the matched pattern literal — NOT a tier string
    label = cov["genes_matched_by"]["BRCA1"]
    assert label not in ("biomcp_tag_only", "biomcp_tag+text_confirmed")


# ---------------------------------------------------------------------------
# (e) Papers without the stamp reproduce pre-F2 coverage (missing-field fallback)
# ---------------------------------------------------------------------------

def test_calculate_coverage_unstamped_papers_fallback_to_legacy():
    """Legacy papers (no `matched_via_query`) behave like pre-F2 under both modes."""
    papers = [_paper("1", abstract="BRCA1 analysis", stamp=None)]
    cov_legacy = _calculate_coverage(
        papers, genes=["BRCA1"], pathways=[], celltypes=[],
        use_retrieval_tags=False,
    )
    cov_tag_on = _calculate_coverage(
        papers, genes=["BRCA1"], pathways=[], celltypes=[],
        use_retrieval_tags=True,
    )
    # Both must mark BRCA1 covered via the regex path with the same label.
    assert "BRCA1" in cov_legacy["genes_covered"]
    assert "BRCA1" in cov_tag_on["genes_covered"]
    assert cov_legacy["genes_matched_by"]["BRCA1"] == cov_tag_on["genes_matched_by"]["BRCA1"]


# ---------------------------------------------------------------------------
# (f) REV-7 additive-only sentinel: _compute_paper_coverage_score picks up the stamp
# ---------------------------------------------------------------------------

def test_compute_paper_coverage_score_stamp_is_additive():
    """Stamped paper adds INSR to `covered`; stripping the stamp yields pre-F2 result."""
    stamped = _paper(
        "1", abstract="",
        stamp={"genes": ["INSR"], "diseases": [], "keywords": []},
    )
    legacy = _paper("1", abstract="")  # no stamp

    _, covered_stamped = _compute_paper_coverage_score(
        stamped, genes=["INSR"], pathways=[], celltypes=[],
    )
    _, covered_legacy = _compute_paper_coverage_score(
        legacy, genes=["INSR"], pathways=[], celltypes=[],
    )

    assert "INSR" in covered_stamped
    assert "INSR" not in covered_legacy  # pre-F2 byte-identical


# ---------------------------------------------------------------------------
# (g) Pathway two-tier resolution via canonical keyword match
# ---------------------------------------------------------------------------

def test_calculate_coverage_pathway_canonical_tag_match():
    """Stamp keyword `erk signaling` tags a `MAPK` pathway via canonical match."""
    papers = [
        _paper(
            "1", title="", abstract="",
            stamp={"genes": [], "diseases": [], "keywords": ["erk signaling"]},
        ),
    ]
    cov = _calculate_coverage(
        papers, genes=[], pathways=["MAPK"], celltypes=[],
        use_retrieval_tags=True,
    )
    assert "MAPK" in cov["pathways_covered"]
    assert cov["pathways_matched_by"]["MAPK"] == "biomcp_tag_only"


# ---------------------------------------------------------------------------
# Extra: pathway text-confirmed tier
# ---------------------------------------------------------------------------

def test_calculate_coverage_pathway_text_confirmed_tier():
    """Stamp keyword + text body both match → confirmed pathway tier."""
    papers = [
        _paper(
            "1", title="", abstract="erk signaling drives proliferation",
            stamp={"genes": [], "diseases": [], "keywords": ["erk signaling"]},
        ),
    ]
    cov = _calculate_coverage(
        papers, genes=[], pathways=["MAPK"], celltypes=[],
        use_retrieval_tags=True,
    )
    assert "MAPK" in cov["pathways_covered"]
    assert cov["pathways_matched_by"]["MAPK"] == "biomcp_tag+text_confirmed"


def test_calculate_coverage_pathway_short_pattern_no_over_match():
    """REV-A NIT-A regression: 1-2 char pattern fragments cannot cause tag hits.

    Guards against over-match where a short pattern like "er" (e.g., from a
    hypothetical 2-char pathway pattern) would substring-match unrelated stamp
    keywords like "her2 signaling". The minimum-length guard at
    _calculate_coverage and _compute_paper_coverage_score blocks this.
    """
    # Use a hypothetical pathway whose generated patterns include "er" (2-char)
    # paired with a stamp keyword "her2 signaling" that contains "er".
    # The genuine pattern must not canonical-hit — it should fall through to
    # legacy regex and only match if "er" appears as a standalone substring
    # in the text (here we leave the abstract empty to force the fallback).
    papers = [
        _paper(
            "1", title="", abstract="",
            stamp={"genes": [], "diseases": [], "keywords": ["her2 signaling"]},
        ),
    ]
    # Use a pathway whose _generate_pathway_patterns emits some short entries.
    # "ER" (estrogen receptor shorthand) is not in PATHWAY_KEYWORDS so it falls
    # back to just ["er"] (2 chars). With the guard, "er" is skipped in the
    # canonical match loop, so the pathway remains uncovered.
    cov = _calculate_coverage(
        papers, genes=[], pathways=["ER"], celltypes=[],
        use_retrieval_tags=True,
    )
    # No over-match: ER should NOT be covered via stamp
    assert "ER" not in cov["pathways_covered"]


def test_compute_paper_coverage_score_pathway_short_pattern_no_over_match():
    """Symmetry of NIT-A guard in _compute_paper_coverage_score."""
    stamped = _paper(
        "1", abstract="",
        stamp={"genes": [], "diseases": [], "keywords": ["her2 signaling"]},
    )
    _, covered = _compute_paper_coverage_score(
        stamped, genes=[], pathways=["ER"], celltypes=[],
    )
    assert "ER" not in covered


def test_compute_paper_coverage_score_pathway_three_char_still_matches():
    """3-char pathway names like WNT/ERK/JAK still participate in stamp matching."""
    stamped = _paper(
        "1", abstract="",
        stamp={"genes": [], "diseases": [], "keywords": ["erk signaling"]},
    )
    _, covered = _compute_paper_coverage_score(
        stamped, genes=[], pathways=["MAPK"], celltypes=[],
    )
    # MAPK's pattern set includes "erk signaling" (3+ chars each) — match holds.
    assert "MAPK" in covered
