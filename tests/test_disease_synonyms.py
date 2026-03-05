"""Tests for lightweight disease post-filter in literature.py.

Tests the hybrid approach: simple rule-based pre-filter + LLM relevance filter.
"""

import json
import pytest

from src.agents.deep_interpreter.tools.literature import (
    _normalize_for_filter,
    _paper_matches_disease_context_simple,
    _llm_disease_relevance_filter,
    _ORGAN_TO_MEDICAL,
)


# =============================================================================
# _normalize_for_filter
# =============================================================================
class TestNormalizeForFilter:
    def test_apostrophe_collapse(self):
        assert _normalize_for_filter("Alzheimer's disease") == "alzheimer s disease"

    def test_multiple_spaces(self):
        assert _normalize_for_filter("breast   cancer") == "breast cancer"

    def test_special_chars(self):
        assert _normalize_for_filter("non-small cell") == "non small cell"

    def test_empty(self):
        assert _normalize_for_filter("") == ""

    def test_none(self):
        assert _normalize_for_filter(None) == ""


# =============================================================================
# _paper_matches_disease_context_simple — canonical match tests
# =============================================================================
class TestSimpleFilterCanonicalMatch:
    def test_exact_match(self):
        paper = {"title": "Breast cancer microenvironment", "abstract": "tumor study"}
        assert _paper_matches_disease_context_simple(paper, ["breast cancer"]) is True

    def test_canonical_in_abstract(self):
        paper = {"title": "Microenvironment study", "abstract": "in breast cancer models"}
        assert _paper_matches_disease_context_simple(paper, ["breast cancer"]) is True

    def test_abbreviation_match_aml(self):
        paper = {"title": "AML treatment outcomes", "abstract": "leukemia study"}
        assert _paper_matches_disease_context_simple(paper, ["AML"]) is True

    def test_abbreviation_word_boundary(self):
        """Short abbreviation should use word-boundary matching."""
        paper = {"title": "Amlodipine pharmacokinetics", "abstract": "blood pressure"}
        # "AML" should NOT match "Amlodipine" (no word boundary)
        assert _paper_matches_disease_context_simple(paper, ["AML"]) is not True

    def test_alzheimers_uncertain(self):
        """Alzheimer's → 'alzheimer s disease' won't match 'alzheimers' → uncertain."""
        paper = {"title": "Alzheimers disease progression", "abstract": "neurodegeneration"}
        # Canonical is "alzheimer s disease", text has "alzheimers disease" — no exact match
        # Should return None (uncertain → LLM decides)
        result = _paper_matches_disease_context_simple(paper, ["Alzheimer's disease"])
        assert result is None

    def test_empty_paper_uncertain(self):
        """Empty paper → None (uncertain, let LLM decide)."""
        paper = {"title": "", "abstract": ""}
        assert _paper_matches_disease_context_simple(paper, ["breast cancer"]) is None

    def test_no_text_paper_uncertain(self):
        """Paper with only PMID → None (uncertain)."""
        paper = {"pmid": "12345", "title": "", "abstract": ""}
        assert _paper_matches_disease_context_simple(paper, ["breast cancer"]) is None


# =============================================================================
# _paper_matches_disease_context_simple — organ mismatch rejection
# =============================================================================
class TestSimpleFilterOrganMismatch:
    def test_different_organ_cancer_rejected(self):
        """Searching 'breast cancer' but paper is about 'prostate cancer' → False."""
        paper = {
            "title": "Prostate cancer progression",
            "abstract": "Prostate cancer metastasis study",
        }
        assert _paper_matches_disease_context_simple(paper, ["breast cancer"]) is False

    def test_different_organ_carcinoma_rejected(self):
        """Searching 'liver cancer' but paper is about 'lung carcinoma' → False."""
        paper = {
            "title": "Lung carcinoma staging",
            "abstract": "Non-small cell lung carcinoma treatment",
        }
        assert _paper_matches_disease_context_simple(paper, ["liver cancer"]) is False

    def test_same_organ_kept(self):
        """Paper about same organ cancer should match."""
        paper = {
            "title": "Breast carcinoma progression",
            "abstract": "mammary gland tumors",
        }
        # "breast cancer" canonical won't match "breast carcinoma" directly
        # but breast (disease organ) IS in the text → not organ-mismatched → uncertain
        result = _paper_matches_disease_context_simple(paper, ["breast cancer"])
        assert result is not False  # Should be True or None, not rejected

    def test_medical_organ_alias_kept(self):
        """Paper using medical term (hepatic) for organ (liver) should not be rejected."""
        paper = {
            "title": "Hepatic carcinoma treatment",
            "abstract": "Hepatocellular cancer therapy",
        }
        result = _paper_matches_disease_context_simple(paper, ["liver cancer"])
        assert result is not False  # hepatic is an alias of liver

    def test_no_organ_disease_uncertain(self):
        """Non-organ disease (e.g., AML) → no organ mismatch check → None."""
        paper = {
            "title": "Novel therapy for colorectal cancer",
            "abstract": "Colon tumor treatment",
        }
        result = _paper_matches_disease_context_simple(paper, ["AML"])
        # AML has no organ in _ORGAN_TO_MEDICAL → can't do organ mismatch
        assert result is None

    def test_generic_paper_uncertain(self):
        """Paper without any organ-cancer context → uncertain."""
        paper = {
            "title": "EMT signaling in tumor progression",
            "abstract": "Epithelial-mesenchymal transition study",
        }
        result = _paper_matches_disease_context_simple(paper, ["breast cancer"])
        assert result is None  # No organ-cancer mismatch detected → uncertain


