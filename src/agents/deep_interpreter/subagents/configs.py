"""Subagent configurations for Deep Interpreter Agent.

This module provides the subagent definitions used by create_deep_agent().
Each subagent has a name, description, system_prompt, and tools.

Architecture:
- 10 Simple SubAgents (configured via dict)
- 1 CompiledSubAgent (literature-searcher with BioMCP workflow)
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


def get_literature_searcher_subagent() -> dict:
    """Get the literature-searcher CompiledSubAgent configuration.

    This subagent uses the BioMCP workflow pattern:
    think → article_searcher → quality loop

    Returns:
        Dictionary with subagent configuration (runnable will be created by DeepAgents)
    """
    # For now, use Simple SubAgent pattern with enhanced tools
    # In future, this could be upgraded to a full CompiledSubAgent with its own graph
    return {
        "name": "literature-searcher",
        "description": (
            "Search PubMed for literature BEFORE interpretation (proactive search). "
            "Uses BioMCP workflow: think → search → quality validation loop. "
            "Outputs to /partN_papers.json for use by interpreters."
        ),
        "system_prompt": SUBAGENT_PROMPTS["literature-searcher"],
        "tools": [search_literature, search_literature_for_context, think_tool],
    }


def get_subagents(
    custom_tools: Sequence[BaseTool | Callable] | None = None,
    exclude_literature_searcher: bool = False,
) -> list[dict]:
    """Get the subagent configurations for Deep Interpreter.

    Returns 11 subagents (or 10 if exclude_literature_searcher=True):
    - 1 CompiledSubAgent-style (literature-searcher with BioMCP workflow)
    - 10 Simple SubAgents

    Args:
        custom_tools: Optional list of additional tools to include
        exclude_literature_searcher: If True, exclude the Simple SubAgent version
            of literature-searcher. Set to True when using CompiledSubAgent with
            backend from create_deep_interpreter_agent().

    Returns:
        List of subagent configuration dictionaries
    """
    # Default tools
    default_tools = [load_analysis_data, search_literature, validate_quality, generate_html_report]

    # Merge with custom tools if provided
    all_tools = list(default_tools)
    if custom_tools:
        all_tools.extend(custom_tools)

    subagents = [
        # Context Analyzer - Extract searchable terms before literature search
        {
            "name": "context-analyzer",
            "description": (
                "Extract searchable biological terms from analysis results BEFORE literature search. "
                "Use this agent to identify genes, pathways, cell types, and keywords for proactive search."
            ),
            "system_prompt": SUBAGENT_PROMPTS["context-analyzer"],
            "tools": [load_analysis_data],
        },
        # Claim Validator - Validate claims against cited literature
        {
            "name": "claim-validator",
            "description": (
                "Validate that each claim in interpretation is supported by cited literature. "
                "Use after interpretation to check PMID citations are accurate. "
                "Prevents hallucination by ensuring claims match paper content."
            ),
            "system_prompt": SUBAGENT_PROMPTS["claim-validator"],
            "tools": [validate_claim_literature],
        },
        # Target Selector (READONLY) - Parse pre-selected targets
        {
            "name": "target-selector",
            "description": (
                "Parse pre-selected targets from initial message and write to /targets.json. "
                "HITL is handled by wrapper agent - DO NOT ask for user input. "
                "After parsing, use write_file to save /targets.json for downstream subagents."
            ),
            "system_prompt": SUBAGENT_PROMPTS["target-selector"],
            "tools": [],  # Filesystem tools (read_file, write_file) are automatic via FilesystemMiddleware
        },
        # Strategic Planner - Hypothesis generation
        {
            "name": "strategic-planner",
            "description": (
                "Generate hypothesis-driven interpretation strategies. "
                "Use after target selection to plan the interpretation approach."
            ),
            "system_prompt": SUBAGENT_PROMPTS["strategic-planner"],
            "tools": [search_literature],  # Can search for background literature
        },
    ]

    # Add literature-searcher as Simple SubAgent only if not excluded
    # When exclude_literature_searcher=True, a CompiledSubAgent with backend
    # is added separately in create_deep_interpreter_agent()
    if not exclude_literature_searcher:
        subagents.append(get_literature_searcher_subagent())

    # Continue with remaining subagents
    subagents.extend([
        # Part 1 Interpreter - Spatial & Pathway (Literature-Based)
        {
            "name": "part1-interpreter",
            "description": (
                "Interpret Part 1: Spatial Distribution & Pathway Analysis (Literature-Based). "
                "REQUIRES /part1_papers.json to be available first. "
                "Analyses: 1-1 Spatial, 1-2 CellType, 1-3 Neighborhood, 1-4 Decoupler, 1-5 MISTy."
            ),
            "system_prompt": SUBAGENT_PROMPTS["part1-interpreter"],
            "tools": [load_analysis_data],
        },
        # Part 2 Interpreter - CCI & NMF (Literature-Based)
        {
            "name": "part2-interpreter",
            "description": (
                "Interpret Part 2: CCI & NMF Analysis (Literature-Based). "
                "REQUIRES /part2_papers.json to be available first. "
                "Analyses: 2-6 LIANA Moran's R, 2-7 NMF Factor, 2-8 Pathway-Factor, 2-9 ctSVG."
            ),
            "system_prompt": SUBAGENT_PROMPTS["part2-interpreter"],
            "tools": [load_analysis_data],
        },
        # Part 3 Interpreter - L-R Details (Literature-Based)
        {
            "name": "part3-interpreter",
            "description": (
                "Interpret Part 3: L-R Interaction Details (Literature-Based). "
                "REQUIRES /part3_papers.json to be available first. "
                "Analyses: 3-10 Spatial L-R Visualization, 3-11 L-R Summary."
            ),
            "system_prompt": SUBAGENT_PROMPTS["part3-interpreter"],
            "tools": [load_analysis_data],
        },
        # Quality Reviewer - Validation with reflection
        {
            "name": "quality-reviewer",
            "description": (
                "Review interpretation quality using think_tool for reflection. "
                "Validates statistics, references, mechanism clarity, and specificity. "
                "Score threshold: 0.7, max 3 iterations."
            ),
            "system_prompt": SUBAGENT_PROMPTS["quality-reviewer"],
            "tools": [validate_quality, think_tool],
        },
        # Synthesizer - Cross-part integration
        {
            "name": "synthesizer",
            "description": (
                "Synthesize cross-part findings into unified narrative. "
                "Integrates Part 1-3 interpretations and validates hypotheses."
            ),
            "system_prompt": SUBAGENT_PROMPTS["synthesizer"],
            "tools": [],  # Uses filesystem only
        },
        # Report Generator - HTML output
        {
            "name": "report-generator",
            "description": (
                "Generate final publication-quality HTML report. "
                "Creates tabbed report with figures, interpretations, and references."
            ),
            "system_prompt": SUBAGENT_PROMPTS["report-generator"],
            "tools": [generate_html_report, load_analysis_data],
        },
    ])

    return subagents


def get_subagent_by_name(name: str) -> dict | None:
    """Get a specific subagent configuration by name.

    Args:
        name: Subagent name (e.g., "target-selector")

    Returns:
        Subagent configuration dict, or None if not found
    """
    subagents = get_subagents()
    for subagent in subagents:
        if subagent["name"] == name:
            return subagent
    return None


def get_interpretation_subagents() -> list[dict]:
    """Get only the interpretation subagents (Part 1/2/3).

    Returns:
        List of interpreter subagent configurations
    """
    all_subagents = get_subagents()
    return [
        s for s in all_subagents
        if s["name"] in ["part1-interpreter", "part2-interpreter", "part3-interpreter"]
    ]


def get_workflow_subagents() -> list[dict]:
    """Get workflow-related subagents (non-interpretation).

    Returns:
        List of workflow subagent configurations
    """
    all_subagents = get_subagents()
    return [
        s for s in all_subagents
        if s["name"] in [
            "context-analyzer",
            "claim-validator",
            "target-selector",
            "strategic-planner",
            "literature-searcher",
            "quality-reviewer",
            "synthesizer",
            "report-generator",
        ]
    ]


def get_hybrid_workflow_subagents() -> list[dict]:
    """Get subagents for the hybrid literature-based workflow.

    Returns:
        List of subagent configurations in workflow order
    """
    all_subagents = get_subagents()

    # Define the order for hybrid workflow
    hybrid_order = [
        "target-selector",
        "strategic-planner",
        "context-analyzer",
        "literature-searcher",
        "part1-interpreter",
        "claim-validator",
        "quality-reviewer",
        "part2-interpreter",
        "part3-interpreter",
        "synthesizer",
        "report-generator",
    ]

    ordered_subagents = []
    for name in hybrid_order:
        for s in all_subagents:
            if s["name"] == name:
                ordered_subagents.append(s)
                break

    return ordered_subagents
