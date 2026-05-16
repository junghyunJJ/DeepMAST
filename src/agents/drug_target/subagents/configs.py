"""Subagent configurations for Drug Target Assessment Agent.

Three-subagent staged funnel (happy path):
- evidence_assessor: 3-stage funnel (Stage 2: validation & scoring ->
  Stage 1: biological context -> Stage 3: ChEMBL drug profiles inline)
  with inline rubric assessment.
- hypothesis_writer: Hypothesis generation with UCB scoring from all evidence.
- summarizer: Flat dict subagent (2026-05-13 simplification) that authors and
  finalizes drug.md via the 6-step tool sequence
  (build_evidence_summary -> load_evidence_files -> save_report_expansions
  -> render_drug_md_from_expansions -> validate_drug_md
  -> generate_drug_html_report). Quality gating is a combination of
  ``validate_drug_md`` (semantic) and ``SummarizerFinalizationGuardMiddleware``
  (mechanical: blocks HTML generation until the validator passes).

Workflow order: evidence_assessor -> hypothesis_writer -> summarizer
"""

import json
import re
from pathlib import Path
from typing import Callable, Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from src.agents.deep_interpreter.middleware.write_file_guard import (
    ReadFileBlockMiddleware,
    WriteFileArgGuardMiddleware,
)
from src.agents.drug_target.subagents.prompts import SUBAGENT_PROMPTS
from src.agents.drug_target.subagents.summarizer import get_summarizer_subagent
from src.agents.drug_target.subagents.summarizer.middleware import (
    HypothesisRetryLoopMiddleware,
)
from src.agents.drug_target.tools import (
    compute_rubric_scores,
    finalize_stage1_artifacts,
    list_census_cell_types,
    list_census_diseases,
    load_evidence_files,
    load_lr_candidates,
    query_cellxgene_lr_context,
    query_chembl_target_profile,
    query_ensembl_vep_consequence,
    query_stage2_gene_panel,
    query_string_ppi_pair,
    read_skill_file,
    run_batch_census_lr_pairs,
    run_compare_census_lr_pair,
    run_stage1_batch,
    save_evidence,
    save_hypothesis_report,
    sequential_thinking,
    think_tool,
    validate_evidence_references,
    validate_quality,
    validate_stage1_gate,
    validate_stage3_gate,
)

__all__ = [
    "SUBAGENT_CONFIGS",
    "WORKFLOW_ORDER",
    "filter_hypothesis_evidence_files",
    "get_subagents",
]


# Keys on each hypothesis dict that may carry a list of evidence file
# references. Different hypothesis_writer prompt revisions have used different
# names; the filter strips nonexistent entries from each.
_EVIDENCE_FILE_KEYS = ("evidence_files", "evidence_references")

# Matches a JSON filename that may be followed by the ``_FAILED`` upstream
# marker, possibly with surrounding bracket characters.
_JSON_FAILED_SUFFIX_RE = re.compile(r"(\b[\w-]+\.json)_FAILED\b")

# Pattern that matches the first ASCII control character (includes \n, \r, \t,
# null bytes, BEL, and all other \x00-\x1f characters).  Everything from that
# character onward is truncated so injected text cannot masquerade as a new
# Markdown heading or instruction block inside a prompt.
_PROMPT_CONTROL_RE = re.compile(r"[\x00-\x1f].*", re.DOTALL)


def _sanitize_prompt_value(value: str | None) -> str:
    """Truncate *value* at the first control character before prompt injection.

    Strips everything from the first ASCII control character (\\x00-\\x1f,
    which includes \\n, \\r, \\t, null bytes, and BEL) onward, then strips
    leading/trailing whitespace.  Returns an empty string for None input.
    """
    if value is None:
        return ""
    return _PROMPT_CONTROL_RE.sub("", value).strip()


# Backwards-compatible alias so existing callers and tests continue to work.
_sanitize_data_dir = _sanitize_prompt_value


def _strip_failed_suffix_in_strings(node: object) -> tuple[object, int]:
    """Replace ``<file>.json_FAILED`` with ``<file>.json`` in every string value."""
    if isinstance(node, str):
        new, n = _JSON_FAILED_SUFFIX_RE.subn(r"\1", node)
        return new, n
    if isinstance(node, list):
        total = 0
        out_list: list[object] = []
        for item in node:
            new_item, n = _strip_failed_suffix_in_strings(item)
            out_list.append(new_item)
            total += n
        return out_list, total
    if isinstance(node, dict):
        total = 0
        out_dict: dict[str, object] = {}
        for k, v in node.items():
            new_v, n = _strip_failed_suffix_in_strings(v)
            out_dict[k] = new_v
            total += n
        return out_dict, total
    return node, 0


