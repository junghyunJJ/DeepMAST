"""Run unified-pool LR evidence bucket benchmark for CCI cases.

This benchmark approximates the production SEARCHER handoff shape: all CCI
benchmark LR pairs are searched together as one shared retrieval pool, then the
saved papers are graded against each pair and collapsed to a unique-paper
direct/context handoff simulation.
"""

from __future__ import annotations

import argparse
import csv
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
from scripts.benchmarks.run_cci_retrieval_bucket_benchmark import (
    _load_cases,
    _load_grader_module,
    _read_json,
    _write_json,
)
from src.agents.deep_interpreter.tools.literature import search_literature_dynamic


BUCKET_RANK = {
    "direct_lr_evidence": 3,
    "receptor_pathway_context_evidence": 2,
    "disease_only_background": 1,
    "rejected_weak_evidence": 0,
}


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in values if item))


def _paper_key(candidate: dict[str, Any]) -> str:
    pmid = str(candidate.get("pmid") or "").strip()
    if pmid:
        return f"pmid:{pmid}"
    title = " ".join(str(candidate.get("title") or "").lower().split())
    doi = str(candidate.get("doi") or "").lower().strip()
    return f"doi:{doi}" if doi else f"title:{title}"


def _build_unified_context(cases: list[dict[str, Any]]) -> dict[str, Any]:
    genes: list[str] = []
    pathways: list[str] = []
    celltypes: list[str] = []
    pairs: list[dict[str, Any]] = []
    for case in cases:
        genes.extend(case["genes"])
        pathways.extend(case["pathways"])
        celltypes.extend(case["celltypes"])
        pairs.append(
            {
                "case_id": case["case_id"],
                "category": case["category"],
                "ligand": case["ligand"],
                "receptor": case["receptor"],
                "lr_pair": case["lr_pair"],
                "pathways": case["pathways"],
                "celltypes": case["celltypes"],
            }
        )
    return {
        "genes": _unique(genes),
        "pathways": sorted(set(pathways)),
        "celltypes": sorted(set(celltypes)),
        "disease": "breast cancer",
        "pairs": pairs,
    }


