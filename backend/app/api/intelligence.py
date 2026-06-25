"""Intelligence routes: knowledge graph, economics, prompts, incidents, and
the autonomous action triggers (startup bootstrap, research survey).

These endpoints surface the Tier 1–4 capability layer to the dashboard and to
operators. Read endpoints are safe; action endpoints kick off work that the
orchestrator/worker then advances.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_session
from app.memory.global_memory import global_memory
from app.models import (
    GraphEdge,
    GraphNode,
    Incident,
    ModelCall,
    User,
)
from app.models.enums import AgentRole, RepoRole
from app.orchestration.fleet import agent_marketplace, fleet_manager
from app.orchestration.graph import knowledge_graph
from app.orchestration.refactor import refactor_analyzer
from app.orchestration.swarm import repo_swarm
from app.security_helpers import resolve_project_for_user
from app.services.economics import economics
from app.services.prompts import prompt_service


class RepoCreate(BaseModel):
    full_name: str
    role: str
    url: str | None = None
    default_branch: str | None = "main"
    primary_language: str | None = None
    depends_on: list[str] | None = None

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


@router.get("/projects/{project_id}/graph/impact")
async def graph_impact(
    project_id: uuid.UUID,
    node_key: str = Query(..., description="key of the node being changed"),
    max_depth: int = Query(6, le=12),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """"What breaks if I change this?" — transitive blast radius of a node."""
    await resolve_project_for_user(project_id, user, session)
    return await knowledge_graph.impact_analysis(
        session, project_id=project_id, node_key=node_key, max_depth=max_depth
    )


# --- Global shared memory ---------------------------------------------------
@router.get("/memory/global")
async def global_memory_stats(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Stats on the cross-project shared intelligence layer."""
    return await global_memory.global_stats(session)


@router.get("/memory/global/search")
async def global_memory_search(
    q: str = Query(..., min_length=2),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """Search only the shared (project-agnostic) memory layer."""
    return await global_memory.recall_global(session, query=q, top_k=10)


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


class FeatureROIRequest(BaseModel):
    title: str
    monthly_cost_usd: float = 0.0
    expected_monthly_revenue_usd: float = 0.0
    build_cost_usd: float = 0.0
    strategic_value: float = 0.0
    confidence: float = 0.5


@router.post("/economics/roi")
async def evaluate_roi(
    body: FeatureROIRequest,
    user: User = Depends(get_current_user),
) -> dict:
    """Founder-style build/reject/defer decision for a proposed feature."""
    return economics.evaluate_feature_roi(
        title=body.title,
        monthly_cost_usd=body.monthly_cost_usd,
        expected_monthly_revenue_usd=body.expected_monthly_revenue_usd,
        build_cost_usd=body.build_cost_usd,
        strategic_value=body.strategic_value,
        confidence=body.confidence,
    )


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


# --- Multi-repository swarm --------------------------------------------------
@router.get("/projects/{project_id}/repos")
async def list_repos(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """All repositories coordinated under this project."""
    await resolve_project_for_user(project_id, user, session)
    repos = await repo_swarm.list_repos(session, project_id=project_id)
    return [
        {
            "id": str(r.id),
            "role": r.role.value,
            "full_name": r.full_name,
            "primary_language": r.primary_language,
            "default_branch": r.default_branch,
            "depends_on": r.meta.get("depends_on", []),
        }
        for r in repos
    ]


@router.post("/projects/{project_id}/repos", status_code=status.HTTP_201_CREATED)
async def add_repo(
    project_id: uuid.UUID,
    body: RepoCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Register a repository in the project's swarm."""
    await resolve_project_for_user(project_id, user, session)
    try:
        role = RepoRole(body.role)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"invalid role: {body.role}") from exc
    repo = await repo_swarm.register(
        session,
        project_id=project_id,
        full_name=body.full_name,
        role=role,
        url=body.url,
        default_branch=body.default_branch or "main",
        primary_language=body.primary_language,
        depends_on=body.depends_on or [],
    )
    return {"id": str(repo.id), "full_name": repo.full_name, "role": repo.role.value}


@router.get("/projects/{project_id}/repos/plan")
async def cross_repo_plan(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Dependency-respecting build order for a change spanning the swarm."""
    await resolve_project_for_user(project_id, user, session)
    plan = await repo_swarm.plan_cross_repo_change(session, project_id=project_id)
    return {
        "ordered_repos": plan.ordered_repos,
        "rationale": plan.rationale,
        "has_cycle": plan.has_cycle,
    }
