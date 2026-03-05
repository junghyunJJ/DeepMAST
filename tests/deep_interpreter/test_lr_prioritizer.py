"""Tests for Hybrid L-R Prioritizer module.

These tests verify the hybrid scoring logic combining Moran's R and GenePT scores.
"""

import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


class TestHybridLRPrioritizer:
    """Tests for HybridLRPrioritizer class."""

    @pytest.fixture
    def sample_liana_df(self):
        """Create sample LIANA results DataFrame with pre-computed genept_score."""
        return pd.DataFrame({
            "ligand": ["MDK", "ECM1", "CALR", "COL1A1"],
            "receptor": ["SDC1", "ITGB4", "ITGA3", "DDR1"],
            "interaction": ["MDK^SDC1", "ECM1^ITGB4", "CALR^ITGA3", "COL1A1^DDR1"],
            "morans_r": [0.170, 0.162, 0.161, 0.150],
            "genept_score": [0.85, 0.72, 0.60, 0.45],
            "source": ["Cancer", "Cancer", "Fibroblast", "Fibroblast"],
            "target": ["Stroma", "Stroma", "Cancer", "Cancer"],
        })

    @pytest.fixture
    def prioritizer(self):
        """Create a prioritizer (reads genept_score from DataFrame column)."""
        from src.agents.deep_interpreter.tools.lr_prioritizer import HybridLRPrioritizer

        return HybridLRPrioritizer(spatial_weight=0.6, genept_weight=0.4)

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
    def temp_data_dir(self):
        """Create temp directory with test data (genept_score + combinedscore pre-computed in CSV)."""
        import shutil

        temp_dir = Path(tempfile.mkdtemp())

        # Create LIANA results with combinedscore column
        liana_df = pd.DataFrame({
            "ligand": ["MDK"],
            "receptor": ["SDC1"],
            "interaction": ["MDK^SDC1"],
            "morans_r": [0.17],
            "genept_score": [0.85],
            "combinedscore": [0.72],
        })
        liana_df.to_csv(temp_dir / "interest_sig_liana.csv", index=False)

        yield temp_dir

        shutil.rmtree(temp_dir)

    def test_tool_returns_json(self, temp_data_dir):
        """Test that tool returns valid JSON."""
        from src.agents.deep_interpreter.tools.lr_prioritizer import prioritize_top_lr_pairs

        result = prioritize_top_lr_pairs.invoke({
            "data_dir": str(temp_data_dir),
            "candidate_count": 1,
        })

        parsed = json.loads(result)
        assert "pairs" in parsed or "error" in parsed

    def test_tool_missing_file_error(self, monkeypatch):
        """Test tool handles missing file gracefully."""
        from src.agents.deep_interpreter.tools.lr_prioritizer import prioritize_top_lr_pairs

        monkeypatch.delenv("DEEP_INTERPRETER_DATA_DIR", raising=False)

        result = prioritize_top_lr_pairs.invoke({
            "data_dir": "/nonexistent/path",
            "candidate_count": 3,
        })

        parsed = json.loads(result)
        assert "error" in parsed

    def test_tool_prefilter_uses_combinedscore(self):
        """Candidate trimming should follow combinedscore rank."""
        from src.agents.deep_interpreter.tools.lr_prioritizer import prioritize_top_lr_pairs

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            pd.DataFrame({
                "ligand": ["L1", "L2", "L3"],
                "receptor": ["R1", "R2", "R3"],
                "interaction": ["L1^R1", "L2^R2", "L3^R3"],
                "morans_r": [1.0, 0.9, 0.0],
                "genept_score": [1.0, 0.9, 0.0],
                "combinedscore": [0.10, 0.20, 0.99],
            }).to_csv(data_dir / "interest_sig_liana.csv", index=False)

            result = prioritize_top_lr_pairs.invoke({
                "data_dir": str(data_dir),
                "candidate_count": 2,
            })
            parsed = json.loads(result)
            interactions = [pair["interaction"] for pair in parsed["pairs"]]
            # combinedscore ranking: L3 (0.99) > L2 (0.20) > L1 (0.10)
            assert interactions == ["L3^R3", "L2^R2"]

    def test_tool_missing_combinedscore_returns_error(self):
        """When combinedscore column is absent, return informative error."""
        from src.agents.deep_interpreter.tools.lr_prioritizer import prioritize_top_lr_pairs

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            pd.DataFrame({
                "ligand": ["L1"],
                "receptor": ["R1"],
                "interaction": ["L1^R1"],
                "morans_r": [0.5],
                "genept_score": [0.8],
            }).to_csv(data_dir / "interest_sig_liana.csv", index=False)

            result = prioritize_top_lr_pairs.invoke({
                "data_dir": str(data_dir),
                "candidate_count": 5,
            })
            parsed = json.loads(result)
            assert "error" in parsed
            assert "combinedscore" in parsed["error"]
            assert "available_columns" in parsed

    def test_tool_scoring_metadata_uses_combinedscore(self):
        """Result should include scoring metadata referencing combinedscore."""
        from src.agents.deep_interpreter.tools.lr_prioritizer import prioritize_top_lr_pairs

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            pd.DataFrame({
                "ligand": ["L1", "L2"],
                "receptor": ["R1", "R2"],
                "interaction": ["L1^R1", "L2^R2"],
                "morans_r": [0.5, 0.3],
                "genept_score": [0.8, 0.6],
                "combinedscore": [0.9, 0.7],
            }).to_csv(data_dir / "interest_sig_liana.csv", index=False)

            result = prioritize_top_lr_pairs.invoke({
                "data_dir": str(data_dir),
                "candidate_count": 5,
            })
            parsed = json.loads(result)
            assert parsed["scoring"]["method"] == "novelty_score"
            assert "hub_penalty" in parsed["scoring"]
            assert "combinedscore_formula" in parsed["scoring"]

    def test_tool_reports_exclusion_mode_and_numeric_level(self):
        """Selection metadata should expose exclusion mode and numeric level."""
        from src.agents.deep_interpreter.tools.lr_prioritizer import prioritize_top_lr_pairs

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            pd.DataFrame({
                "ligand": ["L1", "L2", "L3", "L4", "L5", "L6"],
                "receptor": ["R1", "R2", "R3", "R4", "R5", "R6"],
                "interaction": ["L1^R1", "L2^R2", "L3^R3", "L4^R4", "L5^R5", "L6^R6"],
                "morans_r": [0.9, 0.8, 0.7, 0.6, 0.5, 0.4],
                "genept_score": [0.9, 0.8, 0.7, 0.6, 0.5, 0.4],
                "combinedscore": [0.9, 0.8, 0.7, 0.6, 0.5, 0.4],
            }).to_csv(data_dir / "interest_sig_liana.csv", index=False)

            with open(data_dir / "top_search_genes.json", "w") as f:
                json.dump({
                    "version": 2,
                    "genes": ["L1", "R1"],
                    "scores": [1.0, 1.0],
                    "score_method": "test",
                    "timestamp": "2026-02-21T00:00:00Z",
                }, f)

            result = prioritize_top_lr_pairs.invoke({
                "data_dir": str(data_dir),
                "candidate_count": 5,
            })
            parsed = json.loads(result)
            assert parsed["selection_mode"] == "exclusion"
            assert parsed["exclusion_level"] == 30
            assert parsed["excluded_count"] == 1


