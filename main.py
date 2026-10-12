import os
from dotenv import load_dotenv

from typing import TypedDict, Annotated
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END, add_messages

load_dotenv()

MODEL = os.getenv("MODEL")
BASE_URL = os.getenv("BASE_URL")
API_KEY = os.getenv("API_KEY")


llm = ChatOpenAI(model=MODEL, base_url=BASE_URL, api_key=API_KEY)

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


def antworten(state: AgentState):
    antwort = llm.invoke(state["messages"])
    return {"messages": [antwort]}


builder = StateGraph(AgentState)
builder.add_node("antworten", antworten)
builder.add_edge(START, "antworten")
builder.add_edge("antworten", END)
graph = builder.compile()

frage = "Was ist die Hauptstadt von der Schweiz"
result = graph.invoke({"messages": [("user", frage)]})
print(result)

