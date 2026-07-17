"""Drug Target Assessment Agent using DeepAgents framework.

Production is a guarded three-subagent workflow:
1. EVIDENCE_ASSESSOR: 3-stage funnel (Stage 2: validation & scoring ->
   Stage 1: biological context -> Stage 3: ChEMBL drug profiles).
2. HYPOTHESIS_WRITER: saves the canonical validated evidence handoff.
3. REPORT_WRITER: renders a guarded hybrid report from that handoff;
   DrugReportGuardrailMiddleware validates, repairs, publishes, and audits.

``legacy_hypothesis`` retains the hypothesis_writer plus deterministic
``finalize_report`` super-graph only for explicit compatibility callers.

All database queries are wrapped as @tool functions that run on the host process.
Docker backend is OPTIONAL — set docker_image in DrugTargetConfig to enable
container-level isolation for heavy-dependency tools (Census).

Input: lr_candidates.json (top-30 L-R pairs) + disease context
Output: drug.md (markdown for HTML report integration)
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypeAlias, cast

from deepagents import create_deep_agent
from langchain.agents import create_agent
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
from src.agents.deep_interpreter.middleware.think_tool_quality_gate import (
    ThinkToolQualityGateMiddleware,
)
from deepagents.backends import FilesystemBackend
from src.agents.drug_target.subagents.configs import get_legacy_subagents, get_subagents
from src.agents.drug_target.subagents.prompts import HypothesisWriterPromptMode
from src.agents.drug_target.guarded_pipeline import build_guarded_pipeline
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

SkillActivationMode = Literal[
    "middleware_only",
    "middleware_plus_activator",
    "middleware_plus_governor",
]
Provider: TypeAlias = Literal["openai", "google", "ollama", "ollama-openai", "vllm", "claude", "openrouter"]
WorkflowMode: TypeAlias = Literal["guarded_report", "legacy_hypothesis"]
_WORKFLOW_MODES = frozenset({"guarded_report", "legacy_hypothesis"})


def _validate_workflow_mode(value: str) -> WorkflowMode:
    """Return an accepted workflow mode or fail before selecting any surface."""
    if value not in _WORKFLOW_MODES:
        raise ValueError(
            "workflow_mode must be 'guarded_report' or 'legacy_hypothesis'; "
            f"got {value!r}"
        )
    return cast(WorkflowMode, value)


# =============================================================================
# Legacy Orchestrator System Prompt
# =============================================================================

LEGACY_ORCHESTRATOR_SYSTEM_PROMPT_TEMPLATE = """You are the legacy compatibility Drug Target Assessment orchestrator.
Data directory: {data_dir} | Disease: {disease}

## Steps (execute in exact order)
1. Call {load_lr_candidates_invocation}
2. Call task(subagent_type="evidence_assessor",
            instruction="Run Stage 1+2+3 for {disease}. Data dir: {data_dir}. <paste lr_candidates output>")
3. Call task(subagent_type="hypothesis_writer",
            instruction="Generate hypotheses from evidence. Data dir: {data_dir}")
4. Reply with the single line: EVIDENCE_PIPELINE_COMPLETE

## Rules
- Execute steps 1-4 in order. Do not skip, reorder, or repeat.
- Do not read files. Do not analyze evidence.
- After step 4, stop. Any additional tool call is a failure.
- Legacy report finalization (drug.md, HTML, target_assessment.json) is handled by
  the downstream legacy compatibility finalize_report node — do not attempt it.

## Input
- lr_candidates.json: top-30 L-R pairs (loaded in step 1)

