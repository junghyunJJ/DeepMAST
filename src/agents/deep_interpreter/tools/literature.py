"""Literature search tool for Deep Interpreter Agent.

This tool provides PubMed search capabilities via BioMCP for finding
supporting literature for CCI interpretations.

Includes fixed-strategy internal fallback (_execute_fixed_strategy_search) and
LLM-powered dynamic query generation (search_literature_dynamic).
"""

import asyncio
import json
import logging
import re
import threading
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from src.agents.model import create_llm
from src.agents.deep_interpreter.prompts import (
    LITERATURE_QUERY_GENERATION_PROMPT,
    GAP_FILLING_QUERY_PROMPT,
)
from src.agents.deep_interpreter.tools.mcp_clients import (
    get_executor,
    run_async,
    find_tool_by_name,
    DEFAULT_BIOMCP_URL,
    get_biomcp_tools,
    invalidate_client,
)


logger = logging.getLogger(__name__)


# =============================================================================
# Dynamic Gene Alias Cache (BioMCP gene_getter)
# =============================================================================
# Session-level cache for gene aliases fetched from BioMCP
# This avoids repeated API calls for the same gene
_GENE_ALIAS_CACHE: dict[str, list[str]] = {}
_GENE_ALIAS_CACHE_LOCK = threading.Lock()


async def _fetch_gene_aliases_from_biomcp(
    gene_symbol: str,
    biomcp_url: str = DEFAULT_BIOMCP_URL,
) -> list[str]:
    """Fetch gene aliases from BioMCP gene_getter (MyGene.info).

    This provides comprehensive alias coverage including:
    - Official synonyms from NCBI Gene
    - Historical names
    - Species-specific variants

    Args:
        gene_symbol: Gene symbol (e.g., "ACKR3", "ADAM10")
        biomcp_url: BioMCP server URL

    Returns:
        List of aliases (empty list if fetch fails)

    Note:
        Results are cached at module level to avoid repeated API calls.
        Token cost: 0 (API call, not LLM)
    """
    # Check cache first (thread-safe)
    cache_key = gene_symbol.upper()
    with _GENE_ALIAS_CACHE_LOCK:
        if cache_key in _GENE_ALIAS_CACHE:
            return _GENE_ALIAS_CACHE[cache_key]

    aliases = []
    try:
        tools = await get_biomcp_tools(biomcp_url)

        # Find gene_getter tool
        gene_getter = find_tool_by_name(tools, "gene_getter")

        if gene_getter is None:
            logger.debug(f"gene_getter tool not found, skipping alias fetch for {gene_symbol}")
            with _GENE_ALIAS_CACHE_LOCK:
                _GENE_ALIAS_CACHE[cache_key] = []
            return []

        # Fetch gene info
        result = await gene_getter.ainvoke({"gene_id_or_symbol": gene_symbol})

        # Parse aliases from result
        aliases = _parse_gene_aliases(result)
        logger.debug(f"Fetched aliases for {gene_symbol}: {aliases}")

    except Exception as e:
        logger.debug(f"Failed to fetch aliases for {gene_symbol}: {e}")
        invalidate_client(f"biomcp_{biomcp_url}")

    # Cache result (even empty list to avoid retries) - thread-safe
    with _GENE_ALIAS_CACHE_LOCK:
        _GENE_ALIAS_CACHE[cache_key] = aliases
    return aliases


def _parse_gene_aliases(result: Any) -> list[str]:
    """Parse gene aliases from BioMCP gene_getter result.

    BioMCP returns results in markdown format:
    [{'type': 'text', 'text': '# Record 1\\nSymbol: ACKR3\\nAlias: CMKOR1, CXCR7, ...\\n...'}]

    Args:
        result: Raw result from gene_getter

    Returns:
        List of alias strings
    """
    aliases = []

    if result is None:
        return aliases

    # Handle BioMCP format: list of dicts with 'text' field
    if isinstance(result, list):
        for item in result:
            if isinstance(item, dict) and 'text' in item:
                text = item['text']

                # BioMCP gene_getter returns markdown format
                # Look for "Alias: " line
                alias_match = re.search(r'Alias:\s*([^\n]+)', text)
                if alias_match:
                    alias_line = alias_match.group(1).strip()
                    # Split by comma and clean up
                    for alias in alias_line.split(','):
                        alias_clean = alias.strip()
                        if alias_clean and alias_clean not in aliases:
                            aliases.append(alias_clean)

                # Also extract symbol (might be different case)
                symbol_match = re.search(r'Symbol:\s*([^\n]+)', text)
                if symbol_match:
                    symbol = symbol_match.group(1).strip()
                    if symbol and symbol not in aliases:
                        aliases.append(symbol)

                # Try JSON fallback for different response formats
                if not aliases:
                    try:
                        data = json.loads(text)
                        if isinstance(data, list) and len(data) > 0:
                            data = data[0]
                        if isinstance(data, dict):
                            for field in ['alias', 'aliases', 'synonyms']:
                                if field in data:
                                    field_value = data[field]
                                    if isinstance(field_value, list):
                                        aliases.extend([str(a) for a in field_value])
                                    elif isinstance(field_value, str):
                                        aliases.extend(field_value.split(','))
                    except json.JSONDecodeError:
                        pass
                break

    return list(set(aliases))  # Deduplicate


def _fetch_gene_aliases_sync(
    gene_symbol: str,
    biomcp_url: str = DEFAULT_BIOMCP_URL,
) -> list[str]:
    """Sync wrapper for _fetch_gene_aliases_from_biomcp."""
    # Check cache first (fast path) - thread-safe
    cache_key = gene_symbol.upper()
    with _GENE_ALIAS_CACHE_LOCK:
        if cache_key in _GENE_ALIAS_CACHE:
            return _GENE_ALIAS_CACHE[cache_key]

    return run_async(_fetch_gene_aliases_from_biomcp(gene_symbol, biomcp_url), timeout=30)


