"""LangGraph agent graph builders.

This module provides factory functions that create compiled state graphs
for the LangGraph CLI. These graphs are exported for use with `langgraph dev`.

Exported graphs:
    - graph: STPipelineBuilderAgent for ST pipeline construction
    - biological_interpreter_graph: BiologicalInterpreterAgent for CCI interpretation
    - pubmed_rag_graph: PubMedRAGAgent for literature-based Q&A
    - cci_interpreter_graph: CCIInterpreterAgent (Deep Agents) for CCI interpretation
    - deep_interpreter_graph: DeepInterpreterAgent (refactored DeepAgents)
    - deep_interpreter_wrapped_graph: DeepInterpreterWrapperAgent with HITL (recommended)

Note:
    The synchronous wrappers (_get_graph, _get_biological_interpreter_graph)
    are required because LangGraph CLI expects synchronous graph exports.
    These wrappers handle event loop management for async agent initialization.

    The CCI Interpreter and Deep Interpreter use the Deep Agents framework
    and are imported from their dedicated graph_builder modules.
"""
import os

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph.state import CompiledStateGraph
from langgraph.checkpoint.memory import MemorySaver

from src.agents.pipeline.st_pipeline_info_agent import STPipelineBuilderAgent, STPipelineBuilderState
from src.agents.interpreter.biological_interpreter_agent import BiologicalInterpreterAgent
from src.agents.interpreter.biological_interpreter_state import BiologicalInterpreterState
from src.agents.pubmedrag.pubmedrag_agent import PubMedRAGAgent
from src.agents.pubmedrag.pubmedrag_state import PubMedRAGState
from src.agents.model import create_llm


# Default LLM provider from environment variable
DEFAULT_LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")


def _create_llm_for_graph(llm_provider: str) -> BaseChatModel:
    """Create LLM instance with project-specific defaults.

    Args:
        llm_provider: LLM provider ("google", "openai", "ollama")

    Returns:
        Configured BaseChatModel instance
    """
    if llm_provider == "ollama":
        return create_llm(
            "ollama",
            model=os.getenv("OLLAMA_MODEL", "gpt-oss:120b"),
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:6000")
        )
    elif llm_provider == "openai":
        return create_llm("openai")
    else:
        return create_llm(llm_provider)


def _run_async_safely(coro):
    """Run async coroutine safely, handling existing event loop scenarios.

    Args:
        coro: Async coroutine to run

    Returns:
        Result of the coroutine
    """
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop - safe to use asyncio.run()
        return asyncio.run(coro)

    # Running loop exists - use thread pool to avoid collision
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(asyncio.run, coro)
        return future.result()


async def create_st_pipeline_graph(
    llm_provider: str = DEFAULT_LLM_PROVIDER,
    is_debug: bool = True,
    recursion_limit: int = 50,
    use_checkpointer: bool = True
) -> CompiledStateGraph:
    """Create Spatial Transcriptomics Pipeline Builder agent graph with HITL support

    Args:
        llm_provider: LLM provider to use ("google", "kimi", "openai", "ollama")
        is_debug: Enable debug mode
        recursion_limit: Maximum recursion depth for graph execution
        use_checkpointer: If True, use MemorySaver checkpointer. If False, use None (for LangGraph CLI)

    Returns:
        Compiled state graph for the agent
    """
    # Load environment variables asynchronously to prevent blocking I/O warnings
    from src.base.async_env import load_env_async
    await load_env_async(override=True)

    # Create LLM instance
    llm = _create_llm_for_graph(llm_provider)

    # Create checkpointer (LangGraph CLI uses its own persistence, so None)
    checkpointer = MemorySaver() if use_checkpointer else None

    # Create agent - uses STPipelineBuilderAgent with full HITL workflow
    agent = STPipelineBuilderAgent(
        model=llm,
        state_schema=STPipelineBuilderState,
        checkpointer=checkpointer,
        is_debug=is_debug
    )

    # Build graph (build_graph is called in __init__)
    # Apply recursion_limit as default config
    return agent.graph.with_config({"recursion_limit": recursion_limit})


def _get_graph() -> CompiledStateGraph:
    """ST Pipeline graph (sync wrapper) - for LangGraph CLI without custom checkpointer"""
    return _run_async_safely(
        create_st_pipeline_graph(use_checkpointer=False, is_debug=False)
    )


# LangGraph CLI graph export
graph = _get_graph()


# ==============================================================================
# Biological Interpreter Agent
# ==============================================================================

# BI_LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")

