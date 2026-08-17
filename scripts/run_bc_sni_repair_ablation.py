from __future__ import annotations

import argparse
import asyncio
import contextlib
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict
from urllib.request import urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.sni_ablation_api_stack import APIS, BC_COLLECTION_ID, BC_COLLECTION_SNAPSHOT, MODEL

BC_SOURCE = REPO_ROOT / "res/deep_interpreter/bc/bc"
PMID_FILENAME = re.compile(r"^pmid_(\d+)\.txt$")
BC_PMID_COUNT = 100
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
    "report_validation_terminal.json",
    "report_validation_raw.json",
    "report_validation_guarded.json",
    "synthesis_guardrail_initial.json",
    "synthesis_guardrail_final.json",
    "parts_guardrail_result.json",
    "synthesis_guardrail_result.json",
    "synthesis_raw_validation.json",
    "guardrail_before_after_summary.md",
    "claim_rag_checkpoint.json",
    "timing.json",
    "run_manifest.json",
    "guardrail_manifest.json",
    "recovery_manifest.json",
    "reporter_recovery.json",
    "rag_audit.jsonl",
    "rag_binding.json",
    "collection_snapshot.json",
    "collection_before.json",
    "collection_after.json",
    "collection_after_final.json",
    "writer.trace",
    "reporter.trace",
    "trace.jsonl",
    "token_usage.json",
)
REMOVE_GLOBS = (
    "*_run.stdout.log",
    "*_run.stdout.jsonl",
    "*_run.stderr.log",
    "reporter_attempt_*.json",
    "repair_trace.jsonl",
    "*_tokens.json",
    "token_usage*.json",
)
INPUT_FILES = (
    "papers.json",
    "targets.json",
    "interpretation_guide.md",
    "part4_candidate_selection.json",
)
TARGET_SELECTION_KEYS = ("interest_celltypes", "interest_clusters", "sel_factor")
RUNTIME_DIRS = ("before", "after", "diffs", "logs")
STAGES = (("part1", 1), ("part2", 2), ("part3", 3), ("reporter", None))
STAGE_NUM_PREDICT = {"part1": "12000", "part2": "12000", "part3": "8000", "reporter": "12000"}


@dataclass(frozen=True)
class Condition:
    name: str
    use_wiki_context: bool
    label: str


CONDITIONS = (
    Condition("wiki-on", True, "SNI"),
    Condition("wiki-off", False, "no-SNI"),
)
CONDITION_BY_LABEL = {condition.label: condition for condition in CONDITIONS}
EXPECTED_PAIR_ORDER = {
    "01": ("no-SNI", "SNI", 8882, 5000),
    "02": ("SNI", "no-SNI", 8883, 6000),
    "03": ("no-SNI", "SNI", 8884, 7000),
    "04": ("SNI", "no-SNI", 8882, 5000),
    "05": ("no-SNI", "SNI", 8883, 6000),
    "06": ("SNI", "no-SNI", 8884, 7000),
    "07": ("no-SNI", "SNI", 8882, 5000),
    "08": ("SNI", "no-SNI", 8883, 6000),
    "09": ("no-SNI", "SNI", 8884, 7000),
    "10": ("SNI", "no-SNI", 8882, 5000),
}
RAG_BACKEND_PORT = 4000


class ManifestPair(TypedDict):
    pair_id: str
    api_port: int
    backend_port: int
    rag_backend_port: int
    condition_order: list[str]


class ExperimentManifest(TypedDict):
    path: str
    pairs: list[ManifestPair]

StageRunner = Callable[[Path, dict[str, str]], int]
CollectionSnapshot = Callable[[str], dict[str, Any]]
CollectionPmids = Callable[[str], set[str]]
Api = dict[str, Any]
PairProcessRunner = Callable[[ManifestPair, Path, Path, dict[str, str]], int]


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


def _papers_pmids(path: Path) -> set[str]:
    payload = read_json(path)
    papers = payload.get("papers")
    if not isinstance(papers, list):
        raise RuntimeError(f"BC source papers file is missing papers list: {path}")
    pmids: set[str] = set()
    for paper in papers:
        if not isinstance(paper, dict) or paper.get("pmid") is None:
            raise RuntimeError(f"BC source papers file has malformed PMID entry: {path}")
        pmids.add(str(paper["pmid"]))
    return pmids


