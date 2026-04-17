# Harness X Model Runbook

This benchmark measures whether exposing the SEARCHER agent to the
`biomedical-literature-search` skill improves literature-search coverage,
and whether that effect is moderated by model strength
(`qwen3.5:122b` vs `qwen3.5:35b`).

Authoritative spec: [`REV5_PLAN.md`](REV5_PLAN.md). Rejected alternative
design kept for context: [`REV5_PLAN_OPTION_B_ARCHIVED.md`](REV5_PLAN_OPTION_B_ARCHIVED.md).

## Files

- `common.py` — shared dataclass (`SearchTrialResult`), schedule builder,
  prompt composer, trial runner, and `check_pilot_gates` for the REV5 §8
  4-gate decision.
- `run_trial.py` — single-trial CLI used for debug / smoke runs.
- `run_pilot.py` — 48-trial pilot (12 cases × 4 conditions × 1 repeat) with
  mandatory REV5 §8 gate enforcement on exit.
- `run_full.py` — 360-trial full run (30 cases × 4 conditions × 3 repeats),
  stratification-enforced via `--max-cases 30` or `--per-category N`.
- `harness_x_model_glmm.R` — primary GLMM + sensitivity GLMM (tag-off) + LMM
  secondary + LRT + `emmeans` simple effects + case-level bootstrap CI +
  optional `simr::powerSim`.
- `__init__.py` — marks the directory as a Python package so the runner
  scripts can `from docs.benchmarks.harness_x_model.common import ...`.

## Prerequisites

**Ollama models** (~110 GB combined; A100 80 GB cannot hold both
simultaneously and will swap once per model change):

```bash
ollama pull qwen3.5:122b
ollama pull qwen3.5:35b
```

**BioMCP server** reachable from the runner host. The benchmark depends on
BioMCP for both retrieval and for the production tag-on coverage semantics.

**Environment variables**:

- `OLLAMA_BASE_URL` — Ollama endpoint (default `http://localhost:6000`).
- **Do NOT** export `DEEP_INTERPRETER_DATA_DIR`. The runner sets it per
  trial inside `build_searcher_for_trial` (`common.py:255`); any prior
  export is overwritten silently and will not take effect.

**Python**: use the project DeepMAST environment (contains `langgraph`,
`langchain`, `deepagents`, etc.).

**R packages** (for post-hoc analysis):

```r
install.packages(c("jsonlite", "lme4", "emmeans", "dplyr"))
install.packages("simr")  # optional; gracefully skipped if absent
```

## Input case pack

Default case pack: `docs/benchmarks/cci_skill_ablation/cases/cci_full_cases.json`
— 30 L-R cases in 6 strata (`{low,medium,high}_morans_{known,unknown}` × 5
cases per stratum). The pilot stratified selector picks 2 per stratum → 12
cases. 19 of 30 cases have empty `pathway_associations`, so `coverage_pass`
degrades gracefully to a gene-only gate on those cases (documented REV5 §7
caveat; handled identically in all 4 arms).

## What each trial does

1. Normalize the case into `genes / pathways / celltypes / disease`
   (`normalize_case` in `common.py`).
2. Create an isolated workspace and pre-seed `/data_path.txt` +
   `/benchmark_case.json`.
3. Build a benchmark-mode SEARCHER agent via
   `langgraph.prebuilt.create_react_agent` with:
   - the production SEARCHER tool stack
     (`src/agents/deep_interpreter/subagents/configs.py`)
   - standalone `read_file` / `write_file` (production uses deepagents
     `FilesystemMiddleware`; see **Measurement caveats**)
   - SEARCHER prompt with `HARDCODED_SKILL_BLOCK` string-replaced by a
     benchmark skill block, a `BENCHMARK_APPENDIX` prepended, and the
     active skill registry rendered via `SkillLoadHarness._prompt_template`
   - recursion limit 150
4. Invoke the agent with a fixed user message; the agent calls
   `search_literature_dynamic` with `enable_lr_pair_queries=True,
   coverage_weighted_sort=True` (pinned in both arms) and auto-saves
   `/papers.json` + `/search_context.json`.
