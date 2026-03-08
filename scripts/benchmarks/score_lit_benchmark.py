"""Score literature benchmark runs and generate summary report."""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import random
import statistics
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def jaccard(a: list[str], b: list[str]) -> float:
    """Jaccard similarity between two PMID lists."""
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def top_k_overlap(a: list[str], b: list[str], k: int = 10) -> float:
    """Overlap ratio of top-k PMID sets."""
    if k <= 0:
        return 0.0
    sa = set(a[:k])
    sb = set(b[:k])
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / float(k)


def bootstrap_paired_ci(
    a: list[float],
    b: list[float],
    n_boot: int = 5000,
    seed: int = 42,
    ci: float = 0.95,
) -> tuple[float, float, float]:
    """Bootstrap paired mean-difference CI and two-sided p-value estimate.

    Returns (ci_low, ci_high, p_value) for diff = mean(a - b).
    """
    if len(a) != len(b):
        raise ValueError("a and b must have same length for paired bootstrap")
    if len(a) == 0:
        raise ValueError("a and b must be non-empty")
    if n_boot < 100:
        raise ValueError("n_boot must be >= 100")

    diffs = [float(x) - float(y) for x, y in zip(a, b, strict=True)]
    n = len(diffs)
    rng = random.Random(seed)
    boot_means: list[float] = []
    for _ in range(n_boot):
        sample = [diffs[rng.randrange(n)] for _ in range(n)]
        boot_means.append(sum(sample) / n)

    boot_means.sort()
    alpha = (1.0 - ci) / 2.0
    lo_idx = max(0, min(len(boot_means) - 1, int(math.floor(alpha * n_boot))))
    hi_idx = max(0, min(len(boot_means) - 1, int(math.floor((1.0 - alpha) * n_boot)) - 1))
    lo = boot_means[lo_idx]
    hi = boot_means[hi_idx]

    le_zero = sum(1 for x in boot_means if x <= 0) / n_boot
    ge_zero = sum(1 for x in boot_means if x >= 0) / n_boot
    p_value = min(1.0, 2.0 * min(le_zero, ge_zero))
    return lo, hi, p_value


def compute_coverage_pass(
    record: dict[str, Any],
    target_gene: float = 0.6,
    target_pathway: float = 0.5,
    min_papers: int = 15,
) -> bool:
    """Determine whether a run satisfies coverage thresholds."""
    if isinstance(record.get("coverage_sufficient"), bool):
        return bool(record["coverage_sufficient"])

    coverage = record.get("coverage", {})
    if not isinstance(coverage, dict):
        return False

    gene_cov = float(coverage.get("genes_coverage_pct", 0.0))
    path_cov = float(coverage.get("pathways_coverage_pct", 0.0))
    total_papers = int(coverage.get("total_papers", record.get("total_papers", 0)))

    # Handle either [0,100] or [0,1] format defensively.
    if gene_cov <= 1.0:
        gene_cov *= 100.0
    if path_cov <= 1.0:
        path_cov *= 100.0

    return (
        gene_cov >= target_gene * 100.0
        and path_cov >= target_pathway * 100.0
        and total_papers >= min_papers
    )


def _normalize_coverage_pct(value: Any) -> float:
    """Normalize coverage values to percentage scale [0, 100]-like."""
    try:
        cov = float(value)
    except (TypeError, ValueError):
        return 0.0
    if cov < 0:
        return 0.0
    if cov <= 1.0:
        return cov * 100.0
    return cov


def extract_continuous_metrics(record: dict[str, Any]) -> dict[str, float]:
    """Extract full-set continuous metrics from a run record."""
    coverage = record.get("coverage", {})
    if not isinstance(coverage, dict):
        coverage = {}

    gene_cov = _normalize_coverage_pct(coverage.get("genes_coverage_pct", 0.0))
    path_cov = _normalize_coverage_pct(coverage.get("pathways_coverage_pct", 0.0))
    ct_cov = _normalize_coverage_pct(coverage.get("celltypes_coverage_pct", 0.0))

    total_raw = coverage.get("total_papers", record.get("total_papers", 0))
    try:
        total_papers = float(total_raw)
    except (TypeError, ValueError):
        total_papers = 0.0
    if total_papers < 0:
        total_papers = 0.0

    return {
        "gene_coverage_pct": gene_cov,
        "pathway_coverage_pct": path_cov,
        "celltype_coverage_pct": ct_cov,
        "coverage_composite_pct": (gene_cov + path_cov + ct_cov) / 3.0,
        "total_papers": total_papers,
    }


