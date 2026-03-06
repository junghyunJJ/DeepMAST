"""State schema for Deep Interpreter Wrapper Agent.

This module defines the state used by the wrapper agent that manages
the full spatial analysis pipeline before invoking the Deep Agent.

Workflow:
1. Collect user info (h5ad files, cluster_key, sample_key, data_directory) + shared state from Supervisor
2. Execute spatial analysis Steps 1-8 via MCP (basic plots, pathway enrichment, LIANA+ CCI, NMF)
3. HITL research discussion using interrupt() to extract interest_clusters, interest_celltypes, sel_factor
4. Execute targeted analysis Steps 9-11 via MCP (quadrant plot, spatial/cluster LR visualization)
5. Invoke Deep Agent for interpretation/report generation
"""

from typing import Annotated, Literal, Optional

from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class DeepInterpreterWrapperState(TypedDict):
    """State schema for Deep Interpreter Wrapper Agent.

    This state tracks the full spatial analysis pipeline including
    MCP-based analysis execution, HITL research discussion, and
    Deep Agent invocation.

    Attributes:
        messages: Conversation history with add_messages reducer
        # Shared fields (pre-populated by Supervisor from STPipelineBuilderAgent)
        st_technology: ST platform (Visium, MERFISH, etc.)
        disease: Disease/phenotype being studied
        species: Organism species
        sample_count: Number of samples in dataset
        # User-collected fields
        h5ad_files: Path(s) to .h5ad file(s)
        cluster_key: Column name in adata.obs for cluster assignments
        celltype_key: Column name in adata.obs for cell type annotations
        sample_key: Column name for sample ID (required when sample_count > 1)
        interest_sample: Specific sample to analyze in multi-sample datasets
        data_directory: Path to results output folder
        # Research discussion outputs
        interest_clusters: Selected cluster IDs from HITL
        interest_celltypes: Selected cell types from HITL
        sel_factor: Selected NMF factor (e.g. "Factor_3")
        # Step-loop tracking
        current_analysis_step: Current step index for loop-based execution (1-8 or 9-11)
        # Workflow control flags
        info_complete: Flag indicating all user info collected
        analysis_1_8_complete: Steps 1-8 execution flag
        research_summary_prepared: Phase A done (CSV reads + LLM suggestion cached)
        llm_suggestion: Cached LLM suggestion text from prepare_research_summary
        clusters_collected: Phase B done (cluster/celltype selection confirmed)
        research_discussion_complete: Research HITL flag (all 3 sub-phases done)
        drug_target_complete: Step 9.5 drug_target pipeline execution flag
        drug_target_error: Error message if Step 9.5 failed (None on success)
        featured_lr_pairs: Featured L-R pairs from drug_target assessment
        analysis_9_11_complete: Steps 9-11 execution flag
        # Deep Agent output
        deep_agent_result: Output from Deep Agent invocation (JSON string)
    """

    # Conversation messages (required for LangGraph)
    messages: Annotated[list, add_messages]

    # Shared fields (pre-populated by Supervisor from STPipelineBuilderAgent)
    st_technology: Optional[str]
    disease: Optional[str]
    species: Optional[Literal["human", "mouse"]]
    sample_count: Optional[int]

    # User-collected fields
    h5ad_files: Optional[list[str]]
    cluster_key: Optional[str]
    celltype_key: Optional[str]
    sample_key: Optional[str]
    interest_sample: Optional[str]
    data_directory: Optional[str]

    # Research discussion outputs (from HITL interrupt)
    interest_clusters: Optional[list[str]]
    interest_celltypes: Optional[list[str]]
    sel_factor: Optional[str]

    # Step-loop tracking
    current_analysis_step: Optional[int]

    # Workflow control flags
    info_complete: bool
    analysis_1_8_complete: bool
    research_summary_prepared: bool       # Phase A done (CSV + LLM suggestion)
    llm_suggestion: Optional[str]         # Cached LLM suggestion text
    cluster_attempt: Optional[int]        # Re-prompt counter for cluster selection (0=first, 1+=re-prompt)
    clusters_collected: bool              # Phase B done (clusters selected)
    research_discussion_complete: bool
    drug_target_complete: bool            # Step 9.5: drug_target pipeline done
    drug_target_error: Optional[str]      # Step 9.5: error message if pipeline failed
    featured_lr_pairs: Optional[list[str]]  # ["LIGAND^RECEPTOR", ...] from drug_target
    analysis_9_11_complete: bool
    interpretation_confirmed: bool

    # Deep Agent output (JSON string for checkpoint serialization safety)
    deep_agent_result: Optional[str]


def create_initial_state() -> DeepInterpreterWrapperState:
    """Create initial state with default values.

    Returns:
        Initial state dictionary with None/False defaults
    """
    return DeepInterpreterWrapperState(
        messages=[],
        st_technology=None,
        disease=None,
        species=None,
        sample_count=None,
        h5ad_files=None,
        cluster_key=None,
        celltype_key=None,
        sample_key=None,
        interest_sample=None,
        data_directory=None,
        interest_clusters=None,
        interest_celltypes=None,
        sel_factor=None,
        current_analysis_step=None,
        info_complete=False,
        analysis_1_8_complete=False,
        research_summary_prepared=False,
        llm_suggestion=None,
        cluster_attempt=0,
        clusters_collected=False,
        research_discussion_complete=False,
        drug_target_complete=False,
        drug_target_error=None,
        featured_lr_pairs=[],
        analysis_9_11_complete=False,
        interpretation_confirmed=False,
        deep_agent_result=None,
    )


__all__ = ["DeepInterpreterWrapperState", "create_initial_state"]
