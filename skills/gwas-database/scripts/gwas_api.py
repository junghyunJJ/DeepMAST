"""
GWAS Catalog REST API Helper Functions

This module provides Python functions for querying the NHGRI-EBI GWAS Catalog
REST API. Returns structured data for trait-gene association lookups.

API Base URL: https://www.ebi.ac.uk/gwas/rest/api
Documentation: https://www.ebi.ac.uk/gwas/rest/docs/api

Dependencies: requests
"""

import requests
from time import sleep
from typing import Any, Optional


BASE_URL = "https://www.ebi.ac.uk/gwas/rest/api"
HEADERS = {"Content-Type": "application/json"}
TIMEOUT = 30
REQUEST_DELAY = 0.1  # seconds between requests to respect rate limits


def _get(url: str, params: Optional[dict] = None) -> dict:
    """Make a GET request with error handling and rate limiting.

    Args:
        url: Full URL to request.
        params: Optional query parameters.

    Returns:
        Parsed JSON response as dict.

    Raises:
        requests.exceptions.RequestException: On network/HTTP errors.
        ValueError: On JSON parse errors.
    """
    try:
        response = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
        sleep(REQUEST_DELAY)
        return response.json()
    except requests.exceptions.HTTPError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.reason}", "url": url}
    except requests.exceptions.ConnectionError:
        return {"error": "Connection error", "url": url}
    except requests.exceptions.Timeout:
        return {"error": "Request timed out", "url": url}
    except ValueError:
        return {"error": "Invalid JSON response", "url": url}


def _paginate(url: str, embedded_key: str, params: Optional[dict] = None,
              max_pages: int = 10) -> list[dict]:
    """Paginate through HAL-format responses.

    Args:
        url: Endpoint URL.
        embedded_key: Key inside _embedded (e.g. 'associations').
        params: Base query parameters.
        max_pages: Maximum number of pages to fetch.

    Returns:
        Accumulated list of items across all pages.
    """
    all_items: list[dict] = []
    params = dict(params) if params else {}
    params.setdefault("size", 100)

    for page in range(max_pages):
        params["page"] = page
        data = _get(url, params)

        if "error" in data:
            break

        items = data.get("_embedded", {}).get(embedded_key, [])
        if not items:
            break

        all_items.extend(items)

        # Check if we've reached the last page
        page_info = data.get("page", {})
        total_pages = page_info.get("totalPages", 1)
        if page + 1 >= total_pages:
            break

    return all_items


def search_efo_traits(trait_name: str) -> list[dict]:
    """Search for EFO trait terms by name.

    Uses findByEfoTrait for exact match first. If no results, falls back to
    scanning paginated efoTraits list with case-insensitive substring matching.

    Args:
        trait_name: Disease or trait name to search (e.g. 'type 2 diabetes mellitus').

    Returns:
        List of matching traits with keys: shortForm, trait, uri.

    Example:
        >>> results = search_efo_traits('type 2 diabetes mellitus')
        >>> results[0]['shortForm']  # 'MONDO_0005148'
    """
    def _format(t: dict) -> dict:
        return {
            "shortForm": t.get("shortForm", ""),
            "trait": t.get("trait", ""),
            "uri": t.get("uri", ""),
        }

    # 1. Try exact match via findByEfoTrait
    url = f"{BASE_URL}/efoTraits/search/findByEfoTrait"
    params = {"trait": trait_name}
    data = _get(url, params)

    if "error" not in data:
        traits = data.get("_embedded", {}).get("efoTraits", [])
        if traits:
            return [_format(t) for t in traits]

    # 2. Fallback: scan paginated efoTraits with client-side substring filter
    #    Limited to first 1000 traits to avoid long scan times.
    needle = trait_name.lower()
    matches: list[dict] = []
    for page in range(2):  # scan up to 1000 traits
        data = _get(f"{BASE_URL}/efoTraits", {"size": 500, "page": page})
        if "error" in data:
            break
        for t in data.get("_embedded", {}).get("efoTraits", []):
            if needle in t.get("trait", "").lower():
                matches.append(_format(t))
        total_pages = data.get("page", {}).get("totalPages", 1)
        if page + 1 >= total_pages:
            break
        if len(matches) >= 20:
            break

    return matches if matches else [{"error": f"No traits found for '{trait_name}'"}]


