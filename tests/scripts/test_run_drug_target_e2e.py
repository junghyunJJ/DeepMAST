from __future__ import annotations

import json

import pytest

from scripts import run_drug_target_e2e as runner


class _Agent:
    async def ainvoke(self, *_args, **_kwargs):
        return {"messages": []}


class _Backend:
    def __init__(self) -> None:
        self.cleaned = False

    def cleanup(self) -> None:
        self.cleaned = True


@pytest.mark.asyncio
async def test_e2e_requires_guarded_audit_and_cleans_backend(tmp_path, monkeypatch):
    backend = _Backend()
    monkeypatch.setattr(runner.tempfile, "mkdtemp", lambda **_: str(tmp_path))

    def factory(config):
        assert config.workflow_mode == "guarded_report"
        for name in runner.guarded_run_succeeded.__globals__["REQUIRED_GUARDED_ARTIFACTS"]:
            (tmp_path / name).write_text("{}" if name.endswith(".json") else "x")
        (tmp_path / "drug_report_validation_final.json").write_text(json.dumps({"valid": True, "publication": {"status": "passed"}}))
        return _Agent(), backend

    monkeypatch.setattr(runner, "create_drug_target_agent", factory)
    assert await runner.main() == 0
    assert backend.cleaned


@pytest.mark.asyncio
async def test_e2e_no_message_fallback_is_success(tmp_path, monkeypatch):
    monkeypatch.setattr(runner.tempfile, "mkdtemp", lambda **_: str(tmp_path))
    monkeypatch.setattr(runner, "create_drug_target_agent", lambda _config: (_Agent(), None))
    assert await runner.main() == 1
    assert not (tmp_path / "drug.md").exists()
