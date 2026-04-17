# Session Summary — harness_x_model Tier 1 + Pilot + Post-Hoc

**Date**: 2026-04-15
**Scope**: REV5 Tier 1 patches, middleware fix (H4), pilot execution (48 trials), post-hoc analysis, architect verification.
**Related files**:
- Plan file: `/Users/jungj2/.claude/plans/happy-cuddling-brooks.md`
- Spec: [`REV5_PLAN.md`](REV5_PLAN.md)
- Findings: [`results/pilot_posthoc/FINDINGS.md`](results/pilot_posthoc/FINDINGS.md)

---

## Ralph completion verdict: ✅ APPROVED

Ralph persistence loop completed with architect verification (`oh-my-claudecode:architect`, STANDARD tier). All Tier 1 deliverables landed, pilot ran to completion, post-hoc analysis produced a clean recommendation, state cleaned up via `/oh-my-claudecode:cancel`.

## Artifacts written this session

| File | Purpose |
|---|---|
| `analyze_pilot_workspaces.py` | 48-workspace analyzer computing 22 metrics per trial (gene/celltype coverage, unique PMIDs, Jaccard, L-R co-occurrence, query diversity, latency, journal quality) |
| `results/pilot_posthoc/per_trial.csv` | 48 trials × 22 metrics raw table (R import ready) |
| `results/pilot_posthoc/cross_arm.json` | 48 cross-condition Jaccard / novelty deltas per case |
| `results/pilot_posthoc/summary.json` | Per-condition aggregated statistics |
| `results/pilot_posthoc/FINDINGS.md` | 11-section findings report + architect verification outcome + decision checkpoint |
| `results/pilot/pilot_summary.json` | Regenerated with latest-row-per-trial dedup |
| `results/pilot/pilot_gates.json` | Corrected REV5 §8 gate report (Gate A/C/variance FAIL due to saturation; Gate B PASS with 0% error rate) |
| `results/pilot/_runner.log` | Pilot runner stdout/stderr |
| `results/debug/strong_off_messages.json` | Diagnostic dump that identified the H4 middleware bug |
| `_debug_off_arm.py` | Single-trial diagnostic script used to root-cause papers_not_written |

Plus per-trial workspaces preserved at `workspaces/pilot/trial_*/` (48 directories with full papers.json payloads for any follow-up analysis).

## Core findings (architect verified)

### Tier 1 infrastructure validated

| Deliverable | Status | Evidence |
|---|---|---|
| Dual-endpoint coverage (T1) | ✅ | Both tag-on and tag-off computed per trial |
| BioMCP telemetry best-effort (T2) | ✅ | `biomcp_latency_ms`, `biomcp_error`, `biomcp_paper_count_raw` populated |
| 4-gate enforcement (T3) | ✅ | `pilot_gates.json` written; non-zero exit on failure |
| `run_full.py` stratification guard (T4) | ✅ | `--max-cases 12` raises `SystemExit`; `--per-category` supported |
| R analyzer rewrite (T5) | ✅ | Multi-line JSONL handling, `dplyr::bind_rows`, factor levels pinned, bootstrap CI, `simr::powerSim` |
| Option β model stickiness (T6) | ✅ | 132 model swaps over 360 trials (was 226 pre-fix) |
| F3 resume excludes error rows | ✅ | Failed trials retried, successful trials skipped |
| 6 regression test guards (T7) | ✅ | 11 unit tests passing |
| RUNBOOK minimal augmentation (T8) | ✅ | Prerequisites, workflow, gates, caveats, deferred items |
| REV5 PLAN §4 dual-endpoint clarification (T0) | ✅ | 1 paragraph added resolving §1↔§4 contradiction |

### H4 middleware fix (discovered during pilot)

