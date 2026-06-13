"""Run phase-aware hypothesis_writer skill activation benchmark."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path, PurePosixPath
from typing import Any, Sequence

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from docs.benchmarks.hypothesis_generation_consistency.phase_activation import (
    EXPANDED6_SKILL_NAMES,
    PHASE_ACTIVATION_CASES,
    aggregate_phase_activation,
    build_phase_trial_plan,
    render_phase_activation_summary,
    score_phase_activation,
)
from docs.benchmarks.hypothesis_generation_consistency.run_activation_matrix import (
    unload_model_from_ports,
)
from docs.benchmarks.hypothesis_generation_consistency.run_benchmark import write_json
from src.agents.drug_target.tools.skill_reader import read_skill_file
from src.agents.model import create_llm
from src.agents.shared.skill_activator import SkillActivator
from src.agents.shared.skills_middleware import SkillsMiddleware

DEFAULT_MODELS = ("qwen3.5:35b", "qwen3.5:122b")
DEFAULT_PORTS = (5000, 6000, 7000)
DEFAULT_CONDITIONS = ("passive_listing", "skill_activator")
DEFAULT_MAX_ROUND_TRIPS = len(EXPANDED6_SKILL_NAMES) + 1

PHASE_AWARE_BASE_PROMPT = """\
You are the hypothesis_writer subagent for the Drug Target Assessment Agent.

Your production role is to turn loaded evidence into evidence/hypothesis_report.json.
For this benchmark, do not write files and do not call external database tools.

Use read_skill_file when a skill guide is directly needed to interpret the
current hypothesis-writing task. Database skills may be read as interpretation
guides for already-loaded evidence; reading them does not authorize new
database queries. If no skill guide is needed, say so briefly.

If you decide a skill guide is needed, call read_skill_file now. Do not describe
future skill reads. A skill counts as activated only if read_skill_file was
actually called during this interaction.

After any needed skill reads, answer with:
1. ACTIVATED_SKILLS: a comma-separated list of skill names you read, or NONE
2. RATIONALE: one concise sentence explaining why those skills match the task
3. DRAFT_ACTION: one concise sentence describing how you would draft the section

