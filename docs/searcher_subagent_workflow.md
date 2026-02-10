# SEARCHER Subagent 상세 분석

> Literature-First 문헌 검색 에이전트 — Anti-Hallucination의 핵심 메커니즘

## 목차

- [개요](#개요)
- [설정](#설정)
- [4-Phase 실행 워크플로우](#4-phase-실행-워크플로우)
- [도구 상세](#도구-상세)
- [search_literature_dynamic 완전 분석](#search_literature_dynamic-완전-분석)
- [스마트 커버리지 계산](#스마트-커버리지-계산)
- [Search Context 비교](#search-context-비교)
- [입출력 파일 계약](#입출력-파일-계약)
- [SKILL.md 워크플로우](#skillmd-워크플로우)
- [핵심 설계 원칙](#핵심-설계-원칙)
- [수정 가이드](#수정-가이드)

---

## 개요

SEARCHER는 4-에이전트 워크플로우의 **두 번째** 서브에이전트입니다.

**핵심 원칙**: **"Literature-First"** — INTERPRETER가 실행되기 **전에** 문헌을 검색하여, INTERPRETER의 **유일한 인용 출처**를 제공합니다. 이것이 전체 시스템의 핵심 anti-hallucination 메커니즘입니다.

**위치**: `src/agents/deep_interpreter/subagents/configs.py` (설정), `subagents/prompts.py` (프롬프트)

---

## 설정

### configs.py

```python
"searcher": {
    "name": "searcher",
    "description": (
        "Literature search agent. Searches PubMed BEFORE interpretation. "
        "Part 1: uses spatial_search_context, outputs /part1_papers.json. "
        "Part 2+3: uses lr_search_context (SHARED), outputs /liana_papers.json ONCE for both parts. "
        "Uses search_literature_dynamic (LLM-powered) with automatic internal fallback. "
        "Papers will be the ONLY citation source for interpreter - this prevents hallucination."
    ),
    "system_prompt": SUBAGENT_PROMPTS["searcher"],
    "tools": [
        load_analysis_data,           # 데이터 로딩 + search context 획득
        search_literature_dynamic,     # PRIMARY: LLM 기반 반복 검색
        search_literature,             # 단일 쿼리 보충 검색
        search_pubmed_advanced,        # E-utilities (MeSH/날짜/출판유형)
        think_tool,                    # 품질 반성(reflection)
    ],
}
```

**5개 도구** + 암시적 `read_file`/`write_file` (DeepAgents 프레임워크)

---

## 4-Phase 실행 워크플로우

```
┌──────────────────────────────────────────────────────────────────────┐
│  SEARCHER 실행 흐름                                                  │
│                                                                      │
│  사전: read_file("skills/biomedical-literature-search/SKILL.md")     │
│       → 5-Phase 검색 전략 가이드 로딩 (Progressive Disclosure)        │
│                                                                      │
│  ═══════════════════════════════════════════════════════════════      │
│  ▶ Part 1 검색 (Spatial Context)                                     │
│  ═══════════════════════════════════════════════════════════════      │
│                                                                      │
│  Phase 1: 컨텍스트 추출                                               │
│      │  read_file("/data_path.txt") → 실제 데이터 경로                │
│      │  load_analysis_data(data_dir)                                 │
│      │  → spatial_search_context:                                    │
│      │    { genes: [],           ← Part 1은 유전자 분석 없음!         │
│      │      pathways: [...],     ← Decoupler + MISTy 경로            │
│      │      celltypes: [...] }   ← 세포 유형 조성                    │
│      │  write_file("/part1_search_context.json")                     │
│      ▼                                                               │
│  Phase 2: 문헌 검색                                                   │
│      │  search_literature_dynamic(                                   │
│      │    genes=[],                  ← 빈 배열                       │
│      │    pathways=[우선순위 4-8개],                                   │
│      │    celltypes=[...],                                           │
│      │    disease="breast cancer",                                   │
│      │    max_results=40,                                            │
│      │    target_pathway_coverage=0.5                                │
│      │  )                                                            │
│      ▼                                                               │
│  Phase 3: 반성 & 품질 루프                                            │
│      │  think_tool(reflection=커버리지 분석)                          │
│      │  기준: papers ≥ 25, pathway_coverage ≥ 50%                    │
│      │  미달 시 → search_literature()로 타겟 보충 (최대 2회)          │
│      ▼                                                               │
│  Phase 4: 출력 기록                                                   │
│      │  write_file("/part1_papers.json")                             │
│      │  { papers: [...], coverage: {...},                            │
│      │    search_iterations: N, search_method: "dynamic"|"fallback" }│
│      ▼                                                               │
│  ═══════════════════════════════════════════════════════════════      │
│  ▶ Part 2+3 검색 (L-R Context, 공유)                                 │
│  ═══════════════════════════════════════════════════════════════      │
│                                                                      │
│  Phase 1: lr_search_context 사용                                     │
│      │  { genes: [...~352개], pathways: [...~64개],                   │
│      │    celltypes: [...~13개] }                                     │
│      ▼                                                               │
│  Phase 2: search_literature_dynamic(                                 │
│      │    genes=[우선순위 10-15개],  ← 352개 전체가 아님!             │
│      │    target_gene_coverage=0.6,                                  │
│      │    target_pathway_coverage=0.5                                │
│      │  )                                                            │
│      ▼                                                               │
│  Phase 3-4: 동일한 반성 + 출력                                        │
│      │  write_file("/liana_papers.json")  ← Part 2+3 공유!           │
│      ▼                                                               │
│  SEARCHER 완료 → 오케스트레이터가 INTERPRETER 호출                     │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 도구 상세

### 도구 의사결정 매트릭스

| 상황 | 사용 도구 |
|------|----------|
| 초기 종합 검색 | `search_literature_dynamic` (필수) |
| 특정 유전자 갭 보충 | `search_literature` (단일 쿼리) |
| MeSH 용어 정밀 검색 | `search_pubmed_advanced` |
| 최근 논문만 필요 | `search_pubmed_advanced` (날짜 필터) |
| 체계적 리뷰 검색 | `search_pubmed_advanced` (출판유형) |
| 커버리지 반성 | `think_tool` |

### 1. `search_literature_dynamic` (PRIMARY)

자세한 내용은 아래 [search_literature_dynamic 완전 분석](#search_literature_dynamic-완전-분석) 참조.

### 2. `search_literature`

**파일**: `tools/literature.py`

```python
search_literature(
    genes: list[str],       # 최대 5개 유전자
    disease: str,
    keywords: list[str],    # 최대 5개 키워드
    max_results: int = 15,
) -> list[dict]             # [{pmid, title, abstract}]
```

BioMCP `article_searcher` 단일 쿼리 래퍼. 타겟 갭 보충용.

### 3. `search_pubmed_advanced`

**파일**: `tools/pubmed_eutils.py`

```python
search_pubmed_advanced(
    query: str,             # PubMed 원시 쿼리: "VEGFA[tiab] AND cancer[mh]"
    max_results: int = 20,
    sort: str = "relevance",
    min_date: str = "",
    max_date: str = "",
) -> dict
```

NCBI E-utilities REST API 직접 사용. MeSH, 날짜 범위, 출판 유형 필터 지원.

### 4. `think_tool`

**파일**: `tools/think.py`

reflection-tool MCP 서버 호출. 커버리지 반성 및 품질 평가.

---

## search_literature_dynamic 완전 분석

### 함수 시그니처

```python
@tool
def search_literature_dynamic(
    genes: list[str],                    # 유전자 기호
    pathways: list[str],                 # 경로명
    celltypes: list[str],                # 세포유형
    disease: str,                        # 질병
    max_results: int = 40,               # 최대 논문 수
    target_gene_coverage: float = 0.6,   # 60% 유전자 커버리지 목표
    target_pathway_coverage: float = 0.5,# 50% 경로 커버리지 목표
    max_iterations: int = 3,             # 최대 반복 횟수
) -> dict
```

**반환값**:
```python
{
    "papers": [...],           # [{pmid, title, abstract, query_type, iteration}]
    "generated_queries": [...],# LLM이 생성한 모든 쿼리
    "coverage": {...},         # 최종 커버리지 메트릭
    "think_success": bool,     # BioMCP 전략 사고 성공 여부
    "iterations": int,         # 수행된 반복 횟수
    "coverage_history": [...]  # 각 반복별 커버리지 스냅샷
}
```

### 전체 실행 흐름

```
┌────────────────────────────────────────────────────────────────────┐
│  search_literature_dynamic_async 내부 흐름                          │
│                                                                    │
│  Step 0: BioMCP 전략적 사고 (1회만)                                 │
│  ┌── _think_with_biomcp (3단계) ──────────────────────────────┐    │
│  │  Thought 1: 맥락 분석 (유전자+경로+세포+질병)               │    │
│  │  Thought 2: 검색 키워드 도출 & 생물학적 관련성 우선순위       │    │
│  │  Thought 3: 예상 생물학적 메커니즘                           │    │
│  │  → strategic_context (실패 시 빈 문자열)                     │    │
│  └──────────────────────────────────────────────────────────────┘    │
│       │                                                            │
│       ▼                                                            │
│  llm = create_llm()  ← 쿼리 생성용 (기본: gpt-4.1-mini)          │
│                                                                    │
│  ┌─── Iteration 0 (초기 광범위 검색) ────────────────────────────┐ │
│  │                                                                │ │
│  │  1. LLM 쿼리 생성 (LITERATURE_QUERY_GENERATION_PROMPT)         │ │
│  │     → 6-9개 JSON 쿼리 배열                                    │ │
│  │     ├── 유전자 중심 2-3개                                      │ │
│  │     ├── 경로 중심 2개                                          │ │
│  │     ├── 세포유형 중심 1-2개                                    │ │
│  │     └── 통합 쿼리 1-2개                                       │ │
│  │                                                                │ │
│  │  2. _parse_llm_queries → _validate_generated_queries           │ │
│  │     (JSON 추출, 필드 정규화, genes[:5] 제한)                    │ │
│  │                                                                │ │
│  │  3. 쿼리 분류 & 슬롯 할당                                      │ │
│  │     gene_queries (genes 필드 있음) → 60% 슬롯                  │ │
│  │     pathway_queries (genes 없음) → 40% 슬롯                   │ │
│  │                                                                │ │
│  │  4. _search_with_biomcp 실행 (순차)                            │ │
│  │     → BioMCP article_searcher → PMID                          │ │
│  │     → BioMCP article_getter (병렬) → title + abstract         │ │
│  │     → seen_pmids 중복 제거                                     │ │
│  │                                                                │ │
│  │  ⚠️ LLM 실패 시 → _execute_fixed_strategy_search_async        │ │
│  └────────────────────────────────────────────────────────────────┘ │
│       │                                                            │
│       ▼                                                            │
│  ┌─── Iteration 1+ (갭 필링) ────────────────────────────────────┐ │
│  │                                                                │ │
│  │  1. _calculate_coverage (스마트 패턴 매칭)                      │ │
│  │  2. 조기 종료: gene ≥ 60% AND pathway ≥ 50% → STOP            │ │
│  │  3. missing_genes/pathways 계산                                │ │
│  │  4. GAP_FILLING_QUERY_PROMPT → 3-5개 타겟 쿼리                 │ │
│  │  5. 실행 + 중복 제거                                           │ │
│  └────────────────────────────────────────────────────────────────┘ │
│       │                                                            │
│       ▼                                                            │
│  최종: all_papers[:max_results] + final_coverage                   │
└────────────────────────────────────────────────────────────────────┘
```

### 고정 전략 폴백 (4개 하드코딩)

| # | 전략 | 쿼리 구성 |
|---|------|----------|
| 1 | Gene + Disease | `genes[:5]` + disease |
| 2 | Pathway + Cell type | `pathways[:3]` + `celltypes[:3]` as keywords |
| 3 | L-R Interaction | `genes[:4]` + "ligand receptor", "cell-cell interaction" |
| 4 | Spatial Context | disease + "spatial transcriptomics", "tumor microenvironment" + `celltypes[:3]` |

### BioMCP 검색 실행 (`_search_with_biomcp`)

```
_search_with_biomcp(genes, diseases, keywords, page_size)
    ├── get_biomcp_tools(url) → 캐시된 MCP 도구
    ├── article_searcher.ainvoke({genes, diseases, keywords, page_size})
    ├── _parse_pmids(result) → PMID 추출
    ├── asyncio.gather(*[article_getter.ainvoke({pmid}) ...])  ← 병렬
    └── _parse_article(result) → {pmid, title, abstract}
```

### 에러 처리 계층

| 레벨 | 실패 지점 | 동작 |
|------|----------|------|
| 1 | BioMCP think | `strategic_context=""`, 검색 계속 |
| 2 | LLM 쿼리 생성 (Iteration 0) | 고정 4-전략 폴백 |
| 3 | LLM 쿼리 생성 (Iteration 1+) | 루프 중단, 기존 논문 유지 |
| 4 | 개별 BioMCP 검색 | 경고 로깅, 다음 쿼리 계속 |
| 5 | BioMCP 서버 연결 | 캐시 무효화, 빈 결과 |
| 6 | article_getter 없음 | PMID만 스텁 논문 생성 |
| 7 | 전체 타임아웃 (300s) | 예외 전파 |

---

## 스마트 커버리지 계산

### `_calculate_coverage` 알고리즘

단순 문자열 매칭이 아닌 **다층 패턴 자동 생성**:

#### 유전자 패턴 (`_generate_gene_patterns`)

```
입력: "ADAM10"
  ├── 대소문자: adam10, ADAM10, Adam10
  ├── 문자/숫자 분리: letters="ADAM", numbers="10"
  ├── 구분자: adam-10, adam_10, adam 10
  ├── 패밀리 참조: adam (2자리 이하 숫자)
  ├── 하이픈: ADAM-10 ↔ ADAM10
  ├── 그리스문자: TGFbeta ↔ TGFβ (양방향)
  └── 정적 별칭: SPECIAL_GENE_ALIASES
      CDH1 → [E-CADHERIN, ECAD]
      ERBB2 → [HER2, NEU]
      SNAI1 → [SNAIL]

단어 경계: 3글자 이하 → \bAR\b (오탐 방지)
```

#### 경로 패턴 (`_generate_pathway_patterns`)

```
입력: "Androgen;MAPK"
  ├── 세미콜론 분리: ["Androgen", "MAPK"]
  ├── 키워드 확장 (PATHWAY_KEYWORDS):
  │   androgen → [androgen receptor, ar signaling]
  │   mapk → [erk signaling, ras/mapk, mek/erk, erk1, erk2]
  └── 그리스문자: beta ↔ β
```

#### 주요 별칭 딕셔너리

```python
SPECIAL_GENE_ALIASES = {
    "CDH1": ["E-CADHERIN", "ECAD"],
    "ERBB2": ["HER2", "NEU"],
    "ACKR3": ["CXCR7"],
    "SNAI1": ["SNAIL"],
    "SNAI2": ["SLUG"],
    "VEGFA": ["VEGF"],
    "TNF": ["TNFA"],
    "CXCL12": ["SDF1"],
}

PATHWAY_KEYWORDS = {
    "mapk": ["erk signaling", "ras/mapk", "mek/erk"],
    "pi3k": ["pi3k/akt", "akt signaling", "mtor"],
    "nfkb": ["nf-kb", "nuclear factor kappa"],
    "tgf": ["tgf-beta", "tgfb", "smad"],
    "wnt": ["beta-catenin", "canonical wnt"],
}
```

#### 커버리지 출력

```python
{
    "genes_covered": [...],
    "genes_matched_by": {"CDH1": "e-cadherin"},
    "genes_coverage_pct": 66.7,  # 0-100 스케일
    "genes_missing": [...],
    "pathways_covered": [...],
    "pathways_coverage_pct": 50.0,
    "celltypes_covered": [...],
    "total_papers": 35,
}
```

---

## Search Context 비교

| 항목 | `spatial_search_context` (Part 1) | `lr_search_context` (Part 2+3) |
|------|----------------------------------|-------------------------------|
| **genes** | `[]` (빈 배열) | ~352개 (ligand + receptor) |
| **pathways** | Decoupler + MISTy | LIANA progeny + Decoupler |
| **celltypes** | 세포 유형 조성 | LIANA L-R cell types |
| **출력 파일** | `/part1_papers.json` | `/liana_papers.json` (공유) |
| **커버리지 목표** | pathway ≥ 50% | gene ≥ 60%, pathway ≥ 50% |

**Part 2+3이 공유하는 이유**: 둘 다 동일한 LIANA L-R 상호작용 데이터를 사용하므로 `lr_search_context`가 동일합니다.

---

## 입출력 파일 계약

### 읽기 (Input)

| 가상 경로 | 소스 | 용도 |
|----------|------|------|
| `/data_path.txt` | PLANNER | 실제 데이터 디렉토리 경로 |
| `skills/.../SKILL.md` | 프로젝트 | 검색 워크플로우 가이드 |

### 쓰기 (Output)

| 가상 경로 | 소비자 | 내용 |
|----------|--------|------|
| `/part1_search_context.json` | 내부 참조 | 추출된 Part 1 컨텍스트 |
| `/lr_search_context.json` | 내부 참조 | 추출된 Part 2+3 컨텍스트 |
| `/part1_papers.json` | **INTERPRETER** (Part 1 유일한 인용 출처) | 논문 + 커버리지 |
| `/liana_papers.json` | **INTERPRETER** (Part 2+3 유일한 인용 출처) | 논문 + 커버리지 |

---

## SKILL.md 워크플로우

`skills/biomedical-literature-search/SKILL.md`에 정의된 4-Phase 가이드:

| Phase | 내용 | 도구 |
|-------|------|------|
| 1. Extract Context | `/data_path.txt` 읽기 → `load_analysis_data` → search context 추출 | `load_analysis_data` |
| 2. Search Literature | `search_literature_dynamic` (필수) + 갭 보충 | `search_literature_dynamic`, `search_pubmed_advanced` |
| 3. Reflect | `think_tool`로 커버리지 확인, max 3회 | `think_tool`, `search_literature` |
| 4. Write Output | `write_file` → `/partN_papers.json` | `write_file` |

**품질 기준**: papers ≥ 25, gene coverage ≥ 60%, pathway coverage ≥ 50%

---

## 핵심 설계 원칙

### 1. Faithful Writing Rule

> 도구가 반환한 papers 배열을 **절대 잘라내거나 재계산하지 않고** 그대로 파일에 기록

### 2. Gene 우선순위화

352개 전체가 아닌 10-15개만 선별하여 검색 (컨텍스트 오버플로우 방지)

### 3. Graceful Degradation

BioMCP 다운 → 고정 전략 폴백, LLM 실패 → 고정 전략 폴백

### 4. Progressive Disclosure

SKILL.md는 런타임에 `read_file`로 로딩 (프롬프트 토큰 절약)

---

## 수정 가이드

### 안전한 수정 포인트

| 수정 대상 | 파일 |
|----------|------|
| 커버리지 목표 변경 | `tools/literature.py` (`search_literature_dynamic` 기본 파라미터) |
| 유전자 별칭 추가 | `tools/literature.py` (`SPECIAL_GENE_ALIASES`) |
| 경로 키워드 추가 | `tools/literature.py` (`PATHWAY_KEYWORDS`) |
| LLM 프롬프트 변경 | `prompts.py` (`LITERATURE_QUERY_GENERATION_PROMPT`, `GAP_FILLING_QUERY_PROMPT`) |
| SKILL.md 수정 | `skills/biomedical-literature-search/SKILL.md` |

### 위험한 결합 포인트

| 대상 | 위험 |
|------|------|
| `/part1_papers.json`, `/liana_papers.json` 파일명 | INTERPRETER, REPORTER 프롬프트에서 참조 |
| search_context 필드명 | `data_loader.py`, SEARCHER 프롬프트, SKILL.md |
| papers JSON 스키마 | INTERPRETER, REPORTER, RAG 도구가 소비 |
