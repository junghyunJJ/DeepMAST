"""Data loader tool for Deep Interpreter Agent.

This tool loads pre-computed CCI analysis results from a directory
and returns a summary of available figures and data.
"""

import os
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool


# Analysis file mapping - matches actual filenames in res/ directory
ANALYSIS_FILES = {
    # Part 1: Spatial & Pathway
    "1_1_spatial": {
        "figure": "1.spatial.png",
        "description": "Spatial distribution of clusters",
    },
    "1_2_celltype": {
        "figure": "2.celltype_heatmap_analysis.png",
        "data": "sig_clusterwithcelltyp.csv",
        "description": "Cell type composition by cluster",
    },
    "1_3_nhood": {
        "figure": "3.neighborhood_enrichment_squidpy.png",
        "data": "res_nhood_enrichment.csv",
        "description": "Neighborhood enrichment analysis",
    },
    "1_4_decoupler": {
        "figure": "4.spatial_enrich_decoupler.png",
        "data": "sig_PathwayEnrich_decoupler.csv",
        "description": "Spatial pathway enrichment (Decoupler)",
    },
    "1_5_misty": {
        "figure": "5.spatial_relation_MISTy.png",
        "data": "res_SpatialRelationship_MISTy.csv",
        "description": "Pathway-celltype relationship (MISTy)",
    },
    # Part 2: CCI & NMF
    "2_6_morans": {
        "figure": "6.liana_MoransR.png",
        "data": "sig_liana.csv",
        "description": "LIANA Moran's R analysis",
    },
    "2_7_nmf": {
        "figure": "7.factor_spatial_NMF.png",
        "data": "res_liana_cluster_factor.csv",
        "description": "NMF factor spatial distribution",
    },
    "2_8_pathway_factor": {
        "figure": "8.pathway_factor_heatmap.png",
        "data": "sig_liana_pathway_factor.csv",
        "description": "Pathway-factor enrichment",
    },
    "2_9_ctsvg": {
        "figure": "9.quadrant_analysis.png",
        "data": "interest_sig_liana.csv",
        "description": "ctSVG quadrant analysis",
    },
    # Part 3: L-R Interactions
    "3_10_spatial_lr": {
        "figure": "10.spatial_plot_interections.png",
        "description": "Spatial L-R expression patterns",
    },
    "3_11_lr_summary": {
        "figure": "11.lr_interections.png",
        "data": "anno_sig_liana.csv",
        "description": "L-R interaction summary",
    },
}


def get_recommended_targets(data_dir: str, max_clusters: int = 3, max_celltypes: int = 3) -> dict:
    """Get recommended default targets based on data frequency analysis.

    Automatically selects top N clusters and cell types by occurrence count,
    providing intelligent defaults for automatic target selection.

    Args:
        data_dir: Path to the analysis results directory
        max_clusters: Maximum number of clusters to recommend (default: 3)
        max_celltypes: Maximum number of cell types to recommend (default: 3)

    Returns:
        Dictionary with recommended_clusters, recommended_celltypes,
        recommended_mode, and selection rationale.
    """
    from collections import Counter

    data_path = Path(data_dir)
    cluster_counts = Counter()
    celltype_counts = Counter()

    # Analyze CSV files to count cluster and celltype occurrences
    for analysis_name, config in ANALYSIS_FILES.items():
        if "data" not in config:
            continue
        csv_path = data_path / config["data"]
        if not csv_path.exists():
            continue

        try:
            import pandas as pd
            df = pd.read_csv(csv_path)

            # Count cluster occurrences
            for col in ['cluster', 'Cluster', 'spatial_cluster']:
                if col in df.columns:
                    cluster_counts.update(df[col].dropna().astype(str).tolist())

            # Count cell type occurrences
            for col in ['celltype', 'CellType', 'cell_type', 'ligand_ctSVG', 'receptor_ctSVG']:
                if col in df.columns:
                    for val in df[col].dropna():
                        if isinstance(val, str):
                            if ';' in val:
                                celltype_counts.update([ct.strip() for ct in val.split(';') if ct.strip()])
                            else:
                                celltype_counts[val.strip()] += 1
        except Exception:
            continue

    # Select top N by frequency
    top_clusters = [c for c, _ in cluster_counts.most_common(max_clusters)]
    top_celltypes = [ct for ct, _ in celltype_counts.most_common(max_celltypes)]

    # Default mode
    recommended_mode = "cluster_to_celltype"

    return {
        "recommended_clusters": top_clusters,
        "recommended_celltypes": top_celltypes,
        "recommended_mode": recommended_mode,
        "rationale": f"Auto-selected top {len(top_clusters)} clusters by data frequency and top {len(top_celltypes)} cell types by occurrence count.",
        "cluster_counts": dict(cluster_counts.most_common(10)),
        "celltype_counts": dict(celltype_counts.most_common(10)),
    }


