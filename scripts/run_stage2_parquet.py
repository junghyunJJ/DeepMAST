#!/usr/bin/env python3
"""Run Stage 2 only using the shared batch Stage 2 service."""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from src.agents.drug_target.tools.stage2_service import (
    build_stage2_gene_panel,
    load_stage2_inputs,
    write_stage2_artifacts,
)

DISEASE = "breast cancer"
DATA_DIR = PROJECT_ROOT / "res_bc_ollama"


# ── Load input ────────────────────────────────────────────────────────
stage2_inputs = load_stage2_inputs(DATA_DIR)
unique_genes = stage2_inputs["gene_symbols"]
disease = DISEASE or stage2_inputs["disease"]

evidence_dir = DATA_DIR / "evidence"
evidence_dir.mkdir(exist_ok=True)

print(f"Stage 2: {len(unique_genes)} unique genes, disease='{disease}'")
panel = build_stage2_gene_panel(
    unique_genes,
    disease,
    selected_top3_genes=stage2_inputs["selected_top3_genes"],
    data_dir=DATA_DIR,
)
stage2_evidence = panel["stage2_evidence"]
written_paths = write_stage2_artifacts(panel, evidence_dir)
for path in written_paths:
    print(f"  Saved → {path.name}")

n_ok = sum(1 for g in unique_genes if stage2_evidence[g]["opentargets"].get("executed"))
print(f"\n{'='*70}")
print("Stage 2 COMPLETE")
print(f"  OT success: {n_ok}/{len(unique_genes)}")
print(f"  Source modes: OT={panel['source_modes']['opentargets']}, GWAS={panel['source_modes']['gwas']}")
print(f"  Evidence dir: {evidence_dir}")
print(f"{'='*70}")
