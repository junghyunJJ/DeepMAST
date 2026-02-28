"""Drug Target Assessment Agent using DeepAgents framework.

2-Subagent Architecture with 4-Stage Funnel:
1. EVIDENCE_ASSESSOR: 4-stage funnel (biological context -> validation & scoring ->
   deep dive -> structural druggability) with inline rubric assessment
2. REPORT_WRITER: Generate drug.md with featured candidate emphasis

This module uses a single shared DockerBackend for orchestrator + all subagents:
- Docker container with dual mounts: host data_dir (rw) + project skills/ (ro)
- Per-subagent skill filtering via in-container symlink directories
- SubAgent dicts (not pre-compiled) — framework auto-wires middleware
- Pre-written data_path.txt for deterministic subagent behavior

Input: lr_candidates.json (top-15 L-R pairs) + selected_top3_lr.json + disease context
Output: drug.md (markdown for HTML report integration)
"""

import os
import shlex
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from deepagents import create_deep_agent
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import MemorySaver

from src.agents.drug_target.docker_backend import DockerBackend
from src.agents.model import create_llm
from src.agents.drug_target.subagents.configs import get_subagents
from src.agents.drug_target.tools import (
    load_evidence_files,
    load_lr_candidates,
    save_evidence,
    sequential_thinking,
    think_tool,
    validate_quality,
)

DEFAULT_SUBAGENT_SKILLSETS: dict[str, list[str]] = {
    "evidence_assessor": [
        "opentargets-database",
        "gwas-database",
        "cellxgene-census",
        "kegg-database",
        "reactome-database",
        "string-database",
        "drugbank-database",
        "chembl-database",
        "pubmed-database",
        "alphafold-database",
        "compare-census-gene-pair-by-cell-type",
    ],
    "report_writer": [],
}


# =============================================================================
# Orchestrator System Prompt
# =============================================================================

ORCHESTRATOR_SYSTEM_PROMPT = """You are the Drug Target Assessment orchestrator.

Your task is to coordinate 2 specialized subagents to produce a comprehensive
therapeutic target assessment report (drug.md) using a 4-stage funnel approach.

## CRITICAL: First Action
You MUST call the `load_lr_candidates` tool with the data_dir from the user message
as your VERY FIRST action. This loads lr_candidates.json and selected_top3_lr.json,
extracts gene symbols, and returns structured data. Do NOT use `ls` or `read_file`
to check the directory -- always use `load_lr_candidates`.

## Workflow
Execute subagents strictly in this order via the `task` tool:

1. **evidence_assessor**: Pass the load_lr_candidates output. Runs the 4-stage funnel:
   - Stage 1 (ALL pairs): Biological context (Cellxgene, KEGG/Reactome, STRING, Census)
   - Stage 2 (ALL pairs): Validation & scoring (OpenTargets, VEP, GWAS) + inline rubric
   - Stage 3 (FEATURED only): Deep dive (DrugBank, PubMed)
   - Stage 4 (FEATURED only): Structural druggability (AlphaFold, DiffDock)
2. **report_writer**: Generates drug.md with [FEATURED] Candidate emphasis.
   The report_writer MUST first save target_assessment.json via
   `save_target_assessment`, then call `write_file` to save drug.md.

## Input
- lr_candidates.json: Top-15 L-R pairs from CCI analysis
- selected_top3_lr.json: Top-3 L-R pairs selected for detailed analysis
- Disease context provided in initial message

## Output
- target_assessment.json: Structured contract output (schema-aligned)
- drug.md: Publication-quality therapeutic target assessment report
- evidence/*.json: Intermediate evidence files

## Rules
- ALWAYS start with `load_lr_candidates` -- never skip this step
- Execute subagents in ORDER: evidence_assessor -> report_writer
- Each subagent uses Plan->Execute->Reflect cycle
- selected_top3_lr genes are [FEATURED] Featured Candidates throughout
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
        subagent_skillsets: Optional per-subagent skill-name overrides.
        docker_image: Docker image for the sandbox container.
    """

    provider: Literal["openai", "google", "ollama", "claude", "openrouter"] = "openrouter"
    data_dir: str = field(
        default_factory=lambda: os.getenv(
            "DEEP_INTERPRETER_DATA_DIR", "/tmp/deep_interpreter_workspace"
        )
    )
    disease: str = ""
    max_iterations: int = 2
    quality_threshold: float = 0.7
    use_checkpointer: bool = False
    custom_tools: Sequence[BaseTool] = field(default_factory=list)
    subagent_skillsets: Mapping[str, Sequence[str]] | None = None
    docker_image: str = "python:3.12-slim"


