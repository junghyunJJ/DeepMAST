# Rev 7 — Path A Gene-Enrichment Execution Plan

**Generated**: 2026-04-21
**Predecessor**: `REV6_4ERA_RESULTS.md` (v0/v1/v2/v3 baseline, 48-trial pilots per era).
**Approved plan file**: `/Users/jungj2/.claude/plans/buzzing-juggling-stardust.md`
**PREREGISTRATION addendum**: `PREREGISTRATION.md §16b` (2026-04-21 amendment, celltype primary unchanged).

---

## Part 1 — Why Rev 7

Rev 3 → Rev 6 (v0–v3) proved that **celltype primary is stable** at +19–20 pp Δ (strong model) in the strengthened window `[+12, +22]` across 4 SKILL.md versions. **Gene dimension has been saturated at 0 pp Δ across all 192 pilot trials** — a *mathematical* ceiling (2 genes per case × 60% threshold = 2/2 = 100% trivially). Running the pre-registered 1,080-trial full campaign without fixing this would re-produce the same null on gene Δ.

**Rev 7 change**: enrich each of the 30 cases to **15 genes** (STRING high-confidence PPI partners of ligand+receptor + KEGG `PATHWAY_TO_GENES` hubs), orthogonal to the LIANA spatial table. Raise `coverage_pass` gene floor 0.6 → 0.9. Rerun 3-mode pilot; confirm celltype primary stable and gene Δ becomes non-trivial.

**Fallback**: if the dry-run gate shows gene endpoint re-saturates at the 0.9 floor, pivot to Rev 6 celltype-only narrative (paper-shippable as-is per PREREGISTRATION §5).

---

## Part 2 — Execution Commands

### Environment

```bash
export OLLAMA_HOST=http://localhost:7000
export OLLAMA_BASE_URL=http://localhost:7000
cd /Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST
```

Same Ollama port `:7000` as Rev 4/5/6. Models: `qwen3.5:122b` (strong) + `qwen3.5:35b` (weak). Both `create_llm` kwargs preserved (`keep_alive=24h` hardcoded in `src/agents/model.py:127`).

### Path variables

```bash
BASE_R=docs/benchmarks/harness_x_model/results
BASE_W=docs/benchmarks/harness_x_model/workspaces
CASES=docs/benchmarks/cci_skill_ablation/cases/cci_full_cases_enriched_v1.json
```

### Step 0 — Sanity checks (one-time, ~5 s)

```bash
# Original cases file must not have been modified (sha256 pinned from Rev 6).
[[ "$(shasum -a 256 docs/benchmarks/cci_skill_ablation/cases/cci_full_cases.json | awk '{print $1}')" == \
   "4c29fa35df0c8605a3b4943c78776c4248499bc6b7374bd249264488ce28d82e" ]] && \
   echo "✓ cci_skill_ablation cases file unchanged (Table 3 preserved)"

# Enriched cases file must exist with 30 cases × 15 genes each.
python3 - <<'PY'
import json
from pathlib import Path
d = json.loads(Path("docs/benchmarks/cci_skill_ablation/cases/cci_full_cases_enriched_v1.json").read_text())
assert len(d) == 30
for c in d:
    assert len(c["enriched_genes"]) == 15
    assert c["input_bundle"]["ligand"] in c["enriched_genes"]
    assert c["input_bundle"]["receptor"] in c["enriched_genes"]
print("OK: 30 cases × 15 unique enriched_genes including L+R")
PY

# Regression tests must pass (45+ tests).
pytest tests/benchmarks/test_harness_x_model.py -q
```

### Step 1 — Create Rev 7 output directories

```bash
for suffix in dryrun b b_prime c; do
  mkdir -p $BASE_R/pilot_post_update_rev7_$suffix $BASE_W/pilot_post_update_rev7_$suffix
done
```

### Step 2 — Dry-run gate (mode=C, 1 case × 4 conditions, ~30 min)

Case choice: `cci_full_02_ANOS1_FGFR1` — `low_morans_known` with 1 pathway, representative of the harder stratum. If saturation breaks here, it will break for the rest.

```bash
python -u docs/benchmarks/harness_x_model/run_pilot.py \
  --mode C \
  --cases-file $CASES \
  --results-dir $BASE_R/pilot_post_update_rev7_dryrun \
  --workspace-root $BASE_W/pilot_post_update_rev7_dryrun \
  --per-category 1 --repeats 1 \
  --temperature 0.3 --seed 42 \
  --ignore-gates 2>&1 | tee $BASE_R/_rev7_dryrun.log
```

`--per-category 1` with 6 strata = 6 cases × 4 = 24 trials. To restrict to ANOS1_FGFR1 only: either patch the schedule temporarily, or accept the 6-case dry-run (~60-90 min instead of 30 min — still cheaper than a saturated full pilot). Recommend the 6-case variant for marginally better statistical signal.

