"""Shared stage decision logic for the drug target pipeline."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from langchain_core.tools import tool
from src.agents.drug_target.tools.stage2_service import extract_lr_pairs


_ONCOLOGY_KEYWORDS = (
    "cancer",
    "carcinoma",
    "sarcoma",
    "lymphoma",
    "leukemia",
    "melanoma",
    "glioblastoma",
    "tumor",
    "tumour",
    "neoplasm",
    "oncology",
)


def _to_float(value: Any, default: float = 0.0) -> float:
    """Best-effort numeric conversion with [0,1] clamp for scoring fields."""
    if value is None:
        return default
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(max(0.0, min(1.0, value)))

    text = str(value).strip().lower()
    if not text:
        return default

    # Common qualitative buckets.
    qualitative = {
        "very high": 0.95,
        "high": 0.85,
        "medium": 0.60,
        "low": 0.35,
        "very low": 0.15,
    }
    if text in qualitative:
        return qualitative[text]

    try:
        number = float(text)
        # If likely entered as percentage (0-100), normalize.
        if number > 1.0:
            number = number / 100.0
        return float(max(0.0, min(1.0, number)))
    except ValueError:
        return default


def normalize_st_colocalization_score(value: Any) -> float:
    """Normalize ST colocalization score to [0, 1]."""
    return _to_float(value, default=0.0)


def _extract_pathway_tokens(
    entries: list[Any],
    *,
    id_key: str,
) -> tuple[set[str], set[str]]:
    """Extract stable IDs and fallback names from pathway entries."""
    ids: set[str] = set()
    names: set[str] = set()
    for entry in entries:
        if isinstance(entry, dict):
            raw_id = str(entry.get(id_key) or "").strip()
            raw_name = str(entry.get("name") or "").strip()
            if raw_id:
                ids.add(raw_id)
            if raw_name:
                names.add(raw_name.lower())
        elif isinstance(entry, str):
            text = entry.strip()
            if text:
                names.add(text.lower())
    return ids, names



def infer_oncology_flag(disease: str) -> bool:
    """Infer whether disease context is oncology-related."""
    text = (disease or "").lower()
    return any(keyword in text for keyword in _ONCOLOGY_KEYWORDS)


def classify_disease_type(disease: str) -> str:
    """Classify disease type for stage gating."""
    if infer_oncology_flag(disease):
        return "oncology"
    if (disease or "").strip():
        return "non_oncology"
    return "unknown"


def rank_featured_candidates(
    druggability_matrix: list[dict[str, Any]],
    *,
    min_featured: int = 2,
    max_featured: int = 5,
    min_novel: int = 1,
    max_novel: int = 3,
    max_total: int = 7,
) -> list[dict[str, Any]]:
    """Rank candidates into Featured (validated) and Novel (new) tracks.

    Featured: targets with existing drug evidence (existing_drug_evidence >= 1),
              ranked by combined_total descending.
    Novel: targets with NO existing drug evidence (existing_drug_evidence == 0),
           ranked by exploratory_total descending.

    Each row must contain ``validated_track`` and ``exploratory_track``
    dictionaries (produced by the LLM rubric assessment).  Rows classified
    as ``insufficient_evidence`` are automatically excluded from both tracks.
    """
    if not druggability_matrix:
        return []

    scored_rows: list[dict[str, Any]] = []
    for row in druggability_matrix:
        item = dict(row)
        vt = compute_validated_track(item)
        et = compute_exploratory_track(item)
        classification = classify_target(item)
        priority = compute_priority(item)
        combined_total = vt["total"] + et["total"]

        item["classification"] = classification
        item["priority"] = priority
        item["combined_total"] = combined_total
        item["validated_total"] = vt["total"]
        item["exploratory_total"] = et["total"]
        scored_rows.append(item)

    # Separate insufficient_evidence rows
    eligible = [r for r in scored_rows if r["classification"] != "insufficient_evidence"]
    insufficient = [r for r in scored_rows if r["classification"] == "insufficient_evidence"]

    # --- Featured pool: existing_drug_evidence >= 1 ---
    featured_pool = [
        r for r in eligible
        if _safe_track_get(r, "validated_track", "existing_drug_evidence") >= 1
    ]
    featured_pool.sort(key=lambda x: x["combined_total"], reverse=True)

    # --- Novel pool: existing_drug_evidence == 0 ---
    novel_pool = [
        r for r in eligible
        if _safe_track_get(r, "validated_track", "existing_drug_evidence") == 0
    ]
    novel_pool.sort(key=lambda x: x["exploratory_total"], reverse=True)

    # --- Novel tier assignment ---
    for row in novel_pool:
        gwas = _safe_track_get(row, "exploratory_track", "gwas_genetic_support")
        tract = _safe_track_get(row, "exploratory_track", "tractability")
        row["novel_tier"] = 1 if (gwas >= 1 or tract >= 1) else 2

    # --- Slot allocation (dynamic, max_total limit) ---
    n_featured = min(max_featured, len(featured_pool))
    if len(featured_pool) >= min_featured:
        n_featured = max(min_featured, n_featured)
    else:
        n_featured = len(featured_pool)

    remaining = max_total - n_featured
    n_novel = min(max_novel, len(novel_pool), remaining)
    if remaining > 0 and len(novel_pool) >= min_novel:
        n_novel = max(min_novel, n_novel)
    else:
        n_novel = min(len(novel_pool), remaining)

    # --- Mark featured ---
    for idx, row in enumerate(featured_pool):
        row["is_featured"] = idx < n_featured
        row["is_novel"] = False
        row["rank"] = idx + 1 if idx < n_featured else None

    # --- Mark novel ---
    for idx, row in enumerate(novel_pool):
        row["is_novel"] = idx < n_novel
        row["is_featured"] = False
        row["rank"] = idx + 1 if idx < n_novel else None
        if idx >= n_novel:
            row.pop("novel_tier", None)

    # --- Mark insufficient ---
    for row in insufficient:
        row["rank"] = None
        row["is_featured"] = False
        row["is_novel"] = False

    return featured_pool + novel_pool + insufficient


# -------------------------------------------------------------------------
# RUBRIC scoring helpers (encode prompt logic into testable functions)
# -------------------------------------------------------------------------

# Score ranges per criterion
VALIDATED_CRITERIA = ("existing_drug_evidence", "clinical_trial_activity", "safety_profile")
EXPLORATORY_CRITERIA = ("gwas_genetic_support", "tractability", "biological_plausibility", "novelty_opportunity")


def _extract_score(criterion: dict[str, Any] | int | float) -> int:
    """Extract numeric score from criterion dict or raw value."""
    if isinstance(criterion, dict):
        return int(criterion.get("score", 0))
    return int(criterion)


def _safe_track_get(row: dict, track_key: str, criterion: str, default: int = 0) -> int:
    """Safely extract a criterion score from a track that may be a flat int."""
    track = row.get(track_key, {})
    if not isinstance(track, dict):
        return default
    return _extract_score(track.get(criterion, default))


def compute_validated_track(assessment: dict[str, Any]) -> dict[str, Any]:
    """Compute validated track total and pass/fail.

    Pass logic: existing_drug_evidence >= 2
                OR (existing_drug_evidence >= 1 AND clinical_trial_activity >= 1)
    """
    vt = assessment.get("validated_track", {})
    if not isinstance(vt, dict):
        # LLM passed flat int total — no per-criterion breakdown available
        return {"scores": {k: 0 for k in VALIDATED_CRITERIA}, "total": int(vt) if vt else 0, "pass": False}
    scores = {k: _extract_score(vt.get(k, 0)) for k in VALIDATED_CRITERIA}
    total = sum(scores.values())

    ede = scores["existing_drug_evidence"]
    cta = scores["clinical_trial_activity"]
    passed = ede >= 2 or (ede >= 1 and cta >= 1)

    return {"scores": scores, "total": total, "pass": passed}


def compute_exploratory_track(assessment: dict[str, Any]) -> dict[str, Any]:
    """Compute exploratory track total and pass/fail.

    Pass logic: gwas_genetic_support >= 1
                OR tractability >= 2
                OR biological_plausibility >= 3
    """
    et = assessment.get("exploratory_track", {})
    if not isinstance(et, dict):
        return {"scores": {k: 0 for k in EXPLORATORY_CRITERIA}, "total": int(et) if et else 0, "pass": False}
    scores = {k: _extract_score(et.get(k, 0)) for k in EXPLORATORY_CRITERIA}
    total = sum(scores.values())

    gwas = scores["gwas_genetic_support"]
    tract = scores["tractability"]
    bio = scores["biological_plausibility"]
    passed = gwas >= 1 or tract >= 2 or bio >= 3

    return {"scores": scores, "total": total, "pass": passed}


def classify_target(assessment: dict[str, Any]) -> str:
    """Classify target: validated_target | exploratory_target | novel_candidate | insufficient_evidence.

    Updated for 5-point scales:
    - existing_drug_evidence: -5 to +5 (gene-level − disease-level)
    - validated_pass: existing_drug >= 3 OR (existing_drug >= 1 AND validated_total >= 3)
    """
    vt = compute_validated_track(assessment)
    et = compute_exploratory_track(assessment)

    vt_scores = vt["scores"]
    existing_drug = vt_scores["existing_drug_evidence"]
    validated_total = vt["total"]
    validated_pass = (existing_drug >= 3) or (existing_drug >= 1 and validated_total >= 3)

    if validated_pass:
        return "validated_target"
    if et["pass"]:
        return "exploratory_target"

    # novel_candidate: bio >= 2 or novelty >= 3 or (tract >= 1 and novelty >= 2)
    et_scores = et["scores"]
    if (et_scores["biological_plausibility"] >= 2
            or et_scores["novelty_opportunity"] >= 3
            or (et_scores["tractability"] >= 1 and et_scores["novelty_opportunity"] >= 2)):
        return "novel_candidate"

    return "insufficient_evidence"


def compute_priority(assessment: dict[str, Any]) -> str:
    """Compute priority: high | medium | low | unranked.

    Updated thresholds for 5-point scales:
    - validated_target: uses combined_total (>= 10 high, >= 5 medium)
    - exploratory/novel: uses exploratory_total (>= 12 high, >= 7 medium)
    """
    classification = classify_target(assessment)
    if classification == "insufficient_evidence":
        return "unranked"

    vt = compute_validated_track(assessment)
    et = compute_exploratory_track(assessment)
    combined_total = vt["total"] + et["total"]

    if classification == "validated_target":
        if combined_total >= 10:
            return "high"
        if combined_total >= 5:
            return "medium"
        return "low"

    if classification == "exploratory_target":
        if et["total"] >= 12:
            return "high"
        if et["total"] >= 7:
            return "medium"
        return "low"

    # novel_candidate
    return "low"


def validate_rubric_assessment(assessment: dict[str, Any]) -> list[str]:
    """Validate rubric assessment structure. Returns list of errors (empty = valid)."""
    errors: list[str] = []

    if "validated_track" not in assessment:
        errors.append("Missing validated_track")
    else:
        vt = assessment["validated_track"]
        for key in VALIDATED_CRITERIA:
            if key not in vt:
                errors.append(f"validated_track missing '{key}'")

    if "exploratory_track" not in assessment:
        errors.append("Missing exploratory_track")
    else:
        et = assessment["exploratory_track"]
        for key in EXPLORATORY_CRITERIA:
            if key not in et:
                errors.append(f"exploratory_track missing '{key}'")

    # Score range checks
    if not errors:
        vt = assessment["validated_track"]
        for key in VALIDATED_CRITERIA:
            score = _extract_score(vt[key])
            if key == "safety_profile":
                if not (-3 <= score <= 0):
                    errors.append(f"safety_profile score {score} not in [-3, 0]")
            else:
                if not (-5 <= score <= 5):
                    errors.append(f"{key} score {score} not in [-5, 5]")

        et = assessment["exploratory_track"]
        for key in EXPLORATORY_CRITERIA:
            score = _extract_score(et[key])
            max_val = 5 if key in ("biological_plausibility", "novelty_opportunity") else 3
            if not (0 <= score <= max_val):
                errors.append(f"{key} score {score} not in [0, {max_val}]")

    return errors


# -------------------------------------------------------------------------
# Stage gating helpers
# -------------------------------------------------------------------------

def compute_stage1_confidence(stage1_evidence: dict[str, Any]) -> dict[str, Any]:
    """Compute Stage 1 biological confidence score from evidence signals.

    Weighted combination of 4 signals (all normalized to [0, 1]):
      - STRING PPI (35%): physical interaction evidence
      - Census coexpression (30%): scRNA cross-validation
      - Pathway count (20%): KEGG + Reactome pathways
      - Expression (15%): CELLxGENE gene availability

    Returns dict with individual scores, weights, and combined confidence.
    """
    # STRING PPI: API returns score in 0-1 range (not 0-1000)
    # Note: required_score *input* param uses 0-1000, but output score column is 0-1
    string_data = stage1_evidence.get("string_ppi", {})
    raw_string = float(string_data.get("max_combined_score", 0))
    string_score = min(raw_string, 1.0) if raw_string <= 1.0 else min(raw_string / 1000.0, 1.0)

    # Census coexpression: p-value gated, then risk_ratio normalized
    census = stage1_evidence.get("census_validation", {})
    coexpr = census.get(
        "coexpression",
        census.get("target_vs_rest", {}).get("coexpression", {}),
    )
    p_val = float(coexpr.get("p_value", 1.0))
    rr = float(coexpr.get("risk_ratio") or 0.0)
    census_score = (1.0 if p_val < 0.05 else 0.0) * min(rr / 3.0, 1.0)

    # Pathway: binary — shared pathway between ligand & receptor
    kegg = stage1_evidence.get("kegg_pathways", {})
    kegg_lig_ids, kegg_lig_names = _extract_pathway_tokens(
        kegg.get("ligand_pathways", []),
        id_key="pathway_id",
    )
    kegg_rec_ids, kegg_rec_names = _extract_pathway_tokens(
        kegg.get("receptor_pathways", []),
        id_key="pathway_id",
    )

    reactome = stage1_evidence.get("reactome_pathways", {})
    reactome_lig_ids, reactome_lig_names = _extract_pathway_tokens(
        reactome.get("ligand_pathways", []),
        id_key="reactome_id",
    )
    reactome_rec_ids, reactome_rec_names = _extract_pathway_tokens(
        reactome.get("receptor_pathways", []),
        id_key="reactome_id",
    )

    has_shared = bool(
        (kegg_lig_ids & kegg_rec_ids)
        or (reactome_lig_ids & reactome_rec_ids)
        or (kegg_lig_names & kegg_rec_names)
        or (reactome_lig_names & reactome_rec_names)
    )

    # Backward compatibility: old format (flat "pathways" list) → count-based fallback
    if (
        not kegg_lig_ids and not kegg_rec_ids and not reactome_lig_ids and not reactome_rec_ids
        and not kegg_lig_names and not kegg_rec_names and not reactome_lig_names and not reactome_rec_names
    ):
        old_kegg = len(kegg.get("pathways", []))
        old_reactome = len(reactome.get("pathways", []))
        pathway_score = min((old_kegg + old_reactome) / 4.0, 1.0)
    else:
        pathway_score = 1.0 if has_shared else 0.0

    # Expression: cell-type-specific expression from Census z-test
    tvr = census.get("target_vs_rest", {})
    gene_a_pct = float(tvr.get("gene_a", {}).get("target_pct", 0))
    gene_b_pct = float(tvr.get("gene_b", {}).get("target_pct", 0))
    genes_expressed = sum(1 for pct in [gene_a_pct, gene_b_pct] if pct > 0)
    expression_score = genes_expressed / 2.0

    # Backward compat: no census target_vs_rest → old available_genes fallback
    if not tvr:
        cellxgene = stage1_evidence.get("cellxgene", {})
        available = {g.upper() for g in cellxgene.get("available_genes", [])}
        # Fallback to legacy format when cellxgene.available_genes is empty
        if not available:
            legacy = stage1_evidence.get("legacy_stage1", {}).get("cellxgene_context", {})
            available = {g.upper() for g in legacy.get("available_genes", [])}
        ligand_name = stage1_evidence.get("ligand", "").upper()
        receptor_name = stage1_evidence.get("receptor", "").upper()
        genes_found = sum(1 for g in [ligand_name, receptor_name] if g and g in available)
        expression_score = genes_found / 2.0

    confidence = round(
        0.35 * string_score
        + 0.30 * census_score
        + 0.20 * pathway_score
        + 0.15 * expression_score,
        4,
    )

    return {
        "confidence": confidence,
        "string_score": round(string_score, 4),
        "census_score": round(census_score, 4),
        "pathway_score": round(pathway_score, 4),
        "expression_score": round(expression_score, 4),
    }


def filter_by_stage1_confidence(
    pairs_with_evidence: list[dict[str, Any]],
    *,
    threshold: float = 0.4,
    min_remaining: int = 5,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Tag L-R pairs by Stage 1 confidence score (no filtering).

    All pairs proceed to Stage 2. Pairs with confidence below *threshold*
    are tagged with ``stage1_low_confidence=True`` for informational purposes.

    Returns (all_pairs, []).  The second element is always an empty list
    for backward compatibility.
    """
    for p in pairs_with_evidence:
        conf = p.get("stage1_confidence", {}).get("confidence", 0)
        if conf < threshold:
            p["stage1_low_confidence"] = True

    return list(pairs_with_evidence), []


