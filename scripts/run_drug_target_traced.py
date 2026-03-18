#!/usr/bin/env python3
"""DrugTarget agent traced execution — step-by-step local tracing without LangSmith.

Uses astream(stream_mode="updates", subgraphs=True) to print each node
transition in real time, plus optional set_debug(True) and FileCallbackHandler
for full LLM/tool call logging.

Usage:
    # Mock data (e2e) with full debug
    python scripts/run_drug_target_traced.py

    # Real data
    python scripts/run_drug_target_traced.py --data-dir res_bc_ollama --disease "breast cancer"

    # Node tracing only (no verbose LLM debug output)
    python scripts/run_drug_target_traced.py --no-debug
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Force LangSmith OFF before any LangChain import
# ---------------------------------------------------------------------------
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

# ---------------------------------------------------------------------------
# Project bootstrap
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env", override=False)

# Re-enforce after dotenv (dotenv won't override, but be explicit)
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

# ---------------------------------------------------------------------------
# Mock data (same as run_drug_target_e2e.py)
# ---------------------------------------------------------------------------
MOCK_LR_CANDIDATES = {
    "disease": "breast cancer",
    "disease_context": "Triple-negative breast cancer",
    "pairs": [
        {"ligand": "TGFB1", "receptor": "TGFBR2", "score": 0.95},
        {"ligand": "CDH1", "receptor": "ITGB1", "score": 0.92},
        {"ligand": "SPP1", "receptor": "CD44", "score": 0.90},
        {"ligand": "VEGFA", "receptor": "FLT1", "score": 0.88},
        {"ligand": "WNT5A", "receptor": "FZD7", "score": 0.85},
        {"ligand": "CXCL12", "receptor": "CXCR4", "score": 0.83},
        {"ligand": "HGF", "receptor": "MET", "score": 0.80},
        {"ligand": "FGF2", "receptor": "FGFR1", "score": 0.78},
        {"ligand": "PDGFB", "receptor": "PDGFRB", "score": 0.76},
        {"ligand": "BMP2", "receptor": "BMPR1A", "score": 0.74},
        {"ligand": "EFNA1", "receptor": "EPHA2", "score": 0.72},
        {"ligand": "JAG1", "receptor": "NOTCH1", "score": 0.70},
        {"ligand": "DLL4", "receptor": "NOTCH3", "score": 0.68},
        {"ligand": "GDF15", "receptor": "GFRAL", "score": 0.65},
        {"ligand": "TNFSF10", "receptor": "TNFRSF10B", "score": 0.62},
    ],
}

MOCK_SELECTED_TOP3 = [
    {"ligand": "TGFB1", "receptor": "TGFBR2"},
    {"ligand": "SPP1", "receptor": "CD44"},
    {"ligand": "VEGFA", "receptor": "FLT1"},
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="DrugTarget traced execution")
    p.add_argument(
        "--data-dir",
        default=None,
        help="Data directory with lr_candidates.json. If omitted, uses mock data in a temp dir.",
    )
    p.add_argument(
        "--disease",
        default="breast cancer",
        help="Disease context string (default: 'breast cancer').",
    )
    p.add_argument(
        "--provider",
        default="openrouter",
        help="LLM provider (default: openrouter).",
    )
    p.add_argument(
        "--no-debug",
        action="store_true",
        help="Disable set_debug(True) — only show node transitions.",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=150,
        help="Timeout in minutes (default: 150).",
    )
    return p.parse_args()


def _setup_mock_data() -> Path:
    """Create a temp directory with mock input files."""
    tmpdir = tempfile.mkdtemp(prefix="drug_target_traced_")
    data_dir = Path(tmpdir)
    (data_dir / "lr_candidates.json").write_text(
        json.dumps(MOCK_LR_CANDIDATES, indent=2)
    )
    (data_dir / "selected_top3_lr.json").write_text(
        json.dumps(MOCK_SELECTED_TOP3, indent=2)
    )
    return data_dir


def _format_update_summary(update: dict) -> str:
    """Extract a short summary from a node's update dict."""
    parts = []
    for key, value in update.items():
        if key == "messages" and isinstance(value, list):
            for msg in value:
                msg_type = getattr(msg, "type", type(msg).__name__)
                content = getattr(msg, "content", "")
                # Tool calls
                tool_calls = getattr(msg, "tool_calls", None)
                if tool_calls:
                    names = [tc.get("name", "?") for tc in tool_calls]
                    parts.append(f"tool_calls=[{', '.join(names)}]")
                elif isinstance(content, str) and content:
                    preview = content[:120].replace("\n", " ")
                    parts.append(f"{msg_type}: {preview}...")
                elif isinstance(content, list):
                    parts.append(f"{msg_type}: [multipart, {len(content)} blocks]")
        else:
            parts.append(f"{key}={type(value).__name__}")
    return " | ".join(parts) if parts else "(empty update)"


