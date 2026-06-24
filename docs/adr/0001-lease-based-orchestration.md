# ADR 0001 — Lease-based orchestration instead of a task queue

**Status:** Accepted
**Date:** 2026-01

## Context

RiMo must advance many long-running, multi-step projects "24/7 with minimal
human intervention" and survive worker crashes mid-task. The obvious default is
a distributed task queue (Celery/RQ/Arq) where each step is a queued job.

## Decision

Use **database-backed leases** with a single-stepping `tick()` instead of an
external task queue. State lives entirely in Postgres; each task carries a
`lease_expires_at`. A worker claims a task by setting the lease, and one `tick()`
advances exactly one unit of work. A separate sweep resets `IN_PROGRESS` tasks
whose lease has expired back to `READY`.

## Rationale

- **Crash recovery is automatic and needs no broker.** If a worker dies between
  ticks, the lease lapses and the task is reclaimed on the next cycle. With a
  task queue we'd need acks, visibility timeouts, and a dead-letter strategy to
  get the same property — more moving parts for the same outcome.
- **One source of truth.** Project/task/agent state is already in Postgres for
  the dashboard. Putting execution state there too means no queue/DB consistency
  problems and one place to inspect "what is the system doing right now."
- **Resumability is trivial.** Because the unit of progress is a single `tick()`
  over persisted state, the system is inherently resumable; there is no in-memory
  progress to lose.
- **Testability.** The headline resilience claims are provable as fast unit
  tests against the database (see `test_orchestrator.py::test_expired_lease_is_reclaimed`),
  which would be far harder to assert against a live broker.

## Consequences

- We don't get a queue's built-in fan-out/priority machinery for free; we
  implement task selection (`next_task`, priority + dependency ordering) in SQL.
- Throughput is bounded by how often workers tick and by `max_concurrent_projects`.
  For RiMo's workload (a handful of projects, each step taking seconds–minutes of
  model time) this is a non-issue; if it ever became one, a queue could sit *in
  front of* the lease model without changing the state machine.
- Long leases risk a slow task being reclaimed prematurely; `task_lease_seconds`
  is tuned with headroom and renewed on the active step.

## Alternatives considered

- **Celery + Redis broker.** Mature, but adds a broker, result backend, and
  ack/visibility semantics to re-implement crash recovery we get for free here.
- **Temporal / durable execution engine.** Excellent fit conceptually, but a
  heavy external dependency for a system that already has a database and modest
  scale needs.
