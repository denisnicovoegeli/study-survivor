import operator, os
from typing import Literal
from typing_extensions import Annotated, TypedDict
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from pathlib import Path

load_dotenv()

if os.environ.get("LANGSMITH_API_KEY"):
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_PROJECT"] = "genai_swiss_cw5"
    print("Tracing läuft. Projekt:", os.environ["LANGSMITH_PROJECT"])
else:
    os.environ["LANGSMITH_TRACING"] = "false"
    print("Kein LANGSMITH_API_KEY gefunden — weiter ohne Tracing.")



LLM_MODEL = "gpt-5.6-luna"
LLM_BASE_URL = "https://litellm.engines.aisl.science/v1"

llm = ChatOpenAI(
    model=LLM_MODEL,
    base_url=LLM_BASE_URL,
    api_key=os.environ["LITELLM_API_KEY"],
    temperature=0,
)

SYSTEM_PROMPT = """Du bist ein Studienassistent für Studierende der FHNW und beantwortest Fragen zu ihren Prüfungsterminen.
Fakten: Schlage Prüfungstermine immer mit exam_lookup nach. Erfinde nichts, weder Daten noch Uhrzeiten, Räume oder Prüfungsformen. Liefert das Tool nichts, sag das offen und verweise auf den offiziellen Prüfungsplan der FHNW.
Fehlt eine Angabe (z. B. welches Modul), frage nach.
Antwortstil: Sprich die Person mit «du» an, antworte in der Sprache der Frage, höchstens vier Sätze. Nenne Datum, Uhrzeit und Ort, wenn vorhanden, und bei mehreren Terminen eine kurze Aufzählung nach Datum sortiert.
Kennzeichnung: Du bist ein Prototyp aus einem Studienprojekt, kein offizieller Dienst der FHNW. Termine können sich ändern, verbindlich ist der offizielle Prüfungsplan."""

CLASSIFY_PROMPT = """Entscheide, ob eine Frage zu einem Studienassistenten gehört, und bestimme ihr Thema.
Zuständig: Prüfungstermine, Prüfungszeiten und -orte, Anmeldefristen für Prüfungen, Fragen an den Assistenten.
Nicht zuständig: Inhalte und Lernstoff der Module, Noten, Stundenplan, Organisatorisches ausserhalb von Prüfungen und alles andere."""

