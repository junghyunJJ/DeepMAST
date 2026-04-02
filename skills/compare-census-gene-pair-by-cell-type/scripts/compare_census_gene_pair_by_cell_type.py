#!/usr/bin/env python3
"""Compare a gene pair's expression across cell types in CELLxGENE Census.

This script is designed for disease-focused single-cell analyses where you want:
1. Cell-type-level expression rates for two genes and their co-expression.
2. A statistical comparison of one target cell type vs all remaining cells.

Example:
    python scripts/compare_census_gene_pair_by_cell_type.py \
      --disease "breast cancer" \
      --gene-a TGFB1 \
      --gene-b TGFBR2 \
      --target-cell-type "malignant cell" \
      --census-version 2025-11-08
"""

from __future__ import annotations

import argparse
import csv
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable

import numpy as np
import cellxgene_census
import tiledbsoma as soma


@dataclass
class ZTestResult:
    p_target: float
    p_rest: float
    diff: float
    risk_ratio: float
    z: float
    p_value: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare two genes across cell types in CELLxGENE Census."
    )
    parser.add_argument(
        "--organism",
        default="homo_sapiens",
        choices=["homo_sapiens", "mus_musculus"],
        help="Census organism key (default: homo_sapiens).",
    )
    parser.add_argument(
        "--disease",
        required=True,
        help="Disease label in Census obs metadata (e.g., 'breast cancer').",
    )
    parser.add_argument(
        "--gene-a",
        required=True,
        help="First gene symbol (e.g., TGFB1).",
    )
    parser.add_argument(
        "--gene-b",
        required=True,
        help="Second gene symbol (e.g., TGFBR2).",
    )
    parser.add_argument(
        "--target-cell-type",
        required=True,
        help="Cell type to compare against all other cells.",
    )
    parser.add_argument(
        "--census-version",
        default=None,
        help="Pinned Census release for reproducibility (e.g., 2025-11-08).",
    )
    parser.add_argument(
        "--include-non-primary",
        action="store_true",
        help="Include non-primary cells. Default behavior filters to primary data only.",
    )
    parser.add_argument(
        "--obs-extra-filter",
        default="",
        help="Additional obs filter appended with AND.",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=20,
        help="Show top N cell types by cell count in console output.",
    )
    parser.add_argument(
        "--min-cells",
        type=int,
        default=50,
        help="Minimum cells required for cell type rows in console output.",
    )
    parser.add_argument(
        "--output-csv",
        default="",
        help="Optional path to save full cell-type summary as CSV.",
    )
    return parser.parse_args()


def build_obs_filter(disease: str, include_non_primary: bool, obs_extra_filter: str) -> str:
    clauses = [f"disease == '{disease}'"]
    if not include_non_primary:
        clauses.append("is_primary_data == True")
    if obs_extra_filter.strip():
        clauses.append(f"({obs_extra_filter.strip()})")
    return " and ".join(clauses)


def quote_list(values: Iterable[str]) -> str:
    escaped = [v.replace("'", "\\'") for v in values]
    return "[" + ",".join(f"'{v}'" for v in escaped) + "]"


def safe_cell_type(value: object) -> str:
    if value is None:
        return "UNKNOWN"
    as_str = str(value).strip()
    return as_str if as_str else "UNKNOWN"


def two_proportion_z_test(x_target: int, n_target: int, x_rest: int, n_rest: int) -> ZTestResult:
    p_target = x_target / n_target if n_target else float("nan")
    p_rest = x_rest / n_rest if n_rest else float("nan")
    diff = p_target - p_rest
    risk_ratio = (p_target / p_rest) if p_rest > 0 else float("inf")

    pooled = (x_target + x_rest) / (n_target + n_rest) if (n_target + n_rest) else float("nan")
    se = math.sqrt(pooled * (1.0 - pooled) * ((1.0 / n_target) + (1.0 / n_rest)))
    z = diff / se if se > 0 else float("nan")
    p_value = math.erfc(abs(z) / math.sqrt(2.0)) if not math.isnan(z) else float("nan")
    return ZTestResult(
        p_target=p_target,
        p_rest=p_rest,
        diff=diff,
        risk_ratio=risk_ratio,
        z=z,
        p_value=p_value,
    )


