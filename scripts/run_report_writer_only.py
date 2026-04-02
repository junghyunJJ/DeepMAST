#!/usr/bin/env python3
"""Run ONLY the report_writer subagent on existing evidence files.

Skips evidence_assessor entirely — uses pre-collected evidence.
Generates target_assessment.json and drug.md.

Usage:
    python scripts/run_report_writer_only.py --data-dir res_ipf --disease "idiopathic pulmonary fibrosis"
    python scripts/run_report_writer_only.py --data-dir res_ipf --disease "IPF" --provider openrouter
    python scripts/run_report_writer_only.py --data-dir res_ipf --disease "IPF" --provider ollama --model qwen3.5:122b
"""

import argparse
import asyncio
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
    load_lr_candidates,
    load_evidence_files,
    validate_evidence_completeness,
    save_target_assessment,
    save_drug_md,
    sequential_thinking,
    think_tool,
    validate_quality,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run report_writer subagent only")
    p.add_argument("--data-dir", required=True, help="Data directory with evidence/")
    p.add_argument("--disease", required=True, help="Disease context")
    p.add_argument("--provider", default="ollama", help="LLM provider (default: ollama)")
    p.add_argument("--model", default=None, help="Model override (e.g. qwen3.5:122b)")
    return p.parse_args()


async def main():
    args = parse_args()
    data_dir = str(Path(args.data_dir).expanduser().resolve())

    print("=" * 70)
    print("Report Writer Only")
    print("=" * 70)
    print(f"  Provider: {args.provider}")
    print(f"  Model:    {args.model or 'default'}")
    print(f"  Data dir: {data_dir}")
    print(f"  Disease:  {args.disease}")
    print()

    # Verify evidence files exist
    evidence_dir = Path(data_dir) / "evidence"
    n_files = len(list(evidence_dir.glob("*.json")))
    print(f"  Evidence files: {n_files}")
    if n_files < 5:
        print("ERROR: Not enough evidence files. Run full pipeline first.")
        sys.exit(1)

    # Create LLM
    llm_kwargs = {}
    if args.model:
        llm_kwargs["model"] = args.model
    llm = create_llm(provider=args.provider, **llm_kwargs)

    tools = [
        load_lr_candidates,
        load_evidence_files,
        validate_evidence_completeness,
        save_target_assessment,
        save_drug_md,
        sequential_thinking,
        think_tool,
        validate_quality,
    ]

    data_dir_note = (
        f"\n\n## Data Directory\n"
        f"The data directory for this session is: `{data_dir}`\n"
        f"Pass this exact path as `data_dir` to all tool calls "
        f"(load_lr_candidates, load_evidence_files, save_target_assessment, save_drug_md).\n"
        f"- **Disease context**: `{args.disease}`\n"
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
        f"Generate the drug target assessment report for {args.disease}.\n\n"
        f"Data directory: {data_dir}\n"
        f"All evidence files are already collected (Stage 1, 2, 3 complete).\n\n"
        f"Steps:\n"
        f"1. Call load_lr_candidates(data_dir='{data_dir}', disease='{args.disease}') to get input pairs\n"
        f"2. Call load_evidence_files(data_dir='{data_dir}') to load all evidence\n"
        f"3. Call validate_evidence_completeness(data_dir='{data_dir}') to check readiness\n"
        f"4. Plan the document structure using sequential_thinking\n"
        f"5. Call save_target_assessment to create target_assessment.json\n"
        f"6. Call save_drug_md(data_dir='{data_dir}', content=...) to write drug.md to disk\n"
        f"7. Validate quality >= 0.7\n"
    )

    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": initial_message}]},
        config={"configurable": {"thread_id": str(uuid.uuid4())}},
    )

    elapsed = time.time() - t0
    print("-" * 70)
    print(f"\nCompleted in {elapsed / 60:.1f} minutes")

    # Check outputs
    drug_md = Path(data_dir) / "drug.md"
    target_json = Path(data_dir) / "target_assessment.json"

    if drug_md.exists():
        content = drug_md.read_text()
        print(f"\ndrug.md generated ({len(content)} chars, {content.count(chr(10))} lines)")
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
