#!/usr/bin/env python3
"""Run Drug Target Assessment Agent on res_bc_ollama/ data.

Executes the full 2-subagent pipeline (evidence_assessor → report_writer)
to generate drug.md from lr_candidates.json.
"""

import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from src.agents.drug_target.agent import create_drug_target_agent, DrugTargetConfig

# ── Configuration ──────────────────────────────────────────────────────
DATA_DIR = str(PROJECT_ROOT / "res_bc_ollama")
DISEASE = "breast cancer"
PROVIDER = "openrouter"


async def main():
    print("=" * 70)
    print("Drug Target Assessment Agent — Breast Cancer")
    print("=" * 70)
    print(f"  Provider: {PROVIDER}")
    print(f"  Data dir: {DATA_DIR}")
    print(f"  Disease:  {DISEASE}")
    print()

    # Verify lr_candidates.json exists
    lr_path = Path(DATA_DIR) / "lr_candidates.json"
    if not lr_path.exists():
        print(f"ERROR: lr_candidates.json not found at {lr_path}")
        sys.exit(1)

    lr_data = json.loads(lr_path.read_text())
    n_pairs = len(lr_data.get("pairs", []))
    print(f"  L-R pairs: {n_pairs}")
    print()

    # Create agent
    config = DrugTargetConfig(
        provider=PROVIDER,
        data_dir=DATA_DIR,
        disease=DISEASE,
    )

    print("Creating Drug Target Agent...")
    t0 = time.time()
    agent, backend = create_drug_target_agent(config)
    print(f"  Agent created in {time.time() - t0:.1f}s")

    try:
        # Build initial message
        initial_message = (
            f"Assess therapeutic potential of L-R pair genes in {DATA_DIR}.\n\n"
            f"Disease context: {DISEASE}\n"
            f"Input files: lr_candidates.json\n"
            f"Output: target_assessment.json and drug.md\n\n"
            f"Execute the full evidence_assessor → report_writer pipeline."
        )

        print("\nInvoking agent...")
        print("-" * 70)

        result = await agent.ainvoke(
            {
                "messages": [{
                    "role": "user",
                    "content": initial_message,
                }]
            },
            config={"configurable": {"thread_id": str(uuid.uuid4())}},
        )

        elapsed = time.time() - t0
        print("-" * 70)
        print(f"\nAgent completed in {elapsed / 60:.1f} minutes")

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

        # Print evidence file count
        evidence_dir = Path(DATA_DIR) / "evidence"
        if evidence_dir.exists():
            n_files = len(list(evidence_dir.glob("*.json")))
            print(f"\nEvidence files: {n_files}")

    finally:
        if backend:
            backend.cleanup()

    print(f"\n{'=' * 70}")
    print("DONE!")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    asyncio.run(main())
