---
name: biomedical-literature-search
description: SEARCHER-facing PubMed literature workflow for Deep Interpreter CCI and spatial transcriptomics analysis. Use whenever the SEARCHER subagent needs ligand-receptor, pathway, marker, or disease-context evidence and must save a grounded `/papers.json`. Make sure to use this skill for ST/CCI literature passes, especially when pathway or celltype context may need bundled follow-up beyond `coverage_sufficient`. Use `search_literature_dynamic` first, then inspect `coverage`, `recommended_actions`, and missing pathway or celltype signals before stopping. Use `search_literature` for bundled targeted follow-up and `search_pubmed_advanced` for precision fallback.
metadata:
  author: Junghyun Jung
  version: 1.3.0
---

# Biomedical Literature Search Strategy

SEARCHER-facing literature-search workflow for interpreting ST and CCI analysis results and producing a single grounded paper set for downstream interpretation.

## Purpose

This skill defines the SEARCHER subagent's core workflow:
- **WHEN** to search: before interpretation, after `load_analysis_data` prepares context
- **WHAT** to search: ligand-receptor biology, pathway context, marker evidence, disease anchoring, and celltype-aware microenvironment context
- **HOW** to follow up: run a bundled multi-axis check over papers, genes, pathways, and celltypes instead of trusting `coverage_sufficient` alone
- **WHERE** to write outputs: unified `/papers.json` shared by downstream readers

Progressive disclosure: keep the active SEARCHER contract here, use `references/search_strategies.md` for fuller search patterns, `references/use_cases.md` for concrete triggers, `evals/evals.json` for test prompts, and `evals/manual-test-notes.md` for validation evidence.

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
| `genes` | Search-ready genes. This list may already include candidate genes and should be used as-is. |
| `all_genes` | Full unique gene set for reference only. Do not substitute this for `genes`. |
| `candidate_genes` | Optional novel genes added from prioritized pair context. |
| `lr_pairs` | Optional top ligand-receptor pairs for SEARCHER-only pair query injection. |
| `pathways` | Pathway names from upstream analysis. May be empty. |
| `celltypes` | Cell type names from upstream analysis. May be empty. |
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
If bundled follow-up still leaves important gaps, use:
- `search_literature` for structured gene, pathway, and celltype follow-up
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

Treat `coverage_sufficient` and `recommended_actions` as useful hints, not as the sole stop condition. Rev6 SEARCHER follow-up must inspect the `coverage` object directly.

---

## Phase 3: Multi-Axis Follow-Up

For SEARCHER, `coverage_sufficient` and `recommended_actions` are reference signals. The actual stop decision must inspect papers, genes, pathways, and celltypes together.

### Active Coverage Targets

| Criterion | Target | Role | When It Applies |
|-----------|--------|------|-----------------|
| Total papers | At least 15 | Active driver | Always |
| Gene coverage | At least 60 percent | Guardrail | Always |
| Pathway coverage | At least 50 percent | Active driver | Only when `search_context["pathways"]` is non-empty |
| Celltype coverage | At least 60 percent | Active driver | Only when `search_context["celltypes"]` is non-empty |
| Bundled follow-up rounds | Maximum 2 | Hard cap | Always |

### Decision Rules

1. Run `search_literature_dynamic` first.
2. Read `coverage`, `coverage_sufficient`, and `recommended_actions`.
3. Determine whether pathway context exists and whether celltype context exists.
4. Do **not** treat absent-pathway cases as pathway failures. If `search_context["pathways"]` is empty, pathway is informational only.
5. If any of these are true, run bundled follow-up round 1:
   - `coverage["total_papers"] < 15`
   - `coverage["genes_coverage_pct"] < 60`
   - pathway context exists and `coverage["pathways_coverage_pct"] < 50`
   - celltype context exists and `coverage["celltypes_coverage_pct"] < 60`
6. A bundled follow-up round should combine missing pathway and missing celltype work in one pass. Add gene-synonym follow-up only if the gene guardrail is below 60 percent.
7. Re-run `search_literature_dynamic` at most once, and only when:
   - `coverage["total_papers"] < 15`, or
   - after bundled round 1, both active drivers remain below target
8. Stop after two bundled follow-up rounds. If important gaps remain, proceed with a warning rather than widening the workflow indefinitely.

### Bundled Follow-Up Pattern

Use `search_literature` to combine the weak axes into one structured follow-up:

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

Use `search_pubmed_advanced` when you know the exact phrasing you want:

```python
search_pubmed_advanced(
    query="VEGF signaling[tiab] AND endothelial[tiab] AND breast cancer[tiab]",
    max_results=10,
)
```

### `think_tool` Clarification