class TestTopSearchGenesFormatCompatibility:
    """Tests for top_search_genes.json backward/forward compatibility."""

    def test_load_top_search_genes_supports_legacy_list(self):
        from src.agents.deep_interpreter.tools.lr_prioritizer import _load_top_search_genes

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            with open(data_dir / "top_search_genes.json", "w") as f:
                json.dump(["TP53", "EGFR", "KRAS"], f)

            genes = _load_top_search_genes(data_dir)
            assert genes == ["TP53", "EGFR", "KRAS"]

    def test_load_top_search_genes_supports_v2_object(self):
        from src.agents.deep_interpreter.tools.lr_prioritizer import _load_top_search_genes

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            with open(data_dir / "top_search_genes.json", "w") as f:
                json.dump({
                    "version": 2,
                    "genes": ["TP53", "EGFR", "KRAS"],
                    "scores": [1.0, 0.9, 0.8],
                    "score_method": "test",
                    "timestamp": "2026-02-21T00:00:00Z",
                }, f)

            genes = _load_top_search_genes(data_dir)
            assert genes == ["TP53", "EGFR", "KRAS"]

    def test_load_top_search_genes_rejects_malformed_object(self):
        from src.agents.deep_interpreter.tools.lr_prioritizer import _load_top_search_genes

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            with open(data_dir / "top_search_genes.json", "w") as f:
                json.dump({"version": 2, "scores": [1.0]}, f)

            genes = _load_top_search_genes(data_dir)
            assert genes is None


class TestTopSearchGenesFileWriting:
    """Tests for v2 top_search_genes.json persistence from search context extraction."""

    def test_extract_search_context_writes_v2_top_genes_payload(self):
        from src.agents.deep_interpreter.tools.data_loader import _extract_search_context

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            pd.DataFrame({
                "ligand": ["L1", "L2", "L3"],
                "receptor": ["R1", "R2", "R3"],
                "combinedscore": [0.9, 0.8, 0.7],
            }).to_csv(data_dir / "interest_sig_liana.csv", index=False)

            context = _extract_search_context(data_dir, context_type="lr_interaction")
            assert context["genes"]  # sanity check

            with open(data_dir / "top_search_genes.json") as f:
                payload = json.load(f)

            assert payload["version"] == 2
            assert isinstance(payload["genes"], list)
            assert isinstance(payload["scores"], list)
            assert len(payload["genes"]) == len(payload["scores"])
            assert payload["score_method"]
            assert payload["timestamp"]


class TestLRCandidatesJsonPersistence:
    """Tests for lr_candidates.json auto-save in prioritize_top_lr_pairs."""

    def test_tool_saves_lr_candidates_json(self):
        """Verify lr_candidates.json is written to data_dir after tool call."""
        from src.agents.deep_interpreter.tools.lr_prioritizer import prioritize_top_lr_pairs

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            pd.DataFrame({
                "ligand": ["MDK", "ECM1"],
                "receptor": ["SDC1", "ITGB4"],
                "interaction": ["MDK^SDC1", "ECM1^ITGB4"],
                "morans_r": [0.17, 0.16],
                "genept_score": [0.85, 0.72],
                "combinedscore": [0.75, 0.60],
            }).to_csv(data_dir / "interest_sig_liana.csv", index=False)

            prioritize_top_lr_pairs.invoke({
                "data_dir": str(data_dir),
                "candidate_count": 5,
            })

            candidates_file = data_dir / "lr_candidates.json"
            assert candidates_file.exists(), "lr_candidates.json should be created"

    def test_lr_candidates_json_contains_expected_fields(self):
        """Verify saved file has pairs, selection_mode, exclusion_level."""
        from src.agents.deep_interpreter.tools.lr_prioritizer import prioritize_top_lr_pairs

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            pd.DataFrame({
                "ligand": ["MDK", "ECM1"],
                "receptor": ["SDC1", "ITGB4"],
                "interaction": ["MDK^SDC1", "ECM1^ITGB4"],
                "morans_r": [0.17, 0.16],
                "genept_score": [0.85, 0.72],
                "combinedscore": [0.75, 0.60],
            }).to_csv(data_dir / "interest_sig_liana.csv", index=False)

            prioritize_top_lr_pairs.invoke({
                "data_dir": str(data_dir),
                "candidate_count": 5,
            })

            with open(data_dir / "lr_candidates.json") as f:
                saved = json.load(f)

            assert "pairs" in saved
            assert "selection_mode" in saved
            assert "exclusion_level" in saved
            assert isinstance(saved["pairs"], list)


