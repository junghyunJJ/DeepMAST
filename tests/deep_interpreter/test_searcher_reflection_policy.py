from src.agents.deep_interpreter.subagents.configs import SUBAGENT_CONFIGS
from src.agents.deep_interpreter.subagents.prompts import SUBAGENT_PROMPTS


def test_searcher_tools_do_not_include_think_tool() -> None:
    tool_names = {tool.name for tool in SUBAGENT_CONFIGS["searcher"]["tools"]}

    assert "think_tool" not in tool_names


def test_searcher_prompt_uses_gap_follow_up_without_reflection() -> None:
    prompt = SUBAGENT_PROMPTS["searcher"]

    assert "coverage_sufficient" in prompt
    assert "recommended_actions" in prompt
    assert "think_tool" not in prompt
    assert "Reflect (Quality Loop)" not in prompt
