#!/usr/bin/env python3
"""Run only hypothesis_writer and summarizer on cached DrugTarget evidence.

This runner is for reruns where evidence_assessor has already produced the
expensive Stage 2, Stage 1, and Stage 3 artifacts under ``data_dir/evidence``.
It never exposes Stage 1/2 evidence tools to the agent, so the costly API
collection phase cannot be accidentally repeated.

Example:
    python scripts/run_drug_target_hypothesis_summarizer_only.py \\
        --data-dir res_ipf_openai/ \\
        --disease "idiopathic pulmonary fibrosis" \\
        --no-debug --census --provider openai --phase both

Run only hypothesis_writer:
    python scripts/run_drug_target_hypothesis_summarizer_only.py \\
        --data-dir res_ipf_openai/ \\
        --disease "idiopathic pulmonary fibrosis" \\
        --provider openai --phase hypothesis

Run only summarizer on an existing hypothesis_report.json:
    python scripts/run_drug_target_hypothesis_summarizer_only.py \\
        --data-dir res_ipf_openai/ \\
        --disease "idiopathic pulmonary fibrosis" \\
        --provider openai --phase summarizer

Ollama on a custom port:
    python scripts/run_drug_target_hypothesis_summarizer_only.py \\
        --data-dir res_ipf_openai/ \\
        --disease "idiopathic pulmonary fibrosis" \\
        --provider ollama --port 6000 --phase summarizer

Dry run:
    python scripts/run_drug_target_hypothesis_summarizer_only.py \\
        --data-dir res_ipf_openai/ \\
        --disease "idiopathic pulmonary fibrosis" \\
        --provider openai --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv


load_dotenv(PROJECT_ROOT / ".env", override=False)


_DEFAULT_PROVIDER = os.environ.get("LLM_PROVIDER", "openai")
_DEFAULT_MODEL = os.environ.get("LLM_MODEL")
_DIRECT_SUBAGENTS = ("HYPOTHESIS_WRITER", "SUMMARIZER", "REPORT_WRITER", "CRITIC")
_OLLAMA_PORT_PROVIDERS = {"ollama", "ollama-openai"}


def _parse_port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Run hypothesis_writer + summarizer only, using existing cached "
            "Stage 1/2/3 evidence under data_dir/evidence."
        )
    )
    p.add_argument("--data-dir", required=True, help="Existing DrugTarget run directory.")
    p.add_argument("--disease", required=True, help="Disease context string.")
    p.add_argument(
        "--provider",
        default=_DEFAULT_PROVIDER,
        help=f"LLM provider. Default: {_DEFAULT_PROVIDER}",
    )
    p.add_argument(
        "--model",
        default=_DEFAULT_MODEL,
        help="Optional model override. Defaults to LLM_MODEL/provider default.",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Timeout per phase in minutes. Default: 120.",
    )
    p.add_argument(
        "--port",
        type=_parse_port,
        default=None,
        help=(
            "Override local Ollama port for this run. Valid only with "
            "--provider ollama or --provider ollama-openai."
        ),
    )
    p.add_argument(
        "--phase",
        choices=["both", "hypothesis", "summarizer"],
        default="both",
        help=(
            "Which phase to run: both, hypothesis, or summarizer. "
            "Default: both."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate cached inputs and print config without invoking the LLM.",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="Enable LangChain debug logging.",
    )
    p.add_argument(
        "--no-debug",
        action="store_true",
        help="Compatibility flag for run_drug_target_traced.py; debug is off by default.",
    )
    p.add_argument(
        "--census",
        action="store_true",
        help="Compatibility no-op. This runner never calls Census or Stage 1/2 tools.",
    )
    p.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Python logging level. Default: INFO.",
    )
    args = p.parse_args(argv)
    if args.port is not None and args.provider.lower() not in _OLLAMA_PORT_PROVIDERS:
        p.error("--port can only be used with --provider ollama or ollama-openai")
    return args


def configure_ollama_port_override(args: argparse.Namespace) -> str | None:
    """Apply a localhost Ollama port override for this process."""
    if args.port is None or args.provider.lower() not in _OLLAMA_PORT_PROVIDERS:
        return None

    base_url = f"http://localhost:{args.port}"
    os.environ["OLLAMA_BASE_URL"] = base_url
    os.environ["OLLAMA_HOST"] = base_url
    return base_url


def resolve_data_dir(data_dir: str) -> Path:
    path = Path(data_dir).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def validate_precomputed_inputs(data_dir: Path, phase: str = "both") -> list[str]:
    """Return missing cached artifacts required before rerunning writers."""
    missing: list[str] = []

    if not data_dir.exists():
        return [f"data_dir does not exist: {data_dir}"]
    if not data_dir.is_dir():
        return [f"data_dir is not a directory: {data_dir}"]

    evidence_dir = data_dir / "evidence"
    if not (data_dir / "lr_candidates.json").exists():
        missing.append("lr_candidates.json")
    if not evidence_dir.is_dir():
        missing.append("evidence/")
        return missing

    for rel in ("assessment_results.json", "stage2_evidence.json"):
        if not (evidence_dir / rel).exists():
            missing.append(f"evidence/{rel}")

    stage1_filter_json = evidence_dir / "stage1_filter_results.json"
    stage1_filter_csv = evidence_dir / "stage1_filter_results.csv"
    if not stage1_filter_json.exists() and not stage1_filter_csv.exists():
        missing.append(
            "evidence/stage1_filter_results.json or evidence/stage1_filter_results.csv"
        )

    if not any(evidence_dir.glob("stage1_*--*.json")):
        missing.append("at least one evidence/stage1_<LIGAND>--<RECEPTOR>.json")
    if not any(evidence_dir.glob("stage3_*.json")):
        missing.append("at least one evidence/stage3_<GENE>.json")
    if phase == "summarizer" and not (evidence_dir / "hypothesis_report.json").exists():
        missing.append("evidence/hypothesis_report.json")

    return missing


def _set_subagent_env(provider: str, model: str | None) -> None:
    for name in _DIRECT_SUBAGENTS:
        os.environ[f"SUBAGENT_{name}_PROVIDER"] = provider
        if model:
            os.environ[f"SUBAGENT_{name}_MODEL"] = model


def _data_dir_note(data_dir: Path, disease: str) -> str:
    return (
        "\n\n## Data Directory\n"
        f"The data directory for this session is: `{data_dir}`\n"
        "Pass this exact path as `data_dir` to every tool call.\n"
        f"- **Disease context**: `{disease}`\n"
        "- Stage 1, Stage 2, and Stage 3 evidence is already cached under "
        "`evidence/`; do not attempt evidence collection.\n"
    )


def _configured_subagent_spec(name: str, data_dir: Path, disease: str) -> dict[str, Any]:
    from src.agents.deep_interpreter.middleware.write_file_guard import (
        WriteFileArgGuardMiddleware,
    )
    from src.agents.drug_target.subagents.configs import SUBAGENT_CONFIGS
    from src.agents.drug_target.subagents.summarizer.middleware import (
        HypothesisRetryLoopMiddleware,
    )

    base = SUBAGENT_CONFIGS[name]
    spec = {**base, "tools": list(base["tools"])}
    spec["system_prompt"] = base["system_prompt"] + _data_dir_note(data_dir, disease)

    middleware = [WriteFileArgGuardMiddleware(), *list(base.get("middleware", []))]
    if name == "hypothesis_writer":
        middleware.append(HypothesisRetryLoopMiddleware())
    spec["middleware"] = middleware
    return spec


def _create_llm(provider: str, model: str | None):
    from src.agents.model import create_llm

    kwargs: dict[str, Any] = {}
    if model:
        kwargs["model"] = model
    return create_llm(provider=provider, **kwargs)


def _create_hypothesis_agent(llm: Any, data_dir: Path, disease: str):
    from deepagents import create_deep_agent
    from deepagents.backends import FilesystemBackend

    spec = _configured_subagent_spec("hypothesis_writer", data_dir, disease)
    agent = create_deep_agent(
        model=llm,
        tools=spec["tools"],
        system_prompt=spec["system_prompt"],
        subagents=[],
        backend=FilesystemBackend(root_dir=str(data_dir), virtual_mode=True),
        middleware=spec["middleware"],
    )
    return agent.with_config({"recursion_limit": 1200})


def _create_summarizer_agent(llm: Any, data_dir: Path, disease: str):
    from src.agents.drug_target.subagents.summarizer import (
        create_summarizer_agent,
        wrap_summarizer_with_critic_slices,
    )

    inner_subagents = [
        _configured_subagent_spec("report_writer", data_dir, disease),
        _configured_subagent_spec("critic", data_dir, disease),
    ]
    raw_agent = create_summarizer_agent(
        model=llm,
        inner_subagents=inner_subagents,
        data_dir=str(data_dir),
    )
    return wrap_summarizer_with_critic_slices(raw_agent, data_dir=str(data_dir))


def _file_state(path: Path) -> tuple[bool, int, int]:
    if not path.exists():
        return (False, 0, 0)
    stat = path.stat()
    return (True, stat.st_mtime_ns, stat.st_size)


def _file_changed(before: tuple[bool, int, int], path: Path) -> bool:
    after = _file_state(path)
    return after[0] and after != before


def _last_message_text(result: Any) -> str:
    if not isinstance(result, dict):
        return ""
    messages = result.get("messages")
    if not isinstance(messages, list) or not messages:
        return ""
    last = messages[-1]
    if hasattr(last, "content"):
        return str(last.content)
    if isinstance(last, dict):
        return str(last.get("content") or "")
    return str(last)


async def _await_phase(label: str, coro: Any, timeout_minutes: int) -> Any:
    print(f"\n[{label}] starting")
    t0 = time.time()
    try:
        result = await asyncio.wait_for(coro, timeout=timeout_minutes * 60)
    except asyncio.TimeoutError:
        print(f"[{label}] TIMEOUT after {timeout_minutes} minutes")
        raise
    elapsed = time.time() - t0
    print(f"[{label}] completed in {elapsed / 60:.1f} minutes")
    return result


async def _run_hypothesis(
    *,
    llm: Any,
    data_dir: Path,
    disease: str,
    timeout_minutes: int,
) -> bool:
    agent = _create_hypothesis_agent(llm, data_dir, disease)
    output_path = data_dir / "evidence" / "hypothesis_report.json"
    before = _file_state(output_path)
    message = (
        "Regenerate ONLY evidence/hypothesis_report.json from cached evidence.\n\n"
        f"Data directory: {data_dir}\n"
        f"Disease context: {disease}\n\n"
        "Rules:\n"
        "- Do not run evidence_assessor, Stage 1, Stage 2, Stage 3, Census, "
        "OpenTargets, GWAS, STRING, or ChEMBL collection.\n"
        "- Use load_evidence_files(data_dir=..., scope='hypothesis') to read "
        "the cached evidence.\n"
        "- Validate every evidence filename with validate_evidence_references.\n"
        "- Save exactly one canonical report with save_hypothesis_report.\n"
        "- Do not write drug.md or target_assessment.json.\n"
    )
    await _await_phase(
        "hypothesis_writer",
        agent.ainvoke(
            {"messages": [{"role": "user", "content": message}]},
            config={"configurable": {"thread_id": str(uuid.uuid4())}},
        ),
        timeout_minutes,
    )

    if not output_path.exists():
        print(f"[hypothesis_writer] FAILED: {output_path} was not created")
        return False
    if not _file_changed(before, output_path):
        print(f"[hypothesis_writer] FAILED: {output_path} was not regenerated")
        return False

    try:
        data = json.loads(output_path.read_text(encoding="utf-8"))
        count = len(data.get("hypotheses", [])) if isinstance(data, dict) else 0
    except Exception:
        count = 0
    print(f"[hypothesis_writer] wrote {output_path} ({count} hypotheses)")
    return True


async def _run_summarizer(
    *,
    llm: Any,
    data_dir: Path,
    disease: str,
    timeout_minutes: int,
) -> bool:
    agent = _create_summarizer_agent(llm, data_dir, disease)
    drug_md_path = data_dir / "drug.md"
    target_path = data_dir / "target_assessment.json"
    before_drug = _file_state(drug_md_path)
    before_target = _file_state(target_path)
    message = (
        "Finalize the drug target assessment report from cached evidence.\n\n"
        f"Data directory: {data_dir}\n"
        f"Disease context: {disease}\n\n"
        "The evidence directory already contains completed Stage 1, Stage 2, "
        "Stage 3, and hypothesis_report.json artifacts. Do not run evidence "
        "collection. Run the audited summarizer flow: report_writer, "
        "validate_drug_md, critic, bounded repair loop, and finalization.\n"
        f"The final drug.md must be saved to: {drug_md_path}\n"
    )
    result = await _await_phase(
        "summarizer",
        agent.ainvoke(
            {"messages": [{"role": "user", "content": message}]},
            config={"configurable": {"thread_id": str(uuid.uuid4())}},
        ),
        timeout_minutes,
    )
    final_status = _last_message_text(result)
    if final_status:
        print("[summarizer] final status:")
        print(final_status[:4000])

    ok = True
    expected_sidecars = [
        data_dir / "report_expansions.json",
        data_dir / "drug_report_render.json",
        data_dir / "evidence" / "critic_report.json",
    ]
    for sidecar in expected_sidecars:
        if not sidecar.exists():
            print(f"[summarizer] FAILED: {sidecar} was not created")
            ok = False
    if not drug_md_path.exists():
        print(f"[summarizer] FAILED: {drug_md_path} was not created")
        ok = False
    elif not _file_changed(before_drug, drug_md_path):
        print(f"[summarizer] FAILED: {drug_md_path} was not regenerated")
        ok = False
    if not target_path.exists():
        print(f"[summarizer] FAILED: {target_path} was not created")
        ok = False
    elif not _file_changed(before_target, target_path):
        print(f"[summarizer] FAILED: {target_path} was not regenerated")
        ok = False
    if not ok:
        return False

    print(f"[summarizer] wrote {drug_md_path}")
    print(f"[summarizer] wrote {target_path}")
    return True


def _validate_final_report(data_dir: Path) -> bool:
    from src.agents.drug_target.tools.stage_logic import validate_drug_report_finalization

    impl = getattr(validate_drug_report_finalization, "func", None) or validate_drug_report_finalization
    raw = impl(str(data_dir), require_critic=True)
    try:
        result = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        print("[finalization] FAILED: validator returned non-JSON output")
        print(raw)
        return False

    valid = bool(result.get("valid"))
    issue_count = result.get("issue_count", "unknown")
    print(f"[finalization] valid={valid} issue_count={issue_count}")
    if not valid:
        for issue in (result.get("issues") or [])[:8]:
            code = issue.get("code") or issue.get("type") or "UNKNOWN"
            message = issue.get("message") or issue.get("detail") or ""
            print(f"  - {code}: {message}")
    return valid


async def run(args: argparse.Namespace) -> int:
    numeric_level = getattr(logging, args.log_level, logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    if args.debug and not args.no_debug:
        from langchain_core.globals import set_debug

        set_debug(True)

    data_dir = resolve_data_dir(args.data_dir)
    ollama_base_url = configure_ollama_port_override(args)
    missing = validate_precomputed_inputs(data_dir, phase=args.phase)

    print("=" * 70)
    print("Hypothesis + Summarizer Only Runner")
    print("=" * 70)
    print(f"  Provider: {args.provider}")
    print(f"  Model:    {args.model or '(provider default)'}")
    print(f"  Data dir: {data_dir}")
    print(f"  Disease:  {args.disease}")
    print(f"  Phase:    {args.phase}")
    if ollama_base_url:
        print(f"  Ollama:   {ollama_base_url}")
    print(f"  Census:   ignored (cached evidence only)")
    print(f"  Dry-run:  {args.dry_run}")

    if missing:
        print("\nMissing required cached inputs:")
        for item in missing:
            print(f"  - {item}")
        return 1

    print("\nCached Stage 1/2/3 evidence looks ready.")
    if args.dry_run:
        print("DRY-RUN: no LLM calls made.")
        return 0

    _set_subagent_env(args.provider, args.model)
    llm = _create_llm(args.provider, args.model)

    if args.phase in ("both", "hypothesis"):
        hypothesis_ok = await _run_hypothesis(
            llm=llm,
            data_dir=data_dir,
            disease=args.disease,
            timeout_minutes=args.timeout,
        )
        if not hypothesis_ok:
            return 1

    if args.phase in ("both", "summarizer"):
        summarizer_ok = await _run_summarizer(
            llm=llm,
            data_dir=data_dir,
            disease=args.disease,
            timeout_minutes=args.timeout,
        )
        if not summarizer_ok:
            return 1
        return 0 if _validate_final_report(data_dir) else 1

    return 0


def main() -> None:
    args = parse_args()
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
