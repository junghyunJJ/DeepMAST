"""Graph builder for Drug Target Assessment Agent.

Provides LangGraph CLI integration for standalone testing and deployment.

Graph: DrugTarget — standalone drug target assessment agent
"""

import os

from dotenv import load_dotenv
from langchain_core.runnables import Runnable

load_dotenv()

from src.agents.drug_target.agent import (  # noqa: E402
    create_drug_target_agent,
    DrugTargetConfig,
)


def _get_drug_target_graph() -> Runnable:
    """Drug Target Assessment graph — for LangGraph CLI.

    Uses environment variables:
    - LLM_PROVIDER: LLM provider (default: "openrouter")
    - DEEP_INTERPRETER_DATA_DIR: Data directory with lr_candidates.json

    Returns:
        Compiled Drug Target Agent runnable
    """
    provider = os.getenv("LLM_PROVIDER", "openrouter")
    data_dir = os.getenv("DEEP_INTERPRETER_DATA_DIR", "/tmp/deep_interpreter_workspace")

    config = DrugTargetConfig(
        provider=provider,
        data_dir=data_dir,
        use_checkpointer=False,  # LangGraph CLI uses its own persistence
    )

    agent, backend = create_drug_target_agent(config)
    if backend:
        atexit.register(backend.cleanup)
    return agent


# LangGraph CLI export
drug_target_graph = _get_drug_target_graph()


__all__ = [
    "drug_target_graph",
]
