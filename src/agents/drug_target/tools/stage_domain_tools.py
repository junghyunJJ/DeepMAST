"""Stage-specific domain tool wrappers for the 3-stage funnel."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
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

logger = logging.getLogger(__name__)

_TIMEOUT = 30
_DEFAULT_CENSUS_VERSION = os.getenv("CENSUS_VERSION", "2025-11-08")

_CHEMBL_LOCK = threading.Lock()


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
        rows = client.search_pathways(gene_symbol) or []
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
    """Check STRING interaction evidence for a gene pair."""
    result = {
        "gene_a": gene_a,
        "gene_b": gene_b,
        "species": species,
        "required_score": required_score,
        "executed": False,
        "interaction_found": False,
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


def _fetch_drug_indications_and_mechanism(
    mod: Any, molecule_chembl_id: str
) -> tuple[list[dict], str | None]:
    """Fetch drug indications and mechanism of action for a molecule.

    Returns (indications_list, mechanism_of_action_string).
    """
    indications: list[dict] = []
    mechanism_of_action: str | None = None
    try:
        _drug_info, mechanisms, raw_indications = mod.get_drug_info(molecule_chembl_id)
        for ind in raw_indications:
            indications.append({
                "efo_term": ind.get("efo_term") or ind.get("mesh_heading") or "",
                "max_phase": ind.get("max_phase_for_ind"),
                "mesh_heading": ind.get("mesh_heading") or "",
            })
        if mechanisms:
            mechanism_of_action = mechanisms[0].get("mechanism_of_action")
    except Exception as exc:
        logger.debug("Indication/mechanism lookup failed for %s: %s", molecule_chembl_id, exc)
    return indications, mechanism_of_action


def _query_chembl_drugs(gene_symbol: str, max_drugs: int) -> list[dict]:
    """Query ChEMBL for drugs targeting a gene.

    Each matched compound includes indications and mechanism_of_action
    retrieved from the ChEMBL drug_indication and mechanism APIs.
    """
    mod = _load_skill_module("chembl-database", "example_queries.py", "chembl_queries")
    targets = mod.search_targets_by_name(gene_symbol)
    if not targets:
        return []

    seen: set[str] = set()
    matches: list[dict] = []
    cap = max(1, min(max_drugs, 25))

    for tgt in targets:
        target_id = tgt.get("target_chembl_id")
        if not target_id:
            continue
        activities = mod.get_bioactivity_data(target_id, activity_type="IC50", max_value=10000)
        for act in activities:
            mol_id = act.get("molecule_chembl_id")
            if not mol_id or mol_id in seen:
                continue
            seen.add(mol_id)

            # Fetch indication + mechanism for this compound
            indications, moa = _fetch_drug_indications_and_mechanism(mod, mol_id)

            matches.append(
                {
                    "chembl_id": mol_id,
                    "drug_name": act.get("molecule_pref_name") or mol_id,
                    "target_gene": gene_symbol.upper(),
                    "mechanism_of_action": moa,
                    "indications": indications,
                }
            )
            if len(matches) >= cap:
                return matches

    return matches


@tool
def query_chembl_target_profile(gene_symbol: str, max_drugs: int = 10) -> str:
    """Retrieve drugs targeting a gene symbol via ChEMBL."""
    result = {
        "gene_symbol": gene_symbol,
        "executed": False,
        "matched_drugs": [],
        "source": "chembl",
        "errors": [],
    }
    with _CHEMBL_LOCK:
        try:
            matches = _query_chembl_drugs(gene_symbol, max_drugs)
            result["matched_drugs"] = matches
            result["executed"] = True
        except (sqlite3.DatabaseError, sqlite3.OperationalError) as exc:
            logger.warning("ChEMBL cache corrupted (%s), clearing and retrying", exc)
            try:
                from chembl_webresource_client.settings import Settings
                Settings.Instance().clear_cache()
            except Exception:
                pass
            matches = _query_chembl_drugs(gene_symbol, max_drugs)
            result["matched_drugs"] = matches
            result["executed"] = True
        except Exception as exc:
            result["errors"].append(f"ChEMBL query failed: {exc}")
    return _as_json(result)



@tool
def query_pubmed_clinical_limitations(target_name: str, max_results: int = 5) -> str:
    """Search PubMed clinical-trial adverse event insights for a target.

    Uses a tiered query strategy: tries specific queries first, then
    progressively broader queries until results are found.
    """
    result = {
        "target_name": target_name,
        "executed": False,
        "query": "",
        "query_tier": "",
        "papers": [],
        "errors": [],
    }

    # Tiered query strategy: try progressively broader queries
    queries = [
        (
            f'"{target_name}"[tiab] AND "Clinical Trial"[pt] AND ("adverse event"[tiab] OR "safety"[tiab] OR "toxicity"[tiab])',
            "tier1_clinical_safety",
        ),
        (
            f'"{target_name}"[tiab] AND ("Clinical Trial"[pt] OR "Review"[pt]) AND ("therapeutic"[tiab] OR "treatment"[tiab])',
            "tier2_therapeutic",
        ),
        (
            f'"{target_name}"[tiab] AND ("drug target"[tiab] OR "inhibitor"[tiab] OR "therapy"[tiab])',
            "tier3_broad",
        ),
    ]

    try:
        _pubmed = _load_skill_module("pubmed-eutils-search", "search_pubmed.py", "search_pubmed")
        cap = max(1, min(max_results, 20))

        for query, tier in queries:
            result["query"] = query
            result["query_tier"] = tier
            pub = _pubmed.search_pubmed(query=query, max_results=cap)
            papers = pub.get("papers", []) if isinstance(pub, dict) else []
            if papers:
                result["papers"] = [
                    {
                        "pmid": row.get("pmid"),
                        "title": row.get("title"),
                        "year": row.get("year"),
                    }
                    for row in papers
                ]
                result["executed"] = True
                return _as_json(result)

        # All tiers returned 0 results
        result["executed"] = True
    except Exception as exc:
        result["errors"].append(f"PubMed query failed: {exc}")
    return _as_json(result)


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


__all__ = [
    "query_cellxgene_lr_context",
    "list_census_diseases",
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
]
