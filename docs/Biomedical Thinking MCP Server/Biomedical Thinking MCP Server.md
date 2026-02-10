# Biomedical Thinking MCP Server - Comprehensive Analysis

## Context

Biomedical Thinking MCP Server는 DeepMAST의 Deep Interpreter Agent가 **복잡한 생물의학 질문을 구조화된 PubMed 검색 쿼리로 변환**하기 위해 사용하는 외부 MCP 서버이다. LLM 호출 없이 순수 규칙 기반(regex + dictionary)으로 동작하며, 4-stage 파이프라인 구조를 갖는다.

---

## 1. 서버 개요

| 항목 | 내용 |
|------|------|
| **위치** | `~/Dropbox/Metadata/mcp/biomedical_thinking/` |
| **프레임워크** | FastMCP (`fastmcp`) |
| **전송** | stdio (subprocess로 실행) |
| **LLM 의존성** | 없음 (순수 규칙 기반) |
| **등록 도구** | 4개 MCP tools |
| **테스트** | 44개 (모두 mock, 네트워크 불필요) |

---

## 2. 4-Stage Pipeline Architecture

```
사용자 질문 (e.g., "Does TGFB1-TGFBR2 drive EMT in breast cancer fibroblasts?")
    │
    ▼
┌──────────────────────────────────────────┐
│  Stage 1: analyze_and_decompose          │
│  - Entity extraction (regex + dict)      │
│  - Question classification (5 types)     │
│  - Complexity assessment (3 levels)      │
│  - Sub-question decomposition            │
│  - Strategy suggestion                   │
│  Output: entities, sub_questions,        │
│          question_type, strategy          │
└──────────────────┬───────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────┐
│  Stage 2: expand_entities                │
│  - Gene alias 확장 (로컬 80개+ dict)     │
│  - MeSH term 매핑 (로컬 → API fallback) │
│  - Cell type/Disease subtype 확장        │
│  - PubMed query fragment 생성            │
│  Output: expanded entities,              │
│          pubmed_query_fragments           │
└──────────────────┬───────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────┐
│  Stage 3: build_search_queries           │
│  - Fragment 조합 (focus별 AND 규칙)      │
│  - 5가지 전략 중 선택 적용               │
│  - Iteration roadmap 생성               │
│  Output: search_queries (PubMed-ready),  │
│          iteration_roadmap               │
└──────────────────┬───────────────────────┘
                   │
    ┌──── 실제 PubMed 검색 (서버 외부) ────┐
    │  search_pubmed_advanced(query)        │
    └──────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────┐
│  Stage 4: evaluate_search_results        │
│  - Sub-question 커버리지 평가            │
│  - Entity 커버리지 (alias variant 포함)  │
│  - Overall score 계산                    │
│  - Gap-fill 제안 (needs_iteration)       │
│  Output: coverage analysis, gap_terms    │
└──────────────────┬───────────────────────┘
                   │
            needs_iteration?
           ┌──YES──┴──NO──┐
           │              │
     Stage 3 재호출    검색 완료
     (gap-fill terms)
```

### Stage별 핵심 메커니즘

**Stage 1 - Entity Extraction:**
- Gene: `[A-Z][A-Z0-9]{1,9}` regex + `_NON_GENE_WORDS` 필터 (AND, OR, EMT 등 제거)
- Pathway: 90개+ 키워드 dict (case-insensitive)
- Cell types: 50개+ 키워드 dict
- Diseases: 30개+ 키워드 dict

**Stage 1 - Complexity Assessment:**
- `simple` (0점) → `moderate` (1-2점) → `multi_hop` (3점+)
- 점수: entity 수, causal verb 수, and 접속사, spatial+mechanism 조합

**Stage 2 - 확장 전략:**
- 로컬 dict 조회 (0ms) → API fallback (MyGene.info, NCBI E-utilities, ~500ms)
- PubMed fragment 생성: `(TGFB1[tiab] OR "TGF-beta-1"[tiab] OR "TGF Growth Factor beta1"[mh])`

**Stage 3 - 5가지 전략:**
| 전략 | 트리거 조건 | 동작 |
|------|-----------|------|
| `direct_search` | simple | 단일 combined query |
| `balanced` | moderate (default) | sub-question 1개당 query 1개 |
| `gene_centric_then_pathway` | moderate + genes > 3 | 전반 gene, 후반 pathway |
| `hypothesis_driven` | multi_hop + cci_mechanism | 모든 query에 disease 필수 |
| `iterative_refinement` | multi_hop (기타) | 3-tier broad→medium→narrow |

**Stage 4 - 커버리지 판정:**
- Sub-question: 논문당 key terms 2개+ 매칭 → matching paper, 5개+ 있으면 `well_covered`
- Overall: `0.5 × sq_score + 0.5 × entity_score`
- `needs_iteration = overall_score < 0.6 or any(high priority + poorly_covered)`

