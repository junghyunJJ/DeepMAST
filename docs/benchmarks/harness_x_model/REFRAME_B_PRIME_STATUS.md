# Reframe B' → C — Execution Status

**Plan B'**: `docs/benchmarks/happy-cuddling-brooks.md`
**Plan C**: `~/.claude/plans/mighty-chasing-sparkle.md`

## Reframe B' (completed — null signal)
- Prompt-level kwarg strip: worked
- Tool schema leak: `search_literature_dynamic` schema exposed kwargs to BOTH arms
- Result: `used_lr_pair_queries=True` in all 48 trials, coverage=100%, GLMM variance=0
- **Valid negative finding**: skill's kwarg-guidance is not load-bearing; LLM discovers kwargs from tool schema

## Reframe C (in progress)
**Key changes**:
1. **Tool-schema isolation** (`_make_benchmark_search_tool`): OFF arm wrapper hides `enable_lr_pair_queries` + `coverage_weighted_sort` from schema, hardcoded to `False`
2. **L-R co-occurrence endpoint** (`lr_cooccurrence_count/rate`): non-saturating quality metric
3. **Ollama model unload** (`_ensure_ollama_model_ready`): prevents VRAM wedge
4. **SSL fix** (`SSL_CERT_FILE=/etc/pki/tls/certs/ca-bundle.crt`)

## Progress
- [x] S1-S4: Tool wrapper + L-R endpoint + 3 tests (19/19 pass)
- [x] S7-S8: Schema isolation verified
- [x] S9: B' pilot backed up to `pilot_reframe_b_prime/`
- [ ] S5: Extend analyzer
- [ ] S6: Update GLMM R script
- [ ] S10: 48-trial Reframe C pilot **RUNNING**
- [ ] S11: Analyze + GLMM + gates
- [ ] S12: FINDINGS_REFRAME_C.md
- [ ] S13: Architect verification

## Resume (if interrupted)
```bash
export OLLAMA_HOST=http://localhost:11436 OLLAMA_BASE_URL=http://localhost:11436 \
       SSL_CERT_FILE=/etc/pki/tls/certs/ca-bundle.crt REQUESTS_CA_BUNDLE=/etc/pki/tls/certs/ca-bundle.crt
.venv/bin/python -u docs/benchmarks/harness_x_model/run_pilot.py \
  --results-dir docs/benchmarks/harness_x_model/results/pilot \
  --workspace-root docs/benchmarks/harness_x_model/workspaces/pilot \
  --per-category 2 --repeats 1
```
