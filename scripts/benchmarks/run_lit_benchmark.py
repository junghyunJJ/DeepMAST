"""Run reproducibility and method benchmark for literature search tools.

This script evaluates literature-search methods on a fixed case set:
- dynamic_off: all filters/sort OFF (pure baseline)
- dynamic_lean: rerank OFF, disease filter OFF, SJR ON
- dynamic: disease filter ON, SJR ON
- dynamic_coverage_weighted: coverage+SJR greedy sort ON, disease filter OFF, SJR ON
- dynamic_filter_coverage_weighted: disease filter ON, coverage+SJR greedy sort ON, SJR ON
- dynamic_no_disease_filter: disease filtering disabled
- dynamic_no_sjr: SJR journal quality sorting disabled
- baseline_lit: search_literature (single-pass BioMCP search)
- baseline_eutils: search_pubmed_advanced (single-pass E-utilities query)

Use --shared-queries to cache iteration-0 queries from the reference method
(dynamic_lean) and replay them for all other methods, ensuring identical paper
pools for fair sort/filter strategy comparison.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.agents.deep_interpreter.tools.literature import (
    _calculate_coverage,
    search_literature,
    search_literature_dynamic,
)
from src.agents.deep_interpreter.tools.pubmed_eutils import (
    build_pubmed_query,
    search_pubmed_advanced,
)


REQUIRED_CASE_FIELDS = (
    "case_id",
    "genes",
    "pathways",
    "celltypes",
    "disease",
)

# SEARCHER-equivalent dynamic method variants. Module-level so both the
# `_run_case` dispatch and `_repeats_for` share a single source of truth
# (REV-A arch review NIT-B).
_DYNAMIC_METHODS: set[str] = {
    "dynamic",
    "dynamic_off",
    "dynamic_no_disease_filter",
    "dynamic_no_sjr",
    "dynamic_lean",
    "dynamic_coverage_weighted",
    "dynamic_filter_coverage_weighted",
}


def validate_case(case: dict[str, Any]) -> None:
    """Validate a benchmark case payload."""
    if not isinstance(case, dict):
        raise ValueError("Each case must be a JSON object")

    for field in REQUIRED_CASE_FIELDS:
        if field not in case:
            raise ValueError(f"Missing required field: {field}")

    for list_field in ("genes", "pathways", "celltypes"):
        value = case.get(list_field)
        if not isinstance(value, list):
            raise ValueError(f"{list_field} must be a list")
        if any(not isinstance(item, str) for item in value):
            raise ValueError(f"{list_field} must contain only strings")

    if not isinstance(case.get("case_id"), str) or not case["case_id"].strip():
        raise ValueError("case_id must be a non-empty string")

    if not isinstance(case.get("disease"), str) or not case["disease"].strip():
        raise ValueError("disease must be a non-empty string")

    notes = case.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise ValueError("notes must be a string if provided")


def load_cases(path: str) -> list[dict[str, Any]]:
    """Load and validate case set."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Cases file not found: {p}")

    payload = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Cases JSON must be an array")

    for case in payload:
        validate_case(case)

    return payload


def extract_pmids(papers: list[dict[str, Any]]) -> list[str]:
    """Extract deduplicated PMIDs preserving first-seen order."""
    seen: set[str] = set()
    ordered: list[str] = []
    for paper in papers:
        pmid_raw = paper.get("pmid")
        pmid = str(pmid_raw).strip() if pmid_raw is not None else ""
        if not pmid or pmid in seen:
            continue
        seen.add(pmid)
        ordered.append(pmid)
    return ordered


def _compact_papers(papers: list[dict[str, Any]], abstract_chars: int = 600) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for p in papers:
        abstract = str(p.get("abstract", "") or "")
        compact.append(
            {
                "pmid": str(p.get("pmid", "")).strip(),
                "title": str(p.get("title", "") or "")[:500],
                "abstract": abstract[:abstract_chars],
            }
        )
    return compact


def _build_eutils_query(case: dict[str, Any]) -> str:
    """Build a baseline E-utilities query from structured case inputs."""
    free_text = '"spatial transcriptomics"[tiab] OR "cell-cell interaction"[tiab]'
    return build_pubmed_query(
        genes=case["genes"][:5],
        pathways=case["pathways"][:5],
        celltypes=case["celltypes"][:5],
        disease=case["disease"],
        free_text=free_text,
    )


