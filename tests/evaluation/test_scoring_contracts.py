"""Tests for scorer interfaces and return contracts."""

from __future__ import annotations

from evaluation.scorers import (
    run_scorer,
    score_failure_recovery,
    score_hitl,
    score_known_biology,
    score_literature_grounding,
)


REQUIRED_KEYS = {"score", "passed", "rationale", "artifacts"}


def test_known_biology_scorer_contract():
    result = score_known_biology(["A", "B"], ["A", "C"]).as_dict()
    assert REQUIRED_KEYS <= set(result)
    assert 0.0 <= result["score"] <= 1.0


def test_literature_grounding_scorer_contract():
    result = score_literature_grounding(["1", "2"], ["2"]).as_dict()
    assert REQUIRED_KEYS <= set(result)
    assert result["passed"] is True


def test_hitl_scorer_contract():
    result = score_hitl({"interest_clusters": [1], "sel_factor": "factor_1"}).as_dict()
    assert REQUIRED_KEYS <= set(result)
    assert result["score"] == 1.0


def test_failure_recovery_scorer_contract():
    result = score_failure_recovery(
        {"fallback_triggered": True, "pipeline_completed": True}
    ).as_dict()
    assert REQUIRED_KEYS <= set(result)
    assert result["passed"] is True


def test_run_scorer_dispatches_by_name():
    result = run_scorer(
        "checklist_recall_precision",
        found_entities=["A"],
        expected_entities=["A"],
    ).as_dict()
    assert result["passed"] is True
