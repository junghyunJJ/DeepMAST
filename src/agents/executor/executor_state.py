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
    """State schema for PipelineExecutorAgent.

    Attributes:
        messages: Conversation history with add_messages reducer.

        # Input (from Supervisor / PipelineBuilder)
        pipeline_config: Serialized PipelineConfig dict from pipeline_builder.
        h5ad_input_path: Path to the user's input h5ad file.
        platform_type: "spot-based" or "single-cell".
        st_technology: ST platform name.
        disease: Disease/phenotype being studied.
        species: Organism species.

        # SC Reference resolution
        sc_reference_needed: Whether a SC reference is required.
        sc_reference_candidates: List of candidate reference dicts.
        sc_reference_selected: Index of selected candidate (or -1 for skip).
        sc_reference_path: Final resolved path to SC reference h5ad.

        # Step tracking
        step_results: List of ExecutionStepResult dicts (append-only).
        current_step: Name of the step currently executing.

        # Output
        output_h5ad_path: Path to the latest output h5ad (cascading).
        output_directory: Directory where outputs are written.

        # Completion flags (hub-pattern routing)
        inputs_validated: True after validate_inputs succeeds.
        sc_reference_resolved: True after SC reference resolved/skipped.
        normalization_complete: True after normalization step finishes.
        celltype_complete: True after celltype step finishes.
        clustering_complete: True after clustering step finishes.
        execution_complete: True after save_results (terminal).
    """

    # Conversation messages
    messages: Annotated[list, add_messages]

    # Input fields
    pipeline_config: Optional[dict]
    h5ad_input_path: Optional[str]
    platform_type: Optional[Literal["spot-based", "single-cell"]]
    st_technology: Optional[str]
    disease: Optional[str]
    species: Optional[Literal["human", "mouse"]]

    # SC Reference
    sc_reference_needed: bool
    sc_reference_candidates: Optional[list[dict]]
    sc_reference_selected: Optional[int]
    sc_reference_path: Optional[str]

    # Step tracking
    step_results: list[dict]
    current_step: Optional[str]

    # Output
    output_h5ad_path: Optional[str]
    output_directory: Optional[str]

    # Completion flags
    inputs_validated: bool
    sc_reference_resolved: bool
    normalization_complete: bool
    celltype_complete: bool
    clustering_complete: bool
    execution_complete: bool


__all__ = [
    "PipelineExecutorState",
    "SCReferenceInfo",
    "ExecutionStepResult",
]
