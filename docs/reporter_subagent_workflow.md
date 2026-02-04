# REPORTER Subagent Workflow

REPORTER subagent의 구조, 워크플로우, 생성 파일에 대한 상세 문서입니다.

## 1. REPORTER Subagent 전체 구조

### 1.1 위치 및 역할

REPORTER는 Deep Interpreter의 4-Agent 아키텍처에서 **마지막 단계**를 담당하는 subagent입니다.

**아키텍처 구성:**
```
PLANNER → SEARCHER → INTERPRETER → REPORTER
```

### 1.2 설정 파일 위치

| 파일 경로 | 역할 |
|-----------|------|
| `src/agents/deep_interpreter/subagents/configs.py` | Subagent 설정 정의 |
| `src/agents/deep_interpreter/subagents/prompts.py` | System prompt 정의 |
| `src/agents/deep_interpreter/tools/report.py` | HTML 리포트 생성 도구 |

### 1.3 REPORTER 설정 (configs.py)

```python
"reporter": {
    "name": "reporter",
    "description": (
        "Synthesis and report generation agent. Reads all /partN_final.md files, "
        "identifies cross-part themes, validates synthesis claims with NEW literature search "
        "(following biomedical-literature-search workflow), and generates final HTML report. "
        "Phase 4.5 validates integration claims against independent literature sources. "
        "Outputs /synthesis.md, /synthesis_papers.json, /synthesis_validation.json, "
        "and CCI_Analysis_Report.html."
    ),
    "system_prompt": SUBAGENT_PROMPTS["reporter"],
    "tools": [
        # Core tools
        load_analysis_data,
        generate_html_report,
        # Literature search tools (reuse from SEARCHER for synthesis validation)
        search_literature_dynamic,
        search_literature_for_context,
        search_literature,
        # RAG validation tools
        prepare_rag_literature,
        validate_claim_fulltext,
        # Think tool for strategic planning and reflection
        think_tool,
    ],
}
```

### 1.4 사용 가능 도구

| 도구 | 용도 |
|------|------|
| `load_analysis_data` | 분석 결과 및 Figure 경로 로드 |
| `generate_html_report` | HTML 리포트 생성 |
| `search_literature_dynamic` | LLM-powered PubMed 검색 (Phase 4.5 synthesis validation) |
| `search_literature_for_context` | Context-based 검색 (fallback) |
| `search_literature` | 단일 쿼리 검색 (gap-filling) |
| `prepare_rag_literature` | Full-text 논문 다운로드 및 RAG 인덱싱 |
| `validate_claim_fulltext` | Full-text 기반 claim 검증 |
| `think_tool` | 전략적 계획 (Step 2) 및 품질 reflection (Step 4) |

---

## 2. 워크플로우 흐름도

