from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.deps import get_db, get_redis
from app.logging import setup_logging
from app.routes import auth, chat, contracts, documents


async def health_check(db: AsyncSession = Depends(get_db)):
    """Check that the app, the database and Redis are all working."""
    await db.execute(text("SELECT 1"))
    redis_client = get_redis()
    await redis_client.ping()
    return {"status": "ok"}


def create_app() -> FastAPI:
    """Build the FastAPI app and connect all routers."""
    setup_logging()

    app = FastAPI(title="Contract Intelligence API")

    # Allow the React app (running on another port) to call this API
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_api_route("/health", health_check, methods=["GET"])
    app.include_router(auth.router)
    app.include_router(contracts.router)
    app.include_router(documents.router)
    app.include_router(chat.router)

    return app


app = create_app()