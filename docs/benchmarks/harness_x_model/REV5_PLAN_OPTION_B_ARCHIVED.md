# Plan: PLAN.md Rev 4 → Rev 5 — address triple-review findings

## Context

After updating `docs/benchmarks/harness_x_model/PLAN.md` to Rev 4 (incorporating SEARCHER + `search_literature_dynamic` upstream changes from commits `65b93e0`..`81ffee0`), three independent reviews ran against the update: Codex adversarial, `oh-my-claudecode:architect`, and `oh-my-claudecode:code-reviewer`. All three cross-converged on the same measurement-validity holes.

**Why Rev 5 is needed** — three categories of problem:

1. **Measurement validity (CRITICAL)** — two reviewers independently found that Rev 4's primary endpoint (tag-aware `genes_coverage_pct`) silently credits the LLM for *asking* rather than for *finding*. Under Rev 4's mandatory `enable_lr_pair_queries=True`, any gene the LLM puts in `query_cache` gets full coverage credit via `biomcp_tag_only` label as soon as BioMCP returns any paper — even an empty-abstract placeholder. The harness ON arm instructs the LLM to emit more gene-bearing queries, so ON mechanically scores higher than OFF regardless of whether retrieved papers actually discuss those genes. The benchmark as written risks measuring "did the harness make the LLM put more genes in JSON output" — i.e., re-measuring the existing skill-activation F1 benchmark with extra latency.

2. **Implementer gaps (HIGH)** — Rev 4 added 8 new `SearchTrialResult` fields (`genes_tag_text_confirmed_pct`, `candidate_pool_size`, `alias_prewarm_latency_ms`, etc.) but several cannot be populated from the public return shape of `search_literature_dynamic`. The trial runner also faces a slot-allocator skew: in Option B+'s `query_cache` path, fewer queries are issued, so BioMCP `page_size` per query inflates from ~7 to ~46 (a 6.5× retrieval-load asymmetry vs production) unless `max_results` is explicitly capped.

3. **Process risk (from Codex)** — `docs/benchmarks/harness_x_model/` is `.gitignore`d at `.gitignore:57-60` (everything under `docs/benchmarks/` is ignored except `drugtarget_skill_ablation`). Rev 4 edits to PLAN.md are local-only: they don't appear in `git diff`, won't enter any PR, and won't be protected by history or CI. For a doc that drives a 360-trial benchmark, this is a real correctness risk, not cosmetic.

Intended outcome: ship Rev 5 with the primary endpoint fixed to "retrieval-assertion + text-confirmed" coverage, the trial runner made symmetric with production retrieval (via pre-pending deterministic gene singletons to `query_cache`), the dataclass telemetry made observable, the pilot gate expanded to catch the realistic failure modes (saturation, tag-credit channel dominance, alias degradation), and the file unignored so the plan enters normal code review.

## Review synthesis — findings that Rev 5 must address

Findings are grouped by severity and deduplicated across the three reviewers. I preserve the review's internal labels (CR = code-reviewer, AR = architect, CX = Codex) for traceability.

### CRITICAL (block on these before pilot runs)

1. **Tag-only credit inflates the harness arm** (AR CRITICAL-2, CR CRITICAL-1; cross-confirmed). `_calculate_coverage(use_retrieval_tags=True)` at `literature.py:1796-1818` credits any gene appearing in `paper.matched_via_query.genes` regardless of whether the paper's title/abstract actually mentions that gene. The stamp is constructed unconditionally on success, exception-fallback, and pmid-only paths (`literature.py:520-525, 580-600`). A degraded BioMCP returning empty-abstract papers still triggers full tag-only credit. The harness ON arm, instructed by the inlined SKILL.md to emit more comprehensive gene queries, gets a free coverage lift proportional to query verbosity. Rev 4's "tag-aware vs tag-unaware sensitivity" framing cannot rescue this because tag-unaware still captures the retrieval-driven lift — the two metrics aren't independent enough to disentangle.

2. **Pathway fan-out is NOT a "uniform baseline"** (AR CRITICAL-1). Rev 4's §3.4 step 5 and Rev 4 Delta table both claim pathway fan-out acts uniformly across arms. Verified at `literature.py:2796-2827`: the block does run on both cache-replay and LLM paths, but the dedup pass (`:2801-2813`) operates on structurally different `validated_queries` inputs. Net result:
   - Option B+ cache path executes `~13 pathway queries + N LLM queries (typically 2-8)` per trial.
   - Option A / production executes `~13 pathway queries + ~30 gene singleton queries + N LLM queries`.
   - That is a **≥22-query gene-centric asymmetry per trial**. The harness effect measured in Option B+ is LLM-enrichment-quality *on top of the pathway baseline only*, while Option A measures LLM-enrichment-quality *on top of pathway + gene-singleton baseline*. The two are not directly comparable; the "Option A directional agreement sign-test" mitigation in Rev 4's risk row is insufficient.

3. **Candidate pool slot allocator skew** (AR CRITICAL-3). Internal `max_results` is bumped to `max(max_results*5, 300)` at `literature.py:2564`. The slot allocator at `literature.py:2835-2842` computes `gene_results_per_query = max(5, gene_slots // len(gene_queries) + 1)`. With fewer gene queries in Option B+ cache path (~4 LLM queries), each query asks BioMCP for **46 papers** instead of production's **7**. This is a 6.5× per-query retrieval-load skew — hidden load on PubMed, skewed latency distribution, and contamination of the outage-detection rule.

### HIGH

4. **Parse validator doesn't require gene-bearing queries** (CR HIGH-1). §3.4 `parse_with_retry` validates `query_objects` is a non-empty list but does NOT assert any `query_objects[i]["genes"]` is non-empty. An LLM producing only pathway/keyword queries passes validation, then feeds a `query_cache` with zero gene slots — downstream, the deterministic pathway fan-out contributes all gene credit via `PATHWAY_TO_GENES`, and the harness effect attributable to *LLM gene enrichment* becomes vacuous. Silent attenuation of the harness×model interaction, strongest in arms where the LLM defaults to pathway-heavy queries.

