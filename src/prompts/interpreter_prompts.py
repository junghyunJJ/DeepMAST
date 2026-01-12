"""Prompt templates for CCI Interpreter Agent.

This module contains prompt generation functions for biological interpretation
of Cell-Cell Interaction (CCI) analysis results from spatial transcriptomics.
"""

from typing import Any, Optional


# ===== PROGENy Pathway Descriptions =====
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


def get_pathway_descriptions() -> str:
    """Get formatted pathway descriptions for prompts."""
    lines = []
    for pathway, description in PROGENY_PATHWAYS.items():
        lines.append(f"- **{pathway}**: {description}")
    return "\n".join(lines)


# ===== Part 1 Analysis Prompts =====

PART1_SYSTEM_PROMPT = """You are an expert bioinformatician specializing in spatial transcriptomics analysis.
Your task is to analyze Part 1 results (pre-CCI analysis) and select the most relevant clusters, cell types, and pathways.

IMPORTANT: You must use sequential thinking (sequentialthinking tool) to structure your analysis.

## Your Analysis Goals:
1. Identify 2-3 most biologically relevant clusters from the cell type composition data
2. Determine the cell types significantly associated with these clusters
3. Find pathways enriched in these clusters (from decoupler and MISTy results)

## PROGENy Pathway Reference:
{pathway_descriptions}

## Analysis Guidelines:
- Focus on clusters with statistically significant (FDR < 0.05) cell type enrichment
- Consider neighborhood enrichment patterns to identify spatially related clusters
- Prioritize pathways with strong enrichment in your selected clusters
- Think about the biological significance in the context of {disease_context}

## Output Requirements:
Provide your analysis as a structured selection with:
1. Selected clusters (2-3 max) with justification
2. Associated cell types for each cluster
3. Relevant pathways from both decoupler and MISTy analyses
4. Brief biological reasoning connecting these findings
"""


def create_part1_analysis_prompt(
    state: dict,
    iteration: int = 1
) -> str:
    """Create prompt for Part 1 analysis iteration.

    Args:
        state: Current agent state with loaded data
        iteration: Current iteration number (1-5)

    Returns:
        Formatted prompt string
    """
    system = PART1_SYSTEM_PROMPT.format(
        pathway_descriptions=get_pathway_descriptions(),
        disease_context=state.get("disease_context", "cancer")
    )

    user_prompt = f"""## Part 1 Analysis - Iteration {iteration}

Analyze the following spatial transcriptomics data to select relevant clusters, cell types, and pathways.

### 1. Cell Type Composition (sig_clusterwithcelltyp.csv)
This shows scaled median cell-type compositions within each cluster. Asterisks indicate increased composition
(one-sided Wilcoxon rank sum test, adjusted P < 0.05).

Data columns: cluster, celltype, cluster_medians, fdr

```
{state.get("sig_clusterwithcelltyp", "Data not loaded")}
```

### 2. Neighborhood Enrichment (res_nhood_enrichment.csv)
Enrichment scores on spatial proximity of clusters. High scores = enriched (often close), low scores = depleted (far apart).

```
{state.get("res_nhood_enrichment", "Data not loaded")}
```

### 3. Pathway Enrichment - Decoupler (sig_PathwayEnrich_decoupler.csv)
PROGENy pathway enrichment per cluster using decoupler.

Data columns: group (target cluster), reference, name (pathway), stat, meanchange, pval, padj

```
{state.get("sig_pathway_decoupler", "Data not loaded")}
```

### 4. Spatial Relationship - MISTy (res_SpatialRelationship_MISTy.csv)
Target (cell type) - Predictor (pathway) relationship showing which pathways predict cell type spatial distribution.

Data columns: target, predictor, view (juxta = juxtacrine signalling), importances

```
{state.get("res_spatial_misty", "Data not loaded")}
```

---

**Instructions:**
1. Use `sequentialthinking` tool to systematically analyze each dataset
2. First identify clusters with significant cell type enrichments (FDR < 0.05)
3. Check neighborhood enrichment to find spatially related clusters
4. Find pathways enriched in these clusters
5. Connect findings through MISTy cell type-pathway relationships

**Provide your selection in this JSON format:**
```json
{{
    "clusters": ["cluster1", "cluster2"],
    "cell_types": ["celltype1", "celltype2", "celltype3"],
    "pathways": ["pathway1", "pathway2"],
    "reasoning": "Brief explanation of biological significance in {state.get("disease_context", "cancer")} context"
}}
```
"""
    return user_prompt


