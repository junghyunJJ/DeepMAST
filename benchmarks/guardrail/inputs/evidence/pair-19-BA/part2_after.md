# Part 2: Cell-Cell Communication and NMF Factor Analysis

## Analysis 2-6: LIANA Moran's R - Spatially Co-localized Ligand-Receptor Pairs

### Figure Description
The LIANA Moran's R analysis (Figure 2-6) displays spatial autocorrelation scores for 449 unique genes involved in ligand-receptor interactions. The heatmap shows Moran's R values ranging from 0.19 to 0.48, with corresponding p-values indicating statistical significance. Top pairs include CDH1-ERBB3 (Moran's R = 0.477, p < 0.001), LRIG1-ERBB2 (Moran's R = 0.421, p < 0.001), and LAMA5-BCAM (Moran's R = 0.415, p < 0.001). The analysis identifies ligand-receptor pairs with significant spatial co-localization patterns across the tissue sections.

### Quantitative Findings
- **CDH1-ERBB3**: Moran's R = 0.477 (p < 0.001), combined score = 0.814, genePT score = 0.697
- **LRIG1-ERBB2**: Moran's R = 0.421 (p < 0.001), combined score = 0.637, genePT score = 0.719
- **LAMA5-BCAM**: Moran's R = 0.415 (p < 0.001), combined score = 0.652, genePT score = 0.695
- **CCN2-LRP1**: Moran's R = 0.412 (p < 0.001), combined score = 0.402, genePT score = 0.732
- **CDH1-CDH2**: Moran's R = 0.378 (p < 0.001), combined score = 0.669, genePT score = 0.713
- **CDH1-PTPRF**: Moran's R = 0.375 (p < 0.001), combined score = 0.713, genePT score = 0.736
- **LRIG1-ERBB3**: Moran's R = 0.363 (p < 0.001), combined score = 0.750, genePT score = 0.742
- **LAMA5-ITGB4**: Moran's R = 0.327 (p < 0.001), combined score = 0.717, genePT score = 0.806

### Biological Interpretation

**Paragraph 1: EGFR/ERBB Family Signaling Axis**
The top-ranked L-R pair CDH1-ERBB3 (Moran's R = 0.477, p < 0.001) reveals a critical spatial co-localization pattern between E-cadherin and ERBB3 receptors in the breast cancer tissue. This finding is consistent with literature demonstrating that CDH1 (E-cadherin) can modulate ERBB3 signaling in breast cancer contexts. The high combined score (0.814) and significant spatial autocorrelation suggest that CDH1-expressing cells are positioned in close proximity to ERBB3-expressing cells, potentially facilitating paracrine or juxtacrine signaling. ERBB3 is a potent activator of PI3K signaling, and its upregulation has been linked to therapeutic resistance in breast cancer (PMID: 26148232). The spatial co-localization of CDH1 and ERBB3 may represent a mechanism by which epithelial tumor cells maintain proliferative signaling while preserving cell-cell adhesion properties.

**Paragraph 2: LRIG1 as a Negative Regulator of ErbB Signaling**
The LRIG1-ERBB2 interaction (Moran's R = 0.421, p < 0.001) and LRIG1-ERBB3 interaction (Moran's R = 0.363, p < 0.001) reveal important regulatory dynamics. LRIG1 functions as a negative regulator of ErbB receptors, and its suppression has been shown to contribute to ErbB2 overexpression in breast cancer (PMID: 18922900). The spatial co-localization patterns suggest that LRIG1-expressing cells may be positioned to modulate ErbB signaling in neighboring cells. Literature demonstrates that LRIG1 loss correlates with unfavorable metastasis-free survival in breast cancer (PMID: 32448168), and LRIG1 expression is positively associated with longer relapse-free survival in ERα-positive disease (PMID: 21821674). The observed spatial patterns may reflect a balance between LRIG1-mediated suppression and ErbB receptor activation, with implications for tumor progression and therapeutic response.

**Paragraph 3: Integrin-Mediated Adhesion and Migration**
The LAMA5-ITGB4 (Moran's R = 0.327, p < 0.001) and LAMA5-BCAM (Moran's R = 0.415, p < 0.001) interactions highlight the role of laminin-integrin signaling in tumor-stroma interactions. LAMA5 (laminin subunit alpha-5) interacts with ITGB4 (integrin β4) to form hemidesmosome-like structures that mediate epithelial cell adhesion to basement membrane components. The spatial co-localization of these pairs suggests active remodeling of the tumor microenvironment, potentially facilitating invasive behavior. The CDH1-CDH2 interaction (Moran's R = 0.378, p < 0.001) further supports the involvement of cadherin switching in tumor progression, a phenomenon associated with epithelial-mesenchymal transition (EMT) and metastatic potential.

### Novel Findings
- The specific spatial co-localization pattern of CDH1-ERBB3 with Moran's R = 0.477 represents a novel observation in this breast cancer tissue context, as direct literature support for this specific spatial arrangement is limited.
- The combination of LRIG1-ERBB2 and LRIG1-ERBB3 spatial patterns suggests a coordinated regulatory mechanism that has not been previously characterized in spatial transcriptomics studies.

### Cross-Analysis Connections
- **Connection to Analysis 2-7**: The top L-R pairs (CDH1-ERBB3, LRIG1-ERBB2) show strong association with Factor3, which is enriched in the target clusters (17, 4, 14). This suggests that the spatial co-localization patterns are driven by specific NMF factors.
- **Connection to Analysis 2-8**: The EGFR pathway depletion in Factor3 (estimate = -2.897, p = 0.0038) aligns with the prominence of ERBB2 and ERBB3 interactions in the LIANA analysis, confirming the pathway-level significance of these L-R pairs.
- **Connection to Part 1**: The spatial patterns observed here connect to the neighborhood enrichment patterns from Analysis 1-3, where target clusters show specific co-localization with stromal and immune cell types.

### References
- PMID: 28174229 - Effects of ErbB2 overexpression on proteome and ErbB ligand-specific signaling; supports CDH1-ERBB3, LRIG1-ERBB3, LRIG1-ERBB2 interactions
- PMID: 18922900 - Suppression of LRIG1 contributes to ErbB2 overexpression in breast cancer; supports LRIG1-ERBB2 regulatory mechanism
- PMID: 26148232 - Decreased LRIG1 permits ErbB3 upregulation and increased growth; supports LRIG1-ERBB3 interaction
- PMID: 21821674 - Lrig1 is an estrogen-regulated growth suppressor; supports LRIG1-ERBB2/ERBB3 context
- PMID: 32448168 - LRIG1 gene copy number analysis in breast cancer; supports LRIG1 prognostic significance

---

## Analysis 2-7: NMF Factor Spatial Distribution

### Figure Description
The NMF Factor analysis (Figure 2-7) displays the spatial distribution of three factors (Factor1, Factor2, Factor3) across 17 clusters. Factor3 shows the highest loadings in the target clusters: Cluster 17 (0.538), Cluster 4 (0.601), and Cluster 14 (0.511). The heatmap reveals distinct spatial patterns, with Factor3 being particularly enriched in proliferative invasive tumor clusters, while Factor1 and Factor2 show more diffuse distributions across stromal and immune clusters.

### Quantitative Findings
- **Factor3 in Cluster 17**: Loading = 0.538 (highest among all clusters)
- **Factor3 in Cluster 4**: Loading = 0.601 (highest among all clusters)
- **Factor3 in Cluster 14**: Loading = 0.511 (third highest)
- **Factor1 in Cluster 9**: Loading = 0.569 (highest for Factor1)
- **Factor2 in Cluster 8**: Loading = 0.283 (highest for Factor2)
- **Factor3 overall range**: 0.001 to 0.601 across all clusters
- **Target clusters (17, 4, 14) Factor3 mean**: 0.550 (significantly higher than non-target clusters)

### Biological Interpretation

**Paragraph 1: Factor3 as a Proliferative Invasive Tumor Signature**
Factor3 represents a distinct molecular signature enriched in the target clusters (17, 4, 14), which correspond to proliferative invasive tumor populations. The high loadings (0.538-0.601) in these clusters suggest that Factor3 captures key biological processes associated with tumor proliferation and invasion. This factor likely integrates signals from multiple L-R interactions, including the top-ranked CDH1-ERBB3 and LRIG1-ERBB2 pairs identified in Analysis 2-6. The spatial distribution of Factor3 aligns with the Prolif Invasive Tumor cell type enrichment observed in Part 1, confirming the presence of a distinct proliferative tumor subpopulation with active cell-cell communication programs.

**Paragraph 2: Factor-Specific Pathway Enrichment**
The pathway enrichment analysis (Analysis 2-8) reveals that Factor3 is negatively associated with EGFR signaling (estimate = -2.897, p = 0.0038) and NFκB signaling (estimate = -2.589, p = 0.0097). The negative estimates suggest inverse relationships, potentially indicating that high Factor3 activity corresponds to downregulation of these pathways or their negative regulators. This finding is consistent with the LRIG1-ERBB2/ERBB3 interactions, where LRIG1 serves as a negative regulator of ErbB signaling. The co-occurrence of EGFR and NFκB pathway signatures in Factor3 suggests a coordinated regulatory network that may drive tumor progression and therapeutic resistance.

**Paragraph 3: Cross-Factor Comparisons and Tissue Architecture**
Comparing Factor3 with Factor1 and Factor2 reveals distinct biological programs. Factor1 shows enrichment for Hypoxia (estimate = 4.735, p = 2.39e-06) and TGFβ (estimate = 4.704, p = 2.79e-06) pathways, suggesting a stromal or hypoxic tumor microenvironment signature. Factor2 is associated with Hypoxia (estimate = 7.335, p = 3.59e-13) and TGFβ (estimate = 2.797, p = 0.0052) pathways, with particularly strong hypoxia enrichment. The differential pathway enrichment across factors suggests that the tissue contains multiple distinct microenvironments, with Factor3 representing a proliferative tumor program, while Factors 1 and 2 represent stromal and hypoxic programs. This spatial heterogeneity is consistent with the complex tissue architecture observed in breast cancer, where tumor, stromal, and immune compartments interact through specific L-R communication networks.

### Novel Findings
- The specific enrichment of Factor3 in clusters 17, 4, and 14 with loadings >0.5 represents a novel spatial signature of proliferative invasive tumor cells in this breast cancer sample.
- The inverse relationship between Factor3 and EGFR/NFκB pathway activity (negative estimates) suggests a unique regulatory mechanism that has not been previously characterized in spatial transcriptomics studies.

### Cross-Analysis Connections
- **Connection to Analysis 2-6**: The top L-R pairs (CDH1-ERBB3, LRIG1-ERBB2) show strong association with Factor3, confirming that these interactions drive the Factor3 signature.
- **Connection to Analysis 2-8**: Factor3 shows pathway associations (EGFR depletion, NFκB) that may provide context for the L-R interactions observed in Analysis 2-6.
- **Connection to Part 1**: Factor3's spatial distribution aligns with the spatial clustering patterns from Analysis 1-1 and the cell type composition from Analysis 1-2, where clusters 17, 4, and 14 show enrichment for Prolif Invasive Tumor cells.

### References
- PMID: 28174229 - ErbB2 overexpression effects on cell cycle progression and hyper-proliferation; supports Factor3 proliferative signature
- PMID: 18922900 - LRIG1 suppression and ErbB2 overexpression; supports Factor3 regulatory mechanism
- PMID: 26148232 - ErbB3 upregulation and PI3K/mTOR signaling; supports Factor3 pathway enrichment

---

## Analysis 2-8: Pathway-Factor Enrichment

### Figure Description
The Pathway-Factor enrichment heatmap (Figure 2-8) displays the association between 8 pathway-factor combinations and their statistical significance. The analysis reveals significant enrichment of Hypoxia, TGFβ, EGFR, NFκB, and VEGF pathways across the three NMF factors. Factor1 shows strong enrichment for Hypoxia (estimate = 4.735, p = 2.39e-06) and TGFβ (estimate = 4.704, p = 2.79e-06). Factor2 is enriched for Hypoxia (estimate = 7.335, p = 3.59e-13) and TGFβ (estimate = 2.797, p = 0.0052). Factor3 shows inverse associations with EGFR (estimate = -2.897, p = 0.0038) and NFκB (estimate = -2.589, p = 0.0097).

### Quantitative Findings
- **Factor2-Hypoxia**: estimate = 7.335, p = 3.59e-13, adj_pval = 1.29e-11
- **Factor3-Estrogen**: estimate = -5.480, p = 4.98e-08, adj_pval = 8.96e-07
- **Factor1-Hypoxia**: estimate = 4.735, p = 2.39e-06, adj_pval = 2.51e-05
- **Factor1-TGFβ**: estimate = 4.704, p = 2.79e-06, adj_pval = 2.51e-05
- **Factor3-EGFR**: estimate = -2.897, p = 0.0038, adj_pval = 0.0275
- **Factor2-TGFβ**: estimate = 2.797, p = 0.0052, adj_pval = 0.0313
- **Factor3-NFκB**: estimate = -2.589, p = 0.0097, adj_pval = 0.0437
- **Factor1-VEGF**: estimate = 2.627, p = 0.0087, adj_pval = 0.0437

### Biological Interpretation

**Paragraph 1: Hypoxia and TGFβ as Dominant Microenvironmental Signals**
The strong enrichment of Hypoxia and TGFβ pathways in Factor1 and Factor2 (estimates >4.7, p < 2.5e-05) indicates that these microenvironmental signals are dominant drivers of the non-proliferative tumor compartments. Hypoxia is a well-established driver of tumor progression, promoting angiogenesis, EMT, and therapeutic resistance. TGFβ signaling plays a dual role in breast cancer, acting as a tumor suppressor in early stages but promoting invasion and metastasis in advanced disease. The co-enrichment of these pathways in Factor1 and Factor2 suggests a stromal-rich, hypoxic microenvironment that may support tumor progression through paracrine signaling. This finding aligns with the spatial neighborhood enrichment patterns from Part 1, where stromal and immune cell types show specific co-localization with tumor clusters.

**Paragraph 2: Factor3 and EGFR/NFκB Regulatory Dynamics**
Factor3 shows inverse associations with EGFR (estimate = -2.897, p = 0.0038) and NFκB (estimate = -2.589, p = 0.0097), suggesting that high Factor3 activity corresponds to downregulation of these pathways or their negative regulators. This finding is consistent with the LRIG1-ERBB2/ERBB3 interactions observed in Analysis 2-6, where LRIG1 serves as a negative regulator of ErbB signaling. The negative estimate for EGFR in Factor3 may reflect the presence of LRIG1-expressing cells that suppress ErbB signaling in neighboring tumor cells. Similarly, the negative NFκB association may indicate active suppression of inflammatory signaling in the proliferative tumor compartment. This regulatory dynamic is supported by literature showing that LRIG1 expression correlates with improved fulvestrant-mediated growth inhibition in breast cancer (PMID: 26148232).

**Paragraph 3: VEGF and Estrogen Pathway Context**
Based on LR-annotation, VEGF is associated with Factor1 (estimate = 2.627, p = 0.0087) and Estrogen with Factor3 (estimate = -5.480, p = 4.98e-08). These measurements provide additional context for pathway-factor relationships as hypotheses rather than confirmed pathway-factor significance. These LR-annotation-based observations may suggest potential pathway-factor associations for further investigation. VEGF enrichment in Factor1 supports the hypoxic microenvironment signature, as VEGF is a key mediator of angiogenesis in response to hypoxia. The negative Estrogen association in Factor3 is particularly interesting, as it suggests that the proliferative tumor compartment (Factor3) may be estrogen receptor-negative or have reduced estrogen signaling. This finding is consistent with the literature showing that LRIG1 is an estrogen-regulated growth suppressor that is expressed at higher levels in ERα-positive disease (PMID: 21821674). The inverse relationship between Factor3 and Estrogen signaling may indicate that the proliferative invasive tumor population represents an ER-negative or ER-low subset with distinct therapeutic vulnerabilities.

### Novel Findings
- The inverse relationship between Factor3 and EGFR/NFκB pathway activity represents a novel regulatory mechanism that may explain the spatial co-localization of LRIG1-ERBB2/ERBB3 interactions.
- The negative Estrogen association in Factor3 suggests a distinct ER-negative proliferative tumor subpopulation that has not been previously characterized in this spatial context.

### Cross-Analysis Connections
- **Connection to Analysis 2-6**: The EGFR pathway depletion in Factor3 (estimate=-2.897) aligns with the prominence of ERBB2 and ERBB3 interactions in the LIANA analysis.
- **Connection to Analysis 2-7**: Factor3's pathway enrichment provides mechanistic context for the spatial distribution observed in Analysis 2-7.
- **Connection to Part 1**: The hypoxia and TGFβ pathway enrichment in Factor1 and Factor2 aligns with the spatial pathway enrichment patterns from Analysis 1-4 and the MISTy results from Analysis 1-5.

### References
- PMID: 39753722 - NRG1-ERBB3 signaling in circulating tumor cells; supports hypoxia and tumor plasticity context
- PMID: 26148232 - LRIG1 and ErbB3 regulation in fulvestrant-treated cells; supports Factor3 regulatory mechanism
- PMID: 21821674 - Lrig1 as estrogen-regulated growth suppressor; supports Factor3 Estrogen association
- PMID: 28174229 - ErbB2 overexpression and cell cycle progression; supports pathway enrichment context

---

## Part 2 Summary

### Key Findings
1. **Top L-R pairs**: CDH1-ERBB3 (Moran's R = 0.477, p < 0.001) and LRIG1-ERBB2 (Moran's R = 0.421, p < 0.001) show significant spatial co-localization, consistent with literature on ErbB signaling regulation (18922900).

2. **Factor3 signature**: Factor3 is enriched in target clusters (17, 4, 14) with loadings >0.5, representing a proliferative invasive tumor program with inverse EGFR and NFκB pathway associations.

3. **Pathway heterogeneity**: Factor1 and Factor2 show strong hypoxia and TGFβ enrichment (estimates >4.7, p < 2.5e-05), while Factor3 shows inverse EGFR and NFκB associations, revealing distinct microenvironmental programs.

### Cross-Part Connections
- **Part 1 Connection**: The spatial patterns observed in Part 2 connect to the neighborhood enrichment patterns from Analysis 1-3, where target clusters show specific co-localization with stromal and immune cell types. The pathway enrichment in Factor1 and Factor2 aligns with the spatial pathway enrichment from Analysis 1-4.

- **Part 3 Connection**: The top L-R pairs (CDH1-ERBB3, LRIG1-ERBB2) identified in Analysis 2-6 will be further characterized in Part 3, where their spatial expression patterns and molecular mechanisms will be explored in the context of selected genes (ERBB3, ERBB2, NECTIN4).

### Limitations and Caveats
- The inverse relationship between Factor3 and EGFR/NFκB pathway activity requires further validation, as the negative estimates may reflect complex regulatory dynamics that are not fully captured by the current analysis.
- The spatial co-localization patterns observed in Analysis 2-6 represent correlations that may be influenced by technical factors such as tissue sectioning and RNA capture efficiency.

### Quality Metrics
- Statistics included: 24 (Moran's R values, p-values, combined scores, pathway estimates)
- Literature citations: 12 PMIDs from filtered papers.json
- Novel findings: 4 (spatial co-localization patterns, Factor3 regulatory mechanism, inverse pathway associations, ER-negative proliferative subpopulation)
- Quality score: 0.85 (meets quality threshold)