VEP_HIGH_IMPACT = frozenset({
    "transcript_ablation", "splice_acceptor_variant", "splice_donor_variant",
    "stop_gained", "frameshift_variant", "stop_lost", "start_lost",
})
VEP_MODERATE_IMPACT = frozenset({
    "missense_variant", "inframe_insertion", "inframe_deletion",
    "protein_altering_variant",
})


def classify_vep_consequence(most_severe_consequence: str) -> str:
    """Classify VEP consequence as high_impact, moderate_impact, or low_impact."""
    if most_severe_consequence in VEP_HIGH_IMPACT:
        return "high_impact"
    if most_severe_consequence in VEP_MODERATE_IMPACT:
        return "moderate_impact"
    return "low_impact"


def should_run_pubmed(max_clinical_phase: str | int | None) -> bool:
    """Stage 3 PubMed gate."""
    if max_clinical_phase is None:
        return False
    if isinstance(max_clinical_phase, int):
        return max_clinical_phase >= 2

    text = str(max_clinical_phase).strip().lower()
    match = re.search(r"(\d+)", text)
    if not match:
        return False
    return int(match.group(1)) >= 2


# -------------------------------------------------------------------------
# Programmatic drug-evidence scoring from ChEMBL indications
# -------------------------------------------------------------------------

