"""Server-Sent Events endpoint powering the live dashboard.

A browser opens an `EventSource` against `/events/projects/{id}/stream` and
receives every activity event for that project as it happens. Events originate
from the orchestrator, are persisted to `activity_events`, and fan out through
the Redis-backed :class:`EventBus`.

SSE is used rather than WebSockets because the stream is unidirectional
(server -> dashboard), which keeps proxies, load balancers, and reconnection
logic simple. The browser's native `EventSource` reconnects automatically.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.session import get_session
from app.models import User
from app.orchestration.event_bus import get_event_bus
from app.security_helpers import resolve_project_for_user, user_from_token

logger = get_logger(__name__)
router = APIRouter(prefix="/events", tags=["events"])

# Heartbeat keeps intermediaries from closing an idle connection.
_HEARTBEAT_SECONDS = 20


async def _event_stream(project_id: uuid.UUID, request: Request) -> AsyncGenerator[bytes, None]:
    bus = get_event_bus()
    # Prime the client so EventSource fires `onopen` immediately.
    yield b": connected\n\n"
    queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=1000)

    async def pump() -> None:
        try:
            async for event in bus.subscribe(project_id):
                await queue.put(event)
        except asyncio.CancelledError:  # pragma: no cover - shutdown path
            raise
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("sse_pump_error", project=str(project_id), error=str(exc))

    pump_task = asyncio.create_task(pump())
    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_SECONDS)
            except TimeoutError:
                yield b": ping\n\n"  # comment line = heartbeat
                continue
            payload = json.dumps(event, default=str)
            event_type = event.get("event_type", "message")
            yield f"event: {event_type}\ndata: {payload}\n\n".encode()
    finally:
        pump_task.cancel()
        with_suppress = asyncio.gather(pump_task, return_exceptions=True)
        await with_suppress


@router.get("/projects/{project_id}/stream")
async def stream_project_events(
    project_id: uuid.UUID,
    request: Request,
    token: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """Stream a project's activity as Server-Sent Events.

    ``EventSource`` cannot set Authorization headers, so the short-lived JWT is
    accepted as a ``token`` query parameter and validated exactly like the
    header-based flow. Ownership is enforced before any data is streamed.
    """
    user: User = await user_from_token(token, session)
    await resolve_project_for_user(project_id, user, session)

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",  # disable nginx buffering for SSE
    }
    return StreamingResponse(
        _event_stream(project_id, request),
        media_type="text/event-stream",
        headers=headers,
    )
