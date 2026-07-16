#!/usr/bin/env python3
"""Render the guarded hybrid report from existing evidence."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.drug_target.agent import DrugTargetConfig, create_guarded_report_writer
from src.agents.drug_target.report_guardrails import clear_derived_report_artifacts

REQUIRED_GUARDED_ARTIFACTS = (
    "drug.md",
    "target_assessment.json",
    "drug_report_validation_initial.json",
    "drug_report_validation_final.json",
    "part4_candidate_selection.json",
    "part4_therapeutic_synthesis.md",
    "drug_report.html",
)


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


def infer_timeout_phase(data_dir: Path) -> str:
    if (data_dir / "drug_report_validation_final.json").is_file():
        return "publication"
    if (data_dir / "report_sections.json").is_file():
        return "guardrail_or_publication"
    return "report_writer"


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
    await asyncio.to_thread(
        clear_derived_report_artifacts,
        data_dir,
        include_audits=True,
        include_sources=True,
    )
    config = DrugTargetConfig(
        provider=args.provider,
        model=args.model,
        request_timeout_seconds=args.request_timeout_seconds,
        data_dir=str(data_dir),
        disease=args.disease,
        workflow_mode="guarded_report",
    )
    report_writer = create_guarded_report_writer(config)
    writer_input = {
        "messages": [
            {
                "role": "user",
                "content": (
                    "Render guarded hybrid report from existing evidence. "
                    f"Data dir: {data_dir}. Disease: {args.disease}."
                ),
            }
        ]
    }
    try:
        result = await asyncio.wait_for(
            report_writer.ainvoke(writer_input),
            timeout=args.run_timeout_seconds,
        )
    except TimeoutError:
        phase = infer_timeout_phase(data_dir)
        model_label = args.model or "default"
        print(
            "ERROR: guarded report timed out after "
            f"{args.run_timeout_seconds}s in phase={phase} "
            f"provider={args.provider} model={model_label}",
            file=sys.stderr,
        )
        return 1
    if guarded_run_succeeded(data_dir):
        print("DONE")
        return 0
    print("ERROR: guarded report audit or required artifacts failed")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
