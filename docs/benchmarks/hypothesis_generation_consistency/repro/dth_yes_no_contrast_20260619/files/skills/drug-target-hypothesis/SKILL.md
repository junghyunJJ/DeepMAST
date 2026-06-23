---
name: drug-target-hypothesis
description: Generate evidence-backed follow-up recommendations from completed drug target assessment evidence. Use when Stage 1-3 evidence is present, `assessment_results.json.stage3_candidates` is non-empty, and the hypothesis writer needs to produce `evidence/hypothesis_report.json` for downstream reporting. Do not use for general literature-driven hypothesis ideation or dataset classification.
metadata:
    skill-author: Junghyun Jung
    version: 1.2.0
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

This skill is also the intended contrastive advantage over the base hypothesis
writer prompt. Do not assume the base prompt already knows the evidence-class
rules below. When this skill is loaded, make the output visibly better by
classifying evidence support, stating claim boundaries, and choosing follow-up
language that matches the support class.

---

## Small-Model DTH Decision Card

Use this card before reading the longer workflow, especially for 35B and 122B
models. The base prompt should only make a valid artifact; this skill should
make the DTH-loaded output visibly better.

### Step 1: Build two inventories first

- `cell_context_anchor`: use
  `hypothesis_writer_contract.required_cell_context_anchor` when present;
  otherwise use the original interest cell label plus the resolved Census cell
  type from `celltype_resolution.json`.
- `allowed_direct_pair_axes`: use
  `hypothesis_writer_contract.allowed_direct_pair_axes` when present; otherwise
  use only usable passed `stage1_*.json` files returned by hypothesis scope or
  accepted by `validate_evidence_references`.

Do not create pair axes by combining genes from separate files, shared pathway
mentions, hub context, or skill-guide prose.

### Step 2: Choose exactly one support class for each recommendation

| Support class | Required evidence | Use this wording | Do not write |
| --- | --- | --- | --- |
| Interest-cell intrinsic | A cited Stage 1 file in `interest_cell_intrinsic_stage1_pair_files` and the resolved Census cell type named in validation | `interest-cell intrinsic follow-up`, `same-cell validation readout`, `resolved-cell coexpression follow-up` | direct intrinsic wording without the exact Stage 1 file and cell label |
| Secondary spatial-niche or cross-cell | A cited Stage 1 file that is spatial-only, target-cell-depleted, or coexpression-depleted | `secondary spatial-niche context`, `cross-cell framing`, `non-intrinsic readout` | `same-cell`, `cell-autonomous`, `intrinsic`, or target-cell expression claims |
| Gene-level/actionability-only | `stage3_<GENE>.json`, `ot_<GENE>.json`, known-drug, or disease-level target files | `gene-level follow-up`, `actionability readout`, `perturbation-development candidate` | spatial, same-cell, direct pair, or cell-context claims |

If a FEATURED gene is linked only to depleted or spatial-only Stage 1 evidence,
prefer the Gene-level/actionability-only class and cite `stage3_<GENE>.json`
plus `ot_<GENE>.json`.

### Step 3: Add the DTH quality signature

Every retained recommendation should visibly include this DTH quality signature:
- evidence class: one of the three support classes above
- claim boundary: what the cited files support and what remains unproven
- target rationale: why the named target gene is prioritized
- follow-up readout: perturbation, actionability, validation, or combination
  readout
- limitation: one unresolved boundary when the claim extends beyond direct
  evidence

### Step 4: Use class-specific repair on save rejection

| Save error | Exact repair |
| --- | --- |
| `topn_coverage.missing` | Add one `[FEATURED-GAP]` recommendation per missing FEATURED gene using `stage3_<GENE>.json` and `ot_<GENE>.json`; do not force a depleted Stage 1 pair into intrinsic wording. |
| Unsupported direct pair axis | Cite the exact matching passed Stage 1 filename named by validation, including reverse ligand-receptor order, or remove all direct pair wording and rewrite as a single-gene follow-up. |
| Failed Stage 1 pair | Remove the failed file and rebuild from a passed pair or gene-level evidence. |
| Coexpression-depleted or target-cell-depleted Stage 1 used as intrinsic support | Reclassify as Secondary spatial-niche or cross-cell, or remove the Stage 1 citation and rebuild as Gene-level/actionability-only. |
| Invalid filename | Replace with an exact filename returned by `load_evidence_files` or accepted by `validate_evidence_references`; never invent a filename. |

After a rejection, change only the rejected hypothesis or field when the error
names a location. Validate references again, then save the changed payload.

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

