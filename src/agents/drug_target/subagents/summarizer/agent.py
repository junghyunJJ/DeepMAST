"""Drug-target summarizer subagent — flat dict spec (DeepAgents pattern).

The 2026-05-13 simplification replaced the CompiledSubAgent + inner
``report_writer``/``critic`` + 6 middleware classes + Python repair loop
with a single dict-style subagent that owns the full report-finalization
workflow. The nine tools execute the core 6-step contract described in
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

from deepagents import SubAgentMiddleware

from src.agents.drug_target.subagents.critic import get_critic_subagent
from src.agents.drug_target.subagents.prompts import (
    CRITIC_REVIEW_STEP_FRAGMENT,
    SUMMARIZER_PROMPT_CORE,
)
from src.agents.drug_target.subagents.summarizer.middleware import (
    CriticGateMiddleware,
    SummarizerFinalizationGuardMiddleware,
)
from src.agents.drug_target.tools import (
    build_evidence_summary,
    generate_drug_html_report,
    load_evidence_files,
    lookup_provenance_value,
    render_drug_md_from_expansions,
    read_skill_file,
    save_report_expansions,
    think_tool,
    validate_drug_md,
)


def get_summarizer_subagent(
    backend: object | None = None,
    default_model: object | None = None,  # noqa: ARG001 — reserved for future model routing
    critic_model: object | None = None,
    critic_enabled: bool = True,
) -> dict[str, Any]:
    """Return the summarizer DeepAgents dict spec.

    The dict contains the five canonical fields used by DeepAgents'
    ``SubAgent`` TypedDict: ``name``, ``description``, ``system_prompt``,
    ``tools``, and ``middleware``.

    Args:
        backend: Backend passed to ``SubAgentMiddleware`` when critic is
            enabled. Required when ``critic_enabled=True``.
        default_model: Reserved for task #10 (prompt assembly).
        critic_model: Resolved critic model forwarded to
            ``get_critic_subagent(model=...)``. Required when
            ``critic_enabled=True``.
        critic_enabled: When ``True``, installs a nested
            ``SubAgentMiddleware`` with the critic spec so the summarizer
            can invoke the critic via the ``task`` tool. When ``False``,
            no ``SubAgentMiddleware`` is installed and the summarizer
            functions exactly as before task #4.

    Returns:
        A subagent spec consumable by ``create_deep_agent(subagents=[...])``.
    """
    middlewares: list[object] = [
        SummarizerFinalizationGuardMiddleware(),
    ]

    if critic_enabled and critic_model is None:
        raise ValueError(
            "critic_enabled=True requires a resolved critic_model; "
            "set SUBAGENT_CRITIC_PROVIDER + SUBAGENT_CRITIC_MODEL env vars, "
            "or pass critic_model explicitly to get_summarizer_subagent()."
        )

    if critic_enabled:
        critic_spec = get_critic_subagent(model=critic_model)
        middlewares.append(CriticGateMiddleware())
        middlewares.append(
            SubAgentMiddleware(backend=backend, subagents=[critic_spec])
        )

    if critic_enabled:
        system_prompt = SUMMARIZER_PROMPT_CORE + "\n\n" + CRITIC_REVIEW_STEP_FRAGMENT
    else:
        system_prompt = SUMMARIZER_PROMPT_CORE

    return {
        "name": "summarizer",
        "description": (
            "Authors and finalizes drug.md for the analyzed gene set. "
            "Tool surface: build_evidence_summary, load_evidence_files, "
            "lookup_provenance_value, save_report_expansions, "
            "render_drug_md_from_expansions, validate_drug_md (mandatory "
            "quality gate), then generate_drug_html_report. Emits "
            "SUMMARIZER_STATUS: PASS or SUMMARIZER_STATUS: FAIL on its own "
            "line at the end of the run."
        ),
        "system_prompt": system_prompt,
        "tools": [
            build_evidence_summary,
            load_evidence_files,
            lookup_provenance_value,
            save_report_expansions,
            render_drug_md_from_expansions,
            read_skill_file,
            validate_drug_md,
            generate_drug_html_report,
            think_tool,
        ],
        "middleware": middlewares,
    }


__all__ = [
    "get_summarizer_subagent",
]
