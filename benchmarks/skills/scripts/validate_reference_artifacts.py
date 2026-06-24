from __future__ import annotations

import json
from pathlib import Path


BENCHMARK_DIR = Path(__file__).resolve().parents[1]
RESULTS_DIR = BENCHMARK_DIR / "results"
REFERENCE_MODELS = ("qwen3.5:35b", "qwen3.5:122b")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _count_jsonl(path: Path) -> int:
    count = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                json.loads(line)
                count += 1
    return count


def _safe_model(model: str) -> str:
    return model.replace(":", "_").replace(".", "_")


def _report_suffix(model: str) -> str:
    return model.split(":")[-1]


def _validate_model(model: str) -> None:
    safe_model = _safe_model(model)
    suffix = _report_suffix(model)
    aggregate = _read_json(RESULTS_DIR / f"compare_expanded_{safe_model}.json")
    stats = _read_json(RESULTS_DIR / f"compare_expanded_{safe_model}_stats.json")
    report = (RESULTS_DIR / f"skill_load_harness_benchmark_{suffix}.md").read_text(encoding="utf-8")
    trial_count = _count_jsonl(RESULTS_DIR / f"compare_expanded_{safe_model}_trials.jsonl")

    required_conditions = {"A_passive", "B_NO_hints"}
    if set(aggregate) != required_conditions:
        raise SystemExit(f"{model}: unexpected conditions: {sorted(aggregate)}")
    if trial_count != 280:
        raise SystemExit(f"{model}: expected 280 trial rows, found {trial_count}")
    if stats.get("n_decisions") != 420:
        raise SystemExit(f"{model}: expected 420 paired decisions, found {stats.get('n_decisions')}")
    if "SkillLoadHarness Benchmark" not in report:
        raise SystemExit(f"{model}: reference report title missing")

    f1_a = float(aggregate["A_passive"]["f1"])
    f1_b = float(aggregate["B_NO_hints"]["f1"])
    stats_f1_a = float(stats["f1_A"])
    stats_f1_b = float(stats["f1_B"])
    for label, value in {
        "aggregate A_passive F1": f1_a,
        "aggregate B_NO_hints F1": f1_b,
        "stats A_passive F1": stats_f1_a,
        "stats B_NO_hints F1": stats_f1_b,
    }.items():
        if not 0.0 <= value <= 1.0:
            raise SystemExit(f"{model}: {label} outside [0, 1]: {value}")

    print(f"[offline] validated {model} reference artifacts")
    print(f"[offline] trials={trial_count} paired_decisions={stats['n_decisions']}")
    print(f"[offline] aggregate_F1_A={f1_a:.3f} aggregate_F1_B={f1_b:.3f}")
    print(f"[offline] paired_F1_A={stats_f1_a:.3f} paired_F1_B={stats_f1_b:.3f} paired_dF1={stats['f1_diff']:+.3f}")


def main() -> None:
    for model in REFERENCE_MODELS:
        _validate_model(model)


if __name__ == "__main__":
    main()
