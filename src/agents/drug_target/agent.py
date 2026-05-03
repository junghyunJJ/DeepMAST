"""Drug Target Assessment Agent using DeepAgents framework.

3-Subagent Architecture with Audited Finalization:
1. EVIDENCE_ASSESSOR: 2-stage funnel (Stage 2: validation & scoring ->
   Stage 1: biological context) with inline rubric assessment
2. HYPOTHESIS_WRITER: Hypothesis generation with UCB scoring from all evidence
3. SUMMARIZER: CompiledSubAgent that runs report_writer -> validators ->
   critic -> bounded repair loop before final status

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
from langchain_core.language_models.chat_models import BaseChatModel
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
Data directory: {data_dir} | Disease: {disease}

## Steps (execute in exact order)
1. Call load_lr_candidates(data_dir="{data_dir}", disease="{disease}")
2. Call task(subagent_type="evidence_assessor",
            instruction="Run Stage 1+2+3 for {disease}. Data dir: {data_dir}. <paste lr_candidates output>")
3. Call task(subagent_type="hypothesis_writer",
            instruction="Generate hypotheses from evidence. Data dir: {data_dir}")
4. Call task(subagent_type="summarizer",
            instruction="Finalize drug.md and target_assessment.json with write -> validate -> critic -> repair loop. Data dir: {data_dir}")
5. If summarizer returns "SUMMARIZER_STATUS: PASS", reply "Pipeline complete." with zero tool calls.
   If summarizer returns "SUMMARIZER_STATUS: FAIL", reply "Pipeline incomplete: report remains draft." and include the summarizer's remaining gate failures.

## Rules
- Execute steps 1-5 in order. Do not skip, reorder, or repeat.
- Do not read files. Do not analyze evidence.
- Only summarize the summarizer return when it reports SUMMARIZER_STATUS: FAIL;
  include gate failures verbatim so the caller knows the report is incomplete.
- Completion is fail-closed: never claim success unless summarizer explicitly reports SUMMARIZER_STATUS: PASS.
- After step 5, stop. Any additional tool call is a failure.

## Input
- lr_candidates.json: top-30 L-R pairs (loaded in step 1)

## Output
- drug.md, target_assessment.json, hypothesis_report.json, evidence/*.json
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
        agent_skill_names: Legacy fallback skill tuple retained for registry helpers.
        evidence_assessor_skill_names: Skills exposed to evidence_assessor.
        hypothesis_writer_skill_names: Skills exposed to hypothesis_writer.
        report_writer_skill_names: Skills exposed to inner report_writer.
        skills_dir: Optional override for the project skills directory.
    """

    provider: Literal["openai", "google", "ollama", "ollama-openai", "claude", "openrouter"] = "ollama"
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
        "drug-target-hypothesis",
        "drug-target-reporting",
        "opentargets-database",
        "gwas-database",
        "chembl-database",
    )
    evidence_assessor_skill_names: tuple[str, ...] = ()
    hypothesis_writer_skill_names: tuple[str, ...] = (
        "drug-target-hypothesis",
        "opentargets-database",
        "gwas-database",
        "chembl-database",
    )
    report_writer_skill_names: tuple[str, ...] = (
        "drug-target-reporting",
        "opentargets-database",
        "gwas-database",
        "chembl-database",
    )
    skills_dir: str | None = None
    subagent_models: dict[str, BaseChatModel | str] | None = None
    # init_chat_model format per subagent, e.g.:
    # {"evidence_assessor": "openai:gpt-4.1", "report_writer": "openai:gpt-4.1-mini"}
    # If None, auto-loads from SUBAGENT_{NAME}_PROVIDER env vars.

    def __post_init__(self):
        if self.subagent_models is None:
            self.subagent_models = load_subagent_models_from_env(
                [
                    "evidence_assessor",
                    "hypothesis_writer",
                    "summarizer",
                    "report_writer",
                    "critic",
                ]
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


def _build_skill_registry(
    config: DrugTargetConfig,
    skill_names: Sequence[str] | None = None,
) -> dict[str, str]:
    """Build a skill registry dict from the provided skill names."""
    skills_dir = _resolve_skills_dir(config)
    return {
        name: str(skills_dir / name)
        for name in (skill_names or config.agent_skill_names)
    }


def _filter_census_skills(
    skill_names: Sequence[str],
    *,
    enable_census: bool,
) -> tuple[str, ...]:
    """Drop census-specific skills when Census tooling is disabled."""
    if enable_census:
        return tuple(skill_names)
    disabled = {"cellxgene-census", "compare-census-gene-pair-by-cell-type"}
    return tuple(name for name in skill_names if name not in disabled)


def _build_subagent_skill_name_map(
    config: DrugTargetConfig,
    *,
    enable_census: bool,
) -> dict[str, tuple[str, ...]]:
    """Return the per-subagent skill tuples for the primary workflow."""
    return {
        "evidence_assessor": _filter_census_skills(
            config.evidence_assessor_skill_names,
            enable_census=enable_census,
        ),
        "hypothesis_writer": tuple(config.hypothesis_writer_skill_names),
        "report_writer": tuple(config.report_writer_skill_names),
    }


def create_drug_target_agent(
    config: DrugTargetConfig | None = None,
) -> tuple[Runnable, object | None]:
    """Create the Drug Target Assessment agent using DeepAgents framework.

    Creates a fully configured agent with:
    - 3 top-level subagents (evidence_assessor, hypothesis_writer, summarizer)
    - summarizer is a CompiledSubAgent with inner report_writer + critic
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
    if config.docker_image:
        backend = _create_docker_backend(config, resolved_data_dir)
        skills_dir = None
        subagent_skill_names = None
        subagent_skill_registries = None
    else:
        backend = FilesystemBackend(root_dir=resolved_data_dir, virtual_mode=True)
        skills_dir = str(_resolve_skills_dir(config)) if config.enable_progressive_disclosure else None
        subagent_skill_names = (
            _build_subagent_skill_name_map(config, enable_census=config.enable_census)
            if config.enable_progressive_disclosure
            else None
        )
        subagent_skill_registries = (
            {
                name: _build_skill_registry(config, names)
                for name, names in subagent_skill_names.items()
            }
            if subagent_skill_names is not None
            else None
        )

    # 2. Build orchestrator-level tools — orchestrator only dispatches;
    # all cognitive/IO tools live in subagents.
    tools: list = [
        load_lr_candidates,
        read_skill_file,
    ]
    if config.custom_tools:
        tools.extend(config.custom_tools)

    # 3. Create the orchestrator LLM before subagents so the summarizer
    #    CompiledSubAgent can share the parent model by default.
    llm = create_llm(provider=config.provider)

    # 4. Get subagent specs — primary subagents use allow-listed shared
    #    SkillsMiddleware + SkillActivator instead of deepagents native
    #    `subagent["skills"]` auto-loading.
    subagent_specs = get_subagents(
        custom_tools=config.custom_tools,
        data_dir=resolved_data_dir,
        disease=config.disease,
        model_overrides=config.subagent_models,
        default_model=llm,
        backend=backend,
        enable_census=config.enable_census,
        skills_dir=skills_dir,
        subagent_skill_names=subagent_skill_names,
        subagent_skill_registries=subagent_skill_registries,
    )

    # 5. Create agent — orchestrator has NO skills (just delegates)
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
    # All 3 top-level subagents share this budget. Conservative estimate:
    #   evidence_assessor: ~1500, hypothesis_writer: ~300,
    #   summarizer/report loop: ~1200, orchestrator: ~200 = ~3200 typical,
    #   10000 for margin.
    agent = agent.with_config({"recursion_limit": 10000})

    return agent, backend


__all__ = [
    "create_drug_target_agent",
    "DrugTargetConfig",
]
