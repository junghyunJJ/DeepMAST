#!/usr/bin/env python3
"""Execute full 3-Stage Drug Target Pipeline on res_bc_ollama/ data.

Stage 1: Biological Context (STRING PPI + KEGG + Reactome) for ALL 30 L-R pairs
Stage 2: Target Validation (OpenTargets + GWAS) for unique genes + Rubric scoring
Stage 3: Deep Dive (ChEMBL drug profiles) for Featured + Novel candidates

Output: res_bc_ollama/evidence/*.json
"""

import json
import sys
import time
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.drug_target.tools.stage_domain_tools import (
    query_kegg_pathways,
    query_reactome_pathways,
    query_string_ppi_pair,
    query_chembl_target_profile,
    _chembl_fallback,
)
from src.agents.drug_target.tools.stage2_service import (
    build_stage2_gene_panel,
    load_stage2_inputs,
    write_stage2_artifacts,
)
from src.agents.drug_target.tools.stage_logic import (
    rank_featured_candidates,
    compute_stage1_confidence,
    compute_drug_evidence_scores,
)

# ── Configuration ──────────────────────────────────────────────────────
DATA_DIR = PROJECT_ROOT / "res_bc_ollama"
DISEASE = "breast cancer"
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
stage2_inputs = load_stage2_inputs(DATA_DIR)
pairs = stage2_inputs["pairs"]
print(f"Loaded {len(pairs)} L-R candidate pairs")

unique_genes = stage2_inputs["gene_symbols"]
print(f"Unique genes: {len(unique_genes)}")

# Ensure evidence directory
evidence_dir = DATA_DIR / "evidence"
evidence_dir.mkdir(exist_ok=True)


# ══════════════════════════════════════════════════════════════════════
# STAGE 1: Biological Context (ALL L-R pairs)
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("STAGE 1: STRING PPI + KEGG/Reactome Pathways (ALL pairs)")
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
    print(f"score={ppi.get('max_combined_score', 'N/A')}, found={ppi.get('interaction_found')}")
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
    stage1_evidence[key] = evidence

    # Save per-pair evidence
    _save_json(evidence_dir / f"stage1_{lig}--{rec}.json", evidence)

# Compute Stage 1 confidence scores
print("\n── Stage 1 Confidence Scores ──")
stage1_confidence = {}
for key, ev in stage1_evidence.items():
    conf = compute_stage1_confidence(ev)
    ev["stage1_confidence"] = conf
    stage1_confidence[key] = conf
    print(f"  {key}: confidence={conf['confidence']:.3f} "
          f"(STRING={conf['string_score']:.2f}, pathway={conf['pathway_score']:.2f})")

_save_json(evidence_dir / "stage1_evidence.json", stage1_evidence)
_save_json(evidence_dir / "stage1_confidence.json", stage1_confidence)
print(f"\n✓ Stage 1 complete: {len(stage1_evidence)} pairs processed")


# ══════════════════════════════════════════════════════════════════════
# STAGE 2: Target Validation & Scoring (ALL unique genes)
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("STAGE 2: OpenTargets + GWAS batch")
print("=" * 70)
stage2_bundle = build_stage2_gene_panel(
    unique_genes,
    DISEASE,
    selected_top3_genes=stage2_inputs["selected_top3_genes"],
    data_dir=DATA_DIR,
)
stage2_evidence = stage2_bundle["stage2_evidence"]
for path in write_stage2_artifacts(stage2_bundle, evidence_dir):
    print(f"  Saved → {path.name}")

print(
    f"\n✓ Stage 2 complete: {len(unique_genes)} genes processed "
    f"(OT={stage2_bundle['source_modes']['opentargets']}, "
    f"GWAS={stage2_bundle['source_modes']['gwas']})"
)


# ══════════════════════════════════════════════════════════════════════
# RUBRIC ASSESSMENT: Heuristic scoring + Featured/Novel selection
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("RUBRIC ASSESSMENT: Heuristic Scoring + Dual-Track Ranking")
print("=" * 70)


def _score_existing_drug_evidence(ot_data: dict) -> int:
    target_info = ot_data.get("target_info", {})
    known_drugs = target_info.get("known_drugs", [])
    if isinstance(known_drugs, dict):
        known_drugs = known_drugs.get("rows", [])
    n_drugs = len(known_drugs) if isinstance(known_drugs, list) else 0
    evidence = ot_data.get("disease_evidence", [])
    drug_evidence = [e for e in evidence if "drug" in str(e.get("datatype", "")).lower()
                     or "known_drug" in str(e.get("datatype", "")).lower()]
    if n_drugs >= 3 or len(drug_evidence) >= 3:
        return 3
    if n_drugs >= 1 or len(drug_evidence) >= 1:
        return 2
    associations = ot_data.get("associations", [])
    for a in associations:
        if a.get("score", 0) > 0.5:
            datatypes = a.get("datatypes", {})
            if datatypes.get("known_drug", 0) > 0:
                return 1
    return 0


