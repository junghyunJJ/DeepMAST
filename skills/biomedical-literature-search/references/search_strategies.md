# Search Strategies Reference

Detailed search strategies and keyword combinations by result type.

## L-R Interaction Search Strategy

### Required Parameters
- `genes`: Include both ligand and receptor gene symbols
- `keywords`: "ligand receptor", "cell cell interaction" required

### Recommended Keyword Combinations

| Analysis Tool | Additional Keywords |
|---------------|---------------------|
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
article_searcher(
  genes=["APOE", "TREM2"],
  diseases=["Alzheimer disease"],
  keywords=["ligand receptor", "microglia", "cell cell interaction"],
  include_preprints=True,
  page_size=20
)

# SPP1-CD44 in tumor
article_searcher(
  genes=["SPP1", "CD44"],
  diseases=["neoplasms"],
  keywords=["ligand receptor", "tumor microenvironment", "macrophage"],
  include_preprints=True,
  page_size=20
)
```

---

## Pathway Search Strategy

### Required Parameters
- `keywords`: pathway name + "pathway" or "signaling"

### Major Pathway Keywords

| Pathway | Recommended Keywords |
|---------|---------------------|
| WNT | "WNT pathway", "WNT signaling", "beta-catenin" |
| NFkB | "NFkB pathway", "NF-kappa B", "inflammatory signaling" |
| TNFa | "TNF signaling", "TNF-alpha", "TNFR" |
| TGFb | "TGF-beta signaling", "SMAD", "fibrosis" |
| JAK-STAT | "JAK STAT pathway", "cytokine signaling" |
| PI3K-AKT | "PI3K AKT", "mTOR signaling" |
| MAPK | "MAPK pathway", "ERK signaling" |

### Analysis Tool-specific Keywords
- PROGENy: "pathway activity", "footprint"
- decoupler: "pathway enrichment", "functional analysis"
- GSEA: "gene set enrichment"

### Search Examples
```python
# WNT pathway in AD
article_searcher(
  genes=None,
  diseases=["Alzheimer disease"],
  keywords=["WNT pathway", "spatial transcriptomics", "neurodegeneration"],
  include_preprints=True,
  page_size=20
)

# With specific pathway genes
article_searcher(
  genes=["CTNNB1", "WNT5A"],
  diseases=["Alzheimer disease"],
  keywords=["WNT signaling", "spatial"],
  include_preprints=True,
  page_size=20
)
```

---

## Gene/Marker Search Strategy

### Required Parameters
- `genes`: List of target gene symbols

### Context-specific Keywords

| Context | Recommended Keywords |
|---------|---------------------|
| Spatial marker | "spatial transcriptomics", "spatial distribution" |
| Cell type marker | "cell type", "marker gene", "single cell" |
| DEG | "differential expression", "upregulated", "downregulated" |
| Cluster marker | "cluster", "subpopulation", "heterogeneity" |

### Search Examples
```python
# Spatial marker genes
article_searcher(
  genes=["GFAP", "AQP4"],
  diseases=["Alzheimer disease"],
  keywords=["astrocyte", "spatial transcriptomics", "marker"],
  include_preprints=True,
  page_size=20
)
```

---

## Search Result Filtering Tips

### include_preprints Setting
- `True`: Include latest research, quick trend identification
- `False`: Peer-reviewed papers only, more reliable references

### page_size Setting
- 10-20: General reference search
- 30-50: Comprehensive literature review

### When Results Are Scarce
1. Remove some keywords to expand search scope
2. Change diseases to more general terms
3. Search with genes only, then filter manually
