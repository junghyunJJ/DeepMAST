"""Drug Target Assessment Agent using DeepAgents framework.

4-Subagent Architecture with Staged Funnel:
1. EVIDENCE_ASSESSOR: 2-stage funnel (Stage 2: validation & scoring ->
   Stage 1: biological context) with inline rubric assessment
2. DEEP_DIVER: Stage 3 deep dive (ChEMBL) for FEATURED genes
3. HYPOTHESIS_WRITER: Hypothesis generation with UCB scoring from all evidence
4. REPORT_WRITER: Generate drug.md with featured candidate emphasis

All database queries are wrapped as @tool functions that run on the host process.
Docker backend is OPTIONAL — set docker_image in DrugTargetConfig to enable
container-level isolation for heavy-dependency tools (Census).

Input: lr_candidates.json (top-30 L-R pairs) + disease context
Output: drug.md (markdown for HTML report integration)
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from deepagents import create_deep_agent
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import MemorySaver

from src.agents.model import create_llm, load_subagent_models_from_env
from src.agents.deep_interpreter.middleware.write_file_guard import (
    WriteFileArgGuardMiddleware,
    ReadFileBlockMiddleware,
    SubagentErrorGuardMiddleware,
)
from deepagents.backends import FilesystemBackend
from src.agents.drug_target.subagents.configs import get_subagents
from src.agents.drug_target.tools import (
    check_stage1_completion,
    check_hypothesis_completion,
    load_evidence_files,
    load_lr_candidates,
    read_skill_file,
    save_evidence,
    sequential_thinking,
    think_tool,
    validate_quality,
)

logger = logging.getLogger(__name__)

# =============================================================================
# Orchestrator System Prompt
# =============================================================================

ORCHESTRATOR_SYSTEM_PROMPT_TEMPLATE = """You are the Drug Target Assessment orchestrator.

Your task is to coordinate 4 specialized subagents to produce a comprehensive
therapeutic target assessment report (drug.md) using a staged funnel approach.

## Pre-configured Context
- **Data directory**: `{data_dir}`
- **Disease context**: `{disease}`

These values are injected from configuration. Use them directly — do NOT
attempt to parse or extract data_dir or disease from the user message.

## CRITICAL: First Action
You MUST call `load_lr_candidates(data_dir="{data_dir}", disease="{disease}")` as your VERY FIRST
action. This loads lr_candidates.json, extracts gene symbols, and returns
structured data. Do NOT use `ls` or `read_file` to check the directory.

## Workflow
Execute subagents strictly in this order via the `task` tool:

1. **evidence_assessor**: Pass the load_lr_candidates output. Runs the 2-stage funnel:
   - Stage 2 (ALL unique genes): batch validation & scoring (OpenTargets, GWAS, VEP) + rubric scoring
   - Gene selection: combined_total >= 10 → FEATURED genes → map to L-R pairs
   - Stage 1 (FEATURED pairs only): Biological context (Cellxgene, KEGG/Reactome, STRING, Census)
   - Stage 1 gate validation
   Gate: After completion, verify `assessment_results.json` exists with `stage3_candidates`.

2. **deep_diver**: Stage 3 deep dive for FEATURED genes.
   - Queries ChEMBL for drug profiles
   - Produces `stage3_{{GENE}}.json` per gene (resumes from prior runs automatically)
   Gate: `validate_stage3_gate` must return success before completing.
   **ZERO-CANDIDATE SHORT-CIRCUIT**: If `stage3_candidates` in `assessment_results.json`
   is empty, SKIP deep_diver AND hypothesis_writer — go directly to report_writer.

3. **hypothesis_writer**: Reads all Stage 1-3 evidence files.
   - Generates 4-6 mechanistic hypotheses with UCB scoring
   - Outputs `hypothesis_report.json`
   Gate: `hypothesis_report.json` must exist after completion.

4. **report_writer**: Generates the final report.
   - Saves `target_assessment.json` via `save_target_assessment`
   - Saves `drug.md` via `save_drug_md`
   - Integrates hypothesis analysis if `hypothesis_report.json` exists

