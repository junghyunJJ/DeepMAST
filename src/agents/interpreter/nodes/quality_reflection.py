"""Quality reflection node for Deep Agent.

This module implements the quality reflection and refinement loop
for validating and improving the analysis synthesis.
"""

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from src.agents.interpreter.biological_interpreter_state import (
    BiologicalInterpreterState,
    ReflectionResult,
)
from src.agents.interpreter.nodes.synthesis import targeted_synthesis_update


REFLECTION_SYSTEM_PROMPT = """You are a senior computational biologist reviewing an analysis synthesis.
Your task is to critically evaluate the quality and validity of the findings.

Evaluation criteria:
1. **Biological Plausibility** (0-1): Are the claims biologically reasonable?
2. **Evidence Coverage** (0-1): Are claims well-supported by the data?
3. **Cross-Part Consistency** (0-1): Do findings from different parts align?

Be critical but constructive. Identify specific issues that can be improved.
"""


async def reflect_on_quality(
    state: BiologicalInterpreterState,
    model: BaseChatModel,
    is_debug: bool = False,
) -> ReflectionResult:
    """Evaluate the quality of the synthesis and decide whether to refine.

    Args:
        state: Current agent state
        model: LLM for reflection
        is_debug: Debug flag

    Returns:
        ReflectionResult with decision and scores
    """
    narrative = state.get("integrated_narrative", "")
    claims = state.get("claims", [])
    literature_evidence = state.get("literature_evidence", {})

    # Compile claims with evidence
    claims_summary = []
    for claim in claims:
        claim_id = claim.get("claim_id", "")
        content = claim.get("content", "")
        confidence = claim.get("confidence", 0)
        evidence = claim.get("supporting_evidence", [])
        lit_refs = literature_evidence.get(claim_id, [])

        claims_summary.append(
            f"**{claim_id}** (confidence: {confidence:.2f}):\n"
            f"  Content: {content}\n"
            f"  Evidence: {', '.join(evidence[:3])}\n"
            f"  Literature: {len(lit_refs)} references"
        )

    # Get pathway comparison for consistency check
    pathway_comparison = state.get("pathway_comparison", {})
    consistent_pathways = sum(1 for comp in pathway_comparison.values() if comp.get("consistent", False))
    total_pathways = len(pathway_comparison)

    prompt = f"""## Quality Reflection

**Narrative** (truncated):
{narrative[:1500]}...

**Claims**:
{chr(10).join(claims_summary)}

**Pathway Consistency**: {consistent_pathways}/{total_pathways} pathways consistent between Part1 and Part2

---

## Evaluation Tasks

Please evaluate the synthesis on these criteria:

1. **Biological Plausibility** (0.0-1.0):
   - Are the L-R interactions biologically reasonable?
   - Do pathway associations make sense?
   - Are cell type relationships plausible?

2. **Evidence Coverage** (0.0-1.0):
   - Are all major claims supported by data?
   - Is literature evidence provided?
   - Are confidence levels appropriate?

3. **Cross-Part Consistency** (0.0-1.0):
   - Do Part1-2-3 findings align?
   - Are pathway results consistent?
   - Do spatial patterns match biological expectations?

After evaluation, decide:
- **PASS**: All scores ≥ 0.7, no critical issues
- **REFINE**: Any score < 0.7 or critical issues identified

Provide your response in this format:
```json
{{
    "decision": "pass" or "refine",
    "biological_plausibility_score": <0.0-1.0>,
    "evidence_coverage_score": <0.0-1.0>,
    "cross_part_consistency_score": <0.0-1.0>,
    "issues": ["issue1", "issue2"],
    "refinement_targets": ["target1", "target2"]
}}
```
"""

    messages = [
        SystemMessage(content=REFLECTION_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]

    response = await model.ainvoke(messages)

    # Parse response
    result = parse_reflection_response(response.content, is_debug)

    if is_debug:
        print(f"Reflection decision: {result['decision']}")
        print(f"Scores: bio={result['biological_plausibility_score']:.2f}, "
              f"evidence={result['evidence_coverage_score']:.2f}, "
              f"consistency={result['cross_part_consistency_score']:.2f}")

    return result


def parse_reflection_response(response_text: str, is_debug: bool = False) -> ReflectionResult:
    """Parse the reflection response.

    Args:
        response_text: Raw LLM response
        is_debug: Debug flag

    Returns:
        ReflectionResult
    """
    import json
    import re

    # Try to extract JSON
    json_match = re.search(r'\{[\s\S]*\}', response_text)

    if json_match:
        try:
            data = json.loads(json_match.group())

            return ReflectionResult(
                decision=data.get("decision", "pass").lower(),
                biological_plausibility_score=float(data.get("biological_plausibility_score", 0.7)),
                evidence_coverage_score=float(data.get("evidence_coverage_score", 0.7)),
                cross_part_consistency_score=float(data.get("cross_part_consistency_score", 0.7)),
                issues=data.get("issues", []),
                refinement_targets=data.get("refinement_targets", []),
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            if is_debug:
                print(f"Reflection parse error: {e}")

    # Default to pass with medium scores
    return ReflectionResult(
        decision="pass",
        biological_plausibility_score=0.75,
        evidence_coverage_score=0.7,
        cross_part_consistency_score=0.7,
        issues=[],
        refinement_targets=[],
    )


async def targeted_refinement(
    state: BiologicalInterpreterState,
    model: BaseChatModel,
    is_debug: bool = False,
) -> dict[str, Any]:
    """Perform targeted refinement based on reflection results.

    Args:
        state: Current agent state
        model: LLM for refinement
        is_debug: Debug flag

    Returns:
        Dict with refined narrative and claims
    """
    reflection_result = state.get("reflection_result", {})
    refinement_targets = reflection_result.get("refinement_targets", [])
    issues = reflection_result.get("issues", [])

    if is_debug:
        print(f"Refinement targets: {refinement_targets}")
        print(f"Issues to address: {issues}")

    # Combine issues and targets
    all_targets = list(set(refinement_targets + issues))

    if not all_targets:
        # No specific targets, do general improvement
        all_targets = ["Improve biological plausibility", "Strengthen evidence base"]

    # Use synthesis module to update narrative and claims
    result = await targeted_synthesis_update(
        state=state,
        model=model,
        refinement_targets=all_targets,
        is_debug=is_debug,
    )

    return {
        "integrated_narrative": result.get("narrative"),
        "claims": result.get("claims"),
    }


def calculate_overall_quality_score(reflection_result: ReflectionResult) -> float:
    """Calculate an overall quality score from reflection results.

    Args:
        reflection_result: The reflection result

    Returns:
        Overall quality score (0-1)
    """
    bio_score = reflection_result.get("biological_plausibility_score", 0)
    evidence_score = reflection_result.get("evidence_coverage_score", 0)
    consistency_score = reflection_result.get("cross_part_consistency_score", 0)

    # Weighted average (biological plausibility is most important)
    overall = (
        0.4 * bio_score +
        0.35 * evidence_score +
        0.25 * consistency_score
    )

    return overall


def should_refine(
    reflection_result: ReflectionResult,
    refinement_count: int,
    max_refinements: int = 3,
) -> bool:
    """Determine if refinement is needed.

    Args:
        reflection_result: The reflection result
        refinement_count: Current refinement iteration
        max_refinements: Maximum allowed refinements

    Returns:
        True if refinement should proceed
    """
    # Don't exceed max refinements
    if refinement_count >= max_refinements:
        return False

    # Check decision
    if reflection_result.get("decision", "pass").lower() == "pass":
        return False

    # Check scores - refine if any is below threshold
    threshold = 0.7
    scores = [
        reflection_result.get("biological_plausibility_score", 1),
        reflection_result.get("evidence_coverage_score", 1),
        reflection_result.get("cross_part_consistency_score", 1),
    ]

    return any(score < threshold for score in scores)
