# Plan: harness_x_model Rev 5 — Option A only (production SEARCHER end-to-end)

## 1. Context

Rev 4 of `PLAN.md` (Option B+: outer-LLM extracts PubMed query parameters as JSON, passes them via `query_cache=...` to bypass the inner LLM) drew 24 findings across three independent reviews. Two were CRITICAL measurement-validity issues that no amount of plan-level patching rescues:

1. **Tag-only credit inflation**. `_calculate_coverage(use_retrieval_tags=True)` at `literature.py:1771-1894` credits any gene that appears in `paper.matched_via_query.genes` regardless of whether the paper's abstract actually mentions that gene. The harness-ON arm, instructed by the inlined SKILL.md to emit more gene-bearing queries, mechanically scores higher regardless of retrieved content — re-measuring the existing skill-activation F1 benchmark with added latency.
2. **Pathway-vs-gene-singleton fan-out asymmetry**. Under `query_cache` replay the LLM path skips `_build_deterministic_gene_queries(chunk_size=1)` (~30 queries), while production fires it unconditionally; the measured harness effect in B+ is on top of a pathway-only baseline, while production measures it on top of a pathway + gene-singleton baseline. Not directly comparable.

Neither is a plan-editing defect — they are structural consequences of running a parameter-extraction proxy instead of the real SEARCHER. The fix is to delete the proxy.

**Option A (this plan)**: run the production SEARCHER subagent end-to-end. Skill ON/OFF is toggled by including or excluding `biomedical-literature-search` from `DeepInterpreterConfig.agent_skill_names`. Everything else is byte-identical to production: `enable_lr_pair_queries=True`, deterministic gene singletons fire, hybrid pathway fan-out fires, alias pre-warm fires, retrieval tags are stamped, `_GENE_ALIAS_CACHE` is module-level state (shared within a run — production reality). Measurement is whatever coverage the production pipeline reports. No JSON parse path, no query_cache, no inlined SKILL.md, no tag-aware/tag-unaware split.

One-sentence thesis: **turning on `biomedical-literature-search` in the production SEARCHER subagent, does literature-search coverage improve, and is the effect moderated by model strength (qwen3.5:122b vs 35b)?**

Group A (`.gitignore` unignore for `docs/benchmarks/harness_x_model/`) is already executed in the source session. The archived Option-B+ design with all 24 findings lives at `REV5_PLAN_OPTION_B_ARCHIVED.md`; consult it if a reviewer asks why we switched.

## 2. Experimental Design

| Cell | Label | Model | `biomedical-literature-search` skill |
|------|-------|-------|--------------------------------------|
| A | `strong_off` | qwen3.5:122b | removed from `agent_skill_names` |
| B | `strong_on`  | qwen3.5:122b | present in `agent_skill_names`       |
| C | `weak_off`   | qwen3.5:35b  | removed                              |
| D | `weak_on`    | qwen3.5:35b  | present                              |

Both arms keep `pubmed-eutils-search` and `html-report-generator` in the tuple so only the ONE skill under test varies. 30 L-R-pair cases from `cases/cci_full_cases.json` (symlinked from `../cci_skill_ablation/`, 6 strata × 5 pairs) × 4 conditions × 3 repeats = **360 trials**. Pilot is **48 trials** (12 cases × 4 × 1, 2 cases per stratum) to detect ceiling saturation with usable statistical signal at ~4h turnaround. Full-run wall-clock budget ~18-30h at ~3-5 min per Option A trial. Temperature 0.3 for LLM variance across repeats. Block randomization **Option β** (per-case adjacency, model+harness randomized within case) reduces Ollama model swaps from 360 to 30 and guarantees that any infrastructure hiccup hits all four conditions of a case uniformly.

## 3. Trial Runner

Instantiate SEARCHER alone — not the full Deep Interpreter pipeline — via `langgraph.prebuilt.create_react_agent`. `get_subagents()` in `src/agents/deep_interpreter/subagents/configs.py` returns plain dict configs whose `system_prompt`, `tools`, and `middleware` fields are directly consumable. Pre-seed a minimal in-memory virtual filesystem with `/data_path.txt`, `/targets.json`, and `/search_context.json` so the SEARCHER's Phase 1 can run without the PLANNER upstream.

