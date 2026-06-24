#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
BENCH_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
PYTHON_BIN="${PYTHON:-python}"

RUN=0
if [[ "${1:-}" == "--run" ]]; then
  RUN=1
  shift
fi

RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
LIVE_ROOT="${LIVE_ROOT:-${BENCH_DIR}/live_runs/${RUN_ID}}"
RAW_DIR="${LIVE_ROOT}/results/raw"
SUMMARY_PATH="${LIVE_ROOT}/results/multihop_full_summary_${RUN_ID}.json"
RUNNER_ROOT="${LLMWIKI_RAG_DIR:-}"

if [[ -n "${RUNNER_ROOT}" ]]; then
  RUNNER="${RUNNER_ROOT}/benchmarking/scripts/run_multihop_promotion_full.py"
else
  RUNNER="\${LLMWIKI_RAG_DIR}/benchmarking/scripts/run_multihop_promotion_full.py"
fi

cmd=(
  "${PYTHON_BIN}"
  "${RUNNER}"
  --models "qwen35_35b_port7000,qwen35_122b_port6000"
  --conditions "wiki_off,wiki_static_refs,wiki_doc_routing"
  --results-dir "${RAW_DIR}"
  --summary-path "${SUMMARY_PATH}"
  --max-rewrites 3
  "$@"
)

echo "[live] run id: ${RUN_ID}"
echo "[live] output root: ${LIVE_ROOT}"
echo "[live] expects qwen3.5:35b at http://host.docker.internal:7000"
echo "[live] expects qwen3.5:122b at http://host.docker.internal:6000"
echo "[live] requires LLMWIKI_RAG_DIR pointing to the llmwiki_rag repository"
echo

if [[ "${RUN}" != "1" ]]; then
  echo "[live] dry run. Re-run with --run to execute:"
  if [[ -z "${RUNNER_ROOT}" ]]; then
    echo "  LLMWIKI_RAG_DIR=/path/to/llmwiki_rag ${PYTHON_BIN} \"\${LLMWIKI_RAG_DIR}/benchmarking/scripts/run_multihop_promotion_full.py\" --models qwen35_35b_port7000,qwen35_122b_port6000 --conditions wiki_off,wiki_static_refs,wiki_doc_routing --results-dir \"${RAW_DIR}\" --summary-path \"${SUMMARY_PATH}\" --max-rewrites 3"
  else
    printf '  '
    printf '%q ' "${cmd[@]}"
    printf '\n'
  fi
  echo "  Rscript ${BENCH_DIR}/scripts/plot_sgcp_main_figure.R ${LIVE_ROOT}"
  exit 0
fi

if [[ -z "${RUNNER_ROOT}" ]]; then
  echo "[live] LLMWIKI_RAG_DIR is required when using --run" >&2
  exit 2
fi
if [[ ! -f "${RUNNER}" ]]; then
  echo "[live] runner not found: ${RUNNER}" >&2
  exit 2
fi

mkdir -p "${RAW_DIR}"

echo "[live] executing benchmark"
"${cmd[@]}"

echo "[live] regenerating live summary tables and figure"
Rscript "${BENCH_DIR}/scripts/plot_sgcp_main_figure.R" "${LIVE_ROOT}"

echo
echo "[live] complete: ${LIVE_ROOT}"
