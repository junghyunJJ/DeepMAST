"""Strategic planning node for Deep Agent.

This module implements hypothesis-driven analysis planning
for the biological interpretation workflow.
"""

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from src.agents.interpreter.biological_interpreter_state import (
    BiologicalInterpreterState,
)


STRATEGIC_PLANNING_PROMPT = """You are a computational biologist specializing in spatial transcriptomics and cell-cell interaction analysis.

Your task is to create a strategic analysis plan based on the user's research focus.

## Analysis Context

**Analysis Mode**: {analysis_mode}
{input_description}

**Research Question** (if provided): {research_question}

**Available Data**:
- Part 1: Spatial clustering, Cell type composition, Neighborhood enrichment, Pathway enrichment (Decoupler, MISTy)
- Part 2: LIANA CCI analysis, NMF factors, Pathway-factor analysis, ctSVG analysis
- Part 3: Spatial L-R visualization, L-R summary

## Your Task

Create a strategic analysis plan that includes:

1. **Hypotheses**: Generate 2-3 testable hypotheses based on the research context
   - Each hypothesis should be specific and testable with the available data
   - Consider biological plausibility and relevance to the research question

2. **Key Questions**: List 3-5 key biological questions to address
   - Focus on mechanistic insights
   - Consider both spatial and molecular aspects

3. **Evidence Requirements**: Specify what evidence would support/refute each hypothesis
   - Link to specific analyses (Part 1-2-3)
   - Define success criteria

## Output Format

Provide your response in the following JSON structure:
```json
{{
    "hypotheses": [
        {{
            "id": "H1",
            "content": "Hypothesis statement",
            "expected_evidence": "What data would support this"
        }}
    ],
    "key_questions": [
        "Question 1",
        "Question 2"
    ],
    "evidence_requirements": [
        "Requirement 1",
        "Requirement 2"
    ],
    "analysis_focus": "Brief summary of the main analysis focus",
    "priority_pathways": ["pathway1", "pathway2"],
    "priority_celltypes": ["celltype1", "celltype2"]
}}
```
"""


async def create_analysis_plan(
    state: BiologicalInterpreterState,
    model: BaseChatModel,
    is_debug: bool = False,
) -> dict[str, Any]:
    """Create a strategic analysis plan based on user input and context.

    Args:
        state: Current agent state
        model: LLM to use for planning
        is_debug: Whether to print debug info

    Returns:
        Analysis plan dictionary with hypotheses, questions, and evidence requirements
    """
    analysis_mode = state.get("analysis_mode", "unknown")

    # Build input description based on mode
    if analysis_mode == "cluster_to_celltype":
        input_description = f"""**User Input**: Interest Clusters = {state.get('interest_clusters', [])}
The goal is to identify cell types and pathways associated with these clusters."""
    else:
        input_description = f"""**User Input**: Interest Cell Types = {state.get('interest_celltypes', [])}
The goal is to identify clusters and pathways associated with these cell types."""

    research_question = state.get("research_question") or "No specific research question provided"

    # Format the prompt
    prompt = STRATEGIC_PLANNING_PROMPT.format(
        analysis_mode=analysis_mode,
        input_description=input_description,
        research_question=research_question,
    )

    if is_debug:
        print("Creating strategic analysis plan...")

    # Get LLM response
    messages = [
        SystemMessage(content="You are a computational biology expert. Always respond with valid JSON."),
        HumanMessage(content=prompt),
    ]

    response = await model.ainvoke(messages)
    response_text = response.content

    # Parse JSON response
    plan = parse_plan_response(response_text, is_debug)

    if is_debug:
        print(f"Generated {len(plan.get('hypotheses', []))} hypotheses")
        print(f"Generated {len(plan.get('key_questions', []))} key questions")

    return plan


def parse_plan_response(response_text: str, is_debug: bool = False) -> dict[str, Any]:
    """Parse the LLM response to extract the analysis plan.

    Args:
        response_text: Raw LLM response text
        is_debug: Whether to print debug info

    Returns:
        Parsed analysis plan dictionary
    """
    import json
    import re

    # Try to extract JSON from the response
    json_match = re.search(r'\{[\s\S]*\}', response_text)

    if json_match:
        try:
            plan = json.loads(json_match.group())
            return plan
        except json.JSONDecodeError as e:
            if is_debug:
                print(f"JSON parse error: {e}")

    # Fallback: create a basic plan
    if is_debug:
        print("Using fallback plan structure")

    return {
        "hypotheses": [
            {
                "id": "H1",
                "content": "The identified clusters show distinct cell-cell interaction patterns",
                "expected_evidence": "Significant LR pairs with high Moran's R values"
            }
        ],
        "key_questions": [
            "What are the dominant cell types in the clusters of interest?",
            "Which pathways are enriched in these clusters?",
            "What ligand-receptor pairs mediate communication?",
        ],
        "evidence_requirements": [
            "Significant cluster-celltype associations (FDR < 0.05)",
            "Pathway enrichment from both Decoupler and NMF analyses",
            "Spatially correlated LR pairs (Moran's R > 0, p < 0.05)",
        ],
        "analysis_focus": "Identify key cell-cell interactions in the target clusters",
        "priority_pathways": [],
        "priority_celltypes": [],
    }


def update_plan_with_findings(
    plan: dict[str, Any],
    part1_findings: dict[str, Any] | None = None,
    part2_findings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Update the analysis plan with intermediate findings.

    This function can be called after Part 1 or Part 2 analysis
    to refine the hypotheses and questions.

    Args:
        plan: Current analysis plan
        part1_findings: Findings from Part 1 analysis
        part2_findings: Findings from Part 2 analysis

    Returns:
        Updated analysis plan
    """
    updated_plan = plan.copy()

    # Update priority pathways if found in Part 1
    if part1_findings:
        if "selected_pathways" in part1_findings:
            updated_plan["priority_pathways"] = part1_findings["selected_pathways"]
        if "selected_celltypes" in part1_findings:
            updated_plan["priority_celltypes"] = part1_findings["selected_celltypes"]

    # Update evidence status if Part 2 findings available
    if part2_findings:
        evidence_found = []
        if part2_findings.get("selected_factor"):
            evidence_found.append(f"Factor {part2_findings['selected_factor']} identified")
        if part2_findings.get("selected_lr_pairs"):
            evidence_found.append(f"{len(part2_findings['selected_lr_pairs'])} LR pairs selected")

        updated_plan["evidence_collected"] = evidence_found

    return updated_plan


def generate_hypothesis_id() -> str:
    """Generate a unique hypothesis ID."""
    import uuid
    return f"H_{uuid.uuid4().hex[:8]}"
