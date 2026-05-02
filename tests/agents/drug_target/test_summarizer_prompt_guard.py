"""Verify the T8 prompt guard is present in summarizer/report_writer/critic
prompts AND that no NEW positive instruction to call ``read_file`` for
``/evidence/`` was introduced (CP-P2-005 regression check against the existing
5 HARD prohibitions at prompts.py:246, 284, 657, 660, 672).
"""
import re

import pytest

from src.agents.drug_target.subagents import prompts as _prompts


# The guard sentence MUST appear verbatim in each target prompt.
GUARD_SUBSTRING = "load_evidence_files(data_dir)"
GUARD_HINT = "do NOT conclude the directory is empty"


# ---------------------------------------------------------------------------
# Negation-aware regex to detect POSITIVE-FORM read_file instructions
# ---------------------------------------------------------------------------
# Matches "call read_file ... evidence" or "use read_file ... evidence" UNLESS
# preceded by a negation token (NEVER, NOT, "Do NOT", "do not").
#
# Python re does not support variable-width lookbehinds. We approximate:
#   1. Find all sentence-ish chunks containing read_file+evidence.
#   2. For each, check whether any negation token precedes the read_file token
#      within the preceding ~100 characters.
_READ_FILE_NEAR_EVIDENCE = re.compile(
    r"\b(?:call|use|invoke)\b[^.]*?\bread_file\b[^.]*?\bevidence\b",
    re.IGNORECASE,
)
_NEGATION_TOKENS = ("NEVER", "NOT ", "Do NOT", "do NOT", "do not", "DO NOT")


def _has_unprotected_read_file_directive(text: str) -> list[str]:
    """Return list of positive 'call/use read_file ... evidence' chunks NOT
    immediately preceded (within ~100 chars) by a negation token."""
    findings = []
    for match in _READ_FILE_NEAR_EVIDENCE.finditer(text):
        chunk = match.group(0)
        # Look back up to 100 chars for a negation token
        start = max(0, match.start() - 100)
        preceding = text[start : match.start()]
        if not any(neg in preceding for neg in _NEGATION_TOKENS):
            findings.append(chunk)
    return findings


# ---------------------------------------------------------------------------
# Sanity checks: verify the regex behaves correctly on synthetic inputs
# ---------------------------------------------------------------------------


def test_regex_matches_synthetic_positive_instruction():
    """Sanity: the regex SHOULD match a synthetic positive instruction."""
    synthetic = "Please call read_file with the evidence file path."
    result = _has_unprotected_read_file_directive(synthetic)
    assert len(result) >= 1, (
        "Expected at least one match for a positive read_file instruction"
    )


def test_regex_does_not_match_synthetic_prohibition():
    """Sanity: the regex must NOT flag clearly-negated sentences."""
    s1 = "NEVER use `read_file` for evidence files — use load_evidence_files instead."
    s2 = "Do NOT call read_file directly under /evidence/."
    s3 = "do not use read_file for evidence files."
    assert _has_unprotected_read_file_directive(s1) == []
    assert _has_unprotected_read_file_directive(s2) == []
    assert _has_unprotected_read_file_directive(s3) == []


# ---------------------------------------------------------------------------
# Real prompts: guard sentence is present
# ---------------------------------------------------------------------------


def test_summarizer_prompt_has_guard():
    assert GUARD_SUBSTRING in _prompts.SUMMARIZER_PROMPT, (
        "SUMMARIZER_PROMPT missing 'load_evidence_files(data_dir)' guard"
    )
    assert GUARD_HINT in _prompts.SUMMARIZER_PROMPT, (
        "SUMMARIZER_PROMPT missing 'do NOT conclude the directory is empty' hint"
    )


def test_report_writer_prompt_has_guard():
    assert GUARD_SUBSTRING in _prompts.REPORT_WRITER_PROMPT, (
        "REPORT_WRITER_PROMPT missing 'load_evidence_files(data_dir)' guard"
    )
    assert GUARD_HINT in _prompts.REPORT_WRITER_PROMPT, (
        "REPORT_WRITER_PROMPT missing 'do NOT conclude the directory is empty' hint"
    )


def test_critic_prompt_has_guard():
    assert GUARD_SUBSTRING in _prompts.CRITIC_PROMPT, (
        "CRITIC_PROMPT missing 'load_evidence_files(data_dir)' guard"
    )
    assert GUARD_HINT in _prompts.CRITIC_PROMPT, (
        "CRITIC_PROMPT missing 'do NOT conclude the directory is empty' hint"
    )


# ---------------------------------------------------------------------------
# Real prompts: no NEW unprotected read_file instruction introduced
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "prompt_name,prompt_text",
    [
        ("SUMMARIZER_PROMPT", _prompts.SUMMARIZER_PROMPT),
        ("REPORT_WRITER_PROMPT", _prompts.REPORT_WRITER_PROMPT),
        ("CRITIC_PROMPT", _prompts.CRITIC_PROMPT),
    ],
)
def test_no_unprotected_read_file_instruction(prompt_name: str, prompt_text: str):
    """Regression guard: every read_file mention near 'evidence' must be
    accompanied by a negation token in the preceding context."""
    findings = _has_unprotected_read_file_directive(prompt_text)
    assert findings == [], (
        f"{prompt_name} contains positive-form read_file instruction near 'evidence' "
        f"without negation: {findings!r}"
    )
