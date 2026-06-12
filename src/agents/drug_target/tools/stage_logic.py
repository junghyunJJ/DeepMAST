"""Shared stage decision logic for the drug target pipeline."""

from __future__ import annotations

import json
import logging
import math
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
from src.agents.drug_target.tools.scoring_metadata import (
    NOVELTY_OPPORTUNITY_BUCKETS,
    NOVELTY_OPPORTUNITY_LEGEND,
)
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


def _sanitize_for_strict_json(value: Any) -> Any:
    """Return a JSON-safe copy, mapping only non-finite floats to null."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, list):
        return [_sanitize_for_strict_json(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_for_strict_json(item) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize_for_strict_json(item) for key, item in value.items()}
    return value


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


def _stage1_pair_genes(pair_key: str, evidence: dict[str, Any]) -> tuple[str, str] | None:
    ligand = evidence.get("ligand")
    receptor = evidence.get("receptor")
    if ligand and receptor:
        return str(ligand).upper(), str(receptor).upper()
    parts = str(pair_key).replace("--", "^").split("^", 1)
    if len(parts) == 2 and parts[0] and parts[1]:
        return parts[0].upper(), parts[1].upper()
    return None


def _stage1_pair_passed(evidence: dict[str, Any]) -> bool:
    recorded = evidence.get("stage1_filter")
    if isinstance(recorded, dict) and "passed" in recorded:
        return bool(recorded.get("passed"))
    return bool(compute_stage1_filter(evidence).get("passed"))


def _stage1_bio_bonus_for_gene(gene: str, stage1_evidence: dict[str, Any] | None) -> int:
    gene_upper = str(gene or "").upper()
    if not gene_upper or not isinstance(stage1_evidence, dict):
        return 0
    for pair_key, evidence in stage1_evidence.items():
        if not isinstance(evidence, dict):
            continue
        pair_genes = _stage1_pair_genes(str(pair_key), evidence)
        if pair_genes is None or gene_upper not in pair_genes:
            continue
        if _stage1_pair_passed(evidence):
            return 1
    return 0



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
        item.update(compute_combined_rank_scores(vt["total"], et["scores"]))
        scored_rows.append(item)

    # Separate insufficient_evidence rows
    eligible = [r for r in scored_rows if r["classification"] != "insufficient_evidence"]
    insufficient = [r for r in scored_rows if r["classification"] == "insufficient_evidence"]

    # --- Featured pool: existing_drug_evidence >= 1 ---
    featured_pool = [
        r for r in eligible
        if _safe_track_get(r, "validated_track", "existing_drug_evidence") >= 1
    ]
    featured_pool.sort(
        key=lambda x: (
            x.get("combined_rank_score", x["combined_total"]),
            x["combined_total"],
            x.get("exploratory_rank_total", x["exploratory_total"]),
            x["exploratory_total"],
        ),
        reverse=True,
    )

    # --- Novel pool: existing_drug_evidence == 0 ---
    novel_pool = [
        r for r in eligible
        if _safe_track_get(r, "validated_track", "existing_drug_evidence") == 0
    ]
    novel_pool.sort(
        key=lambda x: (
            x.get("exploratory_rank_total", x["exploratory_total"]),
            x["exploratory_total"],
        ),
        reverse=True,
    )

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


def _rank_points_0_to_5(score: int | float, max_score: int | float) -> float:
    if not max_score:
        return 0.0
    return round((float(score or 0) / float(max_score)) * 5.0, 2)


def compute_exploratory_rank_scores(scores: dict[str, int | float]) -> dict[str, float]:
    """Normalize exploratory criteria to comparable 0-5 rank contributions."""
    gwas = _rank_points_0_to_5(scores.get("gwas_genetic_support", 0), 3)
    tract = _rank_points_0_to_5(scores.get("tractability", 0), 3)
    bio = round(float(scores.get("biological_plausibility", 0) or 0), 2)
    novelty = round(float(scores.get("novelty_opportunity", 0) or 0), 2)
    total = round(gwas + tract + bio + novelty, 2)
    return {
        "gwas_rank_points": gwas,
        "tractability_rank_points": tract,
        "biological_plausibility_rank_points": bio,
        "novelty_opportunity_rank_points": novelty,
        "exploratory_rank_total": total,
    }


def compute_combined_rank_scores(
    validated_total: int | float,
    exploratory_scores: dict[str, int | float],
) -> dict[str, float]:
    rank_scores = compute_exploratory_rank_scores(exploratory_scores)
    rank_scores["combined_rank_score"] = round(
        float(validated_total or 0) + rank_scores["exploratory_rank_total"],
        2,
    )
    return rank_scores


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
    # intersection of (rubric >=10) AND (Stage 1 strict PASS). Both
    # evidence_assessor's Stage 3 loop and hypothesis_writer consume the same narrowed list.
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
                "safety_profile", "safety_evidence_level", "safety_liability_count",
                "safety_liability_sources", "validated_total",
                "gwas_support", "gwas_evidence_type", "gwas_min_pvalue",
                "gwas_trait_match_level", "gwas_direct_hit_count",
                "gwas_proximity_hit_count", "tractability",
                "tractability_basis", "tractability_modalities",
                "tractability_evidence_label",
                "biological_plausibility_base", "stage1_biological_support_bonus",
                "biological_basis", "biological_evidence_types",
                "biological_evidence_count", "biological_max_ot_score",
                "vep_high_impact_count", "stage1_support_pair_count",
                "stage1_support_pairs",
                "stage1_gate_status", "stage1_total_pair_count",
                "stage1_passed_pair_count", "stage1_failed_pair_count",
                "stage1_best_pair", "stage1_best_string_combined",
                "stage1_best_coexpr_pvalue", "stage1_best_gene_a_pvalue",
                "stage1_best_gene_b_pvalue", "stage1_source",
                "biological_plausibility",
                "novelty_opportunity", "novelty_basis", "novelty_association_count",
                "novelty_target_drug_count", "novelty_bucket",
                "novelty_source", "exploratory_total", "combined_total",
                "gwas_rank_points", "tractability_rank_points",
                "biological_plausibility_rank_points", "novelty_opportunity_rank_points",
                "exploratory_rank_total", "combined_rank_score",
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


def _tractability_bucket_label(entry: dict[str, Any]) -> str:
    """Return normalized OpenTargets tractability bucket label across payload shapes."""
    raw = entry.get("id") or entry.get("top_category") or entry.get("label") or ""
    return re.sub(r"\s+", " ", str(raw)).strip().casefold()


def _check_opentargets_approved(
    tractability: list[dict] | None,
) -> bool:
    """Check if OpenTargets tractability contains an approved drug."""
    if not tractability:
        return False
    for entry in tractability:
        if isinstance(entry, dict):
            if _tractability_bucket_label(entry) == "approved drug" and entry.get("value") is True:
                return True
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


def _safety_study_type_has_prefix(study_type: str, prefix: str) -> bool:
    return study_type == prefix or any(
        study_type.startswith(f"{prefix}{separator}")
        for separator in (" ", "_", "-", "/", ":")
    )


def _classify_safety_liability(entry: Any) -> str | None:
    """Classify one OT safety liability as clinical or preclinical."""
    if not isinstance(entry, dict):
        return None

    src = str(entry.get("datasource") or "").lower().strip()
    studies = entry.get("studies") or []
    study_types = [
        str(study.get("type") or "").lower().strip()
        for study in studies
        if isinstance(study, dict)
    ]

    has_clinical_study = any(
        _safety_study_type_has_prefix(study_type, "clinical")
        for study_type in study_types
    )
    if src == "pharmgkb" or has_clinical_study:
        return "clinical"

    return "preclinical"


def _score_safety_profile(safety_liabilities: list | None) -> int:
    """Score safety_profile (-3 to 0) from OT safetyLiabilities.

    Distinguishes clinical evidence (PharmGKB, Brennan et al.) from
    preclinical screens (ToxCast, AOP-Wiki) per OT community guidance.

     0: no safety concerns or fewer than 3 preclinical concerns
    -1: preclinical concerns only (ToxCast/AOP-Wiki 3+)
    -2: clinical concerns (PharmGKB/clinical 1-2)
    -3: major clinical concerns (PharmGKB/clinical 3+)
    """
    if not safety_liabilities:
        return 0
    clinical_count = 0
    preclinical_count = 0
    for entry in safety_liabilities:
        classification = _classify_safety_liability(entry)
        if classification == "clinical":
            clinical_count += 1
        elif classification == "preclinical":
            preclinical_count += 1
    if clinical_count >= 3:
        return -3
    if clinical_count >= 1:
        return -2
    if preclinical_count >= 3:
        return -1
    return 0


def _summarize_safety(safety_liabilities: list | None) -> dict[str, Any]:
    """Return non-scoring safety audit metadata."""
    if not safety_liabilities:
        return {
            "safety_evidence_level": "no_known_liability",
            "safety_liability_count": 0,
            "safety_liability_sources": "",
        }

    clinical_count = 0
    preclinical_count = 0
    sources: set[str] = set()
    for entry in safety_liabilities:
        if not isinstance(entry, dict):
            continue
        src = str(entry.get("datasource") or "unknown").lower().strip()
        sources.add(src)
        classification = _classify_safety_liability(entry)
        if classification == "clinical":
            clinical_count += 1
        elif classification == "preclinical":
            preclinical_count += 1

    if clinical_count >= 3:
        level = "major_clinical_liability"
    elif clinical_count >= 1:
        level = "clinical_liability"
    elif preclinical_count >= 3:
        level = "preclinical_liability"
    elif preclinical_count >= 1:
        level = "low_preclinical_signal"
    else:
        level = "no_known_liability"

    return {
        "safety_evidence_level": level,
        "safety_liability_count": clinical_count + preclinical_count,
        "safety_liability_sources": ";".join(sorted(sources)),
    }


def _min_pval_from_gene_snps(gene_snps: list[dict]) -> float:
    """Extract minimum p-value from gene_snps_in_disease entries."""
    min_pval = 1.0
    for snp in gene_snps:
        if not isinstance(snp, dict):
            continue
        for key in ("pvalue", "p_value", "p-value"):
            pval = snp.get(key)
            if pval is not None:
                try:
                    min_pval = min(min_pval, float(pval))
                except (ValueError, TypeError):
                    pass
        associations = snp.get("associations", [])
        if isinstance(associations, dict):
            nested_associations = [associations]
        elif isinstance(associations, list):
            nested_associations = associations
        else:
            nested_associations = []
        for nested in nested_associations:
            if not isinstance(nested, dict):
                continue
            for key in ("pvalue", "p_value"):
                pval = nested.get(key)
                if pval is not None:
                    try:
                        min_pval = min(min_pval, float(pval))
                    except (ValueError, TypeError):
                        pass
    return min_pval


def _min_pval_from_hits(hits: list[dict]) -> float:
    """Extract minimum p-value from flat or nested GWAS hit entries."""
    min_pval = 1.0
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        for key in ("pvalue", "p_value", "p-value", "p"):
            pval = hit.get(key)
            if pval is not None:
                try:
                    min_pval = min(min_pval, float(pval))
                except (ValueError, TypeError):
                    pass
        nested_hits = []
        for nested_key in ("associations", "association", "traits"):
            nested = hit.get(nested_key)
            if isinstance(nested, list):
                nested_hits.extend(n for n in nested if isinstance(n, dict))
            elif isinstance(nested, dict):
                nested_hits.append(nested)
        if nested_hits:
            min_pval = min(min_pval, _min_pval_from_hits(nested_hits))
    return min_pval


def _normalize_trait_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _trait_is_disease_specific(trait: Any, disease: Any) -> bool:
    trait_text = _normalize_trait_text(trait)
    disease_text = _normalize_trait_text(disease)
    if not trait_text:
        return False
    if "pleiotropy" in trait_text or " or " in f" {trait_text} ":
        return False
    if disease_text and disease_text in trait_text:
        return True
    disease_terms = [term for term in disease_text.split() if len(term) >= 4]
    return bool(disease_terms) and all(term in trait_text for term in disease_terms)


def _hit_trait_values(hit: dict[str, Any]) -> list[Any]:
    values: list[Any] = []
    for key in (
        "trait",
        "disease",
        "mapped_trait",
        "mappedTrait",
        "reported_trait",
        "reportedTrait",
        "efo_trait",
        "efoTrait",
    ):
        value = hit.get(key)
        if isinstance(value, list):
            values.extend(value)
        elif value:
            values.append(value)
    for nested_key in ("associations", "association", "traits"):
        nested = hit.get(nested_key)
        if isinstance(nested, list):
            for item in nested:
                if isinstance(item, dict):
                    values.extend(_hit_trait_values(item))
                elif item:
                    values.append(item)
        elif isinstance(nested, dict):
            values.extend(_hit_trait_values(nested))
    return values


def _hit_has_local_pvalue(hit: dict[str, Any], threshold: float = 5e-8) -> bool:
    for key in ("pvalue", "p_value", "p-value", "p"):
        pval = hit.get(key)
        if pval is None:
            continue
        try:
            if float(pval) < threshold:
                return True
        except (ValueError, TypeError):
            pass
    return False


def _hit_has_disease_specific_significant_trait(hit: dict[str, Any], disease: Any) -> bool:
    has_local_trait = any(
        _trait_is_disease_specific(trait, disease)
        for trait in _hit_trait_values({k: v for k, v in hit.items() if k not in {"associations", "association", "traits"}})
    )
    if has_local_trait and _hit_has_local_pvalue(hit):
        return True
    for nested_key in ("associations", "association", "traits"):
        nested = hit.get(nested_key)
        if isinstance(nested, list):
            if any(
                isinstance(item, dict) and _hit_has_disease_specific_significant_trait(item, disease)
                for item in nested
            ):
                return True
        elif isinstance(nested, dict) and _hit_has_disease_specific_significant_trait(nested, disease):
            return True
    return False


def _has_significant_disease_specific_proximity(dsh: dict[str, Any], disease: Any) -> bool:
    hits = dsh.get("proximity_hits", [])
    if not isinstance(hits, list):
        return False
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        if _hit_has_disease_specific_significant_trait(hit, disease):
            return True
    return False


def _gwas_count(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _gwas_min_pvalue(*values: float) -> float | None:
    valid = [value for value in values if value < 1.0]
    return min(valid) if valid else None


def _hit_has_pleiotropic_trait(hit: dict[str, Any]) -> bool:
    for trait in _hit_trait_values(hit):
        trait_text = _normalize_trait_text(trait)
        if "pleiotropy" in trait_text or " or " in f" {trait_text} ":
            return True
    return False


def _summarize_gwas_support(gwas_data: dict | None) -> dict[str, Any]:
    """Return non-scoring GWAS audit metadata."""
    default = {
        "gwas_evidence_type": "none",
        "gwas_min_pvalue": None,
        "gwas_trait_match_level": "none",
        "gwas_direct_hit_count": 0,
        "gwas_proximity_hit_count": 0,
    }
    if not gwas_data:
        return default

    dsh = gwas_data.get("disease_specific_hits", {})
    if not isinstance(dsh, dict):
        return default

    n_gene_in_trait = _gwas_count(dsh.get("n_gene_in_trait", 0))
    n_gene_snps = _gwas_count(dsh.get("n_gene_snps_in_disease", 0))
    n_proximity = _gwas_count(dsh.get("n_proximity_hits", 0))
    direct_count = n_gene_in_trait + n_gene_snps

    gene_snps = dsh.get("gene_snps_in_disease", [])
    if not isinstance(gene_snps, list):
        gene_snps = []
    proximity_hits = dsh.get("proximity_hits", [])
    if not isinstance(proximity_hits, list):
        proximity_hits = []

    direct_min_pvalue = _min_pval_from_gene_snps(gene_snps) if n_gene_snps > 0 else 1.0
    proximity_min_pvalue = _min_pval_from_hits(proximity_hits) if n_proximity > 0 else 1.0
    min_pvalue = _gwas_min_pvalue(direct_min_pvalue, proximity_min_pvalue)
    disease = gwas_data.get("disease") or gwas_data.get("disease_name") or dsh.get("disease")

    summary = {
        **default,
        "gwas_min_pvalue": min_pvalue,
        "gwas_direct_hit_count": direct_count,
        "gwas_proximity_hit_count": n_proximity,
    }

    if n_gene_snps > 0 and direct_min_pvalue < 5e-8:
        summary.update({
            "gwas_evidence_type": "direct_significant_overlap",
            "gwas_trait_match_level": "disease_specific",
        })
    elif direct_count > 0:
        summary.update({
            "gwas_evidence_type": "direct_disease_link",
            "gwas_trait_match_level": "disease_specific",
        })
    elif n_proximity > 0 and _has_significant_disease_specific_proximity(dsh, disease):
        summary.update({
            "gwas_evidence_type": "disease_specific_proximity",
            "gwas_trait_match_level": "disease_specific",
        })
    elif n_proximity > 0:
        is_pleiotropic = any(
            isinstance(hit, dict) and _hit_has_pleiotropic_trait(hit)
            for hit in proximity_hits
        )
        summary.update({
            "gwas_evidence_type": "pleiotropic_proximity" if is_pleiotropic else "proximity",
            "gwas_trait_match_level": "pleiotropic" if is_pleiotropic else "unknown",
        })

    return summary


def _score_gwas_support(gwas_data: dict | None) -> int:
    """Score gwas_support (0-3) from disease-specific GWAS hits only.

    Uses disease_specific_hits (computed by stage2_service) as the sole
    signal.  gene_associations without disease overlap score 0.

    Score 3: gene_snps_in_disease with p < 5e-8 (genome-wide significant overlap)
    Score 2: gene_in_trait OR gene_snps_in_disease (any p-value), or
             disease-specific genome-wide significant proximity hit
    Score 1: proximity_hits only (±500kb), including pleiotropic proximity
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

    # Score 2: significant disease-specific proximity only
    if n_proximity > 0 and _has_significant_disease_specific_proximity(
        dsh,
        gwas_data.get("disease") or gwas_data.get("disease_name") or dsh.get("disease"),
    ):
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
        label = _tractability_bucket_label(entry)
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


