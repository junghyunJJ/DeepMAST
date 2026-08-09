from __future__ import annotations

import argparse
import asyncio
import contextlib
import difflib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.request import urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.sni_ablation_api_stack import APIS, BC_COLLECTION_ID, BC_COLLECTION_SNAPSHOT, MODEL

BC_SOURCE = Path("/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/res/bc_interpreter")
REPORT_FILES = ("part1_final.md", "part2_final.md", "part3_final.md", "synthesis.md")
REMOVE_FILES = (
    *REPORT_FILES,
    "part1_raw.md",
    "part2_raw.md",
    "part3_raw.md",
    "synthesis_raw.md",
    "synthesis_guarded.md",
    "synthesis_validation.json",
    "synthesis_targets.json",
    "CCI_Analysis_Report.html",
    "report_validation_initial.json",
    "report_validation_final.json",
    "report_validation_raw.json",
    "report_validation_guarded.json",
    "synthesis_guardrail_initial.json",
    "synthesis_guardrail_final.json",
    "synthesis_raw_validation.json",
    "guardrail_before_after_summary.md",
    "claim_rag_checkpoint.json",
)
REMOVE_GLOBS = ("*_run.stdout.log", "*_run.stdout.jsonl", "*_run.stderr.log")
INPUT_FILES = (
    "papers.json",
    "targets.json",
    "interpretation_guide.md",
    "part4_candidate_selection.json",
)
STAGES = (("part1", 1), ("part2", 2), ("part3", 3), ("reporter", None))
STAGE_NUM_PREDICT = {"part1": "12000", "part2": "12000", "part3": "8000", "reporter": "12000"}


@dataclass(frozen=True)
class Condition:
    name: str
    use_wiki_context: bool


CONDITIONS = (
    Condition("wiki-on", True),
    Condition("wiki-off", False),
)

StageRunner = Callable[[Path, dict[str, str]], int]
CollectionSnapshot = Callable[[str], dict[str, Any]]
Api = dict[str, Any]
PairProcessRunner = Callable[[int, Api, Path, Path, dict[str, str]], int]


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _default_collection_snapshot(api_url: str) -> dict[str, Any]:
    with urlopen(f"{api_url}/collections/{BC_COLLECTION_ID}", timeout=30) as response:
        row = json.load(response)
    return {key: row.get(key) for key in BC_COLLECTION_SNAPSHOT}


def _api_int(api: Api, key: str) -> int:
    return int(api[key])


def _output_root_is_inside_source(source: Path, output_root: Path) -> bool:
    resolved_source = source.expanduser().resolve(strict=False)
    resolved_output = output_root.expanduser().resolve(strict=False)
    return resolved_output == resolved_source or resolved_source in resolved_output.parents


def _run_dir(output_root: Path, pair_id: int, condition: Condition) -> Path:
    return output_root / f"pair-{pair_id:02d}" / condition.name


def prepare_condition_copy(
    *,
    source: Path,
    output_root: Path,
    pair_id: int,
    condition: Condition,
) -> Path:
    destination = _run_dir(output_root, pair_id, condition)
    if destination.exists():
        raise RuntimeError(f"refusing to overwrite existing condition run: {destination}")
    shutil.copytree(source, destination)
    for name in REMOVE_FILES:
        (destination / name).unlink(missing_ok=True)
    for pattern in REMOVE_GLOBS:
        for path in destination.glob(pattern):
            path.unlink()
    shutil.rmtree(destination / "large_tool_results", ignore_errors=True)
    for directory in ("before", "after", "diffs", "logs"):
        (destination / directory).mkdir(parents=True, exist_ok=True)

    missing = [name for name in INPUT_FILES if not (destination / name).is_file()]
    if missing:
        raise RuntimeError(f"copied BC source is missing required inputs: {missing}")
    (destination / "data_path.txt").write_text(str(destination.resolve()), encoding="utf-8")
    run_targets = read_json(destination / "targets.json")
    run_targets["data_directory"] = str(destination.resolve())
    write_json(destination / "run_targets.json", run_targets)
    write_json(
        destination / "source_manifest.json",
        {
            "source": str(source),
            "copy": str(destination.resolve()),
            "source_files": {name: sha256(source / name) for name in INPUT_FILES},
            "copied_files": {name: sha256(destination / name) for name in INPUT_FILES},
        },
    )
    return destination


