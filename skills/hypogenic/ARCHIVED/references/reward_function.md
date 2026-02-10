# HypoGeniC Reward Function for CCI Hypothesis Scoring

## Overview

This document details the 4-dimension reward function adapted from HypoGeniC's UCB-inspired scoring for spatial transcriptomics CCI analysis. The PLANNER uses this rubric in Step 6 (Score and Refine) to evaluate and filter hypotheses.

## Composite Score Formula

```
Score = 0.30 × Evidence_Coverage + 0.30 × Specificity + 0.20 × Lit_Grounding + 0.20 × Novelty
```

**Threshold**: Score < 0.4 → Remove hypothesis

## Dimension 1: Evidence Coverage (Weight: 0.30)

**Measures**: How many of the 11 available analyses does this hypothesis reference?

| Score | Criteria | Example |
|-------|----------|---------|
| 0.0 | References only 1 analysis | "Cluster 4 is spatially distinct" (only 1-1 Spatial) |
| 0.25 | References 2 analyses | "Cluster 4 shows enriched pathways" (1-1 + 1-4) |
| 0.5 | References 3 analyses | "Cluster 4 pathways drive L-R interactions" (1-4 + 2-6 + 2-8) |
| 0.75 | References 4-5 analyses | Connects spatial, pathway, and CCI analyses |
| 1.0 | References 6+ analyses or spans all 3 Parts | Integrative hypothesis linking Part 1→2→3 |

**Calculation**: min(analyses_referenced / 4, 1.0) — normalized so that 4+ analyses = full score.

## Dimension 2: Specificity (Weight: 0.30)

**Measures**: Is the prediction concrete, quantitative, and falsifiable?

| Score | Criteria | Example |
|-------|----------|---------|
| 0.0 | Vague, unfalsifiable | "Cell types might interact somehow" |
| 0.25 | Directional but vague | "Some immune cells are probably enriched" |
| 0.5 | Named entities, directional | "Macrophages are enriched near cluster 4" |
| 0.75 | Specific entities + mechanism | "TGFB1-TGFBR2 signaling from fibroblasts drives EMT in cluster 4 epithelial cells" |
| 1.0 | Quantitative + falsifiable | "Cluster 4 shows >2-fold Moran's R for TGFB1-TGFBR2 compared to cluster 16, driven by fibroblast proximity (z-score > 3.0 in neighborhood analysis)" |

**Key indicators of specificity**:
- Names specific clusters, cell types, genes, L-R pairs
- Predicts direction (enriched/depleted, up/down)
- References quantitative thresholds (fold-change, p-value, z-score)
- Can be falsified by the available analysis data

## Dimension 3: Literature Grounding (Weight: 0.20)

**Measures**: Is the hypothesis supported by papers found in Step 3 (Literature Initialization)?

| Score | Criteria | Example |
|-------|----------|---------|
| 0.0 | No literature support, pure speculation | No relevant papers found |
| 0.25 | Tangentially related literature | Papers discuss the disease but not the specific mechanism |
| 0.5 | Partially supported | Papers discuss the pathway but in different tissue |
| 0.75 | Well-supported mechanism | Papers confirm the mechanism in same disease |
| 1.0 | Strong PMID-backed support | Multiple papers confirm the exact mechanism in same tissue/disease context |

**Assessment process**:
1. Check if any Step 3 papers mention the hypothesis entities
2. Check if the proposed mechanism is described in literature
3. Rate alignment between hypothesis prediction and literature evidence

## Dimension 4: Novelty (Weight: 0.20)

**Measures**: Does the hypothesis go beyond restating known biology?

| Score | Criteria | Example |
|-------|----------|---------|
| 0.0 | Restates textbook biology | "Cancer cells proliferate more than normal cells" |
| 0.25 | Known mechanism applied to this dataset | "VEGF signaling in tumor angiogenesis" (well-established) |
| 0.5 | Known mechanism in novel context | "VEGF signaling specifically between clusters 4 and 16" |
| 0.75 | Extends known mechanism | "VEGF-VEGFR2 spatial gradient creates an angiogenic niche at the tumor-stroma boundary" |
| 1.0 | Proposes testable new mechanism | "NMF factor 3 reveals a previously unreported spatial co-localization of WNT5A and SFRP2 suggesting a paracrine feedback loop" |

