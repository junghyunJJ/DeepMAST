"""Drug Target Assessment Agent using DeepAgents framework.

2-Subagent Architecture with 4-Stage Funnel:
1. EVIDENCE_ASSESSOR: 4-stage funnel (biological context -> validation & scoring ->
   deep dive -> structural druggability) with inline rubric assessment
2. REPORT_WRITER: Generate drug.md with featured candidate emphasis

This module uses a split orchestration model:
- Orchestrator: CompositeBackend(State + Filesystem), no execute privileges
- Subagents: Per-subagent local execute backend + per-subagent skills sources
- OverwriteFilesystemBackend for re-run support
- Pre-written data_path.txt for deterministic subagent behavior

Input: lr_candidates.json (top-15 L-R pairs) + selected_top3_lr.json + disease context
Output: drug.md (markdown for HTML report integration)
"""

import os
import shlex
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend
from deepagents.backends.protocol import ExecuteResponse, SandboxBackendProtocol, WriteResult
from langchain.tools import ToolRuntime
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import MemorySaver

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


class OverwriteFilesystemBackend(FilesystemBackend):
    """FilesystemBackend that overwrites existing files on write().

    The base FilesystemBackend.write() rejects existing files (create-only).
    This subclass deletes the existing file and retries, enabling overwrites
    during re-runs, retries, and quality iteration loops.
    """

    def write(self, file_path: str, content: str) -> WriteResult:
        resolved_path = self._resolve_path(file_path)
        if resolved_path.exists():
            resolved_path.unlink()
        return super().write(file_path, content)


class GuardedLocalExecBackend(FilesystemBackend, SandboxBackendProtocol):
    """Local non-isolated execute backend with lightweight command guardrails."""

    ALLOWED_PREFIXES = {"python", "python3", "uv", "pip", "pip3"}
    BLOCKED_TOKENS = {"&&", "||", ";", "|", "`", "$()"}

    def __init__(
        self,
        root_dir: str | Path,
        *,
        virtual_mode: bool,
        max_file_size_mb: int,
        timeout_sec: int,
        work_dir: str,
        env_file: str | Path | None,
    ) -> None:
        super().__init__(
            root_dir=root_dir,
            virtual_mode=virtual_mode,
            max_file_size_mb=max_file_size_mb,
        )
        self.timeout_sec = timeout_sec
        self.work_dir = work_dir
        self.exec_cwd = self._resolve_path(work_dir)
        self.exec_cwd.mkdir(parents=True, exist_ok=True)
        self.exec_env = self._build_exec_env(env_file)
        self._backend_id = f"guarded-local-exec:{self.cwd}:{work_dir}"

    @property
    def id(self) -> str:
        return self._backend_id

    def _build_exec_env(self, env_file: str | Path | None) -> dict[str, str]:
        safe_env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
        }

        if env_file is None:
            return safe_env

        env_path = Path(env_file)
        if not env_path.is_absolute():
            env_path = self.cwd / env_path

        if not env_path.exists():
            return safe_env

        forbidden_markers = ("KEY", "TOKEN", "SECRET", "PASSWORD")
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")

            upper_key = key.upper()
            if any(marker in upper_key for marker in forbidden_markers):
                raise ValueError(
                    f"Forbidden secret-like key in {env_path}: {key}. Use non-secret env only."
                )

            safe_env[key] = value

        return safe_env

    def _validate_command(self, command: str) -> tuple[bool, str]:
        text = command.strip()
        if not text:
            return False, "Empty command"

        for token in self.BLOCKED_TOKENS:
            if token in text:
                return False, f"Blocked token detected: {token}"

        try:
            parts = shlex.split(text)
        except ValueError as exc:
            return False, f"Invalid command parsing: {exc}"

        if not parts:
            return False, "Command parse result is empty"

        if parts[0] not in self.ALLOWED_PREFIXES:
            allowed = ", ".join(sorted(self.ALLOWED_PREFIXES))
            return False, f"Command prefix '{parts[0]}' is not allowed. Allowed: {allowed}"

        return True, ""

    def execute(self, command: str) -> ExecuteResponse:
        ok, reason = self._validate_command(command)
        if not ok:
            return ExecuteResponse(
                output=f"Blocked command: {reason}",
                exit_code=126,
                truncated=False,
            )

        args = shlex.split(command)

        try:
            completed = subprocess.run(
                args,
                shell=False,
                cwd=str(self.exec_cwd),
                env=self.exec_env,
                capture_output=True,
                text=True,
                timeout=self.timeout_sec,
            )
            output = (completed.stdout or "") + (completed.stderr or "")
            truncated = False
            if len(output) > 16_000:
                output = output[:16_000] + "\n...[truncated]"
                truncated = True

            return ExecuteResponse(
                output=output,
                exit_code=completed.returncode,
                truncated=truncated,
            )
        except subprocess.TimeoutExpired:
            return ExecuteResponse(
                output=f"Command timed out after {self.timeout_sec}s",
                exit_code=124,
                truncated=False,
            )


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
        virtual_mode: If True, file paths are sandboxed to data_dir.
        max_file_size_mb: Maximum file size for filesystem backend.
        custom_tools: Additional tools to include.
        exec_timeout_sec: Timeout for subagent local execute commands.
        exec_env_file: Optional env file for execute environment.
        subagent_skillsets: Optional per-subagent skill-name overrides.
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
    virtual_mode: bool = False
    max_file_size_mb: int = 20
    custom_tools: Sequence[BaseTool] = field(default_factory=list)
    exec_timeout_sec: int = 90
    exec_env_file: str | None = ".env.code_runner.local"
    subagent_skillsets: Mapping[str, Sequence[str]] | None = None


