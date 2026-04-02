# Literature Search Strategy (search_literature_dynamic)

> 최종 업데이트: 2026-03-25
> 버전: v2.1 (BioMCP Think 제거, 파라미터 업데이트)

---

## 1. 개요

### 1.1 목적
CCI (Cell-Cell Interaction) 분석 결과 해석을 위한 **LLM 기반 동적 문헌 검색** 시스템.
분석에서 추출된 유전자, 패스웨이, 세포 타입을 기반으로 관련 논문을 자동 검색.

### 1.2 핵심 특징

| 특징 | 설명 |
|------|------|
| **LLM Query Generation** | GPT/Gemini가 맥락 기반 검색 쿼리 생성 |
| **60/40 Slot Allocation** | Gene 60%, Pathway 40% 균형 잡힌 커버리지 |
| **Iterative Gap-filling** | 커버리지 미달 시 추가 검색 (실제로 거의 미사용) |
| **BioMCP 자동 Alias 처리** | ACKR3 검색 시 CXCR7 논문도 자동 포함 |
| **Smart Pattern Matching** | 대소문자, 하이픈 변형 자동 처리 |

---

## 2. 전체 아키텍처

### 2.1 Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Iteration 0: Initial Search                                                  │
│                                                                              │
│   ┌──────────────────────┐    ┌──────────────────────────────────────────┐  │
│   │ LLM Query Generation │    │ Query Distribution                        │  │
│   │ - 5-7 queries        │ →  │ - Gene queries: 최소 3개 (genes 필드 있음) │  │
│   │ - JSON array output  │    │ - Pathway queries: 최소 2개 (keywords)    │  │
│   └──────────────────────┘    └──────────────────────────────────────────┘  │
│                                      │                                       │
│                                      ▼                                       │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │ 60/40 Slot Allocation                                                │   │
│   │                                                                      │   │
│   │   Gene Queries (60%)              Pathway Queries (40%)              │   │
│   │   ┌─────────────────┐             ┌─────────────────┐                │   │
│   │   │ 18 slots        │             │ 12 slots        │                │   │
│   │   │ ~6 papers/query │             │ ~4 papers/query │                │   │
│   │   └─────────────────┘             └─────────────────┘                │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                      │                                       │
│                                      ▼                                       │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │ BioMCP article_searcher 실행                                         │   │
│   │ - Gene queries 먼저 실행                                             │   │
│   │ - Pathway queries 실행                                               │   │
│   │ - PMID 기반 중복 제거                                                │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
                        ┌─────────────────────────┐
                        │ Coverage 계산            │
                        │ - Gene coverage %        │
                        │ - Pathway coverage %     │
                        └─────────────────────────┘
                                      │
                         ┌────────────┴────────────┐
                         │                         │
                    gene ≥ 60%                gene < 60%
                    pathway ≥ 50%             OR pathway < 50%
                         │                         │
                         ▼                         ▼
                    ┌────────┐         ┌─────────────────────────┐
                    │ 완료    │         │ Iteration 1-2:          │
                    │ (조기   │         │ Gap-filling Search      │
                    │  종료)  │         │ - Missing genes 파악     │
                    └────────┘         │ - 타겟 쿼리 생성          │
                                       │ - 추가 검색               │
                                       └─────────────────────────┘
```

### 2.2 컴포넌트 상세

```
search_literature_dynamic()
├── create_llm()                     # LLM 인스턴스 생성
│
├── [Iteration Loop]
│   ├── _calculate_coverage()        # 현재 커버리지 계산
│   │   ├── _generate_gene_patterns()    # 유전자 패턴 생성
│   │   └── _generate_pathway_patterns() # 패스웨이 패턴 생성
│   │
│   ├── LITERATURE_QUERY_GENERATION_PROMPT.format()  # 초기 검색
│   │   OR
│   │   GAP_FILLING_QUERY_PROMPT.format()            # 갭 필링
│   │
│   ├── llm.invoke()                 # LLM 쿼리 생성
│   │
│   ├── _parse_llm_queries()         # JSON 파싱
│   │
│   ├── _validate_generated_queries() # 쿼리 검증
│   │
│   └── _search_with_biomcp()        # BioMCP 검색 실행
│
└── return {papers, queries, coverage, ...}
```

---

## 3. 핵심 컴포넌트 상세

### 3.1 LLM Query Generation

**프롬프트 구조:**
```
LITERATURE_QUERY_GENERATION_PROMPT
├── 역할: biomedical literature search expert
├── 입력 컨텍스트
│   ├── genes: {genes}
│   ├── pathways: {pathways}
│   ├── celltypes: {celltypes}
│   └── disease: {disease}
├── Query Generation Guidelines
│   ├── Gene-centric queries (최소 3개)
│   ├── Pathway-centric queries (최소 2개)
│   └── Integrated queries (1-2개)
└── Output Format: JSON array
```

**LLM 출력 예시:**
```json
[
  {"genes": ["ADAM10", "ADAM17"], "diseases": ["breast cancer"], "keywords": ["metalloprotease", "shedding"]},
  {"genes": ["ACKR3"], "diseases": ["breast cancer"], "keywords": ["chemokine receptor", "cell migration"]},
  {"genes": ["ACVR2A", "ACVR2B"], "diseases": ["breast cancer"], "keywords": ["TGF-beta receptor"]},
  {"genes": [], "diseases": ["breast cancer"], "keywords": ["androgen signaling", "hormone receptor"]},
  {"genes": [], "diseases": ["breast cancer"], "keywords": ["MAPK pathway", "ERK signaling", "PI3K/AKT"]}
]
```

### 3.2 60/40 Slot Allocation

```python
remaining_slots = max_results - len(all_papers)  # 예: 30

