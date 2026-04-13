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


# SJR (Scimago Journal Rank) Composite Score Cache
_SJR_SCORE_CACHE: dict[str, float] = {}  # normalized_name -> composite score (0-1)
_SJR_SCORE_CACHE_LOCK = threading.Lock()
_SJR_CACHE_LOADED = False

_SJR_CSV_URL = "https://raw.githubusercontent.com/Michael-E-Rose/SCImagoJournalRankIndicators/master/all.csv"
_SJR_DEFAULT_SCORE = 0.5
_SJR_CACHE_DIR = Path.home() / ".cache" / "deepmast"
_SJR_CACHE_FILE = _SJR_CACHE_DIR / "sjr_all.csv"
_SJR_CACHE_MAX_AGE_DAYS = 90
# Local SCImago official CSV (manually downloaded from scimagojr.com)
_SJR_LOCAL_DIR = Path(__file__).resolve().parents[4] / "data" / "sjr"

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


def _find_local_sjr_csv() -> str:
    """Find the most recent SCImago CSV in data/sjr/. Returns path or empty string."""
    if not _SJR_LOCAL_DIR.is_dir():
        return ""
    csvs = sorted(_SJR_LOCAL_DIR.glob("scimagojr*.csv"), reverse=True)
    if csvs:
        logger.info(f"Using local SCImago CSV: {csvs[0]}")
        return str(csvs[0])
    return ""


def _download_sjr_csv_sync() -> str:
    """Get SJR CSV path. Prefers local SCImago file, falls back to GitHub download.

    Priority:
    1. Local SCImago CSV in data/sjr/ (manually downloaded from scimagojr.com)
    2. Cached GitHub CSV in ~/.cache/deepmast/sjr_all.csv
    3. Fresh download from GitHub
    """
    import time as _time

    # Priority 1: Local SCImago official CSV
    local = _find_local_sjr_csv()
    if local:
        return local

    # Priority 2: Cached GitHub CSV
    _SJR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if _SJR_CACHE_FILE.exists():
        age_days = (_time.time() - _SJR_CACHE_FILE.stat().st_mtime) / 86400
        if age_days < _SJR_CACHE_MAX_AGE_DAYS:
            logger.debug(f"SJR cache is fresh ({age_days:.0f} days old)")
            return str(_SJR_CACHE_FILE)

    # Priority 3: Download from GitHub
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
        if _SJR_CACHE_FILE.exists():
            logger.info("Using stale SJR cache")
            return str(_SJR_CACHE_FILE)
        return ""


