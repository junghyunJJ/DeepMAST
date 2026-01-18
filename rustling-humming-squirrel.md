# Deep Biological Interpreter Agent - Implementation Plan

## Overview

LangGraph 기반 Deep Agent 아키텍처를 활용한 Biological Interpreter 구현 계획.
사전 계산된 CCI (Cell-Cell Interaction) 분석 결과를 해석하여 구조화된 HTML 보고서 생성.

## Key Design Decisions

| 항목 | 결정 | 근거 |
|------|------|------|
| Agent 유형 | Deep Agent (ReAct 대신) | 반복적 개선, 반성, 근거 수집 필요 |
| 워크플로우 | 순차적 (Part1→Part2→Part3) | 결정이 다음 단계에 영향 |
| 분석 모드 | 양방향 (cluster↔celltype) | 사용자 입력에 따라 분기 |
| HITL 수준 | 최소 (시작 시 입력만) | 자동화 우선 |
| L-R 가중치 | 하이브리드 | LLM 동적 조정 + Guardrails |

## Architecture

### Graph Structure

```
START
  │
  ▼
┌─────────────────────────────────────┐
│          load_results               │  ← CSV/PNG 로드
└─────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────┐
│    🔴 HITL: get_user_targets        │  ← 유일한 HITL
│  • interest_clusters (Mode A)       │
│  • OR interest_celltypes (Mode B)   │
└─────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────┐
│       determine_analysis_mode       │
└─────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────┐
│       strategic_planning            │  ← Deep Agent: 가설 설정
└─────────────────────────────────────┘
  │
  ▼
╔═══════════════════════════════════════════════════════════════╗
║              PART 1 INTERPRETATION SUBGRAPH                    ║
║  ┌─────────┬─────────┬─────────┬─────────┬─────────┐          ║
║  │spatial  │celltype │nhood    │decoupler│misty    │          ║
║  │(1-1)    │(1-2)    │(1-3)    │(1-4)    │(1-5)    │          ║
║  └────┬────┴────┬────┴────┬────┴────┬────┴────┬────┘          ║
║       └─────────┴─────────┼─────────┴─────────┘               ║
║                           ▼                                    ║
║                 ┌─────────────────┐                            ║
║                 │ part1_synthesis │                            ║
║                 └────────┬────────┘                            ║
║                          ▼                                     ║
║           ┌──────────────┴──────────────┐                      ║
║           ▼                             ▼                      ║
║   ┌───────────────┐           ┌───────────────┐               ║
║   │   MODE A      │           │   MODE B      │               ║
║   │ clusters→     │           │ celltypes→    │               ║
║   │ celltypes     │           │ clusters      │               ║
║   └───────────────┘           └───────────────┘               ║
╚═══════════════════════════════════════════════════════════════╝
  │
  ▼
╔═══════════════════════════════════════════════════════════════╗
║              PART 2 INTERPRETATION SUBGRAPH                    ║
║  ┌──────────────────────────────────────────────────┐         ║
║  │ interp_liana_moransR (2-6)                       │         ║
║  └──────────────────────────────────────────────────┘         ║
║                          │                                     ║
║                          ▼                                     ║
║  ┌──────────────────────────────────────────────────┐         ║
║  │ interp_nmf_factors (2-7) + auto_select_factor    │         ║
║  └──────────────────────────────────────────────────┘         ║
║                          │                                     ║
║                          ▼                                     ║
║  ┌──────────────────────────────────────────────────┐         ║
║  │ interp_pathway_factor (2-8)                      │         ║
║  │ + compare_pathways_with_part1                    │         ║
║  └──────────────────────────────────────────────────┘         ║
║                          │                                     ║
║                          ▼                                     ║
║  ┌──────────────────────────────────────────────────┐         ║
║  │ prepare_celltypes_for_ctsvg                      │         ║
║  │ Mode A: selected_celltypes (재계산 가능)         │         ║
║  │ Mode B: interest_celltypes (그대로)              │         ║
║  └──────────────────────────────────────────────────┘         ║
║                          │                                     ║
║                          ▼                                     ║
║  ┌──────────────────────────────────────────────────┐         ║
║  │ interp_ctsvg (2-9)                               │         ║
║  │ + determine_scoring_weights (LLM 동적 조정)      │         ║
║  │ + auto_select_lr_pairs (복합 스코어링)           │         ║
║  └──────────────────────────────────────────────────┘         ║
╚═══════════════════════════════════════════════════════════════╝
  │
  ▼
╔═══════════════════════════════════════════════════════════════╗
║              PART 3 INTERPRETATION SUBGRAPH                    ║
║  interp_spatial_lr (3-10) → interp_lr_summary (3-11)          ║
╚═══════════════════════════════════════════════════════════════╝
  │
  ▼
┌─────────────────────────┐
│ cross_part_synthesis    │  ← Deep Agent: 통합 narrative
└─────────────────────────┘
  │
  ▼
┌─────────────────────────┐
│ literature_search       │  ← Deep Agent: claim별 PMID
└─────────────────────────┘
  │
  ▼
┌─────────────────────────┐
│ quality_reflection      │  ← Deep Agent: 검증
└─────────────────────────┘
  │
  ├────────┬────────┐
[PASS]  [REFINE]    │ (max 3)
  │        └────────┘
  ▼
┌─────────────────────────┐
│ generate_html_report    │
└─────────────────────────┘
  │
  ▼
 END
```