The runtime payload may still include a legacy recommendation string mentioning `think_tool`. SEARCHER should treat that string as manual-only guidance, not as a required SEARCHER step, because the active SEARCHER toolset does not include `think_tool`.

If you are working outside SEARCHER and explicitly have access to `think_tool`, you may use it as an optional reflection aid while reviewing unresolved gaps. Do not model Rev6 SEARCHER follow-up as a `think_tool` loop.

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
    "pathways_missing": [],
    "pathways_coverage_pct": 100,
    "celltypes_covered": ["Tumor", "Fibroblast"],
    "celltypes_missing": ["Macrophages"],
    "celltypes_coverage_pct": 66.7,
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

Use the saved `coverage` object, not only the top-level summary text, when deciding whether Rev6 follow-up is complete.

---

## Common Mistakes to Avoid

### Avoid
- Do not read raw `.csv` files with `read_file`.
- Do not replace `search_context["genes"]` with `all_genes`.
- Do not treat the shell wrapper as the authoritative SEARCHER path.
- Do not omit `data_dir` when using `output_path`.
- Do not call `write_file` for papers after the dynamic search already auto-saved them.
- Do not stop only because `coverage_sufficient` is `True`.
- Do not ignore `coverage["celltypes_coverage_pct"]` or `coverage["celltypes_missing"]` when celltype context exists.
- Do not treat absent-pathway cases as pathway failures.
- Do not treat the legacy `think_tool` recommendation string as a required SEARCHER action.

### Do Instead
- Use `search_context` directly from `load_analysis_data`.
- Treat `search_context["genes"]` as the SEARCHER-ready gene list, even when it already includes candidate genes.
- Use `search_literature_dynamic` first, then inspect `coverage`, `coverage_sufficient`, and `recommended_actions`.
- Use bundled `search_literature` follow-up before escalating to a dynamic rerun.
- Use `search_pubmed_advanced` for exact PubMed phrasing after bundled follow-up still leaves important gaps.
- Keep a single unified `/papers.json` for the SEARCHER output set.

---

## Examples

### Example 1: Bundled Rev6 Follow-Up

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
            "endothelial cells",
            "stromal cells",
            "tumor microenvironment",
        ],
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

## Common Issues

### No Papers After Disease Filtering
If the search returns almost no papers:
1. Check whether the disease term is too narrow.
2. Retry with a broader disease phrase or disable strict disease filtering.
3. Record the fallback in your notes so downstream readers know the result was broadened.

### High Gene Coverage But Weak Pathway Or Celltype Coverage
If genes are fine but pathway or celltype coverage is weak:
1. Read `coverage["pathways_missing"]` and `coverage["celltypes_missing"]`.
2. Run one bundled follow-up that combines pathway keywords such as `signaling` with the missing celltype and disease context.
3. Only escalate to a dynamic rerun if bundle 1 still leaves both active drivers below target.

### Auto-Save Was Skipped
If `output_path` did not create `/papers.json`:
1. Confirm that `data_dir` came from `read_file("/data_path.txt").strip()`.
2. Re-run with the same `output_path` and an explicit `data_dir`.
3. Do not manually patch the file with `write_file`; let the tool save it.

### Legacy `think_tool` Guidance Appears
If the result text mentions `think_tool`:
1. Treat it as legacy manual-only advice.
2. Do not add a `think_tool` step to SEARCHER.
3. Continue with the Rev6 bundled follow-up rules instead.

### Results Look Generic Rather Than Context-Rich
If the paper set looks gene-centric or generic:
- **Cause:** The first pass likely satisfied gene coverage without expanding pathway or celltype context.
- **Solution:** Run a bundled follow-up that explicitly adds missing pathway and celltype keywords.
- **Prevention:** Do not stop on `coverage_sufficient` alone when pathway or celltype context exists.

---

## Where to Find More

- **Use cases and trigger examples**: `references/use_cases.md`
- **Prompt test set**: `evals/evals.json`
- **Validation and manual audit notes**: `evals/manual-test-notes.md`
- **Full tool API, return fields, and rerank options**: `references/search_strategies.md` section `Complete Tool API Reference`
- **Advanced PubMed E-utilities patterns**: `references/search_strategies.md` section `Advanced PubMed E-utilities Patterns`
- **Part-specific search focus**: `references/search_strategies.md` section `Part-Specific Search Focus`
- **Analysis-type mapping and follow-up flow**: `references/search_strategies.md` section `Quick Reference Card`
- **Interpretation paragraph and reference list format used downstream**: `references/search_strategies.md` section `Interpretation Output Format`
- **PubMed E-utilities full syntax**: `skills/pubmed-eutils-search/SKILL.md`
