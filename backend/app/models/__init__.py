"""SQLAlchemy ORM models.

The schema is normalised around five core aggregates:

    Project  ── has many ── Task ── has many ── AgentRun (execution attempts)
        │                    │
        │                    └── may produce ── PullRequest ── Deployment
        │
        ├── has many ── Agent (per-project worker instances)
        ├── has many ── MemoryRecord (vector-indexed knowledge)
        └── has many ── Approval (human-in-the-loop gates)

`pgvector` powers semantic recall on MemoryRecord.embedding.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.db.session import Base
from app.models.enums import (
    AgentRole,
    AgentStatus,
    ApprovalKind,
    DeploymentStatus,
    EdgeKind,
    IncidentStatus,
    MemoryKind,
    ModelProvider,
    NodeKind,
    Priority,
    ProjectStatus,
    PullRequestStatus,
    TaskKind,
    TaskStatus,
)


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class TimestampMixin:
    """Adds created_at / updated_at columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255))
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    github_installation_id: Mapped[str | None] = mapped_column(String(64))

    projects: Mapped[list[Project]] = relationship(back_populates="owner")


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, native_enum=False), default=ProjectStatus.DRAFT, index=True
    )

    # Repository linkage
    repo_full_name: Mapped[str | None] = mapped_column(String(512))  # owner/repo
    repo_url: Mapped[str | None] = mapped_column(String(1024))
    default_branch: Mapped[str] = mapped_column(String(255), default="main")
    primary_language: Mapped[str | None] = mapped_column(String(64))

    # Mission state owned by the CEO agent
    mission: Mapped[str | None] = mapped_column(Text)
    objectives: Mapped[dict] = mapped_column(JSONB, default=dict)
    autonomy_level: Mapped[int] = mapped_column(Integer, default=2)  # 0=manual..3=full
    is_running: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # Cached analysis of the codebase
    architecture_summary: Mapped[str | None] = mapped_column(Text)
    file_tree: Mapped[dict] = mapped_column(JSONB, default=dict)
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict)

    owner: Mapped[User] = relationship(back_populates="projects")
    agents: Mapped[list[Agent]] = relationship(back_populates="project", cascade="all, delete-orphan")
    tasks: Mapped[list[Task]] = relationship(back_populates="project", cascade="all, delete-orphan")
    pull_requests: Mapped[list[PullRequest]] = relationship(back_populates="project", cascade="all, delete-orphan")
    deployments: Mapped[list[Deployment]] = relationship(back_populates="project", cascade="all, delete-orphan")
    approvals: Mapped[list[Approval]] = relationship(back_populates="project", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("owner_id", "slug", name="uq_project_owner_slug"),)


class Agent(Base, TimestampMixin):
    """A per-project instance of a specialist agent role."""

    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    role: Mapped[AgentRole] = mapped_column(Enum(AgentRole, native_enum=False), nullable=False)
    status: Mapped[AgentStatus] = mapped_column(
        Enum(AgentStatus, native_enum=False), default=AgentStatus.IDLE, index=True
    )
    current_task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_runs: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)

    project: Mapped[Project] = relationship(back_populates="agents")

    __table_args__ = (
        UniqueConstraint("project_id", "role", name="uq_agent_project_role"),
        Index("ix_agent_status_role", "status", "role"),
    )


class Task(Base, TimestampMixin):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[TaskKind] = mapped_column(Enum(TaskKind, native_enum=False), default=TaskKind.FEATURE)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, native_enum=False), default=TaskStatus.BACKLOG, index=True
    )
    priority: Mapped[Priority] = mapped_column(Enum(Priority, native_enum=False), default=Priority.MEDIUM, index=True)
    complexity: Mapped[int] = mapped_column(Integer, default=3)  # story points 1..13
    assigned_role: Mapped[AgentRole | None] = mapped_column(Enum(AgentRole, native_enum=False))

    # Execution bookkeeping
    branch_name: Mapped[str | None] = mapped_column(String(255))
    depends_on: Mapped[list] = mapped_column(JSONB, default=list)  # list[str(uuid)]
    acceptance_criteria: Mapped[list] = mapped_column(JSONB, default=list)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict] = mapped_column(JSONB, default=dict)
    github_issue_number: Mapped[int | None] = mapped_column(Integer)

    project: Mapped[Project] = relationship(back_populates="tasks")
    runs: Mapped[list[AgentRun]] = relationship(back_populates="task", cascade="all, delete-orphan")
    pull_request: Mapped[PullRequest | None] = relationship(back_populates="task", uselist=False)

    __table_args__ = (
        Index("ix_task_queue", "project_id", "status", "priority"),
    )