5. **Deterministic vs LLM gene-credit is indistinguishable in telemetry** (CR HIGH-2). After `literature.py:2814, 2819-2820` rebuild `all_queries` from `deterministic_pw + pw_kept`, papers stamped from both sources carry identical `matched_via_query.genes` values. The trial runner cannot tell whether a gene was covered via LLM-submitted genes or via deterministic pathway fan-out. `§4.1` sensitivity analysis cannot isolate the harness-prompt contribution.

6. **Alias cache poisoning across cases** (CR HIGH-3, AR MEDIUM-3). `_GENE_ALIAS_CACHE` is module-level (`literature.py:56-57`) and populated with `setdefault(gene.upper(), [])` on BioMCP outage (`literature.py:2607`). Once a gene is recorded with an empty alias list during a degraded window, every subsequent case sharing that gene symbol runs with crippled pattern matching, silently dropping `genes_tag_text_confirmed_pct` for the rest of the run. Under Option β (per-case block randomization), only the first trial per case pays the pre-warm; the next three see the warmed cache — which also means the `alias_prewarm_latency_ms` telemetry field is inflated on 30 trials and near-zero on 330.

7. **Pilot ceiling gate thresholds wrong** (AR HIGH-2, CR HIGH-4). Rev 4's single ≥95% gate misses: (a) differential attenuation where no cell saturates but the interaction effect shrinks below detection (e.g., strong_on 92/strong_off 88/weak_on 75/weak_off 70); (b) tag-only credit saturation where coverage looks healthy but is composed of stamp-only credits from degraded BioMCP responses; (c) alias degradation masking as coverage drop.

8. **Statistical power re-estimation is hand-waved** (AR HIGH-3). Rev 4 says "MUST re-estimate N_required from observed effect sizes" but specifies no method. With GLMM + binary outcome + interaction there's no closed-form; need `simr::powerSim(fit_pilot, fixed("harness:model_strength", "lrt"), nsim=500)` or equivalent. Rev 4 also doesn't state what to do if pilot says `N_required > 360`.

9. **`max_iterations=1` + candidate pool sentinel makes `max_results` a load-bearing knob** (AR HIGH-1). The early-break check at `literature.py:2660` is gated on `iteration > 0`, so the benchmark never hits it. The internal pool fills to 300, then `_greedy_coverage_sort` truncates to `_final_paper_cap = caller's max_results`. If the runner leaves `max_results` at SEARCHER's default (50), greedy sort has 6× headroom — a different selection regime than `max_results=25`. Rev 4 doesn't fix this knob.

10. **§8 `_calculate_coverage` line range misses legacy fallback** (AR HIGH-4). Line range `1793-1862` covers only the tag-aware branch. Legacy regex label production at `1820-1833, 1864-1868` is what tests assert on and what the trial runner must parse (`label not in ("biomcp_tag_only", "biomcp_tag+text_confirmed")` → regex-only hit). Implementer will silently lose tag-unaware sensitivity data if they use Rev 4's narrower range.

### MEDIUM (address if doing full Rev 5 edit pass)

11. **`candidate_pool_size`, `alias_prewarm_latency_ms`, `llm_query_count_post_dedup` are not observable from `search_literature_dynamic`'s public return** (AR MEDIUM-1/2, AR LOW-2, CR MEDIUM-3). The return dict at `literature.py:3032-3045` exposes `papers`, `generated_queries`, `coverage`, etc. — but not `len(all_papers)` pre-truncation, not the pre-warm timing, and not the pre-dedup LLM query count. Either (a) add return-value fields via a small `literature.py` edit, (b) compute them by re-running pure helpers in the trial runner, or (c) drop the fields.

12. **`genes_matched_by` public return path not verified** (CR MEDIUM-3). Rev 4 §3.4 step 5 says "Capture `genes_matched_by` / `pathways_matched_by` from the coverage return". Whether these survive from `_calculate_coverage` through `search_literature_dynamic_async`'s public return is not audited. If stripped, the new dataclass fields cannot be populated without calling `_calculate_coverage` directly post-hoc on the returned papers.

13. **`PATHWAY_TO_GENES` has no snapshot** (CR MEDIUM-1). Rev 4 inlines the pathway list as a sentence in the Delta section. A later refactor adding/removing a pathway silently desyncs the plan from the measurement. Snapshot + hash on benchmark start, compare on resume, abort on drift.

14. **Missing integration test for unconditional pathway fan-out in cache-replay** (CR MEDIUM-4). Unit tests in `test_deterministic_pathway_queries.py` cover the helper; nothing asserts that `search_literature_dynamic_async(query_cache=..., enable_lr_pair_queries=True, pathways=[...])` actually invokes the helper. A future refactor moving the `if iteration == 0 and enable_lr_pair_queries:` inside the cache-vs-LLM branch would break the benchmark silently while unit tests still pass.

15. **SKILL.md `think_success` strip rule is fragile** (AR MEDIUM-4). §3.2 step 5 says "Strip `think_success` references" but gives no regex. A future SKILL.md edit renaming the field would leak dead instructions into the ON arm prompt.

16. **`_compute_paper_coverage_score` stamp credit leaks via `_execute_fixed_strategy_search_async` fallback** (AR MEDIUM-5). Currently unreachable in benchmark mode because `query_cache` short-circuits the fallback. Add a hard policy row in §10 forbidding any future relaxation of the hard-JSON-failure policy to "fall back to fixed-strategy search", which would silently activate stamp credit in the OFF arm.

17. **`data_dir` kwarg handling not audited** (CR MEDIUM-2). Production SEARCHER passes `data_dir=data_path.strip()` at `subagents/prompts.py:254-263`. Rev 4's trial-runner call example doesn't pass `data_dir`. Whether `data_dir=None` triggers any side-channel affecting coverage is not audited.

