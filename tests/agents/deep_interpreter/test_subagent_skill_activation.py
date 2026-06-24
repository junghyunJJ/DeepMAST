"""Deep Interpreter skill activation wiring regression tests."""

from src.agents.deep_interpreter.subagents.configs import get_subagents
from src.agents.shared.skill_activator import SkillActivator


def _tool_names(subagent: dict) -> set[str]:
    return {
        getattr(tool, "name", getattr(tool, "__name__", repr(tool)))
        for tool in subagent.get("tools", [])
    }


def test_progressive_disclosure_uses_local_skill_activator_not_native_deepagents_skills():
    """Avoid Deep Agents native SkillsMiddleware with callable backends."""
    registry = {
        "biomedical-literature-search": "skills/biomedical-literature-search",
        "pubmed-eutils-search": "skills/pubmed-eutils-search",
        "html-report-generator": "skills/html-report-generator",
    }

    subagents = get_subagents(
        skills_sources=["skills/"],
        skill_registry=registry,
        data_dir="/tmp/deepmast-test-data",
    )
    by_name = {subagent["name"]: subagent for subagent in subagents}

    for name in ("planner", "searcher", "reporter"):
        subagent = by_name[name]
        assert "skills" not in subagent
        assert "read_skill_file" in _tool_names(subagent)
        assert any(
            isinstance(middleware, SkillActivator)
            for middleware in subagent.get("middleware", [])
        )

    interpreter = by_name["interpreter"]
    assert "skills" not in interpreter
    assert not any(
        isinstance(middleware, SkillActivator)
        for middleware in interpreter.get("middleware", [])
    )
