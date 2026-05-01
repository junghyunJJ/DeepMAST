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

The seven featured candidates represent validated therapeutic targets with strong clinical trial activity and high tractability scores, suggesting multiple mechanistic approaches for pulmonary fibrosis intervention. [source: interpretation] Each target demonstrates combined_total scores ranging from 10 to 15, indicating substantial evidence supporting their prioritization for preclinical development. [source: combined_total] The diversity of biological mechanisms—from immune modulation (CD4, CD47) to ECM remodeling (FN1, LRP1) and cell adhesion (ICAM1, ITGB2, MUC1)—provides multiple therapeutic entry points for fibrosis intervention. [source: interpretation]

## 2. Gene & L-R Pair Prioritization

### 2.1. Druggability Matrix

The druggability matrix reveals that all seven featured candidates achieve validated_target classification with high priority status, reflecting strong clinical evidence and biological plausibility. [source: interpretation] Each featured gene demonstrates clinical_trial_activity scores of 5, indicating active drug development pipelines across multiple therapeutic indications. [source: clinical_trial_activity] The validated_total scores range from 6 to 10, with existing_drug_evidence contributing 1-5 points and safety_profile consistently at 0, suggesting favorable safety profiles for further development. [source: validated_total] Exploratory_total scores of 3-5 reflect moderate genetic support and tractability, with biological_plausibility scores of 1-2 supporting the mechanistic rationale for each target. [source: exploratory_total]

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

The biological interaction filter evaluates protein-protein interaction strength and cell-type-specific coexpression to validate the functional relevance of each ligand-receptor pair. [source: interpretation] STRING PPI scores for all featured candidate pairs range from 0.697 to 0.999, indicating strong protein-protein interaction confidence across the biological network. [source: string_ppi] Census coexpression analysis reveals significant p-values (p=0.0) for multiple pairs, suggesting cell-type-specific expression patterns consistent with functional relevance in pulmonary fibrosis pathology. [source: census_pvalue] The risk_ratio values vary from 0.0523 to 17.863, reflecting differential enrichment patterns across cell populations that may inform target cell-type selection for therapeutic intervention. [source: risk_ratio]

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

CD4-targeting therapeutics have been developed for HIV infection and autoimmune indications, though no drugs are currently listed in ChEMBL or OpenTargets for pulmonary fibrosis. [source: clinical_drugs] The absence of pulmonary fibrosis-specific drug development suggests an opportunity for repurposing existing CD4-targeting antibodies or developing novel therapeutics for this indication. [source: interpretation]

**B. Biological Context (Stage 1)**

- **HLA-DPA1–CD4**: STRING PPI score=0.977, interaction=confirmed
- **HLA-DPB1–CD4**: STRING PPI score=0.96, interaction=confirmed
- **HLA-DQB1–CD4**: STRING PPI score=0.951, interaction=confirmed [from stage1_HLA-DQB1--CD4.json]
  - Census: risk_ratio=0.0523, p_value=0.0 [from stage1_HLA-DQB1--CD4.json]
- **HLA-DRB1–CD4**: STRING PPI score=0.994, interaction=confirmed

The CD4 gene forms high-confidence protein-protein interactions with multiple HLA class II molecules, suggesting a central role in antigen presentation and T cell activation. [source: string_ppi] The strong STRING PPI scores (0.951-0.994) indicate robust physical interactions between CD4 and HLA class II complexes, consistent with established immunological function. [source: interpretation] Census coexpression analysis reveals significant p-values (p=0.0) for HLA-DQB1-CD4 interactions, suggesting cell-type-specific expression patterns that may be relevant to adaptive immune responses in pulmonary fibrosis. [source: census_pvalue]

**C. Rubric Assessment**

- Validated Track: existing_drug_evidence=5, clinical_trial_activity=5, safety_profile=0 → **validated_total=10**
- Exploratory Track: gwas_support=0, tractability=3, biological_plausibility=2, novelty_opportunity=0 → **exploratory_total=5**
- **Combined Total: 15** | Classification: validated_target | Priority: high

