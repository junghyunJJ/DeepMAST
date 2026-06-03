"""Run retrieval-only LR evidence bucket benchmark for CCI cases.

This benchmark is intentionally outside the production Deep Interpreter flow.
It sweeps search_literature_dynamic max_results values, grades each saved paper
set with the biomedical-literature-search citation bucket scorer, and simulates
small interpreter handoff caps using direct + context evidence only.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sys
import time
import uuid
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
from src.agents.deep_interpreter.tools.literature import search_literature_dynamic


BUCKETS = (
    "direct_lr_evidence",
    "receptor_pathway_context_evidence",
    "disease_only_background",
    "rejected_weak_evidence",
)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_grader_module() -> Any:
    grader_path = (
        PROJECT_ROOT
        / "skills"
        / "biomedical-literature-search"
        / "scripts"
        / "grade_citation_candidates.py"
    )
    spec = importlib.util.spec_from_file_location("grade_citation_candidates", grader_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not import grader from {grader_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _split_gene_symbol(symbol: str) -> list[str]:
    return [part.strip().upper() for part in str(symbol).split("_") if part.strip()]


def _derive_disease_context(bundle: dict[str, Any]) -> str:
    tissue_context = str(bundle.get("tissue_context", "") or "").strip()
    if "breast cancer" in tissue_context.lower():
        return "breast cancer"
    if tissue_context:
        return tissue_context
    diseases = bundle.get("disease_associations") or []
    if diseases:
        return str(diseases[0]).strip()
    return "cancer"


def _normalize_case(case: dict[str, Any]) -> dict[str, Any]:
    bundle = case.get("input_bundle") or {}
    ligand = str(bundle.get("ligand", "")).strip().upper()
    receptor = str(bundle.get("receptor", "")).strip().upper()
    genes = list(dict.fromkeys(_split_gene_symbol(ligand) + _split_gene_symbol(receptor)))
    pathways = [
        str(item).strip()
        for item in (bundle.get("pathway_associations") or [])
        if str(item).strip()
    ]
    celltypes = sorted(
        {
            str(item).strip()
            for item in (bundle.get("ligand_cell_types") or [])
            + (bundle.get("receptor_cell_types") or [])
            if str(item).strip()
        }
    )
    return {
        "case_id": str(case.get("case_id") or f"{ligand}_{receptor}"),
        "category": str(case.get("category") or ""),
        "ligand": ligand,
        "receptor": receptor,
        "lr_pair": str(case.get("lr_pair") or f"{ligand}-{receptor}"),
        "genes": genes,
        "pathways": pathways,
        "celltypes": celltypes,
        "disease": _derive_disease_context(bundle),
        "raw_case": case,
    }


def _load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("CCI cases JSON must be a list")
    cases = [_normalize_case(case) for case in payload if isinstance(case, dict)]
    for case in cases:
        if not case["ligand"] or not case["receptor"]:
            raise ValueError(f"Missing ligand/receptor in case {case['case_id']}")
    return cases


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _selected_counts(
    grader: Any,
    bucketed: dict[str, Any],
    cap: int,
) -> dict[str, int]:
    direct = bucketed["buckets"].get("direct_lr_evidence", [])
    context = bucketed["buckets"].get("receptor_pathway_context_evidence", [])
    ordered_direct = grader._ordered_candidates(direct)
    ordered_context = grader._ordered_candidates(context)
    selected = [*ordered_direct, *ordered_context][:cap]
    direct_ids = {id(item) for item in ordered_direct}
    return {
        "total": len(selected),
        "direct": sum(1 for item in selected if id(item) in direct_ids),
        "context": sum(1 for item in selected if id(item) not in direct_ids),
    }


def _row_from_result(
    *,
    case: dict[str, Any],
    max_results: int,
    max_iterations: int,
    papers_path: Path,
    candidates_path: Path,
    bucketed: dict[str, Any] | None,
    latency_s: float,
    error: str | None,
    grader: Any,
    caps: list[int],
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "case_id": case["case_id"],
        "category": case["category"],
        "lr_pair": case["lr_pair"],
        "ligand": case["ligand"],
        "receptor": case["receptor"],
        "disease": case["disease"],
        "max_results": max_results,
        "max_iterations": max_iterations,
        "latency_s": round(latency_s, 3),
        "papers_path": str(papers_path),
        "citation_candidates_path": str(candidates_path),
        "error": error or "",
    }
    if not bucketed:
        for bucket in BUCKETS:
            row[bucket] = 0
        row["source_papers"] = 0
        row["unique_papers"] = 0
        row["eligible_direct_context"] = 0
        for cap in caps:
            row[f"cap_{cap}_total"] = 0
            row[f"cap_{cap}_direct"] = 0
            row[f"cap_{cap}_context"] = 0
        return row

    counts = bucketed.get("counts", {})
    for bucket in BUCKETS:
        row[bucket] = int(counts.get(bucket, 0))
    row["source_papers"] = int(bucketed.get("source", {}).get("total_papers", 0))
    row["unique_papers"] = int(bucketed.get("source", {}).get("unique_papers", 0))
    row["eligible_direct_context"] = (
        row["direct_lr_evidence"] + row["receptor_pathway_context_evidence"]
    )
    for cap in caps:
        selected = _selected_counts(grader, bucketed, cap)
        row[f"cap_{cap}_total"] = selected["total"]
        row[f"cap_{cap}_direct"] = selected["direct"]
        row[f"cap_{cap}_context"] = selected["context"]
    return row


def _aggregate(rows: list[dict[str, Any]], caps: list[int]) -> dict[str, Any]:
    by_max: dict[str, dict[str, Any]] = {}
    for max_results in sorted({int(row["max_results"]) for row in rows}):
        group = [row for row in rows if int(row["max_results"]) == max_results]
        successful = [row for row in group if not row.get("error")]
        denom = len(successful) or 1
        stats: dict[str, Any] = {
            "records": len(group),
            "successful_records": len(successful),
            "failed_records": len(group) - len(successful),
        }
        for field in [
            "source_papers",
            "unique_papers",
            "direct_lr_evidence",
            "receptor_pathway_context_evidence",
            "disease_only_background",
            "rejected_weak_evidence",
            "eligible_direct_context",
        ]:
            stats[f"mean_{field}"] = round(
                sum(float(row.get(field, 0) or 0) for row in successful) / denom,
                3,
            )
        stats["cases_with_direct"] = sum(
            1 for row in successful if int(row.get("direct_lr_evidence", 0) or 0) > 0
        )
        stats["cases_with_direct_or_context"] = sum(
            1
            for row in successful
            if int(row.get("eligible_direct_context", 0) or 0) > 0
        )
        for cap in caps:
            stats[f"mean_cap_{cap}_total"] = round(
                sum(float(row.get(f"cap_{cap}_total", 0) or 0) for row in successful)
                / denom,
                3,
            )
            stats[f"mean_cap_{cap}_direct"] = round(
                sum(float(row.get(f"cap_{cap}_direct", 0) or 0) for row in successful)
                / denom,
                3,
            )
            stats[f"mean_cap_{cap}_context"] = round(
                sum(float(row.get(f"cap_{cap}_context", 0) or 0) for row in successful)
                / denom,
                3,
            )
        by_max[str(max_results)] = stats
    return by_max


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_report(path: Path, rows: list[dict[str, Any]], aggregate: dict[str, Any]) -> None:
    lines = [
        "# CCI Retrieval Bucket Benchmark",
        "",
        f"- generated_at_utc: {_utc_now()}",
        f"- records: {len(rows)}",
        "",
        "## Aggregate By max_results",
        "",
        "| max_results | ok | direct mean | context mean | eligible mean | cases direct | cases direct/context |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for max_results, stats in aggregate.items():
        lines.append(
            "| "
            f"{max_results} | "
            f"{stats['successful_records']}/{stats['records']} | "
            f"{stats['mean_direct_lr_evidence']} | "
            f"{stats['mean_receptor_pathway_context_evidence']} | "
            f"{stats['mean_eligible_direct_context']} | "
            f"{stats['cases_with_direct']} | "
            f"{stats['cases_with_direct_or_context']} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_results_ko(path: Path, rows: list[dict[str, Any]], aggregate: dict[str, Any]) -> None:
    lines = [
        "# CCI Retrieval Bucket Sweep 결과",
        "",
        f"- 생성 시각: {_utc_now()}",
        f"- records: {len(rows)}",
        "- 실행 목적: 각 LR pair를 개별 검색했을 때 direct/context evidence가 얼마나 확보되는지 확인",
        "",
        "## 핵심 요약",
        "",
        "| max_results | 성공 | direct 평균 | context 평균 | direct+context 평균 | direct 보유 case | direct/context 보유 case |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for max_results, stats in aggregate.items():
        lines.append(
            "| "
            f"{max_results} | "
            f"{stats['successful_records']}/{stats['records']} | "
            f"{stats['mean_direct_lr_evidence']} | "
            f"{stats['mean_receptor_pathway_context_evidence']} | "
            f"{stats['mean_eligible_direct_context']} | "
            f"{stats['cases_with_direct']} | "
            f"{stats['cases_with_direct_or_context']} |"
        )
    lines.extend(
        [
            "",
            "## 최종 결론",
            "",
            "이 결과는 production handoff 자체가 아니라 LR별 검색 민감도 진단이다. "
            "최종 운영 판단은 unified production handoff validation을 우선하고, "
            "이 sweep은 qwen과 GPT-4.1-mini의 query 생성 차이로 direct/context 후보 수가 얼마나 달라지는지 비교하는 보조 근거로 사용한다.",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, help="Path to cci_full_cases.json")
    parser.add_argument(
        "--output-dir",
        default="docs/benchmarks/lr_retrieval_relevance/results/cci_retrieval_bucket_sweep",
    )
    parser.add_argument(
        "--max-results",
        nargs="+",
        type=int,
        default=[30, 60, 100],
        help="search_literature_dynamic max_results values to sweep.",
    )
    parser.add_argument("--caps", nargs="+", type=int, default=[30, 40, 50])
    parser.add_argument("--max-iterations", type=int, default=1)
    add_benchmark_llm_args(parser)
    parser.add_argument("--limit", type=int, default=0, help="Limit number of cases for smoke runs.")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    llm_config = apply_benchmark_llm_config(args)
    cases_path = Path(args.cases).expanduser().resolve()
    cases = _load_cases(cases_path)
    if args.limit:
        cases = cases[: args.limit]
    grader = _load_grader_module()

    run_id = args.run_id or f"run_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
    run_dir = Path(args.output_dir).expanduser().resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    config = {
        "run_id": run_id,
        "cases": str(cases_path),
        "case_count": len(cases),
        "max_results": args.max_results,
        "caps": args.caps,
        "max_iterations": args.max_iterations,
        "created_at_utc": _utc_now(),
        "retrieval": {
            "tool": "search_literature_dynamic",
            "enable_lr_pair_queries": True,
            "coverage_weighted_sort": True,
            "enforce_disease_match": True,
            "llm_provider": llm_config["llm_provider"],
            "llm_model": llm_config["llm_model"],
            "ollama_base_url": llm_config["ollama_base_url"],
            "ollama_reasoning": llm_config["ollama_reasoning"],
        },
    }
    _write_json(run_dir / "run_config.json", config)

    rows: list[dict[str, Any]] = []
    total = len(cases) * len(args.max_results)
    completed = 0
    for case in cases:
        for max_results in args.max_results:
            completed += 1
            case_dir = run_dir / f"max_{max_results}" / case["case_id"]
            papers_path = case_dir / "papers.json"
            candidates_path = case_dir / "citation_candidates.json"
            report_path = case_dir / "final_report.md"
            row_path = case_dir / "row.json"
            if row_path.exists() and not args.overwrite:
                row = _read_json(row_path)
                rows.append(row)
                print(
                    f"[{completed}/{total}] skip max={max_results} case={case['case_id']}",
                    flush=True,
                )
                continue

            case_dir.mkdir(parents=True, exist_ok=True)
            _write_json(case_dir / "benchmark_case_normalized.json", case)
            _write_json(
                case_dir / "lr_pairs_search.json",
                {
                    "pairs": [
                        {
                            "ligand": case["ligand"],
                            "receptor": case["receptor"],
                        }
                    ],
                    "count": 1,
                },
            )

            t0 = time.perf_counter()
            error = None
            bucketed = None
            try:
                invoke_payload = {
                    "genes": case["genes"],
                    "pathways": case["pathways"],
                    "celltypes": case["celltypes"],
                    "disease": case["disease"],
                    "max_results": max_results,
                    "max_iterations": args.max_iterations,
                    "enforce_disease_match": True,
                    "output_path": "papers.json",
                    "data_dir": str(case_dir),
                    "enable_lr_pair_queries": True,
                    "coverage_weighted_sort": True,
                }
                if args.llm_provider:
                    invoke_payload["llm_provider"] = args.llm_provider
                search_result = search_literature_dynamic.invoke(invoke_payload)
                if not papers_path.exists():
                    if isinstance(search_result, dict) and isinstance(
                        search_result.get("papers"), list
                    ):
                        _write_json(papers_path, search_result)
                    else:
                        raise FileNotFoundError(papers_path)
                payload = _read_json(papers_path)
                bucketed = grader.grade_papers(
                    payload,
                    papers_json=papers_path,
                    ligand=case["ligand"],
                    receptor=case["receptor"],
                    disease=case["disease"],
                    pathways=case["pathways"],
                    celltypes=case["celltypes"],
                )
                _write_json(candidates_path, bucketed)
                grader.write_lr_benchmark_report_v2(bucketed, report_path)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"

            latency_s = time.perf_counter() - t0
            row = _row_from_result(
                case=case,
                max_results=max_results,
                max_iterations=args.max_iterations,
                papers_path=papers_path,
                candidates_path=candidates_path,
                bucketed=bucketed,
                latency_s=latency_s,
                error=error,
                grader=grader,
                caps=args.caps,
            )
            _write_json(row_path, row)
            rows.append(row)
            print(
                f"[{completed}/{total}] max={max_results} case={case['case_id']} "
                f"papers={row['source_papers']} direct={row['direct_lr_evidence']} "
                f"context={row['receptor_pathway_context_evidence']} "
                f"error={'yes' if error else 'no'} latency={latency_s:.1f}s",
                flush=True,
            )

    aggregate = _aggregate(rows, args.caps)
    _write_json(run_dir / "summary.json", {"rows": rows, "aggregate": aggregate})
    _write_csv(run_dir / "summary.csv", rows)
    _write_json(run_dir / "aggregate.json", aggregate)
    _write_report(run_dir / "RESULTS.md", rows, aggregate)
    _write_results_ko(run_dir / "RESULTS_KO.md", rows, aggregate)
    (Path(args.output_dir).expanduser().resolve() / "latest_run.txt").write_text(
        run_id,
        encoding="utf-8",
    )
    print(f"Saved benchmark run to: {run_dir}")
    return 1 if any(row.get("error") for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
