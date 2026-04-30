"""CriticOutput TypedDict schema for the Drug Target Assessment critic subagent.

This module defines the structured output contract for the read-only critic.
All keys in CriticOutput are backward-compatible with the existing CRITIC_PROMPT
JSON envelope; Finding gains two additive fields (claim_text, source_field) and
claim_verdicts is a new top-level list.
"""

from __future__ import annotations

from typing import Literal

from typing_extensions import TypedDict

__all__ = [
    "Finding",
    "ClaimVerdict",
    "CriticOutput",
]


class Finding(TypedDict):
    """A single audit finding from the critic.

    Legacy fields (severity, issue, evidence, repair) are preserved unchanged.
    New additive fields (claim_text, source_field) enable per-claim grounding.
    """

    severity: Literal["P0", "P1", "P2", "P3"]
    issue: str
    evidence: str
    repair: str
    # Additive — new in T18
    claim_text: str
    source_field: str | None


class ClaimVerdict(TypedDict):
    """Per-claim grounding verdict for a factual sentence in Sections 1, 3, or 4."""

    section: Literal["section_1", "section_3", "section_4"]
    claim_text: str
    verdict: Literal["PASS", "FAIL"]
    source_field: str | None
    reason: str


class CriticOutput(TypedDict):
    """Full structured output returned by the critic subagent.

    Backward-compatible with the existing critic JSON envelope.
    claim_verdicts is a new top-level list (additive, non-breaking).
    """

    passed: bool
    severity_counts: dict[str, int]
    checked_gates: list[str]
    findings: list[Finding]
    repair_instructions: list[str]
    # Additive — new in T18
    claim_verdicts: list[ClaimVerdict]
