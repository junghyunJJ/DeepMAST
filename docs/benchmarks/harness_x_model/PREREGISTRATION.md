# Pre-Registration — `biomedical-literature-search` Skill × Model-Strength Ablation (Post-Update Replication)

**Study registration status**: DRAFT — to be submitted to OSF before P2 re-pilot execution.
**Project**: DeepMAST `harness_x_model` benchmark, re-pilot on post-ce4f79b production.
**Benchmark plan reference**: `/Users/jungj2/.claude/plans/misty-weaving-starlight.md` (Rev 4).
**Committed code reference**: `docs/benchmarks/harness_x_model/` — pilots B / B' / C to be fired in modes `--mode B`, `--mode B_prime`, `--mode C` respectively.
**OSF Project ID**: `<TO BE FILLED AFTER SUBMISSION>` (recorded in this file's footer after OSF upload).

---

## 1. Background and Motivation

### 1.1 Prior result (pre-update)

The 2026-04-16 pilot produced the following 3-way isolation evidence (`FINDINGS_SKILL_MECHANISM.md`):

| Experiment | Isolation | Celltype Δ strong | Celltype Δ weak | p (GLMM, skill_on) |
|---|:-:|---:|---:|---:|
| B (null control, kwargs pinned both arms) | kwargs pinned | +0.00 | +0.00 | 1.0000 |
| B' (prompt-level strip of kwarg hints) | prompt strip | +25.93 | +16.96 | **0.0002** |
| C (prompt strip + tool-schema isolation) | schema isolation | +25.90 | +14.58 | **0.015** |

Pooled GLMM across B + B' + C (n=142, dataset FE): β = +10.30 pp, p = 0.001 on celltype coverage. Because B' ≈ C despite C enforcing stronger isolation, the pre-update interpretation was: **skill's load-bearing contribution is workflow guidance, not API affordance (kwarg activation)**.

### 1.2 Why re-register

Between that pilot and today, production was modified by 4 commits:

- `c1c2580` — rename `skill-load-harness` → `skill-activator` (naming refactor).
- `ce4f79b` — remove `think_tool` reflection from SEARCHER subagent. Reflection is now **tool-internal** (coverage-score loop inside `search_literature_dynamic`), not LLM-driven.
- `2db754d` — `think_tool` becomes active reflection in INTERPRETER (orthogonal subagent).
- `93fbc18` — BioMCP payload sanitization + gene-alias 5-min TTL (orthogonal hardening).

**The ce4f79b commit changes the causal mechanism through which the skill exerts its effect on SEARCHER.** Pre-update, the skill's Phase 3 mandated `think_tool` calls for LLM-driven reflection. Post-update, reflection is driven by the tool itself based on coverage scores — the skill's Phase 3 is now prose-level guidance only.

This pre-registration asks whether the effect replicates across this architecture change.

---

## 2. Research Question (3-dimensional)

> Does the `biomedical-literature-search` skill — when toggled ON vs OFF — measurably improve literature-retrieval coverage across the three orthogonal biological dimensions the SEARCHER targets: **genes**, **pathways**, and **celltypes**? Is the effect moderated by model strength (qwen3.5:122b vs 35b)?

The pilot's target is **3-dimensional coverage**. This pre-registration explicitly centers gene / pathway / celltype together; the statistical hypothesis test anchor is celltype only because it is the single dimension adequately powered at pilot n=48 in pre-update data.

---

## 3. Hypothesis

**H1 (primary, post-update)**: On post-ce4f79b production, the skill retains its load-bearing contribution to 3-dimensional literature-retrieval coverage, evidenced by:
1. Mode B shows no between-arm celltype Δ (null control integrity).
2. Mode B' and mode C both show celltype Δ ≥ +12 pp in the strong-model arm (strengthened-claim window).
3. Mode C's celltype Δ is within ±5 pp of mode B' (TOST equivalence on `C − B'` contrast — confirms that adding tool-schema isolation does not shift the observed effect).

**H0 (null)**: The skill's effect was mediated by pre-update LLM-driven `think_tool` reflection (now removed), and the residual prose-level Phase 3 guidance is insufficient to drive cell-type-level retrieval discrimination.

---

## 4. Exploratory Anchors — NOT Confirmatory Bounds

**Critical framing**: The replication thresholds in §6 are anchored to pre-update effect sizes (B' strong Δ ≈ +26 pp; pooled β ≈ +10 pp marginal effect). The causal mechanism has changed between pre- and post-update. Thresholds are therefore **exploratory anchors**, not confirmatory bounds.

Confirmation of H1 requires:
- **(a) B null-control passes Gate Null** (per-arm celltype Δ < 3 pp in both model strengths), AND
- **(b) B' and C celltype Δ land in the strengthened-claim window** ([+12, +22] pp, strong model), AND
- **(c) TOST on `C − B'` equivalence test rejects at α = 0.05** with ±5 pp margin.

Failure at any of (a)(b)(c) triggers the non-replication / nuanced-claim paths in §6.

---

## 5. Primary Analysis (3-dimensional composite)

| Dimension | Role | Statistical test | Rationale |
|---|---|---|---|
| `genes_coverage_pct` | **Descriptive** | None | Saturated at 100% in all arms in pre-update data (2-gene cases + deterministic fan-out = trivial 2/2). Report per-arm mean / SE / range for completeness; no significance test. Not in multiple-comparison family. |
| `pathways_coverage_pct` | **Secondary test** | OLS `pathways_coverage_pct ~ skill_on * model_strength + dataset` on subset with pathways | Underpowered (4–8/12 cases have pathway metadata → n=15-23 post-exclusion). Report Δ and 95% CI regardless of p-value; explicit power caveat if p > 0.05. In Holm-Bonferroni family. |
| `celltypes_coverage_pct` | **Primary test** | GLMM `coverage_pass ~ skill_on * model_strength + (1 \| case_id)` per experiment + pooled `... + dataset` with dataset FE | Only dimension both measurable (no saturation) and adequately powered (p=0.0002 in pre-update B'). Primary hypothesis test. In Holm-Bonferroni family. |

**Pooled model** (all 3 experiments combined):
```
celltypes_coverage_pct ~ skill_on * model_strength + dataset + (1 | case_id)
```
Estimated via `lme4::lmer` on continuous celltype percent. The binary `coverage_pass` GLMM is retained as a robustness check.

**Statistical software**: R (`lme4`, `emmeans`, `dplyr`). Bootstrap CI: case-level percentile, 10000 iterations.

**Research claim to report regardless of outcome**: gene / pathway / celltype Δ side-by-side per experiment, per model strength, with per-dimension caveats in the Methods section.

---

## 6. Replication Thresholds (on celltype primary, strong-model Δ)

| Δ window | Verdict | Narrative |
|---|---|---|
| ∈ [+12, +22] pp | **Strengthened claim confirmed** | Architecture-independent workflow guidance. Skill's contribution replicates across LLM-driven and tool-internal reflection architectures. |
| ∈ [+5, +12] or [+22, +30] pp | Nuanced claim | Effect is modulated by reflection architecture but still load-bearing. Discuss mechanism shift. |
| < +5 pp | Non-replication | Pre-update effect may have been mediated by `think_tool`; skill's residual prose-level Phase 3 guidance is insufficient. Pivot to mechanism investigation before manuscript submission. |

**Supplemental direction check**:
- If gene / pathway Δ tracks the same direction as celltype at smaller magnitude → strengthens the 3-dimensional claim.
- If gene / pathway Δ diverges (e.g., pathway Δ < 0 while celltype Δ > 0) → flag as mechanism nuance requiring explicit Discussion.

---

## 7. Equivalence Test (TOST on C − B' celltype contrast)

**Purpose**: confirm that adding tool-schema isolation (C) does not shift the celltype effect relative to prompt-strip alone (B'). If `|C − B'| < 5 pp` at α = 0.05 via two one-sided tests, we claim: **tool-kwarg activation contributes no additional detectable benefit beyond workflow guidance**.

**Margin**: ±5 pp.
**Test**: `emmeans::emmeans` on fitted pooled model `celltypes_coverage_pct ~ dataset + model_strength + (1 | case_id)` restricted to `dataset ∈ {B', C}` and `skill_on == TRUE`. Two one-sided t-tests on the `C − B'` contrast. Both must reject for equivalence.
**Implementation**: `fit_tost_equivalence` in `harness_x_model_glmm.R`.

---

## 8. Multiple-Comparison Correction

**Family (Holm-Bonferroni)**:
1. B celltype (Gate Null check, one-sided Δ != 0)
2. B' celltype (strong-model Δ, two-sided)
3. C celltype (strong-model Δ, two-sided)
4. Pooled celltype main effect (skill_on, two-sided)
5. Pooled celltype interaction (skill_on × model_strength, two-sided)
6. B' pathway (strong-model Δ, two-sided) — underpowered but still in family
7. C pathway (strong-model Δ, two-sided) — underpowered

**Not in family**: gene-coverage tests (descriptive-only, no significance test performed), TOST equivalence (separate inferential question).

**Threshold**: α = 0.05, Holm-corrected across the 7-test family.

---

## 9. Sensitivity Endpoints

Reported alongside the primary for robustness:

- `coverage_pass_tagoff` — tag-off recomputation of the same papers, addresses REV5 §1 critique of retrieval-tag provenance gating.
- `lr_cooccurrence_count` — non-saturating paper-quality endpoint (papers mentioning BOTH ligand AND receptor in title+abstract). Descriptive.
- `used_lr_pair_queries` — audit of whether the LLM activated the advanced kwargs in mode B' (proxy for tool-affordance adoption).

---

## 10. Exclusion Rules

A trial is excluded from the statistical analysis if ANY of the following holds on its latest retry:
1. `biomcp_error` is non-null.
2. `biomcp_paper_count_raw == 0 AND biomcp_latency_ms > 30000` (BioMCP outage detected per REV5 §6).
3. `error` field on the latest JSONL row is non-null (trial never wrote `papers.json`).

If > 20% of trials in any condition are excluded → the whole mode is re-run after 24h before analysis proceeds. If pooled n < 120 after all re-runs → the pilot is reported as "underpowered, re-running" and the manuscript is held pending a larger sample.

---

## 11. Stopping Rules

**Fixed sample**: 48 trials per experiment (12 cases × 4 conditions × 1 repeat), seed=42 deterministic schedule via `build_trial_schedule`. **No adaptive stopping** — the sample size is pre-committed.

---

## 12. Gate Failure Plans (measurement integrity)

Evaluated after each pilot via `check_pilot_gates` in `common.py`:

| Gate | Fail condition | Remediation |
|---|---|---|
| Gate A (saturation) | celltype median ≥ 90% in BOTH strong arms | Switch primary to `unique_PMIDs` per REV5 §8.1; pre-registered as fallback endpoint. |
| Gate B (BioMCP health) | error rate ≥ 5% OR median latency ≥ 10 min | Retry mode after 24h; apply §6 outage exclusion. |
| Gate C (distributional) | any condition has ≤ 3 unique rounded celltype values | Drop LMM secondary; report GLMM-only. |
| Variance (LLM noise) | mean per-case between-condition std-dev < 2 pp | Raise temperature to 0.5 and re-pilot that mode. |
| **Gate Null** (mode B only) | per-arm celltype Δ ≥ 3 pp in either strength | **STOP** — measurement scaffolding contaminated; investigate before firing B' / C. |

---

## 13. Diagnostic Probe (cheap pre-execution check)

**Before the 12h B+B'+C pilot fires**, a 30-min diagnostic probe is run (see plan Rev 4 §P2.0):

```bash
python docs/benchmarks/harness_x_model/run_pilot.py \
  --mode B_prime \
  --results-dir .../results/diagnostic_probe \
  --workspace-root .../workspaces/diagnostic_probe \
  --per-category 0 --cases cci_full_01_EGF_RACK1 --repeats 1
```

**Decision rule**:
- Strong-model Δ ≥ +5 pp on the single case → proceed to P2.2.
- Strong-model Δ < +5 pp OR effect flips direction → **STOP**; pivot to mechanism investigation.

**Detection limit**: the probe catches catastrophic collapse (>70% effect loss vs pre-update +16 pp baseline), not marginal attenuation. A pilot landing in the "nuanced" window (+5 to +12 pp) is NOT flagged by the probe; the full re-pilot will still be required.

---

## 14. Data Integrity Guards

Two resume-time safety checks prevent silent data contamination during the unattended 12h run:

- **`check_mode_coherence`**: aborts with `SystemExit` if `--mode` differs from the `benchmark_mode` field of already-completed trials in the results directory.
- **`check_cases_coherence`**: aborts if the cases file SHA-256 has changed since the pilot started (deterministic schedule would drift).

Both guards emit structured error messages with recovery hints. See `docs/benchmarks/harness_x_model/RUNBOOK.md` for operator documentation.

---

## 15. Deviations From Pre-Update Study

Any deviation from the pre-update protocol is listed here:

1. **Primary endpoint refinement**: pre-update pilot's FINDINGS selected celltype post-hoc (after gene saturated); Rev 4 pre-registers celltype **in advance** with gene/pathway as descriptive/secondary. Research question framing is 3-dimensional.
2. **Gate A threshold**: switched from `genes_coverage_pct ≥ 95%` (mechanically unreachable — gene saturates at 100% everywhere) to `celltypes_coverage_pct ≥ 90%`.
3. **Gate Null** (mode B only): new gate, pre-registers a 3 pp per-arm threshold for null-control integrity.
4. **Equivalence test**: pre-update had no formal TOST; Rev 4 adds ±5 pp TOST on `C − B'`.
5. **Multi-dataset GLMM**: pooled-analysis R script extension; pre-update pooled β was computed ad-hoc.

---

## 16. Data Availability & Reproducibility

- **Raw per-trial JSONL** (one file per `trial_index`) published under `docs/benchmarks/harness_x_model/results/pilot_post_update_{b,b_prime,c}/` after the pilot completes.
- **Analysis script**: `docs/benchmarks/harness_x_model/harness_x_model_glmm.R` — accepts `--results-dir X --dataset-label Y` (repeated), fits pooled GLMM + TOST, bootstraps case-level CI.
- **Audit fields**: every JSONL row carries `benchmark_mode` and `cases_sha256` enabling post-hoc verification that modes were not mixed and the cases file was stable throughout the run.
- **Regression test suite**: `tests/benchmarks/test_harness_x_model.py` (≥ 40 tests, full coverage of mode-parameterization + resume guards + gate thresholds).

---

## 17. Conflict of Interest

None declared.

---

## Footer — OSF Registration Metadata

- **OSF Project URL**: `<TO BE FILLED AFTER SUBMISSION>`
- **OSF Registration DOI**: `<TO BE FILLED AFTER SUBMISSION>`
- **Registration timestamp (UTC)**: `<TO BE FILLED AFTER SUBMISSION>`
- **Git commit of this file at registration time**: `<TO BE FILLED AFTER SUBMISSION>` (recorded via `git rev-parse HEAD`)
- **Git commit of benchmark code at registration time**: `<TO BE FILLED AFTER SUBMISSION>`

Registration workflow: (1) `git rev-parse HEAD` → record hash here → commit → (2) upload this file to OSF with the hash embedded → (3) update footer with OSF ID/DOI → commit. The fully-populated footer provides a verifiable chain linking the pre-registered design to the code version that produced the data.