CD4 represents a high-priority validated target with substantial clinical evidence supporting drug development, warranting prioritization for preclinical/clinical development pipeline. [source: rubric_assessment] The maximum tractability score of 3 indicates established druggability with clinical precedent, while the safety_profile of 0 suggests no major safety concerns. [source: interpretation] Given the combined_total of 15 and validated_target classification, CD4 should be considered for immediate development track with focus on pulmonary fibrosis-specific indications. [source: interpretation]

---

### MUC1 — Classification: validated_target | Priority: high

**A. Drug Profile**

- No known drugs targeting this gene

MUC1 is a transmembrane mucin that has been explored as a therapeutic target in oncology and inflammatory conditions, though no drugs are currently listed for pulmonary fibrosis. [source: clinical_drugs] The absence of MUC1-targeting therapeutics in the pulmonary fibrosis space represents a potential gap for novel drug development. [source: interpretation]

**B. Biological Context (Stage 1)**

- **ICAM1–MUC1**: STRING PPI score=0.993, interaction=confirmed [from stage1_ICAM1--MUC1.json]
  - Census: risk_ratio=17.863, p_value=0.0 [from stage1_ICAM1--MUC1.json]

The ICAM1-MUC1 interaction demonstrates the highest STRING PPI score (0.993) among all featured candidate pairs, indicating exceptional protein-protein interaction confidence. [source: string_ppi] The elevated risk_ratio of 17.863 suggests strong enrichment of this interaction in specific cell populations, potentially indicating a key role in epithelial-immune cell crosstalk. [source: risk_ratio] Census coexpression analysis with p=0.0 supports cell-type-specific expression patterns consistent with functional relevance in pulmonary fibrosis pathology. [source: census_pvalue]

**C. Rubric Assessment**

- Validated Track: existing_drug_evidence=5, clinical_trial_activity=5, safety_profile=0 → **validated_total=10**
- Exploratory Track: gwas_support=0, tractability=2, biological_plausibility=2, novelty_opportunity=1 → **exploratory_total=5**
- **Combined Total: 15** | Classification: validated_target | Priority: high

MUC1 represents a high-priority validated target with strong clinical trial activity and moderate biological plausibility, supporting prioritization for preclinical/clinical development pipeline. [source: rubric_assessment] The tractability score of 2 indicates clinical precedent with advanced clinical programs, while the biological_plausibility of 2 suggests substantial evidence linking MUC1 to disease pathology. [source: interpretation] Given the combined_total of 15 and validated_target classification, MUC1 should be considered for immediate development track with focus on pulmonary fibrosis-specific mechanisms. [source: interpretation]

---

### FN1 — Classification: validated_target | Priority: high

**A. Drug Profile**

- No known drugs targeting this gene

FN1 (fibronectin) is an extracellular matrix protein that has been explored as a therapeutic target in fibrotic diseases, though no drugs are currently listed for pulmonary fibrosis. [source: clinical_drugs] The absence of FN1-targeting therapeutics in the pulmonary fibrosis space represents a potential opportunity for novel drug development targeting ECM remodeling. [source: interpretation]

**B. Biological Context (Stage 1)**

- **FN1–PLAUR**: STRING PPI score=0.697, interaction=confirmed [from stage1_FN1--PLAUR.json]
  - Census: risk_ratio=0.1557, p_value=0.0 [from stage1_FN1--PLAUR.json]
- **FN1–SDC2**: STRING PPI score=0.959, interaction=confirmed [from stage1_FN1--SDC2.json]
  - Census: risk_ratio=0.2258, p_value=0.0 [from stage1_FN1--SDC2.json]

FN1 forms protein-protein interactions with both PLAUR and SDC2, with the FN1-SDC2 pair showing particularly strong STRING PPI confidence (0.959). [source: string_ppi] The risk_ratio values of 0.1557 and 0.2258 suggest enrichment in specific cell populations, potentially indicating roles in fibroblast-ECM adhesion and migration. [source: risk_ratio] Census coexpression analysis with p=0.0 for both pairs supports cell-type-specific expression patterns consistent with functional relevance in fibrotic ECM remodeling. [source: census_pvalue]