Before drafting any recommendation, build two local control inventories from the
loaded hypothesis-scope payload. Prefer `hypothesis_writer_contract` when
present; it is the canonical save-gate contract, and DTH interpretation must not
override it.
- `cell_context_anchor`: copy
  `hypothesis_writer_contract.required_cell_context_anchor` exactly when present;
  otherwise use the exact original interest cell label and resolved Census cell
  type from `celltype_resolution.json`. If the match mode is `semantic_proxy`,
  describe Census support as proxy validation for the resolved Census cell type
  and do not claim Census validated lost state modifiers from the original label.
- `allowed_direct_pair_axes`: exact pair keys and filenames from
  `hypothesis_writer_contract.allowed_direct_pair_axes` when present, otherwise
  usable `stage1_*.json` files returned by hypothesis scope or accepted by
  `validate_evidence_references`. Do not infer new direct pair axes by combining
  genes from separate Stage 1 files, Stage 2/3 gene evidence, shared pathways,
  hub context, or co-listed entities.

Before drafting each recommendation, apply this DTH evidence decision tree:
- **Interest-cell intrinsic pair**: if the pair is in
  `interest_cell_intrinsic_stage1_pair_files`, direct pair or coexpression
  wording is allowed only when the same hypothesis cites the exact Stage 1 file
  and names the resolved Census cell type in validation.
- **Spatial-niche-only or coexpression-depleted pair**: do not use it as
  malignant-cell intrinsic, same-cell, cell-autonomous, or direct pair-axis
  support. Use it only as constrained secondary spatial-niche or cross-cell
  context when the pair concept is retained.
- **Gene-level/actionability support**: use `stage3_<GENE>.json` and
  `ot_<GENE>.json` to cover FEATURED genes without forcing pair-level claims.
  This is the preferred repair when the only Stage 1 pair for a FEATURED gene is
  spatial-niche-only or coexpression-depleted.

If a hypothesis cites a file from `interest_cell_intrinsic_stage1_pair_files`,
the same hypothesis must name the exact resolved Census cell type in
`biological_entities.cell_types` and in `validation_approach`. If the original
interest label differs from the resolved Census cell type, you may mention both,
but the resolved Census cell type is the required anchor for Stage 1 support.

### Phase 1.5: Stage 1 Eligibility Gate (DETERMINISTIC)

Before using any Stage 1 pair as evidence, check its pass/fail status in `stage1_filter_results.json`.

The strict Stage 1 pass condition uses all of the following:
- STRING combined score above 0.8
- coexpression p-value below 0.05
- gene A p-value below 0.05
- gene B p-value below 0.05

Rules:
- Only `passed=true` Stage 1 pairs may be used as hypothesis evidence.
- A `passed=true` Stage 1 pair is not automatically interest-cell intrinsic
  support. Read `stage1_pair_usage_guidance`,
  `interest_cell_intrinsic_stage1_pair_files`, and
  `spatial_niche_only_stage1_pair_files` from `load_evidence_files` or
  `validate_evidence_references`.
- Only files in `interest_cell_intrinsic_stage1_pair_files` may support
  same-cell, intrinsic, target-cell-autonomous, or resolved-Census-cell
  coexpression claims.
- Files in `spatial_niche_only_stage1_pair_files` must not be used as
  same-cell, intrinsic, resolved-Census-cell-intrinsic, cell-autonomous, or
  target-cell-autonomous support. If a recommendation mentions the interest
  labels or resolved Census cell type, cite these files only as secondary
  spatial-niche/cross-cell framing evidence with explicit constraints. Cover
  those FEATURED genes with `stage3_<GENE>.json` and `ot_<GENE>.json`; use the
  Stage 1 pair only as constrained secondary framing when the recommendation
  names that pair concept.
- A `passed=false` pair cannot be cited, cannot support a core mechanism claim, and cannot be used as an L-R axis in the title, core claim, or prediction.
- If a failed pair appears in citations or as a primary pair claim, `save_hypothesis_report` rejects the payload with `failed_pair_violations`.
- Fix failed-pair rejections by removing that evidence or rebuilding the hypothesis around a passed pair or gene-level Stage 3 evidence.
- For any passed Stage 1 pair, inspect `census_validation.target_vs_rest` before using it as interest-cell evidence. If coexpression is depleted, or all target-vs-rest diff values are negative, cite that Stage 1 pair only as secondary spatial-niche/cross-cell framing evidence. It must not support resolved-Census-cell intrinsic, same-cell, cell-autonomous, or target-cell-autonomous claims. Cover the relevant FEATURED gene with `stage3_<GENE>.json` and `ot_<GENE>.json` for target/actionability support, and use the depleted Stage 1 pair only to constrain the spatial-niche framing.
- Passed but target-cell-depleted Stage 1 pair files may still be cited as secondary spatial-niche/cross-cell framing evidence when the recommendation names that pair concept. They are not intrinsic interest-cell support and must not be used for same-cell, cell-autonomous, or target-cell-autonomous claims.
- The report renderer uses those secondary citations to populate a secondary Stage 1 framing evidence table, so cite depleted Stage 1 pair files when the recommendation names that pair concept, but only as framing evidence and not as interest-cell-intrinsic support.

