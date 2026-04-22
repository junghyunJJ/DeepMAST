from __future__ import annotations

import argparse

import pytest

from scripts import run_drug_target_traced as traced


def test_parse_args_defaults_timeout_to_120():
    args = traced.parse_args([])
    assert args.timeout == 120
    assert args.port is None


def test_parse_args_accepts_port():
    args = traced.parse_args(["--port", "6000"])
    assert args.port == 6000
    assert args.provider == "ollama"


@pytest.mark.parametrize("port", ["0", "70000"])
def test_parse_args_rejects_invalid_port(port: str):
    with pytest.raises(SystemExit):
        traced.parse_args(["--port", port])


def test_parse_args_rejects_port_for_non_ollama_provider():
    with pytest.raises(SystemExit):
        traced.parse_args(["--provider", "openai", "--port", "6000"])


def test_configure_ollama_port_override_sets_env(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)

    args = argparse.Namespace(provider="ollama", port=6000)
    base_url = traced._configure_ollama_port_override(args)

    assert base_url == "http://localhost:6000"
    assert traced.os.environ["OLLAMA_BASE_URL"] == "http://localhost:6000"
    assert traced.os.environ["OLLAMA_HOST"] == "http://localhost:6000"


def test_configure_ollama_port_override_noops_without_port(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:7000")
    monkeypatch.setenv("OLLAMA_HOST", "http://localhost:7000")

    args = argparse.Namespace(provider="ollama", port=None)
    base_url = traced._configure_ollama_port_override(args)

    assert base_url is None
    assert traced.os.environ["OLLAMA_BASE_URL"] == "http://localhost:7000"
    assert traced.os.environ["OLLAMA_HOST"] == "http://localhost:7000"
