"""State schema for CCI Interpreter Wrapper Agent.

This module defines the state used by the wrapper agent that collects
information BEFORE invoking the Deep Agent. This pattern resolves the
HITL issues with Deep Agents' subagent-level interrupt_on.

Workflow:
1. Wrapper collects data_directory, clusters/celltypes from user
2. Wrapper writes /targets.json to filesystem
3. Wrapper invokes Deep Agent with modified target-selector (readonly)
4. Deep Agent proceeds without HITL for target selection
"""

from typing import Annotated, Literal, Optional

from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class CCIInterpreterWrapperState(TypedDict):
    """State schema for CCI Interpreter Wrapper Agent.

    This state tracks the information collection phase before
    invoking the Deep Agent for actual interpretation.

    Attributes:
        messages: Conversation history with add_messages reducer
        data_directory: Path to analysis results (res/ folder)
        interest_clusters: Selected clusters for Mode A
        interest_celltypes: Selected cell types for Mode B
        analysis_mode: Determined mode based on user selection
        info_complete: Flag indicating all info collected
        targets_written: Flag indicating /targets.json written
        deep_agent_result: Output from Deep Agent invocation
    """

    # Conversation messages (required for LangGraph)
    messages: Annotated[list, add_messages]

    # Collected information from user
    data_directory: Optional[str]
    interest_clusters: Optional[list[str]]
    interest_celltypes: Optional[list[str]]
    analysis_mode: Optional[Literal["cluster_to_celltype", "celltype_to_cluster"]]

    # Workflow control flags
    info_complete: bool
    targets_written: bool

    # Deep Agent output
    deep_agent_result: Optional[dict]


def create_initial_state() -> CCIInterpreterWrapperState:
    """Create initial state with default values.

    Returns:
        Initial state dictionary with None/False defaults
    """
    return CCIInterpreterWrapperState(
        messages=[],
        data_directory=None,
        interest_clusters=None,
        interest_celltypes=None,
        analysis_mode=None,
        info_complete=False,
        targets_written=False,
        deep_agent_result=None,
    )


__all__ = ["CCIInterpreterWrapperState", "create_initial_state"]
