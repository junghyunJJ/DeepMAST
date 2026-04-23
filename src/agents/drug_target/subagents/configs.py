"""Subagent configurations for Drug Target Assessment Agent.

Three-subagent staged funnel (happy path):
- evidence_assessor: 3-stage funnel (Stage 2: validation & scoring ->
  Stage 1: biological context -> Stage 3: ChEMBL drug profiles inline)
  with inline rubric assessment.
- hypothesis_writer: Hypothesis generation with UCB scoring from all evidence.
- report_writer: Generate drug.md with featured candidate emphasis.

Workflow order: evidence_assessor -> hypothesis_writer -> report_writer

The `deep_diver` subagent is preserved in SUBAGENT_CONFIGS as an optional
standalone subagent (for manual re-runs or debug flows), but is NOT part
of the default happy path — Stage 3 now runs inside evidence_assessor.
"""

from typing import Callable, Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from src.agents.deep_interpreter.middleware.write_file_guard import (
    WriteFileArgGuardMiddleware,
    ReadFileBlockMiddleware,
)
from src.agents.drug_target.subagents.prompts import SUBAGENT_PROMPTS
from src.agents.drug_target.tools import (
    # Evidence I/O tools
    load_lr_candidates,
    save_evidence,
    load_evidence_files,
    validate_evidence_completeness,
    validate_evidence_references,
    # Stage 2: Target Validation (runs FIRST)
    query_stage2_gene_panel,
    query_ensembl_vep_consequence,
    compute_rubric_scores,
    # Stage 1: Biological Context (FEATURED pairs only)
    query_cellxgene_lr_context,
    list_census_diseases,
    list_census_cell_types,
    query_string_ppi_pair,
    run_compare_census_lr_pair,
    run_batch_census_lr_pairs,
    run_stage1_batch,
    finalize_stage1_artifacts,
    validate_stage1_gate,
    validate_stage3_gate,
    # Stage 3: Deep Dive
    query_chembl_target_profile,
    read_skill_file,
    # Report: Reference Card + Validation
    build_evidence_summary,
    validate_drug_md,
    # Assessment output
    save_target_assessment,
    save_drug_md,
    # HTML report generation
    generate_drug_html_report,
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
# 4-Subagent Configuration Definitions
# =============================================================================

SUBAGENT_CONFIGS = {
    "evidence_assessor": {
        "name": "evidence_assessor",
        "description": (
            "3-stage funnel: Stage 2 first (all genes: OpenTargets/GWAS) -> "
            "rubric scoring (combined_total >= 10) -> gene selection -> "
            "Stage 1 (FEATURED pairs only: Cellxgene, STRING, Census) -> "
            "Stage 1 gate validation -> Stage 3 (ChEMBL drug profiles for FEATURED genes). "
            "Includes inline rubric assessment via compute_rubric_scores. "
            "Uses Plan->Execute->Reflect cycle per stage. "
            "Stage 3 (ChEMBL drug profiles) runs inline after Stage 1 gate passes."
        ),
        "system_prompt": SUBAGENT_PROMPTS["evidence_assessor"],
        "tools": [
            # I/O
            load_lr_candidates,
            save_evidence,
            load_evidence_files,
            # Phase 0: Disease vocabulary matching
            list_census_diseases,
            list_census_cell_types,
            # Stage 2: Target Validation (runs FIRST — batch all genes)
            query_stage2_gene_panel,
            query_ensembl_vep_consequence,
            compute_rubric_scores,
            # Stage 1: Biological Context (FEATURED pairs only, after gene selection)
            query_cellxgene_lr_context,
            query_string_ppi_pair,
            run_compare_census_lr_pair,
            run_batch_census_lr_pairs,
            run_stage1_batch,
            finalize_stage1_artifacts,
            validate_stage1_gate,
            # Stage 3: ChEMBL deep dive (inline after Stage 1)
            query_chembl_target_profile,
            validate_stage3_gate,
            read_skill_file,
            # Cognitive
            sequential_thinking,
            think_tool,
            validate_quality,
        ],
    },
    "deep_diver": {
        "name": "deep_diver",
        "description": (
            "Stage 3 deep dive for FEATURED genes. Queries ChEMBL for drug profiles. "
            "Produces stage3_{GENE}.json for each stage3_candidate. "
            "Validates completeness via validate_stage3_gate."
        ),
        "system_prompt": SUBAGENT_PROMPTS["deep_diver"],
        "tools": [
            # I/O
            load_evidence_files,
            save_evidence,
            # Stage 3: Deep Dive
            query_chembl_target_profile,
            validate_stage3_gate,
            read_skill_file,
            # Cognitive
            sequential_thinking,
            think_tool,
            validate_quality,
        ],
    },
    "hypothesis_writer": {
        "name": "hypothesis_writer",
        "description": (
            "Hypothesis generation from Stage 1-3 evidence. Reads all evidence files, "
            "generates 4-6 mechanistic hypotheses across 4 thematic categories, "
            "applies gap detection and UCB scoring, outputs hypothesis_report.json."
        ),
        "system_prompt": SUBAGENT_PROMPTS["hypothesis_writer"],
        "tools": [
            load_evidence_files,
            read_skill_file,
            save_evidence,
            validate_evidence_references,
            # sequential_thinking removed: this subagent is template-driven (fixed Phases 1→5);
            # planning tool induced infinite-loop stalls on small local LLMs (qwen3.5).
            # Reflection is still available via think_tool below.
            think_tool,
            validate_quality,
        ],
        "middleware": [ReadFileBlockMiddleware()],  # Block read_file, force load_evidence_files
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
            "Featured candidates are determined by rubric scoring (combined_total). "
            "Optionally generates drug_report.html (interactive HTML version)."
        ),
        "system_prompt": SUBAGENT_PROMPTS["report_writer"],
        "tools": [
            load_lr_candidates,
            load_evidence_files,
            validate_evidence_completeness,
            build_evidence_summary,
            validate_drug_md,
            validate_stage3_gate,
            save_target_assessment,
            save_drug_md,
            read_skill_file,
            sequential_thinking,
            think_tool,
            validate_quality,
            generate_drug_html_report,
        ],
    },
}


