"""Run modality-aware hypothesis_writer skill activation benchmark."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage

from docs.benchmarks.hypothesis_generation_consistency.modality_activation import (
    CASE_BY_ID,
    EXPANDED6_SKILL_NAMES,
    MODALITY_ACTIVATION_CASES,
    MODALITY_AWARE_BASE_PROMPT,
    aggregate_modality_activation,
    build_modality_trial_plan,
    render_modality_activation_summary,
    score_modality_activation,
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
DEFAULT_CONDITIONS = (
    "passive_listing",
    "skill_activator",
    "skill_activation_governor",
)
DEFAULT_TRIAL_TIMEOUT_S = 300.0
GOVERNOR_SKILL_NAME = "skill-activation-governor"


def build_skill_registry() -> dict[str, str]:
    return {
        name: str(PROJECT_ROOT / "skills" / name)
        for name in EXPANDED6_SKILL_NAMES
    }


class SkillActivationGovernorPromptMiddleware:
    """Inject skill-activation-governor instructions for benchmark comparison."""

    def __init__(self, *, skill_registry: dict[str, str]) -> None:
        self.skill_registry = skill_registry
        self._prompt_template = self._load_prompt_template()

    async def abefore_agent(self, state: Any, runtime: Any) -> None:
        return None

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        existing = ""
        if request.system_message:
            existing = str(request.system_message.content)
        elif request.system_prompt:
            existing = request.system_prompt

        governor_prompt = "\n\n".join(
            [
                self._prompt_template,
                (
                    "## Benchmark Context\n\n"
                    "No `required_skill_names` are provided in this benchmark "
                    "condition. Use the governor's flexible discovery path only: "
                    "evaluate the available skills below, activate directly "
                    "relevant skills with `read_skill_file`, and do not invent a "
                    "deterministic required list."
                ),
                "## Available Skills for Flexible Discovery\n\n"
                + self._format_available_skills(),
            ]
        )
        enhanced = existing + "\n\n" + governor_prompt if existing else governor_prompt
        modified = request.override(system_message=SystemMessage(content=enhanced))
        return await handler(modified)

    @staticmethod
    def _load_prompt_template() -> str:
        skill_md = PROJECT_ROOT / "skills" / GOVERNOR_SKILL_NAME / "SKILL.md"
        content = skill_md.read_text(encoding="utf-8")
        match = re.match(r"^---\n.*?\n---\n(.*)", content, re.DOTALL)
        return match.group(1).strip() if match else content.strip()

    def _format_available_skills(self) -> str:
        lines: list[str] = []
        for name, path in self.skill_registry.items():
            skill_md = Path(path) / "SKILL.md"
            lines.append(
                f"- **{name}**: {self._load_skill_description(skill_md)}\n"
                f"  Path: `{skill_md}`"
            )
        return "\n".join(lines) if lines else "(No skills available)"

    @staticmethod
    def _load_skill_description(skill_md: Path) -> str:
        try:
            content = skill_md.read_text(encoding="utf-8")
            match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
            if match:
                import yaml

                meta = yaml.safe_load(match.group(1))
                if isinstance(meta, dict):
                    return str(meta.get("description") or "(no description)")
        except Exception:
            pass
        return "(no description)"


def build_middleware_for_condition(condition: str) -> list[Any]:
    registry = build_skill_registry()
    middleware: list[Any] = [
        SkillsMiddleware(
            skills_dir=PROJECT_ROOT / "skills",
            allowed_skill_names=EXPANDED6_SKILL_NAMES,
        )
    ]
    if condition == "passive_listing":
        return middleware
    if condition == "skill_activator":
        middleware.append(SkillActivator(skill_registry=registry))
        return middleware
    if condition == "skill_activation_governor":
        middleware.append(
            SkillActivationGovernorPromptMiddleware(skill_registry=registry)
        )
        return middleware
    raise ValueError(f"unknown condition: {condition}")


async def render_system_prompt(condition: str) -> str:
    system_prompt = MODALITY_AWARE_BASE_PROMPT
    for middleware in build_middleware_for_condition(condition):
        system_prompt = await _apply_middleware(system_prompt, middleware)
    return system_prompt



async def run_one_modality_trial(
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

    score = score_modality_activation(
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


def _format_timeout_s(timeout_s: float) -> str:
    return f"{timeout_s:g}"


def write_timeout_modality_row(
    trial: dict[str, Any],
    output_root: Path,
    *,
    timeout_s: float,
) -> dict[str, Any]:
    case = CASE_BY_ID[str(trial["case_id"])]
    score = score_modality_activation(
        expected_domain_skills=case.expected_domain_skills,
        activated_skill_names=(),
    )
    row = {
        **trial,
        "expected_domain_skills": list(case.expected_domain_skills),
        "activated_skill_names": [],
        "tool_history": [],
        "final_text": "",
        "elapsed_s": round(timeout_s, 3),
        "error": f"TimeoutError: trial exceeded {_format_timeout_s(timeout_s)}s",
        **score,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / f"{trial['run_id']}.json").write_text(
        json.dumps(row, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return row


async def run_one_modality_trial_with_timeout(
    trial: dict[str, Any],
    output_root: Path,
    *,
    trial_timeout_s: float,
) -> dict[str, Any]:
    if trial_timeout_s <= 0:
        return await run_one_modality_trial(trial, output_root)

    try:
        return await asyncio.wait_for(
            run_one_modality_trial(trial, output_root),
            timeout=trial_timeout_s,
        )
    except asyncio.TimeoutError:
        return write_timeout_modality_row(
            trial,
            output_root,
            timeout_s=trial_timeout_s,
        )


async def run_port_trial_sequence(
    trials: Sequence[dict[str, Any]],
    output_root: Path,
    *,
    trial_timeout_s: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for trial in trials:
        rows.append(
            await run_one_modality_trial_with_timeout(
                trial,
                output_root,
                trial_timeout_s=trial_timeout_s,
            )
        )
    return rows


async def run_model_trials_parallel_by_port(
    trials: Sequence[dict[str, Any]],
    output_root: Path,
    *,
    trial_timeout_s: float,
) -> list[dict[str, Any]]:
    partitions = partition_trials_by_port(trials)
    batches = await asyncio.gather(
        *[
            run_port_trial_sequence(
                port_trials,
                output_root,
                trial_timeout_s=trial_timeout_s,
            )
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
        description="Run modality-aware skill activation benchmark."
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
    parser.add_argument(
        "--trial-timeout-s",
        type=float,
        default=DEFAULT_TRIAL_TIMEOUT_S,
        help=(
            "Maximum seconds per trial before recording a timeout row. "
            "Use 0 to disable."
        ),
    )
    parser.add_argument("--output-root", default="")
    return parser.parse_args(argv)


async def run_matrix(args: argparse.Namespace) -> Path:
    stamp = time.strftime("modality_activation_%Y%m%d_%H%M%S")
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
    trials = build_modality_trial_plan(
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
                    trial_timeout_s=float(args.trial_timeout_s),
                )
            else:
                model_rows = []
                for trial in model_trials:
                    model_rows.append(
                        await run_one_modality_trial_with_timeout(
                            trial,
                            output_root,
                            trial_timeout_s=float(args.trial_timeout_s),
                        )
                    )
            rows.extend(model_rows)
            append_trial_rows(output_root, model_rows)
    finally:
        if active_model:
            unload_events.extend(unload_model_from_ports(active_model, ports))

    aggregate = aggregate_modality_activation(rows)
    write_json(
        output_root / "benchmark_results.json",
        {
            "benchmark": "modality_aware_activation",
            "models": list(models),
            "ports": list(ports),
            "conditions": list(conditions),
            "case_ids": (
                list(case_ids)
                if case_ids
                else [case.case_id for case in MODALITY_ACTIVATION_CASES]
            ),
            "trials": rows,
            "aggregate": aggregate,
            "unload_events": unload_events,
        },
    )
    (output_root / "benchmark_summary.md").write_text(
        render_modality_activation_summary(rows, aggregate),
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
