# Scoring Guide for Evolution Reasoning

## Calibration Bands

Use these anchors consistently across all dimensions:

| Score Range | Label | Meaning | Justification Required? |
|-------------|-------|---------|------------------------|
| 0.90 - 1.00 | Excellent | Genuinely outstanding. Specific evidence supports this. | YES — must cite what makes it exceptional |
| 0.70 - 0.89 | Good | Clearly above average with minor issues. | Brief note on what's strong |
| 0.50 - 0.69 | Acceptable | Meets minimum bar but has notable weaknesses. | Note the weaknesses |
| 0.30 - 0.49 | Weak | Significant problems that need addressing. | List specific problems |
| 0.00 - 0.29 | Poor | Fundamentally flawed or missing. | Explain what's wrong or absent |

**The default score for an "okay" item should be around 0.6, not 0.8.** Most items are acceptable, not good. Reserve high scores for genuinely strong work.

---

## Common Pitfalls

### 1. Score Inflation

**What it is**: Giving 0.8+ to items that are merely acceptable.

**Why it happens**: LLMs tend to rate their own outputs favorably. "This seems reasonable" becomes 0.85.

**How to avoid**: Before assigning a score above 0.8, ask: "What specific evidence makes this better than average?" If you can't name concrete strengths, lower the score to 0.6-0.7.

### 2. Score Compression

**What it is**: All items score between 0.7-0.8 regardless of actual quality differences.

**Why it happens**: Reluctance to give very high or very low scores.

**How to avoid**: Force spread. At least one item should score below 0.5 on at least one dimension. If all items look similar, the dimensions may be too coarse — consider subdividing.

### 3. Confirmation Bias

**What it is**: Rating items higher because they align with what you would have generated.

**Why it happens**: Same-model self-critique inherently favors similar reasoning patterns.

**How to avoid**: Score each dimension independently. Ask "Is the evidence actually there?" rather than "Does this sound right?" Focus on what's verifiable, not what's plausible.

### 4. Dimension Conflation

**What it is**: Letting one dimension's score bleed into another. A well-written item gets high "accuracy" even when the accuracy is unverified.

**Why it happens**: Halo effect — a strong impression in one area lifts all scores.

**How to avoid**: Score dimensions in isolation. Cover the other dimension scores when evaluating each one. Ask the dimension-specific question only.

---

## Domain-Specific Scoring Examples

### Hypotheses (e.g., drug-target-hypothesis)

| Dimension | 0.3 (Weak) | 0.6 (Acceptable) | 0.9 (Excellent) |
|-----------|-----------|------------------|-----------------|
| Evidence Coverage | Cites 1 evidence file | Cites 2-3 files with specific findings | Cites 4+ files with quantitative data points |
| Specificity | Vague prediction ("X may affect Y") | Named intervention + measurable outcome | Named intervention + outcome + model system + failure criterion |
| Novelty | Restates known biology | Combines known elements in a new way | Identifies unexpected connection from the data |
| Actionability | No clear experimental path | Feasible experiment identified | Specific protocol with controls and readouts |

### Research Questions

| Dimension | 0.3 (Weak) | 0.6 (Acceptable) | 0.9 (Excellent) |
|-----------|-----------|------------------|-----------------|
| Clarity | Ambiguous scope | Clear but broad | Precisely bounded with defined terms |
| Feasibility | Requires unavailable resources | Doable with significant effort | Achievable with existing tools and data |
| Impact | Incremental confirmation | Useful practical knowledge | Could change current understanding or practice |

### Experimental Designs

| Dimension | 0.3 (Weak) | 0.6 (Acceptable) | 0.9 (Excellent) |
|-----------|-----------|------------------|-----------------|
| Internal Validity | Missing controls | Appropriate controls identified | Controls + confounders + blinding addressed |
| Statistical Power | No sample size justification | Reasonable N with basic justification | Power analysis with effect size estimates |
| Reproducibility | Key details omitted | Methods section present | Full protocol with reagents, settings, and code |

---

## Critique Writing Guide

Each critique point must be:

1. **Specific**: Name the exact weakness. Not "lacks detail" but "the mechanism connecting X to Y is not explained."

2. **Actionable**: Suggest what to do. Not "improve evidence" but "add STRING PPI score for the X-Y interaction from stage1_X--Y.json."

3. **Bounded**: One issue per point. Don't combine "weak evidence AND unclear mechanism" into one critique.

**Good critique examples**:
- "The hypothesis claims TGFB1 drives fibrosis but cites no PPI data for the TGFB1-receptor interaction. Add STRING scores from stage1_TGFB1--P4HB.json."
- "The falsifiable prediction lacks a failure criterion. Add: 'If knockout of X does not reduce Y by >50%, the hypothesis is falsified.'"
- "Evidence Coverage is low (2/8 files cited). The stage3_ICAM1.json ChEMBL data and stage1_ICAM1--EZR.json Census coexpression data are relevant but unused."

**Bad critique examples**:
- "Needs more evidence" (not specific)
- "This is a weak hypothesis" (not actionable)
- "The writing could be improved and the evidence is thin and the prediction is vague" (not bounded — three issues in one)

---

## Composite Score Calculation

```
composite = sum(score[dim] * weight[dim] for dim in dimensions)
```

**Example**: dimensions = {accuracy: 0.4, clarity: 0.3, depth: 0.3}

| Dimension | Score | Weight | Contribution |
|-----------|-------|--------|-------------|
| accuracy | 0.8 | 0.4 | 0.32 |
| clarity | 0.6 | 0.3 | 0.18 |
| depth | 0.7 | 0.3 | 0.21 |
| **Composite** | | | **0.71** |

Weights must sum to ~1.0. If they don't, normalize before calculating.
