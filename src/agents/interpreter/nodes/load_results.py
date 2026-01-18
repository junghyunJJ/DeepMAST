"""Load pre-computed analysis results from CSV files.

This module handles loading all Part 1 and Part 2 analysis results
from the results directory.

IMPORTANT: Results are stored as file path references, not DataFrames.
This is required for msgpack serialization with LangGraph checkpointer.
Use load_dataframe_from_ref() to load DataFrames on-demand.
"""

import os
from pathlib import Path
from typing import Any

import pandas as pd

from src.agents.interpreter.biological_interpreter_state import AnalysisDataRef


# File mapping for Part 1 results (from normalized adata)
PART1_FILE_MAPPING = {
    "spatial": {
        "figure": "1.spatial.png",
        "data": None,  # No CSV for spatial plot
    },
    "celltype": {
        "figure": "2.celltype_heatmap_analysis.png",
        "data": "sig_clusterwithcelltyp.csv",
    },
    "nhood": {
        "figure": "3.neighborhood_enrichment_squidpy.png",
        "data": "res_nhood_enrichment.csv",
    },
    "decoupler": {
        "figure": "4.spatial_enrich_decoupler.png",
        "data": "sig_PathwayEnrich_decoupler.csv",
    },
    "misty": {
        "figure": "5.spatial_relation_MISTy.png",
        "data": "res_SpatialRelationship_MISTy.csv",
    },
}

# File mapping for Part 2 results (from lrdata)
PART2_FILE_MAPPING = {
    "morans": {
        "figure": "6.liana_MoransR.png",
        "data": "sig_liana.csv",
    },
    "nmf_factors": {
        "figure": "7.factor_spatial_NMF.png",
        "data": "res_liana_cluster_factor.csv",
    },
    "pathway_factor": {
        "figure": "8.pathway_factor_heatmap.png",
        "data": "sig_liana_pathway_factor.csv",
    },
    "ctsvg": {
        "figure": "9.quadrant_analysis.png",
        "data": "anno_sig_liana.csv",
        "interest_data": "interest_anno_sig_liana.csv",
    },
}

# Part 3 files (generated from selected LR pairs)
PART3_FILE_MAPPING = {
    "spatial_lr": {
        "figure": "10.spatial_plot_interections.png",
        "data": None,
    },
    "lr_summary": {
        "figure": "11.lr_interections.png",
        "data": None,
    },
}


def load_csv_safe(filepath: str | Path) -> pd.DataFrame | None:
    """Safely load a CSV file, returning None if not found."""
    try:
        if os.path.exists(filepath):
            return pd.read_csv(filepath)
        return None
    except Exception as e:
        print(f"Warning: Could not load {filepath}: {e}")
        return None


def check_figure_exists(filepath: str | Path) -> str | None:
    """Check if a figure file exists and return the path."""
    if os.path.exists(filepath):
        return str(filepath)
    return None


def load_dataframe_from_ref(
    ref: AnalysisDataRef | dict | None,
    key: str = "data_path"
) -> pd.DataFrame | None:
    """Load DataFrame from a file path reference.

    This function is used to load DataFrames on-demand from file path references
    stored in state. This pattern avoids msgpack serialization issues with
    LangGraph checkpointer.

    Args:
        ref: AnalysisDataRef dict containing file path references
        key: The key to use for the data path (default: "data_path",
             also supports "interest_data_path")

    Returns:
        DataFrame if file exists and loads successfully, None otherwise

    Example:
        >>> celltype_ref = state.get("part1_results", {}).get("celltype", {})
        >>> celltype_data = load_dataframe_from_ref(celltype_ref)
        >>> if celltype_data is not None:
        ...     # Process the DataFrame
        ...     pass
    """
    if ref is None:
        return None

    path = ref.get(key)
    if path is None:
        return None

    return load_csv_safe(path)


