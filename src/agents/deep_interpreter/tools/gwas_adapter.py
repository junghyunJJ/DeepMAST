"""GWAS direct adapter for Phase 4.7 therapeutic target assessment.

This module provides a best-effort interface to the GWAS Catalog REST API.
It aggregates disease-trait association rows into per-gene signals using the
`reported + nearest` split required by the hybrid GWAS policy.
"""

from __future__ import annotations

import json
import logging
import math
import re
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

GWAS_REST_BASE = "https://www.ebi.ac.uk/gwas/rest/api"
_TRAIT_ID_RE = re.compile(r"^[A-Z][A-Z0-9]+_[0-9]+$")
_GWAS_DIRECT_TIMEOUT_SECONDS = 30.0


class GwasDirectAdapterError(RuntimeError):
    """Raised when direct GWAS lookup cannot be completed."""


def _safe_float(value: object, default: float = 0.0) -> float:
    """Coerce numbers in mixed API payloads safely."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_efo_id(efo_id: str) -> str:
    """Normalize trait ID string to GWAS Catalog path format."""
    normalized = (efo_id or "").strip()
    if not normalized:
        return ""
    if normalized.startswith("http"):
        normalized = normalized.rsplit("/", 1)[-1]
    normalized = normalized.replace(":", "_").upper()
    if not _TRAIT_ID_RE.match(normalized):
        return ""
    return normalized


def _extract_traits(payload: dict) -> list[dict]:
    """Extract trait rows from HAL response."""
    embedded = payload.get("_embedded", {})
    traits = embedded.get("efoTraits", [])
    if isinstance(traits, list):
        return [row for row in traits if isinstance(row, dict)]
    return []


def _resolve_trait_id_from_disease_name(
    disease: str,
    timeout: float = _GWAS_DIRECT_TIMEOUT_SECONDS,
) -> str:
    """Resolve disease free text to GWAS trait shortForm."""
    disease_name = (disease or "").strip()
    if not disease_name:
        return ""
    url = (
        f"{GWAS_REST_BASE}/efoTraits/search/findByEfoTrait"
        f"?trait={urllib.parse.quote(disease_name)}"
    )
    payload = _fetch_json(url, timeout=timeout)
    traits = _extract_traits(payload)
    if not traits:
        return ""
    short_form = str(traits[0].get("shortForm", "") or "").strip().upper()
    return _normalize_efo_id(short_form)


def _fetch_json(url: str, timeout: float = _GWAS_DIRECT_TIMEOUT_SECONDS) -> dict:
    """Fetch JSON payload from HTTP endpoint."""
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
            "User-Agent": "DeepMAST/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read()
    return json.loads(payload.decode("utf-8"))


def _extract_associations(payload: dict) -> list[dict]:
    """Extract association rows from HAL response."""
    embedded = payload.get("_embedded", {})
    associations = embedded.get("associations", [])
    if isinstance(associations, list):
        return [row for row in associations if isinstance(row, dict)]
    return []


_SYMBOL_TOKEN_RE = re.compile(r"^[A-Z0-9][A-Z0-9_.-]{0,31}$")
_REPORTING_KEYS = {
    "authorreportedgene",
    "authorreportedgenename",
    "authorreportedgenes",
    "reportedgene",
    "reportedgenes",
    "genesymbol",
}
_NEAREST_KEYS = {
    "mappedgene",
    "mappedgenes",
    "nearestgene",
    "nearestgenes",
    "nearestmappedgene",
    "upstreamgene",
    "upstreamgenes",
    "downstreamgene",
    "downstreamgenes",
    "closestgene",
    "functionalgene",
}


def _extract_nearest_from_genomic_contexts(association: dict) -> set[str]:
    """Extract mapped-nearby gene symbols from genomicContexts blocks."""
    nearest: set[str] = set()

    snps = association.get("snps")
    if not isinstance(snps, list):
        return nearest

    for snp in snps:
        if not isinstance(snp, dict):
            continue
        contexts = snp.get("genomicContexts")
        if not isinstance(contexts, list):
            continue
        for context in contexts:
            if not isinstance(context, dict):
                continue
            gene_payload = context.get("gene")
            if not isinstance(gene_payload, dict):
                continue

            symbol = str(gene_payload.get("geneName", "") or "").strip().upper()
            if not symbol or not _SYMBOL_TOKEN_RE.match(symbol):
                continue

            # Treat genomic-context genes as nearest-side evidence. The payload can
            # expose multiple mapped genes, and some diseases have sparse
            # `isClosestGene=True` annotations.
            nearest.add(symbol)
    return nearest


def _extract_reported_and_nearest_symbols(association: dict) -> tuple[set[str], set[str]]:
    """Split association symbols into reported and nearest buckets."""
    reported = _collect_symbols_by_keys(association, _REPORTING_KEYS)
    nearest = _collect_symbols_by_keys(association, _NEAREST_KEYS)
    nearest.update(_extract_nearest_from_genomic_contexts(association))
    nearest.difference_update(reported)
    return reported, nearest


def _iter_association_urls(encoded_efo: str, page: int, page_size: int) -> list[str]:
    """Yield association endpoints from richer to lighter payloads."""
    base = (
        f"{GWAS_REST_BASE}/efoTraits/{encoded_efo}/associations"
        f"?page={page}&size={page_size}"
    )
    return [
        f"{base}&projection=associationByEfoTrait",
        base,
    ]


def _tokenize_symbols(value: object) -> set[str]:
    """Extract possible gene symbol tokens from arbitrary value."""
    symbols: set[str] = set()
    if isinstance(value, str):
        for part in re.split(r"[\s,;|/]+", value.upper()):
            token = part.strip()
            if token and _SYMBOL_TOKEN_RE.match(token):
                symbols.add(token)
    elif isinstance(value, list):
        for item in value:
            symbols.update(_tokenize_symbols(item))
    elif isinstance(value, dict):
        for nested in value.values():
            symbols.update(_tokenize_symbols(nested))
    return symbols


def _collect_symbols_by_keys(data: object, keys: set[str]) -> set[str]:
    """Collect gene symbols by recursively matching key names."""
    symbols: set[str] = set()
    if isinstance(data, dict):
        for key, value in data.items():
            key_norm = str(key).replace("_", "").lower()
            if key_norm in keys:
                symbols.update(_tokenize_symbols(value))
            if isinstance(value, (dict, list)):
                symbols.update(_collect_symbols_by_keys(value, keys))
    elif isinstance(data, list):
        for item in data:
            symbols.update(_collect_symbols_by_keys(item, keys))
    return symbols


def _association_signal(association: dict) -> float:
    """Convert association strength to normalized [0, 1] signal."""
    # If API already provides a normalized score, use it first.
    for field in ("score", "studyScore", "associationScore"):
        score = _safe_float(association.get(field), default=-1.0)
        if score >= 0:
            if score > 1.0:
                return 1.0
            return max(0.0, score)

    # Fallback: derive from p-value.
    p_value = None
    for field in ("pvalue", "pValue", "p_value"):
        raw = association.get(field)
        if raw is None:
            continue
        parsed = _safe_float(raw, default=-1.0)
        if parsed > 0:
            p_value = parsed
            break
    if p_value is None:
        return 0.0

    # 1e-12 and smaller saturate near 1.0.
    return max(0.0, min(1.0, -math.log10(p_value) / 12.0))


def _aggregate_gene_signals(
    associations: list[dict],
    genes: list[str],
) -> dict[str, dict]:
    """Aggregate association rows into per-gene reported/nearest signals."""
    lookup = {gene.upper(): gene for gene in genes}
    reported_buckets: dict[str, list[float]] = {gene: [] for gene in genes}
    nearest_buckets: dict[str, list[float]] = {gene: [] for gene in genes}

    for association in associations:
        signal = _association_signal(association)
        if signal <= 0:
            continue

        reported_symbols, nearest_symbols = _extract_reported_and_nearest_symbols(
            association
        )

        for symbol in reported_symbols:
            gene = lookup.get(symbol)
            if gene:
                reported_buckets[gene].append(signal)

        for symbol in nearest_symbols:
            gene = lookup.get(symbol)
            if gene and symbol not in reported_symbols:
                nearest_buckets[gene].append(signal)

    aggregated: dict[str, dict] = {}
    for gene in genes:
        reported_hits = reported_buckets[gene]
        nearest_hits = nearest_buckets[gene]
        aggregated[gene] = {
            "reported_signal": (
                sum(reported_hits) / len(reported_hits) if reported_hits else 0.0
            ),
            "nearest_signal": (
                sum(nearest_hits) / len(nearest_hits) if nearest_hits else 0.0
            ),
            "reported_hits_count": len(reported_hits),
            "nearest_hits_count": len(nearest_hits),
        }
    return aggregated


def fetch_gwas_direct_gene_scores(
    disease: str,
    genes: list[str],
    efo_id: str | None,
    max_pages: int = 1,
    page_size: int = 200,
    timeout: float = _GWAS_DIRECT_TIMEOUT_SECONDS,
) -> dict[str, dict]:
    """Fetch per-gene GWAS direct signals from GWAS Catalog.

    Args:
        disease: Disease name used for logging only.
        genes: Gene symbols to aggregate.
        efo_id: Disease EFO ID.
        max_pages: Max pages of association rows to scan.
        page_size: Rows per page.
        timeout: HTTP timeout in seconds.

    Returns:
        Dict keyed by gene symbol with fields:
        - reported_signal
        - nearest_signal
        - reported_hits_count
        - nearest_hits_count

    Raises:
        GwasDirectAdapterError: If direct lookup cannot run.
    """
    if not genes:
        return {}

    normalized_efo = _normalize_efo_id(efo_id or "")
    if not normalized_efo:
        try:
            normalized_efo = _resolve_trait_id_from_disease_name(
                disease=disease,
                timeout=timeout,
            )
        except Exception as exc:
            raise GwasDirectAdapterError(
                f"GWAS trait resolve failed for disease '{disease}': {exc}"
            ) from exc
    if not normalized_efo:
        raise GwasDirectAdapterError(
            "GWAS direct lookup requires resolvable trait identifier"
        )

    associations: list[dict] = []
    encoded_efo = urllib.parse.quote(normalized_efo, safe="")
    seen_row_ids: set[str] = set()
    for page in range(max_pages):
        payload = None
        fetch_errors: list[str] = []
        for url in _iter_association_urls(encoded_efo, page, page_size):
            try:
                payload = _fetch_json(url, timeout=timeout)
                break
            except Exception as exc:
                fetch_errors.append(f"{url}: {exc}")

        if payload is None:
            raise GwasDirectAdapterError(
                f"GWAS direct request failed for {normalized_efo}: "
                + " | ".join(fetch_errors)
            )

        page_rows = _extract_associations(payload)
        if not page_rows:
            break

        for row in page_rows:
            links = row.get("_links", {}) if isinstance(row, dict) else {}
            self_href = (
                ((links.get("self", {}) or {}).get("href", ""))
                if isinstance(links, dict)
                else ""
            )
            row_id = str(self_href or "")
            if row_id and row_id in seen_row_ids:
                continue
            if row_id:
                seen_row_ids.add(row_id)
            associations.append(row)

        # GWAS trait associations endpoint may not expose stable page metadata.
        # If pagination info is unavailable, avoid duplicate refetch loops.
        page_meta = payload.get("page", {}) if isinstance(payload, dict) else {}
        if not isinstance(page_meta, dict) or "totalPages" not in page_meta:
            break
        total_pages = int(_safe_float(page_meta.get("totalPages"), default=1))
        if page >= max(total_pages - 1, 0):
            break

    if not associations:
        logger.info(
            "GWAS direct returned no association rows: disease=%s efo=%s",
            disease,
            normalized_efo,
        )
        return {gene: {
            "reported_signal": 0.0,
            "nearest_signal": 0.0,
            "reported_hits_count": 0,
            "nearest_hits_count": 0,
        } for gene in genes}

    return _aggregate_gene_signals(associations=associations, genes=genes)
