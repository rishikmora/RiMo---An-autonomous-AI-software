"""Registry mapping each AgentRole to its concrete agent implementation."""
from __future__ import annotations

from app.agents.base import BaseAgent
from app.agents.engineering import (
    BuilderAgent,
    DevOpsAgent,
    QAAgent,
    ReviewerAgent,
    SecurityAgent,
)
from app.agents.strategy import (
    ArchitectAgent,
    CEOAgent,
    MemoryAgent,
    PlannerAgent,
    ResearchAgent,
)
from app.models.enums import AgentRole

AGENT_REGISTRY: dict[AgentRole, BaseAgent] = {
    AgentRole.CEO: CEOAgent(),
    AgentRole.RESEARCH: ResearchAgent(),
    AgentRole.PLANNER: PlannerAgent(),
    AgentRole.ARCHITECT: ArchitectAgent(),
    AgentRole.BUILDER: BuilderAgent(),
    AgentRole.REVIEWER: ReviewerAgent(),
    AgentRole.QA: QAAgent(),
    AgentRole.SECURITY: SecurityAgent(),
    AgentRole.DEVOPS: DevOpsAgent(),
    AgentRole.MEMORY: MemoryAgent(),
}


def get_agent(role: AgentRole) -> BaseAgent:
    return AGENT_REGISTRY[role]


ALL_ROLES: list[AgentRole] = list(AGENT_REGISTRY.keys())
