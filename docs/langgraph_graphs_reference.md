# LangGraph Graphs Reference

## Overview

DeepMAST provides multiple LangGraph graphs for different use cases. Run with:

```bash
langgraph dev
```

Then select a graph from LangGraph Studio at `http://127.0.0.1:2024`.

## Registered Graphs

| Graph ID | Description | Workflow Order |
|----------|-------------|----------------|
| `Pipeline_builder` | ST Pipeline Builder | - |
| `DeepMAST_RAG` | PubMed RAG Agent | - |
| `Interpreter` | Deep Interpreter (full workflow) | - |
| `Sub_Planner` | PLANNER subagent | 1 |
| `Sub_Searcher` | SEARCHER subagent | 2 |
| `Sub_Interpreter` | INTERPRETER subagent | 3 |
| `Sub_Reporter` | REPORTER subagent | 4 |

## Main Agents

### Pipeline_builder
ST (Spatial Transcriptomics) pipeline construction agent with HITL support.

### DeepMAST_RAG
PubMed-based RAG agent for biological question answering.

### Interpreter
Full Deep Interpreter workflow with 4 subagents orchestrated by DeepAgent framework.

## Subagent Details

### Sub_Planner (Step 1)

**Role**: Target confirmation + hypothesis generation

| Input | Output |
|-------|--------|
| `/targets.json` | `/strategic_plan.md` |
| Analysis data | `/analysis_summary.md` |
| | `/data_path.txt` |

**Tools**: `load_analysis_data`

### Sub_Searcher (Step 2)

**Role**: Context extraction + literature search

| Input | Output |
|-------|--------|
| Analysis data | `/part1_papers.json` (Part 1) |
| Strategic plan | `/liana_papers.json` (Part 2+3 shared) |

**Tools**: `load_analysis_data`, `search_literature_dynamic`, `search_literature`, `think_tool`

### Sub_Interpreter (Step 3)

**Role**: Literature-grounded interpretation with inline validation

| Input | Output |
|-------|--------|
| `/part1_papers.json` | `/part1_final.md` |
| `/liana_papers.json` | `/part2_final.md` |
| | `/part3_final.md` |

**Tools**: `load_analysis_data`, `validate_claim_literature`, `validate_quality`, `think_tool`, `prepare_rag_literature`, `search_literature_fulltext`, `validate_claim_fulltext`

**Features**:
- RAG support for full-text paper search (if Docker available)
- Fallback to Abstract mode if RAG unavailable
- Quality score >= 0.7 required (max 3 iterations)

### Sub_Reporter (Step 4)

**Role**: Cross-part synthesis + HTML report generation

| Input | Output |
|-------|--------|
| `/part1_final.md` | `/synthesis.md` |
| `/part2_final.md` | `CCI_Analysis_Report.html` |
| `/part3_final.md` | |

**Tools**: `load_analysis_data`, `generate_html_report`

## Testing Workflow

To test subagents sequentially:

```
1. Sub_Planner   → Confirm targets, generate strategy
2. Sub_Searcher  → Search literature for each part
3. Sub_Interpreter → Generate interpretations
4. Sub_Reporter  → Create final report
```

### Prerequisites for Subagent Testing

Each subagent expects outputs from previous steps:

| Subagent | Required Files |
|----------|----------------|
| `Sub_Planner` | `/targets.json`, analysis data (`n_adata.h5ad`, etc.) |
| `Sub_Searcher` | `/strategic_plan.md`, `/data_path.txt` |
| `Sub_Interpreter` | `/part1_papers.json`, `/liana_papers.json` |
| `Sub_Reporter` | `/part1_final.md`, `/part2_final.md`, `/part3_final.md` |

## Environment Variables

Configure in `.env`:

```bash
# LLM Provider
LLM_PROVIDER=openai  # or google, ollama, claude

# Data Directory
DEEP_INTERPRETER_DATA_DIR=/path/to/analysis/results

# Model Names (optional)
OPENAI_MODEL=gpt-4.1-mini
GOOGLE_MODEL=gemini-2.0-flash
OLLAMA_MODEL=gpt-oss:20b
ANTHROPIC_MODEL=claude-haiku-4-5-20251001
```

## agent-chat-ui Configuration

To use a specific graph with agent-chat-ui:

```bash
# In agent-chat-ui/.env
NEXT_PUBLIC_ASSISTANT_ID=Sub_Interpreter  # or any Graph ID
```

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    Deep Interpreter                          │
│  ┌─────────┐   ┌─────────┐   ┌────────────┐   ┌──────────┐ │
│  │ PLANNER │ → │ SEARCHER│ → │INTERPRETER │ → │ REPORTER │ │
│  └─────────┘   └─────────┘   └────────────┘   └──────────┘ │
│       │             │              │               │        │
│       ▼             ▼              ▼               ▼        │
│  strategic     papers.json    partN_final.md    Report.html │
│  _plan.md                                                   │
└─────────────────────────────────────────────────────────────┘
```
