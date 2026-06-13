from __future__ import annotations

import time

import pytest

from scripts import run_drug_target_traced as traced
from scripts.run_drug_target_traced import _close_async_stream


class _ClosableStream:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_close_async_stream_awaits_aclose() -> None:
    stream = _ClosableStream()

    await _close_async_stream(stream)

    assert stream.closed is True


@pytest.mark.asyncio
async def test_close_async_stream_ignores_non_closable_object() -> None:
    await _close_async_stream(object())


def test_skip_hypothesis_quality_after_budget_abort_when_report_missing(tmp_path) -> None:
    report_path = tmp_path / "evidence" / "hypothesis_report.json"

    assert (
        traced._should_skip_hypothesis_quality_after_budget_abort(
            hypothesis_budget_aborted=True,
            hypothesis_path=report_path,
            run_started_at=time.time(),
        )
        is True
    )


def test_do_not_skip_hypothesis_quality_after_budget_abort_when_report_is_fresh(
    tmp_path,
) -> None:
    run_started_at = time.time()
    report_path = tmp_path / "evidence" / "hypothesis_report.json"
    report_path.parent.mkdir()
    report_path.write_text("{}", encoding="utf-8")

    assert (
        traced._should_skip_hypothesis_quality_after_budget_abort(
            hypothesis_budget_aborted=True,
            hypothesis_path=report_path,
            run_started_at=run_started_at,
        )
        is False
    )


def test_do_not_skip_hypothesis_quality_without_budget_abort(tmp_path) -> None:
    report_path = tmp_path / "evidence" / "hypothesis_report.json"

    assert (
        traced._should_skip_hypothesis_quality_after_budget_abort(
            hypothesis_budget_aborted=False,
            hypothesis_path=report_path,
            run_started_at=time.time(),
        )
        is False
    )
