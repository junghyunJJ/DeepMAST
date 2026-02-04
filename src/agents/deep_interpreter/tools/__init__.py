"""Tools for Deep Interpreter Agent.

These tools are used by the main agent and subagents for CCI analysis interpretation.
"""

from src.agents.deep_interpreter.tools.data_loader import (
    load_analysis_data,
    get_figure_path,
    get_data_path,
    load_csv_data,
    get_recommended_targets,
    ANALYSIS_FILES,
)
from src.agents.deep_interpreter.tools.literature import (
    search_literature,
    search_literature_for_context,
    search_literature_dynamic,
    search_literature_async,
    search_literature_for_context_async,
    search_literature_dynamic_async,
    format_references,
)
from src.agents.deep_interpreter.tools.quality import (
    validate_quality,
    validate_claim_literature,
    get_improvement_suggestions,
    get_claim_validation_summary,
    QUALITY_CRITERIA,
)
from src.agents.deep_interpreter.tools.report import (
    generate_html_report,
    generate_simple_report,
)
from src.agents.deep_interpreter.tools.think import (
    think_tool,
)
from src.agents.deep_interpreter.tools.literature_rag import (
    prepare_rag_literature,
    search_literature_fulltext,
    validate_claim_fulltext,
    check_rag_availability_sync,
    get_rag_status,
    is_rag_mode_active,
)
from src.agents.deep_interpreter.tools.lr_prioritizer import (
    HybridLRPrioritizer,
    create_lr_prioritizer,
    prioritize_lr_pairs,
)

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
    "search_literature_dynamic",
    "search_literature_async",
    "search_literature_for_context_async",
    "search_literature_dynamic_async",
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
    # RAG Literature
    "prepare_rag_literature",
    "search_literature_fulltext",
    "validate_claim_fulltext",
    "check_rag_availability_sync",
    "get_rag_status",
    "is_rag_mode_active",
    # L-R Prioritizer
    "HybridLRPrioritizer",
    "create_lr_prioritizer",
    "prioritize_lr_pairs",
]
