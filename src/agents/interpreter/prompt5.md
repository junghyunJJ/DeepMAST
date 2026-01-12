# prompt5.md - Biological Interpreter Agent Specification

## Overview

**Agent Name**: CCIInterpreterAgent (Biological Interpreter Agent)
**Purpose**: Automated interpretation of Cell-Cell Interaction (CCI) spatial transcriptomics analysis results with literature-backed biological insights
**Architecture**: LangGraph Deep Agent with MCP Server Integration
**Target Audience**: General biologists (requires terminology explanations)

---

## Agent Workflow Summary

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        CCIInterpreterAgent Workflow                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  [START] → load_data → part1_analysis (3-5 iterations)                      │
│                              ↓                                              │
│                        part2_analysis (3-5 iterations)                      │
│                              ↓                                              │
│                      ┌──────────────────┐                                   │
│                      │ HUMAN-IN-THE-LOOP │ ← L-R pair selection approval    │
│                      └──────────────────┘                                   │
│                              ↓                                              │
│                        part3_analysis → literature_search                   │
│                              ↓                    ↓                         │
│                        paper_download → rag_storage → verification          │
│                              ↓                                              │
│                        report_generation → [END]                            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Part 1: Pre-CCI Analysis (Automated, No LLM Thinking)

### Overview
- **Data Source**: `n_adata.h5ad` (normalized AnnData)
- **Iterations**: Fixed 3-5 iterations
- **Consolidation**: Accumulate all iteration results by section
- **Output**: JSON file with selected clusters, cell types, pathways

### Figures to Process (1-5)

| Figure | Name | Source | Result CSV |
|--------|------|--------|------------|
| 1 | Spatial Clustering | `res/1.spatial.png` | - |
| 2 | Cell Type Composition | `res/2.celltype_heatmap_analysis.png` | `sig_clusterwithcelltyp.csv` |
| 3 | Neighborhood Enrichment | `res/3.neighborhood_enrichment_squidpy.png` | `res_nhood_enrichment.csv` |
| 4 | Spatial Pathway Enrichment | `res/4.spatial_enrich_decoupler.png` | `sig_PathwayEnrich_decoupler.csv` |
| 5 | Spatial Relationship (MISTy) | `res/5.spatial_relation_MISTy.png` | `res_SpatialRelationship_MISTy.csv` |

### Part 1 Analysis Logic

```python
# Pseudocode for Part 1 iteration
for iteration in range(NUM_ITERATIONS):  # 3-5 iterations
    # 1. Read CSV files (no LLM thinking needed)
    celltype_data = read_csv("sig_clusterwithcelltyp.csv")
    nhood_data = read_csv("res_nhood_enrichment.csv")
    pathway_data = read_csv("sig_PathwayEnrich_decoupler.csv")
    misty_data = read_csv("res_SpatialRelationship_MISTy.csv")

    # 2. Select clusters (FDR < 0.05, top 2-3)
    selected_clusters = select_significant_clusters(celltype_data)

    # 3. Select related cell types
    selected_celltypes = select_related_celltypes(celltype_data, selected_clusters)

    # 4. Select pathways (padj < 0.05)
    selected_pathways = select_significant_pathways(pathway_data, selected_clusters)

    # 5. Accumulate results
    accumulate_iteration_results(iteration, results)

# Output to Part 2
part1_output = {
    "selected_clusters": [...],
    "selected_celltypes": [...],
    "selected_pathways": [...],
    "all_interpretations": [...]  # All iteration results accumulated
}
```

### Selection Criteria
- **Clusters**: FDR < 0.05 from `sig_clusterwithcelltyp.csv`, select 2-3 clusters
- **Cell Types**: Associated with selected clusters (FDR < 0.05)
- **Pathways**: padj < 0.05 from `sig_PathwayEnrich_decoupler.csv`
- **Additional Clusters**: From neighborhood enrichment (Squidpy) if related

---

## Part 2: CCI Analysis with NMF (Automated, No LLM Thinking)

