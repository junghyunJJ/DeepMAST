"""Drug-target summarizer subagent — flat dict spec (DeepAgents pattern).

The 2026-05-13 simplification replaced the CompiledSubAgent + inner
``report_writer``/``critic`` + 6 middleware classes + Python repair loop
with a single dict-style subagent that owns the full report-finalization
workflow. The seven tools execute the 6-step contract described in
``SUMMARIZER_PROMPT``:

    build_evidence_summary -> load_evidence_files -> save_report_expansions
        -> render_drug_md_from_expansions -> validate_drug_md
        -> generate_drug_html_report -> emit SUMMARIZER_STATUS: PASS|FAIL

Quality gating is twofold:

1. Semantic gate — ``validate_drug_md`` returns ``{"valid": bool, ...}``.
2. Mechanical gate — ``SummarizerFinalizationGuardMiddleware`` blocks
   ``generate_drug_html_report`` unless the most recent ``validate_drug_md``
   call returned ``valid=true``. The summarizer LLM can therefore not
   declare ``SUMMARIZER_STATUS: PASS`` without a real validator pass when
   the final HTML render is attempted.
"""

from __future__ import annotations

from typing import Any

from src.agents.drug_target.subagents.prompts import SUMMARIZER_PROMPT
from src.agents.drug_target.subagents.summarizer.middleware import (
    SummarizerFinalizationGuardMiddleware,
)
from src.agents.drug_target.tools import (
    build_evidence_summary,
    generate_drug_html_report,
    load_evidence_files,
    render_drug_md_from_expansions,
    save_report_expansions,
    think_tool,
    validate_drug_md,
)


def get_summarizer_subagent() -> dict[str, Any]:
    """Return the summarizer DeepAgents dict spec.

    The dict contains the five canonical fields used by DeepAgents'
    ``SubAgent`` TypedDict: ``name``, ``description``, ``system_prompt``,
    ``tools``, and ``middleware``.

    Returns:
        A subagent spec consumable by ``create_deep_agent(subagents=[...])``.
    """
    return {
        "name": "summarizer",
        "description": (
            "Authors and finalizes drug.md for the analyzed gene set. "
            "Executes the 6-step tool sequence: build_evidence_summary, "
            "load_evidence_files, save_report_expansions, "
            "render_drug_md_from_expansions, validate_drug_md (mandatory "
            "quality gate), then generate_drug_html_report. Emits "
            "SUMMARIZER_STATUS: PASS or SUMMARIZER_STATUS: FAIL on its own "
            "line at the end of the run."
        ),
        "system_prompt": SUMMARIZER_PROMPT,
        "tools": [
            build_evidence_summary,
            load_evidence_files,
            save_report_expansions,
            render_drug_md_from_expansions,
            validate_drug_md,
            generate_drug_html_report,
            think_tool,
        ],
        "middleware": [
            SummarizerFinalizationGuardMiddleware(),
        ],
    }


__all__ = [
    "get_summarizer_subagent",
]
