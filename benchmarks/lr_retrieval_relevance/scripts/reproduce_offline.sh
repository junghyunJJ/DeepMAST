#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
BENCH_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
REPO_ROOT="$(cd -- "${BENCH_DIR}/../.." && pwd -P)"

cd "${REPO_ROOT}"

echo "[offline] regenerating coverage tables"
python "${BENCH_DIR}/scripts/export_coverage_figure_data.py" \
  --results-dir "${BENCH_DIR}/results"

mkdir -p "${BENCH_DIR}/results/coverage_tables"
cp "${BENCH_DIR}/results/manuscript/tables/coverage_percase.csv" \
   "${BENCH_DIR}/results/coverage_tables/coverage_percase.csv"
cp "${BENCH_DIR}/results/manuscript/tables/coverage_group_summary.csv" \
   "${BENCH_DIR}/results/coverage_tables/coverage_group_summary.csv"
cp "${BENCH_DIR}/results/manuscript/tables/coverage_sig.csv" \
   "${BENCH_DIR}/results/coverage_tables/coverage_sig.csv"

if [[ "${SKIP_R:-0}" == "1" ]]; then
  echo "[offline] SKIP_R=1; skipped figure regeneration"
  exit 0
fi

echo "[offline] regenerating coverage figure"
Rscript "${BENCH_DIR}/scripts/coverage_figure.R" "${BENCH_DIR}/results"

mkdir -p "${BENCH_DIR}/figures"
cp "${BENCH_DIR}/results/manuscript/figures/fig_retrieval_coverage.svg" \
   "${BENCH_DIR}/figures/fig_retrieval_coverage.svg"
cp "${BENCH_DIR}/results/manuscript/figures/fig_retrieval_coverage.png" \
   "${BENCH_DIR}/figures/fig_retrieval_coverage.png"

echo "[offline] wrote:"
echo "  ${BENCH_DIR}/results/coverage_tables"
echo "  ${BENCH_DIR}/figures"