async def load_all_results(
    results_dir: str = "res/",
) -> tuple[dict[str, AnalysisDataRef], dict[str, AnalysisDataRef]]:
    """Load all pre-computed analysis results as file path references.

    IMPORTANT: Returns file paths, NOT DataFrames.
    This is required for msgpack serialization with LangGraph checkpointer.
    Use load_dataframe_from_ref() to load DataFrames on-demand.

    Args:
        results_dir: Directory containing the results files

    Returns:
        Tuple of (part1_results, part2_results)

    Each result dict has the structure:
    {
        "analysis_name": {
            "figure_path": str | None,  # Path to figure
            "data_path": str | None,    # Path to CSV data file
        }
    }

    Example:
        >>> part1, part2 = await load_all_results("res/")
        >>> celltype_data = load_dataframe_from_ref(part1.get("celltype"))
    """
    results_path = Path(results_dir)

    # Load Part 1 results as file path references
    part1_results: dict[str, AnalysisDataRef] = {}
    for analysis_name, files in PART1_FILE_MAPPING.items():
        result: AnalysisDataRef = {}

        # Store figure path (verify it exists)
        if files.get("figure"):
            figure_path = results_path / files["figure"]
            result["figure_path"] = check_figure_exists(figure_path)

        # Store data path (don't load DataFrame, just store path)
        if files.get("data"):
            data_path = results_path / files["data"]
            # Only store if file exists
            if os.path.exists(data_path):
                result["data_path"] = str(data_path)
            else:
                result["data_path"] = None
        else:
            result["data_path"] = None

        part1_results[analysis_name] = result

    # Load Part 2 results as file path references
    part2_results: dict[str, AnalysisDataRef] = {}
    for analysis_name, files in PART2_FILE_MAPPING.items():
        result: AnalysisDataRef = {}

        # Store figure path
        if files.get("figure"):
            figure_path = results_path / files["figure"]
            result["figure_path"] = check_figure_exists(figure_path)

        # Store main data path
        if files.get("data"):
            data_path = results_path / files["data"]
            if os.path.exists(data_path):
                result["data_path"] = str(data_path)
            else:
                result["data_path"] = None
        else:
            result["data_path"] = None

        # Store interest data path (for ctsvg)
        if files.get("interest_data"):
            interest_path = results_path / files["interest_data"]
            if os.path.exists(interest_path):
                result["interest_data_path"] = str(interest_path)
            else:
                result["interest_data_path"] = None

        part2_results[analysis_name] = result

    # Load Part 3 results as file path references
    for analysis_name, files in PART3_FILE_MAPPING.items():
        result: AnalysisDataRef = {}

        if files.get("figure"):
            figure_path = results_path / files["figure"]
            result["figure_path"] = check_figure_exists(figure_path)

        result["data_path"] = None
        part2_results[analysis_name] = result

    return part1_results, part2_results


def get_available_clusters(part1_results: dict[str, AnalysisDataRef]) -> list[str]:
    """Extract available clusters from celltype composition data."""
    celltype_ref = part1_results.get("celltype", {})
    celltype_data = load_dataframe_from_ref(celltype_ref)
    if celltype_data is not None and "cluster" in celltype_data.columns:
        return sorted(celltype_data["cluster"].unique().tolist())
    return []


def get_available_celltypes(part1_results: dict[str, AnalysisDataRef]) -> list[str]:
    """Extract available cell types from celltype composition data."""
    celltype_ref = part1_results.get("celltype", {})
    celltype_data = load_dataframe_from_ref(celltype_ref)
    if celltype_data is not None and "celltype" in celltype_data.columns:
        return sorted(celltype_data["celltype"].unique().tolist())
    return []


def get_available_pathways(part1_results: dict[str, AnalysisDataRef]) -> list[str]:
    """Extract available pathways from decoupler data."""
    decoupler_ref = part1_results.get("decoupler", {})
    decoupler_data = load_dataframe_from_ref(decoupler_ref)
    if decoupler_data is not None and "name" in decoupler_data.columns:
        return sorted(decoupler_data["name"].unique().tolist())
    return []


