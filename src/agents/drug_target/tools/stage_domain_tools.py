"""Stage-specific domain tool wrappers for the 3-stage funnel."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import os
import re
import requests
from langchain_core.tools import tool

from src.agents.drug_target.tools.disease_context import (
    disease_labels_equal,
    load_disease_context,
    merge_disease_context,
    resolve_stage2_input_disease,
)
from src.agents.drug_target.tools.stage2_service import (
    build_stage2_gene_panel,
    query_gwas_gene_trait_data,
    query_opentargets_known_drugs_data,
    query_opentargets_target_data,
    summarize_stage2_bundle,
    write_stage2_artifacts,
)

from src.agents.drug_target.tools._skill_loader import load_skill_module as _load_skill_module
from src.agents.drug_target.tools.chembl_resolver import (
    LocalDataRequiredError,
    query_chembl_drugs as _query_chembl_drugs,
)

logger = logging.getLogger(__name__)

_TIMEOUT = 30
_DEFAULT_CENSUS_VERSION = os.getenv("CENSUS_VERSION", "2025-11-08")

_CHEMBL_LOCK = threading.Lock()
_chembl_consecutive_failures = 0
_CHEMBL_MAX_CONSECUTIVE = 3
_chembl_last_failure_time: float = 0.0
_CHEMBL_COOLDOWN_SECONDS = int(os.getenv("CHEMBL_COOLDOWN_SECONDS", "60"))


def _as_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2)


def _chembl_circuit_breaker_open(result: dict[str, Any]) -> bool:
    """Return True when ChEMBL should be skipped due to recent failures."""
    with _CHEMBL_LOCK:
        global _chembl_consecutive_failures, _chembl_last_failure_time
        if _chembl_consecutive_failures < _CHEMBL_MAX_CONSECUTIVE:
            return False
        elapsed = time.time() - _chembl_last_failure_time
        if elapsed < _CHEMBL_COOLDOWN_SECONDS:
            result["errors"].append(
                f"circuit_breaker_open: {_chembl_consecutive_failures} consecutive failures"
            )
            result["note"] = "ChEMBL API circuit breaker open - no drug data retrieved"
            return True
        logger.info(
            "ChEMBL circuit breaker cooldown elapsed (%.0fs), resetting and retrying",
            elapsed,
        )
        _chembl_consecutive_failures = 0
        return False


def _record_chembl_success() -> None:
    """Reset ChEMBL circuit breaker failure count after a successful query."""
    with _CHEMBL_LOCK:
        global _chembl_consecutive_failures
        _chembl_consecutive_failures = 0


def _record_chembl_failure() -> None:
    """Increment ChEMBL circuit breaker failure count after a failed query."""
    with _CHEMBL_LOCK:
        global _chembl_consecutive_failures, _chembl_last_failure_time
        _chembl_consecutive_failures += 1
        _chembl_last_failure_time = time.time()


def _trim_text(value: str, max_len: int = 2000) -> str:
    return value if len(value) <= max_len else value[:max_len] + "...[truncated]"


_ORGANISM_MAP = {
    "human": "homo_sapiens",
    "homo sapiens": "homo_sapiens",
    "mouse": "mus_musculus",
    "mus musculus": "mus_musculus",
}


# PR2-2: HGNC-style gene-symbol allow-list. Only A-Z, 0-9, hyphen permitted.
# Mirrors the disease quote-escape pattern used at lines 94-98.
# Anchored regex prevents quote/escape injection into Census SOQL filter strings.
_GENE_SYMBOL_RE = re.compile(r"^[A-Z0-9-]+$")


def _validate_gene_symbol(symbol: str, *, role: str = "gene") -> str | None:
    """Return error string if gene symbol contains injection vectors, else None."""
    if not isinstance(symbol, str) or not symbol:
        return f"{role} symbol is empty or non-string: {symbol!r}"
    upper = symbol.upper()
    if not _GENE_SYMBOL_RE.match(upper):
        return (
            f"{role} symbol {symbol!r} contains characters outside the safe set "
            f"^[A-Z0-9-]+$. Refusing to interpolate into Census SOQL filter."
        )
    return None


@tool
def query_cellxgene_lr_context(
    ligand: str,
    receptor: str,
    disease: str,
    organism: str = "homo_sapiens",
) -> str:
    """Query CELLxGENE census metadata for disease/cell-type context."""
    organism = _ORGANISM_MAP.get(organism.lower().strip(), organism)
    result = {
        "ligand": ligand,
        "receptor": receptor,
        "disease": disease,
        "organism": organism,
        "executed": False,
        "disease_matched": True,
        "cell_count": 0,
        "top_cell_types": [],
        "available_genes": [],
        "errors": [],
    }
    # PR2-2: validate gene symbols BEFORE any SOQL interpolation (OWASP A03).
    for sym, role in [(ligand, "ligand"), (receptor, "receptor")]:
        err = _validate_gene_symbol(sym, role=role)
        if err:
            result["errors"].append(err)
            return _as_json(result)
    try:
        import cellxgene_census
    except Exception as exc:
        result["errors"].append(f"cellxgene_census unavailable: {exc}")
        return _as_json(result)

    # Auto-resolve disease name against Census MONDO vocabulary
    try:
        from src.agents.drug_target.tools.census_batch_core import _resolve_disease_name
        resolved, mode = _resolve_disease_name(disease, organism)
        if resolved:
            result["disease_resolved"] = resolved
            result["disease_resolution_mode"] = mode
            disease_safe = resolved.replace("\\", "\\\\").replace("'", "\\'")
        else:
            disease_safe = disease.replace("\\", "\\\\").replace("'", "\\'")
    except Exception:
        disease_safe = disease.replace("\\", "\\\\").replace("'", "\\'")

    try:
        with cellxgene_census.open_soma(census_version=_DEFAULT_CENSUS_VERSION) as census:
            obs = cellxgene_census.get_obs(
                census,
                organism,
                value_filter=f"is_primary_data == True and disease == '{disease_safe}'",
                column_names=["cell_type"],
            )
            if len(obs) == 0:
                result["disease_matched"] = False
                result["errors"].append(
                    f"Disease '{disease}' not matched in Census; "
                    "falling back to ALL cells. Use list_census_diseases() "
                    "to find the correct Census MONDO label."
                )
                obs = cellxgene_census.get_obs(
                    census,
                    organism,
                    value_filter="is_primary_data == True",
                    column_names=["cell_type"],
                )
                # OOM guard: cap fallback cell count (consistent with census_batch_core)
                if len(obs) > 2_000_000:
                    result["errors"].append(
                        f"Fallback returned {len(obs)} cells, exceeding safe limit (2M). "
                        "Aborting to prevent OOM. Fix the disease name via list_census_diseases()."
                    )
                    return _as_json(result)

            var = cellxgene_census.get_var(
                census,
                organism,
                value_filter=(
                    f"feature_name in ['{ligand.upper()}', '{receptor.upper()}']"
                ),
                column_names=["feature_name"],
            )

        result["executed"] = True
        result["cell_count"] = int(len(obs))
        if len(obs) > 0:
            vc = obs["cell_type"].value_counts().head(20)
            result["top_cell_types"] = [
                {"cell_type": str(name), "count": int(count)}
                for name, count in vc.items()
            ]
        result["available_genes"] = sorted(
            {str(g).upper() for g in var.get("feature_name", []).tolist()}
        )
    except Exception as exc:
        result["errors"].append(f"CELLxGENE query failed: {exc}")

    return _as_json(result)


@tool
def list_census_diseases(organism: str = "homo_sapiens") -> str:
    """List disease labels available in CELLxGENE Census for vocabulary matching."""
    organism = _ORGANISM_MAP.get(organism.lower().strip(), organism)
    result: dict[str, Any] = {
        "organism": organism,
        "executed": False,
        "diseases": [],
        "errors": [],
    }
    try:
        import cellxgene_census
    except Exception as exc:
        result["errors"].append(f"cellxgene_census unavailable: {exc}")
        return _as_json(result)

    try:
        with cellxgene_census.open_soma(census_version=_DEFAULT_CENSUS_VERSION) as census:
            summary_df = (
                census["census_info"]["summary_cell_counts"]
                .read(column_names=["organism", "category", "label", "total_cell_count"])
                .concat()
                .to_pandas()
            )
        logger.info("Census summary_cell_counts: shape=%s, columns=%s",
                     summary_df.shape, list(summary_df.columns))
        # Match organism with both underscore and space formats (Census uses underscores)
        org_underscore = organism.replace(" ", "_").lower()
        mask = (
            (summary_df["organism"].str.lower().str.replace(" ", "_") == org_underscore)
            & (summary_df["category"] == "disease")
        )
        diseases_df = summary_df[mask].sort_values("total_cell_count", ascending=False)
        result["diseases"] = [
            {"label": str(row["label"]), "total_cell_count": int(row["total_cell_count"])}
            for _, row in diseases_df.iterrows()
        ]
        result["executed"] = True
    except Exception as exc:
        result["errors"].append(f"Census disease list query failed: {exc}")

    return _as_json(result)


@tool
def list_census_cell_types(
    disease: str = "",
    organism: str = "homo_sapiens",
) -> str:
    """List cell type labels available in CELLxGENE Census for a given disease.

    Use in Phase 0 to get Census cell type vocabulary, then match
    interest_celltypes from targets.json to the correct Census label.

    Args:
        disease: Census-matched disease label (from list_census_diseases).
                 If empty, returns organism-wide cell type summary.
        organism: Census organism key (default: homo_sapiens)
    """
    organism = _ORGANISM_MAP.get(organism.lower().strip(), organism)
    result: dict[str, Any] = {
        "organism": organism,
        "disease": disease,
        "executed": False,
        "cell_types": [],
        "errors": [],
    }
    try:
        import cellxgene_census
    except Exception as exc:
        result["errors"].append(f"cellxgene_census unavailable: {exc}")
        return _as_json(result)

    try:
        if disease:
            # Query obs for specific disease → cell_type value_counts
            disease_safe = disease.replace("\\", "\\\\").replace("'", "\\'")
            with cellxgene_census.open_soma(census_version=_DEFAULT_CENSUS_VERSION) as census:
                obs = cellxgene_census.get_obs(
                    census,
                    organism,
                    value_filter=f"is_primary_data == True and disease == '{disease_safe}'",
                    column_names=["cell_type"],
                )
            if len(obs) > 0:
                vc = obs["cell_type"].value_counts().head(50)
                result["cell_types"] = [
                    {"label": str(name), "total_cell_count": int(count)}
                    for name, count in vc.items()
                ]
            result["executed"] = True
        else:
            # Organism-wide summary from summary_cell_counts
            with cellxgene_census.open_soma(census_version=_DEFAULT_CENSUS_VERSION) as census:
                summary_df = (
                    census["census_info"]["summary_cell_counts"]
                    .read(column_names=["organism", "category", "label", "total_cell_count"])
                    .concat()
                    .to_pandas()
                )
            org_underscore = organism.replace(" ", "_").lower()
            mask = (
                (summary_df["organism"].str.lower().str.replace(" ", "_") == org_underscore)
                & (summary_df["category"] == "cell_type")
            )
            ct_df = summary_df[mask].sort_values("total_cell_count", ascending=False).head(50)
            result["cell_types"] = [
                {"label": str(row["label"]), "total_cell_count": int(row["total_cell_count"])}
                for _, row in ct_df.iterrows()
            ]
            result["executed"] = True
    except Exception as exc:
        result["errors"].append(f"Census cell type query failed: {exc}")

    return _as_json(result)


@tool
def query_kegg_pathways(gene_symbol: str, organism: str = "hsa", max_results: int = 5) -> str:
    """Map a gene to KEGG pathways."""
    result = {
        "gene_symbol": gene_symbol,
        "organism": organism,
        "executed": False,
        "gene_entry": None,
        "pathways": [],
        "errors": [],
    }
    try:
        mod = _load_skill_module("kegg-database", "kegg_api.py", "kegg_api")
        lines = str(mod.kegg_find("genes", gene_symbol)).splitlines()
        gene_entry = None
        for line in lines:
            if not line or line.startswith("Error:"):
                continue
            entry = line.split("\t", 1)[0]
            if entry.startswith(f"{organism}:"):
                gene_entry = entry
                break
            if gene_entry is None and ":" in entry:
                gene_entry = entry

        if not gene_entry:
            result["errors"].append(f"No KEGG gene entry found for {gene_symbol}")
            return _as_json(result)

        result["gene_entry"] = gene_entry
        links = str(mod.kegg_link("pathway", gene_entry)).splitlines()
        pathway_ids: list[str] = []
        for line in links:
            if not line or line.startswith("Error:"):
                continue
            cols = line.split("\t")
            if len(cols) >= 2 and cols[1].startswith("path:"):
                pathway_ids.append(cols[1].replace("path:", ""))
        pathway_ids = list(dict.fromkeys(pathway_ids))[: max(1, min(max_results, 10))]

        pathways = []
        for pid in pathway_ids:
            raw = str(mod.kegg_get(pid))
            name = ""
            for row in raw.splitlines():
                if row.startswith("NAME"):
                    name = row.replace("NAME", "").strip().rstrip(";")
                    break
            pathways.append({"pathway_id": pid, "name": name or pid})

        result["pathways"] = pathways
        result["executed"] = True
    except Exception as exc:
        result["errors"].append(f"KEGG query failed: {exc}")
    return _as_json(result)


@tool
def query_reactome_pathways(gene_symbol: str, max_results: int = 5) -> str:
    """Search Reactome pathways related to a gene symbol."""
    result = {
        "gene_symbol": gene_symbol,
        "executed": False,
        "pathways": [],
        "errors": [],
    }
    try:
        mod = _load_skill_module("reactome-database", "reactome_query.py", "reactome_query")
        client = mod.ReactomeClient()
        rows = None
        for attempt in range(3):
            try:
                rows = client.search_pathways(gene_symbol) or []
                break
            except (ConnectionResetError, requests.ConnectionError):
                if attempt < 2:
                    time.sleep(2 ** attempt)
                else:
                    raise
        if rows is None:
            rows = []
        pathways = []
        for row in rows:
            # Accept both old ("schemaClass") and new ("type") response formats
            entry_type = row.get("type") or row.get("schemaClass", "")
            if entry_type != "Pathway":
                continue
            # Strip HTML highlighting tags from name
            raw_name = row.get("name") or row.get("displayName") or ""
            clean_name = re.sub(r"<[^>]+>", "", raw_name)
            # Species: new format returns list of strings, old returns list of dicts
            species_raw = row.get("species")
            if isinstance(species_raw, list) and species_raw:
                sp = species_raw[0]
                species_val = sp.get("displayName") if isinstance(sp, dict) else str(sp)
            else:
                species_val = None
            pathways.append(
                {
                    "reactome_id": row.get("stId"),
                    "name": clean_name,
                    "species": species_val,
                }
            )
            if len(pathways) >= max(1, min(max_results, 10)):
                break
        result["pathways"] = pathways
        result["executed"] = True
    except Exception as exc:
        result["errors"].append(f"Reactome query failed: {exc}")
    return _as_json(result)


@tool
def query_string_ppi_pair(
    gene_a: str,
    gene_b: str,
    species: int = 9606,
    required_score: int = 400,
) -> str:
    """Check STRING interaction evidence for a gene pair.

    PR2-1: `string_record_found` is True iff the STRING TSV contained a row
    matching the exact gene pair (regardless of score). Used by
    compute_stage1_filter to distinguish "pair not in DB at threshold" (which
    should NOT be a hard fail) from "pair in DB with low score" (which IS a fail).
    """
    result = {
        "gene_a": gene_a,
        "gene_b": gene_b,
        "species": species,
        "required_score": required_score,
        "executed": False,
        "interaction_found": False,
        "string_record_found": False,
        "max_combined_score": 0.0,
        "ppi_enrichment": None,
        "errors": [],
    }
    try:
        mod = _load_skill_module("string-database", "string_api.py", "string_api")
        network_tsv = str(
            mod.string_network(
                [gene_a, gene_b],
                species=species,
                required_score=required_score,
            )
        )
        lines = network_tsv.splitlines()
        if lines and not lines[0].startswith("Error:"):
            header = lines[0].split("\t")
            score_idx = header.index("score") if "score" in header else None
            preferred_a_idx = (
                header.index("preferredName_A")
                if "preferredName_A" in header
                else None
            )
            preferred_b_idx = (
                header.index("preferredName_B")
                if "preferredName_B" in header
                else None
            )
            for line in lines[1:]:
                cols = line.split("\t")
                if score_idx is None or len(cols) <= score_idx:
                    continue
                try:
                    score = float(cols[score_idx])
                except ValueError:
                    score = 0.0
                result["max_combined_score"] = max(result["max_combined_score"], score)

                if preferred_a_idx is not None and preferred_b_idx is not None:
                    a_name = cols[preferred_a_idx].upper()
                    b_name = cols[preferred_b_idx].upper()
                    target = {gene_a.upper(), gene_b.upper()}
                    if {a_name, b_name} == target:
                        result["interaction_found"] = True
                        # PR2-1: TSV contained a row matching the exact pair.
                        # Distinct from "score > 0" — a 0-score row with matching
                        # names still counts as "in DB", just below threshold.
                        result["string_record_found"] = True

        ppi_raw = str(
            mod.string_ppi_enrichment(
                [gene_a, gene_b],
                species=species,
                required_score=required_score,
            )
        )
        if not ppi_raw.startswith("Error:"):
            try:
                parsed = json.loads(ppi_raw)
                if isinstance(parsed, list) and parsed:
                    result["ppi_enrichment"] = parsed[0]
                else:
                    result["ppi_enrichment"] = parsed
            except json.JSONDecodeError:
                result["ppi_enrichment"] = _trim_text(ppi_raw, max_len=500)

        result["executed"] = True
    except Exception as exc:
        result["errors"].append(f"STRING query failed: {exc}")
    return _as_json(result)


@tool
def query_ensembl_vep_consequence(variant_ids: str, species: str = "human") -> str:
    """Query Ensembl VEP consequences for variant IDs (e.g., rs IDs)."""
    ids = [v.strip() for v in variant_ids.split(",") if v.strip()]
    result = {
        "species": species,
        "requested_ids": ids,
        "executed": False,
        "variants": [],
        "errors": [],
    }
    if not ids:
        result["errors"].append("No variant IDs provided")
        return _as_json(result)

    url = f"https://rest.ensembl.org/vep/{species}/id"
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    try:
        resp = requests.post(url, headers=headers, data=json.dumps({"ids": ids}), timeout=_TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
        for row in payload:
            result["variants"].append(
                {
                    "input": row.get("input"),
                    "id": row.get("id"),
                    "most_severe_consequence": row.get("most_severe_consequence"),
                }
            )
        result["executed"] = True
    except Exception as exc:
        result["errors"].append(f"VEP query failed: {exc}")
    return _as_json(result)


def _query_chembl_target_profile_payload(
    gene_symbol: str,
    max_drugs: int = 10,
    organism: str = "human",
) -> dict[str, Any]:
    """Return the ChEMBL target profile payload for one gene symbol."""
    result = {
        "gene_symbol": gene_symbol,
        "executed": False,
        "matched_drugs": [],
        "source": "chembl",
        "errors": [],
    }
    if _chembl_circuit_breaker_open(result):
        return result

    try:
        matches = _query_chembl_drugs(gene_symbol, max_drugs, organism=organism)
        result["matched_drugs"] = matches
        result["executed"] = True
        _record_chembl_success()
    except LocalDataRequiredError as exc:
        result["errors"].append(str(exc))
    except (sqlite3.DatabaseError, sqlite3.OperationalError) as exc:
        logger.warning("ChEMBL cache corrupted (%s), clearing and retrying", exc)
        try:
            from chembl_webresource_client.settings import Settings
            with _CHEMBL_LOCK:
                Settings.Instance().clear_cache()
        except Exception:
            pass
        try:
            matches = _query_chembl_drugs(gene_symbol, max_drugs, organism=organism)
            result["matched_drugs"] = matches
            result["executed"] = True
            _record_chembl_success()
        except Exception as exc2:
            _record_chembl_failure()
            result["errors"].append(f"ChEMBL retry after cache clear failed: {exc2}")
    except requests.exceptions.HTTPError as exc:
        # Retry once with backoff for 5xx errors
        status_code = getattr(exc.response, "status_code", 0)
        if 500 <= status_code < 600:
            logger.warning("ChEMBL %d for %s, retrying after 2s", status_code, gene_symbol)
            time.sleep(2)
            try:
                matches = _query_chembl_drugs(gene_symbol, max_drugs, organism=organism)
                result["matched_drugs"] = matches
                result["executed"] = True
                _record_chembl_success()
            except Exception:
                _record_chembl_failure()
                result["errors"].append(f"ChEMBL {status_code} after retry: {exc}")
        else:
            _record_chembl_failure()
            result["errors"].append(f"ChEMBL HTTP {status_code}: {exc}")
    except Exception as exc:
        _record_chembl_failure()
        result["errors"].append(f"ChEMBL query failed: {exc}")
    return result


@tool
def query_chembl_target_profile(
    gene_symbol: str,
    max_drugs: int = 10,
    organism: str = "human",
) -> str:
    """Retrieve drugs targeting a gene symbol via ChEMBL."""
    return _as_json(
        _query_chembl_target_profile_payload(
            gene_symbol,
            max_drugs=max_drugs,
            organism=organism,
        )
    )


def _stage3_candidate_genes(assessment: dict[str, Any]) -> list[str]:
    """Return normalized Stage 3 candidate genes from assessment_results.json."""
    genes: list[str] = []
    seen: set[str] = set()
    for entry in assessment.get("stage3_candidates", []):
        if isinstance(entry, dict):
            gene = str(entry.get("gene") or entry.get("gene_symbol") or "").strip().upper()
        else:
            gene = str(entry).strip().upper()
        if gene and gene not in seen:
            seen.add(gene)
            genes.append(gene)
    return genes


def _stage3_chembl_worker_count(gene_count: int) -> int:
    """Return bounded worker count for Stage 3 ChEMBL calls."""
    if gene_count <= 1:
        return 1
    try:
        configured = int(os.getenv("DRUG_TARGET_STAGE3_CHEMBL_WORKERS", "5"))
    except ValueError:
        configured = 5
    return max(1, min(gene_count, configured))


def _query_stage3_gene_profile(
    args: tuple[str, int, str],
) -> tuple[str, dict[str, Any] | None, str | None]:
    """Query one Stage 3 ChEMBL profile for batch execution."""
    gene, max_drugs, organism = args
    try:
        return (
            gene,
            _query_chembl_target_profile_payload(
                gene,
                max_drugs=max_drugs,
                organism=organism,
            ),
            None,
        )
    except Exception as exc:
        return gene, None, f"ChEMBL {gene}: {exc}"


def _stage3_error_list(value: Any) -> list[str]:
    """Normalize a Stage 3 error field to a list."""
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if value:
        return [str(value)]
    return []


def _existing_stage3_profile_reusable(path: Path, gene: str) -> tuple[bool, str]:
    """Return whether an existing Stage 3 profile can be reused safely."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"invalid_json: {exc}"

    if not isinstance(payload, dict):
        return False, "not_json_object"

    payload_gene = str(payload.get("gene") or payload.get("gene_symbol") or "").strip().upper()
    if payload_gene and payload_gene != gene:
        return False, f"gene_mismatch: {payload_gene}"
    if not payload.get("executed", False):
        return False, "not_executed"
    if _stage3_error_list(payload.get("errors")):
        return False, "errors_present"

    chembl_payload = payload.get("chembl")
    if isinstance(chembl_payload, dict):
        if "executed" in chembl_payload and not chembl_payload.get("executed", False):
            return False, "chembl_not_executed"
        if _stage3_error_list(chembl_payload.get("errors")):
            return False, "chembl_errors_present"

    return True, ""


