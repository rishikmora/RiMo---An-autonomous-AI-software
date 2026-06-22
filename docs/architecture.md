# RiMo — System Architecture

RiMo (Rishik Mora AI) is an autonomous, multi-agent software engineering platform. Ten specialist agents plan, build, review, test, secure, ship, and learn — coordinated by a resumable orchestration engine that turns a project mission into shipped software with human approval at the high-risk boundaries.

This document covers the system's shape: the agents, the orchestration loop, the data model, the memory subsystem, the GitHub integration, and how the processes fit together.

---

## 1. High-level topology

```
                         ┌──────────────────────────┐
                         │   Next.js Dashboard       │
                         │   (operations console)    │
                         └────────────┬─────────────┘
                                      │ HTTPS + SSE
                         ┌────────────▼─────────────┐
                         │      FastAPI API          │  ← stateless, horizontally scalable
                         │  auth · projects · events │
                         └──────┬──────────────┬─────┘
                                │              │
                  ┌─────────────▼───┐    ┌─────▼──────────┐
                  │  PostgreSQL      │    │     Redis       │
                  │  + pgvector      │    │  event bus +    │
                  │  (state + memory)│    │  pub/sub fanout │
                  └─────────▲────────┘    └─────▲──────────┘
                            │                   │
                  ┌─────────┴───────────────────┴─────────┐
                  │        Autonomous Worker                │  ← the 24/7 loop
                  │  Orchestrator.tick() per project        │
                  │  drives the ten agents through stages   │
                  └─────────────────┬───────────────────────┘
                                    │
                            ┌───────▼────────┐
                            │  GitHub (App)   │  clone · commit · PR · merge
                            └─────────────────┘
                                    │
                            ┌───────▼────────┐
                            │  Anthropic API  │  Claude Opus 4.8 / Haiku
                            └─────────────────┘
```

Three runtime processes share one codebase and database:

1. **API** (`uvicorn app.main:app`) — serves the dashboard, authentication, project CRUD, and the SSE activity stream. Stateless; scale horizontally behind the HPA.
2. **Worker** (`python -m app.orchestration.worker`) — the continuous loop. Every cycle it advances each running project by one `tick()`, reclaims expired task leases, and refreshes agent heartbeats. Single replica by design (work is coordinated through DB leases).
3. **Migration job** — enables the `vector` extension and runs Alembic to head before API/worker start.

---

## 2. The ten agents

Each agent is a stateless service with a `role`, a `system_prompt` encoding its mandate and output contract, and an `execute()` method that runs a tool-calling reasoning loop. All durable state lives in the database and the memory subsystem; agents never hold state between runs.

| Agent | Mandate | Model | Output |
|-------|---------|-------|--------|
| **CEO** | Mission planning, objectives, long-term strategy | Opus | `{mission, objectives[], strategic_summary}` |
| **Research** | Docs, prior art, competitor analysis | Opus | `{findings[], recommendation, risks[]}` |
| **Planner** | Roadmap → dependency-ordered, scoped tasks | Opus | `{tasks[]}` with criteria, complexity, role |
| **Architect** | System design, ADRs, technology choices | Opus | `{decision, options_considered[], consequences[]}` |
| **Builder** | Writes and refactors production code | Opus | Staged file changes + tests |
| **Reviewer** | Code review, quality scoring (0–100) | Opus | `{score, verdict, issues[], strengths[]}` |
| **QA** | Unit / integration / E2E testing | Opus | Test results + new tests |
| **Security** | Vulnerability scans, secret detection | Opus | `{findings[], severity}` |
| **DevOps** | Deploy, monitor, roll back | Opus | Deployment outcome |
| **Memory** | Distills runs into durable, reusable lessons | Haiku | `{memories[]}` |

The Memory agent uses the cheaper, faster model because curation is high-volume and lower-stakes; everything else uses Opus for reasoning quality. Model selection is a single field (`BaseAgent.model`) — swapping is trivial.

### The reasoning loop

Every agent runs the same canonical loop (`app/services/llm.py::AgentLoop`):

```
prompt → model → [tool calls?] ──yes──▶ dispatch tools → feed results back ─┐
                       │                                                     │
                       no                                          (repeat) ◀┘
                       ▼
                  final answer
```

The loop drives the model until it returns a turn with no tool use (the final answer) or the iteration budget is exhausted. Tool dispatch is async, errors surface back to the model as tool results, and rate limits trigger exponential backoff. This is provider-shaped, not provider-locked.

---

## 3. The orchestration engine

`app/orchestration/orchestrator.py` is the loop that turns a mission into shipped software. It coordinates the agents through a deterministic pipeline while the agents handle the open-ended reasoning within each stage:

