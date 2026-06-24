#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
BENCH_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
REPO_ROOT="$(cd -- "${BENCH_DIR}/../.." && pwd -P)"
PYTHON_BIN="${PYTHON:-python}"
RUNNER_PATH="${DTH_RUNNER_PATH:-${REPO_ROOT}/docs/benchmarks/hypothesis_generation_consistency/run_governor_production_activation_matrix.py}"
export PYTHONDONTWRITEBYTECODE=1

RUN=0
if [[ "${1:-}" == "--run" ]]; then
  RUN=1
  shift
fi

RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
SOURCE="${SOURCE:-/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/res_bc_drugtarget}"
DTH_MODEL="${DTH_MODEL:-qwen3.5:397b-cloud}"
DTH_PROVIDER="${DTH_PROVIDER:-ollama}"
DTH_PORTS="${DTH_PORTS:-11434}"
DTH_REPEATS="${DTH_REPEATS:-20}"
TIMEOUT_MINUTES="${TIMEOUT_MINUTES:-120}"
RUN_ROOT="${RUN_ROOT:-${BENCH_DIR}/live_runs/${RUN_ID}}"

export DRUG_TARGET_GRAPH_HYPOTHESIS_RETRY="${DRUG_TARGET_GRAPH_HYPOTHESIS_RETRY:-1}"
export DRUG_TARGET_HYPOTHESIS_MAX_QUALITY_RETRIES="${DRUG_TARGET_HYPOTHESIS_MAX_QUALITY_RETRIES:-3}"
export DRUG_TARGET_HYPOTHESIS_RETRY_TIMEOUT_SECONDS="${DRUG_TARGET_HYPOTHESIS_RETRY_TIMEOUT_SECONDS:-600}"
export DRUG_TARGET_ALLOW_HYPOTHESIS_RETRY_AFTER_BUDGET_ABORT="${DRUG_TARGET_ALLOW_HYPOTHESIS_RETRY_AFTER_BUDGET_ABORT:-1}"

run_condition() {
  local condition="$1"
  local skill_set="$2"
  local prompt_mode="$3"
  shift 3
  local output_root="${RUN_ROOT}/results/${condition}"
  local workspace_root="${RUN_ROOT}/workspaces/${condition}"

  "${PYTHON_BIN}" "${RUNNER_PATH}" \
    --source "${SOURCE}" \
    --output-root "${output_root}" \
    --workspace-root "${workspace_root}" \
    --disease "breast cancer" \
    --models "${DTH_MODEL}" \
    --provider "${DTH_PROVIDER}" \
    --ports "${DTH_PORTS}" \
    --modes middleware_only \
    --repeats-per-condition "${DTH_REPEATS}" \
    --hypothesis-skill-set "${skill_set}" \
    --hypothesis-writer-prompt-mode "${prompt_mode}" \
    --host-hypothesis-fallback off \
    --timeout-minutes "${TIMEOUT_MINUTES}" \
    --wait-for-completion \
    "$@"
}

echo "[live] run id: ${RUN_ID}"
echo "[live] output root: ${RUN_ROOT}"
echo "[live] source: ${SOURCE}"
echo "[live] model/provider/ports: ${DTH_MODEL} / ${DTH_PROVIDER} / ${DTH_PORTS}"
echo "[live] repeats per condition: ${DTH_REPEATS}"
echo "[live] native retry max: ${DRUG_TARGET_HYPOTHESIS_MAX_QUALITY_RETRIES}"
echo "[live] runner: ${RUNNER_PATH}"
echo

cd "${REPO_ROOT}"

if [[ ! -f "${RUNNER_PATH}" ]]; then
  echo "[live] missing runner: ${RUNNER_PATH}" >&2
  echo "[live] set DTH_RUNNER_PATH to a checkout containing run_governor_production_activation_matrix.py" >&2
  exit 2
fi

if [[ "${RUN}" != "1" ]]; then
  echo "[live] dry run previews:"
  run_condition DTH_no dth_none operational_contract_minimal --dry-run
  run_condition DTH_yes dth_only operational_contract_minimal_plus_dth --dry-run
  echo
  echo "[live] re-run with --run to execute."
  exit 0
fi

mkdir -p "${RUN_ROOT}"
echo "[live] executing DTH_no"
run_condition DTH_no dth_none operational_contract_minimal
echo "[live] executing DTH_yes"
run_condition DTH_yes dth_only operational_contract_minimal_plus_dth
echo "[live] complete: ${RUN_ROOT}"