@tool
def run_stage3_batch(
    data_dir: str,
    max_drugs: int = 10,
    organism: str = "human",
) -> str:
    """Run ChEMBL Stage 3 for all current stage3_candidates in one tool call.

    This is the Stage 3 counterpart to ``query_stage2_gene_panel`` and
    ``run_stage1_batch``. It reads ``assessment_results.json``, skips existing
    ``stage3_{GENE}.json`` files for resume/idempotency, queries ChEMBL only for
    missing genes, writes canonical stage3 JSON files, then validates the Stage
    3 gate.
    """
    from src.agents.drug_target.tools.evidence_loader import _resolve_data_dir
    from src.agents.drug_target.tools.stage_logic import validate_stage3_gate

    base = _resolve_data_dir(data_dir)
    evidence_dir = base / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    assessment_path = evidence_dir / "assessment_results.json"
    if not assessment_path.exists():
        return _as_json({
            "success": False,
            "error": "assessment_results.json not found. Run compute_rubric_scores first.",
        })

    try:
        assessment = json.loads(assessment_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return _as_json({
            "success": False,
            "error": f"Cannot parse assessment_results.json: {exc}",
        })

    genes = _stage3_candidate_genes(assessment)
    if not genes:
        return _as_json({
            "success": True,
            "total": 0,
            "queried_genes": [],
            "skipped_existing": [],
            "retried_existing": [],
            "saved_files": [],
            "failed_genes": [],
            "validation": {"success": True, "skipped": "No stage3_candidates"},
            "note": "No stage3_candidates in assessment_results.json. Stage 3 skipped.",
        })

    queried_genes: list[str] = []
    skipped_existing: list[str] = []
    saved_files: list[str] = []
    failed_genes: list[str] = []
    errors: list[str] = []
    genes_to_query: list[str] = []
    retried_existing: list[dict[str, str]] = []

    for gene in genes:
        filename = f"stage3_{gene}.json"
        out_path = evidence_dir / filename
        if out_path.exists():
            reusable, reason = _existing_stage3_profile_reusable(out_path, gene)
            if reusable:
                skipped_existing.append(gene)
                continue
            retried_existing.append({"gene": gene, "reason": reason})
        genes_to_query.append(gene)

    if genes_to_query:
        worker_count = _stage3_chembl_worker_count(len(genes_to_query))
        query_args = [(gene, max_drugs, organism) for gene in genes_to_query]
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            stage3_results = list(executor.map(_query_stage3_gene_profile, query_args))
    else:
        stage3_results = []

    for gene, profile, error in stage3_results:
        if error or profile is None:
            failed_genes.append(gene)
            errors.append(error or f"ChEMBL {gene}: no profile returned")
            continue

        queried_genes.append(gene)
        profile_errors = profile.get("errors", [])
        if not isinstance(profile_errors, list):
            profile_errors = [str(profile_errors)] if profile_errors else []
        if profile_errors or not profile.get("executed", False):
            failed_genes.append(gene)

        stage3_payload = {
            "gene": gene,
            "gene_symbol": gene,
            "executed": bool(profile.get("executed", False)),
            "errors": profile_errors,
            "chembl": profile,
            "source": "chembl",
        }
        if profile.get("note"):
            stage3_payload["note"] = profile["note"]
        filename = f"stage3_{gene}.json"
        out_path = evidence_dir / filename
        out_path.write_text(
            json.dumps(stage3_payload, indent=2),
            encoding="utf-8",
        )
        saved_files.append(filename)
        logger.info("Stage 3 auto-saved: %s", filename)

    validation_raw = validate_stage3_gate.invoke({"data_dir": str(base)})
    try:
        validation = json.loads(validation_raw)
    except Exception:
        validation = {"success": False, "raw": validation_raw}

    validation_errors = validation.get("genes_with_errors") or []
    success = bool(validation.get("success")) and not failed_genes and not errors and not validation_errors
    return _as_json({
        "success": success,
        "total": len(genes),
        "queried_genes": queried_genes,
        "skipped_existing": skipped_existing,
        "retried_existing": retried_existing,
        "saved_files": saved_files,
        "failed_genes": failed_genes,
        "validation": validation,
        "errors": errors,
        "note": (
            "Stage 3 ChEMBL profiles saved and gate validated. "
            "Existing successful stage3 files were skipped; failed or incomplete files were retried."
        ) if success else (
            "Stage 3 batch completed but gate validation failed. "
            "Inspect validation.missing_genes, validation.genes_with_errors, and errors."
        ),
    })


def _chembl_fallback(gene_symbol: str, max_drugs: int = 10, organism: str = "human") -> list[dict]:
    """Compatibility wrapper for batch scripts that expect a plain list return."""
    return _query_chembl_drugs(gene_symbol, max_drugs, organism=organism)


def _load_existing_stage1_pair_payload(
    path: str | os.PathLike[str],
    ligand: str,
    receptor: str,
) -> dict[str, Any] | None:
    """Return reusable Stage 1 pair payload when the STRING result exists."""
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("string_ppi"), dict):
        return None
    payload_ligand = str(payload.get("ligand") or "").strip().upper()
    payload_receptor = str(payload.get("receptor") or "").strip().upper()
    if payload_ligand and payload_ligand != ligand:
        return None
    if payload_receptor and payload_receptor != receptor:
        return None
    return payload