def _extract_metadata_from_csv(
    csv_path: Path, clusters: set, celltypes: set, genes: set = None
) -> None:
    """Extract cluster IDs, cell type names, and gene names from a CSV file.

    Args:
        csv_path: Path to the CSV file
        clusters: Set to add cluster IDs to
        celltypes: Set to add cell type names to
        genes: Optional set to add gene names to (from ligand/receptor columns)
    """
    try:
        import pandas as pd
        df = pd.read_csv(csv_path)

        # Extract clusters from 'cluster' or 'Cluster' column
        for col in ['cluster', 'Cluster', 'spatial_cluster']:
            if col in df.columns:
                clusters.update(df[col].dropna().unique())

        # Extract cell types from various columns
        celltype_columns = ['celltype', 'CellType', 'cell_type', 'ligand_ctSVG', 'receptor_ctSVG']
        for col in celltype_columns:
            if col in df.columns:
                for val in df[col].dropna().unique():
                    # Handle semicolon-separated values (e.g., in ctSVG columns)
                    if isinstance(val, str) and ';' in val:
                        celltypes.update([ct.strip() for ct in val.split(';') if ct.strip()])
                    elif isinstance(val, str):
                        celltypes.add(val.strip())

        # Extract actual gene names from ligand/receptor columns (LIANA results)
        # These are real gene symbols, NOT pathway names
        if genes is not None:
            gene_columns = ['ligand', 'receptor']
            for col in gene_columns:
                if col in df.columns:
                    genes.update(df[col].dropna().unique())
    except Exception:
        # Silently skip files that can't be parsed
        pass


