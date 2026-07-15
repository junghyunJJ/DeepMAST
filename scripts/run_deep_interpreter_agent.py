#!/usr/bin/env python3
"""Run src.agents.deep_interpreter.agent directly with LangGraph-like env setup.

Examples:
    uv run python scripts/run_deep_interpreter_agent.py --dry-run
    uv run python scripts/run_deep_interpreter_agent.py
    uv run python scripts/run_deep_interpreter_agent.py --subagent planner --data-dir /path/to/run
    uv run python scripts/run_deep_interpreter_agent.py --subagent searcher --data-dir /path/to/run
    uv run python scripts/run_deep_interpreter_agent.py --subagent interpreter --part 1 --data-dir /path/to/run
    uv run python scripts/run_deep_interpreter_agent.py --subagent reporter --data-dir /path/to/run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
ENV_FILE = REPO_ROOT / ".env"
MAX_PART3_INVOKE_ATTEMPTS = 3

from dotenv import load_dotenv

from src.agents.deep_interpreter.agent import (
    DeepInterpreterConfig,
    create_deep_interpreter_agent,
)


def _csv(value: str | None) -> list[str] | None:
    if not value:
        return None
    parts = [part.strip() for part in value.split(",")]
    return [part for part in parts if part] or None


def _jsonable_message(message: Any) -> dict[str, Any]:
    content = message.get("content") if isinstance(message, dict) else getattr(message, "content", "")
    return {
        "type": type(message).__name__,
        "content_preview": str(content)[:500],
        "tool_call_id": getattr(message, "tool_call_id", None),
    }


def _load_targets(args: argparse.Namespace, data_dir: Path) -> dict[str, Any]:
    if args.targets_json:
        with Path(args.targets_json).expanduser().open(encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("--targets-json must contain a JSON object")
        return data

    return {
        "interest_clusters": _csv(args.interest_clusters),
        "interest_celltypes": _csv(args.interest_celltypes),
        "sel_factor": args.sel_factor,
        "data_directory": str(data_dir),
    }


def _build_initial_message(data_dir: Path, targets: dict[str, Any]) -> str:
    return f"""Interpret the CCI analysis results in {data_dir}.

## PRE-SELECTED TARGET CONFIGURATION
The following targets have been pre-selected by the user (DO NOT ask for user input):

```json
{json.dumps(targets, indent=2, ensure_ascii=False)}
```

IMPORTANT: /targets.json is already pre-written by the wrapper/framework.
The planner should read /targets.json and proceed directly to strategic planning."""


def _seed_standalone_files(data_dir: Path, targets: dict[str, Any]) -> None:
    (data_dir / "data_path.txt").write_text(str(data_dir), encoding="utf-8")
    (data_dir / "targets.json").write_text(
        json.dumps(targets, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _expected_outputs(subagent: str | None, part: int | None) -> list[str]:
    if subagent == "planner":
        return ["data_path.txt", "targets.json", "interpretation_guide.md", "planner_papers.json"]
    if subagent == "searcher":
        return ["search_context.json", "papers_raw.json", "citation_candidates.json", "papers.json"]
    if subagent == "interpreter":
        return [f"part{part}_final.md"] if part else []
    if subagent == "reporter":
        return ["synthesis.md", "synthesis_validation.json", "synthesis_targets.json", "CCI_Analysis_Report.html"]
    return []


def _output_status(data_dir: Path, outputs: list[str]) -> dict[str, bool]:
    return {name: (data_dir / name).exists() for name in outputs}


def _missing_outputs(data_dir: Path, outputs: list[str]) -> list[str]:
    return [name for name in outputs if not (data_dir / name).exists()]


def _should_retry_part3_save(args: argparse.Namespace, missing_outputs: list[str]) -> bool:
    return args.subagent == "interpreter" and args.part == 3 and missing_outputs == ["part3_final.md"]


def _build_part3_save_retry_message(data_dir: Path) -> str:
    return f"""Retry Part 3 output creation for {data_dir}.

Do not copy or save the previous chat-only response.
Re-read /data_path.txt, /interpretation_guide.md, and /papers.json, then call load_analysis_data for the data directory.
Run Part 3 ligand-receptor interpretation only.
Use selected_genes and selected_lr_pairs from part4_candidate_selection.json.
Avoid therapeutic synthesis, druggability, drug ranking, and clinical prioritization.
Your final action MUST be write_file(file_path="/part3_final.md", content=<complete markdown Part 3 report>).
A chat response without that tool call is incomplete."""


def _build_subagent_message(subagent: str, data_dir: Path, targets: dict[str, Any], part: int | None) -> str:
    if subagent == "planner":
        return _build_initial_message(data_dir, targets)
    if subagent == "searcher":
        return f"""Run SEARCHER only for the CCI analysis in {data_dir}.

