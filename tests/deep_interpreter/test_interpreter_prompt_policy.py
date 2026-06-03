"""Prompt policy tests for the INTERPRETER subagent.

Verifies that the Phase 4 block in the INTERPRETER production prompt
encodes the Steps A-E reflection-driven quality loop with the correct
ordering (think_tool BEFORE validate_quality), the correct call-site
kwargs (score_threshold=0.8 on think_tool, use_llm=False on
validate_quality), and the correct consumer-side gate semantics.

These are string/structural checks — no live LLM call.
"""

from __future__ import annotations

import re

import pytest

from src.agents.deep_interpreter.subagents.prompts import SUBAGENT_PROMPTS
from src.agents.deep_interpreter.subagents.configs import SUBAGENT_CONFIGS


INTERPRETER_PROMPT = SUBAGENT_PROMPTS["interpreter"]


def _extract_phase4_block() -> str:
    """Extract the Phase 4 reflection/quality-loop block from INTERPRETER prompt.

    The block starts at the Phase 4 heading and ends at the next Phase heading.
    """
    match = re.search(
        r"### Phase 4:.*?(?=### Phase 5:)",
        INTERPRETER_PROMPT,
        flags=re.DOTALL,
    )
    assert match, "Could not locate Phase 4 block in INTERPRETER prompt"
    return match.group(0)


def test_phase4_block_contains_think_tool():
    block = _extract_phase4_block()
    assert "think_tool" in block, "Phase 4 block must reference think_tool"


def test_phase4_block_contains_validate_quality():
    block = _extract_phase4_block()
    assert "validate_quality" in block, "Phase 4 block must reference validate_quality"


def test_phase4_block_mentions_revision_or_completeness():
    block = _extract_phase4_block()
    revision_terms = ["revision", "revise", "completeness", "reflect"]
    assert any(term in block.lower() for term in revision_terms), (
        f"Phase 4 block must mention one of {revision_terms} to encode the "
        f"revision/reflection loop semantics."
    )


def test_phase4_think_tool_before_validate_quality():
    """Ordering: think_tool (Step B) must appear BEFORE validate_quality (Step D)."""
    block = _extract_phase4_block()
    think_idx = block.index("think_tool")
    vq_idx = block.index("validate_quality")
    assert think_idx < vq_idx, (
        f"Phase 4 ordering violated: think_tool at {think_idx} must precede "
        f"validate_quality at {vq_idx}. Step B (reflect) comes BEFORE Step D "
        f"(deterministic checkpoint)."
    )


def test_phase4_contains_score_threshold_0_8_on_think_tool():
    """score_threshold=0.8 must appear in the Phase 4 block."""
    block = _extract_phase4_block()
    assert "score_threshold=0.8" in block, (
        "Phase 4 block must pass score_threshold=0.8 at the think_tool call site."
    )


def test_phase4_contains_use_llm_false():
    block = _extract_phase4_block()
    assert "use_llm=False" in block, (
        "Phase 4 block must set use_llm=False on validate_quality to avoid a "
        "duplicate reflection-tool MCP call."
    )


def test_phase4_validate_quality_does_not_accept_score_threshold():
    """Regex regression guard: no validate_quality(... score_threshold=...) call site."""
    block = _extract_phase4_block()

    # Find each validate_quality call site and ensure score_threshold is not
    # a kwarg in that call.
    # validate_quality signature is (interpretation, references, use_llm);
    # score_threshold would be a consumer-side drift.
    pattern = re.compile(
        r"validate_quality\s*\(([^)]*)\)",
        flags=re.DOTALL,
    )
    for match in pattern.finditer(block):
        call_args = match.group(1)
        assert "score_threshold" not in call_args, (
            "validate_quality call site must NOT contain score_threshold — "
            "the 0.8 gate is a consumer-side comparison (Step E), not a tool kwarg. "
            f"Offending call: validate_quality({call_args})"
        )


def test_phase4_score_threshold_is_attached_to_think_tool_call():
    """score_threshold=0.8 must appear inside a think_tool(...) call, not floating."""
    block = _extract_phase4_block()
    # Find think_tool call sites and confirm at least one contains score_threshold=0.8.
    pattern = re.compile(
        r"think_tool\s*\(([^)]*)\)",
        flags=re.DOTALL,
    )
    matched = False
    for match in pattern.finditer(block):
        if "score_threshold=0.8" in match.group(1):
            matched = True
            break
    assert matched, (
        "score_threshold=0.8 must be attached to a think_tool(...) call site in "
        "Phase 4 (Step B), not floating in prose."
    )


def test_phase4_labels_consumer_side_comparison():
    """Step E must be labeled as a Consumer-side comparison to prevent future drift."""
    block = _extract_phase4_block()
    assert re.search(r"[Cc]onsumer[- ]side", block), (
        "Phase 4 block must label Step E explicitly as a 'Consumer-side comparison' "
        "so future maintainers do not mistakenly add score_threshold=0.8 to "
        "validate_quality."
    )


def test_interpreter_prompt_treats_papers_json_as_filtered_handoff():
    prompt = INTERPRETER_PROMPT

    assert "filtered" in prompt.lower()
    assert "evidence_bucket" in prompt
    assert "direct_lr_evidence" in prompt
    assert "receptor_pathway_context_evidence" in prompt
    assert "disease_only_background" in prompt
    assert "rejected_weak_evidence" in prompt
    assert "context-level" in prompt.lower()
    assert "partN_papers" not in prompt
    assert "/part1_papers" not in prompt
    assert "/part2_papers" not in prompt
    assert "/part3_papers" not in prompt


def test_interpreter_config_uses_filtered_shared_papers_json():
    description = SUBAGENT_CONFIGS["interpreter"]["description"]

    assert "filtered /papers.json" in description
    assert "partN_papers" not in description
