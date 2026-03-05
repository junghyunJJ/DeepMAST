#!/usr/bin/env python3
"""Run Stage 2 only (OpenTargets + GWAS) using Parquet-first mode.

Reads lr_candidates.json, queries all unique genes, saves results to evidence/.
"""

import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "skills" / "opentargets-database" / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "skills" / "gwas-database" / "scripts"))

import opentargets_parquet as otpq

DISEASE = "breast cancer"
DATA_DIR = PROJECT_ROOT / "res_bc_ollama"
DELAY = 0.3


def _query_gwas_direct(gwas_mod, gene_symbol: str, disease: str,
                       cached_efo_traits: list, cached_trait_assocs: list) -> dict:
    """Direct GWAS query bypassing the tool layer.

    EFO traits and trait_associations are pre-computed once and passed in.
    Only gene_associations is called per gene.
    """
    result = {
        "gene_symbol": gene_symbol, "disease": disease,
        "executed": False, "efo_traits": cached_efo_traits,
        "trait_associations": cached_trait_assocs,
        "gene_associations": [], "errors": [],
    }
    try:
        # Gene-specific variants (only per-gene call)
        result["gene_associations"] = gwas_mod.get_gene_associations(gene_symbol)

        # Disease-specific cross-filtering
        trait_assocs = cached_trait_assocs
        gene_assocs = result["gene_associations"]
        gene_upper = gene_symbol.upper()

        # Method A: trait SNPs where this gene is author-reported
        gene_in_trait = [
            ta for ta in trait_assocs
            if gene_upper in [g.upper() for g in ta.get("genes", [])]
        ]

        # Method B: gene SNPs whose rsId also appears in trait SNPs
        trait_rsids = {ta["rsId"] for ta in trait_assocs if ta.get("rsId")}
        gene_snps_in_disease = [
            ga for ga in gene_assocs
            if ga.get("rsId") in trait_rsids
        ]

        result["disease_specific_hits"] = {
            "gene_in_trait_associations": gene_in_trait,
            "gene_snps_in_disease": gene_snps_in_disease,
            "n_gene_in_trait": len(gene_in_trait),
            "n_gene_snps_in_disease": len(gene_snps_in_disease),
        }
        result["executed"] = True
    except Exception as exc:
        result["errors"].append(f"GWAS query failed: {exc}")
    return result


def _save_json(path, data):
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"  Saved → {path.name}")


# ── Load input ────────────────────────────────────────────────────────
lr_data = json.loads((DATA_DIR / "lr_candidates.json").read_text())
pairs = lr_data.get("pairs", lr_data.get("candidate_pairs", []))
all_genes = set()
for p in pairs:
    all_genes.add(p["ligand"].upper())
    all_genes.add(p["receptor"].upper())
unique_genes = sorted(all_genes)

evidence_dir = DATA_DIR / "evidence"
evidence_dir.mkdir(exist_ok=True)

import gwas_parquet as gwpq
gwas_pq_available = gwpq.is_available()

print(f"Stage 2: {len(unique_genes)} unique genes, disease='{DISEASE}'")
print(f"OT Parquet available:   {otpq.is_available()}")
print(f"GWAS Parquet available: {gwas_pq_available}")

# ── Cache disease EFO ID once ────────────────────────────────────────
disease_hits = otpq.search_entities(DISEASE, entity_types=["disease"])
efo_id = disease_hits[0]["id"] if disease_hits else None
print(f"Disease EFO ID: {efo_id}")

# ── Pre-compute GWAS EFO traits + trait associations once ────────────
gwas_t_pre = time.time()
_synonyms = {"cancer": "carcinoma", "carcinoma": "cancer"}
gwas_efo_traits = gwpq.search_efo_traits(DISEASE)
disease_lower = DISEASE.lower()
for old, new in _synonyms.items():
    if old in disease_lower:
        alt = disease_lower.replace(old, new)
        alt_traits = gwpq.search_efo_traits(alt)
        seen_ids = {t.get("shortForm") for t in gwas_efo_traits}
        for t in alt_traits:
            if t.get("shortForm") not in seen_ids and "error" not in t:
                gwas_efo_traits.append(t)
gwas_efo_traits = gwas_efo_traits[:5]

gwas_trait_assocs: list[dict] = []
seen_rsids: set[str] = set()
for t in gwas_efo_traits:
    if "error" in t:
        continue
    efo_trait_id = t.get("shortForm", "")
    if not efo_trait_id:
        continue
    for ta in gwpq.get_trait_associations(efo_trait_id, max_results=500):
        rsid = ta.get("rsId", "")
        if rsid and rsid in seen_rsids:
            continue
        if rsid:
            seen_rsids.add(rsid)
        gwas_trait_assocs.append(ta)

