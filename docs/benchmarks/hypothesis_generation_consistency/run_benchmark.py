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

TRACE_DISABLED_ENV = {
    "LANGCHAIN_TRACING_V2": "false",
    "LANGSMITH_TRACING": "false",
    "LANGCHAIN_API_KEY": None,
    "LANGSMITH_API_KEY": None,
}

HYPOTHESIS_BENCHMARK_CLEAN_FILES = (
    "drug.md",
    "drug_report.html",
    "drug_report_render.json",
    "drug_report_reference_card.json",
    "part4_candidate_selection.json",
    "part4_therapeutic_synthesis.md",
    "report_expansions.json",
    "target_assessment.json",
    "report_data.json",
    "report_validation.json",
    "evidence/hypothesis_report.json",
)
HYPOTHESIS_BENCHMARK_CLEAN_DIRS = (
    "conversation_history",
    "large_tool_results",
)
HYPOTHESIS_BENCHMARK_CLEAN_GLOBS = (
    "token_usage_*.json",
    "trace_*.log",
)

CURRENT4_HYPOTHESIS_WRITER_SKILLS = (
    "drug-target-hypothesis",
    "opentargets-database",
    "gwas-database",
    "chembl-database",
)

EXPANDED6_HYPOTHESIS_WRITER_SKILLS = (
    "drug-target-hypothesis",
    "opentargets-database",
    "gwas-database",
    "chembl-database",
    "compare-census-gene-pair-by-cell-type",
    "string-database",
)

HYPOTHESIS_WRITER_SKILL_SETS = {
    "current4": CURRENT4_HYPOTHESIS_WRITER_SKILLS,
    "expanded6": EXPANDED6_HYPOTHESIS_WRITER_SKILLS,
}

HYPOTHESIS_WRITER_RESUME_MESSAGE = (
    "Run resume-mode hypothesis generation only using the hypothesis_writer subagent. "
    "Load evidence with load_evidence_files(data_dir=data_dir, scope='hypothesis'). "
    "Do not use write_file, read_file, ls, or /tmp for hypothesis output. "
    "After validate_evidence_references passes, immediately call "
    "save_hypothesis_report(data_dir=data_dir, report=report). "
    "The required artifact is evidence/hypothesis_report.json."
)


def resolve_hypothesis_writer_skill_names(skill_set: str) -> tuple[str, ...]:
    try:
        return tuple(list(HYPOTHESIS_WRITER_SKILL_SETS[skill_set]))
    except KeyError as exc:
        known = ", ".join(sorted(HYPOTHESIS_WRITER_SKILL_SETS))
        raise ValueError(
            f"unknown skill set {skill_set!r}; expected one of: {known}"
        ) from exc


def _is_root_hypothesis_report_artifact(path: Path) -> bool:
    name = path.name.casefold()
    return name.startswith("hypothesis_report") and name.endswith(".json")


def _root_hypothesis_report_artifacts(workspace: Path) -> list[Path]:
    if not workspace.exists():
        return []
    return sorted(
        (
            path
            for path in workspace.iterdir()
            if _is_root_hypothesis_report_artifact(path)
            and (path.is_file() or path.is_dir())
        ),
        key=lambda path: (path.name.casefold(), path.name),
    )


def find_forbidden_hypothesis_artifacts(workspace: Path) -> list[str]:
    """Return root-level hypothesis report artifacts outside evidence/."""
    return [
        path.name
        for path in _root_hypothesis_report_artifacts(workspace)
        if path.is_file()
    ]


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


def clean_hypothesis_benchmark_workspace(workspace: Path) -> list[str]:
    """Remove copied artifacts that can bias fresh hypothesis generation."""
    removed: list[str] = []
    for relative in HYPOTHESIS_BENCHMARK_CLEAN_FILES:
        path = workspace / relative
        if path.exists():
            path.unlink()
            removed.append(relative)
    for relative in HYPOTHESIS_BENCHMARK_CLEAN_DIRS:
        path = workspace / relative
        if path.exists():
            shutil.rmtree(path)
            removed.append(f"{relative}/")
    for path in _root_hypothesis_report_artifacts(workspace):
        if path.is_file():
            path.unlink()
            removed.append(path.name)
        elif path.is_dir():
            shutil.rmtree(path)
            removed.append(f"{path.name}/")
    for pattern in HYPOTHESIS_BENCHMARK_CLEAN_GLOBS:
        for path in sorted(workspace.glob(pattern)):
            if path.is_file():
                path.unlink()
                removed.append(path.name)
            elif path.is_dir():
                shutil.rmtree(path)
                removed.append(f"{path.name}/")
    return removed


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
    clean_hypothesis_benchmark_workspace(workspace)
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