def _coverage_sufficient(
    coverage: dict[str, Any],
    target_gene: float = 0.6,
    target_pathway: float = 0.5,
    min_papers: int = 15,
) -> bool:
    g = float(coverage.get("genes_coverage_pct", 0.0))
    p = float(coverage.get("pathways_coverage_pct", 0.0))
    total = int(coverage.get("total_papers", 0))
    return g >= target_gene * 100 and p >= target_pathway * 100 and total >= min_papers


def _run_method_once(
    method: str,
    case: dict[str, Any],
    max_results: int,
    max_iterations: int,
    rerank_mode: str,
    query_cache: list[dict] | None = None,
    record_queries: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any], str | None, str | None, list[str], list[dict]]:
    """Run a single method for one case and normalize return values.

    Returns:
        (papers, coverage, query_used, search_method, recommended_actions,
         recorded_query_cache)
        recorded_query_cache is non-empty only when record_queries=True.
    """
    query_used = None
    search_method = None
    recommended_actions: list[str] = []
    recorded_query_cache: list[dict] = []

    if method in _DYNAMIC_METHODS:
        enforce_disease_match = method not in {
            "dynamic_off", "dynamic_no_disease_filter", "dynamic_lean",
            "dynamic_coverage_weighted",
        }
        effective_rerank = "off" if method in {"dynamic_off", "dynamic_lean"} else rerank_mode
        sort_by_journal = method not in {"dynamic_no_sjr", "dynamic_off"}
        coverage_weighted = method in {"dynamic_coverage_weighted", "dynamic_filter_coverage_weighted"}
        invoke_params: dict[str, Any] = {
            "genes": case["genes"],
            "pathways": case["pathways"],
            "celltypes": case["celltypes"],
            "disease": case["disease"],
            "max_results": max_results,
            "max_iterations": max_iterations,
            "rerank_mode": effective_rerank,
            "enforce_disease_match": enforce_disease_match,
            "sort_by_journal_quality": sort_by_journal,
            "coverage_weighted_sort": coverage_weighted,
        }
        if query_cache is not None:
            invoke_params["query_cache"] = query_cache
        if record_queries:
            invoke_params["record_queries"] = True
        result = search_literature_dynamic.invoke(invoke_params)
        papers = result.get("papers", []) if isinstance(result, dict) else []
        coverage = result.get("coverage") if isinstance(result, dict) else None
        search_method = result.get("search_method") if isinstance(result, dict) else None
        if isinstance(result, dict):
            recommended_actions = [str(a) for a in result.get("recommended_actions", [])]
            recorded_query_cache = result.get("query_cache", [])
    elif method == "baseline_lit":
        papers = search_literature.invoke(
            {
                "genes": case["genes"],
                "disease": case["disease"],
                "keywords": case["pathways"][:3] + case["celltypes"][:3],
                "max_results": max_results,
            }
        )
        coverage = None
        search_method = "search_literature"
    elif method == "baseline_eutils":
        query = _build_eutils_query(case)
        result = search_pubmed_advanced.invoke(
            {
                "query": query,
                "max_results": max_results,
                "sort": "relevance",
            }
        )
        papers = result.get("papers", []) if isinstance(result, dict) else []
        query_used = result.get("query_used", query) if isinstance(result, dict) else query
        coverage = None
        search_method = "search_pubmed_advanced"
    else:
        raise ValueError(f"Unknown method: {method}")

    papers = [p for p in papers if isinstance(p, dict)]
    if coverage is None:
        # F2: honor evidence manifest stamps when benchmarking SEARCHER-equivalent
        # dynamic modes; legacy baselines keep the default False for
        # comparability with pre-F2 numbers.
        coverage = _calculate_coverage(
            papers=papers,
            genes=case["genes"],
            pathways=case["pathways"],
            celltypes=case["celltypes"],
            use_retrieval_tags=(method in _DYNAMIC_METHODS),
        )
    return papers, coverage, query_used, search_method, recommended_actions, recorded_query_cache


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_label_template(path: Path, rows: list[dict[str, Any]], top_k: int = 20) -> None:
    """Create lightweight manual-label template from benchmark results."""
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (str(row["case_id"]), str(row["method"]))
        grouped.setdefault(key, []).append(row)

    template_rows: list[dict[str, Any]] = []
    for (case_id, method), records in grouped.items():
        # Use first repeat for annotation template
        record = sorted(records, key=lambda x: int(x.get("repeat_index", 0)))[0]
        papers = record.get("papers", [])[:top_k]
        for p in papers:
            template_rows.append(
                {
                    "case_id": case_id,
                    "method": method,
                    "pmid": p.get("pmid", ""),
                    "title": p.get("title", ""),
                    "label": "",  # relevant|partial|irrelevant
                    "annotator": "",
                    "confidence": "",
                }
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "case_id",
                "method",
                "pmid",
                "title",
                "label",
                "annotator",
                "confidence",
            ],
        )
        writer.writeheader()
        writer.writerows(template_rows)


