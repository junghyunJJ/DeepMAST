"""3-way comparison: A_passive vs B_forced_eval(WITH hints) vs B_forced_eval(NO hints).

Runs qwen3.5:122b on 3-skill registry.

Usage:
    python scripts/benchmarks/compare_3way.py
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
    """Run A_passive + B_forced_eval (with/without hints) on qwen3.5:122b."""
    llm = bm.create_llm(provider="ollama", model="qwen3.5:122b")
    model_label = "qwen3.5:122b"
    repeats = 1

    # 3 conditions to compare
    conditions = [
        ("A_passive", "A_passive", None),           # variant, label, hints_override
        ("B_WITH_hints", "B_forced_eval", {"chembl-database": "Stage 3 only"}),
        ("B_NO_hints", "B_forced_eval", {}),
    ]

    summaries: dict[str, bm.BenchmarkSummary] = {}

    for cond_name, variant, hints_override in conditions:
        print(f"\n{'#' * 72}")
        if hints_override is not None:
            print(f"# Condition: {cond_name} | variant={variant} | stage_hints={hints_override}")
            bm.STAGE_HINTS = hints_override
        else:
            print(f"# Condition: {cond_name} | variant={variant} | (passive, no hints used)")
        print(f"{'#' * 72}\n")

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

    # Print individual reports
    for summary in summaries.values():
        summary.print_report()

    # Side-by-side comparison
    v_map = {
        "A_passive": "A_passive",
        "B_WITH_hints": "B_forced_eval",
        "B_NO_hints": "B_forced_eval",
    }

    print(f"\n{'=' * 80}")
    print("3-WAY COMPARISON: qwen3.5:122b (3-skill registry)")
    print(f"{'=' * 80}")
    print(f"{'Metric':<25} {'A_passive':>14} {'B_WITH_hints':>14} {'B_NO_hints':>14}")
    print("-" * 70)

    metric_fns = [
        ("Activation rate", "activation_rate"),
        ("False positive rate", "false_positive_rate"),
        ("Precision", "precision"),
        ("Recall", "recall"),
        ("Specificity", "specificity"),
        ("F1", "f1"),
        ("Avg latency (s)", "avg_latency"),
    ]

    results_data = {}
    for cond_name, summary in summaries.items():
        v = v_map[cond_name]
        results_data[cond_name] = {}
        for label, fn_name in metric_fns:
            val = getattr(summary, fn_name)(v)
            results_data[cond_name][fn_name] = round(val, 4)

    for label, fn_name in metric_fns:
        vals = [results_data[c][fn_name] for c in ["A_passive", "B_WITH_hints", "B_NO_hints"]]
        if "latency" in label.lower():
            print(f"{label:<25} {vals[0]:>13.2f}s {vals[1]:>13.2f}s {vals[2]:>13.2f}s")
        else:
            print(f"{label:<25} {vals[0]:>13.1%} {vals[1]:>13.1%} {vals[2]:>13.1%}")

    # Per-skill accuracy comparison
    print(f"\n{'=' * 80}")
    print("PER-SKILL ACCURACY")
    print(f"{'=' * 80}")
    print(f"{'Skill':<25} {'A_passive':>14} {'B_WITH_hints':>14} {'B_NO_hints':>14}")
    print("-" * 70)

    for cond_name, summary in summaries.items():
        v = v_map[cond_name]
        stats = summary.per_skill_accuracy(v)
        for skill, s in sorted(stats.items()):
            total = s["tp"] + s["fp"] + s["tn"] + s["fn"]
            acc = (s["tp"] + s["tn"]) / total if total else 0.0
            results_data[cond_name][f"acc_{skill}"] = round(acc, 4)

    for skill in sorted(bm.ALL_SKILLS):
        vals = [results_data[c].get(f"acc_{skill}", 0) for c in ["A_passive", "B_WITH_hints", "B_NO_hints"]]
        print(f"{skill:<25} {vals[0]:>13.1%} {vals[1]:>13.1%} {vals[2]:>13.1%}")

    # Save
    output_path = Path(__file__).parent / "compare_3way_results.json"
    output_path.write_text(json.dumps(results_data, indent=2))
    print(f"\nResults saved: {output_path}")


if __name__ == "__main__":
    asyncio.run(run_comparison())
