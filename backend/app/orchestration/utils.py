"""Shared helpers for the orchestration layer."""
from __future__ import annotations

import json
import re
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import ActivityEvent
from app.models.enums import AgentRole

logger = get_logger(__name__)

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def parse_json_output(text: str) -> dict[str, Any] | None:
    """Best-effort extraction of a JSON object from model output.

    Agents are instructed to emit pure JSON, but models occasionally wrap it in
    prose or fences. This recovers the object robustly.
    """
    if not text:
        return None
    candidate = text.strip()
    # Strip markdown fences if present.
    candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.MULTILINE).strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    match = _JSON_BLOCK.search(candidate)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            logger.warning("json_parse_failed", preview=candidate[:200])
    return None


class EventEmitter:
    """Persists ActivityEvents and publishes them for real-time streaming."""

    def __init__(self, session: AsyncSession, project_id: uuid.UUID, publisher: Any | None = None) -> None:
        self._session = session
        self._project_id = project_id
        self._publisher = publisher

    async def emit(
        self,
        event_type: str,
        message: str,
        *,
        role: str | None = None,
        **data: Any,
    ) -> None:
        agent_role = None
        if role:
            try:
                agent_role = AgentRole(role)
            except ValueError:
                agent_role = None
        event = ActivityEvent(
            project_id=self._project_id,
            agent_role=agent_role,
            event_type=event_type,
            message=message,
            data=data,
        )
        self._session.add(event)
        await self._session.flush()
        if self._publisher is not None:
            await self._publisher.publish(
                self._project_id,
                {
                    "type": event_type,
                    "message": message,
                    "role": role,
                    "data": data,
                },
            )
