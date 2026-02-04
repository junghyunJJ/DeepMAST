"""Subagent configurations for Deep Interpreter Agent.

Simplified 4-Agent Architecture:
- PLANNER: Target confirmation + hypothesis generation (load_analysis_data)
- SEARCHER: Context extraction + literature search (load_analysis_data, search_literature_dynamic, search_literature, think_tool)
- INTERPRETER: Part 1/2/3 interpretation with inline validation (load_analysis_data, validate_claim_literature, validate_quality, think_tool)
- REPORTER: Cross-part synthesis + literature validation + HTML report
  (load_analysis_data, generate_html_report, literature search tools, RAG tools)

This module provides the subagent definitions used by create_deep_agent().
"""

from typing import Callable, Sequence

from langchain_core.tools import BaseTool

from src.agents.deep_interpreter.subagents.prompts import SUBAGENT_PROMPTS
from src.agents.deep_interpreter.tools import (
    load_analysis_data,
    search_literature,
    search_literature_for_context,
    search_literature_dynamic,
    validate_claim_literature,
    validate_quality,
    generate_html_report,
    think_tool,
    # RAG tools for interpreter
    prepare_rag_literature,
    search_literature_fulltext,
    validate_claim_fulltext,
)
from src.agents.deep_interpreter.tools.lr_prioritizer import prioritize_top_lr_pairs

__all__ = [
    "get_subagents",
    "get_subagent_by_name",
    "get_simplified_subagents",
    "SUBAGENT_CONFIGS",
]


# =============================================================================
# 4-Agent Configuration Definitions
# =============================================================================

SUBAGENT_CONFIGS = {
    "planner": {
        "name": "planner",
        "description": (
            "Strategic planning agent. Reads /targets.json, loads analysis data, "
            "and generates testable hypotheses. Outputs /strategic_plan.md. "
            "Use this FIRST to establish the interpretation strategy."
        ),
        "system_prompt": SUBAGENT_PROMPTS["planner"],
        "tools": [load_analysis_data],
    },
    "searcher": {
        "name": "searcher",
        "description": (
            "Literature search agent. Searches PubMed BEFORE interpretation. "
            "Part 1: uses spatial_search_context, outputs /part1_papers.json. "
            "Part 2+3: uses lr_search_context (SHARED), outputs /liana_papers.json ONCE for both parts. "
            "Uses search_literature_dynamic (LLM-powered) with automatic internal fallback. "
            "Papers will be the ONLY citation source for interpreter - this prevents hallucination."
        ),
        "system_prompt": SUBAGENT_PROMPTS["searcher"],
        "tools": [
            load_analysis_data,
            search_literature_dynamic,  # PRIMARY: LLM-powered (내부 자동 fallback 포함)
            search_literature,  # Follow-up: Single query search
            think_tool,
        ],
    },
    "interpreter": {
        "name": "interpreter",
        "description": (
            "Interpretation agent with inline validation and RAG support. For each Part (1, 2, 3): "
            "reads /partN_papers.json, optionally downloads full-text papers for RAG search, "
            "generates literature-grounded interpretation with full-text context, "
            "validates each claim against cited papers (using full-text if available), "
            "and ensures quality score >= 0.7. "
            "For Part 3: uses prioritize_top_lr_pairs to select top L-R pairs via hybrid "
            "GenePT + Moran's R scoring (spatial 60% + semantic 40%). "
            "Every claim must cite PMID or be marked (Novel Finding). "
            "Outputs /partN_final.md. Maximum 3 quality iterations per part. "
            "Falls back to Abstract mode if RAG infrastructure unavailable."
        ),
        "system_prompt": SUBAGENT_PROMPTS["interpreter"],
        "tools": [
            load_analysis_data,
            validate_claim_literature,
            validate_quality,
            think_tool,
            # RAG tools for full-text literature support
            prepare_rag_literature,
            search_literature_fulltext,
            validate_claim_fulltext,
            # Hybrid L-R prioritization (GenePT + Moran's R)
            prioritize_top_lr_pairs,
        ],
    },
    "reporter": {
        "name": "reporter",
        "description": (
            "Synthesis and report generation agent. Reads all /partN_final.md files, "
            "identifies cross-part themes, validates synthesis claims with NEW literature search "
            "(following biomedical-literature-search workflow), and generates final HTML report. "
            "Phase 4.5 validates integration claims against independent literature sources. "
            "Outputs /synthesis.md, /synthesis_papers.json, /synthesis_validation.json, "
            "and CCI_Analysis_Report.html."
        ),
        "system_prompt": SUBAGENT_PROMPTS["reporter"],
        "tools": [
            # Core tools
            load_analysis_data,
            generate_html_report,
            # Literature search tools (reuse from SEARCHER for synthesis validation)
            search_literature_dynamic,
            search_literature_for_context,
            search_literature,
            # RAG validation tools
            prepare_rag_literature,
            validate_claim_fulltext,
            # Think tool for strategic planning and reflection
            think_tool,
        ],
    },
}


