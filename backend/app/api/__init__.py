"""API router aggregation.

Combines every feature router under the versioned prefix so the application
factory only has to include a single object.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.api import auth, events, projects, resources
from app.core.config import settings

api_router = APIRouter(prefix=settings.api_v1_prefix)
api_router.include_router(auth.router)
api_router.include_router(projects.router)
api_router.include_router(resources.router)
api_router.include_router(events.router)

__all__ = ["api_router"]
