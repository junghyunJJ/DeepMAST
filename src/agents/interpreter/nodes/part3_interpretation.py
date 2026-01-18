"""Part 3 interpretation nodes.

This module implements interpretation for Part 3 analyses:
- 3-10: Spatial L-R expression patterns
- 3-11: L-R interaction summary
"""

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from src.agents.interpreter.biological_interpreter_state import (
    BiologicalInterpreterState,
)


# ===== Helper functions for analysis_plan context =====

def format_hypotheses(hypotheses: list[dict]) -> str:
    """Format hypotheses for prompt inclusion."""
    if not hypotheses:
        return "No specific hypotheses generated"
    lines = []
    for h in hypotheses:
        h_id = h.get("id", "H")
        content = h.get("content", "")
        expected = h.get("expected_evidence", "N/A")
        lines.append(f"- **{h_id}**: {content}")
        if expected and expected != "N/A":
            lines.append(f"  (Expected evidence: {expected})")
    return "\n".join(lines)


INTERPRETATION_SYSTEM_PROMPT = """You are an expert computational biologist specializing in spatial transcriptomics and cell-cell interaction analysis.
Your task is to provide biological interpretations of analysis results.

Guidelines:
- Be specific and cite the data when making claims
- Consider biological plausibility
- Connect findings to known biology when possible
- Keep interpretations concise but informative (2-4 sentences per major point)
- Use proper scientific terminology
"""


async def interpret_spatial_lr(
    state: BiologicalInterpreterState,
    model: BaseChatModel,
    is_debug: bool = False,
) -> str:
    """Interpret Part3-10: Spatial L-R expression patterns.

    Args:
        state: Current agent state
        model: LLM for interpretation
        is_debug: Debug flag

    Returns:
        Interpretation text
    """
    part2_results = state.get("part2_results", {})
    spatial_lr_result = part2_results.get("spatial_lr", {})

    selected_lr_pairs = state.get("selected_lr_pairs", [])
    lr_scores = state.get("lr_scores", {})

    # Prepare LR pair details
    lr_details = []
    for lr_name in selected_lr_pairs:
        score = lr_scores.get(lr_name, {})
        if score:
            lr_details.append(
                f"- {lr_name}: composite={score.get('composite_score', 0):.3f}, "
                f"morans={score.get('morans_score', 0):.3f}"
            )
        else:
            lr_details.append(f"- {lr_name}")

    # Get context from previous parts
    interest_clusters = state.get("interest_clusters", [])
    selected_clusters = state.get("selected_clusters", [])
    final_celltypes = state.get("final_celltypes_for_ctsvg", [])
    selected_factor = state.get("selected_factor", "")

    clusters_context = interest_clusters or selected_clusters or []

    # Get hypotheses from strategic planning
    analysis_plan = state.get("analysis_plan", {})
    hypotheses = analysis_plan.get("hypotheses", [])

    # Build hypothesis context
    hypothesis_context = ""
    if hypotheses:
        hypothesis_context = f"""
### Initial Hypotheses to Address
{format_hypotheses(hypotheses)}
"""

    prompt = f"""## Spatial L-R Expression Patterns (Part 3-10)

**Selected L-R Pairs**: {selected_lr_pairs}
**Reference Clusters**: {clusters_context}
**Target Cell Types**: {final_celltypes}
**Selected Factor**: {selected_factor}
{hypothesis_context}
**Figure**: {spatial_lr_result.get('figure', 'Not available')}

**L-R Pair Scores**:
{chr(10).join(lr_details) if lr_details else 'No details available'}

This visualization shows the spatial expression patterns of the selected
ligand-receptor pairs across the tissue. Each pair shows:
- Ligand expression spatial distribution
- Receptor expression spatial distribution
- Overlap/co-localization regions

Please provide interpretation:
1. Describe the spatial patterns of ligand and receptor expression
2. Identify regions of strong co-localization
3. Relate patterns to the clusters and cell types of interest
4. Discuss potential biological implications of these spatial patterns
{f"5. **Hypothesis Assessment**: Evaluate how these L-R spatial patterns relate to the initial hypotheses. Do the patterns support or refute any hypothesis?" if hypotheses else ""}

Keep your interpretation to 5-7 sentences.
"""

    messages = [
        SystemMessage(content=INTERPRETATION_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]

    response = await model.ainvoke(messages)

    if is_debug:
        print("Spatial LR interpretation generated")

    return response.content


async def interpret_lr_summary(
    state: BiologicalInterpreterState,
    model: BaseChatModel,
    is_debug: bool = False,
) -> str:
    """Interpret Part3-11: L-R interaction summary.

    Args:
        state: Current agent state
        model: LLM for interpretation
        is_debug: Debug flag

    Returns:
        Interpretation text
    """
    part2_results = state.get("part2_results", {})
    lr_summary_result = part2_results.get("lr_summary", {})

    selected_lr_pairs = state.get("selected_lr_pairs", [])
    lr_scores = state.get("lr_scores", {})
    lr_selection_rationale = state.get("lr_selection_rationale", "")

    # Prepare comprehensive LR summary
    lr_summary_lines = []
    for lr_name in selected_lr_pairs:
        score = lr_scores.get(lr_name, {})
        if score:
            lr_summary_lines.append(
                f"**{lr_name}**:\n"
                f"  - Composite Score: {score.get('composite_score', 0):.3f}\n"
                f"  - Factor Loading: {score.get('factor_score', 0):.3f}\n"
                f"  - Pathway Match: {score.get('pathway_score', 0):.3f}\n"
                f"  - Moran's R: {score.get('morans_score', 0):.3f}\n"
                f"  - ctSVG Overlap: {score.get('ctsvg_score', 0):.3f}"
            )

    # Get pathway and celltype context
    selected_pathways = state.get("selected_pathways", [])
    final_celltypes = state.get("final_celltypes_for_ctsvg", [])
    pathway_comparison = state.get("pathway_comparison", {})

    # Get hypotheses from strategic planning
    analysis_plan = state.get("analysis_plan", {})
    hypotheses = analysis_plan.get("hypotheses", [])

    # Build hypothesis context
    hypothesis_context = ""
    if hypotheses:
        hypothesis_context = f"""
### Initial Hypotheses to Address
{format_hypotheses(hypotheses)}
"""

    prompt = f"""## L-R Interaction Summary (Part 3-11)

**Selected L-R Pairs**: {selected_lr_pairs}
**Selection Rationale**: {lr_selection_rationale}
{hypothesis_context}
**Figure**: {lr_summary_result.get('figure', 'Not available')}

**Detailed L-R Pair Scores**:
{chr(10).join(lr_summary_lines) if lr_summary_lines else 'No detailed scores available'}

**Associated Pathways**: {selected_pathways}
**Associated Cell Types**: {final_celltypes}

This summary provides expression values and statistical significance for
the selected ligand-receptor interactions across the tissue.

Please provide a comprehensive summary:
1. Rank and describe the selected L-R pairs by importance
2. Connect each LR pair to specific biological functions
3. Explain how these interactions relate to the pathways and cell types identified
4. Provide hypotheses for the functional role of these interactions
5. Note any patterns that suggest regulatory relationships
{f"6. **Hypothesis Validation**: Based on the L-R findings, indicate which initial hypotheses are supported or refuted, and what new insights emerge" if hypotheses else ""}

Keep your interpretation to 6-8 sentences.
"""

    messages = [
        SystemMessage(content=INTERPRETATION_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]

    response = await model.ainvoke(messages)

    if is_debug:
        print("LR summary interpretation generated")

    return response.content
