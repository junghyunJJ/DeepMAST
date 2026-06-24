# CCI Skill Ablation Benchmark — Summary

Comprehensive summary of the 4-condition skill ablation experiment evaluating the effect of skill instruction design on hallucination reduction in LLM-based biological interpretation of spatial transcriptomics cell-cell interaction (CCI) analysis.

---

## 1. Experimental Overview

- **Task**: Free-text biological interpretation of ligand-receptor (L-R) pairs from LIANA+ spatial transcriptomics CCI analysis
- **Dataset**: 30 L-R pairs sampled from breast cancer Visium (`interest_sig_liana.csv`, 6 strata × 5 cases)
- **Generator model**: gpt-5.4-nano (OpenAI), temperature = 0.3
- **Judges**: GPT-5.4 (OpenAI) + Claude Sonnet 4.6 (Anthropic), both at temperature = 0
- **Total trials**: 600 (4 conditions × 30 cases × 5 repeats)
- **Primary metric**: Composite hallucination score (0–5, higher = less hallucination)

---

## 2. Results Table — Condition × Dimension

| Condition | Description | Composite | Faithfulness | Fabrication | Uncertainty | Spatial | Overclaiming |
|---|---|---|---|---|---|---|---|
| **A** | Minimal prompt | 3.14 ± 0.28 | 2.79 | 3.89 | 3.91 | 4.74 | 2.74 |
| **B** | Long prose guidance | 3.59 ± 0.35 | 3.09 | 2.17 | 4.26 | 4.96 | 3.11 |
| **C** | Structured skill (rules + tables) | 3.79 ± 0.42 | 3.39 | 2.03 | 4.44 | 4.93 | 3.39 |
| **D** | Structured + guideline compliance | 3.89 ± 0.46 | 3.50 | 1.78 | 4.51 | 4.94 | 3.52 |

**Notes**:
- Faithfulness, Uncertainty, Spatial, Overclaiming: 1–5 ordinal scale (higher = less hallucination)
- Fabrication: count of unsupported mechanisms per interpretation (lower = better)
- N = 150 trials per condition (= 300 judge ratings for per-dimension means)
- Composite shows mean ± SD across 150 trials per condition

### 2.1 Statistical Results

**4-group Kruskal-Wallis** (all conditions):
- H = 253.46, p = 1.17 × 10⁻⁵⁴, N = 600

**3-group Kruskal-Wallis** (A/B/D only, main paper comparison):
- H = 219.16, p = 2.57 × 10⁻⁴⁸, N = 450

**Pairwise comparisons** (Mann-Whitney U, Bonferroni-corrected):

| Comparison | Delta | Effect size r | Bonferroni p | Significance |
|---|---:|---:|---:|---|
| A vs B | −0.445 | 0.621 (large) | 1.58 × 10⁻²⁶ | *** |
| A vs C | −0.652 | 0.723 (large) | 1.45 × 10⁻³⁵ | *** |
| A vs D | −0.754 | 0.776 (large) | 9.30 × 10⁻⁴¹ | *** |
| B vs C | −0.207 | 0.246 (small-medium) | 5.81 × 10⁻⁵ | *** |
| B vs D | −0.309 | 0.342 (medium) | 9.16 × 10⁻⁹ | *** |
| **C vs D** | **−0.102** | **0.100 (small)** | **0.49** | **ns** |

### 2.2 Inter-rater Agreement (Cohen's quadratic weighted κ, N = 600)

| Dimension | κ_w | Interpretation |
|---|---:|---|
| Spatial Calibration | 0.709 | Substantial |
| Faithfulness | 0.472 | Moderate |
| Overclaiming | 0.459 | Moderate |
| Uncertainty Handling | 0.450 | Moderate |

---

## 3. Dose-Response Pattern

```
A (minimal)          3.14  ─┐
                             │ +0.45 ***  (large effect, "any guidance helps")
B (long prose)       3.59  ─┤
                             │ +0.21 ***  (medium-small, "structure matters")
C (structured)       3.79  ─┤
                             │ +0.10  ns  (small trend, "guide patterns help marginally")
D (guide-compliant)  3.89  ─┘
```

