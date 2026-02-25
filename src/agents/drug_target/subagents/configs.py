"""Subagent configurations for Drug Target Assessment Agent.

Three-subagent architecture:
- evidence_collector: Gather multi-database evidence (OT, GWAS, ChEMBL, CT, FDA)
- clinical_assessor: Score targets against rubric, interpret GWAS, assess safety
- report_writer: Generate drug.md with featured candidate emphasis

Workflow order: evidence_collector → clinical_assessor → report_writer
"""

from typing import Callable, Sequence

from langchain_core.tools import BaseTool

from src.agents.drug_target.subagents.prompts import SUBAGENT_PROMPTS
from src.agents.drug_target.tools import (
    # Evidence collection tools
    load_lr_candidates,
    query_ot_target_info,
    query_ot_known_drugs,
    query_ot_drug_details,
    query_gwas_trait_associations,
    query_gwas_variant_details,
    query_chembl_target_bioactivity,
    query_chembl_drug_info,
    search_clinical_trials,
    query_fda_drug_label,
    query_fda_adverse_events,
    save_evidence,
    # Assessment tools
    load_evidence_files,
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
# 3-Subagent Configuration Definitions
# =============================================================================

SUBAGENT_CONFIGS = {
    "evidence_collector": {
        "name": "evidence_collector",
        "description": (
            "Multi-database evidence gatherer. Loads lr_candidates.json + selected_top3_lr.json, "
            "then systematically queries OpenTargets, GWAS Catalog, ChEMBL, ClinicalTrials.gov, "
            "and FDA for each gene. Saves evidence/*.json files with is_selected_top3 flags. "
            "Uses Plan→Execute→Reflect cycle: sequential_thinking for planning, "
            "database tools for execution, think_tool for reflection. "
            "Use this FIRST to gather all evidence before assessment."
        ),
        "system_prompt": SUBAGENT_PROMPTS["evidence_collector"],
        "tools": [
            load_lr_candidates,
            sequential_thinking,       # PLAN: strategy before each query phase
            query_ot_target_info,
            query_ot_known_drugs,
            query_ot_drug_details,
            query_gwas_trait_associations,
            query_gwas_variant_details,
            query_chembl_target_bioactivity,
            query_chembl_drug_info,
            search_clinical_trials,
            query_fda_drug_label,
            query_fda_adverse_events,
            save_evidence,
            think_tool,                # REFLECT: coverage gaps after each phase
        ],
    },
    "clinical_assessor": {
        "name": "clinical_assessor",
        "description": (
            "Rubric-based target assessor. Loads all evidence/*.json files, "
            "evaluates each target against DRUG_TARGET_RUBRIC (validated + exploratory tracks), "
            "produces structured JSON with score + rationale per criterion. "
            "Performs GWAS biological interpretation, clinical landscape analysis, "
            "and safety assessment. Flags is_selected_top3 targets for priority. "
            "Outputs assessment_results.json, gwas_interpretation.json, clinical_landscape.json."
        ),
        "system_prompt": SUBAGENT_PROMPTS["clinical_assessor"],
        "tools": [
            load_evidence_files,
            sequential_thinking,       # PLAN: assessment strategy
            think_tool,                # REFLECT: scoring consistency
            validate_quality,
            save_evidence,
        ],
    },
    "report_writer": {
        "name": "report_writer",
        "description": (
            "Publication-quality report generator. Reads all evidence and assessment files, "
            "generates drug.md with: Executive Summary (★ Featured Candidates first), "
            "Target Druggability Matrix (★ rows bolded/starred), Featured Candidate Deep Dives, "
            "Clinical Landscape, GWAS Evidence & Interpretation, Therapeutic Recommendations. "
            "selected_top3_lr genes receive dedicated sections and priority placement throughout."
        ),
        "system_prompt": SUBAGENT_PROMPTS["report_writer"],
        "tools": [
            load_evidence_files,
            sequential_thinking,       # PLAN: document structure
            think_tool,                # REFLECT: writing quality
            validate_quality,
        ],
    },
}


# =============================================================================
# Workflow Order
# =============================================================================

WORKFLOW_ORDER = ["evidence_collector", "clinical_assessor", "report_writer"]

WORKFLOW_DESCRIPTION = """
Drug Target Assessment 3-Agent Workflow:

1. EVIDENCE_COLLECTOR (Plan→Execute→Reflect per database)
   - Loads lr_candidates.json + selected_top3_lr.json
   - Per gene: OpenTargets → GWAS → ChEMBL
   - Per disease: Known drugs → Clinical trials → FDA labels
   - Outputs: evidence/*.json (each gene tagged top3/not)

2. CLINICAL_ASSESSOR (Plan→Execute→Reflect)
   - Loads all evidence files
   - LLM-evaluates each target against DRUG_TARGET_RUBRIC
     → Validated track: drug evidence, trials, mechanism, safety
     → Exploratory track: GWAS, tractability, plausibility, novelty
   - GWAS biological interpretation
   - Clinical landscape analysis
   - Outputs: assessment/*.json (with rubric scores + rationale)

3. REPORT_WRITER (Plan→Execute→Reflect)
   - Generates drug.md with ★ Featured Candidate emphasis
   - Executive Summary, Druggability Matrix, Deep Dives
   - Clinical Landscape, GWAS Evidence, Recommendations
   - Quality validation (threshold >= 0.7)
   - Output: drug.md
"""


# =============================================================================
# Public API
# =============================================================================

def get_subagents(
    custom_tools: Sequence[BaseTool | Callable] | None = None,
    data_dir: str | None = None,
) -> list[dict]:
    """Get the subagent configurations for Drug Target Assessment.

    Returns 3 subagents in workflow order:
    1. evidence_collector - Multi-database evidence gathering
    2. clinical_assessor - Rubric-based assessment
    3. report_writer - drug.md generation

    Args:
        custom_tools: Optional list of additional tools to include in all subagents
        data_dir: Resolved data directory path to inject into subagent prompts

    Returns:
        List of subagent configuration dictionaries
    """
    subagents = [
        SUBAGENT_CONFIGS["evidence_collector"].copy(),
        SUBAGENT_CONFIGS["clinical_assessor"].copy(),
        SUBAGENT_CONFIGS["report_writer"].copy(),
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
