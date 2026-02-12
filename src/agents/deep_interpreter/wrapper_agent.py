"""Deep Interpreter Wrapper Agent - Full spatial analysis pipeline with MCP.

This module implements a wrapper agent that manages the complete spatial
analysis pipeline before invoking the Deep Agent for interpretation.

Architecture (8-node graph):
1. check_state: Route to next incomplete phase
2. info_collection: Collect h5ad files, keys, directories from user
3. info_validation: Validate collected information
4. run_analysis_1_8: Execute spatial analysis Steps 1-8 via MCP ReAct agent
5. research_discussion: HITL with 2x interrupt() for cluster/celltype/factor selection
6. run_analysis_9_11: Execute targeted analysis Steps 9-11 via MCP ReAct agent
7. confirm_interpretation: HITL confirmation before expensive Deep Agent invocation
8. invoke_deep_agent: Invoke Deep Agent for interpretation/report generation

MCP Server: sp-enrich-mcp (FastMCP, stdio transport)
Pattern Reference: STPipelineBuilderAgent (st_pipeline_info_agent.py)
"""

import asyncio
import json
import logging
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, ClassVar, Literal

import pandas as pd
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import create_react_agent
from langgraph.store.base import BaseStore
from langgraph.types import interrupt

from src.base import BaseAgent
from src.agents.deep_interpreter.info_extraction import DeepInterpreterInfoExtraction
from src.agents.deep_interpreter.wrapper_state import DeepInterpreterWrapperState

logger = logging.getLogger(__name__)


