---
name: drug-target-hypothesis
description: Generate evidence-backed biological mechanism hypotheses from completed drug target assessment evidence. Use when Stage 1-3 evidence is present, `assessment_results.json.stage3_candidates` is non-empty, and the hypothesis writer needs to produce `evidence/hypothesis_report.json` for downstream reporting. Do not use for general literature-driven hypothesis ideation or dataset classification.
metadata:
    skill-author: Junghyun Jung
    version: 1.0.0
---

# Drug Target Hypothesis Generation

## Overview

Generate testable biological mechanism hypotheses from multi-stage drug target assessment evidence. This skill is specialized for the Drug Target Agent's hypothesis-writer runtime: it reads hypothesis-scope evidence, generates mechanism hypotheses across four thematic categories, validates every cited filename, and persists a structured `hypothesis_report.json` artifact for downstream report writing.

Unlike the general `hypothesis-generation` skill or `hypogenic`, this skill is not a free-form ideation workflow. It is a runtime-aligned contract for evidence-backed hypothesis generation with deterministic save gates.

## When to Use This Skill

Use this skill when:
- Stage 1-3 evidence has already been generated in `{data_dir}/evidence/`
- `assessment_results.json.stage3_candidates` is present and non-empty
- The goal is to produce mechanistic drug-target hypotheses for downstream reporting
- The runtime can call `load_evidence_files(data_dir, scope="hypothesis")`, `validate_evidence_references(...)`, and `save_hypothesis_report(...)`

Do not use this skill when:
- You need general scientific hypothesis ideation without drug-target evidence
- You need literature-driven hypothesis generation from scratch
- You are classifying tabular datasets
- `stage3_candidates` is empty; in that case hypothesis generation is skipped and the downstream report proceeds without a hypothesis section

## Concrete Use Cases

Use Case: Runtime hypothesis writer on a completed evidence bundle
Trigger: "Generate `evidence/hypothesis_report.json` from the saved Stage 1-3 evidence" or "Run the hypothesis-writer step for this completed drug-target assessment"
Steps:
1. Load hypothesis-scope evidence with `load_evidence_files(data_dir, scope="hypothesis")`
2. Build retained hypotheses from the returned files and validate all cited filenames
3. Persist the structured result through `save_hypothesis_report(data_dir, hypothesis_data)`
Result: A runtime-aligned JSON hypothesis artifact is saved for downstream reporting

Use Case: Deterministic retry after citation rejection
Trigger: "Retry the hypothesis report after `invalid_references`" or "Recover from `failed_pair_violations` in the hypothesis payload"
Steps:
1. Inspect the deterministic rejection returned by `save_hypothesis_report`
2. Remove or repair invalid citations, including `_FAILED` suffix handling for contrast-only failed pairs
3. Re-run validation and save only after the payload changes
Result: The hypothesis artifact is retried through the runtime contract instead of repeating the same rejected payload

Use Case: Zero-featured bypass
Trigger: "Check whether hypothesis generation should be skipped for this data_dir" or "Handle the case where `stage3_candidates` is empty"
Steps:
1. Read `assessment_results.json.stage3_candidates` from the hypothesis-scope evidence
2. Detect that no FEATURED genes are available for retained hypotheses
3. Stop hypothesis generation and let the downstream report continue without a hypothesis section
Result: The runtime bypasses hypothesis generation cleanly instead of inventing placeholder biology

## Runtime Contract

The active runtime contract is:
- Load evidence only through `load_evidence_files(data_dir, scope="hypothesis")`
- Do not use `read_file`, `write_file`, or `ls` as the persistence path for hypothesis output
- Validate all cited filenames with `validate_evidence_references(data_dir, [...])`
- Persist through `save_hypothesis_report(data_dir, hypothesis_data)`; `save_evidence(data_dir, "hypothesis_report.json", ...)` is a compatibility wrapper over the same canonicalizer

Treat `src/agents/drug_target/subagents/prompts.py` and `src/agents/drug_target/tools/evidence_loader.py` as the source of truth when this skill and repo docs disagree.

