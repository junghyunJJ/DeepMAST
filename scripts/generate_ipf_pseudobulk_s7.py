#!/usr/bin/env python
"""Generate the B1-versus-A1 pseudobulk DEG table and Supplementary Figure S7."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
from typing import cast

import anndata as ad
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import sparse
from scipy.stats import ttest_ind
from statsmodels.stats.multitest import multipletests


DEFAULT_OUTPUT = Path("docs/ICAM1_exp")
EXPECTED_ICAM1 = {"log2fc": 1.39193767252574, "fdr": 0.0461858824677634}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def sample_group(sample: str) -> str:
    return sample.rsplit("-", 1)[-1]


def normalized_sample_means(adata: ad.AnnData, samples: pd.Series) -> pd.DataFrame:
    counts = adata.layers["counts"]
    profiles: list[np.ndarray] = []
    names: list[str] = []

    for sample in sorted(samples.unique()):
        positions = np.flatnonzero(samples.to_numpy() == sample)
        matrix = sparse.csr_matrix(counts[positions])
        library_size = np.asarray(matrix.sum(axis=1)).ravel()
        normalized = matrix.multiply((1e4 / np.maximum(library_size, 1))[:, None]).tocsr()
        normalized.data = np.log1p(normalized.data)
        profiles.append(np.asarray(normalized.mean(axis=0)).ravel())
        names.append(sample)

    return pd.DataFrame(np.vstack(profiles), index=pd.Index(names), columns=adata.var_names)


def calculate_deg(profiles: pd.DataFrame, groups: pd.Series) -> pd.DataFrame:
    mild = profiles.loc[groups.index[groups.to_numpy() == "B1"]]
    normal = profiles.loc[groups.index[groups.to_numpy() == "A1"]]
    statistic = ttest_ind(mild.to_numpy(), normal.to_numpy(), axis=0, equal_var=False)
    raw_pvals = cast(np.ndarray, statistic[1])
    pvals = np.nan_to_num(raw_pvals, nan=1.0, posinf=1.0, neginf=1.0)
    fdr = multipletests(pvals, method="fdr_bh")[1]
    mean_mild = mild.mean(axis=0).to_numpy()
    mean_normal = normal.mean(axis=0).to_numpy()
    log2fc = np.log2(mean_mild + 1e-9) - np.log2(mean_normal + 1e-9)
    result = pd.DataFrame(
        {
            "gene": profiles.columns,
            "mean_target": mean_mild,
            "mean_reference": mean_normal,
            "log2fc": log2fc,
            "pval": pvals,
            "fdr": fdr,
        }
    )
    result["significant"] = (result["fdr"] < 0.05) & (result["log2fc"].abs() > 0.25)
    return result.sort_values(["fdr", "pval", "gene"], kind="stable").reset_index(drop=True)


def render_volcano(table: Path, output_dir: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "docs/ICAM1_exp/plot_b1_vs_a1_volcano.R"
    subprocess.run(["Rscript", str(script), "--input", str(table), "--output-dir", str(output_dir)], check=True)


def plot_composite(volcano: Path, icam: Path, output: Path) -> None:
    volcano_image = plt.imread(volcano)
    icam_image = plt.imread(icam)
    fig, axes = plt.subplots(1, 2, figsize=(13.2, 5.2), dpi=300)
    for label, image, axis in zip(("A", "B"), (volcano_image, icam_image), axes, strict=True):
        axis.imshow(image)
        axis.set_axis_off()
        axis.text(0.01, 0.99, label, transform=axis.transAxes, va="top", ha="left", fontsize=18, fontweight="bold")
    fig.tight_layout(pad=0.5)
    fig.savefig(output.with_suffix(".png"), dpi=300)
    fig.savefig(output.with_suffix(".pdf"))
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.input.exists() or args.input.stat().st_size == 0:
        raise SystemExit(f"Input AnnData file is unavailable: {args.input}")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    adata = ad.read_h5ad(args.input, backed="r")
    if "counts" not in adata.layers or "sample" not in adata.obs:
        raise SystemExit("AnnData must contain a counts layer and sample metadata")
    samples = cast(pd.Series, adata.obs["sample"].astype(str))
    sample_groups = pd.Series({sample: sample_group(sample) for sample in samples.unique()})
    if (sample_groups == "A1").sum() != 6 or (sample_groups == "B1").sum() != 7:
        raise SystemExit("Expected six A1 samples and seven B1 samples")

    profiles = normalized_sample_means(adata, samples)
    result = calculate_deg(profiles, sample_groups)
    adata.file.close()

    icam = result.loc[result["gene"] == "ICAM1"].iloc[0]
    for key, expected in EXPECTED_ICAM1.items():
        if not np.isclose(icam[key], expected, rtol=1e-5, atol=1e-7):
            raise SystemExit(f"ICAM1 {key} does not reproduce the expected value")

    table = args.output_dir / "b1_vs_a1_all_gene_deg.csv"
    volcano = args.output_dir / "b1_vs_a1_volcano"
    composite = args.output_dir / "figure_s7_ipf_pseudobulk"
    result.to_csv(table, index=False)
    render_volcano(table, args.output_dir)
    plot_composite(volcano.with_suffix(".png"), args.output_dir / "icam1_sample_expression.png", composite)

    print(table)
    print(volcano.with_suffix(".png"))
    print(composite.with_suffix(".png"))
    print(f"mild_up={(result['significant'] & (result['log2fc'] > 0.25)).sum()}")
    print(f"normal_up={(result['significant'] & (result['log2fc'] < -0.25)).sum()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
