"""Subagent configurations for Drug Target Assessment Agent.

Three-subagent staged funnel with audited finalization (happy path):
- evidence_assessor: 3-stage funnel (Stage 2: validation & scoring ->
  Stage 1: biological context -> Stage 3: ChEMBL drug profiles inline)
  with inline rubric assessment.
- hypothesis_writer: Hypothesis generation with UCB scoring from all evidence.
- summarizer: CompiledSubAgent finalizer that runs report_writer, validators,
  critic, and bounded repair loop.

Workflow order: evidence_assessor -> hypothesis_writer -> summarizer
"""

import json
import os
import re
import shutil
import copy
from pathlib import Path
from typing import Callable, Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from src.agents.deep_interpreter.middleware.write_file_guard import (
    ReadOnlyToolGuardMiddleware,
    WriteFileArgGuardMiddleware,
    ReadFileBlockMiddleware,
)
from src.agents.drug_target.subagents.summarizer import get_summarizer_subagent
from src.agents.drug_target.subagents.summarizer.middleware import (
    HypothesisRetryLoopMiddleware,
)
from src.agents.drug_target.subagents.prompts import SUBAGENT_PROMPTS
from src.agents.drug_target.tools import (
    # Evidence I/O tools
    load_lr_candidates,
    save_evidence,
    load_evidence_files,
    validate_evidence_completeness,
    validate_evidence_references,
    save_hypothesis_report,
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
    save_report_expansions,
    render_drug_md_from_expansions,
    # HTML report generation
    generate_drug_html_report,
    # Common tools
    sequential_thinking,
    think_tool,
    validate_quality,
)

__all__ = [
    "get_subagents",
    "run_summarizer_loop",
    "synthesize_repair_instructions",
    "write_critic_slices",
    "cleanup_critic_slices",
    "filter_hypothesis_evidence_files",
    "SUBAGENT_CONFIGS",
    "WORKFLOW_ORDER",
]


# Keys on each hypothesis dict that may carry a list of evidence file
# references. Different hypothesis_writer prompt revisions have used different
# names; the filter strips nonexistent entries from each.
_EVIDENCE_FILE_KEYS = ("evidence_files", "evidence_references")

# Matches a JSON filename that may be followed by the ``_FAILED`` upstream
# marker, possibly with surrounding bracket characters. Used to strip
# ``_FAILED`` suffixes from prose fields and remove bracket forms whose
# target file does not exist on disk.
_JSON_FAILED_SUFFIX_RE = re.compile(r"(\b[\w-]+\.json)_FAILED\b")

# Pattern that matches the first newline, carriage-return, or tab character.
# Everything from that character onward is truncated so injected text cannot
# masquerade as a new Markdown heading or instruction block inside a prompt.
_PROMPT_CONTROL_RE = re.compile(r"[\n\r\t].*", re.DOTALL)


def _sanitize_data_dir(value: str | None) -> str:
    """Truncate *value* at the first control character before prompt injection.

    Returns an empty string when *value* is ``None``.  Removes everything
    from the first ``\\n``, ``\\r``, or ``\\t`` onward to prevent prompt
    injection via newline splitting (CP-P2-002).
    """
    if value is None:
        return ""
    return _PROMPT_CONTROL_RE.sub("", value)


