"""Run fig3-style skill activation benchmark."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from docs.benchmarks.hypothesis_generation_consistency.fig3_activation import (
    CASE_BY_ID,
    DOMAIN_SKILL_UNIVERSE,
    FIG3_ACTIVATION_CASES,
    FIG3_STYLE_BASE_PROMPT,
    aggregate_fig3_activation,
    build_fig3_trial_plan,
    render_fig3_activation_summary,
    score_fig3_activation,
)
from docs.benchmarks.hypothesis_generation_consistency.run_activation_matrix import (
    unload_model_from_ports,
)
from docs.benchmarks.hypothesis_generation_consistency.run_benchmark import write_json
from docs.benchmarks.hypothesis_generation_consistency.run_phase_activation_benchmark import (
    _apply_middleware,
    _split_csv,
    append_trial_rows,
    create_phase_trial_llm,
    extract_skills_from_tool_history,
    group_trials_by_model,
    partition_trials_by_port,
    prepare_output_root,
    run_tool_loop,
)
from src.agents.shared.skill_activator import SkillActivator
from src.agents.shared.skills_middleware import SkillsMiddleware

DEFAULT_MODELS = ("qwen3.5:35b", "qwen3.5:122b")
DEFAULT_PORTS = (5000, 6000, 7000)
DEFAULT_CONDITIONS = ("passive_listing", "skill_activator")


def build_skill_registry() -> dict[str, str]:
    return {
        name: str(PROJECT_ROOT / "skills" / name)
        for name in DOMAIN_SKILL_UNIVERSE
    }


async def render_system_prompt(condition: str) -> str:
    registry = build_skill_registry()
    passive = SkillsMiddleware(
        skills_dir=PROJECT_ROOT / "skills",
        allowed_skill_names=DOMAIN_SKILL_UNIVERSE,
    )
    system_prompt = await _apply_middleware(FIG3_STYLE_BASE_PROMPT, passive)
    if condition == "passive_listing":
        return system_prompt
    if condition == "skill_activator":
        activator = SkillActivator(skill_registry=registry)
        return await _apply_middleware(system_prompt, activator)
    raise ValueError(f"unknown condition: {condition}")


async def run_one_fig3_trial(
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

    score = score_fig3_activation(
        expected_domain_skills=case.expected_domain_skills,
        activated_skill_names=activated_skill_names,
    )
    row = {
        **trial,
        "expected_domain_skills": list(case.expected_domain_skills),
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


async def run_port_trial_sequence(
    trials: Sequence[dict[str, Any]],
    output_root: Path,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for trial in trials:
        rows.append(await run_one_fig3_trial(trial, output_root))
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run fig3-style skill activation benchmark."
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


async def run_matrix(args: argparse.Namespace) -> Path:
    stamp = time.strftime("fig3_activation_%Y%m%d_%H%M%S")
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
    trials = build_fig3_trial_plan(
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
                    model_rows.append(await run_one_fig3_trial(trial, output_root))
            rows.extend(model_rows)
            append_trial_rows(output_root, model_rows)
    finally:
        if active_model:
            unload_events.extend(unload_model_from_ports(active_model, ports))

    aggregate = aggregate_fig3_activation(rows)
    write_json(
        output_root / "benchmark_results.json",
        {
            "benchmark": "fig3_style_activation",
            "models": list(models),
            "ports": list(ports),
            "conditions": list(conditions),
            "case_ids": (
                list(case_ids)
                if case_ids
                else [case.case_id for case in FIG3_ACTIVATION_CASES]
            ),
            "trials": rows,
            "aggregate": aggregate,
            "unload_events": unload_events,
        },
    )
    (output_root / "benchmark_summary.md").write_text(
        render_fig3_activation_summary(rows, aggregate),
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
