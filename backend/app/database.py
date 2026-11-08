from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# One engine is shared by the whole app
engine = create_async_engine(settings.database_url)

# expire_on_commit=False keeps objects readable after we commit
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    """Parent class for all database tables."""