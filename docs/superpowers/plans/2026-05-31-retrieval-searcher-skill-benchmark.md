# Retrieval Skill-Only Coverage Benchmark Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` for execution or `superpowers:executing-plans` for a single-agent run. This file is the active PR plan. The old gpt-5.4 content-utility / `fig2.svg` track is archived separately.

**Status:** current PR closes on retrieval coverage, not on gpt-5.4 content-utility.

**Archive:** the previous content-utility / `fig2.svg` / `figs2.svg` plan is preserved at `docs/superpowers/plans/old/2026-05-31-retrieval-searcher-skill-benchmark.old-content-utility-fig2.md`.

**Goal:** measure the retrieval-only effect of `biomedical-literature-search` as breadth/coverage: whether skill ON retrieves papers covering more case biology entities than skill OFF under the same benchmark cases and same posthoc direct/context filter.

**Final PR artifact:** `docs/benchmarks/lr_retrieval_relevance/results/cci_retrieval_skill_only_content_utility_gpt54_live_thinkfalse/COVERAGE_SUMMARY_KO.md`

**Primary figure:** `docs/benchmarks/lr_retrieval_relevance/results/cci_retrieval_skill_only_content_utility_gpt54_live_thinkfalse/manuscript/figures/fig_retrieval_coverage.svg`

---

## Current PR Scope

In scope:

- Keep the updated `biomedical-literature-search` skill role modes:
  - `PLANNER mode`: light context search, no canonical citation authority.
  - `SEARCHER production mode`: canonical `papers_raw.json -> citation_candidates.json -> papers.json` handoff.
  - `SEARCHER retrieval-only benchmark mode`: raw retrieval only; no agent-side handoff.
  - `REPORTER mode`: synthesis-only literature artifacts under `synthesis_*`, never overwrite `papers.json`.
- Keep base SEARCHER prompt policy-light:
  - Load the applicable literature skill.
  - Preserve the invariant that production INTERPRETER reads filtered `papers.json`.
  - Keep detailed handoff workflow in the skill/tool layer, not in the base prompt.
- Run Benchmark A as retrieval-only:
  - skill ON: updated skill retrieval strategy.
  - skill OFF: same wrapper/case contract, no skill search strategy.
  - both arms: common posthoc `create_literature_handoff` only for evaluation.
  - filtered set: `direct_lr_evidence` + `receptor_pathway_context_evidence`, cap 40.
- Score coverage with qwen3.5:122b labels:
  - gene coverage.
  - pathway coverage.
  - celltype coverage.
  - raw retrieved set and filtered direct/context set.
- Close the PR using `COVERAGE_SUMMARY_KO.md` and `fig_retrieval_coverage.*`.

Out of scope for this PR:

- Claiming gpt-5.4 content-utility improvement.
- Regenerating manuscript `fig2.svg` / `figs2.svg` as the final PR deliverable.
- Handoff ranking policy benchmark.
- Changing `coverage_weighted_sort` internals or `alpha=0.4`.
- End-to-end production handoff effect benchmark.

---

## Active Artifacts

Retrieval root:

```text
docs/benchmarks/lr_retrieval_relevance/results/cci_retrieval_skill_only_qwen_full_thinkfalse
```

Coverage/content root:

```text
docs/benchmarks/lr_retrieval_relevance/results/cci_retrieval_skill_only_content_utility_gpt54_live_thinkfalse
```

Note: the coverage/content root name contains `content_utility_gpt54_live` for continuity with the earlier benchmark pipeline, but the current PR conclusion uses coverage artifacts, not a renewed gpt-5.4 content-utility claim.

Key files:

```text
COVERAGE_SUMMARY_KO.md
converted_runner_rows.jsonl
gene_coverage_labels_122b.jsonl
entity_coverage_labels_122b.jsonl
manuscript/tables/coverage_percase.csv
manuscript/tables/coverage_group_summary.csv
manuscript/tables/coverage_sig.csv
manuscript/figures/fig_retrieval_coverage.svg
manuscript/figures/fig_retrieval_coverage.png
```

Coverage exporter:

```text
scripts/benchmarks/export_coverage_figure_data.py
docs/benchmarks/lr_retrieval_relevance/coverage_figure.R
```

---

## Completed Work Checklist

- [x] Added/kept retrieval-only Benchmark A mode.
- [x] Kept common posthoc direct/context filtering for both skill ON and skill OFF.
- [x] Ran qwen35b/qwen122b retrieval benchmark with `reasoning=False`.
- [x] Preserved already completed benchmark rows during recovery.
- [x] Repaired the malformed `row_0011_weak_on` raw retrieval artifact without restarting the full benchmark.
- [x] Refreshed retrieval summary artifacts.
- [x] Refreshed `converted_runner_rows.jsonl`.
- [x] Scored missing coverage labels with qwen3.5:122b.
- [x] Regenerated coverage tables.
- [x] Regenerated `fig_retrieval_coverage.svg` and `.png`.
- [x] Updated `COVERAGE_SUMMARY_KO.md`.
- [x] Updated `INTERPRETATION_KO.md` numeric retrieval/handoff counts affected by the repaired row.

---

## Final Coverage Results

Primary result: skill ON improves entity breadth, especially celltype coverage.

Raw retrieved set:

| Metric | Pooled Delta | Interpretation |
|---|---:|---|
| genes | +0.0pp | saturated, no effect |
| pathways | +22.7pp | positive, pooled significant but pathway n is small |
| celltypes | +22.7pp | robust, highly significant |

Filtered direct/context set:

| Metric | Pooled Delta | Interpretation |
|---|---:|---|
| genes | +0.0pp | saturated, no effect |
| pathways | +15.9pp | positive, borderline/underpowered |
| celltypes | +15.3pp | robust, highly significant |

Recommended PR claim:

> The updated biomedical-literature-search skill significantly increases cell-type coverage of retrieved literature. Pathway coverage shows a consistent positive effect but is underpowered after filtering; gene coverage is saturated in both arms.

Do not claim from this PR:

- The skill improves final biological interpretation utility.
- The skill retrieves more direct LR evidence.
- The skill improves paper-level precision/depth.

---

## Reproduction Commands

Regenerate coverage tables and figure from the current result root:

```bash
ROOT=docs/benchmarks/lr_retrieval_relevance/results/cci_retrieval_skill_only_content_utility_gpt54_live_thinkfalse
python scripts/benchmarks/export_coverage_figure_data.py --results-dir "$ROOT"
Rscript docs/benchmarks/lr_retrieval_relevance/coverage_figure.R "$ROOT"
```

Verify coverage stats:

```bash
ROOT=docs/benchmarks/lr_retrieval_relevance/results/cci_retrieval_skill_only_content_utility_gpt54_live_thinkfalse
python scripts/benchmarks/analyze_coverage_stats.py \
  --runner-rows "$ROOT/converted_runner_rows.jsonl" \
  --gene-labels "$ROOT/gene_coverage_labels_122b.jsonl" \
  --entity-labels "$ROOT/entity_coverage_labels_122b.jsonl"
```

Expected key evidence:

```text
entity_coverage_labels_122b.jsonl: 1423/1423 ok
gene_coverage_labels_122b.jsonl: 1423/1423 ok
raw pooled celltypes delta: +22.7pp, p<0.001
filtered pooled celltypes delta: +15.3pp, p<0.001
```

---

## Archived Old Track

The earlier plan route tried to close this PR on:

- live gpt-5.4 content-utility judging.
- `fig2.svg` / `figs2.svg` regeneration.
- old-style manuscript panels from content-utility effect estimates.

That track is no longer the active close criterion for this PR.

Reason:

- The clean Benchmark A gpt-5.4 content-utility signal was neutral/mixed.
- The useful and defensible signal is retrieval coverage breadth.
- `fig2.svg` / `figs2.svg` should not be treated as the active deliverable for this PR.

Keep the old plan for provenance only:

```text
docs/superpowers/plans/old/2026-05-31-retrieval-searcher-skill-benchmark.old-content-utility-fig2.md
```

Do not use that archived plan as active acceptance criteria unless a future PR explicitly reopens content-utility manuscript figure work.

