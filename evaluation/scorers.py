"""Scoring contract helpers for Core Suite categories."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class ScoreResult:
    score: float
    passed: bool
    rationale: str
    artifacts: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "passed": self.passed,
            "rationale": self.rationale,
            "artifacts": self.artifacts,
        }


def score_known_biology(
    found_entities: Sequence[str],
    expected_entities: Sequence[str],
    pass_threshold: float = 0.7,
) -> ScoreResult:
    found = {str(x).strip() for x in found_entities if str(x).strip()}
    expected = {str(x).strip() for x in expected_entities if str(x).strip()}

    if not expected:
        return ScoreResult(
            score=0.0,
            passed=False,
            rationale="Expected entity set is empty.",
            artifacts={"precision": 0.0, "recall": 0.0},
        )

    overlap = found & expected
    precision = len(overlap) / len(found) if found else 0.0
    recall = len(overlap) / len(expected)
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return ScoreResult(
        score=f1,
        passed=f1 >= pass_threshold,
        rationale="Known-biology overlap scored with F1.",
        artifacts={
            "precision": precision,
            "recall": recall,
            "overlap": sorted(overlap),
            "found_count": len(found),
            "expected_count": len(expected),
        },
    )


def score_literature_grounding(
    cited_pmids: Sequence[str],
    required_pmids: Sequence[str],
    pass_threshold: float = 0.7,
) -> ScoreResult:
    cited = {str(x).strip() for x in cited_pmids if str(x).strip()}
    required = {str(x).strip() for x in required_pmids if str(x).strip()}

    if not required:
        return ScoreResult(
            score=0.0,
            passed=False,
            rationale="Required PMID set is empty.",
            artifacts={"coverage": 0.0},
        )

    overlap = cited & required
    coverage = len(overlap) / len(required)
    return ScoreResult(
        score=coverage,
        passed=coverage >= pass_threshold,
        rationale="Literature grounding scored with required PMID coverage.",
        artifacts={
            "required_pmids": sorted(required),
            "cited_pmids": sorted(cited),
            "overlap": sorted(overlap),
            "coverage": coverage,
        },
    )


def score_hitl(
    trace: Mapping[str, Any],
    required_fields: Sequence[str] = ("interest_clusters", "sel_factor"),
    pass_threshold: float = 1.0,
) -> ScoreResult:
    present = 0
    details: dict[str, bool] = {}
    for field in required_fields:
        value = trace.get(field)
        ok = value not in (None, "", [], {}, ())
        details[field] = ok
        if ok:
            present += 1

    score = present / len(required_fields) if required_fields else 0.0
    return ScoreResult(
        score=score,
        passed=score >= pass_threshold,
        rationale="HITL completeness scored by required response fields.",
        artifacts={"field_presence": details},
    )


def score_failure_recovery(
    events: Mapping[str, Any],
    pass_threshold: float = 1.0,
) -> ScoreResult:
    fallback = bool(events.get("fallback_triggered"))
    completed = bool(events.get("pipeline_completed"))

    score = (float(fallback) + float(completed)) / 2.0
    return ScoreResult(
        score=score,
        passed=score >= pass_threshold,
        rationale="Failure recovery scored by fallback activation and completion.",
        artifacts={
            "fallback_triggered": fallback,
            "pipeline_completed": completed,
        },
    )


SCORERS = {
    "checklist_recall_precision": score_known_biology,
    "citation_alignment": score_literature_grounding,
    "hitl_trace_completeness": score_hitl,
    "fallback_recovery": score_failure_recovery,
}


def run_scorer(name: str, **kwargs: Any) -> ScoreResult:
    if name not in SCORERS:
        raise KeyError(f"Unknown scorer: {name}")
    return SCORERS[name](**kwargs)