def create_part1_consolidation_prompt(
    selections: list[dict],
    disease_context: str = "cancer"
) -> str:
    """Create prompt to consolidate multiple Part 1 iterations.

    Args:
        selections: List of selections from each iteration
        disease_context: Disease context for interpretation

    Returns:
        Formatted prompt string
    """
    selections_text = ""
    for i, sel in enumerate(selections, 1):
        selections_text += f"""
### Iteration {i}:
- Clusters: {sel.get('clusters', [])}
- Cell Types: {sel.get('cell_types', [])}
- Pathways: {sel.get('pathways', [])}
- Reasoning: {sel.get('reasoning', 'N/A')}
"""

    return f"""## Consolidate Part 1 Analysis Results

You performed {len(selections)} iterations of Part 1 analysis. Now consolidate these into a final selection.

### All Iteration Results:
{selections_text}

### Instructions:
1. Identify clusters, cell types, and pathways that appear consistently across iterations
2. Prioritize selections that are biologically coherent in the context of {disease_context}
3. If there are conflicts, choose based on strongest statistical evidence and biological relevance

**Provide final consolidated selection:**
```json
{{
    "clusters": ["final_cluster1", "final_cluster2"],
    "cell_types": ["final_celltype1", "final_celltype2"],
    "pathways": ["final_pathway1", "final_pathway2"],
    "reasoning": "Consolidated biological interpretation explaining the relationship between selected elements in {disease_context}"
}}
```
"""


# ===== Part 2 Analysis Prompts =====

PART2_SYSTEM_PROMPT = """You are an expert in cell-cell interaction analysis and NMF-based pattern discovery.
Your task is to analyze Part 2 results (CCI analysis with NMF) and select the most relevant factor and L-R pairs.

## Your Analysis Goals:
1. Select ONE NMF factor most relevant to the clusters identified in Part 1
2. Identify pathways enriched in that factor
3. Select top 3 ligand-receptor pairs based on factor loading and pathway relevance

## Part 1 Context (Already Selected):
- Clusters of Interest: {selected_clusters}
- Cell Types of Interest: {selected_cell_types}
- Pathways of Interest: {selected_pathways}

## Analysis Guidelines:
- Choose the factor with highest scores in the Part 1 selected clusters
- Verify that factor's pathway enrichment aligns with Part 1 pathways
- For L-R pairs, prioritize those with:
  1. High factor loading
  2. Relevant pathway associations
  3. ctSVG matches with selected cell types
"""


