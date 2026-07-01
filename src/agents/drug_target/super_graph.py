"""Super-graph for Drug Target Assessment.

Topology: START → run_deep_agent → validate_and_maybe_retry_hypothesis
→ finalize_report → END

The DeepAgents runnable is wrapped as a LangGraph node (run_deep_agent) so
that the deterministic finalize_report node can run after it within a single
StateGraph compilation.

Caller MUST pass initial state with all required keys::

    await drug_target_graph.ainvoke(
        {
            "messages": [],
            "data_dir": "/path/to/workspace",
            "disease": "breast cancer",
            "featured_lr_pairs": None,
            "report_finalization_error": None,
            "evidence_truncated": False,
        },
        config={
            "recursion_limit": 10000,   # TOP-LEVEL key, NOT under configurable
            "configurable": {"thread_id": "..."},
        },
    )
"""

from __future__ import annotations

from typing import Annotated

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from typing_extensions import NotRequired, TypedDict


class DrugTargetState(TypedDict):
    """State schema for the drug-target super-graph.

    Fields
    ------
    data_dir
        Workspace directory containing lr_candidates.json and evidence/.
        Injected by the caller; all nodes treat this as read-only.
    disease
        Disease context string (e.g. "breast cancer").
        Injected by the caller; finalize_report passes it to _load_expansion_inputs.
    featured_lr_pairs
        Subset of LR pairs selected as "featured" by the evidence assessor.
        Populated externally (wrapper_agent.py) — this super-graph is read-only.
        May be None when not yet determined.
    messages
        Accumulated messages. add_messages reducer appends new messages.
        Caller MUST pass ``[]`` as the initial value.
        run_deep_agent returns exactly one AIMessage (the last one from the
        DeepAgents transcript), so final len == 1.
    report_finalization_error
        Set by finalize_report on any failure. None means success.
    evidence_truncated
        True when finalize_report aborted due to evidence token budget exceeded.
        Default False.
    hypothesis_quality_valid
        True only when the saved hypothesis_report.json passed deterministic
        quality validation after the optional narrow retry.
    """

    data_dir: str
    disease: str
    featured_lr_pairs: list[str] | None
    messages: Annotated[list[BaseMessage], add_messages]
    report_finalization_error: str | None
    evidence_truncated: bool
    deep_agent_started_at: NotRequired[float]
    hypothesis_quality_valid: NotRequired[bool]
    hypothesis_quality_errors: NotRequired[list[dict]]
    hypothesis_retry_attempted: NotRequired[bool]
    hypothesis_retry_attempts: NotRequired[int]
    hypothesis_retry_status: NotRequired[str]
    hypothesis_retry_error: NotRequired[str | None]
    hypothesis_writer_skill_names: NotRequired[tuple[str, ...] | list[str]]
    hypothesis_writer_prompt_mode: NotRequired[str]
    skill_activation_mode: NotRequired[str]
    enable_skill_activator: NotRequired[bool]


def _drug_target_config_from_state(
    state: DrugTargetState,
    provider: str,
    *,
    use_checkpointer: bool,
):
    """Build an agent config while preserving benchmark hypothesis settings."""
    from typing import Literal as _Lit, cast as _cast

    from src.agents.drug_target.agent import (
        DrugTargetConfig,
        SkillActivationMode as _SkillActivationMode,
    )
    from src.agents.drug_target.subagents.prompts import (
        HypothesisWriterPromptMode as _HypothesisWriterPromptMode,
    )

    skill_activation_mode = state.get("skill_activation_mode")
    enable_skill_activator = state.get("enable_skill_activator")
    if enable_skill_activator is None and skill_activation_mode is not None:
        enable_skill_activator = skill_activation_mode == "middleware_plus_activator"

    prompt_mode = state.get("hypothesis_writer_prompt_mode")
    skill_names = state.get("hypothesis_writer_skill_names")
    default_hypothesis_writer_skill_names = (
        "drug-target-hypothesis",
        "opentargets-database",
        "gwas-database",
        "chembl-database",
    )

    return DrugTargetConfig(
        provider=_cast(
            _Lit["openai", "google", "ollama", "ollama-openai", "vllm", "claude", "openrouter"],
            provider,
        ),
        data_dir=state["data_dir"],
        disease=state["disease"],
        use_checkpointer=use_checkpointer,
        hypothesis_writer_skill_names=(
            tuple(skill_names)
            if skill_names is not None
            else default_hypothesis_writer_skill_names
        ),
        hypothesis_writer_prompt_mode=_cast(
            _HypothesisWriterPromptMode,
            prompt_mode if prompt_mode is not None else "default",
        ),
        skill_activation_mode=(
            _cast(_SkillActivationMode, skill_activation_mode)
            if skill_activation_mode is not None
            else None
        ),
        enable_skill_activator=(
            enable_skill_activator if enable_skill_activator is not None else True
        ),
    )


