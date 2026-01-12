"""CCI Interpreter Agent module.

This module provides the CCIInterpreterAgent for biological interpretation
of Cell-Cell Interaction (CCI) analysis results from spatial transcriptomics.

Example usage:
    from src.agents.interpreter import CCIInterpreterAgent, get_initial_state
    from src.agents.model import create_llm

    # Create agent
    model = await create_llm("openai")
    agent = CCIInterpreterAgent(model=model)

    # Create initial state
    state = get_initial_state(
        result_dir="/path/to/results",
        disease_context="breast cancer"
    )

    # Run analysis
    result = await agent.ainvoke(state)
"""

from src.agents.interpreter.cci_interpreter_agent import CCIInterpreterAgent
from src.agents.interpreter.cci_interpreter_state import (
    CCIInterpreterState,
    Part1Selection,
    Part2Selection,
    LiteratureReference,
    get_initial_state,
)

__all__ = [
    "CCIInterpreterAgent",
    "CCIInterpreterState",
    "Part1Selection",
    "Part2Selection",
    "LiteratureReference",
    "get_initial_state",
]
