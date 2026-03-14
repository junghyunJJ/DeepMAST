"""Generate publication-quality figures for the literature search benchmark.

Produces 5 figures:
  fig1: 2-panel hybrid composite coverage (shared vs independent)
  fig2: String vs hybrid delta (LLM recovery effect)
  fig3: Category heatmap (method x category, both experiments)
  fig4: Ablation feature matrix
  fig5: Reproducibility violin (top-10 vs tail-20)
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# ---------------------------------------------------------------------------
# Style constants
# ---------------------------------------------------------------------------
COLOR_BLUE = "#2C7FB8"
COLOR_ORANGE = "#F28E2B"
COLOR_GREEN = "#59A14F"
COLOR_RED = "#E15759"
COLOR_PURPLE = "#B07AA1"
COLORS_5 = [COLOR_BLUE, COLOR_ORANGE, COLOR_GREEN, COLOR_RED, COLOR_PURPLE]

# 5 dynamic methods in desired order
DYNAMIC_METHODS = [
    "dynamic_off",
    "dynamic_lean",
    "dynamic",
    "dynamic_coverage_weighted",
    "dynamic_filter_coverage_weighted",
]
METHOD_LABELS = {
    "dynamic_off": "off",
    "dynamic_lean": "lean",
    "dynamic": "dyn",
    "dynamic_coverage_weighted": "cov_w",
    "dynamic_filter_coverage_weighted": "filt+cov_w",
}

DPI = 300


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _float(val: str | None) -> float | None:
    if val is None or val.strip() == "":
        return None
    return float(val)


def _load_method_summary(run_dir: Path) -> dict[str, dict[str, float | None]]:
    """Load method_summary_case_mean.csv -> {method: {col: val}}."""
    rows = _load_csv(run_dir / "simple_method_comparison" / "method_summary_case_mean.csv")
    out: dict[str, dict[str, float | None]] = {}
    for r in rows:
        method = r["method"]
        out[method] = {k: _float(v) for k, v in r.items() if k != "method"}
    return out


def _load_case_level(run_dir: Path) -> list[dict[str, float | None | str]]:
    """Load case_level_means.csv."""
    rows = _load_csv(run_dir / "simple_method_comparison" / "case_level_means.csv")
    result = []
    for r in rows:
        parsed: dict[str, float | None | str] = {"case_id": r["case_id"], "method": r["method"]}
        for k, v in r.items():
            if k not in ("case_id", "method"):
                parsed[k] = _float(v)
        result.append(parsed)
    return result


def _load_repro_top10_tail20(run_dir: Path) -> list[dict[str, float | str]]:
    """Load dynamic_case_median_top10_tail20_overlap.csv."""
    path = run_dir / "reproducibility_plots" / "dynamic_case_median_top10_tail20_overlap.csv"
    rows = _load_csv(path)
    result = []
    for r in rows:
        result.append(
            {
                "case_id": r["case_id"],
                "top10_overlap_case_median": float(r["top10_overlap_case_median"]),
                "tail20_overlap_case_median": float(r["tail20_overlap_case_median"]),
            }
        )
    return result


# ---------------------------------------------------------------------------
# Panel label helper
# ---------------------------------------------------------------------------


def _add_panel_label(ax: plt.Axes, label: str) -> None:
    ax.text(
        -0.02,
        1.06,
        label,
        transform=ax.transAxes,
        fontsize=18,
        fontweight="bold",
        va="bottom",
        ha="right",
        bbox=dict(boxstyle="round,pad=0.15", facecolor="white", alpha=0.75, edgecolor="none"),
    )


# ---------------------------------------------------------------------------
# Figure 1: Main Coverage (2-panel)
# ---------------------------------------------------------------------------


def plot_fig1(
    case_shared: list[dict],
    case_indep: list[dict],
    out_dir: Path,
) -> None:
    """Grouped bar chart: hybrid composite coverage, shared vs independent."""
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(12, 5), constrained_layout=True)

    for ax, case_data, title in [
        (ax_a, case_shared, "(A) Shared-Queries (Ablation)"),
        (ax_b, case_indep, "(B) Independent Queries (End-to-End)"),
    ]:
        means = []
        sds = []
        labels = []
        for m in DYNAMIC_METHODS:
            vals = [
                r["hybrid_composite_cov_pct"]
                for r in case_data
                if r["method"] == m and r["hybrid_composite_cov_pct"] is not None
            ]
            means.append(np.mean(vals) if vals else 0)
            sds.append(np.std(vals, ddof=1) if len(vals) >= 2 else 0)
            labels.append(METHOD_LABELS[m])

        x = np.arange(len(DYNAMIC_METHODS))
        bars = ax.bar(x, means, yerr=sds, capsize=4, color=COLORS_5, edgecolor="black", linewidth=0.5, width=0.6)

        # Value labels on bars
        for bar, mean_val in zip(bars, means):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.5,
                f"{mean_val:.1f}",
                ha="center",
                va="bottom",
                fontsize=8,
                fontweight="bold",
            )

        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=10)
        ax.set_ylabel("Hybrid Composite Coverage (%)", fontsize=11)
        ax.set_title(title, fontsize=12, fontweight="bold")
        ax.set_ylim(70, 92)
        ax.grid(axis="y", alpha=0.3)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    _add_panel_label(ax_a, "A")
    _add_panel_label(ax_b, "B")

    out_path = out_dir / "fig1_hybrid_coverage_comparison"
    fig.savefig(out_path.with_suffix(".png"), dpi=DPI, bbox_inches="tight")
    fig.savefig(out_path.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {out_path.with_suffix('.png')}")


# ---------------------------------------------------------------------------
# Figure 2: String vs Hybrid Delta
# ---------------------------------------------------------------------------


def plot_fig2(
    summary: dict[str, dict[str, float | None]],
    out_dir: Path,
) -> None:
    """Paired bar chart showing string coverage (base) + LLM recovery (delta)."""
    fig, ax = plt.subplots(figsize=(8, 5))

    x = np.arange(len(DYNAMIC_METHODS))
    width = 0.55

    string_vals = []
    hybrid_vals = []
    delta_vals = []
    labels = []

    for m in DYNAMIC_METHODS:
        s = summary.get(m, {})
        string_cov = s.get("mean_composite_cov_pct") or 0.0
        hybrid_cov = s.get("mean_hybrid_composite_cov_pct") or 0.0
        delta = hybrid_cov - string_cov
        string_vals.append(string_cov)
        hybrid_vals.append(hybrid_cov)
        delta_vals.append(delta)
        labels.append(METHOD_LABELS[m])

    # Stacked bar: base (string) + delta (LLM recovery)
    bars_base = ax.bar(x, string_vals, width, label="String Coverage", color=COLOR_BLUE, edgecolor="black", linewidth=0.5)
    bars_delta = ax.bar(
        x,
        delta_vals,
        width,
        bottom=string_vals,
        label="LLM Recovery (+\u0394)",
        color=COLOR_ORANGE,
        edgecolor="black",
        linewidth=0.5,
    )

    # Annotate delta values
    for i, (sv, dv) in enumerate(zip(string_vals, delta_vals)):
        if dv > 0.3:
            ax.text(
                x[i],
                sv + dv / 2,
                f"+{dv:.1f}",
                ha="center",
                va="center",
                fontsize=9,
                fontweight="bold",
                color="white",
            )
        # Total hybrid value on top
        ax.text(
            x[i],
            sv + dv + 0.5,
            f"{sv + dv:.1f}",
            ha="center",
            va="bottom",
            fontsize=8,
            fontweight="bold",
        )

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=10)
    ax.set_ylabel("Composite Coverage (%)", fontsize=11)
    ax.set_title("String vs Hybrid Coverage: LLM Recovery Effect", fontsize=12, fontweight="bold")
    ax.set_ylim(0, 95)
    ax.legend(loc="upper left", framealpha=0.9, fontsize=10)
    ax.grid(axis="y", alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    out_path = out_dir / "fig2_string_vs_hybrid_delta"
    fig.savefig(out_path.with_suffix(".png"), dpi=DPI, bbox_inches="tight")
    fig.savefig(out_path.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {out_path.with_suffix('.png')}")


# ---------------------------------------------------------------------------
# Figure 3: Category Heatmap
# ---------------------------------------------------------------------------


def plot_fig3(
    summary_shared: dict[str, dict[str, float | None]],
    summary_indep: dict[str, dict[str, float | None]],
    out_dir: Path,
) -> None:
    """Method x Category heatmap, side-by-side for both experiments."""
    categories = ["Gene", "Pathway", "CellType", "Composite"]
    cat_keys = [
        "mean_hybrid_gene_coverage_pct",
        "mean_hybrid_pathway_coverage_pct",
        "mean_hybrid_celltype_coverage_pct",
        "mean_hybrid_composite_cov_pct",
    ]

    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(12, 4), constrained_layout=True)

    for ax, summary, title in [
        (ax_a, summary_shared, "(A) Shared-Queries"),
        (ax_b, summary_indep, "(B) Independent Queries"),
    ]:
        matrix = []
        row_labels = []
        for m in DYNAMIC_METHODS:
            s = summary.get(m, {})
            row = [s.get(k) or 0.0 for k in cat_keys]
            matrix.append(row)
            row_labels.append(METHOD_LABELS[m])

        data = np.array(matrix)

        im = ax.imshow(data, cmap="YlOrRd", aspect="auto", vmin=70, vmax=100)
        ax.set_xticks(np.arange(len(categories)))
        ax.set_xticklabels(categories, fontsize=10)
        ax.set_yticks(np.arange(len(DYNAMIC_METHODS)))
        ax.set_yticklabels(row_labels, fontsize=10)
        ax.set_title(title, fontsize=12, fontweight="bold")

        # Annotate cells
        for i in range(len(DYNAMIC_METHODS)):
            for j in range(len(categories)):
                val = data[i, j]
                color = "white" if val > 88 else "black"
                ax.text(j, i, f"{val:.1f}", ha="center", va="center", fontsize=9, fontweight="bold", color=color)

    fig.colorbar(im, ax=[ax_a, ax_b], shrink=0.8, label="Hybrid Coverage (%)")
    _add_panel_label(ax_a, "A")
    _add_panel_label(ax_b, "B")

    out_path = out_dir / "fig3_category_heatmap"
    fig.savefig(out_path.with_suffix(".png"), dpi=DPI, bbox_inches="tight")
    fig.savefig(out_path.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {out_path.with_suffix('.png')}")


# ---------------------------------------------------------------------------
# Figure 4: Ablation Feature Matrix
# ---------------------------------------------------------------------------


def plot_fig4(
    summary_shared: dict[str, dict[str, float | None]],
    out_dir: Path,
) -> None:
    """ON/OFF matrix with coverage values, table-style figure."""
    feature_cols = ["Disease\nFilter", "Coverage\nSort", "SJR\nSort", "Disease-Rel.\nReranking"]
    feature_matrix_ext = {
        "dynamic_off": (False, False, False, False),
        "dynamic_lean": (False, False, True, False),
        "dynamic": (True, False, True, False),
        "dynamic_coverage_weighted": (True, True, True, False),
        "dynamic_filter_coverage_weighted": (True, True, True, True),
    }

    # Sort methods by hybrid composite coverage
    methods_sorted = sorted(
        DYNAMIC_METHODS,
        key=lambda m: summary_shared.get(m, {}).get("mean_hybrid_composite_cov_pct") or 0,
    )

    n_feat = len(feature_cols)
    n_meth = len(methods_sorted)

    fig, ax = plt.subplots(figsize=(10, 3.5))
    ax.set_xlim(-0.6, n_feat + 1.4)
    ax.set_ylim(-0.6, n_meth - 0.4)
    ax.invert_yaxis()

    # Draw ON/OFF markers
    for i, m in enumerate(methods_sorted):
        flags = feature_matrix_ext[m]
        for j, on in enumerate(flags):
            if on:
                ax.add_patch(plt.Rectangle((j - 0.3, i - 0.3), 0.6, 0.6, facecolor=COLOR_BLUE, edgecolor="white", linewidth=1, zorder=3))
                ax.text(j, i, "\u2713", ha="center", va="center", fontsize=13, fontweight="bold", color="white", zorder=4)
            else:
                ax.add_patch(plt.Rectangle((j - 0.3, i - 0.3), 0.6, 0.6, facecolor="#E8E8E8", edgecolor="white", linewidth=1, zorder=3))

    # Coverage column (rightmost)
    cov_x = n_feat + 0.5
    ax.axvline(x=n_feat - 0.5, color="#CCCCCC", linewidth=1, linestyle="--")
    for i, m in enumerate(methods_sorted):
        cov_val = summary_shared.get(m, {}).get("mean_hybrid_composite_cov_pct") or 0
        ax.text(
            cov_x,
            i,
            f"{cov_val:.1f}%",
            ha="center",
            va="center",
            fontsize=12,
            fontweight="bold",
            color=COLOR_BLUE,
        )

    # Column headers
    for j, col_label in enumerate(feature_cols):
        ax.text(j, -0.55, col_label, ha="center", va="bottom", fontsize=9, fontweight="bold")
    ax.text(cov_x, -0.55, "Hybrid\nComposite", ha="center", va="bottom", fontsize=9, fontweight="bold")

    # Row labels
    ax.set_yticks(range(n_meth))
    ax.set_yticklabels([METHOD_LABELS[m] for m in methods_sorted], fontsize=11, fontweight="bold")

    ax.set_xticks([])
    ax.grid(False)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(length=0)

    ax.set_title(
        "Ablation Feature Matrix (Shared-Queries)",
        fontsize=13,
        fontweight="bold",
        pad=40,
    )

    out_path = out_dir / "fig4_ablation_matrix"
    fig.savefig(out_path.with_suffix(".png"), dpi=DPI, bbox_inches="tight")
    fig.savefig(out_path.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {out_path.with_suffix('.png')}")


# ---------------------------------------------------------------------------
# Figure 5: Reproducibility (Top-10 vs Tail-20)
# ---------------------------------------------------------------------------


def plot_fig5(
    repro_data: list[dict],
    out_dir: Path,
) -> None:
    """Violin + jitter: top-10 vs tail-20 overlap."""
    import statistics

    top10_vals = [r["top10_overlap_case_median"] for r in repro_data]
    tail20_vals = [r["tail20_overlap_case_median"] for r in repro_data]

    fig, ax = plt.subplots(figsize=(5, 5))
    data = [top10_vals, tail20_vals]
    labels_plot = ["Top-10\noverlap", "Tail-20\noverlap"]
    colors = [COLOR_BLUE, COLOR_ORANGE]

    parts = ax.violinplot(data, positions=[1, 2], showmedians=False, showextrema=False)
    for pc, color in zip(parts["bodies"], colors):
        pc.set_facecolor(color)
        pc.set_alpha(0.4)

    rng = np.random.default_rng(42)
    for pos, vals, color in zip([1, 2], data, colors):
        jitter = rng.uniform(-0.12, 0.12, len(vals))
        ax.scatter(pos + jitter, vals, alpha=0.5, s=22, color=color, zorder=3, edgecolors="none")
        if vals:
            med = statistics.median(vals)
            ax.scatter(pos, med, marker="+", color="black", s=80, zorder=4, linewidths=2)

    ax.set_xticks([1, 2])
    ax.set_xticklabels(labels_plot, fontsize=11)
    ax.set_ylabel("Pairwise Overlap Score", fontsize=11)
    ax.set_title("Reproducibility: Top-10 vs Tail-20", fontsize=12, fontweight="bold")
    ax.set_ylim(-0.05, 1.1)
    ax.grid(axis="y", alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # Add median annotation
    med_top10 = statistics.median(top10_vals)
    med_tail20 = statistics.median(tail20_vals)
    ax.text(
        0.98,
        0.02,
        f"Median: Top-10={med_top10:.2f}, Tail-20={med_tail20:.2f}",
        transform=ax.transAxes,
        fontsize=8,
        ha="right",
        va="bottom",
        style="italic",
        color="#555555",
    )

    out_path = out_dir / "fig5_reproducibility_top10_tail20"
    fig.savefig(out_path.with_suffix(".png"), dpi=DPI, bbox_inches="tight")
    fig.savefig(out_path.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {out_path.with_suffix('.png')}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir-shared", required=True, help="Shared-queries run directory")
    parser.add_argument("--run-dir-independent", required=True, help="Independent run directory")
    parser.add_argument("--output-dir", required=True, help="Output directory for figures")
    args = parser.parse_args()

    shared_dir = Path(args.run_dir_shared).resolve()
    indep_dir = Path(args.run_dir_independent).resolve()
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Loading data...")
    summary_shared = _load_method_summary(shared_dir)
    summary_indep = _load_method_summary(indep_dir)
    case_shared = _load_case_level(shared_dir)
    case_indep = _load_case_level(indep_dir)
    repro_data = _load_repro_top10_tail20(indep_dir)

    print(f"  Shared methods: {sorted(summary_shared.keys())}")
    print(f"  Independent methods: {sorted(summary_indep.keys())}")
    print(f"  Reproducibility cases: {len(repro_data)}")

    print("\nGenerating figures...")

    print("  Figure 1: Hybrid Coverage Comparison")
    plot_fig1(case_shared, case_indep, out_dir)

    print("  Figure 2: String vs Hybrid Delta")
    plot_fig2(summary_shared, out_dir)

    print("  Figure 3: Category Heatmap")
    plot_fig3(summary_shared, summary_indep, out_dir)

    print("  Figure 4: Ablation Matrix")
    plot_fig4(summary_shared, out_dir)

    print("  Figure 5: Reproducibility")
    plot_fig5(repro_data, out_dir)

    print(f"\nDone! All figures saved to {out_dir}")


if __name__ == "__main__":
    main()
