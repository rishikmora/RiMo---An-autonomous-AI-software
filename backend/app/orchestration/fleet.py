"""RiMo OS — fleet management and the agent marketplace.

**Fleet management** treats RiMo as an operating system over a portfolio of
projects. It schedules attention across many projects under a global concurrency
budget, surfaces a fleet-wide health view, and decides which projects the worker
should advance next based on priority, staleness, and pending approvals.

**The agent marketplace** lets a project dynamically "hire" specialized agents
beyond the core ten — e.g. a Flutter agent, an ML agent, a Next.js agent — by
registering an :class:`AgentSpec` that the orchestrator can instantiate on
demand. Specialists are matched to a project from its detected stack, so the
right expertise shows up automatically.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models import Approval, Project, Task
from app.models.enums import ProjectStatus, TaskStatus

logger = get_logger(__name__)


# --- Agent marketplace ------------------------------------------------------
@dataclass(frozen=True)
class AgentSpec:
    """A hireable specialist beyond the core ten."""

    slug: str
    title: str
    expertise: str
    # Stack signals that make this specialist relevant (matched case-insensitively).
    triggers: tuple[str, ...]
    system_prompt: str


class AgentMarketplace:
    """Registry of specialized agents a project can dynamically hire."""

    def __init__(self) -> None:
        self._catalog: dict[str, AgentSpec] = {}
        self._install_defaults()

    def register(self, spec: AgentSpec) -> None:
        self._catalog[spec.slug] = spec
        logger.info("agent_registered", slug=spec.slug)

    def all(self) -> list[AgentSpec]:
        return list(self._catalog.values())

    def get(self, slug: str) -> AgentSpec | None:
        return self._catalog.get(slug)

    def match(self, project: Project) -> list[AgentSpec]:
        """Recommend specialists relevant to a project's stack/mission."""
        haystack = " ".join(
            filter(
                None,
                [
                    project.primary_language or "",
                    project.mission or "",
                    project.description or "",
                    " ".join(str(v) for v in (project.objectives or {}).get("technologies", [])),
                ],
            )
        ).lower()
        matched = [
            spec
            for spec in self._catalog.values()
            if any(trigger.lower() in haystack for trigger in spec.triggers)
        ]
        logger.info("agents_matched", project=str(project.id), count=len(matched))
        return matched

    def _install_defaults(self) -> None:
        defaults = [
            AgentSpec(
                slug="flutter",
                title="RiMo Flutter",
                expertise="Flutter & Dart mobile development",
                triggers=("flutter", "dart", "mobile app"),
                system_prompt=(
                    "You are RiMo Flutter, an expert Flutter/Dart engineer. You build "
                    "idiomatic, performant cross-platform mobile UIs with proper state "
                    "management, null safety, and widget testing."
                ),
            ),
            AgentSpec(
                slug="ml",
                title="RiMo ML",
                expertise="Machine learning & data pipelines",
                triggers=("machine learning", "ml", "pytorch", "tensorflow", "model training", "data pipeline"),
                system_prompt=(
                    "You are RiMo ML, an expert ML engineer. You design training and "
                    "inference pipelines, handle data preprocessing, evaluation, and "
                    "reproducibility, and write rigorous, tested ML code."
                ),
            ),
            AgentSpec(
                slug="nextjs",
                title="RiMo Next.js",
                expertise="Next.js & React architecture",
                triggers=("next.js", "nextjs", "react", "app router", "rsc"),
                system_prompt=(
                    "You are RiMo Next.js, an expert in the Next.js App Router, React "
                    "Server Components, and modern frontend architecture. You build "
                    "type-safe, accessible, performant interfaces."
                ),
            ),
            AgentSpec(
                slug="data",
                title="RiMo Data",
                expertise="SQL, schema design & query optimization",
                triggers=("postgres", "sql", "database", "schema", "query"),
                system_prompt=(
                    "You are RiMo Data, an expert database engineer. You design "
                    "normalized schemas, write efficient queries, add the right "
                    "indexes, and reason about migrations safely."
                ),
            ),
            AgentSpec(
                slug="mobile-rn",
                title="RiMo React Native",
                expertise="React Native cross-platform apps",
                triggers=("react native", "expo", "mobile"),
                system_prompt=(
                    "You are RiMo React Native, an expert in React Native and Expo. "
                    "You build performant native apps with proper navigation and "
                    "platform-aware UX."
                ),
            ),
        ]
        for spec in defaults:
            self._catalog[spec.slug] = spec


