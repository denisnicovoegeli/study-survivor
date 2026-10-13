import os
from pathlib import Path
from typing import TypedDict, Annotated

import pandas as pd
import tabula
from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain_core.messages import SystemMessage
from langgraph.graph import StateGraph, START, add_messages
from langgraph.prebuilt import ToolNode, tools_condition

pdf_path = (
    "data/HS26-27_prov.Prüfungsplan_BSc_Examination Timetable_BSc_Students.pdf"
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

df = pd.concat(tables, ignore_index=True)

df.columns = [
    " ".join(str(col).split())
    for col in df.columns
]

df = df.rename(columns={
    "Tag Datum": "datum",
    "Zeit Time": "uhrzeit",
    "Dauer Min. Duration min.": "dauer_min",
    "Modul bzw. Kurs Module resp. Course": "modul",
    "Verantwortliche Dozierende Responsible Lecturers": "dozierende",
    "Studiengang Study programme": "studiengang",
    "Modell/ Klasse Modell/ Class": "klasse"
})

required_columns = [
    "datum", "uhrzeit", "dauer_min",
    "modul", "dozierende", "studiengang", "klasse"
]

missing = set(required_columns) - set(df.columns)

if missing:
    raise ValueError(f"Fehlende Spalten: {missing}")

df = df.fillna("")

df["datum_parsed"] = pd.to_datetime(
    df["datum"],
    format="%d.%m.%Y",
    errors="coerce"
)


class ExamSearchInput(BaseModel):
    studiengang: str | None = Field(
        default=None,
        description="Studiengang, z.B. BAI"
    )
    klasse: str | None = Field(
        default=None,
        description="Studienmodell oder Klasse, z.B. TZ"
    )
    modul: str | None = Field(
        default=None,
        description="Modulname"
    )
    nur_naechste: bool = Field(
        default=False,
        description="Nur die zeitlich erste Prüfung zurückgeben"
    )


@tool(args_schema=ExamSearchInput)
def module_lookup(
        studiengang: str | None = None,
        klasse: str | None = None,
        modul: str | None = None,
        nur_naechste: bool = False
) -> dict:
    """Sucht Prüfungen nach Studiengang, Klasse und Modul.

    Gibt strukturierte Prüfungsinformationen zurück,
    einschliesslich Datum, Zeit, Dauer und Dozierenden.
    """

    modules = df.copy()

    filters = {
        "studiengang": studiengang,
        "klasse": klasse,
        "modul": modul
    }

    for column, value in filters.items():
        if value:
            modules = modules[
                modules[column].astype(str).str.contains(
                    value.strip(),
                    case=False,
                    regex=False,
                    na=False
                )
            ]

    modules = modules.sort_values(
        ["datum_parsed", "uhrzeit"],
        na_position="last"
    )

    if nur_naechste:
        modules = modules.dropna(
            subset=["datum_parsed"]
        ).head(1)

    records = modules.drop(
        columns=["datum_parsed"]
    ).to_dict(orient="records")

    return {
        "anzahl": len(records),
        "pruefungen": records
    }


llm = ChatOpenAI(
    model=os.getenv("MODEL"),
    base_url=os.getenv("BASE_URL"),
    api_key=os.getenv("API_KEY")
)

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

builder.add_node("answer", get_answer)
builder.add_node("tools", ToolNode(tools))

builder.add_edge(START, "answer")

builder.add_conditional_edges(
    "answer",
    tools_condition
)

builder.add_edge("tools", "answer")

graph = builder.compile()

frage = "Welche Prüfungen finden für BAI TZ statt?"

result = graph.invoke({
    "messages": [("user", frage)]
})

print(result["messages"][-1].content)
