# Search Strategies Reference

Detailed search strategies, tool API, and examples for the `biomedical-literature-search` skill.

> **Note**: This is the canonical reference for `SKILL.md`. See SKILL.md for the 4-phase workflow (Extract → Search → Reflect → Output). This file holds the tool API, advanced patterns, part-specific focus, quick reference card, and full worked examples.

---

## Complete Tool API Reference

### search_literature_dynamic (PRIMARY)

LLM-powered dynamic search with context-aware query generation and internal fallback. This is the primary search tool for all phases.

**Preferred: CLI wrapper**
```bash
python scripts/search_literature_dynamic.py \
  --genes "CDH1,TGFB1,VIM,ERBB2,MMP2" \
  --pathways "EMT,TGFB,WNT,Hypoxia" \
  --celltypes "Tumor,Fibroblast,Macrophages" \
  --disease "breast cancer" \
  --max-results 20 \
  --output-path "papers.json"
```

**Equivalent direct tool call**:
```python
search_literature_dynamic(
    genes=["CDH1", "TGFB1", "VIM"],       # Gene symbols (top 30 from hybrid score)
    pathways=["EMT", "TGFB", "WNT"],       # Pathway names
    celltypes=["Tumor", "Fibroblast"],     # Cell type names
    disease="breast cancer",                # Disease context (string)
    max_results=20,                         # Number of results
    output_path="papers.json",              # Auto-save full results to DEEP_INTERPRETER_DATA_DIR/papers.json
    target_gene_coverage=0.6,               # Gene coverage threshold
    target_pathway_coverage=0.5,            # Pathway coverage threshold
    max_iterations=3,                       # Internal refinement loop cap
    enforce_disease_match=True,             # Post-filter by disease context
    rerank_mode="off",                      # "off" or "llm" for optional rerank
)
```

**Returns (with `output_path`)** — compact summary:
- `saved_to`: Absolute path of saved JSON
- `output_path`: Filename specified
- `total_papers`: Number of papers saved (no truncation)
- `coverage`: Full coverage metrics (`genes_covered`, `genes_missing`, `genes_coverage_pct`, `pathways_*`)
- `paper_titles`: First 10 titles for quick preview
- `message`: Confirmation

**Returns (without `output_path`)** — full result:
- `papers`: List of found papers with PMIDs, abstracts, search_type, relevance_to_context
- `generated_queries`: LLM-generated query structures (for debugging)
- `coverage`: Full metrics
- `think_success`: `True` if LLM query generation succeeded, `False` if internal fallback used

**Fallback behavior**: If LLM query generation fails, automatically switches to a fixed 4-strategy internal search. No separate tool call needed.

### search_literature (Targeted Follow-up)

Single-query PubMed search for targeted gap filling.

```python
search_literature(
    genes=["APOE", "TREM2"],
    disease="Alzheimer",
    keywords=["microglia", "neuroinflammation"],
    max_results=15,
    include_preprints=True
)
```

Or with freeform query:
```python
search_literature(
    query="SNAI1 EMT breast cancer spatial",
    max_results=10,
    include_preprints=True
)
```

**Use when**: Phase 3 coverage gaps remain (missing genes/pathways), or specific topic follow-up after `search_literature_dynamic`.

### think_tool (Phase 3 Reflection)

Structured sequential thinking for quality validation.

```python
think_tool(
    reflection="Coverage analysis for Part N: ...",   # Your reasoning content
    iteration=1,                                       # Current thought number
    max_iterations=2,                                  # Total thoughts planned
    score_threshold=0.7                                # Optional quality threshold
)
```

**Use when**: Phase 3 reflection — validating coverage and planning follow-up searches (1-2 thoughts per iteration).

---

## Advanced PubMed E-utilities Patterns

Use `search_pubmed_advanced` for targeted precision searches after `search_literature_dynamic` when coverage gaps remain in specific areas.

**When to use**:
- Gene coverage < 60% after Phase 3.1: Search missing genes with MeSH terms
- Need recent papers (last 2 years): Use date filter
- Need specific study types: Use publication type filter
- Need pathway-specific papers: Use MeSH subheadings
- Full control over PubMed query syntax (field tags, proximity operators, etc.)

