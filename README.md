<div align="center">

# RiMo

### An autonomous AI software engineering company

**Ten specialist agents that plan, build, review, test, secure, and ship software around the clock.**

[Architecture](docs/architecture.md) · [Database Schema](docs/database-schema.md) · [Deployment](docs/deployment.md) · [Intelligence Layer](docs/intelligence-layer.md) · [Evidence](docs/evidence.md) · [ADRs](docs/adr/0004-server-sent-events.md#adr-index)

</div>

---

RiMo (Rishik Mora AI) accepts a project idea or a GitHub repository and operates on it like a real engineering org: a CEO agent sets the mission, a Planner breaks it into a dependency-ordered backlog, an Architect designs, a Builder writes the code, and Reviewer / QA / Security form a quality gate before anything is committed, PR'd, merged, or deployed — with a human in the loop at the high-risk boundaries. A Memory agent distills every run into durable, reusable knowledge.

This is a working system, not a mock: a resumable orchestration engine, a real Anthropic tool-calling loop, pgvector-backed long-term memory, GitHub integration, secret scanning, human-approval gates, and a live operations dashboard.

## The company

| Agent | Mandate |
|-------|---------|
| **CEO** | Mission planning, objectives, long-term strategy |
| **Research** | Documentation, prior art, competitor analysis |
| **Planner** | Roadmap → scoped, prioritized, dependency-aware tasks |
| **Architect** | System design and Architecture Decision Records |
| **Builder** | Writes and refactors production code |
| **Reviewer** | Code review with a 0–100 quality score |
| **QA** | Unit, integration, and E2E testing |
| **Security** | Vulnerability scans and secret detection |
| **DevOps** | Deployment, monitoring, rollbacks |
| **Memory** | Learns from every run; powers semantic recall |

## How it works

```
plan (CEO → Planner)
  └▶ per task, in priority order:
        architect → build → [review + qa + security] → commit → PR → merge* → deploy*
  └▶ learn (Memory)
                                              * gated by human approval
```

State lives in Postgres, tasks carry time-bound leases, and a single `tick()` advances one unit of work — so the worker can run 24/7 and self-heal from crashes. Full detail in [the architecture doc](docs/architecture.md).

## Intelligence layer

Beyond the ten-agent pipeline, RiMo ships a capability layer most agent systems lack — all real, tested, and wired into the running system ([full detail](docs/intelligence-layer.md)):

- **Knowledge graph** — a typed graph of every file, class, function, route, and table (AST + PageRank centrality) that agents query for blast radius before changing anything.
- **Multi-model routing** — every agent call is routed by complexity tier to the most cost-effective model, with a live cost ledger showing 70–90% savings vs. frontier-only.
- **Agent debate** — Architect → Reviewer → Security → QA challenge each other before code ships; blockers stop a merge.
- **Self-evolving prompts** — Thompson-sampling bandit over prompt variants, with weekly evolution of the champion.
- **Failure recovery** — autonomous diagnose → retry → rollback → escalate, with incident timelines.
- **Architecture refactoring** — graph-driven smell detection (God objects, cycles, hubs) → scoped refactor tasks.
- **Economic reasoning** — cost ledger, unit economics, routing savings, and a budget guard.
- **Autonomous benchmarking** — rejects latency/memory/bundle regressions before merge.
- **RiMo OS** — a fleet scheduler ranking the whole project portfolio by attention, plus a marketplace of hireable specialists (Flutter, ML, Next.js…) auto-matched to each stack.
- **Self-improvement loop** — weekly reflection that mines failures, evolves prompts, and writes lessons to memory.

## Tech stack

**Backend** — FastAPI · async SQLAlchemy 2.0 · PostgreSQL + pgvector · Redis · Anthropic Claude (Opus 4.8 + Haiku) · Alembic
**Frontend** — Next.js 16 · TypeScript · TailwindCSS · Server-Sent Events
**Infra** — Docker · Kubernetes · GitHub Actions CI/CD

## Quick start

```bash
cp .env.example .env          # set SECRET_KEY and ANTHROPIC_API_KEY
docker compose up --build
```

Then open the dashboard at **http://localhost:3000**, create a project, and click **Start company**. API docs are at **http://localhost:8000/docs**.

Other ways to run it (local dev with hot reload, full Kubernetes) are in the [deployment guide](docs/deployment.md).

## Repository layout

```
rimo/
├── backend/                 FastAPI app, agents, orchestrator, memory
│   ├── app/
│   │   ├── agents/          the ten specialists + registry + tools
│   │   ├── orchestration/   the autonomous loop, worker, event bus
│   │   ├── memory/          pgvector semantic memory
│   │   ├── integrations/    GitHub App client
│   │   ├── services/        LLM loop, embeddings, safety
│   │   ├── api/             auth, projects, resources, SSE events
│   │   └── models/          SQLAlchemy schema + enums
│   ├── migrations/          Alembic
│   └── tests/               pytest suite
├── frontend/                Next.js operations dashboard
│   └── src/
│       ├── app/             routes (operations, projects, floor, login)
│       ├── components/      agent floor, activity timeline, UI
│       └── lib/             typed API client
├── infra/k8s/               Kubernetes manifests
├── .github/workflows/       CI/CD pipeline
└── docs/                    architecture · schema · deployment
```

## Safety

RiMo is built to be trusted with real repositories:

- **Human-in-the-loop** approval gates for merge, deploy, and any destructive action (on by default).
- **Secret scanning** (pattern + entropy) on every staged change, with redaction.
- **Repository deletion disabled** platform-wide unless explicitly enabled — and even then it always requires approval.
- **A hard cap** on files changed per PR.
- Secrets are read from the environment / a vault and never committed.

## Development

```bash
# backend (tests need Postgres + Redis reachable; see docker compose up postgres redis -d)
cd backend && pip install -r requirements.txt -r requirements-dev.txt
ruff check app tests && pytest          # 74 tests, incl. orchestrator state-machine tests

# frontend
cd frontend && npm install
npm run typecheck && npm run lint && npm test && npm run build   # 9 component/client tests
```

The backend suite runs the orchestrator's state machine against a real Postgres —
lease reclaim, the approval gate, and the cost cap are proven, not just asserted
(see [docs/evidence.md](docs/evidence.md)). DB-dependent tests skip cleanly when
no database is reachable. See [CONTRIBUTING.md](CONTRIBUTING.md) for the full
workflow and [SECURITY.md](SECURITY.md) for the security model.

CI runs all of the above on every push, builds both Docker images, and pushes them to GHCR on `main`.

---

<div align="center">
<sub>Built by Rishik Mora.</sub>
</div>
