#!/usr/bin/env python3
"""
Open Targets Platform GraphQL Query Helper

This script provides reusable functions for querying the Open Targets Platform
GraphQL API. Use these functions to retrieve target, disease, drug, and
association data.

Dependencies: requests (pip install requests)
"""

import requests
import json
from typing import Dict, List, Optional, Any


# API endpoint
BASE_URL = "https://api.platform.opentargets.org/api/v4/graphql"


def execute_query(query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Execute a GraphQL query against the Open Targets Platform API.

    Args:
        query: GraphQL query string
        variables: Optional dictionary of variables for the query

    Returns:
        Dictionary containing the API response data

    Raises:
        Exception if the API request fails or returns errors
    """
    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    try:
        response = requests.post(BASE_URL, json=payload, timeout=30)

        if response.status_code != 200:
            try:
                error_body = response.json()
            except Exception:
                error_body = response.text[:500]
            raise Exception(
                f"API request failed with HTTP {response.status_code}: {error_body}"
            )

        data = response.json()

        if "errors" in data:
            raise Exception(f"GraphQL errors: {data['errors']}")

        return data.get("data", {})

    except requests.exceptions.RequestException as e:
        raise Exception(f"API request failed: {str(e)}")


def search_entities(query_string: str, entity_types: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Search for targets, diseases, or drugs by name or identifier.

    Args:
        query_string: Search term (e.g., "BRCA1", "alzheimer", "aspirin")
        entity_types: Optional list to filter by entity type ["target", "disease", "drug"]

    Returns:
        List of search results with id, name, entity type, and description
    """
    query = """
      query search($queryString: String!, $entityNames: [String!]) {
        search(queryString: $queryString, entityNames: $entityNames, page: {index: 0, size: 10}) {
          hits {
            id
            entity
            name
            description
          }
        }
      }
    """

    variables = {"queryString": query_string}
    if entity_types:
        variables["entityNames"] = entity_types

    result = execute_query(query, variables)
    return result.get("search", {}).get("hits", [])


def get_target_info(ensembl_id: str, include_diseases: bool = False) -> Dict[str, Any]:
    """
    Retrieve comprehensive information about a target gene.

    Args:
        ensembl_id: Ensembl gene ID (e.g., "ENSG00000157764")
        include_diseases: Whether to include top associated diseases

    Returns:
        Dictionary with target information including tractability, safety, expression
    """
    disease_fragment = """
      associatedDiseases(page: {index: 0, size: 10}) {
        rows {
          disease {
            id
            name
          }
          score
          datatypeScores {
            id
            score
          }
        }
      }
    """ if include_diseases else ""

    query = f"""
      query targetInfo($ensemblId: String!) {{
        target(ensemblId: $ensemblId) {{
          id
          approvedSymbol
          approvedName
          biotype
          functionDescriptions

          tractability {{
            label
            modality
            value
          }}

          safetyLiabilities {{
            event
            effects {{
              dosing
              direction
            }}
            biosamples {{
              tissueId
              tissueLabel
              cellLabel
            }}
          }}

          geneticConstraint {{
            constraintType
            score
            exp
            obs
          }}

          {disease_fragment}
        }}
      }}
    """

    result = execute_query(query, {"ensemblId": ensembl_id})
    return result.get("target", {})


def get_disease_info(efo_id: str, include_targets: bool = False) -> Dict[str, Any]:
    """
    Retrieve information about a disease.

    Args:
        efo_id: EFO disease identifier (e.g., "EFO_0000249")
        include_targets: Whether to include top associated targets

    Returns:
        Dictionary with disease information
    """
    target_fragment = """
      associatedTargets(page: {index: 0, size: 10}) {
        rows {
          target {
            id
            approvedSymbol
            approvedName
          }
          score
          datatypeScores {
            id
            score
          }
        }
      }
    """ if include_targets else ""

    query = f"""
      query diseaseInfo($efoId: String!) {{
        disease(efoId: $efoId) {{
          id
          name
          description
          therapeuticAreas {{
            id
            name
          }}
          synonyms {{
            terms
          }}
          {target_fragment}
        }}
      }}
    """

    result = execute_query(query, {"efoId": efo_id})
    return result.get("disease", {})


def get_target_disease_evidence(ensembl_id: str, efo_id: str,
                                  datasource_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Retrieve evidence linking a target to a disease.

    Args:
        ensembl_id: Ensembl gene ID
        efo_id: EFO disease identifier
        datasource_ids: Optional filter by data source (e.g., ["chembl", "europepmc"])

    Returns:
        List of evidence records with scores and sources
    """
    query = """
      query evidences($ensemblId: String!, $efoId: String!, $datasourceIds: [String!]) {
        disease(efoId: $efoId) {
          evidences(ensemblIds: [$ensemblId], datasourceIds: $datasourceIds, size: 100) {
            rows {
              datasourceId
              datatypeId
              score
              targetFromSourceId
              studyId
              literature
              cohortPhenotypes
            }
          }
        }
      }
    """

    variables = {"ensemblId": ensembl_id, "efoId": efo_id}
    if datasource_ids:
        variables["datasourceIds"] = datasource_ids

    result = execute_query(query, variables)
    return result.get("disease", {}).get("evidences", {}).get("rows", [])


def get_known_drugs_for_disease(efo_id: str) -> Dict[str, Any]:
    """
    Get drugs known to be used for a disease.

    Args:
        efo_id: EFO disease identifier

    Returns:
        Dictionary with drug information including phase, targets, and status
    """
    query = """
      query knownDrugs($efoId: String!) {
        disease(efoId: $efoId) {
          knownDrugs {
            uniqueDrugs
            uniqueTargets
            rows {
              drug {
                id
                name
                drugType
                maximumClinicalTrialPhase
              }
              target {
                id
                approvedSymbol
              }
              phase
              status
              mechanismOfAction
            }
          }
        }
      }
    """

    result = execute_query(query, {"efoId": efo_id})
    return result.get("disease", {}).get("knownDrugs", {})


def get_drug_info(chembl_id: str) -> Dict[str, Any]:
    """
    Retrieve information about a drug.

    Args:
        chembl_id: ChEMBL identifier (e.g., "CHEMBL25")

    Returns:
        Dictionary with drug information
    """
    query = """
      query drugInfo($chemblId: String!) {
        drug(chemblId: $chemblId) {
          id
          name
          synonyms
          drugType
          maximumClinicalTrialPhase
          hasBeenWithdrawn
          mechanismsOfAction {
            rows {
              actionType
              mechanismOfAction
              targets {
                id
                approvedSymbol
              }
            }
          }
          indications {
            count
            rows {
              disease {
                id
                name
              }
              maxPhaseForIndication
            }
          }
        }
      }
    """

    result = execute_query(query, {"chemblId": chembl_id})
    return result.get("drug", {})


def get_target_associations(ensembl_id: str, min_score: float = 0.0) -> List[Dict[str, Any]]:
    """
    Get all disease associations for a target, filtered by minimum score.

    Args:
        ensembl_id: Ensembl gene ID
        min_score: Minimum association score (0-1) to include

    Returns:
        List of disease associations with scores
    """
    query = """
      query targetAssociations($ensemblId: String!) {
        target(ensemblId: $ensemblId) {
          associatedDiseases(page: {index: 0, size: 100}) {
            count
            rows {
              disease {
                id
                name
              }
              score
              datatypeScores {
                id
                score
              }
            }
          }
        }
      }
    """

    result = execute_query(query, {"ensemblId": ensembl_id})
    associations = result.get("target", {}).get("associatedDiseases", {}).get("rows", [])

    # Filter by minimum score
    return [assoc for assoc in associations if assoc.get("score", 0) >= min_score]


# ══════════════════════════════════════════════════════════════════════
# Async wrappers for parallel API queries
# ══════════════════════════════════════════════════════════════════════

import asyncio

try:
    import aiohttp
    _HAS_AIOHTTP = True
except ImportError:
    _HAS_AIOHTTP = False

_SEMAPHORE = asyncio.Semaphore(5)  # max 5 concurrent requests


async def async_execute_query(
    query: str,
    variables: Optional[Dict[str, Any]] = None,
    session: Optional[Any] = None,
) -> Dict[str, Any]:
    """Execute a GraphQL query using aiohttp (async)."""
    if not _HAS_AIOHTTP:
        raise ImportError("aiohttp is required for async queries: pip install aiohttp")

    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    async with _SEMAPHORE:
        async with session.post(BASE_URL, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise Exception(f"API request failed with HTTP {resp.status}: {body[:500]}")
            data = await resp.json()
            if "errors" in data:
                raise Exception(f"GraphQL errors: {data['errors']}")
            return data.get("data", {})


async def async_query_full_target(
    gene_symbol: str,
    disease: str,
    session: Any,
) -> Dict[str, Any]:
    """Query all OpenTargets data for a single gene (async).

    Runs: search → target_info → disease evidence → associations.
    """
    result: Dict[str, Any] = {
        "gene_symbol": gene_symbol,
        "disease": disease,
        "executed": False,
        "ensembl_id": None,
        "target_info": {},
        "disease_evidence": [],
        "associations": [],
        "errors": [],
    }

    try:
        # 1. Gene → Ensembl ID
        search_query = """
          query search($queryString: String!, $entityNames: [String!]) {
            search(queryString: $queryString, entityNames: $entityNames, page: {index: 0, size: 10}) {
              hits { id entity name description }
            }
          }
        """
        search_result = await async_execute_query(
            search_query, {"queryString": gene_symbol, "entityNames": ["target"]}, session
        )
        hits = search_result.get("search", {}).get("hits", [])
        if not hits:
            result["errors"].append(f"No OpenTargets target found for {gene_symbol}")
            return result

        ensembl_id = hits[0]["id"]
        result["ensembl_id"] = ensembl_id

        # 2. Target info (tractability, safety, top diseases)
        target_query = """
          query targetInfo($ensemblId: String!) {
            target(ensemblId: $ensemblId) {
              id approvedSymbol approvedName biotype functionDescriptions
              tractability { label modality value }
              safetyLiabilities {
                event
                effects { dosing direction }
                biosamples { tissueId tissueLabel cellLabel }
              }
              geneticConstraint { constraintType score exp obs }
              associatedDiseases(page: {index: 0, size: 10}) {
                rows {
                  disease { id name }
                  score
                  datatypeScores { id score }
                }
              }
            }
          }
        """
        target_result = await async_execute_query(
            target_query, {"ensemblId": ensembl_id}, session
        )
        result["target_info"] = target_result.get("target", {})

        # 3. Disease → EFO ID, then evidence
        disease_search = await async_execute_query(
            search_query, {"queryString": disease, "entityNames": ["disease"]}, session
        )
        disease_hits = disease_search.get("search", {}).get("hits", [])
        if disease_hits:
            efo_id = disease_hits[0]["id"]
            result["efo_id"] = efo_id

            evidence_query = """
              query evidences($ensemblId: String!, $efoId: String!) {
                disease(efoId: $efoId) {
                  evidences(ensemblIds: [$ensemblId], size: 100) {
                    rows {
                      datasourceId datatypeId score
                      targetFromSourceId studyId literature cohortPhenotypes
                    }
                  }
                }
              }
            """
            ev_result = await async_execute_query(
                evidence_query, {"ensemblId": ensembl_id, "efoId": efo_id}, session
            )
            result["disease_evidence"] = (
                ev_result.get("disease", {}).get("evidences", {}).get("rows", [])
            )

        # 4. All disease associations
        assoc_query = """
          query targetAssociations($ensemblId: String!) {
            target(ensemblId: $ensemblId) {
              associatedDiseases(page: {index: 0, size: 100}) {
                count
                rows {
                  disease { id name }
                  score
                  datatypeScores { id score }
                }
              }
            }
          }
        """
        assoc_result = await async_execute_query(
            assoc_query, {"ensemblId": ensembl_id}, session
        )
        associations = (
            assoc_result.get("target", {}).get("associatedDiseases", {}).get("rows", [])
        )
        result["associations"] = [a for a in associations if a.get("score", 0) >= 0.1]
        result["executed"] = True

    except Exception as exc:
        result["errors"].append(f"Async OpenTargets query failed: {str(exc)}")

    return result


async def async_batch_query_targets(
    gene_symbols: List[str],
    disease: str,
    max_concurrent: int = 5,
) -> Dict[str, Dict[str, Any]]:
    """Query multiple genes in parallel using asyncio.gather().

    Uses a shared aiohttp.ClientSession for connection pooling
    and a semaphore to limit concurrent requests.
    """
    global _SEMAPHORE
    _SEMAPHORE = asyncio.Semaphore(max_concurrent)

    async with aiohttp.ClientSession() as session:
        tasks = [
            async_query_full_target(gene, disease, session)
            for gene in gene_symbols
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    output: Dict[str, Dict[str, Any]] = {}
    for gene, res in zip(gene_symbols, results):
        if isinstance(res, Exception):
            output[gene] = {
                "gene_symbol": gene,
                "executed": False,
                "errors": [str(res)],
            }
        else:
            output[gene] = res
    return output


# Example usage
if __name__ == "__main__":
    # Example 1: Search for a gene
    print("Searching for BRCA1...")
    results = search_entities("BRCA1", entity_types=["target"])
    for result in results[:3]:
        print(f"  {result['name']} ({result['id']})")

    # Example 2: Get target information
    if results:
        ensembl_id = results[0]['id']
        print(f"\nGetting info for {ensembl_id}...")
        target_info = get_target_info(ensembl_id, include_diseases=True)
        print(f"  Symbol: {target_info.get('approvedSymbol')}")
        print(f"  Name: {target_info.get('approvedName')}")

        # Show top diseases
        diseases = target_info.get('associatedDiseases', {}).get('rows', [])
        if diseases:
            print(f"\n  Top associated diseases:")
            for disease in diseases[:3]:
                print(f"    - {disease['disease']['name']} (score: {disease['score']:.2f})")

    # Example 3: Search for a disease
    print("\n\nSearching for Alzheimer's disease...")
    disease_results = search_entities("alzheimer", entity_types=["disease"])
    if disease_results:
        efo_id = disease_results[0]['id']
        print(f"  Found: {disease_results[0]['name']} ({efo_id})")

        # Get known drugs
        print(f"\n  Known drugs for {disease_results[0]['name']}:")
        drugs = get_known_drugs_for_disease(efo_id)
        for drug in drugs.get('rows', [])[:5]:
            print(f"    - {drug['drug']['name']} (Phase {drug['phase']})")
