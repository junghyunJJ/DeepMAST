# Retrieval Skill-Only Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure the retrieval-only effect of `biomedical-literature-search` without mixing old figure inputs or unequal handoff policies, then regenerate `fig2.svg` and `figs2.svg` from the clean benchmark results.

**Architecture:** Split retrieval from evaluation. Skill ON and skill OFF both produce raw retrieval artifacts only; then the same posthoc direct/context filter with cap 40 is applied to both arms before gpt-5.4 content-utility judging. Production code still keeps `create_literature_handoff` as a source tool, but the skill owns the role-specific workflow policy.

**Tech Stack:** Python, pytest, LangChain tools/agents, Ollama qwen3.5 models, BioMCP/PubMed retrieval tools, JSON/CSV benchmark artifacts, gpt-5.4 judge, R tidyverse/cowplot/svglite manuscript figures.

---

## Scope And Stop Conditions

In scope:

- Update `skills/biomedical-literature-search/SKILL.md` with explicit role modes:
  - `PLANNER mode`: light context search, `max_results=10-20`, output `planner_papers.json`, no handoff, no `citation_candidates.json`, no `papers.json`, no INTERPRETER citation authority.
  - `SEARCHER production mode`: full raw retrieval, `max_results=100`, outputs `papers_raw.json`, `citation_candidates.json`, `papers.json`, and canonical INTERPRETER handoff.
  - `SEARCHER retrieval-only benchmark mode`: raw retrieval only, no `create_literature_handoff`, no `citation_candidates.json`, no filtered `papers.json`.
  - `REPORTER mode`: synthesis search only when needed, outputs `synthesis_papers_raw.json`, `synthesis_citation_candidates.json`, `synthesis_papers.json`, and never overwrites `papers.json`.
- Keep `create_literature_handoff` implemented in `src/agents/deep_interpreter/tools/literature_handoff.py`.
- Move detailed raw-to-handoff policy out of the base SEARCHER prompt and into the skill.
- Run Benchmark A:
  - skill ON: updated skill retrieval strategy, retrieval-only mode, raw papers only.
  - skill OFF: same cases and wrapper contract, no skill search/report guidance, raw papers only.
  - common posthoc filter: direct/context usable citable papers only, cap 40.
  - gpt-5.4 judge: real-use primary with cap 40 and matched-budget sensitivity.
- Regenerate figure inputs and final `fig2.svg` / `figs2.svg` from the new clean results only.

Out of scope:

- Benchmark B end-to-end production effect.
- Handoff ranking policy ablation beyond the current direct-first/context fallback behavior.
- Changing the internal `coverage_weighted_sort` algorithm or `alpha=0.4`.
- Reusing old `full_paper_relevance_v1` RDS files for final figures.

Stop condition:

- Do not run full live qwen benchmarks until targeted tests pass.
- Do not run qwen benchmarks unless `curl -s http://localhost:7000/api/tags` and `curl -s http://localhost:6000/api/tags` both reach the expected Ollama servers.
- Stop the benchmark sequence on the first smoke failure and write `RESULTS_KO.md` in the failed smoke root.

---

## File Structure

Modify:

- `skills/biomedical-literature-search/SKILL.md`
  - Add role-mode sections and retrieval-only benchmark mode.
  - Keep production handoff policy in SEARCHER production mode.
- `skills/biomedical-literature-search/references/search_strategies.md`
  - Mirror role-specific output paths and do-not-overwrite rules.
- `src/agents/deep_interpreter/subagents/prompts.py`
  - Keep SEARCHER invariants and skill activation.
  - Remove detailed `papers_raw.json -> citation_candidates.json -> papers.json` instructions from base prompt.
  - Keep INTERPRETER citation invariant: read filtered `/papers.json` only in production runs.
- `docs/benchmarks/harness_x_model/common.py`
  - Add retrieval-only benchmark prompt mode.
  - Make skill ON use retrieval-only skill guidance.
  - Make skill OFF use the same retrieval-only wrapper output contract without skill guidance.
