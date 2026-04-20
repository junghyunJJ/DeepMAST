# Pilot Post-Hoc Findings

**Date**: 2026-04-15
**Pilot run**: 48 trials (12 cases × 4 conditions × 1 repeat), full completion, 0 errors after middleware fix.
**Analysis tool**: `docs/benchmarks/harness_x_model/analyze_pilot_workspaces.py`

## TL;DR

The benchmark as designed cannot measure a skill × model effect on literature-search quality. Every candidate coverage-like metric is either saturated at the ceiling (100%) or determined entirely by case identity, with 0 between-condition variance. The only signal with non-trivial between-condition variance is **latency**, which behaves as a consistent ~36 s skill overhead on the weak model but is dominated by Ollama model-swap confounds on the strong model. No usable primary endpoint for a GLMM exists in the current pilot data. The benchmark needs one of three structural changes before a full run can be defended. The **REV5 Tier 1 patches and the H4 middleware fix are all validated**; the blocker is the endpoint, not the infrastructure.

## 1. What the pilot proved works

| Tier 1 deliverable | Status | Evidence |
|---|---|---|
| Middleware fix (H4) | ✅ | 48/48 trials completed with 0 `papers_not_written`, down from 5/7 failures pre-fix |
| Option β model-stickiness | ✅ | 132 model swaps for 360 projected trials (<150 threshold) |
| 4-gate enforcement | ✅ | `pilot_gates.json` written, non-zero exit triggered, messages shaped correctly |
| BioMCP telemetry (best effort) | ✅ | Gate B PASS: 0% error rate, 117 s median latency |
| Dual coverage endpoint | ✅ | `coverage_pass_tagoff` captured; tag-off mean ~95.8% vs tag-on 100% (small delta, not informative — saturation applies to both) |
| R analyzer rewrite | ✅ | Unit tests pass, parses dedup'd rows |
| `load_trial_rows` dedup fix | ✅ | Corrected Gate B false-positive 9.43% error rate to actual 0% |

## 2. The core finding: total saturation across every content endpoint

| Metric | strong_off | strong_on | weak_off | weak_on | Between-cond range |
|---|---|---|---|---|---|
| genes_coverage_pct | 100 ± 0 | 100 ± 0 | 100 ± 0 | 100 ± 0 | **0.0 pp** |
| celltypes_coverage_pct | 62.59 ± 17.52 | 62.59 ± 17.52 | 62.59 ± 17.52 | 62.59 ± 17.52 | **0.0 pp** |
| unique_pmids | 30 ± 0 | 30 ± 0 | 30 ± 0 | 30 ± 0 | **0.0** |
| lr_cooccurrence_count | 0.08 ± 0.29 | 0.08 ± 0.29 | 0.08 ± 0.29 | 0.08 ± 0.29 | **0.00** |
| lr_title_cooccurrence | 0 | 0 | 0 | 0 | **0** |
| iterations | 2 ± 0 | 2 ± 0 | 2 ± 0 | 2 ± 0 | **0** |
| n_generated_queries | 9.42 ± 0.67 | 9.42 ± 0.67 | 9.42 ± 0.67 | 9.42 ± 0.67 | **0.00** |
| journal_quality_mean | 0.5 ± 0 | 0.5 ± 0 | 0.5 ± 0 | 0.5 ± 0 | **0.0** |

Per-case cross-condition ranges for `celltypes_coverage_pct` are **0.0 pp in all 12 cases**. The 4 conditions produce identical celltype coverage within a case, and identical means across cases. This rules out celltype coverage as an alternative primary endpoint.

`journal_quality_mean` is 0.5 for all 48 trials because every paper falls back to the default `_SJR_DEFAULT_SCORE = 0.5` (the journal name is unparsed/missing in the BioMCP response). Not an endpoint candidate.

`lr_cooccurrence_count` is 0 in 11/12 cases and 1 in the same 1 case across all 4 conditions: PubMed retrieval for CCI L-R pairs finds papers about each gene individually, not papers that discuss the interaction. This is a real biological property of the literature, not a bug in the benchmark — but it means "L-R specificity" cannot be used as an endpoint on this case pack either.

## 3. The one signal: latency, but it's confounded

Variance ranking sorts `latency_s` first with a between-condition range / within-condition stdev ratio of **0.753** (all other metrics are 0). Per-case paired analysis:

