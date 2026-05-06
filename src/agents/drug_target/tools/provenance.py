"""Provenance and upstream-result helpers for DrugTarget report rendering."""

from __future__ import annotations


def pagination_watermark(
    *, source: str, loaded_count: int | None, limit: int | None
) -> dict:
    """Record whether a paginated upstream result may be capped.

    Equality to the requested limit is treated as a warning because many APIs
    return exactly the requested page size when more rows may exist.
    """
    capped = (
        isinstance(loaded_count, int)
        and isinstance(limit, int)
        and limit > 0
        and loaded_count >= limit
    )
    warning = None
    if capped:
        warning = (
            f"{source} returned {loaded_count} rows, equal to requested limit "
            f"{limit}; count may be incomplete."
        )
    return {
        "source": source,
        "loaded_count": loaded_count,
        "limit": limit,
        "capped": capped,
        "warning": warning,
    }