---

## Workflow

Follow these phases sequentially.

### Phase 1: Evidence Ingestion and Target Categorization

**Step 1.1: Load hypothesis-scope evidence**

Start with:

```python
load_evidence_files(data_dir, scope="hypothesis")
```

Use the returned `files` payload as the usable evidence set for hypothesis generation.

Required files for normal hypothesis execution:

| File Pattern | Required? | Description |
|-------------|-----------|-------------|
| `assessment_results.json` | Yes | Canonical disease context and `stage3_candidates` list |
| `stage2_evidence.json` | Yes | OpenTargets evidence summary |
| `stage1_filter_results.json` | Yes | Binary pass/fail data for Stage 1 pair validation |
| `stage1_{LIGAND}--{RECEPTOR}.json` | Usually | Per-pair biological context; PASSED pairs load fully, FAILED pairs may be slim stubs |
| `stage3_{GENE}.json` | Usually | Per-featured-gene deep dives |
| `ot_{GENE}.json` | Optional | Additional OpenTargets detail for featured genes |
| `known_drugs.json` | Optional | Disease-level drug landscape |
| `gene_manifest.json` | Optional | Gene list and selection flags |

Do not treat prior-run outputs or legacy aggregates as valid citation targets. In hypothesis scope, `excluded_files` and denied citations include:
- `hypothesis_report.json`
- `target_assessment.json`
- `stage1_audit.json`
- `stage1_confidence.json`
- `stage1_evidence.json`

If `stage3_candidates` is empty, stop hypothesis generation and let the downstream report writer continue without a hypothesis section.

See `references/evidence_format_spec.md` for schema details.

**Step 1.2: Categorize targets**

Derive tiers from runtime evidence, not from a parent markdown report:
- **FEATURED**: genes listed in `assessment_results.json.stage3_candidates`
- **NOVEL**: non-featured genes that still show distinctive exploratory signal in the available assessment and OpenTargets evidence
- **OTHER**: all remaining genes used as supporting context only

**Step 1.3: Build the evidence inventory**

For each FEATURED gene, collect:
- classification, priority, and evidence available in `assessment_results.json`
- related `stage1_*.json` pairs
- Stage 3 drug and publication evidence from `stage3_{GENE}.json`
- tractability and function summaries from `stage2_evidence.json` or `ot_{GENE}.json`

For NOVEL genes, record:
- why they remain biologically interesting
- which Stage 1 pairs and pathway contexts they appear in
- any tractability or disease-association signals

**Step 1.4: Extract key biological entities**

Look for:
- convergent pathways across multiple Stage 1 pairs
- high-plausibility genes
- strong PPI links
- strong coexpression signals
- hub genes appearing in several pairs
- tractable targets supported by multiple modalities

Record these entities because they become the building blocks of the final hypotheses.

### Phase 1.5: FAILED-pair Citation Gate (DETERMINISTIC)

Before using any Stage 1 pair as evidence, check its pass/fail status in `stage1_filter_results.json`.

The strict Stage 1 pass condition uses all of the following:
- STRING combined score above 0.8
- coexpression p-value below 0.05
- gene A p-value below 0.05
- gene B p-value below 0.05

Rules:
- A FAILED pair cannot support the core mechanism claim of a hypothesis.
- A FAILED pair may be cited only as contrast evidence.
- Contrast citations must append the literal `_FAILED` suffix, for example `stage1_TGFB1--P4HB.json_FAILED`.
- If a FAILED pair is cited without `_FAILED`, `save_evidence` rejects the payload with `failed_pair_violations`.

When a pair is cited with `_FAILED`, do not describe it as validated support.

---

### Phase 2: Hypothesis Generation

Generate an initial set of 4-6 hypotheses across four mandatory thematic categories.

| Category | Focus | Minimum Count |
|----------|-------|:-------------:|
| **Mechanism of Action** | How a target mechanistically drives disease biology | 1 |
| **Therapeutic Strategy** | How to intervene with a target or modality | 1 |
| **Cross-Target Interaction** | Multi-target synergies or pathway convergence | 1 |
| **Novel Pathway** | Unexpected biology revealed by the evidence | 1 |