def _build_sjr_lookup(csv_path: str) -> dict[str, float]:
    """Parse SJR CSV and build composite score lookup.

    Auto-detects format:
    - SCImago official (semicolon-delimited, comma decimals, single year)
    - GitHub mirror (comma-delimited, multi-year with Year column)

    Composite = SJR_norm * 0.4 + hindex_norm * 0.3 + avgcit_norm * 0.3
    Each metric is log-normalized: log(1+x) / log(1+max_x) -> [0, 1]
    """
    if not csv_path:
        return {}

    # Auto-detect format by peeking at the header
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            header_line = f.readline()
    except Exception as e:
        logger.warning(f"Failed to read SJR CSV header: {e}")
        return {}

    is_scimago = ";" in header_line and "H index" in header_line

    # Phase 1: Collect raw values per journal (max across categories/years)
    raw: dict[str, tuple[float, float, float]] = {}
    # raw[name] = (sjr, h_index, avg_citations)

    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            if is_scimago:
                reader = csv.DictReader(f, delimiter=";")
                sjr_col, h_col, cit_col = "SJR", "H index", "Citations / Doc. (2years)"
            else:
                reader = csv.DictReader(f)
                sjr_col, h_col, cit_col = "SJR", "h-index", "avg_citations"

            for row in reader:
                title = row.get("Title", "").strip()
                if not title:
                    continue
                name = _normalize_journal_name(title)

                def _parse_float(val: str) -> float:
                    try:
                        return float((val or "0").replace(",", "."))
                    except (ValueError, TypeError):
                        return 0.0

                sjr_val = _parse_float(row.get(sjr_col, "0"))
                h_val = _parse_float(row.get(h_col, "0"))
                avg_cit = _parse_float(row.get(cit_col, "0"))

                if name in raw:
                    e_sjr, e_h, e_cit = raw[name]
                    raw[name] = (max(sjr_val, e_sjr), max(h_val, e_h), max(avg_cit, e_cit))
                else:
                    raw[name] = (sjr_val, h_val, avg_cit)
    except Exception as e:
        logger.warning(f"Failed to parse SJR CSV: {e}")
        return {}

    logger.info(f"SJR CSV format: {'SCImago official' if is_scimago else 'GitHub mirror'}")

    if not raw:
        return {}

    # Phase 2: Find max values for log-normalization
    max_sjr = max(v[0] for v in raw.values()) or 1.0
    max_h = max(v[1] for v in raw.values()) or 1.0
    max_cit = max(v[2] for v in raw.values()) or 1.0

    log_max_sjr = math.log(1 + max_sjr)
    log_max_h = math.log(1 + max_h)
    log_max_cit = math.log(1 + max_cit)

    # Phase 3: Compute composite scores
    lookup: dict[str, float] = {}
    for name, (sjr_val, h_val, cit_val) in raw.items():
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

    # Post-filter to reduce cross-disease retrieval noise
    if enforce_disease_match and diseases:
        disease_terms = [d for d in diseases if isinstance(d, str) and d.strip()]
        if disease_terms:
            kept = []
            uncertain = []
            rejected = 0
            for article in articles:
                result = _paper_matches_disease_context_simple(article, disease_terms)
                if result is True:
                    kept.append(article)
                elif result is False:
                    rejected += 1
                else:
                    uncertain.append(article)

            llm_dropped = 0
            rerank_local_stats = {
                "applied_count": 0, "dropped_count": 0,
            }
            if uncertain and _normalize_rerank_mode(rerank_mode) == "llm":
                llm_kept, rerank_local_stats = await _llm_disease_relevance_filter(
                    uncertain, disease_terms
                )
                kept.extend(llm_kept)
                llm_dropped = len(uncertain) - len(llm_kept)
            else:
                kept.extend(uncertain)  # No LLM → keep uncertain papers

            if rerank_stats is not None:
                _merge_rerank_stats(rerank_stats, rerank_local_stats)

            if rejected or llm_dropped:
                logger.debug(
                    "Disease filter: rule-rejected=%d, llm-dropped=%d, kept=%d",
                    rejected, llm_dropped, len(kept),
                )
            articles = kept

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



def _paper_matches_disease_context_simple(
    paper: dict[str, Any], diseases: list[str]
) -> bool | None:
    """Lightweight disease pre-filter.

    Returns:
        True  — paper clearly matches disease (canonical name found)
        False — paper clearly about a different disease (organ mismatch)
        None  — uncertain, delegate to LLM
    """
    title = paper.get("title", "") or ""
    abstract = paper.get("abstract", "") or ""
    text = _normalize_for_filter(title + " " + abstract)
    original_text = title + " " + abstract

    if not text.strip():
        return None  # No text → let LLM decide

    for disease in diseases:
        canonical = _normalize_for_filter(disease)
        if not canonical:
            continue
        if len(canonical) <= 4:
            # Word-boundary for short abbreviations (AML, AD, PD)
            if re.search(rf'\b{re.escape(canonical.upper())}\b', original_text):
                return True
        elif canonical in text:
            return True

    # Obvious organ-cancer mismatch detection
    for disease in diseases:
        d_norm = _normalize_for_filter(disease)
        disease_organs = {o for o in _ORGAN_TO_MEDICAL if o in d_norm}
        if not disease_organs:
            continue
        all_disease_organs = set(disease_organs)
        for o in disease_organs:
            all_disease_organs.update(_ORGAN_TO_MEDICAL[o])
        if not any(o in text for o in all_disease_organs):
            cancer_terms = {"cancer", "carcinoma", "tumor", "tumour", "neoplasm"}
            for other_organ in _ORGAN_TO_MEDICAL:
                if other_organ in all_disease_organs:
                    continue
                if other_organ in text and any(
                    f"{other_organ} {ct}" in text for ct in cancer_terms
                ):
                    return False

    return None  # Uncertain → delegate to LLM


