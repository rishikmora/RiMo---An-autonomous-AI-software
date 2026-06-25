"""Project routes: CRUD, repo connection, and autonomous run control."""
from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger
from app.core.security import get_current_user
from app.db.session import get_session, session_scope
from app.integrations.github import GitHubClient
from app.memory.service import MemoryService
from app.models import Project, User
from app.models.enums import ProjectStatus
from app.orchestration.analyzer import CodebaseAnalyzer
from app.orchestration.orchestrator import Orchestrator
from app.schemas import ProjectCreate, ProjectOut, ProjectUpdate
from app.services.llm import LLMClient

logger = get_logger(__name__)
router = APIRouter(prefix="/projects", tags=["projects"])


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:64] or "project"


async def _get_owned_project(project_id: uuid.UUID, user: User, session: AsyncSession) -> Project:
    project = (
        await session.execute(
            select(Project)
            .options(selectinload(Project.owner))
            .where(Project.id == project_id, Project.owner_id == user.id)
        )
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return project


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Project:
    project = Project(
        owner_id=user.id,
        name=payload.name,
        slug=_slugify(payload.name),
        description=payload.description,
        repo_full_name=payload.repo_full_name,
        mission=payload.mission,
        autonomy_level=payload.autonomy_level,
        status=ProjectStatus.ANALYZING if payload.repo_full_name else ProjectStatus.DRAFT,
    )
    if payload.repo_full_name:
        project.repo_url = f"https://github.com/{payload.repo_full_name}"
    session.add(project)
    await session.flush()

    orch = Orchestrator(session)
    await orch.ensure_agents(project)

    if payload.repo_full_name:
        background.add_task(_analyze_repo, project.id, user.id)

    await session.refresh(project, attribute_names=["owner"])
    return project


class StartupRequest(BaseModel):
    idea: str = Field(min_length=10, max_length=2000)
    autonomy_level: int = 2


@router.post("/startup", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def startup_mode(
    body: StartupRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Project:
    """Autonomous startup mode: one idea in, a complete initial plan out.

    From a single line ("Build an AI CRM for real estate agents"), RiMo derives
    a mission, an architecture outline, and an MVP backlog plus standard scaffold
    (landing page, docs, analytics, CI/CD) — no human planning required. The
    project is created ACTIVE so the worker picks it up immediately.
    """
    from app.orchestration.product import startup_factory
    from app.orchestration.utils import parse_json_output

    # Derive a name from the idea (first clause), create the project shell.
    name = body.idea.strip().rstrip(".").split(" for ")[0][:120]
    project = Project(
        owner_id=user.id,
        name=name,
        slug=_slugify(name) + "-" + uuid.uuid4().hex[:6],
        description=body.idea,
        autonomy_level=body.autonomy_level,
        status=ProjectStatus.DRAFT,
        objectives={},
    )
    session.add(project)
    await session.flush()

    llm = LLMClient()

    async def strategist(idea: str) -> dict:
        prompt = (
            "You are RiMo's founding strategist. Given a one-line product idea, "
            "produce a complete initial plan. Return ONLY JSON with keys: "
            '"mission" (one sentence), "architecture" (a short paragraph naming the '
            'stack and major components), "prd" (3-5 sentence product brief), '
            '"market" (2-3 sentences on target users and competition), and '
            '"mvp_tasks" (array of 5-10 objects with "title", "kind" '
            '(feature|infra|docs), "priority" (critical|high|medium|low), '
            '"complexity" (1-8), "acceptance_criteria" (array of strings)).\n\n'
            f"Product idea: {idea}"
        )
        resp = await llm.complete(
            system="You produce complete, scoped startup plans as strict JSON.",
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        return parse_json_output(text) or {}

    blueprint = await startup_factory.bootstrap(
        session, project=project, idea=body.idea, strategist=strategist
    )
    # Persist the PRD/market research onto the project for the dashboard.
    plan_meta = dict(project.metrics or {})
    project.metrics = plan_meta

    orch = Orchestrator(session)
    await orch.ensure_agents(project)

    logger.info(
        "startup_mode",
        project=str(project.id),
        mvp_tasks=len(blueprint.tasks),
        deliverables=len(blueprint.deliverables),
    )
    await session.refresh(project, attribute_names=["owner"])
    return project


@router.get("", response_model=list[ProjectOut])
async def list_projects(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[Project]:
    rows = await session.execute(
        select(Project).where(Project.owner_id == user.id).order_by(Project.created_at.desc())
    )
    return list(rows.scalars().all())


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Project:
    return await _get_owned_project(project_id, user, session)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Project:
    project = await _get_owned_project(project_id, user, session)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    return project


@router.post("/{project_id}/start", response_model=ProjectOut)
async def start_project(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Project:
    """Begin autonomous operation. The worker process picks it up on its next cycle."""
    project = await _get_owned_project(project_id, user, session)
    if project.status == ProjectStatus.DRAFT:
        project.status = ProjectStatus.ACTIVE
    project.is_running = True
    logger.info("project_started", project=str(project.id))
    return project


@router.post("/{project_id}/pause", response_model=ProjectOut)
async def pause_project(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Project:
    project = await _get_owned_project(project_id, user, session)
    project.is_running = False
    project.status = ProjectStatus.PAUSED
    return project


@router.post("/{project_id}/plan", response_model=ProjectOut)
async def trigger_planning(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Project:
    """Run a planning cycle immediately (synchronously)."""
    project = await _get_owned_project(project_id, user, session)
    orch = Orchestrator(session)
    await orch.plan_project(project)
    return project


# --- background helpers -----------------------------------------------------
async def _analyze_repo(project_id: uuid.UUID, user_id: uuid.UUID) -> None:
    async with session_scope() as session:
        project = (
            await session.execute(
                select(Project).options(selectinload(Project.owner)).where(Project.id == project_id)
            )
        ).scalar_one_or_none()
        if project is None or not project.repo_full_name:
            return
        installation_id = project.owner.github_installation_id
        if not installation_id:
            project.status = ProjectStatus.DRAFT
            return
        analyzer = CodebaseAnalyzer(LLMClient(), MemoryService())
        try:
            await analyzer.analyze(session, project, GitHubClient(installation_id))
            project.status = ProjectStatus.ACTIVE
        except Exception as exc:
            logger.error("analyze_failed", project=str(project_id), error=str(exc))
            project.status = ProjectStatus.DRAFT