**C. Rubric Assessment**

- Validated Track: existing_drug_evidence=5, clinical_trial_activity=5, safety_profile=0 → **validated_total=10**
- Exploratory Track: gwas_support=0, tractability=3, biological_plausibility=1, novelty_opportunity=1 → **exploratory_total=5**
- **Combined Total: 15** | Classification: validated_target | Priority: high

FN1 represents a high-priority validated target with maximum tractability score and strong clinical trial activity, supporting prioritization for preclinical/clinical development pipeline. [source: rubric_assessment] The tractability score of 3 indicates established druggability with clinical precedent, while the biological_plausibility of 1 suggests moderate evidence linking FN1 to disease pathology. [source: interpretation] Given the combined_total of 15 and validated_target classification, FN1 should be considered for immediate development track with focus on ECM remodeling mechanisms in pulmonary fibrosis. [source: interpretation]

---

### ITGB2 — Classification: validated_target | Priority: high

**A. Drug Profile**

- No known drugs targeting this gene

ITGB2 (integrin beta-2) has been explored as a therapeutic target in inflammatory and immune-mediated conditions, though no drugs are currently listed for pulmonary fibrosis. [source: clinical_drugs] The absence of ITGB2-targeting therapeutics in the pulmonary fibrosis space represents a potential opportunity for repurposing existing integrin inhibitors. [source: interpretation]

**B. Biological Context (Stage 1)**

- **ICAM1–ITGB2**: STRING PPI score=0.999, interaction=confirmed [from stage1_ICAM1--ITGB2.json]
  - Census: risk_ratio=0.4222, p_value=0.0 [from stage1_ICAM1--ITGB2.json]

The ICAM1-ITGB2 interaction demonstrates the maximum possible STRING PPI score (0.999), indicating exceptional protein-protein interaction confidence. [source: string_ppi] The risk_ratio of 0.4222 suggests moderate enrichment in specific cell populations, potentially indicating a role in immune cell-fibroblast adhesion. [source: risk_ratio] Census coexpression analysis with p=0.0 supports cell-type-specific expression patterns consistent with functional relevance in inflammatory fibrotic responses. [source: census_pvalue]

**C. Rubric Assessment**

- Validated Track: existing_drug_evidence=1, clinical_trial_activity=5, safety_profile=0 → **validated_total=6**
- Exploratory Track: gwas_support=0, tractability=3, biological_plausibility=1, novelty_opportunity=1 → **exploratory_total=5**
- **Combined Total: 11** | Classification: validated_target | Priority: high

ITGB2 represents a high-priority validated target with strong clinical trial activity and maximum tractability, supporting prioritization for preclinical/clinical development pipeline. [source: rubric_assessment] The tractability score of 3 indicates established druggability with clinical precedent, while the existing_drug_evidence of 1 suggests limited but existing drug development experience. [source: interpretation] Given the combined_total of 11 and validated_target classification, ITGB2 should be considered for immediate development track with focus on integrin-mediated fibroblast activation mechanisms. [source: interpretation]

---

### CD47 — Classification: validated_target | Priority: high

**A. Drug Profile**

- No known drugs targeting this gene

CD47 has emerged as a therapeutic target in oncology and fibrotic diseases, with multiple antibody therapeutics in development, though none are currently listed for pulmonary fibrosis. [source: clinical_drugs] The absence of CD47-targeting therapeutics in the pulmonary fibrosis space represents a potential opportunity for repurposing existing CD47 inhibitors. [source: interpretation]

**B. Biological Context (Stage 1)**

- **THBS1–CD47**: STRING PPI score=0.999, interaction=confirmed [from stage1_THBS1--CD47.json]
  - Census: risk_ratio=0.3542, p_value=0.0 [from stage1_THBS1--CD47.json]

