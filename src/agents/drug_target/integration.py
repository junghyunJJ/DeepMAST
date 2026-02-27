"""Reporter integration tool for Drug Target Assessment Agent.

Provides run_drug_target_assessment() as a single @tool that the Reporter
subagent calls to delegate the entire Phase 4.7 drug target assessment
to the DrugTargetAgent.
"""

import json
import logging
import os
import uuid
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# NOTE: create_drug_target_agent and DrugTargetConfig are imported lazily
# inside run_drug_target_assessment() to break circular import chain:
# deep_interpreter.subagents.configs → drug_target.integration
#   → drug_target.agent → drug_target.subagents.configs (cycle)


@tool
async def run_drug_target_assessment(data_dir: str, disease: str) -> str:
    """Run the Drug Target Assessment agent on lr_candidates.json.

    Delegates the full therapeutic target assessment to the DrugTargetAgent,
    which uses 2 subagents (evidence_assessor, report_writer)
    to gather evidence, score targets, and generate drug.md.

    Args:
        data_dir: Directory containing lr_candidates.json and selected_top3_lr.json
        disease: Disease context (e.g., "breast cancer", "glioblastoma")

    Returns:
        Content of drug.md with therapeutic analysis, or error message
    """
    resolved_dir = str(Path(data_dir).expanduser().resolve())
    drug_md_path = Path(resolved_dir) / "drug.md"
    target_assessment_path = Path(resolved_dir) / "target_assessment.json"

    # Check prerequisite files
    lr_path = Path(resolved_dir) / "lr_candidates.json"
    if not lr_path.exists():
        return json.dumps({
            "error": f"lr_candidates.json not found at {lr_path}",
            "drug_md": None,
        })

    try:
        # Lazy import to break circular dependency
        from src.agents.drug_target.agent import create_drug_target_agent, DrugTargetConfig

        # Get provider from environment
        provider = os.getenv("LLM_PROVIDER", "openrouter")

        config = DrugTargetConfig(
            provider=provider,
            data_dir=resolved_dir,
            disease=disease,
        )

        agent = create_drug_target_agent(config)

        # Build initial message with context
        initial_message = (
            f"Assess therapeutic potential of L-R pair genes in {resolved_dir}.\n\n"
            f"Disease context: {disease}\n"
            f"Input files: lr_candidates.json, selected_top3_lr.json\n"
            f"Output: target_assessment.json and drug.md\n\n"
            f"Execute the full evidence_assessor → report_writer pipeline."
        )

        # Run the agent
        result = await agent.ainvoke(
            {
                "messages": [{
                    "role": "user",
                    "content": initial_message,
                }]
            },
            config={"configurable": {"thread_id": str(uuid.uuid4())}},
        )

        # Read drug.md
        if drug_md_path.exists():
            content = drug_md_path.read_text()
            target_assessment = None
            if target_assessment_path.exists():
                try:
                    target_assessment = json.loads(target_assessment_path.read_text())
                except Exception as parse_err:
                    logger.warning(
                        "Failed to parse target_assessment.json at %s: %s",
                        target_assessment_path,
                        parse_err,
                    )
            return json.dumps({
                "success": True,
                "drug_md": content,
                "drug_md_path": str(drug_md_path),
                "target_assessment": target_assessment,
                "target_assessment_path": (
                    str(target_assessment_path) if target_assessment_path.exists() else None
                ),
            })
        else:
            return json.dumps({
                "success": False,
                "error": "DrugTargetAgent completed but drug.md was not generated",
                "drug_md": None,
            })

    except Exception as e:
        logger.error(f"Drug target assessment failed: {e}", exc_info=True)
        return json.dumps({
            "success": False,
            "error": str(e),
            "drug_md": None,
        })


__all__ = ["run_drug_target_assessment"]
