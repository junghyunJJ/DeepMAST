# REPORTER Subagent 상세 분석

> 종합 & 리포트 생성 에이전트 — 교차 파트 합성 + 독립 문헌 검증 + HTML 리포트

## 목차

- [개요](#개요)
- [설정](#설정)
- [6-Phase 실행 워크플로우](#6-phase-실행-워크플로우)
- [Phase 4.5 독립 문헌 검증](#phase-45-독립-문헌-검증)
- [도구 상세](#도구-상세)
- [HTML 리포트 구조](#html-리포트-구조)
- [입출력 파일 계약](#입출력-파일-계약)
- [서브에이전트 비교](#서브에이전트-비교)
- [수정 가이드](#수정-가이드)

---

## 개요

REPORTER는 4-에이전트 워크플로우의 **최종 (네 번째)** 서브에이전트입니다.

**유일하게 모든 Part 해석을 동시에 읽는 에이전트**로서:
1. 교차 파트 종합 (Cross-Part Synthesis)
2. 독립 문헌 검증 (Phase 4.5)
3. 자체 완결형 HTML 리포트 생성

**핵심 특징**: Phase 4.5 — 종합 주장을 SEARCHER와는 **독립적으로** 새로 검색한 문헌으로 검증

---

## 설정

### configs.py

```python
"reporter": {
    "tools": [
        load_analysis_data,           # 1. 분석 데이터 + 그림 경로
        generate_html_report,          # 2. HTML 리포트 생성
        search_literature_dynamic,     # 3. LLM 기반 통합 문헌 검색
        search_literature,             # 4. 단일 쿼리 보충 검색
        prepare_rag_literature,        # 5. RAG: 전문 다운로드 + 인덱싱
        validate_claim_fulltext,       # 6. RAG: 전문 기반 주장 검증
        think_tool,                    # 7. 전략 계획 + 반성
    ],
}
```

**7개 도구** — SEARCHER와 달리 `generate_html_report` 보유, INTERPRETER와 달리 `search_literature_dynamic` 보유

---

## 6-Phase 실행 워크플로우

```
┌──────────────────────────────────────────────────────────────────────────┐
│  REPORTER 실행 흐름                                                      │
│                                                                          │
│  ═══════ Phase 1: 모든 입력 읽기 ═══════                                 │
│                                                                          │
│  read_file("/part1_final.md")         ← INTERPRETER Part 1              │
│  read_file("/part2_final.md")         ← INTERPRETER Part 2              │
│  read_file("/part3_final.md")         ← INTERPRETER Part 3              │
│  read_file("/interpretation_guide.md") ← PLANNER 초점 영역              │
│  read_file("/part1_papers.json")      ← SEARCHER Part 1 논문            │
│  read_file("/liana_papers.json")      ← SEARCHER Part 2+3 논문          │
│  read_file("/data_path.txt")          ← 실제 데이터 경로                 │
│  load_analysis_data(data_dir)         ← 그림 경로 + 메타데이터           │
│                                                                          │
│  ═══════ Phase 2: 교차 파트 종합 ═══════                                 │
│                                                                          │
│  4가지 테마 식별:                                                        │
│  ┌────────────────────────────────────────────────────────────────┐      │
│  │ Theme 1: 공간 조직                                             │      │
│  │   Part 1 공간 패턴 ↔ Part 2 CCI 패턴                          │      │
│  ├────────────────────────────────────────────────────────────────┤      │
│  │ Theme 2: 세포 통신 축                                          │      │
│  │   어떤 세포 (Part 1+2) ↔ 어떤 L-R 쌍 (Part 2+3)               │      │
│  ├────────────────────────────────────────────────────────────────┤      │
│  │ Theme 3: 경로 통합                                             │      │
│  │   Part 1 Decoupler ↔ Part 2 L-R 시그널링                      │      │
│  ├────────────────────────────────────────────────────────────────┤      │
│  │ Theme 4: 질병 메커니즘                                         │      │
│  │   질병 진행 관계 + 치료적 시사점                                │      │
│  └────────────────────────────────────────────────────────────────┘      │
│                                                                          │
│  ═══════ Phase 3: 창발적 테마 식별 ═══════                               │
│                                                                          │
│  ├── Strong Theme: 여러 파트의 일관된 증거                               │
│  ├── Emerging Theme: 부분적 증거                                        │
│  └── Unexpected Pattern: 예상 밖 발견                                   │
│                                                                          │
│  ═══════ Phase 4: 초안 synthesis.md 작성 ═══════                         │
│                                                                          │
│  write_file("/synthesis.md")                                             │
│  ├── # Integrated Biological Narrative                                   │
│  ├── ## Executive Summary (2-3 단락)                                     │
│  ├── ## Cross-Part Themes (4개 테마)                                     │
│  ├── ## Emergent Themes Summary (강도 등급 테이블)                        │
│  ├── ## Clinical/Biological Implications                                 │
│  ├── ## Limitations                                                      │
│  └── ## Novel Findings Summary                                           │
│                                                                          │
│  ═══════ Phase 4.5: 독립 문헌 검증 (5단계) ═══════                       │
│  → 아래 [Phase 4.5 상세](#phase-45-독립-문헌-검증) 참조                   │
│                                                                          │
│  ═══════ Phase 5: HTML 리포트 생성 ═══════                               │
│                                                                          │
│  generate_html_report(parts={...}, output_path="CCI_Analysis_Report.html")│
│                                                                          │
│  ═══════ Phase 6: 검증 ═══════                                           │
│                                                                          │
│  HTML 파일 생성 확인 + 오케스트레이터에 보고                              │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Phase 4.5 독립 문헌 검증

Phase 4.5는 REPORTER의 가장 중요한 아키텍처적 특징입니다.

### 설계 원리

```
SEARCHER가 찾은 논문:          REPORTER가 찾는 논문:
  "CDH1 in breast cancer"       "CDH1 + EMT + fibroblast spatial
  "EMT pathway activation"       interaction in breast cancer"
  "Fibroblast signaling"        → 성분 조합을 다루는 논문
  → 개별 성분 논문

종합 주장: "TGF-β 시그널링이 섬유아세포-상피세포 공간 근접을 통해 EMT를 유도"
  ↑ Part별 논문으로는 검증 불가 → 통합 컨텍스트의 독립 논문이 필요
```

### 5단계 상세

```
┌── Step 1: 종합 컨텍스트 추출 ──────────────────────────────────┐
│  synthesis.md에서 genes, pathways, celltypes,                  │
│  integration_keywords, disease_context 파싱                    │
│  → write_file("/synthesis_search_context.json")                │
└────────────────────────────────────────────────────────────────┘
    │
    ▼
┌── Step 2: 전략 계획 (think_tool × 3회) ────────────────────────┐
│  Thought 1: 통합 테마 분석                                     │
│  Thought 2: 통합 중심 검색 전략 수립                            │
│  Thought 3: 예상 메커니즘 예측                                  │
│  → write_file("/synthesis_search_strategy.json")               │
└────────────────────────────────────────────────────────────────┘
    │
    ▼
┌── Step 3: 통합 문헌 검색 ──────────────────────────────────────┐
│  search_literature_dynamic(                                    │
│    genes + pathways + celltypes를 통합하여 검색                 │
│    ⚠️ SEARCHER와 차이: 개별 성분이 아닌 "조합"을 검색           │
│  )                                                             │
│  + search_literature()로 특정 테마 갭 보충                     │
└────────────────────────────────────────────────────────────────┘
    │
    ▼
┌── Step 4: 품질 반성 (think_tool) ──────────────────────────────┐
│  기준: papers ≥ 20, theme_coverage ≥ 3/4, mechanism_papers ≥ 5 │
│  미달 시 → 추가 검색 (최대 3회 반복)                            │
└────────────────────────────────────────────────────────────────┘
    │
    ▼
┌── Step 5: RAG 검증 + 업데이트 ─────────────────────────────────┐
│  5.1: write_file("/synthesis_papers.json")                     │
│       prepare_rag_literature(part_name="synthesis")            │
│       → 컬렉션: "deep_interpreter_synthesis" (독립 저장)        │
│       → 논문: {data_path}/papers/synthesis/ (별도 디렉토리)      │
│                                                                │
│  5.2: 각 핵심 종합 주장에 대해:                                 │
│       validate_claim_fulltext(claim, pmid, "synthesis")        │
│                                                                │
│  5.3: 신뢰도 기반 업데이트:                                     │
│       ≥ 0.7 → 유지 + PMID 인용 추가                            │
│       0.4~0.7 → 완화 표현 ("suggests", "consistent with")      │
│       < 0.4 → (Hypothesis) 또는 (Needs Validation)             │
│                                                                │
│  5.4: write_file("/synthesis_validation.json")                 │
│       {                                                        │
│         overall_confidence: 0.72,                              │
│         claims_validated: 14,                                  │
│         claims_by_status: {strong: 8, weak: 4, unsupported: 2},│
│         validation_results: [{section, claim, alignment,       │
│           confidence, supporting_pmids, recommendation}]       │
│       }                                                        │
│                                                                │
│  5.5: synthesis.md 최종 업데이트                                │
└────────────────────────────────────────────────────────────────┘
```

---

## 도구 상세

### `generate_html_report`

**파일**: `tools/report.py`

| 항목 | 설명 |
|------|------|
| 입력 | `parts: dict` (리포트 콘텐츠), `output_path: str` |
| 출력 | 상태 메시지 `"Report generated: {path} ({bytes} bytes)"` |

**두 가지 모드**:
- **Structured**: `part1`/`part2`/`part3` → `{analysis_name: {figure_path, interpretation, references}}`
- **HTML Override**: `part1_html`/`part2_html`/`part3_html`/`summary_html` 문자열

**내부 처리**:
1. CSS 로딩: `skills/html-report-generator/assets/theme.css` (503줄, 폴백 내장)
2. JS 로딩: `skills/html-report-generator/assets/interactive.js` (105줄, 폴백 내장)
3. 그림 Base64 인코딩: `_encode_image()` → `data:{mime};base64,{data}` URI
4. HTML 템플릿 채우기 → 파일 쓰기

### `search_literature_dynamic` (통합 검색용)

SEARCHER와 동일한 도구이지만, REPORTER는 **통합 중심 용어**로 검색:
- 개별 유전자가 아닌 유전자+경로+세포유형 조합
- 예: `"TGFb + EMT + fibroblast + breast cancer"`

### `prepare_rag_literature` + `validate_claim_fulltext`

INTERPRETER와 동일하지만 `part_name="synthesis"` 사용:
- 별도 디렉토리: `{data_path}/papers/synthesis/`
- 별도 RAG 컬렉션: `deep_interpreter_synthesis`
- Part별 증거와의 오염 방지

---

## HTML 리포트 구조

```
┌──────────────────────────────────────────────────┐
│  CCI_Analysis_Report.html (자체 완결형)           │
│                                                   │
│  <head>                                           │
│    theme.css 인라인 (다크 테마)                    │
│    interactive.js 인라인 (탭/페이지네이션)         │
│                                                   │
│  Header: 제목 (시안 글로우) + 부제목               │
│  Executive Summary: 그래디언트 배경 + 품질 뱃지    │
│  Analysis Config: 모드/타겟/디렉토리               │
│                                                   │
│  ┌── 탭 네비게이션 ──────────────────────────┐    │
│  │  [Part 1] [Part 2] [Part 3] [Summary]    │    │
│  │                                           │    │
│  │  Part 1-3 탭:                             │    │
│  │    .figure-container                      │    │
│  │      <img src="data:image/png;base64,..."> │    │
│  │    .interpretation (생물학적 해석)         │    │
│  │    .paper-card (PubMed 링크)              │    │
│  │                                           │    │
│  │  Summary 탭:                              │    │
│  │    종합 서사 + 품질 평가 + 참고문헌        │    │
│  └───────────────────────────────────────────┘    │
│                                                   │
│  Footer: "Generated by DeepMAST" + 타임스탬프      │
│                                                   │
│  색상: 배경 #1a1a2e→#16213e                       │
│  Primary: #64ffda (시안)                          │
│  Secondary: #ffd166 (옐로우)                      │
│  Accent: #ff6b9d (핑크)                           │
│                                                   │
│  그림: Base64 인코딩 (외부 파일 의존 없음)         │
└──────────────────────────────────────────────────┘
```

---

## 입출력 파일 계약

### 읽기 (Input)

| 가상 경로 | Phase | 소스 |
|----------|-------|------|
| `/part1_final.md` | 1 | INTERPRETER |
| `/part2_final.md` | 1 | INTERPRETER |
| `/part3_final.md` | 1 | INTERPRETER |
| `/interpretation_guide.md` | 1 | PLANNER |
| `/part1_papers.json` | 1 | SEARCHER |
| `/liana_papers.json` | 1 | SEARCHER |
| `/data_path.txt` | 1 | PLANNER |

### 쓰기 (Output)

| 가상 경로 | Phase | 내용 |
|----------|-------|------|
| `/synthesis.md` | 4 → 4.5 | 초안 → 검증 후 업데이트 |
| `/synthesis_search_context.json` | 4.5-1 | 추출된 통합 컨텍스트 |
| `/synthesis_search_strategy.json` | 4.5-2 | think_tool 전략 |
| `/synthesis_papers.json` | 4.5-5 | 독립 검색 논문 |
| `/synthesis_validation.json` | 4.5-5 | 주장별 검증 결과 |
| `CCI_Analysis_Report.html` | 5 | **최종 산출물** |

---

## 서브에이전트 비교

| 특성 | PLANNER | SEARCHER | INTERPRETER | **REPORTER** |
|------|---------|----------|-------------|-------------|
| 읽는 Part | 없음 | 없음 | 개별 Part | **모든 Part** |
| 검색 능력 | PubMed (10편) | Dynamic + E-utils | 없음 | Dynamic + 단일 |
| 검증 능력 | 없음 | 커버리지 | 주장 검증 + 품질 | **독립 주장 검증** |
| RAG 사용 | 없음 | 없음 | Part별 컬렉션 | **Synthesis 컬렉션** |
| 최종 산출물 | 가이드 | 논문 JSON | Part별 MD | **HTML 리포트** |

---

## 수정 가이드

### 안전한 수정

| 대상 | 파일 |
|------|------|
| HTML 테마 변경 | `skills/html-report-generator/assets/theme.css` (CSS 변수) |
| 탭 추가 | `tools/report.py` (`HTML_TEMPLATE` + `_generate_html_report_impl`) |
| Phase 4.5 신뢰도 기준 | `subagents/prompts.py` (REPORTER_PROMPT) |
| Phase 4.5 품질 기준 | `subagents/prompts.py` (≥20 papers, ≥3/4 themes) |
| synthesis.md 구조 | `subagents/prompts.py` (Phase 4 섹션) |

### 위험한 결합

| 대상 | 영향 |
|------|------|
| `_encode_image` 경로 | `load_analysis_data` 반환 경로와 일치 필요 |
| 가상 경로 해석 | `_resolve_papers_path` 3단계 폴백 체인 |
| CSS 폴백 | `report.py` 내장 CSS와 `theme.css` 수동 동기화 필요 |
| 프롬프트 길이 | REPORTER_PROMPT ~420줄, 작은 모델에서 지시 따르기 저하 가능 |
