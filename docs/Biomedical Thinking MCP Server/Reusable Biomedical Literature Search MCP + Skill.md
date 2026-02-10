# Plan: Reusable Biomedical Literature Search MCP + Skill

## Context

현재 논문 검색 기능이 3곳에 분산되어 있음:
1. **biomedical_thinking MCP** (`/Users/jungj2/Dropbox/Metadata/mcp/biomedical_thinking/`) - Rule-based 4도구 (decompose, expand, build_queries, evaluate). PubMed 검색 기능 없음.
2. **pubmed_eutils.py** (DeepMAST 내부) - E-utilities 직접 호출. LangChain @tool 종속.
3. **search_literature_dynamic** (DeepMAST 내부) - LLM+BioMCP 기반 반복 검색. 1969줄 모놀리식.

**목표**: biomedical_thinking MCP에 pubmed_eutils 검색 기능을 통합하고, 반복적 커버리지 개선 워크플로우를 Claude Skill로 제공하여 **어떤 프로젝트에서든 재사용 가능한** 논문 검색 시스템 구축.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Claude Skill (SKILL.md)                                │
│  "biomedical-literature-search"                         │
│  - Agent가 읽고 따르는 워크플로우 레시피                  │
│  - 반복 검색 + 커버리지 평가 + 갭 필링 오케스트레이션     │
│  - LLM이 맥락 이해하여 쿼리 조합 최적화 (optional)       │
└────────────────────────┬────────────────────────────────┘
                         │ MCP tool calls
                         v
┌─────────────────────────────────────────────────────────┐
│  biomedical_thinking MCP Server (FastMCP)               │
│  Self-contained, No LLM, No BioMCP dependency           │
│                                                         │
│  기존 4도구:                                             │
│  1. analyze_and_decompose  (질문 분해 + 엔티티 추출)      │
│  2. expand_entities        (MeSH + 유전자 별칭 확장)      │
│  3. build_search_queries   (전략 기반 쿼리 빌드)          │
│  4. evaluate_search_results (커버리지 평가) [강화]         │
│                                                         │
│  신규 도구:                                               │
│  5. search_pubmed          (E-utilities 검색 실행)        │
└─────────────────────────────────────────────────────────┘
```

---

## Step 1: `tools/search.py` 신규 생성 (MCP)

**소스**: `DeepMAST/src/agents/deep_interpreter/tools/pubmed_eutils.py`

**적응 사항**:
- `langchain_core.tools.tool` 데코레이터 제거 → 일반 async 함수
- `urllib.request` → `httpx` (MCP 서버에 이미 의존)
- `ThreadPoolExecutor` 브리징 제거 (FastMCP는 네이티브 async)
- `PUBMED_TOOL = "DeepMAST"` → 설정 가능한 이름

**재사용 코드**:
| 원본 함수 | 라인 | 처리 |
|-----------|------|------|
| `_search_with_eutilities()` | 81-211 | httpx로 적응 |
| `_parse_pubmed_xml()` | 214-260 | 그대로 복사 (stdlib) |
| `_rate_limit()` | 62-70 | `utils/rate_limiter.py`로 추출 |
| `build_pubmed_query()` | 267-340 | 도구 내 헬퍼로 포함 |

**도구 시그니처**:
```python
async def search_pubmed(
    query: str,                    # PubMed 쿼리 문자열
    max_results: int = 20,         # 최대 결과 수 (max 100)
    sort: str = "relevance",       # "relevance" | "pub_date"
    min_date: str = "",            # YYYY/MM/DD
    max_date: str = "",            # YYYY/MM/DD
) -> dict:
    # Returns: {papers: [{pmid, title, abstract}], query_used, total_results, returned_results}
```

**파일**: `/Users/jungj2/Dropbox/Metadata/mcp/biomedical_thinking/tools/search.py`

---

## Step 2: `utils/rate_limiter.py` 신규 생성

`pubmed_eutils.py`의 `_rate_limit()` 로직 추출. `search.py`와 `expand.py` (API 호출)에서 공유.

```python
# NCBI_API_KEY 있으면 10 req/s (0.11s), 없으면 3 req/s (0.34s)
async def rate_limit():
    ...
