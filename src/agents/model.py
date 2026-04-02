"""model - Create Language Models for different providers"""
import os
from typing import Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI


def create_llm(provider: Optional[str] = None, **kwargs) -> BaseChatModel:
    """
    Create LLM based on provider (default: openrouter with moonshotai/kimi-k2.5)

    Args:
        provider: LLM provider ('openai', 'google', 'ollama', 'claude', 'openrouter').
                 If None, uses LLM_PROVIDER env var or defaults to 'openrouter'
        **kwargs: Provider-specific arguments

    Returns:
        BaseChatModel instance
    """
    if provider is None:
        provider = os.getenv("LLM_PROVIDER", "openai")

    # LLM_MODEL: provider-independent model override
    if "model" not in kwargs:
        llm_model = os.getenv("LLM_MODEL")
        if llm_model:
            kwargs["model"] = llm_model

    provider = provider.lower()
    
    if provider == "ollama":
        return create_ollama_llm(**kwargs)
    elif provider == "google":
        return create_google_llm(**kwargs)
    elif provider == "openai":
        return create_openai_llm(**kwargs)
    elif provider == "claude":
        return create_claude_llm(**kwargs)
    elif provider == "openrouter":
        return create_openrouter_llm(**kwargs)
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")


def create_openai_llm(**kwargs) -> ChatOpenAI:
    """
    Create OpenAI LLM instance

    Args:
        model: Model name (default: gpt-4.1-mini)
        temperature: Temperature setting (default: 0)
    """
    model = kwargs.get("model", os.getenv("OPENAI_MODEL", "gpt-4.1-mini"))
    # model = kwargs.get("model", os.getenv("OPENAI_MODEL", "gpt-5-nano"))
    # model = kwargs.get("model", os.getenv("OPENAI_MODEL", "gpt-5-nano"))
    # model = kwargs.get("model", os.getenv("OPENAI_MODEL", "gpt-4.1"))
    temperature = kwargs.get("temperature", 0)

    return ChatOpenAI(
        model=model,
        temperature=temperature,
    )


