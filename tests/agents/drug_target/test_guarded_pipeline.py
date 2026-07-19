from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from src.agents.drug_target import guarded_pipeline


DEFAULT_MODEL = object()


class _RoleAgent:
    def __init__(
        self,
        name: str,
        calls: list[str],
        *,
        instructions: list[str] | None = None,
        first_error: RuntimeError | None = None,
    ) -> None:
        self.name = name
        self.calls = calls
        self.instructions = instructions
        self.first_error = first_error

    async def ainvoke(
        self, _input: dict[str, Any], config: Any = None
    ) -> dict[str, Any]:
        _ = config
        if self.instructions is not None:
            self.instructions.append(str(_input["messages"][0]["content"]))
        self.calls.append(self.name)
        if self.first_error is not None:
            error, self.first_error = self.first_error, None
            raise error
        return {"messages": [{"role": "assistant", "content": f"{self.name}:done"}]}


def _specs() -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "model": object(),
            "tools": [],
            "system_prompt": name,
            "middleware": [],
        }
        for name in ("evidence_assessor", "hypothesis_writer", "report_writer")
    ]


def _bounded_card(gene: str, anchor: str = "malignant cell") -> str:
    return "\n".join((
        f"CORE: {gene} is an evidence-supported candidate for validation in {anchor} context. Its prioritization remains a bounded follow-up question.",
        "CONSTRAINT: This follow-up does not establish a causal mechanism. It remains a bounded candidate-level interpretation.",
        f"PREDICTION: Test whether separate {gene} perturbation shifts a prespecified {anchor} readout. Compare the perturbation with a matched non-targeting control.",
        f"VALIDATION: Evaluate separate {gene} perturbation with a generic primary assay, matched controls, and prespecified {anchor} readouts. Add an orthogonal comparator only as a future design choice.",
    ))


def _ollama_card_spec(card_id: str, category: str, gene: str) -> dict[str, object]:
    card = {
        "core_claim": f"{gene} is an evidence-supported candidate for validation in malignant cell context.",
        "interpretation_note": "This follow-up does not establish a causal mechanism.",
        "falsifiable_prediction": f"Test whether separate {gene} perturbation shifts a prespecified malignant cell readout.",
        "validation_approach": f"Evaluate separate {gene} perturbation with a generic primary assay, matched controls, and prespecified malignant cell readouts.",
    }
    return {
        "id": card_id,
        "category": category,
        "validation_focus": "Mechanistic follow-up",
        "genes": [gene],
        "evidence_references": [f"ot_{gene}.json", f"stage3_{gene}.json"],
        "cell_anchor": "malignant cell",
        "fallback_hypothesis": card["core_claim"],
        "fallback_card": card,
        "known_genes": (
            "EFNB2", "EPHB4", "ERBB2", "ERBB3", "INSR", "LAMA5", "SDC1"
        ),
    }


def test_native_ollama_initial_card_instruction_requires_rich_bounded_prose() -> None:
    card_instruction = guarded_pipeline._ollama_card_instruction(
        _ollama_card_spec("mechanism", "Mechanism of Action", "ERBB3")
    )
    card_repair = guarded_pipeline._ollama_card_instruction(
        _ollama_card_spec("mechanism", "Mechanism of Action", "ERBB3"),
        (
            "CORE_UNSAFE_CLAIM",
            "CONSTRAINT_UNSAFE_CLAIM",
            "PREDICTION_UNSAFE_CLAIM",
            "VALIDATION_UNSAFE_CLAIM",
        ),
    )
    candidate_instruction = guarded_pipeline._ollama_candidate_instruction(
        {"gene": "ERBB3", "supporting_source": "evidence/stage3_ERBB3.json"}
    )
    recommendation_instruction = guarded_pipeline._ollama_report_instruction(
        "primary",
        action_anchor="Prioritize ERBB3 validation before advancing target selection.",
    )

    assert "exactly four labelled, plain-text lines" in card_instruction
    assert "exactly two plain sentences on each labelled line" in card_instruction
    assert "exactly two plain sentences on each labelled line" not in card_repair
    assert "one or two plain sentences on each labelled line" in card_repair
    assert "Validation Focus: Mechanistic follow-up" in card_instruction
    assert "Category:" not in card_instruction
    for requirement in (
        "CORE must identify the listed Genes as evidence-supported candidates for validation in the Cell anchor.",
        "CONSTRAINT must state that the follow-up does not establish a causal mechanism.",
        "PREDICTION must propose testing separate listed-gene perturbation against a prespecified Cell anchor readout.",
        "VALIDATION must propose a generic future assay with matched controls or a comparator and prespecified Cell anchor readouts.",
    ):
        assert requirement in card_instruction
    for line in (
        "CORE: ERBB3 is an evidence-supported candidate for validation in malignant cell context.",
        "CONSTRAINT: This follow-up does not establish a causal mechanism.",
        "PREDICTION: Test whether separate ERBB3 perturbation shifts a prespecified malignant cell readout.",
        "VALIDATION: Evaluate separate ERBB3 perturbation with a generic primary assay, matched controls, and prespecified malignant cell readouts.",
    ):
        assert line not in card_instruction
        assert f"Use this safe template: {line}" in card_repair
    assert "rejected model prose" not in card_repair
    assert "exactly one plain sentence" not in card_instruction

    assert "ERBB3" in candidate_instruction
    assert "Supporting source" not in candidate_instruction
    assert "stage3_ERBB3.json" not in candidate_instruction
    assert "Use ERBB3 verbatim" in candidate_instruction
    assert "exactly one plain, future-action sentence" in candidate_instruction

    assert "Recommendation: primary" in recommendation_instruction
    assert "Allowed action anchor: Prioritize ERBB3 validation before advancing target selection." in recommendation_instruction
    assert "Use the allowed action anchor" in recommendation_instruction
    assert "exactly one plain, future-action sentence" in recommendation_instruction