- `scripts/benchmarks/run_cci_searcher_skill_onoff_benchmark.py`
  - Add a clean Benchmark A mode and new output root naming.
  - Ensure agent execution writes raw retrieval artifacts only.
  - Apply common posthoc `create_literature_handoff` to both arms after retrieval for audit/evaluation.
- `scripts/benchmarks/run_cci_content_utility_from_skill_onoff.py`
  - Set `--cap` default to `40` for Benchmark A runs.
  - Preserve real-use and matched-budget protocols.
- `docs/benchmarks/lr_retrieval_relevance/build_content_utility_reports.py`
  - Preserve common grading from raw papers.
  - Support cap 40 manifests cleanly.
- `docs/benchmarks/lr_retrieval_relevance/content_utility_manuscript_figures.R`
  - Stop reading old `full_paper_relevance_v1` RDS inputs for clean Benchmark A figures.
  - Read new Benchmark A figure tables/RDS generated from the new result root.

Create:

- `tests/benchmarks/test_retrieval_skill_only_benchmark.py`
  - Tests retrieval-only prompt behavior, no agent-side handoff, common posthoc filter, cap 40.
- `docs/benchmarks/lr_retrieval_relevance/retrieval_skill_only_figures.py`
  - Builds new figure source tables/RDS from Benchmark A results.
- New result roots:
  - `docs/benchmarks/lr_retrieval_relevance/results/cci_retrieval_skill_only_qwen_smoke/`
  - `docs/benchmarks/lr_retrieval_relevance/results/cci_retrieval_skill_only_qwen_full/`
  - `docs/benchmarks/lr_retrieval_relevance/results/cci_retrieval_skill_only_content_utility_gpt54_live/`

---

## Task 1: Lock The Clean Benchmark A Contract

**Files:**

- Create: `tests/benchmarks/test_retrieval_skill_only_benchmark.py`
- Modify: `docs/benchmarks/harness_x_model/common.py`
- Modify: `scripts/benchmarks/run_cci_searcher_skill_onoff_benchmark.py`

- [ ] **Step 1: Write tests for retrieval-only prompt and output contract**

Create `tests/benchmarks/test_retrieval_skill_only_benchmark.py`:

```python
from __future__ import annotations

from docs.benchmarks.harness_x_model.common import compose_searcher_prompt


def test_retrieval_only_skill_on_mentions_raw_only_and_forbids_handoff():
    prompt = compose_searcher_prompt(
        skill_on=True,
        benchmark_mode="retrieval_only",
    )
    assert "SEARCHER retrieval-only benchmark mode" in prompt
    assert "papers_raw.json" in prompt
    assert "Do not call `create_literature_handoff`" in prompt
    assert "Do not write `/citation_candidates.json`" in prompt
    assert "Default handoff cap is `40`" not in prompt


def test_retrieval_only_skill_off_has_no_biomedical_skill_guidance():
    prompt = compose_searcher_prompt(
        skill_on=False,
        benchmark_mode="retrieval_only",
    )
    assert "biomedical-literature-search" not in prompt
    assert "SEARCHER retrieval-only benchmark mode" in prompt
    assert "Do not call `create_literature_handoff`" in prompt
    assert "Advanced Kwargs" not in prompt
```

- [ ] **Step 2: Run the tests and confirm they fail before implementation**

Run:

```bash
pytest tests/benchmarks/test_retrieval_skill_only_benchmark.py -q
```

Expected before implementation:

```text
FAILED ... benchmark_mode must be one of 'B', 'B_prime', 'C'
```

- [ ] **Step 3: Add `retrieval_only` benchmark mode**

Modify `docs/benchmarks/harness_x_model/common.py`:

```python
BENCHMARK_MODE = Literal["B", "B_prime", "C", "retrieval_only"]
```

Add a retrieval-only appendix:

