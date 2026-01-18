
# 각 파트 및 결과 description

## 문서 개요

### 목적
- **AI Agent (CCIInterpreterAgent) 가이드라인**: CCI 분석 결과의 생물학적 해석을 위한 기준 문서
- 모든 Part의 `**분석 결과:**` 섹션은 AI Agent가 자동 생성

### 사용자 입력
- **관심 cluster ID(s)** 또는 **interest_celltypes** (둘 중 하나만 입력)
- **양방향 자동 탐색**: cluster 입력 시 → enriched celltype 자동 탐색, celltype 입력 시 → enriched cluster 자동 탐색

### AI Agent 참조 소스
- **내부 DB (RAG)**: DisGeNet, PROGENy, Omnipath
- **외부 검색**: PubMed 논문 검색

### 에지 케이스 처리
- 유의미한 결과가 없을 경우 (예: significant LR pair = 0) → **분석 중단 + 사유 설명**

### Part간 데이터 흐름
```
사용자 입력 (cluster 또는 celltype)
    ↓
Part1: Before CCI Analysis (양방향 자동 탐색)
    ↓ [전달: cluster IDs + celltypes + pathways]
Part2: CCI + NMF + ctSVG Analysis
    ↓ [전달: 선정된 LR pairs (1-10개)]
Part3: LR Pair Visualization
    ↓
HTML Report (모든 Part 포함)
```

---

## Part1: before CCI analysis 
 - Part1 분석은 normalization된 n_*adata.h5ad 데이터 시용.


### Part1-1. Spatial Clustering Analysis
  - 그림 설명: 기본적인 Spatial plot
  - 그림 위치: res/1.spatial.png
  - **분석 결과 (AI 자동 생성)**: 생물학적 해석 가이드
    - 각 cluster의 공간적 위치 및 분포 패턴 설명
    - 조직 구조 (예: tumor core, tumor margin, stromal region 등)와의 대응 관계 해석
    - 사용자가 지정한 관심 cluster의 특성 요약


### Part1-2. Cell Type Composition Analysis (ctanalysis)
  - 그림설명: Scaled median cell-type compositions (comp.) within each cluster. Asterisks indicate increased composition of a cell type in a cluster compared with other clusters (one-sided Wilcoxon rank sum test, adjusted (adj.) P < 0.05).   
  - 그림 위치: res/2.celltype_heatmap_analysis.png
  - 결과 파일 위치: res/sig_clusterwithcelltyp.csv
    cluster: cluster name
    celltype: celltype name
    cluster_medians: median value
    fdr: adjust pvalue (False Discovery Rate;FDR)
  - **분석 결과: cluster identification (관심있는 cell type 이 에대한 spatial cluster 찾고싶은경우 = custer 선정 및 결과 해석) or celltype identification (관심있는 cluster와 관련있는 cell tpye을 찾고 싶은 경우 =  cell type 선정 및 결과 해석)**
  

### Part1-3. Neighborhood Enrichment Analysis (Squidpy)
  - 그림 설명: Computing a neighborhood enrichment can help us identify spots clusters that share a common neighborhood structure across the tissue. We can compute such score with the following function: squidpy.gr.nhood_enrichment(). In short, it's an enrichment score on spatial proximity of clusters: if spots belonging to two different clusters are often close to each other, then they will have a high score and can be defined as being enriched. On the other hand, if they are far apart, and therefore are seldom a neighborhood, the score will be low and they can be defined as depleted. This score is based on a permutation-based test.
  - **분석 파라미터**: `n_perms=1000` (permutation 횟수)
  - 그림 위치: res/3.neighborhood_enrichment_squidpy.png
  - 결과 파일 위치: res/res_nhood_enrichment.csv
    cluster: cluster name
    cluster: cluster name
    value: Neighborhood enrichment score
  - **분석 결과 (AI 자동 생성)**: additional cluster identification (관심 cluster와 공간적으로 인접한 cluster 탐색 및 결과 해석)


