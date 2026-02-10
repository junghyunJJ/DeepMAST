# INTERPRETER Subagent 상세 분석

> 문헌 기반 해석 에이전트 — 인라인 검증 + 품질 루프 + RAG 지원

## 목차

- [개요](#개요)
- [설정](#설정)
- [6-Phase 실행 워크플로우](#6-phase-실행-워크플로우)
- [도구 상세](#도구-상세)
- [RAG 파이프라인](#rag-파이프라인)
- [품질 검증 루프](#품질-검증-루프)
- [L-R 우선순위화](#l-r-우선순위화)
- [RAG 모드 vs Abstract 모드](#rag-모드-vs-abstract-모드)
- [4-레벨 Anti-Hallucination](#4-레벨-anti-hallucination)
- [Part 1 vs Part 2 vs Part 3](#part-1-vs-part-2-vs-part-3)
- [입출력 파일 계약](#입출력-파일-계약)
- [수정 가이드](#수정-가이드)

---

## 개요

INTERPRETER는 4-에이전트 워크플로우의 **세 번째** 서브에이전트로, 시스템에서 **가장 무거운 계산 에이전트**입니다.

**핵심 제약**: PubMed 검색 도구가 **없습니다**. SEARCHER가 찾은 논문만 사용 가능 — 이것이 anti-hallucination의 구조적 강제입니다.

**책임**: 문헌 기반 생물학적 해석 생성, 모든 인용 인라인 검증, 품질 점수 임계값(0.7)까지 반복 개선

---

## 설정

### configs.py

```python
"interpreter": {
    "tools": [
        load_analysis_data,          # 1. 분석 결과 로딩
        validate_claim_literature,    # 2. Abstract 모드 주장 검증
        validate_quality,             # 3. 4-기준 가중 품질 점수
        think_tool,                   # 4. 반성(reflection) via MCP
        prepare_rag_literature,       # 5. RAG: 논문 다운로드 + 인덱싱
        search_literature_fulltext,   # 6. RAG: 의미론적 다중 쿼리 검색
        validate_claim_fulltext,      # 7. RAG: 전문 기반 주장 검증
        prioritize_top_lr_pairs,      # 8. 하이브리드 L-R 우선순위화
    ],
}
```

**8개 도구** — 검색 도구(search_literature, search_pubmed_advanced 등)는 의도적으로 **제외**됨

---

## 6-Phase 실행 워크플로우

```
┌──────────────────────────────────────────────────────────────────────────┐
│  INTERPRETER 실행 흐름 (Part 1, 2, 3 각각 반복)                          │
│                                                                          │
│  ═══════ Phase 0: RAG 준비 ═══════                                       │
│                                                                          │
│  prepare_rag_literature(papers_json_path, part_name)                     │
│      ├── check_rag_availability() (환경변수 + MCP 연결 + 헬스체크)        │
│      ├── download_papers_for_rag(pmids) (최대 30편, 1초 rate limit)       │
│      ├── index_papers_to_vectordb(chunk_size=1000, overlap=200)          │
│      └── 결과: rag_mode = True/False                                     │
│                                                                          │
│  ═══════ Phase 1: 컨텍스트 로딩 ═══════                                  │
│                                                                          │
│  read_file("/part1_papers.json" or "/liana_papers.json")                 │
│  read_file("/interpretation_guide.md")                                   │
│  read_file("/data_path.txt")                                             │
│  load_analysis_data(data_dir) → 그림 경로 + CSV 데이터                   │
│                                                                          │
│  ═══════ Phase 1.5: 분석별 RAG 검색 (RAG 모드만) ═══════                 │
│                                                                          │
│  각 분석 해석 전:                                                        │
│  search_literature_fulltext(query="주제 키워드", part_name, limit=5)      │
│      ├── multi_query 생성 (1→5개 다양한 쿼리)                             │
│      ├── 각 쿼리당 3개 결과 (최대 15개 후보)                              │
│      ├── 콘텐츠 해시 기반 중복 제거                                       │
│      └── 점수 내림차순 → 상위 N개 반환                                    │
│                                                                          │
│  ═══════ Phase 2: 해석 생성 (문헌 기반) ═══════                           │
│                                                                          │
│  RAG 모드: Phase 1.5 결과 + papers JSON → 구체적 텍스트 인용              │
│  Abstract 모드: papers JSON 초록만 → 일반적 수준 인용                     │
│  인용 형식: "...역할... (PMID: 35123456)."                               │
│  인용 불가: "(Novel Finding - no direct citation available)"             │
│                                                                          │
│  ═══════ Phase 3: 인라인 주장 검증 ═══════                               │
│                                                                          │
│  사전: PMID가 papers JSON에 있는지 확인 (없으면 즉시 Novel Finding)       │
│                                                                          │
│  RAG 모드:                                                               │
│    validate_claim_fulltext(claim, pmid, part_name)                       │
│    ≥0.7: 유지 | ≥0.4: 유지(강화) | <0.4: 수정/Novel Finding             │
│                                                                          │
│  Abstract 모드:                                                          │
│    validate_claim_literature(claim, pmid, paper_abstract)                │
│    strong: 유지 | moderate: 유지 | weak: 수정 | unsupported: Novel       │
│                                                                          │
│  ═══════ Phase 4: 품질 검증 루프 (최대 3회) ═══════                      │
│                                                                          │
│  validate_quality(interpretation, references)                            │
│    4-기준 가중 점수 (각 0.25):                                           │
│    statistics + references + mechanism + specificity                      │
│    + LLM 강화 (reflection-tool)                                          │
│    score ≥ 0.7 → PASS | < 0.7 → 약한 기준 강화 → 재시도                  │
│                                                                          │
│  ═══════ Phase 5: 최종 해석 기록 ═══════                                 │
│                                                                          │
│  write_file("/partN_final.md")                                           │
│  ## Analysis N-X: {이름}                                                 │
│  ### Figure Description                                                  │
│  ### Quantitative Findings (2+ 통계)                                     │
│  ### Biological Interpretation (PMID 인용 또는 Novel Finding)             │
│  ### References                                                          │
│  ## Part N Summary (핵심 발견 3개 + 품질 메트릭)                          │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 도구 상세

### 1. `validate_claim_literature` (Abstract 모드 검증)

**파일**: `tools/quality.py`

| 항목 | 설명 |
|------|------|
| 입력 | `claim: str`, `pmid: str`, `paper_abstract: str` |
| 출력 | `{alignment, evidence_quote, recommendation, confidence, reasoning}` |
| 방식 | 용어 매칭 + 모순 검출 (LLM 호출 없음) |

**알고리즘**:
1. 주장에서 유전자 패턴(대문자)과 생물학 키워드 추출
2. 초록에서 매칭 용어 카운트
3. 최고 증거 문장 선택 (매칭 용어 최다 문장)
4. 정렬도 판정:
   - match_ratio ≥ 0.6 AND best_score ≥ 2: `"strong"` (confidence ≤ 0.9)
   - match_ratio ≥ 0.3 OR best_score ≥ 1: `"weak"` (confidence ≤ 0.7)
   - 그 외: `"unsupported"` (confidence = match_ratio)
5. 모순 증거 확인 (부정 패턴 탐지), 감점 적용

### 2. `validate_quality` (4-기준 품질 점수)

**파일**: `tools/quality.py`

| 기준 | 가중치 | 측정 방법 | 점수 공식 |
|------|--------|----------|----------|
| statistics | 0.25 | `%`, `p<`, `fold change` 정규식 카운트 | `min(count/2, 1.0)` |
| references | 0.25 | PMID 패턴 + 참조 목록 길이 | `min((refs+patterns)/2, 1.0)` |
| mechanism | 0.25 | 12개 생물학 키워드 매칭 | `min(count/3, 1.0)` |
| specificity | 0.25 | 5개 모호 표현 역패턴 | `max(1.0 - count*0.2, 0.0)` |

**LLM 강화** (선택적): reflection-tool MCP → LLM 점수, 최종 = (기본 + LLM) / 2

**예시 계산**:
```
"23.5% of spots" "p < 0.001" "2.3-fold" → statistics: 3 → 1.0
"(PMID: 35123456)" "(PMID: 36789012)" → references: 2 → 1.0
"signaling" "pathway" "interaction" "receptor" → mechanism: 4 → 1.0
"further research needed" → specificity: 1 → 0.8
기본 점수 = 1.0×0.25 + 1.0×0.25 + 1.0×0.25 + 0.8×0.25 = 0.95
```

### 3. `prioritize_top_lr_pairs` (Part 3 전용)

**파일**: `tools/lr_prioritizer.py`

**하이브리드 점수** = `0.6 × Moran_R_norm + 0.4 × GenePT_norm`

- **Moran's R (60%)**: 공간 자기상관 — L-R 상호작용의 공간적 공동위치화
- **GenePT (40%)**: 리간드-수용체 유전자 임베딩 코사인 유사도

**처리 흐름**:
1. `interest_sig_liana.csv` 읽기
2. Moran's R 컬럼 자동 탐지 (10가지 후보명)
3. `genept_score` 컬럼 읽기 (사전 계산)
4. Min-Max 정규화 → 하이브리드 점수 → 상위 3개 반환

---

## RAG 파이프라인

### prepare → search → validate 흐름

```
prepare_rag_literature(papers_json_path, part_name)
    ├── check_rag_availability() → _RAG_STATE["available"]
    ├── download_papers_for_rag(pmids)
    │   └── pubmed-download MCP → res/papers/pmid_{PMID}.txt (최대 30편)
    ├── index_papers_to_vectordb(file_paths, part_name)
    │   └── langconnect-rag MCP → "deep_interpreter_{part_name}" 컬렉션
    └── return {rag_mode: True/False}

search_literature_fulltext(query, part_name, limit=5)
    ├── multi_query(query) → 5개 다양한 쿼리 생성
    ├── 각 쿼리 × 3개 결과 (최대 15개 후보)
    ├── 콘텐츠 해시 중복 제거
    └── 점수 내림차순 → 상위 N개

validate_claim_fulltext(claim, pmid, part_name)
    ├── search_fulltext_rag(claim, limit=15) → multi-query
    ├── PMID 메타데이터 필터링
    ├── 최고 매치 점수 계산
    └── {valid, confidence, supporting_text}
```

### `_RAG_STATE` 추적

```python
_RAG_STATE = {
    "available": None,        # None=미확인, True/False=확인 (세션 캐시)
    "collection_ids": {},     # {part_name: collection_id}
}
```

---

## 품질 검증 루프

```
For EACH Part (1, 2, 3):
  iteration = 0
  while iteration < 3:
    1. 해석 생성 (Phase 2)
    2. 주장 검증 (Phase 3)
    3. validate_quality(interpretation, references)
    4. score ≥ 0.7 → PASS → write /partN_final.md
    5. score < 0.7 → 약한 기준 식별 → 강화 → iteration++
    6. iteration == 3 → 최선 버전 + 경고 기록
```

---

## RAG 모드 vs Abstract 모드

| 항목 | RAG 모드 | Abstract 모드 |
|------|---------|--------------|
| Phase 0 | 논문 다운로드 + 인덱싱 | 스킵 |
| Phase 1.5 | `search_literature_fulltext` | 스킵 |
| Phase 2 인용 | 검색 결과 + papers JSON | papers JSON만 |
| Phase 3 검증 | `validate_claim_fulltext` | `validate_claim_literature` |
| 인용 정확도 | ~90% | ~70% |
| 경로 커버리지 | ~70-85% | ~32% |

**Abstract 모드 전환 트리거** (어느 하나라도):
- 환경변수 미설정 (`CCI_RAG_PYTHON`, `CCI_RAG_SERVER`)
- MCP 서버 연결 실패
- 논문 다운로드 전체 실패
- 벡터 DB 인덱싱 실패

---

## 4-레벨 Anti-Hallucination

| 레벨 | 메커니즘 | 설명 |
|------|---------|------|
| 1. 아키텍처 | 도구 목록에 검색 도구 없음 | PubMed 검색 불가 |
| 2. 프롬프트 | "절대 PMID를 발명하지 마라" | 플레이스홀더 PMID 금지 |
| 3. 사전 검증 | Phase 3 전 PMID 존재 확인 | papers JSON에 없으면 제거 |
| 4. 도구 검증 | validate_claim_* | 주장-논문 정합성 확인 |

**Novel Finding 태그**:
- `(Novel Finding - no direct citation available)`
- `(Novel Finding - based on data analysis)`

---

## Part 1 vs Part 2 vs Part 3

| 항목 | Part 1 | Part 2 | Part 3 |
|------|--------|--------|--------|
| 초점 | 공간 조직, 경로 기울기 | CCI 패턴, NMF 인자 | L-R 메커니즘 상세 |
| 분석 | 1-1~1-5 | 2-6~2-9 | 3-10~3-11 |
| 논문 소스 | `/part1_papers.json` | `/liana_papers.json` | `/liana_papers.json` |
| RAG 컬렉션 | `deep_interpreter_part1` | `deep_interpreter_liana` | 재사용 |
| 유전자 수준 | NO | YES | YES |
| L-R 우선순위 | 미사용 | 미사용 | `prioritize_top_lr_pairs` |

---

## 입출력 파일 계약

### 읽기 (Input)

| 파일 | 소스 |
|------|------|
| `/part1_papers.json` | SEARCHER |
| `/liana_papers.json` | SEARCHER |
| `/interpretation_guide.md` | PLANNER |
| `/data_path.txt` | PLANNER |
| `interest_sig_liana.csv` | 사전 계산 |

### 쓰기 (Output)

| 파일 | 소비자 |
|------|--------|
| `/part1_final.md` | REPORTER |
| `/part2_final.md` | REPORTER |
| `/part3_final.md` | REPORTER |

---

## 수정 가이드

### 안전한 수정

| 대상 | 파일 |
|------|------|
| 품질 가중치 변경 | `tools/quality.py` (`QUALITY_CRITERIA`) |
| L-R 가중치 변경 | `tools/lr_prioritizer.py` (기본 파라미터) |
| RAG 청크 크기 | `tools/literature_rag.py` (`chunk_size`, `chunk_overlap`) |
| 품질 기준 추가 | `tools/quality.py` (가중치 합 1.0 유지) |

### 위험한 결합

| 대상 | 영향 |
|------|------|
| `_RAG_STATE` 동작 변경 | 모든 RAG 도구 세션 전체 |
| 검색 도구 추가 | Literature-First 패턴 파괴 |
| Phase 번호 변경 | 3개 Part 전체 워크플로우 |
| MCP 클라이언트 캐싱 | 서브프로세스 누수 위험 |
