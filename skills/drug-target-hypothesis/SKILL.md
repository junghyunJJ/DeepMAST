---
name: drug-target-hypothesis
description: Generate biological mechanism hypotheses from drug target assessment evidence. Use when you have completed Stage 1-3 evidence collection and rubric scoring and need to formulate testable mechanistic hypotheses about drug targets, therapeutic strategies, cross-target interactions, and novel pathways. Data-driven — focuses on evidence insights not literature search. For general scientific hypothesis generation use hypothesis-generation; for automated LLM-driven hypothesis testing on datasets use hypogenic. For iterative quality improvement of generated hypotheses use evolution-reasoning.
metadata:
    skill-author: K-Dense Inc.
---

# Drug Target Hypothesis Generation

## Overview

Generate testable biological mechanism hypotheses from multi-stage drug target assessment evidence. This skill applies a data-driven approach adapted from HypoGeniC (Zhou et al., 2024), using evidence from Stage 1-3 assessments to formulate ranked hypotheses with UCB-based quality scoring.

Unlike the general `hypothesis-generation` skill (literature-driven, LaTeX output, broad science) or `hypogenic` (dataset classification), this skill is specialized for drug target assessment — it reads structured evidence files, generates mechanism hypotheses across four thematic categories, applies gap analysis to ensure comprehensive evidence coverage, and scores hypotheses on Evidence Coverage, Specificity, Novelty, and Actionability.

## When to Use This Skill

Use this skill when:
- Drug target assessment with Stage 1-3 evidence has been completed
- `rubric_scores.csv`, `assessment_results.json`, and `stage2_evidence.json` exist in the evidence directory
- You need testable hypotheses about mechanisms, therapeutic strategies, cross-target synergies, or novel pathways
- The drug report markdown (e.g., `drug.md`) has been generated with FEATURED and NOVEL candidates

Do NOT use for:
- General biology questions without drug target evidence data
- Literature-only hypothesis generation (use `hypothesis-generation` skill)
- Classification tasks on tabular datasets (use `hypogenic` skill)
- Generating hypotheses before evidence collection is complete

---

## Workflow

Follow these five phases sequentially. Each phase builds on the previous.

### Phase 1: Evidence Ingestion & Target Categorization

**Step 1.1: Enumerate evidence files**

Read the evidence directory and list all available files:

| File Pattern | Required? | Description |
|-------------|-----------|-------------|
| `rubric_scores.csv` | **YES** | Gene-level rubric scores |
| `assessment_results.json` | **YES** | Full rubric assessment with metadata |
| `stage2_evidence.json` | **YES** | OpenTargets data per gene |
| `stage1_{LIGAND}--{RECEPTOR}.json` | No | Per L-R pair biological context |
| `stage3_{GENE}.json` | No | Per gene deep-dive (FEATURED) |
| `ot_{GENE}.json` | No | OpenTargets detailed per gene |
| `known_drugs.json` | No | Disease-level drug landscape |
| `gene_manifest.json` | No | Gene list with selection flags |

Also check the parent directory for a drug report markdown (e.g., `drug.md`, `tmp_drug.md`).

If any REQUIRED file is missing, stop and report the gap. Do not generate hypotheses with incomplete core evidence.

See `references/evidence_format_spec.md` for complete schema documentation of all file types.

**Step 1.2: Categorize targets**

Parse `rubric_scores.csv` and categorize ALL genes into three tiers:

- **FEATURED**: genes where `stage3_candidate` = True. These have full Stage 1-3 evidence and are the primary hypothesis targets.
- **NOVEL**: genes identified in the drug report's `[NOVEL]` section, OR genes with `priority` >= medium AND `exploratory_total` >= 6 AND no existing drug evidence but distinctive pathway profiles. Cross-reference with the drug report markdown if available.
- **OTHER**: all remaining genes. These provide supporting context but are not primary hypothesis targets.

**Step 1.3: Build Evidence Inventory**

For each tier, extract and record:

**Per FEATURED gene:**
- All 11 rubric scores, classification, priority
- Which `stage1_*.json` pairs involve this gene (as ligand or receptor)
- Stage 3 data: ChEMBL drugs (drug names, mechanisms, max phases), PubMed papers (PMIDs, titles)
- OT tractability modalities (SM, AB, PR, OC)
- OT function descriptions (first 2-3 sentences)
- Safety liabilities from OT or rubric safety_profile score

**Per NOVEL gene:**
- Rubric scores, classification, priority
- Which L-R pairs involve this gene
- OT data (tractability, function, disease association score)

**Disease context:**
- Disease name from `assessment_results.json`
- Known disease drugs from `known_drugs.json` (if exists)
- Total unique drugs and targets in the disease landscape

**Step 1.4: Extract key biological entities**

