"""Drug Target Assessment Agent using DeepAgents framework.

3-Subagent Architecture:
1. EVIDENCE_COLLECTOR: Multi-database evidence gathering (OT, GWAS, ChEMBL, CT, FDA)
2. CLINICAL_ASSESSOR: Rubric-based scoring with LLM-evaluated criteria
3. REPORT_WRITER: Generate drug.md with featured candidate emphasis

This module follows the same patterns as src/agents/deep_interpreter/agent.py:
- OverwriteFilesystemBackend for re-run support
- CompositeBackend with FilesystemBackend for persistent file storage
- SkillsMiddleware for Progressive Disclosure of drug-target skill strategies
- Pre-written data_path.txt for deterministic subagent behavior

Input: lr_candidates.json (top-15 L-R pairs) + selected_top3_lr.json + disease context
Output: drug.md (markdown for HTML report integration)
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional, Sequence

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend
from deepagents.backends.protocol import WriteResult
from langchain.tools import ToolRuntime
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import MemorySaver

from src.agents.model import create_llm
from src.agents.deep_interpreter.middleware import SkillsMiddleware
from src.agents.drug_target.subagents.configs import get_subagents
from src.agents.drug_target.tools import (
    load_lr_candidates,
    load_evidence_files,
    save_evidence,
    sequential_thinking,
    think_tool,
    validate_quality,
)


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


# =============================================================================
# Orchestrator System Prompt
# =============================================================================

ORCHESTRATOR_SYSTEM_PROMPT = """You are the Drug Target Assessment orchestrator.

Your task is to coordinate 3 specialized subagents to produce a comprehensive
therapeutic target assessment report (drug.md).

## CRITICAL: First Action
You MUST call the `load_lr_candidates` tool with the data_dir from the user message
as your VERY FIRST action. This loads lr_candidates.json and selected_top3_lr.json,
extracts gene symbols, and returns structured data. Do NOT use `ls` or `read_file`
to check the directory — always use `load_lr_candidates`.

## Workflow
Execute subagents strictly in this order via the `task` tool:

1. **evidence_collector**: Pass the load_lr_candidates output. It gathers evidence
   from OpenTargets, GWAS, ChEMBL, ClinicalTrials.gov, FDA for each gene.
2. **clinical_assessor**: Scores each target against the DRUG_TARGET_RUBRIC.
3. **report_writer**: Generates drug.md with ★ Featured Candidate emphasis.
   The report_writer MUST call `write_file` to save drug.md to the data directory.

## Input
- lr_candidates.json: Top-15 L-R pairs from CCI analysis
- selected_top3_lr.json: Top-3 L-R pairs selected for detailed analysis
- Disease context provided in initial message

## Output
- drug.md: Publication-quality therapeutic target assessment report
- evidence/*.json: Intermediate evidence files

## Rules
- ALWAYS start with `load_lr_candidates` — never skip this step
- Execute subagents in ORDER: evidence_collector → clinical_assessor → report_writer
- Each subagent uses Plan→Execute→Reflect cycle
- selected_top3_lr genes are [FEATURED] Featured Candidates throughout
- The final drug.md must be self-contained markdown for HTML report integration
"""


@dataclass
class DrugTargetConfig:
    """Configuration for Drug Target Assessment Agent.

    Attributes:
        provider: LLM provider. Defaults to 'openrouter'.
        data_dir: Directory containing lr_candidates.json and workspace
        disease: Disease context for queries
        max_iterations: Maximum quality refinement iterations (default: 2)
        quality_threshold: Minimum quality score to pass (default: 0.7)
        use_checkpointer: Whether to use memory checkpointer (default: False)
        virtual_mode: If True, file paths sandboxed to data_dir
        max_file_size_mb: Maximum file size for filesystem backend
        custom_tools: Additional tools to include
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


def _create_backend_factory(
    config: DrugTargetConfig,
) -> tuple[callable, FilesystemBackend]:
    """Create backend factory for Drug Target Agent.

    Creates a CompositeBackend factory that:
    - Uses StateBackend for in-memory state management
    - Routes file operations to FilesystemBackend based on config.data_dir

    Returns:
        Tuple of (backend_factory function, fs_backend instance)
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


def create_drug_target_agent(
    config: Optional[DrugTargetConfig] = None,
) -> Runnable:
    """Create the Drug Target Assessment agent using DeepAgents framework.

    Creates a fully configured agent with:
    - 3 specialized subagents (evidence_collector, clinical_assessor, report_writer)
    - OverwriteFilesystemBackend for persistent file storage
    - SkillsMiddleware for drug-target skill strategy injection
    - Pre-written data_path.txt for deterministic path resolution

    Args:
        config: Optional configuration. Uses defaults if not provided.

    Returns:
        Compiled Deep Agent runnable
    """
    if config is None:
        config = DrugTargetConfig()

    # Set data_dir in env for tool fallback
    os.environ["DEEP_INTERPRETER_DATA_DIR"] = str(
        Path(config.data_dir).expanduser().resolve()
    )

    # Create LLM
    llm = create_llm(provider=config.provider)

    # Create backend factory
    backend_factory, _fs_backend = _create_backend_factory(config)

    # Pre-write /data_path.txt deterministically
    resolved_data_dir = str(Path(config.data_dir).expanduser().resolve())
    _fs_backend.write("/data_path.txt", resolved_data_dir)

    # Pre-register input files with backend so virtual filesystem ls() sees them
    for fname in ("lr_candidates.json", "selected_top3_lr.json"):
        fpath = Path(resolved_data_dir) / fname
        if fpath.exists():
            _fs_backend.write(f"/{fname}", fpath.read_text())

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

    # Get 3-subagent configuration (inject data_dir so subagents know the path)
    subagents = get_subagents(
        custom_tools=config.custom_tools,
        data_dir=resolved_data_dir,
    )

    # Configure checkpointer
    checkpointer = MemorySaver() if config.use_checkpointer else None

    # SkillsMiddleware for drug-target relevant skills
    # Injects skill metadata (opentargets, gwas, chembl, clinicaltrials, fda, drugbank, clinvar)
    # into system prompts for Progressive Disclosure
    skills_middleware = SkillsMiddleware()

    # Create the agent
    agent = create_deep_agent(
        model=llm,
        tools=tools,
        subagents=subagents,
        checkpointer=checkpointer,
        interrupt_on={},
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        backend=backend_factory,
        middleware=[skills_middleware],
    )

    return agent


def create_drug_target_graph() -> Runnable:
    """Create Drug Target graph for LangGraph deployment.

    Returns:
        Compiled Deep Agent graph
    """
    config = DrugTargetConfig()
    return create_drug_target_agent(config)


__all__ = [
    "create_drug_target_agent",
    "create_drug_target_graph",
    "DrugTargetConfig",
]