Do not fabricate evidence. Treat all evidence mentioned by the user as already
loaded from files.
"""

CASE_BY_ID = {case.case_id: case for case in PHASE_ACTIVATION_CASES}


def build_skill_registry() -> dict[str, str]:
    return {
        name: str(PROJECT_ROOT / "skills" / name)
        for name in EXPANDED6_SKILL_NAMES
    }


class _MockRequest:
    def __init__(self, content: str):
        self.system_message = SystemMessage(content=content)
        self.system_prompt = None

    def override(self, **kwargs: Any) -> "_MockRequest":
        new = _MockRequest(str(self.system_message.content))
        for key, value in kwargs.items():
            setattr(new, key, value)
        return new


async def _apply_middleware(system_prompt: str, middleware: Any) -> str:
    await middleware.abefore_agent(state=None, runtime=None)
    captured = system_prompt

    async def _handler(req: Any) -> None:
        nonlocal captured
        captured = str(req.system_message.content)
        return None

    await middleware.awrap_model_call(_MockRequest(system_prompt), _handler)
    return captured


async def render_system_prompt(condition: str) -> str:
    registry = build_skill_registry()
    passive = SkillsMiddleware(
        skills_dir=PROJECT_ROOT / "skills",
        allowed_skill_names=EXPANDED6_SKILL_NAMES,
    )
    system_prompt = await _apply_middleware(PHASE_AWARE_BASE_PROMPT, passive)
    if condition == "passive_listing":
        return system_prompt
    if condition == "skill_activator":
        activator = SkillActivator(skill_registry=registry)
        return await _apply_middleware(system_prompt, activator)
    raise ValueError(f"unknown condition: {condition}")


def create_phase_trial_llm(model: str, port: int) -> Any:
    return create_llm(
        provider="ollama",
        model=model,
        base_url=f"http://127.0.0.1:{port}",
        reasoning=False,
    )


def _coerce_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return str(content)


def _skill_name_from_path(skill_path: str) -> str | None:
    parts = PurePosixPath(skill_path).parts
    for index, part in enumerate(parts[:-1]):
        if part == "skills" and index + 1 < len(parts):
            return parts[index + 1]
    return None


def coerce_tool_args(raw_args: Any) -> dict[str, Any]:
    if isinstance(raw_args, dict):
        return raw_args
    try:
        decoded = json.loads(raw_args)
    except Exception:
        return {"skill_path": str(raw_args)}
    if isinstance(decoded, dict):
        return decoded
    return {"skill_path": str(decoded)}


def extract_skills_from_tool_history(
    tool_history: Sequence[dict[str, Any]],
) -> list[str]:
    registry = set(EXPANDED6_SKILL_NAMES)
    names: set[str] = set()
    for entry in tool_history:
        if entry.get("name") != read_skill_file.name:
            continue
        raw_args = entry.get("args")
        args = raw_args if isinstance(raw_args, dict) else {}
        skill_name = _skill_name_from_path(str(args.get("skill_path", "")))
        if skill_name in registry:
            names.add(skill_name)
    return sorted(names)


async def run_tool_loop(
    llm: Any,
    *,
    system_prompt: str,
    user_prompt: str,
    max_round_trips: int = DEFAULT_MAX_ROUND_TRIPS,
) -> dict[str, Any]:
    llm_with_tools = llm.bind_tools([read_skill_file])
    messages: list[Any] = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]
    tool_history: list[dict[str, Any]] = []
    final_message: AIMessage | None = None

    for _ in range(max_round_trips):
        response = await llm_with_tools.ainvoke(messages)
        if not isinstance(response, AIMessage):
            response = AIMessage(
                content=_coerce_text(getattr(response, "content", response))
            )
        final_message = response
        messages.append(response)
        if not response.tool_calls:
            break

        for tool_call in response.tool_calls:
            tool_call_id = tool_call.get("id") or f"tool-call-{len(tool_history)}"
            tool_name = tool_call.get("name")
            tool_args = coerce_tool_args(tool_call.get("args", {}))

            if tool_name != read_skill_file.name:
                result = f"Unsupported tool: {tool_name}"
            else:
                result = await asyncio.to_thread(read_skill_file.invoke, tool_args)

            tool_history.append(
                {
                    "name": tool_name,
                    "args": tool_args,
                    "content_preview": str(result)[:240],
                }
            )
            messages.append(ToolMessage(content=str(result), tool_call_id=tool_call_id))

    if final_message is None:
        raise RuntimeError("model produced no response")

    return {
        "final_text": _coerce_text(final_message.content),
        "tool_history": tool_history,
        "tool_budget_exhausted": bool(final_message.tool_calls),
    }


async def run_one_phase_trial(
    trial: dict[str, Any],
    output_root: Path,
) -> dict[str, Any]:
    case = CASE_BY_ID[str(trial["case_id"])]
    output_root.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    error: str | None = None
    final_text = ""
    tool_history: list[dict[str, Any]] = []
    activated_skill_names: list[str] = []

    try:
        llm = create_phase_trial_llm(
            model=str(trial["model"]),
            port=int(trial["port"]),
        )
        system_prompt = await render_system_prompt(str(trial["condition"]))
        loop_result = await run_tool_loop(
            llm,
            system_prompt=system_prompt,
            user_prompt=case.prompt,
        )
        final_text = str(loop_result["final_text"])
        tool_history = list(loop_result["tool_history"])
        activated_skill_names = extract_skills_from_tool_history(tool_history)
        if loop_result.get("tool_budget_exhausted"):
            error = "tool_call_budget_exhausted"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    score = score_phase_activation(
        expected_domain_skills=case.expected_domain_skills,
        activated_skill_names=activated_skill_names,
    )
    row = {
        **trial,
        "expected_domain_skills": list(case.expected_domain_skills),
        "expect_core_skill": case.expect_core_skill,
        "activated_skill_names": activated_skill_names,
        "tool_history": tool_history,
        "final_text": final_text,
        "elapsed_s": round(time.monotonic() - started, 3),
        "error": error,
        **score,
    }
    (output_root / f"{trial['run_id']}.json").write_text(
        json.dumps(row, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return row


def _split_csv(raw: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run phase-aware skill activation appropriateness benchmark."
    )
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS))
    parser.add_argument("--ports", default=",".join(str(port) for port in DEFAULT_PORTS))
    parser.add_argument("--conditions", default=",".join(DEFAULT_CONDITIONS))
    parser.add_argument("--case-ids", default="")
    parser.add_argument(
        "--parallel-ports",
        action="store_true",
        help=(
            "Run ports concurrently within each model while keeping models "
            "sequential and unloading before model switches."
        ),
    )
    parser.add_argument("--output-root", default="")
    return parser.parse_args(argv)


def prepare_output_root(output_root: Path) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    for filename in ("trials.jsonl", "benchmark_results.json", "benchmark_summary.md"):
        path = output_root / filename
        if path.exists():
            path.unlink()


def group_trials_by_model(
    trials: Sequence[dict[str, Any]],
) -> list[tuple[str, list[dict[str, Any]]]]:
    groups: list[tuple[str, list[dict[str, Any]]]] = []
    by_model: dict[str, list[dict[str, Any]]] = {}
    for trial in trials:
        model = str(trial["model"])
        if model not in by_model:
            by_model[model] = []
            groups.append((model, by_model[model]))
        by_model[model].append(trial)
    return groups


def partition_trials_by_port(
    trials: Sequence[dict[str, Any]],
) -> list[tuple[int, list[dict[str, Any]]]]:
    groups: list[tuple[int, list[dict[str, Any]]]] = []
    by_port: dict[int, list[dict[str, Any]]] = {}
    for trial in trials:
        port = int(trial["port"])
        if port not in by_port:
            by_port[port] = []
            groups.append((port, by_port[port]))
        by_port[port].append(trial)
    return groups


async def run_port_trial_sequence(
    trials: Sequence[dict[str, Any]],
    output_root: Path,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for trial in trials:
        rows.append(await run_one_phase_trial(trial, output_root))
    return rows


async def run_model_trials_parallel_by_port(
    trials: Sequence[dict[str, Any]],
    output_root: Path,
) -> list[dict[str, Any]]:
    partitions = partition_trials_by_port(trials)
    batches = await asyncio.gather(
        *[
            run_port_trial_sequence(port_trials, output_root)
            for _port, port_trials in partitions
        ]
    )
    rows_by_run_id = {
        row["run_id"]: row
        for batch in batches
        for row in batch
    }
    return [rows_by_run_id[trial["run_id"]] for trial in trials]


def append_trial_rows(output_root: Path, rows: Sequence[dict[str, Any]]) -> None:
    with (output_root / "trials.jsonl").open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


async def run_matrix(args: argparse.Namespace) -> Path:
    stamp = time.strftime("phase_activation_%Y%m%d_%H%M%S")
    output_root = (
        Path(args.output_root).expanduser().resolve()
        if args.output_root
        else PROJECT_ROOT
        / "docs/benchmarks/hypothesis_generation_consistency/results"
        / stamp
    )
    prepare_output_root(output_root)

    models = _split_csv(args.models)
    ports = tuple(int(port) for port in _split_csv(args.ports))
    conditions = _split_csv(args.conditions)
    case_ids = _split_csv(args.case_ids) if args.case_ids else None
    trials = build_phase_trial_plan(
        models=models,
        ports=ports,
        conditions=conditions,
        case_ids=case_ids,
    )

    rows: list[dict[str, Any]] = []
    unload_events: list[dict[str, Any]] = []
    active_model: str | None = None

    try:
        for model, model_trials in group_trials_by_model(trials):
            if active_model and active_model != model:
                unload_events.extend(unload_model_from_ports(active_model, ports))
            active_model = model
            if args.parallel_ports:
                model_rows = await run_model_trials_parallel_by_port(
                    model_trials,
                    output_root,
                )
            else:
                model_rows = []
                for trial in model_trials:
                    model_rows.append(await run_one_phase_trial(trial, output_root))
            rows.extend(model_rows)
            append_trial_rows(output_root, model_rows)
    finally:
        if active_model:
            unload_events.extend(unload_model_from_ports(active_model, ports))

    aggregate = aggregate_phase_activation(rows)
    write_json(
        output_root / "benchmark_results.json",
        {
            "models": list(models),
            "ports": list(ports),
            "conditions": list(conditions),
            "case_ids": (
                list(case_ids)
                if case_ids
                else [case.case_id for case in PHASE_ACTIVATION_CASES]
            ),
            "trials": rows,
            "aggregate": aggregate,
            "unload_events": unload_events,
        },
    )
    (output_root / "benchmark_summary.md").write_text(
        render_phase_activation_summary(rows, aggregate),
        encoding="utf-8",
    )
    return output_root


def main(argv: list[str] | None = None) -> int:
    output_root = asyncio.run(run_matrix(parse_args(argv)))
    print(f"wrote {output_root / 'benchmark_results.json'}")
    print(f"wrote {output_root / 'benchmark_summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
