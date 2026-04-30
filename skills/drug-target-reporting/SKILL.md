---
name: drug-target-reporting
description: >
  Generate publication-quality drug target assessment reports (drug.md + HTML)
  from spatial transcriptomics pipeline evidence. Programmatic score injection,
  narrative expansion, hypothesis integration, and quality validation.
  Use for "generate drug report", "write drug.md", "create target assessment",
  "generate drug HTML report", "finalize the drug.md", "render the drug target
  HTML report", "polish the EXPAND markers", "after hypothesis_writer completes
  write the report", "validation failed fix the drug.md".
  Do NOT use for general drug target discussion, literature searches, or
  pipeline execution — only for report generation from completed evidence.
  Do NOT use when evidence files (assessment_results.json, stage3_*.json)
  are absent — skill assumes a pre-filled draft exists.
  Do NOT use to re-score or re-classify targets; scores are authoritative
  inputs, not outputs.
---

# Drug Target Report Writing Skill

## Why This Skill Exists

Drug target assessment reports require precise transcription of rubric scores,
drug profiles, and biological context from evidence files.
LLMs consistently fabricate these values when asked to generate reports freely
(observed with gpt-4.1-mini and gpt-5.4-mini — both hallucinated scores,
GWAS values, and classifications). This skill prevents fabrication by
separating factual data (code-injected) from narrative interpretation (LLM-generated).

## Your Role: NARRATIVE EXPANDER

The drug.md draft already contains ALL correct factual data — scores,
drug names, classifications, pathways, Census results — pre-filled by
`build_evidence_summary`. Your ONLY job is to replace each
`&lt;!-- EXPAND: {instruction} --&gt;` comment with 2-4 sentences of biological
interpretation. You must not modify any pre-filled data.

The reason this boundary matters: scores are pre-computed from 41 genes x 14
rubric dimensions using OpenTargets, ChEMBL, STRING, and CellxGene Census
evidence. Re-deriving them risks inconsistency because you lack access to the
full scoring pipeline. The pre-filled values are the single source of truth.

## Workflow

**Output contract:** On success, returns paths to `drug.md` (always), `drug_report.html` (if Step 4 ran), and a validation pass bit from `validate_drug_md`.

### Step 1: Load Data and Build Draft
```
Call build_evidence_summary(data_dir="{data_dir}", disease="{disease}")
```
This writes a pre-filled drug.md draft to disk and returns a Reference Card
JSON with all evidence data. The draft contains `&lt;!-- EXPAND --&gt;` markers
where narrative is needed.

### Step 2: Read and Expand the Draft
```
Call load_evidence_files(data_dir="{data_dir}")
```
Then read the draft drug.md. For each `&lt;!-- EXPAND: {instruction} --&gt;` marker,
write 2-4 sentences following the instruction. Reference ONLY data visible
in the SAME section of the draft.

### Step 3: Save and Validate
```
Call save_drug_md(data_dir="{data_dir}", content="...")
Call validate_drug_md(data_dir="{data_dir}")
```
If validation fails, fix the identified issues and re-save. Repeat until
validation passes.

### Step 4: Generate HTML Report (Optional)
```
Call generate_drug_html_report(data_dir="{data_dir}")
```
Reads the validated drug.md and produces a self-contained `drug_report.html`
with interactive tabs (Overview, Druggability Matrix, Candidate Deep Dives,
Recommendations), color-coded scores, drug phase badges, and dark/light theme
toggle. Uses the same CSS theme as CCI analysis reports. The HTML file embeds
all CSS and JS inline — no external dependencies.

## Evidence Hierarchy

When interpreting data, trust sources in this order:

1. **Reference Card values** (scores, drug names, classifications) — ALWAYS authoritative
2. **Evidence files** via load_evidence_files — supplementary detail for narrative
3. **"Data not available"** — the correct response when Reference Card has no value
4. **General knowledge** — NEVER use to fill data gaps

