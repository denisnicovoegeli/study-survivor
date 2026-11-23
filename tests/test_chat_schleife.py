"""Schleifenschutz im Graphen `chat`: ein Modell, das immer weiter sucht, muss trotzdem antworten."""
import asyncio

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

from study_agent.agent import chat


@tool
def suchen(frage: str) -> str:
    """Sucht im Kursmaterial."""
    return "Nichts zu Gruppe L gefunden."


class Stur:
    """Fake-Modell: mit Tools ruft es immer `suchen` auf, ohne Tools antwortet es."""

    def __init__(self):
        self.aufrufe = 0
        self.ohne_tools = 0

    def bind_tools(self, tools):
        modell = self

        class Gebunden:
            async def ainvoke(self, msgs):
                modell.aufrufe += 1
                return AIMessage("", tool_calls=[{"name": "suchen", "args": {"frage": "Gruppe L"},
                                                  "id": f"c{modell.aufrufe}"}])
        return Gebunden()

    def with_structured_output(self, schema, **kw):
        class Struktur:
            async def ainvoke(self, msgs):
                if schema is chat.Classification:
                    return schema(reason="Studium", in_scope=True, category="termine")
                return schema(answer="x", quellen=[], ergaenzung=False)
        return Struktur()

    async def ainvoke(self, msgs):
        self.ohne_tools += 1
        return AIMessage("Die Einteilung steht nicht im Kursmaterial.")


def test_chat_bricht_tool_schleife_ab(monkeypatch):
    stur = Stur()
    monkeypatch.setattr(chat, "chat_model", lambda model: stur)
    graph = chat.build_chat_graph([suchen])
    state = asyncio.run(graph.ainvoke({"messages": [HumanMessage("Wann präsentiert Gruppe L?")]}))
    assert stur.aufrufe == chat.MAX_TOOL_ROUNDS and stur.ohne_tools == 1
    assert state["response"]["answer"] == "Die Einteilung steht nicht im Kursmaterial."
    assert state["tools_used"] == ["suchen"]


def test_tool_runden_zaehlt_nur_die_laufende_frage():
    alt = [HumanMessage("a"), AIMessage("", tool_calls=[{"name": "t", "args": {}, "id": "1"}])]
    neu = [HumanMessage("b"), AIMessage("", tool_calls=[{"name": "t", "args": {}, "id": "2"}]), AIMessage("fertig")]
    assert chat.tool_runden(alt + neu) == 1


def test_verlauf_behaelt_laufende_frage_auch_bei_grossen_tool_ergebnissen():
    from langchain_core.messages import ToolMessage
    alt = [HumanMessage("alte Frage " + "x" * 40000), AIMessage("alte Antwort")]
    turn = [HumanMessage("Wann präsentiert Gruppe L?"),
            AIMessage("", tool_calls=[{"name": "datei_lesen", "args": {}, "id": "1"}]),
            ToolMessage("y" * 50000, tool_call_id="1", name="datei_lesen")]
    v = chat.verlauf_fuer_answer(alt + turn)
    assert v[0].content == "Wann präsentiert Gruppe L?"  # alte, zu grosse Runde fällt weg, die laufende nie
    assert len(v) == 3 and len(v[-1].content) < 13000 and v[-1].content.endswith("[… gekürzt]")


def test_verarbeiten_fuehrt_suchindex_nach(tmp_path):
    import sqlite3

    from study_agent.agent.verarbeiten import suchindex_nachfuehren
    from study_agent.config import Settings

    s = Settings(data_dir=tmp_path / "m", project_dir=tmp_path / "p")
    k = s.knowledge_dir / "GenKI" / "Folien"
    k.mkdir(parents=True)
    (k / "SW9.pdf.md").write_text("# SW9\n\n## Seite 44: Präsentationsplan\nAnwesenheit pro Block\n")
    suchindex_nachfuehren(s, "GenKI", dense=lambda *a, **kw: {"neu": 0})
    (k / "SW9.pdf.folien.md").write_text("# SW9\n\n## Folie 44 · Präsentationsplan\n| 16:30 | 16:40 | L |\n")

    def kaputt(*a, **kw):
        raise ConnectionError("offline")

    text = suchindex_nachfuehren(s, "GenKI", dense=kaputt)
    con = sqlite3.connect(s.state_dir / "suche.db")
    assert con.execute("SELECT quelle FROM meta").fetchall() == [("folien",)]
    assert "16:40" in con.execute("SELECT text FROM suche").fetchone()[0]
    assert text == "suchindex: 1 neu · semantisch: später (ConnectionError)"
