from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Sequence


def _mean(rows: Sequence[dict[str, Any]], key: str) -> float:
    if not rows:
        return 0.0
    return round(sum(float(row[key]) for row in rows) / len(rows), 4)


def _rate(rows: Sequence[dict[str, Any]], key: str) -> float:
    if not rows:
        return 0.0
    return round(sum(1 for row in rows if row.get(key) is True) / len(rows), 4)


def _signed(value: float) -> str:
    return f"{value:+.4f}"


def summarize_by_model_condition(
    trials: Sequence[dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in trials:
        groups[(str(row["model"]), str(row["condition"]))].append(row)

    summary: dict[tuple[str, str], dict[str, Any]] = {}
    for key, rows in sorted(groups.items()):
        valid = [row for row in rows if not row.get("error")]
        summary[key] = {
            "n": len(rows),
            "valid_n": len(valid),
            "error_n": len(rows) - len(valid),
            "exact": _rate(valid, "domain_exact_match"),
            "precision": _mean(valid, "domain_precision"),
            "recall": _mean(valid, "domain_recall"),
            "f1": _mean(valid, "domain_f1"),
            "specificity": _mean(valid, "domain_specificity"),
        }
    return summary


def summarize_failed_cases(
    trials: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in trials:
        groups[
            (
                str(row["model"]),
                str(row["condition"]),
                str(row["case_id"]),
            )
        ].append(row)

    failures: list[dict[str, Any]] = []
    for (model, condition, case_id), rows in sorted(groups.items()):
        valid = [row for row in rows if not row.get("error")]
        exact_rate = _rate(valid, "domain_exact_match")
        if exact_rate == 1.0:
            continue
        activated_patterns = Counter(
            tuple(row["activated_domain_skills"]) for row in valid
        )
        expected = valid[0].get("expected_domain_skills", []) if valid else []
        failures.append(
            {
                "model": model,
                "condition": condition,
                "case_id": case_id,
                "exact_rate": exact_rate,
                "expected": expected,
                "activated_patterns": {
                    ", ".join(pattern) if pattern else "-": count
                    for pattern, count in activated_patterns.items()
                },
            }
        )
    return failures


def render_analysis(payload: dict[str, Any]) -> str:
    trials = list(payload.get("trials", []))
    summary = summarize_by_model_condition(trials)
    failures = summarize_failed_cases(trials)
    unload_events = list(payload.get("unload_events", []))
    unload_ok = all(event.get("ok") for event in unload_events)

    lines = [
        "# Modality-Aware Activation Analysis",
        "",
        "## Run Validation",
        "",
        f"- benchmark: `{payload.get('benchmark', '-')}`",
        f"- trials: `{len(trials)}`",
        f"- errors: `{sum(1 for row in trials if row.get('error'))}`",
        f"- unload_events: `{len(unload_events)}`",
        f"- unload_ok: `{unload_ok}`",
        "",
        "## Overall By Model And Condition",
        "",
        "| model | condition | n | exact | precision | recall | f1 | specificity |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for (model, condition), row in summary.items():
        lines.append(
            "| {model} | {condition} | {n} | {exact:.4f} | {precision:.4f} | "
            "{recall:.4f} | {f1:.4f} | {specificity:.4f} |".format(
                model=model,
                condition=condition,
                n=row["n"],
                exact=row["exact"],
                precision=row["precision"],
                recall=row["recall"],
                f1=row["f1"],
                specificity=row["specificity"],
            )
        )

    lines.extend(
        [
            "",
            "## Activator Delta",
            "",
            "| model | metric | skill_activator - passive_listing |",
            "| --- | --- | ---: |",
        ]
    )
    models = sorted({model for model, _condition in summary})
    for model in models:
        passive = summary.get((model, "passive_listing"))
        activator = summary.get((model, "skill_activator"))
        if not passive or not activator:
            continue
        for metric in ("exact", "precision", "recall", "f1", "specificity"):
            delta = float(activator[metric]) - float(passive[metric])
            lines.append(f"| {model} | {metric} | {_signed(round(delta, 4))} |")

    lines.extend(
        [
            "",
            "## Non-Exact Case Patterns",
            "",
            "| model | condition | case | exact rate | expected | activated patterns |",
            "| --- | --- | --- | ---: | --- | --- |",
        ]
    )
    for failure in failures:
        patterns = "; ".join(
            f"{pattern}: {count}"
            for pattern, count in failure["activated_patterns"].items()
        )
        lines.append(
            "| {model} | {condition} | {case_id} | {exact:.4f} | {expected} | {patterns} |".format(
                model=failure["model"],
                condition=failure["condition"],
                case_id=failure["case_id"],
                exact=failure["exact_rate"],
                expected=", ".join(failure["expected"]) or "-",
                patterns=patterns or "-",
            )
        )

    lines.extend(
        [
            "",
            "## Interpretation Guardrail",
            "",
            "This report supports claims about skill activation only. It does not "
            "support claims about hypothesis_report.json quality or clinical "
            "validity.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_analysis_report(results_path: Path, output_path: Path) -> None:
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    output_path.write_text(render_analysis(payload), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze modality-aware activation benchmark results."
    )
    parser.add_argument("results_json")
    parser.add_argument("--output", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    results_path = Path(args.results_json).expanduser().resolve()
    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else results_path.with_name("modality_activation_analysis.md")
    )
    write_analysis_report(results_path, output_path)
    print(f"wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
