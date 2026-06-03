from src.agents.deep_interpreter.subagents.configs import SUBAGENT_CONFIGS
from src.agents.deep_interpreter.subagents.prompts import SUBAGENT_PROMPTS
from src.agents.deep_interpreter.prompts import ORCHESTRATOR_SYSTEM_PROMPT


def test_searcher_tools_do_not_include_think_tool() -> None:
    tool_names = {tool.name for tool in SUBAGENT_CONFIGS["searcher"]["tools"]}

    assert "think_tool" not in tool_names


def test_searcher_has_literature_handoff_tool() -> None:
    tool_names = {tool.name for tool in SUBAGENT_CONFIGS["searcher"]["tools"]}

    assert "create_literature_handoff" in tool_names


def test_searcher_prompt_excludes_detailed_gap_follow_up_policy() -> None:
    prompt = SUBAGENT_PROMPTS["searcher"]

    assert "When to Use Which Search Tool" not in prompt
    assert "coverage_sufficient" not in prompt
    assert "recommended_actions" not in prompt
    assert "Gap-filling specific genes" not in prompt
    assert "Need MeSH precision" not in prompt
    assert "Need recent papers only" not in prompt
    assert "Need systematic reviews" not in prompt
    assert "think_tool" not in prompt
    assert "Reflect (Quality Loop)" not in prompt


def test_searcher_prompt_keeps_literature_handoff_policy_light() -> None:
    prompt = SUBAGENT_PROMPTS["searcher"]

    assert "biomedical-literature-search" in prompt
    assert "load the workflow" in prompt
    assert "SEARCHER is responsible for producing `/papers.json`" in prompt
    assert "active benchmark override" in prompt
    assert "Do not invent" in prompt

    assert "papers_raw.json" not in prompt
    assert "citation_candidates.json" not in prompt
    assert "cap=40" not in prompt
    assert "cap is `40`" not in prompt
    assert "direct_lr_evidence" not in prompt
    assert "receptor_pathway_context_evidence" not in prompt
    assert "disease_only_background" not in prompt
    assert "rejected_weak_evidence" not in prompt
    assert 'output_path="papers_raw.json"' not in prompt
    assert 'citation_candidates_path="citation_candidates.json"' not in prompt


def test_orchestrator_names_raw_audit_and_filtered_literature_outputs() -> None:
    prompt = ORCHESTRATOR_SYSTEM_PROMPT

    assert "/papers_raw.json" in prompt
    assert "/citation_candidates.json" in prompt
    assert "/papers.json" in prompt
    assert "filtered" in prompt.lower()
