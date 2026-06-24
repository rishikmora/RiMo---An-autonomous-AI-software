"""Self-improvement loop.

On a cadence (weekly by default), RiMo reflects on its own performance and
improves itself without human intervention:

  1. **Analyze failures** — mine recent incidents and failed tasks for recurring
     root causes, and store the lessons as durable memory.
  2. **Evolve prompts** — for each role with enough evidence, breed an improved
     prompt variant from the current champion (see :mod:`app.services.prompts`).
  3. **Tune routing** — inspect realized success rates per complexity tier and
     flag tiers that should be promoted/demoted to a different model.
  4. **Summarize** — produce a self-improvement report stored as a project-level
     memory the whole company can learn from.

This is the loop that makes RiMo compounding rather than static. It is bounded
and auditable: every change is logged, and prompt evolution only acts on
statistically meaningful samples.
"""
from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import Incident, ModelCall, Task
from app.models.enums import AgentRole, IncidentStatus, MemoryKind, TaskStatus
from app.services.prompts import prompt_service

logger = get_logger(__name__)

# Mutator: async (parent_template: str) -> str   (a model call proposing a better prompt)
PromptMutator = Callable[[str], Awaitable[str]]


@dataclass
class ImprovementReport:
    window_days: int
    failures_analyzed: int
    top_failure_causes: list[tuple[str, int]]
    prompts_evolved: list[str] = field(default_factory=list)
    routing_notes: list[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "window_days": self.window_days,
            "failures_analyzed": self.failures_analyzed,
            "top_failure_causes": self.top_failure_causes,
            "prompts_evolved": self.prompts_evolved,
            "routing_notes": self.routing_notes,
            "summary": self.summary,
        }


class SelfImprovementLoop:
    """Runs the periodic reflection-and-improvement cycle."""

    def __init__(self, window_days: int = 7) -> None:
        self._window = window_days

    async def run(
        self,
        session: AsyncSession,
        *,
        project_id: uuid.UUID,
        mutator: PromptMutator,
        roles: list[AgentRole] | None = None,
        store_memory=None,  # optional async (kind, title, content) -> None
    ) -> ImprovementReport:
        since = datetime.now(timezone.utc) - timedelta(days=self._window)

        causes = await self._analyze_failures(session, project_id=project_id, since=since)
        evolved = await self._evolve_prompts(session, mutator=mutator, roles=roles)
        routing_notes = await self._tune_routing(session, project_id=project_id, since=since)

        failures_total = sum(c for _, c in causes)
        summary = self._render_summary(causes, evolved, routing_notes, failures_total)

        report = ImprovementReport(
            window_days=self._window,
            failures_analyzed=failures_total,
            top_failure_causes=causes,
            prompts_evolved=evolved,
            routing_notes=routing_notes,
            summary=summary,
        )

        if store_memory is not None:
            await store_memory(
                MemoryKind.LESSON_LEARNED,
                f"Self-improvement report ({self._window}d)",
                summary,
            )
        logger.info(
            "self_improvement_complete",
            project=str(project_id),
            failures=failures_total,
            evolved=len(evolved),
        )
        return report

    async def _analyze_failures(
        self, session: AsyncSession, *, project_id: uuid.UUID, since: datetime
    ) -> list[tuple[str, int]]:
        """Cluster recent incidents + failed tasks by trigger/cause."""
        incidents = (
            await session.execute(
                select(Incident).where(
                    Incident.project_id == project_id, Incident.created_at >= since
                )
            )
        ).scalars().all()
        failed_tasks = (
            await session.execute(
                select(Task).where(
                    Task.project_id == project_id,
                    Task.status == TaskStatus.FAILED,
                    Task.updated_at >= since,
                )
            )
        ).scalars().all()

        counter: Counter[str] = Counter()
        for inc in incidents:
            counter[inc.trigger] += 1
            if inc.status == IncidentStatus.ESCALATED:
                counter[f"{inc.trigger}:escalated"] += 1
        for t in failed_tasks:
            counter[f"task:{t.kind.value}"] += 1
        return counter.most_common(5)

    async def _evolve_prompts(
        self,
        session: AsyncSession,
        *,
        mutator: PromptMutator,
        roles: list[AgentRole] | None,
    ) -> list[str]:
        evolved: list[str] = []
        for role in roles or list(AgentRole):
            candidate = await prompt_service.evolve(session, role=role, mutator=mutator)
            if candidate:
                evolved.append(f"{role.value}:{candidate.name}")
        return evolved

    async def _tune_routing(
        self, session: AsyncSession, *, project_id: uuid.UUID, since: datetime
    ) -> list[str]:
        """Surface routing observations from realized spend per tier/purpose."""
        rows = (
            await session.execute(
                select(
                    ModelCall.purpose,
                    func.count().label("n"),
                    func.sum(ModelCall.cost_usd).label("cost"),
                )
                .where(ModelCall.project_id == project_id, ModelCall.created_at >= since)
                .group_by(ModelCall.purpose)
            )
        ).all()
        notes: list[str] = []
        for purpose, n, cost in rows:
            if n and cost is not None:
                notes.append(f"{purpose or 'unknown'}: {n} calls, ${float(cost):.3f}")
        return notes

    @staticmethod
    def _render_summary(
        causes: list[tuple[str, int]],
        evolved: list[str],
        routing_notes: list[str],
        failures_total: int,
    ) -> str:
        lines = ["# Weekly Self-Improvement Report", ""]
        lines.append(f"Failures analyzed: {failures_total}")
        if causes:
            lines.append("\n## Top failure causes")
            for cause, n in causes:
                lines.append(f"- {cause}: {n}")
        if evolved:
            lines.append("\n## Prompts evolved")
            for e in evolved:
                lines.append(f"- {e}")
        else:
            lines.append("\n## Prompts evolved\n- (insufficient evidence this cycle)")
        if routing_notes:
            lines.append("\n## Routing spend by purpose")
            for note in routing_notes:
                lines.append(f"- {note}")
        return "\n".join(lines)


self_improvement = SelfImprovementLoop()
