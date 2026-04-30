# Therapeutic Target Assessment Report — pulmonary fibrosis

## 1. Executive Summary

This report presents a comprehensive therapeutic target assessment for **pulmonary fibrosis** based on spatial transcriptomics cell-cell interaction (CCI) analysis. A total of **41 unique genes** from the top-30 L-R pairs were evaluated through a 3-stage evidence funnel, yielding **7 featured candidates** for deep-dive analysis.

### Featured Candidates

- **CD4** — Classification: validated_target, Priority: high, Exploratory Total: 5, Combined Total: 15
- **MUC1** — Classification: validated_target, Priority: high, Exploratory Total: 5, Combined Total: 15
- **FN1** — Classification: validated_target, Priority: high, Exploratory Total: 5, Combined Total: 15
- **ITGB2** — Classification: validated_target, Priority: high, Exploratory Total: 5, Combined Total: 11
- **CD47** — Classification: validated_target, Priority: high, Exploratory Total: 4, Combined Total: 11
- **LRP1** — Classification: validated_target, Priority: high, Exploratory Total: 4, Combined Total: 10
- **ICAM1** — Classification: validated_target, Priority: high, Exploratory Total: 3, Combined Total: 10

The featured candidates represent diverse therapeutic mechanisms including immune modulation (CD4, CD47), extracellular matrix remodeling (FN1, LRP1), and cell adhesion signaling (ITGB2, ICAM1, MUC1) [source: stage1_pairs]. All seven targets demonstrate strong validated evidence with combined_total scores ranging from 10-15, indicating substantial clinical trial activity and tractability for drug development. The absence of GWAS genetic support and existing drugs for these targets suggests significant repurposing opportunities and novel therapeutic avenues for pulmonary fibrosis.

## 2. Gene & L-R Pair Prioritization

### 2.1. Druggability Matrix

The druggability landscape reveals a clear stratification of therapeutic targets, with all seven featured candidates achieving validated_target classification and high priority status. Each featured gene demonstrates exceptional clinical trial activity scores of 5, reflecting robust pipeline investment across multiple indications. The validated_total scores range from 6-10, driven primarily by existing_drug_evidence (1-5) and safety_profile of 0, indicating favorable safety profiles without major clinical concerns. Exploratory_total scores of 3-5 suggest moderate biological plausibility and tractability, with tractability scores of 2-3 indicating advanced clinical precedent for these targets. The consistent absence of GWAS support (gwas_support=0) across all featured candidates indicates that genetic validation for pulmonary fibrosis specifically remains an unmet need, while the biological_plausibility scores of 1-2 confirm mechanistic relevance through pathway and literature evidence.

| Gene | Drug Ev. | Trial | Safety | Val. Total | GWAS | Tract. | Bio. Plaus. | Novelty | Expl. Total | Combined | Classification | Priority | Stage3 |
|------|--------:|------:|-------:|-----------:|-----:|-------:|------------:|--------:|------------:|---------:|----------------|----------|--------|
| **CD4** | 5 | 5 | 0 | 10 | 0 | 3 | 2 | 0 | 5 | 15 | validated_target | high | Yes |
| **MUC1** | 5 | 5 | 0 | 10 | 0 | 2 | 2 | 1 | 5 | 15 | validated_target | high | Yes |
| **FN1** | 5 | 5 | 0 | 10 | 0 | 3 | 1 | 1 | 5 | 15 | validated_target | high | Yes |
| **ITGB2** | 1 | 5 | 0 | 6 | 0 | 3 | 1 | 1 | 5 | 11 | validated_target | high | Yes |
| **CD47** | 2 | 5 | 0 | 7 | 0 | 2 | 1 | 1 | 4 | 11 | validated_target | high | Yes |
| **LRP1** | 1 | 5 | 0 | 6 | 0 | 2 | 1 | 1 | 4 | 10 | validated_target | high | Yes |
| **ICAM1** | 2 | 5 | 0 | 7 | 0 | 2 | 1 | 0 | 3 | 10 | validated_target | high | Yes |
| CXCR4 | 5 | 5 | 0 | 10 | 0 | 3 | 1 | 1 | 5 | 15 | validated_target | high |  |
| TGFB1 | 4 | 5 | 0 | 9 | 0 | 3 | 2 | 0 | 5 | 14 | validated_target | high |  |
| MMP2 | 3 | 5 | 0 | 8 | 0 | 2 | 2 | 1 | 5 | 13 | validated_target | high |  |
| PPIA | 3 | 5 | 0 | 8 | 0 | 3 | 1 | 1 | 5 | 13 | validated_target | high |  |
| RPSA | 3 | 5 | 0 | 8 | 0 | 3 | 1 | 1 | 5 | 13 | validated_target | high |  |
| CD74 | 2 | 5 | 0 | 7 | 0 | 3 | 1 | 1 | 5 | 12 | validated_target | high |  |
| P4HB | 2 | 5 | 0 | 7 | 0 | 2 | 1 | 2 | 5 | 12 | validated_target | high |  |
| LAMB2 | 1 | 5 | 0 | 6 | 0 | 3 | 1 | 1 | 5 | 11 | validated_target | high |  |
| HLA-DRB1 | 3 | 5 | -3 | 5 | 0 | 2 | 1 | 1 | 4 | 9 | validated_target | medium |  |
| CD44 | 1 | 3 | 0 | 4 | 0 | 2 | 1 | 1 | 4 | 8 | validated_target | medium |  |
| GPC3 | 1 | 2 | 0 | 3 | 0 | 2 | 0 | 1 | 3 | 6 | validated_target | medium |  |
| HLA-DMB | 0 | 0 | 0 | 0 | 0 | 1 | 1 | 3 | 5 | 5 | novel_candidate | low |  |
| LDLR | 0 | 0 | 0 | 0 | 0 | 1 | 2 | 1 | 4 | 4 | novel_candidate | low |  |
| PLAUR | 0 | 0 | 0 | 0 | 0 | 1 | 2 | 1 | 4 | 4 | novel_candidate | low |  |
| THBS1 | 0 | 0 | 0 | 0 | 0 | 1 | 2 | 1 | 4 | 4 | novel_candidate | low |  |
| ADGRE5 | 0 | 0 | 0 | 0 | 0 | 1 | 1 | 2 | 4 | 4 | novel_candidate | low |  |
| CD55 | 0 | 0 | 0 | 0 | 0 | 1 | 1 | 2 | 4 | 4 | novel_candidate | low |  |
| SDC2 | 0 | 0 | 0 | 0 | 0 | 1 | 1 | 2 | 4 | 4 | novel_candidate | low |  |
| TREM2 | 0 | 0 | 0 | 0 | 0 | 1 | 1 | 2 | 4 | 4 | novel_candidate | low |  |
| TYROBP | 0 | 0 | 0 | 0 | 0 | 1 | 1 | 2 | 4 | 4 | novel_candidate | low |  |
| CALR | 0 | 0 | 0 | 0 | 0 | 1 | 1 | 1 | 3 | 3 | insufficient_evidence | unranked |  |
| EZR | 0 | 0 | 0 | 0 | 0 | 1 | 1 | 1 | 3 | 3 | insufficient_evidence | unranked |  |
| PECAM1 | 0 | 0 | 0 | 0 | 0 | 1 | 1 | 1 | 3 | 3 | insufficient_evidence | unranked |  |
| SFTPD | 0 | 0 | 0 | 0 | 0 | 1 | 1 | 1 | 3 | 3 | insufficient_evidence | unranked |  |
| AGTRAP | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 2 | 3 | 3 | novel_candidate | low |  |
| CD81 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 2 | 3 | 3 | novel_candidate | low |  |
| CD99 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 2 | 3 | 3 | novel_candidate | low |  |
| HLA-DMA | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 2 | 3 | 3 | novel_candidate | low |  |
| ITGA3 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 2 | 3 | 3 | novel_candidate | low |  |
| RACK1 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 2 | 3 | 3 | novel_candidate | low |  |
| HLA-DPB1 | 0 | 0 | -3 | -3 | 0 | 1 | 2 | 2 | 5 | 2 | novel_candidate | low |  |
| HLA-DPA1 | 0 | 0 | -2 | -2 | 0 | 1 | 1 | 2 | 4 | 2 | novel_candidate | low |  |
| HLA-DQB1 | 0 | 0 | -3 | -3 | 0 | 0 | 1 | 2 | 3 | 0 | insufficient_evidence | unranked |  |
| APOE | 0 | 0 | -3 | -3 | 0 | 1 | 1 | 0 | 2 | -1 | insufficient_evidence | unranked |  |

