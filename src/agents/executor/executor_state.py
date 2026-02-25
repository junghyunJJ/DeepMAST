"""State schema for Pipeline Executor Agent.

All fields are checkpoint-safe (no DataFrames or non-serializable objects).
Lists and dicts use ``msgpack``-friendly types only.
"""

from __future__ import annotations

from typing import Annotated, Literal, Optional

from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import TypedDict


# ---------------------------------------------------------------------------
# Pydantic models (used for validation, then stored as dicts in state)
# ---------------------------------------------------------------------------

class SCReferenceInfo(BaseModel):
    """Single-cell reference dataset metadata."""

    name: str = Field(description="Reference dataset name")
    path: str = Field(description="File path to the SC reference h5ad")
    source: str = Field(
        default="user",
        description="How the reference was obtained: 'user' or 'auto'",
    )
    species: Optional[str] = Field(default=None, description="Species of the reference")
    tissue: Optional[str] = Field(default=None, description="Tissue type of the reference")


class ExecutionStepResult(BaseModel):
    """Result of a single pipeline execution step."""

    step: str = Field(description="Step name: normalization, celltype_analysis, spatial_clustering")
    method: str = Field(description="Method used (e.g. 'log', 'IRIS', 'leiden')")
    status: Literal["ok", "skipped", "failed"] = Field(description="Execution outcome")
    output_h5ad: Optional[str] = Field(default=None, description="Path to output h5ad if produced")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    message: Optional[str] = Field(default=None, description="Additional info (e.g. skip reason)")


# ---------------------------------------------------------------------------
# State TypedDict
# ---------------------------------------------------------------------------

class PipelineExecutorState(TypedDict):
    """State schema for PipelineExecutorAgent (v2 — Two-Phase Linear)."""

    # Conversation messages
    messages: Annotated[list, add_messages]

    # Input fields (from Supervisor / PipelineBuilder)
    pipeline_config: Optional[dict]
    h5ad_input_path: Optional[str]
    platform_type: Optional[Literal["spot-based", "single-cell"]]
    st_technology: Optional[str]
    disease: Optional[str]
    species: Optional[Literal["human", "mouse"]]

    # SC Reference
    sc_reference_candidates: Optional[list[dict]]
    sc_reference_selected: Optional[dict]  # {name, path, score, source}
    sc_reference_path: Optional[str]

    # Cell type mode (derived from platform_type in load_pipeline_config)
    celltype_mode: Optional[Literal["deconvolution", "annotation"]]

    # MCP availability (set by prep_executor)
    mcp_availability: Optional[dict]       # {"normalization": True, "celltype_analysis": False, ...}
    generated_mcp_configs: Optional[dict]  # {"celltype_analysis": {"command": ..., "args": ...}}
    all_mcp_ready: bool

    # Step tracking
    step_results: list[dict]

    # Output
    output_h5ad_path: Optional[str]
    output_directory: Optional[str]

    # Completion flag
    execution_complete: bool


__all__ = [
    "PipelineExecutorState",
    "SCReferenceInfo",
    "ExecutionStepResult",
]