CRITICAL: After load_lr_candidates returns, you MUST immediately call the `task` tool
to delegate to evidence_assessor. Do NOT call load_lr_candidates again. Do NOT stop.
Example: task(subagent_type="evidence_assessor", instruction="Run the full 2-stage
evidence assessment for {disease}. Data dir: {data_dir}. <paste lr_candidates output>")

## Post-evidence_assessor Gate (MANDATORY)
After evidence_assessor returns (whether success or error), you MUST:
1. Call `check_stage1_completion(data_dir="{data_dir}")`
2. If `stage1_complete=true` AND `stage3_candidates_count > 0`: proceed to deep_diver
3. If `stage1_complete=true` AND `stage3_candidates_count == 0`: SKIP deep_diver + hypothesis_writer, go to report_writer
4. If `stage1_complete=false`: LOG the warning, proceed to deep_diver anyway (partial results > none)

## Post-hypothesis_writer Gate (MANDATORY)
After hypothesis_writer returns, you MUST:
1. Call `check_hypothesis_completion(data_dir="{data_dir}")`
2. If `hypothesis_complete=true`: proceed to report_writer with hypothesis data
3. If `hypothesis_complete=false`: proceed to report_writer anyway (report will note missing hypotheses)

You MUST NOT terminate until ALL required subagents have completed.

## ============================================================
## MANDATORY EXECUTION PROTOCOL (READ THIS BEFORE EVERY ACTION)
## ============================================================
You MUST execute subagents using the `task` tool in this EXACT order:
  1. task(subagent_type="evidence_assessor", ...) → Stage 1+2
  2. check_stage1_completion(data_dir)             → Gate check (MANDATORY)
  3. task(subagent_type="deep_diver", ...)         → Stage 3
  4. task(subagent_type="hypothesis_writer", ...)   → Hypothesis generation
  5. check_hypothesis_completion(data_dir)          → Gate check (MANDATORY)
  6. task(subagent_type="report_writer", ...)       → Final report
  7. STOP — emit ONE final assistant message "Pipeline complete." with ZERO tool calls.

ABSOLUTE RULES — VIOLATION OF ANY RULE IS A CRITICAL FAILURE:
- After evidence_assessor returns, you MUST call check_stage1_completion BEFORE deep_diver.
- After check_stage1_completion, IMMEDIATELY call the NEXT task(). No exceptions.
- NEVER use read_file to read evidence files — subagents handle their own I/O.
- NEVER try to write drug.md yourself — the report_writer subagent does this.
- NEVER use ls, read_file, or write_file between subagent calls.
- Do NOT summarize or analyze subagent results — just pass them to the next subagent.
- Do NOT stop until all required task() calls have been made and returned.
- After report_writer returns successfully, you MUST stop (see TERMINATION below).
- Your ONLY tools are: load_lr_candidates (once), check_stage1_completion (once, after evidence_assessor), check_hypothesis_completion (once, after hypothesis_writer), and task (3-4 times, in order).
## ============================================================

## ============================================================
## TERMINATION (MANDATORY — READ BEFORE EVERY ACTION)
## ============================================================
After report_writer returns successfully (target_assessment.json and drug.md saved),
your job is DONE. Your next response MUST be a single assistant message containing
the exact text `Pipeline complete.` and ZERO tool calls.

Specifically, after a successful report_writer completion you MUST NOT:
  - re-read any file
  - re-call load_lr_candidates
  - re-call check_stage1_completion or check_hypothesis_completion
  - re-call task() for any subagent (including report_writer itself)
  - summarize, reflect on, or validate evidence
  - emit ANY tool call whatsoever

Emitting any tool call after a successful report_writer completion is a CRITICAL
FAILURE — the pipeline is over. The correct and only acceptable final action is
a plain assistant message "Pipeline complete." with no tool_calls.
## ============================================================

## Input
- lr_candidates.json: Top-30 L-R pairs from CCI analysis
- Disease context: {disease}

## Output
- target_assessment.json: Structured contract output (schema-aligned)
- drug.md: Publication-quality therapeutic target assessment report
- hypothesis_report.json: Ranked mechanistic hypotheses with UCB scores
- evidence/*.json: Intermediate evidence files

## Rules
- ALWAYS start with `load_lr_candidates` -- never skip this step
- After load_lr_candidates, IMMEDIATELY call `task` for evidence_assessor -- do NOT stop
- Execute subagents in ORDER: evidence_assessor -> deep_diver -> hypothesis_writer -> report_writer
- Zero-candidate short-circuit: skip deep_diver + hypothesis_writer if no stage3_candidates
- Each subagent uses Plan->Execute->Reflect cycle
- [FEATURED] candidates are determined by rubric scoring (combined_total)
- The final drug.md must be self-contained markdown for HTML report integration
- NEVER use read_file, write_file, or ls — delegate ALL file I/O to subagents via task()
"""


@dataclass
class DrugTargetConfig:
    """Configuration for Drug Target Assessment Agent.

    Attributes:
        provider: LLM provider. Defaults to 'openrouter'.
        data_dir: Directory containing lr_candidates.json and workspace.
        disease: Disease context for queries.
        max_iterations: Maximum quality refinement iterations (default: 2).
        quality_threshold: Minimum quality score to pass (default: 0.7).
        use_checkpointer: Whether to use memory checkpointer (default: False).
        custom_tools: Additional tools to include.
        docker_image: Docker image for sandbox backend. None (default) disables
            Docker — all tools run on the host. Set to e.g. "python:3.12-slim"
            to enable container isolation for heavy-dependency tools.
        enable_progressive_disclosure: Whether to expose selected skills metadata
            to the agent and allow on-demand skill reading.
        agent_skill_names: Agent-facing skills to expose via progressive disclosure.
        skills_dir: Optional override for the project skills directory.
    """

    provider: Literal["openai", "google", "ollama", "claude", "openrouter"] = "ollama"
    data_dir: str = field(
        default_factory=lambda: os.getenv(
            "DRUG_TARGET_DATA_DIR",
            os.getenv("DEEP_INTERPRETER_DATA_DIR", "/tmp/deep_interpreter_workspace"),
        )
    )
    disease: str = ""  # Currently passed via user message, not injected into agent
    use_checkpointer: bool = False
    custom_tools: Sequence[BaseTool] = field(default_factory=list)
    docker_image: str | None = None
    enable_census: bool = True
    enable_progressive_disclosure: bool = True
    agent_skill_names: tuple[str, ...] = (
        "opentargets-database",
        "gwas-database",
        "chembl-database",
        "kegg-database",
        "string-database",
        "drug-target-reporting",
    )
    skills_dir: str | None = None
    subagent_models: dict[str, str] | None = None
    # init_chat_model format per subagent, e.g.:
    # {"evidence_assessor": "openai:gpt-4.1", "report_writer": "openai:gpt-4.1-mini"}
    # If None, auto-loads from SUBAGENT_{NAME}_PROVIDER env vars.

    def __post_init__(self):
        if self.subagent_models is None:
            self.subagent_models = load_subagent_models_from_env(
                ["evidence_assessor", "deep_diver", "hypothesis_writer", "report_writer"]
            )


def _create_docker_backend(
    config: DrugTargetConfig,
    resolved_data_dir: str,
):
    """Create DockerBackend when docker_image is configured.

    Returns:
        DockerBackend instance, or None if import fails.
    """
    from src.agents.drug_target.docker_backend import DockerBackend

    skills_dir = str(_resolve_skills_dir(config))
    backend = DockerBackend(
        image_name=config.docker_image,
        host_dir=resolved_data_dir,
        container_dir="/workspace",
        skills_dir=skills_dir,
    )
    logger.info("DockerBackend enabled (image=%s)", config.docker_image)
    return backend


def _resolve_skills_dir(config: DrugTargetConfig) -> Path:
    """Resolve the project skills directory."""
    if config.skills_dir:
        return Path(config.skills_dir).expanduser().resolve()
    return _find_project_root() / "skills"


def _find_project_root() -> Path:
    """Find project root — delegates to shared utility."""
    from src.agents.shared.utils import find_project_root
    return find_project_root()


def _build_skill_registry(config: DrugTargetConfig) -> dict[str, str]:
    """Build skill registry dict from config's allowed skill names."""
    skills_dir = _resolve_skills_dir(config)
    return {
        name: str(skills_dir / name)
        for name in config.agent_skill_names
    }


def create_drug_target_agent(
    config: DrugTargetConfig | None = None,
) -> tuple[Runnable, object | None]:
    """Create the Drug Target Assessment agent using DeepAgents framework.

    Creates a fully configured agent with:
    - 4 specialized subagents (evidence_assessor, deep_diver, hypothesis_writer, report_writer)
    - All database queries via @tool wrappers (host-side by default)
    - Optional DockerBackend when docker_image is set in config

    Args:
        config: Optional configuration. Uses defaults if not provided.

    Returns:
        Tuple of (compiled agent runnable, backend or None).
        When backend is not None, callers must manage its lifecycle
        via try/finally or context manager (backend.cleanup()).
    """
    if config is None:
        config = DrugTargetConfig()

    resolved_data_dir = str(Path(config.data_dir).expanduser().resolve())
    # data_dir is passed explicitly through config and injected into subagent prompts;
    # no os.environ mutation needed.

    # Ensure evidence directory exists
    evidence_dir = Path(resolved_data_dir) / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    # 1. Backend
    project_root = _find_project_root()

    if config.docker_image:
        backend = _create_docker_backend(config, resolved_data_dir)
        skills_sources = None
    else:
        backend = FilesystemBackend(root_dir=resolved_data_dir, virtual_mode=True)
        skills_sources = (
            [str(_resolve_skills_dir(config)) + "/"]
            if config.enable_progressive_disclosure
            else None
        )

    # 2. Build orchestrator-level tools
    tools: list = [
        load_lr_candidates,
        load_evidence_files,
        check_stage1_completion,
        check_hypothesis_completion,
        read_skill_file,
        save_evidence,
        sequential_thinking,
        think_tool,
        validate_quality,
    ]
    if config.custom_tools:
        tools.extend(config.custom_tools)

    # 3. Get subagent specs (skills go to evidence_assessor + deep_diver)
    subagent_specs = get_subagents(
        custom_tools=config.custom_tools,
        data_dir=resolved_data_dir,
        disease=config.disease,
        model_overrides=config.subagent_models,
        enable_census=config.enable_census,
        skills_sources=skills_sources,
        skill_registry=(
            _build_skill_registry(config)
            if config.enable_progressive_disclosure
            else None
        ),
    )

    # 4. Create agent — orchestrator has NO skills (just delegates)
    llm = create_llm(provider=config.provider)
    checkpointer = MemorySaver() if config.use_checkpointer else None

    # Render system prompt with config values so the LLM knows
    # data_dir / disease without parsing the user message.
    system_prompt = ORCHESTRATOR_SYSTEM_PROMPT_TEMPLATE.format(
        data_dir=resolved_data_dir,
        disease=config.disease or "(see lr_candidates.json)",
    )

    create_kwargs = dict(
        model=llm,
        tools=tools,
        subagents=subagent_specs,
        checkpointer=checkpointer,
        system_prompt=system_prompt,
        backend=backend,
        middleware=[
            WriteFileArgGuardMiddleware(),
            ReadFileBlockMiddleware(),        # Fix 2: block read_file at orchestrator level
            SubagentErrorGuardMiddleware(),   # Fix 4: catch GraphRecursionError from subagents
        ],
    )

    agent = create_deep_agent(**create_kwargs)
    # evidence_assessor alone can consume 500-800 steps for large gene panels
    # (41 genes × ~10 steps/gene for Stage 2, plus Stage 1 batch + rubric + gates).
    # All 4 subagents share this budget. Conservative estimate:
    #   evidence_assessor: ~1500, deep_diver: ~500, hypothesis_writer: ~300,
    #   report_writer: ~500, orchestrator: ~200 = ~3000 typical, 10000 for margin.
    agent = agent.with_config({"recursion_limit": 10000})

    return agent, backend


__all__ = [
    "create_drug_target_agent",
    "DrugTargetConfig",
]