def _grade_pairs(
    *,
    grader: Any,
    payload: dict[str, Any],
    papers_path: Path,
    context: dict[str, Any],
) -> dict[str, Any]:
    pair_results = []
    paper_support: dict[str, dict[str, Any]] = {}
    paper_order: dict[str, int] = {}
    for index, paper in enumerate(payload.get("papers", []) or []):
        if not isinstance(paper, dict):
            continue
        key = _paper_key(paper)
        paper_order.setdefault(key, index)
        paper_support.setdefault(
            key,
            {
                "pmid": str(paper.get("pmid") or "").strip(),
                "title": str(paper.get("title") or "").strip(),
                "doi": str(paper.get("doi") or "").strip(),
                "best_bucket": "rejected_weak_evidence",
                "direct_pairs": [],
                "context_pairs": [],
                "disease_only_pairs": [],
                "rejected_pairs": [],
                "matched_terms_by_pair": {},
            },
        )

    for pair in context["pairs"]:
        result = grader.grade_papers(
            payload,
            papers_json=papers_path,
            ligand=pair["ligand"],
            receptor=pair["receptor"],
            disease=context["disease"],
            pathways=pair["pathways"],
            celltypes=pair["celltypes"],
        )
        pair_results.append(
            {
                "case_id": pair["case_id"],
                "lr_pair": pair["lr_pair"],
                "ligand": pair["ligand"],
                "receptor": pair["receptor"],
                "counts": result["counts"],
            }
        )
        for bucket, candidates in result.get("buckets", {}).items():
            for candidate in candidates:
                key = _paper_key(candidate)
                support = paper_support.setdefault(
                    key,
                    {
                        "pmid": str(candidate.get("pmid") or "").strip(),
                        "title": str(candidate.get("title") or "").strip(),
                        "doi": str(candidate.get("doi") or "").strip(),
                        "best_bucket": "rejected_weak_evidence",
                        "direct_pairs": [],
                        "context_pairs": [],
                        "disease_only_pairs": [],
                        "rejected_pairs": [],
                        "matched_terms_by_pair": {},
                    },
                )
                if BUCKET_RANK[bucket] > BUCKET_RANK[support["best_bucket"]]:
                    support["best_bucket"] = bucket
                pair_label = pair["lr_pair"]
                if bucket == "direct_lr_evidence":
                    support["direct_pairs"].append(pair_label)
                elif bucket == "receptor_pathway_context_evidence":
                    support["context_pairs"].append(pair_label)
                elif bucket == "disease_only_background":
                    support["disease_only_pairs"].append(pair_label)
                else:
                    support["rejected_pairs"].append(pair_label)
                if bucket in {
                    "direct_lr_evidence",
                    "receptor_pathway_context_evidence",
                }:
                    support["matched_terms_by_pair"][pair_label] = candidate.get(
                        "matched_terms", {}
                    )

    papers = list(paper_support.values())
    counts = {
        bucket: sum(1 for paper in papers if paper["best_bucket"] == bucket)
        for bucket in BUCKET_RANK
    }
    direct_pairs = sorted(
        {
            pair
            for paper in papers
            for pair in paper.get("direct_pairs", [])
        }
    )
    context_pairs = sorted(
        {
            pair
            for paper in papers
            for pair in paper.get("context_pairs", [])
        }
    )
    eligible = [
        paper
        for paper in papers
        if paper["best_bucket"]
        in {"direct_lr_evidence", "receptor_pathway_context_evidence"}
    ]

    def sort_key(paper: dict[str, Any]) -> tuple[int, int, int]:
        return (
            -BUCKET_RANK[paper["best_bucket"]],
            -len(set(paper.get("direct_pairs", [])) | set(paper.get("context_pairs", []))),
            paper_order.get(_paper_key(paper), 10**9),
        )

    return {
        "schema_version": "unified_lr_bucket_v1",
        "source": {
            "papers_json": str(papers_path),
            "total_papers": len(payload.get("papers", []) or []),
            "unique_papers": len(papers),
        },
        "inputs": {
            "disease": context["disease"],
            "genes": context["genes"],
            "pathways": context["pathways"],
            "celltypes": context["celltypes"],
            "pairs": context["pairs"],
        },
        "counts_by_best_paper_bucket": counts,
        "pair_results": pair_results,
        "pair_coverage": {
            "direct_pairs": direct_pairs,
            "context_pairs": context_pairs,
            "direct_pair_count": len(direct_pairs),
            "context_pair_count": len(context_pairs),
            "direct_or_context_pair_count": len(set(direct_pairs) | set(context_pairs)),
            "total_pairs": len(context["pairs"]),
        },
        "eligible_papers_ranked": sorted(eligible, key=sort_key),
        "papers_by_best_bucket": {
            bucket: sorted(
                [paper for paper in papers if paper["best_bucket"] == bucket],
                key=sort_key,
            )
            for bucket in BUCKET_RANK
        },
    }


def _handoff_summary(bucketed: dict[str, Any], cap: int) -> dict[str, Any]:
    selected = bucketed.get("eligible_papers_ranked", [])[:cap]
    direct = [paper for paper in selected if paper["best_bucket"] == "direct_lr_evidence"]
    context = [
        paper
        for paper in selected
        if paper["best_bucket"] == "receptor_pathway_context_evidence"
    ]
    pairs = sorted(
        {
            pair
            for paper in selected
            for pair in [*paper.get("direct_pairs", []), *paper.get("context_pairs", [])]
        }
    )
    direct_pairs = sorted({pair for paper in selected for pair in paper.get("direct_pairs", [])})
    return {
        "cap": cap,
        "selected_papers": len(selected),
        "direct_papers": len(direct),
        "context_papers": len(context),
        "covered_pairs": len(pairs),
        "direct_pairs": len(direct_pairs),
        "pair_labels": pairs,
    }


