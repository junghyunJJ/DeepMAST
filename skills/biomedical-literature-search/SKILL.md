---
name: biomedical-literature-search
description: SEARCHER-facing PubMed literature search workflow for Deep Interpreter
  CCI and spatial transcriptomics analysis. Use when the SEARCHER subagent
  needs ligand-receptor, pathway, marker, or disease-context evidence, must
  save unified results to `/papers.json`, and must drive follow-up from
  `coverage_sufficient` plus `recommended_actions` using thresholds of at least
  15 papers, 60 percent gene coverage, and 50 percent pathway coverage.
  Treat `search_literature_dynamic` as the primary tool, `search_literature`
  as targeted follow-up, and `search_pubmed_advanced` as precision fallback.
metadata:
  author: Junghyun Jung
  version: 1.2.0
---

# Biomedical Literature Search Strategy

SEARCHER-facing literature search workflow for interpreting ST and CCI analysis results and producing a single grounded paper set for downstream interpretation.

## Purpose

This skill defines the SEARCHER subagent's core workflow:
- **WHEN** to search: before interpretation, after `load_analysis_data` prepares context
- **WHAT** to search: ligand-receptor biology, pathway context, marker evidence, and disease anchoring
- **HOW** to follow up: inspect `coverage_sufficient` and `recommended_actions`, then run direct follow-up searches only when needed
- **WHERE** to write outputs: unified `/papers.json` shared by downstream readers

Progressive disclosure: this file keeps the SEARCHER workflow compact. Detailed tool API, E-utilities patterns, part-specific search focus, quick reference cards, interpretation output format, and a worked example live in `references/search_strategies.md`.

## Manual Script Entry Point

The shell wrapper is for manual reruns, smoke tests, and debugging outside the SEARCHER subagent. It is not the authoritative SEARCHER workflow.

```bash
python scripts/search_literature_dynamic.py \
  --genes "CDH1,TGFB1,VIM" \
  --pathways "EMT,TGFb,Hypoxia" \
  --celltypes "Tumor,Fibroblast,Macrophages" \
  --disease "breast cancer" \
  --max-results 30 \
  --output-path "papers.json" \
  --data-dir "/path/to/results"
```

The wrapper calls `src/agents/deep_interpreter/tools/literature.py::search_literature_dynamic` and prints JSON output. SEARCHER-specific options such as `enable_lr_pair_queries` are available through the tool call, not this wrapper.

## Virtual Filesystem Contract

| File | Phase | Content |
|------|-------|---------|
| `/data_path.txt` | Read | Real data directory path, pre-written by the orchestrator |
| `/search_context.json` | Phase 1 | Unified search context saved for traceability |
| `/papers.json` | Phase 2 and Phase 4 | Auto-saved literature results shared across parts |

---

## Phase 1: Extract Context

### Step 1.1: Load Data Path
Read `read_file("/data_path.txt")` and keep the stripped path for every later call that uses `output_path`.

### Step 1.2: Load Analysis Data
Call `load_analysis_data` with the exact path from `/data_path.txt`. Do not parse raw CSV files manually.

### Step 1.3: Use `search_context` Directly

`load_analysis_data` returns a SEARCHER-ready `search_context` payload. Key fields include:

| Field | Contains |
|-------|----------|
| `genes` | Search-ready genes. This list may already include novel candidate genes and should be used as-is. |
| `all_genes` | Full unique gene set for reference only. Do not substitute this for `genes`. |
| `candidate_genes` | Optional novel genes added from prioritized pair context. |
| `lr_pairs` | Optional top ligand-receptor pairs for SEARCHER-only pair query injection. |
| `pathways` | Pathway names from upstream analysis. |
| `celltypes` | Cell type names from upstream analysis. |
| `context_type` | Context classification such as `lr_interaction`, `pathway`, or `marker`. |
| `applicable_parts` | Parts that this context supports. |
| `stats` | Summary counts including search genes, pathways, cell types, and optional search pairs. |

### Step 1.4: Write Context File
Write the extracted context to `/search_context.json` for downstream inspection.

---

## Phase 2: Search Literature

### Step 2.1: Run the Primary SEARCHER Tool

SEARCHER should use the direct tool call, not the shell wrapper, as its primary path:

```python
data_path = read_file("/data_path.txt").strip()

result = search_literature_dynamic(
    genes=search_context["genes"],
    pathways=search_context["pathways"],
    celltypes=search_context["celltypes"],
    disease="breast cancer",
    output_path="papers.json",
    data_dir=data_path,
    enable_lr_pair_queries=True,
)
```

