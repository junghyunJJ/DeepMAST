"""Part 2 interpretation nodes.

This module implements interpretation for Part 2 analyses:
- 2-6: LIANA Moran's R analysis
- 2-7: NMF factor analysis and factor selection
- 2-8: Pathway-factor analysis with Part1 comparison
- 2-9: ctSVG analysis with composite LR scoring
"""

from typing import Any

import pandas as pd
import numpy as np
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from src.agents.interpreter.biological_interpreter_state import (
    BiologicalInterpreterState,
    WeightConfiguration,
    LRPairScore,
    DEFAULT_WEIGHT_CONFIG,
)
from src.agents.interpreter.nodes.load_results import (
    get_factor_cluster_scores,
    get_lr_pair_data,
    load_dataframe_from_ref,
)


# ===== Helper functions for analysis_plan context =====

def format_priority_pathways(priority_pathways: list[str]) -> str:
    """Format priority pathways for prompt inclusion."""
    if not priority_pathways:
        return "None specified"
    return ", ".join(priority_pathways)


def format_priority_celltypes(priority_celltypes: list[str]) -> str:
    """Format priority cell types for prompt inclusion."""
    if not priority_celltypes:
        return "None specified"
    return ", ".join(priority_celltypes)


INTERPRETATION_SYSTEM_PROMPT = """You are an expert computational biologist specializing in spatial transcriptomics and cell-cell interaction analysis.
Your task is to provide biological interpretations of analysis results.

Guidelines:
- Be specific and cite the data when making claims
- Consider biological plausibility
- Connect findings to known biology when possible
- Keep interpretations concise but informative (2-4 sentences per major point)
- Use proper scientific terminology
"""


