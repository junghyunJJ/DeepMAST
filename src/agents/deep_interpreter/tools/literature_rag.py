"""RAG-enhanced literature tools for INTERPRETER subagent.

Provides full-text paper download, indexing, and semantic search
capabilities using pubmed-download and langconnect-rag MCP servers.

Falls back to Abstract-based approach if Docker/RAG unavailable.
"""

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from src.agents.deep_interpreter.tools.mcp_clients import (
    run_async,
    _get_cached_tools,
    find_tool_by_name,
    invalidate_client,
)


logger = logging.getLogger(__name__)


# =============================================================================
# Async-safe file I/O helpers
# =============================================================================
def _path_exists(path: str) -> bool:
    """Sync helper for checking path existence."""
    return Path(path).exists()


def _mkdir_parents(path: str) -> None:
    """Sync helper for creating directories with parents."""
    Path(path).mkdir(parents=True, exist_ok=True)


def _read_json_file(path: str) -> Any:
    """Sync helper for reading JSON files with LLM error repair."""
    with open(path, 'r') as f:
        raw = f.read()
    return _repair_json(raw)


def _resolve_path(path: str) -> str:
    """Sync helper for resolving path to absolute."""
    return str(Path(path).resolve())


def _resolve_papers_path(path: str, data_dir: str = "") -> str:
    """Resolve virtual/relative papers path to real OS path.

    DeepAgents uses virtual paths like '/papers.json' which resolve
    to the OS root instead of the data directory. This helper resolves:

    Resolution order:
    1. If path exists as-is → use directly
    2. If data_dir provided → try data_dir/{basename}
    3. If contextvars data_dir set → try context_data_dir/{basename}
    4. Fallback → CWD resolution

    Args:
        path: Virtual, relative, or absolute path to papers JSON
        data_dir: Explicit data directory

    Returns:
        Resolved absolute path to the file
    """
    # 1. If path exists as-is, use it directly
    if Path(path).exists():
        return str(Path(path).resolve())

    # 2. Try explicit data_dir first
    if data_dir:
        candidate = Path(data_dir) / Path(path).name
        if candidate.exists():
            logger.debug(f"_resolve_papers_path: resolved '{path}' -> '{candidate}' (data_dir)")
            return str(candidate.resolve())

    # 3. Try env var data_dir fallback
    if not data_dir:
        env_dir = os.getenv("DEEP_INTERPRETER_DATA_DIR", "")
        if env_dir:
            candidate = Path(env_dir) / Path(path).name
            if candidate.exists():
                logger.debug(f"_resolve_papers_path: resolved '{path}' -> '{candidate}' (env_var)")
                return str(candidate.resolve())

    # 4. Fallback: CWD resolution
    resolved = Path(path).resolve()
    logger.debug(f"_resolve_papers_path: fallback resolution '{path}' -> '{resolved}'")
    return str(resolved)


def _repair_json(raw: str) -> Any:
    """Conservative JSON repair for common LLM writing errors.

    Handles:
    - Trailing commas before ] or }
    - Extra closing braces/brackets
    - Missing closing braces/brackets

    Args:
        raw: Raw JSON string (potentially malformed)

    Returns:
        Parsed Python object (dict or list)

    Raises:
        json.JSONDecodeError: If JSON is unrecoverable
    """
    # Fast path: try parsing as-is
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    text = raw.strip()

    # Remove trailing commas before ] or }
    text = re.sub(r',\s*([}\]])', r'\1', text)

    # Remove trailing comma at end of string (before adding missing braces)
    text = re.sub(r',\s*$', '', text)

    # Try again after comma fix
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Balance braces/brackets
    open_braces = text.count('{') - text.count('}')
    open_brackets = text.count('[') - text.count(']')

    if open_braces < 0:
        # Extra closing braces - remove from end
        for _ in range(-open_braces):
            idx = text.rfind('}')
            if idx != -1:
                text = text[:idx] + text[idx + 1:]
    elif open_braces > 0:
        # Missing closing braces - add at end
        text = text + '}' * open_braces

    if open_brackets < 0:
        # Extra closing brackets - remove from end
        for _ in range(-open_brackets):
            idx = text.rfind(']')
            if idx != -1:
                text = text[:idx] + text[idx + 1:]
    elif open_brackets > 0:
        # Missing closing brackets - add at end
        text = text + ']' * open_brackets

    # Final attempt
    return json.loads(text)


def _glob_files(directory: str, pattern: str) -> list[str]:
    """Sync helper for globbing files in a directory."""
    return [str(p) for p in Path(directory).glob(pattern)]


# =============================================================================
# Configuration (lazy-loaded to support ASGI environments where .env
# is loaded after module import)
# =============================================================================
def _get_pubmed_mcp_python() -> str | None:
    return os.getenv("PUBMED_MCP_PYTHON")

def _get_pubmed_mcp_server() -> str | None:
    return os.getenv("PUBMED_MCP_SERVER")

def _get_pubmed_email() -> str | None:
    return os.getenv("PUBMED_EMAIL")

def _get_ncbi_api_key() -> str | None:
    return os.getenv("NCBI_API_KEY")

def _get_jina_api_key() -> str | None:
    return os.getenv("JINA_API_KEY")

def _get_cci_rag_python() -> str | None:
    return os.getenv("CCI_RAG_PYTHON")

def _get_cci_rag_server() -> str | None:
    return os.getenv("CCI_RAG_SERVER")

def _get_cci_rag_base_url() -> str:
    return os.getenv("CCI_RAG_BASE_URL", "http://localhost:8888")

RAG_COLLECTION_PREFIX = "deep_interpreter_"
DEFAULT_PAPERS_DIR = "res/papers"

# Module-level cache for RAG state
_RAG_STATE: dict[str, Any] = {
    "available": None,  # None = not checked, True/False = checked
    "collection_ids": {},  # {part_name: collection_id}
}


def _normalize_search_result(item: dict) -> dict:
    """Normalize search result to standard format.

    langconnect-rag returns: {"id": "...", "content": "...", "score": 0.85, "metadata": {...}}
    We normalize to: {"page_content": "...", "metadata": {...}, "score": 0.85, "id": "..."}

    Args:
        item: Raw search result dict

    Returns:
        Normalized dict with page_content, metadata, score, id fields
    """
    # Debug: Log raw item structure before normalization
    logger.debug(f"_normalize_search_result: raw item keys = {list(item.keys())}")

    # Try multiple possible score field names (different vector DBs use different names)
    score = (
        item.get("score") or
        item.get("similarity") or
        item.get("relevance_score") or
        item.get("_score") or
        0.0
    )

    # Handle distance metrics (lower is better) - convert to similarity
    if "distance" in item and score == 0.0:
        distance = item.get("distance", 1.0)
        score = max(0, 1 - distance)  # Convert distance to similarity

    logger.debug(f"_normalize_search_result: extracted score = {score} (raw fields: score={item.get('score', 'MISSING')}, similarity={item.get('similarity', 'MISSING')}, distance={item.get('distance', 'MISSING')})")

    return {
        "page_content": item.get("content") or item.get("page_content", ""),
        "metadata": item.get("metadata", {}),
        "score": score,
        "id": item.get("id", ""),
    }


