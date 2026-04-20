"""A/B benchmark: SkillsMiddleware (passive) vs SkillLoadHarness (forced-eval).

Compares skill activation rates across multiple models:
  A) SkillsMiddleware — passive listing (current baseline)
  B) SkillLoadHarness — forced 3-step evaluation (new approach)
  B1) Stage-gated — pre-filter registry by keywords
  B2) NO-bias protocol — negative examples + default-NO framing
  B3) Two-phase — classify task then evaluate skills
  B4) Minimal descriptions — strict criteria + TOOL-ONLY labels

v2: Updated for real agent fidelity.
  - Medium-fidelity system prompt with 3-stage funnel and tool context
  - Real tool-calling loop via bind_tools([read_skill_file])
  - Stage-gated expected skills (opentargets+gwas for Stage 2, chembl for Stage 3)
  - All 5 skills in registry (tests correct YES and correct NO decisions)
  - Enhanced metrics: precision, recall, specificity, F1

Usage:
    python docs/benchmarks/skills/benchmark_skill_harness.py

Environment:
    BENCHMARK_MODELS: Comma-separated model labels (default: all)
    BENCHMARK_REPEATS: Runs per prompt (default: 1)
    BENCHMARK_VARIANTS: Comma-separated variant names (default: all)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.agents.model import create_llm
from src.agents.shared.skill_load_harness import SkillLoadHarness
from src.agents.shared.skills_middleware import SkillsMiddleware
from src.agents.drug_target.tools.skill_reader import read_skill_file

try:
    from scipy.stats import wilcoxon
except Exception:
    wilcoxon = None

logger = logging.getLogger(__name__)

# =============================================================================
# Medium-Fidelity System Prompt (self-contained, not imported from production)
# =============================================================================

BENCHMARK_SYSTEM_PROMPT = """\
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

Stage 1 is TOOL-DRIVEN. Do NOT read skill documents for Stage 1.
kegg-database and string-database are accessed via tools (query_kegg_pathways,
query_string_ppi_pair) — do NOT read their SKILL.md files.

### Stage 2: Target Validation & Scoring (ALL unique genes)
Before starting Stage 2, read these skill guides for evidence interpretation:
- read_skill_file("skills/opentargets-database/SKILL.md")
- read_skill_file("skills/gwas-database/SKILL.md")

Tools: query_stage2_gene_panel, query_ensembl_vep_consequence

### Stage 3: Deep Dive (FEATURED and NOVEL candidates only)
Before calling query_chembl_target_profile, read the ChEMBL skill guide:
- read_skill_file("skills/chembl-database/SKILL.md")

Do NOT read separate pathway, STRING, or Census skill documents for this workflow.

Tools: query_chembl_target_profile, query_pubmed_clinical_limitations

### Utility Tools
- load_lr_candidates, save_evidence, load_evidence_files
- sequential_thinking, think_tool, validate_quality
- read_skill_file

## Evidence Integrity
- NEVER fabricate p-values, odds ratios, or mechanism details
- If a tool returns empty/errors, record ABSENCE of evidence
- Score 0 on any criterion where the tool returned no data

## When NOT to Read Skills (CRITICAL)
Do NOT call read_skill_file for:
- Stage 1 tasks (pathways, PPI, census queries): Use tools DIRECTLY. No skill reading.
- Internal pipeline tasks (save, load, finalize, validate artifacts): No skill reading.
- Data visualization or report generation: No skill reading.
- General biology explanations: No skill reading.

ONLY read skills when explicitly performing:
- Stage 2 target validation/scoring → read opentargets + gwas skills
- Stage 3 deep dive on drug compounds → read chembl skill

