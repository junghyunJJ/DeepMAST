---
name: biomedical-literature-search
description: Role-specific literature workflow for ligand-receptor claims. Use SEARCHER Production mode for canonical INTERPRETER handoff artifacts, PLANNER mode for lightweight feasibility search, SEARCHER Retrieval-Only Benchmark mode to isolate retrieval effects, and REPORTER mode for existing papers.json plus part_name="all" RAG synthesis validation.
metadata:
  author: Junghyun Jung
  version: 2.1.0
---

# Biomedical Literature Search

This skill retrieves disease-anchored PubMed paper pools for ligand-receptor
evidence. In production SEARCHER mode, it grades saved title and abstract
evidence into citation buckets and writes the canonical SEARCHER-to-INTERPRETER
citation source: `papers.json`.

When this skill is evaluated, treat it as a reusable agentic protocol for tool
use, evidence grading, citation selection, and report writing. It is not a new
retrieval backend and should not be described as improving PubMed search itself.

## Core Principles

1. **LR-pair-first.** When SEARCHER has multiple prioritized LR pairs, keep them
   together as one unified `lr_pairs` set and use the shared search context genes.
   For a single-pair caller, construct
   `lr_pairs=[{"ligand": ligand, "receptor": receptor}]`, pass both symbols
   together in `genes=[ligand, receptor]`, and pass that same `lr_pairs` list to
   `create_literature_handoff`.
2. **Disease-anchored.** Always pass the disease or tissue context when known.
3. **Modifiers stay secondary.** Pathways and celltypes refine the context; they do
   not replace the LR pair or disease anchor.
4. **Saved evidence is the source of truth.** Save the full unique raw retrieval
   pool to `papers_raw.json` and grade from that file, not from the compact tool
   return.
5. **No unvalidated expansion.** Do not extract new uppercase symbols from abstracts
   for follow-up searches in the default workflow.
6. **Handoff stays selective.** Send INTERPRETER only direct LR evidence and
   receptor/pathway context evidence by default.

## When To Use

Use this skill when a task needs primary PubMed evidence for:

- multiple prioritized ligand-receptor pairs in a disease or tissue context
- a single ligand-receptor pair in a disease or tissue context
- an LR pair prioritized by CellChat, CellPhoneDB, LIANA, NicheNet, or a similar
  upstream workflow
- a pathway or celltype modifier that should frame LR evidence without becoming the
  primary retrieval axis

Do not use this skill for full-text retrieval, non-biomedical search, broad
background writing without citations, or exhaustive systematic review.

## PLANNER Mode

Purpose: lightweight context search for feasibility and planning.

- Use `search_literature_dynamic` with `max_results=10` to `20`.
- Write `planner_papers.json`.
- Do not call `create_literature_handoff`.
- Do not write `citation_candidates.json`.
- Do not write or overwrite `papers.json`.
- PLANNER papers are not INTERPRETER citation authority.

## SEARCHER Production Mode

Purpose: canonical INTERPRETER evidence handoff. `papers.json` is the canonical
SEARCHER-to-INTERPRETER citation source only in this mode.

Before calling the tool, normalize inputs:

- `lr_pairs`: list of `{ligand, receptor}` dictionaries for SEARCHER unified mode.
  Prefer the workspace `lr_candidates.json` pairs when present; fall back to
  `search_context["lr_pairs"]` / `lr_pairs_search.json` only when
  `lr_candidates.json` is missing or invalid.
- `genes`: shared search context genes, including LR symbols and prioritized modifiers
- `ligand`, `receptor`: official upper-case symbols for single-pair use
- `disease`: one concise phrase
- `pathways`, `celltypes`: lists; use `[]` when absent
- `workspace`: writable directory for saved artifacts

For a single ligand-receptor pair, set:

```python
search_context["lr_pairs"] = [{"ligand": ligand, "receptor": receptor}]
```

Use that same `search_context["lr_pairs"]` list for both retrieval context and the
handoff helper in single-pair mode. In unified SEARCHER production mode, the tools
auto-load `lr_candidates.json` pairs for LR-pair query injection when
`enable_lr_pair_queries=True`; if `lr_candidates.json` is missing or invalid, they
fall back to `lr_pairs_search.json`. Do not rely on `genes` alone to imply the LR
pair.

### Step 1: Retrieve One Broad Raw Paper Pool

Call `search_literature_dynamic` for broad raw retrieval with `max_results=100`.
In SEARCHER unified mode, use the complete `search_context` and opt into LR-pair
query injection. Save the full unique raw retrieval pool to `papers_raw.json`.
Do not apply the `max_results` or handoff cap to `papers_raw.json`; the cap is
applied later by `create_literature_handoff` when writing `papers.json`.
The tool will use `lr_candidates.json` pairs for LR-pair query injection when that
file is present in `workspace`; otherwise it falls back to `lr_pairs_search.json`.

```python
result = search_literature_dynamic(
    genes=search_context["genes"],
    pathways=search_context["pathways"],
    celltypes=search_context["celltypes"],
    disease=normalized_disease,
    max_results=100,
    max_iterations=1,
    output_path="papers_raw.json",
    data_dir=workspace,
    enable_lr_pair_queries=True,
    coverage_weighted_sort=True,
)
```

Treat the tool's internal fixed-strategy fallback as a normal completion path. Retry
manually only if the saved `papers_raw.json` is missing or empty.

### Step 2: Create Bucketed Handoff Artifacts

Run the production handoff helper after raw retrieval. The default handoff cap is
`100`. The cap 100 is an upper bound, not a target that must be filled: if fewer than
100 eligible direct/context papers exist, `papers.json` should contain all
eligible papers.

```python
handoff = create_literature_handoff(
    raw_papers_path="papers_raw.json",
    output_path="papers.json",
    citation_candidates_path="citation_candidates.json",
    data_dir=workspace,
    disease=normalized_disease,
    lr_pairs=search_context["lr_pairs"],
    pathways=search_context.get("pathways", []),
    celltypes=search_context.get("celltypes", []),
    cap=100,
)
```

The helper is implemented in
`src/agents/deep_interpreter/tools/literature_handoff.py`. If tool execution is
not available, apply the same deterministic bucket rules and write the same two
artifacts with the available file tools.

### Step 3: Use The Bucketed Output

`citation_candidates.json` is the complete audit artifact. SEARCHER grading/QC
grades all raw candidates from `papers_raw.json` into this file and keeps all
unique raw papers after grading:

```json
{
  "schema_version": "deep_interpreter_literature_candidates_v1",
  "inputs": {},
  "source": {},
  "bucket_order": [
    "direct_lr_evidence",
    "receptor_pathway_context_evidence",
    "disease_only_background",
    "rejected_weak_evidence"
  ],
  "counts": {},
  "pair_results": [],
  "papers": []
}
```

Each graded paper keeps its original paper fields and adds `evidence_bucket`,
`supported_lr_pairs`, `direct_lr_pairs`, `context_lr_pairs`,
`matched_terms_by_pair`, and `bucket_reasons_by_pair`.

`papers.json` is the filtered INTERPRETER handoff. INTERPRETER handoff selection
uses only papers from `direct_lr_evidence` and
`receptor_pathway_context_evidence`, preserves `evidence_bucket` plus
`supported_lr_pairs` metadata, and applies `cap=100` only if eligible
direct/context papers exceed 100. If eligible direct/context papers are below the
cap, select all eligible papers and record unused capacity as normal. Do not
include `disease_only_background` or `rejected_weak_evidence` in INTERPRETER RAG
context by default, and do not expand raw retrieval solely to fill all 100 slots.

When eligible direct/context papers exceed 100, the production selection policy is
`direct_all_pair_round_robin_100`: preserve direct evidence first; if direct
evidence alone exceeds the cap, truncate direct papers by LR-pair round-robin;
otherwise fill remaining slots with context papers by LR-pair round-robin and use
unpaired context only as a fallback. Keep `papers_raw.json` and
`citation_candidates.json` as larger audit artifacts.

Bucket rules:

- `direct_lr_evidence` (`score=100`): ligand and receptor both boundary-match in
  title+abstract, and the disease phrase matches when disease is provided.
- `receptor_pathway_context_evidence` (`score=70`): disease matches, and at least
  one LR symbol, pathway, or celltype modifier matches, but the paper is not direct
  LR evidence.
- `disease_only_background` (`score=40`): disease matches, but no LR symbol,
  pathway, or celltype modifier matches.
- `rejected_weak_evidence` (`score=0`): evidence text is missing, disease context is
  missing, or the row lacks relevant LR/modifier support.

Keep `papers_raw.json` and `citation_candidates.json` complete for audit.
`papers.json` is intentionally filtered for INTERPRETER consumption.

## SEARCHER Retrieval-Only Benchmark Mode

Purpose: isolate retrieval skill effects.

- Use the same retrieval strategy as SEARCHER Production Mode, including
  broad raw retrieval with `max_results=100`.
