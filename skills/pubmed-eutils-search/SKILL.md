---
name: pubmed-eutils-search
description: Advanced PubMed search using NCBI E-utilities - MeSH terms, field tags, date filters, publication types, and proximity search for targeted literature retrieval.
---

# PubMed E-utilities Advanced Search Guide

Search strategy guide for using `search_pubmed_advanced` tool with NCBI E-utilities
for precise, controlled PubMed queries in spatial transcriptomics and CCI analysis.

## When to Use E-utilities vs BioMCP

| Feature | BioMCP (search_literature_dynamic) | E-utilities (search_pubmed_advanced) |
|---------|------------------------------------|--------------------------------------|
| Gene synonym resolution | Automatic (PubTator3 NER) | Manual (use [tiab] field) |
| MeSH subheadings | Not supported | Full support (e.g., `/therapy[mh]`) |
| Date filtering | Not supported | Full support (YYYY/MM/DD) |
| Publication type filter | Not supported | Full support (`[pt]`) |
| Proximity search | Not supported | Supported (`[TIAB:~N]`) |
| Query control | LLM-generated | Full raw query control |
| Best for | Initial broad search | Targeted gap-filling |

**Rule of thumb**: Use BioMCP first for broad coverage, then E-utilities for precision.

## Core Concepts

### Field Tags

The most important field tags for ST/CCI research:

| Tag | Field | Example | Use When |
|-----|-------|---------|----------|
| `[tiab]` | Title/Abstract | `VEGFA[tiab]` | Searching specific terms in text |
| `[mh]` | MeSH heading | `neoplasms[mh]` | Broad concept search with MeSH tree |
| `[majr]` | MeSH Major Topic | `signal transduction[majr]` | Papers focused on this topic |
| `[pt]` | Publication Type | `review[pt]` | Filter by article type |
| `[dp]` | Date of Publication | `2023/01/01:2025/12/31[dp]` | Date range filter |
| `[au]` | Author | `Smith J[au]` | Author search |
| `[ta]` | Journal | `Nature[ta]` | Journal filter |

### MeSH Subheadings

MeSH terms can be combined with subheadings for precision:

```
# Diabetes treatment papers only
diabetes mellitus/therapy[mh]

# Cancer genetics papers
neoplasms/genetics[mh]

# TGF-beta physiology
transforming growth factor beta/physiology[mh]
```

Common subheadings for ST/CCI research:
- `/physiology` — Normal function
- `/genetics` — Genetic aspects
- `/metabolism` — Metabolic processes
- `/pathology` — Disease-related changes
- `/therapy` — Treatment approaches
- `/drug effects` — Drug responses

### Boolean Operators

```
# AND: Both terms required
VEGFA[tiab] AND cancer[mh]

# OR: Either term matches
(CDH1[tiab] OR E-cadherin[tiab])

# NOT: Exclude term
breast cancer[tiab] NOT review[pt]
```

**Operator precedence**: NOT > AND > OR. Use parentheses for clarity.

### Proximity Search

Find terms within N words of each other:
```
# "spatial" and "transcriptomics" within 3 words
"spatial transcriptomics"[TIAB:~3]

# "cell" and "interaction" within 5 words
"cell interaction"[TIAB:~5]
```

### Automatic Term Mapping (ATM)

PubMed automatically maps untagged terms to MeSH. To bypass ATM:
- Use field tags: `VEGFA[tiab]` (searches only title/abstract)
- Use double quotes: `"spatial transcriptomics"[tiab]` (exact phrase)
- Use `[mh:noexp]` to prevent MeSH tree explosion

## Query Patterns for ST/CCI Research

### Pattern 1: Gene + Disease + MeSH
```
VEGFA[tiab] AND breast neoplasms[mh] AND signal transduction[mh]
```

### Pattern 2: L-R Pair + Mechanism
```
(TGFB1[tiab] AND TGFBR2[tiab]) AND (epithelial-mesenchymal transition[mh] OR EMT[tiab])
```

### Pattern 3: Cell Type Communication
```
(fibroblast[tiab] AND epithelial[tiab]) AND cell communication[mh] AND spatial[tiab]
```

