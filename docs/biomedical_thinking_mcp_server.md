# Biomedical Thinking MCP Server

## Overview

생물의학 문헌 검색을 위한 **4-stage rule-based 파이프라인** MCP 서버. LLM 호출 없이 순수 규칙 기반으로 동작하며, 복잡한 생물의학 질문을 구조화된 PubMed 검색 쿼리로 변환한다.

**위치**: `/Users/jungj2/Dropbox/Metadata/mcp/biomedical_thinking/`

```
Stage 1: Decompose → Stage 2: Expand → Stage 3: Query Builder → Stage 4: Evaluator
```

## 파일 구조

```
biomedical_thinking/
├── server.py                    # FastMCP 서버 등록
├── tools/
│   ├── __init__.py
│   ├── decompose.py             # Stage 1: Query Decomposition
│   ├── expand.py                # Stage 2: Entity Expansion
│   ├── query_builder.py         # Stage 3: Query Strategy Builder
│   └── evaluator.py             # Stage 4: Result Evaluator
├── utils/
│   ├── __init__.py
│   ├── gene_aliases.py          # 로컬 유전자 alias 사전 (80개+)
│   └── mesh.py                  # 로컬 MeSH 매핑 사전
└── tests/
    ├── conftest.py              # 공통 fixtures
    ├── test_decompose.py        # Stage 1 tests (9개)
    ├── test_expand.py           # Stage 2 tests (12개)
    ├── test_query_builder.py    # Stage 3 tests (11개)
    ├── test_evaluator.py        # Stage 4 tests (9개)
    └── test_integration.py      # E2E pipeline tests (3개)
```

## 서버 등록

```python
# server.py
from fastmcp import FastMCP
mcp = FastMCP("biomedical-thinking")
mcp.tool()(analyze_and_decompose)   # Stage 1
mcp.tool()(expand_entities)          # Stage 2
mcp.tool()(build_search_queries)     # Stage 3
mcp.tool()(evaluate_search_results)  # Stage 4
```

4개의 MCP tool이 등록되며, 각각 독립적으로 호출 가능하다.

---

## Stage 1: `analyze_and_decompose` — Query Decomposition

### 역할

복잡한 생물의학 질문을 구조화된 sub-question으로 분해하고 엔티티를 추출한다.

### API

```python
await analyze_and_decompose(
    research_question: str,   # 생물의학 연구 질문
    context: str = "",        # 분석 데이터 컨텍스트 (optional)
    analysis_type: str = "auto"  # auto | cci_mechanism | spatial_pattern | pathway | gene_function
) -> dict
```

### 내부 처리 순서

#### 1. Entity Extraction

regex + keyword dictionary로 4종 엔티티를 추출한다.

| 엔티티 | 추출 방법 | 예시 |
|--------|----------|------|
| Genes | `[A-Z][A-Z0-9]{1,9}` regex - `_NON_GENE_WORDS` 필터 | TGFB1, VEGFA, SMAD2 |
| Pathways | 90개+ 키워드 dict (case-insensitive) | EMT → "Epithelial-Mesenchymal Transition" |
| Cell types | 50개+ 키워드 dict | fibroblast → "Fibroblast" |
| Diseases | 30개+ 키워드 dict | breast cancer → "breast cancer" |

`_NON_GENE_WORDS` 필터: AND, OR, NOT, EMT, NMF, CCI, TME, ECM, MAPK, PI3K, AKT 등 일반 약어를 gene으로 오인식하지 않도록 제거.

#### 2. Question Classification

regex 패턴 매칭으로 질문 유형을 분류한다.

| 유형 | 패턴 |
|------|------|
| `cci_mechanism` | ligand, receptor, L-R, cell-cell, paracrine |
| `spatial_pattern` | spatial, co-localize, neighbor, niche, gradient |
| `pathway` | pathway, signaling, cascade, phosphorylation |
| `gene_function` | expression, upregulate, function, role, marker |
| `general` | 어떤 패턴에도 매칭되지 않을 때 |

#### 3. Complexity Assessment

점수 기반으로 복잡도를 판정한다.

