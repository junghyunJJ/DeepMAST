"""Compose manuscript-ready multi-panel figure for lit reproducibility benchmark.

Panel order (left to right):
A) Composite coverage
B) Contamination rate
C) Dynamic Top-10 vs Tail-20 overlap (case-level medians)
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.image as mpimg
import matplotlib.pyplot as plt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-dir",
        required=True,
        help="Benchmark run directory (contains simple_method_comparison and reproducibility_plots)",
    )
    parser.add_argument(
        "--output",
        default="manuscript_display/fig_main_hallucination_repro_chain.png",
        help="Output path relative to --run-dir unless absolute",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=300,
        help="Output DPI",
    )
    return parser.parse_args()


def _resolve_output(run_dir: Path, output: str) -> Path:
    out = Path(output)
    if out.is_absolute():
        return out
    return run_dir / out


def compose(run_dir: Path, output_path: Path, dpi: int) -> None:
    panel_specs = [
        (
            "A",
            run_dir
            / "simple_method_comparison"
            / "fig_composite_cov_boxplot_case_mean.png",
            "Coverage breadth",
        ),
        (
            "B",
            run_dir
            / "simple_method_comparison"
            / "fig_contamination_boxplot_case_mean.png",
            "Contamination control",
        ),
        (
            "C",
            run_dir
            / "reproducibility_plots"
            / "fig_dynamic_repro_top10_vs_tail20_case_boxplot.png",
            "Top-10 stability vs Tail-20 diversity",
        ),
    ]

    for _, panel_path, _ in panel_specs:
        if not panel_path.exists():
            raise FileNotFoundError(f"Missing panel image: {panel_path}")

    fig, axes = plt.subplots(1, 3, figsize=(20, 6.8), constrained_layout=True)

    for ax, (label, panel_path, panel_title) in zip(axes, panel_specs, strict=True):
        image = mpimg.imread(panel_path)
        ax.imshow(image)
        ax.axis("off")
        ax.text(
            0.01,
            0.98,
            label,
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=18,
            fontweight="bold",
            color="black",
            bbox={"facecolor": "white", "alpha": 0.75, "edgecolor": "none", "pad": 2},
        )
        ax.set_title(panel_title, fontsize=12, pad=8)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    args = parse_args()
    run_dir = Path(args.run_dir).resolve()
    output_path = _resolve_output(run_dir, args.output).resolve()
    compose(run_dir=run_dir, output_path=output_path, dpi=args.dpi)
    print(output_path)


if __name__ == "__main__":
    main()
