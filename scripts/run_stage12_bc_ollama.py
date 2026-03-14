#!/usr/bin/env python3
"""Execute Stage 1-2 Pipeline on res_bc_ollama/ data.

Queries external APIs (STRING, KEGG, Reactome, OpenTargets, GWAS) for all 15
L-R candidate pairs, assigns heuristic rubric scores, and runs the dual-track
rank_featured_candidates() to produce Featured vs Novel selection.
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
)
from src.agents.drug_target.tools.stage2_service import (
    build_stage2_gene_panel,
    load_stage2_inputs,
    write_stage2_artifacts,
)
from src.agents.drug_target.tools.stage_logic import (
    rank_featured_candidates,
    compute_stage1_confidence,
)

# ── Configuration ──────────────────────────────────────────────────────
DATA_DIR = PROJECT_ROOT / "res_bc_ollama"
DISEASE = "breast cancer"
DELAY = 0.3  # polite delay between API calls

# ── Load input data ───────────────────────────────────────────────────
stage2_inputs = load_stage2_inputs(DATA_DIR)
pairs = stage2_inputs["pairs"]
print(f"Loaded {len(pairs)} L-R candidate pairs")

unique_genes = stage2_inputs["gene_symbols"]
print(f"Unique genes: {len(unique_genes)} → {unique_genes}")


def _call_tool(tool_fn, **kwargs):
    """Call a LangChain @tool function and parse JSON result."""
    raw = tool_fn.invoke(kwargs)
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"raw": str(raw), "errors": ["parse_failed"]}


# ══════════════════════════════════════════════════════════════════════
# STAGE 1: PPI + Pathways (per L-R pair)
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("STAGE 1: STRING PPI + KEGG/Reactome Pathways")
print("=" * 70)

stage1_evidence = {}  # keyed by "LIGAND^RECEPTOR"

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

    stage1_evidence[key] = {
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

# Compute Stage 1 confidence scores
print("\n── Stage 1 Confidence Scores ──")
for key, ev in stage1_evidence.items():
    conf = compute_stage1_confidence(ev)
    ev["stage1_confidence"] = conf
    print(f"  {key}: confidence={conf['confidence']:.3f} "
          f"(STRING={conf['string_score']:.2f}, pathway={conf['pathway_score']:.2f})")

# Save Stage 1 evidence
evidence_dir = DATA_DIR / "evidence"
evidence_dir.mkdir(exist_ok=True)
(evidence_dir / "stage1_evidence.json").write_text(
    json.dumps(stage1_evidence, indent=2), encoding="utf-8"
)
print(f"\nStage 1 evidence saved to {evidence_dir / 'stage1_evidence.json'}")


# ══════════════════════════════════════════════════════════════════════
# STAGE 2: OpenTargets + GWAS (per unique gene)
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
write_stage2_artifacts(stage2_bundle, evidence_dir)
print(
    f"\nStage 2 evidence saved to {evidence_dir / 'stage2_evidence.json'} "
    f"(OT={stage2_bundle['source_modes']['opentargets']}, "
    f"GWAS={stage2_bundle['source_modes']['gwas']})"
)


# ══════════════════════════════════════════════════════════════════════
# STEP 3: Assign Rubric Scores (heuristic)
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("STEP 3: Assign Heuristic Rubric Scores")
print("=" * 70)


def _score_existing_drug_evidence(ot_data: dict) -> int:
    """0/1/2/3 based on OpenTargets known_drugs and disease evidence."""
    target_info = ot_data.get("target_info", {})
    known_drugs = target_info.get("known_drugs", [])
    if isinstance(known_drugs, dict):
        known_drugs = known_drugs.get("rows", [])
    n_drugs = len(known_drugs) if isinstance(known_drugs, list) else 0

    # Also check disease_evidence for drug-related datatypes
    evidence = ot_data.get("disease_evidence", [])
    drug_evidence = [e for e in evidence if "drug" in str(e.get("datatype", "")).lower()
                     or "known_drug" in str(e.get("datatype", "")).lower()]

    if n_drugs >= 3 or len(drug_evidence) >= 3:
        return 3
    if n_drugs >= 1 or len(drug_evidence) >= 1:
        return 2
    # Check associations for any drug signal
    associations = ot_data.get("associations", [])
    for a in associations:
        if a.get("score", 0) > 0.5:
            datatypes = a.get("datatypes", {})
            if datatypes.get("known_drug", 0) > 0:
                return 1
    return 0


def _score_clinical_trial_activity(ot_data: dict) -> int:
    """0/1/2/3 based on max_clinical_phase from OpenTargets."""
    target_info = ot_data.get("target_info", {})

    # Look for max clinical trial phase in target_info
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

    # Also check disease_evidence
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
    """0/1/2/3 based on STRING PPI + pathway overlap."""
    # STRING score contribution
    ppi_found = s1_evidence.get("string_ppi", {}).get("interaction_found", False)

    # Pathway overlap
    kegg = s1_evidence.get("kegg_pathways", {})
    kegg_lig_ids = {p.get("pathway_id") for p in kegg.get("ligand_pathways", []) if p.get("pathway_id")}
    kegg_rec_ids = {p.get("pathway_id") for p in kegg.get("receptor_pathways", []) if p.get("pathway_id")}
    kegg_overlap = len(kegg_lig_ids & kegg_rec_ids)

    react = s1_evidence.get("reactome_pathways", {})
    react_lig_ids = {p.get("reactome_id") for p in react.get("ligand_pathways", []) if p.get("reactome_id")}
    react_rec_ids = {p.get("reactome_id") for p in react.get("receptor_pathways", []) if p.get("reactome_id")}
    react_overlap = len(react_lig_ids & react_rec_ids)

    total_overlap = kegg_overlap + react_overlap
    score = 0
    if ppi_found and string_score > 0.7:
        score += 2
    elif ppi_found:
        score += 1
    if total_overlap >= 2:
        score += 1
    elif total_overlap >= 1:
        score += 0  # pathway overlap alone without PPI is weak
    return min(score, 3)


def _score_safety_profile(ot_data: dict) -> int:
    """-2/-1/0 based on OpenTargets safety signals."""
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
    """0/1/2/3 based on GWAS gene associations."""
    gene_assoc = gwas_data.get("gene_associations", [])
    trait_assoc = gwas_data.get("trait_associations", [])

    # Filter for breast-cancer-related trait associations matching this gene
    n_gene = len(gene_assoc) if isinstance(gene_assoc, list) else 0
    n_trait = len(trait_assoc) if isinstance(trait_assoc, list) else 0

    # Count significant p-values in gene associations
    n_significant = 0
    for assoc in (gene_assoc if isinstance(gene_assoc, list) else []):
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
    if n_gene >= 1:
        return 1
    return 0


def _score_tractability(ot_data: dict) -> int:
    """0/1/2/3 based on OpenTargets tractability."""
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
    """0/1/2/3 based on pathway + PPI + expression signals."""
    score = 0
    # PPI interaction found
    if s1_evidence.get("string_ppi", {}).get("interaction_found"):
        score += 1
    # Pathway evidence (any pathways found)
    kegg = s1_evidence.get("kegg_pathways", {})
    react = s1_evidence.get("reactome_pathways", {})
    n_pathways = (
        len(kegg.get("ligand_pathways", [])) + len(kegg.get("receptor_pathways", []))
        + len(react.get("ligand_pathways", [])) + len(react.get("receptor_pathways", []))
    )
    if n_pathways >= 4:
        score += 1
    # Disease association in OpenTargets
    assoc = ot_data.get("associations", [])
    if any(a.get("score", 0) > 0.3 for a in assoc):
        score += 1
    return min(score, 3)


def _score_novelty_opportunity(ot_data: dict, hub_gene_count: int) -> int:
    """0/1/2/3 based on inverse hub gene + limited literature."""
    target_info = ot_data.get("target_info", {})
    known_drugs = target_info.get("known_drugs", [])
    if isinstance(known_drugs, dict):
        known_drugs = known_drugs.get("rows", [])
    n_drugs = len(known_drugs) if isinstance(known_drugs, list) else 0

    n_assoc = len(ot_data.get("associations", []))

    score = 0
    # No hub genes → more novel
    if hub_gene_count == 0:
        score += 1
    # Few known drugs → more novel
    if n_drugs == 0:
        score += 1
    # Few disease associations → unexplored territory
    if n_assoc < 5:
        score += 1
    return min(score, 3)


# Build druggability matrix
druggability_matrix = []

for pair in pairs:
    lig = pair["ligand"]
    rec = pair["receptor"]
    key = f"{lig}^{rec}"
    hub_count = pair.get("hub_gene_count", 0)

    s1 = stage1_evidence.get(key, {})
    string_score = s1.get("string_ppi", {}).get("max_combined_score", 0)

    # Get Stage 2 evidence for both genes
    ot_lig = stage2_evidence.get(lig.upper(), {}).get("opentargets", {})
    ot_rec = stage2_evidence.get(rec.upper(), {}).get("opentargets", {})
    gwas_lig = stage2_evidence.get(lig.upper(), {}).get("gwas", {})
    gwas_rec = stage2_evidence.get(rec.upper(), {}).get("gwas", {})

    # Use the receptor as primary target (convention for drug targeting)
    # but take the max signal from either gene
    ot_primary = ot_rec if ot_rec.get("executed") else ot_lig
    gwas_primary = gwas_rec if gwas_rec.get("executed") else gwas_lig

    # Compute rubric scores
    existing_drug = max(_score_existing_drug_evidence(ot_lig), _score_existing_drug_evidence(ot_rec))
    clinical_trial = max(_score_clinical_trial_activity(ot_lig), _score_clinical_trial_activity(ot_rec))
    mechanism = _score_mechanism_relevance(s1, string_score)
    safety = min(_score_safety_profile(ot_lig), _score_safety_profile(ot_rec))  # worst safety
    gwas_score = max(_score_gwas_genetic_support(gwas_lig), _score_gwas_genetic_support(gwas_rec))
    tractability = max(_score_tractability(ot_lig), _score_tractability(ot_rec))
    bio_plausibility = _score_biological_plausibility(s1, ot_primary)
    novelty = _score_novelty_opportunity(ot_primary, hub_count)

    row = {
        "ligand": lig,
        "receptor": rec,
        "interaction": key,
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

    vt = row["validated_track"]
    et = row["exploratory_track"]
    vt_total = sum(vt.values())
    et_total = sum(et.values())
    print(f"  {key:25s}  VT=[drug={existing_drug} clin={clinical_trial} mech={mechanism} safe={safety}]={vt_total:+d}  "
          f"ET=[gwas={gwas_score} tract={tractability} bio={bio_plausibility} novel={novelty}]={et_total}")


# ══════════════════════════════════════════════════════════════════════
# STEP 4: Run rank_featured_candidates()
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("STEP 4: Dual-Track Ranking (Featured vs Novel)")
print("=" * 70)

ranked = rank_featured_candidates(druggability_matrix)

# Save rubric scores
(evidence_dir / "rubric_scores.json").write_text(
    json.dumps(ranked, indent=2), encoding="utf-8"
)
print(f"Rubric scores saved to {evidence_dir / 'rubric_scores.json'}")


# ══════════════════════════════════════════════════════════════════════
# STEP 5: Report Results
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("RESULTS: Featured vs Novel Candidate Selection")
print("=" * 70)

featured = [r for r in ranked if r.get("is_featured")]
novel = [r for r in ranked if r.get("is_novel")]
remaining = [r for r in ranked if not r.get("is_featured") and not r.get("is_novel")]

print(f"\n{'─' * 90}")
print(f"{'FEATURED CANDIDATES (existing drug evidence)':^90}")
print(f"{'─' * 90}")
print(f"{'Rank':<6}{'L-R Pair':<28}{'Combined':<10}{'VT Total':<10}{'ET Total':<10}{'Classification':<20}{'Priority':<10}")
print(f"{'─' * 90}")
if featured:
    for r in featured:
        print(f"{r.get('rank', '-'):<6}{r['interaction']:<28}{r['combined_total']:<10}"
              f"{r['validated_total']:<10}{r['exploratory_total']:<10}"
              f"{r['classification']:<20}{r['priority']:<10}")
else:
    print("  (No featured candidates — no genes with existing_drug_evidence >= 1)")

print(f"\n{'─' * 90}")
print(f"{'NOVEL CANDIDATES (no existing drug evidence)':^90}")
print(f"{'─' * 90}")
print(f"{'Rank':<6}{'L-R Pair':<28}{'ET Total':<10}{'Novel Tier':<12}{'Classification':<20}{'Priority':<10}")
print(f"{'─' * 90}")
if novel:
    for r in novel:
        print(f"{r.get('rank', '-'):<6}{r['interaction']:<28}{r['exploratory_total']:<10}"
              f"{r.get('novel_tier', '-'):<12}{r['classification']:<20}{r['priority']:<10}")
else:
    print("  (No novel candidates)")

print(f"\n{'─' * 90}")
print(f"{'REMAINING (not selected)':^90}")
print(f"{'─' * 90}")
for r in remaining:
    tag = r.get("classification", "?")
    print(f"  {r['interaction']:<28} classification={tag:<20} "
          f"VT={r['validated_total']} ET={r['exploratory_total']}")

print(f"\n{'═' * 90}")
print(f"SUMMARY: {len(featured)} Featured + {len(novel)} Novel = {len(featured)+len(novel)} selected out of {len(ranked)} total")
print(f"{'═' * 90}")
