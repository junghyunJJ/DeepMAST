from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

from docs.benchmarks.hypothesis_generation_consistency.analysis import (
    aggregate_trial_rows,
    summarize_report,
)
from src.agents.drug_target.tools.evidence_loader import (
    check_hypothesis_completion,
    load_evidence_files,
)


def load_benchmark_env() -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=False)


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def resolve_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else PROJECT_ROOT / path


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def prepare_trial_workspace(
    source: Path,
    workspace_root: Path,
    run_id: str,
    *,
    force: bool,
) -> Path:
    source = source.resolve()
    run_path = Path(run_id)
    if (
        not run_id
        or run_path.is_absolute()
        or len(run_path.parts) != 1
        or run_path.parts[0] in {"", ".", ".."}
    ):
        raise ValueError(f"run_id must be a single relative path component: {run_id!r}")

    workspace_root = workspace_root.resolve()
    workspace = (workspace_root / run_path.parts[0]).resolve()
    if not workspace.is_relative_to(workspace_root):
        raise ValueError(f"workspace escapes workspace_root: {workspace}")

    if workspace.exists():
        if not force:
            raise FileExistsError(f"workspace already exists: {workspace}")
        shutil.rmtree(workspace)
    shutil.copytree(source, workspace)
    stale_report = workspace / "evidence" / "hypothesis_report.json"
    stale_report.unlink(missing_ok=True)
    return workspace


def check_hypothesis_scope(data_dir: Path) -> dict[str, Any]:
    raw = load_evidence_files.invoke({"data_dir": str(data_dir), "scope": "hypothesis"})
    loaded = json.loads(raw)
    return {
        "scope": loaded.get("scope"),
        "file_count": loaded.get("file_count"),
        "contrast_count": loaded.get("contrast_count"),
        "errors": loaded.get("errors", []),
        "first_files": sorted((loaded.get("files") or {}).keys())[:20],
        "excluded_count": len(loaded.get("excluded_files") or []),
    }


@contextmanager
def patched_env(values: dict[str, str | None]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def validate_trial_output(
    run_id: str,
    workspace: Path,
    *,
    elapsed_s: float,
    error: str | None,
) -> dict[str, Any]:
    report_path = workspace / "evidence" / "hypothesis_report.json"
    completion = json.loads(
        check_hypothesis_completion.invoke({"data_dir": str(workspace)})
    )
    report_summary = None
    if report_path.exists():
        try:
            report = read_json(report_path)
            report_summary = summarize_report(report)
        except Exception:
            report_summary = None
    if error is not None:
        return {
            "run_id": run_id,
            "workspace": str(workspace),
            "hypothesis_report": str(report_path),
            "success": False,
            "validation_passed": False,
            "elapsed_s": round(elapsed_s, 3),
            "error": error,
            "completion": completion,
            "report_summary": report_summary,
        }
    if not report_path.exists():
        return {
            "run_id": run_id,
            "workspace": str(workspace),
            "hypothesis_report": str(report_path),
            "success": False,
            "validation_passed": False,
            "elapsed_s": round(elapsed_s, 3),
            "error": "hypothesis_report.json missing",
            "completion": completion,
            "report_summary": None,
        }
    try:
        report = read_json(report_path)
    except Exception as exc:
        return {
            "run_id": run_id,
            "workspace": str(workspace),
            "hypothesis_report": str(report_path),
            "success": False,
            "validation_passed": False,
            "elapsed_s": round(elapsed_s, 3),
            "error": f"{type(exc).__name__}: {exc}",
            "completion": completion,
            "report_summary": None,
        }
    summary = summarize_report(report)
    validation_passed = (
        bool(completion.get("hypothesis_complete"))
        and summary["schema_version"] == "hypothesis_report.v2"
        and summary["hypothesis_count"] > 0
        and isinstance(report, dict)
        and isinstance(report.get("topn_coverage"), dict)
        and isinstance(report.get("prediction_grounding_summary"), dict)
        and not summary["topn_missing"]
        and summary["unverified_numeric_predictions"] == 0
    )
    return {
        "run_id": run_id,
        "workspace": str(workspace),
        "hypothesis_report": str(report_path),
        "success": True,
        "validation_passed": validation_passed,
        "elapsed_s": round(elapsed_s, 3),
        "error": None,
        "completion": completion,
        "report_summary": summary,
    }


async def run_hypothesis_writer_once(
    workspace: Path,
    *,
    disease: str,
    provider: str,
    timeout_s: int,
) -> None:
    from src.agents.drug_target.agent import DrugTargetConfig, create_drug_target_agent

    env = {
        "DRUG_TARGET_SKIP_EVIDENCE_ASSESSOR": "1",
        "DRUG_TARGET_DATA_DIR": str(workspace),
        "DRUG_TARGET_ENABLE_HOST_HYPOTHESIS_FALLBACK": None,
    }
    with patched_env(env):
        config = DrugTargetConfig(
            provider=provider,  # type: ignore[arg-type]
            data_dir=str(workspace),
            disease=disease,
            use_checkpointer=False,
        )
        agent, backend = create_drug_target_agent(config)
        try:
            await asyncio.wait_for(
                agent.ainvoke(
                    {
                        "messages": [
                            {
                                "role": "user",
                                "content": (
                                    "Run resume-mode hypothesis generation only. "
                                    "Use the hypothesis_writer subagent and save "
                                    "evidence/hypothesis_report.json."
                                ),
                            }
                        ]
                    },
                    config={"configurable": {"thread_id": str(uuid.uuid4())}},
                ),
                timeout=timeout_s,
            )
        finally:
            if backend is not None and hasattr(backend, "cleanup"):
                backend.cleanup()  # type: ignore[union-attr]


async def run_trial(
    *,
    run_id: str,
    source: Path,
    workspace_root: Path,
    disease: str,
    provider: str,
    timeout_s: int,
    force: bool,
) -> dict[str, Any]:
    workspace = prepare_trial_workspace(source, workspace_root, run_id, force=force)
    started = time.time()
    error = None
    try:
        await run_hypothesis_writer_once(
            workspace,
            disease=disease,
            provider=provider,
            timeout_s=timeout_s,
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    elapsed = time.time() - started
    return validate_trial_output(run_id, workspace, elapsed_s=elapsed, error=error)
