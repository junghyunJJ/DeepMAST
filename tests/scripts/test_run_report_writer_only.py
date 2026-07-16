from __future__ import annotations

import argparse
import json

import pytest

from scripts import run_report_writer_only as runner
from scripts import run_drug_target_agent_bc as bc_runner
from scripts import run_drug_target_e2e as e2e_runner


class _Agent:
    async def ainvoke(self, *_args, **_kwargs):
        return {"messages": []}


class _Backend:
    def __init__(self) -> None:
        self.cleaned = False

    def cleanup(self) -> None:
        self.cleaned = True


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


@pytest.mark.asyncio
async def test_writer_only_uses_guarded_factory_and_audit_gate(tmp_path, monkeypatch):
    _evidence_ready(tmp_path)
    seen = {}
    backend = _Backend()

    def factory(config):
        seen["config"] = config
        _passed_artifacts(tmp_path)
        return _Agent(), backend

    monkeypatch.setattr(runner, "parse_args", lambda: argparse.Namespace(data_dir=str(tmp_path), disease="IPF", provider="ollama", model=None))
    monkeypatch.setattr(runner, "create_drug_target_agent", factory)
    assert await runner.main() == 0
    assert seen["config"].workflow_mode == "guarded_report"
    assert backend.cleaned


@pytest.mark.asyncio
async def test_writer_only_assigns_model_to_config(tmp_path, monkeypatch):
    _evidence_ready(tmp_path)
    seen = {}

    def factory(config):
        seen["config"] = config
        _passed_artifacts(tmp_path)
        return _Agent(), _Backend()

    monkeypatch.setattr(
        runner,
        "parse_args",
        lambda: argparse.Namespace(
            data_dir=str(tmp_path),
            disease="IPF",
            provider="ollama-openai",
            model="qwen3.5:122b",
        ),
    )
    monkeypatch.setattr(runner, "create_drug_target_agent", factory)

    assert await runner.main() == 0
    assert seen["config"].model == "qwen3.5:122b"


@pytest.mark.asyncio
async def test_writer_only_rejects_stale_outputs_from_a_noop_agent(tmp_path, monkeypatch):
    _evidence_ready(tmp_path)
    _passed_artifacts(tmp_path)
    monkeypatch.setattr(runner, "parse_args", lambda: argparse.Namespace(data_dir=str(tmp_path), disease="IPF", provider="ollama", model=None))
    monkeypatch.setattr(runner, "create_drug_target_agent", lambda _config: (_Agent(), _Backend()))
    assert await runner.main() == 1