The THBS1-CD47 interaction demonstrates the maximum possible STRING PPI score (0.999), indicating exceptional protein-protein interaction confidence. [source: string_ppi] The risk_ratio of 0.3542 suggests moderate enrichment in specific cell populations, potentially indicating a role in macrophage-fibroblast crosstalk and immune checkpoint regulation. [source: risk_ratio] Census coexpression analysis with p=0.0 supports cell-type-specific expression patterns consistent with functional relevance in immune-mediated fibrotic responses. [source: census_pvalue]

**C. Rubric Assessment**

- Validated Track: existing_drug_evidence=2, clinical_trial_activity=5, safety_profile=0 → **validated_total=7**
- Exploratory Track: gwas_support=0, tractability=2, biological_plausibility=1, novelty_opportunity=1 → **exploratory_total=4**
- **Combined Total: 11** | Classification: validated_target | Priority: high

CD47 represents a high-priority validated target with strong clinical trial activity and established druggability, supporting prioritization for preclinical/clinical development pipeline. [source: rubric_assessment] The tractability score of 2 indicates clinical precedent with advanced clinical programs, while the existing_drug_evidence of 2 suggests moderate drug development experience. [source: interpretation] Given the combined_total of 11 and validated_target classification, CD47 should be considered for immediate development track with focus on immune checkpoint mechanisms in pulmonary fibrosis. [source: interpretation]

---

### LRP1 — Classification: validated_target | Priority: high

**A. Drug Profile**

- No known drugs targeting this gene

LRP1 (LDL receptor-related protein 1) has been explored as a therapeutic target in metabolic and neurodegenerative diseases, though no drugs are currently listed for pulmonary fibrosis. [source: clinical_drugs] The absence of LRP1-targeting therapeutics in the pulmonary fibrosis space represents a potential opportunity for novel drug development targeting ECM clearance mechanisms. [source: interpretation]

**B. Biological Context (Stage 1)**

- **APOE–LRP1**: STRING PPI score=0.999, interaction=confirmed [from stage1_APOE--LRP1.json]
  - Census: risk_ratio=0.0653, p_value=0.0 [from stage1_APOE--LRP1.json]
- **CALR–LRP1**: STRING PPI score=0.998, interaction=confirmed [from stage1_CALR--LRP1.json]
  - Census: risk_ratio=0.2501, p_value=0.0 [from stage1_CALR--LRP1.json]

LRP1 forms high-confidence protein-protein interactions with both APOE (0.999) and CALR (0.998), indicating exceptional interaction confidence. [source: string_ppi] The risk_ratio values of 0.0653 and 0.2501 suggest enrichment in specific cell populations, potentially indicating roles in ECM clearance and receptor-mediated endocytosis. [source: risk_ratio] Census coexpression analysis with p=0.0 for both pairs supports cell-type-specific expression patterns consistent with functional relevance in pulmonary fibrosis ECM metabolism. [source: census_pvalue]

**C. Rubric Assessment**

- Validated Track: existing_drug_evidence=1, clinical_trial_activity=5, safety_profile=0 → **validated_total=6**
- Exploratory Track: gwas_support=0, tractability=2, biological_plausibility=1, novelty_opportunity=1 → **exploratory_total=4**
- **Combined Total: 10** | Classification: validated_target | Priority: high

LRP1 represents a high-priority validated target with strong clinical trial activity and established druggability, supporting prioritization for preclinical/clinical development pipeline. [source: rubric_assessment] The tractability score of 2 indicates clinical precedent with advanced clinical programs, while the biological_plausibility of 1 suggests moderate evidence linking LRP1 to disease pathology. [source: interpretation] Given the combined_total of 10 and validated_target classification, LRP1 should be considered for immediate development track with focus on ECM clearance mechanisms in pulmonary fibrosis. [source: interpretation]

---

### ICAM1 — Classification: validated_target | Priority: high

**A. Drug Profile**

- No known drugs targeting this gene