This hierarchy exists because the Reference Card is computed deterministically
from evidence files, while general knowledge introduces unverifiable claims.

## Score Interpretation Calibration

Use this table to calibrate your narrative tone to the evidence strength.
The combined_total is the sum of validated_total + exploratory_total.

Read `classification` from the Reference Card first; pick the row whose Classification Field Value matches. Do not infer from `combined_total` alone — rows 3 and 4 share the same 5-9 combined range and diverge only on the `classification` field.

| Combined Total | Classification Field Value | Interpretation Tone |
|---|---|---|
| ≥ 15 | `classification == "validated_target"` | "Strong validated target with substantial clinical evidence supporting drug development" |
| 10-14 | `classification == "validated_target"` | "Promising target with moderate clinical and exploratory support warranting further investigation" |
| 5-9 | `classification == "exploratory_target"` | "Early-stage target with exploratory evidence requiring additional validation" |
| 5-9 | `classification == "novel_candidate"` | "Novel target from spatial transcriptomics; biological plausibility supports further validation" |
| &lt; 5 | `classification == "insufficient_evidence"` | "Insufficient evidence for current prioritization; data gaps should be addressed" |

| Priority | Recommendation Template |
|---|---|
| high | "Recommend prioritization for preclinical/clinical development pipeline" |
| medium | "Consider for secondary development track pending additional evidence" |
| low | "Monitor for emerging evidence; not recommended for immediate development" |
| low (novel) | "Early-stage novel target; monitor for emerging evidence" |
| unranked | "Insufficient data for development recommendation" |

*Thresholds (15/10/5) are based on the empirical distribution of combined_total
across 41 genes in pilot IPF and breast cancer datasets. Genes above 15 consistently
had Phase 2+ clinical evidence; below 5 had no clinical or genetic support.*

When a gene's combined_total falls on a boundary (e.g., 10), present both interpretations
rather than choosing one: "This target shows moderate validated evidence (combined=10),
at the threshold between high and medium priority classification."

## Section-Specific Grounding Rules

Each deep dive section has its own data source. Using the wrong source
introduces fabrication risk because the LLM fills gaps from training data.

### A. Drug Profile
- ONLY list drugs from Reference Card `stage3.clinical_drugs` and `stage3.preclinical_compounds`
- If Reference Card has no drugs: write "No known drugs identified in ChEMBL or OpenTargets for this gene"
- Explain WHY no drugs were found if applicable (e.g., "antibody target without small-molecule bioactivity data")

### B. Biological Context
- ONLY report STRING scores, KEGG/Reactome pathways, Census values from Reference Card `stage1_pairs`
- If no Stage 1 data: write "No Stage 1 biological context data available for this gene"
- Report STRING combined score, Census p-values, and pathway associations verbatim

### D. Rubric Assessment
- COPY all scores as integers directly from Reference Card `rubric` object
- COPY classification and priority labels verbatim — do not re-derive them
- Therapeutic recommendation MUST use the Score Interpretation Calibration table above

### E. Biological Interaction Filter Results (Section 2.1)
- This section is PRE-FILLED by the template — the table and legend are code-generated
- Your ONLY job is to expand the `&lt;!-- EXPAND --&gt;` marker with 2-3 sentences interpreting:
  - How many L-R pairs passed vs. failed Stage 1 validation
  - Which biological signals (STRING PPI, Census coexpression) drove pass/fail decisions
  - What the filter results imply for target prioritization
- Do NOT modify the table data, column headers, or filter criteria legend
- Reference ONLY the values visible in the same table (STRING scores, p-values, risk ratios)
- Use hedged language for interpretation ("suggests", "indicates", "consistent with")

### Domain-Specific Accuracy Guards

These edge cases cause frequent errors. Check for them before writing narrative.

