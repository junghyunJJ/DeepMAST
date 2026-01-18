"""Part 1 interpretation nodes.

This module implements interpretation for Part 1 analyses:
- 1-1: Spatial clustering analysis
- 1-2: Cell type composition analysis
- 1-3: Neighborhood enrichment analysis
- 1-4: Spatial pathway enrichment (Decoupler)
- 1-5: Spatial pathway-celltype relationship (MISTy)
- Synthesis and target selection
"""

from typing import Any

import pandas as pd
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from src.agents.interpreter.biological_interpreter_state import (
    BiologicalInterpreterState,
)
from src.agents.interpreter.nodes.load_results import (
    get_cluster_celltype_mapping,
    get_celltype_cluster_mapping,
    get_cluster_pathways,
    get_neighborhood_clusters,
    load_dataframe_from_ref,
)


# PROGENy pathway descriptions for context
PROGENY_PATHWAYS = {
    "Androgen": "involved in the growth and development of the male reproductive organs",
    "EGFR": "regulates growth, survival, migration, apoptosis, proliferation, and differentiation in mammalian cells",
    "Estrogen": "promotes the growth and development of the female reproductive organs",
    "Hypoxia": "promotes angiogenesis and metabolic reprogramming when O2 levels are low",
    "JAK-STAT": "involved in immunity, cell division, cell death, and tumor formation",
    "MAPK": "integrates external signals and promotes cell growth and proliferation",
    "NFkB": "regulates immune response, cytokine production and cell survival",
    "p53": "regulates cell cycle, apoptosis, DNA repair and tumor suppression",
    "PI3K": "promotes growth and proliferation",
    "TGFb": "involved in development, homeostasis, and repair of most tissues",
    "TNFa": "mediates haematopoiesis, immune surveillance, tumour regression and protection from infection",
    "Trail": "induces apoptosis",
    "VEGF": "mediates angiogenesis, vascular permeability, and cell migration",
    "WNT": "regulates organ morphogenesis during development and tissue repair",
}


INTERPRETATION_SYSTEM_PROMPT = """You are an expert computational biologist specializing in spatial transcriptomics analysis.
Your task is to provide biological interpretations of analysis results.

Guidelines:
- Be specific and cite the data when making claims
- Consider biological plausibility
- Connect findings to known biology when possible
- Keep interpretations concise but informative (2-4 sentences per major point)
- Use proper scientific terminology
"""