def _document_rows(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("documents", "items", "results"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return rows
    return []


def _collection_pmids(api_url: str) -> set[str]:
    pmids: set[str] = set()
    limit = 100
    offset = 0
    while True:
        url = f"{api_url}/collections/{BC_COLLECTION_ID}/documents?limit={limit}&offset={offset}"
        with urlopen(url, timeout=30) as response:
            rows = _document_rows(json.load(response))
        for row in rows:
            metadata = row.get("metadata") if isinstance(row, dict) else None
            filename = metadata.get("filename") if isinstance(metadata, dict) else None
            if isinstance(filename, str) and (match := PMID_FILENAME.match(filename)):
                pmids.add(match.group(1))
        if len(rows) < limit:
            return pmids
        offset += limit


def _pmid_identity(source_pmids: set[str], collection_pmids: set[str]) -> dict[str, Any]:
    def digest(pmids: set[str]) -> str:
        return hashlib.sha256("\n".join(sorted(pmids)).encode("utf-8")).hexdigest()

    return {
        "source_pmid_count": len(source_pmids),
        "source_pmid_sha256": digest(source_pmids),
        "collection_pmid_count": len(collection_pmids),
        "collection_pmid_sha256": digest(collection_pmids),
    }


def _api_int(api: Api, key: str) -> int:
    return int(api[key])


def _output_root_is_inside_source(source: Path, output_root: Path) -> bool:
    resolved_source = source.expanduser().resolve(strict=False)
    resolved_output = output_root.expanduser().resolve(strict=False)
    return resolved_output == resolved_source or resolved_source in resolved_output.parents


def _pair_id_text(pair_id: int | str) -> str:
    return f"{pair_id:02d}" if isinstance(pair_id, int) else pair_id


def _run_dir(output_root: Path, pair_id: int | str, condition: Condition) -> Path:
    return output_root / f"pair-{_pair_id_text(pair_id)}" / condition.name


def prepare_condition_copy(
    *,
    source: Path,
    output_root: Path,
    pair_id: int | str,
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
    for directory in RUNTIME_DIRS:
        runtime_dir = destination / directory
        if runtime_dir.exists():
            shutil.rmtree(runtime_dir)
        runtime_dir.mkdir(parents=True, exist_ok=True)

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
            "target_selection": {
                name: run_targets.get(name) for name in TARGET_SELECTION_KEYS
            },
        },
    )
    return destination


def _default_manifest_path(output_root: Path) -> Path:
    return (
        output_root.parent / "experiment_manifest.json"
        if output_root.name == "pairs"
        else output_root / "experiment_manifest.json"
    )


def _validate_api_map(manifest: dict[str, Any]) -> None:
    observed = manifest.get("api_ollama_map")
    if not isinstance(observed, list) or len(observed) != len(APIS):
        raise RuntimeError("manifest api_ollama_map must define exactly four lanes")
    expected = [
        {
            "api_port": _api_int(api, "api_port"),
            "ollama_port": _api_int(api, "backend_port"),
            "ollama_base_url": f"http://localhost:{_api_int(api, 'backend_port')}",
            "rag_api_url": f"http://localhost:{_api_int(api, 'api_port')}",
            "service": api["service"],
        }
        for api in APIS
    ]
    if observed != expected:
        raise RuntimeError("manifest api/backend mapping does not match fixed topology")


def load_experiment_manifest(path: Path) -> ExperimentManifest:
    manifest = read_json(path)
    if manifest.get("rag_backend_port") != RAG_BACKEND_PORT:
        raise RuntimeError(f"manifest rag_backend_port must be {RAG_BACKEND_PORT}")
    fixed = manifest.get("fixed_collection")
    if not isinstance(fixed, dict):
        raise RuntimeError("manifest fixed_collection is missing")
    if (
        fixed.get("uuid") != BC_COLLECTION_ID
        or fixed.get("expected_document_count") != 100
        or fixed.get("expected_chunk_count") != 1553
        or fixed.get("snapshot") != BC_COLLECTION_SNAPSHOT
    ):
        raise RuntimeError("manifest fixed collection does not match BC invariant")
    _validate_api_map(manifest)
    if manifest.get("run_settings", {}).get("pair_count") != 10:
        raise RuntimeError("manifest must define exactly 10 pairs")
    pairs = manifest.get("ordered_pairs")
    if not isinstance(pairs, list) or len(pairs) != 10:
        raise RuntimeError("manifest ordered_pairs must contain exactly 10 pairs")

    parsed: list[ManifestPair] = []
    for raw in pairs:
        if not isinstance(raw, dict):
            raise RuntimeError("manifest pair must be an object")
        pair_id = str(raw.get("pair_id"))
        expected = EXPECTED_PAIR_ORDER.get(pair_id)
        if expected is None:
            raise RuntimeError(f"unexpected manifest pair id: {pair_id}")
        first, second, api_port, backend_port = expected
        condition_order = raw.get("condition_order")
        if (
            condition_order != [first, second]
            or raw.get("first_condition") != first
            or raw.get("api_port") != api_port
            or raw.get("ollama_port") != backend_port
            or raw.get("rag_backend_port") != RAG_BACKEND_PORT
        ):
            raise RuntimeError(f"manifest pair {pair_id} does not match frozen order/topology")
        parsed.append(
            {
                "pair_id": pair_id,
                "api_port": api_port,
                "backend_port": backend_port,
                "rag_backend_port": RAG_BACKEND_PORT,
                "condition_order": [first, second],
            }
        )
    if [pair["pair_id"] for pair in parsed] != [f"{idx:02d}" for idx in range(1, 11)]:
        raise RuntimeError("manifest pair order must be 01 through 10")
    return {"path": str(path), "pairs": parsed}


def _verify_source_manifest(data_dir: Path) -> None:
    manifest = read_json(data_dir / "source_manifest.json")
    source = Path(str(manifest.get("source", "")))
    for name, expected in dict(manifest.get("source_files", {})).items():
        if sha256(source / name) != expected:
            raise RuntimeError(f"source input changed during run: {name}")
    for name, expected in dict(manifest.get("copied_files", {})).items():
        if name == "targets.json":
            continue
        if sha256(data_dir / name) != expected:
            raise RuntimeError(f"copied input changed during run: {name}")
    expected_selection = dict(manifest.get("target_selection", {}))
    observed_targets = read_json(data_dir / "targets.json")
    observed_selection = {
        name: observed_targets.get(name) for name in TARGET_SELECTION_KEYS
    }
    if observed_selection != expected_selection:
        raise RuntimeError("copied target selection changed during run")


def _condition_env(data_dir: Path, api: Api, condition: Condition) -> dict[str, str]:
    backend_port = _api_int(api, "backend_port")
    api_port = _api_int(api, "api_port")
    return {
        "LLM_PROVIDER": "ollama",
        "OLLAMA_BASE_URL": f"http://localhost:{backend_port}",
        "OLLAMA_MODEL": MODEL,
        "OLLAMA_REASONING": "true",
        "OLLAMA_REQUEST_TIMEOUT_SECONDS": "10800",
        "REPORTER_ATTEMPT_TIMEOUT_SECONDS": "10800",
        "CLAIM_RAG_JUDGE_NUM_PREDICT": "3000",
        "CLAIM_RAG_JUDGE_TIMEOUT_SECONDS": "300",
        "CLAIM_RAG_PRIMARY_JUDGE_TIMEOUT_SECONDS": "180",
        "CLAIM_RAG_SINGLE_CLAIM_TIMEOUT_SECONDS": "120",
        "CCI_RAG_BASE_URL": f"http://localhost:{api_port}",
        "DEEP_INTERPRETER_DATA_DIR": str(data_dir),
        "DEEP_INTERPRETER_USE_WIKI_CONTEXT": str(condition.use_wiki_context).lower(),
        "DEEP_INTERPRETER_REQUIRE_AGENTIC_RAG": "true",
        "DEEP_INTERPRETER_FIXED_COLLECTION_ID": BC_COLLECTION_ID,
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


def _claim_selection_cache_hits(*artifacts: dict[str, Any]) -> int:
    total = 0
    for artifact in artifacts:
        selection = artifact.get("claim_selection") if isinstance(artifact, dict) else None
        hits = selection.get("retrieval_cache_hits") if isinstance(selection, dict) else None
        if type(hits) is int:
            total += hits
    return total


def _rag_retrieval_metrics(path: Path, retrieval_cache_hits: int = 0) -> dict[str, int | float]:
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ] if path.is_file() else []
    query_hashes = {
        record["query_sha256"]
        for record in records
        if isinstance(record.get("query_sha256"), str)
    }
    hashed_attempt_count = sum(
        1 for record in records if isinstance(record.get("query_sha256"), str)
    )
    result_pmids: set[str] = set()
    for record in records:
        pmids = record.get("result_pmids")
        if isinstance(pmids, list):
            result_pmids.update(pmid for pmid in pmids if isinstance(pmid, str))
    elapsed_seconds_total = sum(
        record["elapsed_seconds"]
        for record in records
        if type(record.get("elapsed_seconds")) in {int, float}
    )
    return {
        "attempt_count": len(records),
        "positive_result_count": sum(
            1
            for record in records
            if record.get("success") is True
            and record.get("error_type") is None
            and type(record.get("result_count")) is int
            and record["result_count"] > 0
        ),
        "zero_hit_count": sum(
            1
            for record in records
            if record.get("success") is False
            and record.get("error_type") == "NoRelevantContext"
            and type(record.get("result_count")) is int
            and record["result_count"] == 0
        ),
        "unique_query_count": len(query_hashes),
        "duplicate_attempt_count": hashed_attempt_count - len(query_hashes),
        "unique_result_pmid_count": len(result_pmids),
        "retrieval_cache_hits": retrieval_cache_hits,
        "elapsed_seconds_total": round(elapsed_seconds_total, 3),
    }


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
    part_repair_attempts = int(parts_guardrail.get("repair_attempt_count") or 0)
    part_terminal_repairs = int(parts_guardrail.get("terminal_repair_count") or 0)
    repair_attempts = int(synthesis_guardrail.get("repair_attempt_count") or 0)
    terminal_repairs = int(synthesis_guardrail.get("terminal_repair_count") or 0)
    return {
        "parts": {
            "repair_attempt_count": part_repair_attempts,
            "terminal_repair_count": part_terminal_repairs,
            "total_repair_count": part_repair_attempts + part_terminal_repairs,
            "changed_sections": parts_guardrail.get("changed_sections"),
        },
        "synthesis": {
            "repair_attempt_count": repair_attempts,
            "terminal_repair_count": terminal_repairs,
            "total_repair_count": repair_attempts + terminal_repairs,
            "changed_claims": synthesis_guardrail.get("changed_claims"),
        },
        "retrieval": _rag_retrieval_metrics(
            data_dir / "rag_audit.jsonl",
            _claim_selection_cache_hits(parts_guardrail, synthesis_guardrail),
        ),
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
        or not (
            record.get("success") is True
            and record.get("error_type") is None
            and type(record.get("result_count")) is int
            and record["result_count"] > 0
            or record.get("success") is False
            and record.get("error_type") == "NoRelevantContext"
            and type(record.get("result_count")) is int
            and record["result_count"] == 0
        )
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
    pair: ManifestPair,
    condition: Condition,
    stage_runner: StageRunner,
    collection_snapshot: CollectionSnapshot,
    collection_pmids: CollectionPmids = _collection_pmids,
) -> int:
    api = {"api_port": pair["api_port"], "backend_port": pair["backend_port"]}
    pair_id = pair["pair_id"]
    data_dir = prepare_condition_copy(source=source, output_root=output_root, pair_id=pair_id, condition=condition)
    env = _condition_env(data_dir, api, condition)
    status = "failed"
    error = None
    started_at = utc_now()
    collection_before = collection_snapshot(env["CCI_RAG_BASE_URL"])
    source_pmids = _papers_pmids(data_dir / "papers.json")
    observed_pmids = collection_pmids(env["CCI_RAG_BASE_URL"])
    pmid_identity = _pmid_identity(source_pmids, observed_pmids)
    write_json(data_dir / "collection_before.json", collection_before | {"pmid_identity": pmid_identity})
    try:
        if collection_before != BC_COLLECTION_SNAPSHOT:
            raise RuntimeError(f"BC collection snapshot drift before run: {collection_before}")
        if len(source_pmids) != BC_PMID_COUNT or len(observed_pmids) != BC_PMID_COUNT:
            raise RuntimeError("BC source and fixed collection must each contain exactly 100 PMIDs")
        if observed_pmids != source_pmids:
            raise RuntimeError("BC source papers PMIDs do not match fixed collection PMIDs")
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
                "condition_label": condition.label,
                "pair_condition_order": pair["condition_order"],
                "backend_port": _api_int(api, "backend_port"),
                "rag_backend_port": pair["rag_backend_port"],
                "api_port": _api_int(api, "api_port"),
                "rag_api_url": env["CCI_RAG_BASE_URL"],
                "collection_id": BC_COLLECTION_ID,
                "collection": collection_before,
                "pmid_identity": pmid_identity,
                "model_settings": {key: env[key] for key in env if key.startswith(("OLLAMA_", "LLM_", "DEEP_INTERPRETER_", "CCI_RAG_"))},
                "started_at": started_at,
                "finished_at": utc_now(),
                "return_status": status,
                "error": error,
                "metrics": metrics,
            },
        )


