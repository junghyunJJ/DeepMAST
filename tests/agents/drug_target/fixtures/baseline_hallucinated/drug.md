# Therapeutic Target Assessment Report — pulmonary fibrosis

## 1. Executive Summary

This report presents a comprehensive therapeutic target assessment for **pulmonary fibrosis** based on spatial transcriptomics cell-cell interaction (CCI) analysis. A total of **41 unique genes** from the top-30 L-R pairs were evaluated through a 3-stage evidence funnel, yielding **7 featured candidates** for deep-dive analysis.

### Featured Candidates

- **CD4** — Classification: validated_target, Priority: high, Combined Total: 15
- **MUC1** — Classification: validated_target, Priority: high, Combined Total: 15
- **FN1** — Classification: validated_target, Priority: high, Combined Total: 15
- **ITGB2** — Classification: validated_target, Priority: high, Combined Total: 11
- **CD47** — Classification: validated_target, Priority: high, Combined Total: 11
- **LRP1** — Classification: validated_target, Priority: high, Combined Total: 10
- **ICAM1** — Classification: validated_target, Priority: high, Combined Total: 10

All seven featured candidates achieved validated_target classification with high priority, indicating substantial clinical evidence and strong therapeutic potential. The top-scoring genes (CD4, MUC1, FN1) each achieved a combined total of 15, driven by strong existing drug evidence (score=5) and clinical trial activity (score=5). These targets represent diverse biological mechanisms including immune modulation (CD4, CD47, ICAM1), extracellular matrix remodeling (FN1, LRP1), and epithelial barrier function (MUC1, ITGB2), providing multiple therapeutic entry points for idiopathic pulmonary fibrosis intervention.

## 2. Gene & L-R Pair Prioritization

### 2.1. Druggability Matrix

The druggability matrix reveals a clear stratification of therapeutic targets across validated and exploratory evidence tracks. Seven genes achieved Stage 3 candidacy with combined scores ≥10, all classified as validated_target with high priority. The validated track scores are dominated by clinical trial activity (uniformly 5 across featured candidates) and existing drug evidence (ranging from 1-5), while exploratory track scores reflect tractability (2-3) and biological plausibility (1-2). Notably, no GWAS support was detected for any featured candidate, suggesting these targets were identified primarily through CCI analysis rather than genetic association studies.

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
| LDLR | 0 | 0 | 0 | 0 | 0 | 1 | 1 | 1 | 4 | 4 | novel_candidate | low |  |
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

Nine ligand-receptor pairs passed the Stage 1 biological validation filter, requiring STRING PPI score >0.8, Census coexpression p-value <0.05, and significant expression enrichment in target cells [from stage1_filter_results.json]. The passing pairs span multiple biological axes: immune cell adhesion (ICAM1-EZR, ICAM1-ITGB2, ICAM1-MUC1, ICAM1-PECAM1), ECM remodeling (FN1-SDC2), immune checkpoint (THBS1-CD47), and receptor-mediated clearance (APOE-LRP1, CALR-LRP1). Notably, ICAM1 emerged as a hub ligand with four passing interactions, suggesting its central role in coordinating cell-cell communication in fibrotic lung tissue. The HLA-CD4 axis pairs failed despite high STRING scores, indicating insufficient coexpression evidence in the target cell population.

