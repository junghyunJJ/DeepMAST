---
name: drug-target-hypothesis
description: Generate evidence-backed follow-up recommendations from completed drug target assessment evidence. Use when Stage 1-3 evidence is present, `assessment_results.json.stage3_candidates` is non-empty, and the hypothesis writer needs to produce `evidence/hypothesis_report.json` for downstream reporting. Do not use for general literature-driven hypothesis ideation or dataset classification.
metadata:
    skill-author: Junghyun Jung
    version: 1.0.0
---

# Drug Target Hypothesis Generation

## Overview

Generate conservative evidence-grounded follow-up recommendations from multi-stage drug target assessment evidence. This skill is specialized for the Drug Target Agent's hypothesis-writer runtime: it reads hypothesis-scope evidence, generates downstream experimental or analysis priorities across four thematic categories, validates every cited filename, and persists a structured `hypothesis_report.json` artifact for downstream report writing.

Unlike the general `hypothesis-generation` skill or `hypogenic`, this skill is not a free-form ideation workflow. It is a runtime-aligned contract for evidence-backed follow-up recommendation generation with deterministic save gates.

## When to Use This Skill

Use this skill when:
- Stage 1-3 evidence has already been generated in `{data_dir}/evidence/`
- `assessment_results.json.stage3_candidates` is present and non-empty
- The goal is to produce conservative drug-target follow-up recommendations for downstream reporting
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
2. Build retained follow-up recommendations from the returned files and validate all cited filenames
3. Persist the structured result through `save_hypothesis_report(data_dir=data_dir, report=report)`
Result: A runtime-aligned JSON hypothesis artifact is saved for downstream reporting

Use Case: Deterministic retry after citation rejection
Trigger: "Retry the hypothesis report after `invalid_references`" or "Recover from `failed_pair_violations` in the hypothesis payload"
Steps:
1. Inspect the deterministic rejection returned by `save_hypothesis_report`
2. Remove or repair invalid citations; failed-pair rejections require removing or rebuilding that hypothesis from passed evidence
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
- Do not call `grep` on `/large_tool_results/` paths. After `load_evidence_files`,
  use the returned evidence payload; do not search for `stage3_candidates` with grep.
- Validate all cited filenames with `validate_evidence_references(data_dir, [...])`
- Persist through `save_hypothesis_report(data_dir=data_dir, report=report)`; do not use `save_evidence` as the primary persistence path.

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
| `stage1_{LIGAND}--{RECEPTOR}.json` | Usually | Per-pair biological context; only pairs with `passed=true` load in hypothesis scope |
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
- related eligible `stage1_*.json` pairs returned by hypothesis scope
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

### Phase 1.5: Stage 1 Eligibility Gate (DETERMINISTIC)

Before using any Stage 1 pair as evidence, check its pass/fail status in `stage1_filter_results.json`.

The strict Stage 1 pass condition uses all of the following:
- STRING combined score above 0.8
- coexpression p-value below 0.05
- gene A p-value below 0.05
- gene B p-value below 0.05

Rules:
- Only `passed=true` Stage 1 pairs may be used as hypothesis evidence.
- A `passed=true` Stage 1 pair is not automatically AT2/resolved-cell intrinsic
  support. Read `stage1_pair_usage_guidance`,
  `interest_cell_intrinsic_stage1_pair_files`, and
  `spatial_niche_only_stage1_pair_files` from `load_evidence_files` or
  `validate_evidence_references`.
- Only files in `interest_cell_intrinsic_stage1_pair_files` may support AT2,
  Transitional AT2, pulmonary/alveolar epithelial, or resolved-Census-cell
  intrinsic coexpression claims.
- Files in `spatial_niche_only_stage1_pair_files` must not be used as
  AT2-intrinsic, Transitional-AT2-intrinsic, pulmonary/alveolar
  epithelial-intrinsic, resolved-Census-cell-intrinsic, same-cell, or
  target-cell-autonomous support. If a recommendation mentions the interest
  labels or resolved Census cell type, cite these files only as secondary
  spatial-niche/cross-cell framing evidence with explicit constraints. Cover
  those FEATURED genes with `stage3_<GENE>.json` and `ot_<GENE>.json`; use the
  Stage 1 pair only as constrained secondary framing when the recommendation
  names that pair concept.
