"""Shared stage decision logic for the drug target pipeline."""

from __future__ import annotations

import re
from typing import Any


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
VALIDATED_CRITERIA = ("existing_drug_evidence", "clinical_trial_activity", "mechanism_relevance", "safety_profile")
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
                AND (tractability >= 1 OR biological_plausibility >= 2)
    """
    et = assessment.get("exploratory_track", {})
    if not isinstance(et, dict):
        return {"scores": {k: 0 for k in EXPLORATORY_CRITERIA}, "total": int(et) if et else 0, "pass": False}
    scores = {k: _extract_score(et.get(k, 0)) for k in EXPLORATORY_CRITERIA}
    total = sum(scores.values())

    gwas = scores["gwas_genetic_support"]
    tract = scores["tractability"]
    bio = scores["biological_plausibility"]
    passed = gwas >= 1 and (tract >= 1 or bio >= 2)

    return {"scores": scores, "total": total, "pass": passed}


def classify_target(assessment: dict[str, Any]) -> str:
    """Classify target: validated_target | exploratory_target | novel_candidate | insufficient_evidence."""
    vt = compute_validated_track(assessment)
    et = compute_exploratory_track(assessment)

    if vt["pass"]:
        return "validated_target"
    if et["pass"]:
        return "exploratory_target"

    # novel_candidate: biological_plausibility >= 2 or novelty_opportunity >= 2
    et_scores = et["scores"]
    if et_scores["biological_plausibility"] >= 2 or et_scores["novelty_opportunity"] >= 2:
        return "novel_candidate"

    return "insufficient_evidence"


def compute_priority(assessment: dict[str, Any]) -> str:
    """Compute priority: high | medium | low | unranked."""
    classification = classify_target(assessment)
    if classification == "insufficient_evidence":
        return "unranked"

    vt = compute_validated_track(assessment)
    et = compute_exploratory_track(assessment)

    if classification == "validated_target":
        if vt["total"] >= 6:
            return "high"
        if vt["total"] >= 3:
            return "medium"
        return "low"

    if classification == "exploratory_target":
        if et["total"] >= 8:
            return "high"
        if et["total"] >= 5:
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
                if not (-2 <= score <= 0):
                    errors.append(f"safety_profile score {score} not in [-2, 0]")
            else:
                if not (0 <= score <= 3):
                    errors.append(f"{key} score {score} not in [0, 3]")

        et = assessment["exploratory_track"]
        for key in EXPLORATORY_CRITERIA:
            score = _extract_score(et[key])
            if not (0 <= score <= 3):
                errors.append(f"{key} score {score} not in [0, 3]")

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
    rr = float(coexpr.get("risk_ratio", 0.0))
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


def should_run_vep(*, oncology_flag: bool, has_gwas_variants: bool) -> bool:
    """Stage 2 VEP gate: run when oncology OR GWAS variants available."""
    return bool(oncology_flag or has_gwas_variants)


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
