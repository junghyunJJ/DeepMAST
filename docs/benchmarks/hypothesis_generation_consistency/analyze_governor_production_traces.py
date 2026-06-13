from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable, Sequence


DOMAIN_SKILLS = (
    "opentargets-database",
    "gwas-database",
    "chembl-database",
    "compare-census-gene-pair-by-cell-type",
    "string-database",
)
CORE_SKILL = "drug-target-hypothesis"
EXPECTED_SKILL_ORDER = (
    CORE_SKILL,
    "chembl-database",
    "compare-census-gene-pair-by-cell-type",
    "gwas-database",
    "opentargets-database",
    "string-database",
)


def _file_text_contains(path: Path, needles: Sequence[str]) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore").casefold()
    except Exception:
        return False
    return any(needle.casefold() in text for needle in needles)


def _ordered_expected_skills(expected: set[str]) -> list[str]:
    ordered = [skill for skill in EXPECTED_SKILL_ORDER if skill in expected]
    extra = sorted(expected.difference(EXPECTED_SKILL_ORDER))
    return ordered + extra


def _gwas_signal_present(path: Path) -> bool:
    return _file_text_contains(
        path,
        (
            "genetic_association",
            "gwas",
            "variant",
            "snp",
        ),
    )


def infer_expected_skills(workspace: Path) -> list[str]:
    evidence = workspace / "evidence"
    expected: set[str] = {CORE_SKILL}
    if not evidence.exists():
        return [CORE_SKILL]

    files = [path for path in evidence.rglob("*") if path.is_file()]
    json_files = [path for path in files if path.suffix == ".json"]

    if any(path.name.startswith("ot_") for path in json_files):
        expected.add("opentargets-database")
    if any(path.name.startswith("stage3_") for path in json_files):
        expected.add("chembl-database")
    if any(path.name.startswith("census_") for path in files) or any(
        _file_text_contains(
            path,
            ("census_validation", "target_vs_rest", "coexpression"),
        )
        for path in json_files
    ):
        expected.add("compare-census-gene-pair-by-cell-type")
    if any(
        _file_text_contains(path, ("string_ppi", "ppi_enrichment", "combined_score"))
        for path in json_files
    ):
        expected.add("string-database")
    if any(_gwas_signal_present(path) for path in json_files):
        expected.add("gwas-database")

    return _ordered_expected_skills(expected)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_nodes_by_skill(trace_payload: dict[str, Any]) -> dict[str, list[int]]:
    nodes: dict[str, list[int]] = {}
    calls = trace_payload.get("hypothesis_writer_read_skill_file_calls") or []
    for call in calls:
        if not isinstance(call, dict):
            continue
        skill_name = call.get("skill_name")
        node_counter = call.get("node_counter")
        if isinstance(skill_name, str) and isinstance(node_counter, int):
            nodes.setdefault(skill_name, []).append(node_counter)
    return nodes


def score_trace_row(
    row: dict[str, Any],
    *,
    expected_skills: Sequence[str],
) -> dict[str, Any]:
    activated = set(str(skill) for skill in row.get("activated_skill_names", []))
    expected = set(expected_skills)
    missing = sorted(expected - activated)
    extra_domain = sorted((activated - expected).intersection(DOMAIN_SKILLS))

    trace_payload = row.get("activation_trace_payload") or {}
    gate_event = trace_payload.get("artifact_gate_event")
    read_nodes = _read_nodes_by_skill(trace_payload)
    if isinstance(gate_event, dict) and isinstance(gate_event.get("node_counter"), int):
        gate_node = int(gate_event["node_counter"])
        expected_reads_before_gate = all(
            any(node < gate_node for node in read_nodes.get(skill, []))
            for skill in expected
        )
    else:
        gate_node = None
        expected_reads_before_gate = False

    scored = dict(row)
    validation = row.get("validation")
    hypothesis_report_success = (
        bool(validation.get("success"))
        if isinstance(validation, dict)
        else False
    )
    scored.update(
        {
            "expected_skill_names": _ordered_expected_skills(expected),
            "hypothesis_report_success": hypothesis_report_success,
            "missing_expected_skills": missing,
            "overactivated_domain_skills": extra_domain,
            "coverage_complete": len(missing) == 0,
            "artifact_gate_node_counter": gate_node,
            "expected_reads_before_gate": expected_reads_before_gate,
        }
    )
    return scored


def _count_values(values: Iterable[object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def summarize_rows(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(f"{row['model']}::{row['mode']}", []).append(row)

    summary: dict[str, Any] = {}
    for key, group_rows in groups.items():
        runs = len(group_rows)
        summary[key] = {
            "runs": runs,
            "activation_trace_valid_runs": sum(
                1 for row in group_rows if row.get("activation_trace_valid") is True
            ),
            "hypothesis_report_success_runs": sum(
                1 for row in group_rows if row.get("hypothesis_report_success") is True
            ),
            "coverage_complete_runs": sum(
                1 for row in group_rows if row.get("coverage_complete") is True
            ),
            "expected_reads_before_gate_runs": sum(
                1 for row in group_rows if row.get("expected_reads_before_gate") is True
            ),
            "missing_expected_skill_counts": _count_values(
                skill
                for row in group_rows
                for skill in row.get("missing_expected_skills", [])
            ),
            "overactivated_domain_skill_counts": _count_values(
                skill
                for row in group_rows
                for skill in row.get("overactivated_domain_skills", [])
            ),
        }
    return {"groups": summary}


def render_markdown(rows: Sequence[dict[str, Any]], summary: dict[str, Any]) -> str:
    lines = [
        "# Governor Production Hypothesis Writer Activation Analysis",
        "",
        (
            "| model | port | mode | trace | report | coverage | before gate | "
            "missing expected | overactivated |"
        ),
        "| --- | ---: | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            (
                "| {model} | {port} | {mode} | {trace} | {report} | {coverage} | "
                "{before_gate} | {missing} | {extra} |"
            ).format(
                model=row["model"],
                port=row["port"],
                mode=row["mode"],
                trace=row.get("activation_trace_valid"),
                report=row.get("hypothesis_report_success"),
                coverage=row.get("coverage_complete"),
                before_gate=row.get("expected_reads_before_gate"),
                missing=", ".join(row.get("missing_expected_skills", [])) or "-",
                extra=", ".join(row.get("overactivated_domain_skills", [])) or "-",
            )
        )
    lines.extend(["", "## Aggregate", "", "```json"])
    lines.append(json.dumps(summary, indent=2, ensure_ascii=False))
    lines.extend(["```", ""])
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("benchmark_results")
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    results_path = Path(args.benchmark_results).expanduser().resolve()
    payload = load_json(results_path)
    rows = []
    for row in payload.get("trials", []):
        trace_path = Path(str(row.get("activation_trace", "")))
        trace_payload = load_json(trace_path) if trace_path.exists() else {}
        enriched = dict(row)
        enriched["activation_trace_payload"] = trace_payload
        workspace = Path(str(row.get("workspace", "")))
        rows.append(
            score_trace_row(
                enriched,
                expected_skills=infer_expected_skills(workspace),
            )
        )

    summary = summarize_rows(rows)
    output_json = (
        Path(args.output_json)
        if args.output_json
        else results_path.with_name("governor_trace_analysis.json")
    )
    output_md = (
        Path(args.output_md)
        if args.output_md
        else results_path.with_name("governor_trace_analysis.md")
    )
    output_json.write_text(
        json.dumps({"trials": rows, "summary": summary}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    output_md.write_text(render_markdown(rows, summary), encoding="utf-8")
    print(f"wrote {output_json}")
    print(f"wrote {output_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