### Dual Mode Workflow

| 단계 | Mode A (clusters→celltypes) | Mode B (celltypes→clusters) |
|------|----------------------------|----------------------------|
| 입력 | `interest_clusters` | `interest_celltypes` |
| Part1 목표 | celltypes 찾기 | clusters 찾기 |
| Part1 출력 | `selected_celltypes` | `selected_clusters` |
| Factor 기준 | `interest_clusters` | `selected_clusters` |
| ctSVG celltypes | `selected_celltypes` (재계산 가능) | `interest_celltypes` (그대로) |

### Composite Scoring (Hybrid Weights)

```python
DEFAULT_WEIGHTS = {
    "factor": 0.35,   # Factor loading
    "pathway": 0.30,  # Pathway relevance
    "morans": 0.20,   # Moran's R
    "ctsvg": 0.15     # ctSVG overlap
}

WEIGHT_RANGES = {  # Guardrails
    "factor": (0.20, 0.50),
    "pathway": (0.15, 0.45),
    "morans": (0.10, 0.35),
    "ctsvg": (0.05, 0.30)
}
```

LLM이 분석 맥락에 따라 범위 내에서 동적 조정, 조정 근거 기록.

## Files to Create/Modify

### New Files

```
src/agents/interpreter/
├── __init__.py                      # Export BiologicalInterpreterAgent
├── biological_interpreter_agent.py  # Main agent class
├── biological_interpreter_state.py  # State definition
├── nodes/
│   ├── __init__.py
│   ├── load_results.py              # Data loading node
│   ├── strategic_planning.py        # Deep Agent planning
│   ├── part1_interpretation.py      # Part1 subgraph nodes
│   ├── part2_interpretation.py      # Part2 subgraph nodes
│   ├── part3_interpretation.py      # Part3 subgraph nodes
│   ├── synthesis.py                 # Cross-part synthesis
│   ├── literature_search.py         # Evidence gathering
│   ├── quality_reflection.py        # Deep Agent reflection
│   └── report_generator.py          # HTML report generation
├── utils/
│   ├── __init__.py
│   ├── scoring.py                   # Composite scoring logic
│   ├── weight_config.py             # Weight management
│   └── html_template.py             # Report template
└── prompts/
    ├── __init__.py
    └── interpretation_prompts.py    # LLM prompts
```

### Modify

```
src/agents/graph_builders.py         # Add biological_interpreter graph
langgraph.json                       # Register new graph
```

## State Schema

