from src.agents.pipeline import st_pipeline_info_agent
from src.prompts.pipeline_prompts import selection_node_prompt


def _state() -> dict[str, str]:
    return {
        "st_technology": "Visium",
        "disease": "breast cancer",
        "species": "human",
        "os_type": "Mac",
        "gpu_available": "CPU",
    }


def test_selection_prompt_uses_wider_but_bounded_rag_search_budget() -> None:
    prompt = selection_node_prompt(_state(), is_spot_based=True, cell_type_task="deconvolution")

    assert "limit=20" in prompt
    assert "limit=10" in prompt
    assert "12-15 total search calls" in prompt
    assert "more than 10 search queries total" not in prompt


def test_pipeline_selection_recursion_limit_is_increased_for_local_models() -> None:
    assert st_pipeline_info_agent.PIPELINE_SELECTION_RECURSION_LIMIT == 60
