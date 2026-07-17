"""Deterministic coordinator for the guarded Drug Target role agents."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Any, NotRequired, TypedDict

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import Runnable, RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from src.agents.drug_target.middleware import clear_guarded_report_run_artifacts
from src.agents.drug_target.tools import check_stage1_completion
from src.agents.drug_target.tools.hypothesis_schema import (
    validate_hypothesis_report_quality,
)


class GuardedPipelineState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    run_started_at: NotRequired[float]


def _compile_role(spec: dict[str, Any]) -> Runnable:
    return create_agent(
        model=spec.get("model"),
        name=spec["name"],
        **{
            key: spec[key] for key in ("tools", "system_prompt", "middleware")
            if key in spec
        },
    )


def _last_ai_message(result: dict[str, Any]) -> list[AIMessage]:
    messages = result.get("messages", [])
    return [message for message in messages[-3:] if isinstance(message, AIMessage)][-1:]


def _format_errors(errors: object) -> str:
    if not isinstance(errors, list):
        return "unknown validation error"
    text = "; ".join(
        f"{item.get('code')}: {item.get('message')}"
        for item in errors
        if isinstance(item, dict)
    )
    return text or "unknown validation error"


def build_guarded_pipeline(
    subagent_specs: Sequence[dict[str, Any]],
    *,
    data_dir: str,
    disease: str,
    skip_evidence_assessor: bool,
) -> Runnable:
    """Compile existing role specs behind code-enforced phase edges."""
    run_dir = Path(data_dir).expanduser().resolve()
    roles = {spec["name"]: _compile_role(spec) for spec in subagent_specs}
    required = {"evidence_assessor", "hypothesis_writer", "report_writer"}
    if set(roles) != required:
        raise ValueError(f"guarded pipeline requires exactly {sorted(required)}")

    async def prepare(_state: GuardedPipelineState) -> dict[str, Any]:
        started_at = time.time()
        await asyncio.to_thread(clear_guarded_report_run_artifacts, run_dir)
        return {"run_started_at": started_at}

    async def invoke_role(
        role_name: str,
        instruction: str,
        config: RunnableConfig,
    ) -> dict[str, Any]:
        result = await roles[role_name].ainvoke(
            {"messages": [{"role": "user", "content": instruction}]},
            config=config,
        )
        return {"messages": _last_ai_message(result)}

    async def run_evidence(
        _state: GuardedPipelineState, config: RunnableConfig
    ) -> dict[str, Any]:
        return await invoke_role(
            "evidence_assessor",
            f"Run Stage 1+2+3 for {disease}. Data dir: {run_dir}.",
            config,
        )

    async def validate_evidence(_state: GuardedPipelineState) -> dict[str, Any]:
        raw = await asyncio.to_thread(
            check_stage1_completion.invoke,
            {"data_dir": str(run_dir)},
        )
        result = json.loads(raw)
        if not result.get("stage1_complete"):
            raise RuntimeError(
                "Drug Target evidence gate failed: "
                + str(result.get("recommendation") or "Stage 1 is incomplete")
            )
        return {}

    async def run_hypothesis(
        _state: GuardedPipelineState, config: RunnableConfig
    ) -> dict[str, Any]:
        return await invoke_role(
            "hypothesis_writer",
            f"Generate and save the canonical validated handoff. Data dir: {run_dir}.",
            config,
        )

    async def validate_hypothesis(state: GuardedPipelineState) -> dict[str, Any]:
        quality = await asyncio.to_thread(
            validate_hypothesis_report_quality,
            run_dir,
            run_started_at=state.get("run_started_at"),
        )
        if not quality.get("valid"):
            raise RuntimeError(
                "Drug Target hypothesis gate failed: "
                + _format_errors(quality.get("errors"))
            )
        return {}

    async def run_report(
        _state: GuardedPipelineState, config: RunnableConfig
    ) -> dict[str, Any]:
        return await invoke_role(
            "report_writer",
            f"Read the validated handoff and render the guarded report. Data dir: {run_dir}.",
            config,
        )

    graph = StateGraph(GuardedPipelineState)
    graph.add_node("prepare", prepare)
    graph.add_node("validate_evidence", validate_evidence)
    graph.add_node("hypothesis_writer", run_hypothesis)
    graph.add_node("validate_hypothesis", validate_hypothesis)
    graph.add_node("report_writer", run_report)
    graph.add_edge(START, "prepare")
    if skip_evidence_assessor:
        graph.add_edge("prepare", "validate_evidence")
    else:
        graph.add_node("evidence_assessor", run_evidence)
        graph.add_edge("prepare", "evidence_assessor")
        graph.add_edge("evidence_assessor", "validate_evidence")
    graph.add_edge("validate_evidence", "hypothesis_writer")
    graph.add_edge("hypothesis_writer", "validate_hypothesis")
    graph.add_edge("validate_hypothesis", "report_writer")
    graph.add_edge("report_writer", END)
    return graph.compile().with_config({"recursion_limit": 10000})
