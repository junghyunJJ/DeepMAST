from __future__ import annotations

from pathlib import Path

from docs.benchmarks.hypothesis_generation_consistency.run_activation_matrix import (
    aggregate_activation,
    trace_records_host_hypothesis_fallback,
)
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


def test_checkpoint_trace_fallback_marker_feeds_aggregate_counts() -> None:
    early_trace = """
[HOST-HYPOTHESIS-FIXUP] save_hypothesis_report completed with 3 hypotheses
[ACTIVATION-TRACE] checkpoint written
"""
    final_trace = """
TRACE COMPLETE
  host_hypothesis_fallback_used: YES
"""

    assert trace_records_host_hypothesis_fallback(early_trace) is True
    assert trace_records_host_hypothesis_fallback(final_trace) is True

    aggregate = aggregate_activation(
        [
            {
                "model": "qwen3.5:35b",
                "mode": "middleware_only",
                "returncode": 0,
                "activation_trace_valid": True,
                "activated_skill_names": [],
                "activated_added_skill_names": [],
                "validation": {"validation_passed": True},
                "host_hypothesis_fallback_used": trace_records_host_hypothesis_fallback(
                    early_trace
                ),
            },
            {
                "model": "qwen3.5:35b",
                "mode": "middleware_only",
                "returncode": 0,
                "activation_trace_valid": True,
                "activated_skill_names": [],
                "activated_added_skill_names": [],
                "validation": {"validation_passed": True},
                "host_hypothesis_fallback_used": False,
            },
        ]
    )

    summary = aggregate["groups"]["qwen3.5:35b::middleware_only"]
    assert summary["validation_passes"] == 2
    assert summary["fallback_assisted_successes"] == 1
    assert summary["writer_native_successes"] == 1
