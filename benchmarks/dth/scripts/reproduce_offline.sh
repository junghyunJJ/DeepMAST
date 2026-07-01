#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
BENCH_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
REPO_ROOT="$(cd -- "${BENCH_DIR}/../.." && pwd -P)"
PYTHON_BIN="${PYTHON:-python}"
export PYTHONDONTWRITEBYTECODE=1

cd "${REPO_ROOT}"

echo "[offline] validating committed DTH artifacts"
"${PYTHON_BIN}" - <<'PY' "${BENCH_DIR}"
import json
import sys
from pathlib import Path

bench = Path(sys.argv[1])
summary = json.loads((bench / "results/cumulative_valid_only_summary_for_20each_target.json").read_text())
assert summary["status"] == "complete_20_valid_each_condition"
assert len(summary["valid_run_table"]) == 40
counts = {}
for row in summary["valid_run_table"]:
    counts[row["condition"]] = counts.get(row["condition"], 0) + 1
assert counts == {"DTH_yes": 20, "DTH_no": 20}, counts

expected_wins = {
    "dth_yes_no_gpt54_blind_summary.json": {"DTH_yes": 18, "DTH_no": 1, "tie": 1},
    "dth_yes_no_sonnet46_blind_summary.json": {"DTH_yes": 11, "DTH_no": 5, "tie": 4},
}
for name, wins in expected_wins.items():
    payload = json.loads((bench / "results/judge" / name).read_text())
    assert payload["metadata"]["status"] == "judged"
    assert payload["metadata"]["pair_count"] == 20
    assert payload["aggregate"]["wins"] == wins
print("[offline] artifact validation ok")
PY

if [[ "${SKIP_R:-0}" == "1" ]]; then
  echo "[offline] SKIP_R=1; skipped figure regeneration"
  exit 0
fi

echo "[offline] regenerating DTH figure tables and SVGs"
Rscript "${BENCH_DIR}/scripts/figure_dth_benchmark_results.R" "${BENCH_DIR}" "${BENCH_DIR}/results"

echo "[offline] wrote:"
echo "  ${BENCH_DIR}/results/figure_tables"
echo "  ${BENCH_DIR}/figures"
