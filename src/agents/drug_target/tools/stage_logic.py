"""Shared stage decision logic for the drug target pipeline."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from langchain_core.tools import tool


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


# -------------------------------------------------------------------------
# Deterministic Rubric Scoring Tool
# -------------------------------------------------------------------------

def _score_existing_drug_evidence(gene: str, drug_rows: list[dict],
                                   disease_evidence: list[dict] | None = None) -> int:
    """Score existing_drug_evidence (0-3) from known_drugs + disease_evidence."""
    gene_upper = gene.upper()
    max_phase = 0

    # Check known_drugs rows (disease-level)
    for row in drug_rows:
        target_sym = (row.get("target", {}).get("approvedSymbol") or "").upper()
        if target_sym == gene_upper:
            phase = row.get("phase", 0) or 0
            max_phase = max(max_phase, phase)

    # Check disease_evidence known_drug entries (gene-level from OT)
    for ev in (disease_evidence or []):
        if ev.get("datatypeId") == "known_drug":
            cp = ev.get("clinicalPhase") or ev.get("clinical_phase") or 0
            try:
                max_phase = max(max_phase, int(cp))
            except (ValueError, TypeError):
                pass

    if max_phase >= 3:
        return 3
    if max_phase >= 1:
        return 2
    # Check indirect: any drug row targeting same gene family
    for row in drug_rows:
        target_sym = (row.get("target", {}).get("approvedSymbol") or "").upper()
        if target_sym and gene_upper[:3] in target_sym:
            return 1
    return 0


def _score_clinical_trial_activity(disease_evidence: list[dict]) -> int:
    """Score clinical_trial_activity (0-3) from OT disease_evidence."""
    trial_sources = {"chembl", "clinicaltrials"}
    trial_count = sum(
        1 for e in disease_evidence
        if (e.get("datasourceId", "") or "").lower() in trial_sources
    )
    if trial_count >= 3:
        return 3
    if trial_count >= 1:
        return 2
    # Check for any genetic/literature evidence as weak signal
    if any(e.get("datatypeId") == "genetic_association" for e in disease_evidence):
        return 1
    return 0


def _score_mechanism_relevance(disease_evidence: list[dict]) -> int:
    """Score mechanism_relevance (0-3) from OT disease_evidence."""
    has_pathway = any(
        e.get("datatypeId") in ("affected_pathway", "known_drug")
        for e in disease_evidence
    )
    has_genetic = any(
        e.get("datatypeId") == "genetic_association"
        for e in disease_evidence
    )
    has_literature = any(
        e.get("datatypeId") == "literature"
        for e in disease_evidence
    )
    if has_pathway and has_genetic:
        return 3
    if has_pathway or has_genetic:
        return 2
    if has_literature:
        return 1
    return 0


def _score_safety_profile(safety_liabilities: list | None) -> int:
    """Score safety_profile (-2 to 0) from OT safetyLiabilities."""
    if not safety_liabilities:
        return 0
    count = len(safety_liabilities)
    if count >= 2:
        return -2
    if count >= 1:
        return -1
    return 0


def _score_gwas_support(gwas_data: dict | None) -> int:
    """Score gwas_support (0-3) from stage2_evidence GWAS data.

    Checks both gene_associations (gene-specific SNPs) and
    trait_associations (disease-level GWAS hits) for p-values.
    Also checks disease_specific_hits for gene-in-trait evidence.
    """
    if not gwas_data:
        return 0

    min_pval = 1.0
    total_hits = 0

    # 1. gene_associations (gene-specific mapped SNPs)
    gene_assocs = gwas_data.get("gene_associations", [])
    for assoc in gene_assocs:
        pval = assoc.get("p_value") or assoc.get("pvalue") or assoc.get("p-value")
        if pval is not None:
            try:
                min_pval = min(min_pval, float(pval))
            except (ValueError, TypeError):
                pass
        # Check nested associations for pvalue
        for nested in assoc.get("associations", []):
            pval = nested.get("pvalue") or nested.get("p_value")
            if pval is not None:
                try:
                    min_pval = min(min_pval, float(pval))
                except (ValueError, TypeError):
                    pass
    total_hits += len(gene_assocs)

    # 2. disease_specific_hits (gene SNPs found in disease GWAS)
    dsh = gwas_data.get("disease_specific_hits", {})
    n_gene_in_trait = dsh.get("n_gene_in_trait", 0) or 0
    n_gene_snps = dsh.get("n_gene_snps_in_disease", 0) or 0
    total_hits += n_gene_in_trait + n_gene_snps

    # 3. trait_associations as fallback signal (disease-level)
    trait_assocs = gwas_data.get("trait_associations", [])
    if trait_assocs and min_pval >= 1.0:
        # Use trait-level p-values as weaker evidence
        for assoc in trait_assocs[:20]:
            pval = assoc.get("pvalue") or assoc.get("p_value")
            if pval is not None:
                try:
                    min_pval = min(min_pval, float(pval))
                except (ValueError, TypeError):
                    pass

    # Scoring
    if min_pval < 5e-8 and (total_hits >= 2 or len(gene_assocs) >= 2):
        return 3
    if min_pval < 5e-8:
        return 2
    if min_pval < 1e-5 or total_hits >= 1:
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


def _score_biological_plausibility(disease_evidence: list[dict]) -> int:
    """Score biological_plausibility (0-3) from OT disease_evidence scores."""
    if not disease_evidence:
        return 0
    max_score = max((e.get("score", 0) or 0) for e in disease_evidence)
    if max_score >= 0.7:
        return 3
    if max_score >= 0.4:
        return 2
    if max_score > 0:
        return 1
    return 0


def _score_novelty_opportunity(associations: list[dict],
                                associations_truncated: bool = False) -> int:
    """Score novelty_opportunity (0-3) inverse of how well-established the target is.

    When truncated=True, actual count exceeds what's returned.
    Apply normal scoring on visible count but cap at 1 (can't be truly novel
    if associations were truncated, meaning 20+ exist).
    """
    count = len(associations) if associations else 0
    if count <= 5:
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


def _classify_target(validated_total: int, exploratory_total: int,
                     existing_drug: int, gwas: int, tractability: int,
                     bio_plausibility: int, novelty: int) -> str:
    """Classify target based on rubric pass logic."""
    # Validated track pass
    validated_pass = (existing_drug >= 2) or (existing_drug >= 1 and validated_total >= 2)
    # Exploratory track pass
    exploratory_pass = (gwas >= 1) and (tractability >= 1 or bio_plausibility >= 2)

    if validated_pass:
        return "validated_target"
    if exploratory_pass:
        return "exploratory_target"
    if bio_plausibility >= 2 or novelty >= 2:
        return "novel_candidate"
    return "insufficient_evidence"


def _assign_priority(classification: str, validated_total: int,
                     exploratory_total: int, combined_total: int) -> str:
    """Assign priority based on classification and scores."""
    if classification == "insufficient_evidence":
        return "unranked"
    if classification == "validated_target":
        if combined_total >= 6:
            return "high"
        if combined_total >= 3:
            return "medium"
        return "low"
    # exploratory or novel
    if exploratory_total >= 8:
        return "high"
    if exploratory_total >= 5:
        return "medium"
    return "low"


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

        # GWAS from stage2_evidence
        gwas_data = None
        if isinstance(stage2, dict):
            gene_s2 = stage2.get(gene, {})
            if isinstance(gene_s2, dict):
                gwas_data = gene_s2.get("gwas", {})

        # Score 8 criteria
        existing_drug = _score_existing_drug_evidence(gene, drug_rows, disease_evidence)
        clinical_trial = _score_clinical_trial_activity(disease_evidence)
        mechanism = _score_mechanism_relevance(disease_evidence)
        safety = _score_safety_profile(safety_data)
        gwas = _score_gwas_support(gwas_data)
        tract = _score_tractability(tractability_data)
        bio_plaus = _score_biological_plausibility(disease_evidence)
        novelty = _score_novelty_opportunity(associations, ot.get("associations_truncated", False))

        validated_total = existing_drug + clinical_trial + mechanism + safety
        exploratory_total = gwas + tract + bio_plaus + novelty
        combined_total = validated_total + exploratory_total

        classification = _classify_target(
            validated_total, exploratory_total,
            existing_drug, gwas, tract, bio_plaus, novelty,
        )
        priority = _assign_priority(
            classification, validated_total, exploratory_total, combined_total,
        )

        row = {
            "gene": gene,
            "existing_drug_evidence": existing_drug,
            "clinical_trial_activity": clinical_trial,
            "mechanism_relevance": mechanism,
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

    # Sort by exploratory_total descending, tiebreak: bio_plausibility → tractability → combined
    results.sort(
        key=lambda r: (
            r["exploratory_total"],
            r["biological_plausibility"],
            r["tractability"],
            r["combined_total"],
        ),
        reverse=True,
    )

    # Stage 3 candidate selection: top N by exploratory_total (unified ranking)
    stage3_max = 7
    eligible = [r for r in results if r["classification"] != "insufficient_evidence"]
    stage3_genes = {r["gene"] for r in eligible[:stage3_max]}
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
        "mechanism_relevance", "safety_profile", "validated_total",
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