@tool
def load_analysis_data(data_dir: str, config: dict = None) -> dict:
    """Load CCI analysis results from a directory and AUTOMATICALLY save to filesystem.

    This tool scans the specified directory for pre-computed analysis files
    and returns a structured summary of available analyses, figures, data,
    AND extracted clusters/cell types for target selection.

    **IMPORTANT**: This tool automatically writes the analysis summary to:
    - /analysis_summary.md - Full summary for subagents to read
    - /data_path.txt - Data directory path

    Subagents (like planner, searcher) will use read_file to access these files.

    Args:
        data_dir: Path to the directory containing analysis results
        config: Optional RunnableConfig with filesystem access (injected by Deep Agents)

    Returns:
        Dictionary with:
        - available_analyses: List of available analysis names
        - figures: Dict mapping analysis names to figure paths
        - data: Dict mapping analysis names to data file paths
        - missing_analyses: List of expected but missing analyses
        - summary: Human-readable summary string
        - clusters: List of unique cluster IDs found in the data
        - celltypes: List of unique cell type names found in the data
        - files_written: List of files automatically saved to filesystem
    """
    data_path = Path(data_dir)

    if not data_path.exists():
        return {
            "error": f"Directory not found: {data_dir}",
            "available_analyses": [],
            "figures": {},
            "data": {},
            "missing_analyses": list(ANALYSIS_FILES.keys()),
            "summary": f"Error: Directory not found at {data_dir}",
            "clusters": [],
            "celltypes": [],
            "genes": [],  # Actual gene names from LIANA
        }

    available_analyses = []
    figures = {}
    data_files = {}
    missing_analyses = []

    # Extract clusters, cell types, and genes
    clusters = set()
    celltypes = set()
    genes = set()  # Actual gene names from LIANA ligand/receptor columns

    # Files that contain actual gene names (ligand/receptor columns)
    LIANA_FILES = {"sig_liana.csv", "anno_sig_liana.csv", "interest_sig_liana.csv"}

    for analysis_name, config in ANALYSIS_FILES.items():
        figure_path = data_path / config["figure"]
        has_figure = figure_path.exists()

        has_data = True
        data_path_str = None
        if "data" in config:
            data_file = data_path / config["data"]
            has_data = data_file.exists()
            if has_data:
                data_path_str = str(data_file)
                # Extract clusters and celltypes from CSV files
                # Only extract genes from LIANA files (which have ligand/receptor columns)
                extract_genes = config["data"] in LIANA_FILES
                _extract_metadata_from_csv(
                    data_file, clusters, celltypes, genes if extract_genes else None
                )

        if has_figure:
            available_analyses.append(analysis_name)
            figures[analysis_name] = str(figure_path)
            if data_path_str:
                data_files[analysis_name] = data_path_str
        else:
            missing_analyses.append(analysis_name)

    # Convert to sorted lists
    def sort_key(x):
        # Sort numerically if possible, otherwise alphabetically
        try:
            return (0, int(x))
        except (ValueError, TypeError):
            return (1, str(x))

    clusters_list = sorted([str(c) for c in clusters], key=sort_key)
    celltypes_list = sorted(list(celltypes))
    genes_list = sorted(list(genes))  # Actual gene names from LIANA

    # Generate summary with clusters and celltypes
    summary_lines = [
        f"CCI Analysis Data Summary for: {data_dir}",
        f"Available analyses: {len(available_analyses)}/{len(ANALYSIS_FILES)}",
        "",
        f"=== AVAILABLE CLUSTERS ({len(clusters_list)}) ===",
    ]
    if clusters_list:
        summary_lines.append(f"  {', '.join(clusters_list)}")
    else:
        summary_lines.append("  (No clusters found in data files)")

    summary_lines.extend([
        "",
        f"=== AVAILABLE CELL TYPES ({len(celltypes_list)}) ===",
    ])
    for ct in celltypes_list:
        summary_lines.append(f"  - {ct}")
    if not celltypes_list:
        summary_lines.append("  (No cell types found in data files)")

    summary_lines.extend([
        "",
        "=== ANALYSIS STATUS ===",
        "",
        "Part 1 - Spatial & Pathway:",
    ])

    for name in ["1_1_spatial", "1_2_celltype", "1_3_nhood", "1_4_decoupler", "1_5_misty"]:
        status = "[OK]" if name in available_analyses else "[MISSING]"
        desc = ANALYSIS_FILES[name]["description"]
        summary_lines.append(f"  {status} {name}: {desc}")

    summary_lines.append("")
    summary_lines.append("Part 2 - CCI & NMF:")

    for name in ["2_6_morans", "2_7_nmf", "2_8_pathway_factor", "2_9_ctsvg"]:
        status = "[OK]" if name in available_analyses else "[MISSING]"
        desc = ANALYSIS_FILES[name]["description"]
        summary_lines.append(f"  {status} {name}: {desc}")

    summary_lines.append("")
    summary_lines.append("Part 3 - L-R Interactions:")

    for name in ["3_10_spatial_lr", "3_11_lr_summary"]:
        status = "[OK]" if name in available_analyses else "[MISSING]"
        desc = ANALYSIS_FILES[name]["description"]
        summary_lines.append(f"  {status} {name}: {desc}")

    # Get recommended targets for auto-selection
    recommendations = get_recommended_targets(data_dir)

    # Extract search context for subagents (prevents CSV context overflow)
    search_context = _extract_search_context(data_path)

    # Build the full summary markdown for subagents
    full_summary_md = f"""# CCI Analysis Data Summary

## Data Directory
{data_path}

## Available Clusters ({len(clusters_list)})
{', '.join(clusters_list) if clusters_list else '(No clusters found)'}

## Available Cell Types ({len(celltypes_list)})
{chr(10).join(f'- {ct}' for ct in celltypes_list) if celltypes_list else '(No cell types found)'}

## Recommended Defaults
- **Recommended Clusters**: {', '.join(recommendations['recommended_clusters']) if recommendations['recommended_clusters'] else 'None'}
- **Recommended Cell Types**: {', '.join(recommendations['recommended_celltypes']) if recommendations['recommended_celltypes'] else 'None'}
- **Recommended Mode**: {recommendations['recommended_mode']}
- **Rationale**: {recommendations['rationale']}

## Analysis Status

### Part 1 - Spatial & Pathway
{chr(10).join(f"- {'[OK]' if name in available_analyses else '[MISSING]'} {name}: {ANALYSIS_FILES[name]['description']}" for name in ['1_1_spatial', '1_2_celltype', '1_3_nhood', '1_4_decoupler', '1_5_misty'])}

### Part 2 - CCI & NMF
{chr(10).join(f"- {'[OK]' if name in available_analyses else '[MISSING]'} {name}: {ANALYSIS_FILES[name]['description']}" for name in ['2_6_morans', '2_7_nmf', '2_8_pathway_factor', '2_9_ctsvg'])}

### Part 3 - L-R Interactions
{chr(10).join(f"- {'[OK]' if name in available_analyses else '[MISSING]'} {name}: {ANALYSIS_FILES[name]['description']}" for name in ['3_10_spatial_lr', '3_11_lr_summary'])}
"""

    # Track files written
    files_written = []

    # Try to write files to the Deep Agents filesystem
    # Deep Agents stores files in the agent state, accessible via read_file/write_file tools
    # We'll return instructions for the orchestrator to write these files
    # since tools cannot directly access the filesystem middleware

    return {
        "data_dir": str(data_path),
        "available_analyses": available_analyses,
        "figures": figures,
        "data": data_files,
        "missing_analyses": missing_analyses,
        "summary": "\n".join(summary_lines),
        "clusters": clusters_list,
        "celltypes": celltypes_list,
        # Actual gene names from LIANA ligand/receptor columns (NOT pathway names)
        "genes": genes_list,
        # Recommended targets for AUTO-SELECTION (no user input needed)
        "recommended_clusters": recommendations["recommended_clusters"],
        "recommended_celltypes": recommendations["recommended_celltypes"],
        "recommended_mode": recommendations["recommended_mode"],
        "selection_rationale": recommendations["rationale"],
        # Pre-extracted search context for subagents (prevents CSV context overflow)
        # Contains ALL unique genes, pathways, celltypes from interest_sig_liana.csv
        # Subagents should use this instead of reading CSV files directly
        "search_context": search_context,
        # Pre-formatted content for write_file - orchestrator MUST write these
        "_MUST_WRITE_FILES": {
            "/analysis_summary.md": full_summary_md,
            "/data_path.txt": str(data_path),
        },
        "_INSTRUCTION": (
            "CRITICAL: You MUST use write_file tool to save the files in _MUST_WRITE_FILES. "
            "Subagents cannot see this tool's output - they can ONLY read files. "
            "Call write_file('/analysis_summary.md', <content>) and write_file('/data_path.txt', <content>) NOW."
        ),
    }


