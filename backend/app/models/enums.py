"""Shared enumerations for the RiMo domain model."""
from __future__ import annotations

import enum


class AgentRole(str, enum.Enum):
    """The ten specialist agent roles that constitute the RiMo company."""

    CEO = "ceo"
    RESEARCH = "research"
    PLANNER = "planner"
    ARCHITECT = "architect"
    BUILDER = "builder"
    REVIEWER = "reviewer"
    QA = "qa"
    SECURITY = "security"
    DEVOPS = "devops"
    MEMORY = "memory"


class AgentStatus(str, enum.Enum):
    IDLE = "idle"
    THINKING = "thinking"
    WORKING = "working"
    WAITING = "waiting"  # blocked on human approval or dependency
    ERROR = "error"
    OFFLINE = "offline"


class ProjectStatus(str, enum.Enum):
    DRAFT = "draft"
    ANALYZING = "analyzing"
    ACTIVE = "active"
    PAUSED = "paused"
    BLOCKED = "blocked"
    ARCHIVED = "archived"


class TaskStatus(str, enum.Enum):
    BACKLOG = "backlog"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    BLOCKED = "blocked"
    DONE = "done"
    CANCELLED = "cancelled"
    FAILED = "failed"


class TaskKind(str, enum.Enum):
    FEATURE = "feature"
    BUGFIX = "bugfix"
    REFACTOR = "refactor"
    TEST = "test"
    SECURITY = "security"
    PERFORMANCE = "performance"
    DOCS = "docs"
    INFRA = "infra"
    RESEARCH = "research"


class Priority(int, enum.Enum):
    CRITICAL = 0
    HIGH = 1
    MEDIUM = 2
    LOW = 3


class PullRequestStatus(str, enum.Enum):
    OPEN = "open"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"
    MERGED = "merged"
    CLOSED = "closed"


class DeploymentStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class MemoryKind(str, enum.Enum):
    ARCHITECTURE_DECISION = "architecture_decision"
    BUG_FIX = "bug_fix"
    USER_PREFERENCE = "user_preference"
    PROJECT_FACT = "project_fact"
    SUCCESSFUL_IMPLEMENTATION = "successful_implementation"
    LESSON_LEARNED = "lesson_learned"


class ApprovalKind(str, enum.Enum):
    MERGE = "merge"
    DEPLOY = "deploy"
    REPO_DELETE = "repo_delete"
    DESTRUCTIVE_MIGRATION = "destructive_migration"