def reset_rag_state() -> None:
    """Reset RAG state cache. Useful for testing."""
    _RAG_STATE["available"] = None
    _RAG_STATE["collection_ids"].clear()


async def _get_cci_rag_tools() -> list:
    """Get cached CCI-RAG tools via singleton MCP client.

    Uses _get_cached_tools from mcp_clients.py to prevent spawning
    a new subprocess on every call.

    Returns:
        List of LangChain tool objects from CCI-RAG server

    Raises:
        ValueError: If required environment variables are not set
    """
    cci_rag_python = _get_cci_rag_python()
    cci_rag_server = _get_cci_rag_server()
    if not cci_rag_python or not cci_rag_server:
        raise ValueError(
            "CCI_RAG_PYTHON and CCI_RAG_SERVER environment variables are required. "
            "Please set them in your .env file."
        )

    config = {
        "command": cci_rag_python,
        "args": [cci_rag_server],
        "env": {"API_BASE_URL": _get_cci_rag_base_url()},
        "transport": "stdio",
    }
    return await _get_cached_tools("CCI-RAG", config)


async def _get_pubmed_download_tools() -> list:
    """Get cached pubmed-download tools via singleton MCP client.

    Returns:
        List of LangChain tool objects from pubmed-download server

    Raises:
        ValueError: If required environment variables are not set
    """
    pubmed_mcp_python = _get_pubmed_mcp_python()
    pubmed_mcp_server = _get_pubmed_mcp_server()
    if not pubmed_mcp_python or not pubmed_mcp_server:
        raise ValueError(
            "PUBMED_MCP_PYTHON and PUBMED_MCP_SERVER environment variables are required."
        )

    mcp_env = {}
    pubmed_email = _get_pubmed_email()
    jina_api_key = _get_jina_api_key()
    ncbi_api_key = _get_ncbi_api_key()
    if pubmed_email:
        mcp_env["PUBMED_EMAIL"] = pubmed_email
    if jina_api_key:
        mcp_env["JINA_API_KEY"] = jina_api_key
    if ncbi_api_key:
        mcp_env["NCBI_API_KEY"] = ncbi_api_key

    config = {
        "command": pubmed_mcp_python,
        "args": [pubmed_mcp_server],
        "env": mcp_env,
        "transport": "stdio",
    }
    return await _get_cached_tools("pubmed-download", config)


# =============================================================================
# Health Check
# =============================================================================
async def check_rag_availability() -> bool:
    """Check if RAG infrastructure (langconnect-rag) is available.

    Uses stdio transport (same as st_pipeline_info_agent.py).
    Caches result for session to avoid repeated health checks.

    Returns:
        True if RAG available, False otherwise (fallback to Abstract mode)
    """
    # Return cached result if available
    if _RAG_STATE["available"] is not None:
        logger.debug(f"check_rag_availability: using cached result = {_RAG_STATE['available']}")
        return _RAG_STATE["available"]

    # Check if environment variables are set
    cci_rag_python = _get_cci_rag_python()
    cci_rag_server = _get_cci_rag_server()
    if not cci_rag_python or not cci_rag_server:
        logger.debug(f"check_rag_availability: CCI_RAG env vars not set")
        logger.debug(f"  CCI_RAG_PYTHON={cci_rag_python}")
        logger.debug(f"  CCI_RAG_SERVER={cci_rag_server}")
        logger.info("RAG not available: CCI_RAG_PYTHON or CCI_RAG_SERVER not set")
        _RAG_STATE["available"] = False
        return False

    logger.debug(f"check_rag_availability: using stdio transport")
    logger.debug(f"  CCI_RAG_PYTHON={cci_rag_python}")
    logger.debug(f"  CCI_RAG_SERVER={cci_rag_server}")
    logger.debug(f"  CCI_RAG_BASE_URL={_get_cci_rag_base_url()}")

    try:
        tools = await _get_cci_rag_tools()
        logger.debug(f"check_rag_availability: got {len(tools)} tools")

        # Find health check tool
        for tool_obj in tools:
            if hasattr(tool_obj, 'name') and 'health' in tool_obj.name.lower():
                logger.debug(f"check_rag_availability: calling health tool")
                result = await tool_obj.ainvoke({})
                # Handle different result formats
                if isinstance(result, dict):
                    _RAG_STATE["available"] = result.get("status") == "ok"
                elif isinstance(result, list) and len(result) > 0:
                    # BioMCP format: [{'type': 'text', 'text': '...'}]
                    text = result[0].get("text", "") if isinstance(result[0], dict) else str(result[0])
                    _RAG_STATE["available"] = "ok" in text.lower() or "healthy" in text.lower()
                else:
                    _RAG_STATE["available"] = True
                logger.debug(f"check_rag_availability: health check result = {_RAG_STATE['available']}")
                logger.info(f"RAG availability check: {_RAG_STATE['available']}")
                return _RAG_STATE["available"]

        # If no health tool but got tools, assume working
        _RAG_STATE["available"] = len(tools) > 0
        logger.debug(f"check_rag_availability: no health tool, assuming {_RAG_STATE['available']}")
        logger.info(f"RAG availability (no health tool, {len(tools)} tools found): {_RAG_STATE['available']}")
        return _RAG_STATE["available"]

    except Exception as e:
        logger.debug(f"check_rag_availability: EXCEPTION {type(e).__name__}: {e}")
        logger.info(f"RAG not available (using Abstract mode): {e}")
        invalidate_client("CCI-RAG")
        _RAG_STATE["available"] = False
        return False


def check_rag_availability_sync() -> bool:
    """Sync wrapper for check_rag_availability.

    Returns:
        True if RAG available, False otherwise
    """
    if _RAG_STATE["available"] is not None:
        return _RAG_STATE["available"]

    try:
        return run_async(check_rag_availability(), timeout=10)
    except Exception as e:
        logger.debug(f"RAG availability check failed: {e}")
        _RAG_STATE["available"] = False
        return False


