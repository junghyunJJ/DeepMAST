"""Stage-specific domain tool wrappers for the 3-stage funnel."""

from __future__ import annotations

import importlib.util
import json
import logging
from pathlib import Path
from typing import Any

import re
import requests
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

_SKILLS_DIR = Path(__file__).resolve().parents[4] / "skills"
_TIMEOUT = 30

_module_cache: dict[tuple[str, str], Any] = {}


def _load_skill_module(skill_name: str, script_name: str, module_name: str):
    cache_key = (skill_name, script_name)
    if cache_key in _module_cache:
        return _module_cache[cache_key]
    script_path = _SKILLS_DIR / skill_name / "scripts" / script_name
    if not script_path.exists():
        raise FileNotFoundError(f"Skill script not found: {script_path}")
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module spec for {script_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _module_cache[cache_key] = mod
    return mod


def _as_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2)


def _trim_text(value: str, max_len: int = 2000) -> str:
    return value if len(value) <= max_len else value[:max_len] + "...[truncated]"


@tool
def query_cellxgene_lr_context(
    ligand: str,
    receptor: str,
    disease: str,
    organism: str = "homo_sapiens",
) -> str:
    """Query CELLxGENE census metadata for disease/cell-type context."""
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

    disease_safe = disease.replace("\\", "\\\\").replace("'", "\\'")
    try:
        with cellxgene_census.open_soma() as census:
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
        with cellxgene_census.open_soma() as census:
            summary_df = (
                census["census_info"]["summary_cell_counts"]
                .read(column_names=["organism", "category", "label", "total_cell_count"])
                .concat()
                .to_pandas()
            )
        org_display = organism.replace("_", " ").lower()
        mask = (
            (summary_df["organism"].str.lower() == org_display)
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


def _chembl_fallback(gene_symbol: str, max_drugs: int) -> list[dict]:
    """Query ChEMBL for drugs targeting a gene (fallback when DrugBank unavailable).

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
def query_drugbank_target_profile(gene_symbol: str, max_drugs: int = 10) -> str:
    """Retrieve drugs targeting a gene symbol (DrugBank primary, ChEMBL fallback)."""
    result = {
        "gene_symbol": gene_symbol,
        "executed": False,
        "matched_drugs": [],
        "source": None,
        "errors": [],
    }

    # --- Try DrugBank first ---
    try:
        mod = _load_skill_module("drugbank-database", "drugbank_helper.py", "drugbank_helper")
        helper = mod.DrugBankHelper()
        try:
            root = helper._get_root()  # noqa: SLF001
        except AttributeError:
            result["errors"].append("DrugBank helper API incompatible — _get_root() unavailable")
            raise
        ns = helper.NAMESPACE
        target_upper = gene_symbol.upper()
        matches = []
        for drug in root.findall("db:drug", ns):
            if len(matches) >= max(1, min(max_drugs, 25)):
                break
            drug_id_el = drug.find("db:drugbank-id[@primary='true']", ns)
            drug_name_el = drug.find("db:name", ns)
            drug_id = drug_id_el.text if drug_id_el is not None else None
            drug_name = drug_name_el.text if drug_name_el is not None else None
            if not drug_id:
                continue
            targets_el = drug.find("db:targets", ns)
            if targets_el is None:
                continue
            for target in targets_el.findall("db:target", ns):
                polypeptide = target.find("db:polypeptide", ns)
                if polypeptide is None:
                    continue
                gene_el = polypeptide.find("db:gene-name", ns)
                gene_name = gene_el.text if gene_el is not None else ""
                if gene_name and gene_name.upper() == target_upper:
                    matches.append(
                        {
                            "drugbank_id": drug_id,
                            "drug_name": drug_name,
                            "target_gene": gene_name,
                        }
                    )
                    break

        result["matched_drugs"] = matches
        result["source"] = "drugbank"
        result["executed"] = True
        return _as_json(result)
    except Exception as exc:
        result["errors"].append(f"DrugBank unavailable: {exc}")

    # --- Fallback to ChEMBL ---
    try:
        matches = _chembl_fallback(gene_symbol, max_drugs)
        result["matched_drugs"] = matches
        result["source"] = "chembl"
        result["executed"] = True
        result["errors"] = []  # clear DrugBank error on successful fallback
    except Exception as exc:
        result["errors"].append(f"ChEMBL fallback also failed: {exc}")

    return _as_json(result)


@tool
def query_pubmed_clinical_limitations(target_name: str, max_results: int = 5) -> str:
    """Search PubMed clinical-trial adverse event insights for a target."""
    result = {
        "target_name": target_name,
        "executed": False,
        "query": "",
        "papers": [],
        "errors": [],
    }
    query = f"\"{target_name}\"[tiab] AND \"Clinical Trial\"[pt] AND \"adverse event\"[tiab]"
    result["query"] = query
    try:
        _pubmed = _load_skill_module("pubmed-eutils-search", "search_pubmed.py", "search_pubmed")
        pub = _pubmed.search_pubmed(query=query, max_results=max(1, min(max_results, 20)))
        papers = pub.get("papers", []) if isinstance(pub, dict) else []
        result["papers"] = [
            {
                "pmid": row.get("pmid"),
                "title": row.get("title"),
                "year": row.get("year"),
            }
            for row in papers
        ]
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
    result = {
        "gene_symbol": gene_symbol, "disease": disease,
        "executed": False, "ensembl_id": None,
        "target_info": {}, "disease_evidence": [], "associations": [],
        "errors": [],
    }
    try:
        # Parquet-first, API fallback
        pq_mod = _try_load_parquet_module()
        mod = pq_mod or _load_skill_module(
            "opentargets-database", "query_opentargets.py", "query_opentargets"
        )

        # 1. Gene → Ensembl ID
        hits = mod.search_entities(gene_symbol, entity_types=["target"])
        if not hits:
            result["errors"].append(f"No OpenTargets target found for {gene_symbol}")
            return _as_json(result)
        ensembl_id = hits[0]["id"]
        result["ensembl_id"] = ensembl_id

        # 2. Target info (tractability, safety, top diseases)
        result["target_info"] = mod.get_target_info(ensembl_id, include_diseases=True)

        # 3. Disease → EFO ID, then evidence
        disease_hits = mod.search_entities(disease, entity_types=["disease"])
        if disease_hits:
            efo_id = disease_hits[0]["id"]
            result["efo_id"] = efo_id
            result["disease_evidence"] = mod.get_target_disease_evidence(ensembl_id, efo_id)

        # 4. All disease associations
        result["associations"] = mod.get_target_associations(ensembl_id, min_score=0.1)
        result["executed"] = True
    except Exception as exc:
        result["errors"].append(f"OpenTargets query failed: {exc}")
    return _as_json(result)


@tool
def query_opentargets_known_drugs(disease: str) -> str:
    """Get known drugs for a disease from OpenTargets."""
    result = {"disease": disease, "executed": False, "efo_id": None, "drugs": {}, "errors": []}
    try:
        # Parquet-first, API fallback
        pq_mod = _try_load_parquet_module()
        mod = pq_mod or _load_skill_module(
            "opentargets-database", "query_opentargets.py", "query_opentargets"
        )
        hits = mod.search_entities(disease, entity_types=["disease"])
        if not hits:
            result["errors"].append(f"No disease found for '{disease}'")
            return _as_json(result)
        efo_id = hits[0]["id"]
        result["efo_id"] = efo_id
        result["drugs"] = mod.get_known_drugs_for_disease(efo_id)
        result["executed"] = True
    except Exception as exc:
        result["errors"].append(f"OpenTargets drug query failed: {exc}")
    return _as_json(result)


@tool
def query_gwas_gene_trait(gene_symbol: str, disease: str) -> str:
    """Query GWAS Catalog for gene-trait associations."""
    result = {
        "gene_symbol": gene_symbol, "disease": disease,
        "executed": False, "efo_traits": [],
        "trait_associations": [], "gene_associations": [],
        "errors": [],
    }
    try:
        # Parquet-first, API fallback
        pq_mod = _try_load_gwas_parquet_module()
        mod = pq_mod or _load_skill_module("gwas-database", "gwas_api.py", "gwas_api")

        # 1. Disease → EFO traits (exact + synonym search for EFO/MONDO coverage)
        traits = mod.search_efo_traits(disease)
        # Cancer/carcinoma are common synonyms in ontologies; try both
        _synonyms = {"cancer": "carcinoma", "carcinoma": "cancer"}
        disease_lower = disease.lower()
        for old, new in _synonyms.items():
            if old in disease_lower:
                alt = disease_lower.replace(old, new)
                alt_traits = mod.search_efo_traits(alt)
                seen_ids = {t.get("shortForm") for t in traits}
                for t in alt_traits:
                    if t.get("shortForm") not in seen_ids and "error" not in t:
                        traits.append(t)
        result["efo_traits"] = traits[:5]

        # 2. Trait associations from ALL matching EFO/MONDO IDs
        #    Different ontologies (EFO vs MONDO) have different gene annotations
        all_trait_assocs: list[dict] = []
        seen_rsids: set[str] = set()
        for t in traits[:5]:
            if "error" in t:
                continue
            efo_id = t.get("shortForm", "")
            if not efo_id:
                continue
            for ta in mod.get_trait_associations(efo_id, max_results=500):
                rsid = ta.get("rsId", "")
                if rsid and rsid in seen_rsids:
                    continue
                if rsid:
                    seen_rsids.add(rsid)
                all_trait_assocs.append(ta)
        result["trait_associations"] = all_trait_assocs

        # 3. Gene-specific variants
        result["gene_associations"] = mod.get_gene_associations(gene_symbol)

        # 4. Disease-specific cross-filtering
        trait_assocs = result["trait_associations"]
        gene_assocs = result["gene_associations"]
        gene_upper = gene_symbol.upper()

        # Method A: trait SNPs where this gene is author-reported
        gene_in_trait = [
            ta for ta in trait_assocs
            if gene_upper in [g.upper() for g in ta.get("genes", [])]
        ]

        # Method B: gene SNPs whose rsId also appears in trait SNPs
        trait_rsids = {ta["rsId"] for ta in trait_assocs if ta.get("rsId")}
        gene_snps_in_disease = [
            ga for ga in gene_assocs
            if ga.get("rsId") in trait_rsids
        ]

        result["disease_specific_hits"] = {
            "gene_in_trait_associations": gene_in_trait,
            "gene_snps_in_disease": gene_snps_in_disease,
            "n_gene_in_trait": len(gene_in_trait),
            "n_gene_snps_in_disease": len(gene_snps_in_disease),
        }

        result["executed"] = True
    except Exception as exc:
        result["errors"].append(f"GWAS query failed: {exc}")
    return _as_json(result)


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
    "query_drugbank_target_profile",
    "query_pubmed_clinical_limitations",
]

