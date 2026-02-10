# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DeepMAST (Deep Multimodal Analysis for Spatial Transcriptomics) is an AI-powered agent framework for bioinformatics analysis. It automates spatial transcriptomics (ST) pipeline construction and Cell-Cell Interaction (CCI) interpretation using LLM-powered LangGraph agents.

## Development Commands

### Backend (Python/LangGraph)

```bash
# Install dependencies (uses uv package manager)
uv pip install -e .

# Run LangGraph development server (port 2024)
langgraph dev

# Build LangGraph for deployment
langgraph build
```

### Frontend (agent-chat-ui)

```bash
cd agent-chat-ui
pnpm install
pnpm dev        # Dev server on port 3001
pnpm build      # Production build
pnpm lint       # Run linter
```

## Environment Configuration

### Backend (.env)
- `LLM_PROVIDER`: `openai` (default), `google`, `ollama`, or `claude`
- `OPENAI_MODEL`: Default `gpt-4.1-mini`
- `GOOGLE_MODEL`: Default `gemini-2.0-flash`
- `OLLAMA_MODEL`: Default `gpt-oss:20b`
- `OLLAMA_BASE_URL`: Default `http://localhost:6000`
- `ANTHROPIC_MODEL`: Default `claude-haiku-4-5-20251001`
- `DEEP_INTERPRETER_DATA_DIR`: Directory for CCI analysis results

### Frontend (agent-chat-ui/.env)
- `NEXT_PUBLIC_API_URL`: LangGraph API endpoint (default: `http://localhost:2024`)
- `NEXT_PUBLIC_ASSISTANT_ID`: Graph ID (see langgraph.json for available graphs)

### Version Pinning Note
`langgraph-api` and `sse-starlette` are pinned for compatibility. See `pyproject.toml` comments before updating.

## Architecture

### Core Design Patterns

**Two Agent Frameworks in Use:**

1. **OOP BaseAgent Pattern** (`src/base/base_agent.py`): Traditional LangGraph agents
   - Used by: `STPipelineBuilderAgent`, `PubMedRAGAgent`
   - Subclasses implement `init_nodes()` and `init_edges()` methods
   - Uses `NODE_NAMES` class variable to prevent string typos

2. **DeepAgents Framework** (`deepagents` package): Multi-agent orchestration
   - Used by: `DeepInterpreterAgent` (the main CCI interpreter)
   - Uses `create_deep_agent()` with subagent configurations
   - Supports middleware (SkillsMiddleware), backends (FilesystemBackend)
   - 4 specialized subagents: planner, searcher, interpreter, reporter

### LangGraph Deployment

The `langgraph.json` exports these graphs:

```json
{
  "Pipeline_builder": "src.agents.graph_builders:graph",
  "DeepMAST_RAG": "src.agents.graph_builders:pubmed_rag_graph",
  "Interpreter": "src.agents.deep_interpreter.graph_builder:deep_interpreter_wrapped_graph",
  "Sub_Planner": "src.agents.deep_interpreter.graph_builder:planner_subagent_graph",
  "Sub_Searcher": "src.agents.deep_interpreter.graph_builder:searcher_subagent_graph",
  "Sub_Interpreter": "src.agents.deep_interpreter.graph_builder:interpreter_subagent_graph",
  "Sub_Reporter": "src.agents.deep_interpreter.graph_builder:reporter_subagent_graph"
}
```

### Deep Interpreter 4-Agent Workflow

The main analysis agent uses a simplified 4-subagent architecture:

1. **PLANNER**: Reads `/targets.json`, loads analysis data, generates biomedical context, searches literature → outputs `/interpretation_guide.md`
2. **SEARCHER**: Extracts context, searches literature (Part 1 → `/part1_papers.json`, Part 2+3 → `/liana_papers.json` shared)
3. **INTERPRETER**: Literature-grounded interpretation with inline validation, max 3 quality iterations → outputs `/partN_final.md`
4. **REPORTER**: Cross-part synthesis with independent literature validation → outputs `/synthesis.md`, `CCI_Analysis_Report.html`

Subagent configs are in `src/agents/deep_interpreter/subagents/configs.py`.

### HITL (Human-in-the-Loop) Pattern