### LOW (polish; bundle with medium pass)

18. **Line numbers in §8 drift** (AR LOW-1). Use function-name anchors + a preflight symbol-existence check in `scripts/diagnose_searcher_coverage.py --check-anchors`.

19. **OWASP-style gene-name sanitization** (CR LOW-1). `enriched_cases.json` flows unsanitized into `_fetch_gene_aliases_from_biomcp`. Low severity (curated cases), but a one-line regex guard is trivial.

20. **Invariant assertion** (CR LOW-2). `genes_coverage_pct` should equal `genes_tag_text_confirmed_pct + genes_tag_only_pct + genes_legacy_regex_pct` (±0.5%). Add `genes_legacy_regex_pct` field and a post-trial assert.

21. **`candidate_pool_size` comment is wrong** (CR LOW-3). Says "≤300" but `literature.py:2564` is a floor, not a cap — pool can exceed 300 when `max_results > 60`.

22. **Alias pre-warm latency budget estimate is 12× off** (CR LOW-4). Rev 4 risk row says "360 trials × 20s ≈ 2h". Under Option β cache reuse it's `30 cases × 20s ≈ 10 min`.

23. **Evidence-manifest test gap** (AR LOW-3). No test asserts tag-only credit is bounded per-query-breadth. Add a smoke test asserting `genes_tag_only_pct` is observable as a separate signal and does not balloon under crafted empty-abstract inputs.

### Process (orthogonal to content)

24. **PLAN.md is git-ignored** (CX HIGH). `.gitignore:57-60` re-ignores everything under `docs/benchmarks/` except `drugtarget_skill_ablation`. `git check-ignore -v docs/benchmarks/harness_x_model/PLAN.md` resolves to `.gitignore:59`, and `git ls-files --error-unmatch` reports the path as unknown to git. Rev 4 edits are local-only. Fix by adding an `!docs/benchmarks/harness_x_model/` unignore rule adjacent to the existing `drugtarget_skill_ablation` exception.

## Recommended Rev 5 edit pass

The review produced ~24 findings. Rev 5 should prioritize the measurement-validity blockers (CRITICAL + HIGH items 1-10) and bundle the MEDIUM/LOW polish into a single second-half edit pass. Total estimated effort: ~5 hours of plan edits + ~30 minutes of `.gitignore` + possibly ~15 lines of `literature.py` telemetry return-field additions (if pursuing observability option (a) for items 11-12).

The edit order below is chosen so that each group is self-contained and independently committable.

### Group A — Process fix (unblocks everything else)

**A.1** Edit `.gitignore` to unignore `docs/benchmarks/harness_x_model/`. Add the rule adjacent to the existing `drugtarget_skill_ablation` exception at `.gitignore:57-60` so the style matches. After this edit, `git status` should surface `PLAN.md` and all Rev 5 edits will enter PRs normally.

Verification: `git check-ignore -v docs/benchmarks/harness_x_model/PLAN.md` must print nothing (the path is no longer ignored) and `git ls-files --error-unmatch docs/benchmarks/harness_x_model/PLAN.md` must exit zero after `git add`.

### Group B — Primary endpoint + pilot gate (fixes CRITICAL-1/2 measurement validity)

**B.1** In Rev 4 Delta "Key measurement implication" paragraph (currently at `PLAN.md:30-32`), add a second sentence: tag-only credit is NOT a measurement of paper-content match, only of query-construction completeness. Under mandatory `enable_lr_pair_queries=True`, `_calculate_coverage(use_retrieval_tags=True)` credits any gene appearing in `paper.matched_via_query.genes` regardless of abstract content, so tag-only credit is diagnostic only.

**B.2** In §4.1 GLMM primary, flip the sensitivity hierarchy: promote the tag-unaware analysis (`use_retrieval_tags=False`) to **secondary/diagnostic**, and make the **tag-text-confirmed-only** metric the primary endpoint. Concretely:
- Redefine `coverage_pass = (genes_tag_text_confirmed_pct ≥ 60%)` (not built from total `genes_coverage_pct`).
- Keep tag-aware total as a diagnostic in §4.5.
- Add a note explaining why: "matches production" is the wrong frame; "measurement-valid for the harness effect" is the right one.

**B.3** In §3.4 `SearchTrialResult`, add two fields:
- `tag_only_with_empty_abstract_count: int = 0` — count papers where stamp credits a gene but `paper.get("abstract", "").strip() == ""`. This is the tripwire for CRITICAL-1.
- `genes_tag_only_with_real_text_pct: float = 0.0` — the "defensible" tag-only metric that re-validates the stamp against a non-empty abstract before crediting.
- Also add `genes_legacy_regex_pct: float = 0.0` so the three-tier invariant `tag_text_confirmed + tag_only + legacy_regex ≈ coverage_pct` holds (fixes LOW-2).

**B.4** In §4.6 pilot checks, **replace** the Rev 4 single-threshold gate (≥95% both strong cells) with three combined gates:
- **Gate A (real-evidence saturation)**: `genes_tag_text_confirmed_pct ≥ 95%` in both `strong_on` AND `strong_off` → abort; deterministic fan-out saturates real-paper coverage. Take fallback (a) — switch endpoint to diversity/novelty — or (b) degrade `enable_lr_pair_queries=False`.
- **Gate B (tag-credit channel dominance)**: `(genes_tag_only_pct − genes_tag_text_confirmed_pct) ≥ 30%` in any cell → abort; BioMCP is returning empty papers and the tag gate is vacuous. **Infrastructure fix first**, do NOT switch primary endpoint.
- **Gate C (alias degradation)**: `alias_cache_hit_rate < 80%` in any cell → abort; BioMCP outage during pre-warm poisoned the cache. Infrastructure fix first.
- Also keep the effect-attenuation gate from AR HIGH-2: pilot interaction Cohen's `f < 0.15` → re-estimate N, expect N>1000 → reconsider Option B+ vs Option A tradeoff.