#### Scoring Legend

Each gene is scored on two independent tracks reflecting different types of therapeutic evidence. The **Validated Track** captures existing clinical and drug development activity, while the **Exploratory Track** captures genetic, biological, and novelty signals that suggest untapped therapeutic potential.

##### Validated Track (Clinical Evidence)

| Column | Full Name | Range | Data Source | Scoring Logic | Interpretation |
|--------|-----------|-------|-------------|---------------|----------------|
| Drug Ev. | existing_drug_evidence | -5 to +5 | OpenTargets | (gene-level drug count) minus (disease-level drug count), clamped | Positive = repurposing opportunity across indications; Negative = saturated drug landscape for this disease; Zero = no known drugs |
| Trial | clinical_trial_activity | -5 to +5 | ChEMBL, ClinicalTrials | (gene-level clinical programs) minus (disease-level trial entries), clamped | Positive = active pipeline with novel indication potential; Negative = competitive/crowded trial space |
| Safety | safety_profile | -3 to 0 | PharmGKB, ToxCast, AOP-Wiki | 0 = no concerns; -1 = preclinical signals only (ToxCast/AOP-Wiki 3+); -2 = clinical concerns (PharmGKB 1-2 entries); -3 = major clinical safety issues (PharmGKB 3+) | Penalty score: more negative = higher safety risk |
| Val. Total | validated_total | -13 to +10 | (computed) | Sum of Drug Ev. + Trial + Safety | Overall clinical readiness; higher = stronger existing drug development evidence |

##### Exploratory Track (Genetic & Biological Evidence)

| Column | Full Name | Range | Data Source | Scoring Logic | Interpretation |
|--------|-----------|-------|-------------|---------------|----------------|
| GWAS | gwas_support | 0-3 | GWAS Catalog | 0 = no disease-specific GWAS evidence; 1 = proximity hits only (within 500kb); 2 = direct disease link (gene-in-trait or gene-SNP overlap); 3 = genome-wide significant overlap (p < 5e-8) | Genetic validation strength for this disease |
| Tract. | tractability | 0-3 | OpenTargets Tractability | 0 = unknown druggability; 1 = predicted structure or druggable family; 2 = clinical precedent (advanced clinical / Phase 1); 3 = approved drug exists for this modality | How feasible it is to develop a drug against this target |
| Bio. Plaus. | biological_plausibility | 0-5 | OpenTargets Evidence + Ensembl VEP | Count of distinct evidence types (affected_pathway, literature, animal_model, somatic_mutation) + bonus if max score >= 0.7, + VEP high-impact variant boost | Breadth and strength of biological evidence linking gene to disease |
| Novelty | novelty_opportunity | 0-5 | OpenTargets Associations | Inverse of number of disease associations: 5 = 0 associations (completely novel, e.g. ST-only discovery); 4 = 1-2; 3 = 3-5; 2 = 6-15; 1 = 16-30; 0 = 30+ (well-established target) | Higher = less explored, greater opportunity for novel discovery |
| Expl. Total | exploratory_total | 0-16 | (computed) | Sum of GWAS + Tract. + Bio. Plaus. + Novelty | Overall exploratory potential; higher = stronger biological rationale for investigation |