async def _fetch_missing_gene_aliases(
    missing_genes: list[str],
    biomcp_url: str = DEFAULT_BIOMCP_URL,
) -> dict[str, list[str]]:
    """Fetch aliases for multiple missing genes in parallel.

    Args:
        missing_genes: List of gene symbols that weren't matched
        biomcp_url: BioMCP server URL

    Returns:
        Dict mapping gene symbol to list of aliases
    """
    # Limit to top N genes to avoid too many API calls
    genes_to_fetch = missing_genes[:10]

    # Fetch in parallel
    tasks = [
        _fetch_gene_aliases_from_biomcp(gene, biomcp_url)
        for gene in genes_to_fetch
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    alias_map = {}
    for gene, result in zip(genes_to_fetch, results):
        if isinstance(result, Exception):
            alias_map[gene] = []
        else:
            alias_map[gene] = result

    return alias_map


async def _search_with_biomcp(
    genes: list[str] | None = None,
    diseases: list[str] | None = None,
    keywords: list[str] | None = None,
    chemicals: list[str] | None = None,
    page_size: int = 20,
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
    # FIX: Check for actual content, not just truthiness
    # Empty list [] should be treated as "no genes" but still allow search
    # if other parameters have values
    has_genes = genes is not None and len(genes) > 0
    has_diseases = diseases is not None and len(diseases) > 0
    has_keywords = keywords is not None and len(keywords) > 0
    has_chemicals = chemicals is not None and len(chemicals) > 0

    if not any([has_genes, has_diseases, has_keywords, has_chemicals]):
        logger.warning("No search parameters provided to _search_with_biomcp")
        return []

    try:
        tools = await get_biomcp_tools(biomcp_url)

        # Find article_searcher and article_getter tools
        article_searcher = find_tool_by_name(tools, "article_searcher")
        article_getter = find_tool_by_name(tools, "article_getter")

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

        # Fetch article details in parallel
        if article_getter and pmids:
            tasks = [article_getter.ainvoke({"pmid": pmid}) for pmid in pmids]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for pmid, result in zip(pmids, results):
                if isinstance(result, Exception):
                    articles.append({
                        "pmid": pmid,
                        "title": f"Article {pmid}",
                        "abstract": "",
                    })
                else:
                    article = _parse_article(pmid, result)
                    articles.append(article)
        else:
            for pmid in pmids:
                articles.append({
                    "pmid": pmid,
                    "title": f"Article {pmid}",
                    "abstract": "",
                })

    except Exception as e:
        # Return empty list on connection failure
        logger.error(f"BioMCP connection failed: {e}")
        invalidate_client(f"biomcp_{biomcp_url}")

    return articles


def _parse_pmids(result: Any) -> list[str]:
    """Parse PMIDs from BioMCP article_searcher result.

    BioMCP returns results in format:
    [{'type': 'text', 'text': '...Pmid: 12345678...', 'id': '...'}]

    We extract PMIDs from the 'text' field using regex patterns.
    """
    pmids = []

    if result is None:
        return pmids

    # Handle BioMCP format: list of dicts with 'text' field
    if isinstance(result, list):
        for item in result:
            if isinstance(item, dict):
                # BioMCP format: {'type': 'text', 'text': '...', 'id': '...'}
                if 'text' in item:
                    text = item['text']
                    # Extract PMIDs from patterns like "Pmid: 12345678" or "PMID: 12345678"
                    # Support 7+ digits for modern PMIDs (currently up to 8 digits, growing)
                    pmid_matches = re.findall(r'(?i)pmid[:\s]+(\d{7,})', text)
                    pmids.extend(pmid_matches)
                # Also check for direct 'pmid' key
                elif 'pmid' in item:
                    pmids.append(str(item['pmid']))
            elif isinstance(item, (str, int)):
                pmids.append(str(item))
        # Deduplicate while preserving order
        seen = set()
        unique_pmids = []
        for pmid in pmids:
            if pmid not in seen:
                seen.add(pmid)
                unique_pmids.append(pmid)
        return unique_pmids[:20]  # Limit to 20 PMIDs

    if isinstance(result, str):
        try:
            data = json.loads(result)
            if isinstance(data, list):
                return _parse_pmids(data)  # Recursive call for parsed JSON
        except json.JSONDecodeError:
            pass

        # Fallback: extract PMIDs with regex patterns
        pmid_matches = re.findall(r'(?i)pmid[:\s]+(\d{7,})', result)
        if pmid_matches:
            return list(dict.fromkeys(pmid_matches))[:20]

        # Last resort: extract any 7+ digit numbers (PMIDs are 7-8+ digits)
        matches = re.findall(r'\b(\d{7,9})\b', result)
        return matches[:10]

    if isinstance(result, dict):
        if 'pmids' in result:
            return [str(p) for p in result['pmids']]
        if 'text' in result:
            return _parse_pmids([result])  # Recursive call
        if 'results' in result:
            for item in result['results']:
                if isinstance(item, dict) and 'pmid' in item:
                    pmids.append(str(item['pmid']))
        return pmids

    return pmids


def _parse_article(pmid: str, result: Any) -> dict:
    """Parse article details from BioMCP article_getter result.

    BioMCP returns results in format:
    [{'type': 'text', 'text': '[{"pmid": 12345, "title": "...", "abstract": "..."}]'}]

    The 'text' field contains JSON with article details.
    """
    article = {
        "pmid": pmid,
        "title": f"Article {pmid}",
        "abstract": "",
    }

    if result is None:
        return article

    # Handle BioMCP format: list of dicts with 'text' field containing JSON
    if isinstance(result, list):
        for item in result:
            if isinstance(item, dict) and 'text' in item:
                text = item['text']
                # Try to parse as JSON (BioMCP article_getter format)
                try:
                    data = json.loads(text)
                    # Data can be a list with one article dict
                    if isinstance(data, list) and len(data) > 0:
                        article_data = data[0]
                        if isinstance(article_data, dict):
                            article["title"] = article_data.get("title", article["title"])
                            article["abstract"] = article_data.get("abstract", "")
                            # Also capture additional fields if available
                            if "authors" in article_data:
                                article["authors"] = article_data["authors"]
                            if "journal" in article_data:
                                article["journal"] = article_data["journal"]
                            if "date" in article_data:
                                article["date"] = article_data["date"]
                    elif isinstance(data, dict):
                        article["title"] = data.get("title", article["title"])
                        article["abstract"] = data.get("abstract", "")
                except json.JSONDecodeError:
                    # Fallback: extract using regex patterns
                    title_match = re.search(r'"title"[:\s]+"([^"]+)"', text)
                    if title_match:
                        article["title"] = title_match.group(1).strip()
                    abstract_match = re.search(r'"abstract"[:\s]+"(.+?)"(?=,\s*"|\})', text, re.DOTALL)
                    if abstract_match:
                        article["abstract"] = abstract_match.group(1).strip()
                break

    if isinstance(result, str):
        try:
            data = json.loads(result)
            if isinstance(data, dict):
                article["title"] = data.get("title", article["title"])
                article["abstract"] = data.get("abstract", "")
            elif isinstance(data, list) and len(data) > 0:
                article_data = data[0]
                if isinstance(article_data, dict):
                    article["title"] = article_data.get("title", article["title"])
                    article["abstract"] = article_data.get("abstract", "")
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
    # Validate inputs
    # FIX: Check for actual content, not just truthiness
    # Empty list [] should be treated as "no genes" but still allow search
    # if other parameters have values
    has_genes = genes is not None and len(genes) > 0
    has_disease = disease is not None and len(disease) > 0
    has_keywords = keywords is not None and len(keywords) > 0

    if not any([has_genes, has_disease, has_keywords]):
        return []

    # Prepare parameters for BioMCP
    genes_list = genes[:5] if genes else None
    diseases_list = [disease] if disease else None
    keywords_list = keywords[:5] if keywords else None

    try:
        return run_async(
            _search_with_biomcp(
                genes=genes_list,
                diseases=diseases_list,
                keywords=keywords_list,
                page_size=max_results,
            ),
            timeout=60,
        )
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
    # Validate inputs
    # FIX: Check for actual content, not just truthiness
    # Empty list [] should be treated as "no genes" but still allow search
    # if other parameters have values
    has_genes = genes is not None and len(genes) > 0
    has_disease = disease is not None and len(disease) > 0
    has_keywords = keywords is not None and len(keywords) > 0

    if not any([has_genes, has_disease, has_keywords]):
        return []

    # Prepare parameters for BioMCP
    genes_list = genes[:5] if genes else None
    diseases_list = [disease] if disease else None
    keywords_list = keywords[:5] if keywords else None

    return await _search_with_biomcp(
        genes=genes_list,
        diseases=diseases_list,
        keywords=keywords_list,
        page_size=max_results,
        biomcp_url=biomcp_url,
    )


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


def _execute_fixed_strategy_search(
    genes: list[str],
    pathways: list[str],
    celltypes: list[str],
    disease: str,
    max_results: int = 20,
) -> dict:
    """Internal fixed-strategy search function (used as fallback).

    Sync wrapper that delegates to _execute_fixed_strategy_search_async.

    Args:
        genes: List of gene names
        pathways: List of pathways
        celltypes: List of cell types
        disease: Disease context
        max_results: Maximum papers to return

    Returns:
        Dictionary with papers, search_queries, and coverage
    """
    return run_async(
        _execute_fixed_strategy_search_async(
            genes=genes,
            pathways=pathways,
            celltypes=celltypes,
            disease=disease,
            max_results=max_results,
        ),
        timeout=120,
    )


async def _execute_fixed_strategy_search_async(
    genes: list[str],
    pathways: list[str],
    celltypes: list[str],
    disease: str,
    max_results: int = 20,
    biomcp_url: str = DEFAULT_BIOMCP_URL,
) -> dict:
    """Async fixed-strategy search function (used as fallback).

    Natively async version of _execute_fixed_strategy_search that uses
    await _search_with_biomcp() directly instead of the executor pattern.
    Implements the same 4-strategy search logic including the lr_pair strategy.

    Args:
        genes: List of gene names
        pathways: List of pathways
        celltypes: List of cell types
        disease: Disease context
        max_results: Maximum papers to return
        biomcp_url: BioMCP server URL

    Returns:
        Dictionary with papers, search_queries, coverage, and search_method
    """
    papers = []
    search_queries = []

    # Strategy 1: Gene + Disease + Interaction focused search
    if genes and disease:
        search_queries.append({
            "type": "gene_disease",
            "genes": genes[:5],
            "diseases": [disease],
            "keywords": [],
        })

    # Strategy 2: Pathway + Cell type search
    if pathways and celltypes:
        pathway_keywords = pathways[:3] + celltypes[:3]
        diseases_list = [disease] if disease else []
        search_queries.append({
            "type": "pathway_celltype",
            "genes": None,
            "diseases": diseases_list,
            "keywords": pathway_keywords,
        })

    # Strategy 3: Ligand-receptor interaction search
    if genes and len(genes) >= 2:
        lr_keywords = ["ligand receptor", "cell-cell interaction", "signaling"]
        diseases_list = [disease] if disease else []
        search_queries.append({
            "type": "lr_pair",
            "genes": genes[:4],
            "diseases": diseases_list,
            "keywords": lr_keywords,
        })

    # Strategy 4: Spatial transcriptomics context
    if celltypes and disease:
        spatial_keywords = ["spatial transcriptomics", "single cell", "tumor microenvironment"]
        spatial_keywords.extend(celltypes[:3])
        search_queries.append({
            "type": "spatial",
            "genes": None,
            "diseases": [disease],
            "keywords": spatial_keywords,
        })

    # Execute searches natively async
    seen_pmids: set[str] = set()
    results_per_query = max(5, max_results // len(search_queries) + 2) if search_queries else 10

    for sq in search_queries:
        try:
            results = await _search_with_biomcp(
                genes=sq.get("genes"),
                diseases=sq.get("diseases"),
                keywords=sq.get("keywords"),
                page_size=results_per_query,
                biomcp_url=biomcp_url,
            )
            for paper in results:
                pmid = paper.get("pmid", "")
                if pmid and pmid not in seen_pmids:
                    seen_pmids.add(pmid)
                    paper["search_type"] = sq["type"]
                    papers.append(paper)
        except Exception as e:
            logger.warning(f"Async fixed strategy search failed for query {sq['type']}: {e}")
            continue

    papers = papers[:max_results]

    # Use unified coverage calculation (same as search_literature_dynamic)
    coverage = _calculate_coverage(papers, genes, pathways, celltypes)

    return {
        "papers": papers,
        "search_queries": [
            {
                "type": sq["type"],
                "genes": sq.get("genes"),
                "diseases": sq.get("diseases"),
                "keywords": sq.get("keywords"),
            }
            for sq in search_queries
        ],
        "coverage": coverage,
        "search_method": "fixed_strategy_fallback",
    }


def _validate_generated_queries(queries: list[dict]) -> list[dict]:
    """Validate and filter LLM-generated queries.

    Args:
        queries: List of query dictionaries from LLM

    Returns:
        List of validated query dictionaries
    """
    validated = []
    for q in queries:
        if not isinstance(q, dict):
            continue

        # Extract fields with defaults
        genes = q.get("genes", [])
        diseases = q.get("diseases", [])
        keywords = q.get("keywords", [])

        # Ensure lists
        if isinstance(genes, str):
            genes = [genes] if genes else []
        if isinstance(diseases, str):
            diseases = [diseases] if diseases else []
        if isinstance(keywords, str):
            keywords = [keywords] if keywords else []

        # Must have at least one non-empty field
        if not any([genes, diseases, keywords]):
            continue

        # Limit field lengths to prevent overly broad queries
        validated.append({
            "genes": genes[:5],
            "diseases": diseases[:3],
            "keywords": keywords[:5],
        })

    return validated


def _parse_llm_queries(response_text: str) -> list[dict]:
    """Parse LLM response to extract query JSON array.

    Args:
        response_text: Raw LLM response text

    Returns:
        List of query dictionaries
    """
    # Try to find JSON array in response
    # Handle markdown code blocks
    text = response_text.strip()

    # Remove markdown code block markers
    if "```json" in text:
        start = text.find("```json") + 7
        end = text.find("```", start)
        if end > start:
            text = text[start:end].strip()
    elif "```" in text:
        start = text.find("```") + 3
        end = text.find("```", start)
        if end > start:
            text = text[start:end].strip()

    # Try to find array boundaries
    if "[" in text and "]" in text:
        start = text.find("[")
        end = text.rfind("]") + 1
        text = text[start:end]

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        elif isinstance(parsed, dict):
            return [parsed]
    except json.JSONDecodeError:
        logger.warning(f"Failed to parse LLM query response: {text[:200]}...")

    return []


# =============================================================================
# Smart Pattern Matching for Gene/Pathway Coverage
# =============================================================================
# Instead of hardcoded aliases, we use intelligent pattern generation:
# 1. Case variations: ADAM10, Adam10, adam10
# 2. Separator variations: ADAM10, ADAM-10, ADAM 10
# 3. Greek letter conversions: TGFβ, TGFB, TGF-beta
# 4. Common suffix patterns: IL6, IL-6, Interleukin-6
#
# This approach:
# - Covers ALL genes automatically (no manual alias maintenance)
# - Works across species (Human: ADAM10, Mouse: Adam10)
# - Zero token cost (pure string manipulation)
# =============================================================================

# Only keep truly non-obvious aliases that can't be pattern-matched
# These are historical names or completely different nomenclature
SPECIAL_GENE_ALIASES = {
    "ACKR3": ["CXCR7"],  # Renamed gene
    "CDH1": ["E-CADHERIN", "ECAD"],
    "CDH2": ["N-CADHERIN", "NCAD"],
    "SNAI1": ["SNAIL"],
    "SNAI2": ["SLUG"],
    "TWIST1": ["TWIST"],
    "VEGFA": ["VEGF"],
    "ERBB2": ["HER2", "NEU"],
    "TNF": ["TNFA"],
    "CXCL12": ["SDF1"],
}

# Pathway keyword mappings (simplified)
PATHWAY_KEYWORDS = {
    "androgen": ["androgen receptor", "ar signaling"],
    "estrogen": ["estrogen receptor", "er signaling"],
    "mapk": ["erk signaling", "ras/mapk", "mek/erk", "erk1", "erk2"],
    "pi3k": ["pi3k/akt", "akt signaling", "mtor"],
    "nfkb": ["nf-kb", "nf-kappab", "nuclear factor kappa", "nf-κb"],
    "egfr": ["erbb", "her family", "egf receptor"],
    "tgf": ["tgf-beta", "tgfb", "smad", "tgf-β"],
    "wnt": ["beta-catenin", "canonical wnt", "β-catenin"],
    "notch": ["delta-notch", "notch signaling"],
    "jak": ["jak/stat", "stat signaling"],
}


def _generate_gene_patterns(gene: str, include_biomcp_aliases: bool = True) -> list[str]:
    """Generate search patterns for a gene name.

    Automatically handles:
    - Case variations: ADAM10, Adam10, adam10
    - Separator variations: ADAM10, ADAM-10, ADAM 10, ADAM_10
    - Number extraction: ADAM10 -> patterns with ADAM and 10
    - Greek letters: β <-> beta, α <-> alpha
    - BioMCP aliases: Dynamically fetched from gene_getter (if cached)

    Works for any species (Human, Mouse, Rat, etc.)

    Args:
        gene: Gene symbol (e.g., "ADAM10", "Tgfb1", "IL-6")
        include_biomcp_aliases: Whether to include BioMCP-fetched aliases

    Returns:
        List of search patterns to match in text
    """
    patterns = set()

    # Normalize input
    gene_clean = gene.strip()

    # 1. Basic case variations
    patterns.add(gene_clean.lower())
    patterns.add(gene_clean.upper())
    patterns.add(gene_clean.capitalize())  # Mouse format: Adam10

    # 2. Extract letters and numbers for separator variations
    # ADAM10 -> letters="ADAM", numbers="10"
    match = re.match(r'^([A-Za-z]+)(\d+)(.*)$', gene_clean)
    if match:
        letters, numbers, suffix = match.groups()
        base = letters.lower()

        # Generate combinations with different separators
        for sep in ['', '-', ' ', '_']:
            combined = f"{base}{sep}{numbers}{suffix.lower()}"
            patterns.add(combined)

        # Also without number (e.g., "adam" for ADAM family mention)
        # Only if number is present - this catches "ADAM family" references
        if len(numbers) <= 2:  # Only for short numbers like 10, 17
            patterns.add(base)

    # 3. Handle hyphenated genes (IL-6 -> IL6, il6, il-6)
    if '-' in gene_clean:
        no_hyphen = gene_clean.replace('-', '')
        patterns.add(no_hyphen.lower())
        patterns.add(no_hyphen.upper())
    else:
        # Try adding hyphen before numbers
        match = re.match(r'^([A-Za-z]+)(\d+)$', gene_clean)
        if match:
            letters, numbers = match.groups()
            patterns.add(f"{letters.lower()}-{numbers}")

    # 4. Greek letter conversions
    greek_map = {
        'α': 'alpha', 'β': 'beta', 'γ': 'gamma', 'δ': 'delta',
        'alpha': 'α', 'beta': 'β', 'gamma': 'γ', 'delta': 'δ',
    }
    gene_lower = gene_clean.lower()
    for greek, latin in greek_map.items():
        if greek in gene_lower:
            patterns.add(gene_lower.replace(greek, latin))

    # 5. Add special aliases if available (hardcoded for common renames)
    gene_upper = gene_clean.upper()
    if gene_upper in SPECIAL_GENE_ALIASES:
        for alias in SPECIAL_GENE_ALIASES[gene_upper]:
            patterns.add(alias.lower())
            # Also generate patterns for the alias (but don't recurse BioMCP)
            alias_patterns = _generate_gene_patterns(alias, include_biomcp_aliases=False)
            patterns.update(alias_patterns)

    return list(patterns)


def _generate_pathway_patterns(pathway: str) -> list[str]:
    """Generate search patterns for a pathway name.

    Handles:
    - Combined pathways: "Androgen;MAPK" -> patterns for both
    - Common variations: MAPK, mapk, erk signaling
    - Greek letters in pathway names

    Args:
        pathway: Pathway name, possibly combined with semicolons

    Returns:
        List of search patterns to match in text
    """
    patterns = set()

    # Split combined pathways (e.g., "Androgen;MAPK")
    pathway_parts = [p.strip() for p in pathway.split(';')]

    for part in pathway_parts:
        part_lower = part.lower()
        patterns.add(part_lower)

        # Add keyword-based patterns
        for key, keywords in PATHWAY_KEYWORDS.items():
            if key in part_lower:
                patterns.update([kw.lower() for kw in keywords])

        # Handle Greek letters
        greek_map = {'β': 'beta', 'α': 'alpha', 'γ': 'gamma'}
        for greek, latin in greek_map.items():
            if greek in part_lower:
                patterns.add(part_lower.replace(greek, latin))
            if latin in part_lower:
                patterns.add(part_lower.replace(latin, greek))

    return list(patterns)


def _normalize_text_for_matching(text: str) -> str:
    """Normalize text for gene/pathway matching.

    Converts to lowercase and normalizes whitespace.
    Keeps hyphens as they're meaningful in gene names.
    """
    return ' '.join(text.lower().split())


def _calculate_coverage(
    papers: list[dict],
    genes: list[str],
    pathways: list[str],
    celltypes: list[str],
) -> dict:
    """Calculate coverage of biological concepts in retrieved papers.

    Uses smart pattern matching for improved coverage:
    - Auto-generates case/separator variations (ADAM10, adam10, adam-10)
    - Works across species (Human: ADAM10, Mouse: Adam10)
    - Handles Greek letters (TGFβ, TGF-beta)
    - Zero token cost (pure string manipulation)

    Args:
        papers: List of paper dictionaries
        genes: Original gene list
        pathways: Original pathway list
        celltypes: Original cell type list

    Returns:
        Coverage dictionary with covered items and percentages
    """
    coverage = {
        "genes_covered": [],
        "genes_matched_by": {},  # Track which pattern matched
        "pathways_covered": [],
        "pathways_matched_by": {},
        "celltypes_covered": [],
        "total_papers": len(papers),
        "genes_coverage_pct": 0.0,
        "pathways_coverage_pct": 0.0,
        "celltypes_coverage_pct": 0.0,
    }

    # Pre-generate all patterns for efficiency
    gene_patterns = {gene: _generate_gene_patterns(gene) for gene in genes}
    pathway_patterns = {pathway: _generate_pathway_patterns(pathway) for pathway in pathways}

    for paper in papers:
        # Normalize text for matching
        combined = _normalize_text_for_matching(
            paper.get("abstract", "") + " " + paper.get("title", "")
        )

        # Gene matching with smart patterns
        for gene in genes:
            if gene in coverage["genes_covered"]:
                continue
            for pattern in gene_patterns[gene]:
                # Use word boundary matching for short patterns to avoid false positives
                if len(pattern) <= 3:
                    # Short patterns need word boundaries
                    if re.search(rf'\b{re.escape(pattern)}\b', combined):
                        coverage["genes_covered"].append(gene)
                        coverage["genes_matched_by"][gene] = pattern
                        break
                else:
                    # Longer patterns can use simple substring match
                    if pattern in combined:
                        coverage["genes_covered"].append(gene)
                        coverage["genes_matched_by"][gene] = pattern
                        break

        # Pathway matching with smart patterns
        for pathway in pathways:
            if pathway in coverage["pathways_covered"]:
                continue
            for pattern in pathway_patterns[pathway]:
                if pattern in combined:
                    coverage["pathways_covered"].append(pathway)
                    coverage["pathways_matched_by"][pathway] = pattern
                    break

        # Cell type matching - use flexible matching
        for celltype in celltypes:
            if celltype in coverage["celltypes_covered"]:
                continue
            # Normalize cell type for matching
            ct_lower = celltype.lower()
            # Try exact match first
            if ct_lower in combined:
                coverage["celltypes_covered"].append(celltype)
            # Try without numbers (e.g., "DCIS 1" -> "dcis")
            elif re.sub(r'\s*\d+\s*', '', ct_lower) in combined:
                coverage["celltypes_covered"].append(celltype)

    # Calculate percentages
    if genes:
        coverage["genes_coverage_pct"] = len(coverage["genes_covered"]) / len(genes) * 100
    if pathways:
        coverage["pathways_coverage_pct"] = len(coverage["pathways_covered"]) / len(pathways) * 100
    if celltypes:
        coverage["celltypes_coverage_pct"] = len(coverage["celltypes_covered"]) / len(celltypes) * 100

    # Calculate missing items (SKILL.md compliance for SEARCHER subagent Phase 4 Reflection)
    coverage["genes_missing"] = [g for g in genes if g not in coverage["genes_covered"]]
    coverage["pathways_missing"] = [p for p in pathways if p not in coverage["pathways_covered"]]
    coverage["celltypes_missing"] = [c for c in celltypes if c not in coverage["celltypes_covered"]]

    return coverage


async def _think_with_biomcp(
    genes: list[str],
    pathways: list[str],
    celltypes: list[str],
    disease: str,
    biomcp_url: str = DEFAULT_BIOMCP_URL,
) -> dict:
    """Execute 3-step strategic thinking via BioMCP think tool.

    Follows biomcp-reference-search skill workflow:
    - Step 1: Context Analysis
    - Step 2: Search Keywords derivation
    - Step 3: Expected Results

    Args:
        genes: List of gene symbols
        pathways: List of pathways
        celltypes: List of cell types
        disease: Disease context
        biomcp_url: BioMCP server URL

    Returns:
        Dictionary with strategic_context string and success flag
    """
    try:
        tools = await get_biomcp_tools(biomcp_url)

        think_tool = find_tool_by_name(tools, "think")

        if think_tool is None:
            logger.warning("BioMCP think tool not found")
            return {"strategic_context": "", "success": False}

        # Build context summary
        context = f"""
Genes: {', '.join(genes[:20]) if genes else 'None'}
Pathways: {', '.join(pathways[:10]) if pathways else 'None'}
Cell types: {', '.join(celltypes) if celltypes else 'None'}
Disease: {disease or 'Not specified'}
Analysis type: CCI (Cell-Cell Interaction) from spatial transcriptomics
"""

        results = []

        # Step 1: Context Analysis
        step1 = await think_tool.ainvoke({
            "thought": f"Context analysis for literature search: {context}",
            "thoughtNumber": 1,
            "totalThoughts": 3,
            "nextThoughtNeeded": True,
        })
        results.append(f"Context: {step1}")

        # Step 2: Search Keywords
        step2 = await think_tool.ainvoke({
            "thought": "Derive search keywords from context: prioritize genes by biological relevance, identify key mechanisms",
            "thoughtNumber": 2,
            "totalThoughts": 3,
            "nextThoughtNeeded": True,
        })
        results.append(f"Keywords: {step2}")

        # Step 3: Expected Results
        step3 = await think_tool.ainvoke({
            "thought": "Expected biological mechanisms and interpretation direction for CCI analysis",
            "thoughtNumber": 3,
            "totalThoughts": 3,
            "nextThoughtNeeded": False,
        })
        results.append(f"Expected: {step3}")

        strategic_context = "\n".join(results)
        logger.info(f"BioMCP think completed successfully (3 steps)")

        return {
            "strategic_context": strategic_context,
            "success": True,
        }

    except Exception as e:
        logger.warning(f"BioMCP think failed: {e}")
        invalidate_client(f"biomcp_{biomcp_url}")
        return {"strategic_context": "", "success": False}


def _execute_biomcp_think(
    genes: list[str],
    pathways: list[str],
    celltypes: list[str],
    disease: str,
) -> dict:
    """Sync wrapper for _think_with_biomcp.

    Args:
        genes: List of gene symbols
        pathways: List of pathways
        celltypes: List of cell types
        disease: Disease context

    Returns:
        Dictionary with strategic_context string and success flag
    """
    try:
        return run_async(_think_with_biomcp(genes, pathways, celltypes, disease), timeout=30)
    except Exception as e:
        logger.warning(f"BioMCP think execution failed: {e}")
        return {"strategic_context": "", "success": False}


async def _think_with_biomcp_for_planner(
    celltypes: list[str],
    pathways: list[str],
    available_analyses: str,
    disease: str,
    biomcp_url: str = DEFAULT_BIOMCP_URL,
) -> dict:
    """Execute 3-step strategic thinking via BioMCP think tool for PLANNER.

    PLANNER-specific chain for interpretation planning context:
    - Step 1: Disease Biology Analysis — analyze celltypes + pathways + tissue context
    - Step 2: Interpretation Directions — suggest promising CCI interpretation focus areas
    - Step 3: Expected Mechanisms — predict key L-R pairs, pathway crosstalk, spatial patterns

    Args:
        celltypes: List of cell types from analysis data
        pathways: List of pathways from analysis data
        available_analyses: Summary of available Part 1/2/3 analyses
        disease: Disease context (inferred from cell types)
        biomcp_url: BioMCP server URL

    Returns:
        Dictionary with strategic_context string and success flag
    """
    try:
        tools = await get_biomcp_tools(biomcp_url)

        think_tool = find_tool_by_name(tools, "think")

        if think_tool is None:
            logger.warning("BioMCP think tool not found for PLANNER")
            return {"strategic_context": "", "success": False}

        # Build context summary (no genes — PLANNER doesn't have gene-level data)
        context = f"""
Cell types: {', '.join(celltypes) if celltypes else 'None'}
Pathways: {', '.join(pathways[:10]) if pathways else 'None'}
Available analyses: {available_analyses}
Disease: {disease or 'Not specified'}
Analysis type: CCI (Cell-Cell Interaction) from spatial transcriptomics
"""

        results = []

        # Step 1: Disease Biology Analysis
        celltypes_str = ', '.join(celltypes) if celltypes else 'unknown'
        pathways_str = ', '.join(pathways[:10]) if pathways else 'unknown'
        step1 = await think_tool.ainvoke({
            "thought": (
                f"Disease biology analysis for {disease}: Given cell types "
                f"[{celltypes_str}] and pathways [{pathways_str}], what are "
                f"the key biological processes and known cell-cell interactions "
                f"in this tissue context?"
            ),
            "thoughtNumber": 1,
            "totalThoughts": 3,
            "nextThoughtNeeded": True,
        })
        results.append(f"Disease Biology: {step1}")

        # Step 2: Interpretation Directions
        step2 = await think_tool.ainvoke({
            "thought": (
                f"Interpretation directions for CCI analysis: Given the disease "
                f"biology and available analyses [{available_analyses}], what "
                f"are the most promising focus areas for cell-cell "
                f"interaction interpretation?"
            ),
            "thoughtNumber": 2,
            "totalThoughts": 3,
            "nextThoughtNeeded": True,
        })
        results.append(f"Interpretation Directions: {step2}")

        # Step 3: Expected Mechanisms
        step3 = await think_tool.ainvoke({
            "thought": (
                "Expected mechanisms: For the identified interpretation directions, "
                "predict key ligand-receptor pairs, pathway crosstalk patterns, "
                "and spatial organization features expected in this tissue."
            ),
            "thoughtNumber": 3,
            "totalThoughts": 3,
            "nextThoughtNeeded": False,
        })
        results.append(f"Expected Mechanisms: {step3}")

        strategic_context = "\n".join(results)
        logger.info("BioMCP think for PLANNER completed successfully (3 steps)")

        return {
            "strategic_context": strategic_context,
            "success": True,
        }

    except Exception as e:
        logger.warning(f"BioMCP think for PLANNER failed: {e}")
        invalidate_client(f"biomcp_{biomcp_url}")
        return {"strategic_context": "", "success": False}


@tool
def generate_biomedical_context(
    celltypes: list[str],
    pathways: list[str],
    available_analyses: str,
    disease: str,
) -> dict:
    """Generate biomedical context for interpretation planning using BioMCP's strategic reasoning.

    Uses BioMCP's think tool to analyze disease biology, suggest interpretation directions,
    and predict expected mechanisms BEFORE literature search. This enriches PLANNER's
    interpretation guide with structured biomedical reasoning.

    Args:
        celltypes: List of cell types from analysis data (e.g., ["Tumor", "Fibroblast", "Macrophage"])
        pathways: List of pathways from analysis data (e.g., ["EMT", "TGFB", "WNT"])
        available_analyses: Summary of available analyses (e.g., "Part 1: spatial, celltype, neighborhood; Part 2: LIANA, NMF")
        disease: Disease context inferred from cell types (e.g., "breast cancer")

    Returns:
        Dictionary with:
        - strategic_context: BioMCP's biomedical reasoning output
        - success: Whether the analysis completed successfully
    """
    try:
        return run_async(
            _think_with_biomcp_for_planner(
                celltypes, pathways, available_analyses, disease
            ),
            timeout=45,
        )
    except Exception as e:
        logger.warning(f"generate_biomedical_context failed: {e}")
        return {"strategic_context": "", "success": False}


@tool
def search_literature_dynamic(
    genes: list[str],
    pathways: list[str],
    celltypes: list[str],
    disease: str,
    max_results: int = 40,
    target_gene_coverage: float = 0.6,
    target_pathway_coverage: float = 0.5,
    max_iterations: int = 3,
) -> dict:
    """LLM-powered dynamic literature search with ITERATIVE coverage improvement.

    Sync wrapper that delegates to search_literature_dynamic_async.
    Uses a single run_async call instead of multiple nested ones.

    This function uses a multi-iteration approach:
    1. Initial broad search based on biological context
    2. Coverage evaluation after each iteration
    3. Gap-filling searches for missing genes/pathways
    4. Early termination when coverage targets are met

    Args:
        genes: List of gene names from analysis (e.g., ["CDH1", "TGFB1", "VIM"])
        pathways: List of pathways identified (e.g., ["EMT", "TGFB", "WNT"])
        celltypes: List of cell types in analysis (e.g., ["Tumor", "Fibroblast"])
        disease: Disease context (e.g., "breast cancer")
        max_results: Maximum number of papers to return (default 40)
        target_gene_coverage: Target gene coverage percentage (default 0.6 = 60%)
        target_pathway_coverage: Target pathway coverage percentage (default 0.5 = 50%)
        max_iterations: Maximum search iterations (default 3)

    Returns:
        Dictionary with:
        - papers: List of relevant papers with pmid, title, abstract
        - generated_queries: All LLM-generated query structures
        - coverage: Final coverage metrics including percentages
        - think_success: Whether BioMCP think was successful
        - iterations: Number of iterations performed
        - coverage_history: Coverage at each iteration
    """
    return run_async(
        search_literature_dynamic_async(
            genes=genes,
            pathways=pathways,
            celltypes=celltypes,
            disease=disease,
            max_results=max_results,
            target_gene_coverage=target_gene_coverage,
            target_pathway_coverage=target_pathway_coverage,
            max_iterations=max_iterations,
        ),
        timeout=300,
    )


async def search_literature_dynamic_async(
    genes: list[str],
    pathways: list[str],
    celltypes: list[str],
    disease: str,
    max_results: int = 40,
    target_gene_coverage: float = 0.6,
    target_pathway_coverage: float = 0.5,
    max_iterations: int = 3,
    biomcp_url: str = DEFAULT_BIOMCP_URL,
) -> dict:
    """Async version of search_literature_dynamic with ITERATIVE coverage improvement.

    Use this function directly in async contexts for better performance.

    Args:
        genes: List of gene names from analysis
        pathways: List of pathways identified
        celltypes: List of cell types in analysis
        disease: Disease context
        max_results: Maximum papers to return (default 40)
        target_gene_coverage: Target gene coverage percentage (default 0.6)
        target_pathway_coverage: Target pathway coverage percentage (default 0.5)
        max_iterations: Maximum search iterations (default 3)
        biomcp_url: BioMCP server URL

    Returns:
        Dictionary with papers, generated_queries, coverage, think_success,
        iterations, and coverage_history
    """
    # Initialize tracking variables
    all_papers = []
    all_queries = []
    seen_pmids = set()
    coverage_history = []

    # Step 0: BioMCP think for strategic planning (once)
    think_result = await _think_with_biomcp(genes, pathways, celltypes, disease, biomcp_url)
    strategic_context = think_result.get("strategic_context", "")

    # Note: Step 0.5 (pre-fetch aliases) removed - BioMCP article_searcher
    # automatically handles gene aliases internally (e.g., ACKR3 -> CXCR7)

    llm = create_llm()

    for iteration in range(max_iterations):
        logger.info(f"=== Async Iteration {iteration + 1}/{max_iterations} ===")

        # Calculate current coverage
        current_coverage = _calculate_coverage(all_papers, genes, pathways, celltypes)
        covered_genes = set(current_coverage.get("genes_covered", []))
        covered_pathways = set(current_coverage.get("pathways_covered", []))

        gene_coverage_pct = current_coverage.get("genes_coverage_pct", 0) / 100
        pathway_coverage_pct = current_coverage.get("pathways_coverage_pct", 0) / 100

        coverage_history.append({
            "iteration": iteration,
            "papers": len(all_papers),
            "gene_coverage": gene_coverage_pct,
            "pathway_coverage": pathway_coverage_pct,
        })

        # Check if targets are met
        if iteration > 0:
            if gene_coverage_pct >= target_gene_coverage and pathway_coverage_pct >= target_pathway_coverage:
                logger.info(f"Coverage targets met: genes={gene_coverage_pct:.1%}, pathways={pathway_coverage_pct:.1%}")
                break
            if len(all_papers) >= max_results:
                logger.info(f"Max results reached: {len(all_papers)}")
                break

        # Generate queries based on iteration
        if iteration == 0:
            # Initial broad search
            # Note: gene_aliases="" - BioMCP article_searcher handles aliases internally
            prompt_text = LITERATURE_QUERY_GENERATION_PROMPT.format(
                genes=", ".join(genes) if genes else "None",
                pathways=", ".join(pathways) if pathways else "None",
                celltypes=", ".join(celltypes) if celltypes else "None",
                disease=disease or "Not specified",
                gene_aliases="",  # BioMCP article_searcher handles aliases internally
                strategic_context=strategic_context,
            )
        else:
            # Gap-filling search for missing genes/pathways
            missing_genes = [g for g in genes if g not in covered_genes]
            missing_pathways = [p for p in pathways if p not in covered_pathways]

            if not missing_genes and not missing_pathways:
                logger.info("No missing genes or pathways to search for")
                break

            # Note: Alias fetching removed - BioMCP article_searcher handles aliases internally
            prompt_text = GAP_FILLING_QUERY_PROMPT.format(
                missing_genes=", ".join(missing_genes) if missing_genes else "None",
                missing_pathways=", ".join(missing_pathways) if missing_pathways else "None",
                disease=disease or "Not specified",
                covered_genes=", ".join(covered_genes) if covered_genes else "None",
                covered_pathways=", ".join(covered_pathways) if covered_pathways else "None",
            )
            logger.info(f"Gap-filling: {len(missing_genes)} missing genes, {len(missing_pathways)} missing pathways")

        # Generate queries using LLM
        try:
            response = await llm.ainvoke([HumanMessage(content=prompt_text)])
            response_text = response.content if hasattr(response, "content") else str(response)
        except Exception as e:
            logger.error(f"LLM query generation failed at iteration {iteration}: {e}")
            if iteration == 0:
                return await _execute_fixed_strategy_search_async(
                    genes=genes,
                    pathways=pathways,
                    celltypes=celltypes,
                    disease=disease,
                    max_results=max_results,
                    biomcp_url=biomcp_url,
                )
            break

        # Parse and validate queries
        raw_queries = _parse_llm_queries(response_text)
        validated_queries = _validate_generated_queries(raw_queries)

        if not validated_queries:
            if iteration == 0:
                logger.warning("No valid queries on first iteration, falling back")
                return await _execute_fixed_strategy_search_async(
                    genes=genes,
                    pathways=pathways,
                    celltypes=celltypes,
                    disease=disease,
                    max_results=max_results,
                    biomcp_url=biomcp_url,
                )
            logger.warning(f"No valid queries at iteration {iteration}, stopping")
            break

        all_queries.extend(validated_queries)
        logger.info(f"Generated {len(validated_queries)} queries for iteration {iteration + 1}")

        # Separate gene-centric and pathway-centric queries for balanced execution
        gene_queries = [q for q in validated_queries if q.get("genes")]
        pathway_queries = [q for q in validated_queries if not q.get("genes")]

        logger.info(f"Query distribution: {len(gene_queries)} gene + {len(pathway_queries)} pathway queries")

        remaining_slots = max_results - len(all_papers)

        # Allocate 60% to gene queries, 40% to pathway queries (minimum 3 per query)
        gene_slots = int(remaining_slots * 0.6) if gene_queries else 0
        pathway_slots = remaining_slots - gene_slots if pathway_queries else remaining_slots

        gene_results_per_query = max(5, gene_slots // len(gene_queries) + 1) if gene_queries else 0
        pathway_results_per_query = max(3, pathway_slots // len(pathway_queries) + 1) if pathway_queries else 0

        logger.info(f"Slot allocation: gene={gene_slots} ({gene_results_per_query}/query), pathway={pathway_slots} ({pathway_results_per_query}/query)")

        # Process gene queries first with higher allocation
        for i, query in enumerate(gene_queries):
            if len(all_papers) >= max_results:
                break

            try:
                results = await _search_with_biomcp(
                    genes=query.get("genes"),
                    diseases=query.get("diseases"),
                    keywords=query.get("keywords"),
                    page_size=gene_results_per_query,
                    biomcp_url=biomcp_url,
                )

                new_papers = 0
                for paper in results:
                    pmid = paper.get("pmid", "")
                    if pmid and pmid not in seen_pmids:
                        seen_pmids.add(pmid)
                        paper["query_index"] = len(all_queries) - len(validated_queries) + i
                        paper["iteration"] = iteration
                        paper["query_type"] = "gene"
                        all_papers.append(paper)
                        new_papers += 1

                logger.debug(f"Gene query {i}: {new_papers} new papers")

            except Exception as e:
                logger.warning(f"Gene search failed for query {i} at iteration {iteration}: {e}")
                continue

        # Process pathway queries with remaining slots
        for i, query in enumerate(pathway_queries):
            if len(all_papers) >= max_results:
                break

            try:
                results = await _search_with_biomcp(
                    genes=query.get("genes"),
                    diseases=query.get("diseases"),
                    keywords=query.get("keywords"),
                    page_size=pathway_results_per_query,
                    biomcp_url=biomcp_url,
                )

                new_papers = 0
                for paper in results:
                    pmid = paper.get("pmid", "")
                    if pmid and pmid not in seen_pmids:
                        seen_pmids.add(pmid)
                        paper["query_index"] = len(all_queries) - len(validated_queries) + len(gene_queries) + i
                        paper["iteration"] = iteration
                        paper["query_type"] = "pathway"
                        all_papers.append(paper)
                        new_papers += 1

                logger.debug(f"Pathway query {i}: {new_papers} new papers")

            except Exception as e:
                logger.warning(f"Pathway search failed for query {i} at iteration {iteration}: {e}")
                continue

    # Final coverage calculation
    final_papers = all_papers[:max_results]
    final_coverage = _calculate_coverage(final_papers, genes, pathways, celltypes)

    coverage_history.append({
        "iteration": "final",
        "papers": len(final_papers),
        "gene_coverage": final_coverage.get("genes_coverage_pct", 0) / 100,
        "pathway_coverage": final_coverage.get("pathways_coverage_pct", 0) / 100,
    })

    return {
        "papers": final_papers,
        "generated_queries": all_queries,
        "coverage": final_coverage,
        "search_method": "search_literature_dynamic",
        "think_success": think_result.get("success", False),
        "iterations": len(coverage_history) - 1,
        "coverage_history": coverage_history,
    }
