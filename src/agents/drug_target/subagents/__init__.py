"""Subagent configurations for Drug Target Assessment Agent."""


def __getattr__(name):
    """Lazy imports to avoid circular dependency during package init."""
    if name in ("get_subagents", "SUBAGENT_CONFIGS"):
        from src.agents.drug_target.subagents.configs import get_subagents, SUBAGENT_CONFIGS
        if name == "get_subagents":
            return get_subagents
        return SUBAGENT_CONFIGS
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["get_subagents", "SUBAGENT_CONFIGS"]