async def _llm_disease_relevance_filter(
    uncertain_papers: list[dict],
    diseases: list[str],
) -> tuple[list[dict], dict[str, int]]:
    """LLM-based disease relevance filter for uncertain papers.

    Batch processes papers with a single LLM call.

    Returns:
        Tuple of (filtered papers, stats dict with applied/dropped counts)
    """
    stats = {"applied_count": 0, "dropped_count": 0}
    if not uncertain_papers:
        return [], stats

    compact_papers = []
    for p in uncertain_papers:
        compact_papers.append({
            "pmid": str(p.get("pmid", "")),
            "title": (p.get("title", "") or "")[:240],
            "abstract": (p.get("abstract", "") or "")[:800],
        })

    prompt = (
        "You are a biomedical literature relevance judge.\n"
        "Task: determine whether each paper is relevant to the target disease context.\n\n"
        f"Target diseases: {diseases}\n\n"
        "A paper is relevant if it studies, treats, diagnoses, or provides "
        "mechanistic insight into the target disease.\n"
        "Be conservative: if uncertain, mark as relevant.\n\n"
        "Return ONLY a JSON array:\n"
        '[{"pmid":"string","relevant":true|false}]\n\n'
        f"Papers:\n{json.dumps(compact_papers, ensure_ascii=False)}"
    )

    try:
        llm = create_llm()
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        response_text = (
            response.content if hasattr(response, "content") else str(response)
        )

        text = _strip_code_fence(response_text)
        if "[" in text and "]" in text:
            start = text.find("[")
            end = text.rfind("]") + 1
            text = text[start:end]

        parsed = json.loads(text)
        if not isinstance(parsed, list):
            return uncertain_papers, stats

        irrelevant_pmids: set[str] = set()
        for item in parsed:
            if isinstance(item, dict) and not item.get("relevant", True):
                irrelevant_pmids.add(str(item.get("pmid", "")))

        stats["applied_count"] = len(compact_papers)
        stats["dropped_count"] = len(irrelevant_pmids)

        filtered = [
            p for p in uncertain_papers
            if str(p.get("pmid", "")) not in irrelevant_pmids
        ]
        if stats["dropped_count"]:
            logger.debug(
                "LLM disease filter: dropped %d/%d papers",
                stats["dropped_count"],
                len(uncertain_papers),
            )
        return filtered, stats

    except Exception as e:
        logger.debug(f"LLM disease filter failed: {e}")
        return uncertain_papers, stats



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
    for key in ("applied_count", "dropped_count"):
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
    lr_pairs: list[dict] | None = None,
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
        lr_pairs: Optional list of L-R pair dicts [{"ligand": str, "receptor": str}, ...].
            When provided, adds pair co-occurrence tracking to the coverage dict.

    Returns:
        Coverage dictionary with covered items and percentages.
        When lr_pairs is provided, also includes:
        - pairs_covered: List of "LIGAND^RECEPTOR" strings for pairs found in same paper
        - pairs_coverage_pct: Percentage of provided pairs covered
        - pairs_missing: List of uncovered pair strings
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

    # L-R pair co-occurrence: both genes must appear in SAME paper (informational, v1)
    pairs_covered_set: set[str] = set()
    if lr_pairs:
        # Pre-generate patterns for all pair genes (optimization: once, not per-paper)
        pair_gene_patterns: dict[str, list[str]] = {}
        for pair in lr_pairs:
            for gene_key in ("ligand", "receptor"):
                gene = pair.get(gene_key, "")
                if gene and gene not in pair_gene_patterns:
                    # Handle complex receptors like ITGA2_ITGB1
                    for g in gene.split("_"):
                        g = g.strip()
                        if g and g not in pair_gene_patterns:
                            pair_gene_patterns[g] = _generate_gene_patterns(g)

        # Build per-paper gene hit sets
        for paper in papers:
            combined = _normalize_text_for_matching(
                paper.get("abstract", "") + " " + paper.get("title", "")
            )
            hits: set[str] = set()
            for gene, patterns in pair_gene_patterns.items():
                for pattern in patterns:
                    if len(pattern) <= 3:
                        if re.search(rf'\b{re.escape(pattern)}\b', combined):
                            hits.add(gene)
                            break
                    elif pattern in combined:
                        hits.add(gene)
                        break

            # Check pair co-occurrence in this paper
            for pair in lr_pairs:
                lig = pair.get("ligand", "")
                rec = pair.get("receptor", "")
                pair_key = f"{lig}^{rec}"
                if pair_key in pairs_covered_set:
                    continue
                # For complex receptors (ITGA2_ITGB1), check any subunit
                rec_genes = [g.strip() for g in rec.split("_") if g.strip()] if "_" in rec else [rec]
                if lig in hits and any(rg in hits for rg in rec_genes):
                    pairs_covered_set.add(pair_key)

        coverage["pairs_covered"] = sorted(pairs_covered_set)
        coverage["pairs_coverage_pct"] = len(pairs_covered_set) / len(lr_pairs) * 100
        coverage["pairs_missing"] = [
            f"{p.get('ligand')}^{p.get('receptor')}"
            for p in lr_pairs
            if f"{p.get('ligand')}^{p.get('receptor')}" not in pairs_covered_set
        ]

    return coverage