def _capture_drug_md_from_update(node_data: dict, holder: dict) -> None:
    """Capture drug.md content from Command(update={'files': ...}) state updates.

    The LLM sometimes uses Command(files=...) to put drug.md into LangGraph
    state instead of calling save_drug_md. This scans each streamed update
    for such content so we can write it to disk as a fallback.
    """
    # Check for 'files' key in the update (from Command(update={'files': ...}))
    files = node_data.get("files") if isinstance(node_data, dict) else None
    if isinstance(files, dict):
        for file_key, file_val in files.items():
            if "drug.md" in str(file_key):
                # file_val may be a dict with 'content' or a string
                if isinstance(file_val, dict):
                    content = file_val.get("content", "")
                    if isinstance(content, list):
                        content = "\n".join(str(c) for c in content)
                elif isinstance(file_val, str):
                    content = file_val
                else:
                    content = str(file_val)
                if len(content) > 2000:
                    holder["content"] = content

    # Also scan messages for drug.md-like content (same heuristic as e2e script)
    messages = node_data.get("messages") if isinstance(node_data, dict) else None
    if isinstance(messages, list):
        for msg in messages:
            content = getattr(msg, "content", None)
            if not isinstance(content, str):
                continue
            if (
                len(content) > 2000
                and "executive summary" in content.lower()
                and ("featured candidate" in content.lower() or "druggability" in content.lower())
            ):
                holder["content"] = content


