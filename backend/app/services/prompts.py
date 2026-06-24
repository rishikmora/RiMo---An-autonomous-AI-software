"""Self-evolving prompts.

Every agent role can have multiple prompt variants. RiMo measures each variant's
real success rate and reward in production and routes new work to the variants
that perform best — while still exploring alternatives so a better prompt can
win. This is a multi-armed bandit over prompts.

Selection uses Thompson sampling on a Beta(successes+1, failures+1) posterior:
it naturally balances exploitation (use the best) with exploration (give new or
uncertain variants a chance), with no hand-tuned epsilon.

The evolution loop (driven weekly by the self-improvement job) takes the top
performer for a role, mutates it via the Memory/Architect model into a new
candidate, and adds it as the next generation. Underperformers are retired.
"""
from __future__ import annotations

import random
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import PromptExecution, PromptVariant
from app.models.enums import AgentRole

logger = get_logger(__name__)


def _beta_sample(successes: int, failures: int) -> float:
    """Sample from Beta(successes+1, failures+1) using the gamma method."""
    a = successes + 1.0
    b = failures + 1.0
    x = random.gammavariate(a, 1.0)
    y = random.gammavariate(b, 1.0)
    return x / (x + y)


class PromptService:
    """Stores, selects, scores, and evolves prompt variants per role."""

    async def ensure_seed(
        self, session: AsyncSession, *, role: AgentRole, template: str
    ) -> PromptVariant:
        """Ensure a role has at least one (baseline) variant; return the active set's seed."""
        existing = (
            await session.execute(
                select(PromptVariant).where(
                    PromptVariant.role == role, PromptVariant.name == "baseline"
                )
            )
        ).scalar_one_or_none()
        if existing:
            return existing
        variant = PromptVariant(role=role, name="baseline", template=template, generation=0)
        session.add(variant)
        await session.flush()
        logger.info("prompt_seed_created", role=role.value)
        return variant

    async def select(
        self, session: AsyncSession, *, role: AgentRole
    ) -> PromptVariant | None:
        """Pick a variant for this run via Thompson sampling over active variants."""
        variants = (
            await session.execute(
                select(PromptVariant).where(
                    PromptVariant.role == role, PromptVariant.active.is_(True)
                )
            )
        ).scalars().all()
        if not variants:
            return None
        if len(variants) == 1:
            return variants[0]
        scored = [
            (_beta_sample(v.successes, v.trials - v.successes), v) for v in variants
        ]
        scored.sort(key=lambda t: t[0], reverse=True)
        chosen = scored[0][1]
        logger.info(
            "prompt_selected",
            role=role.value,
            variant=chosen.name,
            trials=chosen.trials,
            success_rate=round(chosen.success_rate, 3),
        )
        return chosen

    async def record_outcome(
        self,
        session: AsyncSession,
        *,
        variant_id: uuid.UUID,
        success: bool,
        reward: float,
        tokens: int = 0,
        task_id: uuid.UUID | None = None,
    ) -> None:
        """Update a variant's running stats and log the execution."""
        variant = await session.get(PromptVariant, variant_id)
        if not variant:
            return
        variant.trials += 1
        if success:
            variant.successes += 1
        variant.total_reward += max(0.0, min(1.0, reward))
        session.add(
            PromptExecution(
                variant_id=variant_id,
                task_id=task_id,
                success=success,
                reward=reward,
                tokens=tokens,
            )
        )
        logger.info(
            "prompt_outcome",
            variant=variant.name,
            success=success,
            reward=round(reward, 3),
            new_rate=round(variant.success_rate, 3),
        )

    async def leaderboard(
        self, session: AsyncSession, *, role: AgentRole
    ) -> list[PromptVariant]:
        """Variants for a role, best measured performance first."""
        variants = (
            await session.execute(
                select(PromptVariant).where(PromptVariant.role == role)
            )
        ).scalars().all()
        # Rank by mean reward, then success rate, with a small trials tiebreak.
        return sorted(
            variants,
            key=lambda v: (
                v.total_reward / v.trials if v.trials else 0.0,
                v.success_rate,
                v.trials,
            ),
            reverse=True,
        )

    async def evolve(
        self,
        session: AsyncSession,
        *,
        role: AgentRole,
        mutator,  # async callable(parent_template: str) -> str
        min_trials: int = 20,
        retire_threshold: float = 0.5,
    ) -> PromptVariant | None:
        """Breed a new variant from the role's current champion; retire laggards.

        `mutator` is an async function (typically an LLM call) that proposes an
        improved template given the best-performing one. The new candidate joins
        the active pool at the next generation so the bandit can trial it.
        """
        board = await self.leaderboard(session, role=role)
        if not board:
            return None
        champion = board[0]
        if champion.trials < min_trials:
            return None  # not enough evidence to evolve yet

        # Retire consistently weak, well-tested variants.
        for v in board[1:]:
            if v.trials >= min_trials and v.success_rate < retire_threshold and v.active:
                v.active = False
                logger.info("prompt_retired", role=role.value, variant=v.name)

        new_template = await mutator(champion.template)
        if not new_template or new_template.strip() == champion.template.strip():
            return None

        gen = champion.generation + 1
        candidate = PromptVariant(
            role=role,
            name=f"gen{gen}-{uuid.uuid4().hex[:6]}",
            template=new_template,
            parent_id=champion.id,
            generation=gen,
            active=True,
        )
        session.add(candidate)
        await session.flush()
        logger.info(
            "prompt_evolved",
            role=role.value,
            parent=champion.name,
            child=candidate.name,
            generation=gen,
        )
        return candidate


prompt_service = PromptService()