---

### Phase 2: Evidence-Grounded Follow-up Recommendation Generation

Generate an initial set of 4-6 evidence-grounded follow-up recommendations across four mandatory thematic categories. Keep the existing `hypothesis_report.json` schema, but write the content as conservative downstream experimental or analysis recommendations rather than literature-validated causal mechanisms.

Every recommendation should be written so the report can expose four fixed fields:
- **Biological Grounding**: Stage 1/spatial/Census support and the cell-type interpretation.
- **Target-Disease Support**: Stage 2 OpenTargets target-disease support, not causal biology.
- **Actionability**: Stage 3 ChEMBL/drug evidence for actionability, perturbability, or repurposing context, not biological causality.
- **Interpretation Constraint**: primary interest-cell intrinsic support versus secondary spatial-niche/cross-cell framing.

When this skill is loaded, each retained recommendation should have a visible
DTH quality signature in its title, core claim, prediction, or validation
approach:
1. evidence class: intrinsic pair, spatial-niche/cross-cell, or gene-level/actionability
2. claim boundary: what the evidence supports and what remains unproven
3. follow-up readout: a perturbation, actionability, or validation readout
4. target rationale: why the named target/gene is prioritized
5. limitation: one unresolved boundary when the claim extends beyond direct evidence

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
  - Avoid statements such as `target blockade resolves disease`; prefer `test whether target perturbation changes disease-relevant readouts`.
- For interest-cell focused reports, mentally split retained recommendations into
  three support classes even though the JSON schema does not require a separate
  tier field:
  - **Primary interest-cell intrinsic follow-up recommendations**: cite at
    least one `interest_cell_intrinsic_stage1_pair_files` entry and include the
    original interest cell label or resolved Census cell type in the validation
    context.
  - **Secondary interest-cell-associated spatial-niche follow-up recommendations**:
    cite at least one Stage 1/spatial pair file that is spatial-niche-only or
    depleted in the resolved cell context. Use this only as cross-cell or
    non-interest-cell niche framing, not as interest-cell-intrinsic
    target mechanisms.
  - **Gene-level/actionability-only follow-up recommendations**: cite only
    `ot_<GENE>.json`, `stage3_<GENE>.json`, known-drug, or disease-level files.
    If Biological Grounding is `No Stage 1/spatial grounding reference cited`,
    do not label it as spatial-niche. Use title phrases such as `gene-level
    follow-up candidate`, `actionability follow-up candidate`, or
    `perturbation-development candidate`.
- Only use `spatial-niche` when a Stage 1/spatial pair file is cited as
  Biological Grounding or constrained secondary framing evidence.
- Primary interest-cell intrinsic titles should use language such as `prioritizes`, `nominates`, `follow-up axis`, or `program candidate`.
- Secondary interest-cell-associated spatial-niche titles should use language such as `spatial-niche follow-up candidate`, `cross-cell candidate`, or `non-interest-cell niche context`.
- Gene-level/actionability-only titles should use language such as `gene-level follow-up candidate`, `actionability follow-up candidate`, or `perturbation-development candidate`.
- Avoid unsupported title phrases such as `drives`, `dysregulation via`, `blockade for reducing`, `barrier dysfunction`, `complex assembly`, and `activation and matrix deposition`.
- In `falsifiable_prediction`, prefer `test whether ... changes` over `should reduce` or `should alter` unless a cited file directly supports that expected direction.
- For asymmetric Stage 2/3 support in a Stage 1 pair, write the recommendation as `<SUPPORTED_GENE>-anchored`. The supported gene is the perturbation or actionability anchor; the unsupported partner is a coexpression-context partner or readout.
- Do not treat the unsupported partner as independently druggable, target-disease-supported, or perturbation-prioritized unless its exact gene-level evidence file is cited.
- Do not write `A-B axis`, `A/B interaction`, `A-B signaling`,
  `A-B coexpression`, or equivalent direct pair wording unless `A--B` or `B--A`
  is present in `allowed_direct_pair_axes` and the exact matching passed Stage 1
  filename is cited in that same hypothesis. If the desired pair is absent from
  `allowed_direct_pair_axes`, rewrite as `<SUPPORTED_GENE>-anchored`
  gene-level/actionability follow-up and mention the uncited partner only as
  context, not as a direct mechanism.
