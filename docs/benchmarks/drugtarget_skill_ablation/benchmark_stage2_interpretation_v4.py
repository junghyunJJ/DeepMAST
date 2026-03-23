"""Run the V4 DrugTarget interpretation benchmark."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

BENCHMARK_DIR = Path(__file__).resolve().parent
if str(BENCHMARK_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_DIR))

from benchmark_core import (
    CASES_DIR,
    STAGE2_INTERPRETATION_V4_BENCHMARK,
    default_results_paths,
    render_markdown_summary,
    run_benchmark,
    save_json,
    save_jsonl,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stem",
        default="stage2_interpretation_v4",
        help="Result artifact stem. Defaults to stage2_interpretation_v4.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    result = asyncio.run(
        run_benchmark(
            benchmark_type=STAGE2_INTERPRETATION_V4_BENCHMARK,
            cases_path=CASES_DIR / "stage2_interpretation_v4_cases.json",
            include_judge=False,
        )
    )

    paths = default_results_paths(args.stem)
    save_jsonl(paths["trials_jsonl"], result["trials"])
    save_json(paths["summary_json"], result["summary"])

    markdown = render_markdown_summary(
        benchmark_title="DrugTarget Skill Exposure Benchmark V4 — Stage 2 Rule Application Errors",
        summary=result["summary"],
        judgment_summary=None,
    )
    Path(paths["results_md"]).write_text(markdown, encoding="utf-8")

    print(f"Saved trials to: {paths['trials_jsonl']}")
    print(f"Saved summary to: {paths['summary_json']}")
    print(f"Saved markdown report to: {paths['results_md']}")


if __name__ == "__main__":
    main()