_TRACTABILITY_AUDIT_PRIORITY: tuple[tuple[str, str], ...] = (
    ("approved drug", "approved_drug"),
    ("advanced clinical", "clinical_precedent"),
    ("phase 1 clinical", "clinical_precedent"),
    ("structure with ligand", "ligand_or_structure"),
    ("high-quality ligand", "ligand_or_structure"),
    ("druggable family", "druggable_family"),
)


def _summarize_tractability(tractability: list[dict] | None) -> dict[str, Any]:
    """Return non-scoring tractability audit metadata."""
    if not tractability:
        return {
            "tractability_basis": "unknown",
            "tractability_modalities": "",
            "tractability_evidence_label": "none",
        }

    positive_entries: list[tuple[str, str]] = []
    modalities: set[str] = set()
    for entry in tractability:
        if not isinstance(entry, dict):
            continue
        label = _tractability_bucket_label(entry)
        value = entry.get("value", False)
        if value is not True:
            continue
        modality = str(entry.get("modality") or "").upper().strip()
        if modality:
            modalities.add(modality)
        positive_entries.append((label, modality))

    if not positive_entries:
        return {
            "tractability_basis": "unknown",
            "tractability_modalities": "",
            "tractability_evidence_label": "none",
        }

    for label, basis in _TRACTABILITY_AUDIT_PRIORITY:
        if any(entry_label == label for entry_label, _mod in positive_entries):
            return {
                "tractability_basis": basis,
                "tractability_modalities": ";".join(sorted(modalities)),
                "tractability_evidence_label": label,
            }

    return {
        "tractability_basis": "other_signal",
        "tractability_modalities": ";".join(sorted(modalities)),
        "tractability_evidence_label": positive_entries[0][0] or "other",
    }


def _safe_nonnegative_int(value: Any, default: int = 0) -> int:
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    try:
        return max(0, int(value or default))
    except (TypeError, ValueError):
        return default


