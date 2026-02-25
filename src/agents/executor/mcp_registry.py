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
# Dynamic registry (populated at runtime by generate_mcp node)
# ---------------------------------------------------------------------------

_DYNAMIC_REGISTRY: dict[str, dict[str, tuple[str, dict[str, Any]]]] = {
    "normalization": {},
    "celltype_analysis": {},
    "spatial_clustering": {},
}


def register_dynamic_mcp(
    step: str,
    method: str,
    server_key: str,
    config: dict[str, Any],
) -> None:
    """Register a dynamically generated MCP server config at runtime."""
    if step not in _DYNAMIC_REGISTRY:
        raise KeyError(f"Unknown step: {step!r}. Valid: {list(_DYNAMIC_REGISTRY)}")
    _DYNAMIC_REGISTRY[step][method.lower()] = (server_key, config)


def clear_dynamic_registry() -> None:
    """Clear all dynamically registered MCP configs (for testing)."""
    for step_dict in _DYNAMIC_REGISTRY.values():
        step_dict.clear()


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def get_mcp_server_config(
    step: str,
    method: str,
) -> tuple[str, dict[str, Any]]:
    """Look up MCP server config: static registry first, then dynamic.

    Args:
        step: One of "normalization", "celltype_analysis", "spatial_clustering".
        method: Method name (case-insensitive).

    Returns:
        (server_key, config_dict) for MultiServerMCPClient.

    Raises:
        KeyError: If not found in either registry.
    """
    method_lower = method.lower()

    # 1. Static registry
    static_reg = STEP_REGISTRIES.get(step)
    if static_reg:
        entry = static_reg.get(method_lower)
        if entry is not None:
            return entry

    # 2. Dynamic registry
    dynamic_reg = _DYNAMIC_REGISTRY.get(step, {})
    entry = dynamic_reg.get(method_lower)
    if entry is not None:
        return entry

    # 3. Not found
    all_methods = list((static_reg or {}).keys()) + list(dynamic_reg.keys())
    raise KeyError(
        f"Unknown method {method!r} for step {step!r}. "
        f"Available methods: {all_methods}"
    )


def has_mcp_server_config(step: str, method: str) -> bool:
    """Check if an MCP config exists for step+method (static or dynamic)."""
    try:
        get_mcp_server_config(step, method)
        return True
    except KeyError:
        return False


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


def get_visium_ref_selector_config() -> tuple[str, dict[str, Any]]:
    """Return MCP config for the Visium reference selector server.

    Uses OTT-JAX optimal transport to rank SC reference datasets.
    """
    python_path = os.getenv(
        "VISIUM_REF_MCP_PYTHON",
        "python",
    )
    server_path = os.getenv(
        "VISIUM_REF_MCP_PATH",
        "/Users/jungj2/Dropbox/Metadata/mcp/visium_reference_selector_mcp",
    )
    return (
        "visium-reference-selector",
        {
            "command": python_path,
            "args": ["-m", "visium_reference_selector.server"],
            "env": {"PYTHONPATH": f"{server_path}/src"},
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
    "has_mcp_server_config",
    "is_deconvolution_method",
    "get_sc_reference_server_config",
    "get_visium_ref_selector_config",
    "register_dynamic_mcp",
    "clear_dynamic_registry",
]