gwas_pre_elapsed = round(time.time() - gwas_t_pre, 1)
print(f"GWAS pre-cache: {len(gwas_efo_traits)} traits, {len(gwas_trait_assocs)} trait_assocs ({gwas_pre_elapsed}s)")

# ── Process genes ─────────────────────────────────────────────────────
stage2_evidence = {}
t_start = time.time()

for i, gene in enumerate(unique_genes):
    gt0 = time.time()
    print(f"\n[{i+1}/{len(unique_genes)}] {gene}")

    ot = {
        "gene_symbol": gene, "disease": DISEASE,
        "executed": False, "ensembl_id": None,
        "target_info": {}, "disease_evidence": [], "associations": [],
        "errors": [],
    }
    try:
        hits = otpq.search_entities(gene, entity_types=["target"])
        if not hits:
            ot["errors"].append(f"No target found for {gene}")
        else:
            ensembl_id = hits[0]["id"]
            ot["ensembl_id"] = ensembl_id
            ot["target_info"] = otpq.get_target_info(ensembl_id, include_diseases=True)
            if efo_id:
                ot["efo_id"] = efo_id
                ot["disease_evidence"] = otpq.get_target_disease_evidence(ensembl_id, efo_id)
            ot["associations"] = otpq.get_target_associations(ensembl_id, min_score=0.1)
            ot["executed"] = True
    except Exception as exc:
        ot["errors"].append(f"Parquet query failed: {exc}")

    ot_elapsed = round(time.time() - gt0, 1)
    n_assoc = len(ot.get("associations", []))
    n_ev = len(ot.get("disease_evidence", []))
    print(f"  OT(parquet): assoc={n_assoc}, evidence={n_ev} ({ot_elapsed}s)")

    # GWAS (direct parquet)
    gwas_t0 = time.time()
    gwas = _query_gwas_direct(gwpq, gene, DISEASE, gwas_efo_traits, gwas_trait_assocs)
    n_ga = len(gwas.get("gene_associations", []))
    n_ta = len(gwas.get("trait_associations", []))
    ds = gwas.get("disease_specific_hits", {})
    n_ds = ds.get("n_gene_in_trait", 0) + ds.get("n_gene_snps_in_disease", 0)
    gwas_elapsed = round(time.time() - gwas_t0, 1)
    print(f"  GWAS(pq):    gene_assoc={n_ga}, trait_assoc={n_ta}, disease_specific={n_ds} ({gwas_elapsed}s)")

    stage2_evidence[gene] = {"opentargets": ot, "gwas": gwas}
    _save_json(evidence_dir / f"ot_{gene}.json", ot)

total_elapsed = round(time.time() - t_start, 1)

# ── Save aggregated results ──────────────────────────────────────────
_save_json(evidence_dir / "stage2_evidence.json", stage2_evidence)

# Known drugs
print(f"\n→ Known drugs for '{DISEASE}' ...")
if efo_id:
    kd = otpq.get_known_drugs_for_disease(efo_id)
    known_drugs = {"disease": DISEASE, "executed": True, "efo_id": efo_id, "drugs": kd, "errors": []}
else:
    known_drugs = {"disease": DISEASE, "executed": False, "errors": ["No EFO ID"]}
_save_json(evidence_dir / "known_drugs.json", known_drugs)

# Gene manifest
gene_manifest = []
for gene in unique_genes:
    ot = stage2_evidence[gene]["opentargets"]
    gwas = stage2_evidence[gene]["gwas"]
    gene_manifest.append({
        "gene_symbol": gene,
        "ot_executed": ot.get("executed", False),
        "gwas_executed": gwas.get("executed", False),
        "ensembl_id": ot.get("ensembl_id"),
        "n_associations": len(ot.get("associations", [])),
        "n_gwas_hits": len(gwas.get("gene_associations", [])),
    })
_save_json(evidence_dir / "gene_manifest.json", gene_manifest)

# Summary
n_ok = sum(1 for g in unique_genes if stage2_evidence[g]["opentargets"].get("executed"))
print(f"\n{'='*70}")
print(f"Stage 2 COMPLETE in {total_elapsed}s")
print(f"  OT success: {n_ok}/{len(unique_genes)}")
print(f"  Evidence dir: {evidence_dir}")
print(f"{'='*70}")