**Decision** (write to `REV7_DRYRUN_DECISION.md`):
- Median strong_on gene coverage ≥ 95% AND median strong_off gene coverage ≥ 95% → **ABORT**, pivot to celltype-only fallback.
- `strong_on − strong_off` ≥ +5 pp AND both arms < 95% → **PROCEED** to Step 3.
- Otherwise → **REFINE** (extend to 2-case per-stratum mini-dry-run).

### Step 3 — Mode B pilot (null control, 48 trials, ~2 h)

```bash
python -u docs/benchmarks/harness_x_model/run_pilot.py \
  --mode B \
  --cases-file $CASES \
  --results-dir $BASE_R/pilot_post_update_rev7_b \
  --workspace-root $BASE_W/pilot_post_update_rev7_b \
  --per-category 2 --repeats 1 \
  --temperature 0.3 --seed 42 \
  --ignore-gates 2>&1 | tee $BASE_R/_rev7_b.log
```

**Must pass Gate Null** (`|Δ| < 3 pp` in both strong and weak) before firing B' / C. If Gate Null fails, STOP — input-design change may have contaminated the null control.

### Step 4 — Mode B' pilot (48 trials, ~2 h)

```bash
python -u docs/benchmarks/harness_x_model/run_pilot.py \
  --mode B_prime \
  --cases-file $CASES \
  --results-dir $BASE_R/pilot_post_update_rev7_b_prime \
  --workspace-root $BASE_W/pilot_post_update_rev7_b_prime \
  --per-category 2 --repeats 1 \
  --temperature 0.3 --seed 42 \
  --ignore-gates 2>&1 | tee $BASE_R/_rev7_b_prime.log
```

### Step 5 — Mode C pilot (48 trials, ~2-2.5 h)

```bash
python -u docs/benchmarks/harness_x_model/run_pilot.py \
  --mode C \
  --cases-file $CASES \
  --results-dir $BASE_R/pilot_post_update_rev7_c \
  --workspace-root $BASE_W/pilot_post_update_rev7_c \
  --per-category 2 --repeats 1 \
  --temperature 0.3 --seed 42 \
  --ignore-gates 2>&1 | tee $BASE_R/_rev7_c.log
```

### Step 6 — Pooled GLMM + TOST (R, ~30 s)

```bash
Rscript docs/benchmarks/harness_x_model/harness_x_model_glmm.R \
  --results-dir $BASE_R/pilot_post_update_rev7_b        --dataset-label B \
  --results-dir $BASE_R/pilot_post_update_rev7_b_prime  --dataset-label B_prime \
  --results-dir $BASE_R/pilot_post_update_rev7_c        --dataset-label C \
  --pooled --n-boot 1000 \
  --output $BASE_R/pooled_postupdate_v4.json
```

### Step 7 — 5-Era summary (Python, ~2 s)

```bash
python3 docs/benchmarks/harness_x_model/_rev7_summary.py
```

→ Writes `results/FINDINGS_5_ERAS_SUMMARY.md` (v0/v1/v2/v3/v4 comparison with both celltype primary and — new — gene dimension Δ).

### Step 8 — User review gate

**Halt before full run.** Review `FINDINGS_5_ERAS_SUMMARY.md` for:
1. Celltype Δ (v4) in `[+12, +22]` strengthened window → ✅ primary stable.
2. Gene Δ (v4) > 0 AND non-trivial → ✅ saturation broken (was 0 across v0–v3).
3. Gate Null for mode B passes → ✅ null integrity.
4. Pooled β v3 → v4 shift < ±5 pp → ✅ input-design change did not destabilize effect.

Only then proceed to Step 9.

### Step 9 — Full run (only after Step 8 approval, ~36-54 h Ollama)

```bash
for mode in B B_prime C; do
  python -u docs/benchmarks/harness_x_model/run_full.py \
    --mode $mode \
    --cases-file $CASES \
    --results-dir $BASE_R/full_rev7_$(echo $mode | tr 'A-Z_' 'a-z') \
    --workspace-root $BASE_W/full_rev7_$(echo $mode | tr 'A-Z_' 'a-z') \
    --max-cases 30 --repeats 3 \
    --temperature 0.3 --seed 42 2>&1 | tee $BASE_R/_rev7_full_$mode.log
done
```

30 cases × 4 conditions × 3 repeats = 360 trials per mode, 1,080 total. Pre-registered full campaign.

---

## Part 3 — Reproducibility Flags

