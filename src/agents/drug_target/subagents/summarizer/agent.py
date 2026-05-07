"""Summarizer CompiledSubAgent for audited drug target report finalization."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Sequence
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from deepagents.backends.protocol import BackendFactory, BackendProtocol
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool

from src.agents.drug_target.subagents.summarizer.fs_backend import (
    LoggingAndFallbackFilesystemBackend,
)

_lifecycle_logger = logging.getLogger("drug_target.lifecycle")


def _emit_lifecycle(phase: str, data_dir: str) -> None:
    """Emit one structured lifecycle event (CP-P1-003 compliant)."""
    _lifecycle_logger.info(
        json.dumps(
            {
                "event": "critic_slice_lifecycle",
                "phase": phase,
                "data_dir": data_dir,
                "timestamp": time.time(),
            }
        )
    )

from src.agents.deep_interpreter.middleware.write_file_guard import (
    ReadOnlyToolGuardMiddleware,
)
from src.agents.drug_target.subagents.summarizer.middleware import (
    AnnotationDensityMiddleware,
    BuildEvidenceSummaryGuardMiddleware,
    FrozenTemplateSpanMiddleware,
    RepairCycleCounterMiddleware,
    SummarizerFinalizationGuardMiddleware,
)
from src.agents.drug_target.subagents.prompts import SUMMARIZER_PROMPT
from src.agents.drug_target.tools import (
    think_tool,
    validate_drug_md,
    validate_drug_report_finalization,
    validate_quality,
    validate_stage3_gate,
)

_SUMMARIZER_BLOCKED_TOOLS = (
    "save_drug_md",
    "save_target_assessment",
    "save_evidence",
)


def _build_disk_backend(data_dir: str) -> FilesystemBackend:
    """Build a LoggingAndFallbackFilesystemBackend rooted at data_dir with virtual path mode.

    Virtual mode ensures that built-in filesystem tools (ls, read_file, glob)
    resolve paths like /evidence/pair_001.json to data_dir/evidence/pair_001.json
    on real disk rather than against an in-memory StateBackend.

    Returns a ``LoggingAndFallbackFilesystemBackend`` (subclass of
    ``FilesystemBackend``) so every ls/glob call is logged as structured JSON
    for observability (T3).
    """
    return LoggingAndFallbackFilesystemBackend(root_dir=data_dir, virtual_mode=True)


def create_summarizer_agent(
    *,
    model: str | BaseChatModel | None = None,
    backend: BackendProtocol | BackendFactory | None = None,
    inner_subagents: Sequence[dict[str, Any]] = (),
    tools: Sequence[BaseTool | Any] | None = None,
    data_dir: str | None = None,
) -> Runnable:
    """Create the autonomous report-finalization DeepAgent.

    The summarizer supervises the write -> validate -> critic -> repair loop.
    It is intentionally not an artifact writer; only its inner report_writer
    subagent owns drug.md and target_assessment.json writes.

    Args:
        model: LLM model string or BaseChatModel instance.
        backend: Explicit backend to use.  Mutually exclusive with ``data_dir``.
        inner_subagents: Sequence of inner subagent config dicts.
        tools: Override tool list.  Defaults to the standard summarizer tool set.
        data_dir: Root directory for on-disk evidence files.  When provided the
            factory builds a ``FilesystemBackend(root_dir=data_dir,
            virtual_mode=True)`` automatically.  Mutually exclusive with
            ``backend`` — pass one or the other, never both.

    Raises:
        ValueError: If both ``backend`` and ``data_dir`` are provided.
    """
    if backend is not None and data_dir is not None:
        raise ValueError(
            "create_summarizer_agent: pass either `backend` or `data_dir`, not both. "
            "When `data_dir` is provided, the factory builds the FilesystemBackend automatically."
        )
    if backend is None and data_dir is not None:
        backend = _build_disk_backend(data_dir)

    summarizer_tools = list(tools or [
        validate_drug_md,
        validate_drug_report_finalization,
        validate_quality,
        validate_stage3_gate,
        think_tool,
    ])

    agent = create_deep_agent(
        model=model,
        tools=summarizer_tools,
        system_prompt=SUMMARIZER_PROMPT,
        subagents=list(inner_subagents),
        backend=backend,
        middleware=[
            ReadOnlyToolGuardMiddleware(
                blocked_tool_names=_SUMMARIZER_BLOCKED_TOOLS,
            ),
            BuildEvidenceSummaryGuardMiddleware(),
            RepairCycleCounterMiddleware(max_cycles=2),
            SummarizerFinalizationGuardMiddleware(),
            FrozenTemplateSpanMiddleware(data_dir=data_dir),
            AnnotationDensityMiddleware(),
        ],
    )

    return agent.with_config({"recursion_limit": 3000})


class _CriticSliceWrapper:
    """Thin lifecycle wrapper: write slices -> invoke agent -> cleanup slices.

    This is NOT a LangGraph node or DeepAgent — it is a minimal callable that
    satisfies the Runnable protocol used by DeepAgents CompiledSubAgent.  The
    only public method is ``invoke``; ``with_config`` delegates to the inner
    agent so that recursion_limit and other config flow through unchanged.
    """

    def __init__(self, agent: Runnable, *, data_dir: str) -> None:
        self._agent = agent
        self._data_dir = data_dir

    # ------------------------------------------------------------------
    # Runnable protocol: delegate with_config so callers can chain it
    # ------------------------------------------------------------------

    def with_config(self, config: Any, **kwargs: Any) -> "_CriticSliceWrapper":
        new_agent = self._agent.with_config(config, **kwargs)
        return _CriticSliceWrapper(new_agent, data_dir=self._data_dir)

    # ------------------------------------------------------------------
    # Core: write slices, invoke, cleanup
    # ------------------------------------------------------------------

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:  # noqa: A002
        """Write critic slices, run the inner agent, then clean up."""
        # Lazy import to avoid circular dependency:
        # summarizer/agent.py <- configs.py <- summarizer/__init__.py
        from src.agents.drug_target.subagents.configs import (  # noqa: PLC0415
            cleanup_critic_slices,
            filter_hypothesis_evidence_files,
            write_critic_slices,
        )
        _emit_lifecycle("before_filter", self._data_dir)
        filter_hypothesis_evidence_files(self._data_dir)
        _emit_lifecycle("before_write", self._data_dir)
        write_critic_slices(self._data_dir)
        _emit_lifecycle("before_invoke", self._data_dir)
        try:
            if config is not None:
                return self._agent.invoke(input, config, **kwargs)
            return self._agent.invoke(input, **kwargs)
        finally:
            _emit_lifecycle("after_invoke", self._data_dir)
            cleanup_critic_slices(self._data_dir)
            _emit_lifecycle("after_cleanup", self._data_dir)

    async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:  # noqa: A002
        """Async variant: write critic slices, run the inner agent, then clean up."""
        from src.agents.drug_target.subagents.configs import (  # noqa: PLC0415
            cleanup_critic_slices,
            filter_hypothesis_evidence_files,
            write_critic_slices,
        )
        _emit_lifecycle("before_filter", self._data_dir)
        filter_hypothesis_evidence_files(self._data_dir)
        _emit_lifecycle("before_write", self._data_dir)
        write_critic_slices(self._data_dir)
        _emit_lifecycle("before_invoke", self._data_dir)
        try:
            if config is not None:
                return await self._agent.ainvoke(input, config, **kwargs)
            return await self._agent.ainvoke(input, **kwargs)
        finally:
            _emit_lifecycle("after_invoke", self._data_dir)
            cleanup_critic_slices(self._data_dir)
            _emit_lifecycle("after_cleanup", self._data_dir)


def wrap_summarizer_with_critic_slices(
    agent: Runnable,
    *,
    data_dir: str,
) -> _CriticSliceWrapper:
    """Wrap a summarizer agent with critic-slice lifecycle management.

    Writes evidence/_critic_slices/ before the agent runs and removes it
    afterward (unless OMB_CRITIC_SLICES_KEEP=1 is set in the environment).

    Args:
        agent: The compiled summarizer Runnable to wrap.
        data_dir: Path to the run's working directory (parent of ``evidence/``).

    Returns:
        A ``_CriticSliceWrapper`` that satisfies the Runnable invoke protocol.
    """
    return _CriticSliceWrapper(agent, data_dir=data_dir)


def get_summarizer_subagent(
    *,
    model: str | BaseChatModel | None = None,
    backend: BackendProtocol | BackendFactory | None = None,
    inner_subagents: Sequence[dict[str, Any]] = (),
    data_dir: str | None = None,
) -> dict[str, Any]:
    """Return the summarizer in DeepAgents CompiledSubAgent format.

    When ``data_dir`` is provided the returned runnable is wrapped with
    ``_CriticSliceWrapper`` so that per-gene critic slices are written to
    ``evidence/_critic_slices/`` before the first critic call and removed
    afterward.
    """
    agent = create_summarizer_agent(
        model=model,
        backend=backend,
        data_dir=data_dir,
        inner_subagents=inner_subagents,
    )

    runnable: Runnable | _CriticSliceWrapper
    if data_dir is not None:
        runnable = wrap_summarizer_with_critic_slices(agent, data_dir=data_dir)
    else:
        runnable = agent

    return {
        "name": "summarizer",
        "description": (
            "Autonomous audited report finalizer. Runs report_writer, "
            "deterministic validators, read-only critic, and bounded repair "
            "loop before reporting pass/fail."
        ),
        "runnable": runnable,
    }


__all__ = [
    "create_summarizer_agent",
    "get_summarizer_subagent",
    "wrap_summarizer_with_critic_slices",
]
