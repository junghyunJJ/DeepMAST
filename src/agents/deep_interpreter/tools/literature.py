"""Literature search tool for Deep Interpreter Agent.

This tool provides PubMed search capabilities via BioMCP for finding
supporting literature for CCI interpretations.
"""

import asyncio
import atexit
import concurrent.futures
import json
import logging
import os
import re
from typing import Any

from langchain_core.tools import tool
from langchain_mcp_adapters.client import MultiServerMCPClient


logger = logging.getLogger(__name__)

# Default BioMCP server configuration
# 0.0.0.0 is for server binding, localhost is for client connections
DEFAULT_BIOMCP_URL = os.getenv("BIOMCP_URL", "http://localhost:8000/mcp")

# Module-level executor for async operations in sync contexts
_EXECUTOR: concurrent.futures.ThreadPoolExecutor | None = None


def _get_executor() -> concurrent.futures.ThreadPoolExecutor:
    """Get or create the module-level ThreadPoolExecutor."""
    global _EXECUTOR
    if _EXECUTOR is None:
        _EXECUTOR = concurrent.futures.ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="biomcp"
        )
        atexit.register(_EXECUTOR.shutdown, wait=False)
    return _EXECUTOR


async def _search_with_biomcp(
    genes: list[str] | None = None,
    diseases: list[str] | None = None,
    keywords: list[str] | None = None,
    chemicals: list[str] | None = None,
    page_size: int = 10,
    include_preprints: bool = True,
    biomcp_url: str = DEFAULT_BIOMCP_URL,
) -> list[dict]:
    """Execute PubMed search via BioMCP article_searcher.

    Args:
        genes: List of gene symbols to search for (e.g., ["CDH1", "TGFB1"])
        diseases: List of disease names to search for (e.g., ["breast cancer"])
        keywords: List of free-text keywords (e.g., ["EMT", "spatial transcriptomics"])
        chemicals: List of chemical/drug names (optional)
        page_size: Number of results per page (default 10, max 100)
        include_preprints: Include bioRxiv/medRxiv preprints (default True)
        biomcp_url: URL of the BioMCP server

    Returns:
        List of article dictionaries with pmid, title, abstract

    Note:
        As of langchain-mcp-adapters 0.1.0, MultiServerMCPClient cannot be
        used as a context manager. Use client.get_tools() directly instead.
    """
    articles = []

    # Ensure at least one search parameter is provided
    if not any([genes, diseases, keywords, chemicals]):
        logger.warning("No search parameters provided to _search_with_biomcp")
        return []

    try:
        # Note: Do not use 'async with' - API changed in langchain-mcp-adapters 0.1.0
        client = MultiServerMCPClient(
            {"biomcp": {"url": biomcp_url, "transport": "http"}}
        )
        tools = await client.get_tools()

        # Find article_searcher tool
        article_searcher = None
        article_getter = None

        for tool_obj in tools:
            if hasattr(tool_obj, 'name'):
                if 'article_searcher' in tool_obj.name:
                    article_searcher = tool_obj
                elif 'article_getter' in tool_obj.name:
                    article_getter = tool_obj

        if article_searcher is None:
            available_tools = [getattr(t, "name", str(t)) for t in tools]
            logger.warning(
                f"article_searcher tool not found in BioMCP. "
                f"Available tools: {available_tools}"
            )
            return []

        # Build search parameters - only include non-None values
        search_params = {
            "page_size": min(page_size, 100),  # Max 100 per BioMCP spec
            "include_preprints": include_preprints,
        }
        if genes:
            search_params["genes"] = genes
        if diseases:
            search_params["diseases"] = diseases
        if keywords:
            search_params["keywords"] = keywords
        if chemicals:
            search_params["chemicals"] = chemicals

        logger.debug(f"BioMCP article_searcher params: {search_params}")

        # Search for articles using correct BioMCP parameters
        search_result = await article_searcher.ainvoke(search_params)

        pmids = _parse_pmids(search_result)

        # Fetch article details
        for pmid in pmids:
            if article_getter:
                try:
                    article_result = await article_getter.ainvoke({"pmid": pmid})
                    article = _parse_article(pmid, article_result)
                    articles.append(article)
                except Exception:
                    articles.append({
                        "pmid": pmid,
                        "title": f"Article {pmid}",
                        "abstract": "",
                    })
            else:
                articles.append({
                    "pmid": pmid,
                    "title": f"Article {pmid}",
                    "abstract": "",
                })

    except Exception as e:
        # Return empty list on connection failure
        logger.error(f"BioMCP connection failed: {e}")

    return articles