def test_native_ollama_repair_instructions_map_detailed_codes_without_model_text() -> None:
    card_repair = guarded_pipeline._ollama_card_instruction(
        _ollama_card_spec("mechanism", "Mechanism of Action", "ERBB3"),
        ("CORE_REQUIRED_TERMS", "CORE_SENTENCE", "UNSUPPORTED_GENE"),
    )
    candidate_repair = guarded_pipeline._ollama_candidate_instruction(
        {"gene": "ERBB3", "supporting_source": "evidence/stage3_ERBB3.json"},
        ("CANDIDATE_FOLLOWUP_SENTENCE", "CANDIDATE_FOLLOWUP_UNSUPPORTED_ENTITY"),
    )
    recommendation_repair = guarded_pipeline._ollama_report_instruction(
        "primary",
        action_anchor="Prioritize ERBB3 validation before advancing target selection.",
        errors=("PIPELINE_RECOMMENDATION_FUTURE_ACTION",),
    )

    assert "CORE must say the listed genes are evidence-supported candidates for validation." in card_repair
    assert "Use only the listed Genes." in card_repair
    assert "Keep each labelled line to one or two plain sentences." in card_repair
    assert "Return exactly one plain sentence." in candidate_repair
    assert "Use only the supplied gene and ordinary action words." in candidate_repair
    assert "Use a future-directed action such as prioritize, validate, evaluate, or test." in recommendation_repair
    assert "CORE_REQUIRED_TERMS" not in card_repair
    assert "CANDIDATE_FOLLOWUP_SENTENCE" not in candidate_repair
    assert "PIPELINE_RECOMMENDATION_FUTURE_ACTION" not in recommendation_repair


def test_native_ollama_unsafe_claim_repairs_supply_safe_field_templates() -> None:
    repair = guarded_pipeline._ollama_card_instruction(
        _ollama_card_spec("mechanism", "Mechanism of Action", "ERBB3"),
        ("CONSTRAINT_UNSAFE_CLAIM", "PREDICTION_UNSAFE_CLAIM"),
    )

    assert "Remove causal, efficacy, synergy, direct-interaction, and other unsupported claims." in repair
    assert "Use this safe template: CONSTRAINT: This follow-up does not establish a causal mechanism." in repair
    assert "Use this safe template: PREDICTION: Test whether separate ERBB3 perturbation shifts a prespecified malignant cell readout." in repair
    assert "CONSTRAINT_UNSAFE_CLAIM" not in repair
    assert "PREDICTION_UNSAFE_CLAIM" not in repair
    assert "rejected model prose" not in repair

    candidate_repair = guarded_pipeline._ollama_candidate_instruction(
        {"gene": "ERBB3", "supporting_source": "evidence/stage3_ERBB3.json"},
        ("CANDIDATE_FOLLOWUP_UNSAFE_CLAIM",),
    )
    recommendation_repair = guarded_pipeline._ollama_report_instruction(
        "primary",
        action_anchor="Prioritize ERBB3 validation before advancing target selection.",
        errors=("PIPELINE_RECOMMENDATION_UNSAFE_CLAIM",),
    )

    for prompt, code in (
        (candidate_repair, "CANDIDATE_FOLLOWUP_UNSAFE_CLAIM"),
        (recommendation_repair, "PIPELINE_RECOMMENDATION_UNSAFE_CLAIM"),
    ):
        assert "Remove causal, efficacy, synergy, direct-interaction, and other unsupported claims." in prompt
        assert code not in prompt
        assert "drives disease progression" not in prompt


def _install_fakes(
    monkeypatch: pytest.MonkeyPatch,
    calls: list[str],
    *,
    evidence_complete: bool = True,
    hypothesis_valid: bool = True,
) -> None:
    monkeypatch.setattr(
        guarded_pipeline,
        "create_agent",
        lambda *, name, **_kwargs: _RoleAgent(name, calls),
    )
    monkeypatch.setattr(
        guarded_pipeline,
        "clear_guarded_report_run_artifacts",
        lambda _data_dir: calls.append("prepare"),
    )

    class _StageGate:
        @staticmethod
        def invoke(_args: dict[str, str]) -> str:
            return json.dumps({"stage1_complete": evidence_complete})

    monkeypatch.setattr(guarded_pipeline, "check_stage1_completion", _StageGate())
    monkeypatch.setattr(
        guarded_pipeline,
        "validate_hypothesis_report_quality",
        lambda *_args, **_kwargs: {
            "valid": hypothesis_valid,
            "errors": []
            if hypothesis_valid
            else [{"code": "HYPOTHESIS_REPORT_MISSING", "message": "missing"}],
        },
    )


def test_compile_role_preserves_legacy_spec_without_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    default_model = object()
    spec = {
        "name": "report_writer",
        "tools": [object()],
        "system_prompt": "write report",
        "middleware": [object()],
    }

    monkeypatch.setattr(
        guarded_pipeline,
        "create_agent",
        lambda **kwargs: captured.update(kwargs) or object(),
    )

    guarded_pipeline._compile_role(spec, default_model=default_model)

    assert captured == {"model": default_model, **spec}


