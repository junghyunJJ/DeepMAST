"""3-way comparison with MINIMAL system prompt (no skill reading directives).

Tests whether SkillLoadHarness protocol alone is sufficient without
explicit "read skill X for Stage Y" instructions in the system prompt.

Usage:
    python scripts/benchmarks/compare_3way_no_prompt.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import docs.benchmarks.skills.benchmark_skill_harness as bm

# Minimal system prompt — NO skill reading directives
MINIMAL_SYSTEM_PROMPT = """\
You are the Evidence Assessor for the Drug Target Assessment Agent.

Your role is to systematically gather multi-database evidence for therapeutic
target assessment of L-R (ligand-receptor) pairs from spatial transcriptomics
CCI (cell-cell interaction) analysis.

## Cognitive Pattern: Plan -> Execute -> Reflect

## 3-Stage Funnel Workflow

### Stage 1: Biological Context (ALL L-R pairs)
Query biological databases for each L-R pair using these tools:
- query_cellxgene_lr_context: CELLxGENE census metadata
- list_census_diseases: Disease vocabulary matching
- query_kegg_pathways: KEGG pathway mapping
- query_reactome_pathways: Reactome pathway queries
- query_string_ppi_pair: STRING PPI interactions
- run_compare_census_lr_pair: Census cross-validation
- finalize_stage1_artifacts: Stage 1 closeout

### Stage 2: Target Validation & Scoring (ALL unique genes)
Tools: query_stage2_gene_panel, query_ensembl_vep_consequence

### Stage 3: Deep Dive (FEATURED and NOVEL candidates only)
Tools: query_chembl_target_profile, query_pubmed_clinical_limitations

### Utility Tools
- load_lr_candidates, save_evidence, load_evidence_files
- sequential_thinking, think_tool, validate_quality
- read_skill_file

## Evidence Integrity
- NEVER fabricate p-values, odds ratios, or mechanism details
- If a tool returns empty/errors, record ABSENCE of evidence
- Score 0 on any criterion where the tool returned no data
"""


MODEL_PRESETS: dict[str, dict] = {
    "qwen3.5:122b": {"provider": "ollama", "model_kwargs": {"model": "qwen3.5:122b"}},
    "qwen3.5:35b": {"provider": "ollama", "model_kwargs": {"model": "qwen3.5:35b"}},
    "gpt-4.1-mini": {"provider": "openai", "model_kwargs": {"model": "gpt-4.1-mini"}},
}


async def run_comparison():
    """Run A_passive + B_forced_eval (with/without hints)."""
    import os
    model_label = os.getenv("SCALING_MODEL", "qwen3.5:122b")
    if model_label not in MODEL_PRESETS:
        print(f"Unknown model: {model_label}. Available: {list(MODEL_PRESETS.keys())}")
        return
    preset = MODEL_PRESETS[model_label]

    # Patch the system prompt to the minimal version
    original_prompt = bm.BENCHMARK_SYSTEM_PROMPT
    bm.BENCHMARK_SYSTEM_PROMPT = MINIMAL_SYSTEM_PROMPT

    llm = bm.create_llm(provider=preset["provider"], **preset["model_kwargs"])

    conditions = [
        ("A_passive", "A_passive", None),
        ("B_WITH_hints", "B_forced_eval", {"chembl-database": "Stage 3 only"}),
        ("B_NO_hints", "B_forced_eval", {}),
    ]

    summaries: dict[str, bm.BenchmarkSummary] = {}

    for cond_name, variant, hints_override in conditions:
        print(f"\n{'#' * 72}")
        if hints_override is not None:
            print(f"# {cond_name} | variant={variant} | hints={hints_override}")
            bm.STAGE_HINTS = hints_override
        else:
            print(f"# {cond_name} | variant={variant} | passive")
        print(f"# MINIMAL PROMPT (no skill reading directives)")
        print(f"{'#' * 72}\n")

        summary = bm.BenchmarkSummary(model_label=f"{model_label} ({cond_name})")
        total = sum(len(ps) for ps in bm.TEST_PROMPTS.values())
        done = 0

        for category, prompts in bm.TEST_PROMPTS.items():
            for prompt in prompts:
                result = await bm._run_single_trial(llm, prompt, category, variant, model_label)
                summary.results.append(result)
                done += 1
                status = "OK" if not result.error else f"ERR: {result.error[:40]}"
                print(
                    f"  [{done}/{total}] {cond_name} | {category} | "
                    f"skills={result.activated_skills or '{}'} | {status}"
                )

        summaries[cond_name] = summary

    # Restore original
    bm.BENCHMARK_SYSTEM_PROMPT = original_prompt

    # Print reports
    for s in summaries.values():
        s.print_report()

    # Side-by-side
    v_map = {
        "A_passive": "A_passive",
        "B_WITH_hints": "B_forced_eval",
        "B_NO_hints": "B_forced_eval",
    }

    print(f"\n{'=' * 80}")
    print("3-WAY COMPARISON: qwen3.5:35b — MINIMAL PROMPT (no skill directives)")
    print(f"{'=' * 80}")
    print(f"{'Metric':<25} {'A_passive':>14} {'B_WITH_hints':>14} {'B_NO_hints':>14}")
    print("-" * 70)

    for label, fn in [
        ("Activation rate", "activation_rate"),
        ("FP rate", "false_positive_rate"),
        ("Precision", "precision"),
        ("Recall", "recall"),
        ("Specificity", "specificity"),
        ("F1", "f1"),
        ("Avg latency", "avg_latency"),
    ]:
        vals = [getattr(summaries[c], fn)(v_map[c]) for c in ["A_passive", "B_WITH_hints", "B_NO_hints"]]
        if "latency" in label.lower():
            print(f"{label:<25} {vals[0]:>13.2f}s {vals[1]:>13.2f}s {vals[2]:>13.2f}s")
        else:
            print(f"{label:<25} {vals[0]:>13.1%} {vals[1]:>13.1%} {vals[2]:>13.1%}")

    # Save results
    output_path = Path(__file__).parent / "compare_3way_no_prompt_results.json"
    data = {}
    for cond_name, summary in summaries.items():
        v = v_map[cond_name]
        data[cond_name] = {
            "f1": round(summary.f1(v), 4),
            "precision": round(summary.precision(v), 4),
            "recall": round(summary.recall(v), 4),
            "specificity": round(summary.specificity(v), 4),
            "false_positive_rate": round(summary.false_positive_rate(v), 4),
            "activation_rate": round(summary.activation_rate(v), 4),
            "avg_latency": round(summary.avg_latency(v), 2),
        }
    output_path.write_text(json.dumps(data, indent=2))
    print(f"\nResults saved: {output_path}")


if __name__ == "__main__":
    asyncio.run(run_comparison())