def _verify_source_manifest(data_dir: Path) -> None:
    manifest = read_json(data_dir / "source_manifest.json")
    source = Path(str(manifest.get("source", "")))
    for name, expected in dict(manifest.get("source_files", {})).items():
        if sha256(source / name) != expected:
            raise RuntimeError(f"source input changed during run: {name}")
    for name, expected in dict(manifest.get("copied_files", {})).items():
        if sha256(data_dir / name) != expected:
            raise RuntimeError(f"copied input changed during run: {name}")


def _condition_env(data_dir: Path, api: Api, condition: Condition) -> dict[str, str]:
    backend_port = _api_int(api, "backend_port")
    api_port = _api_int(api, "api_port")
    return {
        "LLM_PROVIDER": "ollama",
        "OLLAMA_BASE_URL": f"http://localhost:{backend_port}",
        "OLLAMA_MODEL": MODEL,
        "OLLAMA_REASONING": "true",
        "OLLAMA_REQUEST_TIMEOUT_SECONDS": "3600",
        "REPORTER_ATTEMPT_TIMEOUT_SECONDS": "3600",
        "CLAIM_RAG_JUDGE_NUM_PREDICT": "3000",
        "CLAIM_RAG_JUDGE_TIMEOUT_SECONDS": "300",
        "CLAIM_RAG_PRIMARY_JUDGE_TIMEOUT_SECONDS": "180",
        "CLAIM_RAG_SINGLE_CLAIM_TIMEOUT_SECONDS": "120",
        "CCI_RAG_BASE_URL": f"http://localhost:{api_port}",
        "DEEP_INTERPRETER_DATA_DIR": str(data_dir),
        "DEEP_INTERPRETER_USE_WIKI_CONTEXT": str(condition.use_wiki_context).lower(),
        "DEEP_INTERPRETER_REQUIRE_AGENTIC_RAG": "true",
        "DEEP_INTERPRETER_RAG_AUDIT_PATH": str(data_dir / "rag_audit.jsonl"),
    }


def _with_env(env: dict[str, str], fn: Callable[[], int]) -> int:
    previous = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    try:
        return fn()
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _bind_read_only_collection(data_dir: Path) -> dict[str, str]:
    from src.agents.deep_interpreter.tools import literature_rag

    literature_rag.reset_rag_state()
    literature_rag._RAG_STATE["available"] = True
    aliases = {}
    for part_name in ("all", "part1", "part2", "part3", "synthesis"):
        key = literature_rag._rag_collection_key(part_name, str(data_dir))
        literature_rag._RAG_STATE["collection_ids"][key] = BC_COLLECTION_ID
        aliases[part_name] = key
    return aliases


def _disable_collection_preparation_tool() -> None:
    from src.agents.deep_interpreter.subagents.configs import SUBAGENT_CONFIGS

    for subagent_name in ("interpreter", "reporter"):
        SUBAGENT_CONFIGS[subagent_name]["tools"] = [
            tool
            for tool in SUBAGENT_CONFIGS[subagent_name]["tools"]
            if getattr(tool, "name", "") != "prepare_rag_literature"
        ]


def _snapshot_files(data_dir: Path, destination_name: str, names: tuple[str, ...]) -> None:
    destination = data_dir / destination_name
    destination.mkdir(exist_ok=True)
    for name in names:
        source = data_dir / name
        if source.is_file() and not (destination / name).exists():
            shutil.copy2(source, destination / name)


def _install_guardrail_capture(data_dir: Path) -> Callable[[], None]:
    from src.agents.deep_interpreter.middleware import report_guardrail as middleware_guardrail
    from src.agents.deep_interpreter.tools import report as report_tool

    original_parts = middleware_guardrail.run_report_guardrail
    original_synthesis = report_tool._run_synthesis_guardrail_before_html

    def parts(path: str | Path, *, provider: str | None = None) -> dict[str, Any]:
        resolved = Path(path).resolve()
        _snapshot_files(resolved, "before", REPORT_FILES[:3])
        result = original_parts(path, provider=provider)
        if result.get("status") != "skipped":
            write_json(resolved / "parts_guardrail_result.json", result)
        return result

    def synthesis(path: str) -> dict[str, Any] | None:
        resolved = Path(path).resolve()
        _snapshot_files(resolved, "before", ("synthesis.md",))
        result = original_synthesis(path)
        if result is not None:
            write_json(resolved / "synthesis_guardrail_result.json", result)
        return result

    middleware_guardrail.run_report_guardrail = parts
    report_tool._run_synthesis_guardrail_before_html = synthesis

    def restore() -> None:
        middleware_guardrail.run_report_guardrail = original_parts
        report_tool._run_synthesis_guardrail_before_html = original_synthesis

    return restore