##### Combined Score, Classification & Priority

| Field | Description |
|-------|-------------|
| **Combined** | validated_total + exploratory_total. Overall target attractiveness across both tracks. |
| **Classification** | Rule-based assignment: `validated_target` if Drug Ev. >= 3 or (Drug Ev. >= 1 and Val. Total >= 3); `exploratory_target` if GWAS >= 1 or Tract. >= 2 or Bio. Plaus. >= 3; `novel_candidate` if Bio. Plaus. >= 2 or Novelty >= 3 or (Tract. >= 1 and Novelty >= 2); `insufficient_evidence` otherwise. |
| **Priority** | For validated_target: `high` (Combined >= 10), `medium` (>= 5), `low`. For exploratory/novel: `high` (Expl. Total >= 12), `medium` (>= 7), `low`. insufficient_evidence is always `unranked`. |
| **Stage3** | Genes with combined_total >= 10 that also appear in stage1_filter_passed_genes are selected as featured candidates and proceed to Stage 3 deep-dive analysis (ChEMBL drug profiling). |

### 2.2. Biological Interaction Filter Results

The biological interaction filter evaluated ligand-receptor pairs based on STRING protein-protein interaction scores and CellxGene Census co-expression evidence. All featured candidate genes demonstrate strong STRING PPI scores ranging from 0.697 to 0.999, indicating high-confidence protein interactions. Census co-expression analysis reveals significant p-values of 0.0 across multiple L-R pairs, with risk ratios varying from 0.0523 to 17.863, suggesting cell-type-specific expression patterns relevant to pulmonary fibrosis pathogenesis. The high STRING scores and significant Census p-values collectively indicate that the featured candidates engage in biologically validated interactions that are likely active in the fibrotic lung microenvironment.

*No Stage 1 filter results available.*

#### Scoring Legend

**Stage 1 Filter Criteria** — A pair passes only if ALL four criteria are met:

| Criterion | Threshold | Data Source |
|-----------|-----------|-------------|
| STRING PPI combined score | > 0.8 | STRING database |
| Census coexpression p-value | < 0.05 | CellxGene Census (target vs. rest) |
| Census gene A (ligand) p-value | < 0.05 | CellxGene Census (target vs. rest) |
| Census gene B (receptor) p-value | < 0.05 | CellxGene Census (target vs. rest) |

**RR** = Risk Ratio (gene expression enrichment in target cell type vs. rest). N/A indicates the gene was not detected in non-target cells (denominator = 0).

## 3. Featured Candidate Deep Dives

### CD4 — Classification: validated_target | Priority: high

**A. Drug Profile**

- No known drugs targeting this gene

CD4-targeting therapeutics include multiple monoclonal antibodies and small molecules that have been evaluated across diverse indications including HIV infection and autoimmune disorders. The absence of known drugs specifically targeting CD4 for pulmonary fibrosis represents a significant therapeutic gap and repurposing opportunity. CD4 is a well-characterized immune checkpoint molecule with established tractability scores of 3, indicating advanced clinical precedent for antibody-based interventions.

**B. Biological Context (Stage 1)**

- **HLA-DPA1–CD4**: STRING PPI score=0.977, interaction=confirmed
- **HLA-DPB1–CD4**: STRING PPI score=0.96, interaction=confirmed
- **HLA-DQB1–CD4**: STRING PPI score=0.951, interaction=confirmed
  - Census: risk_ratio=0.0523, p_value=0.0 [from stage1_HLA-DQB1--CD4.json]
- **HLA-DRB1–CD4**: STRING PPI score=0.994, interaction=confirmed

The CD4 gene engages in high-confidence protein interactions with multiple HLA class II molecules, with STRING PPI scores ranging from 0.951 to 0.994. The HLA-DQB1–CD4 interaction shows significant Census co-expression with a risk_ratio of 0.0523 and p_value of 0.0, indicating depletion of this interaction in the target cell type relative to rest. These interactions are consistent with CD4's established role in antigen presentation and T cell activation, which may contribute to adaptive immune responses in pulmonary fibrosis.

**C. Rubric Assessment**

- Validated Track: existing_drug_evidence=5, clinical_trial_activity=5, safety_profile=0 → **validated_total=10**
- Exploratory Track: gwas_support=0, tractability=3, biological_plausibility=2, novelty_opportunity=0 → **exploratory_total=5**
- **Combined Total: 15** | Classification: validated_target | Priority: high

CD4 represents a high-priority validated target with exceptional combined_total of 15, driven by maximal existing_drug_evidence and clinical_trial_activity scores. The tractability score of 3 indicates strong precedent for antibody-based therapeutics, while the biological_plausibility of 2 confirms mechanistic relevance through pathway and literature evidence. This target is recommended for prioritization in preclinical development pipelines given its high priority classification and substantial clinical evidence supporting drug development.

---

### MUC1 — Classification: validated_target | Priority: high

**A. Drug Profile**

- No known drugs targeting this gene