# =============================================================================
# Paper Download
# =============================================================================
async def download_papers_for_rag(
    pmids: list[str],
    output_dir: str = DEFAULT_PAPERS_DIR,
) -> dict[str, dict]:
    """Download full-text papers using pubmed-download MCP.

    Args:
        pmids: List of PMIDs to download
        output_dir: Directory to save papers (default: res/papers/)

    Returns:
        Dict mapping PMID to download result:
        {
            "12345678": {
                "success": True,
                "file_path": "res/papers/pmid_12345678.txt",
                "source": "PMC" | "DOI" | "PubMed_Abstract"
            }
        }
    """
    # CRITICAL FIX: Convert to absolute path to ensure files are saved in DeepMAST directory,
    # not in the MCP server's working directory
    # Use asyncio.to_thread to avoid blocking os.getcwd() call in ASGI context
    output_dir_abs = await asyncio.to_thread(_resolve_path, output_dir)
    logger.debug(f"download_papers_for_rag: {len(pmids)} PMIDs")
    logger.debug(f"download_papers_for_rag: output_dir resolved to {output_dir_abs}")
    results = {}

    # Check if environment variables are set
    pubmed_mcp_python = _get_pubmed_mcp_python()
    pubmed_mcp_server = _get_pubmed_mcp_server()
    if not pubmed_mcp_python or not pubmed_mcp_server:
        logger.debug(f"download_papers_for_rag: PUBMED_MCP env vars not set")
        logger.debug(f"  PUBMED_MCP_PYTHON={pubmed_mcp_python}")
        logger.debug(f"  PUBMED_MCP_SERVER={pubmed_mcp_server}")
        logger.warning("pubmed-download MCP not configured: PUBMED_MCP_PYTHON or PUBMED_MCP_SERVER not set")
        return results

    # Ensure output directory exists (async-safe)
    await asyncio.to_thread(_mkdir_parents, output_dir_abs)

    try:
        logger.debug(f"download_papers_for_rag: connecting via cached stdio transport")
        tools = await _get_pubmed_download_tools()
        logger.debug(f"download_papers_for_rag: got {len(tools)} tools")

        # Find download_paper tool
        download_tool = None
        for tool_obj in tools:
            if hasattr(tool_obj, 'name') and 'download_paper' in tool_obj.name:
                download_tool = tool_obj
                break

        if download_tool is None:
            logger.debug(f"download_papers_for_rag: download_paper tool NOT FOUND")
            logger.warning("download_paper tool not found in pubmed-download MCP")
            return results

        logger.debug(f"download_papers_for_rag: download_paper tool found")

        # Download papers with rate limiting
        total = min(len(pmids), 30)
        logger.debug(f"download_papers_for_rag: downloading {total} papers (max 30)")

        for i, pmid in enumerate(pmids[:30]):  # Limit to prevent rate limiting
            file_path = str(Path(output_dir_abs) / f"pmid_{pmid}.txt")

            # Check if already downloaded (async-safe)
            if await asyncio.to_thread(_path_exists, file_path):
                results[pmid] = {
                    "success": True,
                    "file_path": file_path,
                    "source": "Cache",
                }
                logger.debug(f"PMID {pmid} [{i+1}/{total}]: CACHED")
                continue

            try:
                result = await download_tool.ainvoke({
                    "pmid": pmid,
                    "output_path": file_path,
                    "prefer_pmc": True,
                })

                # Parse result based on format
                # CRITICAL FIX: Always verify file existence first, don't trust MCP response text
                file_exists = await asyncio.to_thread(_path_exists, file_path)

                if isinstance(result, dict):
                    # Override success based on actual file existence
                    result["success"] = file_exists
                    result["file_path"] = file_path if file_exists else None
                    results[pmid] = result
                elif isinstance(result, list) and len(result) > 0:
                    # BioMCP format
                    text = result[0].get("text", "") if isinstance(result[0], dict) else str(result[0])

                    if file_exists:
                        # File actually exists - this is a real success
                        source = "PMC" if "pmc" in text.lower() else "PubMed"
                        results[pmid] = {
                            "success": True,
                            "file_path": file_path,
                            "source": source,
                        }
                    else:
                        # File doesn't exist - report failure regardless of MCP response
                        results[pmid] = {
                            "success": False,
                            "file_path": None,
                            "source": "Not_Downloaded",
                        }
                        if "success" in text.lower():
                            logger.warning(
                                f"PMID {pmid}: MCP reported success but file not found at {file_path}"
                            )
                else:
                    results[pmid] = {
                        "success": file_exists,
                        "file_path": file_path if file_exists else None,
                        "source": "Unknown",
                    }

                status = "OK" if results[pmid].get("success") else "FAIL"
                source = results[pmid].get("source", "Unknown")
                logger.debug(f"PMID {pmid} [{i+1}/{total}]: {status} ({source})")
                logger.debug(f"Downloaded PMID {pmid}: {results[pmid].get('source')}")

                # Rate limiting delay
                await asyncio.sleep(1.0)

            except Exception as e:
                logger.debug(f"PMID {pmid} [{i+1}/{total}]: EXCEPTION {e}")
                logger.warning(f"Failed to download PMID {pmid}: {e}")
                results[pmid] = {"success": False, "error": str(e)}

        successful = sum(1 for r in results.values() if r.get("success"))
        logger.debug(f"download_papers_for_rag: DONE - {successful}/{len(results)} successful")

        # Verify actual files exist (final sanity check)
        existing_files = await asyncio.to_thread(_glob_files, output_dir_abs, "pmid_*.txt")
        logger.debug(f"download_papers_for_rag: ACTUAL FILES in {output_dir_abs}: {len(existing_files)}")
        if len(existing_files) != successful:
            logger.warning(f"Mismatch: {successful} reported vs {len(existing_files)} actual files")
            logger.warning(
                f"File count mismatch: {successful} reported successful, "
                f"but {len(existing_files)} files found in {output_dir_abs}"
            )

    except Exception as e:
        logger.debug(f"download_papers_for_rag: CONNECTION EXCEPTION {type(e).__name__}: {e}")
        logger.error(f"pubmed-download MCP connection failed: {e}")

    return results


