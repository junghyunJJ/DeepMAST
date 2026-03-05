#!/usr/bin/env python3
"""Run ONLY the report_writer subagent on existing evidence files.

Skips evidence_assessor entirely — uses pre-collected evidence in res_bc_ollama/evidence/.
Generates target_assessment.json and drug.md.
"""

import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from deepagents import create_deep_agent
from langgraph.checkpoint.memory import MemorySaver

from src.agents.model import create_llm
from src.agents.drug_target.subagents.prompts import SUBAGENT_PROMPTS
from src.agents.drug_target.tools import (
    load_evidence_files,
    save_target_assessment,
    sequential_thinking,
    think_tool,
    validate_quality,
)

DATA_DIR = str(PROJECT_ROOT / "res_bc_ollama")
DISEASE = "breast cancer"
PROVIDER = "openrouter"


async def main():
    print("=" * 70)
    print("Report Writer Only — Breast Cancer")
    print("=" * 70)
    print(f"  Provider: {PROVIDER}")
    print(f"  Data dir: {DATA_DIR}")
    print()

    # Verify evidence files exist
    evidence_dir = Path(DATA_DIR) / "evidence"
    n_files = len(list(evidence_dir.glob("*.json")))
    print(f"  Evidence files: {n_files}")
    if n_files < 5:
        print("ERROR: Not enough evidence files. Run full pipeline first.")
        sys.exit(1)

    # Create a minimal agent with just report_writer as orchestrator
    llm = create_llm(provider=PROVIDER)

    tools = [
        load_evidence_files,
        save_target_assessment,
        sequential_thinking,
        think_tool,
        validate_quality,
    ]

    data_dir_note = (
        f"\n\n## Data Directory\n"
        f"The data directory for this session is: `{DATA_DIR}`\n"
        f"Pass this exact path as `data_dir` to all tool calls.\n"
    )

    system_prompt = SUBAGENT_PROMPTS["report_writer"] + data_dir_note

    agent = create_deep_agent(
        model=llm,
        tools=tools,
        subagents=[],
        checkpointer=MemorySaver(),
        system_prompt=system_prompt,
    )

    t0 = time.time()
    print("\nInvoking report_writer agent...")
    print("-" * 70)

    initial_message = (
        f"Generate drug.md for {DISEASE} therapeutic target assessment.\n\n"
        f"Data directory: {DATA_DIR}\n"
        f"All evidence files are already collected in {DATA_DIR}/evidence/.\n\n"
        f"Steps:\n"
        f"1. Call load_evidence_files(data_dir='{DATA_DIR}') to load all evidence\n"
        f"2. Plan the document structure\n"
        f"3. Call save_target_assessment to create target_assessment.json\n"
        f"4. Write drug.md using write_file tool\n"
    )

    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": initial_message}]},
        config={"configurable": {"thread_id": str(uuid.uuid4())}},
    )

    elapsed = time.time() - t0
    print("-" * 70)
    print(f"\nCompleted in {elapsed / 60:.1f} minutes")

    # Check outputs
    drug_md = Path(DATA_DIR) / "drug.md"
    target_json = Path(DATA_DIR) / "target_assessment.json"

    if drug_md.exists():
        content = drug_md.read_text()
        print(f"\ndrug.md generated ({len(content)} chars)")
        print(f"  Path: {drug_md}")
    else:
        print("\nWARNING: drug.md was not generated")

    if target_json.exists():
        print(f"target_assessment.json generated")
        print(f"  Path: {target_json}")

    print(f"\n{'=' * 70}")
    print("DONE!")


if __name__ == "__main__":
    asyncio.run(main())
