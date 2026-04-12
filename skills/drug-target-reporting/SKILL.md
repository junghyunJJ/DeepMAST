---
name: drug-target-reporting
description: >
  Generate publication-quality drug target assessment reports (drug.md + HTML)
  from spatial transcriptomics pipeline evidence. Programmatic score injection,
  narrative expansion, hypothesis integration, and quality validation.
  Use for "generate drug report", "write drug.md", "create target assessment",
  "generate drug HTML report".
  Do NOT use for general drug target discussion, literature searches, or
  pipeline execution — only for report generation from completed evidence.
---

# Drug Target Report Writing Skill

## Why This Skill Exists

Drug target assessment reports require precise transcription of rubric scores,
drug profiles, PMID citations, and biological context from evidence files.
LLMs consistently fabricate these values when asked to generate reports freely
(observed with gpt-4.1-mini and gpt-5.4-mini — both hallucinated scores,
GWAS values, and classifications). This skill prevents fabrication by
separating factual data (code-injected) from narrative interpretation (LLM-generated).

## Your Role: NARRATIVE EXPANDER

The drug.md draft already contains ALL correct factual data — scores, PMIDs,
drug names, classifications, pathways, Census results — pre-filled by
`build_evidence_summary`. Your ONLY job is to replace each
`<!-- EXPAND: {instruction} -->` comment with 2-4 sentences of biological
interpretation. You must not modify any pre-filled data.

The reason this boundary matters: scores are pre-computed from 41 genes x 14
rubric dimensions using OpenTargets, ChEMBL, STRING, and CellxGene Census
evidence. Re-deriving them risks inconsistency because you lack access to the
full scoring pipeline. The pre-filled values are the single source of truth.

## Workflow

### Step 1: Load Data and Build Draft
```
Call build_evidence_summary(data_dir="{data_dir}", disease="{disease}")
```
This writes a pre-filled drug.md draft to disk and returns a Reference Card
JSON with all evidence data. The draft contains `<!-- EXPAND -->` markers
where narrative is needed.

### Step 2: Read and Expand the Draft
```
Call load_evidence_files(data_dir="{data_dir}")
```
Then read the draft drug.md. For each `<!-- EXPAND: {instruction} -->` marker,
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

1. **Reference Card values** (scores, PMIDs, drug names) — ALWAYS authoritative
2. **Evidence files** via load_evidence_files — supplementary detail for narrative
3. **"Data not available"** — the correct response when Reference Card has no value
4. **General knowledge** — NEVER use to fill data gaps

This hierarchy exists because the Reference Card is computed deterministically
from evidence files, while general knowledge introduces unverifiable claims.

## Score Interpretation Calibration

Use this table to calibrate your narrative tone to the evidence strength.
The combined_total is the sum of validated_total + exploratory_total.

| Combined Total | Classification | Interpretation Tone |
|---|---|---|
| >= 15 | validated_target | "Strong validated target with substantial clinical evidence supporting drug development" |
| 10-14 | validated_target | "Promising target with moderate clinical and exploratory support warranting further investigation" |
| 5-9 | exploratory_target | "Early-stage target with exploratory evidence requiring additional validation" |
| 5-9 (novel) | novel_candidate | "Novel target from spatial transcriptomics; biological plausibility supports further validation" |
| < 5 | insufficient_evidence | "Insufficient evidence for current prioritization; data gaps should be addressed" |

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
- Your ONLY job is to expand the `<!-- EXPAND -->` marker with 2-3 sentences interpreting:
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

## EXPAND Marker Rules

- Each `<!-- EXPAND: {instruction} -->` MUST be replaced with 2-4 sentences
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

**After (correctly expanded):**
```
CD4-targeting therapeutics include ibalizumab (approved 2018 for HIV) and tregalizumab
(Phase 2 for rheumatoid arthritis), both monoclonal antibodies. These agents have not
been evaluated in pulmonary fibrosis. The existing clinical development confirms CD4
is druggable via antibody-based approaches.
```

### Example 2: Incorrect Expansion (Hallucinated)

**BAD — fabricates a drug not in the Reference Card:**
```
CD4-targeting drugs include ibalizumab and **zanubrutinib**, a BTK inhibitor
showing promise in fibrotic diseases.
```
Why wrong: zanubrutinib targets BTK, not CD4, and is not in the Reference Card.

## Quality Self-Check

Before saving the final drug.md, verify:
- [ ] Every score in the druggability matrix matches Reference Card
- [ ] Every classification label matches Reference Card
- [ ] Every PMID appears in the Reference Card pmids array
- [ ] Every drug name appears in the Reference Card drugs list
- [ ] No `<!-- EXPAND -->` markers remain unexpanded
- [ ] GWAS values are exactly as in Reference Card (likely 0)
- [ ] All deep dive sections have content (not "Data not available" if data exists)

## Troubleshooting

### `build_evidence_summary` returns error
**Cause:** Missing evidence files (assessment_results.json, stage3_*.json)
**Solution:** Verify evidence_assessor and deep_diver completed. Run `load_evidence_files(data_dir)` to check file list.

### `validate_drug_md` reports FABRICATED_PMID
**Cause:** A PMID in drug.md is not in the Reference Card
**Solution:** Remove the fabricated PMID. Replace with one from the Reference Card pmids array, or write "No citation available."

### `validate_drug_md` reports WRONG_CLASSIFICATION
**Cause:** Classification label doesn't match assessment_results.json
**Solution:** Copy the exact classification string from the Reference Card rubric object.

### Remaining `<!-- EXPAND -->` markers after save
**Cause:** Some EXPAND markers were not replaced
**Solution:** Search for `<!-- EXPAND` in the document and replace each with 2-4 sentences per the instruction.

Consult `references/scoring_guide.md` for detailed calibration tables and
evidence interpretation guidelines.
