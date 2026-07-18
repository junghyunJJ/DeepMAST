"""Deterministic coordinator for the guarded Drug Target role agents."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Annotated, Any, NotRequired, TypedDict

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import Runnable, RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from src.agents.drug_target.hybrid_report_sections import (
    build_ollama_candidate_followup_specs,
    build_ollama_candidate_followups,
    build_ollama_report_recommendations,
)
from src.agents.drug_target.middleware import (
    DrugReportGuardrailMiddleware,
    clear_guarded_report_run_artifacts,
)
from src.agents.drug_target.ollama_hypothesis_cards import (
    OllamaCardSpec,
    OllamaHypothesisText,
    build_ollama_card_specs,
    build_ollama_hypothesis_report,
    parse_ollama_hypothesis_card,
    validate_ollama_hypothesis_card,
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
    enrichment_audit: NotRequired[dict[str, Any]]


MAX_OLLAMA_ENRICHMENT_REPAIRS = 3
LLM_ENRICHMENT_AUDIT_FILENAME = "llm_enrichment_audit.json"


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


def _ollama_card_instruction(
    spec: OllamaCardSpec,
    errors: tuple[str, ...] = (),
) -> str:
    """Request only bounded prose; the coordinator owns every report field."""
    correction = (
        " The prior card was rejected for: " + ", ".join(errors) + "."
        if errors
        else ""
    )
    return (
        "Return exactly four labelled, plain-text sentences for this bounded hypothesis card.\n"
        f"Card ID: {spec['id']}\n"
        f"Category: {spec['category']}\n"
        f"Genes: {', '.join(spec['genes'])}\n"
        f"Evidence references: {', '.join(spec['evidence_references'])}\n"
        f"Cell anchor: {spec['cell_anchor']}\n"
        "Do not call tools. Do not return JSON, Markdown, filenames, scores, "
        "drug claims, combination claims, synergy claims, direct-interaction claims, "
        "or genes outside the listed Genes. Use exactly these labels in order: "
        "CORE, CONSTRAINT, PREDICTION, VALIDATION."
        f"{correction}"
    )


def _ollama_report_instruction(label: str, errors: tuple[str, ...] = ()) -> str:
    """Keep native Ollama reporting to one bounded recommendation sentence."""
    correction = f" Previous rejection codes: {', '.join(errors)}." if errors else ""
    return (
        "Return exactly one plain, future-action sentence for a pipeline recommendation.\n"
        f"Recommendation: {label}\n"
        "Do not call tools. Do not return JSON, Markdown, filenames, paths, citations, "
        "headings, or additional sentences."
        f"{correction}"
    )


def _ollama_candidate_instruction(
    spec: Mapping[str, str], errors: tuple[str, ...] = ()
) -> str:
    correction = f" Previous rejection codes: {', '.join(errors)}." if errors else ""
    return (
        "Return exactly one plain, future-action sentence for the named candidate follow-up.\n"
        f"Candidate: {spec['gene']}\n"
        f"Supporting source: {spec['supporting_source']}\n"
        "Do not call tools. Do not return JSON, Markdown, filenames, paths, citations, "
        "headings, or additional sentences."
        f"{correction}"
    )


async def _bounded_ollama_response(
    role: Runnable,
    *,
    initial_instruction: str,
    repair_instruction: Callable[[tuple[str, ...]], str],
    validate: Callable[[str], tuple[object | None, tuple[str, ...]]],
    config: RunnableConfig,
    audit: dict[str, Any],
    unit_id: str,
    phase: str,
) -> tuple[object | None, dict[str, Any]]:
    """Try one bounded prompt and at most three local repairs."""
    history: list[dict[str, object]] = []
    last_result: dict[str, Any] = {"messages": []}
    for attempt in range(MAX_OLLAMA_ENRICHMENT_REPAIRS + 1):
        instruction = (
            initial_instruction
            if attempt == 0
            else repair_instruction(tuple(history[-1]["codes"]))
        )
        last_result = await role.ainvoke(
            {"messages": [{"role": "user", "content": instruction}]},
            config=config,
        )
        value, codes = validate(_ai_message_text(last_result))
        history.append(
            {
                "attempt": attempt,
                "status": "accepted" if not codes else "rejected",
                "codes": list(codes),
            }
        )
        if not codes:
            audit["units"][unit_id] = {
                "phase": phase,
                "status": "accepted",
                "repair_attempt_count": attempt,
                "attempts": history,
            }
            return value, last_result
    audit["units"][unit_id] = {
        "phase": phase,
        "status": "fallback",
        "repair_attempt_count": MAX_OLLAMA_ENRICHMENT_REPAIRS,
        "attempts": history,
    }
    return None, last_result


def write_ollama_enrichment_audit(data_dir: Path, audit: Mapping[str, Any]) -> None:
    """Persist audit metadata only after the structured save boundary succeeds."""
    evidence_dir = data_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / LLM_ENRICHMENT_AUDIT_FILENAME).write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
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
            card_texts: dict[str, OllamaHypothesisText] = {}
            last_result: dict[str, Any] = {"messages": []}
            audit: dict[str, Any] = {
                "schema_version": "drug_target.ollama_enrichment_audit.v1",
                "max_repair_attempts": MAX_OLLAMA_ENRICHMENT_REPAIRS,
                "units": {},
            }
            for spec in specs:
                def validate_card(
                    text: str, *, card_spec: OllamaCardSpec = spec
                ) -> tuple[OllamaHypothesisText | None, tuple[str, ...]]:
                    card, errors = parse_ollama_hypothesis_card(text)
                    if card is not None:
                        errors.extend(validate_ollama_hypothesis_card(card, spec=card_spec))
                    return (card if not errors else None), tuple(errors)

                card, last_result = await _bounded_ollama_response(
                    roles["hypothesis_writer"],
                    initial_instruction=_ollama_card_instruction(spec),
                    repair_instruction=lambda errors, card_spec=spec: _ollama_card_instruction(
                        card_spec, errors
                    ),
                    validate=validate_card,
                    config=config,
                    audit=audit,
                    unit_id=f"hypothesis.{spec['id']}",
                    phase="hypothesis",
                )
                card_texts[spec["id"]] = (
                    card if isinstance(card, dict) else spec["fallback_card"]
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
            return {
                "messages": _last_ai_message(last_result),
                "enrichment_audit": audit,
            }
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
        state: GuardedPipelineState, config: RunnableConfig
    ) -> dict[str, Any]:
        if provider == "ollama":
            source_audit = state.get("enrichment_audit")
            audit = {
                **(source_audit if isinstance(source_audit, dict) else {}),
                "units": dict(
                    source_audit.get("units", {})
                    if isinstance(source_audit, dict)
                    and isinstance(source_audit.get("units"), dict)
                    else {}
                ),
            }
            audit.setdefault("schema_version", "drug_target.ollama_enrichment_audit.v1")
            audit.setdefault("max_repair_attempts", MAX_OLLAMA_ENRICHMENT_REPAIRS)
            candidate_texts: dict[str, str] = {}
            texts: dict[str, str] = {}
            last_result: dict[str, Any] = {"messages": []}
            for spec in build_ollama_candidate_followup_specs(run_dir):
                gene = spec["gene"]

                def validate_followup(
                    text: str, *, candidate_gene: str = gene
                ) -> tuple[dict[str, str] | None, tuple[str, ...]]:
                    followups = build_ollama_candidate_followups(
                        run_dir, {candidate_gene: text}
                    )
                    if len(followups) == 1 and followups[0]["gene"] == candidate_gene:
                        return followups[0], ()
                    return None, ("CANDIDATE_FOLLOWUP_INVALID",)

                followup, last_result = await _bounded_ollama_response(
                    roles["report_writer"],
                    initial_instruction=_ollama_candidate_instruction(spec),
                    repair_instruction=lambda errors, candidate_spec=spec: _ollama_candidate_instruction(
                        candidate_spec, errors
                    ),
                    validate=validate_followup,
                    config=config,
                    audit=audit,
                    unit_id=f"candidate.{gene}",
                    phase="candidate_followup",
                )
                if isinstance(followup, dict):
                    candidate_texts[gene] = followup["text"]

            for index, label in enumerate(("primary", "secondary")):
                def validate_recommendation(
                    text: str,
                    *,
                    recommendation_index: int = index,
                    recommendation_label: str = label,
                ) -> tuple[str | None, tuple[str, ...]]:
                    payload = build_ollama_report_recommendations(
                        run_dir, {**texts, recommendation_label: text}
                    )
                    recommendations = payload.get("pipeline_recommendations", [])
                    if (
                        isinstance(recommendations, list)
                        and recommendation_index < len(recommendations)
                        and isinstance(recommendations[recommendation_index], dict)
                        and recommendations[recommendation_index].get("text") == text.strip()
                    ):
                        return text.strip(), ()
                    return None, ("PIPELINE_RECOMMENDATION_INVALID",)

                text, last_result = await _bounded_ollama_response(
                    roles["report_writer"],
                    initial_instruction=_ollama_report_instruction(label),
                    repair_instruction=lambda errors, recommendation_label=label: _ollama_report_instruction(
                        recommendation_label, errors
                    ),
                    validate=validate_recommendation,
                    config=config,
                    audit=audit,
                    unit_id=f"recommendation.{label}",
                    phase="pipeline_recommendation",
                )
                if isinstance(text, str):
                    texts[label] = text

            payload = build_ollama_report_recommendations(run_dir, texts)
            payload["candidate_followups"] = build_ollama_candidate_followups(
                run_dir, candidate_texts
            )
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
            await asyncio.to_thread(write_ollama_enrichment_audit, run_dir, audit)
            if ollama_report_guardrail is not None:
                await ollama_report_guardrail.aafter_agent({}, None)
            return {
                "messages": _last_ai_message(last_result),
                "enrichment_audit": audit,
            }
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
