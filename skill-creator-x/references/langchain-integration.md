# LangChain / Multi-Agent SDK Integration Guide

SDK version requirements (verified as of 2026-04):
- `langchain-core >= 0.3`, `langchain >= 0.3`
- `langgraph >= 0.4`
- `openai-agents >= 0.0.x` (OpenAI Agents SDK, formerly `agents`)
- `deepagents` (DeepMAST internal — see `src/agents/`)

---

## 1. LangChain `load_skill` Tool Pattern

Expose a skill document as a LangChain `@tool` so any agent can read it on demand.
The `@tool` decorator automatically builds a `StructuredTool` from the function signature and
docstring. Fence markers (```` ``` ````) in the raw YAML/Markdown must be stripped before
injecting content into a prompt.

```python
# verified as of 2026-04 | langchain-core >= 0.3
from __future__ import annotations

from pathlib import Path

from langchain_core.tools import tool  # replaces langchain.tools.tool (deprecated 0.2)

_SKILLS_ROOT = Path(__file__).resolve().parents[2] / "skills"


def _strip_fences(text: str) -> str:
    """Remove leading/trailing ``` fences that some YAML blocks include."""
    lines = text.splitlines()
    cleaned = [ln for ln in lines if not ln.strip().startswith("```")]
    return "\n".join(cleaned)


@tool
def load_skill(skill_name: str, section: str = "") -> str:
    """Return the content of a skill document, optionally filtered to one section.

    Args:
        skill_name: Directory name under skills/, e.g. 'drug-target-reporting'.
        section:    Optional heading to extract (case-insensitive prefix match).
    """
    skill_dir = _SKILLS_ROOT / skill_name
    candidates = list(skill_dir.glob("*.md")) + list(skill_dir.glob("SKILL.md"))
    if not candidates:
        return f"Skill '{skill_name}' not found under {_SKILLS_ROOT}"

    raw = candidates[0].read_text(encoding="utf-8")
    content = _strip_fences(raw)

    if not section:
        return content

    lines = content.splitlines()
    in_section = False
    result: list[str] = []
    for line in lines:
        if line.lstrip("#").strip().lower().startswith(section.lower()):
            in_section = True
        elif line.startswith("#") and in_section:
            break
        if in_section:
            result.append(line)
    return "\n".join(result) if result else content


# Agent registration — pass to create_deep_agent() or any LangChain AgentExecutor
# tools = [load_skill, ...]
```

**Key points:**
- `@tool` from `langchain_core.tools` is the stable import path as of LangChain 0.3.
- The function docstring becomes the tool description seen by the LLM.
- `_strip_fences` prevents raw `` ``` `` characters from breaking prompt formatting.

---

## 2. LangGraph Multi-Agent: `StateGraph` + `skill_loader_node`

Wire a skill-loading step into a `StateGraph` so downstream nodes always have skill content
available in shared state before they execute.

```python
# verified as of 2026-04 | langgraph >= 0.4
from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, StateGraph

from .tools import load_skill  # the @tool defined in section 1


class AgentState(TypedDict):
    skill_name: str
    skill_content: str
    result: str


def skill_loader_node(state: AgentState) -> AgentState:
    """Load skill document into state before the reasoning node runs."""
    content = load_skill.invoke({"skill_name": state["skill_name"]})
    return {**state, "skill_content": content}


def reasoning_node(state: AgentState) -> AgentState:
    """Use skill_content as context for the main agent logic."""
    # skill_content is guaranteed non-empty here
    _ = state["skill_content"]
    return {**state, "result": "..."}


# Graph assembly
builder = StateGraph(AgentState)
builder.add_node("load_skill", skill_loader_node)
builder.add_node("reason", reasoning_node)

builder.set_entry_point("load_skill")
builder.add_edge("load_skill", "reason")
builder.add_edge("reason", END)

graph = builder.compile()
```

**Key points:**
- `skill_loader_node` is a pure function — no LLM call, fast and deterministic.
- State is immutable-by-convention: spread `{**state, ...}` rather than mutating in place.
- Additional subagent nodes (PLANNER, SEARCHER, …) follow the same `add_node` / `add_edge`
  pattern used in DeepMAST's `graph_builder.py`.

---

## 3. OpenAI Agents SDK `@function_tool` Pattern

The OpenAI Agents SDK (package `openai-agents`) uses `@function_tool` instead of LangChain's
`@tool`. The schema is auto-derived from the Python type annotations.

```python
# verified as of 2026-04 | openai-agents >= 0.0.x
from __future__ import annotations

from pathlib import Path

from agents import Agent, Runner, function_tool  # openai-agents package


_SKILLS_ROOT = Path(__file__).resolve().parents[2] / "skills"


@function_tool
def load_skill_oai(skill_name: str) -> str:
    """Return the full content of the named skill document.

    Args:
        skill_name: Directory name under skills/, e.g. 'chembl-database'.
    """
    candidates = list((_SKILLS_ROOT / skill_name).glob("*.md"))
    if not candidates:
        return f"Skill '{skill_name}' not found."
    return candidates[0].read_text(encoding="utf-8")


# Attach to an Agent
agent = Agent(
    name="SkillAwareAgent",
    instructions="You are a biomedical research assistant. Use load_skill_oai when you need domain guidance.",
    tools=[load_skill_oai],
)

# Synchronous run
result = Runner.run_sync(agent, "Load the drug-target-reporting skill and summarise it.")
print(result.final_output)
```

**Key points:**
- `@function_tool` wraps the function into a `FunctionTool`; the docstring's `Args:` block
  is parsed to build per-parameter descriptions.
- `Runner.run_sync` is the blocking entry point; use `await Runner.run(...)` in async contexts.
- Unlike LangChain tools, `function_tool` objects cannot be passed directly to LangChain agents
  — use the LangChain `@tool` variant (section 1) when working in a mixed stack.

---

## 4. DeepMAST `SkillsMiddleware` Integration

`SkillsMiddleware` (from `src/agents/shared/skills_middleware.py`) injects skill metadata into
the system prompt before every model call. It is wired into `create_deep_agent()` via the
`middleware` parameter.

```python
# verified as of 2026-04 | deepagents internal API
from __future__ import annotations

from pathlib import Path

from deepagents import create_deep_agent
from src.agents.shared.skills_middleware import SkillsMiddleware
from src.agents.shared.skill_reader import read_skill_file  # @tool for agents to read files


SKILLS_DIR = Path(__file__).resolve().parents[3] / "skills"


def build_agent():
    middleware = SkillsMiddleware(
        skills_dir=SKILLS_DIR,
        # Restrict to relevant skills; omit to expose all
        allowed_skill_names=[
            "drug-target-reporting",
            "chembl-database",
            "opentargets-database",
        ],
    )

    return create_deep_agent(
        subagents=[...],       # SubagentConfig list from subagents/configs.py
        middleware=[middleware],
        tools=[read_skill_file],  # lets subagents read full skill docs at runtime
    )
```

**How it works at runtime:**
1. `abefore_agent` — called once per agent invocation; scans `skills_dir` and caches
   `SkillMetadata` (name, description, path) via `list_skills()`.
2. `awrap_model_call` — prepends a `## Skills System` block to the system prompt listing
   available skills with their file paths.
3. Subagents read the full skill document using `read_skill_file` (a standard `@tool`) when
   they need detailed guidance — this is the *progressive disclosure* pattern.

**`WriteFileArgGuardMiddleware` and `ReadFileBlockMiddleware`** are additional middleware
used in the Deep Interpreter agent to prevent unintended file writes/reads; they compose
alongside `SkillsMiddleware` in the `middleware=[...]` list.

---

## Quick Reference

| SDK | Decorator | Import path | Min version |
|-----|-----------|-------------|-------------|
| LangChain | `@tool` | `langchain_core.tools` | 0.3 |
| LangGraph | `StateGraph` | `langgraph.graph` | 0.4 |
| OpenAI Agents | `@function_tool` | `agents` | 0.0.x |
| DeepMAST | `SkillsMiddleware` | `src.agents.shared.skills_middleware` | internal |
