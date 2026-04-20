"""A/B benchmark: SkillsMiddleware (passive) vs SkillLoadHarness (forced-eval).

Compares skill activation rates across multiple models:
  A) SkillsMiddleware — passive listing (current baseline)
  B) SkillLoadHarness — forced 3-step evaluation (new approach)

Uses a lightweight mock agent with only `read_skill_file` tool.
Real LLM calls, no external DB queries.

Usage:
    python docs/benchmarks/skills/benchmark_skill_harness.py

Environment:
    BENCHMARK_MODELS: Comma-separated model labels (default: all)
    BENCHMARK_REPEATS: Runs per prompt (default: 1)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from langchain_core.messages import HumanMessage, SystemMessage

from src.agents.model import create_llm
from src.agents.shared.skill_load_harness import SkillLoadHarness
from src.agents.shared.skills_middleware import SkillsMiddleware
from src.agents.drug_target.tools.skill_reader import read_skill_file

logger = logging.getLogger(__name__)

# =============================================================================
# Model Configurations
# =============================================================================

MODEL_CONFIGS: list[dict[str, Any]] = [
    {"label": "qwen3.5:35b", "provider": "ollama", "model_kwargs": {"model": "qwen3.5:35b"}},
    {"label": "qwen3.5:122b", "provider": "ollama", "model_kwargs": {"model": "qwen3.5:122b"}},
    {"label": "gpt-4.1-mini", "provider": "openai", "model_kwargs": {"model": "gpt-4.1-mini"}},
]

# =============================================================================
# Test Prompts
# =============================================================================

TEST_PROMPTS: dict[str, list[str]] = {
    # --- Activation categories (skill activation expected) ---
    "direct_mention": [
        "Check the druggability of BRAF in OpenTargets",
        "Look up the clinical phase information for EGFR in ChEMBL",
        "Query the MAPK signaling pathway in KEGG",
    ],
    "indirect_reference": [
        "Gather target validation evidence for BRAF",
        "Assess the drug target potential of this gene",
        "Find interaction partners for this protein",
    ],
    "composite": [
        "Perform a deep dive using GWAS + ChEMBL data",
        "Comprehensively evaluate genetic evidence and druggability",
        "Validate the target by combining pathway analysis and PPI network",
    ],
    "ambiguous": [
        "Collect all available evidence for this target",
        "Proceed with Stage 2 scoring",
        "Analyze the functional annotation of this gene",
    ],
    # --- FP categories (no skill activation expected) ---
    "no_skill_needed": [
        "Collect Stage 1 biological context",
        "Summarize the top L-R pairs from CCI analysis results",
        "Perform QC on the spatial transcriptomics data",
    ],
    "internal_pipeline": [
        "Organize and summarize the data collected in Stage 1",
        "Write a report based on the results from the previous stage",
        "Check the normalized expression matrix",
    ],
    "general_biology": [
        "Explain the biological significance of the BRAF V600E mutation",
        "Describe the general function of tyrosine kinases",
        "Explain the role of receptors in cell signaling",
    ],
    "data_visualization": [
        "Visualize the analysis results as a heatmap",
        "Create a bar chart of the Stage 2 scoring results",
        "Draw the L-R interaction network as a graph",
    ],
}

# Expected skill activations per category
EXPECTED_SKILLS: dict[str, set[str]] = {
    # Activation categories
    "direct_mention": {"opentargets-database", "chembl-database", "kegg-database"},
    "indirect_reference": {"opentargets-database", "gwas-database", "string-database"},
    "composite": {"gwas-database", "chembl-database", "kegg-database", "string-database"},
    "ambiguous": {"opentargets-database", "gwas-database", "kegg-database"},
    # FP categories — empty set = no skills should activate
    "no_skill_needed": set(),
    "internal_pipeline": set(),
    "general_biology": set(),
    "data_visualization": set(),
}

FP_CATEGORIES: set[str] = {cat for cat, expected in EXPECTED_SKILLS.items() if not expected}

# Skill registry for SkillLoadHarness
SKILL_REGISTRY: dict[str, str] = {
    "opentargets-database": str(_PROJECT_ROOT / "skills" / "opentargets-database"),
    "gwas-database": str(_PROJECT_ROOT / "skills" / "gwas-database"),
    "chembl-database": str(_PROJECT_ROOT / "skills" / "chembl-database"),
    "kegg-database": str(_PROJECT_ROOT / "skills" / "kegg-database"),
    "string-database": str(_PROJECT_ROOT / "skills" / "string-database"),
}

STAGE_HINTS: dict[str, str] = {
    "chembl-database": "Stage 3 only",
    "kegg-database": "Pathway analysis",
    "string-database": "PPI network queries",
}


# =============================================================================
# Result Types
# =============================================================================


@dataclass
class TrialResult:
    """Result from a single benchmark trial."""

    model: str = ""
    category: str = ""
    prompt: str = ""
    variant: str = ""  # "A_passive" or "B_forced_eval"
    activated_skills: set[str] = field(default_factory=set)
    read_skill_calls: int = 0
    latency_s: float = 0.0
    error: str | None = None


@dataclass
class BenchmarkSummary:
    """Aggregated benchmark results for a single model."""

    model_label: str = ""
    results: list[TrialResult] = field(default_factory=list)

    def activation_rate(self, variant: str) -> float:
        """Fraction of trials where at least one expected skill was activated."""
        variant_results = [r for r in self.results if r.variant == variant and not r.error]
        if not variant_results:
            return 0.0
        hits = sum(
            1
            for r in variant_results
            if r.activated_skills & EXPECTED_SKILLS.get(r.category, set())
        )
        return hits / len(variant_results)

    def false_positive_rate(self, variant: str) -> float:
        """Fraction of FP-category trials that activated skills anyway."""
        fp_trials = [
            r
            for r in self.results
            if r.variant == variant and r.category in FP_CATEGORIES and not r.error
        ]
        if not fp_trials:
            return 0.0
        fps = sum(1 for r in fp_trials if r.activated_skills)
        return fps / len(fp_trials)

    def avg_latency(self, variant: str) -> float:
        """Average latency in seconds."""
        times = [r.latency_s for r in self.results if r.variant == variant and not r.error]
        return sum(times) / len(times) if times else 0.0

    def error_count(self, variant: str) -> int:
        return sum(1 for r in self.results if r.variant == variant and r.error)

    def print_report(self) -> None:
        """Print a formatted comparison table for this model."""
        print(f"\n{'=' * 72}")
        print(f"MODEL: {self.model_label}")
        print("=" * 72)

        for variant in ("A_passive", "B_forced_eval"):
            label = "SkillsMiddleware (passive)" if variant == "A_passive" else "SkillLoadHarness (forced-eval)"
            errors = self.error_count(variant)
            print(f"\n--- {label} ---")
            print(f"  Activation rate:     {self.activation_rate(variant):.1%}")
            print(f"  False positive rate: {self.false_positive_rate(variant):.1%}")
            print(f"  Avg latency:         {self.avg_latency(variant):.2f}s")
            if errors:
                print(f"  Errors:              {errors}")

        print(f"\n--- Per-category breakdown ({self.model_label}) ---")
        header = f"{'Category':<20} {'A_passive':>12} {'B_forced_eval':>14}"
        print(header)
        print("-" * len(header))

        for cat in TEST_PROMPTS:
            for tag, variant in [("a", "A_passive"), ("b", "B_forced_eval")]:
                hits = sum(
                    1
                    for r in self.results
                    if r.variant == variant
                    and r.category == cat
                    and r.activated_skills & EXPECTED_SKILLS.get(cat, set())
                    and not r.error
                )
                total = sum(
                    1
                    for r in self.results
                    if r.variant == variant and r.category == cat and not r.error
                )
                if tag == "a":
                    a_str = f"{hits}/{total}" if total else "N/A"
                else:
                    b_str = f"{hits}/{total}" if total else "N/A"
            print(f"{cat:<20} {a_str:>12} {b_str:>14}")

        print("=" * 72)


def print_cross_model_report(summaries: dict[str, BenchmarkSummary]) -> None:
    """Print cross-model comparison table."""
    print("\n" + "=" * 80)
    print("CROSS-MODEL COMPARISON")
    print("=" * 80)
    header = f"{'Model':<18} {'A_act':>7} {'B_act':>7} {'Delta':>7} {'A_FP':>7} {'B_FP':>7} {'A_lat':>7} {'B_lat':>7}"
    print(header)
    print("-" * len(header))

    for label, summary in summaries.items():
        a_act = summary.activation_rate("A_passive")
        b_act = summary.activation_rate("B_forced_eval")
        delta = b_act - a_act
        a_fp = summary.false_positive_rate("A_passive")
        b_fp = summary.false_positive_rate("B_forced_eval")
        a_lat = summary.avg_latency("A_passive")
        b_lat = summary.avg_latency("B_forced_eval")
        print(
            f"{label:<18} {a_act:>6.1%} {b_act:>6.1%} {delta:>+6.1%} "
            f"{a_fp:>6.1%} {b_fp:>6.1%} {a_lat:>6.1f}s {b_lat:>6.1f}s"
        )

    print("=" * 80)


# =============================================================================
# Skill Activation Detection
# =============================================================================


def _extract_skill_calls(response_text: str) -> set[str]:
    """Extract skill names from read_skill_file calls and YES evaluations."""
    skills: set[str] = set()

    # 1. read_skill_file call patterns — flexible whitespace
    for match in re.finditer(
        r'read_skill_file\s*\(\s*skill_path\s*=\s*["\']([^"\']+)["\']',
        response_text,
    ):
        path = Path(match.group(1))
        parts = path.parts
        for i, part in enumerate(parts):
            if part == "skills" and i + 1 < len(parts):
                skills.add(parts[i + 1])
                break

    # 2. YES evaluation patterns — case-insensitive, various separators
    for match in re.finditer(
        r'[\*]*(\w[\w-]+)[\*]*\s*[—–\-:]\s*(?:YES|Yes|yes|예)',
        response_text,
    ):
        candidate = match.group(1).lower()
        for registry_name in SKILL_REGISTRY:
            if candidate == registry_name or candidate in registry_name or registry_name in candidate:
                skills.add(registry_name)

    # 3. Skill name near activation keywords
    for name in SKILL_REGISTRY:
        pattern = (
            rf'(?:activate|활성화|load|읽|read|사용|use)\s.{{0,60}}{re.escape(name)}'
            rf'|{re.escape(name)}.{{0,60}}(?:activate|활성화|load|읽|read|사용|use)'
        )
        if re.search(pattern, response_text, re.IGNORECASE):
            skills.add(name)

    return skills


# =============================================================================
# Mock Agent Runner
# =============================================================================


async def _run_single_trial(
    llm: Any,
    prompt: str,
    category: str,
    variant: str,
    middleware_cls: str,
    model_label: str,
) -> TrialResult:
    """Run a single benchmark trial."""
    result = TrialResult(model=model_label, category=category, prompt=prompt, variant=variant)
    start = time.monotonic()

    try:
        if middleware_cls == "passive":
            mw = SkillsMiddleware(
                skills_dir=_PROJECT_ROOT / "skills",
                allowed_skill_names=tuple(SKILL_REGISTRY.keys()),
            )
        else:
            mw = SkillLoadHarness(
                skill_registry=SKILL_REGISTRY,
                stage_hints=STAGE_HINTS,
            )

        # Simulate abefore_agent
        await mw.abefore_agent(state=None, runtime=None)

        base_system = "You are a drug target assessment agent with access to read_skill_file tool."

        class _MockRequest:
            system_message = SystemMessage(content=base_system)
            system_prompt = None

            def override(self, **kwargs):
                new = _MockRequest()
                for k, v in kwargs.items():
                    setattr(new, k, v)
                return new

        enhanced_request = _MockRequest()
        captured_prompt = None

        async def _capture_handler(req):
            nonlocal captured_prompt
            captured_prompt = str(req.system_message.content)
            return None

        await mw.awrap_model_call(enhanced_request, _capture_handler)

        response = await llm.ainvoke(
            [
                {"role": "system", "content": captured_prompt},
                {"role": "user", "content": prompt},
            ]
        )

        response_text = response.content if hasattr(response, "content") else str(response)
        result.activated_skills = _extract_skill_calls(response_text)
        result.read_skill_calls = response_text.lower().count("read_skill_file")

    except Exception as e:
        result.error = str(e)
        logger.exception("Trial failed: %s", e)
    finally:
        result.latency_s = time.monotonic() - start

    return result


# =============================================================================
# Main
# =============================================================================


async def _run_model_benchmark(
    llm: Any,
    model_label: str,
    repeats: int,
) -> BenchmarkSummary:
    """Run benchmark for a single model."""
    summary = BenchmarkSummary(model_label=model_label)
    total = sum(len(ps) for ps in TEST_PROMPTS.values()) * 2 * repeats
    done = 0

    for rep in range(repeats):
        for category, prompts in TEST_PROMPTS.items():
            for prompt in prompts:
                for variant, mw_cls in [("A_passive", "passive"), ("B_forced_eval", "forced_eval")]:
                    result = await _run_single_trial(
                        llm, prompt, category, variant, mw_cls, model_label
                    )
                    summary.results.append(result)
                    done += 1
                    status = "OK" if not result.error else f"ERR: {result.error[:40]}"
                    print(
                        f"  [{done}/{total}] rep={rep+1} {variant} | {category} | "
                        f"{result.activated_skills or '{}'} | {status}"
                    )

    return summary


async def run_benchmark() -> dict[str, BenchmarkSummary]:
    """Run the full multi-model A/B benchmark."""
    repeats = int(os.getenv("BENCHMARK_REPEATS", "1"))
    model_filter_raw = os.getenv("BENCHMARK_MODELS", "")
    model_filter = [m.strip() for m in model_filter_raw.split(",") if m.strip()] if model_filter_raw else None

    results_by_model: dict[str, BenchmarkSummary] = {}

    for config in MODEL_CONFIGS:
        if model_filter and config["label"] not in model_filter:
            continue

        print(f"\n{'#' * 72}")
        print(f"# Starting benchmark: {config['label']} (repeats={repeats})")
        print(f"{'#' * 72}\n")

        llm = create_llm(provider=config["provider"], **config["model_kwargs"])
        summary = await _run_model_benchmark(llm, config["label"], repeats)
        results_by_model[config["label"]] = summary

        # Save per-model results immediately
        _save_model_results(summary)

    return results_by_model


def _save_model_results(summary: BenchmarkSummary) -> None:
    """Save results for a single model to JSON."""
    safe_label = summary.model_label.replace(":", "_").replace(".", "_")
    output_path = Path(__file__).parent / f"benchmark_results_{safe_label}.json"
    raw = []
    for r in summary.results:
        raw.append(
            {
                "model": r.model,
                "category": r.category,
                "prompt": r.prompt,
                "variant": r.variant,
                "activated_skills": sorted(r.activated_skills),
                "read_skill_calls": r.read_skill_calls,
                "latency_s": round(r.latency_s, 3),
                "error": r.error,
            }
        )
    output_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False))
    print(f"  -> Saved: {output_path}")


def _save_summary(summaries: dict[str, BenchmarkSummary]) -> None:
    """Save cross-model summary."""
    output_path = Path(__file__).parent / "benchmark_summary.json"
    data = {}
    for label, summary in summaries.items():
        data[label] = {
            "activation_rate_A": round(summary.activation_rate("A_passive"), 4),
            "activation_rate_B": round(summary.activation_rate("B_forced_eval"), 4),
            "false_positive_rate_A": round(summary.false_positive_rate("A_passive"), 4),
            "false_positive_rate_B": round(summary.false_positive_rate("B_forced_eval"), 4),
            "avg_latency_A": round(summary.avg_latency("A_passive"), 2),
            "avg_latency_B": round(summary.avg_latency("B_forced_eval"), 2),
            "total_trials": len(summary.results),
            "errors": summary.error_count("A_passive") + summary.error_count("B_forced_eval"),
        }
    output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"\nCross-model summary saved to: {output_path}")


def main() -> None:
    """Entry point."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    repeats = os.getenv("BENCHMARK_REPEATS", "1")
    models_env = os.getenv("BENCHMARK_MODELS", "(all)")
    print("Starting Skill Load Harness A/B Benchmark...")
    print(f"Models: {models_env}")
    print(f"Repeats: {repeats}")
    print(f"Skills: {list(SKILL_REGISTRY.keys())}")

    summaries = asyncio.run(run_benchmark())

    # Print per-model reports
    for summary in summaries.values():
        summary.print_report()

    # Print cross-model comparison
    if len(summaries) > 1:
        print_cross_model_report(summaries)

    _save_summary(summaries)


if __name__ == "__main__":
    main()