If the task does NOT involve target validation scoring or drug compound profiling,
do NOT call read_skill_file. When in doubt, do NOT read skills.
"""

# =============================================================================
# Model Configurations
# =============================================================================

MODEL_CONFIGS: list[dict[str, Any]] = [
    {"label": "qwen3:14b", "provider": "ollama", "model_kwargs": {"model": "qwen3:14b"}},
    {"label": "qwen3.5:35b", "provider": "ollama", "model_kwargs": {"model": "qwen3.5:35b"}},
    {"label": "qwen3.5:122b", "provider": "ollama", "model_kwargs": {"model": "qwen3.5:122b"}},
    {"label": "gpt-4.1-mini", "provider": "openai", "model_kwargs": {"model": "gpt-4.1-mini"}},
]

# =============================================================================
# Test Prompts — stage-contextualized
# =============================================================================

TEST_PROMPTS: dict[str, list[str]] = {
    # --- Activation expected ---
    "stage2_direct": [
        "Evaluate target validation evidence and score druggability using genetic associations",
        "Query OpenTargets for target-disease association and GWAS gene-trait evidence",
        "Assess tractability and genetic support for the target gene panel",
    ],
    "stage3_direct": [
        "Perform deep dive: retrieve known drugs and clinical compound profiles via ChEMBL",
        "Query ChEMBL target profile for the featured candidate's drug landscape",
        "Investigate approved drugs and clinical trial compounds for this target",
    ],
    "composite": [
        "Run full Stage 2 validation then Stage 3 deep dive for featured candidates",
        "Comprehensive target assessment: genetic evidence, druggability, and known compounds",
        "Complete assessment pipeline from GWAS evidence through drug compound profiling",
    ],
    # --- FP expected (no skill reading) ---
    "stage1_tools_only": [
        "Query KEGG pathways for the ligand gene and STRING PPI score for this L-R pair",
        "Run CELLxGENE census validation and Reactome pathway queries for biological context",
        "Gather Stage 1 biological context: pathways, PPI, and cell type expression",
    ],
    "internal_pipeline": [
        "Finalize Stage 1 artifacts and save all evidence files to the evidence directory",
        "Load LR candidates, organize collected data, and prepare for Stage 2",
        "Validate evidence completeness and generate the final drug.md report",
    ],
    "general_biology": [
        "Explain the biological significance of the BRAF V600E mutation",
        "Describe the general function of tyrosine kinases in cell signaling",
        "Explain the role of ligand-receptor interactions in tumor microenvironment",
    ],
    "data_visualization": [
        "Visualize the Stage 2 scoring results as a heatmap",
        "Create a bar chart comparing druggability scores across all targets",
        "Draw the L-R interaction network showing PPI confidence scores",
    ],
}

# Expected skill activations per category — stage-gated ground truth
EXPECTED_SKILLS: dict[str, set[str]] = {
    # Activation categories — which skills should be READ
    "stage2_direct": {"opentargets-database", "gwas-database"},
    "stage3_direct": {"chembl-database"},
    "composite": {"opentargets-database", "gwas-database", "chembl-database"},
    # FP categories — NO skill reading expected
    "stage1_tools_only": set(),
    "internal_pipeline": set(),
    "general_biology": set(),
    "data_visualization": set(),
}

FP_CATEGORIES: set[str] = {cat for cat, expected in EXPECTED_SKILLS.items() if not expected}

# Skill registry — 3 skills (kegg/string removed: tool-only, never read)
SKILL_REGISTRY: dict[str, str] = {
    "opentargets-database": str(_PROJECT_ROOT / "skills" / "opentargets-database"),
    "gwas-database": str(_PROJECT_ROOT / "skills" / "gwas-database"),
    "chembl-database": str(_PROJECT_ROOT / "skills" / "chembl-database"),
}

STAGE_HINTS: dict[str, str] = {}

ALL_SKILLS = set(SKILL_REGISTRY.keys())

# =============================================================================
# Experimental Variants
# =============================================================================

# All experimental variants
VARIANTS = [
    "A_passive",       # Baseline: SkillsMiddleware
    "B_forced_eval",   # Baseline: SkillLoadHarness (original SKILL.md)
    "B1_stage_gated",  # Approach 1: Pre-filter registry by keywords
    "B2_no_bias",      # Approach 2: NO-bias protocol + negative examples
    "B3_two_phase",    # Approach 3: Two-phase (classify then evaluate)
    "B4_minimal_desc", # Approach 4: Minimal descriptions + strict criteria
]

# Environment variable to select variants (default: all)
# e.g., BENCHMARK_VARIANTS=A_passive,B2_no_bias

# =============================================================================
# Stage-Gated Keyword Filter (Approach B1)
# =============================================================================

STAGE2_TRIGGERS = {"stage 2", "validation", "scoring", "druggability", "genetic association",
                   "tractability", "opentargets", "gwas", "target-disease"}
STAGE3_TRIGGERS = {"stage 3", "deep dive", "drug", "compound", "chembl", "clinical trial",
                   "approved drug", "drug landscape"}
FP_TRIGGERS = {"stage 1", "pathway", "ppi", "kegg", "string", "finalize", "save evidence",
               "load", "visualiz", "heatmap", "bar chart", "explain", "describe", "biological context",
               "census", "reactome", "cellxgene"}

STAGE2_SKILLS = {"opentargets-database", "gwas-database"}
STAGE3_SKILLS = {"chembl-database"}


def _filter_registry_by_keywords(prompt: str) -> dict[str, str]:
    """Pre-filter SKILL_REGISTRY based on prompt keywords (Approach B1)."""
    prompt_lower = prompt.lower()
    # FP triggers → empty registry
    if any(t in prompt_lower for t in FP_TRIGGERS):
        return {}
    filtered = {}
    if any(t in prompt_lower for t in STAGE2_TRIGGERS):
        filtered.update({k: v for k, v in SKILL_REGISTRY.items() if k in STAGE2_SKILLS})
    if any(t in prompt_lower for t in STAGE3_TRIGGERS):
        filtered.update({k: v for k, v in SKILL_REGISTRY.items() if k in STAGE3_SKILLS})
    return filtered if filtered else SKILL_REGISTRY  # fallback to all if no match


# =============================================================================
# Protocol Templates for B2, B3, B4
# =============================================================================

# Approach B2: NO-bias protocol with negative examples
B2_NO_BIAS_PROTOCOL = """