def _parse_pmids(result: Any) -> list[str]:
    """Parse PMIDs from BioMCP article_searcher result."""
    pmids = []

    if result is None:
        return pmids

    if isinstance(result, str):
        try:
            data = json.loads(result)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and 'pmid' in item:
                        pmids.append(str(item['pmid']))
                    elif isinstance(item, str) and item.isdigit():
                        pmids.append(item)
                return pmids
        except json.JSONDecodeError:
            pass

        # Fallback: extract numeric PMIDs with regex
        matches = re.findall(r'\b(\d{7,8})\b', result)
        return matches[:10]

    if isinstance(result, dict):
        if 'pmids' in result:
            return [str(p) for p in result['pmids']]
        if 'results' in result:
            for item in result['results']:
                if isinstance(item, dict) and 'pmid' in item:
                    pmids.append(str(item['pmid']))
        return pmids

    if isinstance(result, list):
        for item in result:
            if isinstance(item, dict) and 'pmid' in item:
                pmids.append(str(item['pmid']))
            elif isinstance(item, (str, int)):
                pmids.append(str(item))
        return pmids

    return pmids


def _parse_article(pmid: str, result: Any) -> dict:
    """Parse article details from BioMCP article_getter result."""
    article = {
        "pmid": pmid,
        "title": f"Article {pmid}",
        "abstract": "",
    }

    if result is None:
        return article

    if isinstance(result, str):
        try:
            data = json.loads(result)
            if isinstance(data, dict):
                article["title"] = data.get("title", article["title"])
                article["abstract"] = data.get("abstract", "")
        except json.JSONDecodeError:
            if len(result) > 100:
                article["abstract"] = result
        return article

    if isinstance(result, dict):
        article["title"] = result.get("title", article["title"])
        article["abstract"] = result.get("abstract", "")
        return article

    return article


@tool
def search_literature(
    genes: list[str],
    disease: str,
    keywords: list[str],
    max_results: int = 15,
) -> list[dict]:
    """Search PubMed via BioMCP for supporting literature.

    This tool searches PubMed for articles related to specific genes,
    diseases, and biological keywords relevant to CCI analysis.

    Args:
        genes: List of gene names to search (e.g., ["CDH1", "TGFB1"])
        disease: Disease context (e.g., "breast cancer")
        keywords: Additional keywords (e.g., ["EMT", "spatial transcriptomics"])
        max_results: Maximum number of results to return (default 15)

    Returns:
        List of article dictionaries with:
        - pmid: PubMed ID
        - title: Article title
        - abstract: Article abstract (may be truncated)
    """
    # Build search query
    query_parts = []

    # Add gene terms
    if genes:
        gene_terms = " OR ".join([f'"{g}"[Gene]' for g in genes[:5]])
        query_parts.append(f"({gene_terms})")

    # Add disease context
    if disease:
        query_parts.append(f'"{disease}"[Title/Abstract]')

    # Add keywords
    if keywords:
        keyword_terms = " OR ".join([f'"{k}"' for k in keywords[:5]])
        query_parts.append(f"({keyword_terms})")

    query = " AND ".join(query_parts)

    if not query:
        return []

    # Run async search
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # In async context, use module-level executor
            executor = _get_executor()
            future = executor.submit(
                asyncio.run,
                _search_with_biomcp(query, max_results)
            )
            return future.result(timeout=60)
        else:
            return asyncio.run(_search_with_biomcp(query, max_results))
    except Exception:
        # Fallback: return empty list
        return []


async def search_literature_async(
    genes: list[str],
    disease: str,
    keywords: list[str],
    max_results: int = 15,
    biomcp_url: str = DEFAULT_BIOMCP_URL,
) -> list[dict]:
    """Async version of search_literature.

    Use this function directly in async contexts for better performance.

    Args:
        genes: List of gene names to search
        disease: Disease context
        keywords: Additional keywords
        max_results: Maximum results to return
        biomcp_url: BioMCP server URL

    Returns:
        List of article dictionaries
    """
    query_parts = []

    if genes:
        gene_terms = " OR ".join([f'"{g}"[Gene]' for g in genes[:5]])
        query_parts.append(f"({gene_terms})")

    if disease:
        query_parts.append(f'"{disease}"[Title/Abstract]')

    if keywords:
        keyword_terms = " OR ".join([f'"{k}"' for k in keywords[:5]])
        query_parts.append(f"({keyword_terms})")

    query = " AND ".join(query_parts)

    if not query:
        return []

    return await _search_with_biomcp(query, max_results, biomcp_url)