def get_cluster_celltype_mapping(
    part1_results: dict[str, AnalysisDataRef],
    clusters: list[str] | None = None,
    fdr_threshold: float = 0.05,
) -> dict[str, list[str]]:
    """Get mapping of clusters to enriched cell types.

    Args:
        part1_results: Part 1 results containing celltype data references
        clusters: Specific clusters to filter (None for all)
        fdr_threshold: FDR threshold for significance

    Returns:
        Dict mapping cluster -> list of enriched celltypes
    """
    celltype_ref = part1_results.get("celltype", {})
    celltype_data = load_dataframe_from_ref(celltype_ref)
    if celltype_data is None:
        return {}

    # Filter by significance
    sig_data = celltype_data[celltype_data["fdr"] < fdr_threshold]

    if clusters:
        # Convert clusters to match data type (could be int or str)
        cluster_col_dtype = sig_data["cluster"].dtype
        if cluster_col_dtype in ['int64', 'int32', 'float64']:
            clusters_converted = [int(c) if str(c).isdigit() else c for c in clusters]
        else:
            clusters_converted = [str(c) for c in clusters]
        sig_data = sig_data[sig_data["cluster"].isin(clusters_converted)]

    # Group by cluster
    mapping = {}
    for cluster in sig_data["cluster"].unique():
        cluster_data = sig_data[sig_data["cluster"] == cluster]
        celltypes = cluster_data["celltype"].tolist()
        mapping[str(cluster)] = celltypes

    return mapping


def get_celltype_cluster_mapping(
    part1_results: dict[str, AnalysisDataRef],
    celltypes: list[str] | None = None,
    fdr_threshold: float = 0.05,
) -> dict[str, list[str]]:
    """Get mapping of cell types to enriched clusters.

    Args:
        part1_results: Part 1 results containing celltype data references
        celltypes: Specific celltypes to filter (None for all)
        fdr_threshold: FDR threshold for significance

    Returns:
        Dict mapping celltype -> list of enriched clusters
    """
    celltype_ref = part1_results.get("celltype", {})
    celltype_data = load_dataframe_from_ref(celltype_ref)
    if celltype_data is None:
        return {}

    # Detect column names (could be 'fdr' or 'padj')
    pval_col = "fdr" if "fdr" in celltype_data.columns else "padj"

    # Filter by significance
    sig_data = celltype_data[celltype_data[pval_col] < fdr_threshold]

    if celltypes:
        sig_data = sig_data[sig_data["celltype"].isin(celltypes)]

    # Group by celltype
    mapping = {}
    for ct in sig_data["celltype"].unique():
        ct_data = sig_data[sig_data["celltype"] == ct]
        clusters = ct_data["cluster"].tolist()
        mapping[ct] = [str(c) for c in clusters]

    return mapping


def get_cluster_pathways(
    part1_results: dict[str, AnalysisDataRef],
    clusters: list[str],
    padj_threshold: float = 0.05,
) -> dict[str, list[dict]]:
    """Get pathways enriched in specific clusters.

    Args:
        part1_results: Part 1 results containing decoupler data references
        clusters: Clusters to analyze
        padj_threshold: Adjusted p-value threshold

    Returns:
        Dict mapping cluster -> list of pathway info dicts
    """
    decoupler_ref = part1_results.get("decoupler", {})
    decoupler_data = load_dataframe_from_ref(decoupler_ref)
    if decoupler_data is None:
        return {}

    # Column name may vary: padj or fdr
    pval_col = "fdr" if "fdr" in decoupler_data.columns else "padj"

    # Detect group column - could be 'group', 'cluster', 'Cluster'
    possible_group_cols = ["group", "cluster", "Cluster"]
    group_col = None
    for col in possible_group_cols:
        if col in decoupler_data.columns:
            group_col = col
            break

    if group_col is None:
        return {}

    # Determine group column dtype for type conversion
    group_col_dtype = decoupler_data[group_col].dtype

    result = {}
    for cluster in clusters:
        # Convert cluster to match data type
        if group_col_dtype in ['int64', 'int32', 'float64']:
            cluster_val = int(cluster) if str(cluster).isdigit() else cluster
        else:
            cluster_val = str(cluster)

        # Filter by cluster and significance
        cluster_data = decoupler_data[
            (decoupler_data[group_col] == cluster_val)
            & (decoupler_data[pval_col] < padj_threshold)
        ]
        pathways = []
        for _, row in cluster_data.iterrows():
            pathways.append({
                "name": row["name"],
                "stat": row.get("stat", 0),
                "meanchange": row.get("meanchange", 0),
                "padj": row.get(pval_col, row.get("fdr", row.get("padj", 1))),
            })
        result[str(cluster)] = sorted(
            pathways, key=lambda x: x["stat"], reverse=True
        )

    return result