async def run_deep_agent(state: DrugTargetState, config: RunnableConfig) -> dict:
    """LangGraph node: invoke the DeepAgents drug-target runnable.

    Builds the inner DeepAgents runnable via create_drug_target_agent(config)
    and invokes it with the initial message list from state.  Returns only the
    last AIMessage from the transcript to keep checkpoint size bounded.

    The recursion_limit from the top-level RunnableConfig is forwarded to the
    inner runnable (CP-P1-014 fix: read from config top-level, NOT
    config["configurable"]).
    """
    # Lazy import to avoid circular dependency at module load time
    import asyncio
    import os
    import time

    from langchain_core.runnables import RunnableConfig as _RC

    from src.agents.drug_target.agent import create_drug_target_agent

    started_at = time.time()

    # Read provider from env — DrugTargetConfig.provider is a Literal; cast for pyright.
    provider_str = os.getenv("LLM_PROVIDER", "openrouter")

    agent_config = _drug_target_config_from_state(
        state,
        provider_str,
        use_checkpointer=False,
    )
    runnable, backend = await asyncio.to_thread(create_drug_target_agent, agent_config)

    # recursion_limit is a top-level RunnableConfig key (CP-P1-014)
    recursion_limit: int = config.get("recursion_limit", 10000)
    inner_config: _RC = _RC(
        recursion_limit=recursion_limit,
        configurable=config.get("configurable", {}),
    )

    try:
        result = await runnable.ainvoke(
            {"messages": state["messages"]},
            config=inner_config,
        )
    finally:
        if backend is not None and hasattr(backend, "cleanup"):
            await asyncio.to_thread(backend.cleanup)  # type: ignore[union-attr]

    # Filter to last AIMessage only — blocks trailing ToolMessages from being
    # stored in the checkpoint (CP-P0-009 messages contract).
    ai_messages = [m for m in result.get("messages", [])[-3:] if isinstance(m, AIMessage)]
    return {"messages": ai_messages[-1:], "deep_agent_started_at": started_at}


def _graph_hypothesis_retry_enabled() -> bool:
    """Return whether LangGraph-native hypothesis retry is enabled."""
    import os

    raw = os.getenv("DRUG_TARGET_GRAPH_HYPOTHESIS_RETRY", "1")
    return raw.strip().casefold() not in {"0", "false", "no", "off"}


def _hypothesis_retry_timeout_seconds() -> float | None:
    """Return graph-level retry timeout; 0 disables the timeout."""
    import os

    raw = os.getenv("DRUG_TARGET_HYPOTHESIS_RETRY_TIMEOUT_SECONDS", "600")
    try:
        value = float(raw)
    except ValueError:
        value = 600.0
    return None if value <= 0 else value


def _hypothesis_max_quality_retries() -> int:
    """Return the bounded graph-level hypothesis quality retry count."""
    import os

    raw = os.getenv("DRUG_TARGET_HYPOTHESIS_MAX_QUALITY_RETRIES", "3")
    try:
        value = int(raw)
    except ValueError:
        value = 3
    return max(0, value)


async def _validate_hypothesis_report_quality_async(
    data_dir: str,
    *,
    run_started_at: float | None,
) -> dict:
    """Run sync hypothesis validation off the LangGraph event loop."""
    import asyncio

    from src.agents.drug_target.tools.hypothesis_schema import (
        validate_hypothesis_report_quality,
    )

    return await asyncio.to_thread(
        validate_hypothesis_report_quality,
        data_dir,
        run_started_at=run_started_at,
    )