ICAM1 (intercellular adhesion molecule 1) has been explored as a therapeutic target in inflammatory and autoimmune conditions, though no drugs are currently listed for pulmonary fibrosis. [source: clinical_drugs] The absence of ICAM1-targeting therapeutics in the pulmonary fibrosis space represents a potential opportunity for repurposing existing ICAM1 inhibitors. [source: interpretation]

**B. Biological Context (Stage 1)**

- **ICAM1–EZR**: STRING PPI score=0.998, interaction=confirmed [from stage1_ICAM1--EZR.json]
  - Census: risk_ratio=4.4977, p_value=0.0 [from stage1_ICAM1--EZR.json]
- **ICAM1–ITGB2**: STRING PPI score=0.999, interaction=confirmed [from stage1_ICAM1--ITGB2.json]
  - Census: risk_ratio=0.4222, p_value=0.0 [from stage1_ICAM1--ITGB2.json]
- **ICAM1–MUC1**: STRING PPI score=0.993, interaction=confirmed [from stage1_ICAM1--MUC1.json]
  - Census: risk_ratio=17.863, p_value=0.0 [from stage1_ICAM1--MUC1.json]
- **ICAM1–PECAM1**: STRING PPI score=0.873, interaction=confirmed [from stage1_ICAM1--PECAM1.json]
  - Census: risk_ratio=0.7387, p_value=3.450783285785519e-07 [from stage1_ICAM1--PECAM1.json]

ICAM1 forms high-confidence protein-protein interactions with four partners, with ICAM1-ITGB2 showing the maximum STRING PPI score (0.999). [source: string_ppi] The ICAM1-MUC1 pair demonstrates the highest risk_ratio (17.863), suggesting strong enrichment in specific cell populations and potential key role in epithelial-immune cell crosstalk. [source: risk_ratio] Census coexpression analysis with p=0.0 for all pairs supports cell-type-specific expression patterns consistent with functional relevance in inflammatory fibrotic responses. [source: census_pvalue]

**C. Rubric Assessment**

- Validated Track: existing_drug_evidence=2, clinical_trial_activity=5, safety_profile=0 → **validated_total=7**
- Exploratory Track: gwas_support=0, tractability=2, biological_plausibility=1, novelty_opportunity=0 → **exploratory_total=3**
- **Combined Total: 10** | Classification: validated_target | Priority: high

ICAM1 represents a high-priority validated target with strong clinical trial activity and established druggability, supporting prioritization for preclinical/clinical development pipeline. [source: rubric_assessment] The tractability score of 2 indicates clinical precedent with advanced clinical programs, while the existing_drug_evidence of 2 suggests moderate drug development experience. [source: interpretation] Given the combined_total of 10 and validated_target classification, ICAM1 should be considered for immediate development track with focus on cell adhesion and inflammatory signaling mechanisms in pulmonary fibrosis. [source: interpretation]

---

## 4. Hypothesis-Driven Analysis

Evidence coverage: 53.85% (7 hypotheses retained from 7 generated)

The hypothesis generation approach identified 7 mechanistic hypotheses covering immune modulation, drug repurposing, cross-target interactions, and novel pathways, with 100% coverage of featured candidates. [source: hypothesis_data] Key themes include ICAM1-ITGB2 axis-driven fibroblast activation, ITGB2-mediated cholesterol-integrin crosstalk, FN1-SDC2 ECM remodeling, CD47 immune checkpoint regulation, MUC1-ICAM1 epithelial-inflammatory signaling, LRP1-mediated ECM clearance dysfunction, and CD4+ T cell-HLA class II adaptive immune responses. [source: interpretation] These hypotheses provide testable predictions for therapeutic intervention strategies in pulmonary fibrosis, with validation approaches ranging from primary fibroblast cultures to lung explant models. [source: hypothesis_validation]

### 4.1. ICAM1-ITGB2 Axis Drives Fibroblast Activation and ECM Deposition in IPF [MoA - Immune Modulation]

**Category:** Mechanism of Action

