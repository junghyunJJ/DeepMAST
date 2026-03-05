"""Tests for data_loader gene augmentation with lr_candidates.

Verifies that load_analysis_data augments the unified search_context['genes']
with novel candidate genes from prioritize_top_lr_pairs.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest


@pytest.fixture
def analysis_dir(tmp_path):
    """Create a minimal analysis directory with required files.

    Generates >30 unique genes so the top-30 cutoff triggers,
    plus novel genes that only appear in low-frequency pairs.
    """
    rows = []
    # Generate 35+ unique hub genes to exceed MAX_SEARCH_GENES=30
    # These high-frequency genes will fill the top-30 slots
    hub_genes = [f"HUB_{chr(65 + i)}" for i in range(18)]  # HUB_A..HUB_R (18 genes)
    for i, gene in enumerate(hub_genes):
        for j in range(20 - i):  # decreasing frequency for ranking variation
            partner = hub_genes[(i + 1) % len(hub_genes)]
            rows.append({
                "ligand": gene, "receptor": partner,
                "interaction": f"{gene}^{partner}",
                "morans_r": 0.5 + i * 0.01,
                "genept_score": 0.8,
                "combinedscore": 0.95 - i * 0.02,
                "progeny": "EGFR",
                "ligand_ctSVG": "Cancer", "receptor_ctSVG": "Stroma",
                "cluster": "4",
            })

    # Additional hub genes to push total unique count above 30
    extra_hub_genes = [f"EXTRA_{chr(65 + i)}" for i in range(16)]  # EXTRA_A..EXTRA_P
    for i, gene in enumerate(extra_hub_genes):
        for j in range(5):  # moderate frequency
            rows.append({
                "ligand": gene, "receptor": hub_genes[i % len(hub_genes)],
                "interaction": f"{gene}^{hub_genes[i % len(hub_genes)]}",
                "morans_r": 0.3 + i * 0.01,
                "genept_score": 0.6,
                "combinedscore": 0.7 - i * 0.01,
                "progeny": "TNFa",
                "ligand_ctSVG": "Fibroblast", "receptor_ctSVG": "Cancer",
                "cluster": "16",
            })

    # Novel gene pairs (low frequency - will appear in lr_candidates but NOT top-30)
    rows.append({
        "ligand": "NOVEL_X", "receptor": "HUB_A",
        "interaction": "NOVEL_X^HUB_A",
        "morans_r": 0.35,
        "genept_score": 0.6,
        "combinedscore": 0.75,
        "progeny": "JAK-STAT",
        "ligand_ctSVG": "Cancer", "receptor_ctSVG": "Stroma",
        "cluster": "4",
    })
    rows.append({
        "ligand": "HUB_B", "receptor": "NOVEL_Y",
        "interaction": "HUB_B^NOVEL_Y",
        "morans_r": 0.30,
        "genept_score": 0.55,
        "combinedscore": 0.70,
        "progeny": "TGFb",
        "ligand_ctSVG": "Cancer", "receptor_ctSVG": "Fibroblast",
        "cluster": "17",
    })
    # Complex receptor name with underscore (e.g., ITGA2_ITGB1)
    # Low combinedscore keeps ITGA2_ITGB1 out of top-30 search genes,
    # so the pair survives the prioritizer's both-hub exclusion filter.
    # With <30 total candidate pairs, it still makes it into lr_candidates.
    rows.append({
        "ligand": "HUB_C", "receptor": "ITGA2_ITGB1",
        "interaction": "HUB_C^ITGA2_ITGB1",
        "morans_r": 0.20,
        "genept_score": 0.3,
        "combinedscore": 0.30,
        "progeny": "WNT",
        "ligand_ctSVG": "Stroma", "receptor_ctSVG": "Fibroblast",
        "cluster": "4",
    })
    # Both-novel pair (will be excluded by hub filter in prioritizer)
    rows.append({
        "ligand": "NOVEL_Z", "receptor": "NOVEL_W",
        "interaction": "NOVEL_Z^NOVEL_W",
        "morans_r": 0.25,
        "genept_score": 0.5,
        "combinedscore": 0.60,
        "progeny": "WNT",
        "ligand_ctSVG": "Stroma", "receptor_ctSVG": "Fibroblast",
        "cluster": "4",
    })

    df = pd.DataFrame(rows)
    df.to_csv(tmp_path / "interest_sig_liana.csv", index=False)

    # Create minimal figure files so load_analysis_data finds analyses
    for fig_name in [
        "1.cluster_spatial.png",
        "9.quadrant_analysis.png",
        "10.spatial_plot_interections.png",
        "11.lr_interections.png",
    ]:
        (tmp_path / fig_name).touch()

    # Create sig_clusterwithcelltyp.csv for celltype extraction
    ct_df = pd.DataFrame({
        "cluster": ["4", "16", "17"],
        "celltype": ["Cancer", "Stroma", "Fibroblast"],
    })
    ct_df.to_csv(tmp_path / "sig_clusterwithcelltyp.csv", index=False)

    # Create sel_interest_sig_liana.csv (copy of interest for Part 3-11)
    df.head(5).to_csv(tmp_path / "sel_interest_sig_liana.csv", index=False)

    return tmp_path


class TestLoadAnalysisDataGeneAugmentation:
    """Test that load_analysis_data augments genes with lr_candidates."""

    def test_augments_genes_with_novel_candidates(self, analysis_dir):
        """search_context['genes'] should include novel candidate genes."""
        from src.agents.deep_interpreter.tools.data_loader import load_analysis_data

        result = load_analysis_data.invoke({"data_dir": str(analysis_dir)})

        lr_ctx = result["search_context"]
        genes = lr_ctx["genes"]

        # With >30 unique genes, top-30 cutoff should trigger
        # Novel genes from lr_candidates should be appended
        assert len(genes) > 0

        # Augmentation MUST have occurred with this fixture (unconditional)
        candidate_genes = lr_ctx.get("candidate_genes", [])
        assert len(candidate_genes) > 0, (
            "Expected novel candidate genes from augmentation, got none. "
            f"Total genes: {len(genes)}"
        )
        for gene in candidate_genes:
            assert gene in genes, f"Novel gene {gene} missing from augmented gene list"

    def test_gene_order_preserved(self, analysis_dir):
        """FIX #2: Original top-30 gene order must be preserved after augmentation."""
        from src.agents.deep_interpreter.tools.data_loader import load_analysis_data

        result = load_analysis_data.invoke({"data_dir": str(analysis_dir)})

        lr_ctx = result["search_context"]
        genes = lr_ctx["genes"]
        candidate_genes = lr_ctx.get("candidate_genes", [])

        if candidate_genes:
            # Original genes come first, then novel genes appended
            original_count = len(genes) - len(candidate_genes)
            original_genes = genes[:original_count]
            appended_genes = genes[original_count:]

            # Novel genes should be at the end, sorted
            assert appended_genes == sorted(candidate_genes)

            # Original genes should not be reordered (not a set conversion)
            # Verify no duplicates between original and appended
            assert len(set(original_genes) & set(appended_genes)) == 0

    def test_stats_search_genes_updated(self, analysis_dir):
        """FIX #3: stats['search_genes'] must reflect augmented gene count."""
        from src.agents.deep_interpreter.tools.data_loader import load_analysis_data

        result = load_analysis_data.invoke({"data_dir": str(analysis_dir)})

        lr_ctx = result["search_context"]
        genes = lr_ctx["genes"]
        stats = lr_ctx["stats"]

        assert stats["search_genes"] == len(genes), (
            f"stats['search_genes']={stats['search_genes']} != "
            f"actual gene count={len(genes)}"
        )

    def test_note_preserves_original_info(self, analysis_dir):
        """FIX #4: note field should append, not overwrite original scoring context."""
        from src.agents.deep_interpreter.tools.data_loader import load_analysis_data

        result = load_analysis_data.invoke({"data_dir": str(analysis_dir)})

        lr_ctx = result["search_context"]
        candidate_genes = lr_ctx.get("candidate_genes", [])

        if candidate_genes:
            note = lr_ctx["note"]
            # Original hybrid score info should be preserved
            assert "hybrid score" in note.lower() or "combinedscore" in note.lower(), (
                f"Original scoring context lost in note: {note}"
            )
            # Augmentation info should be appended
            assert "Augmented" in note
            assert "Total:" in note

    def test_complex_receptor_name_split(self, analysis_dir):
        """Underscore-delimited receptor names (e.g., ITGA2_ITGB1) should be split.

        Mocks the prioritizer to return a pair with a complex receptor name,
        bypassing candidate_count ranking which may exclude low-score pairs.
        """
        from src.agents.deep_interpreter.tools.data_loader import load_analysis_data

        mock_result = json.dumps({
            "pairs": [
                {"ligand": "HUB_A", "receptor": "ITGA2_ITGB1",
                 "combinedscore": 0.80, "hub_gene_count": 1,
                 "novelty_score": 0.70, "rank": 1},
            ],
            "total_candidates": 1,
        })
        with patch(
            "src.agents.deep_interpreter.tools.lr_prioritizer.prioritize_top_lr_pairs"
        ) as mock_prioritizer:
            mock_prioritizer.invoke.return_value = mock_result
            result = load_analysis_data.invoke({"data_dir": str(analysis_dir)})

        lr_ctx = result["search_context"]
        genes = lr_ctx["genes"]
        candidate_genes = lr_ctx.get("candidate_genes", [])

        # ITGA2 and ITGB1 should appear as individual split genes
        all_augmented = set(genes) | set(candidate_genes)
        assert "ITGA2" in all_augmented, (
            f"ITGA2 missing after splitting ITGA2_ITGB1. Genes: {sorted(all_augmented)}"
        )
        assert "ITGB1" in all_augmented, (
            f"ITGB1 missing after splitting ITGA2_ITGB1. Genes: {sorted(all_augmented)}"
        )

    def test_lr_candidates_json_created(self, analysis_dir):
        """lr_candidates.json should be created during load_analysis_data."""
        from src.agents.deep_interpreter.tools.data_loader import load_analysis_data

        load_analysis_data.invoke({"data_dir": str(analysis_dir)})

        candidates_file = analysis_dir / "lr_candidates.json"
        assert candidates_file.exists(), "lr_candidates.json should be created"

        with open(candidates_file) as f:
            candidates = json.load(f)

        assert "pairs" in candidates
        assert len(candidates["pairs"]) > 0

    def test_top_search_genes_json_created(self, analysis_dir):
        """top_search_genes.json should be created during load_analysis_data."""
        from src.agents.deep_interpreter.tools.data_loader import load_analysis_data

        load_analysis_data.invoke({"data_dir": str(analysis_dir)})

        top_genes_file = analysis_dir / "top_search_genes.json"
        assert top_genes_file.exists(), "top_search_genes.json should be created"

        with open(top_genes_file) as f:
            payload = json.load(f)

        assert "genes" in payload
        assert len(payload["genes"]) > 0

    def test_graceful_degradation_on_missing_liana(self, tmp_path):
        """Should fall back to original genes if prioritize_top_lr_pairs fails."""
        from src.agents.deep_interpreter.tools.data_loader import load_analysis_data

        # Create minimal dir with just a figure (no CSV)
        (tmp_path / "1.cluster_spatial.png").touch()

        result = load_analysis_data.invoke({"data_dir": str(tmp_path)})

        # Should still return a valid result without crashing
        lr_ctx = result["search_context"]
        assert isinstance(lr_ctx.get("genes", []), list)

    def test_existing_return_structure_preserved(self, analysis_dir):
        """Existing return keys should not be removed or renamed."""
        from src.agents.deep_interpreter.tools.data_loader import load_analysis_data

        result = load_analysis_data.invoke({"data_dir": str(analysis_dir)})

        # All original keys must be present
        required_keys = [
            "data_dir", "available_analyses", "figures", "data",
            "missing_analyses", "summary", "clusters", "celltypes",
            "genes", "search_context",
        ]
        for key in required_keys:
            assert key in result, f"Missing required key: {key}"

        # search_context must have standard fields
        lr_ctx = result["search_context"]
        for field in ["genes", "pathways", "celltypes", "source", "context_type"]:
            assert field in lr_ctx, f"Missing search_context field: {field}"
