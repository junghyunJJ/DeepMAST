---
name: biomedical-literature-search
description: Complete literature search workflow for CCI analysis interpretation - provides 5-phase workflow with search timing, strategic planning, quality criteria, and tool usage guidance.
---

# Biomedical Literature Search Strategy

Complete literature search workflow for interpreting ST/CCI analysis results and generating publication-style output with supporting references.

## Purpose

This skill provides the **complete workflow** for the SEARCHER subagent. It defines:
- **WHEN** to search (timing by interpretation phase)
- **WHAT** to search (priority by analysis type)
- **HOW** to validate (quality criteria)
- **WHERE** to write outputs (virtual filesystem)

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│          This SKILL.md (Workflow Definition)                     │
│  - Phase 1: Extract Context                                      │
│  - Phase 2: Think (Strategic Planning)                           │
│  - Phase 3: Search Literature                                    │
│  - Phase 4: Reflect (Quality Loop)                               │
│  - Phase 5: Write Output                                         │
└────────────────────────────┬────────────────────────────────────┘
                             │ (SEARCHER reads workflow, then calls tools)
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│          Python Tools (Execution Layer)                          │
│  - load_analysis_data: Load analysis results and search_context  │
│  - search_literature: Single query search                        │
│  - search_literature_for_context: Multi-strategy search          │
│  - think_tool: Strategic planning and reflection                 │
│  - read_file / write_file: Virtual filesystem operations         │
└─────────────────────────────────────────────────────────────────┘
```

## Virtual Filesystem

| File | Phase | Content |
|------|-------|---------|
| `/data_path.txt` | Read | Real data directory path |
| `/partN_search_context.json` | Phase 1 | Extracted biological terms |
| `/partN_search_strategy.json` | Phase 2 | Prioritized search plan |
| `/partN_papers.json` | Phase 5 | Search results with coverage |

---

## Phase 1: Extract Context

### Step 1.1: Load Data Path
Read **/data_path.txt** to get the REAL data directory path.

### Step 1.2: Load Analysis Data
Call **load_analysis_data** with the exact path from /data_path.txt.

### Step 1.3: Using search_context (MANDATORY)
The load_analysis_data tool returns a pre-extracted **search_context** field containing:
- `genes`: ALL unique genes from interest_sig_liana.csv (~352 items)
- `pathways`: ALL pathways from LIANA progeny + decoupler (~64 items)
- `celltypes`: ALL cell types from ctSVG columns (~13 items)

**Example search_context structure:**
```json
{
  "genes": ["ADAM10", "ADAM17", "B2M", "CD44", "CDH1", "CEACAM5", "ERBB2", "TGFB1", "MMP2", "VEGFA"],
  "pathways": ["Androgen", "EGFR", "Estrogen", "Hypoxia", "NFkB", "TGFb", "MAPK", "PI3K"],
  "celltypes": ["B cells", "Endothelial", "Invasive Tumor", "Stromal", "Macrophages"],
  "source": "interest_sig_liana.csv",
  "stats": {"total_genes": 352, "total_pathways": 64, "total_celltypes": 13}
}
```

### Step 1.4: Write Context File
Write extracted context to **/partN_search_context.json**:
```json
{
  "genes": ["CDH1", "CEACAM5", "ERBB2", "LRIG1", "TGFB1"],
  "pathways": ["NFkB", "Hypoxia", "TGFb", "MAPK"],
  "celltypes": ["Invasive Tumor", "Stromal", "Macrophages"],
  "keywords": ["spatial transcriptomics", "tumor microenvironment"],
  "disease_context": "breast cancer",
  "analysis_focus": "Part N specific focus"
}
```

---

## Phase 2: Think (Strategic Planning)

**MANDATORY**: Use **think_tool** to plan the optimal search strategy BEFORE searching.

### Three-Thought Planning Workflow

**Thought 1: Context Analysis**
```python
think_tool(
    thought="Analyzing Part 1 context: {N} genes extracted from search_context. "
            "Prioritizing {TOP_GENES} based on their roles in {BIOLOGICAL_PROCESS}. "
            "Key pathways identified: {PATHWAYS}. Disease context: {DISEASE}.",
    thoughtNumber=1,
    totalThoughts=3,
    nextThoughtNeeded=True
)
```
- Assess the extracted biological context
- Identify most biologically significant genes
- Note key pathways and disease mechanisms

**Thought 2: Search Strategy Development**
```python
think_tool(
    thought="Search strategy for Part {N}: "
            "1) Gene+disease queries for top 10 genes: {GENE_LIST}, "
            "2) Pathway+celltype for {FOCUS_AREA}: {PATHWAY_LIST}, "
            "3) Spatial transcriptomics + {DISEASE} for methodology papers. "
            "Priority L-R pairs: {LR_PAIRS}.",
    thoughtNumber=2,
    totalThoughts=3,
    nextThoughtNeeded=True
)
```
- Define prioritized gene list (top 10-15, NOT all extracted genes)
- Plan pathway search with cell type context
- Identify key L-R pairs for Part 2/3

**Thought 3: Expected Findings Prediction**
```python
think_tool(
    thought="Expected findings: Papers should cover mechanisms including {MECHANISMS}. "
            "Known relationships to validate: {GENE1}-{PATHWAY1}, {GENE2}-{CELLTYPE}. "
            "Potential gaps requiring targeted follow-up: {GAPS}.",
    thoughtNumber=3,
    totalThoughts=3,
    nextThoughtNeeded=False
)
```
- Predict what biological mechanisms papers should cover
- List known relationships to validate
- Anticipate potential coverage gaps

### Write Search Strategy
Write **/partN_search_strategy.json**:
```json
{
  "priority_genes": ["CDH1", "ERBB2", "TGFB1", "MMP2", "VIM"],
  "priority_pathways": ["NFkB", "Hypoxia", "TGFb", "EMT"],
  "key_lr_pairs": ["TGFB1-TGFBR1", "CDH1-CTNNB1"],
  "search_focus": "EMT and tumor invasion in breast cancer TME",
  "expected_mechanisms": ["E-cadherin loss", "TGFb-induced EMT", "hypoxia response"],
  "predicted_gaps": ["spatial co-localization patterns"]
}
```

---

## Phase 3: Search Literature

### Step 3.1: Execute Multi-Strategy Search
Use **search_literature_for_context** tool with **prioritized** terms from Phase 2:
- genes: Priority genes from search strategy (NOT all 352)
- pathways: Priority pathways from search strategy
- celltypes: Relevant cell types for this Part
- disease: Disease context (e.g., "breast cancer")

```python
search_literature_for_context(
    genes=["CDH1", "TGFB1", "VIM", "ERBB2", "MMP2"],  # Top 10-15 only
    pathways=["EMT", "TGFB", "WNT", "Hypoxia"],
    celltypes=["Tumor", "Fibroblast", "Macrophages"],
    disease="breast cancer",
    max_results=20
)
```

### Step 3.2: Tool Returns
The tool returns:
- `papers`: List of found papers with PMIDs
- `total_papers`: Number of unique papers
- `genes_covered`: Genes found in papers
- `pathways_covered`: Pathways found in papers
- `coverage_summary`: Coverage statistics

---

## Phase 4: Reflect (Quality Loop)

### Quality Criteria

| Criterion | Threshold | Action if Failed |
|-----------|-----------|------------------|
| **Total Papers** | >= 15 unique papers | Broaden search terms |
| **Gene Coverage** | >= 60% of priority genes | Add synonyms, search individually |
| **Pathway Coverage** | >= 50% of priority pathways | Add "signaling", disease context |
| **Max Iterations** | 3 | Proceed with warning |

### Reflection Workflow

**Reflection Thought 1: Coverage Analysis**
```python
think_tool(
    thought="Coverage analysis for Part {N}: "
            "{GENES_COVERED}/{TOTAL_GENES} priority genes covered ({X}%), "
            "{PATHWAYS_COVERED}/{TOTAL_PATHWAYS} pathways covered ({Y}%). "
            "Gaps identified: {MISSING_ITEMS}. "
            "Expected mechanisms covered: {COVERED_MECHANISMS}. "
            "Missing mechanisms: {MISSING_MECHANISMS}. "
            "Follow-up search needed: {YES/NO}",
    thoughtNumber=1,
    totalThoughts=2,
    nextThoughtNeeded=True  # True if gaps exist
)
```

**Reflection Thought 2: Gap-Targeted Strategy** (if coverage < threshold)
```python
think_tool(
    thought="Targeted follow-up strategy: "
            "Searching for {MISSING_GENES} with synonyms {SYNONYMS}. "
            "Adding broader terms for {PATHWAY}: '{PATHWAY} signaling {DISEASE}'. "
            "Alternative queries: {ALTERNATIVE_QUERIES}.",
    thoughtNumber=2,
    totalThoughts=2,
    nextThoughtNeeded=False
)
```

### Coverage Check Logic
```
If genes_covered < 60%:
    -> Add gene synonyms, search individually with search_literature
