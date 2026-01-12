"""Base state classes for LangGraph agents using Pydantic."""
from typing import Annotated
from pydantic import BaseModel
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class BaseState(BaseModel):
    """Base state class for all agents using Pydantic."""
    messages: Annotated[list[BaseMessage], add_messages]


class BaseInputState(BaseState):
    """Base input state for agents."""
    ...


class BaseOutputState(BaseState):
    """Base output state for agents."""
    ...