"""Shared LangGraph config_schema for runtime LLM provider/model selection."""

from typing import Literal

from pydantic import BaseModel, Field


class LLMConfigSchema(BaseModel):
    """LangGraph config_schema for runtime LLM provider/model selection."""

    llm_provider: Literal["", "kimi", "openai", "google", "ollama", "claude"] = Field(
        default="",
        title="LLM Provider",
        description="LLM provider to use. Leave empty for server default.",
    )
    llm_model: str = Field(
        default="",
        title="LLM Model",
        description="Model name override. Leave empty for provider default.",
    )
