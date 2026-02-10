---
name: hypogenic-hypothesis-generation
description: HypoGeniC-inspired iterative hypothesis generation for CCI analysis - UCB reward scoring, wrong-example refinement, literature-grounded initialization. Read this SKILL for the complete 7-step hypothesis generation workflow.
---

# HypoGeniC Hypothesis Generation for CCI Analysis

## Purpose

This skill provides the **complete workflow** for the PLANNER subagent's hypothesis generation phase. It defines:
- **HOW** to generate hypotheses iteratively (adapted from HypoGeniC/HypoRefine)
- **WHEN** to search literature (initialization, not exhaustive)
- **HOW** to score and refine hypotheses (4-dimension reward function)
- **WHAT** constitutes a quality hypothesis (thresholds and rubric)

Based on the HypoGeniC framework (EMNLP 2024, ChicagoHAI) adapted for spatial transcriptomics CCI analysis.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│          This SKILL.md (Workflow Definition)                     │
│  - Step 1: Read Targets           → read_file("/targets.json")  │
│  - Step 2: Load Analysis Data     → load_analysis_data()        │
│  - Step 3: Literature Init        → search_pubmed_advanced()    │
│  - Step 4: Generate Hypotheses    → LLM reasoning (4-6 initial) │
│  - Step 5: Wrong-Example Analysis → think_tool(iteration=1)     │
│  - Step 6: Score and Refine       → think_tool(iteration=2)     │
│  - Step 7: Write Strategic Plan   → write_file()                │
└────────────────────────────┬────────────────────────────────────┘
                             │ (PLANNER reads workflow, then calls tools)
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│          Python Tools (Execution Layer)                          │
│  - load_analysis_data: Load analysis results + search contexts  │
│  - search_pubmed_advanced: PubMed E-utilities search            │
│  - think_tool: Reflection for gap analysis + scoring            │
│  - read_file / write_file: Virtual filesystem operations        │
└─────────────────────────────────────────────────────────────────┘
```

## Virtual Filesystem

| File | Step | Content |
|------|------|---------|
| `/targets.json` | Read (Step 1) | Pre-selected target configuration |
| `/analysis_summary.md` | Write (Step 2) | Analysis data summary |
| `/data_path.txt` | Write (Step 2) | Real data directory path |
| `/planner_literature_context.md` | Write (Step 3) | Literature initialization results |
| `/strategic_plan.md` | Write (Step 7) | Final strategic plan with scored hypotheses |

## 7-Step Workflow

### Step 1: Read Target Configuration

Read **/targets.json** to get the pre-selected configuration:

```json
{
  "analysis_mode": "cluster_to_celltype",
  "interest_clusters": ["4", "16", "176"],
  "interest_celltypes": null,
  "data_directory": "/path/to/res",
  "user_confirmed": true
}
```

**Actions**: Parse analysis_mode, targets, data_directory.

### Step 2: Load Analysis Data

1. Call **load_analysis_data** with the EXACT path from data_directory
2. **MANDATORY**: Write returned files to virtual filesystem:
   - `write_file("/analysis_summary.md", <content>)`
   - `write_file("/data_path.txt", <content>)`
3. Note the available analyses for each Part (1, 2, 3)

**Key information to extract**:
- Available analysis items (up to 11 across Parts 1-3)
- Cell types present in the data
- Pathways detected
- Disease/tissue context (inferred from cell type composition)

### Step 3: Literature Initialization (HypoRefine Pattern)

**Purpose**: Ground hypothesis generation in existing knowledge. This is a LIGHTWEIGHT search (10 papers max) — the SEARCHER will do comprehensive search later.

**Why search_pubmed_advanced?**
- PLANNER needs disease + celltypes + pathways (not gene-focused)
- Raw PubMed query syntax allows flexible term combination
- Consistent with SEARCHER's use of the same tool

**Procedure**:

1. **Infer disease context** from cell type composition:
   - Epithelial + Fibroblast + Immune → likely carcinoma
   - Neuron + Oligodendrocyte + Astrocyte → likely neurological
   - Use cluster annotations and pathway context

2. **Call search_pubmed_advanced**:
   ```
   search_pubmed_advanced(
     query='"{disease}"[tiab] AND ("{celltype1}"[tiab] OR "{celltype2}"[tiab]) AND ("spatial transcriptomics"[tiab] OR "cell interaction"[tiab])',
     max_results=10,
     sort="relevance"
   )
   ```

3. **Extract from results**:
   - Known mechanisms in this tissue/disease
   - Established L-R interactions
   - Key signaling pathways
   - Known spatial organization patterns

4. **Write** `/planner_literature_context.md`:
   ```markdown
   # Literature Context for Hypothesis Generation

   ## Papers Consulted: {count}

   ## Known Mechanisms
   - {mechanism 1} (PMID: {pmid})
   - {mechanism 2} (PMID: {pmid})

   ## Established L-R Interactions
   - {LR pair 1}: {context} (PMID: {pmid})

   ## Key Signaling Pathways
   - {pathway}: {role in disease} (PMID: {pmid})

   ## Spatial Organization Patterns
   - {pattern}: {description} (PMID: {pmid})
   ```

### Step 4: Generate Initial Hypotheses

**Generate 4-6 hypotheses** (increased from 2-4) using THREE information sources:
1. **Analysis data** (Step 2): What analyses are available, what patterns might emerge
2. **Literature context** (Step 3): What is already known
3. **Domain knowledge**: General ST/CCI biology

**Hypothesis categories** (aim for at least one per category):
- **Spatial organization**: How do clusters/cell types organize spatially?
- **Cell-cell communication**: What L-R interactions characterize these regions?
- **Pathway activation**: What signaling pathways are enriched?
- **Novel/integrative**: What unexpected patterns might emerge from combining analyses?

**Each hypothesis must specify**:
- A concrete, falsifiable prediction
- Which analysis items provide evidence (from the 11 available)
- Key biological entities (clusters, celltypes, L-R pairs, pathways)
- Whether it is literature-grounded or data-driven

### Step 5: Wrong-Example Analysis (Gap Detection)

**Purpose**: Identify analyses that NO hypothesis covers — these represent blind spots.

Use **think_tool** (iteration=1, max_iterations=2):

```
think_tool(
  reflection="Wrong-example analysis for hypothesis coverage:

  Available analyses (up to 11):
  Part 1: 1-1 Spatial, 1-2 CellType, 1-3 Neighborhood, 1-4 Decoupler, 1-5 MISTy
  Part 2: 2-6 LIANA Moran's R, 2-7 NMF Factor, 2-8 Pathway-Factor, 2-9 ctSVG
  Part 3: 3-10 Spatial L-R, 3-11 L-R Summary

  Hypothesis-Analysis mapping:
  - H1 covers: {list analyses}
  - H2 covers: {list analyses}
  - H3 covers: {list analyses}
  - H4 covers: {list analyses}
  ...

  ORPHAN analyses (not covered by any hypothesis):
  - {analysis}: Possible hypothesis angle: {suggestion}

  Action: Generate 1-2 targeted hypotheses for orphan analyses.",
  iteration=1,
  max_iterations=2
)
```

**After think_tool**: Generate additional hypotheses targeting orphan analyses.

### Step 6: Score and Refine (UCB-Adapted Reward)

**Purpose**: Score each hypothesis on 4 dimensions and filter low-quality ones.

Use **think_tool** (iteration=2, max_iterations=2):

```
think_tool(
  reflection="Hypothesis scoring using 4-dimension reward function:

  Scoring Rubric:
  | Dimension | Weight | Criterion |
  |-----------|--------|-----------|
  | Evidence Coverage | 0.30 | How many of 11 analyses does this reference? |
  | Specificity | 0.30 | Is the prediction concrete and falsifiable? |
  | Literature Grounding | 0.20 | Supported by Step 3 literature? |
  | Novelty | 0.20 | Goes beyond known biology? |

  Scores:
  - H1: Coverage={X}, Specificity={Y}, Grounding={Z}, Novelty={W} → Composite={score}
  - H2: ...
  - H3: ...
  ...

  Threshold: composite < 0.4 → REMOVE
  Final set: {list surviving hypotheses}
  All analyses covered: {yes/no}",
  iteration=2,
  max_iterations=2
)
```

**Scoring details** (see `references/reward_function.md` for examples):

| Dimension | Weight | 0.0 (Poor) | 0.5 (Moderate) | 1.0 (Excellent) |
|-----------|--------|------------|-----------------|------------------|
| Evidence Coverage | 0.30 | References 1 analysis | References 2-3 analyses | References 4+ analyses |
| Specificity | 0.30 | Vague prediction ("might be involved") | Directional ("enriched in") | Quantitative/falsifiable (">2-fold in cluster X") |
| Lit. Grounding | 0.20 | No literature support | Partially supported | Strong PMID-backed support |
| Novelty | 0.20 | Restates known biology | Extends known mechanisms | Proposes testable new mechanism |

**Composite score** = 0.30×Coverage + 0.30×Specificity + 0.20×Grounding + 0.20×Novelty

**Thresholds**:
- Score < 0.4 → Remove hypothesis
- Final count: 3-5 hypotheses (remove lowest if >5)
- All available analyses must be covered by at least one hypothesis

### Step 7: Write Strategic Plan

Write **/strategic_plan.md** with the EXTENDED format:

```markdown
# Strategic Interpretation Plan

