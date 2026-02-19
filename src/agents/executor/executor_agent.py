"""Pipeline Executor Agent — runs the 3-step ST pipeline via MCP tools.

Takes a ``PipelineConfig`` (from pipeline_builder), dynamically loads the
correct MCP server for each step, handles SC reference resolution for
spot-based platforms, and cascades h5ad outputs between steps.

Graph (7-node sequential):
    START → validate_inputs
              ├─(no pipeline_config)──────────────────────→ save_results → END
              ├─(h5ad missing)→ collect_h5ad → validate_inputs
              └─(valid)→ resolve_sc_reference → execute_normalization
                                                  ├─(celltype skipped)→ execute_spatial_clustering
                                                  └─(normal)→ execute_celltype_analysis
                                                                → execute_spatial_clustering
                                                                    → save_results → END
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, ClassVar

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import create_react_agent
from langgraph.types import interrupt

from src.base import BaseAgent
from src.agents.executor.executor_state import (
    ExecutionStepResult,
    PipelineExecutorState,
    SCReferenceInfo,
)
from src.agents.executor.mcp_registry import (
    get_mcp_server_config,
    get_sc_reference_server_config,
    is_deconvolution_method,
)

logger = logging.getLogger(__name__)


class PipelineExecutorAgent(BaseAgent):
    """Executes a 3-step ST pipeline (normalize -> celltype -> clustering).

    Each step is run via a dedicated MCP server resolved from
    :mod:`mcp_registry`. MCP client lifetime is scoped to a single step
    using direct ``MultiServerMCPClient(...)`` instantiation (v0.1.0+ API;
    context manager raises ``NotImplementedError``).
    """

    NODE_NAMES: ClassVar[dict[str, str]] = {
        "VALIDATE_INPUTS": "validate_inputs",
        "COLLECT_H5AD": "collect_h5ad_info",
        "RESOLVE_SC_REF": "resolve_sc_reference",
        "EXEC_NORM": "execute_normalization",
        "EXEC_CELLTYPE": "execute_celltype_analysis",
        "EXEC_CLUSTERING": "execute_spatial_clustering",
        "SAVE_RESULTS": "save_results",
    }

    def __init__(
        self,
        model: Any,
        state_schema: Any = PipelineExecutorState,
        config_schema: Any | None = None,
        input_schema: Any | None = None,
        output_schema: Any | None = None,
        checkpointer: Any | None = None,
        store: Any | None = None,
        max_retry_attempts: int = 2,
        agent_name: str | None = None,
        is_debug: bool = True,
    ) -> None:
        super().__init__(
            model=model,
            state_schema=state_schema,
            config_schema=config_schema,
            input_schema=input_schema,
            output_schema=output_schema,
            checkpointer=checkpointer,
            store=store,
            max_retry_attempts=max_retry_attempts,
            agent_name=agent_name or "PipelineExecutorAgent",
            is_debug=is_debug,
        )

    # ================================================================
    # Graph wiring
    # ================================================================

    def init_nodes(self, graph: StateGraph):
        graph.add_node(self.get_node_name("VALIDATE_INPUTS"), self.validate_inputs_node)
        graph.add_node(self.get_node_name("COLLECT_H5AD"), self.collect_h5ad_info_node)
        graph.add_node(self.get_node_name("RESOLVE_SC_REF"), self.resolve_sc_reference_node)
        graph.add_node(self.get_node_name("EXEC_NORM"), self.execute_normalization_node)
        graph.add_node(self.get_node_name("EXEC_CELLTYPE"), self.execute_celltype_analysis_node)
        graph.add_node(self.get_node_name("EXEC_CLUSTERING"), self.execute_spatial_clustering_node)
        graph.add_node(self.get_node_name("SAVE_RESULTS"), self.save_results_node)

    def init_edges(self, graph: StateGraph):
        validate = self.get_node_name("VALIDATE_INPUTS")
        collect = self.get_node_name("COLLECT_H5AD")
        sc_ref = self.get_node_name("RESOLVE_SC_REF")
        norm = self.get_node_name("EXEC_NORM")
        celltype = self.get_node_name("EXEC_CELLTYPE")
        clustering = self.get_node_name("EXEC_CLUSTERING")
        save = self.get_node_name("SAVE_RESULTS")

        # START → validate_inputs
        graph.add_edge(START, validate)

        # validate_inputs → 3-way conditional
        graph.add_conditional_edges(
            validate,
            self.route_after_validate,
            [save, collect, sc_ref],
        )

        # collect_h5ad → validate_inputs (re-validate after user provides path)
        graph.add_edge(collect, validate)

        # resolve_sc_reference → normalization
        graph.add_edge(sc_ref, norm)

        # normalization → conditional (celltype or skip to clustering)
        graph.add_conditional_edges(
            norm,
            self.route_after_normalization,
            [celltype, clustering],
        )

        # celltype → clustering
        graph.add_edge(celltype, clustering)

        # clustering → save_results
        graph.add_edge(clustering, save)

        # save_results → END
        graph.add_edge(save, END)

    # ================================================================
    # Routing (sync — required by LangGraph)
    # ================================================================

    def route_after_validate(
        self, state: PipelineExecutorState, config: RunnableConfig,  # noqa: ARG002
    ) -> str:
        """After validation: no config → save, no h5ad → collect, else → sc_ref."""
        if not state.get("pipeline_config"):
            return self.get_node_name("SAVE_RESULTS")
        if not state.get("h5ad_input_path"):
            return self.get_node_name("COLLECT_H5AD")
        return self.get_node_name("RESOLVE_SC_REF")

    def route_after_normalization(
        self, state: PipelineExecutorState, config: RunnableConfig,  # noqa: ARG002
    ) -> str:
        """After normalization: skip celltype if already marked skipped."""
        for r in state.get("step_results", []):
            if r.get("step") == "celltype_analysis" and r.get("status") == "skipped":
                return self.get_node_name("EXEC_CLUSTERING")
        return self.get_node_name("EXEC_CELLTYPE")

    # ---- validate_inputs ----

    async def validate_inputs_node(
        self, state: PipelineExecutorState, config: RunnableConfig,  # noqa: ARG002
    ) -> dict:
        """Validate PipelineConfig and determine SC reference requirements."""
        pc = state.get("pipeline_config")
        if not pc:
            return {
                "messages": [AIMessage(content="Error: No pipeline_config provided.")],
            }

        h5ad_path = state.get("h5ad_input_path")

        # Determine if SC reference is needed
        celltype_method = pc.get("celltype_analysis", "")
        platform = pc.get("platform_type", state.get("platform_type", ""))
        sc_needed = (
            platform == "spot-based"
            and is_deconvolution_method(celltype_method)
        )

        # Set up output directory based on h5ad location
        output_dir = None
        if h5ad_path:
            output_dir = str(Path(h5ad_path).parent / "executor_output")

        updates: dict[str, Any] = {
            "sc_reference_needed": sc_needed,
            "step_results": state.get("step_results") or [],
            "platform_type": platform or state.get("platform_type"),
        }

        if h5ad_path:
            updates["output_directory"] = output_dir
            updates["messages"] = [
                AIMessage(content=f"Inputs validated. h5ad: {h5ad_path}, SC ref needed: {sc_needed}")
            ]
        # else: h5ad missing — route_after_validate will send to collect

        if self.is_debug:
            logger.info("validate_inputs: h5ad=%s, sc_needed=%s", h5ad_path, sc_needed)

        return updates

    # ---- collect_h5ad_info ----

    async def collect_h5ad_info_node(
        self, state: PipelineExecutorState, config: RunnableConfig,  # noqa: ARG002
    ) -> dict:
        """HITL: ask user for the path to their h5ad file."""
        response = interrupt(value={
            "message": (
                "**h5ad file path required**\n\n"
                "Please provide the full path to your spatial transcriptomics "
                "h5ad file (e.g., `/data/visium_sample.h5ad`)."
            ),
        })

        actual = str(response.get("response", response) if isinstance(response, dict) else response)
        h5ad_path = actual.strip()

        output_dir = str(Path(h5ad_path).parent / "executor_output")

        return {
            "h5ad_input_path": h5ad_path,
            "output_directory": output_dir,
            "messages": [HumanMessage(content=f"h5ad path: {h5ad_path}")],
        }

    # ---- resolve_sc_reference ----

    async def resolve_sc_reference_node(
        self, state: PipelineExecutorState, config: RunnableConfig,
    ) -> dict:
        """Resolve SC reference: auto-recommend via MCP + HITL selection.

        Skip protection: if user skips AND celltype method is deconvolution,
        auto-skip the celltype step entirely.
        """
        if not state.get("sc_reference_needed"):
            return {}

        # Try auto-recommendation via MCP
        candidates: list[dict] = []
        try:
            server_key, server_config = get_sc_reference_server_config()
            from langchain_mcp_adapters.client import MultiServerMCPClient

            client = MultiServerMCPClient({server_key: server_config})
            tools = await client.get_tools()
            agent = create_react_agent(
                model=self.get_model(config),
                tools=tools,
                prompt=(
                    f"Find single-cell reference datasets for "
                    f"{state.get('species', 'human')} {state.get('disease', 'tissue')} "
                    f"using {state.get('st_technology', 'spatial')} platform. "
                    f"Return candidate dataset names and paths."
                ),
                checkpointer=MemorySaver(),
            )
            result = await agent.ainvoke(
                {"messages": [HumanMessage(content="Find SC reference datasets")]},
                config={"configurable": {"thread_id": "sc-ref-search"}},
            )
            # Parse candidates from result (best-effort)
            for msg in reversed(result.get("messages", [])):
                if isinstance(msg, AIMessage) and msg.content:
                    candidates.append({"name": "auto-recommended", "description": msg.content})
                    break
        except Exception as e:
            if self.is_debug:
                logger.warning("SC reference auto-recommendation failed: %s", e)

        # HITL: let user choose or provide their own path
        candidate_text = ""
        if candidates:
            candidate_text = "\n\nAuto-recommended candidates:\n"
            for i, c in enumerate(candidates):
                candidate_text += f"  {i+1}. {c.get('name', 'unknown')}: {c.get('description', '')[:200]}\n"

        response = interrupt(value={
            "message": (
                f"**Single-cell reference dataset required**\n\n"
                f"Your celltype analysis method requires a SC reference dataset."
                f"{candidate_text}\n"
                f"Please provide the path to your SC reference h5ad file, "
                f"or type 'skip' to skip cell type analysis."
            ),
        })

        actual = str(response.get("response", response) if isinstance(response, dict) else response)

        if actual.lower().strip() in ("skip", "no", "none"):
            # Skip protection: if deconvolution, auto-skip celltype step
            pc = state.get("pipeline_config", {})
            celltype_method = pc.get("celltype_analysis", "")

            updates: dict[str, Any] = {
                "sc_reference_path": None,
                "messages": [HumanMessage(content="User skipped SC reference.")],
            }

            if is_deconvolution_method(celltype_method):
                skip_result = ExecutionStepResult(
                    step="celltype_analysis",
                    method=celltype_method,
                    status="skipped",
                    message="Skipped: SC reference required for deconvolution but user declined.",
                )
                current_results = list(state.get("step_results") or [])
                current_results.append(skip_result.model_dump())
                updates["step_results"] = current_results
                updates["messages"] = [
                    HumanMessage(content="SC reference skipped — celltype analysis auto-skipped (deconvolution requires SC ref).")
                ]
                if self.is_debug:
                    logger.info("SC ref skipped + deconvolution method → celltype auto-skipped")

            return updates

        # User provided a path
        sc_path = actual.strip()
        sc_info = SCReferenceInfo(name="user-provided", path=sc_path, source="user")

        return {
            "sc_reference_path": sc_path,
            "sc_reference_candidates": [sc_info.model_dump()],
            "messages": [HumanMessage(content=f"SC reference: {sc_path}")],
        }

    # ---- Pipeline execution steps ----

    async def _run_mcp_step(
        self,
        state: PipelineExecutorState,
        config: RunnableConfig,
        step: str,
        method: str,
        input_h5ad: str,
        extra_prompt: str = "",
    ) -> ExecutionStepResult:
        """Run a single pipeline step via its MCP server.

        The MCP client is created directly (v0.1.0+ API; context manager
        raises ``NotImplementedError``). Sessions are ephemeral.
        """
        try:
            server_key, server_config = get_mcp_server_config(step, method)
        except KeyError as e:
            return ExecutionStepResult(
                step=step, method=method, status="failed", error=str(e),
            )

        output_dir = state.get("output_directory", "/tmp/executor_output")
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        expected_output = str(Path(output_dir) / f"{step}_{method.lower()}.h5ad")

        prompt = (
            f"Execute {step} using {method} on the h5ad file at: {input_h5ad}\n"
            f"Save the output to: {expected_output}\n"
            f"Platform: {state.get('platform_type', 'unknown')}\n"
            f"Technology: {state.get('st_technology', 'unknown')}\n"
            f"Species: {state.get('species', 'unknown')}\n"
        )
        if extra_prompt:
            prompt += f"\n{extra_prompt}"

        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient

            client = MultiServerMCPClient({server_key: server_config})
            tools = await client.get_tools()
            agent = create_react_agent(
                model=self.get_model(config),
                tools=tools,
                prompt=prompt,
                checkpointer=MemorySaver(),
            )
            thread_id = config.get("configurable", {}).get("thread_id", "default")
            await agent.ainvoke(
                {"messages": [HumanMessage(content=f"Run {step}: {method}")]},
                config={"configurable": {"thread_id": f"{thread_id}-{step}"}},
            )

            return ExecutionStepResult(
                step=step,
                method=method,
                status="ok",
                output_h5ad=expected_output,
            )

        except Exception as e:
            if self.is_debug:
                logger.error("MCP step %s/%s failed: %s", step, method, e)
            return ExecutionStepResult(
                step=step, method=method, status="failed", error=str(e),
            )

    def _get_cascading_input(self, state: PipelineExecutorState) -> str:
        """Get the best available input h5ad: latest output or original."""
        # Prefer cascading output from previous step
        output = state.get("output_h5ad_path")
        if output and Path(output).exists():
            return output
        # Fallback to original input
        return state.get("h5ad_input_path", "")

    async def execute_normalization_node(
        self, state: PipelineExecutorState, config: RunnableConfig,
    ) -> dict:
        """Execute normalization step."""
        pc = state.get("pipeline_config", {})
        method = pc.get("normalization", "log")
        input_h5ad = state.get("h5ad_input_path", "")

        if not input_h5ad or not Path(input_h5ad).exists():
            result = ExecutionStepResult(
                step="normalization", method=method, status="failed",
                error=f"Input h5ad not found: {input_h5ad}",
            )
        else:
            result = await self._run_mcp_step(state, config, "normalization", method, input_h5ad)

        current_results = list(state.get("step_results") or [])
        current_results.append(result.model_dump())

        updates: dict[str, Any] = {
            "step_results": current_results,
            "current_step": "normalization",
            "messages": [AIMessage(content=f"Normalization ({method}): {result.status}")],
        }
        if result.output_h5ad:
            updates["output_h5ad_path"] = result.output_h5ad

        return updates

    async def execute_celltype_analysis_node(
        self, state: PipelineExecutorState, config: RunnableConfig,
    ) -> dict:
        """Execute cell type analysis step."""
        pc = state.get("pipeline_config", {})
        method = pc.get("celltype_analysis", "")
        input_h5ad = self._get_cascading_input(state)

        extra_prompt = ""
        if state.get("sc_reference_path"):
            extra_prompt = f"SC reference dataset: {state['sc_reference_path']}"

        if not input_h5ad:
            result = ExecutionStepResult(
                step="celltype_analysis", method=method, status="failed",
                error="No input h5ad available for celltype analysis.",
            )
        else:
            result = await self._run_mcp_step(
                state, config, "celltype_analysis", method, input_h5ad,
                extra_prompt=extra_prompt,
            )

        current_results = list(state.get("step_results") or [])
        current_results.append(result.model_dump())

        updates: dict[str, Any] = {
            "step_results": current_results,
            "current_step": "celltype_analysis",
            "messages": [AIMessage(content=f"Cell type analysis ({method}): {result.status}")],
        }
        if result.output_h5ad:
            updates["output_h5ad_path"] = result.output_h5ad

        return updates

    async def execute_spatial_clustering_node(
        self, state: PipelineExecutorState, config: RunnableConfig,
    ) -> dict:
        """Execute spatial clustering step."""
        pc = state.get("pipeline_config", {})
        method = pc.get("spatial_clustering", "leiden")
        input_h5ad = self._get_cascading_input(state)

        if not input_h5ad:
            result = ExecutionStepResult(
                step="spatial_clustering", method=method, status="failed",
                error="No input h5ad available for spatial clustering.",
            )
        else:
            result = await self._run_mcp_step(
                state, config, "spatial_clustering", method, input_h5ad,
            )

        current_results = list(state.get("step_results") or [])
        current_results.append(result.model_dump())

        updates: dict[str, Any] = {
            "step_results": current_results,
            "current_step": "spatial_clustering",
            "messages": [AIMessage(content=f"Spatial clustering ({method}): {result.status}")],
        }
        if result.output_h5ad:
            updates["output_h5ad_path"] = result.output_h5ad

        return updates

    # ---- save_results ----

    async def save_results_node(
        self, state: PipelineExecutorState, config: RunnableConfig,  # noqa: ARG002
    ) -> dict:
        """Generate execution summary and mark pipeline as complete."""
        results = state.get("step_results", [])

        summary_parts = ["## Pipeline Execution Summary\n"]
        for r in results:
            status_icon = {"ok": "OK", "skipped": "SKIP", "failed": "FAIL"}.get(r.get("status", ""), "?")
            line = f"- **{r.get('step', '?')}** ({r.get('method', '?')}): {status_icon}"
            if r.get("error"):
                line += f" — {r['error']}"
            if r.get("message"):
                line += f" — {r['message']}"
            if r.get("output_h5ad"):
                line += f"\n  Output: `{r['output_h5ad']}`"
            summary_parts.append(line)

        final_output = state.get("output_h5ad_path", "N/A")
        summary_parts.append(f"\nFinal output h5ad: `{final_output}`")

        summary = "\n".join(summary_parts)

        return {
            "execution_complete": True,
            "messages": [AIMessage(content=summary)],
        }


__all__ = ["PipelineExecutorAgent"]