### Group C — Trial runner symmetry (fixes CRITICAL-1 architect, CRITICAL-3)

**C.1** In §3.4 step 5, prepend deterministic gene singletons to `query_cache` in the trial runner before calling `search_literature_dynamic`. Concretely:

```python
from src.agents.deep_interpreter.tools.literature import _build_deterministic_gene_queries
gene_singletons = _build_deterministic_gene_queries(
    genes=case.enriched_genes, disease=case.disease, chunk_size=1
)
final_query_cache = gene_singletons + llm_query_objects
result = search_literature_dynamic(
    ..., query_cache=final_query_cache, max_iterations=1,
    enable_lr_pair_queries=True, max_results=25,
)
```

This restores Option B+ ↔ production retrieval symmetry (fixes CRITICAL-1 architect), fixes the slot-allocator skew (CRITICAL-3) because query count becomes comparable, and aligns the gene-side baseline with pathway-side. Document in the step 5 prose that the runner imports a private helper — acceptable because the plan is already coupled tightly to `literature.py` internals.

**C.2** In §3.4 step 5, **hardcode `max_results=25`** to match production SEARCHER's saved-paper budget. Add a one-line rationale: "the internal candidate pool is auto-bumped to `max(25*5, 300) = 300`; `_greedy_coverage_sort` truncates back to 25. `max_results` is now a load-bearing knob — any change would alter the greedy-sort selection regime and break cross-run comparability."

**C.3** In §3.4 `SearchTrialResult`, add:
- `llm_attributed_genes: list[str] = field(default_factory=list)` — union of `q["genes"]` over the LLM's original `query_cache` (pre-prepend).
- `deterministic_pathway_genes: list[str] = field(default_factory=list)` — union of genes injected by `_build_deterministic_pathway_queries` for that case (computed by calling the helper directly in the runner).
- `genes_covered_llm_only: float = 0.0` — computed as `len(covered_genes − deterministic_pathway_genes) / len(genes)`. This is the **harness-effect-attributable** subset referenced by §4.2 as a primary secondary analysis.

### Group D — Parse validation + query composition telemetry (fixes HIGH-1, HIGH-2)

**D.1** In §3.4 `parse_with_retry`, tighten the validator:

```python
gene_query_count = sum(1 for q in parsed["query_objects"] if q.get("genes"))
assert gene_query_count >= 2, "LLM must produce ≥2 gene-bearing queries"
```

Document that trials failing this tighter gate (`llm_gene_query_count_pre_dedup < 2`) are marked `parse_failure=True` and fall under the existing hard-failure + MNAR sensitivity path (§4.1).

**D.2** In §3.4 `SearchTrialResult`, add:
- `llm_gene_query_count_pre_dedup: int = 0`
- `llm_gene_query_count_post_dedup: int = 0`

And document that these are computed in the runner by counting `q.get("genes")` on the pre- and post-`final_query_cache` lists, since `search_literature_dynamic`'s public return does not expose them (fixes MEDIUM-3 partially).

### Group E — Alias cache isolation (fixes HIGH-3 / MEDIUM-3)

**E.1** In §3.4 (or a new §3.5a subsection), document a **per-case warm phase**: before running any of a case's 4 conditions, the runner clears and pre-warms `_GENE_ALIAS_CACHE` via a direct call to `_fetch_gene_aliases_from_biomcp` on the case's enriched genes. Each condition within the case then measures only `search_literature_dynamic` wall-clock. This moves the warm-up cost outside the trial timer and prevents cross-case poisoning.

**E.2** Add `alias_cache_hit_rate: float = 0.0` to `SearchTrialResult`. Computed as `len(_GENE_ALIAS_CACHE & {g.upper() for g in case.enriched_genes}) / len(case.enriched_genes)` at trial start. Drives Gate C from B.4.

**E.3** Add checkpoint/resume determinism — in §3.6, document persisting the alias cache snapshot to `results/{run_id}/alias_cache.json` after each case completes. On resume, load the snapshot before the next case starts. Include a determinism check in §9: "run pilot twice with the same seed; assert all `genes_tag_text_confirmed_pct` values are bit-identical."

**E.4** Update the Rev 4 risk row on alias pre-warm latency: change "360 trials × 20s ≈ 2h" to "30 case-warm phases × 20s ≈ 10min (latency moved outside trial timer)" (fixes LOW-4).

### Group F — Statistical power method + §8 line range (fixes HIGH-3 architect, HIGH-4 architect)

**F.1** In §4.6 step 3 (and the Rev 4 Delta reference to it), specify: `simr::powerSim(fit_pilot, fixed("harness:model_strength", "lrt"), nsim=500)`. Add a decision rule: if `N_required > 360`, choices are (a) abandon Option B+ interaction claim and report main effects only, (b) raise `repeats` to 5 (600 trials, ~30h wall-clock), (c) report null with framing that explicitly cites `N_required` from the power analysis.

**F.2** In §8, expand the `_calculate_coverage` row from `1793-1862` to `1771-1894` (full function body) and add a one-line note: "the legacy label is the matched pattern literal, not a tier string — parse `genes_matched_by[gene] in {'biomcp_tag_only', 'biomcp_tag+text_confirmed'}` to detect tag credit; anything else is a regex hit."

### Group G — Observability audit COMPLETED (audited in source session, 2026-04-14)

**Audit result**: outcome (b) confirmed. **6 of 8 Rev 5 telemetry fields are reachable from `search_literature_dynamic`'s public return without modifying `literature.py`**; 2 fields (`candidate_pool_size`, `alias_prewarm_latency_ms`) require either a drop or a relocation. **No `literature.py` edit needed.** The original "(c) ~15-line additive edit" branch is abandoned.

#### Audited surface