# =============================================================================
# Vector DB Indexing
# =============================================================================
async def index_papers_to_vectordb(
    file_paths: list[str],
    collection_name: str,
) -> dict:
    """Index downloaded papers into langconnect-rag vector DB.

    Uses stdio transport (same as st_pipeline_info_agent.py).

    Args:
        file_paths: List of paper file paths to index
        collection_name: Part name (e.g., "part1", "part2", "liana")

    Returns:
        {"success": bool, "collection_id": str, "indexed_count": int}
    """
    full_collection_name = f"{RAG_COLLECTION_PREFIX}{collection_name}"
    logger.debug(f"index_papers_to_vectordb: {len(file_paths)} files, collection={full_collection_name}")

    try:
        logger.debug(f"index_papers_to_vectordb: connecting via cached stdio transport")
        tools = await _get_cci_rag_tools()
        logger.debug(f"index_papers_to_vectordb: got {len(tools)} tools")

        # Find required tools
        tools_map = {}
        for tool_obj in tools:
            name = getattr(tool_obj, 'name', '')
            if 'create_collection' in name:
                tools_map['create'] = tool_obj
            elif 'add_documents_from_files' in name:
                tools_map['add_docs'] = tool_obj
            elif 'list_collections' in name:
                tools_map['list'] = tool_obj
            elif 'delete_collection' in name:
                tools_map['delete'] = tool_obj

        if 'add_docs' not in tools_map:
            logger.debug(f"index_papers_to_vectordb: add_documents_from_files NOT FOUND")
            logger.error("add_documents_from_files tool not found in langconnect-rag")
            return {"success": False, "error": "add_documents_from_files not found"}

        logger.debug(f"index_papers_to_vectordb: found tools: {list(tools_map.keys())}")

        # Check/create collection
        collection_id = _RAG_STATE["collection_ids"].get(collection_name)

        if collection_id is None and 'list' in tools_map:
            try:
                collections_result = await tools_map['list'].ainvoke({})
                logger.debug(f"list_collections raw result type: {type(collections_result)}")
                logger.debug(f"list_collections content: {collections_result}")

                # Parse collections result
                collections = []
                if isinstance(collections_result, list):
                    for item in collections_result:
                        logger.debug(f"Processing list item: {type(item)}")
                        if isinstance(item, dict):
                            if 'text' in item:
                                # BioMCP/langconnect format - parse JSON from text
                                try:
                                    parsed = json.loads(item['text'])
                                    logger.debug(f"Parsed JSON type: {type(parsed)}")
                                    if isinstance(parsed, list):
                                        collections = parsed
                                        logger.debug(f"Found {len(collections)} collections from JSON list")
                                    elif isinstance(parsed, dict) and 'collections' in parsed:
                                        collections = parsed['collections']
                                        logger.debug(f"Found {len(collections)} collections from JSON dict")
                                    elif isinstance(parsed, dict) and ('id' in parsed or 'name' in parsed):
                                        # Single collection object
                                        collections.append(parsed)
                                        logger.debug(f"Added single collection from JSON")
                                except json.JSONDecodeError as e:
                                    logger.debug(f"JSON decode failed: {e}")
                                    logger.debug(f"Raw text: {item['text'][:200]}..." if len(item['text']) > 200 else f"Raw text: {item['text']}")
                            elif 'id' in item or 'name' in item:
                                # Direct collection object
                                collections.append(item)
                                logger.debug(f"Added direct collection item: {item.get('name')}")
                elif isinstance(collections_result, dict):
                    if 'collections' in collections_result:
                        collections = collections_result.get('collections', [])
                    elif 'id' in collections_result and 'name' in collections_result:
                        # Single collection returned
                        collections = [collections_result]
                    logger.debug(f"Parsed from dict: {len(collections)} collections")

                logger.debug(f"Total collections found: {len(collections)}")
                for col in collections:
                    logger.debug(f"Checking collection: {col}")
                    if isinstance(col, dict) and col.get("name") == full_collection_name:
                        collection_id = col.get("id")
                        _RAG_STATE["collection_ids"][collection_name] = collection_id
                        logger.debug(f"Found existing collection: {full_collection_name} (id: {collection_id})")
                        logger.info(f"Found existing collection: {full_collection_name}")
                        # Early return - skip re-indexing existing collection
                        return {
                            "success": True,
                            "collection_id": collection_id,
                            "collection_name": full_collection_name,
                            "indexed_count": 0,
                            "chunk_ids": [],
                            "already_indexed": True,
                            "message": f"Collection already exists: {full_collection_name}",
                        }

                logger.debug(f"Collection {full_collection_name} not found in existing collections")
            except Exception as e:
                logger.warning(
                    "Error listing collections for '%s': %r (%s)",
                    full_collection_name, e, type(e).__name__,
                    exc_info=True,
                )

        if collection_id is None and 'create' in tools_map:
            try:
                result = await tools_map['create'].ainvoke({
                    "name": full_collection_name,
                    "metadata_json": json.dumps({
                        "type": "literature_rag",
                        "created_by": "deep_interpreter",
                    })
                })

                # Parse create result
                if isinstance(result, dict):
                    collection_id = result.get("id")
                elif isinstance(result, list) and len(result) > 0:
                    item = result[0]
                    if isinstance(item, dict):
                        if 'text' in item:
                            text = item['text']
                            try:
                                data = json.loads(text)
                                collection_id = data.get("id")
                            except json.JSONDecodeError:
                                # Try to extract UUID after "ID: " (langconnect format)
                                match = re.search(r'ID:\s*([a-f0-9-]{36})', text)
                                if match:
                                    collection_id = match.group(1)
                                else:
                                    # Fallback: Try JSON-style "id": "..."
                                    match = re.search(r'"id"\s*:\s*"([^"]+)"', text)
                                    if match:
                                        collection_id = match.group(1)
                        else:
                            collection_id = item.get("id")

                if collection_id:
                    _RAG_STATE["collection_ids"][collection_name] = collection_id
                    logger.info(f"Created collection: {full_collection_name} (id: {collection_id})")
            except Exception as e:
                logger.error(
                    "Error creating collection '%s': %r (%s)",
                    full_collection_name, e, type(e).__name__,
                    exc_info=True,
                )

        if collection_id is None:
            logger.error("Failed to parse collection_id from create response: %r", result)
            return {"success": False, "error": "Could not create/find collection"}

        # Index papers
        result = await tools_map['add_docs'].ainvoke({
            "collection_id": collection_id,
            "file_paths": file_paths,
            "chunk_size": 1000,
            "chunk_overlap": 200,
        })

        # Parse indexing result
        chunk_ids = []
        if isinstance(result, dict):
            chunk_ids = result.get("added_chunk_ids", [])
        elif isinstance(result, list) and len(result) > 0:
            item = result[0]
            if isinstance(item, dict):
                if 'text' in item:
                    try:
                        data = json.loads(item['text'])
                        chunk_ids = data.get("added_chunk_ids", [])
                    except json.JSONDecodeError:
                        pass
                else:
                    chunk_ids = item.get("added_chunk_ids", [])

        logger.debug(f"index_papers_to_vectordb: SUCCESS - {len(file_paths)} papers, {len(chunk_ids)} chunks")
        logger.info(f"Indexed {len(file_paths)} papers to {full_collection_name}")

        return {
            "success": True,
            "collection_id": collection_id,
            "collection_name": full_collection_name,
            "indexed_count": len(file_paths),
            "chunk_ids": chunk_ids,
        }

    except Exception as e:
        logger.debug(f"index_papers_to_vectordb: EXCEPTION {type(e).__name__}: {e}")
        logger.error(f"Indexing failed: {e}")
        return {"success": False, "error": str(e)}


