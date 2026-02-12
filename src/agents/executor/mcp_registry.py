"""MCP Server config registry for pipeline execution steps.

Maps pipeline methods (normalization, celltype_analysis, spatial_clustering)
to their corresponding MCP server configurations. Config-only — never creates
MultiServerMCPClient instances. The executor agent creates clients directly
via ``MultiServerMCPClient(...)`` per step (v0.1.0+ API; context manager
raises ``NotImplementedError``).
"""

from __future__ import annotations

import os
from typing import Any

# ---------------------------------------------------------------------------
# Registry type: dict[method_name_lower, (server_key, config_dict)]
# ---------------------------------------------------------------------------

NORMALIZATION_REGISTRY: dict[str, tuple[str, dict[str, Any]]] = {
    "log": (
        "scanpy-mcp",
        {
            "command": "scanpy-mcp",
            "args": ["--mode", "normalization", "--method", "log"],
            "transport": "stdio",
        },
    ),
    "sctransform": (
        "sctransform-mcp",
        {
            "command": "sctransform-mcp",
            "args": ["--mode", "normalization"],
            "transport": "stdio",
        },
    ),
    "pearson residuals": (
        "scanpy-mcp",
        {
            "command": "scanpy-mcp",
            "args": ["--mode", "normalization", "--method", "pearson_residuals"],
            "transport": "stdio",
        },
    ),
}

CELLTYPE_REGISTRY: dict[str, tuple[str, dict[str, Any]]] = {
    "iris": (
        "iris-mcp",
        {
            "command": "iris-mcp",
            "args": ["--mode", "celltype"],
            "transport": "stdio",
        },
    ),
    "cytetype": (
        "cytetype-mcp",
        {
            "command": "cytetype-mcp",
            "args": ["--mode", "annotation"],
            "transport": "stdio",
        },
    ),
    "cell2location": (
        "cell2location-mcp",
        {
            "command": "cell2location-mcp",
            "args": ["--mode", "deconvolution"],
            "transport": "stdio",
        },
    ),
    "tangram": (
        "tangram-mcp",
        {
            "command": "tangram-mcp",
            "args": ["--mode", "deconvolution"],
            "transport": "stdio",
        },
    ),
}

CLUSTERING_REGISTRY: dict[str, tuple[str, dict[str, Any]]] = {
    "iris": (
        "iris-mcp",
        {
            "command": "iris-mcp",
            "args": ["--mode", "clustering"],
            "transport": "stdio",
        },
    ),
    "leiden": (
        "scanpy-mcp",
        {
            "command": "scanpy-mcp",
            "args": ["--mode", "clustering", "--method", "leiden"],
            "transport": "stdio",
        },
    ),
    "louvain": (
        "scanpy-mcp",
        {
            "command": "scanpy-mcp",
            "args": ["--mode", "clustering", "--method", "louvain"],
            "transport": "stdio",
        },
    ),
    "bayesspace": (
        "bayesspace-mcp",
        {
            "command": "bayesspace-mcp",
            "args": ["--mode", "clustering"],
            "transport": "stdio",
        },
    ),
}

# Convenience mapping: step name -> registry dict
STEP_REGISTRIES: dict[str, dict[str, tuple[str, dict[str, Any]]]] = {
    "normalization": NORMALIZATION_REGISTRY,
    "celltype_analysis": CELLTYPE_REGISTRY,
    "spatial_clustering": CLUSTERING_REGISTRY,
}

# Methods that require a single-cell reference dataset
DECONVOLUTION_METHODS: set[str] = {"iris", "cell2location", "tangram"}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def get_mcp_server_config(
    step: str,
    method: str,
) -> tuple[str, dict[str, Any]]:
    """Look up MCP server config for a pipeline step + method.

    Args:
        step: One of ``"normalization"``, ``"celltype_analysis"``, ``"spatial_clustering"``.
        method: Method name (case-insensitive), e.g. ``"log"``, ``"IRIS"``.

    Returns:
        ``(server_key, config_dict)`` suitable for passing to
        ``MultiServerMCPClient({server_key: config_dict})``.

    Raises:
        KeyError: If *step* or *method* is not found in the registry.
    """
    registry = STEP_REGISTRIES.get(step)
    if registry is None:
        raise KeyError(f"Unknown pipeline step: {step!r}. Valid steps: {list(STEP_REGISTRIES)}")

    entry = registry.get(method.lower())
    if entry is None:
        raise KeyError(
            f"Unknown method {method!r} for step {step!r}. "
            f"Valid methods: {list(registry)}"
        )
    return entry


def is_deconvolution_method(method: str) -> bool:
    """Return ``True`` if *method* requires a single-cell reference dataset."""
    return method.lower() in DECONVOLUTION_METHODS


def get_sc_reference_server_config() -> tuple[str, dict[str, Any]]:
    """Return MCP config for the SC reference recommendation server.

    The server helps users find appropriate single-cell reference datasets
    for deconvolution methods on spot-based platforms.
    """
    sc_ref_command = os.getenv("SC_REF_MCP_COMMAND", "sc-reference-mcp")
    return (
        "sc-reference-mcp",
        {
            "command": sc_ref_command,
            "args": ["--mode", "recommend"],
            "transport": "stdio",
        },
    )


__all__ = [
    "NORMALIZATION_REGISTRY",
    "CELLTYPE_REGISTRY",
    "CLUSTERING_REGISTRY",
    "STEP_REGISTRIES",
    "DECONVOLUTION_METHODS",
    "get_mcp_server_config",
    "is_deconvolution_method",
    "get_sc_reference_server_config",
]