def _stage1_string_worker_count(pair_count: int) -> int:
    """Return bounded worker count for Stage 1 STRING calls."""
    if pair_count <= 1:
        return 1
    try:
        configured = int(os.getenv("DRUG_TARGET_STAGE1_STRING_WORKERS", "5"))
    except ValueError:
        configured = 5
    return max(1, min(pair_count, configured))


def _stage1_pair_has_census_validation(
    path: str | os.PathLike[str],
    ligand: str,
    receptor: str,
) -> bool:
    """Return True when a Stage 1 pair file already carries Census validation."""
    payload = _load_existing_stage1_pair_payload(path, ligand, receptor)
    if not isinstance(payload, dict):
        return False
    census = payload.get("census_validation")
    if not isinstance(census, dict):
        return False
    return "executed" in census or "target_vs_rest" in census


def _sanitize_census_token(text: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in str(text or "")).strip("_")


def _census_csv_name(ligand: str, receptor: str, target_cell_type: str) -> str:
    return (
        f"census_{ligand.lower()}_{receptor.lower()}_"
        f"{_sanitize_census_token(target_cell_type)}.csv"
    )


def _save_census_validation_to_stage1_file(
    *,
    evidence_dir: Path,
    ligand: str,
    receptor: str,
    census_validation: dict[str, Any],
    input_disease: str,
    stage1_disease_resolution_mode: str,
) -> bool:
    json_path = evidence_dir / f"stage1_{ligand}--{receptor}.json"
    if not json_path.exists():
        logger.warning(
            "Cannot integrate Census CSV for %s--%s: Stage 1 JSON missing at %s",
            ligand,
            receptor,
            json_path,
        )
        return False
    try:
        stage1_data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(
            "Cannot integrate Census CSV for %s--%s: failed to parse %s: %s",
            ligand,
            receptor,
            json_path,
            exc,
        )
        return False
    if not isinstance(stage1_data, dict):
        logger.warning(
            "Cannot integrate Census CSV for %s--%s: Stage 1 JSON is not an object at %s",
            ligand,
            receptor,
            json_path,
        )
        return False

    payload = dict(census_validation)
    disease_used = str(payload.get("disease") or "")
    payload.setdefault("input_disease", input_disease)
    payload.setdefault(
        "disease_fallback_used",
        not disease_labels_equal(input_disease, disease_used),
    )
    payload.setdefault("disease_resolution_mode", stage1_disease_resolution_mode)
    stage1_data["census_validation"] = payload
    json_path.write_text(json.dumps(stage1_data, indent=2), encoding="utf-8")
    return True


