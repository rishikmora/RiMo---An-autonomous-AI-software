"""The continuous autonomous worker.

Runs forever, advancing every running project by one `tick()` per cycle, while
respecting concurrency limits. This is the process that makes RiMo operate
"24/7 with minimal human intervention". Run it as a separate deployment from
the API (see infra/k8s).

Reclaims expired task leases so that crashed work is retried, and refreshes
agent heartbeats so the dashboard can show liveness.
"""
from __future__ import annotations

import asyncio
import contextlib
import signal
from datetime import UTC, datetime

from sqlalchemy import select, update

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.db.session import session_scope
from app.models import Project, Task
from app.models.enums import ProjectStatus, TaskStatus
from app.orchestration.orchestrator import Orchestrator

logger = get_logger(__name__)


class Worker:
    def __init__(self) -> None:
        self._stop = asyncio.Event()
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_projects)

    def request_stop(self) -> None:
        logger.info("worker_stop_requested")
        self._stop.set()

    async def run_forever(self) -> None:
        logger.info("worker_started", concurrency=settings.max_concurrent_projects)
        cycle = 0
        while not self._stop.is_set():
            try:
                await self._reclaim_expired_leases()
                project_ids = await self._running_project_ids()
                if not project_ids:
                    await self._sleep(settings.heartbeat_interval_seconds)
                    continue
                await asyncio.gather(*(self._advance(pid) for pid in project_ids))

                # Slower maintenance cadence: autonomous research surveys and
                # knowledge-graph/refactor upkeep run every Nth cycle so they
                # don't compete with the per-task execution loop.
                cycle += 1
                if cycle % settings.maintenance_cycle_interval == 0:
                    await asyncio.gather(
                        *(self._maintain(pid) for pid in project_ids),
                        return_exceptions=True,
                    )
            except Exception as exc:  # never let the loop die
                logger.error("worker_cycle_error", error=str(exc))
            await self._sleep(2)
        logger.info("worker_stopped")

    async def _maintain(self, project_id) -> None:
        """Run autonomous background upkeep for a project (best-effort).

        Honors an opt-in research request flag set via the API, and is the hook
        where periodic knowledge-graph rebuilds and refactor scans are triggered
        by the orchestrator. Failures here never block the main loop.
        """
        async with self._semaphore, session_scope() as session:
            project = await session.get(Project, project_id)
            if project is None or project.status != ProjectStatus.ACTIVE:
                return
            orch = Orchestrator(session)
            try:
                await orch.run_maintenance(project)
            except Exception as exc:  # noqa: BLE001 - upkeep is best-effort
                logger.warning("maintenance_failed", project=str(project_id), error=str(exc))

    async def _advance(self, project_id) -> None:
        async with self._semaphore, session_scope() as session:
            project = await session.get(Project, project_id)
            if project is None or project.status != ProjectStatus.ACTIVE:
                return
            orch = Orchestrator(session)
            try:
                status = await orch.tick(project)
                await orch.process_pending_deployments(project)
                logger.info("project_ticked", project=str(project_id), result=status)
            except Exception as exc:
                logger.error("project_tick_failed", project=str(project_id), error=str(exc))
                project.status = ProjectStatus.BLOCKED

    async def _running_project_ids(self) -> list:
        async with session_scope() as session:
            rows = await session.execute(
                select(Project.id).where(
                    Project.is_running.is_(True),
                    Project.status == ProjectStatus.ACTIVE,
                )
            )
            return [r[0] for r in rows.all()]

    async def _reclaim_expired_leases(self) -> None:
        """Reset IN_PROGRESS tasks whose lease expired back to READY."""
        async with session_scope() as session:
            await session.execute(
                update(Task)
                .where(
                    Task.status == TaskStatus.IN_PROGRESS,
                    Task.lease_expires_at < datetime.now(UTC),
                )
                .values(status=TaskStatus.READY, lease_expires_at=None)
            )

    async def _sleep(self, seconds: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)


def main() -> None:
    configure_logging()
    worker = Worker()
    loop = asyncio.new_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, worker.request_stop)
    try:
        loop.run_until_complete(worker.run_forever())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