async def _run_deep_stage(data_dir: Path, stage: str, part: int | None) -> dict[str, Any]:
    from scripts import run_deep_interpreter_agent as runner

    subagent = "interpreter" if part else "reporter"
    targets = read_json(data_dir / "run_targets.json")
    argv = [
        "--provider",
        "ollama",
        "--data-dir",
        str(data_dir),
        "--targets-json",
        str(data_dir / "run_targets.json"),
        "--subagent",
        subagent,
        "--traceback",
    ]
    if part:
        argv.extend(("--part", str(part)))
    args = runner.parse_args(argv)
    message = runner._build_subagent_message(subagent, data_dir, targets, part)
    args.message = (
        message
        + "\n\nThe approved BC RAG collection is already bound read-only for all part names. "
        "Do not call prepare_rag_literature, index papers, create collections, or fall back "
        "from agentic RAG."
    )
    previous_num_predict = os.environ.get("OLLAMA_NUM_PREDICT")
    os.environ["OLLAMA_NUM_PREDICT"] = STAGE_NUM_PREDICT[stage]
    stdout_path = data_dir / "logs" / f"{stage}.stdout.log"
    stderr_path = data_dir / "logs" / f"{stage}.stderr.log"
    started = time.monotonic()
    try:
        with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                return_code = await runner.run(args)
    finally:
        if previous_num_predict is None:
            os.environ.pop("OLLAMA_NUM_PREDICT", None)
        else:
            os.environ["OLLAMA_NUM_PREDICT"] = previous_num_predict
    return {
        "stage": stage,
        "return_code": return_code,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "ollama_num_predict": int(STAGE_NUM_PREDICT[stage]),
    }


def _default_stage_runner(data_dir: Path, env: dict[str, str]) -> int:
    def run() -> int:
        aliases = _bind_read_only_collection(data_dir)
        _disable_collection_preparation_tool()
        restore_guardrails = _install_guardrail_capture(data_dir)
        write_json(data_dir / "rag_binding.json", {"collection_id": BC_COLLECTION_ID, "aliases": aliases})
        try:
            stages = []
            for stage, part in STAGES:
                result = asyncio.run(_run_deep_stage(data_dir, stage, part))
                stages.append(result)
                if result["return_code"] != 0:
                    write_json(data_dir / "timing.json", {"stages": stages})
                    return int(result["return_code"])
            write_json(data_dir / "timing.json", {"stages": stages})
            return 0
        finally:
            restore_guardrails()

    return _with_env(env, run)


def _severity_counts(path: Path, artifact: str) -> dict[str, int]:
    counts = {"error": 0, "warning": 0}
    for issue in read_json(path).get("issues", []):
        if not isinstance(issue, dict) or issue.get("file") != artifact:
            continue
        severity = str(issue.get("severity") or issue.get("level") or "").lower()
        if severity in counts:
            counts[severity] += 1
    return counts


def extract_metrics(data_dir: Path) -> dict[str, Any]:
    parts_guardrail = read_json(data_dir / "parts_guardrail_result.json")
    synthesis_guardrail = read_json(data_dir / "synthesis_validation.json").get("synthesis_guardrail", {})
    if not isinstance(synthesis_guardrail, dict):
        synthesis_guardrail = {}
    artifacts = {}
    for artifact in REPORT_FILES:
        if artifact == "synthesis.md":
            artifacts[artifact] = {
                "initial_error_count": synthesis_guardrail.get("initial_error_count"),
                "final_error_count": synthesis_guardrail.get("final_error_count"),
            }
            continue
        artifacts[artifact] = {
            "initial_error_count": _severity_counts(data_dir / "report_validation_initial.json", artifact)["error"],
            "final_error_count": _severity_counts(data_dir / "report_validation_final.json", artifact)["error"],
        }
    repair_attempts = int(synthesis_guardrail.get("repair_attempt_count") or 0)
    terminal_repairs = int(synthesis_guardrail.get("terminal_repair_count") or 0)
    return {
        "parts": {
            "repair_attempt_count": parts_guardrail.get("repair_attempt_count"),
            "changed_sections": parts_guardrail.get("changed_sections"),
        },
        "synthesis": {
            "repair_attempt_count": repair_attempts,
            "terminal_repair_count": terminal_repairs,
            "total_repair_count": repair_attempts + terminal_repairs,
            "changed_claims": synthesis_guardrail.get("changed_claims"),
        },
        "artifacts": artifacts,
    }


