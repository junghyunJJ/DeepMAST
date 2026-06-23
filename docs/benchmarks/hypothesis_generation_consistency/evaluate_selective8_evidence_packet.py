"""Evaluate selective8 runs for validation-gated evidence-packet completeness."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable, Sequence


MODE_LABELS = {
    "middleware_plus_governor": "Governor",
    "middleware_plus_activator": "Activator",
    "middleware_only": "Middleware only",
}
MODE_ORDER = tuple(MODE_LABELS)
REQUIRED_SKILLS = (
    "opentargets-database",
    "chembl-database",
    "compare-census-gene-pair-by-cell-type",
    "string-database",
)
NEGATIVE_CONTROL_SKILLS = (
    "gwas-database",
    "biomedical-literature-search",
    "html-report-generator",
)
EXCLUDED_SKILLS = ("drug-target-hypothesis",)
DEFAULT_STEM = "evidence_packet_scores"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")


def benchmark_path(result_path: Path) -> Path:
    resolved = result_path.expanduser().resolve()
    if resolved.is_dir():
        return resolved / "benchmark_results.json"
    return resolved


def output_dir_for(result_path: Path) -> Path:
    resolved = result_path.expanduser().resolve()
    return resolved if resolved.is_dir() else resolved.parent


def output_paths(output_dir: Path, stem: str) -> dict[str, Path]:
    return {
        "json": output_dir / f"{stem}.json",
        "jsonl": output_dir / f"{stem}.jsonl",
        "md": output_dir / f"{stem}.md",
    }


def validation_passed(trial: dict[str, Any]) -> bool:
    validation = trial.get("validation")
    return isinstance(validation, dict) and validation.get("validation_passed") is True


def report_path_for_trial(trial: dict[str, Any]) -> Path | None:
    validation = trial.get("validation")
    if isinstance(validation, dict) and validation.get("hypothesis_report"):
        return Path(str(validation["hypothesis_report"]))
    workspace = trial.get("workspace")
    if workspace:
        return Path(str(workspace)) / "evidence" / "hypothesis_report.json"
    return None


def report_present(trial: dict[str, Any]) -> bool:
    path = report_path_for_trial(trial)
    return path.exists() if path is not None else False


def activated_skill_names(trial: dict[str, Any]) -> list[str]:
    names = trial.get("activated_skill_names")
    if names is None:
        payload = trial.get("activation_trace_payload")
        if isinstance(payload, dict):
            names = payload.get("activated_skill_names")
    if not isinstance(names, list):
        return []
    return sorted({str(name) for name in names})


def count_values(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def score_trial(trial: dict[str, Any]) -> dict[str, Any]:
    valid_trace = trial.get("activation_trace_valid") is True
    activated = set(activated_skill_names(trial)) if valid_trace else set()
    required = set(REQUIRED_SKILLS)
    negative = set(NEGATIVE_CONTROL_SKILLS)
    required_hits = sorted(activated & required)
    missing_required = sorted(required - activated)
    negative_controls = sorted(activated & negative)
    activation_complete = (
        valid_trace
        and len(required_hits) == len(REQUIRED_SKILLS)
        and not negative_controls
    )
    validation = validation_passed(trial)
    report_path = report_path_for_trial(trial)

    return {
        "model": trial.get("model"),
        "mode": trial.get("mode"),
        "mode_label": MODE_LABELS.get(str(trial.get("mode")), str(trial.get("mode"))),
        "port": trial.get("port"),
        "repeat": trial.get("repeat"),
        "run_id": trial.get("run_id"),
        "activation_trace_valid": valid_trace,
        "validation_passed": validation,
        "report_present": report_present(trial),
        "report_path": str(report_path) if report_path is not None else None,
        "activated_skill_names": sorted(activated),
        "excluded_skills_present": sorted(activated & set(EXCLUDED_SKILLS)),
        "required_skill_hits": required_hits,
        "required_skill_hit_count": len(required_hits),
        "missing_required_skills": missing_required,
        "negative_control_skills": negative_controls,
        "negative_control_count": len(negative_controls),
        "complete_evidence_packet_activation_only": activation_complete,
        "complete_evidence_packet_validated": activation_complete and validation,
    }


def mean(rows: Sequence[dict[str, Any]], key: str) -> float:
    if not rows:
        return 0.0
    return sum(float(row.get(key, 0) or 0) for row in rows) / len(rows)


def count_true(rows: Sequence[dict[str, Any]], key: str) -> int:
    return sum(1 for row in rows if row.get(key) is True)


def aggregate_rows(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("mode")), []).append(row)

    ordered_modes = [mode for mode in MODE_ORDER if mode in grouped]
    ordered_modes.extend(sorted(mode for mode in grouped if mode not in MODE_ORDER))
    groups: dict[str, Any] = {}
    for mode in ordered_modes:
        group_rows = grouped[mode]
        runs = len(group_rows)
        activation_complete = count_true(
            group_rows,
            "complete_evidence_packet_activation_only",
        )
        validated_complete = count_true(
            group_rows,
            "complete_evidence_packet_validated",
        )
        groups[mode] = {
            "label": MODE_LABELS.get(mode, mode),
            "runs": runs,
            "valid_trace_runs": count_true(group_rows, "activation_trace_valid"),
            "validation_passed_runs": count_true(group_rows, "validation_passed"),
            "report_present_runs": count_true(group_rows, "report_present"),
            "mean_required_skill_hit_count": mean(
                group_rows,
                "required_skill_hit_count",
            ),
            "complete_evidence_packet_activation_only_count": activation_complete,
            "complete_evidence_packet_activation_only_rate": activation_complete / runs
            if runs
            else 0.0,
            "complete_evidence_packet_validated_count": validated_complete,
            "complete_evidence_packet_validated_rate": validated_complete / runs
            if runs
            else 0.0,
            "negative_control_intrusion_count": sum(
                1 for row in group_rows if int(row.get("negative_control_count", 0)) > 0
            ),
            "required_skill_hit_counts": {
                skill: sum(
                    1 for row in group_rows if skill in row.get("required_skill_hits", [])
                )
                for skill in REQUIRED_SKILLS
            },
            "missing_required_counts": count_values(
                skill
                for row in group_rows
                for skill in row.get("missing_required_skills", [])
            ),
            "negative_control_counts": count_values(
                skill
                for row in group_rows
                for skill in row.get("negative_control_skills", [])
            ),
        }
    return {"groups": groups}


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Selective8 Evidence Packet Evaluation",
        "",
        f"- Source: `{payload['source']}`",
        "- Primary endpoint: `complete_evidence_packet_validated`",
        "- Definition: valid trace, all required evidence skills activated, no negative-control skills activated, and final validation passed.",
        "",
        "## Mode Summary",
        "",
        "| mode | runs | valid trace | validation pass | report | required hits | activation complete | validated complete | negative intrusion |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for group in payload["aggregate"]["groups"].values():
        lines.append(
            "| {label} | {runs} | {trace} | {valid} | {report} | {hits:.2f} | {activation} ({activation_rate:.1%}) | {validated} ({validated_rate:.1%}) | {negative} |".format(
                label=group["label"],
                runs=group["runs"],
                trace=group["valid_trace_runs"],
                valid=group["validation_passed_runs"],
                report=group["report_present_runs"],
                hits=float(group["mean_required_skill_hit_count"]),
                activation=group["complete_evidence_packet_activation_only_count"],
                activation_rate=float(
                    group["complete_evidence_packet_activation_only_rate"]
                ),
                validated=group["complete_evidence_packet_validated_count"],
                validated_rate=float(group["complete_evidence_packet_validated_rate"]),
                negative=group["negative_control_intrusion_count"],
            )
        )

    lines.extend(
        [
            "",
            "## Required Skill Hits",
            "",
            "| mode | Open Targets | ChEMBL | Census gene-pair | STRING |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for group in payload["aggregate"]["groups"].values():
        hits = group["required_skill_hit_counts"]
        lines.append(
            "| {label} | {ot} | {chembl} | {census} | {string} |".format(
                label=group["label"],
                ot=hits["opentargets-database"],
                chembl=hits["chembl-database"],
                census=hits["compare-census-gene-pair-by-cell-type"],
                string=hits["string-database"],
            )
        )

    lines.extend(
        [
            "",
            "## Run Rows",
            "",
            "| mode | repeat | run | trace | valid | hits | missing | negative | activation complete | validated complete |",
            "| --- | ---: | --- | --- | --- | ---: | --- | --- | --- | --- |",
        ]
    )
    for row in payload["rows"]:
        lines.append(
            "| {mode} | {repeat} | `{run}` | {trace} | {valid} | {hits} | {missing} | {negative} | {activation} | {validated} |".format(
                mode=row.get("mode_label"),
                repeat=row.get("repeat"),
                run=row.get("run_id"),
                trace=row.get("activation_trace_valid"),
                valid=row.get("validation_passed"),
                hits=row.get("required_skill_hit_count"),
                missing=", ".join(row.get("missing_required_skills", [])) or "-",
                negative=", ".join(row.get("negative_control_skills", [])) or "-",
                activation=row.get("complete_evidence_packet_activation_only"),
                validated=row.get("complete_evidence_packet_validated"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result_path", help="Result directory or benchmark_results.json")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--stem", default=DEFAULT_STEM)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result_path = Path(args.result_path)
    results_path = benchmark_path(result_path)
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else output_dir_for(result_path)
    )
    paths = output_paths(output_dir, args.stem)
    benchmark = load_json(results_path)
    rows = [
        score_trial(trial)
        for trial in benchmark.get("trials", [])
        if isinstance(trial, dict)
    ]
    rows.sort(key=lambda row: (str(row.get("mode")), int(row.get("repeat") or 0)))
    payload = {
        "source": str(results_path),
        "required_skills": list(REQUIRED_SKILLS),
        "negative_control_skills": list(NEGATIVE_CONTROL_SKILLS),
        "excluded_skills": list(EXCLUDED_SKILLS),
        "primary_endpoint": "complete_evidence_packet_validated",
        "rows": rows,
        "aggregate": aggregate_rows(rows),
    }
    write_json(paths["json"], payload)
    write_jsonl(paths["jsonl"], rows)
    paths["md"].write_text(render_markdown(payload), encoding="utf-8")
    print(f"wrote {paths['json']}")
    print(f"wrote {paths['jsonl']}")
    print(f"wrote {paths['md']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
