"""Literature search tool for Deep Interpreter Agent.

This tool provides PubMed search capabilities via BioMCP for finding
supporting literature for CCI interpretations.

Includes fixed-strategy internal fallback (_execute_fixed_strategy_search) and
LLM-powered dynamic query generation (search_literature_dynamic).
"""

import asyncio
import csv
import json
import logging
import math
import os
import re
import threading
import urllib.parse
import urllib.request
from pathlib import Path
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


def _sync_save_json(dir_path: str, file_path: str, data: dict) -> None:
    """Sync helper for saving JSON to disk (used via asyncio.to_thread)."""
    os.makedirs(dir_path, exist_ok=True)
    with open(file_path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# =============================================================================
# Dynamic Gene Alias Cache (BioMCP gene_getter)
# =============================================================================
# Session-level cache for gene aliases fetched from BioMCP
# This avoids repeated API calls for the same gene
_GENE_ALIAS_CACHE: dict[str, list[str]] = {}
_GENE_ALIAS_CACHE_LOCK = threading.Lock()

# Session-level cache for disease synonyms fetched from BioMCP + rule-based expansion
_DISEASE_SYNONYM_CACHE: dict[str, list[str]] = {}
_DISEASE_SYNONYM_CACHE_LOCK = threading.Lock()

# SJR (Scimago Journal Rank) Composite Score Cache
_SJR_SCORE_CACHE: dict[str, float] = {}  # normalized_name -> composite score (0-1)
_SJR_SCORE_CACHE_LOCK = threading.Lock()
_SJR_CACHE_LOADED = False

_SJR_CSV_URL = "https://raw.githubusercontent.com/Michael-E-Rose/SCImagoJournalRankIndicators/master/all.csv"
_SJR_DEFAULT_SCORE = 0.5
_SJR_CACHE_DIR = Path.home() / ".cache" / "deepmast"
_SJR_CACHE_FILE = _SJR_CACHE_DIR / "sjr_all.csv"
_SJR_CACHE_MAX_AGE_DAYS = 90

# Composite score weights
_SJR_WEIGHT = 0.4       # Journal prestige (PageRank-based)
_HINDEX_WEIGHT = 0.3    # Cumulative impact
_AVGCIT_WEIGHT = 0.3    # Recent citation impact (IF proxy)


def _normalize_journal_name(name: str) -> str:
    """Normalize journal name for SJR lookup.

    Lowercase, strip 'the ' prefix, collapse whitespace, expand common abbreviations.
    """
    n = name.lower().strip()
    if n.startswith("the "):
        n = n[4:]
    # Expand common abbreviations
    abbrev_map = {
        "j.": "journal",
        "int.": "international",
        "sci.": "science",
        "res.": "research",
        "med.": "medicine",
        "biol.": "biology",
        "chem.": "chemistry",
        "phys.": "physics",
        "proc.": "proceedings",
        "natl.": "national",
        "acad.": "academy",
        "am.": "american",
        "eur.": "european",
        "mol.": "molecular",
        "cell.": "cellular",
        "biochem.": "biochemistry",
        "biophys.": "biophysical",
        "genet.": "genetics",
        "immunol.": "immunology",
        "neurosci.": "neuroscience",
        "pharmacol.": "pharmacology",
        "physiol.": "physiology",
        "rev.": "review",
        "ann.": "annals",
        "clin.": "clinical",
        "exp.": "experimental",
        "dev.": "developmental",
        "environ.": "environmental",
        "microbiol.": "microbiology",
    }
    for abbr, full in abbrev_map.items():
        n = n.replace(abbr, full)
    # Collapse whitespace
    n = re.sub(r"\s+", " ", n).strip()
    return n


def _download_sjr_csv_sync() -> str:
    """Download SJR CSV to local cache. Returns path to cached file.

    Uses ~/.cache/deepmast/sjr_all.csv with 90-day max age.
    Falls back to stale cache on download failure, empty string if no cache exists.
    """
    import time as _time

    _SJR_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Check if cached file is fresh enough
    if _SJR_CACHE_FILE.exists():
        age_days = (_time.time() - _SJR_CACHE_FILE.stat().st_mtime) / 86400
        if age_days < _SJR_CACHE_MAX_AGE_DAYS:
            logger.debug(f"SJR cache is fresh ({age_days:.0f} days old)")
            return str(_SJR_CACHE_FILE)

    # Download
    try:
        logger.info(f"Downloading SJR CSV from {_SJR_CSV_URL}")
        req = urllib.request.Request(_SJR_CSV_URL, headers={"User-Agent": "DeepMAST/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        _SJR_CACHE_FILE.write_bytes(data)
        logger.info(f"SJR CSV cached at {_SJR_CACHE_FILE} ({len(data)} bytes)")
        return str(_SJR_CACHE_FILE)
    except Exception as e:
        logger.warning(f"SJR CSV download failed: {e}")
        # Fall back to stale cache
        if _SJR_CACHE_FILE.exists():
            logger.info("Using stale SJR cache")
            return str(_SJR_CACHE_FILE)
        return ""


def _build_sjr_lookup(csv_path: str) -> dict[str, float]:
    """Parse SJR CSV and build composite score lookup.

    For each journal, uses the most recent year's data.
    When a journal appears in multiple ASJC fields, takes the max values.
    Composite = SJR_norm * 0.4 + hindex_norm * 0.3 + avgcit_norm * 0.3
    Each metric is log-normalized: log(1+x) / log(1+max_x) -> [0, 1]
    """
    if not csv_path:
        return {}

    # Phase 1: Collect raw values per journal (latest year, max across fields)
    raw: dict[str, tuple[int, float, float, float]] = {}
    # raw[name] = (year, sjr, h_index, avg_citations)

    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                title = row.get("Title", "").strip()
                if not title:
                    continue
                name = _normalize_journal_name(title)

                try:
                    year = int(row.get("Year", "0"))
                except (ValueError, TypeError):
                    year = 0

                try:
                    sjr_val = float(row.get("SJR", "0") or "0")
                except (ValueError, TypeError):
                    sjr_val = 0.0

                try:
                    h_val = float(row.get("h-index", "0") or "0")
                except (ValueError, TypeError):
                    h_val = 0.0

                try:
                    avg_cit = float(row.get("avg_citations", "0") or "0")
                except (ValueError, TypeError):
                    avg_cit = 0.0

                if name in raw:
                    existing_year = raw[name][0]
                    if year > existing_year:
                        # Newer year replaces
                        raw[name] = (year, sjr_val, h_val, avg_cit)
                    elif year == existing_year:
                        # Same year: take max of each metric
                        _, e_sjr, e_h, e_cit = raw[name]
                        raw[name] = (year, max(sjr_val, e_sjr), max(h_val, e_h), max(avg_cit, e_cit))
                else:
                    raw[name] = (year, sjr_val, h_val, avg_cit)
    except Exception as e:
        logger.warning(f"Failed to parse SJR CSV: {e}")
        return {}

    if not raw:
        return {}

    # Phase 2: Find max values for log-normalization
    max_sjr = max(v[1] for v in raw.values()) or 1.0
    max_h = max(v[2] for v in raw.values()) or 1.0
    max_cit = max(v[3] for v in raw.values()) or 1.0

    log_max_sjr = math.log(1 + max_sjr)
    log_max_h = math.log(1 + max_h)
    log_max_cit = math.log(1 + max_cit)

    # Phase 3: Compute composite scores
    lookup: dict[str, float] = {}
    for name, (_, sjr_val, h_val, cit_val) in raw.items():
        sjr_norm = math.log(1 + sjr_val) / log_max_sjr if log_max_sjr > 0 else 0.0
        h_norm = math.log(1 + h_val) / log_max_h if log_max_h > 0 else 0.0
        cit_norm = math.log(1 + cit_val) / log_max_cit if log_max_cit > 0 else 0.0
        composite = sjr_norm * _SJR_WEIGHT + h_norm * _HINDEX_WEIGHT + cit_norm * _AVGCIT_WEIGHT
        lookup[name] = round(composite, 4)

    logger.info(f"SJR lookup built: {len(lookup)} journals")
    return lookup


async def _ensure_sjr_cache_loaded() -> None:
    """Load SJR composite scores into _SJR_SCORE_CACHE (once)."""
    global _SJR_CACHE_LOADED
    if _SJR_CACHE_LOADED:
        return

    with _SJR_SCORE_CACHE_LOCK:
        if _SJR_CACHE_LOADED:
            return

        csv_path = await asyncio.to_thread(_download_sjr_csv_sync)
        lookup = await asyncio.to_thread(_build_sjr_lookup, csv_path)

        _SJR_SCORE_CACHE.update(lookup)
        _SJR_CACHE_LOADED = True
        logger.info(f"SJR cache loaded: {len(_SJR_SCORE_CACHE)} journals")


def _get_journal_quality(journal_name: str) -> float:
    """Get composite journal quality score (0-1) from SJR cache.

    Returns _SJR_DEFAULT_SCORE (0.5) for unknown journals.
    """
    if not journal_name:
        return _SJR_DEFAULT_SCORE

    name = _normalize_journal_name(journal_name)
    score = _SJR_SCORE_CACHE.get(name)
    if score is not None:
        return score

    # Fallback: try stripping after colon (e.g. "PLoS ONE : e12345" -> "plos one")
    if ":" in name:
        stripped = _normalize_journal_name(name.split(":")[0])
        score = _SJR_SCORE_CACHE.get(stripped)
        if score is not None:
            return score

    return _SJR_DEFAULT_SCORE


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
    enforce_disease_match: bool = False,
    rerank_mode: str = "off",
    rerank_top_n: int = 12,
    rerank_min_confidence: float = 0.70,
    rerank_stats: dict[str, int] | None = None,
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
        enforce_disease_match: When True, require title/abstract to match disease context
        rerank_mode: "off" or "llm" for optional second-stage reranking
        rerank_top_n: Maximum boundary papers to rerank via LLM
        rerank_min_confidence: Minimum confidence threshold for rerank decisions
        rerank_stats: Optional mutable counter dict for rerank telemetry aggregation

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

    normalized_rerank_mode = _normalize_rerank_mode(rerank_mode)

    # Post-filter to reduce cross-disease retrieval noise
    if enforce_disease_match and diseases:
        disease_terms = [d for d in diseases if isinstance(d, str) and d.strip()]

        # Mandatory pre-warming: fetch disease synonyms once per disease (async context)
        # After this, get_disease_match_terms() inside _paper_matches_disease_context
        # will hit the cache (pure dict lookup, no event loop blocking).
        for d in disease_terms:
            try:
                await _get_disease_synonyms_async(d, biomcp_url)
            except Exception:
                pass  # Graceful degradation: rule-based terms still available

        before_articles = list(articles)
        articles = [a for a in before_articles if _paper_matches_disease_context(a, disease_terms)]
        filtered = len(before_articles) - len(articles)
        if filtered:
            logger.debug(f"Filtered out {filtered} papers by disease context")

        if normalized_rerank_mode == "llm":
            kept_pmids = {str(a.get("pmid", "")) for a in articles}
            removed_articles = [
                a
                for a in before_articles
                if str(a.get("pmid", "")) and str(a.get("pmid", "")) not in kept_pmids
            ]
            articles, local_stats = await _rerank_disease_relevance_with_llm(
                kept_articles=articles,
                removed_articles=removed_articles,
                diseases=disease_terms,
                top_n=rerank_top_n,
                min_confidence=rerank_min_confidence,
            )
            if rerank_stats is not None:
                _merge_rerank_stats(rerank_stats, local_stats)
            if local_stats.get("applied_count", 0):
                logger.debug(
                    "LLM rerank applied: %s",
                    {
                        "applied_count": local_stats.get("applied_count", 0),
                        "dropped_count": local_stats.get("dropped_count", 0),
                        "promoted_count": local_stats.get("promoted_count", 0),
                    },
                )

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


def _normalize_for_filter(text: str) -> str:
    """Normalize text for boolean matching in post-search filtering."""
    normalized = (text or "").lower()
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


# Organ alias mapping: common name → medical/Latin terms (unidirectional)
# Avoids false positives from reverse mapping (e.g., "cerebral palsy" → "brain palsy")
_ORGAN_TO_MEDICAL: dict[str, list[str]] = {
    "liver": ["hepatic", "hepatocellular"],
    "kidney": ["renal"],
    "lung": ["pulmonary"],
    "brain": ["cerebral"],
    "colon": ["colorectal"],
    "stomach": ["gastric"],
    "pancreas": ["pancreatic"],
    "skin": ["cutaneous"],
    "bone": ["osseous"],
    "ovary": ["ovarian"],
    "prostate": ["prostatic"],
    "bladder": ["urothelial"],
    "uterus": ["uterine", "endometrial"],
    "breast": ["mammary"],
}

# --- UBERON Organ Synonym Cache ---
_ORGAN_SYNONYM_CACHE: dict[str, list[str]] = {}
_ORGAN_SYNONYM_CACHE_LOCK = threading.Lock()

_UBERON_STOPWORDS = frozenset({
    "gland", "body", "zone", "part", "pair", "lobe", "wall",
    "area", "region", "left", "right", "upper", "lower",
    "organ", "tissue", "system", "structure", "proper",
})


async def _resolve_uberon_organ_synonyms(organ: str) -> list[str]:
    """Resolve organ synonyms via EBI OLS4 UBERON ontology lookup.

    2-phase lookup:
    - Phase 1 (Search): Find UBERON term, extract synonyms
    - Phase 2 (Term detail): Extract relational adjectives (e.g., liver→hepatic)

    Args:
        organ: Organ name (e.g., "breast", "liver")

    Returns:
        List of synonym strings. Returns [] on failure WITHOUT caching.
    """
    encoded = urllib.parse.quote(organ)
    search_url = f"https://www.ebi.ac.uk/ols4/api/search?q={encoded}&ontology=uberon&rows=3"

    synonyms: list[str] = []
    obo_id = None

    try:
        # Phase 1: Search for UBERON term
        def _fetch_search():
            req = urllib.request.Request(search_url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read().decode("utf-8"))

        data = await asyncio.to_thread(_fetch_search)
        docs = data.get("response", {}).get("docs", [])

        for doc in docs:
            label = (doc.get("label") or "").lower()
            if organ.lower() in label or label in organ.lower():
                # Extract synonyms from search result
                for field in ["synonym", "exact_synonym", "related_synonym"]:
                    raw = doc.get(field, [])
                    if isinstance(raw, list):
                        synonyms.extend([s.lower() for s in raw if isinstance(s, str)])
                    elif isinstance(raw, str):
                        synonyms.append(raw.lower())
                obo_id = doc.get("obo_id")
                break

        # Phase 2: Term detail for relational adjectives
        if obo_id:
            iri = urllib.parse.quote(urllib.parse.quote(
                f"http://purl.obolibrary.org/obo/{obo_id.replace(':', '_')}",
                safe="",
            ))
            term_url = f"https://www.ebi.ac.uk/ols4/api/ontologies/uberon/terms/{iri}"

            def _fetch_term():
                req = urllib.request.Request(term_url, headers={"Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    return json.loads(resp.read().decode("utf-8"))

            try:
                term_data = await asyncio.to_thread(_fetch_term)
                annotation = term_data.get("annotation", {})
                # Relational adjectives (e.g., liver→"hepatic", kidney→"renal")
                adj_list = annotation.get("has_relational_adjective", [])
                if isinstance(adj_list, list):
                    synonyms.extend([a.lower() for a in adj_list if isinstance(a, str)])
                elif isinstance(adj_list, str):
                    synonyms.append(adj_list.lower())
            except Exception:
                pass  # Phase 2 failure is non-fatal

        # Post-processing: extract single-word medical adjectives from multi-word synonyms
        extracted: list[str] = []
        for syn in synonyms:
            words = syn.split()
            if len(words) > 1:
                # Keep multi-word synonym AND extract individual adjective-like words
                for word in words:
                    if len(word) > 5 and word != organ.lower() and word not in _UBERON_STOPWORDS:
                        extracted.append(word)
        synonyms.extend(extracted)

        # Deduplicate and remove the organ itself
        unique = []
        organ_lower = organ.lower()
        for s in synonyms:
            s = s.strip()
            if s and s != organ_lower and s not in unique:
                unique.append(s)

        logger.debug(f"UBERON synonyms for '{organ}': {unique[:8]}")
        return unique

    except Exception as e:
        logger.debug(f"UBERON lookup failed for '{organ}': {e}")
        return []


async def _get_organ_synonyms_async(organ: str) -> list[str]:
    """Get organ synonyms: cache → static dict → UBERON API → cache write.

    Args:
        organ: Organ name (lowercase, e.g., "breast")

    Returns:
        List of medical synonyms for the organ
    """
    organ_lower = organ.lower()

    # Cache hit
    with _ORGAN_SYNONYM_CACHE_LOCK:
        if organ_lower in _ORGAN_SYNONYM_CACHE:
            return list(_ORGAN_SYNONYM_CACHE[organ_lower])

    # Start with static dict terms
    static_terms = list(_ORGAN_TO_MEDICAL.get(organ_lower, []))

    # Enrich with UBERON API
    try:
        uberon_synonyms = await _resolve_uberon_organ_synonyms(organ_lower)
        for syn in uberon_synonyms:
            if syn not in static_terms:
                static_terms.append(syn)
    except Exception:
        pass  # Static terms are sufficient

    # Cache write (including empty lists to avoid repeated UBERON timeouts)
    with _ORGAN_SYNONYM_CACHE_LOCK:
        _ORGAN_SYNONYM_CACHE[organ_lower] = static_terms

    return static_terms


def _get_organ_synonyms(organ: str) -> list[str]:
    """Get organ synonyms (sync wrapper with cache fast path).

    Args:
        organ: Organ name (e.g., "breast")

    Returns:
        List of medical synonyms for the organ
    """
    organ_lower = organ.lower()

    # Cache fast path
    with _ORGAN_SYNONYM_CACHE_LOCK:
        if organ_lower in _ORGAN_SYNONYM_CACHE:
            return list(_ORGAN_SYNONYM_CACHE[organ_lower])

    # Try async enrichment
    try:
        return run_async(_get_organ_synonyms_async(organ_lower), timeout=15)
    except Exception:
        # Fallback to static dict only
        return list(_ORGAN_TO_MEDICAL.get(organ_lower, []))


def _extract_organ_tokens(disease_normalized: str) -> list[str]:
    """Extract known organ tokens from a normalized disease string.

    Only matches against _ORGAN_TO_MEDICAL keys to avoid false positives
    (e.g., won't match "iris" as an organ).

    Args:
        disease_normalized: Lowercase, normalized disease string

    Returns:
        List of organ tokens found in the string
    """
    return [organ for organ in _ORGAN_TO_MEDICAL
            if re.search(rf'\b{re.escape(organ)}\b', disease_normalized)]


# Bidirectional abbreviation ↔ expansion mapping
_DISEASE_ABBREVIATIONS: dict[str, str] = {
    "aml": "acute myeloid leukemia",
    "cml": "chronic myeloid leukemia",
    "cll": "chronic lymphocytic leukemia",
    "all": "acute lymphoblastic leukemia",
    "dlbcl": "diffuse large b cell lymphoma",
    "nsclc": "non small cell lung cancer",
    "sclc": "small cell lung cancer",
    "hcc": "hepatocellular carcinoma",
    "rcc": "renal cell carcinoma",
    "gbm": "glioblastoma multiforme",
    "ipf": "idiopathic pulmonary fibrosis",
    "copd": "chronic obstructive pulmonary disease",
    "ibd": "inflammatory bowel disease",
    "sle": "systemic lupus erythematosus",
    "ra": "rheumatoid arthritis",
    "ms": "multiple sclerosis",
    "ad": "alzheimer disease",
    "pd": "parkinson disease",
    "t1d": "type 1 diabetes",
    "t2d": "type 2 diabetes",
    "tnbc": "triple negative breast cancer",
    "crc": "colorectal cancer",
    "uc": "ulcerative colitis",
    "nash": "non alcoholic steatohepatitis",
    "nafld": "non alcoholic fatty liver disease",
}
# Build reverse mapping: expansion → abbreviation
_DISEASE_EXPANSION_TO_ABBREV: dict[str, str] = {v: k for k, v in _DISEASE_ABBREVIATIONS.items()}

_NEURO_ABBREVS: dict[str, str] = {"alzheimer": "ad", "parkinson": "pd", "huntington": "hd"}

# Safe-mode generic terms that are too broad to use as standalone disease filters.
_DISEASE_GENERIC_EXACT_TERMS: set[str] = {
    "disease",
    "disorder",
    "syndrome",
    "cancer",
    "tumor",
    "tumour",
    "neoplasm",
    "neoplasms",
    "malignancy",
    "malignant",
    "carcinoma",
    "acute",
    "chronic",
    "progressive",
    "advanced",
    "metastatic",
    "invasive",
}

# Generic modifier tokens (used for "all tokens are generic" pruning).
_DISEASE_GENERIC_TOKENS: set[str] = {
    "disease",
    "disorder",
    "syndrome",
    "cancer",
    "tumor",
    "tumour",
    "neoplasm",
    "neoplasms",
    "malignancy",
    "malignant",
    "carcinoma",
    "acute",
    "chronic",
    "progressive",
    "advanced",
    "metastatic",
    "invasive",
    "primary",
    "secondary",
    "idiopathic",
}


def _is_anchor_candidate(token: str) -> bool:
    """Return whether token can act as a disease anchor in safe mode."""
    if not token:
        return False
    # Keep known abbreviations even when short (e.g., AML, UC, AD, PD).
    if token in _DISEASE_ABBREVIATIONS:
        return True
    # Drop generic tokens and very short fragments.
    if token in _DISEASE_GENERIC_TOKENS:
        return False
    return len(token) >= 3


def _build_disease_anchor_tokens(disease: str) -> set[str]:
    """Build disease anchor tokens for safe-mode filtering.

    Anchors represent disease-specific tokens (e.g., "breast", "mammary",
    "myeloid") used to prevent broad terms (e.g., "malignant") from matching
    unrelated papers.
    """
    normalized = _normalize_for_filter(disease)
    if not normalized:
        return set()

    anchors: set[str] = set()
    disease_tokens = [t for t in normalized.split() if t]

    # Base anchors from disease text.
    for token in disease_tokens:
        if _is_anchor_candidate(token):
            anchors.add(token)

    # If disease string is an abbreviation, add anchors from its expansion.
    if normalized in _DISEASE_ABBREVIATIONS:
        expansion = _DISEASE_ABBREVIATIONS[normalized]
        for token in _normalize_for_filter(expansion).split():
            if _is_anchor_candidate(token):
                anchors.add(token)
        anchors.add(normalized)

    # If disease string is a known expansion, include abbreviation anchor.
    if normalized in _DISEASE_EXPANSION_TO_ABBREV:
        anchors.add(_DISEASE_EXPANSION_TO_ABBREV[normalized])

    # Add organ alias anchors in both directions (e.g., breast <-> mammary).
    expanded_anchors = set(anchors)
    for anchor in list(anchors):
        if anchor in _ORGAN_TO_MEDICAL:
            for alias in _ORGAN_TO_MEDICAL[anchor]:
                for token in _normalize_for_filter(alias).split():
                    if _is_anchor_candidate(token):
                        expanded_anchors.add(token)
        for organ, aliases in _ORGAN_TO_MEDICAL.items():
            if anchor in aliases and _is_anchor_candidate(organ):
                expanded_anchors.add(organ)

    return expanded_anchors


def _sanitize_disease_match_terms(terms: list[str], disease: str) -> list[str]:
    """Apply safe-mode sanitization to disease terms.

    Rules:
    1) Remove exact generic terms (e.g., "malignant", "disease").
    2) Remove terms where all tokens are generic modifiers.
    3) Require overlap with disease anchor tokens (unless exact disease term).
    """
    normalized_disease = _normalize_for_filter(disease)
    if not normalized_disease:
        return []

    anchors = _build_disease_anchor_tokens(disease)
    unique_terms: list[str] = []

    for term in terms:
        term_norm = _normalize_for_filter(term)
        if not term_norm:
            continue

        # Always keep the canonical input disease string.
        if term_norm == normalized_disease:
            if term_norm not in unique_terms:
                unique_terms.append(term_norm)
            continue

        if term_norm in _DISEASE_GENERIC_EXACT_TERMS:
            continue

        tokens = [t for t in term_norm.split() if t]
        if not tokens:
            continue

        # Drop terms composed only of generic modifiers.
        if all(t in _DISEASE_GENERIC_TOKENS for t in tokens):
            continue

        # Safe mode: require at least one disease anchor token.
        if anchors and not any(t in anchors for t in tokens):
            continue

        if term_norm not in unique_terms:
            unique_terms.append(term_norm)

    # Never return an empty list; keep canonical term as minimum.
    if not unique_terms:
        return [normalized_disease]

    return unique_terms


def _paper_has_anchor_match(
    normalized_text: str, original_text: str, anchors: set[str]
) -> bool:
    """Return True if paper text contains at least one disease anchor token."""
    if not anchors:
        return True

    for anchor in anchors:
        if len(anchor) <= 4:
            if re.search(rf"\b{re.escape(anchor.upper())}\b", original_text):
                return True
        elif anchor in normalized_text:
            return True
    return False


def _generate_disease_match_terms(disease: str) -> list[str]:
    """Generate disease-matching terms for stricter post-filtering.

    Universal disease synonym generation supporting:
    - Cancer variants (carcinoma, neoplasm, tumor/tumour, malignancy)
    - Organ aliases (common → medical term, unidirectional)
    - Leukemia/leukaemia US/UK spelling
    - Neurodegenerative possessive variants (alzheimer's/alzheimers/alzheimer)
    - Fibrosis ↔ fibrotic
    - 25+ abbreviation expansions (bidirectional)
    - Inflammatory/autoimmune disease patterns
    """
    normalized = _normalize_for_filter(disease)
    if not normalized:
        return []

    terms: list[str] = [normalized]

    # --- 3a. Cancer variants (backward-compatible) ---
    if "cancer" in normalized:
        base = normalized.replace(" cancer", "").strip()
        if base:
            for suffix in ["carcinoma", "neoplasm", "neoplasms", "tumor", "tumour", "malignancy"]:
                terms.append(f"{base} {suffix}")
            terms.append(base)
    if "carcinoma" in normalized:
        base = normalized.replace(" carcinoma", "").replace("carcinoma", "").strip()
        if base:
            for suffix in ["cancer", "neoplasm", "tumor", "tumour"]:
                terms.append(f"{base} {suffix}")
    if "neoplasm" in normalized or "neoplasms" in normalized:
        base = normalized.replace(" neoplasms", "").replace(" neoplasm", "").strip()
        if base:
            terms.append(f"{base} cancer")
            terms.append(f"{base} tumor")
    if "tumor" in normalized or "tumour" in normalized:
        base = normalized.replace(" tumor", "").replace(" tumour", "").strip()
        if base:
            terms.append(f"{base} cancer")
            # US/UK tumor ↔ tumour
            if "tumor" in normalized:
                terms.append(normalized.replace("tumor", "tumour"))
            elif "tumour" in normalized:
                terms.append(normalized.replace("tumour", "tumor"))

    # --- 3b. Organ aliases (cross-product with ALL accumulated terms) ---
    terms_snapshot = list(terms)  # Snapshot to avoid mutation during iteration
    organ_expanded: list[str] = []
    for organ, medical_terms in _ORGAN_TO_MEDICAL.items():
        # Forward: common → medical on ALL terms
        for existing_term in terms_snapshot:
            if re.search(rf'\b{re.escape(organ)}\b', existing_term):
                for med in medical_terms:
                    new_term = existing_term.replace(organ, med)
                    if new_term not in terms and new_term not in organ_expanded:
                        organ_expanded.append(new_term)
        # Reverse: medical → common on ALL terms
        for med in medical_terms:
            for existing_term in terms_snapshot:
                if re.search(rf'\b{re.escape(med)}\b', existing_term):
                    new_term = existing_term.replace(med, organ)
                    if new_term not in terms and new_term not in organ_expanded:
                        organ_expanded.append(new_term)
        if len(terms) + len(organ_expanded) > 200:  # Size guard
            break
    terms.extend(organ_expanded)

    # --- 3c. Leukemia/leukaemia US/UK ---
    if "leukemia" in normalized:
        terms.append(normalized.replace("leukemia", "leukaemia"))
    elif "leukaemia" in normalized:
        terms.append(normalized.replace("leukaemia", "leukemia"))

    # --- 3d. Neurodegenerative possessive variants ---
    # Handle: alzheimer's → alzheimer, alzheimers; parkinson's → parkinson, parkinsons
    for neuro, abbrev in _NEURO_ABBREVS.items():
        if neuro in normalized:
            terms.append(neuro)
            terms.append(f"{neuro}s")
            terms.append(f"{neuro} disease")
            terms.append(f"{neuro}s disease")
            terms.append(abbrev)

    # --- 3e. Fibrosis ↔ fibrotic ---
    if "fibrosis" in normalized:
        terms.append(normalized.replace("fibrosis", "fibrotic"))
    elif "fibrotic" in normalized:
        terms.append(normalized.replace("fibrotic", "fibrosis"))

    # --- 3f. Abbreviation expansions (bidirectional) ---
    # Also try without possessive 's' (e.g., "alzheimer s disease" → "alzheimer disease")
    normalized_no_poss = re.sub(r"\b(\w+)\s+s\b", r"\1", normalized)
    for lookup in {normalized, normalized_no_poss}:
        if lookup in _DISEASE_ABBREVIATIONS:
            expansion = _DISEASE_ABBREVIATIONS[lookup]
            terms.append(expansion)
            if "leukemia" in expansion:
                terms.append(expansion.replace("leukemia", "leukaemia"))
        if lookup in _DISEASE_EXPANSION_TO_ABBREV:
            terms.append(_DISEASE_EXPANSION_TO_ABBREV[lookup])

    # --- 3g. Inflammatory/autoimmune patterns ---
    if "crohn" in normalized:
        terms.extend(["crohn disease", "crohns disease", "crohn s disease"])
    if "colitis" in normalized and "ulcerative" in normalized:
        terms.extend(["uc", "ulcerative colitis"])
    if "lupus" in normalized:
        terms.extend(["sle", "systemic lupus erythematosus", "lupus"])
    if "rheumatoid" in normalized:
        terms.extend(["ra", "rheumatoid arthritis"])

    # --- Lymphoma variants ---
    if "lymphoma" in normalized:
        base = normalized.replace(" lymphoma", "").strip()
        if base:
            terms.append(base)

    # Remove duplicates and keep deterministic order
    unique_terms: list[str] = []
    for term in terms:
        cleaned = term.strip()
        if cleaned and cleaned not in unique_terms:
            unique_terms.append(cleaned)
    return unique_terms


async def _resolve_mondo_id(disease_name: str) -> str | None:
    """Resolve a disease name to a MONDO ontology ID via EBI OLS4 API.

    Args:
        disease_name: Human-readable disease name (e.g., "breast cancer")

    Returns:
        MONDO ID string (e.g., "MONDO:0007254") or None if not found.
        Network errors return None without caching (allows retry).
    """
    encoded = urllib.parse.quote(disease_name)
    url = f"https://www.ebi.ac.uk/ols4/api/search?q={encoded}&ontology=mondo&rows=5"

    try:
        def _fetch():
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))

        data = await asyncio.to_thread(_fetch)

        docs = data.get("response", {}).get("docs", [])
        for doc in docs:
            obo_id = doc.get("obo_id", "")
            if obo_id.startswith("MONDO:"):
                logger.debug(f"Resolved '{disease_name}' → {obo_id}")
                return obo_id

    except Exception as e:
        logger.debug(f"EBI OLS4 lookup failed for '{disease_name}': {e}")

    return None


def _parse_disease_synonyms(result: Any) -> list[str]:
    """Parse disease synonyms from BioMCP disease_getter result.

    BioMCP returns results in markdown format similar to gene_getter:
    [{'type': 'text', 'text': '# Disease\\nName: ...\\nSynonym: term1, term2\\n...'}]

    Args:
        result: Raw result from disease_getter

    Returns:
        List of synonym strings
    """
    synonyms = []

    if result is None:
        return synonyms

    if isinstance(result, list):
        for item in result:
            if isinstance(item, dict) and "text" in item:
                text = item["text"]

                # Parse "Synonym:" lines (BioMCP markdown format)
                for match in re.finditer(r"Synonym[s]?:\s*([^\n]+)", text, re.IGNORECASE):
                    line = match.group(1).strip()
                    for syn in line.split(","):
                        syn_clean = syn.strip().strip('"').strip("'")
                        if syn_clean and syn_clean not in synonyms:
                            synonyms.append(syn_clean)

                # Also extract Name field
                name_match = re.search(r"Name:\s*([^\n]+)", text)
                if name_match:
                    name = name_match.group(1).strip()
                    if name and name not in synonyms:
                        synonyms.append(name)

                # JSON fallback
                if not synonyms:
                    try:
                        data = json.loads(text)
                        if isinstance(data, list) and len(data) > 0:
                            data = data[0]
                        if isinstance(data, dict):
                            for field in ["synonym", "synonyms", "aliases"]:
                                if field in data:
                                    val = data[field]
                                    if isinstance(val, list):
                                        synonyms.extend([str(s) for s in val])
                                    elif isinstance(val, str):
                                        synonyms.extend(val.split(","))
                    except json.JSONDecodeError:
                        pass
                break

    return list(set(synonyms))


async def _fetch_disease_synonyms_from_biomcp(
    disease_id_or_name: str,
    biomcp_url: str = DEFAULT_BIOMCP_URL,
) -> list[str]:
    """Fetch disease synonyms from BioMCP disease_getter (MyDisease.info).

    Args:
        disease_id_or_name: Disease name or MONDO ID (e.g., "MONDO:0007254")
        biomcp_url: BioMCP server URL

    Returns:
        List of synonym strings (empty list if fetch fails)
    """
    try:
        tools = await get_biomcp_tools(biomcp_url)
        disease_getter = find_tool_by_name(tools, "disease_getter")

        if disease_getter is None:
            logger.debug("disease_getter tool not found, skipping synonym fetch")
            return []

        result = await disease_getter.ainvoke({"disease_id_or_name": disease_id_or_name})
        synonyms = _parse_disease_synonyms(result)
        logger.debug(f"Fetched synonyms for {disease_id_or_name}: {synonyms[:5]}...")
        return synonyms

    except Exception as e:
        logger.debug(f"Failed to fetch disease synonyms for {disease_id_or_name}: {e}")
        invalidate_client(f"biomcp_{biomcp_url}")
        return []


async def _get_disease_synonyms_async(
    disease: str,
    biomcp_url: str = DEFAULT_BIOMCP_URL,
) -> list[str]:
    """Get comprehensive disease match terms: rule-based + BioMCP API.

    Orchestrates the hybrid approach:
    1. Check cache (fast path)
    2. Generate rule-based terms via _generate_disease_match_terms()
    3. Try EBI OLS4 → MONDO ID → BioMCP disease_getter chain
    4. Merge and cache results

    Network errors do NOT cache (allows retry on next call).

    Args:
        disease: Disease name string
        biomcp_url: BioMCP server URL

    Returns:
        Deduplicated list of disease match terms
    """
    normalized = _normalize_for_filter(disease)
    if not normalized:
        return []

    # Cache hit → immediate return
    with _DISEASE_SYNONYM_CACHE_LOCK:
        if normalized in _DISEASE_SYNONYM_CACHE:
            return list(_DISEASE_SYNONYM_CACHE[normalized])

    # Rule-based terms (always available)
    terms = _generate_disease_match_terms(disease)

    # Try BioMCP API enrichment
    api_succeeded = False
    try:
        # Step 1: Try disease name directly with disease_getter
        api_synonyms = await _fetch_disease_synonyms_from_biomcp(disease, biomcp_url)

        # Step 2: If few results, try resolving MONDO ID first
        if len(api_synonyms) < 3:
            mondo_id = await _resolve_mondo_id(disease)
            if mondo_id:
                mondo_synonyms = await _fetch_disease_synonyms_from_biomcp(mondo_id, biomcp_url)
                api_synonyms.extend(mondo_synonyms)

        # Merge API synonyms into terms
        for syn in api_synonyms:
            syn_normalized = _normalize_for_filter(syn)
            if syn_normalized and syn_normalized not in terms:
                terms.append(syn_normalized)

        api_succeeded = True

    except Exception as e:
        logger.debug(f"BioMCP disease synonym enrichment failed for '{disease}': {e}")

    # UBERON organ synonym enrichment (cross-product with accumulated terms)
    organ_tokens = _extract_organ_tokens(normalized)
    for organ_token in organ_tokens:
        try:
            uberon_synonyms = await _get_organ_synonyms_async(organ_token)
            for existing_term in list(terms):  # Snapshot
                if organ_token in existing_term:
                    for syn in uberon_synonyms:
                        replacement = existing_term.replace(organ_token, syn)
                        if replacement not in terms:
                            terms.append(replacement)
            if len(terms) > 300:
                break
        except Exception:
            pass  # Static dict terms already applied in rule-based step

    # Safe-mode sanitization: remove broad terms and keep anchor-bound terms only.
    terms = _sanitize_disease_match_terms(terms, disease)

    # Cache result only if API succeeded or we have rule-based terms
    if api_succeeded or len(terms) > 1:
        with _DISEASE_SYNONYM_CACHE_LOCK:
            _DISEASE_SYNONYM_CACHE[normalized] = terms

    return terms


def get_disease_match_terms(disease: str) -> list[str]:
    """Get disease match terms (sync wrapper with cache fast path).

    If the cache is pre-warmed (via _get_disease_synonyms_async in
    _search_with_biomcp), this is a pure dict lookup with no event loop blocking.

    Falls back to rule-based terms only if async call fails.

    Args:
        disease: Disease name string

    Returns:
        List of disease match terms
    """
    normalized = _normalize_for_filter(disease)
    if not normalized:
        return []

    # Cache fast path (dict lookup, no thread)
    with _DISEASE_SYNONYM_CACHE_LOCK:
        if normalized in _DISEASE_SYNONYM_CACHE:
            return _sanitize_disease_match_terms(
                list(_DISEASE_SYNONYM_CACHE[normalized]),
                disease,
            )

    # Try async enrichment
    try:
        return run_async(_get_disease_synonyms_async(disease), timeout=30)
    except Exception:
        # Graceful degradation: rule-based only
        return _sanitize_disease_match_terms(
            _generate_disease_match_terms(disease),
            disease,
        )


def _paper_matches_disease_context(paper: dict[str, Any], diseases: list[str]) -> bool:
    """Return whether paper title/abstract matches at least one target disease context.

    Uses get_disease_match_terms() which returns cached results if pre-warmed
    by _search_with_biomcp(), otherwise falls back to rule-based terms.
    """
    text = _normalize_for_filter(paper.get("title", "") + " " + paper.get("abstract", ""))
    if not text:
        return False

    original_text = paper.get("title", "") + " " + paper.get("abstract", "")

    for disease in diseases:
        anchors = _build_disease_anchor_tokens(disease)
        if not _paper_has_anchor_match(text, original_text, anchors):
            continue

        for term in get_disease_match_terms(disease):
            if term:
                if len(term) <= 4:
                    # Case-sensitive uppercase word boundary for short terms —
                    # disease abbreviations (ALL, AML, PD, AD) are uppercase in papers.
                    # Prevents false positives from common English words ("all", "ms").
                    if re.search(rf'\b{re.escape(term.upper())}\b', original_text):
                        return True
                elif term in text:
                    return True

    return False


def _normalize_rerank_mode(mode: str | None) -> str:
    """Normalize rerank mode string."""
    if not mode:
        return "off"
    mode_norm = str(mode).strip().lower()
    if mode_norm in {"llm", "off"}:
        return mode_norm
    return "off"


def _merge_rerank_stats(target: dict[str, int], delta: dict[str, int]) -> None:
    """Merge rerank counters into mutable target dict."""
    for key in ("applied_count", "promoted_count", "dropped_count"):
        target[key] = int(target.get(key, 0)) + int(delta.get(key, 0))


def _strip_code_fence(text: str) -> str:
    """Strip optional markdown code fences from LLM text."""
    cleaned = (text or "").strip()
    if "```json" in cleaned:
        start = cleaned.find("```json") + 7
        end = cleaned.find("```", start)
        if end > start:
            cleaned = cleaned[start:end].strip()
    elif "```" in cleaned:
        start = cleaned.find("```") + 3
        end = cleaned.find("```", start)
        if end > start:
            cleaned = cleaned[start:end].strip()
    return cleaned


def _contains_canonical_disease_phrase(paper: dict[str, Any], diseases: list[str]) -> bool:
    """Return True when paper text contains explicit canonical disease phrase."""
    text = _normalize_for_filter(
        (paper.get("title", "") or "") + " " + (paper.get("abstract", "") or "")
    )
    if not text:
        return False
    canonical_terms = [
        _normalize_for_filter(d)
        for d in diseases
        if isinstance(d, str) and _normalize_for_filter(d)
    ]
    return any(term in text for term in canonical_terms)


def _select_rerank_candidates(
    kept_articles: list[dict[str, Any]],
    removed_articles: list[dict[str, Any]],
    diseases: list[str],
    top_n: int,
) -> list[dict[str, Any]]:
    """Select boundary candidates for LLM rerank.

    Precision-first selection:
    - kept without canonical phrase -> possible demotion candidate
    - removed with canonical phrase -> possible promotion candidate
    """
    if top_n <= 0:
        return []

    candidates: list[dict[str, Any]] = []

    for paper in kept_articles:
        pmid = str(paper.get("pmid", "")).strip()
        if not pmid:
            continue
        if not _contains_canonical_disease_phrase(paper, diseases):
            candidates.append(
                {"source": "kept", "priority": 0, "pmid": pmid, "paper": paper}
            )

    for paper in removed_articles:
        pmid = str(paper.get("pmid", "")).strip()
        if not pmid:
            continue
        if _contains_canonical_disease_phrase(paper, diseases):
            candidates.append(
                {"source": "removed", "priority": 1, "pmid": pmid, "paper": paper}
            )

    candidates.sort(key=lambda x: (x["priority"], x["pmid"]))
    return candidates[:top_n]


def _parse_rerank_judgments(response_text: str) -> dict[tuple[str, str], tuple[str, float]]:
    """Parse LLM rerank JSON response.

    Returns:
        Mapping (source, pmid) -> (verdict, confidence)
    """
    text = _strip_code_fence(response_text)
    if "[" in text and "]" in text:
        start = text.find("[")
        end = text.rfind("]") + 1
        text = text[start:end]

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}

    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        return {}

    verdicts: dict[tuple[str, str], tuple[str, float]] = {}
    for item in parsed:
        if not isinstance(item, dict):
            continue
        pmid = str(item.get("pmid", "")).strip()
        source = str(item.get("source", "")).strip().lower()
        verdict = str(item.get("verdict", "")).strip().lower()

        conf_raw = item.get("confidence", 0.0)
        try:
            confidence = float(conf_raw)
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        if not pmid or source not in {"kept", "removed"}:
            continue
        if verdict not in {"relevant", "uncertain", "irrelevant"}:
            continue
        verdicts[(source, pmid)] = (verdict, confidence)

    return verdicts


def _build_rerank_prompt(diseases: list[str], candidates: list[dict[str, Any]]) -> str:
    """Build precision-first rerank prompt for boundary papers."""
    compact_candidates = []
    for c in candidates:
        paper = c["paper"]
        compact_candidates.append(
            {
                "source": c["source"],
                "pmid": c["pmid"],
                "title": (paper.get("title", "") or "")[:240],
                "abstract": (paper.get("abstract", "") or "")[:800],
            }
        )

    return (
        "You are a strict biomedical relevance judge.\n"
        "Task: determine whether each paper is relevant to the target disease context.\n\n"
        f"Target diseases: {diseases}\n"
        "Policy (precision-first):\n"
        "- relevant: clearly about the target disease context\n"
        "- uncertain: ambiguous or indirect\n"
        "- irrelevant: not about target disease context\n"
        "- Be conservative. Prefer 'irrelevant' over false positives.\n\n"
        "Return ONLY JSON array with objects:\n"
        '[{"source":"kept|removed","pmid":"string","verdict":"relevant|uncertain|irrelevant","confidence":0.0-1.0}]\n\n'
        f"Candidates:\n{json.dumps(compact_candidates, ensure_ascii=False)}"
    )


async def _rerank_disease_relevance_with_llm(
    kept_articles: list[dict[str, Any]],
    removed_articles: list[dict[str, Any]],
    diseases: list[str],
    top_n: int = 12,
    min_confidence: float = 0.70,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Optional second-stage reranking for precision-first disease relevance."""
    stats = {"applied_count": 0, "promoted_count": 0, "dropped_count": 0}
    candidates = _select_rerank_candidates(
        kept_articles=kept_articles,
        removed_articles=removed_articles,
        diseases=diseases,
        top_n=top_n,
    )
    if not candidates:
        return kept_articles, stats

    try:
        llm = create_llm()
        prompt = _build_rerank_prompt(diseases, candidates)
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        response_text = response.content if hasattr(response, "content") else str(response)
        judgments = _parse_rerank_judgments(response_text)
    except Exception as e:
        logger.debug(f"LLM rerank skipped due to error: {e}")
        return kept_articles, stats

    if not judgments:
        return kept_articles, stats

    kept_map = {str(p.get("pmid", "")): p for p in kept_articles if str(p.get("pmid", ""))}
    removed_map = {str(p.get("pmid", "")): p for p in removed_articles if str(p.get("pmid", ""))}

    drop_pmids: set[str] = set()
    promote_pmids: set[str] = set()

    for (source, pmid), (verdict, confidence) in judgments.items():
        if confidence < min_confidence:
            continue
        stats["applied_count"] += 1

        if source == "kept" and pmid in kept_map:
            if verdict in {"irrelevant", "uncertain"}:
                drop_pmids.add(pmid)
                stats["dropped_count"] += 1
        elif source == "removed" and pmid in removed_map:
            if verdict == "relevant":
                promote_pmids.add(pmid)
                stats["promoted_count"] += 1

    reranked = [p for p in kept_articles if str(p.get("pmid", "")) not in drop_pmids]
    seen = {str(p.get("pmid", "")) for p in reranked if str(p.get("pmid", ""))}
    for pmid in sorted(promote_pmids):
        if pmid in removed_map and pmid not in seen:
            reranked.append(removed_map[pmid])
            seen.add(pmid)

    return reranked, stats


MAX_ABSTRACT_LENGTH = 1500  # ~200 words, sufficient for coverage matching


def _parse_article(pmid: str, result: Any) -> dict:
    """Parse article details from BioMCP article_getter result.

    BioMCP returns results in format:
    [{'type': 'text', 'text': '[{"pmid": 12345, "title": "...", "abstract": "..."}]'}]

    The 'text' field contains JSON with article details.
    Abstracts are truncated to MAX_ABSTRACT_LENGTH characters to prevent
    context window overflow when many papers are loaded.
    """
    article = {
        "pmid": pmid,
        "title": f"Article {pmid}",
        "abstract": "",
        "journal_quality": _SJR_DEFAULT_SCORE,
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
                            abstract = article_data.get("abstract", "")
                            article["abstract"] = abstract[:MAX_ABSTRACT_LENGTH] if len(abstract) > MAX_ABSTRACT_LENGTH else abstract
                            # Also capture additional fields if available
                            if "authors" in article_data:
                                article["authors"] = article_data["authors"]
                            if "journal" in article_data:
                                article["journal"] = article_data["journal"]
                                article["journal_quality"] = _get_journal_quality(article_data["journal"])
                            if "date" in article_data:
                                article["date"] = article_data["date"]
                    elif isinstance(data, dict):
                        article["title"] = data.get("title", article["title"])
                        abstract = data.get("abstract", "")
                        article["abstract"] = abstract[:MAX_ABSTRACT_LENGTH] if len(abstract) > MAX_ABSTRACT_LENGTH else abstract
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
                abstract = data.get("abstract", "")
                article["abstract"] = abstract[:MAX_ABSTRACT_LENGTH] if len(abstract) > MAX_ABSTRACT_LENGTH else abstract
            elif isinstance(data, list) and len(data) > 0:
                article_data = data[0]
                if isinstance(article_data, dict):
                    article["title"] = article_data.get("title", article["title"])
                    abstract = article_data.get("abstract", "")
                    article["abstract"] = abstract[:MAX_ABSTRACT_LENGTH] if len(abstract) > MAX_ABSTRACT_LENGTH else abstract
        except json.JSONDecodeError:
            if len(result) > 100:
                article["abstract"] = result[:MAX_ABSTRACT_LENGTH] if len(result) > MAX_ABSTRACT_LENGTH else result
        return article

    if isinstance(result, dict):
        article["title"] = result.get("title", article["title"])
        abstract = result.get("abstract", "")
        article["abstract"] = abstract[:MAX_ABSTRACT_LENGTH] if len(abstract) > MAX_ABSTRACT_LENGTH else abstract
        return article

    return article


@tool
def search_literature(
    genes: list[str],
    disease: str,
    keywords: list[str],
    max_results: int = 15,
    rerank_mode: str = "off",
    rerank_top_n: int = 12,
    rerank_min_confidence: float = 0.70,
) -> list[dict]:
    """Search PubMed via BioMCP for supporting literature.

    This tool searches PubMed for articles related to specific genes,
    diseases, and biological keywords relevant to CCI analysis.

    Args:
        genes: List of gene names to search (e.g., ["CDH1", "TGFB1"])
        disease: Disease context (e.g., "breast cancer")
        keywords: Additional keywords (e.g., ["EMT", "spatial transcriptomics"])
        max_results: Maximum number of results to return (default 15)
        rerank_mode: "off" or "llm" for optional second-stage rerank
        rerank_top_n: Max boundary candidates reranked by LLM
        rerank_min_confidence: Minimum confidence threshold for rerank decision

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
                enforce_disease_match=bool(disease and isinstance(disease, str) and disease.strip()),
                rerank_mode=rerank_mode,
                rerank_top_n=rerank_top_n,
                rerank_min_confidence=rerank_min_confidence,
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
    rerank_mode: str = "off",
    rerank_top_n: int = 12,
    rerank_min_confidence: float = 0.70,
) -> list[dict]:
    """Async version of search_literature.

    Use this function directly in async contexts for better performance.

    Args:
        genes: List of gene names to search
        disease: Disease context
        keywords: Additional keywords
        max_results: Maximum results to return
        biomcp_url: BioMCP server URL
        rerank_mode: "off" or "llm" for optional second-stage rerank
        rerank_top_n: Max boundary candidates reranked by LLM
        rerank_min_confidence: Minimum confidence threshold for rerank decision

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
        enforce_disease_match=bool(disease and isinstance(disease, str) and disease.strip()),
        biomcp_url=biomcp_url,
        rerank_mode=rerank_mode,
        rerank_top_n=rerank_top_n,
        rerank_min_confidence=rerank_min_confidence,
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
    enforce_disease_match: bool = True,
) -> dict:
    """Internal fixed-strategy search function (used as fallback).

    Sync wrapper that delegates to _execute_fixed_strategy_search_async.

    Args:
        genes: List of gene names
        pathways: List of pathways
        celltypes: List of cell types
        disease: Disease context
        max_results: Maximum papers to return
        enforce_disease_match: Whether to post-filter papers by disease context

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
            enforce_disease_match=enforce_disease_match,
        ),
        timeout=120,
    )