---

## 3. DeepMAST 통합 방식

### 3.1 MCP Client 연결 설정 (`think.py`)

```python
# stdio transport - fastmcp subprocess로 실행
BIOMEDICAL_THINKING_CONFIG = {
    "command": "fastmcp",
    "args": ["run", "~/Dropbox/Metadata/mcp/biomedical_thinking/server.py"],
    "transport": "stdio",
}
```

### 3.2 LangChain Tool로 래핑 (4개)

| DeepMAST Tool Name | MCP Server Tool | 사용 Subagent |
|--------------------|-----------------|---------------|
| `analyze_research_question` | `analyze_and_decompose` | SEARCHER |
| `expand_search_entities` | `expand_entities` | PLANNER, SEARCHER |
| `build_search_queries` | `build_search_queries` | SEARCHER |
| `evaluate_search_results` | `evaluate_search_results` | SEARCHER |

### 3.3 SEARCHER Subagent 워크플로우에서의 역할

```
SEARCHER 시작
    │
    ├─ [1] analyze_research_question(question)  ← Stage 1
    │      → entities, sub_questions, strategy
    │
    ├─ [2] expand_search_entities(genes, ...)    ← Stage 2
    │      → pubmed_query_fragments
    │
    ├─ [3] build_search_queries(sub_q, frags)   ← Stage 3
    │      → optimized PubMed queries
    │
    ├─ [4] search_pubmed_advanced(query)        ← 실제 검색 (E-utilities)
    │      → papers
    │
    └─ [5] evaluate_search_results(papers, ...)  ← Stage 4
           → coverage, gap_analysis
           → needs_iteration? → Stage 3 재호출
```

### 3.4 다른 MCP 서버들과의 관계

DeepMAST는 3개의 MCP 서버를 사용:

| MCP Server | Transport | 역할 | 사용 위치 |
|-----------|-----------|------|----------|
| **biomedical-thinking** | stdio | 쿼리 구조화 (규칙 기반) | SEARCHER, PLANNER |
| **reflection-tool** | stdio | 품질 검증 (think_tool) | All subagents |
| **BioMCP** | HTTP (streamable_http) | PubMed 검색 + Gene 정보 | SEARCHER, REPORTER |

---

## 4. Code Review Findings (14 issues)

### CRITICAL (2)

1. **MCP Client 매 호출마다 새로 생성 → 리소스 누수**
   - stdio transport는 호출마다 새 subprocess를 spawn
   - `search_literature_dynamic` 1회 호출 시 30+ MCP client 인스턴스 가능
   - 파일: `think.py:76,131`, `literature.py:88,287,1329,1459`

2. **사용자 특정 파일경로 하드코딩**
   - `Path.home() / "Dropbox" / "Metadata" / "mcp" / ...` 기본값
   - 다른 개발자/CI 환경에서 silent fail
   - 파일: `think.py:38-39,54-56`

### HIGH (4)

3. **813줄 sync/async 비즈니스 로직 중복** (`literature.py`)
   - `_execute_fixed_strategy_search` vs `_async` 버전 (286줄)
   - `search_literature_dynamic` vs `_async` 버전 (527줄)

4. **`REFLECTION_TOOL_CONFIG` 2개 파일에 중복 정의** (`think.py`, `quality.py`)

5. **substring 매칭으로 tool 탐색** — `'think' in tool_obj.name` 패턴이 의도치 않은 tool 매칭 가능

6. **`quality.py`에서 호출마다 새 ThreadPoolExecutor 생성** — 다른 파일의 singleton 패턴과 불일치

### MEDIUM (5)

7-9. 3곳의 `asyncio.get_event_loop()` 미전환 (Python 3.10+ deprecated)
10. `literature.py` 2120줄 — 800줄 기준 초과, 분리 필요
11. `_GENE_ALIAS_CACHE` thread safety 없음

### Positive Aspects

- 모든 MCP 호출에 예외 처리 + graceful fallback
- 잘 구조화된 docstring (LLM subagent가 tool 설명으로 활용)
- NCBI rate limiting (API key 유무에 따라 10 vs 3 req/s 적응)

---

## 5. 핵심 설계 원칙 요약

1. **Zero LLM Cost**: Biomedical Thinking 서버는 LLM을 사용하지 않음 → 토큰 비용 0
2. **Local-First, API-Fallback**: 로컬 dictionary 우선, 없으면 API 호출
3. **Iterative Refinement**: Stage 4 평가 → gap 발견 시 Stage 3 재호출
4. **Separation of Concerns**: 쿼리 구조화(biomedical-thinking) vs 실제 검색(BioMCP/E-utilities) vs 품질 검증(reflection-tool) 분리
5. **Coverage-Driven**: 단순 검색이 아닌 entity/sub-question 커버리지 기반 검색 전략
