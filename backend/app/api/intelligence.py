"""Intelligence routes: knowledge graph, economics, prompts, incidents, and
the autonomous action triggers (startup bootstrap, research survey).

These endpoints surface the Tier 1–4 capability layer to the dashboard and to
operators. Read endpoints are safe; action endpoints kick off work that the
orchestrator/worker then advances.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_session
from app.models import (
    GraphEdge,
    GraphNode,
    Incident,
    ModelCall,
    User,
)
from app.models.enums import AgentRole
from app.orchestration.fleet import agent_marketplace, fleet_manager
from app.orchestration.refactor import refactor_analyzer
from app.security_helpers import resolve_project_for_user
from app.services.economics import economics
from app.services.prompts import prompt_service

router = APIRouter(tags=["intelligence"])


# --- Knowledge graph --------------------------------------------------------
@router.get("/projects/{project_id}/graph")
async def get_graph(
    project_id: uuid.UUID,
    kind: str | None = Query(None, description="filter by node kind"),
    limit: int = Query(500, le=2000),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Return the project knowledge graph (nodes + edges) for visualization."""
    await resolve_project_for_user(project_id, user, session)

    node_stmt = select(GraphNode).where(GraphNode.project_id == project_id)
    if kind:
        node_stmt = node_stmt.where(GraphNode.kind == kind)
    node_stmt = node_stmt.order_by(GraphNode.centrality.desc()).limit(limit)
    nodes = (await session.execute(node_stmt)).scalars().all()
    node_ids = {n.id for n in nodes}

    edges = (
        await session.execute(
            select(GraphEdge).where(GraphEdge.project_id == project_id)
        )
    ).scalars().all()
    # Only edges whose endpoints are both in the returned node set.
    edges = [e for e in edges if e.source_id in node_ids and e.target_id in node_ids]

    return {
        "nodes": [
            {
                "id": str(n.id),
                "kind": n.kind.value,
                "key": n.key,
                "name": n.name,
                "path": n.path,
                "centrality": round(n.centrality, 5),
                "summary": n.summary,
            }
            for n in nodes
        ],
        "edges": [
            {
                "source": str(e.source_id),
                "target": str(e.target_id),
                "kind": e.kind.value,
                "weight": e.weight,
            }
            for e in edges
        ],
        "stats": {"nodes": len(nodes), "edges": len(edges)},
    }


@router.get("/projects/{project_id}/graph/central")
async def central_nodes(
    project_id: uuid.UUID,
    limit: int = Query(15, le=100),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """The most load-bearing nodes — high blast radius if changed."""
    await resolve_project_for_user(project_id, user, session)
    rows = (
        await session.execute(
            select(GraphNode)
            .where(GraphNode.project_id == project_id)
            .order_by(GraphNode.centrality.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        {
            "name": n.name,
            "kind": n.kind.value,
            "path": n.path,
            "centrality": round(n.centrality, 5),
        }
        for n in rows
    ]


# --- Economics --------------------------------------------------------------
@router.get("/projects/{project_id}/economics")
async def get_economics(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Cost summary, unit economics, and routing-savings for the project."""
    await resolve_project_for_user(project_id, user, session)
    summary = await economics.project_summary(session, project_id=project_id)
    return summary.to_dict()


# --- Prompts (self-evolving) ------------------------------------------------
@router.get("/prompts/{role}")
async def prompt_leaderboard(
    role: AgentRole,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """Performance leaderboard of prompt variants for a role."""
    board = await prompt_service.leaderboard(session, role=role)
    return [
        {
            "name": v.name,
            "generation": v.generation,
            "active": v.active,
            "trials": v.trials,
            "successes": v.successes,
            "success_rate": round(v.success_rate, 3),
            "mean_reward": round(v.total_reward / v.trials, 3) if v.trials else 0.0,
        }
        for v in board
    ]


# --- Incidents (failure recovery) -------------------------------------------
@router.get("/projects/{project_id}/incidents")
async def list_incidents(
    project_id: uuid.UUID,
    limit: int = Query(50, le=200),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """Recent autonomous incidents with their recovery outcomes."""
    await resolve_project_for_user(project_id, user, session)
    rows = (
        await session.execute(
            select(Incident)
            .where(Incident.project_id == project_id)
            .order_by(Incident.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        {
            "id": str(i.id),
            "title": i.title,
            "trigger": i.trigger,
            "status": i.status.value,
            "attempts": i.attempts,
            "diagnosis": i.diagnosis,
            "resolution": i.resolution,
            "timeline": i.timeline,
            "created_at": i.created_at.isoformat(),
        }
        for i in rows
    ]


# --- Actions ----------------------------------------------------------------
@router.post("/projects/{project_id}/research", status_code=status.HTTP_202_ACCEPTED)
async def trigger_research(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Queue an autonomous research survey; the worker performs it next cycle."""
    project = await resolve_project_for_user(project_id, user, session)
    # Flag the project for a research pass; the worker picks this up.
    meta = dict(project.metrics or {})
    meta["research_requested"] = True
    project.metrics = meta
    await session.flush()
    return {"status": "queued", "project_id": str(project_id)}


@router.get("/projects/{project_id}/spend")
async def get_spend(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Total spend to date — a cheap endpoint for budget widgets."""
    await resolve_project_for_user(project_id, user, session)
    total = await economics.spend_to_date(session, project_id=project_id)
    recent = (
        await session.execute(
            select(ModelCall)
            .where(ModelCall.project_id == project_id)
            .order_by(ModelCall.created_at.desc())
            .limit(10)
        )
    ).scalars().all()
    return {
        "total_usd": round(total, 4),
        "recent_calls": [
            {
                "model": c.model,
                "provider": c.provider.value,
                "cost_usd": round(c.cost_usd, 5),
                "tokens": c.input_tokens + c.output_tokens,
                "purpose": c.purpose,
            }
            for c in recent
        ],
    }


# --- Architecture refactoring -----------------------------------------------
@router.get("/projects/{project_id}/smells")
async def get_smells(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """Architectural smells detected from the knowledge graph."""
    await resolve_project_for_user(project_id, user, session)
    smells = await refactor_analyzer.analyze(session, project_id=project_id)
    return [
        {
            "kind": s.kind,
            "node_name": s.node_name,
            "metric": s.metric,
            "severity": round(s.severity, 3),
            "suggestion": s.suggestion,
            "members": s.members,
        }
        for s in smells
    ]


# --- Agent marketplace ------------------------------------------------------
@router.get("/marketplace")
async def list_marketplace(
    user: User = Depends(get_current_user),
) -> list[dict]:
    """All hireable specialist agents in the marketplace."""
    return [
        {"slug": s.slug, "title": s.title, "expertise": s.expertise, "triggers": list(s.triggers)}
        for s in agent_marketplace.all()
    ]


@router.get("/projects/{project_id}/marketplace/recommended")
async def recommended_agents(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """Specialists recommended for this project based on its detected stack."""
    project = await resolve_project_for_user(project_id, user, session)
    return [
        {"slug": s.slug, "title": s.title, "expertise": s.expertise}
        for s in agent_marketplace.match(project)
    ]


# --- Fleet (RiMo OS) --------------------------------------------------------
@router.get("/fleet")
async def get_fleet(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Portfolio-wide health and attention ranking across all projects."""
    view = await fleet_manager.health(session, owner_id=user.id)
    return view.to_dict()