def get_trait_associations(efo_id: str, p_threshold: float = 5e-8,
                           max_results: int = 100) -> list[dict]:
    """Get SNP-trait associations for an EFO trait, filtered by p-value.

    Args:
        efo_id: EFO identifier (e.g. 'EFO_0001360').
        p_threshold: Maximum p-value to include (default: genome-wide 5e-8).
        max_results: Maximum number of associations to return.

    Returns:
        List of association dicts with keys: rsId, pvalue, pvalueMantissa,
        pvalueExponent, riskAllele, orPerCopyNum, betaNum, betaUnit,
        genes, studyId, trait.
    """
    url = f"{BASE_URL}/efoTraits/{efo_id}/associations"
    raw = _paginate(url, "associations")

    results: list[dict] = []
    for assoc in raw:
        pvalue = assoc.get("pvalue")
        if pvalue is None:
            # Try to reconstruct from mantissa/exponent
            mantissa = assoc.get("pvalueMantissa")
            exponent = assoc.get("pvalueExponent")
            if mantissa is not None and exponent is not None:
                try:
                    pvalue = float(mantissa) * (10 ** int(exponent))
                except (ValueError, TypeError):
                    continue
            else:
                continue

        try:
            pval_float = float(pvalue)
        except (ValueError, TypeError):
            continue

        if pval_float > p_threshold:
            continue

        # Extract gene names from loci -> strongestRiskAlleles or SNP links
        genes: list[str] = []
        for locus in assoc.get("loci", []):
            for allele in locus.get("strongestRiskAlleles", []):
                risk_allele = allele.get("riskAlleleName", "")
                if risk_allele:
                    # Risk allele format is typically "rs12345-A"
                    pass
            for gene_entry in locus.get("authorReportedGenes", []):
                gene_name = gene_entry.get("geneName", "")
                if gene_name and gene_name not in genes:
                    genes.append(gene_name)

        results.append({
            "rsId": assoc.get("rsId", ""),
            "pvalue": pval_float,
            "pvalueMantissa": assoc.get("pvalueMantissa"),
            "pvalueExponent": assoc.get("pvalueExponent"),
            "riskAllele": assoc.get("strongestAllele", ""),
            "orPerCopyNum": assoc.get("orPerCopyNum"),
            "betaNum": assoc.get("betaNum"),
            "betaUnit": assoc.get("betaUnit", ""),
            "genes": genes,
            "studyId": assoc.get("studyId", ""),
            "trait": assoc.get("efoTrait", ""),
        })

        if len(results) >= max_results:
            break

    return results


def get_gene_associations(gene_name: str) -> list[dict]:
    """Get SNPs and their associations for a gene.

    Args:
        gene_name: HGNC gene symbol (e.g. 'TCF7L2').

    Returns:
        List of SNP dicts with keys: rsId, functionalClass, locations,
        associations (list of trait/pvalue pairs).
    """
    url = f"{BASE_URL}/singleNucleotidePolymorphisms/search/findByGene"
    params = {"geneName": gene_name}
    data = _get(url, params)

    if "error" in data:
        return [data]

    snps = data.get("_embedded", {}).get("singleNucleotidePolymorphisms", [])
    results: list[dict] = []

    for snp in snps:
        locations = []
        for loc in snp.get("locations", []):
            locations.append({
                "chromosome": loc.get("chromosomeName", ""),
                "position": loc.get("chromosomePosition"),
                "region": loc.get("region", {}).get("name", "") if loc.get("region") else "",
            })

        # Follow link to associations if available
        assoc_link = snp.get("_links", {}).get("associations", {}).get("href", "")
        associations: list[dict] = []
        if assoc_link:
            assoc_data = _get(assoc_link)
            if "error" not in assoc_data:
                for a in assoc_data.get("_embedded", {}).get("associations", []):
                    associations.append({
                        "trait": a.get("efoTrait", ""),
                        "pvalue": a.get("pvalue"),
                        "riskAllele": a.get("strongestAllele", ""),
                    })

        results.append({
            "rsId": snp.get("rsId", ""),
            "functionalClass": snp.get("functionalClass", ""),
            "locations": locations,
            "associations": associations,
        })

    return results