def get_neighborhood_clusters(
    part1_results: dict[str, AnalysisDataRef],
    clusters: list[str],
    enrichment_threshold: float = 0,
) -> dict[str, list[str]]:
    """Get clusters that are spatially enriched neighbors.

    Args:
        part1_results: Part 1 results containing nhood data references
        clusters: Clusters to find neighbors for
        enrichment_threshold: Minimum enrichment score

    Returns:
        Dict mapping cluster -> list of enriched neighbor clusters
    """
    nhood_ref = part1_results.get("nhood", {})
    nhood_data = load_dataframe_from_ref(nhood_ref)
    if nhood_data is None:
        return {}

    # Detect column names - could be 'cluster'/'Cluster' or 'Cluster'/'Cluster.1'
    possible_cluster_cols = ["cluster", "Cluster"]
    cluster_col = None
    for col in possible_cluster_cols:
        if col in nhood_data.columns:
            cluster_col = col
            break

    if cluster_col is None:
        # Fallback to first column
        cluster_col = nhood_data.columns[0]

    # Detect neighbor column - could be 'cluster.1', 'Cluster.1', or second column
    possible_neighbor_cols = ["cluster.1", "Cluster.1", "neighbor"]
    neighbor_col = None
    for col in possible_neighbor_cols:
        if col in nhood_data.columns:
            neighbor_col = col
            break

    if neighbor_col is None:
        # Fallback to second column
        neighbor_col = nhood_data.columns[1]

    # Detect value column
    value_col = "value" if "value" in nhood_data.columns else nhood_data.columns[2]

    # Determine cluster column dtype for type conversion
    cluster_col_dtype = nhood_data[cluster_col].dtype

    result = {}
    for cluster in clusters:
        # Convert cluster to match data type
        if cluster_col_dtype in ['int64', 'int32', 'float64']:
            cluster_val = int(cluster) if str(cluster).isdigit() else cluster
        else:
            cluster_val = str(cluster)

        # Find neighbor clusters with positive enrichment
        neighbors = []
        cluster_rows = nhood_data[nhood_data[cluster_col] == cluster_val]

        for _, row in cluster_rows.iterrows():
            if row[value_col] > enrichment_threshold:
                # Clean up neighbor value (convert '6.0' to '6')
                neighbor_val = row[neighbor_col]
                if isinstance(neighbor_val, float):
                    neighbor_val = int(neighbor_val)
                neighbors.append(str(neighbor_val))

        result[str(cluster)] = neighbors

    return result


