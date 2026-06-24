#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
BENCH_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
REPO_ROOT="$(cd -- "${BENCH_DIR}/../.." && pwd -P)"
PYTHON_BIN="${PYTHON:-python}"
export PYTHONDONTWRITEBYTECODE=1

cd "${REPO_ROOT}"

echo "[offline] validating committed SGCP benchmark artifacts"
"${PYTHON_BIN}" "${BENCH_DIR}/scripts/validate_reference_artifacts.py"

if [[ "${SKIP_R:-0}" == "1" ]]; then
  echo "[offline] SKIP_R=1; skipped figure regeneration"
  exit 0
fi

echo "[offline] regenerating summary tables and figure from committed raw JSONL"
Rscript "${BENCH_DIR}/scripts/plot_sgcp_main_figure.R" "${BENCH_DIR}"

echo "[offline] wrote:"
echo "  ${BENCH_DIR}/results/sgcp_accuracy_recall_summary.csv"
echo "  ${BENCH_DIR}/results/sgcp_accuracy_recall_tests.csv"
echo "  ${BENCH_DIR}/results/sgcp_all_conditions_summary.csv"
echo "  ${BENCH_DIR}/results/sgcp_static_reference_tests.csv"
echo "  ${BENCH_DIR}/figures/sgcp_accuracy_recall_main.svg"
echo "  ${BENCH_DIR}/figures/sgcp_accuracy_recall_main.png"
