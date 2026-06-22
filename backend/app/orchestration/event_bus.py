"""Redis-backed pub/sub event bus for real-time dashboard updates.

The orchestrator publishes activity events to a per-project channel; the API's
WebSocket/SSE endpoints subscribe and relay to connected clients.
"""
from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import redis.asyncio as aioredis

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _channel(project_id: uuid.UUID) -> str:
    return f"rimo:events:{project_id}"


class EventBus:
    """Thin wrapper over Redis pub/sub."""

    def __init__(self, url: str | None = None) -> None:
        self._redis = aioredis.from_url(url or str(settings.redis_url), decode_responses=True)

    async def publish(self, project_id: uuid.UUID, payload: dict[str, Any]) -> None:
        try:
            await self._redis.publish(_channel(project_id), json.dumps(payload, default=str))
        except Exception as exc:  # pub/sub failures must never break the workflow
            logger.warning("event_publish_failed", error=str(exc))

    async def subscribe(self, project_id: uuid.UUID) -> AsyncGenerator[dict[str, Any], None]:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(_channel(project_id))
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        yield json.loads(message["data"])
                    except json.JSONDecodeError:
                        continue
        finally:
            await pubsub.unsubscribe(_channel(project_id))
            await pubsub.aclose()

    async def close(self) -> None:
        await self._redis.aclose()


_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus
