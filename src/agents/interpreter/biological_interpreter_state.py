"""State definitions for Biological Interpreter Agent.

This module defines the state schema for the Deep Biological Interpreter,
supporting both analysis modes:
- Mode A: cluster_to_celltype (interest_clusters -> selected_celltypes)
- Mode B: celltype_to_cluster (interest_celltypes -> selected_clusters)

NOTE: DataFrames are stored as file path references, not in state directly,
to avoid msgpack serialization issues with LangGraph checkpointer.
"""

from typing import Annotated, Literal, Optional
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages


class AnalysisDataRef(TypedDict, total=False):
    """Reference to analysis data files - file paths only, no DataFrames.

    This avoids msgpack serialization issues with LangGraph checkpointer.
    DataFrames are loaded on-demand using load_dataframe_from_ref().
    """
    figure_path: Optional[str]  # Path to figure image file (.png)
    data_path: Optional[str]    # Path to main data file (.csv)
    interest_data_path: Optional[str]  # Path to interest-filtered data (ctsvg only)


class WeightConfiguration(TypedDict):
    """Configuration for L-R pair composite scoring weights.

    LLM dynamically adjusts weights within guardrails based on analysis context.
    """
    # Base weights (default values)
    base_weights: dict[str, float]

    # Allowed ranges for each weight (guardrails)
    weight_ranges: dict[str, tuple[float, float]]

    # Actually applied weights after LLM adjustment
    applied_weights: dict[str, float]

    # LLM's rationale for weight adjustment
    adjustment_rationale: str


class LRPairScore(TypedDict):
    """Detailed scoring breakdown for a ligand-receptor pair."""
    composite_score: float
    factor_score: float
    pathway_score: float
    morans_score: float
    ctsvg_score: float


class Claim(TypedDict):
    """A biological claim with confidence and evidence."""
    claim_id: str
    content: str
    confidence: float
    supporting_evidence: list[str]
    part_source: str  # "part1", "part2", "part3", "synthesis"


class ReflectionResult(TypedDict):
    """Result from quality reflection node."""
    decision: Literal["pass", "refine"]
    biological_plausibility_score: float
    evidence_coverage_score: float
    cross_part_consistency_score: float
    issues: list[str]
    refinement_targets: list[str]


class GeneratedAnalysis(TypedDict):
    """Record of a generated analysis."""
    step: int
    analysis: str
    success: bool
    output_files: Optional[list[str]]
    error: Optional[str]


