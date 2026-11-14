"""LangGraph definition: START -> agent -> (tools -> agent)* -> END."""

import uuid
from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.runnables import Runnable
from langgraph.graph import END, START, StateGraph

from app.runtime.state import AgentState
from app.runtime.tool_node import ToolNode

AGENT_NODE = "agent"
TOOLS_NODE = "tools"


def build_graph(
    model: Runnable[LanguageModelInput, BaseMessage], system_prompt: str, tool_node: ToolNode
) -> Any:
    async def agent(state: AgentState) -> dict[str, Any]:
        messages: list[Any] = list(state["messages"])
        if system_prompt:
            messages.insert(0, SystemMessage(system_prompt))
        response = await model.ainvoke(messages)
        response.id = str(uuid.uuid4())  # stable id, reused as the DB message id
        return {"messages": [response]}

    def after_agent(state: AgentState) -> str:
        last = state["messages"][-1]
        return TOOLS_NODE if isinstance(last, AIMessage) and last.tool_calls else END

    def after_tools(state: AgentState) -> str:
        return END if state.get("stop_reason") else AGENT_NODE

    graph = StateGraph(AgentState)
    graph.add_node(AGENT_NODE, agent)
    graph.add_node(TOOLS_NODE, tool_node)
    graph.add_edge(START, AGENT_NODE)
    graph.add_conditional_edges(AGENT_NODE, after_agent, [TOOLS_NODE, END])
    graph.add_conditional_edges(TOOLS_NODE, after_tools, [AGENT_NODE, END])
    return graph.compile()