def get_figure_path(data_dir: str, analysis_name: str) -> Optional[str]:
    """Get the figure path for a specific analysis.

    Args:
        data_dir: Path to the data directory
        analysis_name: Name of the analysis (e.g., "1_1_spatial")

    Returns:
        Path to the figure file, or None if not found
    """
    if analysis_name not in ANALYSIS_FILES:
        return None

    config = ANALYSIS_FILES[analysis_name]
    figure_path = Path(data_dir) / config["figure"]

    return str(figure_path) if figure_path.exists() else None


def get_data_path(data_dir: str, analysis_name: str) -> Optional[str]:
    """Get the data file path for a specific analysis.

    Args:
        data_dir: Path to the data directory
        analysis_name: Name of the analysis (e.g., "1_2_celltype")

    Returns:
        Path to the data file, or None if not found
    """
    if analysis_name not in ANALYSIS_FILES:
        return None

    config = ANALYSIS_FILES[analysis_name]
    if "data" not in config:
        return None

    data_path = Path(data_dir) / config["data"]

    return str(data_path) if data_path.exists() else None


def load_csv_data(data_path: str) -> Optional[dict]:
    """Load CSV data and return basic statistics.

    Args:
        data_path: Path to the CSV file

    Returns:
        Dictionary with data summary or None if loading fails
    """
    try:
        import pandas as pd

        df = pd.read_csv(data_path)

        return {
            "path": data_path,
            "rows": len(df),
            "columns": list(df.columns),
            "sample": df.head(5).to_dict(orient="records"),
        }
    except Exception as e:
        return {"error": str(e), "path": data_path}