### Pattern 4: Recent Spatial Transcriptomics
```
spatial transcriptomics[tiab] AND cell-cell interaction[tiab] AND 2023:2025[dp]
```

### Pattern 5: Systematic Reviews for Pathway
```
TGF-beta signaling[tiab] AND systematic review[pt] AND cancer[tiab]
```

### Pattern 6: MeSH Subheading Precision
```
transforming growth factor beta/physiology[mh] AND neoplasms/genetics[mh]
```

### Pattern 7: NMF/Spatial Methods
```
(non-negative matrix factorization[tiab] OR NMF[tiab]) AND (single cell[tiab] OR spatial[tiab])
```

## Using with search_pubmed_advanced Tool

### Basic Usage
```python
search_pubmed_advanced(
    query="VEGFA[tiab] AND neoplasms[mh]",
    max_results=20
)
```

### With Date Filter
```python
search_pubmed_advanced(
    query="spatial transcriptomics[tiab] AND cell-cell interaction[tiab]",
    max_results=15,
    min_date="2023/01/01"
)
```

### With Sort by Date
```python
search_pubmed_advanced(
    query="CDH1[tiab] AND EMT[tiab] AND breast cancer[tiab]",
    max_results=10,
    sort="pub_date",
    min_date="2022/01/01"
)
```

### Using build_pubmed_query Helper
```python
from src.agents.deep_interpreter.tools.pubmed_eutils import build_pubmed_query

query = build_pubmed_query(
    genes=["VEGFA", "CDH1"],
    pathways=["TGF-beta", "WNT"],
    disease="breast cancer",
    mesh_terms=["signal transduction"],
    publication_types=["review"],
    date_range=("2022/01/01", "2025/12/31")
)
# → "(VEGFA[tiab] OR CDH1[tiab]) AND ("TGF-beta"[tiab] OR "WNT"[tiab]) AND "breast cancer"[tiab] AND signal transduction[mh] AND ("review"[pt]) AND 2022/01/01:2025/12/31[dp]"

search_pubmed_advanced(query=query, max_results=20)
```

## Gap-Filling Strategy

After `search_literature_dynamic` completes with partial coverage:

1. **Identify gaps**: Check `coverage.genes_missing` and `coverage.pathways_missing`
2. **Build targeted queries**: Use missing terms with MeSH precision
3. **Date-restrict if needed**: Focus on recent papers for cutting-edge findings
4. **Deduplicate**: Papers already found by BioMCP are deduplicated by PMID in `_calculate_coverage()`

### Example Gap-Filling Workflow
```python
# After search_literature_dynamic: gene coverage = 45%, missing: ["ADAM10", "MMP14"]

# Query 1: Missing gene with MeSH disease
search_pubmed_advanced(query="ADAM10[tiab] AND neoplasms[mh] AND cell communication[mh]")

# Query 2: Missing gene with spatial context
search_pubmed_advanced(query="MMP14[tiab] AND extracellular matrix[mh] AND spatial[tiab]", min_date="2020/01/01")

# Query 3: Pathway-level search for uncovered area
search_pubmed_advanced(query="matrix metalloproteinase/physiology[mh] AND tumor microenvironment[tiab]")
```

## Common ST/CCI MeSH Terms

| Concept | MeSH Term |
|---------|-----------|
| Cell-cell interaction | Cell Communication[mh] |
| Spatial transcriptomics | Spatial Gene Expression Analysis[mh] |
| EMT | Epithelial-Mesenchymal Transition[mh] |
| Tumor microenvironment | Tumor Microenvironment[mh] |
| Signal transduction | Signal Transduction[mh] |
| L-R interaction | Ligands[mh], Receptors, Cell Surface[mh] |
| Extracellular matrix | Extracellular Matrix[mh] |
| Immune microenvironment | Tumor Escape[mh] |
| Pathway analysis | Metabolic Networks and Pathways[mh] |
| Single cell | Single-Cell Analysis[mh] |

## Rate Limits

- Without API key: 3 requests/second (enforced automatically)
- Max 100 results per search
- EFetch batches: 50 PMIDs per request

For detailed field tag reference, see: `references/search_syntax.md`
