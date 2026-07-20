"""Reporter integration tool for the guarded direct Drug Target agent.

Each call creates an ``evidence_assessor``/``report_writer`` agent with
``DrugReportGuardrailMiddleware``. Success requires a passed final audit and
all required report-section, report, publication, and audit artifacts.
"""

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
from typing import cast

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

_SUCCESS_ARTIFACTS = (
    "drug.md",
    "target_assessment.json",
    "report_sections.json",
    "part4_candidate_selection.json",
    "part4_therapeutic_synthesis.md",
    "drug_report.html",
    "drug_report_validation_initial.json",
    "drug_report_validation_final.json",
)


@tool
async def run_drug_target_assessment(data_dir: str, disease: str) -> str:
    """Run the Drug Target Assessment agent on lr_candidates.json.

    Builds a guarded direct agent for this data directory, asks it to run the
    assessment, and returns success only after its final audit and every
    required report/publication artifact pass the completion gate.

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

        # Lazy imports preserve the Reporter integration circular-import boundary.
        from src.agents.drug_target.agent import (
            DrugTargetConfig,
            Provider,
            create_drug_target_agent,
        )
        from src.agents.drug_target.report_guardrails import clear_derived_report_artifacts

        await asyncio.to_thread(
            clear_derived_report_artifacts,
            resolved_dir,
            include_audits=True,
            include_sources=True,
        )
        config = DrugTargetConfig(
            provider=cast(Provider, os.getenv("LLM_PROVIDER", "openrouter")),
            data_dir=resolved_dir,
            disease=disease,
            use_checkpointer=False,
            workflow_mode="guarded_report",
        )
        agent, backend = await asyncio.to_thread(create_drug_target_agent, config)
        try:
            await agent.ainvoke(
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                f"Run the drug-target assessment for {disease}. "
                                f"Data directory: {resolved_dir}."
                            ),
                        }
                    ]
                },
                config={
                    "recursion_limit": 10000,
                    "configurable": {"thread_id": str(uuid.uuid4())},
                },
            )
        finally:
            cleanup = getattr(backend, "cleanup", None)
            if callable(cleanup):
                await asyncio.to_thread(cleanup)

        final_audit_raw = await asyncio.to_thread(
            (Path(resolved_dir) / "drug_report_validation_final.json").read_text,
            encoding="utf-8",
        )
        final_audit = json.loads(final_audit_raw)
        publication = final_audit.get("publication", {}) if isinstance(final_audit, dict) else {}
        if (
            not isinstance(final_audit, dict)
            or final_audit.get("valid") is not True
            or not isinstance(publication, dict)
            or publication.get("status") != "passed"
        ):
            return json.dumps({
                "success": False,
                "drug_md": None,
                "target_assessment": None,
                "errors": ["drug-target final audit did not pass publication"],
                "evidence_truncated": False,
            })

        if any(
            not (Path(resolved_dir) / name).is_file()
            or (Path(resolved_dir) / name).stat().st_size == 0
            for name in _SUCCESS_ARTIFACTS
        ):
            return json.dumps({
                "success": False,
                "drug_md": None,
                "target_assessment": None,
                "errors": ["drug-target guarded artifacts are incomplete"],
                "evidence_truncated": False,
            })

        artifact_texts = {
            name: await asyncio.to_thread(
                (Path(resolved_dir) / name).read_text,
                encoding="utf-8",
            )
            for name in _SUCCESS_ARTIFACTS
        }
        return json.dumps({
            "success": True,
            "drug_md": artifact_texts["drug.md"],
            "target_assessment": json.loads(artifact_texts["target_assessment.json"]),
            "errors": [],
            "evidence_truncated": False,
        }, ensure_ascii=False)

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
