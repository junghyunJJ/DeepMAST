#!/usr/bin/env python3
"""Recompute Stage 1 confidence scores from individual stage1_*.json files.

Two-phase fix:
1. Integrate census CSV data into individual stage1_*.json files that are
   missing census_validation (the Census API ran and produced CSVs, but
   results were never saved into the JSON).
2. Recompute confidence scores and rebuild aggregated files.
"""

import csv
import json
import math
import sys
from pathlib import Path
from statistics import NormalDist
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.drug_target.tools.stage_logic import compute_stage1_confidence

DATA_DIR = PROJECT_ROOT / "res_bc_ollama"
EVIDENCE_DIR = DATA_DIR / "evidence"

SKIP_FILES = frozenset([
    "stage1_evidence.json",
    "stage1_confidence.json",
    "stage1_cellxgene_all_pairs.json",
])


def _parse_census_csv(csv_path: Path, target_cell_type: str) -> dict[str, Any] | None:
    """Parse a census CSV file and compute z-test statistics."""
    with open(csv_path) as fh:
        rows = list(csv.DictReader(fh))

    target_rows = [r for r in rows if r["cell_type"].strip() == target_cell_type]
    rest_rows = [r for r in rows if r["cell_type"].strip() != target_cell_type]

    if not target_rows:
        return None

    tr = target_rows[0]
    n1 = int(tr["n_cells"])
    if n1 == 0:
        return None

    n2 = sum(int(r["n_cells"]) for r in rest_rows)
    if n2 == 0:
        return None

    def _ztest(pos_col: str, pct_col: str):
        pos_target = int(tr[pos_col])
        p1 = pos_target / n1
        pos_rest = sum(int(r[pos_col]) for r in rest_rows)
        p2 = pos_rest / n2

        rr = round(p1 / p2, 4) if p2 > 0 else float("inf")
        p_pool = (pos_target + pos_rest) / (n1 + n2)
        if 0 < p_pool < 1:
            se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
            z = round((p1 - p2) / se, 4) if se > 0 else 0
            p_val = 2 * (1 - NormalDist().cdf(abs(z)))
        else:
            z, p_val = 0.0, 1.0

        return {
            "target_pct": round(p1, 6),
            "rest_pct": round(p2, 6),
            "diff": round(p1 - p2, 6),
            "risk_ratio": rr,
            "z": z,
            "p_value": p_val,
        }

    return {
        "gene_a": _ztest("gene_a_pos", "gene_a_pct"),
        "gene_b": _ztest("gene_b_pos", "gene_b_pct"),
        "coexpression": _ztest("coexp_pos", "coexp_pct"),
    }


def integrate_csv_census(data: dict, ligand: str, receptor: str) -> bool:
    """If stage1 JSON lacks census_validation, try to integrate from CSV.

    Returns True if data was modified.
    """
    if "census_validation" in data:
        return False

    csv_path = EVIDENCE_DIR / (
        f"census_{ligand.lower()}_{receptor.lower()}_mammary_gland_epithelial_cell.csv"
    )
    if not csv_path.exists():
        return False

    target_cell_type = "mammary gland epithelial cell"
    tvr = _parse_census_csv(csv_path, target_cell_type)
    if tvr is None:
        return False

    data["census_validation"] = {
        "disease": "breast carcinoma",
        "requested_cell_type": target_cell_type,
        "resolved_cell_type": target_cell_type,
        "resolution_mode": "exact",
        "target_vs_rest": tvr,
        "executed": True,
        "source": "csv_integration",
    }

    # Also add cellxgene available_genes
    if "cellxgene" not in data:
        data["cellxgene"] = {
            "available_genes": [ligand, receptor],
            "executed": True,
            "source": "csv_integration",
        }

    return True


def main():
    individual_files = sorted(
        f for f in EVIDENCE_DIR.glob("stage1_*.json")
        if f.name not in SKIP_FILES
    )

    print(f"Found {len(individual_files)} individual stage1 files")

    # Phase 1: Integrate CSV census data into individual JSONs
    integrated_count = 0
    for fpath in individual_files:
        data = json.loads(fpath.read_text())
        ligand = data.get("ligand", "")
        receptor = data.get("receptor", "")
        if not ligand or not receptor:
            continue

        if integrate_csv_census(data, ligand, receptor):
            integrated_count += 1
            # Remove old stage1_confidence from individual file before rewrite
            data.pop("stage1_confidence", None)
            fpath.write_text(json.dumps(data, indent=2) + "\n")
            print(f"  Integrated CSV -> {ligand}^{receptor}")

    print(f"\nPhase 1: Integrated {integrated_count} CSV files into stage1 JSONs")

    # Phase 2: Recompute confidence from updated individual files
    old_conf_path = EVIDENCE_DIR / "stage1_confidence.json"
    old_confidence = json.loads(old_conf_path.read_text()) if old_conf_path.exists() else {}

    new_confidence = {}
    new_evidence = {}

    for fpath in individual_files:
        data = json.loads(fpath.read_text())
        ligand = data.get("ligand", "")
        receptor = data.get("receptor", "")
        if not ligand or not receptor:
            continue
        pair_key = f"{ligand}^{receptor}"

        conf = compute_stage1_confidence(data)
        new_confidence[pair_key] = conf

        # Update individual file with new confidence
        data["stage1_confidence"] = conf
        fpath.write_text(json.dumps(data, indent=2) + "\n")

        # Rebuild aggregated evidence entry
        entry = {
            "ligand": ligand,
            "receptor": receptor,
            "string_ppi": data.get("string_ppi", {}),
            "kegg_pathways": data.get("kegg_pathways", {}),
            "reactome_pathways": data.get("reactome_pathways", {}),
        }
        if "census_validation" in data:
            entry["census_validation"] = data["census_validation"]
        if "cellxgene" in data:
            entry["cellxgene"] = data["cellxgene"]
        entry["stage1_confidence"] = conf
        new_evidence[pair_key] = entry

        print(f"  {pair_key}: confidence {conf['confidence']:.4f} "
              f"(str={conf['string_score']:.3f} cen={conf['census_score']:.3f} "
              f"path={conf['pathway_score']:.3f} expr={conf['expression_score']:.3f})")

    # Show changes
    print("\n--- Changes ---")
    changes = 0
    for pair_key in sorted(new_confidence):
        old_c = old_confidence.get(pair_key, {}).get("confidence", "N/A")
        new_c = new_confidence[pair_key]["confidence"]
        if old_c != new_c:
            changes += 1
            print(f"  {pair_key}: {old_c} -> {new_c}")

    if changes == 0:
        print("  (no changes)")

    # Write aggregated files
    old_conf_path.write_text(json.dumps(new_confidence, indent=2) + "\n")
    print(f"\nWrote {old_conf_path}")

    evidence_path = EVIDENCE_DIR / "stage1_evidence.json"
    evidence_path.write_text(json.dumps(new_evidence, indent=2) + "\n")
    print(f"Wrote {evidence_path}")

    print(f"\nSummary: {integrated_count} CSVs integrated, {changes} confidence scores changed")


if __name__ == "__main__":
    main()
