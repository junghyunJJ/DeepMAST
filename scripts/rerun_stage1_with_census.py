#!/usr/bin/env python3
"""Re-run Stage 1 with Census coexpression + CellXGene for all L-R pairs.

The original ollama run collected STRING PPI + KEGG + Reactome but missed
Census coexpression (30% weight) and CellXGene expression (15% weight),
causing all confidence scores to cap at ~0.55.

This script:
  1. Loads existing stage1 evidence JSON files
  2. Runs Census coexpression (run_compare_census_lr_pair) for all pairs
  3. Queries CellXGene for gene availability
  4. Merges new data into evidence
  5. Recomputes confidence scores
  6. Saves updated evidence files + confidence JSON
"""

import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.drug_target.tools.census_lr_validation_tools import (
    run_compare_census_lr_pair,
)
from src.agents.drug_target.tools.stage_domain_tools import (
    query_cellxgene_lr_context,
)
from src.agents.drug_target.tools.stage_logic import compute_stage1_confidence

# ── Configuration ──────────────────────────────────────────────────────
DATA_DIR = PROJECT_ROOT / "res_bc_ollama"
EVIDENCE_DIR = DATA_DIR / "evidence"
CENSUS_DISEASE = "breast carcinoma"  # Census MONDO label (from cellxgene_all_pairs.json)
TARGET_CELL_TYPE = "mammary gland epithelial cell"  # mapped from "Prolif Invasive Tumor"
DELAY = 1.0  # polite delay between Census API calls


def _call_tool(tool_fn, **kwargs):
    """Call a LangChain @tool function and parse JSON result."""
    raw = tool_fn.invoke(kwargs)
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"raw": str(raw), "errors": ["parse_failed"]}


def _save_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"  Saved → {path.name}")


# ── Load input data ───────────────────────────────────────────────────
lr_data = json.loads((DATA_DIR / "lr_candidates.json").read_text())
pairs = lr_data.get("pairs", lr_data.get("candidate_pairs", []))
print(f"Loaded {len(pairs)} L-R candidate pairs")
print(f"Census disease: {CENSUS_DISEASE}")
print(f"Target cell type: {TARGET_CELL_TYPE}")

# ══════════════════════════════════════════════════════════════════════
# PHASE 1: CellXGene gene availability (single query for all genes)
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("PHASE 1: CellXGene Gene Availability")
print("=" * 70)

# Check existing cellxgene data first
cellxgene_all_path = EVIDENCE_DIR / "stage1_cellxgene_all_pairs.json"
cellxgene_data = {}
if cellxgene_all_path.exists():
    cellxgene_data = json.loads(cellxgene_all_path.read_text())
    print(f"Loaded existing CellXGene data: all_genes_available={cellxgene_data.get('all_genes_available')}")

# Query CellXGene per pair to get available_genes in the format confidence expects
cellxgene_per_pair = {}
all_genes = set()
for pair in pairs:
    all_genes.add(pair["ligand"].upper())
    all_genes.add(pair["receptor"].upper())

# If all genes are available (from existing data), we can skip individual queries
if cellxgene_data.get("all_genes_available"):
    print(f"All {len(all_genes)} genes confirmed available in CellXGene Census")
    for pair in pairs:
        key = f"{pair['ligand']}_{pair['receptor']}"
        cellxgene_per_pair[key] = {
            "available_genes": [pair["ligand"].upper(), pair["receptor"].upper()],
            "executed": True,
        }
else:
    # Query per pair
    for i, pair in enumerate(pairs):
        lig, rec = pair["ligand"], pair["receptor"]
        key = f"{lig}_{rec}"
        print(f"  [{i+1}/{len(pairs)}] CellXGene {lig}^{rec} ...", end=" ", flush=True)
        result = _call_tool(
            query_cellxgene_lr_context,
            ligand=lig,
            receptor=rec,
            disease=CENSUS_DISEASE,
        )
        cellxgene_per_pair[key] = result
        genes = result.get("available_genes", [])
        print(f"genes={genes}")
        time.sleep(0.5)

# ══════════════════════════════════════════════════════════════════════
# PHASE 2: Census Coexpression (per pair, ~30-60s each)
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("PHASE 2: Census Coexpression Analysis (ALL pairs)")
print("=" * 70)

