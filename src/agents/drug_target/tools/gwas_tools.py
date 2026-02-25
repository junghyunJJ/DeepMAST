"""GWAS Catalog REST API tool wrappers.

New implementation following skills/gwas-database/SKILL.md REST API patterns.
Reuses the reported+nearest weighted scoring concept from the existing
gwas_adapter.py but implemented cleanly using skill patterns.
"""

import json
import logging
import math
from typing import Optional

import requests
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

GWAS_API_BASE = "https://www.ebi.ac.uk/gwas/rest/api"
TIMEOUT = 30
HEADERS = {"Accept": "application/json"}


def _fetch_json(url: str, params: Optional[dict] = None) -> dict:
    """Fetch JSON from GWAS REST API with timeout and error handling."""
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        logger.warning(f"GWAS API request failed: {url} — {e}")
        return {}


def _resolve_trait_id(disease: str) -> Optional[str]:
    """Resolve free-text disease name to EFO trait URI via GWAS search."""
    url = f"{GWAS_API_BASE}/efoTraits/search/findByEfoTrait"
    data = _fetch_json(url, params={"trait": disease})
    traits = data.get("_embedded", {}).get("efoTraits", [])
    if traits:
        # Return the shortForm (e.g., "EFO_0000305")
        return traits[0].get("shortForm")
    return None


def _association_signal(pvalue: float) -> float:
    """Normalize p-value to [0, 1] score via -log10(pvalue)/12."""
    if pvalue <= 0:
        return 1.0
    return min(1.0, -math.log10(pvalue) / 12.0)


def _extract_gene_symbols(association: dict) -> tuple[list[str], list[str]]:
    """Extract reported and nearest gene symbols from an association.

    Returns:
        Tuple of (reported_genes, nearest_genes)
    """
    reported = []
    nearest = []

    # Reported genes (author-reported)
    strongest = association.get("strongestRiskAlleles", [])
    # Gene names often in riskAlleleName field or loci
    loci = association.get("loci", [])
    for locus in loci:
        for gene in locus.get("authorReportedGenes", []):
            name = gene.get("geneName", "")
            if name and name not in ("intergenic", "NR", ""):
                reported.append(name.upper())

    # Nearest/mapped genes from genomic contexts
    for snp in association.get("snps", []):
        for ctx in snp.get("genomicContexts", []):
            gene_obj = ctx.get("gene", {})
            name = gene_obj.get("geneName", "")
            if not name or name in ("intergenic", "NR", ""):
                continue
            is_closest = ctx.get("isClosestGene", False)
            is_upstream = ctx.get("isUpstream", False)
            is_downstream = ctx.get("isDownstream", False)
            distance = ctx.get("distance", 999999)

            if is_closest or distance == 0:
                nearest.append(name.upper())
            elif (is_upstream or is_downstream) and distance <= 50000:
                nearest.append(name.upper())

    return (list(set(reported)), list(set(nearest)))


def _fetch_associations_for_trait(trait_id: str, max_pages: int = 5) -> list[dict]:
    """Fetch associations for an EFO trait with pagination."""
    url = f"{GWAS_API_BASE}/efoTraits/{trait_id}/associations"
    all_assocs = []
    page = 0

    while page < max_pages:
        data = _fetch_json(url, params={"page": page, "size": 100})
        assocs = data.get("_embedded", {}).get("associations", [])
        if not assocs:
            break
        all_assocs.extend(assocs)

        # Check pagination
        page_info = data.get("page", {})
        total_pages = page_info.get("totalPages", 1)
        page += 1
        if page >= total_pages:
            break

    return all_assocs