```python
BENCHMARK_APPENDIX_RETRIEVAL_ONLY = """
## Benchmark Mode Override: SEARCHER retrieval-only benchmark mode

You are running a retrieval-only skill benchmark.

1. Read `/data_path.txt` to get the workspace directory.
2. Read `/benchmark_case.json` to get the exact benchmark case payload.
3. Extract `search_context` from that file and write it to `/search_context.json`.
4. Run `search_literature_dynamic` using the benchmark case context.
5. Save raw retrieval to `/papers_raw.json`.
6. Do not call `create_literature_handoff`.
7. Do not write `/citation_candidates.json`.
8. Do not write a filtered `/papers.json`.

The benchmark runner will apply the same posthoc direct/context filter to both
arms after retrieval. Your job in this mode is retrieval only.
""".strip()
```

In `compose_searcher_prompt`, branch before the existing B/B_prime/C logic:

```python
if benchmark_mode == "retrieval_only":
    base = SUBAGENT_PROMPTS["searcher"].replace(HARDCODED_SKILL_BLOCK, BENCHMARK_SKILL_BLOCK)
    for section in _SEARCHER_PROMPT_KWARG_STRIPS:
        if section in base:
            base = base.replace(section, "")
    base = base.strip()
    harness_prompt = _render_skill_harness_prompt(skill_on)
    if skill_on:
        harness_prompt = f"{harness_prompt}\n\n{BENCHMARK_SKILL_KWARG_HINT}"
    return f"{base}\n\n{BENCHMARK_APPENDIX_RETRIEVAL_ONLY}\n\n{harness_prompt}".strip()
```

- [ ] **Step 4: Make trial results point at raw retrieval in retrieval-only mode**

In `run_single_trial`, choose the expected artifact by mode:

```python
artifact_name = "papers_raw.json" if benchmark_mode == "retrieval_only" else "papers.json"
```

Use `artifact_name` when initializing `papers_path` and when checking existence.

- [ ] **Step 5: Run tests**

Run:

```bash
pytest tests/benchmarks/test_retrieval_skill_only_benchmark.py -q
```

Expected:

```text
2 passed
```

---

## Task 2: Update The Skill Role Modes

**Files:**

- Modify: `skills/biomedical-literature-search/SKILL.md`
- Modify: `skills/biomedical-literature-search/references/search_strategies.md`
- Test: `tests/deep_interpreter/test_skill_loader.py`

- [ ] **Step 1: Add explicit role-mode sections to `SKILL.md`**

Edit `skills/biomedical-literature-search/SKILL.md` so it contains these section headers and contracts:

```markdown
## PLANNER Mode

- Purpose: lightweight context search for feasibility and planning.
- Use `max_results=10` to `20`.
- Write `planner_papers.json`.
- Do not call `create_literature_handoff`.
- Do not write `citation_candidates.json`.
- Do not write or overwrite `papers.json`.
- PLANNER papers are not INTERPRETER citation authority.

## SEARCHER Production Mode

- Purpose: canonical INTERPRETER evidence handoff.
- Use broad raw retrieval with `max_results=100`.
- Save raw retrieval to `papers_raw.json`.
- Call `create_literature_handoff`.
- Write `citation_candidates.json` as the full bucket audit artifact.
- Write `papers.json` as the filtered INTERPRETER handoff.
- `papers.json` contains only `direct_lr_evidence` and `receptor_pathway_context_evidence`.
- Default handoff cap is `40`.

## SEARCHER Retrieval-Only Benchmark Mode

- Purpose: isolate retrieval skill effects.
- Use the same retrieval strategy as SEARCHER Production Mode.
- Save raw retrieval to `papers_raw.json`.
- Do not call `create_literature_handoff`.
- Do not write `citation_candidates.json`.
- Do not write filtered `papers.json`.
- The benchmark runner applies the same direct/context cap-40 filter to skill ON and skill OFF arms after retrieval.

## REPORTER Mode

- Purpose: optional synthesis support after INTERPRETER outputs exist.
- Do not overwrite `papers.json`.
- Use `synthesis_papers_raw.json` for raw synthesis retrieval.
- Use `synthesis_citation_candidates.json` for synthesis audit.
- Use `synthesis_papers.json` for REPORTER-only direct/context synthesis citations.
- Disease-only papers can support background prose only; they must not support LR or mechanism claims.
```

