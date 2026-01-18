"""Analysis generation tools for Biological Interpreter Agent.

This module provides LangGraph Tools for generating CCI analysis results
when pre-computed files are missing.

Tool Categories:
- Part 1 Tools (can run in parallel): 5 tools for basic spatial analysis
- Part 2 Tools (must run sequentially): 4 tools for CCI analysis
- Part 3 Tools (agent dynamic): 2 tools for LR pair visualization
"""

from .part1_tools import (
    tool_run_spatial_plot,
    tool_run_celltype_analysis,
    tool_run_neighborhood_enrichment,
    tool_run_pathway_enrichment,
    tool_run_misty_analysis,
)

from .part2_tools import (
    tool_run_liana_cci,
    tool_run_factor_score,
    tool_run_lr_loadings,
    tool_run_quadrant_analysis,
)

from .part3_tools import (
    tool_run_lr_spatial_plot,
    tool_run_lr_cluster_analysis,
)

from .analysis_tools import (
    Part1AnalysisInput,
    Part2AnalysisInput,
    Part3AnalysisInput,
    check_missing_files,
    get_missing_files_summary,
    get_all_tools,
    get_part1_tools,
    get_part2_tools,
    get_part3_tools,
)

__all__ = [
    # Part 1 Tools
    "tool_run_spatial_plot",
    "tool_run_celltype_analysis",
    "tool_run_neighborhood_enrichment",
    "tool_run_pathway_enrichment",
    "tool_run_misty_analysis",
    # Part 2 Tools
    "tool_run_liana_cci",
    "tool_run_factor_score",
    "tool_run_lr_loadings",
    "tool_run_quadrant_analysis",
    # Part 3 Tools
    "tool_run_lr_spatial_plot",
    "tool_run_lr_cluster_analysis",
    # Utilities
    "Part1AnalysisInput",
    "Part2AnalysisInput",
    "Part3AnalysisInput",
    "check_missing_files",
    "get_missing_files_summary",
    "get_all_tools",
    "get_part1_tools",
    "get_part2_tools",
    "get_part3_tools",
]
