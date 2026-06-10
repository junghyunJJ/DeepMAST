from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import time
from argparse import Namespace
from pathlib import Path

import pytest

from docs.benchmarks.hypothesis_generation_consistency.analysis import (
    aggregate_trial_rows,
    jaccard,
    summarize_report,
)
from docs.benchmarks.hypothesis_generation_consistency.compare_skill_sets import (
    compare_pair,
    evidence_fingerprint,
    main as compare_skill_sets_main,
    render_markdown,
)
from docs.benchmarks.hypothesis_generation_consistency.run_benchmark import (
    CURRENT4_HYPOTHESIS_WRITER_SKILLS,
    EXPANDED6_HYPOTHESIS_WRITER_SKILLS,
    HYPOTHESIS_WRITER_RESUME_MESSAGE,
    build_hypothesis_writer_resume_instruction,
    clean_hypothesis_benchmark_workspace,
    check_hypothesis_scope,
    check_hypothesis_scope_untraced,
    find_forbidden_hypothesis_artifacts,
    parse_args,
    prepare_trial_workspace,
    resolve_trial_sources,
    resolve_hypothesis_writer_skill_names,
    validate_trial_output,
)


def test_hypothesis_generation_consistency_package_imports() -> None:
    module = importlib.import_module(
        "docs.benchmarks.hypothesis_generation_consistency"
    )
    assert module.__name__ == "docs.benchmarks.hypothesis_generation_consistency"


def test_current4_and_expanded6_skill_sets_are_explicit() -> None:
    assert CURRENT4_HYPOTHESIS_WRITER_SKILLS == (
        "drug-target-hypothesis",
        "opentargets-database",
        "gwas-database",
        "chembl-database",
    )
    assert EXPANDED6_HYPOTHESIS_WRITER_SKILLS == (
        "drug-target-hypothesis",
        "opentargets-database",
        "gwas-database",
        "chembl-database",
        "compare-census-gene-pair-by-cell-type",
        "string-database",
    )


def test_resolve_hypothesis_writer_skill_names_returns_tuple_copy() -> None:
    first = resolve_hypothesis_writer_skill_names("expanded6")
    second = resolve_hypothesis_writer_skill_names("expanded6")

    assert first == EXPANDED6_HYPOTHESIS_WRITER_SKILLS
    assert first is not second


def test_resolve_hypothesis_writer_skill_names_rejects_unknown_name() -> None:
    with pytest.raises(ValueError, match="unknown skill set"):
        resolve_hypothesis_writer_skill_names("expanded")


def test_skill_name_from_read_skill_path_handles_project_relative_path() -> None:
    from docs.benchmarks.hypothesis_generation_consistency.activation_trace import (
        skill_name_from_read_skill_path,
    )

    assert (
        skill_name_from_read_skill_path("skills/string-database/SKILL.md")
        == "string-database"
    )
    assert (
        skill_name_from_read_skill_path(
            "/tmp/worktree/skills/compare-census-gene-pair-by-cell-type/SKILL.md"
        )
        == "compare-census-gene-pair-by-cell-type"
    )
    assert skill_name_from_read_skill_path("evidence/stage3_ICAM1.json") is None


def test_extract_hypothesis_writer_read_skill_calls_ignores_other_nodes() -> None:
    from langchain_core.messages import AIMessage

    from docs.benchmarks.hypothesis_generation_consistency.activation_trace import (
        extract_read_skill_file_calls,
    )

    message = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "read_skill_file",
                "args": {"skill_path": "skills/string-database/SKILL.md"},
                "id": "call_1",
            }
        ],
    )

    exposed = ("drug-target-hypothesis", "string-database")
    assert extract_read_skill_file_calls(
        node_path="orchestrator > hypothesis_writer",
        node_name="hypothesis_writer",
        node_data={"messages": [message]},
        exposed_skill_names=exposed,
        scope="hypothesis_writer",
    ) == [
        {
            "skill_name": "string-database",
            "skill_path": "skills/string-database/SKILL.md",
            "tool_call_id": "call_1",
            "node_path": "orchestrator > hypothesis_writer",
            "node_name": "hypothesis_writer",
            "registered": True,
        }
    ]

    assert extract_read_skill_file_calls(
        node_path="orchestrator > finalize_report",
        node_name="finalize_report",
        node_data={"messages": [message]},
        exposed_skill_names=exposed,
        scope="hypothesis_writer",
    ) == []


def test_extract_hypothesis_writer_read_skill_file_calls_keeps_unscoped_strict_by_default() -> None:
    from langchain_core.messages import AIMessage

    from docs.benchmarks.hypothesis_generation_consistency.activation_trace import (
        extract_hypothesis_writer_read_skill_file_calls,
    )

    message = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "read_skill_file",
                "args": {"skill_path": "skills/drug-target-hypothesis/SKILL.md"},
                "id": "call_1",
            }
        ],
    )

    assert (
        extract_hypothesis_writer_read_skill_file_calls(
            node_path="tools:3af27d",
            node_name="model",
            node_data={"messages": [message]},
            exposed_skill_names=("drug-target-hypothesis",),
        )
        == []
    )


def test_extract_hypothesis_writer_read_skill_file_calls_can_infer_registered_unscoped_call() -> None:
    from langchain_core.messages import AIMessage

    from docs.benchmarks.hypothesis_generation_consistency.activation_trace import (
        extract_hypothesis_writer_read_skill_file_calls,
    )

    message = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "read_skill_file",
                "args": {"skill_path": "skills/drug-target-hypothesis/SKILL.md"},
                "id": "call_1",
            },
            {
                "name": "read_skill_file",
                "args": {"skill_path": "skills/unregistered-skill/SKILL.md"},
                "id": "call_2",
            },
        ],
    )

    assert extract_hypothesis_writer_read_skill_file_calls(
        node_path="tools:3af27d",
        node_name="model",
        node_data={"messages": [message]},
        exposed_skill_names=("drug-target-hypothesis",),
        infer_unscoped_registered=True,
    ) == [
        {
            "skill_name": "drug-target-hypothesis",
            "skill_path": "skills/drug-target-hypothesis/SKILL.md",
            "tool_call_id": "call_1",
            "node_path": "tools:3af27d",
            "node_name": "model",
            "registered": True,
        }
    ]


