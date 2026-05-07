#!/usr/bin/env python3
"""Run ONLY the summarizer subagent on pre-collected evidence files.

Skips evidence_assessor and hypothesis_writer entirely — uses frozen evidence.
Writes evidence/_critic_slices/ before the summarizer runs (T17 wire-up) and
removes them afterward unless OMB_CRITIC_SLICES_KEEP=1.

Load order: .env values are loaded before argparse defaults so LLM_PROVIDER,
LLM_MODEL, and OLLAMA_MODEL from .env are honored when not shell-exported.
Shell exports still override .env (override=False semantics).

Example invocations:

    # Default: regenerate drug.md from frozen baseline
    uv run python scripts/run_drug_target_summarizer_only.py

    # Sanity check (no LLM call):
    uv run python scripts/run_drug_target_summarizer_only.py --dry-run

    # Custom evidence:
    uv run python scripts/run_drug_target_summarizer_only.py \\
        --evidence-source path/to/another/run \\
        --output path/to/regenerated/drug.md

    # Keep working directory for inspection:
    uv run python scripts/run_drug_target_summarizer_only.py --keep-data-dir

    # Explicit provider/model:
    uv run python scripts/run_drug_target_summarizer_only.py \\
        --provider ollama --model qwen3.5:122b
"""

from __future__ import annotations

import argparse
import asyncio
import json as _json
import logging
import os
import shutil
import sys
import tempfile
import time
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

_ENV_DEFAULT_PROVIDER = os.environ.get("LLM_PROVIDER")
_ENV_DEFAULT_MODEL = os.environ.get("LLM_MODEL")
_ENV_OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_EVIDENCE_SOURCE = (
    "tests/agents/drug_target/fixtures/baseline_hallucinated"
)
_DEFAULT_OUTPUT = "tests/agents/drug_target/fixtures/regenerated/drug.md"
_DEFAULT_PROVIDER = _ENV_DEFAULT_PROVIDER or "ollama"
_DEFAULT_MODEL = _ENV_DEFAULT_MODEL or _ENV_OLLAMA_MODEL or "qwen3.5:122b"
_OLLAMA_HOST_DEFAULT = "http://localhost:6000"

_SUBAGENT_NAMES = [
    "EVIDENCE_ASSESSOR",
    "HYPOTHESIS_WRITER",
    "SUMMARIZER",
    "REPORT_WRITER",
    "CRITIC",
]

_DEFAULT_LOG_FILE = ".omb/logs/v8_run.log"
_DIAGNOSTIC_LOGGERS = (
    "drug_target.fs_backend",
    "drug_target.fs_middleware",
    "drug_target.lifecycle",
)


# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------


class JsonlFormatter(logging.Formatter):
    """Emit one JSON object per log record on its own line.

    The actual structured payload is already inside ``record.msg`` (callers use
    ``logger.info(json.dumps({...}))``). This formatter adds a small outer
    envelope so consumers can grep ``"level": "INFO"`` etc.
    """

    def format(self, record: logging.LogRecord) -> str:
        try:
            payload = _json.loads(record.msg)
        except (ValueError, TypeError):
            payload = {"raw_msg": record.getMessage()}
        envelope = {
            "level": record.levelname,
            "logger": record.name,
            "ts": record.created,
            **payload,
        }
        return _json.dumps(envelope)


def configure_logging(level: str, log_file: str) -> None:
    """Install JsonlFormatter on a single FileHandler for the diagnostic loggers.

    Single sink to prevent AC7 grep-count duplication (CP-P1-002).
    ``propagate=False`` prevents duplication via the root logger.
    """
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    handler = logging.FileHandler(str(log_path), mode="w")
    handler.setFormatter(JsonlFormatter())

    numeric_level = getattr(logging, level, logging.INFO)
    for name in _DIAGNOSTIC_LOGGERS:
        lg = logging.getLogger(name)
        lg.setLevel(numeric_level)
        lg.addHandler(handler)
        lg.propagate = False  # prevent duplication via root logger


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run ONLY the summarizer subagent on pre-collected evidence."
    )
    p.add_argument(
        "--evidence-source",
        default=_DEFAULT_EVIDENCE_SOURCE,
        help=(
            "Path to a directory containing drug.md (optional) + evidence/. "
            f"Default: {_DEFAULT_EVIDENCE_SOURCE}"
        ),
    )
    p.add_argument(
        "--output",
        default=_DEFAULT_OUTPUT,
        help=f"Path to write regenerated drug.md. Default: {_DEFAULT_OUTPUT}",
    )
    p.add_argument(
        "--data-dir",
        default=None,
        help=(
            "Working directory for this run. "
            "Default: a fresh tempfile.mkdtemp(prefix='drug_target_summarizer_')."
        ),
    )
    p.add_argument(
        "--keep-data-dir",
        action="store_true",
        help="Do NOT clean up the working directory after the run.",
    )
    p.add_argument(
        "--provider",
        default=_DEFAULT_PROVIDER,
        help=f"LLM provider. Default: {_DEFAULT_PROVIDER}",
    )
    p.add_argument(
        "--model",
        default=_DEFAULT_MODEL,
        help=f"Model name. Default: {_DEFAULT_MODEL}",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Resolve config and copy evidence without invoking the LLM. "
            "Use to verify the script wires up correctly."
        ),
    )
    p.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level for diagnostic loggers. Default: INFO",
    )
    p.add_argument(
        "--log-file",
        default=_DEFAULT_LOG_FILE,
        help=f"Path to the structured JSONL log file. Default: {_DEFAULT_LOG_FILE}",
    )
    return p.parse_args()


