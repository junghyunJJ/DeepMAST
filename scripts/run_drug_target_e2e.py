#!/usr/bin/env python
"""Canonical guarded E2E smoke runner: evidence_assessor -> report_writer."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.drug_target.agent import DrugTargetConfig, create_drug_target_agent
from scripts.run_report_writer_only import guarded_run_succeeded

MOCK_LR_CANDIDATES = {
    "disease": "breast cancer",
    "disease_context": "Triple-negative breast cancer",
    "pairs": [{"ligand": "TGFB1", "receptor": "TGFBR2", "score": 0.95}],
}


async def main() -> int:
    data_dir = Path(tempfile.mkdtemp(prefix="drug_target_e2e_"))
    (data_dir / "lr_candidates.json").write_text(json.dumps(MOCK_LR_CANDIDATES), encoding="utf-8")
    old_data_dir = os.environ.get("DRUG_TARGET_DATA_DIR")
    os.environ["DRUG_TARGET_DATA_DIR"] = str(data_dir)
    backend = None
    try:
        config = DrugTargetConfig(
            provider="openrouter",
            data_dir=str(data_dir),
            disease="breast cancer",
            workflow_mode="guarded_report",
            use_checkpointer=True,
        )
        agent, backend = create_drug_target_agent(config)
        try:
            await asyncio.wait_for(
                agent.ainvoke(
                    {"messages": [{"role": "user", "content": "Run the guarded drug target pipeline."}]},
                    config={"configurable": {"thread_id": str(uuid.uuid4())}},
                ),
                timeout=150 * 60,
            )
        except asyncio.TimeoutError:
            print("ERROR: guarded pipeline timed out")
            return 1
        if guarded_run_succeeded(data_dir):
            print("DONE")
            return 0
        print("ERROR: guarded report audit or required artifacts failed")
        return 1
    finally:
        if old_data_dir is None:
            os.environ.pop("DRUG_TARGET_DATA_DIR", None)
        else:
            os.environ["DRUG_TARGET_DATA_DIR"] = old_data_dir
        if backend is not None and hasattr(backend, "cleanup"):
            backend.cleanup()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
