from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from src.agents.drug_target.tools.hypothesis_schema import save_hypothesis_report


def _write_hypothesis_evidence(tmp_path: Path) -> Path:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "assessment_results.json").write_text(
        json.dumps({"stage3_candidates": [{"gene": "CD4"}, {"gene": "FN1"}, {"gene": "MUC1"}]}),
        encoding="utf-8",
    )
    (evidence_dir / "stage1_filter_results.json").write_text(
        json.dumps([
            {"ligand": "FN1", "receptor": "CD4", "passed": True},
            {"ligand": "FN1", "receptor": "SDC2", "passed": True},
        ]),
        encoding="utf-8",
    )
    for name in (
        "stage1_FN1--CD4.json",
        "stage1_FN1--SDC2.json",
        "stage3_CD4.json",
        "stage3_FN1.json",
        "stage3_MUC1.json",
        "ot_MUC1.json",
    ):
        (evidence_dir / name).write_text("{}", encoding="utf-8")
    return tmp_path


def _hypothesis(rank: int, category: str, refs: list[str], genes: list[str]) -> dict:
    title = (
        "Actionability follow-up hypothesis"
        if category == "Therapeutic Strategy"
        else f"{category} hypothesis"
    )
    return {
        "rank": rank,
        "title": title,
        "category": category,
        "gap_type": "none",
        "core_claim": f"{title} is testable.",
        "evidence_references": refs,
        "contrast_references": [],
        "biological_entities": {
            "genes": genes,
            "pathways": [],
            "cell_types": [],
            "drugs": [],
        },
        "falsifiable_prediction": "Measurable qualitative response change.",
        "validation_approach": "Run perturbation assay.",
        "scores": {
            "evidence_coverage": 0.8,
            "specificity": 0.8,
            "novelty": 0.7,
            "actionability": 0.7,
            "composite": 0.75,
        },
    }


def _valid_report() -> dict:
    return {
        "schema_version": "hypothesis_report.v2",
        "disease": "IPF",
        "hypotheses_generated": 4,
        "hypotheses_retained": 4,
        "hypotheses": [
            _hypothesis(1, "Mechanism of Action", ["stage1_FN1--CD4.json"], ["FN1", "CD4"]),
            {
                **_hypothesis(
                    2,
                    "Therapeutic Strategy",
                    ["stage3_FN1.json", "stage3_MUC1.json", "ot_MUC1.json"],
                    ["FN1", "MUC1"],
                ),
                "core_claim": "MUC1-associated FN1 actionability follow-up is testable.",
            },
            _hypothesis(3, "Cross-Target Interaction", ["stage1_FN1--SDC2.json"], ["FN1", "SDC2"]),
            _hypothesis(4, "Novel Pathway", ["stage3_CD4.json"], ["CD4"]),
        ],
        "gap_analysis": {},
    }


def _bad_muc1_rejection_report() -> dict:
    report = _valid_report()
    report["hypotheses"][0].update({
        "title": "EZR--MUC1 direct axis hypothesis",
        "core_claim": "The unsupported EZR--MUC1 axis is testable in IPF.",
        "falsifiable_prediction": "The EZR--MUC1 axis will change qualitative epithelial response.",
        "evidence_references": ["stage1_FN1--CD4.json"],
        "biological_entities": {
            "genes": ["EZR", "MUC1"],
            "pathways": [],
            "cell_types": [],
            "drugs": [],
        },
    })
    return report


def _invalid_numeric_report() -> dict:
    report = _valid_report()
    report["hypotheses"][0]["falsifiable_prediction"] = (
        "The perturbation will reduce profibrotic activation by 40% in 7 days."
    )
    return report


def _write_raw_hypothesis_report(data_dir: Path, report: dict) -> None:
    (data_dir / "evidence" / "hypothesis_report.json").write_text(
        json.dumps(report),
        encoding="utf-8",
    )


def _state(data_dir: Path) -> dict:
    return {
        "messages": [],
        "data_dir": str(data_dir),
        "disease": "idiopathic pulmonary fibrosis",
        "featured_lr_pairs": None,
        "report_finalization_error": None,
        "evidence_truncated": False,
    }


async def _fake_finalize(state, config=None):
    Path(state["data_dir"], "drug.md").write_text("# finalized", encoding="utf-8")
    return {"report_finalization_error": None, "evidence_truncated": False}


def _patch_finalize(monkeypatch, func=_fake_finalize) -> None:
    monkeypatch.setattr("src.agents.drug_target.finalize_report.finalize_report", func)


