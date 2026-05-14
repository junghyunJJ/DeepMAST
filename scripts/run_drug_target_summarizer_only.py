#!/usr/bin/env python3
"""Run ONLY the summarizer subagent on pre-collected evidence files.

Builds a standalone DeepAgent from the dict summarizer spec returned by
``get_summarizer_subagent()`` (post-2026-05-13 simplification) and dispatches
it directly — no evidence_assessor, no hypothesis_writer, no orchestrator.

Verification artifacts after a successful run:
  - ``<data_dir>/drug.md``                     — assembled by render_drug_md_from_expansions
  - ``<data_dir>/drug_report.html``            — assembled by generate_drug_html_report
  - Final assistant message contains the literal line ``SUMMARIZER_STATUS: PASS``

Negative paths to verify:
  - On ``validate_drug_md`` returning ``valid=false`` for 3 consecutive cycles,
    the summarizer must emit ``SUMMARIZER_STATUS: FAIL`` and ``drug_report.html``
    must NOT exist (mechanical gate via SummarizerFinalizationGuardMiddleware).

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
        --provider ollama --model qwen3:30b
"""

from __future__ import annotations

import argparse
import asyncio
import json as _json
import logging
import os
import re
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
_DEFAULT_MODEL = _ENV_DEFAULT_MODEL or _ENV_OLLAMA_MODEL or "qwen3:30b"
_OLLAMA_HOST_DEFAULT = "http://localhost:6000"

_DEFAULT_LOG_FILE = ".omb/logs/summarizer_only.log"


# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------


