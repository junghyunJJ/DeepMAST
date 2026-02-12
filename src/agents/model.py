"""model - Create Language Models for different providers"""
import os
from typing import Optional
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from langchain_core.language_models.chat_models import BaseChatModel


def create_llm(provider: Optional[str] = None, **kwargs) -> BaseChatModel:
    """
    Create LLM based on provider (default: kimi with moonshotai/kimi-k2.5)

    Args:
        provider: LLM provider ('openai', 'google', 'ollama', 'claude', 'kimi').
                 If None, uses LLM_PROVIDER env var or defaults to 'kimi'
        **kwargs: Provider-specific arguments

    Returns:
        BaseChatModel instance
    """
    if provider is None:
        provider = os.getenv("LLM_PROVIDER", "kimi")
    
    provider = provider.lower()
    
    if provider == "ollama":
        return create_ollama_llm(**kwargs)
    elif provider == "google":
        return create_google_llm(**kwargs)
    elif provider == "openai":
        return create_openai_llm(**kwargs)
    elif provider == "claude":
        return create_claude_llm(**kwargs)
    elif provider == "kimi":
        return create_kimi_llm(**kwargs)
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
        model: Model name (default: gemini-2.0-flash)
        temperature: Temperature setting (default: 0)
    """
    model = kwargs.get("model", os.getenv("GOOGLE_MODEL", "gemini-2.0-flash"))
    temperature = kwargs.get("temperature", 0)
    
    return ChatGoogleGenerativeAI(
        model=model,
        temperature=temperature,
    )


def create_ollama_llm(**kwargs) -> ChatOllama:
    """
    Create Ollama LLM instance (default: gpt-oss:20b at localhost:6000)
    
    Args:
        model: Model name (default: gpt-oss:20b)
        base_url: Ollama server URL (default: http://localhost:6000)
        temperature: Temperature setting (default: 0)
    """
    model = kwargs.get("model", os.getenv("OLLAMA_MODEL", "gpt-oss:20b"))
    base_url = kwargs.get("base_url", os.getenv("OLLAMA_BASE_URL", "http://localhost:6000"))
    temperature = kwargs.get("temperature", 0)
    
    return ChatOllama(
        model=model,
        base_url=base_url,
        temperature=temperature,
    )


def create_kimi_llm(**kwargs) -> ChatOpenAI:
    """
    Create Kimi K2.5 LLM instance via OpenRouter's OpenAI-compatible API

    Args:
        model: Model name (default: moonshotai/kimi-k2.5)
        temperature: Temperature setting (default: 0)
    """
    model = kwargs.get("model", os.getenv("KIMI_MODEL", "moonshotai/kimi-k2.5"))
    temperature = kwargs.get("temperature", 0)

    return ChatOpenAI(
        model=model,
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY"),
        temperature=temperature,
    )

