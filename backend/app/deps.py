from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
import redis.asyncio as redis_asyncio
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import User

# One Redis client is shared by the whole app
redis_client = redis_asyncio.from_url(settings.redis_url, decode_responses=True)

# Reads the "Authorization: Bearer <token>" header
bearer_scheme = HTTPBearer()


async def get_db():
    """Give each request its own database session."""
    async with AsyncSessionLocal() as session:
        yield session


def get_redis():
    """Return the shared Redis client."""
    return redis_client


def hash_password(password: str) -> str:
    """Turn a plain password into a safe hash for storing."""
    password_bytes = password.encode("utf-8")
    hashed_bytes = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
    return hashed_bytes.decode("utf-8")


def verify_password(password: str, hashed_password: str) -> bool:
    """Check a plain password against the stored hash."""
    password_bytes = password.encode("utf-8")
    hashed_bytes = hashed_password.encode("utf-8")
    return bcrypt.checkpw(password_bytes, hashed_bytes)


def create_access_token(user_id: int) -> str:
    """Create a login token that expires after a while."""
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_minutes)
    # The "sub" field must be a string
    payload = {"sub": str(user_id), "exp": expires_at}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Find the logged-in user from the token, or return a 401 error."""
    token = credentials.credentials

    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = int(payload["sub"])
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    return user