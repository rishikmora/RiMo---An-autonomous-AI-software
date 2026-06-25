"""Strategy & planning specialist agents.

CEO, Research, Planner, Architect, and Memory. These agents reason over the
project as a whole and produce structured artifacts (objectives, roadmaps,
designs, knowledge) rather than code.
"""
from __future__ import annotations

import json

from app.agents.base import AgentContext, BaseAgent
from app.agents.tools import build_research_toolset
from app.core.config import settings
from app.models.enums import AgentRole
from app.services.llm import ToolRegistry


def _json_instructions(shape: str) -> str:
    return (
        f"\n\nWhen you have finished reasoning, output ONLY a single JSON object "
        f"matching this shape and nothing else (no markdown, no prose):\n{shape}"
    )


class CEOAgent(BaseAgent):
    role = AgentRole.CEO

    @property
    def system_prompt(self) -> str:
        return (
            "You are RiMo CEO, the chief strategist of an autonomous software "
            "engineering company. You own mission planning, goal management, and "
            "long-term strategy for a project. You think in outcomes and business "
            "value, not implementation detail. You set clear, measurable objectives "
            "and decide what matters most next. You are decisive, pragmatic, and "
            "ruthless about prioritising work that moves the mission forward."
            + _json_instructions(
                '{"mission": str, "objectives": [{"id": str, "title": str, '
                '"rationale": str, "success_metric": str, "priority": '
                '"critical|high|medium|low"}], "strategic_summary": str}'
            )
        )

    def build_tools(self, ctx: AgentContext, registry: ToolRegistry) -> None:
        build_research_toolset(
            registry,
            session=ctx.session,
            memory=ctx.memory,
            project=ctx.project,
            web_search=ctx.web_search,
        )

    def build_prompt(self, ctx: AgentContext, memory_context: str) -> str:
        p = ctx.project
        return (
            f"Project: {p.name}\n"
            f"Description: {p.description or 'n/a'}\n"
            f"Repository: {p.repo_full_name or 'greenfield (no repo yet)'}\n"
            f"Current mission: {p.mission or 'undefined'}\n"
            f"Architecture summary: {p.architecture_summary or 'unknown'}\n\n"
            f"{memory_context}\n\n"
            "Define or refine the mission and a prioritised set of 3-6 objectives. "
            "Use recall_memory and search_web if helpful to ground your strategy."
        )


class ResearchAgent(BaseAgent):
    role = AgentRole.RESEARCH

    @property
    def system_prompt(self) -> str:
        return (
            "You are RiMo Research. You investigate technical questions by reading "
            "documentation, surveying libraries and prior art, and analysing "
            "competitors. You produce concise, decision-ready briefs with concrete "
            "recommendations and cite the sources you used. You distinguish fact "
            "from opinion and flag risks and trade-offs."
            + _json_instructions(
                '{"question": str, "findings": [{"point": str, "source": str}], '
                '"recommendation": str, "risks": [str]}'
            )
        )

    def build_tools(self, ctx: AgentContext, registry: ToolRegistry) -> None:
        build_research_toolset(
            registry,
            session=ctx.session,
            memory=ctx.memory,
            project=ctx.project,
            web_search=ctx.web_search,
        )

    def build_prompt(self, ctx: AgentContext, memory_context: str) -> str:
        return (
            f"Research task: {ctx.task.title}\n"
            f"Detail: {ctx.task.description or ''}\n\n"
            f"{memory_context}\n\n"
            "Investigate thoroughly using search_web and recall_memory, then deliver "
            "a brief with a clear recommendation."
        )


