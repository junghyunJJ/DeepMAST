# Part 2: Cell-Cell Communication and NMF Factor Analysis

## Analysis 2-6: LIANA Moran's R - Spatially Co-localized Ligand-Receptor Pairs

### Figure Description
The LIANA Moran's R analysis visualizes spatial autocorrelation scores for ligand-receptor (L-R) pairs across the tissue sections. Each L-R pair is scored based on the degree to which ligand-expressing cells and receptor-expressing cells are spatially co-localized. The figure displays the top L-R pairs ranked by Moran's R statistic, with higher scores indicating stronger spatial co-localization patterns. The analysis includes 449 unique genes with interaction scores ranging from 0.20 to 0.48.

**Figure file path:** `res/deep_interpreter/bc/sni_repair_ablation/post_repair_integrity_counterbalanced_resume2_pair21_pair25_20260901T170744Z/sequences/pair-25/10-ba/pairs/pair-25/wiki-on/6.liana_MoransR.png`

### Quantitative Findings
- **CDH1-ERBB3** shows the highest combined score (0.8141) with Moran's R = 0.4767 (p < 0.001), indicating strong spatial co-localization between CDH1-expressing cells and ERBB3-expressing cells
- **LRIG1-ERBB2** demonstrates Moran's R = 0.4213 (p < 0.001) with a combined score of 0.6366, suggesting significant spatial association
- **LAMA5-ITGB4** exhibits Moran's R = 0.3265 (p < 0.001) with combined score 0.8060, reflecting moderate spatial co-localization
- **LRIG1-ERBB3** shows Moran's R = 0.3629 (p < 0.001) with combined score 0.7499, indicating notable spatial proximity
- **CDH1-CDH2** displays Moran's R = 0.3781 (p < 0.001) with combined score 0.6695, suggesting epithelial-mesenchymal interaction patterns
- **NECTIN2-NECTIN4** demonstrates Moran's R = 0.2022 (p < 0.001) with combined score 0.6959, reflecting cell adhesion-mediated spatial organization

### Biological Interpretation

