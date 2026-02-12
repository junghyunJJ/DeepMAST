"""State schema for Supervisor Agent.

The Supervisor manages the overall workflow, passing shared state
between the STPipelineBuilderAgent and DeepInterpreterWrapperAgent.
"""

from typing import Annotated, Literal, Optional

from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class SupervisorState(TypedDict):
    """State schema for Supervisor Agent.

    Attributes:
        messages: Conversation history with add_messages reducer
        # Shared fields (populated by STPipelineBuilderAgent)
        st_technology: ST platform (Visium, MERFISH, etc.)
        disease: Disease/phenotype being studied
        species: Organism species
        sample_count: Number of samples in dataset
        os_type: Operating system type
        gpu_available: GPU availability
        # Pipeline config (from builder, consumed by executor)
        pipeline_config: Serialized PipelineConfig dict
        # Executor output
        executor_output_path: Path to final h5ad from executor
        # Workflow routing
        current_agent: Which agent is currently active
        pipeline_complete: Flag indicating Pipeline Builder has finished
        execution_complete: Flag indicating Pipeline Executor has finished
        interpretation_complete: Flag indicating Deep Interpreter has finished
        pipeline_approved: Whether user approved Pipeline Builder execution
        execution_approved: Whether user approved Pipeline Executor execution
        interpretation_approved: Whether user approved Deep Interpreter execution
    """

    # Conversation messages
    messages: Annotated[list, add_messages]

    # Shared fields (populated by STPipelineBuilderAgent)
    st_technology: Optional[str]
    disease: Optional[str]
    species: Optional[Literal["human", "mouse"]]
    sample_count: Optional[int]
    os_type: Optional[Literal["Windows", "Mac", "Linux", "HPC"]]
    gpu_available: Optional[Literal["GPU", "CPU"]]

    # Pipeline config (from builder, consumed by executor)
    pipeline_config: Optional[dict]

    # Executor output
    executor_output_path: Optional[str]

    # Workflow routing
    current_agent: Optional[Literal["pipeline_builder", "pipeline_executor", "deep_interpreter"]]
    pipeline_complete: bool
    execution_complete: bool
    interpretation_complete: bool

    # Approval gates
    pipeline_approved: bool
    execution_approved: bool
    interpretation_approved: bool


__all__ = ["SupervisorState"]