def _score_clinical_trial_activity(ot_data: dict) -> int:
    target_info = ot_data.get("target_info", {})
    max_phase = 0
    known_drugs = target_info.get("known_drugs", [])
    if isinstance(known_drugs, dict):
        rows = known_drugs.get("rows", [])
    elif isinstance(known_drugs, list):
        rows = known_drugs
    else:
        rows = []
    for drug in rows:
        phase = drug.get("phase", drug.get("max_phase", drug.get("clinical_trial_phase", 0)))
        if isinstance(phase, (int, float)):
            max_phase = max(max_phase, int(phase))
        elif isinstance(phase, str):
            try:
                max_phase = max(max_phase, int(phase))
            except ValueError:
                pass
    for ev in ot_data.get("disease_evidence", []):
        phase = ev.get("clinicalPhase", ev.get("max_phase", 0))
        if isinstance(phase, (int, float)):
            max_phase = max(max_phase, int(phase))
    if max_phase >= 4:
        return 3
    if max_phase >= 2:
        return 2
    if max_phase >= 1:
        return 1
    return 0


def _score_mechanism_relevance(s1_evidence: dict, string_score: float) -> int:
    ppi_found = s1_evidence.get("string_ppi", {}).get("interaction_found", False)
    kegg = s1_evidence.get("kegg_pathways", {})
    kegg_lig_ids = {p.get("pathway_id") for p in kegg.get("ligand_pathways", []) if p.get("pathway_id")}
    kegg_rec_ids = {p.get("pathway_id") for p in kegg.get("receptor_pathways", []) if p.get("pathway_id")}
    react = s1_evidence.get("reactome_pathways", {})
    react_lig_ids = {p.get("reactome_id") for p in react.get("ligand_pathways", []) if p.get("reactome_id")}
    react_rec_ids = {p.get("reactome_id") for p in react.get("receptor_pathways", []) if p.get("reactome_id")}
    total_overlap = len(kegg_lig_ids & kegg_rec_ids) + len(react_lig_ids & react_rec_ids)
    score = 0
    if ppi_found and string_score > 0.7:
        score += 2
    elif ppi_found:
        score += 1
    if total_overlap >= 2:
        score += 1
    return min(score, 3)


def _score_safety_profile(ot_data: dict) -> int:
    target_info = ot_data.get("target_info", {})
    safety = target_info.get("safety", target_info.get("safetyLiabilities", []))
    if isinstance(safety, list):
        n_safety = len(safety)
    elif isinstance(safety, dict):
        n_safety = len(safety.get("liabilities", safety.get("effects", [])))
    else:
        n_safety = 0
    if n_safety >= 3:
        return -2
    if n_safety >= 1:
        return -1
    return 0


def _score_gwas_genetic_support(gwas_data: dict) -> int:
    gene_assoc = gwas_data.get("gene_associations", [])
    if not isinstance(gene_assoc, list):
        return 0
    n_significant = 0
    for assoc in gene_assoc:
        pval = assoc.get("pvalue", assoc.get("p-value", assoc.get("pValue", 1.0)))
        try:
            if float(pval) < 5e-8:
                n_significant += 1
        except (TypeError, ValueError):
            pass
    if n_significant >= 3:
        return 3
    if n_significant >= 1:
        return 2
    if len(gene_assoc) >= 1:
        return 1
    return 0


def _score_tractability(ot_data: dict) -> int:
    target_info = ot_data.get("target_info", {})
    tract = target_info.get("tractability", {})
    if isinstance(tract, list):
        n_modalities = len(tract)
    elif isinstance(tract, dict):
        n_modalities = sum(
            1 for v in tract.values()
            if (isinstance(v, dict) and v.get("top_category"))
            or (isinstance(v, bool) and v)
            or (isinstance(v, str) and v.strip())
        )
    else:
        n_modalities = 0
    if n_modalities >= 3:
        return 3
    if n_modalities >= 2:
        return 2
    if n_modalities >= 1:
        return 1
    return 0


