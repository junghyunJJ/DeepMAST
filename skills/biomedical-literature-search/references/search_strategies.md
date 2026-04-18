# Search Strategies Reference

Detailed search strategies, tool API, and examples for the `biomedical-literature-search` skill.

Note: this reference expands the SEARCHER-facing workflow in `SKILL.md`. The active SEARCHER contract is coverage-driven: extract context, run the primary search, inspect `coverage_sufficient` plus `recommended_actions`, and follow up only when the result says more work is needed.

## Table of Contents

- [Complete Tool API Reference](#complete-tool-api-reference)
- [Advanced PubMed E-utilities Patterns](#advanced-pubmed-e-utilities-patterns)
- [Part-Specific Search Focus](#part-specific-search-focus)
- [L-R Interaction Search Strategy](#l-r-interaction-search-strategy)
- [Pathway Search Strategy](#pathway-search-strategy)
- [Gene/Marker Search Strategy](#genemarker-search-strategy)
- [Search Result Optimization](#search-result-optimization)
- [Quick Reference Card](#quick-reference-card)
- [Interpretation Output Format](#interpretation-output-format)
- [Full Example: Apoe-Trem2 in Alzheimer Disease](#full-example-apoe-trem2-in-alzheimer-disease)

---

## Complete Tool API Reference

### search_literature_dynamic (PRIMARY)

`search_literature_dynamic` is the primary SEARCHER tool. SEARCHER should use the direct tool call. The shell wrapper is useful for manual reruns and debugging, but it is not the authoritative SEARCHER entrypoint.

**Preferred SEARCHER tool call**

```python
data_path = read_file("/data_path.txt").strip()

result = search_literature_dynamic(
    genes=search_context["genes"],
    pathways=search_context["pathways"],
    celltypes=search_context["celltypes"],
    disease="breast cancer",
    max_results=20,
    output_path="papers.json",
    data_dir=data_path,
    enable_lr_pair_queries=True,
)
```

Notes:
- `genes` may already include candidate genes added by `load_analysis_data`.
- `lr_pairs` support is activated through `enable_lr_pair_queries=True` for SEARCHER.
- When `output_path` is set, always pass `data_dir`.

**Manual shell wrapper**

```bash
python scripts/search_literature_dynamic.py \
  --genes "CDH1,TGFB1,VIM,ERBB2,MMP2" \
  --pathways "EMT,TGFB,WNT,Hypoxia" \
  --celltypes "Tumor,Fibroblast,Macrophages" \
  --disease "breast cancer" \
  --max-results 20 \
  --output-path "papers.json" \
  --data-dir "/path/to/results"
```

**Returns with `output_path`**
- `saved_to`
- `output_path`
- `total_papers`
- `coverage`
- `paper_titles`
- `search_method`
- `iterations`
- `coverage_sufficient`
- `recommended_actions`
- `filter_stage`
- `rerank_applied_count`
- `rerank_dropped_count`
- `message`

`coverage_sufficient` and `recommended_actions` are the operational fields SEARCHER uses for follow-up.

**Returns without `output_path`**
- `papers`
- `generated_queries`
- `coverage`
- `iterations`
- `coverage_history`
- `coverage_sufficient`
- `recommended_actions`
- rerank metadata

**Fallback behavior**

If LLM query generation fails, the tool automatically switches to a fixed internal strategy. No separate fallback call is needed.

### search_literature (Targeted Follow-up)

Use `search_literature` for structured follow-up when the primary search leaves missing genes, pathway context, or too little disease-specific evidence.

```python
search_literature(
    genes=["APOE", "TREM2"],
    disease="Alzheimer disease",
    keywords=["microglia", "neuroinflammation"],
    max_results=15,
)
```

```python
search_literature(
    genes=[],
    disease="breast cancer",
    keywords=["TGF-beta signaling", "fibroblast", "stromal"],
    max_results=10,
)
```

Use it when:
- `recommended_actions` identifies missing genes
- pathway coverage is weak and you need a focused keyword search
- the paper count is low and a broader disease-context follow-up is enough

### think_tool (Manual Reflection Aid)

`think_tool` is not part of the active SEARCHER toolset. SEARCHER should follow `coverage_sufficient` and `recommended_actions` directly.

The runtime payload may still include a legacy recommendation string mentioning `think_tool`. Treat that string as manual-only guidance rather than a SEARCHER step.

Use `think_tool` only when:
- you are manually reviewing the saved result outside SEARCHER
- the surrounding tool environment explicitly exposes `think_tool`
- you want an extra reflection pass before handing results to another stage

```python
think_tool(
    reflection="Coverage summary: gene coverage below target for SNAI1. "
               "Recommended follow-up is a focused gene search with EMT context.",
    iteration=1,
    max_iterations=1,
    score_threshold=0.7,
)
```

---

## Advanced PubMed E-utilities Patterns

Use `search_pubmed_advanced` when coverage gaps remain after direct follow-up or when you need exact PubMed syntax.

Typical reasons to use it:
- recent papers only
- publication-type filters
- MeSH terms
- field-specific query control
- proximity operators

Examples:

```python
search_pubmed_advanced(
    query="TGF-beta signaling[tiab] AND spatial transcriptomics[tiab]",
    max_results=10,
)
```

```python
search_pubmed_advanced(
    query="cell-cell interaction[tiab] AND systematic review[pt]",
    min_date="2023/01/01",
    max_results=10,
)
```

```python
search_pubmed_advanced(
    query="CDH1[tiab] AND E-cadherin[tiab] AND epithelial mesenchymal[mh]",
    min_date="2020/01/01",
    max_results=10,
)
```

```python
search_pubmed_advanced(
    query="(VEGFA[tiab] OR TGFB1[tiab]) AND neoplasms[mh] AND review[pt]",
    min_date="2022/01/01",
    max_results=10,
)
```

See `skills/pubmed-eutils-search/SKILL.md` for the broader E-utilities syntax reference.

---

## Part-Specific Search Focus

| Part | Primary Focus | Follow-up emphasis | Key Analyses |
|------|---------------|-------------------|--------------|
| Part 1 | Spatial organization and pathway context | Missing pathway or tissue-specific context | Spatial, neighborhood, decoupler, MISTy |
| Part 2 | Cell-cell interaction and NMF context | Ligand-receptor gaps and factor composition | LIANA Moran's R, NMF, pathway-factor, ctSVG |
| Part 3 | Detailed ligand-receptor mechanisms | Receptor-specific mechanism and disease anchoring | L-R visualization and summary |

---

## L-R Interaction Search Strategy

### Required Parameters
- `genes`: include both ligand and receptor when they are known
- `disease`: include disease context

### Recommended Keyword Combinations

| Analysis Tool | Additional Keywords |
|---------------|---------------------|
| LIANA+ | `LIANA`, `ligand receptor inference` |
| CellChat | `CellChat`, `cell communication` |
| CellPhoneDB | `CellPhoneDB`, `receptor ligand` |
| NicheNet | `NicheNet`, `ligand target` |

### Disease-Specific Keywords
- Alzheimer: `Alzheimer disease`, `neurodegeneration`, `dementia`
- Cancer: `neoplasms`, `tumor microenvironment`, `cancer`
- Inflammation: `inflammation`, `immune response`

### Search Examples

```python
search_literature_dynamic(
    genes=["APOE", "TREM2"],
    pathways=["TREM2 signaling", "microglial activation"],
    celltypes=["Microglia"],
    disease="Alzheimer disease",
    max_results=20,
    output_path="papers.json",
    data_dir=data_path,
    enable_lr_pair_queries=True,
)
```

```python
search_literature(
    genes=["SPP1", "CD44"],
    disease="breast cancer",
    keywords=["tumor microenvironment", "macrophage", "ECM remodeling"],
    max_results=10,
)
```

---

## Pathway Search Strategy

### Required Parameters
- `pathways`: pathway names from analysis
- `disease`: disease context

### Major Pathway Keywords

| Pathway | Recommended Search Terms |
|---------|--------------------------|
| WNT | `WNT pathway`, `WNT signaling`, `beta-catenin` |
| NFkB | `NFkB pathway`, `NF-kappa B`, `inflammatory signaling` |
| TNFa | `TNF signaling`, `TNF-alpha`, `TNFR` |
| TGFb | `TGF-beta signaling`, `SMAD`, `fibrosis` |
| JAK-STAT | `JAK STAT pathway`, `cytokine signaling` |
| PI3K-AKT | `PI3K AKT`, `mTOR signaling` |
| MAPK | `MAPK pathway`, `ERK signaling` |
| Hypoxia | `hypoxia`, `HIF-1`, `oxygen sensing` |
| EGFR | `EGFR signaling`, `ErbB`, `receptor tyrosine kinase` |
| VEGF | `VEGF signaling`, `angiogenesis`, `vascular` |

### Search Examples

```python
search_literature_dynamic(
    genes=[],
    pathways=["WNT", "TGFb", "Hypoxia"],
    celltypes=["Fibroblast", "Tumor"],
    disease="breast cancer",
    max_results=20,
    output_path="papers.json",
    data_dir=data_path,
    enable_lr_pair_queries=True,
)
```

```python
search_literature(
    genes=[],
    disease="breast cancer",
    keywords=["TGF-beta signaling", "fibroblast", "stroma"],
    max_results=10,
)
```

---

## Gene/Marker Search Strategy

### Required Parameters
- `genes`: SEARCHER-ready gene symbols from `search_context["genes"]`
- `celltypes`: associated cell types when available

### Context-Specific Keywords

| Context | Recommended Keywords |
|---------|----------------------|
| Spatial marker | `spatial transcriptomics`, `spatial distribution` |
| Cell type marker | `cell type`, `marker gene`, `single cell` |
| DEG | `differential expression`, `upregulated`, `downregulated` |
| Cluster marker | `cluster`, `subpopulation`, `heterogeneity` |
| EMT marker | `epithelial mesenchymal transition`, `E-cadherin`, `vimentin` |

### Search Examples

```python
search_literature_dynamic(
    genes=["GFAP", "AQP4", "SLC1A2"],
    pathways=[],
    celltypes=["Astrocyte"],
    disease="Alzheimer disease",
    max_results=20,
    output_path="papers.json",
    data_dir=data_path,
    enable_lr_pair_queries=True,
)
```

```python
search_literature(
    genes=["CDH1"],
    disease="breast cancer",
    keywords=["E-cadherin", "EMT", "epithelial"],
    max_results=10,
)
```

---

## Search Result Optimization

### `max_results` Settings
- 15 to 30: standard primary search
- 10: targeted follow-up search
- 30 to 40: broader literature sweep when paper count stays low

### When Results Are Scarce
1. Broaden the disease phrasing.
2. Remove overly specific cell types from the follow-up query.
3. Use `search_literature` with broader structured keywords.
4. Use `search_pubmed_advanced` when you know the exact PubMed phrasing you want.

### Coverage Targets
- At least 15 papers
- At least 60 percent gene coverage
- At least 50 percent pathway coverage
- Up to 2 SEARCHER follow-up rounds after the primary call

### Example Follow-Up Pattern

```python
if not result["coverage_sufficient"]:
    search_literature(
        genes=["MISSING_GENE"],
        disease="disease context",
        keywords=["pathway keyword", "cell type keyword"],
        max_results=10,
    )
```

---

## Quick Reference Card

### Tool Selection by Analysis Type

| Analysis Type | Primary Tool | Follow-up Tool | Key Parameters |
|---------------|--------------|----------------|----------------|
| L-R interaction | `search_literature_dynamic` | `search_literature` | `genes=[ligand, receptor]`, `disease`, `enable_lr_pair_queries=True` |
| Pathway | `search_literature_dynamic` | `search_literature` | `pathways=[...]`, `disease` |
| Gene markers | `search_literature_dynamic` | `search_literature` | `genes=[...]`, `celltypes=[...]` |
| Precision PubMed syntax | `search_pubmed_advanced` | none | `query=...`, date filters, MeSH filters |

### Follow-Up Flow

1. Run `search_literature_dynamic`.
2. Inspect `coverage_sufficient`.
3. If it is false, inspect `recommended_actions`.
4. Choose the smallest direct follow-up:
   - `search_literature` for structured gap filling
   - `search_pubmed_advanced` for exact PubMed syntax
5. Stop after the result is good enough or the follow-up limit is reached.

### Quality Thresholds

| Check | Target | Typical response if below target |
|-------|--------|----------------------------------|
| Total papers | At least 15 | Broaden disease scope or add supporting keywords |
| Gene coverage | At least 60 percent | Add gene aliases or targeted gene follow-up |
| Pathway coverage | At least 50 percent | Add pathway-specific keywords such as `signaling` |
| SEARCHER follow-up rounds | 2 | Proceed with warning if critical gaps remain |

### Phase-to-Tool Mapping

| Phase | Tool | Purpose | Output |
|-------|------|---------|--------|
| Phase 1 | `load_analysis_data` | Load SEARCHER-ready `search_context` | `/search_context.json` |
| Phase 2 | `search_literature_dynamic` | Run the primary search | `/papers.json` plus compact summary |
| Phase 3 | `search_literature` or `search_pubmed_advanced` | Targeted follow-up from `recommended_actions` | Updated evidence base |
| Phase 4 | auto-save via `output_path` | Persist full result for downstream stages | `/papers.json` |

### Common `recommended_actions` Patterns

| Pattern | Meaning | Typical follow-up |
|---------|---------|------------------|
| Missing genes listed | Symbol coverage is weak | `search_literature` with gene aliases and disease keywords |
| Missing pathways listed | Pathway context is weak | `search_literature` with pathway-specific keywords or `search_pubmed_advanced` |
| Too few papers | Breadth is weak | Broaden disease phrasing or increase `max_results` |

---

## Interpretation Output Format

Note: SEARCHER ends at `/papers.json`. The paragraph and reference formatting below are consumed by INTERPRETER and are kept here for end-to-end traceability.

### Interpretation Paragraph Template

```text
Our finding of [analysis result] is consistent with previous reports
demonstrating that [paper's key finding] (Author et al., Year; PMID: xxxxx).
Furthermore, [expand context] (Author2 et al., Year; PMID: xxxxx).
```

Writing principles:
- state the analysis result first
- connect it to supporting literature
- cite PMIDs from `/papers.json`
- include specific statistics from the analysis

### Reference List Format

```markdown
## References

1. Author et al. (Year) Title. Journal. PMID: xxxxx
   Relevance: [How this paper supports the finding]

2. Author et al. (Year) Title. Journal. PMID: xxxxx
   Relevance: [How this paper supports the finding]
```

---

## Full Example: Apoe-Trem2 in Alzheimer Disease

### Input
Found enriched Apoe-Trem2 interaction (LIANA score: 2.3, p=0.001) in microglia surrounding amyloid plaques in an Alzheimer disease mouse brain dataset.

### Phase 1: Extract Context
- Analysis type: L-R interaction
- Key genes: APOE, TREM2
- Cell types: Microglia
- Disease: Alzheimer disease

### Phase 2: Run Primary Search

```python
result = search_literature_dynamic(
    genes=["APOE", "TREM2"],
    pathways=["TREM2 signaling", "microglial activation"],
    celltypes=["Microglia"],
    disease="Alzheimer disease",
    max_results=20,
    output_path="papers.json",
    data_dir=data_path,
    enable_lr_pair_queries=True,
)
```

Expected compact summary shape:

```python
{
    "saved_to": "/path/to/papers.json",
    "total_papers": 28,
    "coverage_sufficient": True,
    "recommended_actions": [],
}
```

### Phase 3: Inspect Coverage and Decide
- Papers found: 28
- Genes covered: APOE and TREM2
- Pathway coverage reached the threshold
- `coverage_sufficient` is `True`, so no direct SEARCHER follow-up is needed

### Phase 4: Use Saved Output

The full result is already saved to `/papers.json`. Downstream stages can read that file directly without asking SEARCHER to rewrite it.

### Generated Interpretation by INTERPRETER

Our finding of enriched Apoe-Trem2 interaction (LIANA score: 2.3, p=0.001) in plaque-associated microglia is consistent with reports that the TREM2-APOE pathway drives the transcriptional phenotype of disease-associated microglia (Krasemann et al., 2017; PMID: 28930663). This interaction has also been linked to microglial response to amyloid pathology (Zhou et al., 2020; PMID: 31932797).