def _compute_paper_coverage_score(
    paper: dict,
    genes: list[str],
    pathways: list[str],
    celltypes: list[str],
    already_covered: set[str] | None = None,
) -> tuple[float, set[str]]:
    """Compute how many target entities a single paper covers.

    Args:
        paper: Paper dict with 'title' and 'abstract'.
        genes: Target gene list.
        pathways: Target pathway list.
        celltypes: Target cell type list.
        already_covered: If provided, only count entities NOT in this set
            (for greedy marginal-contribution calculation).

    Returns:
        (score, covered_entities) where score is the fraction of (novel)
        entities this paper covers and covered_entities is the set of
        entity names matched.
    """
    combined = _normalize_text_for_matching(
        paper.get("abstract", "") + " " + paper.get("title", "")
    )
    covered: set[str] = set()

    # Gene matching (reuses existing pattern generator)
    for gene in genes:
        if already_covered and gene in already_covered:
            continue
        for pattern in _generate_gene_patterns(gene):
            if len(pattern) <= 3:
                if re.search(rf'\b{re.escape(pattern)}\b', combined):
                    covered.add(gene)
                    break
            else:
                if pattern in combined:
                    covered.add(gene)
                    break

    # Pathway matching
    for pathway in pathways:
        if already_covered and pathway in already_covered:
            continue
        for pattern in _generate_pathway_patterns(pathway):
            if pattern in combined:
                covered.add(pathway)
                break

    # Cell type matching
    for celltype in celltypes:
        if already_covered and celltype in already_covered:
            continue
        ct_lower = celltype.lower()
        if ct_lower in combined:
            covered.add(celltype)
        elif re.sub(r'\s*\d+\s*', '', ct_lower) in combined:
            covered.add(celltype)

    total_target = len(genes) + len(pathways) + len(celltypes)
    if already_covered:
        total_target = total_target - len(already_covered)

    score = len(covered) / total_target if total_target > 0 else 0.0
    return score, covered


def _greedy_coverage_sort(
    papers: list[dict],
    genes: list[str],
    pathways: list[str],
    celltypes: list[str],
    max_results: int,
    alpha: float = 0.4,
) -> list[dict]:
    """Greedy set-cover sort blending journal quality with marginal coverage.

    At each step picks the paper maximising:
        alpha * normalised_sjr  +  (1 - alpha) * marginal_coverage_contribution

    Once all target entities are covered the remaining slots are filled by
    pure SJR order (no coverage signal needed).

    Args:
        papers: Candidate papers (already deduplicated).
        genes/pathways/celltypes: Target entity lists.
        max_results: How many papers to select.
        alpha: Blend weight.  0 = pure coverage, 1 = pure SJR.

    Returns:
        Ordered list of at most *max_results* papers.
    """
    if not papers:
        return []

    all_entities = set(genes) | set(pathways) | set(celltypes)
    if not all_entities:
        # Nothing to optimise for coverage — fall back to pure SJR
        papers_sorted = sorted(
            papers,
            key=lambda p: p.get("journal_quality", _SJR_DEFAULT_SCORE),
            reverse=True,
        )
        return papers_sorted[:max_results]

    # Pre-compute per-paper full entity coverage (before greedy loop)
    paper_entities: list[tuple[dict, set[str]]] = []
    for paper in papers:
        _, entities = _compute_paper_coverage_score(
            paper, genes, pathways, celltypes,
        )
        paper_entities.append((paper, entities))

    # Normalise SJR scores to [0, 1] across candidate set
    sjr_values = [p.get("journal_quality", _SJR_DEFAULT_SCORE) for p in papers]
    sjr_min = min(sjr_values)
    sjr_max = max(sjr_values)
    sjr_range = sjr_max - sjr_min if sjr_max > sjr_min else 1.0

    selected: list[dict] = []
    covered: set[str] = set()
    remaining = list(range(len(paper_entities)))  # indices into paper_entities

    while len(selected) < max_results and remaining:
        # Once all entities covered, fill by SJR only
        if covered >= all_entities:
            leftover = [paper_entities[i][0] for i in remaining]
            leftover.sort(
                key=lambda p: p.get("journal_quality", _SJR_DEFAULT_SCORE),
                reverse=True,
            )
            selected.extend(leftover[: max_results - len(selected)])
            break

        best_idx = -1
        best_score = -1.0
        for idx in remaining:
            paper, entities = paper_entities[idx]
            marginal = entities - covered
            marginal_frac = len(marginal) / len(all_entities - covered) if (all_entities - covered) else 0.0
            norm_sjr = (paper.get("journal_quality", _SJR_DEFAULT_SCORE) - sjr_min) / sjr_range
            composite = alpha * norm_sjr + (1 - alpha) * marginal_frac
            if composite > best_score:
                best_score = composite
                best_idx = idx

        paper, entities = paper_entities[best_idx]
        selected.append(paper)
        covered |= entities
        remaining.remove(best_idx)

    return selected



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