- Do not list a partner gene in `biological_entities.genes` unless the same hypothesis cites `ot_<GENE>.json`, `stage3_<GENE>.json`, or a Stage 1 pair file containing that gene. If an uncited partner is biologically useful, mention it only as context in prose and label it `context only, not independently supported by cited evidence`.
- OpenTargets known-drug evidence and Stage 3 ChEMBL matched-drug evidence are distinct. If `ot_<GENE>.json` contains known-drug programs, attribute those drugs to OpenTargets. If `stage3_<GENE>.json` has empty `matched_drugs`, do not describe that file as ChEMBL drug, ChEMBL compound, or matched-drug support; say Stage 3 provides no matched ChEMBL drug evidence for that gene.
- Avoid disease-resolution claims in hypothesis titles and avoid treating exploratory perturbation readouts as therapeutic outcomes. Prefer disease-relevant cellular or molecular readouts named in the local evidence.
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
- FEATURED gene coverage is independent from pair-level Stage 1 support. A
  FEATURED gene can be covered by `stage3_<GENE>.json` plus `ot_<GENE>.json`
  even when no valid interest-cell intrinsic pair supports that gene.
- Do not reintroduce spatial-niche-only or coexpression-depleted Stage 1 files
  as intrinsic support just to satisfy FEATURED coverage.

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
- For `topn_coverage.missing`, add one `[FEATURED-GAP]` hypothesis per missing
  FEATURED gene. Prefer gene-level/actionability evidence
  (`stage3_<GENE>.json` and `ot_<GENE>.json`) when the missing gene's Stage 1
  pair support is spatial-niche-only, coexpression-depleted, absent, or would
  require an unsupported direct pair claim.
- For `failed_pair_violations`, remove the failed pair citation/claim or rebuild the hypothesis from passed pair or Stage 3 gene evidence
- For `hypothesis_grounding_violations`, apply the exact deterministic repair before retrying:
  - Direct pair-axis violation: remove the unsupported `A-B axis` wording, or cite a matching passed `stage1_A--B.json`/`stage1_B--A.json`. Stage 1 pair filenames may be ligand-receptor ordered and reverse of the prose order; cite the actual available filename returned by validation/load evidence, not a normalized filename you invent. If the rejection names an available reverse-order file, cite that exact file or remove the direct pair-axis wording. Do not infer combinatorial axes from separate hub-partner files.
  - If a direct pair-axis rejection reports `canonical_existing=none` or
    `available: no matching Stage 1 pair file exists`, do not try to repair by
    inventing a filename. Remove the direct pair wording and rebuild the
    recommendation as gene-level/actionability-only or as a supported-pair
    recommendation using an allowed direct pair from `allowed_direct_pair_axes`.
  - Target-cell-depleted Stage 1 used as interest-cell support: if the hypothesis mentions the original interest label or resolved Census cell type anywhere, remove that Stage 1 citation and support the FEATURED gene with `stage3_<GENE>.json`/`ot_<GENE>.json`; otherwise rewrite as non-interest-cell spatial niche evidence.
  - Coexpression-depleted Stage 1 used as intrinsic same-cell support: remove
    same-cell/intrinsic/target-cell-autonomous wording and interest-cell
    validation, or remove that Stage 1 citation. If removing the citation makes
    a FEATURED gene uncovered, immediately add or revise a gene-level/actionability
    hypothesis for that gene using exact `stage3_<GENE>.json` and `ot_<GENE>.json`
    evidence instead of restoring the depleted Stage 1 citation.
  - Target-cell-depleted gene expression claim: remove any statement that the depleted gene is expressed in or on the original interest cell label or resolved Census cell type.

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
  a primary interest-cell, same-cell, cell-autonomous, or intrinsic recommendation.

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

One or more FEATURED genes are uncovered. Add a `[FEATURED-GAP]` hypothesis for
each missing gene before retrying. If the missing gene is linked only through a
spatial-niche-only or coexpression-depleted Stage 1 pair, cover it with
gene-level `stage3_<GENE>.json` and `ot_<GENE>.json` evidence instead of forcing
that Stage 1 pair into an intrinsic claim.

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