| 요소 | 점수 |
|------|------|
| entity 총 수 > 5 | +2 |
| entity 총 수 > 2 | +1 |
| causal verb 2개+ (drive, induce, mediate 등) | +2 |
| causal verb 1개 | +1 |
| "and" 접속사 포함 | +1 |
| spatial + mechanism 조합 | +1 |

- `simple`: 0점
- `moderate`: 1-2점
- `multi_hop`: 3점+

#### 4. Question Decomposition

4가지 전략으로 sub-question을 생성한다.

- **Causal decomposition**: genes ≥ 2개 + causal verb → mechanism + pathway 질문
- **Spatial decomposition**: spatial keyword 포함 → spatial distribution 질문
- **Cell type interaction**: cci_mechanism + celltypes ≥ 2 → communication mechanism 질문
- **Disease context**: disease 존재 → disease role 질문

아무 전략에도 해당하지 않으면 원본 질문을 그대로 1개 sub-question으로 반환.

#### 5. Strategy Suggestion

| complexity | question_type | strategy |
|------------|---------------|----------|
| multi_hop | cci_mechanism | `hypothesis_driven` |
| multi_hop | 기타 | `iterative_refinement` |
| moderate | genes > 3 | `gene_centric_then_pathway` |
| moderate | 기타 | `balanced` |
| simple | any | `direct_search` |

### 출력

```python
{
    "question_type": "cci_mechanism",
    "complexity": "multi_hop",
    "sub_questions": [
        {"id": 1, "question": "What is the mechanism of TGFB1, TGFBR2 signaling?",
         "priority": "high", "search_focus": "gene_centric"},
        ...
    ],
    "entities": {
        "genes": ["TGFB1-TGFBR2"],
        "pathways": ["Epithelial-Mesenchymal Transition", "TGF-beta signaling"],
        "celltypes": ["Fibroblast"],
        "diseases": ["breast cancer"]
    },
    "suggested_strategy": "hypothesis_driven",
    "estimated_search_rounds": 2
}
```

---

## Stage 2: `expand_entities` — Entity Expansion

### 역할

추출된 엔티티를 aliases, MeSH terms, subtypes로 확장하여 PubMed 검색 커버리지를 향상한다.

### API

```python
await expand_entities(
    genes: list[str] | None = None,
    pathways: list[str] | None = None,
    celltypes: list[str] | None = None,
    diseases: list[str] | None = None,
    expand_aliases: bool = True,   # gene alias 확장
    expand_mesh: bool = True,      # MeSH term 매핑
    expand_related: bool = False,  # 관련 유전자 (미구현)
) -> dict
```

### 내부 처리

```
로컬 dict 조회 (빠름, 0ms) → 없으면 API fallback (느림, ~500ms)
```

| 엔티티 | 로컬 소스 | API Fallback |
|--------|----------|--------------|
| Gene aliases | `utils/gene_aliases.py` (80개+ 유전자) | MyGene.info API |
| Gene MeSH | `utils/mesh.py` `_GENE_MESH` (70개+) | NCBI E-utilities |
| Pathway | `utils/mesh.py` `_PATHWAY_MESH` (16개) | NCBI E-utilities |
| Cell type | `utils/mesh.py` `_CELLTYPE_MESH` (20개+) | NCBI E-utilities |
| Disease | `utils/mesh.py` `_DISEASE_MESH` (20개+) | NCBI E-utilities |

### PubMed Query Fragment 생성

`_build_pubmed_fragment(term, aliases, mesh_term)`:

```
(TGFB1[tiab] OR "TGF-beta-1"[tiab] OR "TGF-β1"[tiab] OR "Transforming Growth Factor beta1"[mh])
```

- `[tiab]`: Title/Abstract 필드 검색
- `[mh]`: MeSH Heading 필드 검색

### 출력