def test_run_drug_target_traced_parse_args_accepts_activation_flags() -> None:
    from scripts.run_drug_target_traced import parse_args as parse_traced_args

    args = parse_traced_args(
        [
            "--data-dir",
            "/tmp/example",
            "--skip-evidence-assessor",
            "--hypothesis-skill-set",
            "expanded6",
            "--skill-activation-mode",
            "middleware_only",
            "--activation-trace-json",
            "/tmp/example/activation_trace.json",
        ]
    )

    assert args.hypothesis_skill_set == "expanded6"
    assert args.skill_activation_mode == "middleware_only"
    assert args.activation_trace_json == "/tmp/example/activation_trace.json"


def test_run_drug_target_traced_writes_activation_trace_without_final_report(
    tmp_path: Path,
) -> None:
    from scripts.run_drug_target_traced import write_activation_trace_json

    output_path = tmp_path / "activation_trace.json"
    trace_log_path = tmp_path / "trace.log"
    writer_calls = [
        {
            "skill_name": "drug-target-hypothesis",
            "skill_path": "skills/drug-target-hypothesis/SKILL.md",
            "tool_call_id": "call_1",
            "node_path": "orchestrator > hypothesis_writer",
            "node_name": "hypothesis_writer",
            "registered": True,
        },
        {
            "skill_name": "string-database",
            "skill_path": "skills/string-database/SKILL.md",
            "tool_call_id": "call_2",
            "node_path": "orchestrator > hypothesis_writer",
            "node_name": "hypothesis_writer",
            "registered": True,
        },
    ]

    written_path = write_activation_trace_json(
        activation_trace_path=output_path,
        exposed_skill_names=EXPANDED6_HYPOTHESIS_WRITER_SKILLS,
        hypothesis_writer_read_skill_calls=writer_calls,
        all_read_skill_calls=writer_calls,
        skill_set="expanded6",
        skill_activation_mode="middleware_only",
        model="qwen3.5:35b",
        ollama_base_url="http://localhost:5000",
        data_dir=tmp_path,
        trace_log_path=trace_log_path,
        report_finalized=False,
    )

    assert written_path == output_path
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["report_finalized"] is False
    assert payload["skill_set"] == "expanded6"
    assert payload["skill_activation_mode"] == "middleware_only"
    assert payload["model"] == "qwen3.5:35b"
    assert payload["ollama_base_url"] == "http://localhost:5000"
    assert payload["data_dir"] == str(tmp_path)
    assert payload["trace_log"] == str(trace_log_path)
    assert payload["activated_skill_names"] == [
        "drug-target-hypothesis",
        "string-database",
    ]
    assert payload["activated_added_skill_names"] == ["string-database"]


def test_run_drug_target_traced_writes_checkpoint_to_default_trace_path(
    tmp_path: Path,
) -> None:
    from scripts.run_drug_target_traced import (
        resolve_activation_trace_path,
        write_activation_trace_checkpoint,
    )

    data_dir = tmp_path / "workspace"
    trace_log_path = tmp_path / "trace.log"
    timestamp = "20260610_120000"
    writer_calls = [
        {
            "skill_name": "string-database",
            "skill_path": "skills/string-database/SKILL.md",
            "tool_call_id": "call_1",
            "node_path": "orchestrator > hypothesis_writer",
            "node_name": "hypothesis_writer",
            "registered": True,
        },
    ]

    activation_trace_path = resolve_activation_trace_path(
        None,
        data_dir=data_dir,
        timestamp=timestamp,
    )
    written_path = write_activation_trace_checkpoint(
        activation_trace_path=activation_trace_path,
        exposed_skill_names=EXPANDED6_HYPOTHESIS_WRITER_SKILLS,
        hypothesis_writer_read_skill_calls=writer_calls,
        all_read_skill_calls=writer_calls,
        skill_set="expanded6",
        skill_activation_mode="middleware_plus_activator",
        model="qwen3.5:122b",
        ollama_base_url="http://localhost:7000",
        data_dir=data_dir,
        trace_log_path=trace_log_path,
    )

    assert written_path == data_dir / f"activation_trace_{timestamp}.json"
    payload = json.loads(written_path.read_text(encoding="utf-8"))
    assert payload["report_finalized"] is False
    assert payload["activated_skill_names"] == ["string-database"]
    assert payload["activated_added_skill_names"] == ["string-database"]
    trace_log = trace_log_path.read_text(encoding="utf-8")
    assert "[ACTIVATION-TRACE-CHECKPOINT]" in trace_log
    assert "before hypothesis quality/finalize" in trace_log


def test_activation_matrix_default_plan_has_12_trials() -> None:
    from docs.benchmarks.hypothesis_generation_consistency.run_activation_matrix import (
        build_trial_plan,
    )

    trials = build_trial_plan(
        models=("qwen3.5:35b", "qwen3.5:122b"),
        ports=(5000, 6000, 7000),
        modes=("middleware_only", "middleware_plus_activator"),
    )

    assert len(trials) == 12
    assert trials[0] == {
        "model": "qwen3.5:35b",
        "port": 5000,
        "mode": "middleware_only",
        "run_id": "qwen35b_middleware_only_port5000",
    }
    assert trials[-1] == {
        "model": "qwen3.5:122b",
        "port": 7000,
        "mode": "middleware_plus_activator",
        "run_id": "qwen122b_middleware_plus_activator_port7000",
    }


def test_activation_matrix_unload_request_payload() -> None:
    from docs.benchmarks.hypothesis_generation_consistency.run_activation_matrix import (
        build_ollama_unload_payload,
    )

    assert build_ollama_unload_payload("qwen3.5:122b") == {
        "model": "qwen3.5:122b",
        "keep_alive": 0,
    }


def test_activation_matrix_parse_args_defaults_to_monitored_mode() -> None:
    from docs.benchmarks.hypothesis_generation_consistency.run_activation_matrix import (
        DEFAULT_ACTIVATION_TRACE_GRACE_SECONDS,
        parse_args as parse_activation_matrix_args,
    )

    args = parse_activation_matrix_args([])
    assert args.wait_for_completion is False
    assert args.activation_trace_grace_seconds == DEFAULT_ACTIVATION_TRACE_GRACE_SECONDS

    wait_args = parse_activation_matrix_args(
        ["--wait-for-completion", "--activation-trace-grace-seconds", "0.25"]
    )
    assert wait_args.wait_for_completion is True
    assert wait_args.activation_trace_grace_seconds == 0.25