# Skill Evaluation Protocol

## Default: NO SKILLS NEEDED
Most tasks do NOT require reading skill documents. Start by assuming NONE are needed.

## Step 1 - QUICK SCREEN
Answer this FIRST: "Does this task require interpreting external database results
(OpenTargets, GWAS, ChEMBL) for target validation scoring or drug compound assessment?"
- If NO → Write "NO_SKILLS_NEEDED" and skip to Step 3.
- If YES → Proceed to Step 2.

## Step 2 - EVALUATE (only if Step 1 = YES)
For each skill in {{available_skills}}, state YES or NO:
- YES = task EXPLICITLY requires reading this database's interpretation guide
- NO = everything else (default)

### Negative Examples (always NO):
- "Query KEGG pathways for ligand" → NO for all (tool-driven, no skill needed)
- "Finalize Stage 1 artifacts" → NO for all (internal pipeline task)
- "Visualize scoring results" → NO for all (data visualization)
- "Explain BRAF V600E mutation" → NO for all (general biology knowledge)
- kegg-database → ALWAYS NO (accessed via query_kegg_pathways tool)
- string-database → ALWAYS NO (accessed via query_string_ppi_pair tool)

### Positive Examples (YES):
- "Evaluate target validation using genetic associations" → YES for opentargets + gwas
- "Query ChEMBL target profile for drug landscape" → YES for chembl

## Step 3 - IMPLEMENT
Proceed with the task. Reference activated skill guidance only if skills were loaded.
"""

# Approach B3: Two-phase evaluation (classify then evaluate)
B3_TWO_PHASE_PROTOCOL = """

# Skill Evaluation Protocol

## Phase 1 - CLASSIFY TASK
Determine the task category:
- STAGE_1: Biological context (pathways, PPI, census, cellxgene) → NO skills needed
- STAGE_2: Target validation & scoring (OpenTargets, GWAS, druggability) → opentargets + gwas skills
- STAGE_3: Deep dive on drug compounds (ChEMBL, clinical trials) → chembl skill
- PIPELINE: Internal tasks (save, load, finalize, validate) → NO skills needed
- OTHER: General biology, visualization, reporting → NO skills needed

State: "TASK CATEGORY: [category]"

## Phase 2 - ACTIVATE (based on Phase 1)
- STAGE_1 / PIPELINE / OTHER → Write "NO_SKILLS_NEEDED". Skip to Phase 3.
- STAGE_2 → Evaluate ONLY opentargets-database and gwas-database from {{available_skills}}.
- STAGE_3 → Evaluate ONLY chembl-database from {{available_skills}}.
- If task spans STAGE_2 + STAGE_3 → Evaluate opentargets + gwas + chembl.

For each evaluated skill: [skill-name] — YES / NO — [one-sentence reasoning]
For YES skills: call read_skill_file(skill_path="<path>") to load instructions.

