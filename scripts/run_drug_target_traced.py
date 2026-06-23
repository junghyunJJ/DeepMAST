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

    # Force Ollama on port 6000 for this run
    python scripts/run_drug_target_traced.py --port 6000

    # Force Ollama cloud model on port 7000 for this run
    python scripts/run_drug_target_traced.py --provider ollama --port 7000 --model qwen3.5:397b-cloud

    # Force a vLLM/OpenAI-compatible local server on port 7001
    python scripts/run_drug_target_traced.py --provider vllm --port 7001 \
      --model Qwen/Qwen3.5-122B-A10B-FP8 --max-tokens 16384 --enable-thinking

    # Node tracing only (no verbose LLM debug output)
    python scripts/run_drug_target_traced.py --no-debug
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import inspect
import json
import logging
import os
import re
import sys
import tempfile
import time
import uuid
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, cast

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
from langchain_core.runnables import RunnableConfig

from docs.benchmarks.hypothesis_generation_consistency.activation_trace import (
    extract_hypothesis_writer_read_skill_file_calls,
    extract_named_tool_calls,
    extract_read_skill_file_calls,
    summarize_activation_trace,
)
from docs.benchmarks.hypothesis_generation_consistency.run_benchmark import (
    HYPOTHESIS_WRITER_SKILL_SETS,
    resolve_hypothesis_writer_skill_names,
)

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

DEFAULT_OLLAMA_PORT = 11434
LOCAL_OPENAI_COMPAT_PROVIDERS = {"ollama-openai", "vllm"}
LOCAL_PORT_PROVIDERS = {"ollama", *LOCAL_OPENAI_COMPAT_PROVIDERS}


class _CleanupBackend(Protocol):
    def cleanup(self) -> None:
        ...


def _parse_port(value: str) -> int:
    """Validate TCP port values for Ollama localhost overrides."""
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
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
        default="ollama",
        help="LLM provider (default: ollama).",
    )
    p.add_argument(
        "--model",
        default=None,
        help=(
            "Optional model override for this run. For Ollama this sets both "
            "LLM_MODEL and OLLAMA_MODEL, e.g. qwen3.5:397b-cloud."
        ),
    )
    p.add_argument(
        "--port",
        type=_parse_port,
        default=None,
        help=(
            "Override localhost model-server port for this run. Supported for "
            "ollama, ollama-openai, and vllm providers. Native ollama defaults "
            f"to {DEFAULT_OLLAMA_PORT}; OpenAI-compatible providers use this "
            "only when explicitly supplied."
        ),
    )
    p.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help=(
            "OpenAI-compatible max_tokens override for ollama-openai/vllm "
            "providers, e.g. 16384."
        ),
    )
    thinking_group = p.add_mutually_exclusive_group()
    thinking_group.add_argument(
        "--enable-thinking",
        dest="enable_thinking",
        action="store_true",
        default=None,
        help=(
            "For vLLM/OpenAI-compatible Qwen servers, pass "
            "chat_template_kwargs.enable_thinking=true."
        ),
    )
    thinking_group.add_argument(
        "--disable-thinking",
        dest="enable_thinking",
        action="store_false",
        default=None,
        help=(
            "For vLLM/OpenAI-compatible Qwen servers, pass "
            "chat_template_kwargs.enable_thinking=false."
        ),
    )
    p.add_argument(
        "--no-debug",
        action="store_true",
        help="Disable set_debug(True) — only show node transitions.",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Timeout in minutes (default: 120).",
    )
    p.add_argument(
        "--census",
        action="store_true",
        default=True,
        help="Enable Census API tools (query_cellxgene_lr_context, run_compare_census_lr_pair). "
             "Disabled by default due to slow API response times.",
    )
    p.add_argument(
        "--skip-evidence-assessor",
        action="store_true",
        default=False,
        help="Skip the evidence_assessor subagent (resume mode). Assumes evidence/*.json "
             "files are already on disk from a prior partial run. Orchestrator runs only "
             "hypothesis_writer, then the finalize_report node. Sets env var "
             "DRUG_TARGET_SKIP_EVIDENCE_ASSESSOR=1 before agent construction.",
    )
    p.add_argument(
        "--hypothesis-skill-set",
        choices=sorted(HYPOTHESIS_WRITER_SKILL_SETS),
        default="current4",
        help="Hypothesis writer skill set to expose (default: current4).",
    )
    p.add_argument(
        "--skill-activation-mode",
        choices=(
            "middleware_only",
            "middleware_plus_activator",
            "middleware_plus_governor",
        ),
        default="middleware_plus_activator",
        help="Skill activation mode for hypothesis writer skills.",
    )
    p.add_argument(
        "--hypothesis-writer-prompt-mode",
        choices=(
            "default",
            "dth_contrast_no_skill",
            "dth_contrast_dth_required",
            "operational_contract_only",
            "operational_contract_plus_dth",
            "operational_contract_minimal",
            "operational_contract_minimal_plus_dth",
            "thin_basic",
            "thin_basic_dth_required",
            "thin_basic_domain4_required",
            "thin_basic_dth_plus_domain4_required",
            "dth_only_required",
            "progressive_disclosure_only",
            "progressive_disclosure_with_modality_map",
        ),
        default="default",
        help=(
            "Prompt variant for hypothesis_writer. Use "
            "'progressive_disclosure_only' for benchmarks that remove "
            "prompt-level forced skill reads and leave skill selection to "
            "SkillsMiddleware / activator / governor, or "
            "'dth_only_required' for DTH-only controlled activation runs, or "
            "'progressive_disclosure_with_modality_map' to keep soft "
            "modality-to-skill routing without forcing drug-target-hypothesis."
        ),
    )
    p.add_argument(
        "--activation-trace-json",
        default=None,
        help="Path for activation trace JSON (default: data_dir/activation_trace_<timestamp>.json).",
    )
    args = p.parse_args(argv)
    args.provider = str(args.provider).lower()
    if args.port is not None and args.provider not in LOCAL_PORT_PROVIDERS:
        p.error("--port can only be used with --provider ollama, ollama-openai, or vllm")
    if args.provider == "ollama" and args.port is None:
        args.port = DEFAULT_OLLAMA_PORT
    if args.max_tokens is not None and args.max_tokens <= 0:
        p.error("--max-tokens must be positive")
    if args.enable_thinking is not None and args.provider not in LOCAL_OPENAI_COMPAT_PROVIDERS:
        p.error("--enable-thinking/--disable-thinking can only be used with ollama-openai or vllm")
    return args


def _configure_ollama_port_override(args: argparse.Namespace) -> str | None:
    """Apply localhost model-server port overrides for the current process."""
    provider = str(args.provider).lower()
    if provider not in LOCAL_PORT_PROVIDERS:
        return None
    if provider == "ollama" and args.port is None:
        args.port = DEFAULT_OLLAMA_PORT
    if args.port is None:
        return None

    base_url = f"http://localhost:{args.port}"
    os.environ["OLLAMA_BASE_URL"] = base_url
    if provider == "ollama":
        os.environ["OLLAMA_HOST"] = base_url
    return base_url


def _configure_provider_env(args: argparse.Namespace) -> None:
    """Keep graph-native retry provider resolution aligned with CLI args."""
    provider = str(args.provider).lower()
    os.environ["LLM_PROVIDER"] = provider
    max_tokens = getattr(args, "max_tokens", None)
    if max_tokens is not None:
        os.environ["VLLM_MAX_TOKENS"] = str(max_tokens)
        os.environ["OLLAMA_OPENAI_MAX_TOKENS"] = str(max_tokens)
    enable_thinking = getattr(args, "enable_thinking", None)
    if enable_thinking is not None:
        value = "true" if enable_thinking else "false"
        os.environ["VLLM_ENABLE_THINKING"] = value
        os.environ["OLLAMA_OPENAI_ENABLE_THINKING"] = value
    model = str(getattr(args, "model", "") or "").strip()
    if not model:
        return
    os.environ["LLM_MODEL"] = model
    if provider in LOCAL_PORT_PROVIDERS:
        os.environ["OLLAMA_MODEL"] = model


def _finalize_report_config(args: argparse.Namespace) -> RunnableConfig:
    """Build the config used when the traced runner invokes finalize_report directly."""
    configurable: dict[str, str] = {"llm_provider": args.provider}
    llm_model = str(getattr(args, "model", "") or "").strip() or os.getenv("LLM_MODEL")
    if llm_model:
        configurable["llm_model"] = llm_model
    return {"recursion_limit": 100, "configurable": configurable}


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


def build_activation_trace_payload(
    *,
    exposed_skill_names: Sequence[str],
    hypothesis_writer_read_skill_calls: Sequence[dict[str, Any]],
    all_read_skill_calls: Sequence[dict[str, Any]],
    skill_set: str,
    skill_activation_mode: str,
    model: str,
    ollama_base_url: str | None,
    data_dir: Path,
    trace_log_path: Path,
    report_finalized: bool,
    hypothesis_writer_prompt_mode: str = "default",
    artifact_gate_event: dict[str, Any] | None = None,
) -> dict[str, Any]:
    activation_trace = summarize_activation_trace(
        exposed_skill_names=exposed_skill_names,
        hypothesis_writer_calls=hypothesis_writer_read_skill_calls,
        all_read_skill_calls=all_read_skill_calls,
    )
    activation_trace.update(
        {
            "skill_set": skill_set,
            "skill_activation_mode": skill_activation_mode,
            "hypothesis_writer_prompt_mode": hypothesis_writer_prompt_mode,
            "model": model,
            "ollama_base_url": ollama_base_url,
            "data_dir": str(data_dir),
            "trace_log": str(trace_log_path),
            "report_finalized": report_finalized,
            "artifact_gate_event": artifact_gate_event,
        }
    )
    return activation_trace


