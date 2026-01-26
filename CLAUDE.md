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
- `LLM_PROVIDER`: `google`, `openai` (default), or `ollama`
- `GOOGLE_MODEL`: Default `gemini-2.0-flash`
- `OPENAI_MODEL`: Default `gpt-4.1-mini`
- `OLLAMA_MODEL`: Default `gpt-oss:20b`
- `OLLAMA_BASE_URL`: Default `http://localhost:6000`

### Frontend (agent-chat-ui/.env)
- `NEXT_PUBLIC_API_URL`: LangGraph API endpoint (default: `http://localhost:2024`)
- `NEXT_PUBLIC_ASSISTANT_ID`: Graph ID (`agent` or `biological_interpreter`)

### Version Pinning Note
`langgraph-api` and `sse-starlette` are pinned for compatibility. See `pyproject.toml` comments before updating.

### Recursion Limits
Default recursion limits are set in `graph_builders.py`:
- STPipelineBuilderAgent: 50
- BiologicalInterpreterAgent: 100 (due to complex multi-node workflow)

## Architecture

### Core Design Pattern

OOP-based LangGraph agent architecture:

1. **BaseAgent** (`src/base/base_agent.py`): Abstract base class that all agents extend
   - Provides `init_nodes()` and `init_edges()` abstract methods
   - Handles graph compilation with optional checkpointer/store
   - Supports sync (`invoke`/`stream`) and async (`ainvoke`/`astream`) execution

2. **BaseState** (`src/base/base_state.py`): Pydantic-based state with message history using `add_messages` reducer

3. **Graph Builders** (`src/agents/graph_builders.py`): Factory functions that create compiled graphs for LangGraph CLI

### Agent Implementation Pattern

```python
class MyAgent(BaseAgent):
    NODE_NAMES: ClassVar[dict[str, str]] = {
        "NODE_KEY": "node_function_name",
    }

    def init_nodes(self, graph: StateGraph):
        graph.add_node(self.get_node_name("NODE_KEY"), self.node_function)

    def init_edges(self, graph: StateGraph):
        graph.add_edge(START, self.get_node_name("NODE_KEY"))
        graph.add_edge(self.get_node_name("NODE_KEY"), END)

    async def node_function(self, state: MyState, config: RunnableConfig):
        # Node implementation
        pass
```

### Available Agents

**STPipelineBuilderAgent** (`src/agents/pipeline/`): Multi-node workflow for ST pipeline construction with human-in-the-loop (HITL) support.

**BiologicalInterpreterAgent** (`src/agents/interpreter/`): Deep Agent for CCI analysis interpretation with:
- Dual-mode workflow: `cluster_to_celltype` (Mode A) or `celltype_to_cluster` (Mode B)
- 10-step sequential workflow: load → HITL targets → mode detection → strategic planning → Part 1-3 interpretation → synthesis → literature search → quality reflection → report generation
- Iterative refinement with quality reflection (max 3 iterations)
- Modular node implementations in `interpreter/nodes/`
- LangGraph Tools for analysis generation in `interpreter/tools/`

**NewAgentTemplate** (`src/agents/template/`): Copy this template when creating new agents.

### Tool Execution Dependencies

**Part 1 tools** can run in parallel (all depend only on n_adata.h5ad):
- Steps 1-5: spatial_plot, celltype_analysis, neighborhood_enrichment, pathway_enrichment, misty_analysis

**Part 2 tools** must run sequentially:
- Step 6 (`tool_run_liana_cci`) → creates `lrdata.h5ad`
- Steps 7-9 → require `lrdata.h5ad` and agent's factor/celltype selection

### State Serialization Pattern (Critical)

LangGraph's msgpack checkpointer cannot serialize pandas DataFrames. State uses `TypedDict` with **file paths only**:

```python
# ✓ Correct: Store file paths in AnalysisDataRef
part1_results: Optional[dict[str, AnalysisDataRef]]  # {"spatial": {"figure_path": "res/1.png"}}

# ✗ Wrong: Will fail serialization
# part1_results: Optional[dict[str, pd.DataFrame]]
```

Load DataFrames on-demand within node functions using `load_dataframe_from_ref()`.

### LLM Provider Abstraction

`src/agents/model.py` provides `create_llm(provider)` factory:
- Google Gemini (default)
- OpenAI GPT-4
- Ollama (local inference)

### LangGraph Deployment

The `langgraph.json` exports two graphs:
```json
{
  "graphs": {
    "agent": "src.agents.graph_builders:graph",
    "biological_interpreter": "src.agents.graph_builders:biological_interpreter_graph"
  }
}
```

### Async Environment Loading

For ASGI contexts (LangGraph dev server), use `load_env_async()` from `src/base/async_env.py` to prevent blocking I/O warnings. For CLI scripts and tests, use `load_env_sync_fallback()`.

### HITL (Human-in-the-Loop) Pattern

Use LangGraph's `interrupt()` for user interaction:

```python
from langgraph.types import interrupt

async def get_user_input_node(self, state, config):
    user_response = interrupt(value={"message": "Your prompt here"})
    # Process user_response after resume
    return {"user_input": user_response}
```

### Conditional Routing Pattern

**Important**: Routing functions must be **sync** (not async), returning node names as strings.

```python
def init_edges(self, graph: StateGraph):
    graph.add_conditional_edges(
        self.get_node_name("SOURCE_NODE"),
        self.routing_function,  # Must be sync
        [self.get_node_name("OPTION_A"), self.get_node_name("OPTION_B")]
    )

def routing_function(self, state, config) -> str:  # Sync, not async
    return self.get_node_name("OPTION_A") if state.get("condition") else self.get_node_name("OPTION_B")
```

## Domain Knowledge

### Supported ST Platforms
- **Spot-based**: Visium, Slide-seq, StereoSeq, STARmap
- **Single-cell resolution**: MERFISH, Xenium, CosMx, seqFISH

### Prompts Module

`src/prompts/` contains centralized prompt templates for both agents. When modifying LLM behavior, edit prompts here rather than hardcoding in node functions.

## Key Dependencies

- **langchain/langgraph**: LLM orchestration and agentic workflows
- **scanpy/squidpy**: Single-cell and spatial transcriptomics analysis
- **liana**: Cell-cell interaction analysis
- **omnipath**: Pathway and interaction resources
- **langchain-mcp-adapters**: MCP server integration for external tool calling

## Adding a New Agent

1. Copy `src/agents/template/` to a new directory
2. Define `NODE_NAMES` class variable for all node names
3. Implement `init_nodes()` and `init_edges()` methods
4. Create state schema using `TypedDict` (avoid storing DataFrames)
5. Add graph builder function in `src/agents/graph_builders.py`
6. Export in `langgraph.json`
