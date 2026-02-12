# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DeepMAST (Deep Multimodal Analysis for Spatial Transcriptomics) is an AI-powered agent framework for bioinformatics analysis. It automates spatial transcriptomics (ST) pipeline construction, execution, and Cell-Cell Interaction (CCI) interpretation using LLM-powered LangGraph agents.

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

**LLM Provider:**
- `LLM_PROVIDER`: `kimi` (default in `model.py`), `openai`, `google`, `ollama`, or `claude`
- `OPENAI_MODEL`: Default `gpt-4.1-mini`
- `GOOGLE_MODEL`: Default `gemini-2.0-flash`
- `OLLAMA_MODEL`: Default `gpt-oss:20b`
- `OLLAMA_BASE_URL`: Default `http://localhost:6000`
- `ANTHROPIC_MODEL`: Default `claude-haiku-4-5-20251001`
- `KIMI_MODEL`: Default `moonshotai/kimi-k2.5` (via OpenRouter)
- `OPENROUTER_API_KEY`: Required for `kimi` provider

**Deep Interpreter / Wrapper Agent:**
- `DEEP_INTERPRETER_DATA_DIR`: Directory for CCI analysis results
- `SP_ENRICH_MCP_PYTHON`: Python path for sp-enrich-mcp server (required for wrapper's 11-step analysis)
- `SP_ENRICH_MCP_SERVER_PATH`: Path to sp-enrich-mcp server.py directory

**Literature Search / RAG:**
- `PUBMED_EMAIL`: Email for PubMed E-utilities
- `NCBI_API_KEY`: NCBI API key for higher rate limits
- `JINA_API_KEY`: Jina API key for full-text paper downloads
- `PUBMED_MCP_PYTHON`: Python path for PubMed MCP server
- `PUBMED_MCP_SERVER`: Path to PubMed MCP server
- `CCI_RAG_PYTHON`: Python path for CCI RAG server
- `CCI_RAG_SERVER`: Path to CCI RAG server
- `CCI_RAG_BASE_URL`: Default `http://localhost:8888`
- `BIOMCP_URL`: BioMCP server URL (default `http://localhost:8000/mcp`)

**Pipeline Executor:**
- `SC_REF_MCP_COMMAND`: SC reference recommendation server command (default `sc-reference-mcp`)

### Frontend (agent-chat-ui/.env)
- `NEXT_PUBLIC_API_URL`: LangGraph API endpoint (default: `http://localhost:2024`)
- `NEXT_PUBLIC_ASSISTANT_ID`: Graph ID (see langgraph.json for available graphs)

### Version Pinning Note
`langgraph-api` and `sse-starlette` are pinned for compatibility. See `pyproject.toml` comments before updating.

## Architecture

### Core Design Patterns

**Two Agent Frameworks in Use:**

1. **OOP BaseAgent Pattern** (`src/base/base_agent.py`): Traditional LangGraph agents
   - Used by: `STPipelineBuilderAgent`, `PubMedRAGAgent`, `PipelineExecutorAgent`, `SupervisorAgent`, `DeepInterpreterWrapperAgent`
   - Subclasses implement `init_nodes()` and `init_edges()` methods
   - Uses `NODE_NAMES` class variable to prevent string typos
   - `build_graph()` called in `__init__` — graph is ready immediately after construction

2. **DeepAgents Framework** (`deepagents` package): Multi-agent orchestration
   - Used by: `DeepInterpreterAgent` (the inner CCI interpreter invoked by the wrapper)
   - Uses `create_deep_agent()` with subagent configurations
   - Supports middleware (SkillsMiddleware), backends (FilesystemBackend)
   - 4 specialized subagents: planner, searcher, interpreter, reporter

**Hub-Pattern Routing:** Both Supervisor and Executor agents use a central `check_state` hub node. All other nodes route back to the hub, which then routes to the next incomplete phase based on state flags. This avoids complex edge combinatorics.

### LangGraph Deployment

The `langgraph.json` exports these graphs:

```json
{
  "Pipeline_builder": "src.agents.graph_builders:graph",
  "DeepMAST_RAG": "src.agents.graph_builders:pubmed_rag_graph",
  "Pipeline_executor": "src.agents.graph_builders:executor_graph",
  "Supervisor": "src.agents.supervisor.graph_builder:supervisor_graph",
  "Interpreter": "src.agents.deep_interpreter.graph_builder:deep_interpreter_wrapped_graph",
  "Sub_Planner": "src.agents.deep_interpreter.graph_builder:planner_subagent_graph",
  "Sub_Searcher": "src.agents.deep_interpreter.graph_builder:searcher_subagent_graph",
  "Sub_Interpreter": "src.agents.deep_interpreter.graph_builder:interpreter_subagent_graph",
  "Sub_Reporter": "src.agents.deep_interpreter.graph_builder:reporter_subagent_graph"
}
```

### Supervisor Agent (End-to-End Orchestrator)

`src/agents/supervisor/supervisor_agent.py` orchestrates the full DeepMAST workflow as a 4-phase pipeline with HITL approval gates before each phase:

```
START → router
  ├─ approve_pipeline → pipeline_builder → router
  ├─ approve_executor → pipeline_executor → router
  ├─ approve_interpreter → deep_interpreter → router
  └─ summary → END
```

- **Phase 1**: Pipeline Builder — designs the ST analysis pipeline
- **Phase 2**: Pipeline Executor — runs the pipeline on h5ad data via MCP
- **Phase 3**: Deep Interpreter — interprets CCI results and generates report
- **Phase 4**: Summary

Users can skip phases (type "skip" at approval gates) or skip directly to the interpreter (keywords: "skip pipeline", "interpret only"). Each child agent is invoked as a subgraph with `use_checkpointer=False`.

### Pipeline Executor Agent

`src/agents/executor/executor_agent.py` runs a 3-step ST pipeline (normalize → celltype → clustering) via dynamically loaded MCP servers.

```
START → check_state
  ├─ validate_inputs → collect_h5ad_info (if missing) → validate_inputs
  ├─ resolve_sc_reference (HITL for SC reference dataset)
  ├─ execute_normalization → check_state
  ├─ execute_celltype_analysis → check_state
  ├─ execute_spatial_clustering → check_state
  └─ save_results → END
```

**MCP Registry** (`src/agents/executor/mcp_registry.py`): Config-only registry mapping pipeline methods to MCP server configs. The executor creates and destroys MCP clients per-step via `async with MultiServerMCPClient(...)` for guaranteed subprocess cleanup.

**Deconvolution methods** (IRIS, cell2location, tangram) require a SC reference dataset. If the user skips SC reference selection, the celltype step auto-skips. **Cascading h5ad**: each step's output becomes the next step's input.

### Deep Interpreter Wrapper Agent (Full Analysis Pipeline)

`src/agents/deep_interpreter/wrapper_agent.py` is the recommended entry point for the Interpreter graph. It manages a full 11-step spatial analysis pipeline before invoking the Deep Agent:

```
START → check_state
  ├─ info_collection ↔ info_validation (collect h5ad, keys, directory)
  ├─ run_single_analysis_step (Steps 1-8 loop via MCP)
  ├─ research_discussion (2x interrupt(): cluster/celltype + factor selection)
  ├─ run_single_analysis_step_9_11 (Steps 9-11 loop via MCP)
  ├─ confirm_interpretation (interrupt() gate)
  └─ invoke_deep_agent → END
```

**Steps 1-8** (basic analysis): clustering, celltype heatmap, neighborhood enrichment, pathway enrichment, spatial relationships (MISTy), LIANA+ CCI, NMF factor scores, NMF loadings. Each step sends multimodal messages with base64-encoded figures.

**Research Discussion** (HITL): After Steps 1-8, reads `sig_clusterwithcelltyp.csv` and `res_liana_cluster_factor.csv`, uses LLM to suggest interesting clusters/celltypes, collects user selections via two sequential `interrupt()` calls.

**Steps 9-11** (targeted): NMF quadrant plot, spatial L-R interactions, cluster-level L-R interactions. These depend on user-selected `interest_clusters` and `sel_factor`.

**MCP Server**: Uses `sp-enrich-mcp` (FastMCP, stdio transport) configured via `SP_ENRICH_MCP_PYTHON` and `SP_ENRICH_MCP_SERVER_PATH` env vars.

### Deep Interpreter 4-Subagent Workflow

The inner Deep Agent (`src/agents/deep_interpreter/agent.py`) uses 4 specialized subagents:

1. **PLANNER**: Reads `/targets.json`, loads analysis data, generates biomedical context via BioMCP think, searches literature (10 papers for grounding) → outputs `/interpretation_guide.md`
2. **SEARCHER**: Part 1 → `/part1_papers.json` (spatial context, NO genes); Part 2+3 → `/liana_papers.json` (shared, searched ONCE). Uses `search_literature_dynamic` with automatic fallback
3. **INTERPRETER**: For each Part, reads `/partN_papers.json`, generates literature-grounded interpretation, validates claims inline, max 3 quality iterations (threshold ≥ 0.7). For Part 3, uses `prioritize_top_lr_pairs` (hybrid GenePT + Moran's R scoring). Supports RAG full-text mode with fallback to Abstract mode → outputs `/partN_final.md`
4. **REPORTER**: Cross-part synthesis, Phase 4.5 validates integration claims with independent literature search, generates HTML report → outputs `/synthesis.md`, `CCI_Analysis_Report.html`

Subagent configs: `src/agents/deep_interpreter/subagents/configs.py`
Subagent prompts: `src/agents/deep_interpreter/subagents/prompts.py`

### HITL (Human-in-the-Loop) Pattern

For Deep Interpreter, HITL is handled by the **wrapper agent** (`wrapper_agent.py`), not the Deep Agent itself:
1. Wrapper collects h5ad files, keys, data_directory from user
2. Wrapper runs MCP analysis and HITL research discussion
3. Wrapper passes pre-selected targets to Deep Agent via initial message
4. Deep Agent's planner parses targets and writes `/targets.json`

For traditional BaseAgent HITL, use LangGraph's `interrupt()`:
```python
from langgraph.types import interrupt
user_response = interrupt(value={"message": "Your prompt here"})
```

### Skills System (Progressive Disclosure)

Skills provide workflow guidance for subagents. Located in `skills/`:
- `biomedical-literature-search/SKILL.md`: 5-phase search workflow for SEARCHER
- `html-report-generator/SKILL.md`: Report generation guidelines
- `pubmed-eutils-search/SKILL.md`: PubMed E-utilities search patterns
- `scanpy/SKILL.md`, `anndata/SKILL.md`, `cellxgene-census/SKILL.md`: Library usage guides

Skills are injected via `SkillsMiddleware` (`src/agents/deep_interpreter/middleware/skills_middleware.py`) — agents see skill metadata in system prompt and can read full SKILL.md files for detailed strategies.

### State Serialization (Critical)

LangGraph's msgpack checkpointer cannot serialize pandas DataFrames. State must use **file paths only**:

```python
# Correct: Store file paths in state
part1_results: dict[str, AnalysisDataRef]  # {"spatial": {"figure_path": "res/1.png"}}

# Wrong: Will fail serialization
part1_results: dict[str, pd.DataFrame]
```

Pydantic models (e.g., `ExecutionStepResult`, `SCReferenceInfo` in executor) are stored as dicts via `.model_dump()`.

### Conditional Routing Pattern

Routing functions must be **sync** (not async), returning node names as strings:

```python
def routing_function(self, state, config) -> str:  # Sync, not async
    return self.get_node_name("OPTION_A") if state.get("condition") else self.get_node_name("OPTION_B")
```

### LLM Provider Abstraction

`src/agents/model.py` provides `create_llm(provider)` factory:
- Kimi (default via OpenRouter), OpenAI, Google Gemini, Ollama, Claude (Anthropic)
- Provider determined by `LLM_PROVIDER` env var or explicit parameter
- Note: `model.py` defaults to `kimi` but some graph builders default to `openai` — check `LLM_PROVIDER` env var

### Async Environment Loading

For ASGI contexts (LangGraph dev server), use `load_env_async()` from `src/base/async_env.py`. For CLI/tests, use `load_env_sync_fallback()`. Graph builders in `graph_builders.py` use `_run_async_safely()` to handle both running and non-running event loops.

## Domain Knowledge

### Supported ST Platforms
- **Spot-based**: Visium, Slide-seq, StereoSeq, STARmap
- **Single-cell resolution**: MERFISH, Xenium, CosMx, seqFISH

Single-cell platforms require `celltype_key` in the wrapper agent.

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
- **langchain-mcp-adapters**: MCP server integration (MultiServerMCPClient for stdio transport)

## Adding a New Agent

### Using BaseAgent (Traditional LangGraph)

1. Copy `src/agents/template/` to a new directory
2. Define `NODE_NAMES` class variable
3. Implement `init_nodes()` and `init_edges()` methods
4. Create state schema using `TypedDict` (avoid storing DataFrames)
5. Add graph builder function in `src/agents/graph_builders.py`
6. Export in `langgraph.json`

### Using DeepAgents Framework

1. Define subagent configs with tools and prompts in `subagents/configs.py`
2. Create backend factory for filesystem operations
3. Use `create_deep_agent()` with subagents list
4. Optionally add middleware (SkillsMiddleware, etc.)

## Testing Subagents

`langgraph dev` serves **all** graphs defined in `langgraph.json` simultaneously. There is no `--graph` option to select individual graphs.

```bash
# 1. Start the dev server (serves all graphs)
langgraph dev

# 2. Select the graph in LangGraph Studio UI:
#    Supervisor, Pipeline_builder, Pipeline_executor, Interpreter,
#    Sub_Planner, Sub_Searcher, Sub_Interpreter, Sub_Reporter

# Or call a specific graph via API:
# curl -X POST http://localhost:2024/runs \
#   -d '{"assistant_id": "Sub_Searcher", "input": {...}}'
```

Standalone subagent graphs have per-subagent recursion limits (planner: 100, searcher: 150, interpreter: 200, reporter: 200) — higher than LangGraph's default of 25.
