"""State definition for CCI Interpreter Agent.

This module defines the state schema for the biological interpreter agent
that analyzes Cell-Cell Interaction (CCI) results from spatial transcriptomics.
"""

from typing import Annotated, Any, Optional
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class Part1Selection(BaseModel):
    """Selected clusters, cell types, and pathways from Part 1 analysis."""

    clusters: list[str] = Field(
        default_factory=list,
        description="Selected cluster names (2-3 clusters)"
    )
    cell_types: list[str] = Field(
        default_factory=list,
        description="Cell types associated with selected clusters"
    )
    pathways: list[str] = Field(
        default_factory=list,
        description="Related pathways from decoupler and MISTy analysis"
    )
    reasoning: str = Field(
        default="",
        description="Reasoning for selections"
    )


class Part2Selection(BaseModel):
    """Selected factor and L-R pairs from Part 2 analysis."""

    selected_factor: str = Field(
        default="",
        description="Selected NMF factor (e.g., 'Factor1')"
    )
    factor_pathways: list[str] = Field(
        default_factory=list,
        description="Pathways associated with selected factor"
    )
    top_lr_pairs: list[str] = Field(
        default_factory=list,
        description="Top ligand-receptor pairs (3 selected)"
    )
    reasoning: str = Field(
        default="",
        description="Reasoning for selections"
    )


class LiteratureReference(BaseModel):
    """Literature reference for biological interpretation."""

    pmid: str = Field(description="PubMed ID")
    title: str = Field(default="", description="Paper title")
    doi: Optional[str] = Field(default=None, description="DOI if available")
    downloaded: bool = Field(default=False, description="Whether paper was downloaded")
    context: str = Field(default="", description="Context where this reference is used")


class CCIInterpreterState(TypedDict):
    """State for CCI Interpreter Agent.

    This state tracks all data and workflow progress for biological
    interpretation of CCI analysis results.
    """

    # Conversation messages
    messages: Annotated[list, add_messages]

    # ===== Configuration =====
    result_dir: str  # Directory containing result CSVs and PNGs
    output_dir: str  # Directory for output HTML report
    disease_context: str  # Disease context for interpretation (e.g., "breast cancer")

    # ===== Part 1 Data (Pre-CCI Analysis) =====
    # CSV data stored as string (JSON serialized or raw)
    sig_clusterwithcelltyp: Optional[str]  # Cell type composition data
    res_nhood_enrichment: Optional[str]  # Neighborhood enrichment data
    sig_pathway_decoupler: Optional[str]  # Pathway enrichment (decoupler)
    res_spatial_misty: Optional[str]  # Spatial relationship (MISTy)

    # ===== Part 2 Data (CCI Analysis) =====
    sig_liana: Optional[str]  # CCI results
    res_liana_cluster_factor: Optional[str]  # NMF factor scores
    sig_liana_pathway_factor: Optional[str]  # Pathway factors
    interest_anno_sig_liana: Optional[str]  # Final selected interactions

    # ===== Analysis Selections =====
    part1_iteration_count: int  # Counter for Part 1 iterations (target: 3-5)
    part1_selections: Optional[list[dict[str, Any]]]  # List of Part1Selection from iterations
    final_part1_selection: Optional[dict[str, Any]]  # Final consolidated Part1Selection
    part2_selection: Optional[dict[str, Any]]  # Part2Selection as dict

    # ===== Interpretation Content =====
    part1_interpretation: Optional[str]  # Part 1 biological interpretation text
    part2_interpretation: Optional[str]  # Part 2 biological interpretation text
    part3_interpretation: Optional[str]  # Part 3 biological interpretation text
    summary_interpretation: Optional[str]  # Overall summary interpretation

    # ===== Literature References =====
    literature_queries: Optional[list[str]]  # Search queries for biomcp
    pmid_list: Optional[list[str]]  # Collected PMIDs
    literature_references: Optional[list[dict[str, Any]]]  # LiteratureReference as dicts
    rag_collection_id: Optional[str]  # langconnect-rag collection ID

    # ===== Workflow Control =====
    data_loaded: bool  # Whether all CSVs are loaded
    part1_complete: bool  # Part 1 analysis complete
    part2_complete: bool  # Part 2 analysis complete
    part3_complete: bool  # Part 3 analysis complete
    literature_searched: bool  # Literature search complete
    papers_downloaded: bool  # Papers downloaded to RAG
    verification_complete: bool  # RAG verification complete
    report_generated: bool  # HTML report generated

    # ===== Output =====
    html_report_path: Optional[str]  # Path to generated HTML report
    json_results_path: Optional[str]  # Path to JSON results file


def get_initial_state(
    result_dir: str,
    output_dir: Optional[str] = None,
    disease_context: str = "cancer"
) -> CCIInterpreterState:
    """Create initial state for CCI Interpreter Agent.

    Args:
        result_dir: Directory containing result CSVs and PNGs
        output_dir: Directory for output (defaults to result_dir)
        disease_context: Disease context for interpretation

    Returns:
        Initialized CCIInterpreterState
    """
    return CCIInterpreterState(
        messages=[],
        result_dir=result_dir,
        output_dir=output_dir or result_dir,
        disease_context=disease_context,

        # Part 1 data
        sig_clusterwithcelltyp=None,
        res_nhood_enrichment=None,
        sig_pathway_decoupler=None,
        res_spatial_misty=None,

        # Part 2 data
        sig_liana=None,
        res_liana_cluster_factor=None,
        sig_liana_pathway_factor=None,
        interest_anno_sig_liana=None,

        # Analysis selections
        part1_iteration_count=0,
        part1_selections=None,
        final_part1_selection=None,
        part2_selection=None,

        # Interpretation content
        part1_interpretation=None,
        part2_interpretation=None,
        part3_interpretation=None,
        summary_interpretation=None,

        # Literature references
        literature_queries=None,
        pmid_list=None,
        literature_references=None,
        rag_collection_id=None,

        # Workflow control
        data_loaded=False,
        part1_complete=False,
        part2_complete=False,
        part3_complete=False,
        literature_searched=False,
        papers_downloaded=False,
        verification_complete=False,
        report_generated=False,

        # Output
        html_report_path=None,
        json_results_path=None,
    )