Read /data_path.txt and /interpretation_guide.md, then call load_analysis_data.
Write /search_context.json from load_analysis_data.search_context.
Call search_literature_dynamic with output_path="papers_raw.json", data_dir from /data_path.txt,
max_results=100, max_iterations=3, enable_lr_pair_queries=True, and coverage_weighted_sort=True.
Then call create_literature_handoff to create /citation_candidates.json and filtered /papers.json.
Do not pass lr_pairs to create_literature_handoff; let it auto-load lr_candidates.json from data_dir.
Do not run interpreter or reporter."""
    if subagent == "interpreter":
        if part not in {1, 2, 3}:
            raise ValueError("--subagent interpreter requires --part 1, 2, or 3")
        part_notes = {
            1: "Interpret Part 1 ONLY. Output /part1_final.md.",
            2: "Interpret Part 2 ONLY. Connect CCI findings to Part 1 where relevant. Output /part2_final.md.",
            3: (
                "Interpret Part 3 ONLY. This is not a generic PPI network summary. "
                "Interpret Part 3 ligand-receptor details only. Read "
                "part4_candidate_selection.json via load_analysis_data. Use selected_genes "
                "as the fixed gene-section list. Use selected_lr_pairs as the source of "
                "truth for 3-10 and 3-11 direct L-R evidence when present; fall back to "
                "selected_genes only if selected_lr_pairs is missing. Integrate each "
                "selected pair's spatial and quantitative L-R evidence into the relevant "
                "selected gene subsection. Connect L-R evidence back to both Part 1 "
                "spatial patterns and Part 2 NMF/pathway results. Do not read or summarize "
                "part4_therapeutic_synthesis.md; therapeutic synthesis, druggability, "
                "drug ranking, and clinical prioritization belong to Part 4. You MUST call "
                "write_file with file_path=\"/part3_final.md\" and complete markdown "
                "content. A chat response only is incomplete."
            ),
        }
        return f"""Run INTERPRETER for {data_dir}.

{part_notes[part]}
Read /data_path.txt, /interpretation_guide.md, and filtered /papers.json.
You MUST write the final markdown using the write_file tool at /part{part}_final.md.
Do not finish with only a chat response; if /part{part}_final.md does not exist, your task is incomplete.
Validate citations and do not run planner, searcher, or reporter."""
    if subagent == "reporter":
        return f"""Run REPORTER only for the CCI analysis in {data_dir}.

