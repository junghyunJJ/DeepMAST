from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import sys

import pytest

from scripts import run_drug_target_agent_bc as bc_runner
from scripts import run_drug_target_e2e as e2e_runner
from scripts import run_report_writer_only as runner


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
    def __init__(self) -> None:
        self.cancelled = False

    async def ainvoke(self, _writer_input):
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            self.cancelled = True
            raise


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
    seen = {}
    writer = _Writer(callback=lambda: _passed_artifacts(tmp_path))

    monkeypatch.setattr(runner, "parse_args", lambda: _args(tmp_path, model="qwen3.5:122b"))

    def factory(config):
        seen["factory_calls"] = seen.get("factory_calls", 0) + 1
        seen["config"] = config
        return writer

    monkeypatch.setattr(runner, "create_guarded_report_writer", factory)

    assert await runner.main() == 0
    assert "DRUG_TARGET_SKIP_EVIDENCE_ASSESSOR" not in inspect.getsource(runner)
    assert seen["factory_calls"] == 1
    config = seen["config"]
    assert config.provider == "ollama"
    assert config.model == "qwen3.5:122b"
    assert config.request_timeout_seconds == 600.0
    assert config.data_dir == str(tmp_path.resolve())
    assert config.disease == "breast cancer"
    assert writer.calls == [
        {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Render guarded hybrid report from existing evidence. "
                        f"Data dir: {tmp_path.resolve()}. Disease: breast cancer."
                    ),
                }
            ]
        }
    ]


@pytest.mark.asyncio
async def test_writer_only_clears_stale_outputs_before_direct_writer_runs(tmp_path, monkeypatch):
    _evidence_ready(tmp_path)
    _passed_artifacts(tmp_path)

    def assert_stale_outputs_removed():
        assert not any((tmp_path / name).exists() for name in runner.REQUIRED_GUARDED_ARTIFACTS)

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
async def test_writer_timeout_cancels_and_rejects_stale_success_artifacts(tmp_path, monkeypatch, capsys):
    _evidence_ready(tmp_path)
    _passed_artifacts(tmp_path)
    (tmp_path / "report_sections.json").write_text("{}")
    writer = _HangingWriter()
    monkeypatch.setattr(
        runner,
        "parse_args",
        lambda: _args(tmp_path, request_timeout_seconds=0.001, run_timeout_seconds=0.002),
    )
    monkeypatch.setattr(runner, "create_guarded_report_writer", lambda _config: writer)

    assert await runner.main() == 1
    assert writer.cancelled is True
    assert capsys.readouterr().err == (
        "ERROR: guarded report timed out after 0.002s in phase=report_writer "
        "provider=ollama model=default\n"
    )


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
