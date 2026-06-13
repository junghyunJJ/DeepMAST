from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable, Sequence


EXPECTED_ACTIVE_SKILLS = (
    "drug-target-hypothesis",
    "opentargets-database",
    "chembl-database",
    "compare-census-gene-pair-by-cell-type",
    "string-database",
)
EXPECTED_INACTIVE_SKILLS = (
    "gwas-database",
    "biomedical-literature-search",
    "html-report-generator",
)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _activated_skill_names(row: dict[str, Any]) -> list[str]:
    names = row.get("activated_skill_names")
    if names is None:
        payload = row.get("activation_trace_payload")
        if isinstance(payload, dict):
            names = payload.get("activated_skill_names")
    if not isinstance(names, list):
        return []
    return sorted({str(name) for name in names})


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _count_values(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def score_row(row: dict[str, Any]) -> dict[str, Any]:
    valid_trace = row.get("activation_trace_valid") is True
    activated = set(_activated_skill_names(row)) if valid_trace else set()
    expected_active = set(EXPECTED_ACTIVE_SKILLS)
    expected_inactive = set(EXPECTED_INACTIVE_SKILLS)

    true_positive = len(activated.intersection(expected_active))
    false_positive = len(activated.intersection(expected_inactive))
    false_negative = len(expected_active - activated)
    true_negative = len(expected_inactive - activated)

    precision = _ratio(true_positive, true_positive + false_positive)
    recall = _ratio(true_positive, true_positive + false_negative)
    specificity = _ratio(true_negative, true_negative + false_positive)
    f1 = _ratio(2 * precision * recall, precision + recall)

    missing_active = sorted(expected_active - activated)
    overactivated_inactive = sorted(activated.intersection(expected_inactive))
    return {
        "model": row.get("model"),
        "mode": row.get("mode"),
        "port": row.get("port"),
        "run_id": row.get("run_id"),
        "valid_trace": valid_trace,
        "activated_skill_names": sorted(activated),
        "missing_active_skills": missing_active,
        "overactivated_inactive_skills": overactivated_inactive,
        "selective_exact_match": valid_trace
        and not missing_active
        and not overactivated_inactive,
        "precision": precision,
        "recall": recall,
        "specificity": specificity,
        "f1": f1,
    }


def _mean(rows: Sequence[dict[str, Any]], key: str) -> float:
    if not rows:
        return 0.0
    return sum(float(row.get(key, 0.0)) for row in rows) / len(rows)


def aggregate(scored_rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in scored_rows:
        groups.setdefault(f"{row.get('model')}::{row.get('mode')}", []).append(row)

    summary: dict[str, Any] = {}
    for key, group_rows in groups.items():
        valid_rows = [row for row in group_rows if row.get("valid_trace") is True]
        runs = len(group_rows)
        summary[key] = {
            "runs": runs,
            "valid_trace_runs": len(valid_rows),
            "invalid_trace_runs": runs - len(valid_rows),
            "selective_exact_matches": sum(
                1 for row in group_rows if row.get("selective_exact_match") is True
            ),
            "mean_precision": _mean(valid_rows, "precision"),
            "mean_recall": _mean(valid_rows, "recall"),
            "mean_specificity": _mean(valid_rows, "specificity"),
            "mean_f1": _mean(valid_rows, "f1"),
            "missing_active_counts": _count_values(
                skill
                for row in valid_rows
                for skill in row.get("missing_active_skills", [])
            ),
            "overactivated_inactive_counts": _count_values(
                skill
                for row in valid_rows
                for skill in row.get("overactivated_inactive_skills", [])
            ),
        }
    return {"groups": summary}


def render_markdown(
    scored_rows: Sequence[dict[str, Any]],
    summary: dict[str, Any],
) -> str:
    lines = [
        "# Selective8 Activation Analysis",
        "",
        (
            "| model | port | mode | trace | exact | precision | recall | "
            "specificity | f1 | missing active | overactivated inactive |"
        ),
        "| --- | ---: | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in scored_rows:
        lines.append(
            (
                "| {model} | {port} | {mode} | {trace} | {exact} | {precision:.3f} | "
                "{recall:.3f} | {specificity:.3f} | {f1:.3f} | {missing} | {extra} |"
            ).format(
                model=row.get("model"),
                port=row.get("port"),
                mode=row.get("mode"),
                trace=row.get("valid_trace"),
                exact=row.get("selective_exact_match"),
                precision=float(row.get("precision", 0.0)),
                recall=float(row.get("recall", 0.0)),
                specificity=float(row.get("specificity", 0.0)),
                f1=float(row.get("f1", 0.0)),
                missing=", ".join(row.get("missing_active_skills", [])) or "-",
                extra=", ".join(row.get("overactivated_inactive_skills", [])) or "-",
            )
        )
    lines.extend(["", "## Aggregate", "", "```json"])
    lines.append(json.dumps(summary, indent=2, ensure_ascii=False))
    lines.extend(["```", ""])
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("benchmark_results")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    results_path = Path(args.benchmark_results).expanduser().resolve()
    payload = load_json(results_path)
    scored_rows = [score_row(row) for row in payload.get("trials", [])]
    summary = aggregate(scored_rows)
    output_payload = {
        "source": str(results_path),
        "expected_active_skills": list(EXPECTED_ACTIVE_SKILLS),
        "expected_inactive_skills": list(EXPECTED_INACTIVE_SKILLS),
        "rows": scored_rows,
        "aggregate": summary,
    }

    output_json = results_path.with_name("selective_activation_summary.json")
    output_md = results_path.with_name("selective_activation_summary.md")
    output_json.write_text(
        json.dumps(output_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    output_md.write_text(render_markdown(scored_rows, summary), encoding="utf-8")
    print(f"wrote {output_json}")
    print(f"wrote {output_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