def create_claude_llm(**kwargs) -> ChatAnthropic:
    """
    Create Anthropic Claude LLM instance

    Args:
        model: Model name (default: claude-haiku-4-5-20251001)
        temperature: Temperature setting (default: 0)
    """
    # model = kwargs.get("model", os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929"))
    model = kwargs.get("model", os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"))

    temperature = kwargs.get("temperature", 0)

    return ChatAnthropic(
        model=model,
        temperature=temperature,
    )


def create_google_llm(**kwargs) -> ChatGoogleGenerativeAI:
    """
    Create Google Gemini LLM instance
    
    Args:
        model: Model name (default: gemini-3.1-flash-lite-preview)
        temperature: Temperature setting (default: 0)
    """
    model = kwargs.get("model", os.getenv("GOOGLE_MODEL", "gemini-3.1-flash-lite-preview"))
    temperature = kwargs.get("temperature", 0)
    
    return ChatGoogleGenerativeAI(
        model=model,
        temperature=temperature,
    )


def create_ollama_llm(**kwargs) -> ChatOllama:
    """
    Create Ollama LLM instance (default: qwen3.5:35b at localhost:6000)
    
    Args:
        model: Model name (default: qwen3.5:35b)
        base_url: Ollama server URL (default: http://localhost:6000)
        temperature: Temperature setting (default: 0)
    """
    model = kwargs.get("model", os.getenv("OLLAMA_MODEL", "qwen3.5:35b"))

    base_url = kwargs.get("base_url", os.getenv("OLLAMA_BASE_URL", "http://localhost:6000"))
    temperature = kwargs.get("temperature", 0)
    
    num_ctx = kwargs.get("num_ctx", 65536)
    num_predict = kwargs.get("num_predict", -1)  # unlimited; prevents truncated tool call JSON (#14570)

    llm = ChatOllama(
        model=model,
        base_url=base_url,
        temperature=temperature,
        keep_alive="24h",
        num_ctx=num_ctx,
        num_predict=num_predict,
        disable_streaming=True,
        client_kwargs={
            "timeout": 7200,
        }
    )
    # Set profile so deepagents SummarizationMiddleware triggers at 85% of
    # actual context window instead of defaulting to 170K tokens (unreachable).
    effective_output = num_predict if num_predict > 0 else num_ctx // 4
    llm.profile = {
        "max_input_tokens": num_ctx - effective_output,
        "max_output_tokens": effective_output,
    }
    return llm


def create_openrouter_llm(**kwargs) -> ChatOpenAI:
    """
    Create OpenRouter LLM instance via OpenRouter's OpenAI-compatible API

    Args:
        model: Model name (default: moonshotai/kimi-k2.5)
        temperature: Temperature setting (default: 0)
    """
    model = kwargs.get("model", os.getenv("OPENROUTER_MODEL", "moonshotai/kimi-k2.5"))
    temperature = kwargs.get("temperature", 0)
    max_tokens = kwargs.get("max_tokens")

    init_kwargs = dict(
        model=model,
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY"),
        temperature=temperature,
    )
    if max_tokens is not None:
        init_kwargs["max_tokens"] = max_tokens

    return ChatOpenAI(**init_kwargs)


def load_subagent_models_from_env(
    subagent_names: list[str],
    prefix: str = "SUBAGENT",
) -> dict[str, BaseChatModel] | None:
    """Load per-subagent model configs from environment variables.

    For each subagent name, reads:
        {PREFIX}_{NAME}_PROVIDER  (required to activate override)
        {PREFIX}_{NAME}_MODEL
        {PREFIX}_{NAME}_TEMPERATURE
        {PREFIX}_{NAME}_NUM_CTX       (Ollama only)
        {PREFIX}_{NAME}_NUM_PREDICT   (Ollama only)
        {PREFIX}_{NAME}_BASE_URL      (Ollama only)
        {PREFIX}_{NAME}_MAX_TOKENS    (OpenRouter only)

    Example .env:
        SUBAGENT_PLANNER_PROVIDER=openai
        SUBAGENT_PLANNER_MODEL=gpt-4.1-mini
        SUBAGENT_INTERPRETER_PROVIDER=ollama
        SUBAGENT_INTERPRETER_MODEL=qwen3.5:35b
        SUBAGENT_INTERPRETER_NUM_CTX=65536

    Args:
        subagent_names: List of subagent names to check (e.g. ["planner", "searcher"])
        prefix: Environment variable prefix (default: "SUBAGENT")

    Returns:
        Dict of {name: BaseChatModel} if any env vars found, None otherwise.
    """
    models: dict[str, BaseChatModel] = {}

    for name in subagent_names:
        env_prefix = f"{prefix}_{name.upper()}"
        provider = os.getenv(f"{env_prefix}_PROVIDER")
        if not provider:
            continue

        kwargs: dict = {}

        model = os.getenv(f"{env_prefix}_MODEL")
        if model:
            kwargs["model"] = model

        temperature = os.getenv(f"{env_prefix}_TEMPERATURE")
        if temperature:
            kwargs["temperature"] = float(temperature)

        # Ollama-specific
        num_ctx = os.getenv(f"{env_prefix}_NUM_CTX")
        if num_ctx:
            kwargs["num_ctx"] = int(num_ctx)

        num_predict = os.getenv(f"{env_prefix}_NUM_PREDICT")
        if num_predict:
            kwargs["num_predict"] = int(num_predict)

        base_url = os.getenv(f"{env_prefix}_BASE_URL")
        if base_url:
            kwargs["base_url"] = base_url

        # OpenRouter-specific
        max_tokens = os.getenv(f"{env_prefix}_MAX_TOKENS")
        if max_tokens:
            kwargs["max_tokens"] = int(max_tokens)

        models[name] = create_llm(provider=provider, **kwargs)

    return models if models else None


def create_llm_from_config(
    config: RunnableConfig | None = None,
    fallback_provider: str | None = None,
) -> BaseChatModel:
    """Create LLM from RunnableConfig.configurable, with env var fallback.

    Resolution order: configurable.llm_provider -> fallback_provider -> env var -> "openrouter"
    """
    configurable = (config or {}).get("configurable", {})
    provider = (configurable.get("llm_provider") or "").strip() or fallback_provider
    model_name = (configurable.get("llm_model") or "").strip() or None
    kwargs = {"model": model_name} if model_name else {}
    return create_llm(provider=provider, **kwargs)