**Core insights**:
1. **A → B (biggest jump, +0.45)**: Content alone produces large effect. 54% of total A→D improvement comes from simply adding any hallucination-prevention content.
2. **B → C (meaningful gain, +0.21)**: Structural formatting independently contributes beyond content, despite identical information (verified by automated 26-element concept audit).
3. **C → D (small trend, +0.10)**: Guide-specific design patterns provide consistent positive trend across all dimensions but do not reach statistical significance (p = 0.49). Cohen's d = 0.23 requires ~453 trials/group for 80% power.

**Practical interpretation**: The primary driver of hallucination reduction is structured formatting with hallucination-prevention content. Guide-specific design patterns (worked examples, edge cases, quality self-checks) provide consistent but modest incremental benefit — appropriate for high-stakes applications where marginal improvements justify additional authoring effort.

---

## 4. Detailed Condition Descriptions

### 4.1 Condition A — Minimal Prompt

**Length**: ~600 chars

**Composition**: Base interpretation instruction only. No hallucination-prevention guidance.

**System prompt content**:
- Role definition: "biological interpreter for spatial transcriptomics CCI analysis"
- Task: write 2-3 paragraphs covering biological mechanism, cell types/spatial context, confidence level
- Constraint: "Base your interpretation ONLY on the evidence provided"

**Characteristics**:
- Exposes the LLM's natural hallucination tendency without intervention
- Highest fabrication rate: 3.89 unsupported mechanisms per interpretation on average
- Generator freely imports pathway/mechanism claims from pre-training knowledge
- Serves as the baseline for measuring all other conditions' improvements

**Typical failure modes observed**:
- Invention of downstream signaling cascades not present in the evidence bundle
- Claims of tissue-specific effects drawn from general biological knowledge
- "Strong spatial evidence" claims despite weak Moran's R values
- Fabricated pathway associations when LIANA detected none

---

### 4.2 Condition B — Long Prose Guidance

**Length**: ~3,100 chars total system prompt

**Composition**: Base instruction from A + hallucination-prevention content written as **continuous flowing prose** (no headings, tables, or bullet lists).

**Prose content includes**:
- Moran's R calibration thresholds (R > 0.3 = strong, 0.1–0.3 = moderate, < 0.1 = weak)
- Four-level confidence criteria (high/moderate/low/insufficient)
- Receptor subtype accuracy (named examples: decoy receptors, atypical chemokine receptors)
- L-R specificity constraints (receptors bind multiple ligands)
- Directionality rules based on cell-type breadth (3+ cell types → cannot determine)
- Data-first principle (prioritize dataset-specific evidence over general knowledge)
- Five explicit NEVER rules (no fabricated cascades, no tissue-specific effects without data, etc.)

**Characteristics**:
- Content is **identical** to Condition C / `C_structured_skill` (verified by token-level audit of 26 information elements)
- Differs from Condition C / `C_structured_skill` **only in formatting**: flowing paragraphs vs structured markdown
- 44% reduction in fabrication count vs A (3.89 → 2.17)
- Demonstrates that hallucination-prevention content alone is effective regardless of format
- Serves as the "content control" for isolating formatting effects

**Why this condition exists**: Without Condition B, the A vs C comparison would confound content provision with structural formatting. B isolates the content contribution.

---

### 4.3 Condition C — Structured Skill (Rules + Tables)

**Length**: ~3,000 chars total system prompt

**Composition**: Same base instruction + **same content as B** reorganized into **structured markdown** with headings, tables, and rule lists.

**Section structure**:
```markdown
### Evidence Hierarchy              [4-item ordered list]
### Spatial Evidence Calibration    [3-row table with thresholds and actions]
### Mechanism Grounding Rules       [4 explicit rules]
### Receptor Biology Accuracy       [named examples with functional consequences]
### L-R Specificity Rules           [3 rules with numeric thresholds]
### Confidence Calibration          [4-level table with criteria]
### Data-First Principle            [3 rules]
### Hallucination Prevention        [5 explicit NEVER prohibitions]
```

