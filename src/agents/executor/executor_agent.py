"""Pipeline Executor Agent — Two-Phase Linear architecture.

Phase 1 (Preparation): load config, collect data, resolve SC ref, validate, check/generate MCPs
Phase 2 (Execution): single ReAct agent with all MCP tools

Graph (9-node):
    START → load_pipeline_config → load_st_data ←─ (loop if missing)
          → [spot-based?] → resolve_sc_reference (or skip)
          → validate_data → prep_executor
          → [MCP missing?] → generate_mcp → prep_executor (re-check)
          → human_confirm → execute_pipeline → save_results → END
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, ClassVar, Literal

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
)
from src.agents.executor.mcp_registry import (
    get_mcp_server_config,
    get_visium_ref_selector_config,
    has_mcp_server_config,
    is_deconvolution_method,
    register_dynamic_mcp,
)

logger = logging.getLogger(__name__)


class PipelineExecutorAgent(BaseAgent):
    """Two-Phase Pipeline Executor: Preparation → Execution."""

    NODE_NAMES: ClassVar[dict[str, str]] = {
        "LOAD_CONFIG": "load_pipeline_config",
        "LOAD_ST_DATA": "load_st_data",
        "RESOLVE_SC_REF": "resolve_sc_reference",
        "VALIDATE_DATA": "validate_data",
        "PREP_EXECUTOR": "prep_executor",
        "GENERATE_MCP": "generate_mcp",
        "HUMAN_CONFIRM": "human_confirm",
        "EXECUTE_PIPELINE": "execute_pipeline",
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
        graph.add_node(self.get_node_name("LOAD_CONFIG"), self.load_pipeline_config_node)
        graph.add_node(self.get_node_name("LOAD_ST_DATA"), self.load_st_data_node)
        graph.add_node(self.get_node_name("RESOLVE_SC_REF"), self.resolve_sc_reference_node)
        graph.add_node(self.get_node_name("VALIDATE_DATA"), self.validate_data_node)
        graph.add_node(self.get_node_name("PREP_EXECUTOR"), self.prep_executor_node)
        graph.add_node(self.get_node_name("GENERATE_MCP"), self.generate_mcp_node)
        graph.add_node(self.get_node_name("HUMAN_CONFIRM"), self.human_confirm_node)
        graph.add_node(self.get_node_name("EXECUTE_PIPELINE"), self.execute_pipeline_node)
        graph.add_node(self.get_node_name("SAVE_RESULTS"), self.save_results_node)

    def init_edges(self, graph: StateGraph):
        load_config = self.get_node_name("LOAD_CONFIG")
        load_st = self.get_node_name("LOAD_ST_DATA")
        sc_ref = self.get_node_name("RESOLVE_SC_REF")
        validate = self.get_node_name("VALIDATE_DATA")
        prep = self.get_node_name("PREP_EXECUTOR")
        gen_mcp = self.get_node_name("GENERATE_MCP")
        confirm = self.get_node_name("HUMAN_CONFIRM")
        execute = self.get_node_name("EXECUTE_PIPELINE")
        save = self.get_node_name("SAVE_RESULTS")

        # START → load_pipeline_config
        graph.add_edge(START, load_config)

        # load_config → load_st_data (always, or save if no config)
        graph.add_conditional_edges(
            load_config,
            self.route_after_load_config,
            [load_st, save],
        )

        # load_st_data → conditional (h5ad present? → next, missing → loop)
        graph.add_conditional_edges(
            load_st,
            self.route_after_load_st,
            [load_st, sc_ref, validate],
        )

        # resolve_sc_reference → validate_data
        graph.add_edge(sc_ref, validate)

        # validate_data → prep_executor
        graph.add_edge(validate, prep)

        # prep_executor → conditional (all ready? → confirm, missing → generate)
        graph.add_conditional_edges(
            prep,
            self.route_after_prep,
            [confirm, gen_mcp],
        )

        # generate_mcp → prep_executor (re-check)
        graph.add_edge(gen_mcp, prep)

        # human_confirm → execute_pipeline
        graph.add_edge(confirm, execute)

        # execute_pipeline → save_results
        graph.add_edge(execute, save)

        # save_results → END
        graph.add_edge(save, END)

    # ================================================================
    # Routing (sync — required by LangGraph)
    # ================================================================

    def route_after_load_config(
        self, state: PipelineExecutorState, config: RunnableConfig,
    ) -> str:
        if not state.get("pipeline_config"):
            return self.get_node_name("SAVE_RESULTS")
        return self.get_node_name("LOAD_ST_DATA")

    def route_after_load_st(
        self, state: PipelineExecutorState, config: RunnableConfig,
    ) -> str:
        if not state.get("h5ad_input_path"):
            return self.get_node_name("LOAD_ST_DATA")  # loop: interrupt → re-enter
        if state.get("platform_type") == "spot-based":
            return self.get_node_name("RESOLVE_SC_REF")
        return self.get_node_name("VALIDATE_DATA")

    def route_after_prep(
        self, state: PipelineExecutorState, config: RunnableConfig,
    ) -> str:
        if state.get("all_mcp_ready"):
            return self.get_node_name("HUMAN_CONFIRM")
        return self.get_node_name("GENERATE_MCP")

    # ================================================================
    # Phase 1: Preparation Nodes
    # ================================================================

    async def load_pipeline_config_node(
        self, state: PipelineExecutorState, config: RunnableConfig,
    ) -> dict:
        """Parse pipeline_config, determine platform_type and celltype_mode."""
        pc = state.get("pipeline_config")
        if not pc:
            return {
                "messages": [AIMessage(content="Error: No pipeline_config provided.")],
            }

        platform = pc.get("platform_type", state.get("platform_type", "spot-based"))
        celltype_mode: Literal["deconvolution", "annotation"] = (
            "deconvolution" if platform == "spot-based" else "annotation"
        )

        if self.is_debug:
            logger.info(
                "load_config: platform=%s, celltype_mode=%s, methods=%s/%s/%s",
                platform, celltype_mode,
                pc.get("normalization"), pc.get("celltype_analysis"), pc.get("spatial_clustering"),
            )

        return {
            "platform_type": platform,
            "celltype_mode": celltype_mode,
            "messages": [AIMessage(content=(
                f"Pipeline loaded: {pc.get('normalization')} → "
                f"{pc.get('celltype_analysis')} ({celltype_mode}) → "
                f"{pc.get('spatial_clustering')}"
            ))],
        }

    async def load_st_data_node(
        self, state: PipelineExecutorState, config: RunnableConfig,
    ) -> dict:
        """Collect h5ad path. Uses interrupt() if not already provided."""
        h5ad = state.get("h5ad_input_path")
        if h5ad:
            return {}  # Already have it, routing handles next step

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

    async def resolve_sc_reference_node(
        self, state: PipelineExecutorState, config: RunnableConfig,
    ) -> dict:
        """Resolve SC reference for spot-based deconvolution.

        Flow:
        - SC refs >= 1 provided → visium_reference_selector_mcp (OT ranking)
        - SC refs == 0 → cellxgene-census skill (search & download)
        - interrupt() for final confirmation
        """
        candidates = state.get("sc_reference_candidates") or []

        # --- Auto-resolution ---
        selected: dict | None = None

        if len(candidates) == 1:
            # Single SC ref → use directly
            selected = candidates[0]

        elif len(candidates) >= 2:
            # Multiple → rank with visium_reference_selector_mcp
            try:
                server_key, server_config = get_visium_ref_selector_config()
                from langchain_mcp_adapters.client import MultiServerMCPClient

                client = MultiServerMCPClient({server_key: server_config})
                tools = await client.get_tools()
                agent = create_react_agent(
                    model=self.get_model(config),
                    tools=tools,
                    prompt=(
                        f"Rank these SC reference datasets for {state.get('st_technology', 'Visium')} "
                        f"{state.get('disease', 'tissue')} deconvolution using analyze_references. "
                        f"Spatial h5ad: {state.get('h5ad_input_path')}. "
                        f"References: {[c.get('path') for c in candidates]}"
                    ),
                    checkpointer=MemorySaver(),
                )
                result = await agent.ainvoke(
                    {"messages": [HumanMessage(content="Rank SC references")]},
                    config={"configurable": {"thread_id": "sc-ref-rank"}},
                )
                # Parse best from result
                for msg in reversed(result.get("messages", [])):
                    if isinstance(msg, AIMessage) and msg.content:
                        selected = {
                            "name": "auto-ranked",
                            "path": candidates[0].get("path", ""),
                            "score": "best",
                            "source": "visium_ref_mcp",
                            "description": msg.content[:300],
                        }
                        break
            except Exception as e:
                logger.warning("Visium ref selector failed: %s", e)
                selected = candidates[0]  # fallback to first

        else:
            # No SC refs → cellxgene-census skill
            try:
                census_prompt = (
                    f"Use cellxgene-census to find a single-cell reference dataset for:\n"
                    f"- Species: {state.get('species', 'human')}\n"
                    f"- Disease/Tissue: {state.get('disease', 'tissue')}\n"
                    f"- Technology context: {state.get('st_technology', 'Visium')}\n\n"
                    f"Search the CELLxGENE Census for relevant datasets. "
                    f"Download a suitable reference as h5ad to: "
                    f"{state.get('output_directory', '/tmp')}/sc_reference/"
                )
                census_result = await self.get_model(config).ainvoke(
                    [HumanMessage(content=census_prompt)]
                )
                if isinstance(census_result, AIMessage):
                    selected = {
                        "name": "cellxgene-census",
                        "path": "",
                        "source": "cellxgene-census",
                        "description": census_result.content[:300],
                    }
            except Exception as e:
                logger.warning("cellxgene-census search failed: %s", e)

        # --- HITL: Final confirmation ---
        confirm_msg = "**SC Reference Resolution**\n\n"
        if selected:
            confirm_msg += (
                f"Recommended: {selected.get('name', 'unknown')}\n"
                f"Path: {selected.get('path', 'N/A')}\n"
                f"Source: {selected.get('source', 'N/A')}\n\n"
            )
        confirm_msg += (
            "Provide a path to use, or type 'skip' to skip cell type deconvolution."
        )

        response = interrupt(value={"message": confirm_msg})
        actual = str(response.get("response", response) if isinstance(response, dict) else response)

        if actual.lower().strip() in ("skip", "no", "none"):
            pc = state.get("pipeline_config", {})
            celltype_method = pc.get("celltype_analysis", "")
            updates: dict[str, Any] = {
                "sc_reference_path": None,
                "messages": [HumanMessage(content="SC reference skipped.")],
            }
            if is_deconvolution_method(celltype_method):
                skip_result = ExecutionStepResult(
                    step="celltype_analysis", method=celltype_method,
                    status="skipped",
                    message="SC reference skipped — deconvolution requires SC ref.",
                )
                current = list(state.get("step_results") or [])
                current.append(skip_result.model_dump())
                updates["step_results"] = current
            return updates

        # User confirmed or provided path
        sc_path = actual.strip()
        if selected and not sc_path:
            sc_path = selected.get("path", "")

        return {
            "sc_reference_path": sc_path,
            "sc_reference_selected": selected or {"name": "user", "path": sc_path, "source": "user"},
            "sc_reference_candidates": candidates,
            "messages": [HumanMessage(content=f"SC reference confirmed: {sc_path}")],
        }

    async def validate_data_node(
        self, state: PipelineExecutorState, config: RunnableConfig,
    ) -> dict:
        """Validate h5ad exists and set up output directory."""
        h5ad = state.get("h5ad_input_path", "")
        output_dir = state.get("output_directory") or str(Path(h5ad).parent / "executor_output")

        issues = []
        if not h5ad:
            issues.append("No h5ad input path")
        elif not Path(h5ad).exists():
            issues.append(f"h5ad file not found: {h5ad}")

        if issues:
            return {
                "messages": [AIMessage(content=f"Validation issues: {'; '.join(issues)}")],
            }

        Path(output_dir).mkdir(parents=True, exist_ok=True)

        return {
            "output_directory": output_dir,
            "step_results": state.get("step_results") or [],
            "messages": [AIMessage(content=f"Data validated. Output dir: {output_dir}")],
        }

    # ================================================================
    # Phase 2: Execution Nodes
    # ================================================================

    async def prep_executor_node(
        self, state: PipelineExecutorState, config: RunnableConfig,
    ) -> dict:
        """Batch-check MCP availability for all 3 pipeline steps."""
        pc = state.get("pipeline_config", {})
        steps = {
            "normalization": pc.get("normalization", "log"),
            "celltype_analysis": pc.get("celltype_analysis", ""),
            "spatial_clustering": pc.get("spatial_clustering", "leiden"),
        }

        # Check if celltype was already skipped
        celltype_skipped = any(
            r.get("step") == "celltype_analysis" and r.get("status") == "skipped"
            for r in (state.get("step_results") or [])
        )

        availability = {}
        for step_name, method in steps.items():
            if step_name == "celltype_analysis" and celltype_skipped:
                availability[step_name] = True  # No need to check
                continue
            if not method:
                availability[step_name] = False
                continue
            availability[step_name] = has_mcp_server_config(step_name, method)

        all_ready = all(availability.values())

        if self.is_debug:
            logger.info("prep_executor: availability=%s, all_ready=%s", availability, all_ready)

        return {
            "mcp_availability": availability,
            "all_mcp_ready": all_ready,
            "messages": [AIMessage(content=(
                f"MCP check: {availability}. "
                f"{'All ready!' if all_ready else 'Some MCPs need generation.'}"
            ))],
        }

    async def generate_mcp_node(
        self, state: PipelineExecutorState, config: RunnableConfig,
    ) -> dict:
        """Generate missing MCP servers using code2MCP (Python) or rmcpagent (R)."""
        pc = state.get("pipeline_config", {})
        availability = state.get("mcp_availability", {})
        output_dir = state.get("output_directory", "/tmp/executor_output")
        generated = dict(state.get("generated_mcp_configs") or {})

        mcp_dir = str(Path(output_dir) / "generated_mcps")
        Path(mcp_dir).mkdir(parents=True, exist_ok=True)

        for step_name, is_available in availability.items():
            if is_available:
                continue

            method = pc.get(step_name, "")
            if not method:
                continue

            if self.is_debug:
                logger.info("Generating MCP for %s/%s", step_name, method)

            try:
                # Determine language (R methods: bayesspace)
                r_methods = {"bayesspace"}
                is_r = method.lower() in r_methods

                if is_r:
                    # rmcpagent: R package → MCP server
                    mcp_file = f"{mcp_dir}/{step_name}_{method.lower()}_mcp.R"
                    gen_prompt = (
                        f"Use rmcpagent to generate an MCP server for R function '{method}' "
                        f"in the '{step_name}' step. Workflow template: '{step_name}'. "
                        f"Output file: {mcp_file}"
                    )
                    server_config = {
                        "command": "Rscript",
                        "args": [mcp_file],
                        "transport": "stdio",
                    }
                else:
                    # code2MCP: Python → FastMCP server
                    mcp_file = f"{mcp_dir}/{step_name}_{method.lower()}_mcp.py"
                    gen_prompt = (
                        f"Generate a Python MCP server for '{method}' {step_name}. "
                        f"The server should accept an input h5ad path and output h5ad path. "
                        f"Use FastMCP with stdio transport. Save to: {mcp_file}"
                    )
                    server_config = {
                        "command": "python",
                        "args": [mcp_file],
                        "transport": "stdio",
                    }

                # Use LLM to generate the MCP code (1 retry on failure)
                last_error: Exception | None = None
                for attempt in range(2):
                    try:
                        result = await self.get_model(config).ainvoke(
                            [HumanMessage(content=gen_prompt)]
                        )
                        # Write generated code to disk
                        if isinstance(result, AIMessage) and result.content:
                            Path(mcp_file).write_text(result.content)
                        last_error = None
                        break
                    except Exception as retry_err:
                        last_error = retry_err
                        if attempt == 0:
                            logger.warning("MCP gen attempt 1 failed for %s/%s: %s, retrying", step_name, method, retry_err)

                if last_error is not None:
                    raise last_error

                # Register in dynamic registry
                server_key = f"generated-{step_name}-{method.lower()}"
                register_dynamic_mcp(step_name, method, server_key, server_config)
                generated[step_name] = server_config

                if self.is_debug:
                    logger.info("Generated MCP for %s/%s: %s", step_name, method, mcp_file)

            except Exception as e:
                logger.error("Failed to generate MCP for %s/%s: %s", step_name, method, e)
                skip_result = ExecutionStepResult(
                    step=step_name, method=method, status="failed",
                    error=f"MCP generation failed: {e}",
                )
                current = list(state.get("step_results") or [])
                current.append(skip_result.model_dump())
                return {
                    "step_results": current,
                    "generated_mcp_configs": generated,
                    "messages": [AIMessage(content=f"MCP generation failed for {step_name}/{method}: {e}")],
                }

        return {
            "generated_mcp_configs": generated,
            "messages": [AIMessage(content=f"MCP generation complete: {list(generated.keys())}")],
        }

    async def human_confirm_node(
        self, state: PipelineExecutorState, config: RunnableConfig,
    ) -> dict:
        """Present full execution plan for user approval."""
        pc = state.get("pipeline_config", {})
        celltype_skipped = any(
            r.get("step") == "celltype_analysis" and r.get("status") == "skipped"
            for r in (state.get("step_results") or [])
        )

        plan = "**Pipeline Execution Plan**\n\n"
        plan += f"- Input: `{state.get('h5ad_input_path')}`\n"
        plan += f"- Platform: {state.get('platform_type')} ({state.get('st_technology')})\n"
        plan += f"- Output dir: `{state.get('output_directory')}`\n\n"
        plan += "**Steps:**\n"
        plan += f"1. Normalization: `{pc.get('normalization', 'log')}`\n"
        if celltype_skipped:
            plan += "2. Cell Type Analysis: SKIPPED\n"
        else:
            plan += f"2. Cell Type Analysis: `{pc.get('celltype_analysis')}` ({state.get('celltype_mode')})\n"
            if state.get("sc_reference_path"):
                plan += f"   SC Reference: `{state.get('sc_reference_path')}`\n"
        plan += f"3. Spatial Clustering: `{pc.get('spatial_clustering', 'leiden')}`\n"
        plan += "\nType 'approve' to proceed or 'skip' to cancel execution."

        response = interrupt(value={"message": plan})
        actual = str(response.get("response", response) if isinstance(response, dict) else response)

        if actual.lower().strip() in ("skip", "cancel", "no"):
            return {
                "execution_complete": True,
                "messages": [HumanMessage(content="User cancelled pipeline execution.")],
            }

        return {
            "messages": [HumanMessage(content=f"User approved: {actual}")],
        }

    async def execute_pipeline_node(
        self, state: PipelineExecutorState, config: RunnableConfig,
    ) -> dict:
        """Execute all pipeline steps via a single ReAct agent with all MCP tools."""
        if state.get("execution_complete"):
            return {}  # User cancelled in human_confirm

        pc = state.get("pipeline_config", {})
        h5ad = state.get("h5ad_input_path", "")
        output_dir = state.get("output_directory", "/tmp/executor_output")
        sc_ref = state.get("sc_reference_path")

        celltype_skipped = any(
            r.get("step") == "celltype_analysis" and r.get("status") == "skipped"
            for r in (state.get("step_results") or [])
        )

        # Collect MCP configs for all active steps
        mcp_configs: dict[str, dict] = {}
        active_steps: list[tuple[str, str]] = []

        norm_method = pc.get("normalization", "log")
        ct_method = pc.get("celltype_analysis", "")
        clust_method = pc.get("spatial_clustering", "leiden")

        try:
            sk, sc = get_mcp_server_config("normalization", norm_method)
            mcp_configs[sk] = sc
            active_steps.append(("normalization", norm_method))
        except KeyError as e:
            logger.error("No MCP for normalization: %s", e)

        if not celltype_skipped and ct_method:
            try:
                sk, sc = get_mcp_server_config("celltype_analysis", ct_method)
                mcp_configs[sk] = sc
                active_steps.append(("celltype_analysis", ct_method))
            except KeyError as e:
                logger.error("No MCP for celltype: %s", e)

        try:
            sk, sc = get_mcp_server_config("spatial_clustering", clust_method)
            mcp_configs[sk] = sc
            active_steps.append(("spatial_clustering", clust_method))
        except KeyError as e:
            logger.error("No MCP for clustering: %s", e)

        if not mcp_configs:
            return {
                "messages": [AIMessage(content="Error: No MCP servers available for execution.")],
                "execution_complete": True,
            }

        # Build execution prompt
        step_instructions = []
        for i, (step_name, method) in enumerate(active_steps, 1):
            expected_out = str(Path(output_dir) / f"{step_name}_{method.lower()}.h5ad")
            instr = f"{i}. {step_name} ({method}): output → {expected_out}"
            if step_name == "celltype_analysis" and sc_ref:
                instr += f"\n   SC reference: {sc_ref}"
            step_instructions.append(instr)

        exec_prompt = (
            f"Execute the following spatial transcriptomics pipeline steps IN ORDER.\n"
            f"Input h5ad: {h5ad}\n"
            f"Platform: {state.get('platform_type')} | Species: {state.get('species')}\n"
            f"Each step's output h5ad becomes the next step's input.\n\n"
            + "\n".join(step_instructions)
        )

        # Create single ReAct agent with all MCP tools
        step_results = list(state.get("step_results") or [])
        output_h5ad = h5ad

        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient

            client = MultiServerMCPClient(mcp_configs)
            tools = await client.get_tools()

            agent = create_react_agent(
                model=self.get_model(config),
                tools=tools,
                prompt=exec_prompt,
                checkpointer=MemorySaver(),
            )

            thread_id = config.get("configurable", {}).get("thread_id", "default")
            result = await asyncio.wait_for(
                agent.ainvoke(
                    {"messages": [HumanMessage(content="Execute pipeline now.")]},
                    config={"configurable": {"thread_id": f"{thread_id}-exec"}},
                ),
                timeout=600,  # 10 minutes
            )

            # Record results for each active step
            for step_name, method in active_steps:
                expected_out = str(Path(output_dir) / f"{step_name}_{method.lower()}.h5ad")
                if Path(expected_out).exists():
                    step_results.append(ExecutionStepResult(
                        step=step_name, method=method, status="ok",
                        output_h5ad=expected_out,
                    ).model_dump())
                    output_h5ad = expected_out
                else:
                    step_results.append(ExecutionStepResult(
                        step=step_name, method=method, status="failed",
                        error=f"Expected output not found: {expected_out}",
                    ).model_dump())

        except Exception as e:
            logger.error("Pipeline execution failed: %s", e)
            for step_name, method in active_steps:
                if not any(r.get("step") == step_name for r in step_results):
                    step_results.append(ExecutionStepResult(
                        step=step_name, method=method, status="failed",
                        error=str(e),
                    ).model_dump())

        return {
            "step_results": step_results,
            "output_h5ad_path": output_h5ad,
            "messages": [AIMessage(content=f"Pipeline execution complete. Output: {output_h5ad}")],
        }

    async def save_results_node(
        self, state: PipelineExecutorState, config: RunnableConfig,
    ) -> dict:
        """Generate execution summary and mark pipeline as complete."""
        results = state.get("step_results", [])

        summary_parts = ["## Pipeline Execution Summary\n"]
        for r in results:
            icon = {"ok": "OK", "skipped": "SKIP", "failed": "FAIL"}.get(r.get("status", ""), "?")
            line = f"- **{r.get('step', '?')}** ({r.get('method', '?')}): {icon}"
            if r.get("error"):
                line += f" — {r['error']}"
            if r.get("message"):
                line += f" — {r['message']}"
            if r.get("output_h5ad"):
                line += f"\n  Output: `{r['output_h5ad']}`"
            summary_parts.append(line)

        final = state.get("output_h5ad_path", "N/A")
        summary_parts.append(f"\nFinal output: `{final}`")

        return {
            "execution_complete": True,
            "messages": [AIMessage(content="\n".join(summary_parts))],
        }


__all__ = ["PipelineExecutorAgent"]
