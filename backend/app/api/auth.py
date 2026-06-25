"""Authentication routes: register, login, refresh, logout, me.

Login and register are rate-limited per IP (Redis-backed) to blunt brute-force
and credential-stuffing. Login returns an access+refresh token pair; the
refresh token is rotated on every use and can be revoked (logout).
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.ratelimit import limiter
from app.core.security import (
    create_access_token,
    get_current_user,
    hash_password,
    issue_refresh_token,
    revoke_all_refresh_tokens,
    revoke_refresh_token,
    rotate_refresh_token,
    verify_password,
)
from app.db.session import get_session
from app.models import User
from app.schemas import RefreshRequest, TokenPair, UserCreate, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_pair(access: str, refresh: str) -> TokenPair:
    return TokenPair(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(f"{settings.rate_limit_register_per_minute}/minute")
async def register(
    request: Request,
    payload: UserCreate,
    session: AsyncSession = Depends(get_session),
) -> User:
    existing = (
        await session.execute(select(User).where(User.email == payload.email))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(
        email=payload.email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
    )
    session.add(user)
    await session.flush()
    return user


@router.post("/login", response_model=TokenPair)
@limiter.limit(f"{settings.rate_limit_login_per_minute}/minute")
async def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_session),
) -> TokenPair:
    user = (
        await session.execute(select(User).where(User.email == form.username))
    ).scalar_one_or_none()
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    access = create_access_token(user.id)
    refresh = await issue_refresh_token(session, user.id)
    return _token_pair(access, refresh)


@router.post("/refresh", response_model=TokenPair)
@limiter.limit("30/minute")
async def refresh(
    request: Request,
    payload: RefreshRequest,
    session: AsyncSession = Depends(get_session),
) -> TokenPair:
    """Exchange a valid refresh token for a new pair (refresh is rotated)."""
    user, new_refresh = await rotate_refresh_token(session, payload.refresh_token)
    access = create_access_token(user.id)
    return _token_pair(access, new_refresh)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    payload: RefreshRequest,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Revoke the presented refresh token (single-session logout)."""
    await revoke_refresh_token(session, payload.refresh_token)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Revoke every refresh token for the current user (logout everywhere)."""
    await revoke_all_refresh_tokens(session, user.id)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> User:
    return user