def check_hypothesis_scope_untraced(data_dir: Path) -> dict[str, Any]:
    with patched_env(TRACE_DISABLED_ENV):
        return check_hypothesis_scope(data_dir)


def validate_trial_output(
    run_id: str,
    workspace: Path,
    *,
    elapsed_s: float,
    error: str | None,
) -> dict[str, Any]:
    report_path = workspace / "evidence" / "hypothesis_report.json"
    forbidden_artifacts = find_forbidden_hypothesis_artifacts(workspace)
    completion = json.loads(
        check_hypothesis_completion.invoke({"data_dir": str(workspace)})
    )
    report_summary = None
    if report_path.exists():
        try:
            report = read_json(report_path)
            if isinstance(report, dict):
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
            "forbidden_artifacts": forbidden_artifacts,
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
            "forbidden_artifacts": forbidden_artifacts,
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
            "forbidden_artifacts": forbidden_artifacts,
        }
    if not isinstance(report, dict):
        return {
            "run_id": run_id,
            "workspace": str(workspace),
            "hypothesis_report": str(report_path),
            "success": False,
            "validation_passed": False,
            "elapsed_s": round(elapsed_s, 3),
            "error": (
                "hypothesis_report.json must be a JSON object; "
                f"got {type(report).__name__}"
            ),
            "completion": completion,
            "report_summary": None,
            "forbidden_artifacts": forbidden_artifacts,
        }
    summary = summarize_report(report)
    validation_passed = (
        bool(completion.get("hypothesis_complete"))
        and summary["schema_version"] == "hypothesis_report.v2"
        and summary["hypothesis_count"] > 0
        and isinstance(report.get("topn_coverage"), dict)
        and isinstance(report.get("prediction_grounding_summary"), dict)
        and not summary["topn_missing"]
        and summary["unverified_numeric_predictions"] == 0
        and not forbidden_artifacts
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
        "forbidden_artifacts": forbidden_artifacts,
    }


