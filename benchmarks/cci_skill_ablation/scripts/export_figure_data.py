from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, stdev

from benchmark_cci_core import BENCHMARK_DIR


DIMENSIONS = (
    ("Composite", "consensus_score", "trial"),
    ("Faithfulness", "faithfulness", "judge"),
    ("Uncertainty Handling", "uncertainty_handling", "judge"),
    ("Spatial Calibration", "spatial_calibration", "judge"),
    ("Overclaiming", "overclaiming", "judge"),
)

MAIN_VARIANTS = (
    ("D_guide_compliant_skill", "Structured SKILLs"),
    ("B_unstructured_prose", "Unstructured Prose"),
    ("A_no_skill", "No Skills"),
)

SUPPLEMENTARY_VARIANTS = (
    ("D_guide_compliant_skill", "Structured SKILLs (Guide-Compliant)"),
    ("C_structured_skill", "Structured SKILLs (Basic)"),
    ("B_unstructured_prose", "Unstructured Prose"),
    ("A_no_skill", "No Skills"),
)


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _stats(values: list[float]) -> tuple[float, float, int, float]:
    if not values:
        return 0.0, 0.0, 0, 0.0
    n = len(values)
    sd = stdev(values) if n > 1 else 0.0
    se = sd / (n ** 0.5) if n else 0.0
    return mean(values), sd, n, se


def _judge_values(trials: list[dict], key: str) -> list[float]:
    values = []
    for trial in trials:
        for judge_result in trial.get("judge_results", []):
            parsed = judge_result.get("parsed_output") or {}
            if key in parsed:
                values.append(float(parsed[key]))
    return values


def _condition_rows(
    trials_by_variant: dict[str, list[dict]],
    variants: tuple[tuple[str, str], ...],
) -> list[dict[str, str]]:
    rows = []
    for variant, label in variants:
        trials = trials_by_variant[variant]
        for dimension, key, source in DIMENSIONS:
            if source == "trial":
                values = [float(t["consensus_score"]) for t in trials if t.get("consensus_score") is not None]
            else:
                values = _judge_values(trials, key)
            avg, sd, n, se = _stats(values)
            rows.append(
                {
                    "variant": variant,
                    "condition": label,
                    "dimension": dimension,
                    "mean": f"{avg:.6f}",
                    "sd": f"{sd:.6f}",
                    "n": str(n),
                    "se": f"{se:.6f}",
                }
            )
    return rows


def _fabrication_rows(trials_by_variant: dict[str, list[dict]]) -> list[dict[str, str]]:
    rows = []
    for variant, label in SUPPLEMENTARY_VARIANTS:
        values = _judge_values(trials_by_variant[variant], "fabrication_count")
        avg, sd, n, se = _stats(values)
        rows.append(
            {
                "variant": variant,
                "condition": label,
                "mean": f"{avg:.6f}",
                "sd": f"{sd:.6f}",
                "n": str(n),
                "se": f"{se:.6f}",
            }
        )
    return rows


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export CCI skill ablation figure tables from committed trial artifacts."
    )
    parser.add_argument(
        "--trials",
        type=Path,
        default=BENCHMARK_DIR / "results" / "full_cci_v2_D_guide_trials.jsonl",
        help="Judged trial JSONL artifact.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=BENCHMARK_DIR / "results" / "figure_tables",
        help="Directory for generated figure CSV inputs.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    trials = _read_jsonl(args.trials)
    trials_by_variant: dict[str, list[dict]] = defaultdict(list)
    for trial in trials:
        trials_by_variant[trial["variant"]].append(trial)

    _write_csv(
        args.output_dir / "main_condition_scores.csv",
        _condition_rows(trials_by_variant, MAIN_VARIANTS),
    )
    _write_csv(
        args.output_dir / "supplementary_condition_scores.csv",
        _condition_rows(trials_by_variant, SUPPLEMENTARY_VARIANTS),
    )
    _write_csv(
        args.output_dir / "fabrication_counts.csv",
        _fabrication_rows(trials_by_variant),
    )

    print(f"wrote {args.output_dir}")


if __name__ == "__main__":
    main()
