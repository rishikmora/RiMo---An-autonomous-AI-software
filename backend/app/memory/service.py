"""Long-term memory subsystem (the RiMo Memory agent's substrate).

Stores architectural decisions, fixed bugs, user preferences, project facts,
and successful implementations as embedded `MemoryRecord` rows, and retrieves
them by cosine similarity using pgvector's HNSW index.

`importance` and `access_count` feed a simple decay policy so the store stays
useful rather than unbounded.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models import MemoryRecord
from app.models.enums import MemoryKind
from app.services.embeddings import EmbeddingProvider, get_embedding_provider

logger = get_logger(__name__)


class MemoryService:
    """CRUD + semantic recall over the vector-indexed knowledge base."""

    def __init__(self, embedder: EmbeddingProvider | None = None) -> None:
        self._embedder = embedder or get_embedding_provider()

    async def remember(
        self,
        session: AsyncSession,
        *,
        kind: MemoryKind,
        title: str,
        content: str,
        project_id: uuid.UUID | None = None,
        importance: float = 0.5,
        meta: dict | None = None,
    ) -> MemoryRecord:
        """Embed and persist a new memory."""
        embedding = await self._embedder.embed(f"{title}\n\n{content}")
        record = MemoryRecord(
            project_id=project_id,
            kind=kind,
            title=title,
            content=content,
            importance=max(0.0, min(1.0, importance)),
            meta=meta or {},
            embedding=embedding,
        )
        session.add(record)
        await session.flush()
        logger.info("memory_stored", kind=kind.value, title=title[:60], id=str(record.id))
        return record

    async def recall(
        self,
        session: AsyncSession,
        *,
        query: str,
        project_id: uuid.UUID | None = None,
        kinds: list[MemoryKind] | None = None,
        top_k: int | None = None,
    ) -> list[tuple[MemoryRecord, float]]:
        """Return the most semantically similar memories with similarity scores.

        Scoping: project-specific memories are preferred, but global memories
        (project_id IS NULL) are always eligible so cross-project lessons
        transfer.
        """
        top_k = top_k or settings.memory_top_k
        query_vec = await self._embedder.embed(query)

        # cosine distance operator <=> ; similarity = 1 - distance
        distance = MemoryRecord.embedding.cosine_distance(query_vec).label("distance")
        stmt = select(MemoryRecord, distance)

        if project_id is not None:
            stmt = stmt.where(
                (MemoryRecord.project_id == project_id) | (MemoryRecord.project_id.is_(None))
            )
        if kinds:
            stmt = stmt.where(MemoryRecord.kind.in_(kinds))

        stmt = stmt.order_by(distance).limit(top_k)
        rows = (await session.execute(stmt)).all()

        results: list[tuple[MemoryRecord, float]] = []
        ids: list[uuid.UUID] = []
        for record, dist in rows:
            results.append((record, 1.0 - float(dist)))
            ids.append(record.id)

        if ids:  # bump access counters for retention scoring
            await session.execute(
                text(
                    "UPDATE memory_records SET access_count = access_count + 1 "
                    "WHERE id = ANY(:ids)"
                ),
                {"ids": ids},
            )
        return results

    async def build_context_block(
        self,
        session: AsyncSession,
        *,
        query: str,
        project_id: uuid.UUID | None = None,
        top_k: int | None = None,
    ) -> str:
        """Render recalled memories into a prompt-ready context block."""
        hits = await self.recall(session, query=query, project_id=project_id, top_k=top_k)
        if not hits:
            return "No relevant prior knowledge found."
        lines = ["# Relevant prior knowledge", ""]
        for record, sim in hits:
            if sim < 0.3:  # ignore weak matches to avoid distraction
                continue
            lines.append(f"## {record.title}  (relevance {sim:.0%}, {record.kind.value})")
            lines.append(record.content.strip())
            lines.append("")
        return "\n".join(lines).strip()

    async def prune(self, session: AsyncSession, *, keep_top: int = 5000) -> int:
        """Decay-based pruning: drop the least valuable memories when over cap.

        Value = importance weighted by recency and access frequency.
        """
        result = await session.execute(
            text(
                """
                WITH ranked AS (
                    SELECT id,
                           (importance * 0.6
                            + LEAST(access_count, 50) / 50.0 * 0.2
                            + EXP(-EXTRACT(EPOCH FROM (now() - created_at)) / 2592000.0) * 0.2
                           ) AS score
                    FROM memory_records
                )
                DELETE FROM memory_records
                WHERE id IN (
                    SELECT id FROM ranked ORDER BY score DESC OFFSET :keep
                )
                """
            ),
            {"keep": keep_top},
        )
        deleted = result.rowcount or 0
        if deleted:
            logger.info("memory_pruned", deleted=deleted)
        return deleted
