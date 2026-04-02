#!/usr/bin/env python3
"""Re-run Stage 1 (STRING PPI + KEGG + Reactome) for all 30 L-R pairs.

The original ollama run had STRING API failures (DNS/network errors) for 29/30
pairs. This script re-queries the APIs and recomputes confidence scores.

Output: res_bc_ollama/evidence/stage1_evidence.json
        res_bc_ollama/evidence/stage1_confidence.json
"""

import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.drug_target.tools.stage_domain_tools import (
    query_kegg_pathways,
    query_reactome_pathways,
    query_string_ppi_pair,
)
from src.agents.drug_target.tools.stage_logic import compute_stage1_confidence

# ── Configuration ──────────────────────────────────────────────────────
DATA_DIR = PROJECT_ROOT / "res_bc_ollama"
DELAY = 0.3  # polite delay between API calls


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

evidence_dir = DATA_DIR / "evidence"
evidence_dir.mkdir(exist_ok=True)

# ── Load existing Stage 1 evidence (to preserve Census data) ─────────
existing_evidence_path = evidence_dir / "stage1_evidence.json"
existing_evidence = {}
if existing_evidence_path.exists():
    existing_evidence = json.loads(existing_evidence_path.read_text())
    print(f"Loaded existing evidence for {len(existing_evidence)} pairs")

# ══════════════════════════════════════════════════════════════════════
# STAGE 1: Re-query STRING PPI + KEGG/Reactome for ALL pairs
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("STAGE 1 RE-RUN: STRING PPI + KEGG/Reactome Pathways (ALL pairs)")
print("=" * 70)

stage1_evidence = {}

for i, pair in enumerate(pairs):
    lig = pair["ligand"]
    rec = pair["receptor"]
    key = f"{lig}^{rec}"
    print(f"\n[{i+1}/{len(pairs)}] {key}")

    # STRING PPI
    print(f"  → STRING PPI ...", end=" ", flush=True)
    ppi = _call_tool(query_string_ppi_pair, gene_a=lig, gene_b=rec)
    print(f"score={ppi.get('max_combined_score', 'N/A')}, "
          f"found={ppi.get('interaction_found')}, "
          f"errors={ppi.get('errors', [])}")
    time.sleep(DELAY)

    # KEGG pathways (ligand + receptor)
    print(f"  → KEGG ({lig}) ...", end=" ", flush=True)
    kegg_lig = _call_tool(query_kegg_pathways, gene_symbol=lig)
    print(f"{len(kegg_lig.get('pathways', []))} pathways")
    time.sleep(DELAY)

    print(f"  → KEGG ({rec}) ...", end=" ", flush=True)
    kegg_rec = _call_tool(query_kegg_pathways, gene_symbol=rec)
    print(f"{len(kegg_rec.get('pathways', []))} pathways")
    time.sleep(DELAY)

    # Reactome pathways (ligand + receptor)
    print(f"  → Reactome ({lig}) ...", end=" ", flush=True)
    react_lig = _call_tool(query_reactome_pathways, gene_symbol=lig)
    print(f"{len(react_lig.get('pathways', []))} pathways")
    time.sleep(DELAY)

    print(f"  → Reactome ({rec}) ...", end=" ", flush=True)
    react_rec = _call_tool(query_reactome_pathways, gene_symbol=rec)
    print(f"{len(react_rec.get('pathways', []))} pathways")
    time.sleep(DELAY)

    evidence = {
        "ligand": lig,
        "receptor": rec,
        "string_ppi": ppi,
        "kegg_pathways": {
            "ligand_pathways": kegg_lig.get("pathways", []),
            "receptor_pathways": kegg_rec.get("pathways", []),
        },
        "reactome_pathways": {
            "ligand_pathways": react_lig.get("pathways", []),
            "receptor_pathways": react_rec.get("pathways", []),
        },
    }

    # Preserve Census validation data from original run if available
    old = existing_evidence.get(key, {})
    if "census_validation" in old:
        evidence["census_validation"] = old["census_validation"]
    if "cellxgene" in old:
        evidence["cellxgene"] = old["cellxgene"]

    stage1_evidence[key] = evidence
    _save_json(evidence_dir / f"stage1_{lig}--{rec}.json", evidence)

# ── Compute Stage 1 confidence scores ─────────────────────────────────
print("\n── Stage 1 Confidence Scores ──")
stage1_confidence = {}
for key, ev in stage1_evidence.items():
    conf = compute_stage1_confidence(ev)
    ev["stage1_confidence"] = conf
    stage1_confidence[key] = conf
    print(f"  {key}: confidence={conf['confidence']:.3f} "
          f"(STRING={conf['string_score']:.2f}, "
          f"census={conf['census_score']:.2f}, "
          f"pathway={conf['pathway_score']:.2f}, "
          f"expr={conf['expression_score']:.2f})")

_save_json(evidence_dir / "stage1_evidence.json", stage1_evidence)
_save_json(evidence_dir / "stage1_confidence.json", stage1_confidence)

# ── Summary ───────────────────────────────────────────────────────────
n_string_ok = sum(
    1 for ev in stage1_evidence.values()
    if not ev["string_ppi"].get("errors")
)
n_string_found = sum(
    1 for ev in stage1_evidence.values()
    if ev["string_ppi"].get("interaction_found")
)
n_nonzero = sum(
    1 for ev in stage1_evidence.values()
    if ev.get("stage1_confidence", {}).get("confidence", 0) > 0
)

print(f"\n{'=' * 70}")
print(f"STAGE 1 RE-RUN COMPLETE")
print(f"{'=' * 70}")
print(f"  Total pairs: {len(stage1_evidence)}")
print(f"  STRING API success: {n_string_ok}/{len(stage1_evidence)}")
print(f"  STRING interactions found: {n_string_found}/{len(stage1_evidence)}")
print(f"  Non-zero confidence: {n_nonzero}/{len(stage1_evidence)}")
