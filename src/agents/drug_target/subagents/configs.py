"""Subagent configurations for Drug Target Assessment Agent.

Production workflow: ``evidence_assessor -> report_writer``. The guarded
report writer authors validated report sections, then deterministic rendering
produces report artifacts before middleware validation, repair, publication,
and audit.

``hypothesis_writer`` and the deterministic ``finalize_report`` super-graph
are retained only by :func:`get_legacy_subagents` for explicit
``legacy_hypothesis`` compatibility callers.
"""

import json
import re
from pathlib import Path
from typing import Any, Callable, Literal, Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langchain_core.tools.structured import StructuredTool

from src.agents.deep_interpreter.middleware.write_file_guard import (
    ReadFileBlockMiddleware,
    WriteFileArgGuardMiddleware,
)
from src.agents.drug_target.subagents.prompts import (
    HypothesisWriterPromptMode,
    REPORT_WRITER_PROMPT,
    SUBAGENT_PROMPTS,
    render_hypothesis_writer_prompt,
)
from src.agents.drug_target.middleware import (
    DrugReportGuardrailMiddleware,
    DrugTargetManagedFilesystemGuardMiddleware,
    HypothesisRetryLoopMiddleware,
)
from src.agents.drug_target.production_report_tools import (
    production_assessment_evidence_tool,
    production_assessment_save_evidence_tool,
    production_evidence_summary_tool,
    production_hypothesis_evidence_tool,
    production_save_report_sections_tool,
    production_skill_reader_tool,
)
from src.agents.drug_target.tools import (
    apply_semantic_celltype_proxy,
    build_evidence_summary,
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
    resolve_census_celltypes,
    search_census_celltype_options,
    run_stage3_batch,
    run_batch_census_lr_pairs,
    run_compare_census_lr_pair,
    run_stage1_batch,
    save_evidence,
    save_drug_md,
    save_hypothesis_report,
    save_target_assessment,
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
    "LEGACY_WORKFLOW_ORDER",
    "filter_hypothesis_evidence_files",
    "get_subagents",
    "get_legacy_subagents",
]