_INDICATION_MATCH_ONCOLOGY_SYNONYMS = frozenset({
    "cancer",
    "carcinoma",
    "tumor",
    "tumour",
    "neoplasm",
})


def _normalize_indication_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _core_oncology_tokens(text: str) -> set[str]:
    normalized = _normalize_indication_text(text)
    return {
        token
        for token in normalized.split()
        if token not in _INDICATION_MATCH_ONCOLOGY_SYNONYMS
    }


def _indication_matches_disease(indication_term: str, disease: str) -> bool:
    """Check if an indication term matches the target disease.

    Generic rule:
    - direct normalized substring match first
    - if both sides are oncology terms, allow cancer/carcinoma/tumor/neoplasm
      synonym matching when their non-generic core tokens overlap
    """
    term_normalized = _normalize_indication_text(indication_term)
    disease_normalized = _normalize_indication_text(disease)

    if not term_normalized or not disease_normalized:
        return False

    # Direct match
    if disease_normalized in term_normalized:
        return True

    if not (_indication_is_oncology(indication_term) and infer_oncology_flag(disease)):
        return False

    disease_core = _core_oncology_tokens(disease)
    term_core = _core_oncology_tokens(indication_term)
    if not disease_core or not term_core:
        return False

    return bool(disease_core & term_core)


def _indication_is_oncology(indication_term: str) -> bool:
    """Check if an indication term is oncology-related."""
    return any(kw in indication_term.lower() for kw in _ONCOLOGY_KEYWORDS)


def compute_drug_evidence_scores(
    chembl_drugs: list[dict],
    disease: str,
    opentargets_tractability: list[dict] | None = None,
) -> dict[str, Any]:
    """Programmatically compute existing_drug_evidence and clinical_trial_activity.

    Scoring logic:
      existing_drug_evidence:
        3 = target disease has Phase 3+ or approved drug
        2 = target disease has Phase 1-2 drug
        1 = other indication has approved drug (repurposing candidate)
            OR OpenTargets tractability Approved Drug = True
        0 = no drugs

      clinical_trial_activity:
        3 = target disease has Phase 3+ (multiple)
        2 = target disease has Phase 2+ OR other indication Phase 3+
        1 = other indication has clinical trials
        0 = none

    Args:
        chembl_drugs: List of dicts from _chembl_fallback (with indications).
        disease: Target disease string (e.g. "breast cancer").
        opentargets_tractability: OpenTargets tractability modality list.

    Returns:
        Dict with existing_drug_evidence, clinical_trial_activity, and detail.
    """
    if not chembl_drugs:
        # Check OpenTargets tractability even without ChEMBL drugs
        ot_approved = _check_opentargets_approved(opentargets_tractability)
        return {
            "existing_drug_evidence": 1 if ot_approved else 0,
            "clinical_trial_activity": 0,
            "detail": {
                "disease_phase_max": None,
                "other_phase_max": None,
                "disease_indication_count": 0,
                "other_indication_count": 0,
                "opentargets_approved_drug": ot_approved,
                "matched_disease_drugs": [],
                "matched_other_drugs": [],
            },
        }

    disease_phase_max: float = 0.0
    other_phase_max: float = 0.0
    disease_indication_count = 0
    other_indication_count = 0
    matched_disease_drugs: list[str] = []
    matched_other_drugs: list[str] = []

    for drug in chembl_drugs:
        drug_name = drug.get("drug_name", drug.get("chembl_id", "unknown"))
        indications = drug.get("indications", [])

        drug_has_disease_match = False
        drug_has_other_match = False

        for ind in indications:
            efo_term = ind.get("efo_term") or ind.get("mesh_heading") or ""
            phase = float(ind.get("max_phase") or 0)

            if _indication_matches_disease(efo_term, disease):
                disease_phase_max = max(disease_phase_max, phase)
                disease_indication_count += 1
                drug_has_disease_match = True
            else:
                other_phase_max = max(other_phase_max, phase)
                other_indication_count += 1
                drug_has_other_match = True

        if drug_has_disease_match:
            matched_disease_drugs.append(drug_name)
        elif drug_has_other_match:
            matched_other_drugs.append(drug_name)

    # OpenTargets tractability check
    ot_approved = _check_opentargets_approved(opentargets_tractability)

    # --- existing_drug_evidence scoring ---
    if disease_phase_max >= 3:
        existing_drug_evidence = 3
    elif disease_phase_max >= 1:
        existing_drug_evidence = 2
    elif other_phase_max >= 3 or ot_approved:
        existing_drug_evidence = 1
    else:
        existing_drug_evidence = 0

    # --- clinical_trial_activity scoring ---
    if disease_phase_max >= 3 and disease_indication_count >= 2:
        clinical_trial_activity = 3
    elif disease_phase_max >= 2 or other_phase_max >= 3:
        clinical_trial_activity = 2
    elif other_indication_count > 0:
        clinical_trial_activity = 1
    else:
        clinical_trial_activity = 0

    return {
        "existing_drug_evidence": existing_drug_evidence,
        "clinical_trial_activity": clinical_trial_activity,
        "detail": {
            "disease_phase_max": disease_phase_max if disease_phase_max > 0 else None,
            "other_phase_max": other_phase_max if other_phase_max > 0 else None,
            "disease_indication_count": disease_indication_count,
            "other_indication_count": other_indication_count,
            "opentargets_approved_drug": ot_approved,
            "matched_disease_drugs": matched_disease_drugs,
            "matched_other_drugs": matched_other_drugs,
        },
    }


def _check_opentargets_approved(
    tractability: list[dict] | None,
) -> bool:
    """Check if OpenTargets tractability contains an approved drug."""
    if not tractability:
        return False
    for entry in tractability:
        # OpenTargets tractability modality format:
        #   {"modality": "SM", "top_category": "Approved Drug", "value": True}
        # or nested format with buckets
        if isinstance(entry, dict):
            if entry.get("top_category") == "Approved Drug" and entry.get("value") is True:
                return True
            # Alternative: check for has_drug / approved_drug fields
            if entry.get("approved_drug") is True or entry.get("has_drug") is True:
                return True
    return False


# -------------------------------------------------------------------------
# Deterministic Rubric Scoring Tool
# -------------------------------------------------------------------------

def _score_existing_drug_evidence(gene: str, drug_rows: list[dict],
                                   target_drugs: dict | None = None) -> int:
    """Score existing_drug_evidence (-5 to +5).

    Gene-level drugs (+1 each): unique drug candidates across all diseases.
    Disease-level drugs (-1 each): known drugs for this gene in the target disease.
    Score = clamp(gene_count - disease_count, -5, 5).

    Note: disease_evidence was previously counted here as well (datatypeId ==
    "known_drug"), but that double-counted the same OpenTargets data already
    present in drug_rows. Removed to fix the double-counting bias.
    """
    gene_upper = gene.upper()

    # Gene-level: drugs targeting this gene across ALL diseases
    gene_drug_count = 0
    if target_drugs:
        gene_drug_count = len(target_drugs.get("rows", []))

    # Disease-level: drugs targeting this gene for THIS disease
    disease_drug_count = 0
    for row in drug_rows:
        target_sym = (row.get("target", {}).get("approvedSymbol") or "").upper()
        if target_sym == gene_upper:
            disease_drug_count += 1

    return max(-5, min(5, gene_drug_count - disease_drug_count))


def _has_gwas_genetic_signal(gwas_data: dict | None) -> bool:
    """Check if GWAS data contains genome-wide significant association (p < 5e-8)."""
    if not gwas_data:
        return False
    for assoc in gwas_data.get("gene_associations", []):
        for nested in assoc.get("associations", []):
            pval = nested.get("pvalue") or nested.get("p_value")
            if pval is not None:
                try:
                    if float(pval) < 5e-8:
                        return True
                except (ValueError, TypeError):
                    pass
    return False


def _score_clinical_trial_activity(
    disease_evidence: list[dict],
    target_drugs: dict | None = None,
) -> int:
    """Score clinical_trial_activity (-5 to +5).

    Gene-level: count disease-drug development programs across all diseases.
    Each drug row's indications list represents distinct clinical programs,
    so sum(len(diseases)) gives a more accurate picture of trial activity
    than just counting unique drugs (which is what existing_drug_evidence does).

    Disease-level trials (-1 each): competition in this disease.
    Score = clamp(gene_trial_count - disease_trial_count, -5, 5).
    """
    # Disease-level: trial entries from OT disease_evidence
    trial_sources = {"chembl", "clinicaltrials"}
    disease_trial_count = sum(
        1 for e in disease_evidence
        if (e.get("datasourceId", "") or "").lower() in trial_sources
    )

    # Gene-level: total clinical development programs (drug × indication)
    gene_trial_count = 0
    if target_drugs:
        for row in target_drugs.get("rows", []):
            diseases = row.get("diseases", [])
            gene_trial_count += max(1, len(diseases))

    return max(-5, min(5, gene_trial_count - disease_trial_count))