- A `passed=false` pair cannot be cited, cannot support a core mechanism claim, and cannot be used as an L-R axis in the title, core claim, or prediction.
- If a failed pair appears in citations or as a primary pair claim, `save_hypothesis_report` rejects the payload with `failed_pair_violations`.
- Fix failed-pair rejections by removing that evidence or rebuilding the hypothesis around a passed pair or gene-level Stage 3 evidence.
- For any passed Stage 1 pair, inspect `census_validation.target_vs_rest` before using it as interest-cell evidence. If coexpression is depleted, or all target-vs-rest diff values are negative, cite that Stage 1 pair only as secondary spatial-niche/cross-cell framing evidence. It must not support AT2, Transitional AT2, pulmonary/alveolar epithelial, resolved-Census-cell intrinsic, same-cell, epithelial-cell-autonomous, or target-cell-autonomous claims. Cover the relevant FEATURED gene with `stage3_<GENE>.json` and `ot_<GENE>.json` for target/actionability support, and use the depleted Stage 1 pair only to constrain the spatial-niche framing.
- Passed but target-cell-depleted Stage 1 pair files may still be cited as secondary spatial-niche/cross-cell framing evidence when the recommendation names that pair concept. They are not AT2-intrinsic support and must not be used for same-cell, epithelial-cell-autonomous, or target-cell-autonomous claims.
- The report renderer uses those secondary citations to populate a secondary Stage 1 framing evidence table, so cite depleted Stage 1 pair files when the recommendation names that pair concept, but only as framing evidence and not as AT2-intrinsic support.

---

### Phase 2: Evidence-Grounded Follow-up Recommendation Generation

Generate an initial set of 4-6 evidence-grounded follow-up recommendations across four mandatory thematic categories. Keep the existing `hypothesis_report.json` schema, but write the content as conservative downstream experimental or analysis recommendations rather than literature-validated causal mechanisms.

Every recommendation should be written so the report can expose four fixed fields:
- **Biological Grounding**: Stage 1/spatial/Census support and the cell-type interpretation.
- **Target-Disease Support**: Stage 2 OpenTargets target-disease support, not causal biology.
- **Actionability**: Stage 3 ChEMBL/drug evidence for actionability, perturbability, or repurposing context, not biological causality.
- **Interpretation Constraint**: primary AT2/epithelial intrinsic support versus secondary spatial-niche/cross-cell framing.

| Category | Focus | Minimum Count |
|----------|-------|:-------------:|
| **Mechanism of Action** | What mechanism should be tested next, without claiming causality unless directly supported | 1 |
| **Therapeutic Strategy** | What intervention or tractability follow-up is worth testing | 1 |
| **Cross-Target Interaction** | Co-observed targets or pathway convergence to evaluate; do not claim synergy without direct evidence | 1 |
| **Novel Pathway** | Unexpected evidence-grounded analysis direction or biological context to investigate | 1 |

Each recommendation must include all seven schema elements:
1. Title with conservative wording
2. Thematic category
3. Core claim as a conservative interpretation
4. Supporting evidence references
5. Key biological entities
6. Falsifiable prediction as a recommended follow-up test
7. Proposed validation approach

Generation guidance:
- Start with FEATURED genes first
- Use hub genes and convergent pathways for cross-target follow-up recommendations
- Use distinctive non-featured genes for novel pathway follow-up recommendations
- Prefer recommendations that integrate multiple evidence types
- Lower intervention-success wording:
  - Avoid `therapeutic intervention candidate` unless clinical/intervention evidence directly supports it; prefer `perturbation/actionability follow-up candidate`.
  - Avoid `synergistic effects` unless direct combination evidence is cited; prefer `additive or non-additive effects`.
  - Avoid statements such as `CD47 blockade alters fibrosis resolution`; prefer `test whether CD47 perturbation changes macrophage-fibroblast readouts`.
- For interest-cell focused reports, mentally split retained recommendations into
  three support classes even though the JSON schema does not require a separate
  tier field:
  - **Primary epithelial/AT2-intrinsic follow-up recommendations**: cite at
    least one `interest_cell_intrinsic_stage1_pair_files` entry and include AT2
    or epithelial validation context.
  - **Secondary epithelial-associated spatial-niche follow-up recommendations**:
    cite at least one Stage 1/spatial pair file that is spatial-niche-only or
    depleted in the resolved epithelial/AT2 cell context. Use this only as
    cross-cell or non-AT2 niche framing, not as epithelial-cell-intrinsic
    target mechanisms.
  - **Gene-level/actionability-only follow-up recommendations**: cite only
    `ot_<GENE>.json`, `stage3_<GENE>.json`, known-drug, or disease-level files.
    If Biological Grounding is `No Stage 1/spatial grounding reference cited`,
    do not label it as spatial-niche. Use title phrases such as `gene-level
    follow-up candidate`, `actionability follow-up candidate`, or
    `perturbation-development candidate`.
- Only use `spatial-niche` when a Stage 1/spatial pair file is cited as
  Biological Grounding or constrained secondary framing evidence.