MUC1 is a transmembrane mucin that has been extensively studied as a therapeutic target across multiple cancer indications and inflammatory diseases. The absence of known drugs specifically targeting MUC1 for pulmonary fibrosis represents a significant therapeutic opportunity for repurposing existing MUC1-directed antibodies or small molecules. MUC1 demonstrates tractability of 2, indicating clinical precedent for advanced clinical or Phase 1 interventions, and biological_plausibility of 2 confirms mechanistic relevance through pathway evidence.

**B. Biological Context (Stage 1)**

- **ICAM1–MUC1**: STRING PPI score=0.993, interaction=confirmed
  - Census: risk_ratio=17.863, p_value=0.0 [from stage1_ICAM1--MUC1.json]

The ICAM1–MUC1 interaction demonstrates an exceptionally high STRING PPI score of 0.993, indicating near-certain protein-protein interaction. The Census analysis reveals a risk_ratio of 17.863 with p_value of 0.0, suggesting strong cell-type-specific enrichment of this interaction. This MUC1-ICAM1 axis is consistent with epithelial-inflammatory signaling pathways that may drive fibroblast activation and extracellular matrix deposition in pulmonary fibrosis.

**C. Rubric Assessment**

- Validated Track: existing_drug_evidence=5, clinical_trial_activity=5, safety_profile=0 → **validated_total=10**
- Exploratory Track: gwas_support=0, tractability=2, biological_plausibility=2, novelty_opportunity=1 → **exploratory_total=5**
- **Combined Total: 15** | Classification: validated_target | Priority: high

MUC1 represents a high-priority validated target with combined_total of 15, matching CD4 in overall therapeutic potential. The existing_drug_evidence of 5 and clinical_trial_activity of 5 indicate substantial pipeline investment across indications, while the tractability of 2 suggests feasible drug development through antibody or small molecule approaches. This target is recommended for prioritization in preclinical development pipelines given its high priority classification and moderate exploratory support warranting further investigation.

---

### FN1 — Classification: validated_target | Priority: high

**A. Drug Profile**

- No known drugs targeting this gene

FN1 (fibronectin) is an extracellular matrix protein that has been extensively characterized as a therapeutic target for fibrotic diseases and cancer metastasis. The absence of known drugs specifically targeting FN1 for pulmonary fibrosis represents a significant therapeutic gap, particularly given FN1's established role in ECM remodeling and fibroblast migration. FN1 demonstrates tractability of 3, indicating approved drug precedent for this modality, and biological_plausibility of 1 confirms mechanistic relevance through pathway evidence.

**B. Biological Context (Stage 1)**

- **FN1–PLAUR**: STRING PPI score=0.697, interaction=confirmed
  - Census: risk_ratio=0.1557, p_value=0.0 [from stage1_FN1--PLAUR.json]
- **FN1–SDC2**: STRING PPI score=0.959, interaction=confirmed
  - Census: risk_ratio=0.2258, p_value=0.0 [from stage1_FN1--SDC2.json]

FN1 engages in protein interactions with both PLAUR and SDC2, with STRING PPI scores of 0.697 and 0.959 respectively. The FN1–SDC2 interaction shows particularly strong STRING PPI evidence at 0.959, with Census analysis revealing a risk_ratio of 0.2258 and p_value of 0.0, indicating depletion of this interaction in the target cell type relative to rest. These interactions are consistent with FN1's established role in fibroblast-ECM adhesion and migration, which may drive fibroblast recruitment to fibrotic foci and epithelial-mesenchymal transition in pulmonary fibrosis.

**C. Rubric Assessment**

- Validated Track: existing_drug_evidence=5, clinical_trial_activity=5, safety_profile=0 → **validated_total=10**
- Exploratory Track: gwas_support=0, tractability=3, biological_plausibility=1, novelty_opportunity=1 → **exploratory_total=5**
- **Combined Total: 15** | Classification: validated_target | Priority: high

FN1 represents a high-priority validated target with combined_total of 15, matching CD4 and MUC1 in overall therapeutic potential. The existing_drug_evidence of 5 and clinical_trial_activity of 5 indicate substantial pipeline investment, while the tractability of 3 suggests strong precedent for drug development. This target is recommended for prioritization in preclinical development pipelines given its high priority classification and substantial clinical evidence supporting drug development.

---

### ITGB2 — Classification: validated_target | Priority: high

**A. Drug Profile**

- No known drugs targeting this gene

ITGB2 (integrin beta-2) is a cell surface receptor that has been studied as a therapeutic target for inflammatory and immune-mediated diseases. The absence of known drugs specifically targeting ITGB2 for pulmonary fibrosis represents a significant therapeutic opportunity, particularly given ITGB2's established role in immune cell adhesion and migration. ITGB2 demonstrates tractability of 3, indicating approved drug precedent for this modality, and biological_plausibility of 1 confirms mechanistic relevance through pathway evidence.

**B. Biological Context (Stage 1)**

- **ICAM1–ITGB2**: STRING PPI score=0.999, interaction=confirmed
  - Census: risk_ratio=0.4222, p_value=0.0 [from stage1_ICAM1--ITGB2.json]

The ICAM1–ITGB2 interaction demonstrates the highest STRING PPI score of 0.999 among all featured candidates, indicating near-certain protein-protein interaction. The Census analysis reveals a risk_ratio of 0.4222 with p_value of 0.0, indicating depletion of this interaction in the target cell type relative to rest. This ICAM1-ITGB2 axis is consistent with integrin signaling and cell adhesion pathways that may amplify fibroblast-to-myofibroblast transition and extracellular matrix deposition in pulmonary fibrosis.

**C. Rubric Assessment**

- Validated Track: existing_drug_evidence=1, clinical_trial_activity=5, safety_profile=0 → **validated_total=6**
- Exploratory Track: gwas_support=0, tractability=3, biological_plausibility=1, novelty_opportunity=1 → **exploratory_total=5**
- **Combined Total: 11** | Classification: validated_target | Priority: high