def _strip_failed_suffix_in_strings(node: object) -> tuple[object, int]:
    """Walk a JSON-decoded structure and replace ``<file>.json_FAILED`` with
    ``<file>.json`` in every string value. Returns the (possibly new) node and
    the number of replacements performed."""
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
    """Write a sanitized hypothesis_report copy for summarizer consumption.

    The hypothesis_writer subagent occasionally emits references to files it
    believes exist (e.g. ``known_drugs.json``) or files with the ``_FAILED``
    upstream marker. When SUMMARIZER / report_writer faithfully echoes these
    strings, the produced drug.md cites nonexistent files. Fixing this at the
    consumer (closer to disk) is more reliable than asking the LLM to
    self-check.

    Two passes:
      1. List-key pass — every list-shaped entry under any key in
         ``_EVIDENCE_FILE_KEYS`` is filtered: entries ending with ``_FAILED``
         and entries whose target path does not exist under
         ``<data_dir>/evidence/`` are dropped.
      2. Prose pass — every string value anywhere in the document has
         ``<file>.json_FAILED`` rewritten to ``<file>.json``. The
         ``_FAILED`` suffix is never valid in drug.md regardless of where it
         appears, and prose-embedded references have been observed to bypass
         the list-key filter when the LLM echoes them verbatim.

    Accepts both on-disk shapes:
      1. ``{"hypotheses": [{"evidence_files": [...]}, ...]}`` — current pipeline
      2. ``[{"evidence_files": [...]}, ...]`` — legacy/test fixtures

    The original ``hypothesis_report.json`` is never rewritten. When a mutation
    is needed this writes
    ``hypothesis_report.summarizer_sanitized.json`` beside the source.

    Args:
        data_dir: Run working directory (parent of ``evidence/``).

    Returns:
        Total number of mutations (list-entry drops + prose suffix strips).
    """
    evidence_dir = Path(data_dir) / "evidence"
    hyp_path = evidence_dir / "hypothesis_report.json"
    sanitized_path = evidence_dir / "hypothesis_report.summarizer_sanitized.json"
    if not evidence_dir.exists() or not hyp_path.exists():
        return 0

    try:
        data = json.loads(hyp_path.read_text())
    except Exception:
        return 0

    sanitized = copy.deepcopy(data)
    if isinstance(sanitized, dict):
        hyps = sanitized.get("hypotheses") or []
        container = sanitized
    elif isinstance(sanitized, list):
        hyps = sanitized
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

    # Pass 2: strip ``_FAILED`` suffixes from any string anywhere in the doc.
    # Operate on the container so the rewrite covers both shapes uniformly.
    target = container if container is not None else hyps
    rewritten, suffix_strips = _strip_failed_suffix_in_strings(target)
    total_mutations = dropped + suffix_strips

    if total_mutations:
        sanitized_path.write_text(json.dumps(rewritten, indent=2))
    elif sanitized_path.exists():
        sanitized_path.unlink()
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
            # sequential_thinking removed: this subagent is template-driven (fixed Phases 1→5);
            # planning tool induced infinite-loop stalls on small local LLMs (qwen3.5).
            # Reflection is still available via think_tool below.
            think_tool,
            validate_quality,
        ],
        "middleware": [
            ReadFileBlockMiddleware(),
        ],  # Block read_file, force load_evidence_files
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
            save_report_expansions,
            read_skill_file,
            think_tool,
        ],
    },
    "critic": {
        "name": "critic",
        "description": (
            "Read-only report auditor. Validates drug.md against local evidence, "
            "Reference Card values, deterministic validator outputs, and known "
            "hallucination failure modes. Returns structured audit findings and "
            "repair instructions; never writes artifacts."
        ),
        "system_prompt": SUBAGENT_PROMPTS["critic"],
        "tools": [
            load_lr_candidates,
            load_evidence_files,
            validate_evidence_completeness,
            validate_drug_md,
            validate_stage3_gate,
            read_skill_file,
            think_tool,
            validate_quality,
        ],
        "middleware": [
            ReadOnlyToolGuardMiddleware(
                blocked_tool_names=(
                    "save_drug_md",
                    "save_target_assessment",
                    "save_evidence",
                )
            )
        ],
    },
}


# =============================================================================
# Workflow Order
# =============================================================================

WORKFLOW_ORDER = ["evidence_assessor", "hypothesis_writer", "summarizer"]

_TOP_LEVEL_SIMPLE_SUBAGENTS = ["evidence_assessor", "hypothesis_writer"]
_SUMMARIZER_INNER_SUBAGENTS = ["report_writer", "critic"]

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