EXAMS = {
    "managementorientierte betriebswirtschaftslehre": [
        {"datum": "06.01.2027", "wochentag": "Mittwoch",   "zeit": "08:00 - 20:00", "dauer_min": None, "form": "mündlich", "klasse": "VZ-26", "dozierende": "Hofstetter Charlotte; Köpfli Corinne"},
        {"datum": "07.01.2027", "wochentag": "Donnerstag", "zeit": "08:00 - 20:00", "dauer_min": None, "form": "mündlich", "klasse": "TZ-25", "dozierende": "Hofstetter Charlotte; Köpfli Corinne"},
        {"datum": "08.01.2027", "wochentag": "Freitag",    "zeit": "08:00 - 20:00", "dauer_min": None, "form": "mündlich", "klasse": "VZ-26", "dozierende": "Hofstetter Charlotte; Köpfli Corinne"},
        {"datum": "08.01.2027", "wochentag": "Freitag",    "zeit": "08:00 - 20:00", "dauer_min": None, "form": "mündlich", "klasse": "TZ-25", "dozierende": "Hofstetter Charlotte; Köpfli Corinne"},
    ],
    "deep learning": [
        {"datum": "09.01.2027", "wochentag": "Samstag", "zeit": "09:00 - 10:00", "dauer_min": 60, "form": "schriftlich", "klasse": "VZ + TZ ab 3", "dozierende": "Suter Yannick"},
    ],
    "generative ki & agentensysteme": [
        {"datum": "11.01.2027", "wochentag": "Montag",   "zeit": "08:15 - 21:00", "dauer_min": None, "form": "mündlich", "klasse": "VZ + TZ", "dozierende": "Martin Andreas; Schwander Sandro"},
        {"datum": "12.01.2027", "wochentag": "Dienstag", "zeit": "08:15 - 21:00", "dauer_min": None, "form": "mündlich", "klasse": "VZ + TZ", "dozierende": "Martin Andreas; Schwander Sandro"},
    ],
    "cyber security": [
        {"datum": "12.01.2027", "wochentag": "Dienstag", "zeit": "14:00 - 15:30", "dauer_min": 90, "form": "schriftlich", "klasse": "VZ + TZ", "dozierende": "Grieder Hermann; Moriggl Pascal"},
    ],
    "entrepreneurship": [
        {"datum": "13.01.2027", "wochentag": "Mittwoch", "zeit": "08:00 - 18:00", "dauer_min": None, "form": "mündlich", "klasse": "VZ + TZ", "dozierende": "Metuzale Kristine"},
    ],
    "einführung in die künstliche intelligenz": [
        {"datum": "13.01.2027", "wochentag": "Mittwoch", "zeit": "09:00 - 10:30", "dauer_min": 90, "form": "schriftlich", "klasse": "VZ-26", "dozierende": "Hinkelmann Knut; Renold Manuel; Bargas Javier"},
        {"datum": "13.01.2027", "wochentag": "Mittwoch", "zeit": "09:00 - 10:30", "dauer_min": 90, "form": "schriftlich", "klasse": "TZ-26", "dozierende": "Hinkelmann Knut; Renold Manuel; Bargas Javier"},
    ],
    "statistik & mathematik für maschinelles lernen": [
        {"datum": "15.01.2027", "wochentag": "Freitag", "zeit": "14:00 - 16:00", "dauer_min": 120, "form": "schriftlich", "klasse": "VZ-26", "dozierende": "Miller Barbara; Heimsch Thomas; Müller Roman"},
        {"datum": "15.01.2027", "wochentag": "Freitag", "zeit": "14:00 - 16:00", "dauer_min": 120, "form": "schriftlich", "klasse": "TZ-26", "dozierende": "Miller Barbara; Heimsch Thomas; Müller Roman"},
    ],
    "mensch-ki-interaktion und automation": [
        {"datum": "19.01.2027", "wochentag": "Dienstag", "zeit": "08:30 - 17:00", "dauer_min": None, "form": "mündlich", "klasse": "VZ + TZ", "dozierende": "Wäfler Toni; Zinsli Patrick; Sonderegger Andreas"},
        {"datum": "20.01.2027", "wochentag": "Mittwoch", "zeit": "08:30 - 17:00", "dauer_min": None, "form": "mündlich", "klasse": "VZ + TZ", "dozierende": "Wäfler Toni; Zinsli Patrick; Sonderegger Andreas"},
    ],
    "unternehmensfinanzierung": [
        {"datum": "19.01.2027", "wochentag": "Dienstag", "zeit": "11:00 - 12:00", "dauer_min": 60, "form": "schriftlich", "klasse": "VZ + TZ", "dozierende": "Graef Frank; Kröncke Tim"},
    ],
    "geschäftsprozess-management & -automation": [
        {"datum": "20.01.2027", "wochentag": "Mittwoch", "zeit": "09:00 - 10:30", "dauer_min": 90, "form": "schriftlich", "klasse": "VZ-26", "dozierende": "Spahic Maja; Kostic Milan; Yasar Selim; Felice Eliana"},
        {"datum": "20.01.2027", "wochentag": "Mittwoch", "zeit": "09:00 - 10:30", "dauer_min": 90, "form": "schriftlich", "klasse": "TZ-25", "dozierende": "Spahic Maja; Kostic Milan; Yasar Selim; Felice Eliana"},
    ],
    "wissensmanagement und organisationales lernen": [
        {"datum": "23.01.2027", "wochentag": "Samstag", "zeit": "11:30 - 12:30", "dauer_min": 60, "form": "schriftlich", "klasse": "VZ + TZ", "dozierende": "Witschel Hans Friedrich"},
    ],
}