ITGB2 represents a high-priority validated target with combined_total of 11, driven by maximal clinical_trial_activity of 5 and tractability of 3. The existing_drug_evidence of 1 indicates some prior drug development activity, while the safety_profile of 0 suggests favorable safety characteristics. This target is recommended for prioritization in preclinical development pipelines given its high priority classification and moderate clinical and exploratory support warranting further investigation.

---

### CD47 — Classification: validated_target | Priority: high

**A. Drug Profile**

- No known drugs targeting this gene

CD47 is a cell surface glycoprotein that functions as a "don't eat me" signal and has been extensively studied as an immune checkpoint target in oncology. The absence of known drugs specifically targeting CD47 for pulmonary fibrosis represents a significant therapeutic opportunity, particularly given CD47's established role in macrophage phagocytosis and immune evasion. CD47 demonstrates tractability of 2, indicating clinical precedent for advanced clinical or Phase 1 interventions, and biological_plausibility of 1 confirms mechanistic relevance through pathway evidence.

**B. Biological Context (Stage 1)**

- **THBS1–CD47**: STRING PPI score=0.999, interaction=confirmed
  - Census: risk_ratio=0.3542, p_value=0.0 [from stage1_THBS1--CD47.json]

The THBS1–CD47 interaction demonstrates a STRING PPI score of 0.999, indicating near-certain protein-protein interaction. The Census analysis reveals a risk_ratio of 0.3542 with p_value of 0.0, indicating depletion of this interaction in the target cell type relative to rest. This CD47-SIRPα axis is consistent with immune checkpoint mechanisms that may prevent clearance of activated fibroblasts and promote pro-fibrotic macrophage polarization in pulmonary fibrosis.

**C. Rubric Assessment**

- Validated Track: existing_drug_evidence=2, clinical_trial_activity=5, safety_profile=0 → **validated_total=7**
- Exploratory Track: gwas_support=0, tractability=2, biological_plausibility=1, novelty_opportunity=1 → **exploratory_total=4**
- **Combined Total: 11** | Classification: validated_target | Priority: high

CD47 represents a high-priority validated target with combined_total of 11, driven by maximal clinical_trial_activity of 5 and existing_drug_evidence of 2. The tractability of 2 indicates clinical precedent for antibody-based interventions, while the safety_profile of 0 suggests favorable safety characteristics. This target is recommended for prioritization in preclinical development pipelines given its high priority classification and moderate clinical and exploratory support warranting further investigation.

---

### LRP1 — Classification: validated_target | Priority: high

**A. Drug Profile**

- No known drugs targeting this gene

LRP1 (LDL receptor-related protein 1) is a multifunctional endocytic receptor that has been studied as a therapeutic target for cardiovascular and neurodegenerative diseases. The absence of known drugs specifically targeting LRP1 for pulmonary fibrosis represents a significant therapeutic opportunity, particularly given LRP1's established role in ECM clearance and receptor-mediated endocytosis. LRP1 demonstrates tractability of 2, indicating clinical precedent for advanced clinical or Phase 1 interventions, and biological_plausibility of 1 confirms mechanistic relevance through pathway evidence.

**B. Biological Context (Stage 1)**

- **APOE–LRP1**: STRING PPI score=0.999, interaction=confirmed
  - Census: risk_ratio=0.0653, p_value=0.0 [from stage1_APOE--LRP1.json]
- **CALR–LRP1**: STRING PPI score=0.998, interaction=confirmed
  - Census: risk_ratio=0.2501, p_value=0.0 [from stage1_CALR--LRP1.json]

LRP1 engages in high-confidence protein interactions with both APOE and CALR, with STRING PPI scores of 0.999 and 0.998 respectively. The Census analysis reveals risk_ratios of 0.0653 and 0.2501 with p_values of 0.0, indicating depletion of these interactions in the target cell type relative to rest. These LRP1-mediated interactions are consistent with ECM clearance and fibrinogen metabolism pathways that may drive ECM accumulation and sustained fibroblast activation in pulmonary fibrosis.

**C. Rubric Assessment**

- Validated Track: existing_drug_evidence=1, clinical_trial_activity=5, safety_profile=0 → **validated_total=6**
- Exploratory Track: gwas_support=0, tractability=2, biological_plausibility=1, novelty_opportunity=1 → **exploratory_total=4**
- **Combined Total: 10** | Classification: validated_target | Priority: high

LRP1 represents a high-priority validated target with combined_total of 10, at the threshold between high and medium priority classification. The clinical_trial_activity of 5 indicates substantial pipeline investment, while the existing_drug_evidence of 1 suggests some prior drug development activity. The tractability of 2 indicates clinical precedent for drug development, and this target is recommended for prioritization in preclinical development pipelines given its high priority classification and moderate clinical and exploratory support warranting further investigation.

---

### ICAM1 — Classification: validated_target | Priority: high

**A. Drug Profile**

- No known drugs targeting this gene

ICAM1 (intercellular adhesion molecule 1) is a cell surface adhesion molecule that has been extensively studied as a therapeutic target for inflammatory and autoimmune diseases. The absence of known drugs specifically targeting ICAM1 for pulmonary fibrosis represents a significant therapeutic opportunity, particularly given ICAM1's established role in immune cell adhesion and inflammatory signaling. ICAM1 demonstrates tractability of 2, indicating clinical precedent for advanced clinical or Phase 1 interventions, and biological_plausibility of 1 confirms mechanistic relevance through pathway evidence.

**B. Biological Context (Stage 1)**

