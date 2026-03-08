"""Analyze literature benchmark runs: method comparison, reproducibility, and labels.

Generates:
  - simple_method_comparison/  (CSVs, stats, plots)
  - reproducibility_plots/     (CSVs, summaries, plots)
  - labels_top10_union_template.csv
  - labels_top10_union_autolabel_v1.csv
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import statistics
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy import stats as sp_stats

from scripts.benchmarks.score_lit_benchmark import (
    _disease_tokens,
    _llm_contamination_rate,
    _load_llm_labels,
    _load_runs,
    _normalize,
    _paper_contamination_rate,
    _strict_contamination_rate,
    extract_continuous_metrics,
    jaccard,
    top_k_overlap,
)


# ---------------------------------------------------------------------------
# 2a: Simple method comparison
# ---------------------------------------------------------------------------


def _enrich_records(
    records: list[dict[str, Any]],
    llm_labels: dict[tuple[str, str], bool] | None = None,
) -> list[dict[str, Any]]:
    enriched = []
    for r in records:
        if r.get("error"):
            continue
        rr = dict(r)
        m = extract_continuous_metrics(rr)
        rr.update(m)
        rr["contamination_rate"] = _paper_contamination_rate(rr)
        rr["strict_contamination_rate"] = _strict_contamination_rate(rr)
        rr["llm_contamination_rate"] = _llm_contamination_rate(rr, llm_labels or {})
        enriched.append(rr)
    return enriched


def generate_simple_method_comparison(
    records: list[dict[str, Any]],
    out_dir: Path,
    llm_labels: dict[tuple[str, str], bool] | None = None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    enriched = _enrich_records(records, llm_labels)

    # Group by (case_id, method) -> case-level means
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in enriched:
        grouped[(str(r["case_id"]), str(r["method"]))].append(r)

    case_rows: list[dict[str, Any]] = []
    for (case_id, method), rows in sorted(grouped.items()):
        comp_vals = [r["coverage_composite_pct"] for r in rows]
        contam_vals = [
            r["contamination_rate"]
            for r in rows
            if r["contamination_rate"] is not None
        ]
        strict_contam_vals = [
            r["strict_contamination_rate"]
            for r in rows
            if r["strict_contamination_rate"] is not None
        ]
        llm_contam_vals = [
            r["llm_contamination_rate"]
            for r in rows
            if r["llm_contamination_rate"] is not None
        ]
        case_rows.append(
            {
                "case_id": case_id,
                "method": method,
                "composite_cov_pct": statistics.mean(comp_vals) if comp_vals else None,
                "contamination_rate": (
                    statistics.mean(contam_vals) if contam_vals else None
                ),
                "strict_contamination_rate": (
                    statistics.mean(strict_contam_vals) if strict_contam_vals else None
                ),
                "llm_contamination_rate": (
                    statistics.mean(llm_contam_vals) if llm_contam_vals else None
                ),
                "n_repeats": len(rows),
            }
        )

    # Write case_level_means.csv
    with (out_dir / "case_level_means.csv").open("w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "case_id",
                "method",
                "composite_cov_pct",
                "contamination_rate",
                "strict_contamination_rate",
                "llm_contamination_rate",
                "n_repeats",
            ],
        )
        w.writeheader()
        w.writerows(case_rows)

    # Method summary
    by_method: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in case_rows:
        by_method[r["method"]].append(r)

    summary_rows: list[dict[str, Any]] = []
    for method in sorted(by_method):
        rows = by_method[method]
        comp_vals = [r["composite_cov_pct"] for r in rows if r["composite_cov_pct"] is not None]
        contam_vals = [
            r["contamination_rate"]
            for r in rows
            if r["contamination_rate"] is not None
        ]
        strict_contam_vals2 = [
            r["strict_contamination_rate"]
            for r in rows
            if r["strict_contamination_rate"] is not None
        ]
        llm_contam_vals2 = [
            r["llm_contamination_rate"]
            for r in rows
            if r["llm_contamination_rate"] is not None
        ]
        summary_rows.append(
            {
                "method": method,
                "n_cases": len(rows),
                "mean_composite_cov_pct": statistics.mean(comp_vals) if comp_vals else None,
                "sd_composite_cov_pct": (
                    statistics.stdev(comp_vals) if len(comp_vals) >= 2 else None
                ),
                "mean_contamination_rate": (
                    statistics.mean(contam_vals) if contam_vals else None
                ),
                "sd_contamination_rate": (
                    statistics.stdev(contam_vals) if len(contam_vals) >= 2 else None
                ),
                "mean_strict_contamination_rate": (
                    statistics.mean(strict_contam_vals2) if strict_contam_vals2 else None
                ),
                "sd_strict_contamination_rate": (
                    statistics.stdev(strict_contam_vals2) if len(strict_contam_vals2) >= 2 else None
                ),
                "mean_llm_contamination_rate": (
                    statistics.mean(llm_contam_vals2) if llm_contam_vals2 else None
                ),
                "sd_llm_contamination_rate": (
                    statistics.stdev(llm_contam_vals2) if len(llm_contam_vals2) >= 2 else None
                ),
            }
        )

    with (out_dir / "method_summary_case_mean.csv").open("w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "method",
                "n_cases",
                "mean_composite_cov_pct",
                "sd_composite_cov_pct",
                "mean_contamination_rate",
                "sd_contamination_rate",
                "mean_strict_contamination_rate",
                "sd_strict_contamination_rate",
                "mean_llm_contamination_rate",
                "sd_llm_contamination_rate",
            ],
        )
        w.writeheader()
        w.writerows(summary_rows)

    # Stats: Friedman + pairwise Wilcoxon with Holm correction
    methods = sorted(by_method.keys())
    stats_out: dict[str, Any] = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "run_dir": str(out_dir.parent),
        "n_total_runs": sum(len(v) for v in grouped.values()),
        "n_case_method_rows": len(case_rows),
        "metrics": {},
    }

    for metric_key in ("composite_cov_pct", "contamination_rate", "strict_contamination_rate", "llm_contamination_rate"):
        # Build matrix: cases x methods (only cases present in ALL methods)
        cases_per_method: dict[str, dict[str, float]] = {}
        for m in methods:
            cases_per_method[m] = {}
            for r in by_method[m]:
                val = r[metric_key]
                if val is not None:
                    cases_per_method[m][r["case_id"]] = val

        # Find cases with values in ALL methods
        all_case_sets = [set(cases_per_method[m].keys()) for m in methods]
        common_cases = sorted(set.intersection(*all_case_sets)) if all_case_sets else []

        if len(common_cases) < 3 or len(methods) < 2:
            stats_out["metrics"][metric_key] = {
                "n_complete_cases_all": len(common_cases),
                "friedman": None,
                "pairwise_wilcoxon_holm": [],
            }
            continue

        # Friedman test
        sample_arrays = [
            [cases_per_method[m][c] for c in common_cases] for m in methods
        ]
        try:
            fr_stat, fr_p = sp_stats.friedmanchisquare(*sample_arrays)
        except Exception:
            fr_stat, fr_p = None, None

        # Pairwise Wilcoxon signed-rank with Holm correction
        pairs = list(itertools.combinations(range(len(methods)), 2))
        raw_results = []
        for i, j in pairs:
            m_a, m_b = methods[i], methods[j]
            # Use cases present in both (may differ from common_cases for contamination)
            shared = sorted(
                set(cases_per_method[m_a].keys()) & set(cases_per_method[m_b].keys())
            )
            if len(shared) < 3:
                continue
            vals_a = [cases_per_method[m_a][c] for c in shared]
            vals_b = [cases_per_method[m_b][c] for c in shared]
            diffs = [a - b for a, b in zip(vals_a, vals_b)]
            if all(d == 0 for d in diffs):
                raw_results.append(
                    {
                        "method_a": m_a,
                        "method_b": m_b,
                        "n_cases": len(shared),
                        "p_value_raw": 1.0,
                        "median_diff_a_minus_b": 0.0,
                    }
                )
                continue
            try:
                _, p_raw = sp_stats.wilcoxon(vals_a, vals_b, alternative="two-sided")
            except Exception:
                p_raw = 1.0
            raw_results.append(
                {
                    "method_a": m_a,
                    "method_b": m_b,
                    "n_cases": len(shared),
                    "p_value_raw": p_raw,
                    "median_diff_a_minus_b": statistics.median(diffs),
                }
            )

        # Holm correction
        raw_results.sort(key=lambda x: x["p_value_raw"])
        n_tests = len(raw_results)
        for rank, r in enumerate(raw_results):
            r["p_value_holm"] = min(1.0, r["p_value_raw"] * (n_tests - rank))
        # Enforce monotonicity
        for k in range(1, len(raw_results)):
            raw_results[k]["p_value_holm"] = max(
                raw_results[k]["p_value_holm"], raw_results[k - 1]["p_value_holm"]
            )

        n_key = f"n_complete_cases_all{len(methods)}"
        stats_out["metrics"][metric_key] = {
            n_key: len(common_cases),
            "friedman": {
                "statistic": fr_stat,
                "p_value": fr_p,
            },
            "pairwise_wilcoxon_holm": raw_results,
        }

    with (out_dir / "stats_results.json").open("w") as f:
        json.dump(stats_out, f, indent=2, ensure_ascii=False)

    # Plots
    _plot_violin_jitter(
        case_rows,
        metric_key="composite_cov_pct",
        ylabel="Mean Composite Coverage (%)",
        out_path=out_dir / "fig_composite_cov_boxplot_case_mean.png",
    )
    _plot_violin_jitter(
        case_rows,
        metric_key="contamination_rate",
        ylabel="Disease Nonspecificity Rate",
        out_path=out_dir / "fig_contamination_boxplot_case_mean.png",
    )
    _plot_violin_jitter(
        case_rows,
        metric_key="strict_contamination_rate",
        ylabel="Strict Contamination Rate",
        out_path=out_dir / "fig_strict_contamination_boxplot_case_mean.png",
    )
    _plot_violin_jitter(
        case_rows,
        metric_key="llm_contamination_rate",
        ylabel="LLM Contamination Rate",
        out_path=out_dir / "fig_llm_contamination_boxplot_case_mean.png",
    )


def _plot_violin_jitter(
    case_rows: list[dict[str, Any]],
    metric_key: str,
    ylabel: str,
    out_path: Path,
) -> None:
    by_method: dict[str, list[float]] = defaultdict(list)
    for r in case_rows:
        val = r.get(metric_key)
        if val is not None:
            by_method[r["method"]].append(val)

    methods = sorted(by_method.keys())
    data = [by_method[m] for m in methods]

    fig, ax = plt.subplots(figsize=(max(6, len(methods) * 1.5), 5))
    positions = list(range(1, len(methods) + 1))

    parts = ax.violinplot(data, positions=positions, showmedians=False, showextrema=False)
    for pc in parts["bodies"]:
        pc.set_alpha(0.4)

    for i, (pos, vals) in enumerate(zip(positions, data)):
        jitter = np.random.default_rng(42).uniform(-0.12, 0.12, len(vals))
        ax.scatter(pos + jitter, vals, alpha=0.4, s=18, zorder=3)
        if vals:
            med = statistics.median(vals)
            ax.scatter(pos, med, marker="+", color="black", s=60, zorder=4)

    ax.set_xticks(positions)
    ax.set_xticklabels(methods, rotation=30, ha="right")
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# 2b: Reproducibility plots
# ---------------------------------------------------------------------------


def generate_reproducibility_plots(
    records: list[dict[str, Any]], dynamic_method: str, out_dir: Path
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    # Group dynamic runs by case
    by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        if r.get("method") == dynamic_method and not r.get("error"):
            by_case[str(r.get("case_id", ""))].append(r)

    # --- Pairwise similarity (jaccard + top10) ---
    all_pairs_rows: list[dict[str, Any]] = []
    case_medians_rows: list[dict[str, Any]] = []

    for case_id in sorted(by_case):
        rows = by_case[case_id]
        if len(rows) < 2:
            continue
        pmid_lists = [[str(p) for p in row.get("pmids", [])] for row in rows]
        j_scores = []
        t10_scores = []
        for a, b in itertools.combinations(pmid_lists, 2):
            j = jaccard(a, b)
            t10 = top_k_overlap(a, b, k=10)
            j_scores.append(j)
            t10_scores.append(t10)
            all_pairs_rows.append(
                {
                    "case_id": case_id,
                    "pairwise_jaccard": j,
                    "pairwise_top10_overlap": t10,
                }
            )
        n_pairs = len(j_scores)
        n_repeats = len(rows)
        case_medians_rows.append(
            {
                "case_id": case_id,
                "pairwise_jaccard_median": statistics.median(j_scores),
                "pairwise_top10_overlap_median": statistics.median(t10_scores),
                "n_pairs": n_pairs,
                "n_repeats": n_repeats,
            }
        )

    # Write CSVs
    _write_csv(
        out_dir / "dynamic_pairwise_similarity_all_pairs.csv",
        ["case_id", "pairwise_jaccard", "pairwise_top10_overlap"],
        all_pairs_rows,
    )
    _write_csv(
        out_dir / "dynamic_repro_case_medians.csv",
        [
            "case_id",
            "pairwise_jaccard_median",
            "pairwise_top10_overlap_median",
            "n_pairs",
            "n_repeats",
        ],
        case_medians_rows,
    )

    # Summary JSON
    j_all = [r["pairwise_jaccard"] for r in all_pairs_rows]
    t10_all = [r["pairwise_top10_overlap"] for r in all_pairs_rows]
    j_case = [r["pairwise_jaccard_median"] for r in case_medians_rows]
    t10_case = [r["pairwise_top10_overlap_median"] for r in case_medians_rows]
    summary = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "run_dir": str(out_dir.parent),
        "method": dynamic_method,
        "n_cases_with_repeats": len(case_medians_rows),
        "pair_level": {
            "n_pairwise_records": len(all_pairs_rows),
            "pairwise_jaccard_median": statistics.median(j_all) if j_all else None,
            "pairwise_top10_overlap_median": statistics.median(t10_all) if t10_all else None,
        },
        "case_median_level": {
            "pairwise_jaccard_median": statistics.median(j_case) if j_case else None,
            "pairwise_top10_overlap_median": (
                statistics.median(t10_case) if t10_case else None
            ),
        },
    }
    with (out_dir / "dynamic_repro_summary.json").open("w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    # --- Top-10 vs Tail-20 overlap ---
    t10t20_pair_rows: list[dict[str, Any]] = []
    t10t20_case_rows: list[dict[str, Any]] = []

    for case_id in sorted(by_case):
        rows = by_case[case_id]
        if len(rows) < 2:
            continue
        pmid_lists = [[str(p) for p in row.get("pmids", [])] for row in rows]
        t10_scores = []
        t20_scores = []
        for a, b in itertools.combinations(pmid_lists, 2):
            t10 = top_k_overlap(a, b, k=10)
            t20 = top_k_overlap(a[10:], b[10:], k=20)
            t10_scores.append(t10)
            t20_scores.append(t20)
            t10t20_pair_rows.append(
                {
                    "case_id": case_id,
                    "top10_overlap": t10,
                    "tail20_overlap": t20,
                }
            )
        n_pairs = len(t10_scores)
        n_repeats = len(rows)
        t10t20_case_rows.append(
            {
                "case_id": case_id,
                "top10_overlap_case_median": statistics.median(t10_scores),
                "tail20_overlap_case_median": statistics.median(t20_scores),
                "n_pairs": n_pairs,
                "n_repeats": n_repeats,
            }
        )

    _write_csv(
        out_dir / "dynamic_pairwise_top10_tail20_overlap.csv",
        ["case_id", "top10_overlap", "tail20_overlap"],
        t10t20_pair_rows,
    )
    _write_csv(
        out_dir / "dynamic_case_median_top10_tail20_overlap.csv",
        [
            "case_id",
            "top10_overlap_case_median",
            "tail20_overlap_case_median",
            "n_pairs",
            "n_repeats",
        ],
        t10t20_case_rows,
    )

    # Top10 vs Tail20 summary
    t10_pair_all = [r["top10_overlap"] for r in t10t20_pair_rows]
    t20_pair_all = [r["tail20_overlap"] for r in t10t20_pair_rows]
    t10_case_all = [r["top10_overlap_case_median"] for r in t10t20_case_rows]
    t20_case_all = [r["tail20_overlap_case_median"] for r in t10t20_case_rows]
    t10t20_summary = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "run_dir": str(out_dir.parent),
        "method": dynamic_method,
        "n_cases_with_repeats": len(t10t20_case_rows),
        "pairwise_records": len(t10t20_pair_rows),
        "pair_level_medians": {
            "top10_overlap": statistics.median(t10_pair_all) if t10_pair_all else None,
            "tail20_overlap": statistics.median(t20_pair_all) if t20_pair_all else None,
        },
        "case_median_level_medians": {
            "top10_overlap": (
                statistics.median(t10_case_all) if t10_case_all else None
            ),
            "tail20_overlap": (
                statistics.median(t20_case_all) if t20_case_all else None
            ),
        },
    }
    with (out_dir / "dynamic_repro_top10_tail20_summary.json").open("w") as f:
        json.dump(t10t20_summary, f, indent=2, ensure_ascii=False)

    # --- Plots ---
    # Pairwise violin: jaccard + top10
    _plot_two_metric_violin(
        data_a=[r["pairwise_jaccard"] for r in all_pairs_rows],
        data_b=[r["pairwise_top10_overlap"] for r in all_pairs_rows],
        label_a="Jaccard",
        label_b="Top-10 overlap",
        ylabel="Pairwise similarity",
        out_path=out_dir / "fig_dynamic_repro_pairwise_violin_box.png",
    )
    # Case-median violin: jaccard + top10
    _plot_two_metric_violin(
        data_a=[r["pairwise_jaccard_median"] for r in case_medians_rows],
        data_b=[r["pairwise_top10_overlap_median"] for r in case_medians_rows],
        label_a="Jaccard\n(case median)",
        label_b="Top-10 overlap\n(case median)",
        ylabel="Similarity score",
        out_path=out_dir / "fig_dynamic_repro_case_medians_violin_box.png",
    )
    # Top10 vs Tail20 pair-level
    _plot_two_metric_violin(
        data_a=[r["top10_overlap"] for r in t10t20_pair_rows],
        data_b=[r["tail20_overlap"] for r in t10t20_pair_rows],
        label_a="Top-10\noverlap",
        label_b="Tail-20\noverlap (11-30)",
        ylabel="Pairwise overlap score",
        out_path=out_dir / "fig_dynamic_repro_top10_vs_tail20_pair_violin_box.png",
    )
    # Top10 vs Tail20 case-median level
    _plot_two_metric_violin(
        data_a=[r["top10_overlap_case_median"] for r in t10t20_case_rows],
        data_b=[r["tail20_overlap_case_median"] for r in t10t20_case_rows],
        label_a="Top-10\noverlap",
        label_b="Tail-20\noverlap (11-30)",
        ylabel="Pairwise overlap score",
        out_path=out_dir / "fig_dynamic_repro_top10_vs_tail20_case_boxplot.png",
    )


def _plot_two_metric_violin(
    data_a: list[float],
    data_b: list[float],
    label_a: str,
    label_b: str,
    ylabel: str,
    out_path: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(5, 5))
    data = [data_a, data_b]
    labels = [label_a, label_b]
    colors = ["#2C7FB8", "#F28E2B"]

    parts = ax.violinplot(data, positions=[1, 2], showmedians=False, showextrema=False)
    for pc, color in zip(parts["bodies"], colors):
        pc.set_facecolor(color)
        pc.set_alpha(0.4)

    rng = np.random.default_rng(42)
    for pos, vals, color in zip([1, 2], data, colors):
        jitter = rng.uniform(-0.12, 0.12, len(vals))
        ax.scatter(pos + jitter, vals, alpha=0.4, s=18, color=color, zorder=3)
        if vals:
            med = statistics.median(vals)
            ax.scatter(pos, med, marker="+", color="black", s=60, zorder=4)

    ax.set_xticks([1, 2])
    ax.set_xticklabels(labels)
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# 3: Labels generation
# ---------------------------------------------------------------------------


def generate_labels(records: list[dict[str, Any]], run_dir: Path) -> None:
    # Collect union of top-10 PMIDs per (case_id, method) across all repeats
    union_map: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)
    case_inputs: dict[str, dict[str, Any]] = {}

    for r in records:
        if r.get("error"):
            continue
        case_id = str(r.get("case_id", ""))
        method = str(r.get("method", ""))
        pmids = [str(p) for p in r.get("pmids", [])][:10]
        papers = r.get("papers", [])

        if case_id not in case_inputs:
            case_inputs[case_id] = r.get("input", {})

        paper_titles: dict[str, str] = {}
        if isinstance(papers, list):
            for p in papers:
                if isinstance(p, dict):
                    pid = str(p.get("pmid", p.get("uid", "")))
                    title = str(p.get("title", ""))
                    if pid and title:
                        paper_titles[pid] = title

        for pmid in pmids:
            if pmid not in union_map[(case_id, method)]:
                union_map[(case_id, method)][pmid] = paper_titles.get(pmid, "")

    # Write template
    template_rows: list[dict[str, str]] = []
    for (case_id, method) in sorted(union_map.keys()):
        for pmid, title in sorted(union_map[(case_id, method)].items()):
            template_rows.append(
                {
                    "case_id": case_id,
                    "method": method,
                    "pmid": pmid,
                    "title": title,
                    "label": "",
                    "annotator": "",
                    "confidence": "",
                }
            )

    template_path = run_dir / "labels_top10_union_template.csv"
    with template_path.open("w", newline="") as f:
        w = csv.DictWriter(
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
        w.writeheader()
        w.writerows(template_rows)

    # Auto-label using heuristic
    autolabel_rows: list[dict[str, str]] = []
    for row in template_rows:
        case_id = row["case_id"]
        title = row["title"]
        inp = case_inputs.get(case_id, {})

        genes = [g.lower() for g in inp.get("genes", [])]
        pathways = [p.lower() for p in inp.get("pathways", [])]
        disease = str(inp.get("disease", ""))
        celltypes = [c.lower() for c in inp.get("celltypes", [])]

        title_norm = _normalize(title)

        gene_match = any(g in title_norm for g in genes) if genes else False
        pathway_match = any(p in title_norm for p in pathways) if pathways else False
        disease_toks = _disease_tokens(disease)
        disease_match = any(t in title_norm for t in disease_toks) if disease_toks else False
        celltype_match = (
            any(c in title_norm for c in celltypes) if celltypes else False
        )

        matches = sum([gene_match, pathway_match, disease_match, celltype_match])

        if matches >= 2:
            label = "relevant"
            confidence = "medium"
        elif matches == 1:
            label = "partial"
            confidence = "low"
        else:
            label = "irrelevant"
            confidence = "low"

        autolabel_rows.append(
            {
                "case_id": row["case_id"],
                "method": row["method"],
                "pmid": row["pmid"],
                "title": row["title"],
                "label": label,
                "annotator": "auto_heuristic_v1",
                "confidence": confidence,
            }
        )

    autolabel_path = run_dir / "labels_top10_union_autolabel_v1.csv"
    with autolabel_path.open("w", newline="") as f:
        w = csv.DictWriter(
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
        w.writeheader()
        w.writerows(autolabel_rows)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_csv(
    path: Path, fieldnames: list[str], rows: list[dict[str, Any]]
) -> None:
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-dir",
        required=True,
        help="Benchmark run directory containing raw_runs.jsonl",
    )
    parser.add_argument(
        "--dynamic-method",
        default="dynamic",
        help="Name of the dynamic method for reproducibility analysis",
    )
    parser.add_argument(
        "--skip-labels",
        action="store_true",
        help="Skip labels generation",
    )
    parser.add_argument(
        "--llm-labels",
        default="",
        help="Path to llm_relevance_labels.jsonl (auto-discovers in run dir if absent)",
    )
    return parser


def main() -> None:
    args = _build_arg_parser().parse_args()
    run_dir = Path(args.run_dir).resolve()
    records = _load_runs(run_dir)
    llm_labels_path: Path | None = None
    if args.llm_labels:
        llm_labels_path = Path(args.llm_labels)
    else:
        auto = run_dir / "llm_relevance_labels.jsonl"
        if auto.exists():
            llm_labels_path = auto
    llm_labels = _load_llm_labels(llm_labels_path)
    if llm_labels:
        print(f"Loaded {len(llm_labels)} LLM relevance labels")

    print(f"Loaded {len(records)} records from {run_dir}")

    print("Generating simple_method_comparison/ ...")
    generate_simple_method_comparison(
        records, run_dir / "simple_method_comparison", llm_labels
    )

    print("Generating reproducibility_plots/ ...")
    generate_reproducibility_plots(
        records, args.dynamic_method, run_dir / "reproducibility_plots"
    )

    if not args.skip_labels:
        print("Generating labels ...")
        generate_labels(records, run_dir)

    print("Done.")


if __name__ == "__main__":
    main()
