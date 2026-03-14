"""Subagent configurations for Drug Target Assessment Agent.

Two-subagent architecture with 3-stage funnel:
- evidence_assessor: 3-stage funnel (biological context -> validation & scoring ->
  deep dive) with inline rubric assessment
- report_writer: Generate drug.md with featured candidate emphasis

Workflow order: evidence_assessor -> report_writer
"""

from typing import Callable, Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from src.agents.drug_target.subagents.prompts import SUBAGENT_PROMPTS
from src.agents.drug_target.tools import (
    # Evidence I/O tools
    load_lr_candidates,
    save_evidence,
    load_evidence_files,
    # Stage-specific domain tools
    query_cellxgene_lr_context,
    list_census_diseases,
    query_kegg_pathways,
    query_reactome_pathways,
    query_string_ppi_pair,
    query_ensembl_vep_consequence,
    query_opentargets_target,
    query_opentargets_known_drugs,
    query_gwas_gene_trait,
    query_stage2_gene_panel,
    query_drugbank_target_profile,
    query_pubmed_clinical_limitations,
    run_compare_census_lr_pair,
    read_skill_file,
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
            "3-stage funnel with Stage 1 confidence filtering: biological context -> "
            "confidence filtering -> validation & scoring -> "
            "deep dive. Includes inline rubric assessment. "
            "Loads lr_candidates.json (top-30 L-R pairs), then systematically "
            "queries databases via @tool wrappers (OpenTargets, GWAS, Cellxgene, "
            "KEGG/Reactome, STRING, VEP, DrugBank, PubMed, "
            "Census cross-validation). Applies DRUG_TARGET_RUBRIC scoring to select "
            "Featured Candidates after Stage 2. "
            "Uses Plan->Execute->Reflect cycle per stage."
        ),
        "system_prompt": SUBAGENT_PROMPTS["evidence_assessor"],
        "tools": [
            # I/O
            load_lr_candidates,
            save_evidence,
            load_evidence_files,
            # Phase 0: Disease vocabulary matching
            list_census_diseases,
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
            query_stage2_gene_panel,
            query_ensembl_vep_consequence,
            # Stage 3: Deep Dive
            query_drugbank_target_profile,
            query_pubmed_clinical_limitations,
            read_skill_file,
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
            "[FEATURED] Candidate Deep Dives (Stage 3), "
            "Pipeline Execution Summary & Recommendations. "
            "Featured candidates are determined by rubric scoring (combined_total)."
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
Drug Target Assessment 2-Agent Workflow (3-Stage Funnel):

1. EVIDENCE_ASSESSOR (Plan->Execute->Reflect per stage)
   Stage 1 (ALL L-R pairs): Cellxgene + KEGG/Reactome + STRING + Census cross-validation
   Stage 1 Filtering: confidence score >= 0.4 (graduated relaxation if < 5 pass)
   Stage 2 (ALL unique genes): batch OpenTargets + batch GWAS + VEP (conditional)
     -> Inline DRUG_TARGET_RUBRIC scoring after Stage 2
     -> RUBRIC combined_total based featured selection (top 3-5)
   Stage 3 (FEATURED only): DrugBank + PubMed clinical limitations (conditional)
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
    model_overrides: dict[str, BaseChatModel | str] | None = None,
) -> list[dict]:
    """Get the subagent configurations for Drug Target Assessment.

    Returns 2 subagents in workflow order:
    1. evidence_assessor - 3-stage funnel with inline rubric assessment
    2. report_writer - drug.md generation

    Args:
        custom_tools: Optional list of additional tools to include in all subagents
        data_dir: Resolved data directory path to inject into subagent prompts
        model_overrides: Optional per-subagent model overrides.
            Keys are subagent names, values are init_chat_model format strings
            (e.g. "openai:gpt-4.1") or BaseChatModel instances.

    Returns:
        List of subagent configuration dictionaries
    """
    subagents = [
        {**SUBAGENT_CONFIGS["evidence_assessor"], "tools": list(SUBAGENT_CONFIGS["evidence_assessor"]["tools"])},
        {**SUBAGENT_CONFIGS["report_writer"], "tools": list(SUBAGENT_CONFIGS["report_writer"]["tools"])},
    ]

    # Apply per-subagent model overrides
    if model_overrides:
        for subagent in subagents:
            if subagent["name"] in model_overrides:
                subagent["model"] = model_overrides[subagent["name"]]

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