`search_literature_dynamic_async` at `literature.py:2466-2521` returns `full_result` at `literature.py:3032-3045` only when `output_path` is empty. **The trial runner MUST call with `output_path=None`** — passing a non-empty `output_path` triggers the compact summary path at `literature.py:3061-3082` which strips `papers` and `generated_queries` from the return.

`full_result` shape (verified):

```python
{
  "papers": [paper, ...],            # post-truncation; each paper carries matched_via_query stamp
  "generated_queries": [...],        # post-dedup query list (deterministic_pw + pw_kept order)
  "coverage": <_calculate_coverage return>,
  "search_method": "search_literature_dynamic",
  "think_success": bool,
  "iterations": int,
  "coverage_history": [...],
  "coverage_sufficient": bool,
  "recommended_actions": [...],
  "filter_stage": str,
  "rerank_applied_count": int,
  "rerank_dropped_count": int,
  # optional: "query_cache" if record_queries=True
}
```

`coverage` shape (`literature.py:1771-1781`):

```python
{
  "genes_covered": [...],
  "genes_matched_by": {gene: label},   # label ∈ {"biomcp_tag+text_confirmed", "biomcp_tag_only", <regex_pattern_literal>}
  "pathways_covered": [...],
  "pathways_matched_by": {pathway: label},
  "celltypes_covered": [...],
  "total_papers": int,                  # = len(final_papers), post-truncation
  "genes_coverage_pct": float,
  "pathways_coverage_pct": float,
  "celltypes_coverage_pct": float,
}
```

#### Reachability table

| Rev 5 field | Reachable? | Source / extraction |
|---|---|---|
| `genes_tag_text_confirmed_pct` (B.3) | ✅ | Count `coverage["genes_matched_by"]` values equal to `"biomcp_tag+text_confirmed"` |
| `genes_tag_only_pct` (B.3) | ✅ | Same dict, count `"biomcp_tag_only"` |
| `genes_legacy_regex_pct` (B.3) | ✅ | Same dict, count values that are NEITHER of the two tier labels |
| `pathways_tag_text_confirmed_pct` (B.3) | ✅ | `coverage["pathways_matched_by"]` same pattern |
| `pathways_tag_only_pct` (B.3) | ✅ | Same |
| `tag_only_with_empty_abstract_count` (B.3) | ✅ | Iterate `result["papers"]` — count papers where `matched_via_query.genes` is non-empty AND `abstract.strip() == ""`. **CRITICAL-1 tripwire is implementable WITHOUT touching `literature.py` — the most important audit finding.** |
| `genes_covered_llm_only` (C.3) | ✅ | `set(coverage["genes_covered"]) - deterministic_pathway_genes`. Compute `deterministic_pathway_genes` in the runner by calling `_build_deterministic_pathway_queries(case.pathways, case.disease)` directly (pure function) and unioning the `genes` field of each returned query. |
| `llm_attributed_genes` / `deterministic_pathway_genes` (C.3) | ✅ | Runner-side state — capture `llm_attributed_genes` BEFORE Group C.1's `query_cache` prepend; compute `deterministic_pathway_genes` via the helper above. |
| `llm_gene_query_count_pre_dedup` (D.2) | ✅ | Runner counts gene-bearing queries in the original LLM `query_cache` before prepend. |
| `llm_gene_query_count_post_dedup` (D.2) | ✅ | Count gene-bearing queries in `result["generated_queries"]`, subtract `len(deterministic_pathway_queries)` to get LLM-survivor count. |
| `alias_cache_hit_rate` (E.2) | ✅ | Runner reads `literature._GENE_ALIAS_CACHE` directly at trial start: `len({g.upper() for g in case.genes} & set(_GENE_ALIAS_CACHE.keys())) / len(case.genes)`. Under Option β scheduling, trials 2-4 of each case see hit rate ≈ 100%; only trial 1 measures the real cold-start signal. |
| `candidate_pool_size` (Rev 4 PLAN.md §3.4 line ~331) | ❌ | `len(all_papers)` is a function-internal variable, never returned. **DROP** — see G.1 below. |
| `alias_prewarm_latency_ms` (Rev 4 PLAN.md §3.4 line ~332) | ❌ | The pre-warm block at `literature.py:2580-2629` emits `logger.info` only, no timing stamp in return. **RELOCATE** to runner-side per-case warm phase — see G.2 below. |

#### Extraction code stubs (drop-in for the trial runner)