### Overview
- **Data Source**: `lrdata.h5ad` (CCI, Moran's R, NMF results)
- **Iterations**: Fixed 3-5 iterations
- **Input**: Part 1 output (clusters, cell types, pathways)
- **Output**: JSON file with selected Factor and candidate L-R pairs

### Figures to Process (6-9)

| Figure | Name | Source | Result CSV |
|--------|------|--------|------------|
| 6 | LIANA Moran's R | `res/6.liana_MoransR.png` | - |
| 7 | NMF Factor Spatial | `res/7.factor_spatial_NMF.png` | `res_liana_cluster_factor.csv` |
| 8 | Pathway Factor Heatmap | `res/8.pathway_factor_heatmap.png` | `sig_liana_pathway_factor.csv` |
| 9 | Quadrant Analysis | `res/9.quadrant_analysis.png` | `anno_sig_liana_CCI.csv`, `interest_anno_sig_liana.csv` |

### Factor Selection Logic

```python
# Select Factor with highest score in selected cluster
def select_factor(cluster_factor_data, selected_clusters):
    """
    Factor score 계산: 선택된 클러스터에서 가장 높은 Factor 값
    """
    factor_scores = {}
    for factor in factor_columns:
        score = cluster_factor_data[
            cluster_factor_data['Cluster'].isin(selected_clusters)
        ][factor].mean()
        factor_scores[factor] = score

    selected_factor = max(factor_scores, key=factor_scores.get)
    return selected_factor
```

### Part 2 → Part 3 Output
- **Top Scoring L-R Pairs**: Based on combined scoring (see Part 3)
- **Selected Factor**: Single factor most relevant to selected clusters
- **Pathway Validation**: Compare with Part 1 pathways

---

## Part 3: L-R Pair Selection (LLM-Driven with HITL)

### Human-in-the-Loop Interrupt Point
```python
# HITL occurs ONLY before Part 3 L-R selection
interrupt_result = interrupt({
    "question": "L-R pair 선택을 확인해주세요",
    "candidate_pairs": top_scoring_pairs,
    "scoring_breakdown": scoring_details,
    "recommendation": recommended_pairs
})
```

### L-R Pair Scoring System

**Combined Score Formula** (LLM decides weights dynamically):
```
Total Score = w1 * Factor_Score + w2 * Pathway_Score + w3 * MoransR_Score + w4 * ctSVG_Score
```

| Component | Source | Calculation |
|-----------|--------|-------------|
| Factor Score | `res_liana_cluster_factor.csv` | Selected cluster's Factor value |
| Pathway Score | `sig_liana_pathway_factor.csv` | Match with Part 1 pathways (0 or 1) |
| Moran's R Score | `anno_sig_liana_CCI.csv` | Normalized Moran's R value |
| ctSVG Score | `interest_anno_sig_liana.csv` | Ligand/Receptor ctSVG presence |

### Selection Parameters
- **Number of L-R pairs**: 3 pairs
- **Weight Decision**: LLM dynamically determines weights based on data quality and context

### Scoring Implementation

```python
def calculate_lr_score(lr_pair, selected_factor, selected_pathways, selected_celltypes):
    """
    LLM이 동적으로 가중치를 결정하여 L-R pair 점수 계산
    """
    # Factor Score: 선택된 클러스터의 Factor 값
    factor_score = lr_data[selected_factor]

    # Pathway Score: Part 1 pathway와 일치 여부
    pathway_match = 1 if lr_pair['progeny'] in selected_pathways else 0

    # Moran's R Score: 공간적 co-localization
    morans_score = normalize(lr_pair['morans'])

    # ctSVG Score: Cell type specific spatially variable gene 여부
    ctsvg_score = calculate_ctsvg_relevance(
        lr_pair['ligand_ctSVG'],
        lr_pair['receptor_ctSVG'],
        selected_celltypes
    )

    # LLM이 가중치 결정
    weights = llm_determine_weights(data_quality_assessment)

    total_score = (
        weights['factor'] * factor_score +
        weights['pathway'] * pathway_match +
        weights['morans'] * morans_score +
        weights['ctsvg'] * ctsvg_score
    )

    return total_score
```

---

## Part 3: Figure Generation

### Figure 10-11 Specifications
- **Tool**: Python (matplotlib/seaborn)
- **Input Data**: AnnData (.h5ad) file
- **Output**: Base64 encoded images embedded in HTML

### Figure 10: Spatial Plots for L-R Pairs
```python
import scanpy as sc
import matplotlib.pyplot as plt

def generate_lr_spatial_plots(adata, selected_lr_pairs):
    """
    선택된 L-R pairs에 대한 spatial plot 생성
    """
    for lr_pair in selected_lr_pairs:
        ligand, receptor = lr_pair['ligand'], lr_pair['receptor']

        fig, axes = plt.subplots(1, 2, figsize=(12, 5))

        # Ligand expression
        sc.pl.spatial(adata, color=ligand, ax=axes[0], show=False)
        axes[0].set_title(f'{ligand} Expression')

        # Receptor expression
        sc.pl.spatial(adata, color=receptor, ax=axes[1], show=False)
        axes[1].set_title(f'{receptor} Expression')

        # Save as base64
        save_figure_base64(fig, f'figure10_{ligand}_{receptor}.png')
```

### Figure 11: L-R Interaction Summary
```python
def generate_lr_summary_plot(lr_data, selected_lr_pairs):
    """
    L-R pair 발현 값 및 permutation p-values 요약
    """
    # Heatmap or bar plot showing:
    # - Expression levels
    # - Moran's R values
    # - Statistical significance
    pass
```

---

## Literature Search & RAG Workflow

### MCP Server Sequence
```
biomcp (Article Search) → pubmed-download (Download) → langconnect-rag (Store & Verify)
```

### Search Query Format
```python
# L-R + Cell type + Disease 조합 검색
query = f"{ligand} {receptor} {celltype} {disease_context} interaction"
# Example: "CCL2 CCR2 macrophage melanoma tumor microenvironment"
```

### RAG Collection Management
- **Collection Strategy**: Session-based new creation
- **Papers per L-R pair**: 5 papers (total 15 papers for 3 L-R pairs)
- **Collection Naming**: `cci_interpreter_{session_id}_{timestamp}`

### Literature Workflow Implementation

```python
async def literature_search_workflow(selected_lr_pairs, disease_context, tissue_context):
    """
    Literature search → Download → RAG storage → Verification
    """
    all_references = []

    for lr_pair in selected_lr_pairs:
        # 1. Search with biomcp
        query = f"{lr_pair['ligand']} {lr_pair['receptor']} {disease_context}"
        search_results = await biomcp_article_search(query, max_results=10)

        # 2. Filter and select top 5 papers
        selected_papers = select_top_papers(search_results, n=5)

        # 3. Download with pubmed-download
        for paper in selected_papers:
            downloaded = await pubmed_download(pmid=paper['pmid'])

            # 4. Store in RAG collection
            await langconnect_rag_add_document(
                collection_id=session_collection_id,
                text=downloaded['content'],
                filename=f"{paper['pmid']}.txt"
            )

        all_references.extend(selected_papers)

    return all_references
```

### Verification Process
```python
async def verify_interpretations(interpretations, collection_id):
    """
    RAG를 사용하여 biological interpretation 검증
    """
    for interpretation in interpretations:
        # Multi-query for comprehensive verification
        queries = await langconnect_rag_multi_query(interpretation['claim'])

        verification_results = []
        for query in queries:
            results = await langconnect_rag_search(
                collection_id=collection_id,
                query=query,
                search_type="semantic"
            )
            verification_results.extend(results)

        if not verification_results:
            # Verification failed - retry with different query
            retry_query = generate_alternative_query(interpretation)
            retry_results = await retry_literature_search(retry_query)

            if not retry_results:
                interpretation['status'] = 'literature_support_pending'
        else:
            interpretation['status'] = 'verified'
            interpretation['references'] = extract_pmids(verification_results)

    return interpretations
```

---

## HTML Report Specification

### Structure (Tab-based)
```html
<div class="report-container">
    <nav class="tab-navigation">
        <button data-tab="part1">Part 1: Pre-CCI Analysis</button>
        <button data-tab="part2">Part 2: CCI/NMF Analysis</button>
        <button data-tab="part3">Part 3: L-R Visualization</button>
        <button data-tab="literature">Literature References</button>
        <button data-tab="summary">Summary</button>
    </nav>

    <div class="tab-content">
        <!-- Each part's content with figures and interpretations -->
    </div>
</div>
```

### Figure Embedding
- **Format**: Base64 encoded (single HTML file)
- **Example**:
```html
<img src="data:image/png;base64,{base64_encoded_image}" alt="Figure 1: Spatial Clustering">
```

### Output Filename
- **Format**: `report_{YYYYMMDD}_{HHMMSS}.html`
- **Example**: `report_20240115_143022.html`

### interest_anno_sig_liana.csv Table Display
- Paginated table: 5 rows per page
- Maximum 20 rows displayed
- Tab navigation between pages

---

## State Definition

```python
from typing import TypedDict, List, Optional
from pydantic import BaseModel

class Part1Selection(BaseModel):
    clusters: List[str]
    celltypes: List[str]
    pathways: List[str]
    iteration_results: List[dict]  # All iterations accumulated

class Part2Selection(BaseModel):
    selected_factor: str
    factor_scores: dict
    candidate_lr_pairs: List[dict]
    pathway_validation: dict

class LRPairScore(BaseModel):
    ligand: str
    receptor: str
    factor_score: float
    pathway_score: float
    morans_score: float
    ctsvg_score: float
    total_score: float
    weights_used: dict

class LiteratureReference(BaseModel):
    pmid: str
    title: str
    relevance: str
    verification_status: str

class CCIInterpreterState(TypedDict):
    # Configuration
    config: dict  # disease_context, tissue_context from user
    data_dir: str
    output_dir: str

    # Data
    n_adata_path: str  # Part 1 data
    lr_adata_path: str  # Part 2/3 data

    # Part 1
    part1_iteration: int
    part1_max_iterations: int  # 3-5
    part1_selections: List[Part1Selection]
    part1_complete: bool

    # Part 2
    part2_iteration: int
    part2_max_iterations: int  # 3-5
    part2_selections: List[Part2Selection]
    part2_complete: bool

    # Part 3
    lr_scoring_results: List[LRPairScore]
    selected_lr_pairs: List[dict]  # Final 3 pairs
    part3_figures: List[str]  # Base64 encoded

    # Literature
    rag_collection_id: str
    literature_references: List[LiteratureReference]
    verified_interpretations: List[dict]

    # Report
    html_report: str
    report_filename: str

    # Workflow control
    error_state: Optional[str]
    requires_human_input: bool
```

---

## Node Definitions

### Node 1: load_data
```python
async def load_data(state: CCIInterpreterState, config: RunnableConfig) -> dict:
    """
    데이터 로드 및 초기화
    """
    # Load configuration from user input
    disease_context = config.get("disease_context", "cancer")
    tissue_context = config.get("tissue_context", "tumor")

    # Verify data files exist
    data_dir = state.get("data_dir", "res_bc")

    # Initialize RAG collection
    collection_id = await create_rag_collection(f"cci_interpreter_{session_id}")

    return {
        "config": {"disease": disease_context, "tissue": tissue_context},
        "rag_collection_id": collection_id,
        "part1_iteration": 0,
        "part1_max_iterations": 5,  # Fixed count
        "part2_iteration": 0,
        "part2_max_iterations": 5,
    }
```

### Node 2: part1_analysis
```python
async def part1_analysis(state: CCIInterpreterState, config: RunnableConfig) -> dict:
    """
    Part 1: Pre-CCI Analysis (3-5 iterations, no LLM thinking)
    """
    iteration = state["part1_iteration"]

    # Read CSV files
    celltype_data = read_csv("sig_clusterwithcelltyp.csv")
    nhood_data = read_csv("res_nhood_enrichment.csv")
    pathway_data = read_csv("sig_PathwayEnrich_decoupler.csv")
    misty_data = read_csv("res_SpatialRelationship_MISTy.csv")

    # Automated selection (no LLM thinking)
    selection = Part1Selection(
        clusters=select_clusters(celltype_data),
        celltypes=select_celltypes(celltype_data),
        pathways=select_pathways(pathway_data),
        iteration_results=generate_interpretation(iteration)
    )

    # Accumulate results
    all_selections = state.get("part1_selections", []) + [selection]

    return {
        "part1_iteration": iteration + 1,
        "part1_selections": all_selections,
        "part1_complete": iteration + 1 >= state["part1_max_iterations"]
    }
```

### Node 3: part2_analysis
```python
async def part2_analysis(state: CCIInterpreterState, config: RunnableConfig) -> dict:
    """
    Part 2: CCI/NMF Analysis (3-5 iterations, no LLM thinking)
    """
    # Use Part 1 final selections
    part1_final = consolidate_part1_results(state["part1_selections"])

    # Read Part 2 CSV files
    cluster_factor = read_csv("res_liana_cluster_factor.csv")
    pathway_factor = read_csv("sig_liana_pathway_factor.csv")
    lr_data = read_csv("anno_sig_liana_CCI.csv")

    # Select Factor based on Part 1 clusters
    selected_factor = select_factor(cluster_factor, part1_final.clusters)

    # Generate candidate L-R pairs with scores
    candidates = calculate_all_lr_scores(lr_data, selected_factor, part1_final)

    return {
        "part2_iteration": state["part2_iteration"] + 1,
        "part2_selections": [...],
        "lr_scoring_results": candidates,
        "part2_complete": True
    }
```

### Node 4: human_approval (HITL)
```python
async def human_approval(state: CCIInterpreterState, config: RunnableConfig) -> dict:
    """
    Human-in-the-loop: L-R pair selection approval
    """
    top_pairs = sorted(state["lr_scoring_results"], key=lambda x: x.total_score, reverse=True)[:5]

    # Interrupt for human approval
    result = interrupt({
        "message": "L-R pair 선택을 확인해주세요",
        "recommended_pairs": top_pairs[:3],
        "all_candidates": top_pairs,
        "scoring_details": generate_score_breakdown(top_pairs)
    })

    # User can approve or modify selection
    selected_pairs = result.get("selected_pairs", top_pairs[:3])

    return {
        "selected_lr_pairs": selected_pairs,
        "requires_human_input": False
    }
```

### Node 5: part3_analysis
```python
async def part3_analysis(state: CCIInterpreterState, config: RunnableConfig) -> dict:
    """
    Part 3: Generate L-R visualization figures
    """
    selected_pairs = state["selected_lr_pairs"]

    # Load AnnData for visualization
    adata = sc.read_h5ad(state["lr_adata_path"])

    # Generate Figure 10: Spatial plots
    figure10_base64 = generate_lr_spatial_plots(adata, selected_pairs)

    # Generate Figure 11: Summary plot
    figure11_base64 = generate_lr_summary_plot(selected_pairs)

    return {
        "part3_figures": [figure10_base64, figure11_base64]
    }
```

### Node 6: literature_search
```python
async def literature_search(state: CCIInterpreterState, config: RunnableConfig) -> dict:
    """
    Literature search using biomcp
    """
    selected_pairs = state["selected_lr_pairs"]
    disease = state["config"]["disease"]

    all_papers = []
    for pair in selected_pairs:
        # Search query: L-R + Cell type + Disease
        query = f"{pair['ligand']} {pair['receptor']} {disease} interaction"

        results = await mcp_biomcp_article_searcher(
            genes=[pair['ligand'], pair['receptor']],
            diseases=[disease],
            keywords=["interaction", "signaling"]
        )

        # Select top 5 papers per L-R pair
        top_papers = results[:5]
        all_papers.extend(top_papers)

    return {
        "literature_search_results": all_papers
    }
```

### Node 7: paper_download
```python
async def paper_download(state: CCIInterpreterState, config: RunnableConfig) -> dict:
    """
    Download papers using pubmed-download MCP
    """
    papers = state["literature_search_results"]
    downloaded = []

    for paper in papers:
        result = await mcp_pubmed_download(
            pmid=paper['pmid'],
            prefer_pmc=True
        )

        if result['success']:
            # Add to RAG collection
            await mcp_langconnect_rag_add_documents(
                collection_id=state["rag_collection_id"],
                text=result['content'],
                filename=f"pmid_{paper['pmid']}.txt"
            )
            downloaded.append(paper)

    return {
        "literature_references": downloaded
    }
```

### Node 8: verification
```python
async def verification(state: CCIInterpreterState, config: RunnableConfig) -> dict:
    """
    Verify interpretations using RAG
    """
    interpretations = state.get("all_interpretations", [])
    verified = []

    for interp in interpretations:
        # Multi-query verification
        queries = await mcp_langconnect_rag_multi_query(interp['claim'])

        for query in queries:
            results = await mcp_langconnect_rag_search(
                collection_id=state["rag_collection_id"],
                query=query,
                search_type="semantic",
                limit=5
            )

            if results:
                interp['verified'] = True
                interp['references'] = extract_references(results)
                break

        if not interp.get('verified'):
            # Retry with different query
            retry_results = await retry_verification(interp)
            if retry_results:
                interp['verified'] = True
            else:
                interp['verified'] = False
                interp['status'] = 'literature_support_pending'

        verified.append(interp)

    return {
        "verified_interpretations": verified
    }
```

### Node 9: report_generation
```python
async def report_generation(state: CCIInterpreterState, config: RunnableConfig) -> dict:
    """
    Generate final HTML report
    """
    from datetime import datetime

    # Generate timestamp filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"report_{timestamp}.html"

    # Build HTML with tabs
    html = generate_tabbed_html_report(
        part1_results=state["part1_selections"],
        part2_results=state["part2_selections"],
        part3_figures=state["part3_figures"],
        literature=state["literature_references"],
        verified_interpretations=state["verified_interpretations"],
        lr_table=state.get("interest_anno_sig_liana_data")
    )

    # Save report
    output_path = f"{state['output_dir']}/{filename}"
    with open(output_path, 'w') as f:
        f.write(html)

    return {
        "html_report": html,
        "report_filename": filename
    }
```

---

## Edge Definitions

```python
def init_edges(self, graph: StateGraph):
    # Start → load_data
    graph.add_edge(START, "load_data")

    # load_data → part1_analysis
    graph.add_edge("load_data", "part1_analysis")

    # Part 1 iteration loop
    graph.add_conditional_edges(
        "part1_analysis",
        lambda state: "part1_analysis" if not state["part1_complete"] else "part2_analysis"
    )

    # Part 2 iteration loop
    graph.add_conditional_edges(
        "part2_analysis",
        lambda state: "part2_analysis" if not state["part2_complete"] else "human_approval"
    )

    # HITL → Part 3
    graph.add_edge("human_approval", "part3_analysis")

    # Part 3 → Literature search
    graph.add_edge("part3_analysis", "literature_search")

    # Literature workflow
    graph.add_edge("literature_search", "paper_download")
    graph.add_edge("paper_download", "verification")
    graph.add_edge("verification", "report_generation")

    # End
    graph.add_edge("report_generation", END)
```

---

## Error Handling

### Manual Intervention (HITL)
- **Trigger**: Error during any node execution
- **Action**: Interrupt and ask user for guidance
- **Recovery**: Resume from error point after user input

### Verification Failure Recovery
1. Generate alternative search query
2. Retry literature search with broader terms
3. If still fails, mark as "literature_support_pending"
4. Continue workflow (don't block)

---

## Configuration

### User-Provided Config
```python
config = {
    "disease_context": "melanoma",  # From user input
    "tissue_context": "tumor microenvironment",  # From user input
    "data_dir": "res_bc",
    "output_dir": "output",
    "num_iterations_part1": 5,
    "num_iterations_part2": 5,
    "num_lr_pairs": 3,
    "papers_per_lr": 5
}
```

### MCP Server Configuration
```python
mcp_config = {
    "biomcp": {"enabled": True},
    "pubmed-download": {"enabled": True},
    "langconnect-rag": {"enabled": True},
    "sequential-thinking": {"enabled": True}
}
```

---

## Summary of Interview Results

| Category | Decision |
|----------|----------|
| Part 1/2 Iterations | Fixed 3-5 count |
| Iteration Consolidation | Accumulate all by section |
| Part 1→2 Data | Full interpretation results |
| Part 2→3 Data | Top scoring L-R pairs only |
| L-R Scoring | Factor + Pathway + Moran's R + ctSVG |
| Weight Decision | LLM decides dynamically |
| L-R Pairs Count | 3 pairs |
| HITL Timing | Only before Part 3 L-R selection |
| Literature Query | L-R + Cell type + Disease |
| Papers per L-R | 5 papers (total 15) |
| RAG Collection | Session-based new creation |
| Verification Failure | Retry with different query |
| Figure Tool | Python (matplotlib/seaborn) |
| Figure Input | AnnData (.h5ad) |
| Figure Source (1-9) | Fixed directory structure |
| Cell Type Source | CSV file |
| Factor Selection | Highest in selected cluster |
| HTML Structure | Tab-based (Part별) |
| Figure Embedding | Base64 encoded |
| Output Filename | Timestamp included |
| Timeout | No limit |
| Target Audience | General biologists |
| Context Source | User config input |
