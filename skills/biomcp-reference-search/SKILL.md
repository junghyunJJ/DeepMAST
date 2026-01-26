---
name: biomcp-reference-search
description: Workflow for interpreting spatial transcriptomics and cell-cell interaction analysis results and finding supporting reference papers. Uses BioMCP's think + article_searcher tools to find evidence for L-R interaction, pathway, and gene marker findings, then generates publication-style interpretation paragraphs with reference lists. Use for ST analysis interpretation, CCI analysis reference search, and report writing.
---

# BioMCP Reference Search Skill

Workflow for interpreting ST/CCI analysis results and generating publication-style output with supporting references.

## Workflow Overview

```
[Analysis Result Input] → [Type Classification] → [think: Search Strategy] → [article_searcher: Paper Search] → [Interpretation Draft] → [Quality Validation Loop] → [Final Output]
```

## Step 1: Input Classification

Classify analysis results into 3 types:

| Type | Examples | Identifying Keywords |
|------|----------|---------------------|
| **L-R Interaction** | Apoe-Trem2, SPP1-CD44 | ligand, receptor, interaction, LIANA, CellChat |
| **Pathway** | WNT, NFkB, TNFa signaling | pathway, signaling, PROGENy, decoupler |
| **Gene/Marker** | DEGs, spatial markers | gene, marker, expression, enriched |

## Step 2: Develop Search Strategy with think Tool

Use `think` tool to establish structured research plan:

```
# Think Step 1: Context Analysis
think(
  thought="Context summary: [analysis method], [findings], [biological context]",
  thoughtNumber=1, 
  totalThoughts=3, 
  nextThoughtNeeded=True
)

# Think Step 2: Derive Search Keywords
think(
  thought="Search strategy: genes=[...], diseases=[...], keywords=[...]",
  thoughtNumber=2,
  totalThoughts=3,
  nextThoughtNeeded=True
)

# Think Step 3: Expected Results and Interpretation Direction
think(
  thought="Expected biological mechanisms and interpretation direction",
  thoughtNumber=3,
  totalThoughts=3,
  nextThoughtNeeded=False
)
```

## Step 3: Search Papers with article_searcher

Type-specific search parameter strategies (details: [references/search_strategies.md](references/search_strategies.md)):

### L-R Interaction
```python
article_searcher(
  genes=["APOE", "TREM2"],           # both ligand and receptor
  diseases=["Alzheimer disease"],     # related disease
  keywords=["ligand receptor", "cell cell interaction", "spatial transcriptomics"],
  include_preprints=True,
  page_size=20
)
```

### Pathway
```python
article_searcher(
  genes=None,                         # omit for whole pathway search
  diseases=["Alzheimer disease"],
  keywords=["WNT pathway", "spatial transcriptomics", "single cell"],
  include_preprints=True,
  page_size=20
)
```

### Gene/Marker
```python
article_searcher(
  genes=["GENE1", "GENE2"],
  diseases=["relevant disease"],
  keywords=["spatial", "marker", "expression"],
  include_preprints=True,
  page_size=20
)
```

## Step 4: Generate Output

### 4.1 Interpretation Paragraph

Write publication-style paragraph connecting analysis results with retrieved papers:

```
Our finding of [analysis result] is consistent with previous reports 
demonstrating that [paper's key finding] (Author et al., Year). 
Furthermore, [expand context with additional citations] (Author2 et al., Year).
```

**Writing Principles:**
- State analysis result first
- Use connecting phrases: "consistent with", "in line with", "supports"
- Naturally cite 2-3 papers within a single paragraph
- Include biological mechanism explanations

### 4.2 Reference List

```
## References

1. [Author] et al. ([Year]) [Title]. [Journal]. DOI: [doi]
   → [One-line summary: how this paper relates to my results]

2. [Author] et al. ([Year]) [Title]. [Journal]. DOI: [doi]
   → [One-line summary]
```

## Step 5: Quality Validation Loop

After generating interpretation, validate quality using `reflection-tool:think_tool`.
Loop until Score ≥ 0.7, with **maximum 3 iterations**.

### Validation Process