**Example queries**:
```python
# MeSH subheading for pathway mechanisms
search_pubmed_advanced(
    query="TGF-beta signaling/physiology[mh] AND spatial transcriptomics[tiab]"
)

# Recent systematic reviews
search_pubmed_advanced(
    query="cell-cell interaction[tiab] AND systematic review[pt]",
    min_date="2023/01/01"
)

# Specific L-R interaction with date range and MeSH terms
search_pubmed_advanced(
    query="CDH1[tiab] AND E-cadherin[tiab] AND epithelial mesenchymal[mh]",
    min_date="2020/01/01"
)

# Proximity search for co-occurring terms
search_pubmed_advanced(
    query='"spatial transcriptomics cell interaction"[TIAB:~5]'
)

# Multiple genes with publication type filter
search_pubmed_advanced(
    query="(VEGFA[tiab] OR TGFB1[tiab]) AND neoplasms[mh] AND review[pt]",
    min_date="2022/01/01",
    max_results=10
)
```

**Key advantage over BioMCP**: Full control over PubMed query syntax including MeSH subheadings, field tags, date ranges, proximity operators, and publication type filters. Use this when you know exactly what you're looking for.

**Full E-utilities syntax reference**: See `skills/pubmed-eutils-search/SKILL.md`.

---

## Part-Specific Search Focus

| Part | Primary Focus | think_tool Priority | Key Analyses |
|------|--------------|---------------------|--------------|
| **Part 1** (Spatial/Pathway) | Spatial patterns, pathway biology | Genes driving spatial organization | 1-1 Spatial, 1-3 Neighborhood, 1-4 Decoupler, 1-5 MISTy |
| **Part 2** (CCI/NMF) | Cell-cell interaction, NMF patterns | L-R pairs, factor composition | 2-6 LIANA Moran's R, 2-7 NMF, 2-8 Pathway-Factor, 2-9 ctSVG |
| **Part 3** (L-R Details) | Ligand-receptor biology | Specific L-R mechanisms | 3-10 L-R Visualization, 3-11 L-R Summary |

---

## L-R Interaction Search Strategy

### Required Parameters
- `genes`: Include both ligand and receptor gene symbols
- `disease`: Disease context as string

### Recommended Keyword Combinations

| Analysis Tool | Additional Keywords for query |
|---------------|-------------------------------|
| LIANA+ | "LIANA", "ligand receptor inference" |
| CellChat | "CellChat", "cell communication" |
| CellPhoneDB | "CellPhoneDB", "receptor ligand" |
| NicheNet | "NicheNet", "ligand target" |

### Disease-specific MeSH Term Examples
- Alzheimer: "Alzheimer disease", "neurodegeneration", "dementia"
- Cancer: "neoplasms", "tumor microenvironment", "cancer"
- Inflammation: "inflammation", "immune response"

### Search Examples
```python
# Apoe-Trem2 in AD
search_literature_dynamic(
    genes=["APOE", "TREM2"],
    pathways=["TREM2 signaling", "microglial activation"],
    celltypes=["Microglia"],
    disease="Alzheimer disease",
    max_results=20,
    output_path="papers.json"
)

# SPP1-CD44 in tumor
search_literature_dynamic(
    genes=["SPP1", "CD44"],
    pathways=["integrin signaling", "ECM remodeling"],
    celltypes=["Macrophages", "Tumor"],
    disease="breast cancer",
    max_results=20,
    output_path="papers.json"
)

# Targeted follow-up search
search_literature(
    query="SPP1 CD44 tumor microenvironment macrophage",
    max_results=10
)
```

---

## Pathway Search Strategy

### Required Parameters
- `pathways`: Pathway names from analysis (PROGENy, decoupler)
- `disease`: Disease context

### Major Pathway Keywords

