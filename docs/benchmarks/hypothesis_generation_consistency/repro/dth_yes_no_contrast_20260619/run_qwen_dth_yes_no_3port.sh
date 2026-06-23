#!/usr/bin/env bash
set -euo pipefail

MODEL="${1:-qwen3.5:35b}"
REPEATS="${2:-3}"
PORTS="${PORTS:-5000,6000,7000}"
SOURCE="${SOURCE:-/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/res_bc_drugtarget}"
DISEASE="${DISEASE:-breast cancer}"
TIMEOUT_MINUTES="${TIMEOUT_MINUTES:-120}"
DTH_NO_SKILL_SET="${DTH_NO_SKILL_SET:-dth_none}"
DTH_YES_SKILL_SET="${DTH_YES_SKILL_SET:-dth_only}"
DTH_NO_PROMPT_MODE="${DTH_NO_PROMPT_MODE:-operational_contract_minimal}"
DTH_YES_PROMPT_MODE="${DTH_YES_PROMPT_MODE:-operational_contract_minimal_plus_dth}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../.." && pwd)"
cd "$REPO_ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

export DRUG_TARGET_GRAPH_HYPOTHESIS_RETRY="${DRUG_TARGET_GRAPH_HYPOTHESIS_RETRY:-1}"
export DRUG_TARGET_HYPOTHESIS_MAX_QUALITY_RETRIES="${DRUG_TARGET_HYPOTHESIS_MAX_QUALITY_RETRIES:-3}"
export DRUG_TARGET_HYPOTHESIS_RETRY_TIMEOUT_SECONDS="${DRUG_TARGET_HYPOTHESIS_RETRY_TIMEOUT_SECONDS:-600}"
export DRUG_TARGET_ALLOW_HYPOTHESIS_RETRY_AFTER_BUDGET_ABORT="${DRUG_TARGET_ALLOW_HYPOTHESIS_RETRY_AFTER_BUDGET_ABORT:-1}"
export DRUG_TARGET_ENABLE_HOST_HYPOTHESIS_FALLBACK=""

RUNNER="docs/benchmarks/hypothesis_generation_consistency/run_governor_production_activation_matrix.py"
MODEL_SLUG="$(printf '%s' "$MODEL" | tr ':/' '__' | tr -cd 'A-Za-z0-9_.-')"
STAMP="${STAMP:-dth_yes_no_reuse_${MODEL_SLUG}_${REPEATS}each_$(date +%Y%m%d_%H%M%S)}"
OUT_BASE="${OUT_BASE:-docs/benchmarks/hypothesis_generation_consistency/results/${STAMP}}"
WS_BASE="${WS_BASE:-docs/benchmarks/hypothesis_generation_consistency/workspaces/${STAMP}}"

mkdir -p "$OUT_BASE" "$WS_BASE"

if [[ ! -d "$SOURCE" ]]; then
  echo "SOURCE MISSING: $SOURCE" >&2
  exit 2
fi

python "$RUNNER" --help | grep -q "$DTH_NO_PROMPT_MODE"
python "$RUNNER" --help | grep -q "$DTH_YES_PROMPT_MODE"

python - "$MODEL" "$PORTS" <<'PY'
import json
import sys
from docs.benchmarks.hypothesis_generation_consistency.run_activation_matrix import unload_model_from_ports

requested_model = sys.argv[1]
ports = tuple(int(port) for port in sys.argv[2].split(",") if port.strip())
models = [requested_model, "qwen3.5:35b", "qwen3.5:122b"]
seen = set()
events = []
for model in models:
    if model in seen:
        continue
    seen.add(model)
    events.extend(unload_model_from_ports(model, ports))
print(json.dumps(events, indent=2, ensure_ascii=False))
PY