```
Iteration 1:
  Generate interpretation → reflection-tool:think_tool → Score check
  └── Score ≥ 0.7 → Proceed to final output ✓
  └── Score < 0.7 → Identify gaps, refine interpretation

Iteration 2 (if needed):
  Refine interpretation → reflection-tool:think_tool → Score check
  └── Score ≥ 0.7 → Proceed to final output ✓
  └── Score < 0.7 → Identify gaps, refine interpretation

Iteration 3 (final, if needed):
  Final refinement → reflection-tool:think_tool → Score check
  └── Proceed with best version (with warning if Score < 0.7)
```

### Reflection Format

```python
reflection-tool:think_tool({
  "reflection": """
  Learned:
  - [Interpretation connects analysis result to literature]
  - [N PMIDs included with specific relevance]
  - [Biological mechanism clearly explained]
  - [Statistics from analysis included: values, p-values]

  Gap:
  - [Missing aspects or weak connections]
  - [Areas needing more specificity]

  Next: [Proceed to final output / Refine: add X, improve Y]
  """
})
```

### Quality Criteria for Score ≥ 0.7

| Criterion | Requirement | Example |
|-----------|-------------|---------|
| **Specificity** | ≥2 statistics from analysis | "Moran's R=0.477", "FDR=0.001" |
| **Literature** | ≥2 PMIDs with clear relevance | "consistent with (PMID: 12345678)" |
| **Mechanism** | Clear biological explanation | "CypA binds CD147, activating NF-κB..." |
| **Connecting phrases** | Uses appropriate transitions | "consistent with", "in line with" |
| **No vagueness** | Avoid excessive "may", "might" | Direct statements preferred |

### Score Interpretation

| Score | Action |
|-------|--------|
| < 0.5 | Major revision: missing key elements (PMIDs, statistics, mechanism) |
| 0.5-0.7 | Minor revision: add specifics, strengthen connections |
| ≥ 0.7 | Proceed to final output ✓ |

### Refinement Strategies by Gap Type

| Gap Identified | Refinement Action |
|----------------|-------------------|
| Missing PMIDs | Re-search with refined keywords, add citations |
| Weak mechanism | Expand biological pathway explanation |
| No statistics | Insert specific values from analysis input |
| Vague language | Replace "may" with direct statements |
| Poor connection | Add explicit linking sentence to analysis result |

### Maximum Iterations Reached

If Score remains < 0.7 after 3 iterations:
1. Document best interpretation achieved
2. Add warning note: "Quality threshold not fully met"
3. Proceed with output, noting specific gaps for user review

## Complete Output Template

```markdown
## Interpretation

[Interpretation paragraph - publication-style connection of analysis results with references]

---

## References

1. Author et al. (Year) Title. Journal. DOI: xxx
   → Key finding and relevance to my results

2. Author et al. (Year) Title. Journal. DOI: xxx
   → Key finding and relevance to my results

---

## Quality Validation

- **Iterations**: [1-3]
- **Final Score**: [0.XX]
- **Status**: [✓ Passed / ⚠ Best effort after max iterations]
```

## Example

### Input
> Found enriched Apoe-Trem2 interaction in microglia surrounding amyloid plaques in AD mouse brain using LIANA+

### Output

**Interpretation:**

Our finding of enriched Apoe-Trem2 interaction in plaque-associated microglia is consistent with previous reports demonstrating that the TREM2-APOE pathway drives the transcriptional phenotype of disease-associated microglia (Krasemann et al., 2017). This interaction has been shown to be critical for microglial response to amyloid pathology, where TREM2 signaling enables microglia to adopt a phagocytic state necessary for amyloid clearance (Zhou et al., 2020).

---

**References:**

1. Krasemann S et al. (2017) The TREM2-APOE Pathway Drives the Transcriptional Phenotype of Dysfunctional Microglia in Neurodegenerative Diseases. Immunity. DOI: 10.1016/j.immuni.2017.08.008
   → TREM2-APOE axis is essential for determining neurodegenerative microglia phenotype

2. Zhou Y et al. (2020) Human and mouse single-nucleus transcriptomics reveal TREM2-dependent and TREM2-independent cellular responses in Alzheimer's disease. Nat Med. DOI: 10.1038/s41591-019-0695-9
   → Identified TREM2-dependent microglia subtypes in AD using snRNA-seq