def _load_runs(path: Path) -> list[dict[str, Any]]:
    if path.is_dir():
        path = path / "raw_runs.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"Run file not found: {path}")

    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def _load_labels(path: Path | None) -> dict[tuple[str, str, str], float]:
    if path is None:
        return {}
    if not path.exists():
        raise FileNotFoundError(f"Labels file not found: {path}")

    labels: dict[tuple[str, str, str], float] = {}
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            case_id = str(row.get("case_id", "")).strip()
            method = str(row.get("method", "")).strip()
            pmid = str(row.get("pmid", "")).strip()
            label_raw = str(row.get("label", "")).strip().lower()
            if not case_id or not method or not pmid or not label_raw:
                continue
            if label_raw == "relevant":
                score = 1.0
            elif label_raw == "partial":
                score = 0.5
            elif label_raw == "irrelevant":
                score = 0.0
            else:
                continue
            labels[(case_id, method, pmid)] = score
    return labels


def _normalize(text: str) -> str:
    return " ".join(
        "".join(c.lower() if c.isalnum() or c.isspace() else " " for c in text).split()
    )


def _disease_tokens(disease: str) -> list[str]:
    generic = {"disease", "cancer", "tumor", "tumour", "syndrome", "disorder"}
    tokens = [t for t in _normalize(disease).split() if len(t) >= 4 and t not in generic]
    return tokens[:6]


def _paper_contamination_rate(record: dict[str, Any]) -> float | None:
    """Disease-nonspecificity: fraction of papers lacking disease tokens."""
    papers = record.get("papers", [])
    if not isinstance(papers, list) or not papers:
        return None
    disease = str(record.get("input", {}).get("disease", "")).strip()
    tokens = _disease_tokens(disease)
    if not tokens:
        return None

    contam = 0
    count = 0
    for p in papers:
        if not isinstance(p, dict):
            continue
        text = _normalize(f"{p.get('title', '')} {p.get('abstract', '')}")
        if not text:
            continue
        count += 1
        if not any(tok in text for tok in tokens):
            contam += 1
    if count == 0:
        return None
    return contam / count


def _input_feature_tokens(record: dict[str, Any]) -> list[str]:
    """Collect all normalized input feature tokens (genes, pathways, celltypes, disease)."""
    inp = record.get("input", {})
    if not isinstance(inp, dict):
        return []
    tokens: list[str] = []
    for gene in inp.get("genes", []):
        tok = _normalize(str(gene))
        if len(tok) >= 3:
            tokens.append(tok)
    for pathway in inp.get("pathways", []):
        tok = _normalize(str(pathway))
        if len(tok) >= 3:
            tokens.append(tok)
    for ct in inp.get("celltypes", []):
        tok = _normalize(str(ct))
        if len(tok) >= 3:
            tokens.append(tok)
    tokens.extend(_disease_tokens(str(inp.get("disease", ""))))
    return tokens


def _strict_contamination_rate(record: dict[str, Any]) -> float | None:
    """Strict contamination: fraction of papers matching NO input features at all.

    A paper is strictly contaminated only if none of genes, pathways,
    celltypes, or disease tokens appear in its title+abstract.
    """
    papers = record.get("papers", [])
    if not isinstance(papers, list) or not papers:
        return None
    tokens = _input_feature_tokens(record)
    if not tokens:
        return None

    contam = 0
    count = 0
    for p in papers:
        if not isinstance(p, dict):
            continue
        text = _normalize(f"{p.get('title', '')} {p.get('abstract', '')}")
        if not text:
            continue
        count += 1
        if not any(tok in text for tok in tokens):
            contam += 1
    if count == 0:
        return None
    return contam / count


def _load_llm_labels(path: Path | None) -> dict[tuple[str, str], bool]:
    """Load LLM relevance labels from JSONL file.

    Returns dict keyed by (disease, pmid) -> bool (relevant).
    Entries where relevant is null are skipped.
    If path is None, auto-discovers llm_relevance_labels.jsonl in parent dir.
    """
    if path is None:
        return {}
    if not path.exists():
        return {}

    labels: dict[tuple[str, str], bool] = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            disease = str(obj.get("disease", "")).strip()
            pmid = str(obj.get("pmid", "")).strip()
            relevant = obj.get("relevant")
            if not disease or not pmid or relevant is None:
                continue
            labels[(disease, pmid)] = bool(relevant)
    return labels