## Phase 3 - IMPLEMENT
Proceed with the task.
"""

# Approach B4: Minimal descriptions + strict criteria
B4_MINIMAL_DESC_SKILLS = """\
- opentargets-database — Stage 2: target-disease scoring guide
- gwas-database — Stage 2: genetic association interpretation guide
- chembl-database — Stage 3: drug compound profiling guide
- kegg-database — TOOL-ONLY: never read (use query_kegg_pathways tool instead)
- string-database — TOOL-ONLY: never read (use query_string_ppi_pair tool instead)"""

B4_MINIMAL_PROTOCOL = """

# Skill Evaluation

Available skills:
{{available_skills}}

## Rules
- Skills marked "TOOL-ONLY" → ALWAYS NO. These are accessed via tools, never via skill reading.
- Stage 2 skills → YES only if your task explicitly involves target validation scoring or druggability assessment.
- Stage 3 skills → YES only if your task explicitly involves drug compound profiling or ChEMBL queries.
- If unsure → NO for all skills.
- If no skill is needed → Write "NO_SKILLS_NEEDED" and proceed with the task.

For YES skills: call read_skill_file(skill_path="<path>") to load the guide.
Then proceed with the task.
"""


# =============================================================================
# Render Functions for B2, B3, B4
# =============================================================================


async def _render_b2_prompt(base_prompt: str) -> str:
    """Render B2 (NO-bias + negative examples) protocol."""
    harness = SkillLoadHarness(skill_registry=SKILL_REGISTRY)
    skills_block = harness._format_available_skills()
    protocol = B2_NO_BIAS_PROTOCOL.replace("{{available_skills}}", skills_block)
    return base_prompt + protocol


async def _render_b3_prompt(base_prompt: str) -> str:
    """Render B3 (two-phase classification) protocol."""
    harness = SkillLoadHarness(skill_registry=SKILL_REGISTRY)
    skills_block = harness._format_available_skills()
    protocol = B3_TWO_PHASE_PROTOCOL.replace("{{available_skills}}", skills_block)
    return base_prompt + protocol


async def _render_b4_prompt(base_prompt: str) -> str:
    """Render B4 (minimal descriptions) protocol."""
    protocol = B4_MINIMAL_PROTOCOL.replace("{{available_skills}}", B4_MINIMAL_DESC_SKILLS)
    return base_prompt + protocol


# =============================================================================
# Result Types
# =============================================================================


@dataclass
class TrialResult:
    """Result from a single benchmark trial."""

    model: str = ""
    category: str = ""
    prompt: str = ""
    variant: str = ""
    activated_skills: set[str] = field(default_factory=set)
    tool_history: list[dict[str, Any]] = field(default_factory=list)
    latency_s: float = 0.0
    error: str | None = None


@dataclass
class BenchmarkSummary:
    """Aggregated benchmark results for a single model."""

    model_label: str = ""
    results: list[TrialResult] = field(default_factory=list)

    def _variant_results(self, variant: str) -> list[TrialResult]:
        return [r for r in self.results if r.variant == variant and not r.error]

    def _unique_variants(self) -> list[str]:
        """Get unique variants in order of VARIANTS list."""
        seen = set()
        result = []
        for r in self.results:
            if r.variant not in seen:
                seen.add(r.variant)
                result.append(r.variant)
        return result

    def activation_rate(self, variant: str) -> float:
        """Fraction of activation-expected trials where at least one expected skill was activated."""
        vr = [r for r in self._variant_results(variant) if r.category not in FP_CATEGORIES]
        if not vr:
            return 0.0
        hits = sum(1 for r in vr if r.activated_skills & EXPECTED_SKILLS.get(r.category, set()))
        return hits / len(vr)

    def false_positive_rate(self, variant: str) -> float:
        """Fraction of FP-category trials that activated skills anyway."""
        fp_trials = [r for r in self._variant_results(variant) if r.category in FP_CATEGORIES]
        if not fp_trials:
            return 0.0
        return sum(1 for r in fp_trials if r.activated_skills) / len(fp_trials)

    def precision(self, variant: str) -> float:
        """Of activated skills across all trials, how many were expected?"""
        tp, fp_count = 0, 0
        for r in self._variant_results(variant):
            expected = EXPECTED_SKILLS.get(r.category, set())
            tp += len(r.activated_skills & expected)
            fp_count += len(r.activated_skills - expected)
        total = tp + fp_count
        return tp / total if total else 0.0

    def recall(self, variant: str) -> float:
        """Of expected skills across activation-expected trials, how many were activated?"""
        tp, fn = 0, 0
        for r in self._variant_results(variant):
            expected = EXPECTED_SKILLS.get(r.category, set())
            if not expected:
                continue
            tp += len(r.activated_skills & expected)
            fn += len(expected - r.activated_skills)
        total = tp + fn
        return tp / total if total else 0.0

    def specificity(self, variant: str) -> float:
        """Of non-expected skills, how many were correctly NOT activated?"""
        tn, fp_count = 0, 0
        for r in self._variant_results(variant):
            expected = EXPECTED_SKILLS.get(r.category, set())
            non_expected = ALL_SKILLS - expected
            tn += len(non_expected - r.activated_skills)
            fp_count += len(r.activated_skills - expected)
        total = tn + fp_count
        return tn / total if total else 0.0

    def f1(self, variant: str) -> float:
        """Harmonic mean of precision and recall."""
        p, r = self.precision(variant), self.recall(variant)
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def avg_latency(self, variant: str) -> float:
        times = [r.latency_s for r in self._variant_results(variant)]
        return sum(times) / len(times) if times else 0.0

    def error_count(self, variant: str) -> int:
        return sum(1 for r in self.results if r.variant == variant and r.error)

    def per_skill_accuracy(self, variant: str) -> dict[str, dict[str, int]]:
        """Per-skill YES/NO accuracy (especially kegg/string should be NO)."""
        stats: dict[str, dict[str, int]] = {
            name: {"tp": 0, "fp": 0, "tn": 0, "fn": 0} for name in ALL_SKILLS
        }
        for r in self._variant_results(variant):
            expected = EXPECTED_SKILLS.get(r.category, set())
            for skill in ALL_SKILLS:
                should_activate = skill in expected
                did_activate = skill in r.activated_skills
                if should_activate and did_activate:
                    stats[skill]["tp"] += 1
                elif should_activate and not did_activate:
                    stats[skill]["fn"] += 1
                elif not should_activate and did_activate:
                    stats[skill]["fp"] += 1
                else:
                    stats[skill]["tn"] += 1
        return stats

    def print_report(self) -> None:
        """Print a formatted comparison table for this model."""
        print(f"\n{'=' * 80}")
        print(f"MODEL: {self.model_label}")
        print("=" * 80)

        for variant in self._unique_variants():
            errors = self.error_count(variant)
            print(f"\n--- {variant} ---")
            print(f"  Activation rate:     {self.activation_rate(variant):.1%}")
            print(f"  False positive rate: {self.false_positive_rate(variant):.1%}")
            print(f"  Precision:           {self.precision(variant):.1%}")
            print(f"  Recall:              {self.recall(variant):.1%}")
            print(f"  Specificity:         {self.specificity(variant):.1%}")
            print(f"  F1:                  {self.f1(variant):.1%}")
            print(f"  Avg latency:         {self.avg_latency(variant):.2f}s")
            if errors:
                print(f"  Errors:              {errors}")

        # Per-category breakdown
        unique_variants = self._unique_variants()
        print(f"\n--- Per-category breakdown ({self.model_label}) ---")
        col_w = 14
        header = f"{'Category':<20}" + "".join(f" {v:>{col_w}}" for v in unique_variants)
        print(header)
        print("-" * len(header))

        for cat in TEST_PROMPTS:
            row = f"{cat:<20}"
            for variant in unique_variants:
                expected = EXPECTED_SKILLS.get(cat, set())
                if expected:
                    hits = sum(
                        1
                        for r in self.results
                        if r.variant == variant
                        and r.category == cat
                        and r.activated_skills & expected
                        and not r.error
                    )
                else:
                    hits = sum(
                        1
                        for r in self.results
                        if r.variant == variant
                        and r.category == cat
                        and not r.activated_skills
                        and not r.error
                    )
                total = sum(
                    1
                    for r in self.results
                    if r.variant == variant and r.category == cat and not r.error
                )
                val = f"{hits}/{total}" if total else "N/A"
                row += f" {val:>{col_w}}"
            print(row)

        # Per-skill accuracy
        print(f"\n--- Per-skill YES/NO accuracy ({self.model_label}) ---")
        skill_header = f"{'Skill':<25} {'Variant':<16} {'TP':>4} {'FP':>4} {'TN':>4} {'FN':>4} {'Acc':>7}"
        print(skill_header)
        print("-" * len(skill_header))
        for variant in unique_variants:
            stats = self.per_skill_accuracy(variant)
            for skill, s in sorted(stats.items()):
                total = s["tp"] + s["fp"] + s["tn"] + s["fn"]
                acc = (s["tp"] + s["tn"]) / total if total else 0.0
                print(
                    f"{skill:<25} {variant:<16} {s['tp']:>4} {s['fp']:>4} "
                    f"{s['tn']:>4} {s['fn']:>4} {acc:>6.1%}"
                )

        print("=" * 80)


def print_cross_model_report(summaries: dict[str, BenchmarkSummary]) -> None:
    """Print cross-model comparison table."""
    # Collect all variants across summaries
    all_variants: list[str] = []
    seen: set[str] = set()
    for summary in summaries.values():
        for v in summary._unique_variants():
            if v not in seen:
                seen.add(v)
                all_variants.append(v)

    print("\n" + "=" * 100)
    print("CROSS-MODEL COMPARISON")
    print("=" * 100)

    # Print per-variant block for each pair relative to A_passive baseline
    if "A_passive" in all_variants:
        metric_variants = [v for v in all_variants if v != "A_passive"]
        header = (
            f"{'Model':<18} {'A_act':>7}"
            + "".join(f" {v[:6]+'_act':>10}" for v in metric_variants)
        )
        print(header)
        print("-" * len(header))

        for label, summary in summaries.items():
            a_act = summary.activation_rate("A_passive")
            row = f"{label:<18} {a_act:>6.1%}"
            for v in metric_variants:
                v_act = summary.activation_rate(v)
                delta = v_act - a_act
                row += f" {v_act:>5.1%}({delta:>+5.1%})"
            print(row)

        print()

    # F1 comparison table
    header2 = f"{'Model':<18}" + "".join(f" {v[:14]:>14}" for v in all_variants)
    print(f"F1 scores:")
    print(header2)
    print("-" * len(header2))
    for label, summary in summaries.items():
        row = f"{label:<18}"
        for v in all_variants:
            row += f" {summary.f1(v):>13.1%}"
        print(row)

    # Wilcoxon signed-rank test if scipy available and multiple models
    if wilcoxon and len(summaries) >= 5 and "A_passive" in all_variants and "B_forced_eval" in all_variants:
        a_rates = [s.activation_rate("A_passive") for s in summaries.values()]
        b_rates = [s.activation_rate("B_forced_eval") for s in summaries.values()]
        try:
            stat_result = wilcoxon(a_rates, b_rates)
            print(f"\nWilcoxon signed-rank test (A_passive vs B_forced_eval): stat={stat_result.statistic:.4f}, p={stat_result.pvalue:.4f}")
        except Exception:
            pass

    print("=" * 100)


# =============================================================================
# Skill Prompt Rendering (adapted from benchmark_core.py)
# =============================================================================


async def _render_skill_prompt(
    base_prompt: str,
    skill_registry: dict[str, str],
) -> str:
    """Apply SkillLoadHarness to a base system prompt."""
    harness = SkillLoadHarness(
        skill_registry=skill_registry,
    )

    class _MockRequest:
        def __init__(self, content: str):
            self.system_message = SystemMessage(content=content)
            self.system_prompt = None

        def override(self, **kwargs):
            new = _MockRequest(base_prompt)
            for key, value in kwargs.items():
                setattr(new, key, value)
            return new

    captured = base_prompt

    async def _handler(req):
        nonlocal captured
        captured = str(req.system_message.content)
        return None

    await harness.abefore_agent(state=None, runtime=None)
    await harness.awrap_model_call(_MockRequest(base_prompt), _handler)
    return captured


async def _render_passive_prompt(base_prompt: str) -> str:
    """Apply SkillsMiddleware (passive) to a base system prompt."""
    mw = SkillsMiddleware(
        skills_dir=_PROJECT_ROOT / "skills",
        allowed_skill_names=tuple(SKILL_REGISTRY.keys()),
    )
    await mw.abefore_agent(state=None, runtime=None)

    class _MockRequest:
        def __init__(self, content: str):
            self.system_message = SystemMessage(content=content)
            self.system_prompt = None

        def override(self, **kwargs):
            new = _MockRequest(base_prompt)
            for key, value in kwargs.items():
                setattr(new, key, value)
            return new

    captured = base_prompt

    async def _handler(req):
        nonlocal captured
        captured = str(req.system_message.content)
        return None

    await mw.awrap_model_call(_MockRequest(base_prompt), _handler)
    return captured


# =============================================================================
# Skill Activation Detection (from tool_history, not regex)
# =============================================================================


def _extract_skills_from_tool_history(tool_history: list[dict[str, Any]]) -> set[str]:
    """Extract activated skill names from actual tool call history."""
    skills: set[str] = set()
    for entry in tool_history:
        if entry.get("name") != read_skill_file.name:
            continue
        args = entry.get("args", {})
        skill_path = args.get("skill_path", "")
        path = Path(skill_path)
        parts = path.parts
        for i, part in enumerate(parts):
            if part == "skills" and i + 1 < len(parts):
                candidate = parts[i + 1]
                if candidate in SKILL_REGISTRY:
                    skills.add(candidate)
                break
    return skills


def _coerce_text(content: Any) -> str:
    """Coerce AIMessage content to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return str(content)


