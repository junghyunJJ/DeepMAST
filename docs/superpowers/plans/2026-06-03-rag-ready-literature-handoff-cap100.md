# RAG-Ready Literature Handoff Cap 100 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This is the next PR plan, not a reopening of the cap-40 ranking benchmark PR.

**Status:** planned next PR.

**Goal:** change the production SEARCHER -> INTERPRETER literature handoff from a compact cap-40 ranking artifact into a RAG-ready `papers.json` corpus that includes all eligible direct/context papers up to a maximum cap of 100.

**Architecture:** Keep the existing bucket grading path and replace only the final selection contract. `papers.json` is selected as `min(eligible_direct_context_count, 100)`: when eligible papers are fewer than 100, all eligible papers are passed through; when eligible papers exceed 100, direct evidence is preserved first and context evidence is selected by LR-pair round-robin. QC reporting validates eligibility, coverage, and concentration without treating below-100 eligible counts as a failure.

**Tech Stack:** Python, pytest, ruff, JSON/CSV/Markdown benchmark artifacts, `src.agents.deep_interpreter.tools.literature_handoff`, and the `skills/biomedical-literature-search` production workflow.

**Non-goal:** do not run a new active 3-way cap-100 policy benchmark. The cap-40 ranking benchmark remains a legacy diagnostic artifact for the prior handoff contract.

---

## Decision Summary

Use a single active production selection policy:

```text
direct_all_pair_round_robin_100
```

Treat cap 100 as an upper bound, not a target that must be filled:

```text
selected_count = min(eligible_direct_context_count, 100)
```

Policy rules:

1. Exclude `disease_only_background` and `rejected_weak_evidence` from `papers.json`.
2. If eligible direct/context papers are fewer than or equal to 100, select all eligible papers.
3. If eligible direct/context papers exceed 100, include all `direct_lr_evidence` papers when `available_direct_count <= 100`.
4. If direct papers alone exceed cap, select direct papers by LR-pair round-robin and report `direct_truncated_count`.
5. Fill remaining truncation slots with `receptor_pathway_context_evidence` by LR-pair round-robin.
6. Context papers without pair-scoped support go to a fallback queue in original candidate order.
7. Never pad with background or rejected papers just to reach 100; report unused capacity as normal when eligible papers are fewer than 100.

When eligible papers exceed 100, the selection order is:

1. **Direct preservation:** select every direct paper first if direct count is at or below 100.
2. **Direct overflow fallback:** if direct count alone exceeds 100, select direct papers by LR-pair round-robin and stop at 100.
3. **Context pair balancing:** if slots remain after direct papers, build per-LR-pair queues from context papers with `supported_lr_pairs` or `context_lr_pairs`.
4. **Round-robin pass:** iterate LR pairs in the original `inputs.lr_pairs` order and take at most one not-yet-selected context paper per pair per pass until the cap is reached.
5. **Deduplication:** if one paper supports multiple LR pairs, select it once and skip it in later queues.
6. **Fallback queue:** after pair-scoped context queues are exhausted, fill remaining slots from unpaired context papers in original candidate order.

Tie-breaks stay deterministic and simple: inside each bucket or LR-pair queue, preserve the original candidate order from `citation_candidates.json`. Do not use journal quality, LLM score, or a composite scoring formula as an active handoff tie-break in this PR.

Journal quality is already applied upstream during `search_literature_dynamic` when `sort_by_journal_quality=True`; with `coverage_weighted_sort=True`, final raw retrieval truncation uses a coverage/SJR blend. Therefore, handoff selection should not re-apply journal quality as a second-stage ranking signal. Keep journal quality in QC reporting only, to detect whether the selected handoff corpus has unexpectedly weak journal-quality distribution.

Rationale:

- The next biological interpretation sub-agent uses RAG, so 40 papers is too small for the intended downstream retrieval context.
- Around 300 raw or candidate papers is too large for the INTERPRETER-facing contract.
- If only 65 eligible direct/context papers exist, using those 65 is the expected behavior, not an underfilled failure.
- A policy competition at cap 100 would add complexity without answering the current product question. The current question is the RAG handoff contract, not which cap-40 ranking heuristic wins.

---

## Current Evidence

Relevant implementation anchors:

