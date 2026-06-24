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
STEM="${STEM:-live_cci_v2_${RUN_ID}}"
CASES="${CASES:-${BENCH_DIR}/inputs/cci_full_cases.json}"
RESULTS_DIR="${RESULTS_DIR:-${BENCH_DIR}/live_runs/${RUN_ID}/results}"
CCI_BENCHMARK_MODELS="${CCI_BENCHMARK_MODELS:-openai:gpt-5.4-nano}"
CCI_BENCHMARK_REPEATS="${CCI_BENCHMARK_REPEATS:-5}"
CCI_JUDGE_MODELS="${CCI_JUDGE_MODELS:-openai:gpt-5.4,claude:claude-sonnet-4-20250514}"

cmd=(
  "${PYTHON_BIN}"
  "${BENCH_DIR}/scripts/run_cci_skill_ablation.py"
  --stem "${STEM}"
  --cases "${CASES}"
  --results-dir "${RESULTS_DIR}"
  "$@"
)

echo "[live] run id: ${RUN_ID}"
echo "[live] output root: ${RESULTS_DIR}"
echo "[live] generator models: ${CCI_BENCHMARK_MODELS}"
echo "[live] repeats per case/condition: ${CCI_BENCHMARK_REPEATS}"
echo "[live] judge models: ${CCI_JUDGE_MODELS}"
echo "[live] required credentials: OPENAI_API_KEY for OpenAI models; ANTHROPIC_API_KEY when Claude judging is enabled"
echo

if [[ "${RUN}" != "1" ]]; then
  echo "[live] dry run. Re-run with --run to execute:"
  printf '  CCI_BENCHMARK_MODELS=%q CCI_BENCHMARK_REPEATS=%q CCI_JUDGE_MODELS=%q ' \
    "${CCI_BENCHMARK_MODELS}" "${CCI_BENCHMARK_REPEATS}" "${CCI_JUDGE_MODELS}"
  printf '%q ' "${cmd[@]}"
  printf '\n'
  exit 0
fi

cd "${REPO_ROOT}"
mkdir -p "${RESULTS_DIR}"

echo "[live] executing benchmark"
CCI_BENCHMARK_MODELS="${CCI_BENCHMARK_MODELS}" \
CCI_BENCHMARK_REPEATS="${CCI_BENCHMARK_REPEATS}" \
CCI_JUDGE_MODELS="${CCI_JUDGE_MODELS}" \
  "${cmd[@]}"

echo
echo "[live] complete: ${RESULTS_DIR}"