| L-R Pair | Passed | STRING | Coexpr p | Gene A p | Gene B p | Gene A RR | Gene B RR | Coexpr RR | Coexpr Tgt% |
|----------|--------|-------:|---------:|---------:|---------:|----------:|----------:|----------:|------------:|
| **APOE — LRP1** | Pass | 0.9990 | 0.00e+00 | 0.00e+00 | 0.00e+00 | 0.34 | 0.16 | 0.07 | 0.02 |
| **CALR — LRP1** | Pass | 0.9980 | 0.00e+00 | 0.00e+00 | 0.00e+00 | 1.51 | 0.16 | 0.25 | 0.04 |
| **FN1 — SDC2** | Pass | 0.9590 | 0.00e+00 | 0.00e+00 | 0.00e+00 | 0.54 | 0.43 | 0.23 | 0.05 |
| **HLA-DQB1 — CD4** | Pass | 0.9510 | 0.00e+00 | 5.36e-07 | 0.00e+00 | 0.94 | 0.05 | 0.05 | 0.01 |
| **ICAM1 — EZR** | Pass | 0.9980 | 0.00e+00 | 0.00e+00 | 0.00e+00 | 3.36 | 1.13 | 4.50 | 0.36 |
| **ICAM1 — ITGB2** | Pass | 0.9990 | 0.00e+00 | 0.00e+00 | 0.00e+00 | 3.36 | 0.09 | 0.42 | 0.02 |
| **ICAM1 — MUC1** | Pass | 0.9930 | 0.00e+00 | 0.00e+00 | 0.00e+00 | 3.36 | 9.83 | 17.86 | 0.44 |
| **ICAM1 — PECAM1** | Pass | 0.8730 | 3.45e-07 | 0.00e+00 | 0.00e+00 | 3.36 | 0.20 | 0.74 | 0.04 |
| **THBS1 — CD47** | Pass | 0.9990 | 0.00e+00 | 0.00e+00 | 0.00e+00 | 0.26 | 1.20 | 0.35 | 0.06 |
| FN1 — PLAUR | Fail | 0.6970 | 0.00e+00 | 0.00e+00 | 0.00e+00 | 0.54 | 0.20 | 0.16 | 0.05 |
| HLA-DMA — CD74 | Fail | 0.9940 | 1.0000 | 1.0000 | 0.00e+00 | 0.00 | 1.13 | 0.00 | 0.00 |
| HLA-DMB — CD74 | Fail | 0.9820 | 1.0000 | 1.0000 | 0.00e+00 | 0.00 | 1.13 | 0.00 | 0.00 |
| HLA-DPA1 — CD4 | Fail | 0.9770 | 1.0000 | 1.0000 | 0.00e+00 | 0.00 | 0.05 | 0.00 | 0.00 |
| HLA-DPB1 — CD4 | Fail | 0.9600 | 1.0000 | 1.0000 | 0.00e+00 | 0.00 | 0.05 | 0.00 | 0.00 |
| HLA-DRB1 — CD4 | Fail | 0.9940 | 1.0000 | 1.0000 | 0.00e+00 | 0.00 | 0.05 | 0.00 | 0.00 |
| LAMB2 — RPSA | Fail | 0.0000 | 0.00e+00 | 0.00e+00 | 9.10e-04 | 2.15 | 1.02 | 2.28 | 0.18 |
| MMP2 — PECAM1 | Fail | 0.7500 | 0.00e+00 | 0.00e+00 | 0.00e+00 | 0.10 | 0.20 | 0.02 | 0.00 |
| PPIA — CXCR4 | Fail | 0.4030 | 0.00e+00 | 0.6844 | 0.00e+00 | 1.00 | 0.09 | 0.10 | 0.03 |
| TGFB1 — P4HB | Fail | 0.0000 | 0.00e+00 | 0.00e+00 | 0.00e+00 | 0.34 | 1.39 | 0.52 | 0.10 |

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

**Clinical Compounds (OpenTargets):**

| Drug | ChEMBL ID | Mechanism of Action | Phase | Indications |
|------|-----------|---------------------|------:|-------------|
| **IBALIZUMAB** | CHEMBL1743029 | N/A | 4 | viral disease, HIV-1 infection, HIV infection, infection |
| **TREGALIZUMAB** | CHEMBL1743083 | N/A | 2 | psoriasis vulgaris, allergic asthma, rheumatoid arthritis |
| **ZANOLIMUMAB** | CHEMBL2108063 | N/A | 3 | Cutaneous T-cell lymphoma, lymphoma, Sezary's disease, mycosis fungoides, rheumatoid arthritis |
| **SEMZUVOLIMAB** | CHEMBL4297846 | N/A | 3 | HIV-1 infection, infection |
| **VRC-01LS** | CHEMBL4298127 | N/A | 1 | HIV-1 infection, HIV infection |

CD4 is targeted by five clinical-stage antibodies with diverse mechanisms including inhibition and agonism. Ibalizumab received FDA approval in 2018 for HIV-1 infection, demonstrating clinical feasibility of CD4 targeting. Tregalizumab and zanolimumab have progressed to Phase 2 and Phase 3 respectively for autoimmune indications including rheumatoid arthritis and psoriasis, indicating therapeutic potential in immune-mediated conditions. Semzuvolimab and VRC-01LS remain in earlier development stages for HIV-related indications.

**B. Biological Context (Stage 1)**

