"""Unit tests for LLMConfigSchema — Phase 2 T2.1/T2.2.

Validates that the top-level LangGraph config schema accepts 'ollama-openai'
as a valid llm_provider literal value.
"""

import pytest
from pydantic import ValidationError

from src.agents.llm_config import LLMConfigSchema


def test_schema_accepts_ollama_openai():
    """T2.1 #1: LLMConfigSchema(llm_provider='ollama-openai') must not raise."""
    config = LLMConfigSchema(llm_provider="ollama-openai")
    assert config.llm_provider == "ollama-openai"


def test_schema_accepts_vllm():
    """LLMConfigSchema(llm_provider='vllm') must not raise."""
    config = LLMConfigSchema(llm_provider="vllm")
    assert config.llm_provider == "vllm"


def test_schema_still_accepts_existing_providers():
    """T2.1 #2: regression — all pre-existing providers still accepted."""
    for provider in ("openrouter", "openai", "google", "ollama", "claude"):
        config = LLMConfigSchema(llm_provider=provider)
        assert config.llm_provider == provider


def test_schema_rejects_unknown_provider():
    """T2.1 #3: unknown provider strings must raise ValidationError."""
    with pytest.raises(ValidationError):
        LLMConfigSchema(llm_provider="bogus-provider")