# =============================================================================
# RAG Search
# =============================================================================
async def _lookup_collection_from_db(collection_name: str) -> str | None:
    """Look up collection ID from Vector DB by name.

    Fallback when collection_id is not in memory cache (_RAG_STATE).
    This happens after server restart when collections still exist in DB.

    Args:
        collection_name: Part name (e.g., "part1", "part2")

    Returns:
        Collection ID if found, None otherwise
    """
    full_collection_name = f"{RAG_COLLECTION_PREFIX}{collection_name}"
    logger.debug(f"_lookup_collection_from_db: looking for {full_collection_name}")

    try:
        tools = await _get_cci_rag_tools()

        list_tool = None
        for tool_obj in tools:
            if hasattr(tool_obj, 'name') and 'list_collections' in tool_obj.name:
                list_tool = tool_obj
                break

        if list_tool is None:
            logger.debug(f"_lookup_collection_from_db: list_collections tool not found")
            return None

        collections_result = await list_tool.ainvoke({})
        logger.debug(f"_lookup_collection_from_db: raw result type: {type(collections_result)}")

        # Parse collections result (same logic as index_papers_to_vectordb)
        collections = []
        if isinstance(collections_result, list):
            for item in collections_result:
                if isinstance(item, dict):
                    if 'text' in item:
                        try:
                            parsed = json.loads(item['text'])
                            if isinstance(parsed, list):
                                collections = parsed
                            elif isinstance(parsed, dict) and 'collections' in parsed:
                                collections = parsed['collections']
                            elif isinstance(parsed, dict) and ('id' in parsed or 'name' in parsed):
                                collections.append(parsed)
                        except json.JSONDecodeError as e:
                            logger.debug(f"_lookup_collection_from_db: JSON decode failed: {e}")
                    elif 'id' in item or 'name' in item:
                        collections.append(item)
        elif isinstance(collections_result, dict):
            if 'collections' in collections_result:
                collections = collections_result.get('collections', [])
            elif 'id' in collections_result and 'name' in collections_result:
                collections = [collections_result]

        logger.debug(f"_lookup_collection_from_db: found {len(collections)} collections")

        for col in collections:
            if isinstance(col, dict) and col.get("name") == full_collection_name:
                collection_id = col.get("id")
                logger.debug(f"_lookup_collection_from_db: FOUND {full_collection_name} -> {collection_id}")
                return collection_id

        logger.debug(f"_lookup_collection_from_db: {full_collection_name} NOT FOUND in DB")
        return None

    except Exception as e:
        logger.debug(f"_lookup_collection_from_db EXCEPTION: {type(e).__name__}: {e}")
        logger.debug(f"Error looking up collection from DB: {e}")
        return None


async def _search_single_query(
    query: str,
    collection_id: str,
    limit: int,
    search_type: str,
) -> list[dict]:
    """Internal single-query search (no multi_query).

    This is the low-level search function that directly calls the MCP server.
    Used by search_fulltext_rag for each query in multi-query mode.

    Args:
        query: Search query string
        collection_id: Vector DB collection ID
        limit: Maximum results to return
        search_type: "semantic", "keyword", or "hybrid"

    Returns:
        List of normalized search results
    """
    try:
        tools = await _get_cci_rag_tools()

        search_tool = None
        for tool_obj in tools:
            if hasattr(tool_obj, 'name') and 'search_documents' in tool_obj.name:
                search_tool = tool_obj
                break

        if search_tool is None:
            return []

        result = await search_tool.ainvoke({
            "collection_id": collection_id,
            "query": query,
            "limit": limit,
            "search_type": search_type,
        })

        # Debug: Log raw MCP response structure
        logger.debug(f"_search_single_query: raw MCP result type = {type(result)}")
        if isinstance(result, list) and len(result) > 0:
            first_item = result[0]
            logger.debug(f"_search_single_query: first raw item type = {type(first_item)}")
            if isinstance(first_item, dict):
                logger.debug(f"_search_single_query: first raw item keys = {list(first_item.keys())}")
                if 'text' in first_item:
                    # Log first 300 chars of text to see JSON structure
                    text_preview = first_item['text'][:300] if len(first_item['text']) > 300 else first_item['text']
                    logger.debug(f"_search_single_query: raw text preview = {text_preview}")

        # Parse search results
        results = []
        if isinstance(result, list):
            for item in result:
                if isinstance(item, dict):
                    if 'text' in item:
                        text_content = item['text']
                        try:
                            data = json.loads(text_content)
                            if isinstance(data, dict) and 'results' in data:
                                for d in data['results']:
                                    results.append(_normalize_search_result(d))
                            elif isinstance(data, list):
                                for d in data:
                                    results.append(_normalize_search_result(d))
                            else:
                                results.append(_normalize_search_result(data))
                        except json.JSONDecodeError:
                            results.append({
                                "page_content": text_content,
                                "metadata": {},
                                "score": 0.5,
                            })
                    elif 'content' in item:
                        results.append(_normalize_search_result(item))
                    elif 'page_content' in item:
                        results.append(_normalize_search_result(item))
        elif isinstance(result, dict):
            raw_results = result.get("results", [result])
            for r in raw_results:
                results.append(_normalize_search_result(r))

        # Debug: Log parsed results summary
        if results:
            logger.debug(f"_search_single_query: num results = {len(results)}")
            first = results[0]
            logger.debug(f"_search_single_query: first result keys = {list(first.keys())}")
            logger.debug(f"_search_single_query: first result score = {first.get('score', 'MISSING')}")

        return results

    except Exception as e:
        logger.warning(f"Single query search failed: {e}")
        return []


async def search_fulltext_rag(
    query: str,
    collection_name: str,
    limit: int = 10,
    search_type: str = "hybrid",
) -> list[dict]:
    """Search indexed papers using multi-query semantic/hybrid search.

    Always uses multi-query approach:
    1. Generate 5 diverse queries from input using LLM
    2. Search with each query (limit=3 per query, max 15 candidates)
    3. Deduplicate by content, keep highest score
    4. Return top results up to limit

    Args:
        query: Search query (biological mechanism, gene function, etc.)
        collection_name: Part name (e.g., "part1", "part2")
        limit: Maximum results to return
        search_type: "semantic", "keyword", or "hybrid"

    Returns:
        List of relevant chunks:
        [{"page_content": str, "metadata": dict, "score": float}]
    """
    query_preview = query[:50] + "..." if len(query) > 50 else query
    logger.debug(f"search_fulltext_rag: query={query_preview}, collection={collection_name}")

    collection_id = _RAG_STATE["collection_ids"].get(collection_name)

    # Fallback: look up from Vector DB if not in cache
    if collection_id is None:
        logger.debug(f"search_fulltext_rag: Collection {collection_name} not in cache, looking up from DB...")
        collection_id = await _lookup_collection_from_db(collection_name)
        if collection_id:
            _RAG_STATE["collection_ids"][collection_name] = collection_id
            logger.debug(f"search_fulltext_rag: Found collection in DB and cached: {collection_id}")

    if collection_id is None:
        logger.debug(f"search_fulltext_rag: Collection {collection_name} not found in cache or DB")
        logger.warning(f"Collection {collection_name} not indexed")
        return []

    logger.debug(f"search_fulltext_rag: Using collection_id: {collection_id}")

    # Generate multiple search queries using LLM
    queries = await generate_multi_query(query, num_queries=5)
    logger.debug(f"search_fulltext_rag: generated {len(queries)} queries")

    # Search with each query and collect all results
    all_results = []
    for i, q in enumerate(queries):
        q_preview = q[:50] + "..." if len(q) > 50 else q
        logger.debug(f"search_fulltext_rag: searching query {i+1}/{len(queries)}: {q_preview}")
        results = await _search_single_query(q, collection_id, limit=3, search_type=search_type)
        all_results.extend(results)
        logger.debug(f"  -> got {len(results)} results (total: {len(all_results)})")

    logger.debug(f"search_fulltext_rag: total {len(all_results)} results from multi-query")

    # Deduplicate by content (keep highest score)
    seen = {}
    for r in all_results:
        key = hash(r.get("page_content", "")[:200])
        if key not in seen or r.get("score", 0) > seen[key].get("score", 0):
            seen[key] = r

    results = list(seen.values())
    results.sort(key=lambda x: x.get("score", 0), reverse=True)
    logger.debug(f"search_fulltext_rag: {len(results)} unique results after dedup")

    return results[:limit]