| Edge Case | Common Error | Correct Handling |
|---|---|---|
| Prodrugs | Report prodrug name as active drug | Report the ACTIVE metabolite form |
| Phase across indications | max_phase=4 for HIV, but Phase 0 for IPF | Only report phase for the TARGET disease indication |
| Safety score sign | Interpret -3 as "score of 3" | safety_profile is NEGATIVE: -3 = major concerns, 0 = minimal |
| Antibody targets | Claim "no drugs" for CD47 | CD47 has antibody drugs (magrolimab) — check OpenTargets clinical_drugs, not just ChEMBL IC50 |

## Hallucination Prevention

These rules exist because LLMs consistently fabricate specific data types
when generating scientific reports. Each rule addresses an observed failure mode.

| Data Type | Failure Observed | Rule | Correct Action |
|---|---|---|---|
| Rubric scores | CD4: JSON=16, drug.md=9 | Copy integers verbatim | Read from Reference Card `rubric` |
| GWAS values | All 0 in data, reported as 1-3 | Copy exactly as-is | If Reference Card says 0, write 0 |
| Classifications | validated_target → exploratory_target | Copy exact string | Read from Reference Card `classification` |
| Drug names | Invented drug names | Only use provided names | Read from Reference Card `clinical_drugs` |
| Pathways | Inferred from general knowledge | Only cite evidence pathways | Read from Reference Card `kegg_pathways` |
| FDA approval year | `ocriplasmin (approved 2010)` — fabricated; `first_approval` field absent in `resolved_drugs.json` | Year may be stated only when `first_approval` field is present | Read year from `resolved_drugs.json[*].first_approval`; otherwise omit the year |
| Mechanism of action | `lovastatin disrupts ITGB2 signaling` — `mechanism_of_action` field empty for that drug | Mechanism phrase requires non-empty `mechanism_of_action` field with overlapping keyword | Read from `resolved_drugs.json[*].mechanism_of_action`; otherwise omit the mechanism phrase |
| File reference | `[from known_drugs.json]` — file does not exist; or `stage1_HLA-DPA1--CD4.json_FAILED` — `_FAILED` suffix never valid | Bracket and bare-filename references must point to a real file in `evidence_dir`; never use `*_FAILED` suffix | Reference only files present in `evidence_dir`; cite by exact filename |
| Sentence-level provenance | `lovastatin's known safety profile and oral bioavailability could enable rapid translation` — no source field anchors this sentence | Every prose sentence in `<!-- EXPAND -->` must carry `[source: <field>]` annotation; `interpretation` annotation allowed only with hedged language | Append `[source: <field>]` per sentence; use `[source: interpretation]` only with `suggests`/`indicates`/`consistent with` |

## Closed-Book Generation

Every factual claim written inside an `<!-- EXPAND -->` region must trace to a named field in the per-gene source bundle (Reference Card, `resolved_drugs.json`, `stage1_pairs`, etc.). If the supporting field is absent or empty, emit `"not available in source data"` or omit the sentence entirely. Do not draw on training-data knowledge to fill the gap.

**Annotation rule:** Append `[source: <field>]` (one or more fields, comma-separated) to every prose sentence inside `<!-- EXPAND -->` regions. Multiple fields may be listed: `[source: molecule_type, mechanism_of_action]`. Annotations are stripped from the saved drug.md by post-processing — they are validator/critic-only markers and are never visible to end-users.

`[source: interpretation]` is allowed only when the sentence uses hedged language: `suggests`, `indicates`, `consistent with`, or `implies`. Using `[source: interpretation]` on a sentence with definitive language (`confirms`, `proves`, `drives`) is a hallucination risk and is forbidden.

**Example with annotations:**
```
Ibalizumab is a CD4-binding monoclonal antibody [source: molecule_type, mechanism_of_action].
```

## EXPAND Marker Rules