def get_factor_cluster_scores(
    part2_results: dict[str, AnalysisDataRef],
) -> dict[str, dict[str, float]]:
    """Get factor scores per cluster.

    Args:
        part2_results: Part 2 results containing NMF factor data references

    Returns:
        Dict mapping factor_name -> {cluster: median_score}
    """
    nmf_ref = part2_results.get("nmf_factors", {})
    nmf_data = load_dataframe_from_ref(nmf_ref)
    if nmf_data is None:
        return {}

    result = {}

    # Get factor columns (Factor1, Factor2, ... or Factor_1, Factor_2, ...)
    factor_cols = [col for col in nmf_data.columns if col.startswith("Factor")]

    # Detect cluster/annotation column - could be 'Annotation', 'Cluster', 'cluster'
    possible_cluster_cols = ["Annotation", "Cluster", "cluster", "annotation"]
    cluster_col = None
    for col in possible_cluster_cols:
        if col in nmf_data.columns:
            cluster_col = col
            break

    if cluster_col is None:
        # Try to find any column that looks like cluster/annotation
        for col in nmf_data.columns:
            if "cluster" in col.lower() or "annot" in col.lower():
                cluster_col = col
                break

    if cluster_col is None or len(factor_cols) == 0:
        return {}

    for factor_col in factor_cols:
        cluster_scores = {}
        for cluster in nmf_data[cluster_col].unique():
            cluster_data = nmf_data[nmf_data[cluster_col] == cluster]
            median_score = cluster_data[factor_col].median()
            cluster_scores[str(cluster)] = median_score
        result[factor_col] = cluster_scores

    return result


def get_lr_pair_data(
    part2_results: dict[str, AnalysisDataRef],
    use_interest: bool = True,
) -> pd.DataFrame | None:
    """Get ligand-receptor pair data for scoring.

    Args:
        part2_results: Part 2 results containing ctsvg data references
        use_interest: Whether to use interest_anno_sig_liana.csv

    Returns:
        DataFrame with LR pair data (loaded on-demand)
    """
    ctsvg_ref = part2_results.get("ctsvg", {})

    if use_interest:
        interest_data = load_dataframe_from_ref(ctsvg_ref, key="interest_data_path")
        if interest_data is not None:
            return interest_data

    return load_dataframe_from_ref(ctsvg_ref, key="data_path")


# =============================================================================
# Auto-Detection and Generation Functions
# =============================================================================

def check_missing_files(results_dir: str = "res/") -> dict[str, list[str]]:
    """Check which analysis files are missing.

    Args:
        results_dir: Directory containing results files

    Returns:
        Dictionary with keys 'part1', 'part2', 'part3' containing
        lists of missing analysis names
    """
    results_path = Path(results_dir)
    missing = {
        "part1": [],
        "part2": [],
        "part3": [],
    }

    # Check Part 1 files
    for analysis_name, files in PART1_FILE_MAPPING.items():
        has_required_files = True
        for file_type, filename in files.items():
            if filename and not (results_path / filename).exists():
                has_required_files = False
                break
        if not has_required_files:
            missing["part1"].append(analysis_name)

    # Check Part 2 files
    for analysis_name, files in PART2_FILE_MAPPING.items():
        has_required_files = True
        for file_type, filename in files.items():
            if filename and not (results_path / filename).exists():
                has_required_files = False
                break
        if not has_required_files:
            missing["part2"].append(analysis_name)

    # Check Part 3 files
    for analysis_name, files in PART3_FILE_MAPPING.items():
        has_required_files = True
        for file_type, filename in files.items():
            if filename and not (results_path / filename).exists():
                has_required_files = False
                break
        if not has_required_files:
            missing["part3"].append(analysis_name)

    return missing


def get_missing_files_summary(results_dir: str = "res/") -> str:
    """Get a human-readable summary of missing files.

    Args:
        results_dir: Directory containing results files

    Returns:
        Summary string describing missing files
    """
    missing = check_missing_files(results_dir)

    lines = []
    if missing["part1"]:
        lines.append(f"Part 1 missing: {', '.join(missing['part1'])}")
    if missing["part2"]:
        lines.append(f"Part 2 missing: {', '.join(missing['part2'])}")
    if missing["part3"]:
        lines.append(f"Part 3 missing: {', '.join(missing['part3'])}")

    if not lines:
        return "All analysis files are present."

    return "\n".join(lines)


