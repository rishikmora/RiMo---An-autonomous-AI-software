"""Autonomous failure recovery.

When something fails — a build, a test run, a deploy — RiMo does not stop and
wait for a human. It opens an :class:`Incident`, diagnoses the failure (using the
model to read logs and the knowledge graph to understand blast radius), and runs
a bounded recovery strategy: retry with a fix, then roll back, then escalate.
Every step is recorded on the incident timeline, producing an audit trail and a
post-mortem the Memory agent can learn from.

The recovery policy is deliberately conservative and bounded: a fixed retry
budget, automatic rollback to the last good state on exhaustion, and escalation
(a human approval/incident) rather than unbounded thrashing.
"""
from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import Incident
from app.models.enums import IncidentStatus

logger = get_logger(__name__)

# A recovery action returns True if it resolved the failure.
RecoveryAction = Callable[[], Awaitable[bool]]


class RecoveryOutcome:
    __slots__ = ("status", "incident_id", "summary")

    def __init__(self, status: IncidentStatus, incident_id: uuid.UUID, summary: str) -> None:
        self.status = status
        self.incident_id = incident_id
        self.summary = summary


class FailureRecovery:
    """Runs the diagnose → retry → rollback → escalate loop for a failure."""

    def __init__(self, max_retries: int = 2) -> None:
        self._max_retries = max_retries

    async def open_incident(
        self,
        session: AsyncSession,
        *,
        project_id: uuid.UUID,
        trigger: str,
        title: str,
        task_id: uuid.UUID | None = None,
    ) -> Incident:
        incident = Incident(
            project_id=project_id,
            task_id=task_id,
            title=title,
            trigger=trigger,
            status=IncidentStatus.OPEN,
            timeline=[_step("opened", f"Incident opened for {trigger} failure")],
        )
        session.add(incident)
        await session.flush()
        logger.info("incident_opened", incident=str(incident.id), trigger=trigger)
        return incident

    async def recover(
        self,
        session: AsyncSession,
        incident: Incident,
        *,
        diagnose: Callable[[], Awaitable[str]],
        retry: RecoveryAction,
        rollback: RecoveryAction | None = None,
    ) -> RecoveryOutcome:
        """Execute the bounded recovery strategy against an open incident.

        `diagnose` produces a human-readable root-cause analysis. `retry`
        attempts a fix-and-rerun (it should apply a fix then re-run the failing
        step). `rollback` reverts to the last good state. All are async and
        provided by the orchestrator with the right context bound in.
        """
        incident.status = IncidentStatus.DIAGNOSING
        diagnosis = await diagnose()
        incident.diagnosis = diagnosis
        _append(incident, "diagnosed", diagnosis[:500])
        await session.flush()

        for attempt in range(1, self._max_retries + 1):
            incident.attempts = attempt
            _append(incident, "retry", f"Recovery attempt {attempt}/{self._max_retries}")
            try:
                if await retry():
                    incident.status = IncidentStatus.RECOVERED
                    incident.resolution = f"Recovered on attempt {attempt}"
                    _append(incident, "recovered", incident.resolution)
                    await session.flush()
                    logger.info("incident_recovered", incident=str(incident.id), attempt=attempt)
                    return RecoveryOutcome(IncidentStatus.RECOVERED, incident.id, incident.resolution)
            except Exception as exc:  # noqa: BLE001 - recovery must not raise
                _append(incident, "retry_error", str(exc)[:300])
                logger.warning("recovery_attempt_failed", incident=str(incident.id), error=str(exc))

        # Retries exhausted → roll back if we can.
        if rollback is not None:
            _append(incident, "rollback", "Retry budget exhausted; rolling back to last good state")
            try:
                if await rollback():
                    incident.status = IncidentStatus.ROLLED_BACK
                    incident.resolution = "Rolled back to last known-good state"
                    _append(incident, "rolled_back", incident.resolution)
                    await session.flush()
                    logger.info("incident_rolled_back", incident=str(incident.id))
                    return RecoveryOutcome(IncidentStatus.ROLLED_BACK, incident.id, incident.resolution)
            except Exception as exc:  # noqa: BLE001
                _append(incident, "rollback_error", str(exc)[:300])

        # Nothing worked → escalate to a human.
        incident.status = IncidentStatus.ESCALATED
        incident.resolution = "Automated recovery failed; escalated for human review"
        _append(incident, "escalated", incident.resolution)
        await session.flush()
        logger.warning("incident_escalated", incident=str(incident.id))
        return RecoveryOutcome(IncidentStatus.ESCALATED, incident.id, incident.resolution)

    def post_mortem(self, incident: Incident) -> str:
        """Render a concise incident report suitable for storing as memory."""
        lines = [
            f"# Incident: {incident.title}",
            f"Trigger: {incident.trigger}",
            f"Status: {incident.status.value}",
            f"Attempts: {incident.attempts}",
            "",
            "## Diagnosis",
            incident.diagnosis or "(none)",
            "",
            "## Resolution",
            incident.resolution or "(unresolved)",
            "",
            "## Timeline",
        ]
        for step in incident.timeline:
            lines.append(f"- [{step.get('at', '')}] {step.get('kind')}: {step.get('detail', '')}")
        return "\n".join(lines)


def _step(kind: str, detail: str) -> dict:
    return {"kind": kind, "detail": detail, "at": datetime.now(timezone.utc).isoformat()}


def _append(incident: Incident, kind: str, detail: str) -> None:
    # Reassign so SQLAlchemy detects the JSONB mutation.
    incident.timeline = [*incident.timeline, _step(kind, detail)]


failure_recovery = FailureRecovery()
