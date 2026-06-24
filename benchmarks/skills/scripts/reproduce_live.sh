#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
BENCH_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
REPO_ROOT="$(cd -- "${BENCH_DIR}/../.." && pwd -P)"
PYTHON_BIN="${PYTHON:-python}"
export PYTHONDONTWRITEBYTECODE=1

RUN=0
if [[ "${1:-}" == "--run" ]]; then
  RUN=1
  shift
fi

RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
SCALING_MODEL="${SCALING_MODEL:-qwen3.5:122b}"
RESULTS_DIR="${RESULTS_DIR:-${BENCH_DIR}/live_runs/${RUN_ID}/results}"

cmd=(
  "${PYTHON_BIN}"
  "${BENCH_DIR}/scripts/compare_expanded.py"
  "$@"
)

echo "[live] run id: ${RUN_ID}"
echo "[live] output root: ${RESULTS_DIR}"
echo "[live] model: SCALING_MODEL=${SCALING_MODEL}"
echo "[live] expected Ollama availability for ${SCALING_MODEL}"
echo

if [[ "${RUN}" != "1" ]]; then
  echo "[live] dry run. Re-run with --run to execute:"
  printf '  OLLAMA_BASE_URL=%q SCALING_MODEL=%q SKILLS_BENCHMARK_RESULTS_DIR=%q ' "${OLLAMA_BASE_URL:-}" "${SCALING_MODEL}" "${RESULTS_DIR}"
  printf '%q ' "${cmd[@]}"
  printf '\n'
  exit 0
fi

cd "${REPO_ROOT}"
mkdir -p "${RESULTS_DIR}"

echo "[live] executing benchmark"
SCALING_MODEL="${SCALING_MODEL}" \
SKILLS_BENCHMARK_RESULTS_DIR="${RESULTS_DIR}" \
  "${cmd[@]}"

echo
echo "[live] complete: ${RESULTS_DIR}"
