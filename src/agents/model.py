"""model - Create Language Models for different providers"""
import os
from typing import Optional
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from langchain_core.language_models.chat_models import BaseChatModel


def create_llm(provider: Optional[str] = None, **kwargs) -> BaseChatModel:
    """
    Create LLM based on provider (default: google with gemini-2.0-flash)
    
    Args:
        provider: LLM provider ('openai', 'google', 'ollama'). 
                 If None, uses LLM_PROVIDER env var or defaults to 'openai'
        **kwargs: Provider-specific arguments
    
    Returns:
        BaseChatModel instance
    """
    if provider is None:
        provider = os.getenv("LLM_PROVIDER", "google")
    
    provider = provider.lower()
    
    if provider == "ollama":
        return create_ollama_llm(**kwargs)
    elif provider == "google":
        return create_google_llm(**kwargs)
    elif provider == "openai":
        return create_openai_llm(**kwargs)
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
    # model = kwargs.get("model", os.getenv("OPENAI_MODEL", "gpt-4.1"))
    temperature = kwargs.get("temperature", 0)
    
    return ChatOpenAI(
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




