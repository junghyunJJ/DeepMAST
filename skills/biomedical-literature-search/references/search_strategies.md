# Search Strategies Reference

Detailed search strategies and keyword combinations by result type.

> **Note**: This is a supplementary reference for `SKILL.md`. See SKILL.md for the complete 5-phase workflow.

---

## Tool API Reference

### search_literature_dynamic (PRIMARY)
LLM-powered dynamic search with context-aware query generation and internal fallback.
Prefer running through this skill wrapper script:

```bash
python scripts/search_literature_dynamic.py \
  --genes "GENE1,GENE2" \
  --pathways "pathway1" \
  --celltypes "CellType1" \
  --disease "disease name" \
  --max-results 20
```

Equivalent direct tool call:

```python
search_literature_dynamic(
    genes=["GENE1", "GENE2"],      # Gene symbols (10-15 prioritized)
    pathways=["pathway1"],          # Pathway names
    celltypes=["CellType1"],        # Cell type names
    disease="disease name",         # Disease context (string, not list)
    max_results=20                  # Number of results
)
```

### search_literature (Targeted)
Single-query PubMed search for specific topics.

```python
search_literature(
    query="specific search terms",
    max_results=20
)
```

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
    max_results=20
)

# SPP1-CD44 in tumor
search_literature_dynamic(
    genes=["SPP1", "CD44"],
    pathways=["integrin signaling", "ECM remodeling"],
    celltypes=["Macrophages", "Tumor"],
    disease="breast cancer",
    max_results=20
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
    max_results=20
)

# With pathway-associated genes
search_literature_dynamic(
    genes=["CTNNB1", "WNT5A", "AXIN2"],
    pathways=["WNT"],
    celltypes=["Epithelial"],
    disease="colorectal cancer",
    max_results=20
)

# Targeted pathway search
search_literature(
    query="TGF-beta signaling EMT breast cancer spatial transcriptomics",
    max_results=15
)
```

---

## Gene/Marker Search Strategy

### Required Parameters
- `genes`: List of target gene symbols (prioritize 10-15)
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
    max_results=20
)

# EMT-related markers
search_literature_dynamic(
    genes=["CDH1", "VIM", "SNAI1", "ZEB1"],
    pathways=["EMT", "TGFb"],
    celltypes=["Tumor", "Epithelial"],
    disease="breast cancer",
    max_results=20
)

# Targeted gene search
search_literature(
    query="CDH1 E-cadherin loss breast cancer invasion",
    max_results=10
)
```

---

## Search Result Optimization

### max_results Setting
- 25-30: Standard search (meets quality threshold)
- 10: Targeted follow-up search
- 30: Comprehensive literature review

### When Results Are Scarce
1. Use `search_literature` with broader query terms
2. Remove specific cell types to expand scope
3. Search with genes only: `search_literature(query="GENE1 GENE2 disease")`
4. Add synonyms: "E-cadherin" for CDH1, "TGF-beta" for TGFB1

### Coverage Optimization
Per SKILL.md quality criteria:
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