def _has_vep_functional_impact(vep_data: dict | None) -> bool:
    """Check if VEP data contains high or moderate impact variants."""
    if not vep_data or not vep_data.get("executed"):
        return False
    summary = vep_data.get("impact_summary", {})
    return summary.get("high_impact", 0) > 0 or summary.get("moderate_impact", 0) > 0



# Qualifying datatypeIds for biological plausibility.
# EXCLUDED: "known_drug" (covered by existing_drug_evidence),
#           "genetic_association" (covered by gwas_genetic_support)
_BIO_PLAUSIBILITY_TYPES = frozenset({
    "affected_pathway",
    "literature",
    "animal_model",
    "somatic_mutation",
})


def _score_safety_profile(safety_liabilities: list | None) -> int:
    """Score safety_profile (-3 to 0) from OT safetyLiabilities.

    Distinguishes clinical evidence (PharmGKB, Brennan et al.) from
    preclinical screens (ToxCast, AOP-Wiki) per OT community guidance.

     0: no safety concerns
    -1: preclinical concerns only (ToxCast/AOP-Wiki 3+)
    -2: clinical concerns (PharmGKB/clinical 1-2)
    -3: major clinical concerns (PharmGKB/clinical 3+)
    """
    if not safety_liabilities:
        return 0
    clinical_count = 0
    preclinical_count = 0
    for entry in safety_liabilities:
        src = (entry.get("datasource") or "").lower()
        studies = entry.get("studies") or []
        study_types = [s.get("type", "").lower() for s in studies]
        if src == "pharmgkb" or "clinical" in " ".join(study_types):
            clinical_count += 1
        else:
            preclinical_count += 1
    if clinical_count >= 3:
        return -3
    if clinical_count >= 1:
        return -2
    if preclinical_count >= 3:
        return -1
    return 0


def _min_pval_from_gene_snps(gene_snps: list[dict]) -> float:
    """Extract minimum p-value from gene_snps_in_disease entries."""
    min_pval = 1.0
    for snp in gene_snps:
        for key in ("pvalue", "p_value", "p-value"):
            pval = snp.get(key)
            if pval is not None:
                try:
                    min_pval = min(min_pval, float(pval))
                except (ValueError, TypeError):
                    pass
        for nested in snp.get("associations", []):
            for key in ("pvalue", "p_value"):
                pval = nested.get(key)
                if pval is not None:
                    try:
                        min_pval = min(min_pval, float(pval))
                    except (ValueError, TypeError):
                        pass
    return min_pval


def _score_gwas_support(gwas_data: dict | None) -> int:
    """Score gwas_support (0-3) from disease-specific GWAS hits only.

    Uses disease_specific_hits (computed by stage2_service) as the sole
    signal.  gene_associations without disease overlap score 0.

    Score 3: gene_snps_in_disease with p < 5e-8 (genome-wide significant overlap)
    Score 2: gene_in_trait OR gene_snps_in_disease (any p-value)
    Score 1: proximity_hits only (±500kb)
    Score 0: no disease-specific GWAS evidence
    """
    if not gwas_data:
        return 0

    dsh = gwas_data.get("disease_specific_hits", {})
    if not isinstance(dsh, dict):
        return 0

    n_gene_in_trait = dsh.get("n_gene_in_trait", 0) or 0
    n_gene_snps = dsh.get("n_gene_snps_in_disease", 0) or 0
    n_proximity = dsh.get("n_proximity_hits", 0) or 0

    # Score 3: genome-wide significant overlap
    if n_gene_snps > 0:
        gene_snps = dsh.get("gene_snps_in_disease", [])
        min_pval = _min_pval_from_gene_snps(gene_snps)
        if min_pval < 5e-8:
            return 3

    # Score 2: direct disease link
    if n_gene_in_trait > 0 or n_gene_snps > 0:
        return 2

    # Score 1: proximity only
    if n_proximity > 0:
        return 1

    return 0


def _score_tractability(tractability: list[dict] | None) -> int:
    """Score tractability (0-3) from OT tractability data across ALL modalities.

    Considers SM (small molecule), AB (antibody), PR (PROTAC), OC (other).
    Takes the best score across all modalities.
    """
    if not tractability:
        return 0
    # Collect per-modality labels
    modality_labels: dict[str, dict[str, bool]] = {}
    for entry in tractability:
        mod = (entry.get("modality") or "").upper()
        label = (entry.get("id") or entry.get("top_category") or "").lower()
        value = entry.get("value", False)
        if mod not in modality_labels:
            modality_labels[mod] = {}
        modality_labels[mod][label] = value

    best = 0
    for _mod, labels in modality_labels.items():
        if labels.get("approved drug", False):
            best = max(best, 3)
        elif labels.get("advanced clinical", False):
            best = max(best, 2)
        elif labels.get("phase 1 clinical", False):
            best = max(best, 2)
        elif labels.get("structure with ligand", False) or labels.get("high-quality ligand", False):
            best = max(best, 1)
        elif labels.get("druggable family", False):
            best = max(best, 1)
        elif any(v for v in labels.values()):
            best = max(best, 1)
    return best


def _score_biological_plausibility(
    disease_evidence: list[dict], vep_data: dict | None = None,
) -> int:
    """Score biological_plausibility (0-5) via breadth-weighted evidence.

    Filters disease_evidence to datatypeIds NOT already scored by other
    criteria (excludes known_drug, genetic_association).  Rewards breadth
    (distinct qualifying types present) plus a bonus for high-confidence
    evidence.

    Score = min(5, n_types + max_score_bonus)
      - n_types:         count of distinct qualifying datatypeId present (0-4)
      - max_score_bonus: +1 if max(filtered scores) >= 0.7

    VEP boost: high_impact variants -> +1, capped at 5.
    """
    filtered = [
        e for e in disease_evidence
        if e.get("datatypeId") in _BIO_PLAUSIBILITY_TYPES
    ]
    if not filtered:
        score = 0
    else:
        n_types = len({e["datatypeId"] for e in filtered})
        max_score = max((e.get("score", 0) or 0) for e in filtered)
        max_score_bonus = 1 if max_score >= 0.7 else 0
        score = min(5, n_types + max_score_bonus)
    # VEP boost: high_impact variants strengthen biological plausibility
    if vep_data and vep_data.get("executed"):
        if vep_data.get("impact_summary", {}).get("high_impact", 0) > 0:
            score = min(score + 1, 5)
    return score


def _score_novelty_opportunity(associations: list[dict],
                                associations_truncated: bool = False) -> int:
    """Score novelty_opportunity (0-5) inverse of how well-established the target is.

    0: 30+ associations (truncated, well-established)
    1: 16-30 associations
    2: 6-15 associations
    3: 3-5 associations
    4: 1-2 associations
    5: 0 associations (completely novel, e.g. ST-only discovery)

    When truncated=True, actual count exceeds what's returned (20+).
    Cap novelty at 1.
    """
    count = len(associations) if associations else 0
    if count == 0:
        score = 5
    elif count <= 2:
        score = 4
    elif count <= 5:
        score = 3
    elif count <= 15:
        score = 2
    elif count <= 30:
        score = 1
    else:
        score = 0
    # If truncated, at least 20+ associations exist → cap novelty at 1
    if associations_truncated and score > 1:
        score = 1
    return score


