# Evidence Retrieval Strategy Reference

This reference expands the role-specific `biomedical-literature-search` workflow.
Production SEARCHER mode performs one disease-anchored
`search_literature_dynamic` call, then grades saved title and abstract evidence
into deterministic citation buckets.

## Role Mode Output Contracts

| Mode | Purpose | Retrieval | Output paths | Do not write or overwrite |
| --- | --- | --- | --- | --- |
| PLANNER | Lightweight context search for feasibility and planning. | `max_results=10` to `20` | `planner_papers.json` | `papers.json`, `citation_candidates.json`; do not call `create_literature_handoff`. |
| SEARCHER Production | Canonical INTERPRETER evidence handoff. | Broad raw retrieval with `max_results=100` | `papers_raw.json`, `citation_candidates.json`, filtered `papers.json` | Do not put `disease_only_background` or `rejected_weak_evidence` in `papers.json`. |
| SEARCHER Retrieval-Only Benchmark | Isolate retrieval skill effects. | Same retrieval strategy as SEARCHER Production Mode | `papers_raw.json` | `papers.json`, `citation_candidates.json`; do not call `create_literature_handoff`. |
| REPORTER | Cross-part synthesis using SEARCHER evidence handoff. | Existing RAG retrieval with `search_literature_fulltext(part_name="all")` | `synthesis_validation.json` | Canonical `papers.json`; do not create a separate synthesis evidence set. |

`papers.json` is the canonical SEARCHER-to-INTERPRETER citation source only in
SEARCHER Production Mode. PLANNER and REPORTER must not overwrite it. Retrieval-
only benchmark runs leave filtering to the benchmark runner. Legacy retrieval-
only diagnostics may apply the same direct/context cap-40 filter to skill ON and
skill OFF arms after retrieval; this benchmark-local filter is not the current
SEARCHER Production handoff cap.
REPORTER synthesis citations must stay within `papers.json` and the existing
RAG collection for `part_name="all"`.

## SEARCHER Production Tool Call

Use `search_literature_dynamic` as the only retrieval entry point:

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

The compact return is a status payload. Always grade from
`data_dir/papers_raw.json`; cite from the filtered `data_dir/papers.json` handoff.

## Query Axes

| Axis | Role | Rule |
| --- | --- | --- |
| LR pairs | Primary | Keep prioritized pairs together in `search_context["lr_pairs"]`; single-pair callers must construct `lr_pairs=[{"ligand": ligand, "receptor": receptor}]`, keep both symbols together in `genes`, and pass that same list to `create_literature_handoff`. |
| Disease | Primary anchor | Required when known; keeps the paper set disease-specific. |
| Pathways | Modifier | Helps contextualize evidence; not a replacement for LR symbols. |
| Celltypes | Modifier | Helps contextualize evidence; not a primary scoring target. |

Do not broaden with genes extracted from titles or abstracts. Uppercase text in
biomedical abstracts includes methods, cell lines, variants, acronyms, and headings;
using it as search input creates noisy paper sets.

## Dedup And Evidence Text

Deduplicate in saved order with this priority:

1. PMID
2. normalized DOI
3. normalized title

For each unique paper:

- abstract present: `evidence_text = title + " " + abstract`
- abstract missing: `evidence_text = title` and `abstract_missing=true`
- both missing: `evidence_text_missing=true`; keep only as rejected diagnostics

## Boundary Matching

Match ligand and receptor symbols with:

```text
(?<![A-Za-z0-9])<symbol>(?![A-Za-z0-9])
```

Apply the regex case-insensitively after escaping the symbol. This rejects substring
collisions for short symbols such as `APP`, `MET`, `KIT`, `IL6`, and `MYC`.

## Bucket Contract

The handoff helper writes `citation_candidates.json` with:

- `schema_version`: `deep_interpreter_literature_candidates_v1`
- `inputs`: disease, LR pairs, pathways, celltypes
- `source`: papers path, total paper count, unique paper count, duplicate count
- `counts`: candidate count per bucket
- `bucket_order`: fixed order shown below
- `pair_results`: direct/context counts per LR pair
- `papers`: all graded papers with bucket metadata

Bucket order and predicates:

| Bucket | Score | Predicate |
| --- | ---: | --- |
| `direct_lr_evidence` | 100 | Ligand and receptor boundary-match, and disease matches when provided. |
| `receptor_pathway_context_evidence` | 70 | Disease matches, and at least one LR symbol, pathway, or celltype matches, but not both LR symbols. |
| `disease_only_background` | 40 | Disease matches, but no LR symbol, pathway, or celltype modifier matches. |
| `rejected_weak_evidence` | 0 | Missing evidence, missing disease context, or no relevant LR/modifier support. |

Each graded paper keeps original paper fields and adds:

```json
{
  "pmid": "31364002",
  "title": "...",
  "doi": "...",
  "evidence_bucket": "direct_lr_evidence",
  "supported_lr_pairs": [{"ligand": "TGFB1", "receptor": "TGFBR2"}],
  "direct_lr_pairs": [{"ligand": "TGFB1", "receptor": "TGFBR2"}],
  "context_lr_pairs": [],
  "matched_terms_by_pair": {},
  "bucket_reasons_by_pair": {}
}
```

## Handoff Contract

`papers.json` is the INTERPRETER-facing handoff. It contains only
`direct_lr_evidence` and `receptor_pathway_context_evidence` papers, capped at
100 by default. The cap is an upper bound: if fewer than 100 eligible
direct/context papers exist, select all eligible papers and record the unused
capacity. This canonical `papers.json` handoff is written only by SEARCHER
Production Mode. `papers_raw.json` and `citation_candidates.json` remain
complete audit artifacts.

This handoff style evaluates the skill as an evidence-handling protocol, not as a
new retrieval backend. Keep `papers_raw.json` and `citation_candidates.json`
complete for audit, and exclude
`disease_only_background` plus `rejected_weak_evidence` from the main synthesis
or RAG context by default.

## Worked Example

Input:

```text
ligand = TGFB1
receptor = TGFBR2
disease = breast cancer
pathways = TGFB signaling
celltypes = Fibroblast
```

Run one raw retrieval call to `papers_raw.json`, then
`create_literature_handoff(...)`. Use `citation_candidates.json` for audit and
filtered `papers.json` for INTERPRETER handoff.