# ---------------------------------------------------------------------------
# Env-var setup
# ---------------------------------------------------------------------------


def _set_subagent_env(provider: str, model: str) -> None:
    """Set SUBAGENT_<NAME>_PROVIDER / SUBAGENT_<NAME>_MODEL for all subagents."""
    for name in _SUBAGENT_NAMES:
        os.environ[f"SUBAGENT_{name}_PROVIDER"] = provider
        os.environ[f"SUBAGENT_{name}_MODEL"] = model

    # Ensure OLLAMA_HOST is set when using ollama
    if provider == "ollama" and "OLLAMA_HOST" not in os.environ:
        os.environ["OLLAMA_HOST"] = _OLLAMA_HOST_DEFAULT


# ---------------------------------------------------------------------------
# Evidence copy
# ---------------------------------------------------------------------------


def _copy_evidence(source_dir: Path, data_dir: Path) -> int:
    """Copy evidence/ tree from source_dir into data_dir/evidence/.

    Returns the count of files copied.
    """
    src_evidence = source_dir / "evidence"
    if not src_evidence.is_dir():
        print(f"ERROR: evidence/ not found under {source_dir}", file=sys.stderr)
        sys.exit(1)

    dst_evidence = data_dir / "evidence"
    dst_evidence.mkdir(parents=True, exist_ok=True)

    count = 0
    for src_file in src_evidence.iterdir():
        if src_file.is_file():
            shutil.copy2(src_file, dst_evidence / src_file.name)
            count += 1

    return count


# ---------------------------------------------------------------------------
# Disease extraction from drug.md
# ---------------------------------------------------------------------------


