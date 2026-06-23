"""model - Create Language Models for different providers"""
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI


class _ChatOllamaWithThink(ChatOllama):
    """ChatOllama variant that can send Ollama's native `think` flag."""

    think: bool | None = None

    def _chat_params(self, messages, stop=None, **kwargs) -> dict[str, Any]:
        params = super()._chat_params(messages, stop=stop, **kwargs)
        if self.think is not None and params.get("think") is None:
            params["think"] = self.think
        return params


def _parse_optional_bool(value: Any) -> bool | None:
    """Parse optional env-style booleans; None means leave provider default intact."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value: {value!r}")


def create_llm(provider: Optional[str] = None, **kwargs) -> BaseChatModel:
    """
    Create LLM based on provider (default: openrouter with moonshotai/kimi-k2.5)

    Args:
        provider: LLM provider ('openai', 'google', 'ollama', 'ollama-openai', 'vllm',
                 'claude', 'openrouter').
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
    elif provider in {"ollama-openai", "vllm"}:
        return create_ollama_openai_llm(provider_label=provider, **kwargs)
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
        model: Model name (default: gpt-4.5-mini)
        temperature: Temperature setting (default: 0)
    """
    model = kwargs.get("model", os.getenv("OPENAI_MODEL", "gpt-4.5-mini"))
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
        model_name=model,
        temperature=temperature,
        timeout=None,
        stop=None,
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
    request_timeout = float(
        kwargs.get(
            "request_timeout",
            os.getenv("GOOGLE_REQUEST_TIMEOUT_SECONDS", "600"),
        )
    )
    
    return ChatGoogleGenerativeAI(
        model=model,
        temperature=temperature,
        request_timeout=request_timeout,
    )


def create_ollama_llm(**kwargs) -> ChatOllama:
    """
    Create Ollama LLM instance (default: qwen3.5:122b at localhost:6000)
    
    Args:
        model: Model name (default: qwen3.5:122b)
        base_url: Ollama server URL (default: http://localhost:6000)
        temperature: Temperature setting (default: 0)
    """
    model = kwargs.get("model", os.getenv("OLLAMA_MODEL", "qwen3.5:122b"))

    base_url = kwargs.get("base_url", os.getenv("OLLAMA_BASE_URL", "http://localhost:6000"))
    temperature = kwargs.get("temperature", 0)
    
    num_ctx = kwargs.get("num_ctx", 98304) # default to 98K
    raw_num_predict = kwargs.get("num_predict", os.getenv("OLLAMA_NUM_PREDICT"))
    num_predict = int(raw_num_predict) if raw_num_predict not in (None, "") else -1
    if num_predict <= 0 and str(model).endswith("-cloud"):
        # Ollama cloud rejects unlimited generation as max_tokens=-1.
        num_predict = int(os.getenv("OLLAMA_CLOUD_NUM_PREDICT", "16384"))
    reasoning = _parse_optional_bool(kwargs.get("reasoning", os.getenv("OLLAMA_REASONING")))

    llm = _ChatOllamaWithThink(
        model=model,
        base_url=base_url,
        temperature=temperature,
        keep_alive="24h",
        num_ctx=num_ctx,
        num_predict=num_predict,
        think=reasoning,
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


def create_ollama_openai_llm(**kwargs: Any) -> ChatOpenAI:
    """Ollama via OpenAI-compatible /v1/chat/completions endpoint.

    Bypasses Ollama's PARSER xml->json layer, which corrupts complex
    multi-tool schemas under qwen3.5:35b (XML syntax error: element
    <function> closed by </parameter>). Routes through native JSON
    tool-calls instead.

    Reuses the same NUM_CTX / NUM_PREDICT / BASE_URL env keys as
    create_ollama_llm so load_subagent_models_from_env() works
    without modification. The provider also supports vLLM/OpenAI-compatible
    local servers that expose /v1/chat/completions. Ollama-specific kwargs
    (and the canonical
    ChatOpenAI kwargs we explicitly forward) are POPPED from kwargs
    before the **kwargs spread. Per CP-P2-007: each popped key is
    removed from `kwargs` by `kwargs.pop(...)`, so the subsequent
    `**kwargs` spread cannot re-pass any of them — there is no
    double-pass / "got multiple values for keyword argument" risk.

    KNOWN LIMITATION (verified 2026-05-03 against Ollama 0.20.6 +
    qwen3.5:35b at port 5000): Ollama's OpenAI-compat layer at
    /v1/chat/completions IGNORES every per-request truncation knob
    we have tried — `max_tokens`, `extra_body={"num_predict": N}`,
    and `extra_body={"options": {"num_predict": N, "num_ctx": N}}`.
    Live wire-level test produced output_tokens=7915 in all 3
    variants (versus ChatOllama on /api/chat which honored
    num_predict=10 exactly). The `extra_body` line below is
    therefore a current no-op — kept because the syntax is
    syntactically correct per Ollama's OpenAI-compat docs and
    future Ollama versions are expected to honor it. Until then,
    server-side context limits and output truncation must be set
    via Ollama daemon configuration (Modelfile `PARAMETER num_ctx`,
    or `OLLAMA_NUM_PARALLEL` / `OLLAMA_KV_CACHE_TYPE` env vars at
    daemon launch).

    For our actual use case (tool-calling subagents) this is not a
    binding constraint: the model self-terminates after emitting
    compact JSON tool-call payloads (~50-100 tokens), well below
    any reasonable max_tokens. The risk surface is long agent runs
    where conversation history grows beyond Ollama's server-side
    context window before SummarizationMiddleware fires; operators
    must align `OLLAMA_NUM_CTX` (daemon) with `num_ctx` (this
    factory) to avoid silent server-side context truncation.
    """
    # Pop Ollama-specific kwargs BEFORE forwarding to ChatOpenAI.
    # ChatOpenAI raises TypeError on unknown kwargs (num_ctx, num_predict).
    # All popped kwargs are removed from **kwargs spread; no double-pass risk.
    provider_label = kwargs.pop("provider_label", "ollama-openai")
    base_host = kwargs.pop("base_url", None) or os.getenv(
        "OLLAMA_BASE_URL", "http://localhost:11434"
    )
    # D4 (CP-P2-001 corrected): handle optional user-supplied /v1 suffix
    # rstrip("/") drops trailing slashes; endswith("/v1") checks the literal
    # substring (NOT rstrip("/v1") which is a character-set strip).
    base_host = base_host.rstrip("/")
    if base_host.endswith("/v1"):
        base_url = base_host
    else:
        base_url = f"{base_host}/v1"

    # D9 (iteration 3): default aligned with create_ollama_llm (model.py:115)
    model = kwargs.pop("model", None) or os.getenv(
        "OLLAMA_MODEL", "qwen3.5:122b"
    )
    num_ctx = int(kwargs.pop("num_ctx", 98304))
    num_predict = int(kwargs.pop("num_predict", -1))
    temperature = kwargs.pop("temperature", 0)
    if "max_tokens" not in kwargs:
        raw_max_tokens_env = os.getenv("VLLM_MAX_TOKENS") or os.getenv(
            "OLLAMA_OPENAI_MAX_TOKENS"
        )
        if raw_max_tokens_env:
            kwargs["max_tokens"] = int(raw_max_tokens_env)
    raw_extra_body = kwargs.pop("extra_body", None)
    extra_body = dict(raw_extra_body or {})
    options = dict(extra_body.get("options") or {})
    options.update({"num_ctx": num_ctx, "num_predict": num_predict})
    extra_body["options"] = options
    enable_thinking = _parse_optional_bool(
        kwargs.pop(
            "enable_thinking",
            os.getenv("VLLM_ENABLE_THINKING")
            or os.getenv("OLLAMA_OPENAI_ENABLE_THINKING"),
        )
    )
    if enable_thinking is not None:
        chat_template_kwargs = dict(extra_body.get("chat_template_kwargs") or {})
        chat_template_kwargs["enable_thinking"] = enable_thinking
        extra_body["chat_template_kwargs"] = chat_template_kwargs

    # CP-P2-005 (iteration 4): emit ops audit log before constructing the LLM.
    logger.info(
        "LLM provider=%s model=%s base_url=%s num_ctx=%s num_predict=%s enable_thinking=%s",
        provider_label,
        model,
        base_url,
        num_ctx,
        num_predict,
        enable_thinking,
    )

    llm = ChatOpenAI(
        model=model,
        base_url=base_url,
        api_key="ollama",  # placeholder — Ollama ignores, OpenAI SDK requires non-empty
        temperature=temperature,
        request_timeout=7200,  # pyright: ignore[reportCallIssue]  # D8: verified request_timeout, NOT timeout
        streaming=False,  # D7: explicit (matches ChatOpenAI default; defends against accidental enable)
        parallel_tool_calls=False,  # pyright: ignore[reportCallIssue]  # D10 / CP-P1-002: prevent uncertain Ollama OpenAI-compat parallel-call behavior
        # Codex P2 #1: forward Ollama-native options to server. CURRENTLY A NO-OP
        # in Ollama 0.20.6 (verified 2026-05-03 — see docstring KNOWN LIMITATION
        # block). Kept for future-proofing; the syntax is per Ollama's OpenAI-
        # compat docs and is harmless when ignored.
        extra_body=extra_body,
        **kwargs,  # forward any remaining caller-supplied kwargs (e.g., max_tokens for OpenRouter parity)
    )
    # D2: Mirror create_ollama_llm profile setup VERBATIM.
    # `profile` is a typed Pydantic field on BaseChatModel:
    #   profile: ModelProfile | None  (where ModelProfile is TypedDict, total=False)
    # Formula: copied verbatim from src/agents/model.py:137
    raw_max_tokens = kwargs.get("max_tokens")
    effective_output = (
        num_predict
        if num_predict > 0
        else int(raw_max_tokens)
        if raw_max_tokens not in (None, "")
        else num_ctx // 4
    )
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

    init_kwargs: dict[str, Any] = dict(
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
        {PREFIX}_{NAME}_MAX_TOKENS    (OpenRouter / OpenAI-compatible providers)
        {PREFIX}_{NAME}_ENABLE_THINKING (vLLM / OpenAI-compatible Qwen providers)

    Example .env:
        SUBAGENT_PLANNER_PROVIDER=openai
        SUBAGENT_PLANNER_MODEL=gpt-4.1-mini
        SUBAGENT_INTERPRETER_PROVIDER=ollama
        SUBAGENT_INTERPRETER_MODEL=qwen3.5:122b
        SUBAGENT_INTERPRETER_NUM_CTX=262144 # 256K in H100 x2

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

        # Shared by ollama, ollama-openai, and vllm (all reuse these env keys here).
        num_ctx = os.getenv(f"{env_prefix}_NUM_CTX")
        if num_ctx:
            kwargs["num_ctx"] = int(num_ctx)

        num_predict = os.getenv(f"{env_prefix}_NUM_PREDICT")
        if num_predict:
            kwargs["num_predict"] = int(num_predict)

        base_url = os.getenv(f"{env_prefix}_BASE_URL")
        if base_url:
            kwargs["base_url"] = base_url

        # OpenAI-compatible providers
        max_tokens = os.getenv(f"{env_prefix}_MAX_TOKENS")
        if max_tokens:
            kwargs["max_tokens"] = int(max_tokens)

        enable_thinking = os.getenv(f"{env_prefix}_ENABLE_THINKING")
        if enable_thinking:
            kwargs["enable_thinking"] = _parse_optional_bool(enable_thinking)

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