def test_pipeline_uses_default_model_only_for_missing_role_models(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    models: dict[str, object] = {}
    specs = _specs()
    explicit_model = specs[0]["model"]
    specs[-1].pop("model")
    _install_fakes(monkeypatch, calls)

    def capture_model(*, name: str, model: object, **_kwargs: Any) -> _RoleAgent:
        models[name] = model
        return _RoleAgent(name, calls)

    monkeypatch.setattr(guarded_pipeline, "create_agent", capture_model)
    pipeline = guarded_pipeline.build_guarded_pipeline(
        specs,
        data_dir=str(tmp_path),
        default_model=DEFAULT_MODEL,
        disease="breast cancer",
        skip_evidence_assessor=False,
    )

    asyncio.run(pipeline.ainvoke({"messages": []}))

    assert models["evidence_assessor"] is explicit_model
    assert models["report_writer"] is DEFAULT_MODEL


def test_full_pipeline_runs_roles_in_code_enforced_order(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    _install_fakes(monkeypatch, calls)
    pipeline = guarded_pipeline.build_guarded_pipeline(
        _specs(),
        data_dir=str(tmp_path),
        default_model=DEFAULT_MODEL,
        disease="breast cancer",
        skip_evidence_assessor=False,
    )

    asyncio.run(pipeline.ainvoke({"messages": []}))

    assert calls == [
        "prepare",
        "evidence_assessor",
        "hypothesis_writer",
        "report_writer",
    ]


def test_resume_pipeline_skips_only_evidence_assessor(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    _install_fakes(monkeypatch, calls)
    pipeline = guarded_pipeline.build_guarded_pipeline(
        _specs(),
        data_dir=str(tmp_path),
        default_model=DEFAULT_MODEL,
        disease="breast cancer",
        skip_evidence_assessor=True,
    )

    asyncio.run(pipeline.ainvoke({"messages": []}))

    assert calls == ["prepare", "hypothesis_writer", "report_writer"]


def test_invalid_evidence_stops_before_hypothesis_and_report(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    _install_fakes(monkeypatch, calls, evidence_complete=False)
    pipeline = guarded_pipeline.build_guarded_pipeline(
        _specs(),
        data_dir=str(tmp_path),
        default_model=DEFAULT_MODEL,
        disease="breast cancer",
        skip_evidence_assessor=True,
    )

    with pytest.raises(RuntimeError, match="evidence gate failed"):
        asyncio.run(pipeline.ainvoke({"messages": []}))

    assert calls == ["prepare"]


def test_invalid_hypothesis_never_invokes_report_writer(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    _install_fakes(monkeypatch, calls, hypothesis_valid=False)
    pipeline = guarded_pipeline.build_guarded_pipeline(
        _specs(),
        data_dir=str(tmp_path),
        default_model=DEFAULT_MODEL,
        disease="breast cancer",
        skip_evidence_assessor=True,
    )

    with pytest.raises(RuntimeError, match="hypothesis gate failed"):
        asyncio.run(pipeline.ainvoke({"messages": []}))

    assert calls == ["prepare", "hypothesis_writer"]


def test_missing_hypothesis_report_retries_writer_once_before_report(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    instructions: list[str] = []
    missing = RuntimeError("Hypothesis report guardrail failed with HYPOTHESIS_REPORT_MISSING")

    def fake_create_agent(*, name: str, **_kwargs: Any) -> _RoleAgent:
        return _RoleAgent(
            name,
            calls,
            instructions=instructions if name == "hypothesis_writer" else None,
            first_error=missing if name == "hypothesis_writer" else None,
        )

    monkeypatch.setattr(guarded_pipeline, "create_agent", fake_create_agent)
    monkeypatch.setattr(
        guarded_pipeline,
        "clear_guarded_report_run_artifacts",
        lambda _data_dir: calls.append("prepare"),
    )
    class _StageGate:
        @staticmethod
        def invoke(_args: dict[str, str]) -> str:
            return json.dumps({"stage1_complete": True})

    monkeypatch.setattr(guarded_pipeline, "check_stage1_completion", _StageGate())
    monkeypatch.setattr(
        guarded_pipeline,
        "validate_hypothesis_report_quality",
        lambda *_args, **_kwargs: {"valid": True, "errors": []},
    )

    pipeline = guarded_pipeline.build_guarded_pipeline(
        _specs(),
        data_dir=str(tmp_path),
        default_model=DEFAULT_MODEL,
        disease="breast cancer",
        skip_evidence_assessor=True,
    )

    asyncio.run(pipeline.ainvoke({"messages": []}))

    assert calls == ["prepare", "hypothesis_writer", "hypothesis_writer", "report_writer"]
    assert "save_hypothesis_report" in instructions[1]


def test_nonmissing_hypothesis_error_is_not_retried(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    error = RuntimeError("Hypothesis report guardrail failed with HYPOTHESIS_LAST_SAVE_REJECTION")

    def fake_create_agent(*, name: str, **_kwargs: Any) -> _RoleAgent:
        return _RoleAgent(name, calls, first_error=error if name == "hypothesis_writer" else None)

    monkeypatch.setattr(guarded_pipeline, "create_agent", fake_create_agent)
    monkeypatch.setattr(
        guarded_pipeline,
        "clear_guarded_report_run_artifacts",
        lambda _data_dir: calls.append("prepare"),
    )
    class _StageGate:
        @staticmethod
        def invoke(_args: dict[str, str]) -> str:
            return json.dumps({"stage1_complete": True})

    monkeypatch.setattr(guarded_pipeline, "check_stage1_completion", _StageGate())

    pipeline = guarded_pipeline.build_guarded_pipeline(
        _specs(),
        data_dir=str(tmp_path),
        default_model=DEFAULT_MODEL,
        disease="breast cancer",
        skip_evidence_assessor=True,
    )

    with pytest.raises(RuntimeError, match="HYPOTHESIS_LAST_SAVE_REJECTION"):
        asyncio.run(pipeline.ainvoke({"messages": []}))

    assert calls == ["prepare", "hypothesis_writer"]


def test_ollama_generates_one_bounded_card_per_spec(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    instructions: list[str] = []
    saved_reports: list[dict[str, object]] = []
    specs = [
        _ollama_card_spec(card_id, category, gene)
        for card_id, category, gene in (
            ("primary_pair_1", "Mechanism of Action", "EFNB2"),
            ("primary_pair_2", "Therapeutic Strategy", "EPHB4"),
            ("primary_pair_3", "Cross-Target Interaction", "ERBB2"),
            ("gene_level_1", "Novel Pathway", "ERBB3"),
            ("gene_level_2", "Mechanism of Action", "INSR"),
            ("gene_level_3", "Therapeutic Strategy", "LAMA5"),
        )
    ]
    report = {"hypotheses": []}

    class _CardRole(_RoleAgent):
        async def ainvoke(self, _input: dict[str, Any], config: Any = None):
            _ = config
            self.calls.append(self.name)
            if self.name == "hypothesis_writer":
                instruction = str(_input["messages"][0]["content"])
                instructions.append(instruction)
                genes = instruction.split("Genes: ")[1].split("\n", 1)[0]
                anchor = instruction.split("Cell anchor: ")[1].split("\n", 1)[0]
                return {
                    "messages": [
                        AIMessage(
                            content=_bounded_card(genes, anchor)
                        )
                    ]
                }
            return {"messages": [AIMessage(content="done")]}

    monkeypatch.setattr(
        guarded_pipeline,
        "create_agent",
        lambda *, name, **_kwargs: _CardRole(name, calls),
    )
    monkeypatch.setattr(
        guarded_pipeline,
        "clear_guarded_report_run_artifacts",
        lambda _data_dir: calls.append("prepare"),
    )
    monkeypatch.setattr(
        guarded_pipeline,
        "build_ollama_card_specs",
        lambda _data_dir: specs,
    )
    monkeypatch.setattr(
        guarded_pipeline,
        "build_ollama_hypothesis_report",
        lambda _data_dir, _card_texts: report,
    )

    class _SaveTool:
        @staticmethod
        def invoke(arguments: dict[str, object]) -> str:
            saved_reports.append(arguments["report"])
            return json.dumps({"saved": True})

    monkeypatch.setattr(guarded_pipeline, "save_hypothesis_report", _SaveTool())

    class _StageGate:
        @staticmethod
        def invoke(_args: dict[str, str]) -> str:
            return json.dumps({"stage1_complete": True})

    monkeypatch.setattr(guarded_pipeline, "check_stage1_completion", _StageGate())
    monkeypatch.setattr(
        guarded_pipeline,
        "validate_hypothesis_report_quality",
        lambda *_args, **_kwargs: {"valid": True, "errors": []},
    )
    payload = {
        "schema_version": "hybrid_report_sections/v1",
        "pipeline_recommendations": [
            {
                "text": "Prioritize ERBB2 validation before advancing target selection.",
                "supporting_sources": ["evidence/ot_ERBB2.json"],
            },
            {
                "text": "Evaluate ERBB3 evidence before planning follow-up studies.",
                "supporting_sources": ["evidence/ot_ERBB3.json"],
            },
        ],
    }
    monkeypatch.setattr(
        guarded_pipeline, "build_ollama_candidate_followup_specs", lambda _data_dir: []
    )
    monkeypatch.setattr(
        guarded_pipeline, "build_ollama_candidate_followups", lambda _data_dir, _texts: []
    )
    monkeypatch.setattr(
        guarded_pipeline, "build_ollama_report_recommendations", lambda _data_dir, texts: {
            **payload,
            "pipeline_recommendations": [
                {"text": texts.get("primary", "fallback primary"), "supporting_sources": ["evidence/ot_ERBB2.json"]},
                {"text": texts.get("secondary", "fallback secondary"), "supporting_sources": ["evidence/ot_ERBB3.json"]},
            ],
        }
    )
    monkeypatch.setattr(
        guarded_pipeline,
        "production_save_report_sections_tool",
        lambda *_args: type("_ReportSaveTool", (), {"invoke": staticmethod(lambda _args: '{"saved": true}')})(),
    )
    pipeline = guarded_pipeline.build_guarded_pipeline(
        _specs(),
        data_dir=str(tmp_path),
        default_model=DEFAULT_MODEL,
        disease="breast cancer",
        skip_evidence_assessor=True,
        provider="ollama",
    )

    asyncio.run(pipeline.ainvoke({"messages": []}))

    assert calls == [
        "prepare",
        "hypothesis_writer",
        "hypothesis_writer",
        "hypothesis_writer",
        "hypothesis_writer",
        "hypothesis_writer",
        "hypothesis_writer",
        "report_writer",
        "report_writer",
    ]
    assert [
        instruction.split("Card ID: ")[1].split("\n", 1)[0]
        for instruction in instructions
        if "Card ID: " in instruction
    ] == [spec["id"] for spec in specs]
    audit = json.loads(
        (tmp_path / "evidence" / "llm_enrichment_audit.json").read_text()
    )
    assert set(audit["units"]) >= {f"hypothesis.{spec['id']}" for spec in specs}
    assert all(
        audit["units"][f"hypothesis.{spec['id']}"]["repair_attempt_count"] <= 3
        for spec in specs
    )
    assert saved_reports == [report]


def test_rejected_ollama_card_repairs_three_times_then_uses_fallback(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    saved_card_texts: dict[str, str] = {}
    specs = [
        _ollama_card_spec(card_id, category, gene)
        for card_id, category, gene in (
            ("mechanism", "Mechanism of Action", "EFNB2"),
            ("therapy", "Therapeutic Strategy", "EPHB4"),
            ("cross_target", "Cross-Target Interaction", "ERBB2"),
            ("novel_pathway", "Novel Pathway", "ERBB3"),
        )
    ]
    responses = iter(
        [
            "bad",
            "bad",
            "bad",
            "bad",
            _bounded_card("EPHB4"),
            _bounded_card("ERBB2"),
            _bounded_card("ERBB3"),
        ]
    )

    class _CardRole(_RoleAgent):
        async def ainvoke(self, _input: dict[str, Any], config: Any = None):
            _ = config
            self.calls.append(self.name)
            if self.name == "hypothesis_writer":
                return {"messages": [AIMessage(content=next(responses))]}
            return {"messages": [AIMessage(content="done")]}

    monkeypatch.setattr(
        guarded_pipeline,
        "create_agent",
        lambda *, name, **_kwargs: _CardRole(name, calls),
    )
    monkeypatch.setattr(
        guarded_pipeline,
        "clear_guarded_report_run_artifacts",
        lambda _data_dir: calls.append("prepare"),
    )
    monkeypatch.setattr(
        guarded_pipeline,
        "build_ollama_card_specs",
        lambda _data_dir: specs,
    )
    monkeypatch.setattr(
        guarded_pipeline,
        "build_ollama_hypothesis_report",
        lambda _data_dir, card_texts: saved_card_texts.update(card_texts)
        or {"hypotheses": []},
    )

    class _SaveTool:
        @staticmethod
        def invoke(_arguments: dict[str, object]) -> str:
            return json.dumps({"saved": True})

    monkeypatch.setattr(guarded_pipeline, "save_hypothesis_report", _SaveTool())

    class _StageGate:
        @staticmethod
        def invoke(_args: dict[str, str]) -> str:
            return json.dumps({"stage1_complete": True})

    monkeypatch.setattr(guarded_pipeline, "check_stage1_completion", _StageGate())
    monkeypatch.setattr(
        guarded_pipeline,
        "validate_hypothesis_report_quality",
        lambda *_args, **_kwargs: {"valid": True, "errors": []},
    )
    payload = {
        "schema_version": "hybrid_report_sections/v1",
        "pipeline_recommendations": [
            {
                "text": "Prioritize ERBB2 validation before advancing target selection.",
                "supporting_sources": ["evidence/ot_ERBB2.json"],
            },
            {
                "text": "Evaluate ERBB3 evidence before planning follow-up studies.",
                "supporting_sources": ["evidence/ot_ERBB3.json"],
            },
        ],
    }
    monkeypatch.setattr(
        guarded_pipeline, "build_ollama_candidate_followup_specs", lambda _data_dir: []
    )
    monkeypatch.setattr(
        guarded_pipeline, "build_ollama_candidate_followups", lambda _data_dir, _texts: []
    )
    monkeypatch.setattr(
        guarded_pipeline, "build_ollama_report_recommendations", lambda _data_dir, texts: {
            **payload,
            "pipeline_recommendations": [
                {"text": texts.get("primary", "fallback primary"), "supporting_sources": ["evidence/ot_ERBB2.json"]},
                {"text": texts.get("secondary", "fallback secondary"), "supporting_sources": ["evidence/ot_ERBB3.json"]},
            ],
        }
    )
    monkeypatch.setattr(
        guarded_pipeline,
        "production_save_report_sections_tool",
        lambda *_args: type("_ReportSaveTool", (), {"invoke": staticmethod(lambda _args: '{"saved": true}')})(),
    )
    pipeline = guarded_pipeline.build_guarded_pipeline(
        _specs(),
        data_dir=str(tmp_path),
        default_model=DEFAULT_MODEL,
        disease="breast cancer",
        skip_evidence_assessor=True,
        provider="ollama",
    )

    asyncio.run(pipeline.ainvoke({"messages": []}))

    assert calls.count("hypothesis_writer") == 7
    assert saved_card_texts["mechanism"] == specs[0]["fallback_card"]
    audit = json.loads((tmp_path / "evidence" / "llm_enrichment_audit.json").read_text())
    assert audit["units"]["hypothesis.mechanism"]["repair_attempt_count"] == 3
    assert audit["units"]["hypothesis.mechanism"]["status"] == "fallback"
    assert "bad" not in json.dumps(audit)


def test_ollama_report_route_saves_bounded_payload(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    instructions: list[str] = []
    saved_payloads: list[dict[str, object]] = []
    responses = iter(
        [
            "Prioritize ERBB2 validation before advancing target selection.",
            "Evaluate ERBB3 evidence before planning follow-up studies.",
        ]
    )
    payload = {
        "schema_version": "hybrid_report_sections/v1",
        "pipeline_recommendations": [
            {
                "text": "Prioritize ERBB2 validation before advancing target selection.",
                "supporting_sources": ["evidence/ot_ERBB2.json"],
            },
            {
                "text": "Evaluate ERBB3 evidence before planning follow-up studies.",
                "supporting_sources": ["evidence/ot_ERBB3.json"],
            },
        ],
    }

    class _ReportRole(_RoleAgent):
        async def ainvoke(self, _input: dict[str, Any], config: Any = None):
            _ = config
            self.calls.append(self.name)
            if self.name == "report_writer":
                instructions.append(str(_input["messages"][0]["content"]))
                return {"messages": [AIMessage(content=next(responses))]}
            return {"messages": [AIMessage(content="done")]}

    class _SaveTool:
        @staticmethod
        def invoke(arguments: dict[str, object]) -> str:
            saved_payloads.append(arguments["payload"])
            return json.dumps({"saved": True})

    _install_fakes(monkeypatch, calls)
    monkeypatch.setattr(
        guarded_pipeline,
        "create_agent",
        lambda *, name, **_kwargs: _ReportRole(name, calls),
    )
    monkeypatch.setattr(guarded_pipeline, "build_ollama_card_specs", lambda _data_dir: [])
    monkeypatch.setattr(
        guarded_pipeline,
        "build_ollama_hypothesis_report",
        lambda _data_dir, _texts: {"hypotheses": []},
    )
    monkeypatch.setattr(
        guarded_pipeline,
        "save_hypothesis_report",
        type("_HypothesisSaveTool", (), {"invoke": staticmethod(lambda _args: '{"saved": true}')})(),
    )
    monkeypatch.setattr(
        guarded_pipeline,
        "build_ollama_report_recommendations",
        lambda _data_dir, _texts: payload,
    )
    monkeypatch.setattr(
        guarded_pipeline, "build_ollama_candidate_followup_specs", lambda _data_dir: []
    )
    monkeypatch.setattr(
        guarded_pipeline, "build_ollama_candidate_followups", lambda _data_dir, _texts: []
    )
    monkeypatch.setattr(
        guarded_pipeline,
        "production_save_report_sections_tool",
        lambda _data_dir, _disease: _SaveTool(),
    )

    pipeline = guarded_pipeline.build_guarded_pipeline(
        _specs(),
        data_dir=str(tmp_path),
        default_model=DEFAULT_MODEL,
        disease="breast cancer",
        skip_evidence_assessor=True,
        provider="ollama",
    )

    asyncio.run(pipeline.ainvoke({"messages": []}))

    assert calls == ["prepare", "report_writer", "report_writer"]
    assert [instruction.split("Recommendation: ")[1].split("\n", 1)[0] for instruction in instructions] == [
        "primary",
        "secondary",
    ]
    assert saved_payloads == [payload]


def test_unsafe_ollama_report_sentence_repairs_then_uses_fallback(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    responses = iter(
        [
            "Prioritize ERBB2 validation because it drives disease progression.",
        ]
        * 4
        + ["Evaluate ERBB3 evidence before planning follow-up studies."]
    )
    saved_payloads: list[dict[str, object]] = []

    class _ReportRole(_RoleAgent):
        async def ainvoke(self, _input: dict[str, Any], config: Any = None):
            _ = config, _input
            self.calls.append(self.name)
            if self.name == "report_writer":
                return {"messages": [AIMessage(content=next(responses))]}
            return {"messages": [AIMessage(content="done")]}

    class _SaveTool:
        @staticmethod
        def invoke(arguments: dict[str, object]) -> str:
            saved_payloads.append(arguments["payload"])
            return json.dumps({"saved": True})

    def build_payload(_data_dir: str, texts: dict[str, str]) -> dict[str, object]:
        primary = texts.get("primary", "")
        primary_text = (
            primary.strip()
            if primary == "Prioritize ERBB2 validation before advancing target selection."
            else "Prioritize ERBB2 validation before advancing target selection."
        )
        return {
            "schema_version": "hybrid_report_sections/v1",
            "pipeline_recommendations": [
                {"text": primary_text, "supporting_sources": ["evidence/ot_ERBB2.json"]},
                {
                    "text": texts.get(
                        "secondary",
                        "Evaluate ERBB3 evidence before planning follow-up studies.",
                    ).strip()
                    or "Evaluate ERBB3 evidence before planning follow-up studies.",
                    "supporting_sources": ["evidence/ot_ERBB3.json"],
                },
            ],
        }

    _install_fakes(monkeypatch, calls)
    monkeypatch.setattr(
        guarded_pipeline,
        "create_agent",
        lambda *, name, **_kwargs: _ReportRole(name, calls),
    )
    monkeypatch.setattr(guarded_pipeline, "build_ollama_card_specs", lambda _data_dir: [])
    monkeypatch.setattr(
        guarded_pipeline,
        "build_ollama_hypothesis_report",
        lambda _data_dir, _texts: {"hypotheses": []},
    )
    monkeypatch.setattr(
        guarded_pipeline,
        "save_hypothesis_report",
        type("_HypothesisSaveTool", (), {"invoke": staticmethod(lambda _args: '{"saved": true}')})(),
    )
    monkeypatch.setattr(guarded_pipeline, "build_ollama_report_recommendations", build_payload)
    monkeypatch.setattr(
        guarded_pipeline, "build_ollama_candidate_followup_specs", lambda _data_dir: []
    )
    monkeypatch.setattr(
        guarded_pipeline, "build_ollama_candidate_followups", lambda _data_dir, _texts: []
    )
    monkeypatch.setattr(
        guarded_pipeline,
        "production_save_report_sections_tool",
        lambda _data_dir, _disease: _SaveTool(),
    )

    pipeline = guarded_pipeline.build_guarded_pipeline(
        _specs(),
        data_dir=str(tmp_path),
        default_model=DEFAULT_MODEL,
        disease="breast cancer",
        skip_evidence_assessor=True,
        provider="ollama",
    )

    asyncio.run(pipeline.ainvoke({"messages": []}))

    assert calls == ["prepare", "report_writer", "report_writer", "report_writer", "report_writer", "report_writer"]
    assert len(saved_payloads) == 1
    audit = json.loads((tmp_path / "evidence" / "llm_enrichment_audit.json").read_text())
    assert saved_payloads[0]["pipeline_recommendations"][0]["text"] == (
        "Prioritize ERBB2 validation before advancing target selection."
    )
    assert audit["units"]["recommendation.primary"]["status"] == "fallback"
    assert "PIPELINE_RECOMMENDATION_UNSAFE_CLAIM" in audit["units"]["recommendation.primary"]["attempts"][0]["codes"]
    assert "PIPELINE_RECOMMENDATION_INVALID" not in audit["units"]["recommendation.primary"]["attempts"][0]["codes"]


def test_bounded_ollama_response_repairs_three_times_before_fallback() -> None:
    calls: list[str] = []
    contexts: list[str] = []

    class _RejectedRole:
        async def ainvoke(self, _input: dict[str, Any], config: Any = None) -> dict[str, Any]:
            _ = config
            calls.append(str(_input["messages"][0]["content"]))
            return {"messages": [AIMessage(content="bad")]}

    async def run() -> tuple[object | None, dict[str, Any], dict[str, Any]]:
        audit: dict[str, Any] = {"units": {}}
        value, result = await guarded_pipeline._bounded_ollama_response(
            _RejectedRole(),
            initial_instruction="initial",
            repair_instruction=lambda codes: f"repair {','.join(codes)}",
            validate=lambda text, context: (
                contexts.append(context) or (None, ("BAD",))
                if text == "bad"
                else (text, ())
            ),
            config={},
            audit=audit,
            unit_id="hypothesis.mechanism",
            phase="hypothesis",
        )
        return value, result, audit

    value, result, audit = asyncio.run(run())

    assert value is None
    assert result == {"messages": [AIMessage(content="bad")]}
    assert calls == ["initial", "repair BAD", "repair BAD", "repair BAD"]
    assert contexts == ["initial", "repair", "repair", "repair"]
    assert audit["units"]["hypothesis.mechanism"] == {
        "phase": "hypothesis",
        "status": "fallback",
        "repair_attempt_count": 3,
        "attempts": [
            {"attempt": index, "status": "rejected", "codes": ["BAD"]}
            for index in range(4)
        ],
    }


def test_card_repair_guidance_excludes_rejected_model_prose() -> None:
    from src.agents.drug_target.ollama_hypothesis_cards import (
        parse_ollama_hypothesis_card,
        validate_ollama_hypothesis_card,
    )

    sentinel = "raw-secret-sentinel"
    rejected = _bounded_card("ERBB3").replace(
        "in malignant cell context.",
        f"in malignant cell context where {sentinel} drives disease.",
        1,
    )
    instructions: list[str] = []
    spec = _ollama_card_spec("mechanism", "Mechanism of Action", "ERBB3")

    class _RejectedCardRole:
        async def ainvoke(
            self, payload: dict[str, Any], config: Any = None
        ) -> dict[str, Any]:
            _ = config
            instructions.append(str(payload["messages"][0]["content"]))
            return {"messages": [AIMessage(content=rejected)]}

    def validate_card(
        text: str, attempt_context: str
    ) -> tuple[object | None, tuple[str, ...]]:
        card, errors = parse_ollama_hypothesis_card(text)
        if card is not None:
            errors.extend(
                validate_ollama_hypothesis_card(
                    card,
                    spec=spec,
                    attempt_context=attempt_context,
                )
            )
        return (card if not errors else None), tuple(errors)

    async def run() -> dict[str, Any]:
        audit: dict[str, Any] = {"units": {}}
        await guarded_pipeline._bounded_ollama_response(
            _RejectedCardRole(),
            initial_instruction=guarded_pipeline._ollama_card_instruction(spec),
            repair_instruction=lambda codes: guarded_pipeline._ollama_card_instruction(
                spec, codes
            ),
            validate=validate_card,
            config={},
            audit=audit,
            unit_id="hypothesis.mechanism",
            phase="hypothesis",
        )
        return audit

    audit = asyncio.run(run())

    assert "CORE_UNSAFE_CLAIM" in audit["units"]["hypothesis.mechanism"]["attempts"][0]["codes"]
    assert "Use this safe template: CORE: ERBB3 is an evidence-supported candidate" in instructions[1]
    assert sentinel not in instructions[1]
    assert sentinel not in json.dumps(audit)


def test_rejected_candidate_followup_repairs_three_times_then_is_omitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    saved_payloads: list[dict[str, object]] = []
    responses = iter(
        ["Prioritize FN1 validation because it drives disease progression."] * 4
        + [
            "Prioritize FN1 validation before advancing target selection.",
            "Evaluate FN1 evidence before planning follow-up studies.",
        ]
    )

    class _ReportRole(_RoleAgent):
        async def ainvoke(self, _input: dict[str, Any], config: Any = None) -> dict[str, Any]:
            _ = config, _input
            self.calls.append(self.name)
            if self.name == "report_writer":
                return {"messages": [AIMessage(content=next(responses))]}
            return {"messages": [AIMessage(content="done")]}

    class _SaveTool:
        @staticmethod
        def invoke(arguments: dict[str, object]) -> str:
            saved_payloads.append(arguments["payload"])
            return json.dumps({"saved": True})

    def recommendations(_data_dir: str, texts: dict[str, str]) -> dict[str, object]:
        return {
            "schema_version": "hybrid_report_sections/v1",
            "pipeline_recommendations": [
                {"text": texts.get("primary", "fallback primary"), "supporting_sources": ["evidence/stage3_FN1.json"]},
                {"text": texts.get("secondary", "fallback secondary"), "supporting_sources": ["evidence/stage3_FN1.json"]},
            ],
        }

    _install_fakes(monkeypatch, calls)
    monkeypatch.setattr(
        guarded_pipeline, "create_agent", lambda *, name, **_kwargs: _ReportRole(name, calls)
    )
    monkeypatch.setattr(guarded_pipeline, "build_ollama_card_specs", lambda _data_dir: [])
    monkeypatch.setattr(
        guarded_pipeline, "build_ollama_hypothesis_report", lambda _data_dir, _texts: {"hypotheses": []}
    )
    monkeypatch.setattr(
        guarded_pipeline,
        "save_hypothesis_report",
        type("_HypothesisSaveTool", (), {"invoke": staticmethod(lambda _args: '{"saved": true}')})(),
    )
    monkeypatch.setattr(
        guarded_pipeline,
        "build_ollama_candidate_followup_specs",
        lambda _data_dir: [{"gene": "FN1", "supporting_source": "evidence/stage3_FN1.json"}],
    )
    monkeypatch.setattr(guarded_pipeline, "build_ollama_candidate_followups", lambda _data_dir, _texts: [])
    monkeypatch.setattr(guarded_pipeline, "build_ollama_report_recommendations", recommendations)
    monkeypatch.setattr(
        guarded_pipeline, "production_save_report_sections_tool", lambda _data_dir, _disease: _SaveTool()
    )

    pipeline = guarded_pipeline.build_guarded_pipeline(
        _specs(),
        data_dir=str(tmp_path),
        default_model=DEFAULT_MODEL,
        disease="breast cancer",
        skip_evidence_assessor=True,
        provider="ollama",
    )

    asyncio.run(pipeline.ainvoke({"messages": []}))

    assert calls.count("report_writer") == 6
    assert saved_payloads[0]["candidate_followups"] == []
    audit = json.loads((tmp_path / "evidence" / "llm_enrichment_audit.json").read_text())
    assert audit["units"]["candidate.FN1"]["status"] == "fallback"
    assert audit["units"]["candidate.FN1"]["repair_attempt_count"] == 3
    assert "CANDIDATE_FOLLOWUP_UNSAFE_CLAIM" in audit["units"]["candidate.FN1"]["attempts"][0]["codes"]
    assert "CANDIDATE_FOLLOWUP_INVALID" not in audit["units"]["candidate.FN1"]["attempts"][0]["codes"]


def test_ollama_graph_state_omits_rejected_hypothesis_and_recommendation_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    hypothesis_secret = "hypothesis-rejected-model-text"
    recommendation_secret = "recommendation-rejected-model-text"

    class _RejectedRole(_RoleAgent):
        async def ainvoke(self, _input: dict[str, Any], config: Any = None) -> dict[str, Any]:
            _ = config, _input
            self.calls.append(self.name)
            text = hypothesis_secret if self.name == "hypothesis_writer" else recommendation_secret
            return {"messages": [AIMessage(content=text)]}

    class _SaveTool:
        @staticmethod
        def invoke(_arguments: dict[str, object]) -> str:
            return json.dumps({"saved": True})

    _install_fakes(monkeypatch, calls)
    monkeypatch.setattr(
        guarded_pipeline, "create_agent", lambda *, name, **_kwargs: _RejectedRole(name, calls)
    )
    monkeypatch.setattr(
        guarded_pipeline,
        "build_ollama_card_specs",
        lambda _data_dir: [_ollama_card_spec("mechanism", "Mechanism of Action", "EPHB4")],
    )
    monkeypatch.setattr(
        guarded_pipeline, "build_ollama_hypothesis_report", lambda _data_dir, _cards: {"hypotheses": []}
    )
    monkeypatch.setattr(guarded_pipeline, "save_hypothesis_report", _SaveTool())
    monkeypatch.setattr(
        guarded_pipeline, "build_ollama_candidate_followup_specs", lambda _data_dir: []
    )
    monkeypatch.setattr(
        guarded_pipeline, "build_ollama_candidate_followups", lambda _data_dir, _texts: []
    )
    monkeypatch.setattr(
        guarded_pipeline,
        "build_ollama_report_recommendations",
        lambda _data_dir, _texts: {
            "schema_version": "hybrid_report_sections/v1",
            "pipeline_recommendations": [
                {"text": "Prioritize EPHB4 validation before advancing target selection.", "supporting_sources": ["evidence/ot_EPHB4.json"]},
                {"text": "Evaluate EPHB4 evidence before planning follow-up studies.", "supporting_sources": ["evidence/ot_EPHB4.json"]},
            ],
        },
    )
    monkeypatch.setattr(
        guarded_pipeline, "production_save_report_sections_tool", lambda _data_dir, _disease: _SaveTool()
    )

    pipeline = guarded_pipeline.build_guarded_pipeline(
        _specs(),
        data_dir=str(tmp_path),
        default_model=DEFAULT_MODEL,
        disease="breast cancer",
        skip_evidence_assessor=True,
        provider="ollama",
    )

    state = asyncio.run(pipeline.ainvoke({"messages": []}))

    assert calls.count("hypothesis_writer") == 4
    assert calls.count("report_writer") == 8
    assert hypothesis_secret not in str(state)
    assert recommendation_secret not in str(state)
