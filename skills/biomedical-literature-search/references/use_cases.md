# Biomedical Literature Search Use Cases

Use these examples to decide when the skill should trigger and what artifacts it
should produce. The default SEARCHER contract is one raw `papers_raw.json`, one
complete `citation_candidates.json`, and one filtered INTERPRETER-facing
`papers.json`.

## Use Case 1: Ligand-Receptor Pair In Disease

**Trigger phrases**

- "find PubMed evidence for this LR pair in <disease>"
- "literature backing for ligand <L> and receptor <R> in <disease>"
- "is this ligand-receptor interaction reported in <disease>?"
- "ground my LR-pair claim in primary literature"

**Inputs**

- `ligand`, `receptor`: official upper-case symbols
- `disease`: one concise disease phrase
- `pathways`, `celltypes`: optional modifier lists

**Call shape**

```python
search_literature_dynamic(
    genes=search_context["genes"],
    pathways=search_context["pathways"],
    celltypes=search_context["celltypes"],
    disease=disease,
    max_results=100,
    max_iterations=1,
    output_path="papers_raw.json",
    data_dir=workspace,
    enable_lr_pair_queries=True,
    coverage_weighted_sort=True,
)

create_literature_handoff(
    raw_papers_path="papers_raw.json",
    output_path="papers.json",
    citation_candidates_path="citation_candidates.json",
    data_dir=workspace,
    disease=disease,
    lr_pairs=search_context.get("lr_pairs", []),
    pathways=search_context.get("pathways", []),
    celltypes=search_context.get("celltypes", []),
    cap=100,
)
```

**Expected output**

- `papers_raw.json`: saved full raw retrieval
- `citation_candidates.json`: bucketed evidence candidates and audit metadata
- `papers.json`: filtered handoff containing direct LR and receptor/pathway context
  papers only

## Use Case 2: Upstream-Prioritized LR Pair

**Trigger phrases**

- "the top LR pair from CellChat/CellPhoneDB/LIANA in <disease>"
- "literature support for the highest-scoring LR pair from <pipeline>"
- "back this prioritized interaction with primary citations"

The upstream score selects the LR pair. Do not include the score or pipeline name in
the PubMed query unless the user specifically asks for method-aware retrieval.

**Expected output**

Same artifacts as Use Case 1. In narrative handoff, note which upstream pipeline
prioritized the pair without polluting retrieval.

## Use Case 3: Short-Symbol LR Pair

**Trigger phrases**

- "support APP-AGER in Alzheimer disease"
- "find primary literature for MET and EGFR in cancer"
- "does MYC interact with this receptor in AML?"

Short symbols collide with English substrings and method terms. Use the same one-call
retrieval path, then rely on boundary matching in the scorer.

**Expected output**

`citation_candidates.json` should reject substring collisions and report title-only
or missing-evidence rows diagnostically.

## Use Case 4: No Primary Citation Needed

**Trigger phrases**

- "write a general overview without citing specific papers"
- "summarize breast cancer biology; do not look anything up"

**Expected behavior**

Do not use the skill. The skill exists to produce primary-literature evidence
artifacts, not background prose.

## What This Skill Does Not Do

- Full-text retrieval
- Systematic-review exhaustive recall
- Abstract-derived gene expansion
- Gene-symbol validation
- Non-biomedical search
