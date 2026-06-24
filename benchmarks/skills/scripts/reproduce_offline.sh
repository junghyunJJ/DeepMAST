#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
BENCH_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
REPO_ROOT="$(cd -- "${BENCH_DIR}/../.." && pwd -P)"
PYTHON_BIN="${PYTHON:-python}"
export PYTHONDONTWRITEBYTECODE=1

cd "${REPO_ROOT}"

echo "[offline] validating committed 35B and 122B skill benchmark artifacts"
"${PYTHON_BIN}" "${BENCH_DIR}/scripts/validate_reference_artifacts.py"

if [[ "${SKIP_R:-0}" == "1" ]]; then
  echo "[offline] SKIP_R=1; skipped figure regeneration"
  exit 0
fi

echo "[offline] regenerating main figure from committed artifacts"
Rscript "${BENCH_DIR}/scripts/fig_skill_harness.R" "${BENCH_DIR}"

echo "[offline] wrote:"
echo "  ${BENCH_DIR}/figures/fig3.svg"