### 2.1 REPORTER의 7-Phase 워크플로우 (Phase 4.5 추가)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Phase 1: READ ALL INPUTS                                                    │
│                                                                             │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐          │
│  │ /part1_final.md  │  │ /part2_final.md  │  │ /part3_final.md  │          │
│  │ (Spatial+Pathway)│  │ (CCI+NMF)        │  │ (L-R Details)    │          │
│  └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘          │
│           │                     │                     │                     │
│           └─────────────────────┼─────────────────────┘                     │
│                                 ▼                                           │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐          │
│  │/strategic_plan.md│  │/part1_papers.json│  │/liana_papers.json│          │
│  │ (Hypotheses)     │  │ (Part 1 refs)    │  │ (Part 2/3 refs)  │          │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘          │
│                                 │                                           │
│                                 ▼                                           │
│                      ┌──────────────────────┐                               │
│                      │   load_analysis_data │ → Figure paths                │
│                      └──────────────────────┘                               │
└─────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Phase 2: CROSS-PART SYNTHESIS                                               │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │ Theme 1: Spatial Organization                                 │          │
│  │   - Part 1 evidence → Part 2 CCI patterns → Integration       │          │
│  └──────────────────────────────────────────────────────────────┘          │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │ Theme 2: Cell Communication Axis                              │          │
│  │   - Key cell types + Key L-R pairs + Communication pattern    │          │
│  └──────────────────────────────────────────────────────────────┘          │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │ Theme 3: Pathway Integration                                  │          │
│  │   - Part 1 Decoupler → Part 2 L-R signaling → Connection      │          │
│  └──────────────────────────────────────────────────────────────┘          │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │ Theme 4: Disease Mechanism (optional)                         │          │
│  │   - Disease progression + Therapeutic implications            │          │
│  └──────────────────────────────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Phase 3: HYPOTHESIS VALIDATION                                              │
│                                                                             │
│  For each hypothesis from /strategic_plan.md:                               │
│                                                                             │
│  ┌────────────────┬─────────────────────┬─────────────────────────────┐    │
│  │   Hypothesis   │       Status        │         Evidence            │    │
│  ├────────────────┼─────────────────────┼─────────────────────────────┤    │
│  │      H1        │ Supported           │ Part 1-3 + Part 2-6 findings│    │
│  │      H2        │ Partially Supported │ Part 2-9 only               │    │
│  │      H3        │ Not Supported       │ No evidence found           │    │
│  └────────────────┴─────────────────────┴─────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Phase 4: WRITE SYNTHESIS (Draft)                                            │
│                                                                             │
│  Output: /synthesis.md (initial draft)                                      │
│                                                                             │
│  ├── # Integrated Biological Narrative                                      │
│  │   ├── ## Executive Summary                                               │
│  │   ├── ## Cross-Part Themes                                               │
│  │   │   ├── ### Theme 1: Spatial Organization                              │
│  │   │   ├── ### Theme 2: Cell Communication Axis                           │
│  │   │   ├── ### Theme 3: Pathway Integration                               │
│  │   │   └── ### Theme 4: Disease Mechanism                                 │
│  │   ├── ## Hypothesis Validation (Table)                                   │
│  │   ├── ## Clinical/Biological Implications                                │
│  │   ├── ## Limitations                                                     │
│  │   └── ## Novel Findings Summary                                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Phase 4.5: VALIDATE SYNTHESIS WITH LITERATURE (NEW)                         │
│                                                                             │
│  Purpose: Validate integration claims with INDEPENDENT literature search    │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │ Step 1: Extract Synthesis Context                             │          │
│  │   - Parse /synthesis.md → Extract genes, pathways, celltypes  │          │
│  │   - Output: /synthesis_search_context.json                    │          │
│  └──────────────────────────────────────────────────────────────┘          │
│                            │                                                │
│                            ▼                                                │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │ Step 2: Strategic Planning (think_tool x3)                    │          │
│  │   - Thought 1: Context Analysis                               │          │
│  │   - Thought 2: Search Strategy (INTEGRATION-focused)          │          │
│  │   - Thought 3: Expected Findings                              │          │
│  │   - Output: /synthesis_search_strategy.json                   │          │
│  └──────────────────────────────────────────────────────────────┘          │
│                            │                                                │
│                            ▼                                                │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │ Step 3: Search Literature                                     │          │
│  │   - search_literature_dynamic (integration-focused queries)   │          │
│  │   - Key difference: COMBINED terms (not Part-specific)        │          │
│  │   - Fallback: search_literature_for_context                   │          │
│  └──────────────────────────────────────────────────────────────┘          │
│                            │                                                │
│                            ▼                                                │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │ Step 4: Quality Reflection (think_tool)                       │          │
│  │   - Check coverage: >= 20 papers, >= 3/4 themes               │          │
│  │   - Gap-filling: search_literature for missing themes         │          │
│  │   - Max 3 iterations                                          │          │
│  └──────────────────────────────────────────────────────────────┘          │
│                            │                                                │
│                            ▼                                                │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │ Step 5: RAG Validate & Write                                  │          │
│  │   5.1: write_file("/synthesis_papers.json")                   │          │
│  │   5.2: prepare_rag_literature(part_name="synthesis")          │          │
│  │        → Papers stored in {data_path}/papers/synthesis/       │          │
│  │        → RAG collection: deep_interpreter_synthesis           │          │
│  │   5.3: validate_claim_fulltext for each Theme claim           │          │
│  │   5.4: Update /synthesis.md based on validation               │          │
│  │        - confidence >= 0.7: Keep + add PMID                   │          │
│  │        - 0.4 <= conf < 0.7: Add caveat                        │          │
│  │        - confidence < 0.4: Mark as (Hypothesis)               │          │
│  │   5.5: write_file("/synthesis_validation.json")               │          │
│  └──────────────────────────────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Phase 5: GENERATE HTML REPORT                                               │
│                                                                             │
│  Tool call: generate_html_report(parts={...}, output_path="...")            │
│                                                                             │
│  Output: CCI_Analysis_Report.html                                           │
│                                                                             │
│  ├── Header (Title, Subtitle, Date)                                         │
│  ├── Executive Summary (Quality Score Badge)                                │
│  ├── Analysis Configuration                                                 │
│  ├── Tabs Navigation                                                        │
│  │   ├── [Part 1: Spatial & Pathway] ← part1 dict or part1_html             │
│  │   ├── [Part 2: CCI & NMF]         ← part2 dict or part2_html             │
│  │   ├── [Part 3: L-R Interactions]  ← part3 dict or part3_html             │
│  │   └── [Comprehensive Summary]      ← synthesis or summary_html           │
│  └── Footer (Quality Metrics, Generation Info)                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Phase 6: VERIFICATION                                                       │
│                                                                             │
│  1. Confirm HTML file was created                                           │
│  2. Report file path to orchestrator                                        │
│  3. Summarize key findings and quality metrics                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 생성되는 파일들