Important SEARCHER rules:
- Always pass `output_path="papers.json"` so the full result is saved without truncation.
- Always pass `data_dir` from `/data_path.txt` when using `output_path`.
- `enable_lr_pair_queries=True` is SEARCHER-only. It allows the tool to use saved pair context when available.
- SEARCHER does not need to set `coverage_weighted_sort` manually. The tool handles the SEARCHER-specific behavior internally when pair queries are enabled.

### Step 2.2: Automatic Internal Fallback
`search_literature_dynamic` handles fallback internally. If LLM query generation fails, it automatically switches to a fixed search strategy. Do not call a separate fallback tool.

### Step 2.3: Precision Gap Filling
If follow-up gaps remain after reviewing `recommended_actions`, use:
- `search_literature` for targeted gene or pathway follow-up with the real structured signature
- `search_pubmed_advanced` when you need exact PubMed syntax, MeSH filters, date filters, or publication-type filters

### Step 2.4: Tool Returns
When `output_path` is set, the compact summary includes:
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
- rerank counters
- `message`

`coverage_sufficient` and `recommended_actions` are the fields SEARCHER uses to decide whether follow-up is needed.

---

## Phase 3: Coverage-Driven Follow-Up

For SEARCHER, `coverage_sufficient` and `recommended_actions` are authoritative. Follow-up is coverage-driven, not a separate mandatory reflection phase.

### Coverage Targets

| Criterion | Target | Typical response if below target |
|-----------|--------|----------------------------------|
| Total papers | At least 15 unique papers | Broaden disease context or add broader supporting keywords |
| Gene coverage | At least 60 percent of priority genes | Run targeted gene follow-up with synonyms or related context keywords |
| Pathway coverage | At least 50 percent of priority pathways | Add pathway-specific keywords such as `signaling` plus disease context |
| SEARCHER follow-up rounds | Up to 2 direct follow-up rounds | Proceed with a warning if important gaps remain after the limit |

### Follow-up Logic

1. Inspect `coverage_sufficient`.
2. If it is `True`, proceed without additional SEARCHER follow-up.
3. If it is `False`, inspect `recommended_actions` and execute the smallest targeted follow-up needed.
4. Re-run or supplement the search only until the missing coverage is reasonably addressed.

### Targeted Follow-up Examples

Use `search_literature` for structured gap filling:

```python
search_literature(
    genes=["SNAI1"],
    disease="breast cancer",
    keywords=["EMT", "spatial transcriptomics", "E-cadherin"],
    max_results=10,
)
```

Use `search_pubmed_advanced` when you need precise PubMed syntax:

```python
search_pubmed_advanced(
    query="TGF-beta signaling[tiab] AND breast cancer[tiab] AND review[pt]",
    max_results=10,
)
```

### `think_tool` Clarification

The runtime payload may still include a legacy recommendation string mentioning `think_tool`. SEARCHER should treat that string as manual-only guidance, not as a required SEARCHER step, because the active SEARCHER toolset does not include `think_tool`.

If you are working outside SEARCHER and explicitly have access to `think_tool`, you may use it as an optional reflection aid while reviewing unresolved gaps. Do not model Phase 3 as a mandatory `think_tool` loop.

---

## Phase 4: Output

### Auto-Saved Papers
When `search_literature_dynamic` runs with `output_path`, the tool writes the full result to `data_dir/output_path`. Do not call `write_file` for papers.

Use `read_file("/papers.json")` only if you need to inspect the saved result after the primary call.

### Saved File Shape

