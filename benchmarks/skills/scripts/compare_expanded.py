"""Expanded benchmark: A_passive vs B_NO_hints with 20 prompts per category.

7 categories × 20 prompts × 2 conditions = 280 trials.
Tests SkillActivator protocol effectiveness without hints.

Usage:
    SCALING_MODEL=qwen3.5:122b python benchmarks/skills/scripts/compare_expanded.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BENCHMARK_DIR = Path(__file__).resolve().parents[1]
RESULTS_DIR = Path(os.getenv("SKILLS_BENCHMARK_RESULTS_DIR", BENCHMARK_DIR / "results"))

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import benchmark_skill_harness as bm

# =============================================================================
# Expanded Test Prompts — 20 per category
# =============================================================================

EXPANDED_PROMPTS: dict[str, list[str]] = {
    # --- Activation expected: Stage 2 ---
    "stage2_direct": [
        "Evaluate target validation evidence and score druggability using genetic associations",
        "Query OpenTargets for target-disease association and GWAS gene-trait evidence",
        "Assess tractability and genetic support for the target gene panel",
        "Score each gene's druggability using OpenTargets association scores and GWAS p-values",
        "Run Stage 2 validation: check genetic evidence strength and target tractability profiles",
        "Retrieve target-disease association scores and SNP-trait p-values for all unique genes",
        "Evaluate whether the receptor gene has strong genetic support from GWAS and OpenTargets",
        "Assess the therapeutic potential by combining genetic association data with tractability",
        "Query genetic evidence databases to validate and prioritize the gene targets",
        "Perform target validation scoring using genome-wide association and target platform data",
        "Check OpenTargets safety and tractability bucket classification for each target",
        "Retrieve GWAS summary statistics and lead variants for the gene list",
        "Rank all unique genes by their combined genetic evidence and druggability scores",
        "Evaluate the target's association with the disease phenotype using GWAS catalog data",
        "Run target validation queries to determine which genes have actionable genetic evidence",
        "Assess whether each gene is genetically linked to the disease via OpenTargets evidence",
        "Query SNP-trait associations and compute genetic risk scores for the target panel",
        "Score tractability using antibody accessibility and small molecule binding site predictions",
        "Determine which targets pass the genetic validation threshold for further investigation",
        "Collect target-disease evidence scores and prioritize by overall association strength",
    ],
    # --- Activation expected: Stage 3 ---
    "stage3_direct": [
        "Perform deep dive: retrieve known drugs and clinical compound profiles via ChEMBL",
        "Query ChEMBL target profile for the featured candidate's drug landscape",
        "Investigate approved drugs and clinical trial compounds for this target",
        "Look up existing inhibitors and their IC50 values in ChEMBL for the featured gene",
        "Retrieve the drug compound pipeline and bioactivity data for this therapeutic target",
        "Check ChEMBL for any approved drugs, clinical candidates, or tool compounds",
        "Profile the featured target's drug landscape including selectivity and potency data",
        "Search for known bioactive molecules targeting this protein in ChEMBL",
        "Run Stage 3 deep dive: assess existing drug compounds and clinical development status",
        "Query drug discovery databases for compound activity profiles against this target",
        "Retrieve IC50 and Ki values for all known inhibitors of this target from ChEMBL",
        "Check the clinical development pipeline: are there drugs in Phase I/II/III for this target",
        "Look up approved therapeutics and their mechanism of action against this protein",
        "Search for selective tool compounds that could serve as starting points for drug design",
        "Profile the compound landscape including potency, selectivity, and ADMET properties",
        "Query bioactivity endpoints for all assays run against this target in ChEMBL",
        "Investigate whether any repurposable approved drugs target this protein",
        "Retrieve structure-activity relationship data for known compound series",
        "Check for PROTACs, molecular glues, or other novel modalities targeting this protein",
        "Assess the competitive drug landscape by reviewing all compounds in clinical trials",
    ],
    # --- Activation expected: composite ---
    "composite": [
        "Run full Stage 2 validation then Stage 3 deep dive for featured candidates",
        "Comprehensive target assessment: genetic evidence, druggability, and known compounds",
        "Complete assessment pipeline from GWAS evidence through drug compound profiling",
        "Execute the full 2-stage evaluation: first validate with genetic data, then profile drugs",
        "Assess both the genetic support and existing drug landscape for each featured target",
        "Run end-to-end target assessment combining GWAS validation with ChEMBL compound search",
        "Perform comprehensive evaluation: OpenTargets associations plus ChEMBL drug profiles",
        "Full pipeline: score genetic evidence, assess tractability, then check known compounds",
        "Validate targets with genetic databases and follow up with drug compound deep dive",
        "Complete the target assessment workflow from genetic scoring through drug profiling",
        "Run the full assessment: genetic validation with GWAS/OpenTargets then ChEMBL deep dive",
        "Evaluate the featured candidates end-to-end from genetic evidence to drug availability",
        "Comprehensive pipeline: GWAS associations, target tractability, then existing therapeutics",
        "First validate genetic support, then investigate what drugs exist for top-scoring targets",
        "Multi-database assessment: combine genetic risk evidence with compound activity profiles",
        "Full target evaluation covering both causal evidence and therapeutic accessibility",
        "Score genes for genetic support, then deep dive into drug compound data for top hits",
        "End-to-end druggability assessment from genome-wide evidence through clinical compounds",
        "Assess the complete evidence landscape: genetic associations and drug development status",
        "Two-phase evaluation: validate with genetic data first, then profile drug compounds",
    ],
    # --- FP expected: Stage 1 tools only ---
    "stage1_tools_only": [
        "Query KEGG pathways for the ligand gene and STRING PPI score for this L-R pair",
        "Run CELLxGENE census validation and Reactome pathway queries for biological context",
        "Gather Stage 1 biological context: pathways, PPI, and cell type expression",
        "Check the STRING protein-protein interaction confidence score for this ligand-receptor pair",
        "Map the ligand gene to KEGG pathways and retrieve Reactome pathway annotations",
        "Run census cross-validation to check cell type expression patterns for the gene pair",
        "Query biological context databases: pathway membership, PPI network, expression data",
        "Execute Stage 1 tools: KEGG pathway lookup, STRING PPI query, census validation",
        "Gather pathway and interaction evidence for the L-R pair using Stage 1 tools",
        "Check biological plausibility via pathway mapping and protein interaction scores",
        "Query Reactome for signaling cascades involving this ligand-receptor pair",
        "Retrieve KEGG pathway IDs where both genes co-occur as pathway members",
        "Check cell type specificity of expression using CELLxGENE census data",
        "Verify the PPI confidence score between ligand and receptor via STRING database",
        "Run all Stage 1 biological context queries for the next batch of L-R pairs",
        "Map genes to GO biological process terms and KEGG functional annotations",
        "Check whether the L-R pair co-localizes in known signaling pathways",
        "Retrieve pathway enrichment analysis results for the gene set",
        "Query STRING network neighbors to find additional interacting partners",
        "Finalize Stage 1 evidence collection with census cross-validation results",
    ],
    # --- FP expected: internal pipeline ---
    "internal_pipeline": [
        "Finalize Stage 1 artifacts and save all evidence files to the evidence directory",
        "Load LR candidates, organize collected data, and prepare for Stage 2",
        "Validate evidence completeness and generate the final drug.md report",
        "Save the current evidence batch to JSON and update the evidence index",
        "Load lr_candidates.json and extract unique gene symbols for the next stage",
        "Organize and merge all collected evidence files into a single assessment structure",
        "Run validate_quality on the accumulated evidence to check completeness",
        "Prepare the final target_assessment.json contract output for the report writer",
        "Clean up intermediate evidence files and consolidate into the final output",
        "Finalize all artifacts and hand off to the report writer subagent",
        "Check that all 30 L-R pairs have been processed and no evidence gaps remain",
        "Merge Stage 1 and Stage 2 evidence into a unified data structure",
        "Run the quality validation tool to ensure all required fields are populated",
        "Export the evidence summary as a structured JSON for downstream consumption",
        "Load the previously saved evidence files and verify data integrity",
        "Prepare the handoff package including all JSON artifacts for the report writer",
        "Update the evidence index with timestamps and completion status markers",
        "Archive intermediate working files and keep only the final consolidated output",
        "Run a final completeness check before triggering the report generation phase",
        "Save progress and create a checkpoint so the pipeline can resume if interrupted",
    ],
    # --- FP expected: general biology ---
    "general_biology": [
        "Explain the biological significance of the BRAF V600E mutation",
        "Describe the general function of tyrosine kinases in cell signaling",
        "Explain the role of ligand-receptor interactions in tumor microenvironment",
        "What is the JAK-STAT signaling pathway and how does it relate to immune response",
        "Describe how receptor tyrosine kinases transduce extracellular signals",
        "Explain the concept of druggability and what makes a protein target druggable",
        "What are the hallmarks of cancer and how do they relate to target identification",
        "Describe the difference between oncogenes and tumor suppressor genes",
        "Explain how spatial transcriptomics differs from single-cell RNA sequencing",
        "What is the tumor microenvironment and why is it important for drug targeting",
        "Describe the PI3K/AKT/mTOR pathway and its role in cell proliferation",
        "What is the difference between paracrine and autocrine signaling in tissues",
        "Explain how immune checkpoint proteins regulate T cell activation",
        "What are kinase inhibitors and how do they work at the molecular level",
        "Describe the role of the Wnt/beta-catenin pathway in stem cell maintenance",
        "What is epithelial-mesenchymal transition and its role in metastasis",
        "Explain the concept of synthetic lethality in cancer therapeutics",
        "How do monoclonal antibodies differ from small molecule drugs in mechanism",
        "Describe the role of angiogenesis in tumor progression",
        "What are the main cell types in the tumor immune microenvironment",
    ],
    # --- FP expected: data visualization ---
    "data_visualization": [
        "Visualize the Stage 2 scoring results as a heatmap",
        "Create a bar chart comparing druggability scores across all targets",
        "Draw the L-R interaction network showing PPI confidence scores",
        "Plot the distribution of combined_total scores across all assessed genes",
        "Generate a volcano plot of GWAS p-values vs effect sizes for the gene panel",
        "Create a summary table showing top-ranked candidates with their scores",
        "Visualize the pathway overlap between ligand and receptor genes",
        "Draw a radar chart comparing evidence dimensions for featured candidates",
        "Generate a publication-ready figure showing the 3-stage funnel results",
        "Create a dot plot ranking all genes by their druggability assessment score",
        "Plot a Sankey diagram showing how L-R pairs flow through the 3-stage funnel",
        "Create a forest plot of genetic association effect sizes across targets",
        "Generate a correlation matrix of evidence dimensions for all assessed genes",
        "Draw an upset plot showing overlap between different evidence categories",
        "Visualize the rubric scoring breakdown for each featured candidate",
        "Create a waterfall plot of combined scores ordered by rank",
        "Plot a bubble chart with genetic evidence vs druggability colored by stage",
        "Generate a multi-panel summary figure for the manuscript supplementary",
        "Draw a lollipop chart of the top 10 targets by combined assessment score",
        "Create an interactive dashboard showing all assessment metrics",
    ],
}

EXPANDED_EXPECTED: dict[str, set[str]] = {
    "stage2_direct": {"opentargets-database", "gwas-database"},
    "stage3_direct": {"chembl-database"},
    "composite": {"opentargets-database", "gwas-database", "chembl-database"},
    "stage1_tools_only": set(),
    "internal_pipeline": set(),
    "general_biology": set(),
    "data_visualization": set(),
}

FP_CATEGORIES = {cat for cat, exp in EXPANDED_EXPECTED.items() if not exp}

# =============================================================================
# Model Presets
# =============================================================================

MODEL_PRESETS: dict[str, dict] = {
    "qwen3.5:122b": {"provider": "ollama", "model_kwargs": {"model": "qwen3.5:122b"}},
    "qwen3.5:35b": {
        "provider": "ollama",
        "model_kwargs": {
            "model": "qwen3.5:35b",
            "num_predict": 512,
            "reasoning": False,
        },
    },
    "gpt-4.1": {"provider": "openai", "model_kwargs": {"model": "gpt-4.1"}},
    "gpt-4.1-mini": {"provider": "openai", "model_kwargs": {"model": "gpt-4.1-mini"}},
}

# =============================================================================
# Main
# =============================================================================


async def run_comparison():
    model_label = os.getenv("SCALING_MODEL", "qwen3.5:35b")
    if model_label not in MODEL_PRESETS:
        print(f"Unknown model: {model_label}. Available: {list(MODEL_PRESETS.keys())}")
        return

    preset = MODEL_PRESETS[model_label]
    llm = bm.create_llm(provider=preset["provider"], **preset["model_kwargs"])

    # Patch module-level constants for expanded prompts
    original_prompts = bm.TEST_PROMPTS
    original_expected = bm.EXPECTED_SKILLS
    original_fp = bm.FP_CATEGORIES
    original_all = bm.ALL_SKILLS

    bm.TEST_PROMPTS = EXPANDED_PROMPTS
    bm.EXPECTED_SKILLS = EXPANDED_EXPECTED
    bm.FP_CATEGORIES = FP_CATEGORIES
    bm.ALL_SKILLS = {"opentargets-database", "gwas-database", "chembl-database"}
    bm.STAGE_HINTS = {}  # NO hints

    conditions = [
        ("A_passive", "A_passive"),
        ("B_NO_hints", "B_forced_eval"),
    ]

    summaries: dict[str, bm.BenchmarkSummary] = {}

    for cond_name, variant in conditions:
        print(f"\n{'#' * 72}")
        print(f"# {cond_name} | {model_label} | 140 prompts | NO hints")
        print(f"{'#' * 72}\n")

        summary = bm.BenchmarkSummary(model_label=f"{model_label} ({cond_name})")
        total = sum(len(ps) for ps in EXPANDED_PROMPTS.values())
        done = 0

        for category, prompts in EXPANDED_PROMPTS.items():
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

    # Print reports
    for s in summaries.values():
        s.print_report()

    # Side-by-side
    v_map = {"A_passive": "A_passive", "B_NO_hints": "B_forced_eval"}

    print(f"\n{'=' * 65}")
    print(f"EXPANDED COMPARISON: {model_label} (20 prompts/category, NO hints)")
    print(f"{'=' * 65}")
    print(f"{'Metric':<25} {'A_passive':>18} {'B_NO_hints':>18}")
    print("-" * 65)

    for label, fn in [
        ("Activation rate", "activation_rate"),
        ("FP rate", "false_positive_rate"),
        ("Precision", "precision"),
        ("Recall", "recall"),
        ("Specificity", "specificity"),
        ("F1", "f1"),
        ("Avg latency", "avg_latency"),
    ]:
        v_a = getattr(summaries["A_passive"], fn)(v_map["A_passive"])
        v_b = getattr(summaries["B_NO_hints"], fn)(v_map["B_NO_hints"])
        delta = v_b - v_a
        if "latency" in label.lower():
            print(f"{label:<25} {v_a:>17.2f}s {v_b:>17.2f}s  (Δ={delta:+.2f}s)")
        else:
            print(f"{label:<25} {v_a:>17.1%} {v_b:>17.1%}  (Δ={delta:+.1%})")

    # Save aggregate
    safe_label = model_label.replace(":", "_").replace(".", "_")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = RESULTS_DIR / f"compare_expanded_{safe_label}.json"
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
    print(f"\nAggregate results saved: {output_path}")

    # =========================================================
    # Save per-trial results for statistical testing
    # =========================================================
    all_skills = sorted(EXPANDED_EXPECTED.get("composite", set()))  # all 3 skills
    trials_path = RESULTS_DIR / f"compare_expanded_{safe_label}_trials.jsonl"
    with open(trials_path, "w") as f:
        for cond_name, summary in summaries.items():
            for i, result in enumerate(summary.results):
                expected = EXPANDED_EXPECTED.get(result.category, set())
                # Per-skill binary decisions
                skill_decisions = {}
                for skill in all_skills:
                    should_activate = skill in expected
                    did_activate = skill in result.activated_skills
                    correct = (should_activate == did_activate)
                    skill_decisions[skill] = {
                        "expected": should_activate,
                        "activated": did_activate,
                        "correct": correct,
                    }
                row = {
                    "condition": cond_name,
                    "trial_idx": i,
                    "category": result.category,
                    "prompt": result.prompt,
                    "activated_skills": sorted(result.activated_skills),
                    "expected_skills": sorted(expected),
                    "skill_decisions": skill_decisions,
                    "error": result.error,
                }
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Per-trial results saved: {trials_path}")

    # =========================================================
    # Statistical Analysis: McNemar's + Bootstrap
    # =========================================================
    _run_statistical_analysis(summaries, all_skills, safe_label)

    # Restore module-level constants after all reports and artifacts have been
    # computed. Restoring earlier makes aggregate JSON and statistical JSON use
    # different expected-skill definitions.
    bm.TEST_PROMPTS = original_prompts
    bm.EXPECTED_SKILLS = original_expected
    bm.FP_CATEGORIES = original_fp
    bm.ALL_SKILLS = original_all


def _run_statistical_analysis(
    summaries: dict[str, Any],
    all_skills: list[str],
    safe_label: str,
):
    """Run McNemar's test and Bootstrap F1 CI on per-trial results."""
    import numpy as np
    from scipy import stats as sp_stats

    print(f"\n{'=' * 72}")
    print("STATISTICAL ANALYSIS")
    print(f"{'=' * 72}")

    a_summary = summaries["A_passive"]
    b_summary = summaries["B_NO_hints"]

    # Build paired binary arrays: 1=correct, 0=incorrect
    # Each trial × skill = one decision
    a_decisions = []  # (y_true, y_pred) per skill-decision
    b_decisions = []
    a_correct = []
    b_correct = []

    for i, (a_result, b_result) in enumerate(zip(a_summary.results, b_summary.results)):
        if a_result.error or b_result.error:
            continue
        expected = EXPANDED_EXPECTED.get(a_result.category, set())
        for skill in all_skills:
            should = skill in expected
            a_did = skill in a_result.activated_skills
            b_did = skill in b_result.activated_skills
            a_decisions.append((should, a_did))
            b_decisions.append((should, b_did))
            a_correct.append(int(should == a_did))
            b_correct.append(int(should == b_did))

    a_correct = np.array(a_correct)
    b_correct = np.array(b_correct)
    n_decisions = len(a_correct)

    print(f"\nTotal paired skill-decisions: {n_decisions}")
    print(f"A correct: {a_correct.sum()}/{n_decisions} ({a_correct.mean():.1%})")
    print(f"B correct: {b_correct.sum()}/{n_decisions} ({b_correct.mean():.1%})")

    # --- McNemar's Test ---
    print(f"\n--- McNemar's Test ({n_decisions} paired decisions) ---")
    both_correct = int(((a_correct == 1) & (b_correct == 1)).sum())
    only_a = int(((a_correct == 1) & (b_correct == 0)).sum())  # b
    only_b = int(((a_correct == 0) & (b_correct == 1)).sum())  # c
    both_wrong = int(((a_correct == 0) & (b_correct == 0)).sum())

    print(f"\n  Contingency table:")
    print(f"                    B correct  B incorrect")
    print(f"  A correct           {both_correct:>5}        {only_a:>5}")
    print(f"  A incorrect         {only_b:>5}        {both_wrong:>5}")
    print(f"\n  Concordant: {both_correct + both_wrong} | Discordant: {only_a + only_b}")
    print(f"  Only A correct (b): {only_a}")
    print(f"  Only B correct (c): {only_b}")

    if only_a + only_b > 0:
        # Chi-square with continuity correction
        chi2_stat = (abs(only_a - only_b) - 1) ** 2 / (only_a + only_b)
        chi2_p = 1 - sp_stats.chi2.cdf(chi2_stat, df=1)
        # Without continuity correction
        chi2_stat_nc = (only_a - only_b) ** 2 / (only_a + only_b)
        chi2_p_nc = 1 - sp_stats.chi2.cdf(chi2_stat_nc, df=1)
        # Exact (binomial)
        exact_result = sp_stats.binomtest(only_a, only_a + only_b, 0.5)
        exact_p = exact_result.pvalue
        # Odds ratio
        odds_ratio = only_b / only_a if only_a > 0 else float("inf")

        print(f"\n  McNemar chi2 (corrected):   chi2={chi2_stat:.3f}, p={chi2_p:.6f}")
        print(f"  McNemar chi2 (uncorrected): chi2={chi2_stat_nc:.3f}, p={chi2_p_nc:.6f}")
        print(f"  McNemar exact (binomial):   p={exact_p:.6f}")
        print(f"  Odds ratio (c/b):           {odds_ratio:.2f}")

        sig = "***" if exact_p < 0.001 else "**" if exact_p < 0.01 else "*" if exact_p < 0.05 else "n.s."
        print(f"  Significance: {sig}")
    else:
        print("  No discordant pairs — cannot run McNemar's test")

    # --- Bootstrap F1 CI ---
    print(f"\n--- Bootstrap F1 Difference (BCa, 10000 resamples) ---")

    y_true = np.array([int(d[0]) for d in a_decisions])
    y_pred_a = np.array([int(d[1]) for d in a_decisions])
    y_pred_b = np.array([int(d[1]) for d in b_decisions])

    def _f1(y_t, y_p):
        tp = ((y_t == 1) & (y_p == 1)).sum()
        fp = ((y_t == 0) & (y_p == 1)).sum()
        fn = ((y_t == 1) & (y_p == 0)).sum()
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        return 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0

    f1_a_obs = _f1(y_true, y_pred_a)
    f1_b_obs = _f1(y_true, y_pred_b)
    f1_diff_obs = f1_b_obs - f1_a_obs

    print(f"  Observed F1_A: {f1_a_obs:.4f}")
    print(f"  Observed F1_B: {f1_b_obs:.4f}")
    print(f"  Observed diff: {f1_diff_obs:+.4f}")

    # Bootstrap at prompt level (resample 140 prompts, 3 skills each)
    n_prompts = n_decisions // len(all_skills)
    n_skills = len(all_skills)
    rng = np.random.default_rng(42)
    n_boot = 10000
    boot_diffs = []

    for _ in range(n_boot):
        idx_prompts = rng.choice(n_prompts, size=n_prompts, replace=True)
        idx = np.concatenate([idx_prompts * n_skills + s for s in range(n_skills)])
        f1_a_b = _f1(y_true[idx], y_pred_a[idx])
        f1_b_b = _f1(y_true[idx], y_pred_b[idx])
        boot_diffs.append(f1_b_b - f1_a_b)

    boot_diffs = np.array(boot_diffs)

    # Percentile CI
    ci_lo = np.percentile(boot_diffs, 2.5)
    ci_hi = np.percentile(boot_diffs, 97.5)
    # Bootstrap p-value
    boot_p = (boot_diffs <= 0).mean()

    print(f"\n  Bootstrap (prompt-level resampling, n={n_boot}):")
    print(f"  95% CI (percentile): [{ci_lo:+.4f}, {ci_hi:+.4f}]")
    print(f"  Bootstrap p-value:   {boot_p:.6f}")
    print(f"  Mean diff:           {boot_diffs.mean():+.4f}")
    print(f"  Std diff:            {boot_diffs.std():.4f}")

    if ci_lo > 0:
        print(f"  => CI entirely above 0: B is SIGNIFICANTLY better than A")
    else:
        print(f"  => CI includes 0: difference NOT significant at 95%")

    # --- Cohen's h (effect size) ---
    print(f"\n--- Effect Size (Cohen's h) ---")
    h = 2 * np.arcsin(np.sqrt(f1_b_obs)) - 2 * np.arcsin(np.sqrt(f1_a_obs))
    size = "large" if abs(h) >= 0.8 else "medium" if abs(h) >= 0.5 else "small"
    print(f"  Cohen's h = {h:.4f} ({size} effect)")

    # --- Summary ---
    print(f"\n{'=' * 72}")
    print("STATISTICAL SUMMARY")
    print(f"{'=' * 72}")
    print(f"  F1 difference:        {f1_diff_obs:+.1%} ({f1_a_obs:.1%} → {f1_b_obs:.1%})")
    print(f"  McNemar exact p:      {exact_p:.6f}" if (only_a + only_b > 0) else "  McNemar: N/A")
    print(f"  Bootstrap 95% CI:     [{ci_lo:+.4f}, {ci_hi:+.4f}]")
    print(f"  Bootstrap p:          {boot_p:.6f}")
    print(f"  Cohen's h:            {h:.4f} ({size})")

    # Save statistical results
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stat_path = RESULTS_DIR / f"compare_expanded_{safe_label}_stats.json"
    stat_data = {
        "n_decisions": n_decisions,
        "f1_A": round(f1_a_obs, 4),
        "f1_B": round(f1_b_obs, 4),
        "f1_diff": round(f1_diff_obs, 4),
        "mcnemar": {
            "both_correct": both_correct,
            "only_A_correct": only_a,
            "only_B_correct": only_b,
            "both_wrong": both_wrong,
            "chi2_corrected": round(chi2_stat, 4) if (only_a + only_b > 0) else None,
            "p_corrected": round(chi2_p, 6) if (only_a + only_b > 0) else None,
            "p_exact": round(exact_p, 6) if (only_a + only_b > 0) else None,
        },
        "bootstrap": {
            "n_resamples": n_boot,
            "ci_lo": round(ci_lo, 4),
            "ci_hi": round(ci_hi, 4),
            "p_value": round(boot_p, 6),
            "method": "prompt-level resampling, percentile CI",
        },
        "cohens_h": round(h, 4),
        "effect_size": size,
    }
    stat_path.write_text(json.dumps(stat_data, indent=2))
    print(f"\nStatistical results saved: {stat_path}")


if __name__ == "__main__":
    asyncio.run(run_comparison())
