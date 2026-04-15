"""Unit tests for SkillActivator middleware.

Tests cover:
- Initialization with skill_registry
- SKILL.md prompt template loading
- awrap_model_call: forced-eval block injection into system prompt
- {{available_skills}} placeholder substitution
- Empty registry produces empty skills block
- Coexistence with WriteFileArgGuardMiddleware
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.agents.shared.skill_activator import SkillActivator


# =============================================================================
# Fixtures
# =============================================================================

SAMPLE_REGISTRY = {
    "opentargets-database": "skills/opentargets-database",
    "gwas-database": "skills/gwas-database",
    "chembl-database": "skills/chembl-database",
}


@pytest.fixture
def harness() -> SkillActivator:
    return SkillActivator(skill_registry=SAMPLE_REGISTRY)


@pytest.fixture
def empty_harness() -> SkillActivator:
    return SkillActivator(skill_registry={})


# =============================================================================
# Mock Request
# =============================================================================


class MockSystemMessage:
    def __init__(self, content: str):
        self.content = content


class MockRequest:
    def __init__(self, system_content: str = ""):
        self.system_message = MockSystemMessage(system_content) if system_content else None
        self.system_prompt = system_content if not self.system_message else None

    def override(self, **kwargs):
        new = MockRequest.__new__(MockRequest)
        new.system_message = self.system_message
        new.system_prompt = self.system_prompt
        for k, v in kwargs.items():
            setattr(new, k, v)
        return new


# =============================================================================
# Tests
# =============================================================================


class TestSkillActivatorInit:
    """Test SkillActivator initialization."""

    def test_creates_with_registry(self, harness: SkillActivator):
        assert harness.skill_registry == SAMPLE_REGISTRY

    def test_prompt_template_loaded(self, harness: SkillActivator):
        """SKILL.md body should be loaded (no YAML frontmatter)."""
        assert "{{available_skills}}" in harness._prompt_template
        assert "Phase 1" in harness._prompt_template
        assert "QUICK SCREEN" in harness._prompt_template
        assert "Phase 2" in harness._prompt_template
        assert "EVALUATE" in harness._prompt_template
        assert "Phase 3" in harness._prompt_template
        assert "IMPLEMENT" in harness._prompt_template
        # Frontmatter should be stripped
        assert "---" not in harness._prompt_template


class TestPromptTemplateLoading:
    """Test SKILL.md template loading edge cases."""

    def test_template_has_no_frontmatter(self, harness: SkillActivator):
        assert not harness._prompt_template.startswith("---")

    def test_template_contains_critical_instruction(self, harness: SkillActivator):
        # The "When in doubt → NO" default rule is the critical safety net
        assert "When in doubt" in harness._prompt_template

    def test_fallback_prompt(self):
        """_fallback_prompt should contain the same structure."""
        fallback = SkillActivator._fallback_prompt()
        assert "{{available_skills}}" in fallback
        assert "Step 1 - EVALUATE" in fallback


class TestFormatAvailableSkills:
    """Test _format_available_skills output."""

    def test_formats_all_skills(self, harness: SkillActivator):
        result = harness._format_available_skills()
        assert "opentargets-database" in result
        assert "gwas-database" in result
        assert "chembl-database" in result

    def test_empty_registry(self, empty_harness: SkillActivator):
        result = empty_harness._format_available_skills()
        assert "No skills registered" in result

    def test_skill_md_paths(self, harness: SkillActivator):
        result = harness._format_available_skills()
        assert "SKILL.md" in result


class TestAwrapModelCall:
    """Test system prompt injection via awrap_model_call."""

    @pytest.mark.asyncio
    async def test_injects_forced_eval_block(self, harness: SkillActivator):
        """System prompt should contain the forced-eval protocol."""
        request = MockRequest(system_content="You are a test agent.")
        captured = None

        async def handler(req):
            nonlocal captured
            captured = str(req.system_message.content)
            return "mock_response"

        await harness.awrap_model_call(request, handler)

        assert captured is not None
        assert "You are a test agent." in captured
        assert "Phase 1" in captured
        assert "opentargets-database" in captured

    @pytest.mark.asyncio
    async def test_replaces_placeholder(self, harness: SkillActivator):
        """{{available_skills}} must be replaced with actual skill list."""
        request = MockRequest(system_content="Base prompt.")
        captured = None

        async def handler(req):
            nonlocal captured
            captured = str(req.system_message.content)
            return "mock_response"

        await harness.awrap_model_call(request, handler)

        assert "{{available_skills}}" not in captured
        assert "opentargets-database" in captured
        assert "gwas-database" in captured

    @pytest.mark.asyncio
    async def test_empty_system_prompt(self, harness: SkillActivator):
        """Should work even with no existing system prompt."""
        request = MockRequest(system_content="")
        captured = None

        async def handler(req):
            nonlocal captured
            captured = str(req.system_message.content)
            return "mock_response"

        await harness.awrap_model_call(request, handler)

        assert "Phase 1" in captured

    @pytest.mark.asyncio
    async def test_empty_registry_injection(self, empty_harness: SkillActivator):
        """Empty registry should inject block with 'No skills registered'."""
        request = MockRequest(system_content="Base.")
        captured = None

        async def handler(req):
            nonlocal captured
            captured = str(req.system_message.content)
            return "mock_response"

        await empty_harness.awrap_model_call(request, handler)

        assert "No skills registered" in captured

    @pytest.mark.asyncio
    async def test_handler_receives_modified_request(self, harness: SkillActivator):
        """Handler should receive the modified request and its return value propagated."""
        request = MockRequest(system_content="Original.")

        async def handler(req):
            return "handler_result"

        result = await harness.awrap_model_call(request, handler)
        assert result == "handler_result"


class TestAbforeAgent:
    """Test abefore_agent (should be a no-op)."""

    @pytest.mark.asyncio
    async def test_abefore_agent_noop(self, harness: SkillActivator):
        result = await harness.abefore_agent(state=None, runtime=None)
        assert result is None


class TestMiddlewareCoexistence:
    """Test that SkillActivator coexists with WriteFileArgGuardMiddleware."""

    @pytest.mark.asyncio
    async def test_both_middlewares_in_list(self, harness: SkillActivator):
        """Both middlewares should be instantiable together."""
        from src.agents.deep_interpreter.middleware.write_file_guard import (
            WriteFileArgGuardMiddleware,
        )

        guard = WriteFileArgGuardMiddleware()
        middleware_list = [guard, harness]
        assert len(middleware_list) == 2
        assert isinstance(middleware_list[0], WriteFileArgGuardMiddleware)
        assert isinstance(middleware_list[1], SkillActivator)