def test_monitored_activation_command_stops_after_trace_and_writes_logs(
    tmp_path: Path,
) -> None:
    from docs.benchmarks.hypothesis_generation_consistency.run_activation_matrix import (
        run_monitored_activation_command,
    )

    activation_trace_path = tmp_path / "activation_trace.json"
    stdout_path = tmp_path / "stdout.log"
    stderr_path = tmp_path / "stderr.log"
    child_code = """
import json
import sys
import time
from pathlib import Path

trace_path = Path(sys.argv[1])
print("child stdout before trace", flush=True)
print("child stderr before trace", file=sys.stderr, flush=True)
trace_path.write_text(
    json.dumps({"activated_skill_names": ["drug-target-hypothesis"]}),
    encoding="utf-8",
)
time.sleep(30)
"""

    started = time.monotonic()
    returncode, error = run_monitored_activation_command(
        command=[sys.executable, "-c", child_code, str(activation_trace_path)],
        cwd=tmp_path,
        env=os.environ.copy(),
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        timeout_seconds=10,
        activation_trace_path=activation_trace_path,
        activation_trace_grace_seconds=0.1,
        poll_interval_seconds=0.01,
    )
    elapsed_s = time.monotonic() - started

    assert elapsed_s < 3
    assert returncode is not None
    assert error == f"stopped_after_activation_trace: {activation_trace_path}"
    assert json.loads(activation_trace_path.read_text(encoding="utf-8")) == {
        "activated_skill_names": ["drug-target-hypothesis"]
    }
    assert "child stdout before trace" in stdout_path.read_text(encoding="utf-8")
    assert "child stderr before trace" in stderr_path.read_text(encoding="utf-8")


def test_monitored_activation_command_terminates_descendant_processes(
    tmp_path: Path,
) -> None:
    if not hasattr(os, "killpg"):
        pytest.skip("process-group termination is POSIX-specific")

    from docs.benchmarks.hypothesis_generation_consistency.run_activation_matrix import (
        run_monitored_activation_command,
    )

    activation_trace_path = tmp_path / "activation_trace.json"
    grandchild_pid_path = tmp_path / "grandchild.pid"
    stdout_path = tmp_path / "stdout.log"
    stderr_path = tmp_path / "stderr.log"
    child_code = """
import json
import subprocess
import sys
import time
from pathlib import Path

trace_path = Path(sys.argv[1])
pid_path = Path(sys.argv[2])
grandchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
pid_path.write_text(str(grandchild.pid), encoding="utf-8")
trace_path.write_text(json.dumps({"activated_skill_names": ["drug-target-hypothesis"]}), encoding="utf-8")
time.sleep(30)
"""

    returncode, error = run_monitored_activation_command(
        command=[
            sys.executable,
            "-c",
            child_code,
            str(activation_trace_path),
            str(grandchild_pid_path),
        ],
        cwd=tmp_path,
        env=os.environ.copy(),
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        timeout_seconds=10,
        activation_trace_path=activation_trace_path,
        activation_trace_grace_seconds=0.1,
        poll_interval_seconds=0.01,
    )

    grandchild_pid = int(grandchild_pid_path.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and _pid_exists(grandchild_pid):
        time.sleep(0.05)

    assert returncode is not None
    assert error == f"stopped_after_activation_trace: {activation_trace_path}"
    assert not _pid_exists(grandchild_pid)


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def test_activation_matrix_marks_missing_trace_invalid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from docs.benchmarks.hypothesis_generation_consistency import run_activation_matrix

    def fake_copy_source_workspace(
        source: Path,
        destination: Path,
        *,
        force: bool,
    ) -> None:
        destination.mkdir(parents=True)

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, stdout="", stderr="")

    monkeypatch.setattr(
        run_activation_matrix,
        "copy_source_workspace",
        fake_copy_source_workspace,
    )
    monkeypatch.setattr(run_activation_matrix.subprocess, "run", fake_run)
    monkeypatch.setattr(
        run_activation_matrix,
        "validate_trial_output",
        lambda run_id, workspace, *, elapsed_s, error: {
            "run_id": run_id,
            "validation_passed": True,
            "error": error,
        },
    )

    row = run_activation_matrix.run_one_trial(
        trial={
            "model": "qwen3.5:35b",
            "port": 5000,
            "mode": "middleware_only",
            "run_id": "run_missing_trace",
        },
        source=tmp_path / "source",
        workspace_root=tmp_path / "workspaces",
        output_root=tmp_path,
        disease="pulmonary fibrosis",
        timeout_minutes=1,
        force=True,
    )

    assert row["activation_trace_valid"] is False
    assert "activation trace missing" in row["activation_trace_error"]
    assert row["activated_skill_names"] == []
    assert row["activated_added_skill_names"] == []


