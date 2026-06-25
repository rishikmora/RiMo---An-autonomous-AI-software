"""Multi-repository swarm coordination.

A serious product is rarely one repo. RiMo can manage several repositories —
frontend, backend, AI, infra, mobile, shared libraries — as a single coordinated
system. This module is the coordination layer:

  * **Registration** of repos under a project, each with a role and declared
    cross-repo dependencies.
  * **Work ordering**: when a change spans repos, dependencies are respected
    (you build the shared types before the backend that imports them, the
    backend before the frontend that calls it) via a topological sort over the
    declared dependency graph.
  * **Cross-repo context** so an agent working in one repo knows what the others
    expose (their roles, languages, and public surface).

The swarm does not weaken any safety gate: each repo's changes still flow through
the normal review → QA → security → approval pipeline. Coordination decides
*order and context*, not whether something ships.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import Repository
from app.models.enums import RepoRole

logger = get_logger(__name__)


@dataclass
class CrossRepoPlan:
    """An ordered plan for a change that spans multiple repositories."""

    ordered_repos: list[str]          # full_names, dependency-respecting order
    rationale: list[str]              # human-readable ordering reasons
    has_cycle: bool = False


class RepoSwarm:
    """Coordinates a project's repositories as one system."""

    async def register(
        self,
        session: AsyncSession,
        *,
        project_id: uuid.UUID,
        full_name: str,
        role: RepoRole,
        url: str | None = None,
        default_branch: str = "main",
        primary_language: str | None = None,
        depends_on: list[str] | None = None,
    ) -> Repository:
        """Add (or update) a repository in the project's swarm."""
        existing = (
            await session.execute(
                select(Repository).where(
                    Repository.project_id == project_id,
                    Repository.full_name == full_name,
                )
            )
        ).scalar_one_or_none()
        meta = {"depends_on": depends_on or []}
        if existing:
            existing.role = role
            existing.url = url
            existing.default_branch = default_branch
            existing.primary_language = primary_language
            existing.meta = meta
            await session.flush()
            return existing
        repo = Repository(
            project_id=project_id,
            role=role,
            full_name=full_name,
            url=url,
            default_branch=default_branch,
            primary_language=primary_language,
            meta=meta,
        )
        session.add(repo)
        await session.flush()
        logger.info("repo_registered", project=str(project_id), repo=full_name, role=role.value)
        return repo

    async def list_repos(
        self, session: AsyncSession, *, project_id: uuid.UUID
    ) -> list[Repository]:
        return list(
            (
                await session.execute(
                    select(Repository).where(Repository.project_id == project_id)
                )
            ).scalars().all()
        )

    async def plan_cross_repo_change(
        self, session: AsyncSession, *, project_id: uuid.UUID, repos: list[str] | None = None
    ) -> CrossRepoPlan:
        """Order a set of repos so dependencies are built before dependents.

        Uses the declared ``depends_on`` (by role) on each repo to topologically
        sort. A dependency cycle is reported rather than silently mis-ordered.
        """
        all_repos = await self.list_repos(session, project_id=project_id)
        by_name = {r.full_name: r for r in all_repos}
        by_role: dict[str, list[str]] = {}
        for r in all_repos:
            by_role.setdefault(r.role.value, []).append(r.full_name)

        target_names = repos or [r.full_name for r in all_repos]
        targets = [by_name[n] for n in target_names if n in by_name]

        # Build a dependency edge set among the targets: repo -> repos it depends on.
        deps: dict[str, set[str]] = {r.full_name: set() for r in targets}
        for r in targets:
            for dep_role in r.meta.get("depends_on", []):
                for dep_name in by_role.get(dep_role, []):
                    if dep_name in deps and dep_name != r.full_name:
                        deps[r.full_name].add(dep_name)

        ordered, rationale, has_cycle = _toposort(deps)
        # Translate ordering into human-readable reasons.
        reasons: list[str] = []
        for name in ordered:
            d = deps.get(name, set())
            if d:
                reasons.append(f"{name} after {', '.join(sorted(d))} (depends on them)")
            else:
                reasons.append(f"{name} has no in-set dependencies")
        if has_cycle:
            reasons.append("⚠ dependency cycle detected; order is best-effort")

        logger.info(
            "cross_repo_plan",
            project=str(project_id),
            repos=len(ordered),
            cycle=has_cycle,
        )
        return CrossRepoPlan(ordered_repos=ordered, rationale=reasons, has_cycle=has_cycle)

    async def context_block(
        self, session: AsyncSession, *, project_id: uuid.UUID, current_repo: str | None = None
    ) -> str:
        """Render a prompt block describing the whole swarm for an agent.

        Gives an agent working in one repo awareness of the others — their roles,
        languages, and how they relate — so cross-repo changes are coherent.
        """
        repos = await self.list_repos(session, project_id=project_id)
        if not repos:
            return "This project has a single repository."
        lines = ["# Repositories in this system"]
        for r in sorted(repos, key=lambda x: x.role.value):
            marker = "  <- you are here" if r.full_name == current_repo else ""
            deps = r.meta.get("depends_on", [])
            dep_str = f" (depends on: {', '.join(deps)})" if deps else ""
            lang = f" [{r.primary_language}]" if r.primary_language else ""
            lines.append(f"- {r.role.value}: {r.full_name}{lang}{dep_str}{marker}")
        lines.append(
            "\nWhen a change spans repositories, respect these dependencies and keep "
            "cross-repo contracts (API shapes, shared types) consistent."
        )
        return "\n".join(lines)


def _toposort(deps: dict[str, set[str]]) -> tuple[list[str], list[str], bool]:
    """Kahn's algorithm. Returns (order, [], has_cycle).

    ``deps[x]`` is the set of nodes x depends on (must come before x). The
    returned order places dependencies first.
    """
    # in-degree = number of unmet dependencies.
    remaining = {n: set(d) for n, d in deps.items()}
    order: list[str] = []
    # Stable: process nodes with no remaining deps in sorted order.
    while True:
        ready = sorted(n for n, d in remaining.items() if not d)
        if not ready:
            break
        for n in ready:
            order.append(n)
            del remaining[n]
            for d in remaining.values():
                d.discard(n)
    has_cycle = bool(remaining)
    if has_cycle:
        # Append the cyclic remainder in a deterministic order so we still return
        # a usable (if imperfect) sequence.
        order.extend(sorted(remaining.keys()))
    return order, [], has_cycle


repo_swarm = RepoSwarm()
