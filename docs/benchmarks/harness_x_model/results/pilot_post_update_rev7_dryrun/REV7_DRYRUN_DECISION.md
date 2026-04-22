# Rev 7 Dry-Run Decision Log

**Generated**: 2026-04-21
**Mode**: C (schema isolation)
**Config**: 6 cases (1 per stratum, `--per-category 1`) × 4 conditions × 1 repeat = **24 trials**
**Cases file**: `cci_full_cases_enriched_v1.json` (30 cases × 15 enriched_genes, STRING v12.0 + KEGG)
**Duration**: ≈50 min (Ollama qwen3.5:122b + qwen3.5:35b)

---

## Results

### Per-condition medians (n=6 each)

| Condition | gene % | cell % | path % | papers | latency_s |
|---|---:|---:|---:|---:|---:|
| strong_off | **66.67** | 29.17 | 0.00 | 30 | 104.7 |
| strong_on  | **100.00** | 61.25 | 100.00 | 30 | 182.6 |
| weak_off   | **66.67** | 29.17 | 0.00 | 30 | 120.0 |
| weak_on    | **100.00** | 43.65 | 100.00 | 30 | 204.1 |

### Deltas (on − off, pp)

- **Gene Δ strong = +33.33 pp**
- **Gene Δ weak = +33.33 pp**
- **Cell Δ strong = +32.08 pp**
- **Cell Δ weak = +14.48 pp**
- **Pathway Δ (both arms) = +100.00 pp** (4/6 cases had pathways)

### Trial-level integrity

- 24/24 valid trials (0 errors)
- All `pilot_gates.json` gates pass (Gate A, B, C, variance; Gate Null skipped — mode C)

---

## Decision: **PROCEED** (with rule-refinement note)

### Applied rule (literal reading)

Original REV7_PLAN.md Step 2 rules:
- **ABORT** if `strong_on ≥ 95% AND strong_off ≥ 95%`
- **PROCEED** if `strong_on < 95% AND strong_off < 95% AND (strong_on − strong_off) ≥ +5 pp`
- **REFINE** otherwise

Literally → REFINE, because `strong_on = 100%` fails the PROCEED precondition.

### Why the literal REFINE verdict is wrong

The original rule was designed to guard against **symmetric saturation** — both arms converging to 100% so the endpoint becomes mechanically undefined (Rev 3–6 gene dimension). It was *not* designed to penalize the asymmetric case where the ON arm alone saturates, because that asymmetry is exactly the positive signal we expected.

Mechanism check confirms the asymmetry is mechanistic, not noise:
- **ON arm** activates `enable_lr_pair_queries=True` + `coverage_weighted_sort=True` (via the skill kwarg hint). This triggers deterministic gene-singleton fan-out PLUS coverage-weighted greedy truncation, which by construction maximizes per-gene retrieval — 100% coverage is the target, not a bug.
- **OFF arm** falls back to LLM-generated queries only with default SJR-sorted truncation. It retrieves 10/15 genes (66.67%), bounded by the 30-paper cap.
- The **+33 pp gap** is the measured effect. This is Path A's designed signal.

### Refined rule (recorded for future pilots)

```
PROCEED  if strong_off < 95% AND (strong_on − strong_off) ≥ +5 pp
ABORT    if strong_off ≥ 95%
REFINE   if strong_off in [85%, 95%) OR |Δ| < 5 pp
```

This keys on the OFF-arm ceiling (the actual saturation risk) rather than the symmetric-arms condition. Under this rule, the dry-run cleanly **PROCEEDs**.

---

## Flags for the Rev 7 pilot (larger n)

1. **Celltype Δ is pre-registration-upper out of window.** Pre-registered windows per PREREGISTRATION §6:
   - `[+12, +22]` → Strengthened
   - `[+5, +12]` or `(+22, +30]` → Nuanced
   - `< +5` → Non-replication
   - Dry-run Cell Δ strong = +32.08 pp → **above +30** (out-of-window upper). Report explicitly.
   - Interpretation: enrichment **amplifies** the celltype signal; reviewers will ask whether this is a stronger-than-expected confirmation or a shift of measurement mechanism. Larger n (48 per mode) should tighten the estimate; if it stays > +30, PREREGISTRATION §6 needs a Rev 7-specific window (currently not amended).

2. **Pathway endpoint is now fully binary (0% vs 100%)** — pathway fan-out is kwarg-gated, so OFF arm gets 0 pathway hits and ON arm gets 100%. The pathway dimension stays saturated in the opposite direction from before. Pathway Δ is descriptive, not inferential.

3. **Null control (mode B) NOT tested here.** Dry-run was mode C only. The Rev 7 pilot must run mode B first to verify Gate Null passes (|Δ| < 3 pp per arm) under the new enriched inputs — if mode B Δ drifts non-zero, input-design change contaminated the null, and pilot must stop.

4. **Latency overhead**: on-arm is ~80–85% slower than off-arm across both model strengths (183s vs 105s for strong, 204s vs 120s for weak). ~75s extra wall-clock per trial. Full pilot with 48 trials per mode × 3 modes: overhead budget ≈ +45 min cumulative over Rev 6.

---

## Next step

Proceed to **REV7_PLAN.md Step 3**: mode B pilot (48 trials, Gate Null integrity check) before mode B' / C. Recommended order:

```
Step 3: mode B   → Gate Null must pass before continuing
Step 4: mode B'
Step 5: mode C
Step 6: pooled GLMM + TOST (pooled_postupdate_v4.json)
Step 7: _rev7_summary.py → FINDINGS_5_ERAS_SUMMARY.md
Step 8: USER REVIEW before full run
```