# =============================================================================
# Tool-Calling Loop (adapted from benchmark_core.py:555-621)
# =============================================================================


async def _run_tool_loop(
    llm: Any,
    *,
    system_prompt: str,
    user_prompt: str,
    max_round_trips: int = 4,
) -> dict[str, Any]:
    """Run a minimal tool-calling loop with read_skill_file bound."""
    llm_with_tools = llm.bind_tools([read_skill_file])
    messages: list[Any] = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]
    tool_history: list[dict[str, Any]] = []
    final_message: AIMessage | None = None

    for _ in range(max_round_trips):
        response = await llm_with_tools.ainvoke(messages)
        if not isinstance(response, AIMessage):
            response = AIMessage(content=_coerce_text(getattr(response, "content", response)))
        final_message = response
        messages.append(response)

        if not response.tool_calls:
            break

        for tool_call in response.tool_calls:
            tool_call_id = tool_call.get("id") or f"tool-call-{len(tool_history)}"
            tool_name = tool_call.get("name")
            tool_args = tool_call.get("args", {})

            if tool_name != read_skill_file.name:
                error_text = f"Unsupported tool: {tool_name}"
                tool_history.append(
                    {"name": tool_name, "args": tool_args, "content_preview": error_text}
                )
                messages.append(ToolMessage(content=error_text, tool_call_id=tool_call_id))
                continue

            if not isinstance(tool_args, dict):
                try:
                    tool_args = json.loads(tool_args)
                except Exception:
                    tool_args = {"skill_path": str(tool_args)}

            result = await asyncio.to_thread(read_skill_file.invoke, tool_args)
            tool_history.append(
                {
                    "name": tool_name,
                    "args": tool_args,
                    "content_preview": str(result)[:240],
                }
            )
            messages.append(ToolMessage(content=str(result), tool_call_id=tool_call_id))

    if final_message is None:
        raise RuntimeError("Model produced no response")

    return {
        "final_text": _coerce_text(final_message.content),
        "tool_history": tool_history,
    }


