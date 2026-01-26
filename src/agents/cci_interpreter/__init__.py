"""CCI Interpreter Agent - Deep Agents implementation for CCI analysis interpretation.

This package provides a Deep Agents-based interpreter for Cell-Cell Interaction
analysis results, generating publication-quality HTML reports with biological insights.

Architecture:
- Main orchestrator: create_deep_agent() with 11 specialized subagents
- Hybrid literature-based workflow to prevent hallucination
- HITL: Human-in-the-loop target selection

Two Variants Available:
1. **Original Deep Agent** (create_cci_interpreter_agent):
   - Uses Deep Agents' subagent-level HITL (may be unreliable)
   - target-selector asks for user input directly

2. **Wrapped Agent** (CCIInterpreterWrapperAgent) [RECOMMENDED]:
   - Pre-collection pattern with reliable HITL
   - Wrapper collects info BEFORE invoking Deep Agent
   - Uses readonly target-selector that reads /targets.json

Subagents (Hybrid Workflow):
- context-analyzer: Extract searchable biological terms
- claim-validator: Validate claim-literature alignment
- target-selector: HITL target selection (or readonly for wrapped version)
- strategic-planner: Hypothesis generation
- part1-interpreter: Spatial & pathway analysis (literature-based)
- part2-interpreter: CCI & NMF analysis (literature-based)
- part3-interpreter: L-R interaction details (literature-based)
- literature-searcher: Proactive PubMed evidence gathering
- quality-reviewer: Interpretation quality validation
- synthesizer: Cross-part narrative integration
- report-generator: HTML report generation

Anti-Hallucination Features:
- Literature FIRST: Papers searched before interpretation
- PMID Requirements: All claims must cite from pre-searched papers
- Claim Validation: Each PMID checked for actual support
- Novel Finding Tags: Unsupported claims marked as **(Novel Finding)**
"""

from src.agents.cci_interpreter.cci_analysis_info import CCIAnalysisInfo
from src.agents.cci_interpreter.cci_interpreter_wrapper_state import (
    CCIInterpreterWrapperState,
    create_initial_state,
)

# Lazy imports for agent/graph classes that require API keys at instantiation
# These are imported at function call time to avoid requiring API keys at import
def __getattr__(name: str):
    """Lazy import for components requiring API keys."""
    if name in (
        "CCIInterpreterConfig",
        "ORCHESTRATOR_SYSTEM_PROMPT",
        "create_cci_interpreter_agent",
        "create_cci_interpreter_graph",
        "interpret_cci_analysis",
    ):
        from src.agents.cci_interpreter.cci_interpreter_agent import (
            CCIInterpreterConfig,
            ORCHESTRATOR_SYSTEM_PROMPT,
            create_cci_interpreter_agent,
            create_cci_interpreter_graph,
            interpret_cci_analysis,
        )
        return locals()[name]

    if name == "CCIInterpreterWrapperAgent":
        from src.agents.cci_interpreter.cci_interpreter_wrapper_agent import (
            CCIInterpreterWrapperAgent,
        )
        return CCIInterpreterWrapperAgent

    if name == "create_cci_interpreter_graph_wrapped":
        from src.agents.cci_interpreter.graph_builder import (
            create_cci_interpreter_graph_wrapped,
        )
        return create_cci_interpreter_graph_wrapped

    if name in ("cci_interpreter_graph", "cci_interpreter_wrapped_graph"):
        # These require API keys - import from graph_builder
        from src.agents.cci_interpreter import graph_builder
        return getattr(graph_builder, name)

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    # Original Deep Agent
    "create_cci_interpreter_agent",
    "create_cci_interpreter_graph",
    "interpret_cci_analysis",
    "CCIInterpreterConfig",
    "ORCHESTRATOR_SYSTEM_PROMPT",
    # Wrapper Agent (RECOMMENDED)
    "CCIAnalysisInfo",
    "CCIInterpreterWrapperState",
    "CCIInterpreterWrapperAgent",
    "create_cci_interpreter_graph_wrapped",
    "cci_interpreter_wrapped_graph",
    "create_initial_state",
]
