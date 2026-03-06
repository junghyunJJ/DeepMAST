"""Data loader tool for Deep Interpreter Agent.

This tool loads pre-computed CCI analysis results from a directory
and returns a summary of available figures and data.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


# Analysis file mapping - matches actual filenames in res/ directory
ANALYSIS_FILES = {
    # Part 1: Spatial & Pathway
    "1_1_spatial": {
        "figure": "1.cluster_spatial.png",
        "display_name": "1-1 Spatial Clustering",
        "description": "Spatial distribution of clusters",
    },
    "1_2_celltype": {
        "figure": "2.celltype_heatmap_analysis.png",
        "data": "sig_clusterwithcelltyp.csv",
        "display_name": "1-2 Cell Type Composition",
        "description": "Cell type composition by cluster",
    },
    "1_3_nhood": {
        "figure": "3.neighborhood_enrichment_squidpy.png",
        "data": "res_nhood_enrichment.csv",
        "display_name": "1-3 Neighborhood Enrichment",
        "description": "Neighborhood enrichment analysis",
    },
    "1_4_decoupler": {
        "figure": "4.spatial_enrich_decoupler.png",
        "data": "sig_PathwayEnrich_decoupler.csv",
        "display_name": "1-4 Decoupler Pathway",
        "description": "Spatial pathway enrichment (Decoupler)",
    },
    "1_5_misty": {
        "figure": "5.spatial_relation_MISTy.png",
        "data": "res_SpatialRelationship_MISTy.csv",
        "display_name": "1-5 MISTy",
        "description": "Pathway-celltype relationship (MISTy)",
    },
    # Part 2: CCI & NMF
    "2_6_morans": {
        "figure": "6.liana_MoransR.png",
        "data": "sig_liana.csv",
        "display_name": "2-6 LIANA Moran's R",
        "description": "LIANA Moran's R analysis",
    },
    "2_7_nmf": {
        "figure": "7.factor_spatial_NMF.png",
        "data": "res_liana_cluster_factor.csv",
        "display_name": "2-7 NMF Factor",
        "description": "NMF factor spatial distribution",
    },
    "2_8_pathway_factor": {
        "figure": "8.pathway_factor_heatmap.png",
        "data": "sig_liana_pathway_factor.csv",
        "display_name": "2-8 Pathway-Factor",
        "description": "Pathway-factor enrichment",
    },
    "3_9_quadrant_genept": {
        "figure": "9.quadrant_analysis.png",
        "data": "interest_sig_liana.csv",
        "display_name": "3-9 NMF Quadrant + GenePT",
        "description": "NMF Quadrant + GenePT analysis",
    },
    # Part 3: L-R Interactions
    "3_10_spatial_lr": {
        "figure": "10.spatial_plot_interections.png",
        "display_name": "3-10 Spatial L-R",
        "description": "Spatial L-R expression patterns",
    },
    "3_11_lr_summary": {
        "figure": "11.lr_interections.png",
        "data": "sel_interest_sig_liana.csv",
        "display_name": "3-11 L-R Summary",
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

    data_path = Path(data_dir).expanduser().resolve()
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

    **NOTE**: /data_path.txt is pre-written automatically by the agent framework.
    Subagents can read it via read_file("/data_path.txt") without any manual write.

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
    data_path = Path(data_dir).expanduser().resolve()

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
    LIANA_FILES = {"sig_liana.csv", "sel_interest_sig_liana.csv", "interest_sig_liana.csv"}

    for analysis_name, file_config in ANALYSIS_FILES.items():
        figure_path = data_path / file_config["figure"]
        has_figure = figure_path.exists()

        has_data = True
        data_path_str = None
        if "data" in file_config:
            data_file = data_path / file_config["data"]
            has_data = data_file.exists()
            if has_data:
                data_path_str = str(data_file)
                # Extract clusters and celltypes from CSV files
                # Only extract genes from LIANA files (which have ligand/receptor columns)
                extract_genes = file_config["data"] in LIANA_FILES
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
        display = ANALYSIS_FILES[name].get("display_name", name)
        desc = ANALYSIS_FILES[name]["description"]
        summary_lines.append(f"  {status} {display}: {desc}")

    summary_lines.append("")
    summary_lines.append("Part 2 - CCI & NMF:")

    for name in ["2_6_morans", "2_7_nmf", "2_8_pathway_factor"]:
        status = "[OK]" if name in available_analyses else "[MISSING]"
        display = ANALYSIS_FILES[name].get("display_name", name)
        desc = ANALYSIS_FILES[name]["description"]
        summary_lines.append(f"  {status} {display}: {desc}")

    summary_lines.append("")
    summary_lines.append("Part 3 - L-R Interactions:")

    for name in ["3_9_quadrant_genept", "3_10_spatial_lr", "3_11_lr_summary"]:
        status = "[OK]" if name in available_analyses else "[MISSING]"
        display = ANALYSIS_FILES[name].get("display_name", name)
        desc = ANALYSIS_FILES[name]["description"]
        summary_lines.append(f"  {status} {display}: {desc}")

    # Get recommended targets for auto-selection
    recommendations = get_recommended_targets(data_dir)

    # Extract unified search context for subagents (prevents CSV context overflow)
    # Single context used by ALL parts: genes + pathways + celltypes
    # lr_interaction type is a superset of spatial (adds genes), so one search covers all parts
    search_context_for_search = _extract_search_context(data_path, context_type="lr_interaction")

    # --- Pre-compute lr_candidates and augment gene list ---
    # prioritize_top_lr_pairs reads CSV + optional top_search_genes.json
    # If top_search_genes.json is missing, prioritizer skips novelty exclusion
    try:
        from src.agents.deep_interpreter.tools.lr_prioritizer import prioritize_top_lr_pairs
        lr_result_json = prioritize_top_lr_pairs.invoke(
            {"data_dir": str(data_path), "candidate_count": 30}
        )
        lr_result = json.loads(lr_result_json)                    # FIX #1: use module-level json
        candidate_pairs = lr_result.get("pairs", [])

        # Extract novel genes from candidate pairs
        # Complex receptor names in LIANA use underscore (e.g., ITGA2_ITGB1)
        # Split to get individual gene symbols for search coverage
        candidate_genes = set()
        for pair in candidate_pairs:
            for gene_key in ("ligand", "receptor"):
                gene = pair.get(gene_key, "")
                if gene:
                    for g in gene.split("_"):
                        if g:
                            candidate_genes.add(g)

        # Augment search_context_for_search genes with novel candidate genes
        existing_genes_list = search_context_for_search.get("genes", [])  # FIX #2: preserve order
        existing_genes_set = set(existing_genes_list)
        novel_genes = sorted(candidate_genes - existing_genes_set)
        if novel_genes:
            search_context_for_search["genes"] = existing_genes_list + novel_genes  # FIX #2
            search_context_for_search["candidate_genes"] = novel_genes
            search_context_for_search["stats"]["search_genes"] = len(search_context_for_search["genes"])  # FIX #3
            search_context_for_search["note"] = (                         # FIX #4: append
                search_context_for_search.get("note", "") + " | "
                f"Augmented with {len(novel_genes)} novel genes from lr_candidates. "
                f"Total: {len(search_context_for_search['genes'])} genes."
            )
            logger.info(
                f"Augmented search genes: {len(existing_genes_list)} hub + "
                f"{len(novel_genes)} novel = {len(search_context_for_search['genes'])} total"
            )
    except Exception as e:
        logger.warning(f"lr_candidates pre-computation skipped: {e}")
        # Non-critical: SEARCHER proceeds with original top-30 genes

    # Load target_assessment.json if it exists (generated by wrapper Step 9.5)
    target_assessment = None
    target_assessment_status = "missing"  # "missing" | "parse_error" | "loaded"
    target_assessment_path = data_path / "target_assessment.json"
    if target_assessment_path.exists():
        try:
            with open(target_assessment_path) as f:
                target_assessment = json.load(f)
            target_assessment_status = "loaded"
            logger.info("Loaded target_assessment.json with %d matrix entries",
                        len(target_assessment.get("druggability_matrix", [])))
        except Exception as e:
            target_assessment_status = "parse_error"
            logger.warning(f"Failed to parse target_assessment.json: {e}")

    return {
        "data_dir": str(data_path),
        "available_analyses": available_analyses,
        "figures": figures,
        "data": data_files,
        "missing_analyses": missing_analyses,
        "display_names": {
            name: ANALYSIS_FILES[name].get("display_name", name)
            for name in available_analyses
        },
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
        # Unified search context for ALL parts (genes + pathways + celltypes)
        # lr_interaction context is a superset of spatial (adds genes to pathways+celltypes)
        # Single search covers all 3 parts, eliminating redundant API calls
        "search_context": search_context_for_search,
        # Target assessment from drug_target pipeline (Step 9.5, if available)
        "target_assessment": target_assessment,
        "target_assessment_status": target_assessment_status,
        # Informational: /data_path.txt is pre-written by the agent framework.
        "_DATA_PATH_INFO": {
            "data_path_txt": str(data_path),
            "note": "/data_path.txt is pre-written automatically. No manual write_file needed.",
        },
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
    figure_path = Path(data_dir).expanduser().resolve() / config["figure"]

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

    data_path = Path(data_dir).expanduser().resolve() / config["data"]

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


def _extract_search_context(data_path: Path, context_type: str = None) -> dict:
    """Extract biological terms from analysis files with context-type filtering.

    Uses interest_sig_liana.csv first (already filtered for significant interactions).
    Falls back to sig_liana.csv if interest file doesn't exist.

    Returns ~5KB instead of 571KB while preserving ALL important terms.
    This prevents context overflow when subagents try to read CSV files directly.

    Args:
        data_path: Path to the data directory
        context_type: Context type for extraction:
                     - "spatial": For Part 1 - pathways + celltypes only (NO genes)
                     - "lr_interaction": For Part 2 & 3 - genes + pathways + celltypes
                     - None: Returns combined context for all Parts (backward compatibility)

    Context-type logic:
        - spatial: Part 1 cluster/pathway/celltype level analysis (NO gene-level)
        - lr_interaction: Part 2 & 3 LIANA L-R interaction analysis (includes genes)

    Returns:
        Dictionary with genes, pathways, celltypes, source info, and stats.
    """
    import pandas as pd
    from collections import Counter

    genes = set()
    gene_counts = Counter()
    pathways = set()
    celltypes = set()

    # Priority: interest_sig_liana.csv (pre-filtered important pairs)
    liana_files = ['interest_sig_liana.csv', 'sig_liana.csv', 'sel_interest_sig_liana.csv']
    source_file = None
    liana_df = None

    for fname in liana_files:
        csv_path = data_path / fname
        if csv_path.exists():
            try:
                df = pd.read_csv(csv_path)

                # Extract ALL unique genes (not top N - preserve all important items)
                # Also count frequency for ranking
                for col in ['ligand', 'receptor']:
                    if col in df.columns:
                        genes.update(df[col].dropna().unique())
                        gene_counts.update(df[col].dropna().tolist())

                # Extract pathways from progeny column
                if 'progeny' in df.columns:
                    pathways.update(df['progeny'].dropna().unique())

                # Extract cell types from ctSVG columns
                for col in ['ligand_ctSVG', 'receptor_ctSVG']:
                    if col in df.columns:
                        for val in df[col].dropna():
                            celltypes.update([ct.strip() for ct in str(val).split(';') if ct.strip()])

                source_file = fname
                liana_df = df
                if fname == 'interest_sig_liana.csv':
                    break  # Use interest file if available (most filtered)
            except Exception:
                continue

    # Also extract pathways from decoupler results (Part 1 relevant)
    decoupler_path = data_path / 'sig_PathwayEnrich_decoupler.csv'
    if decoupler_path.exists():
        try:
            df_decoupler = pd.read_csv(decoupler_path)
            if 'name' in df_decoupler.columns:
                pathways.update(df_decoupler['name'].dropna().unique())
        except Exception:
            pass

    # Also extract cell types from celltype heatmap (Part 1 relevant)
    celltype_path = data_path / 'sig_clusterwithcelltyp.csv'
    if celltype_path.exists():
        try:
            df_celltype = pd.read_csv(celltype_path)
            for col in ['celltype', 'CellType', 'cell_type']:
                if col in df_celltype.columns:
                    celltypes.update(df_celltype[col].dropna().unique())
        except Exception:
            pass

    # Context-type filtering
    if context_type == "spatial":
        # Part 1: Spatial, Neighborhood, Decoupler, MISTy analyses
        # These are cluster/pathway/celltype level - NO gene-level analysis
        return {
            "genes": [],  # Part 1 has NO gene-level analysis
            "pathways": sorted(list(pathways)),
            "celltypes": sorted(list(celltypes)),
            "source": "Decoupler + MISTy pathways, cell type composition",
            "context_type": "spatial",
            "applicable_parts": [1],
            "note": "Part 1 analyzes clusters/pathways/celltypes, not individual genes. "
                    "Gene-level data (L-R pairs) is only available in Part 2/3 (LIANA analysis).",
            "stats": {
                "total_genes": 0,
                "total_pathways": len(pathways),
                "total_celltypes": len(celltypes),
            }
        }
    elif context_type == "lr_interaction":
        # Part 2 & 3: LIANA L-R analysis - includes genes
        # Use hybrid-ranked top N genes for effective search coverage
        MAX_SEARCH_GENES = 30
        all_genes_sorted = sorted(list(genes))
        top_gene_scores: list[float] = []
        score_method = "0.7*max_combinedscore_norm + 0.3*freq_norm"

        # Hybrid ranking: 0.7 × max_combinedscore_norm + 0.3 × freq_norm
        # combinedscore = 0.4×Factor + 0.4×Moran's R + 0.2×GenePT
        # freq_norm captures hub genes (appearing in many L-R pairs)
        if liana_df is not None and 'combinedscore' in liana_df.columns and gene_counts:
            # Step 1: max combinedscore per gene
            gene_max_scores = {}
            for col in ['ligand', 'receptor']:
                if col in liana_df.columns:
                    for _, row in liana_df[[col, 'combinedscore']].dropna().iterrows():
                        gene = row[col]
                        score = row['combinedscore']
                        gene_max_scores[gene] = max(gene_max_scores.get(gene, 0), score)

            # Step 2: normalize both signals to 0-1
            max_score = max(gene_max_scores.values()) if gene_max_scores else 1.0
            max_freq = gene_counts.most_common(1)[0][1] if gene_counts else 1

            # Step 3: compute hybrid score for each gene
            gene_hybrid = {}
            for gene in gene_max_scores:
                score_norm = gene_max_scores[gene] / max_score
                freq_norm = gene_counts.get(gene, 0) / max_freq
                gene_hybrid[gene] = 0.7 * score_norm + 0.3 * freq_norm

            ranked_genes = sorted(gene_hybrid.items(), key=lambda x: x[1], reverse=True)
            top_genes = [g for g, _ in ranked_genes[:MAX_SEARCH_GENES]]
            top_gene_scores = [float(score) for _, score in ranked_genes[:MAX_SEARCH_GENES]]
        elif gene_counts:
            # Fallback: frequency only (combinedscore column missing)
            ranked_genes = gene_counts.most_common(MAX_SEARCH_GENES)
            top_genes = [g for g, _ in ranked_genes]
            max_freq = ranked_genes[0][1] if ranked_genes else 1
            top_gene_scores = [float(freq / max_freq) for _, freq in ranked_genes] if max_freq else []
            score_method = "frequency_norm"
        else:
            top_genes = all_genes_sorted[:MAX_SEARCH_GENES]
            score_method = "alphabetical_fallback"

        # Persist top search genes for downstream use (e.g., LR pair novelty filtering)
        try:
            top_genes_file = data_path / "top_search_genes.json"
            top_genes_payload = {
                "version": 2,
                "genes": top_genes,
                "scores": top_gene_scores,
                "score_method": score_method,
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
            with open(top_genes_file, "w") as f:
                json.dump(top_genes_payload, f, indent=2)
        except Exception:
            pass  # Non-critical: prioritizer falls back to no exclusion

        return {
            "genes": top_genes,  # Top N by hybrid score for search
            "all_genes": all_genes_sorted,  # Full list for reference
            "pathways": sorted(list(pathways)),
            "celltypes": sorted(list(celltypes)),
            "source": source_file or "no LIANA files found",
            "context_type": "lr_interaction",
            "applicable_parts": [2, 3],
            "note": (
                f"Top {len(top_genes)} genes by hybrid score (0.7×max_combinedscore + 0.3×freq) from {source_file or 'LIANA files'}. "
                f"Full gene set: {len(all_genes_sorted)} unique genes. "
                "Use 'genes' for search, 'all_genes' for complete reference."
            ),
            "stats": {
                "total_genes": len(all_genes_sorted),
                "search_genes": len(top_genes),
                "total_pathways": len(pathways),
                "total_celltypes": len(celltypes),
            }
        }
    else:
        # Default: Combined context for all Parts (backward compatibility)
        return {
            "genes": sorted(list(genes)),           # ALL unique genes (~352)
            "pathways": sorted(list(pathways)),     # ALL unique pathways (~64)
            "celltypes": sorted(list(celltypes)),   # ALL unique cell types (~13)
            "source": source_file or "no LIANA files found",
            "context_type": "combined",
            "applicable_parts": [1, 2, 3],
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

    data_path = Path(data_dir).expanduser().resolve()
    gene_counts = Counter()

    # Priority: LIANA files contain actual L-R gene pairs
    liana_files = ['sig_liana.csv', 'sel_interest_sig_liana.csv', 'interest_sig_liana.csv']

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
