from __future__ import annotations

import json

import pytest

from scripts import run_drug_target_agent_bc as runner


class _Agent:
    async def ainvoke(self, *_args, **_kwargs):
        return {"messages": []}


class _Backend:
    def __init__(self) -> None:
        self.cleaned = False

    def cleanup(self) -> None:
        self.cleaned = True


@pytest.mark.asyncio
async def test_bc_runner_uses_guarded_factory_and_final_audit(tmp_path, monkeypatch):
    (tmp_path / "lr_candidates.json").write_text("{}")
    backend = _Backend()
    monkeypatch.setattr(runner, "DATA_DIR", str(tmp_path))

    def factory(config):
        assert config.workflow_mode == "guarded_report"
        for name in runner.guarded_run_succeeded.__globals__["REQUIRED_GUARDED_ARTIFACTS"]:
            (tmp_path / name).write_text("{}" if name.endswith(".json") else "x")
        (tmp_path / "drug_report_validation_final.json").write_text(json.dumps({"valid": True, "publication": {"status": "passed"}}))
        return _Agent(), backend

    monkeypatch.setattr(runner, "create_drug_target_agent", factory)
    assert await runner.main() == 0
    assert backend.cleaned
