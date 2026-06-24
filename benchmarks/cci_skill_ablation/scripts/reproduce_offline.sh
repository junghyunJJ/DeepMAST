#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
BENCH_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
REPO_ROOT="$(cd -- "${BENCH_DIR}/../.." && pwd -P)"
PYTHON_BIN="${PYTHON:-python}"
export PYTHONDONTWRITEBYTECODE=1

TRIALS="${TRIALS:-${BENCH_DIR}/results/full_cci_v2_D_guide_trials.jsonl}"
STEM="${STEM:-full_cci_v2_D_guide}"

cd "${REPO_ROOT}"

echo "[offline] regenerating summary"
"${PYTHON_BIN}" "${BENCH_DIR}/scripts/summarize_trials.py" \
  --trials "${TRIALS}" \
  --stem "${STEM}" \
  --results-dir "${BENCH_DIR}/results"

echo "[offline] regenerating figure tables"
"${PYTHON_BIN}" "${BENCH_DIR}/scripts/export_figure_data.py" \
  --trials "${TRIALS}" \
  --output-dir "${BENCH_DIR}/results/figure_tables"

if [[ "${SKIP_R:-0}" == "1" ]]; then
  echo "[offline] SKIP_R=1; skipped figure regeneration"
  exit 0
fi

echo "[offline] regenerating figures"
Rscript "${BENCH_DIR}/scripts/figure_table3_results.R" "${BENCH_DIR}"
Rscript "${BENCH_DIR}/scripts/s_figure_table3_results.R" "${BENCH_DIR}"

echo "[offline] wrote:"
echo "  ${BENCH_DIR}/results/${STEM}_summary.json"
echo "  ${BENCH_DIR}/results/${STEM}_results.md"
echo "  ${BENCH_DIR}/results/figure_tables"
echo "  ${BENCH_DIR}/figures"