def _validate_rag_audit(data_dir: Path, condition: Condition) -> None:
    path = data_dir / "rag_audit.jsonl"
    if not path.is_file():
        raise RuntimeError(f"missing RAG audit: {path}")
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not records:
        raise RuntimeError(f"empty RAG audit: {path}")
    bad = [
        record
        for record in records
        if record.get("endpoint") != "agentic_search"
        or record.get("collection_uuid") != BC_COLLECTION_ID
        or record.get("use_wiki_context") is not condition.use_wiki_context
        or record.get("success") is not True
        or record.get("error_type") is not None
        or not isinstance(record.get("result_count"), int)
        or record.get("result_count", 0) <= 0
    ]
    if bad:
        raise RuntimeError(f"invalid RAG audit record: {bad[0]}")


def _validate_final_guardrails(data_dir: Path) -> None:
    metrics = extract_metrics(data_dir)
    final_errors = [
        artifact
        for artifact, counts in metrics["artifacts"].items()
        if counts.get("final_error_count") not in (0, None)
    ]
    if final_errors:
        raise RuntimeError(f"final guardrail errors remain: {final_errors}")


def _write_diffs(data_dir: Path) -> None:
    _snapshot_files(data_dir, "after", REPORT_FILES)
    for name in REPORT_FILES:
        before_path = data_dir / "before" / name
        after_path = data_dir / "after" / name
        if before_path.is_file() and after_path.is_file():
            diff = difflib.unified_diff(
                before_path.read_text(encoding="utf-8").splitlines(),
                after_path.read_text(encoding="utf-8").splitlines(),
                fromfile=f"before/{name}",
                tofile=f"after/{name}",
                lineterm="",
            )
            (data_dir / "diffs" / f"{name}.diff").write_text("\n".join(diff) + "\n", encoding="utf-8")


def run_condition(
    *,
    source: Path,
    output_root: Path,
    pair_id: int,
    api: Api,
    condition: Condition,
    stage_runner: StageRunner,
    collection_snapshot: CollectionSnapshot,
) -> int:
    data_dir = prepare_condition_copy(source=source, output_root=output_root, pair_id=pair_id, condition=condition)
    env = _condition_env(data_dir, api, condition)
    status = "failed"
    error = None
    started_at = utc_now()
    collection_before = collection_snapshot(env["CCI_RAG_BASE_URL"])
    write_json(data_dir / "collection_before.json", collection_before)
    try:
        if collection_before != BC_COLLECTION_SNAPSHOT:
            raise RuntimeError(f"BC collection snapshot drift before run: {collection_before}")
        return_code = stage_runner(data_dir, env)
        if return_code != 0:
            raise RuntimeError(f"stage runner returned {return_code}")
        collection_after = collection_snapshot(env["CCI_RAG_BASE_URL"])
        write_json(data_dir / "collection_after.json", collection_after)
        if collection_after != collection_before:
            raise RuntimeError(f"BC collection changed during run: {collection_after}")
        _verify_source_manifest(data_dir)
        _validate_rag_audit(data_dir, condition)
        _validate_final_guardrails(data_dir)
        status = "passed"
        return 0
    except Exception as exc:  # noqa: BLE001
        error = {"type": type(exc).__name__, "message": str(exc)}
        return 1
    finally:
        _write_diffs(data_dir)
        metrics = extract_metrics(data_dir)
        write_json(
            data_dir / "run_manifest.json",
            {
                "pair_id": pair_id,
                "condition": condition.name,
                "backend_port": _api_int(api, "backend_port"),
                "api_port": _api_int(api, "api_port"),
                "rag_api_url": env["CCI_RAG_BASE_URL"],
                "collection_id": BC_COLLECTION_ID,
                "collection": collection_before,
                "model_settings": {key: env[key] for key in env if key.startswith(("OLLAMA_", "LLM_", "DEEP_INTERPRETER_", "CCI_RAG_"))},
                "started_at": started_at,
                "finished_at": utc_now(),
                "return_status": status,
                "error": error,
                "metrics": metrics,
            },
        )


def run_pair(
    pair_id: int,
    *,
    source: Path,
    output_root: Path,
    api: Api,
    stage_runner: StageRunner,
    collection_snapshot: CollectionSnapshot,
) -> int:
    rc = 0
    for condition in CONDITIONS:
        rc = max(
            rc,
            run_condition(
                source=source,
                output_root=output_root,
                pair_id=pair_id,
                api=api,
                condition=condition,
                stage_runner=stage_runner,
                collection_snapshot=collection_snapshot,
            ),
        )
    return rc


