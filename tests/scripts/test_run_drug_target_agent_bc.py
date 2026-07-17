from __future__ import annotations

import argparse
import asyncio
import json

import pytest

from scripts import run_drug_target_agent_bc as runner


class _SlowAgent:
    async def ainvoke(self, *_args, **_kwargs):
        await asyncio.sleep(0.02)
        return {"messages": []}


class _Backend:
    def __init__(self) -> None:
        self.cleaned = False

    def cleanup(self) -> None:
        self.cleaned = True


def _args(data_dir):
    return argparse.Namespace(
        data_dir=data_dir,
        disease="breast cancer",
        provider="ollama",
        model="qwen3.5:122b",
        skip_evidence_assessor=True,
        heartbeat_seconds=0.001,
    )


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_positive_seconds_rejects_non_finite_values(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="positive"):
        runner._positive_seconds(value)


@pytest.mark.asyncio
async def test_bc_runner_emits_heartbeat_and_keeps_guarded_success_contract(
    tmp_path, monkeypatch, capsys
):
    (tmp_path / "lr_candidates.json").write_text("{}")
    backend = _Backend()
    monkeypatch.setattr(runner, "parse_args", lambda: _args(tmp_path))

    def factory(config):
        assert config.provider == "ollama"
        assert config.workflow_mode == "guarded_report"
        for name in runner.guarded_run_succeeded.__globals__["REQUIRED_GUARDED_ARTIFACTS"]:
            (tmp_path / name).write_text("{}" if name.endswith(".json") else "x")
        (tmp_path / "drug_report_validation_final.json").write_text(
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
        return _SlowAgent(), backend

    monkeypatch.setattr(runner, "create_drug_target_agent", factory)
    assert await runner.main() == 0
    assert "RUNNING elapsed_seconds=" in capsys.readouterr().out
    assert backend.cleaned is True
