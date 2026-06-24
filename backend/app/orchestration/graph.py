"""Project knowledge graph — RiMo's structural brain.

Most agents only read files. RiMo builds and persists a typed graph of the
codebase: modules, files, classes, functions, API routes, database tables, and
external dependencies, plus the relationships between them (imports, calls,
defines, depends-on). Agents query this graph to understand structure and blast
radius before they touch anything.

Extraction is language-aware:
  * Python is parsed with the standard :mod:`ast` module (precise).
  * JS/TS/TSX is extracted with robust regexes (imports, exported
    classes/functions, React components) — good enough to map structure without
    bundling a full JS parser.

After ingestion, a PageRank pass scores node centrality so the most
load-bearing parts of the system (the things many others depend on) rank
highest. That score drives prioritization: refactors and reviews weight
high-centrality nodes more heavily.
"""
from __future__ import annotations

import ast
import re
import uuid
from dataclasses import dataclass, field

import networkx as nx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import GraphEdge, GraphNode
from app.models.enums import EdgeKind, NodeKind

logger = get_logger(__name__)

_PY_EXT = (".py",)
_JS_EXT = (".js", ".jsx", ".ts", ".tsx", ".mjs")
_SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".next", "dist", "build", ".venv", "venv"}


@dataclass
class _Node:
    kind: NodeKind
    key: str
    name: str
    path: str | None = None
    signature: str | None = None
    summary: str | None = None
    meta: dict = field(default_factory=dict)


@dataclass
class _Edge:
    source_key: str
    target_key: str
    kind: EdgeKind
    weight: float = 1.0


