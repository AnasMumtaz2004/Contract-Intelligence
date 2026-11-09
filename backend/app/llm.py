from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq

from app.config import settings

# How long to wait for one answer, and how many times the library itself retries
REQUEST_TIMEOUT_SECONDS = 45
MAX_RETRIES = 1

# One limiter per provider, shared by all calls, so the whole app stays under the limit
_rate_limiters = {}


def get_rate_limiter(provider: str) -> InMemoryRateLimiter:
    """Return the shared rate limiter of a provider. A call waits for its turn instead of failing."""
    if provider not in _rate_limiters:
        if provider == "gemini":
            requests_per_minute = settings.gemini_requests_per_minute
        else:
            requests_per_minute = settings.groq_requests_per_minute

        _rate_limiters[provider] = InMemoryRateLimiter(
            requests_per_second=requests_per_minute / 60,
            check_every_n_seconds=0.1,
            max_bucket_size=1,
        )
    return _rate_limiters[provider]


def build_gemini() -> ChatGoogleGenerativeAI:
    """Create the Gemini chat model."""
    return ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        api_key=settings.google_api_key,
        temperature=0,
        timeout=REQUEST_TIMEOUT_SECONDS,
        max_retries=MAX_RETRIES,
        rate_limiter=get_rate_limiter("gemini"),
    )


def build_groq() -> ChatGroq:
    """Create the Groq chat model."""
    return ChatGroq(
        model=settings.groq_model,
        api_key=settings.groq_api_key,
        temperature=0,
        timeout=REQUEST_TIMEOUT_SECONDS,
        max_retries=MAX_RETRIES,
        rate_limiter=get_rate_limiter("groq"),
    )


def get_llm(role: str):
    """Return the chat model for a role. If it fails, the other provider is tried, and then the call is retried."""
    # "fast" roles are cheap steps like planning and grading. All other roles are "smart".
    if role == "fast":
        first_provider = settings.fast_provider
    else:
        first_provider = settings.smart_provider

    if first_provider == "groq":
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

    chain = models[0]
    if len(models) > 1:
        # with_fallbacks tries the backup when the first model raises an error (for example a rate limit)
        chain = chain.with_fallbacks(models[1:])

    # If both fail, wait a little (longer each time) and try the whole chain again
    return chain.with_retry(stop_after_attempt=settings.llm_max_attempts, wait_exponential_jitter=True)


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