class AgentRun(Base, TimestampMixin):
    """A single execution of an agent against a task (one reasoning loop)."""

    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    agent_role: Mapped[AgentRole] = mapped_column(Enum(AgentRole, native_enum=False), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    success: Mapped[bool | None] = mapped_column(Boolean)
    iterations: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    model: Mapped[str | None] = mapped_column(String(128))
    transcript: Mapped[list] = mapped_column(JSONB, default=list)  # list of step dicts
    error: Mapped[str | None] = mapped_column(Text)

    task: Mapped[Task] = relationship(back_populates="runs")


class PullRequest(Base, TimestampMixin):
    __tablename__ = "pull_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    head_branch: Mapped[str] = mapped_column(String(255), nullable=False)
    base_branch: Mapped[str] = mapped_column(String(255), default="main")
    status: Mapped[PullRequestStatus] = mapped_column(
        Enum(PullRequestStatus, native_enum=False), default=PullRequestStatus.OPEN, index=True
    )
    files_changed: Mapped[int] = mapped_column(Integer, default=0)
    additions: Mapped[int] = mapped_column(Integer, default=0)
    deletions: Mapped[int] = mapped_column(Integer, default=0)
    review_summary: Mapped[str | None] = mapped_column(Text)
    review_score: Mapped[float | None] = mapped_column(Float)  # 0..100
    checks_passing: Mapped[bool] = mapped_column(Boolean, default=False)
    merge_commit_sha: Mapped[str | None] = mapped_column(String(64))
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    project: Mapped[Project] = relationship(back_populates="pull_requests")
    task: Mapped[Task | None] = relationship(back_populates="pull_request")

    __table_args__ = (UniqueConstraint("project_id", "number", name="uq_pr_project_number"),)


class Deployment(Base, TimestampMixin):
    __tablename__ = "deployments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    environment: Mapped[str] = mapped_column(String(64), default="staging")
    commit_sha: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[DeploymentStatus] = mapped_column(
        Enum(DeploymentStatus, native_enum=False), default=DeploymentStatus.QUEUED, index=True
    )
    url: Mapped[str | None] = mapped_column(String(1024))
    logs: Mapped[str | None] = mapped_column(Text)
    rolled_back_from: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    duration_seconds: Mapped[float | None] = mapped_column(Float)

    project: Mapped[Project] = relationship(back_populates="deployments")


class MemoryRecord(Base, TimestampMixin):
    """Long-term, vector-indexed knowledge for cross-project learning."""

    __tablename__ = "memory_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[MemoryKind] = mapped_column(Enum(MemoryKind, native_enum=False), index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)
    importance: Mapped[float] = mapped_column(Float, default=0.5)  # 0..1, drives retention
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding: Mapped[list[float]] = mapped_column(Vector(settings.embedding_dimensions))

    __table_args__ = (
        Index(
            "ix_memory_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class Approval(Base, TimestampMixin):
    """A human-in-the-loop gate for high-risk actions."""

    __tablename__ = "approvals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[ApprovalKind] = mapped_column(Enum(ApprovalKind, native_enum=False))
    subject_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # PR/deployment id
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    approved: Mapped[bool | None] = mapped_column(Boolean)  # None=pending
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    project: Mapped[Project] = relationship(back_populates="approvals")


class ActivityEvent(Base):
    """Append-only event stream powering the dashboard timeline."""

    __tablename__ = "activity_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    agent_role: Mapped[AgentRole | None] = mapped_column(Enum(AgentRole, native_enum=False))
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


# ---------------------------------------------------------------------------
# Knowledge graph — RiMo's structural "brain" for a project.
# ---------------------------------------------------------------------------
class GraphNode(Base, TimestampMixin):
    """A vertex in the project knowledge graph (file, class, function, table...)."""

    __tablename__ = "graph_nodes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[NodeKind] = mapped_column(Enum(NodeKind, native_enum=False), index=True)
    # Stable identity within a project, e.g. "frontend/Timeline.tsx::class:Timeline".
    key: Mapped[str] = mapped_column(String(1024), index=True)
    name: Mapped[str] = mapped_column(String(512))
    path: Mapped[str | None] = mapped_column(String(1024))  # source file path
    signature: Mapped[str | None] = mapped_column(Text)     # function/class signature
    summary: Mapped[str | None] = mapped_column(Text)       # one-line semantic summary
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Graph-derived importance (PageRank-style centrality), 0..1.
    centrality: Mapped[float] = mapped_column(Float, default=0.0)

    __table_args__ = (UniqueConstraint("project_id", "key", name="uq_graph_node_key"),)


class GraphEdge(Base):
    """A directed relationship between two knowledge-graph nodes."""

    __tablename__ = "graph_edges"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("graph_nodes.id", ondelete="CASCADE"), index=True
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("graph_nodes.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[EdgeKind] = mapped_column(Enum(EdgeKind, native_enum=False), index=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("source_id", "target_id", "kind", name="uq_graph_edge"),
    )


# ---------------------------------------------------------------------------
# Self-evolving prompts — variants compete on measured success rate.
# ---------------------------------------------------------------------------
class PromptVariant(Base, TimestampMixin):
    """A candidate prompt for a given agent role, with live performance stats."""

    __tablename__ = "prompt_variants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    role: Mapped[AgentRole] = mapped_column(Enum(AgentRole, native_enum=False), index=True)
    name: Mapped[str] = mapped_column(String(128))
    template: Mapped[str] = mapped_column(Text, nullable=False)
    # Lineage: which variant this was mutated from (for the evolution loop).
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompt_variants.id", ondelete="SET NULL")
    )
    generation: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Running tallies updated after each execution.
    trials: Mapped[int] = mapped_column(Integer, default=0)
    successes: Mapped[int] = mapped_column(Integer, default=0)
    total_reward: Mapped[float] = mapped_column(Float, default=0.0)  # sum of per-run rewards

    __table_args__ = (UniqueConstraint("role", "name", name="uq_prompt_variant_name"),)

    @property
    def success_rate(self) -> float:
        return self.successes / self.trials if self.trials else 0.0


class PromptExecution(Base):
    """One use of a prompt variant, with its outcome — the evolution training set."""

    __tablename__ = "prompt_executions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    variant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prompt_variants.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    success: Mapped[bool] = mapped_column(Boolean)
    reward: Mapped[float] = mapped_column(Float, default=0.0)  # 0..1 quality signal
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


# ---------------------------------------------------------------------------
# Economic reasoning — a ledger of every model call's cost.
# ---------------------------------------------------------------------------
class ModelCall(Base):
    """A single LLM call with its routed model, token counts, and dollar cost."""

    __tablename__ = "model_calls"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    agent_role: Mapped[AgentRole | None] = mapped_column(Enum(AgentRole, native_enum=False))
    provider: Mapped[ModelProvider] = mapped_column(Enum(ModelProvider, native_enum=False))
    model: Mapped[str] = mapped_column(String(128), index=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    purpose: Mapped[str | None] = mapped_column(String(64))  # routing tier / debate stage
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


# ---------------------------------------------------------------------------
# Failure recovery — incident records for autonomous diagnosis & rollback.
# ---------------------------------------------------------------------------
class Incident(Base, TimestampMixin):
    """An autonomous incident: a failure RiMo diagnosed, recovered, or escalated."""

    __tablename__ = "incidents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    title: Mapped[str] = mapped_column(String(512))
    status: Mapped[IncidentStatus] = mapped_column(
        Enum(IncidentStatus, native_enum=False), default=IncidentStatus.OPEN, index=True
    )
    trigger: Mapped[str] = mapped_column(String(128))  # what failed: build, test, deploy...
    diagnosis: Mapped[str | None] = mapped_column(Text)
    resolution: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    timeline: Mapped[list] = mapped_column(JSONB, default=list)  # ordered recovery steps


class RefreshToken(Base):
    """A hashed, revocable refresh token for the rotation-based auth flow.

    Only the SHA-256 hash of the token is stored, so a database leak does not
    expose usable tokens. Revocation = deleting (or marking) the row, which the
    access-token path cannot do on its own.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
