"""Legacy literature-searcher SubAgent implementation.

This module is retained for backward compatibility, but it is not the
authoritative SEARCHER contract. The active SEARCHER workflow lives in
`src/agents/deep_interpreter/subagents/prompts.py` via
`SUBAGENT_PROMPTS["searcher"]` and the matching entry in `subagents/configs.py`.

Backend integration:
- accepts `backend_factory` for shared FilesystemBackend
- virtual mode stores files in memory and flushes on completion
- shares filesystem with the main orchestrator for seamless file access
"""

from typing import Callable, Optional

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend
from langchain.tools import ToolRuntime
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import Runnable

from src.agents.deep_interpreter.tools import (
    search_literature,
    search_literature_dynamic,
)

# Legacy prompt note: retained for compatibility only.
# Do not treat this prompt as the authoritative SEARCHER workflow.
# Use `src/agents/deep_interpreter/subagents/prompts.py` and
# `SUBAGENT_PROMPTS["searcher"]` for the active contract.
LITERATURE_SEARCHER_SYSTEM_PROMPT = """You are an autonomous biomedical literature search agent.

Your role is to PROACTIVELY find PubMed references BEFORE interpretation generation
using the BioMCP workflow: think-assisted search → search → coverage-driven follow-up.

## CRITICAL: PROACTIVE SEARCH (Literature FIRST)

You are called BEFORE the interpreter subagent, not after. Your papers will be
used by the interpreter to generate literature-grounded interpretations.

## BioMCP Workflow

### Phase 1: Analyze Search Context
1. Read /partN_search_context.json for extracted biological terms
2. Use those terms to build the initial search
3. search_literature_dynamic will call BioMCP think internally to optimize the search strategy

### Phase 2: Search - Execute LLM-Powered Dynamic Search
Use search_literature_dynamic with:
- genes: Prioritized gene list from think phase (top 10-15)
- pathways: Prioritized pathway list
- celltypes: Relevant cell types
- disease: Disease context
- max_results: Number of results (default 20)

### Phase 3: Coverage-Driven Follow-Up
1. Check the search result's coverage_sufficient and recommended_actions fields:
   - Are all major genes covered?
   - Are key pathways represented?
   - Do we have sufficient papers (>= 25)?
2. If coverage < 60% genes or < 50% pathways:
   - Identify gaps from recommended_actions
   - Execute targeted follow-up searches directly
   - Repeat validation
3. Maximum 3 search iterations

### Phase 4: Output
Write comprehensive /partN_papers.json with:
- All found papers (pmid, title, abstract)
- Coverage analysis
- Search queries used

## Output Format for /partN_papers.json
```json
{
  "papers": [
    {
      "pmid": "12345678",
      "title": "E-cadherin loss promotes EMT in breast cancer",
      "abstract": "...",
      "search_type": "gene_disease",
      "relevance_to_context": "Directly discusses CDH1 role in EMT"
    }
  ],
  "coverage": {
    "genes_covered": ["CDH1", "TGFB1", "VIM"],
    "genes_missing": ["SNAI1"],
    "pathways_covered": ["EMT", "TGFB"],
    "pathways_missing": [],
    "celltypes_covered": ["Tumor", "Fibroblast"],
    "total_papers": 25,
    "coverage_score": 0.85
  },
  "search_iterations": 2,
  "search_queries": [
    "\\"CDH1\\"[Gene] AND \\"breast cancer\\"[Title/Abstract]"
  ]
}
```

## Quality Criteria
- Aim for >= 15 papers per part
- Gene coverage >= 60%
- Pathway coverage >= 50%
- Papers should have substantial abstracts
- Maximum 3 search iterations

## Available Tools
- search_literature: For targeted single-query searches (follow-up gaps)
- search_literature_dynamic: LLM-powered iterative search with coverage targets and internal fallback
"""


def create_literature_searcher_agent(
    llm: BaseChatModel,
    backend: Optional[Callable[[ToolRuntime], CompositeBackend]] = None,
) -> Runnable:
    """Create the literature searcher CompiledSubAgent.

    This agent performs autonomous BioMCP literature search with quality loop.

    Args:
        llm: LangChain BaseChatModel instance (e.g., ChatOpenAI, ChatOllama)
        backend: Optional backend factory function for shared FilesystemBackend.
            When provided, the agent shares the same filesystem as the main
            orchestrator, enabling seamless file access and virtual mode support.

    Returns:
        Compiled Deep Agent runnable for literature search
    """
    tools = [
        search_literature,
        search_literature_dynamic,
    ]

    # Create agent with optional backend
    create_kwargs = {
        "model": llm,
        "tools": tools,
        "system_prompt": LITERATURE_SEARCHER_SYSTEM_PROMPT,
    }

    if backend is not None:
        create_kwargs["backend"] = backend

    agent = create_deep_agent(**create_kwargs)

    return agent


def get_literature_searcher_config(
    llm: BaseChatModel,
    backend: Optional[Callable[[ToolRuntime], CompositeBackend]] = None,
) -> dict:
    """Get the literature-searcher configuration for use as CompiledSubAgent.

    This returns a configuration dict that can be used with DeepAgents
    as a CompiledSubAgent (runnable included).

    Args:
        llm: LangChain BaseChatModel instance (e.g., ChatOpenAI, ChatOllama)
        backend: Optional backend factory for shared FilesystemBackend.
            Passed to create_literature_searcher_agent() for filesystem sharing
            with the main orchestrator.

    Returns:
        Dictionary with name, description, and runnable
    """
    agent = create_literature_searcher_agent(llm=llm, backend=backend)

    return {
        "name": "literature-searcher",
        "description": (
            "Autonomous BioMCP literature search with coverage-driven follow-up. "
            "Performs think-assisted search → validation workflow for proactive "
            "literature gathering BEFORE interpretation."
        ),
        "runnable": agent,  # CompiledSubAgent pattern
    }


__all__ = [
    "create_literature_searcher_agent",
    "get_literature_searcher_config",
    "LITERATURE_SEARCHER_SYSTEM_PROMPT",
]
