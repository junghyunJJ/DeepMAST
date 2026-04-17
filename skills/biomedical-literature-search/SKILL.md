---
name: biomedical-literature-search
description: Complete 4-phase PubMed literature search workflow for cell-cell interaction (CCI) and spatial transcriptomics interpretation. Use when the SEARCHER subagent needs to find papers supporting ligand-receptor interactions, pathway enrichment, gene/marker expression, or disease-context evidence with coverage checks (>=25 papers, >=60% gene coverage, >=50% pathway coverage). Orchestrates `search_literature_dynamic` (primary, LLM-powered, auto-fallback to fixed-strategy) and `search_literature` for targeted follow-up, auto-saving results to `/papers.json`.
metadata:
  author: DeepMAST Deep Interpreter
  version: 1.1.0
---

# Biomedical Literature Search Strategy

Complete 4-phase literature search workflow for interpreting ST/CCI analysis results and generating publication-style output with supporting references.

## Purpose

This skill defines the SEARCHER subagent's core workflow:
- **WHEN** to search (timing by interpretation phase)
- **WHAT** to search (priority by analysis type)
- **HOW** to validate (quality criteria)
- **WHERE** to write outputs (virtual filesystem)

> **Progressive disclosure**: This file contains only the core 4-phase workflow and critical rules. Detailed tool API, advanced E-utilities patterns, part-specific focus, quick reference card, interpretation output format, and a full worked example all live in `references/search_strategies.md`. Read that file on demand.

## Script Entry Point

Run the primary wrapper from the skill directory:

```bash
python scripts/search_literature_dynamic.py \
  --genes "CDH1,TGFB1,VIM" \
  --pathways "EMT,TGFb,Hypoxia" \
  --celltypes "Tumor,Fibroblast,Macrophages" \
  --disease "breast cancer" \
  --max-results 30 \
  --output-path "papers.json"
```

The wrapper calls `src/agents/deep_interpreter/tools/literature.py::search_literature_dynamic` and prints JSON output.

## Virtual Filesystem Contract

| File | Phase | Content |
|------|-------|---------|
| `/data_path.txt` | Read | Real data directory path (pre-written by orchestrator) |
| `/search_context.json` | Phase 1 | Unified search context (genes, pathways, celltypes) |
| `/papers.json` | Phase 2/4 | Auto-saved search results (all parts) |

---

## Phase 1: Extract Context

### Step 1.1: Load Data Path
Read **`/data_path.txt`** to get the real data directory path.

### Step 1.2: Load Analysis Data
Call **`load_analysis_data`** with the exact path from `/data_path.txt`. The tool returns pre-extracted `search_context` fields — do NOT parse raw CSVs manually.

### Step 1.3: Use `search_context` (MANDATORY)

The `load_analysis_data` tool returns a unified context:

| Field | Contains |
|-------|----------|
| `genes` | Top 30 by hybrid score (0.7×max_combinedscore + 0.3×freq) — **use directly** |
| `all_genes` | Full unique gene set (reference only, do NOT use for search) |
| `pathways` | Pathway names (e.g., EGFR, Hypoxia, TGFb, MAPK, PI3K) |
| `celltypes` | Cell type names (e.g., B cells, Endothelial, Tumor, Stromal) |
| `context_type` | `lr_interaction` / `pathway` / `marker` |
| `applicable_parts` | List of Part numbers (1, 2, 3) |
| `stats` | `{total_genes, search_genes, total_pathways, total_celltypes}` |

### Step 1.4: Write Context File
Write the extracted context to **`/search_context.json`** for downstream use.

---

## Phase 2: Search Literature

### Step 2.1: Execute LLM-Powered Dynamic Search (Primary)

Use **`scripts/search_literature_dynamic.py`** — the CLI wrapper for the primary tool:

```bash
python scripts/search_literature_dynamic.py \
  --genes "CDH1,TGFB1,VIM,ERBB2,MMP2" \
  --pathways "EMT,TGFB,WNT,Hypoxia" \
  --celltypes "Tumor,Fibroblast,Macrophages" \
  --disease "breast cancer" \
  --max-results 20 \
  --output-path "papers.json"
```

**Why dynamic search first?**
- LLM understands biological context and generates optimized queries
- Adapts to Part-specific analysis types (L-R, pathway, spatial)
- Better relevance for specialized disease/tissue contexts

### Step 2.2: Automatic Internal Fallback
`search_literature_dynamic` handles fallback internally. If LLM query generation fails, it automatically switches to a fixed 4-strategy search.

**You do NOT call a separate fallback tool.**

### Step 2.3: Advanced E-utilities (Optional, Gap-Filling)

If coverage gaps remain after Phase 3 reflection, use `search_pubmed_advanced` for precision MeSH / date / publication-type filters.

→ See `references/search_strategies.md` § "Advanced PubMed E-utilities Patterns" for full syntax. Also cross-references `skills/pubmed-eutils-search/SKILL.md`.

### Step 2.4: Tool Returns
Compact summary (when `output_path` provided): `saved_to`, `total_papers`, `coverage`, `paper_titles`, `message`.

→ Full API parameters and return fields: `references/search_strategies.md` § "Complete Tool API Reference".

---

## Phase 3: Reflect (Quality Loop)

**MANDATORY**: Use **`think_tool`** for quality validation and gap analysis.

### Quality Criteria

| Criterion | Threshold | Action if Failed |
|-----------|-----------|------------------|
| **Total Papers** | >= 25 unique papers | Broaden search terms |
| **Gene Coverage** | >= 60% of priority genes | Add synonyms, search individually |
| **Pathway Coverage** | >= 50% of priority pathways | Add "signaling", disease context |
| **Max Iterations** | 3 | Proceed with warning |

### Reflection Workflow