@pytest.mark.asyncio
async def test_valid_hypothesis_report_skips_retry_and_finalizes(tmp_path: Path, monkeypatch) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)

    async def initial_ainvoke(inp, config=None):
        result = json.loads(
            save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": _valid_report()})
        )
        assert result["saved"] is True
        return {"messages": [AIMessage(content="EVIDENCE_PIPELINE_COMPLETE")]}

    calls = []

    def fake_create_agent(cfg):
        calls.append(cfg)
        return SimpleNamespace(ainvoke=initial_ainvoke), None

    monkeypatch.setattr("src.agents.drug_target.agent.create_drug_target_agent", fake_create_agent)
    _patch_finalize(monkeypatch)

    from src.agents.drug_target.super_graph import build_drug_target_super_graph

    final_state = await build_drug_target_super_graph().ainvoke(_state(data_dir))

    assert len(calls) == 1
    assert final_state["hypothesis_quality_valid"] is True
    assert final_state["hypothesis_retry_attempted"] is False
    assert final_state["hypothesis_retry_attempts"] == 0
    assert (data_dir / "drug.md").exists()


@pytest.mark.asyncio
async def test_missing_report_retries_hypothesis_writer_once(tmp_path: Path, monkeypatch) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    retry_messages: list[str] = []

    async def initial_ainvoke(inp, config=None):
        return {"messages": [AIMessage(content="EVIDENCE_PIPELINE_COMPLETE")]}

    async def retry_ainvoke(inp, config=None):
        retry_messages.append(inp["messages"][0]["content"])
        result = json.loads(
            save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": _valid_report()})
        )
        assert result["saved"] is True
        return {"messages": [AIMessage(content="Hypothesis fixup complete.")]}

    runnables = [
        SimpleNamespace(ainvoke=initial_ainvoke),
        SimpleNamespace(ainvoke=retry_ainvoke),
    ]

    def fake_create_agent(cfg):
        return runnables.pop(0), None

    monkeypatch.setattr("src.agents.drug_target.agent.create_drug_target_agent", fake_create_agent)
    _patch_finalize(monkeypatch)

    from src.agents.drug_target.super_graph import build_drug_target_super_graph

    final_state = await build_drug_target_super_graph().ainvoke(_state(data_dir))

    assert final_state["hypothesis_quality_valid"] is True
    assert final_state["hypothesis_retry_attempted"] is True
    assert final_state["hypothesis_retry_status"] == "success"
    assert final_state["hypothesis_retry_attempts"] == 1
    assert len(retry_messages) == 1
    assert "Retry attempt 1 of 3" in retry_messages[0]
    assert 'task(subagent_type="hypothesis_writer"' in retry_messages[0]
    assert "Do not re-run evidence_assessor" in retry_messages[0]
    assert "Quality validation failures to fix before saving" in retry_messages[0]
    assert "HYPOTHESIS_REPORT_MISSING" in retry_messages[0]
    assert retry_messages[0].index("HYPOTHESIS_REPORT_MISSING") < retry_messages[0].index(
        '")\n\nFor auditability'
    )
    assert (data_dir / "drug.md").exists()