```python
from langgraph.prebuilt import create_react_agent
from src.agents.deep_interpreter.agent import DeepInterpreterConfig, _build_skill_registry, _resolve_skills_dir
from src.agents.deep_interpreter.subagents.configs import get_subagents

def build_searcher_for_trial(*, llm, skill_on: bool, data_dir: str):
    skill_names = ("pubmed-eutils-search", "html-report-generator")
    if skill_on:
        skill_names = ("biomedical-literature-search",) + skill_names
    cfg = DeepInterpreterConfig(data_dir=data_dir, agent_skill_names=skill_names)
    registry = _build_skill_registry(cfg)
    sources  = [str(_resolve_skills_dir(cfg)) + "/"]
    subs = get_subagents(skills_sources=sources, skill_registry=registry)
    s = next(x for x in subs if x["name"] == "searcher")
    return create_react_agent(llm, tools=s["tools"], prompt=s["system_prompt"],
                              middleware=s.get("middleware", []))
```

Invoke per trial with the same user message production SEARCHER receives from the orchestrator (`"Search literature for the targets in /targets.json and write /papers.json"`), let the agent run its tool loop until it writes `/papers.json`, then read the file and call `_calculate_coverage` in-process to extract metrics. No `query_cache`, no `parse_with_retry`, no inlined skill. `max_results` stays at the `search_literature_dynamic` default — matching production SEARCHER (`subagents/prompts.py:254-263` does not pass `max_results`, so neither does the benchmark).

## 4. Data Model

```python
@dataclass
class SearchTrialResult:
    case_id: str; condition: str; model: str; skill_on: bool
    repeat: int; trial_index: int; timestamp_utc: str
    total_papers: int = 0
    genes_coverage_pct: float = 0.0
    pathways_coverage_pct: float | None = None   # None when case.pathways empty
    coverage_pass: bool = False                    # gene ≥ 60% AND (pathway ≥ 50% OR pathways empty)
    latency_s: float = 0.0
    biomcp_latency_ms: float = 0.0
    biomcp_error: str | None = None
    biomcp_paper_count_raw: int = 0
    error: str | None = None
```

No tag-provenance fields, no LLM-attribution split, no `candidate_pool_size`, no `alias_prewarm_latency_ms`. The production coverage IS the measurement.

## 5. Statistical Analysis

- **Primary**: `glmer(coverage_pass ~ skill_on * model_strength + (1|case_id), family=binomial)` via `lme4`. LRT vs `~ skill_on + model_strength` for the interaction.
- **Secondary**: `lmer(genes_coverage_pct ~ skill_on * model_strength + (1|case_id))` — the continuous endpoint.
- **Simple effects** (if interaction significant): `emmeans::emmeans` with pairwise contrasts within each model strength; report Cohen's d.
- **Bootstrap CI**: case-level resampling, 10K iterations, pattern from `compare_expanded.py:365-540`.
- **Pilot power analysis**: `simr::powerSim(fit_pilot, fixed("skill_on:model_strength", "lrt"), nsim=500)`. If `N_required > 360` from pilot effect sizes: (a) abandon interaction claim, report main effects only; (b) raise repeats to 5 (600 trials, ~30-50h); (c) report null with explicit `N_required` framing.

## 6. Reused Infrastructure (from Rev 3, preserved verbatim where still valid)

- **Block randomization Option β**: `build_trial_schedule(cases, conditions, repeats, seed=42)` — per-case adjacency, conditions shuffled within case, from PLAN.md §3.5.
- **Checkpoint/resume**: file-per-trial JSONL in `results/{pilot|full}/`; restart skips completed `trial_index` tuples.
- **Dependency health**: log `biomcp_latency_ms`, `biomcp_error`, `biomcp_paper_count_raw` each trial.
- **BioMCP outage rule**: exclude trials where `biomcp_paper_count_raw == 0 AND biomcp_latency_ms > 30s`; report excluded count in the diagnostics supplement.
- **Case sourcing**: symlink `cases/cci_full_cases.json → ../cci_skill_ablation/cases/cci_full_cases.json` (same dataset as the CCI ablation benchmark).

## 7. Risks (Option A specific)

