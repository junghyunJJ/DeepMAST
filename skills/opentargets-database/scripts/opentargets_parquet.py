#!/usr/bin/env python3
"""Local Parquet reader for Open Targets Platform data.

Mirrors the function signatures and return structures of query_opentargets.py
but reads from local Parquet files in data/ot_data/ instead of calling the API.

Expected directory layout (relative to project root):
    data/ot_data/
        target/   (partitioned parquet, ~94MB)
        disease/  (single file disease.parquet, ~4.6MB)
        evidence/ (partitioned by sourceId, ~7.9GB)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)

# ── Data directory ────────────────────────────────────────────────────
DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "ot_data"

# ── Module-level caches (loaded once on first use) ────────────────────
_target_df: pd.DataFrame | None = None
_disease_df: pd.DataFrame | None = None
_target_evidence_cache: dict[str, pd.DataFrame] = {}
_known_drugs_cache: dict[str, Dict[str, Any]] = {}


# ══════════════════════════════════════════════════════════════════════
# Availability check
# ══════════════════════════════════════════════════════════════════════

def is_available() -> bool:
    """Return True if ot_data/ has target, disease, and evidence dirs."""
    try:
        target_ok = (DATA_DIR / "target").is_dir() and any((DATA_DIR / "target").glob("*.parquet"))
        disease_ok = (DATA_DIR / "disease").is_dir() and any((DATA_DIR / "disease").glob("*.parquet"))
        evidence_ok = (DATA_DIR / "evidence").is_dir() and any((DATA_DIR / "evidence").iterdir())
        return target_ok and disease_ok and evidence_ok
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════
# Internal loaders
# ══════════════════════════════════════════════════════════════════════

def _load_targets() -> pd.DataFrame:
    """Load target parquet into memory (~94MB). Cached after first call."""
    global _target_df
    if _target_df is not None:
        return _target_df
    logger.info("Loading target parquet from %s", DATA_DIR / "target")
    _target_df = pq.read_table(DATA_DIR / "target").to_pandas()
    return _target_df


def _load_diseases() -> pd.DataFrame:
    """Load disease parquet into memory (~4.6MB). Cached after first call."""
    global _disease_df
    if _disease_df is not None:
        return _disease_df
    logger.info("Loading disease parquet from %s", DATA_DIR / "disease")
    _disease_df = pq.read_table(DATA_DIR / "disease").to_pandas()
    return _disease_df


def _to_native(val: Any) -> Any:
    """Recursively convert numpy/pandas types to JSON-serializable Python natives."""
    if val is None:
        return None
    # numpy array (ndarray) — must check before .item() since arrays also have it
    if hasattr(val, "ndim") and hasattr(val, "tolist") and not isinstance(val, str):
        if val.ndim == 0:
            # 0-d array (scalar wrapper)
            return val.item()
        return [_to_native(v) for v in val.tolist()]
    # numpy scalar (int64, float64, bool_, etc.) — has .item() but no .ndim or ndim==0
    if hasattr(val, "item") and not hasattr(val, "__len__"):
        return val.item()
    if isinstance(val, dict):
        return {str(k): _to_native(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_to_native(v) for v in val]
    if isinstance(val, (bytes, bytearray)):
        return val.decode("utf-8", errors="replace")
    return val


def _struct_list_to_dicts(val: Any) -> list[dict]:
    """Convert a numpy array of dicts (from parquet struct list) to plain list[dict]."""
    return _to_native(val) if val is not None else []


def _disease_id_to_name(disease_ids: list[str]) -> dict[str, str]:
    """Map disease IDs to names using the disease parquet."""
    if not disease_ids:
        return {}
    df = _load_diseases()
    matched = df[df["id"].isin(disease_ids)][["id", "name"]]
    return dict(zip(matched["id"], matched["name"]))


def _build_target_info_base(row: pd.Series) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "approvedSymbol": str(row.get("approvedSymbol", "")),
        "approvedName": str(row.get("approvedName", "")),
        "biotype": str(row.get("biotype", "")),
        "functionDescriptions": _to_native(_to_list(row.get("functionDescriptions"))),
        "tractability": _struct_list_to_dicts(row.get("tractability")),
        "safetyLiabilities": _struct_list_to_dicts(row.get("safetyLiabilities")),
        "geneticConstraint": _struct_list_to_dicts(row.get("constraint")),
    }


def _get_target_evidence_df(ensembl_id: str) -> pd.DataFrame:
    cached = _target_evidence_cache.get(ensembl_id)
    if cached is not None:
        return cached

    table = pq.read_table(
        DATA_DIR / "evidence",
        columns=[
            "targetId",
            "diseaseId",
            "score",
            "datatypeId",
            "datasourceId",
            "targetFromSourceId",
            "studyId",
            "literature",
            "cohortPhenotypes",
            "drugId",
            "clinicalPhase",
        ],
        filters=[("targetId", "=", ensembl_id)],
    )
    cached = table.to_pandas()
    _target_evidence_cache[ensembl_id] = cached
    return cached


def _build_associated_diseases(ev: pd.DataFrame) -> dict[str, Any]:
    if len(ev) == 0:
        return {"rows": []}

    agg = ev.groupby("diseaseId")["score"].max().sort_values(ascending=False).head(10)
    disease_names = _disease_id_to_name(list(agg.index))
    rows = []
    for did, sc in agg.items():
        rows.append({
            "disease": {"id": did, "name": disease_names.get(did, did)},
            "score": round(float(sc), 4),
        })
    return {"rows": rows}


def _build_target_disease_records(
    ev: pd.DataFrame,
    efo_id: str,
    datasource_ids: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    if len(ev) == 0:
        return []

    disease_df = ev[ev["diseaseId"] == efo_id]
    if datasource_ids:
        allowed = set(datasource_ids)
        disease_df = disease_df[disease_df["datasourceId"].isin(allowed)]
    if len(disease_df) == 0:
        return []

    # Diversity-aware sampling: ensure each datatypeId is represented
    if "datatypeId" in disease_df.columns and disease_df["datatypeId"].nunique() > 1:
        per_type = (
            disease_df.groupby("datatypeId", group_keys=False)
            .apply(lambda g: g.nlargest(min(5, len(g)), "score"))
        )
        remaining_idx = disease_df.index.difference(per_type.index)
        filler = disease_df.loc[remaining_idx].nlargest(
            max(0, 100 - len(per_type)), "score"
        )
        disease_df = pd.concat([per_type, filler])
        disease_df = disease_df[~disease_df.index.duplicated(keep="first")].head(100)
    else:
        disease_df = disease_df.sort_values("score", ascending=False).head(100)
    records = []
    for _, row in disease_df.iterrows():
        rec = {
            "datasourceId": row.get("datasourceId"),
            "datatypeId": row.get("datatypeId"),
            "score": float(row["score"]) if pd.notna(row.get("score")) else 0.0,
            "targetFromSourceId": row.get("targetFromSourceId"),
            "studyId": row.get("studyId"),
        }
        lit = row.get("literature")
        if lit is not None:
            rec["literature"] = _to_list(lit)
        cohort = row.get("cohortPhenotypes")
        if cohort is not None:
            rec["cohortPhenotypes"] = _to_list(cohort)
        if pd.notna(row.get("drugId")):
            rec["drugId"] = row["drugId"]
        if pd.notna(row.get("clinicalPhase")):
            rec["clinicalPhase"] = int(row["clinicalPhase"])
        records.append(rec)
    return records


def _build_target_associations(
    ev: pd.DataFrame, min_score: float
) -> Dict[str, Any]:
    """Build disease associations from parquet evidence.

    Returns dict with keys:
      - associations: list of per-disease aggregated records (max top-500 by score)
      - pre_head_len: count of diseases matching `min_score` BEFORE head cap
        (the authoritative total for novelty scoring)
    """
    if len(ev) == 0:
        return {"associations": [], "pre_head_len": 0}

    agg = ev.groupby("diseaseId")["score"].max().reset_index()
    filtered = agg[agg["score"] >= min_score].sort_values(
        "score", ascending=False
    )
    pre_head_len = len(filtered)
    # Raise head cap 100 → 500 to match the GraphQL path (A0). The CCI
    # L-R gene panel has 5+ receptors in the 100-299 range where a 100-cap
    # silently drops 50-60% of disease evidence before `_score_biological_plausibility`
    # ever sees it.
    agg = filtered.head(500)
    if len(agg) == 0:
        return {"associations": [], "pre_head_len": pre_head_len}

    dtype_scores = ev.groupby(["diseaseId", "datatypeId"])["score"].max().reset_index()
    disease_names = _disease_id_to_name(list(agg["diseaseId"]))

    results = []
    for _, row in agg.iterrows():
        did = row["diseaseId"]
        ds = dtype_scores[dtype_scores["diseaseId"] == did]
        dt_scores = [
            {"id": r["datatypeId"], "score": round(float(r["score"]), 4)}
            for _, r in ds.iterrows()
        ]
        results.append({
            "disease": {"id": did, "name": disease_names.get(did, did)},
            "score": round(float(row["score"]), 4),
            "datatypeScores": dt_scores,
        })
    return {"associations": results, "pre_head_len": pre_head_len}


def get_target_bundle(
    ensembl_id: str,
    efo_id: Optional[str] = None,
    min_score: float = 0.0,
    datasource_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Read evidence once for a target and derive all Stage 2 views."""
    tdf = _load_targets()
    row_df = tdf[tdf["id"] == ensembl_id]
    if len(row_df) == 0:
        return {
            "target_info": {},
            "disease_evidence": [],
            "associations": [],
            "associations_api_total_count": 0,
        }

    row = row_df.iloc[0]
    target_info = _build_target_info_base(row)

    try:
        ev = _get_target_evidence_df(ensembl_id)
    except Exception as exc:
        logger.warning("Failed to read target evidence for %s: %s", ensembl_id, exc)
        return {
            "target_info": target_info,
            "disease_evidence": [],
            "associations": [],
            "associations_api_total_count": 0,
        }

    target_info["associatedDiseases"] = _build_associated_diseases(ev)
    disease_evidence = (
        _build_target_disease_records(ev, efo_id, datasource_ids=datasource_ids)
        if efo_id
        else []
    )
    assoc_result = _build_target_associations(ev, min_score=min_score)
    return {
        "target_info": target_info,
        "disease_evidence": disease_evidence,
        "associations": assoc_result["associations"],
        # Key name mirrors the GraphQL async path in query_opentargets.py so
        # stage2_service can read `associations_api_total_count` uniformly.
        "associations_api_total_count": assoc_result["pre_head_len"],
    }


