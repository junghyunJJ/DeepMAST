"""Biological Interpreter Agent module.

This module provides the Deep Agent for interpreting CCI analysis results
and generating comprehensive HTML reports with biological insights.

Also provides LangGraph tools for generating analysis results when needed.
"""

from src.agents.interpreter.biological_interpreter_agent import (
    BiologicalInterpreterAgent,
)
from src.agents.interpreter.biological_interpreter_state import (
    BiologicalInterpreterState,
    WeightConfiguration,
    LRPairScore,
    Claim,
    ReflectionResult,
    GeneratedAnalysis,
    DEFAULT_WEIGHT_CONFIG,
    create_initial_state,
)

# Analysis tools for generating results
from src.agents.interpreter.tools import (
    # Part 1 tools
    tool_run_spatial_plot,
    tool_run_celltype_analysis,
    tool_run_neighborhood_enrichment,
    tool_run_pathway_enrichment,
    tool_run_misty_analysis,
    # Part 2 tools
    tool_run_liana_cci,
    tool_run_factor_score,
    tool_run_lr_loadings,
    tool_run_quadrant_analysis,
    # Part 3 tools
    tool_run_lr_spatial_plot,
    tool_run_lr_cluster_analysis,
    # Tool aggregators
    get_part1_tools,
    get_part2_tools,
    get_part3_tools,
    get_all_tools,
    # Utilities
    check_missing_files,
    get_missing_files_summary,
)

__all__ = [
    # Agent
    "BiologicalInterpreterAgent",
    # State types
    "BiologicalInterpreterState",
    "WeightConfiguration",
    "LRPairScore",
    "Claim",
    "ReflectionResult",
    "GeneratedAnalysis",
    "DEFAULT_WEIGHT_CONFIG",
    "create_initial_state",
    # Part 1 tools
    "tool_run_spatial_plot",
    "tool_run_celltype_analysis",
    "tool_run_neighborhood_enrichment",
    "tool_run_pathway_enrichment",
    "tool_run_misty_analysis",
    # Part 2 tools
    "tool_run_liana_cci",
    "tool_run_factor_score",
    "tool_run_lr_loadings",
    "tool_run_quadrant_analysis",
    # Part 3 tools
    "tool_run_lr_spatial_plot",
    "tool_run_lr_cluster_analysis",
    # Tool aggregators
    "get_part1_tools",
    "get_part2_tools",
    "get_part3_tools",
    "get_all_tools",
    # Utilities
    "check_missing_files",
    "get_missing_files_summary",
]
