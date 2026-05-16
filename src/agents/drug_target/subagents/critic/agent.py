"""Drug-target critic subagent — read-only review spec (DeepAgents pattern).

The critic is a summarizer-local subagent.  It is NOT a top-level workflow
stage and must NOT appear in WORKFLOW_ORDER or the top-level subagent list.

The critic reviews the full EXPAND slot payload before ``save_report_expansions``
is called.  It returns structured JSON findings.  It never writes files.

Middleware contract (``CriticGateMiddleware``, task #7):
- ``valid=true`` with matching ``payload_hash`` → save allowed.
- ``valid=false`` or hash mismatch → save blocked.

Prompt source: Appendix A of
  .omb/plans/2026-05-15-drug-target-critic-subagent-replan.md
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Appendix A critic prompt (≤2000 tokens, schema_version v1)
# ---------------------------------------------------------------------------

_CRITIC_PROMPT = """\
You are the read-only critic for the drug_target summarizer.
You review a pre-save EXPAND payload. You never write files.

Input is JSON with schema_version="summarizer_critic_review.v1",
payload_hash, payload, and cited-only provenance_context.

Judge only whether each sentence is supported by its cited source/provenance
text. Do not judge whether a medical claim is generally true. If a sentence
is plausible but not supported by the cited text, mark it blocker.

Also flag boilerplate: the same substantive sentence reused across multiple
slot_ids without slot-specific wording.

Return JSON only:
{
  "valid": boolean,
  "payload_hash": string,
  "findings_count": number,
  "findings": [
    {
      "finding_type": "BOILERPLATE_DUPLICATE|EXTERNAL_KNOWLEDGE_INJECT",
      "severity": "blocker|warning",
      "slot_ids": ["..."],
      "sentence": "...",
      "reason": "...",
      "repair_instruction": "..."
    }
  ]
}

valid=false if any blocker finding exists. Warnings do not block save.

Worked example, pass:

{
  "valid": true,
  "payload_hash": "sha256:example-pass",
  "findings_count": 0,
  "findings": []
}

Worked example, reject:

{
  "valid": false,
  "payload_hash": "sha256:example-reject",
  "findings_count": 1,
  "findings": [
    {
      "finding_type": "EXTERNAL_KNOWLEDGE_INJECT",
      "severity": "blocker",
      "slot_ids": ["section_3_mmp7"],
      "sentence": "MMP7 modulates TGF-beta signaling and fibrotic remodeling.",
      "reason": "The cited source lists drug evidence but does not support TGF-beta or fibrotic-remodeling claims.",
      "repair_instruction": "Remove the unsupported mechanism or cite a source_value that actually contains it."
    }
  ]
}
"""


def get_critic_subagent(
    model: str,
    *,
    response_format_pydantic_compatible: bool = False,
) -> dict[str, Any]:
    """Return the critic DeepAgents dict spec.

    Args:
        model: Explicit model identifier (e.g. ``"gpt-4o"``).  DeepAgents
            rejects declarative subagents without a model, so this argument
            is required and has no default.
        response_format_pydantic_compatible: When ``True``, attach a Pydantic
            ``response_format`` schema matching the Appendix A JSON shape.
            When ``False`` (default), the JSON contract is prompt-only and
            downstream middleware parses the text output.

    Returns:
        A subagent spec dict consumable by ``SubAgentMiddleware(subagents=[...])``.
        Keys: ``name``, ``model``, ``tools``, ``system_prompt``, and
        optionally ``response_format``.
    """
    spec: dict[str, Any] = {
        "name": "critic",
        "description": (
            "Read-only critic that reviews the EXPAND slot payload before "
            "save_report_expansions is called. Returns structured JSON with "
            "valid=true/false, payload_hash, and per-sentence findings. "
            "Never writes files. Call proactively before every save."
        ),
        "model": model,
        "tools": [],
        "system_prompt": _CRITIC_PROMPT,
    }

    if response_format_pydantic_compatible:
        spec["response_format"] = _build_response_format()

    return spec


def _build_response_format() -> type:
    """Build and return the Pydantic response_format model for the critic.

    The schema mirrors the Appendix A JSON contract exactly.  Returned as a
    class (not an instance) so DeepAgents / LangChain ``response_format``
    wiring can call ``.model_json_schema()`` on it.
    """
    from pydantic import BaseModel, Field  # noqa: PLC0415

    class CriticFinding(BaseModel):
        finding_type: str = Field(
            description="BOILERPLATE_DUPLICATE or EXTERNAL_KNOWLEDGE_INJECT"
        )
        severity: str = Field(description="blocker or warning")
        slot_ids: list[str] = Field(description="Affected slot identifiers")
        sentence: str = Field(description="The verbatim sentence being flagged")
        reason: str = Field(description="Why this sentence is flagged")
        repair_instruction: str = Field(
            description="How the summarizer should fix the sentence"
        )

    class CriticReviewOutput(BaseModel):
        valid: bool = Field(
            description="True if no blocker findings; false otherwise"
        )
        payload_hash: str = Field(
            description="Canonical SHA-256 hash of the reviewed payload"
        )
        findings_count: int = Field(description="Total number of findings")
        findings: list[CriticFinding] = Field(
            description="Per-sentence findings (empty list when valid=true)"
        )

    return CriticReviewOutput


__all__ = [
    "get_critic_subagent",
]
