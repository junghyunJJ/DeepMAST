"""LangGraph agent graph builders"""
from typing import Any

from langgraph.graph.state import CompiledStateGraph
from langgraph.checkpoint.memory import MemorySaver

from src.agents.pipeline.st_pipeline_info_agent import STPipelineBuilderAgent, STPipelineBuilderState
from src.agents.model import create_llm


async def create_st_pipeline_graph(
    llm_provider: str = "openai",
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

    # LLM 생성
    if llm_provider == "ollama":
        llm = create_llm("ollama", model = "gpt-oss:120b", base_url = "http://localhost:6000")
    elif llm_provider == "openai":
        llm = create_llm("openai")
    else:
        llm = create_llm(llm_provider)

    # 체크포인터 생성 (LangGraph CLI는 자체 persistence를 사용하므로 None)
    checkpointer = MemorySaver() if use_checkpointer else None

    # 에이전트 생성 - Now uses STPipelineBuilderAgent with full HITL workflow
    agent = STPipelineBuilderAgent(
        model=llm,
        state_schema=STPipelineBuilderState,
        checkpointer=checkpointer,
        is_debug=is_debug
    )

    # 그래프 빌드 (build_graph is called in __init__)
    return agent.graph


# 동기 방식의 래퍼 함수 (LangGraph CLI가 요구하는 형식)
def _get_graph() -> CompiledStateGraph:
    """ST Pipeline graph (동기 래퍼) - for LangGraph CLI without custom checkpointer"""
    import asyncio
    # LangGraph CLI uses platform persistence, so disable custom checkpointer
    # return asyncio.run(create_st_pipeline_graph(llm_provider='ollama', use_checkpointer=False, is_debug=False))
    # return asyncio.run(create_st_pipeline_graph(llm_provider='google', use_checkpointer=False, is_debug=False))
    return asyncio.run(create_st_pipeline_graph(use_checkpointer=False, is_debug=False))

# LangGraph CLI용 graph export
graph = _get_graph()

