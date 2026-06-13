from __future__ import annotations

from typing import Any, cast

import pytest

from src.agents.shared.skill_activation_governor import SkillActivationGovernor


SAMPLE_REGISTRY = {
    "drug-target-hypothesis": "skills/drug-target-hypothesis",
    "opentargets-database": "skills/opentargets-database",
    "chembl-database": "skills/chembl-database",
    "compare-census-gene-pair-by-cell-type": "skills/compare-census-gene-pair-by-cell-type",
    "string-database": "skills/string-database",
    "gwas-database": "skills/gwas-database",
    "biomedical-literature-search": "skills/biomedical-literature-search",
    "html-report-generator": "skills/html-report-generator",
}


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
        for key, value in kwargs.items():
            setattr(new, key, value)
        return new


@pytest.fixture
def governor() -> SkillActivationGovernor:
    return SkillActivationGovernor(
        skill_registry=SAMPLE_REGISTRY,
        artifact_gate="save_hypothesis_report",
    )


def test_loads_skill_body_without_frontmatter(
    governor: SkillActivationGovernor,
) -> None:
    assert not governor._prompt_template.startswith("---")
    assert "Activation Contract" in governor._prompt_template
    assert "Flexible Discovery" in governor._prompt_template
    assert "Required Coverage" in governor._prompt_template


def test_formats_available_skills(governor: SkillActivationGovernor) -> None:
    rendered = governor._format_available_skills()
    assert "drug-target-hypothesis" in rendered
    assert "opentargets-database" in rendered
    assert "gwas-database" in rendered
    assert "chembl-database" in rendered
    assert "compare-census-gene-pair-by-cell-type" in rendered
    assert "string-database" in rendered
    assert "biomedical-literature-search" in rendered
    assert "html-report-generator" in rendered
    assert "SKILL.md" in rendered


@pytest.mark.asyncio
async def test_injects_governor_protocol_and_artifact_gate(
    governor: SkillActivationGovernor,
) -> None:
    request = MockRequest(system_content="Base hypothesis_writer prompt.")
    captured: str | None = None

    async def handler(req):
        nonlocal captured
        captured = str(req.system_message.content)
        return "ok"

    result = await governor.awrap_model_call(cast(Any, request), cast(Any, handler))

    assert result == "ok"
    assert captured is not None
    assert "Base hypothesis_writer prompt." in captured
    assert "Skill Activation Governor" in captured
    assert "Artifact gate: save_hypothesis_report" in captured
    assert "No `required_skill_names` are provided" in captured
    assert "opentargets-database" in captured
    assert "string-database" in captured


@pytest.mark.asyncio
async def test_injects_required_skill_names() -> None:
    governor = SkillActivationGovernor(
        skill_registry=SAMPLE_REGISTRY,
        required_skill_names=("drug-target-hypothesis", "string-database"),
        artifact_gate="save_hypothesis_report",
    )
    request = MockRequest(system_content="Base hypothesis_writer prompt.")
    captured: str | None = None

    async def handler(req):
        nonlocal captured
        captured = str(req.system_message.content)
        return "ok"

    await governor.awrap_model_call(cast(Any, request), cast(Any, handler))

    assert captured is not None
    assert "Hard required skills: drug-target-hypothesis, string-database" in captured
    assert "Required skills: drug-target-hypothesis, string-database" in captured
    assert "Required skills are provided by this caller" in captured
    assert "Hard required skills: NONE" not in captured


@pytest.mark.asyncio
async def test_injects_split_contract_runtime_context() -> None:
    candidate_skill_names = (
        "opentargets-database",
        "chembl-database",
        "compare-census-gene-pair-by-cell-type",
        "string-database",
        "gwas-database",
        "biomedical-literature-search",
        "html-report-generator",
    )
    governor = SkillActivationGovernor(
        skill_registry=SAMPLE_REGISTRY,
        hard_required_skill_names=("drug-target-hypothesis",),
        candidate_skill_names=candidate_skill_names,
        artifact_gate="save_hypothesis_report",
    )
    request = MockRequest(system_content="Base hypothesis_writer prompt.")
    captured: str | None = None

    async def handler(req):
        nonlocal captured
        captured = str(req.system_message.content)
        return "ok"

    await governor.awrap_model_call(cast(Any, request), cast(Any, handler))

    assert governor.hard_required_skill_names == ("drug-target-hypothesis",)
    assert governor.required_skill_names == ("drug-target-hypothesis",)
    assert governor.candidate_skill_names == candidate_skill_names
    assert captured is not None
    assert "Hard required skills: drug-target-hypothesis" in captured
    assert "Required skills: drug-target-hypothesis" in captured
    assert "Candidate skills: " in captured
    assert "Available skills: " in captured
    assert "Artifact gate: save_hypothesis_report" in captured
    for skill_name in candidate_skill_names:
        assert skill_name in captured
    assert "Evaluate every candidate skill with YES or NO" in captured
    assert "NO candidates must remain suppressed" in captured


def test_required_skill_names_remains_alias_for_hard_required_skill_names() -> None:
    governor = SkillActivationGovernor(
        skill_registry=SAMPLE_REGISTRY,
        required_skill_names=("drug-target-hypothesis",),
        artifact_gate="save_hypothesis_report",
    )

    assert governor.hard_required_skill_names == ("drug-target-hypothesis",)
    assert governor.required_skill_names == ("drug-target-hypothesis",)
    assert "drug-target-hypothesis" not in governor.candidate_skill_names
    assert set(governor.candidate_skill_names) == set(SAMPLE_REGISTRY) - {
        "drug-target-hypothesis"
    }


@pytest.mark.asyncio
async def test_abefore_agent_is_noop(governor: SkillActivationGovernor) -> None:
    assert await governor.abefore_agent(state=None, runtime=None) is None