def _load_completed_keys(run_dir: Path) -> set[tuple[str, str, int]]:
    """Read existing raw_runs.jsonl and return completed (method, case_id, rep) keys.

    Records with errors are excluded so they can be retried.
    """
    completed: set[tuple[str, str, int]] = set()
    jsonl_path = run_dir / "raw_runs.jsonl"
    if not jsonl_path.exists():
        return completed
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("error"):
                continue
            # Treat fixed_strategy_fallback as incomplete (LLM was unavailable)
            if rec.get("search_method") == "fixed_strategy_fallback":
                continue
            key = (str(rec["method"]), str(rec["case_id"]), int(rec["repeat_index"]))
            completed.add(key)
    return completed


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cases",
        default="docs/benchmarks/lit_repro_benchmark/cases_v1.json",
        help="Path to benchmark cases JSON file",
    )
    parser.add_argument(
        "--output-dir",
        default="docs/benchmarks/lit_repro_benchmark/results",
        help="Base directory for benchmark outputs",
    )
    parser.add_argument(
        "--methods",
        nargs="+",
        default=["dynamic", "baseline_lit", "baseline_eutils"],
        choices=[
            "dynamic", "dynamic_off", "dynamic_no_disease_filter",
            "dynamic_no_sjr", "dynamic_lean", "dynamic_coverage_weighted",
            "dynamic_filter_coverage_weighted",
            "baseline_lit", "baseline_eutils",
        ],
        help="Methods to run",
    )
    parser.add_argument(
        "--run-dir",
        default=None,
        help="Append results to an existing run directory (skips writing config/summary/labels/latest_run)",
    )
    parser.add_argument("--max-results", type=int, default=30)
    parser.add_argument("--dynamic-repeats", type=int, default=20)
    parser.add_argument("--baseline-repeats", type=int, default=1)
    parser.add_argument("--max-iterations", type=int, default=3)
    parser.add_argument("--rerank-mode", choices=["off", "llm"], default="off")
    parser.add_argument(
        "--shared-queries",
        action="store_true",
        default=False,
        help="Phase 1: reference run (dynamic_lean) caches iteration-0 queries. "
             "Phase 2: remaining methods replay cached queries for fair comparison.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        default=False,
        help="Resume an interrupted run: skip (method, case, rep) combos already "
             "in raw_runs.jsonl (error records are retried). Requires --run-dir.",
    )
    return parser


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    cases = load_cases(args.cases)

    run_id = (
        f"run_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
    )
    appending = args.run_dir is not None
    if args.resume and not args.run_dir:
        parser.error("--resume requires --run-dir")
    if appending:
        run_dir = Path(args.run_dir)
        if not run_dir.exists():
            raise FileNotFoundError(f"--run-dir does not exist: {run_dir}")
    else:
        run_dir = Path(args.output_dir) / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

    completed_keys: set[tuple[str, str, int]] = set()
    if args.resume:
        completed_keys = _load_completed_keys(run_dir)
        print(f"[resume] Found {len(completed_keys)} completed records, skipping them.")

    def _repeats_for(method: str) -> int:
        return args.dynamic_repeats if method in _DYNAMIC_METHODS else args.baseline_repeats

    records: list[dict[str, Any]] = []
    total_jobs = sum(len(cases) * _repeats_for(m) for m in args.methods)
    completed_jobs = 0

    def _record_run(
        method: str,
        case: dict[str, Any],
        rep: int,
        papers: list[dict[str, Any]],
        coverage: dict[str, Any],
        query_used: str | None,
        search_method: str | None,
        recommended_actions: list[str],
        latency_ms: float,
        error: str | None,
        error_type: str | None,
        shared_queries_mode: bool = False,
    ) -> dict[str, Any]:
        nonlocal completed_jobs
        compact_papers = _compact_papers(papers)
        pmids = extract_pmids(compact_papers)
        record = {
            "run_id": run_id,
            "started_at_utc": datetime.now(UTC).isoformat(),
            "finished_at_utc": datetime.now(UTC).isoformat(),
            "case_id": case["case_id"],
            "method": method,
            "repeat_index": rep,
            "input": {
                "genes": case["genes"],
                "pathways": case["pathways"],
                "celltypes": case["celltypes"],
                "disease": case["disease"],
                "notes": case.get("notes", ""),
            },
            "query_used": query_used,
            "search_method": search_method,
            "papers": compact_papers,
            "pmids": pmids,
            "total_papers": len(compact_papers),
            "coverage": coverage,
            "coverage_sufficient": _coverage_sufficient(coverage) if coverage else False,
            "recommended_actions": recommended_actions,
            "shared_queries": shared_queries_mode,
            "latency_ms": latency_ms,
            "error": error,
            "error_type": error_type,
        }
        records.append(record)

        # Incremental append – survives crashes
        with (run_dir / "raw_runs.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        completed_jobs += 1
        print(
            f"[{completed_jobs}/{total_jobs}] "
            f"{method} case={case['case_id']} rep={rep} papers={len(pmids)} "
            f"latency={latency_ms:.0f}ms error={'yes' if error else 'no'}"
            + (" [shared-queries]" if shared_queries_mode else ""),
            flush=True,
        )
        return record

    if args.shared_queries:
        # ── Shared-queries mode ──────────────────────────────────────
        # Phase 1: Run reference method (dynamic_lean) with record_queries
        # Phase 2: Replay cached iteration-0 queries for remaining methods
        reference_method = "dynamic_lean"
        replay_methods = [m for m in args.methods if m != reference_method]

        for case in cases:
            # Phase 1: reference run – record iteration-0 queries
            cached_queries: list[dict] = []
            ref_key = (reference_method, case["case_id"], 0)
            if ref_key in completed_keys:
                completed_jobs += 1
                # Load cached queries from saved artifact for Phase 2
                cache_path = run_dir / f"query_cache_{case['case_id']}.json"
                if cache_path.exists():
                    cached_queries = json.loads(
                        cache_path.read_text(encoding="utf-8")
                    ).get("queries", [])
            else:
                t0 = time.perf_counter()
                error = error_type = query_used = search_method = None
                papers: list[dict[str, Any]] = []
                coverage: dict[str, Any] = {}
                recommended_actions: list[str] = []
                try:
                    papers, coverage, query_used, search_method, recommended_actions, cached_queries = (
                        _run_method_once(
                            method=reference_method,
                            case=case,
                            max_results=args.max_results,
                            max_iterations=args.max_iterations,
                            rerank_mode=args.rerank_mode,
                            record_queries=True,
                        )
                    )
                except Exception as exc:
                    error = str(exc)
                    error_type = type(exc).__name__

                latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)
                _record_run(
                    method=reference_method, case=case, rep=0,
                    papers=papers, coverage=coverage, query_used=query_used,
                    search_method=search_method, recommended_actions=recommended_actions,
                    latency_ms=latency_ms, error=error, error_type=error_type,
                    shared_queries_mode=True,
                )

                # Save cache artifact
                if cached_queries:
                    cache_path = run_dir / f"query_cache_{case['case_id']}.json"
                    _write_json(cache_path, {
                        "case_id": case["case_id"],
                        "generated_at_utc": datetime.now(UTC).isoformat(),
                        "reference_method": reference_method,
                        "queries": cached_queries,
                    })

            # Phase 2: replay cached queries for remaining methods
            for method in replay_methods:
                if method not in _DYNAMIC_METHODS:
                    # Baseline methods don't use query cache
                    for rep in range(_repeats_for(method)):
                        if (method, case["case_id"], rep) in completed_keys:
                            completed_jobs += 1
                            continue
                        t0 = time.perf_counter()
                        error = error_type = query_used = search_method = None
                        papers = []
                        coverage = {}
                        recommended_actions = []
                        try:
                            papers, coverage, query_used, search_method, recommended_actions, _ = (
                                _run_method_once(
                                    method=method, case=case,
                                    max_results=args.max_results,
                                    max_iterations=args.max_iterations,
                                    rerank_mode=args.rerank_mode,
                                )
                            )
                        except Exception as exc:
                            error = str(exc)
                            error_type = type(exc).__name__
                        latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)
                        _record_run(
                            method=method, case=case, rep=rep,
                            papers=papers, coverage=coverage, query_used=query_used,
                            search_method=search_method,
                            recommended_actions=recommended_actions,
                            latency_ms=latency_ms, error=error, error_type=error_type,
                        )
                    continue

                for rep in range(_repeats_for(method)):
                    if (method, case["case_id"], rep) in completed_keys:
                        completed_jobs += 1
                        continue
                    t0 = time.perf_counter()
                    error = error_type = query_used = search_method = None
                    papers = []
                    coverage = {}
                    recommended_actions = []
                    try:
                        papers, coverage, query_used, search_method, recommended_actions, _ = (
                            _run_method_once(
                                method=method, case=case,
                                max_results=args.max_results,
                                max_iterations=args.max_iterations,
                                rerank_mode=args.rerank_mode,
                                query_cache=cached_queries if cached_queries else None,
                            )
                        )
                    except Exception as exc:
                        error = str(exc)
                        error_type = type(exc).__name__
                    latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)
                    _record_run(
                        method=method, case=case, rep=rep,
                        papers=papers, coverage=coverage, query_used=query_used,
                        search_method=search_method,
                        recommended_actions=recommended_actions,
                        latency_ms=latency_ms, error=error, error_type=error_type,
                        shared_queries_mode=bool(cached_queries),
                    )

    else:
        # ── Normal mode (unchanged behavior) ─────────────────────────
        for method in args.methods:
            for case in cases:
                for rep in range(_repeats_for(method)):
                    if (method, case["case_id"], rep) in completed_keys:
                        completed_jobs += 1
                        continue
                    started_at = datetime.now(UTC).isoformat()
                    t0 = time.perf_counter()
                    error = error_type = query_used = search_method = None
                    papers: list[dict[str, Any]] = []
                    coverage: dict[str, Any] = {}
                    recommended_actions: list[str] = []
                    try:
                        papers, coverage, query_used, search_method, recommended_actions, _ = (
                            _run_method_once(
                                method=method,
                                case=case,
                                max_results=args.max_results,
                                max_iterations=args.max_iterations,
                                rerank_mode=args.rerank_mode,
                            )
                        )
                    except Exception as exc:  # pragma: no cover
                        error = str(exc)
                        error_type = type(exc).__name__

                    latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)
                    _record_run(
                        method=method, case=case, rep=rep,
                        papers=papers, coverage=coverage, query_used=query_used,
                        search_method=search_method,
                        recommended_actions=recommended_actions,
                        latency_ms=latency_ms, error=error, error_type=error_type,
                    )

    failed = sum(1 for r in records if r.get("error"))
    if not appending:
        summary = {
            "run_id": run_id,
            "cases_path": str(Path(args.cases).resolve()),
            "methods": args.methods,
            "dynamic_repeats": args.dynamic_repeats,
            "baseline_repeats": args.baseline_repeats,
            "max_results": args.max_results,
            "max_iterations": args.max_iterations,
            "rerank_mode": args.rerank_mode,
            "shared_queries": args.shared_queries,
            "total_records": len(records),
            "failed_records": failed,
            "success_records": len(records) - failed,
            "created_at_utc": datetime.now(UTC).isoformat(),
        }
        _write_json(run_dir / "run_summary.json", summary)
        _write_json(run_dir / "run_config.json", vars(args))
        _write_label_template(run_dir / "labels_top20_template.csv", records, top_k=20)
        (Path(args.output_dir) / "latest_run.txt").write_text(run_id, encoding="utf-8")

    print(f"Saved benchmark run to: {run_dir}")


if __name__ == "__main__":
    main()
