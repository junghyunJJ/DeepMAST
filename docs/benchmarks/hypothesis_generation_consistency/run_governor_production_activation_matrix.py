"""Run production hypothesis_writer Governor activation matrix."""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from docs.benchmarks.hypothesis_generation_consistency.run_activation_matrix import (
    DEFAULT_MODELS,
    DEFAULT_PORTS,
    DEFAULT_SOURCE,
    aggregate_activation,
    model_slug,
    render_summary,
    run_one_trial,
    unload_model_from_ports,
)
from docs.benchmarks.hypothesis_generation_consistency.run_benchmark import (
    HYPOTHESIS_WRITER_SKILL_SETS,
    check_hypothesis_scope_untraced,
    write_json,
)


DEFAULT_MODES = (
    "middleware_only",
    "middleware_plus_activator",
    "middleware_plus_governor",
)


def _split_csv(raw: str, *, field_name: str) -> tuple[str, ...]:
    values = tuple(item.strip() for item in raw.split(",") if item.strip())
    if not values:
        raise ValueError(f"{field_name} must contain at least one value")
    return values


def parse_csv_models(raw: str) -> tuple[str, ...]:
    return _split_csv(raw, field_name="--models")


def normalize_provider(raw: str) -> str:
    provider = raw.strip().lower()
    if not provider:
        raise ValueError("--provider must be non-empty")
    return provider


def parse_csv_ports(raw: str) -> tuple[int, ...]:
    values = _split_csv(raw, field_name="--ports")
    ports: list[int] = []
    for value in values:
        try:
            port = int(value)
        except ValueError as exc:
            raise ValueError(f"invalid port {value!r}") from exc
        if not 1 <= port <= 65535:
            raise ValueError(f"invalid port {value!r}; expected 1..65535")
        ports.append(port)
    return tuple(ports)


def unique_physical_ports(ports: Sequence[int]) -> tuple[int, ...]:
    seen: set[int] = set()
    unique: list[int] = []
    for port in ports:
        if int(port) in seen:
            continue
        seen.add(int(port))
        unique.append(int(port))
    return tuple(unique)


def build_port_worker_slots(ports: Sequence[int]) -> list[dict[str, Any]]:
    port_values = tuple(int(port) for port in ports)
    port_counts = {port: port_values.count(port) for port in port_values}
    seen_counts: dict[int, int] = {}
    workers: list[dict[str, Any]] = []
    for worker_index, physical_port in enumerate(port_values, start=1):
        slot = seen_counts.get(physical_port, 0) + 1
        seen_counts[physical_port] = slot
        duplicate = port_counts[physical_port] > 1
        workers.append(
            {
                "port": physical_port,
                "port_slot": slot,
                "worker_index": worker_index,
                "worker_id": (
                    f"{physical_port}_{slot}"
                    if duplicate
                    else str(physical_port)
                ),
                "duplicate_port": duplicate,
            }
        )
    return workers


def build_provider_worker_slots(
    provider: str,
    parallel_workers: int,
) -> list[dict[str, Any]]:
    if parallel_workers < 1:
        raise ValueError("parallel_workers must be >= 1")
    return [
        {
            "provider": provider,
            "worker_index": worker_index,
            "worker_id": f"{provider}-{worker_index}",
        }
        for worker_index in range(1, parallel_workers + 1)
    ]


def parse_csv_modes(raw: str) -> tuple[str, ...]:
    values = _split_csv(raw, field_name="--modes")
    known = set(DEFAULT_MODES)
    unknown = [value for value in values if value not in known]
    if unknown:
        expected = ", ".join(DEFAULT_MODES)
        raise ValueError(
            f"unknown mode(s): {', '.join(unknown)}; expected one of: {expected}"
        )
    return values