Identify patterns across the evidence:
- **Convergent pathways**: pathways appearing in 2+ stage1 pairs (suggest shared biology)
- **High-plausibility genes**: biological_plausibility score >= 3 in rubric
- **Strong PPI pairs**: STRING `max_combined_score` > 0.9 in stage1 data
- **Strong coexpression**: Census `coexpression_p_value` < 1e-10 AND `coexpression_risk_ratio` > 5.0
- **Hub genes**: genes appearing in 3+ L-R pairs (suggest central role)
- **Tractable targets**: genes with OT tractability in 2+ modalities

Record these entities — they are the building blocks for hypothesis generation.

---

### Phase 2: Hypothesis Generation

Generate **4-6 initial hypotheses** distributed across four mandatory thematic categories. At minimum, one hypothesis per category.

See `references/hypothesis_thematic_categories.md` for detailed category definitions and examples.

| Category | Focus | Min Count |
|----------|-------|:---------:|
| **Mechanism of Action (MoA)** | How a target mechanistically drives the disease | 1 |
| **Therapeutic Strategy** | How to intervene (drug, modality, safety) | 1 |
| **Cross-Target Interaction** | Multi-target synergies or pathway convergence | 1 |
| **Novel Pathway** | Unexpected connections from the evidence data | 1 |

**For each hypothesis, you MUST include all 7 elements:**

1. **Title**: Descriptive and specific. Include gene names, cell types, and mechanism.
   - Good: "ICAM1-EZR Axis Drives Inflammatory Leukocyte Recruitment to Fibrotic Alveoli via NF-kB-Mediated Cytoskeletal Remodeling"
   - Bad: "ICAM1 is important in IPF"

2. **Thematic category**: One of MoA / Therapeutic Strategy / Cross-Target Interaction / Novel Pathway

3. **Core claim**: 2-3 sentences stating the mechanistic hypothesis. Must explain HOW and WHY, not just WHAT.

4. **Supporting evidence references**: Explicit list citing specific evidence files and fields.
   - Format: `{file_id}: {specific finding}`
   - Example: `stage1_ICAM1--MUC1.json: STRING PPI score 0.993, Census risk ratio 17.86 in AT2 cells`

5. **Key biological entities**: Lists of genes, pathways, cell types, and drugs involved.

6. **Falsifiable prediction**: One specific, testable prediction with:
   - Named intervention or condition
   - Measurable outcome with directionality
   - Model system or context
   - Failure criterion (what would disprove it)

7. **Proposed validation approach**: Experimental method, model system, key readouts, and controls.

**Generation strategy:**
- Start with FEATURED genes (highest evidence)
- Use hub genes and convergent pathways for Cross-Target hypotheses
- Use NOVEL genes for Novel Pathway hypotheses
- Prioritize hypotheses that integrate multiple evidence types (Census + PPI + pathways + drugs)

---

### Phase 3: Gap Detection

Ensure comprehensive evidence utilization.

**Step 3.1: Build coverage matrix**

For each evidence file in the inventory, mark whether it was referenced by at least one hypothesis:

```
stage1_ICAM1--MUC1.json    → Referenced by Hypothesis 1 ✓
stage1_ICAM1--EZR.json      → Referenced by Hypothesis 3 ✓
stage1_TGFB1--P4HB.json    → NOT REFERENCED ✗
stage3_TGFB1.json          → Referenced by Hypothesis 2 ✓
...
```

**Step 3.2: Identify orphan evidence**

List all unreferenced evidence:
- Stage 1 pairs with no hypothesis referencing them
- FEATURED genes whose Stage 3 data was not referenced
- Pathways appearing in evidence but not in any hypothesis
- NOVEL genes not mentioned in any hypothesis

**Step 3.3: Generate gap-filling hypotheses**

For each significant cluster of orphan evidence, generate 1-2 supplementary hypotheses:
- Tag with `[GAP]` prefix in the title
- Follow the same 7-element structure as Phase 2 hypotheses
- May span thematic categories

**Step 3.4: Coverage check**

Calculate: `files_referenced / total_evidence_files * 100`

Target: **>= 80%** of stage1_*.json and stage3_*.json files referenced.

If below 80% after gap-filling, generate one more hypothesis targeting the largest cluster of orphan evidence.

---

### Phase 4: UCB Scoring & Filtering

Score ALL hypotheses (Phase 2 + Phase 3 gap-fillers) on four dimensions.

See `references/ucb_scoring_criteria.md` for the full scoring rubric with examples.

**Composite score formula:**
```
Score = 0.30 × Evidence_Coverage + 0.30 × Specificity + 0.20 × Novelty + 0.20 × Actionability
```

**Scoring procedure for each hypothesis:**

1. **Evidence_Coverage** (0.30): Count distinct evidence files referenced. Score = min(count / 4, 1.0)

2. **Specificity** (0.30): Rate the falsifiable prediction on the 0.0-1.0 scale.
   - **Hard rule**: Hypotheses scoring < 0.5 on Specificity are automatically removed regardless of composite score.

