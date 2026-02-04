"""Tests for Hybrid L-R Prioritizer module.

These tests verify the hybrid scoring logic combining Moran's R and GenePT scores.
"""

import json
import pickle
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd
import pytest


class TestHybridLRPrioritizer:
    """Tests for HybridLRPrioritizer class."""

    @pytest.fixture
    def mock_embeddings(self):
        """Create mock embeddings for testing."""
        return {
            "MDK": np.array([0.8, 0.6, 0.0, 0.0]),
            "SDC1": np.array([0.7, 0.7, 0.1, 0.0]),
            "ECM1": np.array([0.5, 0.5, 0.5, 0.0]),
            "ITGB4": np.array([0.4, 0.5, 0.6, 0.0]),
            "CALR": np.array([0.3, 0.3, 0.3, 0.7]),
            "ITGA3": np.array([0.2, 0.3, 0.4, 0.6]),
            "COL1A1": np.array([0.1, 0.1, 0.1, 0.1]),
            "DDR1": np.array([0.9, 0.1, 0.1, 0.1]),
        }

    @pytest.fixture
    def temp_embeddings_file(self, mock_embeddings):
        """Create a temporary embeddings file."""
        with tempfile.NamedTemporaryFile(suffix=".pickle", delete=False) as f:
            pickle.dump(mock_embeddings, f)
            return Path(f.name)

    @pytest.fixture
    def sample_liana_df(self):
        """Create sample LIANA results DataFrame."""
        return pd.DataFrame({
            "ligand": ["MDK", "ECM1", "CALR", "COL1A1"],
            "receptor": ["SDC1", "ITGB4", "ITGA3", "DDR1"],
            "interaction": ["MDK^SDC1", "ECM1^ITGB4", "CALR^ITGA3", "COL1A1^DDR1"],
            "morans_r": [0.170, 0.162, 0.161, 0.150],
            "source": ["Cancer", "Cancer", "Fibroblast", "Fibroblast"],
            "target": ["Stroma", "Stroma", "Cancer", "Cancer"],
        })

    @pytest.fixture
    def prioritizer(self, temp_embeddings_file):
        """Create a prioritizer with mock embeddings."""
        from src.agents.deep_interpreter.tools.genept_scorer import GenePTScorer
        from src.agents.deep_interpreter.tools.lr_prioritizer import HybridLRPrioritizer

        # Reset singleton state
        GenePTScorer._instance = None
        GenePTScorer._initialized = False

        scorer = GenePTScorer(embeddings_path=temp_embeddings_file)
        prioritizer = HybridLRPrioritizer(
            spatial_weight=0.6,
            genept_weight=0.4,
            genept_scorer=scorer,
        )

        yield prioritizer

        # Cleanup
        GenePTScorer._instance = None
        GenePTScorer._initialized = False
        temp_embeddings_file.unlink(missing_ok=True)

    def test_default_weights(self):
        """Test default weight values."""
        from src.agents.deep_interpreter.tools.lr_prioritizer import (
            DEFAULT_SPATIAL_WEIGHT,
            DEFAULT_GENEPT_WEIGHT,
        )

        assert DEFAULT_SPATIAL_WEIGHT == 0.6
        assert DEFAULT_GENEPT_WEIGHT == 0.4
        assert DEFAULT_SPATIAL_WEIGHT + DEFAULT_GENEPT_WEIGHT == 1.0

    def test_invalid_weights_raises_error(self):
        """Test that invalid weights raise ValueError."""
        from src.agents.deep_interpreter.tools.lr_prioritizer import HybridLRPrioritizer

        with pytest.raises(ValueError) as exc_info:
            HybridLRPrioritizer(spatial_weight=0.5, genept_weight=0.3)

        assert "sum to 1.0" in str(exc_info.value)

    def test_prioritize_returns_correct_columns(self, prioritizer, sample_liana_df):
        """Test that prioritize adds expected columns."""
        result = prioritizer.prioritize(sample_liana_df, top_k=3)

        expected_columns = ["genept_score", "morans_r_norm", "genept_score_norm", "hybrid_score", "rank"]
        for col in expected_columns:
            assert col in result.columns, f"Missing column: {col}"

    def test_prioritize_returns_top_k(self, prioritizer, sample_liana_df):
        """Test that prioritize returns correct number of rows."""
        result = prioritizer.prioritize(sample_liana_df, top_k=2)
        assert len(result) == 2

        result = prioritizer.prioritize(sample_liana_df, top_k=3)
        assert len(result) == 3

    def test_prioritize_ranking_order(self, prioritizer, sample_liana_df):
        """Test that results are ranked in descending order by hybrid score."""
        result = prioritizer.prioritize(sample_liana_df, top_k=4)

        # Check that hybrid scores are descending
        hybrid_scores = result["hybrid_score"].tolist()
        assert hybrid_scores == sorted(hybrid_scores, reverse=True)

        # Check that rank column is correct
        assert result["rank"].tolist() == [1, 2, 3, 4]

    def test_prioritize_hybrid_score_calculation(self, prioritizer, sample_liana_df):
        """Test that hybrid score is correctly calculated."""
        result = prioritizer.prioritize(sample_liana_df, top_k=4)

        for _, row in result.iterrows():
            expected_hybrid = (
                0.6 * row["morans_r_norm"] + 0.4 * row["genept_score_norm"]
            )
            np.testing.assert_almost_equal(row["hybrid_score"], expected_hybrid, decimal=5)

    def test_prioritize_normalized_scores_in_range(self, prioritizer, sample_liana_df):
        """Test that normalized scores are in [0, 1] range."""
        result = prioritizer.prioritize(sample_liana_df, top_k=4)

        assert all(0 <= x <= 1 for x in result["morans_r_norm"])
        assert all(0 <= x <= 1 for x in result["genept_score_norm"])
        assert all(0 <= x <= 1 for x in result["hybrid_score"])

    def test_prioritize_min_morans_threshold(self, prioritizer, sample_liana_df):
        """Test minimum Moran's R threshold filtering."""
        result = prioritizer.prioritize(sample_liana_df, top_k=10, min_morans_r=0.16)

        # Should filter out COL1A1^DDR1 (0.150) and CALR^ITGA3 (0.161 >= 0.16 passes)
        assert len(result) == 3

    def test_prioritize_empty_dataframe(self, prioritizer):
        """Test handling of empty DataFrame."""
        empty_df = pd.DataFrame(columns=["ligand", "receptor", "morans_r"])
        result = prioritizer.prioritize(empty_df, top_k=3)
        assert len(result) == 0

    def test_get_selection_rationale(self, prioritizer, sample_liana_df):
        """Test rationale generation."""
        top_pairs = prioritizer.prioritize(sample_liana_df, top_k=3)
        rationale = prioritizer.get_selection_rationale(top_pairs)

        assert "L-R Pair Selection Rationale" in rationale
        assert "60%" in rationale  # spatial weight
        assert "40%" in rationale  # genept weight
        assert "Moran's R" in rationale
        assert "GenePT" in rationale

    def test_compare_with_baseline(self, prioritizer, sample_liana_df):
        """Test baseline comparison."""
        comparison = prioritizer.compare_with_baseline(sample_liana_df, top_k=3)

        assert "hybrid_selection" in comparison
        assert "baseline_selection" in comparison
        assert "overlap" in comparison
        assert "jaccard_similarity" in comparison

        # Jaccard similarity should be between 0 and 1
        assert 0 <= comparison["jaccard_similarity"] <= 1

    def test_interaction_column_parsing(self, prioritizer):
        """Test parsing of interaction column format."""
        df = pd.DataFrame({
            "interaction": ["MDK^SDC1", "ECM1^ITGB4"],
            "morans_r": [0.17, 0.16],
        })

        result = prioritizer.prioritize(df, top_k=2)
        assert len(result) == 2

    def test_ligand_complex_columns(self, prioritizer):
        """Test parsing of ligand_complex/receptor_complex columns."""
        df = pd.DataFrame({
            "ligand_complex": ["MDK", "ECM1"],
            "receptor_complex": ["SDC1", "ITGB4"],
            "morans_r": [0.17, 0.16],
        })

        result = prioritizer.prioritize(df, top_k=2)
        assert len(result) == 2

    def test_different_morans_column_names(self, prioritizer):
        """Test detection of different Moran's R column names."""
        # Test with 'Morans_R'
        df1 = pd.DataFrame({
            "ligand": ["MDK"],
            "receptor": ["SDC1"],
            "Morans_R": [0.17],
        })
        result1 = prioritizer.prioritize(df1, top_k=1)
        assert len(result1) == 1

        # Test with 'global_r'
        df2 = pd.DataFrame({
            "ligand": ["MDK"],
            "receptor": ["SDC1"],
            "global_r": [0.17],
        })
        result2 = prioritizer.prioritize(df2, top_k=1)
        assert len(result2) == 1