### Part1-4. Spatial Pathway Enrichment Analysis (Decoupler)
  - 그림 설명: PROGENy geneset (pathway)을 사용한 spatial cluster에 따른 spatial pathway enrichemnt analysis 결과. PROGENy geneset is a comprehensive resource that provides a curated collection of pathways and their target genes, along with weights for each interaction. -> 특정 cluster와 관련된 pathway 분석 
  - 그림 위치: res/4.spatial_enrich_decoupler.png
  - 결과 파일 위치: res/sig_PathwayEnrich_decoupler.csv
    group: target cluster
    reference: target cluster을 뺸 나머지 cluster
    name: pathway name (PROGENy geneset)
    stat: statistics of Spatial pathway enrichemnt analyis
    meanchange: mean change 결과
    pval: 관련 pvalue
    padj: 관련 adjust pvalue (False Discovery Rate;FDR)
  - **분석 결과: pathway identification (내가 관심있어 하는 cluster와 관련된 pathway 선정 및 결과 해석)**
  - 기타1: decoupler (https://decoupler.readthedocs.io/en/latest/index.html) 사용
  - 기타2: PROGENy Pathway Genes리스트 및 description (*NOTE!! 최종 html report에 추가*)
    Androgen: involved in the growth and development of the male reproductive organs
    EGFR: regulates growth, survival, migration, apoptosis, proliferation, and differentiation in mammalian cells
    Estrogen: promotes the growth and development of the female reproductive organs
    Hypoxia: promotes angiogenesis and metabolic reprogramming when O2 levels are low
    JAK-STAT: involved in immunity, cell division, cell death, and tumor formation
    MAPK: integrates external signals and promotes cell growth and proliferation
    NFkB: regulates immune response, cytokine production and cell survival
    p53: regulates cell cycle, apoptosis, DNA repair and tumor suppression
    PI3K: promotes growth and proliferation
    TGFb: involved in development, homeostasis, and repair of most tissues
    TNFa: mediates haematopoiesis, immune surveillance, tumour regression and protection from infection
    Trail: induces apoptosis
    VEGF: mediates angiogenesis, vascular permeability, and cell migration
    WNT: regulates organ morphogenesis during development and tissue repair


### Part1-5. Spatial pathway enrichment analysis (MISTy)
  - 그림 설명: target(cell type)-predictor(pathway) 관계는 *"어떤 분자적 신호 환경 (pathway)이 특정 세포 타입 (cell type)의 공간적 분포를 결정하는가"*를 정량적으로 보여주는 plot. → 특정 pathway 관련된 celltype 분석
  - 그림 위치: res/5.spatial_relation_MISTy.png
  - 결과 파일 위치: res/res_SpatialRelationship_MISTy.csv
    target: cell type name
    predictor: pathway (PROGENy geneset)
    view: para (Paracrine signalling) - 확산 신호 기반 분석
    importances: Regardless of the model, each target is predicted independently, and the interpretation of feature importances depends on the model used. By default, we use a random forest, so the feature importances are the mean decrease in Gini impurity of the features.
  - **분석 결과 (AI 자동 생성)**: Identification of pathway and cell type relationship (특정 pathway 관련된 celltype 선정 및 결과 해석)
  - 기타: MISTy (https://liana-py.readthedocs.io/en/latest/notebooks/misty.html) 사용


### **NOTE!!! Part 1 분석 주요사항**
 - **입력**: 사용자가 관심 cluster ID(s) 또는 interest_celltypes 중 하나를 사전 지정
 - **양방향 자동 탐색**: cluster 입력 시 enriched celltype 자동 탐색, celltype 입력 시 enriched cluster 자동 탐색
 - **출력**: 최종적으로 관심있는 cluster와 관련된 cell type 및 pathway 선정
 - 관심있는 cluster가 여러 개 (Part1-3 Squidpy 분석으로 추가된 경우 포함) 있다면 각각에 대한 관련 cell type 및 pathway 선정
 - **Part2로 전달**: 선정된 cluster IDs + enriched celltypes + significant pathways



## Part 2: CCI analysis with NMF and ctSVG anlaysis
 - Part 2 분석은 CCI, Morans R, NMF 결과가 있는 lrdata.h5ad 사용.

### Part2-6. Cell Cell interaction (CCI) analyiss (LIANA using Omnipath)
  - 그림설명: ligand-receptor pair에 대한 MoransR 결과. significant (MoransR > 0 & pval < 0.05)는 red dot으로 나타냄.
  - 그림 위치: res/6.liana_MoransR.png
    Bivariate Moran’s R values near zero imply spatial independence, while positive values reflect spatial co-clustering.
  - **분석 결과: Identification of significant ligand-receptor pais**


### Part2-7. Intercellular pattern analysis (factor score; NMF)
  - 그림 설명: Factor scores는 각 spot에서 특정 factor(intercellular pattern)가 얼마나 활성화되어 있는지를 나타내는 값으로 이것에 대한 spatial plot 및 cluster 별로 median bar plot.
  - **NMF factor 개수(k) 결정**: LIANA+ 기본 방법 (데이터 기반 자동 결정)
  - 그림 위치: res/7.factor_spatial_NMF.png
  - 결과 파일 위치: res/res_liana_cluster_factor.csv
    index: spot barcode
    factor (Factor1 ... #): NMF (Non-negative Matrix Factorization)의 factor scores 결과.
    Annotation: cluster information
  - **Factor 선정 기준**: 관심 cluster 내 factor score의 **median/mean 값**이 가장 높은 factor 한 개 선정
  - **분석 결과 (AI 자동 생성)**: Identification of factor (Part1에서 선정된 cluster와 가장 관련이 깊은 factor 선정 및 근거 제시)


### Part2-8. Pathway enrichment analysis using ligand receptor loading (NMF)
  - 그림 설명: Loadings는 NMF (Non-negative Matrix Factorization) 분석을 통해 식별된 각 factor(잠재 패턴)에서 특정 ligand-receptor interaction이 얼마나 중요하게 기여하는지를 나타내는 가중치/기여도 값. 이 Loadings값을 이용해서 pathway enrichment analysis 분석을 진행.
  - **Enrichment method**: Decoupler method (pathway activity estimation)
  - 그림 위치: res/8.pathway_factor_heatmap.png
  - 결과 파일 위치: res/sig_liana_pathway_factor.csv
    factor (Factor1 ... #): NMF (Non-negative Matrix Factorization)의 factor scores 결과.
    pathway: pathway 이름
    estimate: 추정치
    pval: pvalue
    adj_pval: adjust pvalue (False Discovery Rate;FDR)
  - **분석 결과 (AI 자동 생성)**: pathway identification with factor (Part2-7에서 선정한 factor와 관련된 pathway 선정 및 Part1-4에서 선정된 pathway와 비교)


### Part2-9. Cell type-specific spatially variable genes (ctSVGs) analysis (CELINA)
 - 그림 설명: Quadrant analysis plot으로 Moran's R (x축)과 Factor loading (y축)의 두 변수 관계를 해석할 때, **좌표평면을 4개의 사분면(quadrant)**으로 나누어 패턴을 시각화하는 분석 기법.
 - **Quadrant 분할 기준**: 각 축의 **median 값**을 기준으로 4분면 구분
 - **ctSVG 판정 기준**: CELINA 기본 기준 (default statistical threshold)
 - 그림 위치: res/9.quadrant_analysis.png
 - 각각의 ligand, receptor에 대해서 Cell type-specific spatially variable (ctSVGs) 선정을 위한 분석.
 - CCI 결과에서 중요도의 우선순위를 정할 때 사용.
 - 결과 파일 위치: **res/anno_sig_liana_CCI.csv, res/interest_anno_sig_liana.csv**
    liana_interaction: ligand^receptor name of LIANA+ analysis
    ligand: ligand name
    receptor: receptor name
    references: CCIdb reference
    morans: Bivariate Moran's R values near zero imply spatial independence, while positive values reflect spatial co-clustering.
    morans_pvals: pvalues of results of morans
    mean: mean of global expression (ligand + receptor)
    std: standard deviation of global expression (ligand + receptor)
    Factor1 ~ # : NMF (Non-negative Matrix Factorization)의 Loadings 결과. NMF 분석을 통해 식별된 각 factor(잠재 패턴)에서 특정 ligand-receptor interaction이 얼마나 중요하게 기여하는지를 나타내는 가중치/기여도 값.
    progeny: related pathway name from PROGENy geneset
    disease: related disease name from DisGeNet
    ligand_ctSVG: ligand와 관련된 Cell type-specific spatially variable genes (ctSVGs)
    receptor_ctSVG: receptor와 관련된 Cell type-specific spatially variable genes (ctSVGs)
  - NOTE!! interest_anno_sig_liana.csv에는 최종적으로 ctSVG 기준으로 관심 celltype과 관련있는 ligand-receptor pair 결과가 저장됨.
 - **최종 LR pair 선정**:
   - **선정 개수**: 1-10개 (데이터 품질 및 유의성에 따라 유동적)
   - **선정 우선순위** (높은 순): Factor loading > Moran's R > Pathway 일치 > ctSVG
 - **분석 결과 (AI 자동 생성)**: Identification of ctSVGs 및 최종 Part 3에 사용할 ligand-receptor 선정

### **NOTE!! Part 2 분석 주요사항**
  - **입력**: Part1에서 전달된 cluster IDs, enriched celltypes, significant pathways
  - **Part2-7 Factor 선정**: 관심 cluster 내 factor score의 median/mean 값이 가장 높은 factor 한 개 선정 (필수)
  - **Part2-9 interest_celltypes**: Part1에서 선정한 celltype 사용
  - **최종 LR pair 선정**:
    - 선정 개수: 1-10개 (데이터 품질 및 유의성에 따라 유동적)
    - 선정 우선순위: Factor loading > Moran's R > Pathway 일치 > ctSVG
    - interest_anno_sig_liana.csv에서 위 기준에 따라 선정
  - **Part3로 전달**: 선정된 ligand-receptor pairs


## Part3. ligand-receptor pair plots
- Part 3 분석은 lrdata.h5ad 데이터 및 선정된 ligand-receptor pair 사용

### Part3-10. spatial plots for ligand-receptor pair
 - ligand-receptor pair에 대한 spatial plot visualization

### Part3-11. summary of ligand-receptor interactions
 - ligand-receptor pair 에 대한 발현 값 및 p-values 결과.