"""Reporter integration tool for Drug Target Assessment Agent.

Provides run_drug_target_assessment() as a single @tool that the Reporter
subagent calls to delegate the entire Step 9.5 drug target assessment
to the DrugTargetAgent.
"""

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path

from langchain_core.tools import tool
from src.agents.drug_target.tools.assessment_output import (
    validate_target_assessment_file,
)
from src.agents.drug_target.tools.stage1_normalization import (
    finalize_stage1_workspace,
)

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
        data_dir: Directory containing lr_candidates.json
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
        if os.getenv("LANGSMITH_TRACING", "").lower() == "true" and not os.getenv(
            "DISABLE_RUN_COMPRESSION"
        ):
            os.environ["DISABLE_RUN_COMPRESSION"] = "true"
            logger.info(
                "Enabled DISABLE_RUN_COMPRESSION for drug-target runtime while keeping LANGSMITH_TRACING=true"
            )

        config = DrugTargetConfig(
            provider=provider,
            data_dir=resolved_dir,
            disease=disease,
        )

        agent, backend = await asyncio.to_thread(create_drug_target_agent, config)

        try:
            # Natural language message — data_dir and disease are already
            # injected into the system prompt via DrugTargetConfig.
            initial_message = (
                f"Run the full drug target assessment pipeline for {disease}."
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
        finally:
            if backend and hasattr(backend, "cleanup"):
                backend.cleanup()

        stage1_result = await asyncio.to_thread(
            finalize_stage1_workspace,
            resolved_dir,
            disease=disease,
            rerun_missing_census=True,
        )
        target_assessment_validation = await asyncio.to_thread(
            validate_target_assessment_file, resolved_dir
        )

        # Read drug.md — wrap file I/O in thread to avoid blocking async loop
        def _read_results():
            if stage1_result["success"] and target_assessment_validation["valid"] and drug_md_path.exists():
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
                    "stage1_validation": stage1_result["post_validation"],
                    "target_assessment_validation": target_assessment_validation,
                    "target_assessment_path": (
                        str(target_assessment_path) if target_assessment_path.exists() else None
                    ),
                })
            else:
                errors: list[str] = []
                if not stage1_result["success"]:
                    errors.append(
                        "Stage1 artifacts incomplete: "
                        + "; ".join(stage1_result["post_validation"]["errors"])
                    )
                if not target_assessment_validation["valid"]:
                    errors.append(
                        "target_assessment validation failed: "
                        + "; ".join(target_assessment_validation["errors"])
                    )
                if not drug_md_path.exists():
                    errors.append("drug.md was not generated")
                return json.dumps({
                    "success": False,
                    "error": " | ".join(errors) if errors else "DrugTargetAgent artifacts incomplete",
                    "drug_md": None,
                    "stage1_validation": stage1_result["post_validation"],
                    "target_assessment_validation": target_assessment_validation,
                })

        return await asyncio.to_thread(_read_results)

    except Exception as e:
        logger.error("Drug target assessment failed: %s", e, exc_info=True)
        return json.dumps({
            "success": False,
            "error": str(e),
            "drug_md": None,
        })


__all__ = ["run_drug_target_assessment"]