def get_subagents(
    custom_tools: Sequence[BaseTool | Callable] | None = None,
) -> list[dict]:
    """Get the subagent configurations for Deep Interpreter.

    Returns 4 subagents in workflow order:
    1. planner - Target confirmation + hypothesis generation
    2. searcher - Context extraction + literature search
    3. interpreter - Literature-grounded interpretation with inline validation
    4. reporter - Cross-part synthesis + HTML report

    Args:
        custom_tools: Optional list of additional tools to include in all subagents

    Returns:
        List of subagent configuration dictionaries
    """
    # Build subagent list in workflow order
    subagents = [
        SUBAGENT_CONFIGS["planner"].copy(),
        SUBAGENT_CONFIGS["searcher"].copy(),
        SUBAGENT_CONFIGS["interpreter"].copy(),
        SUBAGENT_CONFIGS["reporter"].copy(),
    ]

    # Add custom tools if provided
    if custom_tools:
        for subagent in subagents:
            current_tools = list(subagent.get("tools", []))
            current_tools.extend(custom_tools)
            subagent["tools"] = current_tools

    return subagents


def get_subagent_by_name(name: str) -> dict | None:
    """Get a specific subagent configuration by name.

    Args:
        name: Subagent name ('planner', 'searcher', 'interpreter', or 'reporter')

    Returns:
        Subagent configuration dict, or None if not found
    """
    config = SUBAGENT_CONFIGS.get(name)
    if config:
        return config.copy()
    return None


def get_simplified_subagents() -> list[dict]:
    """Get the simplified 4-agent configuration.

    This is the recommended configuration for the Deep Interpreter.
    Same as get_subagents() but makes the simplified nature explicit.

    Returns:
        List of 4 subagent configurations in workflow order
    """
    return get_subagents()


# =============================================================================
# Workflow Order Constants
# =============================================================================

WORKFLOW_ORDER = ["planner", "searcher", "interpreter", "reporter"]

WORKFLOW_DESCRIPTION = """
Deep Interpreter 4-Agent Workflow:

1. PLANNER (target-selector + strategic-planner consolidated)
   - Reads /targets.json
   - Loads analysis data
   - Generates 2-4 testable hypotheses
   - Outputs: /strategic_plan.md, /analysis_summary.md, /data_path.txt

2. SEARCHER (context-analyzer + literature-searcher consolidated)
   - For Part 1:
     a. Extract context using spatial_search_context (pathways + celltypes, NO genes)
     b. Search PubMed proactively (BEFORE interpretation)
     c. Ensure coverage: >= 50% pathways, 15-20 papers
     d. Output: /part1_papers.json
   - For Part 2+3 (SHARED - identical lr_search_context):
     a. Extract context using lr_search_context (genes + pathways + celltypes)
     b. Search PubMed ONCE for both parts (saves API calls)
     c. Ensure coverage: >= 60% genes, >= 50% pathways, 15-20 papers
     d. Output: /liana_papers.json (shared by Part 2 and Part 3)
   - Total Outputs: /part1_papers.json, /liana_papers.json (2 files, not 3)

3. INTERPRETER (part1/2/3-interpreter + claim-validator + quality-reviewer consolidated)
   - For EACH Part (1, 2, 3):
     a. Read /partN_papers.json (ONLY citation source)
     b. Generate literature-grounded interpretation
     c. Inline claim validation (every PMID checked)
     d. Inline quality check (score >= 0.7, max 3 iterations)
   - Outputs: /part1_final.md, /part2_final.md, /part3_final.md

4. REPORTER (synthesizer + report-generator consolidated + synthesis validation)
   - Read all /partN_final.md files
   - Identify cross-part themes
   - Validate hypotheses from strategic plan
   - **Phase 4.5: Validate synthesis claims with independent literature search**
     a. Extract synthesis context (genes, pathways, celltypes from Themes 1-4)
     b. Strategic planning with think_tool (3 thoughts)
     c. Search literature (search_literature_dynamic with integration-focused terms)
     d. Quality reflection (theme coverage, gap-filling)
     e. RAG validate & write (prepare_rag_literature, validate_claim_fulltext)
   - Generate HTML report
   - Outputs: /synthesis.md, /synthesis_papers.json, /synthesis_validation.json, CCI_Analysis_Report.html
   - Papers stored in: {data_path}/papers/synthesis/ (separate from Part papers)

Hallucination Prevention (maintained):
- Literature-First: Papers searched BEFORE interpretation
- Claim Validation: Every PMID citation verified
- **Synthesis Validation**: Integration claims validated with independent literature
- Novel Finding Tags: Unsupported but valid findings clearly marked
"""
