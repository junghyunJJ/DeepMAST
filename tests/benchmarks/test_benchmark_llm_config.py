import argparse
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.benchmarks.benchmark_llm_config import (
    add_benchmark_llm_args,
    apply_benchmark_llm_config,
    qwen_ollama_defaults,
)


def test_apply_benchmark_llm_config_sets_qwen_ollama_env(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_REASONING", raising=False)
    args = argparse.Namespace(
        llm_provider="ollama",
        llm_model="qwen3.5:35b",
        ollama_base_url="http://localhost:7000",
        ollama_reasoning="false",
    )

    config = apply_benchmark_llm_config(args)

    assert os.environ["LLM_MODEL"] == "qwen3.5:35b"
    assert os.environ["OLLAMA_BASE_URL"] == "http://localhost:7000"
    assert os.environ["OLLAMA_REASONING"] == "false"
    assert config == {
        "llm_provider": "ollama",
        "llm_model": "qwen3.5:35b",
        "ollama_base_url": "http://localhost:7000",
        "ollama_reasoning": "false",
    }


def test_apply_benchmark_llm_config_rejects_invalid_reasoning():
    args = argparse.Namespace(
        llm_provider="ollama",
        llm_model="qwen3.5:35b",
        ollama_base_url="http://localhost:7000",
        ollama_reasoning="maybe",
    )

    with pytest.raises(ValueError, match="--ollama-reasoning"):
        apply_benchmark_llm_config(args)


def test_add_benchmark_llm_args_parses_qwen_options():
    parser = argparse.ArgumentParser()
    add_benchmark_llm_args(parser)

    args = parser.parse_args(
        [
            "--llm-provider",
            "ollama",
            "--llm-model",
            "qwen3.5:35b",
            "--ollama-base-url",
            "http://localhost:7000",
            "--ollama-reasoning",
            "false",
        ]
    )

    assert args.llm_provider == "ollama"
    assert args.llm_model == "qwen3.5:35b"
    assert args.ollama_base_url == "http://localhost:7000"
    assert args.ollama_reasoning == "false"


@pytest.mark.parametrize(
    ("model", "base_url"),
    [
        ("qwen3.5:35b", "http://localhost:7000"),
        ("qwen3.5:122b", "http://localhost:6000"),
    ],
)
def test_qwen_ollama_defaults_returns_supported_model_defaults(model, base_url):
    assert qwen_ollama_defaults(model) == {
        "llm_provider": "ollama",
        "llm_model": model,
        "ollama_base_url": base_url,
        "ollama_reasoning": "false",
        "temperature": "0",
    }


def test_qwen_ollama_defaults_rejects_unsupported_model():
    with pytest.raises(ValueError, match="unsupported qwen ollama model"):
        qwen_ollama_defaults("qwen3.5:7b")