class BiologicalInterpreterState(TypedDict):
    """State for the Deep Biological Interpreter Agent.

    Supports dual-mode workflow:
    - Mode A (cluster_to_celltype): User provides interest_clusters, agent finds celltypes
    - Mode B (celltype_to_cluster): User provides interest_celltypes, agent finds clusters
    """

    # ===== MESSAGE HISTORY =====
    messages: Annotated[list, add_messages]

    # ===== INPUT (HITL at start - one of these must be provided) =====
    analysis_mode: Optional[Literal["cluster_to_celltype", "celltype_to_cluster"]]
    interest_clusters: Optional[list[str]]   # Mode A: User specifies clusters
    interest_celltypes: Optional[list[str]]  # Mode B: User specifies celltypes
    research_question: Optional[str]         # Optional: specific research focus

    # ===== DATA PATHS =====
    adata_path: Optional[str]      # Path to normalized adata (n_*adata.h5ad)
    lrdata_path: Optional[str]     # Path to L-R data (lrdata.h5ad)
    results_dir: Optional[str]     # Directory containing pre-computed results

    # ===== ANALYSIS GENERATION FLAGS =====
    force_regenerate: bool              # --force option to regenerate all analyses
    skip_existing: bool                 # Skip analyses if output files exist (default True)
    organism: Optional[Literal['human', 'mouse']]  # Organism for pathway databases
    cluster_key: Optional[str]          # Cluster column name (default: celltype_niche)

    # ===== GENERATION STATUS =====
    generated_analyses: Optional[list[GeneratedAnalysis]]  # Successfully generated analyses
    failed_analyses: Optional[list[GeneratedAnalysis]]     # Failed analyses (skipped)

    # ===== LOADED DATA =====
    # NOTE: part1_results and part2_results store FILE PATHS, not DataFrames.
    # This is required for msgpack serialization with LangGraph checkpointer.
    # Use load_dataframe_from_ref() to load DataFrames on-demand.

    # Part1 data references (from normalized adata)
    part1_results: Optional[dict[str, AnalysisDataRef]]  # {
    #   "spatial": {"figure_path": "res/1.spatial.png"},
    #   "celltype": {"figure_path": "res/2.celltype_heatmap_analysis.png", "data_path": "res/sig_clusterwithcelltyp.csv"},
    #   "nhood": {"figure_path": "res/3.neighborhood_enrichment_squidpy.png", "data_path": "res/res_nhood_enrichment.csv"},
    #   "decoupler": {"figure_path": "res/4.spatial_enrich_decoupler.png", "data_path": "res/sig_PathwayEnrich_decoupler.csv"},
    #   "misty": {"figure_path": "res/5.spatial_relation_MISTy.png", "data_path": "res/res_SpatialRelationship_MISTy.csv"}
    # }

    # Part2 data references (from lrdata)
    part2_results: Optional[dict[str, AnalysisDataRef]]  # {
    #   "morans": {"figure_path": "res/6.liana_MoransR.png", "data_path": "res/sig_liana.csv"},
    #   "nmf_factors": {"figure_path": "res/7.factor_spatial_NMF.png", "data_path": "res/res_liana_cluster_factor.csv"},
    #   "pathway_factor": {"figure_path": "res/8.pathway_factor_heatmap.png", "data_path": "res/sig_liana_pathway_factor.csv"},
    #   "ctsvg": {"figure_path": "res/9.quadrant_analysis.png", "data_path": "res/anno_sig_liana.csv", "interest_data_path": "res/interest_anno_sig_liana.csv"}
    # }

    # ===== PART 1 OUTPUT =====
    part1_interpretations: Optional[dict[str, str]]  # {analysis_name: interpretation_text}

    # Mode A output: clusters -> celltypes
    selected_celltypes: Optional[list[str]]  # Found celltypes (Mode A)

    # Mode B output: celltypes -> clusters
    selected_clusters: Optional[list[str]]   # Found clusters (Mode B)

    # Common outputs
    selected_pathways: Optional[list[str]]   # Pathways related to interest
    additional_clusters: Optional[list[str]] # Additional clusters from nhood analysis
    part1_selection_rationale: Optional[str] # Explanation of Part1 selections

    # ===== PART 2 OUTPUT =====
    part2_interpretations: Optional[dict[str, str]]

    # Factor selection
    selected_factor: Optional[str]           # e.g., "Factor3"
    factor_selection_rationale: Optional[str]
    factor_reference_clusters: Optional[list[str]]  # Clusters used for factor selection

    # Pathway comparison (Part1-4 vs Part2-8)
    pathway_comparison: Optional[dict]  # {
    #   pathway_name: {
    #     "part1_stat": float,
    #     "part2_estimate": float,
    #     "consistent": bool,
    #     "interpretation": str
    #   }
    # }

    # CellTypes for ctSVG analysis
    final_celltypes_for_ctsvg: Optional[list[str]]  # Mode A: selected_celltypes
                                                     # Mode B: interest_celltypes
    celltype_source: Optional[Literal["derived", "user_specified"]]

    # Scoring weights (hybrid: LLM-adjusted within guardrails)
    scoring_weights: Optional[WeightConfiguration]

    # L-R pair selection
    selected_lr_pairs: Optional[list[str]]   # Top 3 L-R pairs
    lr_scores: Optional[dict[str, LRPairScore]]  # All scored L-R pairs
    lr_selection_rationale: Optional[str]

    # ===== PART 3 OUTPUT =====
    part3_interpretations: Optional[dict[str, str]]

    # ===== DEEP AGENT COMPONENTS =====

    # Strategic planning (hypothesis-driven)
    analysis_plan: Optional[dict]  # {
    #   "hypotheses": [{"id": str, "content": str, "expected_evidence": str}],
    #   "key_questions": [str],
    #   "evidence_requirements": [str]
    # }

    # Cross-part synthesis
    integrated_narrative: Optional[str]

    # Claims with evidence
    claims: Optional[list[Claim]]

    # Literature evidence (claim_id -> PMIDs)
    literature_evidence: Optional[dict[str, list[str]]]

    # Quality reflection
    reflection_result: Optional[ReflectionResult]
    refinement_count: int  # Max 3 iterations

    # ===== FINAL OUTPUT =====
    html_report: Optional[str]


