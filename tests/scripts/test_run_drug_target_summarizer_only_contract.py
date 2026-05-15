"""Contract tests for the standalone drug-target summarizer runner."""

import asyncio
import importlib
import os
import sys
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPTS_DIR = str(Path(__file__).resolve().parents[2] / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

_MODULE_NAME = "run_drug_target_summarizer_only"


def _reload_module() -> object:
    if _MODULE_NAME in sys.modules:
        return importlib.reload(sys.modules[_MODULE_NAME])
    return importlib.import_module(_MODULE_NAME)


def test_scan_for_status_uses_final_assistant_message_only(monkeypatch) -> None:
    mod = _reload_module()
    messages = [
        SimpleNamespace(type="ai", content="SUMMARIZER_STATUS: PASS"),
        SimpleNamespace(type="tool", content="tool output"),
        SimpleNamespace(type="ai", content="I did not finish."),
    ]

    assert mod._scan_for_status(messages) is None


def test_scan_for_status_accepts_final_assistant_literal_status(monkeypatch) -> None:
    mod = _reload_module()
    messages = [
        SimpleNamespace(type="tool", content="SUMMARIZER_STATUS: FAIL"),
        SimpleNamespace(type="ai", content="SUMMARIZER_STATUS: PASS\n- validated"),
    ]

    assert mod._scan_for_status(messages) == "PASS"


def test_main_exits_nonzero_when_run_reports_failure(monkeypatch) -> None:
    mod = _reload_module()

    async def fake_run(args):
        return False

    monkeypatch.setattr(mod, "_parse_args", lambda: SimpleNamespace())
    monkeypatch.setattr(mod, "_run", fake_run)

    with pytest.raises(SystemExit) as exc:
        mod.main()

    assert exc.value.code == 1


def test_main_exits_zero_when_run_reports_success(monkeypatch) -> None:
    mod = _reload_module()

    async def fake_run(args):
        return True

    monkeypatch.setattr(mod, "_parse_args", lambda: SimpleNamespace())
    monkeypatch.setattr(mod, "_run", fake_run)

    with pytest.raises(SystemExit) as exc:
        mod.main()

    assert exc.value.code == 0


def test_dry_run_cleans_owned_temp_data_dir(monkeypatch, tmp_path) -> None:
    mod = _reload_module()
    data_dir = tmp_path / "owned-data-dir"
    fake_tool = SimpleNamespace(name="build_evidence_summary")
    args = SimpleNamespace(
        evidence_source="tests/agents/drug_target/fixtures/baseline_hallucinated",
        output=str(tmp_path / "drug.md"),
        data_dir=None,
        keep_data_dir=False,
        provider="openai",
        model=None,
        dry_run=True,
        recursion_limit=300,
        log_level="INFO",
        log_file=str(tmp_path / "summarizer.log"),
    )

    monkeypatch.setattr(
        mod.tempfile,
        "mkdtemp",
        lambda prefix: str(data_dir),
    )
    monkeypatch.setattr(
        mod,
        "_build_summarizer_spec",
        lambda data_dir, disease: {
            "tools": [fake_tool],
            "middleware": [],
        },
    )

    success = asyncio.run(mod._run(args))

    assert success is True
    assert not data_dir.exists()


def test_parse_args_accepts_port_for_ollama_provider(monkeypatch) -> None:
    mod = _reload_module()
    monkeypatch.setattr(
        sys,
        "argv",
        [_MODULE_NAME, "--provider", "ollama", "--port", "6000"],
    )

    args = mod._parse_args()

    assert args.port == 6000


def test_parse_args_rejects_port_for_non_ollama_provider(monkeypatch) -> None:
    mod = _reload_module()
    monkeypatch.setattr(
        sys,
        "argv",
        [_MODULE_NAME, "--provider", "openai", "--port", "6000"],
    )

    with pytest.raises(SystemExit) as exc:
        mod._parse_args()

    assert exc.value.code == 2


def test_set_provider_env_applies_port_to_ollama_base_urls(monkeypatch) -> None:
    mod = _reload_module()
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    mod._set_provider_env(provider="ollama", model="qwen3.5:122b", port=6000)

    assert os.environ["OLLAMA_BASE_URL"] == "http://localhost:6000"
    assert os.environ["OLLAMA_HOST"] == "http://localhost:6000"
    assert os.environ["LLM_PROVIDER"] == "ollama"
    assert os.environ["LLM_MODEL"] == "qwen3.5:122b"


def test_run_passes_port_to_provider_env(monkeypatch, tmp_path) -> None:
    mod = _reload_module()
    captured: dict[str, int | None] = {}

    def fake_set_provider_env(provider: str, model: str | None, port: int | None) -> None:
        captured["port"] = port

    args = Namespace(
        evidence_source="tests/agents/drug_target/fixtures/baseline_hallucinated",
        output=str(tmp_path / "drug.md"),
        data_dir=str(tmp_path / "data-dir"),
        keep_data_dir=False,
        provider="ollama",
        model="qwen3.5:122b",
        port=7000,
        dry_run=True,
        recursion_limit=300,
        log_level="INFO",
        log_file=str(tmp_path / "summarizer.log"),
    )
    fake_tool = SimpleNamespace(name="build_evidence_summary")
    monkeypatch.setattr(mod, "_set_provider_env", fake_set_provider_env)
    monkeypatch.setattr(
        mod,
        "_build_summarizer_spec",
        lambda data_dir, disease: {
            "tools": [fake_tool],
            "middleware": [],
        },
    )

    success = asyncio.run(mod._run(args))

    assert success is True
    assert captured["port"] == 7000
