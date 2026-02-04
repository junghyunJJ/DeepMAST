"""Tests for GenePT scorer module.

These tests verify the GenePT embedding loading and L-R pair scoring functionality.
"""

import pickle
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd
import pytest


class TestGenePTScorerWithMockEmbeddings:
    """Tests using mock embeddings (no real file required)."""

    @pytest.fixture
    def mock_embeddings(self):
        """Create mock embeddings for testing."""
        # Create simple embeddings for a few genes
        return {
            "TP53": np.array([1.0, 0.0, 0.0, 0.0]),
            "MDK": np.array([0.8, 0.6, 0.0, 0.0]),
            "SDC1": np.array([0.7, 0.7, 0.1, 0.0]),
            "BRCA1": np.array([0.0, 1.0, 0.0, 0.0]),
            "EGFR": np.array([0.0, 0.0, 1.0, 0.0]),
            "ERBB2": np.array([0.1, 0.0, 0.9, 0.1]),
        }

    @pytest.fixture
    def temp_embeddings_file(self, mock_embeddings):
        """Create a temporary embeddings file."""
        with tempfile.NamedTemporaryFile(suffix=".pickle", delete=False) as f:
            pickle.dump(mock_embeddings, f)
            return Path(f.name)

    @pytest.fixture
    def scorer(self, temp_embeddings_file):
        """Create a fresh scorer instance for each test."""
        # Reset singleton state for testing
        from src.agents.deep_interpreter.tools.genept_scorer import GenePTScorer
        GenePTScorer._instance = None
        GenePTScorer._initialized = False

        scorer = GenePTScorer(embeddings_path=temp_embeddings_file)
        yield scorer

        # Cleanup
        GenePTScorer._instance = None
        GenePTScorer._initialized = False
        temp_embeddings_file.unlink(missing_ok=True)

    def test_lazy_loading(self, scorer):
        """Test that embeddings are not loaded until first use."""
        assert not scorer.is_loaded
        # Trigger loading
        _ = scorer.available_genes
        assert scorer.is_loaded

    def test_get_embedding(self, scorer):
        """Test getting embedding for a gene."""
        emb = scorer.get_embedding("TP53")
        assert emb is not None
        assert len(emb) == 4
        np.testing.assert_array_almost_equal(emb, [1.0, 0.0, 0.0, 0.0])

    def test_get_embedding_case_insensitive(self, scorer):
        """Test case-insensitive gene lookup."""
        emb_upper = scorer.get_embedding("TP53")
        emb_lower = scorer.get_embedding("tp53")
        emb_mixed = scorer.get_embedding("Tp53")

        assert emb_upper is not None
        np.testing.assert_array_equal(emb_upper, emb_lower)
        np.testing.assert_array_equal(emb_upper, emb_mixed)

    def test_get_embedding_missing_gene(self, scorer):
        """Test that missing genes return None."""
        emb = scorer.get_embedding("NONEXISTENT_GENE")
        assert emb is None

    def test_score_lr_pair(self, scorer):
        """Test scoring an L-R pair."""
        score = scorer.score_lr_pair("MDK", "SDC1")
        assert score is not None
        assert 0 <= score <= 1

    def test_score_lr_pair_identical_genes(self, scorer):
        """Test that identical genes have similarity ~1."""
        score = scorer.score_lr_pair("TP53", "TP53")
        assert score is not None
        assert score > 0.99  # Should be very close to 1

    def test_score_lr_pair_similar_genes(self, scorer):
        """Test that similar genes have high similarity."""
        # EGFR and ERBB2 are similar (both ErbB family)
        score = scorer.score_lr_pair("EGFR", "ERBB2")
        assert score is not None
        assert score > 0.8  # Should be relatively high

    def test_score_lr_pair_missing_gene(self, scorer):
        """Test that missing genes return None."""
        score = scorer.score_lr_pair("MDK", "NONEXISTENT")
        assert score is None

    def test_score_lr_pairs_batch(self, scorer):
        """Test batch scoring of L-R pairs."""
        lr_df = pd.DataFrame({
            "ligand": ["MDK", "EGFR", "TP53"],
            "receptor": ["SDC1", "ERBB2", "BRCA1"],
        })

        result = scorer.score_lr_pairs_batch(lr_df)

        assert "genept_score" in result.columns
        assert len(result) == 3
        assert all(result["genept_score"].notna())

    def test_available_genes(self, scorer):
        """Test getting available genes."""
        genes = scorer.available_genes
        assert "TP53" in genes
        assert "MDK" in genes
        assert len(genes) == 6

    def test_coverage_stats(self, scorer):
        """Test coverage statistics."""
        stats = scorer.get_coverage_stats(["TP53", "MDK", "UNKNOWN1", "UNKNOWN2"])

        assert stats["total"] == 4
        assert stats["found"] == 2
        assert stats["missing"] == 2
        assert stats["coverage"] == 0.5


class TestGenePTScorerSingleton:
    """Tests for singleton behavior."""

    def test_singleton_pattern(self):
        """Test that GenePTScorer is a singleton."""
        from src.agents.deep_interpreter.tools.genept_scorer import GenePTScorer

        # Reset singleton
        GenePTScorer._instance = None
        GenePTScorer._initialized = False

        with patch.object(GenePTScorer, '_load_embeddings'):
            scorer1 = GenePTScorer()
            scorer2 = GenePTScorer()

            assert scorer1 is scorer2

        # Cleanup
        GenePTScorer._instance = None
        GenePTScorer._initialized = False


class TestGenePTScorerFileNotFound:
    """Tests for missing embeddings file."""

    def test_file_not_found_error(self):
        """Test that missing file raises appropriate error."""
        from src.agents.deep_interpreter.tools.genept_scorer import GenePTScorer

        # Reset singleton
        GenePTScorer._instance = None
        GenePTScorer._initialized = False

        scorer = GenePTScorer(embeddings_path="/nonexistent/path/embeddings.pickle")

        with pytest.raises(FileNotFoundError) as exc_info:
            _ = scorer.available_genes

        assert "download_genept_embeddings.py" in str(exc_info.value)

        # Cleanup
        GenePTScorer._instance = None
        GenePTScorer._initialized = False
