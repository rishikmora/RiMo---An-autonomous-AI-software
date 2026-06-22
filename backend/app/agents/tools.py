"""Concrete tools that agents invoke during their reasoning loops.

`build_engineering_toolset` wires up the tools an engineering agent needs,
bound to a specific project's repository and database session. Every write
goes through the safety layer.

Tools intentionally return structured dicts (never raw exceptions) so the model
can recover from failures inside the loop.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.integrations.github import GitHubClient
from app.memory.service import MemoryService
from app.models import Project
from app.services.llm import ToolRegistry
from app.services.safety import secret_scanner

logger = get_logger(__name__)


class WorkspaceFiles:
    """In-memory staging area for a task's file changes before commit.

    Agents read existing files from GitHub and stage new/modified content here.
    The orchestrator commits the staged set atomically once a task succeeds.
    """

    def __init__(self) -> None:
        self._staged: dict[str, str] = {}

    def stage(self, path: str, content: str) -> None:
        self._staged[path] = content

    @property
    def staged(self) -> dict[str, str]:
        return dict(self._staged)

    def clear(self) -> None:
        self._staged.clear()


def build_research_toolset(
    registry: ToolRegistry,
    *,
    session: AsyncSession,
    memory: MemoryService,
    project: Project,
    web_search: Any,
) -> None:
    """Tools for the Research agent: docs/web search + memory recall."""

    async def _search_web(payload: dict[str, Any]) -> dict[str, Any]:
        query = payload["query"]
        results = await web_search(query)
        return {"query": query, "results": results}

    async def _recall(payload: dict[str, Any]) -> dict[str, Any]:
        hits = await memory.recall(session, query=payload["query"], project_id=project.id)
        return {
            "memories": [
                {"title": r.title, "content": r.content, "similarity": round(s, 3)}
                for r, s in hits
            ]
        }

    registry.add(
        "search_web",
        "Search the web for documentation, libraries, best practices, or competitor analysis.",
        {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        _search_web,
    )
    registry.add(
        "recall_memory",
        "Recall relevant prior knowledge, decisions, and lessons from memory.",
        {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        _recall,
    )


def build_engineering_toolset(
    registry: ToolRegistry,
    *,
    gh: GitHubClient,
    project: Project,
    workspace: WorkspaceFiles,
    branch: str,
) -> None:
    """Tools for Builder/Reviewer/QA agents: read repo, stage files, run scan."""
    repo = project.repo_full_name

    async def _list_files(_: dict[str, Any]) -> dict[str, Any]:
        if not repo:
            return {"files": list(workspace.staged.keys())}
        tree = await gh.get_tree(repo, project.default_branch)
        paths = [t["path"] for t in tree if t["type"] == "blob"]
        return {"files": paths[:2000]}

    async def _read_file(payload: dict[str, Any]) -> dict[str, Any]:
        path = payload["path"]
        if path in workspace.staged:
            return {"path": path, "content": workspace.staged[path], "source": "staged"}
        if not repo:
            return {"error": "no repository connected and file not staged"}
        try:
            content = await gh.get_file(repo, path, ref=branch)
        except Exception:  # fall back to default branch
            content = await gh.get_file(repo, path, ref=project.default_branch)
        return {"path": path, "content": content, "source": "repo"}

    async def _write_file(payload: dict[str, Any]) -> dict[str, Any]:
        path = payload["path"]
        content = payload["content"]
        findings = secret_scanner.scan_file(path, content)
        if findings:
            return {
                "blocked": True,
                "reason": "potential secret detected; remove credentials and use env vars",
                "findings": [
                    {"rule": f.rule, "line": f.line, "preview": f.preview} for f in findings
                ],
            }
        workspace.stage(path, content)
        return {"ok": True, "path": path, "staged_files": len(workspace.staged)}

    async def _secret_scan(_: dict[str, Any]) -> dict[str, Any]:
        findings = secret_scanner.scan_files(workspace.staged)
        return {
            "clean": not findings,
            "findings": [
                {"path": f.path, "rule": f.rule, "line": f.line} for f in findings
            ],
        }

    registry.add(
        "list_files",
        "List files in the repository (or currently staged files).",
        {"type": "object", "properties": {}},
        _list_files,
    )
    registry.add(
        "read_file",
        "Read the full contents of a file by path.",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        _read_file,
    )
    registry.add(
        "write_file",
        "Stage a new or modified file. Content is scanned for secrets before staging. "
        "NEVER include API keys, passwords, or credentials — use environment variables.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
        _write_file,
    )
    registry.add(
        "secret_scan",
        "Scan all staged files for leaked secrets. Run before declaring work complete.",
        {"type": "object", "properties": {}},
        _secret_scan,
    )
