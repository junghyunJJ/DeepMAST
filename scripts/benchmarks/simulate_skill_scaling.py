"""Skill Registry Scaling Simulation.

Tests how F1/precision/recall degrade as more distractor skills are added
to the registry. Ground truth stays constant (opentargets+gwas for Stage 2,
chembl for Stage 3). Additional skills are distractors that should never activate.

Two hint strategies per tier:
  A) Only chembl gets a hint — distractors have no hints
  B) All skills get appropriate hints

Tiers: T3(3) → T5(5) → T8(8) → T10(10) → T12(12)

Usage:
    python scripts/benchmarks/simulate_skill_scaling.py

Environment:
    SCALING_MODEL: Model label (default: qwen3.5:122b)
    SCALING_TIERS: Comma-separated tier names (default: all)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import docs.benchmarks.skills.benchmark_skill_harness as bm

# =============================================================================
# Scaling Tier Definitions
# =============================================================================

SKILLS_DIR = _PROJECT_ROOT / "skills"

# Base 3 skills (ground truth targets)
BASE_SKILLS = ["opentargets-database", "gwas-database", "chembl-database"]

# Progressive distractor additions
TIER_ADDITIONS = OrderedDict({
    "T3": [],
    "T5": ["reactome-database", "cellxgene-census"],
    "T8": ["pubmed-eutils-search", "biomedical-literature-search", "academic-search"],
    "T10": ["html-report-generator", "compare-census-gene-pair-by-cell-type"],
    "T12": ["kegg-database", "string-database"],
})

# Hints strategy B: appropriate hints for all skills
ALL_HINTS: dict[str, str] = {
    # Base (always present)
    "chembl-database": "Stage 3 only",
    # T5 additions
    "reactome-database": "Stage 1 pathway queries only — use query_reactome_pathways tool",
    "cellxgene-census": "Stage 1 census queries only — use query_cellxgene tool",
    # T8 additions
    "pubmed-eutils-search": "Stage 3 literature search only",
    "biomedical-literature-search": "Stage 3 literature interpretation only",
    "academic-search": "General research only — not for target validation",
    # T10 additions
    "html-report-generator": "Report generation only — not for evidence gathering",
    "compare-census-gene-pair-by-cell-type": "Stage 1 census comparison only",
    # T12 additions
    "kegg-database": "TOOL-ONLY: accessed via query_kegg_pathways, never read",
    "string-database": "TOOL-ONLY: accessed via query_string_ppi_pair, never read",
}


def _build_tier_registry(tier_name: str) -> dict[str, str]:
    """Build cumulative skill registry for a given tier."""
    skills = list(BASE_SKILLS)
    for t_name, additions in TIER_ADDITIONS.items():
        skills.extend(additions)
        if t_name == tier_name:
            break
    return {name: str(SKILLS_DIR / name) for name in skills}


def _build_hints_a(tier_name: str) -> dict[str, str]:
    """Strategy A: Only chembl gets a hint, distractors get nothing."""
    return {"chembl-database": "Stage 3 only"}


def _build_hints_b(tier_name: str) -> dict[str, str]:
    """Strategy B: All skills get appropriate hints."""
    registry = _build_tier_registry(tier_name)
    return {name: ALL_HINTS[name] for name in registry if name in ALL_HINTS}


# =============================================================================
# Model Configuration
# =============================================================================

MODEL_PRESETS: dict[str, dict[str, Any]] = {
    "qwen3.5:122b": {"provider": "ollama", "model_kwargs": {"model": "qwen3.5:122b"}},
    "qwen3.5:35b": {"provider": "ollama", "model_kwargs": {"model": "qwen3.5:35b"}},
    "gpt-4.1-mini": {"provider": "openai", "model_kwargs": {"model": "gpt-4.1-mini"}},
    "gpt-4.1": {"provider": "openai", "model_kwargs": {"model": "gpt-4.1"}},
}


# =============================================================================
# Result Collection
# =============================================================================

@dataclass
class TierResult:
    tier: str
    n_skills: int
    strategy: str  # "A" or "B"
    activation_rate: float = 0.0
    false_positive_rate: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    specificity: float = 0.0
    f1: float = 0.0
    avg_latency: float = 0.0
    errors: int = 0
    per_skill: dict[str, dict[str, int]] = field(default_factory=dict)


# =============================================================================
# Run Single Tier
# =============================================================================

async def _run_tier(
    llm: Any,
    model_label: str,
    tier_name: str,
    strategy: str,
    registry: dict[str, str],
    hints: dict[str, str],
) -> TierResult:
    """Run all 21 test prompts for a single tier+strategy combination."""
    # Patch module-level constants
    bm.SKILL_REGISTRY = registry
    bm.STAGE_HINTS = hints
    bm.ALL_SKILLS = set(registry.keys())

    n_skills = len(registry)
    label = f"{tier_name}_{strategy}"

    summary = bm.BenchmarkSummary(model_label=f"{model_label} ({label})")
    total = sum(len(ps) for ps in bm.TEST_PROMPTS.values())
    done = 0

    for category, prompts in bm.TEST_PROMPTS.items():
        for prompt in prompts:
            result = await bm._run_single_trial(
                llm, prompt, category, "B_forced_eval", model_label
            )
            summary.results.append(result)
            done += 1
            status = "OK" if not result.error else f"ERR: {result.error[:40]}"
            print(
                f"  [{done}/{total}] {label} ({n_skills} skills) | {category} | "
                f"skills={result.activated_skills or '{}'} | {status}"
            )

    v = "B_forced_eval"
    tier_result = TierResult(
        tier=tier_name,
        n_skills=n_skills,
        strategy=strategy,
        activation_rate=summary.activation_rate(v),
        false_positive_rate=summary.false_positive_rate(v),
        precision=summary.precision(v),
        recall=summary.recall(v),
        specificity=summary.specificity(v),
        f1=summary.f1(v),
        avg_latency=summary.avg_latency(v),
        errors=summary.error_count(v),
        per_skill=summary.per_skill_accuracy(v),
    )
    return tier_result


# =============================================================================
# Main
# =============================================================================

async def run_simulation():
    """Run the full scaling simulation."""
    model_label = os.getenv("SCALING_MODEL", "qwen3.5:122b")
    tier_filter_raw = os.getenv("SCALING_TIERS", "")
    tier_filter = (
        [t.strip() for t in tier_filter_raw.split(",") if t.strip()]
        if tier_filter_raw
        else list(TIER_ADDITIONS.keys())
    )

    if model_label not in MODEL_PRESETS:
        print(f"Unknown model: {model_label}. Available: {list(MODEL_PRESETS.keys())}")
        sys.exit(1)

    preset = MODEL_PRESETS[model_label]
    llm = bm.create_llm(provider=preset["provider"], **preset["model_kwargs"])

    print(f"{'#' * 72}")
    print(f"# Skill Registry Scaling Simulation")
    print(f"# Model: {model_label}")
    print(f"# Tiers: {tier_filter}")
    print(f"# Strategies: A (chembl hint only), B (all hints)")
    print(f"{'#' * 72}\n")

    results: list[TierResult] = []

    for tier_name in tier_filter:
        if tier_name not in TIER_ADDITIONS:
            print(f"  Skipping unknown tier: {tier_name}")
            continue

        registry = _build_tier_registry(tier_name)
        n_skills = len(registry)

        for strategy, hints_fn in [("A", _build_hints_a), ("B", _build_hints_b)]:
            hints = hints_fn(tier_name)
            print(f"\n{'=' * 60}")
            print(f"TIER {tier_name} | {n_skills} skills | Strategy {strategy}")
            print(f"Registry: {list(registry.keys())}")
            print(f"Hints: {hints}")
            print(f"{'=' * 60}\n")

            tier_result = await _run_tier(
                llm, model_label, tier_name, strategy, registry, hints
            )
            results.append(tier_result)

    # Print summary table
    _print_summary(results, model_label)
    _save_results(results, model_label)


def _print_summary(results: list[TierResult], model_label: str):
    """Print the scaling degradation summary."""
    print(f"\n{'=' * 90}")
    print(f"SCALING SIMULATION SUMMARY: {model_label}")
    print(f"{'=' * 90}")

    header = (
        f"{'Tier':<6} {'#Sk':>4} {'Strat':>5} "
        f"{'F1':>7} {'Prec':>7} {'Recall':>7} {'Spec':>7} "
        f"{'FP%':>7} {'Act%':>7} {'Lat(s)':>8} {'Err':>4}"
    )
    print(header)
    print("-" * len(header))

    for r in results:
        print(
            f"{r.tier:<6} {r.n_skills:>4} {r.strategy:>5} "
            f"{r.f1:>6.1%} {r.precision:>6.1%} {r.recall:>6.1%} {r.specificity:>6.1%} "
            f"{r.false_positive_rate:>6.1%} {r.activation_rate:>6.1%} "
            f"{r.avg_latency:>7.1f}s {r.errors:>4}"
        )

    # Degradation analysis
    print(f"\n--- Degradation Analysis ---")
    baseline_a = next((r for r in results if r.tier == "T3" and r.strategy == "A"), None)
    baseline_b = next((r for r in results if r.tier == "T3" and r.strategy == "B"), None)

    if baseline_a:
        print(f"\nStrategy A (chembl hint only) — F1 degradation from T3 baseline ({baseline_a.f1:.1%}):")
        for r in results:
            if r.strategy == "A" and r.tier != "T3":
                delta = r.f1 - baseline_a.f1
                flag = " ⚠️" if r.f1 < 0.9 else ""
                print(f"  {r.tier} ({r.n_skills} skills): F1={r.f1:.1%} (Δ={delta:+.1%}){flag}")

    if baseline_b:
        print(f"\nStrategy B (all hints) — F1 degradation from T3 baseline ({baseline_b.f1:.1%}):")
        for r in results:
            if r.strategy == "B" and r.tier != "T3":
                delta = r.f1 - baseline_b.f1
                flag = " ⚠️" if r.f1 < 0.9 else ""
                print(f"  {r.tier} ({r.n_skills} skills): F1={r.f1:.1%} (Δ={delta:+.1%}){flag}")

    # Per-skill FP analysis for distractors
    print(f"\n--- Distractor Skill FP Analysis ---")
    distractor_skills = set()
    for additions in TIER_ADDITIONS.values():
        distractor_skills.update(additions)

    for r in results:
        if not r.per_skill:
            continue
        fp_skills = [
            (skill, s["fp"])
            for skill, s in r.per_skill.items()
            if skill in distractor_skills and s["fp"] > 0
        ]
        if fp_skills:
            print(f"  {r.tier}_{r.strategy}: FP distractors: {fp_skills}")

    print(f"{'=' * 90}")


def _save_results(results: list[TierResult], model_label: str):
    """Save results to JSON."""
    safe_label = model_label.replace(":", "_").replace(".", "_")
    output_path = Path(__file__).parent / f"scaling_simulation_{safe_label}.json"

    data = []
    for r in results:
        entry = {
            "tier": r.tier,
            "n_skills": r.n_skills,
            "strategy": r.strategy,
            "f1": round(r.f1, 4),
            "precision": round(r.precision, 4),
            "recall": round(r.recall, 4),
            "specificity": round(r.specificity, 4),
            "false_positive_rate": round(r.false_positive_rate, 4),
            "activation_rate": round(r.activation_rate, 4),
            "avg_latency": round(r.avg_latency, 2),
            "errors": r.errors,
            "per_skill": {
                skill: {k: v for k, v in stats.items()}
                for skill, stats in r.per_skill.items()
            },
        }
        data.append(entry)

    output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"\nResults saved: {output_path}")


def main():
    """Entry point."""
    import logging
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(run_simulation())


if __name__ == "__main__":
    main()
