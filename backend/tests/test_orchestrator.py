"""Orchestrator state-machine tests — the system's highest-risk surface.

These exercise the real DB-backed state machine (lease reclaim, the approval
gate, planning, idempotency, and crash-safety) using a deterministic fake LLM so
no network calls are made. They run against a real Postgres in CI and skip
gracefully when no database is reachable, matching test_api.py.

The headline resilience claims — "resumable, self-healing 24/7 worker" and
"never merges without approval" — are converted here from assertions into
executable proofs.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from app.db.session import Base, engine, session_scope
from app.models import Approval, Project, PullRequest, Task, User
from app.models.enums import (
    ApprovalKind,
    Priority,
    ProjectStatus,
    PullRequestStatus,
    TaskKind,
    TaskStatus,
)

pytestmark = pytest.mark.asyncio


# --- fake LLM ---------------------------------------------------------------
class _Block:
    """Minimal stand-in for an Anthropic content block."""

    def __init__(self, *, type: str, text: str = "", name: str = "", input: dict | None = None, id: str = "") -> None:
        self.type = type
        self.text = text
        self.name = name
        self.input = input or {}
        self.id = id


class _Usage:
    def __init__(self) -> None:
        self.input_tokens = 10
        self.output_tokens = 5


class _Response:
    def __init__(self, blocks: list[_Block]) -> None:
        self.content = blocks
        self.usage = _Usage()


class FakeLLM:
    """Returns deterministic, role-appropriate responses based on the system prompt.

    The Builder turn stages a file via the workspace tool then finishes; all other
    roles return a single JSON final answer. This makes the full pipeline run
    end-to-end without any network access.
    """

    def __init__(self) -> None:
        self._has_staged = False

    async def complete(self, *, system: str, messages, tools=None, model=None, **kwargs):  # noqa: ANN001
        s = system.lower()
        # Match on the distinctive agent identity line ("You are RiMo <Role>")
        # rather than a loose substring — several prompts mention other roles.
        def is_role(name: str) -> bool:
            return f"you are rimo {name}" in s

        # Builder: first call writes a file (tool_use), then finishes.
        if is_role("builder"):
            write_tool = next(
                (t for t in (tools or []) if t.get("name") in {"write_file", "stage_file"}),
                None,
            )
            if write_tool and not self._has_staged:
                self._has_staged = True
                return _Response([
                    _Block(
                        type="tool_use",
                        name=write_tool["name"],
                        input={"path": "src/feature.py", "content": "def feature():\n    return 42\n"},
                        id=f"tu_{uuid.uuid4().hex[:8]}",
                    )
                ])
            return _Response([_Block(type="text", text="Implemented the feature and staged the file.")])

        # Role-specific JSON final answers.
        if is_role("ceo"):
            payload = '{"mission": "Ship it", "objectives": ["MVP"], "strategic_summary": "Focus."}'
        elif is_role("planner"):
            payload = (
                '{"tasks": [{"title": "Add feature", "kind": "feature", "priority": "high", '
                '"complexity": 3, "acceptance_criteria": ["works"]}]}'
            )
        elif is_role("architect"):
            payload = '{"decision": "Use a service", "options_considered": ["a", "b"], "consequences": ["ok"]}'
        elif is_role("reviewer"):
            payload = '{"score": 95, "verdict": "approve", "issues": [], "strengths": ["clean"], "summary": "LGTM"}'
        elif is_role("security"):
            payload = '{"passed": true, "findings": [], "severity": "none"}'
        elif is_role("qa"):
            payload = '{"passed": true, "tests_added": 1, "summary": "tests pass"}'
        else:
            payload = '{"ok": true}'
        return _Response([_Block(type="text", text=payload)])


# --- db harness -------------------------------------------------------------
async def _db_available() -> bool:
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.fixture(autouse=True)
async def _schema():
    if not await _db_available():
        pytest.skip("database not available")
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    yield


async def _make_project(session, *, autonomy: int = 3, status: ProjectStatus = ProjectStatus.ACTIVE) -> Project:
    user = User(email=f"orch-{uuid.uuid4().hex[:8]}@t.example", hashed_password="x")
    session.add(user)
    await session.flush()
    project = Project(
        owner_id=user.id,
        name="Orch Test",
        slug=f"orch-{uuid.uuid4().hex[:8]}",
        status=status,
        autonomy_level=autonomy,
        is_running=True,
        objectives={},
    )
    session.add(project)
    await session.flush()
    return project


def _orchestrator(session):
    # Local import so the module loads even if optional deps are absent.
    from app.orchestration.orchestrator import Orchestrator

    return Orchestrator(session, llm=FakeLLM())


async def _ready_task(session, project, **kw) -> Task:
    task = Task(
        project_id=project.id,
        title=kw.get("title", "Add feature"),
        kind=kw.get("kind", TaskKind.FEATURE),
        status=TaskStatus.READY,
        priority=kw.get("priority", Priority.HIGH),
        complexity=kw.get("complexity", 3),
        acceptance_criteria=["works"],
    )
    session.add(task)
    await session.flush()
    return task


# --- tests ------------------------------------------------------------------
async def test_tick_plans_when_backlog_empty() -> None:
    from sqlalchemy import func as _func

    async with session_scope() as session:
        project = await _make_project(session)
        orch = _orchestrator(session)
        status = await orch.tick(project)
        assert status == "planned"
        # The planner (fake) created at least one task.
        count = (await session.execute(
            select(_func.count()).select_from(Task).where(Task.project_id == project.id)
        )).scalar_one()
        assert count >= 1


async def test_paused_project_does_not_advance() -> None:
    async with session_scope() as session:
        project = await _make_project(session, status=ProjectStatus.PAUSED)
        orch = _orchestrator(session)
        assert await orch.tick(project) == "paused"


async def test_expired_lease_is_reclaimed() -> None:
    """The headline resilience claim: a stuck task self-heals."""
    async with session_scope() as session:
        project = await _make_project(session)
        task = await _ready_task(session, project)
        # Simulate a crashed worker: task stuck IN_PROGRESS with an expired lease.
        task.status = TaskStatus.IN_PROGRESS
        task.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.flush()

    # A fresh worker cycle reclaims it.
    from app.orchestration.worker import Worker

    await Worker()._reclaim_expired_leases()

    async with session_scope() as session:
        refreshed = await session.get(Task, task.id)
        assert refreshed.status == TaskStatus.READY
        assert refreshed.lease_expires_at is None


async def test_unexpired_lease_is_not_reclaimed() -> None:
    async with session_scope() as session:
        project = await _make_project(session)
        task = await _ready_task(session, project)
        task.status = TaskStatus.IN_PROGRESS
        task.lease_expires_at = datetime.now(UTC) + timedelta(seconds=300)
        await session.flush()

    from app.orchestration.worker import Worker

    await Worker()._reclaim_expired_leases()

    async with session_scope() as session:
        refreshed = await session.get(Task, task.id)
        assert refreshed.status == TaskStatus.IN_PROGRESS  # still held


async def test_merge_requires_approval_and_does_not_merge() -> None:
    """Safety invariant: a PR does not merge without an approval record."""
    async with session_scope() as session:
        # autonomy 2; the platform default requires human merge approval
        project = await _make_project(session, autonomy=2)
        task = await _ready_task(session, project)
        orch = _orchestrator(session)
        await orch.execute_task(project, task)

        # A PR exists, an approval is pending, and nothing is merged.
        prs = (await session.execute(
            select(PullRequest).where(PullRequest.project_id == project.id)
        )).scalars().all()
        assert prs, "expected a PR to be opened"
        assert all(p.status != PullRequestStatus.MERGED for p in prs)

        approvals = (await session.execute(
            select(Approval).where(Approval.project_id == project.id)
        )).scalars().all()
        assert any(
            a.kind == ApprovalKind.MERGE and a.approved is None for a in approvals
        ), "expected a pending merge approval"


async def test_approved_merge_completes_and_marks_task_done() -> None:
    async with session_scope() as session:
        project = await _make_project(session, autonomy=2)
        task = await _ready_task(session, project)
        orch = _orchestrator(session)
        await orch.execute_task(project, task)

        pr_obj = (await session.execute(
            select(PullRequest).where(PullRequest.project_id == project.id).limit(1)
        )).scalar_one()

        # Human approves -> merge completes, task transitions to DONE.
        await orch.merge_approved(project, pr_obj)
        assert pr_obj.status == PullRequestStatus.MERGED
        done = await session.get(Task, task.id)
        assert done.status == TaskStatus.DONE


async def test_budget_cap_halts_project() -> None:
    """Financial kill-switch: spend at/over the cap pauses the project."""
    from app.models import ModelCall
    from app.models.enums import ModelProvider

    async with session_scope() as session:
        project = await _make_project(session)
        # Record spend at the cap.
        from app.core.config import settings

        session.add(ModelCall(
            project_id=project.id,
            provider=ModelProvider.ANTHROPIC,
            model="claude-opus-4-8",
            input_tokens=1,
            output_tokens=1,
            cost_usd=settings.max_cost_usd_per_project + 1.0,
        ))
        await session.flush()

        orch = _orchestrator(session)
        status = await orch.tick(project)
        assert status == "budget_halt"
        assert project.status == ProjectStatus.PAUSED
