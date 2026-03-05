#!/usr/bin/env python
"""Stage 2 + Stage 3 re-computation script.

Pipeline:
  Stage 2: OpenTargets + GWAS → rubric scoring (OT tractability for drug estimate) → rank
  Stage 3: ChEMBL with indications for SELECTED candidates only → refine scores → re-rank

Usage:
    python scripts/run_stage2_recompute.py res_bc_ollama
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agents.drug_target.tools.stage_domain_tools import (
    _chembl_fallback,
    query_gwas_gene_trait,
    query_opentargets_target,
)
from src.agents.drug_target.tools.stage_logic import (
    compute_drug_evidence_scores,
    rank_featured_candidates,
)

DISEASE = "breast cancer"


# -------------------------------------------------------------------------
# Stage 2 rubric: evidence-based scoring from OpenTargets + GWAS
# -------------------------------------------------------------------------

def score_tractability(tractability: list[dict]) -> int:
    """Score tractability 0-3 from OpenTargets tractability list."""
    if not tractability:
        return 0
    sm_flags = {}
    ab_flags = {}
    for entry in tractability:
        label = entry.get("label", "")
        modality = entry.get("modality", "")
        value = entry.get("value", False)
        if modality == "SM":
            sm_flags[label] = value
        elif modality == "AB":
            ab_flags[label] = value

    if sm_flags.get("Approved Drug"):
        return 3
    if sm_flags.get("Advanced Clinical") or sm_flags.get("Phase 1 Clinical"):
        return 3
    if sm_flags.get("Structure with Ligand") or sm_flags.get("High-Quality Ligand"):
        return 2
    if sm_flags.get("High-Quality Pocket") or sm_flags.get("Med-Quality Pocket"):
        return 2
    if sm_flags.get("Druggable Family"):
        return 1
    if ab_flags.get("Approved Drug") or ab_flags.get("Advanced Clinical"):
        return 3
    if ab_flags.get("Phase 1 Clinical"):
        return 2
    if any(ab_flags.get(k) for k in ab_flags):
        return 1
    return 0


def score_existing_drug_from_ot(tractability: list[dict]) -> int:
    """Stage 2 initial estimate of existing_drug_evidence from OT tractability only.

    This is a coarse estimate before Stage 3 ChEMBL deep dive.
    0-1 range only (no indication-level detail yet).
    """
    if not tractability:
        return 0
    for entry in tractability:
        label = entry.get("label", "")
        value = entry.get("value", False)
        if label == "Approved Drug" and value:
            return 1  # OT says approved drug exists → at least 1
    return 0


def score_clinical_trial_from_ot(tractability: list[dict]) -> int:
    """Stage 2 initial estimate of clinical_trial_activity from OT tractability."""
    if not tractability:
        return 0
    for entry in tractability:
        label = entry.get("label", "")
        value = entry.get("value", False)
        if label == "Approved Drug" and value:
            return 2
        if label in ("Advanced Clinical", "Phase 1 Clinical") and value:
            return 1
    return 0


def score_gwas(gwas_result: dict, disease: str) -> int:
    """Score gwas_genetic_support 0-3 from GWAS query result."""
    if not gwas_result or not gwas_result.get("executed"):
        return 0
    disease_lower = disease.lower()
    trait_assocs = gwas_result.get("trait_associations", [])
    gene_assocs = gwas_result.get("gene_associations", [])

    disease_hits = 0
    for assoc in trait_assocs:
        trait = (assoc.get("traitName") or assoc.get("diseaseTrait", {}).get("trait", "")).lower()
        if any(kw in trait for kw in disease_lower.split()):
            disease_hits += 1

    if disease_hits >= 3:
        return 3
    if disease_hits >= 1:
        return 2
    if gene_assocs:
        return 1
    if gwas_result.get("efo_traits"):
        return 1
    return 0


def score_mechanism_relevance(ot_result: dict, disease: str) -> int:
    """Score mechanism_relevance 0-3 from OpenTargets data."""
    if not ot_result or not ot_result.get("executed"):
        return 0
    disease_evidence = ot_result.get("disease_evidence", [])
    associations = ot_result.get("associations", [])

    if disease_evidence:
        n_sources = len(disease_evidence)
        if n_sources >= 3:
            return 3
        if n_sources >= 1:
            return 2

    disease_lower = disease.lower()
    for assoc in associations:
        name = (assoc.get("disease_name") or "").lower()
        score = float(assoc.get("score", 0))
        if any(kw in name for kw in disease_lower.split()):
            if score >= 0.5:
                return 3
            if score >= 0.2:
                return 2
            return 1

    if associations:
        return 1
    return 0


def score_safety_profile(ot_result: dict) -> int:
    """Score safety_profile 0 to -2 from OpenTargets safety data."""
    if not ot_result or not ot_result.get("executed"):
        return 0
    target_info = ot_result.get("target_info", {})
    safety = target_info.get("safetyLiabilities") or target_info.get("safety", [])
    if not safety:
        return 0
    if isinstance(safety, list) and len(safety) >= 3:
        return -2
    if isinstance(safety, list) and len(safety) >= 1:
        return -1
    return 0


def score_biological_plausibility(ot_result: dict, disease: str) -> int:
    """Score biological_plausibility 0-3."""
    if not ot_result or not ot_result.get("executed"):
        return 0
    associations = ot_result.get("associations", [])
    target_info = ot_result.get("target_info", {})

    disease_lower = disease.lower()
    max_disease_score = 0.0
    total_assocs = len(associations)

    for assoc in associations:
        name = (assoc.get("disease_name") or "").lower()
        score = float(assoc.get("score", 0))
        if any(kw in name for kw in disease_lower.split()):
            max_disease_score = max(max_disease_score, score)

    func_desc = target_info.get("functionDescriptions", [])
    has_function_info = bool(func_desc)

    if max_disease_score >= 0.5 and has_function_info:
        return 3
    if max_disease_score >= 0.2 or (total_assocs >= 5 and has_function_info):
        return 2
    if total_assocs > 0 or has_function_info:
        return 1
    return 0


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


# -------------------------------------------------------------------------
# Main
# -------------------------------------------------------------------------

def main():
    data_dir = sys.argv[1] if len(sys.argv) > 1 else "res_bc_ollama"
    data_path = Path(data_dir)
    evidence_path = data_path / "evidence"
    evidence_path.mkdir(parents=True, exist_ok=True)

    with open(data_path / "lr_candidates.json") as f:
        lr_data = json.load(f)
    pairs = lr_data["candidate_pairs"]

    genes = sorted({p["ligand"] for p in pairs} | {p["receptor"] for p in pairs})
    print(f"{'='*80}")
    print(f"STAGE 2: Evidence Collection & Rubric Scoring")
    print(f"Disease: {DISEASE} | L-R pairs: {len(pairs)} | Unique genes: {len(genes)}")
    print(f"{'='*80}\n")

    # ================================================================
    # STAGE 2: OpenTargets + GWAS → Rubric → Rank
    # ================================================================

    # Step 1: OpenTargets
    print("--- Step 1/3: OpenTargets queries ---")
    ot_results = {}
    stage2_evidence = {}
    for i, gene in enumerate(genes, 1):
        t0 = time.time()
        try:
            raw = query_opentargets_target.invoke({"gene_symbol": gene, "disease": DISEASE})
            result = json.loads(raw)
        except Exception as e:
            result = {"executed": False, "errors": [str(e)]}
        elapsed = round(time.time() - t0, 1)
        ot_results[gene] = result
        stage2_evidence[gene] = {"opentargets": result}
        n_assocs = len(result.get("associations", [])) if result.get("executed") else 0
        print(f"  [{i}/{len(genes)}] {gene}: {'OK' if result.get('executed') else 'FAIL'}, {n_assocs} assocs ({elapsed}s)")
        sys.stdout.flush()

    # Step 2: GWAS
    print("\n--- Step 2/3: GWAS queries ---")
    gwas_results = {}
    for i, gene in enumerate(genes, 1):
        t0 = time.time()
        try:
            raw = query_gwas_gene_trait.invoke({"gene_symbol": gene, "disease": DISEASE})
            result = json.loads(raw)
        except Exception as e:
            result = {"executed": False, "errors": [str(e)]}
        elapsed = round(time.time() - t0, 1)
        gwas_results[gene] = result
        stage2_evidence[gene]["gwas"] = result
        n_ga = len(result.get("gene_associations", [])) if result.get("executed") else 0
        print(f"  [{i}/{len(genes)}] {gene}: {'OK' if result.get('executed') else 'FAIL'}, {n_ga} gene_assocs ({elapsed}s)")
        sys.stdout.flush()

    # Save stage2_evidence.json
    with open(evidence_path / "stage2_evidence.json", "w") as f:
        json.dump(stage2_evidence, f, indent=2)
    print(f"\nSaved stage2_evidence.json")

    # Step 3: Rubric scoring (OT + GWAS only, no ChEMBL yet)
    print("\n--- Step 3/3: Stage 2 Rubric Scoring ---")
    gene_scores_s2 = {}
    for gene in genes:
        ot = ot_results.get(gene, {})
        gwas = gwas_results.get(gene, {})
        tract_data = ot.get("target_info", {}).get("tractability", [])

        ede_init = score_existing_drug_from_ot(tract_data)
        cta_init = score_clinical_trial_from_ot(tract_data)

        gene_scores_s2[gene] = {
            "existing_drug_evidence": ede_init,
            "clinical_trial_activity": cta_init,
            "mechanism_relevance": score_mechanism_relevance(ot, DISEASE),
            "safety_profile": score_safety_profile(ot),
            "gwas_genetic_support": score_gwas(gwas, DISEASE),
            "tractability": score_tractability(tract_data),
            "biological_plausibility": score_biological_plausibility(ot, DISEASE),
            "novelty_opportunity": score_novelty_opportunity(ot, ede_init),
        }

    # Build rubric per L-R pair
    rubric_rows = []
    for pair in pairs:
        lig = pair["ligand"]
        rec = pair["receptor"]
        ls = gene_scores_s2[lig]
        rs = gene_scores_s2[rec]

        lig_ot = ot_results.get(lig, {})
        rec_ot = ot_results.get(rec, {})
        ot_score = max(
            (float(a.get("score", 0)) for a in lig_ot.get("associations", []) + rec_ot.get("associations", [])),
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
        rubric_rows.append(row)

    # Initial ranking
    ranked_s2 = rank_featured_candidates(rubric_rows)

    # Print Stage 2 results
    featured_s2 = [r for r in ranked_s2 if r.get("is_featured")]
    novel_s2 = [r for r in ranked_s2 if r.get("is_novel")]
    print(f"\n{'='*80}")
    print(f"STAGE 2 RESULTS (before ChEMBL)")
    print(f"{'='*80}")
    print(f"\n{'Gene':<12} {'ede':>4} {'cta':>4} {'mech':>5} {'safe':>5} {'gwas':>5} {'tract':>6} {'bio':>4} {'novel':>6}")
    print("-" * 62)
    for gene in genes:
        s = gene_scores_s2[gene]
        print(f"{gene:<12} {s['existing_drug_evidence']:>4} {s['clinical_trial_activity']:>4} "
              f"{s['mechanism_relevance']:>5} {s['safety_profile']:>5} "
              f"{s['gwas_genetic_support']:>5} {s['tractability']:>6} "
              f"{s['biological_plausibility']:>4} {s['novelty_opportunity']:>6}")

    print(f"\nFeatured ({len(featured_s2)}):")
    for r in featured_s2:
        vt = r["validated_track"]
        print(f"  #{r['rank']} {r['interaction']:<22} class={r['classification']:<20} "
              f"priority={r['priority']:<8} combined={r['combined_total']}")
    print(f"Novel ({len(novel_s2)}):")
    for r in novel_s2:
        print(f"  #{r['rank']} {r['interaction']:<22} class={r['classification']:<20} "
              f"priority={r['priority']:<8} exploratory={r['exploratory_total']}")

    # ================================================================
    # STAGE 3: ChEMBL with indications for SELECTED candidates only
    # ================================================================

    # Collect selected pairs (featured + novel)
    selected = [r for r in ranked_s2 if r.get("is_featured") or r.get("is_novel")]
    selected_genes = set()
    for r in selected:
        selected_genes.add(r["ligand"])
        selected_genes.add(r["receptor"])
    selected_genes = sorted(selected_genes)

    print(f"\n{'='*80}")
    print(f"STAGE 3: ChEMBL Deep Dive (selected {len(selected_genes)} genes from {len(selected)} pairs)")
    print(f"{'='*80}\n")

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
        print(f"  [{i}/{len(selected_genes)}] {gene}: {len(drugs)} drugs, {n_ind} indications ({elapsed}s)")
        sys.stdout.flush()

    # Compute refined drug evidence scores
    print("\n--- Refining drug evidence scores ---")
    for gene in selected_genes:
        drugs = chembl_results.get(gene, [])
        tract_data = ot_results.get(gene, {}).get("target_info", {}).get("tractability", [])
        refined = compute_drug_evidence_scores(drugs, DISEASE, tract_data)

        old_ede = gene_scores_s2[gene]["existing_drug_evidence"]
        new_ede = refined["existing_drug_evidence"]
        old_cta = gene_scores_s2[gene]["clinical_trial_activity"]
        new_cta = refined["clinical_trial_activity"]

        gene_scores_s2[gene]["existing_drug_evidence"] = new_ede
        gene_scores_s2[gene]["clinical_trial_activity"] = new_cta
        # Recalculate novelty based on refined ede
        gene_scores_s2[gene]["novelty_opportunity"] = score_novelty_opportunity(
            ot_results.get(gene, {}), new_ede
        )
        gene_scores_s2[gene]["drug_detail"] = refined["detail"]

        if new_ede != old_ede or new_cta != old_cta:
            print(f"  {gene}: ede {old_ede}->{new_ede}, cta {old_cta}->{new_cta} ***")
        else:
            print(f"  {gene}: ede={new_ede}, cta={new_cta} (unchanged)")

    # Save gene scores
    with open(evidence_path / "gene_drug_scores.json", "w") as f:
        json.dump(gene_scores_s2, f, indent=2)

    # Rebuild rubric with refined scores
    rubric_final = []
    for pair in pairs:
        lig = pair["ligand"]
        rec = pair["receptor"]
        ls = gene_scores_s2[lig]
        rs = gene_scores_s2[rec]

        lig_ot = ot_results.get(lig, {})
        rec_ot = ot_results.get(rec, {})
        ot_score = max(
            (float(a.get("score", 0)) for a in lig_ot.get("associations", []) + rec_ot.get("associations", [])),
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

    # Save stage3_chembl_top3.json
    novel_final = [r for r in ranked_final if r.get("is_novel")][:3]
    featured_final = [r for r in ranked_final if r.get("is_featured")]
    stage3_selected = featured_final + novel_final
    stage3_genes = set()
    for r in stage3_selected:
        stage3_genes.add(r["ligand"])
        stage3_genes.add(r["receptor"])
    stage3_data = {
        "description": "Stage 3 ChEMBL drug-target profiles with indications",
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
            "source": "chembl",
            "errors": [],
        }
    with open(evidence_path / "stage3_chembl_top3.json", "w") as f:
        json.dump(stage3_data, f, indent=2)

    # ================================================================
    # FINAL RESULTS
    # ================================================================
    print(f"\n{'='*80}")
    print(f"FINAL RESULTS (after Stage 3 ChEMBL refinement)")
    print(f"{'='*80}")

    print(f"\n{'Gene':<12} {'ede':>4} {'cta':>4} {'mech':>5} {'safe':>5} {'gwas':>5} {'tract':>6} {'bio':>4} {'novel':>6}")
    print("-" * 62)
    for gene in genes:
        s = gene_scores_s2[gene]
        print(f"{gene:<12} {s['existing_drug_evidence']:>4} {s['clinical_trial_activity']:>4} "
              f"{s['mechanism_relevance']:>5} {s['safety_profile']:>5} "
              f"{s['gwas_genetic_support']:>5} {s['tractability']:>6} "
              f"{s['biological_plausibility']:>4} {s['novelty_opportunity']:>6}")

    featured_f = [r for r in ranked_final if r.get("is_featured")]
    novel_f = [r for r in ranked_final if r.get("is_novel")]

    print(f"\nFEATURED TARGETS ({len(featured_f)}):")
    for r in featured_f:
        vt = r["validated_track"]
        print(f"  #{r['rank']} {r['interaction']:<22} class={r['classification']:<20} "
              f"priority={r['priority']:<8} ede={vt['existing_drug_evidence']} cta={vt['clinical_trial_activity']} "
              f"mech={vt['mechanism_relevance']} safe={vt['safety_profile']} combined={r['combined_total']}")

    print(f"\nNOVEL TARGETS ({len(novel_f)}):")
    for r in novel_f:
        et = r["exploratory_track"]
        print(f"  #{r['rank']} {r['interaction']:<22} class={r['classification']:<20} "
              f"priority={r['priority']:<8} gwas={et['gwas_genetic_support']} tract={et['tractability']} "
              f"bio={et['biological_plausibility']} novel={et['novelty_opportunity']} exploratory={r['exploratory_total']}")

    print(f"\nOTHER:")
    for r in ranked_final:
        if not r.get("is_featured") and not r.get("is_novel"):
            print(f"  {r['interaction']:<22} class={r['classification']:<20} "
                  f"priority={r['priority']:<8} combined={r['combined_total']}")

    print(f"\nSaved: rubric_scores.json, stage3_chembl_top3.json, gene_drug_scores.json, stage2_evidence.json")
    print("Done!")


if __name__ == "__main__":
    main()
