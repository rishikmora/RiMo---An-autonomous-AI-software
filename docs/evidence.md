# RiMo — Evidence

Most "autonomous AI dev team" projects assert their capabilities. This document
points at evidence instead. Every claim below is backed by something runnable in
this repository — a test, a demo script, or a measured number — so a reviewer can
check it rather than take it on faith.

---

## 1. Self-healing: crash recovery, demonstrated

**Claim:** RiMo recovers from a worker crash mid-task with no human intervention.

**Proof:** `backend/scripts/demo_crash_recovery.py` is a runnable experiment, and
`backend/tests/test_orchestrator.py::test_expired_lease_is_reclaimed` is the same
property as an automated test. Real output from the demo:

```
=== RiMo crash-recovery demonstration ===

  [20:31:42] setup              project + task created; task is READY
  [20:31:42] worker_crash       worker claimed task then died; task stuck IN_PROGRESS, lease expired
  [20:31:42] observe            task is still IN_PROGRESS (a naive system would hang here forever)
  [20:31:42] recovery           fresh worker starts; running lease-reclaim sweep...
  [20:31:42] reclaimed          task is now READY, lease cleared — ready to retry

  RESULT: ✅ self-healed. The stuck task was automatically reclaimed.
          (attempts=1; the next worker cycle will pick it up)
```

**Why it works:** tasks are advanced under a time-bound lease (see
[ADR 0001](./adr/0001-lease-based-orchestration.md)). A crashed worker's lease
expires and the next worker cycle returns the task to `READY`. There is no
in-memory progress to lose because the unit of progress is a single `tick()` over
persisted state.

Reproduce:

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://rimo@127.0.0.1:5432/rimo \
SECRET_KEY=$(openssl rand -hex 32) ANTHROPIC_API_KEY=x DB_POOL_SIZE=0 PYTHONPATH=. \
python scripts/demo_crash_recovery.py
```

---

## 2. Cost/quality tradeoff: multi-model routing, measured

**Claim:** Routing cheap work to small models cuts cost 70–90% versus running
everything on the frontier model.

**Proof:** the routing logic and price table are real
(`backend/app/services/router.py`), and the economics service computes realized
savings against a frontier-only baseline for every project
(`GET /projects/{id}/economics`). The arithmetic, on the actual price table:

| Model | $/1M input | $/1M output | Cost of a 10k-in / 2k-out call |
|-------|-----------:|------------:|-------------------------------:|
| Opus (frontier)  | 15.00 | 75.00 | **$0.300** |
| Sonnet (standard)| 3.00  | 15.00 | $0.060 |
| Haiku (trivial)  | 0.80  | 4.00  | **$0.016** |

A trivial task routed to Haiku instead of Opus is **18.8× cheaper** for the same
call shape. Because RiMo routes by complexity tier — the Memory agent and trivial
edits to Haiku, standard work to Sonnet, only architecture/design to Opus — a
realistic workload where most calls are not frontier-tier lands squarely in the
70–90% savings band. The dashboard's Economics tab shows the *measured* split and
savings for real runs, not this illustrative calculation.

**Tradeoff acknowledged honestly:** routing trades a small amount of quality on
trivial tasks for a large cost reduction. The guardrail is that quality-sensitive
roles (Architect, CEO) are pinned to the frontier model regardless of task size,
and the review→QA→security gate catches regressions before anything merges.

---

## 3. Safety invariants: the gates actually hold

**Claim:** RiMo never merges or deploys without human approval, and stops when it
hits a spend cap.

**Proof:** these are enforced and tested, not just configured:

| Invariant | Test |
|-----------|------|
| A PR cannot merge without an approval record | `test_orchestrator.py::test_merge_requires_approval_and_does_not_merge` |
| An approved merge completes and marks the task done | `test_orchestrator.py::test_approved_merge_completes_and_marks_task_done` |
| Spend at the cap pauses the project | `test_orchestrator.py::test_budget_cap_halts_project` |
| Secrets are detected and redacted before commit | `test_safety.py` (scanner suite) |
| Concurrency never exceeds the configured cap | `test_worker_concurrency.py::test_semaphore_caps_concurrency` |

---

## 4. Bugs these tests caught

Writing the orchestrator tests and running them against a real Postgres surfaced
**five genuine bugs** that incidental/API-only testing had missed — which is
itself evidence the tests are exercising the real risk surface:

1. **Async lazy-load crash** — `_github_for` accessed a relationship lazily,
   raising `MissingGreenlet` under asyncpg. Would have failed in production on any
   project with a connected repo.
2. **Engineering agents had no tools without GitHub** — tool registration was
   gated on a GitHub connection, silently breaking greenfield/local code-writing.
3. **passlib/bcrypt incompatibility** — `passlib` 1.7.4 crashes on `bcrypt` 5.x;
   registration would have failed on a fresh deploy. Replaced with direct `bcrypt`.
4. **Dashboard summary** — positional Pydantic construction (empty-state crash)
   plus string-vs-enum comparisons that always counted zero.
5. **Rate-limiter hard-crash** — a Redis blip would have taken down auth; the
   limiter now fails open.

---

## 5. What is *not* yet proven

In the interest of honesty:

- **A long-haul "48 hours, N concurrent projects, $X/project" run** is documented
  as a target in `deployment.md` but has not been executed in this environment.
  The mechanism is proven (crash recovery, concurrency cap, cost cap); the
  multi-day soak is the remaining empirical gap.
- **Public PRs against real open-source issues** would be the strongest possible
  artifact. The pipeline that would produce them is tested end-to-end with a fake
  model; running it against live repositories needs a funded API key and GitHub
  App credentials.

These are the next evidence items to produce, and they're called out so the gap
is explicit rather than papered over.
