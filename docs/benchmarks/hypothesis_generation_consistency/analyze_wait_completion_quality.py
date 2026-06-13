from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _mean(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _numeric_values(rows: Sequence[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = row.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            values.append(float(value))
    return values


def score_row(row: dict[str, Any]) -> dict[str, Any]:
    validation = row.get("validation") or {}
    if not isinstance(validation, dict):
        validation = {}
    completion = validation.get("completion") or {}
    if not isinstance(completion, dict):
        completion = {}
    report_summary = validation.get("report_summary")
    if not isinstance(report_summary, dict):
        report_summary = None

    activated = row.get("activated_skill_names") or []
    if not isinstance(activated, list):
        activated = []
    activated_names = {str(name) for name in activated}

    topn_missing = None
    if report_summary is not None:
        topn_missing = report_summary.get("topn_missing")

    return {
        "model": row.get("model"),
        "mode": row.get("mode"),
        "port": row.get("port"),
        "run_id": row.get("run_id"),
        "returncode": row.get("returncode"),
        "completion_mode": row.get("completion_mode"),
        "activation_trace_valid": row.get("activation_trace_valid") is True,
        "activation_count": len(activated_names),
        "hypothesis_complete": completion.get("hypothesis_complete") is True,
        "validation_passed": validation.get("validation_passed") is True,
        "report_present": report_summary is not None,
        "hypothesis_count": (
            report_summary.get("hypothesis_count")
            if report_summary is not None
            else None
        ),
        "topn_missing_count": (
            len(topn_missing) if isinstance(topn_missing, list) else None
        ),
        "topn_coverage_pct": (
            report_summary.get("topn_coverage_pct")
            if report_summary is not None
            else None
        ),
        "evidence_coverage_pct": (
            report_summary.get("evidence_coverage_pct")
            if report_summary is not None
            else None
        ),
        "unverified_numeric_predictions": (
            report_summary.get("unverified_numeric_predictions")
            if report_summary is not None
            else None
        ),
    }


def aggregate_quality(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(f"{row.get('model')}::{row.get('mode')}", []).append(row)

    summary: dict[str, Any] = {}
    for key in sorted(groups):
        group_rows = groups[key]
        valid_trace_rows = [
            row for row in group_rows if row.get("activation_trace_valid") is True
        ]
        summary[key] = {
            "runs": len(group_rows),
            "completed_process_runs": sum(
                1 for row in group_rows if row.get("completion_mode") == "completed"
            ),
            "returncode_zero_runs": sum(
                1 for row in group_rows if row.get("returncode") == 0
            ),
            "valid_activation_trace_runs": len(valid_trace_rows),
            "hypothesis_complete_runs": sum(
                1 for row in group_rows if row.get("hypothesis_complete") is True
            ),
            "validation_passed_runs": sum(
                1 for row in group_rows if row.get("validation_passed") is True
            ),
            "report_present_runs": sum(
                1 for row in group_rows if row.get("report_present") is True
            ),
            "mean_activation_count": _mean(
                _numeric_values(valid_trace_rows, "activation_count")
            ),
            "mean_hypothesis_count": _mean(
                _numeric_values(group_rows, "hypothesis_count")
            ),
            "mean_evidence_coverage_pct": _mean(
                _numeric_values(group_rows, "evidence_coverage_pct")
            ),
            "topn_missing_total": int(
                sum(_numeric_values(group_rows, "topn_missing_count"))
            ),
            "unverified_numeric_total": int(
                sum(_numeric_values(group_rows, "unverified_numeric_predictions"))
            ),
        }
    return {"groups": summary}


def _format_cell(value: Any) -> str:
    if value is None:
        return "-"
    return str(value)


def render_markdown(rows: Sequence[dict[str, Any]], summary: dict[str, Any]) -> str:
    lines = [
        "# Wait-For-Completion Quality Analysis",
        "",
        (
            "| model | port | mode | completed | report | validation | hypotheses | "
            "TOP-N missing | evidence coverage | activation count |"
        ),
        "| --- | ---: | --- | --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            (
                "| {model} | {port} | {mode} | {completed} | {report} | "
                "{validation} | {hypotheses} | {topn_missing} | {evidence} | "
                "{activation_count} |"
            ).format(
                model=_format_cell(row.get("model")),
                port=_format_cell(row.get("port")),
                mode=_format_cell(row.get("mode")),
                completed=row.get("completion_mode") == "completed",
                report=row.get("report_present") is True,
                validation=row.get("validation_passed") is True,
                hypotheses=_format_cell(row.get("hypothesis_count")),
                topn_missing=_format_cell(row.get("topn_missing_count")),
                evidence=_format_cell(row.get("evidence_coverage_pct")),
                activation_count=_format_cell(row.get("activation_count")),
            )
        )

    lines.extend(["", "## Aggregate", "", "```json"])
    lines.append(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
    lines.extend(["```", ""])
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("benchmark_results")
    parser.add_argument("--output-json")
    parser.add_argument("--output-md")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    results_path = Path(args.benchmark_results).expanduser().resolve()
    payload = load_json(results_path)
    raw_trials = payload.get("trials", []) if isinstance(payload, dict) else []
    trials = raw_trials if isinstance(raw_trials, list) else []
    scored_rows = [score_row(row) for row in trials if isinstance(row, dict)]
    summary = aggregate_quality(scored_rows)

    output_json = (
        Path(args.output_json).expanduser()
        if args.output_json
        else results_path.with_name("wait_completion_quality.json")
    )
    output_md = (
        Path(args.output_md).expanduser()
        if args.output_md
        else results_path.with_name("wait_completion_quality.md")
    )

    output_payload = {
        "source": str(results_path),
        "rows": scored_rows,
        "aggregate": summary,
    }
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
