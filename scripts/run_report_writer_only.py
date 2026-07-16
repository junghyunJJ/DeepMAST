#!/usr/bin/env python3
"""Render the guarded hybrid report from existing evidence."""

from __future__ import annotations

import argparse
import asyncio
import json
import multiprocessing
import os
import sys
from queue import Empty
from pathlib import Path
from typing import Any, NoReturn, cast

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.drug_target.agent import (
    DrugTargetConfig,
    Provider,
    create_guarded_report_writer,
)
from src.agents.drug_target.middleware import clear_guarded_report_run_artifacts

REQUIRED_GUARDED_ARTIFACTS = (
    "drug.md",
    "target_assessment.json",
    "drug_report_validation_initial.json",
    "drug_report_validation_final.json",
    "part4_candidate_selection.json",
    "part4_therapeutic_synthesis.md",
    "drug_report.html",
)
_PROCESS_STOP_SECONDS = 0.1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render guarded hybrid report from existing evidence")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--disease", required=True)
    parser.add_argument("--provider", default="ollama")
    parser.add_argument("--model")
    parser.add_argument("--request-timeout-seconds", type=float, default=600)
    parser.add_argument("--run-timeout-seconds", type=float, default=1800)
    return parser.parse_args()


def guarded_run_succeeded(data_dir: Path) -> bool:
    audit_path = data_dir / "drug_report_validation_final.json"
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    publication = audit.get("publication") if isinstance(audit, dict) else {}
    return (
        audit.get("valid") is True
        and isinstance(publication, dict)
        and publication.get("status") == "passed"
        and all((data_dir / name).is_file() and (data_dir / name).stat().st_size > 0 for name in REQUIRED_GUARDED_ARTIFACTS)
    )


def _validate_timeouts(args: argparse.Namespace) -> None:
    if args.request_timeout_seconds <= 0 or args.run_timeout_seconds <= 0:
        raise ValueError("request and run timeouts must be positive")
    if args.request_timeout_seconds >= args.run_timeout_seconds:
        raise ValueError("request timeout must be shorter than run timeout")


def _infer_timeout_phase(data_dir: Path) -> str:
    if (data_dir / "drug_report_validation_final.json").is_file():
        return "publication"
    if (data_dir / "report_sections.json").is_file():
        return "guardrail_or_publication"
    return "report_writer"


def _writer_input(data_dir: str, disease: str) -> dict[str, list[dict[str, str]]]:
    return {
        "messages": [
            {
                "role": "user",
                "content": (
                    "Render guarded hybrid report from existing evidence. "
                    f"Data dir: {data_dir}. Disease: {disease}."
                ),
            }
        ]
    }


def _process_context() -> Any:
    return multiprocessing.get_context()


def _force_exit() -> NoReturn:
    os._exit(1)


async def _stop_child_process(process: Any) -> bool:
    try:
        if not process.is_alive():
            return True
        process.terminate()
        await asyncio.to_thread(process.join, _PROCESS_STOP_SECONDS)
        if process.is_alive():
            process.kill()
            await asyncio.to_thread(process.join, _PROCESS_STOP_SECONDS)
        return not process.is_alive()
    except Exception:
        return False


async def _require_child_stop(process: Any, data_dir: Path) -> None:
    if not await _stop_child_process(process):
        try:
            await asyncio.to_thread(clear_guarded_report_run_artifacts, data_dir)
        finally:
            _force_exit()


def _run_guarded_writer_child(
    results: Any,
    data_dir: str,
    disease: str,
    provider: str,
    model: str | None,
    request_timeout_seconds: float,
) -> None:
    """Construct and invoke the diagnostic writer outside the parent deadline."""
    try:
        report_writer = create_guarded_report_writer(
            DrugTargetConfig(
                provider=cast(Provider, provider),
                model=model,
                request_timeout_seconds=request_timeout_seconds,
                data_dir=data_dir,
                disease=disease,
                workflow_mode="guarded_report",
                subagent_models={},
            )
        )
        asyncio.run(report_writer.ainvoke(_writer_input(data_dir, disease)))
    except Exception as exc:
        results.put(("error", f"{type(exc).__name__}: {exc}"))
    else:
        results.put(("success", ""))


async def _run_guarded_writer_with_deadline(
    *,
    data_dir: Path,
    args: argparse.Namespace,
) -> tuple[str, str]:
    context = _process_context()
    results = context.Queue()
    process = context.Process(
        target=_run_guarded_writer_child,
        args=(
            results,
            str(data_dir),
            args.disease,
            args.provider,
            args.model,
            args.request_timeout_seconds,
        ),
    )
    stop_attempted = False
    try:
        try:
            process.start()
        except Exception as exc:
            return "error", f"{type(exc).__name__}: {exc}"
        try:
            await asyncio.wait_for(
                asyncio.to_thread(process.join, args.run_timeout_seconds),
                timeout=args.run_timeout_seconds,
            )
        except TimeoutError:
            stop_attempted = True
            await _require_child_stop(process, data_dir)
            return "timeout", ""
        if process.is_alive():
            stop_attempted = True
            await _require_child_stop(process, data_dir)
            return "timeout", ""

        try:
            return await asyncio.to_thread(results.get, True, 0.1)
        except Empty:
            return "error", "child exited without a result"
    finally:
        if not stop_attempted:
            await _require_child_stop(process, data_dir)
        results.close()
        results.join_thread()


async def main() -> int:
    args = parse_args()
    try:
        _validate_timeouts(args)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    data_dir = Path(args.data_dir).expanduser().resolve()
    if len(list((data_dir / "evidence").glob("*.json"))) < 5:
        print("ERROR: Not enough evidence files. Run evidence assessment first.")
        return 1
    await asyncio.to_thread(clear_guarded_report_run_artifacts, data_dir)
    status, detail = await _run_guarded_writer_with_deadline(data_dir=data_dir, args=args)
    if status == "timeout":
        phase = _infer_timeout_phase(data_dir)
        await asyncio.to_thread(clear_guarded_report_run_artifacts, data_dir)
        model_label = args.model or "default"
        print(
            "ERROR: guarded report timed out after "
            f"{args.run_timeout_seconds}s in phase={phase} "
            f"provider={args.provider} model={model_label}",
            file=sys.stderr,
        )
        return 1
    if status == "error":
        await asyncio.to_thread(clear_guarded_report_run_artifacts, data_dir)
        print(f"ERROR: guarded report writer failed: {detail}", file=sys.stderr)
        return 1
    if guarded_run_succeeded(data_dir):
        print("DONE")
        return 0
    print("ERROR: guarded report audit or required artifacts failed")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
