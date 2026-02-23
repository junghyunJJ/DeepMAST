"""Multi-source evidence adapters for Phase 4.7 therapeutic assessment.

Fail-soft integration for:
- ChEMBL target hints (gene -> target presence)
- ClinicalTrials.gov counts (disease + drug -> trial count)
- DrugBank local lookup (drug name -> DrugBank match; optional)
"""

from __future__ import annotations

import json
import logging
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CHEMBL_SEARCH_URL = "https://www.ebi.ac.uk/chembl/api/data/target/search.json"
CLINICALTRIALS_STUDIES_URL = "https://clinicaltrials.gov/api/v2/studies"


def _fetch_json(url: str, timeout: float = 8.0) -> dict:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "DeepMAST/1.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read()
    return json.loads(payload.decode("utf-8"))


def _normalize_key(value: Optional[str]) -> str:
    return (value or "").strip().upper()


def _dedup_preserve(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def fetch_chembl_gene_evidence(
    gene_symbols: list[str],
    max_genes: int = 20,
    timeout: float = 6.0,
) -> tuple[str, dict[str, dict], dict[str, str]]:
    """Fetch lightweight ChEMBL target hints for genes."""
    genes = _dedup_preserve([g for g in gene_symbols if isinstance(g, str)])
    genes = genes[:max_genes]
    evidence_by_gene: dict[str, dict] = {}
    errors: dict[str, str] = {}
    success_requests = 0

    for gene in genes:
        try:
            params = {"q": gene, "limit": 20}
            url = f"{CHEMBL_SEARCH_URL}?{urllib.parse.urlencode(params)}"
            payload = _fetch_json(url, timeout=timeout)
            success_requests += 1
        except Exception as exc:
            errors[gene] = str(exc)
            evidence_by_gene[gene] = {
                "chembl_target_hits_count": 0,
                "chembl_target_ids": [],
                "chembl_exact_symbol_match": False,
            }
            continue

        targets = payload.get("targets", [])
        if not isinstance(targets, list):
            targets = []

        gene_u = gene.upper()
        exact_ids: list[str] = []
        fuzzy_ids: list[str] = []
        for target in targets:
            if not isinstance(target, dict):
                continue
            target_id = str(target.get("target_chembl_id", "") or "")
            pref_name = str(target.get("pref_name", "") or "").upper()
            if not target_id:
                continue
            if pref_name == gene_u or f" {gene_u} " in f" {pref_name} ":
                exact_ids.append(target_id)
            elif gene_u in pref_name:
                fuzzy_ids.append(target_id)

        selected_ids = _dedup_preserve(exact_ids if exact_ids else fuzzy_ids)
        evidence_by_gene[gene] = {
            "chembl_target_hits_count": len(selected_ids),
            "chembl_target_ids": selected_ids[:5],
            "chembl_exact_symbol_match": bool(exact_ids),
        }

    if success_requests > 0:
        status = "ok"
    elif errors:
        status = "degraded"
    else:
        status = "not_requested"

    return status, evidence_by_gene, errors


def fetch_clinicaltrials_drug_counts(
    disease: str,
    drug_names: list[str],
    max_drugs: int = 20,
    timeout: float = 6.0,
) -> tuple[str, dict[str, dict], dict[str, str]]:
    """Fetch ClinicalTrials.gov total count for disease+intervention pairs."""
    names = _dedup_preserve([d for d in drug_names if isinstance(d, str)])
    names = names[:max_drugs]
    results_by_drug: dict[str, dict] = {}
    errors: dict[str, str] = {}
    success_requests = 0

    for drug in names:
        key = _normalize_key(drug)
        if not key:
            continue
        params = {
            "query.cond": disease,
            "query.intr": drug,
            "pageSize": 1,
            "format": "json",
        }
        url = f"{CLINICALTRIALS_STUDIES_URL}?{urllib.parse.urlencode(params)}"
        try:
            payload = _fetch_json(url, timeout=timeout)
            success_requests += 1
            total_count = int(payload.get("totalCount", 0) or 0)
            results_by_drug[key] = {
                "clinical_trials_total_count": total_count,
            }
        except Exception as exc:
            errors[key] = str(exc)
            results_by_drug[key] = {
                "clinical_trials_total_count": 0,
            }

    if success_requests > 0:
        status = "ok"
    elif errors:
        status = "degraded"
    else:
        status = "not_requested"

    return status, results_by_drug, errors


def fetch_drugbank_drug_matches(
    drug_names: list[str],
    max_drugs: int = 20,
) -> tuple[str, dict[str, dict], dict[str, str]]:
    """Try local DrugBank helper lookup; degrade gracefully if unavailable."""
    names = _dedup_preserve([d for d in drug_names if isinstance(d, str)])
    names = names[:max_drugs]
    matches_by_drug: dict[str, dict] = {}
    errors: dict[str, str] = {}

    # DrugBank helper uses local downloader/data. This may be unavailable.
    helper = None
    try:
        skills_root = Path(__file__).resolve().parents[4] / "skills"
        drugbank_scripts = skills_root / "drugbank-database" / "scripts"
        if str(drugbank_scripts) not in sys.path:
            sys.path.insert(0, str(drugbank_scripts))
        from drugbank_helper import DrugBankHelper  # type: ignore

        helper = DrugBankHelper()
    except Exception as exc:
        for drug in names:
            key = _normalize_key(drug)
            if not key:
                continue
            matches_by_drug[key] = {
                "drugbank_match_count": 0,
                "drugbank_ids": [],
            }
        errors["adapter"] = str(exc)
        return "unavailable", matches_by_drug, errors

    success_requests = 0
    for drug in names:
        key = _normalize_key(drug)
        if not key:
            continue
        try:
            exact = helper.search_by_name(drug, exact=True) or []
            fuzzy = [] if exact else (helper.search_by_name(drug, exact=False) or [])[:3]
            selected = exact if exact else fuzzy
            ids = _dedup_preserve([str(r.get("id", "") or "") for r in selected])
            matches_by_drug[key] = {
                "drugbank_match_count": len(ids),
                "drugbank_ids": ids,
            }
            success_requests += 1
        except Exception as exc:
            errors[key] = str(exc)
            matches_by_drug[key] = {
                "drugbank_match_count": 0,
                "drugbank_ids": [],
            }

    if success_requests > 0:
        status = "ok"
    elif errors:
        status = "degraded"
    else:
        status = "not_requested"
    return status, matches_by_drug, errors


def collect_multi_source_evidence(
    disease: str,
    gene_symbols: list[str],
    known_drugs: list[dict],
) -> dict:
    """Collect fail-soft multi-source evidence payload."""
    drug_names = [
        d.get("drug_name", "")
        for d in known_drugs
        if isinstance(d, dict) and isinstance(d.get("drug_name"), str)
    ]

    chembl_status, chembl_by_gene, chembl_errors = fetch_chembl_gene_evidence(
        gene_symbols=gene_symbols
    )
    clinical_status, clinical_by_drug, clinical_errors = fetch_clinicaltrials_drug_counts(
        disease=disease,
        drug_names=drug_names,
    )
    drugbank_status, drugbank_by_drug, drugbank_errors = fetch_drugbank_drug_matches(
        drug_names=drug_names
    )

    return {
        "chembl_status": chembl_status,
        "clinicaltrials_status": clinical_status,
        "drugbank_status": drugbank_status,
        "chembl_by_gene": chembl_by_gene,
        "clinicaltrials_by_drug": clinical_by_drug,
        "drugbank_by_drug": drugbank_by_drug,
        "errors": {
            "chembl": chembl_errors,
            "clinicaltrials": clinical_errors,
            "drugbank": drugbank_errors,
        },
    }
