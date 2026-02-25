"""Pipeline Executor Agent package.

Two-Phase Linear architecture: Preparation → Execution.
Runs a 3-step ST pipeline (normalization → celltype → clustering)
using dynamically loaded MCP tools with single ReAct agent execution.
"""

from src.agents.executor.executor_agent import PipelineExecutorAgent
from src.agents.executor.executor_state import (
    ExecutionStepResult,
    PipelineExecutorState,
    SCReferenceInfo,
)
from src.agents.executor.mcp_registry import (
    STEP_REGISTRIES,
    get_mcp_server_config,
    has_mcp_server_config,
    is_deconvolution_method,
    register_dynamic_mcp,
)

__all__ = [
    "PipelineExecutorAgent",
    "PipelineExecutorState",
    "ExecutionStepResult",
    "SCReferenceInfo",
    "get_mcp_server_config",
    "has_mcp_server_config",
    "is_deconvolution_method",
    "register_dynamic_mcp",
    "STEP_REGISTRIES",
]