- [ ] **Step 2: Mirror output-path rules in `references/search_strategies.md`**

Add this invariant block:

```markdown
## Output Path Invariants

- `papers.json` is reserved for SEARCHER Production Mode and is the canonical INTERPRETER citation source.
- PLANNER writes only `planner_papers.json`.
- SEARCHER Retrieval-Only Benchmark Mode writes only `papers_raw.json` before the runner's common posthoc filter.
- REPORTER writes only `synthesis_*` literature artifacts.
- No role except SEARCHER Production Mode may overwrite `papers.json`.
```

- [ ] **Step 3: Run skill loader tests**

Run:

```bash
pytest tests/deep_interpreter/test_skill_loader.py -q
```

Expected:

```text
passed
```

---

## Task 3: Keep Base SEARCHER Prompt Policy-Light

**Files:**

- Modify: `src/agents/deep_interpreter/subagents/prompts.py`
- Test: `tests/deep_interpreter/test_searcher_reflection_policy.py`
- Test: `tests/deep_interpreter/test_interpreter_prompt_policy.py`

- [ ] **Step 1: Remove detailed handoff workflow from base SEARCHER prompt**

In `SEARCHER_PROMPT`, keep these invariants:

```markdown
## SEARCHER Invariants

- Evaluate and load the applicable literature skill before literature work.
- Search before INTERPRETER runs.
- In production runs, INTERPRETER must receive `/papers.json`.
- Follow the loaded skill's role mode for exact output paths and handoff behavior.
```

Remove detailed instructions from the base prompt that enumerate:

```text
papers_raw.json -> citation_candidates.json -> papers.json
direct_lr_evidence / receptor_pathway_context_evidence / disease_only_background / rejected_weak_evidence
```

Those details must live in `skills/biomedical-literature-search/SKILL.md`.

- [ ] **Step 2: Preserve INTERPRETER citation invariant**

Keep INTERPRETER prompt language equivalent to:

```markdown
Read filtered `/papers.json` as the only citation source for INTERPRETER claims.
If evidence is missing, mark an evidence gap instead of inventing citations.
```

- [ ] **Step 3: Run prompt-policy tests**

Run:

```bash
pytest tests/deep_interpreter/test_searcher_reflection_policy.py tests/deep_interpreter/test_interpreter_prompt_policy.py -q
```

Expected:

```text
passed
```

---

## Task 4: Apply Common Direct/Context Filter With Cap 40

**Files:**

- Modify: `scripts/benchmarks/run_cci_searcher_skill_onoff_benchmark.py`
- Modify: `scripts/benchmarks/run_cci_content_utility_from_skill_onoff.py`
- Modify: `docs/benchmarks/lr_retrieval_relevance/build_content_utility_reports.py`
- Test: `tests/benchmarks/test_cci_searcher_skill_onoff_benchmark.py`
- Test: `tests/benchmarks/test_cci_content_utility_from_skill_onoff.py`

- [ ] **Step 1: Add Benchmark A mode to the searcher skill ON/OFF runner**

In `scripts/benchmarks/run_cci_searcher_skill_onoff_benchmark.py`, add:

```python
parser.add_argument(
    "--benchmark-mode",
    choices=["production", "retrieval_only"],
    default="retrieval_only",
)
```

Map `--benchmark-mode retrieval_only` to `run_single_trial(..., benchmark_mode="retrieval_only")`.

- [ ] **Step 2: Keep posthoc handoff common across both arms**

In retrieval-only mode, run `_run_handoff(row, case)` after raw retrieval for both skill ON and skill OFF. Store the result as common evaluation artifacts:

```text
papers_raw.json
citation_candidates.json
papers_filtered.json
```

