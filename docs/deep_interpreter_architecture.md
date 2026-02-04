# Deep Interpreter Agent Architecture

Deep Interpreter는 DeepMAST 프로젝트의 핵심 에이전트로, Cell-Cell Interaction (CCI) 분석 결과를 해석하고 문헌 기반의 생물학적 인사이트를 생성합니다.

## 1. 디렉토리 구조

```
src/agents/deep_interpreter/
├── __init__.py
├── agent.py                    # 메인 Deep Agent 생성
├── graph_builder.py            # LangGraph CLI용 그래프 빌더
├── wrapper_agent.py            # HITL Wrapper Agent (정보 수집)
├── wrapper_state.py            # Wrapper State 스키마
├── info_extraction.py          # Pydantic 정보 추출 모델
├── prompts.py                  # Orchestrator 시스템 프롬프트
├── middleware/
│   ├── __init__.py
│   ├── load.py                 # Skill 메타데이터 로더
│   └── skills.py               # SkillsMiddleware (Progressive Disclosure)
├── subagents/
│   ├── __init__.py
│   ├── configs.py              # 4개 서브에이전트 설정
│   ├── prompts.py              # 서브에이전트별 시스템 프롬프트
│   └── literature_searcher/
│       ├── __init__.py
│       └── agent.py            # CompiledSubAgent 패턴
├── tools/
│   ├── __init__.py
│   ├── data_loader.py          # 분석 데이터 로드
│   ├── literature.py           # PubMed 문헌 검색 (BioMCP)
│   ├── literature_rag.py       # RAG 기반 전문 검색
│   ├── quality.py              # 품질 검증
│   ├── report.py               # HTML 리포트 생성
│   └── think.py                # Reflection-tool 기반 사고
└── skills/
    └── __init__.py
```

---

## 2. 2-Tier 아키텍처 개요

Deep Interpreter는 **2-Tier 아키텍처**를 사용합니다:

```
┌──────────────────────────────────────────────────────────────────────────┐
│                    Tier 1: Wrapper Agent (HITL)                          │
│                                                                          │
│  DeepInterpreterWrapperAgent (wrapper_agent.py)                         │
│  - 사용자로부터 정보 수집 (data_directory, analysis_mode, targets)        │
│  - Pydantic 모델로 검증 (DeepInterpreterInfoExtraction)                  │
│  - /targets.json 파일 생성                                               │
│  - Deep Agent 호출                                                       │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                    Tier 2: Deep Agent (Orchestrator)                     │
│                                                                          │
│  create_deep_agent() with 4 Subagents (agent.py)                        │
│  - PLANNER: 타겟 확인 + 가설 생성                                        │
│  - SEARCHER: 문헌 검색 (Literature-First 패턴)                           │
│  - INTERPRETER: Part 1/2/3 해석 + 인라인 검증                            │
│  - REPORTER: 교차 분석 종합 + HTML 리포트                                 │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Wrapper Agent 상세

### 3.1 State 스키마 (`wrapper_state.py`)

```python
class DeepInterpreterWrapperState(TypedDict):
    messages: Annotated[list, add_messages]   # 대화 히스토리
    data_directory: Optional[str]             # 분석 결과 경로
    analysis_mode: Optional[Literal["cluster_to_celltype", "celltype_to_cluster"]]
    interest_clusters: Optional[list[str]]    # Mode A용
    interest_celltypes: Optional[list[str]]   # Mode B용
    info_complete: bool                       # 정보 수집 완료 플래그
    targets_written: bool                     # targets.json 작성 완료
    deep_agent_result: Optional[dict]         # Deep Agent 결과
```

### 3.2 노드 흐름도

```
START
   │
   ▼
┌─────────────────┐
│   check_state   │ ← 이미 정보가 있는지 확인
└─────────────────┘
         │
         ├─── info_complete=True ──────────────────┐
         │                                         ▼
         ▼                                 ┌────────────────┐
