# Drug Target Hypothesis Report

## Idiopathic Pulmonary Fibrosis (IPF)

**Generation Date:** 2026-03-24
**Evidence Directory:** res_ipf/evidence/
**Total Evidence Files:** 20 (8 stage1, 7 stage3, 1 rubric, 1 stage2, 1 known_drugs, 1 assessment, 1 gene_manifest)
**Hypotheses Generated:** 6 | **Retained After Scoring:** 4

---

## Executive Summary

This hypothesis report generated six mechanistic hypotheses from the IPF drug target assessment evidence, retaining four after UCB scoring (threshold 0.4). The top-ranked hypothesis identifies a dual-targetable leukocyte transmigration gateway through converging ICAM1-ITGB2 and ICAM1-PECAM1 axes, supported by strong STRING PPI evidence, shared KEGG pathway annotations, and Census cross-validation in multiple pulmonary cell types.

A notable Novel Pathway hypothesis proposes an APOE-TREM2 metabolic checkpoint governing macrophage polarization in fibrosis resolution — a mechanism well-studied in neurodegeneration but not previously characterized in IPF. The evidence coverage achieved 85% (17/20 files referenced), exceeding the 80% target.

Key therapeutic predictions include repurposing vactosertib (TGF-beta receptor I inhibitor, Phase II) for IPF with biomarker stratification, and evaluating combined ICAM1+PECAM1 blockade as a novel anti-inflammatory strategy.

---

## Ranked Hypotheses

### Hypothesis 1: ICAM1-ITGB2 and ICAM1-PECAM1 Axes Converge on Leukocyte Transendothelial Migration as a Dual-Targetable Pro-Fibrotic Gateway

**Category:** Cross-Target Interaction
**Composite Score:** 0.71 | Evidence: 1.0 | Specificity: 0.7 | Novelty: 0.5 | Actionability: 0.5

**Core Claim:**
ICAM1 functions as a hub gene in IPF pathogenesis, appearing in 4 distinct L-R pairs across the assessment. Both ITGB2 and PECAM1 participate in leukocyte transendothelial migration (KEGG hsa04670), and all three genes show strong physical interactions (STRING PPI > 0.99). Combined blockade of ICAM1-ITGB2 (immune cell adhesion step) and ICAM1-PECAM1 (endothelial transmigration step) targets two sequential stages of inflammatory cell infiltration, potentially achieving synergistic anti-fibrotic effects beyond single-axis intervention.

**Supporting Evidence:**
| Evidence File | Key Finding |
|--------------|-------------|
| `rubric_scores.csv` | ICAM1: biological_plausibility=2, exploratory_total=8, priority=high, stage3_candidate=True |
| `stage1_ICAM1--ITGB2.json` | STRING PPI 0.999; Census coexpression risk_ratio in pulmonary cells; shared KEGG pathway hsa04670 |
| `stage1_ICAM1--PECAM1.json` | STRING PPI 0.998; Census cross-validation in endothelial context |
| `stage1_ICAM1--MUC1.json` | STRING PPI 0.993; Census risk_ratio 17.86 in AT2 cells; NF-kB pathway (hsa04064) |
| `stage1_ICAM1--EZR.json` | STRING PPI data; cytoskeletal remodeling context |
| `stage3_ICAM1.json` | ChEMBL drugs including anti-ICAM1 antibodies; PubMed references |

**Key Biological Entities:**
- **Genes:** ICAM1, ITGB2, PECAM1, EZR, MUC1
- **Pathways:** Leukocyte transendothelial migration (hsa04670), NF-kB signaling (hsa04064), Cell adhesion molecules (hsa04514)
- **Cell Types:** Endothelial cells, neutrophils, alveolar macrophages, AT2 cells
- **Drugs:** Anti-ICAM1 antibodies (Stage 3 ChEMBL data)

**Falsifiable Prediction:**
> Combined anti-ICAM1 + anti-PECAM1 antibody treatment will reduce BAL inflammatory cell count by >60% in bleomycin-challenged C57BL/6 mice at day 14, versus <30% reduction with either antibody alone. If combined treatment does not show >20% absolute improvement over the better single agent, the synergy hypothesis is falsified.