def resolve_activation_trace_path(
    activation_trace_json: str | None,
    *,
    data_dir: Path,
    timestamp: str,
    project_root: Path = PROJECT_ROOT,
) -> Path:
    activation_trace_path = (
        Path(activation_trace_json)
        if activation_trace_json
        else data_dir / f"activation_trace_{timestamp}.json"
    )
    if not activation_trace_path.is_absolute():
        activation_trace_path = project_root / activation_trace_path
    return activation_trace_path


def write_activation_trace_json(
    *,
    activation_trace_path: Path,
    exposed_skill_names: Sequence[str],
    hypothesis_writer_read_skill_calls: Sequence[dict[str, Any]],
    all_read_skill_calls: Sequence[dict[str, Any]],
    skill_set: str,
    skill_activation_mode: str,
    model: str,
    ollama_base_url: str | None,
    data_dir: Path,
    trace_log_path: Path,
    report_finalized: bool,
    hypothesis_writer_prompt_mode: str = "default",
    artifact_gate_event: dict[str, Any] | None = None,
    project_root: Path = PROJECT_ROOT,
) -> Path:
    if not activation_trace_path.is_absolute():
        activation_trace_path = project_root / activation_trace_path
    activation_trace = build_activation_trace_payload(
        exposed_skill_names=exposed_skill_names,
        hypothesis_writer_read_skill_calls=hypothesis_writer_read_skill_calls,
        all_read_skill_calls=all_read_skill_calls,
        skill_set=skill_set,
        skill_activation_mode=skill_activation_mode,
        hypothesis_writer_prompt_mode=hypothesis_writer_prompt_mode,
        model=model,
        ollama_base_url=ollama_base_url,
        data_dir=data_dir,
        trace_log_path=trace_log_path,
        report_finalized=report_finalized,
        artifact_gate_event=artifact_gate_event,
    )
    activation_trace_path.parent.mkdir(parents=True, exist_ok=True)
    activation_trace_path.write_text(
        json.dumps(activation_trace, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return activation_trace_path


def write_activation_trace_checkpoint(
    *,
    activation_trace_path: Path,
    exposed_skill_names: Sequence[str],
    hypothesis_writer_read_skill_calls: Sequence[dict[str, Any]],
    all_read_skill_calls: Sequence[dict[str, Any]],
    skill_set: str,
    skill_activation_mode: str,
    model: str,
    ollama_base_url: str | None,
    data_dir: Path,
    trace_log_path: Path,
    hypothesis_writer_prompt_mode: str = "default",
    artifact_gate_event: dict[str, Any] | None = None,
) -> Path:
    written_path = write_activation_trace_json(
        activation_trace_path=activation_trace_path,
        exposed_skill_names=exposed_skill_names,
        hypothesis_writer_read_skill_calls=hypothesis_writer_read_skill_calls,
        all_read_skill_calls=all_read_skill_calls,
        skill_set=skill_set,
        skill_activation_mode=skill_activation_mode,
        hypothesis_writer_prompt_mode=hypothesis_writer_prompt_mode,
        model=model,
        ollama_base_url=ollama_base_url,
        data_dir=data_dir,
        trace_log_path=trace_log_path,
        report_finalized=False,
        artifact_gate_event=artifact_gate_event,
    )
    message = (
        "[ACTIVATION-TRACE-CHECKPOINT] wrote activation trace before "
        f"hypothesis quality/finalize: {written_path}"
    )
    print(f"\n{message}")
    with open(trace_log_path, "a") as fp:
        fp.write(f"\n{message}\n")
    return written_path


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


_VALIDATE_TOOL_RE = re.compile(
    r"""(?:name=["']validate_drug_md["']|tool_calls=\[[^\]]*\bvalidate_drug_md\b[^\]]*\])"""
)
_VALIDATE_PASS_RE = re.compile(r"""["']valid["']\s*:\s*(?:true|True)""")


def _validate_report_finalization(data_dir: Path) -> dict:
    """Run the host-side finalization validator and return its parsed JSON."""
    try:
        from src.agents.drug_target.tools.stage_logic import (
            validate_drug_report_finalization,
        )

        impl = (
            getattr(validate_drug_report_finalization, "func", None)
            or validate_drug_report_finalization
        )
        if callable(impl):
            raw = cast(Callable[..., Any], impl)(data_dir=str(data_dir))
        else:
            raw = validate_drug_report_finalization.invoke(
                {"data_dir": str(data_dir)}
            )
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(parsed, dict):
            return parsed
        return {
            "valid": False,
            "issue_count": 1,
            "issues": [
                {
                    "code": "REPORT_FINALIZATION_VALIDATOR_ERROR",
                    "message": "Validator returned a non-dict result.",
                }
            ],
        }
    except Exception as exc:
        return {
            "valid": False,
            "issue_count": 1,
            "issues": [{"code": "REPORT_FINALIZATION_VALIDATOR_ERROR", "message": str(exc)}],
        }


def _json_tool_result(raw: object) -> dict:
    if isinstance(raw, str):
        return json.loads(raw)
    if isinstance(raw, dict):
        return raw
    return {"result": raw}


_HYPOTHESIS_QUALITY_STATE_FIELDS = (
    "hypothesis_quality_valid",
    "hypothesis_quality_errors",
    "hypothesis_retry_attempted",
    "hypothesis_retry_attempts",
    "hypothesis_retry_status",
    "hypothesis_retry_error",
)


def _capture_hypothesis_quality_state(result: dict, holder: dict) -> None:
    """Copy graph hypothesis quality fields into the traced-run summary state."""
    for field in _HYPOTHESIS_QUALITY_STATE_FIELDS:
        if field in result:
            holder[field] = result[field]
    if "report_finalization_error" in result:
        holder["report_finalization_error"] = result["report_finalization_error"]


def _remaining_timeout_seconds(
    started_at: float,
    timeout_seconds: float,
    *,
    now: float | None = None,
) -> float:
    """Return remaining CLI timeout budget, clamped at zero."""
    current = time.time() if now is None else now
    return max(0.0, timeout_seconds - (current - started_at))


def _record_hypothesis_quality_timeout(
    holder: dict,
    message: str,
    *,
    attempted: bool,
) -> None:
    """Fail closed when the traced runner timeout blocks quality validation."""
    holder["hypothesis_quality_valid"] = False
    holder["hypothesis_quality_errors"] = [
        {
            "code": "HYPOTHESIS_QUALITY_GATE_TIMEOUT",
            "message": message,
        }
    ]
    holder["hypothesis_retry_attempted"] = attempted
    attempts = int(holder.get("hypothesis_retry_attempts") or 0)
    if attempted and attempts == 0:
        attempts = 1
    holder["hypothesis_retry_attempts"] = attempts
    holder["hypothesis_retry_status"] = "timeout"
    holder["hypothesis_retry_error"] = message
    holder["report_finalization_error"] = f"HYPOTHESIS_QUALITY_GATE_FAILED: {message}"


def _should_finalize_after_hypothesis_quality(state: dict) -> bool:
    """Mirror super-graph routing: finalize only after hypothesis quality passes."""
    return state.get("hypothesis_quality_valid") is True


def _format_hypothesis_quality_errors(errors: object, max_items: int = 5) -> str:
    if not isinstance(errors, list) or not errors:
        return "—"
    rendered: list[str] = []
    for err in errors[:max_items]:
        if isinstance(err, dict):
            code = str(err.get("code") or "UNKNOWN")
            message = str(err.get("message") or "")
            rendered.append(f"{code}: {message}" if message else code)
        else:
            rendered.append(str(err))
    if len(errors) > max_items:
        rendered.append(f"... +{len(errors) - max_items} more")
    return "; ".join(rendered)


def _is_hypothesis_writer_stream_node(node_path: str, node_name: str) -> bool:
    path_parts = [part.strip().casefold() for part in node_path.split(">")]
    return (
        node_name.casefold() == "hypothesis_writer"
        or "hypothesis_writer" in path_parts
    )


def _hypothesis_budget_exceeded(
    started_at: float | None,
    now: float,
    budget_seconds: int,
) -> bool:
    return started_at is not None and now - started_at >= budget_seconds


def _hypothesis_stream_budget_seconds() -> int:
    raw = os.environ.get("DRUG_TARGET_HYPOTHESIS_STREAM_BUDGET_SECONDS", "900")
    try:
        return max(1, int(raw))
    except ValueError:
        return 900


def _allow_hypothesis_quality_retry_after_budget_abort() -> bool:
    raw = os.environ.get("DRUG_TARGET_ALLOW_HYPOTHESIS_RETRY_AFTER_BUDGET_ABORT", "")
    return raw.strip().casefold() in {"1", "true", "yes", "on"}


async def _close_async_stream(stream: object) -> None:
    closer = getattr(stream, "aclose", None)
    if closer is None:
        return
    result = closer()
    if inspect.isawaitable(result):
        await result


def _annotation_field(source_field: object) -> str:
    field = str(source_field or "").rsplit("::", 1)[-1].rsplit(".", 1)[-1]
    return field if re.match(r"^[a-z_][a-z0-9_]*$", field, re.IGNORECASE) else "interpretation"


def _slot_meta_from_id(slot_id: str) -> dict:
    meta: dict[str, object] = {"slot_id": slot_id}
    for part in str(slot_id).split("|"):
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        meta[key] = value
    return meta


def _provenance_gene(entry: dict) -> str:
    source_field = str(entry.get("source_field") or "")
    if "::" in source_field:
        return source_field.split("::", 1)[0].strip().upper()
    source_file = str(entry.get("source_file") or "")
    match = re.search(r"(?:ot|stage3)_([A-Za-z0-9_-]+)\.json$", source_file)
    return match.group(1).upper() if match else ""


def _slot_provenance_score(entry: dict, slot: dict) -> int:
    source_class = str(entry.get("source_class") or "").casefold()
    source_field = str(entry.get("source_field") or "")
    field = _annotation_field(source_field).casefold()
    slot_gene = str(slot.get("gene") or "").strip().upper()
    slot_text = " ".join(
        str(slot.get(key) or "")
        for key in ("section", "slot", "instruction", "slot_id")
    ).casefold()
    score = 0
    if slot_gene and _provenance_gene(entry) == slot_gene:
        score += 100
    if "preclinical" in slot_text:
        if source_class == "chembl_preclinical" or field == "preclinical_compounds":
            score += 40
        elif field == "clinical_drugs":
            score -= 10
    elif "clinical" in slot_text or "approved" in slot_text:
        if source_class == "opentargets_clinical" or field == "clinical_drugs":
            score += 40
        elif field == "preclinical_compounds":
            score -= 10
    elif "drug_profile" in slot_text or "what drugs exist" in slot_text:
        if field in {"clinical_drugs", "preclinical_compounds"}:
            score += 25
        if source_class == "opentargets_clinical":
            score += 5
    if any(token in slot_text for token in ("rubric", "scoring", "recommendation", "biological_context", "stage1")):
        if source_class == "deepmast_rubric":
            score += 30
    if "hypothesis" in slot_text and source_class == "deepmast_rubric":
        score += 10
    return score


def _select_template_provenance(
    slot_id: str,
    slot_metadata: dict,
    provenance_entries: list[dict],
    fallback_provenance: dict,
    index: int,
) -> tuple[dict, str | None]:
    slot = slot_metadata.get(slot_id)
    if not isinstance(slot, dict):
        slot = _slot_meta_from_id(slot_id)
    if not provenance_entries:
        return dict(fallback_provenance), "provenance_index_missing"
    scored = [
        (_slot_provenance_score(entry, slot), position, entry)
        for position, entry in enumerate(provenance_entries)
    ]
    best_score, _, best_entry = max(scored, key=lambda item: (item[0], -item[1]))
    if best_score > 0:
        return dict(best_entry), None
    return (
        dict(provenance_entries[index % len(provenance_entries)]),
        "no_slot_specific_provenance_match",
    )


def _load_json_or_default(path: Path, default: object) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _artifact_predates_run(path: Path, run_started_at: float) -> bool:
    try:
        return not path.exists() or path.stat().st_mtime < run_started_at
    except OSError:
        return True


def _should_skip_hypothesis_quality_after_budget_abort(
    *,
    hypothesis_budget_aborted: bool,
    hypothesis_path: Path,
    run_started_at: float,
) -> bool:
    if _allow_hypothesis_quality_retry_after_budget_abort():
        return False
    return hypothesis_budget_aborted and _artifact_predates_run(
        hypothesis_path,
        run_started_at,
    )


def _hypothesis_budget_abort_message(
    *,
    data_dir: Path,
    hypothesis_path: Path,
    evidence_ready_started_at: float | None,
    hypothesis_started_at: float | None,
    now: float,
    budget_seconds: int,
    run_started_at: float,
) -> str | None:
    if (
        _hypothesis_budget_exceeded(
            evidence_ready_started_at,
            now,
            budget_seconds,
        )
        and _artifact_predates_run(hypothesis_path, run_started_at)
    ):
        return (
            "[HYPOTHESIS-BUDGET] evidence has been ready for "
            f"{budget_seconds}s but no fresh hypothesis_report.json was saved; "
            "stopping the stream so the graph-level quality gate can handle recovery."
        )
    if (
        _hypothesis_budget_exceeded(
            evidence_ready_started_at,
            now,
            budget_seconds,
        )
        and not _artifact_predates_run(hypothesis_path, run_started_at)
        and (data_dir / "evidence" / "assessment_results.json").exists()
        and (data_dir / "evidence" / "stage1_filter_results.json").exists()
    ):
        return (
            "[HYPOTHESIS-BUDGET] fresh hypothesis_report.json was saved, but "
            f"the graph stream did not finish within {budget_seconds}s after "
            "evidence became ready; stopping the stream so the graph-level "
            "quality gate can finalize or retry."
        )
    if (
        _hypothesis_budget_exceeded(
            hypothesis_started_at,
            now,
            budget_seconds,
        )
        and (data_dir / "evidence" / "assessment_results.json").exists()
        and (data_dir / "evidence" / "stage1_filter_results.json").exists()
    ):
        return (
            "[HYPOTHESIS-BUDGET] hypothesis_writer stream exceeded "
            f"{budget_seconds}s after deterministic evidence artifacts were written; "
            "stopping the stream so the graph-level quality gate can handle recovery."
        )
    return None


def _should_invoke_finalize_report(data_dir: Path, run_started_at: float) -> bool:
    drug_md_path = data_dir / "drug.md"
    hypothesis_path = data_dir / "evidence" / "hypothesis_report.json"
    drug_html_path = data_dir / "drug_report.html"
    report_validation_path = data_dir / "report_validation.json"
    required_artifacts = [
        data_dir / "target_assessment.json",
        drug_html_path,
        report_validation_path,
    ]
    if _artifact_predates_run(drug_md_path, run_started_at):
        return True
    if any(not artifact.exists() for artifact in required_artifacts):
        return True
    try:
        if not hypothesis_path.exists():
            return False
        hypothesis_mtime = hypothesis_path.stat().st_mtime
        return hypothesis_mtime > drug_md_path.stat().st_mtime or any(
            hypothesis_mtime > artifact.stat().st_mtime
            for artifact in (drug_html_path, report_validation_path)
        )
    except OSError:
        return False


def _should_print_finalize_skip_note(
    report_status: dict,
    *,
    pre_run_drug_md_exists: bool,
    finalize_report_invoked: bool,
) -> bool:
    return (
        bool(report_status.get("finalized"))
        and pre_run_drug_md_exists
        and not finalize_report_invoked
    )


def _host_hypothesis_fallback_enabled() -> bool:
    value = os.environ.get("DRUG_TARGET_ENABLE_HOST_HYPOTHESIS_FALLBACK", "")
    return value.strip().casefold() in {"1", "true", "yes", "on", "smoke", "recovery"}


def _hypothesis_report_ready_for_finalization(path: Path, run_started_at: float) -> bool:
    if _artifact_predates_run(path, run_started_at):
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if payload.get("host_finalized") and payload.get("fallback_quality") == "degraded":
        return _host_hypothesis_fallback_enabled()
    return True


def _evidence_ready_for_hypothesis(data_dir: Path) -> bool:
    evidence_dir = data_dir / "evidence"
    assessment = _load_json_or_default(evidence_dir / "assessment_results.json", {})
    candidates = assessment.get("stage3_candidates", []) if isinstance(assessment, dict) else []
    genes = [
        str(row.get("gene") or row.get("gene_symbol") or "").strip().upper()
        for row in candidates
        if isinstance(row, dict) and str(row.get("gene") or row.get("gene_symbol") or "").strip()
    ]
    if not genes:
        return False
    if not (
        (evidence_dir / "stage1_filter_results.json").exists()
        or (evidence_dir / "stage1_filter_results.csv").exists()
    ):
        return False
    return all((evidence_dir / f"stage3_{gene}.json").exists() for gene in genes)


def _host_stage1_rows(evidence_dir: Path) -> list[dict]:
    rows = _load_json_or_default(evidence_dir / "stage1_filter_results.json", [])
    return rows if isinstance(rows, list) else []


def _stage1_filename(ligand: str, receptor: str) -> str:
    return f"stage1_{ligand.upper()}--{receptor.upper()}.json"


def _host_metric_direction(metric: object) -> str:
    if not isinstance(metric, dict):
        return "not_determined"
    risk_ratio = metric.get("risk_ratio")
    if isinstance(risk_ratio, (int, float)):
        if risk_ratio > 1:
            return "enriched"
        if risk_ratio < 1:
            return "depleted"
    diff = metric.get("diff")
    if isinstance(diff, (int, float)):
        if diff > 0:
            return "enriched"
        if diff < 0:
            return "depleted"
    return "not_determined"


def _host_stage1_is_target_cell_intrinsic(payload: object) -> bool:
    census = payload.get("census_validation") if isinstance(payload, dict) else None
    target_vs_rest = census.get("target_vs_rest") if isinstance(census, dict) else None
    if not isinstance(target_vs_rest, dict):
        return False
    if _host_metric_direction(target_vs_rest.get("coexpression")) != "enriched":
        return False
    return all(
        _host_metric_direction(target_vs_rest.get(metric_key)) != "depleted"
        for metric_key in ("gene_a", "gene_b")
    )


def _host_hypothesis_refs_for_gene(
    gene: str,
    evidence_dir: Path,
    passed_rows: list[dict],
) -> tuple[list[str], list[dict]]:
    gene = gene.upper()
    refs: list[str] = []
    details: list[dict] = []

    def add_ref(filename: str, usage: str) -> None:
        if filename in refs or not (evidence_dir / filename).exists():
            return
        refs.append(filename)
        stage1_status = "not_stage1"
        if filename.startswith("stage1_"):
            stage1_status = "passed"
        details.append(
            {
                "filename": filename,
                "usage": usage,
                "stage1_pair_status": stage1_status,
                "display_reference": filename,
            }
        )

    add_ref(f"stage3_{gene}.json", "primary")
    add_ref(f"ot_{gene}.json", "supporting")

    for row in passed_rows:
        ligand = str(row.get("ligand") or "").strip().upper()
        receptor = str(row.get("receptor") or "").strip().upper()
        if not ligand or not receptor or gene not in {ligand, receptor}:
            continue
        stage1_filename = _stage1_filename(ligand, receptor)
        stage1_payload = _load_json_or_default(evidence_dir / stage1_filename, {})
        if not _host_stage1_is_target_cell_intrinsic(stage1_payload):
            continue
        add_ref(stage1_filename, "supporting")

    return refs, details


def _host_stage1_cell_types_for_refs(evidence_dir: Path, refs: list[str]) -> list[str]:
    cell_types: list[str] = []
    for ref in refs:
        if not ref.startswith("stage1_"):
            continue
        payload = _load_json_or_default(evidence_dir / ref, {})
        if not _host_stage1_is_target_cell_intrinsic(payload):
            continue
        census = payload.get("census_validation") if isinstance(payload, dict) else None
        if not isinstance(census, dict):
            continue
        for key in ("resolved_cell_type", "requested_cell_type", "target_cell_type"):
            cell_type = str(census.get(key) or "").strip()
            if cell_type and cell_type not in cell_types:
                cell_types.append(cell_type)
    return cell_types


def _host_hypothesis_gene_groups(
    featured_genes: list[str],
    *,
    max_groups: int = 6,
) -> list[list[str]]:
    if len(featured_genes) <= max_groups:
        return [[gene] for gene in featured_genes]

    groups = [[gene] for gene in featured_genes[:max_groups]]
    for gene in featured_genes[max_groups:]:
        groups[-1].append(gene)
    return groups


def _build_host_hypothesis_report(data_dir: Path, disease: str) -> dict:
    evidence_dir = data_dir / "evidence"
    assessment = _load_json_or_default(evidence_dir / "assessment_results.json", {})
    candidates = assessment.get("stage3_candidates", []) if isinstance(assessment, dict) else []
    featured_genes = [
        str(row.get("gene") or row.get("gene_symbol") or "").strip().upper()
        for row in candidates
        if isinstance(row, dict) and str(row.get("gene") or row.get("gene_symbol") or "").strip()
    ]
    rows = _host_stage1_rows(evidence_dir)
    passed_rows = [row for row in rows if isinstance(row, dict) and row.get("passed") is True]

    categories = [
        "Mechanism of Action",
        "Therapeutic Strategy",
        "Cross-Target Interaction",
        "Novel Pathway",
    ]
    hypotheses: list[dict] = []
    referenced: set[str] = set()
    for index, genes in enumerate(_host_hypothesis_gene_groups(featured_genes), start=1):
        refs: list[str] = []
        details: list[dict] = []
        for gene in genes:
            gene_refs, gene_details = _host_hypothesis_refs_for_gene(
                gene,
                evidence_dir,
                passed_rows,
            )
            for ref in gene_refs:
                if ref not in refs:
                    refs.append(ref)
            detail_filenames = {item["filename"] for item in details}
            for detail in gene_details:
                if detail["filename"] not in detail_filenames:
                    details.append(detail)
                    detail_filenames.add(detail["filename"])
        referenced.update(refs)
        cell_types = _host_stage1_cell_types_for_refs(evidence_dir, refs)
        validation_context = (
            f"{', '.join(cell_types)} models"
            if cell_types
            else "disease-relevant cell models"
        )
        category = categories[(index - 1) % len(categories)]
        gene_label = " and ".join(genes)
        gene_phrase = ", ".join(genes)
        hypotheses.append(
            {
                "rank": index,
                "title": f"[FEATURED-GAP] {gene_label} evidence-backed target hypothesis",
                "category": category,
                "core_claim": (
                    f"{gene_phrase} remains a testable {disease} target set because the current "
                    "Stage 3 target evidence and eligible Stage 1 support converge on "
                    "a disease-relevant mechanism. Failed Stage 1 pairs are excluded "
                    "from the support set and are not used as mechanistic evidence."
                ),
                "evidence_references": refs,
                "evidence_reference_details": details,
                "contrast_references": [],
                "biological_entities": {
                    "genes": genes,
                    "pathways": [],
                    "cell_types": cell_types,
                    "drugs": [],
                },
                "falsifiable_prediction": (
                    f"Perturbing {gene_phrase} will produce a measurable disease-relevant "
                    "phenotype change compared with matched controls."
                ),
                "validation_approach": (
                    f"Test {gene_phrase} perturbation in {validation_context} with "
                    "matched negative controls and orthogonal readouts."
                ),
                "scores": {
                    "evidence_coverage": 1.0 if refs else 0.5,
                    "specificity": 0.7,
                    "novelty": 0.6,
                    "actionability": 0.7,
                    "composite": 0.75,
                },
            }
        )

    eligible: set[str] = set()
    for gene in featured_genes:
        stage3_name = f"stage3_{gene}.json"
        if (evidence_dir / stage3_name).exists():
            eligible.add(stage3_name)
    for row in passed_rows:
        ligand = str(row.get("ligand") or "").strip().upper()
        receptor = str(row.get("receptor") or "").strip().upper()
        if not ligand or not receptor:
            continue
        filename = _stage1_filename(ligand, receptor)
        if (evidence_dir / filename).exists():
            eligible.add(filename)

    return {
        "schema_version": "hypothesis_report.v2",
        "disease": disease,
        "hypotheses_generated": len(hypotheses),
        "hypotheses_retained": len(hypotheses),
        "hypotheses": hypotheses,
        "gap_analysis": {
            "total_evidence_files": len(eligible),
            "referenced_files": len(referenced & eligible),
            "orphan_files": sorted(eligible - referenced),
        },
        "host_finalized": True,
        "fallback_quality": "degraded",
        "host_finalization_reason": "deterministic fallback after traced hypothesis phase",
    }


def _run_host_hypothesis_fallback(
    data_dir: Path,
    disease: str,
    trace_log_path: Path,
) -> dict:
    """Persist a schema-valid hypothesis_report.json without the LLM writer.

    This recovery path is intentionally conservative: it covers every current
    Stage 3 candidate, cites only existing Stage 3/OpenTargets files and Stage
    1 pair files whose filter row has passed=true, and never restores the
    legacy _FAILED suffix.
    """
    result: dict = {
        "saved": False,
        "errors": [],
        "path": None,
        "host_hypothesis_fallback_used": False,
    }

    def record(message: str) -> None:
        with open(trace_log_path, "a", encoding="utf-8") as fp:
            fp.write(f"\n[HOST-HYPOTHESIS-FIXUP] {message}\n")

    try:
        from src.agents.drug_target.tools.hypothesis_schema import (
            persist_hypothesis_report,
        )

        report = _build_host_hypothesis_report(data_dir, disease)
        if not report["hypotheses"]:
            result["errors"].append("no stage3_candidates available for host hypothesis fixup")
            record(result["errors"][-1])
            return result

        persist_result = persist_hypothesis_report(data_dir, report)
        result.update(persist_result)
        result["host_hypothesis_fallback_used"] = bool(persist_result.get("saved"))
        if persist_result.get("saved"):
            record(
                "save_hypothesis_report completed with "
                f"{report['hypotheses_retained']} hypotheses"
            )
        else:
            record(f"save_hypothesis_report failed: {persist_result}")
        return result
    except Exception as exc:
        result["errors"].append(f"{type(exc).__name__}: {exc}")
        record(result["errors"][-1])
        return result


def _maybe_run_host_hypothesis_fallback_before_quality(
    data_dir: Path,
    disease: str,
    trace_log_path: Path,
    run_started_at: float,
) -> dict:
    result: dict = {
        "saved": False,
        "errors": [],
        "path": None,
        "host_hypothesis_fallback_used": False,
    }
    hypothesis_path = data_dir / "evidence" / "hypothesis_report.json"
    if (
        not _host_hypothesis_fallback_enabled()
        or _artifact_predates_run(hypothesis_path, run_started_at)
    ):
        return result

    try:
        from src.agents.drug_target.tools.hypothesis_schema import (
            validate_hypothesis_report_quality,
        )

        quality = validate_hypothesis_report_quality(str(data_dir))
    except Exception as exc:
        quality = {
            "valid": False,
            "errors": [
                {
                    "code": "HYPOTHESIS_PRE_QUALITY_EXCEPTION",
                    "message": f"{type(exc).__name__}: {exc}",
                }
            ],
        }
    if quality.get("valid") is True:
        return result

    with open(trace_log_path, "a", encoding="utf-8") as fp:
        fp.write(
            "\n[HOST-HYPOTHESIS-FIXUP] pre-quality validation failed; "
            "writing degraded deterministic hypothesis_report.json before "
            "LLM retry\n"
        )
    return _run_host_hypothesis_fallback(data_dir, disease, trace_log_path)


def _build_template_expansions(spec_path: Path) -> dict:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    fallback_provenance = dict(spec["example_sentence"]["source_provenance"])
    reference_card = _load_json_or_default(spec_path.with_name("drug_report_reference_card.json"), {})
    provenance_index = (
        reference_card.get("provenance_index", {})
        if isinstance(reference_card, dict)
        else {}
    )
    slot_metadata = {
        str(slot.get("slot_id")): slot
        for slot in (
            reference_card.get("expansion_slots", [])
            if isinstance(reference_card, dict)
            else []
        )
        if isinstance(slot, dict) and slot.get("slot_id")
    }
    provenance_entries = [
        dict(entry)
        for _, entry in sorted(provenance_index.items())
        if isinstance(entry, dict)
    ]
    required_slots = list(spec["required_slot_ids"])

    def sentence_for_slot(slot_id: str, index: int) -> dict:
        provenance, degraded_reason = _select_template_provenance(
            slot_id,
            slot_metadata,
            provenance_entries,
            fallback_provenance,
            index,
        )
        source_field = str(provenance.get("source_field") or "interpretation")
        field = _annotation_field(source_field)
        source_class = str(provenance.get("source_class") or "interpretation")
        provenance.setdefault("claim_type", "direct_value")
        if "source_value" not in provenance:
            provenance["source_value"] = None
        sentence = {
            "text": (
                "This section is limited to evidence fields captured by the run "
                f"for {slot_id}. [source: {source_class}:{field}]"
            ),
            "source_fields": [source_field, field] if source_field != field else [field],
            "source_provenance": provenance,
            "interpretation": False,
            "hedging_verbs_present": False,
        }
        if degraded_reason:
            sentence["fallback_quality"] = "degraded"
            sentence["fallback_reason"] = degraded_reason
        return sentence

    return {
        "schema_version": "report_expansions.v1",
        "slots": [
            {
                "slot_id": slot_id,
                "sentences": [sentence_for_slot(slot_id, index)],
            }
            for index, slot_id in enumerate(required_slots)
        ],
    }


def _inspect_report_outputs(data_dir: Path, trace_log_path: Path) -> dict:
    """Inspect whether the traced run produced a fully finalized report."""
    evidence_dir = data_dir / "evidence"
    drug_md_path = data_dir / "drug.md"
    drug_html_path = data_dir / "drug_report.html"
    drug_md_content = (
        drug_md_path.read_text(encoding="utf-8") if drug_md_path.exists() else ""
    )
    expand_marker_count = drug_md_content.count("EXPAND")
    finalization_result = _validate_report_finalization(data_dir)
    report_finalization_valid = bool(finalization_result.get("valid"))
    validate_check = finalization_result.get("checks", {}).get("validate_drug_md", {})
    validate_passed = (
        validate_check.get("status") == "pass"
        if validate_check
        else report_finalization_valid
    )

    status = {
        "evidence_count": len(list(evidence_dir.glob("*.json"))) if evidence_dir.exists() else 0,
        "assessment_exists": (evidence_dir / "assessment_results.json").exists()
        if evidence_dir.exists()
        else False,
        "target_assessment_exists": (data_dir / "target_assessment.json").exists(),
        "drug_md_exists": drug_md_path.exists(),
        "drug_html_exists": drug_html_path.exists(),
        "expand_marker_count": expand_marker_count,
        "validate_drug_md_passed": validate_passed,
        "report_finalization_valid": report_finalization_valid,
        "report_finalization_issue_count": finalization_result.get("issue_count"),
        "report_finalization_issues": finalization_result.get("issues", []),
        "missing_requirements": [],
    }

    if status["evidence_count"] <= 0:
        status["missing_requirements"].append("evidence files present")
    if not status["assessment_exists"]:
        status["missing_requirements"].append("assessment_results.json present")
    if not status["target_assessment_exists"]:
        status["missing_requirements"].append("target_assessment.json present")
    if not status["drug_md_exists"]:
        status["missing_requirements"].append("drug.md present")
    if not status["drug_html_exists"]:
        status["missing_requirements"].append("drug_report.html present")
    if expand_marker_count:
        status["missing_requirements"].append("no EXPAND markers")
    if not report_finalization_valid:
        status["missing_requirements"].append("validate_drug_report_finalization valid=true")

    status["finalized"] = not status["missing_requirements"]
    return status


async def run_traced(args: argparse.Namespace) -> int:
    """Run the DrugTarget agent with step-by-step tracing."""

    ollama_base_url = _configure_ollama_port_override(args)
    _configure_provider_env(args)

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

    # ── Token usage tracker ──────────────────────────────────────────
    from scripts.token_tracker import TokenUsageTracker
    token_tracker = TokenUsageTracker()
    token_usage_path = data_dir / f"token_usage_{timestamp}.json"

    # ── Resume mode env-var (must be set BEFORE agent construction) ──
    if args.skip_evidence_assessor:
        os.environ["DRUG_TARGET_SKIP_EVIDENCE_ASSESSOR"] = "1"
        print("[CONFIG] RESUME mode — evidence_assessor will be skipped "
              "(env DRUG_TARGET_SKIP_EVIDENCE_ASSESSOR=1)")

    # ── Create agent ──────────────────────────────────────────────────
    from src.agents.drug_target.agent import (
        DrugTargetConfig,
        create_drug_target_agent,
    )

    hypothesis_writer_skill_names = resolve_hypothesis_writer_skill_names(
        args.hypothesis_skill_set
    )
    enable_skill_activator = (
        args.skill_activation_mode == "middleware_plus_activator"
    )

    config = DrugTargetConfig(
        provider=args.provider,
        data_dir=str(data_dir),
        disease=args.disease,
        use_checkpointer=True,
        enable_census=args.census,
        hypothesis_writer_skill_names=hypothesis_writer_skill_names,
        enable_skill_activator=enable_skill_activator,
        skill_activation_mode=args.skill_activation_mode,
        hypothesis_writer_prompt_mode=args.hypothesis_writer_prompt_mode,
    )
    agent, backend = create_drug_target_agent(config)
    print(f"[CONFIG] Agent created (provider={args.provider})")
    print(f"[CONFIG] Disease: {args.disease}")
    print(f"[CONFIG] Hypothesis skill set: {args.hypothesis_skill_set}")
    print(f"[CONFIG] Skill activation mode: {args.skill_activation_mode}")
    print(f"[CONFIG] Hypothesis writer prompt mode: {args.hypothesis_writer_prompt_mode}")
    print(f"[CONFIG] LLM_PROVIDER env: {os.environ['LLM_PROVIDER']}")
    active_model = os.getenv("LLM_MODEL") or os.getenv("OLLAMA_MODEL") or ""
    if active_model:
        print(f"[CONFIG] LLM model: {active_model}")
    if ollama_base_url:
        print(f"[CONFIG] Model base URL: {ollama_base_url}")
    if args.max_tokens is not None:
        print(f"[CONFIG] max_tokens: {args.max_tokens}")
    if args.enable_thinking is not None:
        print(f"[CONFIG] enable_thinking: {args.enable_thinking}")
    print(f"[CONFIG] Census API: {'ENABLED' if args.census else 'DISABLED'}")
    print(
        "[CONFIG] Hypothesis quality gate retry: "
        f"{os.environ.get('DRUG_TARGET_GRAPH_HYPOTHESIS_RETRY', '1')}"
    )
    print(
        "[CONFIG] Hypothesis retry timeout seconds: "
        f"{os.environ.get('DRUG_TARGET_HYPOTHESIS_RETRY_TIMEOUT_SECONDS', '600')}"
    )

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
    hypothesis_budget_seconds = _hypothesis_stream_budget_seconds()
    hypothesis_started_at: float | None = None
    evidence_ready_started_at: float | None = None
    hypothesis_budget_aborted = False
    captured_drug_md_holder = {"content": None}  # Fallback: capture drug.md from Command(files=...)
    hypothesis_writer_read_skill_calls: list[dict[str, Any]] = []
    all_read_skill_calls: list[dict[str, Any]] = []
    save_hypothesis_report_event: dict[str, Any] | None = None
    # Capture finalize_report state fields from stream updates
    captured_finalization_state: dict = {
        "report_finalization_error": None,
        "evidence_truncated": False,
        "hypothesis_quality_valid": None,
        "hypothesis_quality_errors": [],
        "hypothesis_retry_attempted": None,
        "hypothesis_retry_attempts": None,
        "hypothesis_retry_status": None,
        "hypothesis_retry_error": None,
    }
    # Record whether drug.md existed before this run (for idempotency SOP message)
    pre_run_drug_md_exists = (data_dir / "drug.md").exists()
    finalize_report_invoked = False
    stream: Any | None = None

    try:
        stream = agent.astream(
            {"messages": [{"role": "user", "content": initial_message}]},
            config={
                "configurable": {"thread_id": thread_id},
                "callbacks": [file_handler, token_tracker],
            },
            stream_mode="updates",
            subgraphs=True,
        )
        chunk_wait_seconds = min(30, hypothesis_budget_seconds)
        stream_iter = stream.__aiter__()
        pending_chunk: asyncio.Task[Any] | None = None
        while True:
            if pending_chunk is None:
                pending_chunk = asyncio.create_task(anext(stream_iter))
            done, _ = await asyncio.wait({pending_chunk}, timeout=chunk_wait_seconds)
            if not done:
                elapsed = time.time() - start
                if elapsed > timeout_seconds:
                    print(f"\n[TIMEOUT] {args.timeout}m limit reached")
                    pending_chunk.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await pending_chunk
                    break
                now = time.time()
                hypothesis_path = data_dir / "evidence" / "hypothesis_report.json"
                if (
                    evidence_ready_started_at is None
                    and _evidence_ready_for_hypothesis(data_dir)
                    and _artifact_predates_run(hypothesis_path, start)
                ):
                    evidence_ready_started_at = now
                message = _hypothesis_budget_abort_message(
                    data_dir=data_dir,
                    hypothesis_path=hypothesis_path,
                    evidence_ready_started_at=evidence_ready_started_at,
                    hypothesis_started_at=hypothesis_started_at,
                    now=now,
                    budget_seconds=hypothesis_budget_seconds,
                    run_started_at=start,
                )
                if message:
                    print(f"\n{message}")
                    trace_log_fp.write(f"\n{message}\n")
                    trace_log_fp.flush()
                    hypothesis_budget_aborted = True
                    pending_chunk.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await pending_chunk
                    break
                continue
            try:
                chunk = pending_chunk.result()
            except StopAsyncIteration:
                break
            finally:
                pending_chunk = None

            elapsed = time.time() - start
            if elapsed > timeout_seconds:
                print(f"\n[TIMEOUT] {args.timeout}m limit reached")
                break

            namespace, update = chunk
            node_path = " > ".join(namespace) if namespace else "orchestrator"
            abort_for_hypothesis_budget = False

            for node_name, node_data in update.items():
                now = time.time()
                hypothesis_path = data_dir / "evidence" / "hypothesis_report.json"
                if (
                    evidence_ready_started_at is None
                    and _evidence_ready_for_hypothesis(data_dir)
                    and _artifact_predates_run(hypothesis_path, start)
                ):
                    evidence_ready_started_at = now

                if (
                    hypothesis_started_at is None
                    and _is_hypothesis_writer_stream_node(node_path, node_name)
                ):
                    hypothesis_started_at = now
                message = _hypothesis_budget_abort_message(
                    data_dir=data_dir,
                    hypothesis_path=hypothesis_path,
                    evidence_ready_started_at=evidence_ready_started_at,
                    hypothesis_started_at=hypothesis_started_at,
                    now=now,
                    budget_seconds=hypothesis_budget_seconds,
                    run_started_at=start,
                )
                if message:
                    print(f"\n{message}")
                    trace_log_fp.write(f"\n{message}\n")
                    trace_log_fp.flush()
                    hypothesis_budget_aborted = True
                    abort_for_hypothesis_budget = True
                    break

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

                writer_read_calls = extract_hypothesis_writer_read_skill_file_calls(
                    node_path=node_path,
                    node_name=node_name,
                    node_data=node_data,
                    exposed_skill_names=hypothesis_writer_skill_names,
                    infer_unscoped_registered=args.skip_evidence_assessor,
                )
                for call in writer_read_calls:
                    call["node_counter"] = node_counter
                    call["elapsed_s"] = round(elapsed, 3)
                hypothesis_writer_read_skill_calls.extend(writer_read_calls)

                read_calls = extract_read_skill_file_calls(
                    node_path=node_path,
                    node_name=node_name,
                    node_data=node_data,
                    exposed_skill_names=hypothesis_writer_skill_names,
                    scope="",
                )
                for call in read_calls:
                    call["node_counter"] = node_counter
                    call["elapsed_s"] = round(elapsed, 3)
                all_read_skill_calls.extend(read_calls)

                if save_hypothesis_report_event is None:
                    save_calls = extract_named_tool_calls(
                        node_path=node_path,
                        node_name=node_name,
                        node_data=node_data,
                        tool_name="save_hypothesis_report",
                        scope="hypothesis_writer",
                    )
                    if save_calls:
                        save_hypothesis_report_event = {
                            **save_calls[0],
                            "node_counter": node_counter,
                            "elapsed_s": round(elapsed, 3),
                        }

                # Capture drug.md content from Command(files=...) state updates
                _capture_drug_md_from_update(node_data, captured_drug_md_holder)
                # Capture finalize_report state fields when the node emits them
                if isinstance(node_data, dict):
                    if "report_finalization_error" in node_data:
                        captured_finalization_state["report_finalization_error"] = (
                            node_data["report_finalization_error"]
                        )
                    if "evidence_truncated" in node_data:
                        captured_finalization_state["evidence_truncated"] = bool(
                            node_data["evidence_truncated"]
                        )
                    _capture_hypothesis_quality_state(
                        node_data,
                        captured_finalization_state,
                    )
            if abort_for_hypothesis_budget:
                break

    except asyncio.CancelledError:
        elapsed = time.time() - start
        print(
            f"\n[CANCELLED at {elapsed:.1f}s] Graph task cancelled — "
            f"downstream fixup/fallback will decide whether outputs are complete."
        )
        trace_log_fp.write(
            f"\n[CANCELLED] at {elapsed:.1f}s — graceful shutdown, not re-raised\n"
        )
        trace_log_fp.flush()
        # Do NOT re-raise; let the STAGE1-FIXUP / fallback tail run.
    except Exception as e:
        elapsed = time.time() - start
        print(f"\n[ERROR at {elapsed:.1f}s] {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if hypothesis_budget_aborted and stream is not None:
            await _close_async_stream(stream)
        trace_log_fp.close()
        if backend and hasattr(backend, "cleanup"):
            cast(_CleanupBackend, backend).cleanup()

    elapsed = time.time() - start

    # ── Stage 1 fixup: auto-run if evidence_assessor skipped it ────
    evidence_dir = data_dir / "evidence"
    assessment_path = evidence_dir / "assessment_results.json"
    stage1_pair_files = list(evidence_dir.glob("stage1_*--*.json")) if evidence_dir.exists() else []
    if assessment_path.exists() and len(stage1_pair_files) == 0:
        print(f"\n[STAGE1-FIXUP] assessment_results.json exists but no stage1 pair files.")
        print(f"[STAGE1-FIXUP] Running run_stage1_batch programmatically...")
        try:
            from src.agents.drug_target.tools.stage_domain_tools import run_stage1_batch
            stage1_result_raw = run_stage1_batch.invoke({
                "data_dir": str(data_dir),
                "disease": args.disease,
                "target_cell_type": "",
                "enable_census": args.census,
            })
            stage1_result = json.loads(stage1_result_raw) if isinstance(stage1_result_raw, str) else stage1_result_raw
            pairs_done = stage1_result.get("pairs_processed", 0)
            stage1_errors = stage1_result.get("errors", [])
            print(f"[STAGE1-FIXUP] Completed: {pairs_done} pairs saved")
            if stage1_errors:
                print(f"[STAGE1-FIXUP] Errors: {stage1_errors}")
            with open(trace_log_path, "a") as fp:
                fp.write(f"\n[STAGE1-FIXUP] run_stage1_batch: {pairs_done} pairs, errors={stage1_errors}\n")
        except Exception as exc:
            print(f"[STAGE1-FIXUP] Failed: {exc}")
            import traceback
            traceback.print_exc()

    hypothesis_path = evidence_dir / "hypothesis_report.json"
    host_hypothesis_fallback_used = False

    # ── Host hypothesis fixup: deterministic degraded recovery. This is
    # disabled for normal production runs unless explicitly enabled for smoke
    # or recovery runs via DRUG_TARGET_ENABLE_HOST_HYPOTHESIS_FALLBACK.
    hypothesis_stale = False
    if hypothesis_path.exists():
        try:
            hypothesis_stale = hypothesis_path.stat().st_mtime < start
        except OSError:
            hypothesis_stale = False
    if assessment_path.exists() and (
        hypothesis_budget_aborted or not hypothesis_path.exists() or hypothesis_stale
    ):
        reasons = []
        if hypothesis_budget_aborted:
            reasons.append("hypothesis_writer budget exceeded")
        if not hypothesis_path.exists():
            reasons.append("hypothesis_report.json missing")
        if hypothesis_stale:
            reasons.append("hypothesis_report.json predates this run")
        if not _host_hypothesis_fallback_enabled():
            print(
                "\n[HOST-HYPOTHESIS-FIXUP] SKIPPED — "
                + "; ".join(reasons)
                + "; set DRUG_TARGET_ENABLE_HOST_HYPOTHESIS_FALLBACK=1 "
                "only for smoke/recovery runs."
            )
            with open(trace_log_path, "a") as fp:
                fp.write(
                    "\n[HOST-HYPOTHESIS-FIXUP] skipped because fallback is disabled; "
                    + "; ".join(reasons)
                    + "\n"
                )
        else:
            print(
                "\n[HOST-HYPOTHESIS-FIXUP] "
                + "; ".join(reasons)
                + "; writing degraded deterministic hypothesis_report.json."
            )
            fixup_result = _run_host_hypothesis_fallback(
                data_dir,
                args.disease,
                trace_log_path,
            )
            host_hypothesis_fallback_used = bool(fixup_result.get("saved"))
            if fixup_result.get("saved"):
                print("[HOST-HYPOTHESIS-FIXUP] SUCCESS — degraded hypothesis_report.json saved")
            else:
                print(
                    "[HOST-HYPOTHESIS-FIXUP] FAILED — "
                    + "; ".join(fixup_result.get("errors", [])[:5])
                )
    if not host_hypothesis_fallback_used:
        pre_quality_fixup_result = _maybe_run_host_hypothesis_fallback_before_quality(
            data_dir,
            args.disease,
            trace_log_path,
            start,
        )
        host_hypothesis_fallback_used = bool(
            pre_quality_fixup_result.get("host_hypothesis_fallback_used")
        )
    with open(trace_log_path, "a", encoding="utf-8") as fp:
        fp.write(
            "\n[HOST-HYPOTHESIS-FIXUP] host_hypothesis_fallback_used: "
            f"{'YES' if host_hypothesis_fallback_used else 'NO'}\n"
        )

    activation_trace_path = resolve_activation_trace_path(
        args.activation_trace_json,
        data_dir=data_dir,
        timestamp=timestamp,
    )
    write_activation_trace_checkpoint(
        activation_trace_path=activation_trace_path,
        exposed_skill_names=hypothesis_writer_skill_names,
        hypothesis_writer_read_skill_calls=hypothesis_writer_read_skill_calls,
        all_read_skill_calls=all_read_skill_calls,
        skill_set=args.hypothesis_skill_set,
        skill_activation_mode=args.skill_activation_mode,
        hypothesis_writer_prompt_mode=args.hypothesis_writer_prompt_mode,
        model=os.getenv("LLM_MODEL") or os.getenv("OLLAMA_MODEL") or "",
        ollama_base_url=ollama_base_url,
        data_dir=data_dir,
        trace_log_path=trace_log_path,
        artifact_gate_event=save_hypothesis_report_event,
    )

    # ── Hypothesis quality gate — mirror super-graph routing before
    # deterministic report finalization. The traced script streams the inner
    # agent directly, so it must call this node explicitly to exercise the
    # same validation + narrow retry path as the production super-graph.
    print("\n[HYPOTHESIS-QUALITY] Validating hypothesis_report.json before finalize_report...")
    quality_start = time.time()
    try:
        from src.agents.drug_target.super_graph import validate_and_maybe_retry_hypothesis

        skip_quality_after_budget_abort = _should_skip_hypothesis_quality_after_budget_abort(
            hypothesis_budget_aborted=hypothesis_budget_aborted,
            hypothesis_path=hypothesis_path,
            run_started_at=start,
        )
        remaining_quality_timeout = (
            0
            if skip_quality_after_budget_abort
            else _remaining_timeout_seconds(start, timeout_seconds)
        )
        if remaining_quality_timeout <= 0:
            timeout_message = (
                "hypothesis_writer budget exceeded before a fresh "
                "hypothesis_report.json was saved."
                if skip_quality_after_budget_abort
                else "CLI timeout reached before hypothesis quality gate could run."
            )
            _record_hypothesis_quality_timeout(
                captured_finalization_state,
                timeout_message,
                attempted=False,
            )
            print(f"  [HYPOTHESIS-QUALITY] TIMEOUT — {timeout_message}")
            with open(trace_log_path, "a", encoding="utf-8") as fp:
                fp.write(f"\n[HYPOTHESIS-QUALITY] TIMEOUT — {timeout_message}\n")
        else:
            quality_result = await asyncio.wait_for(
                validate_and_maybe_retry_hypothesis(
                    {
                        "messages": [],
                        "data_dir": str(data_dir),
                        "disease": args.disease,
                        "featured_lr_pairs": None,
                        "report_finalization_error": None,
                        "evidence_truncated": False,
                        "deep_agent_started_at": start,
                        "hypothesis_writer_skill_names": tuple(
                            hypothesis_writer_skill_names
                        ),
                        "hypothesis_writer_prompt_mode": (
                            args.hypothesis_writer_prompt_mode
                        ),
                        "skill_activation_mode": args.skill_activation_mode,
                        "enable_skill_activator": enable_skill_activator,
                    },
                    {
                        "recursion_limit": 10000,
                        "configurable": {
                            "thread_id": f"{thread_id}-hypothesis-quality",
                        },
                    },
                ),
                timeout=remaining_quality_timeout,
            )
            _capture_hypothesis_quality_state(
                quality_result,
                captured_finalization_state,
            )
            quality_elapsed = time.time() - quality_start
            quality_ok = captured_finalization_state["hypothesis_quality_valid"] is True
            quality_status = "PASS" if quality_ok else "FAIL"
            retry_status = captured_finalization_state.get("hypothesis_retry_status")
            error_summary = _format_hypothesis_quality_errors(
                captured_finalization_state.get("hypothesis_quality_errors")
            )
            print(
                f"  [HYPOTHESIS-QUALITY] {quality_elapsed:.1f}s — {quality_status}; "
                f"retry={retry_status}; errors={error_summary}"
            )
            with open(trace_log_path, "a", encoding="utf-8") as fp:
                fp.write(
                    f"\n[HYPOTHESIS-QUALITY] {quality_elapsed:.1f}s — {quality_status}; "
                    f"retry={retry_status}; errors={error_summary}\n"
                )
    except TimeoutError:
        quality_elapsed = time.time() - quality_start
        timeout_message = (
            "CLI timeout reached during hypothesis quality gate."
        )
        _record_hypothesis_quality_timeout(
            captured_finalization_state,
            timeout_message,
            attempted=True,
        )
        print(
            f"  [HYPOTHESIS-QUALITY] {quality_elapsed:.1f}s — TIMEOUT: "
            f"{timeout_message}"
        )
        with open(trace_log_path, "a", encoding="utf-8") as fp:
            fp.write(
                f"\n[HYPOTHESIS-QUALITY] TIMEOUT after {quality_elapsed:.1f}s: "
                f"{timeout_message}\n"
            )
    except Exception as exc:  # noqa: BLE001 — fail closed before finalization
        quality_elapsed = time.time() - quality_start
        captured_finalization_state["hypothesis_quality_valid"] = False
        captured_finalization_state["hypothesis_quality_errors"] = [
            {
                "code": "HYPOTHESIS_QUALITY_GATE_EXCEPTION",
                "message": f"{type(exc).__name__}: {exc}",
            }
        ]
        captured_finalization_state["hypothesis_retry_attempted"] = False
        captured_finalization_state["hypothesis_retry_status"] = "error"
        captured_finalization_state["hypothesis_retry_error"] = (
            f"{type(exc).__name__}: {exc}"
        )
        captured_finalization_state["report_finalization_error"] = (
            "HYPOTHESIS_QUALITY_GATE_EXCEPTION: "
            f"{type(exc).__name__}: {exc}"
        )
        print(
            f"  [HYPOTHESIS-QUALITY] {quality_elapsed:.1f}s — EXCEPTION: "
            f"{type(exc).__name__}: {exc}"
        )
        with open(trace_log_path, "a", encoding="utf-8") as fp:
            fp.write(
                f"\n[HYPOTHESIS-QUALITY] EXCEPTION ({type(exc).__name__}): {exc}\n"
            )

    # ── Fallback: write drug.md from captured stream state ────────
    drug_md_path = data_dir / "drug.md"
    if not drug_md_path.exists() and captured_drug_md_holder["content"]:
        content = captured_drug_md_holder["content"]
        drug_md_path.write_text(content)
        print(f"  [FALLBACK] Extracted drug.md from stream state ({len(content):,} chars)")
        with open(trace_log_path, "a") as fp:
            fp.write(f"\n[FALLBACK] drug.md extracted from Command(files=...) state update\n")

    # ── finalize_report node — the new super-graph node that follows the
    # inner DeepAgents runnable in the production super-graph. The trace
    # script invokes agent.astream() directly on the inner agent (bypassing
    # the super-graph for streaming visibility), so we must invoke
    # finalize_report manually here to reach the post-agent stage.
    if not _should_finalize_after_hypothesis_quality(captured_finalization_state):
        print(
            "\n[FINALIZE_REPORT] SKIPPED — hypothesis quality gate did not pass."
        )
        with open(trace_log_path, "a", encoding="utf-8") as fp:
            fp.write(
                "\n[FINALIZE_REPORT] skipped because hypothesis quality gate "
                "did not pass\n"
            )
    elif _should_invoke_finalize_report(data_dir, start):
        print("\n[FINALIZE_REPORT] Invoking super-graph finalize_report node...")
        finalize_report_invoked = True
        finalize_start = time.time()
        try:
            from src.agents.drug_target.finalize_report import finalize_report
            finalize_state = {
                "data_dir": str(data_dir),
                "disease": args.disease,
            }
            finalize_result = await finalize_report(
                finalize_state,
                _finalize_report_config(args),
            )
            finalize_elapsed = time.time() - finalize_start
            finalize_err = finalize_result.get("report_finalization_error")
            evidence_trunc_now = finalize_result.get("evidence_truncated", False)
            captured_finalization_state["report_finalization_error"] = finalize_err
            captured_finalization_state["evidence_truncated"] = evidence_trunc_now
            status = "OK" if finalize_err is None else f"ERROR: {finalize_err[:120]}"
            print(f"  [FINALIZE_REPORT] {finalize_elapsed:.1f}s — {status}")
            with open(trace_log_path, "a") as fp:
                fp.write(
                    f"\n[FINALIZE_REPORT] {finalize_elapsed:.1f}s — {status}\n"
                )
        except Exception as exc:  # noqa: BLE001 — fail-closed surfaces in summary
            finalize_elapsed = time.time() - finalize_start
            captured_finalization_state["report_finalization_error"] = (
                f"finalize_report_exception: {type(exc).__name__}: {exc}"
            )
            print(f"  [FINALIZE_REPORT] {finalize_elapsed:.1f}s — EXCEPTION: {exc}")
            with open(trace_log_path, "a") as fp:
                fp.write(
                    f"\n[FINALIZE_REPORT] EXCEPTION ({type(exc).__name__}): {exc}\n"
                )

    elapsed = time.time() - start

    # ── Output summary ────────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print(f"TRACE COMPLETE — {elapsed:.1f}s ({node_counter} node transitions)")
    print(f"{'=' * 70}\n")

    report_status = _inspect_report_outputs(data_dir, trace_log_path)
    evidence_count = report_status["evidence_count"]

    finalization_error = captured_finalization_state["report_finalization_error"]
    evidence_truncated = captured_finalization_state["evidence_truncated"]
    hypothesis_quality_valid = captured_finalization_state.get("hypothesis_quality_valid")
    hypothesis_retry_status = captured_finalization_state.get("hypothesis_retry_status")
    hypothesis_retry_attempted = captured_finalization_state.get(
        "hypothesis_retry_attempted"
    )
    hypothesis_retry_attempts = captured_finalization_state.get(
        "hypothesis_retry_attempts"
    )
    hypothesis_retry_error = captured_finalization_state.get("hypothesis_retry_error")
    hypothesis_quality_errors = captured_finalization_state.get(
        "hypothesis_quality_errors"
    )

    if finalization_error:
        report_status["missing_requirements"].append("REPORT_FINALIZATION_ERROR absent")
        report_status["finalized"] = False

    print(f"  Evidence files:      {evidence_count}")
    print(f"  assessment_results:  {'YES' if report_status['assessment_exists'] else 'NO'}")
    print(
        f"  target_assessment:   "
        f"{'YES' if report_status['target_assessment_exists'] else 'NO'}"
    )
    print(f"  drug.md:             {'YES' if report_status['drug_md_exists'] else 'NO'}")
    print(
        f"  drug_report.html:    "
        f"{'YES' if report_status['drug_html_exists'] else 'NO'}"
    )
    print(f"  EXPAND markers:      {report_status['expand_marker_count']}")
    print(
        f"  validate_drug_md:    "
        f"{'PASS' if report_status['validate_drug_md_passed'] else 'NO PASS'}"
    )
    print(
        f"  host_finalization:   "
        f"{'PASS' if report_status['report_finalization_valid'] else 'NO PASS'}"
    )
    print(
        f"  hypothesis_quality:  "
        f"{'PASS' if hypothesis_quality_valid is True else 'FAIL'}"
    )
    print(f"  hypothesis_retry:    {hypothesis_retry_status}")
    print(f"  hypothesis_retry_attempted: {hypothesis_retry_attempted}")
    print(f"  hypothesis_retry_attempts: {hypothesis_retry_attempts}")
    if hypothesis_retry_error:
        print(f"  hypothesis_retry_error: {hypothesis_retry_error}")
    print(
        f"  hypothesis_quality_errors: "
        f"{_format_hypothesis_quality_errors(hypothesis_quality_errors)}"
    )
    print(
        "  host_hypothesis_fallback_used: "
        f"{'YES' if host_hypothesis_fallback_used else 'NO'}"
    )
    print(f"  REPORT_FINALIZATION_ERROR: {finalization_error if finalization_error else '—'}")
    print(f"  EVIDENCE_TRUNCATED:  {evidence_truncated}")
    print(f"  report_finalized:    {'YES' if report_status['finalized'] else 'NO'}")
    if report_status["missing_requirements"]:
        print(
            "  missing_finalization: "
            + "; ".join(report_status["missing_requirements"])
        )
    activation_trace_path = resolve_activation_trace_path(
        args.activation_trace_json,
        data_dir=data_dir,
        timestamp=timestamp,
    )
    activation_trace_path = write_activation_trace_json(
        activation_trace_path=activation_trace_path,
        exposed_skill_names=hypothesis_writer_skill_names,
        hypothesis_writer_read_skill_calls=hypothesis_writer_read_skill_calls,
        all_read_skill_calls=all_read_skill_calls,
        skill_set=args.hypothesis_skill_set,
        skill_activation_mode=args.skill_activation_mode,
        hypothesis_writer_prompt_mode=args.hypothesis_writer_prompt_mode,
        model=os.getenv("LLM_MODEL") or os.getenv("OLLAMA_MODEL") or "",
        ollama_base_url=ollama_base_url,
        data_dir=data_dir,
        trace_log_path=trace_log_path,
        report_finalized=report_status["finalized"],
        artifact_gate_event=save_hypothesis_report_event,
    )
    activation_trace = json.loads(activation_trace_path.read_text(encoding="utf-8"))
    print(f"  Activation trace:    {activation_trace_path}")
    print(
        "  activated_skills:    "
        + ", ".join(activation_trace["activated_skill_names"])
    )
    print(f"  Trace log:           {trace_log_path}")
    print(f"  Workspace:           {data_dir}")
    print(f"  Runtime:             {elapsed:.1f}s")

    # Write summary to trace log
    with open(trace_log_path, "a") as fp:
        fp.write(f"\n{'=' * 62}\n")
        fp.write(f"TRACE COMPLETE — {elapsed:.1f}s ({node_counter} node transitions)\n")
        fp.write(f"{'=' * 62}\n")
        fp.write(f"  Evidence files:      {evidence_count}\n")
        fp.write(
            f"  assessment_results:  "
            f"{'YES' if report_status['assessment_exists'] else 'NO'}\n"
        )
        fp.write(
            f"  target_assessment:   "
            f"{'YES' if report_status['target_assessment_exists'] else 'NO'}\n"
        )
        fp.write(f"  drug.md:             {'YES' if report_status['drug_md_exists'] else 'NO'}\n")
        fp.write(
            f"  drug_report.html:    "
            f"{'YES' if report_status['drug_html_exists'] else 'NO'}\n"
        )
        fp.write(f"  EXPAND markers:      {report_status['expand_marker_count']}\n")
        fp.write(
            f"  validate_drug_md:    "
            f"{'PASS' if report_status['validate_drug_md_passed'] else 'NO PASS'}\n"
        )
        fp.write(
            f"  host_finalization:   "
            f"{'PASS' if report_status['report_finalization_valid'] else 'NO PASS'}\n"
        )
        fp.write(
            f"  hypothesis_quality:  "
            f"{'PASS' if hypothesis_quality_valid is True else 'FAIL'}\n"
        )
        fp.write(f"  hypothesis_retry:    {hypothesis_retry_status}\n")
        fp.write(f"  hypothesis_retry_attempted: {hypothesis_retry_attempted}\n")
        fp.write(f"  hypothesis_retry_attempts: {hypothesis_retry_attempts}\n")
        if hypothesis_retry_error:
            fp.write(f"  hypothesis_retry_error: {hypothesis_retry_error}\n")
        fp.write(
            "  hypothesis_quality_errors: "
            + _format_hypothesis_quality_errors(hypothesis_quality_errors)
            + "\n"
        )
        fp.write(
            "  host_hypothesis_fallback_used: "
            f"{'YES' if host_hypothesis_fallback_used else 'NO'}\n"
        )
        fp.write(
            f"  REPORT_FINALIZATION_ERROR: "
            f"{finalization_error if finalization_error else '—'}\n"
        )
        fp.write(f"  EVIDENCE_TRUNCATED:  {evidence_truncated}\n")
        fp.write(f"  report_finalized:    {'YES' if report_status['finalized'] else 'NO'}\n")
        if report_status["missing_requirements"]:
            fp.write(
                "  missing_finalization: "
                + "; ".join(report_status["missing_requirements"])
                + "\n"
            )
        fp.write(f"  Runtime:             {elapsed:.1f}s\n")

    if report_status["drug_md_exists"]:
        content = (data_dir / "drug.md").read_text()
        print(f"\n  drug.md: {len(content):,} chars")

    # ── Idempotency SOP: hint when finalize_report was skipped ───────────
    if _should_print_finalize_skip_note(
        report_status,
        pre_run_drug_md_exists=pre_run_drug_md_exists,
        finalize_report_invoked=finalize_report_invoked,
    ):
        print(
            "\nNOTE: finalize_report may have been skipped because drug.md already"
            " existed in the data_dir before this run.",
            file=sys.stderr,
        )
        print(
            "To force re-run, delete the four artifacts first:\n"
            f"  rm -f {data_dir}/drug.md {data_dir}/drug_report.html"
            f" {data_dir}/target_assessment.json {data_dir}/report_expansions.json",
            file=sys.stderr,
        )

    # ── Token usage report ────────────────────────────────────────────
    token_tracker.print_summary()
    token_tracker.save_report(token_usage_path)
    print(f"  Token usage report: {token_usage_path}")

    # ── CI smoke fail on evidence truncation (Decision 10 / CP-P0-011) ──
    if evidence_truncated:
        print(
            "\n[CI FAIL] evidence_truncated=True — finalize_report aborted due to"
            " evidence budget exceeded. Delete stale artifacts and re-run after"
            " evidence cap is resolved.",
            file=sys.stderr,
        )
        return 2

    success = report_status["finalized"]
    print(f"\n  {'SUCCESS' if success else 'PARTIAL'}")
    return 0 if success else 1


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    args = parse_args()
    sys.exit(asyncio.run(run_traced(args)))