def _score_biological_plausibility(s1_evidence: dict, ot_data: dict) -> int:
    score = 0
    if s1_evidence.get("string_ppi", {}).get("interaction_found"):
        score += 1
    kegg = s1_evidence.get("kegg_pathways", {})
    react = s1_evidence.get("reactome_pathways", {})
    n_pathways = (
        len(kegg.get("ligand_pathways", [])) + len(kegg.get("receptor_pathways", []))
        + len(react.get("ligand_pathways", [])) + len(react.get("receptor_pathways", []))
    )
    if n_pathways >= 4:
        score += 1
    assoc = ot_data.get("associations", [])
    if any(a.get("score", 0) > 0.3 for a in assoc):
        score += 1
    return min(score, 3)


def _score_novelty_opportunity(ot_data: dict, hub_gene_count: int) -> int:
    target_info = ot_data.get("target_info", {})
    known_drugs = target_info.get("known_drugs", [])
    if isinstance(known_drugs, dict):
        known_drugs = known_drugs.get("rows", [])
    n_drugs = len(known_drugs) if isinstance(known_drugs, list) else 0
    n_assoc = len(ot_data.get("associations", []))
    score = 0
    if hub_gene_count == 0:
        score += 1
    if n_drugs == 0:
        score += 1
    if n_assoc < 5:
        score += 1
    return min(score, 3)


# Build druggability matrix
druggability_matrix = []
gene_drug_scores = {}  # per-gene scores for Stage 3

for pair in pairs:
    lig = pair["ligand"]
    rec = pair["receptor"]
    key = f"{lig}^{rec}"
    hub_count = pair.get("hub_gene_count", 0)

    s1 = stage1_evidence.get(key, {})
    string_score = s1.get("string_ppi", {}).get("max_combined_score", 0)

    ot_lig = stage2_evidence.get(lig.upper(), {}).get("opentargets", {})
    ot_rec = stage2_evidence.get(rec.upper(), {}).get("opentargets", {})
    gwas_lig = stage2_evidence.get(lig.upper(), {}).get("gwas", {})
    gwas_rec = stage2_evidence.get(rec.upper(), {}).get("gwas", {})

    ot_primary = ot_rec if ot_rec.get("executed") else ot_lig

    existing_drug = max(_score_existing_drug_evidence(ot_lig), _score_existing_drug_evidence(ot_rec))
    clinical_trial = max(_score_clinical_trial_activity(ot_lig), _score_clinical_trial_activity(ot_rec))
    mechanism = _score_mechanism_relevance(s1, string_score)
    safety = min(_score_safety_profile(ot_lig), _score_safety_profile(ot_rec))
    gwas_score = max(_score_gwas_genetic_support(gwas_lig), _score_gwas_genetic_support(gwas_rec))
    tractability = max(_score_tractability(ot_lig), _score_tractability(ot_rec))
    bio_plausibility = _score_biological_plausibility(s1, ot_primary)
    novelty = _score_novelty_opportunity(ot_primary, hub_count)

    row = {
        "ligand": lig, "receptor": rec, "interaction": key,
        "hub_gene_count": hub_count,
        "open_targets_score": max(
            max((a.get("score", 0) for a in ot_lig.get("associations", [])), default=0),
            max((a.get("score", 0) for a in ot_rec.get("associations", [])), default=0),
        ),
        "validated_track": {
            "existing_drug_evidence": existing_drug,
            "clinical_trial_activity": clinical_trial,
            "mechanism_relevance": mechanism,
            "safety_profile": safety,
        },
        "exploratory_track": {
            "gwas_genetic_support": gwas_score,
            "tractability": tractability,
            "biological_plausibility": bio_plausibility,
            "novelty_opportunity": novelty,
        },
    }
    druggability_matrix.append(row)

    # Store per-gene scores for Stage 3
    for gene in [lig.upper(), rec.upper()]:
        if gene not in gene_drug_scores:
            ot_g = stage2_evidence.get(gene, {}).get("opentargets", {})
            gwas_g = stage2_evidence.get(gene, {}).get("gwas", {})
            gene_drug_scores[gene] = {
                "existing_drug_evidence": _score_existing_drug_evidence(ot_g),
                "clinical_trial_activity": _score_clinical_trial_activity(ot_g),
                "mechanism_relevance": mechanism,
                "safety_profile": _score_safety_profile(ot_g),
                "gwas_genetic_support": _score_gwas_genetic_support(gwas_g),
                "tractability": _score_tractability(ot_g),
                "biological_plausibility": bio_plausibility,
                "novelty_opportunity": _score_novelty_opportunity(ot_g, hub_count),
            }

    vt = row["validated_track"]
    et = row["exploratory_track"]
    vt_total = sum(vt.values())
    et_total = sum(et.values())
    print(f"  {key:25s}  VT=[drug={existing_drug} clin={clinical_trial} mech={mechanism} safe={safety}]={vt_total:+d}  "
          f"ET=[gwas={gwas_score} tract={tractability} bio={bio_plausibility} novel={novelty}]={et_total}")

