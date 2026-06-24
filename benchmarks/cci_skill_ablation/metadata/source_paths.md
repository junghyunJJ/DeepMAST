# Source Paths

This benchmark bundle was assembled from the local CCI skill-ablation artifacts and normalized into a public, repo-relative layout.

Original source directories:

- Benchmark implementation and figures:
  `docs/benchmarks/cci_skill_ablation/`
- Benchmark input cases:
  `docs/benchmarks/cci_skill_ablation/cases/`
- Full 4-condition judged results:
  `docs/benchmarks/cci_skill_ablation/results/full_cci_v2_D_guide_*`

Path normalization:

- Benchmark scripts were moved under `benchmarks/cci_skill_ablation/scripts/`.
- Runtime inputs were moved from `cases/` to `inputs/`.
- Local absolute paths and `setwd(...)` calls were removed from figure scripts.
- Offline reproduction now regenerates summary markdown and figure CSV tables from committed judged trials.
- Live reruns write to `benchmarks/cci_skill_ablation/live_runs/` instead of overwriting committed reference results.

Files intentionally excluded from the public bundle:

- `.DS_Store`, `.Rhistory`, and `__pycache__/`
- Pilot and intermediate result variants not needed to reproduce the reference 4-condition benchmark
- Enriched and negative-control case variants used by other benchmark families