**Balance**: A perfect score (1.0) on Novelty but 0.0 on Grounding is suspicious — truly novel hypotheses should still connect to some existing knowledge.

## Scoring Examples

### Example 1: High-Quality Hypothesis (Score: 0.75)

**H: "TGF-β-mediated EMT at the tumor-stroma interface"**
- Prediction: "Fibroblasts in clusters 4/16 communicate with epithelial cells via TGFB1-TGFBR2, driving EMT. This will manifest as: (a) high Moran's R for TGFB1-TGFBR2 in Part 2-6, (b) enriched TGFb pathway in fibroblast-adjacent regions in Part 1-4, (c) co-localization of fibroblasts and epithelial cells in Part 1-3 neighborhood enrichment."

| Dimension | Score | Rationale |
|-----------|-------|-----------|
| Coverage | 0.75 | References 4 analyses: 1-3, 1-4, 2-6, 2-9 |
| Specificity | 0.75 | Names entities, mechanism, multiple testable predictions |
| Grounding | 1.0 | TGF-β EMT well-documented in literature |
| Novelty | 0.5 | Known mechanism applied to specific spatial context |

**Composite**: 0.30×0.75 + 0.30×0.75 + 0.20×1.0 + 0.20×0.5 = **0.75** ✓

### Example 2: Low-Quality Hypothesis (Score: 0.175)

**H: "Some immune cells might be important"**
- Prediction: "Immune cells could play a role in the tumor microenvironment."

| Dimension | Score | Rationale |
|-----------|-------|-----------|
| Coverage | 0.25 | Vaguely references cell composition (1-2 only) |
| Specificity | 0.0 | No specific cell types, no mechanism, unfalsifiable |
| Grounding | 0.5 | Immune involvement in TME is broadly supported |
| Novelty | 0.0 | Restates obvious biology |

**Composite**: 0.30×0.25 + 0.30×0.0 + 0.20×0.5 + 0.20×0.0 = **0.175** ✗ (below 0.4 → REMOVE)

### Example 3: Novel Discovery Hypothesis (Score: 0.65)

**H: "NMF Factor 2 reveals a spatially restricted paracrine WNT niche"**
- Prediction: "NMF factor 2 spatially overlaps with WNT pathway activity (Part 2-8) and co-localizes with WNT5A-FZD7 L-R pair (Part 2-6). This defines a paracrine WNT signaling niche where stromal cells secrete WNT5A to maintain epithelial stemness, visible as high ctSVG scores for WNT5A in the stromal compartment (Part 2-9)."

| Dimension | Score | Rationale |
|-----------|-------|-----------|
| Coverage | 0.75 | References 2-6, 2-7, 2-8, 2-9 |
| Specificity | 0.75 | Specific L-R pair, cell types, mechanism |
| Grounding | 0.25 | WNT in stemness is known, but this spatial niche is novel |
| Novelty | 0.75 | Proposes new spatial organization of WNT signaling |

**Composite**: 0.30×0.75 + 0.30×0.75 + 0.20×0.25 + 0.20×0.75 = **0.65** ✓

## Adaptation from Original HypoGeniC

| HypoGeniC Original | CCI Adaptation |
|--------------------|----------------|
| Accuracy on validation set | Evidence Coverage (fraction of analyses) |
| Hypothesis diversity (pairwise) | Specificity (prediction precision) |
| Literature relevance score | Literature Grounding (PMID alignment) |
| UCB exploration bonus | Novelty (discovery potential) |

The original HypoGeniC uses UCB (Upper Confidence Bound) to balance exploitation (high-accuracy hypotheses) and exploration (novel hypotheses). Our adaptation maps this to a weighted rubric that the LLM can self-evaluate during think_tool reflection.