# ══════════════════════════════════════════════════════════════════════
# Public API — mirrors query_opentargets.py signatures
# ══════════════════════════════════════════════════════════════════════

def search_entities(
    query_string: str, entity_types: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """Search for targets and/or diseases by name.

    Target: approvedSymbol exact match → case-insensitive contains fallback.
    Disease: name exact match → contains match → synonyms match.
    """
    results: list[dict] = []
    types = [t.lower() for t in entity_types] if entity_types else ["target", "disease"]

    if "target" in types:
        tdf = _load_targets()
        query_upper = query_string.upper()
        # Exact symbol match
        exact = tdf[tdf["approvedSymbol"] == query_upper]
        if len(exact) == 0:
            # Case-insensitive contains fallback
            exact = tdf[tdf["approvedSymbol"].str.contains(query_string, case=False, na=False)]
        for _, row in exact.head(10).iterrows():
            results.append({
                "id": row["id"],
                "entity": "target",
                "name": row.get("approvedSymbol", ""),
                "description": row.get("approvedName", ""),
            })

    if "disease" in types:
        ddf = _load_diseases()
        query_lower = query_string.lower()
        # Exact name match
        exact = ddf[ddf["name"].str.lower() == query_lower]
        if len(exact) == 0:
            # Contains match
            exact = ddf[ddf["name"].str.lower().str.contains(query_lower, na=False)]
        if len(exact) == 0:
            # Synonyms match
            mask = ddf["synonyms"].apply(
                lambda s: _synonyms_match(s, query_lower) if isinstance(s, dict) else False
            )
            exact = ddf[mask]
        for _, row in exact.head(10).iterrows():
            results.append({
                "id": row["id"],
                "entity": "disease",
                "name": row.get("name", ""),
                "description": row.get("description", ""),
            })

    return results


def _synonyms_match(synonyms: dict, query_lower: str) -> bool:
    """Check if query matches any synonym field."""
    for key in ("hasExactSynonym", "hasRelatedSynonym", "hasNarrowSynonym", "hasBroadSynonym"):
        vals = synonyms.get(key)
        if vals is None:
            continue
        if hasattr(vals, "tolist"):
            vals = vals.tolist()
        if isinstance(vals, list):
            for v in vals:
                if isinstance(v, str) and query_lower in v.lower():
                    return True
    return False


def get_target_info(
    ensembl_id: str, include_diseases: bool = False
) -> Dict[str, Any]:
    """Retrieve target information from local parquet.

    Returns dict with same structure as the API version.
    """
    tdf = _load_targets()
    row_df = tdf[tdf["id"] == ensembl_id]
    if len(row_df) == 0:
        return {}

    row = row_df.iloc[0]
    info = _build_target_info_base(row)

    if include_diseases:
        try:
            info["associatedDiseases"] = get_target_bundle(ensembl_id)["target_info"].get(
                "associatedDiseases",
                {"rows": []},
            )
        except Exception as exc:
            logger.warning("Failed to derive associated diseases: %s", exc)

    return info


def get_target_disease_evidence(
    ensembl_id: str,
    efo_id: str,
    datasource_ids: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Retrieve evidence linking a target to a disease from evidence parquet.

    Uses predicate pushdown for fast filtering on the 7.9GB dataset.
    """
    try:
        bundle = get_target_bundle(
            ensembl_id,
            efo_id=efo_id,
            datasource_ids=datasource_ids,
        )
        return bundle["disease_evidence"]
    except Exception as exc:
        logger.error("Evidence parquet read failed: %s", exc)
        return []


def get_target_associations(
    ensembl_id: str, min_score: float = 0.0
) -> Dict[str, Any]:
    """Get all disease associations for a target, derived from evidence parquet.

    Groups evidence by diseaseId and takes max(score) per disease.

    Returns dict matching `query_opentargets.get_target_associations`:
      - associations: list of filtered disease associations (max 500 by score)
      - api_total_count: pre-head-cap count of diseases matching min_score
    """
    try:
        bundle = get_target_bundle(ensembl_id, min_score=min_score)
        return {
            "associations": bundle.get("associations", []),
            "api_total_count": bundle.get("associations_api_total_count"),
        }
    except Exception as exc:
        logger.error("Associations derivation failed: %s", exc)
        return {"associations": [], "api_total_count": None}


def get_known_drugs_for_disease(efo_id: str) -> Dict[str, Any]:
    """Get known drugs for a disease from evidence parquet.

    Filters evidence where datatypeId='known_drug' and diseaseId=efo_id.
    """
    cached = _known_drugs_cache.get(efo_id)
    if cached is not None:
        return cached
    try:
        ev = pq.read_table(
            DATA_DIR / "evidence",
            columns=[
                "targetId", "diseaseId", "datasourceId", "datatypeId",
                "score", "drugId", "clinicalPhase",
            ],
            filters=[
                ("diseaseId", "=", efo_id),
                ("datatypeId", "=", "known_drug"),
            ],
        ).to_pandas()

        if len(ev) == 0:
            return {"uniqueDrugs": 0, "uniqueTargets": 0, "rows": []}

        unique_drugs = ev["drugId"].dropna().nunique()
        unique_targets = ev["targetId"].dropna().nunique()

        # Load target names for mapping
        tdf = _load_targets()
        target_map = dict(zip(tdf["id"], tdf["approvedSymbol"]))

        rows = []
        # Group by drugId to deduplicate
        for drug_id, grp in ev.groupby("drugId"):
            if pd.isna(drug_id):
                continue
            best = grp.sort_values("score", ascending=False).iloc[0]
            phase = int(best["clinicalPhase"]) if pd.notna(best.get("clinicalPhase")) else None
            target_id = best.get("targetId", "")
            rows.append({
                "drug": {
                    "id": str(drug_id),
                    "name": str(drug_id),  # Parquet doesn't have drug names
                    "drugType": None,
                    "maximumClinicalTrialPhase": phase,
                },
                "target": {
                    "id": target_id,
                    "approvedSymbol": target_map.get(target_id, target_id),
                },
                "phase": phase,
                "status": None,
                "mechanismOfAction": None,
            })

        result = {
            "uniqueDrugs": int(unique_drugs),
            "uniqueTargets": int(unique_targets),
            "rows": rows,
        }
        _known_drugs_cache[efo_id] = result
        return result
    except Exception as exc:
        logger.error("Known drugs parquet read failed: %s", exc)
        return {"uniqueDrugs": 0, "uniqueTargets": 0, "rows": []}


def get_drugs_for_target(ensembl_id: str) -> Dict[str, Any]:
    """Get drugs targeting a specific gene across all diseases from evidence parquet.

    Mirrors the API's target.drugAndClinicalCandidates structure.
    Filters evidence where targetId matches and drugId is not null,
    groups by drugId, and collects associated diseases per drug.
    """
    try:
        ev = _get_target_evidence_df(ensembl_id)
        if "drugId" not in ev.columns:
            return {"count": 0, "rows": []}

        drug_ev = ev[ev["drugId"].notna()].copy()
        if len(drug_ev) == 0:
            return {"count": 0, "rows": []}

        disease_ids = drug_ev["diseaseId"].dropna().unique().tolist()
        disease_names = _disease_id_to_name(disease_ids)

        rows = []
        for drug_id, grp in drug_ev.groupby("drugId"):
            if pd.isna(drug_id):
                continue

            max_phase = None
            if "clinicalPhase" in grp.columns:
                phases = grp["clinicalPhase"].dropna()
                if len(phases) > 0:
                    max_phase = int(phases.max())

            diseases = []
            seen: set = set()
            for _, r in grp.iterrows():
                did = r.get("diseaseId")
                if pd.notna(did) and did not in seen:
                    seen.add(did)
                    diseases.append({
                        "diseaseFromSource": disease_names.get(did, did),
                        "disease": {"id": did, "name": disease_names.get(did, did)},
                    })

            rows.append({
                "maxClinicalStage": max_phase,
                "drug": {
                    "id": str(drug_id),
                    "name": str(drug_id),  # Parquet has no drug names
                    "maximumClinicalStage": max_phase,
                    "drugType": None,
                },
                "diseases": diseases,
            })

        return {"count": len(rows), "rows": rows}
    except Exception as exc:
        logger.error("get_drugs_for_target parquet read failed: %s", exc)
        return {"count": 0, "rows": []}


# ── Helpers ───────────────────────────────────────────────────────────

def _to_list(val: Any) -> list:
    """Convert numpy array or other iterable to plain JSON-safe list."""
    if val is None:
        return []
    if hasattr(val, "tolist") and not isinstance(val, str):
        return _to_native(val.tolist())
    if isinstance(val, list):
        return _to_native(val)
    return [_to_native(val)]