5. Compute **both** tag-on and tag-off coverage from the same papers,
   populate BioMCP telemetry (best-effort coarse proxies), append one row
   to `results/{mode}/trial_NNNN.jsonl`.

## Recommended workflow

```
smoke test → pilot 48 → pilot_gates.json review → go/no-go → full 360 → GLMM
```

### 1. Smoke test (unit suite only)

```bash
pytest tests/benchmarks/test_harness_x_model.py -v
```

All **44 tests** must pass (12 core + 14 mode/schema parity + 9 resume
guards + 5 gate thresholds + 4 bonus defensive). End-to-end single-trial
verification requires a live Ollama + BioMCP and is not covered by pytest.

### 2. Pilot (48 trials, ~4 hours)

```bash
python docs/benchmarks/harness_x_model/run_pilot.py \
  --results-dir docs/benchmarks/harness_x_model/results/pilot \
  --workspace-root docs/benchmarks/harness_x_model/workspaces/pilot \
  --per-category 2 --repeats 1
```

The runner exits **non-zero** if any REV5 §8 gate fails (pass
`--ignore-gates` only if you explicitly want to proceed anyway).
`pilot_gates.json` is written alongside `pilot_summary.json`.

### 3. Pilot gate review

```bash
cat docs/benchmarks/harness_x_model/results/pilot/pilot_gates.json
Rscript docs/benchmarks/harness_x_model/harness_x_model_glmm.R \
  docs/benchmarks/harness_x_model/results/pilot \
  docs/benchmarks/harness_x_model/results/pilot/glmm_summary.json \
  1000 200
```

**Gate decision rules (Rev 4)**:

| Gate | Failure condition | Remediation |
|---|---|---|
| A (saturation) | both strong arms have median `celltypes_coverage_pct ≥ 90` | Switch endpoint to unique_PMIDs / novelty per PREREGISTRATION §12 |
| **Null** (mode B only) | per-arm celltype Δ (on − off) ≥ 3 pp in either model strength | **STOP** — measurement scaffolding contaminated; investigate before firing B' / C |
| B (BioMCP) | `biomcp_error` rate ≥ 5% or median latency ≥ 10 min | Apply §6 outage exclusion and re-pilot |
| C (distributional) | any condition has ≤ 3 discrete rounded celltype values | Drop LMM secondary, GLMM-only |
| Variance | mean per-case between-condition std-dev < 2 pp | Raise temperature to 0.5 and re-pilot |
| Power | `power_sim.power < 0.8` for the interaction | Raise repeats to 5 (600 trials) or report main effects only |

All applicable gates PASS → proceed to full run. Gate Null applies **only** when `--mode B`; modes B'/C skip it cleanly.

### 4. Full run (360 trials, ~18–30 hours)

```bash
python docs/benchmarks/harness_x_model/run_full.py \
  --results-dir docs/benchmarks/harness_x_model/results/full \
  --workspace-root docs/benchmarks/harness_x_model/workspaces/full \
  --repeats 3
```

`--max-cases` only accepts 30 (canonical). Use `--per-category N` for
stratified debug subsets (total = N × 6 strata). Non-stratified slices
raise `SystemExit` to prevent measurement contamination.

### 5. Full-run analysis

```bash
Rscript docs/benchmarks/harness_x_model/harness_x_model_glmm.R \
  docs/benchmarks/harness_x_model/results/full \
  docs/benchmarks/harness_x_model/results/full/glmm_summary.json \
  10000 500
```

The R script reports:

- **Primary**: GLMM on `coverage_pass` (tag-on) with
  `skill_on * model_strength + (1 | case_id)`, LRT vs the additive model.
- **Sensitivity**: GLMM on `coverage_pass_tagoff` (tag-off; REV5 §1 fix).
- **Secondary**: LMM on continuous `genes_coverage_pct`.
- **Simple effects** via `emmeans` if the interaction is significant.
- **Bootstrap CI**: case-level percentile bootstrap, 10 000 iterations.
- **Power simulation**: `simr::powerSim` on the interaction LRT, 500 sims
  (skipped gracefully if `simr` is not installed).
