# Hypothesis Thematic Categories

Four mandatory categories ensure comprehensive coverage of drug target assessment dimensions. Each hypothesis report must include at least one hypothesis per category.

---

## Category 1: Mechanism of Action (MoA)

**Focus**: How a specific target mechanistically drives the disease process.

**Required elements**:
- Name the specific gene and its molecular function (from OT `functionDescriptions`)
- Reference pathway context (from Stage 1 KEGG/Reactome data)
- Cite Census cross-validation evidence (coexpression risk ratio, resolved cell type)
- Specify disease-relevant cell type(s) and proposed cellular process
- Falsifiable prediction linking mechanism to measurable outcome

**Primary evidence sources**: passed/eligible Stage 1 JSONs (pathways, PPI, Census), OT function descriptions, rubric biological_plausibility score

**Example (IPF)**:
> **"ICAM1-MUC1 Interaction Drives Epithelial Barrier Dysfunction in IPF Alveolar Type 2 Cells via NF-kB-Mediated Mucin Dysregulation"**
>
> ICAM1 and MUC1 show strong physical interaction (STRING PPI score 0.993) with exceptionally high disease-specific coexpression in pulmonary alveolar type 2 cells (Census risk ratio 17.86, p < 1e-323). ICAM1 signals through the NF-kB pathway (KEGG hsa04064), which may transcriptionally dysregulate MUC1 expression, compromising the epithelial glycocalyx barrier that protects against fibrotic remodeling.
>
> *Prediction*: siRNA knockdown of ICAM1 in primary human AT2 cells will reduce MUC1 shedding by >40% and restore transepithelial resistance in air-liquid interface culture.

**Typical scoring profile**: Evidence_Coverage 0.6-0.8, Specificity 0.5-0.7, Novelty 0.3-0.5, Actionability 0.3-0.5

---

## Category 2: Therapeutic Strategy

**Focus**: How to intervene against a target, integrating tractability, safety, and clinical precedent.

**Required elements**:
- Name target and proposed modality (SM/AB/PR/OC from OT tractability)
- Reference existing drugs if available (from Stage 3 ChEMBL)
- Address safety concerns (OT safety liabilities, rubric safety_profile score)
- Cite max clinical phase evidence
- Falsifiable prediction with therapeutic endpoint

**Primary evidence sources**: Stage 3 JSONs (ChEMBL drugs), OT tractability, rubric safety_profile, known_drugs.json

**Example (IPF)**:
> **"TGF-beta Receptor I Kinase Inhibition with Vactosertib as IPF-Specific Anti-Fibrotic Strategy"**
>
> TGFB1 has the highest exploratory score (10) with strong GWAS support (3) and biological plausibility (3), but carries safety concerns (safety_profile: -2). Vactosertib (CHEMBL3260567), a selective TGF-beta receptor type I inhibitor currently in Phase II for solid tumors, offers a more targeted approach than pan-TGF-beta blockade. Its selectivity for ALK5 over ALK4/ALK7 may reduce the cardiovascular and immunosuppressive toxicities that limited earlier broad-spectrum TGF-beta inhibitors.
>
> *Prediction*: Vactosertib 200mg daily for 24 weeks will reduce FVC decline rate by >30% compared to placebo in IPF patients with elevated serum TGFB1 (>30 pg/mL), with acceptable hepatic safety (ALT elevation <3x ULN in >90% of patients).

**Typical scoring profile**: Evidence_Coverage 0.6-0.8, Specificity 0.5-0.8, Novelty 0.2-0.4, Actionability 0.7-1.0

---

## Category 3: Cross-Target Interaction

**Focus**: Multi-target synergies or pathway convergence between 2+ assessed genes.

**Required elements**:
- Identify 2+ genes sharing pathways or appearing in the same L-R pair
- Reference STRING PPI evidence for the interaction
- Cite converging pathways (KEGG/Reactome shared between ligand and receptor)
- Propose synergistic or epistatic mechanism
- Falsifiable prediction comparing dual vs. single-target intervention