# =============================================================================
# _paper_matches_disease_context_simple — edge cases
# =============================================================================
class TestSimpleFilterEdgeCases:
    def test_multiple_diseases_any_match(self):
        """Should return True if ANY disease matches."""
        paper = {"title": "AML blast crisis", "abstract": "leukemia"}
        assert _paper_matches_disease_context_simple(paper, ["breast cancer", "AML"]) is True

    def test_generic_disease_uncertain(self):
        """Generic disease name like 'cancer' → uncertain (no organ to check)."""
        paper = {"title": "Novel oncology approaches", "abstract": "tumor biology"}
        result = _paper_matches_disease_context_simple(paper, ["cancer"])
        # "cancer" is in _ORGAN_TO_MEDICAL keys? No. But canonical "cancer" could be in text.
        assert result is None or result is True

    def test_long_disease_name_substring_match(self):
        """Long disease name should use substring matching."""
        paper = {
            "title": "Hepatocellular carcinoma staging",
            "abstract": "HCC treatment outcomes",
        }
        assert _paper_matches_disease_context_simple(
            paper, ["hepatocellular carcinoma"]
        ) is True


# =============================================================================
# _llm_disease_relevance_filter — mock tests
# =============================================================================
class _MockResponse:
    def __init__(self, content: str):
        self.content = content


class _MockLLM:
    def __init__(self, content: str):
        self._content = content

    async def ainvoke(self, _messages):
        return _MockResponse(self._content)


class TestLLMDiseaseRelevanceFilter:
    @pytest.mark.asyncio
    async def test_empty_input(self):
        """No uncertain papers → empty result."""
        result, stats = await _llm_disease_relevance_filter([], ["breast cancer"])
        assert result == []
        assert stats["applied_count"] == 0

    @pytest.mark.asyncio
    async def test_filters_irrelevant(self, monkeypatch):
        """LLM marks paper as irrelevant → dropped."""
        papers = [
            {"pmid": "111", "title": "Breast cancer study", "abstract": "..."},
            {"pmid": "222", "title": "Unrelated prostate paper", "abstract": "..."},
        ]

        monkeypatch.setattr(
            "src.agents.deep_interpreter.tools.literature.create_llm",
            lambda: _MockLLM(
                json.dumps([
                    {"pmid": "111", "relevant": True},
                    {"pmid": "222", "relevant": False},
                ])
            ),
        )

        result, stats = await _llm_disease_relevance_filter(papers, ["breast cancer"])
        pmids = {str(p["pmid"]) for p in result}
        assert pmids == {"111"}
        assert stats["dropped_count"] == 1
        assert stats["applied_count"] == 2

    @pytest.mark.asyncio
    async def test_keeps_all_on_error(self, monkeypatch):
        """LLM error → keep all uncertain papers."""

        class _FailLLM:
            async def ainvoke(self, _messages):
                raise RuntimeError("LLM unavailable")

        monkeypatch.setattr(
            "src.agents.deep_interpreter.tools.literature.create_llm",
            lambda: _FailLLM(),
        )

        papers = [
            {"pmid": "111", "title": "Paper 1", "abstract": "..."},
            {"pmid": "222", "title": "Paper 2", "abstract": "..."},
        ]
        result, stats = await _llm_disease_relevance_filter(papers, ["breast cancer"])
        assert len(result) == 2  # All kept on error
        assert stats["applied_count"] == 0

    @pytest.mark.asyncio
    async def test_keeps_all_on_parse_failure(self, monkeypatch):
        """LLM returns invalid JSON → keep all uncertain papers."""
        monkeypatch.setattr(
            "src.agents.deep_interpreter.tools.literature.create_llm",
            lambda: _MockLLM("not valid json"),
        )

        papers = [{"pmid": "111", "title": "Paper", "abstract": "..."}]
        result, stats = await _llm_disease_relevance_filter(papers, ["breast cancer"])
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_conservative_default(self, monkeypatch):
        """Paper missing from LLM response → kept by default (conservative)."""
        monkeypatch.setattr(
            "src.agents.deep_interpreter.tools.literature.create_llm",
            lambda: _MockLLM(
                json.dumps([{"pmid": "111", "relevant": False}])
            ),
        )

        papers = [
            {"pmid": "111", "title": "Dropped", "abstract": "..."},
            {"pmid": "222", "title": "Not in response", "abstract": "..."},
        ]
        result, stats = await _llm_disease_relevance_filter(papers, ["breast cancer"])
        pmids = {str(p["pmid"]) for p in result}
        assert "222" in pmids  # Not in LLM response → kept


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