- **Factor levels** pinned: `skill_on` `FALSE→TRUE`, `model_strength`
  `weak→strong`.

## Single-trial debug

```bash
python docs/benchmarks/harness_x_model/run_trial.py \
  --case-id cci_full_01_EGF_RACK1 \
  --condition strong_on --repeat 1 --trial-index 1 \
  --results-dir docs/benchmarks/harness_x_model/results/debug \
  --workspace-root docs/benchmarks/harness_x_model/workspaces/debug
```

Valid `--condition` values: `strong_on`, `strong_off`, `weak_on`, `weak_off`.

## Wall-clock estimates

| Phase | Trials | Expected | Notes |
|---|---:|---:|---|
| Pilot | 48 | ~4 h | 12 cases × 4 × 1 |
| Full | 360 | ~18–30 h | 30 cases × 4 × 3; see swap overhead below |

**Model-swap overhead** (A100 80 GB): Option β with
model-stickiness-preserving shuffle produces ~135 swaps across the full run
(down from ~226 before T6), for ~68 min of reload overhead. A stricter
Latin-square alternation could lower this to ~90 swaps if needed — listed
under deferred items.

## Resume behavior

`run_pilot.py` and `run_full.py` read completed trials from
`results_dir/trial_*.jsonl` at startup (`load_completed_trial_indices`).
A trial is considered complete **only when its latest row has no `error`
field set** — error rows are retried on resume. The R analyzer drops rows
with `error` before fitting, so retries are safe.

`prepare_trial_workspace(clean=True)` wipes the workspace before each
trial. Combined with the resume logic, this means manual re-runs of
already-successful trials destroy any existing `papers.json`; if you need
to inspect the exact workspace from a past trial, copy it elsewhere first.

## Measurement caveats (Methods-section-ready)

- **Dual-endpoint coverage**: every trial records both `coverage_pass`
  (tag-on, primary — matches production `_calculate_coverage` under
  `enable_lr_pair_queries=True`) and `coverage_pass_tagoff` (tag-off
  sensitivity — addresses REV5 §1's critique of retrieval-tag credit
  inflation). Report both in the paper; treat the primary as the
  confirmatory analysis and the tag-off as a required supplement.
- **SEARCHER Phase 1 bypass**: the benchmark pre-seeds
  `/benchmark_case.json` with a pre-extracted `search_context` and the
  `BENCHMARK_APPENDIX` tells the LLM not to call `load_analysis_data`. The
  benchmark measures SEARCHER Phase 2/3/4 (query emission + search +
  coverage reflection); Phase 1 (data loading) is not exercised. This is a
  known deviation from "byte-identical to production" — document it in the
  Methods scope statement.
- **Tool kwargs pinned**: `enable_lr_pair_queries=True,
  coverage_weighted_sort=True` are set identically in both arms. Skill
  ON/OFF varies only query content and SKILL.md reading, not search-tool
  configuration.
- **Middleware**: production wraps SEARCHER with
  `WriteFileArgGuardMiddleware` + runtime `SkillLoadHarness` (re-injected
  on every model call). The benchmark uses `create_react_agent` with
  neither — `SkillLoadHarness._prompt_template` is rendered once into the
  initial system prompt. See deferred Tier-2 item H4 below.
- **BioMCP telemetry**: `biomcp_latency_ms`, `biomcp_error`,
  `biomcp_paper_count_raw` are coarse proxies (total trial latency, saved
  error field, `len(papers)`). Production does not emit per-call BioMCP
  telemetry; fine-grained instrumentation is a deferred Tier-2 item. The
  outage exclusion rule (`paper_count_raw==0 AND latency_ms>30000`) is
  still applied, just with coarser signals than REV5 §6 originally
  envisioned.
