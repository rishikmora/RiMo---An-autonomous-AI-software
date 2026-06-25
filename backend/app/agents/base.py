"""Base class for all RiMo specialist agents.

Each agent has:
  * a `role` (one of the ten company roles)
  * a `system_prompt` describing its mandate, tools, and output contract
  * an `execute` method that runs its reasoning loop against a task

Agents are stateless services; all durable state lives in the database and the
memory subsystem. The orchestrator constructs an `AgentContext` per run and
hands it to the agent.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tools import WorkspaceFiles
from app.core.logging import get_logger
from app.integrations.github import GitHubClient
from app.memory.service import MemoryService
from app.models import Project, Task
from app.models.enums import AgentRole
from app.services.llm import AgentLoop, AgentResult, LLMClient, ToolRegistry

logger = get_logger(__name__)


@dataclass(slots=True)
class AgentContext:
    """Everything an agent needs for a single execution."""

    session: AsyncSession
    project: Project
    task: Task
    llm: LLMClient
    memory: MemoryService
    github: GitHubClient | None
    workspace: WorkspaceFiles
    branch: str
    web_search: Any  # async callable(query) -> list[dict]
    emit_event: Any  # async callable(event_type, message, **data)
    extra: dict[str, Any]


class BaseAgent(ABC):
    """Abstract specialist agent."""

    role: AgentRole
    model: str | None = None  # None -> default (Opus); set fast_model for cheap roles

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """Return the agent's system prompt."""

    @abstractmethod
    def build_tools(self, ctx: AgentContext, registry: ToolRegistry) -> None:
        """Register the tools this agent may use."""

    @abstractmethod
    def build_prompt(self, ctx: AgentContext, memory_context: str) -> str:
        """Render the user prompt for this run from task + memory context."""

    async def execute(self, ctx: AgentContext) -> AgentResult:
        """Run the agent's reasoning loop and return its result."""
        registry = ToolRegistry()
        self.build_tools(ctx, registry)

        memory_context = await ctx.memory.build_context_block(
            ctx.session,
            query=f"{ctx.task.title}\n{ctx.task.description or ''}",
            project_id=ctx.project.id,
        )
        prompt = self.build_prompt(ctx, memory_context)

        loop = AgentLoop(ctx.llm, registry, model=self.model)

        async def _on_step(step: dict[str, Any]) -> None:
            if step.get("text"):
                await ctx.emit_event(
                    "agent_step",
                    step["text"][:400],
                    role=self.role.value,
                    iteration=step["iteration"],
                )

        await ctx.emit_event("agent_started", f"{self.role.value} started: {ctx.task.title}", role=self.role.value)
        result = await loop.run(system=self.system_prompt, prompt=prompt, on_step=_on_step)
        status = "succeeded" if result.success else "failed"
        await ctx.emit_event(
            f"agent_{status}",
            f"{self.role.value} {status} after {result.iterations} steps",
            role=self.role.value,
            tokens=result.usage.input_tokens + result.usage.output_tokens,
        )
        return result