def _llm_contamination_rate(
    record: dict[str, Any], llm_labels: dict[tuple[str, str], bool]
) -> float | None:
    """Fraction of papers labeled NOT relevant by LLM."""
    if not llm_labels:
        return None
    disease = str(record.get("input", {}).get("disease", "")).strip()
    papers = record.get("papers", [])
    if not isinstance(papers, list) or not papers or not disease:
        return None

    labeled = 0
    not_relevant = 0
    for p in papers:
        if not isinstance(p, dict):
            continue
        pmid = str(p.get("pmid", "")).strip()
        if not pmid:
            continue
        key = (disease, pmid)
        if key in llm_labels:
            labeled += 1
            if not llm_labels[key]:
                not_relevant += 1
    if labeled == 0:
        return None
    return not_relevant / labeled


def _precision_at_k(
    record: dict[str, Any],
    labels: dict[tuple[str, str, str], float],
    k: int = 10,
) -> float | None:
    if not labels:
        return None
    case_id = str(record.get("case_id", ""))
    method = str(record.get("method", ""))
    pmids = [str(p) for p in record.get("pmids", [])][:k]
    if not pmids:
        return None

    total = 0.0
    for pmid in pmids:
        total += labels.get((case_id, method, pmid), 0.0)
    return total / k


def _compute_reproducibility(records: list[dict[str, Any]], dynamic_method: str) -> dict[str, Any]:
    by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        if r.get("method") == dynamic_method and not r.get("error"):
            by_case[str(r.get("case_id", ""))].append(r)

    case_stats: list[dict[str, Any]] = []
    for case_id, rows in by_case.items():
        if len(rows) < 2:
            continue
        pmid_lists = [[str(p) for p in row.get("pmids", [])] for row in rows]
        j_scores = []
        top10_scores = []
        for a, b in itertools.combinations(pmid_lists, 2):
            j_scores.append(jaccard(a, b))
            top10_scores.append(top_k_overlap(a, b, k=10))
        case_stats.append(
            {
                "case_id": case_id,
                "pairwise_jaccard_median": statistics.median(j_scores) if j_scores else None,
                "pairwise_top10_overlap_median": (
                    statistics.median(top10_scores) if top10_scores else None
                ),
            }
        )

    j_all = [c["pairwise_jaccard_median"] for c in case_stats if c["pairwise_jaccard_median"] is not None]
    t_all = [
        c["pairwise_top10_overlap_median"]
        for c in case_stats
        if c["pairwise_top10_overlap_median"] is not None
    ]
    return {
        "dynamic_method": dynamic_method,
        "n_cases_with_repeats": len(case_stats),
        "pairwise_jaccard_median": statistics.median(j_all) if j_all else None,
        "pairwise_top10_overlap_median": statistics.median(t_all) if t_all else None,
        "per_case": case_stats,
    }


def _group_case_metric(rows: list[dict[str, Any]], key: str) -> dict[str, float]:
    by_case: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        case_id = str(r.get("case_id", ""))
        value = r.get(key)
        if case_id and isinstance(value, (int, float)):
            by_case[case_id].append(float(value))
    return {case_id: (sum(vals) / len(vals)) for case_id, vals in by_case.items() if vals}


