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

# Run the main entry point
python main.py
```

### Frontend (agent-chat-ui)

```bash
cd agent-chat-ui

# Install dependencies (uses pnpm)
pnpm install

# Run dev server (port 3001)
pnpm dev

# Build for production
pnpm build

# Lint and format
pnpm lint
pnpm lint:fix
pnpm format
```

## Environment Configuration

### Backend (.env)
- `LLM_PROVIDER`: `google` (default), `openai`, or `ollama`
- `GOOGLE_MODEL`: Default `gemini-2.0-flash`
- `OPENAI_MODEL`: Default `gpt-4.1`
- `OLLAMA_MODEL`: Default `gpt-oss:20b`
- `OLLAMA_BASE_URL`: Default `http://localhost:6000`
- LangSmith credentials for tracing (optional)

### Frontend (agent-chat-ui/.env)
- `NEXT_PUBLIC_API_URL`: LangGraph API endpoint (default: `http://localhost:2024`)
- `NEXT_PUBLIC_ASSISTANT_ID`: Graph ID (default: `agent`)

## Architecture

### Core Design Pattern

The codebase uses an OOP-based LangGraph agent architecture with:

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

### Key Agents

- **STPipelineBuilderAgent** (`src/agents/pipeline/`): Multi-node workflow for ST pipeline construction with human-in-the-loop (HITL) support
- **CCIInterpreterAgent** (`src/agents/interpreter/`): Biological interpretation of CCI results with RAG and literature search
- **NewAgentTemplate** (`src/agents/template/`): Copy this template when creating new agents

### LLM Provider Abstraction

`src/agents/model.py` provides `create_llm(provider)` factory supporting:
- Google Gemini (default)
- OpenAI GPT-4
- Ollama (local inference)

### LangGraph Deployment

The `langgraph.json` configuration exports graphs via:
```json
{
  "graphs": {
    "agent": "src.agents.graph_builders:graph"
  }
}
```

### Async Environment Loading

For ASGI contexts, use `load_env_async()` from `src/base/async_env.py` to prevent blocking I/O warnings.

### Frontend Architecture (agent-chat-ui)

Next.js 15 chat interface for LangGraph agents:
- **Tech Stack**: Next.js 15, React 19, Tailwind CSS 4, Radix UI
- **State**: React Hooks + nuqs (URL state)
- **Configuration**: YAML-based (`public/chat-config.yaml`, `public/chat-openers.yaml`)
- **Features**: File uploads, markdown/LaTeX rendering, tool call visualization, artifact viewer

Key directories:
- `src/`: Next.js app source code
- `public/`: Static assets and YAML configuration files

## Spatial Transcriptomics Platforms

The framework supports these ST normalization platforms:
- **Spot-based**: Visium, Slide-seq, StereoSeq, STARmap
- **Single-cell resolution**: MERFISH, Xenium, CosMx, seqFISH

## Key Dependencies

- **langchain/langgraph**: LLM orchestration and agentic workflows
- **scanpy/squidpy**: Single-cell and spatial transcriptomics analysis
- **liana**: Cell-cell interaction analysis
- **omnipath**: Pathway and interaction resources
