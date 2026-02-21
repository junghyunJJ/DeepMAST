"""Tests for universal disease synonym matching in literature.py."""

import asyncio
import pytest

from src.agents.deep_interpreter.tools.literature import (
    _normalize_for_filter,
    _generate_disease_match_terms,
    _parse_disease_synonyms,
    _resolve_mondo_id,
    _get_disease_synonyms_async,
    get_disease_match_terms,
    _paper_matches_disease_context,
    _DISEASE_SYNONYM_CACHE,
    _DISEASE_SYNONYM_CACHE_LOCK,
    _resolve_uberon_organ_synonyms,
    _get_organ_synonyms,
    _ORGAN_SYNONYM_CACHE,
    _ORGAN_SYNONYM_CACHE_LOCK,
    _extract_organ_tokens,
    _UBERON_STOPWORDS,
)


# =============================================================================
# Step 0: Regex bug fix
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
# Step 3: _generate_disease_match_terms (rule-based)
# =============================================================================
class TestGenerateDiseaseMatchTerms:
    def test_breast_cancer(self):
        terms = _generate_disease_match_terms("breast cancer")
        assert "breast carcinoma" in terms
        assert "breast neoplasm" in terms
        assert any("mammary" in t for t in terms)

    def test_alzheimers(self):
        terms = _generate_disease_match_terms("Alzheimer's disease")
        assert "alzheimer" in terms
        assert "alzheimers" in terms
        assert "alzheimer disease" in terms
        assert "ad" in terms

    def test_aml_abbreviation(self):
        terms = _generate_disease_match_terms("AML")
        assert "acute myeloid leukemia" in terms
        assert "acute myeloid leukaemia" in terms

    def test_pulmonary_fibrosis(self):
        terms = _generate_disease_match_terms("pulmonary fibrosis")
        assert "pulmonary fibrotic" in terms
        assert any("lung" in t and "fibrosis" in t for t in terms)

    def test_hepatocellular_carcinoma(self):
        terms = _generate_disease_match_terms("hepatocellular carcinoma")
        assert "hcc" in terms
        assert any("cancer" in t for t in terms)
        assert any("liver" in t for t in terms)

    def test_dlbcl(self):
        terms = _generate_disease_match_terms("diffuse large B-cell lymphoma")
        assert "dlbcl" in terms

    def test_unknown_disease(self):
        terms = _generate_disease_match_terms("Xylothrax syndrome")
        assert len(terms) >= 1
        assert "xylothrax syndrome" in terms

    def test_empty(self):
        assert _generate_disease_match_terms("") == []

    def test_leukemia_uk_spelling(self):
        terms = _generate_disease_match_terms("acute myeloid leukemia")
        assert "acute myeloid leukaemia" in terms
        assert "aml" in terms

    def test_parkinson(self):
        terms = _generate_disease_match_terms("Parkinson's disease")
        assert "parkinson" in terms
        assert "pd" in terms

    def test_tumor_tumour(self):
        terms = _generate_disease_match_terms("brain tumor")
        assert any("tumour" in t for t in terms)
        assert any("cancer" in t for t in terms)

    def test_organ_forward_mapping(self):
        """Common organ → medical term."""
        terms = _generate_disease_match_terms("liver cancer")
        assert any("hepatic" in t or "hepatocellular" in t for t in terms)

    def test_organ_reverse_mapping(self):
        """Medical term → common organ (for match generation)."""
        terms = _generate_disease_match_terms("renal cell carcinoma")
        assert any("kidney" in t for t in terms)

    def test_fibrotic_to_fibrosis(self):
        terms = _generate_disease_match_terms("pulmonary fibrotic")
        assert "pulmonary fibrosis" in terms

    def test_inflammatory(self):
        terms = _generate_disease_match_terms("ulcerative colitis")
        assert "uc" in terms

    def test_lupus(self):
        terms = _generate_disease_match_terms("systemic lupus erythematosus")
        assert "sle" in terms

    def test_no_duplicates(self):
        terms = _generate_disease_match_terms("breast cancer")
        assert len(terms) == len(set(terms))