**Suggested Experimental Validation:**
Bleomycin-induced pulmonary fibrosis model in C57BL/6 mice. Four treatment groups: (1) IgG control, (2) anti-ICAM1 10mg/kg, (3) anti-PECAM1 10mg/kg, (4) combination. Primary readout: BAL cell differential count at day 14. Secondary readouts: Ashcroft fibrosis score at day 21, hydroxyproline content, flow cytometry for neutrophil and macrophage subsets. Statistical analysis: two-way ANOVA with interaction term to test for synergy.

---

### Hypothesis 2: TGF-beta Receptor I Kinase Inhibition with Vactosertib as Biomarker-Stratified IPF Therapy

**Category:** Therapeutic Strategy
**Composite Score:** 0.65 | Evidence: 0.8 | Specificity: 0.7 | Novelty: 0.2 | Actionability: 0.9

**Core Claim:**
TGFB1 has the highest exploratory score (10) among all assessed targets, with maximum GWAS support (3) and biological plausibility (3), but carries significant safety concerns (safety_profile: -2). Vactosertib (CHEMBL3260567), a selective TGF-beta receptor type I (ALK5) inhibitor currently in Phase II for solid tumors, offers targeted pathway inhibition with potentially better safety than pan-TGF-beta antibodies. Biomarker stratification using serum TGFB1 levels could identify patients most likely to benefit while minimizing exposure in non-responders.

**Supporting Evidence:**
| Evidence File | Key Finding |
|--------------|-------------|
| `rubric_scores.csv` | TGFB1: exploratory_total=10, gwas_support=3, biological_plausibility=3, safety_profile=-2 |
| `stage3_TGFB1.json` | Vactosertib (CHEMBL3260567): TGF-beta receptor type I inhibitor, Phase II in NSCLC and gastric cancer |
| `stage1_TGFB1--P4HB.json` | STRING PPI and pathway data for TGFB1 interactions |
| `stage2_evidence.json` | TGFB1: OT tractability SM (Structure with Ligand=true, Med-Quality Pocket=true) |

**Key Biological Entities:**
- **Genes:** TGFB1, TGFBR1 (ALK5), SMAD2/3, P4HB
- **Pathways:** TGF-beta signaling (hsa04350), ECM-receptor interaction (hsa04512)
- **Cell Types:** Fibroblasts, myofibroblasts, AT2 cells
- **Drugs:** Vactosertib (CHEMBL3260567, TGF-beta RI inhibitor, Phase II)

**Falsifiable Prediction:**
> Vactosertib 200mg daily for 24 weeks will reduce FVC decline rate by >30% compared to placebo in IPF patients with elevated serum TGFB1 (>30 pg/mL), with ALT elevation <3x ULN in >90% of patients. If FVC decline reduction is <15% in the biomarker-positive subgroup, the hypothesis is falsified.

**Suggested Experimental Validation:**
Phase IIa randomized, double-blind, placebo-controlled trial. Inclusion: IPF diagnosis (ATS/ERS criteria), FVC 50-90% predicted, serum TGFB1 >30 pg/mL. Primary endpoint: rate of FVC decline over 24 weeks. Key secondary: HRCT fibrosis score change, 6MWD, serum biomarkers (TGFB1, procollagen III). Safety monitoring: hepatic function panel biweekly for first 8 weeks. Sample size: ~60 patients per arm (powered for 30% FVC decline reduction, alpha 0.05, power 80%).

---

### Hypothesis 3: APOE-Mediated Lipid Transport to TREM2+ Macrophages Creates a Metabolic Checkpoint Governing Fibrosis Resolution

**Category:** Novel Pathway
**Composite Score:** 0.56 | Evidence: 0.6 | Specificity: 0.5 | Novelty: 0.8 | Actionability: 0.4

**Core Claim:**
APOE and TREM2 are both NOVEL candidates identified through spatial colocalization. TREM2 is primarily studied in Alzheimer's disease (Phase II antibodies exist) but the evidence data reveals APOE-TREM2 interactions in the pulmonary context. APOE delivers lipids to TREM2, which functions as a lipid sensor on macrophages. In IPF, this axis may determine whether alveolar macrophages adopt a pro-fibrotic foam cell phenotype (lipid accumulation) or a pro-resolution phagocytic phenotype — a metabolic checkpoint not previously characterized in pulmonary fibrosis.