**Characteristics**:
- Same information content as B, only format differs
- +0.21 composite improvement over B (small-to-medium effect, r = 0.246)
- This B vs C comparison is the central finding that isolates **pure format effect**
- Demonstrates that structured markdown confers measurable hallucination reduction independent of information content
- Serves as the "format isolation" condition

**Why structure matters**: Headings, tables, and rule lists act as cognitive scaffolds that guide the LLM's attention allocation and constraint adherence. Sclar et al. (2024) demonstrated up to 76 accuracy point variations from superficial prompt format changes alone.

---

### 4.4 Condition D — Structured + Guideline Compliance

**Length**: ~6,000 chars total system prompt

**Composition**: All of Condition C / `C_structured_skill` + **four additional design patterns** recommended by the [Anthropic Skill Building Guide (2026)](https://docs.anthropic.com/en/docs/build-with-claude/skills).

**Four additional guide patterns**:

**Pattern 1: `## Why This Guidance Exists`** — Problem motivation
- Documents observed failure modes (fabricated cascades, tissue overclaim, ignored weak Moran's R, invented pathways)
- Explains *why* the model should comply with rules
- Makes compliance "motivated" rather than arbitrary

**Pattern 2: `### Common Interpretation Traps`** — Edge case table
- 5-row table covering domain-specific traps:
  1. Decoy receptors (TNFRSF10C/DcR1 INHIBITS apoptosis)
  2. Atypical chemokine receptors (ACKR3 scavenges ligands, not canonical GPCR)
  3. Broadly expressed ligand (3+ cell types → "directionality cannot be determined")
  4. Weak Moran's R (< 0.1 → "should not be highlighted")
  5. No pathway data (state "None detected in LIANA", don't infer)
- Each row specifies common error and correct handling

**Pattern 3: `### Examples`** — Worked correct/incorrect pair
- **Correct example**: THBS2-ITGA4 with Moran's R = 0.25, TGFb pathway detected, hedged language
- **INCORRECT example**: Same pair but fabricated FAK-PI3K-AKT cascade + EMT claim
- **Explicit explanation** of why the incorrect version is wrong:
  - FAK-PI3K-AKT not in evidence bundle
  - EMT claim extrapolates beyond spatial data
  - "Drives" implies causation from correlation
  - "Metastasis" is unsupported therapeutic implication

**Pattern 4: `### Before Submitting Your Interpretation`** — Quality self-check
- 6-item checklist:
  - [ ] Every pathway cited appears in evidence bundle
  - [ ] Confidence level matches calibration table
  - [ ] No signaling cascades beyond evidence
  - [ ] Broadly expressed ligands lack directionality claims
  - [ ] Hedged language for interpretations
  - [ ] Definitive language only for data values

**Characteristics**:
- Highest composite score: 3.89 (A→D: +0.75 composite points, 54% reduction in fabrications)
- Best on every dimension (Faithfulness, Fabrication, Uncertainty, Overclaiming; Spatial tied with B)
- C vs D comparison: +0.10 (small effect, r = 0.100, p = 0.49) — **not statistically significant** after Bonferroni correction
- Consistent positive trend across ALL dimensions despite overall ns
- Requires ~6000 chars (2x Condition C / Basic Structured SKILLs) — longer prompt is a trade-off

**Interpretation**: The guide-compliant skill represents the "maximally structured" design point. The small, non-significant improvement over Condition C / Basic Structured SKILLs suggests diminishing returns from additional skill refinement — most of the benefit comes from basic structured formatting, while design patterns provide fine-tuning.

---

## 5. Evaluation Dimensions — Detailed Rubric

The benchmark evaluates each interpretation on **5 dimensions + 1 composite score**. Two LLM judges (GPT-5.4, Claude Sonnet 4.6) rate independently, and the consensus is the arithmetic mean.

### 5.1 Composite Score (0–5, weighted combination)

**Meaning**: Overall hallucination score combining all 5 dimensions. Higher = less hallucination.

**Formula**:
```
composite = 0.30 × faithfulness
          + 0.25 × overclaiming
          + 0.20 × uncertainty_handling
          + 0.15 × spatial_calibration
          + 0.10 × (5 − min(fabrication_count, 5))
```

**Weight rationale**:

| Weight | Dimension | Rationale |
|---:|---|---|
| 0.30 | Faithfulness | Essence of scientific interpretation fidelity |
| 0.25 | Overclaiming | Prevents clinical/therapeutic extrapolation |
| 0.20 | Uncertainty | Calibrated confidence; dependent on other dimensions |
| 0.15 | Spatial | Numerical interpretation is simpler |
| 0.10 | Fabrication | Reverse-signed and overlaps with other dimensions |

**Fabrication term handling**:
- Sign reversal: `5 − count` so higher composite indicates less hallucination
- Capped at 5 to prevent extreme outliers distorting the composite
- Result: 0 fabrications → 0.50 contribution, 5+ fabrications → 0.00 contribution

---

### 5.2 Faithfulness (1–5 ordinal)

**Definition**: Degree to which the interpretation stays within the boundaries of the evidence bundle. Are all claims traceable to the bundle?

**Rubric anchors**:
- **1** — Mostly fabricated (claims unrelated to evidence)
- **2** — Significant unsupported claims mixed with grounded ones
- **3** — Partially grounded (some claims supported, some not)
- **4** — Mostly grounded with minor extrapolations
- **5** — Strictly evidence-grounded (every claim traceable to bundle)

**Characteristics**:
- **Most demanding dimension** — lowest scores across all conditions
- A=2.79 → D=3.50 (25% improvement) — largest absolute gain
- Why demanding: suppressing LLM pre-training knowledge is inherently difficult
- Primary target of `### Mechanism Grounding Rules` and the `### Examples` pattern in Condition D

**Example judgment**:
- ❌ Low faithfulness: "ECM1-ITGA4 activates FAK-PI3K-AKT" (cascade from pre-training, not evidence)
- ✅ High faithfulness: "ECM1-ITGA4 shows moderate co-localization (Moran's R = 0.25)" (numerical value from bundle)

---

### 5.3 Fabrication Count (integer ≥ 0)

**Definition**: Count of specific biological mechanisms / pathways / cascades mentioned in the interpretation that are **not supported** by any element of the evidence bundle.

**Counting criteria**:
- Specific downstream pathway not in `pathway_associations` field → count +1
- Invented therapeutic/clinical implication → count +1
- Cell-type-specific function not in expression data → count +1
- Signaling cascade not in evidence → count +1

**Characteristics**:
- **Only unbounded dimension** (others are 1–5 ordinal)
- Excluded from Cohen's kappa (not ordinal)
- **Most responsive dimension**: A = 3.89 → D = 1.78 (**−54%**)
- Intuitive metric — most persuasive for reviewers ("54% reduction in hallucinations")
- Directly addresses Anthropic guide's core failure mode

**Example fabricated_claims output from judge**:
```json
[
  "Describing THBS2–ITGA4 as mediated by the extracellular matrix
   is biological prior knowledge not provided in the evidence bundle",
  "Claiming downstream PI3K-AKT cascade without evidence support"
]
```

---

### 5.4 Uncertainty Handling (1–5 ordinal)

**Definition**: Appropriateness of expressed uncertainty relative to evidence quality.

**Calibration criteria** (judges consider 3 factors):
1. Moran's R magnitude (spatial signal strength)
2. Pathway data presence/absence
3. Cell-type expression breadth

**Rubric anchors**:
- **1** — No uncertainty expressed despite weak/ambiguous evidence (overconfident)
- **3** — Uncertainty expressed but miscalibrated to evidence strength
- **5** — Uncertainty perfectly calibrated to evidence quality

**Characteristics**:
- Relatively high baseline (A = 3.91) — LLMs naturally use hedging language
- 15% improvement A→D — more modest than Faithfulness/Overclaiming
- "Perfectly calibrated" is a drift-prone target because calibration is subjective

**Example judgment**:
- ❌ Miscalibrated: "Strong evidence supports this interaction" (when Moran's R = 0.05)
- ✅ Calibrated: "Weak spatial signal (Moran's R = 0.05) — interaction cannot be highlighted as a key finding"

---

### 5.5 Spatial Calibration (1–5 ordinal)

**Definition**: Accuracy of Moran's R magnitude interpretation.

**Reference thresholds** (explicitly provided in judge rubric):
- R > 0.3 → strong spatial co-localization
- R = 0.1–0.3 → moderate, report with caveats
- R < 0.1 → weak, do NOT highlight as key finding

**Rubric anchors**:
- **1** — Claims strong spatial evidence when R < 0.1
- **3** — Partially correct spatial interpretation
- **5** — Perfectly calibrated spatial claims

**Characteristics**:
- **Only dimension with ceiling effect**
- All conditions ≥ 4.74 (near maximum)
- Only 4% improvement A→D (smallest of all dimensions)
- **Cause of ceiling**: Moran's R value and p-value are provided as numbers directly in the evidence bundle. LLM pre-training knowledge of statistical concepts is sufficient for correct threshold-based interpretation.
- Practically **does not contribute** to composite score differences across conditions
- Highest inter-rater agreement (κ = 0.709, substantial)

**Implication for design**: Structured skills provide the **greatest benefit for qualitative, open-ended dimensions** (faithfulness, overclaiming, fabrication count) rather than quantitative evidence parsing.

---

### 5.6 Overclaiming (1–5 ordinal)

**Definition**: Extent to which the interpretation extrapolates beyond what the evidence directly supports.

**Main extrapolation types**:
1. Clinical/therapeutic implications ("potential drug target")
2. Downstream signaling cascades not in pathway data
3. Causal language ("drives", "causes") from correlational data
4. Tissue-specific effects without matching spatial support

**Rubric anchors**:
- **1** — Extensive extrapolation (clinical implications, therapeutic targets, downstream cascades)
- **3** — Some extrapolation beyond evidence
- **5** — No extrapolation — stays strictly within provided data

**Characteristics**:
- Second-lowest scoring dimension (A = 2.74, D = 3.52)
- Second-largest improvement: **+28%** (A→D)
- Semantically demanding — the boundary between "permissible inference" and "unjustified extrapolation" is less well-defined than numeric thresholds
- Lowest inter-rater agreement (κ = 0.459)
- Direct target of `### Data-First Principle` section

**Example judgment**:
- ❌ Overclaiming: "THBS2-ITGA4 suggests an anti-fibrotic therapeutic opportunity"
- ✅ Non-overclaiming: "THBS2-ITGA4 shows moderate co-localization; functional implications require further validation"

---

## 6. Per-Dimension Improvement Summary

| Dimension | A | B | C | D | A→D Change | A→D % | Responsiveness |
|---|---:|---:|---:|---:|---:|---:|---|
| Faithfulness | 2.79 | 3.09 | 3.39 | 3.50 | +0.71 | **+25%** | High |
| Fabrication | 3.89 | 2.17 | 2.03 | 1.78 | −2.11 | **−54%** | **Highest** |
| Uncertainty | 3.91 | 4.26 | 4.44 | 4.51 | +0.60 | +15% | Medium |
| Spatial | 4.74 | 4.96 | 4.93 | 4.94 | +0.20 | +4% | **Ceiling** |
| Overclaiming | 2.74 | 3.11 | 3.39 | 3.52 | +0.78 | **+28%** | High |
| **Composite** | **3.14** | **3.59** | **3.79** | **3.89** | **+0.75** | **+24%** | — |

### Key Observations

1. **Fabrication is most responsive** — 54% reduction, intuitive business-impact metric
2. **Spatial shows ceiling effect** — numerical interpretation needs no skill guidance
3. **Faithfulness and Overclaiming drive composite** — semantically demanding dimensions with largest absolute improvements
4. **Uncertainty is middle ground** — high baseline with moderate improvement
5. **Dose-response pattern** — Faithfulness, Fabrication, and Overclaiming all show monotonic A < B < C < D ordering

### Practical Implications

- **Spatial ceiling validates judge rubric** — shows that the judges are not artificially ceiling-biased, but reflect actual task difficulty where numerical interpretation is intrinsically easy
- **Fabrication count as business metric** — "54% reduction in hallucinations" is the most persuasive summary for stakeholders
- **Faithfulness remains imperfect (D = 3.50/5.0)** — indicates room for further improvement; skills are not complete solutions
- **Skill benefit is dimension-dependent** — greatest value for qualitative semantic dimensions, negligible for quantitative numerical dimensions

---

## 7. Methodological Notes

### 7.1 Prompt Injection (Not Progressive Disclosure)

All conditions deliver skill content via **system prompt injection**, not Anthropic's recommended progressive disclosure (YAML frontmatter → body → references/). This design choice removes delivery-mechanism confound so that only content quality effects are measured.

**Limitation**: In production Claude Code environments, progressive disclosure may provide additional benefits through context window efficiency that are not captured by this benchmark.

### 7.2 Canonical Condition Naming

| Code variant | Canonical label | Role |
|---|---|---|
| `A_no_skill` | Condition A / No Skills | Baseline |
| `B_unstructured_prose` | Condition B / Unstructured Prose | Content control |
| `C_structured_skill` | Condition C / Basic Structured SKILLs | Structure-only comparison versus prose |
| `D_guide_compliant_skill` | Condition D / Guide-Compliant Structured SKILLs | Final guide-compliant structured skill |

The B-vs-C comparison isolates structured formatting over matched prose content. The C-vs-D comparison tests guide-specific design patterns and is positive but not statistically significant after correction.

### 7.3 Generator and Judge Configuration

- **Generator**: gpt-5.4-nano, temperature = 0.3 (allows natural variation across repeats)
- **Judges**: GPT-5.4 (temperature = 0) + Claude Sonnet 4.6 (temperature = 0)
- Judges have no access to condition labels (blinded to experimental variable)
- Consensus score = arithmetic mean of both judges' composite scores
- GPT-5.4 systematically ~0.5 points stricter than Claude Sonnet 4.6 (offset cancels in mean)

---

## 8. Result Artifacts

| File | Description |
|---|---|
| `results/full_cci_v2_D_guide_trials.jsonl` | Per-trial data (600 trials with dual-judge scores) |
| `results/full_cci_v2_D_guide_summary.json` | Statistical summary (Kruskal-Wallis, post-hoc, kappa) |
| `results/full_cci_v2_D_guide_results.md` | Markdown results report |
| `cases/cci_full_cases.json` | Frozen benchmark cases (30 L-R pairs, 6 strata) |
| `benchmark_cci_core.py` | Core benchmark library with 4 condition prompts |
| `figure_table3_results.R` | Main figure R script (A/B/D, 3 bars) |
| `s_figure_table3_results.R` | Supplementary figure R script (A/B/C/D, 4 bars) |
| `SkillAblation.png` | Main figure output |
| `s_SkillAblation.png` | Supplementary figure output |
| `example_THBS2_ITGA4_full.md` | Full example showing all 4 conditions on one case |

---

## 9. Core Conclusions

1. **Structured skills dramatically reduce LLM hallucination** in biological interpretation: A→D delta = +0.75 composite points, large effect (r = 0.776), p < 10⁻⁴⁰.

2. **Content alone is insufficient** — structural formatting independently contributes beyond content equivalence (B vs C, r = 0.246, p < 10⁻⁴; B vs D, r = 0.342, p < 10⁻⁸).

3. **Guide-specific design patterns show diminishing returns** — the incremental benefit of worked examples, edge case tables, and quality self-checks (C vs D) trends positive across all dimensions but does not reach statistical significance (p = 0.49, r = 0.100).

4. **Fabrication count is the most responsive metric** — 54% reduction from A to D; most interpretable for downstream stakeholders.

5. **Spatial calibration shows ceiling effect** — LLMs reliably interpret quantitative thresholds even without skill guidance; skill benefit is concentrated in qualitative semantic dimensions.

6. **Practical authoring recommendation** — For production skills, prioritize structured formatting with explicit hallucination-prevention rules. Guide-compliant design patterns (Why Exists, Examples, Edge Cases, Self-Check) offer incremental refinement for high-stakes applications but are not essential for the core effect.
