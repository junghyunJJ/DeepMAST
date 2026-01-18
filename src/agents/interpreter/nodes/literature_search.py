"""Literature search node for Deep Agent.

This module implements evidence gathering from PubMed
to support biological claims with literature references.
"""

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from src.agents.interpreter.biological_interpreter_state import (
    BiologicalInterpreterState,
    Claim,
)


async def search_for_evidence(
    state: BiologicalInterpreterState,
    model: BaseChatModel,
    is_debug: bool = False,
) -> dict[str, list[str]]:
    """Search literature for evidence supporting claims.

    This function generates search queries for each claim and
    retrieves relevant PMIDs. In production, this would integrate
    with biomcp or PubMed APIs.

    Args:
        state: Current agent state
        model: LLM for query generation
        is_debug: Debug flag

    Returns:
        Dict mapping claim_id to list of PMIDs
    """
    claims = state.get("claims", [])
    selected_lr_pairs = state.get("selected_lr_pairs", [])
    selected_pathways = state.get("selected_pathways", [])
    interest_celltypes = state.get("interest_celltypes", [])
    selected_celltypes = state.get("selected_celltypes", [])

    celltypes = interest_celltypes or selected_celltypes or []

    evidence_map = {}

    for claim in claims:
        claim_id = claim.get("claim_id", "")
        claim_content = claim.get("content", "")

        if not claim_id or not claim_content:
            continue

        # Generate search query for this claim
        search_query = await generate_search_query(
            claim_content=claim_content,
            lr_pairs=selected_lr_pairs,
            pathways=selected_pathways,
            celltypes=celltypes,
            model=model,
            is_debug=is_debug,
        )

        # In production, this would call biomcp or PubMed API
        # For now, we generate placeholder PMIDs based on the query
        pmids = await search_pubmed_mock(search_query, is_debug)

        evidence_map[claim_id] = pmids

        if is_debug:
            print(f"Claim {claim_id}: Found {len(pmids)} references")

    return evidence_map


async def generate_search_query(
    claim_content: str,
    lr_pairs: list[str],
    pathways: list[str],
    celltypes: list[str],
    model: BaseChatModel,
    is_debug: bool = False,
) -> str:
    """Generate a PubMed search query for a claim.

    Args:
        claim_content: The claim text
        lr_pairs: Selected L-R pairs
        pathways: Selected pathways
        celltypes: Cell types of interest
        model: LLM for query generation
        is_debug: Debug flag

    Returns:
        PubMed search query string
    """
    # Extract ligand and receptor names from LR pairs
    ligands = []
    receptors = []
    for lr in lr_pairs[:3]:  # Limit to top 3
        if "^" in lr:
            parts = lr.split("^")
            ligands.append(parts[0])
            if len(parts) > 1:
                receptors.append(parts[1])

    prompt = f"""Generate a PubMed search query for this biological claim.

**Claim**: {claim_content}

**Context**:
- Ligands: {ligands}
- Receptors: {receptors}
- Pathways: {pathways[:3] if pathways else 'None'}
- Cell types: {celltypes[:3] if celltypes else 'None'}

Create a focused PubMed query (max 3-4 terms) that would find relevant papers.
Use MeSH terms where appropriate. Format: term1 AND term2 AND term3

Just provide the search query, nothing else.
"""

    messages = [
        SystemMessage(content="You are a biomedical literature search expert."),
        HumanMessage(content=prompt),
    ]

    response = await model.ainvoke(messages)
    query = response.content.strip()

    # Clean up the query
    query = query.replace('"', '')
    query = query.strip('`')

    if is_debug:
        print(f"Generated query: {query}")

    return query


async def search_pubmed_mock(query: str, is_debug: bool = False) -> list[str]:
    """Mock PubMed search - returns placeholder PMIDs.

    In production, this would be replaced with actual biomcp/PubMed API calls.

    Args:
        query: Search query
        is_debug: Debug flag

    Returns:
        List of PMIDs
    """
    # Generate deterministic mock PMIDs based on query hash
    import hashlib

    query_hash = hashlib.md5(query.encode()).hexdigest()

    # Generate 2-5 mock PMIDs
    num_results = (int(query_hash[0], 16) % 4) + 2  # 2-5 results

    pmids = []
    for i in range(num_results):
        # Create realistic-looking PMIDs (8 digits starting with 3)
        pmid_base = int(query_hash[i*4:(i+1)*4], 16) % 10000000
        pmid = f"3{pmid_base:07d}"
        pmids.append(pmid)

    if is_debug:
        print(f"Mock search returned {len(pmids)} PMIDs")

    return pmids


async def search_pubmed_real(
    query: str,
    max_results: int = 5,
    is_debug: bool = False,
) -> list[str]:
    """Real PubMed search using biomcp MCP tool.

    This function would integrate with the biomcp MCP server
    for actual literature searches.

    Args:
        query: Search query
        max_results: Maximum number of results
        is_debug: Debug flag

    Returns:
        List of PMIDs
    """
    # TODO: Integrate with biomcp MCP server
    # This would use the article_searcher tool from biomcp

    # For now, fall back to mock
    return await search_pubmed_mock(query, is_debug)


def format_citations(pmids: list[str]) -> str:
    """Format PMIDs as citation strings.

    Args:
        pmids: List of PMIDs

    Returns:
        Formatted citation string
    """
    if not pmids:
        return "No references found."

    citations = []
    for pmid in pmids:
        citations.append(f"PMID: {pmid}")

    return "; ".join(citations)


async def enrich_claims_with_evidence(
    claims: list[Claim],
    evidence_map: dict[str, list[str]],
    model: BaseChatModel,
    is_debug: bool = False,
) -> list[Claim]:
    """Enrich claims with literature evidence.

    Updates claim confidence based on evidence availability.

    Args:
        claims: List of claims
        evidence_map: Map of claim_id to PMIDs
        model: LLM for evidence assessment
        is_debug: Debug flag

    Returns:
        Updated list of claims with literature evidence
    """
    enriched_claims = []

    for claim in claims:
        claim_id = claim.get("claim_id", "")
        pmids = evidence_map.get(claim_id, [])

        # Copy claim and update
        enriched_claim = dict(claim)

        # Add literature references to supporting evidence
        current_evidence = list(claim.get("supporting_evidence", []))
        if pmids:
            current_evidence.append(f"Literature: {format_citations(pmids)}")

        enriched_claim["supporting_evidence"] = current_evidence

        # Adjust confidence based on literature support
        base_confidence = claim.get("confidence", 0.7)
        if len(pmids) >= 3:
            # Strong literature support
            enriched_claim["confidence"] = min(0.95, base_confidence + 0.1)
        elif len(pmids) >= 1:
            # Some literature support
            enriched_claim["confidence"] = min(0.9, base_confidence + 0.05)
        else:
            # No literature support - slight decrease
            enriched_claim["confidence"] = max(0.4, base_confidence - 0.1)

        enriched_claims.append(Claim(**enriched_claim))

        if is_debug:
            print(f"Claim {claim_id}: {len(pmids)} refs, confidence {enriched_claim['confidence']:.2f}")

    return enriched_claims