**Primary evidence sources**: passed/eligible Stage 1 JSONs (shared pathways between pairs), STRING PPI, rubric scores for multiple genes, stage2_evidence.json (pathway overlap)

**Example (IPF)**:
> **"ICAM1-ITGB2 and ICAM1-PECAM1 Axes Converge on Leukocyte Transendothelial Migration as a Dual-Targetable Pro-Fibrotic Gateway"**
>
> ICAM1 appears in 4 distinct L-R pairs (ICAM1-MUC1, ICAM1-EZR, ICAM1-ITGB2, ICAM1-PECAM1), suggesting it is a hub gene in IPF pathogenesis. Both ITGB2 and PECAM1 participate in the "Leukocyte transendothelial migration" KEGG pathway. Combined blockade of ICAM1-ITGB2 (immune cell adhesion) and ICAM1-PECAM1 (endothelial transmigration) may more effectively reduce inflammatory cell infiltration than targeting either axis alone.
>
> *Prediction*: Combined anti-ICAM1 + anti-PECAM1 treatment will reduce BAL inflammatory cell count by >60% in bleomycin-challenged mice, versus <30% reduction with either antibody alone.

**Typical scoring profile**: Evidence_Coverage 0.8-1.0, Specificity 0.5-0.7, Novelty 0.5-0.7, Actionability 0.3-0.7

---

## Category 4: Novel Pathway

**Focus**: Unexpected biological connections revealed by the evidence data that are not established in the disease literature.

**Required elements**:
- Must involve at least one NOVEL-tier gene OR an unexpected pathway connection
- Reference specific evidence that makes this non-obvious (Census showing unexpected coexpression, novel pathway association)
- Explain why this is novel relative to known disease biology
- Higher Novelty score weight for this category (target >= 0.5)
- Falsifiable prediction with experimental approach

**Primary evidence sources**: Census cross-validation (unexpected cell types, high risk ratios), OT pathway data for NOVEL genes, cross-referencing pathway annotations across pairs

**Example (IPF)**:
> **"APOE-Mediated Lipid Transport to TREM2+ Macrophages Creates a Metabolic Checkpoint Governing Fibrosis Resolution"**
>
> APOE and TREM2 are both classified as NOVEL candidates. TREM2 is primarily studied in neurodegeneration (Alzheimer's disease — Phase II antibodies exist), but Census data reveals significant APOE-TREM2 coexpression in alveolar macrophages in IPF tissue. APOE delivers lipids to TREM2, which functions as a lipid sensor. In IPF, this axis may control whether alveolar macrophages adopt a pro-fibrotic (lipid-laden foam cell) or pro-resolution (phagocytic) phenotype — a metabolic checkpoint not previously described in pulmonary fibrosis.
>
> *Prediction*: Conditional knockout of TREM2 in alveolar macrophages will shift the macrophage lipidome toward pro-fibrotic foam cell markers (increased ceramide:sphingomyelin ratio >2-fold) and worsen bleomycin-induced fibrosis (Ashcroft score increase >2 points).

**Typical scoring profile**: Evidence_Coverage 0.4-0.6, Specificity 0.5-0.7, Novelty 0.7-1.0, Actionability 0.3-0.5

---

## Multi-Category Assignment

Some hypotheses may span categories. Assign to the **primary** category based on emphasis:

| If the hypothesis primarily... | Assign to |
|-------------------------------|-----------|
| Explains a molecular mechanism | MoA |
| Proposes a treatment approach | Therapeutic Strategy |
| Links multiple targets | Cross-Target Interaction |
| Reveals unexpected biology | Novel Pathway |

If a hypothesis equally spans two categories, assign it to the category with fewer hypotheses to ensure balance.

---

## Category Balance Requirements

- **Minimum**: 1 hypothesis per category (4 total minimum)
- **Recommended**: 1-2 per category (4-6 total before scoring)
- **After scoring**: At least 3 categories should be represented in the final 3-5 hypotheses
- If scoring eliminates an entire category, generate one additional hypothesis for that category and re-score
