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
    search_literature_dynamic,
    search_literature_async,
    search_literature_dynamic_async,
    format_references,
)
from src.agents.deep_interpreter.tools.literature_handoff import (
    build_literature_handoff,
    create_literature_handoff,
    grade_lr_literature_candidates,
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
    analyze_research_question,
    expand_search_entities,
    build_search_queries,
    evaluate_search_results,
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
    prioritize_top_lr_pairs,
    save_selected_lr_pairs,
)
from src.agents.deep_interpreter.tools.pubmed_eutils import (
    search_pubmed_advanced,
    build_pubmed_query,
)
from src.agents.deep_interpreter.tools.standalone_fs import (
    write_file as standalone_write_file,
    read_file as standalone_read_file,
)
from src.agents.shared.skill_reader import read_skill_file
__all__ = [
    # Think tool (think_tool used by subagents; others exported for orchestrator-level use)
    "think_tool",
    "analyze_research_question",  # Orchestrator-level: biomedical thinking chain
    "expand_search_entities",     # Orchestrator-level: entity expansion via BioMCP
    "build_search_queries",       # Orchestrator-level: query construction via BioMCP
    "evaluate_search_results",    # Orchestrator-level: result evaluation via BioMCP
    # Data loader
    "load_analysis_data",
    "get_figure_path",
    "get_data_path",
    "load_csv_data",
    "get_recommended_targets",
    "ANALYSIS_FILES",
    # Literature
    "search_literature",
    "search_literature_dynamic",
    "search_literature_async",
    "search_literature_dynamic_async",
    "format_references",
    "build_literature_handoff",
    "create_literature_handoff",
    "grade_lr_literature_candidates",
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
    "prioritize_top_lr_pairs",
    "save_selected_lr_pairs",
    # PubMed E-utilities
    "search_pubmed_advanced",
    "build_pubmed_query",
    # Standalone filesystem tools
    "standalone_write_file",
    "standalone_read_file",
    # Skill reader (shared)
    "read_skill_file",
]
