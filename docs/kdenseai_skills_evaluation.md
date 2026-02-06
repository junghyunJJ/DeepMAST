# K-Dense-AI Scientific Skills Evaluation for DeepMAST

## Overview

This document evaluates the [K-Dense-AI](https://github.com/K-Dense-AI) scientific skills library against DeepMAST's Deep Interpreter subagent architecture. The goal is to identify which external skills would provide the most value for each subagent.

The INTERPRETER is DeepMAST's most complex subagent (8 tools, 326-line prompt, dual RAG/Abstract mode) but has **zero skills**. These external skills would provide the most value:

---

## INTERPRETER Subagent — High-Impact Skills (5)

| # | Skill | What It Provides | DeepMAST Benefit |
|---|-------|------------------|------------------|
| 1 | **`kegg-database`** | KEGG REST API workflows for pathway mapping, gene-to-pathway lookups, cross-database ID conversion | INTERPRETER could validate pathway claims against KEGG's curated 2,825+ pathways. Currently relies on LLM knowledge alone for pathway biology. |
| 2 | **`reactome-database`** | Overrepresentation analysis, expression analysis, pathway hierarchy navigation | Complements KEGG with reaction-level detail. Reactome provides mechanistic pathway data that KEGG lacks. |
| 3 | **`string-database`** | PPI network queries (59M proteins), functional enrichment, network visualization | Directly relevant to L-R interaction interpretation. INTERPRETER could validate that predicted L-R pairs are supported by known protein interactions. |
| 4 | **`gene-database`** | NCBI Gene lookups by symbol/ID, GO term queries, gene-disease associations | Provides gene function context. When interpreting markers like *VEGFA* or *CD274*, structured gene annotations beat LLM recall. |
| 5 | **`uniprot-database`** | Protein function, subcellular localization, tissue expression, domain annotations | L-R interactions are protein-level events. UniProt data on receptor/ligand localization and function would ground interpretations. |

**Key insight**: These 5 skills provide **structured biological knowledge** that the INTERPRETER currently lacks. Right now, the INTERPRETER's biological context comes entirely from (a) LLM training data and (b) PubMed paper abstracts/full-text. Adding pathway/PPI/gene database access would create a third knowledge layer — curated, structured, and verifiable.

### Medium-Impact Skills (2)

| # | Skill | Benefit |
|---|-------|---------|
| 6 | **`opentargets-database`** | Drug target identification and disease associations. Useful when CCI analysis reveals therapeutic targets (e.g., checkpoint ligands). |
| 7 | **`ensembl-database`** | Genome annotations, variant effects. Useful if analysis involves genetic variants affecting L-R interactions. |

---

## SEARCHER Subagent

Already has `biomedical-literature-search` skill. These would extend coverage:

| # | Skill | What It Adds Beyond Current |
|---|-------|-----------------------------|
| 8 | **`pubmed-database`** | Enhanced E-utilities workflows (MeSH term handling, systematic review methodology). DeepMAST already uses BioMCP for PubMed search, but this skill provides more structured search strategy guidance. |
| 9 | **`biorxiv-database`** | Preprint access. DeepMAST currently only searches PubMed. Cutting-edge ST/CCI methods often appear on bioRxiv months before PubMed. |
| 10 | **`openalex-database`** | 240M+ works across all publishers. Broader than PubMed (which is biomedical only). Useful for interdisciplinary CCI papers. |
| 11 | **`literature-review`** | PRISMA-compliant systematic review methodology. Could elevate DeepMAST's search from "find papers" to "systematic evidence gathering". |

**Assessment**: The SEARCHER's existing skill is already comprehensive (5-phase workflow, quality thresholds). The marginal benefit of adding `pubmed-database` is low (overlaps with BioMCP). `biorxiv-database` and `openalex-database` are the most valuable additions for broadening literature coverage.

---

## PLANNER Subagent

| # | Skill | Benefit |
|---|-------|---------|
| 12 | **`hypothesis-generation`** | 8-step structured hypothesis formulation. The PLANNER currently generates 2-4 hypotheses using only LLM reasoning + analysis data. This skill provides frameworks (competing hypotheses, falsifiability criteria, experiment design templates). |

**Assessment**: Moderate value. The PLANNER is intentionally simple (1 tool) and its hypotheses feed the rest of the pipeline. A `hypothesis-generation` skill would improve hypothesis quality but the downstream impact depends on how well SEARCHER and INTERPRETER use those hypotheses.

---

## REPORTER Subagent

Already has `html-report-generator` skill. These could enhance output quality:

| Skill | Benefit |
|-------|---------|
| **`scientific-writing`** | IMRAD manuscript structure, citation management, reporting guidelines (CONSORT/STROBE). Useful if DeepMAST reports need to approach manuscript quality. |
| **`scientific-visualization`** | Publication-ready multi-panel figures with journal-specific formatting. Currently figures are embedded as Base64 without post-processing. |

**Assessment**: Low priority. The existing `html-report-generator` skill already produces good HTML reports. These would only matter if the goal shifts from "analysis report" to "manuscript-ready output".

---

## What's NOT Useful (~130 skills)

| Domain | Count | Why Not Relevant |
|--------|-------|------------------|
| Quantum computing | 4 | Different field entirely |
| Materials science | 3 | Different field |
| Lab automation | 8 | DeepMAST is computational analysis, not bench work |
| Drug discovery/cheminformatics | 11 | Too downstream for CCI analysis |
| Clinical/healthcare | 8 | DeepMAST is research, not clinical |
| Economics/business | 4 | Unrelated domain |
| Astronomy/physics | 2 | Unrelated domain |
| Presentation/publishing | 5 | Already covered by html-report-generator |
| ML frameworks (generic) | 12 | DeepMAST uses LLMs, not training custom models |
| Data processing (Polars/Dask/etc.) | 6 | Tools handle data processing internally |
| Proteomics/flow cytometry | 3 | Too specialized for ST/CCI |
| Most database skills | ~20 | Patent, FDA, metabolomics, etc. — not ST/CCI relevant |
| Communication/writing (generic) | ~14 | Already partially covered |
| Other bioinformatics (NGS-focused) | ~5 | pysam, deeptools, etc. are for raw sequencing, not ST analysis |
| Digital pathology | 2 | Could be relevant for tissue-level ST but currently out of scope |

---

## Integration Considerations

If integrating later, there are **3 possible approaches**:

### Approach A: SKILL.md Only (Easiest)
- Copy/adapt SKILL.md files into `skills/` directory
- Auto-discovered by SkillsMiddleware
- No code changes needed
- **Limitation**: Guidance only, no new tool capabilities

### Approach B: SKILL.md + Python Scripts as Tools
- Add SKILL.md files AND wrap database API scripts as LangGraph tools
- Each skill's `scripts/` directory contains ready-to-use Python code (e.g., `kegg_api.py`, `string_api.py`)
- These could become new tools in `src/agents/deep_interpreter/tools/`
- **Biggest impact** but requires development work

### Approach C: MCP Server Integration
- The K-Dense-AI repo supports MCP server mode
- Could integrate via DeepMAST's existing `langchain-mcp-adapters` dependency
- Cleanest architecture but adds MCP server dependency

---

## Bottom Line

**If you could only add 3 things**, the highest-impact additions would be:

1. **`kegg-database` + `reactome-database`** (as tools for INTERPRETER) — Gives structured pathway knowledge for validating pathway claims in CCI interpretation
2. **`string-database`** (as tool for INTERPRETER) — PPI context for L-R interaction validation
3. **`biorxiv-database`** (as skill for SEARCHER) — Preprint access to catch cutting-edge ST/CCI papers not yet on PubMed

These address the INTERPRETER's biggest weakness: reliance on LLM knowledge + paper abstracts for biological interpretation, without access to curated biological databases.
