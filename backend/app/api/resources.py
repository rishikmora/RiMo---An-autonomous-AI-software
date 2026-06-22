"""Resource routes: tasks, agents, pull requests, deployments, memory,
approvals, activity, and the dashboard summary."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import get_current_user
from app.db.session import get_session
from app.memory.service import MemoryService
from app.models import (
    ActivityEvent,
    Agent,
    Approval,
    Deployment,
    MemoryRecord,
    Project,
    PullRequest,
    Task,
    User,
)
from app.models.enums import (
    ApprovalKind,
    DeploymentStatus,
    PullRequestStatus,
    TaskStatus,
)
from app.orchestration.orchestrator import Orchestrator
from app.schemas import (
    ActivityEventOut,
    AgentOut,
    ApprovalDecision,
    ApprovalOut,
    DashboardSummary,
    DeploymentOut,
    MemoryCreate,
    MemoryHit,
    MemoryOut,
    ProjectMetrics,
    PullRequestOut,
    TaskCreate,
    TaskOut,
    TaskUpdate,
)

router = APIRouter(tags=["resources"])


async def _owned_project(project_id: uuid.UUID, user: User, session: AsyncSession) -> Project:
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


# --- Tasks ------------------------------------------------------------------
@router.get("/projects/{project_id}/tasks", response_model=list[TaskOut])
async def list_tasks(
    project_id: uuid.UUID,
    task_status: TaskStatus | None = Query(default=None),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[Task]:
    await _owned_project(project_id, user, session)
    stmt = select(Task).where(Task.project_id == project_id)
    if task_status:
        stmt = stmt.where(Task.status == task_status)
    stmt = stmt.order_by(Task.priority, Task.created_at)
    return list((await session.execute(stmt)).scalars().all())


@router.post("/projects/{project_id}/tasks", response_model=TaskOut, status_code=201)
async def create_task(
    project_id: uuid.UUID,
    payload: TaskCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Task:
    await _owned_project(project_id, user, session)
    task = Task(
        project_id=project_id,
        title=payload.title,
        description=payload.description,
        kind=payload.kind,
        priority=payload.priority,
        complexity=payload.complexity,
        acceptance_criteria=payload.acceptance_criteria,
        depends_on=[str(d) for d in payload.depends_on],
        status=TaskStatus.READY,
    )
    session.add(task)
    await session.flush()
    return task


@router.patch("/tasks/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: uuid.UUID,
    payload: TaskUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Task:
    task = await session.get(Task, task_id)
    if task is None:
        raise HTTPException(404, "Task not found")
    await _owned_project(task.project_id, user, session)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(task, field, value)
    return task


# --- Agents -----------------------------------------------------------------
@router.get("/projects/{project_id}/agents", response_model=list[AgentOut])
async def list_agents(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[Agent]:
    await _owned_project(project_id, user, session)
    rows = await session.execute(select(Agent).where(Agent.project_id == project_id))
    return list(rows.scalars().all())


# --- Pull requests ----------------------------------------------------------
@router.get("/projects/{project_id}/pull-requests", response_model=list[PullRequestOut])
async def list_prs(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[PullRequest]:
    await _owned_project(project_id, user, session)
    rows = await session.execute(
        select(PullRequest).where(PullRequest.project_id == project_id).order_by(PullRequest.created_at.desc())
    )
    return list(rows.scalars().all())


# --- Deployments ------------------------------------------------------------
@router.get("/projects/{project_id}/deployments", response_model=list[DeploymentOut])
async def list_deployments(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[Deployment]:
    await _owned_project(project_id, user, session)
    rows = await session.execute(
        select(Deployment).where(Deployment.project_id == project_id).order_by(Deployment.created_at.desc())
    )
    return list(rows.scalars().all())


@router.post("/deployments/{deployment_id}/rollback", response_model=DeploymentOut)
async def rollback_deployment(
    deployment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Deployment:
    """Roll a deployment back to the previous succeeded release."""
    deployment = await session.get(Deployment, deployment_id)
    if deployment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deployment not found")
    project = await _owned_project(deployment.project_id, user, session)
    return await Orchestrator(session).rollback_deployment(project, deployment)


# --- Memory -----------------------------------------------------------------
@router.get("/projects/{project_id}/memory", response_model=list[MemoryOut])
async def list_memory(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[MemoryRecord]:
    await _owned_project(project_id, user, session)
    rows = await session.execute(
        select(MemoryRecord)
        .where((MemoryRecord.project_id == project_id) | (MemoryRecord.project_id.is_(None)))
        .order_by(MemoryRecord.importance.desc(), MemoryRecord.created_at.desc())
        .limit(200)
    )
    return list(rows.scalars().all())


@router.post("/projects/{project_id}/memory/search", response_model=list[MemoryHit])
async def search_memory(
    project_id: uuid.UUID,
    query: str = Query(min_length=1),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[MemoryHit]:
    await _owned_project(project_id, user, session)
    memory = MemoryService()
    hits = await memory.recall(session, query=query, project_id=project_id)
    return [
        MemoryHit(**MemoryOut.model_validate(record).model_dump(), similarity=round(sim, 4))
        for record, sim in hits
    ]


@router.post("/projects/{project_id}/memory", response_model=MemoryOut, status_code=201)
async def add_memory(
    project_id: uuid.UUID,
    payload: MemoryCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MemoryRecord:
    await _owned_project(project_id, user, session)
    memory = MemoryService()
    return await memory.remember(
        session, kind=payload.kind, title=payload.title, content=payload.content,
        project_id=project_id, importance=payload.importance, meta=payload.meta,
    )


# --- Approvals --------------------------------------------------------------
@router.get("/projects/{project_id}/approvals", response_model=list[ApprovalOut])
async def list_approvals(
    project_id: uuid.UUID,
    pending_only: bool = Query(default=True),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[Approval]:
    await _owned_project(project_id, user, session)
    stmt = select(Approval).where(Approval.project_id == project_id)
    if pending_only:
        stmt = stmt.where(Approval.approved.is_(None))
    stmt = stmt.order_by(Approval.created_at.desc())
    return list((await session.execute(stmt)).scalars().all())


@router.post("/approvals/{approval_id}/decide", response_model=ApprovalOut)
async def decide_approval(
    approval_id: uuid.UUID,
    decision: ApprovalDecision,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Approval:
    approval = await session.get(Approval, approval_id)
    if approval is None:
        raise HTTPException(404, "Approval not found")
    project = await _owned_project(approval.project_id, user, session)
    if approval.approved is not None:
        raise HTTPException(409, "Approval already decided")

    approval.approved = decision.approved
    approval.decided_by = user.id
    approval.decided_at = datetime.now(UTC)

    # Execute the approved action.
    if decision.approved and approval.kind == ApprovalKind.MERGE and approval.subject_id:
        pr = await session.get(PullRequest, approval.subject_id)
        if pr and pr.status == PullRequestStatus.OPEN:
            await Orchestrator(session).merge_approved(project, pr)
    elif decision.approved and approval.kind == ApprovalKind.DEPLOY and approval.subject_id:
        deployment = await session.get(Deployment, approval.subject_id)
        if deployment:
            deployment.status = DeploymentStatus.QUEUED
    return approval


# --- Activity ---------------------------------------------------------------
@router.get("/projects/{project_id}/activity", response_model=list[ActivityEventOut])
async def list_activity(
    project_id: uuid.UUID,
    limit: int = Query(default=100, le=500),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ActivityEvent]:
    await _owned_project(project_id, user, session)
    rows = await session.execute(
        select(ActivityEvent)
        .where(ActivityEvent.project_id == project_id)
        .order_by(ActivityEvent.created_at.desc())
        .limit(limit)
    )
    return list(rows.scalars().all())


# --- Metrics & dashboard ----------------------------------------------------
@router.get("/projects/{project_id}/metrics", response_model=ProjectMetrics)
async def project_metrics(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProjectMetrics:
    await _owned_project(project_id, user, session)

    async def count(model, *conditions) -> int:
        stmt = select(func.count()).select_from(model).where(*conditions)
        return int((await session.execute(stmt)).scalar() or 0)

    week_ago = datetime.now(UTC) - timedelta(days=7)
    tasks_total = await count(Task, Task.project_id == project_id)
    tasks_done = await count(Task, Task.project_id == project_id, Task.status == TaskStatus.DONE)
    velocity = await count(Task, Task.project_id == project_id, Task.status == TaskStatus.DONE, Task.updated_at >= week_ago)
    avg_score = (await session.execute(
        select(func.avg(PullRequest.review_score)).where(PullRequest.project_id == project_id)
    )).scalar()

    return ProjectMetrics(
        tasks_total=tasks_total,
        tasks_done=tasks_done,
        tasks_in_progress=await count(Task, Task.project_id == project_id, Task.status == TaskStatus.IN_PROGRESS),
        open_prs=await count(PullRequest, PullRequest.project_id == project_id, PullRequest.status == PullRequestStatus.OPEN),
        merged_prs=await count(PullRequest, PullRequest.project_id == project_id, PullRequest.status == PullRequestStatus.MERGED),
        deployments_succeeded=await count(Deployment, Deployment.project_id == project_id, Deployment.status == DeploymentStatus.SUCCEEDED),
        agents_active=await count(Agent, Agent.project_id == project_id, Agent.status.in_(["working", "thinking"])),
        velocity_7d=float(velocity),
        avg_review_score=float(avg_score) if avg_score is not None else None,
    )


@router.get("/dashboard/summary", response_model=DashboardSummary)
async def dashboard_summary(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DashboardSummary:
    project_ids_stmt = select(Project.id).where(Project.owner_id == user.id)
    project_ids = [r[0] for r in (await session.execute(project_ids_stmt)).all()]
    if not project_ids:
        return DashboardSummary(0, 0, 0, 0, 0, 0)

    async def count(model, *conditions) -> int:
        stmt = select(func.count()).select_from(model).where(*conditions)
        return int((await session.execute(stmt)).scalar() or 0)

    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return DashboardSummary(
        projects_active=await count(Project, Project.owner_id == user.id, Project.status == "active"),
        agents_running=await count(Agent, Agent.project_id.in_(project_ids), Agent.status.in_(["working", "thinking"])),
        tasks_queued=await count(Task, Task.project_id.in_(project_ids), Task.status == TaskStatus.READY),
        prs_open=await count(PullRequest, PullRequest.project_id.in_(project_ids), PullRequest.status == PullRequestStatus.OPEN),
        deployments_today=await count(Deployment, Deployment.project_id.in_(project_ids), Deployment.created_at >= today),
        pending_approvals=await count(Approval, Approval.project_id.in_(project_ids), Approval.approved.is_(None)),
    )
