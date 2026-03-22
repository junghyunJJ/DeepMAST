"""Deep 2x2 factorial method comparison: Filter × SJR effect decomposition.

Generates:
  - factorial_decomposition/  (ANOVA-style effects, Wilcoxon tests, CSVs)
  - paper_pool_analysis/      (Jaccard heatmap, SJR overlap stats)
  - per_case_breakdown/       (case × method winner table, win counts)
  - coverage_decomposition/   (Gene/Pathway/CellType component analysis)

Usage:
  python -m scripts.benchmarks.compare_methods_deep \
    --run-dir docs/benchmarks/lit_repro_benchmark/results/run_20260313T094718Z_a752456d
"""

from __future__ import annotations

import argparse
import csv
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

from scripts.benchmarks.analyze_lit_benchmark import (
    _compute_hybrid_coverage,
    _enrich_records,
    _load_llm_coverage_labels,
)
from scripts.benchmarks.score_lit_benchmark import (
    _load_llm_labels,
    _load_runs,
    jaccard,
)

# -- 2×2 factorial layout ------------------------------------------------
FACTORIAL_METHODS = ["dynamic_off", "dynamic_no_sjr", "dynamic_lean", "dynamic"]

# Factor assignments:  (filter_on, sjr_on)
FACTOR_MAP: dict[str, tuple[bool, bool]] = {
    "dynamic_off": (False, False),
    "dynamic_no_sjr": (True, False),
    "dynamic_lean": (False, True),
    "dynamic": (True, True),
}


# -- helpers --------------------------------------------------------------

def _load_and_enrich(
    run_dir: Path,
) -> list[dict[str, Any]]:
    """Load raw_runs.jsonl, enrich with coverage and contamination metrics."""
    records = _load_runs(run_dir)

    llm_labels_path = run_dir / "llm_relevance_labels.jsonl"
    llm_labels = _load_llm_labels(llm_labels_path if llm_labels_path.exists() else None)

    llm_cov_path = run_dir / "llm_coverage_labels.jsonl"
    llm_coverage = _load_llm_coverage_labels(llm_cov_path if llm_cov_path.exists() else None)

    enriched = _enrich_records(records, llm_labels, llm_coverage)
    return [r for r in enriched if r.get("method") in FACTORIAL_METHODS]


def _case_level_means(
    records: list[dict[str, Any]],
    metrics: list[str],
) -> dict[tuple[str, str], dict[str, float | None]]:
    """Group by (case_id, method) and compute means for each metric.

    Returns dict keyed by (case_id, method) -> {metric: mean_value}.
    """
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        grouped[(str(r["case_id"]), str(r["method"]))].append(r)

    result: dict[tuple[str, str], dict[str, float | None]] = {}
    for (case_id, method), rows in grouped.items():
        means: dict[str, float | None] = {}
        for m in metrics:
            vals = [r[m] for r in rows if r.get(m) is not None]
            means[m] = statistics.mean(vals) if vals else None
        result[(case_id, method)] = means
    return result


def _write_csv(
    path: Path, fieldnames: list[str], rows: list[dict[str, Any]]
) -> None:
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


# =========================================================================
# 1. ANOVA-style factorial decomposition
# =========================================================================