def _compute_method_summary(
    records: list[dict[str, Any]],
    labels: dict[tuple[str, str, str], float],
    llm_labels: dict[tuple[str, str], bool] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, float]]]:
    enriched: list[dict[str, Any]] = []
    for r in records:
        rr = dict(r)
        rr["coverage_pass"] = 1.0 if compute_coverage_pass(rr) else 0.0
        p10 = _precision_at_k(rr, labels, k=10)
        rr["p_at_10"] = p10
        rr["contamination_rate"] = _paper_contamination_rate(rr)
        rr["strict_contamination_rate"] = _strict_contamination_rate(rr)
        rr["llm_contamination_rate"] = _llm_contamination_rate(rr, llm_labels or {})
        rr.update(extract_continuous_metrics(rr))
        enriched.append(rr)

    by_method: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in enriched:
        by_method[str(r.get("method", ""))].append(r)

    summary_rows: list[dict[str, Any]] = []
    case_metric_cache: dict[str, dict[str, float]] = {}
    for method, rows in sorted(by_method.items()):
        valid_rows = [r for r in rows if not r.get("error")]
        coverage_vals = [float(r["coverage_pass"]) for r in valid_rows]
        p10_vals = [float(r["p_at_10"]) for r in valid_rows if isinstance(r.get("p_at_10"), (int, float))]
        gene_cov_vals = [float(r["gene_coverage_pct"]) for r in valid_rows]
        path_cov_vals = [float(r["pathway_coverage_pct"]) for r in valid_rows]
        ct_cov_vals = [float(r["celltype_coverage_pct"]) for r in valid_rows]
        comp_cov_vals = [float(r["coverage_composite_pct"]) for r in valid_rows]
        total_paper_vals = [float(r["total_papers"]) for r in valid_rows]
        contam_vals = [
            float(r["contamination_rate"])
            for r in valid_rows
            if isinstance(r.get("contamination_rate"), (int, float))
        ]
        strict_contam_vals = [
            float(r["strict_contamination_rate"])
            for r in valid_rows
            if isinstance(r.get("strict_contamination_rate"), (int, float))
        ]
        llm_contam_vals = [
            float(r["llm_contamination_rate"])
            for r in valid_rows
            if isinstance(r.get("llm_contamination_rate"), (int, float))
        ]

        summary_rows.append(
            {
                "method": method,
                "n_runs": len(rows),
                "n_success_runs": len(valid_rows),
                "mean_gene_coverage_pct": (
                    sum(gene_cov_vals) / len(gene_cov_vals) if gene_cov_vals else None
                ),
                "mean_pathway_coverage_pct": (
                    sum(path_cov_vals) / len(path_cov_vals) if path_cov_vals else None
                ),
                "mean_celltype_coverage_pct": (
                    sum(ct_cov_vals) / len(ct_cov_vals) if ct_cov_vals else None
                ),
                "mean_coverage_composite_pct": (
                    sum(comp_cov_vals) / len(comp_cov_vals) if comp_cov_vals else None
                ),
                "mean_total_papers": (
                    sum(total_paper_vals) / len(total_paper_vals) if total_paper_vals else None
                ),
                "coverage_pass_rate": (sum(coverage_vals) / len(coverage_vals)) if coverage_vals else None,
                "precision_at_10": (sum(p10_vals) / len(p10_vals)) if p10_vals else None,
                "contamination_rate": (sum(contam_vals) / len(contam_vals)) if contam_vals else None,
                "strict_contamination_rate": (
                    sum(strict_contam_vals) / len(strict_contam_vals) if strict_contam_vals else None
                ),
                "llm_contamination_rate": (
                    sum(llm_contam_vals) / len(llm_contam_vals) if llm_contam_vals else None
                ),
                "avg_latency_ms": (
                    sum(float(r.get("latency_ms", 0.0)) for r in valid_rows) / len(valid_rows)
                    if valid_rows
                    else None
                ),
            }
        )

        case_metric_cache[f"{method}:coverage_pass"] = _group_case_metric(valid_rows, "coverage_pass")
        case_metric_cache[f"{method}:p_at_10"] = _group_case_metric(valid_rows, "p_at_10")
        case_metric_cache[f"{method}:gene_coverage_pct"] = _group_case_metric(valid_rows, "gene_coverage_pct")
        case_metric_cache[f"{method}:pathway_coverage_pct"] = _group_case_metric(valid_rows, "pathway_coverage_pct")
        case_metric_cache[f"{method}:celltype_coverage_pct"] = _group_case_metric(valid_rows, "celltype_coverage_pct")
        case_metric_cache[f"{method}:coverage_composite_pct"] = _group_case_metric(valid_rows, "coverage_composite_pct")
        case_metric_cache[f"{method}:total_papers"] = _group_case_metric(valid_rows, "total_papers")
        case_metric_cache[f"{method}:contamination_rate"] = _group_case_metric(valid_rows, "contamination_rate")
        case_metric_cache[f"{method}:strict_contamination_rate"] = _group_case_metric(valid_rows, "strict_contamination_rate")
        case_metric_cache[f"{method}:llm_contamination_rate"] = _group_case_metric(valid_rows, "llm_contamination_rate")

    return summary_rows, case_metric_cache


