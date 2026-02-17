> **DEPRECATED**: 종합 레퍼런스는 [interpreter_subagent_reference.md](interpreter_subagent_reference.md)를 참조하세요.
> 이 문서는 RAG 구현 디버깅용 상세 정보를 위해 보존됩니다.

# INTERPRETER Subagent RAG Mode Workflow

> Full-text 기반 문헌 검증을 통한 고정확도 해석 생성 워크플로우

## 1. 개요: Abstract Mode vs RAG Mode

DeepMAST의 INTERPRETER subagent는 두 가지 문헌 검증 모드를 지원합니다.

### 모드 비교표

| 기능 | Abstract Mode (기본) | RAG Mode (향상) |
|------|---------------------|-----------------|
| **데이터 소스** | PubMed 초록만 | 논문 전문 (Full-text) |
| **검증 도구** | `validate_claim_literature` | `validate_claim_fulltext` |
| **검색 도구** | 해당 없음 (초록 직접 사용) | `search_literature_fulltext` |
| **Citation Accuracy** | ~70% | ~90% |
| **Pathway Coverage** | ~32% | ~70-85% |
| **Supporting Text** | 일반적인 초록 내용 | 구체적인 논문 구절 |
| **인프라 요구사항** | BioMCP만 필요 | BioMCP + Docker + MCP servers |
| **설정 시간** | 즉시 | 초기 다운로드/인덱싱 필요 |

### 모드 선택 기준

- **Abstract Mode**: 빠른 실행이 필요하거나 Docker 인프라가 없는 경우
- **RAG Mode**: 높은 정확도가 필요하거나 초록에 없는 세부 정보 검증이 필요한 경우

---

## 2. RAG 전용 Tools 상세

### 2.1 `prepare_rag_literature` (RAG 인프라 준비)

#### 함수 시그니처

```python
@tool
def prepare_rag_literature(
    papers_json_path: str,   # "res/part1_papers.json" 또는 "res/liana_papers.json"
    part_name: str = "part1" # "part1", "part2", "part3", "liana"
) -> dict:
```

#### 실행 흐름

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     prepare_rag_literature 워크플로우                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. RAG 가용성 확인                                                          │
│     ├── CCI_RAG_PYTHON 환경변수 확인                                         │
│     ├── CCI_RAG_SERVER 환경변수 확인                                         │
│     ├── langconnect-rag MCP 서버 health check                               │
│     └── 실패 시 → Abstract Mode로 fallback                                   │
│                   return {"rag_mode": False, ...}                           │
│                                                                             │
│  2. 논문 JSON 로드                                                           │
│     ├── papers_json_path에서 JSON 파싱                                       │
│     └── PMID 목록 추출                                                       │
│                                                                             │
│  3. Full-text 다운로드                                                       │
│     ├── download_papers_for_rag(pmids)                                      │
│     │     ├── pubmed-download MCP 서버 연결 (stdio transport)               │
│     │     ├── download_paper tool 호출                                       │
│     │     ├── PMC 우선 → DOI fallback → Abstract fallback                   │
│     │     └── res/papers/pmid_XXXXXXXX.txt 저장                              │
│     └── 실패 시 → Abstract Mode로 fallback                                   │
│                                                                             │
│  4. Vector DB 인덱싱                                                         │
│     ├── index_papers_to_vectordb(file_paths, collection_name)               │
│     │     ├── langconnect-rag MCP 서버 연결                                  │
│     │     ├── create_collection: "deep_interpreter_{part_name}"             │
│     │     └── add_documents_from_files (chunk_size=1000, overlap=200)       │
│     └── 성공 시 → RAG Mode 활성화                                            │
│                   return {"rag_mode": True, "collection_id": "...", ...}    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### 반환값 구조

```python
{
    "rag_mode": True,                    # RAG 모드 활성화 여부
    "collection_id": "abc-123-def",      # Vector DB collection ID
    "collection_name": "part1",          # Part 이름
    "papers_count": 25,                  # 시도한 논문 수
    "fulltext_count": 18,                # 성공적으로 다운로드된 논문 수
    "fulltext_ratio": 0.72,              # 다운로드 성공률
    "message": "RAG ready: 18/25 papers indexed"
}
```

