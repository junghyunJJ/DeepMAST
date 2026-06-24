#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
BENCH_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
REPO_ROOT="$(cd -- "${BENCH_DIR}/../.." && pwd -P)"

RUN=0
if [[ "${1:-}" == "--run" ]]; then
  RUN=1
  shift
fi

RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
CASE_LIMIT="${CASE_LIMIT:-0}"
REPEATS="${REPEATS:-1}"
CONDITIONS="${CONDITIONS:-weak_on,weak_off,strong_on,strong_off}"
TRIAL_TIMEOUT_S="${TRIAL_TIMEOUT_S:-1200}"
SCORE_MODE="${SCORE_MODE:-live}"
JUDGE_MODEL="${JUDGE_MODEL:-gpt-5.4}"
TEMPERATURE="${TEMPERATURE:-0}"
COVERAGE_MODEL="${COVERAGE_MODEL:-qwen3.5:122b}"
COVERAGE_OLLAMA_HOST="${COVERAGE_OLLAMA_HOST:-http://localhost:6000}"
COVERAGE_WORKERS="${COVERAGE_WORKERS:-4}"

LIVE_ROOT="${BENCH_DIR}/live_runs/${RUN_ID}"
RETRIEVAL_DIR="${LIVE_ROOT}/retrieval"
WORKSPACE_ROOT="${LIVE_ROOT}/workspaces"
CONTENT_DIR="${LIVE_ROOT}/content_utility"

cmds=(
  "python scripts/benchmarks/run_cci_searcher_skill_onoff_benchmark.py --cases ${BENCH_DIR}/inputs/cci_full_cases.json --output-dir ${RETRIEVAL_DIR} --workspace-root ${WORKSPACE_ROOT} --case-limit ${CASE_LIMIT} --repeats ${REPEATS} --conditions ${CONDITIONS} --mode retrieval_only --trial-timeout-s ${TRIAL_TIMEOUT_S} --resume"
  "python scripts/benchmarks/run_cci_content_utility_from_skill_onoff.py --skill-results-dir ${RETRIEVAL_DIR} --cases ${BENCH_DIR}/inputs/cci_full_cases.json --output-root ${CONTENT_DIR} --score-mode ${SCORE_MODE} --model ${JUDGE_MODEL} --temperature ${TEMPERATURE} --overwrite"
  "python scripts/benchmarks/score_gene_coverage_llm.py --runner-rows ${CONTENT_DIR}/converted_runner_rows.jsonl --output ${CONTENT_DIR}/gene_coverage_labels_122b.jsonl --ollama-host ${COVERAGE_OLLAMA_HOST} --model ${COVERAGE_MODEL} --workers ${COVERAGE_WORKERS}"
  "python scripts/benchmarks/score_entity_coverage_llm.py --runner-rows ${CONTENT_DIR}/converted_runner_rows.jsonl --output ${CONTENT_DIR}/entity_coverage_labels_122b.jsonl --ollama-host ${COVERAGE_OLLAMA_HOST} --model ${COVERAGE_MODEL} --workers ${COVERAGE_WORKERS}"
  "python ${BENCH_DIR}/scripts/export_coverage_figure_data.py --results-dir ${CONTENT_DIR}"
  "Rscript ${BENCH_DIR}/scripts/coverage_figure.R ${CONTENT_DIR}"
)

echo "[live] run id: ${RUN_ID}"
echo "[live] output root: ${LIVE_ROOT}"
echo "[live] qwen3.5:35b expected at http://localhost:7000"
echo "[live] qwen3.5:122b expected at http://localhost:6000"
echo "[live] SCORE_MODE=${SCORE_MODE}; JUDGE_MODEL=${JUDGE_MODEL}; TEMPERATURE=${TEMPERATURE}"
echo

if [[ "${RUN}" != "1" ]]; then
  echo "[live] dry run. Re-run with --run to execute:"
  printf '  %s\n' "${cmds[@]}"
  exit 0
fi

cd "${REPO_ROOT}"
mkdir -p "${LIVE_ROOT}"

for cmd in "${cmds[@]}"; do
  echo
  echo "[live] $cmd"
  eval "$cmd"
done

echo
echo "[live] complete: ${LIVE_ROOT}"