## Output
- hypothesis_report.json, evidence/*.json (legacy finalize_report node writes drug.md + HTML)
"""


# Resume orchestrator prompt — skips load_lr_candidates + evidence_assessor.
# Activated when env var DRUG_TARGET_SKIP_EVIDENCE_ASSESSOR=1 (set by trace
# script --skip-evidence-assessor flag). Use ONLY when evidence/*.json files
# from a prior partial run are present on disk; the orchestrator does not
# verify integrity — the caller is responsible.
LEGACY_RESUME_ORCHESTRATOR_SYSTEM_PROMPT_TEMPLATE = """You are the legacy compatibility Drug Target Assessment orchestrator (RESUME mode).
Data directory: {data_dir} | Disease: {disease}

## Steps (execute in exact order)
1. Call task(subagent_type="hypothesis_writer",
            instruction="{hypothesis_writer_resume_instruction}")
2. Reply with the single line: EVIDENCE_PIPELINE_COMPLETE

## Rules
- Evidence files (evidence/*.json, assessment_results.json, stage*.json) are
  ASSUMED to exist on disk from a prior partial run. Do NOT re-run the
  evidence_assessor subagent.
- Execute steps 1-2 in order. Do not skip, reorder, or repeat.
- Do not read files. Do not analyze evidence.
- After step 2, stop. Any additional tool call is a failure.
- Legacy report finalization (drug.md, HTML, target_assessment.json) is handled by
  the downstream legacy compatibility finalize_report node — do not attempt it.

## Output
- hypothesis_report.json (legacy finalize_report node writes drug.md + HTML)
"""


@dataclass
class DrugTargetConfig:
    """Configuration for Drug Target Assessment Agent.

    Attributes:
        provider: LLM provider. Defaults to 'openrouter'.
        model: Optional explicit model selection. When omitted, the provider
            environment/default model selection remains unchanged.
        request_timeout_seconds: Optional LLM request timeout. When omitted,
            the provider environment/default timeout remains unchanged.
        data_dir: Directory containing lr_candidates.json and workspace.
        disease: Disease context for queries.
        use_checkpointer: Whether to use memory checkpointer (default: False).
        custom_tools: Additional tools to include.
        docker_image: Docker image for sandbox backend. None (default) disables
            Docker — all tools run on the host. Set to e.g. "python:3.12-slim"
            to enable container isolation for heavy-dependency tools.
        enable_progressive_disclosure: Whether to expose selected skills metadata
            to the agent and allow on-demand skill reading.
        enable_skill_activator: Whether to add SkillActivator after
            SkillsMiddleware. Set False for passive middleware-only activation
            benchmarks.
        skill_activation_mode: Optional explicit skill activation strategy.
            When omitted, derives from enable_skill_activator for backward
            compatibility.
        agent_skill_names: Legacy fallback skill tuple retained for registry helpers.
        evidence_assessor_skill_names: Skills exposed to evidence_assessor.
        hypothesis_writer_skill_names: Skills exposed to hypothesis_writer.
        hypothesis_writer_prompt_mode: Prompt mode for hypothesis_writer.
            ``default`` preserves legacy direct skill-read instructions;
            ``progressive_disclosure_only`` removes those prompt-level reads
            for pure progressive-disclosure benchmarks.
        skills_dir: Optional override for the project skills directory.
    """

    provider: Provider = "ollama"
    model: str | None = None
    request_timeout_seconds: float | None = None
    data_dir: str = field(
        default_factory=lambda: os.getenv(
            "DRUG_TARGET_DATA_DIR",
            os.getenv("DEEP_INTERPRETER_DATA_DIR", "/tmp/deep_interpreter_workspace"),
        )
    )
    disease: str = ""  # Currently passed via user message, not injected into agent
    workflow_mode: WorkflowMode = "guarded_report"
    use_checkpointer: bool = False
    custom_tools: Sequence[BaseTool] = field(default_factory=list)
    docker_image: str | None = None
    enable_census: bool = True
    enable_progressive_disclosure: bool = True
    enable_skill_activator: bool = True
    skill_activation_mode: SkillActivationMode | None = None
    agent_skill_names: tuple[str, ...] = (
        "drug-target-hypothesis",
        "drug-target-reporting",
        "opentargets-database",
        "gwas-database",
        "chembl-database",
    )
    evidence_assessor_skill_names: tuple[str, ...] = ()
    report_writer_skill_names: tuple[str, ...] = ("drug-target-reporting",)
    report_writer_resume_instruction: str | None = None
    hypothesis_writer_skill_names: tuple[str, ...] = (
        "drug-target-hypothesis",
        "opentargets-database",
        "gwas-database",
        "chembl-database",
    )
    hypothesis_writer_prompt_mode: HypothesisWriterPromptMode = "default"
    hypothesis_writer_resume_instruction: str | None = None
    skills_dir: str | None = None
    subagent_models: dict[str, BaseChatModel | str] | None = None
    # init_chat_model format per subagent, e.g.:
    # Legacy example: {"evidence_assessor": "openai:gpt-4.1", "hypothesis_writer": "openai:gpt-4.1-mini"}
    # If None, auto-loads from SUBAGENT_{NAME}_PROVIDER env vars.

    def __post_init__(self):
        self.workflow_mode = _validate_workflow_mode(self.workflow_mode)
        if self.workflow_mode == "guarded_report" and self.custom_tools:
            raise ValueError("custom_tools are not allowed in guarded_report mode")
        if self.subagent_models is None:
            if self.workflow_mode == "guarded_report":
                model_names = ["evidence_assessor", "hypothesis_writer", "report_writer"]
            elif self.workflow_mode == "legacy_hypothesis":
                model_names = ["evidence_assessor", "hypothesis_writer"]
            else:
                raise AssertionError(
                    f"validated workflow mode unexpectedly missing: {self.workflow_mode!r}"
                )
            self.subagent_models = cast(
                dict[str, BaseChatModel | str] | None,
                load_subagent_models_from_env(model_names),
            )
        if self.workflow_mode == "guarded_report" and (
            self.subagent_models and "report_writer" in self.subagent_models
        ):
            raise ValueError(
                "guarded_report does not support subagent_models['report_writer']; "
                "set DrugTargetConfig.model instead"
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

    if config.docker_image is None:
        raise ValueError("docker_image is required to create DockerBackend")

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


def _format_hypothesis_writer_resume_instruction(
    config: DrugTargetConfig,
    resolved_data_dir: str,
) -> str:
    instruction = (
        config.hypothesis_writer_resume_instruction
        or f"Generate hypotheses from evidence already on disk. Data dir: {resolved_data_dir}"
    )
    return " ".join(instruction.replace('"', "'").split())


def _format_report_writer_resume_instruction(
    config: DrugTargetConfig,
    resolved_data_dir: str,
) -> str:
    instruction = config.report_writer_resume_instruction or (
        "Render guarded hybrid report from existing evidence. "
        f"Data dir: {resolved_data_dir}"
    )
    return " ".join(instruction.replace('"', "'").split())


def _build_subagent_skill_name_map(
    config: DrugTargetConfig,
    *,
    enable_census: bool,
) -> dict[str, tuple[str, ...]]:
    """Return the per-subagent skill tuples for the primary workflow."""
    if config.workflow_mode == "legacy_hypothesis":
        return {
            "evidence_assessor": _filter_census_skills(
                config.evidence_assessor_skill_names,
                enable_census=enable_census,
            ),
            "hypothesis_writer": tuple(config.hypothesis_writer_skill_names),
        }
    if config.workflow_mode == "guarded_report":
        return {
            "evidence_assessor": _filter_census_skills(
                config.evidence_assessor_skill_names,
                enable_census=enable_census,
            ),
            "hypothesis_writer": tuple(config.hypothesis_writer_skill_names),
            "report_writer": tuple(config.report_writer_skill_names),
        }
    raise AssertionError(f"validated workflow mode unexpectedly missing: {config.workflow_mode!r}")


def create_guarded_report_writer(config: DrugTargetConfig) -> Runnable:
    """Compile the canonical guarded report-writer spec for diagnostics only."""
    if _validate_workflow_mode(config.workflow_mode) != "guarded_report":
        raise ValueError(
            "create_guarded_report_writer requires workflow_mode='guarded_report'"
        )

    resolved_data_dir = str(Path(config.data_dir).expanduser().resolve())
    llm_kwargs: dict[str, Any] = {"provider": config.provider}
    if config.model:
        llm_kwargs["model"] = config.model
    if config.request_timeout_seconds is not None:
        llm_kwargs["request_timeout"] = config.request_timeout_seconds
    llm = create_llm(**llm_kwargs)

    model_overrides = dict(config.subagent_models or {})
    if (
        config.model
        or config.request_timeout_seconds is not None
        or "report_writer" not in model_overrides
    ):
        model_overrides["report_writer"] = llm

    skill_activation_mode: SkillActivationMode = (
        config.skill_activation_mode
        if config.skill_activation_mode is not None
        else (
            "middleware_plus_activator"
            if config.enable_skill_activator
            else "middleware_only"
        )
    )
    resolved_skills_dir = str(_resolve_skills_dir(config))
    if config.docker_image:
        skills_dir = resolved_skills_dir
        subagent_skill_names = {
            "evidence_assessor": (),
            "hypothesis_writer": (),
            "report_writer": (),
        }
        subagent_skill_registries = None
    else:
        skills_dir = resolved_skills_dir if config.enable_progressive_disclosure else None
        subagent_skill_names = (
            _build_subagent_skill_name_map(config, enable_census=config.enable_census)
            if config.enable_progressive_disclosure
            else {
                "evidence_assessor": (),
                "hypothesis_writer": (),
                "report_writer": (),
            }
        )
        subagent_skill_registries = {
            name: _build_skill_registry(config, names)
            for name, names in subagent_skill_names.items()
        }

    report_writer_kwargs: dict[str, Any] = {
        "data_dir": resolved_data_dir,
        "disease": config.disease,
        "provider": config.provider,
        "model_overrides": model_overrides,
        "default_model": llm,
        "enable_census": config.enable_census,
        "skills_dir": skills_dir,
        "subagent_skill_names": subagent_skill_names,
        "subagent_skill_registries": subagent_skill_registries,
        "enable_skill_activator": config.enable_skill_activator,
        "skill_activation_mode": skill_activation_mode,
        "hypothesis_writer_prompt_mode": config.hypothesis_writer_prompt_mode,
    }
    if config.model:
        report_writer_kwargs["report_writer_model"] = config.model
    if config.request_timeout_seconds is not None:
        report_writer_kwargs["report_writer_request_timeout_seconds"] = (
            config.request_timeout_seconds
        )
    report_writers = [
        spec for spec in get_subagents(**report_writer_kwargs) if spec["name"] == "report_writer"
    ]
    if len(report_writers) != 1:
        raise ValueError("expected exactly one report_writer subagent spec")
    report_writer_spec = report_writers[0]
    return create_agent(
        model=report_writer_spec["model"],
        tools=report_writer_spec["tools"],
        system_prompt=report_writer_spec["system_prompt"],
        middleware=report_writer_spec["middleware"],
        name="report_writer",
    )


def create_drug_target_agent(
    config: DrugTargetConfig | None = None,
) -> tuple[Runnable, object | None]:
    """Create the Drug Target Assessment agent using DeepAgents framework.

    Creates a fully configured production agent with:
    - 3 top-level subagents (evidence_assessor, hypothesis_writer, report_writer)
    - All database queries via @tool wrappers (host-side by default)
    - Optional DockerBackend when docker_image is set in config
    - Report validation, repair, publication, and audits are handled by
      DrugReportGuardrailMiddleware after report_writer completes

    ``legacy_hypothesis`` explicitly retains its historical hypothesis_writer
    and finalize_report compatibility surface.

    Args:
        config: Optional configuration. Uses defaults if not provided.

    Returns:
        Tuple of (compiled agent runnable, backend or None).
        When backend is not None, callers must manage its lifecycle
        via try/finally or context manager (backend.cleanup()).
    """
    if config is None:
        config = DrugTargetConfig()

    workflow_mode = _validate_workflow_mode(config.workflow_mode)
    resolved_data_dir = str(Path(config.data_dir).expanduser().resolve())
    # data_dir is passed explicitly through config and injected into subagent prompts;
    # no os.environ mutation needed.

    # Ensure evidence directory exists
    evidence_dir = Path(resolved_data_dir) / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    # 1. Backend
    resolved_skills_dir = str(_resolve_skills_dir(config))
    if config.docker_image:
        backend = _create_docker_backend(config, resolved_data_dir)
        skills_dir = resolved_skills_dir
        if workflow_mode == "guarded_report":
            subagent_skill_names = {
                "evidence_assessor": (),
                "hypothesis_writer": (),
                "report_writer": (),
            }
        elif workflow_mode == "legacy_hypothesis":
            subagent_skill_names = {"evidence_assessor": (), "hypothesis_writer": ()}
        else:
            raise AssertionError(
                f"validated workflow mode unexpectedly missing: {workflow_mode!r}"
            )
        subagent_skill_registries = None
    else:
        backend = FilesystemBackend(root_dir=resolved_data_dir, virtual_mode=True)
        skills_dir = resolved_skills_dir if config.enable_progressive_disclosure else None
        subagent_skill_names = (
            _build_subagent_skill_name_map(config, enable_census=config.enable_census)
            if config.enable_progressive_disclosure
            else {
                "evidence_assessor": (),
                "hypothesis_writer": (),
                "report_writer": (),
            }
        )
        subagent_skill_registries = (
            {
                name: _build_skill_registry(config, names)
                for name, names in subagent_skill_names.items()
            }
            if subagent_skill_names is not None
            else None
        )

    # 2. Create the model used by guarded role specs and legacy orchestration.
    llm_kwargs: dict[str, Any] = {"provider": config.provider}
    if config.model:
        llm_kwargs["model"] = config.model
    if config.request_timeout_seconds is not None:
        llm_kwargs["request_timeout"] = config.request_timeout_seconds
    llm = create_llm(**llm_kwargs)
    skill_activation_mode: SkillActivationMode = (
        config.skill_activation_mode
        if config.skill_activation_mode is not None
        else (
            "middleware_plus_activator"
            if config.enable_skill_activator
            else "middleware_only"
        )
    )

    # 3. Get subagent specs — primary subagents use allow-listed shared
    #    SkillsMiddleware + activation middleware instead of deepagents native
    #    `subagent["skills"]` auto-loading.
    model_overrides = config.subagent_models
    if (config.model or config.request_timeout_seconds is not None) and workflow_mode == "guarded_report":
        model_overrides = {
            **(model_overrides or {}),
            "hypothesis_writer": llm,
            "report_writer": llm,
        }
    subagent_kwargs: dict[str, Any] = dict(
        data_dir=resolved_data_dir,
        disease=config.disease,
        model_overrides=model_overrides,
        default_model=llm,
        backend=backend,
        enable_census=config.enable_census,
        skills_dir=skills_dir,
        subagent_skill_names=subagent_skill_names,
        subagent_skill_registries=subagent_skill_registries,
        enable_skill_activator=config.enable_skill_activator,
        skill_activation_mode=skill_activation_mode,
    )
    if workflow_mode == "guarded_report":
        report_writer_kwargs: dict[str, Any] = {
            "provider": config.provider,
            "hypothesis_writer_prompt_mode": config.hypothesis_writer_prompt_mode,
            **subagent_kwargs,
        }
        if config.model:
            report_writer_kwargs["report_writer_model"] = config.model
        if config.request_timeout_seconds is not None:
            report_writer_kwargs["report_writer_request_timeout_seconds"] = (
                config.request_timeout_seconds
            )
        subagent_specs = get_subagents(**report_writer_kwargs)
        resume_mode = os.getenv(
            "DRUG_TARGET_SKIP_EVIDENCE_ASSESSOR", ""
        ).lower() in {"1", "true", "yes"}
        pipeline = build_guarded_pipeline(
            subagent_specs,
            data_dir=resolved_data_dir,
            default_model=llm,
            disease=config.disease.strip(),
            skip_evidence_assessor=resume_mode,
        )
        return pipeline, backend
    elif workflow_mode == "legacy_hypothesis":
        subagent_specs = get_legacy_subagents(
            custom_tools=config.custom_tools,
            hypothesis_writer_prompt_mode=config.hypothesis_writer_prompt_mode,
            **subagent_kwargs,
        )
    else:
        raise AssertionError(f"validated workflow mode unexpectedly missing: {workflow_mode!r}")

    # 4. Create the legacy Deep Agent — it only dispatches compatibility roles.
    checkpointer = MemorySaver() if config.use_checkpointer else None
    tools: list = [load_lr_candidates, read_skill_file]
    if config.custom_tools:
        tools.extend(config.custom_tools)

    # Render system prompt with config values so the LLM knows
    # data_dir / disease without parsing the user message.
    # Resume mode (DRUG_TARGET_SKIP_EVIDENCE_ASSESSOR=1) skips evidence_assessor
    # — used by trace script --skip-evidence-assessor for partial re-runs.
    resume_mode = os.getenv("DRUG_TARGET_SKIP_EVIDENCE_ASSESSOR", "").lower() in {"1", "true", "yes"}
    template = (
        LEGACY_RESUME_ORCHESTRATOR_SYSTEM_PROMPT_TEMPLATE
        if resume_mode
        else LEGACY_ORCHESTRATOR_SYSTEM_PROMPT_TEMPLATE
    )
    if resume_mode:
        logger.info("Orchestrator running in RESUME mode (evidence_assessor skipped).")
    safe_disease = config.disease.strip()
    invocation = f"load_lr_candidates(data_dir={json.dumps(resolved_data_dir)}"
    if safe_disease:
        invocation += f", disease={json.dumps(safe_disease)}"
    invocation += ")"
    system_prompt = template.format(
        data_dir=resolved_data_dir,
        disease=safe_disease or "the disease returned by load_lr_candidates",
        load_lr_candidates_invocation=invocation,
        hypothesis_writer_resume_instruction=(
            _format_hypothesis_writer_resume_instruction(config, resolved_data_dir)
        ),
        report_writer_resume_instruction=(
            _format_report_writer_resume_instruction(config, resolved_data_dir)
        ),
    )

    middleware = [
        WriteFileArgGuardMiddleware(backend_root=resolved_data_dir),
        ThinkToolQualityGateMiddleware(),
        ReadFileBlockMiddleware(),
        SubagentErrorGuardMiddleware(),
    ]
    create_kwargs: dict[str, Any] = dict(
        model=llm,
        tools=tools,
        subagents=subagent_specs,
        checkpointer=checkpointer,
        system_prompt=system_prompt,
        backend=backend,
        middleware=middleware,
    )

    agent = create_deep_agent(**create_kwargs)
    # evidence_assessor alone can consume 500-800 steps for large gene panels
    # (41 genes × ~10 steps/gene for Stage 2, plus Stage 1 batch + rubric + gates).
    # The guarded top-level subagents share this budget. Conservative estimate:
    #   evidence_assessor: ~1500, hypothesis_writer: ~300, report_writer: ~300,
    #   orchestrator: ~200 = ~2000 typical, 10000 for margin.
    # In guarded production, report middleware does not consume this agent's
    # recursion budget. The legacy finalize_report node is compatibility-only.
    agent = agent.with_config({"recursion_limit": 10000})

    return agent, backend


__all__ = [
    "create_drug_target_agent",
    "create_guarded_report_writer",
    "DrugTargetConfig",
    "Provider",
    "WorkflowMode",
]