---

### 2.2 `search_literature_fulltext` (Semantic 검색)

#### 함수 시그니처

```python
@tool
def search_literature_fulltext(
    query: str,              # 검색 쿼리 (생물학적 용어, 메커니즘 등)
    part_name: str = "part1", # collection 식별자
    limit: int = 5           # 최대 결과 수
) -> list[dict]:
```

#### 검색 메커니즘

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    search_literature_fulltext 워크플로우                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  입력: query = "CDH1 E-cadherin epithelial integrity tumor suppressor"      │
│                                                                             │
│  1. RAG 상태 확인                                                            │
│     └── _RAG_STATE["available"] == True 확인                                │
│                                                                             │
│  2. Collection ID 조회                                                       │
│     └── _RAG_STATE["collection_ids"][part_name]                             │
│                                                                             │
│  3. Semantic/Hybrid Search 실행                                              │
│     ├── langconnect-rag의 search_documents tool 호출                        │
│     ├── 파라미터:                                                            │
│     │   - collection_id: "abc-123-def"                                      │
│     │   - query: "CDH1 E-cadherin..."                                       │
│     │   - limit: 5                                                          │
│     │   - search_type: "hybrid" (semantic + keyword)                        │
│     └── Vector embedding 기반 유사도 검색                                    │
│                                                                             │
│  4. 결과 반환                                                                │
│     └── [                                                                   │
│           {                                                                 │
│             "page_content": "E-cadherin (CDH1) plays a critical role...",   │
│             "metadata": {"source": "pmid_12345678.txt", ...},               │
│             "score": 0.87                                                   │
│           },                                                                │
│           ...                                                               │
│         ]                                                                   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### 반환값 구조

```python
[
    {
        "page_content": "The matching text passage from the paper...",
        "metadata": {
            "source": "res/papers/pmid_12345678.txt",
            "chunk_id": "chunk_042",
        },
        "score": 0.87  # Relevance score (0-1)
    },
    # ... 추가 결과
]
```

---

### 2.3 `validate_claim_fulltext` (Full-text 기반 클레임 검증)

#### 함수 시그니처

```python
@tool
def validate_claim_fulltext(
    claim: str,              # 검증할 생물학적 주장
    pmid: str,               # 인용된 논문의 PMID
    part_name: str = "part1" # collection 식별자
) -> dict:
```

#### 검증 프로세스

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     validate_claim_fulltext 워크플로우                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  입력:                                                                       │
│  - claim: "CDH1 enrichment in cluster 4 suggests epithelial identity"       │
│  - pmid: "12345678"                                                         │
│  - part_name: "part1"                                                       │
│                                                                             │
│  1. Semantic Search 실행                                                     │
│     └── search_fulltext_rag(query=claim, collection_name="part1", limit=5)  │
│                                                                             │
│  2. PMID 필터링                                                              │
│     ├── 검색 결과에서 해당 PMID의 논문 chunk만 필터링                         │
│     └── metadata.source에서 "pmid_{pmid}" 패턴 매칭                          │
│                                                                             │
│  3. Best Match 선택                                                          │
│     └── 가장 높은 score를 가진 chunk 선택                                    │
│                                                                             │
│  4. Confidence 정규화                                                        │
│     ├── score > 1 → score / 100 (0-1 범위로 정규화)                         │
│     └── 최종 confidence 계산                                                 │
│                                                                             │
│  5. 검증 결과 반환                                                           │
│     └── {                                                                   │
│           "valid": True,                                                    │
│           "confidence": 0.87,                                               │
│           "supporting_text": "E-cadherin (CDH1) is a key...",               │
│           "source": "full_text"                                             │
│         }                                                                   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### 반환값 구조

```python
# 성공적인 검증
{
    "valid": True,
    "confidence": 0.87,           # 0-1 범위
    "supporting_text": "...",     # 최대 500자
    "source": "full_text"
}

# 검증 실패
{
    "valid": False,
    "confidence": 0.0,
    "supporting_text": "",
    "source": "full_text",
    "message": "No supporting text found in full paper"
}
```

