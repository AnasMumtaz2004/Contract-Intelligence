import os

from app.config import settings


def setup_tracing() -> None:
    """Turn on LangSmith tracing when it is enabled and a key is set."""
    if not settings.langsmith_tracing or settings.langsmith_api_key == "":
        return

    # LangChain reads these from the environment, not from our settings.
    # Both the new and the old names are set, so any version understands them.
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project