Do not treat `papers_filtered.json` as agent-produced production handoff. It is the common posthoc evaluation filter.

- [ ] **Step 3: Set content-utility cap to 40**

In `scripts/benchmarks/run_cci_content_utility_from_skill_onoff.py`, change the default cap:

```python
parser.add_argument("--cap", type=int, default=40)
```

In `docs/benchmarks/lr_retrieval_relevance/build_content_utility_reports.py`, change:

```python
DEFAULT_CAP = 40
```

- [ ] **Step 4: Preserve real-use and matched-budget protocols**

Verify `_selection_limits` keeps:

```python
if protocol == PROTOCOL_REALUSE:
    return {arm: min(cap, counts[arm]) for arm in ARM_NAMES}, []
if protocol == PROTOCOL_MATCHED:
    matched_n = min(cap, *(counts[arm] for arm in ARM_NAMES))
```

This makes primary `real-use cap 40` and sensitivity `matched budget <= 40`.

- [ ] **Step 5: Run benchmark runner tests**

Run:

```bash
pytest tests/benchmarks/test_cci_searcher_skill_onoff_benchmark.py tests/benchmarks/test_cci_content_utility_from_skill_onoff.py -q
```

Expected:

```text
passed
```

---

## Task 5: Generate New Figure Inputs From Clean Results

**Files:**

- Create: `docs/benchmarks/lr_retrieval_relevance/retrieval_skill_only_figures.py`
- Modify: `docs/benchmarks/lr_retrieval_relevance/content_utility_manuscript_figures.R`
- Test: `tests/benchmarks/test_retrieval_skill_only_benchmark.py`

- [ ] **Step 1: Create figure table builder**

Create `docs/benchmarks/lr_retrieval_relevance/retrieval_skill_only_figures.py` with functions that read:

```text
docs/benchmarks/lr_retrieval_relevance/results/cci_retrieval_skill_only_qwen_full/summary.json
docs/benchmarks/lr_retrieval_relevance/results/cci_retrieval_skill_only_content_utility_gpt54_live/analysis.json
```

and write:

```text
manuscript/tables/fig2b_raw_bucket_composition.csv
manuscript/tables/fig2c_selected_count.csv
manuscript/tables/fig2d_overlap.csv
```

Required columns:

```text
model_strength, model, skill_arm, bucket, count
model_strength, model, skill_arm, selected_count, direct_count, context_count
model_strength, shared_pmids, skill_only_pmids, no_skill_only_pmids
```

- [ ] **Step 2: Ensure figures do not read old RDS**

Modify `content_utility_manuscript_figures.R` so clean Benchmark A rendering reads the CSV files above from:

```text
docs/benchmarks/lr_retrieval_relevance/results/cci_retrieval_skill_only_content_utility_gpt54_live/manuscript/tables/
```

Do not read:

```text
docs/benchmarks/lr_retrieval_relevance/results/full_paper_relevance_v1/paper_relevance/figures/*.rds
```

- [ ] **Step 3: Add a regression test that rejects old RDS inputs**

Add this assertion to `tests/benchmarks/test_retrieval_skill_only_benchmark.py`:

```python
from pathlib import Path


def test_clean_figures_do_not_read_old_full_paper_relevance_rds():
    script = Path(
        "docs/benchmarks/lr_retrieval_relevance/content_utility_manuscript_figures.R"
    ).read_text()
    assert "full_paper_relevance_v1/paper_relevance/figures" not in script
    assert "fig2b_raw_bucket_composition.csv" in script
```

- [ ] **Step 4: Run figure tests**

Run:

```bash
pytest tests/benchmarks/test_retrieval_skill_only_benchmark.py -q
```

Expected:

```text
passed
```

---

## Task 6: Smoke, Full Benchmark, Judge, Figures

**Files:**

- Output: `docs/benchmarks/lr_retrieval_relevance/results/cci_retrieval_skill_only_qwen_smoke/`
- Output: `docs/benchmarks/lr_retrieval_relevance/results/cci_retrieval_skill_only_qwen_full/`
- Output: `docs/benchmarks/lr_retrieval_relevance/results/cci_retrieval_skill_only_content_utility_gpt54_live/`