@tool
def compute_rubric_scores(data_dir: str) -> str:
    """Compute deterministic rubric scores for ALL genes from Stage 2 evidence.

    Reads ot_*.json, known_drugs.json, stage2_evidence.json from evidence/.
    Saves updated assessment_results.json and rubric_scores.csv.
    Returns summary JSON.
    """
    import csv
    import glob

    data_path = Path(data_dir).expanduser().resolve()
    evidence_dir = data_path / "evidence"

    # Load known_drugs
    kd_path = evidence_dir / "known_drugs.json"
    drug_rows: list[dict] = []
    if kd_path.exists():
        kd = json.loads(kd_path.read_text())
        drugs_data = kd.get("drugs", {})
        if isinstance(drugs_data, dict):
            drug_rows = drugs_data.get("rows", [])
        elif isinstance(drugs_data, list):
            drug_rows = drugs_data

    # Load stage2_evidence for GWAS data
    s2_path = evidence_dir / "stage2_evidence.json"
    stage2: dict = {}
    if s2_path.exists():
        stage2 = json.loads(s2_path.read_text())

    # Find all ot_*.json files
    ot_files = sorted(glob.glob(str(evidence_dir / "ot_*.json")))
    if not ot_files:
        return json.dumps({"error": "No ot_*.json files found", "genes_scored": 0})

    results: list[dict] = []

    for ot_path_str in ot_files:
        ot_path = Path(ot_path_str)
        gene = ot_path.stem.replace("ot_", "")
        ot = json.loads(ot_path.read_text())

        if not ot.get("executed", False):
            continue

        disease_evidence = ot.get("disease_evidence", [])
        target_info = ot.get("target_info", {})
        tractability_data = target_info.get("tractability", [])
        safety_data = target_info.get("safetyLiabilities", [])
        associations = ot.get("associations", [])

        # GWAS + VEP from stage2_evidence
        gwas_data = None
        vep_data = None
        if isinstance(stage2, dict):
            gene_s2 = stage2.get(gene, {})
            if isinstance(gene_s2, dict):
                gwas_data = gene_s2.get("gwas", {})
                vep_data = gene_s2.get("vep", {})

        # Target-level drugs (from ot_{GENE}.json)
        target_drugs = ot.get("target_drugs")

        # Score 7 criteria
        existing_drug = _score_existing_drug_evidence(gene, drug_rows, target_drugs)
        clinical_trial = _score_clinical_trial_activity(disease_evidence, target_drugs)
        safety = _score_safety_profile(safety_data)
        gwas = _score_gwas_support(gwas_data)
        tract = _score_tractability(tractability_data)
        bio_plaus = _score_biological_plausibility(disease_evidence, vep_data)
        novelty = _score_novelty_opportunity(associations, ot.get("associations_truncated", False))

        validated_total = existing_drug + clinical_trial + safety
        exploratory_total = gwas + tract + bio_plaus + novelty
        combined_total = validated_total + exploratory_total

        assessment_for_classify = {
            "validated_track": {
                "existing_drug_evidence": existing_drug,
                "clinical_trial_activity": clinical_trial,
                "safety_profile": safety,
            },
            "exploratory_track": {
                "gwas_genetic_support": gwas,
                "tractability": tract,
                "biological_plausibility": bio_plaus,
                "novelty_opportunity": novelty,
            },
        }
        classification = classify_target(assessment_for_classify)
        priority = compute_priority(assessment_for_classify)

        row = {
            "gene": gene,
            "existing_drug_evidence": existing_drug,
            "clinical_trial_activity": clinical_trial,
            "safety_profile": safety,
            "validated_total": validated_total,
            "gwas_support": gwas,
            "tractability": tract,
            "biological_plausibility": bio_plaus,
            "novelty_opportunity": novelty,
            "exploratory_total": exploratory_total,
            "combined_total": combined_total,
            "classification": classification,
            "priority": priority,
            "ot_disease_evidence_count": len(disease_evidence),
            "ot_associations_count": len(associations),
        }
        results.append(row)

    # Sort by combined_total descending, tiebreak: exploratory_total → bio_plausibility → tractability
    results.sort(
        key=lambda r: (
            r["combined_total"],
            r["exploratory_total"],
            r["biological_plausibility"],
            r["tractability"],
        ),
        reverse=True,
    )

    # Stage 3 candidate selection: combined_total >= threshold
    stage3_threshold = 10
    eligible = [r for r in results if r["classification"] != "insufficient_evidence"]
    stage3_genes = [r["gene"] for r in eligible if r["combined_total"] >= stage3_threshold]
    for r in results:
        r["stage3_candidate"] = r["gene"] in stage3_genes

    # Save assessment_results.json
    assessment = {
        "assessment_date": __import__("datetime").datetime.now().isoformat(),
        "disease": stage2.get("_disease", "unknown") if isinstance(stage2, dict) else "unknown",
        "rubric_assessment": results,
        "stage3_candidates": [
            {"gene": r["gene"], "exploratory_total": r["exploratory_total"],
             "combined_total": r["combined_total"],
             "priority": r["priority"], "classification": r["classification"]}
            for r in results if r["stage3_candidate"]
        ],
        "summary": {
            "total_genes": len(results),
            "stage3_count": len(stage3_genes),
            "insufficient_count": sum(1 for r in results if r["classification"] == "insufficient_evidence"),
        },
    }
    (evidence_dir / "assessment_results.json").write_text(
        json.dumps(assessment, indent=2, ensure_ascii=False) + "\n"
    )

    # Save CSV
    csv_path = evidence_dir / "rubric_scores.csv"
    fieldnames = [
        "gene", "existing_drug_evidence", "clinical_trial_activity",
        "safety_profile", "validated_total",
        "gwas_support", "tractability", "biological_plausibility",
        "novelty_opportunity", "exploratory_total", "combined_total",
        "classification", "priority", "stage3_candidate",
    ]
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    return json.dumps({
        "success": True,
        "genes_scored": len(results),
        "stage3_count": len(stage3_genes),
        "csv_path": str(csv_path),
        "assessment_path": str(evidence_dir / "assessment_results.json"),
        "stage3_candidates": [
            {"gene": r["gene"], "exploratory": r["exploratory_total"], "combined": r["combined_total"]}
            for r in results if r["stage3_candidate"]
        ],
    }, indent=2)


# ---------------------------------------------------------------------------
# Gene → L-R Pair mapping for FEATURED subset
# ---------------------------------------------------------------------------


def map_featured_genes_to_pairs(
    stage3_genes: list[str],
    lr_pairs: list[dict],
) -> list[dict]:
    """Return L-R pairs containing at least one FEATURED gene.

    Args:
        stage3_genes: Gene symbols selected by compute_rubric_scores
            (from assessment_results.json stage3_candidates).
        lr_pairs: All L-R pairs from load_lr_candidates output.

    Returns:
        Subset of *lr_pairs* where ligand OR receptor is in *stage3_genes*.
    """
    featured_set = {g.upper() for g in stage3_genes}
    return [
        p for p in lr_pairs
        if (p.get("ligand") or "").upper() in featured_set
        or (p.get("receptor") or "").upper() in featured_set
    ]


# ---------------------------------------------------------------------------
# Stage 1 Gate — blocks Stage 3 until all FEATURED pairs complete Stage 1
# ---------------------------------------------------------------------------


@tool
def validate_stage1_gate(data_dir: str) -> str:
    """Validate Stage 1 completeness for all FEATURED L-R pairs.

    Reads assessment_results.json for stage3_candidates, maps each gene
    back to L-R pairs from lr_candidates.json, and checks that
    ``evidence/stage1_{LIGAND}--{RECEPTOR}.json`` exists for every
    expected pair.

    Returns success=true only when ALL expected files are present.
    Call this BEFORE proceeding to Stage 3.  If ``success`` is false,
    complete Stage 1 for the ``missing_pairs`` first, then re-call.
    """
    data_dir_path = Path(data_dir).expanduser().resolve()
    evidence_dir = data_dir_path / "evidence"

    # 1. Load stage3_candidates
    assessment_path = evidence_dir / "assessment_results.json"
    if not assessment_path.exists():
        return json.dumps({
            "success": False,
            "error": "assessment_results.json not found — run compute_rubric_scores first.",
        })
    assessment = json.loads(assessment_path.read_text())
    stage3_genes = [c["gene"] for c in assessment.get("stage3_candidates", [])]
    if not stage3_genes:
        return json.dumps({
            "success": False,
            "error": "No stage3_candidates in assessment_results.json.",
        })

    # 2. Load lr_candidates → all pairs
    lr_path = data_dir_path / "lr_candidates.json"
    if not lr_path.exists():
        return json.dumps({"success": False, "error": "lr_candidates.json not found."})
    lr_data = json.loads(lr_path.read_text())
    lr_pairs = extract_lr_pairs(lr_data)

    # 3. Map genes → pairs
    featured_pairs = map_featured_genes_to_pairs(stage3_genes, lr_pairs)
    if not featured_pairs:
        return json.dumps({
            "success": False,
            "error": "No L-R pairs matched the FEATURED genes.",
            "stage3_genes": stage3_genes,
        })

    # 4. Check stage1 files
    completed: list[str] = []
    missing: list[str] = []
    for pair in featured_pairs:
        ligand = (pair.get("ligand") or "").upper()
        receptor = (pair.get("receptor") or "").upper()
        pair_key = f"{ligand}_{receptor}"
        stage1_file = evidence_dir / f"stage1_{ligand}--{receptor}.json"
        if stage1_file.exists():
            completed.append(pair_key)
        else:
            missing.append(pair_key)

    return json.dumps({
        "success": len(missing) == 0,
        "expected_count": len(featured_pairs),
        "completed_count": len(completed),
        "missing_count": len(missing),
        "missing_pairs": missing,
        "stage3_genes": stage3_genes,
    }, indent=2)


# ---------------------------------------------------------------------------
# Reference Card — authoritative evidence summary for report_writer
# ---------------------------------------------------------------------------


