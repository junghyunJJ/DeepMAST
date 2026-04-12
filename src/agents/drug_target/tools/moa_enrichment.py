"""Local-first mechanism-of-action enrichment for drug dicts.

Reads `data/chembl/mechanisms.parquet` (via the chembl-database skill module)
to populate ``mechanism_of_action`` on drug dicts coming from either the
OpenTargets clinical-drug loader or the ChEMBL bioactivity preclinical loader.
No network calls — strict local-first.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from . import drug_moa_cache
from ._skill_loader import load_skill_module as _load_skill_module

logger = logging.getLogger(__name__)

_GENERIC_GENE_KEY = "__GLOBAL__"
# Process-lifetime cache of the mechanisms parquet. Not TTL-aware — if a
# long-running service reloads the parquet on disk, call reset_index_cache().
_mechanism_index_cache: dict[str, str] | None = None


def _load_local_chembl() -> Any | None:
    try:
        mod = _load_skill_module("chembl-database", "chembl_parquet.py", "chembl_parquet")
    except Exception as exc:
        logger.debug("chembl_parquet module load failed: %s", exc)
        return None
    if hasattr(mod, "is_available") and mod.is_available():
        return mod
    return None


def _build_mechanism_index(mod: Any) -> dict[str, str]:
    """Return ``{molecule_chembl_id: 'MoA1 | MoA2 | ...'}`` from local parquet."""
    try:
        df = mod._load_mechanisms()
    except Exception as exc:
        logger.debug("mechanisms parquet load failed: %s", exc)
        return {}
    if df is None or df.empty:
        return {}

    index: dict[str, list[str]] = {}
    try:
        rows = df.dropna(subset=["mechanism_of_action"]).itertuples(index=False)
    except Exception as exc:
        logger.debug("mechanisms parquet iteration failed: %s", exc)
        return {}

    for row in rows:
        chembl_id = str(getattr(row, "molecule_chembl_id", "")).strip().upper()
        moa = str(getattr(row, "mechanism_of_action", "")).strip()
        if not chembl_id or not moa:
            continue
        bucket = index.setdefault(chembl_id, [])
        if moa not in bucket:
            bucket.append(moa)

    return {cid: " | ".join(moas) for cid, moas in index.items()}


def _get_cached_index(mod: Any) -> dict[str, str]:
    global _mechanism_index_cache
    if _mechanism_index_cache is None:
        _mechanism_index_cache = _build_mechanism_index(mod)
    return _mechanism_index_cache


def reset_index_cache() -> None:
    """Clear the in-process mechanism index (test helper)."""
    global _mechanism_index_cache
    _mechanism_index_cache = None


def resolve_moa_for_chembl_ids(chembl_ids: Iterable[str]) -> dict[str, str | None]:
    """Resolve mechanism-of-action strings for a set of ChEMBL IDs.

    Lookup order:
      1. ``drug_moa_cache`` under the generic ``__GLOBAL__`` key
      2. local ``data/chembl/mechanisms.parquet`` via the chembl-database skill

    Newly resolved (or missing) entries are persisted back to the cache so the
    next pipeline run can short-circuit. Nothing uses the network.
    """
    ids = sorted({str(c).strip().upper() for c in chembl_ids if c})
    result: dict[str, str | None] = {cid: None for cid in ids}
    if not ids:
        return result

    for cid in ids:
        try:
            cached = drug_moa_cache.get_cached_moa(cid, _GENERIC_GENE_KEY)
        except Exception as exc:
            logger.debug("MoA cache read failed for %s: %s", cid, exc)
            cached = None
        if cached:
            result[cid] = cached

    missing = [cid for cid, moa in result.items() if not moa]
    new_hits: dict[str, str] = {}
    if missing:
        mod = _load_local_chembl()
        if mod is not None:
            index = _get_cached_index(mod)
            for cid in missing:
                moa = index.get(cid)
                if moa:
                    result[cid] = moa
                    new_hits[cid] = moa

    if new_hits or missing:
        new_entries = []
        for cid in ids:
            moa = result.get(cid)
            # Only persist entries we touched this pass: fresh hits, or the
            # genuine local-parquet misses so we can skip re-checking next run.
            if cid in new_hits or cid in missing:
                new_entries.append(
                    {
                        "chembl_id": cid,
                        "target_gene": _GENERIC_GENE_KEY,
                        "status": "resolved" if moa else "not_found",
                        "mechanism_of_action": moa,
                        "source": "chembl_parquet" if moa else None,
                        "source_target": None,
                        "retrieved_at": None,
                    }
                )
        if new_entries:
            try:
                drug_moa_cache.write_entries(
                    new_entries,
                    source_versions={"mode": "local_first"},
                )
            except Exception as exc:
                logger.debug("MoA cache persist skipped: %s", exc)

    return result


def enrich_drugs_in_place(*drug_lists: list[dict]) -> int:
    """Mutate drug dicts to populate ``mechanism_of_action`` from local data.

    Accepts one or more drug-list arguments (clinical + preclinical are fine in
    a single call). Pre-existing non-empty MoA values are preserved. Returns
    the number of dicts whose MoA was newly populated.
    """
    collected: list[str] = []
    for drugs in drug_lists:
        if not isinstance(drugs, list):
            continue
        for d in drugs:
            if not isinstance(d, dict):
                continue
            cid = d.get("chembl_id")
            if cid:
                collected.append(str(cid))
    if not collected:
        return 0

    resolved = resolve_moa_for_chembl_ids(collected)
    filled = 0
    for drugs in drug_lists:
        if not isinstance(drugs, list):
            continue
        for d in drugs:
            if not isinstance(d, dict):
                continue
            cid = str(d.get("chembl_id", "")).strip().upper()
            if not cid:
                continue
            current = d.get("mechanism_of_action")
            if current:
                continue
            moa = resolved.get(cid)
            if moa:
                d["mechanism_of_action"] = moa
                filled += 1
    return filled
