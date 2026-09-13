from __future__ import annotations

import contextlib
import hashlib
import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from src.agents.deep_interpreter import report_guardrails
from src.agents.deep_interpreter import claim_rag_validation
from src.agents.deep_interpreter.middleware import report_guardrail as middleware_guardrail
from src.agents.deep_interpreter import reporter_recovery
from src.agents.deep_interpreter.tools import report as report_tool

REQUIRED_REPORT_FILES = (
    "part1_final.md",
    "part2_final.md",
    "part3_final.md",
    "synthesis.md",
    "CCI_Analysis_Report.html",
)


def _disabled_guardrail(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    return {
        "status": "disabled",
        "reason": "guardrail_ablation",
        "validation_performed": False,
    }


def _is_disabled_synthesis_validation(data_dir: str | Path) -> bool:
    path = Path(data_dir) / "synthesis_validation.json"
    try:
        guardrail = json.loads(path.read_text(encoding="utf-8")).get("synthesis_guardrail", {})
    except (OSError, ValueError):
        return False
    return isinstance(guardrail, dict) and guardrail.get("status") == "disabled" and guardrail.get("validation_performed") is False


@contextlib.contextmanager
def without_report_guardrails() -> Iterator[None]:
    original_middleware_run = middleware_guardrail.ReportGuardrailMiddleware._run
    original_module_run = middleware_guardrail.run_report_guardrail
    original_synthesis_run = report_tool._run_synthesis_guardrail_before_html
    original_synthesis_valid = reporter_recovery._valid_synthesis_validation
    original_completion = reporter_recovery.inspect_reporter_completion

    def middleware_run(_self: object) -> None:
        return None

    def synthesis_valid(data_dir: Path) -> bool:
        return _is_disabled_synthesis_validation(data_dir) or original_synthesis_valid(data_dir)

    def completion(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = original_completion(*args, **kwargs)
        data_dir = args[0] if args else kwargs["data_dir"]
        if _is_disabled_synthesis_validation(data_dir):
            result["complete"] = not result["missing_outputs"] and not result["invalid_outputs"] and not result["stale_outputs"]
        return result

    middleware_guardrail.ReportGuardrailMiddleware._run = middleware_run
    middleware_guardrail.run_report_guardrail = _disabled_guardrail
    report_tool._run_synthesis_guardrail_before_html = _disabled_guardrail
    reporter_recovery._valid_synthesis_validation = synthesis_valid
    reporter_recovery.inspect_reporter_completion = completion
    try:
        yield
    finally:
        middleware_guardrail.ReportGuardrailMiddleware._run = original_middleware_run
        middleware_guardrail.run_report_guardrail = original_module_run
        report_tool._run_synthesis_guardrail_before_html = original_synthesis_run
        reporter_recovery._valid_synthesis_validation = original_synthesis_valid
        reporter_recovery.inspect_reporter_completion = original_completion


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hashes(data_dir: Path) -> dict[str, str]:
    return {
        name: _sha256(data_dir / name)
        for name in REQUIRED_REPORT_FILES
        if (data_dir / name).is_file()
    }


def _missing_or_empty(data_dir: Path) -> list[str]:
    return [
        name
        for name in REQUIRED_REPORT_FILES
        if not (data_dir / name).is_file() or (data_dir / name).stat().st_size == 0
    ]


def _hard_error_count(issues: list[dict[str, Any]]) -> int:
    return sum(1 for issue in issues if issue.get("severity") == "error")


def _mutation_failure(
    *,
    hashes_before: dict[str, str],
    hashes_after: dict[str, str],
    elapsed_seconds: float,
) -> dict[str, Any] | None:
    if hashes_before == hashes_after:
        return None
    return {
        "status": "evaluation_failed",
        "complete": True,
        "usable": None,
        "hard_error_count": None,
        "issues": [
            {
                "severity": "error",
                "code": "report_mutated_by_evaluation",
            }
        ],
        "phases": {},
        "hashes_before": hashes_before,
        "hashes_after": hashes_after,
        "elapsed_seconds": round(elapsed_seconds, 3),
    }


def _incomplete_claim_issue(claims: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not claim_rag_validation._has_incomplete_judge_result(claims):
        return None
    for claim in claims:
        reason = str(claim.get("reason", ""))
        if claim_rag_validation._has_incomplete_judge_result([claim]):
            return {
                "severity": "error",
                "code": "claim_evaluation_incomplete",
                "file": claim.get("file"),
                "section": claim.get("section"),
                "reason": reason,
            }
    return None


def evaluate_report(data_dir: Path, provider: str = "ollama") -> dict[str, Any]:
    started = time.monotonic()
    data_dir = Path(data_dir).expanduser().resolve()
    hashes_before = _hashes(data_dir)
    missing = _missing_or_empty(data_dir)
    if missing:
        return {
            "status": "incomplete",
            "complete": False,
            "usable": False,
            "hard_error_count": None,
            "issues": [
                {
                    "severity": "error",
                    "code": "missing_required_artifact",
                    "file": name,
                }
                for name in missing
            ],
            "phases": {},
            "hashes_before": hashes_before,
            "hashes_after": _hashes(data_dir),
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }

    try:
        claim_cache: dict[str, list[dict[str, Any]]] = {}
        part_issues, part_claims, *_part_rest, part_phase = report_guardrails._validate_part_reports(
            data_dir,
            provider=provider,
            claim_cache=claim_cache,
            filenames=report_guardrails.REQUIRED_PART_FILES,
        )
        (
            synthesis_issues,
            synthesis_claims,
            *_synthesis_rest,
            synthesis_phase,
        ) = report_guardrails._validate_synthesis_guardrails(
            data_dir,
            provider=provider,
            claim_cache=claim_cache,
        )
        issues = [*part_issues, *synthesis_issues]
        hard_errors = _hard_error_count(issues)
        hashes_after = _hashes(data_dir)
        mutation = _mutation_failure(
            hashes_before=hashes_before,
            hashes_after=hashes_after,
            elapsed_seconds=time.monotonic() - started,
        )
        if mutation is not None:
            return mutation
        phases = {"parts": part_phase, "synthesis": synthesis_phase}
        incomplete_claim = _incomplete_claim_issue([*part_claims, *synthesis_claims])
        if incomplete_claim is not None:
            return {
                "status": "evaluation_failed",
                "complete": True,
                "usable": None,
                "hard_error_count": None,
                "issues": [incomplete_claim, *issues],
                "phases": phases,
                "hashes_before": hashes_before,
                "hashes_after": hashes_after,
                "elapsed_seconds": round(time.monotonic() - started, 3),
            }
        return {
            "status": "evaluated",
            "complete": True,
            "usable": hard_errors == 0,
            "hard_error_count": hard_errors,
            "issues": issues,
            "phases": phases,
            "hashes_before": hashes_before,
            "hashes_after": hashes_after,
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "evaluation_failed",
            "complete": True,
            "usable": None,
            "hard_error_count": None,
            "issues": [
                {
                    "severity": "error",
                    "code": "evaluation_failed",
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
            ],
            "phases": {},
            "hashes_before": hashes_before,
            "hashes_after": _hashes(data_dir),
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