def generate_factorial_decomposition(
    case_means: dict[tuple[str, str], dict[str, float | None]],
    out_dir: Path,
    metrics: list[str],
) -> dict[str, Any]:
    """Compute Filter/SJR main effects and interaction per case."""
    out_dir.mkdir(parents=True, exist_ok=True)

    cases = sorted({c for c, _ in case_means})
    all_rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {"generated_at_utc": datetime.now(UTC).isoformat()}

    for metric in metrics:
        metric_rows: list[dict[str, Any]] = []
        filter_effects: list[float] = []
        sjr_effects: list[float] = []
        interactions: list[float] = []

        for case_id in cases:
            vals = {}
            for method in FACTORIAL_METHODS:
                v = (case_means.get((case_id, method)) or {}).get(metric)
                if v is not None:
                    vals[method] = v

            if len(vals) < 4:
                continue

            off = vals["dynamic_off"]
            no_sjr = vals["dynamic_no_sjr"]
            lean = vals["dynamic_lean"]
            full = vals["dynamic"]

            # Main effects (averaged across the other factor level)
            filter_eff = ((no_sjr + full) / 2) - ((off + lean) / 2)
            sjr_eff = ((lean + full) / 2) - ((off + no_sjr) / 2)
            interaction = (full - no_sjr) - (lean - off)

            filter_effects.append(filter_eff)
            sjr_effects.append(sjr_eff)
            interactions.append(interaction)

            row = {
                "case_id": case_id,
                "metric": metric,
                "dynamic_off": off,
                "dynamic_no_sjr": no_sjr,
                "dynamic_lean": lean,
                "dynamic": full,
                "filter_effect": filter_eff,
                "sjr_effect": sjr_eff,
                "interaction": interaction,
            }
            metric_rows.append(row)
            all_rows.append(row)

        # Wilcoxon signed-rank for each effect vs 0
        metric_summary: dict[str, Any] = {"n_cases": len(filter_effects)}
        for name, vals in [
            ("filter", filter_effects),
            ("sjr", sjr_effects),
            ("interaction", interactions),
        ]:
            if len(vals) < 3:
                metric_summary[name] = {"mean": None, "p_value": None}
                continue
            mean_eff = statistics.mean(vals)
            median_eff = statistics.median(vals)
            if all(v == 0 for v in vals):
                p_val = 1.0
            else:
                try:
                    _, p_val = sp_stats.wilcoxon(vals, alternative="two-sided")
                except Exception:
                    p_val = 1.0
            metric_summary[name] = {
                "mean": round(mean_eff, 4),
                "median": round(median_eff, 4),
                "sd": round(statistics.stdev(vals), 4) if len(vals) >= 2 else None,
                "p_value": round(p_val, 6),
                "significant": bool(p_val < 0.05),
            }
        summary[metric] = metric_summary

    # Write per-case effects CSV
    _write_csv(
        out_dir / "per_case_effects.csv",
        [
            "case_id", "metric",
            "dynamic_off", "dynamic_no_sjr", "dynamic_lean", "dynamic",
            "filter_effect", "sjr_effect", "interaction",
        ],
        all_rows,
    )

    # Write summary JSON
    with (out_dir / "factorial_summary.json").open("w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    # Plot: effect size distributions
    _plot_effect_distributions(all_rows, metrics, out_dir)

    return summary


def _plot_effect_distributions(
    rows: list[dict[str, Any]],
    metrics: list[str],
    out_dir: Path,
) -> None:
    """Forest-plot style: Filter, SJR, Interaction effect per metric."""
    target_metrics = [
        m for m in metrics
        if any(r["metric"] == m for r in rows)
    ]
    if not target_metrics:
        return

    fig, axes = plt.subplots(
        1, len(target_metrics),
        figsize=(4 * len(target_metrics), 5),
        sharey=True,
    )
    if len(target_metrics) == 1:
        axes = [axes]

    effect_names = ["filter_effect", "sjr_effect", "interaction"]
    colors = ["#D55E00", "#56B4E9", "#999999"]
    labels = ["Filter", "SJR", "Interaction"]

    for ax, metric in zip(axes, target_metrics):
        metric_rows = [r for r in rows if r["metric"] == metric]
        positions = [1, 2, 3]

        for pos, eff_name, color, label in zip(positions, effect_names, colors, labels):
            vals = [r[eff_name] for r in metric_rows]
            if not vals:
                continue
            rng = np.random.default_rng(42)
            jitter = rng.uniform(-0.15, 0.15, len(vals))
            ax.scatter(pos + jitter, vals, alpha=0.4, s=18, color=color, zorder=3)
            med = statistics.median(vals)
            ax.scatter(pos, med, marker="D", color="black", s=40, zorder=4)

        ax.axhline(0, color="grey", linestyle="--", alpha=0.5)
        ax.set_xticks(positions)
        ax.set_xticklabels(labels, rotation=30, ha="right")
        title = metric.replace("_", " ").replace("pct", "%")
        ax.set_title(title, fontsize=10)
        ax.grid(axis="y", alpha=0.3)

    axes[0].set_ylabel("Effect size (pp)")
    fig.suptitle("2×2 Factorial Effect Decomposition", fontsize=12, fontweight="bold")
    fig.tight_layout()
    fig.savefig(out_dir / "fig_factorial_effects.png", dpi=300, bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# 2. Paper pool analysis (Jaccard heatmap)
# =========================================================================

def generate_paper_pool_analysis(
    records: list[dict[str, Any]],
    out_dir: Path,
) -> None:
    """Compute per-case Jaccard between all 4 methods and create heatmap."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # Group by (case_id, method) -> list of pmid sets (one per repeat)
    by_cm: dict[tuple[str, str], list[set[str]]] = defaultdict(list)
    for r in records:
        case_id = str(r.get("case_id", ""))
        method = str(r.get("method", ""))
        pmids = set(str(p) for p in r.get("pmids", []))
        if pmids and method in FACTORIAL_METHODS:
            by_cm[(case_id, method)].append(pmids)

    cases = sorted({c for c, _ in by_cm})
    methods = FACTORIAL_METHODS

    # Compute per-case Jaccard: union of all repeat PMIDs per method, then Jaccard
    n = len(methods)
    jaccard_matrix = np.zeros((n, n))
    jaccard_counts = np.zeros((n, n))
    pair_rows: list[dict[str, Any]] = []

    for case_id in cases:
        # Union of all repeat PMIDs per method
        method_pmids: dict[str, set[str]] = {}
        for i, m in enumerate(methods):
            repeats = by_cm.get((case_id, m), [])
            if repeats:
                method_pmids[m] = set().union(*repeats)

        if len(method_pmids) < 2:
            continue

        for i, ma in enumerate(methods):
            for j, mb in enumerate(methods):
                if ma in method_pmids and mb in method_pmids:
                    j_score = jaccard(
                        list(method_pmids[ma]),
                        list(method_pmids[mb]),
                    )
                    jaccard_matrix[i, j] += j_score
                    jaccard_counts[i, j] += 1

                    if i < j:
                        pair_rows.append({
                            "case_id": case_id,
                            "method_a": ma,
                            "method_b": mb,
                            "jaccard": round(j_score, 4),
                            "n_union_a": len(method_pmids[ma]),
                            "n_union_b": len(method_pmids[mb]),
                            "n_intersection": len(method_pmids[ma] & method_pmids[mb]),
                        })

    # Average Jaccard matrix
    with np.errstate(divide="ignore", invalid="ignore"):
        avg_jaccard = np.where(
            jaccard_counts > 0,
            jaccard_matrix / jaccard_counts,
            0.0,
        )

    # Write pairwise CSV
    _write_csv(
        out_dir / "pairwise_jaccard_per_case.csv",
        ["case_id", "method_a", "method_b", "jaccard", "n_union_a", "n_union_b", "n_intersection"],
        pair_rows,
    )

    # Write average Jaccard matrix CSV
    matrix_rows = []
    for i, ma in enumerate(methods):
        row = {"method": ma}
        for j, mb in enumerate(methods):
            row[mb] = round(avg_jaccard[i, j], 3)
        matrix_rows.append(row)
    _write_csv(
        out_dir / "avg_jaccard_matrix.csv",
        ["method"] + methods,
        matrix_rows,
    )

    # SJR grouping analysis
    sjr_off = {"dynamic_off", "dynamic_no_sjr"}
    sjr_on = {"dynamic_lean", "dynamic"}
    within_sjr_off = [r["jaccard"] for r in pair_rows if r["method_a"] in sjr_off and r["method_b"] in sjr_off]
    within_sjr_on = [r["jaccard"] for r in pair_rows if r["method_a"] in sjr_on and r["method_b"] in sjr_on]
    across_sjr = [
        r["jaccard"] for r in pair_rows
        if (r["method_a"] in sjr_off and r["method_b"] in sjr_on)
        or (r["method_a"] in sjr_on and r["method_b"] in sjr_off)
    ]

    grouping_summary = {
        "within_sjr_off": {
            "pairs": "dynamic_off vs dynamic_no_sjr",
            "n": len(within_sjr_off),
            "mean_jaccard": round(statistics.mean(within_sjr_off), 3) if within_sjr_off else None,
            "median_jaccard": round(statistics.median(within_sjr_off), 3) if within_sjr_off else None,
        },
        "within_sjr_on": {
            "pairs": "dynamic_lean vs dynamic",
            "n": len(within_sjr_on),
            "mean_jaccard": round(statistics.mean(within_sjr_on), 3) if within_sjr_on else None,
            "median_jaccard": round(statistics.median(within_sjr_on), 3) if within_sjr_on else None,
        },
        "across_sjr_groups": {
            "pairs": "SJR_OFF vs SJR_ON",
            "n": len(across_sjr),
            "mean_jaccard": round(statistics.mean(across_sjr), 3) if across_sjr else None,
            "median_jaccard": round(statistics.median(across_sjr), 3) if across_sjr else None,
        },
    }
    with (out_dir / "sjr_grouping_summary.json").open("w") as f:
        json.dump(grouping_summary, f, indent=2, ensure_ascii=False)

    # Heatmap
    _plot_jaccard_heatmap(avg_jaccard, methods, out_dir)


def _plot_jaccard_heatmap(
    matrix: np.ndarray,
    methods: list[str],
    out_dir: Path,
) -> None:
    """Draw annotated 4×4 Jaccard heatmap."""
    short = {
        "dynamic_off": "Base\n(All OFF)",
        "dynamic_no_sjr": "+Filter",
        "dynamic_lean": "+SJR",
        "dynamic": "+Filter\n+SJR",
    }
    labels = [short.get(m, m) for m in methods]

    fig, ax = plt.subplots(figsize=(6, 5))
    im = ax.imshow(matrix, cmap="YlOrRd", vmin=0, vmax=1, aspect="auto")

    for i in range(len(methods)):
        for j in range(len(methods)):
            val = matrix[i, j]
            color = "white" if val > 0.7 else "black"
            ax.text(j, i, f"{val:.2f}", ha="center", va="center", color=color, fontsize=11)

    ax.set_xticks(range(len(methods)))
    ax.set_yticks(range(len(methods)))
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_title("Paper Pool Overlap (Mean Jaccard)", fontsize=12, fontweight="bold")

    cbar = fig.colorbar(im, ax=ax, shrink=0.8)
    cbar.set_label("Jaccard similarity")

    fig.tight_layout()
    fig.savefig(out_dir / "fig_jaccard_heatmap.png", dpi=300, bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# 3. Per-case breakdown (winner table)
# =========================================================================

def generate_per_case_breakdown(
    case_means: dict[tuple[str, str], dict[str, float | None]],
    out_dir: Path,
    metric: str = "hybrid_composite_cov_pct",
) -> None:
    """For each case, identify best method and compute win counts."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cases = sorted({c for c, _ in case_means})

    rows: list[dict[str, Any]] = []
    win_count: dict[str, int] = defaultdict(int)

    for case_id in cases:
        best_method = None
        best_val = -1.0
        row: dict[str, Any] = {"case_id": case_id}

        for method in FACTORIAL_METHODS:
            val = (case_means.get((case_id, method)) or {}).get(metric)
            if val is not None:
                row[method] = round(val, 2)
                if val > best_val:
                    best_val = val
                    best_method = method
            else:
                row[method] = None

        row["winner"] = best_method
        row["best_value"] = round(best_val, 2) if best_val >= 0 else None

        # Check for ties (within 0.5pp)
        tied = [
            m for m in FACTORIAL_METHODS
            if (case_means.get((case_id, m)) or {}).get(metric) is not None
            and abs(((case_means.get((case_id, m)) or {}).get(metric) or 0) - best_val) < 0.5
        ]
        row["tied_methods"] = ";".join(tied) if len(tied) > 1 else ""

        if best_method:
            win_count[best_method] += 1
        rows.append(row)

    # Write per-case table
    _write_csv(
        out_dir / "per_case_winners.csv",
        ["case_id"] + FACTORIAL_METHODS + ["winner", "best_value", "tied_methods"],
        rows,
    )

    # Win count summary
    total = sum(win_count.values())
    win_rows = [
        {
            "method": m,
            "wins": win_count.get(m, 0),
            "win_pct": round(100 * win_count.get(m, 0) / total, 1) if total > 0 else 0,
        }
        for m in FACTORIAL_METHODS
    ]
    _write_csv(
        out_dir / "win_counts.csv",
        ["method", "wins", "win_pct"],
        win_rows,
    )

    # Head-to-head matrix
    h2h_rows: list[dict[str, Any]] = []
    for ma in FACTORIAL_METHODS:
        row: dict[str, Any] = {"method": ma}
        for mb in FACTORIAL_METHODS:
            if ma == mb:
                row[mb] = "-"
                continue
            a_wins = 0
            for case_id in cases:
                va = (case_means.get((case_id, ma)) or {}).get(metric)
                vb = (case_means.get((case_id, mb)) or {}).get(metric)
                if va is not None and vb is not None and va > vb:
                    a_wins += 1
            row[mb] = a_wins
        h2h_rows.append(row)

    _write_csv(
        out_dir / "head_to_head_matrix.csv",
        ["method"] + FACTORIAL_METHODS,
        h2h_rows,
    )

    # Plot win counts
    _plot_win_counts(win_count, out_dir)


def _plot_win_counts(
    win_count: dict[str, int],
    out_dir: Path,
) -> None:
    short = {
        "dynamic_off": "Base\n(All OFF)",
        "dynamic_no_sjr": "+Filter",
        "dynamic_lean": "+SJR",
        "dynamic": "+Filter\n+SJR",
    }
    colors_map = {
        "dynamic_off": "#E69F00",
        "dynamic_no_sjr": "#D55E00",
        "dynamic_lean": "#56B4E9",
        "dynamic": "#CC79A7",
    }
    methods = FACTORIAL_METHODS
    labels = [short.get(m, m) for m in methods]
    counts = [win_count.get(m, 0) for m in methods]
    colors = [colors_map.get(m, "#999") for m in methods]

    fig, ax = plt.subplots(figsize=(6, 4))
    bars = ax.bar(labels, counts, color=colors, edgecolor="black", linewidth=0.5)
    for bar, c in zip(bars, counts):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                str(c), ha="center", va="bottom", fontsize=11)

    ax.set_ylabel("Number of Cases Won")
    ax.set_title("Per-Case Winner Count (Hybrid Composite Coverage)", fontsize=11, fontweight="bold")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_dir / "fig_win_counts.png", dpi=300, bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# 4. Coverage decomposition (Gene / Pathway / CellType)
# =========================================================================

def generate_coverage_decomposition(
    case_means: dict[tuple[str, str], dict[str, float | None]],
    out_dir: Path,
) -> None:
    """Show where coverage differences come from: Gene vs Pathway vs CellType."""
    out_dir.mkdir(parents=True, exist_ok=True)

    categories = ["hybrid_gene_coverage_pct", "hybrid_pathway_coverage_pct", "hybrid_celltype_coverage_pct"]
    cat_labels = {"hybrid_gene_coverage_pct": "Gene", "hybrid_pathway_coverage_pct": "Pathway", "hybrid_celltype_coverage_pct": "CellType"}

    cases = sorted({c for c, _ in case_means})

    # Per method, per category means
    summary_rows: list[dict[str, Any]] = []
    for method in FACTORIAL_METHODS:
        row: dict[str, Any] = {"method": method}
        for cat in categories:
            vals = [
                (case_means.get((c, method)) or {}).get(cat)
                for c in cases
            ]
            vals = [v for v in vals if v is not None]
            row[f"mean_{cat_labels[cat]}"] = round(statistics.mean(vals), 2) if vals else None
            row[f"sd_{cat_labels[cat]}"] = round(statistics.stdev(vals), 2) if len(vals) >= 2 else None
        summary_rows.append(row)

    _write_csv(
        out_dir / "category_summary.csv",
        ["method"] + [f"mean_{cat_labels[c]}" for c in categories] + [f"sd_{cat_labels[c]}" for c in categories],
        summary_rows,
    )

    # Per-case Filter effect decomposed by category
    decomp_rows: list[dict[str, Any]] = []
    for case_id in cases:
        row: dict[str, Any] = {"case_id": case_id}
        for cat in categories:
            label = cat_labels[cat]
            vals = {}
            for m in FACTORIAL_METHODS:
                v = (case_means.get((case_id, m)) or {}).get(cat)
                if v is not None:
                    vals[m] = v
            if len(vals) == 4:
                filter_eff = ((vals["dynamic_no_sjr"] + vals["dynamic"]) / 2) - \
                             ((vals["dynamic_off"] + vals["dynamic_lean"]) / 2)
                sjr_eff = ((vals["dynamic_lean"] + vals["dynamic"]) / 2) - \
                          ((vals["dynamic_off"] + vals["dynamic_no_sjr"]) / 2)
                row[f"filter_effect_{label}"] = round(filter_eff, 2)
                row[f"sjr_effect_{label}"] = round(sjr_eff, 2)
        decomp_rows.append(row)

    _write_csv(
        out_dir / "per_case_category_effects.csv",
        ["case_id"]
        + [f"filter_effect_{cat_labels[c]}" for c in categories]
        + [f"sjr_effect_{cat_labels[c]}" for c in categories],
        decomp_rows,
    )

    # Wilcoxon per category for Filter and SJR effects
    cat_stats: dict[str, Any] = {}
    for cat in categories:
        label = cat_labels[cat]
        filter_vals = [r.get(f"filter_effect_{label}") for r in decomp_rows]
        filter_vals = [v for v in filter_vals if v is not None]
        sjr_vals = [r.get(f"sjr_effect_{label}") for r in decomp_rows]
        sjr_vals = [v for v in sjr_vals if v is not None]

        cat_entry: dict[str, Any] = {}
        for name, vals in [("filter", filter_vals), ("sjr", sjr_vals)]:
            if len(vals) < 3:
                cat_entry[name] = {"mean": None, "p_value": None}
                continue
            try:
                _, p = sp_stats.wilcoxon(vals, alternative="two-sided")
            except Exception:
                p = 1.0
            cat_entry[name] = {
                "mean": round(statistics.mean(vals), 3),
                "median": round(statistics.median(vals), 3),
                "p_value": round(p, 6),
                "significant": bool(p < 0.05),
            }
        cat_stats[label] = cat_entry

    with (out_dir / "category_effect_stats.json").open("w") as f:
        json.dump(cat_stats, f, indent=2, ensure_ascii=False)

    # Plot: grouped bar of mean coverage by category and method
    _plot_category_decomposition(summary_rows, cat_labels, out_dir)


def _plot_category_decomposition(
    summary_rows: list[dict[str, Any]],
    cat_labels: dict[str, str],
    out_dir: Path,
) -> None:
    short = {
        "dynamic_off": "Base",
        "dynamic_no_sjr": "+Filter",
        "dynamic_lean": "+SJR",
        "dynamic": "+Filter+SJR",
    }
    colors_list = ["#E69F00", "#D55E00", "#56B4E9", "#CC79A7"]
    cats = list(cat_labels.values())
    x = np.arange(len(cats))
    width = 0.18

    fig, ax = plt.subplots(figsize=(8, 5))
    for i, row in enumerate(summary_rows):
        method = row["method"]
        vals = [row.get(f"mean_{c}", 0) or 0 for c in cats]
        ax.bar(x + i * width, vals, width, label=short.get(method, method),
               color=colors_list[i], edgecolor="black", linewidth=0.3)

    ax.set_xticks(x + 1.5 * width)
    ax.set_xticklabels(cats, fontsize=11)
    ax.set_ylabel("Hybrid Coverage (%)")
    ax.set_title("Coverage by Category and Method", fontsize=12, fontweight="bold")
    ax.legend(loc="lower right", fontsize=9)
    ax.grid(axis="y", alpha=0.3)
    ax.set_ylim(0, 105)
    fig.tight_layout()
    fig.savefig(out_dir / "fig_category_decomposition.png", dpi=300, bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# CLI
# =========================================================================

def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--run-dir",
        required=True,
        help="Benchmark run directory containing raw_runs.jsonl",
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help="Output directory (default: <run-dir>/deep_comparison/)",
    )
    return parser


def main() -> None:
    args = _build_arg_parser().parse_args()
    run_dir = Path(args.run_dir).resolve()
    out_base = Path(args.output_dir) if args.output_dir else run_dir / "deep_comparison"

    print(f"Loading from {run_dir} ...")
    records = _load_and_enrich(run_dir)
    print(f"  {len(records)} enriched records (2×2 factorial methods only)")

    metrics = [
        "hybrid_composite_cov_pct",
        "hybrid_gene_coverage_pct",
        "hybrid_pathway_coverage_pct",
        "hybrid_celltype_coverage_pct",
        "llm_contamination_rate",
    ]

    case_means = _case_level_means(records, metrics)
    print(f"  {len(case_means)} (case, method) groups")

    print("1. Factorial decomposition ...")
    summary = generate_factorial_decomposition(case_means, out_base / "factorial_decomposition", metrics)
    for metric, s in summary.items():
        if isinstance(s, dict) and "n_cases" in s:
            f_info = s.get("filter", {})
            s_info = s.get("sjr", {})
            print(f"   {metric}: Filter={f_info.get('mean','?')} (p={f_info.get('p_value','?')}), "
                  f"SJR={s_info.get('mean','?')} (p={s_info.get('p_value','?')})")

    print("2. Paper pool analysis ...")
    generate_paper_pool_analysis(records, out_base / "paper_pool_analysis")

    print("3. Per-case breakdown ...")
    generate_per_case_breakdown(case_means, out_base / "per_case_breakdown")

    print("4. Coverage decomposition ...")
    generate_coverage_decomposition(case_means, out_base / "coverage_decomposition")

    print(f"Done. Outputs in {out_base}")


if __name__ == "__main__":
    main()