census_results = {}
for i, pair in enumerate(pairs):
    lig, rec = pair["ligand"], pair["receptor"]
    key = f"{lig}_{rec}"
    print(f"\n[{i+1}/{len(pairs)}] Census {lig}^{rec}")

    print(f"  → Running compare_census ...", end=" ", flush=True)
    result = _call_tool(
        run_compare_census_lr_pair,
        data_dir=str(DATA_DIR),
        disease=CENSUS_DISEASE,
        gene_a=lig,
        gene_b=rec,
        target_cell_type=TARGET_CELL_TYPE,
        timeout_sec=180,
    )

    executed = result.get("executed", False)
    errors = result.get("errors", [])
    tvr = result.get("target_vs_rest", {})
    coexpr = tvr.get("coexpression") or {}

    p_val = coexpr.get("p_value", "N/A")
    rr = coexpr.get("risk_ratio", "N/A")
    print(f"executed={executed}, p={p_val}, RR={rr}", end="")
    if errors:
        print(f", errors={errors}", end="")
    print()

    census_results[key] = result
    time.sleep(DELAY)

# ══════════════════════════════════════════════════════════════════════
# PHASE 3: Merge into evidence + recompute confidence
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("PHASE 3: Merge Evidence & Recompute Confidence")
print("=" * 70)

stage1_confidence = {}

for pair in pairs:
    lig, rec = pair["ligand"], pair["receptor"]
    key = f"{lig}_{rec}"
    pair_key = f"{lig}^{rec}"

    # Load existing evidence
    ev_path = EVIDENCE_DIR / f"stage1_{key}.json"
    if ev_path.exists():
        evidence = json.loads(ev_path.read_text())
    else:
        print(f"  WARNING: No existing evidence for {pair_key}, creating new")
        evidence = {"ligand": lig, "receptor": rec}

    # Merge Census coexpression
    census = census_results.get(key, {})
    if census.get("executed"):
        evidence["census_validation"] = {
            "disease": census.get("disease", CENSUS_DISEASE),
            "requested_cell_type": census.get("requested_cell_type", TARGET_CELL_TYPE),
            "resolved_cell_type": census.get("resolved_cell_type", TARGET_CELL_TYPE),
            "resolution_mode": census.get("resolution_mode", "exact"),
            "target_vs_rest": census.get("target_vs_rest", {}),
            "executed": True,
        }
    else:
        # Keep any existing census data or mark as failed
        if "census_validation" not in evidence:
            evidence["census_validation"] = {
                "executed": False,
                "errors": census.get("errors", ["Census query did not execute"]),
            }

    # Merge CellXGene data
    cxg = cellxgene_per_pair.get(key, {})
    evidence["cellxgene"] = {
        "available_genes": cxg.get("available_genes", []),
        "executed": cxg.get("executed", False),
    }

    # Recompute confidence
    conf = compute_stage1_confidence(evidence)
    evidence["stage1_confidence"] = conf
    stage1_confidence[pair_key] = conf

    # Save updated evidence
    _save_json(ev_path, evidence)

    print(f"  {pair_key}: confidence={conf['confidence']:.4f} "
          f"(STRING={conf['string_score']:.3f}, "
          f"census={conf['census_score']:.3f}, "
          f"pathway={conf['pathway_score']:.1f}, "
          f"expr={conf['expression_score']:.2f})")

# Save combined confidence
_save_json(EVIDENCE_DIR / "stage1_confidence.json", stage1_confidence)

# ── Summary ───────────────────────────────────────────────────────────
print(f"\n{'=' * 70}")
print("STAGE 1 RE-RUN WITH CENSUS COMPLETE")
print(f"{'=' * 70}")

n_census_ok = sum(1 for r in census_results.values() if r.get("executed"))
n_census_coexpr = sum(
    1 for r in census_results.values()
    if r.get("target_vs_rest", {}).get("coexpression") is not None
)
n_high_conf = sum(
    1 for c in stage1_confidence.values()
    if c.get("confidence", 0) >= 0.7
)
avg_conf = sum(c.get("confidence", 0) for c in stage1_confidence.values()) / len(stage1_confidence) if stage1_confidence else 0

print(f"  Total pairs: {len(pairs)}")
print(f"  Census executed: {n_census_ok}/{len(pairs)}")
print(f"  Census coexpression found: {n_census_coexpr}/{len(pairs)}")
print(f"  High confidence (≥0.7): {n_high_conf}/{len(pairs)}")
print(f"  Average confidence: {avg_conf:.3f}")

# Sort and display ranking
sorted_conf = sorted(
    stage1_confidence.items(),
    key=lambda x: x[1].get("confidence", 0),
    reverse=True,
)
print(f"\n── Confidence Ranking ──")
for rank, (pair_key, conf) in enumerate(sorted_conf, 1):
    print(f"  {rank:2d}. {pair_key:25s} {conf['confidence']:.4f} "
          f"(S={conf['string_score']:.3f} C={conf['census_score']:.3f} "
          f"P={conf['pathway_score']:.1f} E={conf['expression_score']:.2f})")
