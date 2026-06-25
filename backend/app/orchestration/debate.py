"""Agent debate system.

Single-agent output is a first draft. RiMo runs a structured debate in which
specialists challenge each other's work before anything ships:

    Architect → Builder → Reviewer → Security → Performance

Each stage receives the prior stages' positions and must either endorse or
challenge them with specific, actionable critique. A debate produces a
consensus verdict and a consolidated set of required changes — which the
orchestrator feeds back to the Builder before the quality gate. Empirically,
adversarial review of this kind catches defects a lone author misses.

The debate is bounded (fixed participant order, one challenge pass plus an
optional rebuttal) so it cannot loop indefinitely, and every position is
recorded for the activity timeline and memory.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.core.logging import get_logger
from app.models.enums import AgentRole

logger = get_logger(__name__)

# A debater is asked to take a position given the transcript so far.
# Signature: async (prompt: str) -> str  (returns the agent's argument text)
Debater = Callable[[str], Awaitable[str]]


@dataclass
class Position:
    role: AgentRole
    stance: str             # "endorse" | "challenge"
    argument: str
    required_changes: list[str] = field(default_factory=list)
    severity: str = "minor"  # minor | major | blocker


@dataclass
class DebateResult:
    consensus: bool
    verdict: str                      # "approved" | "changes_required"
    positions: list[Position]
    required_changes: list[str]
    blocking_count: int

    def to_dict(self) -> dict:
        return {
            "consensus": self.consensus,
            "verdict": self.verdict,
            "blocking_count": self.blocking_count,
            "required_changes": self.required_changes,
            "positions": [
                {
                    "role": p.role.value,
                    "stance": p.stance,
                    "severity": p.severity,
                    "argument": p.argument,
                    "required_changes": p.required_changes,
                }
                for p in self.positions
            ],
        }


# The default debate order. Each challenges everything before it.
DEBATE_ORDER: list[AgentRole] = [
    AgentRole.ARCHITECT,
    AgentRole.REVIEWER,
    AgentRole.SECURITY,
    AgentRole.QA,  # stands in for "performance/quality" perspective
]


_STANCE_PROMPT = """You are participating in an engineering design debate as the {role} specialist.

The proposed change under debate:
---
{proposal}
---

Positions already taken by other specialists:
{prior}

State your position. You must either ENDORSE the change or CHALLENGE it with
specific, actionable critique grounded in your specialty ({role}). Do not raise
vague concerns — every objection must name what to change.

Respond ONLY as JSON:
{{"stance": "endorse|challenge",
  "severity": "minor|major|blocker",
  "argument": "<your reasoning, 2-4 sentences>",
  "required_changes": ["<specific change>", ...]}}"""


class DebateEngine:
    """Runs a bounded, structured debate among specialist agents."""

    def __init__(self, parse_json) -> None:
        # parse_json: callable(str) -> dict | None  (reuse orchestrator util)
        self._parse = parse_json

    async def run(
        self,
        *,
        proposal: str,
        debaters: dict[AgentRole, Debater],
        order: list[AgentRole] | None = None,
        emit=None,  # optional async (role, position) -> None for the timeline
    ) -> DebateResult:
        order = [r for r in (order or DEBATE_ORDER) if r in debaters]
        positions: list[Position] = []

        for role in order:
            prior = self._format_prior(positions)
            prompt = _STANCE_PROMPT.format(
                role=role.value, proposal=proposal, prior=prior or "(none yet)"
            )
            raw = await debaters[role](prompt)
            position = self._parse_position(role, raw)
            positions.append(position)
            if emit:
                await emit(role, position)
            logger.info(
                "debate_position",
                role=role.value,
                stance=position.stance,
                severity=position.severity,
            )

        return self._consolidate(positions)

    def _format_prior(self, positions: list[Position]) -> str:
        if not positions:
            return ""
        lines = []
        for p in positions:
            lines.append(f"- {p.role.value} ({p.stance}, {p.severity}): {p.argument}")
            for c in p.required_changes:
                lines.append(f"    • requires: {c}")
        return "\n".join(lines)

    def _parse_position(self, role: AgentRole, raw: str) -> Position:
        data = self._parse(raw) or {}
        stance = data.get("stance", "endorse")
        if stance not in {"endorse", "challenge"}:
            stance = "challenge" if data.get("required_changes") else "endorse"
        severity = data.get("severity", "minor")
        if severity not in {"minor", "major", "blocker"}:
            severity = "minor"
        return Position(
            role=role,
            stance=stance,
            argument=str(data.get("argument", "")).strip() or "(no argument provided)",
            required_changes=[str(c) for c in data.get("required_changes", []) if c],
            severity=severity,
        )

    def _consolidate(self, positions: list[Position]) -> DebateResult:
        required: list[str] = []
        blocking = 0
        for p in positions:
            if p.stance == "challenge":
                required.extend(p.required_changes)
                if p.severity == "blocker":
                    blocking += 1
        # Consensus = no challenges at all. Verdict gates on any blocker or
        # any unresolved required change.
        consensus = all(p.stance == "endorse" for p in positions)
        verdict = "approved" if consensus or (blocking == 0 and not required) else "changes_required"
        # De-duplicate while preserving order.
        seen: set[str] = set()
        deduped = [c for c in required if not (c in seen or seen.add(c))]
        return DebateResult(
            consensus=consensus,
            verdict=verdict,
            positions=positions,
            required_changes=deduped,
            blocking_count=blocking,
        )
