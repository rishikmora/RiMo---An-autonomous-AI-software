"""Startup creation mode and the autonomous product manager.

**Startup mode** turns a one-line idea ("Build an AI CRM") into a complete
initial company plan: mission, architecture outline, an MVP roadmap of scoped
tasks, and supporting deliverables (landing page, docs, analytics) — all queued
without further prompting. It chains the CEO → Architect → Planner agents into a
single bootstrap.

**The autonomous PM** closes the loop after launch: it ingests product signals
(feature usage, crashes, feedback, retention) and re-prioritizes the backlog so
the company works on what matters most, the way a human PM would.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import Project, Task
from app.models.enums import Priority, ProjectStatus, TaskKind, TaskStatus

logger = get_logger(__name__)

# A planner step is an async model call returning structured JSON.
Planner = Callable[[str], Awaitable[dict]]


@dataclass
class StartupBlueprint:
    mission: str
    architecture: str
    tasks: list[dict] = field(default_factory=list)
    deliverables: list[str] = field(default_factory=list)


class StartupFactory:
    """Bootstraps a complete project plan from a single product idea."""

    # Standard scaffold every new product gets, beyond feature work.
    _BASE_DELIVERABLES = [
        ("Landing page", TaskKind.FEATURE, Priority.MEDIUM),
        ("Project documentation", TaskKind.DOCS, Priority.MEDIUM),
        ("Analytics instrumentation", TaskKind.INFRA, Priority.LOW),
        ("CI/CD pipeline", TaskKind.INFRA, Priority.HIGH),
    ]

    async def bootstrap(
        self,
        session: AsyncSession,
        *,
        project: Project,
        idea: str,
        strategist: Planner,
    ) -> StartupBlueprint:
        """Produce and persist a full initial plan for a fresh project.

        `strategist` is a model call that, given the idea, returns:
            {"mission", "architecture", "mvp_tasks": [
                {"title","kind","priority","complexity","acceptance_criteria"}]}
        """
        plan = await strategist(idea)
        mission = str(plan.get("mission", "")).strip() or idea
        architecture = str(plan.get("architecture", "")).strip()

        project.mission = mission
        project.architecture_summary = architecture
        project.status = ProjectStatus.ACTIVE

        blueprint = StartupBlueprint(mission=mission, architecture=architecture)

        # 1) MVP feature tasks from the strategist.
        for spec in plan.get("mvp_tasks", [])[:20]:
            title = str(spec.get("title", "")).strip()
            if not title:
                continue
            task = Task(
                project_id=project.id,
                title=title,
                description=str(spec.get("description", ""))[:2000],
                kind=_coerce_kind(spec.get("kind"), TaskKind.FEATURE),
                status=TaskStatus.READY,
                priority=_coerce_priority(spec.get("priority"), Priority.HIGH),
                complexity=int(spec.get("complexity", 5) or 5),
                acceptance_criteria=spec.get("acceptance_criteria", []),
                result={"source": "startup_factory"},
            )
            session.add(task)
            blueprint.tasks.append({"title": title, "kind": task.kind.value})

        # 2) Standard scaffold deliverables.
        for name, kind, priority in self._BASE_DELIVERABLES:
            session.add(
                Task(
                    project_id=project.id,
                    title=name,
                    kind=kind,
                    status=TaskStatus.BACKLOG,
                    priority=priority,
                    complexity=3,
                    result={"source": "startup_factory:scaffold"},
                )
            )
            blueprint.deliverables.append(name)

        await session.flush()
        logger.info(
            "startup_bootstrapped",
            project=str(project.id),
            mvp_tasks=len(blueprint.tasks),
            deliverables=len(blueprint.deliverables),
        )
        return blueprint


@dataclass
class ProductSignals:
    """Inputs the PM reasons over. All optional; richer data = better decisions."""

    feature_usage: dict[str, int] = field(default_factory=dict)   # feature -> events
    crashes: dict[str, int] = field(default_factory=dict)         # area -> crash count
    feedback: list[str] = field(default_factory=list)             # raw user feedback
    retention_pct: float | None = None


class ProductManager:
    """Re-prioritizes the backlog from live product signals."""

    async def reprioritize(
        self,
        session: AsyncSession,
        *,
        project: Project,
        signals: ProductSignals,
        prioritizer: Planner | None = None,
    ) -> list[Task]:
        """Adjust task priorities using signals (and optionally a model).

        Deterministic rules run first (crashes are always urgent); if a
        `prioritizer` model is provided, it refines ordering using feedback and
        usage. Returns the tasks whose priority changed.
        """
        tasks = (
            await session.execute(
                select(Task).where(
                    Task.project_id == project.id,
                    Task.status.in_([TaskStatus.BACKLOG, TaskStatus.READY]),
                )
            )
        ).scalars().all()

        changed: list[Task] = []

        # Rule 1: crashes dominate. Any task referencing a crashing area → critical.
        crash_areas = {k.lower() for k, v in signals.crashes.items() if v > 0}
        for t in tasks:
            text = f"{t.title} {t.description or ''}".lower()
            if any(area in text for area in crash_areas) and t.priority != Priority.CRITICAL:
                t.priority = Priority.CRITICAL
                t.kind = TaskKind.BUGFIX
                changed.append(t)

        # Rule 2: heavily-used features get a priority bump for related work.
        hot_features = {k.lower() for k, v in sorted(
            signals.feature_usage.items(), key=lambda kv: kv[1], reverse=True
        )[:3]}
        for t in tasks:
            text = f"{t.title} {t.description or ''}".lower()
            if any(f in text for f in hot_features) and t.priority.value > Priority.HIGH.value:
                t.priority = Priority.HIGH
                if t not in changed:
                    changed.append(t)

        # Optional model-driven refinement from qualitative feedback.
        if prioritizer and signals.feedback:
            context = self._render_signals(signals, tasks)
            try:
                ranking = await prioritizer(context)
                changed.extend(self._apply_ranking(tasks, ranking, changed))
            except Exception as exc:  # noqa: BLE001 - PM refinement is best-effort
                logger.warning("pm_refinement_failed", error=str(exc))

        await session.flush()
        logger.info("backlog_reprioritized", project=str(project.id), changed=len(changed))
        return changed

    @staticmethod
    def _render_signals(signals: ProductSignals, tasks: list[Task]) -> str:
        lines = ["Product signals:"]
        if signals.retention_pct is not None:
            lines.append(f"- Retention: {signals.retention_pct:.0f}%")
        if signals.feature_usage:
            top = sorted(signals.feature_usage.items(), key=lambda kv: kv[1], reverse=True)[:5]
            lines.append("- Top features: " + ", ".join(f"{k}({v})" for k, v in top))
        if signals.feedback:
            lines.append("- Feedback:")
            lines.extend(f"    • {fb[:160]}" for fb in signals.feedback[:8])
        lines.append("\nCurrent backlog:")
        for t in tasks[:30]:
            lines.append(f"- [{t.id}] {t.title} (priority={t.priority.name})")
        return "\n".join(lines)

    @staticmethod
    def _apply_ranking(tasks: list[Task], ranking: dict, already: list[Task]) -> list[Task]:
        """Apply a model ranking of {task_id: priority_name} to tasks."""
        by_id = {str(t.id): t for t in tasks}
        changed: list[Task] = []
        for tid, pr in (ranking.get("priorities") or {}).items():
            task = by_id.get(str(tid))
            if not task:
                continue
            new_pr = _coerce_priority(pr, task.priority)
            if new_pr != task.priority:
                task.priority = new_pr
                if task not in already:
                    changed.append(task)
        return changed


def _coerce_kind(value, default: TaskKind) -> TaskKind:
    try:
        return TaskKind(str(value))
    except (ValueError, TypeError):
        return default


def _coerce_priority(value, default: Priority) -> Priority:
    mapping = {
        "critical": Priority.CRITICAL,
        "high": Priority.HIGH,
        "medium": Priority.MEDIUM,
        "low": Priority.LOW,
    }
    if isinstance(value, str) and value.lower() in mapping:
        return mapping[value.lower()]
    try:
        return Priority(int(value))
    except (ValueError, TypeError):
        return default


startup_factory = StartupFactory()
product_manager = ProductManager()
