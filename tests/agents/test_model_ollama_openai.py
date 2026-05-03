"""Unit tests for the ollama-openai provider (Phase 1, T1.1 + T1.2).

Tests 1-14: create_ollama_openai_llm() factory (T1.1)
Tests 15-20: create_llm() dispatcher acceptance (T1.2)

Mock strategy: patch "src.agents.model.ChatOpenAI" with autospec=True so
unknown-attr access raises AttributeError instead of silently returning a new
MagicMock. Tests #11 and #12 use the *real* ChatOpenAI (no mock, no network)
to defend against autospec-mock vacuity.
"""
import logging
from unittest.mock import MagicMock, patch

import pytest
from langchain_openai import ChatOpenAI

from src.agents.model import create_llm, create_ollama_openai_llm


# ---------------------------------------------------------------------------
# T1.1: create_ollama_openai_llm() factory tests (14 total)
# ---------------------------------------------------------------------------


def test_create_ollama_openai_llm_returns_chatopenai():
    """Test #1: factory returns a ChatOpenAI instance."""
    with patch("src.agents.model.ChatOpenAI", autospec=True) as mock_chatopenai:
        mock_chatopenai.return_value = MagicMock(spec=ChatOpenAI)
        llm = create_ollama_openai_llm()
    assert isinstance(llm, ChatOpenAI)


def test_create_ollama_openai_llm_default_base_url_appends_v1(monkeypatch):
    """Test #2: when env unset, base_url ends with /v1 at default port 11434."""
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    with patch("src.agents.model.ChatOpenAI", autospec=True) as mock_chatopenai:
        mock_chatopenai.return_value = MagicMock(spec=ChatOpenAI)
        _ = create_ollama_openai_llm()
        kwargs = mock_chatopenai.call_args.kwargs
    assert kwargs["base_url"] == "http://localhost:11434/v1"


def test_create_ollama_openai_llm_custom_base_url_appends_v1(monkeypatch):
    """Test #3: OLLAMA_BASE_URL=http://localhost:5000 → base_url == .../v1."""
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:5000")
    with patch("src.agents.model.ChatOpenAI", autospec=True) as mock_chatopenai:
        mock_chatopenai.return_value = MagicMock(spec=ChatOpenAI)
        _ = create_ollama_openai_llm()
        kwargs = mock_chatopenai.call_args.kwargs
    assert kwargs["base_url"] == "http://localhost:5000/v1"


def test_create_ollama_openai_llm_user_supplied_v1_suffix_handled(monkeypatch):
    """Test #4: OLLAMA_BASE_URL with /v1 already → no double /v1/v1."""
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://x:5000/v1")
    with patch("src.agents.model.ChatOpenAI", autospec=True) as mock_chatopenai:
        mock_chatopenai.return_value = MagicMock(spec=ChatOpenAI)
        _ = create_ollama_openai_llm()
        kwargs = mock_chatopenai.call_args.kwargs
    assert kwargs["base_url"] == "http://x:5000/v1"
    assert "/v1/v1" not in kwargs["base_url"]


def test_create_ollama_openai_llm_api_key_is_ollama_placeholder(monkeypatch):
    """Test #5: api_key is the literal placeholder string 'ollama'."""
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    with patch("src.agents.model.ChatOpenAI", autospec=True) as mock_chatopenai:
        mock_chatopenai.return_value = MagicMock(spec=ChatOpenAI)
        _ = create_ollama_openai_llm()
        kwargs = mock_chatopenai.call_args.kwargs
    assert kwargs["api_key"] == "ollama"


def test_create_ollama_openai_llm_model_passthrough(monkeypatch):
    """Test #6: env unset → default qwen3.5:122b (D9); explicit arg propagated."""
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    # Default case
    with patch("src.agents.model.ChatOpenAI", autospec=True) as mock_chatopenai:
        mock_chatopenai.return_value = MagicMock(spec=ChatOpenAI)
        _ = create_ollama_openai_llm()
        assert mock_chatopenai.call_args.kwargs["model"] == "qwen3.5:122b"

    # Explicit override
    with patch("src.agents.model.ChatOpenAI", autospec=True) as mock_chatopenai:
        mock_chatopenai.return_value = MagicMock(spec=ChatOpenAI)
        _ = create_ollama_openai_llm(model="qwen3.5:35b")
        assert mock_chatopenai.call_args.kwargs["model"] == "qwen3.5:35b"