def _format_lr_pairs_for_prompt(pairs: list[dict] | None) -> str:
    """Format L-R pairs for the query generation prompt."""
    if not pairs:
        return "None"
    return ", ".join(
        f"{p.get('ligand', '')}-{p.get('receptor', '')}" + (f" (score: {p['score']:.2f})" if 'score' in p else "")
        for p in pairs[:10]  # Limit to 10 in prompt for token control
    )


async def _think_search_strategy(
    genes: list[str],
    pathways: list[str],
    celltypes: list[str],
    disease: str,
    lr_pairs: list[dict] | None = None,
    biomcp_url: str = DEFAULT_BIOMCP_URL,
) -> str:
    """Execute a single BioMCP think call to plan search strategy for SEARCHER.

    Unlike _think_with_biomcp_for_planner (3-step chain for PLANNER interpretation),
    this is a 1-step strategic call focused on literature search optimization:
    which gene combinations yield the best results, which keywords disambiguate
    common gene names, and which biological contexts narrow the search.

    Called ONCE per search_literature_dynamic_async invocation, BEFORE the
    iteration loop. Output is injected into the LLM query generation prompt.

    Args:
        genes: Gene list from analysis
        pathways: Pathway list from analysis
        celltypes: Cell type list from analysis
        disease: Disease context
        lr_pairs: L-R pairs (if available from file)
        biomcp_url: BioMCP server URL

    Returns:
        Search strategy text wrapped in section header (empty string on failure)
    """
    try:
        tools = await get_biomcp_tools(biomcp_url)
        think_tool_biomcp = find_tool_by_name(tools, "think")

        if think_tool_biomcp is None:
            logger.debug("BioMCP think tool not found for search strategy")
            return ""

        # Build compact context for the think call
        genes_str = ", ".join(genes[:15]) if genes else "none"
        pathways_str = ", ".join(pathways[:8]) if pathways else "none"
        celltypes_str = ", ".join(celltypes[:8]) if celltypes else "none"
        pairs_str = ", ".join(
            f"{p['ligand']}-{p['receptor']}" for p in (lr_pairs or [])[:8]
        ) or "none"

        result = await asyncio.wait_for(
            think_tool_biomcp.ainvoke({
                "thought": (
                    f"Search strategy for {disease or 'unspecified disease'}: "
                    f"I need to find literature covering genes [{genes_str}], "
                    f"pathways [{pathways_str}], cell types [{celltypes_str}], "
                    f"and L-R pairs [{pairs_str}]. "
                    f"What are the best PubMed search strategies? Consider: "
                    f"(1) which gene combinations co-occur in papers, "
                    f"(2) alternative gene names or symbols that improve recall, "
                    f"(3) which pathway-disease keyword combinations are most specific, "
                    f"(4) whether any L-R pairs are well-studied vs. novel."
                ),
                "thoughtNumber": 1,
                "totalThoughts": 1,
                "nextThoughtNeeded": False,
            }),
            timeout=15,
        )

        strategy = str(result).strip()
        if strategy:
            logger.info(f"BioMCP search strategy think completed ({len(strategy)} chars)")
            return f"\n## Search Strategy Context\n{strategy}\n"
        return ""

    except Exception as e:
        logger.warning(f"BioMCP search strategy think failed (non-critical): {e}")
        invalidate_client(f"biomcp_{biomcp_url}")
        return ""


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
    llm_provider: str = "",
    sort_by_journal_quality: bool = True,
    coverage_weighted_sort: bool = False,
    query_cache: list[dict] | None = None,
    record_queries: bool = False,
    enable_lr_pair_queries: bool = False,
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
        llm_provider: Override LLM provider for query generation (e.g. "openai").
            Empty string uses env default.
        sort_by_journal_quality: Whether to sort final results by SJR journal
            quality score (default True). Set False to skip SJR sorting.
        query_cache: Cached iteration-0 queries to replay (skip LLM generation).
        record_queries: If True, include iteration-0 queries in return value
            under the "query_cache" key.

    Returns:
        If output_path is empty: Dictionary with papers, generated_queries, coverage,
        think_success, iterations, coverage_history.
        If output_path is provided: Compact summary with saved_to, total_papers,
        coverage, paper_titles (first 10), and a message.
    """
    # Auto-read lr_pairs from data_dir ONLY if caller explicitly opted in
    # (prevents silent pair injection for PLANNER/REPORTER which pass data_dir for
    # save-path purposes only — fixes Codex adversarial review finding #1)
    _lr_pairs = None
    if enable_lr_pair_queries and data_dir:
        _lr_pairs_file = Path(data_dir) / "lr_pairs_search.json"
        if _lr_pairs_file.exists():
            try:
                with open(_lr_pairs_file) as f:
                    _lr_pairs = json.load(f).get("pairs", [])
                logger.debug(f"Auto-loaded {len(_lr_pairs)} L-R pairs from {_lr_pairs_file}")
            except Exception:
                pass  # Non-critical: search proceeds without pair data

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
            llm_provider=llm_provider,
            sort_by_journal_quality=sort_by_journal_quality,
            coverage_weighted_sort=coverage_weighted_sort,
            query_cache=query_cache,
            record_queries=record_queries,
            lr_pairs=_lr_pairs,
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
    llm_provider: str = "",
    sort_by_journal_quality: bool = True,
    coverage_weighted_sort: bool = False,
    query_cache: list[dict] | None = None,
    record_queries: bool = False,
    lr_pairs: list[dict] | None = None,
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
        llm_provider: Override LLM provider for query generation (e.g. "openai").
            Empty string uses env default.
        sort_by_journal_quality: Whether to sort final results by SJR journal
            quality score (default True).
        query_cache: Cached iteration-0 queries to replay (skip LLM generation).
        record_queries: If True, include iteration-0 queries in return value
            under the "query_cache" key.

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
    rerank_totals = {"applied_count": 0, "dropped_count": 0}

    # think_success reflects actual BioMCP think tool outcome.
    # Initialized to False; set to True only when _think_search_strategy returns content.
    # (Fixes Codex adversarial review finding #3 — observability gap.)
    think_success = False

    # Note: pre-fetch aliases removed - BioMCP article_searcher
    # automatically handles gene aliases internally (e.g., ACKR3 -> CXCR7)

    llm = create_llm(provider=llm_provider) if llm_provider else create_llm()
    recorded_iter0_queries: list[dict] = []

    # v2: BioMCP think for search strategy (single call, pre-loop)
    search_strategy_context = ""
    if query_cache is None:  # Skip think when replaying cached queries
        search_strategy_context = await _think_search_strategy(
            genes=genes,
            pathways=pathways,
            celltypes=celltypes,
            disease=disease,
            lr_pairs=lr_pairs,
            biomcp_url=biomcp_url,
        )
        if search_strategy_context:
            think_success = True

    for iteration in range(max_iterations):
        logger.info(f"=== Async Iteration {iteration + 1}/{max_iterations} ===")

        # Calculate current coverage
        current_coverage = _calculate_coverage(all_papers, genes, pathways, celltypes, lr_pairs=lr_pairs)
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
            if query_cache is not None:
                # REPLAY: use cached queries, skip LLM entirely
                validated_queries = query_cache
                all_queries.extend(validated_queries)
                logger.info(f"Replaying {len(validated_queries)} cached iteration-0 queries")
            else:
                # GENERATE: initial broad search via LLM
                # Note: gene_aliases="" - BioMCP article_searcher handles aliases internally
                prompt_text = LITERATURE_QUERY_GENERATION_PROMPT.format(
                    genes=", ".join(genes) if genes else "None",
                    pathways=", ".join(pathways) if pathways else "None",
                    celltypes=", ".join(celltypes) if celltypes else "None",
                    disease=disease or "Not specified",
                    gene_aliases="",  # BioMCP article_searcher handles aliases internally
                    lr_pairs=_format_lr_pairs_for_prompt(lr_pairs),
                    search_strategy=search_strategy_context,
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

        # When replaying cached iteration-0 queries, skip LLM generation
        if iteration == 0 and query_cache is not None:
            pass  # validated_queries already set above from cache
        else:
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

            # Record iteration-0 queries if requested
            if iteration == 0 and record_queries:
                recorded_iter0_queries = list(validated_queries)

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
                fallback_papers: list[dict] = []
                for paper in results:
                    pmid = paper.get("pmid", "")
                    if pmid and pmid not in seen_pmids:
                        seen_pmids.add(pmid)
                        paper["query_index"] = len(all_queries) - len(validated_queries) + i
                        paper["iteration"] = iteration
                        paper["query_type"] = "gene"
                        # Option D: gap-filling validation for iteration > 0
                        if coverage_weighted_sort and iteration > 0:
                            score, _ = _compute_paper_coverage_score(
                                paper, genes, pathways, celltypes,
                            )
                            if score == 0:
                                fallback_papers.append(paper)
                                continue
                        all_papers.append(paper)
                        new_papers += 1

                # Backfill from fallback if slots remain
                if fallback_papers and len(all_papers) < max_results:
                    slots = max_results - len(all_papers)
                    all_papers.extend(fallback_papers[:slots])
                    new_papers += min(slots, len(fallback_papers))

                logger.debug(f"Gene query {i}: {new_papers} new papers (fallback={len(fallback_papers)})")

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
                fallback_papers = []
                for paper in results:
                    pmid = paper.get("pmid", "")
                    if pmid and pmid not in seen_pmids:
                        seen_pmids.add(pmid)
                        paper["query_index"] = len(all_queries) - len(validated_queries) + len(gene_queries) + i
                        paper["iteration"] = iteration
                        paper["query_type"] = "pathway"
                        # Option D: gap-filling validation for iteration > 0
                        if coverage_weighted_sort and iteration > 0:
                            score, _ = _compute_paper_coverage_score(
                                paper, genes, pathways, celltypes,
                            )
                            if score == 0:
                                fallback_papers.append(paper)
                                continue
                        all_papers.append(paper)
                        new_papers += 1

                # Backfill from fallback if slots remain
                if fallback_papers and len(all_papers) < max_results:
                    slots = max_results - len(all_papers)
                    all_papers.extend(fallback_papers[:slots])
                    new_papers += min(slots, len(fallback_papers))

                logger.debug(f"Pathway query {i}: {new_papers} new papers (fallback={len(fallback_papers)})")

            except Exception as e:
                logger.warning(f"Pathway search failed for query {i} at iteration {iteration}: {e}")
                continue

    # Truncation: coverage-weighted greedy sort or pure SJR sort
    if sort_by_journal_quality:
        await _ensure_sjr_cache_loaded()
        if coverage_weighted_sort:
            final_papers = _greedy_coverage_sort(
                all_papers, genes, pathways, celltypes,
                max_results=max_results, alpha=0.4,
            )
        else:
            all_papers.sort(key=lambda p: p.get("journal_quality", _SJR_DEFAULT_SCORE), reverse=True)
            final_papers = all_papers[:max_results]
    else:
        final_papers = all_papers[:max_results]
    final_coverage = _calculate_coverage(final_papers, genes, pathways, celltypes, lr_pairs=lr_pairs)

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

    # Pair coverage warning (informational only — not a gap-filling trigger in v2)
    # Fixes Codex adversarial review finding #2 — observability gap when 0 pairs covered.
    if lr_pairs:
        pairs_pct = final_coverage.get("pairs_coverage_pct", 0)
        pairs_covered_count = len(final_coverage.get("pairs_covered", []))
        logger.info(
            f"L-R pair coverage: {pairs_covered_count}/{len(lr_pairs)} ({pairs_pct:.1f}%)"
        )
        if pairs_pct == 0:
            recommended_actions.append(
                f"WARNING: 0/{len(lr_pairs)} L-R pairs covered despite being provided. "
                f"Consider increasing max_results or verifying pair quality."
            )

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
        "rerank_dropped_count": int(rerank_totals.get("dropped_count", 0)),
    }

    if record_queries and recorded_iter0_queries:
        full_result["query_cache"] = recorded_iter0_queries

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