class TestPrioritizeTool:
    """Tests for the LangChain tool wrapper."""

    @pytest.fixture
    def mock_embeddings(self):
        """Create mock embeddings."""
        return {
            "MDK": np.array([0.8, 0.6, 0.0, 0.0]),
            "SDC1": np.array([0.7, 0.7, 0.1, 0.0]),
        }

    @pytest.fixture
    def temp_data_dir(self, mock_embeddings):
        """Create temp directory with test data."""
        import tempfile
        import shutil

        # Create temp directories
        temp_dir = Path(tempfile.mkdtemp())
        embeddings_dir = temp_dir / "embeddings"
        embeddings_dir.mkdir()

        # Save mock embeddings
        embeddings_path = embeddings_dir / "embeddings.pickle"
        with open(embeddings_path, "wb") as f:
            pickle.dump(mock_embeddings, f)

        # Create LIANA results
        liana_df = pd.DataFrame({
            "ligand": ["MDK"],
            "receptor": ["SDC1"],
            "interaction": ["MDK^SDC1"],
            "morans_r": [0.17],
        })
        liana_df.to_csv(temp_dir / "interest_sig_liana.csv", index=False)

        yield temp_dir, embeddings_path

        # Cleanup
        shutil.rmtree(temp_dir)

    def test_tool_returns_json(self, temp_data_dir):
        """Test that tool returns valid JSON."""
        from src.agents.deep_interpreter.tools.genept_scorer import GenePTScorer
        from src.agents.deep_interpreter.tools.lr_prioritizer import prioritize_top_lr_pairs

        temp_dir, embeddings_path = temp_data_dir

        # Reset and configure scorer
        GenePTScorer._instance = None
        GenePTScorer._initialized = False
        GenePTScorer(embeddings_path=embeddings_path)

        result = prioritize_top_lr_pairs.invoke({
            "data_dir": str(temp_dir),
            "top_k": 1,
        })

        # Should be valid JSON
        parsed = json.loads(result)
        assert "selected_pairs" in parsed or "error" in parsed

        # Cleanup
        GenePTScorer._instance = None
        GenePTScorer._initialized = False

    def test_tool_missing_file_error(self):
        """Test tool handles missing file gracefully."""
        from src.agents.deep_interpreter.tools.lr_prioritizer import prioritize_top_lr_pairs

        result = prioritize_top_lr_pairs.invoke({
            "data_dir": "/nonexistent/path",
            "top_k": 3,
        })

        parsed = json.loads(result)
        assert "error" in parsed


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    def test_create_lr_prioritizer(self):
        """Test factory function."""
        from src.agents.deep_interpreter.tools.lr_prioritizer import create_lr_prioritizer

        prioritizer = create_lr_prioritizer(spatial_weight=0.7, genept_weight=0.3)

        assert prioritizer.spatial_weight == 0.7
        assert prioritizer.genept_weight == 0.3

    def test_prioritize_lr_pairs_function(self, mock_embeddings, temp_embeddings_file):
        """Test convenience function."""
        from src.agents.deep_interpreter.tools.genept_scorer import GenePTScorer
        from src.agents.deep_interpreter.tools.lr_prioritizer import prioritize_lr_pairs

        # Reset and configure scorer
        GenePTScorer._instance = None
        GenePTScorer._initialized = False
        GenePTScorer(embeddings_path=temp_embeddings_file)

        df = pd.DataFrame({
            "ligand": ["MDK"],
            "receptor": ["SDC1"],
            "morans_r": [0.17],
        })

        result = prioritize_lr_pairs(df, top_k=1)
        assert len(result) == 1
        assert "hybrid_score" in result.columns

        # Cleanup
        GenePTScorer._instance = None
        GenePTScorer._initialized = False

    @pytest.fixture
    def mock_embeddings(self):
        return {
            "MDK": np.array([0.8, 0.6, 0.0, 0.0]),
            "SDC1": np.array([0.7, 0.7, 0.1, 0.0]),
        }

    @pytest.fixture
    def temp_embeddings_file(self, mock_embeddings):
        with tempfile.NamedTemporaryFile(suffix=".pickle", delete=False) as f:
            pickle.dump(mock_embeddings, f)
            return Path(f.name)