@tool
def build_evidence_summary(data_dir: str) -> str:
    """Build a Reference Card with exact values from all evidence files.

    Returns a structured JSON summary that report_writer MUST use as the
    single source of truth for all numeric values, PMIDs, drug names,
    classifications, and pathway names.

    ALL values in this card are authoritative — use them directly.
    Do NOT modify, round, re-derive, or invent any values.
    """
    data_dir_path = Path(data_dir).expanduser().resolve()
    evidence_dir = data_dir_path / "evidence"

    # 1. Load assessment_results.json
    assessment_path = evidence_dir / "assessment_results.json"
    if not assessment_path.exists():
        return json.dumps({"error": "assessment_results.json not found"})
    assessment = json.loads(assessment_path.read_text())

    # Build per-gene rubric lookup
    rubric_by_gene: dict[str, dict] = {}
    for row in assessment.get("rubric_assessment", []):
        rubric_by_gene[row["gene"]] = {
            "classification": row.get("classification", "unknown"),
            "priority": row.get("priority", "unranked"),
            "validated_total": row.get("validated_total", 0),
            "exploratory_total": row.get("exploratory_total", 0),
            "combined_total": row.get("combined_total", 0),
            "existing_drug_evidence": row.get("existing_drug_evidence", 0),
            "clinical_trial_activity": row.get("clinical_trial_activity", 0),
            "safety_profile": row.get("safety_profile", 0),
            "gwas_support": row.get("gwas_support", 0),
            "tractability": row.get("tractability", 0),
            "biological_plausibility": row.get("biological_plausibility", 0),
            "novelty_opportunity": row.get("novelty_opportunity", 0),
            "stage3_candidate": row.get("stage3_candidate", False),
        }

    stage3_genes = [c["gene"] for c in assessment.get("stage3_candidates", [])]

    # 2. Load stage3_*.json → drugs + PMIDs per gene
    stage3_data: dict[str, dict] = {}
    for gene in stage3_genes:
        s3_path = evidence_dir / f"stage3_{gene}.json"
        if not s3_path.exists():
            stage3_data[gene] = {"drugs": [], "pmids": [], "error": "file not found"}
            continue
        s3 = json.loads(s3_path.read_text())
        drugs = []
        for d in s3.get("chembl_drugs", []):
            drugs.append({
                "chembl_id": d.get("chembl_id", ""),
                "drug_name": d.get("drug_name", ""),
                "mechanism_of_action": d.get("mechanism_of_action"),
                "indications": d.get("indications", []),
                "max_phase": d.get("max_phase"),
            })
        pmids = []
        for p in s3.get("pubmed_papers", []):
            pmid = p.get("pmid", "")
            if pmid:
                pmids.append({"pmid": str(pmid), "title": p.get("title", "")})
        stage3_data[gene] = {"drugs": drugs, "pmids": pmids}

    # 3. Load stage1_*.json → per-pair biological context
    stage1_data: dict[str, dict] = {}
    for s1_path in sorted(evidence_dir.glob("stage1_*.json")):
        if s1_path.name in ("stage1_evidence.json", "stage1_confidence.json", "stage1_audit.json"):
            continue
        try:
            s1 = json.loads(s1_path.read_text())
        except Exception:
            continue
        ligand = s1.get("ligand", "")
        receptor = s1.get("receptor", "")
        pair_key = f"{ligand}_{receptor}"

        string_ppi = s1.get("string_ppi", {})
        kegg = s1.get("kegg_pathways", {})
        reactome = s1.get("reactome_pathways", {})
        census = s1.get("census_cross_validation", s1.get("census_validation", {}))

        stage1_data[pair_key] = {
            "ligand": ligand,
            "receptor": receptor,
            "string_ppi": {
                "interaction_found": string_ppi.get("interaction_found", False),
                "max_combined_score": string_ppi.get("max_combined_score", 0),
            },
            "kegg_pathways": {
                "ligand_pathways": [
                    pw.get("name", pw.get("pathway_name", str(pw)))
                    for pw in (kegg.get("ligand_pathways") or [])
                    if isinstance(pw, dict)
                ] or kegg.get("ligand_pathways", []),
                "receptor_pathways": [
                    pw.get("name", pw.get("pathway_name", str(pw)))
                    for pw in (kegg.get("receptor_pathways") or [])
                    if isinstance(pw, dict)
                ] or kegg.get("receptor_pathways", []),
            },
            "reactome_pathways": {
                "ligand_pathways": [
                    pw.get("name", pw.get("pathway_name", str(pw)))
                    for pw in (reactome.get("ligand_pathways") or [])
                    if isinstance(pw, dict)
                ] or reactome.get("ligand_pathways", []),
                "receptor_pathways": [
                    pw.get("name", pw.get("pathway_name", str(pw)))
                    for pw in (reactome.get("receptor_pathways") or [])
                    if isinstance(pw, dict)
                ] or reactome.get("receptor_pathways", []),
            },
            "census": _extract_census_summary(census),
        }

    # 4. Load known_drugs.json
    kd_path = evidence_dir / "known_drugs.json"
    known_drugs = []
    if kd_path.exists():
        kd = json.loads(kd_path.read_text())
        if isinstance(kd, dict):
            known_drugs = kd.get("drugs", kd.get("known_drugs", []))
        elif isinstance(kd, list):
            known_drugs = kd

    # 5. Build all-genes druggability summary from rubric (full 14 columns)
    all_genes_matrix = []
    for row in assessment.get("rubric_assessment", []):
        all_genes_matrix.append({
            "gene": row["gene"],
            "existing_drug_evidence": row.get("existing_drug_evidence", 0),
            "clinical_trial_activity": row.get("clinical_trial_activity", 0),
            "safety_profile": row.get("safety_profile", 0),
            "validated_total": row.get("validated_total", 0),
            "gwas_support": row.get("gwas_support", 0),
            "tractability": row.get("tractability", 0),
            "biological_plausibility": row.get("biological_plausibility", 0),
            "novelty_opportunity": row.get("novelty_opportunity", 0),
            "exploratory_total": row.get("exploratory_total", 0),
            "combined_total": row.get("combined_total", 0),
            "classification": row.get("classification", "unknown"),
            "priority": row.get("priority", "unranked"),
            "stage3_candidate": row.get("stage3_candidate", False),
        })

    # Assemble Reference Card
    featured_cards = []
    for gene in stage3_genes:
        card = {
            "gene": gene,
            "rubric": rubric_by_gene.get(gene, {}),
            "stage3": stage3_data.get(gene, {}),
            "stage1_pairs": {
                k: v for k, v in stage1_data.items()
                if gene.upper() in [
                    part.strip().upper()
                    for part in k.replace("--", "_").split("_", 1)
                ]
            },
        }
        featured_cards.append(card)

    # Build pre-formatted markdown template
    disease_name = assessment.get("disease", "unknown")
    md_template = _build_markdown_template(
        disease_name, stage3_genes, featured_cards,
        all_genes_matrix, stage1_data,
    )

    reference_card = {
        "reference_card_version": "2.0",
        "instruction": (
            "This is the AUTHORITATIVE Reference Card with a PRE-FORMATTED MARKDOWN TEMPLATE. "
            "Use the `markdown_template` field as the SKELETON for drug.md. "
            "The template contains all correct values (scores, PMIDs, drug names, pathways). "
            "Your job: EXPAND each section with 2-4 sentences of biological interpretation. "
            "Do NOT change any numbers, PMIDs, drug names, or classifications in the template. "
            "Do NOT remove any PMID hyperlinks — they are all verified correct. "
            "ADD narrative around the pre-filled data to create a comprehensive report."
        ),
        "disease": disease_name,
        "stage3_candidates": stage3_genes,
        "featured_genes": featured_cards,
        "all_genes_druggability": all_genes_matrix,
        "known_drugs_disease_level": known_drugs[:20] if isinstance(known_drugs, list) else known_drugs,
        "markdown_template": md_template,
    }

    # Write the template directly to drug.md as a draft
    draft_path = data_dir_path / "drug.md"
    draft_path.write_text(md_template + "\n", encoding="utf-8")

    # Return a compact card (without the full template) + instructions
    reference_card["markdown_template"] = (
        f"DRAFT WRITTEN to {draft_path} ({len(md_template)} chars, "
        f"{md_template.count(chr(10))} lines, "
        f"{md_template.count('pubmed.ncbi')} PMID hyperlinks). "
        f"Read it with read_file, expand each <!-- EXPAND --> comment "
        f"with 2-4 sentences, then save via save_drug_md."
    )

    return json.dumps(reference_card, indent=2, ensure_ascii=False)