# --- Fleet management -------------------------------------------------------
@dataclass
class ProjectHealth:
    project_id: str
    name: str
    status: str
    open_tasks: int
    pending_approvals: int
    is_running: bool
    attention_score: float = 0.0


@dataclass
class FleetView:
    total_projects: int
    running: int
    blocked: int
    total_open_tasks: int
    total_pending_approvals: int
    projects: list[ProjectHealth] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total_projects": self.total_projects,
            "running": self.running,
            "blocked": self.blocked,
            "total_open_tasks": self.total_open_tasks,
            "total_pending_approvals": self.total_pending_approvals,
            "projects": [
                {
                    "project_id": p.project_id,
                    "name": p.name,
                    "status": p.status,
                    "open_tasks": p.open_tasks,
                    "pending_approvals": p.pending_approvals,
                    "is_running": p.is_running,
                    "attention_score": round(p.attention_score, 3),
                }
                for p in self.projects
            ],
        }


class FleetManager:
    """Schedules attention across the project portfolio (the RiMo OS scheduler)."""

    async def health(self, session: AsyncSession, *, owner_id: uuid.UUID) -> FleetView:
        projects = (
            await session.execute(select(Project).where(Project.owner_id == owner_id))
        ).scalars().all()

        healths: list[ProjectHealth] = []
        running = blocked = total_tasks = total_approvals = 0

        for p in projects:
            open_tasks = (
                await session.execute(
                    select(func.count())
                    .select_from(Task)
                    .where(
                        Task.project_id == p.id,
                        Task.status.in_([TaskStatus.READY, TaskStatus.IN_PROGRESS, TaskStatus.BACKLOG]),
                    )
                )
            ).scalar_one()
            pending = (
                await session.execute(
                    select(func.count())
                    .select_from(Approval)
                    .where(Approval.project_id == p.id, Approval.approved.is_(None))
                )
            ).scalar_one()

            if p.is_running:
                running += 1
            if p.status == ProjectStatus.BLOCKED:
                blocked += 1
            total_tasks += open_tasks
            total_approvals += pending

            healths.append(
                ProjectHealth(
                    project_id=str(p.id),
                    name=p.name,
                    status=p.status.value,
                    open_tasks=open_tasks,
                    pending_approvals=pending,
                    is_running=p.is_running,
                    attention_score=self._attention(p, open_tasks, pending),
                )
            )

        healths.sort(key=lambda h: h.attention_score, reverse=True)
        return FleetView(
            total_projects=len(projects),
            running=running,
            blocked=blocked,
            total_open_tasks=total_tasks,
            total_pending_approvals=total_approvals,
            projects=healths,
        )

    async def schedule(
        self, session: AsyncSession, *, owner_id: uuid.UUID, slots: int | None = None
    ) -> list[uuid.UUID]:
        """Pick which projects the worker should advance next, within budget.

        Returns up to `slots` project ids ranked by attention score — the OS
        scheduling decision the worker honors when fanning out work.
        """
        budget = slots or settings.max_concurrent_projects
        view = await self.health(session, owner_id=owner_id)
        chosen = [
            uuid.UUID(p.project_id)
            for p in view.projects
            if p.is_running and p.open_tasks > 0
        ][:budget]
        logger.info("fleet_scheduled", owner=str(owner_id), chosen=len(chosen))
        return chosen

    @staticmethod
    def _attention(project: Project, open_tasks: int, pending: int) -> float:
        """Score how much a project needs the worker's attention.

        Pending approvals and blocked status dominate (they stall progress);
        open work and running state contribute; archived/paused decay.
        """
        score = 0.0
        score += pending * 0.4          # approvals block everything downstream
        score += min(open_tasks, 20) * 0.05
        if project.status == ProjectStatus.BLOCKED:
            score += 0.5
        if project.is_running:
            score += 0.2
        if project.status in {ProjectStatus.ARCHIVED, ProjectStatus.PAUSED}:
            score *= 0.1
        return score


agent_marketplace = AgentMarketplace()
fleet_manager = FleetManager()