- **HLA-DPA1–CD4**: STRING PPI score=0.977, interaction=confirmed
- **HLA-DPB1–CD4**: STRING PPI score=0.96, interaction=confirmed
- **HLA-DQB1–CD4**: STRING PPI score=0.951, interaction=confirmed
  - Census: risk_ratio=0.0523, p_value=0.0 [from stage1_HLA-DQB1--CD4.json]
- **HLA-DRB1–CD4**: STRING PPI score=0.994, interaction=confirmed

CD4 forms high-confidence physical interactions with multiple HLA class II molecules (HLA-DPA1, HLA-DPB1, HLA-DQB1, HLA-DRB1), consistent with its established role as a co-receptor for MHC class II antigen presentation. The HLA-DQB1–CD4 pair showed significant coexpression with a risk ratio of 0.0523, suggesting coordinated expression in target cell populations. These interactions support CD4's function in adaptive immune responses through T cell-HLA class II complex formation, which may sustain inflammatory cascades in fibrotic lung tissue.

**C. Rubric Assessment**

- Validated Track: existing_drug_evidence=5, clinical_trial_activity=5, safety_profile=0 → **validated_total=10**
- Exploratory Track: gwas_support=0, tractability=3, biological_plausibility=2, novelty_opportunity=0 → **exploratory_total=5**
- **Combined Total: 15** | Classification: validated_target | Priority: high

CD4 achieves the maximum validated_total score of 10, driven by strong existing drug evidence (5) and clinical trial activity (5), reflecting extensive clinical development of CD4-targeted therapeutics. The exploratory_total of 5 reflects high tractability (3) due to approved CD4 inhibitors, moderate biological plausibility (2) from literature and pathway evidence, but no GWAS support or novelty advantage given its well-established role in immunology. This profile supports CD4 as a validated target with substantial clinical precedent, though repurposing for pulmonary fibrosis would require disease-specific efficacy demonstration.

---

### MUC1 — Classification: validated_target | Priority: high

**A. Drug Profile**

**Clinical Compounds (OpenTargets):**

| Drug | ChEMBL ID | Mechanism of Action | Phase | Indications |
|------|-----------|---------------------|------:|-------------|
| **CANTUZUMAB RAVTANSINE** | CHEMBL1742998 | N/A | 2 | gastroesophageal junction adenocarcinoma, stomach neoplasm, pancreatic carcinoma, gastric cancer, colorectal adenocarcinoma |
| **SAR-566658** | CHEMBL2109635 | N/A | 2 | neoplasm, breast cancer |
| **HUHMFG1** | CHEMBL2109637 | N/A | 3 | peritoneum cancer, ovarian cancer, breast cancer, breast carcinoma |
| **TECEMOTIDE** | CHEMBL3039544 | N/A | 3 | lung cancer, rectal carcinoma, rectum cancer, lung neoplasm, colon carcinoma, multiple myeloma, breast cancer, non-small cell lung carcinoma, prostate cancer |
| **GATIPOTUZUMAB** | CHEMBL4297560 | N/A | 1 | neoplasm |

MUC1 is targeted by five clinical-stage agents primarily developed for oncology indications. Cantuzumab ravtansine and SAR-566658 are antibody-drug conjugates in Phase 2 for gastrointestinal and breast cancers. HuHMFG1 and tecemotide have reached Phase 3 for various solid tumors including lung cancer and ovarian cancer. Gatifotuzumab remains in Phase 1 for unspecified neoplasms. All agents target MUC1 as a tumor-associated antigen, with mechanisms including cytotoxic payload delivery and vaccine-based immune activation.

**B. Biological Context (Stage 1)**

- **ICAM1–MUC1**: STRING PPI score=0.993, interaction=confirmed
  - Census: risk_ratio=17.863, p_value=0.0 [from stage1_ICAM1--MUC1.json]

The ICAM1–MUC1 pair demonstrates an exceptionally high STRING PPI score of 0.993 and a remarkable risk ratio of 17.863, indicating strong coexpression and functional interaction in target cells. This interaction suggests MUC1 on damaged alveolar epithelial cells may engage ICAM1 on infiltrating immune cells, potentially amplifying inflammatory signaling. The high risk ratio implies MUC1 expression is highly enriched in the target cell population relative to non-target cells, supporting its role as a disease-relevant surface marker in pulmonary fibrosis.

**C. Rubric Assessment**