def _build_markdown_template(
    disease: str,
    stage3_genes: list[str],
    featured_cards: list[dict],
    all_genes_matrix: list[dict],
    stage1_data: dict[str, dict],
) -> str:
    """Build a pre-formatted markdown template with all correct values."""
    lines: list[str] = []

    # Section 1: Executive Summary skeleton
    n_genes = len(all_genes_matrix)
    n_featured = len(stage3_genes)
    lines.append(f"# Therapeutic Target Assessment Report — {disease}")
    lines.append("")
    lines.append("## 1. Executive Summary")
    lines.append("")
    lines.append(f"This report presents a comprehensive therapeutic target assessment for **{disease}** "
                 f"based on spatial transcriptomics cell-cell interaction (CCI) analysis. "
                 f"A total of **{n_genes} unique genes** from the top-30 L-R pairs were evaluated "
                 f"through a 3-stage evidence funnel, yielding **{n_featured} featured candidates** "
                 f"for deep-dive analysis.")
    lines.append("")
    lines.append("### Featured Candidates")
    lines.append("")
    for card in featured_cards:
        gene = card["gene"]
        r = card.get("rubric", {})
        lines.append(f"- **{gene}** — Classification: {r.get('classification', 'N/A')}, "
                     f"Priority: {r.get('priority', 'N/A')}, "
                     f"Exploratory Total: {r.get('exploratory_total', 'N/A')}, "
                     f"Combined Total: {r.get('combined_total', 'N/A')}")
    lines.append("")
    lines.append("<!-- EXPAND: Add 2-3 sentences summarizing key therapeutic opportunities -->")
    lines.append("")

    # Section 2: Druggability Matrix (full 14-column rubric table)
    lines.append("## 2. Druggability Matrix")
    lines.append("")
    lines.append("<!-- EXPAND: Add 2-3 sentences interpreting the overall scoring landscape -->")
    lines.append("")
    lines.append(
        "| Gene | Drug Ev. | Trial | Safety | Val. Total "
        "| GWAS | Tract. | Bio. Plaus. | Novelty | Expl. Total "
        "| Combined | Classification | Priority | Stage3 |"
    )
    lines.append(
        "|------|--------:|------:|-------:|-----------:"
        "|-----:|-------:|------------:|--------:|------------:"
        "|---------:|----------------|----------|--------|"
    )
    # Sort: stage3 candidates first (by combined_total desc), then rest (by combined_total desc)
    featured_rows = sorted(
        [r for r in all_genes_matrix if r.get("stage3_candidate")],
        key=lambda r: r.get("combined_total", 0), reverse=True,
    )
    other_rows = sorted(
        [r for r in all_genes_matrix if not r.get("stage3_candidate")],
        key=lambda r: r.get("combined_total", 0), reverse=True,
    )
    for row in featured_rows + other_rows:
        marker = "**" if row.get("stage3_candidate") else ""
        lines.append(
            f"| {marker}{row['gene']}{marker} "
            f"| {row.get('existing_drug_evidence', 0)} "
            f"| {row.get('clinical_trial_activity', 0)} "
            f"| {row.get('safety_profile', 0)} "
            f"| {row.get('validated_total', 0)} "
            f"| {row.get('gwas_support', 0)} "
            f"| {row.get('tractability', 0)} "
            f"| {row.get('biological_plausibility', 0)} "
            f"| {row.get('novelty_opportunity', 0)} "
            f"| {row.get('exploratory_total', 0)} "
            f"| {row.get('combined_total', 0)} "
            f"| {row.get('classification', 'N/A')} "
            f"| {row.get('priority', 'N/A')} "
            f"| {'Yes' if row.get('stage3_candidate') else ''} |"
        )
    lines.append("")

    # Scoring Legend
    lines.append("### Scoring Legend")
    lines.append("")
    lines.append("Each gene is scored on two independent tracks reflecting different "
                 "types of therapeutic evidence. The **Validated Track** captures existing "
                 "clinical and drug development activity, while the **Exploratory Track** "
                 "captures genetic, biological, and novelty signals that suggest untapped "
                 "therapeutic potential.")
    lines.append("")

    # Validated Track table
    lines.append("#### Validated Track (Clinical Evidence)")
    lines.append("")
    lines.append("| Column | Full Name | Range | Data Source | Scoring Logic | Interpretation |")
    lines.append("|--------|-----------|-------|-------------|---------------|----------------|")
    lines.append(
        "| Drug Ev. | existing_drug_evidence | -5 to +5 | OpenTargets | "
        "(gene-level drug count) minus (disease-level drug count), clamped | "
        "Positive = repurposing opportunity across indications; "
        "Negative = saturated drug landscape for this disease; "
        "Zero = no known drugs |"
    )
    lines.append(
        "| Trial | clinical_trial_activity | -5 to +5 | ChEMBL, ClinicalTrials | "
        "(gene-level clinical programs) minus (disease-level trial entries), clamped | "
        "Positive = active pipeline with novel indication potential; "
        "Negative = competitive/crowded trial space |"
    )
    lines.append(
        "| Safety | safety_profile | -3 to 0 | PharmGKB, ToxCast, AOP-Wiki | "
        "0 = no concerns; -1 = preclinical signals only (ToxCast/AOP-Wiki 3+); "
        "-2 = clinical concerns (PharmGKB 1-2 entries); "
        "-3 = major clinical safety issues (PharmGKB 3+) | "
        "Penalty score: more negative = higher safety risk |"
    )
    lines.append(
        "| Val. Total | validated_total | -13 to +10 | (computed) | "
        "Sum of Drug Ev. + Trial + Safety | "
        "Overall clinical readiness; higher = stronger existing drug development evidence |"
    )
    lines.append("")

    # Exploratory Track table
    lines.append("#### Exploratory Track (Genetic & Biological Evidence)")
    lines.append("")
    lines.append("| Column | Full Name | Range | Data Source | Scoring Logic | Interpretation |")
    lines.append("|--------|-----------|-------|-------------|---------------|----------------|")
    lines.append(
        "| GWAS | gwas_support | 0-3 | GWAS Catalog | "
        "0 = no disease-specific GWAS evidence; "
        "1 = proximity hits only (within 500kb); "
        "2 = direct disease link (gene-in-trait or gene-SNP overlap); "
        "3 = genome-wide significant overlap (p < 5e-8) | "
        "Genetic validation strength for this disease |"
    )
    lines.append(
        "| Tract. | tractability | 0-3 | OpenTargets Tractability | "
        "0 = unknown druggability; "
        "1 = predicted structure or druggable family; "
        "2 = clinical precedent (advanced clinical / Phase 1); "
        "3 = approved drug exists for this modality | "
        "How feasible it is to develop a drug against this target |"
    )
    lines.append(
        "| Bio. Plaus. | biological_plausibility | 0-5 | OpenTargets Evidence + Ensembl VEP | "
        "Count of distinct evidence types (affected_pathway, literature, animal_model, "
        "somatic_mutation) + bonus if max score >= 0.7, + VEP high-impact variant boost | "
        "Breadth and strength of biological evidence linking gene to disease |"
    )
    lines.append(
        "| Novelty | novelty_opportunity | 0-5 | OpenTargets Associations | "
        "Inverse of number of disease associations: "
        "5 = 0 associations (completely novel, e.g. ST-only discovery); "
        "4 = 1-2; 3 = 3-5; 2 = 6-15; 1 = 16-30; "
        "0 = 30+ (well-established target) | "
        "Higher = less explored, greater opportunity for novel discovery |"
    )
    lines.append(
        "| Expl. Total | exploratory_total | 0-16 | (computed) | "
        "Sum of GWAS + Tract. + Bio. Plaus. + Novelty | "
        "Overall exploratory potential; higher = stronger biological rationale for investigation |"
    )
    lines.append("")

    # Classification & Priority rules
    lines.append("#### Combined Score, Classification & Priority")
    lines.append("")
    lines.append("| Field | Description |")
    lines.append("|-------|-------------|")
    lines.append(
        "| **Combined** | validated_total + exploratory_total. "
        "Overall target attractiveness across both tracks. |"
    )
    lines.append(
        "| **Classification** | Rule-based assignment: "
        "`validated_target` if Drug Ev. >= 3 or (Drug Ev. >= 1 and Val. Total >= 3); "
        "`exploratory_target` if GWAS >= 1 or Tract. >= 2 or Bio. Plaus. >= 3; "
        "`novel_candidate` if Bio. Plaus. >= 2 or Novelty >= 3 or (Tract. >= 1 and Novelty >= 2); "
        "`insufficient_evidence` otherwise. |"
    )
    lines.append(
        "| **Priority** | For validated_target: `high` (Combined >= 10), `medium` (>= 5), `low`. "
        "For exploratory/novel: `high` (Expl. Total >= 12), `medium` (>= 7), `low`. "
        "insufficient_evidence is always `unranked`. |"
    )
    lines.append(
        "| **Stage3** | Top 7 genes by exploratory_total are selected as featured candidates "
        "and proceed to Stage 3 deep-dive analysis (ChEMBL drug profiling + PubMed literature search). |"
    )
    lines.append("")

    # Section 3: Featured Candidate Deep Dives
    lines.append("## 3. Featured Candidate Deep Dives")
    lines.append("")

    for card in featured_cards:
        gene = card["gene"]
        r = card.get("rubric", {})
        s3 = card.get("stage3", {})
        pairs = card.get("stage1_pairs", {})

        lines.append(f"### {gene} — Classification: {r.get('classification', 'N/A')} | Priority: {r.get('priority', 'N/A')}")
        lines.append("")

        # A. Drug Profile
        lines.append("**A. Drug Profile**")
        lines.append("")
        drugs = s3.get("drugs", [])
        if drugs:
            for d in drugs:
                name = d.get("drug_name", "Unknown")
                cid = d.get("chembl_id", "")
                moa = d.get("mechanism_of_action") or "mechanism not available"
                phase = d.get("max_phase", "N/A")
                raw_ind = d.get("indications", [])
                indications = ", ".join(
                    (i.get("name", str(i)) if isinstance(i, dict) else str(i))
                    for i in raw_ind
                ) or "N/A"
                lines.append(f"- **{name}** (ChEMBL: {cid}) — {moa}, Max Phase: {phase}, Indications: {indications}")
        else:
            lines.append("- No known drugs targeting this gene")
        lines.append("")
        lines.append("<!-- EXPAND: Add 2-3 sentences interpreting the drug landscape -->")
        lines.append("")

        # B. Literature Evidence
        lines.append("**B. Literature Evidence**")
        lines.append("")
        pmids = s3.get("pmids", [])
        if pmids:
            for p in pmids:
                pmid = p.get("pmid", "")
                title = p.get("title", "")
                lines.append(f"- [PMID: {pmid}](https://pubmed.ncbi.nlm.nih.gov/{pmid}/) — \"{title}\"")
        else:
            lines.append("- No PubMed citations available")
        lines.append("")
        lines.append("<!-- EXPAND: Summarize key findings from the literature -->")
        lines.append("")

        # C. Biological Context
        lines.append("**C. Biological Context (Stage 1)**")
        lines.append("")
        if pairs:
            for pair_key, pair_data in pairs.items():
                lig = pair_data.get("ligand", "")
                rec = pair_data.get("receptor", "")
                ppi = pair_data.get("string_ppi", {})
                score = ppi.get("max_combined_score", "N/A")
                found = ppi.get("interaction_found", False)
                lines.append(f"- **{lig}–{rec}**: STRING PPI score={score}, interaction={'confirmed' if found else 'not found'}")

                kegg = pair_data.get("kegg_pathways", {})
                for role, key in [("ligand", "ligand_pathways"), ("receptor", "receptor_pathways")]:
                    pws = kegg.get(key, [])
                    if pws:
                        pw_str = "; ".join(str(p) for p in pws[:3])
                        lines.append(f"  - KEGG ({role}): {pw_str}")

                reactome = pair_data.get("reactome_pathways", {})
                for role, key in [("ligand", "ligand_pathways"), ("receptor", "receptor_pathways")]:
                    pws = reactome.get(key, [])
                    if pws:
                        pw_str = "; ".join(str(p) for p in pws[:3])
                        lines.append(f"  - Reactome ({role}): {pw_str}")

                census = pair_data.get("census", {})
                if census.get("risk_ratio") is not None:
                    lines.append(f"  - Census: risk_ratio={census['risk_ratio']}, p_value={census.get('p_value', 'N/A')}")
        else:
            lines.append("- No Stage 1 data available for this gene")
        lines.append("")
        lines.append("<!-- EXPAND: Interpret biological context and pathway relevance -->")
        lines.append("")

        # D. Rubric Assessment
        lines.append("**D. Rubric Assessment**")
        lines.append("")
        lines.append(f"- Validated Track: existing_drug_evidence={r.get('existing_drug_evidence', 0)}, "
                     f"clinical_trial_activity={r.get('clinical_trial_activity', 0)}, "
                     f"safety_profile={r.get('safety_profile', 0)} "
                     f"→ **validated_total={r.get('validated_total', 0)}**")
        lines.append(f"- Exploratory Track: gwas_support={r.get('gwas_support', 0)}, "
                     f"tractability={r.get('tractability', 0)}, "
                     f"biological_plausibility={r.get('biological_plausibility', 0)}, "
                     f"novelty_opportunity={r.get('novelty_opportunity', 0)} "
                     f"→ **exploratory_total={r.get('exploratory_total', 0)}**")
        lines.append(f"- **Combined Total: {r.get('combined_total', 0)}** | "
                     f"Classification: {r.get('classification', 'N/A')} | "
                     f"Priority: {r.get('priority', 'N/A')}")
        lines.append("")
        lines.append("<!-- EXPAND: Add therapeutic recommendation based on evidence -->")
        lines.append("")
        lines.append("---")
        lines.append("")

    # Section 4: Pipeline Summary
    lines.append("## 4. Pipeline Execution Summary & Recommendations")
    lines.append("")
    lines.append(f"- Total genes assessed: {n_genes}")
    lines.append(f"- Featured candidates (Stage 3): {n_featured}")
    lines.append(f"- Featured genes: {', '.join(stage3_genes)}")
    lines.append("")
    lines.append("<!-- EXPAND: Add recommendations for validated targets, exploratory targets, and next steps -->")
    lines.append("")

    return "\n".join(lines)


