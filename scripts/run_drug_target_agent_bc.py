#!/usr/bin/env python3
"""Convenience runner for the canonical guarded fixed-dataset workflow."""

from __future__ import annotations

import asyncio
import argparse
import contextlib
import math
import os
import sys
import time
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.drug_target.agent import DrugTargetConfig, create_drug_target_agent
from src.agents.drug_target.report_guardrails import clear_derived_report_artifacts
from scripts.run_report_writer_only import guarded_run_succeeded


def _positive_seconds(value: str) -> float:
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("heartbeat seconds must be positive")
    return seconds


async def _emit_heartbeat(interval_seconds: float, started_at: float) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        elapsed = int(time.monotonic() - started_at)
        print(f"RUNNING elapsed_seconds={elapsed}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the guarded drug target pipeline for breast cancer")
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "res_bc_ollama")
    parser.add_argument("--disease", default="breast cancer")
    parser.add_argument("--provider", default="openrouter")
    parser.add_argument("--model")
    parser.add_argument("--skip-evidence-assessor", action="store_true")
    parser.add_argument(
        "--heartbeat-seconds",
        type=_positive_seconds,
        default=15.0,
        help="Print liveness while the guarded agent awaits model or tool work.",
    )
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    data_dir = args.data_dir.expanduser().resolve()
    if not (data_dir / "lr_candidates.json").exists():
        print(f"ERROR: lr_candidates.json not found at {data_dir / 'lr_candidates.json'}")
        return 1
    clear_derived_report_artifacts(data_dir, include_audits=True, include_sources=True)
    backend = None
    heartbeat_task: asyncio.Task[None] | None = None
    previous_skip_evidence_assessor = os.environ.get("DRUG_TARGET_SKIP_EVIDENCE_ASSESSOR")
    try:
        if args.skip_evidence_assessor:
            os.environ["DRUG_TARGET_SKIP_EVIDENCE_ASSESSOR"] = "1"
        agent, backend = create_drug_target_agent(
            DrugTargetConfig(
                provider=args.provider,
                model=args.model,
                data_dir=str(data_dir),
                disease=args.disease,
                workflow_mode="guarded_report",
            )
        )
        print("STARTED guarded BC pipeline", flush=True)
        started_at = time.monotonic()
        heartbeat_task = asyncio.create_task(
            _emit_heartbeat(args.heartbeat_seconds, started_at)
        )
        await agent.ainvoke(
            {"messages": [{"role": "user", "content": "Run the guarded drug target pipeline."}]},
            config={"configurable": {"thread_id": str(uuid.uuid4())}},
        )
        if guarded_run_succeeded(data_dir):
            print("DONE")
            return 0
        print("ERROR: guarded report audit or required artifacts failed")
        return 1
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    finally:
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task
        if previous_skip_evidence_assessor is None:
            os.environ.pop("DRUG_TARGET_SKIP_EVIDENCE_ASSESSOR", None)
        else:
            os.environ["DRUG_TARGET_SKIP_EVIDENCE_ASSESSOR"] = previous_skip_evidence_assessor
        cleanup = getattr(backend, "cleanup", None)
        if callable(cleanup):
            cleanup()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