## Target Configuration
- Analysis Mode: {mode}
- Selected Targets: {clusters or cell types}
- Data Directory: {path}

## Available Analyses Summary
{Brief summary of available Part 1/2/3 analyses}

## Literature Context
- Papers consulted: {count}
- Key known mechanisms: {list}
- Established L-R interactions: {list}

## Hypotheses

### H1: [Title]
- **Prediction**: {specific, falsifiable prediction}
- **Evidence needed**: {analysis items, e.g., Part 1-1 spatial, Part 2-6 Moran's R}
- **Key entities**: {clusters, celltypes, L-R pairs, pathways}
- **Literature grounding**: {PMID or "Data-driven discovery"}
- **Quality score**: {composite} (Coverage={X}, Specificity={Y}, Grounding={Z}, Novelty={W})

### H2: [Title]
{same format}

### H3: [Title]
{same format}

## Unexplained Findings
{List of analyses not covered by any hypothesis, if any remain after Step 5}

## Hypothesis Generation Metadata
- Initial hypotheses: {N} → After gap analysis: {M} → Final (after scoring): {K}
- Literature papers consulted: {count}
- Scoring threshold applied: 0.4

## Interpretation Priority
1. {Most important analysis first - why}
2. {Second priority - why}
3. {Third priority - why}
```

## Adapted Reward Function (4-Dimension Rubric)

This is the CCI-adapted version of HypoGeniC's UCB reward function.

| Dimension | Weight | What It Measures | Scoring Basis |
|-----------|--------|------------------|---------------|
| **Evidence Coverage** | 0.30 | Breadth of analytical support | Fraction of 11 analyses referenced by the hypothesis |
| **Specificity** | 0.30 | Precision and falsifiability | Can the prediction be tested with the available data? |
| **Literature Grounding** | 0.20 | Connection to existing knowledge | Does Step 3 literature support this hypothesis? |
| **Novelty** | 0.20 | Discovery potential | Does it go beyond restating known biology? |

**Why these weights?**
- Coverage + Specificity (0.60 total): Ensures hypotheses are actionable and testable with available data
- Grounding (0.20): Prevents speculation without biological basis
- Novelty (0.20): Encourages discovery beyond the obvious

See `references/reward_function.md` for detailed scoring examples.

## Wrong-Example Bank (Orphan Analysis Detection)

The "wrong-example" concept from HypoGeniC maps to **orphan analyses** in CCI:

| HypoGeniC Concept | CCI Adaptation |
|--------------------|----------------|
| Wrong examples (misclassified samples) | Orphan analyses (uncovered by hypotheses) |
| Generate hypothesis from wrong examples | Generate hypothesis targeting orphan analysis |
| Iterative refinement | Gap-filling in Step 5 |

**Common orphan analyses** (frequently missed):
- **1-5 MISTy**: Often overlooked but reveals spatial pathway relationships
- **2-8 Pathway-Factor**: Connects NMF factors to pathway biology
- **2-9 ctSVG**: Cell type-specific spatially variable genes

## Quality Thresholds

| Criterion | Threshold | Action if Failed |
|-----------|-----------|------------------|
| Composite score | >= 0.4 | Remove hypothesis |
| Final hypothesis count | 3-5 | Remove lowest if >5, generate more if <3 |
| Analysis coverage | 100% of available | Generate targeted hypothesis for orphans |
| Literature init | >= 5 papers | Broaden search query |

## Relationship to Other Subagents

| Subagent | How It Uses /strategic_plan.md |
|----------|-------------------------------|
| **SEARCHER** | Reads hypotheses to prioritize search terms |
| **INTERPRETER** | Tests each hypothesis against analysis evidence |
| **REPORTER** | Validates hypotheses in synthesis (Supported/Partial/Not Supported) |

**Backward compatibility**: The extended format is ADDITIVE. All existing fields (Target Configuration, Hypotheses H1/H2/H3, Interpretation Priority) are preserved. New sections (Literature Context, Unexplained Findings, Metadata) are additions that downstream agents can use but don't require.

## References

- Zhou et al. (2024). "Hypothesis Generation with Large Language Models." EMNLP Workshop NLP4Science.
- Liu et al. (2024). "Literature Meets Data: A Synergistic Approach to Hypothesis Generation." arXiv:2410.17309.
- See `references/config_template.yaml` for HypoGeniC Python library configuration reference.
- See `references/reward_function.md` for detailed scoring examples and rubric.
