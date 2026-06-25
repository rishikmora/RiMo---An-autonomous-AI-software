"""Tests for global shared memory, graph persistence, and impact analysis.

These exercise the cross-project intelligence layer (#3) and the knowledge-graph
blast-radius query (#6) against a real Postgres, skipping cleanly when no
database is reachable. Includes a regression test for the zero-edges bug: the
graph used to persist no edges at all because node ids were read before flush.
"""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import func, select, text, update

from app.db.session import Base, engine, session_scope
from app.memory.global_memory import global_memory
from app.memory.service import MemoryService
from app.models import GraphEdge, MemoryRecord, Project, User
from app.models.enums import MemoryKind
from app.orchestration.graph import knowledge_graph

pytestmark = pytest.mark.asyncio


async def _db() -> bool:
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.fixture(autouse=True)
async def _schema():
    if not await _db():
        pytest.skip("database not available")
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    yield


async def _project(session) -> Project:
    u = User(email=f"int-{uuid.uuid4().hex[:8]}@rimo.example", hashed_password="x")
    session.add(u)
    await session.flush()
    p = Project(owner_id=u.id, name="Int", slug=f"int-{uuid.uuid4().hex[:8]}", objectives={})
    session.add(p)
    await session.flush()
    return p


def _self_corpus() -> dict[str, str]:
    files: dict[str, str] = {}
    for root, dirs, fnames in os.walk("app"):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in fnames:
            if f.endswith(".py"):
                fp = os.path.join(root, f)
                with open(fp) as fh:
                    files[fp] = fh.read()
    return files


# --- global shared memory ---------------------------------------------------
class TestGlobalMemory:
    async def test_reusable_lesson_is_a_candidate(self) -> None:
        async with session_scope() as s:
            p = await _project(s)
            m = MemoryService()
            rec = await m.remember(
                s, kind=MemoryKind.BUG_FIX, title="Pool fix",
                content="Bound the pool.", project_id=p.id, importance=0.8,
            )
            await s.execute(update(MemoryRecord).where(MemoryRecord.id == rec.id).values(access_count=3))
            await s.flush()
            cands = await global_memory.candidates(s, project_id=p.id)
            assert any(c.id == rec.id for c in cands)

    async def test_unused_lesson_is_not_a_candidate(self) -> None:
        async with session_scope() as s:
            p = await _project(s)
            m = MemoryService()
            # access_count stays 0 -> below the reuse threshold.
            await m.remember(
                s, kind=MemoryKind.BUG_FIX, title="One-off",
                content="Local quirk.", project_id=p.id, importance=0.8,
            )
            cands = await global_memory.candidates(s, project_id=p.id)
            assert cands == []

    async def test_project_fact_never_promotable(self) -> None:
        async with session_scope() as s:
            p = await _project(s)
            m = MemoryService()
            rec = await m.remember(
                s, kind=MemoryKind.PROJECT_FACT, title="Repo name",
                content="This project is called X.", project_id=p.id, importance=0.9,
            )
            await s.execute(update(MemoryRecord).where(MemoryRecord.id == rec.id).values(access_count=9))
            await s.flush()
            cands = await global_memory.candidates(s, project_id=p.id)
            assert cands == []  # PROJECT_FACT is excluded by kind

    async def test_promotion_creates_global_memory(self) -> None:
        async with session_scope() as s:
            p = await _project(s)
            m = MemoryService()
            rec = await m.remember(
                s, kind=MemoryKind.LESSON_LEARNED, title="Redis pooling",
                content="Use a bounded pool and a context manager.",
                project_id=p.id, importance=0.8,
            )
            await s.execute(update(MemoryRecord).where(MemoryRecord.id == rec.id).values(access_count=4))
            await s.flush()

            async def generalizer(title, content):
                return {"general": True, "portable_title": f"[General] {title}",
                        "portable_content": content, "tags": ["redis"]}

            result = await global_memory.promote_project(s, project_id=p.id, generalizer=generalizer)
            assert result.promoted == 1

            # A global (project_id IS NULL) memory now exists.
            globals_count = (
                await s.execute(
                    select(func.count()).select_from(MemoryRecord).where(MemoryRecord.project_id.is_(None))
                )
            ).scalar_one()
            assert globals_count >= 1
            # Source is marked promoted so it won't be re-promoted.
            src = await s.get(MemoryRecord, rec.id)
            assert src.meta.get("promoted") is True

    async def test_non_general_lesson_not_promoted(self) -> None:
        async with session_scope() as s:
            p = await _project(s)
            m = MemoryService()
            rec = await m.remember(
                s, kind=MemoryKind.LESSON_LEARNED, title="Project-specific thing",
                content="In OUR app, the foo module does bar.", project_id=p.id, importance=0.8,
            )
            await s.execute(update(MemoryRecord).where(MemoryRecord.id == rec.id).values(access_count=3))
            await s.flush()

            async def generalizer(title, content):
                return {"general": False}

            result = await global_memory.promote_project(s, project_id=p.id, generalizer=generalizer)
            assert result.promoted == 0


# --- knowledge graph persistence + impact -----------------------------------
class TestGraphPersistenceAndImpact:
    async def test_rebuild_persists_edges(self) -> None:
        """Regression: the graph must persist edges, not silently drop them all."""
        async with session_scope() as s:
            p = await _project(s)
            stats = await knowledge_graph.rebuild(s, project_id=p.id, files=_self_corpus())
            assert stats["nodes"] > 0
            assert stats["edges"] > 0, "edges must persist (zero-edges regression)"
            await s.flush()

            # Edges are actually in the database (the whole point of the fix).
            db_edges = (
                await s.execute(
                    select(func.count()).select_from(GraphEdge).where(GraphEdge.project_id == p.id)
                )
            ).scalar_one()
            assert db_edges > 0
            # The reported count matches what was persisted.
            assert db_edges == stats["edges"]

    async def test_centrality_is_populated(self) -> None:
        async with session_scope() as s:
            p = await _project(s)
            await knowledge_graph.rebuild(s, project_id=p.id, files=_self_corpus())
            central = await knowledge_graph.most_central(s, project_id=p.id, limit=5)
            assert central
            # With edges present, the top node has non-zero centrality.
            assert central[0].centrality > 0

    async def test_impact_analysis_returns_structure(self) -> None:
        async with session_scope() as s:
            p = await _project(s)
            await knowledge_graph.rebuild(s, project_id=p.id, files=_self_corpus())
            # Pick any function node that has callers.
            from app.models import GraphNode

            node = (
                await s.execute(
                    select(GraphNode).where(
                        GraphNode.project_id == p.id, GraphNode.kind == "function"
                    ).limit(1)
                )
            ).scalar_one_or_none()
            assert node is not None
            impact = await knowledge_graph.impact_analysis(s, project_id=p.id, node_key=node.key)
            # Shape is always well-formed even when nothing depends on the node.
            assert "total" in impact and "risk" in impact and "by_depth" in impact

    async def test_impact_unknown_node(self) -> None:
        async with session_scope() as s:
            p = await _project(s)
            await knowledge_graph.rebuild(s, project_id=p.id, files=_self_corpus())
            impact = await knowledge_graph.impact_analysis(
                s, project_id=p.id, node_key="file:does/not/exist.py"
            )
            assert impact["node"] is None
            assert impact["total"] == 0
