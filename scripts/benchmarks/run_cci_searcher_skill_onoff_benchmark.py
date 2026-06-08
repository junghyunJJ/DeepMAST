"""Run qwen CCI SEARCHER skill ON/OFF benchmark rows."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import csv
import json
import os
import signal
import sys
import time
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from docs.benchmarks.harness_x_model.common import (
    CONDITIONS,
    compute_cases_sha256,
    load_cases,
    normalize_case,
    run_single_trial,
)
from src.agents.deep_interpreter.tools.literature_handoff import (
    CONTEXT_BUCKET,
    DIRECT_BUCKET,
    create_literature_handoff,
)


MODEL_HOSTS = {
    "qwen3.5:35b": "http://localhost:7000",
    "qwen3.5:122b": "http://localhost:6000",
}
LEGACY_HANDOFF_CAP = 40

CSV_FIELD_ORDER = [
    "trial_index",
    "case_id",
    "category",
    "lr_pair",
    "condition",
    "model",
    "model_strength",
    "skill_on",
    "total_papers",
    "candidate_unique_papers",
    "direct_papers",
    "context_papers",
    "disease_only_papers",
    "rejected_papers",
    "handoff_papers",
    "latency_s",
    "error",
]


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = {key for row in rows for key in row.keys()}
    fieldnames = [key for key in CSV_FIELD_ORDER if key in fields]
    fieldnames.extend(sorted(fields - set(fieldnames)))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


@contextmanager
def _trial_timeout(seconds: int):
    if seconds <= 0:
        yield
        return

    def _raise_timeout(_signum: int, _frame: Any) -> None:
        raise TimeoutError(f"trial exceeded timeout of {seconds}s")

    previous_handler = signal.signal(signal.SIGALRM, _raise_timeout)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, float(seconds))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, previous_timer[0], previous_timer[1])


def _row_path(rows_dir: Path, trial_index: int, condition_name: str) -> Path:
    return rows_dir / f"row_{trial_index:04d}_{condition_name}.json"


def _serialize_result(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return dict(result)
    if is_dataclass(result) and not isinstance(result, type):
        return asdict(result)
    if isinstance(result, SimpleNamespace):
        return vars(result).copy()
    if hasattr(result, "__dict__"):
        return vars(result).copy()
    raise TypeError(f"Unsupported trial result type: {type(result).__name__}")


def _select_cases(cases: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return cases if limit <= 0 else cases[:limit]


def _parse_conditions(value: str) -> list[dict[str, Any]]:
    by_name = {item["condition"]: item for item in CONDITIONS}
    names = [part.strip() for part in value.split(",") if part.strip()]
    if not names:
        raise argparse.ArgumentTypeError("at least one condition is required")
    unknown = [name for name in names if name not in by_name]
    if unknown:
        raise argparse.ArgumentTypeError(f"unknown condition(s): {', '.join(unknown)}")
    return [by_name[name] for name in names]


def _lr_pairs_for_case(case: dict[str, Any]) -> list[dict[str, Any]]:
    normalized = normalize_case(case)
    pair = str(normalized.get("lr_pair", ""))
    parts = [part.strip() for part in pair.split("-") if part.strip()]
    payload: dict[str, Any] = {"pair": pair}
    if parts:
        payload["ligand"] = parts[0]
    if len(parts) > 1:
        payload["receptor"] = parts[1]
    return [payload]


def _read_bucket_counts(workspace: Path) -> dict[str, int]:
    candidates_path = workspace / "citation_candidates.json"
    handoff_path = workspace / "papers_filtered.json"
    candidates = json.loads(candidates_path.read_text(encoding="utf-8")) if candidates_path.exists() else {}
    handoff = json.loads(handoff_path.read_text(encoding="utf-8")) if handoff_path.exists() else {}
    counts = candidates.get("counts", {}) if isinstance(candidates, dict) else {}
    handoff_papers = handoff.get("papers", []) if isinstance(handoff, dict) else []
    return {
        "candidate_unique_papers": int(candidates.get("source", {}).get("unique_papers", 0))
        if isinstance(candidates, dict)
        else 0,
        "direct_papers": int(counts.get(DIRECT_BUCKET, 0) or 0),
        "context_papers": int(counts.get(CONTEXT_BUCKET, 0) or 0),
        "disease_only_papers": int(counts.get("disease_only_background", 0) or 0),
        "rejected_papers": int(counts.get("rejected_weak_evidence", 0) or 0),
        "handoff_papers": len(handoff_papers) if isinstance(handoff_papers, list) else 0,
    }


def _run_handoff(
    row: dict[str, Any],
    case: dict[str, Any],
    *,
    use_filtered_papers_path: bool = False,
) -> dict[str, Any]:
    workspace_value = row.get("trial_workspace")
    if not workspace_value:
        raise RuntimeError("trial result missing trial_workspace")
    workspace = Path(str(workspace_value)).expanduser().resolve()
    papers_value = row.get("papers_path")
    papers_path = (
        Path(str(papers_value)).expanduser().resolve()
        if papers_value
        else workspace / "papers.json"
    )
    if not papers_path.exists():
        raise RuntimeError(f"missing papers file: {papers_path}")
    data_dir = papers_path.parent

    normalized = normalize_case(case)
    create_literature_handoff.invoke(
        {
            "raw_papers_path": papers_path.name,
            "output_path": "papers_filtered.json",
            "citation_candidates_path": "citation_candidates.json",
            "data_dir": str(data_dir),
            "disease": normalized.get("disease", ""),
            "lr_pairs": _lr_pairs_for_case(case),
            "pathways": normalized.get("pathways", []),
            "celltypes": normalized.get("celltypes", []),
            "cap": LEGACY_HANDOFF_CAP,
        }
    )
    filtered_path = data_dir / "papers_filtered.json"
    updates: dict[str, Any] = {
        **_read_bucket_counts(data_dir),
        "raw_papers_path": str(papers_path),
        "filtered_papers_path": str(filtered_path),
        "citation_candidates_path": str(data_dir / "citation_candidates.json"),
    }
    if use_filtered_papers_path:
        updates["papers_path"] = str(filtered_path)
    return updates


def _recover_papers_artifact(row: dict[str, Any], *, benchmark_mode: str = "C") -> bool:
    candidates: list[Path] = []
    papers_value = row.get("papers_path")
    if papers_value:
        papers_path = Path(str(papers_value)).expanduser().resolve()
        expected_name = "papers_raw.json" if benchmark_mode == "retrieval_only" else "papers.json"
        if papers_path.name == expected_name:
            candidates.append(papers_path)
    workspace_value = row.get("trial_workspace")
    if workspace_value:
        workspace = Path(str(workspace_value)).expanduser().resolve()
        if benchmark_mode == "retrieval_only":
            candidates.append(workspace / "papers_raw.json")
        else:
            candidates.append(workspace / "papers.json")

    for candidate in candidates:
        if not candidate.exists():
            continue
        if row.get("error"):
            row["agent_error"] = row["error"]
            row["artifact_recovered"] = True
            row["error"] = ""
        row["papers_path"] = str(candidate)
        if not row.get("total_papers"):
            try:
                payload = json.loads(candidate.read_text(encoding="utf-8"))
                papers = payload.get("papers", []) if isinstance(payload, dict) else []
                row["total_papers"] = len(papers) if isinstance(papers, list) else 0
            except (OSError, json.JSONDecodeError):
                row["total_papers"] = 0
        return True
    return False


def _load_existing_row(
    rows_dir: Path,
    *,
    trial_index: int,
    condition_name: str,
) -> dict[str, Any] | None:
    path = _row_path(rows_dir, trial_index, condition_name)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _path_exists(value: Any) -> bool:
    if not value:
        return False
    return Path(str(value)).expanduser().exists()


def _resume_row_is_reusable(
    row: dict[str, Any],
    *,
    case: dict[str, Any],
    condition: dict[str, Any],
    repeat: int,
    trial_index: int,
    benchmark_mode: str,
    cases_sha256: str,
) -> bool:
    if row.get("error"):
        return False
    if int(row.get("trial_index", -1) or -1) != trial_index:
        return False
    if row.get("case_id") != case.get("case_id"):
        return False
    if row.get("condition") != condition.get("condition"):
        return False
    if int(row.get("repeat", 1) or 1) != repeat:
        return False
    if row.get("benchmark_mode") != benchmark_mode:
        return False
    if row.get("cases_sha256") != cases_sha256:
        return False

    if benchmark_mode == "retrieval_only":
        return (
            _path_exists(row.get("raw_papers_path"))
            and _path_exists(row.get("filtered_papers_path") or row.get("papers_path"))
            and _path_exists(row.get("citation_candidates_path"))
        )
    return _path_exists(row.get("papers_path"))


def _summarize_by_condition(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_condition: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_condition.setdefault(str(row.get("condition", "")), []).append(row)

    summary: dict[str, dict[str, Any]] = {}
    for condition, condition_rows in sorted(by_condition.items()):
        summary[condition] = {
            "n": len(condition_rows),
            "errors": sum(1 for row in condition_rows if row.get("error")),
            "total_papers": sum(int(row.get("total_papers", 0) or 0) for row in condition_rows),
            "handoff_papers": sum(int(row.get("handoff_papers", 0) or 0) for row in condition_rows),
            "direct_papers": sum(int(row.get("direct_papers", 0) or 0) for row in condition_rows),
            "context_papers": sum(int(row.get("context_papers", 0) or 0) for row in condition_rows),
        }
    return summary


def _write_results_ko(path: Path, rows: list[dict[str, Any]]) -> None:
    error_count = sum(1 for row in rows if row.get("error"))
    lines = [
        "# 검색기 Skill ON/OFF 벤치마크 결과",
        "",
        f"- 생성 시각: {_utc_now()}",
        f"- 총 row: {len(rows)}",
        f"- error row: {error_count}",
        "",
        "## 조건별 요약",
        "",
        "| condition | n | errors | handoff papers | direct | context |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for condition, condition_summary in _summarize_by_condition(rows).items():
        lines.append(
            f"| {condition} | {condition_summary['n']} | "
            f"{condition_summary['errors']} | "
            f"{condition_summary['handoff_papers']} | "
            f"{condition_summary['direct_papers']} | "
            f"{condition_summary['context_papers']} |"
        )
    lines.extend(
        [
            "",
            "## 결론",
            "",
            "error row가 있으면 전체 실행은 실패 코드로 종료된다.",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--case-limit", type=int, default=0)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--conditions", default="weak_on,weak_off,strong_on,strong_off")
    parser.add_argument(
        "--trial-timeout-s",
        type=int,
        default=0,
        help="Abort a single trial after this many seconds; 0 disables the timeout.",
    )
    parser.add_argument(
        "--resume",
        "--resume-existing",
        action="store_true",
        help=(
            "Reuse completed row_*.json artifacts in --output-dir/rows and retry "
            "missing, errored, or artifact-incomplete trials."
        ),
    )
    parser.add_argument(
        "--mode",
        "--benchmark-mode",
        choices=["B", "B_prime", "C", "retrieval_only"],
        default="C",
        dest="mode",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.repeats < 1:
        raise SystemExit("--repeats must be >= 1")
    conditions = _parse_conditions(args.conditions)
    cases_path = Path(args.cases).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    workspace_root = Path(args.workspace_root).expanduser().resolve()
    rows_dir = output_dir / "rows"
    output_dir.mkdir(parents=True, exist_ok=True)
    rows_dir.mkdir(parents=True, exist_ok=True)

    cases = _select_cases(load_cases(cases_path), args.case_limit)
    cases_sha256 = compute_cases_sha256(cases_path)
    rows: list[dict[str, Any]] = []
    trial_index = 0

    for condition in conditions:
        host = MODEL_HOSTS.get(str(condition["model"]))
        if not host:
            raise SystemExit(f"No Ollama host configured for model: {condition['model']}")
        os.environ["OLLAMA_HOST"] = host
        os.environ["OLLAMA_BASE_URL"] = host
        os.environ["OLLAMA_MODEL"] = str(condition["model"])
        os.environ["OLLAMA_REASONING"] = "false"
        os.environ["LLM_PROVIDER"] = "ollama"
        os.environ["LLM_MODEL"] = str(condition["model"])

        for repeat in range(1, args.repeats + 1):
            for case in cases:
                trial_index += 1
                started = time.perf_counter()
                row: dict[str, Any]
                if args.resume:
                    existing_row = _load_existing_row(
                        rows_dir,
                        trial_index=trial_index,
                        condition_name=str(condition["condition"]),
                    )
                    if existing_row is not None and _resume_row_is_reusable(
                        existing_row,
                        case=case,
                        condition=condition,
                        repeat=repeat,
                        trial_index=trial_index,
                        benchmark_mode=args.mode,
                        cases_sha256=cases_sha256,
                    ):
                        rows.append(existing_row)
                        print(
                            "[resume] skip "
                            f"row_{trial_index:04d}_{condition['condition']} "
                            f"{case.get('case_id', '')}",
                            flush=True,
                        )
                        continue

                try:
                    with _trial_timeout(args.trial_timeout_s):
                        result = run_single_trial(
                            case=case,
                            condition=condition,
                            repeat=repeat,
                            trial_index=trial_index,
                            workspace_root=workspace_root,
                            temperature=0.0,
                            benchmark_mode=args.mode,
                            cases_sha256=cases_sha256,
                        )
                    row = _serialize_result(result)
                except Exception as exc:
                    row = {
                        "case_id": case.get("case_id", ""),
                        "category": case.get("category", ""),
                        "lr_pair": case.get("lr_pair", ""),
                        "condition": condition["condition"],
                        "model": condition["model"],
                        "model_strength": condition["model_strength"],
                        "skill_on": bool(condition["skill_on"]),
                        "repeat": repeat,
                        "trial_index": trial_index,
                        "benchmark_mode": args.mode,
                        "cases_sha256": cases_sha256,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                papers_exists = _recover_papers_artifact(row, benchmark_mode=args.mode)
                if args.mode == "retrieval_only":
                    should_run_handoff = papers_exists and not row.get("error")
                    use_filtered_papers_path = True
                else:
                    should_run_handoff = papers_exists or not row.get("error")
                    use_filtered_papers_path = False
                if should_run_handoff:
                    try:
                        row.update(
                            _run_handoff(
                                row,
                                case,
                                use_filtered_papers_path=use_filtered_papers_path,
                            )
                        )
                    except Exception as exc:
                        handoff_error = f"{type(exc).__name__}: {exc}"
                        if row.get("error"):
                            row["handoff_error"] = handoff_error
                        else:
                            row["error"] = handoff_error
                row["latency_s"] = row.get("latency_s", round(time.perf_counter() - started, 3))
                for key in [
                    "candidate_unique_papers",
                    "direct_papers",
                    "context_papers",
                    "disease_only_papers",
                    "rejected_papers",
                    "handoff_papers",
                ]:
                    row.setdefault(key, 0)
                rows.append(row)
                _write_json(_row_path(rows_dir, trial_index, str(condition["condition"])), row)

    summary = {
        "generated_at": _utc_now(),
        "cases": str(cases_path),
        "case_count": len(cases),
        "repeats": args.repeats,
        "trial_count": len(rows),
        "error_count": sum(1 for row in rows if row.get("error")),
        "benchmark_mode": args.mode,
        "conditions": [condition["condition"] for condition in conditions],
        "by_condition": _summarize_by_condition(rows),
        "rows": rows,
    }
    _write_json(output_dir / "summary.json", summary)
    _write_csv(output_dir / "summary.csv", rows)
    _write_results_ko(output_dir / "RESULTS_KO.md", rows)
    return 1 if summary["error_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
