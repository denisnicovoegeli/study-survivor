"""Graph `chat`: Fragen zum Studium (SW5 bis SW8).

    START → classify ─┬─ reject ───────────────→ END
                      └─ answer ⇄ tools
                           └──→ respond ───────→ END
"""
import sys
from datetime import datetime
from typing import Annotated, Literal

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.types import RetryPolicy
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from study_agent.agent import prompts
from study_agent.agent.tools import LOCAL_TOOLS
from study_agent.llm import MAIN_MODEL, chat_model
from study_agent.pipeline.briefing import TZ


class Classification(BaseModel):
    """Einordnung der Frage (strukturierte Ausgabe, SW5)."""
    reason: str = Field(description="Kurze Begründung der Einordnung, ein Satz")
    in_scope: bool = Field(description="true, wenn der Studien-Assistent zuständig ist")
    category: Literal["termine", "inhalt", "pruefung", "organisation", "sonstiges"]


class AgentResponse(BaseModel):
    """Antwort an den Studenten."""
    answer: str = Field(description="Antwort in Markdown")
    quellen: list[str] = Field(description="Quellen als 'Kurs / Datei / Folie N'")
    ergaenzung: bool = Field(description="true, wenn eigene Ergänzungen ausserhalb des Kursmaterials enthalten sind")


class ChatState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    summary: str
    in_scope: bool
    category: str
    tools_used: list[str]
    response: dict


def _current_turn(messages: list[AnyMessage]) -> list[AnyMessage]:
    """Nachrichten ab der letzten Frage des Studenten."""
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            return messages[i:]
    return messages


def _summary_block(state: ChatState) -> str:
    s = state.get("summary")
    return f"\n\n# Bisheriges Gespräch (Zusammenfassung)\n{s}" if s else ""


async def handle_tool_errors(request, handler):
    """Fehler-Wrapper (SW6): Tool-Fehler werden zur ToolMessage, das Modell kann reagieren."""
    try:
        return await handler(request)
    except GraphBubbleUp:  # Interrupts (HITL) nicht verschlucken
        raise
    except ConnectionError:  # RetryPolicy des Knotens soll greifen
        raise
    except Exception as e:
        return ToolMessage(content=f"Fehler in {request.tool_call['name']}: {e}. Sag der Person, was nicht geklappt hat.",
                           tool_call_id=request.tool_call["id"], status="error")


async def load_mcp_tools():
    """Tools des eigenen MCP-Servers `kursmaterial` über stdio (SW6)."""
    from langchain_mcp_adapters.client import MultiServerMCPClient

    client = MultiServerMCPClient({
        "kursmaterial": {
            "transport": "stdio",
            "command": sys.executable,
            "args": ["-m", "study_agent.agent.mcp_server"],
        }
    })
    return await client.get_tools()


def build_chat_graph(tools, model: str = MAIN_MODEL, checkpointer=None, store=None):
    llm = chat_model(model)
    classifier = llm.with_structured_output(Classification, method="json_schema")
    formatter = llm.with_structured_output(AgentResponse, method="json_schema")
    llm_tools = llm.bind_tools(tools)

    async def classify(state: ChatState):
        frage = state["messages"][-1]
        c: Classification = await classifier.ainvoke([
            SystemMessage(prompts.CLASSIFY_PROMPT.format(zusammenfassung=_summary_block(state))),
            HumanMessage(frage.content),
        ])
        return {"in_scope": c.in_scope, "category": c.category}

    def route(state: ChatState):
        return "answer" if state["in_scope"] else "reject"

    async def reject(state: ChatState):
        resp = AgentResponse(answer=prompts.REJECT_TEXT, quellen=[], ergaenzung=False)
        return {"messages": [AIMessage(prompts.REJECT_TEXT)], "response": resp.model_dump(), "tools_used": []}

    async def answer(state: ChatState):
        system = prompts.SYSTEM_PROMPT.format(
            heute=datetime.now(TZ).strftime("%A, %d.%m.%Y"), profil="", zusammenfassung=_summary_block(state))
        msg = await llm_tools.ainvoke([SystemMessage(system), *state["messages"]])
        return {"messages": [msg]}

    async def respond(state: ChatState):
        turn = _current_turn(state["messages"])
        tool_msgs = [m for m in turn if isinstance(m, ToolMessage)]
        used = sorted({m.name for m in tool_msgs if m.name})
        final = state["messages"][-1].content
        results = "\n\n".join(f"[{m.name}]\n{str(m.content)[:3000]}" for m in tool_msgs) or "(keine)"
        resp: AgentResponse = await formatter.ainvoke(
            prompts.RESPOND_PROMPT.format(tool_results=results, answer=final))
        resp.answer = final if isinstance(final, str) and final else resp.answer
        return {"response": resp.model_dump(), "tools_used": used}

    g = StateGraph(ChatState)
    g.add_node("classify", classify)
    g.add_node("reject", reject)
    g.add_node("answer", answer)
    g.add_node("tools", ToolNode(tools, awrap_tool_call=handle_tool_errors),
               retry_policy=RetryPolicy(max_attempts=3, retry_on=ConnectionError))
    g.add_node("respond", respond)
    g.add_edge(START, "classify")
    g.add_conditional_edges("classify", route, ["answer", "reject"])
    g.add_conditional_edges("answer", tools_condition, {"tools": "tools", END: "respond"})
    g.add_edge("tools", "answer")
    g.add_edge("respond", END)
    g.add_edge("reject", END)
    return g.compile(checkpointer=checkpointer, store=store)


async def make_chat_graph(**kw):
    tools = [*LOCAL_TOOLS, *await load_mcp_tools()]
    return build_chat_graph(tools, **kw)