def _row_from_bucketed(
    *,
    max_results: int,
    max_iterations: int,
    context: dict[str, Any],
    papers_path: Path,
    candidates_path: Path,
    bucketed: dict[str, Any] | None,
    latency_s: float,
    error: str | None,
    caps: list[int],
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "max_results": max_results,
        "max_iterations": max_iterations,
        "pair_count": len(context["pairs"]),
        "gene_count": len(context["genes"]),
        "pathway_count": len(context["pathways"]),
        "celltype_count": len(context["celltypes"]),
        "latency_s": round(latency_s, 3),
        "papers_path": str(papers_path),
        "unified_candidates_path": str(candidates_path),
        "error": error or "",
    }
    if not bucketed:
        for name in [
            "source_papers",
            "unique_papers",
            "direct_papers",
            "context_papers",
            "disease_only_papers",
            "rejected_papers",
            "eligible_papers",
            "direct_pair_count",
            "context_pair_count",
            "direct_or_context_pair_count",
        ]:
            row[name] = 0
        for cap in caps:
            row[f"cap_{cap}_selected_papers"] = 0
            row[f"cap_{cap}_covered_pairs"] = 0
            row[f"cap_{cap}_direct_pairs"] = 0
        return row

    counts = bucketed["counts_by_best_paper_bucket"]
    coverage = bucketed["pair_coverage"]
    row.update(
        {
            "source_papers": bucketed["source"]["total_papers"],
            "unique_papers": bucketed["source"]["unique_papers"],
            "direct_papers": counts["direct_lr_evidence"],
            "context_papers": counts["receptor_pathway_context_evidence"],
            "disease_only_papers": counts["disease_only_background"],
            "rejected_papers": counts["rejected_weak_evidence"],
            "eligible_papers": counts["direct_lr_evidence"]
            + counts["receptor_pathway_context_evidence"],
            "direct_pair_count": coverage["direct_pair_count"],
            "context_pair_count": coverage["context_pair_count"],
            "direct_or_context_pair_count": coverage["direct_or_context_pair_count"],
        }
    )
    for cap in caps:
        summary = _handoff_summary(bucketed, cap)
        row[f"cap_{cap}_selected_papers"] = summary["selected_papers"]
        row[f"cap_{cap}_direct_papers"] = summary["direct_papers"]
        row[f"cap_{cap}_context_papers"] = summary["context_papers"]
        row[f"cap_{cap}_covered_pairs"] = summary["covered_pairs"]
        row[f"cap_{cap}_direct_pairs"] = summary["direct_pairs"]
    return row


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_report(path: Path, rows: list[dict[str, Any]], caps: list[int]) -> None:
    lines = [
        "# CCI Unified Retrieval Bucket Benchmark",
        "",
        f"- generated_at_utc: {_utc_now()}",
        f"- records: {len(rows)}",
        "",
        "| max_results | papers | direct papers | context papers | eligible papers | pair coverage | cap40 selected | cap40 pair coverage |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        cap = 40 if 40 in caps else caps[0]
        lines.append(
            "| "
            f"{row['max_results']} | "
            f"{row['source_papers']} | "
            f"{row['direct_papers']} | "
            f"{row['context_papers']} | "
            f"{row['eligible_papers']} | "
            f"{row['direct_or_context_pair_count']}/{row['pair_count']} | "
            f"{row[f'cap_{cap}_selected_papers']} | "
            f"{row[f'cap_{cap}_covered_pairs']}/{row['pair_count']} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_results_ko(path: Path, rows: list[dict[str, Any]], caps: list[int]) -> None:
    cap = 40 if 40 in caps else caps[0]
    best = max(
        rows,
        key=lambda row: (
            int(row.get(f"cap_{cap}_covered_pairs", 0) or 0),
            int(row.get(f"cap_{cap}_selected_papers", 0) or 0),
        ),
    ) if rows else {}
    lines = [
        "# CCI Unified Retrieval Bucket Sweep 결과",
        "",
        f"- 생성 시각: {_utc_now()}",
        f"- records: {len(rows)}",
        "- 실행 목적: 30개 LR pair를 하나의 shared raw pool로 검색했을 때 production handoff 후보 분포 확인",
        "",
        "## 핵심 요약",
        "",
        "| max_results | raw papers | direct | context | eligible | pair coverage | cap40 selected | cap40 pair coverage |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            "| "
            f"{row['max_results']} | "
            f"{row['source_papers']} | "
            f"{row['direct_papers']} | "
            f"{row['context_papers']} | "
            f"{row['eligible_papers']} | "
            f"{row['direct_or_context_pair_count']}/{row['pair_count']} | "
            f"{row[f'cap_{cap}_selected_papers']} | "
            f"{row[f'cap_{cap}_covered_pairs']}/{row['pair_count']} |"
        )
    lines.extend(
        [
            "",
            "## 최종 결론",
            "",
        ]
    )
    if best:
        lines.append(
            f"qwen 조건에서 가장 좋은 cap{cap} handoff 후보는 max_results={best['max_results']}이다. "
            f"이 설정은 cap{cap}에서 {best[f'cap_{cap}_covered_pairs']}/{best['pair_count']} LR pair를 direct/context evidence로 커버했다."
        )
    else:
        lines.append("성공 row가 없어 결론을 낼 수 없다.")
    path.write_text("\n".join(lines), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, help="Path to cci_full_cases.json")
    parser.add_argument(
        "--output-dir",
        default="docs/benchmarks/lr_retrieval_relevance/results/cci_unified_retrieval_bucket_sweep",
    )
    parser.add_argument("--max-results", nargs="+", type=int, default=[30, 60, 100])
    parser.add_argument("--caps", nargs="+", type=int, default=[40])
    parser.add_argument("--max-iterations", type=int, default=1)
    add_benchmark_llm_args(parser)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    llm_config = apply_benchmark_llm_config(args)
    cases_path = Path(args.cases).expanduser().resolve()
    cases = _load_cases(cases_path)
    context = _build_unified_context(cases)
    grader = _load_grader_module()

    run_id = args.run_id or f"run_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
    run_dir = Path(args.output_dir).expanduser().resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        run_dir / "run_config.json",
        {
            "run_id": run_id,
            "cases": str(cases_path),
            "case_count": len(cases),
            "max_results": args.max_results,
            "caps": args.caps,
            "max_iterations": args.max_iterations,
            "created_at_utc": _utc_now(),
            "context_counts": {
                "pairs": len(context["pairs"]),
                "genes": len(context["genes"]),
                "pathways": len(context["pathways"]),
                "celltypes": len(context["celltypes"]),
            },
            "llm_provider": llm_config["llm_provider"],
            "llm_model": llm_config["llm_model"],
            "ollama_base_url": llm_config["ollama_base_url"],
            "ollama_reasoning": llm_config["ollama_reasoning"],
        },
    )
    _write_json(run_dir / "unified_search_context.json", context)

    rows: list[dict[str, Any]] = []
    for index, max_results in enumerate(args.max_results, start=1):
        case_dir = run_dir / f"max_{max_results}"
        papers_path = case_dir / "papers.json"
        candidates_path = case_dir / "unified_citation_candidates.json"
        pair_results_path = case_dir / "pair_citation_counts.json"
        row_path = case_dir / "row.json"
        if row_path.exists() and not args.overwrite:
            row = _read_json(row_path)
            rows.append(row)
            print(f"[{index}/{len(args.max_results)}] skip max={max_results}", flush=True)
            continue

        case_dir.mkdir(parents=True, exist_ok=True)
        _write_json(
            case_dir / "lr_pairs_search.json",
            {"pairs": context["pairs"], "count": len(context["pairs"])},
        )
        t0 = time.perf_counter()
        error = None
        bucketed = None
        try:
            invoke_payload = {
                "genes": context["genes"],
                "pathways": context["pathways"],
                "celltypes": context["celltypes"],
                "disease": context["disease"],
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
            bucketed = _grade_pairs(
                grader=grader,
                payload=payload,
                papers_path=papers_path,
                context=context,
            )
            _write_json(candidates_path, bucketed)
            _write_json(pair_results_path, bucketed["pair_results"])
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        latency_s = time.perf_counter() - t0
        row = _row_from_bucketed(
            max_results=max_results,
            max_iterations=args.max_iterations,
            context=context,
            papers_path=papers_path,
            candidates_path=candidates_path,
            bucketed=bucketed,
            latency_s=latency_s,
            error=error,
            caps=args.caps,
        )
        _write_json(row_path, row)
        rows.append(row)
        print(
            f"[{index}/{len(args.max_results)}] max={max_results} "
            f"papers={row['source_papers']} direct_papers={row['direct_papers']} "
            f"context_papers={row['context_papers']} "
            f"pair_coverage={row['direct_or_context_pair_count']}/{row['pair_count']} "
            f"error={'yes' if error else 'no'} latency={latency_s:.1f}s",
            flush=True,
        )

    _write_json(run_dir / "summary.json", {"rows": rows})
    _write_csv(run_dir / "summary.csv", rows)
    _write_report(run_dir / "RESULTS.md", rows, args.caps)
    _write_results_ko(run_dir / "RESULTS_KO.md", rows, args.caps)
    (Path(args.output_dir).expanduser().resolve() / "latest_run.txt").write_text(
        run_id,
        encoding="utf-8",
    )
    print(f"Saved benchmark run to: {run_dir}")
    return 1 if any(row.get("error") for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
