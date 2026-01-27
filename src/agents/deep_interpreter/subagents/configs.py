"""Subagent configurations for Deep Interpreter Agent.

Simplified 4-Agent Architecture:
- PLANNER: Target confirmation + hypothesis generation (load_analysis_data)
- SEARCHER: Context extraction + literature search (load_analysis_data, search_literature_for_context, search_literature, think_tool)
- INTERPRETER: Part 1/2/3 interpretation with inline validation (load_analysis_data, validate_claim_literature, validate_quality, think_tool)
- REPORTER: Cross-part synthesis + HTML report (load_analysis_data, generate_html_report)

This module provides the subagent definitions used by create_deep_agent().
"""

from typing import Callable, Sequence

from langchain_core.tools import BaseTool

from src.agents.deep_interpreter.subagents.prompts import SUBAGENT_PROMPTS
from src.agents.deep_interpreter.tools import (
    load_analysis_data,
    search_literature,
    search_literature_for_context,
    validate_claim_literature,
    validate_quality,
    generate_html_report,
    think_tool,
)

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
            "Literature search agent. For each Part (1, 2, 3): extracts biological context "
            "(genes, pathways, cell types) from analysis data, then searches PubMed BEFORE interpretation. "
            "Outputs /partN_search_context.json and /partN_papers.json. "
            "Papers will be the ONLY citation source for interpreter - this prevents hallucination."
        ),
        "system_prompt": SUBAGENT_PROMPTS["searcher"],
        "tools": [
            load_analysis_data,
            search_literature_for_context,
            search_literature,
            think_tool,
        ],
    },
    "interpreter": {
        "name": "interpreter",
        "description": (
            "Interpretation agent with inline validation. For each Part (1, 2, 3): "
            "reads /partN_papers.json, generates literature-grounded interpretation, "
            "validates each claim against cited papers, and ensures quality score >= 0.7. "
            "Every claim must cite PMID or be marked (Novel Finding). "
            "Outputs /partN_final.md. Maximum 3 quality iterations per part."
        ),
        "system_prompt": SUBAGENT_PROMPTS["interpreter"],
        "tools": [
            load_analysis_data,
            validate_claim_literature,
            validate_quality,
            think_tool,
        ],
    },
    "reporter": {
        "name": "reporter",
        "description": (
            "Synthesis and report generation agent. Reads all /partN_final.md files, "
            "identifies cross-part themes, validates hypotheses, and generates final HTML report. "
            "Outputs /synthesis.md and CCI_Analysis_Report.html."
        ),
        "system_prompt": SUBAGENT_PROMPTS["reporter"],
        "tools": [load_analysis_data, generate_html_report],
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
   - For EACH Part (1, 2, 3):
     a. Extract biological context (genes, pathways, cell types)
     b. Search PubMed proactively (BEFORE interpretation)
     c. Ensure coverage: >= 60% genes, >= 50% pathways, 15-20 papers
   - Outputs: /part1_search_context.json, /part1_papers.json, etc.

3. INTERPRETER (part1/2/3-interpreter + claim-validator + quality-reviewer consolidated)
   - For EACH Part (1, 2, 3):
     a. Read /partN_papers.json (ONLY citation source)
     b. Generate literature-grounded interpretation
     c. Inline claim validation (every PMID checked)
     d. Inline quality check (score >= 0.7, max 3 iterations)
   - Outputs: /part1_final.md, /part2_final.md, /part3_final.md

4. REPORTER (synthesizer + report-generator consolidated)
   - Read all /partN_final.md files
   - Identify cross-part themes
   - Validate hypotheses from strategic plan
   - Generate HTML report
   - Outputs: /synthesis.md, CCI_Analysis_Report.html

Hallucination Prevention (maintained):
- Literature-First: Papers searched BEFORE interpretation
- Claim Validation: Every PMID citation verified
- Novel Finding Tags: Unsupported but valid findings clearly marked
"""