- `src/agents/deep_interpreter/tools/literature_handoff.py`
  - `DEFAULT_HANDOFF_CAP = 40` currently defines the production default.
  - `build_literature_handoff()` filters to direct/context eligible buckets and caps the result.
  - `grade_lr_literature_candidates()` writes `supported_lr_pairs`, `direct_lr_pairs`, and `context_lr_pairs`, which are enough to implement pair round-robin without another LLM call.
- `src/agents/deep_interpreter/tools/literature.py`
  - `search_literature_dynamic()` defaults `sort_by_journal_quality=True`.
  - When `coverage_weighted_sort=True`, final raw retrieval truncation uses a coverage/SJR blend.
  - This means journal quality is already an upstream retrieval prior, not a necessary handoff tie-break.
- `skills/biomedical-literature-search/SKILL.md`
  - SEARCHER Production Mode currently retrieves `max_results=100`.
  - It calls `create_literature_handoff(..., cap=40)`.
  - It describes `papers.json` as capped at 40.
- `src/agents/deep_interpreter/subagents/prompts.py`
  - The active SEARCHER prompt delegates detailed retrieval and handoff behavior to the loaded literature skill.
- `src/agents/deep_interpreter/subagents/configs.py`
  - The active SEARCHER tool list includes `create_literature_handoff`.

Prior cap-40 result:

- Output root: `docs/benchmarks/lr_retrieval_relevance/results/cci_handoff_ranking_policy_benchmark_20260603`
- Compared `baseline_current`, `bucket_lr_coverage`, and `bucket_lr_coverage_journal_tiebreak` at cap 40.
- All policies selected 2 direct + 38 context papers with leakage 0 on the production candidate artifact.
- The compared policies are diagnostic only for the old compact handoff contract.

Important constraint:

- The existing unified production candidate artifact had 100 unique raw candidates and 65 eligible direct/context papers.
- Under the revised contract, selecting those 65 eligible papers is a valid RAG handoff because cap 100 is a maximum, not a fill target.
- Do not enlarge raw retrieval solely to force `papers.json` to contain exactly 100 papers. Larger raw retrieval can be a separate follow-up only if downstream interpretation shows evidence starvation.

---

## Scope

In scope:

- Change production handoff default cap to 100.
- Add one deterministic selection policy: `direct_all_pair_round_robin_100`.
- Keep bucket eligibility strict: only direct/context enter `papers.json`.
- Update the biomedical literature skill production instructions to match the cap-100 RAG contract.
- Add or update deterministic QC output for the cap-100 handoff.
- Run deterministic QC from existing `citation_candidates.json` first.
- Run a production handoff smoke only if needed to prove the updated production contract and tests, not to force 100 selected papers.

Out of scope:

- Re-running the old cap-40 ranking benchmark as the primary result.
- Comparing `baseline_current_cap100` vs `coverage_aware_cap100` vs journal tie-break as active policies.
- Including disease-only or rejected papers in RAG context.
- Raising raw retrieval headroom just to fill all 100 slots.
- Reopening gpt-5.4 content-utility, `fig2.svg`, or `figs2.svg`.
- Claiming cross-disease generalization. That remains an optional follow-up dataset check.

---

## Required Outputs

Use a new result root, for example:

```text
docs/benchmarks/lr_retrieval_relevance/results/cci_rag_ready_handoff_cap100_202606XX
```

Required files:

```text
RAG_HANDOFF_QC_KO.md
rag_handoff_qc_summary.csv
rag_handoff_pair_coverage.csv
rag_handoff_selected_papers.csv
run_config.json
selected_papers/<candidate_id>/papers.json
```

If a production smoke run is executed, also keep:

```text
papers_raw.json
citation_candidates.json
papers.json
RESULTS_KO.md
summary.csv
summary.json
```

---

## Acceptance Criteria

- `papers.json` policy metadata names `direct_all_pair_round_robin_100`.
- `papers.json` policy cap is 100.
- No selected paper has `evidence_bucket` outside:

```text
direct_lr_evidence
receptor_pathway_context_evidence
```