SkillActivationMode = Literal[
    "middleware_only",
    "middleware_plus_activator",
    "middleware_plus_governor",
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


def _disabled_census_stage1_batch_tool() -> StructuredTool:
    """Return a run_stage1_batch variant that cannot enable Census queries."""

    def _run_stage1_batch_census_disabled(
        data_dir: str,
        disease: str,
        target_cell_type: str = "",
        enable_census: bool = False,
    ):
        func = getattr(run_stage1_batch, "func", None)
        if func is None:
            return run_stage1_batch.invoke(
                {
                    "data_dir": data_dir,
                    "disease": disease,
                    "target_cell_type": target_cell_type,
                    "enable_census": False,
                }
            )
        return func(
            data_dir=data_dir,
            disease=disease,
            target_cell_type=target_cell_type,
            enable_census=False,
        )

    return StructuredTool.from_function(
        func=_run_stage1_batch_census_disabled,
        name="run_stage1_batch",
        description=(
            f"{run_stage1_batch.description}\n\n"
            "Census is disabled for this run; this wrapper always forwards "
            "enable_census=False even if the caller omits it or passes true."
        ),
    )


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
            resolve_census_celltypes,
            search_census_celltype_options,
            apply_semantic_celltype_proxy,
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
            run_stage3_batch,
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
            "Legacy compatibility hypothesis generation from Stage 1-3 evidence. "
            "Reads all evidence files, "
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
    "report_writer": {
        "name": "report_writer",
        "description": "Guarded author of validated report sections.",
        "system_prompt": REPORT_WRITER_PROMPT,
        "tools": [
            load_lr_candidates,
            load_evidence_files,
            build_evidence_summary,
            read_skill_file,
            production_save_report_sections_tool,
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
_TOP_LEVEL_SUBAGENTS = ("evidence_assessor", "report_writer")

# Deprecated compatibility ordering for the outer super-graph and benchmarks.
LEGACY_WORKFLOW_ORDER = ["evidence_assessor", "hypothesis_writer"]
_LEGACY_TOP_LEVEL_SUBAGENTS = ("evidence_assessor", "hypothesis_writer")

_DTH_SINGLE_READ_PROMPT_MODES = frozenset(
    {
        "operational_contract_plus_dth",
        "operational_contract_minimal_plus_dth",
    }
)
_DTH_SKILL_PATH = "skills/drug-target-hypothesis/SKILL.md"

WORKFLOW_DESCRIPTION = """
Drug Target Assessment Production 2-Agent Workflow (Staged Funnel):

1. EVIDENCE_ASSESSOR (Plan->Execute->Reflect per stage)
   Stage 2 FIRST (ALL unique genes): batch OpenTargets + batch GWAS + VEP (conditional)
     -> Inline DRUG_TARGET_RUBRIC scoring (compute_rubric_scores)
     -> Gene selection (combined_total >= 10) → FEATURED genes
     -> Gene→Pair mapping to identify FEATURED L-R pairs
   Stage 1 (FEATURED pairs ONLY): Cellxgene + STRING + Census
     -> Stage 1 gate validation (validate_stage1_gate)
   Stage 3 (FEATURED genes, inline): run_stage3_batch ChEMBL drug profiles
     -> stage3_{GENE}.json per gene (idempotent, skips completed genes)
     -> validate_stage3_gate internally (skipped on zero-candidate)
   Outputs: evidence/*.json (per stage, per L-R pair/gene)
            assessment_results.json, rubric_scores.csv, stage3_{GENE}.json
   Gate: assessment_results.json must exist with stage3_candidates

2. REPORT_WRITER (guarded direct author)
   Reads bounded hypothesis-scope evidence and the reporting skill.
   Writes target_assessment.json exactly once, then drug.md exactly once.
   DrugReportGuardrailMiddleware validates, repairs, publishes, and writes
   initial/final audit artifacts.

Legacy compatibility topology only (explicit ``legacy_hypothesis`` callers):

2. HYPOTHESIS_WRITER (Plan->Execute->Reflect)
   Reads all Stage 1-3 evidence files
   Generates 4-6 mechanistic hypotheses across 4 thematic categories
   Applies gap detection and UCB scoring
   Outputs: hypothesis_report.json
   Gate: hypothesis_report.json must exist

3. LEGACY FINALIZE_REPORT NODE (deterministic post-agent): super-graph node renders
   drug.md + HTML + target_assessment.json with cited-only provenance +
   token-budget fail-closed gate. See src/agents/drug_target/finalize_report.py.
"""


# =============================================================================
# Public API
# =============================================================================

def get_legacy_subagents(
    custom_tools: Sequence[BaseTool | Callable] | None = None,
    data_dir: str | None = None,
    disease: str | None = None,
    model_overrides: dict[str, BaseChatModel | str] | None = None,
    default_model: BaseChatModel | str | None = None,
    backend: object | None = None,
    enable_census: bool = True,
    skills_sources: list[str] | None = None,
    skill_registry: dict[str, str] | None = None,
    skills_dir: str | None = None,
    subagent_skill_names: dict[str, tuple[str, ...]] | None = None,
    subagent_skill_registries: dict[str, dict[str, str]] | None = None,
    enable_skill_activator: bool = True,
    skill_activation_mode: SkillActivationMode | None = None,
    hypothesis_writer_prompt_mode: HypothesisWriterPromptMode = "default",
) -> list[dict]:
    """Build the explicit legacy hypothesis workflow without production guards.

    Returns a list of two flat dict subagents:
      1. evidence_assessor — 3-stage funnel with inline rubric assessment.
      2. hypothesis_writer — hypothesis generation with UCB scoring.

    Legacy report finalization is handled by the deterministic
    ``finalize_report`` LangGraph node after the DeepAgents harness completes.

    Args:
        custom_tools: Additional tools to inject into each subagent.
        data_dir: Resolved data directory path; appended to each subagent's
            system prompt as a ``Data Directory`` note.
        disease: Disease context appended alongside ``data_dir``.
        model_overrides: Optional per-subagent model overrides keyed by
            subagent name (``evidence_assessor``, ``hypothesis_writer``).
        default_model: Reserved for forward-compat.
        backend: Accepted for API compat; not forwarded to any subagent.
        enable_census: When False, strips Census tools from evidence_assessor
            and appends a disabled-notice to its prompt.
        skills_sources: Legacy deepagents-native skill source paths.
        skill_registry: Legacy shared SkillActivator registry.
        skills_dir: Project skills directory for allow-listed SkillsMiddleware.
        subagent_skill_names: Per-subagent allowed skill tuples.
        subagent_skill_registries: Per-subagent registries for SkillActivator.
        enable_skill_activator: Whether to add SkillActivator after
            SkillsMiddleware. Set False for passive middleware-only activation
            benchmarks.
        skill_activation_mode: Optional explicit activation strategy. When
            omitted, derives from enable_skill_activator for compatibility.
        hypothesis_writer_prompt_mode: Prompt variant for legacy hypothesis_writer.
            ``default`` preserves legacy prompt-level skill reads;
            ``progressive_disclosure_only`` removes those benchmark-confounding
            direct reads so SkillsMiddleware/activator/governor owns selection.

    Returns:
        List of three subagent configuration dictionaries.
    """
    subagents = [
        {**SUBAGENT_CONFIGS[name], "tools": list(SUBAGENT_CONFIGS[name]["tools"])}
        for name in _LEGACY_TOP_LEVEL_SUBAGENTS
    ]

    for subagent in subagents:
        if subagent["name"] == "hypothesis_writer":
            subagent["system_prompt"] = render_hypothesis_writer_prompt(
                hypothesis_writer_prompt_mode
            )
            subagent["middleware"] = [
                *list(subagent.get("middleware", [])),
                HypothesisRetryLoopMiddleware(
                    stop_after_first_save=(
                        hypothesis_writer_prompt_mode.startswith("thin_basic")
                    ),
                    max_hypothesis_save_attempts=(
                        3
                        if hypothesis_writer_prompt_mode.startswith(
                            ("dth_contrast", "operational_contract")
                        )
                        else None
                    ),
                    single_read_skill_paths=(
                        (_DTH_SKILL_PATH,)
                        if hypothesis_writer_prompt_mode in _DTH_SINGLE_READ_PROMPT_MODES
                        else ()
                    ),
                ),
            ]

    # Remove Census tools when disabled (too slow for some providers)
    if not enable_census:
        _census_tool_names = {
            "query_cellxgene_lr_context",
            "list_census_diseases",
            "list_census_cell_types",
            "resolve_census_celltypes",
            "search_census_celltype_options",
            "apply_semantic_celltype_proxy",
            "run_compare_census_lr_pair",
            "run_batch_census_lr_pairs",
        }
        for subagent in subagents:
            if subagent["name"] == "evidence_assessor":
                subagent["tools"] = [
                    _disabled_census_stage1_batch_tool()
                    if getattr(t, "name", None) == "run_stage1_batch"
                    else t
                    for t in subagent["tools"]
                    if getattr(t, "name", None) not in _census_tool_names
                ]
                subagent["system_prompt"] += (
                    "\n\n## Census API: DISABLED\n"
                    "Census tools (`query_cellxgene_lr_context`, `list_census_diseases`, "
                    "`list_census_cell_types`, `resolve_census_celltypes`, "
                    "`search_census_celltype_options`, `apply_semantic_celltype_proxy`, "
                    "`run_compare_census_lr_pair`, "
                    "`run_batch_census_lr_pairs`) are NOT available in this run.\n"
                    "- Skip Phase 0 Census disease/cell-type matching entirely.\n"
                    "- In Stage 1, rely on STRING-only validation via run_stage1_batch(enable_census=false).\n"
                    "- Do NOT call query_cellxgene_lr_context, search_census_celltype_options, "
                    "apply_semantic_celltype_proxy, run_compare_census_lr_pair, or "
                    "run_batch_census_lr_pairs.\n"
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
        for subagent in subagents:
            current_tools = list(subagent.get("tools", []))
            current_tools.extend(custom_tools)
            subagent["tools"] = current_tools

    # Guard write_file tool calls against non-string content emitted by some models.
    for subagent in subagents:
        mw = list(subagent.get("middleware", []))
        mw.insert(0, WriteFileArgGuardMiddleware(backend_root=data_dir))
        subagent["middleware"] = mw

    effective_skill_activation_mode: SkillActivationMode = (
        skill_activation_mode
        if skill_activation_mode is not None
        else (
            "middleware_plus_activator"
            if enable_skill_activator
            else "middleware_only"
        )
    )

    # Primary subagents use allow-listed shared SkillsMiddleware plus optional
    # activation middleware.
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
            if effective_skill_activation_mode == "middleware_plus_activator":
                mw.append(
                    SkillActivator(
                        skill_registry=subagent_skill_registries.get(subagent["name"], {}),
                    )
                )
            elif effective_skill_activation_mode == "middleware_plus_governor":
                from src.agents.shared.skill_activation_governor import (
                    SkillActivationGovernor,
                )

                hard_required_skill_names = (
                    ("drug-target-hypothesis",)
                    if (
                        subagent["name"] == "hypothesis_writer"
                        and hypothesis_writer_prompt_mode == "default"
                        and "drug-target-hypothesis" in allowed_names
                    )
                    else ()
                )
                candidate_skill_names = tuple(
                    name
                    for name in allowed_names
                    if name not in hard_required_skill_names
                )
                mw.append(
                    SkillActivationGovernor(
                        skill_registry=subagent_skill_registries.get(subagent["name"], {}),
                        hard_required_skill_names=hard_required_skill_names,
                        candidate_skill_names=candidate_skill_names,
                        artifact_gate=(
                            "save_hypothesis_report"
                            if subagent["name"] == "hypothesis_writer"
                            else "final artifact"
                        ),
                    )
                )
            elif effective_skill_activation_mode != "middleware_only":
                raise ValueError(
                    "unknown skill_activation_mode: "
                    f"{effective_skill_activation_mode!r}"
                )
            subagent["middleware"] = mw
    elif skills_sources:
        # Legacy path retained for callers that still use deepagents native
        # skill auto-loading.
        _skill_subagents = {"evidence_assessor"}
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


def _tool_data_dir_names(tools: Sequence[BaseTool | Callable]) -> set[str]:
    """Return public tools whose declared schema accepts ``data_dir``."""

    names: set[str] = set()
    for tool in tools:
        name = getattr(tool, "name", getattr(tool, "__name__", ""))
        args = getattr(tool, "args", None)
        if isinstance(args, dict) and "data_dir" in args:
            names.add(str(name))
            continue
        target = getattr(tool, "func", tool)
        try:
            import inspect

            if callable(target) and "data_dir" in inspect.signature(target).parameters:
                names.add(str(name))
        except (TypeError, ValueError):
            pass
    return names


def _production_skills_dir(skills_dir: str | None) -> Path:
    if skills_dir:
        return Path(skills_dir).expanduser().resolve()
    from src.agents.shared.utils import find_project_root

    return find_project_root() / "skills"


def get_subagents(
    custom_tools: Sequence[BaseTool | Callable] | None = None,
    data_dir: str | None = None,
    disease: str | None = None,
    provider: str | None = None,
    report_writer_model: str | None = None,
    report_writer_request_timeout_seconds: float | None = None,
    model_overrides: dict[str, BaseChatModel | str] | None = None,
    default_model: BaseChatModel | str | None = None,
    backend: object | None = None,
    enable_census: bool = True,
    skills_sources: list[str] | None = None,
    skill_registry: dict[str, str] | None = None,
    skills_dir: str | None = None,
    subagent_skill_names: dict[str, tuple[str, ...]] | None = None,
    subagent_skill_registries: dict[str, dict[str, str]] | None = None,
    enable_skill_activator: bool = True,
    skill_activation_mode: SkillActivationMode | None = None,
    hypothesis_writer_prompt_mode: HypothesisWriterPromptMode = "default",
) -> list[dict]:
    """Build the guarded production evidence-assessor/report-writer surface.

    ``hypothesis_writer_prompt_mode`` is accepted for source compatibility but
    deliberately ignored: it belongs only to :func:`get_legacy_subagents`.
    """

    _ = custom_tools, default_model, backend, skills_sources, skill_registry
    _ = hypothesis_writer_prompt_mode
    if custom_tools:
        raise ValueError("custom_tools are not allowed in guarded_report mode")
    raw_data_dir = _sanitize_prompt_value(data_dir)
    if not raw_data_dir:
        raise ValueError("guarded production get_subagents requires a non-empty data_dir")

    run_dir = Path(raw_data_dir).expanduser().resolve()
    if not run_dir.exists() or not run_dir.is_dir():
        raise ValueError("guarded production get_subagents requires an existing data_dir")
    safe_data_dir = str(run_dir)
    safe_disease = _sanitize_prompt_value(disease)
    root = _production_skills_dir(skills_dir)
    skill_names = subagent_skill_names or {
        "evidence_assessor": (),
        "report_writer": ("drug-target-reporting",),
    }
    registries = subagent_skill_registries or {
        name: {skill: str(root / skill) for skill in names}
        for name, names in skill_names.items()
    }
    activation_mode: SkillActivationMode = (
        skill_activation_mode
        if skill_activation_mode is not None
        else ("middleware_plus_activator" if enable_skill_activator else "middleware_only")
    )
    if activation_mode not in {
        "middleware_only",
        "middleware_plus_activator",
        "middleware_plus_governor",
    }:
        raise ValueError(f"unknown skill_activation_mode: {activation_mode!r}")

    subagents = [
        {**SUBAGENT_CONFIGS[name], "tools": list(SUBAGENT_CONFIGS[name]["tools"])}
        for name in _TOP_LEVEL_SUBAGENTS
    ]
    for subagent in subagents:
        name = subagent["name"]
        allowed_names = tuple(skill_names.get(name, ()))
        tools = [tool for tool in subagent["tools"] if tool is not None]
        if name == "evidence_assessor":
            tools = [
                production_assessment_evidence_tool(safe_data_dir)
                if getattr(tool, "name", None) == "load_evidence_files"
                else production_assessment_save_evidence_tool(safe_data_dir)
                if getattr(tool, "name", None) == "save_evidence"
                else tool
                for tool in tools
                if getattr(tool, "name", None) != "read_skill_file" or allowed_names
            ]
            if allowed_names:
                tools.append(production_skill_reader_tool(root, allowed_names))
        else:
            replacements = {
                "load_evidence_files": production_hypothesis_evidence_tool(safe_data_dir),
                "build_evidence_summary": production_evidence_summary_tool(safe_data_dir),
                "read_skill_file": production_skill_reader_tool(root, ("drug-target-reporting",)),
            }
            tools = [
                production_save_report_sections_tool(safe_data_dir, safe_disease)
                if tool is production_save_report_sections_tool
                else replacements.get(getattr(tool, "name", ""), tool)
                for tool in tools
            ]

        if not enable_census and name == "evidence_assessor":
            census_names = {
                "query_cellxgene_lr_context", "list_census_diseases", "list_census_cell_types",
                "resolve_census_celltypes", "search_census_celltype_options",
                "apply_semantic_celltype_proxy", "run_compare_census_lr_pair",
                "run_batch_census_lr_pairs",
            }
            tools = [
                _disabled_census_stage1_batch_tool()
                if getattr(tool, "name", None) == "run_stage1_batch"
                else tool
                for tool in tools
                if getattr(tool, "name", None) not in census_names
            ]
        subagent["tools"] = tools
        prompt = subagent["system_prompt"]
        if name == "report_writer":
            prompt = REPORT_WRITER_PROMPT
        available = ", ".join(
            getattr(tool, "name", getattr(tool, "__name__", "tool")) for tool in tools
        )
        subagent["system_prompt"] = (
            f"{prompt}\n\n## Data Directory\n"
            f"The configured data directory is: `{safe_data_dir}`.\n"
            f"Use only these tools: {available}.\n"
            + (f"- **Disease context**: `{safe_disease}`\n" if safe_disease else "")
        )
        middleware = [
            DrugTargetManagedFilesystemGuardMiddleware(
                safe_data_dir,
                data_dir_tool_names=_tool_data_dir_names(
                    [tool for tool in tools if isinstance(tool, BaseTool) or callable(tool)]
                ),
            ),
            WriteFileArgGuardMiddleware(backend_root=safe_data_dir),
        ]
        if name == "report_writer":
            guardrail_kwargs: dict[str, Any] = {
                "data_dir": safe_data_dir,
                "provider": provider,
                "disease": safe_disease,
            }
            if report_writer_model:
                guardrail_kwargs["model"] = report_writer_model
            if report_writer_request_timeout_seconds is not None:
                guardrail_kwargs["request_timeout_seconds"] = (
                    report_writer_request_timeout_seconds
                )
            middleware.append(
                DrugReportGuardrailMiddleware(**guardrail_kwargs)
            )
        if allowed_names:
            from src.agents.shared.skills_middleware import SkillsMiddleware

            middleware.append(
                SkillsMiddleware(skills_dir=root, allowed_skill_names=allowed_names)
            )
            if activation_mode == "middleware_plus_activator":
                from src.agents.shared.skill_activator import SkillActivator

                middleware.append(
                    SkillActivator(skill_registry=registries.get(name, {}))
                )
            elif activation_mode == "middleware_plus_governor":
                from src.agents.shared.skill_activation_governor import SkillActivationGovernor

                hard_required = (
                    ("drug-target-reporting",)
                    if name == "report_writer" and "drug-target-reporting" in allowed_names
                    else ()
                )
                middleware.append(
                    SkillActivationGovernor(
                        skill_registry=registries.get(name, {}),
                        hard_required_skill_names=hard_required,
                        candidate_skill_names=tuple(s for s in allowed_names if s not in hard_required),
                        artifact_gate="save_report_sections" if name == "report_writer" else "final artifact",
                    )
                )
        subagent["middleware"] = middleware
        if model_overrides and name in model_overrides:
            subagent["model"] = model_overrides[name]
    return subagents
