"""Run the CCI Skill Ablation V2 benchmark.

V2: Open-ended generation + Dual LLM Judge.

Usage:
    python benchmarks/cci_skill_ablation/scripts/run_cci_skill_ablation.py

Phase 1: Generate free-text interpretations (model under test)
Phase 2: Judge each interpretation with dual LLM judges

Environment variables:
    CCI_BENCHMARK_MODELS    Generator model (default: openai:gpt-5.4-nano)
    CCI_BENCHMARK_REPEATS   Repeats per case per variant (default: 5)
    CCI_BENCHMARK_STEM      Result artifact stem
    CCI_JUDGE_MODELS        Comma-separated judge models
                            (default: openai:gpt-5.4,claude:claude-sonnet-4-20250514)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env")

from benchmark_cci_core import (
    ALL_VARIANTS,
    CASES_DIR,
    RESULTS_DIR,
    judge_trial,
    load_cases,
    render_markdown_summary,
    run_single_trial,
    save_json,
    save_jsonl,
    summarize_trials,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.model import create_llm

logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stem",
        default=os.environ.get("CCI_BENCHMARK_STEM", "live_cci_v2"),
        help="Result artifact stem.",
    )
    parser.add_argument(
        "--cases",
        default=str(CASES_DIR / "cci_full_cases.json"),
        help="Path to cases JSON file.",
    )
    parser.add_argument(
        "--results-dir",
        default=str(RESULTS_DIR),
        help="Directory for generated benchmark artifacts.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate prompts without running trials.",
    )
    parser.add_argument(
        "--skip-judge",
        action="store_true",
        help="Skip judging phase (generation only).",
    )
    parser.add_argument(
        "--variants",
        default=None,
        help="Comma-separated variants to run (default: all). E.g., B_unstructured_prose",
    )
    parser.add_argument(
        "--merge-with",
        default=None,
        help="Path to existing trials JSONL to merge with (for partial re-runs).",
    )
    return parser.parse_args()


def _parse_generator_configs() -> list[dict]:
    raw = os.environ.get("CCI_BENCHMARK_MODELS", "openai:gpt-5.4-nano")
    repeats = int(os.environ.get("CCI_BENCHMARK_REPEATS", "5"))
    configs = []
    for entry in raw.split(","):
        entry = entry.strip()
        parts = entry.split(":", 1) if ":" in entry else ("ollama", entry)
        provider, model = parts[0], parts[1]
        configs.append({
            "label": entry,
            "provider": provider,
            "model_kwargs": {"model": model, "temperature": 0.3},
            "repeats": repeats,
        })
    return configs


def _parse_judge_configs() -> list[dict]:
    raw = os.environ.get(
        "CCI_JUDGE_MODELS",
        "openai:gpt-5.4,claude:claude-sonnet-4-20250514",
    )
    configs = []
    for entry in raw.split(","):
        entry = entry.strip()
        parts = entry.split(":", 1) if ":" in entry else ("openai", entry)
        provider, model = parts[0], parts[1]
        configs.append({
            "label": entry,
            "provider": provider,
            "model_kwargs": {"model": model, "temperature": 0},
        })
    return configs


async def _run_generation(cases, model_configs, variants=None) -> list[dict]:
    """Phase 1: Generate free-text interpretations."""
    run_variants = variants if variants else ALL_VARIANTS
    all_trials = []
    for mc in model_configs:
        logger.info("Generator: %s (repeats=%d, temp=%.1f, variants=%s)",
                     mc["label"], mc["repeats"], mc["model_kwargs"].get("temperature", 0),
                     ",".join(run_variants))
        llm = create_llm(provider=mc["provider"], **mc["model_kwargs"])

        for case in cases:
            for variant in run_variants:
                for rep in range(mc["repeats"]):
                    logger.info("  %s | %s | repeat %d/%d",
                                case["case_id"], variant, rep + 1, mc["repeats"])
                    trial = await run_single_trial(llm=llm, case=case, variant=variant)
                    trial["model_label"] = mc["label"]
                    trial["repeat_index"] = rep
                    all_trials.append(trial)

                    status = f"ERROR: {trial['error']}" if trial["error"] else f"{len(trial['raw_output'])} chars"
                    logger.info("    → %s (%.1fs)", status, trial["latency_s"])
    return all_trials


async def _run_judging(trials, cases, judge_configs) -> list[dict]:
    """Phase 2: Judge each trial with dual LLM judges."""
    case_map = {c["case_id"]: c for c in cases}
    judged = []
    total = len([t for t in trials if t["raw_output"] and not t.get("error")])
    done = 0

    for trial in trials:
        if not trial["raw_output"] or trial.get("error"):
            judged.append(trial)
            continue

        case = case_map[trial["case_id"]]
        done += 1
        logger.info("Judging %d/%d: %s | %s", done, total, trial["case_id"], trial["variant"])

        result = await judge_trial(trial=trial, case=case, judge_configs=judge_configs)
        judged.append(result)

        scores = [jr["composite_score"] for jr in result.get("judge_results", []) if jr.get("parsed_output")]
        logger.info("  → consensus=%.2f  judges=%s",
                     result["consensus_score"],
                     [f"{jr['judge_label']}:{jr['composite_score']:.2f}" for jr in result.get("judge_results", [])])
    return judged


def main() -> None:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    cases = load_cases(args.cases)
    logger.info("Loaded %d cases from %s", len(cases), args.cases)

    if args.dry_run:
        from benchmark_cci_core import build_system_prompt, build_user_prompt
        for variant in ALL_VARIANTS:
            sp = build_system_prompt(variant)
            logger.info("--- %s system prompt (%d chars) ---", variant, len(sp))
            print(sp[:300] + "\n...\n")
        for case in cases[:1]:
            up = build_user_prompt(case)
            logger.info("--- User prompt for %s (%d chars) ---", case["case_id"], len(up))
            print(up)
        return

    model_configs = _parse_generator_configs()
    judge_configs = _parse_judge_configs()

    # Parse variant filter
    run_variants = None
    if args.variants:
        run_variants = tuple(v.strip() for v in args.variants.split(","))
        logger.info("Running subset of variants: %s", run_variants)

    active_variants = run_variants if run_variants else ALL_VARIANTS
    total_gen = len(cases) * len(active_variants) * sum(mc["repeats"] for mc in model_configs)
    logger.info("Phase 1: %d generation trials", total_gen)

    trials = asyncio.run(_run_generation(cases, model_configs, variants=run_variants))

    results_dir = Path(args.results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    stem = args.stem

    # Save generation results
    gen_path = results_dir / f"{stem}_generations.jsonl"
    save_jsonl(gen_path, trials)
    logger.info("Saved generations to: %s", gen_path)

    if args.skip_judge:
        logger.info("Skipping judge phase (--skip-judge).")
        return

    # Phase 2: Judging
    valid_gen = len([t for t in trials if t["raw_output"] and not t.get("error")])
    logger.info("Phase 2: Judging %d trials × %d judges = %d judge calls",
                valid_gen, len(judge_configs), valid_gen * len(judge_configs))

    judged_trials = asyncio.run(_run_judging(trials, cases, judge_configs))

    # Merge with existing trials if --merge-with provided
    if args.merge_with:
        import json as _json
        merge_path = Path(args.merge_with)
        existing = []
        with merge_path.open() as f:
            for line in f:
                existing.append(_json.loads(line))
        # Keep existing trials for variants NOT in this run
        kept = [t for t in existing if t["variant"] not in active_variants]
        judged_trials = kept + judged_trials
        logger.info("Merged: %d existing (non-%s) + %d new = %d total",
                     len(kept), ",".join(active_variants), len(trials), len(judged_trials))

    # Save judged results
    trials_path = results_dir / f"{stem}_trials.jsonl"
    summary_path = results_dir / f"{stem}_summary.json"
    results_path = results_dir / f"{stem}_results.md"

    save_jsonl(trials_path, judged_trials)
    logger.info("Saved judged trials to: %s", trials_path)

    summary = summarize_trials(judged_trials)
    save_json(summary_path, summary)
    logger.info("Saved summary to: %s", summary_path)

    markdown = render_markdown_summary(summary)
    results_path.write_text(markdown, encoding="utf-8")
    logger.info("Saved markdown to: %s", results_path)

    print("\n" + markdown)

    kw_p = summary.get("kruskal_wallis", {}).get("pvalue")
    if kw_p is not None and kw_p < 0.05:
        logger.info("GO: Kruskal-Wallis p = %.4f < 0.05.", kw_p)
    elif kw_p is not None:
        logger.warning("CAUTION: Kruskal-Wallis p = %.4f >= 0.05.", kw_p)

    kappa = summary.get("cohens_kappa", {})
    for dim, k in kappa.items():
        if k < 0.7:
            logger.warning("LOW KAPPA: %s = %.3f (< 0.7)", dim, k)


if __name__ == "__main__":
    main()