- Save raw retrieval to `papers_raw.json`.
- Do not call `create_literature_handoff`.
- Do not write `citation_candidates.json`.
- Do not write filtered `papers.json`.
- The legacy retrieval-only benchmark runner may apply the same diagnostic
  direct/context cap-40 filter to skill ON and skill OFF arms after retrieval.
  This is benchmark-local and is not the current SEARCHER Production handoff cap.

## REPORTER Mode

Purpose: synthesize using the existing SEARCHER evidence handoff.

- Use canonical `papers.json` as the REPORTER citation universe.
- Use `search_literature_fulltext` with `part_name="all"` for existing RAG retrieval.
- Do not run PubMed retrieval from REPORTER.
- Do not write reporter-specific paper retrieval artifacts.
- Do not write or overwrite canonical `papers.json`.
- If existing RAG does not support a synthesis claim, caveat it or mark it as
  hypothesis/needs validation.

PLANNER and REPORTER must not overwrite canonical `papers.json`. REPORTER uses
the SEARCHER evidence handoff; it does not create a separate synthesis evidence set.

## Evidence Matching Rules

Deduplicate papers by `pmid`, then normalized DOI, then normalized title, preserving
the first occurrence. For each scored paper:

- abstract present: `evidence_text = title + " " + abstract`
- abstract missing: use title-only evidence and set `abstract_missing=true`
- title and abstract both missing: set `evidence_text_missing=true` and reject

Match ligand and receptor with a boundary regex equivalent to:

```text
(?<![A-Za-z0-9])<symbol>(?![A-Za-z0-9])
```

This is especially important for short symbols such as `APP`, `MET`, `KIT`, `IL6`,
and `MYC`.

## Common Issues

### Treating the compact return as citable evidence
The compact return omits full abstracts. Always grade from saved
`papers_raw.json`.

### Dropping one side of the LR pair
If the caller has an LR pair, both symbols belong in `genes` and the pair belongs
in `lr_pairs`. Single-pair callers must construct
`lr_pairs=[{"ligand": ligand, "receptor": receptor}]` and pass that same list to
`create_literature_handoff`. Do not replace LR symbols with pathway genes or
abstract-derived candidates.

### Running abstract symbol expansion
SEARCHER Production Mode stops after one broad raw retrieval through
`search_literature_dynamic` and deterministic handoff grading. Do not create
expansion ledgers, do not run extra high-cap expansion calls, and do not search
uppercase tokens extracted from abstracts.

### Citing disease-missing LR co-mentions
A paper that mentions both symbols but not the disease anchor is diagnostic context,
not a default citation for a disease-specific LR claim.

### Missing saved files
Pass both `output_path` and `data_dir`. If `papers_raw.json` is missing, fix the
save path before grading. If `papers.json` is missing after grading, rerun
`create_literature_handoff`.

## Examples

### LR pair in disease context

```python
search_context = {
    "genes": ["TGFB1", "TGFBR2", "COL1A2", "ITGA1"],
    "pathways": ["TGFB signaling", "ECM-receptor interaction"],
    "celltypes": ["Fibroblast", "Tumor cell"],
    "lr_pairs": [
        {"ligand": "TGFB1", "receptor": "TGFBR2", "lr_pair": "TGFB1-TGFBR2"},
        {"ligand": "COL1A2", "receptor": "ITGA1", "lr_pair": "COL1A2-ITGA1"},
    ],
}

result = search_literature_dynamic(
    genes=search_context["genes"],
    pathways=search_context["pathways"],
    celltypes=search_context["celltypes"],
    disease="breast cancer",
    max_results=100,
    max_iterations=1,
    output_path="papers_raw.json",
    data_dir=workspace,
    enable_lr_pair_queries=True,
    coverage_weighted_sort=True,
)

handoff = create_literature_handoff(
    raw_papers_path="papers_raw.json",
    output_path="papers.json",
    citation_candidates_path="citation_candidates.json",
    data_dir=workspace,
    disease="breast cancer",
    lr_pairs=search_context["lr_pairs"],
    pathways=search_context["pathways"],
    celltypes=search_context["celltypes"],
    cap=100,
)
```

Then use `workspace/papers.json` for INTERPRETER handoff and
`workspace/citation_candidates.json` for audit.

### Upstream prioritized LR pair

If CellChat reports `COL1A2-ITGA1` as a top pair in breast cancer, use the score only
to choose the pair. Do not put `CellChat` or the numeric interaction score into the
PubMed query unless the user asks for tool-method literature.

## References

- Detailed scoring rules: `references/search_strategies.md`
- Trigger examples: `references/use_cases.md`
- Manual smoke wrapper: `scripts/search_literature_dynamic.py`
- Production handoff helper: `src/agents/deep_interpreter/tools/literature_handoff.py`