# =============================================================================
# Trial Runner
# =============================================================================


async def _run_single_trial(
    llm: Any,
    prompt: str,
    category: str,
    variant: str,
    model_label: str,
) -> TrialResult:
    """Run a single benchmark trial with real tool binding."""
    result = TrialResult(model=model_label, category=category, prompt=prompt, variant=variant)
    start = time.monotonic()

    try:
        if variant == "A_passive":
            system_prompt = await _render_passive_prompt(BENCHMARK_SYSTEM_PROMPT)
        elif variant == "B_forced_eval":
            system_prompt = await _render_skill_prompt(
                BENCHMARK_SYSTEM_PROMPT, SKILL_REGISTRY
            )
        elif variant == "B1_stage_gated":
            filtered = _filter_registry_by_keywords(prompt)
            if filtered:
                system_prompt = await _render_skill_prompt(
                    BENCHMARK_SYSTEM_PROMPT, filtered
                )
            else:
                system_prompt = BENCHMARK_SYSTEM_PROMPT  # No skills presented
        elif variant == "B2_no_bias":
            system_prompt = await _render_b2_prompt(BENCHMARK_SYSTEM_PROMPT)
        elif variant == "B3_two_phase":
            system_prompt = await _render_b3_prompt(BENCHMARK_SYSTEM_PROMPT)
        elif variant == "B4_minimal_desc":
            system_prompt = await _render_b4_prompt(BENCHMARK_SYSTEM_PROMPT)
        else:
            raise ValueError(f"Unknown variant: {variant}")

        loop_result = await _run_tool_loop(
            llm, system_prompt=system_prompt, user_prompt=prompt
        )

        result.tool_history = loop_result["tool_history"]
        result.activated_skills = _extract_skills_from_tool_history(result.tool_history)

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
    variants: list[str],
) -> BenchmarkSummary:
    """Run benchmark for a single model."""
    summary = BenchmarkSummary(model_label=model_label)
    total = sum(len(ps) for ps in TEST_PROMPTS.values()) * len(variants) * repeats
    done = 0

    for rep in range(repeats):
        for category, prompts in TEST_PROMPTS.items():
            for prompt in prompts:
                for variant in variants:
                    result = await _run_single_trial(
                        llm, prompt, category, variant, model_label
                    )
                    summary.results.append(result)
                    done += 1
                    status = "OK" if not result.error else f"ERR: {result.error[:40]}"
                    tool_count = len(result.tool_history)
                    print(
                        f"  [{done}/{total}] rep={rep+1} {variant} | {category} | "
                        f"skills={result.activated_skills or '{}'} | "
                        f"tools={tool_count} | {status}"
                    )

    return summary