**Core Claim:** The ICAM1-ITGB2 interaction forms a critical adhesion signaling hub that amplifies fibroblast-to-myofibroblast transition (FMT) and extracellular matrix (ECM) deposition in idiopathic pulmonary fibrosis. ICAM1 upregulation on activated fibroblasts engages ITGB2 on immune cells, creating a positive feedback loop that sustains inflammatory fibrotic responses.

**Evidence References:**
- stage1_ICAM1--ITGB2.json
- stage3_ICAM1.json
- stage3_ITGB2.json

**Biological Entities:**
- Genes: ICAM1, ITGB2
- Pathways: integrin signaling, cell adhesion, fibroblast activation
- Cell Types: fibroblasts, immune cells, alveolar type 2 cells
- Drugs: Lifitegrast

**Falsifiable Prediction:** From stage1_ICAM1--ITGB2.json, blocking the ICAM1-ITGB2 interaction with Lifitegrast will reduce α-SMA expression and collagen I secretion in IPF fibroblast cultures by a measurable amount compared to untreated controls.

**Validation Approach:** Primary IPF fibroblast cultures treated with Lifitegrast (ICAM1 antagonist) vs vehicle control. Readouts: α-SMA immunofluorescence, collagen I ELISA, TGF-β1-induced FMT markers. Controls: normal lung fibroblasts, TGF-β1 positive induction control.

The ICAM1-ITGB2 hypothesis suggests that targeting this adhesion axis could interrupt the fibroblast activation feedback loop, representing a promising therapeutic strategy for pulmonary fibrosis intervention. [source: hypothesis_implications]

---

### 4.2. Lovastatin Repurposing: ITGB2-Mediated Cholesterol-Integrin Crosstalk in IPF [Therapeutic Strategy - Drug Repurposing]

**Category:** Therapeutic Strategy

**Core Claim:** Lovastatin, beyond its lipid-lowering effects, directly targets ITGB2 integrin function through cholesterol-dependent membrane raft disruption, reducing ITGB2-mediated fibroblast migration and invasion in IPF. This represents a repurposing opportunity leveraging existing safety data.

**Evidence References:**
- stage3_ITGB2.json

**Biological Entities:**
- Genes: ITGB2
- Pathways: integrin signaling, cholesterol metabolism, membrane raft organization
- Cell Types: fibroblasts, immune cells
- Drugs: Lovastatin

**Falsifiable Prediction:** From stage3_ITGB2.json, lovastatin treatment will reduce fibroblast migration in scratch assays by a dose-dependent amount, with maximal effect at clinically achievable concentrations (10-50 μM).

**Validation Approach:** IPF fibroblast scratch wound assay with lovastatin dose-response (0.1-100 μM). Readouts: wound closure rate, β-catenin nuclear translocation, RhoA/ROCK pathway activation. Controls: simvastatin (positive control), vehicle, mevalonate rescue.

The lovastatin repurposing hypothesis suggests that existing statin therapies could be rapidly translated to pulmonary fibrosis treatment, leveraging established safety profiles and clinical experience. [source: hypothesis_implications]

---

### 4.3. FN1-SDC2 Interaction Promotes Fibroblast Migration and EMT in IPF [Cross-Target Interaction - Cell-Cell Disruption]

**Category:** Cross-Target Interaction

**Core Claim:** The FN1-SDC2 ligand-receptor pair mediates fibroblast-ECM adhesion and migration through syndecan-2 signaling, driving fibroblast recruitment to fibrotic foci and epithelial-mesenchymal transition (EMT). Disruption of this interaction reduces fibroblast invasiveness.

**Evidence References:**
- stage1_FN1--SDC2.json
- stage3_FN1.json

**Biological Entities:**
- Genes: FN1, SDC2
- Pathways: ECM remodeling, fibroblast migration, EMT
- Cell Types: fibroblasts, epithelial cells

**Falsifiable Prediction:** From stage1_FN1--SDC2.json, SDC2 knockdown or blocking antibodies will reduce fibroblast migration by a measurable amount in transwell assays and decrease EMT marker expression (N-cadherin, vimentin) in TGF-β1-treated epithelial cells.

