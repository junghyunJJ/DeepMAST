"""Hybrid L-R Pair Prioritizer for Deep Interpreter.

This module combines spatial autocorrelation (Moran's R) with GenePT semantic
similarity to prioritize ligand-receptor pairs for detailed interpretation.

The hybrid approach balances:
- Spatial relevance: Moran's R captures spatially co-localized interactions
- Biological relevance: GenePT captures functional gene relationships

Default weights: Spatial 60% + GenePT 40%

Example:
    >>> prioritizer = HybridLRPrioritizer()
    >>> top_pairs = prioritizer.prioritize(liana_df, top_k=3)
    >>> print(prioritizer.get_selection_rationale(top_pairs))
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# Default weights for hybrid scoring
DEFAULT_SPATIAL_WEIGHT = 0.6
DEFAULT_GENEPT_WEIGHT = 0.4


class HybridLRPrioritizer:
    """Hybrid prioritizer combining Moran's R and GenePT scores.

    This prioritizer is designed to select the most biologically relevant
    L-R pairs from LIANA analysis results by combining:

    1. Moran's R (spatial autocorrelation): Measures how spatially
       co-localized the L-R interaction is across tissue spots

    2. GenePT score (semantic similarity): Measures functional relationship
       between ligand and receptor based on gene embeddings

    Attributes:
        spatial_weight: Weight for Moran's R component (default: 0.6)
        genept_weight: Weight for GenePT component (default: 0.4)

    Example:
        >>> prioritizer = HybridLRPrioritizer(spatial_weight=0.6, genept_weight=0.4)
        >>> liana_df = pd.read_csv("interest_sig_liana.csv")
        >>> top_pairs = prioritizer.prioritize(liana_df, top_k=3)
    """

    def __init__(
        self,
        spatial_weight: float = DEFAULT_SPATIAL_WEIGHT,
        genept_weight: float = DEFAULT_GENEPT_WEIGHT,
    ):
        """Initialize the hybrid prioritizer.

        Args:
            spatial_weight: Weight for Moran's R score (0-1)
            genept_weight: Weight for GenePT similarity score (0-1)

        Raises:
            ValueError: If weights don't sum to 1.0
        """
        if not np.isclose(spatial_weight + genept_weight, 1.0):
            raise ValueError(
                f"Weights must sum to 1.0, got {spatial_weight} + {genept_weight} = {spatial_weight + genept_weight}"
            )

        self.spatial_weight = spatial_weight
        self.genept_weight = genept_weight

    def _normalize_scores(self, scores: pd.Series) -> pd.Series:
        """Min-max normalize scores to 0-1 range.

        Args:
            scores: Series of numeric scores

        Returns:
            Normalized scores (0-1 range)
        """
        valid_scores = scores.dropna()
        if len(valid_scores) == 0:
            return scores

        min_val = valid_scores.min()
        max_val = valid_scores.max()

        if max_val == min_val:
            # All scores are the same
            return pd.Series(0.5, index=scores.index)

        return (scores - min_val) / (max_val - min_val)

    def _extract_ligand_receptor(
        self,
        lr_df: pd.DataFrame,
    ) -> tuple[pd.Series, pd.Series]:
        """Extract ligand and receptor from various column formats.

        Supports multiple LIANA output formats:
        - 'ligand' and 'receptor' columns
        - 'ligand_complex' and 'receptor_complex' columns
        - 'interaction' column with 'L^R' format

        Args:
            lr_df: DataFrame with L-R pair information

        Returns:
            Tuple of (ligand_series, receptor_series)

        Raises:
            ValueError: If no recognizable L-R columns found
        """
        # Check for direct ligand/receptor columns
        if "ligand" in lr_df.columns and "receptor" in lr_df.columns:
            return lr_df["ligand"], lr_df["receptor"]

        # Check for complex columns
        if "ligand_complex" in lr_df.columns and "receptor_complex" in lr_df.columns:
            return lr_df["ligand_complex"], lr_df["receptor_complex"]

        # Check for interaction column (format: "LIGAND^RECEPTOR")
        if "interaction" in lr_df.columns:
            interactions = lr_df["interaction"].str.split("^", expand=True)
            if interactions.shape[1] >= 2:
                return interactions[0], interactions[1]

        raise ValueError(
            "Could not find L-R pair columns. Expected 'ligand'/'receptor', "
            "'ligand_complex'/'receptor_complex', or 'interaction' column."
        )

    def _get_morans_r_column(self, lr_df: pd.DataFrame) -> str:
        """Find the Moran's R column in the DataFrame.

        Args:
            lr_df: DataFrame with L-R analysis results

        Returns:
            Column name for Moran's R values

        Raises:
            ValueError: If no Moran's R column found
        """
        possible_columns = [
            "morans_r",
            "morans_R",
            "Morans_R",
            "moran_r",
            "moran_R",
            "Moran_R",
            "moranr",
            "MoranR",
            "global_r",
            "Global_R",
        ]

        for col in possible_columns:
            if col in lr_df.columns:
                return col

        # Check for partial matches
        for col in lr_df.columns:
            if "moran" in col.lower() and "r" in col.lower():
                return col

        raise ValueError(
            f"Could not find Moran's R column. Available columns: {list(lr_df.columns)}"
        )

    def prioritize(
        self,
        lr_df: pd.DataFrame,
        top_k: int = 3,
        morans_col: Optional[str] = None,
        min_morans_r: float = 0.0,
    ) -> pd.DataFrame:
        """Prioritize L-R pairs using hybrid scoring.

        Args:
            lr_df: DataFrame with L-R pairs and Moran's R values
            top_k: Number of top pairs to return
            morans_col: Column name for Moran's R (auto-detected if None)
            min_morans_r: Minimum Moran's R threshold (default: 0.0)

        Returns:
            DataFrame with top_k pairs, including:
            - Original columns
            - genept_score: GenePT similarity score
            - morans_r_norm: Normalized Moran's R
            - genept_score_norm: Normalized GenePT score
            - hybrid_score: Combined weighted score
            - rank: Priority rank (1 = highest)
        """
        if lr_df.empty:
            logger.warning("Empty DataFrame provided")
            return lr_df

        result_df = lr_df.copy()

        # Auto-detect Moran's R column
        if morans_col is None:
            morans_col = self._get_morans_r_column(result_df)

        logger.info(f"Using Moran's R column: {morans_col}")

        # Apply minimum threshold
        if min_morans_r > 0:
            result_df = result_df[result_df[morans_col] >= min_morans_r].copy()
            logger.info(f"Filtered to {len(result_df)} pairs with Moran's R >= {min_morans_r}")

        if result_df.empty:
            logger.warning("No pairs passed Moran's R threshold")
            return result_df

        # Extract ligand and receptor
        ligands, receptors = self._extract_ligand_receptor(result_df)

        # Read GenePT scores from CSV (pre-calculated by MCP pipeline)
        logger.info("Reading GenePT scores from input data...")
        if "genept_score" not in result_df.columns:
            logger.warning(
                "genept_score column not found in input data. "
                "Ensure sig_liana.csv was generated with GenePT scoring enabled."
            )
            result_df["genept_score"] = np.nan

        # Handle missing GenePT scores
        missing_genept = result_df["genept_score"].isna().sum()
        if missing_genept > 0:
            logger.warning(
                f"{missing_genept}/{len(result_df)} pairs missing GenePT scores "
                "(genes not in embeddings)"
            )
            # Fill missing with median of available scores
            median_score = result_df["genept_score"].median()
            if pd.isna(median_score):
                median_score = 0.5  # Default if all missing
            result_df["genept_score"] = result_df["genept_score"].fillna(median_score)

        # Normalize scores
        result_df["morans_r_norm"] = self._normalize_scores(result_df[morans_col])
        result_df["genept_score_norm"] = self._normalize_scores(result_df["genept_score"])

        # Calculate hybrid score
        result_df["hybrid_score"] = (
            self.spatial_weight * result_df["morans_r_norm"]
            + self.genept_weight * result_df["genept_score_norm"]
        )

        # Sort and rank
        result_df = result_df.sort_values("hybrid_score", ascending=False)
        result_df["rank"] = range(1, len(result_df) + 1)

        # Return top_k
        top_pairs = result_df.head(top_k).copy()

        logger.info(
            f"Selected top {len(top_pairs)} L-R pairs by hybrid score "
            f"(spatial={self.spatial_weight}, genept={self.genept_weight})"
        )

        return top_pairs

    def get_selection_rationale(
        self,
        selected_lr: pd.DataFrame,
        morans_col: Optional[str] = None,
    ) -> str:
        """Generate explanation for why these L-R pairs were selected.

        Args:
            selected_lr: DataFrame of selected L-R pairs (from prioritize())
            morans_col: Column name for Moran's R (auto-detected if None)

        Returns:
            Formatted string explaining the selection criteria and scores
        """
        if selected_lr.empty:
            return "No L-R pairs selected."

        if morans_col is None:
            morans_col = self._get_morans_r_column(selected_lr)

        # Extract ligand and receptor
        ligands, receptors = self._extract_ligand_receptor(selected_lr)

        lines = [
            "## L-R Pair Selection Rationale",
            "",
            f"**Scoring Weights**: Spatial (Moran's R) = {self.spatial_weight:.0%}, "
            f"GenePT (Semantic) = {self.genept_weight:.0%}",
            "",
            "| Rank | L-R Pair | Moran's R | GenePT | Hybrid Score |",
            "|------|----------|-----------|--------|--------------|",
        ]

        for idx, row in selected_lr.iterrows():
            ligand = ligands.loc[idx] if hasattr(ligands, 'loc') else ligands.iloc[selected_lr.index.get_loc(idx)]
            receptor = receptors.loc[idx] if hasattr(receptors, 'loc') else receptors.iloc[selected_lr.index.get_loc(idx)]

            rank = int(row.get("rank", 0))
            morans_r = row[morans_col]
            genept = row.get("genept_score", 0)
            hybrid = row.get("hybrid_score", 0)

            lines.append(
                f"| {rank} | {ligand}^{receptor} | {morans_r:.3f} | {genept:.3f} | **{hybrid:.3f}** |"
            )

        lines.extend([
            "",
            "**Interpretation**:",
            "- Higher Moran's R indicates stronger spatial co-localization of L-R interaction",
            "- Higher GenePT score indicates stronger functional relationship between genes",
            "- Hybrid score balances both spatial and biological relevance",
        ])

        return "\n".join(lines)

    def compare_with_baseline(
        self,
        lr_df: pd.DataFrame,
        top_k: int = 3,
        morans_col: Optional[str] = None,
    ) -> dict:
        """Compare hybrid selection with Moran's R-only baseline.

        Args:
            lr_df: DataFrame with L-R pairs
            top_k: Number of top pairs to compare
            morans_col: Column name for Moran's R

        Returns:
            Dict with comparison statistics
        """
        if morans_col is None:
            morans_col = self._get_morans_r_column(lr_df)

        # Get hybrid selection
        hybrid_top = self.prioritize(lr_df, top_k=top_k, morans_col=morans_col)

        # Get Moran's R only selection
        baseline_top = lr_df.nlargest(top_k, morans_col)

        # Extract interaction identifiers
        hybrid_ligands, hybrid_receptors = self._extract_ligand_receptor(hybrid_top)
        baseline_ligands, baseline_receptors = self._extract_ligand_receptor(baseline_top)

        hybrid_pairs = set(zip(hybrid_ligands, hybrid_receptors))
        baseline_pairs = set(zip(baseline_ligands, baseline_receptors))

        overlap = hybrid_pairs & baseline_pairs
        hybrid_only = hybrid_pairs - baseline_pairs
        baseline_only = baseline_pairs - hybrid_pairs

        return {
            "hybrid_selection": list(hybrid_pairs),
            "baseline_selection": list(baseline_pairs),
            "overlap": list(overlap),
            "overlap_count": len(overlap),
            "hybrid_unique": list(hybrid_only),
            "baseline_unique": list(baseline_only),
            "jaccard_similarity": len(overlap) / len(hybrid_pairs | baseline_pairs) if len(hybrid_pairs | baseline_pairs) > 0 else 0.0,
        }


def create_lr_prioritizer(
    spatial_weight: float = DEFAULT_SPATIAL_WEIGHT,
    genept_weight: float = DEFAULT_GENEPT_WEIGHT,
) -> HybridLRPrioritizer:
    """Factory function to create a hybrid L-R prioritizer.

    Args:
        spatial_weight: Weight for Moran's R score (default: 0.6)
        genept_weight: Weight for GenePT similarity (default: 0.4)

    Returns:
        Configured HybridLRPrioritizer instance
    """
    return HybridLRPrioritizer(
        spatial_weight=spatial_weight,
        genept_weight=genept_weight,
    )


# Convenience function for direct use
def prioritize_lr_pairs(
    lr_df: pd.DataFrame,
    top_k: int = 3,
    spatial_weight: float = DEFAULT_SPATIAL_WEIGHT,
    genept_weight: float = DEFAULT_GENEPT_WEIGHT,
) -> pd.DataFrame:
    """Prioritize L-R pairs using hybrid scoring (convenience function).

    Args:
        lr_df: DataFrame with L-R pairs and Moran's R values
        top_k: Number of top pairs to return
        spatial_weight: Weight for Moran's R (default: 0.6)
        genept_weight: Weight for GenePT (default: 0.4)

    Returns:
        DataFrame with top_k prioritized pairs
    """
    prioritizer = create_lr_prioritizer(spatial_weight, genept_weight)
    return prioritizer.prioritize(lr_df, top_k=top_k)


def _find_liana_file(data_path: Path) -> Path | None:
    """Find LIANA results CSV in a directory.

    Args:
        data_path: Directory to search in

    Returns:
        Path to the LIANA CSV file, or None if not found.
    """
    for fname in ("interest_sig_liana.csv", "sig_liana.csv"):
        candidate = data_path / fname
        if candidate.exists():
            return candidate
    return None


def _load_top_search_genes(data_path: Path) -> list[str] | None:
    """Load pre-computed top search genes from JSON file.

    Written by data_loader._extract_search_context() during PLANNER phase.

    Returns:
        List of gene symbols, or None if file not found.
    """
    top_genes_file = data_path / "top_search_genes.json"
    if not top_genes_file.exists():
        return None
    try:
        with open(top_genes_file) as f:
            genes = json.load(f)
        if isinstance(genes, list) and genes:
            return genes
    except Exception:
        pass
    return None


def _exclude_well_known_pairs(
    lr_df: pd.DataFrame,
    top_genes: list[str],
    ligands: pd.Series,
    receptors: pd.Series,
    min_remaining: int = 5,
) -> tuple[pd.DataFrame, int, str]:
    """Exclude L-R pairs where BOTH genes are well-known (in top gene list).

    Uses graduated relaxation: top-30 → top-20 → top-10 → no exclusion.

    Returns:
        (filtered_df, excluded_count, exclusion_level description)
    """
    for n in [30, 20, 10]:
        gene_set = set(top_genes[:n])
        both_in_top = (ligands.isin(gene_set)) & (receptors.isin(gene_set))
        remaining = lr_df[~both_in_top]
        if len(remaining) >= min_remaining:
            excluded = both_in_top.sum()
            logger.info(
                f"Excluded {excluded} pairs where both genes in top-{n}; "
                f"{len(remaining)} candidates remain"
            )
            return remaining.copy(), int(excluded), f"both_in_top_{n}"

    # No exclusion if all thresholds leave too few candidates
    logger.warning(
        f"Graduated exclusion left <{min_remaining} pairs at all levels; "
        "skipping exclusion"
    )
    return lr_df.copy(), 0, "none"


@tool
def prioritize_top_lr_pairs(
    data_dir: str,
    candidate_count: int = 15,
    spatial_weight: float = 0.6,
    genept_weight: float = 0.4,
) -> str:
    """Get candidate L-R pairs for LLM-based novel interaction selection.

    This tool filters out well-known L-R pairs (where both ligand and receptor
    are among the top-30 most-studied genes) and returns candidate pairs for
    the LLM to select the most novel and interesting interactions.

    The workflow:
    1. Load interest_sig_liana.csv (pre-filtered for interest clusters)
    2. Exclude pairs where BOTH genes are well-known hub genes (top-30)
    3. Compute advisory hybrid scores (Moran's R + GenePT) for reference
    4. Return up to candidate_count candidates for LLM selection

    Args:
        data_dir: Path to the analysis directory containing interest_sig_liana.csv
        candidate_count: Max number of candidate pairs to return (default: 15)
        spatial_weight: Weight for Moran's R advisory score (default: 0.6)
        genept_weight: Weight for GenePT advisory score (default: 0.4)

    Returns:
        JSON string with candidate L-R pairs for LLM selection
    """
    data_path = Path(data_dir)

    # Find the LIANA results file
    liana_file = _find_liana_file(data_path)

    # Defense-in-depth: fall back to DEEP_INTERPRETER_DATA_DIR env var
    if liana_file is None:
        env_dir = os.environ.get("DEEP_INTERPRETER_DATA_DIR")
        if env_dir and env_dir != str(data_path):
            logger.warning(
                f"LIANA files not found in {data_dir}, "
                f"falling back to DEEP_INTERPRETER_DATA_DIR={env_dir}"
            )
            fallback_path = Path(env_dir)
            liana_file = _find_liana_file(fallback_path)
            if liana_file is not None:
                data_path = fallback_path

    if liana_file is None:
        return json.dumps({
            "error": f"LIANA results file not found in {data_dir}",
            "searched": ["interest_sig_liana.csv", "sig_liana.csv"],
            "hint": "Ensure data_dir points to the analysis results directory (e.g., res_bc/), not the project root.",
        })

    try:
        lr_df = pd.read_csv(liana_file)
        logger.info(f"Loaded {len(lr_df)} L-R pairs from {liana_file.name}")
    except Exception as e:
        return json.dumps({"error": f"Failed to load LIANA results: {e}"})

    total_pairs = len(lr_df)

    # --- Novelty filtering: exclude well-known hub-gene pairs ---
    excluded_count = 0
    exclusion_level = "none"

    top_genes = _load_top_search_genes(data_path)
    if top_genes:
        try:
            prioritizer_tmp = HybridLRPrioritizer(spatial_weight=spatial_weight, genept_weight=genept_weight)
            ligands, receptors = prioritizer_tmp._extract_ligand_receptor(lr_df)
            lr_df, excluded_count, exclusion_level = _exclude_well_known_pairs(
                lr_df, top_genes, ligands, receptors,
            )
        except ValueError:
            logger.warning("Could not extract ligand/receptor columns for exclusion; skipping")
    else:
        logger.info("top_search_genes.json not found; skipping novelty exclusion")

    if lr_df.empty:
        return json.dumps({
            "error": "No L-R pairs remaining after filtering",
            "total_pairs": total_pairs,
            "excluded_count": excluded_count,
        })

    # --- Compute advisory hybrid scores ---
    try:
        prioritizer = HybridLRPrioritizer(
            spatial_weight=spatial_weight,
            genept_weight=genept_weight,
        )
        scored_df = prioritizer.prioritize(lr_df, top_k=len(lr_df))
    except Exception as e:
        return json.dumps({"error": f"Scoring failed: {e}"})

    # --- Select candidates ---
    # If more than candidate_count: prefer combinedscore if available, else hybrid_score
    if len(scored_df) > candidate_count:
        if "combinedscore" in scored_df.columns:
            scored_df = scored_df.nlargest(candidate_count, "combinedscore")
        else:
            scored_df = scored_df.head(candidate_count)
    # Re-rank after selection
    scored_df = scored_df.sort_values("hybrid_score", ascending=False)
    scored_df["rank"] = range(1, len(scored_df) + 1)

    # Generate rationale
    rationale = prioritizer.get_selection_rationale(scored_df)

    # Extract key columns for output
    output_columns = [
        "ligand", "receptor", "interaction",
        "morans_r", "morans_R", "Morans_R", "global_r",
        "genept_score", "combinedscore", "hybrid_score", "rank",
    ]
    available_columns = [c for c in output_columns if c in scored_df.columns]

    result = {
        "selection_mode": "llm_candidate_list",
        "instruction": (
            "These are CANDIDATE L-R pairs with well-known hub-gene pairs excluded. "
            "YOU must select the TOP 3 most interesting pairs for detailed Part 3 interpretation. "
            "Prioritize: (1) biological novelty, (2) spatial significance (high Moran's R), "
            "(3) mechanistic plausibility in the tissue context. "
            "Write your selection reasoning BEFORE interpreting."
        ),
        "candidate_pairs": scored_df[available_columns].to_dict(orient="records"),
        "total_pairs_in_file": total_pairs,
        "excluded_count": excluded_count,
        "exclusion_level": exclusion_level,
        "candidates_returned": len(scored_df),
        "advisory_scores": {
            "spatial_weight": spatial_weight,
            "genept_weight": genept_weight,
            "note": "hybrid_score is advisory only — use biological reasoning for final selection",
        },
        "rationale": rationale,
    }

    return json.dumps(result, indent=2, default=str)