#### Confidence 임계값 해석

| Confidence | 상태 | INTERPRETER 행동 |
|------------|------|------------------|
| >= 0.7 | Strong support | 주장 유지 (그대로 사용) |
| >= 0.4, < 0.7 | Moderate support | 유지하되 추가 참조 고려 |
| < 0.4 | Weak/No support | 수정 또는 **(Novel Finding)** 표시 |

---

## 3. RAG 모드 전체 워크플로우

### 3.1 Phase 0: RAG Preparation

```
╔═══════════════════════════════════════════════════════════════╗
║  Phase 0: RAG Preparation                                     ║
╠═══════════════════════════════════════════════════════════════╣
║                                                                ║
║  # Part 1의 경우:                                               ║
║  result = prepare_rag_literature(                              ║
║      papers_json_path="res/part1_papers.json",                 ║
║      part_name="part1"                                         ║
║  )                                                              ║
║                                                                ║
║  # Part 2/3의 경우 (공유):                                       ║
║  result = prepare_rag_literature(                              ║
║      papers_json_path="res/liana_papers.json",                 ║
║      part_name="liana"                                         ║
║  )                                                              ║
║                                                                ║
║  ┌─────────────────┐                                           ║
║  │ result.rag_mode │                                           ║
║  │    == ?         │                                           ║
║  └────────┬────────┘                                           ║
║           │                                                     ║
║     TRUE ─┴─ FALSE                                              ║
║       │       │                                                 ║
║       ▼       ▼                                                 ║
║  RAG Mode   Abstract Mode                                       ║
║   진입       fallback                                            ║
║                                                                ║
╚═══════════════════════════════════════════════════════════════╝
```

### 3.2 Phase 1: Load Context

```
╔═══════════════════════════════════════════════════════════════╗
║  Phase 1: Load Context                                        ║
╠═══════════════════════════════════════════════════════════════╣
║                                                                ║
║  1. read_file("/partN_papers.json")  # ONLY citation source   ║
║  2. read_file("/strategic_plan.md")  # Hypotheses             ║
║  3. read_file("/data_path.txt")      # Data directory         ║
║  4. load_analysis_data(data_dir)     # Analysis results       ║
║                                                                ║
╚═══════════════════════════════════════════════════════════════╝
```

### 3.3 Phase 2: Generate Interpretation (RAG-Enhanced)

```
╔═══════════════════════════════════════════════════════════════╗
║  Phase 2: Generate Interpretation (RAG-Enhanced)              ║
╠═══════════════════════════════════════════════════════════════╣
║                                                                ║
║  각 분석 항목에 대해:                                            ║
║                                                                ║
║  ┌─────────────────────────────────────────────────────────┐  ║
║  │ RAG Mode (rag_mode=True)                                │  ║
║  ├─────────────────────────────────────────────────────────┤  ║
║  │                                                         │  ║
║  │  # 분석 결과 해석 전 관련 문헌 검색                        │  ║
║  │  context_chunks = search_literature_fulltext(           │  ║
║  │      query="CDH1 epithelial tumor suppressor",          │  ║
║  │      part_name="part1"                                  │  ║
║  │  )                                                      │  ║
║  │                                                         │  ║
║  │  # 검색된 full-text context를 기반으로 해석 생성          │  ║
║  │  interpretation = generate_interpretation(              │  ║
║  │      analysis_data, context_chunks                      │  ║
║  │  )                                                      │  ║
║  │                                                         │  ║
║  └─────────────────────────────────────────────────────────┘  ║
║                                                                ║
║  ┌─────────────────────────────────────────────────────────┐  ║
║  │ Abstract Mode (rag_mode=False)                          │  ║
║  ├─────────────────────────────────────────────────────────┤  ║
║  │                                                         │  ║
║  │  # JSON에서 초록 직접 사용                                 │  ║
║  │  papers = load_papers_from_json("/partN_papers.json")   │  ║
║  │                                                         │  ║
║  │  # 초록 기반 해석 생성                                     │  ║
║  │  interpretation = generate_interpretation(              │  ║
║  │      analysis_data, papers.abstracts                    │  ║
║  │  )                                                      │  ║
║  │                                                         │  ║
║  └─────────────────────────────────────────────────────────┘  ║
║                                                                ║
╚═══════════════════════════════════════════════════════════════╝
```