- [ ] **Step 1: Verify qwen model servers**

Run:

```bash
curl -s http://localhost:7000/api/tags | rg 'qwen3.5:35b'
curl -s http://localhost:6000/api/tags | rg 'qwen3.5:122b'
```

Expected:

```text
qwen3.5:35b
qwen3.5:122b
```

- [ ] **Step 2: Run one-case smoke**

Run:

```bash
python scripts/benchmarks/run_cci_searcher_skill_onoff_benchmark.py \
  --cases docs/benchmarks/cci_skill_ablation/cases/cci_full_cases.json \
  --output-dir docs/benchmarks/lr_retrieval_relevance/results/cci_retrieval_skill_only_qwen_smoke \
  --workspace-root docs/benchmarks/lr_retrieval_relevance/results/cci_retrieval_skill_only_qwen_smoke_workspaces \
  --case-limit 1 \
  --repeats 1 \
  --conditions weak_on,weak_off,strong_on,strong_off \
  --benchmark-mode retrieval_only
```

Expected:

```text
exit code 0
```

Check:

```bash
test -f docs/benchmarks/lr_retrieval_relevance/results/cci_retrieval_skill_only_qwen_smoke/RESULTS_KO.md
test -f docs/benchmarks/lr_retrieval_relevance/results/cci_retrieval_skill_only_qwen_smoke/summary.json
```

- [ ] **Step 3: Run full 30-LR retrieval benchmark**

Run:

```bash
python scripts/benchmarks/run_cci_searcher_skill_onoff_benchmark.py \
  --cases docs/benchmarks/cci_skill_ablation/cases/cci_full_cases.json \
  --output-dir docs/benchmarks/lr_retrieval_relevance/results/cci_retrieval_skill_only_qwen_full \
  --workspace-root docs/benchmarks/lr_retrieval_relevance/results/cci_retrieval_skill_only_qwen_full_workspaces \
  --case-limit 0 \
  --repeats 1 \
  --conditions weak_on,weak_off,strong_on,strong_off \
  --benchmark-mode retrieval_only
```

Expected:

```text
exit code 0
120 rows
0 error rows
```

- [ ] **Step 4: Run live gpt-5.4 content-utility judge with cap 40**

Run:

```bash
python scripts/benchmarks/run_cci_content_utility_from_skill_onoff.py \
  --skill-results-dir docs/benchmarks/lr_retrieval_relevance/results/cci_retrieval_skill_only_qwen_full \
  --cases docs/benchmarks/cci_skill_ablation/cases/cci_full_cases.json \
  --output-dir docs/benchmarks/lr_retrieval_relevance/results/cci_retrieval_skill_only_content_utility_gpt54_live \
  --protocol all \
  --score-mode live \
  --judge-model gpt-5.4 \
  --cap 40 \
  --cap-rationale "INTERPRETER production handoff cap"
```

Expected:

```text
exit code 0
realuse/judge_rows_live.jsonl exists
matched/judge_rows_live.jsonl exists
RESULTS_KO.md exists
```

- [ ] **Step 5: Build clean figure source tables and render figures**

Run:

```bash
python docs/benchmarks/lr_retrieval_relevance/retrieval_skill_only_figures.py \
  --retrieval-root docs/benchmarks/lr_retrieval_relevance/results/cci_retrieval_skill_only_qwen_full \
  --content-root docs/benchmarks/lr_retrieval_relevance/results/cci_retrieval_skill_only_content_utility_gpt54_live

Rscript docs/benchmarks/lr_retrieval_relevance/content_utility_manuscript_figures.R \
  docs/benchmarks/lr_retrieval_relevance/results/cci_retrieval_skill_only_content_utility_gpt54_live
```

Expected:

```text
manuscript/figures/fig2.svg
manuscript/figures/figs2.svg
```