class GraphExtractor:
    """Turns a {path: content} map of a repository into nodes and edges."""

    def __init__(self) -> None:
        self.nodes: dict[str, _Node] = {}
        self.edges: list[_Edge] = []

    def _add_node(self, node: _Node) -> None:
        # First writer wins on identity; later passes may enrich meta.
        self.nodes.setdefault(node.key, node)

    def _add_edge(self, edge: _Edge) -> None:
        self.edges.append(edge)

    def extract(self, files: dict[str, str]) -> tuple[list[_Node], list[_Edge]]:
        for path, content in files.items():
            if any(part in _SKIP_DIRS for part in path.split("/")):
                continue
            self._add_module_chain(path)
            if path.endswith(_PY_EXT):
                self._extract_python(path, content)
            elif path.endswith(_JS_EXT):
                self._extract_js(path, content)
        self._resolve_external_dependencies()
        return list(self.nodes.values()), self.edges

    # --- module/file structure ---------------------------------------------
    def _add_module_chain(self, path: str) -> None:
        """Create file node and CONTAINS edges from its directory chain."""
        file_key = f"file:{path}"
        self._add_node(_Node(NodeKind.FILE, file_key, path.rsplit("/", 1)[-1], path=path))
        parts = path.split("/")[:-1]
        prev_key: str | None = None
        acc = ""
        for part in parts:
            acc = f"{acc}/{part}" if acc else part
            mod_key = f"module:{acc}"
            self._add_node(_Node(NodeKind.MODULE, mod_key, part, path=acc))
            if prev_key:
                self._add_edge(_Edge(prev_key, mod_key, EdgeKind.CONTAINS))
            prev_key = mod_key
        if prev_key:
            self._add_edge(_Edge(prev_key, file_key, EdgeKind.CONTAINS))

    # --- Python (AST) -------------------------------------------------------
    def _extract_python(self, path: str, content: str) -> None:
        file_key = f"file:{path}"
        try:
            tree = ast.parse(content)
        except SyntaxError:
            logger.warning("graph_python_parse_failed", path=path)
            return

        # Detect FastAPI/Flask-style routes via decorators.
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn_key = f"{path}::func:{node.name}"
                sig = f"{node.name}({', '.join(a.arg for a in node.args.args)})"
                self._add_node(
                    _Node(NodeKind.FUNCTION, fn_key, node.name, path=path, signature=sig)
                )
                self._add_edge(_Edge(file_key, fn_key, EdgeKind.DEFINES))
                self._extract_calls(node, fn_key, path)
                route = self._route_from_decorators(node)
                if route:
                    method, route_path = route
                    rkey = f"route:{method}:{route_path}"
                    self._add_node(
                        _Node(
                            NodeKind.API_ROUTE,
                            rkey,
                            f"{method} {route_path}",
                            path=path,
                            meta={"method": method, "path": route_path},
                        )
                    )
                    self._add_edge(_Edge(fn_key, rkey, EdgeKind.DEFINES))
            elif isinstance(node, ast.ClassDef):
                cls_key = f"{path}::class:{node.name}"
                self._add_node(_Node(NodeKind.CLASS, cls_key, node.name, path=path))
                self._add_edge(_Edge(file_key, cls_key, EdgeKind.DEFINES))
                for base in node.bases:
                    base_name = _name_of(base)
                    if base_name:
                        self._add_edge(
                            _Edge(cls_key, f"class:{base_name}", EdgeKind.INHERITS)
                        )
                # SQLAlchemy table detection: __tablename__ = "..."
                table = _sqlalchemy_table(node)
                if table:
                    tkey = f"table:{table}"
                    self._add_node(
                        _Node(NodeKind.DB_TABLE, tkey, table, path=path)
                    )
                    self._add_edge(_Edge(cls_key, tkey, EdgeKind.DEFINES))

        # Imports → DEPENDS_ON
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self._add_edge(_Edge(file_key, f"ext:{alias.name.split('.')[0]}", EdgeKind.IMPORTS))
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                self._add_edge(_Edge(file_key, f"ext:{root}", EdgeKind.IMPORTS))

    def _extract_calls(self, fn_node: ast.AST, fn_key: str, path: str) -> None:
        for sub in ast.walk(fn_node):
            if isinstance(sub, ast.Call):
                callee = _name_of(sub.func)
                if callee and callee.isidentifier():
                    self._add_edge(_Edge(fn_key, f"{path}::func:{callee}", EdgeKind.CALLS, 0.5))

    @staticmethod
    def _route_from_decorators(node: ast.AST) -> tuple[str, str] | None:
        for dec in getattr(node, "decorator_list", []):
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                method = dec.func.attr.upper()
                if method in {"GET", "POST", "PUT", "PATCH", "DELETE"} and dec.args:
                    arg0 = dec.args[0]
                    if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                        return method, arg0.value
        return None

    # --- JS / TS (regex) ----------------------------------------------------
    _RE_IMPORT = re.compile(r"""import\s+(?:[\w*\s{},]+\s+from\s+)?["']([^"']+)["']""")
    _RE_CLASS = re.compile(r"\bclass\s+([A-Z]\w+)")
    _RE_FUNC = re.compile(r"(?:export\s+)?(?:async\s+)?function\s+(\w+)")
    _RE_COMPONENT = re.compile(r"(?:export\s+)?const\s+([A-Z]\w+)\s*[:=]\s*(?:\([^)]*\)|[\w<>,\s]*)\s*=>")
    _RE_ARROW_FN = re.compile(r"(?:export\s+)?const\s+([a-z]\w+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>")

    def _extract_js(self, path: str, content: str) -> None:
        file_key = f"file:{path}"
        for m in self._RE_IMPORT.finditer(content):
            spec = m.group(1)
            if spec.startswith("."):
                continue  # relative import: structure already captured via files
            root = spec.split("/")[0]
            if root.startswith("@"):
                root = "/".join(spec.split("/")[:2])
            self._add_edge(_Edge(file_key, f"ext:{root}", EdgeKind.IMPORTS))
        for m in self._RE_CLASS.finditer(content):
            key = f"{path}::class:{m.group(1)}"
            self._add_node(_Node(NodeKind.CLASS, key, m.group(1), path=path))
            self._add_edge(_Edge(file_key, key, EdgeKind.DEFINES))
        for regex, kind in ((self._RE_FUNC, NodeKind.FUNCTION), (self._RE_ARROW_FN, NodeKind.FUNCTION)):
            for m in regex.finditer(content):
                key = f"{path}::func:{m.group(1)}"
                self._add_node(_Node(kind, key, m.group(1), path=path))
                self._add_edge(_Edge(file_key, key, EdgeKind.DEFINES))
        for m in self._RE_COMPONENT.finditer(content):
            key = f"{path}::component:{m.group(1)}"
            self._add_node(
                _Node(NodeKind.FUNCTION, key, m.group(1), path=path, meta={"react_component": True})
            )
            self._add_edge(_Edge(file_key, key, EdgeKind.DEFINES))

    # --- external deps ------------------------------------------------------
    def _resolve_external_dependencies(self) -> None:
        """Materialize EXTERNAL nodes for every ext:* edge target."""
        seen: set[str] = set()
        for edge in self.edges:
            if edge.target_key.startswith("ext:") and edge.target_key not in seen:
                seen.add(edge.target_key)
                name = edge.target_key[4:]
                self._add_node(_Node(NodeKind.EXTERNAL, edge.target_key, name))
            # Rewrite ext: import edges to DEPENDS_ON for clarity.
        for edge in self.edges:
            if edge.target_key.startswith("ext:") and edge.kind is EdgeKind.IMPORTS:
                edge.kind = EdgeKind.DEPENDS_ON


