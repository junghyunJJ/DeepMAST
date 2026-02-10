"""PubMed E-utilities search tool for Deep Interpreter Agent.

This tool provides direct PubMed search via NCBI E-utilities REST API,
complementing BioMCP's NER-based article_searcher with:
- MeSH subheading filtering
- Date range filtering
- Publication type filtering
- Proximity search
- Raw query syntax control

Uses only Python stdlib (urllib, xml.etree, json) — no extra dependencies.
"""

import asyncio
import json
import logging
import os
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from langchain_core.tools import tool

from src.agents.deep_interpreter.tools.mcp_clients import run_async

logger = logging.getLogger(__name__)

# Backward-compatible module-level aliases (kept for import compatibility;
# all internal usage goes through _get_ncbi_credentials())
NCBI_API_KEY = os.getenv("NCBI_API_KEY", "")
PUBMED_EMAIL = os.getenv("PUBMED_EMAIL", "")
PUBMED_TOOL = "DeepMAST"


def _get_ncbi_credentials() -> tuple[str, str]:
    """Read NCBI credentials at call time (not import time).

    In LangGraph ASGI contexts, .env is loaded after module imports,
    so os.getenv() at import time returns empty strings.
    """
    return os.getenv("NCBI_API_KEY", ""), os.getenv("PUBMED_EMAIL", "")


# Rate limiting: track last request time
# With API key: 10 req/s (0.11s), without: 3 req/s (0.34s)
_last_request_time: float = 0.0
_rate_limit_lock = threading.Lock()


def _rate_limit() -> None:
    """Enforce NCBI rate limit: 10 req/s with API key, 3 req/s without.

    Safe to call from any context — uses only synchronous primitives.
    Should be called inside executor threads, not on the event loop.
    """
    global _last_request_time
    with _rate_limit_lock:
        api_key, _ = _get_ncbi_credentials()
        interval = 0.11 if api_key else 0.34
        elapsed = time.time() - _last_request_time
        if elapsed < interval:
            time.sleep(interval - elapsed)
        _last_request_time = time.time()


# =============================================================================
# E-utilities API functions
# =============================================================================

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


async def _search_with_eutilities(
    query: str,
    max_results: int = 20,
    sort: str = "relevance",
    min_date: str | None = None,
    max_date: str | None = None,
) -> dict:
    """Execute PubMed search via NCBI E-utilities REST API directly.

    Flow:
    1. ESearch → PMID list
    2. EFetch → article XML for each PMID batch
    3. Parse XML → {"pmid", "title", "abstract"} dicts

    Args:
        query: Raw PubMed query string (e.g., "VEGFA[tiab] AND cancer[mh]")
        max_results: Maximum papers to return (capped at 100)
        sort: Sort order - "relevance" or "pub_date"
        min_date: Start date filter (YYYY/MM/DD format)
        max_date: End date filter (YYYY/MM/DD format)

    Returns:
        Dict with papers list, query_used, total_results, returned_results, source
    """
    max_results = min(max_results, 100)

    # Read credentials at call time (not import time) for ASGI compatibility
    api_key, email = _get_ncbi_credentials()

    # Build ESearch URL
    params = {
        "db": "pubmed",
        "term": query,
        "retmax": str(max_results),
        "retmode": "json",
        "sort": sort,
    }
    if email:
        params["email"] = email
        params["tool"] = PUBMED_TOOL
    if api_key:
        params["api_key"] = api_key
    if min_date:
        params["mindate"] = min_date
        params["datetype"] = "pdat"  # publication date
    if max_date:
        params["maxdate"] = max_date
        if "datetype" not in params:
            params["datetype"] = "pdat"

    esearch_url = f"{ESEARCH_URL}?{urllib.parse.urlencode(params)}"

    # Step 1: ESearch — get PMIDs
    loop = asyncio.get_running_loop()

    def _esearch_with_rate_limit():
        _rate_limit()
        return urllib.request.urlopen(esearch_url, timeout=30).read()

    try:
        esearch_response = await loop.run_in_executor(None, _esearch_with_rate_limit)
        esearch_data = json.loads(esearch_response)
        esearch_result = esearch_data.get("esearchresult", {})
        pmids = esearch_result.get("idlist", [])
        total_count = int(esearch_result.get("count", 0))
        query_translation = esearch_result.get("querytranslation", query)
    except Exception as e:
        logger.error(f"ESearch failed for query '{query}': {e}")
        return {
            "papers": [],
            "query_used": query,
            "total_results": 0,
            "returned_results": 0,
            "source": "pubmed_eutils",
            "error": str(e),
        }

    if not pmids:
        return {
            "papers": [],
            "query_used": query_translation,
            "total_results": total_count,
            "returned_results": 0,
            "source": "pubmed_eutils",
        }

    # Step 2: EFetch — get article details (batch, max 200 per request)
    papers = []
    # Process in batches of 50
    for batch_start in range(0, len(pmids), 50):
        batch_pmids = pmids[batch_start:batch_start + 50]
        efetch_params = {
            "db": "pubmed",
            "id": ",".join(batch_pmids),
            "rettype": "xml",
            "retmode": "xml",
        }
        if email:
            efetch_params["email"] = email
            efetch_params["tool"] = PUBMED_TOOL
        if api_key:
            efetch_params["api_key"] = api_key
        efetch_url = f"{EFETCH_URL}?{urllib.parse.urlencode(efetch_params)}"

        def _efetch_with_rate_limit(url=efetch_url):
            _rate_limit()
            return urllib.request.urlopen(url, timeout=30).read()

        try:
            efetch_response = await loop.run_in_executor(None, _efetch_with_rate_limit)
            batch_papers = _parse_pubmed_xml(efetch_response)
            papers.extend(batch_papers)
        except Exception as e:
            logger.warning(f"EFetch failed for batch starting at {batch_start}: {e}")
            # Add stub entries for failed PMIDs
            for pmid in batch_pmids:
                papers.append({
                    "pmid": pmid,
                    "title": f"Article {pmid}",
                    "abstract": "",
                    "search_type": "eutils_advanced",
                })

    # Add search_type to all papers
    for paper in papers:
        paper["search_type"] = "eutils_advanced"

    return {
        "papers": papers,
        "query_used": query_translation,
        "total_results": total_count,
        "returned_results": len(papers),
        "source": "pubmed_eutils",
    }