def filter_hypothesis_evidence_files(data_dir: str) -> int:
    """Drop hypothesis_report.json evidence-list entries not present on disk.

    Two passes:
      1. List-key pass — every list-shaped entry under any key in
         ``_EVIDENCE_FILE_KEYS`` is filtered: entries ending with ``_FAILED``
         and entries whose target path does not exist under
         ``<data_dir>/evidence/`` are dropped.
      2. Prose pass — every string value anywhere in the document has
         ``<file>.json_FAILED`` rewritten to ``<file>.json``.

    Accepts both on-disk shapes:
      1. ``{"hypotheses": [{"evidence_files": [...]}, ...]}`` — current pipeline
      2. ``[{"evidence_files": [...]}, ...]`` — legacy/test fixtures

    The file is rewritten in place only when at least one entry is dropped or
    one suffix is stripped.

    Args:
        data_dir: Run working directory (parent of ``evidence/``).

    Returns:
        Total number of mutations (list-entry drops + prose suffix strips).
    """
    evidence_dir = Path(data_dir) / "evidence"
    hyp_path = evidence_dir / "hypothesis_report.json"
    if not evidence_dir.exists() or not hyp_path.exists():
        return 0

    try:
        data = json.loads(hyp_path.read_text())
    except Exception:
        return 0

    if isinstance(data, dict):
        hyps = data.get("hypotheses") or []
        container = data
    elif isinstance(data, list):
        hyps = data
        container = None
    else:
        return 0

    dropped = 0
    for hyp in hyps:
        if not isinstance(hyp, dict):
            continue
        for key in _EVIDENCE_FILE_KEYS:
            files = hyp.get(key)
            if not isinstance(files, list):
                continue
            kept = [
                f
                for f in files
                if isinstance(f, str)
                and not f.endswith("_FAILED")
                and (evidence_dir / f).exists()
            ]
            dropped += len(files) - len(kept)
            hyp[key] = kept

    target = container if container is not None else hyps
    rewritten, suffix_strips = _strip_failed_suffix_in_strings(target)
    total_mutations = dropped + suffix_strips

    if total_mutations:
        hyp_path.write_text(json.dumps(rewritten, indent=2))
    return total_mutations


# =============================================================================
# Subagent Configuration Definitions
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
            save_hypothesis_report,
            save_evidence,
            validate_evidence_references,
            think_tool,
            validate_quality,
        ],
        "middleware": [
            ReadFileBlockMiddleware(),
        ],  # Block read_file, force load_evidence_files
    },
}


# =============================================================================
# Workflow Order
# =============================================================================

WORKFLOW_ORDER = ["evidence_assessor", "hypothesis_writer", "summarizer"]

_TOP_LEVEL_SUBAGENTS = ("evidence_assessor", "hypothesis_writer")

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

3. SUMMARIZER (flat dict subagent — 2026-05-13 simplification)
   Six-step tool sequence executed by a single tool-calling LLM:
     build_evidence_summary -> load_evidence_files -> save_report_expansions
       -> render_drug_md_from_expansions -> validate_drug_md
       -> generate_drug_html_report
   Emits SUMMARIZER_STATUS: PASS or SUMMARIZER_STATUS: FAIL on its own line.
   Quality gating:
     - validate_drug_md (semantic gate, mandatory)
     - SummarizerFinalizationGuardMiddleware (mechanical: blocks
       generate_drug_html_report unless validate_drug_md returned valid=true)