def _name_of(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _sqlalchemy_table(cls: ast.ClassDef) -> str | None:
    for stmt in cls.body:
        if isinstance(stmt, ast.Assign):
            for tgt in stmt.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "__tablename__":
                    if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                        return stmt.value.value
    return None


class KnowledgeGraphService:
    """Builds, persists, and queries the project knowledge graph."""

    def __init__(self) -> None:
        self._extractor_cls = GraphExtractor

    async def rebuild(
        self, session: AsyncSession, *, project_id: uuid.UUID, files: dict[str, str]
    ) -> dict[str, int]:
        """Extract the graph from the codebase and replace the stored version."""
        extractor = self._extractor_cls()
        nodes, edges = extractor.extract(files)

        # Compute centrality over a directed graph of keys.
        centrality = self._centrality(nodes, edges)

        # Replace existing graph for the project (idempotent rebuild).
        await session.execute(delete(GraphEdge).where(GraphEdge.project_id == project_id))
        await session.execute(delete(GraphNode).where(GraphNode.project_id == project_id))
        await session.flush()

        key_to_id: dict[str, uuid.UUID] = {}
        for n in nodes:
            row = GraphNode(
                project_id=project_id,
                kind=n.kind,
                key=n.key,
                name=n.name,
                path=n.path,
                signature=n.signature,
                summary=n.summary,
                meta=n.meta,
                centrality=centrality.get(n.key, 0.0),
            )
            session.add(row)
            key_to_id[n.key] = row.id
        await session.flush()

        edge_count = 0
        seen_edges: set[tuple] = set()
        for e in edges:
            sid = key_to_id.get(e.source_key)
            tid = key_to_id.get(e.target_key)
            if not sid or not tid:
                continue  # edge to a node we didn't materialize
            dedup = (sid, tid, e.kind)
            if dedup in seen_edges:
                continue
            seen_edges.add(dedup)
            session.add(
                GraphEdge(
                    project_id=project_id,
                    source_id=sid,
                    target_id=tid,
                    kind=e.kind,
                    weight=e.weight,
                )
            )
            edge_count += 1

        logger.info(
            "knowledge_graph_built",
            project=str(project_id),
            nodes=len(nodes),
            edges=edge_count,
        )
        return {"nodes": len(nodes), "edges": edge_count}

    @staticmethod
    def _centrality(nodes: list[_Node], edges: list[_Edge]) -> dict[str, float]:
        g = nx.DiGraph()
        valid = {n.key for n in nodes}
        g.add_nodes_from(valid)
        for e in edges:
            if e.source_key in valid and e.target_key in valid:
                g.add_edge(e.source_key, e.target_key, weight=e.weight)
        if g.number_of_nodes() == 0:
            return {}
        try:
            # Reverse so that "many things depend on me" => high score.
            return nx.pagerank(g.reverse(copy=False), weight="weight")
        except Exception:  # pragma: no cover - pagerank convergence edge case
            return {k: 1.0 / len(valid) for k in valid}

    async def neighbors(
        self,
        session: AsyncSession,
        *,
        project_id: uuid.UUID,
        node_key: str,
    ) -> dict:
        """Return a node and its immediate dependencies/dependents (blast radius)."""
        node = (
            await session.execute(
                select(GraphNode).where(
                    GraphNode.project_id == project_id, GraphNode.key == node_key
                )
            )
        ).scalar_one_or_none()
        if not node:
            return {"node": None, "depends_on": [], "dependents": []}

        out_edges = (
            await session.execute(select(GraphEdge).where(GraphEdge.source_id == node.id))
        ).scalars().all()
        in_edges = (
            await session.execute(select(GraphEdge).where(GraphEdge.target_id == node.id))
        ).scalars().all()
        return {
            "node": node,
            "depends_on": [e.target_id for e in out_edges],
            "dependents": [e.source_id for e in in_edges],
        }

    async def most_central(
        self, session: AsyncSession, *, project_id: uuid.UUID, limit: int = 15
    ) -> list[GraphNode]:
        """The most load-bearing nodes — high blast radius if changed."""
        rows = (
            await session.execute(
                select(GraphNode)
                .where(GraphNode.project_id == project_id)
                .order_by(GraphNode.centrality.desc())
                .limit(limit)
            )
        ).scalars().all()
        return list(rows)


knowledge_graph = KnowledgeGraphService()