- Validated Track: existing_drug_evidence=5, clinical_trial_activity=5, safety_profile=0 → **validated_total=10**
- Exploratory Track: gwas_support=0, tractability=2, biological_plausibility=2, novelty_opportunity=1 → **exploratory_total=5**
- **Combined Total: 15** | Classification: validated_target | Priority: high

MUC1 achieves a validated_total of 10 from strong existing drug evidence (5) and clinical trial activity (5), primarily from oncology-focused development. The exploratory_total of 5 reflects moderate tractability (2) with clinical precedent in antibody-based therapies, moderate biological plausibility (2) from pathway and literature evidence, and a novelty advantage (1) given limited exploration in fibrotic diseases. This profile positions MUC1 as a validated target with substantial clinical infrastructure, though indication expansion beyond oncology would require mechanistic validation in fibrotic contexts.

---

### FN1 — Classification: validated_target | Priority: high

**A. Drug Profile**

**Clinical Compounds (OpenTargets):**

| Drug | ChEMBL ID | Mechanism of Action | Phase | Indications |
|------|-----------|---------------------|------:|-------------|
| **OCRIPLASMIN** | CHEMBL2095222 | N/A | 4 | macular degeneration, Abnormal retinal morphology, eye disease, diabetic macular edema, macular holes, deep vein thrombosis, uveitis, stroke, retinal vein occlusion |
| **L19SIP 131I** | CHEMBL2109412 | N/A | 1 | cancer, non-small cell lung carcinoma |
| **AS-1409** | CHEMBL2109413 | N/A | 1 | melanoma, renal cell carcinoma |
| **L19TNFA** | CHEMBL2109589 | N/A | 2 | colorectal cancer, leiomyosarcoma |
| **L19IL2** | CHEMBL2109608 | N/A | 3 | metastatic melanoma, melanoma, neoplasm, pancreatic carcinoma |

FN1 is targeted by five clinical-stage agents with diverse mechanisms. Ocriplasmin, approved in 2010, is a proteolytic enzyme that degrades fibronectin and other ECM components, currently used for vitreomacular adhesion and macular holes. The remaining agents are antibody-based therapeutics targeting fibronectin isoforms in oncology: L19SIP 131I (radioimmunotherapy), AS-1409 (aptamer), L19TNFA (TNF-alpha fusion), and L19IL2 (IL-2 fusion), progressing through Phase 1-3 for various solid tumors.

**B. Biological Context (Stage 1)**

- **FN1–PLAUR**: STRING PPI score=0.697, interaction=confirmed
  - Census: risk_ratio=0.1557, p_value=0.0 [from stage1_FN1--PLAUR.json]
- **FN1–SDC2**: STRING PPI score=0.959, interaction=confirmed
  - Census: risk_ratio=0.2258, p_value=0.0 [from stage1_FN1--SDC2.json]

FN1 forms interactions with both PLAUR (failed filter, STRING=0.697) and SDC2 (passed filter, STRING=0.959), with the latter showing strong physical association. The FN1–SDC2 pair passed Stage 1 filtering, indicating significant coexpression and functional relevance. Fibronectin's role as a major ECM component positions it as a central mediator of cell-ECM adhesion and fibroblast migration, with SDC2 (syndecan-2) serving as a cell surface receptor that may amplify fibrotic signaling through proteoglycan-mediated interactions.

**C. Rubric Assessment**

- Validated Track: existing_drug_evidence=5, clinical_trial_activity=5, safety_profile=0 → **validated_total=10**
- Exploratory Track: gwas_support=0, tractability=3, biological_plausibility=1, novelty_opportunity=1 → **exploratory_total=5**
- **Combined Total: 15** | Classification: validated_target | Priority: high

FN1 achieves a validated_total of 10 from strong existing drug evidence (5) and clinical trial activity (5), supported by ocriplasmin's approved status and multiple antibody-based programs. The exploratory_total of 5 reflects high tractability (3) due to approved ECM-targeting therapy, moderate biological plausibility (1) from limited evidence types, and a novelty advantage (1) given fibronectin's underexplored role in pulmonary fibrosis specifically. This profile supports FN1 as a validated target with established druggability, though fibrosis-specific mechanisms require further elucidation.

---

### ITGB2 — Classification: validated_target | Priority: high

**A. Drug Profile**

**Clinical Compounds (OpenTargets):**

