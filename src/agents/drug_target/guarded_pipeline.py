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

from src.agents.drug_target.hybrid_report_sections import (
    build_ollama_report_recommendations,
)
from src.agents.drug_target.middleware import (
    DrugReportGuardrailMiddleware,
    clear_guarded_report_run_artifacts,
)
from src.agents.drug_target.ollama_hypothesis_cards import (
    build_ollama_card_specs,
    build_ollama_hypothesis_report,
    is_ollama_card_text_safe,
)
from src.agents.drug_target.tools import check_stage1_completion
from src.agents.drug_target.tools.hypothesis_schema import (
    save_hypothesis_report,
    validate_hypothesis_report_quality,
)
from src.agents.drug_target.production_report_tools import (
    production_save_report_sections_tool,
)


class GuardedPipelineState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    run_started_at: NotRequired[float]


def _compile_role(spec: dict[str, Any], *, default_model: Any) -> Runnable:
    return create_agent(
        model=spec.get("model", default_model),
        name=spec["name"],
        **{
            key: spec[key] for key in ("tools", "system_prompt", "middleware")
            if key in spec
        },
    )


def _last_ai_message(result: dict[str, Any]) -> list[AIMessage]:
    messages = result.get("messages", [])
    return [message for message in messages[-3:] if isinstance(message, AIMessage)][-1:]


def _ai_message_text(result: dict[str, Any]) -> str:
    messages = _last_ai_message(result)
    if not messages:
        return ""
    content = messages[-1].content
    if isinstance(content, str):
        return content
    return "".join(
        part.get("text", "")
        for part in content
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    )


def _format_errors(errors: object) -> str:
    if not isinstance(errors, list):
        return "unknown validation error"
    text = "; ".join(
        (
            f"{item.get('code')}: {item.get('message')}"
            if isinstance(item, dict)
            else str(item)
        )
        for item in errors
    )
    return text or "unknown validation error"


def _ollama_card_instruction(spec: dict[str, object], *, repair: bool = False) -> str:
    """Request only bounded prose; the coordinator owns every report field."""
    prefix = (
        "Rewrite the rejected card as" if repair else "Return"
    )
    return (
        f"{prefix} exactly one plain sentence for this bounded hypothesis card.\n"
        f"Card ID: {spec['id']}\n"
        f"Category: {spec['category']}\n"
        f"Genes: {', '.join(str(gene) for gene in spec['genes'])}\n"
        f"Evidence references: {', '.join(str(ref) for ref in spec['evidence_references'])}\n"
        f"Cell anchor: {spec['cell_anchor']}\n"
        "Do not call tools. Do not return JSON, Markdown, filenames, scores, "
        "drug claims, combination claims, synergy claims, direct-interaction claims, "
        "or genes outside the listed Genes."
    )


def _ollama_report_instruction(label: str, *, repair: bool = False) -> str:
    """Keep native Ollama reporting to one bounded recommendation sentence."""
    correction = (
        " Your previous response was invalid; correct it now."
        if repair
        else ""
    )
    return (
        "Return exactly one plain, future-action sentence for a pipeline recommendation.\n"
        f"Recommendation: {label}\n"
        "Do not call tools. Do not return JSON, Markdown, filenames, paths, citations, "
        "headings, or additional sentences."
        f"{correction}"
    )


