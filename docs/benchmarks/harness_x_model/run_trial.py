from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import os as _os

from docs.benchmarks.harness_x_model.common import (
    CONDITIONS,
    append_jsonl,
    apply_ollama_host_override,
    check_mode_coherence,
    compute_cases_sha256,
    load_cases,
    run_single_trial,
    serialize_result,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a single harness_x_model benchmark trial.")
    parser.add_argument("--cases-file", default="docs/benchmarks/cci_skill_ablation/cases/cci_full_cases.json")
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--condition", required=True, choices=[item["condition"] for item in CONDITIONS])
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--trial-index", type=int, required=True)
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--temperature", type=float, default=0.3)
    parser.add_argument("--ollama-host", default=None)
    # P0.8 — benchmark_mode toggle (single-trial variant; mode-only guard per
    # Architect finding #1 to prevent contaminated-row injection at :48 below).
    parser.add_argument(
        "--mode",
        choices=["B", "B_prime", "C"],
        default=_os.environ.get("BENCHMARK_MODE", "C"),
        help="Benchmark mode (B, B_prime, C). Default C preserves existing behavior.",
    )
    args = parser.parse_args()
    apply_ollama_host_override(args)

    cases = {case["case_id"]: case for case in load_cases(args.cases_file)}
    if args.case_id not in cases:
        raise SystemExit(f"Unknown case_id: {args.case_id}")

    # P0.8.5 — mode-coherence guard (single-trial; hash check omitted since
    # run_trial has explicit --trial-index and no schedule dependency).
    check_mode_coherence(Path(args.results_dir), args.mode)

    cases_sha = compute_cases_sha256(args.cases_file)
    condition = next(item for item in CONDITIONS if item["condition"] == args.condition)
    result = run_single_trial(
        case=cases[args.case_id],
        condition=condition,
        repeat=args.repeat,
        trial_index=args.trial_index,
        workspace_root=args.workspace_root,
        temperature=args.temperature,
        benchmark_mode=args.mode,
        cases_sha256=cases_sha,
    )
    payload = serialize_result(result)

    out_path = Path(args.results_dir) / f"trial_{args.trial_index:04d}.jsonl"
    append_jsonl(out_path, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