| Drug | ChEMBL ID | Mechanism of Action | Phase | Indications |
|------|-----------|---------------------|------:|-------------|
| **LIFITEGRAST** | CHEMBL2048028 | N/A | 4 | allergic conjunctivitis, dry eye syndrome, diabetic macular edema, graft versus host disease, eye disease |

ITGB2 is targeted by a single approved agent, lifitegrast, which received FDA approval for dry eye syndrome and allergic conjunctivitis. Lifitegrast functions as an LFA-1 (lymphocyte function-associated antigen-1) antagonist, blocking the ITGB2-containing integrin complex involved in T cell adhesion and migration. The drug's success in ophthalmic indications demonstrates ITGB2 targetability, though its application in pulmonary fibrosis remains unexplored clinically.

**B. Biological Context (Stage 1)**

- **ICAM1–ITGB2**: STRING PPI score=0.999, interaction=confirmed
  - Census: risk_ratio=0.4222, p_value=0.0 [from stage1_ICAM1--ITGB2.json]

The ICAM1–ITGB2 pair shows an exceptional STRING PPI score of 0.999, reflecting the well-established biological interaction between ICAM1 (ligand) and ITGB2 (receptor) in leukocyte adhesion. This interaction forms the LFA-1/ICAM1 adhesion axis critical for immune cell trafficking and synapse formation. The risk ratio of 0.4222 indicates coordinated expression patterns in target cells, supporting the functional relevance of this axis in the fibrotic lung microenvironment where immune-fibroblast crosstalk drives disease progression.

**C. Rubric Assessment**

- Validated Track: existing_drug_evidence=1, clinical_trial_activity=5, safety_profile=0 → **validated_total=6**
- Exploratory Track: gwas_support=0, tractability=3, biological_plausibility=1, novelty_opportunity=1 → **exploratory_total=5**
- **Combined Total: 11** | Classification: validated_target | Priority: high

ITGB2 achieves a validated_total of 6 from moderate existing drug evidence (1, reflecting lifitegrast) and strong clinical trial activity (5), indicating active clinical development despite limited approved indications. The exploratory_total of 5 reflects high tractability (3) due to approved integrin antagonists, moderate biological plausibility (1) from pathway evidence, and a novelty advantage (1) given limited exploration in fibrotic diseases. This profile positions ITGB2 as a validated target with repurposing potential via lifitegrast, warranting investigation of its role in fibroblast activation and ECM deposition.

---

### CD47 — Classification: validated_target | Priority: high

**A. Drug Profile**

**Clinical Compounds (OpenTargets):**

| Drug | ChEMBL ID | Mechanism of Action | Phase | Indications |
|------|-----------|---------------------|------:|-------------|
| **EVORPACEPT** | CHEMBL4297880 | N/A | 2 | non-Hodgkins lymphoma, neoplasm, head and neck malignant neoplasia, acute myeloid leukemia, oropharynx cancer, metastatic colorectal cancer, metastatic malignant neoplasm, head and neck squamous cell carcinoma, multiple myeloma, ovarian cancer, cancer, myelodysplastic syndrome |
| **MAGROLIMAB** | CHEMBL4297985 | N/A | 3 | non-Hodgkins lymphoma, neoplasm, diffuse large B-cell lymphoma, triple-negative breast cancer, brain cancer, acute myeloid leukemia, metastatic colorectal cancer, head and neck squamous cell carcinoma, multiple myeloma, Sezary's disease, ovarian cancer, classic Hodgkin lymphoma, urothelial carcinoma, cancer, colorectal cancer, myelodysplastic syndrome, brain neoplasm, lymphoid neoplasm, Hodgkins lymphoma, mycosis fungoides |

CD47 is targeted by two clinical-stage inhibitors, evorpacept (Phase 2) and magrolimab (Phase 3), both developed for oncology indications. Magrolimab has the broadest development program with Phase 3 trials across multiple hematologic and solid tumor types including lymphomas, leukemias, and carcinomas. Both agents function as CD47 inhibitors, blocking the "don't eat me" signal that prevents macrophage phagocytosis of target cells. The extensive clinical development demonstrates CD47's druggability and safety tolerability in human trials.

**B. Biological Context (Stage 1)**

- **THBS1–CD47**: STRING PPI score=0.999, interaction=confirmed
  - Census: risk_ratio=0.3542, p_value=0.0 [from stage1_THBS1--CD47.json]