def format_references(articles: list[dict], max_refs: int = 5) -> str:
    """Format articles as a reference list for inclusion in reports.

    Args:
        articles: List of article dictionaries
        max_refs: Maximum number of references to include

    Returns:
        Formatted reference string with PMID links
    """
    if not articles:
        return "No references available."

    lines = []
    for i, article in enumerate(articles[:max_refs], 1):
        pmid = article.get("pmid", "")
        title = article.get("title", f"Article {pmid}")
        lines.append(f"{i}. {title} (PMID: {pmid})")

    return "\n".join(lines)


@tool
def search_literature_for_context(
    genes: list[str],
    pathways: list[str],
    celltypes: list[str],
    disease: str,
    interaction_type: str = "",
    max_results: int = 20,
) -> dict:
    """Search PubMed for contextual literature BEFORE generating interpretations.

    This tool performs proactive literature search based on analysis context
    (genes, pathways, cell types) to provide a reference foundation for
    interpretation generation. Unlike search_literature, this is designed
    to be called BEFORE interpretation to prevent hallucination.

    Args:
        genes: List of gene names identified in analysis (e.g., ["CDH1", "TGFB1", "VIM"])
        pathways: List of pathways identified (e.g., ["EMT", "TGFB", "WNT"])
        celltypes: List of cell types in analysis (e.g., ["Tumor", "Fibroblast"])
        disease: Disease context (e.g., "breast cancer")
        interaction_type: Type of interaction focus (e.g., "cell-cell interaction", "spatial")
        max_results: Maximum number of papers to return (default 20)

    Returns:
        Dictionary with:
        - papers: List of relevant papers with pmid, title, abstract
        - search_queries: The queries used for searching
        - coverage: Summary of what biological concepts are covered
    """
    papers = []
    search_queries = []

    # Strategy 1: Gene + Disease + Interaction focused search
    if genes and disease:
        for gene in genes[:3]:  # Top 3 genes
            query_parts = [f'"{gene}"[Gene]', f'"{disease}"[Title/Abstract]']
            if interaction_type:
                query_parts.append(f'"{interaction_type}"[Title/Abstract]')
            query = " AND ".join(query_parts)
            search_queries.append({"type": "gene_disease", "query": query})

    # Strategy 2: Pathway + Cell type search
    if pathways and celltypes:
        pathway_terms = " OR ".join([f'"{p}"' for p in pathways[:3]])
        celltype_terms = " OR ".join([f'"{c}"' for c in celltypes[:3]])
        query = f"({pathway_terms}) AND ({celltype_terms})"
        if disease:
            query += f' AND "{disease}"[Title/Abstract]'
        search_queries.append({"type": "pathway_celltype", "query": query})

    # Strategy 3: Ligand-receptor interaction search
    if genes and len(genes) >= 2:
        lr_keywords = ["ligand receptor", "cell-cell interaction", "signaling"]
        gene_pairs = [(genes[i], genes[j]) for i in range(min(3, len(genes)))
                      for j in range(i+1, min(4, len(genes)))]
        for g1, g2 in gene_pairs[:2]:
            lr_terms = " OR ".join(['"{}"'.format(k) for k in lr_keywords])
            query = '("{}" AND "{}") AND ({})'.format(g1, g2, lr_terms)
            search_queries.append({"type": "lr_pair", "query": query})

    # Strategy 4: Spatial transcriptomics context
    if celltypes and disease:
        spatial_terms = ["spatial transcriptomics", "single cell", "tumor microenvironment"]
        celltype_terms = " OR ".join(['"{}"'.format(c) for c in celltypes[:3]])
        spatial_terms_str = " OR ".join(['"{}"'.format(t) for t in spatial_terms])
        query = '({}) AND ({}) AND "{}"'.format(celltype_terms, spatial_terms_str, disease)
        search_queries.append({"type": "spatial", "query": query})

    # Execute searches
    seen_pmids = set()
    try:
        loop = asyncio.get_event_loop()
        is_running = loop.is_running()
    except RuntimeError:
        is_running = False

    for sq in search_queries:
        try:
            if is_running:
                # Use module-level executor
                executor = _get_executor()
                future = executor.submit(
                    asyncio.run,
                    _search_with_biomcp(sq["query"], max_results // len(search_queries) + 5)
                )
                results = future.result(timeout=60)
            else:
                results = asyncio.run(
                    _search_with_biomcp(sq["query"], max_results // len(search_queries) + 5)
                )

            for paper in results:
                pmid = paper.get("pmid", "")
                if pmid and pmid not in seen_pmids:
                    seen_pmids.add(pmid)
                    paper["search_type"] = sq["type"]
                    papers.append(paper)

        except Exception as e:
            logger.warning(f"Search failed for query {sq['type']}: {e}")
            continue

    # Limit to max_results
    papers = papers[:max_results]

    # Calculate coverage
    coverage = {
        "genes_covered": [],
        "pathways_covered": [],
        "celltypes_covered": [],
        "total_papers": len(papers),
    }

    for paper in papers:
        abstract_lower = paper.get("abstract", "").lower()
        title_lower = paper.get("title", "").lower()
        combined = abstract_lower + " " + title_lower

        for gene in genes:
            if gene.lower() in combined and gene not in coverage["genes_covered"]:
                coverage["genes_covered"].append(gene)

        for pathway in pathways:
            if pathway.lower() in combined and pathway not in coverage["pathways_covered"]:
                coverage["pathways_covered"].append(pathway)

        for celltype in celltypes:
            if celltype.lower() in combined and celltype not in coverage["celltypes_covered"]:
                coverage["celltypes_covered"].append(celltype)

    return {
        "papers": papers,
        "search_queries": [sq["query"] for sq in search_queries],
        "coverage": coverage,
    }


async def search_literature_for_context_async(
    genes: list[str],
    pathways: list[str],
    celltypes: list[str],
    disease: str,
    interaction_type: str = "",
    max_results: int = 20,
    biomcp_url: str = DEFAULT_BIOMCP_URL,
) -> dict:
    """Async version of search_literature_for_context.

    Args:
        genes: List of gene names
        pathways: List of pathways
        celltypes: List of cell types
        disease: Disease context
        interaction_type: Type of interaction focus
        max_results: Maximum papers to return
        biomcp_url: BioMCP server URL

    Returns:
        Dictionary with papers, search_queries, and coverage
    """
    papers = []
    search_queries = []

    # Build queries (same logic as sync version)
    if genes and disease:
        for gene in genes[:3]:
            query_parts = [f'"{gene}"[Gene]', f'"{disease}"[Title/Abstract]']
            if interaction_type:
                query_parts.append(f'"{interaction_type}"[Title/Abstract]')
            query = " AND ".join(query_parts)
            search_queries.append({"type": "gene_disease", "query": query})

    if pathways and celltypes:
        pathway_terms = " OR ".join([f'"{p}"' for p in pathways[:3]])
        celltype_terms = " OR ".join([f'"{c}"' for c in celltypes[:3]])
        query = f"({pathway_terms}) AND ({celltype_terms})"
        if disease:
            query += f' AND "{disease}"[Title/Abstract]'
        search_queries.append({"type": "pathway_celltype", "query": query})

    if celltypes and disease:
        spatial_terms = ["spatial transcriptomics", "single cell", "tumor microenvironment"]
        celltype_terms = " OR ".join(['"{}"'.format(c) for c in celltypes[:3]])
        spatial_terms_str = " OR ".join(['"{}"'.format(t) for t in spatial_terms])
        query = '({}) AND ({}) AND "{}"'.format(celltype_terms, spatial_terms_str, disease)
        search_queries.append({"type": "spatial", "query": query})

    # Execute searches concurrently
    seen_pmids = set()
    for sq in search_queries:
        try:
            results = await _search_with_biomcp(
                sq["query"],
                max_results // len(search_queries) + 5,
                biomcp_url
            )
            for paper in results:
                pmid = paper.get("pmid", "")
                if pmid and pmid not in seen_pmids:
                    seen_pmids.add(pmid)
                    paper["search_type"] = sq["type"]
                    papers.append(paper)
        except Exception:
            continue

    papers = papers[:max_results]

    # Calculate coverage
    coverage = {
        "genes_covered": [],
        "pathways_covered": [],
        "celltypes_covered": [],
        "total_papers": len(papers),
    }

    for paper in papers:
        combined = (paper.get("abstract", "") + " " + paper.get("title", "")).lower()
        for gene in genes:
            if gene.lower() in combined and gene not in coverage["genes_covered"]:
                coverage["genes_covered"].append(gene)
        for pathway in pathways:
            if pathway.lower() in combined and pathway not in coverage["pathways_covered"]:
                coverage["pathways_covered"].append(pathway)
        for celltype in celltypes:
            if celltype.lower() in combined and celltype not in coverage["celltypes_covered"]:
                coverage["celltypes_covered"].append(celltype)

    return {
        "papers": papers,
        "search_queries": [sq["query"] for sq in search_queries],
        "coverage": coverage,
    }