def build_guarded_pipeline(
    subagent_specs: Sequence[dict[str, Any]],
    *,
    data_dir: str,
    default_model: Any,
    disease: str,
    skip_evidence_assessor: bool,
    provider: str | None = None,
) -> Runnable:
    """Compile existing role specs behind code-enforced phase edges."""
    run_dir = Path(data_dir).expanduser().resolve()
    ollama_report_guardrail: DrugReportGuardrailMiddleware | None = None
    roles: dict[str, Runnable] = {}
    for spec in subagent_specs:
        compiled_spec = spec
        if provider == "ollama" and spec["name"] == "report_writer":
            middleware = list(spec.get("middleware", ()))
            guardrails = [
                item
                for item in middleware
                if isinstance(item, DrugReportGuardrailMiddleware)
            ]
            if guardrails:
                ollama_report_guardrail = guardrails[-1]
                compiled_spec = {
                    **spec,
                    "middleware": [
                        item
                        for item in middleware
                        if not isinstance(item, DrugReportGuardrailMiddleware)
                    ],
                }
        roles[spec["name"]] = _compile_role(compiled_spec, default_model=default_model)
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
        if provider == "ollama":
            specs = build_ollama_card_specs(run_dir)
            known_genes: list[str] = []
            for spec in specs:
                symbols = spec.get("known_genes", spec["genes"])
                if isinstance(symbols, (list, tuple, set)):
                    known_genes.extend(str(gene) for gene in symbols)
            card_texts: dict[str, str] = {}
            last_result: dict[str, Any] = {"messages": []}
            for spec in specs:
                result = await roles["hypothesis_writer"].ainvoke(
                    {"messages": [{"role": "user", "content": _ollama_card_instruction(spec)}]},
                    config=config,
                )
                last_result = result
                text = _ai_message_text(result)
                if not is_ollama_card_text_safe(
                    text,
                    allowed_genes=spec["genes"],
                    known_genes=known_genes,
                ):
                    result = await roles["hypothesis_writer"].ainvoke(
                        {
                            "messages": [
                                {
                                    "role": "user",
                                    "content": _ollama_card_instruction(spec, repair=True),
                                }
                            ]
                        },
                        config=config,
                    )
                    last_result = result
                    text = _ai_message_text(result)
                card_texts[str(spec["id"])] = (
                    text
                    if is_ollama_card_text_safe(
                        text,
                        allowed_genes=spec["genes"],
                        known_genes=known_genes,
                    )
                    else str(spec["fallback_hypothesis"])
                )
            report = build_ollama_hypothesis_report(run_dir, card_texts)
            raw_receipt = await asyncio.to_thread(
                save_hypothesis_report.invoke,
                {"data_dir": str(run_dir), "report": report},
            )
            try:
                receipt = json.loads(raw_receipt)
            except (TypeError, json.JSONDecodeError) as exc:
                raise RuntimeError(
                    "Drug Target hypothesis save returned an invalid receipt"
                ) from exc
            if not isinstance(receipt, dict) or receipt.get("saved") is not True:
                raise RuntimeError(
                    "Drug Target hypothesis save failed: "
                    + _format_errors(receipt.get("errors") if isinstance(receipt, dict) else None)
                )
            return {"messages": _last_ai_message(last_result)}
        instruction = (
            f"Generate and save the canonical validated handoff. Data dir: {run_dir}."
        )
        try:
            return await invoke_role("hypothesis_writer", instruction, config)
        except RuntimeError as exc:
            if "HYPOTHESIS_REPORT_MISSING" not in str(exc):
                raise
            return await invoke_role(
                "hypothesis_writer",
                f"The handoff was not saved. Call save_hypothesis_report now with a valid canonical payload. Data dir: {run_dir}.",
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
        if provider == "ollama":
            texts: dict[str, str] = {}
            last_result: dict[str, Any] = {"messages": []}
            for index, label in enumerate(("primary", "secondary")):
                result = await roles["report_writer"].ainvoke(
                    {"messages": [{"role": "user", "content": _ollama_report_instruction(label)}]},
                    config=config,
                )
                last_result = result
                text = _ai_message_text(result)
                candidate_payload = build_ollama_report_recommendations(
                    run_dir,
                    {**texts, label: text},
                )
                recommendations = candidate_payload.get("pipeline_recommendations", [])
                accepted = (
                    isinstance(recommendations, list)
                    and index < len(recommendations)
                    and isinstance(recommendations[index], dict)
                    and recommendations[index].get("text") == text.strip()
                )
                if not accepted:
                    result = await roles["report_writer"].ainvoke(
                        {
                            "messages": [
                                {
                                    "role": "user",
                                    "content": _ollama_report_instruction(label, repair=True),
                                }
                            ]
                        },
                        config=config,
                    )
                    last_result = result
                    text = _ai_message_text(result)
                texts[label] = text

            payload = build_ollama_report_recommendations(run_dir, texts)
            raw_receipt = await asyncio.to_thread(
                production_save_report_sections_tool(run_dir, disease).invoke,
                {"payload": payload},
            )
            try:
                receipt = json.loads(raw_receipt)
            except (TypeError, json.JSONDecodeError) as exc:
                raise RuntimeError(
                    "Drug Target report sections save returned an invalid receipt"
                ) from exc
            if not isinstance(receipt, dict) or receipt.get("saved") is not True:
                raise RuntimeError(
                    "Drug Target report sections save failed: "
                    + _format_errors(receipt.get("errors") if isinstance(receipt, dict) else None)
                )
            if ollama_report_guardrail is not None:
                await ollama_report_guardrail.aafter_agent({}, None)
            return {"messages": _last_ai_message(last_result)}
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
