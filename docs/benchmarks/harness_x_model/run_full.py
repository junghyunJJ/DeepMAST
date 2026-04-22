from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from docs.benchmarks.harness_x_model.common import (
    append_jsonl,
    apply_ollama_host_override,
    build_trial_schedule,
    check_cases_coherence,
    check_mode_coherence,
    compute_cases_sha256,
    load_cases,
    load_completed_trial_indices,
    load_trial_rows,
    parse_common_args,
    run_single_trial,
    select_pilot_cases,
    serialize_result,
    summarize_results,
    write_json,
)


def main() -> int:
    parser = parse_common_args(argparse.ArgumentParser(description="Run the full harness_x_model benchmark."))
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--max-cases",
        type=int,
        default=30,
        help=(
            "Number of cases to include. Only 30 is supported for the canonical "
            "full run. Use --per-category for stratified subsets."
        ),
    )
    parser.add_argument(
        "--per-category",
        type=int,
        default=None,
        help=(
            "If set, use stratified selection with N cases per category "
            "(total = N × 6 strata). Overrides --max-cases for stratified debug runs."
        ),
    )
    args = parser.parse_args()
    apply_ollama_host_override(args)

    results_dir = Path(args.results_dir)
    workspace_root = Path(args.workspace_root)
    all_cases = load_cases(args.cases_file)

    if args.per_category is not None:
        cases = select_pilot_cases(all_cases, per_category=args.per_category)
    elif args.max_cases == 30:
        cases = all_cases
    else:
        raise SystemExit(
            f"--max-cases={args.max_cases} is not the canonical full-run size (30) "
            "and slicing by file order breaks REV5 stratification. "
            "Use --per-category N for stratified subsets (total = N×6 strata) "
            "or --max-cases 30 for the full dataset."
        )

    # P0.8.5 — resume safety guards.
    cases_sha = compute_cases_sha256(args.cases_file)
    check_mode_coherence(results_dir, args.mode)
    check_cases_coherence(results_dir, cases_sha)

    schedule = build_trial_schedule(cases=cases, repeats=args.repeats, seed=args.seed)
    completed = load_completed_trial_indices(results_dir)

    for trial in schedule:
        if trial["trial_index"] in completed:
            continue
        row = serialize_result(
            run_single_trial(
                case=next(case for case in cases if case["case_id"] == trial["case_id"]),
                condition=trial,
                repeat=trial["repeat"],
                trial_index=trial["trial_index"],
                workspace_root=workspace_root,
                temperature=args.temperature,
                benchmark_mode=args.mode,
                cases_sha256=cases_sha,
            )
        )
        append_jsonl(results_dir / f"trial_{trial['trial_index']:04d}.jsonl", row)

    rows = load_trial_rows(results_dir)
    summary = summarize_results(rows)
    summary["mode"] = "full"
    summary["case_count"] = len(cases)
    summary["repeats"] = args.repeats
    write_json(results_dir / "full_summary.json", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