| Pathway | Recommended Search Terms |
|---------|--------------------------|
| WNT | "WNT pathway", "WNT signaling", "beta-catenin" |
| NFkB | "NFkB pathway", "NF-kappa B", "inflammatory signaling" |
| TNFa | "TNF signaling", "TNF-alpha", "TNFR" |
| TGFb | "TGF-beta signaling", "SMAD", "fibrosis" |
| JAK-STAT | "JAK STAT pathway", "cytokine signaling" |
| PI3K-AKT | "PI3K AKT", "mTOR signaling" |
| MAPK | "MAPK pathway", "ERK signaling" |
| Hypoxia | "hypoxia", "HIF-1", "oxygen sensing" |
| Estrogen | "estrogen receptor", "ER signaling" |
| Androgen | "androgen receptor", "AR signaling" |
| EGFR | "EGFR signaling", "ErbB", "receptor tyrosine kinase" |
| VEGF | "VEGF signaling", "angiogenesis", "vascular" |
| p53 | "p53 pathway", "tumor suppressor", "apoptosis" |

### Analysis Tool-specific Keywords
- PROGENy: "pathway activity", "footprint"
- decoupler: "pathway enrichment", "functional analysis"
- GSEA: "gene set enrichment"

### Search Examples
```python
# Pathway-focused search (no specific genes)
search_literature_dynamic(
    genes=[],
    pathways=["WNT", "TGFb", "Hypoxia"],
    celltypes=["Fibroblast", "Tumor"],
    disease="breast cancer",
    max_results=20,
    output_path="papers.json"
)

# With pathway-associated genes
search_literature_dynamic(
    genes=["CTNNB1", "WNT5A", "AXIN2"],
    pathways=["WNT"],
    celltypes=["Epithelial"],
    disease="colorectal cancer",
    max_results=20,
    output_path="papers.json"
)
```

---

## Gene/Marker Search Strategy

### Required Parameters
- `genes`: List of target gene symbols (top 30 from search_context pre-filter)
- `celltypes`: Associated cell types

### Context-specific Search Terms

| Context | Recommended Keywords for query |
|---------|--------------------------------|
| Spatial marker | "spatial transcriptomics", "spatial distribution" |
| Cell type marker | "cell type", "marker gene", "single cell" |
| DEG | "differential expression", "upregulated", "downregulated" |
| Cluster marker | "cluster", "subpopulation", "heterogeneity" |
| EMT markers | "epithelial mesenchymal transition", "E-cadherin", "vimentin" |

### Search Examples
```python
# Spatial marker genes
search_literature_dynamic(
    genes=["GFAP", "AQP4", "SLC1A2"],
    pathways=[],
    celltypes=["Astrocyte"],
    disease="Alzheimer disease",
    max_results=20,
    output_path="papers.json"
)

# EMT-related markers
search_literature_dynamic(
    genes=["CDH1", "VIM", "SNAI1", "ZEB1"],
    pathways=["EMT", "TGFb"],
    celltypes=["Tumor", "Epithelial"],
    disease="breast cancer",
    max_results=20,
    output_path="papers.json"
)
```

---

## Search Result Optimization

### `max_results` Setting
- 25-30: Standard search (meets quality threshold)
- 10: Targeted follow-up search
- 30-40: Comprehensive literature review

### When Results Are Scarce
1. Use `search_literature` with broader query terms
2. Remove specific cell types to expand scope
3. Search with genes only: `search_literature(query="GENE1 GENE2 disease")`
4. Add synonyms: "E-cadherin" for CDH1, "TGF-beta" for TGFB1

### Coverage Optimization (per SKILL.md quality criteria)
- Gene coverage >= 60%
- Pathway coverage >= 50%
- Total papers >= 25

If coverage is insufficient after initial search:
```python
# Follow-up for missing genes
search_literature(
    query="MISSING_GENE disease_context spatial",
    max_results=10
)
```

---

## Quick Reference Card

### Tool Selection by Analysis Type

| Analysis Type | Primary Tool | Follow-up Tool | Key Parameters |
|--------------|--------------|----------------|----------------|
| L-R Interaction | `search_literature_dynamic` | `search_literature` | genes=[ligand, receptor], disease |
| Pathway | `search_literature_dynamic` | `search_literature` | pathways=[...], disease |
| Gene Markers | `search_literature_dynamic` | `search_literature` | genes=[...], celltypes |
| Specific Query | `search_literature` | — | query=specific_terms |
| Advanced MeSH | `search_pubmed_advanced` | — | MeSH field tags, date filter |