class PlannerAgent(BaseAgent):
    role = AgentRole.PLANNER

    @property
    def system_prompt(self) -> str:
        return (
            "You are RiMo Planner. You convert objectives into an executable "
            "roadmap: a dependency-aware set of well-scoped tasks. Each task is "
            "small enough to complete in one focused work session, has crisp "
            "acceptance criteria, an estimated complexity (story points 1,2,3,5,8,13), "
            "a kind, and a priority. You sequence work so dependencies come first "
            "and high-value items are front-loaded. You assign each task to the most "
            "appropriate specialist role."
            + _json_instructions(
                '{"tasks": [{"title": str, "description": str, '
                '"kind": "feature|bugfix|refactor|test|security|performance|docs|infra|research", '
                '"priority": "critical|high|medium|low", "complexity": int, '
                '"acceptance_criteria": [str], "assigned_role": '
                '"architect|builder|reviewer|qa|security|devops|research", '
                '"depends_on_titles": [str]}]}'
            )
        )

    def build_tools(self, ctx: AgentContext, registry: ToolRegistry) -> None:
        build_research_toolset(
            registry,
            session=ctx.session,
            memory=ctx.memory,
            project=ctx.project,
            web_search=ctx.web_search,
        )

    def build_prompt(self, ctx: AgentContext, memory_context: str) -> str:
        p = ctx.project
        objectives = json.dumps(p.objectives, indent=2) if p.objectives else "none set"
        return (
            f"Project: {p.name}\nMission: {p.mission or 'n/a'}\n"
            f"Objectives:\n{objectives}\n\n"
            f"Architecture: {p.architecture_summary or 'unknown'}\n\n"
            f"{memory_context}\n\n"
            f"Planning request: {ctx.task.title}\n{ctx.task.description or ''}\n\n"
            "Produce a prioritised, dependency-ordered roadmap of 4-12 tasks."
        )


class ArchitectAgent(BaseAgent):
    role = AgentRole.ARCHITECT

    @property
    def system_prompt(self) -> str:
        return (
            "You are RiMo Architect. You make system design decisions: data models, "
            "module boundaries, API contracts, technology choices, and patterns. You "
            "favour simple, modular, testable designs and you justify every decision "
            "against the project's constraints. You write Architecture Decision "
            "Records (ADRs) that future agents will rely on. You think about "
            "scalability, security, and maintainability as first-class concerns."
            + _json_instructions(
                '{"decision": str, "context": str, "options_considered": '
                '[{"option": str, "tradeoffs": str}], "chosen": str, '
                '"consequences": [str], "implementation_notes": [str]}'
            )
        )

    def build_tools(self, ctx: AgentContext, registry: ToolRegistry) -> None:
        build_research_toolset(
            registry,
            session=ctx.session,
            memory=ctx.memory,
            project=ctx.project,
            web_search=ctx.web_search,
        )

    def build_prompt(self, ctx: AgentContext, memory_context: str) -> str:
        p = ctx.project
        return (
            f"Project: {p.name} ({p.primary_language or 'polyglot'})\n"
            f"Existing architecture: {p.architecture_summary or 'greenfield'}\n\n"
            f"{memory_context}\n\n"
            f"Design task: {ctx.task.title}\n{ctx.task.description or ''}\n\n"
            "Produce an ADR with a clear, justified decision and implementation notes "
            "the Builder can follow."
        )


class MemoryAgent(BaseAgent):
    """Curates the knowledge base. Distils raw run output into durable memories."""

    role = AgentRole.MEMORY
    model = settings.fast_model  # cheap, high-volume curation work

    @property
    def system_prompt(self) -> str:
        return (
            "You are RiMo Memory, the institutional knowledge keeper. You read the "
            "outcome of completed work and extract durable, reusable lessons: "
            "architectural decisions, bug fixes and their root causes, user "
            "preferences, project facts, and patterns that worked well. You write "
            "each memory so a future agent with no context can apply it. You are "
            "concise and you never store secrets or ephemeral detail."
            + _json_instructions(
                '{"memories": [{"kind": '
                '"architecture_decision|bug_fix|user_preference|project_fact|'
                'successful_implementation|lesson_learned", "title": str, '
                '"content": str, "importance": float}]}'
            )
        )

    def build_tools(self, ctx: AgentContext, registry: ToolRegistry) -> None:
        # Memory curation needs no external tools; it reasons over provided text.
        return

    def build_prompt(self, ctx: AgentContext, memory_context: str) -> str:
        source = ctx.extra.get("source_text", ctx.task.description or "")
        return (
            f"Completed work on project {ctx.project.name}.\n"
            f"Task: {ctx.task.title}\n\n"
            f"Outcome / transcript to distil:\n{source[:12000]}\n\n"
            "Extract 0-5 durable memories. If nothing is worth remembering, return "
            'an empty list: {"memories": []}.'
        )