```python
# In trial runner, AFTER: result = search_literature_dynamic(..., output_path=None)
coverage = result["coverage"]
papers = result["papers"]

# ── B.3 / B.2 → tag-tier provenance for genes ──
gene_labels = coverage["genes_matched_by"]
n_total_genes = len(case.genes)
n_tag_text = sum(1 for v in gene_labels.values() if v == "biomcp_tag+text_confirmed")
n_tag_only = sum(1 for v in gene_labels.values() if v == "biomcp_tag_only")
n_legacy_regex = len(gene_labels) - n_tag_text - n_tag_only

trial_result.genes_tag_text_confirmed_pct = 100.0 * n_tag_text / max(n_total_genes, 1)
trial_result.genes_tag_only_pct          = 100.0 * n_tag_only / max(n_total_genes, 1)
trial_result.genes_legacy_regex_pct      = 100.0 * n_legacy_regex / max(n_total_genes, 1)

# ── B.3 → tag-tier provenance for pathways ──
pw_labels = coverage["pathways_matched_by"]
n_total_pw = len(case.pathways)
n_pw_tag_text = sum(1 for v in pw_labels.values() if v == "biomcp_tag+text_confirmed")
n_pw_tag_only = sum(1 for v in pw_labels.values() if v == "biomcp_tag_only")
trial_result.pathways_tag_text_confirmed_pct = 100.0 * n_pw_tag_text / max(n_total_pw, 1)
trial_result.pathways_tag_only_pct           = 100.0 * n_pw_tag_only / max(n_total_pw, 1)

# ── B.3 → CRITICAL-1 tripwire (the most load-bearing field) ──
n_empty_abstract_with_tag = 0
for paper in papers:
    mvq = paper.get("matched_via_query") or {}
    if mvq.get("genes") and not paper.get("abstract", "").strip():
        n_empty_abstract_with_tag += 1
trial_result.tag_only_with_empty_abstract_count = n_empty_abstract_with_tag

# ── C.3 → LLM-vs-deterministic gene attribution split ──
from src.agents.deep_interpreter.tools.literature import _build_deterministic_pathway_queries
det_pw_queries = _build_deterministic_pathway_queries(case.pathways, case.disease)
deterministic_pathway_genes = set()
for q in det_pw_queries:
    deterministic_pathway_genes.update(q.get("genes") or [])
trial_result.deterministic_pathway_genes = sorted(deterministic_pathway_genes)
trial_result.llm_attributed_genes = sorted(
    {g for q in original_query_cache for g in (q.get("genes") or [])}
)
covered_set = set(coverage["genes_covered"])
trial_result.genes_covered_llm_only = (
    100.0 * len(covered_set - deterministic_pathway_genes) / max(n_total_genes, 1)
)

# ── D.2 → LLM gene query counts pre/post dedup ──
trial_result.llm_gene_query_count_pre_dedup = sum(
    1 for q in original_query_cache if q.get("genes")
)
generated = result["generated_queries"]
trial_result.llm_gene_query_count_post_dedup = (
    sum(1 for q in generated if q.get("genes")) - len(det_pw_queries)
)

# ── E.2 → alias cache hit rate (call BEFORE search_literature_dynamic) ──
from src.agents.deep_interpreter.tools import literature as _lit
keys = set(_lit._GENE_ALIAS_CACHE.keys())
input_uppers = {g.upper() for g in case.genes}
trial_result.alias_cache_hit_rate = len(input_uppers & keys) / max(len(input_uppers), 1)
```

Notes for the implementer:

- **`original_query_cache`** = the LLM-emitted JSON BEFORE Group C.1's deterministic gene singleton prepend. The runner must capture this snapshot before constructing `final_query_cache = gene_singletons + original_query_cache`. Otherwise `llm_attributed_genes` and `llm_gene_query_count_pre_dedup` become indistinguishable from the deterministic prepend.
- **`_build_deterministic_pathway_queries`** is a pure function — no BioMCP I/O, no global state mutation. Safe to call from the runner. Same applies to `_build_deterministic_gene_queries` used in Group C.1.
- **`alias_cache_hit_rate` measurement timing**: must run AFTER Group E.1's per-case warm phase (so trial 1 of each case reports the post-warm hit rate, not pre-warm) but BEFORE the `search_literature_dynamic` call (so the metric is independent of the search itself).
- **`genes_legacy_regex_pct` formula**: `len(gene_labels) - n_tag_text - n_tag_only` is the count of genes covered via `_calculate_coverage`'s legacy regex branch (`literature.py:1820-1833`). The `gene_labels` dict only contains entries for COVERED genes — uncovered genes are absent. This means the three tier percentages sum to `genes_coverage_pct`, not to 100% (the LOW-2 invariant assertion in H.8 must use this relation).

#### G.1 — DROP `candidate_pool_size` from `SearchTrialResult`

Rev 4 added `candidate_pool_size: int = 0` at PLAN.md §3.4 line ~331 to track pre-truncation `len(all_papers)`. The audit confirms this value is **not exposed** in `full_result` and would require modifying `literature.py:3032-3045`.

**Rev 5 action**: REMOVE this field from §3.4 dataclass entirely. Replace with a one-line design-time note in the §3.4 prose:

> *Under SEARCHER mode (`enable_lr_pair_queries=True`) + `max_iterations=1`, the internal candidate pool always saturates at the floor (300 papers) before `_greedy_coverage_sort` truncates back to `max_results=25` (per C.2). Pool size is fixed by design and not tracked per-trial.*

**Rationale**: with `max_iterations=1` the iter>0 early-break at `literature.py:2660` cannot fire, so iter-0 fan-out runs to completion. The slot allocator at `literature.py:2835-2842` distributes paper slots across the queries. The pool size has effectively zero per-trial variance — tracking it is wasted telemetry that depends on a `literature.py` edit we don't want to make.

#### G.2 — RELOCATE `alias_prewarm_latency_ms` to runner-side per-case warm phase

Rev 4 added `alias_prewarm_latency_ms: float = 0.0` at PLAN.md §3.4 line ~332 to capture BioMCP gene-alias pre-warm wall-clock. The audit confirms this is **not observable** from `search_literature_dynamic`'s return.

**Rev 5 action**: KEEP the field in `SearchTrialResult`, but populate it from the **runner-side per-case warm phase** introduced in Group E.1, not from inside `search_literature_dynamic`. Implementation:

```python
import time
from src.agents.deep_interpreter.tools.literature import (
    _GENE_ALIAS_CACHE, _GENE_ALIAS_CACHE_LOCK, _fetch_gene_aliases_from_biomcp,
)

async def warm_alias_cache_for_case(case) -> float:
    """Pre-warm _GENE_ALIAS_CACHE for case.genes. Returns wall-clock latency in ms.

    Run ONCE per case before any of its 4 trials. The first trial of each case
    records this latency; trials 2-4 within the same case record 0.0 (warmed).
    """
    start = time.monotonic()
    async def _bounded(g: str) -> list[str]:
        try:
            return await asyncio.wait_for(
                _fetch_gene_aliases_from_biomcp(g), timeout=10.0
            )
        except Exception:
            return []
    targets = case.genes[:30]
    results = await asyncio.gather(
        *[_bounded(g) for g in targets], return_exceptions=True
    )
    with _GENE_ALIAS_CACHE_LOCK:
        for g, r in zip(targets, results):
            if isinstance(r, Exception) or not r:
                _GENE_ALIAS_CACHE.setdefault(g.upper(), [])
            else:
                _GENE_ALIAS_CACHE[g.upper()] = list(r)
    return (time.monotonic() - start) * 1000.0
```

