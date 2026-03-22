"""Compare B_forced_eval with vs without stage_hints on 3-skill registry.

Runs gpt-4.1-mini on B_forced_eval variant twice:
  1) WITH stage_hints = {"chembl-database": "Stage 3 only"}
  2) WITHOUT stage_hints = {}

Usage:
    python scripts/benchmarks/compare_stage_hints.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import docs.benchmarks.skills.benchmark_skill_harness as bm


async def run_comparison():
    """Run B_forced_eval with and without stage_hints."""
    llm = bm.create_llm(provider="openai", model="gpt-4.1-mini")
    model_label = "gpt-4.1-mini"
    variant = "B_forced_eval"
    repeats = 1

    conditions = {
        "WITH_hints": {"chembl-database": "Stage 3 only"},
        "NO_hints": {},
    }

    summaries: dict[str, bm.BenchmarkSummary] = {}

    for cond_name, hints in conditions.items():
        print(f"\n{'#' * 72}")
        print(f"# Condition: {cond_name} | stage_hints = {hints}")
        print(f"{'#' * 72}\n")

        # Patch module-level STAGE_HINTS
        bm.STAGE_HINTS = hints

        summary = bm.BenchmarkSummary(model_label=f"{model_label} ({cond_name})")
        total = sum(len(ps) for ps in bm.TEST_PROMPTS.values()) * repeats
        done = 0

        for rep in range(repeats):
            for category, prompts in bm.TEST_PROMPTS.items():
                for prompt in prompts:
                    result = await bm._run_single_trial(
                        llm, prompt, category, variant, model_label
                    )
                    summary.results.append(result)
                    done += 1
                    status = "OK" if not result.error else f"ERR: {result.error[:40]}"
                    tool_count = len(result.tool_history)
                    print(
                        f"  [{done}/{total}] {cond_name} | {category} | "
                        f"skills={result.activated_skills or '{}'} | "
                        f"tools={tool_count} | {status}"
                    )

        summaries[cond_name] = summary

    # Print comparison
    print(f"\n{'=' * 80}")
    print("COMPARISON: WITH_hints vs NO_hints (3-skill registry, B_forced_eval)")
    print(f"{'=' * 80}")

    header = f"{'Metric':<25} {'WITH_hints':>14} {'NO_hints':>14} {'Delta':>10}"
    print(header)
    print("-" * len(header))

    for cond_name, summary in summaries.items():
        summary.print_report()

    # Side-by-side metrics
    s_with = summaries["WITH_hints"]
    s_no = summaries["NO_hints"]
    v = variant

    metrics = [
        ("Activation rate", s_with.activation_rate(v), s_no.activation_rate(v)),
        ("False positive rate", s_with.false_positive_rate(v), s_no.false_positive_rate(v)),
        ("Precision", s_with.precision(v), s_no.precision(v)),
        ("Recall", s_with.recall(v), s_no.recall(v)),
        ("Specificity", s_with.specificity(v), s_no.specificity(v)),
        ("F1", s_with.f1(v), s_no.f1(v)),
        ("Avg latency (s)", s_with.avg_latency(v), s_no.avg_latency(v)),
    ]

    print(f"\n{'=' * 65}")
    print("SIDE-BY-SIDE COMPARISON")
    print(f"{'=' * 65}")
    print(f"{'Metric':<25} {'WITH_hints':>14} {'NO_hints':>14} {'Delta':>10}")
    print("-" * 65)
    for name, val_w, val_n in metrics:
        delta = val_n - val_w
        if "latency" in name.lower():
            print(f"{name:<25} {val_w:>13.2f}s {val_n:>13.2f}s {delta:>+9.2f}s")
        else:
            print(f"{name:<25} {val_w:>13.1%} {val_n:>13.1%} {delta:>+9.1%}")

    # Save results
    output_path = Path(__file__).parent / "compare_stage_hints_results.json"
    data = {}
    for cond_name, summary in summaries.items():
        data[cond_name] = {
            "activation_rate": round(summary.activation_rate(v), 4),
            "false_positive_rate": round(summary.false_positive_rate(v), 4),
            "precision": round(summary.precision(v), 4),
            "recall": round(summary.recall(v), 4),
            "specificity": round(summary.specificity(v), 4),
            "f1": round(summary.f1(v), 4),
            "avg_latency": round(summary.avg_latency(v), 2),
        }
    output_path.write_text(json.dumps(data, indent=2))
    print(f"\nResults saved: {output_path}")


if __name__ == "__main__":
    asyncio.run(run_comparison())