# Run dual-track ranking
ranked = rank_featured_candidates(druggability_matrix)

_save_json(evidence_dir / "rubric_scores.json", ranked)
_save_json(evidence_dir / "assessment_results.json", druggability_matrix)
_save_json(evidence_dir / "gene_drug_scores.json", gene_drug_scores)

featured = [r for r in ranked if r.get("is_featured")]
novel = [r for r in ranked if r.get("is_novel")]

print(f"\n{'─' * 90}")
print(f"{'FEATURED CANDIDATES':^90}")
print(f"{'─' * 90}")
if featured:
    for r in featured:
        print(f"  #{r.get('rank')} {r['interaction']:<25} combined={r['combined_total']}  "
              f"class={r['classification']}  priority={r['priority']}")
else:
    print("  (None)")

print(f"\n{'─' * 90}")
print(f"{'NOVEL CANDIDATES':^90}")
print(f"{'─' * 90}")
if novel:
    for r in novel:
        print(f"  #{r.get('rank')} {r['interaction']:<25} exploratory={r['exploratory_total']}  "
              f"tier={r.get('novel_tier')}  class={r['classification']}  priority={r['priority']}")
else:
    print("  (None)")

print(f"\n✓ Rubric Assessment complete: {len(featured)} Featured + {len(novel)} Novel selected")


# ══════════════════════════════════════════════════════════════════════
# STAGE 3: Deep Dive (FEATURED + NOVEL candidates only)
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("STAGE 3: Deep Dive — ChEMBL Drug Profiles (Featured + Novel)")
print("=" * 70)

selected = [r for r in ranked if r.get("is_featured") or r.get("is_novel")]
selected_genes = set()
for r in selected:
    selected_genes.add(r["ligand"])
    selected_genes.add(r["receptor"])
selected_genes = sorted(selected_genes)

print(f"Selected {len(selected_genes)} genes from {len(selected)} pairs")

# ChEMBL queries
chembl_results = {}
for i, gene in enumerate(selected_genes, 1):
    t0 = time.time()
    print(f"  [{i}/{len(selected_genes)}] {gene} → ChEMBL ...", end=" ", flush=True)

    # Try DrugBank first via tool, then ChEMBL fallback
    drug_profile = _call_tool(query_chembl_target_profile, gene_symbol=gene, max_drugs=10)
    elapsed = round(time.time() - t0, 1)
    n_drugs = len(drug_profile.get("matched_drugs", []))
    source = drug_profile.get("source", "unknown")
    print(f"{n_drugs} drugs (source={source}, {elapsed}s)")

    chembl_results[gene] = drug_profile
    time.sleep(DELAY)

# Refine drug evidence scores with ChEMBL indication data
print(f"\n── Refining drug evidence scores with indications ──")
for gene in selected_genes:
    profile = chembl_results.get(gene, {})
    drugs = profile.get("matched_drugs", [])

    # Get OT tractability for compute_drug_evidence_scores
    ot = stage2_evidence.get(gene, {}).get("opentargets", {})
    tract_data = ot.get("target_info", {}).get("tractability", [])

    refined = compute_drug_evidence_scores(drugs, DISEASE, tract_data)

    old_ede = gene_drug_scores.get(gene, {}).get("existing_drug_evidence", 0)
    new_ede = refined["existing_drug_evidence"]
    old_cta = gene_drug_scores.get(gene, {}).get("clinical_trial_activity", 0)
    new_cta = refined["clinical_trial_activity"]

    if gene in gene_drug_scores:
        gene_drug_scores[gene]["existing_drug_evidence"] = new_ede
        gene_drug_scores[gene]["clinical_trial_activity"] = new_cta
        gene_drug_scores[gene]["drug_detail"] = refined["detail"]

    marker = " ***CHANGED" if (new_ede != old_ede or new_cta != old_cta) else ""
    print(f"  {gene}: ede {old_ede}→{new_ede}, cta {old_cta}→{new_cta}{marker}")

