# Deep Interpreter Agent 구조 및 워크플로우 분석 보고서

## 1. 개요

`deep_interpreter`는 DeepMAST 프로젝트의 핵심 AI 에이전트로, **Cell-Cell Interaction (CCI) 분석 결과를 자동으로 해석**하여 publication-quality HTML 보고서를 생성합니다.

### 핵심 아키텍처
```
┌──────────────────────────────────────────────────────────────┐
│              2-Tier Agent Architecture                       │
├──────────────────────────────────────────────────────────────┤
│ Tier 1: DeepInterpreterWrapperAgent (BaseAgent Pattern)     │
│         → HITL로 사용자 입력 수집                            │
│         → targets.json 생성                                  │
├──────────────────────────────────────────────────────────────┤
│ Tier 2: DeepInterpreterAgent (DeepAgents Framework)         │
│         → 4개 Subagent 오케스트레이션                        │
│         → PLANNER → SEARCHER → INTERPRETER → REPORTER       │
└──────────────────────────────────────────────────────────────┘
```

---

## 2. 디렉토리 구조

```
src/agents/deep_interpreter/
├── __init__.py              # 모듈 초기화 및 exports
├── agent.py                 # Deep Agent (DeepAgents framework)
├── wrapper_agent.py         # Wrapper Agent (BaseAgent, HITL)
├── wrapper_state.py         # Wrapper 상태 스키마 (TypedDict)
├── info_extraction.py       # Pydantic 정보 추출 모델
├── graph_builder.py         # LangGraph CLI 통합
├── prompts.py               # Orchestrator 시스템 프롬프트
│
├── subagents/               # 4개 Subagent 정의
│   ├── __init__.py
│   ├── configs.py           # Subagent 설정 (tools, prompts)
│   ├── prompts.py           # Subagent별 프롬프트
│   └── literature_searcher/ # (deprecated)
│
├── tools/                   # 분석 도구들
│   ├── __init__.py
│   ├── data_loader.py       # CCI 분석 데이터 로딩
│   ├── literature.py        # PubMed 문헌 검색
│   ├── quality.py           # 품질 검증 도구
│   ├── report.py            # HTML 보고서 생성
│   └── think.py             # Reflection 도구
│
├── middleware/              # Progressive Disclosure
│   ├── __init__.py
│   ├── skills.py            # SkillsMiddleware
│   └── load.py              # Skill 로더
│
└── skills/                  # 워크플로우 가이드
    └── __init__.py
```

---

## 3. 워크플로우 진행 과정

### Phase 1: Wrapper Agent (HITL 정보 수집)

```
START
  ↓
CHECK_STATE ────────────────────────┐
  ↓ (info 없음)                      │ (info 있음)
INFO_COLLECTION ←──────────┐         │
  ↓ (tool_calls)           │         │
INFO_VALIDATION ───────────┘         │
  ↓ (검증 성공)                       │
WRITE_TARGETS ←────────────────────┘
  ↓
INVOKE_DEEP_AGENT
  ↓
END
```

**수집하는 정보:**
1. `data_directory`: 분석 결과 경로 (예: `res/`)
2. `analysis_mode`: `cluster_to_celltype` (Mode A) 또는 `celltype_to_cluster` (Mode B)
3. `targets`: 관심 클러스터 (Mode A) 또는 셀타입 (Mode B)

**생성 파일:** `/targets.json`

---

### Phase 2: Deep Agent (4-Subagent Orchestration)

#### Subagent 1: PLANNER
- **역할**: 전략 계획 수립 및 가설 생성
- **입력**: `/targets.json`
- **출력**:
  - `/strategic_plan.md` - 2-4개 테스트 가능한 가설
  - `/analysis_summary.md` - 데이터 요약
  - `/data_path.txt` - 데이터 디렉토리 경로
- **Tools**: `load_analysis_data`

#### Subagent 2: SEARCHER
- **역할**: 해석 전 문헌 검색 (Hallucination 방지)
- **입력**: `/data_path.txt`, 분석 컨텍스트
- **검색 전략**:
  - Part 1: `spatial_search_context` (pathways + celltypes, 유전자 제외)
  - Part 2+3: `lr_search_context` (genes + pathways + celltypes, 공유)