def _paired_bootstrap_comparisons(
    case_metric_cache: dict[str, dict[str, float]],
    baseline_methods: list[str],
    dynamic_method: str,
    n_boot: int,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for baseline in baseline_methods:
        for metric in (
            "gene_coverage_pct",
            "pathway_coverage_pct",
            "celltype_coverage_pct",
            "coverage_composite_pct",
            "total_papers",
            "coverage_pass",
            "p_at_10",
        ):
            dyn = case_metric_cache.get(f"{dynamic_method}:{metric}", {})
            base = case_metric_cache.get(f"{baseline}:{metric}", {})
            shared_cases = sorted(set(dyn) & set(base))
            if len(shared_cases) < 3:
                continue
            a = [dyn[c] for c in shared_cases]
            b = [base[c] for c in shared_cases]
            lo, hi, p_value = bootstrap_paired_ci(a, b, n_boot=n_boot)
            results.append(
                {
                    "metric": metric,
                    "method_a": dynamic_method,
                    "method_b": baseline,
                    "n_paired_cases": len(shared_cases),
                    "mean_diff_a_minus_b": (sum(x - y for x, y in zip(a, b, strict=True)) / len(a)),
                    "ci_low": lo,
                    "ci_high": hi,
                    "p_value": p_value,
                }
            )
    return results


def _render_markdown_report(
    summary_rows: list[dict[str, Any]],
    repro: dict[str, Any],
    comparisons: list[dict[str, Any]],
) -> str:
    lines: list[str] = []
    lines.append("# Literature Reproducibility and Benchmark Report")
    lines.append("")
    lines.append(f"- Generated at (UTC): {datetime.now(UTC).isoformat()}")
    lines.append("")
    lines.append("## Method Summary")
    lines.append("")
    lines.append(
        "| Method | Runs | Success Runs | Mean Gene Cov % | Mean Pathway Cov % | Mean CellType Cov % | Mean Composite Cov % | Mean Papers | Coverage Pass Rate | Precision@10 | Strict Contam | Disease Nonspec | Avg Latency (ms) |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in summary_rows:
        lines.append(
            "| {method} | {n_runs} | {n_success_runs} | {mean_gene_coverage_pct} | {mean_pathway_coverage_pct} | {mean_celltype_coverage_pct} | {mean_coverage_composite_pct} | {mean_total_papers} | {coverage_pass_rate} | {precision_at_10} | {strict_contamination_rate} | {contamination_rate} | {avg_latency_ms} |".format(
                method=row["method"],
                n_runs=row["n_runs"],
                n_success_runs=row["n_success_runs"],
                mean_gene_coverage_pct=(
                    f"{row['mean_gene_coverage_pct']:.1f}"
                    if isinstance(row.get("mean_gene_coverage_pct"), (int, float))
                    else "NA"
                ),
                mean_pathway_coverage_pct=(
                    f"{row['mean_pathway_coverage_pct']:.1f}"
                    if isinstance(row.get("mean_pathway_coverage_pct"), (int, float))
                    else "NA"
                ),
                mean_celltype_coverage_pct=(
                    f"{row['mean_celltype_coverage_pct']:.1f}"
                    if isinstance(row.get("mean_celltype_coverage_pct"), (int, float))
                    else "NA"
                ),
                mean_coverage_composite_pct=(
                    f"{row['mean_coverage_composite_pct']:.1f}"
                    if isinstance(row.get("mean_coverage_composite_pct"), (int, float))
                    else "NA"
                ),
                mean_total_papers=(
                    f"{row['mean_total_papers']:.1f}"
                    if isinstance(row.get("mean_total_papers"), (int, float))
                    else "NA"
                ),
                coverage_pass_rate=(
                    f"{row['coverage_pass_rate']:.3f}"
                    if isinstance(row.get("coverage_pass_rate"), (int, float))
                    else "NA"
                ),
                precision_at_10=(
                    f"{row['precision_at_10']:.3f}"
                    if isinstance(row.get("precision_at_10"), (int, float))
                    else "NA"
                ),
                strict_contamination_rate=(
                    f"{row['strict_contamination_rate']:.3f}"
                    if isinstance(row.get("strict_contamination_rate"), (int, float))
                    else "NA"
                ),
                contamination_rate=(
                    f"{row['contamination_rate']:.3f}"
                    if isinstance(row.get("contamination_rate"), (int, float))
                    else "NA"
                ),
                avg_latency_ms=(
                    f"{row['avg_latency_ms']:.1f}"
                    if isinstance(row.get("avg_latency_ms"), (int, float))
                    else "NA"
                ),
            )
        )

    lines.append("")
    lines.append("## Dynamic Reproducibility")
    lines.append("")
    lines.append(
        f"- Cases with >=2 repeats: {repro.get('n_cases_with_repeats', 0)}"
    )
    lines.append(
        f"- Pairwise Jaccard median: {repro.get('pairwise_jaccard_median') if repro.get('pairwise_jaccard_median') is not None else 'NA'}"
    )
    lines.append(
        f"- Pairwise Top-10 overlap median: {repro.get('pairwise_top10_overlap_median') if repro.get('pairwise_top10_overlap_median') is not None else 'NA'}"
    )

    lines.append("")
    lines.append("## Paired Bootstrap Comparisons (dynamic - baseline)")
    lines.append("")
    if not comparisons:
        lines.append("No paired comparison available (insufficient shared cases or labels).")
    else:
        lines.append("| Metric | Baseline | Paired Cases | Mean Diff | 95% CI | p-value |")
        lines.append("|---|---|---:|---:|---|---:|")
        for c in comparisons:
            lines.append(
                "| {metric} | {baseline} | {n} | {diff:.4f} | [{lo:.4f}, {hi:.4f}] | {p:.4f} |".format(
                    metric=c["metric"],
                    baseline=c["method_b"],
                    n=c["n_paired_cases"],
                    diff=c["mean_diff_a_minus_b"],
                    lo=c["ci_low"],
                    hi=c["ci_high"],
                    p=c["p_value"],
                )
            )
    lines.append("")
    return "\n".join(lines)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runs",
        required=True,
        help="Path to run directory or raw_runs.jsonl file",
    )
    parser.add_argument(
        "--labels",
        default="",
        help="Optional CSV labels file (case_id,method,pmid,label,annotator,confidence)",
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help="Directory for score_summary.json and benchmark_report.md (default: run dir)",
    )
    parser.add_argument("--dynamic-method", default="dynamic")
    parser.add_argument("--n-boot", type=int, default=5000)
    parser.add_argument(
        "--llm-labels",
        default="",
        help="Path to llm_relevance_labels.jsonl (auto-discovers in run dir if absent)",
    )
    return parser


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    runs_path = Path(args.runs)
    records = _load_runs(runs_path)
    labels_path = Path(args.labels) if args.labels else None
    labels = _load_labels(labels_path)

    llm_labels_path: Path | None = None
    if args.llm_labels:
        llm_labels_path = Path(args.llm_labels)
    else:
        auto = (runs_path if runs_path.is_dir() else runs_path.parent) / "llm_relevance_labels.jsonl"
        if auto.exists():
            llm_labels_path = auto
    llm_labels = _load_llm_labels(llm_labels_path)
    if llm_labels:
        print(f"Loaded {len(llm_labels)} LLM relevance labels")

    summary_rows, case_metric_cache = _compute_method_summary(records, labels, llm_labels)
    repro = _compute_reproducibility(records, dynamic_method=args.dynamic_method)
    baseline_methods = [
        row["method"] for row in summary_rows if row["method"] != args.dynamic_method
    ]
    comparisons = _paired_bootstrap_comparisons(
        case_metric_cache=case_metric_cache,
        baseline_methods=baseline_methods,
        dynamic_method=args.dynamic_method,
        n_boot=args.n_boot,
    )

    output_dir = Path(args.output_dir) if args.output_dir else (
        runs_path if runs_path.is_dir() else runs_path.parent
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "run_source": str(runs_path.resolve()),
        "labels_source": str(labels_path.resolve()) if labels_path else None,
        "n_records": len(records),
        "method_summary": summary_rows,
        "reproducibility": repro,
        "paired_bootstrap": comparisons,
    }

    (output_dir / "score_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    report_md = _render_markdown_report(summary_rows, repro, comparisons)
    (output_dir / "benchmark_report.md").write_text(report_md, encoding="utf-8")
    print(f"Saved score outputs to: {output_dir}")


if __name__ == "__main__":
    main()