def create_part2_analysis_prompt(
    state: dict,
    part1_selection: dict
) -> str:
    """Create prompt for Part 2 analysis.

    Args:
        state: Current agent state with loaded data
        part1_selection: Final Part 1 selection

    Returns:
        Formatted prompt string
    """
    system = PART2_SYSTEM_PROMPT.format(
        selected_clusters=part1_selection.get("clusters", []),
        selected_cell_types=part1_selection.get("cell_types", []),
        selected_pathways=part1_selection.get("pathways", [])
    )

    return f"""{system}

## Part 2 Data Analysis

### 6. CCI Analysis - LIANA (sig_liana.csv)
Ligand-receptor pairs with Moran's R values. Significant: MoransR > 0 & pval < 0.05.
Positive Moran's R = spatial co-clustering.

```
{state.get("sig_liana", "Data not loaded")[:3000]}...
```

### 7. NMF Factor Scores per Cluster (res_liana_cluster_factor.csv)
Factor scores showing activation level of each intercellular pattern per spot/cluster.

```
{state.get("res_liana_cluster_factor", "Data not loaded")[:2000]}...
```

### 8. Pathway Enrichment by Factor (sig_liana_pathway_factor.csv)
Pathway enrichment for each NMF factor.

```
{state.get("sig_liana_pathway_factor", "Data not loaded")}
```

### 9. Final L-R Selection Table (interest_anno_sig_liana.csv)
Final selected interactions with ctSVG annotations.

Columns include: liana_interaction, ligand, receptor, morans, Factor scores, progeny (pathway),
disease, ligand_ctSVG, receptor_ctSVG

```
{state.get("interest_anno_sig_liana", "Data not loaded")[:3000]}...
```

---

**Instructions:**
1. Use `sequentialthinking` tool for systematic analysis
2. First, identify which Factor has highest scores in clusters: {part1_selection.get("clusters", [])}
3. Verify that factor's pathway enrichment matches Part 1 pathways: {part1_selection.get("pathways", [])}
4. From interest_anno_sig_liana.csv, select top 3 L-R pairs based on:
   - High loading for selected factor
   - Pathway matching Part 1 selections
   - ctSVG matching Part 1 cell types

**Provide your selection:**
```json
{{
    "selected_factor": "FactorN",
    "factor_pathways": ["pathway1", "pathway2"],
    "top_lr_pairs": ["LIGAND1^RECEPTOR1", "LIGAND2^RECEPTOR2", "LIGAND3^RECEPTOR3"],
    "reasoning": "Explanation of factor-cluster relationship and L-R pair significance"
}}
```
"""


# ===== Part 3 Analysis Prompts =====

def create_part3_analysis_prompt(
    state: dict,
    part1_selection: dict,
    part2_selection: dict
) -> str:
    """Create prompt for Part 3 analysis (L-R pair visualization interpretation).

    Args:
        state: Current agent state
        part1_selection: Final Part 1 selection
        part2_selection: Part 2 selection

    Returns:
        Formatted prompt string
    """
    return f"""## Part 3: Ligand-Receptor Pair Analysis

Based on previous analyses, interpret the spatial patterns of selected L-R pairs.

### Context from Previous Parts:
- **Selected Clusters**: {part1_selection.get("clusters", [])}
- **Cell Types**: {part1_selection.get("cell_types", [])}
- **Pathways**: {part1_selection.get("pathways", [])}
- **Selected Factor**: {part2_selection.get("selected_factor", "N/A")}
- **Top L-R Pairs**: {part2_selection.get("top_lr_pairs", [])}

### Figures to Interpret:
1. **Figure 10**: Spatial plots for L-R pairs showing expression patterns
2. **Figure 11**: Summary of L-R interactions with permutation-based p-values

### Instructions:
For each selected L-R pair, provide:
1. Spatial distribution pattern (co-localization with specific clusters)
2. Biological significance in {state.get("disease_context", "cancer")}
3. Potential functional implications (signaling outcomes)

**Output Format:**
```json
{{
    "lr_interpretations": [
        {{
            "pair": "LIGAND^RECEPTOR",
            "spatial_pattern": "Description of spatial distribution",
            "biological_significance": "Role in disease context",
            "functional_implications": "Downstream effects"
        }}
    ],
    "integrated_summary": "How these L-R pairs work together in the tissue microenvironment"
}}
```
"""


# ===== Literature Search Prompts =====