### 3.4 Phase 3: Inline Claim Validation

```
╔═══════════════════════════════════════════════════════════════╗
║  Phase 3: Inline Claim Validation                             ║
╠═══════════════════════════════════════════════════════════════╣
║                                                                ║
║  각 PMID 인용이 있는 주장에 대해:                                ║
║                                                                ║
║  ┌─────────────────────────────────────────────────────────┐  ║
║  │ RAG Mode                                                │  ║
║  ├─────────────────────────────────────────────────────────┤  ║
║  │                                                         │  ║
║  │  result = validate_claim_fulltext(                      │  ║
║  │      claim="CDH1 enrichment suggests epithelial...",    │  ║
║  │      pmid="12345678",                                   │  ║
║  │      part_name="part1"                                  │  ║
║  │  )                                                      │  ║
║  │                                                         │  ║
║  │  if result["valid"] and result["confidence"] >= 0.7:    │  ║
║  │      # 주장 유지                                          │  ║
║  │  elif result["valid"] and result["confidence"] >= 0.4:  │  ║
║  │      # 유지하되 강화 고려                                  │  ║
║  │  else:                                                  │  ║
║  │      # 수정 또는 (Novel Finding) 표시                     │  ║
║  │                                                         │  ║
║  └─────────────────────────────────────────────────────────┘  ║
║                                                                ║
║  ┌─────────────────────────────────────────────────────────┐  ║
║  │ Abstract Mode                                           │  ║
║  ├─────────────────────────────────────────────────────────┤  ║
║  │                                                         │  ║
║  │  result = validate_claim_literature(                    │  ║
║  │      claim="CDH1 enrichment suggests epithelial...",    │  ║
║  │      pmid="12345678",                                   │  ║
║  │      paper_abstract="..."                               │  ║
║  │  )                                                      │  ║
║  │                                                         │  ║
║  │  # result["alignment"]:                                 │  ║
║  │  # "strong" | "weak" | "unsupported"                    │  ║
║  │                                                         │  ║
║  └─────────────────────────────────────────────────────────┘  ║
║                                                                ║
╚═══════════════════════════════════════════════════════════════╝
```

### 3.5 Phase 4: Quality Check Loop

```
╔═══════════════════════════════════════════════════════════════╗
║  Phase 4: Inline Quality Check                                ║
╠═══════════════════════════════════════════════════════════════╣
║                                                                ║
║  validate_quality(interpretation)                             ║
║                                                                ║
║  품질 기준 (각 25% 가중치):                                      ║
║  - statistics_score >= 0.7 (분석당 2+ 통계)                    ║
║  - references_score >= 0.7 (분석당 2+ PMIDs)                   ║
║  - mechanism_score >= 0.7 (명확한 생물학적 메커니즘)            ║
║  - specificity_score >= 0.7 (모호한 표현 없음)                 ║
║                                                                ║
║  ┌─────────────────┐                                          ║
║  │ overall_score   │                                          ║
║  │    >= 0.7 ?     │                                          ║
║  └────────┬────────┘                                          ║
║           │                                                    ║
║     YES ──┴── NO                                               ║
║      │        │                                                ║
║      ▼        ▼                                                ║
║   Phase 5   iteration < 3 ?                                    ║
║              │                                                 ║
║        YES ──┴── NO                                            ║
║         │        │                                             ║
║         ▼        ▼                                             ║
║      Revise   Phase 5                                          ║
║      & Loop   (max iter)                                       ║
║                                                                ║
╚═══════════════════════════════════════════════════════════════╝
```

### 3.6 Phase 5: Write Final Output

