from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq

from app.config import settings


def build_gemini() -> ChatGoogleGenerativeAI:
    """Create the Gemini chat model."""
    return ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        api_key=settings.google_api_key,
        temperature=0,
    )


def build_groq() -> ChatGroq:
    """Create the Groq chat model."""
    return ChatGroq(
        model=settings.groq_model,
        api_key=settings.groq_api_key,
        temperature=0,
    )


def get_llm(role: str):
    """Return the chat model for a role. If it fails, the other provider is tried."""
    # "fast" roles try Groq first. All other roles try Gemini first.
    if role == "fast":
        provider_order = ["groq", "gemini"]
    else:
        provider_order = ["gemini", "groq"]

    models = []
    for provider in provider_order:
        if provider == "gemini" and settings.google_api_key != "":
            models.append(build_gemini())
        if provider == "groq" and settings.groq_api_key != "":
            models.append(build_groq())

    if len(models) == 0:
        raise ValueError("Set GOOGLE_API_KEY or GROQ_API_KEY in your .env file.")

    first_model = models[0]
    backup_models = models[1:]
    if len(backup_models) == 0:
        return first_model

    # with_fallbacks tries the backups when the first model raises an error (for example a rate limit)
    return first_model.with_fallbacks(backup_models)


def get_text(response) -> str:
    """Get the plain text from a model response."""
    content = response.content
    if isinstance(content, str):
        return content

    # Some models return a list of content blocks instead of a string
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "".join(parts)


async def ask_llm(role: str, system_prompt: str, user_prompt: str) -> str:
    """Send a system prompt and a user prompt to the model and return its text answer."""
    llm = get_llm(role)
    messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    response = await llm.ainvoke(messages)
    return get_text(response)