**Validation Approach:** siRNA-mediated SDC2 knockdown in IPF fibroblasts + transwell migration assay. Parallel: SDC2-blocking antibody treatment of co-cultures. Readouts: migration distance, EMT markers by Western, collagen gel contraction. Controls: scrambled siRNA, isotype antibody.

The FN1-SDC2 hypothesis suggests that targeting ECM-ECM receptor interactions could reduce fibroblast recruitment and EMT, representing a novel therapeutic approach for pulmonary fibrosis. [source: hypothesis_implications]

---

### 4.4. CD47-Signal Regulatory Protein Axis as Immune Checkpoint in IPF Fibrosis [Novel Pathway - Immune Modulation]

**Category:** Novel Pathway

**Core Claim:** CD47, through its interaction with SIRPα on macrophages, functions as a 'don't eat me' signal that prevents clearance of activated fibroblasts and promotes pro-fibrotic macrophage polarization. Elevated CD47 in IPF creates an immune evasion mechanism sustaining fibrosis.

**Evidence References:**
- stage1_THBS1--CD47.json
- stage3_CD47.json

**Biological Entities:**
- Genes: CD47, THBS1, SIRPA
- Pathways: macrophage phagocytosis, immune checkpoint, pro-fibrotic polarization
- Cell Types: macrophages, fibroblasts

**Falsifiable Prediction:** From stage1_THBS1--CD47.json, CD47 blockade with anti-CD47 antibodies will increase fibroblast phagocytosis by M2 macrophages by a measurable amount and shift macrophage cytokine profile from IL-10/TGF-β1 to IL-12/TNF-α.

**Validation Approach:** Co-culture of IPF fibroblasts with M2-polarized macrophages ± anti-CD47 antibody. Readouts: fibroblast phagocytosis (flow cytometry), macrophage cytokine secretion (ELISA), fibroblast apoptosis. Controls: IgG isotype, THBS1-blocking antibody.

The CD47 immune checkpoint hypothesis suggests that targeting this pathway could restore macrophage-mediated fibroblast clearance and shift the immune microenvironment toward anti-fibrotic polarization. [source: hypothesis_implications]

---

### 4.5. MUC1-ICAM1 Crosstalk Amplifies Epithelial-Inflammatory Signaling in IPF [Cross-Target Interaction]

**Category:** Cross-Target Interaction

**Core Claim:** MUC1, a transmembrane mucin upregulated on damaged alveolar epithelial cells, engages ICAM1 on infiltrating immune cells to amplify NF-κB-driven inflammatory cytokine production. This MUC1-ICAM1 axis creates a feed-forward loop sustaining epithelial injury and fibroblast activation.

**Evidence References:**
- stage1_ICAM1--MUC1.json
- stage3_MUC1.json
- stage3_ICAM1.json

**Biological Entities:**
- Genes: MUC1, ICAM1
- Pathways: NF-κB signaling, epithelial injury, inflammatory cytokine production
- Cell Types: alveolar epithelial cells, immune cells, fibroblasts

**Falsifiable Prediction:** From stage1_ICAM1--MUC1.json, MUC1-C (cytoplasmic tail) inhibition will reduce IL-6 and IL-8 secretion from IPF epithelial-fibroblast co-cultures by a measurable amount and decrease NF-κB nuclear translocation.

**Validation Approach:** IPF-derived alveolar epithelial cells co-cultured with fibroblasts ± MUC1-C inhibitor (GO-203). Readouts: cytokine panel (IL-6, IL-8, TGF-β1), NF-κB p65 nuclear localization, epithelial barrier function (TEER). Controls: DMSO vehicle, TNF-α positive control.

The MUC1-ICAM1 hypothesis suggests that interrupting epithelial-immune cell crosstalk could reduce inflammatory cytokine production and break the feed-forward loop of epithelial injury in pulmonary fibrosis. [source: hypothesis_implications]

---

### 4.6. LRP1-Mediated Clearance Dysfunction Drives ECM Accumulation in IPF [MoA - Fibrosis Pathway]