async def run_traced(args: argparse.Namespace) -> int:
    """Run the DrugTarget agent with step-by-step tracing."""

    # ── Debug mode ────────────────────────────────────────────────────
    if not args.no_debug:
        from langchain_core.globals import set_debug
        set_debug(True)
        print("[CONFIG] LangChain debug mode: ON")
    else:
        print("[CONFIG] LangChain debug mode: OFF (node tracing only)")

    # ── Data directory ────────────────────────────────────────────────
    if args.data_dir:
        data_dir = Path(args.data_dir)
        if not data_dir.is_absolute():
            data_dir = PROJECT_ROOT / data_dir
        data_dir = data_dir.resolve()
        if not (data_dir / "lr_candidates.json").exists():
            print(f"ERROR: lr_candidates.json not found in {data_dir}")
            return 1
        print(f"[CONFIG] Data dir: {data_dir} (user-provided)")
    else:
        data_dir = _setup_mock_data()
        print(f"[CONFIG] Data dir: {data_dir} (mock data)")

    os.environ["DRUG_TARGET_DATA_DIR"] = str(data_dir)

    # ── Trace log file ────────────────────────────────────────────────
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    trace_log_path = data_dir / f"trace_{timestamp}.log"

    from langchain_core.callbacks import FileCallbackHandler
    file_handler = FileCallbackHandler(str(trace_log_path))
    trace_log_fp = open(trace_log_path, "a")  # append structured markers alongside FileCallbackHandler
    print(f"[CONFIG] Trace log: {trace_log_path}")

    # ── Create agent ──────────────────────────────────────────────────
    from src.agents.drug_target.agent import (
        DrugTargetConfig,
        create_drug_target_agent,
    )

    config = DrugTargetConfig(
        provider=args.provider,
        data_dir=str(data_dir),
        disease=args.disease,
        use_checkpointer=True,
    )
    agent, backend = create_drug_target_agent(config)
    print(f"[CONFIG] Agent created (provider={args.provider})")
    print(f"[CONFIG] Disease: {args.disease}")

    # ── Stream with tracing ───────────────────────────────────────────
    initial_message = (
        f"Run the full drug target assessment pipeline for {args.disease}."
    )
    thread_id = str(uuid.uuid4())

    print(f"\n{'=' * 70}")
    print(f"STREAMING — thread_id={thread_id}")
    print(f"{'=' * 70}\n")

    start = time.time()
    node_counter = 0
    timeout_seconds = args.timeout * 60
    captured_drug_md_holder = {"content": None}  # Fallback: capture drug.md from Command(files=...)

    try:
        async for chunk in agent.astream(
            {"messages": [{"role": "user", "content": initial_message}]},
            config={
                "configurable": {"thread_id": thread_id},
                "callbacks": [file_handler],
            },
            stream_mode="updates",
            subgraphs=True,
        ):
            elapsed = time.time() - start
            if elapsed > timeout_seconds:
                print(f"\n[TIMEOUT] {args.timeout}m limit reached")
                break

            namespace, update = chunk
            node_path = " > ".join(namespace) if namespace else "orchestrator"

            for node_name, node_data in update.items():
                node_counter += 1
                print(
                    f"\n[{elapsed:7.1f}s] #{node_counter} [{node_path}] "
                    f"Node: {node_name}"
                )
                print(f"  {_format_update_summary({node_name: node_data})}")
                print(f"  {'─' * 60}")

                # Write structured node transition to trace log
                trace_log_fp.write(f"\n{'═' * 62}\n")
                trace_log_fp.write(
                    f"[{elapsed:7.1f}s] #{node_counter} [{node_path}] "
                    f"Node: {node_name}\n"
                )
                trace_log_fp.write(f"  {_format_update_summary({node_name: node_data})}\n")
                trace_log_fp.write(f"{'─' * 62}\n")
                trace_log_fp.flush()

                # Capture drug.md content from Command(files=...) state updates
                _capture_drug_md_from_update(node_data, captured_drug_md_holder)

    except Exception as e:
        elapsed = time.time() - start
        print(f"\n[ERROR at {elapsed:.1f}s] {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        trace_log_fp.close()
        if backend:
            backend.cleanup()

    elapsed = time.time() - start

    # ── Retry on early termination ───────────────────────────────
    evidence_dir = data_dir / "evidence"
    evidence_count = len(list(evidence_dir.glob("*.json"))) if evidence_dir.exists() else 0
    if evidence_count == 0 and elapsed < 300:
        print(f"\n[RETRY] Agent terminated early ({elapsed:.0f}s, 0 evidence files). "
              f"Retrying with explicit task-tool instructions...")
        with open(trace_log_path, "a") as fp:
            fp.write(f"\n[RETRY] Early termination detected at {elapsed:.1f}s — retrying\n")

        retry_message = (
            f"You MUST execute the full pipeline using the `task` tool. "
            f"Do NOT stop until both subagents complete.\n"
            f"Step 1: Call load_lr_candidates(data_dir=\"{data_dir}\", disease=\"{args.disease}\")\n"
            f"Step 2: IMMEDIATELY call task(subagent_type=\"evidence_assessor\", "
            f"instruction=\"Run full 3-stage evidence assessment for {args.disease}. "
            f"Data dir: {data_dir}.\")\n"
            f"Step 3: After evidence_assessor completes, call "
            f"task(subagent_type=\"report_writer\", instruction=\"Generate drug.md. "
            f"Data dir: {data_dir}.\")"
        )
        retry_thread_id = str(uuid.uuid4())
        retry_start = time.time()
        trace_log_fp = open(trace_log_path, "a")

        try:
            async for chunk in agent.astream(
                {"messages": [{"role": "user", "content": retry_message}]},
                config={
                    "configurable": {"thread_id": retry_thread_id},
                    "callbacks": [file_handler],
                },
                stream_mode="updates",
                subgraphs=True,
            ):
                elapsed = time.time() - start
                if elapsed > timeout_seconds:
                    print(f"\n[TIMEOUT] {args.timeout}m limit reached during retry")
                    break

                namespace, update = chunk
                node_path = " > ".join(namespace) if namespace else "orchestrator"

                for node_name, node_data in update.items():
                    node_counter += 1
                    print(
                        f"\n[{elapsed:7.1f}s] #{node_counter} [{node_path}] "
                        f"Node: {node_name}"
                    )
                    print(f"  {_format_update_summary({node_name: node_data})}")
                    print(f"  {'─' * 60}")

                    trace_log_fp.write(f"\n{'═' * 62}\n")
                    trace_log_fp.write(
                        f"[{elapsed:7.1f}s] #{node_counter} [{node_path}] "
                        f"Node: {node_name}\n"
                    )
                    trace_log_fp.write(f"  {_format_update_summary({node_name: node_data})}\n")
                    trace_log_fp.write(f"{'─' * 62}\n")
                    trace_log_fp.flush()

                    _capture_drug_md_from_update(node_data, captured_drug_md_holder)

        except Exception as e:
            elapsed = time.time() - start
            print(f"\n[RETRY ERROR at {elapsed:.1f}s] {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
        finally:
            trace_log_fp.close()

        elapsed = time.time() - start
        print(f"\n[RETRY] Completed in {time.time() - retry_start:.1f}s")

    # ── Fallback: write drug.md from captured stream state ────────
    drug_md_path = data_dir / "drug.md"
    if not drug_md_path.exists() and captured_drug_md_holder["content"]:
        content = captured_drug_md_holder["content"]
        drug_md_path.write_text(content)
        print(f"  [FALLBACK] Extracted drug.md from stream state ({len(content):,} chars)")
        with open(trace_log_path, "a") as fp:
            fp.write(f"\n[FALLBACK] drug.md extracted from Command(files=...) state update\n")

    elapsed = time.time() - start

    # ── Output summary ────────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print(f"TRACE COMPLETE — {elapsed:.1f}s ({node_counter} node transitions)")
    print(f"{'=' * 70}\n")

    evidence_dir = data_dir / "evidence"
    evidence_count = len(list(evidence_dir.glob("*.json"))) if evidence_dir.exists() else 0
    assessment_exists = (evidence_dir / "assessment_results.json").exists() if evidence_dir.exists() else False
    drug_md_exists = (data_dir / "drug.md").exists()
    target_json_exists = (data_dir / "target_assessment.json").exists()

    print(f"  Evidence files:      {evidence_count}")
    print(f"  assessment_results:  {'YES' if assessment_exists else 'NO'}")
    print(f"  target_assessment:   {'YES' if target_json_exists else 'NO'}")
    print(f"  drug.md:             {'YES' if drug_md_exists else 'NO'}")
    print(f"  Trace log:           {trace_log_path}")
    print(f"  Workspace:           {data_dir}")
    print(f"  Runtime:             {elapsed:.1f}s")

    # Write summary to trace log
    with open(trace_log_path, "a") as fp:
        fp.write(f"\n{'=' * 62}\n")
        fp.write(f"TRACE COMPLETE — {elapsed:.1f}s ({node_counter} node transitions)\n")
        fp.write(f"{'=' * 62}\n")
        fp.write(f"  Evidence files:      {evidence_count}\n")
        fp.write(f"  assessment_results:  {'YES' if assessment_exists else 'NO'}\n")
        fp.write(f"  target_assessment:   {'YES' if target_json_exists else 'NO'}\n")
        fp.write(f"  drug.md:             {'YES' if drug_md_exists else 'NO'}\n")
        fp.write(f"  Runtime:             {elapsed:.1f}s\n")

    if drug_md_exists:
        content = (data_dir / "drug.md").read_text()
        print(f"\n  drug.md: {len(content):,} chars")

    success = drug_md_exists and evidence_count > 0
    print(f"\n  {'SUCCESS' if success else 'PARTIAL'}")
    return 0 if success else 1


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    args = parse_args()
    sys.exit(asyncio.run(run_traced(args)))