def _integrate_existing_census_csvs(
    *,
    evidence_dir: Path,
    pairs: list[tuple[str, str]],
    disease: str,
    input_disease: str,
    existing_disease_context: dict[str, Any],
    target_cell_type: str,
    stage1_disease_resolution_mode: str,
) -> dict[str, Any]:
    from src.agents.drug_target.tools.stage1_normalization import (
        build_census_validation_from_csv,
    )

    if not _census_csv_reuse_provenance_matches(
        existing_disease_context,
        input_disease=input_disease,
        disease=disease,
        target_cell_type=target_cell_type,
    ):
        return {
            "integrated_pairs": [],
            "reused_csv": [],
        }

    integrated_pairs: list[tuple[str, str]] = []
    reused_csv: list[str] = []
    for ligand, receptor in pairs:
        try:
            validation = build_census_validation_from_csv(
                evidence_dir,
                ligand,
                receptor,
                csv_target_cell_type=target_cell_type,
                requested_target_cell_type=target_cell_type,
                resolved_target_cell_type=target_cell_type,
                disease=disease,
            )
        except Exception as exc:
            logger.warning(
                "Skipping Census CSV reuse for %s--%s from likely CSV %s: %s",
                ligand,
                receptor,
                _census_csv_name(ligand, receptor, target_cell_type),
                exc,
            )
            continue
        if not validation:
            continue
        saved = _save_census_validation_to_stage1_file(
            evidence_dir=evidence_dir,
            ligand=ligand,
            receptor=receptor,
            census_validation=validation,
            input_disease=input_disease,
            stage1_disease_resolution_mode=stage1_disease_resolution_mode,
        )
        if saved:
            integrated_pairs.append((ligand, receptor))
            reused_csv.append(
                str(
                    validation.get("csv_file")
                    or _census_csv_name(ligand, receptor, target_cell_type)
                )
            )

    return {
        "integrated_pairs": integrated_pairs,
        "reused_csv": reused_csv,
    }