def test_create_ollama_openai_llm_temperature_default_zero(monkeypatch):
    """Test #7: temperature defaults to 0."""
    with patch("src.agents.model.ChatOpenAI", autospec=True) as mock_chatopenai:
        mock_chatopenai.return_value = MagicMock(spec=ChatOpenAI)
        _ = create_ollama_openai_llm()
        kwargs = mock_chatopenai.call_args.kwargs
    assert kwargs["temperature"] == 0


def test_create_ollama_openai_llm_profile_default_args_exact_values(monkeypatch):
    """Test #8: num_ctx=98304, num_predict=-1 → exact profile arithmetic (AC2)."""
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    with patch("src.agents.model.ChatOpenAI", autospec=True) as mock_chatopenai:
        mock_instance = MagicMock(spec=ChatOpenAI)
        mock_chatopenai.return_value = mock_instance
        llm = create_ollama_openai_llm(num_ctx=98304, num_predict=-1)

    # effective_output = num_ctx // 4 = 24576
    assert llm.profile["max_input_tokens"] == 73728   # 98304 - 24576
    assert llm.profile["max_output_tokens"] == 24576  # 98304 // 4


def test_create_ollama_openai_llm_profile_with_explicit_num_predict(monkeypatch):
    """Test #9: num_predict=2048 → profile uses num_predict directly."""
    with patch("src.agents.model.ChatOpenAI", autospec=True) as mock_chatopenai:
        mock_instance = MagicMock(spec=ChatOpenAI)
        mock_chatopenai.return_value = mock_instance
        llm = create_ollama_openai_llm(num_ctx=98304, num_predict=2048)

    # effective_output = num_predict = 2048
    assert llm.profile["max_input_tokens"] == 96256  # 98304 - 2048
    assert llm.profile["max_output_tokens"] == 2048


def test_create_ollama_openai_llm_does_not_forward_ollama_kwargs_to_chatopenai():
    """Test #10: Ollama-only kwargs (num_ctx, num_predict) must NOT leak through **kwargs.

    temperature, model, base_url ARE present as canonical OpenAI params.
    What is guarded: num_ctx and num_predict (Ollama-only) must be absent.
    All popped kwargs are forwarded explicitly; **kwargs remainder cannot re-pass them.
    """
    with patch("src.agents.model.ChatOpenAI", autospec=True) as mock_chatopenai:
        mock_chatopenai.return_value = MagicMock(spec=ChatOpenAI)
        _ = create_ollama_openai_llm(
            num_ctx=98304,
            num_predict=-1,
            base_url="http://x:5000",
            temperature=0.3,
            model="qwen3.5:35b",
        )
        kwargs = mock_chatopenai.call_args.kwargs

    # Canonical OpenAI kwargs ARE present (explicitly forwarded)
    assert kwargs["base_url"] == "http://x:5000/v1"
    assert kwargs["temperature"] == 0.3
    assert kwargs["model"] == "qwen3.5:35b"
    # Ollama-only kwargs MUST NOT leak through the **kwargs spread
    assert "num_ctx" not in kwargs
    assert "num_predict" not in kwargs


def test_create_ollama_openai_llm_real_construction_sets_profile_correctly():
    """Test #11: real ChatOpenAI (no mock, no network) — profile shape + arithmetic.

    Defends against autospec-mock vacuity. ChatOpenAI.__init__ does not perform
    network I/O; network only happens on .invoke()/.ainvoke()/.stream().
    """
    llm = create_ollama_openai_llm(model="qwen3.5:122b", num_ctx=98304, num_predict=-1)
    assert isinstance(llm, ChatOpenAI)
    assert isinstance(llm.profile, dict)   # NOT SimpleNamespace, NOT MagicMock
    assert llm.profile["max_input_tokens"] == 73728   # 98304 - 24576
    assert llm.profile["max_output_tokens"] == 24576  # 98304 // 4
    # CP-P2-002: pin dict size to detect key bloat / pre-seeded baseline keys
    assert len(llm.profile) == 2