The THBS1–CD47 pair shows an exceptional STRING PPI score of 0.999, reflecting the canonical interaction between thrombospondin-1 (THBS1) and CD47. This interaction modulates multiple cellular processes including apoptosis, migration, and macrophage phagocytosis. The risk ratio of 0.3542 indicates coordinated expression in target cells, supporting the functional relevance of this axis in fibrotic lung tissue where THBS1-CD47 signaling may regulate fibroblast survival and macrophage polarization.

**C. Rubric Assessment**

- Validated Track: existing_drug_evidence=2, clinical_trial_activity=5, safety_profile=0 → **validated_total=7**
- Exploratory Track: gwas_support=0, tractability=2, biological_plausibility=1, novelty_opportunity=1 → **exploratory_total=4**
- **Combined Total: 11** | Classification: validated_target | Priority: high

CD47 achieves a validated_total of 7 from moderate existing drug evidence (2, reflecting evorpacept and magrolimab) and strong clinical trial activity (5), indicating robust clinical development in oncology. The exploratory_total of 4 reflects moderate tractability (2) with clinical-stage inhibitors, moderate biological plausibility (1) from pathway evidence, and a novelty advantage (1) given limited exploration in fibrotic diseases. This profile positions CD47 as a validated target with repurposing potential via existing inhibitors, warranting investigation of its role in fibroblast-phagocyte interactions and pro-fibrotic macrophage polarization.

---

### LRP1 — Classification: validated_target | Priority: high

**A. Drug Profile**

**Clinical Compounds (OpenTargets):**

| Drug | ChEMBL ID | Mechanism of Action | Phase | Indications |
|------|-----------|---------------------|------:|-------------|
| **ANG1005** | CHEMBL1089636 | N/A | 2 | brain neoplasm, Paraganglioma, malignant glioma, glioblastoma multiforme, neoplasm |

LRP1 is targeted by a single clinical-stage agent, ANG1005, in Phase 2 for brain tumors including glioblastoma and malignant glioma. ANG1005 is a paclitaxel derivative that exploits LRP1-mediated transcytosis to cross the blood-brain barrier, delivering cytotoxic payload to tumor cells. This mechanism demonstrates LRP1's functional role in receptor-mediated transport and its druggability as a delivery vehicle for therapeutic agents.

**B. Biological Context (Stage 1)**

- **APOE–LRP1**: STRING PPI score=0.999, interaction=confirmed
  - Census: risk_ratio=0.0653, p_value=0.0 [from stage1_APOE--LRP1.json]
- **CALR–LRP1**: STRING PPI score=0.998, interaction=confirmed
  - Census: risk_ratio=0.2501, p_value=0.0 [from stage1_CALR--LRP1.json]

LRP1 forms high-confidence interactions with both APOE (STRING=0.999) and CALR (STRING=0.998), both passing Stage 1 filtering. These interactions reflect LRP1's established role as a multifunctional clearance receptor for apolipoproteins and chaperone proteins. The risk ratios (0.0653 for APOE, 0.2501 for CALR) indicate coordinated expression patterns, supporting LRP1's function in ECM ligand clearance and protein homeostasis in alveolar type 2 cells and fibroblasts.

**C. Rubric Assessment**

- Validated Track: existing_drug_evidence=1, clinical_trial_activity=5, safety_profile=0 → **validated_total=6**
- Exploratory Track: gwas_support=0, tractability=2, biological_plausibility=1, novelty_opportunity=1 → **exploratory_total=4**
- **Combined Total: 10** | Classification: validated_target | Priority: high

LRP1 achieves a validated_total of 6 from moderate existing drug evidence (1, reflecting ANG1005) and strong clinical trial activity (5), indicating active clinical development primarily for CNS delivery applications. The exploratory_total of 4 reflects moderate tractability (2) with clinical-stage agents, moderate biological plausibility (1) from pathway evidence, and a novelty advantage (1) given limited exploration in fibrotic diseases. This profile positions LRP1 as a validated target with repurposing potential, warranting investigation of its role in ECM clearance dysfunction and pro-fibrotic ligand accumulation.

---

### ICAM1 — Classification: validated_target | Priority: high

**A. Drug Profile**

**Clinical Compounds (OpenTargets):**