Each hypothesis must include all seven elements:
1. Title
2. Thematic category
3. Core claim
4. Supporting evidence references
5. Key biological entities
6. Falsifiable prediction
7. Proposed validation approach

Generation guidance:
- Start with FEATURED genes first
- Use hub genes and convergent pathways for cross-target hypotheses
- Use distinctive non-featured genes for novel pathway hypotheses
- Prefer hypotheses that integrate multiple evidence types

---

### Phase 3: Gap Detection

Build a coverage matrix over the real Stage 1 and Stage 3 evidence files.

**Step 3.1: Mark referenced evidence**
- Map each evidence file to the hypotheses that cite it

**Step 3.2: Identify orphan evidence**
- Stage 1 pairs not cited anywhere
- FEATURED genes whose Stage 3 evidence is absent from retained hypotheses
- pathway clusters never mentioned

**Step 3.3: Generate supplementary hypotheses**
- Use `[GAP]` for orphan-evidence hypotheses
- Reserve `[FEATURED-GAP]` for the mandatory FEATURED-gene coverage rule in Phase 4.75

**Step 3.4: Coverage target**
- Aim to cover at least 80 percent of the real Stage 1 and Stage 3 evidence files
- The runtime recomputes `evidence_coverage_pct` during save; do not rely on manual percentages as the source of truth

---

### Phase 4: UCB Scoring and Filtering

Score every hypothesis on four dimensions:

```text
Score = 0.30 x Evidence_Coverage + 0.30 x Specificity + 0.20 x Novelty + 0.20 x Actionability
```

For each hypothesis, provide:
- four dimension scores
- one short justification per dimension

Filtering rules:
1. Remove any hypothesis with Specificity below 0.5
2. Remove any hypothesis with composite score below 0.4
3. Rank surviving hypotheses by composite score
4. Keep the top `max(5, len(stage3_candidates))` hypotheses after initial ranking
5. Maintain at least three thematic categories in the retained set

If too few retained hypotheses remain to satisfy FEATURED coverage, generate additional hypotheses before rescoring rather than forcing the same underspecified set through save.

See `references/ucb_scoring_criteria.md` for scoring calibration.

### Phase 4.5: Validate Evidence References (MANDATORY)

Before any save attempt, call:

```python
validate_evidence_references(data_dir, all_cited_filenames)
```

Rules:
- Pass one flat combined list containing every filename cited across all hypotheses
- If validation returns invalid references, replace or remove them
- Never invent filenames
- Stage 1 filenames use the `stage1_<LIGAND>--<RECEPTOR>.json` pattern with two hyphens between the gene symbols
- Re-run validation until it returns `valid: true`

Do not proceed to `save_evidence` until filename validation is clean.

### Phase 4.75: TOP-N Coverage Gate (DETERMINISTIC)

After ranking and filtering, ensure every gene in `assessment_results.json.stage3_candidates` appears in the retained hypothesis set through `biological_entities.genes`.

Rules:
- For every uncovered FEATURED gene, add one `[FEATURED-GAP]` hypothesis that explicitly includes that gene
- The final retained set must contain at least `max(4, len(FEATURED))` hypotheses
- `save_hypothesis_report` computes `topn_coverage` deterministically and rejects the payload if `topn_coverage.missing` is non-empty

This gate is independent from the general orphan-evidence `[GAP]` logic.

---

### Phase 5: Save the Hypothesis Artifact

Persist the output only as structured JSON:

```python
save_hypothesis_report(data_dir, hypothesis_data)
```

Do not use `write_file`.

`assets/hypothesis_report_template.md` and `assets/example_hypothesis_ipf.md` are reference assets for downstream human-readable presentation. They are not the runtime persistence contract.

Required top-level payload fields include:
- `disease`
- `evidence_coverage_pct`
- `hypotheses_generated`
- `hypotheses_retained`
- `hypotheses`
- `gap_analysis`

### Phase 5.5: Retry Policy on Deterministic Rejection