async def interpret_morans(
    state: BiologicalInterpreterState,
    model: BaseChatModel,
    is_debug: bool = False,
) -> str:
    """Interpret Part2-6: LIANA Moran's R analysis.

    Args:
        state: Current agent state
        model: LLM for interpretation
        is_debug: Debug flag

    Returns:
        Interpretation text
    """
    part2_results = state.get("part2_results", {})
    morans_result = part2_results.get("morans", {})
    # Load DataFrame from file path reference
    morans_data = load_dataframe_from_ref(morans_result)

    # Prepare data summary
    data_summary = "No data available"
    if morans_data is not None:
        # Show significant LR pairs (morans > 0 and pval < 0.05)
        sig_data = morans_data.copy()
        if "morans" in sig_data.columns and "morans_pvals" in sig_data.columns:
            sig_data = sig_data[(sig_data["morans"] > 0) & (sig_data["morans_pvals"] < 0.05)]
            sig_data = sig_data.sort_values("morans", ascending=False).head(20)

            if not sig_data.empty:
                cols_to_show = ["liana_interaction", "morans", "morans_pvals"]
                cols_to_show = [c for c in cols_to_show if c in sig_data.columns]
                data_summary = f"Top significant LR pairs:\n{sig_data[cols_to_show].to_string()}"
            else:
                data_summary = "No significant LR pairs found (morans > 0 & pval < 0.05)"

    prompt = f"""## LIANA Moran's R Analysis (Part 2-6)

**Figure**: {morans_result.get('figure_path', 'Not available')}

**Data Summary**:
{data_summary}

This analysis shows bivariate Moran's R values for ligand-receptor pairs.
- Moran's R near zero: spatial independence
- Positive values: spatial co-clustering (ligand and receptor expressed in nearby regions)
- Significant pairs (red dots): Moran's R > 0 and p-value < 0.05

Please provide interpretation:
1. Describe the overall distribution of Moran's R values
2. Highlight the most significantly co-localized LR pairs
3. Discuss the biological implications of spatial co-clustering

Keep your interpretation to 4-6 sentences.
"""

    messages = [
        SystemMessage(content=INTERPRETATION_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]

    response = await model.ainvoke(messages)

    if is_debug:
        print("Morans interpretation generated")

    return response.content


async def interpret_nmf_and_select_factor(
    state: BiologicalInterpreterState,
    model: BaseChatModel,
    is_debug: bool = False,
) -> dict[str, Any]:
    """Interpret Part2-7: NMF factor analysis and select best factor.

    Factor selection is based on median/mean factor score in interest clusters.

    Args:
        state: Current agent state
        model: LLM for interpretation
        is_debug: Debug flag

    Returns:
        Dict with interpretation, selected_factor, rationale, and reference_clusters
    """
    part2_results = state.get("part2_results", {})
    nmf_result = part2_results.get("nmf_factors", {})
    # Load DataFrame from file path reference
    nmf_data = load_dataframe_from_ref(nmf_result)

    analysis_mode = state.get("analysis_mode")

    # Determine reference clusters for factor selection
    if analysis_mode == "cluster_to_celltype":
        # Mode A: Use interest_clusters
        reference_clusters = state.get("interest_clusters", [])
    else:
        # Mode B: Use selected_clusters from Part1
        reference_clusters = state.get("selected_clusters", [])

    # Calculate factor scores per cluster
    factor_cluster_scores = {}
    selected_factor = None
    best_score = -float('inf')

    if nmf_data is not None and reference_clusters:
        factor_cluster_scores = get_factor_cluster_scores(part2_results)

        # Find factor with highest median score in reference clusters
        for factor_name, cluster_scores in factor_cluster_scores.items():
            ref_scores = [cluster_scores.get(str(c), 0) for c in reference_clusters]
            if ref_scores:
                median_score = np.median(ref_scores)
                if median_score > best_score:
                    best_score = median_score
                    selected_factor = factor_name

    # Prepare factor summary
    factor_summary = "No data available"
    if factor_cluster_scores and reference_clusters:
        summary_lines = []
        for factor_name, cluster_scores in factor_cluster_scores.items():
            ref_scores = [cluster_scores.get(str(c), 0) for c in reference_clusters]
            if ref_scores:
                median = np.median(ref_scores)
                summary_lines.append(f"{factor_name}: median={median:.3f} in clusters {reference_clusters}")
        factor_summary = "\n".join(summary_lines)

    prompt = f"""## NMF Factor Analysis (Part 2-7)

**Reference Clusters** (for factor selection): {reference_clusters}
**Analysis Mode**: {analysis_mode}

**Figure**: {nmf_result.get('figure_path', 'Not available')}

**Factor Scores in Reference Clusters**:
{factor_summary}

**Selected Factor**: {selected_factor} (highest median score = {best_score:.3f})

This analysis shows NMF factor scores representing intercellular communication patterns.
Higher factor scores indicate stronger activation of that communication pattern in a region.

Please provide interpretation:
1. Describe the spatial distribution of factor scores
2. Explain why {selected_factor or "the selected factor"} is most relevant to the interest clusters
3. Discuss what this factor might represent biologically

Keep your interpretation to 4-6 sentences.
"""

    messages = [
        SystemMessage(content=INTERPRETATION_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]

    response = await model.ainvoke(messages)

    # Build rationale
    rationale = f"Selected {selected_factor} based on highest median factor score ({best_score:.3f}) in reference clusters {reference_clusters}."

    if is_debug:
        print(f"Selected factor: {selected_factor}")

    return {
        "interpretation": response.content,
        "selected_factor": selected_factor,
        "rationale": rationale,
        "reference_clusters": reference_clusters,
    }


async def interpret_pathway_factor(
    state: BiologicalInterpreterState,
    model: BaseChatModel,
    is_debug: bool = False,
) -> dict[str, Any]:
    """Interpret Part2-8: Pathway-factor analysis with Part1 comparison.

    Args:
        state: Current agent state
        model: LLM for interpretation
        is_debug: Debug flag

    Returns:
        Dict with interpretation and pathway_comparison
    """
    part2_results = state.get("part2_results", {})
    pathway_result = part2_results.get("pathway_factor", {})
    # Load DataFrame from file path reference
    pathway_data = load_dataframe_from_ref(pathway_result)

    selected_factor = state.get("selected_factor")
    selected_pathways_part1 = state.get("selected_pathways", [])

    # Get priority pathways from strategic planning
    analysis_plan = state.get("analysis_plan", {})
    priority_pathways = analysis_plan.get("priority_pathways", [])

    # Get pathways associated with selected factor
    factor_pathways = []
    if pathway_data is not None and selected_factor:
        # Filter for selected factor and significant pathways
        factor_data = pathway_data[
            (pathway_data["factor"] == selected_factor) &
            (pathway_data["adj_pval"] < 0.05)
        ].sort_values("estimate", ascending=False)

        for _, row in factor_data.iterrows():
            factor_pathways.append({
                "pathway": row["pathway"],
                "estimate": row.get("estimate", 0),
                "adj_pval": row.get("adj_pval", 1),
            })

    # Compare with Part1 pathways
    pathway_comparison = {}
    part1_results = state.get("part1_results", {})
    decoupler_ref = part1_results.get("decoupler", {})
    decoupler_data = load_dataframe_from_ref(decoupler_ref)

    for pw_info in factor_pathways[:10]:
        pw_name = pw_info["pathway"]
        comparison_entry = {
            "part2_estimate": pw_info["estimate"],
            "part2_pval": pw_info["adj_pval"],
            "in_part1": pw_name in selected_pathways_part1,
            "part1_stat": None,
            "consistent": False,
        }

        # Try to find Part1 stat
        if decoupler_data is not None and pw_name in selected_pathways_part1:
            pw_part1 = decoupler_data[decoupler_data["name"] == pw_name]
            if not pw_part1.empty:
                comparison_entry["part1_stat"] = pw_part1["stat"].max()
                # Check consistency: both positive
                comparison_entry["consistent"] = (
                    pw_info["estimate"] > 0 and comparison_entry["part1_stat"] > 0
                )

        pathway_comparison[pw_name] = comparison_entry

    # Prepare comparison summary
    comparison_summary = []
    for pw_name, comp in pathway_comparison.items():
        status = "✓ Consistent" if comp["consistent"] else "⚠ Part2 only"
        if comp["in_part1"]:
            status = "✓ Consistent" if comp["consistent"] else "⚠ Inconsistent"
        comparison_summary.append(f"{pw_name}: Part2={comp['part2_estimate']:.2f}, {status}")

    # Build priority context
    priority_context = ""
    if priority_pathways:
        # Highlight which pathways from priority list are present in findings
        found_priority = [p for p in priority_pathways if p in pathway_comparison]
        missing_priority = [p for p in priority_pathways if p not in pathway_comparison]
        priority_context = f"\n**Priority Pathways (from strategic planning)**: {format_priority_pathways(priority_pathways)}"
        if found_priority:
            priority_context += f"\n  - Found in results: {', '.join(found_priority)}"
        if missing_priority:
            priority_context += f"\n  - Not significant: {', '.join(missing_priority)}\n"

    prompt = f"""## Pathway-Factor Analysis (Part 2-8)

**Selected Factor**: {selected_factor}
**Part1 Selected Pathways**: {selected_pathways_part1}
{priority_context}
**Figure**: {pathway_result.get('figure_path', 'Not available')}

**Pathways Associated with Selected Factor**:
{chr(10).join(comparison_summary) if comparison_summary else 'No significant pathways found'}

This analysis shows pathway enrichment based on NMF factor loadings.
We compare Part2 pathway results with Part1 Decoupler results for consistency.

Please provide interpretation:
1. Identify pathways strongly associated with the selected factor
2. Compare Part1 and Part2 pathway findings - note consistencies and discrepancies
3. Explain the biological significance of consistent pathways
{f"4. **Priority Assessment**: Evaluate whether priority pathways ({format_priority_pathways(priority_pathways)}) are enriched with the selected factor, and discuss implications for the research hypothesis" if priority_pathways else ""}

Keep your interpretation to 4-6 sentences.
"""

    messages = [
        SystemMessage(content=INTERPRETATION_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]

    response = await model.ainvoke(messages)

    if is_debug:
        print(f"Pathway comparison: {len(pathway_comparison)} pathways analyzed")

    return {
        "interpretation": response.content,
        "pathway_comparison": pathway_comparison,
    }


async def determine_scoring_weights(
    state: BiologicalInterpreterState,
    model: BaseChatModel,
    is_debug: bool = False,
) -> WeightConfiguration:
    """Dynamically adjust scoring weights based on analysis context.

    Uses LLM to adjust weights within guardrails based on:
    - Research question focus
    - Data quality indicators
    - Pathway significance

    Args:
        state: Current agent state
        model: LLM for weight adjustment
        is_debug: Debug flag

    Returns:
        WeightConfiguration with adjusted weights
    """
    base_config = DEFAULT_WEIGHT_CONFIG.copy()

    # Prepare context for weight adjustment
    research_question = state.get("research_question", "")
    analysis_plan = state.get("analysis_plan", {})
    selected_factor = state.get("selected_factor", "")
    pathway_comparison = state.get("pathway_comparison", {})

    # Extract priority information from analysis_plan
    priority_pathways = analysis_plan.get("priority_pathways", [])
    priority_celltypes = analysis_plan.get("priority_celltypes", [])
    hypotheses = analysis_plan.get("hypotheses", [])

    # Count consistent pathways
    consistent_count = sum(1 for comp in pathway_comparison.values() if comp.get("consistent", False))

    # Build strategic context
    strategic_context = ""
    if priority_pathways or priority_celltypes or hypotheses:
        strategic_context = "\n**Strategic Planning Context**:"
        if priority_pathways:
            strategic_context += f"\n- Priority Pathways: {format_priority_pathways(priority_pathways)}"
        if priority_celltypes:
            strategic_context += f"\n- Priority Cell Types: {format_priority_celltypes(priority_celltypes)}"
        if hypotheses:
            hypothesis_summary = "; ".join([h.get("content", "")[:50] for h in hypotheses[:2]])
            strategic_context += f"\n- Key Hypotheses: {hypothesis_summary}..."
        strategic_context += "\n"

    prompt = f"""## L-R Pair Scoring Weight Adjustment

**Research Context**:
- Research Question: {research_question or "Not specified"}
- Selected Factor: {selected_factor}
- Consistent Pathways (Part1↔Part2): {consistent_count}
{strategic_context}
**Default Weights** (must sum to 1.0):
- Factor loading: {base_config['base_weights']['factor']} (range: 0.20-0.50)
- Pathway relevance: {base_config['base_weights']['pathway']} (range: 0.15-0.45)
- Moran's R: {base_config['base_weights']['morans']} (range: 0.10-0.35)
- ctSVG overlap: {base_config['base_weights']['ctsvg']} (range: 0.05-0.30)

Based on the analysis context, recommend adjusted weights:
1. If pathway consistency is high OR priority pathways are specified, increase pathway weight
2. If spatial patterns are important for the research question, increase morans weight
3. If cell-type specificity is key OR priority celltypes are specified, increase ctsvg weight
4. Factor weight should remain relatively high as the anchor

{f"**Note**: Priority pathways ({format_priority_pathways(priority_pathways)}) and celltypes ({format_priority_celltypes(priority_celltypes)}) should influence weight adjustments to prioritize L-R pairs relevant to the research hypothesis." if (priority_pathways or priority_celltypes) else ""}

Provide your response in JSON format:
```json
{{
    "factor": <value>,
    "pathway": <value>,
    "morans": <value>,
    "ctsvg": <value>,
    "rationale": "Brief explanation of adjustments"
}}
```

IMPORTANT: Weights must sum to 1.0 and stay within the specified ranges.
"""

    messages = [
        SystemMessage(content="You are an expert at optimizing scoring weights. Always respond with valid JSON."),
        HumanMessage(content=prompt),
    ]

    response = await model.ainvoke(messages)

    # Parse response and validate weights
    import json
    import re

    try:
        json_match = re.search(r'\{[\s\S]*\}', response.content)
        if json_match:
            weights = json.loads(json_match.group())

            # Validate ranges
            ranges = base_config["weight_ranges"]
            adjusted = {}
            for key in ["factor", "pathway", "morans", "ctsvg"]:
                val = weights.get(key, base_config["base_weights"][key])
                min_val, max_val = ranges[key]
                adjusted[key] = max(min_val, min(max_val, val))

            # Normalize to sum to 1.0
            total = sum(adjusted.values())
            if total > 0:
                adjusted = {k: v / total for k, v in adjusted.items()}

            rationale = weights.get("rationale", "Weights adjusted based on analysis context")

            return WeightConfiguration(
                base_weights=base_config["base_weights"],
                weight_ranges=ranges,
                applied_weights=adjusted,
                adjustment_rationale=rationale,
            )

    except (json.JSONDecodeError, KeyError) as e:
        if is_debug:
            print(f"Weight adjustment parse error: {e}, using defaults")

    # Return defaults if parsing fails
    return base_config


def calculate_composite_score(
    lr_row: pd.Series,
    weights: dict[str, float],
    selected_factor: str,
    selected_pathways: list[str],
    final_celltypes: list[str],
) -> LRPairScore:
    """Calculate composite score for a single LR pair.

    Args:
        lr_row: Row from LR pair data
        weights: Scoring weights
        selected_factor: Selected NMF factor
        selected_pathways: Selected pathways from Part1
        final_celltypes: Cell types for ctSVG matching

    Returns:
        LRPairScore with component scores
    """
    # Factor score (from NMF loading)
    factor_score = 0.0
    if selected_factor and selected_factor in lr_row.index:
        factor_val = lr_row[selected_factor]
        if pd.notna(factor_val):
            factor_score = float(factor_val)

    # Pathway score (match with selected pathways)
    pathway_score = 0.0
    if "progeny" in lr_row.index and selected_pathways:
        progeny_val = lr_row.get("progeny", "")
        if pd.notna(progeny_val) and progeny_val:
            # Check if any selected pathway matches
            for pw in selected_pathways:
                if pw.lower() in str(progeny_val).lower():
                    pathway_score = 1.0
                    break

    # Moran's score
    morans_score = 0.0
    if "morans" in lr_row.index:
        morans_val = lr_row["morans"]
        if pd.notna(morans_val) and morans_val > 0:
            morans_score = float(morans_val)

    # ctSVG score (cell type overlap)
    ctsvg_score = 0.0
    if final_celltypes:
        ligand_ctsvg = lr_row.get("ligand_ctSVG", "")
        receptor_ctsvg = lr_row.get("receptor_ctSVG", "")

        for ct in final_celltypes:
            if pd.notna(ligand_ctsvg) and ct.lower() in str(ligand_ctsvg).lower():
                ctsvg_score += 0.5
            if pd.notna(receptor_ctsvg) and ct.lower() in str(receptor_ctsvg).lower():
                ctsvg_score += 0.5

        ctsvg_score = min(1.0, ctsvg_score)  # Cap at 1.0

    # Normalize scores to 0-1 range
    # Factor loading normalization (assume typical range 0-1)
    factor_score = min(1.0, max(0.0, factor_score))

    # Calculate composite score
    composite = (
        weights["factor"] * factor_score +
        weights["pathway"] * pathway_score +
        weights["morans"] * morans_score +
        weights["ctsvg"] * ctsvg_score
    )

    return LRPairScore(
        composite_score=composite,
        factor_score=factor_score,
        pathway_score=pathway_score,
        morans_score=morans_score,
        ctsvg_score=ctsvg_score,
    )


async def interpret_ctsvg_and_select_lr(
    state: BiologicalInterpreterState,
    model: BaseChatModel,
    is_debug: bool = False,
) -> dict[str, Any]:
    """Interpret Part2-9: ctSVG analysis and select top L-R pairs.

    Uses composite scoring with hybrid weights.

    Args:
        state: Current agent state
        model: LLM for interpretation
        is_debug: Debug flag

    Returns:
        Dict with interpretation, selected LR pairs, scores, and weights
    """
    part2_results = state.get("part2_results", {})
    ctsvg_result = part2_results.get("ctsvg", {})

    # Get LR pair data
    lr_data = get_lr_pair_data(part2_results, use_interest=True)

    if lr_data is None:
        # Try full data if interest data not available
        lr_data = get_lr_pair_data(part2_results, use_interest=False)

    # Determine scoring weights
    scoring_weights = await determine_scoring_weights(state, model, is_debug)

    selected_factor = state.get("selected_factor", "")
    selected_pathways = state.get("selected_pathways", [])
    final_celltypes = state.get("final_celltypes_for_ctsvg", [])

    # Score all LR pairs
    lr_scores = {}
    if lr_data is not None:
        for idx, row in lr_data.iterrows():
            lr_name = row.get("liana_interaction", f"LR_{idx}")
            score = calculate_composite_score(
                row,
                scoring_weights["applied_weights"],
                selected_factor,
                selected_pathways,
                final_celltypes,
            )
            lr_scores[lr_name] = score

    # Select top LR pairs (1-10 based on composite score)
    sorted_pairs = sorted(lr_scores.items(), key=lambda x: x[1]["composite_score"], reverse=True)
    selected_lr_pairs = [pair[0] for pair in sorted_pairs[:3]]  # Top 3

    # Prepare score summary
    score_summary = []
    for pair_name, score in sorted_pairs[:10]:
        score_summary.append(
            f"{pair_name}: composite={score['composite_score']:.3f} "
            f"(factor={score['factor_score']:.2f}, pathway={score['pathway_score']:.2f}, "
            f"morans={score['morans_score']:.2f}, ctsvg={score['ctsvg_score']:.2f})"
        )

    prompt = f"""## ctSVG Analysis and L-R Pair Selection (Part 2-9)

**Selected Factor**: {selected_factor}
**Selected Pathways**: {selected_pathways}
**Target Cell Types**: {final_celltypes}

**Figure**: {ctsvg_result.get('figure_path', 'Not available')}

**Scoring Weights** (LLM-adjusted):
{scoring_weights['applied_weights']}
Rationale: {scoring_weights['adjustment_rationale']}

**Top Scored L-R Pairs**:
{chr(10).join(score_summary) if score_summary else 'No LR pairs scored'}

**Selected L-R Pairs for Part 3**: {selected_lr_pairs}

This quadrant analysis plots Moran's R (x-axis) vs Factor loading (y-axis).
The composite score prioritizes: Factor loading > Pathway relevance > Moran's R > ctSVG overlap.

Please provide interpretation:
1. Describe the distribution of LR pairs in the quadrant plot
2. Explain why the top LR pairs were selected
3. Discuss the biological relevance of these ligand-receptor interactions
4. Note any ctSVG patterns (cell-type specific expression)

Keep your interpretation to 5-7 sentences.
"""

    messages = [
        SystemMessage(content=INTERPRETATION_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]

    response = await model.ainvoke(messages)

    # Build rationale
    rationale = f"Selected top {len(selected_lr_pairs)} L-R pairs based on composite scoring. Weight adjustments: {scoring_weights['adjustment_rationale']}"

    if is_debug:
        print(f"Selected {len(selected_lr_pairs)} L-R pairs")

    return {
        "interpretation": response.content,
        "scoring_weights": scoring_weights,
        "selected_lr_pairs": selected_lr_pairs,
        "lr_scores": lr_scores,
        "rationale": rationale,
    }
