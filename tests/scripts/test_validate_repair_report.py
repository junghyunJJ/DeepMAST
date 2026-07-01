from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "validate_repair_report.py"
SPEC = importlib.util.spec_from_file_location("validate_repair_report", SCRIPT_PATH)
assert SPEC and SPEC.loader
orchestrator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(orchestrator)


def test_one_pass_returns_zero_when_repair_clears_errors(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []

    def fake_validate(data_dir: Path, output: Path) -> int:
        calls.append("validate")
        issues = [{"severity": "error", "code": "bad"}] if calls.count("validate") == 1 else []
        output.write_text(json.dumps({"issues": issues}), encoding="utf-8")
        return 1 if issues else 0

    def fake_repair(data_dir: Path, issues: Path, provider: str | None) -> int:
        calls.append("repair")
        assert provider == "ollama"
        return 0

    monkeypatch.setattr(orchestrator, "_run_validate", fake_validate)
    monkeypatch.setattr(orchestrator, "_run_repair", fake_repair)

    rc = orchestrator.validate_repair_once(tmp_path, provider="ollama")

    assert rc == 0
    assert calls == ["validate", "repair", "validate"]


def test_one_pass_returns_one_when_final_errors_remain(tmp_path: Path, monkeypatch) -> None:
    def fake_validate(data_dir: Path, output: Path) -> int:
        output.write_text(json.dumps({"issues": [{"severity": "error", "code": "bad"}]}), encoding="utf-8")
        return 1

    def fake_repair(data_dir: Path, issues: Path, provider: str | None) -> int:
        return 0

    monkeypatch.setattr(orchestrator, "_run_validate", fake_validate)
    monkeypatch.setattr(orchestrator, "_run_repair", fake_repair)

    rc = orchestrator.validate_repair_once(tmp_path, provider=None)

    assert rc == 1


def test_returns_one_when_final_validation_fails_after_clean_initial(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []

    def fake_validate(data_dir: Path, output: Path) -> int:
        calls.append("validate")
        issues = [] if len(calls) == 1 else [{"severity": "error", "code": "late"}]
        output.write_text(json.dumps({"issues": issues}), encoding="utf-8")
        return 1 if issues else 0

    def fake_repair(data_dir: Path, issues: Path, provider: str | None) -> int:
        calls.append("repair")
        return 0

    monkeypatch.setattr(orchestrator, "_run_validate", fake_validate)
    monkeypatch.setattr(orchestrator, "_run_repair", fake_repair)

    rc = orchestrator.validate_repair_once(tmp_path, provider=None)

    assert rc == 1
    assert calls == ["validate", "validate"]


def test_runs_final_validation_even_when_repair_fails(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []

    def fake_validate(data_dir: Path, output: Path) -> int:
        calls.append("validate")
        output.write_text(json.dumps({"issues": [{"severity": "error", "code": "bad"}]}), encoding="utf-8")
        return 1

    def fake_repair(data_dir: Path, issues: Path, provider: str | None) -> int:
        calls.append("repair")
        return 7

    monkeypatch.setattr(orchestrator, "_run_validate", fake_validate)
    monkeypatch.setattr(orchestrator, "_run_repair", fake_repair)

    rc = orchestrator.validate_repair_once(tmp_path, provider=None)

    assert rc == 7
    assert calls == ["validate", "repair", "validate"]
    assert (tmp_path / "report_validation_final.json").exists()
