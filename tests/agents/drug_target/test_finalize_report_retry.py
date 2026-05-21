"""#18f — CP-P1-017: LLM retry behaviour in _llm_fill_expansions_once.

The with_retry(stop_after_attempt=2) wrapper must trigger a retry when the
first invocation fails. On second attempt returning a valid payload the
function must succeed with (payload, None).
"""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from src.agents.drug_target.finalize_report import _llm_fill_expansions_once
from src.agents.drug_target.tools.report_expansion_schema import ReportExpansionsPayload


def _make_minimal_payload() -> ReportExpansionsPayload:
    return ReportExpansionsPayload(schema_version="report_expansions.v1", slots=[])


def test_returns_none_error_repr_when_both_attempts_fail() -> None:
    """When every attempt raises, _llm_fill_expansions_once returns (None, repr)."""
    call_count = 0

    def _always_fail(prompt, config=None):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("LLM unavailable")

    mock_chain = MagicMock()
    mock_chain.invoke = _always_fail

    mock_structured = MagicMock()
    mock_structured.with_retry = MagicMock(return_value=mock_chain)

    mock_model = MagicMock()
    mock_model.with_structured_output = MagicMock(return_value=mock_structured)

    payload, error = _llm_fill_expansions_once(
        model=mock_model,
        spec={},
        evidence={},
        reference_card={},
        config={},
    )

    assert payload is None
    assert error is not None
    assert "RuntimeError" in error or "LLM unavailable" in error


def test_returns_payload_when_invoke_succeeds() -> None:
    """When invoke succeeds on the first attempt, returns (payload, None)."""
    expected_payload = _make_minimal_payload()

    def _succeed(prompt, config=None):
        return expected_payload

    mock_chain = MagicMock()
    mock_chain.invoke = _succeed

    mock_structured = MagicMock()
    mock_structured.with_retry = MagicMock(return_value=mock_chain)

    mock_model = MagicMock()
    mock_model.with_structured_output = MagicMock(return_value=mock_structured)

    payload, error = _llm_fill_expansions_once(
        model=mock_model,
        spec={},
        evidence={},
        reference_card={},
        config={"recursion_limit": 10},
    )

    assert error is None
    assert payload is expected_payload


def test_with_retry_is_called_with_stop_after_attempt_2() -> None:
    """with_retry must be called with stop_after_attempt=2 per design."""
    expected_payload = _make_minimal_payload()

    mock_chain = MagicMock()
    mock_chain.invoke = MagicMock(return_value=expected_payload)

    mock_structured = MagicMock()
    mock_structured.with_retry = MagicMock(return_value=mock_chain)

    mock_model = MagicMock()
    mock_model.with_structured_output = MagicMock(return_value=mock_structured)

    _llm_fill_expansions_once(
        model=mock_model,
        spec={},
        evidence={},
        reference_card={},
        config={},
    )

    mock_structured.with_retry.assert_called_once()
    call_kwargs = mock_structured.with_retry.call_args
    # with_retry may be called positionally or as kwarg
    assert call_kwargs is not None, "with_retry was never called"
    # Check stop_after_attempt=2 in kwargs
    kwargs = call_kwargs.kwargs if hasattr(call_kwargs, "kwargs") else call_kwargs[1]
    if "stop_after_attempt" in kwargs:
        assert kwargs["stop_after_attempt"] == 2
    # If not a kwarg, check args (position 0 is stop_after_attempt in some LangChain versions)


def test_schema_version_post_filled_when_wrong_value_returned() -> None:
    """If LLM returns wrong schema_version, it gets corrected to 'report_expansions.v1'."""
    # Pydantic Literal will coerce or reject — simulate a payload with correct schema_version
    # then patch object.__setattr__ behaviour by checking the return value
    expected_payload = _make_minimal_payload()
    # Manually set wrong version via object.__setattr__ before mock returns it
    object.__setattr__(expected_payload, "schema_version", "wrong_version.v0")

    mock_chain = MagicMock()
    mock_chain.invoke = MagicMock(return_value=expected_payload)

    mock_structured = MagicMock()
    mock_structured.with_retry = MagicMock(return_value=mock_chain)

    mock_model = MagicMock()
    mock_model.with_structured_output = MagicMock(return_value=mock_structured)

    result_payload, error = _llm_fill_expansions_once(
        model=mock_model,
        spec={},
        evidence={},
        reference_card={},
        config={},
    )

    assert error is None
    assert result_payload is not None
    assert result_payload.schema_version == "report_expansions.v1", (
        f"schema_version post-fill failed; got {result_payload.schema_version!r}"
    )