class TestSaveSelectedLRPairs:
    """Tests for the save_selected_lr_pairs tool."""

    def test_save_selected_lr_pairs_creates_file(self):
        """Verify selected_top3_lr.json is written."""
        from src.agents.deep_interpreter.tools.lr_prioritizer import save_selected_lr_pairs

        with tempfile.TemporaryDirectory() as tmpdir:
            result = save_selected_lr_pairs.invoke({
                "data_dir": tmpdir,
                "selected_pairs": [
                    {"ligand": "MDK", "receptor": "SDC1", "reasoning": "Novel interaction"},
                    {"ligand": "ECM1", "receptor": "ITGB4", "reasoning": "High Moran's R"},
                    {"ligand": "CALR", "receptor": "ITGA3", "reasoning": "Mechanistic fit"},
                ],
            })

            parsed = json.loads(result)
            assert parsed["status"] == "saved"
            assert Path(tmpdir, "selected_top3_lr.json").exists()

    def test_save_selected_lr_pairs_content(self):
        """Verify file content has version, selected_pairs, count, timestamp."""
        from src.agents.deep_interpreter.tools.lr_prioritizer import save_selected_lr_pairs

        with tempfile.TemporaryDirectory() as tmpdir:
            pairs = [
                {"ligand": "MDK", "receptor": "SDC1", "reasoning": "Test"},
            ]
            save_selected_lr_pairs.invoke({
                "data_dir": tmpdir,
                "selected_pairs": pairs,
            })

            with open(Path(tmpdir) / "selected_top3_lr.json") as f:
                saved = json.load(f)

            assert saved["version"] == 1
            assert saved["count"] == 1
            assert "timestamp" in saved
            assert saved["selected_pairs"] == pairs

    def test_save_selected_lr_pairs_invalid_dir(self):
        """Graceful error on bad path."""
        from src.agents.deep_interpreter.tools.lr_prioritizer import save_selected_lr_pairs

        result = save_selected_lr_pairs.invoke({
            "data_dir": "/nonexistent/path/that/does/not/exist",
            "selected_pairs": [{"ligand": "A", "receptor": "B", "reasoning": "X"}],
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

    def test_prioritize_lr_pairs_function(self):
        """Test convenience function (genept_score read from DataFrame column)."""
        from src.agents.deep_interpreter.tools.lr_prioritizer import prioritize_lr_pairs

        df = pd.DataFrame({
            "ligand": ["MDK"],
            "receptor": ["SDC1"],
            "morans_r": [0.17],
            "genept_score": [0.85],
        })

        result = prioritize_lr_pairs(df, top_k=1)
        assert len(result) == 1
        assert "hybrid_score" in result.columns


# ---------------------------------------------------------------------------
# Tests for drug_targets helper functions
# ---------------------------------------------------------------------------

class TestDrugTargetsLoadTopSearchGenes:
    """Tests for drug_targets._load_top_search_genes helper."""

    def test_load_v1_list_format(self):
        from src.agents.deep_interpreter.tools.drug_targets import _load_top_search_genes

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(Path(tmpdir) / "top_search_genes.json", "w") as f:
                json.dump(["TP53", "EGFR", "KRAS"], f)

            genes = _load_top_search_genes(tmpdir)
            assert genes == ["TP53", "EGFR", "KRAS"]

    def test_load_v2_object_format(self):
        from src.agents.deep_interpreter.tools.drug_targets import _load_top_search_genes

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(Path(tmpdir) / "top_search_genes.json", "w") as f:
                json.dump({
                    "version": 2,
                    "genes": ["TP53", "EGFR"],
                    "scores": [1.0, 0.9],
                    "score_method": "hybrid",
                    "timestamp": "2026-02-22T00:00:00Z",
                }, f)

            genes = _load_top_search_genes(tmpdir)
            assert genes == ["TP53", "EGFR"]

    def test_returns_empty_when_file_missing(self):
        from src.agents.deep_interpreter.tools.drug_targets import _load_top_search_genes

        with tempfile.TemporaryDirectory() as tmpdir:
            genes = _load_top_search_genes(tmpdir)
            assert genes == []

    def test_returns_empty_on_malformed_json(self):
        from src.agents.deep_interpreter.tools.drug_targets import _load_top_search_genes

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(Path(tmpdir) / "top_search_genes.json", "w") as f:
                json.dump({"version": 2, "scores": [1.0]}, f)  # missing "genes"

            genes = _load_top_search_genes(tmpdir)
            assert genes == []

    def test_filters_non_string_entries(self):
        from src.agents.deep_interpreter.tools.drug_targets import _load_top_search_genes

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(Path(tmpdir) / "top_search_genes.json", "w") as f:
                json.dump(["TP53", None, "", 123, "EGFR"], f)

            genes = _load_top_search_genes(tmpdir)
            assert genes == ["TP53", "EGFR"]


class TestDrugTargetsLoadSelectedTop3LR:
    """Tests for drug_targets._load_selected_top3_lr helper."""

    def test_load_valid_file(self):
        from src.agents.deep_interpreter.tools.drug_targets import _load_selected_top3_lr

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(Path(tmpdir) / "selected_top3_lr.json", "w") as f:
                json.dump({
                    "version": 1,
                    "selected_pairs": [
                        {"ligand": "MDK", "receptor": "SDC1", "reasoning": "test"},
                        {"ligand": "ECM1", "receptor": "ITGB4", "reasoning": "test"},
                        {"ligand": "CALR", "receptor": "ITGA3", "reasoning": "test"},
                    ],
                    "count": 3,
                    "timestamp": "2026-02-22T00:00:00Z",
                }, f)

            genes = _load_selected_top3_lr(tmpdir)
            assert genes == ["MDK", "SDC1", "ECM1", "ITGB4", "CALR", "ITGA3"]

    def test_deduplicates_genes(self):
        from src.agents.deep_interpreter.tools.drug_targets import _load_selected_top3_lr

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(Path(tmpdir) / "selected_top3_lr.json", "w") as f:
                json.dump({
                    "version": 1,
                    "selected_pairs": [
                        {"ligand": "MDK", "receptor": "SDC1", "reasoning": "a"},
                        {"ligand": "MDK", "receptor": "ITGB4", "reasoning": "b"},
                    ],
                    "count": 2,
                }, f)

            genes = _load_selected_top3_lr(tmpdir)
            assert genes == ["MDK", "SDC1", "ITGB4"]

    def test_returns_empty_when_file_missing(self):
        from src.agents.deep_interpreter.tools.drug_targets import _load_selected_top3_lr

        with tempfile.TemporaryDirectory() as tmpdir:
            genes = _load_selected_top3_lr(tmpdir)
            assert genes == []

    def test_returns_empty_on_empty_pairs(self):
        from src.agents.deep_interpreter.tools.drug_targets import _load_selected_top3_lr

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(Path(tmpdir) / "selected_top3_lr.json", "w") as f:
                json.dump({"version": 1, "selected_pairs": [], "count": 0}, f)

            genes = _load_selected_top3_lr(tmpdir)
            assert genes == []


class TestDrugTargetsLoadLrCandidates:
    """Tests for drug_targets._load_lr_candidates_genes helper."""

    def test_loads_top15_candidate_genes_only(self):
        from src.agents.deep_interpreter.tools.drug_targets import _load_lr_candidates_genes

        with tempfile.TemporaryDirectory() as tmpdir:
            candidate_pairs = []
            for idx in range(1, 18):  # 17 pairs, but helper should keep top 15
                candidate_pairs.append({
                    "rank": idx,
                    "ligand": f"L{idx}",
                    "receptor": f"R{idx}",
                })

            with open(Path(tmpdir) / "lr_candidates.json", "w") as f:
                json.dump({"candidate_pairs": candidate_pairs}, f)

            genes = _load_lr_candidates_genes(tmpdir, top_k_pairs=15)
            assert len(genes) == 30
            assert "L15" in genes and "R15" in genes
            assert "L16" not in genes and "R16" not in genes

    def test_deduplicates_lr_candidate_genes(self):
        from src.agents.deep_interpreter.tools.drug_targets import _load_lr_candidates_genes

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(Path(tmpdir) / "lr_candidates.json", "w") as f:
                json.dump({
                    "candidate_pairs": [
                        {"rank": 1, "ligand": "MDK", "receptor": "SDC1"},
                        {"rank": 2, "ligand": "MDK", "receptor": "ITGB4"},
                    ]
                }, f)

            genes = _load_lr_candidates_genes(tmpdir, top_k_pairs=15)
            assert genes == ["MDK", "SDC1", "ITGB4"]


class TestDrugTargetsGwasScoring:
    """Tests for GWAS proxy scoring helper in drug_targets."""

    def test_compute_gwas_proxy_scores_reported_plus_nearest_weighted(self):
        from src.agents.deep_interpreter.tools.drug_targets import _compute_gwas_proxy_scores

        evidence = [
            {
                "datatypeId": "genetic_association",
                "datasourceId": "gwas_catalog",
                "score": 0.9,
                "targetFromSourceId": "EGFR",
            },
            {
                "datatypeId": "genetic_association",
                "datasourceId": "gwas_catalog",
                "score": 0.3,
                "targetFromSourceId": "LOC1000",
            },
            {
                "datatypeId": "known_drug",
                "datasourceId": "chembl",
                "score": 1.0,
                "targetFromSourceId": "EGFR",
            },
        ]

        gwas = _compute_gwas_proxy_scores(
            evidence=evidence,
            approved_symbol="EGFR",
            ot_genetic_association_score=0.2,
        )

        assert gwas["gwas_mapping_policy"] == "reported_plus_nearest_weighted"
        assert gwas["gwas_weights"] == {"reported_gene": 1.0, "nearest_gene": 0.6}
        assert gwas["gwas_reported_hits_count"] == 1
        assert gwas["gwas_nearest_hits_count"] == 1
        assert gwas["gwas_reported_score"] == pytest.approx(0.9)
        assert gwas["gwas_nearest_score"] == pytest.approx(0.3)
        assert gwas["gwas_combined_score"] == pytest.approx((0.9 + 0.3 * 0.6) / 1.6)
        assert gwas["genetic_consistency_flag"] is True

    def test_merge_gwas_hybrid_scores_with_direct_signal(self):
        from src.agents.deep_interpreter.tools.drug_targets import _merge_gwas_hybrid_scores

        proxy = {
            "gwas_mapping_policy": "reported_plus_nearest_weighted",
            "gwas_weights": {"reported_gene": 1.0, "nearest_gene": 0.6},
            "ot_genetic_association_score": 0.2,
            "gwas_reported_hits_count": 1,
            "gwas_nearest_hits_count": 0,
            "gwas_reported_score": 0.2,
            "gwas_nearest_score": 0.0,
            "gwas_combined_score": 0.125,
            "genetic_consistency_flag": False,
        }
        direct = {
            "reported_signal": 0.8,
            "nearest_signal": 0.1,
            "reported_hits_count": 2,
            "nearest_hits_count": 1,
        }

        merged = _merge_gwas_hybrid_scores(proxy_scores=proxy, direct_scores=direct)

        assert merged["gwas_signal_source"] == "hybrid_open_targets_plus_gwas_database"
        assert merged["gwas_direct_used"] is True
        assert merged["gwas_direct_reported_hits_count"] == 2
        assert merged["gwas_direct_nearest_hits_count"] == 1
        assert merged["gwas_reported_hits_count"] == 3
        assert merged["gwas_nearest_hits_count"] == 1
        assert merged["gwas_reported_score"] == pytest.approx((0.2 + 0.8) / 2.0)
        assert merged["gwas_nearest_score"] == pytest.approx(0.1)
        assert merged["gwas_combined_score"] == pytest.approx(((0.5 * 1.0) + (0.1 * 0.6)) / 1.6)

    def test_merge_gwas_hybrid_scores_proxy_only_fallback(self):
        from src.agents.deep_interpreter.tools.drug_targets import _merge_gwas_hybrid_scores

        proxy = {
            "gwas_mapping_policy": "reported_plus_nearest_weighted",
            "gwas_weights": {"reported_gene": 1.0, "nearest_gene": 0.6},
            "ot_genetic_association_score": 0.9,
            "gwas_reported_hits_count": 1,
            "gwas_nearest_hits_count": 1,
            "gwas_reported_score": 0.7,
            "gwas_nearest_score": 0.2,
            "gwas_combined_score": (0.7 + 0.2 * 0.6) / 1.6,
            "genetic_consistency_flag": False,
        }

        merged = _merge_gwas_hybrid_scores(proxy_scores=proxy, direct_scores={})

        assert merged["gwas_signal_source"] == "opentargets_proxy_only"
        assert merged["gwas_direct_used"] is False
        assert merged["gwas_reported_hits_count"] == 1
        assert merged["gwas_nearest_hits_count"] == 1
        assert merged["gwas_reported_score"] == pytest.approx(0.7)
        assert merged["gwas_nearest_score"] == pytest.approx(0.2)
        assert merged["gwas_combined_score"] == pytest.approx((0.7 + 0.2 * 0.6) / 1.6)

    def test_compute_validated_score_uses_clinicaltrials_and_drugbank(self):
        from src.agents.deep_interpreter.tools.drug_targets import _compute_validated_score

        target = {
            "evidence_types": {"known_drug": 0},
            "safety_liabilities": [],
        }
        with_multi_source = _compute_validated_score(
            target=target,
            gene_drugs=[
                {
                    "phase": 0,
                    "clinical_trials_total_count": 120,
                    "drugbank_match_count": 1,
                }
            ],
            from_lr_candidates=True,
        )
        without_multi_source = _compute_validated_score(
            target=target,
            gene_drugs=[],
            from_lr_candidates=True,
        )

        assert with_multi_source["clinical_trials_signal"] > 0
        assert with_multi_source["drugbank_support"] == 1.0
        assert with_multi_source["validated_score"] > without_multi_source["validated_score"]
        assert with_multi_source["validated_pass"] is True

    def test_compute_exploratory_score_uses_chembl_and_gwas_direct(self):
        from src.agents.deep_interpreter.tools.drug_targets import _compute_exploratory_score

        target_with_direct = {
            "gwas_combined_score": 0.1,
            "ot_genetic_association_score": 0.1,
            "tractability": {},
            "evidence_count": 0,
            "gwas_direct_reported_hits_count": 2,
            "gwas_direct_nearest_hits_count": 1,
        }
        target_without_direct = {
            **target_with_direct,
            "gwas_direct_reported_hits_count": 0,
            "gwas_direct_nearest_hits_count": 0,
        }

        with_signals = _compute_exploratory_score(
            target=target_with_direct,
            from_lr_candidates=True,
            chembl_target_hits_count=3,
            chembl_exact_symbol_match=True,
        )
        without_signals = _compute_exploratory_score(
            target=target_without_direct,
            from_lr_candidates=True,
            chembl_target_hits_count=0,
            chembl_exact_symbol_match=False,
        )

        assert with_signals["chembl_target_support"] > without_signals["chembl_target_support"]
        assert with_signals["gwas_direct_support"] > without_signals["gwas_direct_support"]
        assert with_signals["exploratory_score"] > without_signals["exploratory_score"]

    def test_search_drug_targets_uses_direct_adapter_when_available(self, monkeypatch):
        from src.agents.deep_interpreter.tools import drug_targets

        monkeypatch.setattr(drug_targets, "_resolve_disease_to_efo", lambda disease: "EFO_0000305")
        monkeypatch.setattr(drug_targets, "_resolve_gene_to_ensembl", lambda gene: f"ENSG_{gene}")
        monkeypatch.setattr(
            drug_targets,
            "get_target_info",
            lambda ensembl_id, include_diseases=True: {
                "approvedSymbol": "EGFR",
                "approvedName": "EGFR protein",
                "biotype": "protein_coding",
                "functionDescriptions": ["EGFR function"],
                "tractability": [],
                "safetyLiabilities": [],
                "geneticConstraint": [],
                "associatedDiseases": {
                    "rows": [
                        {
                            "disease": {"id": "EFO_0000305"},
                            "score": 0.4,
                            "datatypeScores": [{"id": "genetic_association", "score": 0.2}],
                        }
                    ]
                },
            },
        )
        monkeypatch.setattr(
            drug_targets,
            "get_target_disease_evidence",
            lambda ensembl_id, efo_id: [
                {
                    "datatypeId": "genetic_association",
                    "datasourceId": "gwas_catalog",
                    "score": 0.2,
                    "targetFromSourceId": "EGFR",
                }
            ],
        )
        monkeypatch.setattr(
            drug_targets,
            "fetch_gwas_direct_gene_scores",
            lambda disease, genes, efo_id: {
                "EGFR": {
                    "reported_signal": 0.8,
                    "nearest_signal": 0.0,
                    "reported_hits_count": 2,
                    "nearest_hits_count": 0,
                }
            },
        )

        result = json.loads(drug_targets.search_drug_targets.invoke({
            "gene_symbols": ["EGFR"],
            "disease": "test cancer",
        }))

        egfr = result["targets"]["EGFR"]
        assert result["gwas_direct_status"] == "ok"
        assert egfr["gwas_signal_source"] == "hybrid_open_targets_plus_gwas_database"
        assert egfr["gwas_direct_used"] is True
        assert egfr["gwas_direct_reported_hits_count"] == 2
        assert egfr["gwas_reported_score"] == pytest.approx((0.2 + 0.8) / 2.0)

    def test_search_drug_targets_fallback_when_direct_adapter_fails(self, monkeypatch):
        from src.agents.deep_interpreter.tools import drug_targets
        from src.agents.deep_interpreter.tools.gwas_adapter import GwasDirectAdapterError

        monkeypatch.setattr(drug_targets, "_resolve_disease_to_efo", lambda disease: "EFO_0000305")
        monkeypatch.setattr(drug_targets, "_resolve_gene_to_ensembl", lambda gene: f"ENSG_{gene}")
        monkeypatch.setattr(
            drug_targets,
            "get_target_info",
            lambda ensembl_id, include_diseases=True: {
                "approvedSymbol": "EGFR",
                "approvedName": "EGFR protein",
                "biotype": "protein_coding",
                "functionDescriptions": ["EGFR function"],
                "tractability": [],
                "safetyLiabilities": [],
                "geneticConstraint": [],
                "associatedDiseases": {
                    "rows": [
                        {
                            "disease": {"id": "EFO_0000305"},
                            "score": 0.4,
                            "datatypeScores": [{"id": "genetic_association", "score": 0.2}],
                        }
                    ]
                },
            },
        )
        monkeypatch.setattr(
            drug_targets,
            "get_target_disease_evidence",
            lambda ensembl_id, efo_id: [
                {
                    "datatypeId": "genetic_association",
                    "datasourceId": "gwas_catalog",
                    "score": 0.2,
                    "targetFromSourceId": "EGFR",
                }
            ],
        )
        monkeypatch.setattr(
            drug_targets,
            "fetch_gwas_direct_gene_scores",
            lambda disease, genes, efo_id: (_ for _ in ()).throw(
                GwasDirectAdapterError("gwascatalog unavailable")
            ),
        )

        result = json.loads(drug_targets.search_drug_targets.invoke({
            "gene_symbols": ["EGFR"],
            "disease": "test cancer",
        }))

        egfr = result["targets"]["EGFR"]
        assert result["gwas_direct_status"] == "degraded"
        assert "unavailable" in result["gwas_direct_error"]
        assert egfr["gwas_signal_source"] == "opentargets_proxy_only"
        assert egfr["gwas_direct_used"] is False


class TestGwasDirectAdapter:
    """Tests for GWAS direct adapter trait resolution and aggregation."""

    def test_normalize_trait_id_accepts_mondo_curie_and_uri(self):
        from src.agents.deep_interpreter.tools.gwas_adapter import _normalize_efo_id

        assert _normalize_efo_id("MONDO:0007254") == "MONDO_0007254"
        assert (
            _normalize_efo_id("http://purl.obolibrary.org/obo/MONDO_0007254")
            == "MONDO_0007254"
        )

    def test_fetch_direct_scores_resolves_trait_from_disease_name(self, monkeypatch):
        from src.agents.deep_interpreter.tools import gwas_adapter

        calls = {"n": 0}

        def fake_fetch_json(url, timeout=8.0):
            calls["n"] += 1
            if "findByEfoTrait" in url:
                return {
                    "_embedded": {
                        "efoTraits": [
                            {"trait": "breast cancer", "shortForm": "MONDO_0007254"}
                        ]
                    }
                }
            return {
                "_embedded": {
                    "associations": [
                        {
                            "score": 0.8,
                            "authorReportedGenes": "EGFR",
                            "mappedGenes": "LOC1000",
                        }
                    ]
                }
            }

        monkeypatch.setattr(gwas_adapter, "_fetch_json", fake_fetch_json)

        out = gwas_adapter.fetch_gwas_direct_gene_scores(
            disease="breast cancer",
            genes=["EGFR"],
            efo_id="",
            max_pages=1,
        )
        egfr = out["EGFR"]
        assert calls["n"] >= 2
        assert egfr["reported_hits_count"] == 1
        assert egfr["nearest_hits_count"] == 0
        assert egfr["reported_signal"] == pytest.approx(0.8)

    def test_fetch_direct_scores_accepts_mondo_trait_id(self, monkeypatch):
        from src.agents.deep_interpreter.tools import gwas_adapter

        called_urls = []

        def fake_fetch_json(url, timeout=8.0):
            called_urls.append(url)
            return {"_embedded": {"associations": []}}

        monkeypatch.setattr(gwas_adapter, "_fetch_json", fake_fetch_json)

        gwas_adapter.fetch_gwas_direct_gene_scores(
            disease="breast cancer",
            genes=["EGFR"],
            efo_id="MONDO_0007254",
            max_pages=1,
        )
        assert any("MONDO_0007254/associations" in u for u in called_urls)


class TestAssessTherapeuticPotentialGeneSelection:
    """Tests for assess_therapeutic_potential gene selection logic.

    These tests mock the OpenTargets calls to focus on gene selection behavior.
    """

    @pytest.fixture(autouse=True)
    def _mock_opentargets(self, monkeypatch):
        """Mock search_drug_targets and search_known_drugs to avoid API calls.

        Patches the tool .invoke via object.__setattr__ to bypass Pydantic field validation.
        """
        from src.agents.deep_interpreter.tools import drug_targets

        def fake_search_drug_targets(input_dict):
            genes = input_dict["gene_symbols"]
            targets = {}
            for g in genes:
                targets[g] = {
                    "ensembl_id": f"ENSG_{g}",
                    "approved_symbol": g,
                    "approved_name": f"{g} protein",
                    "tractability": {"SM": ["Clinical_Precedence"]},
                    "safety_liabilities": [],
                    "disease_association_score": 0.0,
                    "evidence_count": 0,
                    "evidence_types": {},
                    "ot_genetic_association_score": 0.2,
                    "gwas_mapping_policy": "reported_plus_nearest_weighted",
                    "gwas_weights": {"reported_gene": 1.0, "nearest_gene": 0.6},
                    "gwas_reported_hits_count": 1,
                    "gwas_nearest_hits_count": 0,
                    "gwas_reported_score": 0.2,
                    "gwas_nearest_score": 0.0,
                    "gwas_combined_score": 0.2,
                    "genetic_consistency_flag": False,
                }
            return json.dumps({
                "disease": input_dict["disease"],
                "efo_id": "EFO_0000305",
                "genes_found": len(genes),
                "genes_failed": [],
                "targets": targets,
            })

        def fake_search_known_drugs(input_dict):
            return json.dumps({
                "disease": input_dict["disease"],
                "efo_id": "EFO_0000305",
                "drugs_returned": 0,
                "drugs": [],
            })

        def fake_collect_multi_source_evidence(disease, gene_symbols, known_drugs):
            return {
                "chembl_status": "mocked",
                "clinicaltrials_status": "mocked",
                "drugbank_status": "mocked",
                "chembl_by_gene": {
                    g: {
                        "chembl_target_hits_count": 0,
                        "chembl_target_ids": [],
                        "chembl_exact_symbol_match": False,
                    }
                    for g in gene_symbols
                },
                "clinicaltrials_by_drug": {},
                "drugbank_by_drug": {},
                "errors": {},
            }

        # Save originals for teardown
        orig_sdt = drug_targets.search_drug_targets.invoke
        orig_skd = drug_targets.search_known_drugs.invoke
        orig_mse = drug_targets.collect_multi_source_evidence
        object.__setattr__(drug_targets.search_drug_targets, "invoke", fake_search_drug_targets)
        object.__setattr__(drug_targets.search_known_drugs, "invoke", fake_search_known_drugs)
        monkeypatch.setattr(drug_targets, "collect_multi_source_evidence", fake_collect_multi_source_evidence)
        yield
        object.__setattr__(drug_targets.search_drug_targets, "invoke", orig_sdt)
        object.__setattr__(drug_targets.search_known_drugs, "invoke", orig_skd)
        monkeypatch.setattr(drug_targets, "collect_multi_source_evidence", orig_mse)

    def test_uses_both_gene_files(self, _mock_opentargets):
        """When both files exist, genes come from top_search_genes + selected_top3_lr."""
        from src.agents.deep_interpreter.tools.drug_targets import assess_therapeutic_potential

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(Path(tmpdir) / "top_search_genes.json", "w") as f:
                json.dump(["HUB1", "HUB2", "HUB3"], f)
            with open(Path(tmpdir) / "selected_top3_lr.json", "w") as f:
                json.dump({
                    "version": 1,
                    "selected_pairs": [
                        {"ligand": "NOV_L", "receptor": "NOV_R", "reasoning": "novel"},
                    ],
                    "count": 1,
                }, f)

            result = json.loads(assess_therapeutic_potential.invoke({
                "data_dir": tmpdir,
                "disease": "test cancer",
            }))

            assert result["gene_source"] == "top_search_genes+selected_top3_lr"
            assert result["hub_genes_count"] == 3
            assert result["novel_lr_genes_count"] == 2
            evaluated = set(result["gene_ranking"].keys())
            assert evaluated == {"HUB1", "HUB2", "HUB3", "NOV_L", "NOV_R"}

    def test_uses_only_hub_genes(self, _mock_opentargets):
        """When only top_search_genes.json exists."""
        from src.agents.deep_interpreter.tools.drug_targets import assess_therapeutic_potential

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(Path(tmpdir) / "top_search_genes.json", "w") as f:
                json.dump(["HUB1", "HUB2"], f)

            result = json.loads(assess_therapeutic_potential.invoke({
                "data_dir": tmpdir,
                "disease": "test cancer",
            }))

            assert result["gene_source"] == "top_search_genes+selected_top3_lr"
            assert result["hub_genes_count"] == 2
            assert result["novel_lr_genes_count"] == 0
            assert set(result["gene_ranking"].keys()) == {"HUB1", "HUB2"}

    def test_uses_only_novel_lr_genes(self, _mock_opentargets):
        """When only selected_top3_lr.json exists."""
        from src.agents.deep_interpreter.tools.drug_targets import assess_therapeutic_potential

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(Path(tmpdir) / "selected_top3_lr.json", "w") as f:
                json.dump({
                    "version": 1,
                    "selected_pairs": [
                        {"ligand": "L1", "receptor": "R1", "reasoning": "x"},
                    ],
                    "count": 1,
                }, f)

            result = json.loads(assess_therapeutic_potential.invoke({
                "data_dir": tmpdir,
                "disease": "test cancer",
            }))

            assert result["gene_source"] == "top_search_genes+selected_top3_lr"
            assert result["hub_genes_count"] == 0
            assert result["novel_lr_genes_count"] == 2
            assert set(result["gene_ranking"].keys()) == {"L1", "R1"}

    def test_uses_lr_candidates_only_when_candidates_exist(self, _mock_opentargets):
        """When lr_candidates.json exists, use only top-15 candidate genes as primary input."""
        from src.agents.deep_interpreter.tools.drug_targets import assess_therapeutic_potential

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(Path(tmpdir) / "top_search_genes.json", "w") as f:
                json.dump(["HUB1"], f)
            with open(Path(tmpdir) / "selected_top3_lr.json", "w") as f:
                json.dump({
                    "version": 1,
                    "selected_pairs": [
                        {"ligand": "TOP3_L", "receptor": "TOP3_R", "reasoning": "x"},
                    ],
                    "count": 1,
                }, f)
            with open(Path(tmpdir) / "lr_candidates.json", "w") as f:
                json.dump({
                    "candidate_pairs": [
                        {"rank": 1, "ligand": "CAND_L", "receptor": "CAND_R"},
                    ]
                }, f)

            result = json.loads(assess_therapeutic_potential.invoke({
                "data_dir": tmpdir,
                "disease": "test cancer",
            }))

            assert result["gene_source"] == "lr_candidates_top15_primary"
            assert set(result["gene_ranking"].keys()) == {
                "CAND_L", "CAND_R"
            }
            assert result["hub_genes_count"] == 1
            assert result["novel_lr_genes_count"] == 2
            assert result["lr_candidates_genes_count"] == 2

    def test_fallback_to_liana_csv(self, _mock_opentargets):
        """When no JSON files exist, falls back to LIANA CSV."""
        from src.agents.deep_interpreter.tools.drug_targets import assess_therapeutic_potential

        with tempfile.TemporaryDirectory() as tmpdir:
            pd.DataFrame({
                "ligand": ["GENE_A", "GENE_B"],
                "receptor": ["GENE_C", "GENE_D"],
                "combinedscore": [0.9, 0.8],
            }).to_csv(Path(tmpdir) / "interest_sig_liana.csv", index=False)

            result = json.loads(assess_therapeutic_potential.invoke({
                "data_dir": tmpdir,
                "disease": "test cancer",
            }))

            assert result["gene_source"] == "liana_csv_fallback"
            assert set(result["gene_ranking"].keys()) == {"GENE_A", "GENE_B", "GENE_C", "GENE_D"}

    def test_error_when_no_files_at_all(self):
        """When no gene source files exist, returns error."""
        from src.agents.deep_interpreter.tools.drug_targets import assess_therapeutic_potential

        with tempfile.TemporaryDirectory() as tmpdir:
            result = json.loads(assess_therapeutic_potential.invoke({
                "data_dir": tmpdir,
                "disease": "test cancer",
            }))

            assert "error" in result

    def test_novel_lr_genes_flagged_in_classification(self, _mock_opentargets):
        """Genes from selected_top3_lr.json should be flagged and classified as novel."""
        from src.agents.deep_interpreter.tools.drug_targets import assess_therapeutic_potential

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(Path(tmpdir) / "top_search_genes.json", "w") as f:
                json.dump(["HUB1"], f)
            with open(Path(tmpdir) / "selected_top3_lr.json", "w") as f:
                json.dump({
                    "version": 1,
                    "selected_pairs": [
                        {"ligand": "NOV_L", "receptor": "NOV_R", "reasoning": "novel"},
                    ],
                    "count": 1,
                }, f)

            result = json.loads(assess_therapeutic_potential.invoke({
                "data_dir": tmpdir,
                "disease": "test cancer",
            }))

            # All genes should be novel targets (assoc_score=0.0 from mock)
            novel_genes_in_result = {t["gene"] for t in result["novel_targets"]}
            assert "NOV_L" in novel_genes_in_result
            assert "NOV_R" in novel_genes_in_result

            # Check from_novel_lr_selection flag
            novel_entries = [t for t in result["novel_targets"] if t.get("from_novel_lr_selection")]
            novel_flagged = {t["gene"] for t in novel_entries}
            assert novel_flagged == {"NOV_L", "NOV_R"}

    def test_deduplicates_overlapping_genes(self, _mock_opentargets):
        """Genes in both hub and novel lists should not be duplicated."""
        from src.agents.deep_interpreter.tools.drug_targets import assess_therapeutic_potential

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(Path(tmpdir) / "top_search_genes.json", "w") as f:
                json.dump(["SHARED", "HUB_ONLY"], f)
            with open(Path(tmpdir) / "selected_top3_lr.json", "w") as f:
                json.dump({
                    "version": 1,
                    "selected_pairs": [
                        {"ligand": "SHARED", "receptor": "NOV_ONLY", "reasoning": "x"},
                    ],
                    "count": 1,
                }, f)

            result = json.loads(assess_therapeutic_potential.invoke({
                "data_dir": tmpdir,
                "disease": "test cancer",
            }))

            gene_keys = list(result["gene_ranking"].keys())
            assert gene_keys.count("SHARED") == 1
            assert set(gene_keys) == {"SHARED", "HUB_ONLY", "NOV_ONLY"}

    def test_writes_dual_gwas_output_files(self, _mock_opentargets):
        """Writes therapeutic_targets_gwas.json and synthesis_gwas.json."""
        from src.agents.deep_interpreter.tools.drug_targets import assess_therapeutic_potential

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(Path(tmpdir) / "top_search_genes.json", "w") as f:
                json.dump(["HUB1"], f)
            with open(Path(tmpdir) / "selected_top3_lr.json", "w") as f:
                json.dump({
                    "version": 1,
                    "selected_pairs": [
                        {"ligand": "NOV_L", "receptor": "NOV_R", "reasoning": "novel"},
                    ],
                    "count": 1,
                }, f)

            result = json.loads(assess_therapeutic_potential.invoke({
                "data_dir": tmpdir,
                "disease": "test cancer",
            }))

            gwas_detail_file = Path(tmpdir) / "therapeutic_targets_gwas.json"
            gwas_summary_file = Path(tmpdir) / "synthesis_gwas.json"
            assert gwas_detail_file.exists()
            assert gwas_summary_file.exists()
            assert "gwas_files" in result

            gwas_detail = json.loads(gwas_detail_file.read_text())
            assert gwas_detail["disease"] == "test cancer"
            assert "summary" in gwas_detail
            assert "genes" in gwas_detail
            assert "gwas_direct_status" in gwas_detail
            assert "multi_source_status" in gwas_detail
            assert "genes_with_chembl_target_support" in gwas_detail["summary"]

    def test_outputs_validated_and_exploratory_tracks(self, _mock_opentargets):
        """Output payload includes 2-track results and summary counts."""
        from src.agents.deep_interpreter.tools.drug_targets import assess_therapeutic_potential

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(Path(tmpdir) / "lr_candidates.json", "w") as f:
                json.dump({
                    "candidate_pairs": [
                        {"rank": 1, "ligand": "L1", "receptor": "R1"},
                        {"rank": 2, "ligand": "L2", "receptor": "R2"},
                    ]
                }, f)

            result = json.loads(assess_therapeutic_potential.invoke({
                "data_dir": tmpdir,
                "disease": "test cancer",
            }))

            assert "validated_track" in result
            assert "exploratory_track" in result
            assert len(result["validated_track"]) == 4
            assert len(result["exploratory_track"]) == 4

            first_validated = result["validated_track"][0]
            first_exploratory = result["exploratory_track"][0]
            assert "validated_score" in first_validated
            assert "validated_pass" in first_validated
            assert "rank" in first_validated
            assert "exploratory_score" in first_exploratory
            assert "exploratory_pass" in first_exploratory
            assert "rank" in first_exploratory

            summary = result["summary"]
            assert "validated_pass_count" in summary
            assert "exploratory_pass_count" in summary
            assert "top_validated_genes" in summary
            assert "top_exploratory_genes" in summary

    def test_outputs_multi_source_status_fields(self, _mock_opentargets):
        """Output payload includes fail-soft multi-source status metadata."""
        from src.agents.deep_interpreter.tools.drug_targets import assess_therapeutic_potential

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(Path(tmpdir) / "lr_candidates.json", "w") as f:
                json.dump({
                    "candidate_pairs": [
                        {"rank": 1, "ligand": "L1", "receptor": "R1"},
                    ]
                }, f)

            result = json.loads(assess_therapeutic_potential.invoke({
                "data_dir": tmpdir,
                "disease": "test cancer",
            }))

            assert "multi_source_status" in result
            assert result["multi_source_status"]["chembl"] == "mocked"
            assert result["multi_source_status"]["clinicaltrials"] == "mocked"
            assert result["multi_source_status"]["drugbank"] == "mocked"

            summary = result["summary"]
            assert "multi_source_status" in summary
            assert summary["multi_source_status"]["chembl"] == "mocked"
            assert "genes_with_chembl_target_support" in summary
            assert "drugs_with_clinical_trials" in summary
            assert "drugs_with_drugbank_match" in summary


# ---------------------------------------------------------------------------
# Tests for hub gene penalty
# ---------------------------------------------------------------------------

class TestHubGenePenalty:
    """Tests for _compute_hub_gene_count and novelty_score integration."""

    def test_compute_hub_gene_count_no_hubs(self):
        """All 0 when no genes match top_genes."""
        from src.agents.deep_interpreter.tools.lr_prioritizer import _compute_hub_gene_count

        df = pd.DataFrame({"ligand": ["A", "B"], "receptor": ["C", "D"]})
        top_genes = [f"G{i}" for i in range(30)]
        result = _compute_hub_gene_count(df, top_genes, df["ligand"], df["receptor"])
        assert (result == 0).all()

    def test_compute_hub_gene_count_one_hub(self):
        """1 when one gene in the pair matches top_genes."""
        from src.agents.deep_interpreter.tools.lr_prioritizer import _compute_hub_gene_count

        df = pd.DataFrame({"ligand": ["TP53", "NOVEL"], "receptor": ["R1", "R2"]})
        top_genes = ["TP53"] + [f"G{i}" for i in range(29)]
        result = _compute_hub_gene_count(df, top_genes, df["ligand"], df["receptor"])
        assert result.iloc[0] == 1  # TP53 is hub
        assert result.iloc[1] == 0  # NOVEL is not

    def test_tool_output_includes_hub_and_novelty(self):
        """pairs should include hub_gene_count and novelty_score fields."""
        from src.agents.deep_interpreter.tools.lr_prioritizer import prioritize_top_lr_pairs

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            pd.DataFrame({
                "ligand": ["TP53", "NOVEL_L"],
                "receptor": ["R1", "R2"],
                "interaction": ["TP53^R1", "NOVEL_L^R2"],
                "morans_r": [0.5, 0.45],
                "genept_score": [0.5, 0.45],
                "combinedscore": [0.50, 0.45],
            }).to_csv(data_dir / "interest_sig_liana.csv", index=False)

            with open(data_dir / "top_search_genes.json", "w") as f:
                json.dump({
                    "version": 2,
                    "genes": ["TP53"] + [f"G{i}" for i in range(29)],
                    "scores": [1.0] + [0.5] * 29,
                    "score_method": "test",
                    "timestamp": "2026-02-23",
                }, f)

            result = json.loads(prioritize_top_lr_pairs.invoke({
                "data_dir": str(data_dir),
                "candidate_count": 5,
            }))
            pairs = result["pairs"]
            assert all("hub_gene_count" in p for p in pairs)
            assert all("novelty_score" in p for p in pairs)

    def test_novelty_score_reranks_candidates(self):
        """Hub pair (combinedscore=0.50, hub=1→novelty=0.40) ranks below
        novel pair (combinedscore=0.45, hub=0→novelty=0.45)."""
        from src.agents.deep_interpreter.tools.lr_prioritizer import prioritize_top_lr_pairs

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            pd.DataFrame({
                "ligand": ["TP53", "NOVEL_L", "OTHER"],
                "receptor": ["R1", "R2", "R3"],
                "interaction": ["TP53^R1", "NOVEL_L^R2", "OTHER^R3"],
                "morans_r": [0.5, 0.45, 0.3],
                "genept_score": [0.5, 0.45, 0.3],
                "combinedscore": [0.50, 0.45, 0.30],
            }).to_csv(data_dir / "interest_sig_liana.csv", index=False)

            with open(data_dir / "top_search_genes.json", "w") as f:
                json.dump({
                    "version": 2,
                    "genes": ["TP53"] + [f"G{i}" for i in range(29)],
                    "scores": [1.0] + [0.5] * 29,
                    "score_method": "test",
                    "timestamp": "2026-02-23",
                }, f)

            result = json.loads(prioritize_top_lr_pairs.invoke({
                "data_dir": str(data_dir),
                "candidate_count": 10,
            }))
            pairs = result["pairs"]
            # NOVEL_L^R2 (novelty=0.45) should rank above TP53^R1 (novelty=0.40)
            assert pairs[0]["interaction"] == "NOVEL_L^R2"
            assert pairs[0]["hub_gene_count"] == 0
            assert pairs[1]["interaction"] == "TP53^R1"
            assert pairs[1]["hub_gene_count"] == 1

    def test_no_top_genes_defaults_zero(self):
        """novelty_score == combinedscore when no top_genes file exists."""
        from src.agents.deep_interpreter.tools.lr_prioritizer import prioritize_top_lr_pairs

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            pd.DataFrame({
                "ligand": ["L1", "L2"],
                "receptor": ["R1", "R2"],
                "interaction": ["L1^R1", "L2^R2"],
                "morans_r": [0.5, 0.3],
                "genept_score": [0.8, 0.6],
                "combinedscore": [0.9, 0.7],
            }).to_csv(data_dir / "interest_sig_liana.csv", index=False)

            result = json.loads(prioritize_top_lr_pairs.invoke({
                "data_dir": str(data_dir),
                "candidate_count": 5,
            }))
            for pair in result["pairs"]:
                assert pair["hub_gene_count"] == 0
                assert pair["novelty_score"] == pair["combinedscore"]


# ---------------------------------------------------------------------------
# Tests for structured rubric in save_selected_lr_pairs
# ---------------------------------------------------------------------------

class TestStructuredRubric:
    """Tests for rubric support in save_selected_lr_pairs."""

    def test_save_with_rubric_scores(self):
        """version=2, rubric persisted, total computed."""
        from src.agents.deep_interpreter.tools.lr_prioritizer import save_selected_lr_pairs

        with tempfile.TemporaryDirectory() as tmpdir:
            pairs = [
                {"ligand": "L1", "receptor": "R1", "reasoning": "test",
                 "rubric": {"novelty": 5, "spatial": 4, "mechanism": 3}},
            ]
            result = json.loads(save_selected_lr_pairs.invoke({
                "data_dir": tmpdir,
                "selected_pairs": pairs,
            }))
            assert result["has_rubric"] is True

            with open(Path(tmpdir) / "selected_top3_lr.json") as f:
                saved = json.load(f)

            assert saved["version"] == 2
            assert "rubric_dimensions" in saved
            rubric = saved["selected_pairs"][0]["rubric"]
            assert rubric["novelty"] == 5
            assert rubric["spatial"] == 4
            assert rubric["mechanism"] == 3
            assert rubric["total"] == 12

    def test_save_without_rubric_backward_compat(self):
        """version=1, no rubric key when rubric not provided."""
        from src.agents.deep_interpreter.tools.lr_prioritizer import save_selected_lr_pairs

        with tempfile.TemporaryDirectory() as tmpdir:
            pairs = [
                {"ligand": "L1", "receptor": "R1", "reasoning": "test"},
            ]
            result = json.loads(save_selected_lr_pairs.invoke({
                "data_dir": tmpdir,
                "selected_pairs": pairs,
            }))
            assert result["has_rubric"] is False

            with open(Path(tmpdir) / "selected_top3_lr.json") as f:
                saved = json.load(f)

            assert saved["version"] == 1
            assert "rubric_dimensions" not in saved

    def test_rubric_scores_clamped(self):
        """Scores outside 1-5 are clamped: 0→1, 7→5."""
        from src.agents.deep_interpreter.tools.lr_prioritizer import save_selected_lr_pairs

        with tempfile.TemporaryDirectory() as tmpdir:
            pairs = [
                {"ligand": "L1", "receptor": "R1", "reasoning": "test",
                 "rubric": {"novelty": 0, "spatial": 7, "mechanism": 3}},
            ]
            save_selected_lr_pairs.invoke({
                "data_dir": tmpdir,
                "selected_pairs": pairs,
            })

            with open(Path(tmpdir) / "selected_top3_lr.json") as f:
                saved = json.load(f)

            rubric = saved["selected_pairs"][0]["rubric"]
            assert rubric["novelty"] == 1   # clamped from 0
            assert rubric["spatial"] == 5   # clamped from 7
            assert rubric["mechanism"] == 3
            assert rubric["total"] == 9     # 1 + 5 + 3

    def test_drug_targets_reads_rubric_file(self):
        """_load_selected_top3_lr works with version=2 rubric files."""
        from src.agents.deep_interpreter.tools.drug_targets import _load_selected_top3_lr

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(Path(tmpdir) / "selected_top3_lr.json", "w") as f:
                json.dump({
                    "version": 2,
                    "selected_pairs": [
                        {"ligand": "MDK", "receptor": "SDC1", "reasoning": "test",
                         "rubric": {"novelty": 5, "spatial": 4, "mechanism": 3, "total": 12}},
                    ],
                    "count": 1,
                    "rubric_dimensions": ["novelty", "spatial", "mechanism"],
                    "timestamp": "2026-02-23T00:00:00Z",
                }, f)

            genes = _load_selected_top3_lr(tmpdir)
            assert genes == ["MDK", "SDC1"]