async def _execute_fixed_strategy_search_async(
    genes: list[str],
    pathways: list[str],
    celltypes: list[str],
    disease: str,
    max_results: int = 20,
    enforce_disease_match: bool = True,
    biomcp_url: str = DEFAULT_BIOMCP_URL,
    rerank_mode: str = "off",
    rerank_top_n: int = 12,
    rerank_min_confidence: float = 0.70,
    rerank_stats: dict[str, int] | None = None,
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
        enforce_disease_match: Whether to post-filter papers by disease context
        biomcp_url: BioMCP server URL
        rerank_mode: "off" or "llm" for optional second-stage rerank
        rerank_top_n: Max boundary candidates reranked by LLM
        rerank_min_confidence: Minimum confidence threshold for rerank decision
        rerank_stats: Optional mutable counter dict for rerank telemetry aggregation

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
                enforce_disease_match=enforce_disease_match,
                rerank_mode=rerank_mode,
                rerank_top_n=rerank_top_n,
                rerank_min_confidence=rerank_min_confidence,
                rerank_stats=rerank_stats,
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

    await _ensure_sjr_cache_loaded()
    papers.sort(key=lambda p: p.get("journal_quality", _SJR_DEFAULT_SCORE), reverse=True)
    papers = papers[:max_results]

    # Use unified coverage calculation (same as search_literature_dynamic)
    coverage = _calculate_coverage(papers, genes, pathways, celltypes)

    rerank_telemetry = rerank_stats or {
        "applied_count": 0,
        "promoted_count": 0,
        "dropped_count": 0,
    }
    filter_stage = (
        "hybrid_2stage"
        if _normalize_rerank_mode(rerank_mode) == "llm"
        else "deterministic_only"
    )

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
        "filter_stage": filter_stage,
        "rerank_applied_count": int(rerank_telemetry.get("applied_count", 0)),
        "rerank_promoted_count": int(rerank_telemetry.get("promoted_count", 0)),
        "rerank_dropped_count": int(rerank_telemetry.get("dropped_count", 0)),
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
    max_results: int = 30,
    target_gene_coverage: float = 0.6,
    target_pathway_coverage: float = 0.5,
    max_iterations: int = 3,
    enforce_disease_match: bool = True,
    output_path: str = "",
    data_dir: str = "",
    rerank_mode: str = "off",
    rerank_top_n: int = 12,
    rerank_min_confidence: float = 0.70,
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
        max_results: Maximum number of papers to return (default 30)
        target_gene_coverage: Target gene coverage percentage (default 0.6 = 60%)
        target_pathway_coverage: Target pathway coverage percentage (default 0.5 = 50%)
        max_iterations: Maximum search iterations (default 3)
        enforce_disease_match: Whether to post-filter papers by disease context
        output_path: If provided (e.g., "papers.json"), saves complete results
            to data_dir/output_path. Returns compact summary.
        data_dir: Directory for saving output files. SEARCHER should read this from
            /data_path.txt (written by PLANNER). Falls back to contextvars if empty.
        rerank_mode: "off" or "llm" for optional second-stage rerank
        rerank_top_n: Max boundary candidates reranked by LLM
        rerank_min_confidence: Minimum confidence threshold for rerank decision

    Returns:
        If output_path is empty: Dictionary with papers, generated_queries, coverage,
        think_success, iterations, coverage_history.
        If output_path is provided: Compact summary with saved_to, total_papers,
        coverage, paper_titles (first 10), and a message.
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
            enforce_disease_match=enforce_disease_match,
            output_path=output_path,
            data_dir=data_dir,
            rerank_mode=rerank_mode,
            rerank_top_n=rerank_top_n,
            rerank_min_confidence=rerank_min_confidence,
        ),
        timeout=300,
    )