If pathways_covered < 50%:
    -> Search pathway + "signaling" + disease
If total_papers < 15:
    -> Broaden disease context, add "spatial transcriptomics"
```

### Follow-up Search (if needed)
Use **search_literature** for targeted single-query searches:
```python
search_literature(
    query="SNAI1 EMT breast cancer spatial",
    max_results=10,
    include_preprints=True
)
```

---

## Phase 5: Write Output

### Write Papers File
Write **/partN_papers.json** with this format:
```json
{
  "papers": [
    {
      "pmid": "12345678",
      "title": "E-cadherin loss promotes EMT in breast cancer",
      "abstract": "...",
      "search_type": "gene_disease",
      "relevance_to_context": "Directly discusses CDH1 role in EMT"
    }
  ],
  "coverage": {
    "genes_covered": ["CDH1", "TGFB1", "VIM"],
    "genes_missing": ["SNAI1"],
    "genes_coverage_pct": 75,
    "pathways_covered": ["EMT", "TGFB"],
    "pathways_missing": [],
    "pathways_coverage_pct": 100,
    "total_papers": 18
  },
  "search_iterations": 2,
  "search_queries": [
    "\"CDH1\"[Gene] AND \"breast cancer\"[Title/Abstract]"
  ]
}
```

---

## Part-Specific Search Focus

| Part | Primary Focus | think_tool Priority | Key Analyses |
|------|--------------|---------------------|--------------|
| **Part 1** (Spatial/Pathway) | Spatial patterns, pathway biology | Genes driving spatial organization | 1-1 Spatial, 1-3 Neighborhood, 1-4 Decoupler, 1-5 MISTy |
| **Part 2** (CCI/NMF) | Cell-cell interaction, NMF patterns | L-R pairs, factor composition | 2-6 LIANA Moran's R, 2-7 NMF, 2-8 Pathway-Factor, 2-9 ctSVG |
| **Part 3** (L-R Details) | Ligand-receptor biology | Specific L-R mechanisms | 3-10 L-R Visualization, 3-11 L-R Summary |

### Part 1 Planning Focus
```python
# Thought 1 emphasis: Spatial organization genes
"Prioritizing genes with spatial patterns: markers with high Moran's R,
neighborhood enrichment drivers, pathway-associated genes."