class JsonlFormatter(logging.Formatter):
    """Emit one JSON object per log record on its own line."""

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
    """Install a JSONL FileHandler on the drug_target logger root."""
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    handler = logging.FileHandler(str(log_path), mode="w")
    handler.setFormatter(JsonlFormatter())

    numeric_level = getattr(logging, level, logging.INFO)
    lg = logging.getLogger("drug_target")
    lg.setLevel(numeric_level)
    lg.addHandler(handler)
    lg.propagate = False


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
        "--recursion-limit",
        type=int,
        default=300,
        help=(
            "LangGraph recursion limit for the standalone summarizer agent. "
            "The new dict subagent runs a single tool-calling loop with at most "
            "2 validator retries, so 300 is generous. Default: 300"
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


def _set_provider_env(provider: str, model: str) -> None:
    """Set LLM_PROVIDER / LLM_MODEL and OLLAMA_HOST defaults."""
    os.environ.setdefault("LLM_PROVIDER", provider)
    os.environ.setdefault("LLM_MODEL", model)
    if provider == "ollama" and "OLLAMA_HOST" not in os.environ:
        os.environ["OLLAMA_HOST"] = _OLLAMA_HOST_DEFAULT


# ---------------------------------------------------------------------------
# Evidence copy
# ---------------------------------------------------------------------------


def _copy_evidence(source_dir: Path, data_dir: Path) -> int:
    """Copy evidence/ tree from source_dir into data_dir/evidence/."""
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
            return stripped[2:].strip()
    return ""


# ---------------------------------------------------------------------------
# Result inspection
# ---------------------------------------------------------------------------


_STATUS_LINE_RE = re.compile(
    r"^\s*SUMMARIZER_STATUS:\s*(PASS|FAIL)\b", re.MULTILINE
)


def _scan_for_status(messages: list) -> str | None:
    """Return 'PASS' or 'FAIL' if the final assistant message contains the
    literal SUMMARIZER_STATUS line, else None."""
    for msg in reversed(messages):
        content = getattr(msg, "content", None)
        text = ""
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = "\n".join(
                p.get("text", "") if isinstance(p, dict) else str(p)
                for p in content
            )
        match = _STATUS_LINE_RE.search(text)
        if match:
            return match.group(1)
    return None


def _dump_messages(messages: list) -> None:
    print("\n--- MESSAGE DUMP ---")
    for i, msg in enumerate(messages):
        role = (
            getattr(msg, "type", None)
            or getattr(msg, "role", None)
            or type(msg).__name__
        )
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def _run(args: argparse.Namespace) -> None:
    configure_logging(args.log_level, args.log_file)

    source_dir = Path(args.evidence_source).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()

    owns_data_dir = False
    if args.data_dir:
        data_dir = Path(args.data_dir).expanduser().resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
    else:
        data_dir = Path(tempfile.mkdtemp(prefix="drug_target_summarizer_"))
        owns_data_dir = True

    print("=" * 70)
    print("Summarizer-Only Runner (post-2026-05-13 dict spec)")
    print("=" * 70)
    print(f"  Provider:        {args.provider}")
    print(f"  Model:           {args.model}")
    print(f"  Evidence source: {source_dir}")
    print(f"  Data dir:        {data_dir}")
    print(f"  Output:          {output_path}")
    print(f"  Recursion limit: {args.recursion_limit}")
    print(f"  Dry-run:         {args.dry_run}")
    print()

    _set_provider_env(provider=args.provider, model=args.model)
    n_copied = _copy_evidence(source_dir, data_dir)
    print(f"  Copied {n_copied} evidence files -> {data_dir}/evidence/")

    disease = _extract_disease(source_dir)
    print(f"  Disease context: {disease or '(not found in drug.md)'}")

    if args.dry_run:
        print()
        print("DRY-RUN: skipping LLM invocation. Verifying summarizer dict spec only.")
        from src.agents.drug_target.subagents.summarizer import get_summarizer_subagent

        spec = get_summarizer_subagent()
        tool_names = [t.name for t in spec["tools"]]
        mw_names = [type(m).__name__ for m in spec["middleware"]]
        print(f"  Summarizer keys:  {sorted(spec.keys())}")
        print(f"  Tools ({len(tool_names)}):  {tool_names}")
        print(f"  Middleware:       {mw_names}")
        print(f"  data_dir:         {data_dir}")
        print(f"  evidence files:   {n_copied}")
        return

    # ------------------------------------------------------------------
    # Imports (deferred so --dry-run never touches heavy LangChain stack)
    # ------------------------------------------------------------------
    from deepagents import create_deep_agent
    from deepagents.backends import FilesystemBackend

    from src.agents.deep_interpreter.middleware.write_file_guard import (
        WriteFileArgGuardMiddleware,
    )
    from src.agents.drug_target.subagents.summarizer import get_summarizer_subagent
    from src.agents.model import create_llm

    # ------------------------------------------------------------------
    # Build standalone summarizer DeepAgent
    # ------------------------------------------------------------------
    llm = create_llm(provider=args.provider, model=args.model)

    spec = get_summarizer_subagent()
    backend = FilesystemBackend(
        root_dir=str(data_dir),
        virtual_mode=True,
    )

    # The standalone agent uses the same tool surface, system prompt, and
    # fail-closed guard as the full pipeline summarizer. We additionally
    # prepend WriteFileArgGuardMiddleware so any incidental write_file call
    # is shaped correctly (mirroring the parent agent's middleware stack).
    agent = create_deep_agent(
        model=llm,
        tools=list(spec["tools"]),
        system_prompt=spec["system_prompt"],
        backend=backend,
        middleware=[
            WriteFileArgGuardMiddleware(backend_root=str(data_dir)),
            *spec["middleware"],
        ],
    )
    agent = agent.with_config({"recursion_limit": args.recursion_limit})

    initial_message = (
        f"Finalize the drug target assessment report.\n\n"
        f"Data directory: {data_dir}\n"
        f"Disease context: {disease or 'see evidence files'}\n\n"
        f"The evidence directory already contains all Stage 1, 2, and 3 files.\n"
        f"Follow the 6-step tool sequence in your system prompt:\n"
        f"  1) build_evidence_summary (exactly once)\n"
        f"  2) load_evidence_files\n"
        f"  3) save_report_expansions (per gene/section)\n"
        f"  4) render_drug_md_from_expansions\n"
        f"  5) validate_drug_md  -- MANDATORY quality gate\n"
        f"  6) generate_drug_html_report (exactly once after valid=true)\n"
        f"Then emit `SUMMARIZER_STATUS: PASS` on its own line.\n"
        f"Pass `data_dir=\"{data_dir}\"` to every tool call.\n"
    )

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
    # Validate artifacts
    # ------------------------------------------------------------------
    drug_md_src = data_dir / "drug.md"
    drug_html_src = data_dir / "drug_report.html"
    md_ok = drug_md_src.exists()
    html_ok = drug_html_src.exists()
    print()
    print(f"  drug.md exists:           {md_ok} ({drug_md_src})")
    print(f"  drug_report.html exists:  {html_ok} ({drug_html_src})")

    if md_ok:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(drug_md_src, output_path)
        content = drug_md_src.read_text(encoding="utf-8")
        print(
            f"  drug.md saved:            {len(content)} chars, "
            f"{content.count(chr(10))} lines -> {output_path}"
        )

    messages = result.get("messages", [])
    status = _scan_for_status(messages)
    print(f"  SUMMARIZER_STATUS:        {status or '(NOT FOUND)'}")
    print(f"  Total messages:           {len(messages)}")

    # Quality-gate cross-check: status PASS requires HTML to exist.
    if status == "PASS" and not html_ok:
        print(
            "  WARNING: SUMMARIZER_STATUS: PASS but drug_report.html missing — "
            "the literal-line contract was emitted without the finalization "
            "tool actually running. The fail-closed middleware should have "
            "blocked this; investigate.",
            file=sys.stderr,
        )

    _dump_messages(messages)

    print("=" * 70)
    print("DONE" if status == "PASS" and md_ok and html_ok else "INCOMPLETE")

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
