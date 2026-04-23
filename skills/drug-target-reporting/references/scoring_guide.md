# Drug Target Scoring & Interpretation Guide

## Rubric Dimensions (14 total)

### Validated Track (3 dimensions → validated_total)

| Dimension | Range | Source | Interpretation |
|---|---|---|---|
| existing_drug_evidence | -5 to +5 | OpenTargets target_drugs count minus disease known_drugs overlap | Positive = more gene-specific drugs than disease-level drugs |
| clinical_trial_activity | -5 to +5 | OpenTargets target_drugs disease indications minus disease clinical evidence | Positive = active clinical pipeline for this gene |
| safety_profile | -3 to 0 | OpenTargets safetyLiabilities: major_clinical(-3), clinical_concerns(-2), preclinical_only(-1), minimal_or_none(0) | More negative = more safety concerns |

**validated_total** = existing_drug_evidence + clinical_trial_activity + safety_profile

### Exploratory Track (4 dimensions → exploratory_total)

| Dimension | Range | Source | Interpretation |
|---|---|---|---|
| gwas_genetic_support | 0 to 3 | GWAS Catalog variant count for gene-disease pair | 0 = no GWAS variants found (common for rare diseases) |
| tractability | 0 to 3 | OpenTargets tractability assessment across modalities | Higher = more druggable (antibody/small molecule/other clinical) |
| biological_plausibility | 0 to 5 | Disease association score from OpenTargets | Higher = stronger gene-disease association |
| novelty_opportunity | 0 to 5 | Inverse of existing evidence (less studied = more novel) | Higher = more novel target |

**exploratory_total** = gwas_support + tractability + biological_plausibility + novelty_opportunity

### Aggregate Scores

**combined_total** = validated_total + exploratory_total

### Classification Rules (deterministic, not LLM-judged)

```
validated_pass = existing_drug_evidence >= 3 OR (existing_drug_evidence >= 1 AND validated_total >= 3)
exploratory_pass = gwas_genetic_support >= 1 OR tractability >= 2 OR biological_plausibility >= 3
novel_pass = biological_plausibility >= 2 OR novelty_opportunity >= 3 OR (tractability >= 1 AND novelty_opportunity >= 2)

IF validated_pass:
    classification = "validated_target"
ELIF exploratory_pass:
    classification = "exploratory_target"
ELIF novel_pass:
    classification = "novel_candidate"
ELSE:
    classification = "insufficient_evidence"
```

### Priority Rules (per-classification branching)

| Classification | Condition | Priority |
|---|---|---|
| validated_target | combined_total >= 10 | high |
| validated_target | combined_total >= 5 | medium |
| validated_target | combined_total < 5 | low |
| exploratory_target | exploratory_total >= 12 | high |
| exploratory_target | exploratory_total >= 7 | medium |
| exploratory_target | exploratory_total < 7 | low |
| novel_candidate | (always) | low |
| novel_candidate | novel_pass AND (biological_plausibility >= 3 OR novelty_opportunity >= 4) | medium |
| insufficient_evidence | (always) | unranked |

## Stage 3 Candidate Selection

A gene becomes a stage3_candidate when BOTH conditions are met:
1. `combined_total >= 10`
2. Gene is in `stage1_filter_passed_genes` (passed STRING + Census biological validation)

## Stage 1 Filter Criteria

An L-R pair passes Stage 1 when ALL criteria are met:
- STRING combined score > 0.8 (out of 1.0, raw score > 800 out of 1000)
- Census coexpression p-value < 0.05
- Census gene_a p-value < 0.05
- Census gene_b p-value < 0.05

## Evidence Source Mapping

| drug.md Section | Primary Source | File |
|---|---|---|
| Druggability Matrix | rubric_scores.csv / assessment_results.json | evidence/ |
| Biological Interaction Filter | stage1_filter_results.csv / stage1_filter.json | evidence/ |
| Drug Profile (deep dive) | stage3_{GENE}.json + ot_{GENE}.json | evidence/ |
| Biological Context | stage1_{LIGAND}--{RECEPTOR}.json | evidence/ |
| Rubric Assessment | assessment_results.json rubric_assessment[] | evidence/ |
| Hypothesis Priorities | hypothesis_report.json | evidence/ |

## Narrative Tone Calibration

### For Validated Targets (combined >= 10, classification = validated_target)

Use language reflecting established clinical evidence:
- "This target has demonstrated clinical relevance through..."
- "Existing drug development programs targeting [gene] include..."
- "The validated status is supported by [N] clinical-stage compounds..."

### For Exploratory Targets (combined 5-9)

Use language reflecting potential with caveats:
- "Exploratory evidence suggests [gene] may play a role in..."
- "While clinical evidence is limited, biological plausibility is supported by..."
- "Further investigation is warranted to establish..."

### For Novel Candidates (spatial transcriptomics-derived)

Use language reflecting biological plausibility with explicit novelty framing:
- "This target emerged from spatial transcriptomics analysis and lacks prior drug development..."
- "Biological plausibility is supported by [pathway/STRING/Census evidence]..."
- "As a novel candidate, further mechanistic validation is required before..."

### For Insufficient Evidence (combined < 5)

Use language acknowledging gaps:
- "Current evidence is insufficient to support [gene] as a therapeutic target..."
- "Key data gaps include..."
- "Additional studies are needed to evaluate..."

## Common Hallucination Patterns to Avoid

Based on observed failures across gpt-4.1-mini and gpt-5.4-mini:

1. **GWAS inflation**: All GWAS scores were 0 but reports showed 1-3. Always copy the actual value.
2. **Classification drift**: validated_target reported as exploratory_target. Copy the exact string.
3. **Score deflation**: CD4 had combined=16 but was reported as 9. Copy the integer.
4. **Drug invention**: Reports listed drugs not in ChEMBL/OpenTargets data. Only use provided drugs.
5. **Pathway extrapolation**: Reports described pathways not in the evidence. Only cite detected pathways.

## Score Threshold Rationale

*Thresholds (15/10/5) are based on the empirical distribution of combined_total
across 41 genes in pilot IPF and breast cancer datasets. Genes above 15 consistently
had Phase 2+ clinical evidence; below 5 had no clinical or genetic support.*

When a gene's combined_total falls on a boundary (e.g., 10), present both interpretations
rather than choosing one: "This target shows moderate validated evidence (combined=10),
at the threshold between high and medium priority classification."
