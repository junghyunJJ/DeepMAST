"""Tools for Deep Interpreter Agent.

This module re-exports all tools from the tools/ directory.
It serves as the main entry point for tool imports.
"""

# Import all tools from the tools/ directory
from src.agents.deep_interpreter.tools import (
    # Think tool
    think_tool,
    # Data loader
    load_analysis_data,
    get_figure_path,
    get_data_path,
    load_csv_data,
    get_recommended_targets,
    ANALYSIS_FILES,
    # Literature
    search_literature,
    search_literature_for_context,
    search_literature_async,
    search_literature_for_context_async,
    format_references,
    # Quality
    validate_quality,
    validate_claim_literature,
    get_improvement_suggestions,
    get_claim_validation_summary,
    QUALITY_CRITERIA,
    # Report
    generate_html_report,
    generate_simple_report,
)


# Export all tools
__all__ = [
    # Think tool
    "think_tool",
    # Data loader
    "load_analysis_data",
    "get_figure_path",
    "get_data_path",
    "load_csv_data",
    "get_recommended_targets",
    "ANALYSIS_FILES",
    # Literature
    "search_literature",
    "search_literature_for_context",
    "search_literature_async",
    "search_literature_for_context_async",
    "format_references",
    # Quality
    "validate_quality",
    "validate_claim_literature",
    "get_improvement_suggestions",
    "get_claim_validation_summary",
    "QUALITY_CRITERIA",
    # Report
    "generate_html_report",
    "generate_simple_report",
]