# Thought 2 emphasis: Pathway-spatial queries
"Strategy: 1) Spatial marker genes + disease, 2) Pathway activity + tissue type,
3) Cell type composition + microenvironment."
```

### Part 2 Planning Focus
```python
# Thought 1 emphasis: L-R pairs and cell communication
"Prioritizing L-R pairs from LIANA with high Moran's R (>0.3),
NMF factor-associated genes, ctSVG significant pairs."

# Thought 2 emphasis: Interaction-focused queries
"Strategy: 1) Ligand + receptor + cell-cell interaction, 2) NMF factor genes + pathway,
3) Cell type pairs + communication."
```

### Part 3 Planning Focus
```python
# Thought 1 emphasis: Specific L-R mechanisms
"Focusing on selected L-R pairs: {LR1}, {LR2}, {LR3}.
Mechanism keywords: binding, signaling cascade, downstream effects."

# Thought 2 emphasis: Mechanistic queries
"Strategy: 1) Specific L-R pair + signaling mechanism, 2) Receptor + downstream pathway,
3) Ligand + secretion + source cell type."
```

---

## Common Mistakes to Avoid

### FORBIDDEN ACTIONS
- **DO NOT** use read_file on .csv files - causes context overflow (571KB -> 5KB)
- **DO NOT** try to parse raw CSV data manually
- **DO NOT** extract genes from pathway enrichment `name` column - those are pathways, not genes
- **DO NOT** skip Phase 2 (Think) - MUST plan search strategy before searching
- **DO NOT** search with all 352 genes instead of prioritized 10-15 genes
- **DO NOT** proceed with < 60% gene coverage without additional searches
- **DO NOT** skip reflection after search (Phase 4)

### CORRECT ACTIONS
- **USE** search_context field from load_analysis_data - all terms pre-extracted
- **USE** genes for actual gene symbols: CDH1, CEACAM5, ERBB2, TGFB1, MMP2, VEGFA
- **USE** pathways for pathway names: NFkB, Hypoxia, TGFb, MAPK, PI3K, Estrogen, EGFR
- **USE** think_tool to plan strategy BEFORE search_literature_for_context
- **WRITE** /partN_search_strategy.json before searching
- **RUN** follow-up searches for missing coverage
- **WRITE** /partN_papers.json with coverage metrics

---

## Tool Reference

### search_literature
Single-query PubMed search for specific topics.

```python
search_literature(
    query="APOE TREM2 microglia Alzheimer",
    max_results=20,
    include_preprints=True
)
```

**Use when**: Targeted search for specific gene/pathway/interaction.

### search_literature_for_context
Multi-strategy search with coverage tracking.

```python
search_literature_for_context(
    genes=["CDH1", "TGFB1", "VIM"],
    pathways=["EMT", "TGFB", "WNT"],
    celltypes=["Tumor", "Fibroblast"],
    disease="breast cancer",
    max_results=20
)
```

**Returns**:
- `papers`: List of found papers with PMIDs
- `total_papers`: Number of unique papers
- `genes_covered`: Genes found in papers
- `pathways_covered`: Pathways found in papers
- `coverage_summary`: Coverage statistics

**Use when**: Comprehensive literature support for interpretation.

### think_tool
Strategic planning and reflection.

```python
think_tool(
    thought="Analysis of search context...",
    thoughtNumber=1,
    totalThoughts=3,
    nextThoughtNeeded=True
)
```

**Use when**: Phase 2 (planning) and Phase 4 (reflection).

---

## Output Format

### Interpretation Paragraph
```
Our finding of [analysis result] is consistent with previous reports
demonstrating that [paper's key finding] (Author et al., Year; PMID: xxxxx).
Furthermore, [expand context] (Author2 et al., Year; PMID: xxxxx).
```

**Writing Principles**:
- State analysis result first
- Use connecting phrases: "consistent with", "in line with", "supports"
- Cite 2-3 papers per paragraph with PMIDs
- Include specific statistics from analysis (Moran's R, p-values, FDR)

### Reference List Format
```markdown
## References

1. Author et al. (Year) Title. Journal. PMID: xxxxx
   -> Relevance: [How this paper supports the finding]

2. Author et al. (Year) Title. Journal. PMID: xxxxx
   -> Relevance: [How this paper supports the finding]
```

---

## Quick Reference Card

| Analysis Type | Primary Tool | Key Parameters |
|--------------|--------------|----------------|
| L-R Interaction | `search_literature_for_context` | genes=[ligand, receptor], disease |
| Pathway | `search_literature_for_context` | pathways=[...], disease |
| Gene Markers | `search_literature_for_context` | genes=[...], celltypes |
| Specific Query | `search_literature` | query=specific_terms |

| Quality Check | Threshold | Action if Failed |
|--------------|-----------|------------------|
| Papers | >= 15 | Broaden search terms |
| Gene coverage | >= 60% | Add synonyms, search individually |
| Pathway coverage | >= 50% | Add "signaling", disease context |
| Max iterations | 3 | Proceed with warning |

| Phase | Thoughts | Purpose | Output |
|-------|----------|---------|--------|
| Phase 2 (Planning) | 3 thoughts | Develop search strategy | /partN_search_strategy.json |
| Phase 4 (Reflection) | 1-2 thoughts | Validate coverage, plan follow-up | Updated /partN_papers.json |

| Thought Type | Key Content | nextThoughtNeeded |
|--------------|-------------|-------------------|
| Context Analysis | Gene priorities, pathway focus | True |
| Strategy Development | Search queries, L-R pairs | True |
| Expected Findings | Mechanisms, gaps | False |
| Coverage Reflection | Coverage %, gaps | True if gaps |
| Follow-up Strategy | Targeted queries | False |

---

## Example Workflow

### Input
> Found enriched Apoe-Trem2 interaction (LIANA score: 2.3, p=0.001) in microglia surrounding amyloid plaques in AD mouse brain.

### Phase 1: Extract Context
- Analysis type: L-R Interaction
- Key genes: APOE, TREM2
- Cell types: Microglia
- Disease: Alzheimer's disease

### Phase 2: Think Strategy
```python
think_tool(thought="Context: APOE-TREM2 in microglia. Priority genes: APOE, TREM2.
Key pathways: microglial activation, neuroinflammation. Disease: AD.",
thoughtNumber=1, totalThoughts=3, nextThoughtNeeded=True)
```

### Phase 3: Execute Search
```python
result = search_literature_for_context(
    genes=["APOE", "TREM2"],
    pathways=["TREM2 signaling", "microglial activation"],
    celltypes=["Microglia"],
    disease="Alzheimer disease",
    max_results=20
)
```

### Phase 4: Reflect on Coverage
- Papers found: 18 (pass)
- Genes covered: ["APOE", "TREM2"] (100%) (pass)
- Pathways covered: ["TREM2 signaling"] (50%) (pass)

### Phase 5: Write Output
```python
write_file("/part2_papers.json", json.dumps({
    "papers": [...],
    "coverage": {"genes_coverage_pct": 100, "pathways_coverage_pct": 50, "total_papers": 18},
    "search_iterations": 1
}))
```

### Generated Interpretation
Our finding of enriched Apoe-Trem2 interaction (LIANA score: 2.3, p=0.001) in plaque-associated microglia is consistent with previous reports demonstrating that the TREM2-APOE pathway drives the transcriptional phenotype of disease-associated microglia (Krasemann et al., 2017; PMID: 28930663). This interaction has been shown to be critical for microglial response to amyloid pathology (Zhou et al., 2020; PMID: 31932797).
