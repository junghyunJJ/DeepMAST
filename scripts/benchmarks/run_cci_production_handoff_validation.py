"""Validate production SEARCHER -> INTERPRETER handoff artifacts for CCI cases."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.benchmarks.benchmark_llm_config import (
    add_benchmark_llm_args,
    apply_benchmark_llm_config,
)
from scripts.benchmarks.run_cci_retrieval_bucket_benchmark import _load_cases
from scripts.benchmarks.run_cci_unified_retrieval_bucket_benchmark import _build_unified_context
from src.agents.deep_interpreter.tools.literature import search_literature_dynamic
from src.agents.deep_interpreter.tools.literature_handoff import (
    CONTEXT_BUCKET,
    DIRECT_BUCKET,
    create_literature_handoff,
)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _select_cases(cases: list[dict[str, Any]], case_limit: int) -> list[dict[str, Any]]:
    if case_limit <= 0:
        return cases
    return cases[:case_limit]


def _parse_bool_arg(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"expected a boolean value, got {value!r}")


def _validate_handoff(run_dir: Path, cap: int) -> dict[str, Any]:
    raw_path = run_dir / "papers_raw.json"
    candidates_path = run_dir / "citation_candidates.json"
    handoff_path = run_dir / "papers.json"
    missing = [path.name for path in [raw_path, candidates_path, handoff_path] if not path.exists()]
    if missing:
        raise RuntimeError(f"missing artifacts: {', '.join(missing)}")

    raw = _read_json(raw_path)
    candidates = _read_json(candidates_path)
    handoff = _read_json(handoff_path)
    handoff_papers = handoff.get("papers", [])
    excluded = [
        paper.get("pmid") or paper.get("title")
        for paper in handoff_papers
        if paper.get("evidence_bucket") not in {DIRECT_BUCKET, CONTEXT_BUCKET}
    ]
    if excluded:
        raise RuntimeError(f"excluded bucket found in filtered handoff: {excluded[:3]}")
    if len(handoff_papers) > cap:
        raise RuntimeError(f"handoff cap exceeded: {len(handoff_papers)} > {cap}")

    counts = candidates.get("counts", {})
    return {
        "raw_papers": len(raw.get("papers", []) or []),
        "candidate_unique_papers": candidates.get("source", {}).get("unique_papers", 0),
        "direct_papers": counts.get(DIRECT_BUCKET, 0),
        "context_papers": counts.get(CONTEXT_BUCKET, 0),
        "disease_only_papers": counts.get("disease_only_background", 0),
        "rejected_papers": counts.get("rejected_weak_evidence", 0),
        "handoff_papers": len(handoff_papers),
        "handoff_direct_papers": sum(
            1 for paper in handoff_papers if paper.get("evidence_bucket") == DIRECT_BUCKET
        ),
        "handoff_context_papers": sum(
            1 for paper in handoff_papers if paper.get("evidence_bucket") == CONTEXT_BUCKET
        ),
    }


def _write_results_ko(path: Path, row: dict[str, Any]) -> None:
    lines = [
        "# CCI Production Handoff Validation 결과",
        "",
        f"- 생성 시각: {_utc_now()}",
        f"- case_count: {row['case_count']}",
        f"- pair_count: {row['pair_count']}",
        f"- max_results: {row['max_results']}",
        f"- cap: {row['cap']}",
        f"- status: {'PASS' if row['error'] == '' else 'FAIL'}",
        "",
        "## Artifact 확인",
        "",
        "- `papers_raw.json`: raw SEARCHER retrieval",
        "- `citation_candidates.json`: bucket audit artifact",
        "- `papers.json`: INTERPRETER-facing filtered handoff",
        "",
        "## 핵심 요약",
        "",
        "| raw papers | direct | context | disease-only | rejected | handoff papers |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
        (
            f"| {row['raw_papers']} | {row['direct_papers']} | "
            f"{row['context_papers']} | {row['disease_only_papers']} | "
            f"{row['rejected_papers']} | {row['handoff_papers']} |"
        ),
        "",
        "## 최종 결론",
        "",
    ]
    if row["error"]:
        lines.append(f"FAIL: {row['error']}")
    else:
        lines.append(
            "`papers_raw.json -> citation_candidates.json -> papers.json` production handoff가 통과했다. "
            "filtered `papers.json`에는 `direct_lr_evidence`와 `receptor_pathway_context_evidence`만 남는다."
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True)
    parser.add_argument(
        "--output-dir",
        default="docs/benchmarks/lr_retrieval_relevance/results/cci_production_handoff_validation",
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--case-limit", type=int, default=0)
    parser.add_argument("--max-results", type=int, default=100)
    parser.add_argument("--max-iterations", type=int, default=1)
    parser.add_argument("--cap", type=int, default=40)
    parser.add_argument("--enforce-disease-match", type=_parse_bool_arg, default=True)
    parser.add_argument("--rerank-mode", choices=["off", "llm"], default="off")
    parser.add_argument("--sort-by-journal-quality", type=_parse_bool_arg, default=True)
    parser.add_argument("--coverage-weighted-sort", type=_parse_bool_arg, default=True)
    parser.add_argument("--enable-lr-pair-queries", type=_parse_bool_arg, default=True)
    add_benchmark_llm_args(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    llm_config = apply_benchmark_llm_config(args)
    cases_path = Path(args.cases).expanduser().resolve()
    cases = _select_cases(_load_cases(cases_path), args.case_limit)
    context = _build_unified_context(cases)
    run_dir = Path(args.output_dir).expanduser().resolve() / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        run_dir / "run_config.json",
        {
            "run_id": args.run_id,
            "cases": str(cases_path),
            "case_count": len(cases),
            "case_limit": args.case_limit,
            "max_results": args.max_results,
            "max_iterations": args.max_iterations,
            "cap": args.cap,
            "enforce_disease_match": args.enforce_disease_match,
            "rerank_mode": args.rerank_mode,
            "sort_by_journal_quality": args.sort_by_journal_quality,
            "coverage_weighted_sort": args.coverage_weighted_sort,
            "enable_lr_pair_queries": args.enable_lr_pair_queries,
            "created_at_utc": _utc_now(),
            "llm_provider": llm_config["llm_provider"],
            "llm_model": llm_config["llm_model"],
            "ollama_base_url": llm_config["ollama_base_url"],
            "ollama_reasoning": llm_config["ollama_reasoning"],
        },
    )
    _write_json(run_dir / "unified_search_context.json", context)
    _write_json(run_dir / "lr_pairs_search.json", {"pairs": context["pairs"], "count": len(context["pairs"])})

    row: dict[str, Any] = {
        "run_id": args.run_id,
        "case_count": len(cases),
        "pair_count": len(context["pairs"]),
        "max_results": args.max_results,
        "max_iterations": args.max_iterations,
        "cap": args.cap,
        "error": "",
    }
    t0 = time.perf_counter()
    try:
        search_payload: dict[str, Any] = {
            "genes": context["genes"],
            "pathways": context["pathways"],
            "celltypes": context["celltypes"],
            "disease": context["disease"],
            "max_results": args.max_results,
            "max_iterations": args.max_iterations,
            "output_path": "papers_raw.json",
            "data_dir": str(run_dir),
            "enforce_disease_match": args.enforce_disease_match,
            "rerank_mode": args.rerank_mode,
            "sort_by_journal_quality": args.sort_by_journal_quality,
            "coverage_weighted_sort": args.coverage_weighted_sort,
            "enable_lr_pair_queries": args.enable_lr_pair_queries,
        }
        if llm_config["llm_provider"]:
            search_payload["llm_provider"] = llm_config["llm_provider"]
        search_literature_dynamic.invoke(search_payload)
        create_literature_handoff.invoke(
            {
                "raw_papers_path": "papers_raw.json",
                "output_path": "papers.json",
                "citation_candidates_path": "citation_candidates.json",
                "data_dir": str(run_dir),
                "disease": context["disease"],
                "lr_pairs": context["pairs"],
                "pathways": context["pathways"],
                "celltypes": context["celltypes"],
                "cap": args.cap,
            }
        )
        row.update(_validate_handoff(run_dir, args.cap))
    except Exception as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"
    row["latency_s"] = round(time.perf_counter() - t0, 3)
    for key in [
        "raw_papers",
        "candidate_unique_papers",
        "direct_papers",
        "context_papers",
        "disease_only_papers",
        "rejected_papers",
        "handoff_papers",
        "handoff_direct_papers",
        "handoff_context_papers",
    ]:
        row.setdefault(key, 0)

    _write_json(run_dir / "row.json", row)
    _write_json(run_dir / "summary.json", {"rows": [row], "error": row["error"]})
    _write_csv(run_dir / "summary.csv", [row])
    _write_results_ko(run_dir / "RESULTS_KO.md", row)
    print(
        f"saved={run_dir} status={'PASS' if row['error'] == '' else 'FAIL'} "
        f"raw={row['raw_papers']} handoff={row['handoff_papers']} error={row['error']}",
        flush=True,
    )
    return 0 if row["error"] == "" else 1


if __name__ == "__main__":
    raise SystemExit(main())
