from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmark_cci_core import (
    BENCHMARK_DIR,
    render_markdown_summary,
    save_json,
    summarize_trials,
)


def _read_jsonl(path: Path) -> list[dict]:
    records = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Regenerate CCI skill ablation summary artifacts from committed trials."
    )
    parser.add_argument(
        "--trials",
        type=Path,
        default=BENCHMARK_DIR / "results" / "full_cci_v2_D_guide_trials.jsonl",
        help="Judged trial JSONL artifact.",
    )
    parser.add_argument(
        "--stem",
        default="full_cci_v2_D_guide",
        help="Output artifact stem under results/.",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=BENCHMARK_DIR / "results",
        help="Directory for regenerated summary JSON and markdown.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    trials = _read_jsonl(args.trials)
    summary = summarize_trials(trials)

    args.results_dir.mkdir(parents=True, exist_ok=True)
    summary_path = args.results_dir / f"{args.stem}_summary.json"
    results_path = args.results_dir / f"{args.stem}_results.md"

    save_json(summary_path, summary)
    results_path.write_text(render_markdown_summary(summary), encoding="utf-8")

    print(f"wrote {summary_path}")
    print(f"wrote {results_path}")


if __name__ == "__main__":
    main()