```python
{
    "expanded_genes": {
        "TGFB1": {"aliases": ["TGF-beta-1", "TGFB", "TGF-β1", "TGFbeta1"],
                   "mesh_id": "D053773", "mesh_term": "Transforming Growth Factor beta1"}
    },
    "expanded_pathways": {
        "TGF-beta signaling": {"mesh_id": "D053773", "mesh_term": "...",
                                "keywords": ["TGF-beta", "SMAD signaling"],
                                "child_terms": ["canonical TGF-beta", "non-canonical TGF-beta"]}
    },
    "expanded_celltypes": {
        "Fibroblast": {"mesh_id": "D005347", "mesh_term": "Fibroblasts",
                        "subtypes": ["cancer-associated fibroblast", "CAF", "myofibroblast"]}
    },
    "expanded_diseases": {
        "breast cancer": {"mesh_id": "D001943", "mesh_term": "Breast Neoplasms",
                          "subtypes": ["DCIS", "triple-negative breast cancer", ...]}
    },
    "pubmed_query_fragments": {
        "gene_fragment": "(TGFB1[tiab] OR ...)",
        "pathway_fragment": "(TGF-beta signaling[tiab] OR ...)",
        "celltype_fragment": "(Fibroblast[tiab] OR ...)",
        "disease_fragment": "(breast cancer[tiab] OR ...)"
    },
    "coverage_stats": {
        "genes_input": 1, "genes_expanded": 6,
        "pathways_input": 1, "pathways_expanded": 5,
        "celltypes_input": 1, "celltypes_expanded": 4,
        "diseases_input": 1, "diseases_expanded": 5
    }
}
```

---

## Stage 3: `build_search_queries` — Query Strategy Builder

### 역할

Stage 1의 sub-questions + Stage 2의 fragments를 전략적으로 조합하여 최적화된 PubMed 쿼리를 생성한다.

### API

```python
await build_search_queries(
    sub_questions: list[dict],        # Stage 1 출력
    pubmed_query_fragments: dict,     # Stage 2 출력
    question_type: str = "general",
    suggested_strategy: str = "balanced",
    max_queries: int = 5,
    disease_context: str = "",        # 보충 disease term
) -> dict
```

### Fragment 조합 규칙 (`_combine_by_focus`)

| search_focus | 조합 fragments |
|--------------|---------------|
| `gene_centric` | gene AND disease |
| `pathway_centric` | pathway AND gene |
| `cell_interaction` | celltype AND gene |
| `spatial` | celltype AND pathway |
| `disease_context` | disease AND (gene \|\| pathway) |
| `general` | gene AND pathway AND celltype (max 3 AND) |

### 5가지 전략

| 전략 | 동작 |
|------|------|
| `balanced` | sub-question 1개당 query 1개, focus별 조합 |
| `hypothesis_driven` | 모든 query에 disease fragment 필수 포함, focus별 차별화 |
| `gene_centric_then_pathway` | 전반: gene 중심, 후반: pathway 중심 |
| `iterative_refinement` | 3-tier (broad: 1개 frag → medium: 2개 → narrow: 3개) |
| `direct_search` | 단일 combined query |

### Iteration Roadmap

```python
{
    "round1_queries": [1, 2, 3],        # 최대 3개 먼저 실행
    "round2_contingency": [              # 조건부 추가 검색
        {"condition": "gene_centric_coverage < 60%",
         "query_id": 4, "focus": "gap_fill_gene_centric"}
    ]
}
```

### 출력

```python
{
    "search_queries": [
        {"id": 1, "query": "(TGFB1[tiab] OR ...) AND (breast cancer[tiab] OR ...)",
         "targets_sub_questions": [1], "focus": "gene_centric",
         "expected_results": "20-50",
         "rationale": "Hypothesis-driven: causal relationship for '...'"},
        ...
    ],
    "iteration_roadmap": {"round1_queries": [1, 2], "round2_contingency": [...]},
    "total_queries": 3,
    "strategy_applied": "hypothesis_driven"
}
```

---

## Stage 4: `evaluate_search_results` — Result Evaluator

### 역할

PubMed 검색 결과를 sub-questions/entities 대비 평가하여 커버리지 분석 및 gap-fill 제안.

### API

```python
await evaluate_search_results(
    papers: list[dict],         # [{"pmid": "...", "title": "...", "abstract": "..."}]
    sub_questions: list[dict],  # Stage 1 출력
    entities: dict,             # Stage 1 출력
    question_type: str = "general",
) -> dict
```