def _pair_process_env(pair_id: int, api: Api, output_root: Path, source: Path) -> dict[str, str]:
    pair_root = output_root / f"pair-{pair_id:02d}"
    return {
        "BC_SNI_PAIR_ID": str(pair_id),
        "BC_SNI_BACKEND_PORT": str(_api_int(api, "backend_port")),
        "BC_SNI_API_PORT": str(_api_int(api, "api_port")),
        "BC_SNI_PAIR_ROOT": str(pair_root),
        "BC_SNI_PAIR_AUDIT_ROOT": str(pair_root / "audit"),
        "BC_SNI_PAIR_RAG_BINDING_ROOT": str(pair_root / "rag-bindings"),
        "BC_SNI_SOURCE": str(source),
    }


def _default_pair_process_runner(
    pair_id: int,
    api: Api,
    output_root: Path,
    source: Path,
    env: dict[str, str],
) -> int:
    api_index = APIS.index(api)
    completed = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--pair",
            str(pair_id),
            "--api-index",
            str(api_index),
            "--output-root",
            str(output_root),
            "--source",
            str(source),
        ],
        env={**os.environ, **env},
        check=False,
    )
    return completed.returncode


def build_schedule(pair_ids: Sequence[int], apis: Sequence[Api]) -> list[list[dict[str, int]]]:
    batches = []
    api_count = len(apis)
    for start in range(0, len(pair_ids), api_count):
        batch = []
        for pair_id, api in zip(pair_ids[start : start + api_count], apis, strict=False):
            batch.append(
                {
                    "pair_id": int(pair_id),
                    "api_port": _api_int(api, "api_port"),
                    "backend_port": _api_int(api, "backend_port"),
                }
            )
        batches.append(batch)
    return batches


def summarize(output_root: Path) -> int:
    rows = []
    for manifest_path in sorted(output_root.glob("pair-*/wiki-*/run_manifest.json")):
        manifest = read_json(manifest_path)
        rows.append(
            {
                "pair_id": manifest.get("pair_id"),
                "condition": manifest.get("condition"),
                "return_status": manifest.get("return_status"),
                "backend_port": manifest.get("backend_port"),
                "metrics": manifest.get("metrics", {}),
            }
        )
    write_json(output_root / "summary.json", {"runs": rows})
    print(json.dumps({"runs": rows}, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run paired BC SNI repair ablation conditions.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--smoke", action="store_true", help="Run pair 1 only.")
    mode.add_argument("--pair", type=int, help="Run one ordered pair.")
    mode.add_argument("--all", action="store_true", help="Run ordered pairs 1-10, max four backend lanes.")
    mode.add_argument("--summarize", action="store_true", help="Write summary.json from existing manifests.")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=BC_SOURCE)
    parser.add_argument("--api-index", type=int, choices=range(len(APIS)), help=argparse.SUPPRESS)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    stage_runner: StageRunner = _default_stage_runner,
    collection_snapshot: CollectionSnapshot = _default_collection_snapshot,
    pair_process_runner: PairProcessRunner = _default_pair_process_runner,
) -> int:
    args = build_parser().parse_args(argv)
    if _output_root_is_inside_source(args.source, args.output_root):
        print("output root must not equal or be nested under source", file=sys.stderr)
        return 1
    args.output_root.mkdir(parents=True, exist_ok=True)
    if args.summarize:
        return summarize(args.output_root)
    if args.pair or args.smoke:
        pair_id = args.pair or 1
        api = APIS[args.api_index] if args.api_index is not None else APIS[(pair_id - 1) % len(APIS)]
        return run_pair(
            pair_id,
            source=args.source,
            output_root=args.output_root,
            api=api,
            stage_runner=stage_runner,
            collection_snapshot=collection_snapshot,
        )

    rc = 0
    pair_ids = list(range(1, 11))
    api_by_backend = {int(api["backend_port"]): api for api in APIS}
    for batch in build_schedule(pair_ids, APIS):
        with ThreadPoolExecutor(max_workers=len(batch)) as pool:
            futures = [
                pool.submit(
                    pair_process_runner,
                    item["pair_id"],
                    api_by_backend[item["backend_port"]],
                    args.output_root,
                    args.source,
                    _pair_process_env(
                        item["pair_id"],
                        api_by_backend[item["backend_port"]],
                        args.output_root,
                        args.source,
                    ),
                )
                for item in batch
            ]
            for future in futures:
                rc = max(rc, future.result())
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