def _has_stage3_candidates(data_dir: str) -> bool:
    """Check whether deterministic evidence exists for a hypothesis retry."""
    import json
    from pathlib import Path

    path = Path(data_dir).expanduser().resolve() / "evidence" / "assessment_results.json"
    if not path.exists():
        return False
    try:
        assessment = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    candidates = assessment.get("stage3_candidates")
    return isinstance(candidates, list) and bool(candidates)


async def _invoke_hypothesis_retry(
    state: DrugTargetState,
    config: RunnableConfig,
    quality_errors: list[dict],
    *,
    attempt: int,
    max_attempts: int,
) -> None:
    """Invoke the drug-target agent with a hypothesis-writer-only instruction."""
    import asyncio
    import os
    import uuid
    from typing import Literal as _Lit, cast as _cast

    from langchain_core.runnables import RunnableConfig as _RC

    from src.agents.drug_target.agent import create_drug_target_agent
    from src.agents.drug_target.hypothesis_retry import build_hypothesis_retry_message

    provider_str = os.getenv("LLM_PROVIDER", "openrouter")
    provider = _cast(
        _Lit["openai", "google", "ollama", "ollama-openai", "vllm", "claude", "openrouter"],
        provider_str,
    )
    agent_config = _drug_target_config_from_state(
        state,
        provider,
        use_checkpointer=False,
    )
    runnable, backend = await asyncio.to_thread(create_drug_target_agent, agent_config)

    configurable = dict(config.get("configurable", {}) or {})
    configurable["thread_id"] = f"hypothesis-retry-{uuid.uuid4()}"
    inner_config: _RC = _RC(
        recursion_limit=config.get("recursion_limit", 10000),
        configurable=configurable,
    )
    message = build_hypothesis_retry_message(
        state["data_dir"],
        state["disease"],
        quality_errors=quality_errors,
        attempt=attempt,
        max_attempts=max_attempts,
    )
    try:
        call = runnable.ainvoke(
            {"messages": [{"role": "user", "content": message}]},
            config=inner_config,
        )
        timeout = _hypothesis_retry_timeout_seconds()
        if timeout is None:
            await call
        else:
            task = asyncio.ensure_future(call)
            done, _ = await asyncio.wait({task}, timeout=timeout)
            if not done:
                task.cancel()

                def _consume_cancelled_retry(done_task: asyncio.Future) -> None:
                    try:
                        done_task.result()
                    except BaseException:
                        pass

                task.add_done_callback(_consume_cancelled_retry)
                raise TimeoutError("hypothesis retry timed out")
            await task
    finally:
        if backend is not None and hasattr(backend, "cleanup"):
            await asyncio.to_thread(backend.cleanup)  # type: ignore[union-attr]