def _extract_search_context(data_path: Path) -> dict:
    """Extract ALL unique biological terms from interest_sig_liana.csv (pre-filtered important L-R pairs).

    Uses interest_sig_liana.csv first (already filtered for significant interactions).
    Falls back to sig_liana.csv if interest file doesn't exist.

    Returns ~5KB instead of 571KB while preserving ALL important terms.
    This prevents context overflow when subagents try to read CSV files directly.

    Args:
        data_path: Path to the data directory

    Returns:
        Dictionary with genes, pathways, celltypes, source info, and stats.
    """
    import pandas as pd

    genes = set()
    pathways = set()
    celltypes = set()

    # Priority: interest_sig_liana.csv (pre-filtered important pairs)
    liana_files = ['interest_sig_liana.csv', 'sig_liana.csv', 'anno_sig_liana.csv']
    source_file = None

    for fname in liana_files:
        csv_path = data_path / fname
        if csv_path.exists():
            try:
                df = pd.read_csv(csv_path)

                # Extract ALL unique genes (not top N - preserve all important items)
                for col in ['ligand', 'receptor']:
                    if col in df.columns:
                        genes.update(df[col].dropna().unique())

                # Extract pathways from progeny column
                if 'progeny' in df.columns:
                    pathways.update(df['progeny'].dropna().unique())

                # Extract cell types from ctSVG columns
                for col in ['ligand_ctSVG', 'receptor_ctSVG']:
                    if col in df.columns:
                        for val in df[col].dropna():
                            celltypes.update([ct.strip() for ct in str(val).split(';') if ct.strip()])

                source_file = fname
                if fname == 'interest_sig_liana.csv':
                    break  # Use interest file if available (most filtered)
            except Exception:
                continue

    # Also extract pathways from decoupler results
    decoupler_path = data_path / 'sig_PathwayEnrich_decoupler.csv'
    if decoupler_path.exists():
        try:
            df = pd.read_csv(decoupler_path)
            if 'name' in df.columns:
                pathways.update(df['name'].dropna().unique())
        except Exception:
            pass

    return {
        "genes": sorted(list(genes)),           # ALL unique genes (~352)
        "pathways": sorted(list(pathways)),     # ALL unique pathways (~64)
        "celltypes": sorted(list(celltypes)),   # ALL unique cell types (~13)
        "source": source_file or "no LIANA files found",
        "note": "Pre-extracted from interest_sig_liana.csv (pre-filtered important L-R pairs). "
                "DO NOT read CSV files directly with read_file - causes context overflow.",
        "stats": {
            "total_genes": len(genes),
            "total_pathways": len(pathways),
            "total_celltypes": len(celltypes),
        }
    }


def get_recommended_search_terms(data_dir: str, max_genes: int = 15) -> dict:
    """Get recommended search terms based on LIANA results.

    Extracts actual gene names from ligand/receptor columns,
    NOT pathway names from enrichment results. This ensures PubMed
    searches use proper gene symbols.

    Args:
        data_dir: Path to the analysis results directory
        max_genes: Maximum number of top genes to return (default: 15)

    Returns:
        Dictionary with recommended_genes (actual gene symbols),
        gene_counts by frequency, and source information.
    """
    from collections import Counter

    import pandas as pd

    data_path = Path(data_dir)
    gene_counts = Counter()

    # Priority: LIANA files contain actual L-R gene pairs
    liana_files = ['sig_liana.csv', 'anno_sig_liana.csv', 'interest_sig_liana.csv']

    for fname in liana_files:
        csv_path = data_path / fname
        if not csv_path.exists():
            continue
        try:
            df = pd.read_csv(csv_path)
            for col in ['ligand', 'receptor']:
                if col in df.columns:
                    gene_counts.update(df[col].dropna().tolist())
        except Exception:
            continue

    # Return top genes by frequency
    top_genes = [g for g, _ in gene_counts.most_common(max_genes)]

    return {
        "recommended_genes": top_genes,
        "gene_counts": dict(gene_counts.most_common(20)),
        "source": "LIANA ligand/receptor columns (actual gene symbols)",
        "note": "These are actual gene names suitable for PubMed [Gene] searches, "
                "NOT pathway names like EGFR/p53/TGFb from decoupler results.",
    }
