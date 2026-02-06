# PubMed E-utilities Search Syntax Reference

Quick reference for PubMed search field tags, MeSH subheadings, publication types,
and date syntax used by `search_pubmed_advanced`.

## Field Tags (Complete)

| Tag | Field | Example |
|-----|-------|---------|
| `[tiab]` | Title/Abstract | `VEGFA[tiab]` |
| `[ti]` | Title only | `spatial transcriptomics[ti]` |
| `[ab]` | Abstract only | `mechanism[ab]` |
| `[mh]` | MeSH heading (exploded) | `neoplasms[mh]` |
| `[mh:noexp]` | MeSH (not exploded) | `breast neoplasms[mh:noexp]` |
| `[majr]` | MeSH Major Topic | `signal transduction[majr]` |
| `[sh]` | MeSH Subheading | `therapy[sh]` |
| `[pt]` | Publication Type | `review[pt]` |
| `[dp]` | Date of Publication | `2023[dp]` |
| `[au]` | Author | `Smith J[au]` |
| `[1au]` | First Author | `Smith J[1au]` |
| `[lastau]` | Last Author | `Smith J[lastau]` |
| `[ta]` | Journal Title Abbreviation | `Nature[ta]` |
| `[la]` | Language | `english[la]` |
| `[gr]` | Grant Number | `R01CA123456[gr]` |
| `[ad]` | Affiliation | `Harvard[ad]` |
| `[tw]` | Text Word (all text fields) | `cancer[tw]` |
| `[nm]` | Substance Name | `aspirin[nm]` |
| `[ot]` | Other Term | `machine learning[ot]` |

## MeSH Subheadings

### Commonly Used in ST/CCI Research

| Subheading | Code | Use For |
|------------|------|---------|
| `/physiology` | PH | Normal biological function |
| `/genetics` | GE | Genetic aspects, gene expression |
| `/metabolism` | ME | Metabolic processes, protein expression |
| `/pathology` | PA | Disease-related changes |
| `/therapy` | TH | Treatment approaches |
| `/drug effects` | DE | Response to drugs/chemicals |
| `/immunology` | IM | Immune responses |
| `/cytology` | CY | Cellular aspects |
| `/analysis` | AN | Analytical methods |
| `/methods` | MT | Methodological aspects |
| `/classification` | CL | Categorization |
| `/diagnosis` | DI | Diagnostic aspects |

### Usage Examples
```
# TGF-beta signaling function
transforming growth factor beta/physiology[mh]

# Cancer genetics
neoplasms/genetics[mh]

# Drug effects on cell communication
cell communication/drug effects[mh]

# Multiple subheadings
neoplasms/genetics[mh] OR neoplasms/pathology[mh]
```

## Publication Types

### Research Articles
| Type | Tag |
|------|-----|
| Journal Article | `Journal Article[pt]` |
| Research Article | Implicit (default) |
| Clinical Trial | `Clinical Trial[pt]` |
| Randomized Controlled Trial | `Randomized Controlled Trial[pt]` |
| Observational Study | `Observational Study[pt]` |

### Reviews & Meta-analyses
| Type | Tag |
|------|-----|
| Review | `Review[pt]` |
| Systematic Review | `Systematic Review[pt]` |
| Meta-Analysis | `Meta-Analysis[pt]` |
| Scoping Review | `Scoping Review[pt]` |

### Other
| Type | Tag |
|------|-----|
| Case Reports | `Case Reports[pt]` |
| Comment | `Comment[pt]` |
| Editorial | `Editorial[pt]` |
| Letter | `Letter[pt]` |
| Preprint | `Preprint[pt]` |
| Practice Guideline | `Practice Guideline[pt]` |
| Retracted Publication | `Retracted Publication[pt]` |

## Date Syntax

### Date Range in Query
```
# Year range
2020:2025[dp]

# Specific date range
2023/01/01:2025/12/31[dp]

# Single year
2024[dp]

# From date to present
2023/01/01:3000[dp]
```

### Using min_date/max_date Parameters
```python
# Papers from 2023 onward
search_pubmed_advanced(query="...", min_date="2023/01/01")

# Papers before 2020
search_pubmed_advanced(query="...", max_date="2019/12/31")

# Specific range
search_pubmed_advanced(query="...", min_date="2022/01/01", max_date="2024/12/31")
```

## Boolean Operators