async def run_hypothesis_writer_once(
    workspace: Path,
    *,
    disease: str,
    provider: str,
    timeout_s: int,
    hypothesis_writer_skill_names: tuple[str, ...],
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
            hypothesis_writer_skill_names=hypothesis_writer_skill_names,
        )
        agent, backend = create_drug_target_agent(config)
        try:
            await asyncio.wait_for(
                agent.ainvoke(
                    {
                        "messages": [
                            {
                                "role": "user",
                                "content": HYPOTHESIS_WRITER_RESUME_MESSAGE,
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
    hypothesis_writer_skill_names: tuple[str, ...],
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
            hypothesis_writer_skill_names=hypothesis_writer_skill_names,
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    elapsed = time.time() - started
    return validate_trial_output(run_id, workspace, elapsed_s=elapsed, error=error)


def format_markdown_summary(
    aggregate: dict[str, Any],
    rows: list[dict[str, Any]],
) -> str:
    lines = [
        "# Hypothesis Generation Consistency Benchmark Summary",
        "",
        f"- Total runs: {aggregate['total_runs']}",
        f"- Successful runs: {aggregate['successful_runs']}",
        f"- Validation-passed runs: {aggregate['validation_passed_runs']}",
        f"- Success rate: {aggregate['success_rate']:.2%}",
        f"- Validation pass rate: {aggregate['validation_pass_rate']:.2%}",
        f"- Hypothesis count values: {aggregate['hypothesis_count_values']}",
        f"- Mean pairwise gene Jaccard: {aggregate['mean_pairwise_gene_jaccard']}",
        (
            "- Mean pairwise evidence-reference Jaccard: "
            f"{aggregate['mean_pairwise_ref_jaccard']}"
        ),
        (
            "- Mean pairwise title similarity: "
            f"{aggregate['mean_pairwise_title_similarity']}"
        ),
        (
            "- Mean pairwise core-claim similarity: "
            f"{aggregate['mean_pairwise_core_claim_similarity']}"
        ),
        "",
        "## Runs",
        "",
        (
            "| Run | Success | Validation | Hypotheses | TOP-N missing | "
            "Unverified numeric | Elapsed s |"
        ),
        "| --- | --- | --- | ---: | --- | ---: | ---: |",
    ]
    for row in rows:
        summary = row.get("report_summary") or {}
        lines.append(
            (
                "| {run_id} | {success} | {validation} | {count} | {missing} | "
                "{unverified} | {elapsed} |"
            ).format(
                run_id=row.get("run_id"),
                success=row.get("success"),
                validation=row.get("validation_passed"),
                count=summary.get("hypothesis_count", 0),
                missing=", ".join(summary.get("topn_missing", [])) or "-",
                unverified=summary.get("unverified_numeric_predictions", "-"),
                elapsed=row.get("elapsed_s"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run repeated real hypothesis_writer trials on frozen evidence."
    )
    parser.add_argument("--source", default="res_ipf_ollama_tmp")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--disease", default="pulmonary fibrosis")
    parser.add_argument("--provider", default=os.getenv("LLM_PROVIDER") or "ollama")
    parser.add_argument("--timeout-s", type=int, default=1800)
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--skill-set",
        choices=sorted(HYPOTHESIS_WRITER_SKILL_SETS),
        default="current4",
        help=(
            "Hypothesis-writer skill registry for the run. "
            "current4 is production default; expanded6 adds compare-census and STRING."
        ),
    )
    return parser.parse_args()


async def async_main() -> int:
    load_benchmark_env()
    args = parse_args()
    source = resolve_path(args.source)
    if not source.exists():
        raise SystemExit(f"source workspace does not exist: {source}")
    if args.dry_run:
        scope = check_hypothesis_scope_untraced(source)
        print(json.dumps(scope, indent=2, ensure_ascii=False))
        return 0 if not scope["errors"] else 1
    provider = args.provider.strip()
    if not provider:
        raise SystemExit("--provider must be non-empty for live benchmark runs")
    hypothesis_writer_skill_names = resolve_hypothesis_writer_skill_names(
        args.skill_set
    )
    scope = check_hypothesis_scope(source)
    if scope["errors"]:
        raise SystemExit(f"hypothesis scope loader errors: {scope['errors']}")

    stem = (
        Path(args.output_root).name
        if args.output_root
        else f"ipf_hypothesis_consistency_{utc_stamp()}"
    )
    output_root = (
        resolve_path(args.output_root)
        if args.output_root
        else PROJECT_ROOT
        / "docs/benchmarks/hypothesis_generation_consistency/results"
        / stem
    )
    workspace_root = (
        PROJECT_ROOT
        / "docs/benchmarks/hypothesis_generation_consistency/workspaces"
        / stem
    )
    output_root.mkdir(parents=True, exist_ok=True)
    workspace_root.mkdir(parents=True, exist_ok=True)

    trials_path = output_root / "trials.jsonl"
    rows: list[dict[str, Any]] = []
    for index in range(1, args.runs + 1):
        run_id = f"run_{index:02d}"
        row = await run_trial(
            run_id=run_id,
            source=source,
            workspace_root=workspace_root,
            disease=args.disease,
            provider=provider,
            timeout_s=args.timeout_s,
            force=args.force,
            hypothesis_writer_skill_names=hypothesis_writer_skill_names,
        )
        rows.append(row)
        append_jsonl(trials_path, row)
        print(json.dumps(row, ensure_ascii=False))

    aggregate = aggregate_trial_rows(rows)
    result_payload = {
        "source": str(source),
        "provider": provider,
        "disease": args.disease,
        "runs_requested": args.runs,
        "skill_set": args.skill_set,
        "hypothesis_writer_skill_names": list(hypothesis_writer_skill_names),
        "hypothesis_scope": scope,
        "aggregate": aggregate,
        "trials": rows,
    }
    write_json(output_root / "benchmark_results.json", result_payload)
    (output_root / "benchmark_summary.md").write_text(
        format_markdown_summary(aggregate, rows),
        encoding="utf-8",
    )
    print(f"wrote {output_root / 'benchmark_results.json'}")
    print(f"wrote {output_root / 'benchmark_summary.md'}")
    return 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