def test_activation_matrix_marks_malformed_trace_invalid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from docs.benchmarks.hypothesis_generation_consistency import run_activation_matrix

    def fake_copy_source_workspace(
        source: Path,
        destination: Path,
        *,
        force: bool,
    ) -> None:
        destination.mkdir(parents=True)

    def fake_run(command, *args, **kwargs):
        trace_path = Path(command[command.index("--activation-trace-json") + 1])
        trace_path.write_text("{not json", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(
        run_activation_matrix,
        "copy_source_workspace",
        fake_copy_source_workspace,
    )
    monkeypatch.setattr(run_activation_matrix.subprocess, "run", fake_run)
    monkeypatch.setattr(
        run_activation_matrix,
        "validate_trial_output",
        lambda run_id, workspace, *, elapsed_s, error: {
            "run_id": run_id,
            "validation_passed": True,
            "error": error,
        },
    )

    row = run_activation_matrix.run_one_trial(
        trial={
            "model": "qwen3.5:35b",
            "port": 5000,
            "mode": "middleware_only",
            "run_id": "run_malformed_trace",
        },
        source=tmp_path / "source",
        workspace_root=tmp_path / "workspaces",
        output_root=tmp_path,
        disease="pulmonary fibrosis",
        timeout_minutes=1,
        force=True,
    )

    assert row["activation_trace_valid"] is False
    assert "JSONDecodeError" in row["activation_trace_error"]
    assert row["activated_skill_names"] == []


def test_activation_matrix_aggregate_excludes_invalid_trace_denominator() -> None:
    from docs.benchmarks.hypothesis_generation_consistency.run_activation_matrix import (
        aggregate_activation,
    )

    aggregate = aggregate_activation(
        [
            {
                "model": "qwen3.5:35b",
                "mode": "middleware_only",
                "returncode": 0,
                "validation": {"validation_passed": True},
                "activation_trace_valid": True,
                "activated_skill_names": ["string-database"],
                "activated_added_skill_names": ["string-database"],
            },
            {
                "model": "qwen3.5:35b",
                "mode": "middleware_only",
                "returncode": 0,
                "validation": {"validation_passed": True},
                "activation_trace_valid": False,
                "activated_skill_names": [],
                "activated_added_skill_names": [],
            },
        ]
    )

    group = aggregate["groups"]["qwen3.5:35b::middleware_only"]
    assert group["runs"] == 2
    assert group["successes"] == 2
    assert group["validation_passes"] == 2
    assert group["activation_trace_checkpoint_runs"] == 0
    assert group["activation_trace_valid_runs"] == 1
    assert group["activation_trace_invalid_runs"] == 1
    assert group["mean_activation_count"] == 1.0
    assert group["skill_activation_rates"] == {"string-database": 1.0}
    assert group["added_skill_activation_rates"] == {"string-database": 1.0}


def test_activation_matrix_aggregate_counts_checkpoint_runs_separately() -> None:
    from docs.benchmarks.hypothesis_generation_consistency.run_activation_matrix import (
        aggregate_activation,
    )

    aggregate = aggregate_activation(
        [
            {
                "model": "qwen3.5:35b",
                "mode": "middleware_only",
                "returncode": -15,
                "completion_mode": "activation_trace_checkpoint",
                "validation": {"validation_passed": False},
                "activation_trace_valid": True,
                "activated_skill_names": ["drug-target-hypothesis"],
                "activated_added_skill_names": [],
            }
        ]
    )

    group = aggregate["groups"]["qwen3.5:35b::middleware_only"]
    assert group["runs"] == 1
    assert group["successes"] == 0
    assert group["validation_passes"] == 0
    assert group["activation_trace_checkpoint_runs"] == 1
    assert group["activation_trace_valid_runs"] == 1
    assert group["skill_activation_rates"] == {"drug-target-hypothesis": 1.0}


def test_activation_matrix_unloads_active_model_when_trial_raises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from docs.benchmarks.hypothesis_generation_consistency import run_activation_matrix

    source = tmp_path / "source"
    source.mkdir()
    unload_calls: list[tuple[str, tuple[int, ...]]] = []

    monkeypatch.setattr(
        run_activation_matrix,
        "parse_args",
        lambda: Namespace(
            source=str(source),
            output_root=str(tmp_path / "out"),
            workspace_root=str(tmp_path / "workspaces"),
            disease="pulmonary fibrosis",
            timeout_minutes=1,
            force=True,
        ),
    )
    monkeypatch.setattr(
        run_activation_matrix,
        "build_trial_plan",
        lambda *, models, ports, modes: [
            {
                "model": "qwen3.5:35b",
                "port": 5000,
                "mode": "middleware_only",
                "run_id": "run_raises",
            }
        ],
    )

    def fake_run_one_trial(**kwargs):
        raise RuntimeError("trial failed")

    def fake_unload_model_from_ports(model: str, ports) -> list[dict]:
        unload_calls.append((model, tuple(ports)))
        return [{"model": model, "ports": list(ports), "ok": True}]

    monkeypatch.setattr(run_activation_matrix, "run_one_trial", fake_run_one_trial)
    monkeypatch.setattr(
        run_activation_matrix,
        "unload_model_from_ports",
        fake_unload_model_from_ports,
    )

    with pytest.raises(RuntimeError, match="trial failed"):
        run_activation_matrix.main()

    assert unload_calls == [("qwen3.5:35b", (5000, 6000, 7000))]
    payload = json.loads((tmp_path / "out" / "benchmark_results.json").read_text())
    assert payload["runner_error"] == "RuntimeError: trial failed"
    assert payload["unload_events"] == [
        {"model": "qwen3.5:35b", "ports": [5000, 6000, 7000], "ok": True}
    ]


def test_activation_matrix_direct_script_help_works() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "docs/benchmarks/hypothesis_generation_consistency/run_activation_matrix.py",
            "--help",
        ],
        check=False,
        capture_output=True,
        encoding="utf-8",
    )

    assert completed.returncode == 0
    assert "Run expanded6 activation comparison" in completed.stdout


