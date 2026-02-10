# PLANNER Subagent 상세 분석

> 전략 기획 에이전트 — 가설 없는 데이터 기반 해석 프레임워크 구축

## 목차

- [개요](#개요)
- [설정](#설정)
- [6단계 실행 워크플로우](#6단계-실행-워크플로우)
- [도구 상세](#도구-상세)
- [입출력 파일 계약](#입출력-파일-계약)
- [인스턴스 생성 경로](#인스턴스-생성-경로)
- [핵심 설계 원칙](#핵심-설계-원칙)
- [수정 가이드](#수정-가이드)

---

## 개요

PLANNER는 Deep Interpreter 4-에이전트 워크플로우의 **첫 번째** 서브에이전트입니다.

**핵심 원칙**: "가설을 세우지 않는 전략 기획" — 확증 편향을 방지하기 위해 데이터 기반의 해석 프레임워크만 구축하고, 실제 패턴 발견은 하류 에이전트(SEARCHER, INTERPRETER, REPORTER)에게 맡깁니다.

**위치**: `src/agents/deep_interpreter/subagents/configs.py` (설정), `subagents/prompts.py` (프롬프트)

---

## 설정

### configs.py

```python
"planner": {
    "name": "planner",
    "description": (
        "Strategic planning agent. Reads /targets.json, loads analysis data, "
        "generates biomedical context via BioMCP think (disease biology context), "
        "searches literature for grounding (10 papers), assesses data availability, "
        "and creates a data-driven interpretation guide with focus areas and priorities. "
        "Outputs /interpretation_guide.md, /planner_literature_context.md, /planner_biomcp_context.md. "
        "Use this FIRST to establish the interpretation strategy."
    ),
    "system_prompt": SUBAGENT_PROMPTS["planner"],
    "tools": [load_analysis_data, generate_biomedical_context, search_pubmed_advanced, think_tool],
}
```

**4개 명시적 도구** + DeepAgents 프레임워크가 제공하는 `read_file`/`write_file` (암시적)

---

## 6단계 실행 워크플로우

```
┌─────────────────────────────────────────────────────────────────┐
│  PLANNER 서브에이전트 실행 흐름                                    │
│                                                                 │
│  Step 0: SKILL.md 로딩 (SkillsMiddleware로 주입된 메타데이터 참조)  │
│      │   read_file("skills/biomedical-literature-search/SKILL.md")│
│      ▼                                                          │
│  Step 1: 타겟 설정 읽기                                          │
│      │   read_file("/targets.json")                              │
│      │   → analysis_mode, interest_clusters, data_directory 추출  │
│      ▼                                                          │
│  Step 2: 분석 데이터 로딩                                         │
│      │   load_analysis_data(data_dir)                            │
│      │   ├── 11개 분석 파일 스캔 (5 Part1 + 4 Part2 + 2 Part3)   │
│      │   ├── CSV에서 clusters, celltypes, genes 추출             │
│      │   ├── spatial_search_context 생성 (Part1: 경로+세포, 유전자X)│
│      │   └── lr_search_context 생성 (Part2/3: 유전자+경로+세포)    │
│      │   → write_file("/analysis_summary.md")                    │
│      │   → write_file("/data_path.txt")                          │
│      ▼                                                          │
│  Step 3: 생의학 컨텍스트 생성 (선택적, BioMCP think)               │
│      │   generate_biomedical_context(celltypes, pathways, ...)   │
│      │   ├── BioMCP think #1: 질병 생물학 분석                    │
│      │   ├── BioMCP think #2: 해석 방향 제안                     │
│      │   └── BioMCP think #3: 예상 메커니즘 (L-R, 경로 상호작용)   │
│      │   → write_file("/planner_biomcp_context.md")              │
│      │   ⚠️ BioMCP 미사용 시 graceful skip (비필수)               │
│      ▼                                                          │
│  Step 4: 초기 문헌 검색                                           │
│      │   search_pubmed_advanced(query, max_results=10)           │
│      │   ├── NCBI ESearch → PMID 목록                            │
│      │   └── NCBI EFetch → 논문 XML → {pmid, title, abstract}   │
│      │   → write_file("/planner_literature_context.md")          │
│      │     (알려진 메커니즘, L-R 상호작용, 시그널링 경로, 지식 공백)  │
│      ▼                                                          │
│  Step 5: 분석 커버리지 체크리스트                                   │
│      │   think_tool(reflection=..., iteration=1, max_iterations=1)│
│      │   └── reflection-tool MCP 서버 호출 → 구조화된 평가         │
│      ▼                                                          │
│  Step 6: 해석 가이드 작성                                         │
│      │   write_file("/interpretation_guide.md")                  │
│      │   내용:                                                    │
│      │   ├── 타겟 설정 (모드, 대상, 디렉토리)                      │
│      │   ├── 가용 분석 테이블 (11행, Yes/No + 핵심 관찰)           │
│      │   ├── 문헌 컨텍스트 (논문 수, 메커니즘, L-R, 경로)          │
│      │   ├── BioMCP 질병 생물학 컨텍스트                           │
│      │   ├── 해석 초점 영역 (데이터 기반, 가설 아님!)               │
│      │   ├── 분석 우선순위 (통계적 유의성 기준)                     │
│      │   └── 하류 에이전트별 가이던스                               │
│      ▼                                                          │
│  PLANNER 완료 → 오케스트레이터가 SEARCHER 호출                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 도구 상세

### 1. `load_analysis_data` (Step 2)

**파일**: `tools/data_loader.py`

| 항목 | 설명 |
|------|------|
| 입력 | `data_dir: str` (res/ 디렉토리 경로) |
| 출력 | `available_analyses`, `figures`, `data`, `clusters`, `celltypes`, `genes`, `search_context` |
| 외부 의존성 | 없음 (로컬 pandas) |

**동작**:
- 11개 분석 파일 스캔 (ANALYSIS_FILES 딕셔너리)
- 각 파일: 그림 PNG 존재 확인 + 데이터 CSV 존재 확인
- CSV 메타데이터 추출: cluster IDs, cell types, gene names (LIANA 파일의 ligand/receptor)
- `_extract_search_context()` 호출:
  - `spatial_search_context` (Part 1): `{genes: [], pathways: [...], celltypes: [...]}`
  - `lr_search_context` (Part 2/3): `{genes: [...~352], pathways: [...~64], celltypes: [...~13]}`
- `_MUST_WRITE_FILES` 반환 → PLANNER가 `write_file()`로 저장해야 함

### 2. `generate_biomedical_context` (Step 3)

**파일**: `tools/literature.py` (`_think_with_biomcp_for_planner`)

| 항목 | 설명 |
|------|------|
| 입력 | `celltypes, pathways, available_analyses, disease` |
| 출력 | `{strategic_context: str, success: bool}` |
| 외부 의존성 | BioMCP (localhost:8000) |
| 타임아웃 | 45초 |
| Graceful Degradation | BioMCP 다운 시 `success=False` 반환, 워크플로우 계속 |

**3단계 BioMCP Think Chain** (PLANNER 전용 — 유전자 없음):
1. Disease Biology Analysis: 세포 유형 + 경로의 조직 맥락
2. Interpretation Directions: 유망한 CCI 초점 영역
3. Expected Mechanisms: L-R 쌍, 경로 상호작용, 공간 패턴

### 3. `search_pubmed_advanced` (Step 4)

**파일**: `tools/pubmed_eutils.py`

| 항목 | 설명 |
|------|------|
| 입력 | `query: str`, `max_results: int`, `sort: str`, `min_date`, `max_date` |
| 출력 | `{papers, query_used, total_results, returned_results, source}` |
| 외부 의존성 | NCBI E-utilities REST API |
| Rate Limiting | API 키 있으면 10 req/s, 없으면 3 req/s |

**2단계 API 호출**: ESearch (PMID 목록) → EFetch (논문 XML 파싱)

PLANNER는 다음과 같은 구조화된 쿼리를 사용:
```
'"{disease}"[tiab] AND ("{celltype1}"[tiab] OR "{celltype2}"[tiab])
 AND ("spatial transcriptomics"[tiab] OR "cell interaction"[tiab])'
```

### 4. `think_tool` (Step 5)

**파일**: `tools/think.py`

| 항목 | 설명 |
|------|------|
| 입력 | `reflection: str`, `iteration: int`, `max_iterations: int`, `score_threshold: float` |
| 출력 | `{success, result, iteration, should_continue, parsed_score}` |
| 외부 의존성 | reflection-tool MCP (stdio) |

PLANNER는 `iteration=1, max_iterations=1` (단일 패스, 루프 없음)로 호출.

---

## 입출력 파일 계약

### 읽기 (Input)

| 가상 경로 | Step | 소스 |
|----------|------|------|
| `/targets.json` | 1 | 오케스트레이터가 초기 메시지에서 파싱하여 기록 |
| `skills/biomedical-literature-search/SKILL.md` | 0 | 프로젝트 스킬 디렉토리 |

### 쓰기 (Output)

| 가상 경로 | Step | 소비자 | 내용 |
|----------|------|--------|------|
| `/analysis_summary.md` | 2 | SEARCHER, INTERPRETER | 11개 분석 상태 + 메타데이터 |
| `/data_path.txt` | 2 | SEARCHER, INTERPRETER, REPORTER | 실제 파일시스템 경로 |
| `/planner_biomcp_context.md` | 3 | 내부 참조 | BioMCP 전략적 컨텍스트 (선택적) |
| `/planner_literature_context.md` | 4 | 내부 참조 | 10편 논문 기반 문헌 맥락 |
| `/interpretation_guide.md` | 6 | **모든 하류 에이전트** | 마스터 가이드 문서 |

---

## 인스턴스 생성 경로

### 전체 파이프라인 (Wrapped)

```
graph_builder.py:_get_deep_interpreter_graph_wrapped()
  → create_deep_interpreter_graph_wrapped(provider, data_dir)
    → DeepInterpreterWrapperAgent(model, deep_agent_config)
      → .get_deep_agent() [lazy]
        → create_deep_interpreter_agent(config)  [agent.py]
          → get_subagents()  [subagents/configs.py]
            → SUBAGENT_CONFIGS["planner"] = {name, system_prompt, tools}
          → create_deep_agent(model, tools, subagents, system_prompt, backend, middleware)
```

### 독립 테스트

```
graph_builder.py:_get_planner_subagent_graph()
  → create_subagent_graph("planner", provider)
    → create_react_agent(model, tools=[4개], prompt=PLANNER_PROMPT)
```

```bash
# langgraph dev 실행 후 LangGraph Studio에서 Sub_Planner 선택
langgraph dev
```

---

## 핵심 설계 원칙

### 1. Anti-Hypothesis 설계

프롬프트에서 명시적으로 지시:
> "Your role is to assess available data, gather literature and biomedical context, and produce a data-driven interpretation guide — WITHOUT generating hypotheses."
> "Focus areas should be data-driven directions, NOT predictions to confirm."

### 2. Graceful Degradation

| 도구 | 실패 시 동작 |
|------|-------------|
| `generate_biomedical_context` | BioMCP 다운 → skip, `success=False` |
| `think_tool` | reflection-tool 실패 → `success=False`, 워크플로우 계속 |
| `search_pubmed_advanced` | 네트워크 오류 → 빈 결과 |

### 3. `_MUST_WRITE_FILES` 패턴

`load_analysis_data`가 반환한 파일 내용을 LLM이 `write_file()`로 저장해야 하는 **암시적 계약**. 프롬프트에 의존하는 방식.

### 4. Virtual Filesystem

`FilesystemBackend(virtual_mode=True)` — 모든 파일 I/O가 인메모리, 서브에이전트 간 공유.

---

## 수정 가이드

### 안전한 수정 포인트

| 수정 대상 | 파일 | 위치 |
|----------|------|------|
| 도구 추가 | `subagents/configs.py` | `tools` 리스트 |
| 워크플로우 변경 | `subagents/prompts.py` | `PLANNER_PROMPT` |
| BioMCP think 체인 | `tools/literature.py` | `_think_with_biomcp_for_planner()` |
| 분석 파일 추가 | `tools/data_loader.py` | `ANALYSIS_FILES` 딕셔너리 |

### 위험한 결합 포인트

| 대상 | 위험 | 영향 범위 |
|------|------|----------|
| `/interpretation_guide.md` 파일명 변경 | 모든 하류 에이전트 프롬프트에서 참조 | SEARCHER, INTERPRETER, REPORTER |
| `/data_path.txt` 파일명 변경 | 3개 에이전트에서 읽기 | SEARCHER, INTERPRETER, REPORTER |
| `_MUST_WRITE_FILES` 키 변경 | LLM이 올바른 파일명을 사용하지 못할 수 있음 | SEARCHER |
| MCP 서버 URI 변경 | `tools/mcp_clients.py` 하드코딩 | 모든 MCP 의존 도구 |