class DeepInterpreterWrapperAgent(BaseAgent):
    """Wrapper agent for Deep Interpreter with full spatial analysis pipeline.

    Graph Flow:
        START → check_state
          ├─(need_info)──→ info_collection ←─┐
          │                     ↓              │
          │               info_validation ─────┘
          │                     ↓ (complete)
          ├─(info_complete)───→ run_analysis_1_8
          │                          ↓
          ├─(analysis done)──→ research_discussion (2x interrupt() HITL)
          │                          ↓
          ├─(research done)──→ run_analysis_9_11
          │                          ↓
          ├─(9-11 done)──────→ confirm_interpretation (interrupt() HITL)
          │                          ↓
          └─(confirmed)──────→ invoke_deep_agent → END
    """

    NODE_NAMES: ClassVar[dict[str, str]] = {
        "CHECK_STATE": "check_state",
        "INFO_COL": "info_collection",
        "INFO_VAL": "info_validation",
        "RUN_ANALYSIS_1_8": "run_analysis_1_8",
        "RESEARCH_DISCUSSION": "research_discussion",
        "RUN_ANALYSIS_9_11": "run_analysis_9_11",
        "CONFIRM_INTERP": "confirm_interpretation",
        "INVOKE_DEEP": "invoke_deep_agent",
    }

    SYSTEM_TEMPLATE: ClassVar[str] = """You are a Deep Interpreter assistant for spatial transcriptomics analysis.

Your job is to collect essential information from the user to configure the analysis pipeline.

You must collect the following information:

1. **h5ad_files**: Path(s) to .h5ad file(s)
   - Example: "/path/to/n_adata.h5ad"

2. **cluster_key**: Column name in adata.obs for cluster assignments
   - Example: "leiden", "louvain", "clusters"

3. **celltype_key** (optional for Visium, required for MERFISH/Xenium/CosMx/seqFISH):
   - Column name in adata.obs for cell type annotations

4. **sample_key** (required if multiple samples):
   - Column name for sample ID in adata.obs

5. **interest_sample** (optional, for multi-sample datasets):
   - Specific sample to analyze for LIANA+ CCI

6. **data_directory**: Output directory for results (res/ folder)
   - Example: "/path/to/results/res"

## Pre-populated Fields (from Supervisor)
The following may already be available - only ask if missing:
- st_technology: ST platform type
- disease: Disease/phenotype
- species: "human" or "mouse"
- sample_count: Number of samples

## Guidelines

- Ask for h5ad_files and cluster_key first if not provided
- Then ask for data_directory
- If sample_count > 1, ask for sample_key and optionally interest_sample
- For single-cell platforms (MERFISH, Xenium, CosMx, seqFISH), require celltype_key
- Accept various input formats flexibly

## CRITICAL RULES

- DO NOT call the DeepInterpreterInfoExtraction tool until you have at minimum:
  1. h5ad_files (at least one valid path)
  2. cluster_key
  3. data_directory
- Parse all paths as strings
- If user provides all info in one message, call the tool immediately

## Example

User: "I have breast cancer Visium data at /data/n_adata.h5ad, cluster_key='leiden', save to /data/res"
Assistant: [Calls DeepInterpreterInfoExtraction with:
  h5ad_files=["/data/n_adata.h5ad"],
  cluster_key="leiden",
  data_directory="/data/res",
  disease="breast cancer",
  st_technology="Visium"]

After you have confirmed ALL required information, call the DeepInterpreterInfoExtraction tool."""

    def __init__(
        self,
        model: Any,
        state_schema: Any = DeepInterpreterWrapperState,
        config_schema: Any | None = None,
        input_schema: Any | None = None,
        output_schema: Any | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
        store: BaseStore | None = None,
        max_retry_attempts: int = 2,
        agent_name: str | None = None,
        is_debug: bool = True,
        deep_agent_config: Any | None = None,
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
            agent_name=agent_name or "DeepInterpreterWrapperAgent",
            is_debug=is_debug,
        )
        # Bind DeepInterpreterInfoExtraction tool to LLM
        self.llm_with_tool = self.model.bind_tools([DeepInterpreterInfoExtraction])
        # Deep Agent config - store for later use
        self.deep_agent_config = deep_agent_config
        # Deep Agent will be created on-demand
        self._deep_agent = None

    # ===== Helper Methods =====

    def get_deep_agent(self, data_directory: str):
        """Get or create the Deep Agent instance with correct data_dir.

        Creates a fresh Deep Agent with per-invocation config to avoid
        concurrency bugs from mutating shared config.

        Args:
            data_directory: Path to analysis results directory

        Returns:
            Compiled Deep Agent runnable
        """
        from src.agents.deep_interpreter.agent import (
            create_deep_interpreter_agent,
            DeepInterpreterConfig,
        )

        if self.deep_agent_config is not None:
            # Create a copy to avoid mutating shared config
            config_copy = deepcopy(self.deep_agent_config)
            config_copy.data_dir = str(data_directory)
            return create_deep_interpreter_agent(config_copy)
        else:
            config = DeepInterpreterConfig(data_dir=str(data_directory))
            return create_deep_interpreter_agent(config)

    def _build_research_summary(
        self, celltype_csv: pd.DataFrame, factor_csv: pd.DataFrame, state: dict
    ) -> str:
        """Build a summary of analysis results for research discussion.

        Args:
            celltype_csv: DataFrame from sig_clusterwithcelltyp.csv
            factor_csv: DataFrame from res_liana_cluster_factor.csv
            state: Current wrapper state

        Returns:
            Formatted summary string
        """
        summary_parts = []

        # Disease and technology context
        disease = state.get("disease", "unknown")
        st_tech = state.get("st_technology", "unknown")
        summary_parts.append(f"## Analysis Context\n- Disease: {disease}\n- Platform: {st_tech}")

        # Cluster-celltype mapping
        summary_parts.append("\n## Cluster-Cell Type Mapping")
        summary_parts.append(celltype_csv.to_string(index=False))

        # Factor scores
        summary_parts.append("\n## NMF Factor-Cluster Scores")
        summary_parts.append(factor_csv.to_string(index=False))

        return "\n".join(summary_parts)

    def _suggest_factor(
        self, factor_csv: pd.DataFrame, interest_clusters: list[str]
    ) -> str:
        """Suggest the best NMF factor for the selected interest clusters.

        Computes mean factor score across interest_clusters and returns
        the factor with highest mean.

        Args:
            factor_csv: DataFrame from res_liana_cluster_factor.csv
            interest_clusters: List of cluster IDs selected by user

        Returns:
            Factor name with highest mean (e.g. "Factor_3")
        """
        # Filter to interest clusters
        cluster_col = factor_csv.columns[0]  # First column is cluster ID
        factor_cols = [c for c in factor_csv.columns if c.startswith("Factor")]

        if not factor_cols:
            return "Factor_0"

        # Convert cluster column to string for matching (copy to avoid mutating input)
        df = factor_csv.copy()
        df[cluster_col] = df[cluster_col].astype(str)
        filtered = df[df[cluster_col].isin(interest_clusters)]

        if filtered.empty:
            return factor_cols[0]

        # Compute mean score per factor across interest clusters
        means = filtered[factor_cols].mean()
        return str(means.idxmax())

    # ===== Node Initialization =====

    def init_nodes(self, graph: StateGraph):
        """Initialize nodes in the graph."""
        graph.add_node(self.get_node_name("CHECK_STATE"), self.check_state_node)
        graph.add_node(self.get_node_name("INFO_COL"), self.info_collection_node)
        graph.add_node(self.get_node_name("INFO_VAL"), self.info_validation_node)
        graph.add_node(self.get_node_name("RUN_ANALYSIS_1_8"), self.run_analysis_1_8_node)
        graph.add_node(self.get_node_name("RESEARCH_DISCUSSION"), self.research_discussion_node)
        graph.add_node(self.get_node_name("RUN_ANALYSIS_9_11"), self.run_analysis_9_11_node)
        graph.add_node(self.get_node_name("CONFIRM_INTERP"), self.confirm_interpretation_node)
        graph.add_node(self.get_node_name("INVOKE_DEEP"), self.invoke_deep_agent_node)

    def init_edges(self, graph: StateGraph):
        """Initialize edges in the graph."""
        check_state = self.get_node_name("CHECK_STATE")
        info_col = self.get_node_name("INFO_COL")
        info_val = self.get_node_name("INFO_VAL")
        run_1_8 = self.get_node_name("RUN_ANALYSIS_1_8")
        research = self.get_node_name("RESEARCH_DISCUSSION")
        run_9_11 = self.get_node_name("RUN_ANALYSIS_9_11")
        confirm_interp = self.get_node_name("CONFIRM_INTERP")
        invoke_deep = self.get_node_name("INVOKE_DEEP")

        # START → check_state
        graph.add_edge(START, check_state)

        # check_state → conditional routing to next incomplete phase
        graph.add_conditional_edges(
            check_state,
            self.route_after_check,
            [info_col, run_1_8, research, run_9_11, confirm_interp, invoke_deep],
        )

        # info_collection → [END | info_validation | info_collection]
        graph.add_conditional_edges(
            info_col,
            self.get_state,
            [END, info_val, info_col],
        )

        # info_validation → [info_collection | run_analysis_1_8]
        graph.add_conditional_edges(
            info_val,
            self.route_after_validation,
            [info_col, run_1_8],
        )

        # run_analysis_1_8 → research_discussion
        graph.add_edge(run_1_8, research)

        # research_discussion → run_analysis_9_11
        graph.add_edge(research, run_9_11)

        # run_analysis_9_11 → confirm_interpretation
        graph.add_edge(run_9_11, confirm_interp)

        # confirm_interpretation → invoke_deep_agent
        graph.add_edge(confirm_interp, invoke_deep)

        # invoke_deep_agent → END
        graph.add_edge(invoke_deep, END)

    # ===== Routing Functions =====

    def route_after_check(
        self, state: DeepInterpreterWrapperState, config: RunnableConfig  # noqa: ARG002
    ) -> str:
        """Route from check_state to the next incomplete phase."""
        if not state.get("info_complete"):
            return self.get_node_name("INFO_COL")
        if not state.get("analysis_1_8_complete"):
            return self.get_node_name("RUN_ANALYSIS_1_8")
        if not state.get("research_discussion_complete"):
            return self.get_node_name("RESEARCH_DISCUSSION")
        if not state.get("analysis_9_11_complete"):
            return self.get_node_name("RUN_ANALYSIS_9_11")
        if not state.get("interpretation_confirmed"):
            return self.get_node_name("CONFIRM_INTERP")
        return self.get_node_name("INVOKE_DEEP")

    def route_after_validation(
        self, state: DeepInterpreterWrapperState, config: RunnableConfig  # noqa: ARG002
    ) -> str:
        """Route after info_validation: back to info_collection or forward to analysis."""
        if state.get("info_complete"):
            return self.get_node_name("RUN_ANALYSIS_1_8")
        return self.get_node_name("INFO_COL")

    def get_state(
        self, state: DeepInterpreterWrapperState, config: RunnableConfig  # noqa: ARG002
    ) -> Literal["__end__", "info_validation", "info_collection"]:
        """Determine next state based on message type."""
        messages = state["messages"]

        if isinstance(messages[-1], AIMessage) and messages[-1].tool_calls:
            return self.get_node_name("INFO_VAL")

        if not isinstance(messages[-1], HumanMessage):
            return END

        return self.get_node_name("INFO_COL")

    # ===== Node 1: Check State =====

    async def check_state_node(
        self, state: DeepInterpreterWrapperState, config: RunnableConfig  # noqa: ARG002
    ) -> dict:
        """Check current state and route to next incomplete phase.

        This is a pass-through node; routing logic is in route_after_check.
        """
        return {}

    # ===== Node 2: Info Collection =====

    def get_messages_with_system(
        self, messages: list, state: dict
    ) -> list:
        """Combine messages with system template, including pre-populated context."""
        system_content = self.SYSTEM_TEMPLATE

        # Add pre-populated fields context
        pre_populated = []
        if state.get("st_technology"):
            pre_populated.append(f"- st_technology: {state['st_technology']}")
        if state.get("disease"):
            pre_populated.append(f"- disease: {state['disease']}")
        if state.get("species"):
            pre_populated.append(f"- species: {state['species']}")
        if state.get("sample_count"):
            pre_populated.append(f"- sample_count: {state['sample_count']}")

        if pre_populated:
            system_content += f"\n\n## Pre-populated Information (already known)\n" + "\n".join(pre_populated)
            system_content += "\nDo NOT ask the user for these fields again. Include them in the tool call."

        return [SystemMessage(content=system_content)] + messages

    async def info_collection_node(
        self, state: DeepInterpreterWrapperState, config: RunnableConfig  # noqa: ARG002
    ) -> dict:
        """Collect Deep Interpreter analysis information from user."""
        try:
            messages = self.get_messages_with_system(state["messages"], state)
            response = await self.llm_with_tool.ainvoke(messages)
            return {"messages": [response]}
        except Exception as e:
            if self.is_debug:
                print(f"Error in info_collection_node: {e}")
            raise

    # ===== Node 3: Info Validation =====

    async def info_validation_node(
        self, state: DeepInterpreterWrapperState, config: RunnableConfig  # noqa: ARG002
    ) -> dict:
        """Validate and extract information from tool calls."""
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

        # Extract fields
        h5ad_files = tool_args.get("h5ad_files")
        cluster_key = tool_args.get("cluster_key")
        data_directory = tool_args.get("data_directory")

        # Validate required fields
        if not h5ad_files or len(h5ad_files) == 0:
            return {
                "messages": [
                    ToolMessage(
                        content="Error: h5ad_files is required. Please provide path(s) to .h5ad file(s).",
                        tool_call_id=tool_call_id,
                    )
                ],
                "info_complete": False,
            }

        if not cluster_key:
            return {
                "messages": [
                    ToolMessage(
                        content="Error: cluster_key is required. Please provide the column name for cluster assignments.",
                        tool_call_id=tool_call_id,
                    )
                ],
                "info_complete": False,
            }

        if not data_directory:
            return {
                "messages": [
                    ToolMessage(
                        content="Error: data_directory is required. Please provide the output directory path.",
                        tool_call_id=tool_call_id,
                    )
                ],
                "info_complete": False,
            }

        # Validate h5ad paths exist
        resolved_paths = []
        for path_str in h5ad_files:
            p = Path(path_str).expanduser().resolve()
            if not await asyncio.to_thread(p.exists):
                return {
                    "messages": [
                        ToolMessage(
                            content=f"Error: h5ad file not found: {p}. Please check the path.",
                            tool_call_id=tool_call_id,
                        )
                    ],
                    "info_complete": False,
                }
            resolved_paths.append(str(p))

        # Resolve data directory
        data_path = Path(data_directory).expanduser().resolve()
        await asyncio.to_thread(data_path.mkdir, parents=True, exist_ok=True)

        # Extract optional/shared fields
        st_technology = tool_args.get("st_technology") or state.get("st_technology")
        disease = tool_args.get("disease") or state.get("disease")
        species = tool_args.get("species") or state.get("species")
        sample_count = tool_args.get("sample_count") or state.get("sample_count")
        celltype_key = tool_args.get("celltype_key")
        sample_key = tool_args.get("sample_key")
        interest_sample = tool_args.get("interest_sample")

        # Validate sample_key for multi-sample
        if sample_count and sample_count > 1 and not sample_key:
            return {
                "messages": [
                    ToolMessage(
                        content="Error: sample_key is required when sample_count > 1. Please provide the sample column name.",
                        tool_call_id=tool_call_id,
                    )
                ],
                "info_complete": False,
            }

        if self.is_debug:
            print("Info collection complete:")
            print(f"  h5ad_files: {resolved_paths}")
            print(f"  cluster_key: {cluster_key}")
            print(f"  data_directory: {data_path}")
            print(f"  st_technology: {st_technology}")

        return {
            "messages": [
                ToolMessage(
                    content=(
                        f"Configuration collected:\n"
                        f"- h5ad files: {resolved_paths}\n"
                        f"- cluster_key: {cluster_key}\n"
                        f"- data_directory: {data_path}\n"
                        f"- st_technology: {st_technology}\n"
                        f"- disease: {disease}\n"
                        f"\nProceeding to spatial analysis pipeline (Steps 1-8)..."
                    ),
                    tool_call_id=tool_call_id,
                )
            ],
            "h5ad_files": resolved_paths,
            "cluster_key": cluster_key,
            "celltype_key": celltype_key,
            "sample_key": sample_key,
            "interest_sample": interest_sample,
            "data_directory": str(data_path),
            "st_technology": st_technology,
            "disease": disease,
            "species": species,
            "sample_count": sample_count,
            "info_complete": True,
        }

    # ===== Node 4: Run Analysis Steps 1-8 (MCP ReAct Agent) =====

    async def run_analysis_1_8_node(
        self, state: DeepInterpreterWrapperState, config: RunnableConfig
    ) -> dict:
        """Execute spatial analysis Steps 1-8 via MCP ReAct agent.

        Steps:
        1. plot_cluster - Spatial clustering visualization
        2. runplot_clusterwithcelltyp - Cluster-celltype heatmap
        3. plot_neighborhood_enrichment - Neighborhood enrichment
        4. runplot_pathway_enrich - Pathway enrichment (decoupler)
        5. runplot_spatial_relationship - Spatial relationships (MISTy)
        6. run_lianap - LIANA+ CCI analysis (produces lrdata.h5ad)
        7. runplot_liana_factorscore - NMF factor scores
        8. runplot_liana_loadings - NMF loadings
        """
        # Derive parameters from state
        filename = state["h5ad_files"][0]
        organism = state.get("species") or "human"
        cluster_key = state["cluster_key"]
        celltype_key = state.get("celltype_key")
        sample_key = state.get("sample_key")
        interest_sample = state.get("interest_sample")
        save_path = state["data_directory"]
        lrdata_path = f"{save_path}/lrdata.h5ad"

        # Build Step 2 and Step 5 blocks - always included
        # Both MCP tools accept celltype_key=None and fall back to adata.obsm['compositions'] for Visium
        if celltype_key:
            celltype_param_step2 = f', celltype_key="{celltype_key}"'
            celltype_param_step5 = f', celltype_key="{celltype_key}"'
        else:
            celltype_param_step2 = ""
            celltype_param_step5 = ""

        step2_block = f"""
**Step 2**: Call `runplot_clusterwithcelltyp`
  - filename="{filename}", cluster_key="{cluster_key}"{celltype_param_step2}, save_path="{save_path}"
"""
        step5_block = f"""
**Step 5**: Call `runplot_spatial_relationship`
  - filename="{filename}", cluster_key="{cluster_key}"{celltype_param_step5}, organism="{organism}", geneset="progeny", save_path="{save_path}"
"""
        skipped_steps_note = ""

        # Build system prompt for ReAct agent
        analysis_prompt = f"""You are a spatial transcriptomics analysis executor.
Execute the following 8 analysis steps IN ORDER using the available MCP tools.
Wait for each step to complete before starting the next.

## Parameters
- filename: {filename}
- organism: {organism}
- cluster_key: {cluster_key}
- celltype_key: {celltype_key if celltype_key else "N/A (spot-based platform)"}
- sample_key: {sample_key if sample_key else "None"}
- interest_sample: {interest_sample if interest_sample else "None"}
- save_path: {save_path}
- geneset: progeny

## Execution Sequence

**Step 1**: Call `plot_cluster`
  - filename="{filename}", cluster_key="{cluster_key}"{f', sample_key="{sample_key}"' if sample_key else ''}, save_path="{save_path}"

{step2_block}

**Step 3**: Call `plot_neighborhood_enrichment`
  - filename="{filename}", cluster_key="{cluster_key}", save_path="{save_path}"

**Step 4**: Call `runplot_pathway_enrich`
  - filename="{filename}", cluster_key="{cluster_key}", organism="{organism}", geneset="progeny", save_path="{save_path}"

{step5_block}

**Step 6**: Call `run_lianap` (THIS MAY TAKE 10+ MINUTES - be patient)
  - filename="{filename}", organism="{organism}", platform="auto"{f', sample_key="{sample_key}"' if sample_key else ''}{f', interest_sample="{interest_sample}"' if interest_sample else ''}, save_path="{save_path}"

**Step 7**: Call `runplot_liana_factorscore`
  - filename="{lrdata_path}", cluster_key="{cluster_key}"{f', sample_key="{sample_key}"' if sample_key else ''}, save_path="{save_path}"

**Step 8**: Call `runplot_liana_loadings`
  - filename="{lrdata_path}", organism="{organism}", geneset="progeny", save_path="{save_path}"

## Important Notes
- Execute steps sequentially, waiting for each to complete
- Step 6 (run_lianap) produces lrdata.h5ad which is required for Steps 7-8
- Steps 7-8 use lrdata.h5ad as input (path: {lrdata_path})
- If a step fails, log the error and continue to the next step
- Report completion status for all steps at the end{skipped_steps_note}"""

        # Get MCP server paths from environment
        sp_python = os.getenv("SP_ENRICH_MCP_PYTHON")
        sp_server_path = os.getenv("SP_ENRICH_MCP_SERVER_PATH")

        if not sp_python or not sp_server_path:
            raise ValueError(
                "SP_ENRICH_MCP_PYTHON and SP_ENRICH_MCP_SERVER_PATH environment variables must be set"
            )

        if self.is_debug:
            print(f"Starting analysis Steps 1-8 for {filename}")
            print(f"  MCP Python: {sp_python}")
            print(f"  MCP Server: {sp_server_path}/server.py")

        # Initialize MCP client per-node
        mcp_client = MultiServerMCPClient(
            {
                "sp-enrich-mcp": {
                    "command": sp_python,
                    "args": [f"{sp_server_path}/server.py"],
                    "transport": "stdio",
                }
            }
        )
        tools = await mcp_client.get_tools()

        if self.is_debug:
            print(f"  MCP tools available: {[t.name for t in tools]}")

        # Create ReAct agent
        agent = create_react_agent(
            model=self.model,
            tools=tools,
            prompt=analysis_prompt,
            checkpointer=MemorySaver(),
        )

        # Execute with high recursion limit (Step 6 can take many turns)
        react_config = {
            "recursion_limit": 50,
            "configurable": {
                "thread_id": config.get("configurable", {}).get("thread_id", "analysis_1_8")
            },
        }

        result = await agent.ainvoke(
            {"messages": [HumanMessage(content="Execute all 8 analysis steps now.")]},
            config=react_config,
        )

        if self.is_debug:
            print("Steps 1-8 completed")

        # Extract last AI message as summary
        result_messages = result.get("messages", [])
        summary = "Spatial analysis Steps 1-8 completed."
        for msg in reversed(result_messages):
            if isinstance(msg, AIMessage) and msg.content:
                summary = str(msg.content)
                break

        return {
            "analysis_1_8_complete": True,
            "messages": [AIMessage(content=summary)],
        }

    # ===== Node 5: Research Discussion (HITL with 2x interrupt()) =====

    async def research_discussion_node(
        self, state: DeepInterpreterWrapperState, config: RunnableConfig  # noqa: ARG002
    ) -> dict:
        """HITL research discussion with 2 sequential interrupt() calls.

        Phase A: LLM reads CSVs and prepares summary
        Phase B: interrupt() #1 - Confirm interest_celltypes + interest_clusters
        Phase C: interrupt() #2 - Confirm sel_factor
        """
        save_path = state["data_directory"]

        # Phase A: Read analysis outputs and build summary
        try:
            celltype_csv = pd.read_csv(f"{save_path}/sig_clusterwithcelltyp.csv")
        except FileNotFoundError:
            celltype_csv = pd.DataFrame({"note": ["celltype analysis was skipped (no celltype_key)"]})

        try:
            factor_csv = pd.read_csv(f"{save_path}/res_liana_cluster_factor.csv")
        except FileNotFoundError:
            raise ValueError(
                f"res_liana_cluster_factor.csv not found in {save_path}. "
                "Steps 1-8 may not have completed successfully."
            )

        summary = self._build_research_summary(celltype_csv, factor_csv, state)

        # LLM suggests interest_clusters and interest_celltypes based on disease context
        disease = state.get("disease", "unknown")
        llm_suggestion = await self.model.ainvoke([
            SystemMessage(content=(
                f"You are analyzing {disease} spatial transcriptomics data. "
                "Based on the analysis summary below, suggest which clusters and cell types "
                "are most relevant for investigating cell-cell interactions in this disease context. "
                "Be specific about WHY each cluster/celltype is interesting."
            )),
            HumanMessage(content=f"Analysis results:\n{summary}\n\nSuggest interest clusters and cell types."),
        ])

        # Phase B: interrupt() #1 - Confirm interest_celltypes + interest_clusters
        prompt1 = f"""## Analysis Summary
{summary}

## AI Suggestion
{llm_suggestion.content}

Please review the image at: `{save_path}/2.celltype_heatmap_analysis.png`

**Confirm or modify:**
- interest_celltypes: (e.g., ["Invasive Tumor", "Fibroblast", "Macrophage"])
- interest_clusters: (e.g., ["4", "16", "17"])

Please provide your selections as JSON or natural language."""

        response1 = interrupt(value={"message": prompt1})

        # Parse response1
        if isinstance(response1, dict):
            actual_response1 = response1.get("response", response1.get("message", str(response1)))
        else:
            actual_response1 = str(response1)

        # Use LLM to extract structured data from user response
        parse_result1 = await self.model.ainvoke([
            SystemMessage(content=(
                "Extract interest_celltypes and interest_clusters from the user's response. "
                "Return ONLY valid JSON: {\"interest_celltypes\": [...], \"interest_clusters\": [...]}\n"
                "Cluster IDs must be strings (e.g. \"4\" not 4)."
            )),
            HumanMessage(content=actual_response1),
        ])

        try:
            parsed1 = json.loads(parse_result1.content)
            parsed_celltypes = parsed1.get("interest_celltypes", [])
            parsed_clusters = parsed1.get("interest_clusters", [])
        except (json.JSONDecodeError, AttributeError):
            # Fallback: use LLM suggestion
            parsed_celltypes = []
            parsed_clusters = []

        # Phase C: interrupt() #2 - Confirm sel_factor
        sel_factor_suggestion = self._suggest_factor(factor_csv, parsed_clusters)
        available_factors = [c for c in factor_csv.columns if c.startswith("Factor")]

        prompt2 = f"""Please review the image at: `{save_path}/7.factor_spatial_NMF.png`

Based on the cluster-factor analysis, **{sel_factor_suggestion}** has the highest association with your selected clusters {parsed_clusters}.

Available factors: {available_factors}
**Confirm or modify sel_factor:**"""

        response2 = interrupt(value={"message": prompt2})

        if isinstance(response2, dict):
            actual_response2 = response2.get("response", response2.get("message", str(response2)))
        else:
            actual_response2 = str(response2)

        # Parse factor selection
        parsed_factor = sel_factor_suggestion  # default
        response2_lower = actual_response2.lower().strip()
        if "factor" in response2_lower:
            # Extract factor name (e.g. "Factor_3")
            match = re.search(r"factor[_\s]?(\d+)", response2_lower)
            if match:
                candidate = f"Factor_{match.group(1)}"
                if candidate in available_factors:
                    parsed_factor = candidate
                # else: keep sel_factor_suggestion (auto-detected best factor)
        elif response2_lower in ("yes", "ok", "confirm", "y", "sure", "accepted"):
            parsed_factor = sel_factor_suggestion

        if self.is_debug:
            print(f"Research discussion complete:")
            print(f"  interest_celltypes: {parsed_celltypes}")
            print(f"  interest_clusters: {parsed_clusters}")
            print(f"  sel_factor: {parsed_factor}")

        return {
            "interest_celltypes": parsed_celltypes,
            "interest_clusters": parsed_clusters,
            "sel_factor": parsed_factor,
            "research_discussion_complete": True,
            "messages": [
                HumanMessage(content=actual_response1),
                HumanMessage(content=actual_response2),
            ],
        }

    # ===== Node 6: Run Analysis Steps 9-11 (MCP ReAct Agent) =====

    async def run_analysis_9_11_node(
        self, state: DeepInterpreterWrapperState, config: RunnableConfig
    ) -> dict:
        """Execute targeted analysis Steps 9-11 via MCP ReAct agent.

        Steps:
        9. plot_liana_nmf - Quadrant plot with NMF factor analysis
        10. plot_liana_spatial_interections - Spatial LR interaction plots
        11. plot_liana_interections - Cluster-level LR interaction plots
        """
        save_path = state["data_directory"]
        lrdata_path = f"{save_path}/lrdata.h5ad"
        csv_path = f"{save_path}/sig_liana.csv"
        cluster_key = state["cluster_key"]
        sample_key = state.get("sample_key")
        sel_interest_cluster = state["interest_clusters"]
        sel_factor = state["sel_factor"]

        # Validate sel_factor exists in the actual data
        try:
            sig_headers = pd.read_csv(csv_path, index_col=0, nrows=0)
            available_factors = [c for c in sig_headers.columns if c.startswith("Factor")]
            if sel_factor not in available_factors and available_factors:
                sel_factor = available_factors[0]
        except FileNotFoundError:
            pass  # Let the MCP tool handle missing file

        # Build system prompt for ReAct agent
        analysis_prompt = f"""You are a spatial transcriptomics analysis executor.
Execute the following 3 analysis steps IN ORDER using the available MCP tools.

## Parameters
- lrdata_path: {lrdata_path}
- csv_path: {csv_path}
- cluster_key: {cluster_key}
- sample_key: {sample_key if sample_key else "None"}
- sel_interest_cluster: {json.dumps(sel_interest_cluster)}
- sel_factor: {sel_factor}
- save_path: {save_path}

## Execution Sequence

**Step 9**: Call `plot_liana_nmf`
  - lrdata_path="{lrdata_path}"
  - csv_path="{csv_path}"
  - cluster_key="{cluster_key}"
  - sel_interest_cluster={json.dumps(sel_interest_cluster)}
  - sel_factor="{sel_factor}"
  - save_path="{save_path}"

After Step 9 completes, read the file `{save_path}/sel_interest_sig_liana.csv` to extract the `interaction` column values. These will be used as `sel_interactions` for Steps 10-11.

**Step 10**: Call `plot_liana_spatial_interections`
  - filename="{lrdata_path}"
  - sel_interactions=[extracted from Step 9 output CSV]
  - cluster_key="{cluster_key}"
  {f'- sample_key="{sample_key}"' if sample_key else ''}
  - save_path="{save_path}"

**Step 11**: Call `plot_liana_interections`
  - filename="{lrdata_path}"
  - cluster_key="{cluster_key}"
  - sel_interactions=[same as Step 10]
  - sel_interest_cluster={json.dumps(sel_interest_cluster)}
  {f'- sample_key="{sample_key}"' if sample_key else ''}
  - save_path="{save_path}"

## Important
- Step 9 internally creates sel_interest_sig_liana.csv - read it to get sel_interactions
- The interaction column contains values like "GeneA^GeneB" - pass them as a list
- Execute steps sequentially"""

        # Get MCP server paths
        sp_python = os.getenv("SP_ENRICH_MCP_PYTHON")
        sp_server_path = os.getenv("SP_ENRICH_MCP_SERVER_PATH")

        if not sp_python or not sp_server_path:
            raise ValueError(
                "SP_ENRICH_MCP_PYTHON and SP_ENRICH_MCP_SERVER_PATH environment variables must be set"
            )

        if self.is_debug:
            print(f"Starting analysis Steps 9-11")
            print(f"  sel_interest_cluster: {sel_interest_cluster}")
            print(f"  sel_factor: {sel_factor}")

        # Initialize MCP client per-node
        mcp_client = MultiServerMCPClient(
            {
                "sp-enrich-mcp": {
                    "command": sp_python,
                    "args": [f"{sp_server_path}/server.py"],
                    "transport": "stdio",
                }
            }
        )
        tools = await mcp_client.get_tools()

        agent = create_react_agent(
            model=self.model,
            tools=tools,
            prompt=analysis_prompt,
            checkpointer=MemorySaver(),
        )

        react_config = {
            "recursion_limit": 30,
            "configurable": {
                "thread_id": config.get("configurable", {}).get("thread_id", "analysis_9_11")
            },
        }

        result = await agent.ainvoke(
            {"messages": [HumanMessage(content="Execute Steps 9-11 now.")]},
            config=react_config,
        )

        if self.is_debug:
            print("Steps 9-11 completed")

        result_messages = result.get("messages", [])
        summary = "Targeted analysis Steps 9-11 completed."
        for msg in reversed(result_messages):
            if isinstance(msg, AIMessage) and msg.content:
                summary = str(msg.content)
                break

        return {
            "analysis_9_11_complete": True,
            "messages": [AIMessage(content=summary)],
        }

    # ===== Node 7: Confirm Interpretation (HITL) =====

    async def confirm_interpretation_node(
        self, state: DeepInterpreterWrapperState, config: RunnableConfig  # noqa: ARG002
    ) -> dict:
        """HITL confirmation before invoking the expensive Deep Agent pipeline.

        Uses interrupt() to ask the user whether to proceed with full
        interpretation after all analysis steps (1-11) are complete.
        """
        save_path = state["data_directory"]
        prompt = (
            f"모든 분석이 완료되었습니다 (Steps 1-11).\n"
            f"결과 디렉토리: `{save_path}`\n\n"
            f"본격적으로 결과를 해석하길 원하십니까?\n"
            f"(Deep Interpreter가 문헌 검색 및 해석 리포트를 생성합니다)\n\n"
            f"진행하려면 'yes'를 입력하세요."
        )
        response = interrupt(value={"message": prompt})
        # Any response proceeds (the interrupt itself is the gate)
        return {
            "interpretation_confirmed": True,
            "messages": [HumanMessage(content=str(response))],
        }

    # ===== Node 8: Invoke Deep Agent =====

    async def invoke_deep_agent_node(
        self, state: DeepInterpreterWrapperState, config: RunnableConfig
    ) -> dict:
        """Invoke the Deep Agent for CCI interpretation and report generation.

        Creates a per-invocation Deep Agent with fresh config to avoid
        concurrency issues from mutating shared config.
        """
        data_directory = state.get("data_directory")
        if not data_directory:
            raise ValueError("data_directory is required but not set in state")

        if self.is_debug:
            print(f"Invoking Deep Agent for: {data_directory}")

        # Get or create Deep Agent with per-invocation config
        deep_agent = self.get_deep_agent(data_directory)

        # Build initial message with embedded targets
        targets_content = {
            "interest_clusters": state.get("interest_clusters"),
            "interest_celltypes": state.get("interest_celltypes"),
            "sel_factor": state.get("sel_factor"),
            "data_directory": str(data_directory),
        }

        initial_message = f"""Interpret the CCI analysis results in {data_directory}.

## PRE-SELECTED TARGET CONFIGURATION
The following targets have been pre-selected by the user (DO NOT ask for user input):

```json
{json.dumps(targets_content, indent=2)}
```

IMPORTANT: The planner subagent will parse the targets from this message and write /targets.json to the virtual filesystem.
After target confirmation, proceed directly to strategic planning with these targets."""

        try:
            result = await deep_agent.ainvoke(
                {"messages": [{"role": "user", "content": initial_message}]},
                config=config,
            )

            if self.is_debug:
                print("Deep Agent invocation complete")

            deep_messages = result.get("messages", [])

            try:
                result_summary = {
                    "status": "completed",
                    "message_count": len(deep_messages),
                }
                serialized_result = json.dumps(result_summary)
            except (TypeError, ValueError):
                serialized_result = json.dumps({"status": "completed"})

            # Convert to safe AIMessage summaries for checkpoint serialization
            safe_messages = []
            for msg in deep_messages:
                try:
                    if hasattr(msg, "content") and msg.content:
                        safe_messages.append(AIMessage(content=str(msg.content)))
                except Exception:
                    continue

            if not safe_messages:
                safe_messages = [AIMessage(content="Deep Interpreter analysis completed.")]

            return {
                "deep_agent_result": serialized_result,
                "messages": safe_messages,
            }
        except Exception as e:
            if self.is_debug:
                print(f"Error invoking Deep Agent: {e}")
            raise


__all__ = ["DeepInterpreterWrapperAgent"]
