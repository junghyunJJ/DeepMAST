"""Drug Target Assessment Agent using DeepAgents framework.

2-Subagent Architecture with 3-Stage Funnel:
1. EVIDENCE_ASSESSOR: 3-stage funnel (biological context -> validation & scoring ->
   deep dive) with inline rubric assessment
2. REPORT_WRITER: Generate drug.md with featured candidate emphasis

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
from src.agents.deep_interpreter.middleware.write_file_guard import WriteFileArgGuardMiddleware
from deepagents.backends import FilesystemBackend
from src.agents.shared.skill_load_harness import SkillLoadHarness
from src.agents.drug_target.subagents.configs import get_subagents
from src.agents.drug_target.tools import (
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

Your task is to coordinate 2 specialized subagents to produce a comprehensive
therapeutic target assessment report (drug.md) using a 3-stage funnel approach.

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

1. **evidence_assessor**: Pass the load_lr_candidates output. Runs the 3-stage funnel:
   - Stage 1 (ALL pairs): Biological context (Cellxgene, KEGG/Reactome, STRING, Census)
   - Stage 2 (ALL unique genes): batch validation & scoring (OpenTargets, GWAS, VEP) + inline rubric
   - Stage 3 (FEATURED only): Deep dive (ChEMBL, PubMed)
2. **report_writer**: Generates drug.md with [FEATURED] Candidate emphasis.
   The report_writer MUST first save target_assessment.json via
   `save_target_assessment`, then call `save_drug_md` to save drug.md.

CRITICAL: After load_lr_candidates returns, you MUST immediately call the `task` tool
to delegate to evidence_assessor. Do NOT call load_lr_candidates again. Do NOT stop.
Example: task(subagent_type="evidence_assessor", instruction="Run the full 3-stage
evidence assessment for {disease}. Data dir: {data_dir}. <paste lr_candidates output>")

After evidence_assessor completes, IMMEDIATELY call:
task(subagent_type="report_writer", instruction="Generate drug.md report. Data dir: {data_dir}.")

You MUST NOT terminate until BOTH subagents have completed.

## Input
- lr_candidates.json: Top-30 L-R pairs from CCI analysis
- Disease context: {disease}

## Output
- target_assessment.json: Structured contract output (schema-aligned)
- drug.md: Publication-quality therapeutic target assessment report
- evidence/*.json: Intermediate evidence files

## Rules
- ALWAYS start with `load_lr_candidates` -- never skip this step
- After load_lr_candidates, IMMEDIATELY call `task` for evidence_assessor -- do NOT stop
- Execute subagents in ORDER: evidence_assessor -> report_writer
- Each subagent uses Plan->Execute->Reflect cycle
- [FEATURED] candidates are determined by rubric scoring (combined_total)
- The final drug.md must be self-contained markdown for HTML report integration
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

    provider: Literal["openai", "google", "ollama", "claude", "openrouter"] = "openrouter"
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
    enable_progressive_disclosure: bool = True
    agent_skill_names: tuple[str, ...] = (
        "opentargets-database",
        "gwas-database",
        "chembl-database",
        # kegg-database: REMOVED — tool-only, accessed via query_kegg_pathways
        # string-database: REMOVED — tool-only, accessed via query_string_ppi_pair
    )
    skills_dir: str | None = None
    stage_hints: dict[str, str] = field(
        default_factory=lambda: {
            "chembl-database": "Stage 3 only",
        }
    )
    subagent_models: dict[str, str] | None = None
    # init_chat_model format per subagent, e.g.:
    # {"evidence_assessor": "openai:gpt-4.1", "report_writer": "openai:gpt-4.1-mini"}
    # If None, auto-loads from SUBAGENT_{NAME}_PROVIDER env vars.

    def __post_init__(self):
        if self.subagent_models is None:
            self.subagent_models = load_subagent_models_from_env(
                ["evidence_assessor", "report_writer"]
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
    """Find project root by searching parent directories for pyproject.toml or .git."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            return parent
    raise FileNotFoundError(
        f"Could not find project root from {current}. "
        "Ensure pyproject.toml or .git exists in a parent directory."
    )


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
    - 2 specialized subagents (evidence_assessor, report_writer)
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
        backend = FilesystemBackend(root_dir=project_root, virtual_mode=True)
        skills_sources = (
            [str(_resolve_skills_dir(config)) + "/"]
            if config.enable_progressive_disclosure
            else None
        )

    # 2. Build orchestrator-level tools
    tools: list = [
        load_lr_candidates,
        load_evidence_files,
        read_skill_file,
        save_evidence,
        sequential_thinking,
        think_tool,
        validate_quality,
    ]
    if config.custom_tools:
        tools.extend(config.custom_tools)

    # 3. Get subagent specs (skills go to evidence_assessor only)
    subagent_specs = get_subagents(
        custom_tools=config.custom_tools,
        data_dir=resolved_data_dir,
        disease=config.disease,
        model_overrides=config.subagent_models,
        skills_sources=skills_sources,
        skill_registry=(
            _build_skill_registry(config)
            if config.enable_progressive_disclosure
            else None
        ),
        stage_hints=(
            config.stage_hints
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
        middleware=[WriteFileArgGuardMiddleware()],
    )

    agent = create_deep_agent(**create_kwargs)

    return agent, backend


def create_drug_target_graph() -> Runnable:
    """Create Drug Target graph for LangGraph deployment.

    Returns:
        Compiled Deep Agent graph.
    """
    agent, backend = create_drug_target_agent(DrugTargetConfig())
    if backend:
        import atexit
        atexit.register(backend.cleanup)
    return agent


__all__ = [
    "create_drug_target_agent",
    "create_drug_target_graph",
    "DrugTargetConfig",
]
