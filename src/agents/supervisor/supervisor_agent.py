"""Supervisor Agent - Orchestrates Pipeline Builder → Executor → Deep Interpreter workflow.

The Supervisor manages the full DeepMAST workflow:
1. Router: Determines which agent to invoke next
2. Pipeline Builder: Constructs ST analysis pipeline (subgraph invocation)
3. Pipeline Executor: Executes the pipeline on user's h5ad data (subgraph invocation)
4. Deep Interpreter: Runs CCI analysis + interpretation (subgraph invocation)
5. Summary: Final workflow summary
"""

import logging
import os
from typing import Any, ClassVar, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.store.base import BaseStore
from langgraph.types import interrupt

from src.base import BaseAgent
from src.agents.supervisor.supervisor_state import SupervisorState

logger = logging.getLogger(__name__)


class SupervisorAgent(BaseAgent):
    """Supervisor agent that orchestrates Pipeline Builder, Executor, and Deep Interpreter.

    Graph Flow:
        START → router
          ├─(need pipeline, not approved)──→ approve_pipeline ──→ router
          ├─(need pipeline, approved)──────→ pipeline_builder ──→ router
          ├─(need execution, not approved)─→ approve_executor ──→ router
          ├─(need execution, approved)─────→ pipeline_executor ─→ router
          ├─(need interp, not approved)────→ approve_interpreter → router
          ├─(need interp, approved)────────→ deep_interpreter ──→ router
          └─(all done)─────────────────────→ summary → END
    """

    NODE_NAMES: ClassVar[dict[str, str]] = {
        "ROUTER": "router",
        "APPROVE_PIPELINE": "approve_pipeline",
        "PIPELINE_BUILDER": "pipeline_builder",
        "APPROVE_EXECUTOR": "approve_executor",
        "PIPELINE_EXECUTOR": "pipeline_executor",
        "APPROVE_INTERPRETER": "approve_interpreter",
        "DEEP_INTERPRETER": "deep_interpreter",
        "SUMMARY": "summary",
    }

    def __init__(
        self,
        model: Any,
        state_schema: Any = SupervisorState,
        config_schema: Any | None = None,
        input_schema: Any | None = None,
        output_schema: Any | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
        store: BaseStore | None = None,
        max_retry_attempts: int = 2,
        agent_name: str | None = None,
        is_debug: bool = True,
    ) -> None:
        """Initialize the supervisor agent."""
        super().__init__(
            model=model,
            state_schema=state_schema,
            config_schema=config_schema,
            input_schema=input_schema,
            output_schema=output_schema,
            checkpointer=checkpointer,
            store=store,
            max_retry_attempts=max_retry_attempts,
            agent_name=agent_name or "SupervisorAgent",
            is_debug=is_debug,
        )

    # ===== Node Initialization =====

    def init_nodes(self, graph: StateGraph):
        """Initialize all 8 nodes in the graph."""
        graph.add_node(self.get_node_name("ROUTER"), self.router_node)
        graph.add_node(self.get_node_name("APPROVE_PIPELINE"), self.approve_pipeline_node)
        graph.add_node(self.get_node_name("PIPELINE_BUILDER"), self.pipeline_builder_node)
        graph.add_node(self.get_node_name("APPROVE_EXECUTOR"), self.approve_executor_node)
        graph.add_node(self.get_node_name("PIPELINE_EXECUTOR"), self.pipeline_executor_node)
        graph.add_node(self.get_node_name("APPROVE_INTERPRETER"), self.approve_interpreter_node)
        graph.add_node(self.get_node_name("DEEP_INTERPRETER"), self.deep_interpreter_node)
        graph.add_node(self.get_node_name("SUMMARY"), self.summary_node)

    def init_edges(self, graph: StateGraph):
        """Initialize edges with 7-target conditional routing from router."""
        router = self.get_node_name("ROUTER")
        approve_pipeline = self.get_node_name("APPROVE_PIPELINE")
        pipeline = self.get_node_name("PIPELINE_BUILDER")
        approve_exec = self.get_node_name("APPROVE_EXECUTOR")
        executor = self.get_node_name("PIPELINE_EXECUTOR")
        approve_interp = self.get_node_name("APPROVE_INTERPRETER")
        interpreter = self.get_node_name("DEEP_INTERPRETER")
        summary = self.get_node_name("SUMMARY")

        # START → router
        graph.add_edge(START, router)

        # Router → conditional routing (7 possible targets)
        graph.add_conditional_edges(
            router,
            self.route_from_router,
            [approve_pipeline, pipeline, approve_exec, executor,
             approve_interp, interpreter, summary],
        )

        # All non-terminal nodes route back to ROUTER
        graph.add_edge(approve_pipeline, router)
        graph.add_edge(pipeline, router)
        graph.add_edge(approve_exec, router)
        graph.add_edge(executor, router)
        graph.add_edge(approve_interp, router)
        graph.add_edge(interpreter, router)

        # summary → END
        graph.add_edge(summary, END)

    # ===== Routing =====

    def route_from_router(
        self, state: SupervisorState, config: RunnableConfig  # noqa: ARG002
    ) -> str:
        """Route from router to the next agent or summary.

        Phase 1: Pipeline Builder (design)
        Phase 2: Pipeline Executor (run)
        Phase 3: Deep Interpreter (interpret)
        Phase 4: Summary
        """
        # Phase 1: Pipeline Builder
        if not state.get("pipeline_complete"):
            if not state.get("pipeline_approved"):
                return self.get_node_name("APPROVE_PIPELINE")
            return self.get_node_name("PIPELINE_BUILDER")

        # Phase 2: Pipeline Executor
        if not state.get("execution_complete"):
            if not state.get("execution_approved"):
                return self.get_node_name("APPROVE_EXECUTOR")
            return self.get_node_name("PIPELINE_EXECUTOR")

        # Phase 3: Deep Interpreter
        if not state.get("interpretation_complete"):
            if not state.get("interpretation_approved"):
                return self.get_node_name("APPROVE_INTERPRETER")
            return self.get_node_name("DEEP_INTERPRETER")

        # Phase 4: Summary
        return self.get_node_name("SUMMARY")

    # ===== Router Node =====

    async def router_node(
        self, state: SupervisorState, config: RunnableConfig  # noqa: ARG002
    ) -> dict:
        """Router node - determines next step based on state.

        Checks completion flags and user intent to route appropriately.
        Supports skip-ahead: if user already has pipeline results,
        can go directly to Deep Interpreter.
        """
        # Check if user wants to skip pipeline (e.g., already has results)
        messages = state.get("messages", [])
        if messages and not state.get("pipeline_complete"):
            last_msg = messages[-1] if messages else None
            if last_msg and isinstance(last_msg, HumanMessage):
                content = str(last_msg.content).lower()
                # Skip pipeline if user indicates they already have results
                skip_keywords = ["skip pipeline", "already have", "interpret only", "skip to interpret"]
                if any(kw in content for kw in skip_keywords):
                    if self.is_debug:
                        print("User requested skip to Deep Interpreter")
                    return {
                        "pipeline_complete": True,
                        "pipeline_approved": False,
                        "execution_complete": True,
                        "execution_approved": False,
                    }

        return {}

    # ===== Approval Gate Nodes =====

    async def approve_pipeline_node(
        self, state: SupervisorState, config: RunnableConfig  # noqa: ARG002
    ) -> dict:
        """HITL gate: request user approval before Pipeline Builder execution."""
        context_parts = ["The ST Pipeline Builder will:"]
        context_parts.append("- Collect your dataset info (h5ad files, cluster keys)")
        context_parts.append("- Guide you through spatial transcriptomics analysis setup")
        context = "\n".join(context_parts)

        response = interrupt(value={
            "message": f"**Pipeline building pending approval**\n\n{context}\n\nType 'approve' to proceed or 'skip' to skip.",
        })

        actual = str(response.get("response", response) if isinstance(response, dict) else response)

        if actual.lower().strip() in ("skip", "no", "reject", "cancel"):
            if self.is_debug:
                print("User skipped Pipeline Builder")
            return {
                "pipeline_complete": True,
                "pipeline_approved": False,
                "messages": [HumanMessage(content=f"User choice: {actual} (pipeline skipped)")],
            }

        return {
            "pipeline_approved": True,
            "messages": [HumanMessage(content=f"User choice: {actual} (pipeline approved)")],
        }

    async def approve_executor_node(
        self, state: SupervisorState, config: RunnableConfig  # noqa: ARG002
    ) -> dict:
        """HITL gate: request user approval before Pipeline Executor execution."""
        pc = state.get("pipeline_config", {})
        context_parts = ["The Pipeline Executor will run the designed pipeline on your data:"]
        if pc:
            context_parts.append(f"  1. Normalization: {pc.get('normalization', 'N/A')}")
            context_parts.append(f"  2. Cell Type Analysis: {pc.get('celltype_analysis', 'N/A')}")
            context_parts.append(f"  3. Spatial Clustering: {pc.get('spatial_clustering', 'N/A')}")
        if state.get("st_technology"):
            context_parts.append(f"- Platform: {state['st_technology']}")
        context = "\n".join(context_parts)

        response = interrupt(value={
            "message": f"**Pipeline execution pending approval**\n\n{context}\n\nType 'approve' to proceed or 'skip' to skip.",
        })

        actual = str(response.get("response", response) if isinstance(response, dict) else response)

        if actual.lower().strip() in ("skip", "no", "reject", "cancel"):
            if self.is_debug:
                print("User skipped Pipeline Executor")
            return {
                "execution_complete": True,
                "execution_approved": False,
                "messages": [HumanMessage(content=f"User choice: {actual} (execution skipped)")],
            }

        return {
            "execution_approved": True,
            "messages": [HumanMessage(content=f"User choice: {actual} (execution approved)")],
        }

    async def approve_interpreter_node(
        self, state: SupervisorState, config: RunnableConfig  # noqa: ARG002
    ) -> dict:
        """HITL gate: request user approval before Deep Interpreter execution."""
        context_parts = ["The Deep Interpreter will:"]
        context_parts.append("- Execute spatial analysis (MCP tools: clustering, pathways, CCI, NMF)")
        context_parts.append("- Run HITL research discussion (cluster & factor selection)")
        context_parts.append("- Generate biological interpretation report")
        if state.get("st_technology"):
            context_parts.append(f"- Platform: {state['st_technology']}")
        if state.get("disease"):
            context_parts.append(f"- Disease: {state['disease']}")
        context = "\n".join(context_parts)

        response = interrupt(value={
            "message": f"**Biological interpretation pending approval**\n\n{context}\n\nType 'approve' to proceed or 'skip' to skip.",
        })

        actual = str(response.get("response", response) if isinstance(response, dict) else response)

        if actual.lower().strip() in ("skip", "no", "reject", "cancel"):
            if self.is_debug:
                print("User skipped Deep Interpreter")
            return {
                "interpretation_complete": True,
                "interpretation_approved": False,
                "messages": [HumanMessage(content=f"User choice: {actual} (interpretation skipped)")],
            }

        return {
            "interpretation_approved": True,
            "messages": [HumanMessage(content=f"User choice: {actual} (interpretation approved)")],
        }

    # ===== Pipeline Builder Node =====

    async def pipeline_builder_node(
        self, state: SupervisorState, config: RunnableConfig
    ) -> dict:
        """Invoke the STPipelineBuilderAgent as a subgraph.

        Passes messages and collects shared state fields + pipeline_config from the result.
        """
        from src.agents.graph_builders import create_st_pipeline_graph

        if self.is_debug:
            print("Invoking Pipeline Builder subgraph...")

        # Create Pipeline Builder graph
        pipeline_graph = await create_st_pipeline_graph(
            use_checkpointer=False,
            is_debug=self.is_debug,
        )

        # Invoke with current messages
        child_input = {
            "messages": state.get("messages", []),
        }

        result = await pipeline_graph.ainvoke(child_input, config=config)

        if self.is_debug:
            print("Pipeline Builder completed")

        # Extract pipeline_config as dict (model_dump for Pydantic)
        pipeline_config = result.get("pipeline_config")
        pipeline_config_dict = None
        if pipeline_config is not None:
            if hasattr(pipeline_config, "model_dump"):
                pipeline_config_dict = pipeline_config.model_dump()
            elif isinstance(pipeline_config, dict):
                pipeline_config_dict = pipeline_config
            else:
                pipeline_config_dict = dict(pipeline_config)

        # Extract shared fields from pipeline result
        return {
            "pipeline_complete": True,
            "st_technology": result.get("st_technology"),
            "disease": result.get("disease"),
            "species": result.get("species"),
            "sample_count": result.get("sample_count"),
            "os_type": result.get("os_type"),
            "gpu_available": result.get("gpu_available"),
            "pipeline_config": pipeline_config_dict,
            "messages": result.get("messages", []),
        }

    # ===== Pipeline Executor Node =====

    async def pipeline_executor_node(
        self, state: SupervisorState, config: RunnableConfig
    ) -> dict:
        """Invoke the PipelineExecutorAgent as a subgraph.

        Uses create_executor_graph() factory for proper env var loading.
        Passes pipeline_config and shared fields. h5ad_input_path is None
        (executor collects it from user via HITL).
        """
        from src.agents.graph_builders import create_executor_graph

        if self.is_debug:
            print("Invoking Pipeline Executor subgraph...")

        executor_graph = await create_executor_graph(
            use_checkpointer=False,
            is_debug=self.is_debug,
        )

        # Build child input — h5ad_input_path is None; executor collects via HITL
        child_input = {
            "messages": [HumanMessage(content="Begin pipeline execution.")],
            "pipeline_config": state.get("pipeline_config"),
            "platform_type": state.get("pipeline_config", {}).get("platform_type"),
            "st_technology": state.get("st_technology"),
            "disease": state.get("disease"),
            "species": state.get("species"),
            "h5ad_input_path": None,
        }

        result = await executor_graph.ainvoke(child_input, config=config)

        if self.is_debug:
            print("Pipeline Executor completed")

        return {
            "execution_complete": True,
            "executor_output_path": result.get("output_h5ad_path"),
            "messages": result.get("messages", []),
        }

    # ===== Deep Interpreter Node =====

    async def deep_interpreter_node(
        self, state: SupervisorState, config: RunnableConfig
    ) -> dict:
        """Invoke the DeepInterpreterWrapperAgent as a subgraph.

        Maps shared state fields from Supervisor to Deep Interpreter input.
        """
        from src.agents.deep_interpreter.graph_builder import (
            create_deep_interpreter_graph_wrapped,
        )

        if self.is_debug:
            print("Invoking Deep Interpreter subgraph...")

        provider = os.getenv("LLM_PROVIDER", "openai")
        data_dir = os.getenv("DEEP_INTERPRETER_DATA_DIR", "/tmp/deep_interpreter_workspace")

        wrapper_graph = create_deep_interpreter_graph_wrapped(
            provider=provider,
            data_dir=data_dir,
            is_debug=self.is_debug,
        )

        # Map shared state fields to child graph input
        child_input = {
            "messages": [HumanMessage(content="Begin Deep Interpreter analysis pipeline.")],
            "st_technology": state.get("st_technology"),
            "disease": state.get("disease"),
            "species": state.get("species"),
            "sample_count": state.get("sample_count"),
        }

        result = await wrapper_graph.ainvoke(child_input, config=config)

        if self.is_debug:
            print("Deep Interpreter completed")

        return {
            "interpretation_complete": True,
            "messages": result.get("messages", []),
        }

    # ===== Summary Node =====

    async def summary_node(
        self, state: SupervisorState, config: RunnableConfig  # noqa: ARG002
    ) -> dict:
        """Generate final workflow summary."""
        summary_parts = ["## DeepMAST Workflow Complete"]

        if state.get("st_technology"):
            summary_parts.append(f"- Platform: {state['st_technology']}")
        if state.get("disease"):
            summary_parts.append(f"- Disease: {state['disease']}")
        if state.get("species"):
            summary_parts.append(f"- Species: {state['species']}")

        def _status(complete_key: str, approved_key: str) -> str:
            if state.get(complete_key) and state.get(approved_key):
                return "Complete"
            if state.get(complete_key):
                return "Skipped"
            return "Pending"

        summary_parts.append(f"- Pipeline Builder: {_status('pipeline_complete', 'pipeline_approved')}")
        summary_parts.append(f"- Pipeline Executor: {_status('execution_complete', 'execution_approved')}")
        summary_parts.append(f"- Deep Interpreter: {_status('interpretation_complete', 'interpretation_approved')}")

        if state.get("executor_output_path"):
            summary_parts.append(f"- Executor Output: `{state['executor_output_path']}`")

        summary = "\n".join(summary_parts)

        return {
            "messages": [AIMessage(content=summary)],
        }


__all__ = ["SupervisorAgent"]
