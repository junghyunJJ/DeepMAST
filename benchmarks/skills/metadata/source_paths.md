# Source Paths

This benchmark bundle was assembled from the local skill-activation benchmark artifacts without modifying the original source files.

Original source paths:

- Benchmark implementation:
  `docs/benchmarks/skills/benchmark_skill_harness.py`
- Expanded model-aware runner:
  `docs/benchmarks/skills/compare_expanded.py`
- Final qwen3.5:122b reference results:
  `docs/benchmarks/skills/results/compare_expanded_qwen3_5_122b*`
- qwen3.5:35b scaling-check results:
  `benchmarks/skills/live_runs/skills_35b_bounded_20260608T215223Z/results/compare_expanded_qwen3_5_35b*`
- Reference report:
  `docs/benchmarks/skills/skill_load_harness_benchmark_122b.md`
- Figures and figure scripts:
  `docs/benchmarks/skills/figures/`

Path normalization:

- Scripts were moved under `benchmarks/skills/scripts/`.
- Final reference outputs were moved under `benchmarks/skills/results/`.
- The qwen3.5:35b scaling-check outputs were copied from the bounded live run into `benchmarks/skills/results/`.
- Figure outputs and source Mermaid diagrams were moved under `benchmarks/skills/figures/`.
- Live reruns write to `benchmarks/skills/live_runs/` instead of overwriting committed reference results.
- Script imports and output paths were normalized to the public bundle location.

Files intentionally excluded:

- `docs/benchmarks/skills/old/`
- `.DS_Store`, `.Rhistory`, and `__pycache__/`
- Duplicate `fig_skill_harness copy.R`
- Presentation-only `.pptx` output