- **출력**:
  - `/part1_papers.json` - Part 1용 문헌 (15-20편)
  - `/liana_papers.json` - Part 2&3 공유 문헌 (15-20편)
- **Tools**: `load_analysis_data`, `search_literature_dynamic`, `search_literature_for_context`, `think_tool`
- **Coverage 목표**: genes ≥60%, pathways ≥50%

#### Subagent 3: INTERPRETER
- **역할**: 문헌 기반 해석 + 인라인 검증
- **처리 순서**: Part 1 → Part 2 → Part 3
- **각 Part 처리**:
  1. `/partN_papers.json` 읽기 (유일한 인용 소스)
  2. 해석 텍스트 생성
  3. Claim-PMID 검증 (validate_claim_literature)
  4. Quality 검증 (score ≥ 0.7, 최대 3회 반복)
- **출력**:
  - `/part1_final.md` - Part 1 최종 해석
  - `/part2_final.md` - Part 2 최종 해석
  - `/part3_final.md` - Part 3 최종 해석
- **Tools**: `load_analysis_data`, `validate_claim_literature`, `validate_quality`, `think_tool`

#### Subagent 4: REPORTER
- **역할**: 통합 및 HTML 보고서 생성
- **입력**: 모든 `/partN_final.md` 파일
- **출력**:
  - `/synthesis.md` - 교차 주제 통합
  - `CCI_Analysis_Report.html` - **최종 보고서**
- **Tools**: `load_analysis_data`, `generate_html_report`

---

## 4. 생성되는 파일 목록

### Virtual Filesystem (Deep Agent 관리)

| 파일명 | 생성 주체 | 단계 | 설명 |
|--------|----------|------|------|
| `/targets.json` | Wrapper | HITL | 사용자 선택 타겟 설정 |
| `/analysis_summary.md` | PLANNER | Phase 2-1 | 전체 데이터 요약 |
| `/data_path.txt` | PLANNER | Phase 2-1 | 데이터 디렉토리 경로 |
| `/strategic_plan.md` | PLANNER | Phase 2-1 | 2-4개 테스트 가설 |
| `/part1_papers.json` | SEARCHER | Phase 2-2 | Part 1 문헌 (15-20편) |
| `/liana_papers.json` | SEARCHER | Phase 2-2 | Part 2&3 공유 문헌 |
| `/part1_final.md` | INTERPRETER | Phase 2-3 | Part 1 최종 해석 |
| `/part2_final.md` | INTERPRETER | Phase 2-3 | Part 2 최종 해석 |
| `/part3_final.md` | INTERPRETER | Phase 2-3 | Part 3 최종 해석 |
| `/synthesis.md` | REPORTER | Phase 2-4 | 교차 주제 통합 |
| `CCI_Analysis_Report.html` | REPORTER | Phase 2-4 | **최종 HTML 보고서** |

### 실제 Filesystem (입력 데이터)

`res/` 디렉토리에서 읽는 분석 결과:

| Part | Figure | Data CSV | 분석명 |
|------|--------|----------|--------|
| **Part 1** | 1.spatial.png | - | 공간 분포 |
| | 2.celltype_heatmap_analysis.png | sig_clusterwithcelltyp.csv | 셀타입 구성 |
| | 3.neighborhood_enrichment_squidpy.png | res_nhood_enrichment.csv | 이웃 농축 |
| | 4.spatial_enrich_decoupler.png | sig_PathwayEnrich_decoupler.csv | 경로 농축 |
| | 5.spatial_relation_MISTy.png | res_SpatialRelationship_MISTy.csv | MISTy 관계 |
| **Part 2** | 6.liana_MoransR.png | sig_liana.csv | LIANA Moran's R |
| | 7.factor_spatial_NMF.png | res_liana_cluster_factor.csv | NMF 인자 |
| | 8.pathway_factor_heatmap.png | sig_liana_pathway_factor.csv | 경로-인자 |
| | 9.quadrant_analysis.png | interest_sig_liana.csv | ctSVG 사분면 |
| **Part 3** | 10.spatial_plot_interections.png | - | L-R 공간 패턴 |
| | 11.lr_interections.png | anno_sig_liana.csv | L-R 상호작용 요약 |