- If `available_direct_count <= 100`, then `selected_direct_count == available_direct_count`.
- `selected_count == min(eligible_count, 100)`.
- If `eligible_count >= 100`, then `selected_count == 100`.
- If `eligible_count < 100`, then `selected_count == eligible_count`, `eligible_all_selected == true`, and `unused_capacity_count == 100 - eligible_count`.
- When eligible papers exceed 100, context selection is distributed by supported LR pair before using fallback unpaired context.
- QC reports:
  - selected count
  - available and selected direct/context counts
  - eligible count
  - eligible-all-selected flag
  - unused capacity count
  - leakage count
  - LR pair coverage
  - gene/pathway/celltype coverage
  - journal quality summary
  - per-pair selected counts
  - concentration/redundancy metrics such as top pair share and HHI
- Existing cap-40 ranking benchmark tests continue to pass as legacy benchmark tests unless explicitly renamed or archived.

---

## Implementation Steps

- [ ] **Task 1: Add pure cap-100 upper-bound selection logic to `src/agents/deep_interpreter/tools/literature_handoff.py`.**
   - Keep bucket grading unchanged.
   - Add a helper such as `select_literature_handoff_papers(candidates, cap=100, policy="direct_all_pair_round_robin_100")`.
   - First compute eligible papers as direct/context only.
   - If `len(eligible) <= cap`, return all eligible papers and set `eligible_all_selected = true`.
   - If `len(eligible) > cap`, select with direct-first then LR-pair round-robin context truncation.
   - Use `inputs.lr_pairs` order for the round-robin pair order.
   - Use `supported_lr_pairs` and `context_lr_pairs` to assign context papers to pair queues.
   - Select multi-pair papers once, then skip duplicates in later pair queues.
   - Use original candidate order as the final deterministic tie-break.
   - Do not use `journal_quality` for handoff ordering; it was already used upstream by literature search sorting/truncation.
   - Deduplicate once, before selection.

- [ ] **Task 2: Update production handoff metadata.**
   - Change `DEFAULT_HANDOFF_CAP` from 40 to 100.
   - Add `policy.name`.
   - Add QC-friendly counts such as `eligible_count`, `eligible_all_selected`, `unused_capacity_count`, and `direct_truncated_count`.
   - Preserve existing `schema_version` unless a real backward-incompatible field removal is introduced.

- [ ] **Task 3: Update SEARCHER Production Mode instructions in `skills/biomedical-literature-search/SKILL.md`.**
   - Change the production handoff cap from 40 to 100.
   - State that cap 100 is an upper bound: when fewer than 100 eligible direct/context papers exist, `papers.json` should contain all eligible papers.
   - Explain that `papers_raw.json` and `citation_candidates.json` may be larger audit artifacts.
   - Do not instruct SEARCHER to expand raw retrieval solely to fill all 100 slots.

- [ ] **Task 4: Update production validation defaults where appropriate.**
   - `scripts/benchmarks/run_cci_production_handoff_validation.py` should default to the production cap-100 contract.
   - Its raw `--max-results` default should stay aligned with SEARCHER Production Mode unless a separate benchmark shows evidence starvation.
   - Do not mechanically update unrelated legacy content-utility or cap-40 benchmark defaults.

- [ ] **Task 5: Add a cap-100 QC runner or adapt the new ranking benchmark code into a single-policy QC path.**
   - Preferred new script name: `scripts/benchmarks/run_rag_handoff_qc.py`.
   - It should accept `--candidate-path`, `--candidate-glob`, `--output-dir`, and `--cap`.
   - It should not call raw literature search or LLM judges.
   - It should write the required QC files and Korean interpretation report.

- [ ] **Task 6: Update tests.**
   - `tests/deep_interpreter/test_literature_handoff.py`
     - default cap is 100
     - disease-only/rejected exclusion still holds
     - if eligible count is below 100, all eligible papers are selected and this is not treated as failure
     - all direct papers are included when direct count is below cap
     - context round-robin distributes across LR pairs
     - fallback unpaired context is used only after pair-scoped queues
     - unused capacity is reported without padding
   - `tests/deep_interpreter/test_skill_loader.py`
     - production skill text expects cap 100, not cap 40
     - retrieval-only benchmark text can remain cap-40 only if it explicitly describes the old benchmark mode
   - `tests/benchmarks/test_cci_production_handoff_policy_knobs.py`
     - verify production validation forwards the cap and new defaults correctly
   - Keep `tests/benchmarks/test_handoff_ranking_policy_benchmark.py` focused on the old cap-40 policy benchmark unless that script is intentionally archived.