def test_create_ollama_openai_llm_temperature_kwarg_does_not_double_pass():
    """Test #12: explicit temperature=0.5 must NOT raise TypeError (no double-pass).

    kwargs.pop('temperature', 0) removes it from **kwargs spread — this pins the invariant.
    """
    # Should not raise TypeError: ChatOpenAI got multiple values for 'temperature'
    llm = create_ollama_openai_llm(temperature=0.5)
    assert isinstance(llm, ChatOpenAI)


def test_create_ollama_openai_llm_passes_parallel_tool_calls_false():
    """Test #13: D10 / CP-P1-002 — parallel_tool_calls=False must be explicit."""
    with patch("src.agents.model.ChatOpenAI", autospec=True) as mock_chatopenai:
        mock_chatopenai.return_value = MagicMock(spec=ChatOpenAI)
        _ = create_ollama_openai_llm()
        assert mock_chatopenai.call_args.kwargs["parallel_tool_calls"] is False


def test_create_ollama_openai_llm_emits_provider_info_log(caplog):
    """Test #14: CP-P2-005 — construction emits INFO log with provider fields."""
    with caplog.at_level(logging.INFO, logger="src.agents.model"):
        _ = create_ollama_openai_llm(model="qwen3.5:35b", base_url="http://x:5000")
    assert any(
        "LLM provider=" in rec.getMessage()
        and "qwen3.5:35b" in rec.getMessage()
        and "http://x:5000/v1" in rec.getMessage()
        for rec in caplog.records
    ), f"No matching INFO log found. Records: {[r.getMessage() for r in caplog.records]}"


# ---------------------------------------------------------------------------
# T1.2: create_llm() dispatcher acceptance tests (6 total)
# ---------------------------------------------------------------------------


def test_dispatcher_accepts_ollama_openai_provider_string():
    """Test #15 (T1.2 #1): create_llm(provider='ollama-openai') returns ChatOpenAI."""
    with patch("src.agents.model.ChatOpenAI", autospec=True) as mock_chatopenai:
        mock_chatopenai.return_value = MagicMock(spec=ChatOpenAI)
        llm = create_llm(provider="ollama-openai")
    assert isinstance(llm, ChatOpenAI)


def test_dispatcher_accepts_ollama_openai_via_env(monkeypatch):
    """Test #16 (T1.2 #2): LLM_PROVIDER=ollama-openai → create_llm() returns ChatOpenAI."""
    monkeypatch.setenv("LLM_PROVIDER", "ollama-openai")
    with patch("src.agents.model.ChatOpenAI", autospec=True) as mock_chatopenai:
        mock_chatopenai.return_value = MagicMock(spec=ChatOpenAI)
        llm = create_llm()
    assert isinstance(llm, ChatOpenAI)


def test_dispatcher_unknown_provider_still_raises():
    """Test #17 (T1.2 #3): regression — unknown provider still raises ValueError."""
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        create_llm(provider="bogus")


def test_load_subagent_models_from_env_with_ollama_openai_end_to_end(monkeypatch):
    """Test #18 (T1.2 #4): subagent env-var loader with ollama-openai routes correctly.

    Verifies:
    - Returns a ChatOpenAI instance for the subagent
    - num_ctx/num_predict popped before ChatOpenAI init (profile set correctly)
    - profile["max_input_tokens"] == 127072 (131072 - 4096)
    """
    monkeypatch.setenv("SUBAGENT_FOO_PROVIDER", "ollama-openai")
    monkeypatch.setenv("SUBAGENT_FOO_MODEL", "qwen3.5:35b")
    monkeypatch.setenv("SUBAGENT_FOO_NUM_CTX", "131072")
    monkeypatch.setenv("SUBAGENT_FOO_NUM_PREDICT", "4096")
    monkeypatch.setenv("SUBAGENT_FOO_BASE_URL", "http://localhost:5000")

    from src.agents.model import load_subagent_models_from_env

    with patch("src.agents.model.ChatOpenAI", autospec=True) as mock_chatopenai:
        mock_instance = MagicMock(spec=ChatOpenAI)
        mock_chatopenai.return_value = mock_instance
        models = load_subagent_models_from_env(["foo"])

    assert models is not None
    assert "foo" in models
    foo_llm = models["foo"]
    assert isinstance(foo_llm, ChatOpenAI)
    # num_ctx/num_predict must be popped — profile should be set
    assert foo_llm.profile["max_input_tokens"] == 126976   # 131072 - 4096
    assert foo_llm.profile["max_output_tokens"] == 4096


