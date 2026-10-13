
import os
from pathlib import Path
from typing import TypedDict, Annotated

import tabula
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain_core.messages import SystemMessage
from langgraph.graph import StateGraph, START, END, add_messages
from langgraph.prebuilt import ToolNode, tools_condition

pdf_path = (
    "data/HS26-27_prov.Prüfungsplan_BSc_"
    "Examination Timetable_BSc_Students.pdf"
)

tables = tabula.read_pdf(
    pdf_path,
    pages="all",
    multiple_tables=False
)

Path("data").mkdir(exist_ok=True)

for i, table in enumerate(tables):
    table.to_csv(f"data/table_{i}.csv", index=False)

if not tables:
    raise ValueError("Keine Tabellen im PDF gefunden.")

MODULES = "\n\n".join(
    f"Tabelle {i}:\n{table.to_csv(index=False)}"
    for i, table in enumerate(tables)
)

load_dotenv()

llm = ChatOpenAI(
    model=os.getenv("MODEL"),
    base_url=os.getenv("BASE_URL"),
    api_key=os.getenv("API_KEY")
)

@tool
def module_lookup(search_term: str) -> str:
    """Sucht Prüfungsinformationen nach Studiengang,
    Schulklasse, Modul oder Prüfung.
    """
    lines = MODULES.splitlines()

    matches = [
        line for line in lines
        if search_term.lower() in line.lower()
    ]

    if not matches:
        return f"Keine Einträge für '{search_term}' gefunden."

    return "\n".join(matches[:100])


tools = [module_lookup]
llm_with_tools = llm.bind_tools(tools)

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


def get_answer(state: AgentState):
    system = SystemMessage(
        content=(
            "Du bist ein Prüfungsassistent der FHNW. "
            "Nutze module_lookup für Fragen zum Prüfungsplan. "
            "Erfinde keine Prüfungstermine. "
            "Bei Fragen nach der ersten Prüfung "
            "vergleiche die gefundenen Datumswerte."
            "Beantworte nur Fragen zum Prüfungsplan, weise darauf hin sollten andere Fragen gestellt werden."
        )
    )

    response = llm_with_tools.invoke(
        [system] + state["messages"]
    )

    return {"messages": [response]}


builder = StateGraph(AgentState)

builder.add_node("get_answer", get_answer)
builder.add_node("tools", ToolNode(tools))

builder.add_edge(START, "get_answer")

builder.add_conditional_edges(
    "get_answer",
    tools_condition
)

builder.add_edge("tools", "get_answer")

graph = builder.compile()

frage = "Welche Prüfungen finden für BAI TZ statt?"

result = graph.invoke({
    "messages": [("user", frage)]
})

print(result["messages"][-1].content)