async def create_biological_interpreter_graph(
    # llm_provider: str = BI_LLM_PROVIDER,
    llm_provider: str = DEFAULT_LLM_PROVIDER,
    is_debug: bool = True,
    recursion_limit: int = 100,
    use_checkpointer: bool = True
) -> CompiledStateGraph:
    """Create Biological Interpreter agent graph for CCI analysis interpretation

    Args:
        llm_provider: LLM provider to use ("google", "openai", "ollama")
        is_debug: Enable debug mode
        recursion_limit: Maximum recursion depth for graph execution
        use_checkpointer: If True, use MemorySaver checkpointer. If False, use None (for LangGraph CLI)

    Returns:
        Compiled state graph for the agent
    """
    # Load environment variables asynchronously
    from src.base.async_env import load_env_async
    await load_env_async(override=True)

    # Create LLM instance
    llm = _create_llm_for_graph(llm_provider)

    # Create checkpointer (LangGraph CLI uses its own persistence)
    checkpointer = MemorySaver() if use_checkpointer else None

    # Create agent
    agent = BiologicalInterpreterAgent(
        model=llm,
        state_schema=BiologicalInterpreterState,
        checkpointer=checkpointer,
        is_debug=is_debug
    )

    # Apply recursion_limit as default config
    return agent.graph.with_config({"recursion_limit": recursion_limit})


def _get_biological_interpreter_graph() -> CompiledStateGraph:
    """Biological Interpreter graph (sync wrapper) - for LangGraph CLI"""
    return _run_async_safely(
        create_biological_interpreter_graph(use_checkpointer=False, is_debug=False)
    )


# LangGraph CLI export for biological interpreter
biological_interpreter_graph = _get_biological_interpreter_graph()


# ==============================================================================
# PubMed RAG Agent
# ==============================================================================

async def create_pubmed_rag_graph(
    llm_provider: str = DEFAULT_LLM_PROVIDER,
    is_debug: bool = True,
    recursion_limit: int = 50,
    use_checkpointer: bool = True
) -> CompiledStateGraph:
    """Create PubMed RAG agent graph for literature-based question answering.

    This agent answers biological questions using a hybrid RAG approach:
    1. Search existing mast_pubmed collection
    2. LLM judges if results are sufficient
    3. If insufficient: search PubMed, download papers, add to collection
    4. Generate answer with sequential-thinking (inline PMID citations)

    Args:
        llm_provider: LLM provider to use ("google", "openai", "ollama")
        is_debug: Enable debug mode
        recursion_limit: Maximum recursion depth for graph execution
        use_checkpointer: If True, use MemorySaver checkpointer

    Returns:
        Compiled state graph for the agent
    """
    # Load environment variables asynchronously
    from src.base.async_env import load_env_async
    await load_env_async(override=True)

    # Create LLM instance
    llm = _create_llm_for_graph(llm_provider)

    # Create checkpointer
    checkpointer = MemorySaver() if use_checkpointer else None

    # Create agent
    agent = PubMedRAGAgent(
        model=llm,
        state_schema=PubMedRAGState,
        checkpointer=checkpointer,
        is_debug=is_debug
    )

    # Apply recursion_limit as default config
    return agent.graph.with_config({"recursion_limit": recursion_limit})


def _get_pubmed_rag_graph() -> CompiledStateGraph:
    """PubMed RAG graph (sync wrapper) - for LangGraph CLI"""
    return _run_async_safely(
        create_pubmed_rag_graph(use_checkpointer=False, is_debug=False)
    )


# LangGraph CLI export for PubMed RAG agent
pubmed_rag_graph = _get_pubmed_rag_graph()


# ==============================================================================
# CCI Interpreter Agent (Deep Agents)
# ==============================================================================

# Import from dedicated module - uses Deep Agents framework
from src.agents.cci_interpreter.graph_builder import cci_interpreter_graph

# ==============================================================================
# CCI Interpreter Wrapped Agent (RECOMMENDED)
# ==============================================================================

# Wrapped version with reliable HITL - uses pre-collection pattern
from src.agents.cci_interpreter.graph_builder import cci_interpreter_wrapped_graph


# ==============================================================================
# Deep Interpreter Agent (DeepAgents Framework - Refactored)
# ==============================================================================

# Import from dedicated module - uses DeepAgents framework (refactored version)
from src.agents.deep_interpreter.graph_builder import deep_interpreter_graph

# Wrapped version with HITL target collection (RECOMMENDED)
from src.agents.deep_interpreter.graph_builder import deep_interpreter_wrapped_graph