# =============================================================================
# Multi-Query Generation for Better RAG Search
# =============================================================================
async def generate_multi_query(claim: str, num_queries: int = 5) -> list[str]:
    """Generate multiple search queries from a claim using LLM.

    Uses langconnect-rag MCP server's multi_query tool to generate
    diverse queries that improve recall in semantic search.

    Args:
        claim: The biological claim to search for
        num_queries: Maximum number of queries to generate (default: 5)

    Returns:
        List of search queries (including original claim as fallback)
    """
    logger.debug(f"generate_multi_query: claim={claim[:50]}...")

    try:
        tools = await _get_cci_rag_tools()

        # Find multi_query tool
        multi_query_tool = None
        for tool_obj in tools:
            if hasattr(tool_obj, 'name') and 'multi_query' in tool_obj.name:
                multi_query_tool = tool_obj
                break

        if multi_query_tool is None:
            logger.debug(f"generate_multi_query: multi_query tool NOT FOUND, fallback to original claim")
            return [claim]

        logger.debug(f"generate_multi_query: calling multi_query tool...")
        result = await multi_query_tool.ainvoke({"question": claim})

        # Parse result - multi_query returns list of queries
        queries = []
        if isinstance(result, list):
            for item in result:
                if isinstance(item, dict) and 'text' in item:
                    try:
                        parsed = json.loads(item['text'])
                        if isinstance(parsed, list):
                            queries.extend(parsed)
                        elif isinstance(parsed, dict) and 'queries' in parsed:
                            queries.extend(parsed['queries'])
                        elif isinstance(parsed, dict) and 'error' in parsed:
                            # MCP tool returned error - log and skip
                            logger.debug(f"generate_multi_query: MCP error: {str(parsed.get('error', ''))[:100]}")
                            continue
                        else:
                            queries.append(str(parsed))
                    except json.JSONDecodeError:
                        # Plain text - might be newline separated
                        text = item['text']
                        if '\n' in text:
                            queries.extend([q.strip() for q in text.split('\n') if q.strip()])
                        else:
                            queries.append(text)
                elif isinstance(item, str):
                    queries.append(item)
        elif isinstance(result, dict):
            if 'error' in result:
                # MCP tool returned error at top level
                logger.debug(f"generate_multi_query: MCP top-level error: {str(result.get('error', ''))[:100]}")
            elif 'queries' in result:
                queries = result['queries']
            elif 'text' in result:
                try:
                    parsed = json.loads(result['text'])
                    if isinstance(parsed, list):
                        queries = parsed
                    elif isinstance(parsed, dict) and 'error' in parsed:
                        logger.debug(f"generate_multi_query: MCP error in text: {str(parsed.get('error', ''))[:100]}")
                except json.JSONDecodeError:
                    pass

        # Filter out non-string or error-like queries (e.g., stringified error dicts)
        queries = [q for q in queries if isinstance(q, str) and not q.startswith('{') and len(q) > 5]

        # Limit to num_queries and ensure we have at least the original claim
        queries = queries[:num_queries] if queries else [claim]
        logger.debug(f"generate_multi_query: generated {len(queries)} valid queries")
        for i, q in enumerate(queries):
            logger.debug(f"  Query {i+1}: {q[:60]}...")

        return queries

    except Exception as e:
        logger.debug(f"generate_multi_query EXCEPTION: {type(e).__name__}: {e}")
        logger.warning(f"multi_query generation failed: {e}, using original claim")
        return [claim]


# =============================================================================
# Claim Validation with RAG
# =============================================================================
async def validate_claim_with_rag(
    claim: str,
    pmid: str,
    collection_name: str,
) -> dict:
    """Validate a claim against full-text paper content using RAG.

    Uses search_fulltext_rag which internally applies multi-query:
    1. search_fulltext_rag generates 5 diverse queries
    2. Searches with each query (3 results per query, max 15)
    3. Deduplicates by content, keeps highest score
    4. This function filters by PMID and returns best match

    Args:
        claim: The biological claim to validate
        pmid: PMID of the cited paper
        collection_name: Part name for the collection

    Returns:
        {
            "valid": bool,
            "confidence": float (0-1),
            "supporting_text": str,
            "source": "full_text" | "abstract"
        }
    """
    # DEBUG: Entry point
    claim_preview = claim[:50] + "..." if len(claim) > 50 else claim
    logger.debug(f"validate_claim_with_rag: claim={claim_preview}, pmid={pmid}, collection={collection_name}")

    # search_fulltext_rag now handles multi-query internally
    # Request more results to allow PMID filtering
    results = await search_fulltext_rag(
        query=claim,
        collection_name=collection_name,
        limit=15,
        search_type="hybrid",
    )

    logger.debug(f"validate_claim_with_rag: got {len(results)} results from search_fulltext_rag")

    # DEBUG: Log metadata structure of results
    if results:
        logger.debug(f"validate_claim_with_rag: First result keys: {list(results[0].keys())}")
        logger.debug(f"validate_claim_with_rag: First result metadata: {results[0].get('metadata', {})}")

    # Filter by PMID if metadata available
    # langconnect-rag stores filename in metadata (e.g., "pmid_12345678.txt")
    relevant_chunks = []
    for r in results:
        metadata = r.get("metadata", {})
        page_content = r.get("page_content", "")

        # Check multiple possible PMID locations:
        # 1. filename in metadata (e.g., "pmid_12345678.txt" or "/path/to/pmid_12345678.txt")
        filename = metadata.get("filename", "") or metadata.get("source", "") or metadata.get("file_path", "")
        # 2. Check stringified metadata for PMID
        metadata_str = str(metadata).lower()

        pmid_found = (
            pmid in filename or
            f"pmid_{pmid}" in filename.lower() or
            f"pmid_{pmid}" in metadata_str or
            pmid in metadata_str
        )

        if pmid_found:
            relevant_chunks.append(r)
            logger.debug(f"validate_claim_with_rag: PMID {pmid} MATCHED in filename={filename[:50]}...")

    logger.debug(f"validate_claim_with_rag: {len(relevant_chunks)} PMID-specific chunks found")

    # If no PMID-specific results, use all results (less strict)
    if not relevant_chunks:
        relevant_chunks = results[:3]
        logger.debug(f"validate_claim_with_rag: using top {len(relevant_chunks)} results (no PMID match)")

    if relevant_chunks:
        # Sort by score descending
        relevant_chunks_sorted = sorted(
            relevant_chunks,
            key=lambda x: x.get("score", 0),
            reverse=True
        )
        best_match = relevant_chunks_sorted[0]
        confidence = best_match.get("score", 0)

        logger.debug(f"validate_claim_with_rag: best_match score raw = {confidence}")

        # If score is 0 or missing, estimate confidence based on text length
        # (longer matching text from the right paper = higher confidence)
        if confidence == 0 and best_match.get("page_content"):
            content_len = len(best_match.get("page_content", ""))
            # Heuristic: 400+ chars = 0.6, 1000+ = 0.7, 1800+ = 0.85 (raised cap)
            confidence = min(0.85, 0.4 + (content_len / 2000))
            logger.debug(f"validate_claim_with_rag: estimated confidence from text length ({content_len}) = {confidence}")

        # Normalize confidence if it's outside 0-1 range
        if confidence > 1:
            confidence = min(confidence / 100, 1.0)

        result = {
            "valid": True,
            "confidence": round(confidence, 3),
            "supporting_text": best_match.get("page_content", "")[:500],
            "source": "full_text",
        }
        logger.debug(f"validate_claim_with_rag: returning valid={result['valid']}, confidence={result['confidence']}")
        return result

    result = {
        "valid": False,
        "confidence": 0.0,
        "supporting_text": "",
        "source": "full_text",
        "message": "No supporting text found in full paper",
    }
    logger.debug(f"validate_claim_with_rag: returning valid={result['valid']}, confidence={result['confidence']}")
    return result


