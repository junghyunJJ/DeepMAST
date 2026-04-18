# UCB Scoring Criteria for Drug Target Hypotheses

Adapted from HypoGeniC (Zhou et al., 2024) Upper Confidence Bound framework, specialized for drug target assessment.

## Composite Score Formula

```
Score = 0.30 x Evidence_Coverage + 0.30 x Specificity + 0.20 x Novelty + 0.20 x Actionability
```

**Threshold**: Hypotheses scoring below **0.4** are removed.
**Retention floor**: After filtering and FEATURED-gene coverage checks, retain at least `max(4, len(FEATURED))` hypotheses.
**Fallback**: If fewer than `max(4, len(FEATURED))` viable hypotheses remain, generate targeted `[FEATURED-GAP]` or other evidence-backed additions before rescoring.

---

## Dimension 1: Evidence Coverage (Weight: 0.30)

Measures how comprehensively the hypothesis draws on available evidence data.

| Score | Definition | Example |
|-------|-----------|---------|
| 0.0 | References no evidence files | Pure speculation with no data backing |
| 0.2 | References 1 evidence file | "TGFB1 has high biological plausibility" (rubric only) |
| 0.4 | References 2 evidence files | Uses rubric scores + one stage1 pair |
| 0.6 | References 3 evidence files | Uses rubric + stage1 pair + stage3 drugs |
| 0.8 | References 4 evidence files | Uses rubric + stage1 + stage3 + OT tractability |
| 1.0 | References 5+ evidence files | Integrates rubric + stage1 + stage2 + stage3 + Census data |

**Calculation**: `min(distinct_files_referenced / 4, 1.0)`