The saved file contains the full result, not the compact summary. Expect fields such as:

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
  "generated_queries": [
    {
      "query": "CDH1 EMT breast cancer",
      "source": "llm"
    }
  ],
  "coverage": {
    "genes_covered": ["CDH1", "TGFB1", "VIM"],
    "genes_missing": ["SNAI1"],
    "genes_coverage_pct": 75,
    "pathways_covered": ["EMT", "TGFB"],
    "pathways_coverage_pct": 100,
    "total_papers": 28
  },
  "iterations": 2,
  "coverage_history": [
    {
      "iteration": 0,
      "papers": 20
    }
  ],
  "coverage_sufficient": true,
  "recommended_actions": []
}
```

---

## Common Mistakes to Avoid

### Avoid
- Do not read raw `.csv` files with `read_file`.
- Do not replace `search_context["genes"]` with `all_genes`.
- Do not treat the shell wrapper as the authoritative SEARCHER path.
- Do not omit `data_dir` when using `output_path`.
- Do not call `write_file` for papers after the dynamic search already auto-saved them.
- Do not treat the legacy `think_tool` recommendation string as a required SEARCHER action.

### Do Instead
- Use `search_context` directly from `load_analysis_data`.
- Treat `search_context["genes"]` as the SEARCHER-ready gene list, even when it already includes candidate genes.
- Use `search_literature_dynamic` first, then inspect `coverage_sufficient` and `recommended_actions`.
- Use `search_literature` for structured targeted follow-up.
- Use `search_pubmed_advanced` for precise PubMed syntax and filters.
- Keep a single unified `/papers.json` for the SEARCHER output set.

---

## Examples

### Example 1: SEARCHER Follow-Up Using `recommended_actions`

```python
data_path = read_file("/data_path.txt").strip()

result = search_literature_dynamic(
    genes=search_context["genes"],
    pathways=search_context["pathways"],
    celltypes=search_context["celltypes"],
    disease="breast cancer",
    output_path="papers.json",
    data_dir=data_path,
    enable_lr_pair_queries=True,
)

if not result["coverage_sufficient"]:
    search_literature(
        genes=["SNAI1"],
        disease="breast cancer",
        keywords=["EMT", "E-cadherin"],
        max_results=10,
    )
```

### Example 2: Manual Shell Rerun

```bash
python scripts/search_literature_dynamic.py \
  --genes "APOE,TREM2" \
  --pathways "TREM2 signaling,microglial activation" \
  --celltypes "Microglia" \
  --disease "Alzheimer disease" \
  --max-results 10 \
  --output-path "papers.json" \
  --data-dir "/tmp/literature-smoke"
```

---

## Troubleshooting

### Error: 0 papers returned after disease filter
**Cause**: `enforce_disease_match=True` filtered out everything because the disease string was too specific.
**Solution**: Retry with `--no-enforce-disease-match` in the wrapper or `enforce_disease_match=False` in the tool call. You can also broaden the disease term.

### Error: Gene coverage remains low after SEARCHER follow-up
**Cause**: The initial search was too narrow, or the missing gene is usually described with aliases rather than the symbol.
**Solution**: Run `search_literature` with structured `genes`, `disease`, and `keywords` arguments. For example, search `genes=["CDH1"]` with keywords such as `"E-cadherin"` and `"EMT"`. Limit SEARCHER to two direct follow-up rounds, then proceed with a warning if the gap remains.

### Error: `load_analysis_data` returned empty `search_context`
**Cause**: `/data_path.txt` points at the wrong directory, or required result files are missing.
**Solution**: Verify `/data_path.txt`, then confirm the expected analysis files exist in that directory before rerunning SEARCHER.

### Error: Auto-save was skipped
**Cause**: `output_path` was set but `data_dir` was missing, so the tool could not resolve the real save path.
**Solution**: Always pass `data_dir=read_file("/data_path.txt").strip()` when using `output_path`.

### Error: Results look weakly anchored to the disease context
**Cause**: The query mix stayed too generic, or reranking was left off for a noisy context.
**Solution**: Supply more specific pathway or cell type context, or enable LLM reranking with `rerank_mode="llm"` and the matching rerank thresholds.

---

## Where to Find More

- **Full tool API, return fields, and rerank options**: `references/search_strategies.md` section `Complete Tool API Reference`
- **Advanced PubMed E-utilities patterns**: `references/search_strategies.md` section `Advanced PubMed E-utilities Patterns`
- **Part 1, Part 2, and Part 3 search focus**: `references/search_strategies.md` section `Part-Specific Search Focus`
- **Analysis-type mapping, follow-up flow, and quality thresholds**: `references/search_strategies.md` section `Quick Reference Card`
- **Interpretation paragraph and reference list format used downstream**: `references/search_strategies.md` section `Interpretation Output Format`
- **Full worked example**: `references/search_strategies.md` section `Full Example: Apoe-Trem2 in Alzheimer Disease`
- **L-R interaction keyword combinations**: `references/search_strategies.md` section `L-R Interaction Search Strategy`
- **Pathway keyword combinations**: `references/search_strategies.md` section `Pathway Search Strategy`
- **Gene and marker keyword combinations**: `references/search_strategies.md` section `Gene/Marker Search Strategy`
- **PubMed E-utilities full syntax**: `skills/pubmed-eutils-search/SKILL.md`