async def validate_and_maybe_retry_hypothesis(
    state: DrugTargetState,
    config: RunnableConfig,
) -> dict:
    """Validate hypothesis_report.json and run bounded narrow retries if needed."""
    import asyncio

    quality = await _validate_hypothesis_report_quality_async(
        state["data_dir"],
        run_started_at=state.get("deep_agent_started_at"),
    )
    attempts = 0
    if quality["valid"]:
        return {
            "hypothesis_quality_valid": True,
            "hypothesis_quality_errors": [],
            "hypothesis_retry_attempted": False,
            "hypothesis_retry_attempts": 0,
            "hypothesis_retry_status": "skipped",
            "hypothesis_retry_error": None,
        }

    retry_enabled = _graph_hypothesis_retry_enabled()
    has_stage3_candidates = await asyncio.to_thread(
        _has_stage3_candidates,
        state["data_dir"],
    )
    max_attempts = _hypothesis_max_quality_retries()

    if retry_enabled and has_stage3_candidates and max_attempts > 0:
        for attempt in range(1, max_attempts + 1):
            attempts = attempt
            try:
                await _invoke_hypothesis_retry(
                    state,
                    config,
                    quality.get("errors", []),
                    attempt=attempt,
                    max_attempts=max_attempts,
                )
                quality = await _validate_hypothesis_report_quality_async(
                    state["data_dir"],
                    run_started_at=state.get("deep_agent_started_at"),
                )
            except TimeoutError as exc:
                quality = await _validate_hypothesis_report_quality_async(
                    state["data_dir"],
                    run_started_at=state.get("deep_agent_started_at"),
                )
                if quality["valid"]:
                    return {
                        "hypothesis_quality_valid": True,
                        "hypothesis_quality_errors": [],
                        "hypothesis_retry_attempted": True,
                        "hypothesis_retry_attempts": attempts,
                        "hypothesis_retry_status": "success_after_timeout",
                        "hypothesis_retry_error": None,
                    }
                if attempt < max_attempts:
                    continue
                return {
                    "hypothesis_quality_valid": False,
                    "hypothesis_quality_errors": quality.get("errors", []),
                    "hypothesis_retry_attempted": True,
                    "hypothesis_retry_attempts": attempts,
                    "hypothesis_retry_status": "timeout",
                    "hypothesis_retry_error": str(exc) or "hypothesis retry timed out",
                    "report_finalization_error": (
                        "HYPOTHESIS_QUALITY_GATE_FAILED: hypothesis retry timed out"
                    ),
                }
            except Exception as exc:
                return {
                    "hypothesis_quality_valid": False,
                    "hypothesis_quality_errors": quality.get("errors", []),
                    "hypothesis_retry_attempted": True,
                    "hypothesis_retry_attempts": attempts,
                    "hypothesis_retry_status": "error",
                    "hypothesis_retry_error": f"{type(exc).__name__}: {exc}",
                    "report_finalization_error": (
                        f"HYPOTHESIS_QUALITY_GATE_FAILED: {type(exc).__name__}: {exc}"
                    ),
                }
            if quality["valid"]:
                return {
                    "hypothesis_quality_valid": True,
                    "hypothesis_quality_errors": [],
                    "hypothesis_retry_attempted": True,
                    "hypothesis_retry_attempts": attempts,
                    "hypothesis_retry_status": "success",
                    "hypothesis_retry_error": None,
                }
        retry_status = "failed"
        retry_attempted = True
    else:
        if not retry_enabled:
            retry_status = "disabled"
        elif not has_stage3_candidates:
            retry_status = "skipped_no_stage3_candidates"
        else:
            retry_status = "max_retries_zero"
        retry_attempted = False

    return {
        "hypothesis_quality_valid": False,
        "hypothesis_quality_errors": quality.get("errors", []),
        "hypothesis_retry_attempted": retry_attempted,
        "hypothesis_retry_attempts": attempts,
        "hypothesis_retry_status": retry_status,
        "hypothesis_retry_error": None,
        "report_finalization_error": (
            "HYPOTHESIS_QUALITY_GATE_FAILED: "
            + "; ".join(
                f"{err.get('code')}: {err.get('message')}"
                for err in quality.get("errors", [])
                if isinstance(err, dict)
            )
        ),
    }


def _route_after_hypothesis_quality(state: DrugTargetState) -> str:
    """Route to finalization only when hypothesis quality passed."""
    return "finalize_report" if state.get("hypothesis_quality_valid") is True else END


def build_drug_target_super_graph() -> CompiledStateGraph:
    """Build and compile the drug-target super-graph.

    Topology: START → run_deep_agent → validate_and_maybe_retry_hypothesis
    → finalize_report → END. The quality gate conditionally routes directly to
    END when hypothesis_report.json remains invalid after retry.

    Note: do NOT pass ``recursion_limit`` to ``.compile()`` — pass it at
    invocation time via ``config={"recursion_limit": N}``.
    """
    from src.agents.drug_target.finalize_report import finalize_report

    graph = StateGraph(DrugTargetState)
    graph.add_node("run_deep_agent", run_deep_agent)  # type: ignore[arg-type]
    graph.add_node(
        "validate_and_maybe_retry_hypothesis",
        validate_and_maybe_retry_hypothesis,  # type: ignore[arg-type]
    )
    graph.add_node("finalize_report", finalize_report)  # type: ignore[arg-type]

    graph.add_edge(START, "run_deep_agent")
    graph.add_edge("run_deep_agent", "validate_and_maybe_retry_hypothesis")
    graph.add_conditional_edges(
        "validate_and_maybe_retry_hypothesis",
        _route_after_hypothesis_quality,
        ["finalize_report", END],
    )
    graph.add_edge("finalize_report", END)

    return graph.compile()
