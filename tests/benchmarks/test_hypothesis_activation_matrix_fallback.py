from __future__ import annotations

from pathlib import Path

from docs.benchmarks.hypothesis_generation_consistency.run_governor_production_activation_matrix import (
    build_dry_run_payload,
    build_trial_plan,
)


def test_dry_run_payload_records_host_hypothesis_fallback_mode() -> None:
    trials = build_trial_plan(
        models=("qwen3.5:35b",),
        ports=(5000, 6000, 7000),
        modes=("middleware_only",),
        repeats_per_condition=9,
    )

    payload = build_dry_run_payload(
        source=Path("/tmp/source"),
        trials=trials,
        models=("qwen3.5:35b",),
        ports=(5000, 6000, 7000),
        modes=("middleware_only",),
        repeats_per_condition=9,
        timeout_minutes=120,
        wait_for_completion=True,
        hypothesis_skill_set="expanded6",
        hypothesis_scope_errors=[],
        host_hypothesis_fallback="recovery",
    )

    assert payload["host_hypothesis_fallback"] == "recovery"
    assert payload["trial_count"] == 9
    assert payload["per_port"] == {"5000": 3, "6000": 3, "7000": 3}