def has_all_required_files(results_dir: str = "res/") -> bool:
    """Check if all required analysis files exist.

    Args:
        results_dir: Directory containing results files

    Returns:
        True if all Part 1 and Part 2 files exist (Part 3 is optional)
    """
    missing = check_missing_files(results_dir)
    return len(missing["part1"]) == 0 and len(missing["part2"]) == 0


async def load_results_with_generation(
    results_dir: str = "res/",
    adata_path: str | None = None,
    cluster_key: str = "celltype_niche",
    organism: str = "human",
    force_regenerate: bool = False,
) -> dict[str, Any]:
    """Load results, generating missing analyses if needed.

    This function checks for missing files and invokes the appropriate
    tools to generate them. Part 1 analyses are run in parallel,
    Part 2 analyses are run sequentially due to dependencies.

    Args:
        results_dir: Directory containing results files
        adata_path: Path to normalized adata (required for generation)
        cluster_key: Cluster column name (for generation)
        organism: Organism for databases (for generation)
        force_regenerate: If True, regenerate all analyses

    Returns:
        Dictionary with:
        - part1_results: Loaded Part 1 data
        - part2_results: Loaded Part 2 data
        - generated: List of successfully generated analyses
        - failed: List of failed analyses
    """
    import logging
    logger = logging.getLogger(__name__)

    missing = check_missing_files(results_dir)
    generated = []
    failed = []

    # Determine if generation is required
    require_generation = force_regenerate or (
        len(missing["part1"]) > 0 or len(missing["part2"]) > 0
    )

    # If no adata_path, can't generate - just load what exists
    if not adata_path:
        logger.warning("No adata_path provided, skipping generation of missing analyses")
        part1_results, part2_results = await load_all_results(results_dir)
        return {
            "part1_results": part1_results,
            "part2_results": part2_results,
            "generated": [],
            "failed": [],
            "missing": missing,
        }

    # If force_regenerate, treat all as missing
    if force_regenerate:
        missing = {
            "part1": ["spatial", "celltype", "nhood", "decoupler", "misty"],
            "part2": ["morans", "nmf_factors", "pathway_factor", "ctsvg"],
            "part3": [],  # Part 3 requires agent input
        }

    # Generate missing Part 1 analyses (can run in parallel)
    if missing["part1"]:
        logger.info(f"Generating Part 1 analyses: {missing['part1']}")
        part1_results_gen = await _generate_part1_analyses(
            missing["part1"],
            adata_path=adata_path,
            cluster_key=cluster_key,
            organism=organism,
            results_dir=results_dir,
        )
        generated.extend(part1_results_gen["generated"])
        failed.extend(part1_results_gen["failed"])

    # Generate missing Part 2 analyses (must run sequentially)
    if missing["part2"]:
        logger.info(f"Generating Part 2 analyses: {missing['part2']}")
        part2_results_gen = await _generate_part2_analyses(
            missing["part2"],
            adata_path=adata_path,
            cluster_key=cluster_key,
            organism=organism,
            results_dir=results_dir,
        )
        generated.extend(part2_results_gen["generated"])
        failed.extend(part2_results_gen["failed"])

    # Reload all results after generation
    part1_results, part2_results = await load_all_results(results_dir)

    return {
        "part1_results": part1_results,
        "part2_results": part2_results,
        "generated": generated,
        "failed": failed,
        "missing": check_missing_files(results_dir),  # Recheck after generation
    }


