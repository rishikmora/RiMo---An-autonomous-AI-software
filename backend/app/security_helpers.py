"""Reusable authorization helpers shared across API routers.

Centralises two concerns that several routes need:

* resolving a :class:`User` from a raw JWT string (used by the SSE endpoint,
  where ``EventSource`` cannot send an ``Authorization`` header), and
* loading a project while enforcing that the caller owns it.

Keeping these here avoids duplicating ownership checks (and the subtle bugs
that come from divergent copies) across modules.
"""
from __future__ import annotations

import uuid

import jwt
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import ALGORITHM
from app.models import Project, User


async def user_from_token(token: str | None, session: AsyncSession) -> User:
    """Validate a JWT string and return the active user, or raise 401."""
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exc
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
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


async def resolve_project_for_user(
    project_id: uuid.UUID, user: User, session: AsyncSession
) -> Project:
    """Return the project iff it exists and is owned by ``user`` (else 404)."""
    project = await session.get(Project, project_id)
    if project is None or project.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return project