# =============================================================================
# High-Level Integration Function
# =============================================================================
async def prepare_rag_for_interpretation(
    papers_json_path: str,
    part_name: str = "part1",
    data_dir: str = "",
) -> dict:
    """Prepare RAG infrastructure for interpretation generation.

    Call this at the start of INTERPRETER workflow for each part.

    Args:
        papers_json_path: Path to res/part*_papers.json
        part_name: "part1", "part2", "part3", or "liana"
        data_dir: Explicit data directory for paper downloads. Falls back
            to DEFAULT_PAPERS_DIR.

    Returns:
        {
            "rag_mode": bool,
            "collection_id": str | None,
            "papers_count": int,
            "fulltext_count": int,
            "message": str
        }
    """
    logger.debug(f"prepare_rag_for_interpretation START")

    # Check RAG availability
    logger.debug(f"Checking RAG availability...")
    rag_available = await check_rag_availability()
    logger.debug(f"RAG available: {rag_available}")

    if not rag_available:
        logger.debug(f"RAG not available - returning Abstract mode")
        return {
            "rag_mode": False,
            "collection_id": None,
            "papers_count": 0,
            "fulltext_count": 0,
            "message": "RAG not available, using Abstract mode",
        }

    # Resolve virtual/relative path to real OS path
    resolved_path = await asyncio.to_thread(_resolve_papers_path, papers_json_path)
    logger.debug(f"Resolved papers path: {papers_json_path} -> {resolved_path}")

    # Load papers from JSON (async-safe, with LLM error repair)
    logger.debug(f"Loading papers from: {resolved_path}")
    try:
        data = await asyncio.to_thread(_read_json_file, resolved_path)
        papers = data.get("papers", data) if isinstance(data, dict) else data
        logger.debug(f"Papers loaded: {type(papers)}, count: {len(papers) if isinstance(papers, list) else 'N/A'}")
    except FileNotFoundError:
        logger.debug(f"ERROR: Papers file not found: {resolved_path} (original: {papers_json_path})")
        return {
            "rag_mode": False,
            "collection_id": None,
            "papers_count": 0,
            "fulltext_count": 0,
            "message": f"Papers file not found: {resolved_path} (original: {papers_json_path})",
        }
    except json.JSONDecodeError as e:
        logger.debug(f"ERROR: JSON decode failed: {e}")
        return {
            "rag_mode": False,
            "collection_id": None,
            "papers_count": 0,
            "fulltext_count": 0,
            "message": f"Failed to parse papers JSON: {e}",
        }
    except Exception as e:
        logger.debug(f"ERROR: Load failed: {e}")
        return {
            "rag_mode": False,
            "collection_id": None,
            "papers_count": 0,
            "fulltext_count": 0,
            "message": f"Failed to load papers: {e}",
        }

    # Extract PMIDs
    pmids = []
    if isinstance(papers, list):
        pmids = [p.get("pmid") for p in papers if isinstance(p, dict) and p.get("pmid")]
    elif isinstance(papers, dict):
        pmids = [papers.get("pmid")] if papers.get("pmid") else []

    logger.debug(f"Extracted PMIDs: {len(pmids)}")
    if pmids:
        logger.debug(f"First 5 PMIDs: {pmids[:5]}")

    if not pmids:
        logger.debug(f"ERROR: No PMIDs found")
        return {
            "rag_mode": False,
            "collection_id": None,
            "papers_count": 0,
            "fulltext_count": 0,
            "message": "No PMIDs found in papers",
        }

    # Resolve download directory: data_dir/papers/{part_name}/ or fallback
    if not data_dir:
        data_dir = os.getenv("DEEP_INTERPRETER_DATA_DIR", "")
    if data_dir:
        data_dir = str(Path(data_dir).expanduser().resolve())
        papers_output_dir = os.path.join(data_dir, "papers", part_name)
    else:
        papers_output_dir = DEFAULT_PAPERS_DIR

    # Download papers
    logger.debug(f"Downloading {len(pmids)} papers to {papers_output_dir}...")
    download_results = await download_papers_for_rag(pmids, output_dir=papers_output_dir)
    successful_paths = [
        r["file_path"]
        for r in download_results.values()
        if r.get("success") and r.get("file_path")
    ]
    logger.debug(f"Download results: {len(successful_paths)}/{len(pmids)} successful")

    if not successful_paths:
        logger.debug(f"ERROR: No papers downloaded")
        return {
            "rag_mode": False,
            "collection_id": None,
            "papers_count": len(pmids),
            "fulltext_count": 0,
            "message": "No papers downloaded successfully, using Abstract mode",
        }

    # Index to Vector DB
    logger.debug(f"Indexing {len(successful_paths)} papers to VectorDB...")
    index_result = await index_papers_to_vectordb(successful_paths, part_name)
    logger.debug(f"Index result: success={index_result.get('success')}, collection_id={index_result.get('collection_id')}")

    if not index_result.get("success"):
        logger.debug(f"ERROR: Indexing failed: {index_result.get('error')}")
        return {
            "rag_mode": False,
            "collection_id": None,
            "papers_count": len(pmids),
            "fulltext_count": len(successful_paths),
            "message": f"Indexing failed: {index_result.get('error')}, using Abstract mode",
        }

    fulltext_ratio = len(successful_paths) / len(pmids) if pmids else 0

    logger.debug(f"RAG preparation SUCCESS!")
    logger.debug(f"rag_mode=True, papers={len(pmids)}, fulltext={len(successful_paths)}, ratio={fulltext_ratio:.2f}")

    return {
        "rag_mode": True,
        "collection_id": index_result.get("collection_id"),
        "collection_name": part_name,
        "papers_count": len(pmids),
        "fulltext_count": len(successful_paths),
        "fulltext_ratio": round(fulltext_ratio, 2),
        "message": f"RAG ready: {len(successful_paths)}/{len(pmids)} papers indexed",
    }