def _find_project_root() -> Path:
    """Find project root by searching parent directories for pyproject.toml or .git."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            return parent
    return current.parents[3]


def _resolve_skillsets(config: DrugTargetConfig) -> dict[str, list[str]]:
    """Resolve per-subagent skillsets from defaults + optional config overrides."""
    resolved = {k: list(v) for k, v in DEFAULT_SUBAGENT_SKILLSETS.items()}
    if config.subagent_skillsets:
        for subagent_name, skill_names in config.subagent_skillsets.items():
            resolved[subagent_name] = [str(skill_name) for skill_name in skill_names]
    return resolved


def _setup_filtered_skills(
    backend: DockerBackend,
    skillsets: dict[str, list[str]],
) -> None:
    """Create per-subagent filtered skill directories via symlinks inside container.

    SkillsMiddleware expects a source directory containing skill subdirectories
    (each with SKILL.md). This creates /filtered_skills/<subagent>/ with symlinks
    pointing to the read-only /skills/ mount.
    """
    for subagent_name, skill_names in skillsets.items():
        if not skill_names:
            continue
        backend.execute(f"mkdir -p /filtered_skills/{shlex.quote(subagent_name)}")
        for skill in skill_names:
            backend.execute(
                f"ln -sf /skills/{shlex.quote(skill)} "
                f"/filtered_skills/{shlex.quote(subagent_name)}/{shlex.quote(skill)}"
            )


def _build_subagent_dicts(
    subagent_specs: list[dict],
    skillsets: dict[str, list[str]],
) -> list[dict]:
    """Convert subagent specs to SubAgent dicts with container skill paths.

    Returns SubAgent dicts (not CompiledSubAgent) so the framework's
    create_deep_agent() auto-wires middleware including SkillsMiddleware.
    """
    result: list[dict] = []
    for spec in subagent_specs:
        name = spec["name"]
        entry: dict = {
            "name": name,
            "description": spec["description"],
            "system_prompt": spec["system_prompt"],
            "tools": spec["tools"],
        }
        if skillsets.get(name):
            entry["skills"] = [f"/filtered_skills/{name}/"]
        result.append(entry)
    return result


def create_drug_target_agent(
    config: DrugTargetConfig | None = None,
) -> tuple[Runnable, DockerBackend]:
    """Create the Drug Target Assessment agent using DeepAgents framework.

    Creates a fully configured agent with:
    - Single shared DockerBackend (container with dual volume mounts)
    - 2 specialized subagents as SubAgent dicts (framework auto-wires middleware)
    - Per-subagent skill filtering via in-container symlink directories
    - Pre-written data_path.txt for deterministic path resolution

    Args:
        config: Optional configuration. Uses defaults if not provided.

    Returns:
        Tuple of (compiled agent runnable, DockerBackend instance).
        Callers must manage backend lifecycle via try/finally or context manager.
    """
    if config is None:
        config = DrugTargetConfig()

    resolved_data_dir = str(Path(config.data_dir).expanduser().resolve())
    os.environ["DEEP_INTERPRETER_DATA_DIR"] = resolved_data_dir

    skills_dir = str(_find_project_root() / "skills")

    # Ensure evidence directory exists on host before mounting
    evidence_dir = Path(resolved_data_dir) / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    # 1. Create DockerBackend with dual mounts
    backend = DockerBackend(
        image_name=config.docker_image,
        host_dir=resolved_data_dir,
        container_dir="/workspace",
        skills_dir=skills_dir,
    )

    # 2. Create per-subagent filtered skill directories (symlinks inside container)
    skillsets = _resolve_skillsets(config)
    _setup_filtered_skills(backend, skillsets)

    # 3. Pre-write data_path.txt inside container
    backend.write("/workspace/data_path.txt", resolved_data_dir)

    # 4. Build orchestrator-level tools (these run host-side, not in Docker)
    tools: list = [
        load_lr_candidates,
        load_evidence_files,
        save_evidence,
        sequential_thinking,
        think_tool,
        validate_quality,
    ]
    if config.custom_tools:
        tools.extend(config.custom_tools)

    # 5. Get subagent specs + convert to SubAgent dicts with skills
    subagent_specs = get_subagents(
        custom_tools=config.custom_tools,
        data_dir=resolved_data_dir,
    )
    subagents = _build_subagent_dicts(subagent_specs, skillsets)

    # 6. Create agent
    llm = create_llm(provider=config.provider)
    checkpointer = MemorySaver() if config.use_checkpointer else None

    agent = create_deep_agent(
        model=llm,
        tools=tools,
        subagents=subagents,
        checkpointer=checkpointer,
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        backend=backend,
    )

    return agent, backend


def create_drug_target_graph() -> Runnable:
    """Create Drug Target graph for LangGraph deployment.

    Returns:
        Compiled Deep Agent graph.
    """
    import atexit

    agent, backend = create_drug_target_agent(DrugTargetConfig())
    atexit.register(backend.cleanup)
    return agent


__all__ = [
    "create_drug_target_agent",
    "create_drug_target_graph",
    "DrugTargetConfig",
]
