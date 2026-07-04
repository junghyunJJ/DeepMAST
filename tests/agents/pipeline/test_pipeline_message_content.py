from langchain_core.messages import AIMessage

from src.agents.pipeline.st_pipeline_info_agent import STPipelineBuilderAgent


def _agent_without_init() -> STPipelineBuilderAgent:
    return object.__new__(STPipelineBuilderAgent)


def test_extract_pipeline_updates_accepts_gpt_string_content() -> None:
    agent = _agent_without_init()

    result = agent._extract_pipeline_updates(
        [AIMessage(content="Use normalization and clustering for this pipeline.")]
    )

    assert result is None


def test_extract_pipeline_updates_accepts_ollama_list_content() -> None:
    agent = _agent_without_init()

    result = agent._extract_pipeline_updates(
        [
            AIMessage(
                content=[
                    {"type": "text", "text": "Use normalization for this pipeline."},
                    {"type": "text", "text": "Then run clustering."},
                ]
            )
        ]
    )

    assert result is None
