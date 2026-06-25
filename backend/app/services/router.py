"""Multi-model routing and economic cost tracking.

RiMo never hard-codes a single model. The :class:`ModelRouter` classifies each
unit of work into a complexity tier and routes it to the most cost-effective
model that can do the job — trivial fixes go to a small fast model, system
design goes to a frontier model. This is the single biggest lever on operating
cost (typically a 70–90% reduction versus "everything on Opus").

Routing degrades gracefully: if a provider isn't keyed, the router substitutes
the best available Anthropic model, so the system is never blocked by a missing
OpenAI/Google key.

Every routed call is (optionally) recorded in the :class:`ModelCall` ledger,
giving the economic-reasoning subsystem real spend data per project, per agent,
and per task.
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models import ModelCall
from app.models.enums import (
    AgentRole,
    ModelProvider,
    TaskComplexityTier,
    TaskKind,
)

logger = get_logger(__name__)


# Which roles inherently need frontier reasoning regardless of task size.
_FRONTIER_ROLES = {AgentRole.ARCHITECT, AgentRole.CEO}
# Roles whose work is high-volume and low-stakes — bias cheap.
_CHEAP_ROLES = {AgentRole.MEMORY}


def classify_complexity(
    *,
    role: AgentRole,
    kind: TaskKind | None = None,
    complexity_points: int = 3,
    files_touched: int = 1,
) -> TaskComplexityTier:
    """Heuristically classify a unit of work into a routing tier.

    Combines the owning role, the task kind, its estimated story points, and how
    many files it spans. Deliberately simple and explainable — the router logs
    its reasoning so routing decisions are auditable.
    """
    if role in _FRONTIER_ROLES:
        return TaskComplexityTier.COMPLEX
    if role in _CHEAP_ROLES:
        return TaskComplexityTier.TRIVIAL

    if kind in {TaskKind.DOCS} and complexity_points <= 2:
        return TaskComplexityTier.TRIVIAL
    if kind in {TaskKind.REFACTOR, TaskKind.PERFORMANCE} and files_touched > 3:
        return TaskComplexityTier.COMPLEX

    if complexity_points >= 8 or files_touched > 5:
        return TaskComplexityTier.COMPLEX
    if complexity_points >= 5 or files_touched > 2:
        return TaskComplexityTier.STANDARD
    if complexity_points <= 1 and files_touched <= 1:
        return TaskComplexityTier.TRIVIAL
    return TaskComplexityTier.SIMPLE


class RoutedModel:
    """The resolved model for a unit of work."""

    __slots__ = ("provider", "model", "tier")

    def __init__(self, provider: ModelProvider, model: str, tier: TaskComplexityTier) -> None:
        self.provider = provider
        self.model = model
        self.tier = tier

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"RoutedModel({self.provider.value}:{self.model}, tier={self.tier.value})"


def _provider_has_key(provider: ModelProvider) -> bool:
    return {
        ModelProvider.ANTHROPIC: bool(settings.anthropic_api_key),
        ModelProvider.OPENAI: bool(settings.openai_api_key),
        ModelProvider.GOOGLE: bool(settings.google_api_key),
    }[provider]


def _parse_spec(spec: str) -> RoutedModel:
    provider_str, _, model = spec.partition(":")
    provider = ModelProvider(provider_str)
    return RoutedModel(provider, model, TaskComplexityTier.STANDARD)


class ModelRouter:
    """Routes work to models by tier and records spend.

    Stateless aside from configuration; safe to share. Pass a session to
    :meth:`record` to persist a call to the economic ledger.
    """

    _TIER_SPEC = {
        TaskComplexityTier.TRIVIAL: lambda: settings.model_trivial,
        TaskComplexityTier.SIMPLE: lambda: settings.model_simple,
        TaskComplexityTier.STANDARD: lambda: settings.model_standard,
        TaskComplexityTier.COMPLEX: lambda: settings.model_complex,
    }

    # Anthropic fallbacks per tier, used when the configured provider isn't keyed.
    _ANTHROPIC_FALLBACK = {
        TaskComplexityTier.TRIVIAL: settings.fast_model,
        TaskComplexityTier.SIMPLE: settings.fast_model,
        TaskComplexityTier.STANDARD: "claude-sonnet-4-6",
        TaskComplexityTier.COMPLEX: settings.default_model,
    }

    def route(self, tier: TaskComplexityTier) -> RoutedModel:
        """Resolve a model for a tier, honoring provider availability."""
        if not settings.routing_enabled:
            # Routing off: everything on the default frontier model.
            return RoutedModel(ModelProvider.ANTHROPIC, settings.default_model, tier)

        chosen = _parse_spec(self._TIER_SPEC[tier]())
        chosen.tier = tier
        if _provider_has_key(chosen.provider):
            return chosen

        # Graceful degradation to Anthropic.
        fallback_model = self._ANTHROPIC_FALLBACK[tier]
        logger.info(
            "router_fallback",
            requested=f"{chosen.provider.value}:{chosen.model}",
            fallback=f"anthropic:{fallback_model}",
            reason="provider_not_keyed",
        )
        return RoutedModel(ModelProvider.ANTHROPIC, fallback_model, tier)

    def route_for_task(
        self,
        *,
        role: AgentRole,
        kind: TaskKind | None = None,
        complexity_points: int = 3,
        files_touched: int = 1,
    ) -> RoutedModel:
        tier = classify_complexity(
            role=role,
            kind=kind,
            complexity_points=complexity_points,
            files_touched=files_touched,
        )
        routed = self.route(tier)
        logger.info(
            "model_routed",
            role=role.value,
            tier=tier.value,
            model=f"{routed.provider.value}:{routed.model}",
        )
        return routed

    @staticmethod
    def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
        """Dollar cost of a call given token counts, from the price table."""
        prices = settings.model_prices.get(model)
        if not prices:
            return 0.0
        in_price, out_price = prices
        return (input_tokens / 1_000_000) * in_price + (output_tokens / 1_000_000) * out_price

    async def record(
        self,
        session: AsyncSession,
        *,
        routed: RoutedModel,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int = 0,
        project_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
        agent_role: AgentRole | None = None,
        purpose: str | None = None,
    ) -> ModelCall:
        """Persist a routed call to the economic ledger and return it."""
        cost = self.estimate_cost(routed.model, input_tokens, output_tokens)
        call = ModelCall(
            project_id=project_id,
            task_id=task_id,
            agent_role=agent_role,
            provider=routed.provider,
            model=routed.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
            purpose=purpose or routed.tier.value,
        )
        session.add(call)
        return call


# Shared singleton.
model_router = ModelRouter()