- **Schedule randomization**: Option β with per-case adjacency and
  model-stickiness preserving shuffle. Intra-case model swaps are bounded
  to exactly 1 per case; inter-case transitions are ~50% random. 135
  swaps ≈ 68 min reload overhead across the full run.

## Deferred items (Tier 2/3)

Listed in the project plan file. Not blockers for the pilot, but must be
addressed before the full-run Methods section is finalized:

- **H1** — Resolve `BENCHMARK_APPENDIX` vs SEARCHER Phase 1 prompt
  conflict (either string-replace Phase 1 instructions or stub
  `load_analysis_data`).
- **H4** — Attach `WriteFileArgGuardMiddleware` and runtime
  `SkillLoadHarness` re-injection to the benchmark `create_react_agent`
  call.
- **H6** — Add a public `SkillLoadHarness.render_prompt()` API so the
  benchmark stops reaching into private underscore members.
- **Tier 3** — `schema_version="v1"` on `papers.json` and
  `SearchTrialResult`; `os.environ` → `contextvars` for concurrency safety;
  curated disease-context mapping (no-op for the current all-breast-cancer
  case pack); `recursion_limit_hit` telemetry (asymmetric survivor bias
  detection); OFF-arm `read_file("skills/...")` hardening; `has_pathways`
  GLMM covariate; `run_pilot.py` ↔ `run_full.py` deduplication;
  `json.dumps(allow_nan=False)`; troubleshooting section expansion;
  Latin-square model-swap optimization if swap overhead becomes a
  bottleneck.

## Troubleshooting

- **`ollama: model not found`** — ensure `ollama pull` completed for both
  `qwen3.5:122b` and `qwen3.5:35b`; check `ollama list`.
- **`papers_not_written` error row** — the SEARCHER finished its tool loop
  without writing `/papers.json`. Inspect the trial workspace for partial
  files; common cause is recursion limit (150) or a transient BioMCP
  timeout. Resume will retry automatically on next run.
- **R `error in glmer: ...`** — usually means the pilot sample is too
  sparse for the interaction term. The R script wraps GLMM fits in
  `tryCatch` and emits the error string into the JSON output instead of
  crashing.
- **`simr package not installed`** — `install.packages("simr")`. The
  power analysis block is skipped gracefully if absent.
- **Tests fail on `test_hardcoded_skill_block_matches_searcher_prompt`** —
  someone changed `src/agents/deep_interpreter/subagents/prompts.py:182-194`.
  Update `HARDCODED_SKILL_BLOCK` in `common.py` to match, or the
  benchmark's string-replace will silently no-op and leak the original
  MANDATORY block into both arms.

---

## `--mode` Flag (Rev 4)

The benchmark supports three experiment modes that differ in how the OFF arm
is isolated from the kwarg-activated production behavior. The mode is
selected via the `--mode` CLI flag (default `C`; env var `BENCHMARK_MODE`
acts as an override fallback for ad-hoc scripts).

| Mode | `BENCHMARK_APPENDIX` | Prompt strip | OFF-arm tool schema | Use case |
|---|---|:-:|:-:|---|
| `B` | `B_PINNED` — both arms see `enable_lr_pair_queries=True`, `coverage_weighted_sort=True` bullets | ❌ | Full schema | **Null control**: if this shows Δ > 3 pp on celltype, measurement is contaminated |
| `B_prime` | `BPRIME_C` — kwarg bullets removed | ✅ 4 strip targets | Full schema | **Prompt-level isolation**: OFF arm has no kwarg hints in prompt (but LLM can still discover them via tool schema) |
| `C` (default) | `BPRIME_C` | ✅ 4 strip targets | **Restricted** on OFF arm — hides `enable_lr_pair_queries` + `coverage_weighted_sort`, hardcodes both to `False` | **Tool-schema isolation**: OFF arm cannot discover kwargs from schema; wrapper forces `False` |

Every JSONL trial row carries a `benchmark_mode` audit field; `check_pilot_gates`
reads the mode to decide whether Gate Null (mode B only) applies.

