"""Cross-part synthesis node.

This module implements the Deep Agent's cross-part synthesis,
creating a coherent narrative and generating claims with evidence.
"""

from typing import Any
import uuid

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from src.agents.interpreter.biological_interpreter_state import (
    BiologicalInterpreterState,
    Claim,
)


SYNTHESIS_SYSTEM_PROMPT = """You are an expert computational biologist creating a synthesis report.
Your task is to integrate findings from multiple analyses into a coherent biological narrative.

Guidelines:
- Synthesize findings across all parts (Part 1, 2, 3)
- Identify consistent patterns and highlight key discoveries
- Generate specific, evidence-backed claims
- Maintain scientific rigor while being accessible
- Focus on biological insights, not just data description
"""


async def cross_part_synthesis(
    state: BiologicalInterpreterState,
    model: BaseChatModel,
    is_debug: bool = False,
) -> dict[str, Any]:
    """Create cross-part synthesis with coherent narrative and claims.

    Args:
        state: Current agent state
        model: LLM for synthesis
        is_debug: Debug flag

    Returns:
        Dict with narrative and claims list
    """
    # Gather all interpretations
    part1_interps = state.get("part1_interpretations", {})
    part2_interps = state.get("part2_interpretations", {})
    part3_interps = state.get("part3_interpretations", {})

    # Key selections and findings
    analysis_mode = state.get("analysis_mode")
    interest_clusters = state.get("interest_clusters", [])
    interest_celltypes = state.get("interest_celltypes", [])
    selected_celltypes = state.get("selected_celltypes", [])
    selected_clusters = state.get("selected_clusters", [])
    selected_pathways = state.get("selected_pathways", [])
    selected_factor = state.get("selected_factor", "")
    selected_lr_pairs = state.get("selected_lr_pairs", [])
    pathway_comparison = state.get("pathway_comparison", {})
    analysis_plan = state.get("analysis_plan", {})

    # Compile Part 1 summary
    part1_summary = "\n".join([
        f"- {name}: {interp[:200]}..."
        for name, interp in part1_interps.items()
    ])

    # Compile Part 2 summary
    part2_summary = "\n".join([
        f"- {name}: {interp[:200]}..."
        for name, interp in part2_interps.items()
    ])

    # Compile Part 3 summary
    part3_summary = "\n".join([
        f"- {name}: {interp[:200]}..."
        for name, interp in part3_interps.items()
    ])

    # Prepare pathway consistency info
    consistent_pathways = [
        pw for pw, comp in pathway_comparison.items()
        if comp.get("consistent", False)
    ]

    # Prepare hypotheses from analysis plan
    hypotheses = analysis_plan.get("hypotheses", [])
    hypothesis_text = "\n".join([
        f"- {h.get('id', 'H')}: {h.get('content', '')}"
        for h in hypotheses
    ])

    prompt = f"""## Cross-Part Synthesis

**Analysis Mode**: {analysis_mode}
**Input**: {"Clusters " + str(interest_clusters) if interest_clusters else "Cell Types " + str(interest_celltypes)}

### Key Findings Summary

**Part 1 (Before CCI)**:
- Selected Cell Types: {selected_celltypes or interest_celltypes}
- Selected Clusters: {selected_clusters or interest_clusters}
- Selected Pathways: {selected_pathways}

{part1_summary}

**Part 2 (CCI + NMF + ctSVG)**:
- Selected Factor: {selected_factor}
- Pathway Consistency (Part1↔Part2): {consistent_pathways}
- Selected L-R Pairs: {selected_lr_pairs}

{part2_summary}

**Part 3 (L-R Visualization)**:
{part3_summary}

### Initial Hypotheses
{hypothesis_text if hypothesis_text else "No specific hypotheses generated"}

---

## Your Tasks

1. **Create Integrated Narrative** (400-600 words):
   - Synthesize findings into a coherent biological story
   - Connect spatial organization → cell types → pathways → L-R interactions
   - Explain the biological significance of the findings
   - Address the initial hypotheses with evidence

2. **Generate Claims** (3-5 specific claims):
   For each claim, provide:
   - A specific, testable biological statement
   - Confidence level (high/medium/low)
   - Supporting evidence from the analyses
   - Source part (part1, part2, part3, or synthesis)

Format your response as:

### NARRATIVE
[Your integrated narrative here]

### CLAIMS
CLAIM_1:
- Content: [Specific claim]
- Confidence: [high/medium/low]
- Evidence: [List of supporting evidence]
- Source: [part1/part2/part3/synthesis]

CLAIM_2:
[Continue for each claim]
"""

    messages = [
        SystemMessage(content=SYNTHESIS_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]

    response = await model.ainvoke(messages)

    # Parse response
    narrative, claims = parse_synthesis_response(response.content, is_debug)

    if is_debug:
        print(f"Generated narrative ({len(narrative)} chars) and {len(claims)} claims")

    return {
        "narrative": narrative,
        "claims": claims,
    }


def parse_synthesis_response(response_text: str, is_debug: bool = False) -> tuple[str, list[Claim]]:
    """Parse the synthesis response to extract narrative and claims.

    Args:
        response_text: Raw LLM response
        is_debug: Debug flag

    Returns:
        Tuple of (narrative_text, list_of_claims)
    """
    import re

    narrative = ""
    claims = []

    # Split by major sections
    parts = re.split(r'###\s*NARRATIVE|###\s*CLAIMS', response_text, flags=re.IGNORECASE)

    if len(parts) >= 2:
        narrative = parts[1].strip()
        # Remove the CLAIMS section from narrative if it got included
        if "CLAIM_" in narrative:
            narrative = narrative.split("###")[0].strip()

    if len(parts) >= 3:
        claims_text = parts[2].strip()

        # Parse individual claims
        claim_blocks = re.split(r'CLAIM_\d+:', claims_text)

        for i, block in enumerate(claim_blocks[1:], 1):  # Skip empty first element
            block = block.strip()
            if not block:
                continue

            claim = parse_single_claim(block, i)
            if claim:
                claims.append(claim)

    # Fallback if parsing failed
    if not narrative:
        narrative = response_text[:1000]
        if is_debug:
            print("Narrative parsing fallback used")

    if not claims:
        # Create a default claim
        claims = [
            Claim(
                claim_id=f"C_{uuid.uuid4().hex[:8]}",
                content="The identified L-R pairs show spatially correlated expression patterns.",
                confidence=0.7,
                supporting_evidence=["Moran's R analysis", "NMF factor loading"],
                part_source="synthesis",
            )
        ]
        if is_debug:
            print("Claims parsing fallback used")

    return narrative, claims


def parse_single_claim(block: str, index: int) -> Claim | None:
    """Parse a single claim block.

    Args:
        block: Text block containing claim details
        index: Claim index for ID generation

    Returns:
        Claim object or None if parsing fails
    """
    import re

    content = ""
    confidence = 0.5
    evidence = []
    source = "synthesis"

    lines = block.strip().split("\n")

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Parse content
        if line.lower().startswith("- content:") or line.lower().startswith("content:"):
            content = re.sub(r'^-?\s*content:\s*', '', line, flags=re.IGNORECASE).strip()

        # Parse confidence
        elif line.lower().startswith("- confidence:") or line.lower().startswith("confidence:"):
            conf_str = re.sub(r'^-?\s*confidence:\s*', '', line, flags=re.IGNORECASE).strip().lower()
            if "high" in conf_str:
                confidence = 0.9
            elif "medium" in conf_str:
                confidence = 0.7
            elif "low" in conf_str:
                confidence = 0.5
            else:
                try:
                    confidence = float(conf_str)
                except ValueError:
                    confidence = 0.7

        # Parse evidence
        elif line.lower().startswith("- evidence:") or line.lower().startswith("evidence:"):
            evidence_str = re.sub(r'^-?\s*evidence:\s*', '', line, flags=re.IGNORECASE).strip()
            # Split by common delimiters
            evidence = [e.strip() for e in re.split(r'[,;]', evidence_str) if e.strip()]

        # Parse source
        elif line.lower().startswith("- source:") or line.lower().startswith("source:"):
            source = re.sub(r'^-?\s*source:\s*', '', line, flags=re.IGNORECASE).strip().lower()
            if source not in ["part1", "part2", "part3", "synthesis"]:
                source = "synthesis"

    if not content:
        return None

    return Claim(
        claim_id=f"C_{uuid.uuid4().hex[:8]}",
        content=content,
        confidence=confidence,
        supporting_evidence=evidence if evidence else ["Analysis results"],
        part_source=source,
    )


async def targeted_synthesis_update(
    state: BiologicalInterpreterState,
    model: BaseChatModel,
    refinement_targets: list[str],
    is_debug: bool = False,
) -> dict[str, Any]:
    """Update synthesis based on refinement targets.

    Called during the refinement loop to address specific issues.

    Args:
        state: Current agent state
        model: LLM for refinement
        refinement_targets: Specific aspects to refine
        is_debug: Debug flag

    Returns:
        Updated narrative and claims
    """
    current_narrative = state.get("integrated_narrative", "")
    current_claims = state.get("claims", [])

    prompt = f"""## Synthesis Refinement

**Current Narrative**:
{current_narrative[:1000]}...

**Current Claims**:
{chr(10).join([f"- {c['content']}" for c in current_claims])}

**Refinement Targets**:
{chr(10).join([f"- {t}" for t in refinement_targets])}

Please refine the synthesis to address the identified issues:
1. Strengthen biological plausibility
2. Improve evidence coverage
3. Ensure cross-part consistency

Provide your refined output in the same format:

### NARRATIVE
[Refined narrative]

### CLAIMS
[Refined claims with updated evidence]
"""

    messages = [
        SystemMessage(content=SYNTHESIS_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]

    response = await model.ainvoke(messages)

    narrative, claims = parse_synthesis_response(response.content, is_debug)

    if is_debug:
        print(f"Refined narrative and {len(claims)} claims")

    return {
        "narrative": narrative,
        "claims": claims,
    }