┌─────────────────┐                        │  write_targets │
│ info_collection │ ← LLM이 도구 호출      └────────────────┘
└─────────────────┘                                │
         │                                         ▼
         ▼                                 ┌────────────────┐
┌─────────────────┐                        │invoke_deep_agent│
│ info_validation │ ← Pydantic 검증        └────────────────┘
└─────────────────┘                                │
         │                                         ▼
         ├─── 검증 실패 → info_collection          END
         │
         └─── 검증 성공 → write_targets
```

### 3.3 HITL 패턴

Wrapper Agent는 `DeepInterpreterInfoExtraction` Pydantic 모델을 LLM의 tool로 바인딩하여 구조화된 정보를 추출합니다:

```python
class DeepInterpreterInfoExtraction(BaseModel):
    data_directory: str
    analysis_mode: Literal["cluster_to_celltype", "celltype_to_cluster"]
    interest_clusters: Optional[list[str]]  # Mode A
    interest_celltypes: Optional[list[str]] # Mode B
```

---

## 4. Deep Agent (Orchestrator) 상세

### 4.1 4-Agent 아키텍처

원래 11개 에이전트에서 4개로 통합되었습니다:

| 서브에이전트 | 역할 | 입력 | 출력 |
|-------------|------|------|------|
| **PLANNER** | 타겟 확인 + 가설 생성 | /targets.json | /strategic_plan.md, /analysis_summary.md, /data_path.txt |
| **SEARCHER** | 문헌 검색 (Literature-First) | spatial_search_context, lr_search_context | /part1_papers.json, /liana_papers.json |
| **INTERPRETER** | Part 1/2/3 해석 + 검증 | /partN_papers.json | /part1_final.md, /part2_final.md, /part3_final.md |
| **REPORTER** | 종합 + 리포트 생성 | /partN_final.md | /synthesis.md, CCI_Analysis_Report.html |

### 4.2 워크플로우 다이어그램

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ PLANNER                                                                      │
│  - Parse /targets.json from initial message                                 │
│  - Load analysis data                                                       │
│  - Generate 2-4 hypotheses                                                  │
│  → /strategic_plan.md, /analysis_summary.md, /data_path.txt                 │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ SEARCHER (for Part 1, 2, 3)                                                 │
│  - Extract context (genes, pathways, cell types)                            │
│  - Search PubMed proactively (BEFORE interpretation)                        │
│  - Quality loop: coverage >= 60% genes, >= 50% pathways, 15-20 papers       │
│  → /part1_papers.json (Part 1)                                              │
│  → /liana_papers.json (Part 2/3 shared)                                     │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ INTERPRETER (for Part 1, 2, 3)                                              │
│  - Read /partN_papers.json (ONLY citation source)                           │
│  - Generate literature-grounded interpretation                              │
│  - Inline claim validation (every PMID checked)                             │
│  - Quality loop: score >= 0.7, max 3 iterations                             │
│  → /part1_final.md, /part2_final.md, /part3_final.md                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ REPORTER                                                                     │
│  - Read all /partN_final.md                                                 │
│  - Identify cross-part themes                                               │
│  - Validate hypotheses                                                      │
│  - Generate HTML report                                                     │
│  → /synthesis.md, CCI_Analysis_Report.html                                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Hallucination Prevention (환각 방지) 메커니즘

### 5.1 Literature-First 패턴

```
1. SEARCHER가 먼저 PubMed 검색 → papers.json 생성
2. INTERPRETER는 papers.json의 PMID만 인용 가능
3. 논문에 없는 주장 → (Novel Finding)으로 명시
```

### 5.2 3단계 검증

1. **Literature FIRST**: SEARCHER가 해석 전에 논문 검색
2. **Claim Validation**: 모든 PMID 인용을 `validate_claim_literature`로 검증
3. **Novel Finding Tags**: 지원되지 않는 발견은 명확히 표시

---

## 6. Tools (도구들) 상세

### 6.1 Data Loader (`data_loader.py`)

```python
@tool
def load_analysis_data(data_dir: str) -> dict:
    """
    CCI 분석 결과를 로드하고 자동으로 파일 저장

    반환값:
    - available_analyses: 사용 가능한 분석 목록
    - figures: {분석명: 그림 경로}
    - data: {분석명: CSV 경로}
    - clusters: 고유 클러스터 ID
    - celltypes: 고유 세포 유형
    - search_context: 검색 컨텍스트 (genes, pathways, celltypes)
    - spatial_search_context: Part 1용 (pathway + celltype만)
    - lr_search_context: Part 2/3용 (gene + pathway + celltype)
    """