def _parse_pubmed_xml(xml_data: bytes) -> list[dict]:
    """Parse PubMed EFetch XML response into paper dictionaries.

    Extracts: PMID, ArticleTitle, AbstractText from PubmedArticle elements.

    Args:
        xml_data: Raw XML bytes from EFetch

    Returns:
        List of {"pmid", "title", "abstract"} dicts
    """
    papers = []
    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as e:
        logger.error(f"XML parse error: {e}")
        return papers

    for article_elem in root.findall(".//PubmedArticle"):
        paper = {"pmid": "", "title": "", "abstract": ""}

        # Extract PMID
        pmid_elem = article_elem.find(".//PMID")
        if pmid_elem is not None and pmid_elem.text:
            paper["pmid"] = pmid_elem.text.strip()

        # Extract title
        title_elem = article_elem.find(".//ArticleTitle")
        if title_elem is not None:
            # ArticleTitle may contain inline tags; get all text
            paper["title"] = "".join(title_elem.itertext()).strip()

        # Extract abstract (may have multiple AbstractText sections)
        abstract_parts = []
        for abstract_text in article_elem.findall(".//AbstractText"):
            label = abstract_text.get("Label", "")
            text = "".join(abstract_text.itertext()).strip()
            if label and text:
                abstract_parts.append(f"{label}: {text}")
            elif text:
                abstract_parts.append(text)
        paper["abstract"] = " ".join(abstract_parts)

        if paper["pmid"]:
            papers.append(paper)

    return papers


# =============================================================================
# Query builder helper
# =============================================================================

def _sanitize_pubmed_term(term: str) -> str:
    """Sanitize a term for use in PubMed queries.

    Removes characters that could break query syntax.
    """
    # Remove unbalanced quotes and special PubMed operators
    sanitized = term.replace('"', '').replace('[', '').replace(']', '')
    return sanitized.strip()


