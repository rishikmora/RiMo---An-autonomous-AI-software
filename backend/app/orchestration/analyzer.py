"""Codebase analysis.

When a project connects a repository, the analyzer fetches the file tree,
detects the primary language and stack, samples key files, and asks an agent to
produce an architecture summary. The result is cached on the Project and seeds
the Memory store with project facts.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.integrations.github import GitHubClient
from app.memory.service import MemoryService
from app.models import Project
from app.models.enums import MemoryKind
from app.orchestration.utils import parse_json_output
from app.services.llm import LLMClient

logger = get_logger(__name__)

_LANG_BY_EXT = {
    ".py": "Python", ".ts": "TypeScript", ".tsx": "TypeScript", ".js": "JavaScript",
    ".jsx": "JavaScript", ".go": "Go", ".rs": "Rust", ".java": "Java", ".rb": "Ruby",
    ".php": "PHP", ".cs": "C#", ".cpp": "C++", ".c": "C", ".kt": "Kotlin",
    ".swift": "Swift", ".scala": "Scala", ".sql": "SQL",
}

_KEY_FILES = (
    "README.md", "package.json", "pyproject.toml", "requirements.txt", "go.mod",
    "Cargo.toml", "pom.xml", "build.gradle", "Dockerfile", "docker-compose.yml",
    "tsconfig.json", "next.config.js", "next.config.mjs",
)

_ANALYSIS_SYSTEM = (
    "You are a principal engineer onboarding to a codebase. Given its file tree "
    "and key configuration files, produce a precise architecture summary. Output "
    "ONLY JSON: {\"summary\": str, \"stack\": [str], \"entrypoints\": [str], "
    "\"modules\": [{\"name\": str, \"purpose\": str}], \"facts\": [str]}"
)


class CodebaseAnalyzer:
    def __init__(self, llm: LLMClient, memory: MemoryService) -> None:
        self._llm = llm
        self._memory = memory

    async def analyze(
        self, session: AsyncSession, project: Project, gh: GitHubClient
    ) -> dict[str, Any]:
        if not project.repo_full_name:
            return {}
        repo = project.repo_full_name
        tree = await gh.get_tree(repo, project.default_branch)
        blobs = [t["path"] for t in tree if t["type"] == "blob"]

        primary_language = self._detect_language(blobs)
        project.primary_language = primary_language
        project.file_tree = {"paths": blobs[:3000], "count": len(blobs)}

        # Sample key files to give the model real signal.
        samples: dict[str, str] = {}
        for path in blobs:
            if any(path.endswith(k) or path == k for k in _KEY_FILES):
                try:
                    samples[path] = (await gh.get_file(repo, path, project.default_branch))[:4000]
                except Exception:
                    continue
            if len(samples) >= 8:
                break

        prompt = self._build_prompt(repo, primary_language, blobs, samples)
        response = await self._llm.complete(
            system=_ANALYSIS_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
        )
        text = "".join(b.text for b in response.content if b.type == "text")
        parsed = parse_json_output(text) or {}

        project.architecture_summary = parsed.get("summary", "")
        project.metrics = {
            **(project.metrics or {}),
            "file_count": len(blobs),
            "stack": parsed.get("stack", []),
        }

        # Seed memory with durable project facts.
        for fact in parsed.get("facts", [])[:10]:
            await self._memory.remember(
                session,
                kind=MemoryKind.PROJECT_FACT,
                title=f"Codebase fact: {fact[:60]}",
                content=fact,
                project_id=project.id,
                importance=0.7,
            )
        logger.info("codebase_analyzed", repo=repo, files=len(blobs), language=primary_language)
        return parsed

    def _detect_language(self, paths: list[str]) -> str:
        counts: Counter[str] = Counter()
        for p in paths:
            for ext, lang in _LANG_BY_EXT.items():
                if p.endswith(ext):
                    counts[lang] += 1
        return counts.most_common(1)[0][0] if counts else "unknown"

    def _build_prompt(
        self, repo: str, language: str, blobs: list[str], samples: dict[str, str]
    ) -> str:
        tree_preview = "\n".join(blobs[:300])
        sample_text = "\n\n".join(f"### {path}\n{content}" for path, content in samples.items())
        return (
            f"Repository: {repo}\nPrimary language: {language}\n"
            f"File count: {len(blobs)}\n\n"
            f"File tree (truncated):\n{tree_preview}\n\n"
            f"Key files:\n{sample_text}\n\n"
            "Analyse the architecture and respond with the required JSON."
        )
