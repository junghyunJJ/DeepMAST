#!/usr/bin/env python3
"""Convenience runner for the canonical guarded fixed-dataset workflow."""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.drug_target.agent import DrugTargetConfig, create_drug_target_agent
from src.agents.drug_target.report_guardrails import clear_derived_report_artifacts
from scripts.run_report_writer_only import guarded_run_succeeded

DATA_DIR = str(PROJECT_ROOT / "res_bc_ollama")
DISEASE = "breast cancer"
PROVIDER = "openrouter"


async def main() -> int:
    data_dir = Path(DATA_DIR).expanduser().resolve()
    if not (data_dir / "lr_candidates.json").exists():
        print(f"ERROR: lr_candidates.json not found at {data_dir / 'lr_candidates.json'}")
        return 1
    clear_derived_report_artifacts(data_dir, include_audits=True, include_sources=True)
    backend = None
    try:
        agent, backend = create_drug_target_agent(
            DrugTargetConfig(
                provider=PROVIDER,
                data_dir=str(data_dir),
                disease=DISEASE,
                workflow_mode="guarded_report",
            )
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
        if backend is not None and hasattr(backend, "cleanup"):
            backend.cleanup()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
