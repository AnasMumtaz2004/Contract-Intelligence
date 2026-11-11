import hashlib

from app.config import settings
from app.deps import get_redis

# Each limit counts the requests in a window of this length
WINDOW_SECONDS = 60


def find_rule(method: str, path: str):
    """Find the rate limit that applies to a request. Returns (name, limit per minute, by user) or None."""
    if method != "POST":
        return None

    # Login and register share one limit per computer address, which slows down password guessing
    if path == "/auth/login" or path == "/auth/register":
        return ("login", settings.rate_limit_login_per_minute, False)

    # Questions cost LLM calls, so they are limited per user
    if path.startswith("/chat/conversations/") and path.endswith("/ask"):
        return ("ask", settings.rate_limit_ask_per_minute, True)

    if path == "/documents/upload":
        return ("upload", settings.rate_limit_upload_per_minute, True)

    return None


def make_identity(client_ip: str, authorization: str, by_user: bool) -> str:
    """Decide who a request counts for: the user (from the login token), or the computer address."""
    if by_user and authorization != "":
        # The token itself is never stored. Only a short fingerprint of it is.
        return hashlib.sha256(authorization.encode("utf-8")).hexdigest()[:16]
    return client_ip


async def check_rate_limit(name: str, identity: str, limit: int) -> int:
    """Count one request. Returns 0 if it is allowed, or the number of seconds to wait if the limit is reached."""
    if limit <= 0:
        return 0

    key = "rl:" + name + ":" + identity

    # If Redis is down, the app keeps working without limits
    try:
        redis_client = get_redis()
        count = await redis_client.incr(key)
        if count == 1:
            await redis_client.expire(key, WINDOW_SECONDS)
        if count > limit:
            seconds_left = await redis_client.ttl(key)
            if seconds_left < 1:
                seconds_left = WINDOW_SECONDS
            return seconds_left
    except Exception:
        return 0

    return 0