- **BioMCP / PubMed downtime** during the full run — exclude by outage rule, re-run excluded cases in a patch-up pass.
- **Ollama VRAM**: 122b + 35b total ~110 GB; A100 80 GB insufficient → accept ~30s reload per model swap; Option β bounds swaps to 30 (~15 min overhead).
- **Temperature 0.3 too low for repeat variance** — pilot checks the std-dev of `genes_coverage_pct` across the three repeats of a case; if <2% mean absolute difference, raise to 0.5 and re-run pilot.
- **Empty pathways**: 19/30 cases have empty `pathway_associations`, so `coverage_pass` degrades to gene-only there. Documented, not a confound — identical in all four arms.
- **Module-level `_GENE_ALIAS_CACHE` shared across trials**: this is production behavior, not a benchmark artifact. Trials 2-4 within a case see warm cache; trial 1 of each case measures cold start. Under Option β randomization every condition gets a proportional share of cold starts across the 30-case span.
- **Ceiling effect on `strong_on`**: if production saturates real-paper coverage, the interaction effect collapses. Screened in pilot Gate A below.

## 8. Pilot Protocol (48 trials, mandatory before committing to 360)

Run 12 cases × 4 conditions × 1 repeat, then:

1. **Gate A — saturation**: if `genes_coverage_pct ≥ 95%` median in BOTH `strong_on` and `strong_off`, the skill-effect is unmeasurable on the current endpoint; switch the endpoint to retrieval diversity (`len(unique_pmids)`) or novelty (`len(pmids ∉ skill_off_pmids)`), or narrow `coverage_pass` to ≥ 80% / pathway ≥ 70%.
2. **Gate B — dependency health**: `biomcp_error` rate < 5% across the 48 trials; `biomcp_latency_ms` median < 10 min per trial.
3. **Gate C — distributional check**: plot `genes_coverage_pct` histogram per cell; if clustered at ≤3 discrete values, the LMM secondary is invalid — drop to GLMM-only.
4. **Power analysis**: fit the GLMM on the 48 pilot trials, run `simr::powerSim` with `nsim=500`; apply the §5 decision rule on `N_required`.
5. **Variance check**: per-case std-dev of `genes_coverage_pct` across 3 conceptual repeats (extrapolated from the repeat=1 pilot via within-case between-condition variance); if < 2 percentage points, raise temperature to 0.5 for full run.

If all four gates pass, proceed to the 360-trial full run. Otherwise, apply the gate-specific remediation and re-pilot.

## 9. Implementation Sequence

1. Read `docs/benchmarks/skills/benchmark_skill_harness.py:739-800` to understand `_run_tool_loop`'s pattern; **do not extend it** — write a new `build_searcher_for_trial()` using `create_react_agent` instead (per §3).
2. Write `scripts/benchmarks/harness_x_model/run_trial.py` — single-trial async runner that builds the searcher, invokes, captures `/papers.json` + `/search_context.json` + BioMCP telemetry from the virtual FS, and emits one `SearchTrialResult`.
3. Reuse `build_trial_schedule` from PLAN.md §3.5 verbatim. Add a seeded JSONL checkpoint pattern from `scripts/benchmarks/benchmark_cci_core.py:986-999`.
4. Write `scripts/benchmarks/harness_x_model/run_pilot.py` — 48 trials, one JSONL per trial under `results/pilot/`, aggregate into `pilot_summary.json`.
5. Run pilot. Verify the four gates in §8. Record the power-analysis `N_required`.
6. Write `scripts/benchmarks/harness_x_model/run_full.py` (thin wrapper around the pilot script with `repeats=3`, `cases=30`). Run full. Expected ~18-30h.
7. Write `analysis/harness_x_model_glmm.R` implementing §5 (primary GLMM + LRT, secondary LMM, bootstrap CI, simple-effects if interaction significant).
8. Generate 2-panel figure: (A) interaction plot (model strength × skill_on, coverage_pass rate with SE), (B) violin+jitter of `genes_coverage_pct` per condition. Style from `s_figure_table3_results.R` (firebrick3 for ON, gray60 for OFF, theme_bw, patchwork).
9. Run `python -m pytest tests/evaluation` and the existing CCI ablation regression suite to confirm no measurement drift in shared helpers.
