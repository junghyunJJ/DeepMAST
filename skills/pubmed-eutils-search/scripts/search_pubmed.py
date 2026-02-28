"""Standalone synchronous PubMed E-utilities search module.

Extracted from deep_interpreter's pubmed_eutils.py with async removed.
Uses only Python stdlib — no external dependencies.

Usage:
    from skills.pubmed_eutils_search.scripts.search_pubmed import search_pubmed, build_pubmed_query
    result = search_pubmed("VEGFA[tiab] AND cancer[mh]", max_results=10)
"""

import json
import logging
import os
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

PUBMED_TOOL = "DeepMAST"

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

# Rate limiting state
_last_request_time: float = 0.0
_rate_limit_lock = threading.Lock()


def _get_ncbi_credentials() -> tuple[str, str]:
    """Read NCBI credentials at call time (not import time)."""
    return os.getenv("NCBI_API_KEY", ""), os.getenv("PUBMED_EMAIL", "")


def _rate_limit() -> None:
    """Enforce NCBI rate limit: 10 req/s with API key, 3 req/s without."""
    global _last_request_time
    with _rate_limit_lock:
        api_key, _ = _get_ncbi_credentials()
        interval = 0.11 if api_key else 0.34
        elapsed = time.time() - _last_request_time
        if elapsed < interval:
            time.sleep(interval - elapsed)
        _last_request_time = time.time()


def _parse_pubmed_xml(xml_data: bytes) -> list[dict]:
    """Parse PubMed EFetch XML response into paper dictionaries.

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

        pmid_elem = article_elem.find(".//PMID")
        if pmid_elem is not None and pmid_elem.text:
            paper["pmid"] = pmid_elem.text.strip()

        title_elem = article_elem.find(".//ArticleTitle")
        if title_elem is not None:
            paper["title"] = "".join(title_elem.itertext()).strip()

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


def _sanitize_pubmed_term(term: str) -> str:
    """Sanitize a term for use in PubMed queries."""
    sanitized = term.replace('"', '').replace('[', '').replace(']', '')
    return sanitized.strip()


def search_pubmed(
    query: str,
    max_results: int = 20,
    sort: str = "relevance",
    min_date: str | None = None,
    max_date: str | None = None,
) -> dict:
    """Execute PubMed search via NCBI E-utilities REST API (synchronous).

    Args:
        query: Raw PubMed query string (e.g., "VEGFA[tiab] AND cancer[mh]")
        max_results: Maximum papers to return (capped at 100)
        sort: Sort order - "relevance" or "pub_date"
        min_date: Start date filter (YYYY/MM/DD format)
        max_date: End date filter (YYYY/MM/DD format)

    Returns:
        Dict with papers list, query_used, total_results, returned_results, source
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

    max_results = max(1, min(max_results, 100))
    api_key, email = _get_ncbi_credentials()

    # Build ESearch params
    params = {
        "db": "pubmed",
        "term": query.strip(),
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
        params["datetype"] = "pdat"
    if max_date:
        params["maxdate"] = max_date
        if "datetype" not in params:
            params["datetype"] = "pdat"

    esearch_url = f"{ESEARCH_URL}?{urllib.parse.urlencode(params)}"

    # Step 1: ESearch — get PMIDs
    try:
        _rate_limit()
        esearch_response = urllib.request.urlopen(esearch_url, timeout=30).read()
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

    # Step 2: EFetch — get article details (batch of 50)
    papers = []
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

        try:
            _rate_limit()
            efetch_response = urllib.request.urlopen(efetch_url, timeout=30).read()
            batch_papers = _parse_pubmed_xml(efetch_response)
            papers.extend(batch_papers)
        except Exception as e:
            logger.warning(f"EFetch failed for batch starting at {batch_start}: {e}")
            for pmid in batch_pmids:
                papers.append({
                    "pmid": pmid,
                    "title": f"Article {pmid}",
                    "abstract": "",
                    "search_type": "eutils_advanced",
                })

    for paper in papers:
        paper["search_type"] = "eutils_advanced"

    return {
        "papers": papers,
        "query_used": query_translation,
        "total_results": total_count,
        "returned_results": len(papers),
        "source": "pubmed_eutils",
    }


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

    Args:
        genes: Gene symbols to search in title/abstract
        pathways: Pathway names for title/abstract search
        celltypes: Cell type names for title/abstract
        disease: Disease context as MeSH or free text
        mesh_terms: Explicit MeSH terms
        publication_types: Publication type filters
        date_range: Tuple of (min_date, max_date) in YYYY/MM/DD format
        free_text: Additional free text to AND with the query

    Returns:
        Formatted PubMed query string
    """
    parts = []

    if genes:
        gene_terms = " OR ".join(f"{_sanitize_pubmed_term(g)}[tiab]" for g in genes)
        parts.append(f"({gene_terms})")

    if pathways:
        pathway_terms = " OR ".join(f'"{_sanitize_pubmed_term(p)}"[tiab]' for p in pathways)
        parts.append(f"({pathway_terms})")

    if celltypes:
        ct_terms = " OR ".join(f'"{_sanitize_pubmed_term(ct)}"[tiab]' for ct in celltypes)
        parts.append(f"({ct_terms})")

    if disease:
        parts.append(f'"{_sanitize_pubmed_term(disease)}"[tiab]')

    if mesh_terms:
        for mesh in mesh_terms:
            parts.append(f"{mesh}[mh]")

    if publication_types:
        pt_terms = " OR ".join(f'"{pt}"[pt]' for pt in publication_types)
        parts.append(f"({pt_terms})")

    if date_range and len(date_range) == 2:
        min_d, max_d = date_range
        if min_d and max_d:
            parts.append(f"{min_d}:{max_d}[dp]")
        elif min_d:
            parts.append(f"{min_d}:3000[dp]")
        elif max_d:
            parts.append(f"1900:{max_d}[dp]")

    if free_text:
        parts.append(f"({free_text})")

    return " AND ".join(parts)