**Thought 1 — Coverage Analysis**:
```python
think_tool(
    reflection="Coverage analysis for Part {N}: "
               "{GENES_COVERED}/{TOTAL_GENES} priority genes covered ({X}%), "
               "{PATHWAYS_COVERED}/{TOTAL_PATHWAYS} pathways covered ({Y}%). "
               "Gaps identified: {MISSING_ITEMS}. "
               "Follow-up search needed: {YES/NO}",
    iteration=1,
    max_iterations=2
)
```

**Thought 2 — Gap-Targeted Strategy** (only if coverage below threshold):
```python
think_tool(
    reflection="Targeted follow-up: Searching {MISSING_GENES} with synonyms. "
               "Broader terms for {PATHWAY}: '{PATHWAY} signaling {DISEASE}'.",
    iteration=2,
    max_iterations=2
)
```

### Follow-up Search (only if needed)

Use `search_literature` for targeted single-query searches:
```python
search_literature(
    query="SNAI1 EMT breast cancer spatial",
    max_results=10,
    include_preprints=True
)
```

→ Full reflection workflow, coverage-check logic, and part-specific priorities: `references/search_strategies.md`.

---

## Phase 4: Output (Auto-Saved via `output_path`)

### Papers Are Auto-Saved
When you call `search_literature_dynamic` with `output_path`, the tool saves complete results (all papers with full abstracts) directly to file. **You do NOT call `write_file` for papers.**

The saved file is guaranteed to have `total_papers == len(papers)` (no truncation). Use `read_file('/papers.json')` if you need to inspect the saved data.

### Saved File Format
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
    "pathways_coverage_pct": 100,
    "total_papers": 28
  },
  "search_iterations": 2,
  "search_queries": ["\"CDH1\"[Gene] AND \"breast cancer\"[Title/Abstract]"]
}
```

---

## Common Mistakes to Avoid

### ❌ FORBIDDEN
- **DO NOT** use `read_file` on raw `.csv` files — causes context overflow
- **DO NOT** parse raw CSV data manually
- **DO NOT** extract genes from pathway enrichment `name` column — those are pathways, not genes
- **DO NOT** override `search_context["genes"]` with `all_genes` — top 30 is pre-filtered
- **DO NOT** call `write_file` for papers when using `output_path` — auto-save handles it
- **DO NOT** proceed with < 60% gene coverage without follow-up searches
- **DO NOT** skip Phase 3 reflection after search

### ✅ CORRECT
- **USE** `search_context` field from `load_analysis_data` — all terms pre-extracted
- **USE** `search_literature_dynamic` as PRIMARY search tool (handles fallback internally)
- **USE** `think_tool` for quality validation in Phase 3 (1-2 thoughts)
- **USE** `search_literature` for targeted follow-up on specific gaps
- **ALWAYS** pass `output_path="papers.json"` to auto-save
- **WRITE** unified `/papers.json` (all parts)

---

## Troubleshooting

### Error: 0 papers returned after disease filter
**Cause**: `enforce_disease_match=True` filtered out all results because no paper matched the disease context string exactly.
**Solution**: Retry with `--no-enforce-disease-match` (CLI) or `enforce_disease_match=False` (tool call). Alternatively, use a broader disease term (e.g., "cancer" instead of "triple-negative breast cancer").

### Error: Gene coverage < 60% after 3 iterations
**Cause**: Search terms too specific, or gene symbols missing from the PubMed abstracts.
**Solution**: Use `search_literature(query="GENE synonym disease")` for individual missing genes with known synonyms (e.g., `CDH1` → `"E-cadherin"`, `TGFB1` → `"TGF-beta"`). Accept residual gaps after iteration cap and note them in Phase 3 reflection.

### Error: `load_analysis_data` returned empty `search_context`
**Cause**: `/data_path.txt` points to a wrong directory, or the analysis result files are missing.
**Solution**: `read_file('/data_path.txt')` to verify. Check that `interest_sig_liana.csv` (or decoupler results) exists at that path. If missing, the PLANNER subagent must rerun data assessment first.

### Error: `write_file` refused by `WriteFileArgGuardMiddleware`
**Cause**: Attempted to manually write papers after calling `search_literature_dynamic` without `output_path`.
**Solution**: Always pass `output_path="papers.json"` to `search_literature_dynamic`. The tool auto-saves; manual `write_file` for papers is blocked by guard middleware. See "Common Mistakes" above.

### Error: Results look irrelevant to the disease context
**Cause**: LLM generated generic queries without disease anchoring, or `rerank_mode="off"`.
**Solution**: Enable LLM rerank with `--rerank-mode llm --rerank-top-n 12 --rerank-min-confidence 0.70`. Or supply more specific pathway/celltype context in the arguments.

---

## Where to Find More

- **Full tool API (parameters, returns, rerank options)** → `references/search_strategies.md` § "Complete Tool API Reference"
- **Advanced PubMed E-utilities patterns** → `references/search_strategies.md` § "Advanced PubMed E-utilities Patterns"
- **Part 1/2/3 specific search focus** → `references/search_strategies.md` § "Part-Specific Search Focus"
- **Analysis-type → tool mapping, phase mapping, quality thresholds** → `references/search_strategies.md` § "Quick Reference Card"
- **Interpretation paragraph + reference list format (consumed by INTERPRETER)** → `references/search_strategies.md` § "Interpretation Output Format"
- **Full worked example (Apoe-Trem2 in Alzheimer disease)** → `references/search_strategies.md` § "Full Example"
- **Gene/pathway/L-R keyword combinations** → `references/search_strategies.md` § "L-R / Pathway / Gene-Marker Search Strategy"
- **PubMed E-utilities full syntax** → `skills/pubmed-eutils-search/SKILL.md`
