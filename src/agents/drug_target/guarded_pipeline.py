"""Deterministic coordinator for the guarded Drug Target role agents."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Annotated, Any, Literal, NotRequired, TypedDict, TypeVar

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import Runnable, RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from src.agents.drug_target.hybrid_report_sections import (
    _ollama_recommendation_errors,
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


class OllamaEnrichmentAttempt(TypedDict):
    attempt: int
    status: Literal["accepted", "rejected"]
    codes: list[str]


T = TypeVar("T")


MAX_OLLAMA_ENRICHMENT_REPAIRS = 3
LLM_ENRICHMENT_AUDIT_FILENAME = "llm_enrichment_audit.json"

_GENE_TOKEN_RE = re.compile(r"\b[A-Z][A-Z0-9-]{1,}\b")
_REPAIR_GUIDANCE = {
    "CARD_FORMAT": "Return exactly four labelled lines in the required order.",
    "CORE_REQUIRED_TERMS": "CORE must say the listed genes are evidence-supported candidates for validation.",
    "CONSTRAINT_REQUIRED_TERMS": "CONSTRAINT must say this does not establish a causal mechanism.",
    "PREDICTION_REQUIRED_TERMS": "PREDICTION must use Test and perturbation.",
    "VALIDATION_REQUIRED_TERMS": "VALIDATION must use Evaluate and perturbation.",
    "UNSUPPORTED_GENE": "Use only the listed Genes.",
    "UNSUPPORTED_NUMBER": "Remove unsupported numbers.",
    "CANDIDATE_FOLLOWUP_UNSUPPORTED_ENTITY": "Use only the supplied gene and ordinary action words.",
    "PIPELINE_RECOMMENDATION_UNSUPPORTED_ENTITY": "Use only the allowed action anchor and ordinary action words.",
}


def _repair_guidance(
    errors: tuple[str, ...],
    *,
    safe_templates: Mapping[str, str] | None = None,
    sentence_rule: str = "Return exactly one plain sentence.",
) -> str:
    """Convert safe symbolic validator codes into model-safe rewrite directions."""
    directions: list[str] = []
    for code in errors:
        direction = _REPAIR_GUIDANCE.get(code)
        if direction is None and code.endswith("_LENGTH"):
            direction = "Keep the response between 24 and 360 characters."
        elif direction is None and code.endswith("_SINGLE_LINE"):
            direction = "Keep the response on one line."
        elif direction is None and code.endswith("_SENTENCE"):
            direction = sentence_rule
        elif direction is None and code.endswith("_UNSAFE_CONTENT"):
            direction = "Remove Markdown, paths, filenames, citations, and syntax."
        elif direction is None and code.endswith("_FUTURE_ACTION"):
            direction = "Use a future-directed action such as prioritize, validate, evaluate, or test."
        elif direction is None and code.endswith("_PLACEHOLDER"):
            direction = "Remove template placeholder syntax."
        elif direction is None and code.endswith("_UNSUPPORTED_SOURCE"):
            direction = "Remove source references."
        elif direction is None and code.endswith("_UNSAFE_CLAIM"):
            field = code.removesuffix("_UNSAFE_CLAIM")
            template = (safe_templates or {}).get(field)
            direction = (
                "Remove causal, efficacy, synergy, direct-interaction, and other unsupported claims."
                + (
                    f" Use this safe template: {template}"
                    if template
                    else " Return the supplied valid safe template for that field."
                )
            )
        elif direction is None:
            direction = "Return only the required bounded format."
        if direction not in directions:
            directions.append(direction)
    return "" if not directions else "\nRepair requirements:\n- " + "\n- ".join(directions)


def _recommendation_error_codes(
    errors: list[str],
    *,
    prefix: str,
) -> tuple[str, ...]:
    """Keep audit and repair inputs granular without retaining model prose."""
    codes: list[str] = []
    for error in errors:
        if error == "must be text.":
            suffix = "TYPE"
        elif error == "must contain 24-360 characters.":
            suffix = "LENGTH"
        elif error == "must be a single line.":
            suffix = "SINGLE_LINE"
        elif error == "must contain exactly one sentence.":
            suffix = "SENTENCE"
        elif error == "must not contain Markdown or source syntax.":
            suffix = "UNSAFE_CONTENT"
        elif error == "must state a future-directed action.":
            suffix = "FUTURE_ACTION"
        elif error == "UNSAFE_CLAIM":
            suffix = error
        elif error == "Interpretation text is empty.":
            suffix = "EMPTY"
        elif error == "Interpretation text contains template placeholder syntax.":
            suffix = "PLACEHOLDER"
        elif error.startswith("Unsupported entity token"):
            suffix = "UNSUPPORTED_ENTITY"
        elif error.startswith("Unsupported source reference"):
            suffix = "UNSUPPORTED_SOURCE"
        elif error.startswith("Unsupported numeric claim"):
            suffix = "UNSUPPORTED_NUMBER"
        else:
            suffix = "INVALID_FORMAT"
        code = f"{prefix}_{suffix}"
        if code not in codes:
            codes.append(code)
    return tuple(codes)


def _bounded_recommendation_codes(
    text: str,
    *,
    prefix: str,
    allowed_genes: tuple[str, ...],
) -> tuple[str, ...]:
    """Classify a rejected bounded response without keeping its text."""
    return _recommendation_error_codes(
        _ollama_recommendation_errors(
            text,
            {
                "allowed_genes": list(allowed_genes),
                "allowed_drugs": [],
                "allowed_sources": [],
                "allowed_terms": [],
                "allowed_numbers": [],
            },
        ),
        prefix=prefix,
    )


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
    genes = " and ".join(spec["genes"])
    core_line = (
        f"CORE: {spec['genes'][0]} is an evidence-supported candidate for validation "
        f"in {spec['cell_anchor']} context.\n"
        if len(spec["genes"]) == 1
        else f"CORE: {genes} are evidence-supported candidates for validation "
        f"in {spec['cell_anchor']} context.\n"
    )
    constraint_line = "CONSTRAINT: This follow-up does not establish a causal mechanism."
    prediction_line = (
        f"PREDICTION: Test whether separate {' and '.join(spec['genes'])} perturbation "
        f"shifts a prespecified {spec['cell_anchor']} readout."
    )
    validation_line = (
        f"VALIDATION: Evaluate separate {' and '.join(spec['genes'])} perturbation with a "
        f"generic primary assay, matched controls, and prespecified {spec['cell_anchor']} readouts."
    )
    repair = _repair_guidance(
        errors,
        safe_templates={
            "CORE": core_line.rstrip(),
            "CONSTRAINT": constraint_line,
            "PREDICTION": prediction_line,
            "VALIDATION": validation_line,
        },
        sentence_rule="Keep each labelled line to one or two plain sentences.",
    )
    return (
        "Return exactly four labelled, plain-text lines, with one or two plain sentences per line, for this bounded hypothesis card.\n"
        f"Card ID: {spec['id']}\n"
        f"Validation Focus: {spec['validation_focus']}\n"
        f"Genes: {', '.join(spec['genes'])}\n"
        f"Cell anchor: {spec['cell_anchor']}\n"
        f"{core_line}"
        f"{constraint_line}\n"
        f"{prediction_line}\n"
        f"{validation_line}\n"
        "Only PREDICTION and VALIDATION may propose a generic future assay, control, comparator, or readout. "
        "Present every method as a proposed test, not a reported result. Do not call tools. "
        "Do not return JSON, Markdown, filenames, paths, named drugs, doses, numerical thresholds, "
        "evidence references, established-biology assertions, unsafe claims, or genes outside the listed Genes. "
        "Use exactly these labels in order: CORE, CONSTRAINT, PREDICTION, VALIDATION."
        f"{repair}"
    )


def _ollama_report_instruction(
    label: str,
    *,
    action_anchor: str,
    errors: tuple[str, ...] = (),
) -> str:
    """Keep native Ollama reporting to one bounded recommendation sentence."""
    return (
        "Return exactly one plain, future-action sentence for a pipeline recommendation.\n"
        f"Recommendation: {label}\n"
        f"Allowed action anchor: {action_anchor}\n"
        "Use the allowed action anchor as the factual boundary and write one conservative future action.\n"
        "Do not call tools. Do not return JSON, Markdown, filenames, paths, citations, "
        "headings, or additional sentences."
        f"{_repair_guidance(errors)}"
    )


def _ollama_candidate_instruction(
    spec: Mapping[str, str], errors: tuple[str, ...] = ()
) -> str:
    return (
        "Return exactly one plain, future-action sentence for the named candidate follow-up.\n"
        f"Candidate: {spec['gene']}\n"
        f"Use {spec['gene']} verbatim and state one conservative future action.\n"
        "Do not call tools. Do not return JSON, Markdown, filenames, paths, citations, "
        "headings, or additional sentences."
        f"{_repair_guidance(errors)}"
    )


async def _bounded_ollama_response(
    role: Runnable,
    *,
    initial_instruction: str,
    repair_instruction: Callable[[tuple[str, ...]], str],
    validate: Callable[[str], tuple[T | None, tuple[str, ...]]],
    config: RunnableConfig,
    audit: dict[str, Any],
    unit_id: str,
    phase: str,
) -> tuple[T | None, dict[str, Any]]:
    """Try one bounded prompt and at most three local repairs."""
    history: list[OllamaEnrichmentAttempt] = []
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

                card, _ = await _bounded_ollama_response(
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
                    card if card is not None else spec["fallback_card"]
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
                "messages": [],
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
            candidate_specs = build_ollama_candidate_followup_specs(run_dir)
            for spec in candidate_specs:
                gene = spec["gene"]

                def validate_followup(
                    text: str, *, candidate_gene: str = gene
                ) -> tuple[dict[str, str] | None, tuple[str, ...]]:
                    followups = build_ollama_candidate_followups(
                        run_dir, {candidate_gene: text}
                    )
                    if len(followups) == 1 and followups[0]["gene"] == candidate_gene:
                        return followups[0], ()
                    return None, _bounded_recommendation_codes(
                        text,
                        prefix="CANDIDATE_FOLLOWUP",
                        allowed_genes=(candidate_gene,),
                    )

                followup, _ = await _bounded_ollama_response(
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
                if followup is not None:
                    candidate_texts[gene] = followup["text"]

            fallback_payload = build_ollama_report_recommendations(run_dir, {})
            fallback_recommendations = fallback_payload.get("pipeline_recommendations", [])
            if not isinstance(fallback_recommendations, list) or len(fallback_recommendations) != 2:
                raise RuntimeError("Drug Target report recommendations require two deterministic fallbacks")
            for index, label in enumerate(("primary", "secondary")):
                fallback = fallback_recommendations[index]
                if not isinstance(fallback, Mapping) or not isinstance(fallback.get("text"), str):
                    raise RuntimeError("Drug Target report recommendation fallback is invalid")
                action_anchor = fallback["text"].strip()
                allowed_genes = tuple(_GENE_TOKEN_RE.findall(action_anchor))

                def validate_recommendation(
                    text: str,
                    *,
                    recommendation_index: int = index,
                    recommendation_label: str = label,
                    recommendation_genes: tuple[str, ...] = allowed_genes,
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
                    return None, _bounded_recommendation_codes(
                        text,
                        prefix="PIPELINE_RECOMMENDATION",
                        allowed_genes=recommendation_genes,
                    )

                text, _ = await _bounded_ollama_response(
                    roles["report_writer"],
                    initial_instruction=_ollama_report_instruction(
                        label, action_anchor=action_anchor
                    ),
                    repair_instruction=lambda errors, recommendation_label=label, recommendation_anchor=action_anchor: _ollama_report_instruction(
                        recommendation_label,
                        action_anchor=recommendation_anchor,
                        errors=errors,
                    ),
                    validate=validate_recommendation,
                    config=config,
                    audit=audit,
                    unit_id=f"recommendation.{label}",
                    phase="pipeline_recommendation",
                )
                if text is not None:
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
                "messages": [],
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
