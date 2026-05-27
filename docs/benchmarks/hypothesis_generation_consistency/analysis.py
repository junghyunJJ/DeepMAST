from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher
from itertools import combinations
from statistics import mean
from typing import Any


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _sorted_strings(values: Any) -> list[str]:
    return sorted({str(v).strip() for v in _as_list(values) if str(v).strip()})


def jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 1.0
    return len(left & right) / len(union)


def text_similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, left or "", right or "").ratio()


def summarize_report(report: dict[str, Any]) -> dict[str, Any]:
    hypotheses = _as_list(report.get("hypotheses"))
    category_counts: Counter[str] = Counter()
    genes: set[str] = set()
    refs: set[str] = set()
    titles: list[str] = []
    core_claims: list[str] = []

    for hyp in hypotheses:
        if not isinstance(hyp, dict):
            continue
        category = str(hyp.get("category") or "").strip()
        if category:
            category_counts[category] += 1
        entities = (
            hyp.get("biological_entities")
            if isinstance(hyp.get("biological_entities"), dict)
            else {}
        )
        genes.update(g.upper() for g in _sorted_strings(entities.get("genes")))
        refs.update(_sorted_strings(hyp.get("evidence_references")))
        title = str(hyp.get("title") or "").strip()
        claim = str(hyp.get("core_claim") or "").strip()
        if title:
            titles.append(title)
        if claim:
            core_claims.append(claim)

    topn = (
        report.get("topn_coverage")
        if isinstance(report.get("topn_coverage"), dict)
        else {}
    )
    grounding = (
        report.get("prediction_grounding_summary")
        if isinstance(report.get("prediction_grounding_summary"), dict)
        else {}
    )
    return {
        "schema_version": report.get("schema_version"),
        "hypothesis_count": len(hypotheses),
        "category_counts": dict(sorted(category_counts.items())),
        "covered_genes": sorted(genes),
        "evidence_refs": sorted(refs),
        "titles_joined": "\n".join(titles),
        "core_claims_joined": "\n".join(core_claims),
        "topn_covered": _sorted_strings(topn.get("covered")),
        "topn_missing": _sorted_strings(topn.get("missing")),
        "topn_coverage_pct": topn.get("coverage_pct"),
        "evidence_coverage_pct": report.get("evidence_coverage_pct"),
        "unverified_numeric_predictions": int(grounding.get("unverified") or 0),
    }


def _successful_summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row["report_summary"]
        for row in rows
        if row.get("success") and isinstance(row.get("report_summary"), dict)
    ]


def _report_summary(row: dict[str, Any]) -> dict[str, Any]:
    summary = row.get("report_summary")
    return summary if isinstance(summary, dict) else {}


def _mean_pairwise(
    summaries: list[dict[str, Any]],
    key: str,
    mode: str,
) -> float | None:
    if len(summaries) < 2:
        return None
    scores: list[float] = []
    for left, right in combinations(summaries, 2):
        if mode == "set":
            scores.append(jaccard(set(left.get(key, [])), set(right.get(key, []))))
        elif mode == "text":
            scores.append(text_similarity(str(left.get(key, "")), str(right.get(key, ""))))
        else:
            raise ValueError(f"unsupported pairwise mode: {mode}")
    return round(mean(scores), 4) if scores else None


def aggregate_trial_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    successes = [row for row in rows if row.get("success")]
    validation_passes = [row for row in rows if row.get("validation_passed")]
    summaries = _successful_summaries(rows)
    count_values = sorted({int(s.get("hypothesis_count") or 0) for s in summaries})
    category_distributions = [s.get("category_counts", {}) for s in summaries]
    return {
        "total_runs": total,
        "successful_runs": len(successes),
        "validation_passed_runs": len(validation_passes),
        "success_rate": round(len(successes) / total, 4) if total else 0.0,
        "validation_pass_rate": round(len(validation_passes) / total, 4) if total else 0.0,
        "hypothesis_count_values": count_values,
        "category_distributions": category_distributions,
        "mean_pairwise_gene_jaccard": _mean_pairwise(summaries, "covered_genes", "set"),
        "mean_pairwise_ref_jaccard": _mean_pairwise(summaries, "evidence_refs", "set"),
        "mean_pairwise_title_similarity": _mean_pairwise(
            summaries,
            "titles_joined",
            "text",
        ),
        "mean_pairwise_core_claim_similarity": _mean_pairwise(
            summaries,
            "core_claims_joined",
            "text",
        ),
        "topn_missing_by_run": {
            row["run_id"]: _report_summary(row).get("topn_missing", [])
            for row in rows
            if row.get("run_id")
        },
        "unverified_numeric_predictions_by_run": {
            row["run_id"]: _report_summary(row).get("unverified_numeric_predictions")
            for row in rows
            if row.get("run_id")
        },
    }