def _create_backend_factory(
    config: DrugTargetConfig,
) -> tuple[callable, FilesystemBackend]:
    """Create backend factory for the orchestrator agent.

    The orchestrator uses StateBackend as default and routes file operations to
    FilesystemBackend rooted at config.data_dir. It does not receive execute rights.
    """
    fs_backend = OverwriteFilesystemBackend(
        root_dir=config.data_dir,
        virtual_mode=config.virtual_mode,
        max_file_size_mb=config.max_file_size_mb,
    )

    def backend_factory(rt: ToolRuntime) -> CompositeBackend:
        return CompositeBackend(
            default=StateBackend(rt),
            routes={"/": fs_backend},
        )

    return backend_factory, fs_backend


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


def _prepare_subagent_skill_sources(
    *,
    resolved_data_dir: str,
    skillsets: Mapping[str, Sequence[str]],
) -> dict[str, str]:
    """Materialize per-subagent skill source directories under data_dir.

    DeepAgents `skills=` expects source directories containing one or more skill
    subdirectories. This helper copies selected project skills into:
    - {data_dir}/.skillsets/<subagent>/<skill>/SKILL.md
    and returns virtual source paths (e.g., '/.skillsets/evidence_assessor/').
    """
    project_skills_dir = _find_project_root() / "skills"
    source_map: dict[str, str] = {}

    for subagent_name, skill_names in skillsets.items():
        if not skill_names:
            continue

        source_root = Path(resolved_data_dir) / ".skillsets" / subagent_name
        source_root.mkdir(parents=True, exist_ok=True)

        keep = set(skill_names)
        for child in list(source_root.iterdir()):  # materialize before mutation
            if child.is_dir() and child.name not in keep:
                shutil.rmtree(child)

        for skill_name in skill_names:
            if Path(skill_name).parts != (skill_name,):
                raise ValueError(
                    f"Invalid skill name for {subagent_name}: {skill_name!r}. "
                    "Must be a plain directory name without path separators."
                )
            src = project_skills_dir / skill_name
            if not src.exists():
                raise FileNotFoundError(
                    f"Skill directory not found for {subagent_name}: {src}"
                )
            dst = source_root / skill_name
            shutil.copytree(src, dst, dirs_exist_ok=True)

        source_map[subagent_name] = f"/.skillsets/{subagent_name}/"

    return source_map


