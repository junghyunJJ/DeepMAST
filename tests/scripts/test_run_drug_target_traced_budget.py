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


def test_hypothesis_budget_abort_message_detects_missing_report_after_evidence_ready(
    tmp_path,
) -> None:
    report_path = tmp_path / "evidence" / "hypothesis_report.json"

    message = traced._hypothesis_budget_abort_message(
        data_dir=tmp_path,
        hypothesis_path=report_path,
        evidence_ready_started_at=10.0,
        hypothesis_started_at=None,
        now=20.0,
        budget_seconds=10,
        run_started_at=0.0,
    )

    assert message is not None
    assert "evidence has been ready for 10s" in message
    assert "no fresh hypothesis_report.json was saved" in message


def test_hypothesis_budget_abort_message_detects_stalled_hypothesis_writer(
    tmp_path,
) -> None:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "assessment_results.json").write_text("{}", encoding="utf-8")
    (evidence_dir / "stage1_filter_results.json").write_text("[]", encoding="utf-8")

    message = traced._hypothesis_budget_abort_message(
        data_dir=tmp_path,
        hypothesis_path=evidence_dir / "hypothesis_report.json",
        evidence_ready_started_at=None,
        hypothesis_started_at=5.0,
        now=16.0,
        budget_seconds=10,
        run_started_at=0.0,
    )

    assert message is not None
    assert "hypothesis_writer stream exceeded 10s" in message
    assert "graph-level quality gate can handle recovery" in message


def test_hypothesis_budget_abort_message_ignores_fresh_report(tmp_path) -> None:
    run_started_at = time.time()
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    report_path = evidence_dir / "hypothesis_report.json"
    report_path.write_text("{}", encoding="utf-8")

    message = traced._hypothesis_budget_abort_message(
        data_dir=tmp_path,
        hypothesis_path=report_path,
        evidence_ready_started_at=10.0,
        hypothesis_started_at=10.0,
        now=30.0,
        budget_seconds=10,
        run_started_at=run_started_at,
    )

    assert message is None
