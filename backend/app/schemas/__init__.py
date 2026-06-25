"""Pydantic v2 schemas for the public API."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import (
    AgentRole,
    AgentStatus,
    ApprovalKind,
    DeploymentStatus,
    MemoryKind,
    Priority,
    ProjectStatus,
    PullRequestStatus,
    TaskKind,
    TaskStatus,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Auth -------------------------------------------------------------------
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenPair(BaseModel):
    """Access + refresh token pair returned by login and refresh."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # access-token lifetime in seconds


class RefreshRequest(BaseModel):
    refresh_token: str


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = None


class UserOut(ORMModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    is_active: bool
    is_superuser: bool


# --- Projects ---------------------------------------------------------------
class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    repo_full_name: str | None = Field(default=None, examples=["acme/web-app"])
    mission: str | None = None
    autonomy_level: int = Field(default=2, ge=0, le=3)


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    mission: str | None = None
    objectives: dict | None = None
    autonomy_level: int | None = Field(default=None, ge=0, le=3)
    status: ProjectStatus | None = None


class ProjectOut(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    status: ProjectStatus
    repo_full_name: str | None
    repo_url: str | None
    default_branch: str
    primary_language: str | None
    mission: str | None
    objectives: dict
    autonomy_level: int
    is_running: bool
    architecture_summary: str | None
    metrics: dict
    created_at: datetime
    updated_at: datetime


# --- Agents -----------------------------------------------------------------
class AgentOut(ORMModel):
    id: uuid.UUID
    role: AgentRole
    status: AgentStatus
    current_task_id: uuid.UUID | None
    last_heartbeat: datetime | None
    total_runs: int
    total_tokens: int


# --- Tasks ------------------------------------------------------------------
class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    description: str | None = None
    kind: TaskKind = TaskKind.FEATURE
    priority: Priority = Priority.MEDIUM
    complexity: int = Field(default=3, ge=1, le=13)
    acceptance_criteria: list[str] = Field(default_factory=list)
    depends_on: list[uuid.UUID] = Field(default_factory=list)


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: TaskStatus | None = None
    priority: Priority | None = None
    assigned_role: AgentRole | None = None


class TaskOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    parent_id: uuid.UUID | None
    title: str
    description: str | None
    kind: TaskKind
    status: TaskStatus
    priority: Priority
    complexity: int
    assigned_role: AgentRole | None
    branch_name: str | None
    acceptance_criteria: list
    attempts: int
    github_issue_number: int | None
    created_at: datetime
    updated_at: datetime


# --- Pull requests ----------------------------------------------------------
class PullRequestOut(ORMModel):
    id: uuid.UUID
    number: int
    title: str
    body: str | None
    head_branch: str
    base_branch: str
    status: PullRequestStatus
    files_changed: int
    additions: int
    deletions: int
    review_summary: str | None
    review_score: float | None
    checks_passing: bool
    merged_at: datetime | None
    created_at: datetime


# --- Deployments ------------------------------------------------------------
class DeploymentOut(ORMModel):
    id: uuid.UUID
    environment: str
    commit_sha: str | None
    status: DeploymentStatus
    url: str | None
    duration_seconds: float | None
    created_at: datetime


# --- Memory -----------------------------------------------------------------
class MemoryCreate(BaseModel):
    kind: MemoryKind
    title: str
    content: str
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    meta: dict = Field(default_factory=dict)


class MemoryOut(ORMModel):
    id: uuid.UUID
    kind: MemoryKind
    title: str
    content: str
    importance: float
    access_count: int
    meta: dict
    created_at: datetime


class MemoryHit(MemoryOut):
    similarity: float


# --- Approvals --------------------------------------------------------------
class ApprovalOut(ORMModel):
    id: uuid.UUID
    kind: ApprovalKind
    subject_id: uuid.UUID | None
    summary: str
    payload: dict
    approved: bool | None
    created_at: datetime


class ApprovalDecision(BaseModel):
    approved: bool
    reason: str | None = None


# --- Activity ---------------------------------------------------------------
class ActivityEventOut(ORMModel):
    id: int
    project_id: uuid.UUID
    agent_role: AgentRole | None
    event_type: str
    message: str
    data: dict
    created_at: datetime


# --- Dashboard --------------------------------------------------------------
class ProjectMetrics(BaseModel):
    tasks_total: int
    tasks_done: int
    tasks_in_progress: int
    open_prs: int
    merged_prs: int
    deployments_succeeded: int
    agents_active: int
    velocity_7d: float
    avg_review_score: float | None


class DashboardSummary(BaseModel):
    projects_active: int
    agents_running: int
    tasks_queued: int
    prs_open: int
    deployments_today: int
    pending_approvals: int