Trial runner integration: store the returned latency in a case-scoped variable; assign it to `trial_result.alias_prewarm_latency_ms` for the FIRST trial of that case only, set `0.0` for the other three trials. This makes the field semantically meaningful (real cold-start cost per case) instead of capturing internal `search_literature_dynamic` pre-warm noise that fires on every trial.

This relocation also closes **CR HIGH-3 (alias cache cross-case poisoning)** by giving the runner explicit ownership of cache lifecycle. Combined with Group E.3's snapshot/restore between cases, alias cache state becomes deterministic across resume-from-checkpoint.

#### G.3 — `literature.py` is unchanged

The Group G audit conclusion is **outcome (b) — partial reachability with documented workarounds**. The original "(c) — critical fields missing → 15-line additive edit to `full_result`" branch is **abandoned**. Rev 5 ships with PLAN.md edits only.

This preserves byte-equivalence guarantees for PLANNER/REPORTER (the dead-code chain comment at `literature.py:514-519` still holds end-to-end) and avoids any risk of breaking existing `search_literature_dynamic` callers in the production Deep Interpreter pipeline.

### Group H — MEDIUM/LOW polish (bundle as a second-half edit)

These items are low individual effort; do them in one pass.

- **H.1** PATHWAY_TO_GENES snapshot: §3.4 adds "hash `literature.py.PATHWAY_TO_GENES` + `PATHWAY_KEYWORDS` on benchmark start; write to `results/{run_id}/pathway_mapping_snapshot.json`; abort on resume mismatch." Add §10 risk row and §9 verification step. (MEDIUM item 13.)
- **H.2** Integration test contract: §9 verification adds a requirement for `tests/deep_interpreter/test_search_literature_dynamic_integration.py::test_pathway_fanout_runs_in_cache_replay` (mocked BioMCP, asserts MAPK1/MAPK3/RAF1 appear in recorded queries when `query_cache` is passed with pathways=['mapk']). Implementer writes this test during pilot prep. (MEDIUM item 14.)
- **H.3** `think_success` strip regex: §3.2 step 5 adds an explicit regex (`re.sub(r"###?.*?think_success.*?(?=\n###|\n##|\Z)", "", body, flags=re.DOTALL)`) and a post-strip assertion (`assert "think_success" not in result`). (MEDIUM item 15.)
- **H.4** `_compute_paper_coverage_score` fallback warning: §10 risks adds a row: "Implementer must NOT enable `_execute_fixed_strategy_search_async` fallback as a JSON-failure recovery path. Hard-failure policy is load-bearing for the dead-code-chain guarantee at `literature.py:514-519`." (MEDIUM item 16.)
- **H.5** `data_dir` kwarg audit: §3.4 step 5 documents the explicit set of kwargs including `data_dir=None, output_path=None`; §9 verification adds "print the full kwargs dict passed to `search_literature_dynamic` for one trial; manually verify it matches the production SEARCHER call sans `output_path`/`data_dir`." (MEDIUM item 17.)
- **H.6** Anchor-based §8 references: replace line-range citations with function-name anchors plus a preflight symbol-existence check in `scripts/diagnose_searcher_coverage.py --check-anchors`. (LOW item 18.)
- **H.7** Gene-name sanitization: §3.3 `enrich_case_genes` adds a `re.match(r"^[A-Za-z][A-Za-z0-9-]{0,19}$", gene)` guard; drop-and-log invalid entries. §9 adds spot-check. (LOW item 19.)
- **H.8** Invariant assertion: §3.4 post-trial adds `assert abs(result.genes_coverage_pct - (result.genes_tag_text_confirmed_pct + result.genes_tag_only_pct + result.genes_legacy_regex_pct)) < 0.5`. (LOW item 20, needs B.3 `genes_legacy_regex_pct` field.)
- **H.9** `candidate_pool_size` comment: update "≤300 after sentinel" to "= max(caller_max_results × 5, 300)". (LOW item 21.)
- **H.10** Evidence-manifest bounded-credit smoke test: §9 verification adds a reference to a new test asserting `genes_tag_only_pct` remains observable as a separate signal and does not balloon under crafted empty-abstract inputs. (LOW item 23.)

## Critical files to modify

1. `/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/.gitignore` — add `!docs/benchmarks/harness_x_model/` unignore rule adjacent to the existing `drugtarget_skill_ablation` exception at lines 57-60. This is the first edit; it unblocks all subsequent PLAN.md edits to surface in git.

2. `/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/docs/benchmarks/harness_x_model/PLAN.md` — Rev 5 edit pass bumping the header, inserting a "Rev 5 Delta" section covering the 24 findings, and doing the surgical edits in Groups B-H. Touches:
   - Rev 4 Delta "Key measurement implication" paragraph (B.1)
   - §3.2 step 5 (H.3)
   - §3.3 `enrich_case_genes` (H.7)
   - §3.4 step 5 (C.1, C.2, E.1, H.5)
   - §3.4 `SearchTrialResult` dataclass (B.3, C.3, D.2, E.2)
   - §3.4 `parse_with_retry` (D.1)
   - §3.6 checkpoint/resume (E.3)
   - §4.1 GLMM primary endpoint definition (B.2)
   - §4.6 pilot checks (B.4, F.1)
   - §8 reusable code (F.2, H.6)
   - §9 verification (E.3, H.1, H.2, H.5, H.7, H.10)
   - §10 risks (E.4, H.1, H.4)