---

## Next PR Handoff: Ranking Policy Benchmark

Purpose: compare which 40 papers should be handed to INTERPRETER once `citation_candidates.json` already exists.

This is a separate PR because it evaluates handoff selection, not raw retrieval.

### Input

Use existing or newly generated `citation_candidates.json` artifacts from retrieval-only/production runs.

Do not rerun raw literature search unless a candidate file is missing or malformed.

Candidate buckets:

```text
direct_lr_evidence
receptor_pathway_context_evidence
disease_only_background
rejected_weak_evidence
```

Eligible handoff papers:

```text
direct_lr_evidence
receptor_pathway_context_evidence
```

Excluded from INTERPRETER handoff:

```text
disease_only_background
rejected_weak_evidence
```

### Active Ranking Policies

Keep the first benchmark intentionally small. Run exactly these three policies first:

1. **`baseline_current`**
   - direct papers first.
   - context papers next.
   - preserve current order inside each bucket.
   - purpose: current production-equivalent baseline.

2. **`bucket_lr_coverage`**
   - include only direct/context candidates.
   - bucket priority remains direct > context.
   - within the same bucket, rank papers that support more LR pairs or case entities higher.
   - goal: avoid handing 40 papers dominated by one famous pathway/gene.

3. **`bucket_lr_coverage_journal_tiebreak`**
   - same as `bucket_lr_coverage`.
   - journal quality is a tie-breaker, not a primary score component.
   - goal: test whether journal quality improves selected-paper quality without sacrificing coverage.

Do not add more active policies in the first pass. The benchmark should answer whether
coverage-aware handoff improves the current baseline, and whether journal-quality tie-breaking
helps without muddying the interpretation.

### Optional Follow-Up Policy

Do not run this initially:

4. **`direct_quota_policy`**
   - direct evidence is reserved first.
   - remaining slots are filled by context evidence.
   - run only if the active benchmark shows direct evidence is available but under-selected.
   - quota value is not fixed in this PR; decide after inspecting `available_direct_count` and `selected_direct_count`.

Rationale: direct evidence was sparse in the previous benchmark, so a direct quota may collapse to
the current baseline or add little signal. Track direct availability first, then decide if this
policy deserves a separate run.

### Metrics

Report per policy:

- handoff count.
- direct/context composition.
- available direct count.
- selected direct count.
- disease-only/rejected leakage count; expected zero.
- LR pair coverage.
- gene/pathway/celltype coverage.
- unique PMID overlap across policies.
- journal quality summary.
- redundancy or concentration by receptor/pathway.
- optional downstream gpt-5.4 content-utility only after retrieval/handoff metrics are understood.

### Proposed Output Root

```text
docs/benchmarks/lr_retrieval_relevance/results/cci_handoff_ranking_policy_benchmark_YYYYMMDD
```

Required outputs:

```text
HANDOFF_RANKING_RESULTS_KO.md
ranking_policy_summary.csv
ranking_policy_percase.csv
ranking_policy_overlap.csv
```

### Stop Conditions

- Stop if any policy leaks `disease_only_background` or `rejected_weak_evidence` into INTERPRETER handoff.
- Stop if a candidate file schema mismatch prevents fair comparison.
- Do not judge with gpt-5.4 until the deterministic ranking metrics pass.

---

## Current PR Acceptance Criteria

- `COVERAGE_SUMMARY_KO.md` is the final Korean interpretation for this PR.
- `fig_retrieval_coverage.svg` and `.png` are regenerated from the clean `_thinkfalse` result root.
- Coverage tables under `manuscript/tables/coverage_*.csv` match the regenerated figure.
- qwen3.5:122b coverage labels are complete: 1423/1423 ok for gene and entity labels.
- The repaired malformed row has full raw/candidate/filtered artifacts:
  - raw papers: 30.
  - citation candidates: 30.
  - filtered handoff papers: 21.
- gpt-5.4 content-utility / `fig2.svg` / `figs2.svg` work is archived as old, not active.
- Next PR starts from the handoff ranking policy benchmark section above.