def format_p_value(p_value: float) -> str:
    if math.isnan(p_value):
        return "nan"
    if p_value == 0.0:
        return "<1e-323"
    return f"{p_value:.3e}"


def main() -> None:
    args = parse_args()
    gene_a = args.gene_a.strip()
    gene_b = args.gene_b.strip()
    target_cell_type = args.target_cell_type.strip()

    if gene_a == gene_b:
        raise ValueError("--gene-a and --gene-b must be different genes.")

    obs_filter = build_obs_filter(args.disease, args.include_non_primary, args.obs_extra_filter)
    var_filter = f"feature_name in {quote_list([gene_a, gene_b])}"

    open_kwargs = {}
    if args.census_version:
        open_kwargs["census_version"] = args.census_version

    print("Running CELLxGENE Census query")
    print(f"- organism: {args.organism}")
    print(f"- obs filter: {obs_filter}")
    print(f"- genes: {gene_a}, {gene_b}")
    print(f"- target cell type: {target_cell_type}")
    if args.census_version:
        print(f"- census version: {args.census_version}")
    else:
        print("- census version: stable release")

    with cellxgene_census.open_soma(**open_kwargs) as census:
        obs = cellxgene_census.get_obs(
            census,
            args.organism,
            value_filter=obs_filter,
            column_names=["soma_joinid", "cell_type"],
        )
        if obs.empty:
            raise RuntimeError("No cells matched the provided obs filter.")

        obs["cell_type"] = obs["cell_type"].map(safe_cell_type)
        totals_by_cell_type: Dict[str, int] = Counter(obs["cell_type"])
        cell_type_by_joinid = {
            int(joinid): cell_type
            for joinid, cell_type in zip(obs["soma_joinid"], obs["cell_type"])
        }

        var = cellxgene_census.get_var(
            census,
            args.organism,
            value_filter=var_filter,
            column_names=["soma_joinid", "feature_name", "feature_id"],
        )
        if var.empty:
            raise RuntimeError(f"No genes found for filter: {var_filter}")

        gene_to_joinid = {
            row["feature_name"]: int(row["soma_joinid"])
            for _, row in var.iterrows()
        }
        missing = [g for g in (gene_a, gene_b) if g not in gene_to_joinid]
        if missing:
            raise RuntimeError(f"Gene(s) not found in Census var metadata: {', '.join(missing)}")

        gene_a_id = gene_to_joinid[gene_a]
        gene_b_id = gene_to_joinid[gene_b]

        query = census["census_data"][args.organism].axis_query(
            measurement_name="RNA",
            obs_query=soma.AxisQuery(value_filter=obs_filter),
            var_query=soma.AxisQuery(value_filter=var_filter),
        )

        # Per-batch vectorized processing (bounded memory, no collect-all)
        state_by_cell: Dict[int, int] = {}
        nonzero_rows = 0
        for batch in query.X("raw").tables():
            cell_ids = batch["soma_dim_0"].to_numpy()
            gene_ids = batch["soma_dim_1"].to_numpy()
            nonzero_rows += len(cell_ids)
            mask_a = gene_ids == gene_a_id
            mask_b = gene_ids == gene_b_id
            for cid in cell_ids[mask_a]:
                state_by_cell[int(cid)] = state_by_cell.get(int(cid), 0) | 1
            for cid in cell_ids[mask_b]:
                state_by_cell[int(cid)] = state_by_cell.get(int(cid), 0) | 2
        query.close()

    gene_a_pos_by_cell_type: Dict[str, int] = defaultdict(int)
    gene_b_pos_by_cell_type: Dict[str, int] = defaultdict(int)
    coexp_pos_by_cell_type: Dict[str, int] = defaultdict(int)

    for cell_id, bits in state_by_cell.items():
        cell_type = cell_type_by_joinid.get(cell_id, "UNKNOWN")
        if bits & 1:
            gene_a_pos_by_cell_type[cell_type] += 1
        if bits & 2:
            gene_b_pos_by_cell_type[cell_type] += 1
        if bits == 3:
            coexp_pos_by_cell_type[cell_type] += 1

    total_cells = len(obs)
    total_gene_a = sum(gene_a_pos_by_cell_type.values())
    total_gene_b = sum(gene_b_pos_by_cell_type.values())
    total_coexp = sum(coexp_pos_by_cell_type.values())

    print("\nOverall summary")
    print(f"- total cells: {total_cells}")
    print(f"- cell types: {len(totals_by_cell_type)}")
    print(f"- nonzero rows scanned: {nonzero_rows}")
    print(f"- {gene_a}+ cells: {total_gene_a} ({(total_gene_a / total_cells) * 100:.4f}%)")
    print(f"- {gene_b}+ cells: {total_gene_b} ({(total_gene_b / total_cells) * 100:.4f}%)")
    print(f"- {gene_a}+ & {gene_b}+ cells: {total_coexp} ({(total_coexp / total_cells) * 100:.4f}%)")

    if target_cell_type not in totals_by_cell_type:
        top_available = sorted(
            totals_by_cell_type.items(),
            key=lambda item: item[1],
            reverse=True,
        )[:20]
        available = ", ".join(f"{name}({count})" for name, count in top_available)
        raise RuntimeError(
            f"Target cell type '{target_cell_type}' not found. "
            f"Examples of available cell types: {available}"
        )

    n_target = totals_by_cell_type[target_cell_type]
    n_rest = total_cells - n_target
    if n_rest == 0:
        raise RuntimeError(
            "Target cell type contains all filtered cells; "
            "cannot run target-vs-rest comparison."
        )
    metrics = [
        (f"{gene_a}+", gene_a_pos_by_cell_type),
        (f"{gene_b}+", gene_b_pos_by_cell_type),
        (f"{gene_a}+ & {gene_b}+", coexp_pos_by_cell_type),
    ]

    print("\nTarget vs rest")
    print(f"- target cell type: {target_cell_type}")
    print(f"- n_target: {n_target}")
    print(f"- n_rest: {n_rest}")
    for metric_name, metric_counts in metrics:
        x_target = metric_counts.get(target_cell_type, 0)
        x_rest = sum(metric_counts.values()) - x_target
        result = two_proportion_z_test(x_target, n_target, x_rest, n_rest)
        print(
            f"- {metric_name}: "
            f"target={result.p_target * 100:.4f}% | "
            f"rest={result.p_rest * 100:.4f}% | "
            f"diff={result.diff * 100:.4f}% | "
            f"RR={result.risk_ratio:.4f} | "
            f"z={result.z:.4f} | "
            f"p={format_p_value(result.p_value)}"
        )

    rows = []
    for cell_type, n_cells in totals_by_cell_type.items():
        if n_cells < args.min_cells:
            continue
        a_pos = gene_a_pos_by_cell_type.get(cell_type, 0)
        b_pos = gene_b_pos_by_cell_type.get(cell_type, 0)
        both_pos = coexp_pos_by_cell_type.get(cell_type, 0)
        rows.append(
            {
                "cell_type": cell_type,
                "n_cells": n_cells,
                "gene_a_pos": a_pos,
                "gene_a_pct": (a_pos / n_cells) * 100.0,
                "gene_b_pos": b_pos,
                "gene_b_pct": (b_pos / n_cells) * 100.0,
                "coexp_pos": both_pos,
                "coexp_pct": (both_pos / n_cells) * 100.0,
            }
        )

    rows.sort(key=lambda row: row["n_cells"], reverse=True)
    top_rows = rows[: max(args.top_n, 0)]
    if target_cell_type not in [row["cell_type"] for row in top_rows]:
        target_row = next((row for row in rows if row["cell_type"] == target_cell_type), None)
        if target_row:
            top_rows.append(target_row)

    print(f"\nCell-type summary (top {args.top_n}, min_cells={args.min_cells})")
    print("cell_type\tn_cells\tgene_a_pct\tgene_b_pct\tcoexp_pct")
    for row in top_rows:
        print(
            f"{row['cell_type']}\t{row['n_cells']}\t"
            f"{row['gene_a_pct']:.4f}\t{row['gene_b_pct']:.4f}\t{row['coexp_pct']:.4f}"
        )

    if args.output_csv:
        with open(args.output_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "cell_type",
                    "n_cells",
                    "gene_a_pos",
                    "gene_a_pct",
                    "gene_b_pos",
                    "gene_b_pct",
                    "coexp_pos",
                    "coexp_pct",
                ],
            )
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nSaved full summary CSV: {args.output_csv}")


if __name__ == "__main__":
    main()