def _run_single_pair_census_fallback(
    *,
    data_dir: Path,
    evidence_dir: Path,
    pairs: list[tuple[str, str]],
    disease: str,
    input_disease: str,
    target_cell_type: str,
    stage1_disease_resolution_mode: str,
    batch_error: str,
) -> dict[str, Any]:
    from src.agents.drug_target.tools.census_lr_validation_tools import (
        run_compare_census_lr_pair,
    )
    from src.agents.drug_target.tools.stage1_normalization import (
        build_census_validation_from_csv,
    )

    records: list[dict[str, Any]] = []
    first_disease_used = ""
    first_resolution_mode = ""
    for ligand, receptor in pairs:
        pair_label = f"{ligand}--{receptor}"
        csv_name = _census_csv_name(ligand, receptor, target_cell_type)
        csv_path = evidence_dir / csv_name
        record: dict[str, Any] = {
            "pair": pair_label,
            "executed": False,
            "csv_file": csv_name,
        }
        invoked_single_pair_tool = False
        try:
            if csv_path.exists():
                csv_path.unlink()
            invoked_single_pair_tool = True
            raw = run_compare_census_lr_pair.invoke({
                "data_dir": str(data_dir),
                "disease": disease,
                "gene_a": ligand,
                "gene_b": receptor,
                "target_cell_type": target_cell_type,
                "organism": "homo_sapiens",
                "census_version": _DEFAULT_CENSUS_VERSION,
                "output_csv": str(csv_path),
            })
            if isinstance(raw, str):
                try:
                    single_result = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"single-pair Census returned invalid JSON: {exc}") from exc
            else:
                single_result = raw
            if not isinstance(single_result, dict):
                raise ValueError(
                    f"single-pair Census returned non-object result: "
                    f"{type(single_result).__name__}"
                )
            tool_errors = single_result.get("errors")
            if isinstance(tool_errors, list):
                normalized_errors = [str(error) for error in tool_errors]
                if normalized_errors:
                    record["errors"] = normalized_errors
            elif tool_errors:
                record["errors"] = [str(tool_errors)]
            if single_result.get("message"):
                record["message"] = str(single_result["message"])
            if single_result.get("executed") is not True:
                failure_details = record.get("errors", [])
                if record.get("message"):
                    failure_details = [*failure_details, str(record["message"])]
                detail = "; ".join(failure_details) if failure_details else "executed was not true"
                raise ValueError(f"single-pair Census did not execute successfully: {detail}")

            disease_used = str(single_result.get("disease") or disease)
            requested_cell_type = str(
                single_result.get("requested_cell_type") or target_cell_type
            )
            resolved_cell_type = str(
                single_result.get("resolved_cell_type") or requested_cell_type
            )
            validation = build_census_validation_from_csv(
                evidence_dir,
                ligand,
                receptor,
                csv_target_cell_type=target_cell_type,
                requested_target_cell_type=requested_cell_type,
                resolved_target_cell_type=resolved_cell_type,
                disease=disease_used,
            )
            if not validation:
                raise ValueError(f"single-pair Census CSV was not usable: {csv_name}")

            validation = dict(validation)
            validation["source"] = "single_pair_fallback"
            validation["batch_error"] = batch_error
            resolution_mode = str(
                single_result.get("disease_resolution_mode")
                or stage1_disease_resolution_mode
            )
            saved = _save_census_validation_to_stage1_file(
                evidence_dir=evidence_dir,
                ligand=ligand,
                receptor=receptor,
                census_validation=validation,
                input_disease=input_disease,
                stage1_disease_resolution_mode=resolution_mode,
            )
            if not saved:
                raise ValueError(f"failed to save single-pair Census validation for {pair_label}")

            record["executed"] = True
            if not first_disease_used:
                first_disease_used = disease_used
            if not first_resolution_mode:
                first_resolution_mode = resolution_mode
        except Exception as exc:
            if invoked_single_pair_tool and csv_path.exists():
                try:
                    csv_path.unlink()
                except OSError as cleanup_exc:
                    logger.warning(
                        "Failed to remove rejected single-pair Census CSV %s: %s",
                        csv_path,
                        cleanup_exc,
                    )
            record["error"] = str(exc)
            logger.warning(
                "Single-pair Census fallback failed for %s from %s: %s",
                pair_label,
                csv_name,
                exc,
            )
        records.append(record)

    return {
        "records": records,
        "all_succeeded": bool(records) and all(record.get("executed") for record in records),
        "disease_used": first_disease_used,
        "disease_resolution_mode": first_resolution_mode,
    }