def run_pair(
    pair: ManifestPair,
    *,
    source: Path,
    output_root: Path,
    stage_runner: StageRunner,
    collection_snapshot: CollectionSnapshot,
    collection_pmids: CollectionPmids = _collection_pmids,
) -> int:
    rc = 0
    for label in pair["condition_order"]:
        condition = CONDITION_BY_LABEL[label]
        rc = run_condition(
            source=source,
            output_root=output_root,
            pair=pair,
            condition=condition,
            stage_runner=stage_runner,
            collection_snapshot=collection_snapshot,
            collection_pmids=collection_pmids,
        )
        if rc:
            return rc
    return rc


def _pair_process_env(
    pair: ManifestPair, output_root: Path, source: Path, manifest_path: Path
) -> dict[str, str]:
    pair_root = output_root / f"pair-{pair['pair_id']}"
    return {
        "BC_SNI_PAIR_ID": pair["pair_id"],
        "BC_SNI_BACKEND_PORT": str(pair["backend_port"]),
        "BC_SNI_RAG_BACKEND_PORT": str(pair["rag_backend_port"]),
        "BC_SNI_API_PORT": str(pair["api_port"]),
        "BC_SNI_CONDITION_ORDER": ",".join(pair["condition_order"]),
        "BC_SNI_PAIR_ROOT": str(pair_root),
        "BC_SNI_PAIR_AUDIT_ROOT": str(pair_root / "audit"),
        "BC_SNI_PAIR_RAG_BINDING_ROOT": str(pair_root / "rag-bindings"),
        "BC_SNI_SOURCE": str(source),
        "BC_SNI_MANIFEST_PATH": str(manifest_path),
    }