def test_activation_matrix_default_workspace_root_is_sibling_to_results(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from docs.benchmarks.hypothesis_generation_consistency import run_activation_matrix

    source = tmp_path / "source"
    source.mkdir()
    monkeypatch.setattr(run_activation_matrix, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(run_activation_matrix.time, "strftime", lambda _: "expanded6_activation_fixed")
    monkeypatch.setattr(
        run_activation_matrix,
        "parse_args",
        lambda: Namespace(
            source=str(source),
            output_root="",
            workspace_root="",
            disease="pulmonary fibrosis",
            timeout_minutes=1,
            force=True,
        ),
    )
    monkeypatch.setattr(
        run_activation_matrix,
        "build_trial_plan",
        lambda *, models, ports, modes: [],
    )

    assert run_activation_matrix.main() == 0

    assert (
        tmp_path
        / "docs/benchmarks/hypothesis_generation_consistency/results/expanded6_activation_fixed"
    ).is_dir()
    assert (
        tmp_path
        / "docs/benchmarks/hypothesis_generation_consistency/workspaces/expanded6_activation_fixed"
    ).is_dir()
    assert not (
        tmp_path
        / "docs/benchmarks/hypothesis_generation_consistency/results/workspaces/expanded6_activation_fixed"
    ).exists()


def _report_one() -> dict:
    return {
        "schema_version": "hypothesis_report.v2",
        "hypotheses": [
            {
                "title": "ICAM1 ITGB2 adhesion",
                "category": "Mechanism of Action",
                "core_claim": "ICAM1 and ITGB2 drive adhesion.",
                "evidence_references": ["stage1_ICAM1--ITGB2.json", "stage3_ICAM1.json"],
                "biological_entities": {"genes": ["ICAM1", "ITGB2"]},
            },
            {
                "title": "CD47 checkpoint",
                "category": "Therapeutic Strategy",
                "core_claim": "CD47 blockade changes clearance.",
                "evidence_references": ["stage1_THBS1--CD47.json", "stage3_CD47.json"],
                "biological_entities": {"genes": ["THBS1", "CD47"]},
            },
        ],
        "topn_coverage": {"covered": ["CD47", "ICAM1", "ITGB2"], "missing": []},
        "evidence_coverage_pct": 87.5,
        "prediction_grounding_summary": {"unverified": 0, "qualitative": 2},
    }


def _report_two() -> dict:
    report = _report_one()
    report["hypotheses"][0]["title"] = "ICAM1-ITGB2 adhesion signaling"
    report["hypotheses"][0]["core_claim"] = "ICAM1 with ITGB2 supports adhesion."
    return report


def _write_workspace_report(
    workspace: Path,
    report: dict,
    *,
    assessment_payload: dict | None = None,
) -> None:
    evidence = workspace / "evidence"
    evidence.mkdir(parents=True)
    (evidence / "assessment_results.json").write_text(
        json.dumps(assessment_payload or {"stage3_candidates": [{"gene": "ICAM1"}]}),
        encoding="utf-8",
    )
    (evidence / "stage1_filter_results.json").write_text(
        json.dumps({"results": []}),
        encoding="utf-8",
    )
    (evidence / "hypothesis_report.json").write_text(
        json.dumps(report),
        encoding="utf-8",
    )


def test_jaccard_handles_empty_and_nonempty_sets() -> None:
    assert jaccard(set(), set()) == 1.0
    assert jaccard({"A"}, set()) == 0.0
    assert jaccard({"A", "B"}, {"B", "C"}) == 1 / 3


def test_summarize_report_extracts_structure() -> None:
    summary = summarize_report(_report_one())
    assert summary["schema_version"] == "hypothesis_report.v2"
    assert summary["hypothesis_count"] == 2
    assert summary["category_counts"] == {
        "Mechanism of Action": 1,
        "Therapeutic Strategy": 1,
    }
    assert summary["covered_genes"] == ["CD47", "ICAM1", "ITGB2", "THBS1"]
    assert summary["evidence_refs"] == [
        "stage1_ICAM1--ITGB2.json",
        "stage1_THBS1--CD47.json",
        "stage3_CD47.json",
        "stage3_ICAM1.json",
    ]
    assert summary["topn_missing"] == []
    assert summary["unverified_numeric_predictions"] == 0


def test_aggregate_trial_rows_reports_pairwise_consistency() -> None:
    rows = [
        {
            "run_id": "run_01",
            "success": True,
            "validation_passed": True,
            "report_summary": summarize_report(_report_one()),
        },
        {
            "run_id": "run_02",
            "success": True,
            "validation_passed": True,
            "report_summary": summarize_report(_report_two()),
        },
    ]
    aggregate = aggregate_trial_rows(rows)
    assert aggregate["total_runs"] == 2
    assert aggregate["success_rate"] == 1.0
    assert aggregate["validation_pass_rate"] == 1.0
    assert aggregate["hypothesis_count_values"] == [2]
    assert aggregate["mean_pairwise_gene_jaccard"] == 1.0
    assert 0.0 < aggregate["mean_pairwise_title_similarity"] <= 1.0


def test_aggregate_trial_rows_handles_failed_row_without_summary() -> None:
    rows = [
        {
            "run_id": "run_01",
            "success": True,
            "validation_passed": True,
            "report_summary": summarize_report(_report_one()),
        },
        {
            "run_id": "run_failed",
            "success": False,
            "validation_passed": False,
            "report_summary": None,
        },
    ]

    aggregate = aggregate_trial_rows(rows)

    assert aggregate["total_runs"] == 2
    assert aggregate["successful_runs"] == 1
    assert aggregate["validation_passed_runs"] == 1
    assert aggregate["success_rate"] == 0.5
    assert aggregate["validation_pass_rate"] == 0.5
    assert aggregate["topn_missing_by_run"]["run_failed"] == []
    assert aggregate["unverified_numeric_predictions_by_run"]["run_failed"] is None


def test_aggregate_trial_rows_pairwise_metrics_use_validation_passed_runs() -> None:
    invalid_report = _report_two()
    invalid_report["hypotheses"][0]["title"] = "invalid divergent title"
    rows = [
        {
            "run_id": "run_valid",
            "success": True,
            "validation_passed": True,
            "report_summary": summarize_report(_report_one()),
        },
        {
            "run_id": "run_invalid",
            "success": True,
            "validation_passed": False,
            "report_summary": summarize_report(invalid_report),
        },
    ]

    aggregate = aggregate_trial_rows(rows)

    assert aggregate["successful_runs"] == 2
    assert aggregate["validation_passed_runs"] == 1
    assert aggregate["hypothesis_count_values"] == [2]
    assert aggregate["mean_pairwise_title_similarity"] is None
    assert aggregate["mean_pairwise_core_claim_similarity"] is None


def test_evidence_fingerprint_ignores_generated_hypothesis_report(
    tmp_path: Path,
) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    _write_workspace_report(left, _report_one())
    _write_workspace_report(right, _report_two())

    assert evidence_fingerprint(left) == evidence_fingerprint(right)


def test_evidence_fingerprint_detects_non_generated_evidence_mismatch(
    tmp_path: Path,
) -> None:
    current4 = tmp_path / "current4"
    expanded6 = tmp_path / "expanded6"
    _write_workspace_report(current4, _report_one())
    _write_workspace_report(
        expanded6,
        _report_one(),
        assessment_payload={"stage3_candidates": [{"gene": "MUC1"}]},
    )

    assert evidence_fingerprint(current4)["sha256"] != evidence_fingerprint(
        expanded6
    )["sha256"]

    row = compare_pair(
        {
            "case_id": "ipf_35b_run1",
            "current4": str(current4),
            "expanded6": str(expanded6),
        }
    )
    assert row["evidence_fingerprint_match"] is False


def test_compare_pair_reports_summary_deltas(tmp_path: Path) -> None:
    current4 = tmp_path / "current4"
    expanded6 = tmp_path / "expanded6"
    _write_workspace_report(current4, _report_one())
    _write_workspace_report(expanded6, _report_two())

    row = compare_pair(
        {
            "case_id": "ipf_35b_run1",
            "current4": str(current4),
            "expanded6": str(expanded6),
        }
    )

    assert row["case_id"] == "ipf_35b_run1"
    assert row["current4_hypothesis_count"] == 2
    assert row["expanded6_hypothesis_count"] == 2
    assert row["gene_jaccard"] == 1.0
    assert row["evidence_ref_jaccard"] == 1.0
    assert 0.0 < row["title_similarity"] <= 1.0
    assert row["evidence_fingerprint_match"] is True


def test_render_markdown_includes_pairwise_metrics() -> None:
    markdown = render_markdown(
        [
            {
                "case_id": "ipf_35b_run1",
                "current4_hypothesis_count": 5,
                "expanded6_hypothesis_count": 6,
                "current4_topn_missing": [],
                "expanded6_topn_missing": [],
                "gene_jaccard": 0.83,
                "evidence_ref_jaccard": 0.77,
                "title_similarity": 0.62,
                "core_claim_similarity": 0.58,
                "evidence_fingerprint_match": True,
            }
        ]
    )

    assert "# Current4 vs Expanded6 Hypothesis Comparison" in markdown
    assert "| ipf_35b_run1 | 5 | 6 | - | - | 0.83 | 0.77 | 0.62 | 0.58 | True |" in markdown


def test_compare_skill_sets_main_rejects_non_object_pairs_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pairs_json = tmp_path / "pairs.json"
    pairs_json.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "compare_skill_sets.py",
            "--pairs-json",
            str(pairs_json),
            "--output-dir",
            str(tmp_path / "out"),
        ],
    )

    with pytest.raises(
        SystemExit,
        match="--pairs-json must contain a JSON object with a non-empty 'pairs' list",
    ):
        compare_skill_sets_main()


