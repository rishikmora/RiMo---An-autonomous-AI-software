#!/usr/bin/env python3
"""Reproducible crash-recovery demonstration.

Proves RiMo's headline resilience claim — "self-heals from a worker crash
mid-task" — as a runnable experiment, not an assertion. It:

  1. creates a project with a READY task,
  2. simulates a worker that crashes *while holding the task* (sets it
     IN_PROGRESS with a lease, then "dies" without finishing),
  3. shows the task is stuck,
  4. runs a fresh worker's lease-reclaim sweep,
  5. shows the task returned to READY and is picked up again.

Run against a Postgres with pgvector:

    DATABASE_URL=postgresql+asyncpg://rimo@127.0.0.1:5432/rimo \\
    SECRET_KEY=$(openssl rand -hex 32) ANTHROPIC_API_KEY=x DB_POOL_SIZE=0 \\
    python scripts/demo_crash_recovery.py

Output is a clear before/after timeline you can paste into a report.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.db.session import Base, engine, session_scope
from app.models import Project, Task, User
from app.models.enums import Priority, ProjectStatus, TaskKind, TaskStatus


def log(step: str, detail: str) -> None:
    print(f"  [{datetime.now(UTC).strftime('%H:%M:%S')}] {step:18s} {detail}")


async def main() -> None:
    print("\n=== RiMo crash-recovery demonstration ===\n")

    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)

    # 1) Set up a project with one READY task.
    async with session_scope() as session:
        user = User(email=f"demo-{uuid.uuid4().hex[:6]}@rimo.example", hashed_password="x")
        session.add(user)
        await session.flush()
        project = Project(
            owner_id=user.id, name="Crash Demo", slug=f"crash-{uuid.uuid4().hex[:6]}",
            status=ProjectStatus.ACTIVE, is_running=True, objectives={},
        )
        session.add(project)
        await session.flush()
        task = Task(
            project_id=project.id, title="Implement feature X",
            kind=TaskKind.FEATURE, status=TaskStatus.READY, priority=Priority.HIGH,
            complexity=3, acceptance_criteria=["works"],
        )
        session.add(task)
        await session.flush()
        task_id = task.id
        log("setup", f"project + task created; task is {task.status.value.upper()}")

    # 2) Simulate a worker claiming the task then crashing mid-flight.
    async with session_scope() as session:
        t = await session.get(Task, task_id)
        t.status = TaskStatus.IN_PROGRESS
        t.attempts += 1
        t.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)  # already expired => crashed long enough ago
        await session.flush()
        log("worker_crash", f"worker claimed task then died; task stuck {t.status.value.upper()}, lease expired")

    # 3) Show it's stuck.
    async with session_scope() as session:
        t = await session.get(Task, task_id)
        assert t.status == TaskStatus.IN_PROGRESS
        log("observe", f"task is still {t.status.value.upper()} (a naive system would hang here forever)")

    # 4) A fresh worker runs its lease-reclaim sweep.
    from app.orchestration.worker import Worker

    log("recovery", "fresh worker starts; running lease-reclaim sweep...")
    await Worker()._reclaim_expired_leases()

    # 5) Show it's been reclaimed.
    async with session_scope() as session:
        t = await session.get(Task, task_id)
        ok = t.status == TaskStatus.READY and t.lease_expires_at is None
        log("reclaimed", f"task is now {t.status.value.upper()}, lease cleared — ready to retry")
        print()
        if ok:
            print("  RESULT: ✅ self-healed. The stuck task was automatically reclaimed.")
            print(f"          (attempts={t.attempts}; the next worker cycle will pick it up)\n")
        else:
            print("  RESULT: ❌ unexpected state\n")
            raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