| Operator | Meaning | Example |
|----------|---------|---------|
| `AND` | Both required | `VEGFA[tiab] AND cancer[mh]` |
| `OR` | Either matches | `CDH1[tiab] OR E-cadherin[tiab]` |
| `NOT` | Exclude | `cancer[tiab] NOT review[pt]` |

**Precedence**: NOT > AND > OR

**Always use parentheses** for complex queries:
```
(VEGFA[tiab] OR FLT1[tiab]) AND (neoplasms[mh] OR tumor[tiab]) NOT review[pt]
```

## Proximity Search

Find terms within N words of each other:
```
"spatial transcriptomics"[TIAB:~3]    # within 3 words
"cell cell interaction"[TIAB:~5]       # within 5 words
"ligand receptor"[TIAB:~2]             # within 2 words
```

## Automatic Term Mapping (ATM)

PubMed automatically maps untagged terms:
- `cancer` → maps to MeSH "Neoplasms" + title/abstract search
- `BRCA1` → maps to gene search + title/abstract

### Bypassing ATM
```
# Force title/abstract only (no MeSH mapping)
VEGFA[tiab]

# Force exact phrase
"spatial transcriptomics"[tiab]

# Force MeSH without explosion
breast neoplasms[mh:noexp]
```

## ST/CCI-Specific MeSH Terms

### Spatial Analysis
| Concept | MeSH Term |
|---------|-----------|
| Spatial transcriptomics | Gene Expression Profiling[mh] |
| In situ hybridization | In Situ Hybridization, Fluorescence[mh] |
| Single cell analysis | Single-Cell Analysis[mh] |
| Tissue microarray | Tissue Array Analysis[mh] |

### Cell Communication
| Concept | MeSH Term |
|---------|-----------|
| Cell-cell interaction | Cell Communication[mh] |
| Paracrine signaling | Paracrine Communication[mh] |
| Autocrine signaling | Autocrine Communication[mh] |
| Gap junctions | Gap Junctions[mh] |
| Receptor-ligand | Protein Binding[mh] |

### Tumor Biology
| Concept | MeSH Term |
|---------|-----------|
| TME | Tumor Microenvironment[mh] |
| EMT | Epithelial-Mesenchymal Transition[mh] |
| Angiogenesis | Neovascularization, Pathologic[mh] |
| Metastasis | Neoplasm Metastasis[mh] |
| Immune evasion | Tumor Escape[mh] |

### Signaling Pathways
| Concept | MeSH Term |
|---------|-----------|
| Signal transduction | Signal Transduction[mh] |
| TGF-beta | Transforming Growth Factor beta[mh] |
| WNT | Wnt Signaling Pathway[mh] |
| Notch | Receptors, Notch[mh] |
| NF-kB | NF-kappa B[mh] |
| MAPK | MAP Kinase Signaling System[mh] |
| PI3K/AKT | Phosphatidylinositol 3-Kinases[mh] |
| JAK/STAT | Janus Kinases[mh] |

### Cell Types
| Cell Type | MeSH Term |
|-----------|-----------|
| Fibroblast | Fibroblasts[mh] |
| Macrophage | Macrophages[mh] |
| T cell | T-Lymphocytes[mh] |
| B cell | B-Lymphocytes[mh] |
| Endothelial | Endothelial Cells[mh] |
| Epithelial | Epithelial Cells[mh] |
| Stem cell | Stem Cells[mh] |
| NK cell | Killer Cells, Natural[mh] |
| Dendritic cell | Dendritic Cells[mh] |

## Example Queries for Common ST/CCI Tasks

### Find L-R interaction papers
```
(TGFB1[tiab] AND TGFBR2[tiab]) AND cell communication[mh] AND neoplasms[mh]
```

### Find spatial transcriptomics methodology
```
(spatial transcriptomics[tiab] OR Visium[tiab] OR MERFISH[tiab]) AND methods[sh] AND 2022:2025[dp]
```

### Find pathway crosstalk papers
```
(wnt signaling pathway[mh] AND transforming growth factor beta[mh]) AND epithelial-mesenchymal transition[mh]
```

### Find cell type interaction in TME
```
(fibroblasts[mh] AND macrophages[mh]) AND tumor microenvironment[mh] AND cell communication[mh]
```

### Find recent reviews on CCI methods
```
(cell communication[mh] OR cell-cell interaction[tiab]) AND (single-cell analysis[mh] OR spatial[tiab]) AND systematic review[pt] AND 2023:2025[dp]
```