# =============================================================================
# Workflow Order
# =============================================================================

WORKFLOW_ORDER = ["evidence_assessor", "hypothesis_writer", "report_writer"]

WORKFLOW_DESCRIPTION = """
Drug Target Assessment 3-Agent Workflow (Staged Funnel):

1. EVIDENCE_ASSESSOR (Plan->Execute->Reflect per stage)
   Stage 2 FIRST (ALL unique genes): batch OpenTargets + batch GWAS + VEP (conditional)
     -> Inline DRUG_TARGET_RUBRIC scoring (compute_rubric_scores)
     -> Gene selection (combined_total >= 10) → FEATURED genes
     -> Gene→Pair mapping to identify FEATURED L-R pairs
   Stage 1 (FEATURED pairs ONLY): Cellxgene + STRING + Census
     -> Stage 1 gate validation (validate_stage1_gate)
   Stage 3 (FEATURED genes, inline): ChEMBL drug profiles
     -> stage3_{GENE}.json per gene (idempotent, skips completed genes)
     -> validate_stage3_gate (skipped on zero-candidate)
   Outputs: evidence/*.json (per stage, per L-R pair/gene)
            assessment_results.json, rubric_scores.csv, stage3_{GENE}.json
   Gate: assessment_results.json must exist with stage3_candidates

2. HYPOTHESIS_WRITER (Plan->Execute->Reflect)
   Reads all Stage 1-3 evidence files
   Generates 4-6 mechanistic hypotheses across 4 thematic categories
   Applies gap detection and UCB scoring
   Outputs: hypothesis_report.json
   Gate: hypothesis_report.json must exist

3. REPORT_WRITER (Plan->Execute->Reflect)
   - Generates target_assessment.json (structured contract)
   - Generates drug.md with structure:
     1. Executive Summary
     2. Pan-Disease Target Druggability Matrix
     3. [FEATURED] Candidate Deep Dives
     3.5. Hypothesis-Driven Analysis (if hypothesis_report.json exists)
     4. [NOVEL] Candidate Deep Dives
     5. Pipeline Execution Summary & Recommendations
   - Quality validation (threshold >= 0.7)

Optional/standalone subagents (NOT in happy path):
- DEEP_DIVER: preserved in SUBAGENT_CONFIGS for manual re-runs or debug flows.
  Stage 3 ChEMBL logic also runs inline inside evidence_assessor by default.
"""


# =============================================================================
# Public API
# =============================================================================

