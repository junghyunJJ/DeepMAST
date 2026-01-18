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
- `LLM_PROVIDER`: `google` (default), `openai`, or `ollama`
- `GOOGLE_MODEL`: Default `gemini-2.0-flash`
- `OPENAI_MODEL`: Default `gpt-4.1-mini`
- `OLLAMA_MODEL`: Default `gpt-oss:20b`
- `OLLAMA_BASE_URL`: Default `http://localhost:6000`

### Frontend (agent-chat-ui/.env)
- `NEXT_PUBLIC_API_URL`: LangGraph API endpoint (default: `http://localhost:2024`)
- `NEXT_PUBLIC_ASSISTANT_ID`: Graph ID (`agent` or `biological_interpreter`)

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

### BiologicalInterpreterAgent Nodes Structure

```
interpreter/
├── biological_interpreter_agent.py  # Main agent with graph definition
├── biological_interpreter_state.py  # State schema with TypedDicts
├── nodes/                            # Node implementations
│   ├── load_results.py              # Load/generate analysis results
│   ├── strategic_planning.py        # Hypothesis-driven planning
│   ├── part1_interpretation.py      # 5 spatial analyses (1-1 to 1-5)
│   ├── part2_interpretation.py      # 4 CCI analyses (2-6 to 2-9)
│   ├── part3_interpretation.py      # 2 L-R visualization analyses
│   ├── synthesis.py                 # Cross-part narrative synthesis
│   ├── literature_search.py         # PubMed evidence gathering
│   ├── quality_reflection.py        # Quality validation + refinement
│   └── report_generator.py          # HTML report generation
└── tools/                           # LangGraph Tools for analysis generation
    ├── part1_tools.py               # 5 tools (can run parallel)
    ├── part2_tools.py               # 4 tools (must run sequential)
    ├── part3_tools.py               # 2 tools (agent dynamic)
    └── analysis_tools.py            # Input schemas and utilities
```

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

For ASGI contexts, use `load_env_async()` from `src/base/async_env.py` to prevent blocking I/O warnings.

## Spatial Transcriptomics Platforms

Supported ST normalization platforms:
- **Spot-based**: Visium, Slide-seq, StereoSeq, STARmap
- **Single-cell resolution**: MERFISH, Xenium, CosMx, seqFISH

## Key Dependencies

- **langchain/langgraph**: LLM orchestration and agentic workflows
- **scanpy/squidpy**: Single-cell and spatial transcriptomics analysis
- **liana**: Cell-cell interaction analysis
- **omnipath**: Pathway and interaction resources
