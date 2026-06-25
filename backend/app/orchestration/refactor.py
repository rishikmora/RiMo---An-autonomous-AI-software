"""Autonomous architecture refactoring.

Most agents only add code. RiMo also detects architectural decay and proposes
bounded refactors. It mines the knowledge graph for objective smells — God
objects (excessively high fan-in/fan-out), hub files, deep dependency chains,
and circular dependencies — and turns each into a scoped refactor task with a
migration plan for the Architect and Builder to execute behind the normal
quality gate and benchmark guard.

This is deliberately graph-driven and quantitative rather than vibe-based: every
proposed refactor cites the metric that triggered it, so the backlog stays
explainable and the Planner can weigh it against feature work.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import networkx as nx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import GraphEdge, GraphNode, Task
from app.models.enums import NodeKind, Priority, TaskKind, TaskStatus

logger = get_logger(__name__)


@dataclass
class Smell:
    kind: str               # god_object | hub_file | deep_chain | cycle
    node_key: str
    node_name: str
    metric: str             # human-readable metric that triggered it
    severity: float         # 0..1
    suggestion: str
    members: list[str] = field(default_factory=list)


class RefactorAnalyzer:
    """Detects architectural smells from the persisted knowledge graph."""

    def __init__(
        self,
        *,
        god_object_threshold: int = 20,
        hub_fanin_threshold: int = 15,
        deep_chain_threshold: int = 6,
    ) -> None:
        self._god = god_object_threshold
        self._hub = hub_fanin_threshold
        self._chain = deep_chain_threshold

    async def analyze(
        self, session: AsyncSession, *, project_id: uuid.UUID
    ) -> list[Smell]:
        nodes = (
            await session.execute(
                select(GraphNode).where(GraphNode.project_id == project_id)
            )
        ).scalars().all()
        edges = (
            await session.execute(
                select(GraphEdge).where(GraphEdge.project_id == project_id)
            )
        ).scalars().all()
        if not nodes:
            return []

        id_to_node = {n.id: n for n in nodes}
        g = nx.DiGraph()
        for n in nodes:
            g.add_node(n.id)
        for e in edges:
            if e.source_id in id_to_node and e.target_id in id_to_node:
                g.add_edge(e.source_id, e.target_id)

        smells: list[Smell] = []
        smells.extend(self._god_objects(g, id_to_node))
        smells.extend(self._hub_files(g, id_to_node))
        smells.extend(self._cycles(g, id_to_node))
        smells.extend(self._deep_chains(g, id_to_node))

        smells.sort(key=lambda s: s.severity, reverse=True)
        logger.info("refactor_analysis", project=str(project_id), smells=len(smells))
        return smells

    def _god_objects(self, g: nx.DiGraph, id_to_node: dict) -> list[Smell]:
        out: list[Smell] = []
        for nid in g.nodes:
            node = id_to_node[nid]
            if node.kind not in {NodeKind.CLASS, NodeKind.FILE}:
                continue
            degree = g.in_degree(nid) + g.out_degree(nid)
            if degree >= self._god:
                out.append(
                    Smell(
                        kind="god_object",
                        node_key=node.key,
                        node_name=node.name,
                        metric=f"{degree} total dependencies (in={g.in_degree(nid)}, out={g.out_degree(nid)})",
                        severity=min(1.0, degree / (self._god * 2)),
                        suggestion=f"Split {node.name} into smaller, single-responsibility units.",
                    )
                )
        return out

    def _hub_files(self, g: nx.DiGraph, id_to_node: dict) -> list[Smell]:
        out: list[Smell] = []
        for nid in g.nodes:
            node = id_to_node[nid]
            if node.kind is not NodeKind.FILE:
                continue
            fanin = g.in_degree(nid)
            if fanin >= self._hub:
                out.append(
                    Smell(
                        kind="hub_file",
                        node_key=node.key,
                        node_name=node.name,
                        metric=f"{fanin} modules depend on this file",
                        severity=min(1.0, fanin / (self._hub * 2)),
                        suggestion=f"{node.name} is a change-coupling hub; consider extracting stable interfaces.",
                    )
                )
        return out

    def _cycles(self, g: nx.DiGraph, id_to_node: dict) -> list[Smell]:
        out: list[Smell] = []
        try:
            cycles = list(nx.simple_cycles(g))
        except Exception:  # pragma: no cover - defensive
            return out
        for cycle in cycles:
            if len(cycle) < 2:
                continue
            members = [id_to_node[c].name for c in cycle if c in id_to_node]
            out.append(
                Smell(
                    kind="cycle",
                    node_key=id_to_node[cycle[0]].key,
                    node_name=" → ".join(members),
                    metric=f"circular dependency across {len(members)} nodes",
                    severity=min(1.0, 0.5 + len(members) / 10),
                    suggestion="Break the cycle by introducing an abstraction or inverting a dependency.",
                    members=members,
                )
            )
        return out[:10]  # cap to avoid noise

    def _deep_chains(self, g: nx.DiGraph, id_to_node: dict) -> list[Smell]:
        out: list[Smell] = []
        if g.number_of_nodes() == 0:
            return out
        try:
            dag = g.copy()
            # Remove cycles for the longest-path computation.
            while not nx.is_directed_acyclic_graph(dag):
                cyc = next(iter(nx.simple_cycles(dag)), None)
                if not cyc or len(cyc) < 2:
                    break
                dag.remove_edge(cyc[0], cyc[1])
            longest = nx.dag_longest_path(dag)
        except Exception:  # pragma: no cover
            return out
        if len(longest) >= self._chain:
            members = [id_to_node[n].name for n in longest if n in id_to_node]
            out.append(
                Smell(
                    kind="deep_chain",
                    node_key=id_to_node[longest[0]].key if longest[0] in id_to_node else "",
                    node_name=members[0] if members else "",
                    metric=f"dependency chain of depth {len(longest)}",
                    severity=min(1.0, len(longest) / (self._chain * 2)),
                    suggestion="Flatten the dependency chain to reduce coupling and build-time cascades.",
                    members=members,
                )
            )
        return out

    async def propose_refactors(
        self,
        session: AsyncSession,
        *,
        project_id: uuid.UUID,
        max_tasks: int = 5,
        min_severity: float = 0.5,
    ) -> list[Task]:
        """Turn the worst smells into scoped refactor tasks on the backlog."""
        smells = await self.analyze(session, project_id=project_id)
        created: list[Task] = []
        for smell in smells:
            if smell.severity < min_severity or len(created) >= max_tasks:
                continue
            task = Task(
                project_id=project_id,
                title=f"Refactor: {smell.kind.replace('_', ' ')} in {smell.node_name}"[:200],
                description=(
                    f"Detected {smell.kind} — {smell.metric}.\n\n"
                    f"Suggested approach: {smell.suggestion}\n\n"
                    "Refactor behind the standard review + benchmark gate; no behavior change."
                ),
                kind=TaskKind.REFACTOR,
                status=TaskStatus.BACKLOG,
                priority=Priority.MEDIUM if smell.severity < 0.8 else Priority.HIGH,
                complexity=5,
                acceptance_criteria=[
                    "No behavior change (tests still pass)",
                    "No performance regression (benchmark gate passes)",
                    f"The {smell.kind} metric is measurably reduced",
                ],
                result={"source": "refactor_analyzer", "smell": smell.kind, "severity": smell.severity},
            )
            session.add(task)
            created.append(task)
        await session.flush()
        logger.info("refactors_proposed", project=str(project_id), count=len(created))
        return created


refactor_analyzer = RefactorAnalyzer()