def build_trial_plan(
    *,
    models: Sequence[str],
    ports: Sequence[int],
    modes: Sequence[str],
    repeats_per_condition: int | None = None,
    provider: str = "ollama",
    parallel_workers: int = 1,
) -> list[dict[str, Any]]:
    provider_name = normalize_provider(provider)
    if parallel_workers < 1:
        raise ValueError("parallel_workers must be >= 1")
    if provider_name == "ollama":
        if not ports:
            raise ValueError("ports must contain at least one port")
        worker_count = len(ports)
        port_workers = build_port_worker_slots(ports)
    else:
        worker_count = parallel_workers
        provider_workers = build_provider_worker_slots(provider_name, worker_count)

    effective_repeats = (
        worker_count if repeats_per_condition is None else repeats_per_condition
    )
    if effective_repeats < 1:
        raise ValueError("repeats_per_condition must be >= 1")

    trials: list[dict[str, Any]] = []
    if provider_name == "ollama":
        has_duplicate_ports = any(worker["duplicate_port"] for worker in port_workers)
        for model in models:
            for mode in modes:
                for repeat_index in range(1, effective_repeats + 1):
                    worker = port_workers[(repeat_index - 1) % len(port_workers)]
                    port = int(worker["port"])
                    wave = (repeat_index - 1) // len(ports)
                    run_id = f"{model_slug(model)}_{mode}_rep{repeat_index:03d}_port{port}"
                    if has_duplicate_ports and worker["duplicate_port"]:
                        run_id += f"_slot{worker['port_slot']}"
                    trial = {
                        "model": model,
                        "port": port,
                        "mode": mode,
                        "repeat": repeat_index,
                        "wave": wave,
                        "run_id": run_id,
                    }
                    if has_duplicate_ports:
                        trial.update(
                            {
                                "port_slot": int(worker["port_slot"]),
                                "worker_index": int(worker["worker_index"]),
                                "worker_id": str(worker["worker_id"]),
                            }
                        )
                    trials.append(trial)
        return trials

    for model in models:
        for mode in modes:
            for repeat_index in range(1, effective_repeats + 1):
                worker = provider_workers[(repeat_index - 1) % len(provider_workers)]
                wave = (repeat_index - 1) // worker_count
                worker_index = int(worker["worker_index"])
                trials.append(
                    {
                        "provider": provider_name,
                        "model": model,
                        "mode": mode,
                        "repeat": repeat_index,
                        "wave": wave,
                        "worker_index": worker_index,
                        "worker_id": str(worker["worker_id"]),
                        "run_id": (
                            f"{model_slug(model)}_{mode}_rep{repeat_index:03d}_"
                            f"{provider_name}_slot{worker_index}"
                        ),
                    }
                )
    return trials


