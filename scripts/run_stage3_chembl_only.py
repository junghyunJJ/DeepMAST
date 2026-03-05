#!/usr/bin/env python
"""Stage 3 ChEMBL-only re-run.

Reads rubric_scores.json to identify Featured + Novel candidates,
runs ChEMBL with indications for their genes,
refines existing_drug_evidence / clinical_trial_activity,
and saves stage3_chembl_top3.json + updated rubric_scores.json + gene_drug_scores.json.

Usage:
    python scripts/run_stage3_chembl_only.py res_bc_ollama
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agents.drug_target.tools.stage_domain_tools import _chembl_fallback
from src.agents.drug_target.tools.stage_logic import (
    compute_drug_evidence_scores,
    rank_featured_candidates,
)

DISEASE = "breast cancer"


def score_novelty_opportunity(ot_result: dict, drug_ede: int) -> int:
    """Score novelty_opportunity 0-3."""
    if drug_ede >= 3:
        return 0
    if drug_ede >= 2:
        return 1
    associations = []
    if ot_result and ot_result.get("executed"):
        associations = ot_result.get("associations", [])
    n_assocs = len(associations)
    if drug_ede == 0 and n_assocs < 5:
        return 3
    if drug_ede == 0:
        return 2
    return 1


def main():
    data_dir = sys.argv[1] if len(sys.argv) > 1 else "res_bc_ollama"
    data_path = Path(data_dir)
    evidence_path = data_path / "evidence"

    # Load existing data
    with open(evidence_path / "rubric_scores.json") as f:
        rubric = json.load(f)
    with open(evidence_path / "gene_drug_scores.json") as f:
        gene_scores = json.load(f)

    # Load stage2_evidence for OT tractability
    ot_results = {}
    stage2_ev_path = evidence_path / "stage2_evidence.json"
    if stage2_ev_path.exists():
        with open(stage2_ev_path) as f:
            stage2_ev = json.load(f)
        for gene, ev in stage2_ev.items():
            ot_results[gene] = ev.get("opentargets", {})

    # Identify selected pairs (Featured + Novel)
    selected = [r for r in rubric if r.get("is_featured") or r.get("is_novel")]
    selected_genes = set()
    for r in selected:
        selected_genes.add(r["ligand"])
        selected_genes.add(r["receptor"])
    selected_genes = sorted(selected_genes)

    print(f"{'='*80}")
    print(f"STAGE 3: ChEMBL Deep Dive")
    print(f"Selected {len(selected_genes)} genes from {len(selected)} pairs")
    print(f"Disease: {DISEASE}")
    print(f"{'='*80}\n")

    # Run ChEMBL for selected genes
    chembl_results = {}
    for i, gene in enumerate(selected_genes, 1):
        t0 = time.time()
        try:
            drugs = _chembl_fallback(gene, 10)
        except Exception as e:
            print(f"  [{i}/{len(selected_genes)}] {gene}: ChEMBL ERROR - {e}")
            drugs = []
        elapsed = round(time.time() - t0, 1)
        chembl_results[gene] = drugs
        n_ind = sum(len(d.get("indications", [])) for d in drugs)
        n_bc = sum(
            1 for d in drugs
            for ind in d.get("indications", [])
            if "breast" in (ind.get("efo_term") or "").lower()
        )
        print(f"  [{i}/{len(selected_genes)}] {gene}: {len(drugs)} drugs, "
              f"{n_ind} indications ({n_bc} breast-related) ({elapsed}s)")
        sys.stdout.flush()

    # Compute refined drug evidence scores
    print(f"\n--- Refining drug evidence scores ---")
    for gene in selected_genes:
        drugs = chembl_results.get(gene, [])
        ot = ot_results.get(gene, {})
        tract_data = ot.get("target_info", {}).get("tractability", [])
        refined = compute_drug_evidence_scores(drugs, DISEASE, tract_data)

        old_ede = gene_scores.get(gene, {}).get("existing_drug_evidence", 0)
        new_ede = refined["existing_drug_evidence"]
        old_cta = gene_scores.get(gene, {}).get("clinical_trial_activity", 0)
        new_cta = refined["clinical_trial_activity"]

        gene_scores[gene]["existing_drug_evidence"] = new_ede
        gene_scores[gene]["clinical_trial_activity"] = new_cta
        gene_scores[gene]["novelty_opportunity"] = score_novelty_opportunity(ot, new_ede)
        gene_scores[gene]["drug_detail"] = refined["detail"]

        marker = " ***" if (new_ede != old_ede or new_cta != old_cta) else ""
        print(f"  {gene}: ede {old_ede}->{new_ede}, cta {old_cta}->{new_cta}{marker}")

    # Save updated gene_drug_scores
    with open(evidence_path / "gene_drug_scores.json", "w") as f:
        json.dump(gene_scores, f, indent=2)
    print(f"\nSaved gene_drug_scores.json")

    # Rebuild rubric with refined scores
    with open(data_path / "lr_candidates.json") as f:
        lr_data = json.load(f)
    pairs = lr_data.get("candidate_pairs") or lr_data.get("pairs", [])

    # Default scores for genes not in gene_drug_scores (not part of Stage 2 run)
    _default_scores = {
        "existing_drug_evidence": 0, "clinical_trial_activity": 0,
        "mechanism_relevance": 0, "safety_profile": 0,
        "gwas_genetic_support": 0, "tractability": 0,
        "biological_plausibility": 0, "novelty_opportunity": 2,
    }

    rubric_final = []
    for pair in pairs:
        lig = pair["ligand"]
        rec = pair["receptor"]
        ls = gene_scores.get(lig, _default_scores)
        rs = gene_scores.get(rec, _default_scores)

        lig_ot = ot_results.get(lig, {})
        rec_ot = ot_results.get(rec, {})
        ot_score = max(
            (float(a.get("score", 0))
             for a in lig_ot.get("associations", []) + rec_ot.get("associations", [])),
            default=0.0,
        )

        row = {
            "ligand": lig, "receptor": rec,
            "interaction": pair["interaction"],
            "hub_gene_count": pair.get("hub_gene_count", 0),
            "open_targets_score": ot_score,
            "validated_track": {
                "existing_drug_evidence": max(ls["existing_drug_evidence"], rs["existing_drug_evidence"]),
                "clinical_trial_activity": max(ls["clinical_trial_activity"], rs["clinical_trial_activity"]),
                "mechanism_relevance": max(ls["mechanism_relevance"], rs["mechanism_relevance"]),
                "safety_profile": min(ls["safety_profile"], rs["safety_profile"]),
            },
            "exploratory_track": {
                "gwas_genetic_support": max(ls["gwas_genetic_support"], rs["gwas_genetic_support"]),
                "tractability": max(ls["tractability"], rs["tractability"]),
                "biological_plausibility": max(ls["biological_plausibility"], rs["biological_plausibility"]),
                "novelty_opportunity": max(ls["novelty_opportunity"], rs["novelty_opportunity"]),
            },
        }
        rubric_final.append(row)

    ranked_final = rank_featured_candidates(rubric_final)

    with open(evidence_path / "rubric_scores.json", "w") as f:
        json.dump(ranked_final, f, indent=2)
    print("Saved rubric_scores.json")

    # Build stage3_chembl_top3.json
    novel_final = [r for r in ranked_final if r.get("is_novel")][:3]
    featured_final = [r for r in ranked_final if r.get("is_featured")]
    stage3_selected = featured_final + novel_final
    stage3_genes = set()
    for r in stage3_selected:
        stage3_genes.add(r["ligand"])
        stage3_genes.add(r["receptor"])

    stage3_data = {
        "description": "Stage 3 ChEMBL drug-target profiles with indications",
        "disease": DISEASE,
        "featured_pairs": [r["interaction"] for r in featured_final],
        "novel_pairs": [r["interaction"] for r in novel_final],
        "gene_profiles": {},
    }
    for gene in sorted(stage3_genes):
        drugs = chembl_results.get(gene, [])
        stage3_data["gene_profiles"][gene] = {
            "gene_symbol": gene,
            "executed": True,
            "matched_drugs": drugs,
            "drug_evidence_scores": gene_scores[gene].get("drug_detail", {}),
            "source": "chembl",
            "errors": [],
        }
    with open(evidence_path / "stage3_chembl_top3.json", "w") as f:
        json.dump(stage3_data, f, indent=2)
    print("Saved stage3_chembl_top3.json")

    # Print final results
    print(f"\n{'='*80}")
    print(f"FINAL RESULTS")
    print(f"{'='*80}")

    print(f"\nFEATURED TARGETS ({len(featured_final)}):")
    for r in featured_final:
        vt = r["validated_track"]
        print(f"  #{r['rank']} {r['interaction']:<25} ede={vt['existing_drug_evidence']} "
              f"cta={vt['clinical_trial_activity']} mech={vt['mechanism_relevance']} "
              f"safe={vt['safety_profile']}  combined={r['combined_total']}")

    print(f"\nNOVEL TARGETS ({len(novel_final)}):")
    for r in novel_final:
        et = r["exploratory_track"]
        print(f"  #{r['rank']} {r['interaction']:<25} gwas={et['gwas_genetic_support']} "
              f"tract={et['tractability']} bio={et['biological_plausibility']} "
              f"novel={et['novelty_opportunity']}  exploratory={r['exploratory_total']}")

    # Print per-gene ChEMBL summary
    print(f"\n--- Per-gene ChEMBL summary ---")
    for gene in selected_genes:
        drugs = chembl_results.get(gene, [])
        detail = gene_scores[gene].get("drug_detail", {})
        disease_drugs = detail.get("matched_disease_drugs", [])
        other_drugs = detail.get("matched_other_drugs", [])
        print(f"  {gene:<14} drugs={len(drugs):>2}  "
              f"disease_drugs={len(disease_drugs)}  other_drugs={len(other_drugs)}  "
              f"ede={gene_scores[gene]['existing_drug_evidence']}  "
              f"cta={gene_scores[gene]['clinical_trial_activity']}")

    print("\nDone!")


if __name__ == "__main__":
    main()