### Tool Selection Flow
```
search_literature_dynamic (primary — handles fallback internally)
        │
        ├─ Success → Use results
        │
        └─ Insufficient coverage (Phase 3 reflect)
                │
                ├─ search_literature (targeted follow-up for gaps)
                │
                └─ search_pubmed_advanced (precision MeSH queries)
```

### Quality Check Thresholds

| Quality Check | Threshold | Action if Failed |
|--------------|-----------|------------------|
| Total Papers | >= 25 | Broaden search terms |
| Gene coverage | >= 60% | Add synonyms, search individually |
| Pathway coverage | >= 50% | Add "signaling", disease context |
| Max iterations | 3 | Proceed with warning |

### Phase-to-Tool Mapping

| Phase | Tool | Thoughts | Purpose | Output |
|-------|------|----------|---------|--------|
| Phase 1 (Extract) | `load_analysis_data` | — | Load `search_context` | `/search_context.json` |
| Phase 2 (Search) | `search_literature_dynamic` | — | Primary search | `/papers.json` (auto) |
| Phase 3 (Reflect) | `think_tool` | 1-2 | Validate coverage | (internal) |
| Phase 3 follow-up | `search_literature` | — | Gap filling | append to `/papers.json` |
| Phase 4 (Output) | (auto-saved) | — | — | `/papers.json` |

### Thought Types for think_tool

| Thought Type | Key Content | should_continue |
|--------------|-------------|-------------------|
| Coverage Reflection | Coverage %, gaps | True if gaps |
| Follow-up Strategy | Targeted queries | False |

---

## Interpretation Output Format

> **Note**: The SEARCHER subagent's responsibility ends at `/papers.json`. The interpretation paragraph and reference list formatting below are consumed by the INTERPRETER subagent, documented here for end-to-end traceability.

### Interpretation Paragraph Template
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

## Full Example: Apoe-Trem2 in Alzheimer Disease

### Input
> Found enriched Apoe-Trem2 interaction (LIANA score: 2.3, p=0.001) in microglia surrounding amyloid plaques in AD mouse brain.

### Phase 1: Extract Context
- Analysis type: L-R Interaction
- Key genes: APOE, TREM2
- Cell types: Microglia
- Disease: Alzheimer's disease

### Phase 2: Execute Dynamic Search
```bash
python scripts/search_literature_dynamic.py \
  --genes "APOE,TREM2" \
  --pathways "TREM2 signaling,microglial activation" \
  --celltypes "Microglia" \
  --disease "Alzheimer disease" \
  --max-results 20 \
  --output-path "papers.json"
# Fallback handled internally — result contains compact summary with total_papers, coverage
```

**Dynamic search benefits in this example**:
- LLM understands APOE-TREM2 is a well-known AD pathway
- Generates optimized queries like "TREM2 APOE microglia neurodegeneration"
- Better coverage of mechanistic papers
- Automatic internal fallback if LLM fails

### Phase 3: Reflect on Coverage (think_tool)
```python
think_tool(
    reflection="Coverage: 28 papers found. Genes: APOE, TREM2 (100%). "
               "Pathways: TREM2 signaling (50%). All thresholds met. "
               "think_success: True. No follow-up needed.",
    iteration=1,
    max_iterations=1
)
```
- Papers found: 28 (pass >= 25)
- Genes covered: ["APOE", "TREM2"] (100% pass)
- Pathways covered: ["TREM2 signaling"] (50% pass)
- think_success: True (no fallback needed)

### Phase 4: Output (Auto-Saved)
Papers already auto-saved via `output_path` in Phase 2 — no `write_file` needed.
```python
# result = {"saved_to": "/path/to/papers.json", "total_papers": 28, "coverage": {...}}
# Use read_file("/papers.json") if you need to inspect the saved data
```

### Generated Interpretation (by INTERPRETER)
> Our finding of enriched Apoe-Trem2 interaction (LIANA score: 2.3, p=0.001) in plaque-associated microglia is consistent with previous reports demonstrating that the TREM2-APOE pathway drives the transcriptional phenotype of disease-associated microglia (Krasemann et al., 2017; PMID: 28930663). This interaction has been shown to be critical for microglial response to amyloid pathology (Zhou et al., 2020; PMID: 31932797).