For Deep Interpreter, HITL is handled by the **wrapper agent** (`wrapper_agent.py`), not the Deep Agent itself:
1. Wrapper collects `data_directory`, `analysis_mode`, targets from user
2. Wrapper writes `/targets.json` to filesystem
3. Wrapper invokes Deep Agent with pre-selected targets

For traditional BaseAgent HITL, use LangGraph's `interrupt()`:
```python
from langgraph.types import interrupt
user_response = interrupt(value={"message": "Your prompt here"})
```

### Skills System (Progressive Disclosure)

Skills provide workflow guidance for subagents. Located in `skills/`:
- `biomedical-literature-search/SKILL.md`: 5-phase search workflow for SEARCHER
- `html-report-generator/SKILL.md`: Report generation guidelines

Skills are injected via `SkillsMiddleware` - agents see skill metadata in system prompt and can read full SKILL.md files for detailed strategies.

### State Serialization (Critical)

LangGraph's msgpack checkpointer cannot serialize pandas DataFrames. State must use **file paths only**:

```python
# ✓ Correct: Store file paths in state
part1_results: dict[str, AnalysisDataRef]  # {"spatial": {"figure_path": "res/1.png"}}

# ✗ Wrong: Will fail serialization
part1_results: dict[str, pd.DataFrame]
```

### Conditional Routing Pattern

Routing functions must be **sync** (not async), returning node names as strings:

```python
def routing_function(self, state, config) -> str:  # Sync, not async
    return self.get_node_name("OPTION_A") if state.get("condition") else self.get_node_name("OPTION_B")
```

### LLM Provider Abstraction

`src/agents/model.py` provides `create_llm(provider)` factory:
- OpenAI (default), Google Gemini, Ollama, Claude (Anthropic)
- Provider determined by `LLM_PROVIDER` env var or explicit parameter

### Async Environment Loading

For ASGI contexts (LangGraph dev server), use `load_env_async()` from `src/base/async_env.py`. For CLI/tests, use `load_env_sync_fallback()`.

## Domain Knowledge

### Supported ST Platforms
- **Spot-based**: Visium, Slide-seq, StereoSeq, STARmap
- **Single-cell resolution**: MERFISH, Xenium, CosMx, seqFISH

### Analysis Parts (Deep Interpreter)
- **Part 1**: Spatial patterns, pathway biology (no gene-level analysis)
- **Part 2**: CCI/NMF patterns, L-R interactions with LIANA
- **Part 3**: Detailed L-R biology and mechanisms

### Literature Search Strategy
SEARCHER uses context-aware searches:
- Part 1: `spatial_search_context` (pathways + celltypes, NO genes)
- Part 2+3: `lr_search_context` (genes + pathways + celltypes) - searched ONCE, shared

## Key Dependencies

- **langchain/langgraph**: LLM orchestration and agentic workflows
- **deepagents**: Multi-agent orchestration framework (for Deep Interpreter)
- **scanpy/squidpy**: Single-cell and spatial transcriptomics analysis
- **liana**: Cell-cell interaction analysis
- **langchain-mcp-adapters**: MCP server integration

## Adding a New Agent

### Using BaseAgent (Traditional LangGraph)

1. Copy `src/agents/template/` to a new directory
2. Define `NODE_NAMES` class variable
3. Implement `init_nodes()` and `init_edges()` methods
4. Create state schema using `TypedDict` (avoid storing DataFrames)
5. Add graph builder function in `src/agents/graph_builders.py`
6. Export in `langgraph.json`

### Using DeepAgents Framework

1. Define subagent configs with tools and prompts
2. Create backend factory for filesystem operations
3. Use `create_deep_agent()` with subagents list
4. Optionally add middleware (SkillsMiddleware, etc.)

## Testing Subagents

`langgraph dev` serves **all** graphs defined in `langgraph.json` simultaneously. There is no `--graph` option to select individual graphs.

```bash
# 1. Start the dev server (serves all graphs)
langgraph dev

# 2. Select the subagent in LangGraph Studio UI:
#    Sub_Planner, Sub_Searcher, Sub_Interpreter, Sub_Reporter

# Or call a specific subagent via API:
# curl -X POST http://localhost:2024/runs \
#   -d '{"assistant_id": "Sub_Searcher", "input": {...}}'
```
