"""CCI Interpreter Wrapper Agent - Pre-collection pattern for reliable HITL.

This module implements a wrapper agent that collects analysis configuration
BEFORE invoking the Deep Agent. This resolves the HITL issues where
Deep Agents' interrupt_on doesn't work at subagent level.

Architecture:
1. Wrapper Agent (this file): Collects data_directory, clusters/celltypes
2. Writes /targets.json to filesystem
3. Invokes Deep Agent with readonly target-selector

Pattern Reference: STPipelineBuilderAgent (st_pipeline_info_agent.py)
"""

import json
from pathlib import Path
from typing import Any, ClassVar, Literal, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.store.base import BaseStore

from src.base import BaseAgent
from src.agents.cci_interpreter.cci_analysis_info import CCIAnalysisInfo
from src.agents.cci_interpreter.cci_interpreter_wrapper_state import (
    CCIInterpreterWrapperState,
)
from src.agents.cci_interpreter.cci_interpreter_agent import (
    create_cci_interpreter_agent,
    CCIInterpreterConfig,
)


class CCIInterpreterWrapperAgent(BaseAgent):
    """Wrapper agent for CCI Interpreter with pre-collection HITL.

    This agent collects the necessary information (data directory and targets)
    before invoking the Deep Agent, resolving HITL issues with subagent-level
    interrupt_on in the Deep Agents framework.

    Graph Flow:
        START → check_state
          ├─(info exists)→ write_targets → invoke_deep_agent → END
          └─(need info)→ info_collection ←─┐
                             ↓              │
                         get_state ─────────┤
                             ↓ (tool_calls) │
                      info_validation ──────┘
                             ↓ (complete)
                      write_targets → invoke_deep_agent → END
    """

    NODE_NAMES: ClassVar[dict[str, str]] = {
        "CHECK_STATE": "check_state",
        "INFO_COL": "info_collection",
        "INFO_VAL": "info_validation",
        "WRITE_TARGETS": "write_targets",
        "INVOKE_DEEP": "invoke_deep_agent",
    }

    SYSTEM_TEMPLATE: ClassVar[str] = """You are a CCI (Cell-Cell Interaction) analysis interpreter assistant.

Your job is to collect essential information from the user to configure the CCI analysis interpretation.

You must collect the following information:

1. **Data Directory**: Path to the analysis results directory (res/ folder)
   - This folder should contain figures (1.spatial.png, etc.) and CSV files
   - Example: "/path/to/results/res" or "~/analysis/sample1/res"

2. **Analysis Targets**: Either clusters OR cell types of interest
   - **Mode A (Cluster to Cell Type)**: Start from spatial clusters
     - Example: clusters 4, 16, 176
   - **Mode B (Cell Type to Cluster)**: Start from known cell types
     - Example: Invasive Tumor, Fibroblast, Macrophage

## Guidelines

- Ask for the data directory first if not provided
- Then ask for the analysis mode and targets
- If the user provides both clusters AND cell types, ask them to choose one mode
- Accept various input formats:
  - "Mode A: 4, 16, 176" → clusters ['4', '16', '176']
  - "clusters 4 16 176" → clusters ['4', '16', '176']
  - "analyze Tumor and Fibroblast" → celltypes ['Tumor', 'Fibroblast']
  - "Mode B with Macrophage, T cell" → celltypes ['Macrophage', 'T cell']

## CRITICAL RULES

- DO NOT call the CCIAnalysisInfo tool until you have:
  1. A valid data_directory path
  2. Either interest_clusters OR interest_celltypes (not both)
- If user mentions "cluster" keywords → Mode A (interest_clusters)
- If user mentions cell type names → Mode B (interest_celltypes)
- Parse cluster numbers as strings: "4" not 4

## Example Conversation

User: "Interpret CCI in /data/sample1/res for clusters 4, 16"
Assistant: [Calls CCIAnalysisInfo tool with data_directory="/data/sample1/res", interest_clusters=["4", "16"]]

User: "I have results in ~/res, analyze Tumor and CAF interactions"
Assistant: [Calls CCIAnalysisInfo tool with data_directory="~/res", interest_celltypes=["Tumor", "CAF"]]

After you have confirmed ALL required information, call the CCIAnalysisInfo tool."""

    def __init__(
        self,
        model: Any,
        state_schema: Any = CCIInterpreterWrapperState,
        config_schema: Any | None = None,
        input_schema: Any | None = None,
        output_schema: Any | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
        store: BaseStore | None = None,
        max_retry_attempts: int = 2,
        agent_name: str | None = None,
        is_debug: bool = True,
        deep_agent_config: CCIInterpreterConfig | None = None,
    ) -> None:
        """Initialize the wrapper agent.

        Args:
            model: LLM model to use for info collection
            state_schema: State schema class
            config_schema: Optional config schema
            input_schema: Optional input schema
            output_schema: Optional output schema
            checkpointer: Optional checkpointer for persistence
            store: Optional store for state
            max_retry_attempts: Max retries for LLM calls
            agent_name: Name for the agent
            is_debug: Enable debug logging
            deep_agent_config: Configuration for the Deep Agent
        """
        super().__init__(
            model=model,
            state_schema=state_schema,
            config_schema=config_schema,
            input_schema=input_schema,
            output_schema=output_schema,
            checkpointer=checkpointer,
            store=store,
            max_retry_attempts=max_retry_attempts,
            agent_name=agent_name or "CCIInterpreterWrapperAgent",
            is_debug=is_debug,
        )
        # Bind CCIAnalysisInfo tool to LLM
        self.llm_with_tool = self.model.bind_tools([CCIAnalysisInfo])
        # Deep Agent config - always use readonly selector in wrapped mode
        if deep_agent_config:
            self.deep_agent_config = deep_agent_config
            # Ensure readonly selector is enabled
            self.deep_agent_config.use_readonly_selector = True
        else:
            self.deep_agent_config = CCIInterpreterConfig(use_readonly_selector=True)
        # Deep Agent will be created on-demand
        self._deep_agent = None

    # ===== Helper Methods =====

    def extract_info_from_messages(self, messages: list) -> dict[str, Any]:
        """Extract collected information from tool calls in messages.

        Args:
            messages: List of conversation messages

        Returns:
            Dictionary with extracted info (data_directory, clusters, celltypes)
        """
        extracted_info = {}

        for message in reversed(messages):
            if (
                isinstance(message, AIMessage)
                and hasattr(message, "tool_calls")
                and message.tool_calls
            ):
                for tool_call in message.tool_calls:
                    if tool_call.get("name") == "CCIAnalysisInfo":
                        args = tool_call.get("args", {})
                        extracted_info = {
                            "data_directory": args.get("data_directory"),
                            "interest_clusters": args.get("interest_clusters"),
                            "interest_celltypes": args.get("interest_celltypes"),
                        }

                        # Determine analysis mode
                        if extracted_info.get("interest_clusters"):
                            extracted_info["analysis_mode"] = "cluster_to_celltype"
                        elif extracted_info.get("interest_celltypes"):
                            extracted_info["analysis_mode"] = "celltype_to_cluster"

                        return extracted_info

        return extracted_info

    def get_deep_agent(self):
        """Get or create the Deep Agent instance.

        Returns:
            Compiled Deep Agent runnable
        """
        if self._deep_agent is None:
            self._deep_agent = create_cci_interpreter_agent(self.deep_agent_config)
        return self._deep_agent

    # ===== Node Initialization =====

    def init_nodes(self, graph: StateGraph):
        """Initialize nodes in the graph."""
        check_state_node = self.get_node_name("CHECK_STATE")
        info_collection_node = self.get_node_name("INFO_COL")
        info_validation_node = self.get_node_name("INFO_VAL")
        write_targets_node = self.get_node_name("WRITE_TARGETS")
        invoke_deep_node = self.get_node_name("INVOKE_DEEP")

        graph.add_node(check_state_node, self.check_state_node)
        graph.add_node(info_collection_node, self.info_collection_node)
        graph.add_node(info_validation_node, self.info_validation_node)
        graph.add_node(write_targets_node, self.write_targets_node)
        graph.add_node(invoke_deep_node, self.invoke_deep_agent_node)

    def init_edges(self, graph: StateGraph):
        """Initialize edges in the graph."""
        check_state_node = self.get_node_name("CHECK_STATE")
        info_collection_node = self.get_node_name("INFO_COL")
        info_validation_node = self.get_node_name("INFO_VAL")
        write_targets_node = self.get_node_name("WRITE_TARGETS")
        invoke_deep_node = self.get_node_name("INVOKE_DEEP")

        # START → check_state
        graph.add_edge(START, check_state_node)

        # check_state → [write_targets | info_collection]
        graph.add_conditional_edges(
            check_state_node,
            self.route_after_check,
            [write_targets_node, info_collection_node],
        )

        # info_collection → [END | info_validation | info_collection]
        graph.add_conditional_edges(
            info_collection_node,
            self.get_state,
            [END, info_validation_node, info_collection_node],
        )

        # info_validation → [info_collection (retry) | write_targets (success)]
        graph.add_conditional_edges(
            info_validation_node,
            self.route_after_validation,
            [info_collection_node, write_targets_node],
        )

        # write_targets → invoke_deep_agent
        graph.add_edge(write_targets_node, invoke_deep_node)

        # invoke_deep_agent → END
        graph.add_edge(invoke_deep_node, END)

    # ===== Check State Node =====

    async def check_state_node(
        self, state: CCIInterpreterWrapperState, config: RunnableConfig  # noqa: ARG002
    ) -> dict:
        """Check if info is already available in state.

        This is a pass-through node; routing logic is in route_after_check.
        """
        return {}

    def route_after_check(
        self, state: CCIInterpreterWrapperState, config: RunnableConfig  # noqa: ARG002
    ) -> str:
        """Route after checking state.

        Returns:
            write_targets if info_complete, else info_collection
        """
        if state.get("info_complete"):
            return self.get_node_name("WRITE_TARGETS")
        return self.get_node_name("INFO_COL")

    # ===== Information Collection Node =====

    def get_messages_with_system(
        self, messages: list[HumanMessage | AIMessage | SystemMessage]
    ) -> list[SystemMessage | HumanMessage | AIMessage]:
        """Combine messages with system template."""
        return [SystemMessage(content=self.SYSTEM_TEMPLATE)] + messages

    async def info_collection_node(
        self, state: CCIInterpreterWrapperState, config: RunnableConfig  # noqa: ARG002
    ) -> dict:
        """Collect CCI analysis information from user.

        Uses LLM with bound CCIAnalysisInfo tool to extract structured data.
        """
        try:
            messages = self.get_messages_with_system(state["messages"])
            response = await self.llm_with_tool.ainvoke(messages)
            return {"messages": [response]}
        except Exception as e:
            if self.is_debug:
                print(f"Error in info_collection_node: {e}")
            raise

    def get_state(
        self, state: CCIInterpreterWrapperState, config: RunnableConfig  # noqa: ARG002
    ) -> Literal["__end__", "info_validation", "info_collection"]:
        """Determine next state based on message type.

        Returns:
            info_validation if tool_calls present
            END if waiting for user input
            info_collection to continue collection
        """
        messages = state["messages"]

        # If LLM made tool calls, go to validation
        if isinstance(messages[-1], AIMessage) and messages[-1].tool_calls:
            return self.get_node_name("INFO_VAL")

        # If waiting for user input, end turn
        if not isinstance(messages[-1], HumanMessage):
            return END

        # Continue collection
        return self.get_node_name("INFO_COL")

    # ===== Information Validation Node =====

    async def info_validation_node(
        self, state: CCIInterpreterWrapperState, config: RunnableConfig  # noqa: ARG002
    ) -> dict:
        """Validate and extract information from tool calls.

        Extracts data_directory, clusters/celltypes from the CCIAnalysisInfo
        tool call and updates state.
        """
        last_message = state["messages"][-1]

        if not isinstance(last_message, AIMessage):
            raise ValueError("Expected AIMessage with tool call")

        if not last_message.tool_calls:
            raise ValueError("No tool calls found")

        tool_call = last_message.tool_calls[0]
        tool_call_id = tool_call.get("id")
        tool_args = tool_call.get("args", {})

        if not tool_call_id:
            raise ValueError("Missing tool_call_id")

        # Extract info
        data_directory = tool_args.get("data_directory")
        interest_clusters = tool_args.get("interest_clusters")
        interest_celltypes = tool_args.get("interest_celltypes")

        # Validate: must have directory and exactly one target type
        if not data_directory:
            return {
                "messages": [
                    ToolMessage(
                        content="Error: data_directory is required. Please provide the path to the analysis results.",
                        tool_call_id=tool_call_id,
                    )
                ],
                "info_complete": False,
            }

        has_clusters = interest_clusters and len(interest_clusters) > 0
        has_celltypes = interest_celltypes and len(interest_celltypes) > 0

        if has_clusters and has_celltypes:
            return {
                "messages": [
                    ToolMessage(
                        content="Error: Please provide either clusters (Mode A) OR cell types (Mode B), not both.",
                        tool_call_id=tool_call_id,
                    )
                ],
                "info_complete": False,
            }

        if not has_clusters and not has_celltypes:
            return {
                "messages": [
                    ToolMessage(
                        content="Error: Please provide either clusters of interest (Mode A) or cell types of interest (Mode B).",
                        tool_call_id=tool_call_id,
                    )
                ],
                "info_complete": False,
            }

        # Determine analysis mode
        analysis_mode = "cluster_to_celltype" if has_clusters else "celltype_to_cluster"
        targets = interest_clusters if has_clusters else interest_celltypes
        mode_desc = "Mode A (Cluster to Cell Type)" if has_clusters else "Mode B (Cell Type to Cluster)"

        if self.is_debug:
            print(f"Info collection complete:")
            print(f"  Data directory: {data_directory}")
            print(f"  Analysis mode: {analysis_mode}")
            print(f"  Targets: {targets}")

        return {
            "messages": [
                ToolMessage(
                    content=f"Configuration collected:\n- Data: {data_directory}\n- Mode: {mode_desc}\n- Targets: {targets}\n\nProceeding to CCI analysis...",
                    tool_call_id=tool_call_id,
                )
            ],
            "data_directory": data_directory,
            "interest_clusters": interest_clusters,
            "interest_celltypes": interest_celltypes,
            "analysis_mode": analysis_mode,
            "info_complete": True,
        }

    def route_after_validation(
        self, state: CCIInterpreterWrapperState, config: RunnableConfig  # noqa: ARG002
    ) -> str:
        """Route after validation.

        Returns:
            write_targets if info_complete, else info_collection to retry
        """
        if state.get("info_complete"):
            return self.get_node_name("WRITE_TARGETS")
        return self.get_node_name("INFO_COL")

    # ===== Write Targets Node =====

    async def write_targets_node(
        self, state: CCIInterpreterWrapperState, config: RunnableConfig  # noqa: ARG002
    ) -> dict:
        """Write targets.json file for Deep Agent consumption.

        Creates /targets.json in the data directory with the collected
        configuration, which the readonly target-selector will read.
        """
        data_directory = state.get("data_directory")
        if not data_directory:
            raise ValueError("data_directory not set in state")

        # Expand user home directory if needed
        data_path = Path(data_directory).expanduser()

        # Create targets.json content
        targets_content = {
            "analysis_mode": state.get("analysis_mode"),
            "interest_clusters": state.get("interest_clusters"),
            "interest_celltypes": state.get("interest_celltypes"),
            "data_directory": str(data_path),
            "user_confirmed": True,
        }

        # Write to file in data directory
        targets_path = data_path / "targets.json"
        try:
            with open(targets_path, "w") as f:
                json.dump(targets_content, f, indent=2)

            if self.is_debug:
                print(f"Wrote targets.json to: {targets_path}")

            return {
                "targets_written": True,
                "messages": [
                    AIMessage(
                        content=f"Configuration saved to {targets_path}. Starting CCI interpretation..."
                    )
                ],
            }
        except Exception as e:
            if self.is_debug:
                print(f"Error writing targets.json: {e}")
            raise

    # ===== Invoke Deep Agent Node =====

    async def invoke_deep_agent_node(
        self, state: CCIInterpreterWrapperState, config: RunnableConfig
    ) -> dict:
        """Invoke the Deep Agent for CCI interpretation.

        The Deep Agent will:
        1. Load analysis data from data_directory
        2. Read pre-written /targets.json (readonly target-selector)
        3. Proceed with strategic planning → interpretation → report generation
        """
        data_directory = state.get("data_directory")

        # Null check - data_directory is required
        if not data_directory:
            raise ValueError("data_directory is required but not set in state")

        if self.is_debug:
            print(f"Invoking Deep Agent for: {data_directory}")

        # Get or create Deep Agent
        deep_agent = self.get_deep_agent()

        # Build initial message for Deep Agent with embedded targets
        # Pass targets content directly to bypass filesystem abstraction mismatch
        # (StateBackend vs real filesystem)
        targets_content = {
            "analysis_mode": state.get("analysis_mode"),
            "interest_clusters": state.get("interest_clusters"),
            "interest_celltypes": state.get("interest_celltypes"),
            "data_directory": str(data_directory),
            "user_confirmed": True,
        }

        initial_message = f"""Interpret the CCI analysis results in {data_directory}.

## PRE-SELECTED TARGET CONFIGURATION
The following targets have been pre-selected by the user (DO NOT ask for user input):

```json
{json.dumps(targets_content, indent=2)}
```

IMPORTANT: Skip the target-selector subagent. The targets are already confirmed above.
Proceed directly to strategic planning with these targets."""

        # Invoke Deep Agent
        try:
            result = await deep_agent.ainvoke(
                {"messages": [{"role": "user", "content": initial_message}]},
                config=config,
            )

            if self.is_debug:
                print("Deep Agent invocation complete")

            # Extract messages from Deep Agent result
            deep_messages = result.get("messages", [])

            return {
                "deep_agent_result": result,
                "messages": deep_messages,  # Pass through Deep Agent messages
            }
        except Exception as e:
            if self.is_debug:
                print(f"Error invoking Deep Agent: {e}")
            raise


__all__ = ["CCIInterpreterWrapperAgent"]