def _restore_single_pair_fallback_provenance(
    *,
    evidence_dir: Path,
    fallback_records: list[dict[str, Any]],
    batch_error: str,
    input_disease: str,
    stage1_disease_resolution_mode: str,
) -> None:
    for record in fallback_records:
        if not record.get("executed"):
            continue
        pair_label = str(record.get("pair") or "")
        if "--" not in pair_label:
            continue
        ligand, receptor = pair_label.split("--", 1)
        json_path = evidence_dir / f"stage1_{ligand}--{receptor}.json"
        try:
            stage1_data = json.loads(json_path.read_text(encoding="utf-8"))
            validation = stage1_data.get("census_validation")
            if not isinstance(validation, dict):
                continue
            validation["source"] = "single_pair_fallback"
            validation["batch_error"] = batch_error
            if record.get("csv_file"):
                validation["csv_file"] = record["csv_file"]
            _save_census_validation_to_stage1_file(
                evidence_dir=evidence_dir,
                ligand=ligand,
                receptor=receptor,
                census_validation=validation,
                input_disease=input_disease,
                stage1_disease_resolution_mode=stage1_disease_resolution_mode,
            )
        except Exception as exc:
            logger.warning(
                "Failed to restore single-pair Census fallback provenance for %s: %s",
                pair_label,
                exc,
            )


def _census_csv_reuse_provenance_matches(
    disease_context: dict[str, Any],
    *,
    input_disease: str,
    disease: str,
    target_cell_type: str,
) -> bool:
    """Return True when workspace metadata proves Census CSVs fit this request."""
    if not disease_context:
        return False

    labels_to_match = [input_disease, disease]
    for key in ("input_disease", "canonical_disease"):
        context_label = disease_context.get(key)
        if any(disease_labels_equal(context_label, label) for label in labels_to_match):
            break
    else:
        return False

    stage1_meta = disease_context.get("stage1")
    if not isinstance(stage1_meta, dict):
        return True

    stage1_target = str(stage1_meta.get("target_cell_type") or "").strip()
    if stage1_target and not disease_labels_equal(stage1_target, target_cell_type):
        return False

    requested = stage1_meta.get("requested_disease")
    if requested and not disease_labels_equal(requested, input_disease):
        return False

    disease_used = stage1_meta.get("disease_used")
    if disease_used and not disease_labels_equal(disease_used, disease):
        return False

    return True


def _stage1_aggregate_artifacts_exist(evidence_dir: Path) -> bool:
    """Return True when Stage 1 aggregate/filter outputs are already present."""
    required = (
        "stage1_evidence.json",
        "stage1_filter.json",
        "stage1_filter_results.json",
        "stage1_audit.json",
    )
    return all((evidence_dir / name).exists() for name in required)


def _query_stage1_string_pair(pair: tuple[str, str]) -> tuple[str, str, dict[str, Any], str | None]:
    """Query STRING for one pair and return a canonical Stage 1 payload."""
    ligand, receptor = pair
    pair_data: dict[str, Any] = {"ligand": ligand, "receptor": receptor}
    try:
        string_raw = query_string_ppi_pair.invoke({"gene_a": ligand, "gene_b": receptor})
        pair_data["string_ppi"] = json.loads(string_raw)
        return ligand, receptor, pair_data, None
    except Exception as exc:
        pair_data["string_ppi"] = {"interaction_found": False, "error": str(exc)}
        return ligand, receptor, pair_data, f"STRING {ligand}/{receptor}: {exc}"



def _try_load_parquet_module():
    """Try to load opentargets_parquet module. Returns module or None."""
    try:
        mod = _load_skill_module(
            "opentargets-database", "opentargets_parquet.py", "opentargets_parquet"
        )
        if mod.is_available():
            return mod
    except Exception as exc:
        logger.debug("Parquet module unavailable: %s", exc)
    return None


def _try_load_gwas_parquet_module():
    """Try to load gwas_parquet module. Returns module or None."""
    try:
        mod = _load_skill_module(
            "gwas-database", "gwas_parquet.py", "gwas_parquet"
        )
        if mod.is_available():
            return mod
    except Exception as exc:
        logger.debug("GWAS parquet module unavailable: %s", exc)
    return None


@tool
def query_opentargets_target(gene_symbol: str, disease: str) -> str:
    """Query OpenTargets for target-disease association, tractability, and safety."""
    return _as_json(query_opentargets_target_data(gene_symbol, disease))


@tool
def query_opentargets_known_drugs(disease: str) -> str:
    """Get known drugs for a disease from OpenTargets."""
    return _as_json(query_opentargets_known_drugs_data(disease))


@tool
def query_gwas_gene_trait(gene_symbol: str, disease: str) -> str:
    """Query GWAS Catalog for gene-trait associations."""
    return _as_json(query_gwas_gene_trait_data(gene_symbol, disease))


@tool
def query_stage2_gene_panel(
    gene_symbols: list[str],
    disease: str,
    selected_top3_genes: list[str] | None = None,
    data_dir: str = "",
) -> str:
    """Build Stage 2 evidence for all unique genes in one batch call.

    Full evidence data is **always** saved to ``<data_dir>/evidence/``.
    The tool returns a **compact summary** (gene-level stats) instead of
    the raw payloads to keep LangGraph checkpoint size small.
    Use ``load_evidence_files()`` to read the detailed per-gene JSON files.

    DO NOT call save_evidence for stage2_evidence.json, known_drugs.json,
    gene_manifest.json, or ot_*.json — this tool writes them automatically.
    """
    from src.agents.drug_target.tools.evidence_loader import _resolve_data_dir

    # Resolve data_dir with fallback to env var
    resolved_dir = _resolve_data_dir(data_dir)
    evidence_dir = resolved_dir / "evidence"
    stage2_disease, disease_warning = resolve_stage2_input_disease(evidence_dir, disease)

    bundle = build_stage2_gene_panel(
        gene_symbols,
        stage2_disease,
        selected_top3_genes=selected_top3_genes,
        data_dir=str(resolved_dir),
    )

    # Always persist full evidence to disk.
    written = write_stage2_artifacts(bundle, evidence_dir)
    logger.info("Stage 2 artifacts written (%d files) → %s", len(written), evidence_dir)

    # Return a lightweight summary so ToolMessage stays small.
    summary = summarize_stage2_bundle(bundle)
    if disease_warning:
        summary["warnings"] = [disease_warning]
        logger.warning(disease_warning)
    summary["evidence_dir"] = str(evidence_dir)
    summary["written_files_count"] = len(written)
    summary["note"] = (
        "Full evidence data saved to evidence/ directory. "
        "Use load_evidence_files() to read detailed per-gene payloads. "
        "Do NOT overwrite these files with save_evidence."
    )
    return _as_json(summary)