def build_pubmed_query(
    genes: list[str] | None = None,
    pathways: list[str] | None = None,
    celltypes: list[str] | None = None,
    disease: str = "",
    mesh_terms: list[str] | None = None,
    publication_types: list[str] | None = None,
    date_range: tuple[str, str] | None = None,
    free_text: str = "",
) -> str:
    """Build a PubMed query string from structured parameters.

    Convenience function that constructs proper E-utilities query syntax.
    Useful when the LLM needs help constructing raw queries.

    Args:
        genes: Gene symbols to search in title/abstract (e.g., ["VEGFA", "CDH1"])
        pathways: Pathway names for title/abstract search (e.g., ["TGF-beta", "WNT"])
        celltypes: Cell type names for title/abstract (e.g., ["fibroblast", "macrophage"])
        disease: Disease context as MeSH or free text
        mesh_terms: Explicit MeSH terms (e.g., ["neoplasms/therapy", "signal transduction"])
        publication_types: Publication type filters (e.g., ["systematic review", "review"])
        date_range: Tuple of (min_date, max_date) in YYYY/MM/DD format
        free_text: Additional free text to AND with the query

    Returns:
        Formatted PubMed query string ready for search_pubmed_advanced
    """
    parts = []

    # Genes: OR together, search in title/abstract
    if genes:
        gene_terms = " OR ".join(f"{_sanitize_pubmed_term(g)}[tiab]" for g in genes)
        parts.append(f"({gene_terms})")

    # Pathways: OR together, search in title/abstract
    if pathways:
        pathway_terms = " OR ".join(f'"{_sanitize_pubmed_term(p)}"[tiab]' for p in pathways)
        parts.append(f"({pathway_terms})")

    # Cell types: OR together, search in title/abstract
    if celltypes:
        ct_terms = " OR ".join(f'"{_sanitize_pubmed_term(ct)}"[tiab]' for ct in celltypes)
        parts.append(f"({ct_terms})")

    # Disease: prefer MeSH if looks like a standard term
    if disease:
        parts.append(f'"{_sanitize_pubmed_term(disease)}"[tiab]')

    # Explicit MeSH terms
    if mesh_terms:
        for mesh in mesh_terms:
            parts.append(f"{mesh}[mh]")

    # Publication types
    if publication_types:
        pt_terms = " OR ".join(f'"{pt}"[pt]' for pt in publication_types)
        parts.append(f"({pt_terms})")

    # Date range
    if date_range and len(date_range) == 2:
        min_d, max_d = date_range
        if min_d and max_d:
            parts.append(f"{min_d}:{max_d}[dp]")
        elif min_d:
            parts.append(f"{min_d}:3000[dp]")
        elif max_d:
            parts.append(f"1900:{max_d}[dp]")

    # Free text
    if free_text:
        parts.append(f"({free_text})")

    return " AND ".join(parts)


# =============================================================================
# LangChain @tool decorated function
# =============================================================================

@tool
def search_pubmed_advanced(
    query: str,
    max_results: int = 20,
    sort: str = "relevance",
    min_date: str = "",
    max_date: str = "",
) -> dict:
    """Search PubMed using advanced E-utilities query syntax.

    Use this tool when you need:
    - MeSH term filtering: "diabetes mellitus/therapy[mh]"
    - Date range: min_date="2020/01/01", max_date="2025/12/31"
    - Publication type: "systematic review[pt]"
    - Field-specific search: "VEGFA[tiab] AND spatial transcriptomics[tiab]"
    - Proximity search: '"term1 term2"[TIAB:~5]'

    For entity-based search (gene/disease NER), use search_literature_dynamic instead.

    Args:
        query: PubMed query string with field tags (e.g., "VEGFA[tiab] AND cancer[mh]")
        max_results: Maximum papers to return (default 20, max 100)
        sort: Sort order - "relevance" or "pub_date"
        min_date: Start date filter (YYYY/MM/DD format, optional)
        max_date: End date filter (YYYY/MM/DD format, optional)

    Returns:
        Dict with papers list, query used, and result count
    """
    if not query or not query.strip():
        return {
            "papers": [],
            "query_used": "",
            "total_results": 0,
            "returned_results": 0,
            "source": "pubmed_eutils",
            "error": "Empty query provided",
        }

    # Clamp max_results
    max_results = max(1, min(max_results, 100))

    # Convert empty strings to None for the async function
    min_date_val = min_date.strip() if min_date and min_date.strip() else None
    max_date_val = max_date.strip() if max_date and max_date.strip() else None

    # Run async function using shared executor from mcp_clients
    try:
        return run_async(
            _search_with_eutilities(
                query=query.strip(),
                max_results=max_results,
                sort=sort,
                min_date=min_date_val,
                max_date=max_date_val,
            ),
            timeout=60,
        )
    except Exception as e:
        logger.error(f"search_pubmed_advanced failed: {e}")
        return {
            "papers": [],
            "query_used": query,
            "total_results": 0,
            "returned_results": 0,
            "source": "pubmed_eutils",
            "error": str(e),
        }