def create_literature_search_prompt(
    part1_selection: dict,
    part2_selection: dict,
    disease_context: str = "cancer"
) -> str:
    """Create prompt for literature search queries.

    Args:
        part1_selection: Part 1 selections
        part2_selection: Part 2 selections
        disease_context: Disease context

    Returns:
        Formatted prompt string
    """
    return f"""## Generate Literature Search Queries

Based on the biological findings, generate search queries for PubMed to find supporting literature.

### Key Findings to Support:
- **Cell Types**: {part1_selection.get("cell_types", [])}
- **Pathways**: {part1_selection.get("pathways", [])}
- **L-R Pairs**: {part2_selection.get("top_lr_pairs", [])}
- **Disease Context**: {disease_context}

### Instructions:
Generate 5-10 specific search queries that combine:
1. Cell type + Pathway + Disease (e.g., "macrophage MAPK signaling breast cancer")
2. Ligand-Receptor + Disease (e.g., "SPP1 CD44 tumor microenvironment")
3. Pathway + Cell type interaction + Disease

Use the `article_searcher` tool from biomcp MCP to search for each query.

For each search:
1. Use genes/diseases/keywords parameters appropriately
2. Collect PMIDs from relevant results
3. Prioritize recent publications (last 5 years) with high relevance
"""


# ===== Verification Prompts =====

def create_verification_prompt(
    interpretation: str,
    context: str = ""
) -> str:
    """Create prompt for RAG-based verification.

    Args:
        interpretation: Biological interpretation to verify
        context: Additional context

    Returns:
        Formatted prompt string
    """
    return f"""## Verify Biological Interpretation

Use the downloaded papers in the RAG collection to verify and enhance this interpretation.

### Interpretation to Verify:
{interpretation}

### Instructions:
1. Use `multi_query` tool to generate 3-5 verification queries
2. Search the 'CCIAgent_interpretor' collection for each query
3. For each claim in the interpretation:
   - Find supporting evidence from downloaded papers
   - Note the PMID for citations
   - If contradictory evidence exists, note it
4. Enhance the interpretation with additional relevant findings

### Output Format:
```json
{{
    "verified_claims": [
        {{
            "claim": "original claim text",
            "evidence": "supporting evidence from papers",
            "pmids": ["PMID1", "PMID2"],
            "confidence": "high/medium/low"
        }}
    ],
    "additional_insights": "New relevant information from papers",
    "updated_interpretation": "Enhanced interpretation with citations"
}}
```
"""


# ===== Report Generation Prompts =====

def create_report_generation_prompt(
    state: dict,
    part1_selection: dict,
    part2_selection: dict
) -> str:
    """Create prompt for final HTML report generation.

    Args:
        state: Current agent state with all interpretations
        part1_selection: Part 1 selections
        part2_selection: Part 2 selections

    Returns:
        Formatted prompt string
    """
    return f"""## Generate Comprehensive HTML Report

Create a detailed biological interpretation report following the reference.html template structure.

### Report Structure:
1. **Part 1 Tab**: Pre-CCI Analysis (Figures 1-5)
   - Spatial Clustering Analysis
   - Cell Type Composition Analysis
   - Neighborhood Enrichment Analysis
   - Spatial Pathway Enrichment (Decoupler)
   - Spatial Pathway Enrichment (MISTy)

2. **Part 2 Tab**: CCI Analysis (Figures 6-9)
   - Cell-Cell Interaction (LIANA)
   - Intercellular Pattern Analysis (NMF Factors)
   - Pathway Enrichment by Factor
   - ctSVG Analysis

3. **Part 3 Tab**: L-R Pair Analysis (Figures 10-11)
   - Spatial L-R Plots
   - L-R Interaction Summary
   - Paginated table of interest_anno_sig_liana.csv

4. **Summary Tab**: Integrated Findings
   - Key Discoveries
   - Biological Implications
   - References

### Content to Include:

**Part 1 Interpretation:**
{state.get("part1_interpretation", "Not yet generated")}

**Part 2 Interpretation:**
{state.get("part2_interpretation", "Not yet generated")}

**Part 3 Interpretation:**
{state.get("part3_interpretation", "Not yet generated")}

**Summary:**
{state.get("summary_interpretation", "Not yet generated")}

**Selected Elements:**
- Clusters: {part1_selection.get("clusters", [])}
- Cell Types: {part1_selection.get("cell_types", [])}
- Pathways: {part1_selection.get("pathways", [])}
- Factor: {part2_selection.get("selected_factor", "N/A")}
- L-R Pairs: {part2_selection.get("top_lr_pairs", [])}

**References (PMIDs):**
{state.get("pmid_list", [])}

### Styling Requirements:
- Use dark theme with colors: #64ffda (teal), #ffd166 (yellow), #ff6b9d (pink)
- Tab-based navigation for each part
- Paginated table for L-R pairs (5 per page, max 20)
- PMID links in format: https://pubmed.ncbi.nlm.nih.gov/{{PMID}}/
- Include all figure images from the result directory
"""