def get_subagents(
    custom_tools: Sequence[BaseTool | Callable] | None = None,
    data_dir: str | None = None,
    disease: str | None = None,
    model_overrides: dict[str, BaseChatModel | str] | None = None,
    enable_census: bool = True,
    skills_sources: list[str] | None = None,
    skill_registry: dict[str, str] | None = None,
    skills_dir: str | None = None,
    subagent_skill_names: dict[str, tuple[str, ...]] | None = None,
    subagent_skill_registries: dict[str, dict[str, str]] | None = None,
) -> list[dict]:
    """Get the subagent configurations for Drug Target Assessment.

    Returns 3 subagents in workflow order (deep_diver remains in
    SUBAGENT_CONFIGS as an optional standalone but is NOT in the happy path):
    1. evidence_assessor - 3-stage funnel with inline rubric assessment
       (Stage 2 -> Stage 1 -> Stage 3 ChEMBL inline)
    2. hypothesis_writer - hypothesis generation with UCB scoring
    3. report_writer - drug.md generation

    Args:
        custom_tools: Optional list of additional tools to include in all subagents
        data_dir: Resolved data directory path to inject into subagent prompts
        disease: Disease context to inject into subagent prompts
        model_overrides: Optional per-subagent model overrides.
            Keys are subagent names, values are init_chat_model format strings
            (e.g. "openai:gpt-4.1") or BaseChatModel instances.
        skills_sources: Legacy deepagents-native skill source paths.
        skill_registry: Legacy shared SkillActivator registry.
        skills_dir: Project skills directory for allow-listed SkillsMiddleware.
        subagent_skill_names: Per-subagent allowed skill tuples.
        subagent_skill_registries: Per-subagent registries for SkillActivator.

    Returns:
        List of subagent configuration dictionaries
    """
    subagents = [
        {**SUBAGENT_CONFIGS[name], "tools": list(SUBAGENT_CONFIGS[name]["tools"])}
        for name in WORKFLOW_ORDER
    ]

    # Remove Census tools when disabled (too slow for some providers)
    if not enable_census:
        _census_tool_names = {
            "query_cellxgene_lr_context",
            "list_census_diseases",
            "run_compare_census_lr_pair",
            "run_batch_census_lr_pairs",
        }
        for subagent in subagents:
            if subagent["name"] == "evidence_assessor":
                subagent["tools"] = [
                    t for t in subagent["tools"]
                    if getattr(t, "name", None) not in _census_tool_names
                ]
                subagent["system_prompt"] += (
                    "\n\n## Census API: DISABLED\n"
                    "Census tools (`query_cellxgene_lr_context`, `list_census_diseases`, "
                    "`list_census_cell_types`, `run_compare_census_lr_pair`, "
                    "`run_batch_census_lr_pairs`) are NOT available in this run.\n"
                    "- Skip Phase 0 Census disease/cell-type matching entirely.\n"
                    "- Skip the `cellxgene-census` and "
                    "`compare-census-gene-pair-by-cell-type` skill guides.\n"
                    "- In Stage 1, rely on STRING-only validation via run_stage1_batch(enable_census=false).\n"
                    "- Do NOT call query_cellxgene_lr_context, run_compare_census_lr_pair, "
                    "or run_batch_census_lr_pairs.\n"
                )

    # Apply per-subagent model overrides
    if model_overrides:
        for subagent in subagents:
            if subagent["name"] in model_overrides:
                subagent["model"] = model_overrides[subagent["name"]]

    # Inject data_dir and disease into each subagent's system prompt
    if data_dir:
        disease_line = ""
        if disease:
            disease_line = (
                f"- **Disease context**: `{disease}`\n"
                f"Pass `disease=\"{disease}\"` to `load_lr_candidates` so the CLI disease "
                f"context takes priority over lr_candidates.json.\n"
            )
        data_dir_note = (
            f"\n\n## Data Directory\n"
            f"The data directory for this session is: `{data_dir}`\n"
            f"Pass this exact path as `data_dir` to all tool calls "
            f"(load_lr_candidates, load_evidence_files, save_evidence).\n"
            f"{disease_line}"
        )
        for subagent in subagents:
            subagent["system_prompt"] = subagent["system_prompt"] + data_dir_note

    if custom_tools:
        for subagent in subagents:
            current_tools = list(subagent.get("tools", []))
            current_tools.extend(custom_tools)
            subagent["tools"] = current_tools

    # Guard write_file tool calls against non-string content emitted by some models.
    for subagent in subagents:
        mw = list(subagent.get("middleware", []))
        mw.insert(0, WriteFileArgGuardMiddleware())
        subagent["middleware"] = mw

    # Primary subagents use allow-listed shared SkillsMiddleware + SkillActivator.
    # Do NOT set `subagent["skills"]` in this path; deepagents would auto-attach
    # its native SkillsMiddleware and defeat the allow-list.
    if skills_dir and subagent_skill_names and subagent_skill_registries:
        from src.agents.shared.skill_activator import SkillActivator
        from src.agents.shared.skills_middleware import SkillsMiddleware

        for subagent in subagents:
            allowed_names = subagent_skill_names.get(subagent["name"])
            if not allowed_names:
                continue
            mw = list(subagent.get("middleware", []))
            mw.append(
                SkillsMiddleware(
                    skills_dir=skills_dir,
                    allowed_skill_names=allowed_names,
                )
            )
            mw.append(
                SkillActivator(
                    skill_registry=subagent_skill_registries.get(subagent["name"], {}),
                )
            )
            subagent["middleware"] = mw
    elif skills_sources:
        # Legacy path retained for callers that still use deepagents native
        # skill auto-loading.
        _skill_subagents = {"evidence_assessor", "deep_diver", "report_writer"}
        for subagent in subagents:
            if subagent["name"] in _skill_subagents:
                subagent["skills"] = skills_sources
                if skill_registry:
                    from src.agents.shared.skill_activator import SkillActivator
                    mw = list(subagent.get("middleware", []))
                    mw.append(SkillActivator(
                        skill_registry=skill_registry,
                    ))
                    subagent["middleware"] = mw

    return subagents