---

## 5. 핵심 Tools 상세

### data_loader.py
```python
load_analysis_data(data_dir, config) → dict
# 반환: clusters, celltypes, genes, available_analyses
# 자동 생성: /analysis_summary.md, /data_path.txt
```

### literature.py
```python
search_literature_dynamic(genes, pathways, celltypes, disease, ...) → dict
# LLM 기반 반복 검색 (최대 3회)
# Coverage 목표: genes ≥60%, pathways ≥50%
# 반환: papers, generated_queries, coverage, coverage_history
```

### quality.py
```python
validate_quality(interpretation, references) → dict
# 4가지 기준: Statistics(0.25), References(0.25), Mechanism(0.25), Specificity(0.25)
# 통과 기준: score ≥ 0.7

validate_claim_literature(claim, pmid, paper_abstract) → dict
# Claim-PMID 정합성 검증
# 반환: alignment, confidence, evidence_quote, recommendation
```

### report.py
```python
generate_html_report(title, parts, figures, output_path) → str
# Dark theme HTML 생성
# Base64 이미지 임베딩
```

---

## 6. Hallucination 방지 메커니즘

1. **Literature-FIRST**: SEARCHER가 INTERPRETER 전에 문헌 검색
2. **Claim Validation**: 모든 PMID 인용 검증 (validate_claim_literature)
3. **Novel Finding Tags**: 미지원 발견은 `(Novel Finding)`으로 표시
4. **Quality Loop**: score < 0.7이면 최대 3회 재시도

---

## 7. 진입점 및 실행 방법

### LangGraph CLI
```bash
# 권장: Wrapper 포함 (HITL)
langgraph dev  # deep_interpreter_wrapped_graph

# 직접 실행 (targets.json 필요)
# deep_interpreter_graph
```

### Programmatic
```python
from src.agents.deep_interpreter import (
    create_deep_interpreter_agent,
    interpret_analysis,
    DeepInterpreterConfig
)

# Option 1: Agent 직접 생성
config = DeepInterpreterConfig(
    provider="openai",
    data_dir="/path/to/res",
    max_iterations=3,
    quality_threshold=0.7
)
agent = create_deep_interpreter_agent(config)

# Option 2: 편의 함수
result = interpret_analysis(
    data_dir="/path/to/res",
    analysis_mode="cluster_to_celltype",
    targets=["4", "16", "17"]
)
```

---

## 8. State 스키마 (TypedDict)

```python
class DeepInterpreterWrapperState(TypedDict):
    messages: Annotated[list, add_messages]  # 대화 기록
    data_directory: Optional[str]            # 데이터 경로
    analysis_mode: Optional[Literal["cluster_to_celltype", "celltype_to_cluster"]]
    interest_clusters: Optional[list[str]]   # Mode A 타겟
    interest_celltypes: Optional[list[str]]  # Mode B 타겟
    info_complete: bool                      # 정보 수집 완료 플래그
    targets_written: bool                    # targets.json 생성 플래그
    deep_agent_result: Optional[dict]        # Deep Agent 결과
```

---

---

## 9. Literature 검색 로직 상세

### 검색 도구 3종류

#### 1. `search_literature` (단순 검색)
```python
search_literature(genes, disease, keywords, max_results=15)
# 단일 BioMCP article_searcher 호출
# 최대 5개 유전자, 5개 키워드로 제한
```

#### 2. `search_literature_for_context` (4전략 고정 검색)
```python
search_literature_for_context(genes, pathways, celltypes, disease, interaction_type, max_results=20)
```

**4가지 검색 전략:**
| 전략 | 설명 | 파라미터 |
|------|------|----------|
| gene_disease | 유전자 + 질병 + 상호작용 | genes[:5], [disease], [interaction_type] |
| pathway_celltype | 경로 + 세포타입 | None, [disease], pathways[:3] + celltypes[:3] |
| lr_pair | L-R 상호작용 | genes[:4], [disease], ["ligand receptor", "cell-cell interaction"] |
| spatial | 공간 전사체 | None, [disease], ["spatial transcriptomics", "single cell", "tumor microenvironment"] + celltypes[:3] |

