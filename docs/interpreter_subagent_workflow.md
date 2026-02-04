# INTERPRETER Subagent 실행 순서

> Tool Calling & File I/O 중심의 상세 워크플로우 가이드

## 목차

- [개요](#개요)
- [전체 흐름 다이어그램](#전체-흐름-다이어그램)
- [Phase 0: RAG Preparation](#phase-0-rag-preparation)
- [Phase 1: Load Context](#phase-1-load-context)
- [Phase 2: Generate Interpretation](#phase-2-generate-interpretation)
- [Phase 3: Claim Validation](#phase-3-claim-validation)
- [Phase 4: Quality Check](#phase-4-quality-check)
- [Phase 5: Write Final](#phase-5-write-final)
- [Part별 실행 순서](#part별-실행-순서)
- [Tool Calling 타임라인](#tool-calling-타임라인)
- [파일 I/O 요약](#파일-io-요약)

---

## 개요

INTERPRETER subagent는 Deep Interpreter의 4-agent 아키텍처 중 핵심 해석 담당 에이전트입니다.

### 역할
- Part 1/2/3 분석 결과의 문헌 기반 해석 생성
- 인라인 claim validation (모든 PMID 검증)
- 품질 루프를 통한 해석 품질 보장 (score ≥ 0.7)

### 입력
| 파일 | 용도 |
|------|------|
| `/part1_papers.json` | Part 1 citation source |
| `/liana_papers.json` | Part 2/3 공유 citation source |
| `/strategic_plan.md` | 가설 확인 |
| `/data_path.txt` | 실제 데이터 경로 |

### 출력
| 파일 | 내용 |
|------|------|
| `/part1_final.md` | Part 1 최종 해석 |
| `/part2_final.md` | Part 2 최종 해석 |
| `/part3_final.md` | Part 3 최종 해석 |

---

## 전체 흐름 다이어그램

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  INTERPRETER EXECUTION FLOW (per Part)                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Phase 0: RAG Preparation                                                    │
│  ─────────────────────────────────────────────────────────────────────────  │
│  📖 READ: /partN_papers.json (or /liana_papers.json)                        │
│  🔧 TOOL: prepare_rag_literature(papers_json_path, part_name)               │
│       └── Internal: download_papers_for_rag() → MCP call                    │
│       └── Internal: index_papers_to_vectordb() → MCP call                   │
│  💾 SAVE: res/papers/pmid_*.txt (다운로드된 전문)                            │
│  ⚙️ STATE: rag_mode = True/False 결정                                       │
│                                                                              │
│  Phase 1: Load Context                                                       │
│  ─────────────────────────────────────────────────────────────────────────  │
│  📖 READ: /partN_papers.json (citation source)                              │
│  📖 READ: /strategic_plan.md (가설 확인)                                     │
│  📖 READ: /data_path.txt (실제 데이터 경로)                                  │
│  🔧 TOOL: load_analysis_data(data_path)                                     │
│       └── Returns: figures, summaries, search_context                       │
│                                                                              │
│  Phase 2: Generate Interpretation                                            │
│  ─────────────────────────────────────────────────────────────────────────  │
│  📝 LLM: 해석 텍스트 생성 (PMID 인용 포함)                                   │
│  🔧 TOOL (Optional, RAG Mode): search_literature_fulltext(query, part_name) │
│       └── 전문에서 supporting context 검색                                   │
│                                                                              │
│  Phase 3: Claim Validation (per claim with PMID)                            │
│  ─────────────────────────────────────────────────────────────────────────  │
│  [RAG Mode]                                                                  │
│  🔧 TOOL: validate_claim_fulltext(claim, pmid, part_name)                   │
│       └── Returns: {valid, confidence, supporting_text, source}             │
│                                                                              │
│  [Abstract Mode]                                                             │
│  🔧 TOOL: validate_claim_literature(claim, pmid, paper_abstract)            │
│       └── Returns: {alignment, evidence_quote, recommendation, confidence}  │
│                                                                              │
│  Phase 4: Quality Check                                                      │
│  ─────────────────────────────────────────────────────────────────────────  │
│  🔧 TOOL: validate_quality(interpretation, references, use_llm=True)        │
│       └── Returns: {score, statistics_score, references_score, ...}         │
│  🔧 TOOL (Optional): think_tool(reflection) - 품질 반성                      │
│                                                                              │
│  ┌── score < 0.7? ──────────────────────────────────────────────────────┐   │
│  │   └── iteration < 3? → Phase 2로 돌아가서 개선                         │   │
│  │   └── iteration >= 3? → 현재 상태로 진행                               │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  Phase 5: Write Final                                                        │
│  ─────────────────────────────────────────────────────────────────────────  │
│  💾 SAVE: /partN_final.md (Virtual Filesystem)                              │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Phase 0: RAG Preparation

### 목적
RAG(Retrieval-Augmented Generation) 인프라를 준비하여 전문 기반 검증을 활성화합니다.

### 선행 조건
- Docker 컨테이너 실행 중
- `langconnect-rag` 서버 (http://localhost:8080)
- `pubmed-download` MCP 서버 (http://localhost:8001/mcp)

### Tool Calling 순서

```python
# Step 0-1: papers.json 읽기
📖 read_file("/part1_papers.json")
   └── papers 배열 + coverage 메트릭 로드

# Step 0-2: RAG 준비
🔧 prepare_rag_literature(
       papers_json_path="res/part1_papers.json",
       part_name="part1"
   )
```

### Internal Process

```
prepare_rag_literature()
    │
    ├── [Internal] check_rag_availability()
    │   └── MCP: langconnect-rag health check
    │
    ├── [Internal] download_papers_for_rag(pmids)
    │   └── MCP: pubmed-download → download_paper(pmid, output_path)
    │   💾 SAVE: res/papers/pmid_12345678.txt (per paper)
    │   💾 SAVE: res/papers/pmid_23456789.txt
    │   └── ... (최대 30개)
    │
    └── [Internal] index_papers_to_vectordb(file_paths, "part1")
        └── MCP: langconnect-rag → create_collection()
        └── MCP: langconnect-rag → add_documents_from_files()
        └── Returns: {rag_mode: True, collection_id: "xxx", ...}
```

### 출력

```json
{
    "rag_mode": true,
    "collection_id": "deep_interpreter_part1",
    "papers_count": 20,
    "fulltext_count": 18,
    "fulltext_ratio": 0.9,
    "message": "RAG ready: 18/20 papers indexed"
}
```

### RAG vs Abstract 모드 결정

| 조건 | 결과 |
|------|------|
| RAG 인프라 정상 + 다운로드 성공 | `rag_mode = True` |
| RAG 인프라 없음 또는 다운로드 실패 | `rag_mode = False` (Abstract 모드) |

---

## Phase 1: Load Context

### 목적
해석에 필요한 모든 컨텍스트 정보를 로드합니다.

### Tool Calling 순서

```python
# Step 1-1: 전략 계획 읽기
📖 read_file("/strategic_plan.md")
   └── 가설 H1, H2, H3 확인

# Step 1-2: 데이터 경로 읽기
📖 read_file("/data_path.txt")
   └── 실제 경로: "res/" 또는 "/path/to/data"

# Step 1-3: 분석 데이터 로드
🔧 load_analysis_data(data_path="res/")
   └── Returns:
       {
         "figures": {
           "1.spatial.png": "/abs/path/res/1.spatial.png",
           "2.celltype_composition.png": "...",
           "3.neighborhood_enrichment.png": "...",
           "4.decoupler_pathway.png": "...",
           "5.misty.png": "..."
         },
         "spatial_search_context": {...},
         "analysis_summary": "Part 1 analyses: ..."
       }
```

### Papers JSON 구조

```json
{
  "part": 1,
  "analysis_type": "Spatial & Pathway Analysis",
  "search_method": "search_literature_dynamic",
  "papers": [
    {
      "pmid": "38341519",
      "title": "Targeting M2-like tumor-associated macrophages...",
      "abstract": "Tumor drug resistance emerges from...",
      "authors": ["Wang S", "Wang J", ...],
      "journal": "NPJ Precis Oncol",
      "date": "2024-02-10T00:00:00Z",
      "search_type": "pathway_celltype"
    }
  ],
  "coverage": {
    "total_papers": 20,
    "pathway_coverage": 0.55,
    "gene_coverage": 0.65
  }
}
```

---

## Phase 2: Generate Interpretation

### 목적
분석 결과에 대한 문헌 기반 해석을 생성합니다.

### Citation Format 규칙

| 상황 | 포맷 |
|------|------|
| 문헌 지원 있음 | `"CDH1 enrichment indicates epithelial identity (PMID: 12345678)."` |
| 문헌 지원 없음 | `"This spatial pattern **(Novel Finding)** has not been reported."` |

### Tool Calling (RAG Mode)

```python
# (Optional) 전문에서 supporting context 검색
🔧 search_literature_fulltext(
       query="CDH1 epithelial marker breast cancer",
       part_name="part1",
       limit=5
   )
   └── Returns: [
       {
           "page_content": "CDH1 (E-cadherin) is a hallmark...",
           "metadata": {"source": "pmid_38341519.txt"},
           "score": 0.85
       }
   ]
```

### 생성되는 해석 구조

```markdown
### Analysis 1-1: Spatial Clustering

#### Figure Description
{Figure 설명, 파일 경로}

#### Quantitative Findings
- Finding 1: {구체적 통계, e.g., "p < 0.001", "2.5-fold enrichment"}
- Finding 2: {또 다른 정량적 관찰}

#### Biological Interpretation
{문헌 기반 해석 - PMID 인용 포함}
"The enrichment of CDH1 in cluster 4 (p < 0.001) suggests epithelial
identity, consistent with E-cadherin's role (PMID: 38341519)."

{지원 문헌 없으면}
"Interestingly, this spatial gradient **(Novel Finding)** has not
been previously reported."
```

---

## Phase 3: Claim Validation

### 목적
생성된 해석의 각 PMID 인용이 실제 논문 내용과 일치하는지 검증합니다.

### RAG Mode 검증

```python
🔧 validate_claim_fulltext(
       claim="CDH1 enrichment indicates epithelial identity",
       pmid="38341519",
       part_name="part1"
   )
   └── Returns:
       {
           "valid": True,
           "confidence": 0.85,
           "supporting_text": "CDH1 (E-cadherin) is a hallmark...",
           "source": "full_text"
       }
```

### Abstract Mode 검증

```python
# 먼저 paper abstract 추출
📖 Extract paper_abstract from /part1_papers.json for pmid="38341519"

🔧 validate_claim_literature(
       claim="CDH1 enrichment indicates epithelial identity",
       pmid="38341519",
       paper_abstract="CDH1, encoding E-cadherin, is essential for..."
   )
   └── Returns:
       {
           "alignment": "strong",
           "evidence_quote": "CDH1 is essential for maintaining...",
           "recommendation": "keep",
           "confidence": 0.82,
           "reasoning": "Matched 4/5 terms: cdh1, epithelial, identity, enrichment"
       }
```

### Alignment 해석

| alignment | recommendation | 조치 |
|-----------|----------------|------|
| `strong` | `keep` | 인용 유지 |
| `weak` | `keep` | 유지하되 추가 참조 고려 |
| `unsupported` | `revise` | claim 수정 필요 |
| `unsupported` | `mark_novel` | `(Novel Finding)` 태그 |

### 검증 결과 집계

```python
# 여러 claim 검증 후 요약
summary = get_claim_validation_summary(validation_results)
# Returns:
{
    "total_claims": 5,
    "strong_support": 3,
    "weak_support": 1,
    "unsupported": 1,
    "needs_revision": 0,
    "novel_findings": 1,
    "overall_confidence": 0.78
}
```

---

## Phase 4: Quality Check

### 목적
해석의 품질을 4가지 기준으로 평가하고, threshold(0.7) 미달 시 개선 루프를 실행합니다.

### Quality Criteria

| Criterion | Weight | 체크 방법 |
|-----------|--------|-----------|
| `statistics` | 0.25 | 정량적 통계 패턴 (p-값, fold change, %) |
| `references` | 0.25 | PMID 인용 패턴 |
| `mechanism` | 0.25 | 생물학적 키워드 (signaling, pathway, receptor) |
| `specificity` | 0.25 | 모호한 표현 검출 (negative) |

### Tool Calling

```python
🔧 validate_quality(
       interpretation="### Analysis 1-1: Spatial Clustering\n...",
       references=[
           {"pmid": "38341519", "title": "Targeting M2-like TAMs..."},
           {"pmid": "39834406", "title": "The role of cell cycle..."}
       ],
       use_llm=True  # reflection-tool MCP 사용
   )
   └── Returns:
       {
           "score": 0.76,
           "statistics_score": 0.75,
           "references_score": 0.80,
           "mechanism_score": 0.85,
           "specificity_score": 0.65,
           "feedback": "Make claims more specific",
           "passed": True
       }
```

### Quality Loop

```
┌─────────────────────────────────────────────────────┐
│  Quality Loop (max 3 iterations)                     │
├─────────────────────────────────────────────────────┤
│                                                      │
│  Iteration 1:                                        │
│    🔧 validate_quality() → score = 0.65             │
│    ❌ score < 0.7 → 개선 필요                        │
│    🔧 think_tool() → 개선 방향 도출                  │
│    📝 LLM → 해석 개선                                │
│                                                      │
│  Iteration 2:                                        │
│    🔧 validate_quality() → score = 0.72             │
│    ✅ score >= 0.7 → 통과                            │
│    → Phase 5로 진행                                  │
│                                                      │
└─────────────────────────────────────────────────────┘
```

### Think Tool (Optional)

```python
🔧 think_tool(
       reflection="""
       Current Score: 0.65
       Statistics Score: 0.50
       What areas need improvement?
       """
   )
   └── Returns: LLM reflection on quality improvement
```

---

## Phase 5: Write Final

### 목적
최종 해석을 `/partN_final.md` 파일로 저장합니다.

### 파일 구조

```markdown
# Part N: {Title}

## Analysis N-X: {Name}

### Figure Description
{Figure 설명, 파일 경로}

### Quantitative Findings
- Finding 1: {구체적 통계}
- Finding 2: {또 다른 정량적 관찰}

### Biological Interpretation
{PMID 인용 포함 해석}
{Novel Finding 태그 포함}

---

## Part N Summary

### Key Findings
1. {주요 발견 + PMID}
2. {Novel Finding 포함}

### Hypothesis Status
- H1: **Supported/Partially Supported/Not Supported** - {설명}

### Quality Metrics
- Statistics included: {count}
- Literature citations: {count PMIDs}
- Novel findings: {count}
- Quality score: {0.76}

### Validation Notes
All PMID citations validated:
- PMID XXXXXXXX: {alignment status}
```

### Tool Calling

```python
# Virtual Filesystem에 저장
💾 write_file("/part1_final.md", content)
   └── 실제 경로: DeepAgents workspace
```

---

## Part별 실행 순서

### Part 1 (Spatial & Pathway)

```
📖 read_file("/part1_papers.json")
🔧 prepare_rag_literature("res/part1_papers.json", "part1")
    └── 💾 res/papers/pmid_*.txt × N
📖 read_file("/strategic_plan.md")
📖 read_file("/data_path.txt")
🔧 load_analysis_data("res/")

[Analysis 1-1 ~ 1-5]
├── 🔧 search_literature_fulltext() (Optional, RAG)
├── 📝 Generate interpretation
├── 🔧 validate_claim_fulltext() or validate_claim_literature()
└── 🔧 validate_quality()

💾 write_file("/part1_final.md")
```

### Part 2 (CCI & NMF)

```
📖 read_file("/liana_papers.json")  ◀── Part 2/3 공유
🔧 prepare_rag_literature("res/liana_papers.json", "liana")
    └── 💾 res/papers/pmid_*.txt × M
🔧 load_analysis_data("res/")

[Analysis 2-6 ~ 2-9]
├── 🔧 validate_claim_fulltext(..., "liana")
└── ...

💾 write_file("/part2_final.md")
```

### Part 3 (L-R Details)

```
📖 read_file("/liana_papers.json")  ◀── 동일 파일
🔧 prepare_rag_literature("res/liana_papers.json", "liana")
    └── (CACHE HIT - 이미 인덱싱됨)
🔧 load_analysis_data("res/")

[Analysis 3-10 ~ 3-11]
├── 🔧 validate_claim_fulltext(..., "liana")  ◀── 동일 collection
└── ...

💾 write_file("/part3_final.md")
```

---

## Tool Calling 타임라인

```
Timeline: INTERPRETER for Part 1 + Part 2 + Part 3
══════════════════════════════════════════════════════════════════════════════

T0: Part 1 시작
├── 📖 read_file("/part1_papers.json")
├── 🔧 prepare_rag_literature("res/part1_papers.json", "part1")
│       └── 💾 res/papers/pmid_*.txt × N (다운로드)
├── 📖 read_file("/strategic_plan.md")
├── 📖 read_file("/data_path.txt")
├── 🔧 load_analysis_data("res/")
│
├── [Analysis 1-1]
│   ├── 🔧 search_literature_fulltext("spatial clustering breast", "part1")
│   ├── 📝 Generate interpretation
│   ├── 🔧 validate_claim_fulltext(claim1, pmid1, "part1")
│   ├── 🔧 validate_claim_fulltext(claim2, pmid2, "part1")
│   └── 🔧 validate_quality(...)
│
├── [Analysis 1-2 ~ 1-5] (동일 패턴 반복)
│
├── 🔧 validate_quality(full_part1_interpretation, refs)
│   └── [If score < 0.7] 🔧 think_tool() → retry
│
└── 💾 write_file("/part1_final.md")

─────────────────────────────────────────────────────────────────────────────

T1: Part 2 시작
├── 📖 read_file("/liana_papers.json")
├── 🔧 prepare_rag_literature("res/liana_papers.json", "liana")
│       └── 💾 res/papers/pmid_*.txt × M (다운로드)
├── 🔧 load_analysis_data("res/")
│
├── [Analysis 2-6 ~ 2-9]
│   ├── 🔧 validate_claim_fulltext(..., "liana")
│   └── ...
│
└── 💾 write_file("/part2_final.md")

─────────────────────────────────────────────────────────────────────────────

T2: Part 3 시작
├── 📖 read_file("/liana_papers.json")  (동일)
├── 🔧 prepare_rag_literature("res/liana_papers.json", "liana")
│       └── (CACHE HIT - 이미 인덱싱됨)
├── 🔧 load_analysis_data("res/")
│
├── [Analysis 3-10 ~ 3-11]
│   ├── 🔧 validate_claim_fulltext(..., "liana")  (동일 collection)
│   └── ...
│
└── 💾 write_file("/part3_final.md")

══════════════════════════════════════════════════════════════════════════════
```

---

## 파일 I/O 요약

### 읽기 (READ)

| 시점 | 파일 | 용도 |
|------|------|------|
| Phase 0 | `/part1_papers.json` | PMID 목록 추출 (RAG 준비) |
| Phase 0 | `/liana_papers.json` | Part 2/3 공유 PMID 목록 |
| Phase 1 | `/strategic_plan.md` | 가설 H1, H2, H3 확인 |
| Phase 1 | `/data_path.txt` | 실제 데이터 경로 |
| Phase 3 | `/partN_papers.json` | paper_abstract 추출 (Abstract 모드) |

### 쓰기 (WRITE)

| 시점 | 파일 | 위치 | 용도 |
|------|------|------|------|
| Phase 0 | `pmid_*.txt` | `res/papers/` | 전문 다운로드 |
| Phase 5 | `part1_final.md` | Virtual FS (`/`) | Part 1 최종 해석 |
| Phase 5 | `part2_final.md` | Virtual FS (`/`) | Part 2 최종 해석 |
| Phase 5 | `part3_final.md` | Virtual FS (`/`) | Part 3 최종 해석 |

---

## Tool Calling 횟수 예상

### Part 당 호출 횟수

| Tool | 호출 횟수 | 조건 |
|------|----------|------|
| `prepare_rag_literature` | 1 | RAG 모드 시 |
| `load_analysis_data` | 1 | 항상 |
| `search_literature_fulltext` | 0-5 | RAG 모드 + 필요시 |
| `validate_claim_fulltext` | 2-10 | RAG 모드, claim 수에 비례 |
| `validate_claim_literature` | 2-10 | Abstract 모드, claim 수에 비례 |
| `validate_quality` | 1-3 | 품질 루프 (최대 3회) |
| `think_tool` | 0-2 | 품질 미달 시 |

### 총 Tool Calls (3 Parts)

| 모드 | 예상 호출 횟수 |
|------|----------------|
| RAG Mode | ~45-60 calls |
| Abstract Mode | ~30-45 calls |

---

## 관련 문서

- [Deep Interpreter Overview](./deep_interpreter_overview.md)
- [Literature Search Strategy](./literature_search_strategy.md)

## 테스트

INTERPRETER 워크플로우를 직접 테스트하려면:

```bash
jupyter notebook notebook/test_interpreter_steps.ipynb
```
