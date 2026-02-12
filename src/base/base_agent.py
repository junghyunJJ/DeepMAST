"""Base classes for building LangGraph agents with OOP patterns."""
from typing import Any, ClassVar

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import StateGraph
from langgraph.store.base import BaseStore
from langgraph.types import RetryPolicy


class BaseAgent:
    """
    Base class for LangGraph agents.
    Provides common functionality for building agents in an object-oriented manner.
    """
    
    # Node names as class attributes to prevent string typos
    NODE_NAMES: ClassVar[dict[str, str]] = {}
    
    def __init__(
        self,
        model: BaseChatModel,
        state_schema: Any,
        config_schema: Any | None = None,
        input_schema: Any | None = None,
        output_schema: Any | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
        store: BaseStore | None = None,
        max_retry_attempts: int = 2,
        agent_name: str | None = None,
        is_debug: bool = True,
    ):
        """
        Initialize base agent.
        
        Args:
            model: Language model to use
            state_schema: Schema for the agent's state
            config_schema: Optional configuration schema
            input_schema: Optional input schema
            output_schema: Optional output schema
            checkpointer: Optional checkpointer for state persistence
            store: Optional store for shared state
            max_retry_attempts: Maximum retry attempts for operations
            agent_name: Optional name for the agent
            is_debug: Enable debug mode
        """
        self.model = model
        self.state_schema = state_schema
        self.config_schema = config_schema
        self.input_schema = input_schema
        self.output_schema = output_schema
        self.checkpointer = checkpointer
        self.store = store
        self.max_retry_attempts = max_retry_attempts
        self.agent_name = agent_name or self.__class__.__name__
        self.is_debug = is_debug
        
        # Setup retry policy
        self.retry_policy = None
        if self.max_retry_attempts > 0:
            self.retry_policy = RetryPolicy(
                max_attempts=self.max_retry_attempts,
            )
        
        # Build the graph
        self.graph = self.build_graph()

    def get_node_name(self, key="DEFAULT") -> str:
        """
        Get node name by key.
        
        Args:
            key: Node name key (defaults to "DEFAULT")
            
        Returns:
            Node name string
            
        Raises:
            ValueError: If key not found in NODE_NAMES
        """
        if key not in self.NODE_NAMES:
            raise ValueError(f"Node name key '{key}' is not defined.")
        return self.NODE_NAMES.get(key, "DEFAULT")

    def get_model(self, config=None):
        """Get LLM, checking runtime config first, falling back to init-time model."""
        if config:
            configurable = config.get("configurable", {})
            if configurable.get("llm_provider", "").strip():
                from src.agents.model import create_llm_from_config

                return create_llm_from_config(config)
        return self.model

    def init_nodes(self, graph: StateGraph):
        """
        Initialize graph nodes.
        Must be implemented by subclasses.
        
        Args:
            graph: StateGraph to add nodes to
        """
        raise NotImplementedError("Subclasses must implement init_nodes method")
    
    def init_edges(self, graph: StateGraph):
        """
        Initialize graph edges.
        Must be implemented by subclasses.
        
        Args:
            graph: StateGraph to add edges to
        """
        raise NotImplementedError("Subclasses must implement init_edges method")
    
    def build_graph(self):
        """
        Build the complete graph.
        
        Returns:
            Compiled StateGraph
        """
        # Create state graph with the provided schema
        from src.agents.llm_config import LLMConfigSchema

        effective_config_schema = self.config_schema or LLMConfigSchema

        _graph = StateGraph(
            state_schema=self.state_schema,
            config_schema=effective_config_schema,
            input_schema=self.input_schema,
            output_schema=self.output_schema,
        )
        
        # Initialize nodes and edges
        self.init_nodes(_graph)
        self.init_edges(_graph)
        
        # Compile with checkpointer, store, name, and debug flag
        if self.agent_name:
            self.graph = _graph.compile(
                store=self.store,
                checkpointer=self.checkpointer,
                name=f"{self.agent_name}",
                debug=self.is_debug,
            )
        else:
            self.graph = _graph.compile(
                store=self.store,
                checkpointer=self.checkpointer,
                name=f"{self.__class__.__name__}",
                debug=self.is_debug,
            )
        return self.graph
    
    def invoke(self, input_state: dict, config: dict | None = None) -> dict:
        """
        Invoke the agent synchronously.
        
        Args:
            input_state: Initial state
            config: Optional configuration
            
        Returns:
            Final state
        """
        return self.graph.invoke(input_state, config=config)
    
    async def ainvoke(self, input_state: dict, config: dict | None = None) -> dict:
        """
        Invoke the agent asynchronously.
        
        Args:
            input_state: Initial state
            config: Optional configuration
            
        Returns:
            Final state
        """
        return await self.graph.ainvoke(input_state, config=config)
    
    def stream(self, input_state: dict, config: dict | None = None):
        """
        Stream agent execution.
        
        Args:
            input_state: Initial state
            config: Optional configuration
            
        Yields:
            State updates
        """
        for update in self.graph.stream(input_state, config=config):
            yield update
    
    async def astream(self, input_state: dict, config: dict | None = None):
        """
        Stream agent execution asynchronously.
        
        Args:
            input_state: Initial state
            config: Optional configuration
            
        Yields:
            State updates
        """
        async for update in self.graph.astream(input_state, config=config):
            yield update