# Default weight configuration
DEFAULT_WEIGHT_CONFIG: WeightConfiguration = {
    "base_weights": {
        "factor": 0.35,
        "pathway": 0.30,
        "morans": 0.20,
        "ctsvg": 0.15
    },
    "weight_ranges": {
        "factor": (0.20, 0.50),
        "pathway": (0.15, 0.45),
        "morans": (0.10, 0.35),
        "ctsvg": (0.05, 0.30)
    },
    "applied_weights": {
        "factor": 0.35,
        "pathway": 0.30,
        "morans": 0.20,
        "ctsvg": 0.15
    },
    "adjustment_rationale": "Default weights - no context-specific adjustment"
}


def create_initial_state(
    interest_clusters: Optional[list[str]] = None,
    interest_celltypes: Optional[list[str]] = None,
    research_question: Optional[str] = None,
    adata_path: Optional[str] = None,
    lrdata_path: Optional[str] = None,
    results_dir: Optional[str] = None,
    force_regenerate: bool = False,
    skip_existing: bool = True,
    organism: Literal['human', 'mouse'] = 'human',
    cluster_key: str = "celltype_niche",
) -> BiologicalInterpreterState:
    """Create initial state for the Biological Interpreter.

    Args:
        interest_clusters: Clusters of interest (Mode A)
        interest_celltypes: Cell types of interest (Mode B)
        research_question: Optional specific research focus
        adata_path: Path to normalized adata file
        lrdata_path: Path to L-R data file
        results_dir: Directory containing pre-computed results
        force_regenerate: Force regeneration of all analyses (--force option)
        skip_existing: Skip analyses if output files exist (default True)
        organism: Organism for pathway databases ('human' or 'mouse')
        cluster_key: Cluster column name in adata.obs

    Returns:
        Initial state with proper mode detection

    Raises:
        ValueError: If both or neither of interest_clusters/interest_celltypes provided
    """
    has_clusters = interest_clusters is not None and len(interest_clusters) > 0
    has_celltypes = interest_celltypes is not None and len(interest_celltypes) > 0

    if has_clusters and has_celltypes:
        raise ValueError(
            "Provide either interest_clusters OR interest_celltypes, not both"
        )

    if not has_clusters and not has_celltypes:
        raise ValueError(
            "Must provide either interest_clusters or interest_celltypes"
        )

    analysis_mode: Literal["cluster_to_celltype", "celltype_to_cluster"]
    if has_clusters:
        analysis_mode = "cluster_to_celltype"
    else:
        analysis_mode = "celltype_to_cluster"

    return BiologicalInterpreterState(
        messages=[],
        analysis_mode=analysis_mode,
        interest_clusters=interest_clusters,
        interest_celltypes=interest_celltypes,
        research_question=research_question,
        adata_path=adata_path,
        lrdata_path=lrdata_path,
        results_dir=results_dir,
        # Analysis generation fields
        force_regenerate=force_regenerate,
        skip_existing=skip_existing,
        organism=organism,
        cluster_key=cluster_key,
        generated_analyses=None,
        failed_analyses=None,
        # Loaded data
        part1_results=None,
        part2_results=None,
        part1_interpretations=None,
        selected_celltypes=None,
        selected_clusters=None,
        selected_pathways=None,
        additional_clusters=None,
        part1_selection_rationale=None,
        part2_interpretations=None,
        selected_factor=None,
        factor_selection_rationale=None,
        factor_reference_clusters=None,
        pathway_comparison=None,
        final_celltypes_for_ctsvg=None,
        celltype_source=None,
        scoring_weights=DEFAULT_WEIGHT_CONFIG,
        selected_lr_pairs=None,
        lr_scores=None,
        lr_selection_rationale=None,
        part3_interpretations=None,
        analysis_plan=None,
        integrated_narrative=None,
        claims=None,
        literature_evidence=None,
        reflection_result=None,
        refinement_count=0,
        html_report=None,
    )