```
╔═══════════════════════════════════════════════════════════════╗
║  Phase 5: Write Final Interpretation                          ║
╠═══════════════════════════════════════════════════════════════╣
║                                                                ║
║  write_file("/partN_final.md", interpretation_content)        ║
║                                                                ║
║  출력 형식:                                                     ║
║  ┌─────────────────────────────────────────────────────────┐  ║
║  │ # Part N: {Title}                                       │  ║
║  │                                                         │  ║
║  │ ## Analysis N-X: {Name}                                 │  ║
║  │                                                         │  ║
║  │ ### Quantitative Findings                               │  ║
║  │ - Finding 1: p < 0.001, 2.5-fold enrichment             │  ║
║  │ - Finding 2: 45% of cells express CDH1                  │  ║
║  │                                                         │  ║
║  │ ### Biological Interpretation                           │  ║
║  │ {Literature-grounded interpretation with citations}     │  ║
║  │ {Novel findings marked with (Novel Finding)}            │  ║
║  │                                                         │  ║
║  │ ### References                                          │  ║
║  │ - PMID: 12345678 - Title of paper                       │  ║
║  │                                                         │  ║
║  │ ### Quality Metrics                                     │  ║
║  │ - Statistics: 8 | Citations: 6 | Score: 0.78            │  ║
║  └─────────────────────────────────────────────────────────┘  ║
║                                                                ║
╚═══════════════════════════════════════════════════════════════╝
```

---

## 4. RAG 데이터 흐름 다이어그램

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         RAG 데이터 흐름 다이어그램                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  res/part1_papers.json                                                      │
│         │                                                                   │
│         │ PMIDs 추출                                                        │
│         ▼                                                                   │
│  ┌─────────────────┐                                                        │
│  │  pubmed-download │                                                       │
│  │    MCP Server    │                                                       │
│  └────────┬────────┘                                                        │
│           │                                                                 │
│           │ download_paper(pmid, output_path, prefer_pmc=True)              │
│           │                                                                 │
│           ▼                                                                 │
│  ┌─────────────────────────────────────────────────────────────────┐       │
│  │                     논문 다운로드 우선순위                         │       │
│  │  1. PMC (PubMed Central) - Free full-text                       │       │
│  │  2. DOI via Jina Reader - Publisher full-text                   │       │
│  │  3. PubMed Abstract - Fallback                                  │       │
│  └─────────────────────────────────────────────────────────────────┘       │
│           │                                                                 │
│           │ 저장                                                            │
│           ▼                                                                 │
│  res/papers/                                                                │
│  ├── pmid_12345678.txt                                                      │
│  ├── pmid_23456789.txt                                                      │
│  └── ...                                                                    │
│           │                                                                 │
│           │ 파일 경로 목록                                                   │
│           ▼                                                                 │
│  ┌─────────────────┐                                                        │
│  │  langconnect-rag │                                                       │
│  │    MCP Server    │                                                       │
│  └────────┬────────┘                                                        │
│           │                                                                 │
│           │ add_documents_from_files(                                       │
│           │     collection_id, file_paths,                                  │
│           │     chunk_size=1000, chunk_overlap=200                          │
│           │ )                                                               │
│           ▼                                                                 │
│  ┌─────────────────────────────────────────────────────────────────┐       │
│  │                        Vector Database                          │       │
│  ├─────────────────────────────────────────────────────────────────┤       │
│  │  Collection: "deep_interpreter_part1"                           │       │
│  │  ┌─────────────────────────────────────────────────────────┐   │       │
│  │  │  chunk_001: embedding + "E-cadherin (CDH1) plays..."    │   │       │
│  │  │  chunk_002: embedding + "The tumor suppressor..."       │   │       │
│  │  │  chunk_003: embedding + "Spatial analysis revealed..."  │   │       │
│  │  │  ...                                                     │   │       │
│  │  └─────────────────────────────────────────────────────────┘   │       │
│  └─────────────────────────────────────────────────────────────────┘       │
│           │                                                                 │
│           │ search_documents(query, collection_id, search_type="hybrid")    │
│           ▼                                                                 │
│  ┌─────────────────────────────────────────────────────────────────┐       │
│  │                      Semantic Search Results                    │       │
│  ├─────────────────────────────────────────────────────────────────┤       │
│  │  [                                                              │       │
│  │    {                                                            │       │
│  │      "page_content": "E-cadherin (CDH1) plays a critical...",   │       │
│  │      "metadata": {"source": "pmid_12345678.txt"},               │       │
│  │      "score": 0.87                                              │       │
│  │    },                                                           │       │
│  │    ...                                                          │       │
│  │  ]                                                              │       │
│  └─────────────────────────────────────────────────────────────────┘       │
│           │                                                                 │
│           │ INTERPRETER가 해석 생성 및 검증에 활용                           │
│           ▼                                                                 │
│  /part1_final.md (Literature-grounded interpretation)                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. MCP 서버 통합