### 평가 로직

#### Sub-question Coverage

1. 각 sub-question에서 key terms 추출 (stopword 제거, 구두점 strip)
2. 각 paper의 title+abstract와 term 매칭 (case-insensitive)
3. ≥ 2 terms match → "matching paper"

| matching papers | coverage |
|-----------------|----------|
| ≥ 5 | `well_covered` |
| ≥ 2 | `moderate` |
| < 2 | `poorly_covered` |

#### Entity Coverage

Gene alias variant matching 지원:

```python
_GENE_ALIASES = {
    "TGFB1": ["TGF-beta", "TGF-β1", "TGF-beta-1", "transforming growth factor beta"],
    "VEGFA": ["VEGF", "VEGF-A", "vascular endothelial growth factor"],
    ...
}
```

논문 텍스트에 "TGF-beta"가 있으면 TGFB1이 covered로 판정.

#### Overall Score

```
overall_score = 0.5 × sq_score + 0.5 × entity_score
```

- `sq_score`: well_covered/moderate인 sub-question 비율
- `entity_score`: 평균 entity coverage %

#### needs_iteration 판정

```python
needs_iteration = overall_score < 0.6 or any(
    sq["coverage"] == "poorly_covered" and sq_dict["priority"] == "high"
)
```

#### Gap-fill Suggestions

- Missing gene → `"SNAI1 snail SNAIL"` (gene + aliases)
- Missing pathway → `"Apoptosis signaling pathway"`

### 출력

```python
{
    "sub_question_coverage": [
        {"sub_question_id": 1, "question": "...", "matching_papers": 5,
         "coverage": "well_covered", "key_pmids": ["12345678", ...]}
    ],
    "entity_coverage": {
        "genes": {"covered": ["TGFB1"], "missing": ["TGFBR2"], "pct": 50.0},
        "pathways": {"covered": [...], "missing": [...], "pct": 100.0}
    },
    "gap_analysis": {
        "poorly_covered_sub_questions": [2],
        "missing_entities": ["TGFBR2"],
        "suggested_gap_fill_terms": ["TGFBR2 TGF-beta receptor type II TBRII"],
        "needs_iteration": true
    },
    "overall_score": 0.65,
    "recommendation": "Run gap-fill queries for sub-questions [2] and missing entities: TGFBR2"
}
```

---

## Pipeline 사용 흐름

```
사용자 질문
    │
    ▼
[Stage 1] analyze_and_decompose
    │  → entities, sub_questions, strategy
    ▼
[Stage 2] expand_entities
    │  → pubmed_query_fragments, expanded entities
    ▼
[Stage 3] build_search_queries
    │  → PubMed 쿼리 목록
    ▼
  ┌─── 실제 PubMed 검색 수행 (서버 외부) ───┐
  │  search_pubmed(query) → papers            │
  └───────────────────────────────────────────┘
    │
    ▼
[Stage 4] evaluate_search_results
    │  → coverage 분석, gap-fill 제안
    ▼
  ┌─── needs_iteration == True? ───┐
  │  YES: gap-fill terms로         │
  │  Stage 3 재호출 → 반복         │
  │  NO: 검색 완료                  │
  └────────────────────────────────┘
```

Stage 3과 Stage 4 사이에 실제 PubMed 검색이 수행되어야 한다 (이 서버 범위 밖). 검색된 papers를 Stage 4에 전달하여 평가하고, `needs_iteration=True`이면 gap-fill terms로 Stage 3를 다시 호출하는 반복 구조.

## 테스트

```bash
cd /Users/jungj2/Dropbox/Metadata/mcp/biomedical_thinking

# 전체 테스트 실행 (44개)
python -m pytest tests/ -v

# 개별 stage 테스트
python -m pytest tests/test_decompose.py -v      # 9 tests
python -m pytest tests/test_expand.py -v          # 12 tests
python -m pytest tests/test_query_builder.py -v   # 11 tests
python -m pytest tests/test_evaluator.py -v       # 9 tests
python -m pytest tests/test_integration.py -v     # 3 tests
```

모든 API 호출은 mock 처리되어 네트워크 없이 실행 가능.