# =============================================================================
# Tool Exports for LangGraph
# =============================================================================

@tool
def prepare_rag_literature(
    papers_json_path: str,
    part_name: str = "part1",
    data_dir: str = "",
) -> dict:
    """Prepare RAG infrastructure for literature-grounded interpretation.

    Downloads full-text papers and indexes them for semantic search.
    Falls back to Abstract mode if Docker/RAG unavailable.

    Args:
        papers_json_path: Path to papers JSON (e.g., "res/papers.json")
        part_name: Part identifier ("all", "part1", "part2", "part3", "synthesis")
        data_dir: Explicit data directory for resolving papers path. Read from
            /data_path.txt (written by PLANNER). Falls back to contextvars if empty.

    Returns:
        RAG preparation result with:
        - rag_mode: bool - Whether RAG mode is active
        - collection_id: str | None - Vector DB collection ID
        - papers_count: int - Total papers attempted
        - fulltext_count: int - Papers successfully indexed
        - fulltext_ratio: float - Ratio of successful downloads
        - message: str - Status message
    """
    # DEBUG: Entry point
    logger.debug("=" * 60)
    logger.debug("prepare_rag_literature CALLED")
    logger.debug(f"papers_json_path: {papers_json_path}")
    logger.debug(f"part_name: {part_name}")
    logger.debug(f"data_dir: {data_dir}")
    logger.debug("=" * 60)

    # Resolve path using explicit data_dir before entering async
    resolved_path = _resolve_papers_path(papers_json_path, data_dir=data_dir)
    logger.debug(f"Resolved papers path: {papers_json_path} -> {resolved_path}")

    try:
        result = run_async(
            prepare_rag_for_interpretation(resolved_path, part_name, data_dir=data_dir),
            timeout=300,
        )

        logger.debug(f"prepare_rag_literature RESULT: rag_mode={result.get('rag_mode')}, "
                      f"papers={result.get('papers_count')}, fulltext={result.get('fulltext_count')}")

        return result
    except Exception as e:
        logger.error(f"RAG preparation failed: {type(e).__name__}: {e}")
        return {
            "rag_mode": False,
            "collection_id": None,
            "papers_count": 0,
            "fulltext_count": 0,
            "message": f"RAG preparation failed: {e}",
        }


@tool
def search_literature_fulltext(
    query: str,
    part_name: str = "part1",
    limit: int = 5,
) -> list[dict]:
    """Search full-text papers using semantic search (RAG mode only).

    Args:
        query: Search query (biological term, mechanism, etc.)
        part_name: Part identifier for collection lookup
        limit: Maximum results to return

    Returns:
        List of relevant text chunks with:
        - page_content: str - The matching text passage
        - metadata: dict - Source information
        - score: float - Relevance score
    """
    # DEBUG: Entry point
    logger.debug("=" * 60)
    logger.debug("search_literature_fulltext CALLED")
    logger.debug(f"query: {query[:50]}..." if len(query) > 50 else f"query: {query}")
    logger.debug(f"part_name: {part_name}")
    logger.debug(f"limit: {limit}")
    logger.debug(f"_RAG_STATE['available']: {_RAG_STATE.get('available')}")
    logger.debug(f"_RAG_STATE['collection_ids']: {_RAG_STATE.get('collection_ids')}")
    logger.debug("=" * 60)

    # Check if availability has been initialized
    if _RAG_STATE.get("available") is None:
        logger.debug("search_literature_fulltext: RAG availability not initialized, checking now...")
        check_rag_availability_sync()
        logger.debug(f"search_literature_fulltext: After init, available = {_RAG_STATE.get('available')}")

    if not _RAG_STATE.get("available"):
        logger.debug("search_literature_fulltext: RAG not available, returning empty results")
        logger.debug("RAG not available, returning empty results")
        return []

    try:
        result = run_async(search_fulltext_rag(query, part_name, limit), timeout=30)
        logger.debug(f"search_literature_fulltext: returning {len(result)} results")
        return result
    except Exception as e:
        logger.warning(f"Full-text search failed: {type(e).__name__}: {e}")
        return []


@tool
def validate_claim_fulltext(
    claim: str,
    pmid: str,
    part_name: str = "part1",
) -> dict:
    """Validate a biological claim against full-text paper content.

    Uses semantic search to find supporting text in the cited paper.
    Returns validation result with confidence score.

    Args:
        claim: The biological claim to validate
        pmid: PMID of the cited paper
        part_name: Part identifier for collection lookup

    Returns:
        Validation result with:
        - valid: bool - Whether claim is supported
        - confidence: float - Confidence score (0-1)
        - supporting_text: str - Relevant text passage
        - source: str - "full_text" or "abstract"
    """
    # DEBUG: Entry point
    logger.debug("=" * 60)
    logger.debug("validate_claim_fulltext CALLED")
    claim_preview = claim[:80] + "..." if len(claim) > 80 else claim
    logger.debug(f"claim: {claim_preview}")
    logger.debug(f"pmid: {pmid}")
    logger.debug(f"part_name: {part_name}")
    logger.debug(f"_RAG_STATE['available']: {_RAG_STATE.get('available')}")
    logger.debug(f"_RAG_STATE['collection_ids']: {_RAG_STATE.get('collection_ids')}")
    logger.debug("=" * 60)

    # Check if availability has been initialized
    if _RAG_STATE.get("available") is None:
        logger.debug("validate_claim_fulltext: RAG availability not initialized, checking now...")
        check_rag_availability_sync()
        logger.debug(f"validate_claim_fulltext: After init, available = {_RAG_STATE.get('available')}")

    if not _RAG_STATE.get("available"):
        logger.debug("validate_claim_fulltext: RAG not available, returning abstract fallback")
        return {
            "valid": False,
            "confidence": 0.0,
            "supporting_text": "",
            "source": "abstract",
            "message": "RAG not available, use abstract validation",
        }

    try:
        result = run_async(validate_claim_with_rag(claim, pmid, part_name), timeout=30)
        logger.debug(f"validate_claim_fulltext RESULT: valid={result.get('valid')}, "
                      f"confidence={result.get('confidence')}, source={result.get('source')}")
        return result
    except Exception as e:
        logger.warning(f"Full-text claim validation failed: {type(e).__name__}: {e}")
        return {
            "valid": False,
            "confidence": 0.0,
            "supporting_text": "",
            "source": "error",
            "message": str(e),
        }


# =============================================================================
# Utility Functions
# =============================================================================

def get_rag_status() -> dict:
    """Get current RAG status.

    Returns:
        Dictionary with:
        - available: bool | None - RAG availability status
        - collections: dict - Indexed collection IDs by part name
    """
    return {
        "available": _RAG_STATE["available"],
        "collections": dict(_RAG_STATE["collection_ids"]),
    }


def is_rag_mode_active() -> bool:
    """Check if RAG mode is currently active.

    Returns:
        True if RAG is available and at least one collection is indexed
    """
    return (
        _RAG_STATE.get("available") is True
        and len(_RAG_STATE.get("collection_ids", {})) > 0
    )

