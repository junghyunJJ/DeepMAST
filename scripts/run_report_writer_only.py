#!/usr/bin/env python3
"""Render the guarded hybrid report from existing evidence."""

from __future__ import annotations

import argparse
import asyncio
import json
import multiprocessing
import os
import sys
import time
from queue import Empty
from pathlib import Path
from typing import Any, NoReturn, cast

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.runnables import RunnableConfig

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


class ReportWriterTraceCallback(BaseCallbackHandler):
    def __init__(self, trace_file: str) -> None:
        self._file = Path(trace_file).open("a", encoding="utf-8")

    def _write(self, event: str, **fields: object) -> None:
        self._file.write(json.dumps({"event": event, "at": time.time(), **fields}) + "\n")
        self._file.flush()

    def on_chat_model_start(self, serialized: dict[str, Any], messages: list[list[Any]], **_kwargs: Any) -> None:
        self._write("llm_start")

    def on_llm_end(self, response: Any, **_kwargs: Any) -> None:
        self._write("llm_end")

    def on_llm_error(self, error: BaseException, **_kwargs: Any) -> None:
        self._write("llm_error", error=type(error).__name__)

    def on_tool_start(self, serialized: dict[str, Any], input_str: str, **_kwargs: Any) -> None:
        tool = serialized.get("name")
        self._write("tool_start", tool=tool if isinstance(tool, str) else "unknown")

    def on_tool_end(self, output: Any, **_kwargs: Any) -> None:
        self._write("tool_end")

    def on_tool_error(self, error: BaseException, **_kwargs: Any) -> None:
        self._write("tool_error", error=type(error).__name__)

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render guarded hybrid report from existing evidence")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--disease", required=True)
    parser.add_argument("--provider", default="ollama")
    parser.add_argument("--model")
    parser.add_argument("--request-timeout-seconds", type=float, default=600)
    parser.add_argument("--run-timeout-seconds", type=float, default=1800)
    parser.add_argument("--trace-file", type=Path)
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


def _resolve_trace_file(data_dir: Path, trace_file: Path | None) -> str | None:
    if trace_file is None:
        return None
    resolved = trace_file.expanduser().resolve()
    if resolved.is_relative_to(data_dir):
        raise ValueError("trace file must be outside data directory")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return str(resolved)


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
    trace_file: str | None,
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
        callback = ReportWriterTraceCallback(trace_file) if trace_file else None
        try:
            if callback is None:
                asyncio.run(report_writer.ainvoke(_writer_input(data_dir, disease)))
            else:
                invoke_config: RunnableConfig = {"callbacks": [callback]}
                asyncio.run(report_writer.ainvoke(_writer_input(data_dir, disease), config=invoke_config))
        finally:
            if callback:
                callback.close()
    except Exception as exc:
        results.put(("error", f"{type(exc).__name__}: {exc}"))
    else:
        results.put(("success", ""))


async def _run_guarded_writer_with_deadline(
    *,
    data_dir: Path,
    args: argparse.Namespace,
    trace_file: str | None,
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
            trace_file,
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
    try:
        trace_file = _resolve_trace_file(data_dir, args.trace_file)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    await asyncio.to_thread(clear_guarded_report_run_artifacts, data_dir)
    status, detail = await _run_guarded_writer_with_deadline(
        data_dir=data_dir,
        args=args,
        trace_file=trace_file,
    )
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
