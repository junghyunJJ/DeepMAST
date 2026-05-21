"""#18e — CP-P1-015: LangSmith config propagation through _llm_fill_expansions_once.

Verifies that the config kwarg passed to _llm_fill_expansions_once is forwarded
verbatim to model.invoke(..., config=config).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.agents.drug_target.finalize_report import _llm_fill_expansions_once
from src.agents.drug_target.tools.report_expansion_schema import ReportExpansionsPayload


def _make_minimal_payload() -> ReportExpansionsPayload:
    """Build a minimal valid ReportExpansionsPayload for mock returns."""
    return ReportExpansionsPayload(
        schema_version="report_expansions.v1",
        slots=[],
    )


def test_config_forwarded_to_model_invoke() -> None:
    """_llm_fill_expansions_once must forward config to chain.invoke(prompt, config=config)."""
    captured: dict = {}
    test_config = {"recursion_limit": 99, "configurable": {"run_id": "abc-123"}}

    payload_instance = _make_minimal_payload()

    # Build mock chain: model -> with_structured_output -> with_retry -> invoke
    mock_chain = MagicMock()
    mock_chain.invoke = MagicMock(return_value=payload_instance)

    mock_with_retry = MagicMock()
    mock_with_retry.invoke = mock_chain.invoke

    mock_structured = MagicMock()
    mock_structured.with_retry = MagicMock(return_value=mock_with_retry)

    mock_model = MagicMock()
    mock_model.with_structured_output = MagicMock(return_value=mock_structured)
    mock_model.bind = MagicMock(return_value=mock_model)

    # Intercept the invoke call to capture what config kwarg was passed
    def _capturing_invoke(prompt, config=None):
        captured["config"] = config
        return payload_instance

    mock_with_retry.invoke = _capturing_invoke

    result_payload, error = _llm_fill_expansions_once(
        model=mock_model,
        spec={},
        evidence={},
        reference_card={},
        config=test_config,
    )

    assert error is None, f"Expected success, got error: {error}"
    assert result_payload is not None

    # The config passed to invoke must contain the run_id
    assert "config" in captured, (
        "_llm_fill_expansions_once never called chain.invoke — config not captured"
    )
    forwarded_config = captured["config"]
    assert forwarded_config is test_config or (
        isinstance(forwarded_config, dict)
        and forwarded_config.get("configurable", {}).get("run_id") == "abc-123"
    ), (
        f"Config not forwarded correctly. Expected run_id='abc-123' in "
        f"configurable, got: {forwarded_config!r}"
    )


def test_config_with_thread_id_is_preserved() -> None:
    """thread_id inside configurable must survive the chain call."""
    test_config = {
        "recursion_limit": 50,
        "configurable": {"thread_id": "thread-xyz", "run_id": "run-abc"},
    }
    payload_instance = _make_minimal_payload()
    captured: dict = {}

    mock_with_retry = MagicMock()

    def _capturing_invoke(prompt, config=None):
        captured["config"] = config
        return payload_instance

    mock_with_retry.invoke = _capturing_invoke

    mock_structured = MagicMock()
    mock_structured.with_retry = MagicMock(return_value=mock_with_retry)

    mock_model = MagicMock()
    mock_model.with_structured_output = MagicMock(return_value=mock_structured)

    _llm_fill_expansions_once(
        model=mock_model,
        spec={"required_slot_ids": []},
        evidence={},
        reference_card={},
        config=test_config,
    )

    forwarded = captured.get("config")
    assert forwarded is not None, "invoke was not called with config kwarg"
    if isinstance(forwarded, dict):
        assert forwarded.get("configurable", {}).get("thread_id") == "thread-xyz"