def _extract_disease(source_dir: Path) -> str:
    """Best-effort: extract disease name from drug.md H1 heading."""
    drug_md = source_dir / "drug.md"
    if not drug_md.exists():
        return ""
    for line in drug_md.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            # H1 often contains disease context, e.g. "# IPF Drug Targets"
            return stripped[2:].strip()
    return ""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def _run(args: argparse.Namespace) -> None:
    # Configure diagnostic loggers before any agent construction (T3.6b).
    configure_logging(args.log_level, args.log_file)

    source_dir = Path(args.evidence_source).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()

    # ------------------------------------------------------------------
    # Resolve working directory
    # ------------------------------------------------------------------
    owns_data_dir = False
    if args.data_dir:
        data_dir = Path(args.data_dir).expanduser().resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
    else:
        data_dir = Path(tempfile.mkdtemp(prefix="drug_target_summarizer_"))
        owns_data_dir = True

    print("=" * 70)
    print("Summarizer-Only Runner (T17)")
    print("=" * 70)
    print(f"  Provider:        {args.provider}")
    print(f"  Model:           {args.model}")
    print(f"  Evidence source: {source_dir}")
    print(f"  Data dir:        {data_dir}")
    print(f"  Output:          {output_path}")
    print(f"  Dry-run:         {args.dry_run}")
    print()

    # ------------------------------------------------------------------
    # Set env vars for all subagents
    # ------------------------------------------------------------------
    _set_subagent_env(provider=args.provider, model=args.model)

    # ------------------------------------------------------------------
    # Copy evidence
    # ------------------------------------------------------------------
    n_copied = _copy_evidence(source_dir, data_dir)
    print(f"  Copied {n_copied} evidence files -> {data_dir}/evidence/")

    # ------------------------------------------------------------------
    # Resolve disease
    # ------------------------------------------------------------------
    disease = _extract_disease(source_dir)
    print(f"  Disease context: {disease or '(not found in drug.md)'}")

    if args.dry_run:
        print()
        print("DRY-RUN: skipping LLM invocation. Config verified OK.")
        print(f"  data_dir:  {data_dir}")
        print(f"  evidence files: {n_copied}")
        print(f"  provider:  {args.provider}")
        print(f"  model:     {args.model}")
        return

    # ------------------------------------------------------------------
    # Imports (deferred so --dry-run never touches heavy LangChain stack)
    # ------------------------------------------------------------------
    from src.agents.model import create_llm
    from src.agents.drug_target.subagents.configs import (
        SUBAGENT_CONFIGS,
        _SUMMARIZER_INNER_SUBAGENTS,  # noqa: PLC2701
    )
    from src.agents.drug_target.subagents.summarizer import (
        create_summarizer_agent,
        wrap_summarizer_with_critic_slices,
    )

    # ------------------------------------------------------------------
    # Build model
    # ------------------------------------------------------------------
    llm = create_llm(provider=args.provider, model=args.model)

    # ------------------------------------------------------------------
    # Build summarizer inner subagents (report_writer + critic)
    # Mirrors the pattern in get_subagents() in configs.py.
    # ------------------------------------------------------------------
    inner_subagents = [
        {**SUBAGENT_CONFIGS[name], "tools": list(SUBAGENT_CONFIGS[name]["tools"])}
        for name in _SUMMARIZER_INNER_SUBAGENTS
    ]

    # ------------------------------------------------------------------
    # Build summarizer agent wrapped with critic-slice lifecycle
    # ------------------------------------------------------------------
    raw_agent = create_summarizer_agent(
        model=llm,
        inner_subagents=inner_subagents,
        data_dir=str(data_dir),
    )
    agent = wrap_summarizer_with_critic_slices(raw_agent, data_dir=str(data_dir))

    # ------------------------------------------------------------------
    # Build initial prompt
    # ------------------------------------------------------------------
    initial_message = (
        f"Finalize the drug target assessment report.\n\n"
        f"Data directory: {data_dir}\n"
        f"Disease context: {disease or 'see evidence files'}\n\n"
        f"The evidence directory already contains all Stage 1, 2, and 3 files.\n"
        f"Steps:\n"
        f"1. Invoke report_writer to build the report skeleton and fill EXPAND markers.\n"
        f"2. Run validate_drug_md to check for P0 findings.\n"
        f"3. Run critic (via task tool) on per-gene slices in "
        f"evidence/_critic_slices/.\n"
        f"4. Self-revise via repair loop (max 2 cycles).\n"
        f"5. Confirm 0 P0 findings, then report DONE.\n"
        f"\nThe final drug.md must be saved to: {data_dir}/drug.md\n"
    )

    # ------------------------------------------------------------------
    # Invoke
    # ------------------------------------------------------------------
    t0 = time.time()
    print("\nInvoking summarizer agent...")
    print("-" * 70)

    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": initial_message}]},
        config={"configurable": {"thread_id": str(uuid.uuid4())}},
    )

    elapsed = time.time() - t0
    print("-" * 70)
    print(f"\nCompleted in {elapsed / 60:.1f} minutes")

    # ------------------------------------------------------------------
    # Copy output
    # ------------------------------------------------------------------
    drug_md_src = data_dir / "drug.md"
    if drug_md_src.exists():
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(drug_md_src, output_path)
        content = drug_md_src.read_text(encoding="utf-8")
        print(f"\ndrug.md generated ({len(content)} chars, {content.count(chr(10))} lines)")
        print(f"  Saved to: {output_path}")
    else:
        print("\nWARNING: drug.md was not generated in data_dir", file=sys.stderr)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    messages = result.get("messages", [])
    print(f"\n  Total messages in final state: {len(messages)}")
    # Dump all messages for diagnosis
    print("\n--- MESSAGE DUMP ---")
    for i, msg in enumerate(messages):
        role = getattr(msg, "type", None) or getattr(msg, "role", None) or type(msg).__name__
        content = getattr(msg, "content", None)
        tool_calls = getattr(msg, "tool_calls", None) or []
        name = getattr(msg, "name", "") or ""
        text = ""
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = " | ".join(str(p)[:200] for p in content)
        text_short = (text[:400] + "...") if len(text) > 400 else text
        tc_summary = ""
        if tool_calls:
            tc_summary = " tool_calls=" + ",".join(
                tc.get("name", "?") if isinstance(tc, dict) else getattr(tc, "name", "?")
                for tc in tool_calls
            )
        print(f"[{i:02d}] {role}{(' name=' + name) if name else ''}{tc_summary}")
        if text_short:
            for line in text_short.splitlines()[:8]:
                print(f"    {line}")
    print("--- END MESSAGE DUMP ---\n")
    print("=" * 70)
    print("DONE")

    # ------------------------------------------------------------------
    # Cleanup working directory
    # ------------------------------------------------------------------
    if owns_data_dir and not args.keep_data_dir:
        shutil.rmtree(data_dir, ignore_errors=True)
        print(f"  Cleaned up temp data dir: {data_dir}")
    elif args.keep_data_dir:
        print(f"  Kept data dir (--keep-data-dir): {data_dir}")


def main() -> None:
    args = _parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