# Save Stage 3 evidence
stage3_data = {
    "description": "Stage 3 drug-target profiles (DrugBank/ChEMBL)",
    "disease": DISEASE,
    "featured_pairs": [r["interaction"] for r in featured],
    "novel_pairs": [r["interaction"] for r in novel],
    "gene_profiles": {},
}
for gene in selected_genes:
    stage3_data["gene_profiles"][gene] = chembl_results.get(gene, {})
    # Save per-gene Stage 3 file
    _save_json(evidence_dir / f"stage3_{gene}.json", chembl_results.get(gene, {}))

_save_json(evidence_dir / "stage3_deep_dive.json", stage3_data)
_save_json(evidence_dir / "gene_drug_scores.json", gene_drug_scores)

# Re-rank with refined scores
print(f"\n── Re-ranking with refined scores ──")
rubric_final = []
for pair in pairs:
    lig = pair["ligand"]
    rec = pair["receptor"]
    ls = gene_drug_scores.get(lig.upper(), gene_drug_scores.get(lig, {}))
    rs = gene_drug_scores.get(rec.upper(), gene_drug_scores.get(rec, {}))

    if not ls or not rs:
        # Skip pairs where we don't have gene scores
        continue

    lig_ot = stage2_evidence.get(lig.upper(), {}).get("opentargets", {})
    rec_ot = stage2_evidence.get(rec.upper(), {}).get("opentargets", {})
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
            "existing_drug_evidence": max(ls.get("existing_drug_evidence", 0), rs.get("existing_drug_evidence", 0)),
            "clinical_trial_activity": max(ls.get("clinical_trial_activity", 0), rs.get("clinical_trial_activity", 0)),
            "mechanism_relevance": max(ls.get("mechanism_relevance", 0), rs.get("mechanism_relevance", 0)),
            "safety_profile": min(ls.get("safety_profile", 0), rs.get("safety_profile", 0)),
        },
        "exploratory_track": {
            "gwas_genetic_support": max(ls.get("gwas_genetic_support", 0), rs.get("gwas_genetic_support", 0)),
            "tractability": max(ls.get("tractability", 0), rs.get("tractability", 0)),
            "biological_plausibility": max(ls.get("biological_plausibility", 0), rs.get("biological_plausibility", 0)),
            "novelty_opportunity": max(ls.get("novelty_opportunity", 0), rs.get("novelty_opportunity", 0)),
        },
    }
    rubric_final.append(row)

ranked_final = rank_featured_candidates(rubric_final)
_save_json(evidence_dir / "rubric_scores.json", ranked_final)

featured_final = [r for r in ranked_final if r.get("is_featured")]
novel_final = [r for r in ranked_final if r.get("is_novel")]

print(f"\n✓ Stage 3 complete: {len(selected_genes)} gene profiles collected")


# ══════════════════════════════════════════════════════════════════════
# FINAL SUMMARY
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("FINAL PIPELINE SUMMARY")
print("=" * 70)
print(f"  Disease: {DISEASE}")
print(f"  Input: {len(pairs)} L-R pairs, {len(unique_genes)} unique genes")
print(f"  Stage 1: STRING PPI + KEGG/Reactome for all {len(pairs)} pairs")
print(f"  Stage 2: OpenTargets + GWAS for {len(unique_genes)} genes")
print(f"  Stage 3: DrugBank/ChEMBL for {len(selected_genes)} selected genes")
print(f"  Output: {len(featured_final)} Featured + {len(novel_final)} Novel candidates")

print(f"\n{'─' * 90}")
print(f"{'FINAL FEATURED CANDIDATES':^90}")
print(f"{'─' * 90}")
for r in featured_final:
    vt = r["validated_track"]
    print(f"  #{r.get('rank')} {r['interaction']:<25} combined={r['combined_total']}  "
          f"ede={vt['existing_drug_evidence']} cta={vt['clinical_trial_activity']}  "
          f"class={r['classification']}  priority={r['priority']}")

print(f"\n{'─' * 90}")
print(f"{'FINAL NOVEL CANDIDATES':^90}")
print(f"{'─' * 90}")
for r in novel_final:
    et = r["exploratory_track"]
    print(f"  #{r.get('rank')} {r['interaction']:<25} exploratory={r['exploratory_total']}  "
          f"tier={r.get('novel_tier')}  "
          f"class={r['classification']}  priority={r['priority']}")

print(f"\n{'═' * 90}")
print(f"ALL DONE! Evidence saved to: {evidence_dir}")
print(f"{'═' * 90}")