3. SUMMARIZER (CompiledSubAgent; write -> validate -> critic -> repair)
   - Delegates initial/fix writes to inner REPORT_WRITER
   - Runs deterministic validators (validate_drug_md, validate_quality)
   - Delegates independent evidence audit to read-only CRITIC
   - Loops back to REPORT_WRITER for bounded repairs
   - Fails closed when any validator or CRITIC gate remains failed
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
    skills_sources: list[str] | None = None,
    skill_registry: dict[str, str] | None = None,
    skills_dir: str | None = None,
    subagent_skill_names: dict[str, tuple[str, ...]] | None = None,
    subagent_skill_registries: dict[str, dict[str, str]] | None = None,
) -> list[dict]:
    """Get the subagent configurations for Drug Target Assessment.

    Returns 3 subagents in workflow order:
    1. evidence_assessor - 3-stage funnel with inline rubric assessment
       (Stage 2 -> Stage 1 -> Stage 3 ChEMBL inline)
    2. hypothesis_writer - hypothesis generation with UCB scoring
    3. summarizer - CompiledSubAgent report finalization audit loop

    Args:
        custom_tools: Optional list of additional tools to include in all subagents
        data_dir: Resolved data directory path to inject into subagent prompts
        disease: Disease context to inject into subagent prompts
        model_overrides: Optional per-subagent model overrides.
            Keys are subagent names, values are init_chat_model format strings
            (e.g. "openai:gpt-4.1") or BaseChatModel instances.
        default_model: Parent model to reuse for the summarizer CompiledSubAgent
            when no explicit summarizer override is configured.
        backend: Shared DeepAgents backend for summarizer and inner subagents.
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
        for name in _TOP_LEVEL_SIMPLE_SUBAGENTS
    ]
    summarizer_inner_subagents = [
        {**SUBAGENT_CONFIGS[name], "tools": list(SUBAGENT_CONFIGS[name]["tools"])}
        for name in _SUMMARIZER_INNER_SUBAGENTS
    ]
    configurable_subagents = [*subagents, *summarizer_inner_subagents]

    for subagent in configurable_subagents:
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
        for subagent in configurable_subagents:
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
        for subagent in configurable_subagents:
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
        safe_data_dir = _sanitize_data_dir(data_dir)
        data_dir_note = (
            f"\n\n## Data Directory\n"
            f"The data directory for this session is: `{safe_data_dir}`\n"
            f"Pass this exact path as `data_dir` to all tool calls "
            f"(load_lr_candidates, load_evidence_files, save_evidence).\n"
            f"{disease_line}"
        )
        for subagent in configurable_subagents:
            subagent["system_prompt"] = subagent["system_prompt"] + data_dir_note

    if custom_tools:
        # Keep the audited finalization surface stable: custom tools are added
        # only to directly exposed top-level dictionary subagents. The compiled
        # summarizer owns report finalization with a fixed writer/critic tool set.
        for subagent in subagents:
            current_tools = list(subagent.get("tools", []))
            current_tools.extend(custom_tools)
            subagent["tools"] = current_tools

    # Guard write_file tool calls against non-string content emitted by some models.
    for subagent in configurable_subagents:
        mw = list(subagent.get("middleware", []))
        mw.insert(0, WriteFileArgGuardMiddleware(backend_root=data_dir))
        subagent["middleware"] = mw

    # Primary subagents use allow-listed shared SkillsMiddleware + SkillActivator.
    # Do NOT set `subagent["skills"]` in this path; deepagents would auto-attach
    # its native SkillsMiddleware and defeat the allow-list.
    if skills_dir and subagent_skill_names and subagent_skill_registries:
        from src.agents.shared.skill_activator import SkillActivator
        from src.agents.shared.skills_middleware import SkillsMiddleware

        for subagent in configurable_subagents:
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
        _skill_subagents = {"evidence_assessor", "report_writer"}
        for subagent in configurable_subagents:
            if subagent["name"] in _skill_subagents:
                subagent["skills"] = skills_sources
                if skill_registry:
                    from src.agents.shared.skill_activator import SkillActivator
                    mw = list(subagent.get("middleware", []))
                    mw.append(SkillActivator(
                        skill_registry=skill_registry,
                    ))
                    subagent["middleware"] = mw

    summarizer_model = None
    if model_overrides:
        summarizer_model = model_overrides.get("summarizer")
    if summarizer_model is None:
        summarizer_model = default_model

    subagents.append(
        get_summarizer_subagent(
            model=summarizer_model,
            backend=None if data_dir is not None else backend,
            inner_subagents=summarizer_inner_subagents,
            data_dir=data_dir,
        )
    )

    return subagents


# =============================================================================
# T17: Pre-write critic slice files
# =============================================================================

def write_critic_slices(data_dir: str) -> None:
    """Write per-gene evidence slices for the critic before it runs.

    For each gene X found in evidence/stage3_<X>.json, writes:
      data_dir/evidence/_critic_slices/<X>.json

    Contents per gene slice:
    - Reference Card fields from resolved_drugs.json (entries referencing X)
    - stage3_<X>.json content
    - All stage1_*<X>*.json entries

    Also writes:
      data_dir/evidence/_critic_slices/_hypothesis.json
    containing hypothesis_report.json union with Reference Cards for all
    genes listed in hypothesis_report.json[*].entities.

    Cleanup: call cleanup_critic_slices(data_dir) at end of run
    unless OMB_CRITIC_SLICES_KEEP=1 is set.
    """
    evidence_dir = Path(data_dir) / "evidence"
    slices_dir = evidence_dir / "_critic_slices"
    slices_dir.mkdir(parents=True, exist_ok=True)

    # Load resolved_drugs for Reference Card fields
    resolved_drugs: list[dict] = []
    resolved_path = evidence_dir / "resolved_drugs.json"
    if resolved_path.exists():
        try:
            resolved_drugs = json.loads(resolved_path.read_text())
        except Exception:
            resolved_drugs = []

    # Collect all stage3 genes
    stage3_genes: dict[str, dict] = {}
    for stage3_file in evidence_dir.glob("stage3_*.json"):
        gene = stage3_file.stem[len("stage3_"):]
        try:
            stage3_genes[gene] = json.loads(stage3_file.read_text())
        except Exception:
            stage3_genes[gene] = {}

    # Write per-gene slices
    for gene, stage3_data in stage3_genes.items():
        # Reference Card entries referencing this gene
        ref_card_entries = [
            entry for entry in resolved_drugs
            if gene in json.dumps(entry)
        ]
        # stage1 files referencing this gene
        stage1_entries: list[dict] = []
        for stage1_file in evidence_dir.glob(f"stage1_*{gene}*.json"):
            try:
                stage1_entries.append({
                    "file": stage1_file.name,
                    "data": json.loads(stage1_file.read_text()),
                })
            except Exception:
                pass

        slice_payload = {
            "gene": gene,
            "reference_card": ref_card_entries,
            "stage3": stage3_data,
            "stage1": stage1_entries,
        }
        (slices_dir / f"{gene}.json").write_text(
            json.dumps(slice_payload, indent=2)
        )

    # Write hypothesis slice. The on-disk shape varies:
    #   1. {"hypotheses": [{"biological_entities": {"genes": [...]}, ...}, ...]}
    #      — current pipeline output (frozen baseline).
    #   2. [{"entities": [...]}, ...]
    #      — legacy/test-fixture shape preserved in unit tests.
    # Accept both.
    sanitized_hyp_path = evidence_dir / "hypothesis_report.summarizer_sanitized.json"
    hyp_path = sanitized_hyp_path if sanitized_hyp_path.exists() else evidence_dir / "hypothesis_report.json"
    hyp_raw: object = []
    if hyp_path.exists():
        try:
            hyp_raw = json.loads(hyp_path.read_text())
        except Exception:
            hyp_raw = []

    hypothesis_metadata: dict[str, object] = {}
    if isinstance(hyp_raw, dict):
        hyp_data = hyp_raw.get("hypotheses") or []
        hypothesis_metadata = {
            key: value
            for key, value in hyp_raw.items()
            if key != "hypotheses"
        }
    elif isinstance(hyp_raw, list):
        hyp_data = hyp_raw
    else:
        hyp_data = []

    hyp_genes: set[str] = set()
    for hyp in hyp_data:
        if not isinstance(hyp, dict):
            continue
        for entity in hyp.get("entities", []) or []:
            hyp_genes.add(str(entity))
        bio = hyp.get("biological_entities") or {}
        if isinstance(bio, dict):
            for entity in bio.get("genes", []) or []:
                hyp_genes.add(str(entity))

    hyp_ref_cards = [
        entry for entry in resolved_drugs
        if any(g in json.dumps(entry) for g in hyp_genes)
    ]
    hypothesis_slice = {
        "hypothesis_report": hyp_data,
        "hypothesis_metadata": hypothesis_metadata,
        "hypothesis_report_raw": hyp_raw,
        "genes": sorted(hyp_genes),
        "reference_cards": hyp_ref_cards,
    }
    (slices_dir / "_hypothesis.json").write_text(
        json.dumps(hypothesis_slice, indent=2)
    )


def cleanup_critic_slices(data_dir: str) -> None:
    """Remove _critic_slices directory unless OMB_CRITIC_SLICES_KEEP=1."""
    if os.environ.get("OMB_CRITIC_SLICES_KEEP") == "1":
        return
    slices_dir = Path(data_dir) / "evidence" / "_critic_slices"
    if slices_dir.exists():
        shutil.rmtree(slices_dir)


# =============================================================================
# Fix 3: Repair-instruction synthesis helper (dedup + Section-4 gate)
# =============================================================================

def synthesize_repair_instructions(claim_verdicts: list[dict]) -> list[str]:
    """Build a deduplicated repair instruction list from critic claim_verdicts.

    Applies two filters before generating instructions:
    1. Skip verdicts where ``verdict != "FAIL"``.
    2. Skip verdicts where ``section == "section_4"`` — Section 4 hypothesis
       prose originates from hypothesis_report.json and is not editable by
       report_writer; passing these causes an oscillation loop.
    3. Deduplicate on (claim_text, source_field) — case-insensitive. Many
       critic FAILs target the same source-field gap; one instruction per
       unique pair is sufficient.

    Args:
        claim_verdicts: List of critic claim verdict dicts. Each dict may have:
            - verdict: "FAIL" | "PASS" (required)
            - claim_text: the offending claim string
            - source_field: the missing source field name
            - section: optional section identifier (e.g. "section_4")

    Returns:
        Deduplicated list of repair instruction strings. Empty list means
        no actionable repairs — caller should NOT re-invoke report_writer.
    """
    seen: set[tuple[str, str]] = set()
    instructions: list[str] = []

    for entry in claim_verdicts:
        if not isinstance(entry, dict):
            continue
        if entry.get("verdict") != "FAIL":
            continue
        if entry.get("section") == "section_4":
            continue

        claim_text = str(entry.get("claim_text", "")).strip().lower()
        source_field = str(entry.get("source_field", "")).strip().lower()
        key = (claim_text, source_field)
        if key in seen:
            continue
        seen.add(key)

        raw_claim = str(entry.get("claim_text", "")).strip()
        raw_field = str(entry.get("source_field", "")).strip()
        instructions.append(
            f'Remove or rewrite claim "{raw_claim}" — no source for "{raw_field}".'
        )

    return instructions


# =============================================================================
# T16: Programmatic repair-loop counter
# =============================================================================

def run_summarizer_loop(
    data_dir: str,
    *,
    fake_validate_result: dict | None = None,
    fake_critic_output: dict | None = None,
    max_cycles: int = 2,
) -> dict:
    """Programmatic bounded repair loop for the summarizer orchestration.

    In production the summarizer DeepAgent calls validate_drug_md and the
    critic subagent directly (prompt-driven). This function encapsulates the
    counter logic so it can be unit-tested without a live LLM.

    In test mode, inject ``fake_validate_result`` and ``fake_critic_output``
    to simulate deterministic critic responses. In production these are None
    and the caller is responsible for driving the actual tool/subagent calls.

    Args:
        data_dir: Path to the run's evidence directory.
        fake_validate_result: Injected validate_drug_md result dict (tests only).
        fake_critic_output: Injected critic output dict (tests only).
        max_cycles: Maximum number of repair iterations before BLOCKED.

    Returns:
        dict with keys:
            - status: "PASS" | "BLOCKED"
            - repair_cycles: int (number of critic iterations executed)
            - blocker: list[dict] | None (P0 findings if BLOCKED, else None)
    """
    repair_cycles = 0
    last_critic_output: dict = {}

    for _ in range(max_cycles):
        # --- validate_drug_md ---
        validate_result = fake_validate_result or {}
        if validate_result.get("valid", True):
            return {"status": "PASS", "repair_cycles": repair_cycles, "blocker": None}

        # --- critic ---
        critic_output = fake_critic_output or {}
        last_critic_output = critic_output
        repair_cycles += 1

        if critic_output.get("passed", False):
            return {"status": "PASS", "repair_cycles": repair_cycles, "blocker": None}

    # Exhausted max_cycles — extract P0 findings for the blocker payload
    p0_findings = [
        f for f in last_critic_output.get("findings", [])
        if f.get("severity") == "P0"
    ]
    blocker = p0_findings if p0_findings else last_critic_output.get("findings", [])
    return {
        "status": "BLOCKED",
        "repair_cycles": repair_cycles,
        "blocker": blocker,
    }