def get_variant_info(rs_id: str) -> dict:
    """Get detailed information for a variant.

    Args:
        rs_id: dbSNP rsID (e.g. 'rs7903146').

    Returns:
        Dict with keys: rsId, functionalClass, merged, locations,
        genomicContexts (nearby genes).
    """
    url = f"{BASE_URL}/singleNucleotidePolymorphisms/{rs_id}"
    data = _get(url)

    if "error" in data:
        return data

    locations = []
    for loc in data.get("locations", []):
        locations.append({
            "chromosome": loc.get("chromosomeName", ""),
            "position": loc.get("chromosomePosition"),
            "region": loc.get("region", {}).get("name", "") if loc.get("region") else "",
        })

    genomic_contexts = []
    for ctx in data.get("genomicContexts", []):
        gene = ctx.get("gene", {})
        genomic_contexts.append({
            "geneName": gene.get("geneName", ""),
            "distance": ctx.get("distance"),
            "isIntergenic": ctx.get("isIntergenic", False),
            "isUpstream": ctx.get("isUpstream", False),
            "isDownstream": ctx.get("isDownstream", False),
        })

    return {
        "rsId": data.get("rsId", ""),
        "functionalClass": data.get("functionalClass", ""),
        "merged": data.get("merged", False),
        "lastUpdateDate": data.get("lastUpdateDate", ""),
        "locations": locations,
        "genomicContexts": genomic_contexts,
    }


def get_study_info(study_id: str) -> dict:
    """Get metadata for a GWAS study.

    Args:
        study_id: GWAS Catalog accession (e.g. 'GCST001795').

    Returns:
        Dict with keys: accessionId, title, publicationInfo, initialSampleSize,
        replicationSampleSize, genotypingTechnologies.
    """
    url = f"{BASE_URL}/studies/{study_id}"
    data = _get(url)

    if "error" in data:
        return data

    return {
        "accessionId": data.get("accessionId", ""),
        "title": data.get("title", ""),
        "publicationInfo": data.get("publicationInfo", {}),
        "initialSampleSize": data.get("initialSampleSize", ""),
        "replicationSampleSize": data.get("replicationSampleSize", ""),
        "genotypingTechnologies": [
            t.get("genotypingTechnology", "")
            for t in data.get("genotypingTechnologies", [])
        ],
    }


if __name__ == "__main__":
    print("=== GWAS Catalog API Test ===\n")

    # Search for a trait
    print("Searching for 'type 2 diabetes' traits...")
    traits = search_efo_traits("type 2 diabetes")
    for t in traits[:3]:
        print(f"  {t.get('shortForm')}: {t.get('trait')}")

    # Get associations for the first trait
    if traits and "error" not in traits[0]:
        efo_id = traits[0]["shortForm"]
        print(f"\nFetching associations for {efo_id}...")
        assocs = get_trait_associations(efo_id, max_results=5)
        for a in assocs[:3]:
            print(f"  {a['rsId']}: p={a['pvalue']:.2e}, genes={a['genes']}")

    # Get gene associations
    print("\nSearching gene associations for TCF7L2...")
    gene_snps = get_gene_associations("TCF7L2")
    if gene_snps and "error" not in gene_snps[0]:
        print(f"  Found {len(gene_snps)} SNPs")