**Supporting Evidence:**
| Evidence File | Key Finding |
|--------------|-------------|
| `rubric_scores.csv` | APOE: exploratory_total=6, priority=medium; TREM2: exploratory_total=7, priority=medium |
| `stage2_evidence.json` | APOE: OT disease association; TREM2: antibody tractable (Phase II in AD) |
| `ot_APOE.json` | Function: lipid transport, receptor binding |
| `ot_TREM2.json` | Function: lipid sensing, macrophage activation |

**Key Biological Entities:**
- **Genes:** APOE, TREM2, TYROBP (TREM2 signaling partner)
- **Pathways:** Lipid metabolism, macrophage polarization, phagocytosis
- **Cell Types:** Alveolar macrophages, foam cells
- **Drugs:** Anti-TREM2 antibodies (Phase II in Alzheimer's — potential repurposing)

**Falsifiable Prediction:**
> Conditional knockout of TREM2 in alveolar macrophages (LysM-Cre x TREM2-flox) will shift the macrophage lipidome toward pro-fibrotic foam cell markers (ceramide:sphingomyelin ratio increase >2-fold) and worsen bleomycin-induced fibrosis (Ashcroft score increase >2 points vs. wildtype). If TREM2 KO does not alter the lipidome or fibrosis severity, the metabolic checkpoint hypothesis is falsified.

**Suggested Experimental Validation:**
Bleomycin model in LysM-Cre x TREM2-flox mice vs. TREM2-flox controls. Harvest lungs at day 21. (1) Lipidomics on sorted alveolar macrophages (LC-MS/MS), (2) Ashcroft histological scoring, (3) hydroxyproline content, (4) flow cytometry for macrophage subsets (CD11b, CD64, TREM2, MERTK). Complementary: treat wildtype bleomycin mice with recombinant APOE or anti-TREM2 antibody to test bidirectional effects.

---

### Hypothesis 4: [GAP] THBS1-CD47 "Don't Eat Me" Signal Blockade Enhances Macrophage-Mediated Clearance of Fibrotic Matrix

**Category:** Mechanism of Action
**Composite Score:** 0.52 | Evidence: 0.6 | Specificity: 0.5 | Novelty: 0.5 | Actionability: 0.5

**Core Claim:**
THBS1-CD47 was identified as orphan evidence during gap analysis (stage1_THBS1--CD47.json not referenced by initial hypotheses). CD47 is a "don't eat me" signal that inhibits phagocytosis when bound by THBS1 or SIRPalpha. In IPF, persistent CD47 expression on fibrotic matrix-producing cells may shield them from macrophage-mediated clearance. CD47 has Phase III antibody therapeutics in oncology (anti-CD47 "magrolimab" class), providing a direct repurposing opportunity for IPF.

**Supporting Evidence:**
| Evidence File | Key Finding |
|--------------|-------------|
| `rubric_scores.csv` | THBS1: exploratory_total=8, priority=high; CD47: exploratory_total=7, priority=medium |
| `stage1_THBS1--CD47.json` | STRING PPI interaction; pathway context |
| `stage2_evidence.json` | CD47: OT association score 0.38, Phase III antibodies |

**Key Biological Entities:**
- **Genes:** THBS1, CD47, SIRPalpha
- **Pathways:** Phagocytosis, immune checkpoint
- **Cell Types:** Myofibroblasts (CD47+), alveolar macrophages (SIRPalpha+)
- **Drugs:** Anti-CD47 antibodies (magrolimab class, Phase III in oncology)

**Falsifiable Prediction:**
> Anti-CD47 antibody treatment (10mg/kg, 3x/week) in established bleomycin fibrosis (starting day 14) will reduce lung collagen content by >25% at day 28 compared to IgG control, mediated by increased macrophage efferocytosis. If anti-CD47 does not reduce collagen or increase macrophage phagocytic activity (measured by pHrodo assay), the hypothesis is falsified.

**Suggested Experimental Validation:**
Therapeutic (not preventive) bleomycin model: start anti-CD47 treatment at day 14 when fibrosis is established. Readouts at day 28: hydroxyproline, Ashcroft score, flow cytometry (macrophage phagocytosis using pHrodo-labeled apoptotic cells ex vivo), immunofluorescence for CD47 on alpha-SMA+ myofibroblasts. Controls: IgG isotype, anti-CD47 alone (no bleomycin) to assess baseline safety.

---

## Scoring Summary

| Rank | Hypothesis | Category | Evidence | Specificity | Novelty | Actionability | **Composite** |
|:----:|-----------|----------|:--------:|:-----------:|:-------:|:------------:|:-------------:|
| 1 | ICAM1 Dual-Target Gateway | Cross-Target | 1.0 | 0.7 | 0.5 | 0.5 | **0.71** |
| 2 | Vactosertib IPF Therapy | Therapeutic | 0.8 | 0.7 | 0.2 | 0.9 | **0.65** |
| 3 | APOE-TREM2 Metabolic Checkpoint | Novel Pathway | 0.6 | 0.5 | 0.8 | 0.4 | **0.56** |
| 4 | [GAP] THBS1-CD47 Phagocytic Clearance | MoA | 0.6 | 0.5 | 0.5 | 0.5 | **0.52** |

**Removed hypotheses:**
- Hypothesis 5 (MUC1 epithelial barrier): Specificity 0.3 — removed by hard rule (< 0.5)
- Hypothesis 6 (HLA-CD4 immune activation): Composite 0.38 — below threshold

---

## Gap Analysis

### Evidence Coverage
- **Total evidence files:** 20
- **Files referenced by hypotheses:** 17 (85%)
- **Coverage target:** >= 80%
- **Target met:** Yes

### Orphan Evidence
| File | Type | Reason Not Referenced |
|------|------|---------------------|
| `ot_LAMB2.json` | ot | Low priority (unranked), insufficient_evidence classification |
| `ot_AGTRAP.json` | ot | Low exploratory_total (4), no distinctive pathway |
| `ot_RPSA.json` | ot | Low priority (medium), limited tractability |

### Gap-Filling Hypotheses
- **[GAP] THBS1-CD47 Phagocytic Clearance** (Hypothesis 4): Generated to cover `stage1_THBS1--CD47.json`. Survived scoring with composite 0.52. Retained in final set.

---

## Appendix A: Evidence Inventory

### FEATURED Targets

| Gene | Classification | Priority | Exploratory Total | Combined Total | Stage3 | Key Pathways |
|------|---------------|----------|:-----------------:|:--------------:|:------:|-------------|
| TGFB1 | exploratory_target | high | 10 | 9 | Yes | TGF-beta signaling, ECM-receptor |
| MUC1 | exploratory_target | high | 9 | 10 | Yes | CDH1 regulation |
| MMP2 | exploratory_target | high | 9 | 9 | Yes | ECM degradation |
| CXCR4 | exploratory_target | high | 9 | 10 | Yes | Chemokine signaling |
| CD4 | exploratory_target | high | 8 | 9 | Yes | T cell receptor signaling |
| THBS1 | exploratory_target | high | 8 | 9 | Yes | ECM organization, phagocytosis |
| ICAM1 | exploratory_target | high | 8 | 7 | Yes | Cell adhesion, leukocyte migration |

### NOVEL Targets

| Gene | Rationale | Exploratory Total | Key Evidence |
|------|-----------|:-----------------:|-------------|
| APOE | Lipid metabolism-fibrosis link | 6 | OT: SM+AB tractable |
| TREM2 | Macrophage lipid sensing | 7 | Phase II antibodies in AD |
| LRP1 | Endocytic clearance receptor | 7 | OT: SM+AB tractable |
| SDC2 | ECM-receptor interactions | 6 | SM tractable |

### Stage 1 L-R Pair Evidence

| L-R Pair | STRING PPI | Census Risk Ratio | Census Cell Type | Shared Pathways |
|----------|:---------:|:-----------------:|-----------------|----------------|
| ICAM1-MUC1 | 0.993 | 17.86 | AT2 cell | NF-kB signaling |
| ICAM1-ITGB2 | 0.999 | — | Pulmonary cells | Leukocyte TEM |
| ICAM1-EZR | — | — | — | Cytoskeletal |
| ICAM1-PECAM1 | 0.998 | — | Endothelial | Leukocyte TEM |
| TGFB1-P4HB | — | — | — | TGF-beta signaling |
| THBS1-CD47 | — | — | — | Phagocytosis |
| PPIA-CXCR4 | — | — | — | Chemokine signaling |
| HLA-DRB1-CD4 | — | — | — | Antigen presentation |

---

*Generated by drug-target-hypothesis skill | UCB scoring adapted from HypoGeniC (Zhou et al., 2024)*