### 5.1 사용되는 MCP 서버

RAG 모드는 두 개의 MCP 서버를 사용합니다:

#### pubmed-download MCP

| 항목 | 값 |
|------|-----|
| **목적** | Full-text 논문 다운로드 |
| **Transport** | stdio |
| **주요 Tool** | `download_paper(pmid, output_path, prefer_pmc)` |

**환경변수:**
```bash
PUBMED_MCP_PYTHON=/path/to/python
PUBMED_MCP_SERVER=/path/to/pubmed_download_mcp/server.py
PUBMED_EMAIL=your.email@example.com
NCBI_API_KEY=your_ncbi_api_key          # 선택
JINA_API_KEY=your_jina_api_key          # DOI 다운로드용
```

#### langconnect-rag MCP

| 항목 | 값 |
|------|-----|
| **목적** | Vector DB 관리 및 Semantic Search |
| **Transport** | stdio |
| **주요 Tools** | `get_health_status`, `list_collections`, `create_collection`, `add_documents_from_files`, `search_documents`, `delete_collection` |

**환경변수:**
```bash
CCI_RAG_PYTHON=/path/to/python
CCI_RAG_SERVER=/path/to/langconnect_rag/server.py
CCI_RAG_BASE_URL=http://localhost:8888  # RAG API 엔드포인트
```

### 5.2 MCP 클라이언트 연결 코드

```python
from langchain_mcp_adapters.client import MultiServerMCPClient

# pubmed-download MCP 연결
client = MultiServerMCPClient({
    "pubmed-download": {
        "command": PUBMED_MCP_PYTHON,
        "args": [PUBMED_MCP_SERVER],
        "env": {
            "PUBMED_EMAIL": PUBMED_EMAIL,
            "NCBI_API_KEY": NCBI_API_KEY,
            "JINA_API_KEY": JINA_API_KEY,
        },
        "transport": "stdio",
    }
})

# langconnect-rag MCP 연결
client = MultiServerMCPClient({
    "CCI-RAG": {
        "command": CCI_RAG_PYTHON,
        "args": [CCI_RAG_SERVER],
        "env": {"API_BASE_URL": CCI_RAG_BASE_URL},
        "transport": "stdio",
    }
})
```

---

## 6. 모듈-레벨 상태 관리

RAG 모드는 모듈-레벨 상태를 사용하여 세션 간 일관성을 유지합니다:

```python
# 모듈-레벨 RAG 상태 캐시
_RAG_STATE: dict[str, Any] = {
    "available": None,        # None = 미확인, True/False = 확인됨
    "collection_ids": {},     # {part_name: collection_id}
}

# 상태 리셋 함수 (테스트용)
def reset_rag_state() -> None:
    """RAG 상태 캐시 리셋."""
    global _RAG_STATE
    _RAG_STATE = {
        "available": None,
        "collection_ids": {},
    }

# 현재 상태 조회
def get_rag_status() -> dict:
    """현재 RAG 상태 반환."""
    return {
        "available": _RAG_STATE["available"],
        "collections": dict(_RAG_STATE["collection_ids"]),
    }

# RAG 모드 활성 여부 확인
def is_rag_mode_active() -> bool:
    """RAG 모드가 현재 활성화되어 있는지 확인."""
    return (
        _RAG_STATE.get("available") is True
        and len(_RAG_STATE.get("collection_ids", {})) > 0
    )
```

---