def _build_compiled_subagents(
    *,
    llm,
    config: DrugTargetConfig,
    subagent_specs: list[dict],
    resolved_data_dir: str,
) -> list[dict[str, object]]:
    """Build runnable subagents with per-subagent execute backend and skills."""
    skill_sources = _prepare_subagent_skill_sources(
        resolved_data_dir=resolved_data_dir,
        skillsets=_resolve_skillsets(config),
    )

    compiled_subagents: list[dict[str, object]] = []
    env_file = config.exec_env_file
    if env_file and not Path(env_file).is_absolute():
        env_file = str((_find_project_root() / env_file).resolve())

    for subagent in subagent_specs:
        name = subagent["name"]
        backend = GuardedLocalExecBackend(
            root_dir=resolved_data_dir,
            virtual_mode=True,
            max_file_size_mb=config.max_file_size_mb,
            timeout_sec=config.exec_timeout_sec,
            work_dir=f".exec/{name}",
            env_file=env_file,
        )

        create_kwargs = {
            "model": llm,
            "tools": subagent["tools"],
            "system_prompt": subagent["system_prompt"],
            "backend": backend,
        }

        source = skill_sources.get(name)
        if source:
            create_kwargs["skills"] = [source]

        runnable = create_deep_agent(**create_kwargs)
        compiled_subagents.append(
            {
                "name": name,
                "description": subagent["description"],
                "runnable": runnable,
            }
        )

    return compiled_subagents


def create_drug_target_agent(
    config: Optional[DrugTargetConfig] = None,
) -> Runnable:
    """Create the Drug Target Assessment agent using DeepAgents framework.

    Creates a fully configured agent with:
    - 2 specialized compiled subagents (each with local execute backend)
    - Per-subagent skill sources (distinct sets per role)
    - Orchestrator-level CompositeBackend for persistent file storage
    - Pre-written data_path.txt for deterministic path resolution

    Args:
        config: Optional configuration. Uses defaults if not provided.

    Returns:
        Compiled Deep Agent runnable.
    """
    if config is None:
        config = DrugTargetConfig()

    # Set data_dir in env for tool fallback
    os.environ["DEEP_INTERPRETER_DATA_DIR"] = str(
        Path(config.data_dir).expanduser().resolve()
    )

    # Create LLM
    llm = create_llm(provider=config.provider)

    # Create orchestrator backend factory
    backend_factory, _fs_backend = _create_backend_factory(config)

    # Pre-write /data_path.txt deterministically
    resolved_data_dir = str(Path(config.data_dir).expanduser().resolve())
    _fs_backend.write("data_path.txt", resolved_data_dir)

    # Pre-register input files with backend so virtual filesystem ls() sees them
    for fname in ("lr_candidates.json", "selected_top3_lr.json"):
        fpath = Path(resolved_data_dir) / fname
        if fpath.exists():
            _fs_backend.write(fname, fpath.read_text())

    # Ensure evidence directory exists
    evidence_dir = Path(resolved_data_dir) / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    # Build orchestrator-level tools
    tools = [
        load_lr_candidates,
        load_evidence_files,
        save_evidence,
        sequential_thinking,
        think_tool,
        validate_quality,
    ]

    if config.custom_tools:
        tools.extend(config.custom_tools)

    # Get base 2-subagent specs (inject data_dir so subagents know the path)
    subagent_specs = get_subagents(
        custom_tools=config.custom_tools,
        data_dir=resolved_data_dir,
    )

    # Compile each subagent with dedicated backend + skills set
    compiled_subagents = _build_compiled_subagents(
        llm=llm,
        config=config,
        subagent_specs=subagent_specs,
        resolved_data_dir=resolved_data_dir,
    )

    # Configure checkpointer
    checkpointer = MemorySaver() if config.use_checkpointer else None

    # Create orchestrator agent
    agent = create_deep_agent(
        model=llm,
        tools=tools,
        subagents=compiled_subagents,
        checkpointer=checkpointer,
        interrupt_on={},
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        backend=backend_factory,
    )

    return agent


def create_drug_target_graph() -> Runnable:
    """Create Drug Target graph for LangGraph deployment.

    Returns:
        Compiled Deep Agent graph.
    """
    config = DrugTargetConfig()
    return create_drug_target_agent(config)


__all__ = [
    "create_drug_target_agent",
    "create_drug_target_graph",
    "DrugTargetConfig",
]