# 쿼리 분류
gene_queries = [q for q in queries if q.get("genes")]      # genes 필드 있음
pathway_queries = [q for q in queries if not q.get("genes")]  # genes 없음

# 슬롯 배분
gene_slots = int(remaining_slots * 0.6)      # 18개 (60%)
pathway_slots = remaining_slots - gene_slots  # 12개 (40%)

# 쿼리당 결과 수
gene_results_per_query = max(5, gene_slots // len(gene_queries))      # ~6개
pathway_results_per_query = max(3, pathway_slots // len(pathway_queries))  # ~4개
```

**실행 순서:**
1. Gene queries 먼저 실행 (60% 슬롯)
2. Pathway queries 실행 (40% 슬롯)
3. PMID 기반 중복 제거

### 3.3 Smart Pattern Matching (Coverage 계산)

```python
def _generate_gene_patterns(gene: str) -> list[str]:
    """
    ADAM10 → ["adam10", "adam-10", "adam 10", "ADAM10", "Adam10"]
    IL-6   → ["il6", "il-6", "IL6", "IL-6"]
    """
    patterns = set()

    # 1. 대소문자 변형
    patterns.add(gene.lower())
    patterns.add(gene.upper())
    patterns.add(gene.capitalize())  # Mouse: Adam10

    # 2. 구분자 변형 (ADAM10 → adam-10, adam 10)
    match = re.match(r'^([A-Za-z]+)(\d+)(.*)$', gene)
    if match:
        letters, numbers, suffix = match.groups()
        for sep in ['', '-', ' ', '_']:
            patterns.add(f"{letters.lower()}{sep}{numbers}")

    # 3. 하이픈 처리
    if '-' in gene:
        patterns.add(gene.replace('-', '').lower())

    # 4. 특수 Alias (하드코딩된 것만)
    SPECIAL_ALIASES = {
        "ACKR3": ["CXCR7"],
        "CDH1": ["E-CADHERIN"],
        ...
    }

    return list(patterns)
```

**Pathway 패턴:**
```python
def _generate_pathway_patterns(pathway: str) -> list[str]:
    """
    Androgen;MAPK → ["androgen", "mapk", "erk signaling", "ar signaling"]
    """
    PATHWAY_KEYWORDS = {
        "androgen": ["androgen receptor", "ar signaling"],
        "mapk": ["erk signaling", "ras/mapk", "mek/erk"],
        "nfkb": ["nf-kb", "nf-kappab", "nuclear factor kappa"],
        ...
    }
```

### 3.4 BioMCP 자동 Alias 처리

> **핵심**: BioMCP article_searcher가 내부적으로 유전자 alias를 자동 처리

```
ACKR3 검색 요청
    ↓
BioMCP article_searcher 내부:
    ACKR3 → [ACKR3, CXCR7, CMKOR1, ...]
    ↓
PubMed 검색: ACKR3 OR CXCR7 OR CMKOR1
    ↓
CXCR7 논문도 결과에 포함
```

**테스트 결과:**
```
ACKR3 검색 → CXCR7 논문 반환 ✓
CXCR7 검색 → 동일 논문 반환 ✓
```

따라서 **alias pre-fetch 로직 제거** (v2.0에서 단순화)

---

## 4. Iterative Gap-filling

### 4.1 트리거 조건

```python
if iteration > 0:
    if gene_coverage >= 0.6 and pathway_coverage >= 0.5:
        break  # 조기 종료
    if len(all_papers) >= max_results:
        break  # 최대 결과 도달
```

### 4.2 Gap-filling 쿼리 생성

```python
GAP_FILLING_QUERY_PROMPT.format(
    missing_genes=", ".join(missing_genes),    # 커버되지 않은 유전자
    missing_pathways=", ".join(missing_pathways),  # 커버되지 않은 패스웨이
    disease=disease,
    covered_genes=", ".join(covered_genes),    # 이미 커버된 것 (재검색 방지)
    covered_pathways=", ".join(covered_pathways),
)
```

### 4.3 실제 사용 빈도

```
테스트 결과 (res/ 데이터):
- Iteration 0: 30 papers, genes=60%, pathways=100%
- 목표 달성 → 조기 종료
- Gap-filling 미실행
```

> **참고**: 대부분의 경우 1회 검색으로 목표 달성. Gap-filling은 보험용.

---

## 5. 입출력 구조

### 5.1 입력 파라미터

```python
def search_literature_dynamic(
    genes: list[str],              # 유전자 목록 (예: ["ADAM10", "ACKR3"])
    pathways: list[str],           # 패스웨이 목록 (예: ["Androgen", "MAPK"])
    celltypes: list[str],          # 세포 타입 (예: ["Tumor", "Fibroblast"])
    disease: str,                  # 질병 컨텍스트 (예: "breast cancer")
    max_results: int = 30,         # 최대 논문 수
    target_gene_coverage: float = 0.6,     # 목표 유전자 커버리지 (60%)
    target_pathway_coverage: float = 0.5,  # 목표 패스웨이 커버리지 (50%)
    max_iterations: int = 3,       # 최대 반복 횟수
    enforce_disease_match: bool = True,    # 질병 관련성 후필터링
    output_path: str = "",         # 결과 파일 자동저장 경로
    data_dir: str = "",            # 데이터 디렉토리 (env var 우선)
    rerank_mode: str = "off",      # "off" 또는 "llm" (2차 리랭킹)
    rerank_top_n: int = 12,        # 리랭킹 대상 최대 수
    rerank_min_confidence: float = 0.70,   # 리랭킹 최소 신뢰도
    llm_provider: str = "",        # LLM 프로바이더 오버라이드 (예: "openai")
    sort_by_journal_quality: bool = True,  # SJR 저널 품질 정렬
    coverage_weighted_sort: bool = False,  # 커버리지 가중 정렬
    query_cache: list[dict] | None = None, # 캐시된 쿼리 재사용
    record_queries: bool = False,  # 생성된 쿼리 기록 여부
) -> dict:
```

### 5.2 출력 구조

```python
{
    "papers": [
        {
            "pmid": "38317965",
            "title": "New insight into the role of ADAM protease family...",
            "abstract": "...",
            "query_index": 0,       # 어떤 쿼리에서 나왔는지
            "iteration": 0,         # 몇 번째 iteration
            "query_type": "gene"    # gene 또는 pathway
        },
        ...
    ],
    "generated_queries": [
        {"genes": ["ADAM10"], "diseases": ["breast cancer"], "keywords": [...]},
        ...
    ],
    "coverage": {
        "genes_covered": ["ADAM10", "ADAM17", ...],
        "genes_coverage_pct": 60.0,
        "pathways_covered": ["Androgen", "MAPK", ...],
        "pathways_coverage_pct": 100.0,
        "celltypes_covered": [...],
        "total_papers": 30
    },
    "think_success": True,          # backward-compat 필드 (항상 True)
    "iterations": 2,                # 실행된 iteration 수
    "coverage_history": [           # iteration별 커버리지 추이
        {"iteration": 0, "papers": 0, "gene_coverage": 0.0, "pathway_coverage": 0.0},
        {"iteration": 1, "papers": 30, "gene_coverage": 0.6, "pathway_coverage": 1.0},
        {"iteration": "final", ...}
    ]
}
```

---

## 6. 테스트 결과

### 6.1 테스트 환경

```
Input:
- Genes: 10개 (ACKR3, ACTR2, ACVR1B, ACVR2A, ACVR2B, ADAM10, ADAM12, ADAM15, ADAM17, ADAM9)
- Pathways: 5개 (Androgen, Androgen;Estrogen, Androgen;MAPK, Androgen;NFkB, Androgen;PI3K)
- Cell types: 5개
- Disease: breast cancer
- max_results: 30
```

### 6.2 결과

| 항목 | 결과 | 목표 |
|------|------|------|
| **Gene Coverage** | 60-80% | ≥60% |
| **Pathway Coverage** | 100% | ≥50% |
| **Papers** | 30 | 30 |
| **Iterations** | 1-2 (조기 종료) | max 3 |
| **API Calls** | ~8 | - |

### 6.3 생성된 쿼리 예시

```json
[
  {"genes": ["ACKR3", "ACTR2", "ACVR1B"], "diseases": ["breast cancer"], "keywords": ["chemokine receptor", "TGF-beta receptor"]},
  {"genes": ["ADAM10", "ADAM12", "ADAM15", "ADAM17", "ADAM9"], "diseases": ["breast cancer"], "keywords": ["metalloprotease", "shedding"]},
  {"genes": ["ACVR2A", "ACVR2B"], "diseases": ["breast cancer"], "keywords": ["activin receptor", "TGF-beta signaling"]},
  {"genes": [], "diseases": ["breast cancer"], "keywords": ["androgen receptor signaling", "estrogen receptor", "hormone signaling"]},
  {"genes": [], "diseases": ["breast cancer"], "keywords": ["MAPK pathway", "ERK signaling", "PI3K/AKT", "NF-kB pathway"]}
]
```

---

## 7. 코드 위치

| 파일 | 역할 |
|------|------|
| `src/agents/deep_interpreter/tools/literature.py` | 메인 구현 |
| `src/agents/deep_interpreter/prompts.py` | 프롬프트 템플릿 |
| `test_searcher.py` | 테스트 스크립트 |

### 7.1 주요 함수

```python
# Public API
search_literature_dynamic()          # Sync 버전 (@tool)
search_literature_dynamic_async()    # Async 버전
generate_biomedical_context()        # PLANNER용 BioMCP think (@tool, 별도 기능)

# Internal
_search_with_biomcp()                # BioMCP article_searcher 실행
_parse_llm_queries()                 # LLM 응답 JSON 파싱
_validate_generated_queries()        # 쿼리 유효성 검증
_calculate_coverage()                # 커버리지 계산
_generate_gene_patterns()            # 유전자 패턴 생성
_generate_pathway_patterns()         # 패스웨이 패턴 생성
_compute_paper_coverage_score()      # 논문별 커버리지 점수
_greedy_coverage_sort()              # 커버리지 가중 정렬
_think_with_biomcp_for_planner()     # PLANNER용 BioMCP think (generate_biomedical_context 내부)
```

---

## 8. 버전 히스토리

| 버전 | 날짜 | 변경 사항 |
|------|------|----------|
| v1.0 | 2025-01-28 | 초기 구현 (search_literature_dynamic) |
| v1.5 | 2025-01-28 | Iterative gap-filling, 60/40 allocation 추가 |
| v2.0 | 2025-01-28 | Alias pre-fetch 제거 (BioMCP 자동 처리) |
| **v2.1** | **2026-03-25** | **BioMCP Think (Step 0) dead code 제거, 파라미터 업데이트 (rerank, auto-save, query_cache 등)** |

### v2.0 단순화 내용

**제거된 코드:**
```python
# Step 0.5: Pre-fetch aliases (제거됨)
# for gene in genes[:10]:
#     _fetch_gene_aliases_sync(gene)
# alias_info_for_initial_prompt = "..."
```

**이유:**
- BioMCP article_searcher가 내부적으로 alias 처리
- ACKR3 검색 → CXCR7 논문도 자동 반환
- 불필요한 gene_getter API 호출 제거
- ~36줄 코드 감소

### v2.1 단순화 내용

**제거된 코드:**
```python
# Step 0: BioMCP Think (전략 수립) — dead code 제거
# async def _think_with_biomcp(genes, pathways, celltypes, disease, biomcp_url)
# def _execute_biomcp_think(genes, pathways, celltypes, disease)
```

**이유:**
- `search_literature_dynamic_async`에서 이미 호출하지 않고 있었음 (`think_success = True` 하드코딩)
- LLM Query Generation이 직접 맥락을 처리하므로 별도 think 단계 불필요
- ~105줄 dead code 제거
- 참고: `_think_with_biomcp_for_planner()`는 PLANNER용 별도 함수로 유지됨

**추가된 파라미터 문서화:**
- `enforce_disease_match`: 질병 관련성 후필터링
- `output_path` / `data_dir`: 결과 자동 저장
- `rerank_mode` / `rerank_top_n` / `rerank_min_confidence`: LLM 리랭킹
- `sort_by_journal_quality` / `coverage_weighted_sort`: 정렬 옵션
- `query_cache` / `record_queries`: 쿼리 캐시 및 재현성

---

## 9. 향후 개선 고려사항

1. **Iteration 제거 고려**: 1회 검색으로 목표 달성하므로 gap-filling 불필요할 수 있음
2. **쿼리 수 증가**: gap-filling 대신 초기 쿼리 수를 늘려 커버리지 확보
3. **병렬 검색**: asyncio.gather로 쿼리 병렬 실행
4. **Part별 특화**: Part 1/2/3에 맞는 특화 프롬프트
