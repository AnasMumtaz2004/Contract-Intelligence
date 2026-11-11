import asyncio
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.deps import get_db, get_redis
from app.embeddings import get_model
from app.errors import add_error_handlers
from app.logging import setup_logging
from app.middleware import RequestMiddleware
from app.retrieval.rerank import get_reranker
from app.routes import auth, chat, contracts, documents, memory
from app.tracing import setup_tracing

# Secret keys that are only examples. A token that is signed with one of them can be forged by anyone.
UNSAFE_SECRETS = ["change-this-to-a-long-random-string", "secret", "changeme"]
MIN_SECRET_LENGTH = 12


def check_settings() -> None:
    """Refuse to start with a weak secret key."""
    if settings.secret_key in UNSAFE_SECRETS or len(settings.secret_key) < MIN_SECRET_LENGTH:
        raise RuntimeError(
            "SECRET_KEY is missing or too weak. Create one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load the embedding and reranking models when the server starts, so the first question is not slow."""
    await asyncio.to_thread(get_model)
    await asyncio.to_thread(get_reranker)
    yield


async def health_check(db: AsyncSession = Depends(get_db)):
    """Check that the app, the database and Redis are all working."""
    await db.execute(text("SELECT 1"))
    redis_client = get_redis()
    await redis_client.ping()
    return {"status": "ok"}


def create_app() -> FastAPI:
    """Build the FastAPI app and connect all routers."""
    check_settings()
    setup_logging()
    setup_tracing()

    app = FastAPI(title="Contract Intelligence API", lifespan=lifespan)

    add_error_handlers(app)

    # The last middleware that is added is the outermost one. CORS must be outside ours,
    # so that the browser can also read our 413 and 429 answers.
    app.add_middleware(RequestMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )

    app.add_api_route("/health", health_check, methods=["GET"])
    app.include_router(auth.router)
    app.include_router(contracts.router)
    app.include_router(documents.router)
    app.include_router(chat.router)
    app.include_router(memory.router)

    return app


app = create_app()