- Primary epithelial/AT2-intrinsic titles should use language such as `prioritizes`, `nominates`, `follow-up axis`, or `program candidate`.
- Secondary epithelial-associated spatial-niche titles should use language such as `spatial-niche follow-up candidate`, `cross-cell candidate`, or `non-AT2 niche context`.
- Gene-level/actionability-only titles should use language such as `gene-level follow-up candidate`, `actionability follow-up candidate`, or `perturbation-development candidate`.
- Avoid unsupported title phrases such as `drives`, `dysregulation via`, `blockade for reducing`, `barrier dysfunction`, `complex assembly`, and `activation and matrix deposition`.
- In `falsifiable_prediction`, prefer `test whether ... changes` over `should reduce` or `should alter` unless a cited file directly supports that expected direction.
- For asymmetric Stage 2/3 support in a Stage 1 pair, write the recommendation as `<SUPPORTED_GENE>-anchored`. The supported gene is the perturbation or actionability anchor; the unsupported partner is a coexpression-context partner or readout.
- Do not treat the unsupported partner as independently druggable, target-disease-supported, or perturbation-prioritized unless its exact gene-level evidence file is cited.
- Include `Not yet established:` when the recommendation extends beyond direct Stage 1, Stage 3, OpenTargets, ChEMBL, or spatial evidence.

---

### Phase 3: Gap Detection

Build a coverage matrix over eligible hypothesis evidence: passed Stage 1 pair files and current Stage 3 candidate files.

**Step 3.1: Mark referenced evidence**
- Map each evidence file to the hypotheses that cite it

**Step 3.2: Identify orphan evidence**
- Passed Stage 1 pairs not cited anywhere
- FEATURED genes whose Stage 3 evidence is absent from retained hypotheses
- pathway clusters never mentioned

**Step 3.3: Generate supplementary hypotheses**
- Use `[GAP]` for orphan-evidence hypotheses
- Reserve `[FEATURED-GAP]` for the mandatory FEATURED-gene coverage rule in Phase 4.75

**Step 3.4: Coverage target**
- Aim to cover at least 80 percent of eligible hypothesis evidence files
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
4. Keep 4-6 retained recommendations after initial ranking, unless FEATURED coverage requires the lower bound in Phase 4.75
5. Maintain all four thematic categories in the retained set: Mechanism of Action, Therapeutic Strategy, Cross-Target Interaction, and Novel Pathway

If too few retained hypotheses remain to satisfy FEATURED coverage, generate additional hypotheses before rescoring rather than forcing the same underspecified set through save.

See `references/ucb_scoring_criteria.md` for scoring calibration.

### Phase 4.5: Validate Evidence References (MANDATORY)

Before any save attempt, call:

```python
validate_evidence_references(data_dir, all_cited_filenames)
```

Rules:
- Pass one flat combined list containing every filename cited across all hypotheses
- Read `interest_cell_intrinsic_stage1_pair_files` and
  `spatial_niche_only_stage1_pair_files` from the response before saving; these
  are the authoritative whitelist for interest-cell intrinsic Stage 1 usage.
- If validation returns invalid references, replace or remove them
- Never invent filenames
- Stage 1 filenames use the `stage1_<LIGAND>--<RECEPTOR>.json` pattern with two hyphens between the gene symbols
- Re-run validation until it returns `valid: true`

Do not proceed to `save_hypothesis_report` until filename validation is clean.

### Phase 4.75: TOP-N Coverage Gate (DETERMINISTIC)

After ranking and filtering, ensure every gene in `assessment_results.json.stage3_candidates` appears in the retained hypothesis set through `biological_entities.genes`.

Rules:
- For every uncovered FEATURED gene, add one `[FEATURED-GAP]` hypothesis that explicitly includes that gene
- The final retained set must contain 4-6 retained recommendations while covering every FEATURED gene
- Use 6 retained recommendations only when needed for FEATURED coverage or mandatory category balance
- If FEATURED coverage cannot be satisfied within 6 retained recommendations, stop and report the deterministic blocker instead of saving an incomplete payload
- `save_hypothesis_report` computes `topn_coverage` deterministically and rejects the payload if `topn_coverage.missing` is non-empty

This gate is independent from the general orphan-evidence `[GAP]` logic.

---

### Phase 5: Save the Hypothesis Artifact

Persist the output only as structured JSON:

```python
save_hypothesis_report(data_dir=data_dir, report=report)
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

If `save_hypothesis_report` returns `saved: false`:
- For `invalid_references`, remove or replace invalid filenames and validate again
- For `topn_coverage.missing`, add one `[FEATURED-GAP]` hypothesis per missing FEATURED gene
- For `failed_pair_violations`, remove the failed pair citation/claim or rebuild the hypothesis from passed pair or Stage 3 gene evidence
- For `hypothesis_grounding_violations`, apply the exact deterministic repair before retrying:
  - Direct pair-axis violation: remove the unsupported `A-B axis` wording, or cite a matching passed `stage1_A--B.json`/`stage1_B--A.json`. Stage 1 pair filenames may be ligand-receptor ordered and reverse of the prose order; cite the actual available filename returned by validation/load evidence, not a normalized filename you invent. If the rejection names an available reverse-order file, cite that exact file or remove the direct pair-axis wording. Do not infer combinatorial axes from separate hub-partner files.
  - Target-cell-depleted Stage 1 used as interest-cell support: if the hypothesis mentions AT2, Transitional AT2, pulmonary/alveolar epithelial, or the resolved Census cell type anywhere, remove that Stage 1 citation and support the FEATURED gene with `stage3_<GENE>.json`/`ot_<GENE>.json`; otherwise rewrite as non-interest-cell spatial niche evidence.
  - Coexpression-depleted Stage 1 used as intrinsic same-cell support: remove same-cell/intrinsic/AT2-intrinsic wording and AT2 validation, or remove that Stage 1 citation.
  - Target-cell-depleted gene expression claim: remove any statement that the depleted gene is expressed on/in AT2, Transitional AT2, pulmonary alveolar type 2, alveolar epithelial, or pulmonary epithelial cells.

Do not retry the same payload after a deterministic rejection. Change the payload first, then retry.

### Phase 5.6: Last Rejection Sidecar

If a previous save failed, inspect `hypothesis_report_last_rejection.json` when
it is present in the evidence directory. The graph-level retry may surface this sidecar as HYPOTHESIS_LAST_SAVE_REJECTION in the next hypothesis-writer prompt.

Repair the exact saved=false errors before saving again:
- Rebuild only the rejected hypothesis or fields when an index/path is provided.
- Cite real gene-level evidence files or remove unsupported gene mentions.
- Remove unsupported pair-axis wording unless the matching passed Stage 1 pair
  file is cited. If the rejection names an available reverse-order matching file,
  cite that exact available filename or remove the direct pair-axis wording.
- Reframe depleted Stage 1 Census evidence as secondary spatial-niche/cross-cell
  context only when the named pair concept is retained.
- For `target-cell-depleted Stage 1 Census evidence as interest-cell support`,
  choose one repair path for the named hypothesis: keep the depleted Stage 1
  file only after rewriting title, core_claim, prediction, validation_approach,
  and biological_entities.cell_types as secondary spatial-niche/cross-cell or
  non-interest-cell context; or remove that Stage 1 citation and rewrite the
  hypothesis as gene-level/actionability-only. Do not leave depleted Stage 1 in
  a primary AT2/epithelial, interest-cell, same-cell, or intrinsic recommendation.

Do not repeat a rejected payload. Validate references again, then save only the
repaired report.

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

save_hypothesis_report(data_dir=data_dir, report={
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

### Example 2: Failed-pair rejection and recovery

```python
validate_evidence_references(data_dir, [
    "stage1_TGFB1--P4HB.json",
    "stage3_TGFB1.json",
])

save_hypothesis_report(data_dir=data_dir, report=report)
# returns saved: false with failed_pair_violations
```

Correct recovery:
- remove `stage1_TGFB1--P4HB.json` from citations and from the primary mechanism
- rebuild the hypothesis around a passed pair or Stage 3 gene evidence
- then validate again and retry with a changed payload

---

## Quality Standards

Every generated hypothesis report must meet these standards:
- Every claim traces to a specific evidence file and field
- Every hypothesis includes a falsifiable prediction
- The retained set covers the required FEATURED genes
- All dimension scores have short justifications
- No fabricated literature, drug names, or filenames
- Failed pairs are never used as hypothesis evidence or primary mechanism claims

---

## Common Issues

### `stage3_candidates` is empty

Hypothesis generation should stop. This is a zero-featured bypass case, not a reason to invent placeholder hypotheses.

### `validate_evidence_references` returns invalid filenames

Remove or replace the bad filenames. Do not invent new ones. Stage 1 pair filenames always use two hyphens between ligand and receptor.

### `save_hypothesis_report` returns `topn_coverage.missing`

One or more FEATURED genes are uncovered. Add a `[FEATURED-GAP]` hypothesis for each missing gene before retrying.

### `save_hypothesis_report` returns `failed_pair_violations`

You cited a failed Stage 1 pair or made it the primary mechanism. Remove the failed pair evidence or rebuild the hypothesis from passed evidence.

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
