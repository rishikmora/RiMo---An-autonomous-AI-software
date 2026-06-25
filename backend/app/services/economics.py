"""Economic reasoning.

RiMo tracks the dollar cost of its own work and reasons about ROI — something
most agents lack entirely. Every routed model call is logged to the
:class:`ModelCall` ledger; this service aggregates that ledger into spend by
project, agent, model, and time window, and turns it into decisions:

  * a per-project **budget guard** that can pause autonomous spend when a cap is
    hit (surfaced as an approval rather than a silent overrun);
  * **cost-per-outcome** (dollars per merged PR / completed task), the unit
    economics of the company;
  * **routing efficiency** — how much the multi-model router is saving versus a
    naive "everything on the frontier model" baseline.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models import ModelCall, PullRequest, Task
from app.models.enums import PullRequestStatus, TaskStatus

logger = get_logger(__name__)


@dataclass
class CostSummary:
    total_usd: float
    total_input_tokens: int
    total_output_tokens: int
    calls: int
    by_model: dict[str, float]
    by_agent: dict[str, float]
    cost_per_completed_task: float | None
    cost_per_merged_pr: float | None
    naive_baseline_usd: float          # cost if every call used the frontier model
    routing_savings_usd: float         # baseline - actual
    routing_savings_pct: float

    def to_dict(self) -> dict:
        return asdict(self)


class EconomicsService:
    """Aggregates the cost ledger and produces ROI signals and budget decisions."""

    async def project_summary(
        self, session: AsyncSession, *, project_id: uuid.UUID
    ) -> CostSummary:
        calls = (
            await session.execute(
                select(ModelCall).where(ModelCall.project_id == project_id)
            )
        ).scalars().all()

        total = sum(c.cost_usd for c in calls)
        in_tok = sum(c.input_tokens for c in calls)
        out_tok = sum(c.output_tokens for c in calls)

        by_model: dict[str, float] = {}
        by_agent: dict[str, float] = {}
        for c in calls:
            by_model[c.model] = by_model.get(c.model, 0.0) + c.cost_usd
            role = c.agent_role.value if c.agent_role else "system"
            by_agent[role] = by_agent.get(role, 0.0) + c.cost_usd

        # Unit economics.
        completed = (
            await session.execute(
                select(func.count())
                .select_from(Task)
                .where(Task.project_id == project_id, Task.status == TaskStatus.DONE)
            )
        ).scalar_one()
        merged = (
            await session.execute(
                select(func.count())
                .select_from(PullRequest)
                .where(
                    PullRequest.project_id == project_id,
                    PullRequest.status == PullRequestStatus.MERGED,
                )
            )
        ).scalar_one()

        # Routing efficiency vs. a frontier-only baseline.
        frontier = settings.default_model
        fin, fout = settings.model_prices.get(frontier, (15.0, 75.0))
        naive = sum(
            (c.input_tokens / 1_000_000) * fin + (c.output_tokens / 1_000_000) * fout
            for c in calls
        )
        savings = max(0.0, naive - total)
        savings_pct = (savings / naive * 100) if naive > 0 else 0.0

        return CostSummary(
            total_usd=round(total, 4),
            total_input_tokens=in_tok,
            total_output_tokens=out_tok,
            calls=len(calls),
            by_model={k: round(v, 4) for k, v in by_model.items()},
            by_agent={k: round(v, 4) for k, v in by_agent.items()},
            cost_per_completed_task=round(total / completed, 4) if completed else None,
            cost_per_merged_pr=round(total / merged, 4) if merged else None,
            naive_baseline_usd=round(naive, 4),
            routing_savings_usd=round(savings, 4),
            routing_savings_pct=round(savings_pct, 1),
        )

    async def spend_to_date(
        self, session: AsyncSession, *, project_id: uuid.UUID
    ) -> float:
        total = (
            await session.execute(
                select(func.coalesce(func.sum(ModelCall.cost_usd), 0.0)).where(
                    ModelCall.project_id == project_id
                )
            )
        ).scalar_one()
        return float(total)

    async def check_budget(
        self,
        session: AsyncSession,
        *,
        project_id: uuid.UUID,
        budget_usd: float,
    ) -> dict:
        """Decide whether autonomous spend should continue under a budget cap.

        Returns a decision dict; the orchestrator turns an `exceeded` result into
        an approval gate rather than silently overspending.
        """
        spent = await self.spend_to_date(session, project_id=project_id)
        remaining = budget_usd - spent
        exceeded = remaining <= 0
        ratio = spent / budget_usd if budget_usd > 0 else 0.0
        decision = {
            "budget_usd": round(budget_usd, 2),
            "spent_usd": round(spent, 4),
            "remaining_usd": round(remaining, 4),
            "utilization_pct": round(ratio * 100, 1),
            "exceeded": exceeded,
            "warning": 0.8 <= ratio < 1.0,
        }
        if exceeded:
            logger.warning("budget_exceeded", project=str(project_id), spent=spent, budget=budget_usd)
        return decision

    @staticmethod
    def evaluate_feature_roi(
        *,
        title: str,
        monthly_cost_usd: float,
        expected_monthly_revenue_usd: float = 0.0,
        build_cost_usd: float = 0.0,
        strategic_value: float = 0.0,
        confidence: float = 0.5,
    ) -> dict:
        """Decide whether a feature is worth building, like a founder would.

        Weighs recurring cost (hosting/API/GPU) and one-off build cost against
        expected revenue and a strategic-value term (0..1, for things that don't
        pay off immediately but matter — e.g. table-stakes features). Returns a
        recommendation with the reasoning, not just a number.

        The decision is deliberately conservative: a feature with real recurring
        cost and no revenue or strategic justification is rejected. Pure
        bean-counting is wrong for early products, so a high strategic_value can
        carry a feature that doesn't yet pay for itself.
        """
        # Expected monthly margin, discounted by confidence in the revenue est.
        expected_margin = expected_monthly_revenue_usd * confidence - monthly_cost_usd
        # Months to recoup the build cost from positive margin (if any).
        payback_months = (
            build_cost_usd / expected_margin if expected_margin > 0 and build_cost_usd > 0 else None
        )

        # Decision logic.
        if expected_margin > 0 and (payback_months is None or payback_months <= 12):
            decision = "build"
            reason = (
                f"Positive expected margin (${expected_margin:.0f}/mo)"
                + (f", payback in {payback_months:.1f} months." if payback_months else ".")
            )
        elif strategic_value >= 0.7:
            decision = "build"
            reason = (
                f"Not yet profitable (${expected_margin:.0f}/mo), but high strategic "
                f"value ({strategic_value:.0%}) justifies it (e.g. table stakes / retention)."
            )
        elif expected_margin <= 0 and strategic_value < 0.3 and monthly_cost_usd > 0:
            decision = "reject"
            reason = (
                f"Recurring cost ${monthly_cost_usd:.0f}/mo with negative expected "
                f"margin (${expected_margin:.0f}/mo) and low strategic value "
                f"({strategic_value:.0%}). Not worth it."
            )
        else:
            decision = "defer"
            reason = (
                "Marginal: neither clearly profitable nor strategically critical. "
                "Revisit when there's more signal on demand or revenue."
            )

        return {
            "feature": title,
            "decision": decision,
            "reason": reason,
            "expected_monthly_margin_usd": round(expected_margin, 2),
            "payback_months": round(payback_months, 1) if payback_months else None,
            "inputs": {
                "monthly_cost_usd": monthly_cost_usd,
                "expected_monthly_revenue_usd": expected_monthly_revenue_usd,
                "build_cost_usd": build_cost_usd,
                "strategic_value": strategic_value,
                "confidence": confidence,
            },
        }


economics = EconomicsService()
