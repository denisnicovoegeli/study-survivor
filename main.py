import operator, os, subprocess
from typing import Literal
from typing_extensions import Annotated, TypedDict
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import ToolNode
from langchain.tools import ToolRuntime
from pathlib import Path
from google.cloud import texttospeech
from langchain_google_community import TextToSpeechTool

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
Wenn die Person möchte, dass etwas vorgelesen wird, rufe speak mit dem Antworttext auf.
Antworte danach kurz, dass du es vorgelesen hast.
Kennzeichnung: Du bist ein Prototyp aus einem Studienprojekt, kein offizieller Dienst der FHNW. Termine können sich ändern, verbindlich ist der offizielle Prüfungsplan."""

CLASSIFY_PROMPT = """Entscheide, ob eine Frage zu einem Studienassistenten gehört, und bestimme ihr Thema.
Zuständig: Prüfungstermine, Prüfungszeiten und -orte, Anmeldefristen für Prüfungen, Fragen an den Assistenten selbst, z.B. "Was kannst du?", "Wobei kannst du mir helfen?".
Nicht zuständig: Inhalte und Lernstoff der Module, Noten, Stundenplan, Organisatorisches ausserhalb von Prüfungen und alles andere.
- Bitten, eine Antwort vorzulesen, z. B. «Lies mir das vor»"""

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

DATE_KEYS = ["datum", "wochentag", "zeit", "klasse"]

@tool
def exam_lookup(modul: str, runtime: ToolRuntime) -> str:
    """Schlägt die Prüfungstermine eines BAI-Moduls nach.

    Liefert Datum, Wochentag, Zeit, Dauer, Prüfungsform, Klasse (VZ/TZ) und Dozierende.
    Bei mehreren Terminen (z. B. VZ und TZ) kommt eine Zeile pro Termin.
    Der Plan enthält keinen Prüfungsort.
    Mögliche Module: Managementorientierte Betriebswirtschaftslehre, Deep Learning,
    Generative KI & Agentensysteme, Cyber Security, Entrepreneurship,
    Einführung in die Künstliche Intelligenz, Statistik & Mathematik für maschinelles Lernen,
    Mensch-KI-Interaktion und Automation, Unternehmensfinanzierung,
    Geschäftsprozess-Management & -Automation, Wissensmanagement und organisationales Lernen.
    """
    q = modul.strip().lower()
    matches = [k for k in EXAMS if q in k or k in q]
    if not matches:
        return f"Keine Prüfungstermine gefunden für '{modul}'. Bitte prüfe die Schreibweise oder den offiziellen Prüfungsplan der FHNW."
    lines = []
    for k in matches:
        for t in EXAMS[k]:
            if runtime.state["category"] == "exam_date":
                t = {f: v for f, v in t.items() if f in DATE_KEYS}
            lines.append(f"{k.title()}: " + ", ".join(f"{f}: {v}" for f, v in t.items() if v is not None))
    return "\n".join(lines)

print("Das Modell sieht nur:", list(exam_lookup.tool_call_schema.model_json_schema()["properties"]))

@tool
def speak(text: str) -> str:
    """Liest einen Text auf Deutsch vor und spielt ihn ab.

    Nur verwenden, wenn die Person ausdrücklich möchte, dass etwas vorgelesen wird.
    Übergib den vollständigen Text, der vorgelesen werden soll.
    """
    tts = TextToSpeechTool.model_construct() 
    tts._client = texttospeech.TextToSpeechClient(
        client_options={"api_key": os.environ["GOOGLE_TTS_API_KEY"]}
    )
    path = tts._run(input_text=text.replace("*", ""), language_code="de-DE")
    try:
        subprocess.run(["afplay", path])
    finally:
        os.remove(path)
    return "Der Text wurde vorgelesen."


tools = [exam_lookup, speak]
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
    result = classifier.invoke([SystemMessage(content=CLASSIFY_PROMPT)] + state["messages"][-6:])
    return {"in_scope": result.in_scope, "category": result.category}


def reject(state: AgentState):
    text = "Dabei kann ich leider nicht helfen. Ich beantworte nur Fragen zun den BAI Prüfungen an der FHNW."
    return {"messages": [AIMessage(content=text)],
            "response": AgentResponse(answer=text, exams=None, needs_human=False)}


def answer(state: AgentState):
    return {"messages": [llm_with_tools.invoke([SystemMessage(content=SYSTEM_PROMPT)] + state["messages"])]}

tool_node = ToolNode(tools)


def call_tools(state: AgentState):
    """Führt die angeforderten Werkzeuge mit dem fertigen ToolNode aus."""
    result = tool_node.invoke(state)
    tool_names = [c["name"] for c in state["messages"][-1].tool_calls]
    return {"messages": result["messages"], "tools_used": tool_names}



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
    return builder.compile(checkpointer=InMemorySaver())


graph = build_graph()


def ask(question, thread_id="default"):
    config = {"configurable": {"thread_id": thread_id}}
    result = graph.invoke({"messages": [HumanMessage(content=question)]}, config)
    return result["response"].answer

#print(ask("Wann ist die Prüfung für Deep Learning?"))

#png = graph.get_graph().draw_mermaid_png()
#Path("graph.png").write_bytes(png)
#print("Graph gespeichert in graph.png")

#def chat():
    thread_id = "silian"
    print("Willkommen beim Studienassistenten. Stelle deine Frage zu den BAI Prüfungen an der FHNW. Beende das Gespräch mit 'exit'.")
    while True:
        try:
            user_input = input("Du: ")
            if user_input.lower() == "exit":
                print("Auf Wiedersehen!")
                break
            answer = ask(user_input, thread_id=thread_id)
            print("Assistent:", answer)
        except Exception as e:
            print("Fehler:", e)

#if __name__ == "__main__":
    #chat()


#result = graph.invoke({"messages": [HumanMessage(content="wann findet die Prüfung in Deep Learning statt?")]}, {"configurable": {"thread_id": "test"}})
#print("tools_used:", result["tools_used"])
#print(result["response"].answer)

#print(speak.invoke({"text": "Hallo, ich bin dein Studienassistent. Die Prüfung in Cyber Security findet am zwölften Januar statt."}))

print(ask("Wann findet die erste Prüfung statt?", thread_id="t1"))
print(ask("Lies mir das bitte vor.", thread_id="t1"))