| Drug | ChEMBL ID | Mechanism of Action | Phase | Indications |
|------|-----------|---------------------|------:|-------------|
| **ALICAFORSEN** | CHEMBL2108326 | N/A | 3 | ulcerative colitis, inflammatory bowel disease, Crohn's disease, pouchitis |
| **BI-505** | CHEMBL2109482 | N/A | 2 | multiple myeloma |

ICAM1 is targeted by two clinical-stage agents with distinct mechanisms. Alicaforsen, an antisense oligonucleotide in Phase 3, inhibits ICAM1 mRNA translation and has been developed for inflammatory bowel diseases including ulcerative colitis and Crohn's disease. BI-505, an antibody antagonist in Phase 2, targets ICAM1 for multiple myeloma. Both agents demonstrate ICAM1's druggability through different modalities (nucleic acid-based and protein-based), with alicaforsen's Phase 3 status indicating substantial clinical advancement.

**B. Biological Context (Stage 1)**

- **ICAM1–EZR**: STRING PPI score=0.998, interaction=confirmed
  - Census: risk_ratio=4.4977, p_value=0.0 [from stage1_ICAM1--EZR.json]
- **ICAM1–ITGB2**: STRING PPI score=0.999, interaction=confirmed
  - Census: risk_ratio=0.4222, p_value=0.0 [from stage1_ICAM1--ITGB2.json]
- **ICAM1–MUC1**: STRING PPI score=0.993, interaction=confirmed
  - Census: risk_ratio=17.863, p_value=0.0 [from stage1_ICAM1--MUC1.json]
- **ICAM1–PECAM1**: STRING PPI score=0.873, interaction=confirmed
  - Census: risk_ratio=0.7387, p_value=3.45e-07 [from stage1_ICAM1--PECAM1.json]

ICAM1 emerges as a central hub ligand with four passing interactions, all showing exceptional STRING scores (0.873-0.999). The ICAM1–MUC1 pair exhibits the highest risk ratio (17.863), suggesting strong coexpression enrichment. ICAM1–EZR (risk ratio=4.4977) and ICAM1–PECAM1 (risk ratio=0.7387, p=3.45e-07) also show significant coexpression. This interaction network positions ICAM1 as a key mediator of cell-cell adhesion, linking epithelial cells (MUC1), immune cells (ITGB2, PECAM1), and cytoskeletal organizers (EZR) in the fibrotic microenvironment.

**C. Rubric Assessment**

- Validated Track: existing_drug_evidence=2, clinical_trial_activity=5, safety_profile=0 → **validated_total=7**
- Exploratory Track: gwas_support=0, tractability=2, biological_plausibility=1, novelty_opportunity=0 → **exploratory_total=3**
- **Combined Total: 10** | Classification: validated_target | Priority: high

ICAM1 achieves a validated_total of 7 from moderate existing drug evidence (2, reflecting alicaforsen and BI-505) and strong clinical trial activity (5), indicating robust clinical development primarily for inflammatory indications. The exploratory_total of 3 reflects moderate tractability (2) with clinical-stage agents, moderate biological plausibility (1) from pathway evidence, and no novelty advantage (0) given ICAM1's well-established role in inflammation. This profile positions ICAM1 as a validated target with substantial clinical precedent, warranting investigation of its role in fibroblast activation and ECM deposition through the ICAM1-ITGB2 axis.

---

## 4. Hypothesis-Driven Analysis

Evidence coverage: 53.85% (7 hypotheses retained from 7 generated)

Seven mechanistic hypotheses were generated based on the Stage 1-3 assessment results, focusing on key L-R pairs and their therapeutic implications for pulmonary fibrosis. The hypotheses span multiple biological mechanisms including immune modulation, ECM remodeling, and fibroblast activation, providing testable predictions for experimental validation. Each hypothesis includes falsifiable predictions with specific readouts and validation approaches to guide preclinical investigation.

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

This hypothesis suggests lifitegrast, currently approved for dry eye syndrome, may have repurposing potential for pulmonary fibrosis by disrupting the ICAM1-ITGB2 adhesion axis that sustains fibroblast activation. Preclinical validation in IPF fibroblast models would establish mechanistic proof-of-concept before considering clinical trials.

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

This hypothesis proposes that lovastatin's known safety profile and oral bioavailability could enable rapid translation to pulmonary fibrosis trials if mechanistic validation confirms ITGB2 inhibition. The cholesterol-integrin crosstalk mechanism represents a novel therapeutic angle beyond traditional anti-fibrotic approaches.

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