@tool
def run_stage1_batch(
    data_dir: str,
    disease: str,
    target_cell_type: str = "",
    enable_census: bool = True,
) -> str:
    """Run all Stage 1 queries for FEATURED L-R pairs and auto-save results.

    This is the Stage 1 equivalent of query_stage2_gene_panel: one tool call
    that queries KEGG, Reactome, STRING (and optionally CellxGene/Census)
    for every FEATURED pair and saves per-pair JSON files to disk.

    Call this AFTER compute_rubric_scores has produced assessment_results.json.

    Args:
        data_dir: Output directory containing lr_candidates.json and evidence/
        disease: Disease context (use Census-matched name from Phase 0)
        target_cell_type: Census-matched cell type for Census validation
        enable_census: Whether to run CellxGene Census queries (default True)
    """
    from src.agents.drug_target.tools.evidence_loader import _resolve_data_dir
    from src.agents.drug_target.tools.stage2_service import extract_lr_pairs

    base = _resolve_data_dir(data_dir)
    evidence_dir = base / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []

    # 1. Load FEATURED genes from assessment_results.json
    assessment_path = evidence_dir / "assessment_results.json"
    if not assessment_path.exists():
        return _as_json({
            "success": False,
            "error": "assessment_results.json not found. Run compute_rubric_scores first.",
        })

    try:
        assessment = json.loads(assessment_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return _as_json({"success": False, "error": f"Cannot parse assessment_results.json: {exc}"})

    existing_disease_context = load_disease_context(evidence_dir)
    assessment_disease = str(assessment.get("disease") or "").strip()
    input_disease = (
        assessment_disease
        or str(existing_disease_context.get("input_disease") or "").strip()
        or disease
    )

    raw_candidates = assessment.get("stage3_candidates", [])
    featured_genes: set[str] = set()
    for entry in raw_candidates:
        if isinstance(entry, dict):
            gene = str(entry.get("gene") or entry.get("gene_symbol") or "").strip().upper()
        else:
            gene = str(entry).strip().upper()
        if gene:
            featured_genes.add(gene)
    if not featured_genes:
        return _as_json({
            "success": True,
            "pairs_processed": 0,
            "note": "No featured genes (stage3_candidates empty). Nothing to do.",
        })

    # 2. Map FEATURED genes → L-R pairs from lr_candidates.json
    lr_path = base / "lr_candidates.json"
    if not lr_path.exists():
        return _as_json({"success": False, "error": "lr_candidates.json not found."})

    try:
        lr_data = json.loads(lr_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return _as_json({"success": False, "error": f"Cannot parse lr_candidates.json: {exc}"})

    all_pairs = extract_lr_pairs(lr_data)
    featured_pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for pair in all_pairs:
        ligand = str(pair.get("ligand") or pair.get("source") or "").strip().upper()
        receptor = str(pair.get("receptor") or pair.get("target") or "").strip().upper()
        if not ligand or not receptor:
            continue
        if ligand in featured_genes or receptor in featured_genes:
            key = (ligand, receptor)
            if key not in seen:
                seen.add(key)
                featured_pairs.append(key)

    if not featured_pairs:
        return _as_json({
            "success": True,
            "pairs_processed": 0,
            "featured_genes": sorted(featured_genes),
            "note": "No L-R pairs contain featured genes.",
        })

    logger.info("Stage 1 batch: %d featured pairs for genes %s", len(featured_pairs), featured_genes)

    # 3. Query Stage 1 STRING evidence for missing FEATURED pairs and auto-save.
    # Existing complete per-pair files are reused so partial reruns do not repeat
    # external STRING calls.
    saved_files: list[str] = []
    skipped_existing: list[str] = []
    pairs_to_query: list[tuple[str, str]] = []
    for ligand, receptor in featured_pairs:
        filename = f"stage1_{ligand}--{receptor}.json"
        out_path = evidence_dir / filename
        if _load_existing_stage1_pair_payload(out_path, ligand, receptor) is not None:
            skipped_existing.append(filename)
            continue
        pairs_to_query.append((ligand, receptor))

    if pairs_to_query:
        worker_count = _stage1_string_worker_count(len(pairs_to_query))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            stage1_results = list(executor.map(_query_stage1_string_pair, pairs_to_query))
    else:
        stage1_results = []

    for ligand, receptor, pair_data, error in stage1_results:
        if error:
            errors.append(error)
        filename = f"stage1_{ligand}--{receptor}.json"
        out_path = evidence_dir / filename
        out_path.write_text(json.dumps(pair_data, indent=2), encoding="utf-8")
        saved_files.append(filename)
        logger.info("Stage 1 auto-saved: %s", filename)

    # 4. Census batch validation (one Census open for all pairs)
    census_status = "skipped"
    stage1_disease_used = disease
    stage1_disease_resolution_mode = (
        "exact" if disease_labels_equal(input_disease, disease) else "provided_fallback"
    )
    census_reused_csv: list[str] = []
    census_single_fallback: list[dict[str, Any]] = []
    census_batch_error = ""
    if enable_census and target_cell_type:
        pairs_requiring_census = [
            (ligand, receptor)
            for ligand, receptor in featured_pairs
            if not _stage1_pair_has_census_validation(
                evidence_dir / f"stage1_{ligand}--{receptor}.json",
                ligand,
                receptor,
            )
        ]
        if pairs_requiring_census:
            csv_integration = _integrate_existing_census_csvs(
                evidence_dir=evidence_dir,
                pairs=pairs_requiring_census,
                disease=disease,
                input_disease=input_disease,
                existing_disease_context=existing_disease_context,
                target_cell_type=target_cell_type,
                stage1_disease_resolution_mode=stage1_disease_resolution_mode,
            )
            census_reused_csv = list(csv_integration["reused_csv"])
            integrated_pair_set = set(csv_integration["integrated_pairs"])
            pairs_requiring_census = [
                pair for pair in pairs_requiring_census if pair not in integrated_pair_set
            ]

        if not pairs_requiring_census:
            census_status = (
                "completed_from_existing_csv"
                if census_reused_csv
                else "skipped_existing"
            )
        else:
            try:
                from src.agents.drug_target.tools.census_batch_core import (
                    batch_census_lr_pairs,
                    write_census_csv,
                )
                # Create lightweight LLM for cell type / disease semantic matching
                try:
                    from src.agents.model import create_llm as _create_llm
                    _census_llm = _create_llm()
                except Exception:
                    _census_llm = None
                _batch_results, csv_results = batch_census_lr_pairs(
                    pairs_requiring_census,
                    disease=disease,
                    target_cell_type=target_cell_type,
                    organism="homo_sapiens",
                    census_version=_DEFAULT_CENSUS_VERSION,
                    llm=_census_llm,
                )
                for br in _batch_results:
                    if isinstance(br, dict) and br.get("disease"):
                        stage1_disease_used = str(br.get("disease") or disease)
                        stage1_disease_resolution_mode = str(
                            br.get("disease_resolution_mode")
                            or stage1_disease_resolution_mode
                        )
                        break
                for pair_key, csv_rows in csv_results.items():
                    if isinstance(pair_key, tuple) and len(pair_key) == 2 and csv_rows:
                        gene_a, gene_b = pair_key
                        csv_name = (
                            f"census_{gene_a.lower()}_{gene_b.lower()}_"
                            f"{target_cell_type.lower().replace(' ', '_')}.csv"
                        )
                        write_census_csv(evidence_dir / csv_name, csv_rows)
                # Save batch census results directly to per-pair stage1 JSONs
                # (bypasses CSV re-parsing which can fail on cell type name mismatch)
                for br in _batch_results:
                    ga = br.get("gene_a", "")
                    gb = br.get("gene_b", "")
                    if not ga or not gb:
                        continue
                    json_path = evidence_dir / f"stage1_{ga}--{gb}.json"
                    if not json_path.exists():
                        continue
                    try:
                        stage1_data = json.loads(json_path.read_text(encoding="utf-8"))
                        stage1_data["census_validation"] = {
                            "disease": br.get("disease", ""),
                            "input_disease": input_disease,
                            "disease_fallback_used": not disease_labels_equal(
                                input_disease,
                                br.get("disease", ""),
                            ),
                            "disease_resolution_mode": (
                                br.get("disease_resolution_mode")
                                or stage1_disease_resolution_mode
                            ),
                            "requested_cell_type": br.get("requested_cell_type", ""),
                            "resolved_cell_type": br.get("resolved_cell_type", ""),
                            "resolution_mode": br.get("resolution_mode", ""),
                            "executed": br.get("executed", False),
                            "errors": br.get("errors", []),
                            "target_vs_rest": br.get("target_vs_rest"),
                            "n_target_cells": br.get("n_target_cells", 0),
                            "n_rest_cells": br.get("n_rest_cells", 0),
                            "census_version": br.get("census_version", ""),
                            "source": "batch_census_direct",
                        }
                        json_path.write_text(
                            json.dumps(stage1_data, indent=2), encoding="utf-8",
                        )
                    except Exception as exc:
                        logger.warning(
                            "Failed to save census result for %s--%s: %s", ga, gb, exc,
                        )
                # Surface warning if Census validation failed for ALL pairs
                if _batch_results and all(
                    not r.get("pair_result", r).get("executed", False) for r in _batch_results
                ):
                    errors.append(
                        f"WARNING: Census validation executed=false for ALL "
                        f"{len(_batch_results)} pairs. Cell type '{target_cell_type}' "
                        f"likely failed to resolve in Census vocabulary."
                    )
                census_status = "completed"
            except Exception as exc:
                census_batch_error = str(exc)
                fallback = _run_single_pair_census_fallback(
                    data_dir=base,
                    evidence_dir=evidence_dir,
                    pairs=pairs_requiring_census,
                    disease=disease,
                    input_disease=input_disease,
                    target_cell_type=target_cell_type,
                    stage1_disease_resolution_mode=stage1_disease_resolution_mode,
                    batch_error=census_batch_error,
                )
                census_single_fallback = list(fallback["records"])
                if fallback.get("disease_used"):
                    stage1_disease_used = str(fallback["disease_used"])
                if fallback.get("disease_resolution_mode"):
                    stage1_disease_resolution_mode = str(fallback["disease_resolution_mode"])
                if fallback["all_succeeded"]:
                    census_status = "completed_with_single_pair_fallback"
                else:
                    any_fallback_succeeded = any(
                        record.get("executed") for record in census_single_fallback
                    )
                    if not any_fallback_succeeded:
                        errors.append(f"Census batch: {exc}")
                    for record in census_single_fallback:
                        if record.get("executed"):
                            continue
                        errors.append(
                            f"Census single-pair fallback {record.get('pair')}: "
                            f"{record.get('error', 'unknown error')}"
                        )
                    census_status = "partial_with_single_pair_fallback"

    workspace_reused = (
        not saved_files
        and census_status in {"skipped", "skipped_existing"}
        and not errors
        and _stage1_aggregate_artifacts_exist(evidence_dir)
    )

    # 5. Finalize: normalize per-pair files and rebuild aggregates
    finalize_status = "skipped"
    if workspace_reused:
        finalize_status = "skipped_existing"
    else:
        try:
            from src.agents.drug_target.tools.stage1_normalization import finalize_stage1_workspace
            finalize_stage1_workspace(
                data_dir,
                disease=disease,
                target_cell_type=target_cell_type or None,
                rerun_missing_census=enable_census,
                pair_subset=list(featured_pairs),
            )
            if census_single_fallback and census_batch_error:
                _restore_single_pair_fallback_provenance(
                    evidence_dir=evidence_dir,
                    fallback_records=census_single_fallback,
                    batch_error=census_batch_error,
                    input_disease=input_disease,
                    stage1_disease_resolution_mode=stage1_disease_resolution_mode,
                )
            finalize_status = "completed"
        except Exception as exc:
            errors.append(f"finalize_stage1_artifacts: {exc}")
            finalize_status = f"failed: {exc}"

    # 6. Auto-apply Stage 1 filter to update assessment_results.json
    filter_status = "skipped"
    filter_summary: dict[str, Any] = {}
    try:
        from src.agents.drug_target.tools.stage_logic import apply_stage1_filter
        filter_raw = apply_stage1_filter.invoke({"data_dir": data_dir})
        filter_summary = json.loads(filter_raw) if isinstance(filter_raw, str) else filter_raw
        filter_status = "applied" if filter_summary.get("success") else f"failed: {filter_summary.get('error')}"
        logger.info("Stage 1 filter auto-applied: %s", filter_status)
    except Exception as exc:
        errors.append(f"apply_stage1_filter: {exc}")
        filter_status = f"failed: {exc}"

    _finalize_ok = finalize_status in {"completed", "skipped_existing"}
    _filter_ok = filter_status == "applied"
    _all_ok = _finalize_ok and _filter_ok and not errors
    _success_note = (
        "Existing Stage 1 evidence and Census validation reused. "
        "Stage 1 filter was reapplied to the current assessment_results.json."
    ) if workspace_reused else (
        "Stage 1 evidence files auto-saved and filter applied. "
        "assessment_results.json updated with filtered stage3_candidates. "
        "Call validate_stage1_gate(data_dir) to confirm."
    )
    stage1_fallback_used = not disease_labels_equal(input_disease, stage1_disease_used)
    stage1_disease_metadata = {
        "requested_disease": input_disease,
        "disease_used": stage1_disease_used,
        "exact_match": not stage1_fallback_used and stage1_disease_resolution_mode == "exact",
        "fallback_used": stage1_fallback_used,
        "fallback_reason": (
            "CELLxGENE Census used a backend-compatible disease label different "
            "from the input disease."
            if stage1_fallback_used else ""
        ),
        "resolution_mode": stage1_disease_resolution_mode,
        "source": "cellxgene_census" if enable_census else "stage1",
        "target_cell_type": target_cell_type,
        "census_status": census_status,
    }
    disease_context = merge_disease_context(
        evidence_dir,
        input_disease=input_disease,
        stage1=stage1_disease_metadata,
    )
    try:
        assessment_for_context = json.loads(assessment_path.read_text(encoding="utf-8"))
        if isinstance(assessment_for_context, dict):
            assessment_for_context["disease"] = input_disease
            assessment_for_context["disease_context"] = disease_context
            assessment_path.write_text(
                json.dumps(assessment_for_context, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
    except Exception as exc:
        logger.warning("Failed to sync disease_context into assessment_results.json: %s", exc)
    disease_warnings = disease_context.get("warnings", [])
    if stage1_fallback_used:
        logger.warning(
            "Stage 1 disease fallback: input=%r, stage1=%r, mode=%s",
            input_disease,
            stage1_disease_used,
            stage1_disease_resolution_mode,
        )

    return _as_json({
        "success": _all_ok,
        "status": "success" if _all_ok else "partial",
        "featured_genes": sorted(featured_genes),
        "pairs_processed": len(featured_pairs),
        "saved_files": saved_files,
        "skipped_existing": skipped_existing,
        "census_reused_csv": census_reused_csv,
        "census_single_fallback": census_single_fallback,
        "census_batch_error": census_batch_error,
        "census_batch": census_status,
        "finalize": finalize_status,
        "finalize_status": finalize_status,
        "stage1_filter": filter_status,
        "filter_status": filter_status,
        "stage1_filter_summary": filter_summary,
        "disease_context": disease_context,
        "warnings": disease_warnings,
        "errors": errors if errors else [],
        "note": _success_note if _all_ok else (
            "Stage 1 batch completed with partial failures. Check finalize_status, "
            "filter_status, and errors for details. assessment_results.json may be stale."
        ),
    })


__all__ = [
    "query_cellxgene_lr_context",
    "list_census_diseases",
    "list_census_cell_types",
    "query_kegg_pathways",
    "query_reactome_pathways",
    "query_string_ppi_pair",
    "query_ensembl_vep_consequence",
    "query_opentargets_target",
    "query_opentargets_known_drugs",
    "query_gwas_gene_trait",
    "query_stage2_gene_panel",
    "query_chembl_target_profile",
    "query_pubmed_clinical_limitations",
    "run_stage1_batch",
    "run_stage3_batch",
]