**Strong model (qwen3.5:122b):**
```
mean(skill_on − skill_off) = +45.5 s
median                      = +0.1 s
stdev                       = 160.9 s
```
Dominated by one outlier (`cci_full_12_COL1A2_ITGA1 strong_on = 599 s, strong_off = 57 s, Δ = +542 s`). Removing the outlier collapses the mean toward zero. The trial order shows `trial_7 (strong_on)` ran immediately after a `weak → strong` model swap on Ollama, so ~30 s of the 599 s is model reload cost, but even subtracting that leaves a +510 s outlier. **Latency on the strong model does not reliably distinguish skill arms** in a 12-case pilot.

**Weak model (qwen3.5:35b):**
```
mean(paired skill_on − skill_off) = +33.7 s
median                            = +36.1 s
stdev(paired diff)                =  61.7 s
```
**8 of 12** cases show positive skill effect (skill_on slower). The 4 negative-delta cases are `cci_full_17_COL1A1_CD93 (-42.8 s)`, `cci_full_22_BAMBI_ACVR2B (-28.6 s)`, `cci_full_07_LAMA2_ITGA6 (-27.3 s)`, `cci_full_02_ANOS1_FGFR1 (-57.0 s)`. This is still a consistent signal: the SKILL.md reflection and multi-phase workflow adds ~36 s on the weak model before tools complete. **But it is a negative signal** — it says "skill makes things slower", not "skill improves retrieval quality". The stdev above is the **paired per-case** stdev; the per-condition stdev reported by `summary.json` (`weak_on: 52.8`, `weak_off: 36.5`) is a different statistic (variance around each condition's mean, not around the paired delta).

## 4. Retrieval is near-deterministic given the case

Cross-arm Jaccard similarity on retrieved PMIDs:

| comparison | mean Jaccard | mean novelty per side |
|---|---|---|
| strong_on vs strong_off | 0.874 | 2.25 papers |
| weak_on vs weak_off | 0.886 | 1.92 papers |
| strong_off vs weak_off | 0.878 | 2.08 papers |
| strong_on vs weak_on | 0.817 | 3.50 papers |

88% of the retrieved papers are the **same** across skill ON vs OFF within the same model. Model strength is the larger driver (strong_on vs weak_on shows 82% overlap vs 88% for same-model comparisons), but even the model effect is small — out of 30 papers, only 3.5 on average are unique to each model.

Query content: per-case hash comparison across 4 conditions shows every condition emits **different query text** (all 4 hashes distinct, query COUNT per case identical — 9, 10, or 11 depending on case). Conclusion: the LLM is doing different work per condition, but PubMed retrieval on these 2-gene cases is robust enough that the final paper set is nearly identical regardless of query phrasing. The skill ON arm's advantage in query strategy does not translate to a measurable advantage in the retrieved paper set.

## 5. Why saturation happens

1. **Case pack property**: all 30 cases have exactly 2 genes (ligand + receptor). A gene coverage target of 60% requires matching 2/2 = 100%, achievable by any search that mentions either gene in an abstract. BioMCP auto-expands gene aliases and returns 30 papers easily.
2. **Ceiling enforcement**: `search_literature_dynamic` is configured with `max_results=30` in production, so every successful search returns exactly 30 papers. `total_papers` cannot exceed 30 regardless of workflow quality.
3. **Production fan-out**: `_build_deterministic_gene_queries` fires one singleton query per gene unconditionally (REV5 §1), so the baseline retrieval is identical across conditions — the LLM-generated query text layers on top, but doesn't displace the deterministic retrieval.
4. **PubMed semantics**: For CCI L-R pairs, PubMed does not return papers that discuss the specific interaction. It returns papers about each gene's role in relevant disease contexts. The "interaction-specific" papers the benchmark would want to reward do not exist in the retrieval window.
5. **Default SJR**: `journal_quality = 0.5` for all papers means sort-by-quality collapses to original order; no quality signal.

## 6. What this means for the full run

A full 360-trial run on the current benchmark configuration would produce:
- GLMM primary endpoint (`coverage_pass`): zero variance, interaction LRT p = 1.0, model uninterpretable.
- GLMM sensitivity endpoint (`coverage_pass_tagoff`): near-zero variance, same result.
- LMM secondary endpoint (`genes_coverage_pct`): no informative between-condition effect.
- Bootstrap CI: degenerate.
- Power simulation: meaningless (can't detect an effect that doesn't exist on the endpoint).

**The full run should not be executed against the current primary endpoint.** REV5 §8 Gate A was designed to catch exactly this, and it did.

## 7. Three structural fixes (ranked)

### Option α — case pack augmentation (highest retrieval-quality power, medium work)

Expand each case's gene set to include:
- The L-R pair (current, 2 genes)
- Top hub neighbors from the CCI analysis's gene graph (e.g., from `liana_moran_r` table, top 10 co-ranked genes)
- Members of the relevant KEGG/Reactome pathway (5–15 per pathway) via a pre-extracted mapping
- Marker genes for each celltype in `ligand_cell_types` + `receptor_cell_types`

Result: 15–30 genes per case. 60% gene coverage becomes a non-trivial target. Coverage variance between conditions can exceed the Gate A 95% saturation threshold.

Cost: ~1 day to build the augmentation pipeline, produces a new `cci_full_cases_augmented.json` that the existing `normalize_case` can ingest with no code changes.

Risk: the augmented gene set may still be easy for the production fan-out to hit if BioMCP's alias expansion is aggressive. Would need a dry-run of one case to confirm variance.

### Option β — switch benchmark task to citation accuracy (highest alignment with production, high work)

Instead of "retrieve supporting papers", measure:
- Given an analysis result and a target interpretation, did the retrieved paper set contain **≥1 PMID that actually supports the claim**?
- Ground truth: hand-labeled by a domain expert (or GPT-4 with chain-of-thought validation)
- Endpoint: binary `citation_support_pass` per trial.

This aligns with the actual downstream use of SEARCHER (feeding INTERPRETER which cites PMIDs). The skill's effect on citation quality — if real — would show up as a sensitivity gain on this endpoint.

Cost: ~2 weeks to design the ground truth, validate it, integrate a judge. Probably needs a separate agent.

### Option γ — accept the benchmark is an efficiency measurement (lowest effort, narrowest claim)

Switch the primary endpoint to a latency-based composite:
- Primary: `coverage_pass AND latency_s ≤ efficiency_threshold(model_strength)`
- Threshold chosen per model to reflect realistic production budgets
- Skill-ON is expected to cost latency but justify it with auxiliary quality metrics from paper content

This is the smallest change and matches what the data already supports. The claim narrows from "skill improves retrieval" to "skill changes latency profile". The Methods section becomes honest but limited.

Cost: ~2 hours to swap the endpoint in `common.py`, regenerate pilot_gates.json on existing data, document the claim in RUNBOOK.

Risk: the paper reviewer will ask "but does the skill help retrieval quality?" and the answer is "we can't measure it on this benchmark". Acceptable for a bioRxiv preprint or a methods-development paper, probably not for Nature Methods.

## 8. Recommendation

Run **Option α (case pack augmentation)** as the next patch. Reasoning:

1. Preserves the REV5 design goal of "measure whether the skill helps literature search" — the thesis the user set out to test.
2. Preserves the existing harness infrastructure — all Tier 1 fixes land unchanged.
3. Bounded effort (~1 day for the augmentation script + dry run).
4. The augmentation is testable in isolation: run a single trial with the augmented gene set and confirm coverage drops below 100%.
5. Option γ is a fallback if Option α still saturates.

A small pilot (4 cases × 4 conditions × 1 repeat = 16 trials, ~1 h) should be run on the augmented case pack to verify the coverage distribution is non-degenerate before committing to the full 48-trial pilot.

## 9. Artifacts written

- `docs/benchmarks/harness_x_model/results/pilot_posthoc/per_trial.csv` — 48 trials × 22 metrics
- `docs/benchmarks/harness_x_model/results/pilot_posthoc/cross_arm.json` — 48 cross-condition comparisons
- `docs/benchmarks/harness_x_model/results/pilot_posthoc/summary.json` — per-condition aggregated stats
- `docs/benchmarks/harness_x_model/results/pilot_posthoc/FINDINGS.md` — this document
- `docs/benchmarks/harness_x_model/results/pilot/pilot_gates.json` — corrected REV5 §8 gate report

Pilot workspaces (`docs/benchmarks/harness_x_model/workspaces/pilot/trial_*/`) are preserved for any follow-up analysis; they contain the full retrieved paper payloads and generated query logs.

## 10. Architect verification (2026-04-15)

Independent review by `oh-my-claudecode:architect` confirmed every numerical claim with two corrections (applied above: 9/12 → 8/12 weak-model positive deltas; stdev framing clarified as paired-per-case vs per-condition). The architect greenlit Option α but flagged three residual risks that must be addressed **before** building the augmentation pipeline:

1. **Saturation can persist at 60% threshold** even with 15–30 genes per case because `_build_deterministic_gene_queries(chunk_size=1)` at `literature.py:2760-2763` unconditionally fires one BioMCP call per gene, and BioMCP's alias pre-warm at `literature.py:2587-2614` is aggressive. Coverage could still hit 80–95% on the augmented pack.

2. **Circular provenance leak**: if hub genes are sourced from the same `liana_moran_r` table used to rank the original L-R pair, the "augmented" gene set is trivially satisfied because the L-R pair is in the top of that table by construction. **Mitigation**: pull hub genes from an orthogonal source (STRING physical-interaction neighbors, KEGG/Reactome pathway membership, or top differentially expressed genes in the contextual celltype) rather than from the CCI analysis itself.

3. **Latency confound from Ollama swaps**: the measured Option β schedule produces 14 swaps in the 48-trial pilot and ~132 swaps in the 360-trial full run. The first trial after each swap carries ~30 s of VRAM reload plus occasional paging pathology (trial 7 in this pilot: 599 s vs twin 57 s). Any latency-based analysis must **exclude the first trial after each model swap** or include a `post_swap` covariate in the GLMM.

### Refined recommendation: dry-run gate before committing

Before building the full augmentation pipeline (~1 day), run a **single-trial Option-α dry run** (~30 min):

1. Hand-augment `cci_full_17_COL1A1_CD93` with 15 genes drawn from STRING or KEGG (not from `liana_moran_r`).
2. Run `run_trial.py --case-id ... --condition strong_on` with `target_gene_coverage=0.9` (not 0.6) as the pass threshold.
3. Read the resulting `papers.json.coverage.genes_coverage_pct`:
   - **≤ 85%** → Option α is viable. Build the full augmentation pipeline.
   - **≥ 95%** → Option α still saturates at the harder threshold. **Abandon Option α** and pivot to **Option γ (latency composite)** as the primary endpoint, accepting the narrower claim.
   - **85–95%** → borderline. Run 4 cases and check variance before deciding.

This 30-min diagnostic prevents the risk of committing 1+ day of work to an augmentation that still saturates. REV5 §8 Gate A discipline applies to benchmark redesigns too.

### Hardening options (orthogonal to case-pack augmentation)

The architect suggested three hardening patches that would reduce saturation risk independent of the case pack:

| Patch | Change | Pro | Con |
|---|---|---|---|
| Lower ceiling | `max_results=10` (down from 30) | Tighter retrieval window → lower gene-hit probability | Fewer papers to cite; diverges from production |
| Raise threshold | `target_gene_coverage=0.9` (from 0.6) in `coverage_pass` definition | Harder bar, pure endpoint-side change | Same retrieval, just stricter grading |
| Disable fan-out | `enable_lr_pair_queries=False` | Kills the deterministic saturation floor | **Diverges from production** — violates REV5 "byte-identical" goal |

The middle option (raise threshold to 0.9) is the cleanest because it keeps production retrieval semantics intact and only shifts the pass/fail criterion. It should be combined with Option α so the augmented cases are graded against a non-trivial bar.

## 11. Decision checkpoint

The pilot + post-hoc analysis + architect verification have produced a clean set of findings. The path forward requires a user decision between:

- **Path A**: Build Option α (case pack augmentation) + threshold tightening. ~30 min diagnostic dry-run, then ~1 day of augmentation work if the diagnostic passes. Preserves the REV5 "does the skill improve retrieval" thesis.
- **Path B**: Accept Option γ (latency composite endpoint) + Methods-section scope narrowing. ~2 h of work. Narrower claim ("the skill changes latency profile, not retrieval quality on this case pack") but ships immediately.
- **Path C**: Abandon the harness_x_model benchmark entirely and pursue a citation-accuracy judge benchmark (Option β from §7). ~2 weeks of work. Highest scientific value but out of scope for the current session.

Tier-1 patches, the middleware fix (H4), the pilot runner, the 4-gate enforcement, the R analyzer, the RUNBOOK, and the post-hoc analyzer are all validated and shippable regardless of which path is chosen. The architect explicitly approved the infrastructure; the only open question is which endpoint to measure.