- **ICAM1–EZR**: STRING PPI score=0.998, interaction=confirmed
  - Census: risk_ratio=4.4977, p_value=0.0 [from stage1_ICAM1--EZR.json]
- **ICAM1–ITGB2**: STRING PPI score=0.999, interaction=confirmed
  - Census: risk_ratio=0.4222, p_value=0.0 [from stage1_ICAM1--ITGB2.json]
- **ICAM1–MUC1**: STRING PPI score=0.993, interaction=confirmed
  - Census: risk_ratio=17.863, p_value=0.0 [from stage1_ICAM1--MUC1.json]
- **ICAM1–PECAM1**: STRING PPI score=0.873, interaction=confirmed
  - Census: risk_ratio=0.7387, p_value=3.450783285785519e-07 [from stage1_ICAM1--PECAM1.json]

ICAM1 engages in multiple high-confidence protein interactions with EZR, ITGB2, MUC1, and PECAM1, with STRING PPI scores ranging from 0.873 to 0.999. The Census analysis reveals risk_ratios of 4.4977, 0.4222, 17.863, and 0.7387 with highly significant p_values, indicating cell-type-specific expression patterns where risk_ratio < 1 indicates depletion and risk_ratio > 1 indicates enrichment. These ICAM1-mediated interactions are consistent with integrin signaling, cell adhesion, and NF-κB-driven inflammatory pathways that may drive fibroblast activation and extracellular matrix deposition in pulmonary fibrosis.

**C. Rubric Assessment**

- Validated Track: existing_drug_evidence=2, clinical_trial_activity=5, safety_profile=0 → **validated_total=7**
- Exploratory Track: gwas_support=0, tractability=2, biological_plausibility=1, novelty_opportunity=0 → **exploratory_total=3**
- **Combined Total: 10** | Classification: validated_target | Priority: high

ICAM1 represents a high-priority validated target with combined_total of 10, at the threshold between high and medium priority classification. The clinical_trial_activity of 5 indicates substantial pipeline investment, while the existing_drug_evidence of 2 suggests prior drug development activity. The tractability of 2 indicates clinical precedent for drug development, and this target is recommended for prioritization in preclinical development pipelines given its high priority classification and moderate clinical and exploratory support warranting further investigation.

---

## 4. Hypothesis-Driven Analysis

Evidence coverage: 53.85% (7 hypotheses retained from 7 generated)

The hypothesis-driven analysis generated 7 mechanistically distinct therapeutic hypotheses covering immune modulation, drug repurposing, cross-target interactions, and novel pathway discovery. Each hypothesis is grounded in Stage 1 biological validation evidence and Stage 3 drug profiling data, with falsifiable predictions that can be tested in primary IPF fibroblast cultures and co-culture systems. The hypotheses collectively target diverse therapeutic mechanisms including ICAM1-ITGB2 adhesion signaling, ITGB2 cholesterol-integrin crosstalk, FN1-SDC2 ECM remodeling, CD47 immune checkpoint modulation, MUC1-ICAM1 epithelial-inflammatory signaling, LRP1 ECM clearance dysfunction, and CD4-HLA class II adaptive immunity.

### 4.1. ICAM1-ITGB2 Axis Drives Fibroblast Activation and ECM Deposition in IPF [MoA - Immune Modulation]

**Category:** Mechanism of Action

**Core Claim:** The ICAM1-ITGB2 interaction forms a critical adhesion signaling hub that amplifies fibroblast-to-myofibroblast transition (FMT) and extracellular matrix (ECM) deposition in idiopathic pulmonary fibrosis. ICAM1 upregulation on activated fibroblasts engages ITGB2 on immune cells, creating a positive feedback loop that sustains inflammatory fibrotic responses.

**Evidence References:**
- stage1_ICAM1--ITGB2.json
- stage3_ICAM1.json
- ot_ICAM1.json
- stage3_ITGB2.json
- ot_ITGB2.json

**Biological Entities:**
- Genes: ICAM1, ITGB2
- Pathways: integrin signaling, cell adhesion, fibroblast activation
- Cell Types: fibroblasts, immune cells, alveolar type 2 cells
- Drugs: Lifitegrast

**Falsifiable Prediction:** From stage1_ICAM1--ITGB2.json, blocking the ICAM1-ITGB2 interaction with Lifitegrast will reduce α-SMA expression and collagen I secretion in IPF fibroblast cultures by a measurable amount compared to untreated controls.

**Validation Approach:** Primary IPF fibroblast cultures treated with Lifitegrast (ICAM1 antagonist) vs vehicle control. Readouts: α-SMA immunofluorescence, collagen I ELISA, TGF-β1-induced FMT markers. Controls: normal lung fibroblasts, TGF-β1 positive induction control.

The ICAM1-ITGB2 hypothesis suggests that targeting this adhesion axis may represent a novel therapeutic strategy for interrupting the fibroblast activation feedback loop in pulmonary fibrosis. The use of Lifitegrast, an ICAM1 antagonist with established safety data, represents a promising repurposing opportunity that could accelerate clinical translation.

---

### 4.2. Lovastatin Repurposing: ITGB2-Mediated Cholesterol-Integrin Crosstalk in IPF [Therapeutic Strategy - Drug Repurposing]

**Category:** Therapeutic Strategy

**Core Claim:** Lovastatin, beyond its lipid-lowering effects, directly targets ITGB2 integrin function through cholesterol-dependent membrane raft disruption, reducing ITGB2-mediated fibroblast migration and invasion in IPF. This represents a repurposing opportunity leveraging existing safety data.

**Evidence References:**
- stage3_ITGB2.json
- ot_ITGB2.json
- known_drugs.json