def _extract_census_summary(census: dict | Any) -> dict:
    """Extract census cross-validation summary safely."""
    if not isinstance(census, dict):
        return {}
    tvr = census.get("target_vs_rest", {})
    if not isinstance(tvr, dict):
        return {}
    coexpr = tvr.get("coexpression", {})
    if not isinstance(coexpr, dict):
        return {"target_vs_rest": tvr}
    return {
        "risk_ratio": coexpr.get("risk_ratio"),
        "p_value": coexpr.get("p_value"),
        "coexpression_detected": coexpr.get("risk_ratio", 0) > 1 if coexpr.get("risk_ratio") else None,
    }


# ---------------------------------------------------------------------------
# Validation — automated drug.md vs evidence cross-check
# ---------------------------------------------------------------------------


@tool
def validate_drug_md(data_dir: str) -> str:
    """Validate drug.md against evidence files for hallucinations.

    Checks:
    1. All PMIDs in drug.md exist in stage3_*.json pubmed_papers
    2. Classification/priority labels match assessment_results.json
    3. Drug names match stage3_*.json chembl_drugs
    4. No fabricated numeric patterns (e.g. decimal rubric scores)

    Returns: {valid: bool, total_checks: int, issues: [...]}
    Call this AFTER save_drug_md to catch hallucinations before finalizing.
    """
    data_dir_path = Path(data_dir).expanduser().resolve()
    evidence_dir = data_dir_path / "evidence"
    drug_md_path = data_dir_path / "drug.md"

    if not drug_md_path.exists():
        return json.dumps({"valid": False, "error": "drug.md not found"})

    drug_text = drug_md_path.read_text()
    issues: list[dict] = []

    # 1. PMID validation
    evidence_pmids: set[str] = set()
    for s3_path in evidence_dir.glob("stage3_*.json"):
        try:
            s3 = json.loads(s3_path.read_text())
            for p in s3.get("pubmed_papers", []):
                pmid = str(p.get("pmid", "")).strip()
                if pmid:
                    evidence_pmids.add(pmid)
        except Exception:
            pass

    # Find PMIDs in drug.md (patterns: PMID 12345678, PMID: 12345678, (PMID: 12345678))
    doc_pmids = set(re.findall(r'(?:PMID[:\s]*|pmid[:\s]*)(\d{7,8})', drug_text))
    fabricated_pmids = doc_pmids - evidence_pmids
    if fabricated_pmids:
        issues.append({
            "type": "FABRICATED_PMID",
            "severity": "critical",
            "count": len(fabricated_pmids),
            "fabricated": sorted(fabricated_pmids),
            "valid_pmids": sorted(evidence_pmids),
        })

    # 2. Classification/Priority validation
    assessment_path = evidence_dir / "assessment_results.json"
    if assessment_path.exists():
        assessment = json.loads(assessment_path.read_text())
        for row in assessment.get("rubric_assessment", []):
            gene = row["gene"]
            if gene.upper() not in drug_text.upper():
                continue
            true_class = row.get("classification", "")
            true_priority = row.get("priority", "")

            # Check for wrong classification near gene name
            gene_sections = drug_text.split(gene)
            for section in gene_sections[1:]:  # after gene name
                chunk = section[:500]  # look in nearby text
                if "validated_target" in chunk.lower() and true_class != "validated_target":
                    issues.append({
                        "type": "WRONG_CLASSIFICATION",
                        "severity": "high",
                        "gene": gene,
                        "claimed": "validated_target",
                        "actual": true_class,
                    })
                if "novel_candidate" in chunk.lower() and true_class != "novel_candidate":
                    issues.append({
                        "type": "WRONG_CLASSIFICATION",
                        "severity": "high",
                        "gene": gene,
                        "claimed": "novel_candidate",
                        "actual": true_class,
                    })

    # 3. Decimal rubric score detection (should be integers)
    decimal_scores = re.findall(
        r'(?:validated|exploratory|combined)[_ ](?:total|track|score)[:\s]*(\d+\.\d+)',
        drug_text, re.IGNORECASE
    )
    if decimal_scores:
        issues.append({
            "type": "DECIMAL_RUBRIC_SCORES",
            "severity": "high",
            "detail": "Rubric scores should be integers, found decimals",
            "values": decimal_scores[:10],
        })

    # 4. Fabricated column detection
    for fake_col in ["OT Association Score", "ST Colocalization Score"]:
        if fake_col.lower() in drug_text.lower():
            issues.append({
                "type": "FABRICATED_COLUMN",
                "severity": "high",
                "column": fake_col,
                "detail": f"'{fake_col}' does not exist in evidence files",
            })

    total_checks = len(doc_pmids) + 4  # PMIDs + classification + decimals + columns
    return json.dumps({
        "valid": len(issues) == 0,
        "total_checks": total_checks,
        "pmids_in_doc": len(doc_pmids),
        "pmids_in_evidence": len(evidence_pmids),
        "fabricated_pmid_count": len(fabricated_pmids) if fabricated_pmids else 0,
        "issue_count": len(issues),
        "issues": issues,
    }, indent=2)