## 7. Abstract Mode와의 검증 프로세스 비교

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        검증 프로세스 비교                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      Abstract Mode                                  │   │
│  ├─────────────────────────────────────────────────────────────────────┤   │
│  │  1. /partN_papers.json에서 초록 로드                                 │   │
│  │  2. claim 텍스트와 초록 비교                                          │   │
│  │  3. validate_claim_literature 호출                                   │   │
│  │  4. 단순 키워드/의미 매칭                                              │   │
│  │  5. 결과: "strong" | "weak" | "unsupported"                         │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        RAG Mode                                     │   │
│  ├─────────────────────────────────────────────────────────────────────┤   │
│  │  1. prepare_rag_literature로 전문 다운로드 & 인덱싱                   │   │
│  │  2. 전문이 Vector DB에 chunk로 저장됨                                 │   │
│  │  3. validate_claim_fulltext 호출                                     │   │
│  │  4. Semantic search로 관련 chunk 검색                                 │   │
│  │  5. PMID 필터링으로 정확한 논문 매칭                                   │   │
│  │  6. 결과: {"valid": bool, "confidence": 0-1, "supporting_text": ...} │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 8. RAG 모드의 핵심 장점

### 8.1 높은 Citation Accuracy

- **Abstract Mode**: ~70% (초록에 없는 정보는 검증 불가)
- **RAG Mode**: ~90% (전문에서 직접 supporting text 검색)

### 8.2 구체적인 Evidence

```markdown
# Abstract Mode
"CDH1 is associated with epithelial phenotype (PMID: 12345678)"

# RAG Mode
"CDH1 is associated with epithelial phenotype, specifically through
its role in maintaining adherens junctions and preventing EMT
(PMID: 12345678, Fig. 3A)"
```

### 8.3 Pathway Coverage 향상

- **Abstract Mode**: ~32% (초록은 주요 발견만 언급)
- **RAG Mode**: ~70-85% (Methods, Results 섹션의 세부 정보 접근)

### 8.4 Hallucination 방지 강화

- Semantic similarity 기반 검증으로 정확도 향상
- 구체적인 supporting text 제공으로 검증 가능성 증가
- PMID별 chunk 필터링으로 정확한 논문 매칭

---

## 9. 환경 설정 체크리스트

RAG 모드를 사용하려면 다음을 확인하세요:

### 필수 환경변수

```bash
# .env 파일

# pubmed-download MCP Server
PUBMED_MCP_PYTHON=/path/to/python
PUBMED_MCP_SERVER=/path/to/pubmed_download_mcp/server.py
PUBMED_EMAIL=your.email@example.com

# langconnect-rag MCP Server
CCI_RAG_PYTHON=/path/to/python
CCI_RAG_SERVER=/path/to/langconnect_rag/server.py
CCI_RAG_BASE_URL=http://localhost:8888
```

### 선택적 환경변수

```bash
# NCBI API 키 (rate limit 증가)
NCBI_API_KEY=your_ncbi_api_key

# Jina Reader API 키 (DOI 다운로드용)
JINA_API_KEY=your_jina_api_key
```

### Docker 요구사항

- langconnect-rag 서버가 실행 중이어야 함
- Vector DB (예: Qdrant, Chroma)가 설정되어 있어야 함

---

## 10. 문제 해결

### RAG 모드가 활성화되지 않는 경우

1. **환경변수 확인**: `CCI_RAG_PYTHON`, `CCI_RAG_SERVER` 경로 확인
2. **서버 상태 확인**: `get_health_status` 호출로 서버 응답 확인
3. **Docker 확인**: langconnect-rag 컨테이너 실행 상태 확인

### Full-text 다운로드 실패

1. **NCBI API 키**: rate limit 초과 시 API 키 설정
2. **JINA API 키**: DOI 다운로드 실패 시 API 키 확인
3. **네트워크**: PMC/DOI 서버 접근 가능 여부 확인

### 낮은 검증 Confidence

1. **Query 품질**: 더 구체적인 생물학적 용어 사용
2. **Chunk 크기**: `chunk_size` 조정 (기본 1000)
3. **검색 유형**: `search_type="hybrid"` 사용 권장

---

## 관련 문서

- [INTERPRETER Subagent Workflow](./interpreter_subagent_workflow.md)
- [Literature Search Strategy](./literature_search_strategy.md)
- [Deep Interpreter Architecture](./deep_interpreter_architecture.md)
