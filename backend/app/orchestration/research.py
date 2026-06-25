"""Autonomous research engine.

RiMo doesn't only execute assigned work — it scans the outside world for things
worth doing and proposes them as tasks. The engine periodically surveys signal
sources (new libraries, releases, papers, competitor moves, community trends)
relevant to a project's mission and stack, then asks the Research model to
distill findings into concrete, scoped task proposals (e.g. "adopt the new
FFmpeg hardware-decode API to cut export latency").

Proposals are not executed blindly: they enter the backlog as `research`/feature
tasks for the Planner to prioritize against everything else, so the human and
the CEO agent stay in control of direction.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import Project, Task
from app.models.enums import Priority, TaskKind, TaskStatus

logger = get_logger(__name__)

# Source query templates. {topic} is filled from the project's stack/mission.
SIGNAL_SOURCES: dict[str, str] = {
    "releases": "{topic} new release changelog 2026",
    "libraries": "best {topic} libraries 2026",
    "papers": "{topic} state of the art paper 2026",
    "trends": "{topic} hacker news discussion",
    "competitors": "{topic} alternatives comparison 2026",
}

WebSearch = Callable[[str], Awaitable[list[dict]]]
# Distiller: async (research_context: str) -> list[dict task proposals]
Distiller = Callable[[str], Awaitable[list[dict]]]


@dataclass
class ResearchFinding:
    source: str
    query: str
    results: list[dict] = field(default_factory=list)


class ResearchEngine:
    """Surveys external sources and turns findings into task proposals."""

    def __init__(self, web_search: WebSearch) -> None:
        self._search = web_search

    def _topics(self, project: Project) -> list[str]:
        topics: list[str] = []
        if project.primary_language:
            topics.append(project.primary_language)
        # Pull named technologies from objectives/mission if present.
        objectives = project.objectives or {}
        for v in (objectives.get("technologies") or [])[:3]:
            topics.append(str(v))
        if not topics and project.mission:
            topics.append(project.mission.split(".")[0][:40])
        return topics[:3] or ["software engineering"]

    async def survey(
        self, project: Project, *, sources: list[str] | None = None
    ) -> list[ResearchFinding]:
        """Run searches across the selected sources for the project's topics."""
        chosen = sources or list(SIGNAL_SOURCES.keys())
        topics = self._topics(project)
        findings: list[ResearchFinding] = []
        for source in chosen:
            template = SIGNAL_SOURCES.get(source)
            if not template:
                continue
            for topic in topics:
                query = template.format(topic=topic)
                try:
                    results = await self._search(query)
                except Exception as exc:  # noqa: BLE001 - research is best-effort
                    logger.warning("research_search_failed", source=source, error=str(exc))
                    results = []
                findings.append(ResearchFinding(source=source, query=query, results=results[:5]))
        logger.info("research_survey_complete", project=str(project.id), findings=len(findings))
        return findings

    @staticmethod
    def _render_context(findings: list[ResearchFinding]) -> str:
        blocks = []
        for f in findings:
            if not f.results:
                continue
            lines = [f"## Source: {f.source} (query: {f.query})"]
            for r in f.results:
                title = r.get("title", "")
                url = r.get("url", "")
                snippet = (r.get("snippet") or r.get("description") or "")[:200]
                lines.append(f"- {title} — {snippet} ({url})")
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)

    async def propose_tasks(
        self,
        session: AsyncSession,
        *,
        project: Project,
        distiller: Distiller,
        max_tasks: int = 5,
    ) -> list[Task]:
        """Survey, distill into proposals, and add them to the backlog.

        `distiller` is an async function (a Research-agent model call) that turns
        the rendered research context into structured task dicts:
            {"title", "rationale", "kind", "priority", "complexity"}
        """
        findings = await self.survey(project)
        context = self._render_context(findings)
        if not context.strip():
            return []

        proposals = await distiller(context)
        created: list[Task] = []
        for p in proposals[:max_tasks]:
            title = str(p.get("title", "")).strip()
            if not title:
                continue
            kind = _coerce_kind(p.get("kind"))
            priority = _coerce_priority(p.get("priority"))
            task = Task(
                project_id=project.id,
                title=title,
                description=str(p.get("rationale", ""))[:2000],
                kind=kind,
                status=TaskStatus.BACKLOG,
                priority=priority,
                complexity=int(p.get("complexity", 3) or 3),
                acceptance_criteria=p.get("acceptance_criteria", []),
                result={"source": "research_engine"},
            )
            session.add(task)
            created.append(task)
        await session.flush()
        logger.info("research_tasks_proposed", project=str(project.id), count=len(created))
        return created


def _coerce_kind(value) -> TaskKind:
    try:
        return TaskKind(str(value))
    except (ValueError, TypeError):
        return TaskKind.RESEARCH


def _coerce_priority(value) -> Priority:
    mapping = {"critical": Priority.CRITICAL, "high": Priority.HIGH, "medium": Priority.MEDIUM, "low": Priority.LOW}
    if isinstance(value, str) and value.lower() in mapping:
        return mapping[value.lower()]
    try:
        return Priority(int(value))
    except (ValueError, TypeError):
        return Priority.LOW  # research suggestions default to low priority