async def interpret_spatial(
    state: BiologicalInterpreterState,
    model: BaseChatModel,
    is_debug: bool = False,
) -> str:
    """Interpret Part1-1: Spatial clustering analysis.

    Args:
        state: Current agent state
        model: LLM for interpretation
        is_debug: Debug flag

    Returns:
        Interpretation text
    """
    part1_results = state.get("part1_results", {})
    spatial_result = part1_results.get("spatial", {})

    analysis_mode = state.get("analysis_mode")
    interest_clusters = state.get("interest_clusters", [])
    interest_celltypes = state.get("interest_celltypes", [])

    prompt = f"""## Spatial Clustering Analysis (Part 1-1)

**Analysis Mode**: {analysis_mode}
**Interest Clusters**: {interest_clusters if interest_clusters else "N/A"}
**Interest Cell Types**: {interest_celltypes if interest_celltypes else "N/A"}

**Figure**: {spatial_result.get('figure_path', 'Not available')}

This is a basic spatial plot showing the distribution of clusters across the tissue.

Please provide a brief interpretation:
1. Describe the general spatial organization of clusters
2. If interest clusters are specified, describe their spatial distribution
3. Note any obvious spatial patterns (e.g., tumor core vs margin, stromal regions)

Keep your interpretation to 3-5 sentences.
"""

    messages = [
        SystemMessage(content=INTERPRETATION_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]

    response = await model.ainvoke(messages)

    if is_debug:
        print("Spatial interpretation generated")

    return response.content


async def interpret_celltype(
    state: BiologicalInterpreterState,
    model: BaseChatModel,
    is_debug: bool = False,
) -> str:
    """Interpret Part1-2: Cell type composition analysis.

    Args:
        state: Current agent state
        model: LLM for interpretation
        is_debug: Debug flag

    Returns:
        Interpretation text
    """
    part1_results = state.get("part1_results", {})
    celltype_result = part1_results.get("celltype", {})
    # Load DataFrame from file path reference
    celltype_data = load_dataframe_from_ref(celltype_result)

    analysis_mode = state.get("analysis_mode")
    interest_clusters = state.get("interest_clusters", [])
    interest_celltypes = state.get("interest_celltypes", [])

    # Prepare data summary
    data_summary = "No data available"
    if celltype_data is not None:
        # Filter for significant results
        sig_data = celltype_data[celltype_data["fdr"] < 0.05]

        if analysis_mode == "cluster_to_celltype" and interest_clusters:
            # Show celltypes enriched in interest clusters
            relevant_data = sig_data[sig_data["cluster"].astype(str).isin([str(c) for c in interest_clusters])]
            if not relevant_data.empty:
                summary_df = relevant_data[["cluster", "celltype", "cluster_medians", "fdr"]].head(20)
                data_summary = f"Significant cell types in interest clusters:\n{summary_df.to_string()}"
        elif analysis_mode == "celltype_to_cluster" and interest_celltypes:
            # Show clusters enriched with interest celltypes
            relevant_data = sig_data[sig_data["celltype"].isin(interest_celltypes)]
            if not relevant_data.empty:
                summary_df = relevant_data[["cluster", "celltype", "cluster_medians", "fdr"]].head(20)
                data_summary = f"Clusters enriched with interest cell types:\n{summary_df.to_string()}"
        else:
            # General summary
            summary_df = sig_data[["cluster", "celltype", "fdr"]].head(20)
            data_summary = f"Top significant cluster-celltype associations:\n{summary_df.to_string()}"

    prompt = f"""## Cell Type Composition Analysis (Part 1-2)

**Analysis Mode**: {analysis_mode}
**Interest Clusters**: {interest_clusters if interest_clusters else "N/A"}
**Interest Cell Types**: {interest_celltypes if interest_celltypes else "N/A"}

**Figure**: {celltype_result.get('figure_path', 'Not available')}

**Data Summary**:
{data_summary}

This analysis shows scaled median cell-type compositions within each cluster.
Asterisks indicate increased composition (one-sided Wilcoxon rank sum test, adjusted P < 0.05).

Please provide interpretation:
1. {"Identify cell types enriched in the interest clusters" if analysis_mode == "cluster_to_celltype" else "Identify clusters enriched with the interest cell types"}
2. Note the statistical significance (FDR values)
3. Discuss biological implications of these associations

Keep your interpretation to 4-6 sentences.
"""

    messages = [
        SystemMessage(content=INTERPRETATION_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]

    response = await model.ainvoke(messages)

    if is_debug:
        print("Celltype interpretation generated")

    return response.content


async def interpret_nhood(
    state: BiologicalInterpreterState,
    model: BaseChatModel,
    is_debug: bool = False,
) -> str:
    """Interpret Part1-3: Neighborhood enrichment analysis.

    Args:
        state: Current agent state
        model: LLM for interpretation
        is_debug: Debug flag

    Returns:
        Interpretation text
    """
    part1_results = state.get("part1_results", {})
    nhood_result = part1_results.get("nhood", {})
    # Check if data file exists (don't load DataFrame here, helper function will load it)
    has_nhood_data = nhood_result.get("data_path") is not None

    interest_clusters = state.get("interest_clusters", [])

    # Get neighbor clusters if data available
    neighbor_summary = "No data available"
    if has_nhood_data and interest_clusters:
        neighbors = get_neighborhood_clusters(part1_results, interest_clusters, enrichment_threshold=0)
        if neighbors:
            neighbor_lines = []
            for cluster, nbs in neighbors.items():
                neighbor_lines.append(f"Cluster {cluster} neighbors: {', '.join(nbs) if nbs else 'None'}")
            neighbor_summary = "\n".join(neighbor_lines)

    prompt = f"""## Neighborhood Enrichment Analysis (Part 1-3)

**Interest Clusters**: {interest_clusters if interest_clusters else "N/A"}

**Figure**: {nhood_result.get('figure_path', 'Not available')}

**Neighbor Summary**:
{neighbor_summary}

This analysis identifies clusters that share common spatial neighborhood structure.
High enrichment scores indicate clusters that are often spatially close to each other.
Permutation-based test (n_perms=1000) was used for statistical assessment.

Please provide interpretation:
1. Identify clusters that are spatially proximal to the interest clusters
2. Discuss the biological significance of these spatial relationships
3. Suggest any additional clusters to consider based on neighborhood patterns

Keep your interpretation to 3-5 sentences.
"""

    messages = [
        SystemMessage(content=INTERPRETATION_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]

    response = await model.ainvoke(messages)

    if is_debug:
        print("Neighborhood interpretation generated")

    return response.content


async def interpret_decoupler(
    state: BiologicalInterpreterState,
    model: BaseChatModel,
    is_debug: bool = False,
) -> str:
    """Interpret Part1-4: Spatial pathway enrichment (Decoupler).

    Args:
        state: Current agent state
        model: LLM for interpretation
        is_debug: Debug flag

    Returns:
        Interpretation text
    """
    part1_results = state.get("part1_results", {})
    decoupler_result = part1_results.get("decoupler", {})
    # Check if data file exists (don't load DataFrame here, helper function will load it)
    has_decoupler_data = decoupler_result.get("data_path") is not None

    interest_clusters = state.get("interest_clusters", [])
    selected_clusters = state.get("selected_clusters", [])

    # Use either interest_clusters or selected_clusters
    clusters_to_analyze = interest_clusters or selected_clusters or []

    # Get pathway data summary
    pathway_summary = "No data available"
    if has_decoupler_data and clusters_to_analyze:
        pathways = get_cluster_pathways(part1_results, clusters_to_analyze, padj_threshold=0.05)
        if pathways:
            pathway_lines = []
            for cluster, pw_list in pathways.items():
                if pw_list:
                    top_pathways = [f"{p['name']} (stat={p['stat']:.2f})" for p in pw_list[:5]]
                    pathway_lines.append(f"Cluster {cluster}: {', '.join(top_pathways)}")
            pathway_summary = "\n".join(pathway_lines) if pathway_lines else "No significant pathways found"

    # Add pathway descriptions
    pathway_descriptions = "\n".join([f"- {name}: {desc}" for name, desc in PROGENY_PATHWAYS.items()])

    prompt = f"""## Spatial Pathway Enrichment Analysis - Decoupler (Part 1-4)

**Interest Clusters**: {clusters_to_analyze if clusters_to_analyze else "N/A"}

**Figure**: {decoupler_result.get('figure_path', 'Not available')}

**Significant Pathways in Interest Clusters**:
{pathway_summary}

**PROGENy Pathway Descriptions**:
{pathway_descriptions}

This analysis uses PROGENy geneset for spatial pathway enrichment per cluster.
Positive stat values indicate pathway activation in the target cluster vs others.

Please provide interpretation:
1. Identify the most significantly enriched pathways in the interest clusters
2. Explain the biological functions of these pathways
3. Discuss how these pathway activities relate to the tissue biology

Keep your interpretation to 4-6 sentences.
"""

    messages = [
        SystemMessage(content=INTERPRETATION_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]

    response = await model.ainvoke(messages)

    if is_debug:
        print("Decoupler interpretation generated")

    return response.content


async def interpret_misty(
    state: BiologicalInterpreterState,
    model: BaseChatModel,
    is_debug: bool = False,
) -> str:
    """Interpret Part1-5: Spatial pathway-celltype relationship (MISTy).

    Args:
        state: Current agent state
        model: LLM for interpretation
        is_debug: Debug flag

    Returns:
        Interpretation text
    """
    part1_results = state.get("part1_results", {})
    misty_result = part1_results.get("misty", {})
    # Load DataFrame from file path reference
    misty_data = load_dataframe_from_ref(misty_result)

    # Get selected pathways and celltypes from previous analyses
    selected_pathways = state.get("selected_pathways", [])
    interest_celltypes = state.get("interest_celltypes", [])
    selected_celltypes = state.get("selected_celltypes", [])

    celltypes_of_interest = interest_celltypes or selected_celltypes or []

    # Prepare MISTy data summary
    misty_summary = "No data available"
    if misty_data is not None:
        # Filter for relevant celltypes and pathways
        filtered_data = misty_data.copy()

        if celltypes_of_interest:
            filtered_data = filtered_data[filtered_data["target"].isin(celltypes_of_interest)]

        if selected_pathways:
            filtered_data = filtered_data[filtered_data["predictor"].isin(selected_pathways)]

        if not filtered_data.empty:
            # Sort by importance
            sorted_data = filtered_data.sort_values("importances", ascending=False).head(15)
            misty_summary = sorted_data[["target", "predictor", "importances"]].to_string()
        else:
            # Show top results overall
            sorted_data = misty_data.sort_values("importances", ascending=False).head(15)
            misty_summary = f"Top pathway-celltype relationships:\n{sorted_data[['target', 'predictor', 'importances']].to_string()}"

    prompt = f"""## Spatial Pathway-CellType Relationship Analysis - MISTy (Part 1-5)

**Cell Types of Interest**: {celltypes_of_interest if celltypes_of_interest else "N/A"}
**Selected Pathways**: {selected_pathways if selected_pathways else "N/A"}

**Figure**: {misty_result.get('figure_path', 'Not available')}

**MISTy Results** (target=celltype, predictor=pathway):
{misty_summary}

This analysis shows which molecular signaling environments (pathways) determine
the spatial distribution of specific cell types. Higher importance values indicate
stronger predictive relationships.

Please provide interpretation:
1. Identify which pathways strongly predict the distribution of interest cell types
2. Explain the biological meaning of these pathway-celltype relationships
3. Connect these findings to the Decoupler results from Part 1-4

Keep your interpretation to 4-6 sentences.
"""

    messages = [
        SystemMessage(content=INTERPRETATION_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]

    response = await model.ainvoke(messages)

    if is_debug:
        print("MISTy interpretation generated")

    return response.content


async def synthesize_part1(
    state: BiologicalInterpreterState,
    model: BaseChatModel,
    is_debug: bool = False,
) -> str:
    """Synthesize all Part 1 interpretations.

    Args:
        state: Current agent state
        model: LLM for synthesis
        is_debug: Debug flag

    Returns:
        Synthesis text
    """
    part1_interps = state.get("part1_interpretations", {})
    analysis_mode = state.get("analysis_mode")

    # Compile all interpretations
    all_interps = "\n\n".join([
        f"### {name.capitalize()} Analysis:\n{interp}"
        for name, interp in part1_interps.items()
        if name != "synthesis"
    ])

    prompt = f"""## Part 1 Synthesis

**Analysis Mode**: {analysis_mode}

**Individual Interpretations**:
{all_interps}

Please synthesize the Part 1 findings:
1. Summarize the key biological insights from all 5 analyses
2. Identify consistent patterns across analyses
3. Highlight any contradictions or areas of uncertainty
4. Provide a coherent narrative connecting spatial organization, cell types, and pathways

Keep your synthesis to 6-8 sentences, focusing on the most important findings.
"""

    messages = [
        SystemMessage(content=INTERPRETATION_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]

    response = await model.ainvoke(messages)

    if is_debug:
        print("Part 1 synthesis generated")

    return response.content


async def auto_select_targets(
    state: BiologicalInterpreterState,
    model: BaseChatModel,
    is_debug: bool = False,
) -> dict[str, Any]:
    """Automatically select targets based on Part 1 analysis and mode.

    Mode A (cluster_to_celltype): Select celltypes based on interest_clusters
    Mode B (celltype_to_cluster): Select clusters based on interest_celltypes

    Args:
        state: Current agent state
        model: LLM for decision making
        is_debug: Debug flag

    Returns:
        Dict with selected targets and rationale
    """
    part1_results = state.get("part1_results", {})
    analysis_mode = state.get("analysis_mode")

    result = {}

    if analysis_mode == "cluster_to_celltype":
        # Mode A: Find celltypes for interest clusters
        interest_clusters = state.get("interest_clusters", [])

        # Get celltype mapping
        cluster_celltype_map = get_cluster_celltype_mapping(
            part1_results,
            clusters=interest_clusters,
            fdr_threshold=0.05
        )

        # Flatten to get all celltypes
        all_celltypes = []
        for cluster, cts in cluster_celltype_map.items():
            all_celltypes.extend(cts)

        # Remove duplicates while preserving order
        selected_celltypes = list(dict.fromkeys(all_celltypes))

        # Get additional clusters from neighborhood analysis
        additional_clusters = []
        nhood_neighbors = get_neighborhood_clusters(part1_results, interest_clusters)
        for cluster, neighbors in nhood_neighbors.items():
            for n in neighbors:
                if n not in interest_clusters and n not in additional_clusters:
                    additional_clusters.append(n)

        # Get pathways for all relevant clusters
        all_clusters = interest_clusters + additional_clusters[:3]  # Limit additional
        cluster_pathways = get_cluster_pathways(part1_results, all_clusters)

        # Extract unique pathways
        selected_pathways = []
        for cluster, pathways in cluster_pathways.items():
            for pw in pathways[:3]:  # Top 3 per cluster
                if pw["name"] not in selected_pathways:
                    selected_pathways.append(pw["name"])

        result = {
            "selected_celltypes": selected_celltypes[:10],  # Limit to top 10
            "additional_clusters": additional_clusters[:5],  # Limit to top 5
            "selected_pathways": selected_pathways[:7],  # Limit to top 7
            "part1_selection_rationale": f"Selected {len(selected_celltypes)} cell types enriched in clusters {interest_clusters}. Found {len(additional_clusters)} additional clusters from neighborhood analysis. Identified {len(selected_pathways)} significant pathways.",
        }

    else:
        # Mode B: Find clusters for interest celltypes
        interest_celltypes = state.get("interest_celltypes", [])

        # Get cluster mapping
        celltype_cluster_map = get_celltype_cluster_mapping(
            part1_results,
            celltypes=interest_celltypes,
            fdr_threshold=0.05
        )

        # Flatten to get all clusters
        all_clusters = []
        for ct, clusters in celltype_cluster_map.items():
            all_clusters.extend(clusters)

        # Remove duplicates while preserving order
        selected_clusters = list(dict.fromkeys(all_clusters))

        # Get pathways for selected clusters
        cluster_pathways = get_cluster_pathways(part1_results, selected_clusters[:5])

        selected_pathways = []
        for cluster, pathways in cluster_pathways.items():
            for pw in pathways[:3]:
                if pw["name"] not in selected_pathways:
                    selected_pathways.append(pw["name"])

        result = {
            "selected_clusters": selected_clusters[:10],  # Limit to top 10
            "selected_pathways": selected_pathways[:7],  # Limit to top 7
            "part1_selection_rationale": f"Selected {len(selected_clusters)} clusters enriched with cell types {interest_celltypes}. Identified {len(selected_pathways)} significant pathways.",
        }

    if is_debug:
        print(f"Auto-selected targets: {result}")

    return result