### 3.1 REPORTER가 생성하는 파일

| 파일명 | 형식 | Phase | 설명 |
|--------|------|-------|------|
| `/synthesis.md` | Markdown | 4 (draft), 4.5 (updated) | 통합 생물학적 서술, Cross-part 테마, 가설 검증 결과 |
| `/synthesis_search_context.json` | JSON | 4.5 Step 1 | 추출된 integration terms (genes, pathways, celltypes) |
| `/synthesis_search_strategy.json` | JSON | 4.5 Step 2 | think_tool 기반 검색 전략 |
| `/synthesis_papers.json` | JSON | 4.5 Step 5 | Synthesis validation용 논문 (Part papers와 별도) |
| `/synthesis_validation.json` | JSON | 4.5 Step 5 | 상세 claim 검증 결과 |
| `CCI_Analysis_Report.html` | HTML | 5 | 최종 발행 품질 리포트 (Dark theme, 탭 네비게이션, 임베디드 Figure) |

### 3.2 Paper Storage 구조

**Phase 4.5에서 생성된 synthesis 논문은 Part 논문과 별도 폴더에 저장됩니다:**

```
{data_path}/papers/
├── part1/              # Part 1 spatial analysis 논문
├── part2/              # Part 2 CCI analysis 논문 (= liana)
├── part3/              # Part 3 L-R details 논문 (= liana와 공유)
└── synthesis/          # Phase 4.5: Synthesis validation 전용 논문
```

**RAG Collection 분리:**

| Collection Name | 용도 |
|-----------------|------|
| `deep_interpreter_part1` | Part 1 full-text |
| `deep_interpreter_part2` | Part 2 full-text |
| `deep_interpreter_part3` | Part 3 full-text |
| `deep_interpreter_synthesis` | Synthesis validation full-text |

### 3.3 REPORTER가 읽는 입력 파일

| 파일명 | 생성 주체 | 내용 |
|--------|-----------|------|
| `/part1_final.md` | INTERPRETER | Part 1 해석 (Spatial & Pathway) |
| `/part2_final.md` | INTERPRETER | Part 2 해석 (CCI & NMF) |
| `/part3_final.md` | INTERPRETER | Part 3 해석 (L-R Details) |
| `/strategic_plan.md` | PLANNER | 가설 및 해석 전략 |
| `/part1_papers.json` | SEARCHER | Part 1 문헌 참조 |
| `/liana_papers.json` | SEARCHER | Part 2/3 공유 문헌 참조 |
| `/data_path.txt` | PLANNER | Figure 경로를 위한 데이터 디렉토리 |

### 3.4 synthesis_validation.json 구조

```json
{
  "validation_timestamp": "2025-01-30T12:00:00",
  "overall_confidence": 0.72,
  "claims_validated": 14,
  "claims_by_status": {
    "strong": 8,
    "weak": 4,
    "unsupported": 2
  },
  "validation_results": [
    {
      "section": "Theme 4: Disease Mechanism",
      "claim": "TGF-β signaling drives EMT through spatial proximity",
      "alignment": "strong",
      "confidence": 0.85,
      "supporting_evidence": "Recent studies show that spatially proximate CAFs...",
      "supporting_pmids": ["38123456", "38234567"],
      "recommendation": "keep",
      "revision_applied": null
    },
    {
      "section": "Executive Summary",
      "claim": "Fibroblasts exclusively communicate with epithelial cells",
      "alignment": "weak",
      "confidence": 0.55,
      "supporting_evidence": "Macrophage-epithelial crosstalk is also observed...",
      "supporting_pmids": ["38345678"],
      "recommendation": "add_caveat",
      "revision_applied": "Changed 'exclusively' to 'predominantly'"
    }
  ],
  "search_summary": {
    "method": "dynamic",
    "papers_found": 28,
    "iterations": 2,
    "theme_coverage": {
      "Theme 1": 0.8,
      "Theme 2": 0.9,
      "Theme 3": 0.7,
      "Theme 4": 0.85
    }
  }
}
```

