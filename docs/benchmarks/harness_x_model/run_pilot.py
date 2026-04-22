from __future__ import annotations

import argparse
import json
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
    check_pilot_gates,
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
    parser = parse_common_args(argparse.ArgumentParser(description="Run the harness_x_model pilot benchmark."))
    parser.add_argument("--per-category", type=int, default=2, help="Pilot cases per category.")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument(
        "--ignore-gates",
        action="store_true",
        help="Skip the non-zero exit on gate failure (gate report is still written).",
    )
    args = parser.parse_args()
    apply_ollama_host_override(args)

    results_dir = Path(args.results_dir)
    workspace_root = Path(args.workspace_root)

    # P0.8.5 — resume safety guards. Mode check first (cheap, catches the common
    # user error); cases-hash check second (rare but catastrophic if unchecked).
    cases_sha = compute_cases_sha256(args.cases_file)
    check_mode_coherence(results_dir, args.mode)
    check_cases_coherence(results_dir, cases_sha)

    cases = select_pilot_cases(load_cases(args.cases_file), per_category=args.per_category)
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
    summary["mode"] = "pilot"
    summary["case_count"] = len(cases)
    summary["repeats"] = args.repeats
    write_json(results_dir / "pilot_summary.json", summary)

    # REV5 §8 pilot gates — mandatory before committing to the 360-trial full run.
    # P1.1 Rev 4: pass benchmark_mode so Gate Null activates for mode B.
    gates = check_pilot_gates(rows, benchmark_mode=args.mode)
    write_json(results_dir / "pilot_gates.json", gates)
    if not gates.get("all_passed"):
        print(json.dumps(gates, ensure_ascii=False, indent=2), file=sys.stderr)
        if not args.ignore_gates:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
