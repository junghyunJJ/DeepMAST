"""Subagent configurations for Drug Target Assessment Agent.

Two-subagent architecture with 4-stage funnel:
- evidence_assessor: 4-stage funnel (biological context -> validation & scoring ->
  deep dive -> structural druggability) with inline rubric assessment
- report_writer: Generate drug.md with featured candidate emphasis

Workflow order: evidence_assessor -> report_writer
"""

from typing import Callable, Sequence

from langchain_core.tools import BaseTool

from src.agents.drug_target.subagents.prompts import SUBAGENT_PROMPTS
from src.agents.drug_target.tools import (
    # Evidence I/O tools
    load_lr_candidates,
    save_evidence,
    load_evidence_files,
    # Stage-specific domain tools
    query_cellxgene_lr_context,
    query_kegg_pathways,
    query_reactome_pathways,
    query_string_ppi_pair,
    query_ensembl_vep_consequence,
    query_opentargets_target,
    query_opentargets_known_drugs,
    query_gwas_gene_trait,
    query_drugbank_target_profile,
    query_pubmed_clinical_limitations,
    query_alphafold_plddt,
    run_diffdock_screen,
    run_compare_census_lr_pair,
    # Assessment tools
    save_target_assessment,
    # Common tools
    sequential_thinking,
    think_tool,
    validate_quality,
)

__all__ = [
    "get_subagents",
    "SUBAGENT_CONFIGS",
    "WORKFLOW_ORDER",
]


# =============================================================================
# 2-Subagent Configuration Definitions
# =============================================================================

SUBAGENT_CONFIGS = {
    "evidence_assessor": {
        "name": "evidence_assessor",
        "description": (
            "4-stage funnel: biological context -> validation & scoring -> "
            "deep dive -> structural druggability. Includes inline rubric assessment. "
            "Loads lr_candidates.json + selected_top3_lr.json, then systematically "
            "queries databases via @tool wrappers (OpenTargets, GWAS, Cellxgene, "
            "KEGG/Reactome, STRING, VEP, DrugBank, PubMed, AlphaFold, DiffDock, "
            "Census cross-validation). Applies DRUG_TARGET_RUBRIC scoring inline "
            "after Stage 2. Saves evidence/*.json files with is_selected_top3 flags. "
            "Uses Plan->Execute->Reflect cycle per stage."
        ),
        "system_prompt": SUBAGENT_PROMPTS["evidence_assessor"],
        "tools": [
            # I/O
            load_lr_candidates,
            save_evidence,
            load_evidence_files,
            # Stage 1: Biological Context
            query_cellxgene_lr_context,
            query_kegg_pathways,
            query_reactome_pathways,
            query_string_ppi_pair,
            run_compare_census_lr_pair,
            # Stage 2: Target Validation
            query_opentargets_target,
            query_opentargets_known_drugs,
            query_gwas_gene_trait,
            query_ensembl_vep_consequence,
            # Stage 3: Deep Dive
            query_drugbank_target_profile,
            query_pubmed_clinical_limitations,
            # Stage 4: Structural Druggability
            query_alphafold_plddt,
            run_diffdock_screen,
            # Cognitive
            sequential_thinking,
            think_tool,
            validate_quality,
        ],
    },
    "report_writer": {
        "name": "report_writer",
        "description": (
            "Publication-quality report generator. Reads all evidence and assessment files, "
            "generates target_assessment.json + drug.md with 4-section structure: "
            "Executive Summary ([FEATURED] Candidates first), "
            "Pan-Disease Target Druggability Matrix ([FEATURED] rows bolded), "
            "[FEATURED] Candidate Deep Dives (Stage 3 & 4), "
            "Pipeline Execution Summary & Recommendations. "
            "selected_top3_lr genes receive dedicated sections and priority placement throughout."
        ),
        "system_prompt": SUBAGENT_PROMPTS["report_writer"],
        "tools": [
            load_evidence_files,
            save_target_assessment,
            sequential_thinking,
            think_tool,
            validate_quality,
        ],
    },
}


# =============================================================================
# Workflow Order
# =============================================================================

WORKFLOW_ORDER = ["evidence_assessor", "report_writer"]

WORKFLOW_DESCRIPTION = """
Drug Target Assessment 2-Agent Workflow (4-Stage Funnel):

1. EVIDENCE_ASSESSOR (Plan->Execute->Reflect per stage)
   Stage 1 (ALL L-R pairs): Cellxgene + KEGG/Reactome + STRING + Census cross-validation
   Stage 2 (ALL L-R pairs): OpenTargets + VEP (conditional) + GWAS batch
     -> Inline DRUG_TARGET_RUBRIC scoring after Stage 2
     -> Dynamic featured candidate selection (top 3-5)
   Stage 3 (FEATURED only): DrugBank + PubMed clinical limitations (conditional)
   Stage 4 (FEATURED only): AlphaFold pLDDT + DiffDock (conditional)
   Outputs: evidence/*.json (per stage, per L-R pair/gene)
            assessment_results.json, gwas_interpretation.json, clinical_landscape.json

2. REPORT_WRITER (Plan->Execute->Reflect)
   - Generates target_assessment.json (structured contract)
   - Generates drug.md with 4-section structure:
     1. Executive Summary
     2. Pan-Disease Target Druggability Matrix
     3. [FEATURED] Candidate Deep Dives
     4. Pipeline Execution Summary & Recommendations
   - Quality validation (threshold >= 0.7)
"""


# =============================================================================
# Public API
# =============================================================================

def get_subagents(
    custom_tools: Sequence[BaseTool | Callable] | None = None,
    data_dir: str | None = None,
) -> list[dict]:
    """Get the subagent configurations for Drug Target Assessment.

    Returns 2 subagents in workflow order:
    1. evidence_assessor - 4-stage funnel with inline rubric assessment
    2. report_writer - drug.md generation

    Args:
        custom_tools: Optional list of additional tools to include in all subagents
        data_dir: Resolved data directory path to inject into subagent prompts

    Returns:
        List of subagent configuration dictionaries
    """
    subagents = [
        {**SUBAGENT_CONFIGS["evidence_assessor"], "tools": list(SUBAGENT_CONFIGS["evidence_assessor"]["tools"])},
        {**SUBAGENT_CONFIGS["report_writer"], "tools": list(SUBAGENT_CONFIGS["report_writer"]["tools"])},
    ]

    # Inject data_dir into each subagent's system prompt so they know the path
    if data_dir:
        data_dir_note = (
            f"\n\n## Data Directory\n"
            f"The data directory for this session is: `{data_dir}`\n"
            f"Pass this exact path as `data_dir` to all tool calls "
            f"(load_lr_candidates, load_evidence_files, save_evidence).\n"
        )
        for subagent in subagents:
            subagent["system_prompt"] = subagent["system_prompt"] + data_dir_note

    if custom_tools:
        for subagent in subagents:
            current_tools = list(subagent.get("tools", []))
            current_tools.extend(custom_tools)
            subagent["tools"] = current_tools

    return subagents