def test_dispatcher_still_returns_chatollama_for_ollama_string():
    """Test #19 (T1.2 #5): CP-P2-004 — 'ollama' branch is NOT subsumed by new branch."""
    from langchain_ollama import ChatOllama

    llm = create_llm(provider="ollama")
    assert isinstance(llm, ChatOllama)


def test_create_llm_with_llm_model_env_overrides_ollama_model(monkeypatch):
    """Test #20 (T1.2 #6): CP-P2-006 — LLM_MODEL takes precedence over OLLAMA_MODEL."""
    monkeypatch.setenv("LLM_MODEL", "qwen3.5:7b")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3.5:122b")
    with patch("src.agents.model.ChatOpenAI", autospec=True) as mock_chatopenai:
        mock_chatopenai.return_value = MagicMock(spec=ChatOpenAI)
        create_llm(provider="ollama-openai")
        assert mock_chatopenai.call_args.kwargs["model"] == "qwen3.5:7b"


# ---------------------------------------------------------------------------
# Fix 1 — Codex P2 #1: num_ctx/num_predict forwarded to Ollama via extra_body
# ---------------------------------------------------------------------------


def test_create_ollama_openai_llm_forwards_num_ctx_to_ollama_options():
    """Codex P2 #1 (partial): SDK-LEVEL forwarding only.

    This test asserts the ChatOpenAI constructor receives extra_body with the
    expected options shape — i.e., the langchain SDK plumbing is wired
    correctly. It does NOT (and cannot) verify Ollama actually honors the
    forwarded options at the wire level.

    Wire-level reality (verified 2026-05-03 against Ollama 0.20.6 + qwen3.5:35b
    at port 5000): Ollama's OpenAI-compat layer IGNORES `extra_body.options.*`
    for both num_ctx and num_predict (live test produced output_tokens=7915 in
    every variant tried, vs ChatOllama on /api/chat which honored num_predict
    exactly). See create_ollama_openai_llm docstring KNOWN LIMITATION block.

    Until a future Ollama version honors these options at the wire level,
    server-side context limits must be set via Ollama daemon configuration
    (Modelfile `PARAMETER num_ctx`, daemon launch flags, etc.). The extra_body
    line in production is kept as future-proof syntactically-correct dead code.
    """
    with patch("src.agents.model.ChatOpenAI", autospec=True) as mock_chatopenai:
        mock_chatopenai.return_value = MagicMock(spec=ChatOpenAI)
        _ = create_ollama_openai_llm(num_ctx=16384, num_predict=2048)
        kwargs = mock_chatopenai.call_args.kwargs
    # Either extra_body (preferred) OR model_kwargs.extra_body (fallback)
    if "extra_body" in kwargs:
        opts = kwargs["extra_body"].get("options", {})
    else:
        opts = kwargs.get("model_kwargs", {}).get("extra_body", {}).get("options", {})
    assert opts.get("num_ctx") == 16384, f"num_ctx not forwarded; kwargs={kwargs}"
    assert opts.get("num_predict") == 2048, f"num_predict not forwarded; kwargs={kwargs}"


def test_create_ollama_openai_llm_extra_body_uses_popped_values():
    """Fix 1 regression: extra_body.options must use the POPPED num_ctx/num_predict,
    not any residual value from **kwargs (guards against accidental double-pass)."""
    with patch("src.agents.model.ChatOpenAI", autospec=True) as mock_chatopenai:
        mock_chatopenai.return_value = MagicMock(spec=ChatOpenAI)
        _ = create_ollama_openai_llm(num_ctx=4096, num_predict=512)
        kwargs = mock_chatopenai.call_args.kwargs
    # num_ctx / num_predict must NOT appear at top-level kwargs (still popped)
    assert "num_ctx" not in kwargs, "num_ctx leaked into top-level ChatOpenAI kwargs"
    assert "num_predict" not in kwargs, "num_predict leaked into top-level ChatOpenAI kwargs"
    # And must appear nested under extra_body.options
    if "extra_body" in kwargs:
        opts = kwargs["extra_body"]["options"]
    else:
        opts = kwargs.get("model_kwargs", {}).get("extra_body", {}).get("options", {})
    assert opts["num_ctx"] == 4096
    assert opts["num_predict"] == 512
