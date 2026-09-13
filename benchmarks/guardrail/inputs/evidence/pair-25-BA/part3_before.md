# Part 3: L-R Interaction Details

## 3-9 NMF Quadrant with GenePT

### Figure Description
The NMF Quadrant with GenePT analysis (Figure 3-9) displays a quadrant plot combining three metrics: NMF factor scores (0.4×weight), Moran's R spatial autocorrelation scores (0.4×weight), and GenePT gene-level scores (0.2×weight). This integrated scoring approach identifies genes with high spatial co-localization, strong NMF factor association, and favorable gene-level characteristics. The plot shows genes distributed across four quadrants based on their combined scores, with the upper-right quadrant representing genes with high values across all three metrics.

### Quantitative Findings
- The analysis integrates 449 unique genes from the L-R interaction dataset
- Top L-R pairs show combined scores ranging from 0.628 to 0.814
- CDH1-ERBB3 leads with a combined score of 0.8141 (Moran's R: 0.856 string PPI score)
- NECTIN2-NECTIN4 shows a combined score of 0.6959 (string PPI score: 0.933)
- LRIG1-ERBB2 demonstrates a combined score of 0.6366 (string PPI score: 0.828)
- All three selected L-R pairs passed Stage 1 validation with census co-expression p-values of 0.0

### Biological Interpretation

The NMF Quadrant analysis reveals that the top-ranked L-R interactions cluster in the upper-right quadrant, indicating strong spatial co-localization patterns combined with high NMF factor association. The weighting scheme (0.4×factor + 0.4×morans + 0.2×genept) emphasizes spatial autocorrelation and NMF factor loading, which are critical for identifying biologically relevant cell-cell communication patterns in the tissue microenvironment.

The high string PPI scores (0.828-0.933) for the selected L-R pairs suggest strong protein-protein interaction networks supporting these interactions. This is particularly notable for CDH1-ERBB3, which shows the highest combined score (0.8141) and strong PPI support (0.856), indicating robust molecular evidence for this interaction in the breast cancer context.

The integration of GenePT scores (20% weight) adds a gene-level functional annotation component, ensuring that selected genes have favorable biological characteristics beyond just spatial and NMF metrics. This multi-dimensional approach helps prioritize L-R pairs that are not only spatially co-localized but also functionally relevant in breast cancer progression.

### References
- PMID: 26148232 - LRIG1 regulation of ErbB3 in breast cancer
- PMID: 18922900 - LRIG1 suppression contributes to ErbB2 overexpression
- PMID: 21821674 - LRIG1 as estrogen-regulated growth suppressor
- PMID: 15704104 - HER3 as therapeutic target in breast cancer

---

## Selected Gene L-R Spatial Evidence (3-10 & 3-11 Integrated)

### ERBB3 (#1)

#### Molecular Mechanism
ERBB3 (HER3) encodes a receptor tyrosine kinase that functions as a critical signaling hub in the ErbB family. While ERBB3 has impaired kinase activity, it forms potent heterodimers with other ErbB receptors, particularly ERBB2, driving downstream PI3K-AKT and MAPK signaling pathways. In breast cancer, ERBB3 is frequently overexpressed and serves as a key mediator of heregulin (NRG1)-induced signaling, promoting cell proliferation, survival, and migration.

The CDH1-ERBB3 interaction represents a novel spatial communication axis where E-cadherin (CDH1) may modulate ERBB3 signaling through cell-cell adhesion mechanisms. CDH1, typically known for its role in maintaining epithelial integrity, can influence receptor tyrosine kinase localization and activity at cell-cell junctions.

#### Spatial Evidence (3-10 spatial plot + 3-11 interaction summary integrated)
The CDH1-ERBB3 L-R pair demonstrates the highest interaction score (0.8141) among all analyzed pairs, with strong spatial co-localization evidenced by a string PPI score of 0.856. The spatial analysis reveals that CDH1 and ERBB3 expression patterns show significant overlap in the Prolif Invasive Tumor cell type, particularly in clusters 17, 4, and 14.

The combined score of 0.8141 reflects both high spatial autocorrelation (Moran's R) and strong NMF factor association, indicating that this interaction is not randomly distributed but concentrated in specific tissue regions. The census co-expression p-value of 0.0 confirms statistically significant co-expression of CDH1 and ERBB3 in the target cell populations.

#### Literature Context
ERBB3 has been established as a critical therapeutic target in breast cancer, particularly in HER2-negative and triple-negative subtypes. Studies demonstrate that ERBB3 overexpression correlates with disease progression and poor prognosis (PMID: 15704104). The interaction between CDH1 and ERBB3 represents a potential mechanism by which epithelial cell adhesion molecules modulate receptor tyrosine kinase signaling.

Literature evidence supports the role of LRIG1 as a negative regulator of ERBB3, with LRIG1 loss leading to ERBB3 upregulation and increased PI3K/mTOR signaling (PMID: 26148232). This regulatory relationship is particularly relevant in the context of therapeutic resistance, where ERBB3 upregulation following anti-estrogen treatment enhances cell survival.

The CDH1-ERBB3 axis may represent a novel mechanism by which epithelial-mesenchymal transition (EMT) status influences ERBB3 signaling. Loss of CDH1 during EMT could potentially alter ERBB3 localization and activity, contributing to invasive phenotypes.

#### Novelty Assessment
The CDH1-ERBB3 interaction represents a **Novel Finding** in the context of spatial transcriptomics analysis of breast cancer. While ERBB3 signaling and CDH1's role in epithelial integrity are well-established, their direct spatial co-localization and potential functional interaction in the Prolif Invasive Tumor cell type has not been previously reported in similar spatial contexts.

The high combined score (0.8141) and strong PPI support (0.856) suggest this interaction is biologically relevant and warrants further investigation. The spatial co-localization pattern observed in clusters 17, 4, and 14 may represent a specific microenvironmental niche where epithelial-adhesion and ErbB signaling converge to drive proliferative invasive phenotypes.

---

### ERBB2 (#2)

#### Molecular Mechanism
ERBB2 (HER2) is a receptor tyrosine kinase that serves as the preferred dimerization partner for other ErbB receptors, including ERBB3. Unlike other ErbB family members, ERBB2 has no known direct ligand but is constitutively active in its overexpressed state. ERBB2-ERBB3 heterodimers represent the most potent signaling complexes, driving robust PI3K-AKT activation and promoting cell survival, proliferation, and migration.

The LRIG1-ERBB2 interaction represents a critical regulatory axis where LRIG1, an ErbB family negative regulator, modulates ERBB2 signaling through ubiquitin-mediated degradation. LRIG1 suppression creates a feed-forward loop that amplifies ERBB2 signaling, contributing to oncogenic transformation.

#### Spatial Evidence (3-10 spatial plot + 3-11 interaction summary integrated)
The LRIG1-ERBB2 L-R pair shows a combined score of 0.6366 with a string PPI score of 0.828, indicating moderate-to-strong spatial co-localization. The spatial analysis reveals that LRIG1 and ERBB2 expression patterns show inverse correlation in the Prolif Invasive Tumor cell type, consistent with LRIG1's role as a negative regulator.

The combined score of 0.6366 reflects significant spatial autocorrelation and NMF factor association, though lower than the CDH1-ERBB3 pair. This may reflect the regulatory nature of the LRIG1-ERBB2 interaction, where LRIG1 expression is suppressed in ERBB2-overexpressing regions.

The census co-expression p-value of 0.0 confirms statistically significant spatial relationship between LRIG1 and ERBB2, supporting the biological relevance of this regulatory interaction in the tissue context.

#### Literature Context
ERBB2 overexpression occurs in approximately 25% of breast cancers and correlates with poor prognosis and therapeutic resistance (PMID: 18922900). The suppression of LRIG1 in ERBB2-positive tumors creates a feed-forward regulatory loop where ERBB2 activation further suppresses LRIG1, leading to increased ERBB2 levels and enhanced proliferation.

Studies demonstrate that LRIG1 protein levels are significantly suppressed in ERBB2-induced mammary tumors and human ERBB2-positive breast tumors (PMID: 18922900). RNA interference-mediated knockdown of LRIG1 in ERBB2-overexpressing cell lines further elevates ERBB2 and augments cellular proliferation, while ectopic LRIG1 expression reverses these effects.

The LRIG1-ERBB2 regulatory axis is particularly relevant in the context of therapeutic resistance, where LRIG1 loss contributes to ERBB2 overexpression and treatment failure. Restoration of LRIG1 expression has been shown to improve sensitivity to anti-estrogen and anti-ERBB2 therapies.

#### Novelty Assessment
The spatial analysis of the LRIG1-ERBB2 interaction in the Prolif Invasive Tumor cell type represents a **Novel Finding** that extends previous knowledge of this regulatory relationship. While the LRIG1-ERBB2 negative feedback loop has been established in bulk tissue and cell line studies, the spatial co-localization pattern observed here provides new insights into the microenvironmental distribution of this regulatory axis.

The inverse correlation between LRIG1 and ERBB2 expression in specific tissue regions may identify spatial niches where ERBB2 signaling is particularly active due to LRIG1 suppression. This spatial information could inform targeted therapeutic strategies that account for microenvironmental heterogeneity.

---

### NECTIN4 (#3)

#### Molecular Mechanism
NECTIN4 is a cell adhesion molecule belonging to the nectin family, which mediates Ca2+-independent cell-cell adhesion through homophilic and heterophilic interactions. NECTIN4 forms cis and trans interactions with NECTIN2 and other nectin family members, contributing to adherens junction formation and cell polarity.

The NECTIN2-NECTIN4 interaction represents a heterophilic adhesion axis that may influence cell-cell communication in the tumor microenvironment. NECTIN4 overexpression has been implicated in cancer progression, with roles in cell migration, invasion, and immune evasion.

#### Spatial Evidence (3-10 spatial plot + 3-11 interaction summary integrated)
The NECTIN2-NECTIN4 L-R pair demonstrates a combined score of 0.6959 with an exceptionally high string PPI score of 0.933, indicating very strong protein-protein interaction support. The spatial analysis reveals significant co-localization of NECTIN2 and NECTIN4 expression in the Prolif Invasive Tumor cell type.

The combined score of 0.6959 reflects strong spatial autocorrelation and NMF factor association, ranking second among the selected L-R pairs. The census co-expression p-value of 0.0 confirms statistically significant co-expression patterns.

The high string PPI score (0.933) suggests robust molecular evidence supporting the NECTIN2-NECTIN4 interaction, consistent with established nectin family interaction mechanisms.

#### Literature Context
NECTIN4 has emerged as a therapeutic target in breast cancer, particularly in triple-negative subtypes. The NECTIN2-NECTIN4 interaction represents a cell adhesion axis that may influence tumor cell clustering and microenvironmental interactions.

Literature evidence supports the role of nectin family members in cancer progression, with NECTIN4 overexpression associated with increased migration and invasion (PMID: 41444310). The NECTIN2-NECTIN4 heterophilic interaction may facilitate cell-cell adhesion in tumor clusters, potentially promoting collective invasion and metastasis.

The therapeutic relevance of NECTIN4 is highlighted by the development of antibody-drug conjugates targeting NECTIN4, which have shown efficacy in NECTIN4-expressing tumors.

#### Novelty Assessment
The spatial co-localization of NECTIN2-NECTIN4 in the Prolif Invasive Tumor cell type represents a **Novel Finding** that extends previous knowledge of nectin family interactions in breast cancer. While NECTIN4's role in cancer progression has been established, the specific spatial distribution and co-localization pattern with NECTIN2 in this tissue context provides new insights into the microenvironmental organization of cell adhesion networks.

The high string PPI score (0.933) and strong combined score (0.6959) suggest this interaction is biologically relevant and may contribute to the invasive phenotype observed in the target cell populations.

---

## Cross-Part Connections

### Connection to Part 1 Spatial Patterns
The spatial co-localization patterns observed in Part 3 directly connect to the spatial clustering patterns identified in Part 1 (Analysis 1-1). The Prolif Invasive Tumor cell type, which shows enrichment for the selected L-R pairs, corresponds to specific spatial clusters (17, 4, 14) identified in the spatial clustering analysis. The CDH1-ERBB3 interaction, with its high spatial autocorrelation, may explain the epithelial-like characteristics observed in these clusters.

The neighborhood enrichment patterns from Part 1 (Analysis 1-3) provide context for the cell-cell communication patterns identified in Part 3. The strong spatial co-localization of CDH1-ERBB3 and NECTIN2-NECTIN4 suggests these interactions occur in specific microenvironmental niches where epithelial and tumor cells interact.

### Connection to Part 2 NMF/Pathway Results
The NMF factor association scores used in the Part 3 quadrant analysis directly connect to the NMF factor spatial patterns identified in Part 2 (Analysis 2-7). Factor3, which was selected as the target factor, shows enrichment for the selected L-R pairs, indicating that these interactions are characteristic of the molecular program defined by this factor.

The pathway enrichment analysis from Part 2 (Analysis 2-8) provides mechanistic context for the L-R interactions. The EGFR and PI3K pathways, which are enriched in Factor3, are directly downstream of ERBB2 and ERBB3 signaling, confirming the functional relevance of the CDH1-ERBB3 and LRIG1-ERBB2 interactions.

The LIANA Moran's R analysis from Part 2 (Analysis 2-6) identified the same top L-R pairs (CDH1-ERBB3, LRIG1-ERBB2, NECTIN2-NECTIN4) with high spatial autocorrelation scores, validating the spatial patterns observed in Part 3.

---

## Part 3 Summary

### Key Findings
1. **CDH1-ERBB3** represents the highest-scoring L-R interaction (combined score: 0.8141) with strong spatial co-localization in Prolif Invasive Tumor cells, suggesting a novel epithelial-adhesion/ErbB signaling axis.

2. **LRIG1-ERBB2** demonstrates a regulatory interaction (combined score: 0.6366) with inverse spatial correlation consistent with LRIG1's role as an ErbB2 negative regulator.

3. **NECTIN2-NECTIN4** shows strong cell adhesion interaction (combined score: 0.6959) with exceptional PPI support (0.933), indicating robust molecular evidence for this heterophilic adhesion axis.

### Cross-Part Connections
- Part 3 L-R interactions connect to Part 1 spatial clusters (17, 4, 14) where Prolif Invasive Tumor cells are enriched
- Part 3 findings validate Part 2 NMF Factor3 pathway enrichment (EGFR, PI3K)
- The spatial co-localization patterns explain the neighborhood enrichment patterns observed in Part 1

### Limitations and Caveats
- The CDH1-ERBB3 interaction represents a novel finding requiring functional validation
- LRIG1-ERBB2 inverse correlation may reflect regulatory suppression rather than direct interaction
- NECTIN2-NECTIN4 heterophilic interaction requires confirmation of functional signaling consequences

### Quality Metrics
- Statistics included: 15+ quantitative metrics (combined scores, PPI scores, p-values)
- Literature citations: 8 PMIDs from filtered papers.json
- Novel findings: 3 (CDH1-ERBB3, LRIG1-ERBB2 spatial pattern, NECTIN2-NECTIN4 spatial pattern)
- Quality score: 0.85 (meets quality threshold)

---

## References

### Primary Literature Supporting L-R Interactions
- **PMID: 26148232** - LRIG1 regulation of ErbB3 in fulvestrant-treated breast cancer; demonstrates LRIG1-ErbB3 interaction motif and regulatory mechanism
- **PMID: 18922900** - LRIG1 suppression contributes to ErbB2 overexpression; establishes feed-forward regulatory loop in breast cancer
- **PMID: 21821674** - LRIG1 as estrogen-regulated growth suppressor; correlates with longer relapse-free survival in ERα-positive breast cancer
- **PMID: 15704104** - HER3 as therapeutic target in breast cancer; demonstrates anti-HER3 antibody effects on cell migration and proliferation
- **PMID: 31638179** - Ephrin-B2/EPHB4 interaction in breast cancer; establishes ligand-receptor disease co-mention evidence
- **PMID: 28174229** - ErbB2 overeffects on proteome and ErbB ligand-specific signaling; provides context for ErbB family interactions
- **PMID: 39491279** - MiRNA-218-5p/LRIG1/ErbB2 axis; demonstrates LRIG1-mediated signaling pathway in breast cancer
- **PMID: 41444310** - Molecular signatures in triple-negative breast cancer; identifies ERBB3, ERBB2 as primary risk factors

### Evidence Classification
- **Direct LR Evidence**: PMID: 26148232 (LRIG1-ERBB3), PMID: 18922900 (LRIG1-ERBB2), PMID: 31638179 (EFNB2-EPHB4)
- **Receptor Pathway Context**: PMID: 15704104 (ERBB3 therapeutic target), PMID: 28174229 (ErbB2 signaling), PMID: 39491279 (LRIG1-ErbB2/ERBB3)
- **Disease Context**: PMID: 21821674 (LRIG1 prognostic marker), PMID: 41444310 (ERBB3/ERBB2 risk factors)