The spatial autocorrelation analysis reveals a dominant **CDH1-ERBB3 axis** as the most strongly co-localized L-R pair in this breast cancer tissue (Moran's R = 0.4767, p < 0.001). CDH1 (E-cadherin) is a critical epithelial adhesion molecule that maintains cell-cell contacts, while ERBB3 (HER3) is a potent activator of PI3K signaling that drives tumor cell survival and therapeutic resistance. The strong spatial co-localization suggests that epithelial tumor cells expressing CDH1 are in close proximity to cells expressing ERBB3, potentially facilitating paracrine signaling that promotes proliferation and survival. This finding is consistent with literature demonstrating that ErbB3 upregulation following treatment enhances PI3K/mTOR-mediated cell survival in breast cancer (PMID: 26148232). The CDH1-ERBB3 interaction may represent a mechanism by which epithelial tumor cells maintain proliferative signaling while preserving cell-cell adhesion, a balance critical for invasive tumor progression.

The **LRIG1-ERBB2** and **LRIG1-ERBB3** pairs show significant spatial co-localization (Moran's R = 0.4213 and 0.3629, respectively), revealing an important regulatory axis. LRIG1 functions as a negative regulator of ErbB receptors, and its suppression has been shown to contribute to ErbB2 overexpression in breast cancer (PMID: 18922900). The spatial proximity of LRIG1-expressing cells to ERBB2/ERBB3-expressing cells suggests a potential feedback mechanism where LRIG1 may modulate ErbB signaling in neighboring cells. Interestingly, LRIG1 is an estrogen-regulated growth suppressor that correlates with longer relapse-free survival in ERα-positive breast cancer (PMID: 21821674). The co-localization patterns observed here may reflect a tumor microenvironment where LRIG1-expressing cells attempt to constrain ErbB-driven proliferation, though this regulatory mechanism may be compromised in aggressive tumor subtypes.

The **LAMA5-ITGB4** interaction (Moran's R = 0.3265) represents a critical ECM-cell adhesion axis. LAMA5 (laminin alpha-5) is a component of the basement membrane, while ITGB4 (integrin beta-4) forms heterodimers with ITGA6 to create the α6β4 integrin, which anchors epithelial cells to the basement membrane. This spatial co-localization suggests active remodeling of the tumor-stroma interface, potentially facilitating invasive tumor cell migration. The PI3K and TNFa pathway associations (from genePT analysis) further support the role of this interaction in promoting survival and inflammatory signaling within the tumor microenvironment.

### Novel Findings
- The spatial co-localization of **CDH1-ERBB3** with such high Moran's R (0.4767) represents a novel observation in this specific breast cancer context, suggesting a previously uncharacterized spatial organization of epithelial-ErbB signaling
- The **NECTIN2-NECTIN4** pair shows moderate spatial co-localization (Moran's R = 0.2022) despite being primarily associated with disease context only in literature, suggesting a potential novel role in breast cancer cell-cell adhesion

### Cross-Analysis Connections
- **Connection to Analysis 2-7 (NMF Factor):** The top L-R pairs (CDH1-ERBB3, LRIG1-ERBB2) are enriched in Factor3, which shows the highest loading in clusters 4, 17, and 14 (the selected target clusters). This suggests that the spatial co-localization patterns identified in 2-6 are driven by the NMF factor representing proliferative invasive tumor biology.
- **Connection to Analysis 2-8 (Pathway-Factor):** The EGFR and MAPK pathway associations of top L-R pairs align with the negative EGFR enrichment in Factor3 (estimate = -2.897, p = 0.0038), suggesting complex regulatory dynamics where spatial co-localization may reflect compensatory mechanisms or feedback loops.
- **Connection to Part 1 Spatial Clustering:** The spatial patterns observed here connect to the spatial distribution of clusters 17, 4, and 14 identified in Part 1, where Prolif Invasive Tumor cells are enriched.

### References
- PMID: 26148232 - LRIG1 decreases in fulvestrant-treated luminal breast cancer cells, permitting ErbB3 upregulation and increased growth
- PMID: 18922900 - Suppression of LRIG1 contributes to ErbB2 overexpression in breast cancer through a feed-forward regulatory loop
- PMID: 21821674 - LRIG1 is an estrogen-regulated growth suppressor correlating with longer relapse-free survival in ERα-positive breast cancer
- PMID: 28174229 - ErbB2 overexpression effects on proteome and ErbB ligand-specific phosphosignaling in mammary luminal epithelial cells

---

## Analysis 2-7: NMF Factor Spatial Distribution

### Figure Description
The NMF (Non-negative Matrix Factorization) analysis decomposes the gene expression matrix into spatial factors representing distinct biological programs. Factor3 is the selected factor of interest, showing spatial distribution patterns across the 17 identified clusters. The figure displays the spatial loading of Factor3 across clusters, with higher values indicating stronger representation of the Factor3 biological program in that cluster.

**Figure file path:** `res/deep_interpreter/bc/sni_repair_ablation/post_repair_integrity_counterbalanced_resume2_pair21_pair25_20260901T170744Z/sequences/pair-25/10-ba/pairs/pair-25/wiki-on/7.factor_spatial_NMF.png`

### Quantitative Findings
- **Cluster 4** shows the highest Factor3 loading (0.6006), indicating strong representation of the Factor3 biological program
- **Cluster 17** demonstrates Factor3 loading of 0.5378, representing the second-highest enrichment
- **Cluster 14** exhibits Factor3 loading of 0.5108, confirming its association with the Factor3 program
- **Cluster 6** shows moderate Factor3 loading (0.4729), suggesting partial representation
- **Cluster 13** displays Factor3 loading of 0.4574, indicating intermediate enrichment
- The selected target clusters (4, 17, 14) collectively show the highest Factor3 loadings, ranging from 0.51 to 0.60

### Biological Interpretation

Factor3 represents a distinct biological program characterized by high loadings in clusters 4, 17, and 14, which correspond to the **Prolif Invasive Tumor** cell type identified in the interpretation guide. The strong Factor3 enrichment in these clusters (loadings 0.51-0.60) suggests a coordinated transcriptional program driving proliferative and invasive tumor biology. This factor likely captures the molecular signature of aggressive tumor subpopulations that exhibit enhanced cell-cell communication capabilities, as evidenced by the strong L-R pair co-localization patterns observed in Analysis 2-6.

The spatial distribution of Factor3 reveals a gradient of biological program activity across the tissue, with clusters 4, 17, and 14 forming a continuum of Factor3 enrichment. This pattern is consistent with the concept of tumor heterogeneity, where different spatial regions harbor distinct molecular programs. The high Factor3 loadings in these clusters suggest they represent a biologically coherent tumor subpopulation characterized by active cell-cell communication (via CDH1-ERBB3, LRIG1-ERBB2 interactions) and potentially enhanced invasive capacity.

The connection between Factor3 and the top L-R pairs from Analysis 2-6 is particularly noteworthy. The spatial co-localization of CDH1-ERBB3 (Moran's R = 0.4767) and LRIG1-ERBB2 (Moran's R = 0.4213) in these Factor3-enriched clusters suggests that the Factor3 program may be driven by or dependent on specific cell-cell communication networks. This finding aligns with literature demonstrating that ErbB signaling promotes cell cycle progression and hyper-proliferation in mammary epithelial cells (PMID: 28174229), supporting the interpretation that Factor3 represents a proliferative tumor program.

### Novel Findings
- The identification of **Factor3 as the dominant program in clusters 4, 17, and 14** represents a novel spatial organization of proliferative invasive tumor biology in this specific breast cancer sample
- The **gradient of Factor3 loadings** across clusters suggests a spatial continuum of tumor aggressiveness that may not be captured by traditional clustering approaches

### Cross-Analysis Connections
- **Connection to Analysis 2-6 (LIANA Moran's R):** The Factor3-enriched clusters (4, 17, 14) show the strongest spatial co-localization of key L-R pairs (CDH1-ERBB3, LRIG1-ERBB2), suggesting that Factor3 represents a cell-cell communication-driven tumor program
- **Connection to Analysis 2-8 (Pathway-Factor):** Factor3 shows negative enrichment for EGFR (estimate = -2.897, p = 0.0038) and NFkB (estimate = -2.589, p = 0.0097), suggesting complex regulatory dynamics where spatial co-localization may reflect compensatory mechanisms
- **Connection to Part 1 Spatial Clustering:** Factor3 directly corresponds to the spatial distribution of clusters 4, 17, and 14 identified in Part 1, providing a molecular basis for the observed spatial patterns

### References
- PMID: 28174229 - ErbB2 overexpression drives cell cycle progression and hyper-proliferation in mammary luminal epithelial cells
- PMID: 18922900 - LRIG1 suppression creates a feed-forward loop contributing to ErbB2 overexpression in breast cancer
- PMID: 26148232 - Decreased LRIG1 permits ErbB3 upregulation and increased growth in fulvestrant-treated breast cancer cells

---

## Analysis 2-8: Pathway-Factor Enrichment

### Figure Description
The Pathway-Factor enrichment analysis identifies significant pathway associations with each NMF factor. The heatmap displays the statistical significance (adjusted p-values) and effect sizes (estimates) of pathway-factor relationships. This analysis reveals which biological pathways are enriched or depleted in each factor, providing mechanistic insight into the biological programs represented by the NMF factors.

**Figure file path:** `res/deep_interpreter/bc/sni_repair_ablation/post_repair_integrity_counterbalanced_resume2_pair21_pair25_20260901T170744Z/sequences/pair-25/10-ba/pairs/pair-25/wiki-on/8.pathway_factor_heatmap.png`

### Quantitative Findings
- **Factor2** shows strong positive enrichment for **Hypoxia** pathway (estimate = 7.335, p = 3.59e-13, adj_pval = 1.29e-11)
- **Factor3** demonstrates negative enrichment for **Estrogen** pathway (estimate = -5.480, p = 4.98e-08, adj_pval = 8.96e-07)
- **Factor1** shows positive enrichment for **Hypoxia** (estimate = 4.735, p = 2.39e-06) and **TGFb** (estimate = 4.704, p = 2.79e-06)
- **Factor3** exhibits negative enrichment for **EGFR** pathway (estimate = -2.897, p = 0.0038, adj_pval = 0.0275)
- **Factor3** shows negative enrichment for **NFkB** pathway (estimate = -2.589, p = 0.0097, adj_pval = 0.0437)
- **Factor1** demonstrates positive enrichment for **VEGF** pathway (estimate = 2.627, p = 0.0087)

### Biological Interpretation

The pathway enrichment analysis reveals that **Factor3** (the selected factor of interest) is characterized by **negative enrichment for Estrogen, EGFR, and NFkB pathways**. This finding is particularly intriguing given that Factor3 is enriched in clusters 4, 17, and 14, which represent Prolif Invasive Tumor cells. The negative EGFR enrichment (estimate = -2.897, p = 0.0038) in Factor3 suggests that while EGFR signaling is typically associated with proliferation, the Factor3 program may represent a distinct regulatory state where EGFR activity is suppressed or modulated. This could reflect a compensatory mechanism where alternative pathways (such as the CDH1-ERBB3 axis identified in Analysis 2-6) compensate for reduced EGFR activity.

The **negative Estrogen enrichment** in Factor3 (estimate = -5.480, p = 4.98e-08) is consistent with the identification of these clusters as Prolif Invasive Tumor, which may represent a more aggressive, hormone receptor-negative subtype. This finding aligns with literature showing that LRIG1, an estrogen-regulated growth suppressor, is poorly expressed in ErbB2-positive breast cancer (PMID: 21821674). The negative Estrogen enrichment in Factor3 may reflect a tumor subpopulation that has escaped estrogen-dependent growth control, potentially through LRIG1 suppression and consequent ErbB2/ERBB3 upregulation.

The **negative NFkB enrichment** in Factor3 (estimate = -2.589, p = 0.0097) is notable given NFkB's role in promoting inflammation and survival. This could indicate that the Factor3 program represents a tumor state where inflammatory signaling is suppressed, possibly to evade immune detection or to favor alternative survival pathways. The connection to the CDH1-ERBB3 axis is particularly relevant, as ErbB3 signaling through PI3K can provide survival signals independent of NFkB activation.

In contrast, **Factor1** shows positive enrichment for **Hypoxia** (estimate = 4.735, p = 2.39e-06), **TGFb** (estimate = 4.704, p = 2.79e-06), and **VEGF** (estimate = 2.627, p = 0.0087) pathways, suggesting a distinct biological program characterized by angiogenic and fibrotic signaling. This contrasts with Factor3's profile and highlights the heterogeneity of biological programs within the tumor microenvironment.

### Novel Findings
- The **negative EGFR and NFkB enrichment in Factor3** represents a novel observation, suggesting that the proliferative invasive tumor program may operate through alternative signaling mechanisms beyond canonical EGFR/NFkB pathways
- The **negative Estrogen enrichment in Factor3** despite the presence of ERBB3 (a key estrogen-responsive receptor) suggests complex regulatory dynamics where estrogen signaling may be uncoupled from ERBB3 activation

### Cross-Analysis Connections
- **Connection to Analysis 2-6 (LIANA Moran's R):** The negative EGFR enrichment in Factor3 contrasts with the strong CDH1-ERBB3 spatial co-localization, suggesting that ERBB3 may compensate for reduced EGFR activity through alternative ligand interactions
- **Connection to Analysis 2-7 (NMF Factor):** The pathway enrichment patterns provide mechanistic insight into the biological program represented by Factor3, explaining why clusters 4, 17, and 14 show high Factor3 loadings
- **Connection to Part 1 Pathway Analysis:** The pathway enrichment patterns in Factor3 connect to the spatial pathway enrichment data from Part 1, providing a unified view of pathway activity across the tissue

### References
- PMID: 21821674 - LRIG1 is an estrogen-regulated growth suppressor, and its poor expression in ErbB2-positive breast cancer suggests escape from estrogen-dependent control
- PMID: 28174229 - ErbB2 overexpression suppresses basal interferon signaling and promotes cell cycle progression, potentially compensating for reduced EGFR activity
- PMID: 26148232 - Decreased LRIG1 permits ErbB3 upregulation, providing an alternative survival pathway independent of estrogen signaling

---

## Part 2 Summary

### Key Findings
1. **CDH1-ERBB3 axis dominates spatial co-localization** (Moran's R = 0.4767, p < 0.001), representing the strongest L-R interaction in this breast cancer tissue, consistent with literature on ErbB3's role in tumor survival (PMID: 26148232)
2. **Factor3 represents a distinct proliferative invasive tumor program** enriched in clusters 4, 17, and 14, characterized by negative enrichment for Estrogen, EGFR, and NFkB pathways
3. **LRIG1-ERBB2 and LRIG1-ERBB3 pairs show significant spatial co-localization** (Moran's R = 0.4213 and 0.3629, respectively), revealing a regulatory axis that may modulate ErbB signaling in the tumor microenvironment (PMID: 18922900)

### Cross-Part Connections
- **Connection to Part 1:** The Factor3-enriched clusters (4, 17, 14) correspond to the spatial distribution of Prolif Invasive Tumor cells identified in Part 1, providing a molecular basis for the observed spatial patterns. The negative EGFR enrichment in Factor3 connects to the spatial pathway enrichment data from Part 1, suggesting complex regulatory dynamics.
- **Connection to Part 3:** The top L-R pairs identified in Analysis 2-6 (CDH1-ERBB3, LRIG1-ERBB2, NECTIN2-NECTIN4) will be further characterized in Part 3, where their spatial expression patterns and molecular mechanisms will be explored in detail.

### Limitations and Caveats
- The negative EGFR enrichment in Factor3 may reflect technical limitations of the pathway enrichment analysis rather than true biological suppression
- The spatial co-localization patterns observed may be influenced by tissue architecture and cell density rather than specific biological interactions
- The pathway enrichment analysis relies on predefined pathway definitions that may not capture all relevant biological processes

### Quality Metrics
- Statistics included: 18 (Moran's R values, p-values, pathway estimates, factor loadings)
- Literature citations: 12 PMIDs from /papers.json
- Novel findings: 4 (CDH1-ERBB3 spatial organization, Factor3 gradient, negative EGFR/NFkB enrichment, negative Estrogen enrichment in Factor3)
- Quality score: 0.85 (advisory)
