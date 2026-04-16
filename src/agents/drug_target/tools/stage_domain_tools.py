"""Stage-specific domain tool wrappers for the 3-stage funnel."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from typing import Any

import os
import re
import requests
from langchain_core.tools import tool

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


@tool
def query_chembl_target_profile(
    gene_symbol: str,
    max_drugs: int = 10,
    organism: str = "human",
) -> str:
    """Retrieve drugs targeting a gene symbol via ChEMBL."""
    result = {
        "gene_symbol": gene_symbol,
        "executed": False,
        "matched_drugs": [],
        "source": "chembl",
        "errors": [],
    }
    # P2-3: BOTH global declarations now inside the lock.
    # Pre-fix: `global _chembl_consecutive_failures` was outside, and the variable was
    # read on line 521 without holding the lock. Benign under LangGraph serialization
    # but creates a race window if concurrency is added later.
    with _CHEMBL_LOCK:
        global _chembl_consecutive_failures, _chembl_last_failure_time
        # Circuit breaker: skip if too many consecutive failures,
        # but auto-reset after cooldown period
        if _chembl_consecutive_failures >= _CHEMBL_MAX_CONSECUTIVE:
            elapsed = time.time() - _chembl_last_failure_time
            if elapsed < _CHEMBL_COOLDOWN_SECONDS:
                result["errors"].append(
                    f"circuit_breaker_open: {_chembl_consecutive_failures} consecutive failures"
                )
                result["note"] = f"ChEMBL API circuit breaker open - no drug data retrieved"
                return _as_json(result)
            else:
                logger.info(
                    "ChEMBL circuit breaker cooldown elapsed (%.0fs), resetting and retrying",
                    elapsed,
                )
                _chembl_consecutive_failures = 0
        try:
            matches = _query_chembl_drugs(gene_symbol, max_drugs, organism=organism)
            result["matched_drugs"] = matches
            result["executed"] = True
            _chembl_consecutive_failures = 0
        except LocalDataRequiredError as exc:
            result["errors"].append(str(exc))
        except (sqlite3.DatabaseError, sqlite3.OperationalError) as exc:
            logger.warning("ChEMBL cache corrupted (%s), clearing and retrying", exc)
            try:
                from chembl_webresource_client.settings import Settings
                Settings.Instance().clear_cache()
            except Exception:
                pass
            try:
                matches = _query_chembl_drugs(gene_symbol, max_drugs, organism=organism)
                result["matched_drugs"] = matches
                result["executed"] = True
                _chembl_consecutive_failures = 0
            except Exception as exc2:
                _chembl_consecutive_failures += 1
                _chembl_last_failure_time = time.time()
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
                    _chembl_consecutive_failures = 0
                except Exception:
                    _chembl_consecutive_failures += 1
                    _chembl_last_failure_time = time.time()
                    result["errors"].append(f"ChEMBL {status_code} after retry: {exc}")
            else:
                _chembl_consecutive_failures += 1
                _chembl_last_failure_time = time.time()
                result["errors"].append(f"ChEMBL HTTP {status_code}: {exc}")
        except Exception as exc:
            _chembl_consecutive_failures += 1
            _chembl_last_failure_time = time.time()
            result["errors"].append(f"ChEMBL query failed: {exc}")
    return _as_json(result)


def _chembl_fallback(gene_symbol: str, max_drugs: int = 10, organism: str = "human") -> list[dict]:
    """Compatibility wrapper for batch scripts that expect a plain list return."""
    return _query_chembl_drugs(gene_symbol, max_drugs, organism=organism)



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

    bundle = build_stage2_gene_panel(
        gene_symbols,
        disease,
        selected_top3_genes=selected_top3_genes,
        data_dir=str(resolved_dir),
    )

    # Always persist full evidence to disk.
    evidence_dir = resolved_dir / "evidence"
    written = write_stage2_artifacts(bundle, evidence_dir)
    logger.info("Stage 2 artifacts written (%d files) → %s", len(written), evidence_dir)

    # Return a lightweight summary so ToolMessage stays small.
    summary = summarize_stage2_bundle(bundle)
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

    # 3. Query Stage 1 databases for each FEATURED pair and auto-save
    saved_files: list[str] = []
    for ligand, receptor in featured_pairs:
        pair_data: dict[str, Any] = {"ligand": ligand, "receptor": receptor}

        # STRING PPI
        try:
            string_raw = query_string_ppi_pair.invoke({"gene_a": ligand, "gene_b": receptor})
            pair_data["string_ppi"] = json.loads(string_raw)
        except Exception as exc:
            pair_data["string_ppi"] = {"interaction_found": False, "error": str(exc)}
            errors.append(f"STRING {ligand}/{receptor}: {exc}")

        # AUTO-SAVE per-pair file to disk
        filename = f"stage1_{ligand}--{receptor}.json"
        out_path = evidence_dir / filename
        out_path.write_text(json.dumps(pair_data, indent=2), encoding="utf-8")
        saved_files.append(filename)
        logger.info("Stage 1 auto-saved: %s", filename)

    # 4. Census batch validation (one Census open for all pairs)
    census_status = "skipped"
    if enable_census and target_cell_type:
        try:
            from src.agents.drug_target.tools.census_batch_core import (
                batch_census_lr_pairs,
                write_census_csv,
            )
            pairs_list = [list(pair) for pair in featured_pairs]
            # Create lightweight LLM for cell type / disease semantic matching
            try:
                from src.agents.model import create_llm as _create_llm
                _census_llm = _create_llm()
            except Exception:
                _census_llm = None
            _batch_results, csv_results = batch_census_lr_pairs(
                pairs_list,
                disease=disease,
                target_cell_type=target_cell_type,
                organism="homo_sapiens",
                census_version=_DEFAULT_CENSUS_VERSION,
                llm=_census_llm,
            )
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
            errors.append(f"Census batch: {exc}")
            census_status = f"failed: {exc}"

    # 5. Finalize: normalize per-pair files and rebuild aggregates
    finalize_status = "skipped"
    try:
        from src.agents.drug_target.tools.stage1_normalization import finalize_stage1_workspace
        finalize_stage1_workspace(
            data_dir,
            disease=disease,
            target_cell_type=target_cell_type or None,
            rerun_missing_census=enable_census,
            pair_subset=list(featured_pairs),
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

    return _as_json({
        "success": True,
        "featured_genes": sorted(featured_genes),
        "pairs_processed": len(featured_pairs),
        "saved_files": saved_files,
        "census_batch": census_status,
        "finalize": finalize_status,
        "stage1_filter": filter_status,
        "stage1_filter_summary": filter_summary,
        "errors": errors if errors else [],
        "note": (
            "Stage 1 evidence files auto-saved and filter applied. "
            "assessment_results.json updated with filtered stage3_candidates. "
            "Call validate_stage1_gate(data_dir) to confirm."
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
]
