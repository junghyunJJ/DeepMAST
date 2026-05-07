from __future__ import annotations

from unittest.mock import patch


def test_get_subagents_constructs_hypothesis_retry_middleware_per_call(tmp_path) -> None:
    from src.agents.drug_target.subagents.configs import get_subagents
    from src.agents.drug_target.subagents.summarizer.middleware import (
        HypothesisRetryLoopMiddleware,
    )

    with patch(
        "src.agents.drug_target.subagents.configs.get_summarizer_subagent",
        return_value={"name": "summarizer", "runnable": object(), "description": ""},
    ):
        first = get_subagents(data_dir=str(tmp_path / "run_a"))
        second = get_subagents(data_dir=str(tmp_path / "run_b"))

    first_hyp = next(s for s in first if s["name"] == "hypothesis_writer")
    second_hyp = next(s for s in second if s["name"] == "hypothesis_writer")
    first_retry = next(
        m for m in first_hyp["middleware"] if isinstance(m, HypothesisRetryLoopMiddleware)
    )
    second_retry = next(
        m for m in second_hyp["middleware"] if isinstance(m, HypothesisRetryLoopMiddleware)
    )

    assert first_retry is not second_retry


def test_get_subagents_routes_data_dir_to_summarizer_subagent(tmp_path) -> None:
    from src.agents.drug_target.subagents.configs import get_subagents

    with patch(
        "src.agents.drug_target.subagents.configs.get_summarizer_subagent",
        return_value={"name": "summarizer", "runnable": object(), "description": ""},
    ) as mock_get_summarizer:
        get_subagents(data_dir=str(tmp_path))

    assert mock_get_summarizer.call_args.kwargs["data_dir"] == str(tmp_path)

