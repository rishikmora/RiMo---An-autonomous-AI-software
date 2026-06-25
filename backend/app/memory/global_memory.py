"""Global shared memory — the compounding intelligence layer.

Per-project memory is necessary but not sufficient. The thing that makes a fleet
of projects smarter *together* is promoting genuinely general lessons (a Redis
connection-pool fix, a safe migration pattern, a Next.js hydration gotcha) out of
the project where they were learned and into a shared layer that every project
recalls.

The storage already supports this: a memory with ``project_id IS NULL`` is global
and is always eligible during recall (see ``MemoryService.recall``). What was
missing is the *promotion* decision. This module supplies it:

  * **Heuristic gate** — only memories of generalizable kinds, with enough
    independent reuse (access_count) and importance, are candidates.
  * **Model judgement** — a candidate is promoted only if the model judges it
    project-agnostic (no project-specific names, paths, or business logic), and
    it rewrites the lesson in portable form before promotion.

Promotion is conservative by design: a wrong global memory pollutes every
project, so the bar is deliberately high.
"""
from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.memory.service import MemoryService
from app.models import MemoryRecord
from app.models.enums import MemoryKind

logger = get_logger(__name__)

# Kinds that can ever be general. Project facts and user preferences never are.
_PROMOTABLE_KINDS = {
    MemoryKind.LESSON_LEARNED,
    MemoryKind.BUG_FIX,
    MemoryKind.SUCCESSFUL_IMPLEMENTATION,
    MemoryKind.ARCHITECTURE_DECISION,
}

# Generalizer: async (title, content) -> {"general": bool, "portable_title",
# "portable_content", "tags": [...]}  — typically a model call.
Generalizer = Callable[[str, str], Awaitable[dict]]


@dataclass
class PromotionResult:
    examined: int
    promoted: int
    promoted_titles: list[str]


class GlobalMemoryService:
    """Promotes generalizable project memories into the shared layer."""

    def __init__(self, memory: MemoryService | None = None) -> None:
        self._memory = memory or MemoryService()

    async def candidates(
        self,
        session: AsyncSession,
        *,
        project_id: uuid.UUID,
        min_access: int = 2,
        min_importance: float = 0.6,
    ) -> list[MemoryRecord]:
        """Project memories that clear the heuristic bar for promotion.

        Requires a generalizable kind, evidence of independent reuse
        (``access_count``), and sufficient importance. ``access_count >= 2``
        means the lesson helped on more than the task that created it.
        """
        rows = (
            await session.execute(
                select(MemoryRecord).where(
                    MemoryRecord.project_id == project_id,
                    MemoryRecord.kind.in_(_PROMOTABLE_KINDS),
                    MemoryRecord.access_count >= min_access,
                    MemoryRecord.importance >= min_importance,
                    # not already promoted: the JSONB `promoted` key is absent or
                    # not true. coalesce handles records that never set it.
                    func.coalesce(
                        MemoryRecord.meta["promoted"].as_boolean(), False
                    ).is_(False),
                )
            )
        ).scalars().all()
        return list(rows)

    async def promote_project(
        self,
        session: AsyncSession,
        *,
        project_id: uuid.UUID,
        generalizer: Generalizer,
        max_promotions: int = 10,
    ) -> PromotionResult:
        """Examine a project's reusable memories and promote the general ones.

        For each candidate, the generalizer judges portability and rewrites the
        lesson in project-agnostic form. Promotion creates a *new* global
        memory (so the original project-scoped record is preserved) and marks the
        source as promoted to avoid re-promoting it.
        """
        candidates = await self.candidates(session, project_id=project_id)
        promoted_titles: list[str] = []

        for record in candidates:
            if len(promoted_titles) >= max_promotions:
                break
            try:
                verdict = await generalizer(record.title, record.content)
            except Exception as exc:  # noqa: BLE001 - generalization is best-effort
                logger.warning("generalize_failed", memory=str(record.id), error=str(exc))
                continue

            if not verdict.get("general"):
                # Mark examined-but-not-general so we don't reconsider forever.
                record.meta = {**record.meta, "promotion_checked": True}
                continue

            title = str(verdict.get("portable_title") or record.title)[:512]
            content = str(verdict.get("portable_content") or record.content)
            tags = verdict.get("tags", [])

            # Create the global memory (project_id=None) via the embedder path.
            await self._memory.remember(
                session,
                kind=record.kind,
                title=title,
                content=content,
                project_id=None,
                importance=min(1.0, record.importance + 0.1),
                meta={"origin_project": str(project_id), "tags": tags, "promoted_from": str(record.id)},
            )
            record.meta = {**record.meta, "promoted": True}
            promoted_titles.append(title)
            logger.info("memory_promoted", origin_project=str(project_id), title=title[:80])

        return PromotionResult(
            examined=len(candidates),
            promoted=len(promoted_titles),
            promoted_titles=promoted_titles,
        )

    async def global_stats(self, session: AsyncSession) -> dict:
        """Summary of the shared layer for the dashboard."""
        total = (
            await session.execute(
                select(func.count()).select_from(MemoryRecord).where(
                    MemoryRecord.project_id.is_(None)
                )
            )
        ).scalar_one()
        by_kind_rows = (
            await session.execute(
                select(MemoryRecord.kind, func.count())
                .where(MemoryRecord.project_id.is_(None))
                .group_by(MemoryRecord.kind)
            )
        ).all()
        most_used = (
            await session.execute(
                select(MemoryRecord)
                .where(MemoryRecord.project_id.is_(None))
                .order_by(MemoryRecord.access_count.desc())
                .limit(10)
            )
        ).scalars().all()
        return {
            "total_global_memories": total,
            "by_kind": {k.value: c for k, c in by_kind_rows},
            "most_reused": [
                {"title": m.title, "kind": m.kind.value, "reuse": m.access_count}
                for m in most_used
            ],
        }

    async def recall_global(
        self, session: AsyncSession, *, query: str, top_k: int = 10
    ) -> list[dict]:
        """Search only the shared layer (project-agnostic lessons)."""
        hits = await self._memory.recall(session, query=query, project_id=None, top_k=top_k)
        return [
            {"title": r.title, "kind": r.kind.value, "content": r.content, "relevance": round(sim, 3)}
            for r, sim in hits
            if r.project_id is None
        ]


global_memory = GlobalMemoryService()