**Counting rules**:
- Each `stage1_*.json` counts as 1 file
- Each `stage3_*.json` counts as 1 file
- `rubric_scores.csv` counts as 1 file (regardless of how many genes cited)
- `stage2_evidence.json` counts as 1 file (regardless of how many genes cited)
- `ot_*.json` counts as 1 file per gene referenced
- `known_drugs.json` counts as 1 file
- Drug report markdown does NOT count (it's a synthesis, not primary evidence)

---

## Dimension 2: Specificity (Weight: 0.30)

Measures the precision and falsifiability of the hypothesis prediction.

| Score | Definition | Example |
|-------|-----------|---------|
| 0.0 | Vague statement, no named entities | "Inflammation may play a role in fibrosis" |
| 0.2 | Names entities but no mechanism | "TGFB1 is involved in IPF" |
| 0.3 | Mechanism stated but not directional | "ICAM1 mediates immune cell interactions in IPF lungs" |
| 0.5 | Directional prediction with named entities | "ICAM1 upregulation on fibrotic endothelium increases neutrophil transendothelial migration via ITGB2 binding" |
| 0.7 | Quantitative or conditional prediction | "Dual ICAM1+CXCR4 blockade reduces BAL neutrophil count by >50% compared to single-target blockade in bleomycin-induced IPF model" |
| 1.0 | Fully falsifiable with explicit failure criterion | "If EZR knockdown in primary human AT2 cells does not reduce ICAM1-mediated adhesion to THP-1 monocytes by >30% in transwell assay, the hypothesis is falsified" |

**Key rule**: A hypothesis MUST score >= 0.5 on Specificity to survive filtering. Hypotheses at 0.3 or below are automatically removed regardless of composite score.

---

## Dimension 3: Novelty (Weight: 0.20)

Measures discovery potential beyond established biology.

| Score | Definition | Example |
|-------|-----------|---------|
| 0.0 | Restates textbook biology | "TGF-beta drives fibrosis via SMAD signaling" |
| 0.2 | Known mechanism, well-established in this disease | "TGFB1 promotes fibroblast-to-myofibroblast transition in IPF" |
| 0.3 | Known mechanism, minor refinement | "TGFB1-P4HB interaction stabilizes collagen crosslinks in IPF fibrotic foci" |
| 0.5 | Known mechanism in novel cell type or context | "TREM2+ alveolar macrophages show unexpected TGFB1-dependent pro-resolution phenotype (supported by Census coexpression data)" |
| 0.7 | Novel combination of established mechanisms | "APOE-mediated lipid transport to TREM2+ macrophages creates a metabolic switch from pro-fibrotic to phagocytic phenotype, linking lipid metabolism to immune resolution" |
| 1.0 | Entirely new testable mechanism not established in any disease | "SDC2 heparan sulfate chains sequester latent TGFB1 in the ECM, creating spatial gradients that direct fibroblast chemotaxis — disrupting SDC2-TGFB1 binding abolishes directional fibroblast migration" |

**Guidance**: Category 4 (Novel Pathway) hypotheses should target >= 0.5 Novelty. Category 1 (MoA) hypotheses may score lower (0.2-0.5) and still be valuable if Evidence_Coverage and Specificity are high.

---

## Dimension 4: Actionability (Weight: 0.20)

Measures drug development feasibility and experimental testability.

| Score | Definition | Example |
|-------|-----------|---------|
| 0.0 | No path to drug development or experimental testing | Hypothesis about unmeasurable cellular state |
| 0.2 | Basic research testable but no therapeutic angle | "Census coexpression pattern reflects developmental lineage" |
| 0.3 | Target exists but no modality available | "RPSA overexpression drives fibrosis" (no tractability in OT) |
| 0.5 | Target has OT tractability but no clinical precedent for this disease | "GPC3 antibody (OT: AB tractable) could block Wnt-driven proliferation in IPF" |
| 0.7 | Target has clinical-stage drugs + clear validation path | "CXCR4 antagonist plerixafor (Phase III, SM) could be repurposed for IPF — test in bleomycin mouse model" |
| 1.0 | Directly repurposable drug with existing safety data for related indication | "Pirfenidone (approved IPF drug) + anti-ICAM1 combination — both drugs have Phase II+ safety profiles, direct path to combination trial" |

**Data sources for scoring**:
- OT tractability modalities (SM, AB, PR, OC) from `stage2_evidence.json` or `ot_*.json`
- ChEMBL drugs and max clinical phases from `stage3_*.json`
- Known disease drugs from `known_drugs.json`
- Safety profile score from `rubric_scores.csv`

---

## Score Interpretation Bands

| Band | Score Range | Interpretation |
|------|-----------|----------------|
| Exceptional | 0.70 - 1.00 | High-confidence hypothesis with strong evidence, specific prediction, novel insight, and clear drug development path |
| Strong | 0.50 - 0.69 | Well-supported hypothesis suitable for immediate experimental planning |
| Moderate | 0.40 - 0.49 | Acceptable hypothesis that may benefit from additional evidence or refinement |
| Weak | 0.30 - 0.39 | Below threshold under the active runtime contract; replace with additional FEATURED-coverage hypotheses instead of relaxing the threshold |
| Insufficient | 0.00 - 0.29 | Always remove |

---

## Edge Cases

**High coverage but vague prediction**: A hypothesis that cites 5+ evidence files but makes a non-specific claim (e.g., "TGFB1 pathway is important for IPF treatment") will score high on Evidence_Coverage (1.0) but low on Specificity (0.2). Composite: 0.30*1.0 + 0.30*0.2 + 0.20*0.3 + 0.20*0.5 = 0.52. Passes threshold but the Specificity minimum rule (>= 0.5) catches it. **Remove**.

**Novel but unsupported**: A creative hypothesis with minimal evidence backing. Evidence_Coverage 0.2, Specificity 0.7, Novelty 0.8, Actionability 0.3. Composite: 0.30*0.2 + 0.30*0.7 + 0.20*0.8 + 0.20*0.3 = 0.49. Passes threshold. **Keep** but note low evidence coverage.

**Actionable but unoriginal**: Known drug target with clear path. Evidence_Coverage 0.8, Specificity 0.7, Novelty 0.0, Actionability 1.0. Composite: 0.30*0.8 + 0.30*0.7 + 0.20*0.0 + 0.20*1.0 = 0.65. **Keep** — practical value outweighs low novelty.