def _safe_float_score(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _biological_evidence_entries(disease_evidence: list | None) -> list[dict[str, Any]]:
    if not isinstance(disease_evidence, list):
        return []
    return [
        entry for entry in disease_evidence
        if isinstance(entry, dict) and entry.get("datatypeId") in _BIO_PLAUSIBILITY_TYPES
    ]


def _vep_high_impact_count(vep_data: dict | None) -> int:
    if not isinstance(vep_data, dict) or not vep_data.get("executed"):
        return 0
    impact_summary = vep_data.get("impact_summary", {})
    if not isinstance(impact_summary, dict):
        return 0
    return _safe_nonnegative_int(impact_summary.get("high_impact", 0))


def _stage1_pair_passed_for_biological_audit(evidence: dict[str, Any]) -> bool:
    recorded = evidence.get("stage1_filter")
    if isinstance(recorded, dict) and "passed" in recorded:
        return recorded.get("passed") is True
    try:
        return _stage1_pair_passed(evidence)
    except Exception as exc:
        logger.warning("Skipping malformed Stage1 evidence in biological audit: %s", exc)
        return False


def _stage1_bio_support_pairs_for_gene(
    gene: str,
    stage1_evidence: dict[str, Any] | None,
) -> list[str]:
    gene_upper = str(gene or "").upper()
    if not gene_upper or not isinstance(stage1_evidence, dict):
        return []
    pairs: set[str] = set()
    for pair_key, evidence in stage1_evidence.items():
        if not isinstance(evidence, dict):
            continue
        pair_genes = _stage1_pair_genes(str(pair_key), evidence)
        if pair_genes is None or gene_upper not in pair_genes:
            continue
        if _stage1_pair_passed_for_biological_audit(evidence):
            pairs.add(f"{pair_genes[0]}^{pair_genes[1]}")
    return sorted(pairs)


def _stage1_audit_defaults() -> dict[str, Any]:
    return {
        "stage1_gate_status": "not_evaluated",
        "stage1_total_pair_count": 0,
        "stage1_passed_pair_count": 0,
        "stage1_failed_pair_count": 0,
        "stage1_best_pair": "",
        "stage1_best_string_combined": None,
        "stage1_best_coexpr_pvalue": None,
        "stage1_best_gene_a_pvalue": None,
        "stage1_best_gene_b_pvalue": None,
        "stage1_source": "none",
    }


def _stage1_audit_metadata_from_row(row: dict[str, Any]) -> dict[str, Any]:
    defaults = _stage1_audit_defaults()
    return {key: row.get(key, default) for key, default in defaults.items()}


def _target_assessment_audit_metadata_from_rubric(rubric: dict[str, Any]) -> dict[str, Any]:
    """Copy gene-level audit metadata onto pair-level target-assessment rows."""
    return {
        "gwas_evidence_type": rubric.get("gwas_evidence_type", "none"),
        "gwas_min_pvalue": rubric.get("gwas_min_pvalue"),
        "gwas_trait_match_level": rubric.get("gwas_trait_match_level", "none"),
        "gwas_direct_hit_count": rubric.get("gwas_direct_hit_count", 0),
        "gwas_proximity_hit_count": rubric.get("gwas_proximity_hit_count", 0),
        "tractability_basis": rubric.get("tractability_basis", "unknown"),
        "tractability_modalities": rubric.get("tractability_modalities", ""),
        "tractability_evidence_label": rubric.get("tractability_evidence_label", "none"),
        "safety_evidence_level": rubric.get("safety_evidence_level", "no_known_liability"),
        "safety_liability_count": rubric.get("safety_liability_count", 0),
        "safety_liability_sources": rubric.get("safety_liability_sources", ""),
        "biological_plausibility_base": rubric.get("biological_plausibility_base", 0),
        "stage1_biological_support_bonus": rubric.get("stage1_biological_support_bonus", 0),
        "biological_basis": rubric.get("biological_basis", "none"),
        "biological_evidence_types": rubric.get("biological_evidence_types", ""),
        "biological_evidence_count": rubric.get("biological_evidence_count", 0),
        "biological_max_ot_score": rubric.get("biological_max_ot_score"),
        "vep_high_impact_count": rubric.get("vep_high_impact_count", 0),
        "stage1_support_pair_count": rubric.get("stage1_support_pair_count", 0),
        "stage1_support_pairs": rubric.get("stage1_support_pairs", ""),
        **_stage1_audit_metadata_from_row(rubric),
        "novelty_basis": rubric.get("novelty_basis", "st_only_or_brand_new_target"),
        "novelty_association_count": rubric.get("novelty_association_count", 0),
        "novelty_target_drug_count": rubric.get("novelty_target_drug_count", 0),
        "novelty_bucket": rubric.get("novelty_bucket", "0-9 associations"),
        "novelty_source": rubric.get("novelty_source", "list_length"),
    }


def _stage1_filter_for_audit(evidence: dict[str, Any]) -> dict[str, Any]:
    try:
        computed = compute_stage1_filter(evidence)
    except Exception as exc:
        logger.warning("Using failed Stage1 audit defaults for malformed evidence: %s", exc)
        return {
            "passed": False,
            "string_combined": 0.0,
            "string_status": "malformed",
            "census_coexpr_pvalue": 1.0,
            "census_gene_a_pvalue": 1.0,
            "census_gene_b_pvalue": 1.0,
        }

    recorded = evidence.get("stage1_filter")
    if isinstance(recorded, dict) and type(recorded.get("passed")) is bool:
        computed["passed"] = recorded["passed"]
    return computed


def _summarize_stage1_gate(
    gene: str,
    stage1_evidence: dict[str, Any] | None,
) -> dict[str, Any]:
    gene_upper = str(gene or "").upper()
    if not gene_upper or not isinstance(stage1_evidence, dict):
        return _stage1_audit_defaults()

    rows: list[dict[str, Any]] = []
    for pair_key, evidence in stage1_evidence.items():
        if not isinstance(evidence, dict):
            continue
        pair_genes = _stage1_pair_genes(str(pair_key), evidence)
        if pair_genes is None or gene_upper not in pair_genes:
            continue

        filt = _stage1_filter_for_audit(evidence)
        if not filt:
            continue
        rows.append({
            "pair": f"{pair_genes[0]}^{pair_genes[1]}",
            "passed": filt.get("passed") is True,
            "string_combined": _safe_float_score(filt.get("string_combined")),
            "coexpr_pvalue": _safe_float_score(filt.get("census_coexpr_pvalue")),
            "gene_a_pvalue": _safe_float_score(filt.get("census_gene_a_pvalue")),
            "gene_b_pvalue": _safe_float_score(filt.get("census_gene_b_pvalue")),
        })

    if not rows:
        return _stage1_audit_defaults()

    rows.sort(
        key=lambda row: (
            not row["passed"],
            -row["string_combined"],
            row["coexpr_pvalue"],
            str(row["pair"]),
        )
    )
    best = rows[0]
    passed_count = sum(1 for row in rows if row["passed"])
    total_count = len(rows)
    return {
        "stage1_gate_status": "pass" if passed_count else "fail",
        "stage1_total_pair_count": total_count,
        "stage1_passed_pair_count": passed_count,
        "stage1_failed_pair_count": total_count - passed_count,
        "stage1_best_pair": best["pair"],
        "stage1_best_string_combined": best["string_combined"],
        "stage1_best_coexpr_pvalue": best["coexpr_pvalue"],
        "stage1_best_gene_a_pvalue": best["gene_a_pvalue"],
        "stage1_best_gene_b_pvalue": best["gene_b_pvalue"],
        "stage1_source": "stage1_evidence.json",
    }


def _biological_basis(
    biological_evidence_count: int,
    vep_high_impact_count: int,
    stage1_pair_count: int,
) -> str:
    sources: list[str] = []
    if biological_evidence_count > 0:
        sources.append("ot_evidence")
    if vep_high_impact_count > 0:
        sources.append("vep_high_impact")
    if stage1_pair_count > 0:
        sources.append("stage1_pair")
    return "_plus_".join(sources) if sources else "none"


def _summarize_biological_plausibility(
    disease_evidence: list | None,
    vep_data: dict | None,
    gene: str,
    stage1_evidence: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return non-scoring biological plausibility audit metadata."""
    entries = _biological_evidence_entries(disease_evidence)
    evidence_types = sorted({
        str(entry.get("datatypeId"))
        for entry in entries
        if entry.get("datatypeId")
    })
    max_score = max(
        (_safe_float_score(entry.get("score")) for entry in entries),
        default=None,
    )
    high_impact_count = _vep_high_impact_count(vep_data)
    stage1_pairs = _stage1_bio_support_pairs_for_gene(gene, stage1_evidence)

    return {
        "biological_basis": _biological_basis(
            len(entries),
            high_impact_count,
            len(stage1_pairs),
        ),
        "biological_evidence_types": ";".join(evidence_types),
        "biological_evidence_count": len(entries),
        "biological_max_ot_score": max_score,
        "vep_high_impact_count": high_impact_count,
        "stage1_support_pair_count": len(stage1_pairs),
        "stage1_support_pairs": ";".join(stage1_pairs),
    }


def _score_biological_plausibility(
    disease_evidence: list[dict],
    vep_data: dict | None = None,
    stage1_support_bonus: int = 0,
) -> int:
    """Score biological_plausibility (0-5) via breadth-weighted evidence.

    Filters disease_evidence to datatypeIds NOT already scored by other
    criteria (excludes known_drug, genetic_association). Rewards evidence
    breadth, high-confidence OpenTargets evidence, VEP high-impact variants,
    and one bounded Stage1/Census biological support bonus.

    Score = min(5, n_types + max_score_bonus + stage1_support_bonus)
      - n_types:         count of distinct qualifying datatypeId present (0-4)
      - max_score_bonus: +1 if max(filtered scores) >= 0.7
      - stage1_support_bonus: +1 when the gene appears in a Stage1-passed L-R pair

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
    if stage1_support_bonus > 0:
        score = min(score + 1, 5)
    return score


def _score_novelty_opportunity(associations: list[dict],
                                associations_truncated: bool = False,
                                associations_total_count: int | None = None) -> int:
    """Score novelty_opportunity (0-5) inverse of how well-established the target is.

    Bracket schema tuned for well-studied gene panels (CCI-derived L-R
    receptors routinely have 300-3000 OpenTargets disease associations).
    A live probe against res_ipf_qwen2's 41 genes on 2026-04-20 measured
    the true API count for each — the new brackets produce
    14 / 22 / 5 / 0 / 0 / 0 distribution across 0..5, whereas the legacy
    0-30 schema collapsed every gene into bucket 0 once the true count
    was wired through.

    0: 1000+ associations (well-studied, e.g. TGFB1=3124, CD4=2905)
    1: 300-999  associations (moderately studied, e.g. LRP1=781, CD74=967)
    2: 100-299  associations (emerging, e.g. ITGA3=262, HLA-DMA=232)
    3: 30-99    associations
    4: 10-29    associations
    5: 0-9      associations (ST-only discovery or brand-new target)

    Prefers ``associations_total_count`` (persisted before truncation) over
    ``len(associations)``. When the total is unavailable and
    ``associations_truncated=True``, cap novelty at 1 (500+ floor via page-size).
    """
    if associations_total_count is not None:
        count = int(associations_total_count)
    else:
        count = len(associations) if associations else 0
    score = next(
        int(bucket["score"])
        for bucket in NOVELTY_OPPORTUNITY_BUCKETS
        if count >= int(bucket["min_count"])
    )
    # When the true total is unknown and the list is truncated, at least
    # page_size (500 post-A0) associations exist → floor novelty at 1.
    # Skip this cap when the caller passed the authoritative
    # ``associations_total_count``.
    if associations_total_count is None and associations_truncated and score > 1:
        score = 1
    return score


_NOVELTY_BASIS_BY_SCORE = {
    0: "well_studied_target",
    1: "moderately_studied_target",
    2: "emerging_target",
    3: "less_explored_target",
    4: "sparsely_explored_target",
    5: "st_only_or_brand_new_target",
}


def _novelty_bucket_for_count(count: int) -> dict[str, Any]:
    for bucket in NOVELTY_OPPORTUNITY_BUCKETS:
        if count >= int(bucket["min_count"]):
            return bucket
    return NOVELTY_OPPORTUNITY_BUCKETS[-1]


def _target_drug_count_for_novelty_audit(target_drugs: Any) -> int:
    if not isinstance(target_drugs, dict):
        return 0
    count = _safe_nonnegative_int(target_drugs.get("count"), default=-1)
    if count >= 0:
        return count
    rows = target_drugs.get("rows")
    return len(rows) if isinstance(rows, list) else 0


def _summarize_novelty_opportunity(
    associations: list[dict] | None,
    associations_truncated: bool = False,
    associations_total_count: Any = None,
    associations_total_source: Any = None,
    target_drugs: Any = None,
) -> dict[str, Any]:
    """Summarize audit-only metadata behind novelty_opportunity scoring."""
    observed_count = len(associations) if isinstance(associations, list) else 0
    authoritative_count = _safe_nonnegative_int(
        associations_total_count,
        default=-1,
    )

    if authoritative_count >= 0:
        count = authoritative_count
        source = str(associations_total_source or "associations_total_count").strip()
        source = source or "associations_total_count"
        bucket = _novelty_bucket_for_count(count)
        score = int(bucket["score"])
        basis = _NOVELTY_BASIS_BY_SCORE[score]
        bucket_label = str(bucket["label"])
    elif associations_truncated:
        count = observed_count
        source = "truncated_list_length"
        basis = "total_unknown_truncated"
        bucket_label = "truncated_total_unknown"
    else:
        count = observed_count
        source = "list_length"
        bucket = _novelty_bucket_for_count(count)
        score = int(bucket["score"])
        basis = _NOVELTY_BASIS_BY_SCORE[score]
        bucket_label = str(bucket["label"])

    return {
        "novelty_basis": basis,
        "novelty_association_count": count,
        "novelty_target_drug_count": _target_drug_count_for_novelty_audit(target_drugs),
        "novelty_bucket": bucket_label,
        "novelty_source": source,
    }


def _ot_safety_summary(evidence_dir: Path, gene: str) -> str | None:
    """Summarize OpenTargets `target_info.safetyLiabilities` for a gene.

    Stage 3 (ChEMBL) rarely populates `safety_summary`, but the OT JSON
    already contains curated safety events (ToxCast, AOP-Wiki, clinical
    safety). Surface them so `toxicity_admet` isn't a silent
    "No safety data available" when evidence is available.
    Returns None when no signal exists.
    """
    ot_file = evidence_dir / f"ot_{gene}.json"
    if not ot_file.exists():
        return None
    try:
        data = json.loads(ot_file.read_text(encoding="utf-8"))
    except Exception:
        return None
    safety = ((data.get("target_info") or {}).get("safetyLiabilities") or [])
    if not isinstance(safety, list) or not safety:
        return None
    parts: list[str] = []
    for s in safety[:3]:
        if not isinstance(s, dict):
            continue
        event = str(s.get("event") or "").strip()
        ds = str(s.get("datasource") or "").strip()
        effects = s.get("effects")
        effect_str = ""
        if isinstance(effects, list) and effects:
            # Each effect entry has `direction` and `dosing` in OT schema.
            first = effects[0]
            if isinstance(first, dict):
                d = first.get("direction") or ""
                if d:
                    effect_str = f", {d}"
        if event:
            parts.append(f"{event} ({ds}{effect_str})" if ds else event)
    return "; ".join(parts) if parts else None


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

    stage1_path = evidence_dir / "stage1_evidence.json"
    stage1_evidence: dict[str, Any] = {}
    if stage1_path.exists():
        stage1_evidence = json.loads(stage1_path.read_text(encoding="utf-8"))

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
        gwas_summary = _summarize_gwas_support(gwas_data)
        tract = _score_tractability(tractability_data)
        tractability_summary = _summarize_tractability(tractability_data)
        safety_summary = _summarize_safety(safety_data)
        bio_plaus_base = _score_biological_plausibility(disease_evidence, vep_data)
        stage1_bio_bonus = _stage1_bio_bonus_for_gene(gene, stage1_evidence)
        biological_summary = _summarize_biological_plausibility(
            disease_evidence,
            vep_data,
            gene,
            stage1_evidence,
        )
        stage1_summary = _summarize_stage1_gate(gene, stage1_evidence)
        bio_plaus = _score_biological_plausibility(
            disease_evidence,
            vep_data,
            stage1_support_bonus=stage1_bio_bonus,
        )
        novelty = _score_novelty_opportunity(
            associations,
            ot.get("associations_truncated", False),
            ot.get("associations_total_count"),
        )
        novelty_summary = _summarize_novelty_opportunity(
            associations,
            ot.get("associations_truncated", False),
            ot.get("associations_total_count"),
            ot.get("associations_total_source"),
            target_drugs,
        )

        validated_total = existing_drug + clinical_trial + safety
        exploratory_total = gwas + tract + bio_plaus + novelty
        combined_total = validated_total + exploratory_total
        rank_scores = compute_combined_rank_scores(
            validated_total,
            {
                "gwas_genetic_support": gwas,
                "tractability": tract,
                "biological_plausibility": bio_plaus,
                "novelty_opportunity": novelty,
            },
        )

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
            **safety_summary,
            "validated_total": validated_total,
            "gwas_support": gwas,
            **gwas_summary,
            "tractability": tract,
            **tractability_summary,
            "biological_plausibility_base": bio_plaus_base,
            "stage1_biological_support_bonus": stage1_bio_bonus,
            **biological_summary,
            **stage1_summary,
            "biological_plausibility": bio_plaus,
            "novelty_opportunity": novelty,
            **novelty_summary,
            "exploratory_total": exploratory_total,
            "combined_total": combined_total,
            **rank_scores,
            "classification": classification,
            "priority": priority,
            "ot_disease_evidence_count": len(disease_evidence),
            "ot_associations_count": len(associations),
        }
        results.append(row)

    # Sort by normalized rank score; keep raw combined_total for Stage 3 thresholding.
    results.sort(
        key=lambda r: (
            r["combined_rank_score"],
            r["combined_total"],
            r["exploratory_rank_total"],
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
    # later overwrites it in place with the (rubric ∩ Stage 1 PASS) intersection so
    # evidence_assessor (Stage 3) and hypothesis_writer consume the same narrowed list.
    assessment = {
        "schema_version": 3,
        "assessment_date": datetime.now().isoformat(),
        "disease": stage2.get("_disease", "unknown") if isinstance(stage2, dict) else "unknown",
        "disease_context": stage2.get("_disease_context", {}) if isinstance(stage2, dict) else {},
        "rubric_assessment": results,
        "all_genes_matrix": results,
        "stage3_candidates": [
            {"gene": r["gene"], "exploratory_total": r["exploratory_total"],
             "combined_total": r["combined_total"],
             "exploratory_rank_total": r["exploratory_rank_total"],
             "combined_rank_score": r["combined_rank_score"],
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
        "safety_profile", "safety_evidence_level", "safety_liability_count",
        "safety_liability_sources", "validated_total",
        "gwas_support", "gwas_evidence_type", "gwas_min_pvalue",
        "gwas_trait_match_level", "gwas_direct_hit_count",
        "gwas_proximity_hit_count", "tractability",
        "tractability_basis", "tractability_modalities",
        "tractability_evidence_label",
        "biological_plausibility_base", "stage1_biological_support_bonus",
        "biological_basis", "biological_evidence_types",
        "biological_evidence_count", "biological_max_ot_score",
        "vep_high_impact_count", "stage1_support_pair_count",
        "stage1_support_pairs",
        "stage1_gate_status", "stage1_total_pair_count",
        "stage1_passed_pair_count", "stage1_failed_pair_count",
        "stage1_best_pair", "stage1_best_string_combined",
        "stage1_best_coexpr_pvalue", "stage1_best_gene_a_pvalue",
        "stage1_best_gene_b_pvalue", "stage1_source",
        "biological_plausibility",
        "novelty_opportunity", "novelty_basis", "novelty_association_count",
        "novelty_target_drug_count", "novelty_bucket",
        "novelty_source", "exploratory_total", "combined_total",
        "gwas_rank_points", "tractability_rank_points",
        "biological_plausibility_rank_points", "novelty_opportunity_rank_points",
        "exploratory_rank_total", "combined_rank_score",
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
            {
                "gene": r["gene"],
                "exploratory": r["exploratory_total"],
                "combined": r["combined_total"],
                "combined_rank_score": r["combined_rank_score"],
            }
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

    Returns success=true only when ALL expected files are present and no
    completed profile contains query/API errors.
    Call this after Stage 3 completes to verify no genes were skipped.
    If ``success`` is false, complete Stage 3 for the ``missing_genes`` or
    retry genes listed in ``genes_with_errors`` first, then re-call.
    """
    from src.agents.drug_target.tools.evidence_loader import _resolve_data_dir  # PR2-3
    data_dir_path = _resolve_data_dir(data_dir)
    evidence_dir = data_dir_path / "evidence"

    # 1. Load stage3_candidates (single narrowed set — rubric ∩ Stage 1 PASS).
    # Evidence_assessor's Stage 3 loop and hypothesis_writer run on this list.
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
                if has_errors or not_executed:
                    genes_with_errors.append(gene)
            except (json.JSONDecodeError, OSError):
                genes_with_errors.append(gene)
        else:
            missing.append(gene)

    result = {
        "success": len(missing) == 0 and len(genes_with_errors) == 0,
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


def _indication_dedup_key(indication: Any) -> str:
    if isinstance(indication, dict):
        for key in (
            "efo_term",
            "mesh_heading",
            "disease",
            "disease_name",
            "indication",
            "label",
            "name",
        ):
            value = indication.get(key)
            if value:
                return re.sub(r"\s+", " ", str(value).strip().casefold())
        return json.dumps(indication, sort_keys=True, default=str).casefold()
    return re.sub(r"\s+", " ", str(indication or "").strip().casefold())


def _dedupe_indications(indications: list[Any] | Any) -> list[Any]:
    """Drop blank/duplicate indications while preserving first spelling/order."""
    if indications is None:
        return []
    if not isinstance(indications, list):
        indications = [indications]
    result: list[Any] = []
    seen: set[str] = set()
    for indication in indications:
        if isinstance(indication, str):
            cleaned: Any = re.sub(r"\s+", " ", indication.strip())
        else:
            cleaned = indication
        key = _indication_dedup_key(cleaned)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def _stage1_row_pair_key(row: dict[str, Any]) -> str:
    ligand = str(row.get("ligand", "")).strip().upper()
    receptor = str(row.get("receptor", "")).strip().upper()
    return f"{ligand}^{receptor}" if ligand and receptor else ""


def _stage1_row_passed(row: dict[str, Any], stage1_passed: dict[str, bool]) -> bool:
    key = _stage1_row_pair_key(row)
    if not key:
        return False
    ligand, receptor = key.split("^", 1)
    return stage1_passed.get(key, stage1_passed.get(f"{receptor}^{ligand}", False))


def _stage1_row_pathway_for_gene(row: dict[str, Any], gene: str) -> str:
    gene_upper = gene.upper()
    ligand = str(row.get("ligand", "")).strip().upper()
    receptor = str(row.get("receptor", "")).strip().upper()
    kegg = row.get("kegg_pathways", {})
    if not isinstance(kegg, dict):
        return ""
    preferred_keys = (
        ("receptor_pathways", "ligand_pathways")
        if gene_upper == receptor
        else ("ligand_pathways", "receptor_pathways")
        if gene_upper == ligand
        else ("receptor_pathways", "ligand_pathways")
    )
    for key in preferred_keys:
        pathways = kegg.get(key, [])
        if pathways:
            return pathways[0] if isinstance(pathways[0], str) else str(pathways[0])
    return ""


def _select_stage1_representative_context(
    gene: str,
    stage1_data: dict[str, dict],
    stage1_passed: dict[str, bool],
) -> dict[str, Any]:
    """Pick one representative Stage 1 row, preferring PASSED evidence."""
    gene_upper = gene.upper()
    candidates: list[tuple[bool, float, dict[str, Any]]] = []
    for s1_val in stage1_data.values():
        if not isinstance(s1_val, dict):
            continue
        s1_lig = str(s1_val.get("ligand", "")).strip().upper()
        s1_rec = str(s1_val.get("receptor", "")).strip().upper()
        if gene_upper not in (s1_lig, s1_rec):
            continue
        ppi = s1_val.get("string_ppi", {})
        score = 0.0
        if isinstance(ppi, dict):
            score = _to_float(ppi.get("max_combined_score", 0.0), 0.0)
        candidates.append((_stage1_row_passed(s1_val, stage1_passed), score, s1_val))
    if not candidates:
        return {"string_ppi_score": 0.0, "primary_kegg_pathway": "No pathway data"}
    passed, score, row = max(candidates, key=lambda item: (item[0], item[1]))
    del passed
    return {
        "string_ppi_score": score,
        "primary_kegg_pathway": _stage1_row_pathway_for_gene(row, gene) or "No pathway data",
    }


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
        # Pair rubric inherits the scores of whichever gene has rubric data:
        # receptor preferred, ligand as fallback. Record which gene provided
        # the scores so downstream consumers can distinguish pair-intrinsic
        # from gene-inherited signal (e.g. HLA-DQB1--CD4 inherits CD4, not
        # HLA-DQB1, and without this annotation the HLA pair appeared as a
        # top-ranked candidate despite HLA-DQB1 itself being
        # insufficient_evidence at the gene level).
        if receptor in rubric_by_gene:
            rubric = rubric_by_gene[receptor]
            score_source = receptor
        elif ligand in rubric_by_gene:
            rubric = rubric_by_gene[ligand]
            score_source = ligand
        else:
            rubric = {}
            score_source = ""
        pair_matrix.append({
            "ligand": ligand,
            "receptor": receptor,
            "score_source": score_source,
            "existing_drug_evidence": rubric.get("existing_drug_evidence", 0),
            "clinical_trial_activity": rubric.get("clinical_trial_activity", 0),
            "safety_profile": rubric.get("safety_profile", 0),
            "gwas_support": rubric.get("gwas_support", 0),
            "tractability": rubric.get("tractability", 0),
            "biological_plausibility": rubric.get("biological_plausibility", 0),
            "novelty_opportunity": rubric.get("novelty_opportunity", 0),
            **_target_assessment_audit_metadata_from_rubric(rubric),
        })

    # C. Rank candidates and inject OpenTargets scores
    ranked_matrix = rank_featured_candidates(pair_matrix)

    # Stage 1 filter lookup ({ligand}^{receptor} → passed bool) for B5
    # promotion logic. stage1_filter.json is authoritative; fall back to an
    # empty map if the file is missing so the existing behaviour is preserved.
    stage1_passed: dict[str, bool] = {}
    filter_path = evidence_dir / "stage1_filter.json"
    if filter_path.exists():
        try:
            _raw = json.loads(filter_path.read_text(encoding="utf-8"))
            if isinstance(_raw, dict):
                for key, entry in _raw.items():
                    if not isinstance(entry, dict):
                        continue
                    stage1_passed[key.upper()] = bool(entry.get("passed", False))
        except Exception:
            stage1_passed = {}

    def _pair_passed_stage1(row: dict) -> bool:
        ligand_u = str(row.get("ligand", "")).strip().upper()
        receptor_u = str(row.get("receptor", "")).strip().upper()
        key1 = f"{ligand_u}^{receptor_u}"
        key2 = f"{receptor_u}^{ligand_u}"
        return stage1_passed.get(key1, stage1_passed.get(key2, False))

    # Initialise promotion_reason for every row. The "organic_featured"
    # label applies to pairs that were already marked featured by
    # `rank_featured_candidates` (i.e., they earned it via combined_total).
    for row in ranked_matrix:
        if row.get("is_featured") or row.get("is_novel"):
            row["promotion_reason"] = "organic_featured"
        else:
            row["promotion_reason"] = None

    # Reconcile pair-level featured/novel with gene-level stage3_candidates:
    # 1. Remove featured from pairs where NEITHER gene is a stage3_candidate
    # 2. Ensure EVERY stage3 gene has at least one pair marked is_featured
    #    — 2-pass logic: prefer Stage 1 PASSED pairs, fall back to any pair.
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
                row["promotion_reason"] = None
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

        def _promote_for_missing(only_passed: bool, reason: str) -> None:
            for row in ranked_matrix:
                if not missing:
                    break
                if only_passed and not _pair_passed_stage1(row):
                    continue
                ligand = str(row.get("ligand", "")).strip().upper()
                receptor = str(row.get("receptor", "")).strip().upper()
                for g in (receptor, ligand):
                    if g in missing:
                        row["is_featured"] = True
                        row["promotion_reason"] = reason
                        missing.discard(g)
                        break

        # Pass 1: try Stage 1 PASSED pairs for missing genes
        _promote_for_missing(
            only_passed=True,
            reason="stage3_coverage_fallback_passed",
        )
        # Pass 2: if still uncovered, fall back to any pair (including
        # FAILED Stage 1). This preserves the previous behaviour so no
        # gene disappears from deep_dive, but the `promotion_reason`
        # field now tells downstream consumers that the evidence is
        # weak.
        _promote_for_missing(
            only_passed=False,
            reason="stage3_coverage_fallback_failed",
        )

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

    # Gene-level authoritative track map from rubric classification.
    # Previously the track was derived from `row.get("is_featured")` on the
    # last iterand of the `ranked_matrix` loop above — a stale-variable leak
    # that tagged every gene the same way regardless of identity.
    gene_track_map: dict[str, str] = {}
    for g_name, g_rubric in (rubric_by_gene or {}).items():
        cls = str((g_rubric or {}).get("classification", "")).strip()
        gene_track_map[g_name.upper()] = "novel" if cls == "novel_candidate" else "featured"

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
        stage1_context = _select_stage1_representative_context(
            gene,
            stage1_data,
            stage1_passed,
        )

        featured_deep_dive.append({
            "target_gene": gene,
            "track": gene_track_map.get(gene.upper(), "featured"),
            "stage3_clinical_safety": {
                "known_drugs_drugbank": [
                    d.get("drug_name", d.get("name", ""))
                    for d in s3.get("drugs", [])
                ],
                "toxicity_admet": (
                    s3.get("safety_summary")
                    or _ot_safety_summary(evidence_dir, gene)
                    or "No safety data available"
                ),
            },
            "stage1_biological_context": {
                "string_ppi_score": stage1_context["string_ppi_score"],
                "primary_kegg_pathway": stage1_context["primary_kegg_pathway"],
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


def _stage1_evidence_disease(stage1_payload: dict[str, Any]) -> str:
    for key in ("census_cross_validation", "census_validation"):
        census = stage1_payload.get(key)
        if isinstance(census, dict):
            disease = str(census.get("disease") or "").strip()
            if disease:
                return disease
    return ""


def _build_disease_scope(
    requested_disease: object,
    evidence_diseases: set[str],
) -> dict[str, object]:
    requested = str(requested_disease or "").strip()
    evidence = sorted(d for d in evidence_diseases if d)
    requested_norm = requested.casefold()
    requires_proxy_note = any(
        disease.casefold() == "pulmonary fibrosis"
        and requested_norm == "idiopathic pulmonary fibrosis"
        for disease in evidence
    )
    proxy_note = ""
    if requires_proxy_note:
        proxy_note = (
            "Scope note: Stage 1 Census evidence for these hypotheses is labeled "
            "pulmonary fibrosis and is used here as a proxy for idiopathic pulmonary "
            "fibrosis; Section 4 statements should be read as IPF-oriented hypotheses "
            "rather than direct disease-specific proof. [source: disease_scope]"
        )
    return {
        "requested_disease": requested,
        "evidence_diseases": evidence,
        "requires_proxy_note": requires_proxy_note,
        "proxy_note": proxy_note,
    }


@tool
def build_evidence_summary(data_dir: str) -> str:
    """Build a Reference Card with exact values from all evidence files.

    Returns a structured JSON summary that report_writer MUST use as the
    single source of truth for all numeric values, drug names,
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
            "gwas_rank_points": row.get("gwas_rank_points", 0),
            "tractability_rank_points": row.get("tractability_rank_points", 0),
            "biological_plausibility_rank_points": row.get("biological_plausibility_rank_points", 0),
            "novelty_opportunity_rank_points": row.get("novelty_opportunity_rank_points", 0),
            "exploratory_rank_total": row.get("exploratory_rank_total", row.get("exploratory_total", 0)),
            "combined_rank_score": row.get("combined_rank_score", row.get("combined_total", 0)),
            "existing_drug_evidence": row.get("existing_drug_evidence", 0),
            "clinical_trial_activity": row.get("clinical_trial_activity", 0),
            "safety_profile": row.get("safety_profile", 0),
            "safety_evidence_level": row.get("safety_evidence_level", "no_known_liability"),
            "safety_liability_count": row.get("safety_liability_count", 0),
            "safety_liability_sources": row.get("safety_liability_sources", ""),
            "gwas_support": row.get("gwas_support", 0),
            "gwas_evidence_type": row.get("gwas_evidence_type", "none"),
            "gwas_min_pvalue": row.get("gwas_min_pvalue"),
            "gwas_trait_match_level": row.get("gwas_trait_match_level", "none"),
            "gwas_direct_hit_count": row.get("gwas_direct_hit_count", 0),
            "gwas_proximity_hit_count": row.get("gwas_proximity_hit_count", 0),
            "tractability": row.get("tractability", 0),
            "tractability_basis": row.get("tractability_basis", "unknown"),
            "tractability_modalities": row.get("tractability_modalities", ""),
            "tractability_evidence_label": row.get("tractability_evidence_label", "none"),
            "biological_plausibility_base": row.get("biological_plausibility_base", 0),
            "stage1_biological_support_bonus": row.get("stage1_biological_support_bonus", 0),
            "biological_basis": row.get("biological_basis", "none"),
            "biological_evidence_types": row.get("biological_evidence_types", ""),
            "biological_evidence_count": row.get("biological_evidence_count", 0),
            "biological_max_ot_score": row.get("biological_max_ot_score"),
            "vep_high_impact_count": row.get("vep_high_impact_count", 0),
            "stage1_support_pair_count": row.get("stage1_support_pair_count", 0),
            "stage1_support_pairs": row.get("stage1_support_pairs", ""),
            **_stage1_audit_metadata_from_row(row),
            "biological_plausibility": row.get("biological_plausibility", 0),
            "novelty_opportunity": row.get("novelty_opportunity", 0),
            "novelty_basis": row.get("novelty_basis", "st_only_or_brand_new_target"),
            "novelty_association_count": row.get("novelty_association_count", 0),
            "novelty_target_drug_count": row.get("novelty_target_drug_count", 0),
            "novelty_bucket": row.get("novelty_bucket", "0-9 associations"),
            "novelty_source": row.get("novelty_source", "list_length"),
            "stage3_candidate": row.get("stage3_candidate", False),
        }

    # build_evidence_summary feeds the report_writer Reference Card.
    # stage3_candidates is the single source of truth (post Stage 1 narrowing).
    _validated = assessment.get("stage3_candidates", [])
    stage3_genes = [g for c in _validated if (g := c.get("gene"))]

    # 2. Load stage3_*.json → drugs per gene
    stage3_data: dict[str, dict] = {}
    for gene in stage3_genes:
        s3_path = evidence_dir / f"stage3_{gene}.json"
        if not s3_path.exists():
            stage3_data[gene] = {"drugs": [], "error": "file not found"}
            continue
        try:
            s3 = json.loads(s3_path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Corrupt stage3_%s.json: %s", gene, exc)
            stage3_data[gene] = {"drugs": [], "error": f"corrupt: {exc}"}
            continue
        drugs = []
        raw_drugs: list[dict] = []
        stage3_containers = [s3]
        if isinstance(s3.get("chembl"), dict):
            stage3_containers.append(s3["chembl"])
        for container in stage3_containers:
            for key in ("chembl_drugs", "matched_drugs", "preclinical_compounds", "chembl_records"):
                entries = container.get(key)
                if isinstance(entries, dict):
                    entries = entries.get("matched_drugs", [])
                if isinstance(entries, list):
                    raw_drugs.extend([entry for entry in entries if isinstance(entry, dict)])
        for d in raw_drugs:
            indications = d.get("indications", [])
            if not indications and d.get("indication"):
                indications = [d.get("indication")]
            indications = _dedupe_indications(indications)
            drugs.append({
                "chembl_id": d.get("chembl_id") or d.get("molecule_chembl_id", ""),
                "drug_name": d.get("drug_name") or d.get("name") or d.get("pref_name", ""),
                "mechanism_of_action": d.get("mechanism_of_action"),
                "indications": indications,
                "max_phase": d.get("max_phase"),
                "first_approval": d.get("first_approval"),
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
                    indications = _dedupe_indications(indications)
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
        s3_chembl = s3.get("chembl") if isinstance(s3.get("chembl"), dict) else {}
        s3_errors = s3.get("errors", []) or s3_chembl.get("errors", [])
        s3_executed = bool(s3.get("executed", False) or s3_chembl.get("executed", False))

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
    stage1_evidence_diseases: set[str] = set()
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
        evidence_disease = _stage1_evidence_disease(s1)
        if evidence_disease:
            stage1_evidence_diseases.add(evidence_disease)

        stage1_data[pair_key] = {
            "ligand": ligand,
            "receptor": receptor,
            "evidence_disease": evidence_disease,
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
            "safety_evidence_level": row.get("safety_evidence_level", "no_known_liability"),
            "safety_liability_count": row.get("safety_liability_count", 0),
            "safety_liability_sources": row.get("safety_liability_sources", ""),
            "validated_total": row.get("validated_total", 0),
            "gwas_support": row.get("gwas_support", 0),
            "gwas_evidence_type": row.get("gwas_evidence_type", "none"),
            "gwas_min_pvalue": row.get("gwas_min_pvalue"),
            "gwas_trait_match_level": row.get("gwas_trait_match_level", "none"),
            "gwas_direct_hit_count": row.get("gwas_direct_hit_count", 0),
            "gwas_proximity_hit_count": row.get("gwas_proximity_hit_count", 0),
            "tractability": row.get("tractability", 0),
            "tractability_basis": row.get("tractability_basis", "unknown"),
            "tractability_modalities": row.get("tractability_modalities", ""),
            "tractability_evidence_label": row.get("tractability_evidence_label", "none"),
            "biological_plausibility_base": row.get("biological_plausibility_base", 0),
            "stage1_biological_support_bonus": row.get("stage1_biological_support_bonus", 0),
            "biological_basis": row.get("biological_basis", "none"),
            "biological_evidence_types": row.get("biological_evidence_types", ""),
            "biological_evidence_count": row.get("biological_evidence_count", 0),
            "biological_max_ot_score": row.get("biological_max_ot_score"),
            "vep_high_impact_count": row.get("vep_high_impact_count", 0),
            "stage1_support_pair_count": row.get("stage1_support_pair_count", 0),
            "stage1_support_pairs": row.get("stage1_support_pairs", ""),
            **_stage1_audit_metadata_from_row(row),
            "biological_plausibility": row.get("biological_plausibility", 0),
            "novelty_opportunity": row.get("novelty_opportunity", 0),
            "novelty_basis": row.get("novelty_basis", "st_only_or_brand_new_target"),
            "novelty_association_count": row.get("novelty_association_count", 0),
            "novelty_target_drug_count": row.get("novelty_target_drug_count", 0),
            "novelty_bucket": row.get("novelty_bucket", "0-9 associations"),
            "novelty_source": row.get("novelty_source", "list_length"),
            "exploratory_total": row.get("exploratory_total", 0),
            "combined_total": row.get("combined_total", 0),
            "gwas_rank_points": row.get("gwas_rank_points", 0),
            "tractability_rank_points": row.get("tractability_rank_points", 0),
            "biological_plausibility_rank_points": row.get("biological_plausibility_rank_points", 0),
            "novelty_opportunity_rank_points": row.get("novelty_opportunity_rank_points", 0),
            "exploratory_rank_total": row.get("exploratory_rank_total", row.get("exploratory_total", 0)),
            "combined_rank_score": row.get("combined_rank_score", row.get("combined_total", 0)),
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

    # 7. Load hypothesis_report.json (if hypothesis_writer completed).
    # The summarizer may create a sanitized copy that removes impossible file
    # references while preserving the original hypothesis_writer artifact.
    hypothesis_data = {}
    sanitized_hypothesis_path = evidence_dir / "hypothesis_report.summarizer_sanitized.json"
    hypothesis_path = (
        sanitized_hypothesis_path
        if sanitized_hypothesis_path.exists()
        else evidence_dir / "hypothesis_report.json"
    )
    hypothesis_source: dict[str, object] | None = None
    if hypothesis_path.exists():
        with open(hypothesis_path, encoding="utf-8") as _f:
            hypothesis_data = json.load(_f)
        from src.agents.drug_target.tools.report_expansion_schema import (
            canonical_json_hash,
        )

        hypothesis_source = {
            "path": str(hypothesis_path.relative_to(data_dir_path)),
            "canonical_sha256": canonical_json_hash(hypothesis_data),
        }

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
        _s3_path = evidence_dir / f"stage3_{gene}.json"
        if _s3_path.exists():
            try:
                _s3_raw = json.loads(_s3_path.read_text())
                card.setdefault("stage3", {})["matched_drugs"] = _s3_raw.get("chembl", {}).get("matched_drugs", [])
            except (json.JSONDecodeError, OSError):
                card.setdefault("stage3", {})["matched_drugs"] = []
        else:
            card.setdefault("stage3", {})["matched_drugs"] = []
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
                "first_approval": drug.get("first_approval"),
                "mechanism_of_action": drug.get("mechanism_of_action"),
                "source": drug.get("source", "opentargets"),
            })
        for drug in gene_data.get("preclinical_compounds", []):
            resolved_drugs_audit.append({
                "gene": gene,
                "chembl_id": drug.get("chembl_id", ""),
                "resolved_name": drug.get("drug_name", ""),
                "molecule_type": None,
                "max_phase": drug.get("max_phase"),
                "first_approval": drug.get("first_approval"),
                "mechanism_of_action": drug.get("mechanism_of_action"),
                "source": "chembl",
            })
    resolved_drugs_path = evidence_dir / "resolved_drugs.json"
    resolved_drugs_path.write_text(
        json.dumps(
            _sanitize_for_strict_json(resolved_drugs_audit),
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        ),
        encoding="utf-8",
    )

    # Build pre-formatted markdown template
    disease_name = assessment.get("disease", "unknown")
    disease_scope = _build_disease_scope(disease_name, stage1_evidence_diseases)
    celltype_resolution = {}
    celltype_resolution_path = evidence_dir / "celltype_resolution.json"
    if celltype_resolution_path.exists():
        try:
            celltype_resolution = json.loads(
                celltype_resolution_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            celltype_resolution = {}
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
        disease_scope=disease_scope,
        data_limitations=data_limitations,
        celltype_resolution=celltype_resolution,
        novelty_opportunity_legend=NOVELTY_OPPORTUNITY_LEGEND,
    )

    reference_card = {
        "reference_card_version": "2.0",
        "instruction": (
            "This is the AUTHORITATIVE Reference Card with a PRE-FORMATTED MARKDOWN TEMPLATE. "
            "Use the `markdown_template` field as the SKELETON for drug.md. "
            "The template contains all correct values (scores, drug names, pathways). "
            "Your job: EXPAND each section with 2-4 sentences of biological interpretation. "
            "Do NOT change any numbers, drug names, or classifications in the template. "
            "ADD narrative around the pre-filled data to create a comprehensive report."
        ),
        "disease": disease_name,
        "disease_scope": disease_scope,
        "stage3_candidates": stage3_genes,
        "featured_genes": featured_cards,
        "all_genes_druggability": all_genes_matrix,
        "stage1_filter_results": stage1_filter_results,
        "hypothesis_data": hypothesis_data,
        "hypothesis_source": hypothesis_source,
        "known_drugs_disease_level": known_drugs[:20] if isinstance(known_drugs, list) else known_drugs,
        "data_limitations": data_limitations,
        "markdown_template": md_template,
    }

    try:
        from src.agents.drug_target.tools.report_expansion_schema import (
            persist_drug_report_reference_card,
        )

        reference_card = persist_drug_report_reference_card(
            data_dir_path,
            reference_card,
        )
    except Exception as exc:
        logger.warning("Failed to persist drug_report_reference_card.json: %s", exc)

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

# --- T3-T7 helper constants -------------------------------------------------

_DRUG_NAME_RE = re.compile(
    r"\b([A-Z][A-Za-z]{2,}(?:[\s-][A-Z0-9][A-Za-z0-9]*){0,2}|[A-Z]{2,}-?\d+[A-Z]*\d*)\b"
)

_DRUG_NAME_STOPLIST: frozenset[str] = frozenset({
    # Spec-defined stoplist
    "Phase", "Class", "Section", "Reference", "Card", "Note", "FDA", "HIV",
    "AML", "CML", "EMA", "TBD", "OR", "AND", "NOT", "IF", "THEN",
    "Yes", "No", "None", "WT", "MT", "ENA", "OS", "PFS", "ORR",
    "Trial", "Drug", "Targets", "Indications", "Mechanism", "Action",
    "Across", "Taken", "Together", "Their", "Its", "Overall", "Because", "Use",
    "Test", "Profile", "Model", "Quantify", "Blocking", "Criteria", "ALL",
    # Common sentence-initial English words (Title-case at line start)
    "This", "The", "These", "Those", "Both", "All", "Any", "Some", "Each",
    "That", "Next", "Pairs", "Approved", "When", "Where",
    "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
    "Current", "Previous", "Further", "Additional", "Several", "Multiple",
    "Analysis", "Evidence", "Data", "Summary", "Report", "Results",
    "Spatial", "Clinical", "Biological", "Therapeutic", "Therapeutically", "Genetic",
    "Biomarker", "Biomarkers", "Pathway", "Pathways", "Receptor", "Receptors",
    "Compound", "Compounds", "Target", "Gene", "Genes", "Protein", "Proteins",
    # Disease / pathway acronyms that are not drug names
    "IPF", "GWAS", "ERK", "AKT", "TGF", "SMAD", "SMAD2", "SMAD3",
    "ATP", "GTP", "mRNA", "RNA", "DNA", "PCR", "IFN", "TNF", "IL",
    "VEGF", "MAPK", "PI3K", "NF", "NFkB", "HER", "KRAS", "BRAF",
    "SRC", "MHC", "Ras", "RAS", "JAK", "STAT", "WNT", "Notch",
    "NSCLC", "DLBCL", "CLL", "NHL", "MDS", "MF", "ET", "PV",
    "COPD", "ILD", "CVD", "CHF", "CKD", "T2D", "T1D", "MS",
    # Report section / template markup words
    "FEATURED", "Featured", "Validated", "Exploratory", "Recommended", "Prioritized",
    "Top", "Key", "Main", "Primary", "Secondary",
    # Pipeline stage labels — never drug names (Fix F-E)
    # The regex captures multi-word tokens like "Stage 1" as a single match.
    "Stage", "Stage1", "Stage2", "Stage3",
    "Stage 1", "Stage 2", "Stage 3",
    "Stage 1 Filter", "Stage 3 ChEMBL",
    # Report labels and data-source labels
    "CCI", "Census", "STRING", "KEGG", "Reactome", "OpenTargets", "ChEMBL", "ChEMBL Bioactivity",
    "Risk Ratio", "Drug Profile", "Clinical Compounds",
    "Preclinical Compounds", "Biological Context", "Rubric Assessment",
    "Validated Track", "Exploratory Track", "Core Claim",
    "Evidence References", "Biological Entities", "Falsifiable Prediction",
    "Validation Approach", "Category", "Therapeutic Strategy",
    "Cross-Target Interaction", "Novel Pathway",
    # Disease/biology proper nouns frequently appearing in indication/pathway text
    "HIV-1", "Sezary", "Hodgkins", "Crohn", "MHC-II", "APC-T",
})

_DRUG_LIKE_SUFFIXES: tuple[str, ...] = (
    "mab",
    "nib",
    "tinib",
    "statin",
    "cillin",
    "cycline",
    "azole",
    "vir",
    "xaban",
    "parin",
    "platin",
    "taxel",
    "mycin",
    "ol",
)

_BRACKET_FILE_RE = re.compile(r"\[from\s+([\w\-\.]+\.json(?:_FAILED)?)\s*\]")
_BARE_FILE_RE = re.compile(r"\b(stage[0-9][\w\-]*\.json(?:_FAILED)?)\b")
_SPECIAL_FILE_RE = re.compile(
    r"\b((?:known_drugs|hypothesis_report|resolved_drugs|gene_manifest"
    r"|assessment_results|rubric_scores)\.(?:json|csv)(?:_FAILED)?)\b"
)

_APPROVAL_YEAR_RE = re.compile(
    r"(?P<drug>[A-Z][A-Za-z0-9_-]+)[^.]{0,80}?(?:approved|approval)[^.]{0,30}?(?P<year>\d{4})",
    re.IGNORECASE,
)

_MOA_VERB_RE = re.compile(
    r"\b(?:degrades?|cleaves?|antagoni[sz]es?|inhibits?|blocks?|targets?\s+the|"
    r"binds?\s+to|disrupts?|activates?\s+as|functions?\s+as)\b",
    re.IGNORECASE,
)

_ANNOTATION_RE = re.compile(r"\[source:\s*([^\]]+)\]", re.IGNORECASE)
_ANNOTATION_FIELD_RE = re.compile(r"^[a-z_][a-z0-9_]*$", re.IGNORECASE)

_EVIDENCE_SECTION_RE = re.compile(
    r"(?:evidence\s+references?|gap\s+analysis|uncovered\s+evidence\s+files?)",
    re.IGNORECASE,
)

_EXPAND_SENTENCE_END_RE = re.compile(r"[.!?]")

# Allowed source annotation fields (base set; augmented from evidence JSONs at runtime)
_BASE_EVIDENCE_FIELDS: frozenset[str] = frozenset({
    "name", "max_phase", "indications", "mechanism_of_action", "molecule_type",
    "first_approval", "chembl_id", "gene", "matched_drugs",
    "preclinical_compounds", "interpretation",
})


def _is_expand_prose(line: str) -> bool:
    """Return True if the line looks like EXPAND-region prose (not table/header/list).

    Prose lines do not need to end with sentence-ending punctuation — multi-line
    sentences are common and the check must not skip wrapped continuation lines.
    """
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith("|"):
        return False
    if stripped.startswith("#"):
        return False
    if re.match(r"[-*]\s+|^\d+\.\s+", stripped):
        return False
    if re.match(r"^\*\*[^*]+:?\*\*", stripped):
        return False
    if stripped.startswith(
        (
            "This report presents a comprehensive therapeutic target assessment",
            "Each gene is scored on two independent tracks",
            "Evidence coverage:",
        )
    ):
        return False
    return True


def _build_drug_allowlist(
    evidence_dir: "Path",
    resolved_drugs: list[dict],
) -> frozenset[str]:
    """Build case-folded set of known drug/gene names from evidence files.

    Includes gene symbols from stage3 files so they are not flagged as
    fabricated drug names when they appear in prose.

    Supports both ``name`` and ``resolved_name`` fields so that evidence files
    produced by the ChEMBL resolver (which uses ``resolved_name``) are
    recognised alongside legacy files that use ``name``.
    """
    allowlist: set[str] = set()
    for d in resolved_drugs:
        name = (d.get("name") or d.get("resolved_name") or "").strip().casefold()
        if name:
            allowlist.add(name)
    for stage3_path in evidence_dir.glob("stage3_*.json"):
        try:
            stage3 = json.loads(stage3_path.read_text())
        except Exception:
            continue
        # Add gene symbol so it is not flagged as a fabricated drug name
        gene = (stage3.get("gene") or "").strip().casefold()
        if gene:
            allowlist.add(gene)
        for entry in stage3.get("matched_drugs", []):
            name = (entry.get("name") or "").strip().casefold()
            if name:
                allowlist.add(name)
        for entry in stage3.get("preclinical_compounds", []):
            name = (entry.get("name") or "").strip().casefold()
            if name:
                allowlist.add(name)
    for stage1_path in evidence_dir.glob("stage1_*.json"):
        if not _is_stage1_pair_artifact(stage1_path):
            continue
        pair_text = stage1_path.stem.removeprefix("stage1_")
        pair_parts = pair_text.split("--", 1)
        if len(pair_parts) == 2:
            ligand, receptor = (part.strip() for part in pair_parts)
            if ligand and receptor:
                allowlist.add(ligand.casefold())
                allowlist.add(receptor.casefold())
                allowlist.add(f"{ligand}-{receptor}".casefold())
                allowlist.add(f"{ligand}–{receptor}".casefold())
                allowlist.add(f"{ligand}—{receptor}".casefold())
        try:
            stage1 = json.loads(stage1_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(stage1, dict):
            ligand = str(stage1.get("ligand") or "").strip()
            receptor = str(stage1.get("receptor") or "").strip()
            if ligand and receptor:
                allowlist.add(ligand.casefold())
                allowlist.add(receptor.casefold())
                allowlist.add(f"{ligand}-{receptor}".casefold())
                allowlist.add(f"{ligand}–{receptor}".casefold())
                allowlist.add(f"{ligand}—{receptor}".casefold())
    # Load all gene symbols from gene_manifest.json so they are not mistaken
    # for fabricated drug names when appearing in prose. (Fix F-E)
    gene_manifest_path = evidence_dir / "gene_manifest.json"
    if gene_manifest_path.exists():
        try:
            manifest = json.loads(gene_manifest_path.read_text())
            if isinstance(manifest, list):
                for entry in manifest:
                    symbol = (entry.get("symbol") or "").strip().casefold()
                    if symbol:
                        allowlist.add(symbol)
        except Exception:
            pass
    return frozenset(allowlist)


def _build_moa_map(resolved_drugs: list[dict]) -> dict[str, str]:
    """Build case-folded drug-name → mechanism_of_action map.

    Supports both ``name`` and ``resolved_name`` fields so that evidence files
    produced by the ChEMBL resolver (which uses ``resolved_name``) are
    recognised alongside legacy files that use ``name``.
    """
    result: dict[str, str] = {}
    for d in resolved_drugs:
        name = (d.get("name") or d.get("resolved_name") or "").strip().casefold()
        if name:
            result[name] = (d.get("mechanism_of_action") or "").casefold()
    return result


def _build_evidence_field_set(evidence_dir: "Path") -> frozenset[str]:
    """Build set of known evidence JSON field names from all evidence files."""
    fields: set[str] = set(_BASE_EVIDENCE_FIELDS)

    def add_field(value: object) -> None:
        field = str(value or "").strip()
        if field:
            fields.add(field.casefold())

    for json_path in evidence_dir.glob("*.json"):
        try:
            data = json.loads(json_path.read_text())
        except Exception:
            continue
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    fields.update(k.casefold() for k in item.keys())
        elif isinstance(data, dict):
            fields.update(k.casefold() for k in data.keys())
    data_dir = evidence_dir.parent
    expansions_path = data_dir / "report_expansions.json"
    if expansions_path.exists():
        try:
            expansions = json.loads(expansions_path.read_text(encoding="utf-8"))
        except Exception:
            expansions = {}
        slots = expansions.get("slots", []) if isinstance(expansions, dict) else []
        for slot in slots:
            if not isinstance(slot, dict):
                continue
            for sentence in slot.get("sentences", []) or []:
                if not isinstance(sentence, dict):
                    continue
                provenance = sentence.get("source_provenance")
                if isinstance(provenance, dict):
                    sf = provenance.get("source_field")
                    add_field(sf)
                    # Also register the bare field after a gene prefix
                    # (``CD4::combined_total`` → ``combined_total``) so the
                    # T7 unanchored-sentence check, which extracts the bare
                    # segment via rsplit(":", 1)[-1], finds a match.
                    if sf:
                        add_field(str(sf).rsplit("::", 1)[-1])
                for field in sentence.get("source_fields", []) or []:
                    add_field(str(field).rsplit(".", 1)[-1])
                    add_field(str(field).rsplit("::", 1)[-1])
    reference_path = data_dir / "drug_report_reference_card.json"
    if reference_path.exists():
        try:
            reference = json.loads(reference_path.read_text(encoding="utf-8"))
        except Exception:
            reference = {}
        provenance_index = (
            reference.get("provenance_index", {})
            if isinstance(reference, dict)
            else {}
        )
        for provenance in provenance_index.values():
            if isinstance(provenance, dict):
                add_field(provenance.get("source_field"))
    return frozenset(fields)


def _check_fabricated_drug_name(
    line: str,
    line_no: int,
    drug_allowlist: frozenset[str],
) -> list[dict]:
    """T3: Flag drug-like capitalized names in EXPAND prose absent from evidence allowlist."""
    if not _is_expand_prose(line):
        return []
    findings: list[dict] = []
    for match in _DRUG_NAME_RE.finditer(line):
        candidate = match.group(1)
        candidate_words = candidate.split()
        if candidate in _DRUG_NAME_STOPLIST:
            continue
        if candidate_words and candidate_words[0] in _DRUG_NAME_STOPLIST:
            continue
        if candidate_words and all(word in _DRUG_NAME_STOPLIST for word in candidate_words):
            continue
        first_nonspace = len(line) - len(line.lstrip())
        if (
            match.start(1) == first_nonspace
            and len(candidate_words) == 1
            and candidate.istitle()
            and "-" not in candidate
            and not any(char.isdigit() for char in candidate)
            and not candidate.casefold().endswith(_DRUG_LIKE_SUFFIXES)
        ):
            continue
        if candidate.casefold() not in drug_allowlist:
            findings.append({
                "type": "FABRICATED_DRUG_NAME",
                "line": line_no,
                "snippet": line[:120],
                "expected": "drug name in resolved_drugs.json or stage3_*.json[matched_drugs/preclinical_compounds]",
                "actual": f"{candidate} not found in evidence allowlist",
                "remediation": "Remove drug claim or move drug to the appropriate stage3 evidence file",
            })
    return findings


def _check_fabricated_file_reference(
    line: str,
    line_no: int,
    evidence_dir: "Path",
    in_evidence_section: bool,
) -> list[dict]:
    """T4: Flag file references that are _FAILED or point to absent evidence files."""
    findings: list[dict] = []
    seen_filenames: set[str] = set()

    def _emit(filename: str, snippet: str) -> None:
        if filename in seen_filenames:
            return
        seen_filenames.add(filename)
        if filename.endswith("_FAILED"):
            findings.append({
                "type": "FABRICATED_FILE_REFERENCE",
                "line": line_no,
                "snippet": snippet[:120],
                "expected": "evidence file without _FAILED suffix",
                "actual": f"file with _FAILED suffix referenced",
                "remediation": "Remove the _FAILED suffix or remove the citation entirely",
            })
        elif not in_evidence_section and not (evidence_dir / filename).exists():
            findings.append({
                "type": "FABRICATED_FILE_REFERENCE",
                "line": line_no,
                "snippet": snippet[:120],
                "expected": f"file exists at {evidence_dir / filename}",
                "actual": "file does not exist",
                "remediation": "Remove the citation or check the filename spelling",
            })

    for pattern in (_BRACKET_FILE_RE, _BARE_FILE_RE, _SPECIAL_FILE_RE):
        for match in pattern.finditer(line):
            # Use full line as snippet so context like "From stage..." is visible
            _emit(match.group(1), line)
    return findings


def _check_wrong_approval_year_extended(
    line: str,
    line_no: int,
    resolved_drugs: list[dict],
) -> list[dict]:
    """T5: Extended WRONG_APPROVAL_YEAR — also fires when drug absent or first_approval null."""
    if "first_approval" in line.casefold() and "[source:" in line.casefold():
        return []
    findings: list[dict] = []
    resolved_lookup: dict[str, dict] = {
        (d.get("name") or "").strip().casefold(): d
        for d in resolved_drugs
        if (d.get("name") or "").strip()
    }
    for match in _APPROVAL_YEAR_RE.finditer(line):
        drug = match.group("drug").casefold()
        year = match.group("year")
        snippet = match.group(0)[:120]
        drug_entry = resolved_lookup.get(drug)
        if drug_entry is None:
            findings.append({
                "type": "WRONG_APPROVAL_YEAR",
                "line": line_no,
                "snippet": snippet,
                "expected": f"drug '{drug}' present in resolved_drugs.json",
                "actual": "drug not in evidence",
                "remediation": "Remove the approval year claim or add drug to evidence",
            })
        elif drug_entry.get("first_approval") is None:
            findings.append({
                "type": "WRONG_APPROVAL_YEAR",
                "line": line_no,
                "snippet": snippet,
                "expected": f"first_approval field present in resolved_drugs.json[{drug}]",
                "actual": "drug found but first_approval field is null/missing",
                "remediation": f"Remove the approval year claim — {drug}'s first_approval is not in evidence",
            })
    return findings


def _check_ungrounded_mechanism(
    line: str,
    line_no: int,
    drug_allowlist: frozenset[str],
    moa_map: dict[str, str],
) -> list[dict]:
    """T6: Flag mechanism verbs near drug names when MoA field is empty or mismatched.

    Per spec: only complete-sentence lines (containing terminal punctuation) are checked.
    """
    if not _is_expand_prose(line):
        return []
    if not _EXPAND_SENTENCE_END_RE.search(line.strip()):
        return []
    # Carve-out: sentence has explicit [source: mechanism_of_action] annotation
    if re.search(r"\[source:[^\]]*(?:^|[:,\s])mechanism_of_action(?:\]|[,\s])", line.casefold()):
        return []
    findings: list[dict] = []
    tokens = re.findall(r"\b\w[\w-]*\b", line)

    def is_drug_token(token: str) -> bool:
        folded = token.casefold()
        return (
            folded in moa_map
            or (
                folded not in drug_allowlist
                and re.fullmatch(r"DRUG_[A-Z0-9]+", token) is not None
            )
        )

    drug_positions: list[tuple[int, str]] = [
        (i, tok.casefold())
        for i, tok in enumerate(tokens)
        if is_drug_token(tok)
    ]
    if not drug_positions:
        return []
    moa_matches = list(_MOA_VERB_RE.finditer(line))
    if not moa_matches:
        return []

    seen_drugs: set[str] = set()
    for drug_idx, drug in drug_positions:
        if drug in seen_drugs:
            continue
        for moa_match in moa_matches:
            moa_pos = moa_match.start()
            # Approximate token index for the MoA verb
            text_before_moa = line[:moa_pos]
            moa_token_idx = len(re.findall(r"\b\w[\w-]*\b", text_before_moa))
            if abs(moa_token_idx - drug_idx) > 50:
                continue
            moa_verb = moa_match.group(0).casefold()
            moa_text = moa_map.get(drug, "")
            if not moa_text:
                findings.append({
                    "type": "UNGROUNDED_MECHANISM",
                    "line": line_no,
                    "snippet": line[:120],
                    "expected": f"resolved_drugs.json[{drug}].mechanism_of_action populated",
                    "actual": "mechanism_of_action is empty/missing",
                    "remediation": f"Remove the mechanism claim — {drug}'s MoA is not in evidence",
                })
                seen_drugs.add(drug)
                break
            verb_stem = moa_verb.rstrip("se").rstrip()
            if verb_stem not in moa_text:
                findings.append({
                    "type": "UNGROUNDED_MECHANISM",
                    "line": line_no,
                    "snippet": line[:120],
                    "expected": f"mechanism field contains '{moa_verb}' or related",
                    "actual": f"mechanism field is '{moa_text[:80]}' — no overlap",
                    "remediation": "Align mechanism claim with the field text or remove",
                })
                seen_drugs.add(drug)
                break
    return findings


def _check_unanchored_sentence(
    line: str,
    line_no: int,
    evidence_field_set: frozenset[str],
) -> list[dict]:
    """T7: Flag EXPAND-region sentences missing [source: <field>] or citing absent fields.

    Per spec: only lines that contain at least one terminal punctuation mark (.!?)
    constitute a complete sentence and are checked. Continuation lines, horizontal
    rules (---), and lines without terminal punctuation are skipped.
    """
    if not _is_expand_prose(line):
        return []
    # Only check lines that contain a complete sentence (terminal punctuation)
    if not _EXPAND_SENTENCE_END_RE.search(line.strip()):
        return []
    findings: list[dict] = []
    annotations = [
        field.strip().rsplit(":", 1)[-1].strip()
        for annotation in _ANNOTATION_RE.findall(line)
        for field in annotation.split(",")
        if field.strip()
    ]
    if not annotations:
        findings.append({
            "type": "UNANCHORED_SENTENCE",
            "line": line_no,
            "snippet": line[:120],
            "expected": "[source: <field>] annotation",
            "actual": "no annotation",
            "remediation": "Add [source: <field>] citing the evidence JSON field, or remove the claim",
        })
    else:
        for field in annotations:
            if (
                not _ANNOTATION_FIELD_RE.match(field)
                or field.casefold() not in evidence_field_set
            ):
                findings.append({
                    "type": "UNANCHORED_SENTENCE",
                    "line": line_no,
                    "snippet": line[:120],
                    "expected": "annotation citing an evidence field",
                    "actual": f"annotation [source: {field}] not in allowed fields",
                    "remediation": f"Use a real evidence field name or 'interpretation' for hedged claims",
                })
    return findings


@tool
def validate_drug_md(data_dir: str | Path) -> str:
    """Validate drug.md against evidence files for hallucinations.

    Dual-input contract:
    - When called with `str` (agent runtime), `_resolve_data_dir` is invoked
      so the existing env-var fallback (`DRUG_TARGET_DATA_DIR`,
      `DEEP_INTERPRETER_DATA_DIR`) and LLM-typo tolerance are preserved.
    - When called with `Path` (e.g. from `validate_drug_report_finalization`),
      the path is treated as already resolved and `_resolve_data_dir` is
      bypassed entirely. This prevents the deterministic finalizer from
      silently re-resolving via env fallback.

    Checks:
    1. Classification/priority labels match assessment_results.json
    2. Drug names match stage3_*.json chembl_drugs
    3. No fabricated numeric patterns (e.g. decimal rubric scores)

    Returns: {valid: bool, total_checks: int, issues: [...]}
    Call this AFTER save_drug_md to catch hallucinations before finalizing.
    """
    if isinstance(data_dir, Path):
        data_dir_path = data_dir  # already resolved by caller
    else:
        from src.agents.drug_target.tools.evidence_loader import _resolve_data_dir  # PR2-3
        data_dir_path = _resolve_data_dir(data_dir)
    evidence_dir = data_dir_path / "evidence"
    drug_md_path = data_dir_path / "drug.md"

    if not drug_md_path.exists():
        return json.dumps({"valid": False, "error": "drug.md not found"})

    drug_text = drug_md_path.read_text()
    issues: list[dict] = []

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
                # Determine the line containing this gene match.
                line_start = drug_text.rfind('\n', 0, match.start()) + 1
                line_end = drug_text.find('\n', match.end())
                if line_end == -1:
                    line_end = len(drug_text)
                line_text = drug_text[line_start:line_end]
                # Fix F-D: when the gene is on a Markdown table row (line starts
                # with '|'), only inspect that row's text.  A 500-char window leaks
                # into adjacent rows and finds the next gene's classification, causing
                # false WRONG_CLASSIFICATION.  Non-table lines (prose, headers) still
                # use the 500-char window because the classification can appear on a
                # following line within the same section.
                if line_text.lstrip().startswith("|"):
                    chunk = line_text.lower()
                else:
                    chunk = drug_text[match.end():match.end() + 500].lower()
                if "validated_target" in chunk and true_class != "validated_target":
                    issues.append({
                        "type": "WRONG_CLASSIFICATION",
                        "severity": "high",
                        "gene": gene,
                        "claimed": "validated_target",
                        "actual": true_class,
                    })
                    found_wrong = True
                elif "novel_candidate" in chunk and true_class != "novel_candidate":
                    issues.append({
                        "type": "WRONG_CLASSIFICATION",
                        "severity": "high",
                        "gene": gene,
                        "claimed": "novel_candidate",
                        "actual": true_class,
                    })
                    found_wrong = True

    # 3. Decimal rubric score detection (should be integers)
    # Use an explicit underscore-delimited allowlist so bare "combined score 0.999"
    # phrases (e.g. STRING PPI confidence values) are not matched.  The old pattern
    # r'(?:validated|exploratory|combined)[_ ](?:total|track|score)' matched space-
    # separated variants like "combined score 0.999" which is a PPI DB confidence
    # value, not a rubric field.  Fix-A: require underscore separator.
    decimal_scores = re.findall(
        r'\b(?:validated_total|exploratory_total|combined_total'
        r'|validated_track|exploratory_track|combined_track)[:\s]*(\d+\.\d+)',
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
        def _is_preclinical_phase(value: object) -> bool:
            if value is None:
                return True
            if isinstance(value, (int, float)):
                return value == 0
            text = str(value).strip().casefold()
            return text in {"", "0", "none", "null", "n/a", "na", "preclinical"}

        def _is_clinical_phase(value: object) -> bool:
            if isinstance(value, (int, float)):
                return value >= 1
            text = str(value).strip().casefold()
            if not text or text in {"0", "none", "null", "n/a", "na", "preclinical"}:
                return False
            phase_match = re.search(r"\b([1-4])\b", text)
            return bool(phase_match or "approved" in text)

        clinically_supported_names = {
            (entry.get("resolved_name") or "").strip().casefold()
            for entry in resolved
            if (entry.get("resolved_name") or "").strip()
            and _is_clinical_phase(entry.get("max_phase"))
        }
        for d in resolved:
            source = d.get("source", "")
            max_phase = d.get("max_phase")
            drug_name = (d.get("resolved_name") or "").strip()
            if not drug_name or len(drug_name) < 3:
                continue
            # Only check preclinical compounds from ChEMBL
            if (
                source == "chembl"
                and _is_preclinical_phase(max_phase)
                and drug_name.casefold() not in clinically_supported_names
            ):
                drug_name_esc = re.escape(drug_name)
                pattern = re.compile(
                    drug_name_esc + r'[^\n]{0,200}(?:(?:FDA\s+)?approved|Phase\s+[1-4])',
                    re.IGNORECASE,
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
        r"(?:\.json|\[from\s+[^\]]+\]|stage[123]_[A-Za-z0-9_\-]+)",
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
                "MUST reference an evidence filename (e.g. "
                "stage2_evidence.json, ot_<GENE>.json). Uncited "
                "statistics are treated as hallucinated."
            ),
        })

    # --- T3-T7: new hallucination flags (line-by-line scan) -------------------
    findings: list[dict] = []

    if evidence_dir.exists():
        drug_allowlist = _build_drug_allowlist(evidence_dir, resolved)
        moa_map = _build_moa_map(resolved)
        evidence_field_set = _build_evidence_field_set(evidence_dir)
    else:
        drug_allowlist = frozenset()
        moa_map = {}
        evidence_field_set = frozenset(_BASE_EVIDENCE_FIELDS)

    in_code_block = False
    in_evidence_section = False

    for line_no, line in enumerate(drug_text.splitlines(), start=1):
        stripped = line.strip()

        # Track fenced code blocks
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        # Track evidence-reference sections (carve-out for T4)
        if stripped.startswith("#") and _EVIDENCE_SECTION_RE.search(stripped):
            in_evidence_section = True
        elif stripped.startswith("#"):
            in_evidence_section = False

        # Table rows are carve-outs for T3/T6/T7
        if stripped.startswith("|"):
            continue

        # Universal carve-out: "not available in source data"
        if "not available in source data" in line.casefold():
            continue

        # T3: FABRICATED_DRUG_NAME
        findings.extend(_check_fabricated_drug_name(line, line_no, drug_allowlist))

        # T4: FABRICATED_FILE_REFERENCE
        findings.extend(_check_fabricated_file_reference(
            line, line_no, evidence_dir, in_evidence_section
        ))

        # T5: WRONG_APPROVAL_YEAR extension
        findings.extend(_check_wrong_approval_year_extended(line, line_no, resolved))

        # T6: UNGROUNDED_MECHANISM
        findings.extend(_check_ungrounded_mechanism(line, line_no, drug_allowlist, moa_map))

        # T7: UNANCHORED_SENTENCE
        findings.extend(_check_unanchored_sentence(line, line_no, evidence_field_set))

    total_checks = 14  # 9 original + 5 new (T3-T7)
    # ``valid`` and ``issue_count`` reflect only the legacy T1-T2 checks so that
    # existing callers (e.g. finalization validator) are not broken by the new
    # advisory T3-T7 findings.  ``findings`` is an additive diagnostic output.
    return json.dumps({
        "valid": len(issues) == 0,
        "total_checks": total_checks,
        "issue_count": len(issues),
        "issues": issues,
        "findings": findings,
    }, indent=2)


# ---------------------------------------------------------------------------
# Deterministic fail-closed finalization validator
# ---------------------------------------------------------------------------
# Robust prose patterns for Stage 1 count claims in drug.md. If `drug.md`
# makes any such claim, the captured number must match the total pair count
# in `stage1_filter_results.json`. If no claim matches, the check is a no-op.
STAGE1_COUNT_PATTERNS = [
    r"of\s+(\d+)\s+L[-\s]?R\s+pairs",
    r"of\s+(\d+)\s+ligand[-\s]?receptor\s+pairs",
    r"across\s+(\d+)\s+L[-\s]?R\s+pairs",
    r"across\s+(\d+)\s+ligand[-\s]?receptor\s+pairs",
    r"from\s+(\d+)\s+(?:L[-\s]?R\s+)?pairs",
]

# MoA cell values that count as explicitly unavailable (case-insensitive,
# trimmed). When a Drug Profile MoA cell matches one of these, the cell is
# treated as supported and no UNSUPPORTED_MOA_CLAIM issue is emitted.
_MOA_UNAVAILABLE_MARKERS = frozenset({
    "n/a",
    "na",
    "mechanism not available",
    "unknown",
    "not available",
    "data not available",  # Fix-B: placeholder seen in res_ipf_openai2 trace (drug.md:233)
    "not characterized",
})


def _count_unescaped_pipes(line: str) -> int:
    """Count `|` characters that are not preceded by a backslash."""
    count = 0
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch == "\\" and i + 1 < n and line[i + 1] == "|":
            # Skip the escaped pipe entirely.
            i += 2
            continue
        if ch == "|":
            count += 1
        i += 1
    return count


def _is_table_separator(line: str) -> bool:
    """A markdown separator row contains only `|`, `-`, `:`, and whitespace,
    and includes at least one `---` segment."""
    stripped = line.strip()
    if not stripped:
        return False
    if not all(ch in "|:- \t" for ch in stripped):
        return False
    return "---" in stripped


def _split_markdown_table_row(line: str) -> list[str]:
    """Split a markdown table row while preserving escaped pipe characters."""
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]

    cells: list[str] = []
    current: list[str] = []
    i = 0
    while i < len(stripped):
        ch = stripped[i]
        if ch == "\\" and i + 1 < len(stripped) and stripped[i + 1] == "|":
            current.append("|")
            i += 2
            continue
        if ch == "|":
            cells.append("".join(current).strip())
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1
    cells.append("".join(current).strip())
    return cells


def _check_markdown_table_pipe_drift(drug_text: str) -> list[dict]:
    """Detect markdown tables whose data rows have an inconsistent unescaped
    pipe count vs the header/separator. Each divergent row emits a single
    issue keyed on its line number."""
    issues: list[dict] = []
    lines = drug_text.splitlines()
    n = len(lines)
    i = 0
    while i < n:
        line = lines[i]
        stripped = line.strip()
        # A table block starts with a header row (pipe row) followed by a
        # separator row on the next line.
        is_pipe_row = stripped.startswith("|") and stripped.endswith("|") and "|" in stripped
        if not is_pipe_row or i + 1 >= n or not _is_table_separator(lines[i + 1]):
            i += 1
            continue
        header_pipes = _count_unescaped_pipes(line)
        sep_pipes = _count_unescaped_pipes(lines[i + 1])
        # Header vs separator drift counts as a single issue at the separator.
        if header_pipes != sep_pipes:
            issues.append({
                "code": "MARKDOWN_TABLE_PIPE_DRIFT",
                "severity": "high",
                "message": (
                    f"Table separator pipe count ({sep_pipes}) does not match "
                    f"header pipe count ({header_pipes})."
                ),
                "location": f"drug.md:{i + 2}",
                "evidence": {
                    "header_pipes": header_pipes,
                    "separator_pipes": sep_pipes,
                    "header_line": line.strip()[:200],
                    "separator_line": lines[i + 1].strip()[:200],
                },
            })
        # Walk data rows.
        j = i + 2
        while j < n:
            row = lines[j]
            row_stripped = row.strip()
            if not (row_stripped.startswith("|") and row_stripped.endswith("|")):
                break
            row_pipes = _count_unescaped_pipes(row)
            if row_pipes != header_pipes:
                issues.append({
                    "code": "MARKDOWN_TABLE_PIPE_DRIFT",
                    "severity": "high",
                    "message": (
                        f"Table row has {row_pipes} unescaped pipes; expected "
                        f"{header_pipes} (header)."
                    ),
                    "location": f"drug.md:{j + 1}",
                    "evidence": {
                        "header_pipes": header_pipes,
                        "row_pipes": row_pipes,
                        "row_line": row_stripped[:200],
                        "header_line": line.strip()[:200],
                    },
                })
            j += 1
        i = j if j > i + 1 else i + 1
    return issues


def _stage1_filter_results_path(data_dir_path: Path) -> Path | None:
    """Return the current Stage 1 filter artifact path.

    Current runs persist the JSON sidecar under ``evidence/``.  Legacy fixtures
    and older outputs kept it at the run root, so the root path remains a
    fallback for compatibility.
    """
    evidence_path = data_dir_path / "evidence" / "stage1_filter_results.json"
    if evidence_path.exists():
        return evidence_path
    legacy_path = data_dir_path / "stage1_filter_results.json"
    if legacy_path.exists():
        return legacy_path
    return None


def _check_stage1_count_mismatch(drug_text: str, data_dir_path: Path) -> list[dict]:
    """Compare any prose Stage 1 count claim in drug.md against the total
    pair count derived from stage1_filter_results.json. Skipped silently if
    the report makes no such claim."""
    issues: list[dict] = []
    stage1_path = _stage1_filter_results_path(data_dir_path)
    if stage1_path is None:
        return issues  # MISSING_REQUIRED_ARTIFACT path covers this case.
    try:
        stage1_payload = json.loads(stage1_path.read_text(encoding="utf-8"))
    except Exception as exc:
        issues.append({
            "code": "STAGE1_COUNT_MISMATCH",
            "severity": "high",
            "message": f"Failed to parse stage1_filter_results.json: {exc}",
            "location": str(stage1_path),
            "evidence": {},
        })
        return issues

    # Compute total = number of pair entries. The file shape is a dict that
    # commonly carries a list of pair entries under a top-level key like
    # `pairs` / `results` / `entries`, or it may itself be a list. Fall back
    # to summing pass+fail buckets when present.
    total: int | None = None
    if isinstance(stage1_payload, list):
        total = len(stage1_payload)
    elif isinstance(stage1_payload, dict):
        if isinstance(stage1_payload.get("total"), int):
            total = stage1_payload["total"]
        for key in ("pairs", "results", "entries", "stage1_pairs"):
            if total is not None:
                break
            value = stage1_payload.get(key)
            if isinstance(value, list):
                total = len(value)
                break
        if total is None:
            passed = stage1_payload.get("passed") or stage1_payload.get("pass")
            failed = stage1_payload.get("failed") or stage1_payload.get("fail")
            if isinstance(passed, list) and isinstance(failed, list):
                total = len(passed) + len(failed)
    if total is None:
        # Cannot determine the authoritative total — skip the check rather
        # than emit a spurious mismatch.
        return issues

    for pattern in STAGE1_COUNT_PATTERNS:
        for match in re.finditer(pattern, drug_text, re.IGNORECASE):
            try:
                claimed = int(match.group(1))
            except (TypeError, ValueError):
                continue
            if claimed == total:
                continue
            # Compute the line number of the match for `location`.
            line_no = drug_text.count("\n", 0, match.start()) + 1
            issues.append({
                "code": "STAGE1_COUNT_MISMATCH",
                "severity": "high",
                "message": (
                    f"drug.md claims {claimed} L-R pair(s) but "
                    f"stage1_filter_results.json contains {total}."
                ),
                "location": f"drug.md:{line_no}",
                "evidence": {
                    "claimed": claimed,
                    "actual": total,
                    "matched_phrase": match.group(0),
                    "pattern": pattern,
                },
            })
    return issues


def _check_empty_gap_analysis(drug_text: str) -> list[dict]:
    """Detect a `### Gap Analysis` heading whose body (until the next heading
    at the same or shallower depth) is whitespace-only or contains fewer than
    20 non-whitespace characters."""
    issues: list[dict] = []
    lines = drug_text.splitlines()
    heading_pattern = re.compile(r"^(#{1,6})\s+(.+?)\s*:?\s*$")
    target_pattern = re.compile(r"^gap\s+analysis$", re.IGNORECASE)
    for idx, line in enumerate(lines):
        match = heading_pattern.match(line.strip())
        if not match:
            continue
        depth = len(match.group(1))
        if depth != 3:
            continue
        title = match.group(2).rstrip(":").strip()
        if not target_pattern.match(title):
            continue
        # Walk forward until the next heading at depth <= 3.
        body_chars: list[str] = []
        j = idx + 1
        while j < len(lines):
            next_match = heading_pattern.match(lines[j].strip())
            if next_match and len(next_match.group(1)) <= depth:
                break
            body_chars.append(lines[j])
            j += 1
        body_text = "\n".join(body_chars)
        non_ws = re.sub(r"\s+", "", body_text)
        if len(non_ws) < 20:
            issues.append({
                "code": "EMPTY_GAP_ANALYSIS",
                "severity": "medium",
                "message": (
                    "### Gap Analysis section is empty or contains fewer than "
                    "20 non-whitespace characters."
                ),
                "location": f"drug.md:{idx + 1}",
                "evidence": {
                    "non_whitespace_char_count": len(non_ws),
                    "body_preview": body_text.strip()[:200],
                },
            })
    return issues


def _check_stale_hypothesis_report(drug_text: str, data_dir_path: Path) -> list[dict]:
    """Detect drug.md that predates a populated hypothesis_report.json."""
    drug_md_path = data_dir_path / "drug.md"
    hypothesis_path = data_dir_path / "evidence" / "hypothesis_report.json"
    if not drug_md_path.exists() or not hypothesis_path.exists():
        return []

    try:
        if hypothesis_path.stat().st_mtime <= drug_md_path.stat().st_mtime:
            return []
    except OSError:
        return []

    try:
        hypothesis_payload = json.loads(hypothesis_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [{
            "code": "STALE_HYPOTHESIS_REPORT",
            "severity": "high",
            "message": f"hypothesis_report.json is newer than drug.md but is unreadable: {exc}",
            "location": str(hypothesis_path),
            "evidence": {},
        }]

    hypotheses = hypothesis_payload.get("hypotheses", []) if isinstance(hypothesis_payload, dict) else []
    if not isinstance(hypotheses, list) or not hypotheses:
        return []

    placeholder_re = re.compile(
        r"No hypothesis(?:_report\.json)?(?: analysis)?(?: content)? (?:was )?(?:loaded|available)"
        r"|hypothesis_writer subagent may not have completed",
        re.IGNORECASE,
    )
    titles = [
        str(item.get("title", "")).strip()
        for item in hypotheses
        if isinstance(item, dict) and str(item.get("title", "")).strip()
    ]
    has_rendered_title = any(title in drug_text for title in titles)
    has_placeholder = bool(placeholder_re.search(drug_text))
    if has_placeholder or (titles and not has_rendered_title):
        return [{
            "code": "STALE_HYPOTHESIS_REPORT",
            "severity": "high",
            "message": (
                "hypothesis_report.json is newer than drug.md and the report "
                "does not render the final hypothesis content."
            ),
            "location": str(data_dir_path / "drug.md"),
            "evidence": {
                "hypothesis_report": str(hypothesis_path),
                "hypothesis_count": len(hypotheses),
                "sample_titles": titles[:3],
                "placeholder_text_present": has_placeholder,
            },
        }]
    return []


def _clean_markdown_cell_text(value: str) -> str:
    """Remove lightweight markdown decoration from a table cell."""
    value = value.strip()
    value = re.sub(r"^\*\*(.*?)\*\*$", r"\1", value)
    value = re.sub(r"^`(.*?)`$", r"\1", value)
    return value.strip()


def _column_index(header_cells: list[str], *needles: str) -> int | None:
    for idx, cell in enumerate(header_cells):
        normalized = cell.strip().lower()
        for needle in needles:
            if needle in normalized:
                return idx
    return None


def _iter_drug_profile_moa_cells(drug_text: str):
    """Yield `(line_no, drug_name, chembl_id, moa_value)` tuples for each MoA cell in
    every markdown table that exposes a MoA / Mechanism of Action column.

    The drug name is taken from an explicit drug/name column when available,
    falling back to the first non-empty cell. `line_no` is 1-indexed and points
    at the data row line.
    """
    lines = drug_text.splitlines()
    n = len(lines)
    i = 0
    while i < n:
        line = lines[i]
        stripped = line.strip()
        is_pipe_row = stripped.startswith("|") and stripped.endswith("|") and "|" in stripped
        if not is_pipe_row or i + 1 >= n or not _is_table_separator(lines[i + 1]):
            i += 1
            continue
        header_cells = [_clean_markdown_cell_text(c) for c in _split_markdown_table_row(stripped)]
        moa_idx = _column_index(header_cells, "mechanism of action", "moa")
        if moa_idx is None:
            i += 1
            continue
        chembl_idx = _column_index(header_cells, "chembl")
        drug_idx = _column_index(header_cells, "drug", "compound", "name")
        j = i + 2
        while j < n:
            row = lines[j]
            row_stripped = row.strip()
            if not (row_stripped.startswith("|") and row_stripped.endswith("|")):
                break
            cells = [_clean_markdown_cell_text(c) for c in _split_markdown_table_row(row_stripped)]
            if moa_idx < len(cells):
                moa_value = cells[moa_idx]
                drug_name = ""
                if drug_idx is not None and drug_idx < len(cells):
                    drug_name = cells[drug_idx]
                if not drug_name:
                    drug_name = next((cell for cell in cells if cell), "")
                chembl_id = ""
                if chembl_idx is not None and chembl_idx < len(cells):
                    chembl_id = cells[chembl_idx]
                yield (j + 1, drug_name, chembl_id, moa_value)
            j += 1
        i = j if j > i + 1 else i + 1


def _normalize_moa_support_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\\|", "|")).strip().casefold()


def _normalize_lookup_key(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _iter_stage3_drug_entries(payload: Any):
    """Yield drug-like entries from the Stage3 JSON formats used by the pipeline."""
    if not isinstance(payload, dict):
        return
    containers = [payload]
    chembl_payload = payload.get("chembl")
    if isinstance(chembl_payload, dict):
        containers.append(chembl_payload)

    for container in containers:
        for key in (
            "chembl_drugs",
            "matched_drugs",
            "preclinical_compounds",
            "chembl_records",
            "drugs",
            "clinical_drugs",
        ):
            entries = container.get(key)
            if isinstance(entries, dict):
                entries = entries.get("matched_drugs") or entries.get("rows") or []
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if isinstance(entry, dict):
                    yield entry


def _build_moa_support_map(data_dir_path: Path) -> dict[str, set[str]]:
    """Build drug/ChEMBL-specific MoA support from resolved_drugs and Stage3."""
    evidence_dir = data_dir_path / "evidence"
    support: dict[str, set[str]] = {}

    def add_entry(entry: dict[str, Any]) -> None:
        moa = _normalize_moa_support_text(entry.get("mechanism_of_action"))
        if not moa:
            return
        names = [
            entry.get("name"),
            entry.get("resolved_name"),
            entry.get("drug_name"),
            entry.get("pref_name"),
            entry.get("molecule_name"),
        ]
        ids = [
            entry.get("chembl_id"),
            entry.get("molecule_chembl_id"),
        ]
        for value in names + ids:
            key = _normalize_lookup_key(value)
            if key:
                support.setdefault(key, set()).add(moa)

    resolved_path = evidence_dir / "resolved_drugs.json"
    if resolved_path.exists():
        try:
            resolved_payload = json.loads(resolved_path.read_text(encoding="utf-8"))
        except Exception:
            resolved_payload = []
        if isinstance(resolved_payload, list):
            for entry in resolved_payload:
                if isinstance(entry, dict):
                    add_entry(entry)

    if evidence_dir.is_dir():
        for stage3_path in sorted(evidence_dir.glob("stage3_*.json")):
            try:
                stage3_payload = json.loads(stage3_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            for entry in _iter_stage3_drug_entries(stage3_payload):
                add_entry(entry)
    return support


def _check_unsupported_moa_claim(drug_text: str, data_dir_path: Path) -> list[dict]:
    """Each Drug Profile MoA cell must be either explicitly unavailable
    (N/A markers) or match MoA support for the same drug/ChEMBL ID."""
    issues: list[dict] = []
    moa_support = _build_moa_support_map(data_dir_path)
    for line_no, drug_name, chembl_id, moa_value in _iter_drug_profile_moa_cells(drug_text):
        normalized = _normalize_moa_support_text(moa_value)
        if not normalized:
            # Empty cells are treated as unavailable (no claim made).
            continue
        if normalized in _MOA_UNAVAILABLE_MARKERS:
            continue
        keys = [
            _normalize_lookup_key(chembl_id),
            _normalize_lookup_key(drug_name),
        ]
        supported_moas = set()
        for key in keys:
            if key:
                supported_moas.update(moa_support.get(key, set()))
        if any(normalized == moa or normalized in moa or moa in normalized for moa in supported_moas):
            continue
        issues.append({
            "code": "UNSUPPORTED_MOA_CLAIM",
            "severity": "medium",
            "message": (
                f"Drug Profile MoA cell for {drug_name or '<unknown>'} claims "
                f"'{moa_value}' but the value is absent from matching "
                "resolved_drugs.json or stage3 drug records and is not in the "
                "unavailable-marker set."
            ),
            "location": f"drug.md:{line_no}",
            "evidence": {
                "drug": drug_name,
                "chembl_id": chembl_id,
                "claimed_moa": moa_value,
            },
        })
    return issues


def _sha256_text(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _check_failed_suffix_leak(drug_text: str, data_dir_path: Path) -> list[dict]:
    if "_FAILED" not in drug_text:
        return []
    return [{
        "code": "FAILED_SUFFIX_LEAK",
        "severity": "high",
        "message": "_FAILED contrast marker leaked into final drug.md.",
        "location": str(data_dir_path / "drug.md"),
        "evidence": {"occurrences": drug_text.count("_FAILED")},
    }]


def _check_unverified_numeric_predictions(
    data_dir_path: Path,
    *,
    strict: bool,
) -> tuple[list[dict], list[dict]]:
    """Return (issues, warnings) for hypothesis prediction grounding."""
    hypothesis_path = data_dir_path / "evidence" / "hypothesis_report.json"
    if not hypothesis_path.exists():
        return [], []
    try:
        payload = json.loads(hypothesis_path.read_text(encoding="utf-8"))
    except Exception:
        return [], []
    summary = payload.get("prediction_grounding_summary")
    if not isinstance(summary, dict) or int(summary.get("unverified", 0) or 0) <= 0:
        return [], []
    item = {
        "code": "UNVERIFIED_NUMERIC_PREDICTION",
        "severity": "high" if strict else "warning",
        "message": "hypothesis_report.json contains unverified numeric predictions.",
        "location": str(hypothesis_path),
        "evidence": summary,
    }
    return ([item], []) if strict else ([], [item])


def _check_renderer_metadata(data_dir_path: Path, drug_text: str) -> list[dict]:
    """Validate renderer sidecars when renderer mode is active or required."""
    import os

    issues: list[dict] = []
    metadata_path = data_dir_path / "drug_report_render.json"
    reference_path = data_dir_path / "drug_report_reference_card.json"
    expansions_path = data_dir_path / "report_expansions.json"
    sidecars_present = any(p.exists() for p in (metadata_path, reference_path, expansions_path))
    require_renderer = os.getenv("DEEPMAST_REQUIRE_RENDERER") == "1"
    if not sidecars_present and not require_renderer:
        if os.getenv("DEEPMAST_ALLOW_LEGACY_DRUG_MD") == "1":
            return issues
        return [{
            "code": "MISSING_RENDER_METADATA",
            "severity": "critical",
            "message": (
                "drug_report_render.json is required for markdown publication; "
                "set DEEPMAST_ALLOW_LEGACY_DRUG_MD=1 only for explicit legacy compatibility."
            ),
            "location": str(metadata_path),
            "evidence": {"legacy_compat_allowed": False},
        }]
    if not metadata_path.exists():
        # DEEPMAST_ALLOW_LEGACY_DRUG_MD=1 skips this check for the legacy save_drug_md flow
        # which does not produce drug_report_render.json. Renderer pipeline path is unaffected:
        # when report_expansions.json is present the renderer is active and the check must fire.
        # See plan R7 / D10.
        if os.getenv("DEEPMAST_ALLOW_LEGACY_DRUG_MD") == "1" and not expansions_path.exists():
            return issues  # legacy save_drug_md flow — skip render-metadata check
        return [{
            "code": "MISSING_RENDER_METADATA",
            "severity": "critical",
            "message": "drug_report_render.json is required when renderer sidecars exist.",
            "location": str(metadata_path),
            "evidence": {},
        }]
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [{
            "code": "RENDER_METADATA_INVALID",
            "severity": "critical",
            "message": f"drug_report_render.json is unreadable: {exc}",
            "location": str(metadata_path),
            "evidence": {},
        }]
    if metadata.get("schema_version") != "drug_report_render.v1":
        issues.append({
            "code": "RENDER_METADATA_INVALID",
            "severity": "critical",
            "message": "drug_report_render.json has an invalid schema_version.",
            "location": str(metadata_path),
            "evidence": {"schema_version": metadata.get("schema_version")},
        })
    if (
        metadata.get("mode") == "legacy_compat"
        and os.getenv("DEEPMAST_ALLOW_LEGACY_DRUG_MD") != "1"
    ):
        issues.append({
            "code": "LEGACY_RENDER_MODE_NOT_ALLOWED",
            "severity": "critical",
            "message": "legacy render mode requires DEEPMAST_ALLOW_LEGACY_DRUG_MD=1.",
            "location": str(metadata_path),
            "evidence": {"mode": metadata.get("mode")},
        })
    source_hashes = metadata.get("source_hashes")
    if not isinstance(source_hashes, dict):
        source_hashes = {}
    if (
        metadata.get("mode") == "renderer"
        or metadata.get("renderer") == "render_drug_md_from_expansions"
    ):
        for source_path, artifact, hash_key in (
            (
                reference_path,
                "drug_report_reference_card.json",
                "reference_card",
            ),
            (
                expansions_path,
                "report_expansions.json",
                "report_expansions",
            ),
        ):
            if not source_path.exists():
                issues.append({
                    "code": "MISSING_RENDER_SOURCE",
                    "severity": "critical",
                    "message": f"{artifact} is required by renderer metadata.",
                    "location": str(source_path),
                    "evidence": {
                        "artifact": artifact,
                        "expected_hash": source_hashes.get(hash_key),
                    },
                })
    try:
        from src.agents.drug_target.tools.report_expansion_schema import (
            canonical_json_hash,
            validate_report_expansions,
        )

        if reference_path.exists():
            actual = canonical_json_hash(json.loads(reference_path.read_text(encoding="utf-8")))
            if source_hashes.get("reference_card") != actual:
                issues.append({
                    "code": "RENDER_SOURCE_HASH_MISMATCH",
                    "severity": "critical",
                    "message": "reference card hash differs from renderer metadata.",
                    "location": str(reference_path),
                    "evidence": {
                        "expected": source_hashes.get("reference_card"),
                        "actual": actual,
                    },
                })
        if expansions_path.exists():
            expansions = json.loads(expansions_path.read_text(encoding="utf-8"))
            actual = canonical_json_hash(expansions)
            if source_hashes.get("report_expansions") != actual:
                issues.append({
                    "code": "RENDER_SOURCE_HASH_MISMATCH",
                    "severity": "critical",
                    "message": "report_expansions hash differs from renderer metadata.",
                    "location": str(expansions_path),
                    "evidence": {
                        "expected": source_hashes.get("report_expansions"),
                        "actual": actual,
                    },
                })
            _, expansion_errors = validate_report_expansions(data_dir_path, expansions)
            for error in expansion_errors:
                issues.append({
                    "code": error.get("code", "REPORT_EXPANSIONS_INVALID"),
                    "severity": "critical",
                    "message": error.get("message", "report expansions invalid"),
                    "location": str(expansions_path),
                    "evidence": error,
                })
    except Exception as exc:
        issues.append({
            "code": "RENDER_METADATA_INVALID",
            "severity": "critical",
            "message": f"Failed to validate renderer source hashes: {exc}",
            "location": str(metadata_path),
            "evidence": {},
        })
    rendered_hash = metadata.get("rendered_drug_md_sha256")
    actual_rendered_hash = _sha256_text(drug_text)
    if rendered_hash and rendered_hash != actual_rendered_hash:
        issues.append({
            "code": "RENDERED_DRUG_MD_HASH_MISMATCH",
            "severity": "critical",
            "message": "drug.md hash differs from renderer metadata.",
            "location": str(data_dir_path / "drug.md"),
            "evidence": {"expected": rendered_hash, "actual": actual_rendered_hash},
        })
    if metadata.get("missing_slots") or metadata.get("extra_slots"):
        issues.append({
            "code": "REPORT_EXPANSIONS_INVALID",
            "severity": "critical",
            "message": "renderer metadata reports missing or extra expansion slots.",
            "location": str(metadata_path),
            "evidence": {
                "missing_slots": metadata.get("missing_slots"),
                "extra_slots": metadata.get("extra_slots"),
            },
        })
    return issues


_BLOCKING_VALIDATE_DRUG_MD_FINDINGS: frozenset[str] = frozenset({
    "FABRICATED_DRUG_NAME",
    "FABRICATED_FILE_REFERENCE",
    "WRONG_APPROVAL_YEAR",
    "PRECLINICAL_CALLED_APPROVED",
    "UNSUPPORTED_CLINICAL_STATUS",
    "UNGROUNDED_MECHANISM",
    "UNANCHORED_SENTENCE",
    "SOURCE_PROVENANCE_MISSING",
    "SOURCE_PROVENANCE_MISMATCH",
})

_RENDERER_SCOPED_PROSE_FINDINGS: frozenset[str] = frozenset({
    "FABRICATED_DRUG_NAME",
    "UNGROUNDED_MECHANISM",
    "UNANCHORED_SENTENCE",
})


def _normalized_text_fragment(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _load_renderer_expansion_texts(data_dir_path: Path) -> tuple[str, ...]:
    expansions_path = data_dir_path / "report_expansions.json"
    if not expansions_path.exists():
        return ()
    try:
        payload = json.loads(expansions_path.read_text(encoding="utf-8"))
    except Exception:
        return ()
    texts: list[str] = []
    slots = payload.get("slots", []) if isinstance(payload, dict) else []
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        for sentence in slot.get("sentences", []) or []:
            if not isinstance(sentence, dict):
                continue
            text = _normalized_text_fragment(sentence.get("text"))
            if text:
                texts.append(text)
    return tuple(texts)


def _finding_matches_renderer_expansion(
    finding: dict,
    expansion_texts: tuple[str, ...],
) -> bool:
    snippet = _normalized_text_fragment(finding.get("snippet"))
    if not snippet:
        return False
    return any(snippet in text or text in snippet for text in expansion_texts)


def _check_disease_scope_note(drug_text: str, data_dir_path: Path) -> list[dict]:
    reference_path = data_dir_path / "drug_report_reference_card.json"
    if not reference_path.exists():
        return []
    try:
        reference = json.loads(reference_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [{
            "code": "DISEASE_SCOPE_METADATA_INVALID",
            "severity": "critical",
            "message": f"Failed to parse drug_report_reference_card.json: {exc}",
            "location": str(reference_path),
            "evidence": {},
        }]
    scope = reference.get("disease_scope") if isinstance(reference, dict) else None
    if not isinstance(scope, dict) or scope.get("requires_proxy_note") is not True:
        return []
    note = str(scope.get("proxy_note") or "").strip()
    if not note or _normalized_text_fragment(note) not in _normalized_text_fragment(drug_text):
        return [{
            "code": "MISSING_DISEASE_SCOPE_NOTE",
            "severity": "critical",
            "message": (
                "Section 4 requires an explicit disease proxy/scope note because "
                "the evidence disease scope differs from the requested report disease."
            ),
            "location": str(data_dir_path / "drug.md"),
            "evidence": {
                "requested_disease": scope.get("requested_disease"),
                "evidence_diseases": scope.get("evidence_diseases"),
                "expected_note": note,
            },
        }]
    return []


def _critic_finalization_issues(data_dir_path: Path) -> tuple[dict, list[dict]]:
    """Return critic check details and blocking issues for require_critic=True."""
    critic_path = data_dir_path / "evidence" / "critic_report.json"
    check: dict[str, object] = {
        "status": "fail",
        "path": str(critic_path),
        "raw": {},
    }
    issues: list[dict] = []
    if not critic_path.exists():
        issues.append({
            "code": "MISSING_CRITIC_REPORT",
            "severity": "critical",
            "message": "require_critic=True but evidence/critic_report.json is missing.",
            "location": str(critic_path),
            "evidence": {},
        })
        return check, issues
    try:
        raw = json.loads(critic_path.read_text(encoding="utf-8"))
    except Exception as exc:
        issues.append({
            "code": "CRITIC_REPORT_INVALID",
            "severity": "critical",
            "message": f"critic_report.json is not parseable JSON: {exc}",
            "location": str(critic_path),
            "evidence": {},
        })
        return check, issues
    if not isinstance(raw, dict):
        issues.append({
            "code": "CRITIC_REPORT_INVALID",
            "severity": "critical",
            "message": "critic_report.json must be a JSON object.",
            "location": str(critic_path),
            "evidence": {"type": type(raw).__name__},
        })
        return check, issues

    check["raw"] = raw
    if raw.get("passed") is not True:
        issues.append({
            "code": "CRITIC_REPORT_FAILED",
            "severity": "critical",
            "message": "Critic report did not pass.",
            "location": str(critic_path),
            "evidence": {"passed": raw.get("passed")},
        })

    for finding in raw.get("findings", []) or []:
        if isinstance(finding, dict) and finding.get("severity") in {"P0", "P1"}:
            issues.append({
                "code": "CRITIC_BLOCKING_FINDING",
                "severity": "critical",
                "message": "Critic report contains a P0/P1 finding.",
                "location": str(critic_path),
                "evidence": finding,
            })

    for verdict in raw.get("claim_verdicts", []) or []:
        if isinstance(verdict, dict) and verdict.get("verdict") == "FAIL":
            issues.append({
                "code": "CRITIC_CLAIM_VERDICT_FAILED",
                "severity": "critical",
                "message": "Critic report contains a failed claim verdict.",
                "location": str(critic_path),
                "evidence": verdict,
            })

    if not issues:
        check["status"] = "pass"
    return check, issues


@tool
def validate_drug_report_finalization(data_dir: str, require_critic: bool = False) -> str:
    """Deterministic fail-closed finalization validator for drug.md.

    Composes the existing `validate_drug_md` and `validate_target_assessment_file`
    checks with four additional finalization-only checks:
    `MARKDOWN_TABLE_PIPE_DRIFT`, `STAGE1_COUNT_MISMATCH`, `EMPTY_GAP_ANALYSIS`,
    and `UNSUPPORTED_MOA_CLAIM`.

    The validator MUST NOT call `_resolve_data_dir` and MUST NOT consult any
    env var. Path resolution is strictly `Path(data_dir).expanduser().resolve()`.
    A missing or invalid `data_dir` fails the validator (no env fallback).

    Returns a JSON string with the schema documented in the rev2 plan.
    """
    issues: list[dict] = []
    checks: dict[str, dict] = {
        "data_dir": {"status": "fail", "path": ""},
        "required_artifacts": {"status": "fail", "missing": []},
        "validate_drug_md": {"status": "fail", "raw": {}},
        "target_assessment": {"status": "fail", "issues": []},
        "report_finalization": {"status": "fail", "issues": [], "warnings": []},
        "critic": {"status": "skipped", "path": "", "raw": {}},
    }

    # ------------------------------------------------------------------
    # 1. Path validation — fail closed, no env fallback.
    # ------------------------------------------------------------------
    try:
        data_dir_path = Path(data_dir).expanduser().resolve()
    except Exception as exc:
        checks["data_dir"] = {"status": "fail", "path": str(data_dir)}
        issues.append({
            "code": "INVALID_DATA_DIR",
            "severity": "critical",
            "message": f"Failed to resolve data_dir: {exc}",
            "location": str(data_dir),
            "evidence": {},
        })
        return json.dumps({
            "valid": False,
            "issue_count": len(issues),
            "issues": issues,
            "checks": checks,
            "sources": [],
        }, indent=2)

    checks["data_dir"]["path"] = str(data_dir_path)

    invalid_reason: str | None = None
    if not data_dir_path.exists():
        invalid_reason = "data_dir does not exist"
    elif not data_dir_path.is_dir():
        invalid_reason = "data_dir is not a directory"
    elif str(data_dir_path) == "/":
        invalid_reason = "data_dir is the filesystem root"
    elif (data_dir_path / ".git").is_dir():
        invalid_reason = (
            "data_dir is the repository root (contains .git/); "
            "expected a per-run output directory"
        )

    if invalid_reason is not None:
        issues.append({
            "code": "INVALID_DATA_DIR",
            "severity": "critical",
            "message": invalid_reason,
            "location": str(data_dir_path),
            "evidence": {"path": str(data_dir_path)},
        })
        return json.dumps({
            "valid": False,
            "issue_count": len(issues),
            "issues": issues,
            "checks": checks,
            "sources": [],
        }, indent=2)

    checks["data_dir"]["status"] = "pass"

    # ------------------------------------------------------------------
    # 2. Required artifacts (all unconditional per MR4).
    # ------------------------------------------------------------------
    required_artifacts = [
        "drug.md",
        "target_assessment.json",
        "evidence/assessment_results.json",
        "stage1_filter_results.json",
    ]
    missing: list[str] = []
    for rel in required_artifacts:
        artifact_path = data_dir_path / rel
        if rel == "stage1_filter_results.json":
            resolved_stage1_path = _stage1_filter_results_path(data_dir_path)
            if resolved_stage1_path is not None:
                continue
            artifact_path = data_dir_path / "evidence" / rel
        if not artifact_path.exists():
            missing.append(rel)
            issues.append({
                "code": "MISSING_REQUIRED_ARTIFACT",
                "severity": "critical",
                "message": f"Required artifact not found: {rel}",
                "location": str(artifact_path),
                "evidence": {"artifact": rel},
            })
    checks["required_artifacts"]["missing"] = missing
    checks["required_artifacts"]["status"] = "pass" if not missing else "fail"

    # ------------------------------------------------------------------
    # 3. validate_drug_md — pass the resolved Path so _resolve_data_dir
    #    is bypassed (per MR1 dual-input contract).
    # ------------------------------------------------------------------
    drug_md_present = (data_dir_path / "drug.md").exists()
    if drug_md_present:
        try:
            impl: Any = getattr(validate_drug_md, "func", None) or validate_drug_md
            raw_json = impl(data_dir_path)
            raw = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
        except Exception as exc:
            raw = {"valid": False, "error": f"validate_drug_md raised: {exc}"}
        checks["validate_drug_md"]["raw"] = raw if isinstance(raw, dict) else {}
        if raw.get("valid", False):
            checks["validate_drug_md"]["status"] = "pass"
        else:
            checks["validate_drug_md"]["status"] = "fail"
            issues.append({
                "code": "VALIDATE_DRUG_MD_FAILED",
                "severity": "high",
                "message": (
                    f"validate_drug_md returned valid=false with "
                    f"{raw.get('issue_count', 'unknown')} issue(s)."
                ),
                "location": str(data_dir_path / "drug.md"),
                "evidence": {
                    "issues": raw.get("issues", []),
                    "error": raw.get("error"),
                },
            })
        import os

        renderer_mode_active = any(
            (data_dir_path / rel).exists()
            for rel in (
                "drug_report_render.json",
                "drug_report_reference_card.json",
                "report_expansions.json",
            )
        )
        renderer_expansion_texts = (
            _load_renderer_expansion_texts(data_dir_path)
            if renderer_mode_active
            else ()
        )
        block_findings = (
            require_critic
            or renderer_mode_active
            or os.getenv("DEEPMAST_ALLOW_LEGACY_DRUG_MD") != "1"
        )
        if block_findings:
            for finding in raw.get("findings", []) or []:
                if not isinstance(finding, dict):
                    continue
                finding_type = str(finding.get("type") or "")
                if finding_type not in _BLOCKING_VALIDATE_DRUG_MD_FINDINGS:
                    continue
                if (
                    renderer_mode_active
                    and finding_type in _RENDERER_SCOPED_PROSE_FINDINGS
                    and not _finding_matches_renderer_expansion(
                        finding,
                        renderer_expansion_texts,
                    )
                ):
                    continue
                issues.append({
                    "code": "VALIDATE_DRUG_MD_BLOCKING_FINDING",
                    "severity": "critical",
                    "message": f"validate_drug_md reported blocking finding: {finding_type}",
                    "location": str(data_dir_path / "drug.md"),
                    "evidence": finding,
                })

    # ------------------------------------------------------------------
    # 4. target_assessment.json contract.
    # ------------------------------------------------------------------
    ta_path = data_dir_path / "target_assessment.json"
    if not ta_path.exists():
        issues.append({
            "code": "MISSING_TARGET_ASSESSMENT",
            "severity": "critical",
            "message": "target_assessment.json not found.",
            "location": str(ta_path),
            "evidence": {},
        })
        checks["target_assessment"]["status"] = "fail"
        checks["target_assessment"]["issues"] = ["target_assessment.json not found"]
    else:
        try:
            from src.agents.drug_target.tools.assessment_output import (
                validate_target_assessment_file,
            )
            ta_result = validate_target_assessment_file(data_dir_path)
        except Exception as exc:
            ta_result = {"valid": False, "errors": [f"validator raised: {exc}"]}
        ta_errors = list(ta_result.get("errors", []))
        checks["target_assessment"]["issues"] = ta_errors
        if ta_result.get("valid", False):
            checks["target_assessment"]["status"] = "pass"
        else:
            checks["target_assessment"]["status"] = "fail"
            issues.append({
                "code": "TARGET_ASSESSMENT_INVALID",
                "severity": "high",
                "message": "target_assessment.json failed contract validation.",
                "location": str(ta_path),
                "evidence": {"errors": ta_errors[:20]},
            })

    # ------------------------------------------------------------------
    # 5. Report finalization checks (markdown structure + content).
    # ------------------------------------------------------------------
    finalization_issues: list[dict] = []
    numeric_warnings: list[dict] = []
    if drug_md_present:
        try:
            drug_text = (data_dir_path / "drug.md").read_text(encoding="utf-8")
        except Exception as exc:
            finalization_issues.append({
                "code": "VALIDATE_DRUG_MD_FAILED",
                "severity": "high",
                "message": f"Failed to read drug.md for finalization checks: {exc}",
                "location": str(data_dir_path / "drug.md"),
                "evidence": {},
            })
            drug_text = ""

        if drug_text:
            finalization_issues.extend(_check_markdown_table_pipe_drift(drug_text))
            finalization_issues.extend(
                _check_stage1_count_mismatch(drug_text, data_dir_path)
            )
            finalization_issues.extend(_check_empty_gap_analysis(drug_text))
            finalization_issues.extend(
                _check_stale_hypothesis_report(drug_text, data_dir_path)
            )
            finalization_issues.extend(
                _check_unsupported_moa_claim(drug_text, data_dir_path)
            )
            finalization_issues.extend(_check_failed_suffix_leak(drug_text, data_dir_path))
            finalization_issues.extend(_check_disease_scope_note(drug_text, data_dir_path))
            finalization_issues.extend(
                _check_renderer_metadata(drug_text=drug_text, data_dir_path=data_dir_path)
            )
            import os

            numeric_issues, numeric_warnings = _check_unverified_numeric_predictions(
                data_dir_path,
                strict=os.getenv("DEEPMAST_STRICT_NUMERIC_PREDICTIONS") == "1",
            )
            finalization_issues.extend(numeric_issues)

    checks["report_finalization"]["issues"] = [
        f"{i['code']} @ {i.get('location', '')}: {i.get('message', '')}"
        for i in finalization_issues
    ]
    checks["report_finalization"]["warnings"] = [
        f"{i['code']} @ {i.get('location', '')}: {i.get('message', '')}"
        for i in numeric_warnings
    ]
    checks["report_finalization"]["status"] = "pass" if not finalization_issues else "fail"
    issues.extend(finalization_issues)

    if require_critic:
        critic_check, critic_issues = _critic_finalization_issues(data_dir_path)
        checks["critic"] = critic_check
        issues.extend(critic_issues)

    # ------------------------------------------------------------------
    # 6. Final verdict.
    # ------------------------------------------------------------------
    return json.dumps({
        "valid": len(issues) == 0,
        "issue_count": len(issues),
        "issues": issues,
        "checks": checks,
        "sources": [],
    }, indent=2)
