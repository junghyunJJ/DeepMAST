# Search Strategies Reference

Detailed search strategies, tool API, and examples for the `biomedical-literature-search` skill.

Note: this reference expands the Rev6 SEARCHER workflow in `SKILL.md`. The active SEARCHER contract is multi-axis: extract context, run the primary search, inspect `coverage`, treat `coverage_sufficient` and `recommended_actions` as reference signals, then bundle pathway and celltype follow-up when the active drivers are still weak.

## Table of Contents

- [Complete Tool API Reference](#complete-tool-api-reference)
- [Rev6 Follow-Up Policy](#rev6-follow-up-policy)
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
- The compact summary is only the first layer. Rev6 follow-up must inspect the nested `coverage` object directly.
- SEARCHER pathway fan-out uses controlled pathway labels/aliases with `genes=[]`; pathway query stamps are provenance only and require title/abstract pathway text before coverage is credited.
- `query_type="pathway"` is reserved for deterministic pathway fan-out. Other no-gene searches are generic keyword retrieval (`query_type="keyword"`).

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

`coverage_sufficient` and `recommended_actions` are operational hints, not the only follow-up gate.

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

### search_literature (Bundled Follow-up)

Use `search_literature` for structured follow-up when the primary search leaves missing pathway or celltype context, weak disease anchoring, or low paper count.

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
    genes=["COL1A2"],
    disease="breast cancer",
    keywords=["VEGF signaling", "endothelial cells", "tumor microenvironment"],
    max_results=10,
)
```

Use it when:
- pathway coverage is weak and pathway context exists
- celltype coverage is weak and celltype context exists
- the paper count is low and a broader disease-context follow-up is enough
- gene coverage is below the guardrail and gene aliases need one targeted pass

### think_tool (Manual-Only Legacy Aid)

`think_tool` is not part of the active SEARCHER toolset. SEARCHER should follow the Rev6 bundled follow-up rules rather than trying to add a reflection loop.

The runtime payload may still include a legacy recommendation string mentioning `think_tool`. Treat that string as manual-only guidance rather than a SEARCHER step.

Use `think_tool` only when:
- you are manually reviewing the saved result outside SEARCHER
- the surrounding tool environment explicitly exposes `think_tool`
- you want an extra reflection pass before handing results to another stage

```python
think_tool(
    reflection="Coverage summary: pathway context is still weak after bundle 1. "
               "Manual reviewer wants an extra reflection pass before escalating.",
    iteration=1,
    max_iterations=1,
    score_threshold=0.7,
)
```

---

## Rev6 Follow-Up Policy

Rev6 SEARCHER completion is based on multiple axes, not only on `coverage_sufficient`.

### Active Drivers

| Axis | Target | Role | Applies When |
|------|--------|------|--------------|
| Papers | `>=15` | Active driver | Always |
| Gene | `>=60%` | Guardrail | Always |
| Pathway | `>=50%` | Active driver | Only when `search_context["pathways"]` is non-empty |
| Celltype | `>=60%` | Active driver | Only when `search_context["celltypes"]` is non-empty |

### Rev6 Decision Rules

1. Run `search_literature_dynamic` first.
2. Inspect `coverage`, `coverage_sufficient`, and `recommended_actions`.
3. Determine which active axes exist for this case.
4. If papers are low or any active axis is below target, run bundled follow-up round 1.
5. Bundle pathway and celltype signals together in one follow-up pass. Add gene aliases only if gene coverage is below 60 percent.
6. Re-run `search_literature_dynamic` at most once, and only when papers stay below 15 or both active drivers remain weak after bundle 1.
7. Stop after two bundled follow-up rounds. Carry forward a warning if important gaps remain.

### Rev6 Bundled Follow-Up Example

```python
coverage = result["coverage"]
has_pathways = bool(search_context["pathways"])
has_celltypes = bool(search_context["celltypes"])

needs_bundle = (
    coverage["total_papers"] < 15
    or coverage["genes_coverage_pct"] < 60
    or (has_pathways and coverage["pathways_coverage_pct"] < 50)
    or (has_celltypes and coverage["celltypes_coverage_pct"] < 60)
)

if needs_bundle:
    search_literature(
        genes=coverage["genes_missing"][:3] or search_context["genes"][:2],
        disease="breast cancer",
        keywords=[
            "VEGF signaling",
            "angiogenesis",
            "endothelial cells",
            "stromal cells",
            "tumor microenvironment",
            "spatial transcriptomics",
        ],
        max_results=10,
    )
```

Absent-pathway cases are not pathway failures. If the case has no pathway context, pathway is informational only.

---

## Advanced PubMed E-utilities Patterns

Use `search_pubmed_advanced` when bundled follow-up still leaves important gaps or when you need exact PubMed syntax.

Typical reasons to use it:
- recent papers only
- publication-type filters
- MeSH terms
- field-specific query control
- exact pathway wording
- exact celltype wording

Examples:

```python
search_pubmed_advanced(
    query="TGF-beta signaling[tiab] AND spatial transcriptomics[tiab]",
    max_results=10,
)
```

```python
search_pubmed_advanced(
    query="VEGF signaling[tiab] AND endothelial[tiab] AND breast cancer[tiab]",
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
    keywords=["cell-cell interaction", "tumor microenvironment", "stromal cells"],
    max_results=10,
)
```

---

## Pathway Search Strategy

### Required Parameters
- `pathways`: pathway names from analysis
- `disease`: disease context
- `celltypes`: associated cell types when available

### Controlled Pathway Rephrasings

| Input | Useful Follow-up Terms |
|------|-------------------------|
| WNT | `Wnt signaling pathway`, `WNT beta-catenin signaling`, `canonical WNT` |
| NFkB | `NF-kappa B signaling pathway`, `NF-kB`, `nuclear factor kappa B` |
| TGFb | `TGF-beta signaling pathway`, `TGF-beta`, `SMAD signaling` |
| Hypoxia | `HIF-1 signaling pathway`, `hypoxia inducible factor`, `cellular response to hypoxia` |
| MAPK | `MAPK signaling pathway`, `ERK signaling`, `RAS/MAPK` |

### Pattern

When pathway context is weak, combine:
- controlled pathway labels/aliases
- disease context
- one or two missing celltypes

```python
search_literature(
    genes=[],
    disease="breast cancer",
    keywords=["VEGF signaling", "angiogenesis", "endothelial cells", "stromal cells"],
    max_results=10,
)
```

For pathway follow-up, keep `genes=[]` unless the user explicitly asks for a
gene-specific search. A pathway paper should be retained as pathway evidence
only when the title/abstract contains both disease context and pathway text.

---

## Gene/Marker Search Strategy

### Required Parameters
- `genes`: search genes from `search_context`
- `celltypes`: associated cell types when available
- `disease`: disease context

### Pattern

Gene follow-up is a guardrail pass, not the main optimization target. Only do it when gene coverage is below 60 percent.

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
- 10: targeted bundled follow-up search
- 30 to 40: broader literature sweep when paper count stays low

### When Results Are Scarce
1. Broaden the disease phrasing.
2. Remove overly specific terms from the bundled keyword list.
3. Use `search_literature` with broader structured keywords.
4. Use `search_pubmed_advanced` when exact PubMed phrasing is known.

### Coverage Targets
- At least 15 papers
- At least 60 percent gene coverage
- At least 50 percent pathway coverage when pathway context exists
- At least 60 percent celltype coverage when celltype context exists
- Up to 2 bundled SEARCHER follow-up rounds

### Example Follow-Up Pattern

```python
if (
    result["coverage"]["total_papers"] < 15
    or result["coverage"]["genes_coverage_pct"] < 60
    or result["coverage"]["celltypes_coverage_pct"] < 60
):
    search_literature(
        genes=result["coverage"]["genes_missing"][:3],
        disease="disease context",
        keywords=["pathway keyword", "celltype keyword", "microenvironment keyword"],
        max_results=10,
    )
```

---

## Quick Reference Card

### Tool Selection by Analysis Type

| Analysis Type | Primary Tool | Follow-up Tool | Key Parameters |
|---------------|--------------|----------------|----------------|
| L-R interaction | `search_literature_dynamic` | `search_literature` | `genes=[ligand, receptor]`, `disease`, `enable_lr_pair_queries=True` |
| Pathway | `search_literature_dynamic` | `search_literature` or `search_pubmed_advanced` | `pathways=[...]`, `disease`, `celltypes=[...]` |
| Gene markers | `search_literature_dynamic` | `search_literature` | `genes=[...]`, `celltypes=[...]` |
| Precision PubMed syntax | `search_pubmed_advanced` | none | `query=...`, date filters, MeSH filters |

### Rev6 Follow-Up Flow

1. Run `search_literature_dynamic`.
2. Inspect `coverage`, `coverage_sufficient`, and `recommended_actions`.
3. Decide which active axes apply to this case.
4. If papers are low or any active axis is weak, run bundled follow-up:
   - `search_literature` for structured gap filling
   - `search_pubmed_advanced` for exact PubMed phrasing
5. Re-run `search_literature_dynamic` only under the bounded Rev6 rerun rule.
6. Stop after two bundled rounds or when the active targets are good enough.

### Quality Thresholds

| Check | Target | Notes |
|-------|--------|-------|
| Total papers | At least 15 | Always active |
| Gene coverage | At least 60 percent | Guardrail only |
| Pathway coverage | At least 50 percent | Only when pathway context exists |
| Celltype coverage | At least 60 percent | Only when celltype context exists |
| SEARCHER follow-up rounds | 2 | Hard cap |

### Common `recommended_actions` Patterns

| Pattern | Meaning | Typical follow-up |
|---------|---------|------------------|
| Missing genes listed | Symbol coverage is weak | `search_literature` with gene aliases and disease keywords |
| Missing pathways listed | Pathway context is weak | bundled `search_literature` with pathway and celltype keywords |
| Celltype coverage is weak | Context-rich papers are missing | bundled `search_literature` with celltype and microenvironment keywords |
| Too few papers | Breadth is weak | Broaden disease phrasing or bounded rerun |

---

## Interpretation Output Format

Note: SEARCHER ends at `/papers.json`. The paragraph and reference formatting below are consumed by INTERPRETER and are kept here for end-to-end traceability.

### Interpretation Paragraph Template

```text
Our finding of [analysis result] is consistent with previous reports
demonstrating that [paper's key finding] (Author et al., Year; PMID: xxxxx).
Furthermore, [expand context] (Author2 et al., Year; PMID: xxxxx).
```

---

## Full Example: Apoe-Trem2 in Alzheimer Disease

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

Expected interpretation:
- if pathway and celltype coverage are good, stop after the primary pass
- if either is weak, run one bundled follow-up with microglia and pathway keywords
- only escalate to exact PubMed syntax if the bundled pass still leaves important gaps

Example summary:

```python
{
  "coverage_sufficient": True,
  "recommended_actions": [],
  "coverage": {
    "genes_coverage_pct": 100,
    "pathways_coverage_pct": 100,
    "celltypes_coverage_pct": 100,
    "total_papers": 20
  }
}
```

When this happens:
- the active drivers are satisfied
- no bundled follow-up is needed
- `/papers.json` is ready for downstream interpretation
