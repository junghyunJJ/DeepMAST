"""Shared LLM CLI/env configuration for benchmark runners."""

from __future__ import annotations

import argparse
import os
from typing import Any


_REASONING_VALUES = {"true", "false"}
_QWEN_OLLAMA_DEFAULTS = {
    "qwen3.5:35b": {
        "llm_provider": "ollama",
        "llm_model": "qwen3.5:35b",
        "ollama_base_url": "http://localhost:7000",
        "ollama_reasoning": "false",
        "temperature": "0",
    },
    "qwen3.5:122b": {
        "llm_provider": "ollama",
        "llm_model": "qwen3.5:122b",
        "ollama_base_url": "http://localhost:6000",
        "ollama_reasoning": "false",
        "temperature": "0",
    },
}


def qwen_ollama_defaults(model: str) -> dict[str, str]:
    normalized_model = model.strip()
    if normalized_model not in _QWEN_OLLAMA_DEFAULTS:
        raise ValueError(f"unsupported qwen ollama model: {model}")
    return dict(_QWEN_OLLAMA_DEFAULTS[normalized_model])


def add_benchmark_llm_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--llm-provider", default="", help="Optional provider override for query generation.")
    parser.add_argument("--llm-model", default="", help="Optional LLM_MODEL env override for query generation.")
    parser.add_argument("--ollama-base-url", default="", help="Optional OLLAMA_BASE_URL override.")
    parser.add_argument(
        "--ollama-reasoning",
        default="",
        choices=sorted(_REASONING_VALUES),
        help="Set OLLAMA_REASONING for ChatOllama. Use false for qwen benchmark search.",
    )


def apply_benchmark_llm_config(args: Any) -> dict[str, str]:
    provider = str(getattr(args, "llm_provider", "") or "").strip()
    model = str(getattr(args, "llm_model", "") or "").strip()
    base_url = str(getattr(args, "ollama_base_url", "") or "").strip()
    reasoning = str(getattr(args, "ollama_reasoning", "") or "").strip().lower()

    if reasoning and reasoning not in _REASONING_VALUES:
        raise ValueError("--ollama-reasoning must be 'true' or 'false'")
    if model:
        os.environ["LLM_MODEL"] = model
    if base_url:
        os.environ["OLLAMA_BASE_URL"] = base_url
    if reasoning:
        os.environ["OLLAMA_REASONING"] = reasoning

    return {
        "llm_provider": provider,
        "llm_model": model,
        "ollama_base_url": base_url,
        "ollama_reasoning": reasoning,
    }
