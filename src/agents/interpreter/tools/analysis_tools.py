"""Base schemas and utilities for analysis tools.

This module provides:
- Pydantic input schemas for tool validation
- File checking utilities for auto-detection
- Tool aggregation functions
"""

import os
from pathlib import Path
from typing import Optional, Literal

from pydantic import BaseModel, Field


# =============================================================================
# Input Schemas
# =============================================================================

class Part1AnalysisInput(BaseModel):
    """Input schema for Part 1 analysis tools.

    Part 1 analyses all use normalized adata (n_adata.h5ad) and can run in parallel.
    """
    adata_path: str = Field(
        description="Path to normalized adata (n_adata.h5ad)"
    )
    cluster_key: str = Field(
        default="celltype_niche",
        description="Column name in adata.obs for cluster annotations"
    )
    results_dir: str = Field(
        default="res/",
        description="Output directory for saving results"
    )
    organism: Literal['human', 'mouse'] = Field(
        default='human',
        description="Organism for pathway databases"
    )


class Part2AnalysisInput(BaseModel):
    """Input schema for Part 2 analysis tools.

    Part 2 analyses require sequential execution with dependencies.
    """
    adata_path: str = Field(
        description="Path to normalized adata (n_adata.h5ad)"
    )
    lrdata_path: Optional[str] = Field(
        default=None,
        description="Path to lrdata.h5ad (generated if None)"
    )
    cluster_key: str = Field(
        default="celltype_niche",
        description="Column name in adata.obs for cluster annotations"
    )
    results_dir: str = Field(
        default="res/",
        description="Output directory for saving results"
    )
    organism: Literal['human', 'mouse'] = Field(
        default='human',
        description="Organism for LR database selection"
    )
    n_perms: int = Field(
        default=1000,
        description="Number of permutations for Moran's R significance testing"
    )


class Part3AnalysisInput(BaseModel):
    """Input schema for Part 3 analysis tools.

    Part 3 analyses are generated dynamically after agent selects LR pairs.
    """
    lrdata_path: str = Field(
        description="Path to lrdata.h5ad"
    )
    sel_interactions: list[str] = Field(
        description="Selected LR pair names (e.g., ['TGFB1_TGFBR1', 'VEGFA_FLT1'])"
    )
    cluster_key: str = Field(
        default="celltype_niche",
        description="Column name in lrdata.obs for cluster annotations"
    )
    results_dir: str = Field(
        default="res/",
        description="Output directory for saving results"
    )


# =============================================================================
# File Mapping Constants
# =============================================================================

# Part 1 expected files
PART1_FILES = {
    "spatial": {
        "figure": "1.spatial.png",
        "data": None,
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

# Part 2 expected files
PART2_FILES = {
    "liana": {
        "figure": "6.liana_MoransR.png",
        "data": "lrdata.h5ad",
        "csv": "sig_liana.csv",
    },
    "factor": {
        "figure": "7.factor_spatial_NMF.png",
        "data": "res_liana_cluster_factor.csv",
    },
    "loadings": {
        "figure": "8.pathway_factor_heatmap.png",
        "data": "sig_liana_pathway_factor.csv",
    },
    "quadrant": {
        "figure": "9.quadrant_analysis.png",
        "data": "interest_anno_sig_liana.csv",
    },
}

# Part 3 expected files
PART3_FILES = {
    "spatial_lr": {
        "figure": "10.spatial_plot_interections.png",
        "data": None,
    },
    "lr_summary": {
        "figure": "11.lr_interections.png",
        "data": None,
    },
}


# =============================================================================
# File Checking Utilities
# =============================================================================

def check_file_exists(results_dir: str, filename: str) -> bool:
    """Check if a file exists in the results directory."""
    if filename is None:
        return True  # No file expected
    filepath = Path(results_dir) / filename
    return filepath.exists()


def check_missing_files(results_dir: str) -> dict[str, list[str]]:
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
    for analysis_name, files in PART1_FILES.items():
        for file_type, filename in files.items():
            if filename and not check_file_exists(results_dir, filename):
                if analysis_name not in missing["part1"]:
                    missing["part1"].append(analysis_name)
                break

    # Check Part 2 files
    for analysis_name, files in PART2_FILES.items():
        for file_type, filename in files.items():
            if filename and not check_file_exists(results_dir, filename):
                if analysis_name not in missing["part2"]:
                    missing["part2"].append(analysis_name)
                break

    # Check Part 3 files
    for analysis_name, files in PART3_FILES.items():
        for file_type, filename in files.items():
            if filename and not check_file_exists(results_dir, filename):
                if analysis_name not in missing["part3"]:
                    missing["part3"].append(analysis_name)
                break

    return missing


def get_missing_files_summary(results_dir: str) -> str:
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


# =============================================================================
# Tool Aggregation Functions
# =============================================================================

def get_part1_tools() -> list:
    """Get list of Part 1 analysis tools."""
    from .part1_tools import (
        tool_run_spatial_plot,
        tool_run_celltype_analysis,
        tool_run_neighborhood_enrichment,
        tool_run_pathway_enrichment,
        tool_run_misty_analysis,
    )
    return [
        tool_run_spatial_plot,
        tool_run_celltype_analysis,
        tool_run_neighborhood_enrichment,
        tool_run_pathway_enrichment,
        tool_run_misty_analysis,
    ]


def get_part2_tools() -> list:
    """Get list of Part 2 analysis tools."""
    from .part2_tools import (
        tool_run_liana_cci,
        tool_run_factor_score,
        tool_run_lr_loadings,
        tool_run_quadrant_analysis,
    )
    return [
        tool_run_liana_cci,
        tool_run_factor_score,
        tool_run_lr_loadings,
        tool_run_quadrant_analysis,
    ]


def get_part3_tools() -> list:
    """Get list of Part 3 analysis tools."""
    from .part3_tools import (
        tool_run_lr_spatial_plot,
        tool_run_lr_cluster_analysis,
    )
    return [
        tool_run_lr_spatial_plot,
        tool_run_lr_cluster_analysis,
    ]


def get_all_tools() -> list:
    """Get all analysis tools combined."""
    return get_part1_tools() + get_part2_tools() + get_part3_tools()