@tool
def query_gwas_trait_associations(disease: str, gene_symbols: str) -> str:
    """Query GWAS Catalog for trait-associated variants linked to genes.

    Resolves disease to EFO trait, fetches paginated associations,
    then buckets by reported vs nearest gene with signal scoring.

    Args:
        disease: Disease name (e.g., "breast cancer")
        gene_symbols: Comma-separated gene symbols to check (e.g., "TGFB1,CD274,EGFR")

    Returns:
        JSON with per-gene GWAS signals (reported/nearest scores, hit counts, top variants)
    """
    genes = [g.strip().upper() for g in gene_symbols.split(",") if g.strip()]

    result = {
        "disease": disease,
        "trait_id": None,
        "genes_queried": genes,
        "gene_signals": {},
        "total_associations_scanned": 0,
        "errors": [],
    }

    # Resolve disease to trait
    trait_id = _resolve_trait_id(disease)
    if not trait_id:
        result["errors"].append(f"Could not resolve '{disease}' to GWAS trait")
        return json.dumps(result, indent=2)
    result["trait_id"] = trait_id

    # Fetch associations
    associations = _fetch_associations_for_trait(trait_id)
    result["total_associations_scanned"] = len(associations)

    # Initialize per-gene buckets
    gene_data: dict[str, dict] = {}
    for g in genes:
        gene_data[g] = {
            "reported_signals": [],
            "nearest_signals": [],
            "reported_hits": 0,
            "nearest_hits": 0,
            "top_variants": [],
        }

    # Bucket associations by gene
    for assoc in associations:
        pvalue = assoc.get("pvalue", 1.0)
        if pvalue is None:
            continue
        try:
            pval_float = float(pvalue)
        except (ValueError, TypeError):
            continue

        signal = _association_signal(pval_float)
        reported, nearest = _extract_gene_symbols(assoc)

        # Extract variant info
        risk_alleles = assoc.get("strongestRiskAlleles", [])
        variant_name = risk_alleles[0].get("riskAlleleName", "unknown") if risk_alleles else "unknown"

        for g in genes:
            if g in reported:
                gene_data[g]["reported_signals"].append(signal)
                gene_data[g]["reported_hits"] += 1
                if len(gene_data[g]["top_variants"]) < 5:
                    gene_data[g]["top_variants"].append({
                        "variant": variant_name,
                        "pvalue": pval_float,
                        "signal": round(signal, 3),
                        "type": "reported",
                    })
            if g in nearest:
                gene_data[g]["nearest_signals"].append(signal)
                gene_data[g]["nearest_hits"] += 1
                if len(gene_data[g]["top_variants"]) < 5:
                    gene_data[g]["top_variants"].append({
                        "variant": variant_name,
                        "pvalue": pval_float,
                        "signal": round(signal, 3),
                        "type": "nearest",
                    })

    # Aggregate signals
    for g in genes:
        d = gene_data[g]
        reported_avg = sum(d["reported_signals"]) / len(d["reported_signals"]) if d["reported_signals"] else 0.0
        nearest_avg = sum(d["nearest_signals"]) / len(d["nearest_signals"]) if d["nearest_signals"] else 0.0
        # Weighted: reported gene signals carry more weight
        combined = reported_avg * 0.7 + nearest_avg * 0.3 if (d["reported_signals"] or d["nearest_signals"]) else 0.0

        result["gene_signals"][g] = {
            "reported_signal": round(reported_avg, 4),
            "nearest_signal": round(nearest_avg, 4),
            "combined_signal": round(combined, 4),
            "reported_hits": d["reported_hits"],
            "nearest_hits": d["nearest_hits"],
            "top_variants": sorted(d["top_variants"], key=lambda x: x["pvalue"])[:5],
        }

    return json.dumps(result, indent=2)


@tool
def query_gwas_variant_details(rs_ids: str) -> str:
    """Query GWAS Catalog for variant details with genomic context.

    Args:
        rs_ids: Comma-separated rsIDs (e.g., "rs7903146,rs1234567")

    Returns:
        JSON with variant details including genomic context, mapped genes, functional class
    """
    ids = [r.strip() for r in rs_ids.split(",") if r.strip()]

    result = {
        "variants": {},
        "errors": [],
    }

    for rs_id in ids[:10]:  # Limit to 10 variants
        url = f"{GWAS_API_BASE}/singleNucleotidePolymorphisms/{rs_id}"
        data = _fetch_json(url)

        if not data:
            result["errors"].append(f"No data for {rs_id}")
            continue

        # Extract genomic contexts
        contexts = []
        for ctx in data.get("genomicContexts", []):
            gene = ctx.get("gene", {})
            contexts.append({
                "gene": gene.get("geneName", ""),
                "distance": ctx.get("distance"),
                "is_closest": ctx.get("isClosestGene", False),
                "is_intergenic": ctx.get("isIntergenic", False),
            })

        # Extract locations
        locations = []
        for loc in data.get("locations", []):
            locations.append({
                "chromosome": loc.get("chromosomeName"),
                "position": loc.get("chromosomePosition"),
                "region": loc.get("region", {}).get("name") if loc.get("region") else None,
            })

        result["variants"][rs_id] = {
            "functional_class": data.get("functionalClass", "unknown"),
            "merged": data.get("merged", False),
            "locations": locations,
            "genomic_contexts": contexts,
        }

    return json.dumps(result, indent=2)