3. **NOT required**: `/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/src/agents/deep_interpreter/tools/literature.py` is **unchanged** in Rev 5. The Group G audit (executed in the source session, see Group G below) confirmed outcome (b): 6 of 8 telemetry fields are reachable from the public return without modification, and the 2 unreachable fields (`candidate_pool_size`, `alias_prewarm_latency_ms`) have documented workarounds (drop and relocate-to-runner, respectively). The original "(c) ~15-line additive edit" path is abandoned.

## Existing functions and utilities to reuse (no new code to invent)

- `_build_deterministic_gene_queries(genes, disease, chunk_size)` at `literature.py:~1319` — called directly from the trial runner per C.1 to prepend singletons to `query_cache`. Pure function.
- `_build_deterministic_pathway_queries(pathways, disease, pathway_to_genes, max_genes_per_query)` at `literature.py:~1369` — called directly from the trial runner per C.3 to compute `deterministic_pathway_genes` for the LLM-attribution split. Pure function.
- `PATHWAY_TO_GENES` dict at `literature.py:1571-1585` — hashed for the drift snapshot per H.1.
- `PATHWAY_KEYWORDS` dict at `literature.py:1547-1569` — hashed alongside for the same snapshot.
- `_fetch_gene_aliases_from_biomcp(gene, biomcp_url)` at `literature.py` — called directly from the trial runner per E.1 for the per-case warm phase. Async.
- `_GENE_ALIAS_CACHE` + `_GENE_ALIAS_CACHE_LOCK` at `literature.py:56-57` — manipulated from the runner per E.1/E.3 for snapshot/reset.
- `_calculate_coverage(papers, genes, pathways, celltypes, lr_pairs, use_retrieval_tags)` at `literature.py:1771-1894` — called directly from the runner post-hoc if `genes_matched_by` isn't exposed in the public return per G.1.
- `scripts/diagnose_searcher_coverage.py` — extended with `--check-anchors` preflight for H.6 and pathway-hash comparison for H.1.
- `scripts/rerun_searcher_only.py` — used as-is in the §8 reusable code table.
- `tests/deep_interpreter/test_deterministic_gene_queries.py` — existing unit tests; no modification.
- `tests/deep_interpreter/test_deterministic_pathway_queries.py` — existing unit tests; H.2 adds a new integration test alongside, not modifying this file.
- `tests/deep_interpreter/test_evidence_manifest.py` — existing tests; H.10 adds a new smoke test alongside.
- `benchmark_skill_harness.py:739-800` — existing tool-loop pattern, unchanged; referenced by Option A arm.
- `compare_expanded.py:365-540` — existing bootstrap CI, unchanged; referenced by §4.4.

## Verification

This section describes how to verify Rev 5 end-to-end after the edits land.

### Stage 1 — Process (unblocks everything)

```bash
# After Group A edit:
git check-ignore -v docs/benchmarks/harness_x_model/PLAN.md
# Expected: empty output (path no longer ignored)

git ls-files --error-unmatch docs/benchmarks/harness_x_model/PLAN.md
# Expected: exit 0 after `git add`

git diff docs/benchmarks/harness_x_model/PLAN.md
# Expected: full Rev 5 diff visible
```

### Stage 2 — Content compliance

```bash
# Read Rev 5 header and diff markers
grep -n "^## Rev 5" docs/benchmarks/harness_x_model/PLAN.md
# Expected: header section present

# Spot-check the 11 Rev 5 additions against the edit plan
grep -c "tag_only_with_empty_abstract_count\|genes_tag_only_with_real_text_pct\|genes_legacy_regex_pct\|alias_cache_hit_rate\|llm_gene_query_count_pre_dedup\|llm_gene_query_count_post_dedup\|llm_attributed_genes\|deterministic_pathway_genes\|genes_covered_llm_only" docs/benchmarks/harness_x_model/PLAN.md
# Expected: ≥9 (all new dataclass fields present)

# Verify pilot gate expansion
grep -A5 "Gate A\|Gate B\|Gate C" docs/benchmarks/harness_x_model/PLAN.md
# Expected: three gates documented in §4.6
```

### Stage 3 — Upstream code cross-check

```bash
# Verify line-range citations in §8 still resolve
python - <<'PY'
import ast, pathlib
src = pathlib.Path("src/agents/deep_interpreter/tools/literature.py").read_text()
for sym in ("_build_deterministic_gene_queries", "_build_deterministic_pathway_queries", "PATHWAY_TO_GENES", "PATHWAY_KEYWORDS", "_fetch_gene_aliases_from_biomcp", "_GENE_ALIAS_CACHE", "_calculate_coverage"):
    assert sym in src, f"missing symbol: {sym}"
print("all symbols resolved")
PY
```

### Stage 4 — Existing test suite unchanged

```bash
# Rev 5 should not touch any existing test; run to confirm no regressions
pytest tests/deep_interpreter/test_deterministic_gene_queries.py \
       tests/deep_interpreter/test_deterministic_pathway_queries.py \
       tests/deep_interpreter/test_evidence_manifest.py -v
# Expected: all pass unchanged
```

### Stage 5 — Pilot trial dry-run (after edits but before 360-trial commitment)

Not executed as part of Rev 5 plan approval — this is the user's next step after Rev 5 lands. Run a 4-trial smoke test (1 case × 4 conditions × 1 repeat) with the Rev 5 runner and verify:
- All new `SearchTrialResult` fields populate with non-zero, plausible values (not silently zero).
- `alias_cache_hit_rate` is 0.0 on the first trial and >0.8 on the next three (per-case warm phase working).
- `tag_only_with_empty_abstract_count` is 0 in a healthy BioMCP window.
- `llm_gene_query_count_pre_dedup ≥ 2` passes the tightened parse validator.
- `candidate_pool_size` (if reachable per G.1) is between 120 and 300.

### Stage 6 — Full pilot (24 trials, mandatory before committing to 360)

Run per §4.6 checks 1-8 with the expanded gates (B.4). Abort and re-plan if any gate fires. Otherwise, commit to the 360-trial full run.