```
plan (CEO → Planner)
  └▶ for each ready task, in priority/dependency order:
        architect   (design-bearing tasks only)
        build       (Builder stages changes)
        ┌─ review   (Reviewer scores 0–100)        ┐
        ├─ qa       (QA runs/writes tests)         ├─ quality gate
        └─ security (Security scans + secrets)     ┘
        commit + push + open PR
        merge        (guarded by Approval)
        deploy       (DevOps, guarded by Approval)
  └▶ learn (Memory distills the run into knowledge)
```

**Resumability.** State lives in the database, tasks carry time-bound leases, and a single `tick()` advances one unit of work. If the worker crashes mid-task, the lease expires and the task returns to `ready` for retry. This is what makes "operate 24/7 with minimal human intervention" real rather than aspirational.

**Quality gate.** A PR only proceeds to merge when checks pass *and* the review score clears the threshold (default 80). Below that, the orchestrator loops back to the Builder with the reviewer's issues.

**Human-in-the-loop.** Merge, deploy, repository deletion, and destructive migrations create an `Approval` row and pause. The `ActionGuard` (`app/services/safety.py`) decides what may proceed autonomously based on autonomy level and platform policy. Defaults require human approval for both merge and deploy.

---

## 4. Data model

Normalized around five aggregates (full column-level detail in [`database-schema.md`](./database-schema.md)):

```
Project ──< Task ──< AgentRun          (execution attempts, with transcripts)
   │         │
   │         └──> PullRequest ──> Deployment
   │
   ├──< Agent          (per-project instance of each of the 10 roles)
   ├──< MemoryRecord   (pgvector-indexed knowledge)
   ├──< Approval       (human-in-the-loop gates)
   └──< ActivityEvent  (append-only stream powering the timeline)
```

`MemoryRecord.embedding` is a `vector(1536)` column with an HNSW index (`vector_cosine_ops`) for fast semantic recall.

---

## 5. Memory subsystem

`app/memory/service.py` gives the company institutional knowledge that survives across tasks and projects.

- **Write.** After a task completes, the Memory agent distills the run into 0–5 durable memories (architecture decisions, bug fixes, user preferences, lessons learned). Each is embedded and stored.
- **Read.** Before any agent runs, the orchestrator builds a context block by semantically recalling the most relevant memories for the task — so a future agent with no context can apply what was learned before.
- **Retention.** Memories carry an `importance` score and an `access_count`; pruning keeps the highest-value records.

**Embeddings.** The default provider calls OpenAI's `text-embedding-3-small`. With no `OPENAI_API_KEY`, the system falls back to a deterministic, dependency-free hashing embedder that preserves dimensionality — so RiMo stays fully functional offline and in tests, just with lower semantic richness.

---

## 6. GitHub integration

`app/integrations/github.py` wraps the GitHub App flow: clone, read structure, create branches, commit files, open PRs, request reviews, and merge. The codebase analyzer (`app/orchestration/analyzer.py`) reads a repository's structure and produces the architecture summary the strategy agents reason over.

**Safety rails** are enforced before anything touches a real repo:
- Secret scanning on every staged change (pattern + entropy based), with redaction.
- A hard cap on files changed per PR.
- Repository deletion disabled platform-wide by default; always requires approval even when enabled.

---

## 7. Real-time dashboard

The Next.js dashboard is an operations console, not an admin panel. Its signature is **the floor** — the ten agents rendered as role-coded cards with live, breathing status. The activity timeline streams over **Server-Sent Events**: the orchestrator emits events → persisted to `activity_events` → fanned out through the Redis-backed `EventBus` → delivered to every connected `EventSource`. SSE (not WebSockets) because the stream is unidirectional and reconnection is free.

---

## 8. Observability

- **Structured logging** (`structlog`) — JSON in production, keyed events throughout.
- **Prometheus** `/metrics` — request counts and latencies via middleware.
- **Health** `/health` (liveness) and `/ready` (readiness, checks the DB) for orchestrators.
- **Per-request timing** via the `X-Process-Time-Ms` header.

---

## 9. Technology choices, briefly

| Layer | Choice | Why |
|-------|--------|-----|
| API | FastAPI + async SQLAlchemy 2.0 | Native async, typed, fast |
| DB | PostgreSQL + pgvector | One store for state *and* semantic memory |
| Cache/bus | Redis | Event fan-out + future task queue |
| AI | Claude Opus 4.8 / Haiku | Reasoning quality; cheap curation |
| Frontend | Next.js 16 + TS + Tailwind | Standalone output, type safety |
| Infra | Docker · Kubernetes · GitHub Actions | Portable, autoscaling, CI/CD |

See [`deployment.md`](./deployment.md) to run it.