- Each `&lt;!-- EXPAND: {instruction} --&gt;` MUST be replaced with 2-4 sentences
- Sentences MUST reference data visible in the SAME section
- Do NOT cross-reference data from other gene sections
- Use hedged language ("suggests", "indicates", "consistent with") for interpretations
- Use definitive language ("has", "shows", "contains") only for pre-filled data
- When evidence is absent, acknowledge the gap rather than filling it
- Do NOT speculate about repurposing potential, disease-specific applicability, or therapeutic opportunities unless the evidence files explicitly contain data supporting that claim
- Do NOT extrapolate from a drug's approved indication to the target disease
- State what drugs are approved for; do not infer what they might do for the study disease

## Examples

### Example 1: Correct EXPAND Expansion (CD4 Deep Dive)

**Before (pre-filled draft):**
```
### [FEATURED] CD4 — Classification: validated_target | Priority: high

**A. Drug Profile**
**Clinical Compounds:**
- **IBALIZUMAB** (CHEMBL1743029) — Antibody | Phase 4 | Indications: HIV infection
- **TREGALIZUMAB** (CHEMBL1743083) — Antibody | Phase 2 | Indications: rheumatoid arthritis

<!-- EXPAND: Interpret the drug landscape for CD4 in the context of idiopathic pulmonary fibrosis. Note that existing drugs target CD4 for other indications. -->
```

**After (proposed):**
```
CD4-targeting therapeutics include ibalizumab and tregalizumab (both monoclonal antibodies per Reference Card `molecule_type`). Ibalizumab is listed at Phase 4 for HIV infection; no approval year is stated because the Reference Card has no `first_approval` field for it. These agents have not been evaluated in pulmonary fibrosis, confirming CD4 is druggable via antibody-based approaches.
```

**WRONG (forbidden):**
```
ibalizumab (approved 2018 for HIV)  ← fabricated; first_approval absent
```

### Example 2: Incorrect Expansion (Hallucinated)

**BAD — fabricates a drug not in the Reference Card:**
```
CD4-targeting drugs include ibalizumab and **zanubrutinib**, a BTK inhibitor
showing promise in fibrotic diseases.
```
Why wrong: zanubrutinib targets BTK, not CD4, and is not in the Reference Card.

### Example 3: Correct "Data Not Available" Handling

When Reference Card has `clinical_drugs: []` and `gwas_variants: 0`, do not fill the gap with general knowledge. Report the absence explicitly.

**Pre-filled draft fragment:**
```
### COL1A1 — Classification: exploratory_target | Priority: medium

**A. Drug Profile**
**Clinical Compounds:** (none)
**Preclinical Compounds:** (none)

**GWAS Catalog Associations:** 0 variants
```

**Correctly expanded:**
```
No clinical compounds are listed in ChEMBL or OpenTargets for COL1A1, and GWAS Catalog
reports no variants associated with the target disease. This evidence gap warrants
primary screening rather than repurposing; extracellular matrix proteins are historically
challenging to drug with small molecules, which is consistent with the empty drug
landscape here.
```
Why correct: every factual claim is anchored to the Reference Card's explicit zeros; the final sentence hedges ("is consistent with") without asserting unsupported mechanism.

### Example 4: Hedged vs Definitive Language

Use definitive verbs ("has", "shows", "contains") ONLY for pre-filled Reference Card data. Use hedged verbs ("suggests", "indicates", "consistent with") for LLM-generated narrative interpretation.

**Correct mix (COL1A1 Biological Context):**
```
STRING combined score **has** a value of 0.82 for COL1A1-ITGB1 (pre-filled). Census
co-expression p-value **shows** 1.2e-4 across fibroblast populations (pre-filled).
Together these signals **suggest** that COL1A1-ITGB1 interaction is active in the
fibrotic niche and **are consistent with** a role in ECM remodeling.
```
Why correct: numeric values use "has"/"shows" (definitive, anchored to data); biological interpretation uses "suggest"/"consistent with" (hedged, flags as LLM inference).

