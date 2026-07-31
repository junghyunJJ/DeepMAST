from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from src.agents.deep_interpreter.reporter_recovery import (
    DEFAULT_REPORTER_ATTEMPT_TIMEOUT_SECONDS,
    ReporterRecoveryError,
    inspect_reporter_completion,
    reporter_attempt_timeout_seconds,
    run_reporter_with_recovery,
)


def _write_reporter_outputs(data_dir: Path, *, status: str, errors: int) -> None:
    (data_dir / "synthesis.md").write_text(
        "# Synthesis\n\n## Executive Summary\n\nGrounded narrative.\n",
        encoding="utf-8",
    )
    (data_dir / "synthesis_validation.json").write_text(
        json.dumps(
            {
                "synthesis_guardrail": {
                    "status": status,
                    "final_error_count": errors,
                }
            }
        ),
        encoding="utf-8",
    )
    (data_dir / "synthesis_targets.json").write_text("{}", encoding="utf-8")
    (data_dir / "CCI_Analysis_Report.html").write_text(
        "<html>report</html>",
        encoding="utf-8",
    )


def test_reporter_attempt_timeout_seconds_accepts_positive_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REPORTER_ATTEMPT_TIMEOUT_SECONDS", "12.5")

    assert reporter_attempt_timeout_seconds() == 12.5


@pytest.mark.parametrize("value", ["nan", "inf"])
def test_reporter_attempt_timeout_seconds_rejects_non_finite_override(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("REPORTER_ATTEMPT_TIMEOUT_SECONDS", value)

    assert (
        reporter_attempt_timeout_seconds()
        == DEFAULT_REPORTER_ATTEMPT_TIMEOUT_SECONDS
    )


def test_inspect_reporter_completion_requires_guardrail_pass(tmp_path: Path) -> None:
    _write_reporter_outputs(tmp_path, status="failed", errors=1)

    result = inspect_reporter_completion(tmp_path)

    assert result["complete"] is False
    assert result["guardrail_status"] == "failed"
    assert result["final_error_count"] == 1


def test_inspect_reporter_completion_accepts_complete_pass(tmp_path: Path) -> None:
    _write_reporter_outputs(tmp_path, status="passed", errors=0)

    result = inspect_reporter_completion(tmp_path)

    assert result["complete"] is True
    assert result["missing_outputs"] == []


@pytest.mark.asyncio
async def test_reporter_recovery_uses_fresh_context_once(tmp_path: Path) -> None:
    prompts: list[str] = []

    async def invoke(description: str) -> dict[str, list[dict[str, str]]]:
        prompts.append(description)
        if len(prompts) == 1:
            (tmp_path / "synthesis.md").write_text(
                "<p>Unsupported fragment</p>",
                encoding="utf-8",
            )
            (tmp_path / "synthesis_validation.json").write_text(
                json.dumps(
                    {
                        "synthesis_guardrail": {
                            "status": "failed",
                            "final_error_count": 1,
                        }
                    }
                ),
                encoding="utf-8",
            )
        else:
            _write_reporter_outputs(tmp_path, status="passed", errors=0)
        return {
            "messages": [
                {"role": "assistant", "content": f"attempt-{len(prompts)}"}
            ]
        }

    result = await run_reporter_with_recovery(
        invoke=invoke,
        initial_description="normal reporter request",
        data_dir=tmp_path,
        timeout_seconds=1,
    )

    assert result["messages"][-1]["content"] == "attempt-2"
    assert prompts[0] == "normal reporter request"
    assert prompts[1].startswith("[REPORTER_RECOVERY]")
    assert "tool results above" not in prompts[1]
    assert "prepare_rag_literature" in prompts[1]
    assert (tmp_path / "synthesis_reporter_attempt1.md").read_text(
        encoding="utf-8"
    ) == "<p>Unsupported fragment</p>"
    audit = json.loads((tmp_path / "reporter_recovery.json").read_text(encoding="utf-8"))
    assert audit["status"] == "passed"
    assert audit["attempt_count"] == 2
    assert audit["recovery_used"] is True


@pytest.mark.asyncio
async def test_reporter_recovery_retries_once_after_timeout(tmp_path: Path) -> None:
    prompts: list[str] = []
    never_finishes = asyncio.Event()

    async def invoke(description: str) -> dict[str, list[dict[str, str]]]:
        prompts.append(description)
        if len(prompts) == 1:
            await never_finishes.wait()
        _write_reporter_outputs(tmp_path, status="passed", errors=0)
        return {
            "messages": [
                {"role": "assistant", "content": f"attempt-{len(prompts)}"}
            ]
        }

    result = await run_reporter_with_recovery(
        invoke=invoke,
        initial_description="normal reporter request",
        data_dir=tmp_path,
        timeout_seconds=0.01,
    )

    assert result["messages"][-1]["content"] == "attempt-2"
    assert len(prompts) == 2
    audit = json.loads((tmp_path / "reporter_recovery.json").read_text(encoding="utf-8"))
    assert audit["status"] == "passed"
    assert audit["attempts"][0]["timed_out"] is True
    assert audit["recovery_used"] is True


@pytest.mark.asyncio
async def test_reporter_recovery_raises_after_second_invalid_attempt(
    tmp_path: Path,
) -> None:
    prompts: list[str] = []

    async def invoke(description: str) -> dict[str, list[dict[str, str]]]:
        prompts.append(description)
        _write_reporter_outputs(tmp_path, status="failed", errors=1)
        return {
            "messages": [
                {"role": "assistant", "content": f"attempt-{len(prompts)}"}
            ]
        }

    with pytest.raises(ReporterRecoveryError):
        await run_reporter_with_recovery(
            invoke=invoke,
            initial_description="normal reporter request",
            data_dir=tmp_path,
            timeout_seconds=1,
        )

    assert len(prompts) == 2
    audit = json.loads((tmp_path / "reporter_recovery.json").read_text(encoding="utf-8"))
    assert audit["status"] == "failed"
    assert audit["attempt_count"] == 2
    assert audit["recovery_used"] is True