### 3.5 HTML Report 구조

```
CCI_Analysis_Report.html
├── <head>
│   └── CSS (Dark theme: #1a1a2e 배경, #64ffda 강조)
├── <body>
│   ├── .container
│   │   ├── <h1> Title
│   │   ├── .subtitle
│   │   ├── .summary-box (Executive Summary)
│   │   ├── .analysis-section (Configuration)
│   │   ├── .tabs (Navigation)
│   │   │   ├── [Part 1: Spatial & Pathway]
│   │   │   ├── [Part 2: CCI & NMF]
│   │   │   ├── [Part 3: L-R Interactions]
│   │   │   └── [Comprehensive Summary]
│   │   ├── #part1.tab-content
│   │   ├── #part2.tab-content
│   │   ├── #part3.tab-content
│   │   ├── #summary.tab-content
│   │   └── .metadata (Footer)
│   └── <script> (Tab navigation, Pagination)
```

### 3.6 HTML CSS 클래스 (LLM 생성 HTML용)

| CSS 클래스 | 용도 | 스타일 |
|------------|------|--------|
| `.highlight-cluster` | 클러스터명 강조 | Yellow (#ffd166) |
| `.highlight-pathway` | Pathway명 강조 | Pink (#ff6b9d) |
| `.highlight-celltype` | 세포 유형 강조 | Cyan (#64ffda) |
| `.pathway-box` | Pathway 설명 박스 | Yellow border |
| `.key-findings` | 주요 발견 목록 | Pink border |
| `.interpretation` | 해석 블록 | Cyan border |
| `.analysis-section` | 섹션 컨테이너 | Cyan left border |
| `.score-badge` | 품질 점수 배지 | high/medium/low 색상 |

---

## 4. 다른 Subagent들과의 관계

### 4.1 4-Agent 워크플로우 의존성

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           DEEP INTERPRETER WORKFLOW                          │
│                                                                              │
│  ┌──────────────┐                                                            │
│  │   PLANNER    │ ─────────────────────────────────────────────────────────┐│
│  │              │                                                          ││
│  │ Inputs:      │  Outputs:                                                ││
│  │ /targets.json│  /strategic_plan.md ──────────────────────────────────┐  ││
│  │              │  /analysis_summary.md                                 │  ││
│  │              │  /data_path.txt ──────────────────────────────────┐   │  ││
│  └──────────────┘                                                   │   │  ││
│         │                                                           │   │  ││
│         ▼                                                           │   │  ││
│  ┌──────────────┐                                                   │   │  ││
│  │   SEARCHER   │                                                   │   │  ││
│  │              │                                                   │   │  ││
│  │ Inputs:      │  Outputs:                                         │   │  ││
│  │ /data_path   │  /part1_papers.json ─────────────────────────┐    │   │  ││
│  │ (from PLANNER)  /liana_papers.json ─────────────────────┐   │    │   │  ││
│  │              │                                          │   │    │   │  ││
│  └──────────────┘                                          │   │    │   │  ││
│         │                                                  │   │    │   │  ││
│         ▼                                                  │   │    │   │  ││
│  ┌──────────────┐                                          │   │    │   │  ││
│  │  INTERPRETER │                                          │   │    │   │  ││
│  │              │                                          │   │    │   │  ││
│  │ Inputs:      │  Outputs:                                │   │    │   │  ││
│  │ papers.json ◄┼──────────────────────────────────────────┼───┘    │   │  ││
│  │ strategic_plan◄─────────────────────────────────────────┼────────┘   │  ││
│  │              │  /part1_final.md ───────────────────┐    │            │  ││
│  │              │  /part2_final.md ───────────────────┼────┼────────┐   │  ││
│  │              │  /part3_final.md ───────────────────┼────┼────────┼───┘  ││
│  └──────────────┘                                     │    │        │      ││
│         │                                             │    │        │      ││
│         ▼                                             ▼    ▼        ▼      ▼│
│  ┌──────────────────────────────────────────────────────────────────────────┤
│  │                          REPORTER                                        │
│  │                                                                          │
│  │ Inputs:                                                                  │
│  │  ├── /part1_final.md      (from INTERPRETER)                             │
│  │  ├── /part2_final.md      (from INTERPRETER)                             │
│  │  ├── /part3_final.md      (from INTERPRETER)                             │
│  │  ├── /strategic_plan.md   (from PLANNER)                                 │
│  │  ├── /part1_papers.json   (from SEARCHER)                                │
│  │  ├── /liana_papers.json   (from SEARCHER)                                │
│  │  └── /data_path.txt       (from PLANNER)                                 │
│  │                                                                          │
│  │ Outputs:                                                                 │
│  │  ├── /synthesis.md (Phase 4 draft + Phase 4.5 updated)                  │
│  │  ├── /synthesis_papers.json (Phase 4.5)                                 │
│  │  ├── /synthesis_validation.json (Phase 4.5)                             │
│  │  └── CCI_Analysis_Report.html (Phase 5)                                 │
│  └──────────────────────────────────────────────────────────────────────────┘
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 데이터 흐름 요약

| From | To | Data |
|------|----|------|
| PLANNER | REPORTER | `/strategic_plan.md` (가설 검증용) |
| PLANNER | REPORTER | `/data_path.txt` (Figure 경로용) |
| SEARCHER | REPORTER | `/part1_papers.json`, `/liana_papers.json` (참조 문헌) |
| INTERPRETER | REPORTER | `/part1_final.md`, `/part2_final.md`, `/part3_final.md` (해석 내용) |

### 4.3 각 Subagent 역할 비교

| Subagent | 주요 역할 | 도구 | 출력 |
|----------|----------|------|------|
| **PLANNER** | 타겟 확인 + 가설 생성 | `load_analysis_data` | strategic_plan.md, analysis_summary.md, data_path.txt |
| **SEARCHER** | 문헌 검색 (사전 검색) | `search_literature_dynamic`, `search_literature`, `think_tool` | part1_papers.json, liana_papers.json |
| **INTERPRETER** | Part 1/2/3 해석 + 검증 | `validate_claim_literature`, `validate_quality`, `think_tool`, RAG tools | part1_final.md, part2_final.md, part3_final.md |
| **REPORTER** | 통합 + **Synthesis validation** + HTML 리포트 | `load_analysis_data`, `generate_html_report`, `search_literature_dynamic`, RAG tools, `think_tool` | synthesis.md, synthesis_papers.json, synthesis_validation.json, CCI_Analysis_Report.html |

---

## 5. generate_html_report 도구 상세

### 5.1 함수 시그니처

```python
@tool
def generate_html_report(
    parts: dict,
    output_path: str,
) -> str:
```

### 5.2 parts 파라미터 구조

```python
parts = {
    # 필수 필드
    "title": "CCI Analysis Report",
    "subtitle": "Comprehensive Cell-Cell Interaction Analysis",
    "executive_summary": "<HTML allowed>",
    "analysis_config": "<HTML allowed>",
    "part1": {
        "1-1 Spatial Clustering": {
            "figure_path": "/absolute/path/to/figure.png",
            "interpretation": "<interpretation text>",
            "caption": "Figure caption",
            "references": [{"pmid": "12345678", "title": "Paper title"}]
        },
        "1-2 Cell Type Composition": {...},
        # ...
    },
    "part2": {...},
    "part3": {...},
    "synthesis": "<synthesis narrative>",
    "quality_score": 0.85,  # 0.0-1.0
    "references": [{"pmid": "...", "title": "..."}],

    # 선택적 HTML 오버라이드 필드 (LLM 생성 HTML용)
    "part1_html": "<complete HTML for Part 1>",
    "part2_html": "<complete HTML for Part 2>",
    "part3_html": "<complete HTML for Part 3>",
    "summary_html": "<complete HTML for Summary>",
}
```

### 5.3 Figure 임베딩

`generate_html_report`는 Figure를 Base64 인코딩하여 HTML에 직접 임베딩합니다.

```python
def _encode_image(image_path: str) -> Optional[str]:
    """Encode an image as Base64 data URI."""
    # 지원 형식: PNG, JPG, JPEG, GIF, SVG
    mime_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".svg": "image/svg+xml",
    }
```

---

## 6. 독립 실행 (테스트용)

REPORTER subagent는 독립적으로 테스트할 수 있습니다.

### 6.1 LangGraph CLI 등록

`src/agents/deep_interpreter/graph_builder.py`:

```python
def _get_reporter_subagent_graph() -> Runnable:
    """Standalone REPORTER subagent graph - for LangGraph CLI."""
    provider = os.getenv("LLM_PROVIDER", "openai")
    return create_subagent_graph("reporter", provider=provider)

reporter_subagent_graph = _get_reporter_subagent_graph()
```

### 6.2 테스트 실행

```bash
# langgraph.json에 등록된 경우
langgraph dev --graph reporter_subagent_graph
```

---

## 7. Phase 4.5: Synthesis Validation 상세

### 7.1 목적

Synthesis claims는 Part 1-3의 개별 findings를 통합하여 **새로운 생물학적 메커니즘**을 제안합니다.
기존 Part-specific papers (part1_papers.json, liana_papers.json)는 개별 컴포넌트용이며,
통합 메커니즘을 다루는 논문이 아닙니다.

Phase 4.5는 이러한 **integration claims**를 독립적인 문헌 검색으로 검증합니다.

### 7.2 SEARCHER vs REPORTER 검색 차이

| 구분 | SEARCHER | REPORTER (Phase 4.5) |
|------|----------|---------------------|
| 목적 | Part-specific interpretation | Integration validation |
| 검색 대상 | Part 1 또는 Part 2/3 | Themes 1-4 통합 |
| 쿼리 포커스 | 개별 genes/pathways | **COMBINED** terms |
| 예시 쿼리 | "TGFB1 TGFb signaling" | "TGF-beta EMT spatial tumor microenvironment" |
| 출력 | part1_papers.json, liana_papers.json | synthesis_papers.json |
| 저장 위치 | papers/part1/, papers/liana/ | papers/synthesis/ |

### 7.3 5-Step Workflow

```
Step 1: Extract Context
    ↓  Parse /synthesis.md → /synthesis_search_context.json
Step 2: Strategic Planning
    ↓  think_tool x3 → /synthesis_search_strategy.json
Step 3: Search Literature
    ↓  search_literature_dynamic (integration-focused)
Step 4: Quality Reflection
    ↓  think_tool (coverage check, gap-filling)
Step 5: RAG Validate & Write
    ↓  prepare_rag_literature → validate_claim_fulltext
    ↓  Update /synthesis.md, Write outputs
```

### 7.4 Quality Criteria

| Criterion | Threshold | Action if Failed |
|-----------|-----------|------------------|
| Total Papers | >= 20 | Broaden integration terms |
| Theme Coverage | >= 3/4 themes | Targeted theme-specific search |
| Mechanism Papers | >= 5 | Add mechanism keywords |
| Max Iterations | 3 | Proceed with warning |

### 7.5 Validation Confidence Levels

| Confidence | Action |
|------------|--------|
| >= 0.7 | Keep claim + add PMID citation |
| 0.4 - 0.7 | Add caveat ("suggests", "consistent with") |
| < 0.4 | Mark as **(Hypothesis)** or **(Needs Validation)** |

---

## 8. 핵심 요약

| 항목 | 내용 |
|------|------|
| **역할** | Cross-part 통합 + **Synthesis validation** + 가설 검증 + HTML 리포트 생성 |
| **입력** | 3개의 part_final.md, strategic_plan.md, papers.json 파일들 |
| **출력** | synthesis.md, synthesis_papers.json, synthesis_validation.json, CCI_Analysis_Report.html |
| **도구** | `load_analysis_data`, `generate_html_report`, `search_literature_dynamic`, `prepare_rag_literature`, `validate_claim_fulltext`, `think_tool` |
| **특징** | Dark theme HTML, Base64 Figure 임베딩, 탭 네비게이션, **Phase 4.5 synthesis validation** |
| **의존성** | PLANNER, SEARCHER, INTERPRETER의 모든 출력에 의존 (최종 단계) |
| **NEW Phase 4.5** | Integration claims를 독립 문헌으로 검증, 별도 papers/synthesis/ 폴더에 저장 |

---

## 관련 문서

- [Deep Interpreter Overview](./deep_interpreter_overview.md)
- [Deep Interpreter Architecture](./deep_interpreter_architecture.md)
- [Interpreter Subagent Workflow](./interpreter_subagent_workflow.md)
- [Literature Search Strategy](./literature_search_strategy.md)