def _default_pair_process_runner(
    pair: ManifestPair,
    output_root: Path,
    source: Path,
    env: dict[str, str],
) -> int:
    completed = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--pair",
            str(pair["pair_id"]),
            "--output-root",
            str(output_root),
            "--source",
            str(source),
            "--manifest",
            env["BC_SNI_MANIFEST_PATH"],
        ],
        env={**os.environ, **env},
        check=False,
    )
    return completed.returncode


def build_schedule(manifest: ExperimentManifest) -> list[list[ManifestPair]]:
    return [[pair] for pair in manifest["pairs"]]


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
    mode.add_argument("--smoke", action="store_true", help="Validate manifest and print the dry run plan.")
    mode.add_argument("--pair", type=int, help="Run one ordered pair.")
    mode.add_argument("--all", action="store_true", help="Run ordered pairs 1-10 globally serial.")
    mode.add_argument("--summarize", action="store_true", help="Write summary.json from existing manifests.")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=BC_SOURCE)
    parser.add_argument("--manifest", type=Path)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    stage_runner: StageRunner = _default_stage_runner,
    collection_snapshot: CollectionSnapshot = _default_collection_snapshot,
    collection_pmids: CollectionPmids = _collection_pmids,
    pair_process_runner: PairProcessRunner = _default_pair_process_runner,
) -> int:
    args = build_parser().parse_args(argv)
    if _output_root_is_inside_source(args.source, args.output_root):
        print("output root must not equal or be nested under source", file=sys.stderr)
        return 1
    manifest_path = args.manifest or _default_manifest_path(args.output_root)
    try:
        manifest = load_experiment_manifest(manifest_path)
    except Exception as exc:  # noqa: BLE001
        print(f"invalid experiment manifest: {exc}", file=sys.stderr)
        return 1
    schedule = build_schedule(manifest)
    if args.smoke:
        print(json.dumps({"ok": True, "manifest": str(manifest_path), "schedule": schedule}, indent=2))
        return 0
    if args.summarize:
        args.output_root.mkdir(parents=True, exist_ok=True)
        return summarize(args.output_root)
    args.output_root.mkdir(parents=True, exist_ok=True)
    if args.pair or args.smoke:
        pair_id = f"{args.pair:02d}" if args.pair is not None else "01"
        pair = next((item for item in manifest["pairs"] if item["pair_id"] == pair_id), None)
        if pair is None:
            print(f"pair {pair_id} is not in manifest", file=sys.stderr)
            return 1
        return run_pair(
            pair,
            source=args.source,
            output_root=args.output_root,
            stage_runner=stage_runner,
            collection_snapshot=collection_snapshot,
            collection_pmids=collection_pmids,
        )

    rc = 0
    for batch in schedule:
        with ThreadPoolExecutor(max_workers=len(batch)) as pool:
            futures = [
                pool.submit(
                    pair_process_runner,
                    item,
                    args.output_root,
                    args.source,
                    _pair_process_env(
                        item,
                        args.output_root,
                        args.source,
                        manifest_path,
                    ),
                )
                for item in batch
            ]
            for future in futures:
                rc = max(rc, future.result())
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
