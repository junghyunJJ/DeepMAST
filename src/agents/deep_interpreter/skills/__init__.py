"""Skills middleware for Deep Interpreter Agent.

This module provides skills middleware for enhancing the Deep Interpreter
with additional capabilities like BioMCP literature search workflow.

Skills follow the biomcp-reference-search pattern:
think → article_searcher → quality validation loop
"""

from typing import Any, Callable, Optional


class DeepInterpreterSkillsMiddleware:
    """Skills middleware for Deep Interpreter.

    This middleware enhances the Deep Interpreter with skills for:
    - Literature search using BioMCP (think → search → validate)
    - Quality validation using reflection-tool
    - Report generation

    Usage:
        middleware = DeepInterpreterSkillsMiddleware()
        # Skills are automatically applied via the DeepAgents framework
    """

    def __init__(
        self,
        biomcp_url: str = "http://0.0.0.0:8000/mcp",
        enable_literature_search: bool = True,
        enable_quality_validation: bool = True,
    ):
        """Initialize skills middleware.

        Args:
            biomcp_url: URL of the BioMCP server
            enable_literature_search: Enable BioMCP literature search
            enable_quality_validation: Enable reflection-tool validation
        """
        self.biomcp_url = biomcp_url
        self.enable_literature_search = enable_literature_search
        self.enable_quality_validation = enable_quality_validation

    def get_skill_handlers(self) -> dict[str, Callable]:
        """Get skill handler functions.

        Returns:
            Dictionary mapping skill names to handler functions
        """
        handlers = {}

        if self.enable_literature_search:
            handlers["literature_search"] = self._literature_search_skill

        if self.enable_quality_validation:
            handlers["quality_validation"] = self._quality_validation_skill

        return handlers

    async def _literature_search_skill(
        self,
        genes: list[str],
        pathways: list[str],
        celltypes: list[str],
        disease: str,
        **kwargs
    ) -> dict:
        """Literature search skill using BioMCP workflow.

        Implements: think → article_searcher → quality validation loop

        Args:
            genes: List of gene names
            pathways: List of pathway names
            celltypes: List of cell types
            disease: Disease context

        Returns:
            Dictionary with papers and coverage analysis
        """
        from src.agents.deep_interpreter.tools.literature import (
            search_literature_for_context_async,
        )

        return await search_literature_for_context_async(
            genes=genes,
            pathways=pathways,
            celltypes=celltypes,
            disease=disease,
            biomcp_url=self.biomcp_url,
        )

    async def _quality_validation_skill(
        self,
        interpretation: str,
        references: list[dict],
        iteration: int = 1,
        **kwargs
    ) -> dict:
        """Quality validation skill using reflection-tool.

        Implements quality loop with max 3 iterations, score >= 0.7.

        Args:
            interpretation: Text to validate
            references: Supporting references
            iteration: Current iteration number

        Returns:
            Dictionary with validation results
        """
        from src.agents.deep_interpreter.tools.quality import validate_quality

        return validate_quality.invoke({
            "interpretation": interpretation,
            "references": references,
            "use_llm": True,
        })


__all__ = [
    "DeepInterpreterSkillsMiddleware",
]
