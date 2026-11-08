from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import create_access_token, get_db, hash_password, verify_password
from app.models import User
from app.schemas import LoginRequest, RegisterRequest, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut)
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Create a new user account."""
    # Lowercase the email so "A@x.com" and "a@x.com" are the same user
    email = data.email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Please enter a valid email")

    result = await db.execute(select(User).where(User.email == email))
    existing_user = result.scalar_one_or_none()
    if existing_user is not None:
        raise HTTPException(status_code=400, detail="Email is already registered")

    user = User(email=email, hashed_password=hash_password(data.password))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Check the email and password and return a login token."""
    email = data.email.strip().lower()

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    # Same message for both cases so we do not reveal which emails exist
    if user is None or not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Wrong email or password")

    token = create_access_token(user.id)
    return TokenResponse(access_token=token)