# =============================================================================
# Step 2: BioMCP response parsing
# =============================================================================
class TestParseDiseaseSyms:
    def test_markdown_format(self):
        result = [{"type": "text", "text": (
            "# Disease\nName: Breast carcinoma\n"
            "Synonym: breast cancer, mammary carcinoma, mammary cancer\n"
        )}]
        syns = _parse_disease_synonyms(result)
        assert "breast cancer" in syns
        assert "mammary carcinoma" in syns
        assert "Breast carcinoma" in syns  # from Name field

    def test_json_fallback(self):
        result = [{"type": "text", "text": '{"synonyms": ["term1", "term2"]}'}]
        syns = _parse_disease_synonyms(result)
        assert "term1" in syns
        assert "term2" in syns

    def test_none_input(self):
        assert _parse_disease_synonyms(None) == []

    def test_empty_list(self):
        assert _parse_disease_synonyms([]) == []


# =============================================================================
# Step 4: Call site — _paper_matches_disease_context
# =============================================================================
class TestPaperMatchesDiseaseContext:
    def test_exact_match(self):
        paper = {"title": "Breast cancer microenvironment", "abstract": "..."}
        assert _paper_matches_disease_context(paper, ["breast cancer"]) is True

    def test_synonym_match(self):
        paper = {"title": "Mammary carcinoma study", "abstract": "tumor progression"}
        assert _paper_matches_disease_context(paper, ["breast cancer"]) is True

    def test_no_match(self):
        paper = {"title": "Lung adenocarcinoma", "abstract": "pulmonary disease"}
        assert _paper_matches_disease_context(paper, ["breast cancer"]) is False

    def test_empty_paper(self):
        paper = {"title": "", "abstract": ""}
        assert _paper_matches_disease_context(paper, ["breast cancer"]) is False

    def test_alzheimer_match(self):
        paper = {"title": "Alzheimers disease progression", "abstract": "neurodegeneration"}
        assert _paper_matches_disease_context(paper, ["Alzheimer's disease"]) is True

    def test_abbreviation_match(self):
        paper = {"title": "AML treatment outcomes", "abstract": "acute myeloid leukemia"}
        assert _paper_matches_disease_context(paper, ["AML"]) is True

    def test_safe_mode_blocks_generic_term_false_positive(self):
        """Safe mode should block broad term-only matches (e.g., 'malignant')."""
        paper = {
            "title": "Malignant microenvironment in colorectal cancer",
            "abstract": "Tumor-associated macrophage dynamics in colorectal tumors",
        }
        assert _paper_matches_disease_context(paper, ["breast cancer"]) is False


class TestSafeModeDiseaseTerms:
    def test_no_generic_single_terms_for_breast_cancer(self):
        terms = get_disease_match_terms("breast cancer")
        assert "malignant" not in terms
        assert "disease" not in terms
        assert "neoplasm" not in terms

    def test_keeps_specific_cross_organ_synonym(self):
        terms = get_disease_match_terms("breast cancer")
        assert "mammary carcinoma" in terms


# =============================================================================
# Step 2: Async functions (EBI OLS4 + BioMCP) — integration tests
# =============================================================================
class TestAsyncDiseaseSync:
    """These tests hit real APIs — mark as integration."""

    @pytest.mark.asyncio
    async def test_resolve_mondo_id(self):
        """Test EBI OLS4 lookup (requires network)."""
        mondo_id = await _resolve_mondo_id("breast cancer")
        if mondo_id is not None:  # Network might be unavailable
            assert mondo_id.startswith("MONDO:")
            print(f"  Resolved 'breast cancer' → {mondo_id}")
        else:
            pytest.skip("EBI OLS4 unavailable")

    @pytest.mark.asyncio
    async def test_get_disease_synonyms_async_enriched(self):
        """Test full hybrid pipeline (requires BioMCP)."""
        # Clear cache first
        with _DISEASE_SYNONYM_CACHE_LOCK:
            _DISEASE_SYNONYM_CACHE.pop("breast cancer", None)

        terms = await _get_disease_synonyms_async("breast cancer")
        assert len(terms) >= 3  # At minimum rule-based terms
        assert "breast carcinoma" in terms
        print(f"  Got {len(terms)} terms for 'breast cancer': {terms[:8]}...")

    def test_sync_wrapper(self):
        """Test get_disease_match_terms sync wrapper."""
        terms = get_disease_match_terms("hepatocellular carcinoma")
        assert "hcc" in terms
        assert any("liver" in t for t in terms)