---

## Task 7: Verification And Reporting

**Files:**

- Modify: `docs/benchmarks/lr_retrieval_relevance/results/cci_retrieval_skill_only_qwen_full/RESULTS_KO.md`
- Modify: `docs/benchmarks/lr_retrieval_relevance/results/cci_retrieval_skill_only_content_utility_gpt54_live/RESULTS_KO.md`

- [ ] **Step 1: Run targeted tests**

Run:

```bash
pytest \
  tests/benchmarks/test_retrieval_skill_only_benchmark.py \
  tests/benchmarks/test_cci_searcher_skill_onoff_benchmark.py \
  tests/benchmarks/test_cci_content_utility_from_skill_onoff.py \
  tests/deep_interpreter/test_skill_loader.py \
  tests/deep_interpreter/test_searcher_reflection_policy.py \
  tests/deep_interpreter/test_interpreter_prompt_policy.py \
  -q
```

Expected:

```text
passed
```

- [ ] **Step 2: Run syntax checks**

Run:

```bash
python -m py_compile \
  docs/benchmarks/harness_x_model/common.py \
  scripts/benchmarks/run_cci_searcher_skill_onoff_benchmark.py \
  scripts/benchmarks/run_cci_content_utility_from_skill_onoff.py \
  docs/benchmarks/lr_retrieval_relevance/build_content_utility_reports.py \
  docs/benchmarks/lr_retrieval_relevance/retrieval_skill_only_figures.py
```

Expected: command exits `0`.

- [ ] **Step 3: Verify figure files**

Run:

```bash
test -s docs/benchmarks/lr_retrieval_relevance/results/cci_retrieval_skill_only_content_utility_gpt54_live/manuscript/figures/fig2.svg
test -s docs/benchmarks/lr_retrieval_relevance/results/cci_retrieval_skill_only_content_utility_gpt54_live/manuscript/figures/figs2.svg
rsvg-convert docs/benchmarks/lr_retrieval_relevance/results/cci_retrieval_skill_only_content_utility_gpt54_live/manuscript/figures/fig2.svg -o /tmp/deepmast_clean_fig2.png
rsvg-convert docs/benchmarks/lr_retrieval_relevance/results/cci_retrieval_skill_only_content_utility_gpt54_live/manuscript/figures/figs2.svg -o /tmp/deepmast_clean_figs2.png
```

Expected: all commands exit `0`.

- [ ] **Step 4: Write Korean conclusions**

Ensure both `RESULTS_KO.md` files state:

```markdown
## 핵심 결론

이 benchmark는 retrieval skill-only 효과를 평가한다. skill ON/OFF가 모두 raw retrieval을 먼저 수행하고, 이후 동일한 direct/context cap=40 posthoc filter와 gpt-5.4 judge를 적용한다. 따라서 결과 차이는 production handoff policy 차이가 아니라 검색 전략과 raw retrieval quality 차이로 해석한다.
```

- [ ] **Step 5: Final git status review**

Run:

```bash
git status --short
```

Expected:

```text
Only planned source/test/docs files and new benchmark result roots are changed.
No old full_paper_relevance_v1 RDS artifacts are used as final figure inputs.
```

---

## Acceptance Criteria

- `biomedical-literature-search` clearly documents PLANNER, SEARCHER production, SEARCHER retrieval-only benchmark, and REPORTER modes.
- Base SEARCHER prompt no longer owns detailed handoff workflow policy.
- Benchmark A skill ON/OFF rows are raw retrieval first; agent-side production handoff is not part of either retrieval arm.
- Common posthoc filter applies the same direct/context usable-citable policy to both arms.
- Content-utility judge uses cap 40 for real-use primary and matched-budget sensitivity.
- New `fig2.svg` and `figs2.svg` are generated from clean Benchmark A results, not old `full_paper_relevance_v1` RDS files.
- Existing results remain in their original folders; clean Benchmark A outputs are stored under new `cci_retrieval_skill_only_*` result roots.
