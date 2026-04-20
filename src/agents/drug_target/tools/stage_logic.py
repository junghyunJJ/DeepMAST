"""Shared stage decision logic for the drug target pipeline."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime

# Note: _resolve_data_dir is imported lazily inside each call site below to avoid
# circular import (evidence_loader.py imports from this module at top level).
# PR2-3: 5 functions previously used raw Path().expanduser().resolve() — now all 6
# (incl. apply_stage1_filter) inline-import _resolve_data_dir for env-var fallback
# and LLM-typo tolerance.


def _atomic_write_text(path, content: str, encoding: str = "utf-8") -> None:
    """P2-8: write to a temp file in the same dir, then rename atomically.

    Prevents partial-write corruption of assessment_results.json (and similar)
    if the process crashes mid-write or the disk fills. Uses os.replace which
    is atomic on POSIX and acts as a single rename system call. Same-directory
    temp file ensures the rename stays within the same filesystem.
    """
    import os, tempfile
    path_str = str(path)
    parent = os.path.dirname(path_str) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp_", suffix=".write", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
        os.replace(tmp_path, path_str)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
from pathlib import Path
from typing import Any

from langchain_core.tools import tool
from src.agents.drug_target.tools.chembl_resolver import resolve_chembl_molecule
from src.agents.drug_target.tools.moa_enrichment import enrich_drugs_in_place
from src.agents.drug_target.tools.stage2_service import extract_lr_pairs

logger = logging.getLogger(__name__)


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

_STAGE1_NON_PAIR_ARTIFACTS = frozenset({
    "stage1_evidence.json",
    "stage1_confidence.json",
    "stage1_filter.json",
    "stage1_audit.json",
    "stage1_filter_results.json",
})
_STAGE1_PAIR_ARTIFACT_RE = re.compile(r"^stage1_[A-Za-z0-9-]+--[A-Za-z0-9-]+\.json$")


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


def _is_stage1_pair_artifact(path: Path) -> bool:
    """Return True only for per-pair Stage 1 detail artifacts."""
    name = path.name
    if name in _STAGE1_NON_PAIR_ARTIFACTS:
        return False
    return bool(_STAGE1_PAIR_ARTIFACT_RE.match(name))


def compute_stage1_filter(stage1_evidence: dict[str, Any]) -> dict[str, Any]:
    """Pass/fail filter for Stage 1 L-R pairs.

    Criteria (ALL must be met — strict, no relaxation for missing STRING records):
      - STRING combined score > 0.8
      - Census coexpression p-value < 0.05
      - Census gene_a (ligand) p-value < 0.05
      - Census gene_b (receptor) p-value < 0.05

    ``string_status`` is informational only — it records whether the pair was
    found in the STRING TSV but never changes the pass/fail decision.
    """
    string_data = stage1_evidence.get("string_ppi", {})
    _raw_score = string_data.get("max_combined_score", 0)
    raw_string = float(_raw_score) if _raw_score is not None else 0.0
    string_combined = min(raw_string, 1.0) if raw_string <= 1.0 else min(raw_string / 1000.0, 1.0)
    string_record_found = bool(
        string_data.get("string_record_found",
                         string_data.get("interaction_found", True))
    )

    census = stage1_evidence.get("census_validation", {})
    tvr = census.get("target_vs_rest", {})

    def _pvalue_or_fail(container: dict, key: str = "p_value") -> float:
        """Null-safe p-value parse. Explicit None → 1.0 (non-passing)."""
        v = container.get(key)
        return 1.0 if v is None else float(v)

    coexpr_p = _pvalue_or_fail(tvr.get("coexpression", {}))
    gene_a_p = _pvalue_or_fail(tvr.get("gene_a", {}))
    gene_b_p = _pvalue_or_fail(tvr.get("gene_b", {}))

    string_status = "in_db" if string_record_found else "no_record"
    passed = (
        string_combined > 0.8
        and coexpr_p < 0.05
        and gene_a_p < 0.05
        and gene_b_p < 0.05
    )

    return {
        "passed": passed,
        "string_combined": round(string_combined, 4),
        "string_status": string_status,
        "census_coexpr_pvalue": coexpr_p,
        "census_gene_a_pvalue": gene_a_p,
        "census_gene_b_pvalue": gene_b_p,
    }



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


# Key aliases: flat LLM keys -> canonical criterion names
_VALIDATED_KEY_ALIASES = {
    "drug_evidence": "existing_drug_evidence",
    "existing_drug": "existing_drug_evidence",
    "existing_drug_evidence": "existing_drug_evidence",
    "trial": "clinical_trial_activity",
    "clinical_trial": "clinical_trial_activity",
    "clinical_trial_activity": "clinical_trial_activity",
    "safety": "safety_profile",
    "safety_profile": "safety_profile",
}

_EXPLORATORY_KEY_ALIASES = {
    "gwas": "gwas_genetic_support",
    "gwas_support": "gwas_genetic_support",
    "gwas_genetic_support": "gwas_genetic_support",
    "tractability": "tractability",
    "biological_plausibility": "biological_plausibility",
    "bio_plausibility": "biological_plausibility",
    "bio_plaus": "biological_plausibility",
    "novelty": "novelty_opportunity",
    "novelty_opportunity": "novelty_opportunity",
}


def _normalize_matrix_row_to_tracks(row: dict[str, Any]) -> dict[str, Any]:
    """Reconstruct validated_track/exploratory_track from flat keys if missing.

    LLMs sometimes pass flat rows (e.g., {"drug_evidence": 3, "gwas": 2})
    instead of nested dicts (e.g., {"validated_track": {"existing_drug_evidence": 3}}).
    This normalizer handles both formats.
    """
    if isinstance(row.get("validated_track"), dict) and isinstance(row.get("exploratory_track"), dict):
        return row  # Already has nested dicts, no normalization needed

    normalized = dict(row)

    # Reconstruct validated_track from flat keys
    if not isinstance(normalized.get("validated_track"), dict):
        vt: dict[str, Any] = {}
        for flat_key, canonical in _VALIDATED_KEY_ALIASES.items():
            if flat_key in normalized and canonical not in vt:
                vt[canonical] = normalized[flat_key]
        if vt:
            normalized["validated_track"] = vt

    # Reconstruct exploratory_track from flat keys
    if not isinstance(normalized.get("exploratory_track"), dict):
        et: dict[str, Any] = {}
        for flat_key, canonical in _EXPLORATORY_KEY_ALIASES.items():
            if flat_key in normalized and canonical not in et:
                et[canonical] = normalized[flat_key]
        if et:
            normalized["exploratory_track"] = et

    return normalized


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
        item = _normalize_matrix_row_to_tracks(dict(row))
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

@tool
def apply_stage1_filter(data_dir: str) -> str:
    """Apply Stage 1 pass/fail filter and update stage3_candidates.

    Reads stage1 evidence, applies filtering criteria:
    - STRING combined score > 0.8
    - Census coexpression p-value < 0.05
    - Census gene_a p-value < 0.05
    - Census gene_b p-value < 0.05

    Saves stage1_filter_results.csv and updates assessment_results.json
    to keep only genes that appear in at least one passed pair.
    """
    from src.agents.drug_target.tools.evidence_loader import _resolve_data_dir

    base = _resolve_data_dir(data_dir)
    evidence_dir = base / "evidence"

    # 1. Load stage1_evidence.json
    evidence_path = evidence_dir / "stage1_evidence.json"
    if not evidence_path.exists():
        return json.dumps({"success": False, "error": "stage1_evidence.json not found"})

    stage1_evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

    # 2. Apply filter to each pair
    results = []
    passed_genes: set[str] = set()
    for pair_key, evidence in stage1_evidence.items():
        parts = pair_key.split("^", 1)
        if len(parts) != 2:
            continue
        ligand, receptor = parts
        filt = compute_stage1_filter(evidence)
        filt["ligand"] = ligand
        filt["receptor"] = receptor
        # Add census target_vs_rest summary fields
        census = evidence.get("census_validation", {})
        tvr = census.get("target_vs_rest", {})
        for prefix, key in [("gene_a", "gene_a"), ("gene_b", "gene_b"), ("coexpr", "coexpression")]:
            sub = tvr.get(key, {})
            filt[f"{prefix}_target_pct"] = round(float(sub.get("target_pct") or 0), 4)
            filt[f"{prefix}_risk_ratio"] = round(float(sub.get("risk_ratio") or 0), 4)
        results.append(filt)
        if filt["passed"]:
            passed_genes.add(ligand)
            passed_genes.add(receptor)

    # 3. Save CSV
    import csv
    csv_path = evidence_dir / "stage1_filter_results.csv"
    fieldnames = ["ligand", "receptor", "passed", "string_combined", "string_status",
                  "census_coexpr_pvalue", "census_gene_a_pvalue", "census_gene_b_pvalue",
                  "gene_a_target_pct", "gene_a_risk_ratio",
                  "gene_b_target_pct", "gene_b_risk_ratio",
                  "coexpr_target_pct", "coexpr_risk_ratio"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in sorted(results, key=lambda x: (not x["passed"], x["ligand"])):
            writer.writerow(r)

    # 3b. PR1-2: Sidecar JSON for hypothesis_writer (load_evidence_files globs only *.json).
    # Same row data as the CSV; consumed by the deterministic FAILED-pair block in
    # save_evidence (PR1-6) and by hypothesis_writer prompt rules (PR1-7).
    json_sidecar_path = evidence_dir / "stage1_filter_results.json"
    json_sidecar_path.write_text(
        json.dumps(
            sorted(results, key=lambda x: (not x["passed"], x["ligand"])),
            indent=2,
        ),
        encoding="utf-8",
    )

    # 4. Update assessment_results.json (schema_version=3):
    # Single-field contract: `stage3_candidates` is overwritten IN PLACE with the
    # intersection of (rubric >=10) AND (Stage 1 strict PASS). Both deep_diver and
    # hypothesis_writer consume the same narrowed list.
    assessment_path = evidence_dir / "assessment_results.json"
    updated_assessment = False
    if assessment_path.exists():
        assessment = json.loads(assessment_path.read_text(encoding="utf-8"))
        assessment["schema_version"] = 3

        rubric_candidates = assessment.get("stage3_candidates", [])
        passed_upper = {g.upper() for g in passed_genes}
        narrowed = [
            c for c in rubric_candidates
            if (c.get("gene") or c.get("gene_symbol", "")).upper() in passed_upper
        ]
        assessment["stage3_candidates"] = narrowed
        assessment["stage1_filter_applied"] = True
        assessment.setdefault("summary", {})["stage3_count"] = len(narrowed)

        # Update per-row stage3_candidate to reflect the post-filter narrow set.
        for row in assessment.get("rubric_assessment", []):
            gene = (row.get("gene") or "").upper()
            row["stage3_candidate"] = bool(
                gene
                and gene in passed_upper
                and row.get("classification") != "insufficient_evidence"
                and row.get("combined_total", 0) >= 10
            )
        _atomic_write_text(assessment_path, json.dumps(assessment, indent=2))
        updated_assessment = True

        # 5. Regenerate rubric_scores.csv to match updated assessment
        rubric_rows = assessment.get("rubric_assessment", [])
        if rubric_rows:
            csv_path_rubric = evidence_dir / "rubric_scores.csv"
            # SYNC: keep in sync with compute_rubric_scores() fieldnames (~line 1170)
            rubric_fieldnames = [
                "gene", "existing_drug_evidence", "clinical_trial_activity",
                "safety_profile", "validated_total",
                "gwas_support", "tractability", "biological_plausibility",
                "novelty_opportunity", "exploratory_total", "combined_total",
                "classification", "priority", "stage3_candidate",
            ]
            with open(csv_path_rubric, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=rubric_fieldnames, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rubric_rows)

    passed_pairs = [r for r in results if r["passed"]]
    failed_pairs = [r for r in results if not r["passed"]]

    return json.dumps({
        "success": True,
        "total_pairs": len(results),
        "passed_pairs": len(passed_pairs),
        "failed_pairs": len(failed_pairs),
        "passed_genes": sorted(passed_genes),
        "csv_path": str(csv_path),
        "rubric_csv_updated": updated_assessment,
        "assessment_updated": updated_assessment,
    })


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
        study_types = [(s.get("type") or "").lower() for s in studies]
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


def _extract_ot_disease_score(ot_data: dict[str, Any]) -> float:
    """Extract disease-specific OpenTargets association score from ot_*.json.

    Prefers max(disease_evidence[*].score) because it is disease-filtered
    (higher score = stronger target-disease link for the input disease).
    Falls back to associations[0].score, then legacy flat keys.
    Returns 0.0 if no signal is available.
    """
    if not isinstance(ot_data, dict):
        return 0.0
    de = ot_data.get("disease_evidence") or []
    if isinstance(de, list) and de:
        try:
            best = max(
                (float(e.get("score") or 0) for e in de if isinstance(e, dict)),
                default=0.0,
            )
            if best:
                return best
        except Exception:
            pass
    assocs = ot_data.get("associations") or []
    if isinstance(assocs, list) and assocs:
        first = assocs[0]
        if isinstance(first, dict):
            try:
                val = float(first.get("score") or 0)
                if val:
                    return val
            except Exception:
                pass
    legacy = ot_data.get("association_score") or ot_data.get("overall_association_score") or 0
    try:
        return float(legacy or 0)
    except Exception:
        return 0.0


@tool
def compute_rubric_scores(data_dir: str) -> str:
    """Compute deterministic rubric scores for ALL genes from Stage 2 evidence.

    Reads ot_*.json, known_drugs.json, stage2_evidence.json from evidence/.
    Saves updated assessment_results.json and rubric_scores.csv.
    Returns summary JSON.
    """
    import csv
    import glob
    from src.agents.drug_target.tools.evidence_loader import _resolve_data_dir

    # PR2-3: use _resolve_data_dir for env-var fallback when LLM passes empty/wrong path
    data_path = _resolve_data_dir(data_dir)
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
        # PR2-4: activate the previously-unused validate_rubric_assessment.
        # Catches scoring-function bugs (out-of-range values) at the source rather than
        # silently propagating through classify_target / compute_priority.
        rubric_errors = validate_rubric_assessment(assessment_for_classify)
        if rubric_errors:
            raise ValueError(
                f"Rubric scoring out of range for gene {gene}: {rubric_errors}. "
                f"This indicates a bug in one of the _score_* functions."
            )
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

    # Save assessment_results.json (schema_version=3).
    # stage3_candidates is written here as the RUBRIC-QUALIFIED pool; apply_stage1_filter
    # later overwrites it in place with the (rubric ∩ Stage 1 PASS) intersection so both
    # deep_diver and hypothesis_writer consume the same narrowed list.
    assessment = {
        "schema_version": 3,
        "assessment_date": datetime.now().isoformat(),
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
    # P2-8: atomic temp+rename instead of write_text.
    _atomic_write_text(
        evidence_dir / "assessment_results.json",
        json.dumps(assessment, indent=2, ensure_ascii=False) + "\n",
    )

    # Save CSV
    csv_path = evidence_dir / "rubric_scores.csv"
    # SYNC: keep in sync with apply_stage1_filter() rubric_fieldnames
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
    from src.agents.drug_target.tools.evidence_loader import _resolve_data_dir  # PR2-3
    data_dir_path = _resolve_data_dir(data_dir)
    evidence_dir = data_dir_path / "evidence"

    # 1. Load stage3_candidates (narrowed: rubric ∩ Stage 1 PASS).
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
    # P2-1: quality check parity with validate_stage3_gate.
    # apply_stage1_filter sets stage1_filter_applied=true on success. If absent
    # OR False, the filter step never ran cleanly — files may exist but the
    # narrow set is unreliable. Refuse the gate to force a re-run.
    if not assessment.get("stage1_filter_applied"):
        return json.dumps({
            "success": False,
            "error": (
                "stage1_filter_applied is False/missing in assessment_results.json. "
                "Re-run apply_stage1_filter (or run_stage1_batch which calls it) "
                "before calling validate_stage1_gate."
            ),
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
# Stage 3 Gate — checks that Stage 3 evidence files exist for all candidates
# ---------------------------------------------------------------------------


@tool
def validate_stage3_gate(data_dir: str) -> str:
    """Validate Stage 3 completeness for all stage3_candidates.

    Reads assessment_results.json for stage3_candidates and checks that
    ``evidence/stage3_{GENE}.json`` exists for every candidate gene.

    Returns success=true only when ALL expected files are present.
    Call this after Stage 3 completes to verify no genes were skipped.
    If ``success`` is false, complete Stage 3 for the ``missing_genes``
    first, then re-call.
    """
    from src.agents.drug_target.tools.evidence_loader import _resolve_data_dir  # PR2-3
    data_dir_path = _resolve_data_dir(data_dir)
    evidence_dir = data_dir_path / "evidence"

    # 1. Load stage3_candidates (single narrowed set — rubric ∩ Stage 1 PASS).
    # Both deep_diver and hypothesis_writer run on this list.
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

    # 2. Check stage3 files — both existence AND data quality
    found: list[str] = []
    missing: list[str] = []
    genes_with_errors: list[str] = []
    for gene in stage3_genes:
        stage3_file = evidence_dir / f"stage3_{gene}.json"
        if stage3_file.exists():
            found.append(gene)
            # Check data quality: did the query actually succeed?
            try:
                data = json.loads(stage3_file.read_text())
                has_errors = bool(data.get("errors"))
                not_executed = not data.get("executed", False)
                if has_errors and not_executed:
                    genes_with_errors.append(gene)
            except (json.JSONDecodeError, OSError):
                genes_with_errors.append(gene)
        else:
            missing.append(gene)

    result = {
        "success": len(missing) == 0,
        "total": len(stage3_genes),
        "found": len(found),
        "completed_genes": found,
        "missing_genes": missing,
        "genes_with_errors": genes_with_errors,
    }
    if genes_with_errors:
        result["warning"] = (
            f"{len(genes_with_errors)} of {len(found)} genes have API errors "
            f"(no drug data retrieved): {', '.join(genes_with_errors)}. "
            f"Consider retrying after ChEMBL API recovers."
        )
    return json.dumps(result, indent=2)


# ---------------------------------------------------------------------------
# Reference Card — authoritative evidence summary for report_writer
# ---------------------------------------------------------------------------


_chembl_drug_cache: dict[str, dict] = {}


def _resolve_chembl_drug(chembl_id: str) -> dict:
    """Resolve CHEMBL ID to drug name and type via local-first ChEMBL lookup."""
    if chembl_id in _chembl_drug_cache:
        return _chembl_drug_cache[chembl_id]
    result = resolve_chembl_molecule(chembl_id, allow_api_fallback=True)
    _chembl_drug_cache[chembl_id] = result
    return result


def _prebuild_target_assessment(
    data_dir_path: Path,
    evidence_dir: Path,
    disease_name: str,
    rubric_by_gene: dict[str, dict],
    stage3_data: dict[str, dict],
    stage1_data: dict[str, dict],
    stage3_genes: list[str] | None = None,
) -> None:
    """Pre-build target_assessment.json deterministically from evidence data.

    Mirrors the drug.md pre-build pattern: all factual data is assembled
    programmatically so the LLM doesn't need to construct the JSON schema.
    """
    import logging
    _log = logging.getLogger(__name__)

    # A. Load L-R pairs
    lr_path = data_dir_path / "lr_candidates.json"
    lr_pairs: list[dict] = []
    if lr_path.exists():
        lr_data = json.loads(lr_path.read_text(encoding="utf-8"))
        if isinstance(lr_data, dict):
            lr_pairs = lr_data.get("pairs", lr_data.get("lr_pairs", []))
        elif isinstance(lr_data, list):
            lr_pairs = lr_data

    if not lr_pairs:
        _log.warning("No L-R pairs found; skipping target_assessment.json pre-build")
        return

    # B. Build pair-level druggability_matrix
    #    Each pair uses the RECEPTOR gene's rubric scores (receptor = drug target)
    pair_matrix: list[dict[str, Any]] = []
    for pair in lr_pairs:
        ligand = pair.get("ligand", "")
        receptor = pair.get("receptor", "")
        rubric = rubric_by_gene.get(receptor, rubric_by_gene.get(ligand, {}))
        pair_matrix.append({
            "ligand": ligand,
            "receptor": receptor,
            "existing_drug_evidence": rubric.get("existing_drug_evidence", 0),
            "clinical_trial_activity": rubric.get("clinical_trial_activity", 0),
            "safety_profile": rubric.get("safety_profile", 0),
            "gwas_support": rubric.get("gwas_support", 0),
            "tractability": rubric.get("tractability", 0),
            "biological_plausibility": rubric.get("biological_plausibility", 0),
            "novelty_opportunity": rubric.get("novelty_opportunity", 0),
        })

    # C. Rank candidates and inject OpenTargets scores
    ranked_matrix = rank_featured_candidates(pair_matrix)

    # Reconcile pair-level featured/novel with gene-level stage3_candidates:
    # 1. Remove featured from pairs where NEITHER gene is a stage3_candidate
    # 2. Ensure EVERY stage3 gene has at least one pair marked is_featured
    if stage3_genes:
        s3_set = {g.upper() for g in stage3_genes}
        # Step 1: Remove non-stage3 featured
        for row in ranked_matrix:
            ligand = str(row.get("ligand", "")).strip().upper()
            receptor = str(row.get("receptor", "")).strip().upper()
            if ligand not in s3_set and receptor not in s3_set:
                row["is_featured"] = False
                row["is_novel"] = False
                row["rank"] = None
        # Step 2: Ensure all stage3 genes covered
        covered = set()
        for row in ranked_matrix:
            if not row.get("is_featured"):
                continue
            for key in ("ligand", "receptor"):
                g = str(row.get(key, "")).strip().upper()
                if g in s3_set:
                    covered.add(g)
        missing = s3_set - covered
        if missing:
            for row in ranked_matrix:
                if not missing:
                    break
                ligand = str(row.get("ligand", "")).strip().upper()
                receptor = str(row.get("receptor", "")).strip().upper()
                for g in (receptor, ligand):
                    if g in missing:
                        row["is_featured"] = True
                        missing.discard(g)
                        break

    for row in ranked_matrix:
        if "open_targets_score" in row:
            continue
        for gene_key in ("receptor", "ligand"):
            gene = str(row.get(gene_key, "")).strip().upper()
            if not gene:
                continue
            ot_file = evidence_dir / f"ot_{gene}.json"
            if ot_file.exists():
                try:
                    ot_data = json.loads(ot_file.read_text(encoding="utf-8"))
                    score = _extract_ot_disease_score(ot_data)
                    if score:
                        row["open_targets_score"] = float(score)
                        break
                except Exception:
                    continue
        if "open_targets_score" not in row:
            row["open_targets_score"] = 0.0

    # D. Build featured_candidates_deep_dive from stage3/stage1 data
    #    Both ligand and receptor may be stage3 genes (e.g., ICAM1^MUC1)
    #    so we collect ALL stage3 genes from featured pairs, then build entries.
    featured_deep_dive: list[dict[str, Any]] = []
    seen_genes: set[str] = set()
    s3_set = {g.upper() for g in (stage3_genes or [])}

    # Collect all stage3 genes that appear in any featured/novel pair
    candidate_genes: list[str] = []
    for row in ranked_matrix:
        if not (row.get("is_featured") or row.get("is_novel")):
            continue
        for key in ("receptor", "ligand"):
            g = str(row.get(key, "")).strip()
            if g and g.upper() in s3_set and g not in seen_genes:
                seen_genes.add(g)
                candidate_genes.append(g)

    for gene in candidate_genes:

        s3 = stage3_data.get(gene, {})
        # Find stage1 context for this gene
        string_score = 0.0
        kegg_pathway = ""
        for s1_val in stage1_data.values():
            if not isinstance(s1_val, dict):
                continue
            s1_lig = str(s1_val.get("ligand", "")).strip().upper()
            s1_rec = str(s1_val.get("receptor", "")).strip().upper()
            if gene.upper() not in (s1_lig, s1_rec):
                continue
            ppi = s1_val.get("string_ppi", {})
            string_score = max(string_score, ppi.get("max_combined_score", 0.0))
            kegg = s1_val.get("kegg_pathways", {})
            rec_pws = kegg.get("receptor_pathways", [])
            if rec_pws and not kegg_pathway:
                kegg_pathway = rec_pws[0] if isinstance(rec_pws[0], str) else str(rec_pws[0])

        featured_deep_dive.append({
            "target_gene": gene,
            "track": "featured" if row.get("is_featured") else "novel",
            "stage3_clinical_safety": {
                "known_drugs_drugbank": [
                    d.get("drug_name", d.get("name", ""))
                    for d in s3.get("drugs", [])
                ],
                "toxicity_admet": s3.get("safety_summary", "No safety data available"),
                "latest_pubmed_insights": (
                    ", ".join(
                        str(p.get("pmid", "")) if isinstance(p, dict) else str(p)
                        for p in s3.get("pmids", [])[:5]
                    ) or None
                ),
            },
            "stage1_biological_context": {
                "string_ppi_score": string_score,
                "primary_kegg_pathway": kegg_pathway or "No pathway data",
            },
        })

    # E. Assemble and save
    ta_payload = {
        "project_meta": {
            "disease_focus": disease_name,
            "total_input_pairs": len(lr_pairs),
        },
        "druggability_matrix": ranked_matrix,
        "featured_candidates_deep_dive": featured_deep_dive,
    }
    ta_path = data_dir_path / "target_assessment.json"
    ta_path.write_text(json.dumps(ta_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    _log.info(
        "Pre-built target_assessment.json: %d pairs, %d deep dives",
        len(ranked_matrix), len(featured_deep_dive),
    )


@tool
def build_evidence_summary(data_dir: str) -> str:
    """Build a Reference Card with exact values from all evidence files.

    Returns a structured JSON summary that report_writer MUST use as the
    single source of truth for all numeric values, PMIDs, drug names,
    classifications, and pathway names.

    ALL values in this card are authoritative — use them directly.
    Do NOT modify, round, re-derive, or invent any values.
    """
    from src.agents.drug_target.tools.evidence_loader import _resolve_data_dir  # PR2-3
    data_dir_path = _resolve_data_dir(data_dir)
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

    # build_evidence_summary feeds the report_writer Reference Card.
    # stage3_candidates is the single source of truth (post Stage 1 narrowing).
    _validated = assessment.get("stage3_candidates", [])
    stage3_genes = [g for c in _validated if (g := c.get("gene"))]

    # 2. Load stage3_*.json → drugs + PMIDs per gene
    stage3_data: dict[str, dict] = {}
    for gene in stage3_genes:
        s3_path = evidence_dir / f"stage3_{gene}.json"
        if not s3_path.exists():
            stage3_data[gene] = {"drugs": [], "pmids": [], "error": "file not found"}
            continue
        try:
            s3 = json.loads(s3_path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Corrupt stage3_%s.json: %s", gene, exc)
            stage3_data[gene] = {"drugs": [], "pmids": [], "error": f"corrupt: {exc}"}
            continue
        drugs = []
        # Try multiple keys: chembl_drugs (old format) or matched_drugs (new format)
        raw_drugs = s3.get("chembl_drugs") or s3.get("matched_drugs") or []
        # Handle nested dict format: {"executed": true, "matched_drugs": [...]}
        if isinstance(raw_drugs, dict):
            raw_drugs = raw_drugs.get("matched_drugs", [])
        if not isinstance(raw_drugs, list):
            raw_drugs = []
        for d in raw_drugs:
            if not isinstance(d, dict):
                continue
            drugs.append({
                "chembl_id": d.get("chembl_id", ""),
                "drug_name": d.get("drug_name", ""),
                "mechanism_of_action": d.get("mechanism_of_action"),
                "indications": d.get("indications", []),
                "max_phase": d.get("max_phase"),
            })
        # Load clinical drugs from OpenTargets target_drugs (ot_{gene}.json)
        clinical_drugs = []
        ot_path = evidence_dir / f"ot_{gene}.json"
        if ot_path.exists():
            try:
                ot = json.loads(ot_path.read_text())
                ot_rows = ot.get("target_drugs", {})
                if isinstance(ot_rows, dict):
                    ot_rows = ot_rows.get("rows", [])
                if not isinstance(ot_rows, list):
                    ot_rows = []
                for r in ot_rows:
                    d = r.get("drug", {})
                    chembl_id = d.get("id", "")
                    if not chembl_id:
                        continue
                    resolved = _resolve_chembl_drug(chembl_id)
                    indications = []
                    for dis in r.get("diseases", []):
                        dname = dis.get("disease", {}).get("name", "")
                        if dname:
                            indications.append(dname)
                    clinical_drugs.append({
                        "chembl_id": chembl_id,
                        "drug_name": resolved["name"],
                        "molecule_type": resolved["molecule_type"],
                        "max_phase": r.get("maxClinicalStage"),
                        "first_approval": resolved["first_approval"],
                        "indications": indications,
                        "mechanism_of_action": None,
                        "source": "opentargets",
                    })
            except Exception:
                pass

        # Check for stage3 API errors
        s3_errors = s3.get("errors", [])
        s3_executed = s3.get("executed", False)

        stage3_data[gene] = {
            "clinical_drugs": clinical_drugs,
            "preclinical_compounds": drugs,
            "drugs": clinical_drugs + drugs,  # backward compat
            "stage3_api_errors": s3_errors if s3_errors else [],
            "stage3_executed": s3_executed,
        }

    # 2b. Local-first mechanism-of-action enrichment for all drug dicts.
    # Uses data/chembl/mechanisms.parquet via the chembl-database skill.
    # Runs BEFORE featured_cards assembly so _preformat_cards picks up the
    # populated `mechanism_of_action` field. The `drugs` alias list holds the
    # same dict references as clinical_drugs + preclinical_compounds, so the
    # in-place mutations propagate through both views.
    _moa_filled = 0
    for _gene_key, _gene_data in stage3_data.items():
        _moa_filled += enrich_drugs_in_place(
            _gene_data.get("clinical_drugs", []),
            _gene_data.get("preclinical_compounds", []),
        )
    logger.info(
        "MoA enrichment: populated %d drug records across %d stage3 genes",
        _moa_filled,
        len(stage3_data),
    )

    # 3. Load stage1_*.json → per-pair biological context
    stage1_data: dict[str, dict] = {}
    for s1_path in sorted(evidence_dir.glob("stage1_*.json")):
        if s1_path.name in _STAGE1_NON_PAIR_ARTIFACTS:
            continue
        if not _is_stage1_pair_artifact(s1_path):
            logger.warning("Skipping non-pair Stage 1 artifact in reference card: %s", s1_path.name)
            continue
        try:
            s1 = json.loads(s1_path.read_text())
        except Exception:
            continue
        if not isinstance(s1, dict):
            logger.warning(
                "Skipping non-dict Stage 1 artifact payload in reference card: %s",
                s1_path.name,
            )
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

    # 5. Build all-genes druggability summary from rubric.
    # Single per-row flag: stage3_candidate reflects the post-filter narrow set
    # (rubric ∩ Stage 1 PASS). drug_report_html splits FEATURED rows on this flag.
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

    # 6. Load stage1_filter_results.csv for Biological Interaction Filter table
    import csv as _csv
    stage1_filter_results = []
    filter_csv_path = evidence_dir / "stage1_filter_results.csv"
    if filter_csv_path.exists():
        with open(filter_csv_path, encoding="utf-8") as _f:
            for row in _csv.DictReader(_f):
                stage1_filter_results.append(row)

    # 7. Load hypothesis_report.json (if hypothesis_writer completed)
    hypothesis_data = {}
    hypothesis_path = evidence_dir / "hypothesis_report.json"
    if hypothesis_path.exists():
        with open(hypothesis_path, encoding="utf-8") as _f:
            hypothesis_data = json.load(_f)

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

    # --- Fix 5: Detect stage3 API failures and build data_limitations ---
    # Must be computed BEFORE render_drug_md which uses data_limitations
    data_limitations: list[str] = []
    stage3_error_genes = [
        gene for gene in stage3_genes
        if stage3_data.get(gene, {}).get("stage3_api_errors")
        and not stage3_data.get(gene, {}).get("stage3_executed", False)
    ]
    if stage3_error_genes:
        data_limitations.append(
            f"Stage 3 ChEMBL drug profiling was unavailable for "
            f"{len(stage3_error_genes)} of {len(stage3_genes)} genes "
            f"({', '.join(stage3_error_genes)}) due to API errors. "
            f"Drug profiles shown for these genes are from OpenTargets Stage 2 data only."
        )

    # --- Fix 4: Persist resolved drug names for audit trail ---
    resolved_drugs_audit: list[dict] = []
    for gene in stage3_genes:
        gene_data = stage3_data.get(gene, {})
        for drug in gene_data.get("clinical_drugs", []):
            resolved_drugs_audit.append({
                "gene": gene,
                "chembl_id": drug.get("chembl_id", ""),
                "resolved_name": drug.get("drug_name", ""),
                "molecule_type": drug.get("molecule_type"),
                "max_phase": drug.get("max_phase"),
                "source": drug.get("source", "opentargets"),
            })
        for drug in gene_data.get("preclinical_compounds", []):
            resolved_drugs_audit.append({
                "gene": gene,
                "chembl_id": drug.get("chembl_id", ""),
                "resolved_name": drug.get("drug_name", ""),
                "molecule_type": None,
                "max_phase": drug.get("max_phase"),
                "source": "chembl",
            })
    resolved_drugs_path = evidence_dir / "resolved_drugs.json"
    resolved_drugs_path.write_text(
        json.dumps(resolved_drugs_audit, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Build pre-formatted markdown template
    disease_name = assessment.get("disease", "unknown")
    # Lazy import to avoid circular dependency:
    # stage_logic → drug_report_html → evidence_loader → stage_logic
    from src.agents.drug_target.tools.drug_report_html import render_drug_md

    md_template = render_drug_md(
        disease=disease_name,
        stage3_genes=stage3_genes,
        featured_cards=featured_cards,
        all_genes_matrix=all_genes_matrix,
        stage1_data=stage1_data,
        stage1_filter_results=stage1_filter_results,
        hypothesis_data=hypothesis_data,
        data_limitations=data_limitations,
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
        "stage1_filter_results": stage1_filter_results,
        "hypothesis_data": hypothesis_data,
        "known_drugs_disease_level": known_drugs[:20] if isinstance(known_drugs, list) else known_drugs,
        "data_limitations": data_limitations,
        "markdown_template": md_template,
    }

    # Write the template directly to drug.md as a draft
    draft_path = data_dir_path / "drug.md"
    draft_path.write_text(md_template + "\n", encoding="utf-8")

    # === Pre-build target_assessment.json ===
    _prebuild_target_assessment(
        data_dir_path, evidence_dir, disease_name,
        rubric_by_gene, stage3_data, stage1_data,
        stage3_genes,
    )

    # Return full Reference Card with inline template (no read_file needed)
    return json.dumps(reference_card, indent=2, ensure_ascii=False)




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
    from src.agents.drug_target.tools.evidence_loader import _resolve_data_dir  # PR2-3
    data_dir_path = _resolve_data_dir(data_dir)
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
    # drug.md FEATURED Deep Dive section is keyed on stage3_candidates (post Stage 1 narrowing).
    assessment_path = evidence_dir / "assessment_results.json"
    if assessment_path.exists():
        assessment = json.loads(assessment_path.read_text())
        _validated = assessment.get("stage3_candidates", [])
        stage3_genes = {c.get("gene") for c in _validated}

        for row in assessment.get("rubric_assessment", []):
            gene = row["gene"]
            if gene not in stage3_genes:
                continue
            true_class = row.get("classification", "")

            # Use word-boundary regex to avoid CD4 matching CD44/CD47
            pattern = re.compile(r'\b' + re.escape(gene) + r'\b')
            found_wrong = False

            for match in pattern.finditer(drug_text):
                if found_wrong:
                    break
                chunk = drug_text[match.end():match.end() + 500]
                if "validated_target" in chunk.lower() and true_class != "validated_target":
                    issues.append({
                        "type": "WRONG_CLASSIFICATION",
                        "severity": "high",
                        "gene": gene,
                        "claimed": "validated_target",
                        "actual": true_class,
                    })
                    found_wrong = True
                elif "novel_candidate" in chunk.lower() and true_class != "novel_candidate":
                    issues.append({
                        "type": "WRONG_CLASSIFICATION",
                        "severity": "high",
                        "gene": gene,
                        "claimed": "novel_candidate",
                        "actual": true_class,
                    })
                    found_wrong = True

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

    # 5. Drug approval year validation against resolved_drugs.json
    # P2-7: pre-init `resolved` so the variable always exists, removing the
    # fragile `'resolved' in dir()` introspection downstream.
    resolved: list = []
    resolved_drugs_path = evidence_dir / "resolved_drugs.json"
    if resolved_drugs_path.exists():
        try:
            resolved = json.loads(resolved_drugs_path.read_text())
        except Exception:
            resolved = []

        # Build name → first_approval lookup (case-insensitive)
        approval_lookup: dict[str, int | None] = {}
        for d in resolved:
            name = (d.get("resolved_name") or "").strip().upper()
            if name:
                approval_lookup[name] = d.get("first_approval")

        # Find approval year claims: "approved (YYYY)", "approved in YYYY",
        # "(YYYY)" near "approved", "FDA approved YYYY"
        year_claims = re.findall(
            r'(?:approved|approval)\s*(?:in\s*)?\(?(\d{4})\)?',
            drug_text, re.IGNORECASE
        )
        # Also match patterns like "drug_name (2018)" near "approved"
        contextual_years = re.findall(
            r'(\b[A-Z][A-Z0-9-]+\b)\s*\((?:approved\s+)?(\d{4})\)',
            drug_text
        )
        for drug_name_match, claimed_year in contextual_years:
            known_approval = approval_lookup.get(drug_name_match.upper())
            if known_approval is not None and str(known_approval) != claimed_year:
                issues.append({
                    "type": "WRONG_APPROVAL_YEAR",
                    "severity": "high",
                    "drug": drug_name_match,
                    "claimed_year": claimed_year,
                    "actual_year": known_approval,
                })

        # 6. Clinical vs Preclinical classification check
        for d in resolved:
            source = d.get("source", "")
            max_phase = d.get("max_phase")
            drug_name = (d.get("resolved_name") or "").strip()
            if not drug_name or len(drug_name) < 3:
                continue
            # Only check preclinical compounds from ChEMBL
            if source == "chembl" and max_phase in (None, "Preclinical", 0, "0"):
                drug_name_esc = re.escape(drug_name)
                pattern = re.compile(
                    drug_name_esc + r'.{0,200}(?:(?:FDA\s+)?approved|Phase\s+[1-4])',
                    re.IGNORECASE | re.DOTALL,
                )
                if pattern.search(drug_text):
                    issues.append({
                        "type": "PRECLINICAL_CALLED_APPROVED",
                        "severity": "high",
                        "drug": drug_name,
                        "actual_phase": max_phase,
                        "detail": (
                            f"'{drug_name}' is a preclinical compound (source=chembl) "
                            f"but described as approved/clinical in drug.md"
                        ),
                    })

    # 7. Hypothesis drug claims validation
    hypothesis_path = evidence_dir / "hypothesis_report.json"
    if hypothesis_path.exists() and resolved_drugs_path.exists():
        try:
            hyp = json.loads(hypothesis_path.read_text())
        except Exception:
            hyp = {}

        # Build MOA lookup from resolved drugs (P2-7: `resolved` is always defined now)
        moa_lookup: dict[str, str | None] = {}
        for d in resolved:
            name = (d.get("resolved_name") or "").strip().lower()
            if name:
                moa_lookup[name] = d.get("mechanism_of_action")

        for h in hyp.get("hypotheses", []):
            for drug_claim in h.get("biological_entities", {}).get("drugs", []):
                # Extract drug name and parenthetical mechanism
                paren_match = re.match(r'(.+?)\s*\((.+?)\)', drug_claim)
                if paren_match:
                    claim_drug = paren_match.group(1).strip().lower()
                    claim_moa = paren_match.group(2).strip().lower()
                    known_moa = moa_lookup.get(claim_drug)
                    # Flag if the drug exists in resolved but MOA doesn't match
                    if known_moa and claim_moa not in known_moa.lower():
                        issues.append({
                            "type": "HYPOTHESIS_WRONG_MOA",
                            "severity": "medium",
                            "drug": paren_match.group(1).strip(),
                            "claimed_moa": paren_match.group(2).strip(),
                            "actual_moa": known_moa,
                            "hypothesis": h.get("title", "")[:80],
                        })

    # 8. Unexpanded EXPAND placeholders — the report_writer must have
    #    replaced every `<!-- EXPAND: ... -->` marker with real narrative
    #    before saving. Leftover markers mean Phase 2 (Expand the Draft)
    #    was skipped.
    expand_markers = re.findall(r"<!--\s*EXPAND:([^>]*?)-->", drug_text)
    if expand_markers:
        preview = [m.strip()[:120] for m in expand_markers[:5]]
        issues.append({
            "type": "UNEXPANDED_PLACEHOLDER",
            "severity": "high",
            "count": len(expand_markers),
            "sample_markers": preview,
            "detail": (
                "drug.md still contains <!-- EXPAND: --> markers. Each one "
                "must be replaced with 2-4 sentences of biological "
                "interpretation (Phase 2 'Expand the Draft')."
            ),
        })

    # 9. Uncited quantitative claims — when the text makes a precise
    #    statistical claim (p-value=, OR=, HR=, logFC=) it MUST also
    #    cite an evidence file on the same line. This blocks fabricated
    #    numbers like "OpenTargets: p-value=3.2e-08, OR=2.1" that were
    #    observed in qwen3 runs and never appeared in any ot_*.json.
    #
    # The pattern is intentionally narrow to avoid false positives on
    # markdown tables and prose "A OR B" usage:
    #   - requires a key = value form where value has decimal magnitude
    #     (integer like "OR=2" is too noisy; real stats always carry a
    #     decimal or scientific notation)
    #   - skips fenced code blocks and lines that look like markdown
    #     table rows (start with "|")
    #   - skips key-only/threshold-definition lines like
    #     "p_value_threshold: 0.05" that describe cutoffs, not findings
    quant_pattern = re.compile(
        r"(?:p[-_ ]?value|pval|odds[ _-]?ratio|"
        r"(?<![A-Za-z])OR(?![A-Za-z])|"
        r"hazard[ _-]?ratio|(?<![A-Za-z])HR(?![A-Za-z])|"
        r"log\s*2?\s*fc|effect[ _-]?size)"
        r"\s*[=:<>]\s*[-+]?\d+\.\d+(?:[eE][-+]?\d+)?",
        re.IGNORECASE,
    )
    threshold_pattern = re.compile(
        r"\b(?:threshold|cutoff|limit|min|max)\b",
        re.IGNORECASE,
    )
    citation_pattern = re.compile(
        r"(?:\.json|\[from\s+[^\]]+\]|PMID[:\s]*\d|stage[123]_[A-Za-z0-9_\-]+)",
        re.IGNORECASE,
    )
    uncited_quant: list[str] = []
    in_code_fence = False
    for line in drug_text.splitlines():
        stripped = line.strip()
        # Track fenced code blocks (```...```).
        if stripped.startswith("```"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue
        # Skip markdown tables entirely — each row has its own cell
        # scoping that our regex cannot reason about cleanly.
        if stripped.startswith("|"):
            continue
        # Skip lines that are describing a threshold rather than a finding.
        if threshold_pattern.search(stripped):
            continue
        if len(stripped) < 12:
            continue
        if quant_pattern.search(stripped) and not citation_pattern.search(stripped):
            uncited_quant.append(stripped[:180])
        if len(uncited_quant) >= 10:
            break
    if uncited_quant:
        issues.append({
            "type": "UNCITED_QUANTITATIVE",
            "severity": "high",
            "count": len(uncited_quant),
            "sample_lines": uncited_quant,
            "detail": (
                "Lines contain precise statistics (p-value=, OR=, HR=, "
                "logFC=) without citing an evidence file. Every such line "
                "MUST reference either an evidence filename (e.g. "
                "stage2_evidence.json, ot_<GENE>.json) or a PMID. Uncited "
                "statistics are treated as hallucinated."
            ),
        })

    total_checks = len(doc_pmids) + 9  # PMIDs + classification + decimals + columns + approval + phase + hypothesis + expand + quant
    return json.dumps({
        "valid": len(issues) == 0,
        "total_checks": total_checks,
        "pmids_in_doc": len(doc_pmids),
        "pmids_in_evidence": len(evidence_pmids),
        "fabricated_pmid_count": len(fabricated_pmids) if fabricated_pmids else 0,
        "issue_count": len(issues),
        "issues": issues,
    }, indent=2)