- **Seed**: `--seed 42` on all pilots (identical to Rev 3–6)
- **Temperature**: `0.3` fixed
- **Ollama port**: `:7000` via `OLLAMA_HOST` + `OLLAMA_BASE_URL`
- **Cases file**: `cci_full_cases_enriched_v1.json`, sha256 captured per-trial in `cases_sha256` field (differs from v0–v3 hash by design)
- **Gate bypass**: `--ignore-gates` on pilots so analysis still runs if a gate fails; gate reports land in `pilot_gates.json` regardless
- **Provenance of enrichment**: `docs/benchmarks/cci_skill_ablation/cases/cci_full_cases_enriched_v1.provenance.json` (STRING version, KEGG snapshot, script SHA)

## Part 4 — File Manifest

| Path | Role |
|---|---|
| `enrich_cases_string_kegg.py` | One-shot enricher (already run, 40.8 s, Apr 21) |
| `cci_full_cases_enriched_v1.json` | Rev 7 input data (30 cases × 15 enriched_genes) |
| `cci_full_cases_enriched_v1.provenance.json` | Enrichment provenance sidecar |
| `common.py` | Rev 7 patched: `normalize_case` prefers enriched_genes; threshold 0.9 |
| `run_pilot.py` / `run_full.py` | Unchanged — accept the new cases file via `--cases-file` |
| `_rev7_summary.py` | 5-era summary script |
| `PREREGISTRATION.md §16b` | Rev 7 amendment |
| `results/pilot_post_update_rev7_{dryrun,b,b_prime,c}/` | Rev 7 pilot artifacts (generated at runtime) |
| `results/pooled_postupdate_v4.json` | Rev 7 pooled GLMM + TOST output |
| `results/FINDINGS_5_ERAS_SUMMARY.md` | Auto-generated 5-era comparison table |

---

## Part 5 — Parallel Multi-Port Full-Run Protocol

### Prerequisites

1. **3 Ollama instances** running on separate ports (e.g., 7000 / 7001 / 7002) — either on separate machines or one machine with GPU-partitioned Ollama instances.
2. **Both models loaded on each instance**: `qwen3.5:122b` (strong) + `qwen3.5:35b` (weak). Verify with `curl http://localhost:70XX/api/tags` on each port.
3. **Sufficient VRAM per instance**: ~80 GB for 122b + ~30 GB for 35b non-concurrent (`keep_alive` swap handled by `_ensure_ollama_model_ready`).
4. **`LANGSMITH_TRACING=false`** strongly recommended — Rev 7 pilot saw heavy 429 log noise from monthly-trace cap with tracing enabled.

### Execution commands

```bash
# Terminal / nohup session 1 — mode B on port 7000
nohup python -u docs/benchmarks/harness_x_model/run_full.py \
  --mode B --cases-file docs/benchmarks/cci_skill_ablation/cases/cci_full_cases_enriched_v1.json \
  --results-dir docs/benchmarks/harness_x_model/results/full_rev7_b \
  --workspace-root docs/benchmarks/harness_x_model/workspaces/full_rev7_b \
  --max-cases 30 --repeats 3 --ollama-host http://localhost:7000 \
  > docs/benchmarks/harness_x_model/results/_rev7_full_b.log 2>&1 &

# Terminal / nohup session 2 — mode B' on port 7001
nohup python -u docs/benchmarks/harness_x_model/run_full.py \
  --mode B_prime --cases-file docs/benchmarks/cci_skill_ablation/cases/cci_full_cases_enriched_v1.json \
  --results-dir docs/benchmarks/harness_x_model/results/full_rev7_b_prime \
  --workspace-root docs/benchmarks/harness_x_model/workspaces/full_rev7_b_prime \
  --max-cases 30 --repeats 3 --ollama-host http://localhost:7001 \
  > docs/benchmarks/harness_x_model/results/_rev7_full_b_prime.log 2>&1 &

# Terminal / nohup session 3 — mode C on port 7002
nohup python -u docs/benchmarks/harness_x_model/run_full.py \
  --mode C --cases-file docs/benchmarks/cci_skill_ablation/cases/cci_full_cases_enriched_v1.json \
  --results-dir docs/benchmarks/harness_x_model/results/full_rev7_c \
  --workspace-root docs/benchmarks/harness_x_model/workspaces/full_rev7_c \
  --max-cases 30 --repeats 3 --ollama-host http://localhost:7002 \
  > docs/benchmarks/harness_x_model/results/_rev7_full_c.log 2>&1 &
```

### Resume protocol

Re-run the same command; resume is automatic and independent per-mode. Each mode's `results_dir` is separate, so one mode crashing does not affect the others. The `load_completed_trial_indices` function skips completed (non-error) trials, and failed trials are retried.

### Robustness guarantee

If a SIGKILL occurs mid-`append_jsonl`, the final JSONL line may be truncated. Both `load_completed_trial_indices` and `load_trial_rows` now tolerate malformed JSON lines (logged at WARN, skipped). The truncated trial will not appear in the completed set and will be automatically retried on resume. This preserves the invariant that "resume = re-run the same command".

---

*End of Rev 7 execution plan.*
