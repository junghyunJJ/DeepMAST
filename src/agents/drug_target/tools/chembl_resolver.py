"""Shared local-first ChEMBL resolver helpers."""

from __future__ import annotations

import logging
from typing import Any

from src.agents.drug_target.tools._skill_loader import load_skill_module as _load_skill_module
from . import drug_moa_cache

logger = logging.getLogger(__name__)

_ACTIVITY_PRIORITY = ("IC50", "Ki", "EC50")


class LocalDataRequiredError(RuntimeError):
    """Raised when a local-only ChEMBL path is requested without local data."""


def normalize_chembl_organism(organism: str | None) -> str:
    text = (organism or "human").strip().lower().replace("_", " ")
    if text in {"human", "homo sapiens"}:
        return "human"
    if text in {"mouse", "mus musculus"}:
        return "mouse"
    return text


def _try_load_local_module():
    try:
        mod = _load_skill_module("chembl-database", "chembl_parquet.py", "chembl_parquet")
        if hasattr(mod, "is_available") and mod.is_available():
            return mod
    except Exception as exc:
        logger.debug("Local ChEMBL subset unavailable: %s", exc)
    return None


def _load_api_module():
    return _load_skill_module("chembl-database", "example_queries.py", "chembl_queries")


def _search_targets(mod: Any, gene_symbol: str, organism: str) -> list[dict]:
    try:
        return list(mod.search_targets_by_name(gene_symbol, organism=organism))
    except TypeError:
        return list(mod.search_targets_by_name(gene_symbol))


def _get_molecule_info(mod: Any, chembl_id: str):
    if not hasattr(mod, "get_molecule_info"):
        return None
    return mod.get_molecule_info(chembl_id)


def _fetch_drug_indications_and_mechanism(
    mod: Any,
    molecule_chembl_id: str,
    *,
    target_gene: str | None = None,
) -> tuple[list[dict], str | None]:
    indications: list[dict] = []
    mechanism_of_action: str | None = None
    try:
        _drug_info, mechanisms, raw_indications = mod.get_drug_info(molecule_chembl_id)
        for ind in raw_indications:
            indications.append(
                {
                    "efo_term": ind.get("efo_term") or ind.get("mesh_heading") or "",
                    "max_phase": ind.get("max_phase_for_ind"),
                    "mesh_heading": ind.get("mesh_heading") or "",
                }
            )
        if mechanisms:
            mechanism_of_action = mechanisms[0].get("mechanism_of_action")
    except Exception as exc:
        logger.debug("Indication/mechanism lookup failed for %s: %s", molecule_chembl_id, exc)
    if not mechanism_of_action and target_gene:
        try:
            mechanism_of_action = drug_moa_cache.get_cached_moa(
                molecule_chembl_id,
                target_gene,
            )
        except Exception as exc:
            logger.debug(
                "Local MOA cache lookup failed for %s/%s: %s",
                molecule_chembl_id,
                target_gene,
                exc,
            )
    return indications, mechanism_of_action


def resolve_chembl_molecule(
    chembl_id: str,
    *,
    allow_api_fallback: bool = True,
) -> dict[str, Any]:
    """Resolve CHEMBL ID to name and core molecule metadata."""
    local_mod = _try_load_local_module()
    if local_mod is not None:
        try:
            local_info = _get_molecule_info(local_mod, chembl_id)
            if local_info:
                return {
                    "name": local_info.get("pref_name") or chembl_id,
                    "molecule_type": local_info.get("molecule_type"),
                    "first_approval": local_info.get("first_approval"),
                }
        except Exception as exc:
            logger.debug("Local molecule lookup failed for %s: %s", chembl_id, exc)

    if allow_api_fallback:
        try:
            api_mod = _load_api_module()
            api_info = _get_molecule_info(api_mod, chembl_id)
            if api_info:
                return {
                    "name": api_info.get("pref_name") or chembl_id,
                    "molecule_type": api_info.get("molecule_type"),
                    "first_approval": api_info.get("first_approval"),
                }
        except Exception as exc:
            logger.debug("API molecule lookup failed for %s: %s", chembl_id, exc)

    return {"name": chembl_id, "molecule_type": None, "first_approval": None}


def _query_chembl_drugs_with_module(
    mod: Any,
    gene_symbol: str,
    max_drugs: int,
    organism: str,
) -> tuple[list[dict], int]:
    targets = _search_targets(mod, gene_symbol, organism)
    if not targets:
        return [], 0

    seen: set[str] = set()
    matches: list[dict] = []
    cap = max(1, min(max_drugs, 25))

    for tgt in targets:
        target_id = tgt.get("target_chembl_id")
        if not target_id:
            continue

        activities: list[dict] = []
        for activity_type in _ACTIVITY_PRIORITY:
            activities = mod.get_bioactivity_data(
                target_id,
                activity_type=activity_type,
                max_value=10000,
            )
            if activities:
                break

        for act in activities:
            mol_id = act.get("molecule_chembl_id")
            if not mol_id or mol_id in seen:
                continue
            seen.add(mol_id)

            molecule_info = resolve_chembl_molecule(mol_id, allow_api_fallback=False)
            indications, mechanism = _fetch_drug_indications_and_mechanism(
                mod,
                mol_id,
                target_gene=gene_symbol,
            )
            matches.append(
                {
                    "chembl_id": mol_id,
                    "drug_name": (
                        act.get("molecule_pref_name")
                        or molecule_info.get("name")
                        or mol_id
                    ),
                    "target_gene": gene_symbol.upper(),
                    "mechanism_of_action": mechanism,
                    "indications": indications,
                }
            )
            if len(matches) >= cap:
                return matches, len(targets)

    return matches, len(targets)


def query_chembl_drugs(
    gene_symbol: str,
    max_drugs: int,
    organism: str = "human",
) -> list[dict]:
    """Resolve ChEMBL drugs for one gene with local-first behavior."""
    organism_key = normalize_chembl_organism(organism)
    local_mod = _try_load_local_module()

    if local_mod is not None:
        try:
            matches, target_count = _query_chembl_drugs_with_module(
                local_mod,
                gene_symbol,
                max_drugs,
                organism_key,
            )
            if target_count > 0 or organism_key == "mouse":
                return matches
        except Exception as exc:
            if organism_key == "mouse":
                raise LocalDataRequiredError(
                    f"local-data-required: mouse ChEMBL subset unavailable or unreadable: {exc}"
                ) from exc
            logger.warning("Local ChEMBL lookup failed for %s: %s", gene_symbol, exc)
    elif organism_key == "mouse":
        raise LocalDataRequiredError(
            "local-data-required: mouse ChEMBL subset unavailable"
        )

    api_mod = _load_api_module()
    matches, _target_count = _query_chembl_drugs_with_module(
        api_mod,
        gene_symbol,
        max_drugs,
        organism_key,
    )
    return matches