async def run_benchmark() -> dict[str, BenchmarkSummary]:
    """Run the full multi-model A/B benchmark."""
    repeats = int(os.getenv("BENCHMARK_REPEATS", "1"))
    model_filter_raw = os.getenv("BENCHMARK_MODELS", "")
    model_filter = (
        [m.strip() for m in model_filter_raw.split(",") if m.strip()]
        if model_filter_raw
        else None
    )
    variant_filter_raw = os.getenv("BENCHMARK_VARIANTS", "")
    variants = (
        [v.strip() for v in variant_filter_raw.split(",") if v.strip()]
        if variant_filter_raw
        else VARIANTS
    )

    results_by_model: dict[str, BenchmarkSummary] = {}

    for config in MODEL_CONFIGS:
        if model_filter and config["label"] not in model_filter:
            continue

        print(f"\n{'#' * 72}")
        print(f"# Starting benchmark: {config['label']} (repeats={repeats})")
        print(f"# Variants: {variants}")
        print(f"{'#' * 72}\n")

        llm = create_llm(provider=config["provider"], **config["model_kwargs"])
        summary = await _run_model_benchmark(llm, config["label"], repeats, variants)
        results_by_model[config["label"]] = summary

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
                "tool_history": r.tool_history,
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
        model_data: dict[str, Any] = {"total_trials": len(summary.results), "errors": 0}
        for variant in summary._unique_variants():
            safe_v = variant.replace("-", "_")
            model_data[f"activation_rate_{safe_v}"] = round(summary.activation_rate(variant), 4)
            model_data[f"false_positive_rate_{safe_v}"] = round(summary.false_positive_rate(variant), 4)
            model_data[f"precision_{safe_v}"] = round(summary.precision(variant), 4)
            model_data[f"recall_{safe_v}"] = round(summary.recall(variant), 4)
            model_data[f"specificity_{safe_v}"] = round(summary.specificity(variant), 4)
            model_data[f"f1_{safe_v}"] = round(summary.f1(variant), 4)
            model_data[f"avg_latency_{safe_v}"] = round(summary.avg_latency(variant), 2)
            model_data["errors"] += summary.error_count(variant)
        data[label] = model_data
    output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"\nCross-model summary saved to: {output_path}")


def main() -> None:
    """Entry point."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    repeats = os.getenv("BENCHMARK_REPEATS", "1")
    models_env = os.getenv("BENCHMARK_MODELS", "(all)")
    variants_env = os.getenv("BENCHMARK_VARIANTS", "(all)")
    print("Starting Skill Activation Benchmark v2 (6 variants)...")
    print(f"Models: {models_env}")
    print(f"Repeats: {repeats}")
    print(f"Variants: {variants_env}")
    print(f"Skills: {list(SKILL_REGISTRY.keys())}")
    print(f"Categories: {list(TEST_PROMPTS.keys())}")

    summaries = asyncio.run(run_benchmark())

    for summary in summaries.values():
        summary.print_report()

    if len(summaries) > 1:
        print_cross_model_report(summaries)

    _save_summary(summaries)


if __name__ == "__main__":
    main()