async def _generate_part1_analyses(
    missing_analyses: list[str],
    adata_path: str,
    cluster_key: str,
    organism: str,
    results_dir: str,
) -> dict[str, list]:
    """Generate missing Part 1 analyses.

    Part 1 analyses can run in parallel as they only depend on n_adata.h5ad.
    """
    import logging
    logger = logging.getLogger(__name__)

    from src.agents.interpreter.tools.part1_tools import (
        tool_run_spatial_plot,
        tool_run_celltype_analysis,
        tool_run_neighborhood_enrichment,
        tool_run_pathway_enrichment,
        tool_run_misty_analysis,
    )

    tool_map = {
        "spatial": tool_run_spatial_plot,
        "celltype": tool_run_celltype_analysis,
        "nhood": tool_run_neighborhood_enrichment,
        "decoupler": tool_run_pathway_enrichment,
        "misty": tool_run_misty_analysis,
    }

    generated = []
    failed = []

    for analysis in missing_analyses:
        if analysis not in tool_map:
            logger.warning(f"Unknown Part 1 analysis: {analysis}")
            continue

        tool = tool_map[analysis]
        logger.info(f"Running Part 1 analysis: {analysis}")

        try:
            # Build parameters based on tool requirements
            params = {
                "adata_path": adata_path,
                "cluster_key": cluster_key,
                "results_dir": results_dir,
            }

            # Add organism for pathway/misty tools
            if analysis in ["decoupler", "misty"]:
                params["organism"] = organism

            # Invoke the tool
            result = tool.invoke(params)

            if result.get("success", False):
                generated.append({
                    "analysis": analysis,
                    "step": result.get("step"),
                    "output_files": result.get("output_files", []),
                })
                logger.info(f"Part 1 analysis {analysis} completed successfully")
            else:
                failed.append({
                    "analysis": analysis,
                    "step": result.get("step"),
                    "error": result.get("error", "Unknown error"),
                    "skipped": result.get("skipped", False),
                })
                logger.warning(f"Part 1 analysis {analysis} failed: {result.get('error')}")

        except Exception as e:
            failed.append({
                "analysis": analysis,
                "error": str(e),
                "skipped": True,
            })
            logger.error(f"Part 1 analysis {analysis} exception: {e}")

    return {"generated": generated, "failed": failed}


async def _generate_part2_analyses(
    missing_analyses: list[str],
    adata_path: str,
    cluster_key: str,
    organism: str,
    results_dir: str,
) -> dict[str, list]:
    """Generate missing Part 2 analyses.

    Part 2 analyses must run sequentially due to dependencies:
    Step 6 (LIANA) -> Step 7 (Factor) -> Step 8 (Loadings) -> Step 9 (ctSVG)
    """
    import logging
    import os
    logger = logging.getLogger(__name__)

    from src.agents.interpreter.tools.part2_tools import (
        tool_run_liana_cci,
        tool_run_factor_score,
        tool_run_lr_loadings,
        tool_run_quadrant_analysis,
    )

    generated = []
    failed = []
    lrdata_path = os.path.join(results_dir, "lrdata.h5ad")

    # Order matters for Part 2
    analysis_order = ["morans", "nmf_factors", "pathway_factor", "ctsvg"]

    for analysis in analysis_order:
        if analysis not in missing_analyses:
            continue

        logger.info(f"Running Part 2 analysis: {analysis}")

        try:
            if analysis == "morans":
                # Step 6: LIANA CCI - creates lrdata.h5ad
                result = tool_run_liana_cci.invoke({
                    "adata_path": adata_path,
                    "cluster_key": cluster_key,
                    "organism": organism,
                    "results_dir": results_dir,
                })

            elif analysis == "nmf_factors":
                # Step 7: Factor score - requires lrdata.h5ad
                if not os.path.exists(lrdata_path):
                    failed.append({
                        "analysis": analysis,
                        "step": 7,
                        "error": "lrdata.h5ad not found. Run Step 6 first.",
                        "skipped": True,
                    })
                    continue

                result = tool_run_factor_score.invoke({
                    "lrdata_path": lrdata_path,
                    "cluster_key": cluster_key,
                    "results_dir": results_dir,
                })

            elif analysis == "pathway_factor":
                # Step 8: LR Loadings - requires lrdata.h5ad
                if not os.path.exists(lrdata_path):
                    failed.append({
                        "analysis": analysis,
                        "step": 8,
                        "error": "lrdata.h5ad not found. Run Step 6 first.",
                        "skipped": True,
                    })
                    continue

                result = tool_run_lr_loadings.invoke({
                    "lrdata_path": lrdata_path,
                    "organism": organism,
                    "results_dir": results_dir,
                })

            elif analysis == "ctsvg":
                # Step 9: Quadrant analysis - requires sig_liana.csv and agent input
                # NOTE: This step requires interest_celltypes and sel_factor from agent
                # For now, skip this in auto-generation - it will be done by agent
                logger.info("Step 9 (ctsvg) requires agent input - skipping auto-generation")
                failed.append({
                    "analysis": analysis,
                    "step": 9,
                    "error": "Step 9 requires agent to select celltypes and factor",
                    "skipped": True,
                    "requires_agent_input": True,
                })
                continue

            else:
                continue

            if result.get("success", False):
                generated.append({
                    "analysis": analysis,
                    "step": result.get("step"),
                    "output_files": result.get("output_files", []),
                })
                logger.info(f"Part 2 analysis {analysis} completed successfully")
            else:
                failed.append({
                    "analysis": analysis,
                    "step": result.get("step"),
                    "error": result.get("error", "Unknown error"),
                    "skipped": result.get("skipped", False),
                })
                logger.warning(f"Part 2 analysis {analysis} failed: {result.get('error')}")

        except Exception as e:
            failed.append({
                "analysis": analysis,
                "error": str(e),
                "skipped": True,
            })
            logger.error(f"Part 2 analysis {analysis} exception: {e}")

    return {"generated": generated, "failed": failed}


