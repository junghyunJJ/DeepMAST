#!/usr/bin/env python3
"""Run the canonical guarded report writer against existing evidence."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.model import create_llm
from src.agents.drug_target.agent import DrugTargetConfig, create_drug_target_agent
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
    parser = argparse.ArgumentParser(description="Run guarded report_writer on existing evidence")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--disease", required=True)
    parser.add_argument("--provider", default="ollama")
    parser.add_argument("--model")
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
        and publication.get("status") in {"passed", "published"}
        and all((data_dir / name).is_file() and (data_dir / name).stat().st_size > 0 for name in REQUIRED_GUARDED_ARTIFACTS)
    )


async def main() -> int:
    args = parse_args()
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
    model = create_llm(provider=args.provider, model=args.model) if args.model else None
    config = DrugTargetConfig(
        provider=args.provider,
        data_dir=str(data_dir),
        disease=args.disease,
        workflow_mode="guarded_report",
        use_checkpointer=True,
        report_writer_resume_instruction=(
            "Write target_assessment.json and a complete drug.md from evidence already "
            f"on disk. Data dir: {data_dir}"
        ),
        subagent_models={"report_writer": model} if model is not None else None,
    )
    old_skip = os.environ.get("DRUG_TARGET_SKIP_EVIDENCE_ASSESSOR")
    os.environ["DRUG_TARGET_SKIP_EVIDENCE_ASSESSOR"] = "1"
    backend = None
    try:
        agent, backend = create_drug_target_agent(config)
        await agent.ainvoke(
            {"messages": [{"role": "user", "content": "Write the guarded report from existing evidence."}]},
            config={"configurable": {"thread_id": str(uuid.uuid4())}},
        )
    finally:
        if old_skip is None:
            os.environ.pop("DRUG_TARGET_SKIP_EVIDENCE_ASSESSOR", None)
        else:
            os.environ["DRUG_TARGET_SKIP_EVIDENCE_ASSESSOR"] = old_skip
        if backend is not None and hasattr(backend, "cleanup"):
            backend.cleanup()
    if guarded_run_succeeded(data_dir):
        print("DONE")
        return 0
    print("ERROR: guarded report audit or required artifacts failed")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