```

### 6.2 Literature Search (`literature.py`)

**세 가지 검색 도구:**

| 도구 | 용도 | 특징 |
|------|------|------|
| `search_literature` | 단일 쿼리 검색 | 기본 PubMed 검색 |
| `search_literature_for_context` | 고정 전략 검색 | 4가지 전략 (gene_disease, pathway_celltype, lr_pair, spatial) |
| `search_literature_dynamic` | **LLM-powered 동적 검색** | 반복적 coverage 개선, 자동 fallback |

**search_literature_dynamic 워크플로우:**

```
1. BioMCP think_tool로 전략 수립
2. LLM이 검색 쿼리 생성
3. 검색 실행 및 coverage 계산
4. coverage 미달시 gap-filling 검색
5. 최대 3회 반복
6. target_gene_coverage=60%, target_pathway_coverage=50%
```

### 6.3 Quality Validation (`quality.py`)

```python
@tool
def validate_quality(interpretation: str, references: list[dict]) -> dict:
    """
    해석 품질 검증 (점수 >= 0.7 통과)

    평가 기준:
    - statistics_score: 통계 2개 이상
    - references_score: PMID 인용 2개 이상
    - mechanism_score: 명확한 생물학적 메커니즘
    - specificity_score: 구체적 언어 사용
    """

@tool
def validate_claim_literature(claim: str, pmid: str, paper_abstract: str) -> dict:
    """
    주장-논문 정합성 검증

    반환값:
    - alignment: "strong" | "weak" | "unsupported"
    - recommendation: "keep" | "revise" | "mark_novel"
    - confidence: 0.0-1.0
    """
```

### 6.4 RAG Tools (`literature_rag.py`)

```python
@tool
def prepare_rag_literature(papers_json_path: str, part_name: str) -> dict:
    """논문 전문 다운로드 및 RAG 인덱싱"""

@tool
def search_literature_fulltext(query: str, part_name: str) -> dict:
    """전문 기반 시맨틱 검색"""

@tool
def validate_claim_fulltext(claim: str, pmid: str, part_name: str) -> dict:
    """전문 기반 주장 검증 (높은 정확도)"""
```

### 6.5 Report Generator (`report.py`)

```python
@tool
def generate_html_report(parts: dict, output_path: str) -> str:
    """
    다크 테마 HTML 리포트 생성

    parts 구조:
    - title, subtitle
    - executive_summary
    - analysis_config
    - part1, part2, part3: {분석명: {figure_path, interpretation, caption, references}}
    - synthesis
    - quality_score
    - references
    """
```

---

## 7. 생성되는 파일들

### 7.1 Virtual Filesystem 파일 (메모리 내)

| 파일 | 생성자 | 설명 |
|------|--------|------|
| `/targets.json` | PLANNER | 분석 설정 (mode, clusters/celltypes, data_directory) |
| `/strategic_plan.md` | PLANNER | 2-4개 가설 + 해석 우선순위 |
| `/analysis_summary.md` | PLANNER | 분석 데이터 요약 |
| `/data_path.txt` | PLANNER | 데이터 디렉토리 경로 |
| `/part1_papers.json` | SEARCHER | Part 1 문헌 (15-20개) |
| `/liana_papers.json` | SEARCHER | Part 2/3 공유 문헌 |
| `/part1_final.md` | INTERPRETER | Part 1 최종 해석 |
| `/part2_final.md` | INTERPRETER | Part 2 최종 해석 |
| `/part3_final.md` | INTERPRETER | Part 3 최종 해석 |
| `/synthesis.md` | REPORTER | 교차 분석 종합 |

### 7.2 실제 파일시스템 출력

| 파일 | 위치 | 설명 |
|------|------|------|
| `CCI_Analysis_Report.html` | data_dir/ 또는 output_dir/ | 최종 HTML 리포트 |
| `targets.json` | data_dir/ | Wrapper가 생성한 타겟 설정 |

---

## 8. Middleware: Skills System

### 8.1 Progressive Disclosure 패턴

```python
class SkillsMiddleware(AgentMiddleware):
    """
    세션 시작시: skill 메타데이터만 로드 (이름, 설명, 경로)
    시스템 프롬프트: skill 목록 주입
    필요시: 에이전트가 read_file로 전체 SKILL.md 읽기
    """