async def search_literature_dynamic_async(
    genes: list[str],
    pathways: list[str],
    celltypes: list[str],
    disease: str,
    max_results: int = 30,
    target_gene_coverage: float = 0.6,
    target_pathway_coverage: float = 0.5,
    max_iterations: int = 3,
    enforce_disease_match: bool = True,
    biomcp_url: str = DEFAULT_BIOMCP_URL,
    output_path: str = "",
    data_dir: str = "",
    rerank_mode: str = "off",
    rerank_top_n: int = 12,
    rerank_min_confidence: float = 0.70,
) -> dict:
    """Async version of search_literature_dynamic with ITERATIVE coverage improvement.

    Use this function directly in async contexts for better performance.

    Args:
        genes: List of gene names from analysis
        pathways: List of pathways identified
        celltypes: List of cell types in analysis
        disease: Disease context
        max_results: Maximum papers to return (default 30)
        target_gene_coverage: Target gene coverage percentage (default 0.6)
        target_pathway_coverage: Target pathway coverage percentage (default 0.5)
        max_iterations: Maximum search iterations (default 3)
        enforce_disease_match: Whether to post-filter papers by disease context
        biomcp_url: BioMCP server URL
        output_path: If provided, saves full results to file and returns compact summary
        data_dir: Explicit data directory for auto-save (priority over env var)
        rerank_mode: "off" or "llm" for optional second-stage rerank
        rerank_top_n: Max boundary candidates reranked by LLM
        rerank_min_confidence: Minimum confidence threshold for rerank decision

    Returns:
        If output_path is empty: full results dict.
        If output_path is provided: compact summary dict.
    """
    # Initialize tracking variables
    all_papers = []
    all_queries = []
    seen_pmids = set()
    coverage_history = []
    normalized_rerank_mode = _normalize_rerank_mode(rerank_mode)
    rerank_totals = {"applied_count": 0, "promoted_count": 0, "dropped_count": 0}

    # Keep output schema backward-compatible even though strategic think is skipped.
    think_success = True

    # Note: pre-fetch aliases removed - BioMCP article_searcher
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
                    enforce_disease_match=enforce_disease_match,
                    biomcp_url=biomcp_url,
                    rerank_mode=normalized_rerank_mode,
                    rerank_top_n=rerank_top_n,
                    rerank_min_confidence=rerank_min_confidence,
                    rerank_stats=rerank_totals,
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
                    enforce_disease_match=enforce_disease_match,
                    biomcp_url=biomcp_url,
                    rerank_mode=normalized_rerank_mode,
                    rerank_top_n=rerank_top_n,
                    rerank_min_confidence=rerank_min_confidence,
                    rerank_stats=rerank_totals,
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
                query_diseases = query.get("diseases")
                if not query_diseases and disease:
                    query_diseases = [disease]

                results = await _search_with_biomcp(
                    genes=query.get("genes"),
                    diseases=query_diseases,
                    keywords=query.get("keywords"),
                    page_size=gene_results_per_query,
                    biomcp_url=biomcp_url,
                    enforce_disease_match=enforce_disease_match,
                    rerank_mode=normalized_rerank_mode,
                    rerank_top_n=rerank_top_n,
                    rerank_min_confidence=rerank_min_confidence,
                    rerank_stats=rerank_totals,
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
                query_diseases = query.get("diseases")
                if not query_diseases and disease:
                    query_diseases = [disease]

                results = await _search_with_biomcp(
                    genes=query.get("genes"),
                    diseases=query_diseases,
                    keywords=query.get("keywords"),
                    page_size=pathway_results_per_query,
                    biomcp_url=biomcp_url,
                    enforce_disease_match=enforce_disease_match,
                    rerank_mode=normalized_rerank_mode,
                    rerank_top_n=rerank_top_n,
                    rerank_min_confidence=rerank_min_confidence,
                    rerank_stats=rerank_totals,
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

    # Sort by journal quality before truncating
    await _ensure_sjr_cache_loaded()
    all_papers.sort(key=lambda p: p.get("journal_quality", _SJR_DEFAULT_SCORE), reverse=True)

    # Final coverage calculation
    final_papers = all_papers[:max_results]
    final_coverage = _calculate_coverage(final_papers, genes, pathways, celltypes)

    coverage_history.append({
        "iteration": "final",
        "papers": len(final_papers),
        "gene_coverage": final_coverage.get("genes_coverage_pct", 0) / 100,
        "pathway_coverage": final_coverage.get("pathways_coverage_pct", 0) / 100,
    })

    # Post-search reflection guidance: determine if coverage is sufficient
    gene_pct = final_coverage.get("genes_coverage_pct", 0)
    pathway_pct = final_coverage.get("pathways_coverage_pct", 0)
    coverage_sufficient = (
        gene_pct >= target_gene_coverage * 100
        and pathway_pct >= target_pathway_coverage * 100
        and len(final_papers) >= 15
    )

    recommended_actions: list[str] = []
    if not coverage_sufficient:
        if gene_pct < target_gene_coverage * 100:
            missing = final_coverage.get("genes_missing", [])[:5]
            recommended_actions.append(
                f"Gene coverage {gene_pct:.0f}% < {target_gene_coverage*100:.0f}% target. "
                f"Missing: {missing}. Use search_literature for targeted follow-up."
            )
        if pathway_pct < target_pathway_coverage * 100:
            missing = final_coverage.get("pathways_missing", [])[:3]
            recommended_actions.append(
                f"Pathway coverage {pathway_pct:.0f}% < {target_pathway_coverage*100:.0f}% target. "
                f"Missing: {missing}. Search with 'signaling' + disease context."
            )
        if len(final_papers) < 15:
            recommended_actions.append(
                f"Only {len(final_papers)} papers found (target: 15+). Broaden disease context."
            )
        recommended_actions.append("Use think_tool to reflect on gaps before proceeding.")

    filter_stage = (
        "hybrid_2stage" if normalized_rerank_mode == "llm" else "deterministic_only"
    )

    full_result = {
        "papers": final_papers,
        "generated_queries": all_queries,
        "coverage": final_coverage,
        "search_method": "search_literature_dynamic",
        "think_success": think_success,
        "iterations": len(coverage_history) - 1,
        "coverage_history": coverage_history,
        "coverage_sufficient": coverage_sufficient,
        "recommended_actions": recommended_actions,
        "filter_stage": filter_stage,
        "rerank_applied_count": int(rerank_totals.get("applied_count", 0)),
        "rerank_promoted_count": int(rerank_totals.get("promoted_count", 0)),
        "rerank_dropped_count": int(rerank_totals.get("dropped_count", 0)),
    }

    # Auto-save: write full results to file, return compact summary to LLM
    if output_path:
        save_dir = data_dir or os.getenv("DEEP_INTERPRETER_DATA_DIR", "")
        if save_dir:
            save_dir = str(Path(save_dir).expanduser().resolve())
            real_path = os.path.join(save_dir, output_path)
            try:
                await asyncio.to_thread(_sync_save_json, save_dir, real_path, full_result)
                logger.info(
                    f"Auto-saved {len(final_papers)} papers to {real_path}"
                )
                return {
                    "saved_to": real_path,
                    "output_path": output_path,
                    "total_papers": len(final_papers),
                    "coverage": final_coverage,
                    "paper_titles": [
                        p.get("title", "")[:100] for p in final_papers[:10]
                    ],
                    "search_method": "search_literature_dynamic",
                    "think_success": think_success,
                    "iterations": len(coverage_history) - 1,
                    "coverage_sufficient": coverage_sufficient,
                    "recommended_actions": recommended_actions,
                    "filter_stage": filter_stage,
                    "rerank_applied_count": int(rerank_totals.get("applied_count", 0)),
                    "rerank_promoted_count": int(rerank_totals.get("promoted_count", 0)),
                    "rerank_dropped_count": int(rerank_totals.get("dropped_count", 0)),
                    "message": (
                        f"Full results ({len(final_papers)} papers) saved to "
                        f"{output_path}. Use read_file('/{output_path}') to "
                        f"access complete data."
                    ),
                }
            except Exception as e:
                logger.warning(f"Auto-save to {real_path} failed: {e}")
                # Fall through to return full_result
        else:
            logger.warning(
                "output_path='%s' specified but data_dir not set "
                "(param or DEEP_INTERPRETER_DATA_DIR env). Auto-save SKIPPED.",
                output_path,
            )
            return {
                **full_result,
                "error": "AUTO_SAVE_FAILED",
                "auto_save": False,
                "error_detail": (
                    f"output_path='{output_path}' specified but data_dir not available. "
                    f"Set DEEP_INTERPRETER_DATA_DIR env var or pass data_dir parameter."
                ),
            }

    return full_result