3. **Novelty** (0.20): Rate discovery potential on the 0.0-1.0 scale. Category 4 (Novel Pathway) hypotheses should target >= 0.5.

4. **Actionability** (0.20): Rate drug development feasibility on the 0.0-1.0 scale. Use OT tractability, ChEMBL drugs, and clinical phase data.

**For each dimension, provide a brief justification** (1 sentence explaining the score).

**Filtering:**
1. Remove hypotheses with Specificity < 0.5
2. Remove hypotheses with composite score < 0.4
3. If fewer than 3 survive, lower composite threshold to 0.35 and re-filter
4. Rank remaining by composite score descending
5. Keep top **3-5** hypotheses

**Category balance check:** If scoring eliminates an entire thematic category, generate one additional hypothesis for that category and re-score before finalizing.

---

### Phase 4.5: Evolutionary Refinement (Conditional)

**Trigger conditions** — apply this phase if ANY of the following are true:
- Best composite score < 0.7
- Fewer than 3 hypotheses survived Phase 4 filtering
- An entire thematic category was eliminated after the balance check

If triggered, use the `evolution-reasoning` skill:
1. Call `read_skill_file(skill_path="skills/evolution-reasoning")` to load the refinement protocol
2. Pass surviving hypotheses as items with their UCB scores as dimensions:
   - dimensions: `{Evidence_Coverage: 0.30, Specificity: 0.30, Novelty: 0.20, Actionability: 0.20}`
   - threshold: 0.7
   - generation_limit: 2
3. Follow the skill's 4-phase protocol (Initialize, Critique & Score, Select & Mutate, Termination)
4. Replace Phase 4 output with the refined hypotheses

If NOT triggered (best composite >= 0.7 AND >= 3 hypotheses AND all categories represented), skip directly to Phase 5.

---

### Phase 5: Markdown Report Output

Generate the hypothesis report using the template from `assets/hypothesis_report_template.md`.

**Report sections:**

1. **Header**: Disease name, date, evidence directory, file counts, hypothesis counts (generated vs. retained)

2. **Executive Summary**: 2-3 paragraphs naming the top hypothesis, key predictions, cross-target insights, and novel discoveries. State evidence coverage percentage.

3. **Ranked Hypotheses**: Full detail for each retained hypothesis (all 7 elements + 4 dimension scores with justifications)

4. **Scoring Summary**: Table comparing all retained hypotheses across dimensions

5. **Gap Analysis**: Evidence coverage stats, list of orphan evidence, gap-filling hypothesis outcomes

6. **Appendix**: Evidence Inventory tables (FEATURED targets, NOVEL targets, Stage 1 L-R pairs)

**Output location**: Save as `hypothesis_report.md` in the same directory as the drug report.

---

## Quality Standards

Every generated report must meet these standards:

- **Evidence integrity**: Every claim traces to a specific evidence file and field. No hallucinated data points. If a value is referenced, it must exist in the evidence files.
- **Falsifiability**: Every hypothesis includes a prediction that can be disproven by a specific experiment.
- **Coverage**: At least 80% of stage1/stage3 evidence files referenced by at least one hypothesis.
- **Category balance**: At least 3 of 4 thematic categories represented in final hypotheses.
- **Scoring transparency**: All 4 dimension scores justified with explicit rationale per hypothesis.
- **No fabricated literature**: Do not cite PubMed papers not present in the evidence data. Only use PMIDs from `stage3_*.json` files.
- **No fabricated drug data**: Only reference drugs found in `stage3_*.json` or `known_drugs.json`.

---

## Resources

### references/

- `evidence_format_spec.md` — Complete schema documentation for all evidence file types (rubric CSV, stage1-3 JSON, OT JSON, known_drugs, gene_manifest)
- `ucb_scoring_criteria.md` — Detailed 4-dimension scoring rubric with 0.0-1.0 scale definitions, drug-target-specific examples, edge cases, and score interpretation bands
- `hypothesis_thematic_categories.md` — Definitions for 4 thematic categories (MoA, Therapeutic Strategy, Cross-Target Interaction, Novel Pathway) with IPF examples and multi-category assignment guidelines

### assets/

- `hypothesis_report_template.md` — Markdown template with placeholder variables for the output report
- `example_hypothesis_ipf.md` — Worked example using IPF evidence data demonstrating the expected quality level

### Related Skills

- `hypothesis-generation` — General scientific hypothesis generation with LaTeX PDF output and 8-step manual workflow
- `hypogenic` — Automated LLM-driven hypothesis generation and testing on tabular datasets (HypoGeniC/HypoRefine)
- `pubmed-eutils-search` — PubMed literature search (can supplement hypotheses with additional literature if needed)
- `evolution-reasoning` — Iterative quality improvement via evolutionary critique-and-refine cycles. Use after UCB scoring when hypothesis quality is below threshold.
- `html-report-generator` — Can integrate hypothesis report as a tab in the HTML drug target report