```

### 8.2 Strategy vs Execution 분리

```
┌─────────────────────────────────────────────────────────────────┐
│              SkillsMiddleware (Strategy Layer)                   │
│  skills/biomedical-literature-search/SKILL.md → 검색 전략       │
└─────────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Python Tools (Execution Layer)                │
│  tools/literature.py → 안정적인 MCP 호출 + 에러 처리            │
└─────────────────────────────────────────────────────────────────┘
```

---

## 9. LangGraph CLI 통합

### 9.1 그래프 Export (`graph_builder.py`)

```python
# 메인 그래프 (타겟 사전 선택 필요)
deep_interpreter_graph = _get_deep_interpreter_graph()

# Wrapper 버전 (HITL 타겟 수집, 권장)
deep_interpreter_wrapped_graph = _get_deep_interpreter_graph_wrapped()

# 개별 서브에이전트 테스트용
planner_subagent_graph = _get_planner_subagent_graph()
searcher_subagent_graph = _get_searcher_subagent_graph()
interpreter_subagent_graph = _get_interpreter_subagent_graph()
reporter_subagent_graph = _get_reporter_subagent_graph()
```

### 9.2 langgraph.json 설정

```json
{
  "graphs": {
    "deep_interpreter": "src.agents.deep_interpreter.graph_builder:deep_interpreter_graph",
    "deep_interpreter_wrapped": "src.agents.deep_interpreter.graph_builder:deep_interpreter_wrapped_graph"
  }
}
```

---

## 10. 사용 예시

### 10.1 직접 호출 (타겟 사전 선택)

```python
from src.agents.deep_interpreter.agent import interpret_analysis

result = interpret_analysis(
    data_dir="/path/to/res",
    analysis_mode="cluster_to_celltype",
    targets=["4", "16", "17"],
    provider="openai",
)
```

### 10.2 Wrapper Agent 사용 (HITL)

```python
from src.agents.deep_interpreter.graph_builder import create_deep_interpreter_graph_wrapped

graph = create_deep_interpreter_graph_wrapped(provider="openai")
result = graph.invoke(
    {"messages": [{"role": "user", "content": "Interpret CCI in /data/res for clusters 4, 16"}]}
)
```

---

## 11. 핵심 설계 원칙

1. **Literature-First**: 환각 방지를 위해 해석 전에 문헌 검색
2. **Inline Validation**: 각 주장을 생성하면서 즉시 검증
3. **Quality Loop**: 품질 점수 0.7 미만시 최대 3회 재시도
4. **Novel Finding Tags**: 논문 지원 없는 발견은 명시적 표시
5. **Context-Type Search**: Part별 적절한 검색 컨텍스트 사용
   - Part 1 (Spatial): pathway + celltype (NO genes)
   - Part 2/3 (LIANA): genes + pathway + celltype
6. **Virtual Filesystem**: 중간 파일은 메모리에, 최종 리포트만 디스크에

---

## 12. 관련 문서

- [Deep Interpreter Overview](deep_interpreter_overview.md)
- [Interpreter Subagent Workflow](interpreter_subagent_workflow.md)
- [Literature Search Strategy](literature_search_strategy.md)
- [LangGraph Graphs Reference](langgraph_graphs_reference.md)