run_condition() {
  local condition="$1"
  local skill_set="$2"
  local prompt_mode="$3"
  local out="$OUT_BASE/$condition"
  local ws="$WS_BASE/$condition"
  mkdir -p "$out" "$ws"

  python "$RUNNER" \
    --source "$SOURCE" \
    --output-root "$out" \
    --workspace-root "$ws" \
    --disease "$DISEASE" \
    --models "$MODEL" \
    --ports "$PORTS" \
    --modes middleware_only \
    --repeats-per-condition "$REPEATS" \
    --hypothesis-skill-set "$skill_set" \
    --hypothesis-writer-prompt-mode "$prompt_mode" \
    --host-hypothesis-fallback off \
    --timeout-minutes "$TIMEOUT_MINUTES" \
    --wait-for-completion \
    --dry-run > "$out/dry_run.json"

  python - "$out/dry_run.json" "$MODEL" "$PORTS" "$REPEATS" "$skill_set" "$prompt_mode" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
expected_model = sys.argv[2]
expected_ports = [int(port) for port in sys.argv[3].split(",") if port.strip()]
expected_repeats = int(sys.argv[4])
expected_skill_set = sys.argv[5]
expected_prompt_mode = sys.argv[6]

checks = {
    "trial_count": payload.get("trial_count") == expected_repeats,
    "models": payload.get("models") == [expected_model],
    "ports": payload.get("ports") == expected_ports,
    "unique_physical_ports": payload.get("unique_physical_ports") == expected_ports,
    "modes": payload.get("modes") == ["middleware_only"],
    "repeats_per_condition": payload.get("repeats_per_condition") == expected_repeats,
    "hypothesis_skill_set": payload.get("hypothesis_skill_set") == expected_skill_set,
    "hypothesis_writer_prompt_mode": payload.get("hypothesis_writer_prompt_mode") == expected_prompt_mode,
    "host_hypothesis_fallback": payload.get("host_hypothesis_fallback") == "off",
    "hypothesis_scope_errors": payload.get("hypothesis_scope_errors") == [],
}
failed = [name for name, passed in checks.items() if not passed]
if failed:
    raise SystemExit(f"dry-run failed {failed}: {path}")
PY

  python "$RUNNER" \
    --source "$SOURCE" \
    --output-root "$out" \
    --workspace-root "$ws" \
    --disease "$DISEASE" \
    --models "$MODEL" \
    --ports "$PORTS" \
    --modes middleware_only \
    --repeats-per-condition "$REPEATS" \
    --hypothesis-skill-set "$skill_set" \
    --hypothesis-writer-prompt-mode "$prompt_mode" \
    --host-hypothesis-fallback off \
    --timeout-minutes "$TIMEOUT_MINUTES" \
    --wait-for-completion
}

run_condition "DTH_no" "$DTH_NO_SKILL_SET" "$DTH_NO_PROMPT_MODE"
run_condition "DTH_yes" "$DTH_YES_SKILL_SET" "$DTH_YES_PROMPT_MODE"

python - "$OUT_BASE" <<'PY'
import json
import sys
from pathlib import Path

out_base = Path(sys.argv[1])
summary = {"output_root": str(out_base), "conditions": {}}
for condition in ("DTH_no", "DTH_yes"):
    result_path = out_base / condition / "benchmark_results.json"
    state_path = out_base / condition / "runner_state.json"
    condition_summary = {"result_path": str(result_path), "runner_state_path": str(state_path)}
    if result_path.exists():
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        trials = payload.get("trials", [])
        condition_summary["trial_count"] = len(trials)
        condition_summary["returncode_0"] = sum(1 for row in trials if row.get("returncode") == 0)
        condition_summary["validation_passed"] = sum(
            1
            for row in trials
            if isinstance(row.get("validation"), dict)
            and row["validation"].get("validation_passed") is True
        )
        condition_summary["host_hypothesis_fallback_used"] = sum(
            1 for row in trials if row.get("host_hypothesis_fallback_used")
        )
    if state_path.exists():
        condition_summary["runner_state"] = json.loads(state_path.read_text(encoding="utf-8"))
    summary["conditions"][condition] = condition_summary

(out_base / "dth_yes_no_reuse_summary.json").write_text(
    json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)
print(json.dumps(summary, indent=2, ensure_ascii=False))
PY

python - "$MODEL" "$PORTS" <<'PY'
import json
import sys
from docs.benchmarks.hypothesis_generation_consistency.run_activation_matrix import unload_model_from_ports

model = sys.argv[1]
ports = tuple(int(port) for port in sys.argv[2].split(",") if port.strip())
events = unload_model_from_ports(model, ports)
print(json.dumps(events, indent=2, ensure_ascii=False))
PY

echo "Done: $OUT_BASE"
