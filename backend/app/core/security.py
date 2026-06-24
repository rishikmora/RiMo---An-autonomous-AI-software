"""Authentication: password hashing and JWT access/refresh token handling.

Implements a rotation-based flow:
  * **Access token** - short-lived (minutes) JWT, stateless, carries type=access.
  * **Refresh token** - longer-lived opaque secret; only its SHA-256 hash is
    stored in Postgres so it can be revoked and rotated. Each refresh issues a
    new pair and invalidates the old refresh token (rotation), which bounds the
    damage of a leaked refresh token and enables real logout.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_session
from app.models import RefreshToken, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.api_v1_prefix}/auth/login")

ALGORITHM = "HS256"
# bcrypt operates on at most 72 bytes; longer inputs are silently truncated by
# the algorithm. We pre-hash with SHA-256 so the full password contributes and
# the 72-byte limit never rejects or quietly weakens a long passphrase.
_BCRYPT_ROUNDS = 12


def _prepare(password: str) -> bytes:
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    # base64 keeps it within bcrypt's byte budget while staying printable.
    import base64

    return base64.b64encode(digest)


# --- passwords --------------------------------------------------------------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prepare(password), bcrypt.gensalt(_BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_prepare(plain), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# --- access tokens (stateless JWT) ------------------------------------------
def create_access_token(subject: str | uuid.UUID) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(subject),
        "type": "access",
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
        "iat": now,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


# --- refresh tokens (opaque, hashed, revocable) -----------------------------
def _hash_refresh(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def issue_refresh_token(session: AsyncSession, user_id: uuid.UUID) -> str:
    """Mint a refresh token, store only its hash, and return the raw secret."""
    raw = secrets.token_urlsafe(48)
    record = RefreshToken(
        user_id=user_id,
        token_hash=_hash_refresh(raw),
        expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days),
    )
    session.add(record)
    await session.flush()
    return raw


async def rotate_refresh_token(session: AsyncSession, raw_token: str) -> tuple[User, str]:
    """Validate a refresh token, revoke it, and issue a fresh refresh token.

    Rotation: the presented token is single-use. Reuse of an already-rotated
    token fails (it's revoked), the standard refresh-token-reuse defense.
    """
    record = (
        await session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == _hash_refresh(raw_token))
        )
    ).scalar_one_or_none()

    invalid = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired refresh token")
    if record is None or record.revoked:
        raise invalid
    if record.expires_at < datetime.now(UTC):
        raise invalid

    user = await session.get(User, record.user_id)
    if user is None or not user.is_active:
        raise invalid

    record.revoked = True
    record.last_used_at = datetime.now(UTC)
    new_raw = await issue_refresh_token(session, user.id)
    return user, new_raw


async def revoke_all_refresh_tokens(session: AsyncSession, user_id: uuid.UUID) -> int:
    """Revoke every active refresh token for a user (logout-everywhere)."""
    rows = (
        await session.execute(
            select(RefreshToken).where(
                RefreshToken.user_id == user_id, RefreshToken.revoked.is_(False)
            )
        )
    ).scalars().all()
    for row in rows:
        row.revoked = True
    return len(rows)


async def revoke_refresh_token(session: AsyncSession, raw_token: str) -> bool:
    record = (
        await session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == _hash_refresh(raw_token))
        )
    ).scalar_one_or_none()
    if record and not record.revoked:
        record.revoked = True
        return True
    return False


# --- current-user dependency ------------------------------------------------
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        if payload.get("type") != "access":
            raise credentials_exc  # refresh tokens must not authenticate requests
        user_id = payload.get("sub")
        if user_id is None:
            raise credentials_exc
    except jwt.PyJWTError as exc:
        raise credentials_exc from exc

    user = (
        await session.execute(select(User).where(User.id == uuid.UUID(user_id)))
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        raise credentials_exc
    return user