Original Tier 1 plan deferred H4 (attach `WriteFileArgGuardMiddleware` to the benchmark's `create_react_agent`). The first pilot run revealed this was a **hard blocker**: 5/7 trials failed with `papers_not_written` because the OFF arm called `write_file(content=dict)` and Pydantic's schema validator rejected the dict before the `standalone_fs.write_file` body's `isinstance(content, dict)` fallback could run.

**Fix applied**: switched `common.py` from `langgraph.prebuilt.create_react_agent` to `langchain.agents.create_agent`, added `WriteFileArgGuardMiddleware` to the middleware list. The middleware coerces dict/list content to `json.dumps(...)` BEFORE Pydantic validation runs. Production DeepAgents has used this middleware all along — the benchmark was missing it.

**Verification**: re-run of the same failing trial with the fix completed in 177s (vs 673s + failure pre-fix), message count 17 (vs 151), `papers.json` + `search_context.json` both written.

**Pilot-wide**: full 48-trial pilot completed with **0 errors** (corrected from initial 9.43% false-positive caused by a `load_trial_rows` dedup bug — also fixed this session).

### The deeper problem: endpoint saturation

Every coverage-like metric has **zero between-condition variance**:

| Metric | strong_off | strong_on | weak_off | weak_on | Between-cond range |
|---|---|---|---|---|---|
| genes_coverage_pct | 100 ± 0 | 100 ± 0 | 100 ± 0 | 100 ± 0 | **0.0 pp** |
| celltypes_coverage_pct | 62.59 ± 17.52 | 62.59 ± 17.52 | 62.59 ± 17.52 | 62.59 ± 17.52 | **0.0 pp** |
| unique_pmids | 30 ± 0 | 30 ± 0 | 30 ± 0 | 30 ± 0 | **0.0** |
| lr_cooccurrence_count | 0.08 ± 0.29 | 0.08 ± 0.29 | 0.08 ± 0.29 | 0.08 ± 0.29 | **0.00** |
| iterations | 2 ± 0 | 2 ± 0 | 2 ± 0 | 2 ± 0 | **0** |
| n_generated_queries | 9.42 ± 0.67 | 9.42 ± 0.67 | 9.42 ± 0.67 | 9.42 ± 0.67 | **0.00** |
| journal_quality_mean | 0.5 ± 0 | 0.5 ± 0 | 0.5 ± 0 | 0.5 ± 0 | **0.0** |

Only **latency_s** shows between-condition variance, and even that is confounded by Ollama model-swap reload cost on the strong model (trial 7 outlier: strong_on=599s vs strong_off=57s because trial 7 was the first strong-model trial after a weak block).

### Root cause

1. **Case pack**: all 30 cases have exactly 2 genes (ligand + receptor). 60% coverage = 2/2 = 100%, trivially achievable.
2. **Production fan-out**: `_build_deterministic_gene_queries(chunk_size=1)` at `literature.py:2760-2763` unconditionally fires one BioMCP query per gene, regardless of skill state. The LLM-generated queries are exact-set-deduped against these deterministic chunks, so the skill's query strategy is **decorative** — the base retrieval is identical across arms.
3. **PubMed semantics**: for CCI L-R pairs, PubMed returns papers about each gene individually, not papers about the specific interaction. 11/12 cases have 0 papers mentioning both ligand AND receptor in the same abstract.
4. **Retrieval ceiling**: `max_results=30` caps every trial at 30 papers regardless of effort.
5. **Jaccard overlap 0.81–0.89**: 88% of retrieved papers are identical across skill ON/OFF within the same model.

### Pilot proved what works AND what can't be measured

- ✅ Infrastructure: all Tier 1 patches, the H4 middleware fix, the 4-gate runner, the R analyzer — all validated.
- ❌ Endpoint: `coverage_pass` is structurally saturated given this case pack + production code path. GLMM interaction effect is mechanically undefined.
- ⚠ Only signal: latency shows +36s skill overhead on weak model (paired median, 8/12 cases positive) and noise on strong model.

## Three paths forward

### Path A — Option α (case pack augmentation) with dry-run gate

Expand each case's gene set from 2 to 15-30 by including:
- L-R pair (current)
- STRING/KEGG hub genes (orthogonal to `liana_moran_r` to avoid circular provenance — architect flag)
- Pathway members for the L-R pair's canonical pathway
- Marker genes for source/target celltypes

**Hardening**: raise `target_gene_coverage` from 0.6 to 0.9 in the pass threshold (pure endpoint-side change, preserves production retrieval semantics).

**Mandatory dry-run gate**: run a single trial with one hand-augmented case before committing to the full pipeline (~30 min diagnostic vs ~1 day of work). Decision rule:
- Coverage ≤85% → proceed with Option α
- Coverage ≥95% → abandon, pivot to Path B
- Coverage 85–95% → run 4-case diagnostic to refine

**Cost**: 30 min dry-run + ~1 day augmentation if green-lit.

### Path B — Option γ (latency composite endpoint)

Switch primary endpoint to `coverage_pass AND latency_s ≤ threshold(model)`. Accept that the claim narrows from "the skill improves retrieval quality" to "the skill changes latency profile". Re-run the existing pilot analysis with the new endpoint; no new Ollama work needed.

**Cost**: ~2 h to swap the endpoint definition + regenerate gates + rewrite Methods caveats.

**Risk**: reviewer asks "does the skill help retrieval?" and the answer is "we can't measure it on this benchmark". Acceptable for preprint, probably not for Nature Methods.

### Path C — Option β (citation-accuracy judge benchmark)

Replace the retrieval coverage endpoint entirely with a citation-accuracy task: given an analysis result and a target interpretation, did the retrieved paper set contain ≥1 PMID that actually supports the claim? Ground truth hand-labeled or judged by GPT-4 with chain-of-thought validation.

**Cost**: ~2 weeks. Out of scope for the current session.

**Recommendation**: **Path A** (architect endorsed) with the dry-run gate as a mandatory checkpoint. Path B as fallback if dry-run fails. Path C as a separate research track if Paths A/B don't produce a publishable result.

## Architect verification outcome

`oh-my-claudecode:architect` reviewed the post-hoc analysis against the raw per_trial.csv, summary.json, cross_arm.json, pilot_gates.json, and the source `literature.py` code paths. Verdict: **APPROVED with two numerical corrections (applied)**:

1. ✅ FINDINGS §3: "9 of 12 cases" → corrected to **8 of 12** (recomputed from raw CSV)
2. ✅ FINDINGS §3: stdev framing — clarified that the `+160.9s` stdev is the paired-per-case stdev, while `summary.json strong_on latency_s.stdev=144.82` is the per-condition stdev (legitimately different statistics)

All other claims verified:
- Saturation is mathematically dispositive — 48 trials with zero between-condition variance cannot be rescued by more repeats
- `celltypes_coverage_pct` per-case range = 0.0 across all 12 cases (confirmed by recomputation)
- Trial 7 latency outlier confirmed as a genuine Ollama weak→strong swap artifact via schedule replay
- Jaccard 0.81–0.89 verified; interpretation sound
- L-R co-occurrence word-boundary regex is correct (biological reality, not a regex bug)
- `_build_deterministic_gene_queries` is ungated by any benchmark-controllable flag (confirmed via `literature.py:2760-2763`)
- H4 middleware fix has no asymmetric measurement bias (pass-through for string content, symmetric dict coercion on both arms)
- No measurement bugs in the analyzer

**Additional architect insights applied to the recommendation**:
- Option α has higher saturation risk than FINDINGS initially implied — 15 genes × aggressive alias expansion + `max_results=30` may still produce ~80% coverage. Hardening via `target_gene_coverage=0.9` threshold is needed.
- Circular provenance leak if hub genes come from the same `liana_moran_r` table that ranked the original L-R pair. Mitigation: STRING/KEGG orthogonal source.
- Latency analysis must exclude first-trial-after-swap or include a `post_swap` covariate in the GLMM.
- 30-min dry-run gate is mandatory before committing ~1 day to the full augmentation pipeline.

## Ralph termination checklist (all green)

- ✅ Original task (post-hoc analysis script + findings + architect verification) fully completed
- ✅ Zero pending or in_progress TODO items (tasks 9, 10, 11, 12 all completed)
- ✅ Fresh test run: **11 passed** (`pytest tests/benchmarks/test_harness_x_model.py`)
- ✅ Fresh static check: `analyze_pilot_workspaces.py`, `common.py`, `run_pilot.py`, `run_full.py`, `harness_x_model_glmm.R` all parse cleanly
- ✅ Architect verification passed (STANDARD tier minimum, via `oh-my-claudecode:architect`)
- ✅ `/oh-my-claudecode:cancel` executed — `ralph-state.json` + linked `ultrawork-state.json` cleaned from `.omc/state/sessions/19c39a13-.../`

## Next user decision

Choose one:
- **Path A** (recommended, architect endorsed): Start the 30-min Option α dry-run diagnostic on a hand-augmented case
- **Path B** (fallback): Swap endpoint to latency composite (~2 h work)
- **Path C** (research): Pivot to citation-accuracy judge benchmark (~2 weeks)

Regardless of which path, all Tier-1 patches, the H4 middleware fix, the runner, the 4-gate enforcer, the R analyzer, the RUNBOOK, the 6 regression tests, and the post-hoc analyzer are shippable as-is.
