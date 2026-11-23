"""Zugang zum LiteLLM-Proxy der FHNW (OpenAI-kompatibel)."""
import os
from pathlib import Path

from dotenv import load_dotenv

from study_agent.config import REPO_DIR

PROXY = os.environ.get("LITELLM_BASE_URL", "https://litellm.engines.aisl.science/v1")
_KEY_VARS = ("LITELLM_API_KEY", "AISL_API_KEY")

# Modelle (SW4: Modellwahl). Hauptmodell fuer Chat und Extraktion, zweites Modell eines
# anderen Anbieters fuer die Pruefung im Graph verarbeiten (Vier-Augen-Prinzip, SW8).
MAIN_MODEL = os.environ.get("STUDY_MAIN_MODEL", "gpt-5.6-luna")
CHECK_MODEL = os.environ.get("STUDY_CHECK_MODEL", "azure_ai/claude-haiku-5-5")
VISION_MODEL = os.environ.get("STUDY_VISION_MODEL", "gpt-5.6-luna")
EMBED_MODEL = os.environ.get("STUDY_EMBED_MODEL", "andreasmartin/apertus-v1.1-swiss-embed-0.4b")

# .env im Repo (LITELLM_API_KEY, LANGSMITH_*), danach ~/.config/aisl.env als Rueckfall
load_dotenv(REPO_DIR / ".env")


def _key_files() -> list[Path]:
    return [REPO_DIR / ".env", Path.home() / ".config/aisl.env"]


def api_key() -> str:
    for var in _KEY_VARS:
        if key := os.environ.get(var):
            return key
    for path in _key_files():
        if not path.is_file():
            continue
        for line in path.read_text().splitlines():
            name, _, value = line.partition("=")
            if name.strip() in _KEY_VARS and value.strip():
                return value.strip().strip('"')
    raise RuntimeError("LiteLLM-Key fehlt: LITELLM_API_KEY in .env, Umgebung oder ~/.config/aisl.env")


def chat_model(model: str = MAIN_MODEL, **kw):
    from langchain_openai import ChatOpenAI

    # Keine temperature setzen: einige Modelle akzeptieren ueber den Proxy nur den Standardwert.
    kw = {"timeout": 180, "max_retries": 2, **kw}
    return ChatOpenAI(model=model, base_url=PROXY, api_key=api_key(), **kw)


def embeddings(model: str = EMBED_MODEL):
    from langchain_openai import OpenAIEmbeddings

    # check_embedding_ctx_length=False: kein tiktoken-Tokenisieren, der Proxy bekommt Klartext
    return OpenAIEmbeddings(model=model, base_url=PROXY, api_key=api_key(), check_embedding_ctx_length=False)
