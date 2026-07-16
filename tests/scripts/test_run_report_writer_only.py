from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import multiprocessing
import sys
import time
from pathlib import Path

import pytest

from scripts import run_drug_target_agent_bc as bc_runner
from scripts import run_drug_target_e2e as e2e_runner
from scripts import run_report_writer_only as runner


@pytest.fixture(autouse=True)
def _use_fork_for_runner_monkeypatches(monkeypatch):
    monkeypatch.setattr(runner, "_process_context", lambda: multiprocessing.get_context("fork"))


class _Writer:
    def __init__(self, callback=None) -> None:
        self.calls: list[dict[str, object]] = []
        self.callback = callback

    async def ainvoke(self, writer_input):
        self.calls.append(writer_input)
        if self.callback:
            self.callback()
        return {"messages": []}


class _HangingWriter:
    async def ainvoke(self, _writer_input):
        await asyncio.sleep(60)


class _ThreadHangingWriter:
    def __init__(self, data_dir) -> None:
        self.data_dir = data_dir

    async def ainvoke(self, _writer_input):
        (self.data_dir / "report_data.json").write_text("partial")

        def publish_late() -> None:
            time.sleep(0.5)
            (self.data_dir / "drug_report_render.json").write_text("late")

        await asyncio.to_thread(publish_late)


class _ResultQueue:
    def close(self) -> None:
        return None

    def join_thread(self) -> None:
        return None


class _TerminationResistantProcess:
    def __init__(self) -> None:
        self.alive = True
        self.terminated = False
        self.killed = False
        self.join_timeouts: list[float | None] = []

    def start(self) -> None:
        return None

    def is_alive(self) -> bool:
        return self.alive

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        self.alive = False

    def join(self, timeout: float | None = None) -> None:
        self.join_timeouts.append(timeout)
        if timeout is None:
            time.sleep(0.3 if self.terminated else 0.05)


class _CliLifecycleProcess(_TerminationResistantProcess):
    def join(self, timeout: float | None = None) -> None:
        self.join_timeouts.append(timeout)
        if timeout is None:
            time.sleep(0.3)


class _KillIneffectiveProcess(_TerminationResistantProcess):
    def __init__(self, data_dir) -> None:
        super().__init__()
        self.data_dir = data_dir
        self.wrote_partial_outputs = False

    def join(self, timeout: float | None = None) -> None:
        self.join_timeouts.append(timeout)
        if not self.wrote_partial_outputs:
            self.wrote_partial_outputs = True
            (self.data_dir / "drug.md").write_text("partial")
            (self.data_dir / "report_sections.json").write_text("{}")
            (self.data_dir / "report_data.json").write_text("partial")
            (self.data_dir / "drug_report_render.json").write_text("partial")
            (self.data_dir / ".report-sections-partial").mkdir()

    def kill(self) -> None:
        self.killed = True


class _ForcedExit(Exception):
    pass


class _StartFailingProcess:
    def start(self) -> None:
        raise OSError("cannot start child")

    def is_alive(self) -> bool:
        return False


class _ProcessContext:
    def __init__(self, process) -> None:
        self.process = process

    def Queue(self):
        return _ResultQueue()

    def Process(self, **_kwargs):
        return self.process