```

**파일**: `/Users/jungj2/Dropbox/Metadata/mcp/biomedical_thinking/utils/rate_limiter.py`

---

## Step 3: `server.py` 업데이트

```python
from tools.search import search_pubmed
mcp.tool()(search_pubmed)
```

**파일**: `/Users/jungj2/Dropbox/Metadata/mcp/biomedical_thinking/server.py`

---

## Step 4: `tools/evaluator.py` 강화 - 스마트 패턴 매칭

**현재 문제**: `_entity_in_text()`가 단순 substring 매칭 + 27개 하드코딩 alias만 사용.

**병합할 코드** (from `literature.py`):
| 함수 | 라인 | 기능 |
|------|------|------|
| `_generate_gene_patterns()` | 987-1072 | Case/separator/Greek letter 변환 자동 생성 |
| `_generate_pathway_patterns()` | 1075-1111 | 세미콜론 분리, 키워드 확장, Greek 변환 |
| `_normalize_text_for_matching()` | 1114-1120 | 텍스트 정규화 |
| `SPECIAL_GENE_ALIASES` | 959-970 | ACKR3→CXCR7, ERBB2→HER2 등 |
| `PATHWAY_KEYWORDS` | 973-984 | MAPK→"erk signaling" 등 |

**변경 사항**:
- `_entity_in_text()` → `_generate_gene_patterns()` + `_generate_pathway_patterns()` 기반으로 교체
- 기존 `_GENE_ALIASES` dict (27개) 유지 + `SPECIAL_GENE_ALIASES` 병합
- `PATHWAY_KEYWORDS` dict 추가
- BioMCP 캐시 참조 부분 제거 (`_GENE_ALIAS_CACHE` 관련 코드)
- 반환값에 `matched_by` 필드 추가 (어떤 패턴으로 매칭됐는지)

**파일**: `/Users/jungj2/Dropbox/Metadata/mcp/biomedical_thinking/tools/evaluator.py`

---

## Step 5: `utils/gene_aliases.py` 소폭 업데이트

`SPECIAL_GENE_ALIASES`에서 누락된 항목 추가:
- `ACKR3: ["CXCR7"]`
- `ERBB2: ["HER2", "NEU"]`
- `CXCL12: ["SDF1"]`

**파일**: `/Users/jungj2/Dropbox/Metadata/mcp/biomedical_thinking/utils/gene_aliases.py`

---

## Step 6: 테스트 추가

**신규**: `tests/test_search.py`
- E-utilities ESearch + EFetch 응답 모킹
- XML 파싱 검증
- Rate limiting 동작 확인
- 빈 결과, 오류 응답 처리

**업데이트**: `tests/test_evaluator.py`
- 스마트 패턴 매칭 검증 (ADAM10 → adam-10, adam10 등)
- Greek letter 변환 (TGFβ → TGFbeta)
- SPECIAL_GENE_ALIASES 동작 확인

---

## Step 7: Claude Skill (SKILL.md) 작성

**위치**: `/Users/jungj2/Dropbox/Metadata/mcp/biomedical_thinking/skills/biomedical-literature-search/SKILL.md`

기존 DeepMAST SKILL.md를 기반으로 하되 **프로젝트 독립적**으로 재작성:

### Skill 워크플로우 (7 Phase)

```
Phase 1: ANALYZE - analyze_and_decompose로 질문 분해
Phase 2: EXPAND  - expand_entities로 MeSH/별칭 확장
Phase 3: BUILD   - build_search_queries로 전략적 쿼리 생성
Phase 4: SEARCH  - search_pubmed로 각 쿼리 실행
Phase 5: EVALUATE - evaluate_search_results로 커버리지 평가
Phase 6: GAP-FILL - 목표 미달 시 Phase 3으로 돌아가 갭 쿼리 생성 (max 3회)
Phase 7: OUTPUT  - 최종 결과 정리
```

### 기존 DeepMAST SKILL.md와의 차이

| 항목 | 기존 (DeepMAST) | 신규 (범용) |
|------|-----------------|------------|
| 검색 도구 | `search_literature_dynamic` (Python) | `search_pubmed` (MCP) |
| 전략 수립 | `think_tool` (Python) | `analyze_and_decompose` + `build_search_queries` (MCP) |
| 커버리지 평가 | LLM + Python `_calculate_coverage` | `evaluate_search_results` (MCP) |
| 반복 루프 | Python 코드 내장 | Agent가 Skill 따라 수행 |
| BioMCP 의존 | 필수 | 없음 |
| DeepMAST 종속 | VFS, load_analysis_data 등 | 없음 |

### LLM 역할 (하이브리드)

MCP 도구는 rule-based이지만, **Skill을 따르는 Agent(LLM)가**:
- Phase 1 결과를 보고 우선순위 유전자/경로를 선별
- Phase 5 갭 분석을 해석하여 Phase 6 갭 필링 전략 결정
- 생물학적 맥락을 이해하여 쿼리 조합 최적화

→ Rule-based 도구의 확정적 처리 + LLM의 맥락 이해가 결합.

---

## Step 8 (Optional): DeepMAST 마이그레이션

DeepMAST의 SEARCHER가 새 MCP 도구를 사용하도록 전환. **별도 작업**으로 진행.

- `subagents/configs.py`의 SEARCHER 도구 목록에 MCP 도구 추가
- 기존 `search_literature_dynamic` → MCP Skill 기반 워크플로우로 점진적 전환
- `pubmed_eutils.py`는 MCP로 이전 후 DeepMAST에서 제거 가능

---

## 파일 변경 요약

| 파일 | 작업 | 위치 |
|------|------|------|
| `tools/search.py` | **신규** | MCP 서버 |
| `utils/rate_limiter.py` | **신규** | MCP 서버 |
| `server.py` | 수정 (tool 등록 추가) | MCP 서버 |
| `tools/__init__.py` | 수정 (export 추가) | MCP 서버 |
| `tools/evaluator.py` | 강화 (패턴 매칭) | MCP 서버 |
| `utils/gene_aliases.py` | 소폭 추가 | MCP 서버 |
| `pyproject.toml` | 버전 범프 0.1.0→0.2.0 | MCP 서버 |
| `tests/test_search.py` | **신규** | MCP 서버 |
| `tests/test_evaluator.py` | 업데이트 | MCP 서버 |
| `skills/.../SKILL.md` | **신규** | MCP 서버 |

---

## Verification

1. **MCP 서버 시작**: `cd /Users/jungj2/Dropbox/Metadata/mcp/biomedical_thinking && uv run python server.py`
2. **search_pubmed 도구 테스트**: MCP Inspector 또는 Claude Code에서 `search_pubmed(query="TGFB1[tiab] AND breast cancer[mh]", max_results=5)` 호출
3. **evaluate_search_results 강화 검증**: "ADAM10" 유전자가 "adam-10", "ADAM 10" 패턴으로 매칭되는지 확인
4. **전체 워크플로우 테스트**: Skill 워크플로우를 따라 Phase 1-7 순차 실행
5. **테스트 스위트**: `cd /Users/jungj2/Dropbox/Metadata/mcp/biomedical_thinking && uv run pytest tests/`

---

## 향후 확장 (참고)

Researcher 분석 결과, 다음 추가 통합이 가치 있음:
- **Europe PMC API**: Full-text 검색 + preprint 커버리지 (PubMed 보완)
- **OpenAlex API**: 98.6% 커버리지로 갭 필링에 활용
- **LitSense 2.0**: 문장 수준 시맨틱 검색 (메커니즘 세부사항에 유용)
- **Persistent MeSH 캐시**: 반복 API 호출 제거 (SQLite 또는 JSON)

이들은 Step 1-7 완료 후 `search.py`에 추가 백엔드로 점진적 통합 가능.
