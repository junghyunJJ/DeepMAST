"""Stage-specific domain tool wrappers for the 4-stage funnel."""

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


def _load_skill_module(skill_name: str, script_name: str, module_name: str):
    script_path = _SKILLS_DIR / skill_name / "scripts" / script_name
    if not script_path.exists():
        raise FileNotFoundError(f"Skill script not found: {script_path}")
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module spec for {script_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
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

    disease_safe = disease.replace("'", "\\'")
    try:
        with cellxgene_census.open_soma() as census:
            obs = cellxgene_census.get_obs(
                census,
                organism,
                value_filter=f"is_primary_data == True and disease == '{disease_safe}'",
                column_names=["cell_type"],
            )
            if len(obs) == 0:
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
            vc = obs["cell_type"].value_counts().head(5)
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


def _chembl_fallback(gene_symbol: str, max_drugs: int) -> list[dict]:
    """Query ChEMBL for drugs targeting a gene (fallback when DrugBank unavailable)."""
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
            matches.append(
                {
                    "chembl_id": mol_id,
                    "drug_name": act.get("molecule_pref_name") or mol_id,
                    "target_gene": gene_symbol.upper(),
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
        root = helper._get_root()  # noqa: SLF001 - library helper exposes this method
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


@tool
def query_alphafold_plddt(uniprot_id: str) -> str:
    """Retrieve AlphaFold confidence summary (average pLDDT) by UniProt ID."""
    result = {
        "uniprot_id": uniprot_id,
        "executed": False,
        "entry_id": None,
        "mean_plddt": None,
        "errors": [],
    }
    api_url = f"https://alphafold.ebi.ac.uk/api/prediction/{uniprot_id}"
    try:
        meta_resp = requests.get(api_url, timeout=_TIMEOUT)
        meta_resp.raise_for_status()
        rows = meta_resp.json()
        if not rows:
            result["errors"].append(f"No AlphaFold prediction found for {uniprot_id}")
            return _as_json(result)

        entry = rows[0]
        entry_id = entry.get("entryId")
        if not entry_id:
            result["errors"].append("AlphaFold entryId missing")
            return _as_json(result)

        result["entry_id"] = entry_id
        # Use plddtDocUrl (v6+) with fallback to legacy confidenceUrl
        conf_url = (
            entry.get("plddtDocUrl")
            or entry.get("confidenceUrl")
            or f"https://alphafold.ebi.ac.uk/files/{entry_id}-confidence_v6.json"
        )
        conf_resp = requests.get(conf_url, timeout=_TIMEOUT)
        conf_resp.raise_for_status()
        conf = conf_resp.json()
        scores = conf.get("confidenceScore", [])
        if scores:
            result["mean_plddt"] = round(sum(scores) / len(scores), 3)
        result["executed"] = True
    except Exception as exc:
        result["errors"].append(f"AlphaFold query failed: {exc}")
    return _as_json(result)


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
        mod = _load_skill_module("opentargets-database", "query_opentargets.py", "query_opentargets")

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
        mod = _load_skill_module("opentargets-database", "query_opentargets.py", "query_opentargets")
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
        mod = _load_skill_module("gwas-database", "gwas_api.py", "gwas_api")

        # 1. Disease → EFO traits
        traits = mod.search_efo_traits(disease)
        result["efo_traits"] = traits[:5]

        # 2. Trait associations (if valid trait found)
        if traits and "error" not in traits[0]:
            efo_id = traits[0]["shortForm"]
            result["trait_associations"] = mod.get_trait_associations(efo_id, max_results=50)

        # 3. Gene-specific variants
        result["gene_associations"] = mod.get_gene_associations(gene_symbol)
        result["executed"] = True
    except Exception as exc:
        result["errors"].append(f"GWAS query failed: {exc}")
    return _as_json(result)


@tool
def run_diffdock_screen(
    protein_path: str,
    ligand_smiles: str,
    out_dir: str = "",
    samples_per_complex: int = 10,
) -> str:
    """Fail-soft DiffDock launcher placeholder for Stage 4 gating."""
    result = {
        "protein_path": protein_path,
        "ligand_smiles": ligand_smiles,
        "out_dir": out_dir,
        "samples_per_complex": samples_per_complex,
        "executed": False,
        "binding_affinity": None,
        "errors": [
            (
                "DiffDock execution is not available in this environment. "
                "Install DiffDock locally to enable in-silico docking."
            )
        ],
    }
    return _as_json(result)


__all__ = [
    "query_cellxgene_lr_context",
    "query_kegg_pathways",
    "query_reactome_pathways",
    "query_string_ppi_pair",
    "query_ensembl_vep_consequence",
    "query_opentargets_target",
    "query_opentargets_known_drugs",
    "query_gwas_gene_trait",
    "query_drugbank_target_profile",
    "query_pubmed_clinical_limitations",
    "query_alphafold_plddt",
    "run_diffdock_screen",
]