@tool
def exam_lookup(modul: str) -> str:
    """Schlägt Datum, Uhrzeit und Ort einer Prüfung nach. Gibt eine kurze Aufzählung zurück, wenn es mehrere Termine gibt.

    Liefert alle Termine des Moduls (z.B. getrennt für VZ und TZ).
    Mögliche Module: siehe Schlüssel der Prüfungstabelle.
    """
    q = modul.strip().lower()
    matches = [k for k in EXAMS if q in k or k in q]
    if not matches:
        return f"Keine Prüfungstermine gefunden für '{modul}'. Bitte prüfe die Schreibweise oder den offiziellen Prüfungsplan der FHNW."
    lines = []
    for k in matches:
        for t in EXAMS[k]:
            dauer = f"{t['dauer_min']} min" if t["dauer_min"] else "Dauer unbekannt"
            lines.append(f"{k.title()}: {t['datum']} ({t['wochentag']}), {t['zeit']}, {dauer}, {t['form']}, Klasse: {t['klasse']}, Dozierende: {t['dozierende']}")
    return "\n".join(lines)


tools = [exam_lookup]
tools_by_name = {t.name: t for t in tools}
llm_with_tools = llm.bind_tools(tools)


class Classification(BaseModel):
    reason: str = Field(description="Begründung in einem Satz")
    in_scope: bool = Field(description="True, wenn die Frage in den Zuständigkeitsbereich fällt")
    category: Literal["exam_date", "exam_info", "other"] = Field(description="Thema der Frage")


class AgentResponse(BaseModel):
    answer: str = Field(description="Antwort an die Studentin oder den Studenten")
    exams: str | None = Field(description="Modul, um den es geht, falls eines genannt wird")
    needs_human: bool = Field(description="True bei Beschwerden, Fragen zur Prüfung, Verhinderung")


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]
    in_scope: bool
    category: str
    tools_used: Annotated[list[str], operator.add]
    response: AgentResponse


classifier = llm.with_structured_output(Classification, method="json_schema")
responder = llm.with_structured_output(AgentResponse, method="json_schema")


def classify(state: AgentState):
    """Prüft, ob die letzte Frage zum Zuständigkeitsbereich gehört, und bestimmt ihr Thema."""
    result = classifier.invoke([SystemMessage(content=CLASSIFY_PROMPT), state["messages"][-1]])
    return {"in_scope": result.in_scope, "category": result.category}


def reject(state: AgentState):
    text = "Dabei kann ich leider nicht helfen. Ich beantworte nur Fragen zun den BAI Prüfungen an der FHNW."
    return {"messages": [AIMessage(content=text)],
            "response": AgentResponse(answer=text, exams=None, needs_human=False)}


def answer(state: AgentState):
    return {"messages": [llm_with_tools.invoke([SystemMessage(content=SYSTEM_PROMPT)] + state["messages"])]}


def call_tools(state: AgentState):
    tool_calls = state["messages"][-1].tool_calls
    results = []
    for tool_call in tool_calls:
        result = tools_by_name[tool_call["name"]].invoke(tool_call["args"])
        results.append(ToolMessage(content=str(result), tool_call_id=tool_call["id"]))
    return {"messages": results, "tools_used": [c["name"] for c in tool_calls]}


def respond(state: AgentState):
    messages = ([SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
                + [HumanMessage(content="Übernimm deine letzte Antwort unverändert in das vorgegebene Format.")])
    return {"response": responder.invoke(messages)}


def route_after_classify(state: AgentState):
    return "answer" if state["in_scope"] else "reject"


def route_after_answer(state: AgentState):
    return "tools" if state["messages"][-1].tool_calls else "respond"


def build_graph():
    builder = StateGraph(AgentState)
    builder.add_node("classify", classify)
    builder.add_node("reject", reject)
    builder.add_node("answer", answer)
    builder.add_node("tools", call_tools)
    builder.add_node("respond", respond)
    builder.add_edge(START, "classify")
    builder.add_conditional_edges("classify", route_after_classify, ["answer", "reject"])
    builder.add_edge("reject", END)
    builder.add_conditional_edges("answer", route_after_answer, ["tools", "respond"])
    builder.add_edge("tools", "answer")
    builder.add_edge("respond", END)
    return builder.compile()


graph = build_graph()


def ask(question):
    return graph.invoke({"messages": [HumanMessage(content=question)]})["response"].answer

#print(ask("Wann ist die Prüfung für Deep Learning?"))

#png = graph.get_graph().draw_mermaid_png()
#Path("graph.png").write_bytes(png)
#print("Graph gespeichert in graph.png")

user_input = input("Stelle eine Frage zu den BAI Prüfungen: ")
response = ask(user_input)
print("Antwort:", response)