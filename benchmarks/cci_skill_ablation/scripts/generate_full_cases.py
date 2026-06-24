"""Generate full experiment CCI cases from interest_sig_liana.csv.

Selects 30 L-R pairs stratified by Moran's R (high/med/low) × literature
evidence (known/unknown) = 6 groups × 5 pairs each.

Usage:
    python benchmarks/cci_skill_ablation/scripts/generate_full_cases.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

BENCHMARK_DIR = Path(__file__).resolve().parents[1]
DATA_PATH = BENCHMARK_DIR / "inputs" / "interest_sig_liana.csv"
OUTPUT_PATH = BENCHMARK_DIR / "inputs" / "cci_full_cases.json"

SEED = 42
PAIRS_PER_GROUP = 5

MORANS_BINS = [-1.0, 0.05, 0.15, 1.0]
MORANS_LABELS = ["low", "medium", "high"]


def _parse_semicolon_list(val) -> list[str]:
    """Parse semicolon-separated string into list, handling NaN."""
    if pd.isna(val) or not str(val).strip():
        return []
    return [x.strip() for x in str(val).split(";") if x.strip()]


def build_case(row: pd.Series, morans_tier: str, lit_tier: str, idx: int) -> dict:
    """Build a single V2 case from a DataFrame row."""
    ligand = str(row["ligand"])
    receptor = str(row["receptor"])

    pathway_assoc = _parse_semicolon_list(row.get("progeny"))
    disease_assoc = _parse_semicolon_list(row.get("disease"))
    ligand_cts = _parse_semicolon_list(row.get("ligand_ctSVG"))
    receptor_cts = _parse_semicolon_list(row.get("receptor_ctSVG"))

    category = f"{morans_tier}_morans_{lit_tier}"
    case_id = f"cci_full_{idx:02d}_{ligand}_{receptor}"

    return {
        "case_id": case_id,
        "benchmark_type": "cci_interpretation_v2",
        "lr_pair": f"{ligand}-{receptor}",
        "category": category,
        "input_bundle": {
            "ligand": ligand,
            "receptor": receptor,
            "interaction": str(row["interaction"]),
            "morans_r": round(float(row["morans"]), 6),
            "morans_pval": float(row["morans_pvals"]),
            "ligand_means": round(float(row["ligand_means"]), 4),
            "ligand_props": round(float(row["ligand_props"]), 4),
            "receptor_means": round(float(row["receptor_means"]), 4),
            "receptor_props": round(float(row["receptor_props"]), 4),
            "factor1": round(float(row["Factor1"]), 4),
            "factor2": round(float(row["Factor2"]), 4),
            "factor3": round(float(row["Factor3"]), 4),
            "pathway_associations": pathway_assoc,
            "disease_associations": disease_assoc,
            "ligand_cell_types": ligand_cts,
            "receptor_cell_types": receptor_cts,
            "mean_interest": round(float(row["mean_interest"]), 6) if pd.notna(row.get("mean_interest")) else None,
            "pval_interest": float(row["pval_interest"]) if pd.notna(row.get("pval_interest")) else None,
            "pval_interest_adj": float(row["pval_interest_adj"]) if pd.notna(row.get("pval_interest_adj")) else None,
            "tissue_context": "Breast cancer Visium spatial transcriptomics",
        },
    }


def main() -> None:
    df = pd.read_csv(DATA_PATH)
    print(f"Loaded {len(df)} pairs from {DATA_PATH}")

    # Stratify
    df["morans_tier"] = pd.cut(
        df["morans"], bins=MORANS_BINS, labels=MORANS_LABELS
    )
    has_lit = (df["progeny"].notna() & (df["progeny"] != "")) | (
        df["disease"].notna() & (df["disease"] != "")
    )
    df["lit_tier"] = has_lit.map({True: "known", False: "unknown"})

    # Prefer pairs with both cell type columns populated
    has_both_ct = (
        df["ligand_ctSVG"].notna() & (df["ligand_ctSVG"] != "")
    ) & (df["receptor_ctSVG"].notna() & (df["receptor_ctSVG"] != ""))

    cases = []
    idx = 1
    for (mt, lt), group in df.groupby(["morans_tier", "lit_tier"], observed=True):
        # Prefer pairs with cell type data
        ct_group = group[has_both_ct.loc[group.index]]
        pool = ct_group if len(ct_group) >= PAIRS_PER_GROUP else group
        selected = pool.sample(n=min(PAIRS_PER_GROUP, len(pool)), random_state=SEED)
        print(f"  {mt:8s} × {lt:8s}: selected {len(selected)}/{len(group)} (ct_available={len(ct_group)})")
        for _, row in selected.iterrows():
            cases.append(build_case(row, mt, lt, idx))
            idx += 1

    # Sort by case_id for reproducibility
    cases.sort(key=lambda c: c["case_id"])

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(cases, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nSaved {len(cases)} cases to {OUTPUT_PATH}")

    # Validation summary
    categories = {}
    for c in cases:
        cat = c["category"]
        categories[cat] = categories.get(cat, 0) + 1
    print("\nCategory distribution:")
    for cat, count in sorted(categories.items()):
        print(f"  {cat}: {count}")

    # Check cell type coverage
    no_ligand_ct = sum(1 for c in cases if not c["input_bundle"]["ligand_cell_types"])
    no_receptor_ct = sum(1 for c in cases if not c["input_bundle"]["receptor_cell_types"])
    print(f"\nMissing cell types: ligand={no_ligand_ct}, receptor={no_receptor_ct}")


if __name__ == "__main__":
    main()
