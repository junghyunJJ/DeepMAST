"""Direct guarded Drug Target runnable for LangGraph deployment.

The production agent dispatches ``evidence_assessor`` then ``report_writer``;
``DrugReportGuardrailMiddleware`` validates and publishes the report. Callers
keep ``recursion_limit`` at the top level of ``RunnableConfig``.
"""

import os
from typing import cast

from dotenv import load_dotenv
from langchain_core.runnables import Runnable

from src.agents.drug_target.agent import (
    DrugTargetConfig,
    Provider,
    create_drug_target_agent,
)

load_dotenv()


def create_drug_target_graph(
    *,
    provider: Provider = "openrouter",
    data_dir: str = "",
    disease: str = "",
    use_checkpointer: bool = False,
) -> Runnable:
    """Build the guarded direct agent for one configured workspace."""
    resolved_data_dir = data_dir or os.getenv(
        "DRUG_TARGET_DATA_DIR",
        os.getenv("DEEP_INTERPRETER_DATA_DIR", "/tmp/deep_interpreter_workspace"),
    )
    agent, _backend = create_drug_target_agent(
        DrugTargetConfig(
            provider=provider,
            data_dir=resolved_data_dir,
            disease=disease,
            use_checkpointer=use_checkpointer,
            workflow_mode="guarded_report",
        )
    )
    return agent


# LangGraph CLI export — langgraph.json depends on this symbol name.
drug_target_graph = create_drug_target_graph(
    provider=cast(Provider, os.getenv("LLM_PROVIDER", "openrouter")),
    disease=os.getenv("DRUG_TARGET_DISEASE", ""),
    use_checkpointer=False,
)
