"""Reporter integration tool for Drug Target Assessment Agent.

Provides run_drug_target_assessment() as a single @tool that the Reporter
subagent calls to delegate the entire Step 9.5 drug target assessment
to the DrugTargetAgent super-graph.
"""

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# NOTE: drug_target_graph is imported lazily inside run_drug_target_assessment()
# to break the circular import chain:
# deep_interpreter.subagents.configs → drug_target.integration
#   → drug_target.graph_builder → drug_target.super_graph (cycle)


@tool
async def run_drug_target_assessment(data_dir: str, disease: str) -> str:
    """Run the Drug Target Assessment agent on lr_candidates.json.

    Delegates the full therapeutic target assessment to the drug-target
    super-graph (START → run_deep_agent → finalize_report → END), which
    uses 2 top-level subagents (evidence_assessor, hypothesis_writer) to
    gather evidence, score targets, generate hypotheses, and produce an
    audited drug.md via the deterministic finalize_report node.

    Args:
        data_dir: Directory containing lr_candidates.json
        disease: Disease context (e.g., "breast cancer", "glioblastoma")

    Returns:
        JSON string with keys: success, drug_md, target_assessment, errors,
        evidence_truncated.
    """
    resolved_dir = str(Path(data_dir).expanduser().resolve())

    # Check prerequisite files
    lr_path = Path(resolved_dir) / "lr_candidates.json"
    if not await asyncio.to_thread(lr_path.exists):
        return json.dumps({
            "success": False,
            "drug_md": None,
            "target_assessment": None,
            "errors": [f"lr_candidates.json not found at {lr_path}"],
            "evidence_truncated": False,
        })

    _prev_disable_rc = os.environ.get("DISABLE_RUN_COMPRESSION")
    try:
        if os.getenv("LANGSMITH_TRACING", "").lower() == "true" and not _prev_disable_rc:
            os.environ["DISABLE_RUN_COMPRESSION"] = "true"
            logger.info(
                "Temporarily set DISABLE_RUN_COMPRESSION for drug-target runtime"
            )

        # Lazy import to break circular dependency
        from src.agents.drug_target.graph_builder import drug_target_graph

        initial_state = {
            "messages": [],
            "data_dir": resolved_dir,
            "disease": disease,
            "featured_lr_pairs": None,
            "report_finalization_error": None,
            "evidence_truncated": False,
        }

        # recursion_limit is a top-level RunnableConfig key (NOT under configurable).
        final_state = await drug_target_graph.ainvoke(
            initial_state,
            config={
                "recursion_limit": 10000,
                "configurable": {"thread_id": str(uuid.uuid4())},
            },
        )

        finalization_error: str | None = final_state.get("report_finalization_error")
        evidence_truncated: bool = final_state.get("evidence_truncated", False)

        if finalization_error is not None:
            envelope = {
                "success": False,
                "drug_md": None,
                "target_assessment": None,
                "errors": [finalization_error],
                "evidence_truncated": evidence_truncated,
            }
        else:
            drug_md_path = Path(resolved_dir) / "drug.md"
            target_assessment_path = Path(resolved_dir) / "target_assessment.json"
            drug_md = await asyncio.to_thread(drug_md_path.read_text, encoding="utf-8")
            target_assessment_raw = await asyncio.to_thread(
                target_assessment_path.read_text,
                encoding="utf-8",
            )
            target_assessment = json.loads(target_assessment_raw)
            envelope = {
                "success": True,
                "drug_md": drug_md,
                "target_assessment": target_assessment,
                "errors": [],
                "evidence_truncated": evidence_truncated,
            }

        return json.dumps(envelope, ensure_ascii=False)

    except Exception as exc:
        logger.error("Drug target assessment failed: %s", exc, exc_info=True)
        return json.dumps({
            "success": False,
            "drug_md": None,
            "target_assessment": None,
            "errors": [str(exc)],
            "evidence_truncated": False,
        })
    finally:
        # Restore DISABLE_RUN_COMPRESSION to its original state
        if _prev_disable_rc is None:
            os.environ.pop("DISABLE_RUN_COMPRESSION", None)
        else:
            os.environ["DISABLE_RUN_COMPRESSION"] = _prev_disable_rc


__all__ = ["run_drug_target_assessment"]