Read /part1_final.md, /part2_final.md, /part3_final.md, /part4_therapeutic_synthesis.md if present, and /drug.md if present.
Use existing /papers.json-backed RAG retrieval only; do not run new literature searches or create reporter-specific paper artifacts.
Call write_file("/synthesis.md", ...) with the complete integrated narrative as Markdown, not HTML.
Then call generate_html_report with parts={{"template_mode": "comprehensive", ...}},
output_path="CCI_Analysis_Report.html", and data_dir from /data_path.txt.
generate_html_report writes synthesis_validation.json and synthesis_targets.json automatically after running the synthesis guardrail.
Do not hand-author part1_html, part2_html, part3_html, summary_html, or therapeutic_html.
Do not run planner, searcher, or interpreter."""
    raise ValueError(f"Unknown subagent: {subagent}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    load_dotenv(ENV_FILE)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--provider",
        default=os.getenv("LLM_PROVIDER", "openai"),
        choices=[
            "openai",
            "google",
            "ollama",
            "ollama-openai",
            "vllm",
            "claude",
            "openrouter",
        ],
    )
    parser.add_argument(
        "--data-dir",
        default=os.getenv("DEEP_INTERPRETER_DATA_DIR", "/tmp/deep_interpreter_workspace"),
    )
    parser.add_argument("--targets-json", help="Optional JSON object matching wrapper targets_content.")
    parser.add_argument("--interest-clusters", help="Comma-separated fallback target clusters.")
    parser.add_argument("--interest-celltypes", help="Comma-separated fallback target cell types.")
    parser.add_argument("--sel-factor", help="Fallback selected NMF factor, e.g. Factor3.")
    parser.add_argument("--message", help="Override the wrapper-equivalent initial user message.")
    parser.add_argument(
        "--subagent",
        choices=["planner", "searcher", "interpreter", "reporter"],
        help="Run one Deep Interpreter subagent instead of the full orchestrator.",
    )
    parser.add_argument("--part", type=int, choices=[1, 2, 3], help="Interpreter part to run with --subagent interpreter.")
    parser.add_argument("--dry-run", action="store_true", help="Create the agent and print config without invoking LLM.")
    parser.add_argument(
        "--disable-summarization",
        action="store_true",
        help="Disable DeepAgents summarization middleware for long direct smoke tests.",
    )
    parser.add_argument("--traceback", action="store_true", help="Print full traceback on failure.")
    return parser.parse_args(argv)


async def run(args: argparse.Namespace) -> int:
    load_dotenv(ENV_FILE)

    data_dir = Path(args.data_dir).expanduser().resolve(strict=False)
    data_dir.mkdir(parents=True, exist_ok=True)
    targets = _load_targets(args, data_dir)
    os.environ["DEEP_INTERPRETER_DATA_DIR"] = str(data_dir)
    if args.subagent == "searcher":
        os.environ.setdefault("LITERATURE_DYNAMIC_SEARCH_TIMEOUT", "900")
    if args.subagent == "interpreter" and args.part is None:
        print(
            json.dumps(
                {
                    "event": "argument_error",
                    "message": "--subagent interpreter requires --part 1, 2, or 3",
                },
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2

    config = DeepInterpreterConfig(
        provider=args.provider,
        data_dir=str(data_dir),
        use_checkpointer=False,
    )
    if args.disable_summarization:
        from langchain.agents.middleware.types import AgentMiddleware
        import deepagents.graph as deepagents_graph

        # ponytail: test-only bypass for deepagents/langchain summarization API drift.
        setattr(
            deepagents_graph,
            "create_summarization_middleware",
            lambda *_args, **_kwargs: AgentMiddleware(),
        )

    if args.subagent:
        _seed_standalone_files(data_dir, targets)
        from src.agents.deep_interpreter.graph_builder import create_subagent_graph

        agent = create_subagent_graph(args.subagent, provider=args.provider)
        initial_message = args.message or _build_subagent_message(
            args.subagent,
            data_dir,
            targets,
            args.part,
        )
    else:
        agent = create_deep_interpreter_agent(config, preselected_targets=targets)
        initial_message = args.message or _build_initial_message(data_dir, targets)

    expected_outputs = _expected_outputs(args.subagent, args.part)

    setup = {
        "env_file": str(ENV_FILE),
        "provider": args.provider,
        "data_dir": str(data_dir),
        "targets": targets,
        "subagent": args.subagent,
        "part": args.part,
        "agent_type": type(agent).__name__,
        "dry_run": args.dry_run,
        "expected_outputs": expected_outputs,
    }

    if args.dry_run:
        print(json.dumps(setup, indent=2, sort_keys=True, ensure_ascii=False))
        return 0

    print(json.dumps({**setup, "event": "invoke_start"}, indent=2, sort_keys=True, ensure_ascii=False))
    try:
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": initial_message}]},
            config=None,
        )
    except Exception as exc:
        if args.traceback:
            traceback.print_exc()
        print(
            json.dumps(
                {
                    "event": "invoke_error",
                    "exception_type": type(exc).__name__,
                    "exception_repr": repr(exc),
                },
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1

    messages = result.get("messages", []) if isinstance(result, dict) else []
    outputs = _output_status(data_dir, expected_outputs)
    missing_outputs = _missing_outputs(data_dir, expected_outputs)
    recovery: dict[str, Any] = {}
    invoke_attempt_count = 1
    retry_history: list[dict[str, Any]] = []

    for retry_number in range(1, MAX_PART3_INVOKE_ATTEMPTS):
        if not _should_retry_part3_save(args, missing_outputs):
            break

        print(
            json.dumps(
                {
                    "event": "part3_save_retry_start",
                    "retry_number": retry_number,
                    "max_invoke_attempts": MAX_PART3_INVOKE_ATTEMPTS,
                    "missing_outputs": missing_outputs,
                },
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
        )
        invoke_attempt_count += 1
        attempt: dict[str, Any] = {"retry_number": retry_number}
        try:
            result = await agent.ainvoke(
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": _build_part3_save_retry_message(data_dir),
                        }
                    ]
                },
                config=None,
            )
            messages = result.get("messages", []) if isinstance(result, dict) else []
            outputs = _output_status(data_dir, expected_outputs)
            missing_outputs = _missing_outputs(data_dir, expected_outputs)
            attempt.update(
                {
                    "event": (
                        "part3_save_retry_complete"
                        if not missing_outputs
                        else "part3_save_retry_incomplete"
                    ),
                    "outputs": outputs,
                    "missing_outputs": missing_outputs,
                }
            )
        except Exception as exc:
            if args.traceback:
                traceback.print_exc()
            attempt.update(
                {
                    "event": "part3_save_retry_error",
                    "exception_type": type(exc).__name__,
                    "exception_repr": repr(exc),
                }
            )
        retry_history.append(attempt)

    if retry_history:
        recovery["part3_save_retry"] = {
            "retry_attempt_count": len(retry_history),
            "max_invoke_attempts": MAX_PART3_INVOKE_ATTEMPTS,
            "attempts": retry_history,
        }

    summary = {
        "event": "invoke_incomplete" if missing_outputs else "invoke_complete",
        "invoke_attempt_count": invoke_attempt_count,
        "message_count": len(messages),
        "last_message": _jsonable_message(messages[-1]) if messages else None,
        "result_keys": sorted(result.keys()) if isinstance(result, dict) else [],
        "outputs": outputs,
    }
    if recovery:
        summary["recovery"] = recovery
    if missing_outputs:
        summary["missing_outputs"] = missing_outputs
    print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False))
    return 1 if missing_outputs else 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(run(parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