def test_prepare_trial_workspace_copies_source_and_removes_stale_report(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    evidence = source / "evidence"
    evidence.mkdir(parents=True)
    (source / "lr_candidates.json").write_text("{}", encoding="utf-8")
    (evidence / "assessment_results.json").write_text(
        json.dumps({"stage3_candidates": [{"gene": "ICAM1"}]}),
        encoding="utf-8",
    )
    (evidence / "hypothesis_report.json").write_text(
        '{"stale": true}',
        encoding="utf-8",
    )

    workspace = prepare_trial_workspace(
        source,
        tmp_path / "workspaces",
        "run_01",
        force=True,
    )

    assert (workspace / "evidence" / "assessment_results.json").exists()
    assert not (workspace / "evidence" / "hypothesis_report.json").exists()


def test_prepare_trial_workspace_removes_prior_report_artifacts(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    evidence = source / "evidence"
    history = source / "conversation_history"
    large_tool_results = source / "large_tool_results"
    evidence.mkdir(parents=True)
    history.mkdir()
    large_tool_results.mkdir()
    (source / "lr_candidates.json").write_text("{}", encoding="utf-8")
    (source / "drug.md").write_text("stale drug report", encoding="utf-8")
    (source / "drug_report.html").write_text("<html></html>", encoding="utf-8")
    (source / "drug_report_render.json").write_text("{}", encoding="utf-8")
    (source / "drug_report_reference_card.json").write_text("{}", encoding="utf-8")
    (source / "part4_candidate_selection.json").write_text("{}", encoding="utf-8")
    (source / "part4_therapeutic_synthesis.md").write_text("stale", encoding="utf-8")
    (source / "report_expansions.json").write_text("{}", encoding="utf-8")
    (source / "target_assessment.json").write_text("{}", encoding="utf-8")
    (source / "hypothesis_report.json").write_text("{}", encoding="utf-8")
    (source / "hypothesis_report.tmp.json").write_text("{}", encoding="utf-8")
    (source / "Hypothesis_Report_Mixed.JSON").write_text("{}", encoding="utf-8")
    (source / "hypothesis_report_draft.json").write_text("{}", encoding="utf-8")
    (source / "report_data.json").write_text("{}", encoding="utf-8")
    (source / "report_validation.json").write_text("{}", encoding="utf-8")
    (source / "trace_20260528_113442.log").write_text("stale", encoding="utf-8")
    (source / "token_usage_20260528_113442.json").write_text("{}", encoding="utf-8")
    (history / "prior.md").write_text("old conversation", encoding="utf-8")
    (large_tool_results / "prior-tool-call").write_text(
        '{"data_dir": "res_ipf_ollama"}',
        encoding="utf-8",
    )
    (evidence / "assessment_results.json").write_text(
        json.dumps({"stage3_candidates": [{"gene": "ICAM1"}]}),
        encoding="utf-8",
    )
    (evidence / "hypothesis_report.json").write_text(
        json.dumps({"schema_version": "hypothesis_report.v2"}),
        encoding="utf-8",
    )
    (evidence / "hypothesis_report_last_rejection.json").write_text(
        "{}",
        encoding="utf-8",
    )
    (evidence / "hypothesis_draft.json").write_text("{}", encoding="utf-8")

    workspace = prepare_trial_workspace(
        source,
        tmp_path / "workspaces",
        "run_01",
        force=True,
    )

    assert (workspace / "lr_candidates.json").exists()
    assert (workspace / "evidence" / "assessment_results.json").exists()
    assert not (workspace / "drug.md").exists()
    assert not (workspace / "drug_report.html").exists()
    assert not (workspace / "drug_report_render.json").exists()
    assert not (workspace / "drug_report_reference_card.json").exists()
    assert not (workspace / "part4_candidate_selection.json").exists()
    assert not (workspace / "part4_therapeutic_synthesis.md").exists()
    assert not (workspace / "report_expansions.json").exists()
    assert not (workspace / "target_assessment.json").exists()
    assert not (workspace / "hypothesis_report.json").exists()
    assert not (workspace / "hypothesis_report.tmp.json").exists()
    assert not (workspace / "Hypothesis_Report_Mixed.JSON").exists()
    assert not (workspace / "hypothesis_report_draft.json").exists()
    assert not (workspace / "report_data.json").exists()
    assert not (workspace / "report_validation.json").exists()
    assert not (workspace / "trace_20260528_113442.log").exists()
    assert not (workspace / "token_usage_20260528_113442.json").exists()
    assert not (workspace / "conversation_history").exists()
    assert not (workspace / "large_tool_results").exists()
    assert not (workspace / "evidence" / "hypothesis_draft.json").exists()
    assert not (workspace / "evidence" / "hypothesis_report.json").exists()
    assert not (
        workspace / "evidence" / "hypothesis_report_last_rejection.json"
    ).exists()


def test_hypothesis_writer_resume_message_preserves_output_guards() -> None:
    assert "save_hypothesis_report" in HYPOTHESIS_WRITER_RESUME_MESSAGE
    assert "write_todos" in HYPOTHESIS_WRITER_RESUME_MESSAGE
    assert "write_file" in HYPOTHESIS_WRITER_RESUME_MESSAGE
    assert "/tmp" in HYPOTHESIS_WRITER_RESUME_MESSAGE
    assert "evidence/hypothesis_report.json" in HYPOTHESIS_WRITER_RESUME_MESSAGE
    assert "target-cell-depleted" in HYPOTHESIS_WRITER_RESUME_MESSAGE
    assert "gene-level/actionability-only" in HYPOTHESIS_WRITER_RESUME_MESSAGE
    assert "ot_<GENE>.json" in HYPOTHESIS_WRITER_RESUME_MESSAGE


def test_build_hypothesis_writer_resume_instruction_includes_exact_data_dir(
    tmp_path: Path,
) -> None:
    instruction = build_hypothesis_writer_resume_instruction(tmp_path)

    assert str(tmp_path) in instruction
    assert "target-cell-depleted" in instruction
    assert "save_hypothesis_report" in instruction


def test_clean_hypothesis_benchmark_workspace_reports_removed_artifacts(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "evidence").mkdir(parents=True)
    (workspace / "conversation_history").mkdir()
    (workspace / "large_tool_results").mkdir()
    (workspace / "drug.md").write_text("stale", encoding="utf-8")
    (workspace / "drug_report.html").write_text("<html></html>", encoding="utf-8")
    (workspace / "drug_report_reference_card.json").write_text("{}", encoding="utf-8")
    (workspace / "report_expansions.json").write_text("{}", encoding="utf-8")
    (workspace / "target_assessment.json").write_text("{}", encoding="utf-8")
    (workspace / "hypothesis_report.json").write_text("{}", encoding="utf-8")
    (workspace / "hypothesis_report.tmp.json").write_text("{}", encoding="utf-8")
    (workspace / "Hypothesis_Report_Mixed.JSON").write_text("{}", encoding="utf-8")
    (workspace / "hypothesis_report_draft.json").write_text("{}", encoding="utf-8")
    (workspace / "report_data.json").write_text("{}", encoding="utf-8")
    (workspace / "report_validation.json").write_text("{}", encoding="utf-8")
    (workspace / "token_usage_20260528_113442.json").write_text("{}", encoding="utf-8")
    (workspace / "trace_20260528_113442.log").write_text("stale", encoding="utf-8")
    (workspace / "conversation_history" / "prior.md").write_text(
        "old conversation",
        encoding="utf-8",
    )
    (workspace / "large_tool_results" / "old-tool-result").write_text(
        "stale payload",
        encoding="utf-8",
    )
    (workspace / "evidence" / "hypothesis_report.json").write_text(
        "{}",
        encoding="utf-8",
    )
    (workspace / "evidence" / "hypothesis_report_last_rejection.json").write_text(
        "{}",
        encoding="utf-8",
    )
    (workspace / "evidence" / "hypothesis_draft.json").write_text(
        "{}",
        encoding="utf-8",
    )

    removed = clean_hypothesis_benchmark_workspace(workspace)

    assert removed == [
        "drug.md",
        "drug_report.html",
        "drug_report_reference_card.json",
        "report_expansions.json",
        "target_assessment.json",
        "report_data.json",
        "report_validation.json",
        "evidence/hypothesis_draft.json",
        "evidence/hypothesis_report.json",
        "evidence/hypothesis_report_last_rejection.json",
        "conversation_history/",
        "large_tool_results/",
        "hypothesis_report.json",
        "hypothesis_report.tmp.json",
        "hypothesis_report_draft.json",
        "Hypothesis_Report_Mixed.JSON",
        "token_usage_20260528_113442.json",
        "trace_20260528_113442.log",
    ]
    assert not (workspace / "drug.md").exists()
    assert not (workspace / "drug_report.html").exists()
    assert not (workspace / "drug_report_reference_card.json").exists()
    assert not (workspace / "report_expansions.json").exists()
    assert not (workspace / "target_assessment.json").exists()
    assert not (workspace / "hypothesis_report.json").exists()
    assert not (workspace / "hypothesis_report.tmp.json").exists()
    assert not (workspace / "Hypothesis_Report_Mixed.JSON").exists()
    assert not (workspace / "hypothesis_report_draft.json").exists()
    assert not (workspace / "report_data.json").exists()
    assert not (workspace / "report_validation.json").exists()
    assert not (workspace / "conversation_history").exists()
    assert not (workspace / "large_tool_results").exists()
    assert not (workspace / "token_usage_20260528_113442.json").exists()
    assert not (workspace / "trace_20260528_113442.log").exists()
    assert not (workspace / "evidence" / "hypothesis_draft.json").exists()
    assert not (workspace / "evidence" / "hypothesis_report.json").exists()
    assert not (
        workspace / "evidence" / "hypothesis_report_last_rejection.json"
    ).exists()


@pytest.mark.parametrize("run_id", ["absolute", "../escaped"])
def test_prepare_trial_workspace_rejects_escaping_run_id_without_touching_target(
    tmp_path: Path,
    run_id: str,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    workspace_root = tmp_path / "workspaces"
    if run_id == "absolute":
        target = tmp_path / "absolute_escape"
        rejected_run_id = str(target)
    else:
        target = workspace_root / run_id
        rejected_run_id = run_id
    target.mkdir(parents=True)
    sentinel = target / "sentinel.txt"
    sentinel.write_text("preserved", encoding="utf-8")

    with pytest.raises(ValueError):
        prepare_trial_workspace(source, workspace_root, rejected_run_id, force=True)

    assert sentinel.read_text(encoding="utf-8") == "preserved"


def test_check_hypothesis_scope_reports_loader_errors(tmp_path: Path) -> None:
    source = tmp_path / "source"
    evidence = source / "evidence"
    evidence.mkdir(parents=True)
    (evidence / "assessment_results.json").write_text(
        json.dumps({"stage3_candidates": [{"gene": "ICAM1"}]}),
        encoding="utf-8",
    )
    (evidence / "stage1_ICAM1--ITGB2.json").write_text(
        json.dumps({"passed": True}),
        encoding="utf-8",
    )
    result = check_hypothesis_scope(source)
    assert result["scope"] == "hypothesis"
    assert result["file_count"] == 0
    assert result["errors"]


def test_check_hypothesis_scope_untraced_restores_tracing_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    (source / "evidence").mkdir(parents=True)
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGCHAIN_API_KEY", "test-langchain-key")
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-langsmith-key")

    result = check_hypothesis_scope_untraced(source)

    assert result["scope"] == "hypothesis"
    assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
    assert os.environ["LANGSMITH_TRACING"] == "true"
    assert os.environ["LANGCHAIN_API_KEY"] == "test-langchain-key"
    assert os.environ["LANGSMITH_API_KEY"] == "test-langsmith-key"


def test_dry_run_cli_suppresses_langsmith_tracing() -> None:
    source = Path("res_ipf_ollama_tmp")
    if not source.exists():
        pytest.skip("benchmark source workspace is not available")
    env = {
        **os.environ,
        "LANGCHAIN_TRACING_V2": "true",
        "LANGSMITH_TRACING": "true",
        "LANGCHAIN_API_KEY": "test-langchain-key",
        "LANGSMITH_API_KEY": "test-langsmith-key",
    }

    completed = subprocess.run(
        [
            sys.executable,
            "docs/benchmarks/hypothesis_generation_consistency/run_benchmark.py",
            "--source",
            str(source),
            "--runs",
            "10",
            "--dry-run",
        ],
        check=False,
        capture_output=True,
        encoding="utf-8",
        env=env,
    )

    assert completed.returncode == 0
    assert "LangSmith" not in completed.stderr
    assert "RateLimit" not in completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["file_count"] == 64
    assert payload["contrast_count"] == 10
    assert payload["errors"] == []


def test_parse_args_uses_ollama_when_provider_env_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "")
    monkeypatch.setattr(sys, "argv", ["run_benchmark.py"])

    args = parse_args()

    assert args.provider == "ollama"


def test_parse_args_accepts_expanded6_skill_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_benchmark.py", "--skill-set", "expanded6"],
    )

    args = parse_args()

    assert args.skill_set == "expanded6"


def test_resolve_trial_sources_repeats_single_source(tmp_path: Path) -> None:
    source = tmp_path / "source"

    sources = resolve_trial_sources(str(source), None, 3)

    assert sources == [source, source, source]


def test_resolve_trial_sources_requires_sources_count_to_match_runs(
    tmp_path: Path,
) -> None:
    first = tmp_path / "source1"
    second = tmp_path / "source2"

    with pytest.raises(ValueError, match="--sources count"):
        resolve_trial_sources(str(first), [str(first), str(second)], 3)


def test_validate_trial_output_marks_missing_report_as_failure(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "evidence").mkdir(parents=True)
    row = validate_trial_output("run_01", workspace, elapsed_s=1.25, error=None)
    assert row["run_id"] == "run_01"
    assert row["success"] is False
    assert row["validation_passed"] is False
    assert "hypothesis_report.json missing" in row["error"]


@pytest.mark.parametrize(
    "report",
    [
        {},
        {
            "schema_version": "hypothesis_report.v2",
            "hypotheses": [],
            "topn_coverage": {"covered": [], "missing": []},
            "prediction_grounding_summary": {"unverified": 0},
        },
    ],
)
def test_validate_trial_output_rejects_structurally_empty_reports(
    tmp_path: Path,
    report: dict,
) -> None:
    workspace = tmp_path / "workspace"
    evidence = workspace / "evidence"
    evidence.mkdir(parents=True)
    (evidence / "hypothesis_report.json").write_text(
        json.dumps(report),
        encoding="utf-8",
    )

    row = validate_trial_output("run_01", workspace, elapsed_s=1.25, error=None)

    assert row["success"] is True
    assert row["validation_passed"] is False


def test_validate_trial_output_rejects_non_object_report(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    evidence = workspace / "evidence"
    evidence.mkdir(parents=True)
    (evidence / "hypothesis_report.json").write_text("[]", encoding="utf-8")

    row = validate_trial_output("run_01", workspace, elapsed_s=1.25, error=None)

    assert row["success"] is False
    assert row["validation_passed"] is False
    assert row["report_summary"] is None
    assert "JSON object" in row["error"]
    assert "list" in row["error"]


def test_validate_trial_output_marks_forbidden_draft_artifact_invalid(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    evidence = workspace / "evidence"
    evidence.mkdir(parents=True)
    (workspace / "hypothesis_report.json").write_text("{}", encoding="utf-8")
    (workspace / "hypothesis_report.tmp.json").write_text("{}", encoding="utf-8")
    (workspace / "Hypothesis_Report_Mixed.JSON").write_text("{}", encoding="utf-8")
    (workspace / "hypothesis_report_draft.json").write_text("{}", encoding="utf-8")
    (evidence / "hypothesis_report.json").write_text(
        json.dumps(_report_one()),
        encoding="utf-8",
    )

    row = validate_trial_output("run_01", workspace, elapsed_s=1.25, error=None)

    assert row["success"] is True
    assert row["validation_passed"] is False
    assert row["forbidden_artifacts"] == [
        "hypothesis_report.json",
        "hypothesis_report.tmp.json",
        "hypothesis_report_draft.json",
        "Hypothesis_Report_Mixed.JSON",
    ]


def test_find_forbidden_hypothesis_artifacts_reports_root_level_variants(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    evidence = workspace / "evidence"
    evidence.mkdir(parents=True)
    (workspace / "hypothesis_report.json").write_text("{}", encoding="utf-8")
    (workspace / "hypothesis_report_a.json").write_text("{}", encoding="utf-8")
    (workspace / "hypothesis_report_b.json").write_text("{}", encoding="utf-8")
    (workspace / "Hypothesis_Report_Mixed.JSON").write_text("{}", encoding="utf-8")
    (evidence / "hypothesis_report.json").write_text("{}", encoding="utf-8")

    artifacts = find_forbidden_hypothesis_artifacts(workspace)

    assert artifacts == [
        "hypothesis_report.json",
        "hypothesis_report_a.json",
        "hypothesis_report_b.json",
        "Hypothesis_Report_Mixed.JSON",
    ]


def test_validate_trial_output_includes_summary_when_invocation_errors_after_report(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    evidence = workspace / "evidence"
    evidence.mkdir(parents=True)
    (evidence / "hypothesis_report.json").write_text(
        json.dumps(_report_one()),
        encoding="utf-8",
    )

    row = validate_trial_output(
        "run_01",
        workspace,
        elapsed_s=1.25,
        error="RuntimeError: failed after writing report",
    )

    assert row["success"] is False
    assert row["validation_passed"] is False
    assert row["report_summary"]["hypothesis_count"] == 2