- [ ] **Task 7: Run deterministic validation.**
   - First run QC against existing `citation_candidates.json` artifacts.
   - If eligible papers are fewer than 100, record `eligible_all_selected = true` and `unused_capacity_count`; do not treat it as a failed or underpowered run.
   - Run one production smoke only if needed to verify the updated `create_literature_handoff` production path.

---

## Verification Commands

Targeted tests:

```bash
uv run pytest \
  tests/deep_interpreter/test_literature_handoff.py \
  tests/deep_interpreter/test_skill_loader.py \
  tests/deep_interpreter/test_searcher_reflection_policy.py \
  tests/benchmarks/test_cci_production_handoff_policy_knobs.py \
  -q
```

Legacy cap-40 benchmark regression:

```bash
uv run pytest tests/benchmarks/test_handoff_ranking_policy_benchmark.py -q
```

Lint changed Python files:

```bash
uv run ruff check \
  src/agents/deep_interpreter/tools/literature_handoff.py \
  scripts/benchmarks/run_rag_handoff_qc.py \
  tests/deep_interpreter/test_literature_handoff.py
```

Deterministic QC from existing candidates:

```bash
uv run python scripts/benchmarks/run_rag_handoff_qc.py \
  --candidate-path /path/to/citation_candidates.json \
  --output-dir docs/benchmarks/lr_retrieval_relevance/results/cci_rag_ready_handoff_cap100_202606XX \
  --cap 100
```

Production smoke only if needed to verify the updated production path:

```bash
uv run python scripts/benchmarks/run_cci_production_handoff_validation.py \
  --cases docs/benchmarks/lr_retrieval_relevance/cci_cases.json \
  --output-dir docs/benchmarks/lr_retrieval_relevance/results/cci_rag_ready_handoff_cap100_202606XX \
  --run-id production_cap100_smoke \
  --case-limit 0 \
  --cap 100
```

---

## Result Interpretation Template

`RAG_HANDOFF_QC_KO.md` should answer:

1. `papers.json` selected all eligible direct/context papers up to the cap of 100.
2. Direct papers were all preserved unless direct evidence alone exceeded cap.
3. Disease-only/rejected leakage is zero.
4. LR pair coverage and concentration are acceptable for downstream RAG.
5. The previous cap-40 benchmark is not the primary evidence for the new cap-100 contract.

Recommended conclusion language:

> 이번 PR은 ranking policy 경쟁을 다시 수행한 것이 아니라, RAG 기반 INTERPRETER 입력 계약을 cap=100 상한으로 업데이트하고 deterministic QC로 검증한 PR이다. `papers.json`은 direct/context evidence만 포함하며, eligible direct/context가 100개 미만이면 전부 사용하고, 100개를 초과할 때만 direct 보존 및 LR pair round-robin으로 truncation한다.

---

## ADR

**Decision:** use a single RAG-ready handoff policy that selects all eligible direct/context papers up to cap 100 with QC reporting, not a cap-100 multi-policy benchmark.

**Drivers:**

- Downstream INTERPRETER now uses RAG and benefits from a larger citation corpus.
- The user-facing decision is the production handoff contract, not a ranking leaderboard.
- Cap 100 is a noise-control upper bound, not a requirement to force 100 papers into every case.
- Simple deterministic behavior is easier to reason about and test.

**Alternatives considered:**

- `baseline_current_cap100` vs `coverage_aware_cap100` vs journal tie-break: rejected because it repeats the cap-40 benchmark shape without a clear downstream decision.
- Passing all ~300 candidate papers to INTERPRETER: rejected because it makes the RAG context too broad and noisy.
- Expanding raw retrieval only to fill exactly 100 papers: rejected because eligible evidence quality is more important than reaching a fixed count.
- Keeping cap 40: rejected because it likely drops too much usable context for RAG interpretation.

**Consequences:**

- The next PR will produce descriptive QC metrics rather than inferential policy comparison statistics.
- Below-cap selected counts are valid when all eligible direct/context papers were selected.
- Cross-dataset validation remains a separate follow-up, not part of this contract-change PR.

**Follow-ups:**

- Optional: run the same cap-100 QC on a second disease/dataset once another production candidate artifact exists.
- Optional: evaluate final biological interpretation quality after the RAG interpreter consumes cap-100 `papers.json`.