"""


# =============================================================================
# Public API
# =============================================================================

def get_subagents(
    custom_tools: Sequence[BaseTool | Callable] | None = None,
    data_dir: str | None = None,
    disease: str | None = None,
    model_overrides: dict[str, BaseChatModel | str] | None = None,
    default_model: BaseChatModel | str | None = None,
    backend: object | None = None,
    enable_census: bool = True,
    critic_enabled: bool = True,
    skills_sources: list[str] | None = None,
    skill_registry: dict[str, str] | None = None,
    skills_dir: str | None = None,
    subagent_skill_names: dict[str, tuple[str, ...]] | None = None,
    subagent_skill_registries: dict[str, dict[str, str]] | None = None,
) -> list[dict]:
    """Build the three drug-target subagents in workflow order.

    Returns a list of three flat dict subagents:
      1. evidence_assessor — 3-stage funnel with inline rubric assessment.
      2. hypothesis_writer — hypothesis generation with UCB scoring.
      3. summarizer — single dict subagent owning the drug.md authoring +
         validation + HTML rendering workflow.

    Args:
        custom_tools: Additional tools to inject into evidence_assessor and
            hypothesis_writer (not the summarizer — its tool set is fixed).
        data_dir: Resolved data directory path; appended to each subagent's
            system prompt as a ``Data Directory`` note.
        disease: Disease context appended alongside ``data_dir``.
        model_overrides: Optional per-subagent model overrides keyed by
            subagent name (``evidence_assessor``, ``hypothesis_writer``,
            ``summarizer``).
        default_model: Reserved for forward-compat; the new dict summarizer
            inherits the parent agent's model when no override is provided.
        backend: Passed into get_summarizer_subagent for future SubAgentMiddleware
            wiring (task #4). Currently accepted and forwarded unchanged.
        critic_enabled: When False the critic gate is disabled inside the
            summarizer. Forwarded unchanged to get_summarizer_subagent.
        enable_census: When False, strips Census tools from evidence_assessor
            and appends a disabled-notice to its prompt.
        skills_sources: Legacy deepagents-native skill source paths.
        skill_registry: Legacy shared SkillActivator registry.
        skills_dir: Project skills directory for allow-listed SkillsMiddleware.
        subagent_skill_names: Per-subagent allowed skill tuples.
        subagent_skill_registries: Per-subagent registries for SkillActivator.

    Returns:
        List of three subagent configuration dictionaries.
    """
    # Resolve critic_model: critic override > summarizer override > default_model.
    overrides = model_overrides or {}
    critic_model: BaseChatModel | str | None = (
        overrides.get("critic")
        or overrides.get("summarizer")
        or default_model
    )

    subagents = [
        {**SUBAGENT_CONFIGS[name], "tools": list(SUBAGENT_CONFIGS[name]["tools"])}
        for name in _TOP_LEVEL_SUBAGENTS
    ]
    subagents.append(
        get_summarizer_subagent(
            backend=backend,
            default_model=default_model,
            critic_model=critic_model,
            critic_enabled=critic_enabled,
        )
    )

    for subagent in subagents:
        if subagent["name"] == "hypothesis_writer":
            subagent["middleware"] = [
                *list(subagent.get("middleware", [])),
                HypothesisRetryLoopMiddleware(),
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
            safe_disease = _sanitize_prompt_value(disease)
            disease_line = (
                f"- **Disease context**: `{safe_disease}`\n"
                f"Pass `disease=\"{safe_disease}\"` to `load_lr_candidates` so the CLI disease "
                f"context takes priority over lr_candidates.json.\n"
            )
        safe_data_dir = _sanitize_prompt_value(data_dir)
        data_dir_note = (
            f"\n\n## Data Directory\n"
            f"The data directory for this session is: `{safe_data_dir}`\n"
            f"Pass this exact path as `data_dir` to all tool calls "
            f"(load_lr_candidates, load_evidence_files, save_evidence).\n"
            f"{disease_line}"
        )
        for subagent in subagents:
            subagent["system_prompt"] = subagent["system_prompt"] + data_dir_note

    if custom_tools:
        # Custom tools go to evidence_assessor and hypothesis_writer only; the
        # summarizer tool surface is fixed by `get_summarizer_subagent()`.
        for subagent in subagents:
            if subagent["name"] == "summarizer":
                continue
            current_tools = list(subagent.get("tools", []))
            current_tools.extend(custom_tools)
            subagent["tools"] = current_tools

    # Guard write_file tool calls against non-string content emitted by some models.
    for subagent in subagents:
        mw = list(subagent.get("middleware", []))
        mw.insert(0, WriteFileArgGuardMiddleware(backend_root=data_dir))
        subagent["middleware"] = mw

    # Primary subagents use allow-listed shared SkillsMiddleware + SkillActivator.
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
        _skill_subagents = {"evidence_assessor", "summarizer"}
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