**Invocation examples**:

```bash
# Mode B (null control) — kwargs pinned both arms
python docs/benchmarks/harness_x_model/run_pilot.py --mode B \
  --results-dir docs/benchmarks/harness_x_model/results/pilot_post_update_b \
  --workspace-root docs/benchmarks/harness_x_model/workspaces/pilot_post_update_b \
  --per-category 2 --repeats 1

# Mode B' (prompt-level strip, no schema isolation)
python docs/benchmarks/harness_x_model/run_pilot.py --mode B_prime ...

# Mode C (B' + tool-schema isolation — CURRENT DEFAULT)
python docs/benchmarks/harness_x_model/run_pilot.py --mode C ...
# OR: python docs/benchmarks/harness_x_model/run_pilot.py ...  # default C

# Env var fallback (no --mode flag; picks up BENCHMARK_MODE)
BENCHMARK_MODE=B_prime python docs/benchmarks/harness_x_model/run_pilot.py ...
```

Use separate `--results-dir` per mode (the convention is
`pilot_post_update_{b,b_prime,c}/`). Mixing modes in the same directory is
caught by the resume safety guards (see below) before any trial is written.

---

## Post-Update Measurement Caveats (ce4f79b and related commits)

As of 2026-04-17, production has been updated by four commits that shift the
reflection architecture. The re-pilot measures whether the skill's effect
still replicates under the new architecture.

- **SEARCHER reflection is now tool-internal** (`ce4f79b`). The pre-update
  SKILL.md mandated `think_tool` calls in Phase 3 for LLM-driven reflection
  on coverage gaps. Post-update, `search_literature_dynamic` drives the
  reflection loop internally based on `coverage_sufficient` checks against
  `target_gene_coverage` / `target_pathway_coverage` thresholds. The skill's
  Phase 3 guidance remains in prose form (reflection checklist, follow-up
  query strategy) but no longer triggers an LLM-level tool call. This is a
  **mechanism change** — if the re-pilot replicates the pre-update effect,
  the paper claim strengthens to "workflow guidance is architecture-independent".
- **BioMCP payload sanitization active** (`93fbc18`). Orthogonal defensive
  layer. Does not affect coverage measurement but may reject malformed
  strings earlier than before.
- **Gene-alias 5-minute TTL** (`93fbc18`). Transient BioMCP failures no
  longer poison `_GENE_ALIAS_CACHE` permanently. Improves reproducibility
  across trials when BioMCP has brief hiccups. Post-hoc audit via the
  `biomcp_error` field on each JSONL row.
- **`skill-load-harness` → `skill-activator` rename** (`c1c2580`). Module
  path, class name, AND the MANDATORY-block text all changed. The benchmark's
  `HARDCODED_SKILL_BLOCK` constant was updated to match; the
  `test_hardcoded_skill_block_matches_searcher_prompt` CI guard catches any
  future drift.

---

## P2.0 Diagnostic Probe (cheap pre-flight before the 12h re-pilot)

**Purpose**: catch catastrophic effect collapse (>70% loss vs pre-update
+16 pp baseline) in 30 minutes before committing to 12h of unattended
compute. Detection limit: the probe does NOT distinguish between
strengthened (+12..+22 pp) and nuanced (+5..+12 pp) outcomes.

**Protocol**:

```bash
python docs/benchmarks/harness_x_model/run_pilot.py \
  --mode B_prime \
  --results-dir docs/benchmarks/harness_x_model/results/diagnostic_probe \
  --workspace-root docs/benchmarks/harness_x_model/workspaces/diagnostic_probe \
  --per-category 0 --cases cci_full_01_EGF_RACK1 --repeats 1
# Runs 4 trials: strong_off, strong_on, weak_off, weak_on — 1 case.
```

**Manual inspection (~10 min)** of `results/diagnostic_probe/trial_*.jsonl`:

1. **Fan-out sanity**: `generated_queries` in each trial's `papers.json`
   should show deterministic singleton fan-out (one query per input gene)
   for both arms in mode B'. Asymmetric fan-out between ON/OFF is a flag.