#### 3. `search_literature_dynamic` (LLM 기반 반복 검색) - **PRIMARY**
```python
search_literature_dynamic(
    genes, pathways, celltypes, disease,
    max_results=30,
    target_gene_coverage=0.6,      # 60% 유전자 커버리지 목표
    target_pathway_coverage=0.5,   # 50% 경로 커버리지 목표
    max_iterations=3               # 최대 3회 반복
)
```

**동적 검색 워크플로우:**
```
Step 0: BioMCP think (3단계 전략 계획)
  ├── Step 1: Context Analysis
  ├── Step 2: Search Keywords
  └── Step 3: Expected Results
       ↓
Iteration Loop (최대 3회):
  1. Coverage 계산
  2. LLM Query 생성 (LITERATURE_QUERY_GENERATION_PROMPT)
     - 6-9개 다양한 쿼리 생성
     - ≥2-3 유전자 중심, ≥2 경로 중심, ≥1-2 세포타입 중심
  3. 유전자 쿼리 실행 (60% 슬롯)
  4. 경로 쿼리 실행 (40% 슬롯)
  5. Coverage 재계산
  6. 목표 미달시 GAP_FILLING_QUERY_PROMPT로 추가 검색
       ↓
Coverage 목표 달성 또는 max_iterations 도달
```

### Coverage 계산 로직

**스마트 패턴 매칭:**
```python
def _generate_gene_patterns(gene):
    # 1. Case variations: ADAM10, Adam10, adam10
    # 2. Separator variations: ADAM10, ADAM-10, ADAM 10
    # 3. Greek letters: TGFβ ↔ TGF-beta
    # 4. Special aliases: ACKR3 → CXCR7, CDH1 → E-CADHERIN
    # 5. BioMCP aliases: 캐시된 gene_getter 결과

def _calculate_coverage(papers, genes, pathways, celltypes):
    # 패턴 매칭으로 coverage 계산
    # genes_coverage_pct, pathways_coverage_pct, celltypes_coverage_pct
    # genes_missing, pathways_missing (SKILL.md 준수)
```

---

## 10. Quality 검증 메커니즘 상세

### 품질 점수 계산 (`validate_quality`)

**4가지 기준 (각 0.25 가중치):**

| 기준 | 설명 | 체크 패턴 |
|------|------|-----------|
| **statistics** | 정량적 통계 ≥2개 | `\d+\.?\d*%`, `p\s*[<>=]\s*\d+`, `fold\s*change`, `\d+\s*(cells?\|spots?\|clusters?)` |
| **references** | PMID 인용 ≥2개 | `PMID[:\s]*\d+`, `\[\d+\]` |
| **mechanism** | 명확한 생물학적 메커니즘 | "signaling", "pathway", "receptor", "ligand", "activation", "inhibition" 등 |
| **specificity** | 모호한 표현 회피 | `-0.2/개` for: "might be", "could potentially", "further research is needed" |

**점수 계산:**
```python
total_score = (
    statistics_score * 0.25 +
    references_score * 0.25 +
    mechanism_score * 0.25 +
    specificity_score * 0.25
)
# 통과: score >= 0.7
```

### Claim-Literature 검증 (`validate_claim_literature`)

```python
validate_claim_literature(claim, pmid, paper_abstract)
# 반환:
#   alignment: "strong" | "moderate" | "weak" | "unsupported"
#   confidence: 0.0-1.0
#   evidence_quote: 지지 인용구
#   recommendation: "keep" | "revise" | "mark_novel"
```

**처리 로직:**
- **strong**: 유지
- **moderate**: 유지 (추가 참조 고려)
- **weak**: claim 수정하여 논문 내용과 일치시킴
- **unsupported**: claim 수정 OR `(Novel Finding)` 태그

### Quality Loop

```
Part N 해석 생성
      ↓
validate_quality() 호출
      ↓
score >= 0.7? ─Yes→ 완료
      │
      No
      ↓
피드백 기반 개선
      ↓
재검증 (최대 3회)
```

---

## 11. Subagent 프롬프트 상세