def get_generation_order(missing: dict[str, list[str]]) -> list[dict[str, Any]]:
    """Determine the order for generating missing analyses.

    Respects dependencies:
    - Part 1 analyses can run in parallel
    - Part 2 analyses must run sequentially (6 -> 7 -> 8 -> 9)
    - Part 3 analyses require agent's LR pair selections

    Args:
        missing: Dict of missing analyses by part

    Returns:
        List of generation tasks with tool names and parameters
    """
    tasks = []

    # Part 1 tasks (can run in parallel)
    part1_tool_map = {
        "spatial": "tool_run_spatial_plot",
        "celltype": "tool_run_celltype_analysis",
        "nhood": "tool_run_neighborhood_enrichment",
        "decoupler": "tool_run_pathway_enrichment",
        "misty": "tool_run_misty_analysis",
    }

    for analysis in missing.get("part1", []):
        if analysis in part1_tool_map:
            tasks.append({
                "part": 1,
                "analysis": analysis,
                "tool": part1_tool_map[analysis],
                "parallel": True,
                "step": ["spatial", "celltype", "nhood", "decoupler", "misty"].index(analysis) + 1,
            })

    # Part 2 tasks (must run sequentially)
    part2_tool_map = {
        "morans": ("tool_run_liana_cci", 6),
        "nmf_factors": ("tool_run_factor_score", 7),
        "pathway_factor": ("tool_run_lr_loadings", 8),
        "ctsvg": ("tool_run_quadrant_analysis", 9),
    }

    # Sort by step order
    part2_missing = [a for a in ["morans", "nmf_factors", "pathway_factor", "ctsvg"]
                     if a in missing.get("part2", [])]

    for analysis in part2_missing:
        if analysis in part2_tool_map:
            tool_name, step = part2_tool_map[analysis]
            tasks.append({
                "part": 2,
                "analysis": analysis,
                "tool": tool_name,
                "parallel": False,
                "step": step,
                "dependencies": [t["tool"] for t in tasks if t["part"] == 2],
            })

    # Part 3 tasks are generated dynamically by agent
    for analysis in missing.get("part3", []):
        tasks.append({
            "part": 3,
            "analysis": analysis,
            "tool": "tool_run_lr_spatial_plot" if analysis == "spatial_lr" else "tool_run_lr_cluster_analysis",
            "parallel": True,
            "step": 10 if analysis == "spatial_lr" else 11,
            "requires_agent_input": True,
            "note": "Requires agent to select LR pairs first",
        })

    return sorted(tasks, key=lambda x: x["step"])