2. **Celltype Δ**: compute `strong_on − strong_off` on `celltypes_coverage_pct`.
   If Δ ≥ +5 pp on the single case → effect channel is plausibly intact,
   **proceed** to P2.1 (OSF submission) and P2.2-P2.4 (full pilots).
3. **Iteration behavior**: inspect `iterations` in `papers.json`. If
   post-ce4f79b SEARCHER exits at iter 0 in all trials, the tool-internal
   reflection loop isn't engaging — mechanism investigation needed.

**Lifecycle note**: `diagnostic_probe/` is a one-shot workspace. Overwritten
on every re-run (not timestamped, not archived). Its JSONL is a go/no-go
gate artifact, not a measurement artifact.

**Decision rule**:

- Strong-model Δ ≥ +5 pp → **proceed** to P2.1.
- Strong-model Δ < +5 pp OR direction flip → **STOP**; pivot to mechanism
  investigation before burning 12h compute. Re-plan with the user.

---

## Resume Safety Guards (P0.8.5)

The 12h re-pilot is unattended. Two runtime guards abort fast if the
execution state is incoherent:

### Mode coherence (`check_mode_coherence`)

Runs at the start of `run_pilot.py`, `run_full.py`, and `run_trial.py`.
Compares the `--mode` CLI flag to the `benchmark_mode` field of the first
completed trial in the results directory. Mismatch → `SystemExit` with
recovery hints.

**Example failure mode**: user accidentally resumes a mode-B pilot with
`--mode C`:

```
Mode mismatch: existing trials in results/pilot_post_update_b used
benchmark_mode='B', but --mode='C' was passed. Mixing modes would corrupt
the pilot. Recovery: (a) pass --mode=B to resume, OR (b) use a different
--results-dir, OR (c) archive existing dir and start fresh.
```

### Cases-file hash coherence (`check_cases_coherence`)

Runs at the start of `run_pilot.py` and `run_full.py` only (not
`run_trial.py` — single-trial debug has an explicit `--trial-index`).
Compares `SHA-256(cases_file)` at resume time to the `cases_sha256` field
recorded on every JSONL row. Mismatch → `SystemExit`.

**Why this matters**: the deterministic schedule
`build_trial_schedule(cases, ..., seed=42)` produces a fixed
`trial_index → (case, condition, repeat)` mapping ONLY when the cases file
is byte-identical across runs. Any edit (even whitespace) shifts the
mapping silently. The guard prevents this class of silent data corruption.

### Backward compatibility with pre-P0.8 archives

Pre-P0.8 JSONL rows lack `benchmark_mode` and `cases_sha256`. Both guards
**warn and skip** rather than abort, so `analyze_pilot_workspaces.py` and
`load_trial_rows` can still read archived data (`pilot_reframe_b_attempt/`,
`pilot_reframe_b_prime/`, `pilot_reframe_c_preupdate/`). This is
transitional behavior; once the archives are retired (post-manuscript
acceptance), the warn branches can be removed.

### Guard recovery cheatsheet

| Failure | Immediate fix | Durable fix |
|---|---|---|
| Mode mismatch | `--mode <existing>` to resume | Verify the correct mode from the results-dir name convention |
| Cases-hash mismatch | `git checkout HEAD -- docs/benchmarks/cci_skill_ablation/cases/cci_full_cases.json` | Don't modify cases file mid-pilot; archive+new dir if edit was intentional |
| Legacy archive warn | (no action needed — warn is informational) | N/A — expected for pre-P0.8 data |

---

## Test Suite (regression guards)

After any change to `common.py`, `run_*.py`, `analyze_pilot_workspaces.py`,
or the R script, run:

```bash
pytest tests/benchmarks/test_harness_x_model.py -v
```

Target: **44+ passing** (12 core + 14 mode/schema + 9 resume guards +
1 drift guard + 5 gate tests + 3 bonus defensive). See the Rev 4
regression matrix in the plan for the full breakdown.
