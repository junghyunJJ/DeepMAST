"""Prompt policy tests for the INTERPRETER subagent.

Verifies that the INTERPRETER production prompt keeps grounding constraints
while treating think_tool and validate_quality as optional/advisory checks.

These are string/structural checks — no live LLM call.
"""

from __future__ import annotations

import re

from src.agents.deep_interpreter.subagents.prompts import SUBAGENT_PROMPTS
from src.agents.deep_interpreter.subagents.configs import SUBAGENT_CONFIGS


INTERPRETER_PROMPT = SUBAGENT_PROMPTS["interpreter"]


def _extract_phase4_block() -> str:
    """Extract the Phase 4 quality-policy block from INTERPRETER prompt."""
    match = re.search(
        r"### Phase 4:.*?(?=### Phase 5:)",
        INTERPRETER_PROMPT,
        flags=re.DOTALL,
    )
    assert match, "Could not locate Phase 4 block in INTERPRETER prompt"
    return match.group(0)


def test_phase4_keeps_quality_tools_advisory():
    block = _extract_phase4_block()

    assert "think_tool" in block
    assert "validate_quality" in block
    assert "optional" in block.lower() or "advisory" in block.lower()


def test_phase4_removes_reflection_hard_gate_language():
    block = _extract_phase4_block()

    forbidden = [
        "MANDATORY think_tool",
        "score_threshold=0.8",
        "score_threshold = 0.8",
        "max_iterations=3",
        "Max 3 total iterations",
        "Consumer-side comparison",
        "return to Step B",
        "score < 0.8",
        "result['score'] < 0.8",
    ]
    for phrase in forbidden:
        assert phrase not in block


def test_phase4_sends_final_quality_to_downstream_guardrail():
    block = _extract_phase4_block()

    assert "downstream" in block.lower()
    assert "validate_report.py" in block
    assert "repair_report.py" in block


def test_interpreter_quality_requirements_do_not_set_numeric_gate():
    prompt = INTERPRETER_PROMPT

    assert "Quality threshold: 0.8" not in prompt
    assert "Quality Score Met" not in prompt
    assert "quality score from validate_quality is >= 0.8" not in prompt


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


def test_part3_uses_part4_candidate_selection_selected_genes_and_lr_pairs():
    prompt = INTERPRETER_PROMPT
    description = SUBAGENT_CONFIGS["interpreter"]["description"]

    assert "part4_candidate_selection.json" in prompt
    assert "selected_genes" in prompt
    assert "selected_lr_pairs" in prompt
    assert "part4_candidate_selection.json" in description
    assert "selected_genes" in description
    assert "selected_lr_pairs" in description


def test_part3_no_longer_selects_featured_candidates_from_target_assessment():
    match = re.search(
        r"### Part 3 \(L-R Interaction Details\).*?(?=## Quality Requirements)",
        INTERPRETER_PROMPT,
        flags=re.DOTALL,
    )
    assert match, "Could not locate Part 3 block in INTERPRETER prompt"
    part3_block = match.group(0)

    assert "is_featured" not in part3_block
    assert "druggability_matrix" not in part3_block
    assert "target_assessment.json" not in part3_block


def test_part3_excludes_part4_therapeutic_synthesis_scope():
    prompt = INTERPRETER_PROMPT

    assert "part4_therapeutic_synthesis.md" in prompt
    assert "must not read" in prompt.lower()
    assert "therapeutic synthesis" in prompt.lower()
    assert "Part 4" in prompt


def test_interpreter_rag_fulltext_tools_pass_explicit_data_dir():
    prompt = INTERPRETER_PROMPT

    assert re.search(
        r"search_literature_fulltext\s*\([^)]*data_dir=data_path\.strip\(\)",
        prompt,
        flags=re.DOTALL,
    ), "INTERPRETER search_literature_fulltext calls must pass explicit data_dir"
    assert "- data_dir: data_path.strip()" in prompt


def test_interpreter_prompt_mentions_sni_navigation_not_citation_evidence():
    prompt = INTERPRETER_PROMPT

    assert "SNI" in prompt
    assert "LLM Wiki" in prompt
    assert "navigation" in prompt.lower()
    assert "not citation evidence" in prompt.lower()


def test_interpreter_prompt_says_search_uses_sni_promotion_when_available():
    prompt = INTERPRETER_PROMPT

    assert "search_literature_fulltext" in prompt
    assert "SNI promotion" in prompt
    assert "fallback" in prompt.lower()