If `save_evidence` returns `saved: false`:
- For `invalid_references`, remove or replace invalid filenames and validate again
- For `topn_coverage.missing`, add one `[FEATURED-GAP]` hypothesis per missing FEATURED gene
- For `failed_pair_violations`, remove the citation or append `_FAILED` if it is truly contrast evidence

Do not retry the same payload after a deterministic rejection. Change the payload first, then retry.

---

## Examples

### Example 1: Happy-path save flow

```python
evidence = load_evidence_files(data_dir, scope="hypothesis")
# Build hypotheses only from evidence["files"]

validate_evidence_references(data_dir, [
    "stage1_ICAM1--ITGB2.json",
    "stage3_ICAM1.json",
    "ot_ICAM1.json",
])

save_evidence(data_dir, "hypothesis_report.json", {
    "disease": "Idiopathic Pulmonary Fibrosis",
    "evidence_coverage_pct": 0,
    "hypotheses_generated": 6,
    "hypotheses_retained": 5,
    "hypotheses": [...],
    "gap_analysis": {...}
})
```

Why this works:
- citations come from real hypothesis-scope files
- the artifact is JSON, not markdown
- runtime fills the final deterministic coverage metadata during save

### Example 2: FAILED-pair rejection and recovery

```python
validate_evidence_references(data_dir, [
    "stage1_TGFB1--P4HB.json",
    "stage3_TGFB1.json",
])

save_evidence(...)
# returns saved: false with failed_pair_violations
```

Correct recovery:
- if `stage1_TGFB1--P4HB.json` is contrast evidence only, change the citation to `stage1_TGFB1--P4HB.json_FAILED`
- if it was being used as primary support, rebuild the hypothesis around a PASSED pair instead
- then validate again and retry with a changed payload

---

## Quality Standards

Every generated hypothesis report must meet these standards:
- Every claim traces to a specific evidence file and field
- Every hypothesis includes a falsifiable prediction
- The retained set covers the required FEATURED genes
- All dimension scores have short justifications
- No fabricated literature, drug names, or filenames
- FAILED pairs are never presented as validated primary evidence

---

## Common Issues

### `stage3_candidates` is empty

Hypothesis generation should stop. This is a zero-featured bypass case, not a reason to invent placeholder hypotheses.

### `validate_evidence_references` returns invalid filenames

Remove or replace the bad filenames. Do not invent new ones. Stage 1 pair filenames always use two hyphens between ligand and receptor.

### `save_evidence` returns `topn_coverage.missing`

One or more FEATURED genes are uncovered. Add a `[FEATURED-GAP]` hypothesis for each missing gene before retrying.

### `save_evidence` returns `failed_pair_violations`

You cited a FAILED Stage 1 pair without `_FAILED`, or used it as primary support. Fix the citation or rebuild the hypothesis.

### `load_evidence_files` did not return a pair as full content

In hypothesis scope, some files are intentionally stubbed or excluded. Only cite files returned with usable content in `files`, and never cite entries from `excluded_files`.

### Validator flags raw comparator text

Avoid prose like bare angle-bracket comparisons outside inline code or fenced blocks. Use words such as "at least", "below", or "above" in narrative text.

---

## Resources

### references/

- `evidence_format_spec.md` - schema documentation for evidence files and citation constraints
- `ucb_scoring_criteria.md` - detailed scoring rubric and calibration guidance
- `hypothesis_thematic_categories.md` - category definitions and examples

### assets/

- `hypothesis_report_template.md` - reference markdown presentation for downstream human-readable reports
- `example_hypothesis_ipf.md` - worked IPF example showing target quality level

### Related Skills

- `hypothesis-generation` - general scientific hypothesis generation
- `hypogenic` - automated LLM-driven hypothesis generation on tabular data
- `pubmed-eutils-search` - PubMed search support when extra literature context is needed
- `html-report-generator` - downstream HTML presentation once structured outputs already exist

### evals/

- `evals/evals.json` - trigger, paraphrase, and non-trigger prompt set for PDF-first skill maintenance checks
