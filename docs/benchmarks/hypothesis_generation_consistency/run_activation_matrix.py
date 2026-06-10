"""Run expanded6 SkillsMiddleware vs SkillActivator activation benchmark."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from docs.benchmarks.hypothesis_generation_consistency.run_benchmark import (
    clean_hypothesis_benchmark_workspace,
    validate_trial_output,
    write_json,
)

DEFAULT_SOURCE = Path(
    "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/docs/benchmarks/tmp/res_ipf_drugtarget_tmp"
)
DEFAULT_MODELS = ("qwen3.5:35b", "qwen3.5:122b")
DEFAULT_PORTS = (5000, 6000, 7000)
DEFAULT_MODES = ("middleware_only", "middleware_plus_activator")


def model_slug(model: str) -> str:
    return model.replace("qwen3.5:", "qwen").replace(":", "").replace(".", "")


def build_trial_plan(
    *,
    models: Sequence[str],
    ports: Sequence[int],
    modes: Sequence[str],
) -> list[dict[str, Any]]:
    trials: list[dict[str, Any]] = []
    for model in models:
        for mode in modes:
            for port in ports:
                trials.append(
                    {
                        "model": model,
                        "port": int(port),
                        "mode": mode,
                        "run_id": f"{model_slug(model)}_{mode}_port{int(port)}",
                    }
                )
    return trials


def build_ollama_unload_payload(model: str) -> dict[str, Any]:
    return {"model": model, "keep_alive": 0}


def unload_model_from_port(
    model: str,
    port: int,
    timeout_s: int = 30,
) -> dict[str, Any]:
    url = f"http://127.0.0.1:{port}/api/generate"
    payload = json.dumps(build_ollama_unload_payload(model)).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            response.read()
        return {
            "model": model,
            "port": int(port),
            "ok": True,
            "elapsed_s": round(time.time() - started, 3),
            "error": None,
        }
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {
            "model": model,
            "port": int(port),
            "ok": False,
            "elapsed_s": round(time.time() - started, 3),
            "error": str(exc),
        }


def unload_model_from_ports(
    model: str,
    ports: Sequence[int],
) -> list[dict[str, Any]]:
    return [unload_model_from_port(model, int(port)) for port in ports]


def copy_source_workspace(source: Path, destination: Path, *, force: bool) -> None:
    if destination.exists():
        if not force:
            raise FileExistsError(f"workspace exists: {destination}")
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    clean_hypothesis_benchmark_workspace(destination)


def load_activation_trace(path: Path) -> tuple[dict[str, Any], bool, str | None]:
    if not path.exists():
        return {}, False, f"activation trace missing: {path}"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, False, f"{type(exc).__name__}: {exc}"
    if not isinstance(payload, dict):
        return {}, False, (
            "activation trace must be a JSON object; "
            f"got {type(payload).__name__}"
        )
    return payload, True, None


def run_one_trial(
    *,
    trial: dict[str, Any],
    source: Path,
    workspace_root: Path,
    output_root: Path,
    disease: str,
    timeout_minutes: int,
    force: bool,
) -> dict[str, Any]:
    run_id = str(trial["run_id"])
    workspace = workspace_root / run_id
    copy_source_workspace(source, workspace, force=force)

    activation_trace_path = workspace / "activation_trace.json"
    stdout_path = output_root / f"{run_id}.stdout.log"
    stderr_path = output_root / f"{run_id}.stderr.log"
    started = time.time()

    env = os.environ.copy()
    env.update(
        {
            "LLM_PROVIDER": "ollama",
            "LLM_MODEL": str(trial["model"]),
            "OLLAMA_MODEL": str(trial["model"]),
            "OLLAMA_REASONING": "false",
            "OLLAMA_HOST": f"http://127.0.0.1:{trial['port']}",
            "OLLAMA_BASE_URL": f"http://127.0.0.1:{trial['port']}",
            "DRUG_TARGET_ENABLE_HOST_HYPOTHESIS_FALLBACK": "",
        }
    )

    command = [
        sys.executable,
        "scripts/run_drug_target_traced.py",
        "--data-dir",
        str(workspace),
        "--disease",
        disease,
        "--provider",
        "ollama",
        "--port",
        str(trial["port"]),
        "--timeout",
        str(timeout_minutes),
        "--no-debug",
        "--skip-evidence-assessor",
        "--hypothesis-skill-set",
        "expanded6",
        "--skill-activation-mode",
        str(trial["mode"]),
        "--activation-trace-json",
        str(activation_trace_path),
    ]

    stdout = ""
    stderr = ""
    returncode: int | None = None
    error: str | None = None
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_minutes * 60,
        )
        stdout = completed.stdout
        stderr = completed.stderr
        returncode = completed.returncode
        if completed.returncode != 0:
            error = f"returncode={completed.returncode}"
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        returncode = None
        error = f"TimeoutExpired: exceeded {timeout_minutes} minutes"

    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")

    elapsed_s = time.time() - started
    validation = validate_trial_output(
        run_id,
        workspace,
        elapsed_s=elapsed_s,
        error=error,
    )
    activation_trace, activation_trace_valid, activation_trace_error = (
        load_activation_trace(activation_trace_path)
    )

    return {
        **trial,
        "workspace": str(workspace),
        "activation_trace": str(activation_trace_path),
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
        "returncode": returncode,
        "elapsed_s": round(elapsed_s, 3),
        "validation": validation,
        "activation_trace_valid": activation_trace_valid,
        "activation_trace_error": activation_trace_error,
        "activated_skill_names": (
            activation_trace.get("activated_skill_names", [])
            if activation_trace_valid
            else []
        ),
        "activated_added_skill_names": (
            activation_trace.get("activated_added_skill_names", [])
            if activation_trace_valid
            else []
        ),
        "hypothesis_writer_read_skill_file_calls": (
            activation_trace.get("hypothesis_writer_read_skill_file_calls", [])
            if activation_trace_valid
            else []
        ),
    }


def aggregate_activation(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = f"{row['model']}::{row['mode']}"
        groups.setdefault(key, []).append(row)

    summaries: dict[str, Any] = {}
    for key, group_rows in groups.items():
        skill_counts: dict[str, int] = {}
        added_counts: dict[str, int] = {}
        valid_rows = [
            row for row in group_rows if row.get("activation_trace_valid") is True
        ]
        for row in valid_rows:
            for skill in row.get("activated_skill_names", []):
                skill_counts[str(skill)] = skill_counts.get(str(skill), 0) + 1
            for skill in row.get("activated_added_skill_names", []):
                added_counts[str(skill)] = added_counts.get(str(skill), 0) + 1
        runs = len(group_rows)
        valid_runs = len(valid_rows)
        summaries[key] = {
            "runs": runs,
            "successes": sum(1 for row in group_rows if row.get("returncode") == 0),
            "validation_passes": sum(
                1
                for row in group_rows
                if row.get("validation", {}).get("validation_passed")
            ),
            "activation_trace_valid_runs": valid_runs,
            "activation_trace_invalid_runs": runs - valid_runs,
            "mean_activation_count": (
                sum(len(row.get("activated_skill_names", [])) for row in valid_rows)
                / valid_runs
                if valid_runs
                else 0.0
            ),
            "skill_activation_rates": {
                skill: count / valid_runs
                for skill, count in sorted(skill_counts.items())
            }
            if valid_runs
            else {},
            "added_skill_activation_rates": {
                skill: count / valid_runs
                for skill, count in sorted(added_counts.items())
            }
            if valid_runs
            else {},
        }
    return {"groups": summaries}


def render_summary(rows: Sequence[dict[str, Any]], aggregate: dict[str, Any]) -> str:
    lines = [
        "# Expanded6 Activation Comparison",
        "",
        (
            "| model | port | mode | returncode | validation | activation trace | "
            "activated skills | added skills |"
        ),
        "| --- | ---: | --- | ---: | --- | --- | --- | --- |",
    ]
    for row in rows:
        validation = row.get("validation", {})
        lines.append(
            (
                "| {model} | {port} | {mode} | {returncode} | {validation} | "
                "{trace} | {skills} | {added} |"
            ).format(
                model=row["model"],
                port=row["port"],
                mode=row["mode"],
                returncode=row["returncode"],
                validation=validation.get("validation_passed"),
                trace=(
                    "valid"
                    if row.get("activation_trace_valid")
                    else f"invalid: {row.get('activation_trace_error')}"
                ),
                skills=", ".join(row.get("activated_skill_names", [])) or "-",
                added=", ".join(row.get("activated_added_skill_names", [])) or "-",
            )
        )
    lines.extend(
        [
            "",
            "## Aggregate",
            "",
            "```json",
            json.dumps(aggregate, indent=2, ensure_ascii=False),
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run expanded6 activation comparison.")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--output-root", default="")
    parser.add_argument("--workspace-root", default="")
    parser.add_argument("--disease", default="pulmonary fibrosis")
    parser.add_argument("--timeout-minutes", type=int, default=120)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    stamp = time.strftime("expanded6_activation_%Y%m%d_%H%M%S")
    output_root = (
        Path(args.output_root).expanduser().resolve()
        if args.output_root
        else PROJECT_ROOT
        / "docs/benchmarks/hypothesis_generation_consistency/results"
        / stamp
    )
    workspace_root = (
        Path(args.workspace_root).expanduser().resolve()
        if args.workspace_root
        else PROJECT_ROOT
        / "docs/benchmarks/hypothesis_generation_consistency/workspaces"
        / stamp
    )
    output_root.mkdir(parents=True, exist_ok=True)
    workspace_root.mkdir(parents=True, exist_ok=True)

    source = Path(args.source).expanduser().resolve()
    if not source.exists():
        raise SystemExit(f"source workspace does not exist: {source}")

    rows: list[dict[str, Any]] = []
    unload_events: list[dict[str, Any]] = []
    runner_error: str | None = None
    trials = build_trial_plan(
        models=DEFAULT_MODELS,
        ports=DEFAULT_PORTS,
        modes=DEFAULT_MODES,
    )

    def write_results() -> None:
        aggregate = aggregate_activation(rows)
        payload = {
            "source": str(source),
            "models": list(DEFAULT_MODELS),
            "ports": list(DEFAULT_PORTS),
            "modes": list(DEFAULT_MODES),
            "trials": rows,
            "aggregate": aggregate,
            "unload_events": unload_events,
            "runner_error": runner_error,
        }
        write_json(output_root / "benchmark_results.json", payload)
        (output_root / "benchmark_summary.md").write_text(
            render_summary(rows, aggregate),
            encoding="utf-8",
        )

    active_model = None
    try:
        for trial in trials:
            model = str(trial["model"])
            if active_model and active_model != model:
                unload_events.extend(
                    unload_model_from_ports(active_model, DEFAULT_PORTS)
                )
            active_model = model
            row = run_one_trial(
                trial=trial,
                source=source,
                workspace_root=workspace_root,
                output_root=output_root,
                disease=args.disease,
                timeout_minutes=args.timeout_minutes,
                force=args.force,
            )
            rows.append(row)
            with (output_root / "trials.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as exc:
        runner_error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if active_model:
            unload_events.extend(unload_model_from_ports(active_model, DEFAULT_PORTS))
        write_results()

    print(f"wrote {output_root / 'benchmark_results.json'}")
    print(f"wrote {output_root / 'benchmark_summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