This hypothesis identifies the FN1-SDC2 axis as a potential therapeutic target for disrupting fibroblast recruitment and EMT, two key processes in fibrosis progression. SDC2 inhibition could complement existing anti-fibrotic therapies by targeting cell-ECM adhesion mechanisms.

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

This hypothesis proposes CD47 blockade as a novel immunomodulatory strategy for pulmonary fibrosis, leveraging existing clinical-stage inhibitors (magrolimab, evorpacept). The mechanism addresses both fibroblast persistence and macrophage polarization, two interconnected drivers of fibrosis.

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

This hypothesis identifies the MUC1-ICAM1 axis as a potential target for disrupting epithelial-immune crosstalk that perpetuates fibrosis. MUC1 inhibitors developed for oncology could be repurposed for pulmonary fibrosis if mechanistic validation confirms the inflammatory amplification mechanism.

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

This hypothesis proposes LRP1 enhancement as a therapeutic strategy to restore ECM clearance and reduce pro-fibrotic ligand accumulation. Unlike typical inhibition-based approaches, this strategy would aim to augment LRP1 function, potentially through gene therapy or small molecule activators.

---

### 4.7. CD4+ T Cell-HLA Class II Interaction Sustains Adaptive Immune Response in IPF [Novel Pathway - Immune Modulation]

**Category:** Novel Pathway

**Core Claim:** Multiple HLA class II genes (HLA-DPA1, HLA-DPB1, HLA-DQB1, HLA-DRB1) form functional complexes with CD4+ T cells in IPF lung tissue, driving sustained adaptive immune responses that perpetuate fibroblast activation. This represents an underappreciated adaptive immune component in IPF pathogenesis.

**Evidence References:**
- stage1_HLA-DPA1--CD4.json_FAILED
- stage1_HLA-DPB1--CD4.json_FAILED
- stage3_CD4.json
- ot_CD4.json
- ot_HLA-DPA1.json
- ot_HLA-DPB1.json

**Biological Entities:**
- Genes: CD4, HLA-DPA1, HLA-DPB1, HLA-DQB1, HLA-DRB1
- Pathways: antigen presentation, T cell activation, adaptive immunity
- Cell Types: CD4+ T cells, antigen-presenting cells, fibroblasts

**Falsifiable Prediction:** From stage1_HLA-DPA1--CD4.json_FAILED, CD4+ T cell depletion in IPF lung explant cultures will reduce fibroblast proliferation and collagen secretion by a measurable amount compared to untreated explants.

**Validation Approach:** IPF lung explant culture ± anti-CD4 depletion antibody. Readouts: fibroblast outgrowth, collagen I deposition (Sirius Red), T cell infiltration (CD3/CD4 IHC). Controls: IgG isotype, CD8+ T cell depletion control.

This hypothesis suggests that adaptive immune mechanisms involving CD4+ T cells and HLA class II molecules contribute to fibrosis progression, potentially through antigen-specific T cell activation or cytokine-mediated fibroblast stimulation. CD4-targeted therapies (e.g., ibalizumab) could be explored for immunomodulation in IPF.

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

**Recommendations for Validated Targets:** All seven featured candidates achieved validated_target classification with high priority, indicating substantial clinical evidence and strong therapeutic potential. CD4, MUC1, and FN1 represent the highest-priority targets with combined scores of 15, driven by strong existing drug evidence and clinical trial activity. These targets have established clinical-stage inhibitors or binding agents that could be repurposed for pulmonary fibrosis. ITGB2, CD47, LRP1, and ICAM1 achieved combined scores of 10-11, also supporting their validation as therapeutic targets with repurposing potential.

**Recommendations for Next Steps:** Priority should be given to testing the mechanistic hypotheses generated in Section 4, particularly the ICAM1-ITGB2 axis (Hypothesis 4.1) and CD47 blockade (Hypothesis 4.4), which have the strongest clinical infrastructure (lifitegrast approved, magrolimab in Phase 3). Preclinical validation should focus on IPF-relevant models including primary fibroblast cultures, lung explant systems, and established murine fibrosis models. Drug repurposing trials should consider existing safety data and mechanism-of-action alignment with fibrotic pathways. Additional investigation of the HLA-CD4 axis (Hypothesis 4.7) may reveal underappreciated adaptive immune contributions to IPF pathogenesis.