**Incorrect (inverted hedging):**
```
STRING combined score **suggests** ~0.82 for COL1A1-ITGB1. Census co-expression
p-value **indicates** roughly 1.2e-4. These signals **confirm** that COL1A1-ITGB1
**drives** fibrosis.
```
Why wrong: hedges the factual data ("~0.82", "roughly 1.2e-4") as if uncertain, then upgrades LLM inference ("confirm", "drives") to definitive — the exact inversion that fuels hallucination.

## Quality Self-Check

Before saving the final drug.md, verify:
- [ ] Every score in the druggability matrix matches Reference Card
- [ ] Every classification label matches Reference Card
- [ ] Every drug name appears in the Reference Card drugs list
- [ ] No `&lt;!-- EXPAND --&gt;` markers remain unexpanded
- [ ] GWAS values are exactly as in Reference Card (likely 0)
- [ ] All deep dive sections have content (not "Data not available" if data exists)
- [ ] `combined_total` equals `validated_total + exploratory_total` (no arithmetic drift)
- [ ] Disease phase reported is for the TARGET indication (not an approved different indication)
- [ ] `safety_profile` sign preserved (negative scores not rendered as positive)
- [ ] Cell types cited appear in `stage1_pairs` (not inferred from general knowledge)
- [ ] No FDA approval year stated without `first_approval` source field
- [ ] No mechanism description without `mechanism_of_action` source field
- [ ] No `[from X.json]` or bare `stageN_*.json` reference to a non-existent or `*_FAILED` file
- [ ] Every prose sentence in EXPAND regions carries `[source: <field>]` annotation

## Troubleshooting

### `build_evidence_summary` returns error
**Cause:** Missing evidence files (assessment_results.json, stage3_*.json)
**Solution:** Verify evidence_assessor completed Stages 1-3. Run `load_evidence_files(data_dir)` to check file list.

### `validate_drug_md` reports WRONG_CLASSIFICATION
**Cause:** Classification label doesn't match assessment_results.json
**Solution:** Copy the exact classification string from the Reference Card rubric object.

### Remaining `&lt;!-- EXPAND --&gt;` markers after save
**Cause:** Some EXPAND markers were not replaced
**Solution:** Search for `&lt;!-- EXPAND` in the document and replace each with 2-4 sentences per the instruction.

### `validate_drug_md` reports WRONG_SCORE
**Cause:** A numeric score in drug.md does not match the Reference Card `rubric` object (e.g., CD4 assessment_results.json = 16 but drug.md renders 9 — the pattern that originally motivated this skill).
**Solution:** Re-read the Reference Card `rubric` for the flagged gene, copy each integer verbatim (no rounding, no re-deriving from components), and re-save. Do not reinterpret — the pre-computed value is authoritative.

### `validate_drug_md` reports FABRICATED_DRUG
**Cause:** A drug name in drug.md does not appear in Reference Card `stage3.clinical_drugs` or `stage3.preclinical_compounds`.
**Solution:** Remove the fabricated drug. If the Reference Card lists no drugs for the gene, write "No known drugs identified in ChEMBL or OpenTargets for this gene" — never substitute a remembered drug name.

### Validation loop diverges (repeated `validate_drug_md` failures)
**Cause:** Re-save attempts keep failing validation. The underlying data gap or contradiction cannot be resolved by rewriting narrative.
**Solution:** After 3 consecutive re-save attempts on the same gene or section, STOP. Return the list of unresolved issues to the orchestrator with each issue's type, affected gene, and the Reference Card excerpt you were trying to honor. Do not loop indefinitely — upstream evidence must be corrected before the report can pass.

`references/scoring_guide.md` is a **REQUIRED read when** (a) a gene sits on a score boundary (e.g., combined_total = 10 or 5), (b) the classification label seems inconsistent with `combined_total`, or (c) the therapeutic recommendation requires explaining priority derivation. **OPTIONAL** otherwise. Call `read_skill_file("skills/drug-target-reporting/references/scoring_guide.md")` directly when the trigger conditions hold.