# ===== HTML Template =====

HTML_REPORT_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Cell-Cell Interaction Analysis Report - {disease_context}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}

        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #e4e4e4;
            line-height: 1.6;
            padding: 20px;
        }}

        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background: rgba(26, 26, 46, 0.95);
            border-radius: 15px;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
            padding: 40px;
        }}

        h1 {{
            color: #64ffda;
            font-size: 2.5em;
            margin-bottom: 10px;
            text-align: center;
            text-shadow: 0 0 10px rgba(100, 255, 218, 0.5);
        }}

        .subtitle {{
            text-align: center;
            color: #aaa;
            font-size: 1.2em;
            margin-bottom: 40px;
            font-style: italic;
        }}

        h2 {{
            color: #64ffda;
            font-size: 2em;
            margin-top: 40px;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid #64ffda;
        }}

        h3 {{
            color: #ffd166;
            font-size: 1.5em;
            margin-top: 30px;
            margin-bottom: 15px;
        }}

        h4 {{
            color: #ff6b9d;
            font-size: 1.2em;
            margin-top: 20px;
            margin-bottom: 10px;
        }}

        .analysis-section {{
            background: rgba(35, 35, 60, 0.6);
            padding: 25px;
            border-radius: 10px;
            margin-bottom: 30px;
            border-left: 4px solid #64ffda;
        }}

        .figure-container {{
            text-align: center;
            margin: 30px 0;
            background: rgba(0, 0, 0, 0.3);
            padding: 20px;
            border-radius: 10px;
        }}

        .figure-container img {{
            max-width: 100%;
            height: auto;
            border-radius: 8px;
            box-shadow: 0 5px 15px rgba(100, 255, 218, 0.3);
        }}

        .figure-caption {{
            color: #aaa;
            font-style: italic;
            margin-top: 15px;
            font-size: 0.95em;
        }}

        .interpretation {{
            background: rgba(100, 255, 218, 0.1);
            padding: 20px;
            border-left: 4px solid #64ffda;
            border-radius: 5px;
            margin: 20px 0;
        }}

        .key-findings {{
            background: rgba(255, 107, 157, 0.1);
            padding: 20px;
            border-radius: 5px;
            margin: 20px 0;
        }}

        .key-findings ul {{
            list-style-position: inside;
            margin-left: 20px;
        }}

        .key-findings li {{
            margin: 10px 0;
            color: #e4e4e4;
        }}

        .reference {{
            color: #64ffda;
            text-decoration: none;
            font-weight: bold;
        }}

        .reference:hover {{
            text-decoration: underline;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
            background: rgba(35, 35, 60, 0.6);
            border-radius: 8px;
            overflow: hidden;
        }}

        th {{
            background: rgba(100, 255, 218, 0.2);
            color: #64ffda;
            padding: 12px;
            text-align: left;
            font-weight: bold;
            border-bottom: 2px solid #64ffda;
        }}

        td {{
            padding: 10px 12px;
            border-bottom: 1px solid rgba(100, 255, 218, 0.1);
        }}

        tr:hover {{
            background: rgba(100, 255, 218, 0.05);
        }}

        .tabs {{
            display: flex;
            gap: 10px;
            margin: 20px 0;
            flex-wrap: wrap;
            border-bottom: 2px solid #64ffda;
            padding-bottom: 10px;
        }}

        .tab-button {{
            background: rgba(35, 35, 60, 0.8);
            color: #64ffda;
            border: 2px solid #64ffda;
            padding: 12px 24px;
            cursor: pointer;
            border-radius: 5px 5px 0 0;
            transition: all 0.3s ease;
            font-size: 1.1em;
            font-weight: 500;
        }}

        .tab-button:hover {{
            background: rgba(100, 255, 218, 0.2);
            transform: translateY(-2px);
        }}

        .tab-button.active {{
            background: rgba(100, 255, 218, 0.3);
            border-bottom: 2px solid transparent;
        }}

        .tab-content {{
            display: none;
            animation: fadeIn 0.3s ease;
        }}

        .tab-content.active {{
            display: block;
        }}

        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(10px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}

        .pagination {{
            display: flex;
            justify-content: center;
            gap: 10px;
            margin: 20px 0;
        }}

        .pagination button {{
            background: rgba(35, 35, 60, 0.8);
            color: #64ffda;
            border: 1px solid #64ffda;
            padding: 8px 16px;
            cursor: pointer;
            border-radius: 5px;
            transition: all 0.3s ease;
        }}

        .pagination button:hover {{
            background: rgba(100, 255, 218, 0.2);
        }}

        .pagination button.active {{
            background: rgba(100, 255, 218, 0.3);
        }}

        .summary-box {{
            background: linear-gradient(135deg, rgba(100, 255, 218, 0.1) 0%, rgba(255, 107, 157, 0.1) 100%);
            padding: 25px;
            border-radius: 10px;
            margin: 30px 0;
            border: 2px solid rgba(100, 255, 218, 0.3);
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Comprehensive Cell-Cell Interaction Analysis Report</h1>
        <p class="subtitle">{disease_context} - Spatial Transcriptomics Analysis</p>

        <div class="tabs">
            <button class="tab-button active" onclick="openTab('part1')">Part 1: Pre-CCI</button>
            <button class="tab-button" onclick="openTab('part2')">Part 2: CCI Analysis</button>
            <button class="tab-button" onclick="openTab('part3')">Part 3: L-R Pairs</button>
            <button class="tab-button" onclick="openTab('summary')">Summary</button>
        </div>

        <!-- Part 1 Content -->
        <div id="part1" class="tab-content active">
            {part1_content}
        </div>

        <!-- Part 2 Content -->
        <div id="part2" class="tab-content">
            {part2_content}
        </div>

        <!-- Part 3 Content -->
        <div id="part3" class="tab-content">
            {part3_content}
        </div>

        <!-- Summary Content -->
        <div id="summary" class="tab-content">
            {summary_content}
        </div>
    </div>

    <script>
        function openTab(tabName) {{
            // Hide all tabs
            document.querySelectorAll('.tab-content').forEach(tab => {{
                tab.classList.remove('active');
            }});
            document.querySelectorAll('.tab-button').forEach(btn => {{
                btn.classList.remove('active');
            }});

            // Show selected tab
            document.getElementById(tabName).classList.add('active');
            event.target.classList.add('active');
        }}

        // Pagination for L-R table
        let currentPage = 1;
        const itemsPerPage = 5;
        const maxItems = 20;

        function showPage(page) {{
            const rows = document.querySelectorAll('#lr-table tbody tr');
            const totalPages = Math.min(Math.ceil(rows.length / itemsPerPage), Math.ceil(maxItems / itemsPerPage));

            if (page < 1) page = 1;
            if (page > totalPages) page = totalPages;
            currentPage = page;

            rows.forEach((row, index) => {{
                if (index >= maxItems) {{
                    row.style.display = 'none';
                }} else if (index >= (page - 1) * itemsPerPage && index < page * itemsPerPage) {{
                    row.style.display = '';
                }} else {{
                    row.style.display = 'none';
                }}
            }});

            // Update pagination buttons
            document.querySelectorAll('.pagination button').forEach((btn, i) => {{
                btn.classList.toggle('active', i + 1 === page);
            }});
        }}

        // Initialize pagination on load
        document.addEventListener('DOMContentLoaded', () => {{
            const table = document.getElementById('lr-table');
            if (table) {{
                showPage(1);
            }}
        }});
    </script>
</body>
</html>
'''