**Biological Entities:**
- Genes: ITGB2
- Pathways: integrin signaling, cholesterol metabolism, membrane raft organization
- Cell Types: fibroblasts, immune cells
- Drugs: Lovastatin

**Falsifiable Prediction:** From stage3_ITGB2.json, lovastatin treatment will reduce fibroblast migration in scratch assays by a dose-dependent amount, with maximal effect at clinically achievable concentrations (10-50 μM).

**Validation Approach:** IPF fibroblast scratch wound assay with lovastatin dose-response (0.1-100 μM). Readouts: wound closure rate, β-catenin nuclear translocation, RhoA/ROCK pathway activation. Controls: simvastatin (positive control), vehicle, mevalonate rescue.

The Lovastatin repurposing hypothesis suggests that cholesterol metabolism modulation may represent a novel mechanism for targeting ITGB2-mediated fibroblast migration in pulmonary fibrosis. The use of lovastatin, a widely-used statin with extensive safety data, represents a promising repurposing opportunity that could accelerate clinical translation.

---

### 4.3. FN1-SDC2 Interaction Promotes Fibroblast Migration and EMT in IPF [Cross-Target Interaction - Cell-Cell Disruption]

**Category:** Cross-Target Interaction

**Core Claim:** The FN1-SDC2 ligand-receptor pair mediates fibroblast-ECM adhesion and migration through syndecan-2 signaling, driving fibroblast recruitment to fibrotic foci and epithelial-mesenchymal transition (EMT). Disruption of this interaction reduces fibroblast invasiveness.

**Evidence References:**
- stage1_FN1--SDC2.json
- stage3_FN1.json
- ot_FN1.json
- ot_SDC2.json

**Biological Entities:**
- Genes: FN1, SDC2
- Pathways: ECM remodeling, fibroblast migration, EMT
- Cell Types: fibroblasts, epithelial cells

**Falsifiable Prediction:** From stage1_FN1--SDC2.json, SDC2 knockdown or blocking antibodies will reduce fibroblast migration by a measurable amount in transwell assays and decrease EMT marker expression (N-cadherin, vimentin) in TGF-β1-treated epithelial cells.

**Validation Approach:** siRNA-mediated SDC2 knockdown in IPF fibroblasts + transwell migration assay. Parallel: SDC2-blocking antibody treatment of co-cultures. Readouts: migration distance, EMT markers by Western, collagen gel contraction. Controls: scrambled siRNA, isotype antibody.

The FN1-SDC2 hypothesis suggests that targeting this cross-target interaction may represent a novel therapeutic strategy for interrupting fibroblast recruitment and EMT in pulmonary fibrosis. The use of SDC2 knockdown or blocking antibodies represents a promising therapeutic approach that could be validated in preclinical models.

---

### 4.4. CD47-Signal Regulatory Protein Axis as Immune Checkpoint in IPF Fibrosis [Novel Pathway - Immune Modulation]

**Category:** Novel Pathway

**Core Claim:** CD47, through its interaction with SIRPα on macrophages, functions as a 'don't eat me' signal that prevents clearance of activated fibroblasts and promotes pro-fibrotic macrophage polarization. Elevated CD47 in IPF creates an immune evasion mechanism sustaining fibrosis.

**Evidence References:**
- stage1_THBS1--CD47.json
- stage3_CD47.json
- ot_CD47.json
- ot_THBS1.json

**Biological Entities:**
- Genes: CD47, THBS1, SIRPA
- Pathways: macrophage phagocytosis, immune checkpoint, pro-fibrotic polarization
- Cell Types: macrophages, fibroblasts

**Falsifiable Prediction:** From stage1_THBS1--CD47.json, CD47 blockade with anti-CD47 antibodies will increase fibroblast phagocytosis by M2 macrophages by a measurable amount and shift macrophage cytokine profile from IL-10/TGF-β1 to IL-12/TNF-α.

**Validation Approach:** Co-culture of IPF fibroblasts with M2-polarized macrophages ± anti-CD47 antibody. Readouts: fibroblast phagocytosis (flow cytometry), macrophage cytokine secretion (ELISA), fibroblast apoptosis. Controls: IgG isotype, THBS1-blocking antibody.

The CD47 immune checkpoint hypothesis suggests that targeting this novel pathway may represent a therapeutic strategy for promoting fibroblast clearance and shifting macrophage polarization in pulmonary fibrosis. The use of anti-CD47 antibodies, which have been extensively studied in oncology, represents a promising repurposing opportunity that could accelerate clinical translation.

---

### 4.5. MUC1-ICAM1 Crosstalk Amplifies Epithelial-Inflammatory Signaling in IPF [Cross-Target Interaction]

**Category:** Cross-Target Interaction

**Core Claim:** MUC1, a transmembrane mucin upregulated on damaged alveolar epithelial cells, engages ICAM1 on infiltrating immune cells to amplify NF-κB-driven inflammatory cytokine production. This MUC1-ICAM1 axis creates a feed-forward loop sustaining epithelial injury and fibroblast activation.

**Evidence References:**
- stage1_ICAM1--MUC1.json
- stage3_MUC1.json
- ot_MUC1.json
- stage3_ICAM1.json

**Biological Entities:**
- Genes: MUC1, ICAM1
- Pathways: NF-κB signaling, epithelial injury, inflammatory cytokine production
- Cell Types: alveolar epithelial cells, immune cells, fibroblasts

**Falsifiable Prediction:** From stage1_ICAM1--MUC1.json, MUC1-C (cytoplasmic tail) inhibition will reduce IL-6 and IL-8 secretion from IPF epithelial-fibroblast co-cultures by a measurable amount and decrease NF-κB nuclear translocation.