def batches_by_model_mode_and_wave(
    trials: Sequence[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    batches: list[list[dict[str, Any]]] = []
    seen: list[tuple[str, str, int]] = []
    for trial in trials:
        key = (
            str(trial["model"]),
            str(trial["mode"]),
            int(trial.get("wave", 0)),
        )
        if key not in seen:
            seen.append(key)
            batches.append(
                [
                    item
                    for item in trials
                    if (
                        str(item["model"]),
                        str(item["mode"]),
                        int(item.get("wave", 0)),
                    )
                    == key
                ]
            )
    return batches


def _hypothesis_scope_errors(scope: Any) -> list[str]:
    if isinstance(scope, dict):
        errors = scope.get("errors", [])
        return [str(error) for error in errors] if isinstance(errors, list) else []
    if isinstance(scope, list):
        return [str(error) for error in scope]
    return [str(scope)] if scope else []


def build_dry_run_payload(
    *,
    source: Path,
    trials: Sequence[dict[str, Any]],
    models: Sequence[str],
    ports: Sequence[int],
    modes: Sequence[str],
    repeats_per_condition: int,
    timeout_minutes: int,
    wait_for_completion: bool,
    hypothesis_skill_set: str,
    hypothesis_writer_prompt_mode: str,
    hypothesis_scope_errors: Sequence[str],
    host_hypothesis_fallback: str,
    provider: str = "ollama",
    parallel_workers: int | None = None,
) -> dict[str, Any]:
    provider_name = normalize_provider(provider)
    effective_parallel_workers = (
        len(ports) if parallel_workers is None and provider_name == "ollama"
        else 1 if parallel_workers is None
        else parallel_workers
    )
    per_condition: dict[str, int] = {}
    per_port: dict[str, int] = {}
    per_worker: dict[str, int] = {}
    for trial in trials:
        condition_key = f"{trial['model']}::{trial['mode']}"
        per_condition[condition_key] = per_condition.get(condition_key, 0) + 1
        port_key = None
        if "port" in trial:
            port_key = str(trial["port"])
            per_port[port_key] = per_port.get(port_key, 0) + 1
        worker_key = str(trial.get("worker_id", port_key or provider_name))
        per_worker[worker_key] = per_worker.get(worker_key, 0) + 1
    workers = (
        [
            {
                key: value
                for key, value in worker.items()
                if key != "duplicate_port"
            }
            for worker in build_port_worker_slots(ports)
        ]
        if provider_name == "ollama"
        else build_provider_worker_slots(provider_name, int(effective_parallel_workers))
    )
    return {
        "dry_run": True,
        "source": str(source),
        "trial_count": len(trials),
        "provider": provider_name,
        "models": list(models),
        "ports": [int(port) for port in ports] if provider_name == "ollama" else [],
        "unique_physical_ports": (
            list(unique_physical_ports(ports)) if provider_name == "ollama" else []
        ),
        "parallel_workers": int(effective_parallel_workers),
        "workers": workers,
        "modes": list(modes),
        "repeats_per_condition": repeats_per_condition,
        "timeout_minutes": timeout_minutes,
        "wait_for_completion": wait_for_completion,
        "hypothesis_skill_set": hypothesis_skill_set,
        "hypothesis_writer_prompt_mode": hypothesis_writer_prompt_mode,
        "hypothesis_scope_errors": list(hypothesis_scope_errors),
        "host_hypothesis_fallback": host_hypothesis_fallback,
        "per_condition": dict(sorted(per_condition.items())),
        "per_port": dict(sorted(per_port.items())),
        "per_worker": dict(sorted(per_worker.items())),
    }


def load_existing_rows(output_root: Path) -> list[dict[str, Any]]:
    jsonl_path = output_root / "trials.jsonl"
    if jsonl_path.exists():
        rows: list[dict[str, Any]] = []
        for line in jsonl_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if isinstance(row, dict):
                    rows.append(row)
        return rows

    results_path = output_root / "benchmark_results.json"
    if results_path.exists():
        payload = json.loads(results_path.read_text(encoding="utf-8"))
        trials = payload.get("trials", [])
        if isinstance(trials, list):
            return [row for row in trials if isinstance(row, dict)]
    return []


def row_should_rerun(row: dict[str, Any]) -> bool:
    if row.get("completion_mode") in {"timeout", "error"}:
        return True
    if row.get("returncode") not in (0, None):
        return True
    validation = row.get("validation")
    if isinstance(validation, dict) and validation.get("validation_passed") is False:
        return True
    return False


def filter_pending_trials(
    trials: Sequence[dict[str, Any]],
    *,
    existing_rows: Sequence[dict[str, Any]],
    resume: bool,
    rerun_failed: bool,
) -> list[dict[str, Any]]:
    if not resume:
        return list(trials)

    existing_by_run_id = {
        str(row.get("run_id")): row
        for row in existing_rows
        if row.get("run_id") is not None
    }
    pending: list[dict[str, Any]] = []
    for trial in trials:
        run_id = str(trial["run_id"])
        existing = existing_by_run_id.get(run_id)
        if existing is None:
            pending.append(trial)
        elif rerun_failed and row_should_rerun(existing):
            pending.append(trial)
    return pending


def write_runner_state(
    *,
    output_root: Path,
    total_trials: int,
    completed_trials: int,
    skipped_trials: int,
    pending_trials: int,
    active_model: str | None,
    current_batch_key: dict[str, Any] | None,
) -> None:
    write_json(
        output_root / "runner_state.json",
        {
            "total_trials": total_trials,
            "completed_trials": completed_trials,
            "skipped_trials": skipped_trials,
            "pending_trials": pending_trials,
            "active_model": active_model,
            "current_batch_key": current_batch_key,
            "updated_at_unix": time.time(),
        },
    )


def run_trial_batch_parallel(
    *,
    batch: Sequence[dict[str, Any]],
    source: Path,
    workspace_root: Path,
    output_root: Path,
    disease: str,
    timeout_minutes: int,
    force: bool,
    wait_for_completion: bool,
    activation_trace_grace_seconds: float,
    hypothesis_skill_set: str = "expanded6",
    hypothesis_writer_prompt_mode: str = "default",
    host_hypothesis_fallback: str = "off",
    provider: str = "ollama",
) -> list[dict[str, Any]]:
    provider_name = normalize_provider(provider)
    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=len(batch)) as executor:
        futures = [
            executor.submit(
                run_one_trial,
                trial=trial,
                source=source,
                workspace_root=workspace_root,
                output_root=output_root,
                disease=disease,
                timeout_minutes=timeout_minutes,
                force=force,
                monitor_activation_trace=not wait_for_completion,
                activation_trace_grace_seconds=activation_trace_grace_seconds,
                hypothesis_skill_set=hypothesis_skill_set,
                hypothesis_writer_prompt_mode=hypothesis_writer_prompt_mode,
                host_hypothesis_fallback=host_hypothesis_fallback,
                provider=provider_name,
            )
            for trial in batch
        ]
        for future in as_completed(futures):
            rows.append(future.result())
    return sorted(
        rows,
        key=lambda row: (
            int(row.get("worker_index", 0) or 0),
            int(row["port"]) if "port" in row else 0,
        ),
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run production Governor activation benchmark."
    )
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--output-root", default="")
    parser.add_argument("--workspace-root", default="")
    parser.add_argument("--disease", default="pulmonary fibrosis")
    parser.add_argument("--timeout-minutes", type=int, default=120)
    parser.add_argument(
        "--hypothesis-skill-set",
        choices=sorted(HYPOTHESIS_WRITER_SKILL_SETS),
        default="expanded6",
        help="Hypothesis-writer skill registry for traced benchmark runs.",
    )
    parser.add_argument(
        "--host-hypothesis-fallback",
        choices=("off", "recovery"),
        default="off",
        help=(
            "Enable deterministic host hypothesis fallback for recovery smokes. "
            "Use 'off' for pure writer benchmarking and 'recovery' for pipeline "
            "stability acceptance runs."
        ),
    )
    parser.add_argument(
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
            "'progressive_disclosure_only' to remove prompt-level forced skill "
            "reads, 'dth_only_required' for DTH-only controlled activation "
            "runs, or 'progressive_disclosure_with_modality_map' to keep soft "
            "modality-to-skill routing without forcing drug-target-hypothesis."
        ),
    )
    parser.add_argument(
        "--models",
        default=",".join(DEFAULT_MODELS),
        help="Comma-separated model list for this matrix.",
    )
    parser.add_argument(
        "--provider",
        default="ollama",
        help="LLM provider for traced runs. Ollama uses --ports; non-Ollama uses --parallel-workers.",
    )
    parser.add_argument(
        "--ports",
        default=",".join(str(port) for port in DEFAULT_PORTS),
        help="Comma-separated Ollama ports for this matrix; ignored for non-Ollama providers.",
    )
    parser.add_argument(
        "--parallel-workers",
        type=int,
        default=1,
        help="Number of serial/parallel worker slots for non-Ollama providers.",
    )
    parser.add_argument(
        "--modes",
        default=",".join(DEFAULT_MODES),
        help="Comma-separated activation modes for this matrix.",
    )
    parser.add_argument(
        "--repeats-per-condition",
        type=int,
        default=None,
        help=(
            "Number of repeated trials for each model x mode condition. "
            "Defaults to one legacy trial per selected port."
        ),
    )
    parser.add_argument("--activation-trace-grace-seconds", type=float, default=10.0)
    parser.add_argument("--wait-for-completion", action="store_true")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate source scope and print the planned matrix without running trials.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip run_ids already present in trials.jsonl or benchmark_results.json.",
    )
    parser.add_argument(
        "--rerun-failed",
        action="store_true",
        help="With --resume, rerun rows that timed out, errored, or failed validation.",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    fallback_mode = getattr(args, "host_hypothesis_fallback", "off")
    prompt_mode = getattr(args, "hypothesis_writer_prompt_mode", "default")
    try:
        provider = normalize_provider(getattr(args, "provider", "ollama"))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    project_root = PROJECT_ROOT
    stamp = time.strftime("governor_production_activation_%Y%m%d_%H%M%S")
    output_root = (
        Path(args.output_root).expanduser().resolve()
        if args.output_root
        else project_root
        / "docs/benchmarks/hypothesis_generation_consistency/results"
        / stamp
    )
    workspace_root = (
        Path(args.workspace_root).expanduser().resolve()
        if args.workspace_root
        else project_root
        / "docs/benchmarks/hypothesis_generation_consistency/workspaces"
        / stamp
    )
    source = Path(args.source).expanduser().resolve()
    if not source.exists():
        raise SystemExit(f"source workspace does not exist: {source}")

    try:
        selected_models = parse_csv_models(args.models)
        selected_ports = (
            parse_csv_ports(args.ports)
            if provider == "ollama"
            else ()
        )
        selected_modes = parse_csv_modes(args.modes)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    parallel_workers = int(getattr(args, "parallel_workers", 1) or 1)
    if parallel_workers < 1:
        raise SystemExit("--parallel-workers must be >= 1")

    if args.repeats_per_condition is not None and args.repeats_per_condition < 1:
        raise SystemExit("--repeats-per-condition must be >= 1")
    if args.repeats_per_condition is None:
        repeats_per_condition = (
            len(selected_ports) if provider == "ollama" else parallel_workers
        )
    else:
        repeats_per_condition = args.repeats_per_condition
    selected_unload_ports = (
        unique_physical_ports(selected_ports) if provider == "ollama" else ()
    )

    trials = build_trial_plan(
        models=selected_models,
        ports=selected_ports,
        modes=selected_modes,
        repeats_per_condition=repeats_per_condition,
        provider=provider,
        parallel_workers=parallel_workers,
    )

    scope_errors = _hypothesis_scope_errors(check_hypothesis_scope_untraced(source))
    if args.dry_run:
        print(
            json.dumps(
                build_dry_run_payload(
                    source=source,
                    trials=trials,
                    models=selected_models,
                    ports=selected_ports,
                    modes=selected_modes,
                    repeats_per_condition=repeats_per_condition,
                    timeout_minutes=args.timeout_minutes,
                    wait_for_completion=args.wait_for_completion,
                    hypothesis_skill_set=args.hypothesis_skill_set,
                    hypothesis_writer_prompt_mode=prompt_mode,
                    hypothesis_scope_errors=scope_errors,
                    host_hypothesis_fallback=fallback_mode,
                    provider=provider,
                    parallel_workers=(
                        len(selected_ports) if provider == "ollama" else parallel_workers
                    ),
                ),
                indent=2,
                ensure_ascii=False,
            )
        )
        return 2 if scope_errors else 0
    if scope_errors:
        raise SystemExit(
            "hypothesis source preflight failed:\n- " + "\n- ".join(scope_errors)
        )

    output_root.mkdir(parents=True, exist_ok=True)
    workspace_root.mkdir(parents=True, exist_ok=True)

    existing_rows = load_existing_rows(output_root) if args.resume else []
    pending_trials = filter_pending_trials(
        trials,
        existing_rows=existing_rows,
        resume=args.resume,
        rerun_failed=args.rerun_failed,
    )
    rows: list[dict[str, Any]] = list(existing_rows)
    remaining_run_ids = {str(trial["run_id"]) for trial in pending_trials}
    skipped_trials = len(trials) - len(pending_trials)
    unload_events: list[dict[str, Any]] = []
    active_model: str | None = None

    def completed_trial_count() -> int:
        seen_completed: set[str] = set()
        for row in rows:
            run_id = row.get("run_id")
            if run_id is None:
                continue
            run_id_text = str(run_id)
            if run_id_text not in remaining_run_ids:
                seen_completed.add(run_id_text)
        return len(seen_completed)

    def write_results() -> None:
        aggregate = aggregate_activation(rows)
        payload = {
            "source": str(source),
            "provider": provider,
            "models": list(selected_models),
            "ports": list(selected_ports) if provider == "ollama" else [],
            "unique_physical_ports": list(selected_unload_ports),
            "parallel_workers": (
                len(selected_ports) if provider == "ollama" else parallel_workers
            ),
            "modes": list(selected_modes),
            "hypothesis_skill_set": args.hypothesis_skill_set,
            "hypothesis_writer_prompt_mode": prompt_mode,
            "host_hypothesis_fallback": fallback_mode,
            "repeats_per_condition": repeats_per_condition,
            "runs_requested": len(trials),
            "resume": args.resume,
            "rerun_failed": args.rerun_failed,
            "trials": rows,
            "aggregate": aggregate,
            "unload_events": unload_events,
        }
        write_json(output_root / "benchmark_results.json", payload)
        (output_root / "benchmark_summary.md").write_text(
            render_summary(rows, aggregate),
            encoding="utf-8",
        )

    try:
        write_runner_state(
            output_root=output_root,
            total_trials=len(trials),
            completed_trials=completed_trial_count(),
            skipped_trials=skipped_trials,
            pending_trials=len(remaining_run_ids),
            active_model=active_model,
            current_batch_key=None,
        )
        for batch in batches_by_model_mode_and_wave(pending_trials):
            model = str(batch[0]["model"])
            if provider == "ollama" and active_model is not None and active_model != model:
                unload_events.extend(
                    unload_model_from_ports(active_model, selected_unload_ports)
                )
            active_model = model

            batch_rows = run_trial_batch_parallel(
                batch=batch,
                source=source,
                workspace_root=workspace_root,
                output_root=output_root,
                disease=args.disease,
                timeout_minutes=args.timeout_minutes,
                force=args.force or args.resume,
                wait_for_completion=args.wait_for_completion,
                activation_trace_grace_seconds=args.activation_trace_grace_seconds,
                hypothesis_skill_set=args.hypothesis_skill_set,
                hypothesis_writer_prompt_mode=prompt_mode,
                host_hypothesis_fallback=fallback_mode,
                provider=provider,
            )
            rerun_run_ids = {str(row["run_id"]) for row in batch_rows}
            rows = [row for row in rows if str(row.get("run_id")) not in rerun_run_ids]
            rows.extend(batch_rows)
            remaining_run_ids.difference_update(rerun_run_ids)
            with (output_root / "trials.jsonl").open("w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            write_results()
            write_runner_state(
                output_root=output_root,
                total_trials=len(trials),
                completed_trials=completed_trial_count(),
                skipped_trials=skipped_trials,
                pending_trials=len(remaining_run_ids),
                active_model=active_model,
                current_batch_key={
                    "model": str(batch[0]["model"]),
                    "mode": str(batch[0]["mode"]),
                    "wave": int(batch[0].get("wave", 0)),
                },
            )
    finally:
        if active_model is not None:
            if provider == "ollama":
                unload_events.extend(
                    unload_model_from_ports(active_model, selected_unload_ports)
                )
        write_results()
        write_runner_state(
            output_root=output_root,
            total_trials=len(trials),
            completed_trials=completed_trial_count(),
            skipped_trials=skipped_trials,
            pending_trials=len(remaining_run_ids),
            active_model=None,
            current_batch_key=None,
        )

    print(f"wrote {output_root / 'benchmark_results.json'}")
    print(f"wrote {output_root / 'benchmark_summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