### PLANNER_PROMPT 핵심 지시사항

```markdown
## Workflow
1. Read /targets.json (analysis_mode, interest_clusters, interest_celltypes, data_directory)
2. Call load_analysis_data with EXACT path from data_directory
3. Write /analysis_summary.md, /data_path.txt
4. Generate 2-4 testable hypotheses:
   - H1: Spatial Organization
   - H2: Cell-Cell Communication
   - H3: Pathway Activation
5. Write /strategic_plan.md
```

### SEARCHER_PROMPT 핵심 지시사항

```markdown
## CRITICAL: Literature-First Pattern
Papers = ONLY citation source for interpreter → Hallucination 방지

## 5-Phase Workflow
1. Extract Context (spatial_search_context for Part 1, lr_search_context for Part 2+3)
2. Think (BioMCP think x3 for strategic planning)
3. Search (search_literature_dynamic PRIMARY, search_literature_for_context FALLBACK)
4. Reflect (think_tool for coverage check: genes >= 60%, pathways >= 50%)
5. Write Output (/part1_papers.json, /liana_papers.json)

## Common Mistakes to AVOID
- DO NOT read .csv files directly (context overflow)
- DO NOT search with all 352 genes (prioritize 10-15)
- DO NOT skip Phase 2 (Think) before searching
```

### INTERPRETER_PROMPT 핵심 지시사항

```markdown
## CRITICAL: Literature-First Interpretation
Every claim MUST either:
- Cite a PMID from /partN_papers.json with supporting evidence
- Be marked as (Novel Finding) if no literature support

## Workflow for EACH Part
1. Load Context: Read /partN_papers.json (ONLY citation source)
2. Generate Interpretation: 2+ statistics, PMID citations
3. Inline Claim Validation: validate_claim_literature for EACH PMID
4. Inline Quality Check: validate_quality, score >= 0.7, max 3 iterations
5. Write /partN_final.md

## Citation Format
- Supported: "The enrichment... (PMID: 12345678)."
- Novel: "This spatial pattern... **(Novel Finding)** has not been previously reported."
```

### REPORTER_PROMPT 핵심 지시사항

```markdown
## Workflow
1. Read all inputs: /part1_final.md, /part2_final.md, /part3_final.md, /strategic_plan.md
2. Cross-Part Synthesis: 4 themes (Spatial, Communication, Pathway, Disease)
3. Hypothesis Validation: Supported | Partially Supported | Not Supported
4. Write /synthesis.md
5. Call generate_html_report() with parts dict and output_path

## Report Structure
- Header, Executive Summary, Configuration
- Part 1/2/3 Tabs with figures
- Summary Tab: Synthesis, Hypothesis validation, References
```

---

## 요약

deep_interpreter는 **2-Tier 아키텍처**로 구성됩니다:
- **Wrapper Agent**: HITL로 사용자 입력 수집 → `/targets.json` 생성
- **Deep Agent**: 4개 Subagent 오케스트레이션 (PLANNER → SEARCHER → INTERPRETER → REPORTER)

**생성 파일**: 11개 가상 파일 + 1개 최종 HTML 보고서
**핵심 특징**: Literature-FIRST 검색 + Claim 검증으로 Hallucination 방지

### 핵심 도구 요약

| 도구 | 목적 | 핵심 로직 |
|------|------|-----------|
| `search_literature_dynamic` | LLM 기반 반복 검색 | BioMCP think → LLM query 생성 → coverage 평가 → gap filling |
| `validate_quality` | 해석 품질 검증 | 4기준 가중 평균 (statistics, references, mechanism, specificity) |
| `validate_claim_literature` | Claim-PMID 정합성 | alignment 판정 → keep/revise/mark_novel |

### Subagent 역할 요약

| Subagent | 핵심 역할 | 출력 파일 |
|----------|-----------|-----------|
| PLANNER | 가설 생성 | /strategic_plan.md |
| SEARCHER | 문헌 검색 | /part1_papers.json, /liana_papers.json |
| INTERPRETER | 문헌 기반 해석 | /part1,2,3_final.md |
| REPORTER | 통합 + HTML | /synthesis.md, CCI_Analysis_Report.html |