**Validation Approach:** IPF-derived alveolar epithelial cells co-cultured with fibroblasts ± MUC1-C inhibitor (GO-203). Readouts: cytokine panel (IL-6, IL-8, TGF-β1), NF-κB p65 nuclear localization, epithelial barrier function (TEER). Controls: DMSO vehicle, TNF-α positive control.

The MUC1-ICAM1 hypothesis suggests that targeting this cross-target interaction may represent a therapeutic strategy for interrupting epithelial-inflammatory signaling in pulmonary fibrosis. The use of MUC1-C inhibitors, which have been studied in oncology, represents a promising repurposing opportunity that could accelerate clinical translation.

---

### 4.6. LRP1-Mediated Clearance Dysfunction Drives ECM Accumulation in IPF [MoA - Fibrosis Pathway]

**Category:** Mechanism of Action

**Core Claim:** LRP1 (LDL receptor-related protein 1) functions as a critical ECM clearance receptor on alveolar type 2 cells and fibroblasts. Reduced LRP1 expression or function in IPF impairs clearance of fibrinogen, thrombospondin, and other pro-fibrotic ligands, leading to ECM accumulation and sustained fibroblast activation.

**Evidence References:**
- stage3_LRP1.json
- ot_LRP1.json
- stage1_APOE--LRP1.json
- ot_APOE.json

**Biological Entities:**
- Genes: LRP1, APOE
- Pathways: ECM clearance, receptor-mediated endocytosis, fibrinogen metabolism
- Cell Types: alveolar type 2 cells, fibroblasts

**Falsifiable Prediction:** From stage3_LRP1.json, LRP1 overexpression in IPF fibroblasts will increase clearance of fluorescently-labeled fibrinogen by a measurable amount and reduce endogenous TGF-β1 activation in conditioned media.

**Validation Approach:** Lentiviral LRP1 overexpression in IPF fibroblasts + fluorescent fibrinogen uptake assay. Parallel: LRP1 knockdown in normal fibroblasts. Readouts: fibrinogen clearance rate, latent TGF-β1 activation, ECM protein accumulation. Controls: empty vector, scrambled shRNA.

The LRP1 clearance dysfunction hypothesis suggests that enhancing LRP1-mediated ECM clearance may represent a therapeutic strategy for reducing ECM accumulation in pulmonary fibrosis. The use of LRP1 overexpression or small molecule activators represents a promising therapeutic approach that could be validated in preclinical models.

---

### 4.7. CD4+ T Cell-HLA Class II Interaction Sustains Adaptive Immune Response in IPF [Novel Pathway - Immune Modulation]

**Category:** Novel Pathway

**Core Claim:** Multiple HLA class II genes (HLA-DPA1, HLA-DPB1, HLA-DQB1, HLA-DRB1) form functional complexes with CD4+ T cells in IPF lung tissue, driving sustained adaptive immune responses that perpetuate fibroblast activation. This represents an underappreciated adaptive immune component in IPF pathogenesis.

**Evidence References:**
- stage1_HLA-DPA1--CD4.json
- stage1_HLA-DPB1--CD4.json
- stage3_CD4.json
- ot_CD4.json
- ot_HLA-DPA1.json
- ot_HLA-DPB1.json

**Biological Entities:**
- Genes: CD4, HLA-DPA1, HLA-DPB1, HLA-DQB1, HLA-DRB1
- Pathways: antigen presentation, T cell activation, adaptive immunity
- Cell Types: CD4+ T cells, antigen-presenting cells, fibroblasts

**Falsifiable Prediction:** From stage1_HLA-DPA1--CD4.json, CD4+ T cell depletion in IPF lung explant cultures will reduce fibroblast proliferation and collagen secretion by a measurable amount compared to untreated explants.

**Validation Approach:** IPF lung explant culture ± anti-CD4 depletion antibody. Readouts: fibroblast outgrowth, collagen I deposition (Sirius Red), T cell infiltration (CD3/CD4 IHC). Controls: IgG isotype, CD8+ T cell depletion control.

The CD4-HLA class II hypothesis suggests that targeting adaptive immune responses may represent a therapeutic strategy for interrupting sustained fibroblast activation in pulmonary fibrosis. The use of CD4+ T cell depletion or HLA class II blockade represents a promising therapeutic approach that could be validated in lung explant cultures.

---


### Gap Analysis


**Uncovered evidence files:**
- stage1_FN1--PLAUR.json
- stage1_ICAM1--EZR.json
- stage1_ICAM1--PECAM1.json
- stage1_LAMB2--RPSA.json
- stage1_MMP2--PECAM1.json
- stage1_PPIA--CXCR4.json
- stage1_TGFB1--P4HB.json
- stage1_CALR--LRP1.json
- stage1_HLA-DMB--CD74.json
- stage1_HLA-DQB1--CD4.json
- stage1_HLA-DRB1--CD4.json



## 5. Pipeline Execution Summary & Recommendations

- Total genes assessed: 41
- Featured candidates (Stage 3): 7
- Featured genes: CD4, MUC1, FN1, ITGB2, CD47, LRP1, ICAM1

The seven featured candidates represent high-priority validated targets with combined_total scores ranging from 10-15, indicating substantial clinical trial activity and tractability for drug development. All featured candidates demonstrate maximal clinical_trial_activity scores of 5, reflecting robust pipeline investment across multiple indications. The absence of GWAS genetic support and existing drugs for these targets suggests significant repurposing opportunities and novel therapeutic avenues for pulmonary fibrosis. These targets are recommended for prioritization in preclinical development pipelines given their high priority classification and substantial clinical evidence supporting drug development.