# =============================================================================
# Cross-product organ alias tests
# =============================================================================
class TestCrossProductOrganAliases:
    def test_cross_product_mammary_carcinoma(self):
        """breast cancer → mammary carcinoma, mammary neoplasm via cross-product."""
        terms = _generate_disease_match_terms("breast cancer")
        assert "mammary carcinoma" in terms
        assert "mammary neoplasm" in terms

    def test_cross_product_hepatic_carcinoma(self):
        """liver cancer → hepatic carcinoma, hepatocellular carcinoma."""
        terms = _generate_disease_match_terms("liver cancer")
        assert "hepatic carcinoma" in terms
        assert "hepatocellular carcinoma" in terms

    def test_cross_product_reverse(self):
        """renal cell carcinoma → kidney cell carcinoma via reverse cross-product."""
        terms = _generate_disease_match_terms("renal cell carcinoma")
        assert "kidney cell carcinoma" in terms


# =============================================================================
# Organ synonym functions
# =============================================================================
class TestOrganSynonyms:
    def test_static_fallback_breast(self):
        """_get_organ_synonyms('breast') includes 'mammary' from static dict."""
        syns = _get_organ_synonyms("breast")
        assert "mammary" in syns

    def test_static_fallback_brain(self):
        """_get_organ_synonyms('brain') includes 'cerebral'."""
        syns = _get_organ_synonyms("brain")
        assert "cerebral" in syns

    def test_unknown_organ(self):
        """_get_organ_synonyms for unknown organ returns []."""
        syns = _get_organ_synonyms("xylophone")
        assert syns == []

    def test_extract_organ_tokens_breast_cancer(self):
        tokens = _extract_organ_tokens("breast cancer")
        assert "breast" in tokens

    def test_extract_organ_tokens_no_match(self):
        tokens = _extract_organ_tokens("alzheimer disease")
        assert tokens == []

    def test_extract_organ_tokens_multiple(self):
        tokens = _extract_organ_tokens("liver and kidney disease")
        assert "liver" in tokens
        assert "kidney" in tokens


# =============================================================================
# UBERON API tests (network-dependent)
# =============================================================================
class TestUberonLookup:
    """These tests hit EBI OLS4 — skip if network unavailable."""

    @pytest.mark.asyncio
    async def test_resolve_uberon_breast(self):
        """UBERON synonyms for 'breast' should contain 'mammary'."""
        syns = await _resolve_uberon_organ_synonyms("breast")
        if not syns:
            pytest.skip("EBI OLS4 UBERON unavailable")
        assert any("mammary" in s for s in syns), f"Expected 'mammary' in {syns}"

    @pytest.mark.asyncio
    async def test_resolve_uberon_liver(self):
        """UBERON synonyms for 'liver' should contain 'hepatic'."""
        syns = await _resolve_uberon_organ_synonyms("liver")
        if not syns:
            pytest.skip("EBI OLS4 UBERON unavailable")
        assert any("hepatic" in s for s in syns), f"Expected 'hepatic' in {syns}"

    @pytest.mark.asyncio
    async def test_uberon_timeout(self):
        """Nonexistent organ returns [] without error."""
        syns = await _resolve_uberon_organ_synonyms("xylophoneorgan")
        assert syns == []


# =============================================================================
# Substring bug regression tests (HIGH-1, HIGH-2, HIGH-3)
# =============================================================================
class TestSubstringBugRegression:
    def test_all_abbreviation_no_false_positive(self):
        """HIGH-1: 'ALL' should NOT match 'overall survival analysis'."""
        paper = {"title": "Overall survival analysis of treatment outcomes",
                 "abstract": "We analyzed all patients in the small cohort"}
        assert _paper_matches_disease_context(paper, ["ALL"]) is False

    def test_extract_organ_tokens_hodgkin(self):
        """HIGH-2: 'hodgkin lymphoma' should NOT extract 'skin'."""
        tokens = _extract_organ_tokens("hodgkin lymphoma")
        assert "skin" not in tokens

    @pytest.mark.asyncio
    async def test_uberon_stopword_filtering(self):
        """HIGH-3: UBERON results should NOT contain generic words."""
        syns = await _resolve_uberon_organ_synonyms("breast")
        stopwords = {"gland", "body", "zone", "region", "tissue", "organ"}
        assert not any(s in stopwords for s in syns), f"Found stopwords in {syns}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
