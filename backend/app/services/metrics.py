"""Agent- and orchestration-level metrics.

The HTTP layer is the least interesting thing to measure for an autonomous agent
system. What actually matters — and what anyone serious asks about first — is
whether the agents are working and not burning money: tokens and dollars per
role, task throughput and duration, approval-gate wait time, and LLM failure
rate. These are exposed on the same ``/metrics`` endpoint as the HTTP metrics.

All helpers degrade to no-ops if ``prometheus_client`` isn't installed, so
importing and calling them is always safe.
"""
from __future__ import annotations

from app.core.logging import get_logger

logger = get_logger(__name__)

try:
    from prometheus_client import Counter, Histogram

    _AGENT_TOKENS = Counter(
        "rimo_agent_tokens_total",
        "LLM tokens consumed per agent role",
        ["role", "kind"],  # kind = input | output
    )
    _AGENT_COST = Counter(
        "rimo_agent_cost_usd_total",
        "Estimated USD cost per agent role",
        ["role"],
    )
    _AGENT_RUNS = Counter(
        "rimo_agent_runs_total",
        "Agent executions per role and outcome",
        ["role", "outcome"],  # outcome = success | failure
    )
    _TASK_DURATION = Histogram(
        "rimo_task_duration_seconds",
        "Wall-clock duration of agent task execution",
        ["role"],
        buckets=(1, 5, 15, 30, 60, 120, 300, 600, 1800),
    )
    _LLM_FAILURES = Counter(
        "rimo_llm_call_failures_total",
        "LLM call failures (post-retry) per role",
        ["role"],
    )
    _APPROVAL_WAIT = Histogram(
        "rimo_approval_wait_seconds",
        "Time a high-risk action waited for human approval",
        ["kind"],
        buckets=(10, 30, 60, 300, 900, 3600, 14400, 86400),
    )
    _TASKS_COMPLETED = Counter(
        "rimo_tasks_completed_total",
        "Tasks reaching a terminal state",
        ["status"],  # done | failed
    )
    _AVAILABLE = True
except Exception:  # pragma: no cover - prometheus optional
    _AVAILABLE = False


def record_agent_run(
    *,
    role: str,
    success: bool,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    duration_seconds: float,
) -> None:
    """Record one agent execution's tokens, cost, outcome, and duration."""
    if not _AVAILABLE:
        return
    _AGENT_TOKENS.labels(role=role, kind="input").inc(input_tokens)
    _AGENT_TOKENS.labels(role=role, kind="output").inc(output_tokens)
    _AGENT_COST.labels(role=role).inc(cost_usd)
    _AGENT_RUNS.labels(role=role, outcome="success" if success else "failure").inc()
    _TASK_DURATION.labels(role=role).observe(duration_seconds)


def record_llm_failure(role: str) -> None:
    if _AVAILABLE:
        _LLM_FAILURES.labels(role=role).inc()


def record_approval_wait(kind: str, seconds: float) -> None:
    if _AVAILABLE:
        _APPROVAL_WAIT.labels(kind=kind).observe(seconds)


def record_task_completed(status: str) -> None:
    if _AVAILABLE:
        _TASKS_COMPLETED.labels(status=status).inc()