def _args(path, **overrides):
    values = {
        "data_dir": str(path),
        "disease": "breast cancer",
        "provider": "ollama",
        "model": None,
        "request_timeout_seconds": 600.0,
        "run_timeout_seconds": 1800.0,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _evidence_ready(path):
    evidence = path / "evidence"
    evidence.mkdir()
    for index in range(5):
        (evidence / f"e{index}.json").write_text("{}")


def _passed_artifacts(path):
    for name in runner.REQUIRED_GUARDED_ARTIFACTS:
        (path / name).write_text("x" if not name.endswith(".json") else "{}")
    (path / "drug_report_validation_final.json").write_text(
        json.dumps(
            {
                "valid": True,
                "publication": {
                    "status": "passed",
                    "artifacts": [
                        "part4_candidate_selection.json",
                        "part4_therapeutic_synthesis.md",
                        "drug_report.html",
                    ],
                    "error": None,
                },
            }
        )
    )


def test_guarded_runner_predicate_rejects_published_alias_and_is_shared(tmp_path):
    _passed_artifacts(tmp_path)
    (tmp_path / "drug_report_validation_final.json").write_text(
        json.dumps({"valid": True, "publication": {"status": "published"}})
    )

    assert runner.guarded_run_succeeded(tmp_path) is False
    assert e2e_runner.guarded_run_succeeded is runner.guarded_run_succeeded
    assert bc_runner.guarded_run_succeeded is runner.guarded_run_succeeded


def test_parse_args_has_bounded_deadline_defaults(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_report_writer_only.py", "--data-dir", "run", "--disease", "breast cancer"],
    )

    args = runner.parse_args()

    assert args.request_timeout_seconds == 600.0
    assert args.run_timeout_seconds == 1800.0


@pytest.mark.parametrize(
    ("request_timeout_seconds", "run_timeout_seconds"),
    [(0, 1800), (600, 0), (1800, 1800), (1801, 1800)],
)
def test_timeout_validation_rejects_invalid_deadlines(
    tmp_path,
    request_timeout_seconds,
    run_timeout_seconds,
):
    with pytest.raises(ValueError):
        runner._validate_timeouts(
            _args(
                tmp_path,
                request_timeout_seconds=request_timeout_seconds,
                run_timeout_seconds=run_timeout_seconds,
            )
        )


@pytest.mark.asyncio
async def test_writer_only_requires_evidence_before_creating_writer(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(runner, "parse_args", lambda: _args(tmp_path))
    monkeypatch.setattr(
        runner,
        "create_guarded_report_writer",
        lambda _config: pytest.fail("writer should not be created"),
    )

    assert await runner.main() == 1
    assert capsys.readouterr().out == "ERROR: Not enough evidence files. Run evidence assessment first.\n"


@pytest.mark.asyncio
async def test_writer_only_uses_direct_factory_with_existing_evidence_context_and_no_env_mutation(
    tmp_path,
    monkeypatch,
):
    _evidence_ready(tmp_path)
    writer = _Writer(callback=lambda: _passed_artifacts(tmp_path))

    monkeypatch.setattr(runner, "parse_args", lambda: _args(tmp_path, model="qwen3.5:122b"))

    monkeypatch.setattr(runner, "create_guarded_report_writer", lambda _config: writer)

    assert await runner.main() == 0
    assert "DRUG_TARGET_SKIP_EVIDENCE_ASSESSOR" not in inspect.getsource(runner)


@pytest.mark.asyncio
async def test_writer_only_clears_stale_outputs_before_direct_writer_runs(tmp_path, monkeypatch):
    _evidence_ready(tmp_path)
    _passed_artifacts(tmp_path)
    for name in ("report_data.json", "drug_report_render.json"):
        (tmp_path / name).write_text("stale")
        (tmp_path / name).with_suffix(f"{Path(name).suffix}.tmp").write_text("temporary")
    staging = tmp_path / ".report-sections-stale"
    staging.mkdir()
    (staging / "partial.json").write_text("stale")

    def assert_stale_outputs_removed():
        assert not any((tmp_path / name).exists() for name in runner.REQUIRED_GUARDED_ARTIFACTS)
        assert not any(
            (tmp_path / name).exists()
            for name in ("report_data.json", "drug_report_render.json")
        )
        assert not staging.exists()

    monkeypatch.setattr(runner, "parse_args", lambda: _args(tmp_path))
    monkeypatch.setattr(
        runner,
        "create_guarded_report_writer",
        lambda _config: _Writer(callback=assert_stale_outputs_removed),
    )

    assert await runner.main() == 1


@pytest.mark.asyncio
async def test_invalid_deadlines_fail_before_writer_creation(tmp_path, monkeypatch, capsys):
    _evidence_ready(tmp_path)
    monkeypatch.setattr(
        runner,
        "parse_args",
        lambda: _args(tmp_path, request_timeout_seconds=1800, run_timeout_seconds=1800),
    )
    monkeypatch.setattr(
        runner,
        "create_guarded_report_writer",
        lambda _config: pytest.fail("invalid deadlines must stop before writer creation"),
    )

    assert await runner.main() == 1
    assert "request timeout" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_writer_timeout_cleans_all_guarded_outputs(tmp_path, monkeypatch, capsys):
    _evidence_ready(tmp_path)
    _passed_artifacts(tmp_path)
    (tmp_path / "report_sections.json").write_text("{}")
    for name in ("report_data.json", "drug_report_render.json"):
        (tmp_path / name).write_text("stale")
    writer = _HangingWriter()
    monkeypatch.setattr(
        runner,
        "parse_args",
        lambda: _args(tmp_path, request_timeout_seconds=0.001, run_timeout_seconds=0.002),
    )
    monkeypatch.setattr(runner, "create_guarded_report_writer", lambda _config: writer)

    assert await runner.main() == 1
    assert not any(
        (tmp_path / name).exists()
        for name in (*runner.REQUIRED_GUARDED_ARTIFACTS, "report_sections.json", "report_data.json", "drug_report_render.json")
    )
    assert capsys.readouterr().err == (
        "ERROR: guarded report timed out after 0.002s in phase=report_writer "
        "provider=ollama model=default\n"
    )


@pytest.mark.asyncio
async def test_writer_timeout_hard_stops_threaded_guardrail_work_and_prevents_late_publish(
    tmp_path,
    monkeypatch,
    capsys,
):
    _evidence_ready(tmp_path)
    monkeypatch.setattr(
        runner,
        "parse_args",
        lambda: _args(tmp_path, request_timeout_seconds=0.01, run_timeout_seconds=0.02),
    )
    monkeypatch.setattr(
        runner,
        "create_guarded_report_writer",
        lambda _config: _ThreadHangingWriter(tmp_path),
    )

    started = time.monotonic()
    assert await runner.main() == 1
    assert time.monotonic() - started < 0.3
    assert not (tmp_path / "report_data.json").exists()
    assert not (tmp_path / "drug_report_render.json").exists()
    await asyncio.sleep(0.55)
    assert not (tmp_path / "report_data.json").exists()
    assert not (tmp_path / "drug_report_render.json").exists()
    assert capsys.readouterr().err == (
        "ERROR: guarded report timed out after 0.02s in phase=report_writer "
        "provider=ollama model=default\n"
    )


@pytest.mark.asyncio
async def test_writer_timeout_kills_a_termination_resistant_child(tmp_path, monkeypatch, capsys):
    _evidence_ready(tmp_path)
    process = _TerminationResistantProcess()
    monkeypatch.setattr(runner, "parse_args", lambda: _args(tmp_path, request_timeout_seconds=0.001, run_timeout_seconds=0.01))
    monkeypatch.setattr(runner, "_process_context", lambda: _ProcessContext(process))

    started = time.monotonic()
    assert await runner.main() == 1
    assert time.monotonic() - started < 0.15
    assert process.terminated is True
    assert process.killed is True
    assert process.join_timeouts[1:] == [runner._PROCESS_STOP_SECONDS] * 2
    assert capsys.readouterr().err == (
        "ERROR: guarded report timed out after 0.01s in phase=report_writer "
        "provider=ollama model=default\n"
    )


@pytest.mark.asyncio
async def test_writer_child_start_failure_is_reported_by_parent(tmp_path, monkeypatch, capsys):
    _evidence_ready(tmp_path)
    monkeypatch.setattr(runner, "parse_args", lambda: _args(tmp_path))
    monkeypatch.setattr(runner, "_process_context", lambda: _ProcessContext(_StartFailingProcess()))

    assert await runner.main() == 1
    assert capsys.readouterr().err == "ERROR: guarded report writer failed: OSError: cannot start child\n"


def test_cli_timeout_never_waits_for_an_unbounded_child_join(tmp_path, monkeypatch, capsys):
    _evidence_ready(tmp_path)
    process = _CliLifecycleProcess()
    monkeypatch.setattr(runner, "parse_args", lambda: _args(tmp_path, request_timeout_seconds=0.001, run_timeout_seconds=0.01))
    monkeypatch.setattr(runner, "_process_context", lambda: _ProcessContext(process))

    started = time.monotonic()
    assert asyncio.run(runner.main()) == 1
    assert time.monotonic() - started < 0.15
    assert process.terminated is True
    assert process.killed is True
    assert all(timeout is not None for timeout in process.join_timeouts)
    assert capsys.readouterr().err == (
        "ERROR: guarded report timed out after 0.01s in phase=report_writer "
        "provider=ollama model=default\n"
    )


@pytest.mark.asyncio
async def test_force_exit_clears_guarded_outputs_when_kill_is_ineffective(
    tmp_path,
    monkeypatch,
):
    _evidence_ready(tmp_path)
    _passed_artifacts(tmp_path)
    (tmp_path / "report_sections.json").write_text("{}")
    for name in ("report_data.json", "drug_report_render.json"):
        (tmp_path / name).write_text("stale")
    staging = tmp_path / ".report-sections-stale"
    staging.mkdir()
    process = _KillIneffectiveProcess(tmp_path)
    monkeypatch.setattr(runner, "parse_args", lambda: _args(tmp_path, request_timeout_seconds=0.001, run_timeout_seconds=0.01))
    monkeypatch.setattr(runner, "_process_context", lambda: _ProcessContext(process))
    monkeypatch.setattr(runner, "_force_exit", lambda: (_ for _ in ()).throw(_ForcedExit()))

    with pytest.raises(_ForcedExit):
        await runner.main()

    assert process.terminated is True
    assert process.killed is True
    assert not any(
        (tmp_path / name).exists()
        for name in (*runner.REQUIRED_GUARDED_ARTIFACTS, "report_sections.json", "report_data.json", "drug_report_render.json")
    )
    assert not staging.exists()


@pytest.mark.asyncio
async def test_force_exit_runs_when_last_resort_cleanup_raises(tmp_path, monkeypatch):
    process = _KillIneffectiveProcess(tmp_path)
    cleanup_calls = []

    def failing_cleanup(data_dir):
        cleanup_calls.append(data_dir)
        raise OSError("cleanup failed")

    monkeypatch.setattr(runner, "clear_guarded_report_run_artifacts", failing_cleanup)
    monkeypatch.setattr(runner, "_force_exit", lambda: (_ for _ in ()).throw(_ForcedExit()))

    with pytest.raises(_ForcedExit):
        await runner._require_child_stop(process, tmp_path)

    assert cleanup_calls == [tmp_path]
    assert process.terminated is True
    assert process.killed is True
    assert process.is_alive() is True


@pytest.mark.parametrize(
    ("artifact", "phase"),
    [
        (None, "report_writer"),
        ("report_sections.json", "guardrail_or_publication"),
        ("drug_report_validation_final.json", "publication"),
    ],
)
def test_timeout_phase_uses_only_current_run_artifacts(tmp_path, artifact, phase):
    if artifact:
        (tmp_path / artifact).write_text("{}")

    assert runner._infer_timeout_phase(tmp_path) == phase
