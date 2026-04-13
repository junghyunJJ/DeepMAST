"""Shared agent utilities.

NOTE: Intentionally does NOT re-export SkillsMiddleware at package level.
The re-export would chain through shared/skills_middleware.py →
deep_interpreter.middleware.load → deep_interpreter/__init__.py (eager),
booting graph_builder as an import side effect whenever any submodule
of `src.agents.shared` is touched (e.g., `src.agents.shared.skill_reader`).

Consumers that need SkillsMiddleware must import it directly from the
submodule: `from src.agents.shared.skills_middleware import SkillsMiddleware`.
"""

__all__ = []