```python
class BiologicalInterpreterState(TypedDict):
    messages: Annotated[list, add_messages]

    # Input (HITL)
    analysis_mode: Literal["cluster_to_celltype", "celltype_to_cluster"]
    interest_clusters: Optional[list[str]]
    interest_celltypes: Optional[list[str]]
    research_question: Optional[str]

    # Data paths
    adata_path: str
    lrdata_path: str
    results_dir: str

    # Part1 output
    part1_results: dict
    part1_interpretations: dict[str, str]
    selected_celltypes: Optional[list[str]]  # Mode A
    selected_clusters: Optional[list[str]]   # Mode B
    selected_pathways: list[str]
    additional_clusters: list[str]

    # Part2 output
    part2_results: dict
    part2_interpretations: dict[str, str]
    selected_factor: str
    factor_selection_rationale: str
    pathway_comparison: dict
    final_celltypes_for_ctsvg: list[str]
    celltype_source: Literal["derived", "user_specified"]
    scoring_weights: WeightConfiguration
    selected_lr_pairs: list[str]
    lr_scores: dict[str, dict]

    # Part3 output
    part3_interpretations: dict[str, str]

    # Deep Agent components
    analysis_plan: dict
    integrated_narrative: str
    claims: list[dict]
    literature_evidence: dict[str, list[str]]
    reflection_result: dict
    refinement_count: int

    # Output
    html_report: str
```

## Implementation Order

### Phase 1: Foundation
1. Create state schema (`biological_interpreter_state.py`)
2. Create base agent class (`biological_interpreter_agent.py`)
3. Implement `load_results` node
4. Implement `determine_analysis_mode` node

### Phase 2: Part1 Implementation
5. Implement Part1 interpretation nodes (1-1 through 1-5)
6. Implement `part1_synthesis` node
7. Implement mode branching (auto_select_targets)

### Phase 3: Part2 Implementation
8. Implement Part2 interpretation nodes (2-6 through 2-9)
9. Implement `determine_scoring_weights` (hybrid weights)
10. Implement `auto_select_lr_pairs` (composite scoring)

### Phase 4: Part3 & Synthesis
11. Implement Part3 interpretation nodes
12. Implement `cross_part_synthesis`
13. Implement `literature_search` (biomcp integration)

### Phase 5: Deep Agent Components
14. Implement `strategic_planning`
15. Implement `quality_reflection`
16. Implement refinement loop

### Phase 6: Report Generation
17. Create HTML template (dark theme)
18. Implement `generate_html_report`

### Phase 7: Integration
19. Register in graph_builders.py
20. Update langgraph.json
21. End-to-end testing

## Verification Plan

### Unit Tests
- [ ] State initialization and mode detection
- [ ] Weight configuration and guardrails
- [ ] Composite scoring calculation
- [ ] Mode A vs Mode B branching

### Integration Tests
- [ ] Full Part1 → Part2 → Part3 flow
- [ ] Literature search with biomcp
- [ ] Refinement loop (max 3 iterations)
- [ ] HTML report generation

### End-to-End Test
```bash
# Run LangGraph dev server
langgraph dev

# Test with sample data
# Mode A: interest_clusters provided
curl -X POST http://localhost:2024/runs \
  -H "Content-Type: application/json" \
  -d '{
    "assistant_id": "biological_interpreter",
    "input": {
      "interest_clusters": ["4", "17", "14"],
      "results_dir": "res/",
      "adata_path": "n_adata.h5ad",
      "lrdata_path": "lrdata.h5ad"
    }
  }'

# Mode B: interest_celltypes provided
curl -X POST http://localhost:2024/runs \
  -H "Content-Type: application/json" \
  -d '{
    "assistant_id": "biological_interpreter",
    "input": {
      "interest_celltypes": ["Invasive Tumor", "Prolif Invasive Tumor"],
      "results_dir": "res/",
      "adata_path": "n_adata.h5ad",
      "lrdata_path": "lrdata.h5ad"
    }
  }'
```

### Expected Output
- Dark-themed HTML report similar to `Breast_Cancer_CCI_Comprehensive_Analysis_Report.html`
- Executive summary with key findings
- Part1, Part2, Part3 tabs with interpretations
- Literature references (PMIDs)
- Interactive elements (tabs, pagination)

## Dependencies

### Required
- langchain-core
- langgraph
- pandas (CSV reading)
- jinja2 (HTML templating)

### MCP Integration
- biomcp (literature search)
- pubmed-download (paper retrieval)
- sequential-thinking (complex analysis)

## Notes

- Part1 analyses are pre-computed (CSV/PNG files)
- Agent interprets results, doesn't run analyses
- Literature search targets specific claims for evidence
- Quality reflection ensures biological plausibility
- Maximum 3 refinement iterations