@pytest.mark.asyncio
async def test_missing_report_retry_receives_last_rejection_details(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    sidecar = data_dir / "evidence" / "hypothesis_report_last_rejection.json"
    retry_messages: list[str] = []

    async def initial_ainvoke(inp, config=None):
        result = json.loads(
            save_hypothesis_report.invoke({
                "data_dir": str(data_dir),
                "report": _bad_muc1_rejection_report(),
            })
        )
        assert result["saved"] is False
        assert sidecar.exists()
        assert not (data_dir / "evidence" / "hypothesis_report.json").exists()
        return {"messages": [AIMessage(content="EVIDENCE_PIPELINE_COMPLETE")]}

    async def retry_ainvoke(inp, config=None):
        retry_messages.append(inp["messages"][0]["content"])
        result = json.loads(
            save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": _valid_report()})
        )
        assert result["saved"] is True
        return {"messages": [AIMessage(content="Hypothesis fixup complete.")]}

    runnables = [
        SimpleNamespace(ainvoke=initial_ainvoke),
        SimpleNamespace(ainvoke=retry_ainvoke),
    ]

    def fake_create_agent(cfg):
        return runnables.pop(0), None

    monkeypatch.setattr("src.agents.drug_target.agent.create_drug_target_agent", fake_create_agent)
    _patch_finalize(monkeypatch)

    from src.agents.drug_target.super_graph import build_drug_target_super_graph

    final_state = await build_drug_target_super_graph().ainvoke(_state(data_dir))

    assert len(retry_messages) == 1
    retry_message = retry_messages[0]
    assert "HYPOTHESIS_LAST_SAVE_REJECTION" in retry_message
    assert "GENE_LEVEL_EVIDENCE_REFERENCE_MISSING" in retry_message
    assert "Direct pair-axis repair" in retry_message
    assert "EZR--MUC1" in retry_message
    assert "MUC1: ot_MUC1.json, stage3_MUC1.json" in retry_message
    assert final_state["hypothesis_quality_valid"] is True
    assert final_state["hypothesis_retry_status"] == "success"
    assert final_state["hypothesis_retry_attempts"] == 1
    assert (data_dir / "drug.md").exists()
    assert not sidecar.exists()


@pytest.mark.asyncio
async def test_retry_failure_hard_blocks_finalize(tmp_path: Path, monkeypatch) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    monkeypatch.setenv("DRUG_TARGET_HYPOTHESIS_MAX_QUALITY_RETRIES", "1")

    async def initial_ainvoke(inp, config=None):
        return {"messages": [AIMessage(content="EVIDENCE_PIPELINE_COMPLETE")]}

    async def retry_ainvoke(inp, config=None):
        return {"messages": [AIMessage(content="Hypothesis fixup complete.")]}

    runnables = [
        SimpleNamespace(ainvoke=initial_ainvoke),
        SimpleNamespace(ainvoke=retry_ainvoke),
    ]

    def fake_create_agent(cfg):
        return runnables.pop(0), None

    async def fail_if_called(state, config=None):
        raise AssertionError("finalize_report must not run after failed hypothesis quality")

    monkeypatch.setattr("src.agents.drug_target.agent.create_drug_target_agent", fake_create_agent)
    _patch_finalize(monkeypatch, fail_if_called)

    from src.agents.drug_target.super_graph import build_drug_target_super_graph

    final_state = await build_drug_target_super_graph().ainvoke(_state(data_dir))

    assert final_state["hypothesis_quality_valid"] is False
    assert final_state["hypothesis_retry_attempted"] is True
    assert final_state["hypothesis_retry_status"] == "failed"
    assert final_state["hypothesis_retry_attempts"] == 1
    assert final_state["report_finalization_error"].startswith("HYPOTHESIS_QUALITY_GATE_FAILED")
    assert not (data_dir / "drug.md").exists()


@pytest.mark.asyncio
async def test_retry_timeout_accepts_valid_report_saved_before_timeout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    monkeypatch.setenv("DRUG_TARGET_HYPOTHESIS_MAX_QUALITY_RETRIES", "1")

    async def save_then_timeout(state, config, quality_errors, *, attempt, max_attempts):
        result = json.loads(
            save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": _valid_report()})
        )
        assert result["saved"] is True
        raise TimeoutError("retry timed out after saving")

    monkeypatch.setattr(
        "src.agents.drug_target.super_graph._invoke_hypothesis_retry",
        save_then_timeout,
    )

    from src.agents.drug_target.super_graph import validate_and_maybe_retry_hypothesis

    result = await validate_and_maybe_retry_hypothesis(
        _state(data_dir),
        {"recursion_limit": 10000, "configurable": {}},
    )

    assert result["hypothesis_quality_valid"] is True
    assert result["hypothesis_retry_attempted"] is True
    assert result["hypothesis_retry_attempts"] == 1
    assert result["hypothesis_retry_status"] == "success_after_timeout"
    assert result["hypothesis_retry_error"] is None
    assert "report_finalization_error" not in result


@pytest.mark.asyncio
async def test_retry_disabled_hard_blocks_finalize(tmp_path: Path, monkeypatch) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    monkeypatch.setenv("DRUG_TARGET_GRAPH_HYPOTHESIS_RETRY", "0")

    async def initial_ainvoke(inp, config=None):
        return {"messages": [AIMessage(content="EVIDENCE_PIPELINE_COMPLETE")]}

    def fake_create_agent(cfg):
        return SimpleNamespace(ainvoke=initial_ainvoke), None

    async def fail_if_called(state, config=None):
        raise AssertionError("finalize_report must not run when quality gate fails")

    monkeypatch.setattr("src.agents.drug_target.agent.create_drug_target_agent", fake_create_agent)
    _patch_finalize(monkeypatch, fail_if_called)

    from src.agents.drug_target.super_graph import build_drug_target_super_graph

    final_state = await build_drug_target_super_graph().ainvoke(_state(data_dir))

    assert final_state["hypothesis_quality_valid"] is False
    assert final_state["hypothesis_retry_attempted"] is False
    assert final_state["hypothesis_retry_status"] == "disabled"
    assert final_state["hypothesis_retry_attempts"] == 0
    assert final_state["report_finalization_error"].startswith("HYPOTHESIS_QUALITY_GATE_FAILED")
    assert not (data_dir / "drug.md").exists()


@pytest.mark.asyncio
async def test_numeric_quality_failure_succeeds_on_second_retry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    retry_messages: list[str] = []

    async def initial_ainvoke(inp, config=None):
        _write_raw_hypothesis_report(data_dir, _invalid_numeric_report())
        return {"messages": [AIMessage(content="EVIDENCE_PIPELINE_COMPLETE")]}

    async def retry_invalid_ainvoke(inp, config=None):
        retry_messages.append(inp["messages"][0]["content"])
        _write_raw_hypothesis_report(data_dir, _invalid_numeric_report())
        return {"messages": [AIMessage(content="Hypothesis fixup complete.")]}

    async def retry_valid_ainvoke(inp, config=None):
        retry_messages.append(inp["messages"][0]["content"])
        result = json.loads(
            save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": _valid_report()})
        )
        assert result["saved"] is True
        return {"messages": [AIMessage(content="Hypothesis fixup complete.")]}

    runnables = [
        SimpleNamespace(ainvoke=initial_ainvoke),
        SimpleNamespace(ainvoke=retry_invalid_ainvoke),
        SimpleNamespace(ainvoke=retry_valid_ainvoke),
    ]

    def fake_create_agent(cfg):
        return runnables.pop(0), None

    monkeypatch.setattr("src.agents.drug_target.agent.create_drug_target_agent", fake_create_agent)
    _patch_finalize(monkeypatch)

    from src.agents.drug_target.super_graph import build_drug_target_super_graph

    final_state = await build_drug_target_super_graph().ainvoke(_state(data_dir))

    assert final_state["hypothesis_quality_valid"] is True
    assert final_state["hypothesis_retry_attempted"] is True
    assert final_state["hypothesis_retry_status"] == "success"
    assert final_state["hypothesis_retry_attempts"] == 2
    assert len(retry_messages) == 2
    assert "Retry attempt 1 of 3" in retry_messages[0]
    assert "Retry attempt 2 of 3" in retry_messages[1]
    assert "UNVERIFIED_NUMERIC_PREDICTION" in retry_messages[1]
    assert "unsupported percentages" in retry_messages[1]
    assert (data_dir / "drug.md").exists()


@pytest.mark.asyncio
async def test_retry_stops_after_configured_max_attempts_without_finalize(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    monkeypatch.setenv("DRUG_TARGET_HYPOTHESIS_MAX_QUALITY_RETRIES", "2")
    retry_messages: list[str] = []

    async def initial_ainvoke(inp, config=None):
        return {"messages": [AIMessage(content="EVIDENCE_PIPELINE_COMPLETE")]}

    async def retry_ainvoke(inp, config=None):
        retry_messages.append(inp["messages"][0]["content"])
        _write_raw_hypothesis_report(data_dir, _invalid_numeric_report())
        return {"messages": [AIMessage(content="Hypothesis fixup complete.")]}

    runnables = [
        SimpleNamespace(ainvoke=initial_ainvoke),
        SimpleNamespace(ainvoke=retry_ainvoke),
        SimpleNamespace(ainvoke=retry_ainvoke),
    ]

    def fake_create_agent(cfg):
        return runnables.pop(0), None

    async def fail_if_called(state, config=None):
        raise AssertionError("finalize_report must not run after failed hypothesis quality")

    monkeypatch.setattr("src.agents.drug_target.agent.create_drug_target_agent", fake_create_agent)
    _patch_finalize(monkeypatch, fail_if_called)

    from src.agents.drug_target.super_graph import build_drug_target_super_graph

    final_state = await build_drug_target_super_graph().ainvoke(_state(data_dir))

    assert final_state["hypothesis_quality_valid"] is False
    assert final_state["hypothesis_retry_attempted"] is True
    assert final_state["hypothesis_retry_status"] == "failed"
    assert final_state["hypothesis_retry_attempts"] == 2
    assert final_state["report_finalization_error"].startswith("HYPOTHESIS_QUALITY_GATE_FAILED")
    assert len(retry_messages) == 2
    assert "Retry attempt 1 of 2" in retry_messages[0]
    assert "Retry attempt 2 of 2" in retry_messages[1]
    assert not (data_dir / "drug.md").exists()