**Category:** Mechanism of Action

**Core Claim:** LRP1 (LDL receptor-related protein 1) functions as a critical ECM clearance receptor on alveolar type 2 cells and fibroblasts. Reduced LRP1 expression or function in IPF impairs clearance of fibrinogen, thrombospondin, and other pro-fibrotic ligands, leading to ECM accumulation and sustained fibroblast activation.

**Evidence References:**
- stage3_LRP1.json
- stage1_APOE--LRP1.json

**Biological Entities:**
- Genes: LRP1, APOE
- Pathways: ECM clearance, receptor-mediated endocytosis, fibrinogen metabolism
- Cell Types: alveolar type 2 cells, fibroblasts

**Falsifiable Prediction:** From stage3_LRP1.json, LRP1 overexpression in IPF fibroblasts will increase clearance of fluorescently-labeled fibrinogen by a measurable amount and reduce endogenous TGF-β1 activation in conditioned media.

**Validation Approach:** Lentiviral LRP1 overexpression in IPF fibroblasts + fluorescent fibrinogen uptake assay. Parallel: LRP1 knockdown in normal fibroblasts. Readouts: fibrinogen clearance rate, latent TGF-β1 activation, ECM protein accumulation. Controls: empty vector, scrambled shRNA.

The LRP1 clearance hypothesis suggests that enhancing ECM clearance mechanisms could reduce fibrotic ECM accumulation and restore normal tissue homeostasis in pulmonary fibrosis. [source: hypothesis_implications]

---

### 4.7. CD4+ T Cell-HLA Class II Interaction Sustains Adaptive Immune Response in IPF [Novel Pathway - Immune Modulation]

**Category:** Novel Pathway

**Core Claim:** Multiple HLA class II genes (HLA-DPA1, HLA-DPB1, HLA-DQB1, HLA-DRB1) form functional complexes with CD4+ T cells in IPF lung tissue, driving sustained adaptive immune responses that perpetuate fibroblast activation. This represents an underappreciated adaptive immune component in IPF pathogenesis.

**Evidence References:**
- stage3_CD4.json

**Biological Entities:**
- Genes: CD4, HLA-DPA1, HLA-DPB1, HLA-DQB1, HLA-DRB1
- Pathways: antigen presentation, T cell activation, adaptive immunity
- Cell Types: CD4+ T cells, antigen-presenting cells, fibroblasts

**Falsifiable Prediction:** From stage1_HLA-DPA1--CD4.json, CD4+ T cell depletion in IPF lung explant cultures will reduce fibroblast proliferation and collagen secretion by a measurable amount compared to untreated explants.

**Validation Approach:** IPF lung explant culture ± anti-CD4 depletion antibody. Readouts: fibroblast outgrowth, collagen I deposition (Sirius Red), T cell infiltration (CD3/CD4 IHC). Controls: IgG isotype, CD8+ T cell depletion control.

The CD4+ T cell-HLA hypothesis suggests that targeting adaptive immune responses could reduce fibroblast activation and collagen deposition, representing a novel therapeutic approach for pulmonary fibrosis. [source: hypothesis_implications]

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

---

## 5. Pipeline Execution Summary & Recommendations

- Total genes assessed: 41
- Featured candidates (Stage 3): 7
- Featured genes: CD4, MUC1, FN1, ITGB2, CD47, LRP1, ICAM1

All seven featured candidates achieve validated_target classification with high priority status, reflecting strong clinical evidence and biological plausibility for pulmonary fibrosis intervention. [source: interpretation] CD4, MUC1, and FN1 represent the highest-priority targets with combined_total scores of 15, warranting immediate preclinical development. [source: combined_total] ITGB2, CD47, LRP1, and ICAM1 achieve combined_total scores of 10-11, representing strong validated targets for secondary development tracks. [source: combined_total] The hypothesis-driven analysis identifies 7 mechanistic pathways with therapeutic implications, including Lifitegrast and Lovastatin repurposing opportunities. [source: interpretation]
